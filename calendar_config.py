"""Configuração da agenda (Google Calendar) do painel WhatsAYA.

Só stdlib: este módulo roda tanto no container do painel (`python:3.12-slim`,
sem libs Google) quanto é importado pelo agente. Guarda a seção `"calendar"`
de `panel.config.json`, com dois níveis de rigor:

- `normalize_calendar_config` é LENIENTE — valor ruim vira default, nunca
  levanta. O agente chama isso a cada turno; config quebrada não pode travar
  o atendimento.
- `validate_calendar_settings` é ESTRITO — usado só quando o painel salva uma
  mudança; cada regra violada levanta `CalendarConfigError` com mensagem
  pt-BR segura pro browser.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_DEFAULT_CONFIG_PATH = "/opt/data/panel.config.json"
_DEFAULT_TOKEN_PATH = "/opt/data/.hermes/google_token.json"

_ENV_FALLBACKS = {
    "calendar_id": "WHATSAPP_CALENDAR_ID",
    "timezone": "WHATSAPP_CALENDAR_TZ",
    "min_lead_minutes": "WHATSAPP_CALENDAR_MIN_LEAD_MINUTES",
}


class CalendarConfigError(ValueError):
    """Erro de configuração de agenda, com mensagem segura pra mostrar no navegador."""


@dataclass(frozen=True)
class CalendarConfig:
    enabled: bool = True
    calendar_id: str = "primary"
    timezone: str = "America/Sao_Paulo"
    availability_mode: str = "freebusy_gaps"
    slot_keyword: str = "Livre"
    block_keyword: str = "Bloqueada"
    business_days: tuple[int, ...] = (1, 2, 3, 4, 5)
    business_start: str = "08:00"
    business_end: str = "18:00"
    duration_minutes: int = 30
    min_lead_minutes: int = 120
    search_days: int = 14
    event_title: str = "Reunião WhatsAYA"
    origin_label: str = "WhatsApp / AYA"

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def open_time(self) -> datetime.time:
        return _parse_hhmm(self.business_start)

    def close_time(self) -> datetime.time:
        return _parse_hhmm(self.business_end)

    def is_business_day(self, d: datetime.date) -> bool:
        return d.isoweekday() in self.business_days

    def to_public_dict(self) -> dict:
        data = asdict(self)
        data["business_days"] = list(self.business_days)
        return data


EDITABLE_FIELDS = (
    "enabled", "calendar_id", "timezone", "availability_mode", "slot_keyword", "block_keyword",
    "business_days", "business_start", "business_end", "duration_minutes", "min_lead_minutes",
    "search_days", "event_title",
)


def _parse_hhmm(value: str) -> datetime.time:
    hours, minutes = value.split(":")
    return datetime.time(int(hours), int(minutes))


def config_path(env: Mapping | None = None) -> Path:
    env = env if env is not None else os.environ
    value = env.get("WHATSAPP_PANEL_CONFIG")
    return Path(value).expanduser() if value else Path(_DEFAULT_CONFIG_PATH)


def token_path(env: Mapping | None = None) -> Path:
    env = env if env is not None else os.environ
    value = env.get("WHATSAPP_CALENDAR_TOKEN_PATH")
    return Path(value).expanduser() if value else Path(_DEFAULT_TOKEN_PATH)


# --- validadores individuais, usados tanto pelo normalize (leniente) quanto
# pelo validate (estrito) — uma regra só, dois jeitos de reagir a ela falhar.

def _check_bool(value: Any):
    return value if isinstance(value, bool) else None


def _check_calendar_id(value: Any):
    if not isinstance(value, str) or not (1 <= len(value) <= 200):
        return None
    if any(c.isspace() or ord(c) < 32 for c in value):
        return None
    return value


def _check_timezone(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        ZoneInfo(value)
    except Exception:
        return None
    return value


def _check_mode(value: Any):
    return value if value in ("freebusy_gaps", "explicit_slots") else None


def _check_keyword(value: Any):
    if not isinstance(value, str) or not (1 <= len(value) <= 40):
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return value


def _check_business_days(value: Any):
    if not isinstance(value, (list, tuple)) or not value:
        return None
    days = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not (1 <= item <= 7):
            return None
        days.append(item)
    if len(set(days)) != len(days):
        return None
    return tuple(sorted(set(days)))


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _check_time_str(value: Any):
    if not isinstance(value, str) or not _TIME_RE.match(value):
        return None
    return value


def _check_int_range(value: Any, lo: int, hi: int):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if lo <= value <= hi else None


def _check_duration(value: Any):
    checked = _check_int_range(value, 15, 240)
    return checked if checked is not None and checked % 5 == 0 else None


def _check_title(value: Any, max_len: int):
    if not isinstance(value, str) or not (1 <= len(value) <= max_len):
        return None
    if any(ord(c) < 32 for c in value):
        return None
    return value


def _coerce_env_int(value: Any):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def normalize_calendar_config(raw: Mapping | None, env: Mapping | None = None) -> CalendarConfig:
    raw = raw if isinstance(raw, Mapping) else {}
    env = env if env is not None else os.environ
    defaults = CalendarConfig()

    def resolve(key: str, checker, env_checker=None):
        if key in raw:
            value = checker(raw[key])
            if value is not None:
                return value
            return getattr(defaults, key)
        env_var = _ENV_FALLBACKS.get(key)
        if env_var is not None:
            env_raw = env.get(env_var)
            if env_raw is not None:
                value = (env_checker or checker)(env_raw)
                if value is not None:
                    return value
        return getattr(defaults, key)

    enabled = resolve("enabled", _check_bool)
    calendar_id = resolve("calendar_id", _check_calendar_id)
    timezone = resolve("timezone", _check_timezone)
    availability_mode = resolve("availability_mode", _check_mode)
    slot_keyword = resolve("slot_keyword", _check_keyword)
    block_keyword = resolve("block_keyword", _check_keyword)
    business_days = resolve("business_days", _check_business_days)
    business_start = resolve("business_start", _check_time_str)
    business_end = resolve("business_end", _check_time_str)
    duration_minutes = resolve("duration_minutes", _check_duration)
    min_lead_minutes = resolve(
        "min_lead_minutes",
        lambda v: _check_int_range(v, 0, 10080),
        env_checker=lambda v: _check_int_range(_coerce_env_int(v), 0, 10080),
    )
    search_days = resolve("search_days", lambda v: _check_int_range(v, 1, 42))
    event_title = resolve("event_title", lambda v: _check_title(v, 80))

    if slot_keyword.lower() == block_keyword.lower():
        slot_keyword, block_keyword = defaults.slot_keyword, defaults.block_keyword

    if not business_start < business_end:
        business_start, business_end = defaults.business_start, defaults.business_end

    origin_label = defaults.origin_label
    if "origin_label" in raw:
        checked = _check_title(raw["origin_label"], 120)
        if checked is not None:
            origin_label = checked

    return CalendarConfig(
        enabled=enabled,
        calendar_id=calendar_id,
        timezone=timezone,
        availability_mode=availability_mode,
        slot_keyword=slot_keyword,
        block_keyword=block_keyword,
        business_days=business_days,
        business_start=business_start,
        business_end=business_end,
        duration_minutes=duration_minutes,
        min_lead_minutes=min_lead_minutes,
        search_days=search_days,
        event_title=event_title,
        origin_label=origin_label,
    )


_CACHE_LOCK = threading.Lock()
_cache: dict[Path, tuple[tuple[int, int], CalendarConfig]] = {}


def load_calendar_config(path: Path | None = None, env: Mapping | None = None) -> CalendarConfig:
    env = env if env is not None else os.environ
    target = path or config_path(env)

    try:
        st = target.stat()
        cache_key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return normalize_calendar_config(None, env)

    with _CACHE_LOCK:
        cached = _cache.get(target)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    raw = data.get("calendar") if isinstance(data, dict) else None
    config = normalize_calendar_config(raw if isinstance(raw, dict) else None, env)

    with _CACHE_LOCK:
        _cache[target] = (cache_key, config)
    return config


def validate_calendar_settings(raw: Mapping) -> dict:
    if not isinstance(raw, Mapping):
        raise CalendarConfigError("Configuração da agenda inválida.")

    unknown = set(raw) - set(EDITABLE_FIELDS)
    if unknown:
        raise CalendarConfigError(f"Campo desconhecido: {sorted(unknown)[0]!r}.")

    defaults = CalendarConfig()
    out: dict[str, Any] = {}

    def field(key: str, checker, message: str) -> None:
        if key not in raw:
            out[key] = getattr(defaults, key)
            return
        value = checker(raw[key])
        if value is None:
            raise CalendarConfigError(message)
        out[key] = value

    field("enabled", _check_bool, "enabled precisa ser true ou false.")
    field(
        "calendar_id",
        _check_calendar_id,
        "calendar_id inválido: use 'primary' ou o e-mail/ID do calendário do Google, sem espaços, até 200 caracteres.",
    )
    field("timezone", _check_timezone, "Fuso horário inválido.")
    field(
        "availability_mode",
        _check_mode,
        "availability_mode precisa ser 'freebusy_gaps' ou 'explicit_slots'.",
    )
    field("slot_keyword", _check_keyword, "slot_keyword precisa ter de 1 a 40 caracteres, sem quebras de linha.")
    field("block_keyword", _check_keyword, "block_keyword precisa ter de 1 a 40 caracteres, sem quebras de linha.")
    field(
        "business_days",
        _check_business_days,
        "business_days precisa ser uma lista de dias de 1 (segunda) a 7 (domingo), sem repetição.",
    )
    field("business_start", _check_time_str, "business_start precisa estar no formato HH:MM.")
    field("business_end", _check_time_str, "business_end precisa estar no formato HH:MM.")
    field(
        "duration_minutes",
        _check_duration,
        "duration_minutes precisa ser um número entre 15 e 240, múltiplo de 5.",
    )
    field(
        "min_lead_minutes",
        lambda v: _check_int_range(v, 0, 10080),
        "min_lead_minutes precisa ser um número entre 0 e 10080.",
    )
    field("search_days", lambda v: _check_int_range(v, 1, 42), "search_days precisa ser um número entre 1 e 42.")
    field("event_title", lambda v: _check_title(v, 80), "event_title precisa ter de 1 a 80 caracteres, sem quebras de linha.")

    if out["slot_keyword"].lower() == out["block_keyword"].lower():
        raise CalendarConfigError("slot_keyword e block_keyword não podem ser iguais.")

    if not out["business_start"] < out["business_end"]:
        raise CalendarConfigError("business_start precisa ser antes de business_end.")

    out["business_days"] = list(out["business_days"])
    return out


def save_calendar_settings(raw: Mapping, path: Path | None = None) -> CalendarConfig:
    validated = validate_calendar_settings(raw)
    target = path or config_path()

    try:
        current = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            current = {}
    except (OSError, json.JSONDecodeError):
        current = {}

    existing_calendar = current.get("calendar")
    existing_calendar = existing_calendar if isinstance(existing_calendar, dict) else {}
    merged_calendar = {**existing_calendar, **validated}
    current["calendar"] = merged_calendar

    atomic_write_json(target, current)
    return normalize_calendar_config(merged_calendar)


def atomic_write_json(path: Path, payload: Any, *, mode: int = 0o600) -> None:
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(directory))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        try:
            existing_stat = path.stat()
        except FileNotFoundError:
            existing_stat = None

        if existing_stat is not None:
            os.chmod(tmp_path, existing_stat.st_mode & 0o777)
            try:
                os.chown(tmp_path, existing_stat.st_uid, existing_stat.st_gid)
            except PermissionError:
                pass
        else:
            os.chmod(tmp_path, mode)
            if os.geteuid() == 0:
                try:
                    parent_stat = directory.stat()
                    os.chown(tmp_path, parent_stat.st_uid, parent_stat.st_gid)
                except PermissionError:
                    pass

        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
