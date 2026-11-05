"""Autoria sobrevive à rotação do log e à corrida entre ACK e echo."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))
import daily_audit
import history_store
from panel import data as panel_data

CHAT = "5511999999999@s.whatsapp.net"
AT = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


class AttributionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.db"
        self.conn = history_store.connect(str(self.path))
        history_store.ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_out_of_order_echo_never_overwrites_ack(self):
        for mid, order in [("before", ("human_device_inferred", "ai")),
                           ("after", ("ai", "human_device_inferred"))]:
            for origin in order:
                history_store.record_message_origin(self.conn, CHAT, mid, origin)
        self.conn.commit()
        self.assertEqual(self.conn.execute(
            "SELECT message_id,origin FROM message_origins ORDER BY message_id"
        ).fetchall(), [("after", "ai"), ("before", "ai")])

    def test_audit_and_panel_keep_unknown_and_inferred_distinct_from_confirmed(self):
        records = [
            {"chat_id": CHAT, "message_id": mid, "body": mid, "message_type": "text",
             "timestamp": AT.timestamp() + index, "from_me": True}
            for index, mid in enumerate(("ai", "human", "device", "old"))
        ]
        history_store.insert_records(self.conn, records)
        for mid, origin in (("ai", "ai"), ("human", "human_panel"),
                            ("device", "human_device_inferred")):
            history_store.record_message_origin(self.conn, CHAT, mid, origin)
        self.conn.commit()

        turns = daily_audit.read_day_turns(self.path, AT.date())
        audit = daily_audit.build_day_audit(AT.date(), [], turns, lambda _: None)
        self.assertEqual(audit.owner_manual, 1)
        self.assertEqual(audit.replies_author_uncertain, 2)
        rows = [dict(zip(("chat_id", "message_id", "body", "timestamp", "from_me"),
                         (CHAT, r["message_id"], r["body"], r["timestamp"], 1))) for r in records]
        panel_data._mark_conversation_owners(rows, Path(self.tmp.name) / "absent.log", [CHAT], self.path)
        self.assertEqual([r["owner"] for r in rows], ["aya", "owner", "possible_owner", "unknown"])

    def test_old_schema_without_origin_table_remains_readable(self):
        self.conn.execute("DROP TABLE message_origins")
        history_store.insert_records(self.conn, [{"chat_id": CHAT, "message_id": "old", "body": "oi",
                                                   "timestamp": AT.timestamp(), "from_me": True}])
        self.conn.commit()
        turns = daily_audit.read_day_turns(self.path, AT.date())
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].origin, "")

    def test_panel_resolves_confirmed_origin_across_contact_aliases(self):
        alias = "123456789@lid"
        history_store.record_message_origin(self.conn, CHAT, "same-id", "ai")
        history_store.record_message_origin(self.conn, alias, "same-id", "human_device_inferred")
        self.conn.commit()
        rows = [{"chat_id": alias, "message_id": "same-id", "body": "resposta",
                 "timestamp": AT.timestamp(), "from_me": True}]
        panel_data._mark_conversation_owners(rows, Path(self.tmp.name) / "absent.log", [CHAT, alias], self.path)
        self.assertEqual(rows[0]["owner"], "aya")


if __name__ == "__main__":
    unittest.main()
