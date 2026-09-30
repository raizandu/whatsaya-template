from concurrent.futures import ThreadPoolExecutor, TimeoutError
import threading
import unittest
from unittest.mock import patch

import whatsapp_manager as wm

CHAT = "5511999999999@s.whatsapp.net"


class LiveClassificationTests(unittest.TestCase):
    def setUp(self):
        for name in ("_live_classification_jobs", "_live_classification_attempts"):
            getattr(wm, name, {}).clear()

    def test_repeated_default_metadata_does_not_queue_duplicates(self):
        entered, release = threading.Event(), threading.Event()
        def slow(**kwargs):
            entered.set()
            release.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool, \
             patch.object(wm, "_live_classification_pool", pool), \
             patch.object(wm, "_live_classify_contact", side_effect=slow) as classify:
            args = dict(phone_number=CHAT, target_key=CHAT, personal_contacts={CHAT: {}})
            try:
                self.assertTrue(wm._schedule_live_classification(**args))
                self.assertTrue(entered.wait(1))
                self.assertFalse(wm._schedule_live_classification(**args))
            finally:
                release.set()
                pool.shutdown(wait=True)
            self.assertFalse(wm._schedule_live_classification(**args))
            self.assertEqual(classify.call_count, 1)

    def test_slow_classifier_does_not_hold_the_real_pre_llm_hook(self):
        entered, release = threading.Event(), threading.Event()
        contact = {"ai_enabled": True, "in_flow": True, "name": "Ana", "language": "pt",
                   "summary": "Conversa inicial.", "intent": "Atendimento", "frequency": "esporádica"}
        def slow(**kwargs):
            entered.set()
            release.wait(3)
            return dict(contact)
        patches = {
            "_load_support_files": ("recepção", "regras"),
            "_fetch_chat_history": "",
            "_load_personal_contacts": {CHAT: contact},
            "_same_trusted_whatsapp_identity": False,
            "_session_is_owner": False,
            "_contact_security_reset_is_pending": False,
            "_resolve_contact_name_from_bridge": None,
            "_infer_message_language": None,
            "_extract_external_commercial_metadata": {},
            "_current_inbound_commercial_metadata": {},
            "_infer_explicit_market_metadata": {},
            "_market_from_country_reply": {},
            "_register_contact_turn": "test-turn",
            "_core_bound_turn": ("test-turn", {}),
            "_patient_registration_prompt_context": "",
            "_patient_directory_prompt_context": "",
            "_pv_booking_prompt_context": "",
            "_build_support_prompt": {"context": "ready"},
            "_is_contact_blocked": False,
        }
        for key, value in patches.items():
            self.enterContext(patch.object(wm, key, return_value=value))
        self.enterContext(patch.dict(wm.os.environ, {"WHATSAPP_OWNER_NUMBER": "5511888888888"}))
        self.enterContext(patch.object(wm, "_live_classify_contact", side_effect=slow))
        with ThreadPoolExecutor(max_workers=1) as hook_pool:
            future = hook_pool.submit(wm.pre_llm_call, platform="whatsapp", sender_id=CHAT,
                                      session_id="fixture-session", user_message="Quero marcar uma avaliação")
            try:
                self.assertTrue(entered.wait(1))
                try:
                    result = future.result(timeout=0.5)
                except TimeoutError:
                    self.fail("pre_llm_call is waiting for the external classifier")
                self.assertIsNotNone(result)
            finally:
                release.set()
                future.result(timeout=3)
