"""Durable, fail-closed spool for confirmed PV booking and reschedule jobs.

This module owns request persistence and lifecycle state only. A browser worker
must recheck live availability and the original appointment before writing.
It must never retry an operation after a possibly submitted write.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path("/opt/data/prontuario_verde_booking")
MAX_AGE = timedelta(minutes=15)
MAX_OFFER_TTL = timedelta(minutes=10)
MAX_ORIGINAL_VERIFICATION_AGE = timedelta(minutes=5)
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_POSITIVE_ID = re.compile(r"[0-9]{1,32}\Z")
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{1,256}\Z")
_POLICY_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_DIRS = ("pending", "running", "results")
_COMMON_FIELDS = {
    "operation", "idempotency_key", "chat_id", "patient_id", "professional_id",
    "professional_key", "appointment_type", "policy_context", "unit_id", "type_id",
    "procedure_id", "duration_min", "requested_start",
    "requested_end", "clinic_id", "source_clinic_hash", "confirmation", "created_at",
}
_RESCHEDULE_FIELDS = {"appointment_id", "expected_start", "expected_end", "original_verified_at"}
_CONFIRMATION_FIELDS = {
    "chat_id", "message_id", "offer_id", "slot_id", "requested_start", "requested_end",
    "offer_expires_at", "confirmed_at", "explicit", "kind",
}
_TERMINAL = {"succeeded", "failed", "needs_review"}


def initialize(root: str | Path = DEFAULT_ROOT) -> None:
    """Create the spool and mark interrupted running writes for review."""
    base = Path(root)
    base.mkdir(mode=0o2770, parents=True, exist_ok=True)
    os.chmod(base, 0o2770)
    for name in _DIRS:
        directory = base / name
        directory.mkdir(mode=0o2770, exist_ok=True)
        os.chmod(directory, 0o2770)
    with _locked(base):
        running = base / "running"
        for path in sorted(running.glob("*.json")):
            request_id = _request_id(path.stem)
            if request_id is None:
                path.unlink(missing_ok=True)
                continue
            existing = _read_json(base / "results" / f"{request_id}.json")
            if existing:
                path.unlink(missing_ok=True)
                continue
            payload = _read_json(path)
            _write_result(base, request_id, "needs_review", "worker_restarted", payload)
            path.unlink(missing_ok=True)


def enqueue_booking(root: str | Path, request_payload: dict) -> dict:
    """Validate confirmation evidence and atomically enqueue a new booking."""
    return _enqueue(root, request_payload, "book")


def enqueue_reschedule(root: str | Path, request_payload: dict) -> dict:
    """Validate confirmation and verified original details before enqueueing."""
    return _enqueue(root, request_payload, "reschedule")


def _enqueue(root: str | Path, value: dict, operation: str) -> dict:
    payload = _validate_payload(value, operation)
    idempotency_hash = _hash(payload["idempotency_key"])
    fingerprint = _fingerprint(payload)
    payload["idempotency_hash"] = idempotency_hash
    payload["request_fingerprint"] = fingerprint
    payload.pop("idempotency_key")
    base = Path(root)
    with _locked(base):
        for directory_name in ("pending", "running", "results"):
            for path in sorted((base / directory_name).glob("*.json")):
                item = _read_json(path)
                if not _valid_index_record(item):
                    raise ValueError("queue history requires review")
                if directory_name == "results":
                    if item.get("status") not in _TERMINAL:
                        raise ValueError("queue history requires review")
                elif not _valid_stored_request(item):
                    raise ValueError("queue history requires review")
                if item["idempotency_hash"] != idempotency_hash:
                    continue
                if item["request_fingerprint"] != fingerprint:
                    raise ValueError("idempotency key conflict")
                request_id = _request_id(path.stem)
                if request_id is None:
                    raise ValueError("queue history requires review")
                if directory_name == "results" and item.get("status") not in _TERMINAL:
                    raise ValueError("queue history requires review")
                if directory_name != "results" and item.get("operation") not in {"book", "reschedule"}:
                    raise ValueError("queue history requires review")
                status = item.get("status") if directory_name == "results" else directory_name
                return {"request_id": request_id, "status": status, "deduplicated": True}

        request_id = str(uuid.uuid4())
        _atomic_json(base / "pending" / f"{request_id}.json", payload, 0o640)
        return {"request_id": request_id, "status": "pending", "deduplicated": False}


def claim_next(root: str | Path) -> dict | None:
    """Claim the oldest fresh request; expired offers never reach the worker."""
    base = Path(root)
    with _locked(base):
        pending = base / "pending"
        running = base / "running"
        for path in sorted(pending.glob("*.json"), key=lambda item: item.name):
            request_id = _request_id(path.stem)
            if request_id is None:
                path.unlink(missing_ok=True)
                continue
            payload = _read_json(path)
            now = datetime.now(timezone.utc)
            created = _parse_timestamp(payload.get("created_at")) if payload else None
            expires = _parse_timestamp((payload.get("confirmation") or {}).get("offer_expires_at")) if payload else None
            if payload is None or created is None:
                _write_result(base, request_id, "needs_review", "invalid_request", payload)
                path.unlink(missing_ok=True)
                continue
            if created > now or now - created > MAX_AGE:
                _write_result(base, request_id, "needs_review", "expired_before_attempt", payload)
                path.unlink(missing_ok=True)
                continue
            if expires is None or expires <= now:
                _write_result(base, request_id, "needs_review", "offer_expired", payload)
                path.unlink(missing_ok=True)
                continue
            requested_start = _parse_timestamp(payload.get("requested_start"))
            if requested_start is None or requested_start <= now:
                _write_result(base, request_id, "needs_review", "slot_elapsed_before_attempt", payload)
                path.unlink(missing_ok=True)
                continue
            if not _valid_stored_request(payload):
                _write_result(base, request_id, "needs_review", "invalid_request", payload)
                path.unlink(missing_ok=True)
                continue
            destination = running / path.name
            os.replace(path, destination)
            return {"request_id": request_id, **payload}
    return None


def finish(
    root: str | Path,
    request_id: str,
    status: str,
    code: str,
    verified_result: dict | None = None,
) -> dict:
    """Finish a claimed job; success requires exact live-verification proof.

    A malformed or mismatched success report is stored as ``needs_review``.
    An interrupted/uncertain write is terminal for this request and is never
    returned to ``pending``.
    """
    valid_id = _request_id(request_id)
    if valid_id is None:
        raise ValueError("invalid request id")
    if status not in _TERMINAL:
        raise ValueError("invalid result status")
    if not isinstance(code, str) or not _SAFE_CODE.fullmatch(code):
        raise ValueError("invalid result code")

    base = Path(root)
    with _locked(base):
        request_path = base / "running" / f"{valid_id}.json"
        payload = _read_json(request_path)
        if payload is None:
            existing = _read_json(base / "results" / f"{valid_id}.json")
            if existing:
                return _public_result(valid_id, existing)
            raise ValueError("request is not running")
        final_status, final_code, proof = status, code, None
        if status == "succeeded":
            proof = _verified_result(payload, verified_result)
            if proof is None:
                final_status, final_code = "needs_review", "verification_mismatch"
        result = _write_result(base, valid_id, final_status, final_code, payload, proof)
        request_path.unlink(missing_ok=True)
        return _public_result(valid_id, result)


def reconcile(root: str | Path, request_id: str, evidence: dict) -> dict:
    """Resolve a ``needs_review`` result from a fresh authoritative check.

    A verified booking becomes succeeded. A verified absence becomes failed
    without retrying. Anything ambiguous remains needs_review.
    """
    valid_id = _request_id(request_id)
    if valid_id is None:
        raise ValueError("invalid request id")
    base = Path(root)
    with _locked(base):
        if (base / "running" / f"{valid_id}.json").exists():
            raise ValueError("request is still running")
        path = base / "results" / f"{valid_id}.json"
        existing = _read_json(path)
        if not existing:
            raise ValueError("request result not found")
        if existing.get("status") != "needs_review":
            return _public_result(valid_id, existing)
        payload = existing.get("reconciliation_request")
        if not isinstance(payload, dict):
            return _public_result(valid_id, existing)

        proof = _verified_result(payload, evidence)
        if proof is not None:
            result = _write_result(base, valid_id, "succeeded", "reconciled_verified", payload, proof)
            return _public_result(valid_id, result)
        if _verified_absence(payload, evidence):
            result = _write_result(base, valid_id, "failed", "verified_not_booked", payload)
            return _public_result(valid_id, result)
        return _public_result(valid_id, existing)


def get_result(root: str | Path, request_id: str) -> dict | None:
    """Return sanitized lifecycle state, never the queued patient/chat data."""
    valid_id = _request_id(request_id)
    if valid_id is None:
        return None
    base = Path(root)
    with _locked(base):
        result = _read_json(base / "results" / f"{valid_id}.json")
        if result:
            return _public_result(valid_id, result)
        for directory_name in ("running", "pending"):
            payload = _read_json(base / directory_name / f"{valid_id}.json")
            if payload:
                return {
                    "request_id": valid_id,
                    "status": directory_name,
                    "code": None,
                    "updated_at": payload.get("created_at"),
                }
    return None


def _validate_payload(value: object, operation: str, *, now: datetime | None = None) -> dict:
    expected = (_COMMON_FIELDS - {"procedure_id"}) | (_RESCHEDULE_FIELDS if operation == "reschedule" else set())
    if (
        not isinstance(value, dict)
        or set(value) not in (expected, expected | {"procedure_id"})
        or value.get("operation") != operation
    ):
        raise ValueError("invalid booking request")
    payload: dict[str, Any] = {}
    for field in _COMMON_FIELDS - {"confirmation", "duration_min", "policy_context"}:
        item = value.get(field)
        if field == "procedure_id" and item in (None, ""):
            payload[field] = None
            continue
        if field in {"patient_id", "professional_id", "unit_id", "type_id", "procedure_id"}:
            normalized_id = _positive_id(item)
            if normalized_id is None:
                raise ValueError("invalid booking request")
            payload[field] = normalized_id
            continue
        if not isinstance(item, str) or not item.strip() or len(item) > 256:
            raise ValueError("invalid booking request")
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError("invalid booking request")
        payload[field] = item.strip()
    for field in ("professional_key", "appointment_type"):
        if not _POLICY_KEY.fullmatch(payload[field]):
            raise ValueError("invalid booking policy identity")
    context = value.get("policy_context")
    context_fields = {"established_patient", "in_treatment", "no_added_procedure", "chart_verified"}
    if (not isinstance(context, dict) or set(context) != context_fields
            or any(not isinstance(context[field], bool) for field in context_fields)):
        raise ValueError("invalid booking policy context")
    payload["policy_context"] = dict(context)
    if not _IDEMPOTENCY_KEY.fullmatch(payload["idempotency_key"]):
        raise ValueError("invalid booking request")
    if not _HASH.fullmatch(payload["source_clinic_hash"]):
        raise ValueError("invalid booking request")
    duration = value.get("duration_min")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 1440:
        raise ValueError("invalid booking request")
    payload["duration_min"] = duration
    start = _parse_timestamp(value.get("requested_start"))
    end = _parse_timestamp(value.get("requested_end"))
    created = _parse_timestamp(value.get("created_at"))
    now = now or datetime.now(timezone.utc)
    if start is None or end is None or end <= start or start <= now or int((end - start).total_seconds()) != duration * 60:
        raise ValueError("invalid booking request")
    if created is None or created > now or now - created > MAX_AGE:
        raise ValueError("invalid booking request")
    payload["confirmation"] = _validate_confirmation(
        value.get("confirmation"),
        chat_id=payload["chat_id"],
        start=value["requested_start"],
        end=value["requested_end"],
        created=created,
        now=now,
    )
    if operation == "reschedule":
        for field in _RESCHEDULE_FIELDS:
            item = value.get(field)
            if field == "appointment_id":
                normalized_id = _positive_id(item)
                if normalized_id is None:
                    raise ValueError("invalid reschedule request")
                payload[field] = normalized_id
                continue
            if not isinstance(item, str) or not item.strip() or len(item) > 256:
                raise ValueError("invalid reschedule request")
            if any(ord(char) < 32 or ord(char) == 127 for char in item):
                raise ValueError("invalid reschedule request")
            payload[field] = item.strip()
        old_start = _parse_timestamp(payload["expected_start"])
        old_end = _parse_timestamp(payload["expected_end"])
        verified_at = _parse_timestamp(payload["original_verified_at"])
        if (
            old_start is None or old_end is None or old_end <= old_start
            or int((old_end - old_start).total_seconds()) != duration * 60
        ):
            raise ValueError("invalid reschedule request")
        confirmed_at = payload["confirmation"]["confirmed_at_dt"]
        if (
            verified_at is None or verified_at > confirmed_at
            or confirmed_at - verified_at > MAX_ORIGINAL_VERIFICATION_AGE
        ):
            raise ValueError("invalid reschedule request")
        payload["original_verified_at"] = _iso(verified_at)
        payload["expected_start"] = _iso(old_start)
        payload["expected_end"] = _iso(old_end)
        if _same_time(old_start, start) and _same_time(old_end, end):
            raise ValueError("reschedule target must differ from original")
    payload["requested_start"] = _iso(start)
    payload["requested_end"] = _iso(end)
    payload["created_at"] = _iso(created)
    # Do not persist free-form confirmation text; only the explicit assertion
    # and its message/offer/slot binding are stored.
    payload["confirmation"].pop("confirmed_at_dt")
    return payload


def _validate_confirmation(value: object, *, chat_id: str, start: str, end: str, created: datetime, now: datetime) -> dict:
    if not isinstance(value, dict) or set(value) != _CONFIRMATION_FIELDS:
        raise ValueError("invalid confirmation evidence")
    for field in ("chat_id", "message_id", "offer_id", "slot_id", "requested_start", "requested_end", "kind"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip() or len(item) > 256:
            raise ValueError("invalid confirmation evidence")
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError("invalid confirmation evidence")
    if value["chat_id"].strip() != chat_id:
        raise ValueError("confirmation chat mismatch")
    if value["requested_start"].strip() != start or value["requested_end"].strip() != end:
        raise ValueError("confirmation slot mismatch")
    if value["explicit"] is not True or value["kind"] != "offer_acceptance":
        raise ValueError("explicit offer confirmation required")
    confirmed = _parse_timestamp(value.get("confirmed_at"))
    expires = _parse_timestamp(value.get("offer_expires_at"))
    requested_start = _parse_timestamp(start)
    requested_end = _parse_timestamp(end)
    if (
        confirmed is None or expires is None or requested_start is None or requested_end is None
        or confirmed > expires or expires <= now or expires - confirmed > MAX_OFFER_TTL
        or confirmed > now or confirmed > created or requested_end <= requested_start
    ):
        raise ValueError("confirmation expired or invalid")
    return {
        "chat_id": value["chat_id"].strip(),
        "message_id": value["message_id"].strip(),
        "offer_id": value["offer_id"].strip(),
        "slot_id": value["slot_id"].strip(),
        "requested_start": _iso(requested_start),
        "requested_end": _iso(requested_end),
        "offer_expires_at": _iso(expires),
        "confirmed_at": _iso(confirmed),
        "confirmed_at_dt": confirmed,
        "explicit": True,
        "kind": "offer_acceptance",
    }


def _verified_result(payload: dict, value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    required = {
        "status", "appointment_id", "patient_id", "professional_id", "unit_id", "type_id",
        "duration_min", "start", "end", "verified_at", "clinic_id", "source_clinic_hash",
    }
    if payload["operation"] == "reschedule":
        required |= {
            "old_appointment_id", "old_patient_id", "old_professional_id", "old_unit_id",
            "old_type_id", "old_duration_min", "old_start", "old_end", "old_appointment_active",
        }
        if payload.get("procedure_id") is not None:
            required.add("old_procedure_id")
    if not required.issubset(value) or value.get("status") != "verified":
        return None
    id_fields = ("appointment_id", "patient_id", "professional_id", "unit_id", "type_id")
    normalized_ids = {field: _positive_id(value.get(field)) for field in id_fields}
    if any(normalized_ids[field] is None for field in id_fields):
        return None
    text_fields = ("clinic_id", "source_clinic_hash")
    if any(not isinstance(value.get(field), str) or not value[field].strip() for field in text_fields):
        return None
    if normalized_ids["patient_id"] != payload["patient_id"] or normalized_ids["professional_id"] != payload["professional_id"]:
        return None
    if normalized_ids["unit_id"] != payload["unit_id"] or normalized_ids["type_id"] != payload["type_id"]:
        return None
    if payload.get("procedure_id") is not None and _positive_id(value.get("procedure_id")) != payload["procedure_id"]:
        return None
    if value["clinic_id"] != payload["clinic_id"] or value["source_clinic_hash"] != payload["source_clinic_hash"]:
        return None
    duration = value.get("duration_min")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration != payload["duration_min"]:
        return None
    start, end, verified_at = (_parse_timestamp(value.get(key)) for key in ("start", "end", "verified_at"))
    requested_start = _parse_timestamp(payload["requested_start"])
    requested_end = _parse_timestamp(payload["requested_end"])
    created = _parse_timestamp(payload["created_at"])
    if (
        start is None or end is None or verified_at is None or requested_start is None
        or requested_end is None or created is None
        or not _same_time(start, requested_start) or not _same_time(end, requested_end)
        or verified_at < created or verified_at > datetime.now(timezone.utc) or end <= start
    ):
        return None
    if payload["operation"] == "reschedule":
        if not _old_appointment_matches(payload, value, active=False):
            return None
    proof = {
        "appointment_id": normalized_ids["appointment_id"],
        "start": _iso(start),
        "end": _iso(end),
        "professional_id": normalized_ids["professional_id"],
        "unit_id": normalized_ids["unit_id"],
        "type_id": normalized_ids["type_id"],
        "duration_min": duration,
        "verified_at": _iso(verified_at),
    }
    if payload["operation"] == "reschedule":
        old_start = _parse_timestamp(value["old_start"])
        old_end = _parse_timestamp(value["old_end"])
        proof["old_start"] = _iso(old_start)
        proof["old_end"] = _iso(old_end)
        proof["old_appointment_id"] = payload["appointment_id"]
        proof["old_patient_id"] = payload["patient_id"]
        proof["old_professional_id"] = payload["professional_id"]
        proof["old_unit_id"] = payload["unit_id"]
        proof["old_type_id"] = payload["type_id"]
        proof["old_duration_min"] = payload["duration_min"]
        if payload.get("procedure_id") is not None:
            proof["old_procedure_id"] = payload["procedure_id"]
        proof["old_appointment_active"] = False
    return proof


def _verified_absence(payload: dict, value: object) -> bool:
    if not isinstance(value, dict) or value.get("status") != "absent":
        return False
    expected = {
        "patient_id": payload["patient_id"],
        "professional_id": payload["professional_id"],
        "unit_id": payload["unit_id"],
        "type_id": payload["type_id"],
        "clinic_id": payload["clinic_id"],
        "source_clinic_hash": payload["source_clinic_hash"],
        "requested_start": payload["requested_start"],
        "requested_end": payload["requested_end"],
    }
    if payload.get("procedure_id") is not None:
        expected["procedure_id"] = payload["procedure_id"]
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        return False
    if payload["operation"] == "reschedule":
        if not _old_appointment_matches(payload, value, active=True):
            return False
    checked = _parse_timestamp(value.get("checked_at"))
    created = _parse_timestamp(payload.get("created_at"))
    return checked is not None and created is not None and created <= checked <= datetime.now(timezone.utc)


def _old_appointment_matches(payload: dict, value: dict, *, active: bool) -> bool:
    if value.get("old_appointment_active") is not active:
        return False
    expected_ids = {
        "old_appointment_id": payload["appointment_id"],
        "old_patient_id": payload["patient_id"],
        "old_professional_id": payload["professional_id"],
        "old_unit_id": payload["unit_id"],
        "old_type_id": payload["type_id"],
    }
    if payload.get("procedure_id") is not None:
        expected_ids["old_procedure_id"] = payload["procedure_id"]
    if any(_positive_id(value.get(field)) != expected for field, expected in expected_ids.items()):
        return False
    if value.get("old_duration_min") != payload["duration_min"]:
        return False
    old_start, old_end = (_parse_timestamp(value.get(key)) for key in ("old_start", "old_end"))
    expected_start = _parse_timestamp(payload.get("expected_start"))
    expected_end = _parse_timestamp(payload.get("expected_end"))
    return bool(
        old_start is not None and old_end is not None and expected_start is not None and expected_end is not None
        and _same_time(old_start, expected_start) and _same_time(old_end, expected_end)
    )


def _fingerprint(payload: dict) -> str:
    excluded = {"created_at", "idempotency_key", "idempotency_hash", "request_fingerprint"}
    value = {key: item for key, item in payload.items() if key not in excluded}
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_id(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if not _POSITIVE_ID.fullmatch(text):
        return None
    number = int(text)
    return str(number) if number > 0 else None


def _valid_index_record(value: dict | None) -> bool:
    return bool(
        isinstance(value, dict)
        and value.get("operation") in {"book", "reschedule"}
        and isinstance(value.get("idempotency_hash"), str)
        and _HASH.fullmatch(value["idempotency_hash"])
        and isinstance(value.get("request_fingerprint"), str)
        and _HASH.fullmatch(value["request_fingerprint"])
    )


def _valid_stored_request(payload: dict) -> bool:
    if not _valid_index_record(payload):
        return False
    operation = payload["operation"]
    stored = {key: item for key, item in payload.items() if key not in {"idempotency_hash", "request_fingerprint"}}
    stored["idempotency_key"] = "stored-request-key"
    created = _parse_timestamp(stored.get("created_at"))
    if created is None:
        return False
    try:
        normalized = _validate_payload(stored, operation, now=created)
    except (TypeError, ValueError):
        return False
    return _fingerprint(normalized) == payload["request_fingerprint"]


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _same_time(left: datetime, right: datetime) -> bool:
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


@contextmanager
def _locked(base: Path):
    fd = os.open(base / ".lock", os.O_CREAT | os.O_RDWR, 0o660)
    try:
        os.fchmod(fd, 0o660)
        with os.fdopen(fd, "r+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_json(path: Path, value: dict, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), mode)
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_result(
    base: Path,
    request_id: str,
    status: str,
    code: str,
    payload: dict | None,
    proof: dict | None = None,
) -> dict:
    result = {
        "request_id": request_id,
        "status": status,
        "code": code,
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    if payload:
        result["idempotency_hash"] = payload.get("idempotency_hash")
        result["request_fingerprint"] = payload.get("request_fingerprint")
        result["operation"] = payload.get("operation")
    if proof:
        result["appointment"] = proof
    if status == "needs_review" and payload:
        result["reconciliation_request"] = payload
    _atomic_json(base / "results" / f"{request_id}.json", result, 0o640)
    return result


def _public_result(request_id: str, result: dict) -> dict:
    public = {
        "request_id": request_id,
        "status": result.get("status"),
        "code": result.get("code"),
        "updated_at": result.get("updated_at"),
    }
    if result.get("status") == "succeeded" and isinstance(result.get("appointment"), dict):
        proof = result["appointment"]
        public["appointment"] = {key: proof[key] for key in ("start", "end", "professional_id", "unit_id", "type_id", "duration_min")}
    return public
