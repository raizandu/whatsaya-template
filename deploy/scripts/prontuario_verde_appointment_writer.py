"""Fail-closed orchestration boundary for native PV appointment writes.

This module intentionally provides no Hermes/PV form driver. The form is
known to require APEX-specific date/time interactions, but the complete native
create/reschedule contract and all post-save identity fields are not validated
in this template worktree. The port protocol below is the only supported seam
until those details are verified. The feature is disabled unless both clinic
and appointment-write flags are explicitly enabled.

The writer never retries a submit. It always performs one fresh reconciliation
after the submit boundary, including after a timeout or other exception. The
queue's idempotency fingerprint is local deduplication only; PV receives no
idempotency key from this adapter.

Known native controls include `BT_NOVO`, the page-41 appointment form, and
`botaoAgendarPaciente`. The form requires APEX date/time interactions and a
blur-triggered duration reload. The specific reschedule flow and the complete
post-save identity/status fields still need native confirmation, so no concrete
Hermes browser driver is included.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Protocol


_ID = re.compile(r"[1-9][0-9]*\Z")
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")


class AppointmentWriteError(Exception):
    """A stable, sanitized adapter error code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class NativeAppointmentPort(Protocol):
    """Future native form driver; methods must return normalized safe fields only."""

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        """Open/fill without saving; include an independent live-slot proof.

        `target_matches` only prevents a duplicate appointment. It is not proof
        that the requested slot is free; `availability` must come from the
        separately validated Abertura de agenda source.
        """
        ...

    def submit_once(self, request: dict[str, Any]) -> None:
        """Cross the save boundary exactly once; never retry internally."""
        ...

    def reconcile_after_save(self, request: dict[str, Any]) -> dict[str, Any]:
        """Force a fresh PV read and return normalized exact candidates.

        Top-level output includes clinic_id, source_clinic_hash, and matches.
        For reschedule it also includes old_appointment_id and
        old patient/professional/unit/type/procedure, old duration and window,
        plus old_appointment_active, all checked against the requested original.
        Candidate rows include appointment_id, patient_id, professional_id,
        unit_id, type_id, procedure_id when requested, duration_min, start,
        end, and an active status.
        """
        ...


