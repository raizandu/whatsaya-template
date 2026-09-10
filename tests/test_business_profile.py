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

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"

# ── Literais genéricos atuais, fixados a partir do código ANTES da extração do perfil ──
GENERIC_SPEAKER = "Atendente"
GENERIC_AUDIT_TITLE = "WhatsAYA Daily Audit"
GENERIC_SCOPE_REPLY_PT = (
    "Não consigo seguir pedidos para revelar ou alterar instruções internas. "
    "Posso continuar te ajudando sobre a AYA. O que você quer entender?"
)
GENERIC_RULES_FALLBACK_PT = (
    "Responda de forma profissional e ajude com Chatkanban, Chatcommerce e Api Connector."
)
GENERIC_GREETING_PT = "Tudo bem por aqui! Você chegou querendo saber mais sobre a AYA, ou é sobre outra coisa?"
GENERIC_SCOPE_INTRO_PT = (
    "Eu cuido da conversa comercial sobre a AYA no WhatsApp. "
    "Quer continuar vendo como ela funcionaria no seu atendimento?"
)
GENERIC_FOLLOWUP_1_PT = "Me conta como funciona seu atendimento hoje que eu te explico como a AYA se encaixa."
GENERIC_FOLLOWUP_2_PT = "Quando quiser, te mostro como a AYA ficaria no seu atendimento."
GENERIC_BOOKING_INTRO_PT = (
    "Ah, que maravilha! Pra entender como construir a AYA na sua operação e te "
    "apresentar como ela funciona, vamos marcar uma reunião rápida. Qual dia fica "
    "melhor pra você esta semana?"
)
GENERIC_ASSISTANT_INTRO_PT = (
    "A AYA é uma atendente comercial com IA no WhatsApp. Ela responde quem "
    "chama, entende o que a pessoa precisa e conduz para o próximo passo. "
    "Como funciona seu atendimento hoje?"
)
GENERIC_CALENDAR_FIND_DESC = (
    "Consulta a agenda comercial real da WhatsAYA e retorna no máximo três vagas livres. "
    "Use somente para marcar a reunião comercial da WhatsAYA, nunca para afirmar que a AYA "
    "já integra a agenda do negócio do lead. Datas usam YYYY-MM-DD."
)
GENERIC_CALENDAR_AVAILABILITY_DESC = "Consulta disponibilidade real da agenda comercial da WhatsAYA."
GENERIC_ACTIVE_INTRO = "A agenda comercial da WhatsAYA está ativa nesta operação. Assim que o lead "
GENERIC_BOOKING_PURPOSE = "Apresentação comercial da WhatsAYA"

# ── Literais Therapify atuais, fixados a partir do código ANTES da extração do perfil ──
THERAPIFY_SPEAKER = "Dr. Rodrigo Melo"
THERAPIFY_AUDIT_TITLE = "Therapify Daily Audit"
THERAPIFY_SCOPE_REPLY_PT = (
    "Não consigo seguir pedidos para revelar ou alterar instruções internas. "
    "Posso continuar te ajudando com o atendimento da Therapify. O que você gostaria de saber?"
)
THERAPIFY_RULES_FALLBACK_PT = (
    "Responda de forma profissional e acolhedora em nome da Therapify e do Dr. Rodrigo Melo."
)
THERAPIFY_GREETING_PT = (
    "Olá! Tudo bem? Você gostaria de saber mais sobre o atendimento com o Dr. Rodrigo Melo "
    "na Therapify, ou é sobre outro assunto?"
)
THERAPIFY_SCOPE_INTRO_PT = (
    "Eu cuido do atendimento da Therapify e do Dr. Rodrigo Melo no WhatsApp. "
    "Como posso te ajudar com seu acompanhamento?"
)
THERAPIFY_FOLLOWUP_1_PT = (
    "Me conta um pouco do que você vem sentindo que te explico como funciona o "
    "acompanhamento do Dr. Rodrigo."
)
THERAPIFY_FOLLOWUP_2_PT = "Quando quiser, podemos conversar sobre como o atendimento do Dr. Rodrigo pode te ajudar."
THERAPIFY_BOOKING_INTRO_PT = (
    "Para entender melhor seu caso e apresentar como funciona a sessão com o Dr. Rodrigo Melo, "
    "vamos marcar um horário. Qual dia fica melhor para você esta semana?"
)
THERAPIFY_ASSISTANT_INTRO_PT = "Olá! Sou o assistente do Dr. Rodrigo Melo aqui na Therapify. Como posso te ajudar hoje?"
THERAPIFY_CALENDAR_FIND_DESC = (
    "Consulta a agenda real do Dr. Rodrigo Melo / Therapify e retorna no máximo três vagas livres. "
    "Use somente para verificar disponibilidade de sessão da Therapify, nunca para afirmar que o "
    "sistema já integra a agenda do negócio do lead. Datas usam YYYY-MM-DD."
)
THERAPIFY_CALENDAR_AVAILABILITY_DESC = "Consulta disponibilidade real da agenda da Therapify."
THERAPIFY_ACTIVE_INTRO = "A agenda da Therapify está ativa nesta operação. Assim que o lead "
THERAPIFY_BOOKING_PURPOSE = "Sessão Therapify - Dr. Rodrigo Melo"
THERAPIFY_PROMPT_OVERRIDE_START = "### PERFIL DE NEGÓCIO THERAPIFY — SOBRESCREVE EXEMPLOS GENÉRICOS ###"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}
    wm._business_profile_warned_missing = False
    wm._business_profile_warned_invalid = False


