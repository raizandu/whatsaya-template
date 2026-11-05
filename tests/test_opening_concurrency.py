import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from tests.test_panel_actions import panel_actions
import contacts_store
import opening_resolution
from opening_inbound_outbox import OpeningInboundOutbox

CHAT = "5511999999999@s.whatsapp.net"
LID = "117171717171@lid"


class OpeningCoordinationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = SimpleNamespace(contacts_json=self.root / "contacts.json", followups_db=self.root / "followups.db")
        self.paths.contacts_json.write_text(json.dumps({CHAT: {"ai_enabled": False, "in_flow": False}}))

    def test_original_race_inserted_during_resume_is_rechecked(self):
        original = opening_resolution.resume_pending
        def insert_then_resume(paths, chat):
            result = original(paths, chat)
            outbox = OpeningInboundOutbox(self.root / "opening_inbound_outbox.db")
            outbox.defer(CHAT, "one", "turn", "message", 1)
            outbox.mark_opening_uncertain("turn")
            contacts_store.update_record(paths.contacts_json, [CHAT], {"ai_enabled": False, "ai_disabled_reason": "opening_uncertain"})
            return result
        with mock.patch.object(opening_resolution, "resume_pending", side_effect=insert_then_resume):
            with self.assertRaisesRegex(panel_actions.ActionError, "entrega incerta"):
                panel_actions.set_ai_access(self.paths, chat_id=CHAT, enabled=True)
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[CHAT]["ai_enabled"])

    def test_alias_insertion_and_activation_serialize_between_processes(self):
        entered = threading.Event()
        release = threading.Event()
        actual_apply = panel_actions._apply_ai_enable
        outcome = []
        def held_apply(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("activation not released")
            return actual_apply(*args, **kwargs)
        def activate():
            try:
                outcome.append(panel_actions.set_ai_access(self.paths, chat_id=CHAT, enabled=True))
            except Exception as exc:
                outcome.append(exc)
        script = r"""
import sys, time
from pathlib import Path
import contacts_store
from opening_inbound_outbox import OpeningInboundOutbox, opening_state_lock
root, chat, lid = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
print('attempting', flush=True)
with opening_state_lock(root):
    box = OpeningInboundOutbox(root / 'opening_inbound_outbox.db')
    box.defer_batch(lid, 'turn', [('m1','message')], time.time(), initial_state='uncertain')
    contacts_store.update_record(root / 'contacts.json', [chat], {'ai_enabled':False, 'ai_disabled_reason':'opening_uncertain'})
print('written', flush=True)
"""
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        child = None
        with mock.patch.object(panel_actions, "_apply_ai_enable", side_effect=held_apply):
            thread = threading.Thread(target=activate)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                child = subprocess.Popen([sys.executable, "-c", script, str(self.root), CHAT, LID], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                self.assertEqual(child.stdout.readline().strip(), "attempting")
                self.assertEqual(select.select([child.stdout], [], [], .2)[0], [])
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn("written", stdout)
        self.assertTrue(outcome and isinstance(outcome[0], dict), outcome)
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[CHAT]["ai_enabled"])
        self.assertTrue(OpeningInboundOutbox(self.root / "opening_inbound_outbox.db").uncertain_batches(LID))


class LateOpeningCaptureTest(unittest.TestCase):
    def test_capture_received_before_clearance_pauses_even_after_activation(self):
        import contextlib
        import time
        from tests.test_therapify_opening_direct import wm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contacts_path = root / "contacts.json"
            contacts_path.write_text(json.dumps({CHAT: {"ai_enabled": True, "in_flow": True}}))
            box = OpeningInboundOutbox(root / "opening_inbound_outbox.db")
            received_at = time.time() - 1
            box.request_resume(CHAT, ["turn"])
            record = {"chat_id": CHAT, "opening": True, "inbound_message_id": "original", "inbound_at": 1}
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}))
                for name, value in {"_OPENING_INBOUND_OUTBOX_PATH": box.path}.items():
                    stack.enter_context(mock.patch.object(wm, name, value))
                stack.enter_context(mock.patch.object(wm, "_partial_reply_records", return_value={"turn": record}))
                stack.enter_context(mock.patch.object(wm, "_partial_reply_for_turn", return_value=record))
                stack.enter_context(mock.patch.object(wm, "_contact_identity_candidates", return_value=({CHAT, LID}, {"5511999999999"})))
                stack.enter_context(mock.patch.object(wm, "_contact_effect_identity_lock", side_effect=lambda *a: contextlib.nullcontext()))
                stack.enter_context(mock.patch.object(wm, "_opening_text_is_safe", return_value=True))
                stack.enter_context(mock.patch.object(wm, "_load_personal_contacts", side_effect=lambda: contacts_store.read_contacts(contacts_path)))
                stack.enter_context(mock.patch.object(wm, "_merge_contact_record_atomic", side_effect=lambda key, fields, **kw: contacts_store.update_record(contacts_path, [CHAT], fields)))
                stack.enter_context(mock.patch.object(wm, "_followup_cancel"))
                stack.enter_context(mock.patch.object(wm, "_queue_owner_notification_safely"))
                self.assertTrue(wm._defer_new_opening_inbound(LID, {"message_id": "late", "text": "Sim", "at": received_at}, before_coalesce=True))
            self.assertFalse(contacts_store.read_contacts(contacts_path)[CHAT]["ai_enabled"])
            self.assertTrue(box.uncertain_batches(CHAT))


    def test_capture_after_clearance_does_not_pause(self):
        import time
        from tests.test_therapify_opening_direct import wm
        with tempfile.TemporaryDirectory() as tmp:
            box = OpeningInboundOutbox(Path(tmp) / "opening_inbound_outbox.db")
            box.request_resume(CHAT, ["turn"])
            with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", box.path), mock.patch.object(wm, "_pause_for_opening_uncertainty") as pause:
                wm._persist_opening_capture(CHAT, "turn", [("new", "Sim")], time.time() + 1)
            pause.assert_not_called()
            self.assertFalse(box.uncertain_batches(CHAT))
            self.assertTrue(box.contains_all(CHAT, ["new"]))

    def test_duplicate_before_clearance_does_not_reopen_review(self):
        import time
        from tests.test_therapify_opening_direct import wm
        with tempfile.TemporaryDirectory() as tmp:
            box = OpeningInboundOutbox(Path(tmp) / "opening_inbound_outbox.db")
            received_at = time.time() - 1
            box.defer_batch(CHAT, "turn", [("old", "Sim")], received_at)
            box.mark_opening_complete("turn")
            box.request_resume(CHAT, ["turn"])
            with mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", box.path), mock.patch.object(wm, "_pause_for_opening_uncertainty") as pause:
                wm._persist_opening_capture(CHAT, "turn", [("old", "Sim")], received_at)
            pause.assert_not_called()
            self.assertFalse(box.uncertain_batches(CHAT))


