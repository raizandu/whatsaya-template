import unittest
from unittest.mock import patch, PropertyMock
import whatsapp_manager as wm

CHAT = "5511999999999@s.whatsapp.net"
SESSION = "document-fixture-session"
ENVELOPE = "PDF recebido. Conteúdo extraído: requisição do laboratório."

class ReachedOutputGuards(Exception):
    pass

class DocumentTurnBindingTests(unittest.TestCase):
    def setUp(self):
        with wm._pending_inbound_lock:
            wm._pending_inbound.clear()
            wm._pending_inbound_queue.clear()
        with wm._turn_lock:
            wm._turn_key.clear()
            wm._turn_inbound.clear()
            wm._core_turn_bindings.clear()
        wm._sender_to_chat[SESSION] = CHAT
        self.enterContext(patch.object(wm, "_typing_hold"))
        self.enterContext(patch.object(type(wm.config), "whatsapp_owner_number", new_callable=PropertyMock, return_value=""))
        self.enterContext(patch.object(wm, "_runtime_turn_for_session", return_value=None))

    def bind(self, message_id="document-A", history_content=ENVELOPE, trailing_assistant=False):
        history = [{"role": "user", "content": history_content, "platform_message_id": message_id}]
        if trailing_assistant:
            history.append({"role": "assistant", "content": "Resposta anterior"})
        wm.pre_llm_call(platform="whatsapp", sender_id=CHAT, session_id=SESSION,
            turn_id="document-core-A", user_message=ENVELOPE,
            conversation_history=history)
        return wm._core_bound_turn(SESSION, "document-core-A")

    def output_reaches_guards(self):
        with patch.object(wm, "_session_is_owner", return_value=False), \
             patch.object(wm, "_calendar_state_for_turn", return_value={}), \
             patch.object(wm, "_inbound_prompt_injection_kind", return_value=None), \
             patch.object(wm, "_unrelated_assistant_task_redirect", side_effect=ReachedOutputGuards), \
             patch.object(wm, "_clear_inbound"), \
             patch.object(wm, "_complete_contact_send"):
            try:
                wm.transform_llm_output(platform="whatsapp", session_id=SESSION,
                    turn_id="document-core-A", response_text="Recebi o documento.")
            except ReachedOutputGuards:
                return True
        return False

    def test_document_envelope_binds_original_id_and_is_not_suppressed(self):
        wm._track_inbound(CHAT, "document-A", "[document received]")
        _, snapshot = self.bind()
        self.assertEqual(snapshot["message_id"], "document-A")
        self.assertEqual(snapshot["text"], ENVELOPE)
        self.assertTrue(self.output_reaches_guards())

    def test_genuine_newer_message_still_suppresses_document_reply(self):
        wm._track_inbound(CHAT, "document-A", "[document received]")
        _, snapshot = self.bind()
        self.assertEqual(snapshot["message_id"], "document-A")
        wm._track_inbound(CHAT, "message-B", "Obrigada, já resolvi")
        self.assertFalse(self.output_reaches_guards())

    def test_newer_message_before_hook_cannot_replace_document_identity(self):
        wm._track_inbound(CHAT, "document-A", "[document received]")
        wm._track_inbound(CHAT, "message-B", ENVELOPE)
        _, snapshot = self.bind()
        self.assertEqual(snapshot["message_id"], "document-A")
        self.assertFalse(self.output_reaches_guards())

    def test_platform_id_from_other_chat_cannot_be_claimed(self):
        wm._track_inbound("5511888888888@s.whatsapp.net", "document-A", "[document received]")
        _, snapshot = self.bind()
        self.assertNotEqual(snapshot["message_id"], "document-A")

    def test_native_timestamp_prefix_preserves_platform_identity(self):
        wm._track_inbound(CHAT, "document-A", "[document received]")
        _, snapshot = self.bind(history_content="[2026-09-30 09:27] " + ENVELOPE)
        self.assertEqual(snapshot["message_id"], "document-A")
        self.assertTrue(self.output_reaches_guards())

    def test_unknown_platform_id_does_not_claim_identical_pending_text(self):
        wm._track_inbound(CHAT, "message-B", ENVELOPE)
        _, snapshot = self.bind(message_id="unknown-A")
        self.assertNotEqual(snapshot["message_id"], "message-B")

    def test_historical_id_before_assistant_is_not_used(self):
        wm._track_inbound(CHAT, "document-A", "[document received]")
        _, snapshot = self.bind(history_content="Mensagem anterior", trailing_assistant=True)
        self.assertNotEqual(snapshot["message_id"], "document-A")

if __name__ == "__main__":
    unittest.main()
