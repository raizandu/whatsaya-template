"""Guarded orchestration for automatic Prontuário Verde patient registration."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from patient_directory import normalize_phone


_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


class RegistrationError(Exception):
    """A stable, safe error code for callers; never includes patient data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _normalized_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = " ".join(unicodedata.normalize("NFKC", value).split())
    if (
        not name
        or len(name) > 100
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or not any(char.isalnum() for char in name)
    ):
        return None
    return name.lower()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".registration-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_journal(
    path: Path, clinic: str, phone: str, source_clinic_hash: str,
) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > 4096:
            raise RegistrationError("needs_review")
        journal = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError, TypeError):
        raise RegistrationError("needs_review") from None
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version") != 1
        or journal.get("clinic_id") != clinic
        or journal.get("phone") != phone
        or journal.get("source_clinic_hash") != source_clinic_hash.lower()
        or journal.get("state") not in ("submitted", "created")
        or not isinstance(journal.get("patient_id"), str)
    ):
        raise RegistrationError("needs_review")
    return journal


def _lookup(adapter: Any, phone: str, name: str) -> tuple[list[dict[str, Any]], int]:
    try:
        result = adapter.lookup(phone, name)
    except Exception:
        raise RegistrationError("lookup_failed") from None
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("matches"), list)
        or isinstance(result.get("name_candidates"), bool)
        or not isinstance(result.get("name_candidates"), int)
        or result["name_candidates"] < 0
    ):
        raise RegistrationError("invalid_adapter_response")
    matches = result["matches"]
    for match in matches:
        if not isinstance(match, dict):
            raise RegistrationError("invalid_adapter_response")
        patient_id, candidate_name, phones = match.get("id"), match.get("name"), match.get("phones")
        if (
            not isinstance(patient_id, str)
            or not patient_id.strip()
            or not isinstance(candidate_name, str)
            or not isinstance(phones, list)
            or any(not isinstance(item, str) or normalize_phone(item) is None for item in phones)
        ):
            raise RegistrationError("invalid_adapter_response")
    return matches, result["name_candidates"]


def _patient_result(match: dict[str, Any], phone: str, status: str) -> dict[str, Any]:
    result = {"status": status, "patient_id": match["id"].strip(), "phone": phone}
    record_number = match.get("record_number")
    if isinstance(record_number, str) and record_number.strip():
        result["record_number"] = record_number.strip()
    return result


def _exact_phone(matches: list[dict[str, Any]], phone: str) -> list[dict[str, Any]]:
    return [match for match in matches if phone in {normalize_phone(item) for item in match["phones"]}]


def ensure_patient(
    adapter: Any,
    *,
    name: str,
    phone: str,
    clinic_id: str,
    source_clinic_hash: str,
    journal_dir: str | Path,
) -> dict[str, Any]:
    """Return an exact existing patient or create once, with uncertain submits fenced."""
    normalized_name = _normalized_name(name)
    normalized_phone = normalize_phone(phone)
    clinic = clinic_id.strip() if isinstance(clinic_id, str) else ""
    if (
        normalized_name is None
        or normalized_phone is None
        or not clinic
        or not isinstance(source_clinic_hash, str)
        or not _HASH.fullmatch(source_clinic_hash)
    ):
        raise RegistrationError("invalid_input")

    try:
        directory = Path(journal_dir)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    except OSError:
        raise RegistrationError("journal_unavailable") from None

    key = hashlib.sha256((clinic + "\0" + normalized_phone).encode()).hexdigest()
    journal_path = directory / (key + ".json")
    lock_path = directory / (key + ".lock")
    try:
        with _locked(lock_path):
            journal = _read_journal(
                journal_path, clinic, normalized_phone, source_clinic_hash.lower(),
            )
            matches, name_candidates = _lookup(adapter, normalized_phone, name)
            phone_matches = _exact_phone(matches, normalized_phone)

            if matches and not phone_matches:
                raise RegistrationError("needs_review")

            if journal is not None:
                if len(phone_matches) == 1:
                    match = phone_matches[0]
                    if (
                        _normalized_name(match["name"]) == normalized_name
                        and (not journal["patient_id"] or journal["patient_id"] == match["id"])
                    ):
                        _atomic_json(journal_path, {**journal, "state": "created", "patient_id": match["id"]})
                        return _patient_result(match, normalized_phone, "existing")
                raise RegistrationError("needs_review")

            if len(phone_matches) > 1:
                raise RegistrationError("needs_review")
            if phone_matches:
                match = phone_matches[0]
                if _normalized_name(match["name"]) != normalized_name:
                    raise RegistrationError("needs_review")
                return _patient_result(match, normalized_phone, "existing")
            if name_candidates:
                raise RegistrationError("needs_review")

            submitted = False

            def before_submit() -> None:
                nonlocal submitted
                if submitted:
                    raise RegistrationError("needs_review")
                _atomic_json(journal_path, {
                    "schema_version": 1,
                    "clinic_id": clinic,
                    "source_clinic_hash": source_clinic_hash.lower(),
                    "phone": normalized_phone,
                    "state": "submitted",
                    "patient_id": "",
                })
                submitted = True

            try:
                patient_id = adapter.create(name, normalized_phone, before_submit)
            except RegistrationError:
                raise
            except Exception:
                raise RegistrationError("outcome_uncertain" if submitted else "create_failed") from None
            if not submitted:
                raise RegistrationError("invalid_adapter_response")
            if patient_id is not None and (
                not isinstance(patient_id, str) or not patient_id.strip()
            ):
                raise RegistrationError("needs_review")

            if patient_id is not None:
                patient_id = patient_id.strip()
                _atomic_json(journal_path, {
                    "schema_version": 1,
                    "clinic_id": clinic,
                    "source_clinic_hash": source_clinic_hash.lower(),
                    "phone": normalized_phone,
                    "state": "submitted",
                    "patient_id": patient_id,
                })
            verified, _ = _lookup(adapter, normalized_phone, name)
            verified_phone_matches = _exact_phone(verified, normalized_phone)
            verified_matches = [
                match for match in verified_phone_matches
                if (patient_id is None or match["id"].strip() == patient_id)
                and _normalized_name(match["name"]) == normalized_name
            ]
            if len(verified_matches) != 1 or len(verified_phone_matches) != 1:
                raise RegistrationError("needs_review")

            match = verified_matches[0]
            patient_id = match["id"].strip()
            _atomic_json(journal_path, {
                "schema_version": 1,
                "clinic_id": clinic,
                "source_clinic_hash": source_clinic_hash.lower(),
                "phone": normalized_phone,
                "state": "created",
                "patient_id": patient_id.strip(),
            })
            return _patient_result(match, normalized_phone, "created")
    except RegistrationError:
        raise
    except OSError:
        raise RegistrationError("journal_unavailable") from None
