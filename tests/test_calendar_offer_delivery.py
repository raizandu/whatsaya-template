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

    def test_explicit_hour_must_match_single_or_ordinal_offer_selection(self):
        second_slot = {
            "start": "2999-01-07T18:00:00-03:00",
            "end": "2999-01-07T19:00:00-03:00",
        }
        self.assertIsNone(wm._calendar_selected_slot("Sim, às 19h", [SLOT]))
        self.assertIsNone(
            wm._calendar_selected_slot("o primeiro horário às 19h", [SLOT, second_slot])
        )

        inbound = self._find_offer()
        offer_text = wm._calendar_visible_reply(wm._calendar_turn_state[CHAT], inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            for part in wm._split_human_bubbles(offer_text):
                wm._calendar_mark_offer_delivered(CHAT, inbound, part, "offer-mid")
        delivered_at = wm._calendar_turn_state[CHAT]["delivered_slots"][SLOT["start"]]["at"]
        token = ("wrong-explicit-hour", delivered_at + 1)
        confirm = {"message_id": token[0], "at": token[1], "text": "Sim, às 19h"}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, confirm, token)), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "create_booking"
        ) as create:
            result = json.loads(wm._handle_calendar_book(
                SLOT,
                session_id=SESSION,
                expected_inbound_token=token,
                inbound_snapshot=confirm,
            ))
        self.assertEqual(result["status"], "error")
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

    def test_phase3_schedule_offer_after_consumed_inbound_is_promoted_and_confirmation_can_book(self):
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
        ), mock.patch.object(wm, "_current_inbound_record", return_value={}), mock.patch.object(
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

    def test_guarded_offer_callback_keeps_real_ack_time_when_newer_inbound_is_pending(self):
        inbound = self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        offer_text = wm._calendar_visible_reply(state, inbound["text"])
        confirmed_at = 101.5
        newer = {"message_id": "arrived-before-hook", "at": 101.0, "text": "Sim"}
        with mock.patch.object(wm, "_current_inbound_record", return_value=newer):
            delivered = all(
                wm._calendar_mark_offer_delivered(
                    CHAT,
                    inbound,
                    part,
                    "out-mid",
                    delivery_guarded=True,
                    confirmed_at=confirmed_at,
                )
                for part in wm._split_human_bubbles(offer_text)
            )

        self.assertTrue(delivered)
        offered = wm._calendar_turn_state[CHAT]
        self.assertEqual(offered["kind"], "offered")
        self.assertEqual(offered["delivered_slots"][SLOT["start"]]["at"], confirmed_at)
        early = {"message_id": "arrived-before-hook", "at": 101.0, "text": "Sim"}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, early, (early["message_id"], early["at"]))), mock.patch.object(
            wm, "_contact_has_explicit_ai_access", return_value=True
        ), mock.patch.object(wm, "create_booking") as create:
            result = json.loads(wm._handle_calendar_book(
                SLOT,
                session_id=SESSION,
                expected_inbound_token=(early["message_id"], early["at"]),
                inbound_snapshot=early,
            ))
        self.assertEqual(result["status"], "error")
        create.assert_not_called()

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

    def _orchestrate(self, inbound, *, history="", now=None):
        return wm._orchestrate_calendar_turn(
            chat_id=CHAT,
            session_id=SESSION,
            user_message=inbound["text"],
            history=history,
            now=now,
            inbound_snapshot=inbound,
        )

    def test_restart_with_existing_booking_acknowledges_sim_without_rescheduling(self):
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "persisted-event"}
        inbound = {"message_id": "restart-sim", "at": 500.0, "text": "Sim"}
        history = "Aya: Tenho quinta-feira, 07/01, às 17:00. Funciona?\nLead: Sim"
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "find_available_slots") as find:
            handled = self._orchestrate(inbound, history=history)

        self.assertTrue(handled)
        find.assert_not_called()
        state = wm._calendar_state_for_turn(CHAT, wm._inbound_record_token(inbound))
        self.assertEqual(state["kind"], "booked")
        self.assertEqual(state["result"]["event_id"], "persisted-event")
        self.assertEqual(state["action"], "book")

    def test_new_inbound_after_committed_booking_recovers_booking_after_delayed_reply_is_stale(self):
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "committed-event"}
        committed_token = ("book-confirmed", 490.0)
        wm._calendar_turn_state[CHAT] = {
            "kind": "booked",
            "action": "book",
            "inbound_token": committed_token,
            "result": booking,
        }
        inbound = {"message_id": "follow-up-after-delay", "at": 500.0, "text": "Sim"}
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "find_available_slots") as find:
            handled = self._orchestrate(inbound)

        self.assertTrue(handled)
        find.assert_not_called()
        state = wm._calendar_state_for_turn(CHAT, wm._inbound_record_token(inbound))
        self.assertEqual(state["kind"], "booked")
        self.assertEqual(state["result"]["event_id"], "committed-event")

    def test_price_question_after_existing_booking_stays_in_commercial_flow(self):
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "persisted-event"}
        inbound = {
            "message_id": "price-after-booking",
            "at": 500.0,
            "text": "Sim, só gostaria saber valor?!",
        }
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "find_available_slots") as find:
            handled = self._orchestrate(inbound)

        self.assertFalse(handled)
        self.assertNotIn(CHAT, wm._calendar_turn_state)
        find.assert_not_called()
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_history_has_pending_sales_call", return_value=True), mock.patch.object(
            wm, "_history_has_call_handoff_started", return_value=False
        ), mock.patch.object(wm, "_fetch_chat_history", return_value="Aya: Vamos marcar uma reunião?"):
            visible = wm._enforce_aya_payment_output_gate(
                "Fechado, sua reunião ficou agendada para quinta-feira.",
                user_message=inbound["text"],
                contact_info={},
                rules_content="",
                chat_id=CHAT,
            )
        self.assertNotIn("07/01", visible)

    def test_direct_slot_query_cannot_reopen_a_future_booking_as_new_booking(self):
        inbound = {"message_id": "ordinary-yes", "at": 500.0, "text": "Sim"}
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "existing"}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, inbound, OFFER_TOKEN)), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "find_available_slots") as find:
            payload = json.loads(
                wm._handle_calendar_find_slots(
                    {"date_from": "2099-01-07", "max_slots": 1, "action": "book"},
                    session_id=SESSION,
                    expected_inbound_token=OFFER_TOKEN,
                    inbound_snapshot=inbound,
                )
            )

        self.assertEqual(payload["status"], "error")
        find.assert_not_called()

    def test_direct_reschedule_query_requires_reschedule_intent_for_existing_booking(self):
        inbound = {"message_id": "ordinary-yes", "at": 500.0, "text": "Sim"}
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "existing"}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, inbound, OFFER_TOKEN)), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_fetch_chat_history", return_value=""), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={}
        ), mock.patch.object(wm, "find_available_slots") as find:
            payload = json.loads(
                wm._handle_calendar_find_slots(
                    {"date_from": "2099-01-07", "max_slots": 1, "action": "reschedule"},
                    session_id=SESSION,
                    expected_inbound_token=OFFER_TOKEN,
                    inbound_snapshot=inbound,
                )
            )

        self.assertEqual(payload["status"], "error")
        find.assert_not_called()

    def test_confirmed_reschedule_offer_still_uses_reschedule_operation(self):
        delivered_at = 101.0
        token = ("reschedule-confirm", 102.0)
        confirm = {"message_id": token[0], "at": token[1], "text": "Sim"}
        wm._calendar_turn_state[CHAT] = {
            "kind": "offered",
            "action": "reschedule",
            "inbound_token": ("reschedule-query", 100.0),
            "expires_at": 9_999_999_999.0,
            "slots": [SLOT],
            "delivered_message_id": "reschedule-offer-mid",
            "delivered_slots": {
                SLOT["start"]: {"message_id": "reschedule-offer-mid", "at": delivered_at}
            },
        }
        result = {"status": "rescheduled", "event_id": "existing", "start": SLOT["start"]}
        with mock.patch.object(wm, "_calendar_tool_context", return_value=(CHAT, confirm, token)), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "_contact_record_for_chat", return_value={}
        ), mock.patch.object(wm, "_qualification_fields", return_value=[]), mock.patch.object(
            wm, "reschedule_booking", return_value=result
        ) as reschedule, mock.patch.object(wm, "create_booking") as create, mock.patch.object(
            wm, "_profile_flag", return_value=False
        ), mock.patch.object(wm, "_followup_mark_commercial_terminal", return_value=True):
            response = json.loads(wm._handle_calendar_book(
                SLOT,
                session_id=SESSION,
                expected_inbound_token=token,
                inbound_snapshot=confirm,
            ))

        self.assertEqual(response["status"], "rescheduled")
        reschedule.assert_called_once()
        create.assert_not_called()

    def test_explicit_different_date_does_not_select_offered_slot_by_hour_only(self):
        inbound = {"message_id": "different-date", "at": 500.0, "text": "2099-01-08 às 17h"}
        offer_inbound = self._find_offer()
        offered_text = wm._calendar_visible_reply(wm._calendar_turn_state[CHAT], offer_inbound["text"])
        with mock.patch.object(wm, "_calendar_turn_is_current", return_value=True):
            promoted = all(
                wm._calendar_mark_offer_delivered(CHAT, offer_inbound, part, "offer-mid")
                for part in wm._split_human_bubbles(offered_text)
            )
        self.assertTrue(promoted)
        self.assertEqual(wm._calendar_active_state(CHAT)["kind"], "offered")

        self.assertIsNone(wm._calendar_selected_slot(inbound["text"], [SLOT]))
        ordinal_slots = [
            SLOT,
            {"start": "2099-01-08T17:00:00-03:00", "end": "2099-01-08T18:00:00-03:00"},
        ]
        self.assertIsNone(
            wm._calendar_selected_slot("primeiro horário 2099-01-08", ordinal_slots)
        )
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=None
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_calendar_phase_is_open", return_value=True), mock.patch.object(
            wm,
            "find_available_slots",
            return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": [SLOT]},
        ) as find:
            handled = self._orchestrate(inbound)

        self.assertTrue(handled, repr(wm._calendar_turn_state[CHAT]))

        self.assertEqual(find.call_args.kwargs["date_from"], "2099-01-08")
        self.assertEqual(wm._calendar_turn_state[CHAT]["kind"], "offer_pending_delivery")

    def test_same_persisted_day_and_hour_is_acknowledged_but_new_preference_reschedules(self):
        booking = {"start": SLOT["start"], "end": SLOT["end"], "event_id": "persisted-event"}
        same = {"message_id": "same-time", "at": 501.0, "text": "Sim, 2999-01-07 às 17h"}
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "find_available_slots") as find:
            handled = self._orchestrate(same)

        self.assertTrue(handled)
        find.assert_not_called()
        state = wm._calendar_state_for_turn(CHAT, wm._inbound_record_token(same))
        self.assertEqual(state["kind"], "booked")
        self.assertEqual(state["result"]["start"], SLOT["start"])

        different = {"message_id": "different-time", "at": 502.0, "text": "2099-01-08 às 16h"}
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=booking
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "_calendar_phase_is_open", return_value=True), mock.patch.object(
            wm, "find_available_slots", return_value={"status": "ok", "timezone": "America/Sao_Paulo", "slots": [SLOT]}
        ) as find:
            self.assertTrue(self._orchestrate(different))

        self.assertEqual(find.call_args.kwargs["date_from"], "2099-01-08")
        self.assertEqual(wm._calendar_turn_state[CHAT]["action"], "reschedule")

    def test_open_multi_slot_offer_survives_price_question_for_payment_gate(self):
        slots = [
            SLOT,
            {"start": "2999-01-07T18:00:00-03:00", "end": "2999-01-07T19:00:00-03:00"},
        ]
        offered = {
            "kind": "offered",
            "action": "book",
            "inbound_token": OFFER_TOKEN,
            "expires_at": 9_999_999_999.0,
            "slots": slots,
            "delivered_message_id": "offer-mid",
            "delivered_slots": {
                slot["start"]: {"message_id": "offer-mid", "at": 99.0} for slot in slots
            },
        }
        wm._calendar_turn_state[CHAT] = offered
        inbound = {"message_id": "price-question", "at": 101.0, "text": "Sim, só gostaria saber valor?!"}
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "get_booking", return_value=None
        ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ):
            handled = self._orchestrate(inbound)

        self.assertFalse(handled)
        self.assertEqual(wm._calendar_turn_state[CHAT], offered)
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
            wm, "_calendar_open_offer", return_value=offered
        ), mock.patch.object(wm, "_history_has_pending_sales_call", return_value=True), mock.patch.object(
            wm, "_history_has_call_handoff_started", return_value=False
        ), mock.patch.object(wm, "_fetch_chat_history", return_value="Aya: Vamos marcar uma reunião?"):
            visible = wm._enforce_aya_payment_output_gate(
                "Boa, qual horário você prefere?",
                user_message=inbound["text"],
                contact_info={},
                rules_content="",
                chat_id=CHAT,
            )
        self.assertNotIn("qual dos horários", visible.casefold())
        self.assertNotIn("horarios que te enviei", visible.casefold())

    def test_delivered_offer_preserves_commercial_questions_including_mixed_selection(self):
        slots = [SLOT, {"start": "2999-01-07T21:00:00-03:00", "end": "2999-01-07T22:00:00-03:00"}]
        for message in (
            "D graca?",
            "21h, d graça?",
            "21 mas a de hj é gratuita?",
            "É de graça?",
            "E quanto tempo de consulta?",
            "Quanto tempo dura a sessão?",
            "Como funcionam as sessões? Duração e tal",
            "É uma sessão ou tem retorno?",
            "Sim, é pelo Google Meet?",
        ):
            with self.subTest(message=message), mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}):
                offered = {
                    "kind": "offered", "action": "book", "inbound_token": OFFER_TOKEN,
                    "expires_at": 9_999_999_999.0, "slots": slots,
                    "delivered_message_id": "offer-mid",
                    "delivered_slots": {slot["start"]: {"message_id": "offer-mid", "at": 99.0} for slot in slots},
                }
                wm._calendar_turn_state[CHAT] = offered
                inbound = {"message_id": "commercial-question", "at": 101.0, "text": message}
                with mock.patch.object(wm, "_calendar_is_ready", return_value=True), mock.patch.object(
                    wm, "get_booking", return_value=None
                ), mock.patch.object(wm, "_contact_record_for_chat", return_value={}), mock.patch.object(
                    wm, "_calendar_turn_is_current", return_value=True
                ), mock.patch.object(wm, "create_booking") as book, mock.patch.object(wm, "find_available_slots") as find:
                    self.assertFalse(self._orchestrate(inbound))
                self.assertEqual(wm._calendar_turn_state[CHAT], offered)
                book.assert_not_called()
                find.assert_not_called()

    def test_booking_tool_refuses_selection_mixed_with_free_question(self):
        self._find_offer()
        state = wm._calendar_turn_state[CHAT]
        inbound = {"message_id": "free-question", "at": 101.0, "text": "17h, d graça?"}
        state.update({
            "kind": "offered", "delivered_message_id": "offer-mid", "delivered_at": 100.0,
            "delivered_slots": {SLOT["start"]: {"message_id": "offer-mid", "at": 100.0}},
        })
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "therapify"}), mock.patch.object(
            wm, "_calendar_tool_context", return_value=(CHAT, inbound, ("free-question", 101.0))
        ), mock.patch.object(wm, "_contact_has_explicit_ai_access", return_value=True), mock.patch.object(
            wm, "_calendar_turn_is_current", return_value=True
        ), mock.patch.object(wm, "get_booking", return_value=None), mock.patch.object(wm, "create_booking") as create:
            payload = json.loads(wm._handle_calendar_book(SLOT, session_id=SESSION))
        self.assertEqual(payload["status"], "error")
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
