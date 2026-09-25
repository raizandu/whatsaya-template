from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "scripts"))

from prontuario_verde_appointment_writer import (  # noqa: E402
    AppointmentWriteError,
    ProntuarioVerdeAppointmentWriter,
)


HASH = "a" * 64
NOW = datetime.now(timezone.utc)
OLD_START_DT = (NOW + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
OLD_END_DT = OLD_START_DT + timedelta(minutes=30)
START_DT = OLD_START_DT + timedelta(days=1)
END_DT = START_DT + timedelta(minutes=30)
START = START_DT.isoformat()
END = END_DT.isoformat()
OLD_START = OLD_START_DT.isoformat()
OLD_END = OLD_END_DT.isoformat()
CONFIG = {"enabled": True, "appointment_write_enabled": True,
          "clinic_id": "clinic", "source_clinic_hash": HASH}


def request(operation="book"):
    result = {
        "operation": operation, "request_id": "req-1",
        "patient_id": "30", "professional_id": "10", "unit_id": "20",
        "type_id": "40", "procedure_id": "50", "duration_min": 30,
        "requested_start": START, "requested_end": END,
        "clinic_id": "clinic", "source_clinic_hash": HASH,
    }
    if operation == "reschedule":
        result.update(appointment_id="60", expected_start=OLD_START, expected_end=OLD_END)
    return result


def match(**changes):
    row = {
        "appointment_id": "60", "patient_id": "30", "professional_id": "10",
        "unit_id": "20", "type_id": "40", "procedure_id": "50", "duration_min": 30,
        "start": START, "end": END, "status": "AGENDADO",
    }
    return {**row, **changes}


def old_evidence(**changes):
    values = {
        "old_appointment_id": "60", "old_patient_id": "30", "old_professional_id": "10",
        "old_unit_id": "20", "old_type_id": "40", "old_procedure_id": "50",
        "old_duration_min": 30, "old_start": OLD_START, "old_end": OLD_END,
        "old_appointment_active": False,
    }
    return {**values, **changes}


def prepared(operation="book", **changes):
    data = {
        "clinic_id": "clinic", "source_clinic_hash": HASH,
        "patient_id": "30", "professional_id": "10", "unit_id": "20",
        "type_id": "40", "procedure_id": "50", "duration_min": 30,
        "start": START, "end": END,
        "availability": {
            "status": "available", "professional_id": "10", "unit_id": "20",
            "source_clinic_hash": HASH, "start": START, "end": END,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
        "target_matches": [],
    }
    if operation == "reschedule":
        data["original_appointment"] = {
            "appointment_id": "60", "patient_id": "30", "professional_id": "10",
            "unit_id": "20", "type_id": "40", "procedure_id": "50", "duration_min": 30,
            "start": OLD_START, "end": OLD_END,
        }
    return {**data, **changes}


class FakePort:
    def __init__(self, *, preflight=None, outcome=None, submit_error=None):
        self.preflight = preflight
        self.outcome = outcome
        self.submit_error = submit_error
        self.calls = []

    def prepare(self, request):
        self.calls.append("prepare")
        return self.preflight if self.preflight is not None else prepared(request["operation"])

    def submit_once(self, request):
        self.calls.append("submit_once")
        if self.submit_error:
            raise self.submit_error

    def reconcile_after_save(self, request):
        self.calls.append("reconcile_after_save")
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome if self.outcome is not None else {
            "clinic_id": "clinic", "source_clinic_hash": HASH,
            "matches": [match()], "old_appointment_active": False,
        }


class AppointmentWriterTests(unittest.TestCase):
    def test_disabled_by_default_without_touching_port(self):
        port = FakePort()
        writer = ProntuarioVerdeAppointmentWriter(port, {"enabled": True})
        with self.assertRaisesRegex(AppointmentWriteError, "appointment_writes_disabled"):
            writer.book(request())
        self.assertEqual(port.calls, [])

    def test_requires_live_exact_slot_proof_before_submit(self):
        for proof in (
            {"status": "unknown"},
            {"status": "available", "professional_id": "10", "unit_id": "21",
             "source_clinic_hash": HASH, "start": START, "end": END,
             "checked_at": NOW.isoformat()},
            {"status": "available", "professional_id": "10", "unit_id": "20",
             "source_clinic_hash": HASH, "start": START, "end": END,
             "checked_at": (NOW - timedelta(minutes=2)).isoformat()},
        ):
            with self.subTest(proof=proof):
                port = FakePort(preflight=prepared(availability=proof))
                with self.assertRaises(AppointmentWriteError):
                    ProntuarioVerdeAppointmentWriter(port, CONFIG).book(request())
                self.assertEqual(port.calls, ["prepare"])

    def test_empty_duplicate_query_is_not_slot_proof_and_exact_target_duplicate_blocks(self):
        preflight = prepared(target_matches=[match()])
        port = FakePort(preflight=preflight)
        with self.assertRaisesRegex(AppointmentWriteError, "target_already_present"):
            ProntuarioVerdeAppointmentWriter(port, CONFIG).book(request())
        self.assertEqual(port.calls, ["prepare"])

    def test_slot_that_passes_before_preflight_is_rejected_if_start_has_passed(self):
        past_request = request()
        past_request.update(
            requested_start="2020-10-02T12:00:00+00:00",
            requested_end="2020-10-02T12:30:00+00:00",
        )
        past_preflight = prepared(
            start=past_request["requested_start"], end=past_request["requested_end"],
            availability={
                "status": "available", "professional_id": "10", "unit_id": "20",
                "source_clinic_hash": HASH, "start": past_request["requested_start"],
                "end": past_request["requested_end"], "checked_at": NOW.isoformat(),
            },
        )
        port = FakePort(preflight=past_preflight)
        with self.assertRaisesRegex(AppointmentWriteError, "requested_start_passed"):
            ProntuarioVerdeAppointmentWriter(port, CONFIG).book(past_request)
        self.assertEqual(port.calls, ["prepare"])

    def test_timeout_reconciles_once_and_only_exact_persisted_match_is_success(self):
        port = FakePort(submit_error=TimeoutError("hidden"))
        result = ProntuarioVerdeAppointmentWriter(port, CONFIG).book(request())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["appointment_id"], "60")
        self.assertEqual(port.calls, ["prepare", "submit_once", "reconcile_after_save"])

    def test_timeout_without_match_or_with_duplicates_is_needs_review_without_retry(self):
        for rows in ([], [match(), match(appointment_id="61")]):
            with self.subTest(rows=rows):
                port = FakePort(submit_error=TimeoutError("hidden"), outcome={
                    "clinic_id": "clinic", "source_clinic_hash": HASH, "matches": rows,
                })
                result = ProntuarioVerdeAppointmentWriter(port, CONFIG).book(request())
                self.assertEqual(result["status"], "needs_review")
                self.assertEqual(port.calls, ["prepare", "submit_once", "reconcile_after_save"])

    def test_wrong_patient_or_clinic_on_post_save_read_is_not_success(self):
        for outcome in (
            {"clinic_id": "other", "source_clinic_hash": HASH, "matches": [match()]},
            {"clinic_id": "clinic", "source_clinic_hash": HASH, "matches": [match(patient_id="31")]},
            {"clinic_id": "clinic", "source_clinic_hash": "b" * 64, "matches": [match()]},
        ):
            with self.subTest(outcome=outcome):
                result = ProntuarioVerdeAppointmentWriter(
                    FakePort(outcome=outcome), CONFIG,
                ).book(request())
                self.assertEqual(result["status"], "needs_review")

    def test_reschedule_requires_original_and_new_match_with_old_slot_cleared(self):
        request_value = request("reschedule")
        port = FakePort(outcome={
            "clinic_id": "clinic", "source_clinic_hash": HASH,
            "matches": [match(appointment_id="61")], **old_evidence(),
        })
        result = ProntuarioVerdeAppointmentWriter(port, CONFIG).reschedule(request_value)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["appointment_id"], "61")
        self.assertEqual(result["old_start"], OLD_START)
        self.assertIs(result["old_appointment_active"], False)

        port = FakePort(outcome={
            "clinic_id": "clinic", "source_clinic_hash": HASH,
            "matches": [match(appointment_id="61")],
            **old_evidence(old_appointment_active=True),
        })
        self.assertEqual(
            ProntuarioVerdeAppointmentWriter(port, CONFIG).reschedule(request_value)["status"],
            "needs_review",
        )

        port = FakePort(outcome={
            "clinic_id": "clinic", "source_clinic_hash": HASH,
            "matches": [match(appointment_id="61")],
            **old_evidence(old_procedure_id="51"),
        })
        self.assertEqual(
            ProntuarioVerdeAppointmentWriter(port, CONFIG).reschedule(request_value)["status"],
            "needs_review",
        )

    def test_mismatched_prepared_form_never_crosses_save_boundary(self):
        for changes in ({"patient_id": "999"}, {"procedure_id": "51"}):
            with self.subTest(changes=changes):
                port = FakePort(preflight=prepared(**changes))
                with self.assertRaisesRegex(AppointmentWriteError, "form_values_unverified"):
                    ProntuarioVerdeAppointmentWriter(port, CONFIG).book(request())
                self.assertEqual(port.calls, ["prepare"])

    def test_request_must_match_enabled_clinic_scope_before_browser_access(self):
        port = FakePort()
        with self.assertRaisesRegex(AppointmentWriteError, "clinic_mismatch"):
            ProntuarioVerdeAppointmentWriter(
                port, {**CONFIG, "source_clinic_hash": "b" * 64},
            ).book(request())
        self.assertEqual(port.calls, [])

    def test_reschedule_original_must_match_expected_old_appointment(self):
        for changes in ({"appointment_id": "61"}, {"procedure_id": "51"}):
            with self.subTest(changes=changes):
                original = {
                    "appointment_id": "60", "patient_id": "30", "professional_id": "10",
                    "unit_id": "20", "type_id": "40", "procedure_id": "50",
                    "duration_min": 30, "start": OLD_START, "end": OLD_END,
                }
                original.update(changes)
                port = FakePort(preflight=prepared("reschedule", original_appointment=original))
                with self.assertRaisesRegex(AppointmentWriteError, "original_appointment_changed"):
                    ProntuarioVerdeAppointmentWriter(port, CONFIG).reschedule(request("reschedule"))
                self.assertEqual(port.calls, ["prepare"])


if __name__ == "__main__":
    unittest.main()
