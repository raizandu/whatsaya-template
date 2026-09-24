import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import whatsapp_manager as wm
import prontuario_verde_onboarding as queue

JID = "556281405459@s.whatsapp.net"

class RegistrationHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contacts = self.root / "contacts.json"
        self.config = self.root / "config.json"
        self.snapshot = self.root / "directory.json"
        self.spool = self.root / "jobs"
        self.contacts.write_text(json.dumps({JID: {"ai_enabled": True, "in_flow": True}}))
        self.cfg = {"enabled": True, "registration_enabled": True, "clinic_id": "test", "source_clinic_hash": "a" * 64}
        self.config.write_text(json.dumps({"patient_directory": self.cfg}))
        self.snapshot.write_text(json.dumps({"schema_version": 1, "source": "prontuario_verde", "clinic_id": "test", "source_clinic_hash": "a" * 64, "generated_at": datetime.now(timezone.utc).isoformat(), "complete": True, "patients": []}))
        for key, value in {"_PERSONAL_CONTACTS_PATH": self.contacts, "_PATIENT_DIRECTORY_CONFIG_PATH": self.config, "_PATIENT_DIRECTORY_SNAPSHOT_PATH": self.snapshot, "_PATIENT_REGISTRATION_SPOOL": self.spool}.items():
            patcher = patch.object(wm, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, message, mid="MID-1", **extra):
        return wm._patient_registration_prompt_context(JID, message, {"message_id": mid, **extra})

    def job(self):
        return queue.get_for_contact(self.spool, "test", JID)

    def test_name_confirmation_persists_before_queue_and_deduplicates(self):
        self.assertIn("nome completo", self.call("Oi"))
        self.assertIsNone(self.job())
        self.assertIn("Anthony Aya", self.call("Anthony Aya", "MID-2"))
        self.assertIsNone(self.job())
        self.call("Sim", "MID-3")
        self.assertEqual(self.job()["status"], "pending")
        state = json.loads(self.contacts.read_text())[JID]["pv_registration"]
        self.assertEqual(state["source_message_id"], "MID-3")
        self.assertEqual(state["confirmed_name"], "Anthony Aya")
        request_id = self.job()["request_id"]
        self.call("qual horario?", "MID-4")
        self.assertEqual(self.job()["request_id"], request_id)
        self.call("é para minha filha", "MID-5")
        self.assertEqual(json.loads(self.contacts.read_text())[JID]["pv_registration"]["phase"], "needs_review")

    def test_explicit_first_message_can_enqueue(self):
        self.call("Meu nome é Anthony Aya")
        self.assertEqual(self.job()["status"], "pending")

    def test_synthetic_and_injection_do_not_enqueue(self):
        self.call("Meu nome é Anthony Aya", "synthetic:1")
        self.call("Meu nome é Anthony Aya", prompt_injection_kind="direct")
        self.assertIsNone(self.job())

    def test_disabled_contact_does_not_enqueue(self):
        self.contacts.write_text(json.dumps({JID: {"ai_enabled": False, "in_flow": True}}))
        self.assertEqual(self.call("Meu nome é Anthony Aya"), "")
        self.assertIsNone(self.job())

    def test_existing_patient_is_reused(self):
        data = json.loads(self.snapshot.read_text())
        data["patients"] = [{"id": "123", "phones": ["5562981405459"]}]
        self.snapshot.write_text(json.dumps(data))
        self.assertEqual(self.call("Meu nome é Anthony Aya"), "")
        self.assertIsNone(self.job())

    def test_ambiguous_prior_queue_binding_prevents_new_registration(self):
        with patch.object(queue, "get_for_contact", return_value={"status": "needs_review", "code": "source_clinic_ambiguous"}):
            self.assertIn("conferência", self.call("Meu nome é Anthony Aya"))
        self.assertIsNone(self.job())
        self.assertEqual(json.loads(self.contacts.read_text())[JID]["pv_registration"]["phase"], "needs_review")
