"""Read the clinic-bound Prontuário Verde schedule cache for the panel agenda."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_ID = re.compile(r"[1-9][0-9]{0,30}\Z")
_PROFESSIONAL_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_RECORD = re.compile(r"[1-9][0-9]{0,30}\Z")
_MAX_AGE = timedelta(hours=2)


class ScheduleUnavailable(ValueError):
    """The local schedule cache cannot be trusted for display."""


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ScheduleUnavailable("schedule_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ScheduleUnavailable("schedule_timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScheduleUnavailable("schedule_timezone_missing")
    return parsed


def _label(value: object) -> str:
    if not isinstance(value, str):
        raise ScheduleUnavailable("schedule_text_invalid")
    value = " ".join(value.split())
    if not value or len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ScheduleUnavailable("schedule_text_invalid")
    return value


def load_schedule(path: str | Path, clinic_id: object, source_clinic_hash: object,
                  *, now: datetime | None = None) -> dict:
    """Read once and validate the complete snapshot before exposing any event."""
    clinic = clinic_id.strip() if isinstance(clinic_id, str) else ""
    if not clinic or not isinstance(source_clinic_hash, str) or not _HASH.fullmatch(source_clinic_hash):
        raise ScheduleUnavailable("schedule_config_invalid")
    try:
        cache_path = Path(path)
        if cache_path.stat().st_size > 16 * 1024 * 1024:
            raise ScheduleUnavailable("schedule_too_large")
        snapshot = json.loads(cache_path.read_text(encoding="utf-8"))
    except ScheduleUnavailable:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ScheduleUnavailable("schedule_unavailable") from None

    if not isinstance(snapshot, dict) or (
        snapshot.get("schema_version") != 1
        or snapshot.get("source") != "prontuario_verde"
        or snapshot.get("clinic_id") != clinic
        or snapshot.get("complete") is not True
        or not isinstance(snapshot.get("source_clinic_hash"), str)
        or not _HASH.fullmatch(snapshot["source_clinic_hash"])
        or snapshot["source_clinic_hash"].lower() != source_clinic_hash.lower()
        or not isinstance(snapshot.get("appointments"), list)
    ):
        raise ScheduleUnavailable("schedule_snapshot_invalid")

    generated = _timestamp(snapshot.get("generated_at"))
    coverage_start = _timestamp(snapshot.get("coverage_start"))
    coverage_end = _timestamp(snapshot.get("coverage_end"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    generated_utc = generated.astimezone(timezone.utc)
    if (coverage_end <= coverage_start or generated_utc > current
            or current - generated_utc > _MAX_AGE
            or not coverage_start.astimezone(timezone.utc) <= current < coverage_end.astimezone(timezone.utc)):
        raise ScheduleUnavailable("schedule_stale_or_out_of_coverage")

    professionals: dict[str, str] = {}
    raw_professionals = snapshot.get("professionals")
    if raw_professionals is not None:
        if not isinstance(raw_professionals, list):
            raise ScheduleUnavailable("professionals_invalid")
        for item in raw_professionals:
            if not isinstance(item, dict):
                raise ScheduleUnavailable("professionals_invalid")
            professional_id = item.get("id")
            if not isinstance(professional_id, str) or not _PROFESSIONAL_ID.fullmatch(professional_id):
                raise ScheduleUnavailable("professionals_invalid")
            if professional_id in professionals:
                raise ScheduleUnavailable("professional_id_duplicate")
            professionals[professional_id] = _label(item.get("name"))

    seen: set[str] = set()
    rows: list[dict] = []
    for item in snapshot["appointments"]:
        if not isinstance(item, dict):
            raise ScheduleUnavailable("appointment_invalid")
        event_id = item.get("id")
        patient_id = item.get("patient_id")
        professional_id = item.get("professional_id")
        if (not isinstance(event_id, str) or not _ID.fullmatch(event_id) or event_id in seen
                or not isinstance(patient_id, str) or not _ID.fullmatch(patient_id)
                or not isinstance(professional_id, str) or not _PROFESSIONAL_ID.fullmatch(professional_id)):
            raise ScheduleUnavailable("appointment_id_invalid")
        seen.add(event_id)
        start, end = _timestamp(item.get("start")), _timestamp(item.get("end"))
        if end <= start or not coverage_start <= start < coverage_end:
            raise ScheduleUnavailable("appointment_window_invalid")
        professional_name = _label(item.get("professional_name"))
        if raw_professionals is not None and professional_id not in professionals:
            raise ScheduleUnavailable("professional_unknown")
        professionals.setdefault(professional_id, professional_name)
        if professionals[professional_id] != professional_name:
            raise ScheduleUnavailable("professional_name_mismatch")
        status = _label(item.get("status"))
        if status not in {"agendado", "confirmado"}:
            raise ScheduleUnavailable("appointment_status_invalid")
        row = {
            "id": event_id, "start": start.isoformat(), "end": end.isoformat(), "all_day": False,
            "source": "prontuario_verde", "kind": "prontuario",
            "title": "Paciente cadastrado", "patient_id": patient_id,
            "professional_id": professional_id, "professional_name": professional_name,
            "status": status,
        }
        record_number = item.get("record_number")
        patient_name = item.get("patient_name")
        if record_number is not None:
            if not isinstance(record_number, str) or not _RECORD.fullmatch(record_number):
                raise ScheduleUnavailable("appointment_record_invalid")
            row["title"] = f"Prontuário {record_number}"
        if patient_name is not None:
            row["title"] = _label(patient_name)
        rows.append(row)

    # Older snapshots have no independent professional catalogue. In that case,
    # event rows are the only available source of names and IDs.
    return {
        "updated_at": generated.isoformat(), "coverage_start": coverage_start.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "professionals": [{"id": key, "name": value} for key, value in sorted(professionals.items())],
        "events": rows,
    }


def events_for_range(schedule: dict, start: datetime, end: datetime,
                     professional_id: str | None = None) -> list[dict]:
    if professional_id is not None and not any(
        item["id"] == professional_id for item in schedule["professionals"]
    ):
        raise ValueError("professional_unknown")
    begin_utc, finish_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    rows = []
    for event in schedule["events"]:
        event_start = _timestamp(event["start"]).astimezone(timezone.utc)
        event_end = _timestamp(event["end"]).astimezone(timezone.utc)
        if event_start < finish_utc and event_end > begin_utc:
            if professional_id is None or event["professional_id"] == professional_id:
                rows.append(event)
    return sorted(rows, key=lambda event: (event["start"], event["id"]))
