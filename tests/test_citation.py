from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

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


class InboundFragmentsTests(unittest.TestCase):
    def test_debounce_com_tres_partes(self):
        raw = {
            "debounceIds": ["id1", "id2", "id3"],
            "bodyParts": ["Sim", "Não, só à noite", "Ah, mas dá pra remarcar?"],
        }
        fragments = wm._inbound_fragments(raw, "id3", "ah, mas dá pra remarcar?")
        self.assertEqual(
            fragments,
            [
                {"n": 1, "id": "id1", "text": "Sim"},
                {"n": 2, "id": "id2", "text": "Não, só à noite"},
                {"n": 3, "id": "id3", "text": "Ah, mas dá pra remarcar?"},
            ],
        )

    def test_evento_unico_sem_debounce(self):
        fragments = wm._inbound_fragments({}, "abc123", "Oi tudo bem")
        self.assertEqual(fragments, [{"n": 1, "id": "abc123", "text": "Oi tudo bem"}])

    def test_evento_unico_quando_raw_nao_e_dict(self):
        fragments = wm._inbound_fragments(None, "abc123", "Oi")
        self.assertEqual(fragments, [{"n": 1, "id": "abc123", "text": "Oi"}])

    def test_listas_de_tamanhos_diferentes_cai_no_evento_unico(self):
        raw = {"debounceIds": ["id1", "id2"], "bodyParts": ["Sim"]}
        fragments = wm._inbound_fragments(raw, "id2", "Sim")
        self.assertEqual(fragments, [{"n": 1, "id": "id2", "text": "Sim"}])

    def test_sem_ids_devolve_lista_vazia(self):
        self.assertEqual(wm._inbound_fragments(None, "", ""), [])
        self.assertEqual(
            wm._inbound_fragments({"debounceIds": [], "bodyParts": []}, "", ""), []
        )


class CitationPromptBlockTests(unittest.TestCase):
    def test_vazio_devolve_string_vazia(self):
        self.assertEqual(wm._citation_prompt_block([]), "")
        self.assertEqual(wm._citation_prompt_block(None), "")

    def test_um_fragmento(self):
        block = wm._citation_prompt_block([{"n": 1, "text": "Sim"}])
        self.assertIn("### CITAÇÃO ###", block)
        self.assertIn('[1] "Sim"', block)
        self.assertIn("[[CITA: n]]", block)
        self.assertIn("### FIM CITAÇÃO ###", block)

    def test_tres_fragmentos_numerados_em_ordem(self):
        fragments = [
            {"n": 1, "text": "Sim"},
            {"n": 2, "text": "Não, só à noite"},
            {"n": 3, "text": "Beleza"},
        ]
        block = wm._citation_prompt_block(fragments)
        self.assertIn('[1] "Sim"', block)
        self.assertIn('[2] "Não, só à noite"', block)
        self.assertIn('[3] "Beleza"', block)

    def test_escape_de_aspas_e_truncamento(self):
        long_text = "a" * 200
        block = wm._citation_prompt_block([{"n": 1, "text": f'ele disse "oi" {long_text}'}])
        self.assertNotIn('"oi"', block.split("\n")[2])
        self.assertIn("disse 'oi'", block)
        self.assertIn("…", block)
        # A linha do fragmento não pode passar de 120 chars de texto + moldura.
        frag_line = next(line for line in block.splitlines() if line.startswith("[1]"))
        self.assertLessEqual(len(frag_line), 130)


class CitationMarkerTests(unittest.TestCase):
    def test_extrai_marcador_basico(self):
        n, clean = wm._extract_citation_marker("[[CITA: 2]] Ok✅")
        self.assertEqual(n, 2)
        self.assertEqual(clean, "Ok✅")

    def test_extrai_ignorando_caixa_e_espacos(self):
        n, clean = wm._extract_citation_marker("[[  cita:3]]Tudo bem")
        self.assertEqual(n, 3)
        self.assertEqual(clean, "Tudo bem")

    def test_texto_sem_marcador_fica_intacto(self):
        n, clean = wm._extract_citation_marker("Sem marcador aqui")
        self.assertIsNone(n)
        self.assertEqual(clean, "Sem marcador aqui")

    def test_marcador_fora_do_inicio_nao_e_extraido(self):
        n, clean = wm._extract_citation_marker("Oi [[CITA: 1]] tudo bem")
        self.assertIsNone(n)
        self.assertEqual(clean, "Oi [[CITA: 1]] tudo bem")

    def test_strip_remove_marcador_no_meio(self):
        cleaned = wm._strip_citation_markers("Oi [[CITA: 1]] tudo bem")
        self.assertEqual(cleaned, "Oi tudo bem")

    def test_strip_sem_marcador_fica_intacto(self):
        self.assertEqual(wm._strip_citation_markers("Nada aqui"), "Nada aqui")

    def test_strip_colapsa_espacos_duplos(self):
        cleaned = wm._strip_citation_markers("A [[CITA:1]] [[CITA:2]] B")
        self.assertEqual(cleaned, "A B")


