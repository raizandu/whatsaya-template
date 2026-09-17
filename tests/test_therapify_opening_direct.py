"""Fase 1 da Therapify sai na hora, sem modelo e sem espera (decisão de 2026-09-17)."""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
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

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
CHAT = "556181856062@s.whatsapp.net"
SESSION = "20260917_090000_abc"
LEAD_MESSAGE = "Olá! Tenho interesse e queria mais informações, por favor."
INBOUND = {"message_id": "in-1", "at": 1000.0, "text": LEAD_MESSAGE}


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


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

    def _fast_path(self):
        return wm._try_deterministic_contact_fast_path(
            chat_id=CHAT, session_id=SESSION, user_message=LEAD_MESSAGE,
        )

    def test_lead_novo_no_horario_recebe_as_6_bolhas_sem_modelo(self):
        with mock.patch.object(wm, "_playbook_business_window_open", return_value=True):
            self.assertTrue(self._fast_path())
        kwargs = self.scheduled.call_args.kwargs
        self.assertEqual(kwargs["response_text"].split("\n\n"), wm._therapify_first_outbound_bubbles())
        self.assertEqual(len(wm._therapify_first_outbound_bubbles()), 6)
        self.assertEqual(kwargs["consumed_inbound_token"], ("in-1", 1000.0))
        self.assertTrue(kwargs["allow_committed_stale"], "mensagem nova do lead não cancela a Fase 1")

    def test_lead_novo_fora_do_horario_fica_para_o_gate_de_ritmo(self):
        with mock.patch.object(wm, "_playbook_business_window_open", return_value=False):
            self.assertFalse(self._fast_path())
        self.scheduled.assert_not_called()

    def test_bot_ja_falou_nao_reenvia_abertura(self):
        with mock.patch.object(wm, "_bot_has_spoken", return_value=True), \
             mock.patch.object(wm, "_playbook_business_window_open", return_value=True):
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


if __name__ == "__main__":
    unittest.main()
