from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "reactivation_store.py"
SPEC = importlib.util.spec_from_file_location("reactivation_store", MODULE_PATH)
assert SPEC and SPEC.loader
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


def _t(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset_seconds)


class ReactivationStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "commercial_followups.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_ensure_schema_is_idempotent(self):
        store.ensure_schema(self.db_path)
        store.ensure_schema(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='manual_reactivation'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)

    def test_prepare_is_idempotent_and_reports_totals(self):
        result = store.prepare(
            self.db_path,
            ["5511999990001", "5511999990002@s.whatsapp.net"],
            label="remarketing",
            now=_t(),
        )
        self.assertEqual(result, {"added": 2, "rearmed": 0, "total": 2})

        # mesma chave duas vezes na mesma chamada (uma como dígitos, outra como
        # JID completo) dedupa pra uma; chat já preparado -> rearm, não added.
        result2 = store.prepare(
            self.db_path,
            ["5511999990001@s.whatsapp.net", "5511999990001"],
            label="remarketing",
            now=_t(10),
        )
        self.assertEqual(result2, {"added": 0, "rearmed": 1, "total": 1})

    def test_prepare_rearms_only_when_not_sent(self):
        store.prepare(self.db_path, ["5511999990001"], label="remarketing", now=_t())
        store.mark_sent(self.db_path, "5511999990001", sent=True, now=_t(10))
        entry_before = store.get_entry(self.db_path, "5511999990001")

        result = store.prepare(self.db_path, ["5511999990001"], label="remarketing", now=_t(20))
        self.assertEqual(result, {"added": 0, "rearmed": 0, "total": 1})

        entry_after = store.get_entry(self.db_path, "5511999990001")
        self.assertEqual(entry_after["prepared_utc"], entry_before["prepared_utc"])
        self.assertEqual(entry_after["sent_utc"], entry_before["sent_utc"])
        self.assertEqual(entry_after["first_manual_pending"], 0)

    def test_list_entries_orders_and_splits_pending_and_sent(self):
        store.prepare(self.db_path, ["5511900000001"], label="remarketing", now=_t(0))
        store.prepare(self.db_path, ["5511900000002"], label="remarketing", now=_t(10))
        store.prepare(self.db_path, ["5511900000003"], label="remarketing", now=_t(20))
        store.mark_sent(self.db_path, "5511900000001", sent=True, now=_t(30))
        store.mark_sent(self.db_path, "5511900000003", sent=True, now=_t(40))

        entries = store.list_entries(self.db_path)
        self.assertEqual(
            [e["chat_id"] for e in entries["pending"]], ["5511900000002@s.whatsapp.net"]
        )
        self.assertEqual(
            [e["chat_id"] for e in entries["sent"]],
            ["5511900000003@s.whatsapp.net", "5511900000001@s.whatsapp.net"],
        )

    def test_set_message_strips_caps_length_and_raises_for_unknown_chat(self):
        store.prepare(self.db_path, ["5511900000001"], label="remarketing", now=_t())
        long_text = "x" * 2000
        result = store.set_message(
            self.db_path, "5511900000001", f"  {long_text}  ", variant=2, now=_t(5)
        )
        self.assertEqual(len(result["message"]), 1000)
        self.assertEqual(result["message_variant"], 2)

        cleared = store.set_message(self.db_path, "5511900000001", "   ", now=_t(6))
        self.assertEqual(cleared["message"], "")
        # sem variant explícito, a variante escolhida antes é preservada.
        self.assertEqual(cleared["message_variant"], 2)

        with self.assertRaises(KeyError):
            store.set_message(self.db_path, "5511900099999", "oi", now=_t(7))

    def test_mark_sent_toggle_clears_and_rearms_first_manual_pending(self):
        store.prepare(self.db_path, ["5511900000001"], label="remarketing", now=_t())
        sent = store.mark_sent(self.db_path, "5511900000001", sent=True, now=_t(5))
        self.assertIsNotNone(sent["sent_utc"])
        self.assertEqual(sent["first_manual_pending"], 0)

        unsent = store.mark_sent(self.db_path, "5511900000001", sent=False, now=_t(10))
        self.assertIsNone(unsent["sent_utc"])
        self.assertEqual(unsent["first_manual_pending"], 1)

    def test_consume_first_manual_is_one_shot_across_aliases(self):
        store.prepare(self.db_path, ["5511900000001"], label="remarketing", now=_t())
        aliases = ["123abc@lid", "5511900000001@s.whatsapp.net"]

        consumed = store.consume_first_manual(self.db_path, aliases, now=_t(5))
        self.assertEqual(consumed, "5511900000001@s.whatsapp.net")

        entry = store.get_entry(self.db_path, "5511900000001")
        self.assertEqual(entry["first_manual_pending"], 0)
        self.assertIsNotNone(entry["sent_utc"])
        self.assertIsNotNone(entry["first_manual_consumed_utc"])

        second = store.consume_first_manual(self.db_path, aliases, now=_t(10))
        self.assertIsNone(second)

    def test_consume_first_manual_tolerates_missing_table(self):
        missing_db = Path(self._tmp.name) / "no_table.db"
        result = store.consume_first_manual(missing_db, ["5511900000001@s.whatsapp.net"])
        self.assertIsNone(result)

    def test_first_manual_pending_reads_across_aliases(self):
        store.prepare(self.db_path, ["5511900000001"], label="remarketing", now=_t())
        self.assertTrue(
            store.first_manual_pending(
                self.db_path, ["999@lid", "5511900000001@s.whatsapp.net"]
            )
        )
        store.consume_first_manual(self.db_path, ["5511900000001@s.whatsapp.net"], now=_t(5))
        self.assertFalse(
            store.first_manual_pending(self.db_path, "5511900000001@s.whatsapp.net")
        )

    def test_suggest_message_is_stable_and_cycles_through_variants_without_leftovers(self):
        chat_id = "5511900000001@s.whatsapp.net"
        first = store.suggest_message(chat_id, "Maria", 0)
        again = store.suggest_message(chat_id, "Maria", 0)
        self.assertEqual(first, again)

        texts = [store.suggest_message(chat_id, "Maria", v) for v in range(store.SUGGESTION_VARIANTS)]
        self.assertEqual(len(set(texts)), store.SUGGESTION_VARIANTS)
        for text in texts:
            self.assertNotIn("{nome}", text)
            self.assertIn("Maria", text)

    def test_suggest_message_empty_name_is_graceful(self):
        text = store.suggest_message("5511900000002@s.whatsapp.net", "", 0)
        self.assertNotIn("{nome}", text)
        self.assertNotIn("  ", text)
        self.assertNotIn(" ,", text)
        self.assertTrue(text.startswith("Oi"))

    def test_prepare_rejects_lid_chat_ids(self):
        with self.assertRaises(ValueError):
            store.prepare(self.db_path, ["123456@lid"], label="remarketing", now=_t())


if __name__ == "__main__":
    unittest.main()
