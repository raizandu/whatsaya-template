from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import patient_directory as directory  # noqa: E402
import whatsapp_manager as wm  # noqa: E402


NOW = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
PHONE = "5511987654321"
CLINIC_ID = "cuidar-odontologia"
SOURCE_CLINIC_HASH = "a" * 64


def _snapshot(*, patients=None, **overrides):
    value = {
        "schema_version": 1,
        "source": "prontuario_verde",
        "clinic_id": CLINIC_ID,
        "source_clinic_hash": SOURCE_CLINIC_HASH,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "complete": True,
        "patients": patients if patients is not None else [{"id": "p-1", "phones": [PHONE]}],
    }
    value.update(overrides)
    return value


class PatientDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.snapshot_path = Path(self.temp.name) / "patient_directory.json"

    def _write_snapshot(self, payload):
        self.snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    def _lookup(
        self,
        *,
        phone=PHONE,
        max_age_hours=24,
        source_clinic_hash=SOURCE_CLINIC_HASH,
    ):
        return directory.lookup_patient(
            self.snapshot_path,
            CLINIC_ID,
            phone,
            max_age_hours=max_age_hours,
            now=NOW,
            source_clinic_hash=source_clinic_hash,
        )

    def test_normalize_phone_accepts_brazilian_number_and_classic_jid(self):
        self.assertEqual(directory.normalize_phone("(11) 98765-4321"), PHONE)
        self.assertEqual(directory.normalize_phone("+55 11 98765-4321"), PHONE)
        self.assertEqual(directory.normalize_phone(f"{PHONE}:4@s.whatsapp.net"), PHONE)

    def test_normalize_phone_rejects_lid_group_and_non_brazilian_number(self):
        self.assertIsNone(directory.normalize_phone("123456789@lid"))
        self.assertIsNone(directory.normalize_phone("120363000000000000@g.us"))
        self.assertIsNone(directory.normalize_phone("447700900123"))

    def test_lookup_matches_phone_without_exposing_patient_id(self):
        self._write_snapshot(_snapshot())
        result = self._lookup()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["updated_at"], "2026-09-23 15:00 UTC")
        self.assertNotIn("id", result)
        self.assertNotIn("patient_ids", result)

    def test_lookup_requires_a_valid_expected_source_hash(self):
        self._write_snapshot(_snapshot())
        for source_hash in (None, "", "not-a-sha256", "a" * 63, "g" * 64):
            with self.subTest(source_hash=source_hash):
                result = self._lookup(source_clinic_hash=source_hash)
                self.assertEqual(result["status"], "unavailable")

    def test_malformed_snapshot_is_unavailable(self):
        self.snapshot_path.write_text("{", encoding="utf-8")
        self.assertEqual(self._lookup()["status"], "unavailable")
        self._write_snapshot(_snapshot(patients=[{"id": "p-1", "phones": "not-a-list"}]))
        self.assertEqual(self._lookup()["status"], "unavailable")

    def test_expired_incomplete_future_and_cross_clinic_snapshots_are_unavailable(self):
        for payload in (
            _snapshot(generated_at=(NOW - timedelta(hours=25)).isoformat()),
            _snapshot(complete=False),
            _snapshot(generated_at=(NOW + timedelta(minutes=1)).isoformat()),
            _snapshot(clinic_id="other-clinic"),
        ):
            with self.subTest(payload=payload):
                self._write_snapshot(payload)
                result = self._lookup()
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["count"])

    def test_explicit_lid_input_is_unavailable(self):
        self._write_snapshot(_snapshot())
        self.assertEqual(self._lookup(phone="123456789@lid")["status"], "unavailable")

    def test_no_match_and_duplicate_shared_phone(self):
        self._write_snapshot(_snapshot())
        self.assertEqual(self._lookup(phone="5511987654322")["status"], "not_found")
        self._write_snapshot(_snapshot(patients=[
            {"id": "p-1", "phones": [PHONE, PHONE]},
            {"id": "p-2", "phones": ["(11) 98765-4321"]},
        ]))
        result = self._lookup()
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["count"], 2)

    def test_configured_source_clinic_hash_binds_snapshot_to_authenticated_clinic(self):
        hash_a = "b" * 64
        hash_b = "c" * 64
        self._write_snapshot(_snapshot(source_clinic_hash=hash_a))
        self.assertEqual(
            self._lookup(source_clinic_hash=hash_a)["status"], "matched"
        )
        self.assertEqual(
            self._lookup(source_clinic_hash=hash_b)["status"], "unavailable"
        )
        self._write_snapshot(_snapshot())
        self.assertEqual(
            self._lookup(source_clinic_hash=hash_a)["status"], "unavailable"
        )

    def test_prompt_block_is_injected_and_contains_no_identity_data(self):
        config_path = Path(self.temp.name) / "panel.config.json"
        config_path.write_text(json.dumps({"patient_directory": {
            "enabled": True,
            "clinic_id": CLINIC_ID,
            "source_clinic_hash": SOURCE_CLINIC_HASH,
            "max_age_hours": 24,
        }}), encoding="utf-8")
        self._write_snapshot(_snapshot(patients=[
            {"id": "private-patient-id", "phones": [PHONE], "name": "Nome que não pode vazar"},
        ]))
        with (
            mock.patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config_path),
            mock.patch.object(wm, "_PATIENT_DIRECTORY_SNAPSHOT_PATH", self.snapshot_path),
        ):
            block = wm._patient_directory_prompt_context(f"{PHONE}@s.whatsapp.net")
            prompt = wm._build_support_prompt(
                "persona", "regras", "", chat_id="chat", patient_directory_context=block
            )

        self.assertIn("Status: matched", block)
        self.assertIn("### STATUS CADASTRAL", prompt["context"])
        self.assertIn("não confirma a identidade", prompt["context"])
        self.assertNotIn("private-patient-id", prompt["context"])
        self.assertNotIn("Nome que não pode vazar", prompt["context"])

    def test_enabled_prompt_without_source_hash_fails_closed(self):
        config_path = Path(self.temp.name) / "panel.config.json"
        config_path.write_text(json.dumps({"patient_directory": {
            "enabled": True,
            "clinic_id": CLINIC_ID,
        }}), encoding="utf-8")
        self._write_snapshot(_snapshot())
        with (
            mock.patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config_path),
            mock.patch.object(wm, "_PATIENT_DIRECTORY_SNAPSHOT_PATH", self.snapshot_path),
        ):
            block = wm._patient_directory_prompt_context(f"{PHONE}@s.whatsapp.net")
        self.assertIn("Status: unavailable", block)

    def test_disabled_feature_keeps_existing_prompt_unchanged(self):
        config_path = Path(self.temp.name) / "panel.config.json"
        config_path.write_text(json.dumps({"patient_directory": {"enabled": False}}), encoding="utf-8")
        with mock.patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config_path):
            context = wm._patient_directory_prompt_context(f"{PHONE}@s.whatsapp.net")
        self.assertEqual(context, "")
        with_context = wm._build_support_prompt(
            "persona", "regras", "", chat_id="chat", patient_directory_context=context
        )
        original = wm._build_support_prompt("persona", "regras", "", chat_id="chat")
        self.assertEqual(with_context, original)
        self.assertNotIn("STATUS CADASTRAL", original["context"])


if __name__ == "__main__":
    unittest.main()
