from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "scripts"))

from prontuario_verde_native_booking import (  # noqa: E402
    NativeBookingError,
    ProntuarioVerdeHermesPort,
)


HASH = "a" * 64
CONFIG = {
    "enabled": True,
    "appointment_write_enabled": True,
    "clinic_id": "clinic",
    "source_clinic_hash": HASH,
}


def request(**overrides):
    values = {
        "operation": "book", "request_id": "req",
        "patient_id": "31", "professional_id": "12", "unit_id": "22",
        "type_id": "42", "duration_min": 30,
        "requested_start": "2031-09-24T13:00:00+00:00",
        "requested_end": "2031-09-24T13:30:00+00:00",
        "clinic_id": "clinic", "source_clinic_hash": HASH,
    }
    return {**values, **overrides}


class FakeBrowser:
    source_clinic_hash = HASH

    def __init__(self):
        self.calls = []

    def evaluate(self, expression):
        self.calls.append(("evaluate", expression))
        return True

    def command(self, name, args):
        self.calls.append((name, args))

    def refresh_authenticated(self):
        self.calls.append(("refresh_authenticated",))
        return True


class NativeBookingPortTests(unittest.TestCase):
    def test_reschedule_keeps_original_evidence_before_filling_target(self):
        from prontuario_verde_availability import Interval, OpeningSnapshot
        from prontuario_verde_native_booking import SAO_PAULO

        start = datetime(2031, 9, 24, 10, tzinfo=SAO_PAULO)
        end = start + timedelta(minutes=30)
        old_start = start - timedelta(days=1)
        old_end = old_start + timedelta(minutes=30)
        req = request(operation="reschedule", appointment_id="61",
                      expected_start=old_start.isoformat(), expected_end=old_end.isoformat())
        original_form = {
            "agenda_id": "61", "patient_id": "31", "professional_id": "12",
            "unit_id": "22", "type_id": "42", "duration_min": 30,
            "date": old_start.strftime("%d/%m/%Y"), "time": "10:00",
            "start": old_start.isoformat(), "end": old_end.isoformat(),
        }
        target_form = {**original_form, "date": start.strftime("%d/%m/%Y"),
                       "start": start.isoformat(), "end": end.isoformat()}
        snapshot = OpeningSnapshot(
            HASH, "12", "22", start.date(), datetime.now(timezone.utc),
            (Interval(start, end),), (), (start,), True,
        )
        port = ProntuarioVerdeHermesPort(
            FakeBrowser(), CONFIG, opening_provider=lambda _: snapshot,
            target_reader=lambda _: {"complete": True, "clinic_id": "clinic",
                                     "source_clinic_hash": HASH, "rows": []},
            old_appointment_reader=lambda _: {},
            patient_selector=lambda _, patient_id: patient_id,
        )
        state = {"form": original_form}
        with patch.object(port, "_require_authenticated_agenda"), patch.object(port, "_open_native_form"), \
             patch.object(port, "_read_form", side_effect=lambda: dict(state["form"])), \
             patch.object(port, "_fill_known_fields", side_effect=lambda _: state.update(form=target_form)):
            result = port.prepare(req)
        self.assertEqual(result["original_appointment"]["start"], old_start.isoformat())
        self.assertEqual(result["original_appointment"]["end"], old_end.isoformat())
        self.assertEqual(result["start"], start.isoformat())
        self.assertEqual(result["end"], end.isoformat())

    def test_failed_preflight_invalidates_previous_preparation(self):
        port = ProntuarioVerdeHermesPort(FakeBrowser(), CONFIG)
        port._prepared = request()
        with self.assertRaisesRegex(NativeBookingError, "opening_source_unavailable"):
            port.prepare(request())
        with self.assertRaisesRegex(NativeBookingError, "preflight_not_current"):
            port.submit_once(request())

    def test_preparing_again_cannot_reset_a_submission(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        port._submitted = True
        with self.assertRaisesRegex(NativeBookingError, "submit_already_attempted"):
            port.prepare(request())
        self.assertEqual(browser.calls, [])

    def test_slot_change_before_submit_prevents_click(self):
        from prontuario_verde_availability import Interval, OpeningSnapshot
        from prontuario_verde_native_booking import SAO_PAULO

        start = datetime(2031, 9, 24, 10, tzinfo=SAO_PAULO)
        end = start + timedelta(minutes=30)
        busy = Interval(start, end)
        snapshot = OpeningSnapshot(HASH, "12", "22", start.date(),
                                   datetime.now(timezone.utc), (busy,), (busy,), (start,), True)
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG, opening_provider=lambda _: snapshot)
        port._prepared = request()
        with self.assertRaisesRegex(NativeBookingError, "slot_not_verified_available"):
            port.submit_once(request())
        self.assertEqual(browser.calls, [])
        self.assertFalse(port._submitted)

    def test_native_date_and_other_duration_follow_observed_form_contract(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        values = []
        selects = []
        def evaluate(script):
            browser.calls.append(("evaluate", script))
            return "S" if "P41_DURACAO_LIVRE" in script else True
        browser.evaluate = evaluate
        with patch.object(port, "_set_apex_item", side_effect=lambda key, value: values.append((key, value))), \
             patch.object(port, "_set_select", side_effect=lambda key, value: selects.append((key, value))), \
             patch.object(port, "_wait", return_value=True):
            port._fill_known_fields(request(duration_min=40))
        self.assertIn(("P41_DATA_AGENDAR", "24/09/2031"), values)
        self.assertIn(("P41_NOVA_DURACAO", "40"), values)
        self.assertIn(("P41_DURACAO", "9999999999"), selects)
        self.assertTrue(any("#BT_INFORMADO_OK" in script for _, script in browser.calls))
        self.assertFalse(any("#botaoAgendarPaciente" in script for _, script in browser.calls))

    def test_native_form_parses_brazilian_date_and_rejects_invalid_date(self):
        port = ProntuarioVerdeHermesPort(FakeBrowser(), CONFIG)
        fields = {"date": "24/09/2031", "time": "10:00", "duration_min": "40"}
        with patch.object(port, "_eval", return_value=fields):
            result = port._read_form()
        self.assertEqual(result["start"], "2031-09-24T10:00:00-03:00")
        self.assertEqual(result["end"], "2031-09-24T10:40:00-03:00")
        with patch.object(port, "_eval", return_value={**fields, "date": "31/09/2031"}):
            with self.assertRaisesRegex(NativeBookingError, "form_values_unverified"):
                port._read_form()

    def test_submit_waits_for_async_save_and_never_retries_on_timeout(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                browser = FakeBrowser()
                port = ProntuarioVerdeHermesPort(browser, CONFIG)
                port._prepared = request()
                wait_error = NativeBookingError("page_not_ready") if timeout else None
                with patch.object(port, "_verify_live_target"), patch.object(port, "_verify_native_opening"), patch.object(port, "_read_form"), \
                     patch.object(port, "_validate_form"), patch.object(port, "_wait", side_effect=wait_error) as wait:
                    if timeout:
                        with self.assertRaisesRegex(NativeBookingError, "submit_outcome_uncertain"):
                            port.submit_once(request())
                    else:
                        port.submit_once(request())
                    self.assertIn("jQuery.active===0", wait.call_args.args[0])
                    with self.assertRaisesRegex(NativeBookingError, "submit_already_attempted"):
                        port.submit_once(request())
                self.assertEqual(sum("#botaoAgendarPaciente" in script for _, script in browser.calls), 1)

    def test_native_opening_check_rejects_closed_incomplete_or_short_slots(self):
        port = ProntuarioVerdeHermesPort(FakeBrowser(), CONFIG)
        for value, error in (
            (None, "native_opening_unverified"),
            ({"within_opening": False, "duration_max": "480"}, "native_opening_unverified"),
            ({"within_opening": True, "duration_max": "0"}, "native_duration_unavailable"),
            ({"within_opening": True, "duration_max": "20"}, "native_duration_unavailable"),
            ({"within_opening": True, "duration_max": ""}, "native_duration_unavailable"),
        ):
            with self.subTest(value=value), patch.object(port, "_eval", return_value=value):
                with self.assertRaisesRegex(NativeBookingError, error):
                    port._verify_native_opening(request())
        with patch.object(port, "_eval", return_value={"within_opening": True, "duration_max": "40"}), \
             patch.object(port, "_read_form"), patch.object(port, "_validate_form") as validate:
            port._verify_native_opening(request())
            validate.assert_called_once()

    def test_write_gate_is_off_by_default_and_does_not_touch_browser(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, {})
        with self.assertRaisesRegex(NativeBookingError, "appointment_writes_disabled"):
            port.prepare(request())
        with self.assertRaisesRegex(NativeBookingError, "appointment_writes_disabled"):
            port.submit_once(request())
        self.assertEqual(browser.calls, [])

    def test_missing_opening_or_duplicate_source_fails_before_browser_actions(self):
        for kwargs, expected in (
            ({}, "opening_source_unavailable"),
            ({"opening_provider": lambda _request: object()}, "duplicate_reader_unavailable"),
        ):
            with self.subTest(expected=expected):
                browser = FakeBrowser()
                port = ProntuarioVerdeHermesPort(browser, CONFIG, **kwargs)
                with self.assertRaisesRegex(NativeBookingError, expected):
                    port.prepare(request())
                self.assertEqual(browser.calls, [])

    def test_procedure_is_rejected_until_native_control_is_identified(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(
            browser, CONFIG,
            opening_provider=lambda _request: object(),
            target_reader=lambda _request: {"complete": True, "clinic_id": "clinic",
                                            "source_clinic_hash": HASH, "rows": []},
        )
        with self.assertRaisesRegex(NativeBookingError, "procedure_form_contract_unknown"):
            port.prepare(request(procedure_id="52"))
        self.assertEqual(browser.calls, [])

    def test_unknown_duration_fails_closed(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(
            browser, CONFIG,
            opening_provider=lambda _request: object(),
            target_reader=lambda _request: {"complete": True, "clinic_id": "clinic",
                                            "source_clinic_hash": HASH, "rows": []},
            patient_selector=lambda _browser, patient_id: patient_id,
        )
        with self.assertRaisesRegex(NativeBookingError, "duration_form_contract_unknown"):
            port.prepare(request(duration_min=45))
        self.assertEqual(browser.calls, [])

    def test_duplicate_reader_must_assert_complete_clinic_bound_result(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        for result in (
            [],
            {"complete": False, "clinic_id": "clinic", "source_clinic_hash": HASH, "rows": []},
            {"complete": True, "clinic_id": "other", "source_clinic_hash": HASH, "rows": []},
            {"complete": True, "clinic_id": "clinic", "source_clinic_hash": "b" * 64, "rows": []},
        ):
            with self.subTest(result=result):
                with self.assertRaisesRegex(NativeBookingError, "duplicate_read_unverified"):
                    port._complete_rows(result, request())

    def test_duplicate_result_requires_full_normalized_identity(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        result = {
            "complete": True, "clinic_id": "clinic", "source_clinic_hash": HASH,
            "rows": [{"appointment_id": "61", "start": request()["requested_start"]}],
        }
        with self.assertRaisesRegex(NativeBookingError, "duplicate_read_unverified"):
            port._complete_rows(result, request())


if __name__ == "__main__":
    unittest.main()
