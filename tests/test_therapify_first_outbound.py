"""Regressões do primeiro outbound obrigatório da Therapify."""
from __future__ import annotations

import importlib.util
import json
import os
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
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            "WHATSAPP_OWNER_NUMBER": "5521979069520",
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

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
             mock.patch.object(wm, "_schedule_deterministic_contact_reply") as schedule:
            result = wm.pre_gateway_dispatch(event=event, gateway=SimpleNamespace())

        self.assertEqual(
            result,
            {"action": "skip", "reason": "commercial-scope-unconfirmed"},
        )
        schedule.assert_not_called()

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

        def deliver(_chat_id, text, **_kwargs):
            captured.append(text)
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


if __name__ == "__main__":
    unittest.main()
