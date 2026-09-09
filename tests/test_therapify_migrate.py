from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "therapify_migrate.py"
SPEC = importlib.util.spec_from_file_location("therapify_migrate", MODULE_PATH)
assert SPEC and SPEC.loader
migrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrator)


SCHEMA = """
CREATE TABLE leads (
    phone TEXT PRIMARY KEY,
    profile_name TEXT,
    full_name TEXT,
    gender TEXT,
    status TEXT NOT NULL,
    is_existing_patient INTEGER NOT NULL DEFAULT 0,
    paused INTEGER NOT NULL DEFAULT 0,
    last_phase TEXT,
    last_inbound_at TEXT,
    last_outbound_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    wamid TEXT UNIQUE,
    phone TEXT NOT NULL,
    direction TEXT NOT NULL,
    role TEXT NOT NULL,
    body TEXT NOT NULL,
    context_wamid TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE appointments (
    id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    slot_start TEXT NOT NULL,
    slot_end TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE purchases (
    id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    product TEXT NOT NULL,
    amount REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE escalations (
    id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    reason TEXT NOT NULL,
    resolved INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE reactivation_progress (
    phone TEXT PRIMARY KEY,
    stage INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class TherapifyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="whatsaya-fixture-")
        self.root = Path(self.tempdir.name)
        self.source = self.root / "therapify.db"
        connection = sqlite3.connect(self.source)
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO leads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "0000000",
                "Fixture Lead",
                "Fixture Lead Full",
                "F",
                "in_funnel",
                0,
                0,
                "phase-2",
                "2026-01-02T10:00:00Z",
                "2026-01-02T10:01:00Z",
                "2026-01-02T09:00:00Z",
                "2026-01-02T10:01:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "fixture-in", "0000000", "in", "user", "fixture inbound", None, "2026-01-02T10:00:00Z"),
        )
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, "fixture-out", "0000000", "out", "assistant", "fixture outbound", "fixture-in", "2026-01-02T10:01:00Z"),
        )
        connection.execute(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (3, "0000000", "2026-01-03T12:00:00Z", "2026-01-03T12:30:00Z", "session", "pending_manual", "2026-01-02T10:02:00Z"),
        )
        connection.execute(
            "INSERT INTO purchases VALUES (?, ?, ?, ?, ?)",
            (4, "0000000", "metodo_gravado", 47.0, "2026-01-03T12:30:00Z"),
        )
        connection.execute(
            "INSERT INTO escalations VALUES (?, ?, ?, ?, ?)",
            (5, "0000000", "fixture escalation", 0, "2026-01-02T10:03:00Z"),
        )
        connection.execute("INSERT INTO app_settings VALUES (?, ?)", ("global_pause", "1"))
        connection.execute("INSERT INTO app_settings VALUES (?, ?)", ("google_refresh_token", "fixture-secret"))
        connection.execute(
            "INSERT INTO reactivation_progress VALUES (?, ?, ?)",
            ("0000000", 2, "2026-01-03T12:31:00Z"),
        )
        connection.commit()
        connection.close()
        self.data = self.root / "data"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_dry_run_has_no_target_side_effects_or_raw_content(self) -> None:
        report = migrator.run_migration(source_db=self.source, data_dir=self.data, dry_run=True)
        self.assertEqual(report["status"], "dry-run")
        self.assertFalse(self.data.exists())
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("fixture inbound", serialized)
        self.assertNotIn("0000000", serialized)

    def test_migration_is_idempotent_and_preserves_operational_fields(self) -> None:
        self.data.mkdir()
        contacts = self.data / "personal_contacts.json"
        contacts.write_text(
            json.dumps(
                {
                    "0000000@s.whatsapp.net": {
                        "blocked": True,
                        "manual_relationship": "fixture",
                        "ai_enabled": False,
                    }
                }
            ),
            encoding="utf-8",
        )
        first = migrator.run_migration(source_db=self.source, data_dir=self.data)
        second = migrator.run_migration(source_db=self.source, data_dir=self.data)
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertEqual(second["migrated"]["messages_inserted"], 0)
        self.assertEqual(second["migrated"]["sales_inserted"], 0)
        saved_contacts = json.loads(contacts.read_text(encoding="utf-8"))
        saved = saved_contacts["0000000@s.whatsapp.net"]
        self.assertTrue(saved["blocked"])
        self.assertEqual(saved["manual_relationship"], "fixture")
        self.assertEqual(saved["reactivation_stage"], 2)
        self.assertFalse(saved["ai_enabled"])
        messages = sqlite3.connect(self.data / ".hermes" / "whatsapp_messages.db")
        self.assertEqual(messages.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)
        self.assertEqual(messages.execute("SELECT context_wamid FROM messages WHERE message_id='fixture-out'").fetchone()[0], "fixture-in")
        messages.close()
        followups = sqlite3.connect(self.data / ".hermes" / "commercial_followups.db")
        self.assertEqual(followups.execute("SELECT COUNT(*) FROM appointments").fetchone()[0], 1)
        self.assertEqual(followups.execute("SELECT COUNT(*) FROM purchases").fetchone()[0], 1)
        self.assertEqual(followups.execute("SELECT COUNT(*) FROM escalations").fetchone()[0], 1)
        self.assertEqual(followups.execute("SELECT COUNT(*) FROM reactivation_progress").fetchone()[0], 1)
        self.assertEqual(followups.execute("SELECT value, redacted FROM app_settings WHERE key='google_refresh_token'").fetchone(), ("[REDACTED]", 1))
        self.assertEqual(followups.execute("SELECT automation_enabled FROM lead_state").fetchone()[0], 0)
        followups.close()
        sales = json.loads((self.data / "sales.json").read_text(encoding="utf-8"))
        self.assertEqual(len(sales), 1)

    def test_wal_source_is_snapshotted_consistently(self) -> None:
        connection = sqlite3.connect(self.source)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE leads SET last_phase='wal-phase'")
        connection.commit()
        report = migrator.run_migration(source_db=self.source, data_dir=self.data)
        self.assertEqual(report["status"], "success")
        connection.close()
        followups = sqlite3.connect(self.data / ".hermes" / "commercial_followups.db")
        self.assertEqual(followups.execute("SELECT last_phase FROM therapify_leads").fetchone()[0], "wal-phase")
        followups.close()

    def test_explicit_activation_only_releases_pending_migration(self) -> None:
        migrator.run_migration(source_db=self.source, data_dir=self.data)
        migrator.run_migration(source_db=self.source, data_dir=self.data, enable_automation=True)
        contacts = json.loads((self.data / "personal_contacts.json").read_text(encoding="utf-8"))
        self.assertTrue(contacts["0000000@s.whatsapp.net"]["ai_enabled"])
        followups = sqlite3.connect(self.data / ".hermes" / "commercial_followups.db")
        self.assertEqual(followups.execute("SELECT automation_enabled FROM lead_state").fetchone()[0], 1)
        followups.close()

    def test_missing_table_fails_closed(self) -> None:
        broken = self.root / "broken.db"
        connection = sqlite3.connect(broken)
        connection.execute("CREATE TABLE leads(phone TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaises(migrator.MigrationError):
            migrator.run_migration(source_db=broken, data_dir=self.data)
        self.assertFalse(self.data.exists())

    def test_transaction_failure_restores_existing_stores_and_removes_sidecars(self) -> None:
        migrator.run_migration(source_db=self.source, data_dir=self.data)
        messages_path = self.data / ".hermes" / "whatsapp_messages.db"
        followups_path = self.data / ".hermes" / "commercial_followups.db"

        def logical_dump(path: Path) -> list[str]:
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                return list(connection.iterdump())

        messages_before = logical_dump(messages_path)
        followups_before = logical_dump(followups_path)

        original_ensure = migrator._ensure_followup_schema

        def fail_after_schema(connection: sqlite3.Connection) -> None:
            original_ensure(connection)
            raise sqlite3.OperationalError("synthetic transaction failure")

        with mock.patch.object(migrator, "_ensure_followup_schema", side_effect=fail_after_schema):
            with self.assertRaisesRegex(migrator.MigrationError, "stores restaurados"):
                migrator.run_migration(source_db=self.source, data_dir=self.data)

        self.assertFalse(messages_path.with_name(messages_path.name + "-wal").exists())
        self.assertFalse(messages_path.with_name(messages_path.name + "-shm").exists())
        self.assertFalse(followups_path.with_name(followups_path.name + "-wal").exists())
        self.assertFalse(followups_path.with_name(followups_path.name + "-shm").exists())
        self.assertEqual(logical_dump(messages_path), messages_before)
        self.assertEqual(logical_dump(followups_path), followups_before)


if __name__ == "__main__":
    unittest.main()
