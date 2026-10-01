from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from datetime import date, datetime
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

CHAT = "556281405459@s.whatsapp.net"
SESSION = CHAT
SLOT = {"start": "2999-01-07T17:00:00-03:00", "end": "2999-01-07T18:00:00-03:00"}
OFFER_TOKEN = ("lead-offer", 100.0)
CONFIRM_TOKEN = ("lead-confirm", 102.0)


class CalendarOfferDeliveryTests(unittest.TestCase):
    def setUp(self):
        wm._calendar_turn_state.pop(CHAT, None)
        self.addCleanup(wm._calendar_turn_state.pop, CHAT, None)

    def _find_offer(self):
        inbound = {"message_id": OFFER_TOKEN[0], "at": OFFER_TOKEN[1], "text": "Sim"}
        with mock.patch.object(
            wm,
            "_calendar_tool_context",
            return_value=(CHAT, inbound, OFFER_TOKEN),
        ), mock.patch.object(
            wm,
            "find_available_slots",
            return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": [SLOT]},
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "_calendar_phase_is_open", return_value=True
        ):
            payload = json.loads(
                wm._handle_calendar_find_slots(
                    {"date_from": "2999-01-07", "max_slots": 1},
                    session_id=SESSION,
                    expected_inbound_token=OFFER_TOKEN,
                    inbound_snapshot=inbound,
                )
            )
        self.assertEqual(payload["status"], "ok")
        return inbound

    def test_slot_query_is_not_an_offer_until_the_outbound_message_id_is_confirmed(self):
        self._find_offer()

        state = wm._calendar_turn_state[CHAT]
        self.assertEqual(state["kind"], "offer_pending_delivery")
        self.assertFalse(state.get("delivered_message_id"))

    def test_human_send_calls_delivery_hook_only_after_bridge_returns_message_id(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"messageId":"bridge-mid"}'

        callbacks = []
        with mock.patch.object(wm.urllib.request, "urlopen", return_value=Response()):
            result = wm._human_send(
                CHAT,
                "Tenho este horário livre: segunda às 17:00. Funciona?",
                on_message_sent=lambda text, message_id: callbacks.append((text, message_id)),
            )

        self.assertEqual(result, "bridge-mid")
        self.assertEqual(callbacks, [("Tenho este horário livre: segunda às 17:00. Funciona?", "bridge-mid")])

    def test_confirmation_cannot_book_an_offer_that_has_not_been_delivered(self):
        self._find_offer()
        confirm = {"message_id": CONFIRM_TOKEN[0], "at": CONFIRM_TOKEN[1], "text": "Sim"}
        with mock.patch.object(
            wm,
            "_calendar_tool_context",
            return_value=(CHAT, confirm, CONFIRM_TOKEN),
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "create_booking"
        ) as create:
            payload = json.loads(
                wm._handle_calendar_book(
                    SLOT,
                    session_id=SESSION,
                    expected_inbound_token=CONFIRM_TOKEN,
                    inbound_snapshot=confirm,
                )
            )

        self.assertEqual(payload["status"], "error")
        create.assert_not_called()

    def test_only_the_exact_offer_bubble_is_promoted_after_bridge_message_id(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            assert wm._calendar_mark_offer_delivered(CHAT, inbound, "texto diferente", "out-mid") is False
        self.assertEqual(state["kind"], "offer_pending_delivery")

        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            for part in wm._split_human_bubbles(offer_text):
                wm._calendar_mark_offer_delivered(CHAT, inbound, part, "out-mid")
        self.assertEqual(wm._calendar_turn_state[CHAT]["kind"], "offered")
        self.assertEqual(wm._calendar_turn_state[CHAT]["delivered_message_id"], "out-mid")

    def test_delivery_callback_does_not_resurrect_offer_after_new_inbound(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=False):
            delivered = wm._calendar_mark_offer_delivered(CHAT, inbound, offer_text, "out-mid")

        self.assertFalse(delivered)
        self.assertEqual(state["kind"], "offer_pending_delivery")

    def test_booking_requires_inbound_received_after_the_delivered_offer(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            for part in wm._split_human_bubbles(offer_text):
                wm._calendar_mark_offer_delivered(CHAT, inbound, part, "out-mid")
        self.assertEqual(wm._calendar_turn_state[CHAT]["kind"], "offered")
        # A distinct token alone is insufficient: an inbound received before delivery
        # may be processed afterward by the asynchronous tool path.
        delivered_at = wm._calendar_turn_state[CHAT]["delivered_at"]
        early_token = ("early-confirm", delivered_at - 0.01)
        early = {"message_id": early_token[0], "at": early_token[1], "text": "Sim"}
        with mock.patch.object(
            wm,
            "_calendar_tool_context",
            return_value=(CHAT, early, early_token),
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "_contact_has_explicit_ai_access", return_value=True
        ), mock.patch.object(wm, "create_booking") as create:
            payload = json.loads(
                wm._handle_calendar_book(
                    SLOT,
                    session_id=SESSION,
                    expected_inbound_token=early_token,
                    inbound_snapshot=early,
                )
            )

        self.assertEqual(payload["status"], "error")
        create.assert_not_called()

    def test_delivered_offer_can_be_booked_and_meet_link_stays_internal(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            for part in wm._split_human_bubbles(offer_text):
                wm._calendar_mark_offer_delivered(CHAT, inbound, part, "out-mid")
        delivered_at = wm._calendar_turn_state[CHAT]["delivered_slots"][SLOT["start"]]["at"]
        token = ("lead-confirm", delivered_at + 1)
        confirm = {"message_id": token[0], "at": token[1], "text": "Sim"}
        booking = {
            "status": "created",
            "event_id": "event-1",
            "start": SLOT["start"],
            "meet_link": "https://meet.google.com/abc-defg-hij",
        }
        with mock.patch.object(
            wm, "_calendar_tool_context", return_value=(CHAT, confirm, token)
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "_contact_has_explicit_ai_access", return_value=True
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_qualification_fields", return_value=[]
        ), mock.patch.object(wm, "create_booking", return_value=booking) as create, mock.patch.object(
            wm, "_profile_flag", return_value=False
        ), mock.patch.object(wm, "_followup_mark_commercial_terminal", return_value=True):
            payload = json.loads(
                wm._handle_calendar_book(
                    SLOT,
                    session_id=SESSION,
                    expected_inbound_token=token,
                    inbound_snapshot=confirm,
                )
            )

        create.assert_called_once()
        self.assertEqual(payload["status"], "created")
        self.assertNotIn("meet_link", payload)
        self.assertEqual(wm._calendar_turn_state[CHAT]["result"]["meet_link"], booking["meet_link"])

    def test_manual_meet_booking_succeeds_without_link_and_notifies_owner(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            for part in wm._split_human_bubbles(offer_text):
                wm._calendar_mark_offer_delivered(CHAT, inbound, part, "out-mid")
        delivered_at = wm._calendar_turn_state[CHAT]["delivered_slots"][SLOT["start"]]["at"]
        token = ("lead-confirm", delivered_at + 1)
        confirm = {"message_id": token[0], "at": token[1], "text": "Sim"}
        booking = {"status": "created", "event_id": "event-manual-meet", "start": SLOT["start"]}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, confirm, token)), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={}
        ), mock.patch.object(wm, "_qualification_fields", return_value=[]), mock.patch.object(
            wm, "create_booking", return_value=booking
        ) as create, mock.patch.object(wm, "_profile_flag", return_value=False), mock.patch.object(
            wm, "_followup_mark_commercial_terminal", return_value=True
        ) as terminalizer:
            payload = json.loads(
                wm._handle_calendar_book(
                    SLOT,
                    session_id=SESSION,
                    expected_inbound_token=token,
                    inbound_snapshot=confirm,
                )
            )

        create.assert_called_once()
        self.assertEqual(payload["status"], "created")
        self.assertEqual(wm._calendar_turn_state[CHAT]["kind"], "booked")
        self.assertEqual(wm._calendar_turn_state[CHAT]["result"]["event_id"], booking["event_id"])
        terminalizer.assert_called_once_with(
            CHAT, reason="booking", booking=booking, notify_owner=True
        )

    def test_phase3_schedule_offer_ack_then_confirmation_can_book(self):
        inbound = {"message_id": OFFER_TOKEN[0], "at": OFFER_TOKEN[1], "text": "Quero marcar"}
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"messageId":"phase3-offer-mid"}'

        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "find_available_slots", return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": [SLOT]}
        ), mock.patch.object(wm, "_current_inbound_record", return_value=inbound), mock.patch.object(
            wm, "_newer_inbound_arrived", return_value=False
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), mock.patch.object(wm, "_assert_delivery_allowed"), mock.patch.object(
            wm.urllib.request, "urlopen", return_value=Response()
        ):
            sent = wm._playbook_offer_slots(
                CHAT,
                {"max_slots": 1, "schedule_question": "Qual horário fica melhor?"},
                OFFER_TOKEN,
            )

        self.assertTrue(sent)
        self.assertEqual(wm._calendar_turn_state[CHAT]["kind"], "offered")
        offered = wm._calendar_active_state(CHAT)
        self.assertEqual(offered["kind"], "offered")
        self.assertEqual(offered["delivered_slots"][SLOT["start"]]["message_id"], "phase3-offer-mid")
        confirm_at = offered["delivered_slots"][SLOT["start"]]["at"] + 1
        confirm_token = ("phase3-confirm", confirm_at)
        confirm = {"message_id": confirm_token[0], "at": confirm_token[1], "text": "Sim"}
        booking = {
            "status": "created",
            "event_id": "phase3-event",
            "start": SLOT["start"],
            "meet_link": "https://meet.google.com/abc-defg-hij",
        }
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, confirm, confirm_token)), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={}
        ), mock.patch.object(wm, "_qualification_fields", return_value=[]), mock.patch.object(
            wm, "create_booking", return_value=booking
        ) as create, mock.patch.object(wm, "_followup_mark_commercial_terminal", return_value=True):
            payload = json.loads(
                wm._handle_calendar_book(
                    SLOT,
                    session_id=SESSION,
                    expected_inbound_token=confirm_token,
                    inbound_snapshot=confirm,
                )
            )

        self.assertEqual(payload["status"], "created")
        create.assert_called_once()

    def test_phase3_day_schedule_requires_ack_of_date_and_slot_bubble(self):
        inbound = {"message_id": OFFER_TOKEN[0], "at": OFFER_TOKEN[1], "text": "Quero marcar"}
        slot_start = datetime.fromisoformat(SLOT["start"])
        slot_end = datetime.fromisoformat(SLOT["end"])
        day = {
            "date": slot_start.date(),
            "slots": [{"start": slot_start, "end": slot_end, "status": "free"}],
        }
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"messageId":"day-mid"}'

        cfg = {
            "schedule_days": 1,
            "schedule_name_format": "first",
            "schedule_private_words": [],
            "schedule_extend_if_no_free": True,
            "schedule_question": "Qual horário fica melhor?",
        }
        with mock.patch.object(wm, "day_schedule", return_value=[day]), mock.patch.object(
            wm, "_format_day_schedule", wraps=wm._format_day_schedule
        ), mock.patch.object(wm, "_newer_inbound_arrived", return_value=False), mock.patch.object(
            wm, "_current_inbound_record", return_value=inbound
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "_playbook_business_window_open", return_value=True
        ), mock.patch.object(wm, "_assert_delivery_allowed"), mock.patch.object(
            wm.urllib.request, "urlopen", return_value=Response()
        ):
            self.assertTrue(wm._playbook_offer_day_schedule(CHAT, cfg, OFFER_TOKEN))

        offered = wm._calendar_active_state(CHAT)
        self.assertEqual(offered["kind"], "offered")
        self.assertIn(SLOT["start"], offered["delivered_slots"])
        self.assertIn(SLOT["start"], {slot["start"] for slot in offered["slots"]})

    def test_stale_slot_query_does_not_publish_offer(self):
        inbound = {"message_id": OFFER_TOKEN[0], "at": OFFER_TOKEN[1], "text": "Sim"}
        with mock.patch.object(
            wm,
            "_calendar_tool_context",
            return_value=(CHAT, inbound, OFFER_TOKEN),
        ), mock.patch.object(
            wm,
            "find_available_slots",
            return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": [SLOT]},
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=False), mock.patch.object(
            wm, "_calendar_phase_is_open", return_value=True
        ):
            payload = json.loads(
                wm._handle_calendar_find_slots(
                    {"date_from": "2999-01-07", "max_slots": 1},
                    session_id=SESSION,
                    expected_inbound_token=OFFER_TOKEN,
                    inbound_snapshot=inbound,
                )
            )

        self.assertEqual(payload["status"], "error")
        self.assertNotIn(CHAT, wm._calendar_turn_state)

    def test_slot_query_clamps_to_fourteen_inclusive_days(self):
        inbound = {"message_id": OFFER_TOKEN[0], "at": OFFER_TOKEN[1], "text": "Sim"}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, inbound, OFFER_TOKEN)), mock.patch.object(
            wm, "_calendar_phase_is_open", return_value=True
        ), mock.patch.object(wm, "_calendar_turn_is_current", return_value=True), mock.patch.object(
            wm, "find_available_slots", return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": []}
        ) as find:
            result = json.loads(
                wm._handle_calendar_find_slots(
                    {"date_from": "2999-01-07", "date_to": "2999-01-25"},
                    session_id=SESSION,
                    expected_inbound_token=OFFER_TOKEN,
                    inbound_snapshot=inbound,
                )
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(find.call_args.kwargs["date_to"], "2999-01-20")

    def test_generic_booking_reply_keeps_meet_link_when_profile_uses_default(self):
        booked = {
            "kind": "booked",
            "action": "book",
            "result": {"start": SLOT["start"], "meet_link": "https://meet.google.com/abc-defg-hij"},
        }
        with mock.patch.object(wm, "_profile_flag", side_effect=lambda _path, default: default):
            visible = wm._calendar_visible_reply(booked, "Sim")

        self.assertIn("https://meet.google.com/abc-defg-hij", visible)

    def test_booked_reply_honors_manual_meet_delivery_profile(self):
        booked = {
            "kind": "booked",
            "action": "book",
            "result": {"start": SLOT["start"], "meet_link": "https://meet.google.com/abc-defg-hij"},
        }
        with mock.patch.object(wm, "_profile_flag", return_value=False):
            visible = wm._calendar_visible_reply(booked, "Sim")

        self.assertNotIn("meet.google.com", visible)
        self.assertIn("agendada", visible)
        self.assertEqual(booked["result"]["meet_link"], "https://meet.google.com/abc-defg-hij")


if __name__ == "__main__":
    unittest.main()
