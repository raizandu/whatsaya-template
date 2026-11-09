"""Fase 1 da Therapify: espera de Lead Novo antes, depois as 6 bolhas em sequência sem modelo (2026-09-17)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

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
SESSION = "20260917_090000_abc"
LEAD_MESSAGE = "Olá! Tenho interesse e queria mais informações, por favor."
INBOUND = {"message_id": "in-1", "at": 1000.0, "text": LEAD_MESSAGE}
BRT = ZoneInfo("America/Sao_Paulo")


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


def _brt(year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=BRT).astimezone(dt.UTC)


class Fase1DiretaTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(mock.patch.object(wm, "_current_inbound_record", return_value=dict(INBOUND)))
        self.enterContext(mock.patch.object(wm, "_bot_has_spoken", return_value=False))
        self.scheduled = self.enterContext(
            mock.patch.object(wm, "_schedule_deterministic_contact_reply", return_value=True)
        )

    def _fast_path(self, is_replay=True):
        return wm._try_deterministic_contact_fast_path(
            chat_id=CHAT, session_id=SESSION, user_message=LEAD_MESSAGE, is_replay=is_replay,
        )

    def test_primeiro_inbound_respeita_a_espera_de_lead_novo(self):
        # Não é replay: o gate de ritmo cria o job de 12–35 min; nada sai agora.
        with mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 6, 10)):
            self.assertFalse(self._fast_path(is_replay=False))
        self.scheduled.assert_not_called()

    def test_retomada_de_lead_novo_recebe_as_6_bolhas_sem_modelo(self):
        with mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 6, 10)):
            self.assertTrue(self._fast_path())
        kwargs = self.scheduled.call_args.kwargs
        self.assertEqual(kwargs["response_text"].split("\n\n"), wm._therapify_first_outbound_bubbles())
        self.assertEqual(len(wm._therapify_first_outbound_bubbles()), 6)
        self.assertEqual(kwargs["consumed_inbound_token"], ("in-1", 1000.0))
        self.assertFalse(kwargs["allow_committed_stale"], "a guarda por bolha deve avaliar mensagens novas")

    def test_lead_novo_fora_do_horario_fica_para_o_gate_de_ritmo(self):
        with mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 6, 21, 30)):
            self.assertFalse(self._fast_path())
        self.scheduled.assert_not_called()

    def test_retomada_no_sabado_a_tarde_recebe_as_6_bolhas_sem_modelo(self):
        with mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 7, 16, 30)):
            self.assertTrue(self._fast_path())
        self.assertEqual(
            self.scheduled.call_args.kwargs["response_text"].split("\n\n"),
            wm._therapify_first_outbound_bubbles(),
        )

    def test_sabado_antes_das_16h_e_depois_das_21h_nada_sai(self):
        for now in (_brt(2026, 11, 7, 15), _brt(2026, 11, 7, 21, 30)):
            with self.subTest(now=now), mock.patch.object(wm, "_hum_now", return_value=now):
                self.assertFalse(self._fast_path())
        self.scheduled.assert_not_called()

    def test_fase3_continua_bloqueada_no_sabado_a_tarde(self):
        effect = mock.Mock()
        with mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 7, 16, 30)), \
             mock.patch.object(wm, "_therapify_crisis_is_active", return_value=False), \
             mock.patch.object(wm, "_newer_inbound_arrived", return_value=False):
            self.assertFalse(wm._playbook_business_window_open())
            with self.assertRaises(wm.DeliveryBlocked):
                wm._run_playbook_effect(CHAT, ("in-1", 1000.0), effect)
        effect.assert_not_called()

    def test_bot_ja_falou_nao_reenvia_abertura(self):
        with mock.patch.object(wm, "_bot_has_spoken", return_value=True), \
             mock.patch.object(wm, "_hum_now", return_value=_brt(2026, 11, 6, 10)):
            self.assertFalse(self._fast_path())
        self.scheduled.assert_not_called()

    def test_primeira_saida_nao_espera_pela_categoria(self):
        with mock.patch.object(wm, "_humanization", return_value={"reply_delay_s": {"comum": [15, 210]}}), \
             mock.patch.object(wm, "_session_is_owner", return_value=False), \
             mock.patch.object(wm.time, "sleep") as sleep:
            self.assertTrue(wm._ritmo_wait_before_send(CHAT, "comum", ("in-1", 1000.0)))
        sleep.assert_not_called()

    def test_segundo_turno_espera_a_abertura_em_voo(self):
        other = f"{CHAT}:abertura"
        with wm._turn_lock:
            wm._turn_inflight.add(other)
        self.addCleanup(lambda: wm._turn_inflight.discard(other))
        released = threading.Timer(0.6, lambda: wm._turn_inflight.discard(other))
        released.start()
        wm._wait_other_turns_in_flight(CHAT, turn_key=f"{CHAT}:segundo")
        self.assertNotIn(other, wm._turn_inflight)


class RespostaVaziaNoPrimeiroEnvioTests(unittest.TestCase):
    """07–08/11: o modelo devolveu só `[cat:comum]` na abertura e o lead ficou sem a Fase 1."""

    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            "WHATSAPP_CONFIG_SUBDIR": "generic",
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        turn_key = f"{CHAT}:in-1"
        for name, value in {
            "_session_is_owner": False,
            "_resolve_mapped_chat_id": CHAT,
            "_select_transform_turn": (turn_key, dict(INBOUND)),
            "_current_inbound_record": dict(INBOUND),
            "_calendar_state_for_turn": {},
            "_model_response_expired": False,
            "_inbound_prompt_injection_kind": "",
            "_prompt_injection_kind": "",
            "_unrelated_assistant_task_redirect": "",
            "_contact_record_for_chat": {},
            "_fetch_chat_history": "",
            "_reserve_contact_send": (True, turn_key),
            "_bot_has_spoken": False,
            "_contact_has_explicit_ai_access": True,
        }.items():
            self.enterContext(mock.patch.object(wm, name, return_value=value))
        self.schedule = self.enterContext(mock.patch.object(wm, "_schedule_contact_reply", return_value=True))

    def _transform(self, now, response="[cat:comum]"):
        with mock.patch.object(wm, "_hum_now", return_value=now):
            return wm.transform_llm_output(
                platform="whatsapp", session_id=CHAT, turn_id="in-1", response_text=response,
            )

    def test_resposta_vazia_no_primeiro_envio_vira_fase1(self):
        for now in (_brt(2026, 11, 7, 16, 30), _brt(2026, 11, 6, 10)):
            with self.subTest(now=now):
                self.schedule.reset_mock()
                self.assertEqual(self._transform(now), "\n")
                self.schedule.assert_called_once()
                self.assertEqual(
                    self.schedule.call_args.args[1].split("\n\n"),
                    wm._therapify_first_outbound_bubbles(),
                )

    def test_resposta_vazia_fora_da_janela_continua_em_silencio(self):
        for now in (_brt(2026, 11, 7, 15), _brt(2026, 11, 7, 21, 30)):
            with self.subTest(now=now):
                self.assertEqual(self._transform(now), "\n")
        self.schedule.assert_not_called()

    def test_supressao_legitima_com_texto_vazio_continua_em_silencio(self):
        now = _brt(2026, 11, 7, 16, 30)
        with mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=False):
            self.assertEqual(self._transform(now), "\n")
        with mock.patch.object(wm, "_bot_has_spoken", return_value=True):
            self.assertEqual(self._transform(now), "\n")
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            self.assertEqual(self._transform(now), "\n")
        self.schedule.assert_not_called()

    def test_crise_no_primeiro_contato_nao_vira_fase1(self):
        crisis = dict(INBOUND, text="eu quero me matar")
        with mock.patch.object(wm, "_select_transform_turn", return_value=(f"{CHAT}:in-1", crisis)), \
             mock.patch.object(wm, "_current_inbound_record", return_value=crisis):
            self.assertEqual(self._transform(_brt(2026, 11, 7, 16, 30)), "\n")
        self.schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
