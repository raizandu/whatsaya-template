from __future__ import annotations

import concurrent.futures
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import prontuario_verde_onboarding as onboarding  # noqa: E402


PHONE = "5511987654321"
HASH = "a" * 64


def request(**changes):
    values = {
        "chat_id": f"{PHONE}@s.whatsapp.net",
        "name": "Anthony Aya",
        "clinic_id": "cuidar-odontologia",
        "source_clinic_hash": HASH,
        "source_message_id": "wamid-123",
    }
    values.update(changes)
    return values


class OnboardingQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "registrations"
        onboarding.initialize(self.root)

    def test_enqueue_and_public_lookup_exclude_contact_data(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        self.assertEqual(queued["status"], "pending")
        self.assertFalse(queued["deduplicated"])
        self.assertEqual(
            onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)["status"],
            "pending",
        )
        public = onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)
        self.assertTrue({"request_id", "status", "code", "created_at", "updated_at", "source_clinic_hash"} <= set(public))
        self.assertFalse({"name", "phone", "chat_id", "source_message_id", "patient_id"} & set(public))

    def test_phone_aliases_dedupe_through_pending_running_and_completed(self):
        first = onboarding.enqueue_registration(self.root, **request())
        alias = onboarding.enqueue_registration(
            self.root,
            **request(chat_id="(11) 8765-4321", source_message_id="wamid-456"),
        )
        self.assertTrue(alias["deduplicated"])
        self.assertEqual(alias["request_id"], first["request_id"])
        claimed = onboarding.claim_next(self.root)
        self.assertEqual(claimed["status"], "running")
        duplicate_running = onboarding.enqueue_registration(self.root, **request())
        self.assertEqual(duplicate_running["request_id"], first["request_id"])
        self.assertEqual(duplicate_running["status"], "running")

        done = onboarding.finish(self.root, first["request_id"], "succeeded", "registered", "882")
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["patient_id"], "882")
        duplicate_done = onboarding.enqueue_registration(self.root, **request())
        self.assertEqual(duplicate_done["request_id"], first["request_id"])
        self.assertEqual(duplicate_done["status"], "succeeded")
        contact = onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)
        self.assertNotIn("patient_id", contact)

    def test_concurrent_claim_returns_a_job_once(self):
        onboarding.enqueue_registration(self.root, **request())
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda _: onboarding.claim_next(self.root), range(8)))
        self.assertEqual(sum(job is not None for job in claimed), 1)

    def test_worker_startup_quarantines_running_job_without_replay(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        onboarding.claim_next(self.root)
        onboarding.initialize(self.root)
        result = onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)
        self.assertEqual(result["request_id"], queued["request_id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "worker_restarted")
        self.assertEqual(onboarding.claim_next(self.root), None)

    def test_claim_expires_stale_pending_job_to_review(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        path = self.root / "pending" / f"{queued['request_id']}.json"
        job = json.loads(path.read_text())
        job["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
        path.write_text(json.dumps(job))
        self.assertIsNone(onboarding.claim_next(self.root))
        state = onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["code"], "expired_before_attempt")

    def test_clinic_and_source_hash_bind_dedupe_identity(self):
        one = onboarding.enqueue_registration(self.root, **request())
        other_clinic = onboarding.enqueue_registration(
            self.root, **request(clinic_id="other-clinic"),
        )
        other_source = onboarding.enqueue_registration(
            self.root, **request(source_clinic_hash="b" * 64),
        )
        self.assertEqual(len({one["request_id"], other_clinic["request_id"], other_source["request_id"]}), 3)
        self.assertEqual(
            onboarding.get_for_contact(self.root, "cuidar-odontologia", PHONE)["status"],
            "needs_review",
        )

    def test_enqueue_initializes_without_quarantining_existing_running_job(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        onboarding.claim_next(self.root)
        again = onboarding.enqueue_registration(self.root, **request(source_message_id="wamid-next"))
        self.assertEqual(again["request_id"], queued["request_id"])
        self.assertEqual(again["status"], "running")

    def test_malformed_or_tampered_pending_payload_is_rejected(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        path = self.root / "pending" / f"{queued['request_id']}.json"
        job = json.loads(path.read_text())
        job["phone"] = "5511999999999"
        path.write_text(json.dumps(job))
        with self.assertRaises(onboarding.RegistrationStoreError) as caught:
            onboarding.claim_next(self.root)
        self.assertEqual(caught.exception.code, "store_corrupt")

    def test_invalid_request_fields_are_rejected(self):
        for changes in (
            {"chat_id": "123456789@lid"},
            {"name": "\n"},
            {"name": "x" * 101},
            {"source_clinic_hash": "invalid"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                onboarding.enqueue_registration(self.root, **request(**changes))

    def test_store_directories_and_files_are_private(self):
        queued = onboarding.enqueue_registration(self.root, **request())
        path = self.root / "pending" / f"{queued['request_id']}.json"
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / ".lock").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
