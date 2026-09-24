import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import importlib.util

SPEC = importlib.util.spec_from_file_location(
    "pv_worker",
    Path(__file__).resolve().parents[1] / "deploy/scripts/process_prontuario_verde_actions.py",
)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


CHAT = "5511987654321@s.whatsapp.net"
SOURCE_ID = "inbound-123"
CLINIC = "cuidar-odontologia"
CLINIC_HASH = "a" * 64
NAME = "Maria da Silva"


class RegistrationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.contacts = root / "personal_contacts.json"
        self.messages = root / "whatsapp_messages.db"
        self.followups = root / "followups.db"
        self.config = root / "panel.config.json"
        self.journal = root / "journal"
        self.lock = root / ".patient-directory-sync.lock"
        self.config.write_text(json.dumps({"patient_directory": {
            "enabled": True,
            "registration_enabled": True,
            "clinic_id": CLINIC,
            "source_clinic_hash": CLINIC_HASH,
            "expected_clinic_name": "Cuidar Odontologia",
        }}))
        self._write_contact()
        db = sqlite3.connect(self.messages)
        db.execute("""CREATE TABLE messages (
            chat_id TEXT, message_id TEXT, from_me INTEGER, is_historical INTEGER
        )""")
        db.execute("INSERT INTO messages VALUES (?, ?, 0, 0)", (CHAT, SOURCE_ID))
        db.commit()
        db.close()
        self.paths = worker.panel_data.Paths(
            contacts_json=self.contacts,
            messages_db=self.messages,
            followups_db=self.followups,
            panel_db=Path(self.temp.name) / "panel.db",
            patient_directory_json=Path(self.temp.name) / "patient_directory.json",
        )
        self.request = {
            "request_id": "request-1",
            "chat_id": CHAT,
            "name": NAME,
            "phone": "5511987654321",
            "clinic_id": CLINIC,
            "source_clinic_hash": CLINIC_HASH,
            "source_message_id": SOURCE_ID,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _write_contact(self, **changes):
        contact = {
            "ai_enabled": True,
            "pv_registration": {
                "clinic_id": CLINIC,
                "source_clinic_hash": CLINIC_HASH,
                "phase": "queued",
                "confirmed_name": NAME,
                "source_message_id": SOURCE_ID,
            },
        }
        contact.update(changes)
        self.contacts.write_text(json.dumps({CHAT: contact}))

    def test_current_guard_requires_real_inbound_and_matching_confirmation(self):
        config = worker.current_registration(self.request, self.paths, self.config)
        self.assertEqual(config["clinic_id"], CLINIC)

        db = sqlite3.connect(self.messages)
        db.execute("UPDATE messages SET is_historical=1")
        db.commit()
        db.close()
        with self.assertRaisesRegex(worker.RegistrationError, "source_message_missing"):
            worker.current_registration(self.request, self.paths, self.config)

        db = sqlite3.connect(self.messages)
        db.execute("UPDATE messages SET is_historical=0")
        db.commit()
        db.close()
        self._write_contact(pv_registration={
            "clinic_id": CLINIC, "source_clinic_hash": CLINIC_HASH,
            "phase": "needs_review", "confirmed_name": NAME,
            "source_message_id": SOURCE_ID,
        })
        with self.assertRaisesRegex(worker.RegistrationError, "identity_confirmation_changed"):
            worker.current_registration(self.request, self.paths, self.config)

    def test_source_message_accepts_legacy_eight_digit_phone_alias(self):
        db = sqlite3.connect(self.messages)
        db.execute("DELETE FROM messages")
        db.execute("INSERT INTO messages VALUES (?, ?, 0, 0)",
                   ("551187654321@s.whatsapp.net", SOURCE_ID))
        db.commit()
        db.close()
        self.assertEqual(worker.current_registration(self.request, self.paths, self.config)["clinic_id"], CLINIC)

    def test_current_guard_stops_blocked_and_human_takeover_contacts(self):
        self._write_contact(blocked=True)
        with self.assertRaisesRegex(worker.RegistrationError, "contact_not_eligible"):
            worker.current_registration(self.request, self.paths, self.config)

        self._write_contact()
        db = sqlite3.connect(self.followups)
        db.execute("CREATE TABLE lead_state (chat_id TEXT, takeover INTEGER, opt_out INTEGER, updated_utc TEXT)")
        db.execute("INSERT INTO lead_state VALUES (?, 1, 0, 'now')", (CHAT,))
        db.commit()
        db.close()
        with self.assertRaisesRegex(worker.RegistrationError, "human_takeover"):
            worker.current_registration(self.request, self.paths, self.config)

    def test_current_guard_requires_ai_permission_and_rejects_personal_contacts(self):
        self._write_contact(ai_enabled=False)
        with self.assertRaisesRegex(worker.RegistrationError, "contact_not_eligible"):
            worker.current_registration(self.request, self.paths, self.config)

        self._write_contact(manual_relationship="Irmã")
        with self.assertRaisesRegex(worker.RegistrationError, "contact_not_eligible"):
            worker.current_registration(self.request, self.paths, self.config)

    def test_registration_failure_after_submit_is_not_replayed(self):
        session = Mock()
        adapter = Mock(submitted=True)
        adapter.before_submit_check = None
        with patch.object(worker, "current_registration", return_value={}), \
             patch.object(worker, "RegistrationBrowser", return_value=adapter), \
             patch.object(worker, "ensure_patient", side_effect=worker.RegistrationError("outcome_uncertain")), \
             patch.object(worker.registration_queue, "finish") as finish:
            worker.process_registration(
                self.request, root=Path(self.temp.name) / "spool", session=session,
                paths=self.paths, config_path=self.config, journal_dir=self.journal,
                sync_lock_path=self.lock,
            )
        finish.assert_called_once_with(Path(self.temp.name) / "spool", "request-1",
                                       "needs_review", "outcome_uncertain")
        session.close.assert_called_once()

    def _enqueue(self, root):
        worker.registration_queue.initialize(root)
        queued = worker.registration_queue.enqueue_registration(
            root, chat_id=CHAT, name=NAME, clinic_id=CLINIC,
            source_clinic_hash=CLINIC_HASH, source_message_id=SOURCE_ID,
        )
        return worker.registration_queue.claim_next(root), queued

    def test_worker_success_uses_real_queue_and_guarded_registration(self):
        root = Path(self.temp.name) / "spool"
        request, queued = self._enqueue(root)
        adapter_lookups = 0
        browser = Mock()
        saved = []

        def lookup(_adapter, phone, name):
            nonlocal adapter_lookups
            adapter_lookups += 1
            matches = [] if adapter_lookups == 1 else [{"id": "42", "name": name, "phones": [phone]}]
            return {"matches": matches, "name_candidates": 0}

        def save(_adapter, name, phone, before_submit):
            before_submit()
            saved.append((name, phone))
            return "42"

        with patch.object(worker.RegistrationFormBrowser, "lookup", lookup), \
             patch.object(worker.RegistrationFormBrowser, "create", save):
            worker.process_registration(
                request, root=root, session=Mock(acquire=Mock(return_value=browser)),
                paths=self.paths, config_path=self.config, journal_dir=self.journal,
                sync_lock_path=self.lock,
            )

        result = worker.registration_queue.get_for_contact(root, CLINIC, request["phone"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["code"], "created")
        self.assertEqual(saved, [(NAME, request["phone"])])

    def test_guard_change_before_submit_prevents_form_save(self):
        root = Path(self.temp.name) / "spool"
        request, _queued = self._enqueue(root)
        calls = []
        browser = Mock()

        def lookup(_adapter, _phone, _name):
            return {"matches": [], "name_candidates": 0}

        def save(_adapter, name, phone, before_submit):
            self._write_contact(ai_enabled=False)
            before_submit()
            calls.append((name, phone))
            return "42"

        with patch.object(worker.RegistrationFormBrowser, "lookup", lookup), \
             patch.object(worker.RegistrationFormBrowser, "create", save):
            worker.process_registration(
                request, root=root, session=Mock(acquire=Mock(return_value=browser)),
                paths=self.paths, config_path=self.config, journal_dir=self.journal,
                sync_lock_path=self.lock,
            )

        result = worker.registration_queue.get_for_contact(root, CLINIC, request["phone"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "contact_not_eligible")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