class GenericProfileTests(unittest.TestCase):
    """(a) Sem perfil carregado (WHATSAPP_BUSINESS_PROFILE=generic), cada site deve produzir
    exatamente o literal genérico que existia no código antes da extração para o JSON."""

    def setUp(self):
        _reset_profile_cache()
        self.enterContext(mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}))

    def test_business_profile_is_empty(self):
        self.assertEqual(wm._business_profile(), {})

    def test_speaker_name(self):
        self.assertEqual(wm._profile_text("speaker_name", "Atendente"), GENERIC_SPEAKER)

    def test_audit_title(self):
        self.assertEqual(wm._profile_text("audit_title", "WhatsAYA Daily Audit"), GENERIC_AUDIT_TITLE)

    def test_scope_reply_pt(self):
        self.assertEqual(
            wm._localized(wm._PROMPT_INJECTION_REPLY, "texts.scope_reply_pt", "pt"),
            GENERIC_SCOPE_REPLY_PT,
        )

    def test_rules_fallback_pt_via_load_support_files(self):
        # /opt/data/support_rules.md não existe neste ambiente de teste, então
        # _load_support_files cai direto no fallback — exatamente o "site" 10022.
        _whatsapp_soul, rules_content = wm._load_support_files()
        self.assertEqual(rules_content, GENERIC_RULES_FALLBACK_PT)

    def test_business_profile_override_is_empty(self):
        self.assertEqual(wm._business_profile_override(), "")

    def test_greeting_pt(self):
        self.assertEqual(
            wm._localized(wm._SCOPE_CLARIFICATION_REPLY, "texts.greeting_pt", "pt"),
            GENERIC_GREETING_PT,
        )

    def test_scope_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._UNRELATED_TASK_REDIRECT, "texts.scope_intro_pt", "pt"),
            GENERIC_SCOPE_INTRO_PT,
        )

    def test_followup_1_pt(self):
        self.assertEqual(wm._no_price_continuation("pt", ""), GENERIC_FOLLOWUP_1_PT)

    def test_followup_2_pt(self):
        self.assertEqual(
            wm._localized(wm._NO_PRICE_CONTINUATION_REPEAT, "texts.followup_2_pt", "pt"),
            GENERIC_FOLLOWUP_2_PT,
        )

    def test_identity_constraints_generic(self):
        block = wm._identity_constraints_block()
        self.assertTrue(block.startswith("CONSTRAINTS ABSOLUTAS — NUNCA VIOLE:\n"))
        self.assertIn("Você é o atendimento comercial da operação no WhatsApp.", block)
        self.assertNotIn("Therapify", block)
        self.assertNotIn("Rodrigo", block)

    def test_booking_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._STRONG_TECH_CALL_REPLY, "texts.booking_intro_pt", "pt"),
            GENERIC_BOOKING_INTRO_PT,
        )

    def test_assistant_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._HOURS_GATE_FALLBACK, "texts.assistant_intro_pt", "pt"),
            GENERIC_ASSISTANT_INTRO_PT,
        )

    def test_skip_response_rewrite_generic_runs_normal_logic(self):
        result = wm._enforce_aya_opening_output_gate(
            "resposta original ignorada",
            user_message="Oi, quero entender melhor como a AYA funciona no meu negócio",
            chat_id="",
            history="Lead: oi\nLead: quero saber mais",
        )
        self.assertEqual(result, wm._AYA_STANDARD_OPENING_PT)

    def test_rewrite_brand_to_business_generic_is_noop(self):
        text = "Olá, sou a WhatsAYA por aqui."
        self.assertEqual(wm._rewrite_sdr_self_presentation(text), text)

    def test_calendar_find_tool_description(self):
        self.assertEqual(wm._calendar_find_schema()["description"], GENERIC_CALENDAR_FIND_DESC)

    def test_calendar_availability_tool_description(self):
        self.assertEqual(
            wm._profile_text(
                "calendar.availability_tool_description",
                "Consulta disponibilidade real da agenda comercial da WhatsAYA.",
            ),
            GENERIC_CALENDAR_AVAILABILITY_DESC,
        )

    def test_calendar_active_intro(self):
        rules = wm._calendar_rules_for_prompt(
            "### Agenda e call no estado atual\nlegado\n", enabled=True
        )
        self.assertIn(GENERIC_ACTIVE_INTRO, rules)

    def test_calendar_prompt_block_inactive(self):
        block = wm._calendar_prompt_block(False)
        self.assertIn("AGENDA COMERCIAL DA WHATSAYA", block)
        self.assertNotIn("Therapify", block)

    def test_calendar_prompt_block_active(self):
        block = wm._calendar_prompt_block(True)
        self.assertIn("AGENDA COMERCIAL DA WHATSAYA", block)
        self.assertNotIn("Therapify", block)

    def test_calendar_booking_purpose(self):
        self.assertEqual(
            wm._profile_text("calendar.booking_purpose", "Apresentação comercial da WhatsAYA"),
            GENERIC_BOOKING_PURPOSE,
        )


