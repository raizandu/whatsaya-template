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

import history_store  # noqa: E402
import reactivation_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402

OWNER_NUMBER = "5511900000000"
NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _paths(tmp_dir: Path, *, contacts_json: Path, messages_db: Path, followups_db: Path, workspace_dir: Path) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=contacts_json,
        messages_db=messages_db,
        followups_db=followups_db,
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
        workspace_dir=workspace_dir,
    )


def _write_contacts(path: Path, contacts: dict) -> None:
    path.write_text(json.dumps(contacts), encoding="utf-8")


def _write_classification(workspace_dir: Path, records: list[dict]) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "whatsapp_classification.json").write_text(
        json.dumps({"records": records}), encoding="utf-8",
    )


def _init_messages_db(path: Path) -> None:
    conn = history_store.connect(str(path))
    try:
        history_store.ensure_schema(conn)
    finally:
        conn.close()


def _insert_message(
    db_path: Path, chat_id: str, *, message_id: str, body: str, timestamp: float,
    from_me: int = 0, is_historical: int = 0,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO messages(chat_id, sender_id, sender_name, message_id, message_type, body,"
            " timestamp, from_me, is_historical, has_media, media_type)"
            " VALUES (?, ?, '', ?, 'chat', ?, ?, ?, ?, 0, NULL)",
            (chat_id, chat_id, message_id, body, timestamp, from_me, is_historical),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_followup_job(db_path: Path, chat_id: str, *, due_utc: str, status: str = "pending", step_no: int = 1) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO followup_jobs(chat_id, generation, cadence_kind, step_no, due_utc, basis_outbound_id,"
            " status, created_utc, updated_utc)"
            " VALUES (?, 0, 'silence', ?, ?, 'base-msg', ?, ?, ?)",
            (chat_id, step_no, due_utc, status, due_utc, due_utc),
        )
        conn.commit()
    finally:
        conn.close()


ACTIVE_PHONE = "5511911111111@s.whatsapp.net"
ACTIVE_LID = "111111@lid"
LEGACY_NO_MSG_PHONE = "5511922222222@s.whatsapp.net"
LEGACY_HIST_MSG_PHONE = "5511933333333@s.whatsapp.net"
BLOCKED_PHONE = "5511944444444@s.whatsapp.net"
REACT_OPTIN_PHONE = "5511955555555@s.whatsapp.net"
REACT_PENDING_PHONE = "5511966666666@s.whatsapp.net"
LID_ONLY_LEGACY = "777777@lid"
HUMAN_PHONE = "5511988888888@s.whatsapp.net"
GROUP_ID = "120363000000000000@g.us"
BROADCAST_ID = "status@broadcast"
OWNER_JID = f"{OWNER_NUMBER}@s.whatsapp.net"


class ContactsDirectoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        contacts_json = tmp_dir / "personal_contacts.json"
        messages_db = tmp_dir / "whatsapp_messages.db"
        followups_db = tmp_dir / "commercial_followups.db"
        workspace_dir = tmp_dir / "workspace"

        legacy_ts = (NOW - timedelta(days=40)).timestamp()
        _write_contacts(contacts_json, {
            ACTIVE_PHONE: {"name": "Ana Viva", "lid": ACTIVE_LID},
            ACTIVE_LID: {"name": "Ana Viva", "lid": ACTIVE_LID},
            LEGACY_NO_MSG_PHONE: {
                "name": "Legado Bea", "ai_enabled": False, "in_flow": False,
                "ai_disabled_reason": "legacy_history", "flow_origin": "legacy_fullsync",
                "legacy_last_message_at": legacy_ts,
            },
            LEGACY_HIST_MSG_PHONE: {
                "name": "Legado Caio", "ai_enabled": False, "in_flow": False,
                "ai_disabled_reason": "legacy_history", "flow_origin": "legacy_fullsync",
            },
            BLOCKED_PHONE: {"name": "Bloqueado Dan", "blocked": True, "ai_disabled_reason": "panel_block"},
            REACT_OPTIN_PHONE: {
                "name": "Reativada Eva", "ai_enabled": True, "in_flow": True,
                "flow_origin": "reactivation_optin",
            },
            REACT_PENDING_PHONE: {"name": "Pendente Fabio"},
            LID_ONLY_LEGACY: {
                "name": "Legado Gil", "ai_enabled": False, "ai_disabled_reason": "legacy_history",
                "flow_origin": "legacy_fullsync",
            },
            HUMAN_PHONE: {"name": "Humano Ivo"},
            GROUP_ID: {"name": "Grupo da Firma"},
            BROADCAST_ID: {"name": "Status"},
            OWNER_JID: {"name": "Rodrigo (dono)"},
        })

        _init_messages_db(messages_db)
        _insert_message(
            messages_db, ACTIVE_PHONE, message_id="m1", body="Quanto custa a sessão?",
            timestamp=(NOW - timedelta(hours=1)).timestamp(), from_me=0, is_historical=0,
        )
        _insert_message(
            messages_db, LEGACY_HIST_MSG_PHONE, message_id="m2", body="Conversa antiga do fullsync",
            timestamp=(NOW - timedelta(days=10)).timestamp(), from_me=0, is_historical=1,
        )

        engine = FollowupEngine(followups_db)
        engine.configure_lead(ACTIVE_PHONE, stage="qualification", automation_enabled=True)
        engine.set_estimated_value(ACTIVE_PHONE, 480000)
        _insert_followup_job(followups_db, ACTIVE_PHONE, due_utc=(NOW + timedelta(hours=2)).isoformat())
        engine.configure_lead(HUMAN_PHONE, automation_enabled=False, takeover=True)
        reactivation_store.prepare(followups_db, [REACT_PENDING_PHONE], label="remarketing", now=NOW)

        _write_classification(workspace_dir, [
            {
                "chat_id": ACTIVE_PHONE, "display_name": "Ana", "flag": "Lead",
                "relationship": "Desconhecido", "automation": "comercial", "stage": "lead_qualificado",
                "confidence": "alta", "contact_data": {}, "summary": "Perguntou sobre preço.",
                "evidence": ["\"quanto custa a sessão?\""], "next_action": "Enviar proposta",
            },
            {
                "chat_id": LID_ONLY_LEGACY, "display_name": "Gil", "flag": "Revisar",
                "relationship": "Desconhecido", "automation": "revisao", "stage": "incerto",
                "confidence": "baixa", "contact_data": {}, "summary": "Mensagem antiga ambígua.",
                "evidence": [], "next_action": "Revisar manualmente",
            },
        ])

        self.paths = _paths(
            tmp_dir, contacts_json=contacts_json, messages_db=messages_db,
            followups_db=followups_db, workspace_dir=workspace_dir,
        )
        self.result = panel_data.contacts_directory(self.paths, owner_number=OWNER_NUMBER, now=NOW)
        self.by_chat_id = {row["chat_id"]: row for row in self.result["contacts"]}

    def test_collapses_phone_and_lid_prefers_phone(self):
        matches = [row for row in self.result["contacts"] if ACTIVE_LID in row["aliases"] or row["chat_id"] == ACTIVE_PHONE]
        self.assertEqual(len(matches), 1)
        row = matches[0]
        self.assertEqual(row["chat_id"], ACTIVE_PHONE)
        self.assertEqual(set(row["aliases"]), {ACTIVE_PHONE, ACTIVE_LID})
        self.assertEqual(row["name"], "Ana Viva")

    def test_legacy_kind_and_label(self):
        row = self.by_chat_id[LEGACY_NO_MSG_PHONE]
        self.assertEqual(row["kind"], "legacy")
        self.assertTrue(row["legacy"])
        self.assertEqual(row["ai"], {"enabled": False, "reason": "legacy_history", "label": "IA desligada (legado)"})

    def test_blocked_kind(self):
        row = self.by_chat_id[BLOCKED_PHONE]
        self.assertEqual(row["kind"], "blocked")
        self.assertFalse(row["ai"]["enabled"])
        self.assertEqual(row["ai"]["label"], "Bloqueado")

    def test_reactivation_kind_via_flow_origin(self):
        row = self.by_chat_id[REACT_OPTIN_PHONE]
        self.assertEqual(row["kind"], "reactivation")
        self.assertEqual(row["ai"]["label"], "Reativação")

    def test_reactivation_kind_via_pending_manual_entry(self):
        row = self.by_chat_id[REACT_PENDING_PHONE]
        self.assertEqual(row["kind"], "reactivation")

    def test_active_card_inherits_stage_and_followup(self):
        row = self.by_chat_id[ACTIVE_PHONE]
        self.assertEqual(row["kind"], "active")
        self.assertTrue(row["automation"])
        self.assertFalse(row["human"])
        self.assertEqual(row["stage"], "qualification")
        self.assertEqual(row["stage_label"], "Qualificação")
        self.assertEqual(row["estimated_value_cents"], 480000)
        self.assertNotEqual(row["next_followup"], "")
        self.assertNotEqual(row["next_followup_rel"], "atrasado")

    def test_last_historical_true_from_actual_message(self):
        row = self.by_chat_id[LEGACY_HIST_MSG_PHONE]
        self.assertTrue(row["last_historical"])
        self.assertEqual(row["preview"], "Conversa antiga do fullsync")

    def test_contact_without_message_uses_legacy_last_message_at(self):
        row = self.by_chat_id[LEGACY_NO_MSG_PHONE]
        self.assertTrue(row["last_historical"])
        self.assertAlmostEqual(row["last_at"], (NOW - timedelta(days=40)).timestamp(), delta=1)
        self.assertNotEqual(row["last"], "")

    def test_groups_broadcast_and_owner_excluded(self):
        chat_ids = set(self.by_chat_id)
        self.assertNotIn(GROUP_ID, chat_ids)
        self.assertNotIn(BROADCAST_ID, chat_ids)
        self.assertNotIn(OWNER_JID, chat_ids)

    def test_classification_matches_by_phone_and_by_lid(self):
        active_row = self.by_chat_id[ACTIVE_PHONE]
        self.assertIsNotNone(active_row["triage"])
        self.assertEqual(active_row["triage"]["flag"], "Lead")

        lid_row = self.by_chat_id[LID_ONLY_LEGACY]
        self.assertIsNotNone(lid_row["triage"])
        self.assertEqual(lid_row["triage"]["flag"], "Revisar")
        self.assertEqual(lid_row["kind"], "legacy")

    def test_counts_and_flags(self):
        self.assertEqual(self.result["total"], 8)
        self.assertEqual(self.result["counts"], {
            "all": 8, "attention": 1, "human": 1, "aya": 1, "legacy": 3, "blocked": 1, "reactivation": 2,
        })
        self.assertEqual(self.result["flags"], {"Lead": 1, "Revisar": 1})


class SetAiAccessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        contacts_json = tmp_dir / "personal_contacts.json"
        _write_contacts(contacts_json, {
            ACTIVE_PHONE: {
                "name": "Ana", "ai_enabled": False, "in_flow": False,
                "ai_disabled_reason": "legacy_history", "flow_origin": "legacy_fullsync", "lid": ACTIVE_LID,
            },
            ACTIVE_LID: {"name": "Ana", "ai_enabled": False, "ai_disabled_reason": "legacy_history", "lid": ACTIVE_LID},
            BLOCKED_PHONE: {"name": "Dan", "blocked": True},
            "5511977777777@s.whatsapp.net": {"name": "Hugo", "manual_relationship": "Namorada"},
            "5511900000001@s.whatsapp.net": {
                "name": "Rui", "ai_enabled": True, "in_flow": True, "lid": "999999@lid",
            },
            "999999@lid": {"name": "Rui"},
        })
        self.paths = _paths(
            tmp_dir, contacts_json=contacts_json, messages_db=tmp_dir / "missing_messages.db",
            followups_db=tmp_dir / "commercial_followups.db", workspace_dir=tmp_dir / "workspace",
        )

    def _contacts(self) -> dict:
        return json.loads(self.paths.contacts_json.read_text(encoding="utf-8"))

    def test_enable_turns_ai_on_across_mirrors(self):
        result = panel_actions.set_ai_access(self.paths, chat_id=ACTIVE_PHONE, enabled=True)
        self.assertTrue(result["enabled"])
        self.assertEqual(set(result["keys"]), {ACTIVE_PHONE, ACTIVE_LID})
        self.assertEqual(result["ai"]["label"], "AYA atendendo")
        contacts = self._contacts()
        for key in (ACTIVE_PHONE, ACTIVE_LID):
            self.assertTrue(contacts[key]["ai_enabled"], key)
            self.assertTrue(contacts[key]["in_flow"], key)
            self.assertNotIn("ai_disabled_reason", contacts[key])
            self.assertEqual(contacts[key]["flow_origin"], "owner_optin")
            self.assertEqual(contacts[key]["ai_policy_version"], 2)
            self.assertIn("commercial_scope_confirmed_at", contacts[key])

    def test_disable_turns_ai_off_across_mirrors(self):
        result = panel_actions.set_ai_access(self.paths, chat_id="5511900000001@s.whatsapp.net", enabled=False)
        self.assertFalse(result["enabled"])
        contacts = self._contacts()
        for key in ("5511900000001@s.whatsapp.net", "999999@lid"):
            self.assertFalse(contacts[key]["ai_enabled"], key)
            self.assertFalse(contacts[key]["in_flow"], key)
            self.assertEqual(contacts[key]["ai_disabled_reason"], "owner_optout")
            self.assertEqual(contacts[key]["flow_origin"], "owner_optout")

    def test_blocked_contact_refused(self):
        with self.assertRaises(panel_actions.ActionError) as ctx:
            panel_actions.set_ai_access(self.paths, chat_id=BLOCKED_PHONE, enabled=True)
        self.assertIn("Desbloqueie primeiro", str(ctx.exception))

    def test_personal_relationship_refused(self):
        with self.assertRaises(panel_actions.ActionError) as ctx:
            panel_actions.set_ai_access(self.paths, chat_id="5511977777777@s.whatsapp.net", enabled=True)
        self.assertIn("Contato pessoal", str(ctx.exception))

    def test_missing_chat_id_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, chat_id="", enabled=True)

    def test_non_bool_enabled_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, chat_id=ACTIVE_PHONE, enabled="yes")


class LeadDetailHistoryAndTriageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_dir = Path(self._tmp.name)
        contacts_json = tmp_dir / "personal_contacts.json"
        messages_db = tmp_dir / "whatsapp_messages.db"
        followups_db = tmp_dir / "commercial_followups.db"
        workspace_dir = tmp_dir / "workspace"

        _write_contacts(contacts_json, {
            LEGACY_HIST_MSG_PHONE: {
                "name": "Legado Caio", "ai_enabled": False, "in_flow": False,
                "ai_disabled_reason": "legacy_history", "flow_origin": "legacy_fullsync",
            },
        })
        _init_messages_db(messages_db)
        _insert_message(
            messages_db, LEGACY_HIST_MSG_PHONE, message_id="h1", body="Mensagem importada do fullsync",
            timestamp=(NOW - timedelta(days=90)).timestamp(), from_me=0, is_historical=1,
        )
        _insert_message(
            messages_db, LEGACY_HIST_MSG_PHONE, message_id="l1", body="Mensagem viva recente",
            timestamp=(NOW - timedelta(minutes=5)).timestamp(), from_me=0, is_historical=0,
        )
        _write_classification(workspace_dir, [
            {
                "chat_id": LEGACY_HIST_MSG_PHONE, "display_name": "Caio", "flag": "Cliente",
                "relationship": "Desconhecido", "automation": "comercial", "stage": "cliente",
                "confidence": "media", "contact_data": {}, "summary": "Já comprou antes.",
                "evidence": ["\"comprei o pacote em março\""], "next_action": "Oferecer upsell",
            },
        ])
        self.paths = _paths(
            tmp_dir, contacts_json=contacts_json, messages_db=messages_db,
            followups_db=followups_db, workspace_dir=workspace_dir,
        )
        FollowupEngine(followups_db)  # só cria o schema; sem lead pra este contato
        self.detail = panel_data.lead_detail(self.paths, LEGACY_HIST_MSG_PHONE, now=NOW)

    def test_timeline_includes_both_historical_and_live_messages(self):
        message_items = [item for item in self.detail["timeline"] if item["type"] == "message"]
        historical_flags = [item["historical"] for item in message_items]
        self.assertIn(True, historical_flags)
        self.assertIn(False, historical_flags)
        bodies = [bubble["body"] for item in message_items for bubble in item["bubbles"]]
        self.assertIn("Mensagem importada do fullsync", bodies)
        self.assertIn("Mensagem viva recente", bodies)

    def test_historical_item_comes_before_live_item(self):
        message_items = [item for item in self.detail["timeline"] if item["type"] == "message"]
        first_historical_index = next(i for i, item in enumerate(message_items) if item["historical"])
        first_live_index = next(i for i, item in enumerate(message_items) if not item["historical"])
        self.assertLess(first_historical_index, first_live_index)

    def test_legacy_and_ai_fields_present(self):
        self.assertTrue(self.detail["legacy"])
        self.assertEqual(self.detail["ai"], {"enabled": False, "reason": "legacy_history", "label": "IA desligada (legado)"})

    def test_triage_field_matches_classification(self):
        self.assertIsNotNone(self.detail["triage"])
        self.assertEqual(self.detail["triage"]["flag"], "Cliente")
        self.assertEqual(self.detail["triage"]["evidence"], ["\"comprei o pacote em março\""])


if __name__ == "__main__":
    unittest.main()
