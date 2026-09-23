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

import prontuario_verde_actions as actions  # noqa: E402


def request_payload(**overrides):
    now = datetime.now(timezone.utc)
    payload = {
        "operation": "cancel",
        "chat_id": "5511999999999@s.whatsapp.net",
        "appointment_id": "4501",
        "patient_id": "81",
        "professional_id": "22",
        "expected_start": (now + timedelta(days=1)).isoformat(),
        "expected_end": (now + timedelta(days=1, minutes=30)).isoformat(),
        "clinic_id": "cuidar-odontologia",
        "source_clinic_hash": "a" * 64,
        "requested_by": "panel:admin",
        "created_at": now.isoformat(),
    }
    payload.update(overrides)
    return payload


class ProntuarioVerdeActionQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "spool"
        actions.initialize(self.root)

    def test_enqueue_and_get_result_return_only_safe_lifecycle_fields(self):
        payload = request_payload()
        queued = actions.enqueue_cancel(self.root, payload)
        result = actions.get_result(self.root, queued["request_id"])

        self.assertEqual(queued["status"], "pending")
        self.assertFalse(queued["deduplicated"])
        self.assertEqual(result["status"], "pending")
        self.assertIsNone(result["code"])
        self.assertEqual(set(result), {"request_id", "status", "code", "updated_at"})
        request_file = self.root / "pending" / f"{queued['request_id']}.json"
        self.assertEqual(json.loads(request_file.read_text()), payload)
        self.assertEqual(request_file.stat().st_mode & 0o777, 0o640)

    def test_duplicate_appointment_returns_existing_active_request(self):
        first = actions.enqueue_cancel(self.root, request_payload())
        duplicate = actions.enqueue_cancel(
            self.root, request_payload(chat_id="5511888888888@s.whatsapp.net")
        )

        self.assertEqual(duplicate, {
            "request_id": first["request_id"],
            "status": "pending",
            "deduplicated": True,
        })
        claimed = actions.claim_next(self.root)
        duplicate_running = actions.enqueue_cancel(self.root, request_payload())
        self.assertEqual(claimed["request_id"], first["request_id"])
        self.assertEqual(duplicate_running["status"], "running")
        self.assertEqual(duplicate_running["request_id"], first["request_id"])

    def test_concurrent_enqueue_deduplicates_across_callers(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: actions.enqueue_cancel(self.root, request_payload()), range(8)
            ))

        self.assertEqual(len({item["request_id"] for item in results}), 1)
        self.assertEqual(sum(not item["deduplicated"] for item in results), 1)
        self.assertEqual(len(list((self.root / "pending").glob("*.json"))), 1)

    def test_invalid_payload_and_noncanonical_request_ids_are_rejected(self):
        for payload in (
            request_payload(operation="read"),
            request_payload(source_clinic_hash="bad"),
            request_payload(created_at="2026-09-23T12:00:00"),
            {**request_payload(), "extra": "unexpected"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                actions.enqueue_cancel(self.root, payload)

        self.assertIsNone(actions.get_result(self.root, "../pending"))
        self.assertIsNone(actions.get_result(self.root, "ABCDEFAB-1234-5678-9ABC-ABCDEFABCDEF"))

    def test_claim_expires_old_request_without_attempting_it(self):
        old = datetime.now(timezone.utc) - timedelta(minutes=16)
        queued = actions.enqueue_cancel(self.root, request_payload(created_at=old.isoformat()))

        self.assertIsNone(actions.claim_next(self.root))
        result = actions.get_result(self.root, queued["request_id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "expired_before_attempt")

    def test_initialize_marks_orphan_running_job_for_review(self):
        queued = actions.enqueue_cancel(self.root, request_payload())
        self.assertEqual(actions.claim_next(self.root)["request_id"], queued["request_id"])

        actions.initialize(self.root)

        result = actions.get_result(self.root, queued["request_id"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["code"], "worker_restarted")
        self.assertFalse(list((self.root / "running").glob("*.json")))

    def test_finish_stores_safe_terminal_result_and_removes_running_item(self):
        queued = actions.enqueue_cancel(self.root, request_payload())
        actions.claim_next(self.root)

        result = actions.finish(self.root, queued["request_id"], "succeeded", "cancelled")

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["code"], "cancelled")
        self.assertFalse((self.root / "running" / f"{queued['request_id']}.json").exists())
        self.assertEqual(actions.get_result(self.root, queued["request_id"]), result)
        with self.assertRaises(ValueError):
            actions.finish(self.root, queued["request_id"], "failed", "raw error: secret")


if __name__ == "__main__":
    unittest.main()
