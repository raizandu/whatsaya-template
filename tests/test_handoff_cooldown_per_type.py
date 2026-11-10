"""Cooldown de cards ao dono: deduplica repetição do mesmo tipo, não engole tipos diferentes."""
from __future__ import annotations

import importlib.util
import os
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


CHAT = "556281409936@s.whatsapp.net"
OTHER_CHAT = "556281401111@s.whatsapp.net"


class HandoffCooldownPerTypeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        wm._handoff_outbox.clear()
        wm._handoff_outbox_loaded_from = ""
        wm._handoff_sent_at.clear()
        self.addCleanup(wm._handoff_outbox.clear)
        self.addCleanup(wm._handoff_sent_at.clear)
        self.addCleanup(setattr, wm, "_handoff_outbox_loaded_from", "")
        self.enterContext(mock.patch.object(wm, "_HANDOFF_OUTBOX_PATH", Path(temp.name) / "outbox.json"))
        self.enterContext(mock.patch.object(
            type(wm.config), "whatsapp_owner_number",
            new_callable=mock.PropertyMock, return_value="5511888880000",
        ))
        self.enterContext(mock.patch.object(wm, "_load_personal_contacts", return_value={}))
        self.send = self.enterContext(mock.patch.object(wm, "_human_send", return_value="m1"))

    def _deliver(self, event_id, reason, chat_id=CHAT):
        self.assertTrue(wm._enqueue_handoff_notification(chat_id, reason, "resumo", event_id=event_id))
        wm._drain_handoff_outbox_once(chat_id)
        self.assertNotIn(event_id, wm._handoff_outbox)

    def test_alert_of_another_type_is_not_swallowed_by_recent_handoff(self):
        for first, second in (
            (CHAT, "death-talk:x"),
            ("handoff:h", "crisis:x"),
            ("handoff:h", "alarm:x"),  # caso real 09/11 final 9936
            ("handoff:h", "booking:x"),
            ("scope-pending:" + CHAT, "crisis:x"),
            ("death-talk:x", "handoff:h"),  # card do modelo no mesmo turno do URGENTE
            ("crisis:x", "handoff:h"),
        ):
            with self.subTest(first=first, second=second):
                wm._handoff_sent_at.clear()
                self.send.reset_mock()
                self._deliver(first, "primeiro")
                self._deliver(second, "segundo")
                self.assertEqual(self.send.call_count, 2)

    def test_same_type_repeat_within_cooldown_is_deduplicated_without_retry(self):
        for first, second in (
            (CHAT, "handoff:h"),
            ("handoff:h", "handoff-partial:p"),
            ("handoff:h", "therapify-escalation-3"),
            ("alarm:a", "alarm:b"),
            ("death-talk:a", "death-talk:b"),
            ("crisis:a", "crisis:b"),
        ):
            with self.subTest(first=first, second=second):
                wm._handoff_sent_at.clear()
                self.send.reset_mock()
                self._deliver(first, "primeiro")
                self._deliver(second, "segundo")
                self.assertEqual(self.send.call_count, 1)
                self.assertEqual(wm._handoff_outbox, {})

    def test_cooldown_stays_per_chat(self):
        self._deliver("handoff:a", "primeiro", CHAT)
        self._deliver("handoff:b", "segundo", OTHER_CHAT)
        self.assertEqual(self.send.call_count, 2)

    def test_direct_dispatch_uses_the_same_type_key(self):
        self._deliver("handoff:h", "primeiro")
        wm._remember_handoff_notification(CHAT, "URGENTE", "resumo", event_id="death-talk:x")
        wm._notify_owner_outbox_entry_direct("death-talk:x")
        self.assertEqual(self.send.call_count, 2)
        self.assertNotIn("death-talk:x", wm._handoff_outbox)

    def test_alert_type_comes_from_known_event_id_prefix(self):
        for event_id, expected in (
            ("crisis:ab", "crisis"),
            ("death-talk:ab", "death-talk"),
            ("alarm:ab", "alarm"),
            ("booking:ab", "booking"),
            ("scope-pending:" + CHAT, "scope-pending"),
            ("5511999999936:12@s.whatsapp.net", "handoff"),
            ("therapify-escalation-7", "handoff"),
            ("handoff-partial:ab", "handoff"),
            ("handoff:ab", "handoff"),
        ):
            with self.subTest(event_id=event_id):
                self.assertEqual(wm._handoff_alert_type(event_id), expected)


if __name__ == "__main__":
    unittest.main()
