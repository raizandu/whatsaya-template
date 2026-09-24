"""Durable, no-replay queue for first-contact patient registration."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from patient_directory import normalize_phone


DEFAULT_ROOT = Path("/opt/data/prontuario_verde_registrations")
PENDING_TTL = timedelta(minutes=15)
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_DIRS = ("pending", "running", "results")
_TERMINAL = {"succeeded", "failed", "needs_review"}


class RegistrationStoreError(Exception):
    """Safe storage error with a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp(value: object) -> datetime | None:
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


def _safe_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    text = value.strip()
    if not text or len(text) > maximum:
        return None
    return text


def _normalized_name(value: object) -> str | None:
    text = _safe_text(value, 100)
    if text is None:
        return None
    text = " ".join(unicodedata.normalize("NFKC", text).split())
    if len(text) > 100 or not text or not any(char.isalnum() for char in text):
        return None
    return text


def _identity_key(clinic_id: str, source_clinic_hash: str, phone: str) -> str:
    material = "\0".join((clinic_id, source_clinic_hash.lower(), phone))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _ensure_dirs(root: Path) -> None:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        for name in _DIRS:
            path = root / name
            path.mkdir(mode=0o700, exist_ok=True)
            os.chmod(path, 0o700)
    except OSError:
        raise RegistrationStoreError("store_unavailable") from None


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    try:
        fd = os.open(root / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(fd, 0o600)
    except OSError:
        raise RegistrationStoreError("store_unavailable") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        raise RegistrationStoreError("store_unavailable") from None
    finally:
        os.close(fd)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except OSError:
        raise RegistrationStoreError("store_unavailable") from None
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_job(path: Path, expected_status: str | None = None) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        raise RegistrationStoreError("store_corrupt") from None
    if not isinstance(value, dict):
        raise RegistrationStoreError("store_corrupt")
    request_id = _request_id(value.get("request_id"))
    phone = normalize_phone(value.get("phone")) if isinstance(value.get("phone"), str) else None
    clinic_id = value.get("clinic_id")
    source_hash = value.get("source_clinic_hash")
    allowed_fields = {
        "request_id", "status", "code", "created_at", "updated_at", "chat_id",
        "name", "phone", "clinic_id", "source_clinic_hash", "source_message_id",
        "identity_key",
    }
    if "patient_id" in value:
        allowed_fields.add("patient_id")
    chat_id = value.get("chat_id")
    name = value.get("name")
    if (
        set(value) != allowed_fields
        or request_id != path.stem
        or phone is None
        or not isinstance(chat_id, str)
        or normalize_phone(chat_id) != phone
        or not isinstance(name, str)
        or _normalized_name(name) != name
        or not isinstance(clinic_id, str)
        or _safe_text(clinic_id, 120) != clinic_id
        or not isinstance(source_hash, str)
        or not _HASH.fullmatch(source_hash)
        or value.get("identity_key") != _identity_key(clinic_id, source_hash, phone)
        or value.get("status") not in {"pending", "running", *_TERMINAL}
        or (expected_status is not None and value.get("status") != expected_status)
        or (value.get("status") in {"pending", "running"} and value.get("code") is not None)
        or (value.get("status") in _TERMINAL and (
            not isinstance(value.get("code"), str) or not _SAFE_CODE.fullmatch(value["code"])
        ))
        or (value.get("status") in {"pending", "running"} and "patient_id" in value)
        or _timestamp(value.get("created_at")) is None
        or _timestamp(value.get("updated_at")) is None
        or not isinstance(value.get("source_message_id"), str)
        or _safe_text(value.get("source_message_id"), 256) != value.get("source_message_id")
        or (value.get("code") is not None and (
            not isinstance(value.get("code"), str) or not _SAFE_CODE.fullmatch(value["code"])
        ))
        or ("patient_id" in value and value.get("patient_id") is not None and (
            _safe_text(value.get("patient_id"), 120) != value.get("patient_id")
        ))
    ):
        raise RegistrationStoreError("store_corrupt")
    return value


def _all_jobs(root: Path) -> list[dict[str, Any]]:
    jobs = []
    for directory in _DIRS:
        for path in sorted((root / directory).glob("*.json")):
            job = _read_job(path, "pending" if directory == "pending" else "running" if directory == "running" else None)
            if directory == "results" and job["status"] not in _TERMINAL:
                raise RegistrationStoreError("store_corrupt")
            if job is not None:
                jobs.append(job)
    return jobs


def _public(job: dict[str, Any], *, include_patient_id: bool = False) -> dict[str, Any]:
    result = {
        "request_id": job["request_id"],
        "status": job["status"],
        "code": job.get("code"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "source_clinic_hash": job["source_clinic_hash"],
    }
    if include_patient_id and job.get("patient_id") is not None:
        result["patient_id"] = job["patient_id"]
    return result


def initialize(root: str | Path = DEFAULT_ROOT) -> None:
    """Create queue directories and quarantine running jobs left by a restart."""
    base = Path(root)
    _ensure_dirs(base)
    with _locked(base):
        running = base / "running"
        results = base / "results"
        for path in sorted(running.glob("*.json")):
            request_id = _request_id(path.stem)
            if request_id is None:
                path.unlink(missing_ok=True)
                continue
            existing = results / path.name
            if existing.exists():
                path.unlink(missing_ok=True)
                continue
            job = _read_job(path, "running")
            if job is None:
                path.unlink(missing_ok=True)
                continue
            job.update(status="needs_review", code="worker_restarted", updated_at=_now())
            _atomic_json(existing, job)
            path.unlink(missing_ok=True)


def enqueue_registration(
    root: str | Path = DEFAULT_ROOT,
    *,
    chat_id: str,
    name: str,
    clinic_id: str,
    source_clinic_hash: str,
    source_message_id: str,
) -> dict[str, Any]:
    """Queue one confirmed identity, deduplicating by clinic binding and phone."""
    canonical_phone = normalize_phone(chat_id)
    normalized_name = _normalized_name(name)
    clinic = _safe_text(clinic_id, 120)
    message_id = _safe_text(source_message_id, 256)
    if (
        canonical_phone is None
        or normalized_name is None
        or clinic is None
        or message_id is None
        or not isinstance(source_clinic_hash, str)
        or not _HASH.fullmatch(source_clinic_hash)
    ):
        raise ValueError("invalid registration request")
    base = Path(root)
    _ensure_dirs(base)
    source_hash = source_clinic_hash.lower()
    identity_key = _identity_key(clinic, source_hash, canonical_phone)
    with _locked(base):
        for existing in _all_jobs(base):
            if existing["identity_key"] == identity_key:
                return {**_public(existing), "deduplicated": True}

        request_id = str(uuid.uuid4())
        created_at = _now()
        job = {
            "request_id": request_id,
            "status": "pending",
            "code": None,
            "created_at": created_at,
            "updated_at": created_at,
            "chat_id": _safe_text(chat_id, 256),
            "name": normalized_name,
            "phone": canonical_phone,
            "clinic_id": clinic,
            "source_clinic_hash": source_hash,
            "source_message_id": message_id,
            "identity_key": identity_key,
        }
        if job["chat_id"] is None:
            raise ValueError("invalid registration request")
        _atomic_json(base / "pending" / f"{request_id}.json", job)
        return {**_public(job), "deduplicated": False}


def claim_next(root: str | Path = DEFAULT_ROOT) -> dict[str, Any] | None:
    """Atomically claim the oldest fresh request; expire old requests for review."""
    base = Path(root)
    _ensure_dirs(base)
    with _locked(base):
        pending = base / "pending"
        now = datetime.now(timezone.utc)
        ordered = []
        for path in pending.glob("*.json"):
            request_id = _request_id(path.stem)
            if request_id is None:
                path.unlink(missing_ok=True)
                continue
            job = _read_job(path, "pending")
            created = _timestamp(job.get("created_at")) if job else None
            if job is None or created is None or created > now or now - created > PENDING_TTL:
                if job is not None:
                    job.update(status="needs_review", code="expired_before_attempt", updated_at=_now())
                    _atomic_json(base / "results" / path.name, job)
                path.unlink(missing_ok=True)
                continue
            ordered.append((created, path, job))

        if not ordered:
            return None
        _, path, job = min(ordered, key=lambda item: (item[0], item[1].name))
        job.update(status="running", code=None, updated_at=_now())
        destination = base / "running" / path.name
        _atomic_json(destination, job)
        path.unlink(missing_ok=True)
        return dict(job)


def finish(
    root: str | Path,
    request_id: str,
    status: str,
    code: str,
    patient_id: str | None = None,
) -> dict[str, Any]:
    """Write a terminal worker result and remove the running request."""
    valid_id = _request_id(request_id)
    if valid_id is None or status not in _TERMINAL:
        raise ValueError("invalid registration result")
    if not isinstance(code, str) or not _SAFE_CODE.fullmatch(code):
        raise ValueError("invalid registration result")
    if patient_id is not None and _safe_text(patient_id, 120) is None:
        raise ValueError("invalid registration result")
    base = Path(root)
    _ensure_dirs(base)
    with _locked(base):
        request_path = base / "running" / f"{valid_id}.json"
        if not request_path.exists():
            existing = base / "results" / f"{valid_id}.json"
            if existing.exists():
                return _public(_read_job(existing), include_patient_id=True)
            raise ValueError("registration request is not running")
        job = _read_job(request_path, "running")
        if job is None:
            raise RegistrationStoreError("store_corrupt")
        job.update(status=status, code=code, updated_at=_now(), patient_id=patient_id)
        result_path = base / "results" / f"{valid_id}.json"
        _atomic_json(result_path, job)
        request_path.unlink(missing_ok=True)
        return _public(job, include_patient_id=True)


def get_for_contact(
    root: str | Path,
    clinic_id: str,
    phone: str,
) -> dict[str, Any] | None:
    """Return a minimal state for one contact, omitting names and patient IDs."""
    clinic = _safe_text(clinic_id, 120)
    canonical_phone = normalize_phone(phone)
    if clinic is None or canonical_phone is None:
        return None
    base = Path(root)
    if not base.exists():
        return None
    _ensure_dirs(base)
    with _locked(base):
        matches = [
            job for job in _all_jobs(base)
            if job["clinic_id"] == clinic and job["phone"] == canonical_phone
        ]
        if not matches:
            return None
        if len(matches) > 1:
            return {
                "status": "needs_review",
                "code": "source_clinic_ambiguous",
                "source_clinic_hash": None,
            }
        return _public(matches[0])
