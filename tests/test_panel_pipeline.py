from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


panel_data = _load_module("data", PANEL_DIR / "data.py")
panel_actions = _load_module("actions", PANEL_DIR / "actions.py")

from commercial_followups import FollowupEngine, engine_options_from_profile  # noqa: E402
from therapify_preset import THERAPIFY_PIPELINE  # noqa: E402

THERAPIFY_PROFILE = json.loads(
    (REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json").read_text(encoding="utf-8")
)


def _create_therapify_tables(db_path: Path) -> None:
    """Mesmo schema de `deploy/clients/therapify/tools/therapify_migrate.py:_ensure_followup_schema`,
    só as tabelas importadas do Therapify (o resto já vem do `FollowupEngine`)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS therapify_leads (
                source_phone TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL UNIQUE,
                profile_name TEXT,
                full_name TEXT,
                gender TEXT,
                status TEXT NOT NULL,
                is_existing_patient INTEGER NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 0,
                last_phase TEXT,
                last_inbound_at TEXT,
                last_outbound_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                migrated_at TEXT NOT NULL,
                source_status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_phone TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                slot_start TEXT NOT NULL,
                slot_end TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                migrated_at TEXT NOT NULL,
                UNIQUE(source_id, source_phone)
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_phone TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                product TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                migrated_at TEXT NOT NULL,
                UNIQUE(source_id, source_phone)
            );
            CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_phone TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                migrated_at TEXT NOT NULL,
                UNIQUE(source_id, source_phone)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_therapify_lead(db_path: Path, chat_id: str, status: str, *, is_existing_patient: int = 0) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO therapify_leads(source_phone, chat_id, status, is_existing_patient, migrated_at, source_status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, chat_id, status, is_existing_patient, "2024-01-01T00:00:00+00:00", status),
        )
        conn.commit()
    finally:
        conn.close()


def _touch_lead_timestamp(db_path: Path, chat_id: str, when: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE lead_state SET last_inbound_utc=?, updated_utc=? WHERE chat_id=?",
            (when.isoformat(), when.isoformat(), chat_id),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_appointment(db_path: Path, chat_id: str, created_at: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO appointments(source_id, source_phone, chat_id, slot_start, slot_end, kind, status, created_at, migrated_at)"
            " VALUES (?, ?, ?, ?, ?, 'session', 'scheduled', ?, ?)",
            (chat_id, chat_id, chat_id, created_at.isoformat(), created_at.isoformat(), created_at.isoformat(), created_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_purchase(db_path: Path, chat_id: str, product: str, amount: float, created_at: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO purchases(source_id, source_phone, chat_id, product, amount, created_at, migrated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"{chat_id}-{product}", chat_id, chat_id, product, amount, created_at.isoformat(), created_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_escalation(db_path: Path, chat_id: str, *, resolved: int, created_at: datetime) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO escalations(source_id, source_phone, chat_id, reason, resolved, created_at, migrated_at)"
            " VALUES (?, ?, ?, 'teste', ?, ?, ?)",
            (f"{chat_id}-esc", chat_id, chat_id, resolved, created_at.isoformat(), created_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _paths(tmp_dir: Path, *, followups_db: Path, contacts_json: Path) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=contacts_json,
        messages_db=missing / "messages.db",
        followups_db=followups_db,
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
    )


def _write_contacts(path: Path, contacts: dict) -> None:
    path.write_text(json.dumps(contacts), encoding="utf-8")


class ResolvePipelineStageTests(unittest.TestCase):
    def setUp(self):
        self.default = panel_data.pipeline("default")
        self.therapify = panel_data.pipeline(THERAPIFY_PIPELINE)

    def test_contact_override_wins_over_everything(self):
        stage = panel_data.resolve_pipeline_stage(
            self.therapify,
            contact_record={"pipeline_stage": "lost"},
            lead_row={"stage": "qualification"},
            imported_row={"status": "in_funnel"},
        )
        self.assertEqual(stage, "lost")

    def test_invalid_override_falls_through_to_reverse_map(self):
        stage = panel_data.resolve_pipeline_stage(
            self.therapify,
            contact_record={"pipeline_stage": "not_a_real_stage"},
            lead_row={"stage": "new"},
            imported_row=None,
        )
        self.assertEqual(stage, "new")

    def test_therapify_status_wins_over_reverse_map(self):
        stage = panel_data.resolve_pipeline_stage(
            self.therapify,
            contact_record={},
            lead_row={"stage": "payment"},
            imported_row={"status": "purchased_gravado"},
        )
        self.assertEqual(stage, "purchased_gravado")

    def test_existing_patient_by_status_is_excluded(self):
        stage = panel_data.resolve_pipeline_stage(
            self.therapify,
            contact_record={},
            lead_row={"stage": "won"},
            imported_row={"status": "existing_patient"},
        )
        self.assertIsNone(stage)

    def test_existing_patient_by_flag_is_excluded(self):
        stage = panel_data.resolve_pipeline_stage(
            self.therapify,
            contact_record={},
            lead_row={"stage": "qualification"},
            imported_row={"status": "in_funnel", "excluded": 1},
        )
        self.assertIsNone(stage)

    def test_reverse_map_lost_variants(self):
        for engine_stage in ("lost",):
            with self.subTest(engine_stage=engine_stage):
                stage = panel_data.resolve_pipeline_stage(
                    self.therapify, contact_record={}, lead_row={"stage": engine_stage}, imported_row=None,
                )
                self.assertEqual(stage, "lost")

    def test_reverse_map_in_funnel_variants(self):
        for engine_stage in ("qualification", "pricing", "proposal", "payment"):
            with self.subTest(engine_stage=engine_stage):
                stage = panel_data.resolve_pipeline_stage(
                    self.therapify, contact_record={}, lead_row={"stage": engine_stage}, imported_row=None,
                )
                self.assertEqual(stage, "in_funnel")

    def test_reverse_map_won_variants_are_existing_patients(self):
        for engine_stage in ("won",):
            with self.subTest(engine_stage=engine_stage):
                stage = panel_data.resolve_pipeline_stage(
                    self.therapify, contact_record={}, lead_row={"stage": engine_stage}, imported_row=None,
                )
                self.assertIsNone(stage)

    def test_default_preset_uses_engine_stage_as_is(self):
        stage = panel_data.resolve_pipeline_stage(
            self.default, contact_record={}, lead_row={"stage": "pricing"}, imported_row={"status": "in_funnel"},
        )
        self.assertEqual(stage, "pricing")

    def test_default_preset_unknown_engine_stage_falls_back_to_new(self):
        stage = panel_data.resolve_pipeline_stage(
            self.default, contact_record={}, lead_row={"stage": "won"}, imported_row=None,
        )
        self.assertEqual(stage, "new")


class LeadsTherapifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        followups_db = tmp_dir / "commercial_followups.db"
        contacts_json = tmp_dir / "personal_contacts.json"
        engine = FollowupEngine(followups_db)
        _create_therapify_tables(followups_db)

        engine.configure_lead("new1@x", stage="new")
        engine.configure_lead("funnel1@x", stage="qualification")
        engine.configure_lead("funnel2@x", stage="proposal")
        engine.configure_lead("sched1@x", stage="proposal")
        engine.configure_lead("gravado1@x", stage="payment", terminal=True)
        engine.configure_lead("protocolo1@x", stage="payment", terminal=True)
        engine.configure_lead("lost1@x", stage="lost", terminal=True)
        engine.configure_lead("override1@x", stage="new")
        engine.configure_lead("existing1@x", stage="won", terminal=True)
        engine.configure_lead("blocked1@x", stage="new")

        _insert_therapify_lead(followups_db, "funnel1@x", "in_funnel")
        _insert_therapify_lead(followups_db, "sched1@x", "scheduled_session")
        _insert_therapify_lead(followups_db, "gravado1@x", "purchased_gravado")
        _insert_therapify_lead(followups_db, "protocolo1@x", "purchased_protocolo_final")
        _insert_therapify_lead(followups_db, "lost1@x", "lost")
        _insert_therapify_lead(followups_db, "existing1@x", "existing_patient", is_existing_patient=1)

        _write_contacts(contacts_json, {
            "override1@x": {"name": "Override", "pipeline_stage": "purchased_gravado"},
            "blocked1@x": {"name": "Blocked", "blocked": True},
        })

        self.paths = _paths(tmp_dir, followups_db=followups_db, contacts_json=contacts_json)

    def test_six_ordered_columns_with_exact_labels(self):
        result = panel_data.leads(self.paths, pipeline_id=THERAPIFY_PIPELINE)
        self.assertEqual(result["pipeline"], "therapify")
        expected = [
            ("new", "Novo", False),
            ("in_funnel", "No funil", False),
            ("scheduled_session", "Sessão agendada", False),
            ("purchased_gravado", "Comprou R$47", True),
            ("purchased_protocolo_final", "Comprou R$27", True),
            ("lost", "Perdido", True),
        ]
        got = [(s["id"], s["label"], s["terminal"]) for s in result["stages"]]
        self.assertEqual(got, expected)

    def test_cards_land_in_the_right_columns(self):
        result = panel_data.leads(self.paths, pipeline_id=THERAPIFY_PIPELINE)
        by_stage = {s["id"]: {c["chat_id"] for c in s["cards"]} for s in result["stages"]}
        self.assertEqual(by_stage["new"], {"new1@x"})
        self.assertEqual(by_stage["in_funnel"], {"funnel1@x", "funnel2@x"})
        self.assertEqual(by_stage["scheduled_session"], {"sched1@x"})
        self.assertEqual(by_stage["purchased_gravado"], {"gravado1@x", "override1@x"})
        self.assertEqual(by_stage["purchased_protocolo_final"], {"protocolo1@x"})
        self.assertEqual(by_stage["lost"], {"lost1@x"})

    def test_existing_patient_excluded_and_counted(self):
        result = panel_data.leads(self.paths, pipeline_id=THERAPIFY_PIPELINE)
        all_cards = {c["chat_id"] for s in result["stages"] for c in s["cards"]}
        self.assertNotIn("existing1@x", all_cards)
        self.assertEqual(result["excluded"]["outside_funnel"], 1)

    def test_blocked_skipped_and_counted(self):
        result = panel_data.leads(self.paths, pipeline_id=THERAPIFY_PIPELINE)
        all_cards = {c["chat_id"] for s in result["stages"] for c in s["cards"]}
        self.assertNotIn("blocked1@x", all_cards)
        self.assertEqual(result["excluded"]["blocked"], 1)

    def test_total_counts_only_non_terminal_columns(self):
        result = panel_data.leads(self.paths, pipeline_id=THERAPIFY_PIPELINE)
        # new(1) + in_funnel(2) + scheduled_session(1) = 4; as três colunas terminais
        # (purchased_gravado, purchased_protocolo_final, lost) ficam de fora.
        self.assertEqual(result["total"], 4)


class LeadsDefaultTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        followups_db = tmp_dir / "commercial_followups.db"
        contacts_json = tmp_dir / "personal_contacts.json"
        engine = FollowupEngine(followups_db)

        engine.configure_lead("d1@x", stage="qualification")
        engine.configure_lead("d2@x", stage="won")
        engine.configure_lead("d3@x", stage="new")

        _write_contacts(contacts_json, {"d3@x": {"name": "Blocked", "blocked": True}})

        self.paths = _paths(tmp_dir, followups_db=followups_db, contacts_json=contacts_json)

    def test_five_columns_terminal_rows_skipped_and_counted(self):
        result = panel_data.leads(self.paths, pipeline_id="default")
        self.assertEqual(result["pipeline"], "default")
        got = [(s["id"], s["label"], s["terminal"]) for s in result["stages"]]
        expected = [(sid, panel_data.STAGE_LABEL[sid], False) for sid in panel_data.STAGES]
        self.assertEqual(got, expected)
        by_stage = {s["id"]: {c["chat_id"] for c in s["cards"]} for s in result["stages"]}
        self.assertEqual(by_stage["qualification"], {"d1@x"})
        self.assertEqual(result["terminal"], {"won": 1, "lost": 0})
        self.assertEqual(result["excluded"], {"outside_funnel": 0, "blocked": 1})
        self.assertEqual(result["total"], 1)


class SetStageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        followups_db = tmp_dir / "commercial_followups.db"
        self.contacts_json = tmp_dir / "personal_contacts.json"
        engine = FollowupEngine(followups_db)
        engine.configure_lead("5511900000001@s.whatsapp.net", stage="new")

        _write_contacts(self.contacts_json, {
            "5511900000001@s.whatsapp.net": {"name": "Ana", "lid": "111@lid"},
            "111@lid": {"name": "Ana"},
        })
        self.paths = _paths(tmp_dir, followups_db=followups_db, contacts_json=self.contacts_json)
        self.chat_id = "5511900000001@s.whatsapp.net"

    def test_therapify_move_to_terminal_writes_pipeline_stage_on_both_mirrors(self):
        result = panel_actions.set_stage(
            self.paths, chat_id=self.chat_id, stage="purchased_gravado", pipeline_id=THERAPIFY_PIPELINE,
        )
        self.assertEqual(result["stage"], "purchased_gravado")
        self.assertEqual(result["engine_stage"], "payment")
        self.assertEqual(result["lead"]["stage"], "payment")
        self.assertEqual(int(result["lead"]["terminal"]), 1)

        contacts = panel_data.load_contacts(self.contacts_json)
        self.assertEqual(contacts["5511900000001@s.whatsapp.net"]["pipeline_stage"], "purchased_gravado")
        self.assertEqual(contacts["111@lid"]["pipeline_stage"], "purchased_gravado")

    def test_moving_back_out_of_terminal_clears_terminal_flag(self):
        panel_actions.set_stage(self.paths, chat_id=self.chat_id, stage="purchased_gravado", pipeline_id=THERAPIFY_PIPELINE)
        result = panel_actions.set_stage(self.paths, chat_id=self.chat_id, stage="in_funnel", pipeline_id=THERAPIFY_PIPELINE)
        self.assertEqual(result["engine_stage"], "qualification")
        self.assertEqual(int(result["lead"]["terminal"]), 0)
        contacts = panel_data.load_contacts(self.contacts_json)
        self.assertEqual(contacts["5511900000001@s.whatsapp.net"]["pipeline_stage"], "in_funnel")

    def test_invalid_stage_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id=self.chat_id, stage="not_a_stage", pipeline_id=THERAPIFY_PIPELINE)

    def test_unknown_lead_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id="ghost@x", stage="new", pipeline_id=THERAPIFY_PIPELINE)

    def test_default_preset_leaves_contacts_untouched(self):
        panel_actions.set_stage(self.paths, chat_id=self.chat_id, stage="purchased_gravado", pipeline_id=THERAPIFY_PIPELINE)
        result = panel_actions.set_stage(self.paths, chat_id=self.chat_id, stage="pricing", pipeline_id="default")
        self.assertEqual(result["engine_stage"], "pricing")
        contacts = panel_data.load_contacts(self.contacts_json)
        # A escrita anterior (therapify) fica; o preset default não mexe em contato nenhum.
        self.assertEqual(contacts["5511900000001@s.whatsapp.net"]["pipeline_stage"], "purchased_gravado")


class CommercialMetricsTests(unittest.TestCase):
    def test_totals_period_products_and_escalations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            followups_db = tmp_dir / "commercial_followups.db"
            contacts_json = tmp_dir / "personal_contacts.json"
            engine = FollowupEngine(followups_db)
            _create_therapify_tables(followups_db)

            now = datetime(2024, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
            start, _end = panel_data._period_bounds("7d", now)

            engine.configure_lead("leadA@x", stage="qualification")
            engine.configure_lead("leadB@x", stage="qualification")
            engine.configure_lead("leadC@x", stage="qualification")  # blocked
            owner_number = "5511999999999"
            engine.configure_lead(f"{owner_number}@s.whatsapp.net", stage="qualification")  # owner

            _touch_lead_timestamp(followups_db, "leadA@x", start + timedelta(hours=1))
            _touch_lead_timestamp(followups_db, "leadB@x", start - timedelta(days=3))
            _touch_lead_timestamp(followups_db, "leadC@x", start + timedelta(hours=1))
            _touch_lead_timestamp(followups_db, f"{owner_number}@s.whatsapp.net", start + timedelta(hours=1))

            _write_contacts(contacts_json, {"leadC@x": {"name": "Blocked", "blocked": True}})

            _insert_appointment(followups_db, "leadA@x", start + timedelta(hours=1))
            _insert_appointment(followups_db, "leadB@x", start - timedelta(days=2))

            _insert_purchase(followups_db, "leadA@x", "metodo_gravado", 47.0, start + timedelta(hours=1))
            _insert_purchase(followups_db, "leadB@x", "metodo_gravado", 47.0, start - timedelta(days=2))
            _insert_purchase(followups_db, "leadA@x", "protocolo_final", 27.0, start + timedelta(hours=2))
            _insert_purchase(followups_db, "leadA@x", "mystery_product", 99.0, start + timedelta(hours=3))

            _insert_escalation(followups_db, "leadA@x", resolved=0, created_at=start)
            _insert_escalation(followups_db, "leadB@x", resolved=1, created_at=start)

            paths = _paths(tmp_dir, followups_db=followups_db, contacts_json=contacts_json)
            commercial = panel_data.metrics(
                paths, "7d", now=now, pipeline_id=THERAPIFY_PIPELINE, owner_number=owner_number,
            )["commercial"]

            self.assertEqual(commercial["leads_total"], 2)  # leadA, leadB — leadC bloqueado, owner fora
            self.assertEqual(commercial["leads_period"], 1)  # só leadA está dentro do período
            self.assertEqual(commercial["appointments_total"], 2)
            self.assertEqual(commercial["appointments_period"], 1)
            self.assertEqual(commercial["session_price_brl"], 247)
            self.assertEqual(commercial["appointments_potential_brl"], 494)
            self.assertEqual(commercial["purchases_count"], 4)
            self.assertEqual(commercial["purchases_total_brl"], 220.0)
            self.assertEqual(commercial["purchases_period_brl"], 173.0)
            self.assertEqual(commercial["purchases_by_product"], [
                {"product": "metodo_gravado", "label": "Método gravado", "unit_price_brl": 47, "count": 2, "total_brl": 94.0},
                {"product": "protocolo_final", "label": "Protocolo final", "unit_price_brl": 27, "count": 1, "total_brl": 27.0},
                {"product": "mystery_product", "label": "mystery_product", "unit_price_brl": None, "count": 1, "total_brl": 99.0},
            ])
            self.assertEqual(commercial["escalations_open"], 1)

    def test_zeros_without_exception_when_therapify_tables_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            followups_db = tmp_dir / "commercial_followups.db"
            contacts_json = tmp_dir / "personal_contacts.json"
            FollowupEngine(followups_db)  # só lead_state/followup_jobs/crm_outbox, sem tabelas do Therapify

            paths = _paths(tmp_dir, followups_db=followups_db, contacts_json=contacts_json)
            commercial = panel_data.metrics(paths, "7d", pipeline_id=THERAPIFY_PIPELINE)["commercial"]

            self.assertEqual(commercial, {
                "leads_total": 0,
                "leads_period": 0,
                "appointments_total": 0,
                "appointments_period": 0,
                "session_price_brl": 247,
                "appointments_potential_brl": 0,
                "purchases_total_brl": 0.0,
                "purchases_period_brl": 0.0,
                "purchases_count": 0,
                "purchases_by_product": [],
                "escalations_open": 0,
            })


class FollowupsViewTests(unittest.TestCase):
    """`resume` (ADR 0001) e `reactivation`/`skipped` (Fase 7, ADR 0002): rótulos e
    copy que a tela `followups.js` usa não podem regredir para "toque N de 3" nem
    para o horário fixo 8h-18h (docs/specs/2026-09-10-ritmo-e-horario-therapify.md)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.followups_db = self.tmp_dir / "commercial_followups.db"
        self.contacts_json = self.tmp_dir / "personal_contacts.json"
        _write_contacts(self.contacts_json, {"lead1@x": {"name": "Lead Um"}})
        self.paths = _paths(self.tmp_dir, followups_db=self.followups_db, contacts_json=self.contacts_json)
        self.now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

    def test_resume_job_carries_kind_and_reason_label_instead_of_step_count(self):
        engine = FollowupEngine(self.followups_db)
        engine.schedule_resume(
            "lead1@x", due=self.now - timedelta(minutes=5), reason="fila_manha", at=self.now - timedelta(hours=1),
        )
        result = panel_data.followups(self.paths, now=self.now)
        self.assertEqual(len(result["queue"]), 1)
        job = result["queue"][0]
        self.assertEqual(job["cadence"], "Retomada")
        self.assertEqual(job["kind"], "resume")
        self.assertEqual(job["reason_label"], "fila da manhã")

    def test_generic_job_keeps_plain_kind_for_step_count_rendering(self):
        engine = FollowupEngine(self.followups_db)
        engine.configure_lead("lead1@x", automation_enabled=True, stage="qualification", now=self.now)
        engine.configure_lead(
            "lead1@x", context_kind="pain", context_fact="ansiedade no trabalho",
            context_source_message_id="m1", context_verified=True, now=self.now,
        )
        engine.note_outbound("lead1@x", message_id="bridge-1", cadence_kind="silence", at=self.now)
        result = panel_data.followups(self.paths, now=self.now)
        self.assertEqual(len(result["queue"]), 3)  # a cadência "silence" agenda os 3 passos de uma vez
        self.assertTrue(all(j["kind"] == "generic" for j in result["queue"]))
        self.assertTrue(all(j["reason_label"] == "" for j in result["queue"]))

    def test_skipped_reactivation_step_gets_label_and_reason_in_lead_timeline(self):
        engine = FollowupEngine(self.followups_db, **engine_options_from_profile(THERAPIFY_PROFILE))
        engine.configure_lead("lead1@x", automation_enabled=True, stage="payment", now=self.now)
        engine.note_outbound("lead1@x", message_id="bridge-1", cadence_kind="reactivation", at=self.now)
        due = {j["step_no"]: datetime.fromisoformat(j["due_utc"]) for j in engine.get_jobs("lead1@x")}
        first = engine.claim_due(now=due[1])[0]
        engine.mark_sent(first["id"], "bridge-d1", first["lease_token"], at=due[1])
        second = engine.claim_due(now=due[2])[0]
        self.assertTrue(engine.skip_step(second["id"], second["lease_token"], "downsell_ja_oferecido", at=due[2]))

        timeline = panel_data._flow_timeline(self.paths, "lead1@x", [])
        skipped_events = [e for e in timeline if e.get("status") == "skipped"]
        self.assertEqual(len(skipped_events), 1)
        self.assertEqual(skipped_events[0]["label"], "Toque de follow-up pulado (R$47 já oferecido)")
        self.assertEqual(skipped_events[0]["reason"], "R$47 já oferecido")
        self.assertEqual(skipped_events[0]["cadence"], "Reativação")

    def test_cadence_label_covers_resume_and_reactivation(self):
        self.assertEqual(panel_data.CADENCE_LABEL["resume"], "Retomada")
        self.assertEqual(panel_data.CADENCE_LABEL["reactivation"], "Reativação")

    def test_cancel_reason_label_covers_new_engine_reasons(self):
        self.assertEqual(panel_data.CANCEL_REASON_LABEL["nothing_pending"], "nada pendente na retomada")
        self.assertEqual(panel_data.CANCEL_REASON_LABEL["downsell_ja_oferecido"], "R$47 já oferecido")
        self.assertEqual(panel_data.CANCEL_REASON_LABEL["reactivation_step_missing"], "toque sem texto no profile")

    def test_business_hours_missing_profile_returns_none(self):
        # `_paths` aponta `business_profile_json` para o default de produção
        # (`/opt/data/business_profile.json`), que não existe numa máquina de dev.
        self.assertIsNone(panel_data.load_business_hours(self.paths.business_profile_json))
        result = panel_data.followups(self.paths, now=self.now)
        self.assertIsNone(result["schedule"])

    def test_business_hours_reads_open_close_from_profile(self):
        profile_json = self.tmp_dir / "business_profile.json"
        profile_json.write_text(json.dumps({"schedule": {"open": "09:00", "close": "21:00"}}), encoding="utf-8")
        self.assertEqual(
            panel_data.load_business_hours(profile_json), {"open": "09:00", "close": "21:00"},
        )
        paths = replace(self.paths, business_profile_json=profile_json)
        result = panel_data.followups(paths, now=self.now)
        self.assertEqual(result["schedule"], {"open": "09:00", "close": "21:00"})

    def test_queue_job_exposes_created_utc_due_local_and_waiting_window(self):
        # `docs/specs/2026-09-10-ritmo-e-horario-therapify.md`: job vencido que
        # ainda está `pending` é o motor esperando o horário comercial, não atraso.
        engine = FollowupEngine(self.followups_db)
        engine.schedule_resume(
            "lead1@x", due=self.now - timedelta(minutes=5), reason="fila_manha", at=self.now - timedelta(hours=1),
        )
        result = panel_data.followups(self.paths, now=self.now)
        job = result["queue"][0]
        self.assertTrue(job["created_utc"])
        self.assertTrue(job["waiting_window"])
        self.assertRegex(job["due_local"], r"^\S{3} \d{2}/\d{2} \d{2}:\d{2}$")

    def test_reactivation_job_step_label_is_d1_d2_toque_final(self):
        engine = FollowupEngine(self.followups_db, **engine_options_from_profile(THERAPIFY_PROFILE))
        engine.configure_lead("lead1@x", automation_enabled=True, stage="payment", now=self.now)
        engine.note_outbound("lead1@x", message_id="bridge-1", cadence_kind="reactivation", at=self.now)
        result = panel_data.followups(self.paths, now=self.now)
        by_step = {j["step"]: j["step_label"] for j in result["queue"]}
        self.assertEqual(by_step, {1: "D1", 2: "D2", 3: "toque final"})
        self.assertTrue(all(j["kind"] == "reactivation" for j in result["queue"]))

    def test_load_ritmo_config_with_therapify_profile(self):
        cfg = panel_data.load_ritmo_config(
            REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
        )
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["schedule"], {"open": "09:00", "close": "21:00",
                                            "holidays_fixed": THERAPIFY_PROFILE["schedule"]["holidays_fixed"],
                                            "holidays_extra": []})
        self.assertEqual(cfg["humanization"]["first_reply"], {"min_s": 720, "max_s": 2100})
        self.assertEqual(
            cfg["humanization"]["diagnostic_debounce"],
            {"min_s": 120, "max_s": 180, "cap_s": 300},
        )
        self.assertEqual(cfg["humanization"]["reply_delay_s"]["intencao"], [5, 75])
        self.assertTrue(cfg["reactivation"]["enabled"])
        self.assertEqual(len(cfg["reactivation"]["steps"]), 3)
        self.assertEqual([s["offset"] for s in cfg["reactivation"]["steps"]], [1, 2, 3])
        self.assertEqual([s["label"] for s in cfg["reactivation"]["steps"]], ["D1", "D2", "toque final"])

    def test_load_ritmo_config_missing_profile_returns_none(self):
        self.assertIsNone(panel_data.load_ritmo_config(self.tmp_dir / "does-not-exist.json"))

    def test_ritmo_engine_status_parses_env_and_cron_log(self):
        hermes_dir = self.tmp_dir / ".hermes"
        hermes_dir.mkdir()
        env_path = hermes_dir / ".env"
        env_path.write_text("SOME_OTHER=1\nWHATSAPP_FOLLOWUP_ENABLED=true\n", encoding="utf-8")
        log_dir = hermes_dir / "logs"
        log_dir.mkdir()
        log_path = log_dir / "whatsapp_followup_cron.log"
        log_path.write_text(
            "2026-09-10 08:00:00,000 INFO tick sent=2\n"
            "2026-09-10 08:58:23,498 INFO tick sent=0\n",
            encoding="utf-8",
        )
        paths = replace(self.paths, hermes_env=env_path, followup_cron_log=log_path)
        status = panel_data._ritmo_engine_status(paths, self.now)
        self.assertTrue(status["enabled"])
        self.assertEqual(status["last_tick_sent"], 0)
        self.assertEqual(status["last_tick_rel"], "há 1 min")
        self.assertFalse(status["stalled"])

    def test_ritmo_engine_status_missing_files_returns_none_fields(self):
        paths = replace(
            self.paths,
            hermes_env=self.tmp_dir / "missing" / ".env",
            followup_cron_log=self.tmp_dir / "missing" / "cron.log",
        )
        status = panel_data._ritmo_engine_status(paths, self.now)
        self.assertIsNone(status["enabled"])
        self.assertIsNone(status["last_tick_utc"])
        self.assertEqual(status["last_tick_rel"], "")
        self.assertFalse(status["stalled"])

    def test_next_action_on_lead_payload_for_resume_job(self):
        engine = FollowupEngine(self.followups_db)
        engine.schedule_resume(
            "lead1@x", due=self.now + timedelta(minutes=8), reason="lead_novo", at=self.now,
        )
        detail = panel_data.lead_detail(self.paths, "lead1@x", now=self.now)
        action = detail["lead"]["next_action"]
        self.assertEqual(action["kind"], "resume")
        self.assertEqual(action["label"], "Retomada (lead novo)")
        self.assertFalse(action["waiting_window"])
        self.assertTrue(action["due_utc"])

    def test_next_action_on_lead_payload_for_reactivation_step(self):
        engine = FollowupEngine(self.followups_db, **engine_options_from_profile(THERAPIFY_PROFILE))
        engine.configure_lead("lead1@x", automation_enabled=True, stage="payment", now=self.now)
        engine.note_outbound("lead1@x", message_id="bridge-1", cadence_kind="reactivation", at=self.now)
        detail = panel_data.lead_detail(self.paths, "lead1@x", now=self.now)
        action = detail["lead"]["next_action"]
        self.assertEqual(action["kind"], "reactivation")
        self.assertEqual(action["label"], "Reativação D1")

    def test_next_action_absent_when_no_open_job(self):
        detail = panel_data.lead_detail(self.paths, "lead1@x", now=self.now)
        self.assertIsNone(detail["lead"]["next_action"])


if __name__ == "__main__":
    unittest.main()
