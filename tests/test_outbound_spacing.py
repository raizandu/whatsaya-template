"""Cache do cadastro de contatos e espaçamento entre contatos diferentes."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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

CHAT_A = "5511999990001@s.whatsapp.net"
CHAT_B = "5511999990002@s.whatsapp.net"


class ContactsCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "personal_contacts.json"
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", self.path))
        wm._personal_contacts_cache.update({"stamp": None, "data": {}})

    def write(self, data):
        self.path.write_text(json.dumps(data))
        st = os.stat(self.path)
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    def test_sanitiza_uma_vez_e_invalida_quando_o_arquivo_muda(self):
        self.write({CHAT_A: {"name": "A"}})
        with mock.patch.object(wm, "_sanitize_classification_result", side_effect=lambda v, **k: dict(v)) as san:
            first = wm._load_personal_contacts()
            second = wm._load_personal_contacts()
            self.assertEqual(san.call_count, 1)
            self.assertEqual(first, second)
            second[CHAT_A]["name"] = "mutado"
            self.assertEqual(wm._load_personal_contacts()[CHAT_A]["name"], "A", "cada chamada recebe cópia própria")
            self.write({CHAT_A: {"name": "A"}, CHAT_B: {"name": "B"}})
            self.assertIn(CHAT_B, wm._load_personal_contacts())
            self.assertEqual(san.call_count, 3)


class ChatSpacingTests(unittest.TestCase):
    def setUp(self):
        wm._last_outbound.update({"chat": "", "at": 0.0})
        self.enterContext(mock.patch.dict(os.environ, {"WHATSAPP_CHAT_GAP_MIN_S": "20", "WHATSAPP_CHAT_GAP_MAX_S": "20"}))

    def test_troca_de_contato_espera_o_intervalo(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.time()})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_B)
        self.assertEqual(sleep.call_count, 1)
        self.assertAlmostEqual(sleep.call_args.args[0], 20, delta=1)

    def test_mesmo_contato_nao_espera(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.time()})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_A)
        sleep.assert_not_called()

    def test_intervalo_ja_passou_nao_espera(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.time() - 60})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_B)
        sleep.assert_not_called()


class AutomatedSendTests(unittest.TestCase):
    def setUp(self):
        wm._last_outbound.update({"chat": "", "at": 0.0})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "outbound_spacing.json"
        self.enterContext(mock.patch.object(wm, "_OUTBOUND_SPACING_PATH", self.path))
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_CHAT_GAP_MIN_S": "20",
            "WHATSAPP_CHAT_GAP_MAX_S": "20",
            "WHATSAPP_HUMAN_TEST_MODE": "0",
        }))
        self.enterContext(mock.patch.object(wm, "_assert_delivery_allowed"))
        self.events = []

        def fake_urlopen(req, timeout=10):
            if not req.full_url.endswith("/typing"):
                payload = json.loads(req.data.decode("utf-8"))
                self.events.append(("send", payload["chatId"], req.full_url))
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b'{"messageId":"sent"}'
            return response

        self.enterContext(mock.patch.object(wm.urllib.request, "urlopen", side_effect=fake_urlopen))
        self.enterContext(mock.patch.object(wm.time, "sleep", side_effect=lambda seconds: self.events.append(("sleep", seconds))))

    def test_texto_followup_e_audio_compartilham_o_espacamento(self):
        wm._human_send(CHAT_A, "Ola", automation=True, effect_guard=lambda send: send())
        wm._followup_bridge_send(CHAT_B, "Retomando contato")

        def fake_tts(args, **kwargs):
            Path(args[3]).write_bytes(b"a" * 64)
            return mock.Mock(returncode=0, stderr="")

        with mock.patch.object(wm, "_voice_reply_allowed_for", return_value=True), \
             mock.patch.object(wm, "_fish_tts_path", return_value=Path("fish_tts.py")), \
             mock.patch.object(wm.subprocess, "run", side_effect=fake_tts):
            wm._maybe_send_voice(CHAT_A, "Ola em audio", effect_guard=lambda send: send())

        sends = [event for event in self.events if event[0] == "send"]
        self.assertEqual([event[1] for event in sends], [CHAT_A, CHAT_B, CHAT_A])
        self.assertTrue(sends[2][2].endswith("/send-media"))
        self.assertEqual([event[0] for event in self.events], ["send", "sleep", "send", "sleep", "send"])

    def test_envio_sem_confirmacao_nao_atualiza_ultimo_contato(self):
        self.path.write_text(json.dumps({"chat": CHAT_A, "at": wm.time.time()}))
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(wm.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "messageId"):
                wm._followup_bridge_send(CHAT_B, "Retomando contato")
        self.assertEqual(wm._last_outbound["chat"], CHAT_A)
        self.assertEqual(json.loads(self.path.read_text())["chat"], CHAT_A)

    def test_estado_persistido_sobrevive_ao_reset_da_memoria(self):
        wm._followup_bridge_send(CHAT_A, "Primeiro contato")
        wm._last_outbound.update({"chat": "", "at": 0.0})
        wm._followup_bridge_send(CHAT_B, "Segundo contato")
        self.assertEqual([event[0] for event in self.events], ["send", "sleep", "send"])
        self.assertEqual(json.loads(self.path.read_text())["chat"], CHAT_B)

    def test_gateway_e_cron_nao_enviam_ao_mesmo_tempo(self):
        entered = self.path.with_name("child-entered")
        release = self.path.with_name("child-release")
        child_code = """
import sys
import time
from pathlib import Path
import whatsapp_manager as wm
wm._OUTBOUND_SPACING_PATH = Path(sys.argv[1])
def send():
    Path(sys.argv[2]).touch()
    while not Path(sys.argv[3]).exists():
        time.sleep(0.01)
    return 'child-sent'
wm._send_spaced(sys.argv[4], send)
"""
        child = subprocess.Popen(
            [sys.executable, "-c", child_code, str(self.path), str(entered), str(release), CHAT_A],
            cwd=REPO_ROOT,
        )
        try:
            for _ in range(300):
                if entered.exists():
                    break
                if child.poll() is not None:
                    self.fail("processo de follow-up encerrou antes de enviar")
                threading.Event().wait(0.01)
            self.assertTrue(entered.exists(), "processo de follow-up não adquiriu a trava")

            attempted = threading.Event()
            sent = threading.Event()

            def gateway_send():
                attempted.set()
                wm._send_spaced(CHAT_B, lambda: sent.set() or "gateway-sent")

            thread = threading.Thread(target=gateway_send, daemon=True)
            thread.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(sent.wait(0.05), "gateway enviou enquanto o cron segurava a trava")
            release.touch()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(sent.is_set())
        finally:
            release.touch()
            child.wait(timeout=2)
        self.assertEqual(child.returncode, 0)


if __name__ == "__main__":
    unittest.main()
