"""Regressões do funil Therapify: ordem comercial e janela de envio automático."""
from __future__ import annotations

import datetime as dt
import contextlib
import importlib.util
import os
import sqlite3
import sys
import tempfile
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
CHAT = "558197472911@s.whatsapp.net"
BRT = ZoneInfo("America/Sao_Paulo")

FASE1_OPENING = "\n\n".join(
    [
        "Olá! Atendimento 100% online, do conforto da sua casa.",
        "O Dr. Rodrigo Melo é especialista em dependência emocional, com 8 anos de experiência.",
        "A sessão inicial inclui liberação emocional, protocolo para descobrir a raiz do sofrimento "
        "e um plano de autocuidado – tudo por R$ 247,00.",
        "Após a primeira sessão, você já percebe os primeiros resultados.",
        "O tempo estimado até o agendamento da sua consulta é de 4 a 6 minutos.",
        "Para entender melhor o seu caso: tem quanto tempo que terminaram? Como você vem lidando com tudo isso?",
    ]
)
EARLY_HISTORY = f"Dr. Rodrigo Melo: {FASE1_OPENING}"
MODEL_COMMERCIAL_REPLY = (
    "A sessão custa R$ 247,00, dura 1 hora, é pelo Google Meet e pode ser paga no Pix."
)

MESSAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    sender_id TEXT,
    sender_name TEXT,
    message_id TEXT NOT NULL,
    message_type TEXT,
    body TEXT,
    timestamp REAL,
    from_me INTEGER NOT NULL DEFAULT 0,
    is_historical INTEGER NOT NULL DEFAULT 0,
    has_media INTEGER NOT NULL DEFAULT 0,
    media_type TEXT,
    sync_type TEXT,
    context_wamid TEXT,
    inserted_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


def _brt(year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=BRT).astimezone(dt.UTC)


