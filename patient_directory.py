"""Local, privacy-preserving patient directory lookup for support prompts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


SNAPSHOT_PATH = Path("/opt/data/patient_directory.json")
DEFAULT_MAX_AGE_HOURS = 24
MAX_MAX_AGE_HOURS = 168
_PHONE_SEPARATORS = re.compile(r"[\s().+\-]")
_SOURCE_CLINIC_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


def normalize_phone(value: str) -> str | None:
    """Return a Brazilian phone as 55+DDD+number; reject non-phone JIDs."""
    raw = str(value or "").strip()
    if not raw:
        return None

    if "@" in raw:
        local, domain = raw.split("@", 1)
        if domain.lower() != "s.whatsapp.net":
            return None
        raw = local.split(":", 1)[0]

    digits = _PHONE_SEPARATORS.sub("", raw)
    if not digits.isdigit():
        return None

    if digits.startswith("55") and len(digits) in (12, 13):
        national = digits[2:]
    elif len(digits) in (10, 11):
        national = digits
    else:
        return None

    area_code = int(national[:2])
    if not 11 <= area_code <= 99:
        return None
    return "55" + national


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _max_age(value: object) -> int:
    try:
        age = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_MAX_AGE_HOURS
    return age if 1 <= age <= MAX_MAX_AGE_HOURS else DEFAULT_MAX_AGE_HOURS


def lookup_patient(
    snapshot_path: str | Path,
    clinic_id: str,
    phone: str,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
    source_clinic_hash: str | None = None,
) -> dict:
    """Look up only registration status; never return snapshot patient data."""
    normalized_phone = normalize_phone(phone)
    clinic = str(clinic_id or "").strip()
    if (
        not normalized_phone
        or not clinic
        or not isinstance(source_clinic_hash, str)
        or not _SOURCE_CLINIC_HASH.fullmatch(source_clinic_hash)
    ):
        return {"status": "unavailable", "count": None, "updated_at": None}

    try:
        path = Path(snapshot_path)
        if path.stat().st_size > 16 * 1024 * 1024:
            return {"status": "unavailable", "count": None, "updated_at": None}
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return {"status": "unavailable", "count": None, "updated_at": None}

    if not isinstance(snapshot, dict):
        return {"status": "unavailable", "count": None, "updated_at": None}
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("source") != "prontuario_verde"
        or snapshot.get("clinic_id") != clinic
        or snapshot.get("complete") is not True
        or not isinstance(snapshot.get("patients"), list)
        or not isinstance(snapshot.get("source_clinic_hash"), str)
        or not _SOURCE_CLINIC_HASH.fullmatch(snapshot["source_clinic_hash"])
        or snapshot["source_clinic_hash"].lower() != source_clinic_hash.lower()
    ):
        return {"status": "unavailable", "count": None, "updated_at": None}

    generated_at = _parse_timestamp(snapshot.get("generated_at"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if (
        generated_at is None
        or generated_at > current
        or current - generated_at > timedelta(hours=_max_age(max_age_hours))
    ):
        return {"status": "unavailable", "count": None, "updated_at": None}

    patient_ids: set[str] = set()
    for patient in snapshot["patients"]:
        if not isinstance(patient, dict):
            return {"status": "unavailable", "count": None, "updated_at": None}
        patient_id = patient.get("id")
        phones = patient.get("phones")
        if not isinstance(patient_id, str) or not patient_id.strip() or not isinstance(phones, list):
            return {"status": "unavailable", "count": None, "updated_at": None}
        if any(not isinstance(item, str) or normalize_phone(item) is None for item in phones):
            return {"status": "unavailable", "count": None, "updated_at": None}
        if normalized_phone in {normalize_phone(item) for item in phones}:
            patient_ids.add(patient_id)

    updated_at = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    count = len(patient_ids)
    status = "not_found" if count == 0 else "matched" if count == 1 else "ambiguous"
    return {"status": status, "count": count, "updated_at": updated_at}


def prompt_context(
    config: dict,
    clean_jid: str,
    snapshot_path: str | Path = SNAPSHOT_PATH,
    now: datetime | None = None,
) -> str:
    """Build the compact support prompt block, or nothing while disabled."""
    if not isinstance(config, dict) or config.get("enabled") is not True:
        return ""

    result = lookup_patient(
        snapshot_path=snapshot_path,
        clinic_id=config.get("clinic_id", ""),
        phone=clean_jid,
        max_age_hours=config.get("max_age_hours", DEFAULT_MAX_AGE_HOURS),
        now=now,
        source_clinic_hash=config.get("source_clinic_hash"),
    )
    status = result["status"]
    lines = [
        "### STATUS CADASTRAL — FONTE LOCAL ###",
        f"Status: {status}",
        f"Quantidade de cadastros associados ao telefone: {result['count'] if result['count'] is not None else 'indisponível'}",
        f"Atualização do snapshot: {result['updated_at'] or 'indisponível'}",
    ]
    if status == "matched":
        lines.append(
            "Isso indica somente um cadastro associado a este telefone; não confirma a identidade "
            "de quem está escrevendo nem atendimento anterior."
        )
    elif status == "ambiguous":
        lines.append(
            "Não revele nomes nem detalhes. Confirme com naturalidade se o assunto é para a própria "
            "pessoa ou para outra pessoa."
        )
    elif status == "not_found":
        lines.append(
            "A ausência no snapshot não significa que a pessoa seja paciente nova. Não afirme que "
            "é paciente nova; siga a conversa normalmente."
        )
    else:
        lines.append("O status não pôde ser confirmado. Não infira se existe cadastro ou atendimento anterior.")
    return "\n".join(lines) + "\n\n"
