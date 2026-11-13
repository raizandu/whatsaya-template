"""Regressões do roteiro clínico calmo e do takeover manual da Therapify."""
from __future__ import annotations

import importlib.util
from contextlib import ExitStack
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
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
_REAL_WRITE_THERAPIFY_CRISIS_STATE = wm._write_therapify_crisis_state


THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
CHAT = "556281405459@s.whatsapp.net"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class TherapifyClinicalCalmTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(wm, "_write_therapify_crisis_state"))
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "WHATSAPP_BUSINESS_PROFILE": "therapify",
                    "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
                    "WHATSAPP_OWNER_NUMBER": "5500000000000",
                },
            )
        )
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def _gate(self, response: str, user_message: str, *, history: str = "") -> str:
        gate = getattr(wm, "_enforce_therapify_clinical_calm", None)
        self.assertIsNotNone(
            gate,
            "RED esperado: falta o seam _enforce_therapify_clinical_calm",
        )
        return gate(response, user_message, CHAT, history)

    def test_suicidal_ideation_gets_support_and_handoff(self):
        response = (
            "Sinto muito. Ligue para o CVV 188 ou procure uma emergência imediatamente.\n\n"
            "[[HANDOFF: risco de vida]]"
        )
        visible = self._gate(
            response,
            "Estou desesperada e pensando em me matar agora.",
        )
        folded = visible.casefold()
        self.assertIn("188", folded)
        self.assertIn("188", folded)
        self.assertNotIn("samu", folded)
        self.assertIn("[[handoff", folded)
        self.assertNotIn("relacionamento", folded)

    def test_non_suicidal_distress_does_not_trigger_crisis(self):
        self.assertFalse(wm._therapify_crisis_detected("estou desesperada com o relacionamento"))
        self.assertFalse(wm._therapify_crisis_detected("vi uma notícia sobre suicídio"))

    def test_direct_self_harm_expressions_trigger_crisis(self):
        for text in ("Quero me matar agora", "penso em tirar minha vida", "vou me cortar"):
            with self.subTest(text=text):
                self.assertTrue(wm._therapify_crisis_detected(text))

    def _calm(self, response, lead_text):
        with mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True) as alert, \
             mock.patch.object(wm, "_fetch_chat_history", return_value=""):
            return wm._enforce_therapify_clinical_calm(response, lead_text, CHAT), alert

    def test_unprompted_emergency_referral_is_replaced_and_owner_reviews(self):
        response = (
            "Sinto muito que esteja passando por isso.\n\n"
            "Você está pensando em se machucar ou em tirar a própria vida neste momento?\n\n"
            "Se houver risco imediato, ligue para o SAMU 192. O CVV atende no 188.\n\n"
            "[[HANDOFF: possível risco]]"
        )
        for lead_text in ("Demora muito\nPreciso de ajuda", "Tenho borderline e bipolar, ansiedade 10"):
            with self.subTest(lead_text=lead_text):
                visible, alert = self._calm(response, lead_text)
                self.assertNotRegex(visible, r"(?i)samu|cvv|188|machucar|HANDOFF")
                self.assertIn("Ok✅", visible)
                alert.assert_called_once()

    def test_venting_about_dying_stays_in_flow_with_urgent_alert(self):
        response = "Sinto muito. Se houver risco imediato, ligue para o SAMU 192.\n\n[[HANDOFF: risco]]"
        for lead_text in ("quero morrer", "não quero mais viver", "tenho vontade de morrer"):
            with self.subTest(lead_text=lead_text):
                self.assertFalse(wm._therapify_crisis_detected(lead_text))
                visible, alert = self._calm(response, lead_text)
                self.assertNotRegex(visible, r"(?i)samu|192|HANDOFF")
                self.assertIn("Ok✅", visible)
                alert.assert_called_once()
                self.assertEqual(alert.call_args.kwargs["thread_name"], "wa-crisis-alert")
                # Prefixo próprio: o cooldown de card ao dono é por tipo de alerta.
                self.assertTrue(alert.call_args.kwargs["event_id"].startswith("death-talk:"))

    def test_venting_alerts_even_when_model_reply_is_already_on_script(self):
        visible, alert = self._calm("Tudo bem", "quero morrer")
        self.assertEqual(visible, "Tudo bem")
        alert.assert_called_once()

    def test_handoff_from_model_on_venting_returns_to_flow(self):
        visible, alert = self._calm("Vou avisar o Rodrigo.\n\n[[HANDOFF: risco]]", "quero morrer")
        self.assertNotIn("HANDOFF", visible)
        alert.assert_called_once()

    def test_longing_is_not_crisis(self):
        self.assertFalse(wm._therapify_crisis_detected("vou morrer de saudade dele"))
        _, alert = self._calm("Tudo bem", "vou morrer de saudade dele")
        alert.assert_not_called()

    def test_concrete_intent_attempt_or_injury_is_crisis(self):
        for lead_text in ("quero me matar", "vou me matar hoje", "tentei morrer", "estou me cortando"):
            with self.subTest(lead_text=lead_text):
                self.assertTrue(wm._therapify_crisis_detected(lead_text))

    def test_vague_distress_never_goes_outside_the_flow(self):
        response = "Sinto muito. Se houver risco imediato, ligue para o SAMU 192.\n\n[[HANDOFF: risco]]"
        for lead_text in ("queria sumir de vez", "não aguento mais", "não consigo viver sem ele"):
            with self.subTest(lead_text=lead_text):
                visible, alert = self._calm(response, lead_text)
                self.assertNotRegex(visible, r"(?i)samu|HANDOFF")
                alert.assert_called_once()

    def test_medical_referrals_from_real_conversations_are_replaced(self):
        lead_text = "tem vários dias que eu não como direito, passo o dia sem comer"
        for response in (
            "[[CITA: 2]] Como você está há vários dias sem comer direito, é importante procurar avaliação médica o quanto antes.",
            "Você conseguiu buscar a avaliação médica que conversamos?",
            "Se puder, peça a alguém de confiança para te acompanhar a uma unidade de saúde.",
            "é importante ter uma avaliação profissional com cuidado. Se estiver fraca, procure uma UPA",
            "Fique perto de alguém de confiança hoje, se puder.",
            "Procure um médico para ver isso",
            "Vale conversar com seu psiquiatra",
            "Marque uma consulta com um nutricionista",
            "Busque ajuda profissional",
            "Ligue 180 para orientação",
            "Ficar dias sem comer merece atenção. Procure atendimento de saúde ainda hoje.",
            "Procure um pronto atendimento.",
        ):
            with self.subTest(response=response):
                visible, alert = self._calm(response, lead_text)
                self.assertNotEqual(visible, response)
                self.assertIn("Ok✅", visible)
                alert.assert_called_once()

    def test_replies_that_only_mention_a_profession_are_kept(self):
        for response in (
            "Sou Psicoterapeuta especializado em Hipnose Clínica",
            "Não sou médico, sou psicoterapeuta",
            "Mas está ajudando amigo?",
            "O valor é 188 reais".replace("188", "197"),
        ):
            with self.subTest(response=response):
                visible, alert = self._calm(response, "você é médico?")
                self.assertEqual(visible, response)
                alert.assert_not_called()

    def test_referral_words_only_inside_internal_tags_keep_model_reply(self):
        # Caso de 09/11: o RESUMO do handoff casava a guarda e o lead ficou sem o preço.
        for response in (
            "O valor da consulta é R$ 247.\n\n[[HANDOFF: dúvida de valor || RESUMO: relata "
            "consulta online anterior, sem identificar o profissional]]",
            "Entendi, me conta mais.\n\n[[HANDOFF: lead já procurou psicólogo antes]]",
            "Entendi.\n\n[cat: emergencia]",
            "Entendi.\n\n[[CITA: 188]]",
        ):
            with self.subTest(response=response):
                visible, alert = self._calm(response, "o valor é 297?")
                self.assertEqual(visible, response)
                alert.assert_not_called()

    def test_visible_referral_with_neutral_handoff_is_still_replaced(self):
        visible, alert = self._calm("Procure avaliação médica.\n\n[[HANDOFF: dúvida]]", "o valor é 297?")
        self.assertNotIn("HANDOFF", visible)
        self.assertIn("Ok✅", visible)
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["thread_name"], "wa-alarm-review")

    def test_stopping_medication_and_opt_out_keep_model_reply(self):
        response = "Converse com seu médico antes de mudar a dose."
        for lead_text in ("posso parar o remédio por conta própria?", "quero sair da lista"):
            with self.subTest(lead_text=lead_text):
                visible, alert = self._calm(response, lead_text)
                self.assertEqual(visible, response)
                alert.assert_not_called()

    def test_referral_after_last_diagnostic_question_fires_phase3(self):
        history = "Você (bot): Isso vem te afetando no trabalho em outros momentos também?"
        referral = "é importante procurar avaliação médica o quanto antes."
        with mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
             mock.patch.object(wm, "_history_from_me_and_lead", return_value=(history, [])), \
             mock.patch.object(wm, "_contact_record_for_chat", return_value={}):
            visible = wm._enforce_therapify_clinical_calm(referral, "não estou comendo", CHAT, history)
        self.assertEqual(visible.split("\n\n"), list(wm._THERAPIFY_PHASE2_CLOSING_BUBBLES))

    def test_referral_after_phase3_returns_to_schedule_unless_booked(self):
        referral = "é importante procurar avaliação médica o quanto antes."
        record = {wm._PLAYBOOK_COMPLETION_FIELD: "2026-11-06T12:00:00Z"}
        for booked in (False, True):
            with self.subTest(booked=booked), \
                 mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
                 mock.patch.object(wm, "_contact_record_for_chat", return_value=record), \
                 mock.patch.object(wm, "_followup_close_for_active_booking", return_value=booked):
                visible = wm._enforce_therapify_clinical_calm(referral, "não estou comendo", CHAT, "")
            self.assertNotIn("médica", visible)
            self.assertEqual("horário" in visible, not booked)

    def test_explicit_self_harm_keeps_safety_reply(self):
        visible, _ = self._calm("Tudo bem", "quero me matar")
        self.assertIn("188", visible)
        self.assertIn("[[HANDOFF:", visible)

    def test_normal_reply_is_untouched(self):
        visible, alert = self._calm("Tudo bem", "Preciso de ajuda")
        self.assertEqual(visible, "Tudo bem")
        alert.assert_not_called()

    def _script(self, response, lead_text, history="AYA: Isso vem te afetando no trabalho em outros momentos também?", record=None):
        with mock.patch.object(wm, "_contact_record_for_chat", return_value=record or {}):
            return wm._enforce_therapify_script_lines(response, lead_text, CHAT, history)

    def test_improvised_reaction_after_last_question_fires_phase3(self):
        improvised = "Ok✅\n\nTudo bem\n\nÉ comum que situações assim afetem a alimentação.\n\nPodemos ajudar você."
        visible = self._script(improvised, "Um pouco eu acho")
        self.assertEqual(visible.split("\n\n"), list(wm._THERAPIFY_PHASE2_CLOSING_BUBBLES))

    def test_phase2_reaction_keeps_real_exits(self):
        cases = (
            ("Compreendo perfeitamente.\n\n[[HANDOFF: não deseja]]", "Não quero mais"),
            ("Vamos lhe passar maiores informações", "Qual o valor?"),
            ("Ok✅\n\nTudo bem\n\nRapidamente a gente muda isso.", "sim"),
        )
        for response, lead_text in cases:
            with self.subTest(lead_text=lead_text):
                self.assertEqual(self._script(response, lead_text), response)

    def test_reaction_rule_needs_last_question_pending_and_phase3_open(self):
        response = "Tudo bem"
        self.assertEqual(self._script(response, "sim", history="AYA: Qual horário ficaria mais confortável?"), response)
        record = {wm._PLAYBOOK_COMPLETION_FIELD: "x"}
        self.assertEqual(self._script(response, "sim", record=record), response)

    def test_model_imitating_commercial_transition_still_gets_fixed_reaction(self):
        # 11/11: o modelo copiou "maiores informações" sem pergunta comercial e a Fase 3 não disparou.
        improvised = (
            "Vamos lhe passar maiores informações.\n\nOk✅\n\nTudo bem\n\n"
            "Entendo que sua alimentação tem sido afetada por esse momento.\n\nTudo bem\n\nTudo bem\n\n"
            "Vamos buscar compreender o que você vem sentindo."
        )
        visible = self._script(improvised, "Fico sem fome e às vezes com muita fome\nAgora a 8\nSim")
        self.assertEqual(visible.split("\n\n"), list(wm._THERAPIFY_PHASE2_CLOSING_BUBBLES))

    def test_reaction_is_not_sent_again_once_phase3_started(self):
        # 11/11: cada nova mensagem com a Fase 3 pendente repetia o bloco de reação.
        record = {wm._PLAYBOOK_PENDING_FIELD: 1.0, wm._PLAYBOOK_PROGRESS_FIELD: {"media_sent": 6}}
        improvised = "Ok✅\n\nTudo bem\n\nÉ comum que situações assim afetem a alimentação."
        self.assertEqual(self._script(improvised, "Ok", record=record), improvised)
        with mock.patch.object(wm, "_contact_record_for_chat", return_value=record):
            resumed = wm._therapify_resume_flow(CHAT, "Ok", "AYA: Isso vem te afetando no trabalho em outros momentos também?")
        self.assertNotIn("Rapidamente a gente muda isso", resumed)
        self.assertNotIn("deixar de sentir fome", resumed)

    def test_wanting_to_leave_the_room_or_relationship_is_not_opt_out(self):
        for lead_text in ("Não quero sair do quarto", "Quero sair dessa relação", "queria sair disso"):
            with self.subTest(lead_text=lead_text):
                self.assertIsNone(wm._FOLLOWUP_OPT_OUT_RE.search(wm._normalize_text(lead_text)))
        for lead_text in ("quero sair da lista", "Quero sair", "não me chame mais", "pare de me mandar mensagem"):
            with self.subTest(lead_text=lead_text):
                self.assertIsNotNone(wm._FOLLOWUP_OPT_OUT_RE.search(wm._normalize_text(lead_text)))

    def test_medical_referral_is_replaced_when_lead_says_they_dont_want_to_leave_the_room(self):
        # 10/11: "Não quero sair do quarto" virou opt-out e deixou passar encaminhamento médico.
        response = (
            "Como seu coração está disparado o tempo todo, é importante procurar uma avaliação médica o quanto antes.\n\n"
            "Se tiver dor no peito, procure atendimento de urgência imediatamente."
        )
        visible, alert = self._calm(response, "Em tudo\nNão quero sair do quarto\nNão durmo bem\nAnsiedade e coração dispara")
        self.assertNotIn("médica", visible)
        alert.assert_called_once()

    def test_health_service_and_urgent_care_referrals_are_replaced(self):
        # 12/11 e 10/11: "avaliação de saúde" e "atendimento de urgência" escaparam da guarda.
        for response in (
            "Se isso persistir ou tiver dificuldade para se alimentar, procure uma avaliação de saúde.",
            "Se tiver dor no peito, procure atendimento de urgência imediatamente.",
            "Procure um serviço de saúde perto de você.",
        ):
            with self.subTest(response=response):
                visible, alert = self._calm(response, "Realmente não tenho muita fome")
                self.assertNotIn("procure", visible.casefold())
                alert.assert_called_once()
        visible, alert = self._calm("Você quer cuidar da sua saúde e seguir em frente.", "quero melhorar")
        self.assertEqual(visible, "Você quer cuidar da sua saúde e seguir em frente.")
        alert.assert_not_called()

    def test_paraphrased_last_question_still_gets_fixed_reaction(self):
        # 12/11: o modelo reescreveu a última pergunta e a Fase 3 não disparou.
        history = (
            "AYA: Além da dificuldade de concentração no trabalho que você mencionou, "
            "isso vem te afetando em outros momentos também?"
        )
        visible = self._script("Compreendo, obrigado por responder.", "Sim", history=history)
        self.assertEqual(visible.split("\n\n"), list(wm._THERAPIFY_PHASE2_CLOSING_BUBBLES))
        pattern = wm._playbook_completion_config()["requires_sent_regex"]
        speaker = wm._profile_text("speaker_name", "Atendente")
        with mock.patch.object(wm, "_fetch_chat_history", return_value=f"{speaker}: {history[5:]}"):
            self.assertTrue(wm._chat_bot_sent_matching(CHAT, pattern))

    def test_model_schedule_question_is_dropped_while_phase3_is_running(self):
        # 12/11: a pergunta do modelo saiu antes da agenda e a Fase 3 repetiu logo depois.
        record = {wm._PLAYBOOK_PENDING_FIELD: 1.0, wm._PLAYBOOK_PROGRESS_FIELD: {"media_sent": 6}}
        reply = (
            "Entendo, depois de tanta terapia é compreensível se sentir desacreditada.\n\n"
            "Qual horário ficaria mais confortável para ti?"
        )
        visible = self._script(reply, "Eu sei, já fiz muita terapia", history="AYA: Tudo bem?", record=record)
        self.assertEqual(visible, reply.split("\n\n")[0])
        only_question = self._script("Qual horário ficaria mais confortável para ti?", "ok", history="AYA: Tudo bem?", record=record)
        self.assertEqual(only_question, "Ok✅")
        done = {wm._PLAYBOOK_COMPLETION_FIELD: 1.0}
        self.assertEqual(self._script(reply, "ok", history="AYA: Tudo bem?", record=done), reply)

    def test_legal_referral_is_replaced_and_owner_reviews(self):
        # 09/11: dúvida sobre direitos virou indicação de Defensoria/advogada.
        for response in (
            "Você pode procurar a Defensoria Pública ou uma advogada de família.",
            "Isso é decidido na vara de família; a OAB indica profissionais.",
            "O Ministério Público pode orientar sobre a pensão.",
        ):
            with self.subTest(response=response):
                visible, alert = self._calm(response, "e a guarda dos meus filhos?")
                self.assertNotEqual(visible, response)
                alert.assert_called_once()

    def test_credential_question_gets_rodrigo_text_as_one_bubble(self):
        for lead_text in ("Você é psicólogo?", "vc eh psicologo", "É psicólogo?", "Qual sua formação?"):
            with self.subTest(lead_text=lead_text):
                visible = self._script("O Dr. Rodrigo é psicoterapeuta.\n\n[[HANDOFF: credencial]]", lead_text, history="")
                self.assertTrue(visible.startswith("Sou Psicoterapeuta especializado em Hipnose Clínica"))
                self.assertNotIn("HANDOFF", visible)
                self.assertEqual(len(wm._split_human_bubbles(visible)), 1)

    def test_someone_else_being_a_psychologist_is_not_a_credential_question(self):
        self.assertEqual(self._script("Tudo bem", "minha amiga é psicóloga", history=""), "Tudo bem")

    def test_handoff_stays_in_first_person(self):
        for response in (
            "Tudo bem. Vou encaminhar seu pedido para o Dr. Rodrigo.\n\n[[HANDOFF: humano || RESUMO: x]]",
            "O Dr. Rodrigo pode explicar isso em detalhes.\n\n[[HANDOFF: hipnose || RESUMO: x]]",
        ):
            with self.subTest(response=response):
                visible = self._script(response, "vou dormir na hipnose?", history="")
                self.assertTrue(visible.startswith("Vou te explicar em detalhes"))
                self.assertIn("[[HANDOFF:", visible)
                self.assertNotIn("Rodrigo", visible.split("[[")[0])

    def test_robot_question_is_left_alone(self):
        response = "Vou direcionar sua pergunta.\n\n[[HANDOFF: robô]]"
        self.assertEqual(self._script(response, "isso é robô?", history=""), response)

    def test_price_question_after_last_diagnostic_still_fires_phase3(self):
        history = "AYA: Isso vem te afetando no trabalho em outros momentos também?"
        with mock.patch.object(wm, "_therapify_reply_to_d1", return_value=""):
            visible = wm._enforce_therapify_playbook_order("R$ 247", "Qual o valor?", CHAT, history, {})
        self.assertTrue(visible.startswith("Vamos lhe passar maiores informações"))
        self.assertTrue(visible.endswith("Rapidamente a gente muda isso"))

    def _closing(self, lead_text, history="AYA: Qual horário ficaria mais confortável para ti?", booked=False):
        record = {wm._PLAYBOOK_COMPLETION_FIELD: "x"}
        with mock.patch.object(wm, "_followup_close_for_active_booking", return_value=booked):
            return self._script("Vamos lhe passar maiores informações", lead_text, history=history, record=record)

    def test_closing_questions_use_rodrigo_lines_and_return_to_schedule(self):
        for lead_text, first in (
            ("Esse valor é só de uma sessão?", "Isso, perfeito ✅"),
            ("Como funciona?", "Acessamos a raiz do quadro"),
            ("como funciona a sessão?", "Acessamos a raiz do quadro"),
        ):
            with self.subTest(lead_text=lead_text):
                visible = self._closing(lead_text)
                self.assertTrue(visible.startswith(first))
                self.assertIn("Qual horário", visible)

    def test_closing_answers_respect_downsell_booking_and_other_topics(self):
        original = "Vamos lhe passar maiores informações"
        self.assertEqual(self._closing("Como funciona?", history="AYA: método autoaplicável por R$ 47,00"), original)
        self.assertEqual(self._closing("Como funciona?", booked=True), original)
        self.assertEqual(self._closing("como funciona esse método auto aplicável?"), original)
        self.assertEqual(self._closing("como funciona o pagamento"), original)

    def test_spoken_name_skips_titles_and_places(self):
        cases = {"Dra. Jaina Fonseca": "Jaina", "Sr Indy": "Indy", "Gaby": "Gaby", "Maria Clara": "Maria"}
        for name, spoken in cases.items():
            with self.subTest(name=name):
                self.assertEqual(wm._resolve_lead_spoken_name({"name": name}), spoken)
        for name in ("Dra.", "Sr", "Dra Em Ciencias Da Saúde", "Curitiba Golden"):
            with self.subTest(name=name):
                self.assertIsNone(wm._resolve_lead_spoken_name({"name": name}))

    def test_phase2_closing_is_restored_so_phase3_can_fire(self):
        improvised = (
            "Ok✅\n\nTudo bem\n\nÉ muito comum a pessoa deixar de sentir fome ou cair para uma compulsão."
            "\n\nTudo bem\n\nTudo bem\n\nVamos trabalhar isso com cuidado."
        )
        with mock.patch.object(wm, "_therapify_reply_to_d1", return_value=""):
            visible = wm._enforce_therapify_playbook_order(improvised, "sim", CHAT, "")
        self.assertEqual(visible.split("\n\n"), list(wm._THERAPIFY_PHASE2_CLOSING_BUBBLES))
        self.assertRegex(visible.split("\n\n")[-1].lower(), "rapidamente.*(a gente|voc[eê]s?).*muda")

    def test_generic_profile_keeps_model_response_unchanged(self):
        response = (
            "Sinto muito. Ligue para o CVV 188 ou procure uma emergência.\n\n"
            "[[HANDOFF: risco]]"
        )
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_BUSINESS_PROFILE": "generic",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            },
        ):
            _reset_profile_cache()
            visible = wm._enforce_therapify_clinical_calm(
                response,
                "Estou desesperada e pensando em me matar.",
                CHAT,
                "",
            )
        self.assertEqual(visible, response)

    def test_crisis_alert_and_reply_before_any_commercial_action(self):
        inbound = {"message_id": "risk-1", "at": 1700000000.0, "text": "quero me matar"}
        wm._therapify_crisis_turns.clear()
        self.addCleanup(wm._therapify_crisis_turns.clear)
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True) as alert, \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_followup_mark_commercial_terminal") as close, \
             mock.patch.object(wm, "_reserve_contact_send", return_value=(True, "risk-turn")), \
             mock.patch.object(wm, "_schedule_contact_reply", return_value=True) as schedule:
            self.assertTrue(wm._handle_therapify_crisis(CHAT, CHAT, "risk-turn", inbound))
            self.assertTrue(wm._handle_therapify_crisis(CHAT, CHAT, "risk-turn", inbound))
        alert.assert_called_once()
        close.assert_called_once()
        schedule.assert_called_once()
        self.assertTrue(schedule.call_args.kwargs["urgent_safety"])
        self.assertIn("188", schedule.call_args.args[1])

    def test_crisis_reply_bypasses_sales_opening_and_business_delay_but_not_delivery_guard(self):
        inbound = {"message_id": "risk-2", "at": 1700000001.0, "text": "quero me matar"}
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_partial_reply_for_turn", return_value={}), \
             mock.patch.object(wm, "_ritmo_wait_before_send") as delay, \
             mock.patch.object(wm, "_ritmo_send_window_ok") as hours, \
             mock.patch.object(wm, "_enforce_therapify_first_outbound") as opening, \
             mock.patch.object(wm, "_deliver_contact_reply", return_value="ack") as deliver, \
             mock.patch.object(wm, "_write_therapify_crisis_state") as pause, \
             mock.patch.object(wm, "_followup_cancel") as cancel, \
             mock.patch.object(wm, "_complete_contact_send"):
            self.assertTrue(wm._schedule_contact_reply(
                CHAT, wm._THERAPIFY_CRISIS_REPLY, "risk-turn", wm._inbound_record_token(inbound),
                inbound_snapshot=inbound, urgent_safety=True,
            ))
        delay.assert_not_called()
        hours.assert_not_called()
        opening.assert_not_called()
        self.assertTrue(deliver.call_args.kwargs["require_ai_access"])
        self.assertFalse(pause.call_args.args[1]["ai_enabled"])
        cancel.assert_called_once_with(CHAT)

    def test_calendar_rejects_crisis_turn_even_if_it_contains_a_time(self):
        inbound = {"message_id": "risk-3", "at": 1700000002.0, "text": "19h, mas quero me matar"}
        token = wm._inbound_record_token(inbound)
        with mock.patch.object(wm, "_resolve_mapped_chat_id", return_value=CHAT), \
             mock.patch.object(wm, "_session_is_owner", return_value=False):
            with self.assertRaises(wm.CalendarBookingError):
                wm._calendar_tool_context(CHAT, expected_inbound_token=token, inbound_snapshot=inbound)

    def test_transcribed_audio_is_routed_to_crisis_before_prompt_or_tools(self):
        transcript = "estou pensando em me matar"
        inbound = {"message_id": "audio-risk", "at": 1700000003.0, "text": transcript,
                   "is_voice": True, "_chat_id": CHAT}
        with mock.patch.object(wm, "_sender_to_chat", {CHAT: CHAT}), \
             mock.patch.object(wm, "_turn_inbound", {"audio-turn": inbound}), \
             mock.patch.object(wm, "_core_bound_turn", return_value=("audio-turn", inbound)), \
             mock.patch.object(wm, "_same_trusted_whatsapp_identity", return_value=False), \
             mock.patch.object(wm, "_session_is_owner", return_value=False), \
             mock.patch.object(wm, "_handle_therapify_crisis") as handle, \
             mock.patch.object(wm, "_load_support_files") as load:
            result = wm.pre_llm_call(platform="whatsapp", sender_id=CHAT, session_id=CHAT,
                                     user_message=transcript)
        self.assertIsNone(result)
        handle.assert_called_once_with(CHAT, CHAT, "audio-turn", inbound)
        load.assert_not_called()

    def test_crisis_alert_survives_blocked_delivery_and_closes_automation(self):
        inbound = {"message_id": "risk-4", "at": 1700000004.0, "text": "quero me matar"}
        with mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True), \
             mock.patch.object(wm, "_partial_reply_for_turn", return_value={}), \
             mock.patch.object(wm, "_deliver_contact_reply", side_effect=wm.DeliveryBlocked("pausa")), \
             mock.patch.object(wm, "_write_therapify_crisis_state") as pause, \
             mock.patch.object(wm, "_followup_cancel") as cancel, \
             mock.patch.object(wm, "_followup_discard_snapshot"), \
             mock.patch.object(wm, "_clear_partial_reply"), \
             mock.patch.object(wm, "_complete_contact_send"):
            self.assertFalse(wm._schedule_contact_reply(
                CHAT, wm._THERAPIFY_CRISIS_REPLY, "risk-turn", wm._inbound_record_token(inbound),
                inbound_snapshot=inbound, urgent_safety=True,
            ))
        self.assertFalse(pause.call_args.args[1]["ai_enabled"])
        cancel.assert_called_once_with(CHAT)

    def test_reservation_failure_keeps_alert_and_pauses_automation(self):
        inbound = {"message_id": "risk-5", "at": 1700000006.0, "text": "quero me matar"}
        wm._therapify_crisis_turns.clear()
        self.addCleanup(wm._therapify_crisis_turns.clear)
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True) as alert, \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_followup_mark_commercial_terminal"), \
             mock.patch.object(wm, "_reserve_contact_send", side_effect=RuntimeError("indisponível")), \
             mock.patch.object(wm, "_pause_therapify_crisis") as pause:
            self.assertFalse(wm._handle_therapify_crisis(CHAT, CHAT, "risk-turn-5", inbound))
        alert.assert_called_once()
        pause.assert_called_once_with(CHAT)

    def test_text_crisis_intercepts_before_deterministic_opening_and_calendar(self):
        text = "quero me matar"
        source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
        event = SimpleNamespace(source=source, text=text, raw_message={"messageId": "risk-in"}, raw={}, is_historical=False)
        info = {"has_media": False, "media_type": None, "media_urls": [], "message_id": "risk-in"}
        inbound = {"message_id": "risk-in", "at": 1700000005.0, "text": text}
        gateway = SimpleNamespace(_session_key_for_source=lambda _: CHAT, _session_model_overrides={})
        with mock.patch.object(wm, "_get_media_info", return_value=info), \
             mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
             mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
             mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
             mock.patch.object(wm, "_prompt_injection_kind_for_turn", return_value=None), \
             mock.patch.object(wm, "_fetch_chat_history", return_value=""), \
             mock.patch.object(wm, "_complete_pending_panel_unblock"), \
             mock.patch.object(wm, "_ensure_contact_ai_access", return_value=(True, "")), \
             mock.patch.object(wm, "_followup_note_activity"), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False), \
             mock.patch.object(wm, "_get_active_owner_status", return_value=None), \
             mock.patch.object(wm, "_coalesce_contact_inbound", return_value=text), \
             mock.patch.object(wm, "_track_inbound"), \
             mock.patch.object(wm, "_current_inbound_record", return_value=inbound), \
             mock.patch.object(wm, "_register_contact_turn", return_value="risk-turn"), \
             mock.patch.object(wm, "_activate_therapify_crisis"), \
             mock.patch.object(wm, "_handle_therapify_crisis") as handle, \
             mock.patch.object(wm, "_try_deterministic_contact_fast_path") as commercial:
            result = wm.pre_gateway_dispatch(event=event, gateway=gateway)
        self.assertEqual(result, {"action": "skip", "reason": "therapify-crisis"})
        handle.assert_called_once()
        commercial.assert_not_called()

    def test_crisis_blocks_ordinary_delivery_and_phase_three_but_allows_safe_response(self):
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with mock.patch.object(wm, "_followup_cancel") as cancel, \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
             mock.patch.object(wm, "_canonical_delivery_jid", side_effect=lambda value: value), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False), \
             mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True):
            wm._activate_therapify_crisis(CHAT)
            with self.assertRaises(wm.DeliveryBlocked):
                wm._assert_delivery_allowed(CHAT, require_ai_access=True)
            wm._assert_delivery_allowed(CHAT, require_ai_access=True, urgent_safety=True)
            with self.assertRaises(wm.DeliveryBlocked):
                wm._run_playbook_effect(CHAT, None, lambda: self.fail("fase 3 enviada"))
        cancel.assert_called_once_with(CHAT)

    def test_crisis_bypasses_only_automatic_opening_pause_and_respects_human_takeover(self):
        automatic = {"ai_enabled": False, "in_flow": False, "ai_disabled_reason": "opening_uncertain", "flow_origin": "opening_uncertain"}
        manual = {"ai_enabled": False, "in_flow": False, "ai_disabled_reason": "manual_takeover", "flow_origin": "manual_takeover"}
        self.addCleanup(wm._opening_capture_failed.clear)
        wm._opening_capture_failed[wm._contact_effect_lock_key(CHAT)] = 100
        with mock.patch.object(wm, "_is_contact_blocked", return_value=False), \
             mock.patch.object(wm, "_chat_disabling_label", return_value=None), \
             mock.patch.object(wm, "_load_personal_contacts", return_value={CHAT: automatic}), \
             mock.patch.object(wm, "_matching_contact_ai_corrupt_keys", return_value=[]), \
             mock.patch.object(wm, "_matching_contact_ai_records", return_value=[(CHAT, automatic, True)]) as records, \
             mock.patch.object(wm, "_canonical_delivery_jid", side_effect=lambda value: value), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False) as paused, \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False) as silenced, \
             mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=False), \
             mock.patch.object(wm, "_opening_inbound_outbox", return_value=SimpleNamespace(resume_requested_at=lambda _chat: 0)):
            with self.assertRaises(wm.DeliveryBlocked):
                wm._assert_delivery_allowed(CHAT, require_ai_access=True)
            wm._assert_delivery_allowed(CHAT, require_ai_access=True, urgent_safety=True)
            silenced.return_value = True
            with self.assertRaises(wm.DeliveryBlocked):
                wm._assert_delivery_allowed(CHAT, require_ai_access=True, urgent_safety=True)
            silenced.return_value = False
            paused.return_value = True
            with self.assertRaises(wm.DeliveryBlocked):
                wm._assert_delivery_allowed(CHAT, require_ai_access=True, urgent_safety=True)
            paused.return_value = False
            records.return_value = [(CHAT, automatic, True), ("other@lid", manual, False)]
            with self.assertRaises(wm.DeliveryBlocked):
                wm._assert_delivery_allowed(CHAT, require_ai_access=True, urgent_safety=True)

    def test_capture_failure_does_not_overwrite_manual_takeover_on_an_alias(self):
        manual = {"ai_enabled": False, "in_flow": False, "ai_disabled_reason": "manual_takeover"}
        enabled = {"ai_enabled": True, "in_flow": True}
        self.addCleanup(wm._opening_capture_failed.clear)
        with mock.patch.object(wm, "_load_personal_contacts", return_value={}), \
             mock.patch.object(wm, "_matching_contact_ai_records", return_value=[(CHAT, enabled, True), ("other@lid", manual, False)]), \
             mock.patch.object(wm, "_merge_contact_record_atomic") as update, \
             mock.patch.object(wm, "_followup_cancel") as cancel:
            wm._pause_for_opening_uncertainty(CHAT)
        update.assert_not_called()
        cancel.assert_called_once_with(CHAT)

    def test_crisis_after_automatic_opening_pause_reaches_urgent_path(self):
        text = "quero me matar"
        source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
        event = SimpleNamespace(source=source, text=text, raw_message={"messageId": "risk-after-capture"}, raw={}, is_historical=False)
        info = {"has_media": False, "media_type": None, "media_urls": [], "message_id": "risk-after-capture"}
        inbound = {"message_id": "risk-after-capture", "at": 1700000005.0, "text": text}
        gateway = SimpleNamespace(_session_key_for_source=lambda _: CHAT, _session_model_overrides={})
        with mock.patch.object(wm, "_get_media_info", return_value=info), \
             mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid), \
             mock.patch.object(wm, "_contact_security_reset_snapshot", return_value={}), \
             mock.patch.object(wm, "_prompt_injection_kind", return_value=None), \
             mock.patch.object(wm, "_complete_pending_panel_unblock"), \
             mock.patch.object(wm, "_ensure_contact_ai_access", return_value=(False, "legacy-contact-disabled")), \
             mock.patch.object(wm, "_urgent_allowed_after_opening_failure", return_value=True), \
             mock.patch.object(wm, "_followup_note_activity"), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False), \
             mock.patch.object(wm, "_get_active_owner_status", return_value=None), \
             mock.patch.object(wm, "_coalesce_contact_inbound", return_value=text), \
             mock.patch.object(wm, "_track_inbound"), \
             mock.patch.object(wm, "_current_inbound_record", return_value=inbound), \
             mock.patch.object(wm, "_register_contact_turn", return_value="risk-turn"), \
             mock.patch.object(wm, "_activate_therapify_crisis"), \
             mock.patch.object(wm, "_handle_therapify_crisis") as handle:
            result = wm.pre_gateway_dispatch(event=event, gateway=gateway)
        self.assertEqual(result, {"action": "skip", "reason": "therapify-crisis"})
        handle.assert_called_once()

    def test_crisis_alert_is_durable_and_reloaded_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "handoff.json"
            wm._handoff_outbox.clear()
            wm._handoff_outbox_loaded_from = ""
            wm._therapify_crisis_chats.clear()
            self.addCleanup(wm._handoff_outbox.clear)
            self.addCleanup(wm._therapify_crisis_chats.clear)
            with mock.patch.object(wm, "_HANDOFF_OUTBOX_PATH", path), \
                 mock.patch.object(wm, "_followup_cancel"), \
                 mock.patch.object(wm.threading, "Thread") as worker:
                wm._activate_therapify_crisis(CHAT, "risk-msg")
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(len(persisted), 1)
                entry = next(iter(persisted.values()))
                self.assertEqual(entry["chat_id"], CHAT)
                self.assertIn("risco", entry["reason"].lower())
                worker.assert_called_once()
                wm._handoff_outbox.clear()
                wm._handoff_outbox_loaded_from = ""
                self.assertTrue(wm._load_handoff_outbox())
                self.assertEqual(next(iter(wm._handoff_outbox.values()))["chat_id"], CHAT)
            wm._handoff_outbox_loaded_from = ""

    def test_crisis_real_delivery_after_failed_capture_and_real_takeover(self):
        text = "quero me matar"
        source = SimpleNamespace(platform=SimpleNamespace(value="whatsapp"), user_id=CHAT, chat_id=CHAT)
        event = SimpleNamespace(source=source, text=text, raw_message={"messageId": "risk-full"}, raw={}, is_historical=False)
        gateway = SimpleNamespace(_session_key_for_source=lambda _: CHAT, _session_model_overrides={})
        inbound = {"message_id": "risk-full", "at": 1700000005.0, "text": text}
        automatic = {"ai_enabled": False, "ai_disabled_reason": "opening_uncertain"}
        manual = {"ai_enabled": False, "ai_disabled_reason": "manual_takeover"}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self): return b'{"messageId":"emergency-ack"}'
        self.addCleanup(wm._opening_capture_failed.clear)
        self.addCleanup(wm._therapify_crisis_chats.clear)
        self.addCleanup(wm._therapify_crisis_turns.clear)
        wm._opening_capture_failed[wm._contact_effect_lock_key(CHAT)] = 100
        with ExitStack() as stack:
            patches = {
                "_get_media_info": {"has_media": False, "media_type": None, "media_urls": [], "message_id": "risk-full"},
                "_contact_security_reset_snapshot": {}, "_prompt_injection_kind": None,
                "_complete_pending_panel_unblock": None, "_ensure_contact_ai_access": (False, "legacy-contact-disabled"),
                "_followup_note_activity": None, "_check_bot_paused": False, "_check_chat_silenced": False,
                "_get_active_owner_status": None, "_coalesce_contact_inbound": text, "_track_inbound": None,
                "_current_inbound_record": inbound, "_register_contact_turn": "risk-full-turn",
                "_is_contact_blocked": False, "_chat_disabling_label": None,
                "_load_personal_contacts": {CHAT: automatic}, "_matching_contact_ai_corrupt_keys": [],
                "_contact_has_explicit_ai_access": False, "_followup_cancel": None,
                "_followup_mark_commercial_terminal": None, "_reserve_contact_send": (True, "risk-full-turn"),
                "_partial_reply_for_turn": {}, "_followup_remember_turn": None,
                "_newer_inbound_arrived": False, "_log_bot_delivery": None,
                "_calendar_mark_offer_delivered": None, "_followup_register_outbound": None,
                "_complete_contact_send": None, "_clear_inbound": None,
                "_mark_bot_spoke": None, "_clear_unsent_replies": None,
                "_opening_inbound_outbox": SimpleNamespace(resume_requested_at=lambda _chat: 0),
            }
            for name, result in patches.items():
                stack.enter_context(mock.patch.object(wm, name, return_value=result))
            records = stack.enter_context(mock.patch.object(wm, "_matching_contact_ai_records", return_value=[(CHAT, automatic, True)]))
            stack.enter_context(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
            stack.enter_context(mock.patch.object(wm, "_canonical_delivery_jid", side_effect=lambda jid: jid))
            stack.enter_context(mock.patch.object(wm, "_HUMAN_DELIVER_SYNC", True))
            alert = stack.enter_context(mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True))
            send = stack.enter_context(mock.patch.object(wm.urllib.request, "urlopen", return_value=Response()))
            result = wm.pre_gateway_dispatch(event=event, gateway=gateway)
            self.assertEqual(result, {"action": "skip", "reason": "therapify-crisis"})
            self.assertGreater(send.call_count, 0)
            self.assertGreater(alert.call_count, 0)
            send.reset_mock()
            records.return_value = [(CHAT, manual, True)]
            wm._therapify_crisis_turns.clear()
            result = wm.pre_gateway_dispatch(event=event, gateway=gateway)
            self.assertEqual(result.get("action"), "skip")
            send.assert_not_called()

    def test_prior_calendar_turn_cannot_book_after_crisis_activation(self):
        slot = {"start": "2999-01-07T17:00:00-03:00", "end": "2999-01-07T18:00:00-03:00"}
        token = ("old-inbound", 102.0)
        inbound = {"message_id": token[0], "at": token[1], "text": "sim, 17h"}
        offer = {"kind": "offered", "delivered_message_id": "out", "expires_at": 99999999999,
                 "slots": [slot], "delivered_slots": {slot["start"]: {"message_id": "out", "at": 100}}}
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with mock.patch.object(wm, "_calendar_turn_state", {CHAT: offer}), \
             mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, inbound, token)), \
             mock.patch.object(wm, "_contact_record_for_chat", return_value={}), \
             mock.patch.object(wm, "get_booking", return_value=None), \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
             mock.patch.object(wm, "create_booking") as create:
            wm._activate_therapify_crisis(CHAT)
            response = json.loads(wm._handle_calendar_book(slot, session_id=CHAT))
        self.assertEqual(response["status"], "error")
        create.assert_not_called()

    def test_opening_stops_between_bubbles_after_crisis(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return None
            def read(self): return b'{"messageId":"first-bubble"}'
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with mock.patch.object(wm.urllib.request, "urlopen", return_value=Response()) as send, \
             mock.patch.object(wm, "_canonical_delivery_jid", side_effect=lambda value: value), \
             mock.patch.object(wm, "_check_bot_paused", return_value=False), \
             mock.patch.object(wm, "_check_chat_silenced", return_value=False), \
             mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), \
             mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True), \
             mock.patch.object(wm, "_log_bot_delivery"):
            with self.assertRaises(wm.PartialMessageDelivery):
                wm._human_send(CHAT, "Primeira bolha\n\nSegunda bolha", automation=True,
                               require_ai_access=True,
                               on_message_confirmed=lambda *_: wm._activate_therapify_crisis(CHAT, "risk"))
        self.assertEqual(send.call_count, 1)

    def test_crisis_activation_waits_for_inflight_effect_lock(self):
        self.addCleanup(wm._therapify_crisis_chats.clear)
        attempted, finished = threading.Event(), threading.Event()
        def activate():
            attempted.set()
            wm._activate_therapify_crisis(CHAT)
            finished.set()
        with mock.patch.object(wm, "_followup_cancel"), \
             mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True):
            with wm._contact_effect_lock(CHAT):
                thread = threading.Thread(target=activate)
                thread.start()
                self.assertTrue(attempted.wait(1))
                self.assertFalse(finished.wait(0.05))
            self.assertTrue(finished.wait(1))
            thread.join()
        self.assertTrue(wm._therapify_crisis_is_active(CHAT))

    def test_crisis_flag_is_visible_after_process_local_state_is_lost(self):
        self.addCleanup(wm._therapify_crisis_chats.clear)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "personal_contacts.json"
            lid = "123456789@lid"
            path.write_text(json.dumps({
                CHAT: {"ai_enabled": True, "in_flow": True, "lid": lid},
                lid: {"ai_enabled": True, "in_flow": True, "lid": lid},
            }))
            with mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", path), \
                 mock.patch.object(wm, "_write_therapify_crisis_state", _REAL_WRITE_THERAPIFY_CRISIS_STATE), \
                 mock.patch.object(wm, "_followup_cancel"), \
                 mock.patch.object(wm, "_queue_owner_notification_safely", return_value=True):
                wm._activate_therapify_crisis(CHAT, "risk-cross-process")
                records = json.loads(path.read_text())
                self.assertTrue(records[CHAT]["safety_crisis_active"])
                self.assertTrue(records[lid]["safety_crisis_active"])
                wm._therapify_crisis_chats.clear()
                self.assertTrue(wm._therapify_crisis_is_active(CHAT))
                probe = subprocess.run(
                    [sys.executable, "-c", (
                        "import sys; from pathlib import Path; import whatsapp_manager as w; "
                        "w._PERSONAL_CONTACTS_PATH=Path(sys.argv[1]); "
                        "raise SystemExit(0 if w._therapify_crisis_is_active(sys.argv[2]) else 1)"
                    ), str(path), CHAT], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(probe.returncode, 0, probe.stderr)
                wm._pause_therapify_crisis(CHAT)
                records = json.loads(path.read_text())
                self.assertFalse(records[CHAT]["ai_enabled"])
                self.assertFalse(records[lid]["ai_enabled"])
                self.assertFalse(records[CHAT]["safety_crisis_active"])
                self.assertFalse(records[lid]["safety_crisis_active"])


class ManualTakeoverPersistenceTests(unittest.TestCase):
    def test_manual_takeover_disables_ai_and_leaves_a_reason_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            contacts_path = Path(tmp) / "personal_contacts.json"
            with mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts_path):
                wm._persist_manual_takeover(CHAT)

            contacts = json.loads(contacts_path.read_text(encoding="utf-8"))
            record = contacts[CHAT]
            self.assertFalse(record["ai_enabled"])
            self.assertFalse(record["in_flow"])
            self.assertEqual(record["flow_origin"], "manual_takeover")
            self.assertEqual(record["ai_disabled_reason"], "manual_takeover")


if __name__ == "__main__":
    unittest.main()