class ProntuarioVerdeAppointmentWriter:
    """Single-attempt write coordinator; a concrete PV browser driver is not wired."""

    def __init__(self, port: NativeAppointmentPort, config: dict[str, Any]):
        self.port = port
        self.config = config if isinstance(config, dict) else {}

    def book(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._write(request, "book")

    def reschedule(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._write(request, "reschedule")

    def _write(self, request: dict[str, Any], operation: str) -> dict[str, Any]:
        if not self._enabled():
            raise AppointmentWriteError("appointment_writes_disabled")
        request = _validate_request(request, operation)
        if (self.config.get("clinic_id") != request["clinic_id"]
                or self.config.get("source_clinic_hash") != request["source_clinic_hash"]):
            raise AppointmentWriteError("clinic_mismatch")
        try:
            prepared = self.port.prepare(request)
        except AppointmentWriteError:
            # Preserve the adapter's stable, sanitized preflight code for the
            # worker/operator; arbitrary driver exceptions remain generic.
            raise
        except Exception:
            raise AppointmentWriteError("preflight_unavailable") from None
        _validate_prepared(prepared, request)

        # If the PV state changed after the offer, don't create a duplicate or
        # replace the wrong original appointment.
        conflicts = prepared.get("target_matches")
        if not isinstance(conflicts, list):
            raise AppointmentWriteError("preflight_unverified")
        if conflicts:
            raise AppointmentWriteError("target_already_present")
        if operation == "reschedule":
            _validate_original(prepared.get("original_appointment"), request)
        requested_start = _timestamp(request["requested_start"])
        if requested_start <= datetime.now(requested_start.tzinfo):
            raise AppointmentWriteError("requested_start_passed")

        # The irreversible boundary is marked before calling the port, because
        # a timeout can occur after PV has accepted the request.
        submit_error = False
        try:
            self.port.submit_once(request)
        except Exception:
            submit_error = True

        try:
            reconciled = self.port.reconcile_after_save(request)
        except Exception:
            return _needs_review("post_save_read_failed")
        verified = _verified_result(reconciled, request)
        if verified is not None:
            return verified
        return _needs_review("submit_outcome_uncertain" if submit_error else "post_save_unverified")

    def _enabled(self) -> bool:
        return (self.config.get("enabled") is True
                and self.config.get("appointment_write_enabled") is True)


def _validate_request(value: object, operation: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("operation") != operation:
        raise AppointmentWriteError("invalid_request")
    required = (
        "request_id", "patient_id", "professional_id", "unit_id",
        "type_id", "duration_min", "requested_start", "requested_end", "clinic_id",
        "source_clinic_hash",
    )
    if any(key not in value for key in required):
        raise AppointmentWriteError("invalid_request")
    for key in ("patient_id", "professional_id", "unit_id", "type_id"):
        if not isinstance(value[key], (str, int)) or isinstance(value[key], bool) or not _ID.fullmatch(str(value[key])):
            raise AppointmentWriteError("invalid_request")
    if value.get("procedure_id") is not None:
        procedure_id = value["procedure_id"]
        if not isinstance(procedure_id, (str, int)) or isinstance(procedure_id, bool) or not _ID.fullmatch(str(procedure_id)):
            raise AppointmentWriteError("invalid_request")
    if (not isinstance(value["duration_min"], int) or isinstance(value["duration_min"], bool)
            or value["duration_min"] <= 0):
        raise AppointmentWriteError("invalid_request")
    if (not isinstance(value["clinic_id"], str) or not value["clinic_id"].strip()
            or not isinstance(value["source_clinic_hash"], str)
            or not _HASH.fullmatch(value["source_clinic_hash"])):
        raise AppointmentWriteError("invalid_request")
    if not isinstance(value["request_id"], str) or not value["request_id"].strip():
        raise AppointmentWriteError("invalid_request")
    start, end = _timestamp(value["requested_start"]), _timestamp(value["requested_end"])
    if end <= start or int((end - start).total_seconds()) != value["duration_min"] * 60:
        raise AppointmentWriteError("invalid_request")
    if start.date() != end.date():
        raise AppointmentWriteError("invalid_request")
    if operation == "reschedule":
        if not _ID.fullmatch(str(value.get("appointment_id", ""))):
            raise AppointmentWriteError("invalid_request")
        old_start, old_end = _timestamp(value.get("expected_start")), _timestamp(value.get("expected_end"))
        if (old_end <= old_start
                or int((old_end - old_start).total_seconds()) != value["duration_min"] * 60):
            raise AppointmentWriteError("invalid_request")
    return dict(value)


def _validate_prepared(prepared: object, request: dict[str, Any]) -> None:
    if not isinstance(prepared, dict):
        raise AppointmentWriteError("preflight_unverified")
    if (prepared.get("clinic_id") != request["clinic_id"]
            or prepared.get("source_clinic_hash") != request["source_clinic_hash"]):
        raise AppointmentWriteError("clinic_mismatch")
    _validate_slot_proof(prepared.get("availability"), request)
    fields = (
        ("patient_id", "patient_id"), ("professional_id", "professional_id"),
        ("unit_id", "unit_id"), ("type_id", "type_id"), ("duration_min", "duration_min"),
    )
    for observed, requested in fields:
        if str(prepared.get(observed)) != str(request[requested]):
            raise AppointmentWriteError("form_values_unverified")
    if (request.get("procedure_id") is not None
            and str(prepared.get("procedure_id")) != str(request["procedure_id"])):
        raise AppointmentWriteError("form_values_unverified")
    if not _same_time(prepared.get("start"), request["requested_start"]):
        raise AppointmentWriteError("form_values_unverified")
    if not _same_time(prepared.get("end"), request["requested_end"]):
        raise AppointmentWriteError("form_values_unverified")


def _validate_original(original: object, request: dict[str, Any]) -> None:
    if not isinstance(original, dict):
        raise AppointmentWriteError("original_appointment_unverified")
    if (str(original.get("appointment_id")) != str(request["appointment_id"])
            or str(original.get("patient_id")) != str(request["patient_id"])
            or str(original.get("professional_id")) != str(request["professional_id"])
            or str(original.get("unit_id")) != str(request["unit_id"])
            or str(original.get("type_id")) != str(request["type_id"])
            or original.get("duration_min") != request["duration_min"]
            or (request.get("procedure_id") is not None
                and str(original.get("procedure_id")) != str(request["procedure_id"]))
            or not _same_time(original.get("start"), request["expected_start"])
            or not _same_time(original.get("end"), request["expected_end"])):
        raise AppointmentWriteError("original_appointment_changed")


def _validate_slot_proof(proof: object, request: dict[str, Any]) -> None:
    if not isinstance(proof, dict) or proof.get("status") != "available":
        raise AppointmentWriteError("slot_not_verified_available")
    if (str(proof.get("professional_id")) != str(request["professional_id"])
            or str(proof.get("unit_id")) != str(request["unit_id"])
            or proof.get("source_clinic_hash") != request["source_clinic_hash"]
            or not _same_time(proof.get("start"), request["requested_start"])
            or not _same_time(proof.get("end"), request["requested_end"])):
        raise AppointmentWriteError("slot_proof_mismatch")
    try:
        checked_at = _timestamp(proof.get("checked_at")).astimezone(timezone.utc)
    except AppointmentWriteError:
        raise AppointmentWriteError("slot_proof_stale") from None
    age = datetime.now(timezone.utc) - checked_at
    if age.total_seconds() < 0 or age.total_seconds() > 60:
        raise AppointmentWriteError("slot_proof_stale")


def _verified_result(reconciled: object, request: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(reconciled, dict) or not isinstance(reconciled.get("matches"), list):
        return None
    matches = reconciled["matches"]
    if len(matches) != 1 or not isinstance(matches[0], dict):
        return None
    match = matches[0]
    if (reconciled.get("clinic_id") != request["clinic_id"]
            or reconciled.get("source_clinic_hash") != request["source_clinic_hash"]):
        return None
    if (str(match.get("patient_id")) != str(request["patient_id"])
            or str(match.get("professional_id")) != str(request["professional_id"])
            or str(match.get("unit_id")) != str(request["unit_id"])
            or str(match.get("type_id")) != str(request["type_id"])
            or str(match.get("status", "")).strip().upper() not in {"AGENDADO", "CONFIRMADO"}
            or match.get("duration_min") != request["duration_min"]
            or not _same_time(match.get("start"), request["requested_start"])
            or not _same_time(match.get("end"), request["requested_end"])):
        return None
    appointment_id = match.get("appointment_id")
    if not isinstance(appointment_id, (str, int)) or isinstance(appointment_id, bool) or not _ID.fullmatch(str(appointment_id)):
        return None
    procedure_id = request.get("procedure_id")
    if procedure_id is not None and str(match.get("procedure_id")) != str(procedure_id):
        return None
    result = {
        "status": "verified",
        "appointment_id": str(appointment_id),
        "patient_id": str(request["patient_id"]),
        "professional_id": str(request["professional_id"]),
        "unit_id": str(request["unit_id"]),
        "start": _timestamp(request["requested_start"]).isoformat(),
        "end": _timestamp(request["requested_end"]).isoformat(),
        "type_id": str(request["type_id"]),
        "duration_min": request["duration_min"],
        "clinic_id": request["clinic_id"],
        "source_clinic_hash": request["source_clinic_hash"].lower(),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    if procedure_id is not None:
        result["procedure_id"] = str(procedure_id)
    if request["operation"] == "reschedule":
        old_fields = (
            ("old_appointment_id", "appointment_id"),
            ("old_patient_id", "patient_id"),
            ("old_professional_id", "professional_id"),
            ("old_unit_id", "unit_id"),
            ("old_type_id", "type_id"),
        )
        if any(str(reconciled.get(observed)) != str(request[requested])
               for observed, requested in old_fields):
            return None
        if (reconciled.get("old_duration_min") != request["duration_min"]
                or reconciled.get("old_appointment_active") is not False
                or not _same_time(reconciled.get("old_start"), request["expected_start"])
                or not _same_time(reconciled.get("old_end"), request["expected_end"])):
            return None
        procedure_id = request.get("procedure_id")
        if procedure_id is not None and str(reconciled.get("old_procedure_id")) != str(procedure_id):
            return None
        result.update({
            "old_appointment_id": str(request["appointment_id"]),
            "old_patient_id": str(request["patient_id"]),
            "old_professional_id": str(request["professional_id"]),
            "old_unit_id": str(request["unit_id"]),
            "old_type_id": str(request["type_id"]),
            "old_duration_min": request["duration_min"],
            "old_start": _timestamp(request["expected_start"]).isoformat(),
            "old_end": _timestamp(request["expected_end"]).isoformat(),
            "old_appointment_active": False,
        })
        if procedure_id is not None:
            result["old_procedure_id"] = str(procedure_id)
    return result


def _needs_review(code: str) -> dict[str, str]:
    return {"status": "needs_review", "code": code}


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise AppointmentWriteError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AppointmentWriteError("invalid_timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AppointmentWriteError("timezone_required")
    return parsed


def _same_time(left: object, right: object) -> bool:
    try:
        return _timestamp(left) == _timestamp(right)
    except AppointmentWriteError:
        return False
