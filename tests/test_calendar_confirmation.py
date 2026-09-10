"""Aceite da sugestão de horário: respostas curtas reais do WhatsApp contam como confirmação."""
from __future__ import annotations

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

SLOT = {"start": "2999-01-07T08:00:00-03:00", "end": "2999-01-07T09:00:00-03:00"}


class ConfirmationPresentTest(unittest.TestCase):
    def test_short_acceptances(self):
        for text in [
            "ai funciona", "isso", "Isso mesmo!", "isso aí", "perfeito", "sim", "Sim!", "ok",
            "tá bom", "pode ser", "Boa, funciona pra mim", "fechado", "beleza", "claro",
            "sim, funciona", "exato", "top", "combinado", "pode marcar", "tudo bem",
        ]:
            with self.subTest(text=text):
                self.assertTrue(wm._calendar_confirmation_present(text))

    def test_refusals_and_open_answers(self):
        for text in ["não", "nao funciona", "talvez depois", "outro horário", "não teria amanhã as 8?", ""]:
            with self.subTest(text=text):
                self.assertFalse(wm._calendar_confirmation_present(text))

    def test_accepts_single_offer_with_short_reply(self):
        self.assertEqual(wm._calendar_selected_slot("ai funciona", [SLOT]), SLOT)
        self.assertEqual(wm._calendar_selected_slot("isso", [SLOT]), SLOT)


class ConfirmPromptVariantTest(unittest.TestCase):
    def test_second_prompt_asks_for_explicit_yes(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            first = wm._calendar_visible_reply({"reply_kind": "choice_required", "slots": [SLOT], "confirm_prompts": 1}, "hmm")
            second = wm._calendar_visible_reply({"reply_kind": "choice_required", "slots": [SLOT], "confirm_prompts": 2}, "hmm")
        self.assertIn("Só pra confirmar", first)
        self.assertNotEqual(first, second)
        self.assertIn('"sim"', second)
        self.assertIn("outro horário", second)


if __name__ == "__main__":
    unittest.main()
