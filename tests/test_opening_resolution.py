import json
import hashlib
import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

import opening_resolution as resolution
from opening_inbound_outbox import OpeningInboundOutbox


class OpeningResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = SimpleNamespace(followups_db=self.root / "followups.db")
        self.cursor_path = self.root / "partial_reply_state.json"
        self.chat, self.turn = "5511999999999@s.whatsapp.net", "turn-1"
        self.outbox = OpeningInboundOutbox(self.root / "opening_inbound_outbox.db")

    def cursor(self, text="Primeira\n\nSegunda"):
        self.cursor_path.write_text(json.dumps({self.turn: {"chat_id": self.chat, "opening": True,
            "send_in_flight": True, "remaining_text": text, "inbound_message_id": "in-1",
            "inbound_text": "oi", "inbound_at": 100, "updated_at": 100}}))

    def test_sent_cursor_removes_only_confirmed_bubble_and_audits_actor(self):
        self.cursor()
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        self.assertEqual(item["display_text"], "Primeira")
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        saved = json.loads(self.cursor_path.read_text())[self.turn]
        self.assertEqual(saved["remaining_text"], "Segunda")
        self.assertFalse(saved["send_in_flight"])
        self.assertTrue(saved["resolved_pending_resume"])
        with sqlite3.connect(self.outbox.path) as conn:
            rows = conn.execute("SELECT decision,actor,status FROM opening_resolution_audit ORDER BY id").fetchall()
        self.assertEqual(rows, [("sent", "operador", "requested"), ("sent", "operador", "applied")])

    def test_not_sent_keeps_bubble_and_requires_explicit_resume(self):
        self.cursor()
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        with self.assertRaises(ValueError):
            resolution.resume_pending(self.paths, self.chat)
        result = resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "not_sent", "operador")
        self.assertEqual(result, {"resolved": False, "manual_required": True})
        self.assertEqual(json.loads(self.cursor_path.read_text())[self.turn]["remaining_text"], "Primeira\n\nSegunda")
        self.assertFalse(self.outbox.turn_authorized(self.turn))
        with self.assertRaises(ValueError):
            resolution.resume_pending(self.paths, self.chat)
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        resolution.resume_pending(self.paths, self.chat)
        self.assertTrue(self.outbox.turn_authorized(self.turn))

    def test_stale_version_rejected_without_changing_cursor(self):
        self.cursor()
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        self.cursor("Alterada")
        with self.assertRaises(ValueError):
            resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        self.assertEqual(json.loads(self.cursor_path.read_text())[self.turn]["remaining_text"], "Alterada")

    def test_final_bubble_confirmation_releases_captured_inbound(self):
        self.cursor("Última")
        self.outbox.defer(self.chat, "new-id", self.turn, "Minha dúvida", 101)
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        self.assertNotIn(self.turn, json.loads(self.cursor_path.read_text()))
        self.assertIsNone(self.outbox.claim_next())
        resolution.resume_pending(self.paths, self.chat)
        intent = self.outbox.pending_resumes()[0]
        self.outbox.consume_resume(self.chat, intent["requested_at"])
        self.assertEqual(self.outbox.claim_next()["message_id"], "new-id")

    def test_crash_after_intent_cannot_reverse_recorded_decision(self):
        self.cursor("Última")
        self.outbox.defer(self.chat, "new-id", self.turn, "Minha dúvida", 101)
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        with mock.patch.object(resolution, "_write_cursors", side_effect=OSError("queda")):
            with self.assertRaises(OSError):
                resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        self.assertEqual(resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "not_sent", "operador"), {"resolved": False, "manual_required": True})
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        self.assertNotIn(self.turn, json.loads(self.cursor_path.read_text()))

    def test_deferred_uncertainty_resolves_by_exact_id_and_requires_resume(self):
        self.outbox.defer(self.chat, "new-id", self.turn, "Minha dúvida", 101)
        self.outbox.mark_opening_complete(self.turn)
        claim = self.outbox.claim_next()
        self.outbox.dispatch_result(self.chat, "new-id", queue_id="queued", attempt_id=claim["attempt_id"])
        self.outbox.claim_processing(self.chat, "new-id", attempt_id=claim["attempt_id"])
        actual_turn = self.chat + ":" + hashlib.md5("Minha dúvida\0new-id".encode()).hexdigest()
        self.outbox.bind_turn(self.chat, "new-id", actual_turn, attempt_id=claim["attempt_id"])
        self.outbox.mark_expired_uncertain(before=10**20)
        item = resolution.inspect(self.paths, self.chat)["items"][0]
        self.assertEqual(item["kind"], "deferred_reply")
        self.assertEqual(resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "not_sent", "operador"), {"resolved": False, "manual_required": True})
        with self.assertRaises(ValueError):
            resolution.resume_pending(self.paths, self.chat)
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "sent", "operador")
        self.assertIsNone(self.outbox.claim_next())

    def test_resume_is_blocked_while_deferred_reply_is_in_flight(self):
        self.outbox.defer(self.chat, "new-id", self.turn, "Minha dúvida", 101)
        self.outbox.mark_opening_complete(self.turn)
        self.outbox.claim_next()
        with self.assertRaisesRegex(ValueError, "processamento"):
            resolution.resume_pending(self.paths, self.chat)
        self.assertEqual(self.outbox.pending_resumes(), [])

    def test_manual_takeover_requires_review_of_pending_reply_before_resume(self):
        self.paths.contacts_json = self.root / "contacts.json"
        self.paths.contacts_json.write_text(json.dumps({self.chat: {"ai_enabled": False}}))
        self.outbox.defer(self.chat, "new-id", self.turn, "Minha dúvida", 101)
        items = resolution.inspect(self.paths, self.chat)["items"]
        self.assertEqual([(item["kind"], item["item_id"]) for item in items], [("deferred_reply", "new-id")])
        with self.assertRaises(ValueError):
            resolution.resume_pending(self.paths, self.chat)
        item = items[0]
        resolution.resolve(self.paths, self.chat, item["kind"], item["item_id"], item["version"], "not_sent", "operador")
        resolution.resume_pending(self.paths, self.chat)
        intent = self.outbox.pending_resumes()[0]
        self.outbox.consume_resume(self.chat, intent["requested_at"])
        self.assertIsNone(self.outbox.claim_next())
        self.outbox.mark_opening_complete(self.turn)
        self.assertEqual(self.outbox.claim_next()["message_id"], "new-id")
