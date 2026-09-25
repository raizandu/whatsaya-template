from __future__ import annotations

import sys
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

    def test_40_minute_duration_fails_closed_until_other_duration_contract_is_known(self):
        browser = FakeBrowser()
        port = ProntuarioVerdeHermesPort(
            browser, CONFIG,
            opening_provider=lambda _request: object(),
            target_reader=lambda _request: {"complete": True, "clinic_id": "clinic",
                                            "source_clinic_hash": HASH, "rows": []},
            patient_selector=lambda _browser, patient_id: patient_id,
        )
        with self.assertRaisesRegex(NativeBookingError, "duration_form_contract_unknown"):
            port.prepare(request(duration_min=40))
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
