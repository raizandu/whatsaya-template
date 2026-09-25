from __future__ import annotations

import sys
import json
import shutil
import subprocess
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

    @unittest.skipUnless(shutil.which("node"), "native JavaScript contract requires Node")
    def test_form_reader_executes_native_javascript_contract(self):
        values = {
            "P41_UNIDADE": "22", "P41_PROFISSIONAL_AGENDAR": "12",
            "P41_DATA_AGENDAR": "24/09/2031", "P41_HORARIO_AGENDAR": "10:00",
            "P41_HORARIO_LIVRE": "10:00", "P41_DURACAO": "40",
            "P41_DURACAO_LIVRE": "S", "P41_TIPO_AGENDAMENTO": "42",
            "P41_ID_PACIENTE": "31", "P41_ID_AGENDA": "61",
        }
        browser = FakeBrowser()
        def evaluate(expression):
            script = "const values=" + json.dumps(values) + ";"
            script += "const document={querySelector:s=>s.slice(1) in values?{value:values[s.slice(1)]}:null};"
            script += "const apex={item:id=>({getValue:()=>values[id]})};"
            script += "process.stdout.write(JSON.stringify(" + expression + "));"
            result = subprocess.run([shutil.which("node"), "-e", script],
                                    capture_output=True, text=True, check=True, timeout=10)
            return json.loads(result.stdout)
        browser.evaluate = evaluate
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        actual = port._read_form()
        self.assertEqual(actual["patient_id"], "31")
        self.assertEqual(actual["agenda_id"], "61")
        self.assertEqual(actual["start"], "2031-09-24T10:00:00-03:00")
        self.assertEqual(actual["end"], "2031-09-24T10:40:00-03:00")
        del values["P41_DURACAO"]
        with self.assertRaisesRegex(NativeBookingError, "appointment_form_changed"):
            port._read_form()

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

    def test_patient_selection_uses_real_suggestion_and_waits_for_identity(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        with patch.object(port, "_wait", return_value=True) as wait:
            selected = port.select_patient("31", "Pessoa Exemplo", "5511999999999")
        self.assertEqual(selected, "31")
        self.assertIn(("fill", ["#P41_NOME_PACIENTE", "Pessoa Exemplo"]), browser.calls)
        self.assertIn(("click", ['.autocomplete-suggestion[data-value^="31|"]']), browser.calls)
        self.assertIn("getClientRects", wait.call_args_list[0].args[0])
        self.assertIn("jQuery.active===0", wait.call_args_list[1].args[0])
        scripts = [call[1] for call in browser.calls if call[0]=="evaluate"]
        self.assertFalse(any("botaoAgendarPaciente" in script or "setValue" in script for script in scripts))

    def test_patient_selection_fails_closed_without_matching_suggestion(self):
        port = ProntuarioVerdeHermesPort(FakeBrowser(), CONFIG)
        with patch.object(port, "_wait", side_effect=NativeBookingError("page_not_ready")):
            with self.assertRaisesRegex(NativeBookingError, "patient_selection_unverified"):
                port.select_patient("31", "Pessoa Exemplo", "5511999999999")
        self.assertFalse(any(call[0]=="click" for call in port.browser.calls))

    def test_patient_selection_rejects_invalid_identity_before_browser_io(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(browser, CONFIG)
        for values in (("bad", "Pessoa Exemplo", "5511999999999"),
                       ("31", "Pessoa Exemplo", "bad"),
                       ("31", "", "5511999999999"),
                       ("31", '<b>Nome</b>', "5511999999999")):
            with self.subTest(values=values):
                with self.assertRaisesRegex(NativeBookingError, "patient_search_invalid"):
                    port.select_patient(*values)
        self.assertEqual(browser.calls, [])

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
