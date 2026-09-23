"""Filesystem spool for authenticated panel cancellation requests."""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_ROOT = Path("/opt/data/prontuario_verde_actions")
MAX_AGE = timedelta(minutes=15)
REQUEST_FIELDS = (
    "operation",
    "chat_id",
    "appointment_id",
    "patient_id",
    "professional_id",
    "expected_start",
    "expected_end",
    "clinic_id",
    "source_clinic_hash",
    "requested_by",
    "created_at",
)
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_DIRS = ("pending", "running", "results")


def initialize(root: str | Path = DEFAULT_ROOT) -> None:
    """Create the shared spool and quarantine jobs left running after a crash."""
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


def enqueue_cancel(root: str | Path, request_payload: dict) -> dict:
    """Atomically enqueue a validated cancellation or return its active duplicate."""
    base = Path(root)
    payload = _validate_payload(request_payload)
    with _locked(base):
        for directory_name in ("pending", "running"):
            for path in sorted((base / directory_name).glob("*.json")):
                active = _read_json(path)
                request_id = _request_id(path.stem)
                if directory_name == "pending" and request_id is not None and active:
                    created = _parse_timestamp(active.get("created_at"))
                    now = datetime.now(timezone.utc)
                    if created is None or created > now or now - created > MAX_AGE:
                        code = "invalid_request" if created is None else "expired_before_attempt"
                        _write_result(base, request_id, "needs_review", code, active)
                        path.unlink(missing_ok=True)
                        continue
                if active and active.get("appointment_id") == payload["appointment_id"]:
                    if request_id is not None:
                        return {
                            "request_id": request_id,
                            "status": directory_name,
                            "deduplicated": True,
                        }

        request_id = str(uuid.uuid4())
        _atomic_json(base / "pending" / f"{request_id}.json", payload, 0o640)
        return {"request_id": request_id, "status": "pending", "deduplicated": False}


def get_result(root: str | Path, request_id: str) -> dict | None:
    """Return the public lifecycle state without exposing request data."""
    valid_id = _request_id(request_id)
    if valid_id is None:
        return None
    base = Path(root)
    with _locked(base):
        result = _read_json(base / "results" / f"{valid_id}.json")
        if result:
            return _public_result(valid_id, result)
        for directory_name, status in (("running", "running"), ("pending", "pending")):
            payload = _read_json(base / directory_name / f"{valid_id}.json")
            if payload:
                return {
                    "request_id": valid_id,
                    "status": status,
                    "code": None,
                    "updated_at": payload.get("created_at"),
                }
    return None


def claim_next(root: str | Path) -> dict | None:
    """Move the oldest fresh pending request into running and return its payload."""
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
            created = _parse_timestamp(payload.get("created_at")) if payload else None
            now = datetime.now(timezone.utc)
            if payload is None or created is None:
                _write_result(base, request_id, "needs_review", "invalid_request", payload)
                path.unlink(missing_ok=True)
                continue
            if created > now or now - created > MAX_AGE:
                _write_result(base, request_id, "needs_review", "expired_before_attempt", payload)
                path.unlink(missing_ok=True)
                continue
            destination = running / path.name
            os.replace(path, destination)
            return {"request_id": request_id, **payload}
    return None


def finish(root: str | Path, request_id: str, status: str, code: str) -> dict:
    """Store a sanitized terminal outcome and remove the matching running item."""
    valid_id = _request_id(request_id)
    if valid_id is None:
        raise ValueError("invalid request id")
    if status not in {"succeeded", "failed", "needs_review"}:
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
                request_path.unlink(missing_ok=True)
                return _public_result(valid_id, existing)
            raise ValueError("request is not running")
        result = _write_result(base, valid_id, status, code, payload)
        request_path.unlink(missing_ok=True)
        return _public_result(valid_id, result)


@contextmanager
def _locked(base: Path):
    lock_path = base / ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o660)
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


def _validate_payload(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(REQUEST_FIELDS):
        raise ValueError("invalid cancellation request")
    if value.get("operation") != "cancel":
        raise ValueError("invalid cancellation request")
    payload = {}
    for field in REQUEST_FIELDS:
        item = value[field]
        if not isinstance(item, str) or not item.strip() or len(item) > 256:
            raise ValueError("invalid cancellation request")
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError("invalid cancellation request")
        payload[field] = item.strip()
    if not _HASH.fullmatch(payload["source_clinic_hash"]):
        raise ValueError("invalid cancellation request")
    if _parse_timestamp(payload["created_at"]) is None:
        raise ValueError("invalid cancellation request")
    for field in ("expected_start", "expected_end"):
        if _parse_timestamp(payload[field]) is None:
            raise ValueError("invalid cancellation request")
    return payload


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


def _request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


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
) -> dict:
    result = {
        "request_id": request_id,
        "status": status,
        "code": code,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if payload:
        result["created_at"] = payload.get("created_at")
        result["appointment_id"] = payload.get("appointment_id")
    _atomic_json(base / "results" / f"{request_id}.json", result, 0o640)
    return result


def _public_result(request_id: str, result: dict) -> dict:
    return {
        "request_id": request_id,
        "status": result.get("status"),
        "code": result.get("code"),
        "updated_at": result.get("updated_at"),
    }