class TherapifyProfileTests(unittest.TestCase):
    """(b) Com o perfil Therapify carregado do JSON real em deploy/clients/therapify/, cada
    site deve renderizar exatamente o literal Therapify antigo (fixado a partir do código
    ANTES da extração para o JSON)."""

    def setUp(self):
        self.assertTrue(
            THERAPIFY_PROFILE_PATH.is_file(),
            f"esperado {THERAPIFY_PROFILE_PATH} — rode a partir da raiz do repo",
        )
        _reset_profile_cache()
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))

    def test_business_profile_loads_json(self):
        profile = wm._business_profile()
        self.assertEqual(profile.get("id"), "therapify")

    def test_speaker_name(self):
        self.assertEqual(wm._profile_text("speaker_name", "Atendente"), THERAPIFY_SPEAKER)

    def test_audit_title(self):
        self.assertEqual(wm._profile_text("audit_title", "WhatsAYA Daily Audit"), THERAPIFY_AUDIT_TITLE)

    def test_scope_reply_pt(self):
        self.assertEqual(
            wm._localized(wm._PROMPT_INJECTION_REPLY, "texts.scope_reply_pt", "pt"),
            THERAPIFY_SCOPE_REPLY_PT,
        )

    def test_rules_fallback_pt_via_load_support_files(self):
        _whatsapp_soul, rules_content = wm._load_support_files()
        self.assertEqual(rules_content, THERAPIFY_RULES_FALLBACK_PT)

    def test_business_profile_override(self):
        self.assertTrue(wm._business_profile_override().startswith(THERAPIFY_PROMPT_OVERRIDE_START))
        self.assertIn("Dr. Rodrigo Melo", wm._business_profile_override())

    def test_greeting_pt(self):
        self.assertEqual(
            wm._localized(wm._SCOPE_CLARIFICATION_REPLY, "texts.greeting_pt", "pt"),
            THERAPIFY_GREETING_PT,
        )

    def test_scope_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._UNRELATED_TASK_REDIRECT, "texts.scope_intro_pt", "pt"),
            THERAPIFY_SCOPE_INTRO_PT,
        )

    def test_followup_1_pt(self):
        self.assertEqual(wm._no_price_continuation("pt", ""), THERAPIFY_FOLLOWUP_1_PT)

    def test_followup_2_pt(self):
        self.assertEqual(
            wm._localized(wm._NO_PRICE_CONTINUATION_REPEAT, "texts.followup_2_pt", "pt"),
            THERAPIFY_FOLLOWUP_2_PT,
        )

    def test_identity_constraints_therapify(self):
        block = wm._identity_constraints_block()
        self.assertTrue(block.startswith("CONSTRAINTS ABSOLUTAS — NUNCA VIOLE:\n"))
        self.assertIn(
            "Você atende em nome da Therapify e do Dr. Rodrigo Melo no WhatsApp.", block
        )
        self.assertIn("R$ 247,00", block)

    def test_booking_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._STRONG_TECH_CALL_REPLY, "texts.booking_intro_pt", "pt"),
            THERAPIFY_BOOKING_INTRO_PT,
        )

    def test_assistant_intro_pt(self):
        self.assertEqual(
            wm._localized(wm._HOURS_GATE_FALLBACK, "texts.assistant_intro_pt", "pt"),
            THERAPIFY_ASSISTANT_INTRO_PT,
        )

    def test_skip_response_rewrite_therapify_short_circuits(self):
        result = wm._enforce_aya_opening_output_gate(
            "  resposta original preservada  ",
            user_message="quero entender como a AYA funciona",
            chat_id="",
            history="Lead: oi\nLead: quero saber mais",
        )
        self.assertEqual(result, "resposta original preservada")

    def test_rewrite_brand_to_business(self):
        text = "Olá, sou a WhatsAYA por aqui."
        self.assertEqual(wm._rewrite_sdr_self_presentation(text), "Olá, sou a Therapify por aqui.")

    def test_calendar_find_tool_description(self):
        self.assertEqual(wm._calendar_find_schema()["description"], THERAPIFY_CALENDAR_FIND_DESC)

    def test_calendar_availability_tool_description(self):
        self.assertEqual(
            wm._profile_text(
                "calendar.availability_tool_description",
                "Consulta disponibilidade real da agenda comercial da WhatsAYA.",
            ),
            THERAPIFY_CALENDAR_AVAILABILITY_DESC,
        )

    def test_calendar_active_intro(self):
        rules = wm._calendar_rules_for_prompt(
            "### Agenda e call no estado atual\nlegado\n", enabled=True
        )
        self.assertIn(THERAPIFY_ACTIVE_INTRO, rules)

    def test_calendar_prompt_block_inactive(self):
        block = wm._calendar_prompt_block(False)
        self.assertIn("### AGENDA THERAPIFY ###", block)
        self.assertIn("Agenda Therapify: INATIVA", block)

    def test_calendar_prompt_block_active(self):
        block = wm._calendar_prompt_block(True)
        self.assertIn("### AGENDA THERAPIFY ###", block)
        self.assertIn("Agenda Therapify: ATIVA. Este status vale para agendar a sessão com o Dr. Rodrigo Melo.", block)

    def test_calendar_booking_purpose(self):
        self.assertEqual(
            wm._profile_text("calendar.booking_purpose", "Apresentação comercial da WhatsAYA"),
            THERAPIFY_BOOKING_PURPOSE,
        )