class TherapifyOrderTest(unittest.TestCase):
    def setUp(self):
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "WHATSAPP_BUSINESS_PROFILE": "therapify",
                    "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
                    "WHATSAPP_CONFIG_SUBDIR": "generic",
                },
            )
        )

    def _gate(self, response: str, message: str, *, history: str = EARLY_HISTORY, contact: dict | None = None) -> str:
        gate = getattr(wm, "_enforce_therapify_playbook_order", None)
        self.assertIsNotNone(
            gate,
            "RED esperado: falta o seam _enforce_therapify_playbook_order",
        )
        return gate(
            response,
            user_message=message,
            chat_id=CHAT,
            history=history,
            contact_info=contact or {},
        )

    def _assert_commercial_details_suppressed(self, visible: str) -> None:
        folded = " ".join(visible.casefold().split())
        self.assertNotIn("247", folded)
        self.assertNotIn("1 hora", folded)
        self.assertNotIn("google meet", folded)
        self.assertNotIn("pix", folded)

    def test_commercial_questions_wait_for_partial_phase_three_to_finish(self):
        history = EARLY_HISTORY + "\nAYA: Isso vem te afetando no trabalho em outros momento também?"
        contact = {wm._PLAYBOOK_PENDING_FIELD: 1.0, wm._PLAYBOOK_PROGRESS_FIELD: {"media_sent": 3}}
        for message in ("Como?", "É de graça?", "E quanto tempo de consulta?", "É uma sessão ou tem retorno?"):
            with self.subTest(message=message):
                visible = self._gate(MODEL_COMMERCIAL_REPLY, message, history=history, contact=contact)
                self._assert_commercial_details_suppressed(visible)
                self.assertIn("Vamos lhe passar maiores informações", visible)
                completed = self._gate(
                    MODEL_COMMERCIAL_REPLY, message, history=history,
                    contact={wm._PLAYBOOK_COMPLETION_FIELD: 1.0},
                )
                if message == "É de graça?":
                    self.assertIn("não", completed.casefold())
                    self.assertIn("R$ 247,00", completed)
                else:
                    self.assertEqual(completed, MODEL_COMMERCIAL_REPLY)

    def test_external_care_does_not_end_commercial_attendance(self):
        response = (
            "Entendi. Sinto que você esteja se sentindo esgotada. "
            "Como já está em acompanhamento presencial, leve isso para a sua terapeuta "
            "na próxima sessão ou entre em contato com ela antes, se estiver piorando."
        )
        history = EARLY_HISTORY + "\nLead: Estou fazendo com a dr presencial\nAYA: Isso vem te afetando no trabalho em outros momento também?"
        visible = self._gate(response, "Muito", history=history)
        self.assertNotIn("leve isso", visible)
        self.assertEqual(visible, "Ok✅\n\nTudo bem\n\nVou te explicar como funciona o atendimento.")
        self.assertNotIn("gostaria", visible)

    def test_external_care_continues_pending_diagnostic_question(self):
        response = "Como já faz terapia, converse com sua terapeuta."
        for previous, expected in zip(wm._THERAPIFY_DIAGNOSTIC_QUESTIONS, wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[1:]):
            with self.subTest(previous=previous):
                visible = self._gate(response, "Sim", history=f"AYA: {previous}")
                self.assertTrue(visible.endswith(expected))
                self.assertNotIn("gostaria", visible)

    def test_relationship_answer_advances_without_repeating_the_question(self):
        history = (
            EARLY_HISTORY
            + "\nLead: Não terminei, continuo na relação."
        )
        visible = self._gate(
            "Tem quanto tempo que terminaram?",
            "Não terminei, continuo na relação.",
            history=history,
        )

        self.assertNotIn("Tem quanto tempo que terminaram", visible)
        self.assertIn(wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[1], visible)

    def test_later_turn_uses_prior_relationship_answer_to_advance_question(self):
        history = (
            EARLY_HISTORY
            + "\nLead: Não terminamos, continuo na relação."
        )
        visible = self._gate(
            "Tem quanto tempo que terminaram?",
            "Estou ansiosa.",
            history=history,
        )

        self.assertNotIn("Tem quanto tempo que terminaram", visible)
        self.assertIn(wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[1], visible)

    def test_relationship_answer_stays_advanced_after_later_question_was_sent(self):
        anxiety_question = wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[1]
        history = (
            EARLY_HISTORY
            + "\nLead: Não terminamos, continuo na relação."
            + f"\nDr. Rodrigo Melo: {anxiety_question}"
        )
        visible = self._gate(
            "Atualmente o relacionamento se encerrou ou seguem em uma relação?",
            "Tenho sentido ansiedade e desânimo.",
            history=history,
        )

        self.assertNotIn("relacionamento se encerrou", visible)
        self.assertIn(wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[2], visible)

    def test_completed_diagnostic_advances_to_phase_three_transition(self):
        history = (
            EARLY_HISTORY
            + "\nLead: Não terminamos, continuo na relação."
            + "\n".join(
                f"\nDr. Rodrigo Melo: {question}"
                for question in wm._THERAPIFY_DIAGNOSTIC_QUESTIONS[1:]
            )
        )
        visible = self._gate(
            "Atualmente o relacionamento se encerrou ou seguem em uma relação?",
            "Isso está afetando muito.",
            history=history,
        )

        self.assertNotIn("relacionamento se encerrou", visible)
        self.assertTrue(visible.endswith(wm._THERAPIFY_DIAGNOSTIC_TRANSITION))

    def test_replaying_full_opening_is_not_rewritten_by_relationship_progress(self):
        visible = self._gate(
            FASE1_OPENING,
            "Não terminamos, continuo na relação.",
            history=EARLY_HISTORY,
        )

        self.assertEqual(visible, FASE1_OPENING)

    def test_external_care_exit_is_blocked_even_after_phase_three(self):
        response = "Como você já faz terapia, converse com sua psicóloga na próxima sessão."
        visible = self._gate(response, "Muito", contact={wm._PLAYBOOK_COMPLETION_FIELD: True})
        self.assertEqual(visible, wm._playbook_completion_config()["schedule_question"])

    def test_external_care_gate_preserves_refusal_and_clinical_requests(self):
        response = "Como já está em acompanhamento presencial, leve isso para a sua terapeuta."
        for message in (
            "Não tenho interesse, obrigada",
            "Não quero continuar",
            "Prefiro ficar só com minha terapeuta",
            "Não me mande mais mensagens",
            "Devo falar com minha terapeuta sobre isso?",
            "Posso parar meu tratamento?",
            "Estou pensando em me matar agora",
            "Quero falar com um humano",
        ):
            with self.subTest(message=message):
                self.assertEqual(self._gate(response, message), response)

    def test_external_care_gate_keeps_safety_guidance(self):
        response = "Como já faz terapia, converse com sua terapeuta. Se há risco imediato, procure emergência."
        self.assertEqual(self._gate(response, "Muito"), response)

    def test_external_care_gate_keeps_other_profiles(self):
        response = "Como já faz terapia, converse com sua terapeuta."
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            self.assertEqual(self._gate(response, "Muito"), response)

    def test_external_care_policy_is_injected_in_therapify_prompt(self):
        policy = wm._business_profile_override()
        self.assertIn("ACOMPANHAMENTO COM OUTRO PROFISSIONAL", policy)
        self.assertIn("Não pergunte novamente se quer conhecer", policy)
        self.assertNotIn("Se houver dúvida sobre interesse", policy)

    def test_external_care_exit_is_replaced_before_scheduling_whatsapp_reply(self):
        response = "Como já está em acompanhamento presencial, leve isso para a sua terapeuta."
        snapshot = {"message_id": "care-test", "at": 100.0, "text": "Muito"}
        turn_key = f"{CHAT}:care-test"
        with contextlib.ExitStack() as stack:
            for name, value in {
                "_session_is_owner": False,
                "_resolve_mapped_chat_id": CHAT,
                "_select_transform_turn": (turn_key, snapshot),
                "_current_inbound_record": snapshot,
                "_calendar_state_for_turn": {},
                "_model_response_expired": False,
                "_inbound_prompt_injection_kind": "",
                "_prompt_injection_kind": "",
                "_unrelated_assistant_task_redirect": "",
                "_contact_record_for_chat": {},
                "_fetch_chat_history": "AYA: Isso vem te afetando no trabalho em outros momento também?",
                "_reserve_contact_send": (True, turn_key),
            }.items():
                stack.enter_context(mock.patch.object(wm, name, return_value=value))
            stack.enter_context(mock.patch.object(wm, "_calendar_guard_completion_claim", side_effect=lambda text, **kwargs: text))
            stack.enter_context(mock.patch.object(wm, "_enforce_internal_role_output_gate", side_effect=lambda text, **kwargs: text))
            schedule = stack.enter_context(mock.patch.object(wm, "_schedule_contact_reply", return_value=True))
            result = wm.transform_llm_output(
                platform="whatsapp", session_id=CHAT, turn_id="care-test", response_text=response,
            )
        self.assertEqual(result, "\n")
        schedule.assert_called_once()
        self.assertNotIn("leve isso", schedule.call_args.args[1])
        self.assertIn("Vou te explicar como funciona o atendimento.", schedule.call_args.args[1])
        self.assertNotIn("gostaria", schedule.call_args.args[1])

    def test_generic_config_subdir_does_not_disable_therapify_order_gate(self):
        visible = self._gate(MODEL_COMMERCIAL_REPLY, "Quanto tempo dura a sessão?")
        self.assertIn("maiores informações", visible.casefold())
        self._assert_commercial_details_suppressed(visible)

    def test_early_commercial_questions_use_fixed_transition_before_completion(self):
        questions = [
            "Qual é o preço?",
            "Como faço o pagamento?",
            "Quanto tempo dura a sessão?",
            "É no Meet ou presencial?",
            "Qual é o formato do atendimento?",
            "Isso é uma sessão ou o tratamento?",
        ]
        for question in questions:
            with self.subTest(question=question):
                visible = self._gate(MODEL_COMMERCIAL_REPLY, question)
                self.assertIn("maiores informações", visible.casefold())
                self.assertRegex(visible.casefold(), r"relacionamento|terminaram")
                self._assert_commercial_details_suppressed(visible)

    def test_mixed_duration_and_diagnostic_answer_keeps_diagnostic_progress(self):
        visible = self._gate(MODEL_COMMERCIAL_REPLY, "Quanto dura? Faz 2 dias")
        self.assertIn("maiores informações", visible.casefold())
        self.assertRegex(visible.casefold(), r"relacionamento|ansiedade|alimenta[cç][aã]o")
        self._assert_commercial_details_suppressed(visible)

    def test_completed_playbook_allows_commercial_details(self):
        visible = self._gate(
            MODEL_COMMERCIAL_REPLY,
            "Quanto tempo dura a sessão?",
            contact={"playbook_completion_at": "2026-09-14T12:00:00-03:00"},
        )
        self.assertEqual(visible, MODEL_COMMERCIAL_REPLY)

    def test_abbreviated_free_question_is_answered_after_phase_three(self):
        for message in ("D graca?", "21h, d graça?", "A sessão é gratuita?"):
            with self.subTest(message=message):
                visible = self._gate(
                    "Qual horário ficaria mais confortável para ti?",
                    message,
                    contact={wm._PLAYBOOK_COMPLETION_FIELD: 1.0},
                )
                self.assertIn("não", visible.casefold())
                self.assertIn("R$ 247,00", visible)
                self.assertNotIn("horário", visible.casefold())

    def test_abbreviated_free_question_respects_early_commercial_gate(self):
        visible = self._gate(MODEL_COMMERCIAL_REPLY, "D graca?")
        self._assert_commercial_details_suppressed(visible)
        self.assertIn("Vamos lhe passar maiores informações", visible)

    def test_free_question_is_not_replaced_by_booking_confirmation(self):
        response = "Sua reunião está confirmada!"
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value={"meet_link": "https://meet.google.com/aaa-bbbb-ccc", "start": "2999-01-07T17:00:00-03:00"}
        ), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={wm._PLAYBOOK_COMPLETION_FIELD: 1.0}
        ):
            visible = wm._calendar_guard_completion_claim(response, user_message="D graca?", chat_id=CHAT)
        self.assertIn("não", visible.casefold())
        self.assertIn("R$ 247,00", visible)
        self.assertNotIn("confirmada", visible.casefold())

    def test_free_question_reaches_outbound_with_official_price(self):
        message = "D graca?"
        snapshot = {"message_id": "free-question", "at": 100.0, "text": message}
        turn_key = f"{CHAT}:free-question"
        with contextlib.ExitStack() as stack:
            for name, value in {
                "_session_is_owner": False,
                "_resolve_mapped_chat_id": CHAT,
                "_select_transform_turn": (turn_key, snapshot),
                "_current_inbound_record": snapshot,
                "_calendar_state_for_turn": {},
                "_model_response_expired": False,
                "_inbound_prompt_injection_kind": "",
                "_prompt_injection_kind": "",
                "_unrelated_assistant_task_redirect": "",
                "_contact_record_for_chat": {wm._PLAYBOOK_COMPLETION_FIELD: 1.0},
                "_fetch_chat_history": "AYA: Qual horário ficaria mais confortável para ti?",
                "_reserve_contact_send": (True, turn_key),
            }.items():
                stack.enter_context(mock.patch.object(wm, name, return_value=value))
            stack.enter_context(mock.patch.object(wm, "_enforce_internal_role_output_gate", side_effect=lambda text, **kwargs: text))
            schedule = stack.enter_context(mock.patch.object(wm, "_schedule_contact_reply", return_value=True))
            wm.transform_llm_output(
                platform="whatsapp", session_id=CHAT, turn_id="free-question",
                response_text="Qual horário ficaria mais confortável para ti?",
            )
        schedule.assert_called_once()
        sent = schedule.call_args.args[1]
        self.assertIn("não", sent.casefold())
        self.assertIn("R$ 247,00", sent)
        self.assertNotIn("horário", sent.casefold())

    def test_initial_price_question_keeps_mandatory_phase1_block(self):
        visible = self._gate(
            FASE1_OPENING,
            "Qual é o valor?",
            history="",
            contact={},
        )
        self.assertEqual(visible, FASE1_OPENING)
        self.assertIn("R$ 247,00", visible)


class TherapifyHoursTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "WHATSAPP_BUSINESS_PROFILE": "therapify",
                    "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
                    "WHATSAPP_CONFIG_SUBDIR": "generic",
                    "WHATSAPP_FOLLOWUP_ENABLED": "true",
                },
            )
        )
        self.db_path = Path(self.tmp.name) / "whatsapp_messages.db"
        con = sqlite3.connect(self.db_path)
        try:
            con.executescript(MESSAGES_SCHEMA)
        finally:
            con.close()
        self.enterContext(mock.patch.object(wm, "_MSG_DB_PATH", self.db_path))
        self.enterContext(mock.patch.object(wm, "_FOLLOWUP_DB_PATH", Path(self.tmp.name) / "followups.db"))
        wm._FOLLOWUP_ENGINE = None
        self.addCleanup(setattr, wm, "_FOLLOWUP_ENGINE", None)
        self.record: dict = {}
        self.enterContext(
            mock.patch.object(
                wm,
                "_contact_record_for_chat",
                side_effect=lambda _chat_id, contacts=None: dict(self.record),
            )
        )
        self.enterContext(
            mock.patch.object(
                wm,
                "_merge_contact_record_atomic",
                side_effect=lambda _key, fields, **_kwargs: self.record.update(fields),
            )
        )
        self.enterContext(mock.patch.object(wm, "_session_is_owner", return_value=False))
        self.enterContext(
            mock.patch.object(
                wm,
                "_contact_effect_identity_lock",
                side_effect=lambda *_args, **_kwargs: contextlib.nullcontext(),
            )
        )

    def _jobs(self) -> list[dict]:
        path = Path(self.tmp.name) / "followups.db"
        if not path.exists():
            return []
        con = sqlite3.connect(path)
        try:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute("SELECT * FROM followup_jobs ORDER BY id")]
        finally:
            con.close()

    def test_lead_novo_weekend_opening_is_deferred_to_weekday(self):
        now = _brt(2026, 9, 12, 10, 0)
        with mock.patch.object(wm, "_hum_now", return_value=now), mock.patch.object(
            wm, "_hum_after", side_effect=lambda value, _prefix: value + dt.timedelta(minutes=15)
        ):
            reason = wm._ritmo_gate(CHAT, is_replay=False)
        self.assertEqual(reason, "ritmo-lead-novo")
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)
        due = dt.datetime.fromisoformat(jobs[0]["due_utc"]).astimezone(BRT)
        self.assertEqual(jobs[0]["off_days_ok"], 0)
        self.assertGreaterEqual(due.weekday(), 0)
        self.assertLessEqual(due.weekday(), 4)
        self.assertGreaterEqual(due, dt.datetime(2026, 9, 14, 9, 0, tzinfo=BRT))

    def test_final_send_gate_blocks_lead_novo_on_weekend(self):
        now = _brt(2026, 9, 13, 10, 0)
        with mock.patch.object(wm, "_hum_now", return_value=now), mock.patch.object(
            wm, "_hum_after", side_effect=lambda value, _prefix: value + dt.timedelta(minutes=15)
        ):
            allowed = wm._ritmo_send_window_ok(CHAT)
        self.assertFalse(allowed)
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)
        due = dt.datetime.fromisoformat(jobs[0]["due_utc"]).astimezone(BRT)
        self.assertEqual(jobs[0]["off_days_ok"], 0)
        self.assertEqual(due.weekday(), 0)
        self.assertGreaterEqual(due, dt.datetime(2026, 9, 14, 9, 0, tzinfo=BRT))

    def test_weekday_inside_window_still_allows_automatic_send(self):
        now = _brt(2026, 9, 15, 10, 0)
        with mock.patch.object(wm, "_hum_now", return_value=now):
            self.assertTrue(wm._ritmo_send_window_ok(CHAT))

    def test_disabled_followup_engine_does_not_disable_absolute_hours_gate(self):
        now = _brt(2026, 9, 13, 10, 0)
        with mock.patch.dict(os.environ, {"WHATSAPP_FOLLOWUP_ENABLED": "false"}), \
             mock.patch.object(wm, "_hum_now", return_value=now):
            self.assertFalse(wm._ritmo_send_window_ok(CHAT))


if __name__ == "__main__":
    unittest.main()
