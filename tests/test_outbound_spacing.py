"""Cache do cadastro de contatos e espaçamento entre contatos diferentes (2026-09-17)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
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
        self.enterContext(mock.patch.object(wm, "_humanization", return_value={"chat_gap_min_s": 20, "chat_gap_max_s": 20}))

    def test_troca_de_contato_espera_o_intervalo(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.monotonic()})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_B)
        self.assertEqual(sleep.call_count, 1)
        self.assertAlmostEqual(sleep.call_args.args[0], 20, delta=1)

    def test_mesmo_contato_nao_espera(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.monotonic()})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_A)
        sleep.assert_not_called()

    def test_intervalo_ja_passou_nao_espera(self):
        wm._last_outbound.update({"chat": CHAT_A, "at": wm.time.monotonic() - 60})
        with mock.patch.object(wm.time, "sleep") as sleep:
            wm._space_between_chats(CHAT_B)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
