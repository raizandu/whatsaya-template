from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
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


CHAT = "5511999999999@s.whatsapp.net"


class IncomingAudioHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / "whatsapp_messages.db"
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    body TEXT,
                    timestamp REAL,
                    from_me INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                "INSERT INTO messages(chat_id,message_id,body,timestamp,from_me) "
                "VALUES (?,?,?,?,0)",
                (CHAT, "audio-1", "", 1000.0),
            )
        self.enterContext(mock.patch.object(wm, "_MSG_DB_PATH", self.db_path))
        with wm._pending_inbound_lock:
            wm._pending_inbound.clear()
            wm._pending_inbound_queue.clear()

    def test_native_stt_transcript_is_persisted_by_original_message_id(self):
        wm._track_inbound(CHAT, "audio-1", "", is_voice=True)

        turn_key = wm._register_contact_turn(
            CHAT,
            CHAT,
            "estou com muita ansiedade",
        )

        self.assertTrue(turn_key)
        with sqlite3.connect(self.db_path) as connection:
            body = connection.execute(
                "SELECT body FROM messages WHERE message_id='audio-1'"
            ).fetchone()[0]
        self.assertEqual(body, "estou com muita ansiedade")


if __name__ == "__main__":
    unittest.main()
