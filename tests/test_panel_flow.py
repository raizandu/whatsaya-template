"""Fluxo (SOP) da ficha do lead: `panel_data.flow_status` confere o `flow` do
business_profile.json da Therapify contra evidência real (mensagens, jobs,
contato, reserva). Cenários espelham produção em 2026-09-10 (docs/specs/
2026-09-10-ritmo-e-horario-therapify.md), horários em America/Sao_Paulo."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = REPO_ROOT / "panel"
for _p in (str(REPO_ROOT), str(PANEL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


panel_data = _load_module("flow_test_panel_data", PANEL_DIR / "data.py")

import calendar_booking  # noqa: E402
import history_store  # noqa: E402
from commercial_followups import FollowupEngine, engine_options_from_profile  # noqa: E402

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
THERAPIFY_PROFILE = json.loads(THERAPIFY_PROFILE_PATH.read_text(encoding="utf-8"))
SP_TZ = ZoneInfo("America/Sao_Paulo")

# As seis bolhas fixas da Fase 1, texto real do playbook (ver flow.steps.fase1 do profile).
FASE1_BODIES = [
    "Olá! Atendimento 100% online, do conforto da sua casa!!",
    "O Dr. Rodrigo Melo é especialista em dependência emocional, com 8 anos de experiência.",
    "A sessão inicial inclui liberação emocional, protocolo para descobrir a raiz do sofrimento e um plano de autocuidado – tudo por R$ 247,00.",
    "Após a primeira sessão, você já percebe os primeiros...",
    "O tempo estimado até o agendamento da sua consulta...",
    "Para entender melhor o seu caso: tem quanto tempo que terminaram? Como você vem lidando com tudo isso?",
]


def _sp(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=SP_TZ)


def _paths(
    tmp_dir: Path, *, followups_db: Path, contacts_json: Path, messages_db: Path,
    bookings_db: Path | None = None, business_profile_json: Path | None = None,
) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=contacts_json,
        messages_db=messages_db,
        followups_db=followups_db,
        bookings_db=bookings_db or missing / "bookings.db",
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
        business_profile_json=business_profile_json or THERAPIFY_PROFILE_PATH,
    )


def _write_contacts(path: Path, contacts: dict) -> None:
    path.write_text(json.dumps(contacts), encoding="utf-8")


def _init_messages_db(path: Path) -> sqlite3.Connection:
    conn = history_store.connect(str(path))
    history_store.ensure_schema(conn)
    conn.commit()
    return conn


def _insert_message(conn: sqlite3.Connection, *, chat_id: str, message_id: str, body: str, at: datetime, from_me: bool) -> None:
    conn.execute(
        "INSERT INTO messages(chat_id, message_id, message_type, body, timestamp, from_me, is_historical)"
        " VALUES (?, ?, 'text', ?, ?, ?, 0)",
        (chat_id, message_id, body, at.timestamp(), 1 if from_me else 0),
    )
    conn.commit()


class FlowStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.messages_db = self.tmp_dir / "messages.db"
        self.followups_db = self.tmp_dir / "followups.db"
        self.bookings_db = self.tmp_dir / "bookings.db"
        self.contacts_json = self.tmp_dir / "contacts.json"
        self.msg_conn = _init_messages_db(self.messages_db)
        self.addCleanup(self.msg_conn.close)
        self.paths = _paths(
            self.tmp_dir, followups_db=self.followups_db, contacts_json=self.contacts_json,
            messages_db=self.messages_db, bookings_db=self.bookings_db,
        )

    def t(self, hms: str) -> datetime:
        h, m, sec = (int(x) for x in hms.split(":"))
        return _sp(2026, 9, 10, h, m, sec)

    def _flow_for_lead_a(self, *, record: dict, extra_bot: list | None = None) -> dict:
        """Cenário do lead 5521979506458 (Fase 1 inteira, sem resposta) com registro de
        contato e bolhas extras à escolha do teste."""
        chat_id = "5521979506458@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: record})
        engine = FollowupEngine(self.followups_db, **engine_options_from_profile(THERAPIFY_PROFILE))
        engine.configure_lead(chat_id, automation_enabled=True, stage="new", now=self.t("14:37:56"))
        _insert_message(self.msg_conn, chat_id=chat_id, message_id="in-1", body="Oi, vi o anúncio", at=self.t("14:37:56"), from_me=False)
        engine.schedule_resume(chat_id, due=self.t("14:54:52"), reason="lead_novo", at=self.t("14:38:20"), off_days_ok=True)
        claimed = engine.claim_due(now=self.t("14:54:52"))
        engine.mark_sent(claimed[0]["id"], "bridge-resume-1", claimed[0]["lease_token"], at=self.t("14:55:22"))
        for i, (hms, body) in enumerate(zip(["14:57:05", "14:57:24", "14:57:40", "14:57:58", "14:58:10", "14:58:19"], FASE1_BODIES), start=1):
            _insert_message(self.msg_conn, chat_id=chat_id, message_id=f"bot-{i}", body=body, at=self.t(hms), from_me=True)
        for i, (from_me, body, at) in enumerate(extra_bot or [], start=100):
            _insert_message(self.msg_conn, chat_id=chat_id, message_id=f"x-{i}", body=body, at=at, from_me=bool(from_me))
        engine.note_outbound(chat_id, message_id="bot-6", cadence_kind="reactivation", at=self.t("14:58:25"))
        return panel_data.flow_status(self.paths, chat_id, now=self.t("15:30:00"))

    def test_lead_a_silent_after_fase1_carries_armed_reactivation(self):
        # Lead 5521979506458: escreve, dorme os 12-35 min de Lead Novo, recebe a
        # Fase 1 inteira e não responde — a Fase 7 já fica armada em segundo plano.
        chat_id = "5521979506458@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead A"}})
        engine = FollowupEngine(self.followups_db, **engine_options_from_profile(THERAPIFY_PROFILE))
        engine.configure_lead(chat_id, automation_enabled=True, stage="new", now=_sp(2026, 9, 10, 14, 37, 56))

        inbound_at = _sp(2026, 9, 10, 14, 37, 56)
        _insert_message(self.msg_conn, chat_id=chat_id, message_id="in-1", body="Oi, vi o anúncio", at=inbound_at, from_me=False)

        due_at = _sp(2026, 9, 10, 14, 54, 52)
        engine.schedule_resume(chat_id, due=due_at, reason="lead_novo", at=_sp(2026, 9, 10, 14, 38, 20), off_days_ok=True)
        claimed = engine.claim_due(now=due_at)
        self.assertEqual(len(claimed), 1)
        engine.mark_sent(claimed[0]["id"], "bridge-resume-1", claimed[0]["lease_token"], at=_sp(2026, 9, 10, 14, 55, 22))

        bubble_times = [
            (14, 57, 5), (14, 57, 24), (14, 57, 40), (14, 57, 58), (14, 58, 10), (14, 58, 19),
        ]
        for i, ((h, m, s), body) in enumerate(zip(bubble_times, FASE1_BODIES), start=1):
            _insert_message(self.msg_conn, chat_id=chat_id, message_id=f"bot-{i}", body=body, at=_sp(2026, 9, 10, h, m, s), from_me=True)

        engine.note_outbound(chat_id, message_id="bot-6", cadence_kind="reactivation", at=_sp(2026, 9, 10, 14, 58, 25))

        flow = panel_data.flow_status(self.paths, chat_id, now=_sp(2026, 9, 10, 15, 5, 0))
        self.assertIsNotNone(flow)
        steps = {step["id"]: step for step in flow["steps"]}

        self.assertEqual(steps["inbound"]["state"], "done")

        self.assertEqual(steps["lead_novo_wait"]["state"], "done")
        self.assertIsNotNone(steps["lead_novo_wait"]["check"])
        self.assertTrue(steps["lead_novo_wait"]["check"]["ok"])
        self.assertIn("17 min", steps["lead_novo_wait"]["check"]["label"])
        self.assertIn("esperado 12 a 35", steps["lead_novo_wait"]["check"]["label"])

        self.assertEqual(steps["fase1"]["state"], "done")
        self.assertEqual(steps["fase1"]["detail"], "6 de 6 bolhas")
        self.assertTrue(steps["fase1"]["check"]["ok"])
        self.assertEqual(steps["fase1"]["check"]["label"], "6 de 6")

        self.assertEqual(steps["fase1_reply"]["state"], "current")
        self.assertEqual(steps["fase2"]["state"], "pending")
        self.assertEqual(steps["fase3"]["state"], "pending")
        self.assertEqual(steps["fase4_5"]["state"], "pending")
        self.assertEqual(steps["outcome"]["state"], "pending")

        # opcional sem evidência nenhuma some da lista; opcional com job em
        # andamento (Fase 7 armada) aparece mesmo sem ser a etapa "current".
        self.assertNotIn("downsell", steps)
        self.assertIn("fase7", steps)
        self.assertEqual(steps["fase7"]["state"], "pending")
        self.assertIsNotNone(steps["fase7"]["due_utc"])

        self.assertIn("aguardando resposta do lead", flow["summary"])

    def test_fase1_partial_bubble_is_done_with_truncation_warning(self):
        chat_id = "5521900000002@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead B"}})
        _insert_message(self.msg_conn, chat_id=chat_id, message_id="in-1", body="Oi", at=_sp(2026, 9, 10, 10, 0, 0), from_me=False)
        _insert_message(
            self.msg_conn, chat_id=chat_id, message_id="bot-1",
            body="Me conta um pouco: tem quanto tempo que terminaram?",
            at=_sp(2026, 9, 10, 10, 20, 0), from_me=True,
        )

        flow = panel_data.flow_status(self.paths, chat_id, now=_sp(2026, 9, 10, 10, 30, 0))
        steps = {step["id"]: step for step in flow["steps"]}

        self.assertEqual(steps["fase1"]["state"], "done")
        self.assertEqual(steps["fase1"]["detail"], "1 de 6 bolhas")
        self.assertFalse(steps["fase1"]["check"]["ok"])
        self.assertIn("1 de 6", steps["fase1"]["check"]["label"])
        self.assertIn("abertura truncada", steps["fase1"]["check"]["label"])

    def _seed_fase2_diagnostic(self, chat_id: str, *, last_answer_at: datetime, reaction_delay_s: int) -> datetime:
        base = _sp(2026, 9, 10, 11, 0, 0)
        _insert_message(self.msg_conn, chat_id=chat_id, message_id="in-1", body="Oi", at=base, from_me=False)
        for i, body in enumerate(FASE1_BODIES, start=1):
            _insert_message(self.msg_conn, chat_id=chat_id, message_id=f"f1-{i}", body=body, at=base + timedelta(minutes=i), from_me=True)
        lead_reply_at = base + timedelta(minutes=10)
        _insert_message(self.msg_conn, chat_id=chat_id, message_id="reply-1", body="Terminamos há 2 meses", at=lead_reply_at, from_me=False)

        q_at = lead_reply_at + timedelta(minutes=1)
        questions = [
            "Você tem sentido ansiedade, desânimo?",
            "Sua alimentação está normal?",
            "De zero a dez, qual seu nível de ansiedade?",
            "Isso está afetando no trabalho?",
        ]
        for i, body in enumerate(questions, start=1):
            _insert_message(self.msg_conn, chat_id=chat_id, message_id=f"f2q-{i}", body=body, at=q_at + timedelta(seconds=i * 5), from_me=True)

        for i, body in enumerate(["Ansiedade", "Desânimo também", "Sim, afeta"], start=1):
            _insert_message(
                self.msg_conn, chat_id=chat_id, message_id=f"ans-{i}", body=body,
                at=last_answer_at - timedelta(seconds=(3 - i)), from_me=False,
            )

        reaction_at = last_answer_at + timedelta(seconds=reaction_delay_s)
        _insert_message(
            self.msg_conn, chat_id=chat_id, message_id="reaction-1",
            body="É comum a pessoa deixar de sentir fome quando isso acontece",
            at=reaction_at, from_me=True,
        )
        return reaction_at

    def test_fase2_debounce_ok_when_bot_waits_before_reacting(self):
        chat_id = "5521900000003@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead C"}})
        last_answer_at = _sp(2026, 9, 10, 11, 20, 0)
        reaction_at = self._seed_fase2_diagnostic(chat_id, last_answer_at=last_answer_at, reaction_delay_s=150)

        flow = panel_data.flow_status(self.paths, chat_id, now=reaction_at + timedelta(minutes=1))
        steps = {step["id"]: step for step in flow["steps"]}

        self.assertEqual(steps["fase2"]["state"], "done")
        self.assertEqual(steps["fase2"]["detail"], "4 de 4 bolhas")
        self.assertTrue(steps["fase2"]["check"]["ok"])
        self.assertEqual(steps["fase2"]["check"]["label"], "esperou 2 min 30 s")

    def test_fase2_debounce_not_ok_when_bot_reacts_too_fast(self):
        chat_id = "5521900000004@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead C2"}})
        last_answer_at = _sp(2026, 9, 10, 11, 20, 0)
        reaction_at = self._seed_fase2_diagnostic(chat_id, last_answer_at=last_answer_at, reaction_delay_s=25)

        flow = panel_data.flow_status(self.paths, chat_id, now=reaction_at + timedelta(minutes=1))
        steps = {step["id"]: step for step in flow["steps"]}

        self.assertEqual(steps["fase2"]["state"], "done")
        self.assertFalse(steps["fase2"]["check"]["ok"])
        self.assertEqual(steps["fase2"]["check"]["label"], "⚠ respondeu em 25 s")

    def test_relationship_cliente_e_valor_na_abertura_nao_fecham_etapas(self):
        # Todo lead admitido nasce com relationship "Cliente" e a abertura já cita R$ 247,00:
        # nenhum dos dois pode contar como Fase 4/5 feita nem como "virou paciente".
        rec = {"name": "Lead A", "relationship": "Cliente"}
        steps = {s["id"]: s for s in self._flow_for_lead_a(record=rec)["steps"]}
        self.assertEqual(steps["fase4_5"]["state"], "pending")
        self.assertEqual(steps["outcome"]["state"], "pending")

    def test_etiqueta_novo_cliente_vira_paciente_e_nome_completo_fecha_fase5(self):
        rec = {"name": "Lead A", "relationship": "Cliente", "ai_disabled_reason": "label_client"}
        extra = [(1, "Como é seu nome completo?", self.t("15:20:00"))]
        steps = {s["id"]: s for s in self._flow_for_lead_a(record=rec, extra_bot=extra)["steps"]}
        self.assertEqual(steps["fase4_5"]["state"], "done")
        self.assertEqual(steps["outcome"]["detail"], "virou paciente")

    def test_outcome_agendou_when_booking_exists(self):
        chat_id = "5521900000005@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead D", "playbook_completion_at": time.time()}})
        last_answer_at = _sp(2026, 9, 10, 11, 20, 0)
        reaction_at = self._seed_fase2_diagnostic(chat_id, last_answer_at=last_answer_at, reaction_delay_s=150)

        calendar_booking._ensure_booking_store(self.bookings_db)
        created_at = time.time()
        with contextlib.closing(sqlite3.connect(self.bookings_db)) as conn:
            conn.execute(
                "INSERT INTO current_bookings(chat_key, event_id, start, end, timezone, meet_link, html_link,"
                " status, created_at, updated_at) VALUES (?, 'evt-1', ?, ?, 'America/Sao_Paulo', 'https://meet.example', '', 'active', ?, ?)",
                (
                    calendar_booking._booking_chat_key(chat_id),
                    "2026-09-11T14:00:00+00:00", "2026-09-11T15:00:00+00:00",
                    created_at, created_at,
                ),
            )
            conn.commit()

        flow = panel_data.flow_status(self.paths, chat_id, now=reaction_at + timedelta(minutes=1))
        steps = {step["id"]: step for step in flow["steps"]}

        self.assertEqual(steps["fase1_reply"]["state"], "done")
        self.assertEqual(steps["fase2"]["state"], "done")
        self.assertEqual(steps["fase3"]["state"], "done")
        self.assertEqual(steps["fase4_5"]["state"], "done")
        self.assertEqual(steps["outcome"]["state"], "done")
        self.assertEqual(steps["outcome"]["detail"], "agendou")
        self.assertEqual(flow["summary"], "Desfecho · agendou")

    def test_missing_flow_block_returns_none(self):
        chat_id = "5521900000006@s.whatsapp.net"
        profile_without_flow = dict(THERAPIFY_PROFILE)
        profile_without_flow.pop("flow", None)
        profile_path = self.tmp_dir / "profile_no_flow.json"
        profile_path.write_text(json.dumps(profile_without_flow), encoding="utf-8")
        paths = _paths(
            self.tmp_dir, followups_db=self.followups_db, contacts_json=self.contacts_json,
            messages_db=self.messages_db, bookings_db=self.bookings_db, business_profile_json=profile_path,
        )
        self.assertIsNone(panel_data.flow_status(paths, chat_id))

    def test_lead_detail_payload_carries_none_when_profile_has_no_flow(self):
        chat_id = "5521900000007@s.whatsapp.net"
        _write_contacts(self.contacts_json, {chat_id: {"name": "Lead E"}})
        profile_without_flow = dict(THERAPIFY_PROFILE)
        profile_without_flow.pop("flow", None)
        profile_path = self.tmp_dir / "profile_no_flow.json"
        profile_path.write_text(json.dumps(profile_without_flow), encoding="utf-8")
        paths = _paths(
            self.tmp_dir, followups_db=self.followups_db, contacts_json=self.contacts_json,
            messages_db=self.messages_db, bookings_db=self.bookings_db, business_profile_json=profile_path,
        )
        detail = panel_data.lead_detail(paths, chat_id)
        self.assertIsNone(detail["flow"])


if __name__ == "__main__":
    unittest.main()
