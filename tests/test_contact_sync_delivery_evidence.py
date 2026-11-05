"""A sincronização de histórico preserva efeitos já entregues ao lead."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import whatsapp_manager as wm


CHAT = "5511999991111@s.whatsapp.net"
DELIVERY_EVIDENCE = {
    "bot_first_outbound_at": 1793708885.0,
    "downsell_metodo_gravado_at": 1793708910.0,
    "playbook_completion_at": 1793708000.0,
    "playbook_completion_pending_at": None,
    "playbook_completion_progress": None,
}


class ContactSyncDeliveryEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.hermes = self.root / "hermes"
        self.hermes.mkdir()
        self.contacts = self.root / "contacts.json"
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", self.contacts))
        for name, value in (
            ("_check_bot_paused", False),
            ("_fetch_all_bridge_contact_names", {}),
            ("_build_lid_phone_map", {}),
            ("_sync_full_summaries", 0),
            ("_should_run_style_learning", False),
        ):
            self.enterContext(mock.patch.object(wm, name, return_value=value))
        self.enterContext(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
        self.enterContext(mock.patch.object(wm, "_best_contact_name", return_value=("Lead Teste", "log")))
        for name, value in (("whatsapp_owner_number", "5511888880000"),
                            ("config_repo", ""), ("config_github_token", ""),
                            ("hermes_setup_github_user", "")):
            self.enterContext(mock.patch.object(type(wm.config), name,
                new_callable=mock.PropertyMock, return_value=value))
        self.enterContext(mock.patch.object(wm, "_classify_contact_via_llm", return_value={
            "summary": "Relato classificado do contato.", "intent": "Atendimento.",
            "frequency": "esporádica", "ai_enabled": True,
            "downsell_metodo_gravado_at": 9999999999,
        }))

    def _run_sync(self, *, count, threshold, limit, evidence=None):
        before = {
            "name": "Lead Teste", "summary": "Histórico do contato.",
            "intent": "Atendimento.", "frequency": "esporádica", "last_interaction": 1,
            "ai_enabled": False, "in_flow": False, "flow_origin": "legacy_history",
            "ai_disabled_reason": "legacy_history", "arbitrary_old_field": "discard me",
            **(DELIVERY_EVIDENCE if evidence is None else evidence),
        }
        self.contacts.write_text(json.dumps({CHAT: before}))
        with closing(sqlite3.connect(self.hermes / "whatsapp_messages.db")) as conn, conn:
            conn.execute("CREATE TABLE messages(chat_id TEXT,sender_name TEXT,from_me INTEGER,body TEXT,timestamp REAL)")
            conn.executemany("INSERT INTO messages VALUES(?,?,?,?,?)", [
                (CHAT, "Lead Teste", 0, "Mensagem do contato", 1793709000 + i)
                for i in range(count)
            ])
        original_path = Path
        def local_path(value):
            return self.hermes if str(value) == "/opt/data/.hermes" else original_path(value)
        connections = []
        connect = sqlite3.connect
        def local_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            connections.append(conn)
            return conn
        with mock.patch.object(type(wm.config), "whatsapp_sync_min_messages", new_callable=mock.PropertyMock, return_value=threshold), \
             mock.patch.object(type(wm.config), "whatsapp_sync_max_classifications", new_callable=mock.PropertyMock, return_value=limit), \
             mock.patch("pathlib.Path", side_effect=local_path), \
             mock.patch("sqlite3.connect", side_effect=local_connect):
            try:
                result = wm._sync_contacts_from_db_internal(force=True)
            finally:
                for conn in connections:
                    conn.close()
        self.assertIn("Sucesso!", result)
        return json.loads(self.contacts.read_text())[CHAT]

    def test_history_sync_preserves_delivery_evidence_in_all_rebuild_branches(self):
        for count, threshold, limit in ((1, 3, 10), (3, 1, 0), (3, 1, 10)):
            with self.subTest(count=count, threshold=threshold, limit=limit):
                (self.hermes / "whatsapp_messages.db").unlink(missing_ok=True)
                after = self._run_sync(count=count, threshold=threshold, limit=limit)
                self.assertEqual({key: after.get(key) for key in DELIVERY_EVIDENCE}, DELIVERY_EVIDENCE)
                self.assertFalse(after["ai_enabled"])
                self.assertFalse(after["in_flow"])
                self.assertEqual(after["ai_disabled_reason"], "legacy_history")
                self.assertNotIn("arbitrary_old_field", after)

    def test_history_sync_preserves_unfinished_playbook_progress(self):
        evidence = {"playbook_completion_pending_at": 1793708000,
                    "playbook_completion_progress": {"next_line": 3, "media_sent": True}}
        after = self._run_sync(count=3, threshold=1, limit=10, evidence=evidence)
        self.assertEqual({key: after.get(key) for key in evidence}, evidence)
        self.assertNotIn("downsell_metodo_gravado_at", after, "classificação não comprova entrega")

    def test_delivery_confirmed_while_sync_classifies_survives_stale_snapshot(self):
        def classify(*_args):
            wm._merge_contact_record_atomic(CHAT, DELIVERY_EVIDENCE, chat_id=CHAT)
            return {"summary": "Histórico atualizado.", "intent": "Atendimento."}
        with mock.patch.object(wm, "_classify_contact_via_llm", side_effect=classify):
            after = self._run_sync(count=3, threshold=1, limit=10, evidence={})
        self.assertEqual({key: after.get(key) for key in DELIVERY_EVIDENCE}, DELIVERY_EVIDENCE)
        self.assertFalse(after["ai_enabled"])

    def test_completed_playbook_clears_progress_and_stale_writer_cannot_reopen_it(self):
        before = {"ai_enabled": False, "in_flow": False,
                  "playbook_completion_pending_at": 1793708000,
                  "playbook_completion_progress": {"next_line": 3}}
        self.contacts.write_text(json.dumps({CHAT: before}))
        wm._playbook_completion_mark_done(CHAT)
        completed = json.loads(self.contacts.read_text())[CHAT]
        self.assertTrue(completed["playbook_completion_at"])
        self.assertIsNone(completed["playbook_completion_pending_at"])
        self.assertIsNone(completed["playbook_completion_progress"])
        wm._write_personal_contacts_atomic({CHAT: before})
        after = json.loads(self.contacts.read_text())[CHAT]
        self.assertEqual(after, completed)


if __name__ == "__main__":
    unittest.main()