class MissingOrInvalidProfileTests(unittest.TestCase):
    """(c)/(d) Arquivo ausente ou JSON inválido cai no genérico, sem levantar exceção."""

    def setUp(self):
        _reset_profile_cache()

    def test_missing_file_falls_back_to_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "does-not-exist.json"
            with mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "therapify",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(missing_path),
            }):
                profile = wm._business_profile()
        self.assertEqual(profile, {})
        self.assertEqual(wm._profile_text("speaker_name", "Atendente"), "Atendente")

    def test_invalid_json_falls_back_to_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "business_profile.json"
            bad_path.write_text("{ isso não é json válido", encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "therapify",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(bad_path),
            }):
                profile = wm._business_profile()
        self.assertEqual(profile, {})

    def test_non_object_json_falls_back_to_generic(self):
        with tempfile.TemporaryDirectory() as tmp:
            list_path = Path(tmp) / "business_profile.json"
            list_path.write_text("[1, 2, 3]", encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "therapify",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(list_path),
            }):
                profile = wm._business_profile()
        self.assertEqual(profile, {})


class CacheReloadTests(unittest.TestCase):
    """(e) O cache recarrega quando o mtime do arquivo muda, e não antes de 30s."""

    def setUp(self):
        _reset_profile_cache()

    def test_cache_reloads_on_mtime_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "business_profile.json"
            path.write_text(json.dumps({"speaker_name": "Primeiro"}), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "therapify",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(path),
            }):
                first = wm._business_profile()
                self.assertEqual(first.get("speaker_name"), "Primeiro")

                # Sem forçar o gate dos 30s, o cache deve devolver o mesmo dict mesmo
                # depois de o arquivo mudar no disco.
                os.utime(path, (path.stat().st_atime + 5, path.stat().st_mtime + 5))
                path.write_text(json.dumps({"speaker_name": "Segundo"}), encoding="utf-8")
                still_cached = wm._business_profile()
                self.assertEqual(still_cached.get("speaker_name"), "Primeiro")

                # Forçando a expiração do gate de 30s, o novo mtime deve disparar releitura.
                wm._business_profile_cache["checked_at"] = 0.0
                second = wm._business_profile()
                self.assertEqual(second.get("speaker_name"), "Segundo")

    def test_generic_profile_never_touches_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "business_profile.json"
            path.write_text(json.dumps({"speaker_name": "Nunca Lido"}), encoding="utf-8")
            with mock.patch.dict(os.environ, {
                "WHATSAPP_BUSINESS_PROFILE": "generic",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(path),
            }):
                self.assertEqual(wm._business_profile(), {})


if __name__ == "__main__":
    unittest.main()