class AuthorizedTurnReservationTest(unittest.TestCase):
    def test_two_threads_cannot_reserve_the_same_authorized_turn(self):
        import contextlib
        from tests.test_therapify_opening_direct import wm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            box = OpeningInboundOutbox(root / "opening_inbound_outbox.db")
            box.request_resume(CHAT, ["turn"])
            sent_path = root / "sent.json"
            sent_path.write_text(json.dumps({"turn": 1}))
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(wm, "_OPENING_INBOUND_OUTBOX_PATH", box.path))
                stack.enter_context(mock.patch.object(wm, "_TURN_SENT_PATH", sent_path))
                stack.enter_context(mock.patch.object(wm, "_turn_sent", {"turn"}))
                stack.enter_context(mock.patch.object(wm, "_turn_inflight", set()))
                stack.enter_context(mock.patch.object(wm, "_log_suppressed"))
                start = threading.Barrier(2)
                results = []
                errors = []
                def reserve():
                    try:
                        start.wait(timeout=3)
                        results.append(wm._reserve_contact_send(CHAT, CHAT, "text", expected_turn_key="turn")[0])
                    except BaseException as exc:
                        errors.append(type(exc).__name__)
                threads = [threading.Thread(target=reserve, daemon=True) for _ in range(2)]
                for thread in threads: thread.start()
                for thread in threads: thread.join(timeout=3)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertFalse(errors, errors)
                self.assertEqual(sorted(results), [False, True])
                self.assertFalse(box.turn_authorized("turn"))
