from __future__ import annotations

import concurrent.futures
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import prontuario_verde_booking_queue as queue


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def request_payload(operation="book", **overrides):
    now = datetime.now(timezone.utc)
    # Keep the appointment on one calendar day regardless of test run time.
    start = (now + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=40)
    confirmation = {
        "chat_id": "5511999999999@s.whatsapp.net",
        "message_id": "inbound-confirm-1",
        "offer_id": "offer-opaque-1",
        "slot_id": "slot-opaque-1",
        "requested_start": iso(start),
        "requested_end": iso(end),
        "offer_expires_at": iso(now + timedelta(minutes=5)),
        "confirmed_at": iso(now - timedelta(seconds=1)),
        "explicit": True,
        "kind": "offer_acceptance",
    }
    payload = {
        "operation": operation,
        "idempotency_key": "5511999999999:inbound-confirm-1",
        "chat_id": "5511999999999@s.whatsapp.net",
        "patient_id": "81",
        "professional_id": "22",
        "professional_key": "liliane",
        "appointment_type": "evaluation",
        "policy_context": {
            "established_patient": False,
            "in_treatment": False,
            "no_added_procedure": False,
            "chart_verified": False,
        },
        "unit_id": "4",
        "type_id": "44",
        "duration_min": 40,
        "requested_start": iso(start),
        "requested_end": iso(end),
        "clinic_id": "clinic-a",
        "source_clinic_hash": "a" * 64,
        "confirmation": confirmation,
        "created_at": iso(now),
    }
    if operation == "reschedule":
        payload.update({
            "appointment_id": "55",
            "expected_start": iso(start + timedelta(days=1)),
            "expected_end": iso(start + timedelta(days=1, minutes=40)),
            "original_verified_at": iso(now - timedelta(seconds=30)),
        })
    payload.update(overrides)
    return payload


def verified_result(payload):
    proof = {
        "status": "verified",
        "appointment_id": payload.get("appointment_id", "91"),
        "patient_id": payload["patient_id"],
        "professional_id": payload["professional_id"],
        "unit_id": payload["unit_id"],
        "type_id": payload["type_id"],
        "procedure_id": payload["procedure_id"],
        "duration_min": payload["duration_min"],
        "start": payload["requested_start"],
        "end": payload["requested_end"],
        "verified_at": iso(datetime.now(timezone.utc)),
        "clinic_id": payload["clinic_id"],
        "source_clinic_hash": payload["source_clinic_hash"],
    }
    if payload["operation"] == "reschedule":
        proof.update({
            "old_appointment_id": payload["appointment_id"],
            "old_patient_id": payload["patient_id"],
            "old_professional_id": payload["professional_id"],
            "old_unit_id": payload["unit_id"],
            "old_type_id": payload["type_id"],
            "old_procedure_id": payload["procedure_id"],
            "old_duration_min": payload["duration_min"],
            "old_start": payload["expected_start"],
            "old_end": payload["expected_end"],
            "old_appointment_active": False,
        })
    return proof


class ProntuarioVerdeBookingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "spool"
        queue.initialize(self.root)

    def enqueue(self, payload=None):
        payload = payload or request_payload()
        if payload["operation"] == "reschedule":
            return queue.enqueue_reschedule(self.root, payload)
        return queue.enqueue_booking(self.root, payload)

    def test_enqueue_persists_confirmed_job_with_private_mode_and_safe_public_result(self):
        payload = request_payload()
        queued = self.enqueue(payload)
        path = self.root / "pending" / f"{queued['request_id']}.json"
        stored = json.loads(path.read_text())
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertNotIn("idempotency_key", stored)
        self.assertNotIn("text", stored["confirmation"])
        pending = queue.get_result(self.root, queued["request_id"])
        self.assertEqual(pending["status"], "pending")
        self.assertNotIn("patient_id", pending)
        self.assertNotIn("chat_id", pending)

    def test_requires_explicit_same_chat_current_unexpired_offer_confirmation(self):
        payload = request_payload()
        payload["confirmation"]["explicit"] = False
        with self.assertRaises(ValueError):
            self.enqueue(payload)
        payload = request_payload()
        payload["confirmation"]["chat_id"] = "different-chat"
        with self.assertRaises(ValueError):
            self.enqueue(payload)
        payload = request_payload()
        payload["confirmation"]["requested_start"] = iso(datetime.now(timezone.utc) + timedelta(days=10))
        with self.assertRaises(ValueError):
            self.enqueue(payload)

    def test_rejects_expired_or_long_lived_offer_and_malformed_payload(self):
        payload = request_payload()
        payload["confirmation"]["offer_expires_at"] = iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.enqueue(payload)
        payload = request_payload()
        payload["confirmation"]["offer_expires_at"] = iso(datetime.now(timezone.utc) + timedelta(minutes=20))
        with self.assertRaises(ValueError):
            self.enqueue(payload)
        with self.assertRaises(ValueError):
            self.enqueue({**request_payload(), "unexpected": "field"})

    def test_pv_ids_must_be_positive_numeric_and_slot_must_be_future(self):
        for field, invalid in (("patient_id", "patient-81"), ("professional_id", "0"), ("unit_id", "4A"), ("type_id", "evaluation"), ("procedure_id", "service-17")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.enqueue(request_payload(**{field: invalid}))
        payload = request_payload(procedure_id=None)
        self.assertEqual(self.enqueue(payload)["status"], "pending")
        past = datetime.now(timezone.utc) - timedelta(minutes=2)
        payload = request_payload(requested_start=iso(past), requested_end=iso(past + timedelta(minutes=40)))
        payload["confirmation"].update({"requested_start": payload["requested_start"], "requested_end": payload["requested_end"]})
        with self.assertRaises(ValueError):
            self.enqueue(payload)

    def test_idempotency_deduplicates_retries_and_rejects_key_reuse_for_different_job(self):
        payload = request_payload()
        first = self.enqueue(payload)
        duplicate = self.enqueue(payload)
        self.assertEqual(duplicate["request_id"], first["request_id"])
        self.assertTrue(duplicate["deduplicated"])
        changed = request_payload()
        changed["requested_start"] = iso(datetime.now(timezone.utc) + timedelta(days=5))
        changed["requested_end"] = iso(datetime.fromisoformat(changed["requested_start"].replace("Z", "+00:00")) + timedelta(minutes=40))
        changed["confirmation"]["requested_start"] = changed["requested_start"]
        changed["confirmation"]["requested_end"] = changed["requested_end"]
        with self.assertRaisesRegex(ValueError, "idempotency key conflict"):
            self.enqueue(changed)

    def test_concurrent_retries_create_only_one_job(self):
        payload = request_payload()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.enqueue(payload), range(8)))
        self.assertEqual(len({item["request_id"] for item in results}), 1)
        self.assertEqual(sum(not item["deduplicated"] for item in results), 1)
        self.assertEqual(len(list((self.root / "pending").glob("*.json"))), 1)

    def test_claim_expiry_and_worker_restart_never_requeue_uncertain_write(self):
        queued = self.enqueue()
        claimed = queue.claim_next(self.root)
        self.assertEqual(claimed["request_id"], queued["request_id"])
        queue.initialize(self.root)
        result = queue.get_result(self.root, queued["request_id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "worker_restarted")
        self.assertIsNone(queue.claim_next(self.root))

    def test_claim_moves_elapsed_or_tampered_pending_jobs_to_review(self):
        queued = self.enqueue()
        path = self.root / "pending" / f"{queued['request_id']}.json"
        payload = json.loads(path.read_text())
        past = iso(datetime.now(timezone.utc) - timedelta(minutes=1))
        payload["requested_start"] = past
        payload["requested_end"] = iso(datetime.fromisoformat(past.replace("Z", "+00:00")) + timedelta(minutes=40))
        path.write_text(json.dumps(payload))
        self.assertIsNone(queue.claim_next(self.root))
        result = queue.get_result(self.root, queued["request_id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "slot_elapsed_before_attempt")

        queued = self.enqueue(request_payload(idempotency_key="tampered-record"))
        path = self.root / "pending" / f"{queued['request_id']}.json"
        payload = json.loads(path.read_text())
        payload["request_fingerprint"] = "0" * 64
        path.write_text(json.dumps(payload))
        self.assertIsNone(queue.claim_next(self.root))
        self.assertEqual(queue.get_result(self.root, queued["request_id"])["code"], "invalid_request")

    def test_enqueue_fails_closed_on_corrupt_history(self):
        corrupt = self.root / "results" / "deadbeef.json"
        corrupt.write_text("{")
        with self.assertRaisesRegex(ValueError, "queue history requires review"):
            self.enqueue()

    def test_success_requires_matching_verified_live_result(self):
        queued = self.enqueue()
        queue.claim_next(self.root)
        result = queue.finish(self.root, queued["request_id"], "succeeded", "booked", verified_result={"status": "verified"})
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "verification_mismatch")

        queued = self.enqueue(request_payload(idempotency_key="another-message"))
        payload = queue.claim_next(self.root)
        proof = verified_result(payload)
        success = queue.finish(self.root, queued["request_id"], "succeeded", "booked", proof)
        self.assertEqual(success["status"], "succeeded")
        self.assertEqual(success["appointment"]["start"], payload["requested_start"])
        self.assertNotIn("appointment_id", success["appointment"])

    def test_reschedule_accepts_new_unique_id_but_requires_old_inactive_proof(self):
        payload = request_payload("reschedule")
        queued = self.enqueue(payload)
        claim = queue.claim_next(self.root)
        proof = verified_result(claim)
        proof["appointment_id"] = "56"
        result = queue.finish(self.root, queued["request_id"], "succeeded", "rescheduled", proof)
        self.assertEqual(result["status"], "succeeded")

        payload = request_payload("reschedule", idempotency_key="reschedule-confirm-2")
        queued = self.enqueue(payload)
        claim = queue.claim_next(self.root)
        proof = verified_result(claim)
        proof["old_appointment_active"] = True
        result = queue.finish(self.root, queued["request_id"], "succeeded", "rescheduled", proof)
        self.assertEqual(result["status"], "needs_review")

    def test_reconciliation_can_confirm_write_or_verified_absence_without_retry(self):
        queued = self.enqueue()
        claimed = queue.claim_next(self.root)
        uncertain = queue.finish(self.root, queued["request_id"], "needs_review", "browser_timeout")
        self.assertEqual(uncertain["status"], "needs_review")
        reconciled = queue.reconcile(self.root, queued["request_id"], verified_result(claimed))
        self.assertEqual(reconciled["status"], "succeeded")
        self.assertEqual(reconciled["code"], "reconciled_verified")
        self.assertIsNone(queue.claim_next(self.root))

        queued = self.enqueue(request_payload(idempotency_key="another-reconcile"))
        claimed = queue.claim_next(self.root)
        queue.finish(self.root, queued["request_id"], "needs_review", "write_uncertain")
        evidence = {
            "status": "absent",
            "patient_id": claimed["patient_id"],
            "professional_id": claimed["professional_id"],
            "unit_id": claimed["unit_id"],
            "type_id": claimed["type_id"],
            "procedure_id": claimed["procedure_id"],
            "clinic_id": claimed["clinic_id"],
            "source_clinic_hash": claimed["source_clinic_hash"],
            "requested_start": claimed["requested_start"],
            "requested_end": claimed["requested_end"],
            "checked_at": iso(datetime.now(timezone.utc)),
        }
        result = queue.reconcile(self.root, queued["request_id"], evidence)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "verified_not_booked")
        self.assertIsNone(queue.claim_next(self.root))

    def test_reschedule_absence_reconciliation_requires_original_to_remain_active(self):
        payload = request_payload("reschedule")
        queued = self.enqueue(payload)
        claimed = queue.claim_next(self.root)
        queue.finish(self.root, queued["request_id"], "needs_review", "write_uncertain")
        evidence = {
            "status": "absent",
            "patient_id": claimed["patient_id"],
            "professional_id": claimed["professional_id"],
            "unit_id": claimed["unit_id"],
            "type_id": claimed["type_id"],
            "procedure_id": claimed["procedure_id"],
            "clinic_id": claimed["clinic_id"],
            "source_clinic_hash": claimed["source_clinic_hash"],
            "requested_start": claimed["requested_start"],
            "requested_end": claimed["requested_end"],
            "checked_at": iso(datetime.now(timezone.utc)),
            "old_appointment_active": True,
            "old_appointment_id": claimed["appointment_id"],
            "old_patient_id": claimed["patient_id"],
            "old_professional_id": claimed["professional_id"],
            "old_unit_id": claimed["unit_id"],
            "old_type_id": claimed["type_id"],
            "old_procedure_id": claimed["procedure_id"],
            "old_duration_min": claimed["duration_min"],
            "old_start": claimed["expected_start"],
            "old_end": claimed["expected_end"],
        }
        result = queue.reconcile(self.root, queued["request_id"], evidence)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "verified_not_booked")

        payload = request_payload("reschedule", idempotency_key="reschedule-confirm-3")
        queued = self.enqueue(payload)
        claimed = queue.claim_next(self.root)
        queue.finish(self.root, queued["request_id"], "needs_review", "write_uncertain")
        evidence["old_appointment_active"] = False
        result = queue.reconcile(self.root, queued["request_id"], evidence)
        self.assertEqual(result["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
