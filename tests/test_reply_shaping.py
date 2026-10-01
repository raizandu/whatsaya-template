from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import whatsapp_manager as wm  # noqa: E402


class ReplyShapingTests(unittest.TestCase):
    def test_prepare_and_split_preserve_abbreviated_clinic_address(self):
        source = (
            "Ah, entendi. A clínica fica na Av. Prof. Joaquim Barreto, 302, "
            "1º andar, sala 04, Centro, Cotia/SP. É no primeiro andar."
        )

        prepared = wm._prepare_contact_reply(source)
        bubbles = wm._split_human_bubbles(prepared)

        delivered_text = " ".join(bubbles)
        self.assertIn("Av. Prof. Joaquim Barreto, 302", delivered_text)
        self.assertIn("1º andar, sala 04, Centro, Cotia/SP", delivered_text)
        self.assertIn("É no primeiro andar.", delivered_text)

    def test_titles_decimals_and_times_do_not_consume_sentence_budget(self):
        source = (
            "Dr. João e Dra. Maria, Sr. Paulo e Sra. Ana atendem na Av. "
            "Prof. Joaquim Barreto, 302. A consulta dura 1.5h e começa às "
            "08.30h. Posso ajudar?"
        )

        prepared = wm._prepare_contact_reply(source)

        for detail in (
            "Dr. João", "Dra. Maria", "Sr. Paulo", "Sra. Ana",
            "Av. Prof. Joaquim Barreto, 302", "1.5h", "08.30h", "Posso ajudar?",
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail, prepared)

    def test_real_five_sentence_limit_still_shortens_the_reply(self):
        source = (
            "Primeira frase. Segunda frase. Terceira frase. "
            "Quarta frase. Quinta frase."
        )

        prepared = wm._prepare_contact_reply(source)

        self.assertIn("Primeira frase.", prepared)
        self.assertNotIn("Quinta frase.", prepared)
        self.assertLess(len(prepared), len(source))

    def test_single_and_compound_questions_keep_existing_behavior(self):
        single = wm._prepare_contact_reply(
            "A clínica fica em Cotia? Você prefere terça?"
        )
        compound = wm._prepare_contact_reply(
            "Você prefere terça ou quinta, de manhã ou à tarde?"
        )

        self.assertEqual(single.count("?"), 1)
        self.assertIn("A clínica fica em Cotia?", single)
        self.assertNotIn("Você prefere terça", single)
        self.assertEqual(compound, "Você prefere terça ou quinta, de manhã ou à tarde?")


if __name__ == "__main__":
    unittest.main()
