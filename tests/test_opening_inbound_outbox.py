import tempfile
import unittest
from unittest import mock
from pathlib import Path

from opening_inbound_outbox import OpeningInboundOutbox


class OpeningInboundOutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "outbox.db"
        self.outbox = OpeningInboundOutbox(self.path)

    def test_restart_preserves_inbound_until_opening_and_reply_ack(self):
        self.assertTrue(self.outbox.defer("chat", "mid", "turn", "Mensagem", 10))
        self.assertFalse(self.outbox.defer("chat", "mid", "turn", "Mensagem", 10))
        self.assertIsNone(OpeningInboundOutbox(self.path).claim_next())
        self.outbox.mark_opening_complete("turn")
        restored = OpeningInboundOutbox(self.path)
        item = restored.claim_next()
        self.assertEqual(item["message_id"], "mid")
        self.assertTrue(restored.dispatch_result("chat", "mid", queue_id="queue"))
        self.assertIsNone(OpeningInboundOutbox(self.path).claim_next())
        self.assertFalse(restored.acknowledge("chat", "wrong", "reply"))
        self.assertTrue(restored.acknowledge("chat", "mid", "reply"))

    def test_known_rejection_is_retryable_after_restart(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        self.outbox.claim_next()
        self.outbox.dispatch_result("chat", "mid", retry=True)
        self.assertEqual(OpeningInboundOutbox(self.path).claim_next()["message_id"], "mid")

    def test_interrupted_dispatch_is_uncertain_and_not_retried(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        self.outbox.claim_next()
        restored = OpeningInboundOutbox(self.path)
        rows = restored.mark_expired_uncertain(before=10**20)
        self.assertEqual([r["message_id"] for r in rows], ["mid"])
        self.assertIsNone(restored.claim_next())

    def test_late_confirmed_reply_resolves_uncertain_without_retry(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        self.outbox.claim_next()
        self.assertTrue(self.outbox.claim_processing("chat", "mid"))
        self.outbox.mark_expired_uncertain(before=10**20)
        self.assertTrue(self.outbox.acknowledge("chat", "mid", "confirmed-reply"))
        self.assertIsNone(self.outbox.claim_next())

    def test_ack_before_dispatch_response_wins(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        self.outbox.claim_next()
        self.assertTrue(self.outbox.acknowledge("chat", "mid", "reply"))
        self.assertFalse(self.outbox.dispatch_result("chat", "mid", queue_id="queue"))
        self.assertIsNone(self.outbox.claim_next())

    def test_debounce_batch_keeps_each_id_and_preserves_order(self):
        self.outbox.defer_batch("chat", "turn", [("id1", "oi"), ("id2", "quanto custa?")], 10)
        self.assertTrue(self.outbox.contains_all("chat", ["id1", "id2"]))
        self.outbox.mark_opening_complete("turn")
        item = self.outbox.claim_next()
        self.assertEqual(item["message_ids"], ["id1", "id2"])
        self.assertEqual(item["body_parts"], ["oi", "quanto custa?"])
        self.assertTrue(self.outbox.claim_processing("chat", "id1"))
        self.assertIsNone(self.outbox.claim_next())
        self.assertTrue(self.outbox.acknowledge("chat", "id1", "out1"))
        self.assertIsNone(OpeningInboundOutbox(self.path).claim_next())

    def test_events_captured_before_coalescing_group_after_restart(self):
        clock = [100.0]
        with mock.patch("opening_inbound_outbox.time.time", side_effect=lambda: clock[0]):
            self.outbox.defer_batch("chat", "turn", [("id1", "Sim")], 100, coalesce_s=2)
            clock[0] = 101.0
            OpeningInboundOutbox(self.path).defer_batch("chat", "turn", [("id2", "10")], 101, coalesce_s=2)
            self.outbox.mark_opening_complete("turn")
            self.assertIsNone(self.outbox.claim_next())
            clock[0] = 104.0
            item = OpeningInboundOutbox(self.path).claim_next()
            self.assertEqual(item["message_ids"], ["id1", "id2"])
            self.assertEqual(item["body"], "Sim\n10")

    def test_late_ack_from_original_attempt_cancels_approved_retry(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        attempt = self.outbox.claim_next()["attempt_id"]
        self.outbox.claim_processing("chat", "mid", attempt_id=attempt)
        self.outbox.mark_expired_uncertain(before=10**20)
        item = self.outbox.uncertain_batches("chat")[0]
        self.assertEqual(self.outbox.resolve_batch("chat", "mid", item["version"], "not_sent", "admin"), "manual_required")
        self.assertTrue(self.outbox.acknowledge("chat", "mid", "late-ack", attempt_id=attempt))
        self.outbox.request_resume("chat")
        request = self.outbox.pending_resumes()[0]
        self.outbox.consume_resume("chat", request["requested_at"])
        self.assertIsNone(self.outbox.claim_next())

    def test_old_attempt_cannot_acknowledge_a_new_attempt(self):
        self.outbox.defer("chat", "mid", "turn", "Mensagem", 10)
        self.outbox.mark_opening_complete("turn")
        first = self.outbox.claim_next()["attempt_id"]
        self.outbox.claim_processing("chat", "mid", attempt_id=first)
        self.outbox.mark_expired_uncertain(before=10**20)
        item = self.outbox.uncertain_batches("chat")[0]
        self.assertEqual(self.outbox.resolve_batch("chat", "mid", item["version"], "not_sent", "admin"), "manual_required")
        # Simula legado inseguro que mudou o estado por fora; mesmo assim o ACK
        # da tentativa antiga não pode confirmar a tentativa nova.
        with self.outbox._connect() as conn:
            conn.execute("UPDATE opening_inbound_outbox SET state='ready' WHERE chat_id='chat'")
        second = self.outbox.claim_next()["attempt_id"]
        self.assertNotEqual(first, second)
        self.assertFalse(self.outbox.acknowledge("chat", "mid", "late-old", attempt_id=first))
        self.assertTrue(self.outbox.acknowledge("chat", "mid", "new-ack", attempt_id=second))
