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

import reactivation_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402

OWNER_NUMBER = "5511900000000"


class FakeBridge:
    """Só o pedaço de `BridgeClient` que as ações de reativação usam."""

    def __init__(self, status: int | None, payload: dict | None):
        self.status = status
        self.payload = payload
        self.calls: list[str] = []

    def get_json_status(self, path: str):
        self.calls.append(path)
        return self.status, self.payload


def _paths(tmp_dir: Path) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=tmp_dir / "personal_contacts.json",
        messages_db=missing / "messages.db",
        followups_db=tmp_dir / "commercial_followups.db",
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
    )


def _write_contacts(path: Path, contacts: dict) -> None:
    path.write_text(json.dumps(contacts), encoding="utf-8")


def _labels_payload(chats: list[dict]) -> dict:
    return {"success": True, "label": {"id": "1", "name": "remarketing"}, "chats": chats}


class ReactivationPrepareTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.paths = _paths(self.tmp_dir)
        _write_contacts(self.paths.contacts_json, {
            "5511944444444@s.whatsapp.net": {"name": "Dan", "blocked": True},
        })
        self.chats = [
            {"chatId": "5511911111111@s.whatsapp.net", "canonicalChatId": "5511911111111@s.whatsapp.net",
             "isLid": False, "name": "Ana"},
            {"chatId": "222222@lid", "canonicalChatId": "5511922222222@s.whatsapp.net",
             "isLid": True, "name": "Bea"},
            {"chatId": "333333@lid", "canonicalChatId": "333333@lid", "isLid": True, "name": "Cae"},
            {"chatId": "5511944444444@s.whatsapp.net", "canonicalChatId": "5511944444444@s.whatsapp.net",
             "isLid": False, "name": "Dan"},
            {"chatId": f"{OWNER_NUMBER}@s.whatsapp.net", "canonicalChatId": f"{OWNER_NUMBER}@s.whatsapp.net",
             "isLid": False, "name": "Rodrigo"},
        ]

    def test_prepare_counts_mix_of_pn_lid_blocked_and_owner(self):
        bridge = FakeBridge(200, _labels_payload(self.chats))
        result = panel_actions.reactivation_prepare(
            self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER,
        )
        self.assertEqual(result, {
            "label": "remarketing", "found": 5, "added": 2, "rearmed": 0,
            "skipped_lid": 1, "skipped_blocked": 1, "reenabled": 0, "total": 2,
        })
        entries = reactivation_store.list_entries(self.paths.followups_db)
        self.assertEqual(len(entries["pending"]), 2)
        chat_ids = {row["chat_id"] for row in entries["pending"]}
        self.assertEqual(chat_ids, {"5511911111111@s.whatsapp.net", "5511922222222@s.whatsapp.net"})
        self.assertEqual(bridge.calls, ["/labels/chats?name=remarketing"])

    def test_prepare_reenables_legacy_ai_off_contacts_only(self):
        _write_contacts(self.paths.contacts_json, {
            "5511911111111@s.whatsapp.net": {"name": "Ana", "ai_enabled": False, "in_flow": False,
                                             "ai_disabled_reason": "legacy_history", "flow_origin": "legacy_fullsync",
                                             "lid": "111111@lid"},
            "111111@lid": {"name": "Ana", "ai_enabled": False, "ai_disabled_reason": "legacy_history", "lid": "111111@lid"},
            # Bea só existe pelo LID que o bridge devolve como chatId bruto.
            "222222@lid": {"name": "Bea", "ai_enabled": False, "ai_disabled_reason": "legacy_history", "lid": "222222@lid"},
            "5511944444444@s.whatsapp.net": {"name": "Dan", "blocked": True},
        })
        bridge = FakeBridge(200, _labels_payload(self.chats))
        result = panel_actions.reactivation_prepare(
            self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER,
        )
        self.assertEqual(result["reenabled"], 2)
        contacts = json.loads(self.paths.contacts_json.read_text(encoding="utf-8"))
        for key in ("5511911111111@s.whatsapp.net", "111111@lid"):
            self.assertTrue(contacts[key]["ai_enabled"], key)
            self.assertTrue(contacts[key]["in_flow"], key)
            self.assertNotIn("ai_disabled_reason", contacts[key])
            self.assertEqual(contacts[key]["flow_origin"], "reactivation_optin")
        self.assertTrue(contacts["222222@lid"]["ai_enabled"])
        self.assertNotIn("ai_disabled_reason", contacts["222222@lid"])
        self.assertTrue(contacts["5511944444444@s.whatsapp.net"]["blocked"])

    def test_prepare_is_idempotent_second_call_only_rearms(self):
        bridge = FakeBridge(200, _labels_payload(self.chats))
        panel_actions.reactivation_prepare(self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER)
        result = panel_actions.reactivation_prepare(self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER)
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["rearmed"], 2)
        self.assertEqual(result["total"], 2)

    def test_prepare_label_not_found_raises_action_error(self):
        bridge = FakeBridge(404, {"error": "label_not_found", "labels": ["outra-etiqueta"]})
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_prepare(self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER)

    def test_prepare_bridge_unreachable_raises_action_error(self):
        bridge = FakeBridge(None, None)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_prepare(self.paths, bridge, label="remarketing", owner_number=OWNER_NUMBER)

    def test_prepare_empty_label_raises_action_error(self):
        bridge = FakeBridge(200, _labels_payload([]))
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_prepare(self.paths, bridge, label="   ", owner_number=OWNER_NUMBER)
        self.assertEqual(bridge.calls, [])


class ReactivationSuggestMessageSentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.paths = _paths(self.tmp_dir)
        _write_contacts(self.paths.contacts_json, {
            "5511911111111@s.whatsapp.net": {"name": "Ana Souza"},
        })
        reactivation_store.ensure_schema(self.paths.followups_db)
        reactivation_store.prepare(
            self.paths.followups_db, ["5511911111111@s.whatsapp.net"], label="remarketing",
        )
        self.chat_id = "5511911111111@s.whatsapp.net"

    def test_suggest_unknown_chat_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_suggest(self.paths, chat_id="5511999999999@s.whatsapp.net")

    def test_suggest_twice_changes_text_and_variant(self):
        first = panel_actions.reactivation_suggest(self.paths, chat_id=self.chat_id)
        self.assertEqual(first["message_variant"], 0)
        self.assertIn("Ana", first["message"])
        second = panel_actions.reactivation_suggest(self.paths, chat_id=self.chat_id)
        self.assertEqual(second["message_variant"], 1)
        self.assertNotEqual(first["message"], second["message"])

    def test_message_save_persists_edited_text(self):
        result = panel_actions.reactivation_message(
            self.paths, chat_id=self.chat_id, message="  Oi, tudo bem?  ",
        )
        self.assertEqual(result["message"], "Oi, tudo bem?")
        entry = reactivation_store.get_entry(self.paths.followups_db, self.chat_id)
        self.assertEqual(entry["message"], "Oi, tudo bem?")

    def test_message_unknown_chat_raises(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_message(
                self.paths, chat_id="5511999999999@s.whatsapp.net", message="oi",
            )

    def test_sent_toggle_sets_and_clears_sent_utc(self):
        marked = panel_actions.reactivation_sent(self.paths, chat_id=self.chat_id, sent=True)
        self.assertIsNotNone(marked["sent_utc"])
        entry = reactivation_store.get_entry(self.paths.followups_db, self.chat_id)
        self.assertFalse(entry["first_manual_pending"])

        unmarked = panel_actions.reactivation_sent(self.paths, chat_id=self.chat_id, sent=False)
        self.assertIsNone(unmarked["sent_utc"])
        entry = reactivation_store.get_entry(self.paths.followups_db, self.chat_id)
        self.assertTrue(entry["first_manual_pending"])

    def test_sent_requires_boolean(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reactivation_sent(self.paths, chat_id=self.chat_id, sent="yes")


class ReactivationReadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.paths = _paths(self.tmp_dir)
        _write_contacts(self.paths.contacts_json, {
            "5511911111111@s.whatsapp.net": {"name": "Ana Souza"},
            "5511922222222@s.whatsapp.net": {"name": "Bea Lima"},
            "5511933333333@s.whatsapp.net": {"name": "Caio Reis"},
        })
        engine = FollowupEngine(self.paths.followups_db)
        now = datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc)
        engine.configure_lead("5511911111111@s.whatsapp.net", stage="qualification")
        engine.configure_lead("5511922222222@s.whatsapp.net", stage="new", takeover=True)
        engine.configure_lead("5511933333333@s.whatsapp.net", stage="new")

        def _touch(chat_id: str, when: datetime) -> None:
            conn = sqlite3.connect(str(self.paths.followups_db))
            try:
                conn.execute(
                    "UPDATE lead_state SET last_inbound_utc=? WHERE chat_id=?",
                    (when.isoformat(), chat_id),
                )
                conn.commit()
            finally:
                conn.close()

        _touch("5511922222222@s.whatsapp.net", now - timedelta(days=2))

        reactivation_store.ensure_schema(self.paths.followups_db)
        reactivation_store.prepare(
            self.paths.followups_db, ["5511911111111@s.whatsapp.net"], label="remarketing",
            now=now - timedelta(hours=2),
        )
        reactivation_store.prepare(
            self.paths.followups_db, ["5511922222222@s.whatsapp.net"], label="remarketing",
            now=now - timedelta(hours=1),
        )
        reactivation_store.prepare(
            self.paths.followups_db, ["5511933333333@s.whatsapp.net"], label="remarketing",
            now=now,
        )
        reactivation_store.mark_sent(
            self.paths.followups_db, "5511933333333@s.whatsapp.net", sent=True, now=now - timedelta(days=1),
        )
        reactivation_store.mark_sent(
            self.paths.followups_db, "5511911111111@s.whatsapp.net", sent=True, now=now,
        )
        self.now = now

    def test_split_ordering_stage_label_and_takeover(self):
        result = panel_data.reactivation(
            self.paths, label="remarketing", now=self.now, pipeline_id="therapify",
        )
        self.assertEqual(result["label"], "remarketing")
        self.assertEqual(result["counts"], {"pending": 1, "sent": 2})

        pending = result["pending"]
        self.assertEqual(len(pending), 1)
        item = pending[0]
        self.assertEqual(item["chat_id"], "5511922222222@s.whatsapp.net")
        self.assertEqual(item["name"], "Bea Lima")
        self.assertEqual(item["stage_label"], "Novo")
        self.assertTrue(item["takeover"])
        self.assertEqual(item["last_inbound"], "há 2 dias")

        sent = result["sent"]
        self.assertEqual(len(sent), 2)
        # sent DESC: o marcado por último (911...) vem primeiro.
        self.assertEqual(sent[0]["chat_id"], "5511911111111@s.whatsapp.net")
        self.assertEqual(sent[0]["stage_label"], "No funil")
        self.assertEqual(sent[1]["chat_id"], "5511933333333@s.whatsapp.net")

    def test_default_pipeline_falls_back_to_stage_label_novo(self):
        result = panel_data.reactivation(self.paths, label="remarketing", now=self.now, pipeline_id="default")
        pending_item = result["pending"][0]
        self.assertEqual(pending_item["stage_label"], "Novo")


if __name__ == "__main__":
    unittest.main()
