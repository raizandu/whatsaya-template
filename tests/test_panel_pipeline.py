from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
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

from commercial_followups import FollowupEngine  # noqa: E402
from therapify_preset import THERAPIFY_PIPELINE  # noqa: E402


def _create_therapify_tables(db_path: Path) -> None:
    """Mesmo schema de `tools/therapify_migrate.py:_ensure_followup_schema`, só as
    tabelas importadas do Therapify (o resto já vem do `FollowupEngine`)."""
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


if __name__ == "__main__":
    unittest.main()
