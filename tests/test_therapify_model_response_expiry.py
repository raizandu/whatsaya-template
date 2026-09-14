"""Regressões para impedir a entrega de respostas LLM envelhecidas.

O teste de integração abaixo atravessa ``transform_llm_output`` apenas até o
gate de expiração. Os efeitos externos (WhatsApp, calendário e scheduler) são
substituídos por seams locais para deixar explícito que uma resposta antiga é
descartada e que o mesmo inbound é reprocessado na próxima janela.
"""
from __future__ import annotations

import datetime
import importlib.util
import os
import sys
import unittest
from pathlib import Path
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


CHAT = "556281405459@s.whatsapp.net"
TURN_KEY = f"{CHAT}:turn-expired"
TOKEN = ("inbound-expired", 100.0)
SNAPSHOT = {
    "message_id": TOKEN[0],
    "at": TOKEN[1],
    "text": "Oi, gostaria de entender melhor",
    "_turn_created_at": 1_000.0,
}


class _FakeFollowupEngine:
    hours = object()

    def __init__(self):
        self.calls: list[dict] = []

    def schedule_resume(
        self,
        chat_id,
        *,
        due,
        reason,
        at,
        off_days_ok,
        replace_pending_reason,
    ):
        self.calls.append(
            {
                "chat_id": chat_id,
                "due": due,
                "reason": reason,
                "at": at,
                "off_days_ok": off_days_ok,
                "replace_pending_reason": replace_pending_reason,
            }
        )
        return "resume-expired"


