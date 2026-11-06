"""Regressões do primeiro outbound obrigatório da Therapify."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("WHATSAPP_HUMAN_TEST_MODE", "1")

MODULE_PATH = REPO_ROOT / "whatsapp_manager.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_manager", MODULE_PATH)
assert SPEC and SPEC.loader
wm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wm
SPEC.loader.exec_module(wm)


THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
CHAT = "556181856062@s.whatsapp.net"
LEAD_MESSAGE = "Olá! Tenho interesse e queria mais informações, por favor."
FASE1 = "\n\n".join([
    "Olá! Atendimento 100% online, do conforto da sua casa.",
    "O Dr. Rodrigo Melo é especialista em dependência emocional, com 8 anos de experiência.",
    "A sessão inicial inclui liberação emocional, protocolo para descobrir a raiz do sofrimento "
    "e um plano de autocuidado – tudo por R$ 247,00.",
    "Após a primeira sessão, você já percebe os primeiros resultados.",
    "O tempo estimado até o agendamento da sua consulta é de 4 a 6 minutos.",
    "Para entender melhor o seu caso: tem quanto tempo que terminaram? Como você vem lidando com tudo isso?",
])


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class TherapifyFirstOutboundTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", Path(temp.name) / "contacts.json"))
        self.enterContext(mock.patch.object(wm, "_MSG_DB_PATH", Path(temp.name) / "messages.db"))
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            "WHATSAPP_OWNER_NUMBER": "5521979069520",
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def test_ad_origin_is_durable_even_when_dispatch_stops_before_the_model(self):
        source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
        event = SimpleNamespace(source=source, text=LEAD_MESSAGE, raw={}, is_historical=False,
            raw_message={"messageId": "ad-before-queue", "leadMetadata": {
                "origin": "FB_Ads", "campaign": "Therapify", "ad_id": "ad-real-42",
                "ad_title": "Dependência emocional", "ad_source_app": "facebook", "ctwa_clid": "real-click-42",
            }})
        media = {"has_media": False, "media_type": None, "media_urls": [], "message_id": "ad-before-queue"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "contacts.json"
            path.write_text(json.dumps({CHAT: {"ai_enabled": False, "in_flow": False}}))
            with mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", path), \
                 mock.patch.object(wm, "_get_media_info", return_value=media), \
                 mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
                 mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
                 mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
                 mock.patch.object(wm, "_fetch_chat_history", return_value=""), \
                 mock.patch.object(wm, "_complete_pending_panel_unblock"), \
                 mock.patch.object(wm, "_ensure_contact_ai_access", return_value=(False, "label-client")), \
                 mock.patch.object(wm, "_followup_cancel"):
                result = wm.pre_gateway_dispatch(event=event, gateway=SimpleNamespace())
            self.assertEqual(result["reason"], "label-client")
            saved = json.loads(path.read_text())[CHAT]
            self.assertEqual(saved.get("ad_id"), "ad-real-42")
            self.assertEqual(saved.get("ctwa_clid"), "real-click-42")
            self.assertFalse(saved["ai_enabled"], "capturar origem não pode ligar a IA")

    def test_unconfirmed_scope_is_silent_instead_of_sending_alternate_greeting(self):
        source = SimpleNamespace(
            platform=SimpleNamespace(value="whatsapp"),
            user_id=CHAT,
            chat_id=CHAT,
        )
        event = SimpleNamespace(
            source=source,
            text=LEAD_MESSAGE,
            raw_message={"messageId": "in-camilla"},
            raw={},
            is_historical=False,
        )
        media_info = {
            "has_media": False,
            "media_type": None,
            "media_urls": [],
            "message_id": "in-camilla",
        }
        with mock.patch.object(wm, "_get_media_info", return_value=media_info), \
             mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
             mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
             mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
             mock.patch.object(wm, "_fetch_chat_history", return_value=""), \
             mock.patch.object(wm, "_complete_pending_panel_unblock"), \
             mock.patch.object(
                 wm,
                 "_ensure_contact_ai_access",
                 return_value=(False, "commercial-scope-unconfirmed"),
             ), \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_queue_owner_notification_safely") as alert, \
             mock.patch.object(wm, "_schedule_deterministic_contact_reply") as schedule:
            result = wm.pre_gateway_dispatch(event=event, gateway=SimpleNamespace())

        self.assertEqual(
            result,
            {"action": "skip", "reason": "commercial-scope-unconfirmed"},
        )
        schedule.assert_not_called()
        alert.assert_called_once()

    def test_pre_gateway_reads_lead_metadata_from_event_raw(self):
        source = SimpleNamespace(
            platform=SimpleNamespace(value="whatsapp"),
            user_id=CHAT,
            chat_id=CHAT,
        )
        event = SimpleNamespace(
            source=source,
            text=LEAD_MESSAGE,
            raw_message={"messageId": "in-meta"},
            raw={
                "leadMetadata": {
                    "origin": "FB_Ads",
                    "ad_title": "Tratamento para dependência emocional com Dr. Rodrigo",
                    "ctwa_clid": "clid-therapify",
                }
            },
            is_historical=False,
        )
        media_info = {
            "has_media": False,
            "media_type": None,
            "media_urls": [],
            "message_id": "in-meta",
        }
        with mock.patch.object(wm, "_get_media_info", return_value=media_info), \
             mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
             mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
             mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
             mock.patch.object(wm, "_fetch_chat_history", return_value=""), \
             mock.patch.object(wm, "_complete_pending_panel_unblock"), \
             mock.patch.object(
                 wm,
                 "_ensure_contact_ai_access",
                 return_value=(False, "commercial-scope-unconfirmed"),
             ) as ensure_access, \
             mock.patch.object(wm, "_followup_cancel"):
            wm.pre_gateway_dispatch(event=event, gateway=SimpleNamespace())

        metadata = ensure_access.call_args.kwargs["commercial_metadata"]
        self.assertEqual(metadata["origin"], "FB_Ads")
        self.assertEqual(
            metadata["ad_title"],
            "Tratamento para dependência emocional com Dr. Rodrigo",
        )
        self.assertEqual(metadata["ctwa_clid"], "clid-therapify")

    def test_first_admitted_delivery_is_always_the_complete_fase1(self):
        captured = []
        opening_flags = []

        def deliver(_chat_id, text, **kwargs):
            captured.append(text)
            opening_flags.append(kwargs.get("opening_delivery"))
            return "wamid.first"

        inbound = {
            "message_id": "in-camilla",
            "at": 100.0,
            "text": LEAD_MESSAGE,
        }
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_partial_reply_for_turn", return_value={}), \
             mock.patch.object(wm, "_ritmo_wait_before_send", return_value=True), \
             mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), \
             mock.patch.object(wm, "_bot_has_spoken", return_value=False), \
             mock.patch.object(wm, "_save_partial_reply", return_value=True), \
             mock.patch.object(wm, "_deliver_contact_reply", side_effect=deliver), \
             mock.patch.object(wm, "_complete_contact_send"), \
             mock.patch.object(wm, "_followup_register_outbound"), \
             mock.patch.object(wm, "_maybe_start_playbook_completion"):
            sent = wm._schedule_contact_reply(
                CHAT,
                "Olá! Tudo bem? Você gostaria de saber mais?",
                "turn-camilla",
                consumed_inbound_token=("in-camilla", 100.0),
                inbound_snapshot=inbound,
            )

        self.assertTrue(sent)
        self.assertEqual(captured, [FASE1])
        self.assertEqual(opening_flags, [True])

    def test_existing_conversation_does_not_repeat_complete_fase1(self):
        with mock.patch.object(wm, "_bot_has_spoken", return_value=True):
            result = wm._enforce_therapify_first_outbound(
                FASE1,
                chat_id=CHAT,
            )

        self.assertEqual(
            result,
            "Para entender melhor o seu caso: tem quanto tempo que terminaram? "
            "Como você vem lidando com tudo isso?",
        )

    def test_opening_does_not_start_without_durable_cursor(self):
        inbound = {"message_id": "in-1", "at": 100.0, "text": LEAD_MESSAGE}
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_partial_reply_for_turn", return_value={}), \
             mock.patch.object(wm, "_ritmo_wait_before_send", return_value=True), \
             mock.patch.object(wm, "_ritmo_send_window_ok", return_value=True), \
             mock.patch.object(wm, "_bot_has_spoken", return_value=False), \
             mock.patch.object(wm, "_save_partial_reply", return_value=False), \
             mock.patch.object(wm, "_schedule_model_retry", return_value=True) as retry, \
             mock.patch.object(wm, "_complete_contact_send"), \
             mock.patch.object(wm, "_deliver_contact_reply") as deliver:
            self.assertFalse(wm._schedule_contact_reply(
                CHAT, "texto", "turn-1", consumed_inbound_token=("in-1", 100.0), inbound_snapshot=inbound,
            ))
        deliver.assert_not_called()
        retry.assert_called_once()

    def test_opening_continues_after_normal_message_between_confirmed_bubbles(self):
        sent = []
        newer = {"message_id": "new", "at": 101.0, "text": "Entendi, obrigado"}

        def human_send(_chat_id, text, *, effect_guard, on_message_confirmed, **kwargs):
            for idx, bubble in enumerate(text.split("\n\n")):
                effect_guard(lambda: sent.append(bubble))
                on_message_confirmed(bubble, f"out-{idx}", 100.0 + idx)
            return "out-5"

        with mock.patch.object(wm, "_followup_remember_turn"), \
             mock.patch.object(wm, "_followup_register_outbound"), \
             mock.patch.object(wm, "_mark_bot_spoke"), \
             mock.patch.object(wm, "_clear_unsent_replies"), \
             mock.patch.object(wm, "_clear_inbound"), \
             mock.patch.object(wm, "_maybe_mark_downsell"), \
             mock.patch.object(wm, "_assert_delivery_allowed"), \
             mock.patch.object(wm, "_calendar_mark_offer_delivered"), \
             mock.patch.object(wm, "_split_voice_and_text", return_value=(FASE1, "", "")), \
             mock.patch.object(wm, "_voice_reply_allowed_for", return_value=False), \
             mock.patch.object(wm, "_human_send", side_effect=human_send), \
             mock.patch.object(wm, "_newer_inbound_arrived", side_effect=lambda *_: bool(sent)), \
             mock.patch.object(wm, "_current_inbound_record", return_value=newer):
            wm._deliver_contact_reply(
                CHAT, FASE1, consumed_inbound_token=("old", 100.0),
                inbound_snapshot={"message_id": "old", "at": 100.0, "text": LEAD_MESSAGE},
                opening_delivery=True,
            )

        self.assertEqual(sent, FASE1.split("\n\n"))

    def test_opening_stops_for_new_human_request(self):
        sent = []
        newer = {"message_id": "new", "at": 101.0, "text": "Quero falar com uma pessoa"}

        def human_send(_chat_id, text, *, effect_guard, on_message_confirmed, **kwargs):
            for idx, bubble in enumerate(text.split("\n\n")):
                effect_guard(lambda: sent.append(bubble))
                on_message_confirmed(bubble, f"out-{idx}", 100.0 + idx)
            return "out-5"

        with mock.patch.object(wm, "_followup_remember_turn"), \
             mock.patch.object(wm, "_assert_delivery_allowed"), \
             mock.patch.object(wm, "_calendar_mark_offer_delivered"), \
             mock.patch.object(wm, "_split_voice_and_text", return_value=(FASE1, "", "")), \
             mock.patch.object(wm, "_voice_reply_allowed_for", return_value=False), \
             mock.patch.object(wm, "_human_send", side_effect=human_send), \
             mock.patch.object(wm, "_newer_inbound_arrived", side_effect=lambda *_: bool(sent)), \
             mock.patch.object(wm, "_current_inbound_record", return_value=newer):
            with self.assertRaises(wm.StaleContactReply):
                wm._deliver_contact_reply(
                    CHAT, FASE1, consumed_inbound_token=("old", 100.0),
                    inbound_snapshot={"message_id": "old", "at": 100.0, "text": LEAD_MESSAGE},
                    opening_delivery=True,
                )
        self.assertEqual(sent, [FASE1.split("\n\n")[0]])

    def test_opening_remains_text_even_when_voice_reply_is_available(self):
        with mock.patch.object(wm, "_followup_remember_turn"), \
             mock.patch.object(wm, "_followup_register_outbound"), \
             mock.patch.object(wm, "_mark_bot_spoke"), \
             mock.patch.object(wm, "_clear_unsent_replies"), \
             mock.patch.object(wm, "_clear_inbound"), \
             mock.patch.object(wm, "_maybe_mark_downsell"), \
             mock.patch.object(wm, "_voice_reply_allowed_for", return_value=True), \
             mock.patch.object(wm, "_maybe_send_voice") as voice, \
             mock.patch.object(wm, "_human_send", return_value="out") as text:
            wm._deliver_contact_reply(CHAT, FASE1, inbound_snapshot={"message_id": "in", "at": 1, "text": "oi"}, opening_delivery=True)
        voice.assert_not_called()
        self.assertEqual(text.call_args.args[1], FASE1)

    def test_opening_stops_for_optout_risk_and_untranscribed_voice(self):
        for record in (
            {"message_id": "new", "at": 101.0, "text": "Não me mande mais mensagens"},
            {"message_id": "new", "at": 101.0, "text": "Estou pensando em me matar"},
            {"message_id": "new", "at": 101.0, "text": "", "is_voice": True},
        ):
            with self.subTest(record=record), \
                 mock.patch.object(wm, "_pending_inbound_queue", {}), \
                 mock.patch.object(wm, "_current_inbound_record", return_value=record):
                self.assertFalse(wm._opening_new_inbounds_are_safe(CHAT, ("old", 100.0)))

    def test_opening_checks_risk_and_human_request_beyond_snapshot_limit(self):
        self.assertFalse(wm._opening_text_is_safe("texto " * 500 + " estou pensando em me matar"))
        self.assertFalse(wm._opening_text_is_safe("texto " * 500 + " quero falar com uma pessoa"))

    def test_opening_checks_all_new_messages_not_only_last_one(self):
        prior = {"message_id": "danger", "at": 101.0, "text": "Estou pensando em me matar"}
        latest = {"message_id": "new", "at": 102.0, "text": "Obrigado"}
        with mock.patch.object(wm, "_pending_inbound_queue", {CHAT: [prior, latest]}), \
             mock.patch.object(wm, "_current_inbound_record", return_value=latest):
            self.assertFalse(wm._opening_new_inbounds_are_safe(CHAT, ("old", 100.0)))

    def test_deterministic_opening_does_not_bypass_new_inbound_guards(self):
        inbound = {"message_id": "in-1", "at": 100.0, "text": LEAD_MESSAGE}
        with mock.patch.object(wm, "_current_inbound_record", return_value=inbound), \
             mock.patch.object(wm, "_bot_has_spoken", return_value=False), \
             mock.patch.object(wm, "_playbook_business_window_open", return_value=True), \
             mock.patch.object(wm, "_schedule_deterministic_contact_reply", return_value=True) as schedule:
            self.assertTrue(wm._try_deterministic_contact_fast_path(
                chat_id=CHAT, session_id=CHAT, user_message=LEAD_MESSAGE, is_replay=True,
            ))
        self.assertFalse(schedule.call_args.kwargs["allow_committed_stale"])



if __name__ == "__main__":
    unittest.main()
