"""Restart no meio do atendimento: cursor por bolha e varredura pós-boot (2026-09-17)."""
from __future__ import annotations

import datetime
import json
import time
import unittest
from unittest import mock

from test_humanization import CHAT, RitmoTestCase, _FakeResponse, _brt, wm

OTHER = "5511999990002@s.whatsapp.net"


class CursorPorBolhaTest(unittest.TestCase):
    def test_on_progress_recebe_o_que_falta_apos_cada_bolha(self):
        seen = []
        with mock.patch.object(
            wm.urllib.request, "urlopen",
            side_effect=lambda *a, **k: _FakeResponse(json.dumps({"messageId": "wamid.1"}).encode()),
        ):
            wm._human_send(CHAT, "um\n\ndois\n\ntrês", on_progress=seen.append)
        self.assertEqual(seen, ["dois\n\ntrês", "três", ""])


class VarreduraPosRestartTest(RitmoTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(wm, "_PARTIAL_REPLY_PATH", self.tmp / "partial.json"))
        self.enterContext(mock.patch.object(wm, "_check_chat_silenced", return_value=False))
        self.enterContext(mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True))
        self.now = self.freeze(_brt(2026, 9, 17, 10, 6))
        self.enterContext(mock.patch.object(wm.time, "time", return_value=self.now.timestamp()))

    def test_mensagem_do_lead_sem_resposta_vira_retomada(self):
        t = self.now.timestamp()
        self.add_message("Fase 1", from_me=1, ts=t - 600)
        self.add_message("Sim", from_me=0, ts=t - 60, message_id="in-sim")
        self.assertEqual(wm._recover_after_restart(), 1)
        job = self.only_job()
        self.assertEqual(job["basis_outbound_id"], "resume:pos_restart")
        self.assertEqual(job["chat_id"], CHAT)

    def test_lead_ja_respondido_ou_antigo_nao_gera_job(self):
        t = self.now.timestamp()
        self.add_message("Sim", from_me=0, ts=t - 60)
        self.add_message("resposta do bot", from_me=1, ts=t - 30)
        self.add_message("antiga", from_me=0, ts=t - 3 * 3600, message_id="old")
        self.assertEqual(wm._recover_after_restart(), 0)
        self.assertEqual(self.jobs(), [])

    def test_dono_na_conversa_nao_gera_job(self):
        t = self.now.timestamp()
        self.add_message("Sim", from_me=0, ts=t - 60)
        with mock.patch.object(wm, "_check_chat_silenced", return_value=True):
            self.assertEqual(wm._recover_after_restart(), 0)

    def test_cursor_parcial_vira_retry_das_bolhas_restantes(self):
        tk = f"{CHAT}:abc"
        wm._save_partial_reply(tk, CHAT, "De zero a dez…\n\nAfetando no trabalho?", {
            "message_id": "in-1", "text": "Poucos dias", "at": self.now.timestamp() - 300,
        })
        self.assertEqual(wm._recover_after_restart(), 1)
        job = self.only_job()
        self.assertEqual(job["basis_outbound_id"], f"resume:partial_delivery:{tk}")


if __name__ == "__main__":
    unittest.main()