class TherapifyModelResponseExpiryTests(unittest.TestCase):
    def setUp(self):
        wm._turn_inflight.discard(TURN_KEY)
        wm._turn_sent.discard(TURN_KEY)
        wm._turn_inbound.pop(TURN_KEY, None)

    def test_configured_limit_is_strict_and_uses_turn_creation_time(self):
        with mock.patch.object(wm, "_profile_lookup", return_value=480):
            self.assertEqual(wm._max_model_response_age_s(), 480)
            self.assertFalse(
                wm._model_response_expired(SNAPSHOT, now=1_480.0),
                "o limite é inclusivo no instante exato dos 8 minutos",
            )
            self.assertTrue(wm._model_response_expired(SNAPSHOT, now=1_480.01))

        self.assertFalse(
            wm._model_response_expired(
                {"message_id": TOKEN[0], "at": TOKEN[1]},
                now=9_999.0,
            ),
            "sem _turn_created_at não há idade de geração a inferir",
        )

    def test_missing_or_invalid_therapify_delivery_profile_keeps_safe_default(self):
        with mock.patch.object(
            type(wm.config),
            "whatsapp_business_profile",
            new_callable=mock.PropertyMock,
            return_value="therapify",
        ):
            with mock.patch.object(wm, "_profile_lookup", return_value=None):
                self.assertEqual(wm._max_model_response_age_s(), 480)
            with mock.patch.object(wm, "_profile_lookup", return_value="inválido"):
                self.assertEqual(wm._max_model_response_age_s(), 480)
            with mock.patch.object(wm, "_profile_lookup", return_value=0):
                self.assertEqual(wm._max_model_response_age_s(), 480)

    def test_expired_transform_suppresses_old_reply_and_schedules_regeneration(self):
        retry = mock.Mock(return_value=True)
        with mock.patch.object(
            wm, "_session_is_owner", return_value=False
        ), mock.patch.object(
            wm, "_select_transform_turn", return_value=(TURN_KEY, dict(SNAPSHOT))
        ), mock.patch.object(
            wm, "_current_inbound_record", return_value=dict(SNAPSHOT)
        ), mock.patch.object(
            wm, "_calendar_state_for_turn", return_value={}
        ), mock.patch.object(
            wm, "_model_response_expired", return_value=True
        ), mock.patch.object(
            wm, "_schedule_model_retry", retry
        ), mock.patch.object(
            wm, "_note_unsent_reply"
        ) as note_unsent, mock.patch.object(
            wm, "_clear_inbound"
        ) as clear_inbound, mock.patch.object(
            wm, "_complete_contact_send"
        ) as complete_send:
            result = wm.transform_llm_output(
                platform="whatsapp",
                session_id=CHAT,
                turn_id="core-turn-expired",
                response_text="Resposta gerada tarde demais",
            )

        self.assertEqual(result, "\n")
        note_unsent.assert_called_once_with(
            CHAT,
            "Resposta gerada tarde demais",
            "resposta do modelo expirou",
        )
        retry.assert_called_once_with(
            CHAT,
            "model_response_expired",
            turn_key=TURN_KEY,
        )
        clear_inbound.assert_called_once_with(CHAT, expected_token=TOKEN)
        complete_send.assert_called_once_with(
            TURN_KEY,
            delivered=False,
            uncertain=False,
        )

    def test_confirmed_booking_bypasses_expiry_and_delivers_verified_reply(self):
        schedule = mock.Mock(return_value=True)
        reserve = mock.Mock(return_value=(True, TURN_KEY))
        booked = {"kind": "booked", "inbound_token": TOKEN}
        with mock.patch.object(
            wm, "_session_is_owner", return_value=False
        ), mock.patch.object(
            wm, "_select_transform_turn", return_value=(TURN_KEY, dict(SNAPSHOT))
        ), mock.patch.object(
            wm, "_current_inbound_record", return_value=dict(SNAPSHOT)
        ), mock.patch.object(
            wm, "_calendar_state_for_turn", return_value=booked
        ), mock.patch.object(
            wm, "_model_response_expired", return_value=True
        ), mock.patch.object(
            wm, "_calendar_visible_reply", return_value="Agendamento confirmado."
        ), mock.patch.object(
            wm, "_enforce_therapify_clinical_calm", side_effect=lambda text, **_: text
        ), mock.patch.object(
            wm, "_extract_handoff_details", return_value=("Agendamento confirmado.", None, None)
        ), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={}
        ), mock.patch.object(
            wm, "_enforce_internal_role_output_gate", side_effect=lambda text, **_: text
        ), mock.patch.object(
            wm, "_enforce_therapify_playbook_order", side_effect=lambda text, **_: text
        ), mock.patch.object(
            wm, "_prepare_contact_reply", side_effect=lambda text: text
        ), mock.patch.object(
            wm, "_reserve_contact_send", reserve
        ), mock.patch.object(
            wm, "_schedule_contact_reply", schedule
        ):
            result = wm.transform_llm_output(
                platform="whatsapp",
                session_id=CHAT,
                turn_id="core-turn-booked",
                response_text="Resposta velha do modelo",
            )

        self.assertEqual(result, "\n")
        reserve.assert_called_once()
        schedule.assert_called_once()
        self.assertTrue(schedule.call_args.kwargs["allow_committed_stale"])

    def test_model_expiry_retry_uses_next_business_window(self):
        now = datetime.datetime(2026, 9, 14, 10, 0, tzinfo=datetime.UTC)
        due = now + datetime.timedelta(minutes=5)
        engine = _FakeFollowupEngine()
        with mock.patch.object(wm, "_followup_enabled", return_value=True), mock.patch.object(
            wm, "_followup_engine", return_value=engine
        ), mock.patch.object(wm, "_hum_now", return_value=now), mock.patch.object(
            wm, "next_business_time", return_value=due
        ) as next_window:
            self.assertTrue(
                wm._schedule_model_retry(
                    CHAT,
                    "model_response_expired",
                    turn_key=TURN_KEY,
                )
            )

        next_window.assert_called_once_with(now + datetime.timedelta(seconds=5), engine.hours)
        self.assertEqual(engine.calls, [{
            "chat_id": CHAT,
            "due": due,
            "reason": f"model_response_expired:{TURN_KEY}",
            "at": now,
            "off_days_ok": False,
            "replace_pending_reason": True,
        }])


if __name__ == "__main__":
    unittest.main()