class GatesPreservamMarcadorTests(unittest.TestCase):
    """Os marcadores atravessam transform_llm_output como texto comum."""

    def test_salvage_complete_reply_text_preserva_marcador(self):
        text = "[[CITA: 1]] Ok✅"
        self.assertEqual(wm._salvage_complete_reply_text(text), text)

    def test_strip_wrong_market_money_preserva_marcador(self):
        text = "[[CITA: 1]] Ok✅"
        self.assertEqual(wm._strip_wrong_market_money(text, set()), text)

    def test_vary_repeated_acknowledgement_preserva_marcador(self):
        text = "[[CITA: 1]] Ok✅"
        self.assertEqual(
            wm._vary_repeated_acknowledgement(text, "5511999999999@s.whatsapp.net"),
            text,
        )

    def test_split_human_bubbles_mantem_marcadores_intactos(self):
        text = (
            "[[CITA: 1]] Ok✅\n[[CITA: 2]] Tudo bem\n\n"
            "Rapidamente a gente muda isso."
        )
        bubbles = wm._split_human_bubbles(text)
        self.assertEqual(len(bubbles), 3)
        self.assertTrue(bubbles[0].startswith("[[CITA: 1]]"))
        self.assertTrue(bubbles[1].startswith("[[CITA: 2]]"))


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class HumanSendCitationTests(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = wm.urllib.request.urlopen
        self._captured: list[dict] = []

        def _fake_urlopen(req, timeout=10):
            payload = json.loads(req.data.decode("utf-8"))
            self._captured.append(payload)
            return _FakeResponse({"messageId": f"OUT-{len(self._captured)}"})

        wm.urllib.request.urlopen = _fake_urlopen

    def tearDown(self):
        wm.urllib.request.urlopen = self._orig_urlopen

    def test_bolha_com_cita_sai_com_reply_to_e_sem_marcador(self):
        wm._human_send(
            "5511999999999@s.whatsapp.net",
            "[[CITA: 2]] Perfeito, fechado então.\n\nSem marcador aqui.",
            automation=False,
            effect_guard=None,
            reply_targets={1: "id-1", 2: "id-2"},
        )
        self.assertEqual(len(self._captured), 2)
        first, second = self._captured

        self.assertEqual(first["replyTo"], "id-2")
        self.assertNotIn("[[CITA", first["message"])
        self.assertEqual(first["message"], "Perfeito, fechado então.")

        self.assertNotIn("replyTo", second)
        self.assertEqual(second["message"], "Sem marcador aqui.")

    def test_n_desconhecido_sai_sem_reply_to_e_sem_marcador(self):
        wm._human_send(
            "5511999999999@s.whatsapp.net",
            "[[CITA: 9]] Beleza, combinado.",
            automation=False,
            effect_guard=None,
            reply_targets={1: "id-1"},
        )
        self.assertEqual(len(self._captured), 1)
        payload = self._captured[0]
        self.assertNotIn("replyTo", payload)
        self.assertNotIn("[[CITA", payload["message"])
        self.assertEqual(payload["message"], "Beleza, combinado.")

    def test_nenhum_payload_carrega_o_marcador_cru(self):
        wm._human_send(
            "5511999999999@s.whatsapp.net",
            "[[CITA: 1]] Bolha um.\n\n[[CITA: 2]] Bolha dois.\n\nBolha três sem marcador.",
            automation=False,
            effect_guard=None,
            reply_targets={1: "id-1", 2: "id-2"},
        )
        self.assertTrue(self._captured)
        for payload in self._captured:
            self.assertNotIn("[[CITA", payload["message"])


if __name__ == "__main__":
    unittest.main()
