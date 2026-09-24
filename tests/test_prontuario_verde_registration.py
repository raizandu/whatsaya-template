from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from prontuario_verde_registration import RegistrationError, ensure_patient
from patient_directory import normalize_phone


PHONE = "5511987654321"
HASH = "a" * 64


class FakeAdapter:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.create_calls = 0
        self.failure = None
        self.verify_override = None

    def lookup(self, phone, name):
        matches = [
            {key: value for key, value in row.items() if key != "name_only"}
            for row in self.records
            if phone in {normalize_phone(item) for item in row["phones"]}
        ]
        name_candidates = sum(
            1 for row in self.records
            if row["name"].casefold() == name.casefold()
        )
        if self.verify_override is not None and self.create_calls:
            return self.verify_override
        return {"matches": matches, "name_candidates": name_candidates}

    def create(self, name, phone, before_submit):
        self.create_calls += 1
        if self.failure == "before":
            raise RuntimeError("private adapter details")
        before_submit()
        if self.failure == "after_without_save":
            raise RuntimeError("private adapter details")
        row = {"id": str(100 + self.create_calls), "name": name, "phones": [phone]}
        self.records.append(row)
        if self.failure == "after_save":
            raise RuntimeError("private adapter details")
        return row["id"]


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal_dir = Path(self.temp.name) / "journal"

    def ensure(self, adapter, **changes):
        args = {
            "name": "Anthony Aya",
            "phone": "(11) 98765-4321",
            "clinic_id": "cuidar-odontologia",
            "source_clinic_hash": HASH,
            "journal_dir": self.journal_dir,
        }
        args.update(changes)
        return ensure_patient(adapter, **args)

    def assert_code(self, code, callable_):
        with self.assertRaises(RegistrationError) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("Anthony", str(caught.exception))
        self.assertNotIn(PHONE, str(caught.exception))

    def test_existing_exact_patient_matches_legacy_phone_alias_and_normalized_name(self):
        adapter = FakeAdapter([{
            "id": "42", "name": "  ANTHONY   AYA ", "phones": ["551187654321"],
            "record_number": "PV-42",
        }])
        result = self.ensure(adapter)
        self.assertEqual(result, {
            "status": "existing", "patient_id": "42", "phone": PHONE,
            "record_number": "PV-42",
        })
        self.assertEqual(adapter.create_calls, 0)

    def test_phone_ambiguity_and_name_candidate_without_phone_require_review(self):
        self.assert_code("needs_review", lambda: self.ensure(FakeAdapter([
            {"id": "1", "name": "Anthony Aya", "phones": [PHONE]},
            {"id": "2", "name": "Anthony Aya", "phones": [PHONE]},
        ])))
        adapter = FakeAdapter([{
            "id": "1", "name": "Anthony Aya", "phones": ["5511999999999"],
        }])
        self.assert_code("needs_review", lambda: self.ensure(adapter))
        self.assertEqual(adapter.create_calls, 0)

    def test_same_phone_with_different_name_requires_review(self):
        adapter = FakeAdapter([{
            "id": "1", "name": "Anthony A. Silva", "phones": [PHONE],
        }])
        self.assert_code("needs_review", lambda: self.ensure(adapter))
        self.assertEqual(adapter.create_calls, 0)

    def test_invalid_phone_name_or_config_hash_is_rejected_without_lookup(self):
        for changes in (
            {"phone": "123456789@lid"},
            {"name": "\n"},
            {"name": "x" * 101},
            {"source_clinic_hash": "z" * 64},
        ):
            with self.subTest(changes=changes):
                self.assert_code(
                    "invalid_input", lambda: self.ensure(FakeAdapter(), **changes),
                )

    def test_create_failure_before_submit_can_retry(self):
        adapter = FakeAdapter()
        adapter.failure = "before"
        self.assert_code("create_failed", lambda: self.ensure(adapter))
        adapter.failure = None
        result = self.ensure(adapter)
        self.assertEqual(result["status"], "created")
        self.assertEqual(adapter.create_calls, 2)

    def test_save_then_adapter_exception_reconciles_without_replay(self):
        adapter = FakeAdapter()
        adapter.failure = "after_save"
        self.assert_code("outcome_uncertain", lambda: self.ensure(adapter))
        adapter.failure = None
        result = self.ensure(adapter)
        self.assertEqual(result["status"], "existing")
        self.assertEqual(result["patient_id"], "101")
        self.assertEqual(adapter.create_calls, 1)

    def test_uncertain_submit_with_absent_patient_never_replays(self):
        adapter = FakeAdapter()
        adapter.failure = "after_without_save"
        self.assert_code("outcome_uncertain", lambda: self.ensure(adapter))
        adapter.failure = None
        self.assert_code("needs_review", lambda: self.ensure(adapter))
        self.assertEqual(adapter.create_calls, 1)

    def test_post_submit_mismatch_is_reviewed_and_never_replayed(self):
        adapter = FakeAdapter()
        adapter.verify_override = {"matches": [], "name_candidates": 0}
        self.assert_code("needs_review", lambda: self.ensure(adapter))
        adapter.verify_override = None
        result = self.ensure(adapter)
        self.assertEqual(result["status"], "existing")
        self.assertEqual(adapter.create_calls, 1)

    def test_journal_is_private_and_independent_by_clinic(self):
        adapter = FakeAdapter()
        other_clinic_adapter = FakeAdapter()
        first = self.ensure(adapter)
        second = self.ensure(other_clinic_adapter, clinic_id="other-clinic")
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "created")
        self.assertEqual(adapter.create_calls + other_clinic_adapter.create_calls, 2)
        self.assertEqual(self.journal_dir.stat().st_mode & 0o777, 0o700)
        for path in self.journal_dir.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
