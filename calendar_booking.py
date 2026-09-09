"""Agenda da operação via Google Calendar."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import threading
import time as time_module
import urllib.parse
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import calendar_config
from calendar_config import CalendarConfig
from calendar_service import CALENDAR_SCOPE, CALENDAR_EVENTS_SCOPE, token_has_calendar_scope

MAX_SLOTS = 3
MEETING_OUTCOMES = ("no_status", "attended", "no_show", "rescheduled")
_BOOKINGS_DB_DEFAULT = "/opt/data/.hermes/calendar_bookings.db"
_MAX_EVENT_PAGES = 4
_API_LOCK = threading.RLock()
_BOOKING_DB_LOCK = threading.RLock()


class CalendarBookingError(RuntimeError):
    """Erro seguro e apresentável ao modelo, sem vazar credenciais."""


def _cfg() -> CalendarConfig:
    return calendar_config.load_calendar_config()


def business_timezone() -> ZoneInfo:
    return _cfg().tz()


def token_path() -> Path:
    return calendar_config.token_path()


def calendar_id() -> str:
    return _cfg().calendar_id


def bookings_db_path(override: str | Path | None = None) -> Path:
    value = override or os.getenv("WHATSAPP_CALENDAR_BOOKINGS_DB", _BOOKINGS_DB_DEFAULT)
    return Path(value).expanduser()


def _booking_chat_key(chat_id: str) -> str:
    digits = "".join(ch for ch in str(chat_id).split("@", 1)[0].split(":", 1)[0] if ch.isdigit())
    material = digits or str(chat_id).strip()
    if not material:
        raise CalendarBookingError("Chat da reserva não foi identificado.")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _ensure_booking_store(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path, timeout=10)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS current_bookings (
                chat_key TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                timezone TEXT NOT NULL,
                meet_link TEXT NOT NULL,
                html_link TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS booking_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_key TEXT NOT NULL,
                event_id TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                timezone TEXT NOT NULL,
                meet_link TEXT NOT NULL DEFAULT '',
                html_link TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT 'no_status'
                    CHECK(outcome IN ('no_status', 'attended', 'no_show', 'rescheduled')),
                outcome_source TEXT NOT NULL DEFAULT '',
                outcome_updated_at REAL,
                rescheduled_to_start TEXT NOT NULL DEFAULT '',
                rescheduled_to_end TEXT NOT NULL DEFAULT '',
                followup_due_at REAL,
                followup_sent_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(event_id, start)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_booking_occurrences_start "
            "ON booking_occurrences(start)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_booking_occurrences_followup "
            "ON booking_occurrences(outcome, followup_due_at, followup_sent_at)"
        )
        # Instalações anteriores já possuem apenas a reserva atual. O backfill é
        # idempotente e faz esse encontro também ganhar status sem perder dados.
        conn.execute("""
            INSERT OR IGNORE INTO booking_occurrences (
                chat_key, event_id, start, end, timezone, meet_link, html_link,
                outcome, created_at, updated_at
            )
            SELECT chat_key, event_id, start, end, timezone, meet_link, html_link,
                   'no_status', created_at, updated_at
            FROM current_bookings WHERE status='active'
        """)
        conn.execute("""
            UPDATE booking_occurrences
            SET followup_due_at=CAST(strftime('%s', end) AS REAL) + 900
            WHERE outcome='no_status' AND followup_due_at IS NULL
              AND strftime('%s', end) IS NOT NULL
        """)
        conn.commit()
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _persist_booking(
    *,
    chat_id: str,
    result: dict[str, Any],
    previous: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> None:
    path = bookings_db_path(db_path)
    now = time_module.time()
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=10)) as conn:
            chat_key = _booking_chat_key(chat_id)
            conn.execute(
                """
                INSERT INTO current_bookings (
                    chat_key, event_id, start, end, timezone, meet_link,
                    html_link, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(chat_key) DO UPDATE SET
                    event_id=excluded.event_id,
                    start=excluded.start,
                    end=excluded.end,
                    timezone=excluded.timezone,
                    meet_link=excluded.meet_link,
                    html_link=excluded.html_link,
                    status='active',
                    updated_at=excluded.updated_at
                """,
                (
                    chat_key,
                    str(result.get("event_id") or ""),
                    str(result.get("start") or ""),
                    str(result.get("end") or ""),
                    str(result.get("timezone") or business_timezone().key),
                    str(result.get("meet_link") or ""),
                    str(result.get("htmlLink") or ""),
                    now,
                    now,
                ),
            )
            if previous and str(previous.get("start") or "") != str(result.get("start") or ""):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO booking_occurrences (
                        chat_key, event_id, start, end, timezone, meet_link, html_link,
                        outcome, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'no_status', ?, ?)
                    """,
                    (
                        chat_key,
                        str(previous.get("event_id") or ""),
                        str(previous.get("start") or ""),
                        str(previous.get("end") or ""),
                        str(previous.get("timezone") or business_timezone().key),
                        str(previous.get("meet_link") or ""),
                        str(previous.get("html_link") or ""),
                        float(previous.get("created_at") or now),
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE booking_occurrences
                    SET outcome='rescheduled', outcome_source='aya', outcome_updated_at=?,
                        rescheduled_to_start=?, rescheduled_to_end=?, updated_at=?
                    WHERE event_id=? AND start=?
                    """,
                    (
                        now,
                        str(result.get("start") or ""),
                        str(result.get("end") or ""),
                        now,
                        str(previous.get("event_id") or ""),
                        str(previous.get("start") or ""),
                    ),
                )
            try:
                end_epoch = _parse_datetime(
                    str(result.get("end") or ""), "end", business_timezone()
                ).timestamp()
            except CalendarBookingError:
                end_epoch = None
            conn.execute(
                """
                INSERT INTO booking_occurrences (
                    chat_key, event_id, summary, start, end, timezone, meet_link,
                    html_link, outcome, followup_due_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'no_status', ?, ?, ?)
                ON CONFLICT(event_id, start) DO UPDATE SET
                    summary=excluded.summary,
                    end=excluded.end,
                    timezone=excluded.timezone,
                    meet_link=excluded.meet_link,
                    html_link=excluded.html_link,
                    followup_due_at=COALESCE(booking_occurrences.followup_due_at, excluded.followup_due_at),
                    updated_at=excluded.updated_at
                """,
                (
                    chat_key,
                    str(result.get("event_id") or ""),
                    str(result.get("summary") or ""),
                    str(result.get("start") or ""),
                    str(result.get("end") or ""),
                    str(result.get("timezone") or business_timezone().key),
                    str(result.get("meet_link") or ""),
                    str(result.get("htmlLink") or result.get("html_link") or ""),
                    end_epoch + 15 * 60 if end_epoch is not None else None,
                    now,
                    now,
                ),
            )
            conn.commit()


def _occurrence_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["outcome"] = str(payload.get("outcome") or "no_status")
    payload["outcome_pending"] = payload["outcome"] == "no_status"
    return payload


def list_booking_occurrences(
    start: str,
    end: str,
    *,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Ocorrências persistidas que começam no intervalo semiaberto informado."""
    path = bookings_db_path(db_path)
    if not path.is_file():
        return []
    tz = business_timezone()
    range_start = _parse_datetime(str(start), "start", tz).timestamp()
    range_end = _parse_datetime(str(end), "end", tz).timestamp()
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_id, summary, start, end, timezone, meet_link, html_link,
                       outcome, outcome_source, outcome_updated_at,
                       rescheduled_to_start, rescheduled_to_end,
                       followup_due_at, followup_sent_at
                FROM booking_occurrences
                WHERE CAST(strftime('%s', start) AS REAL) >= ?
                  AND CAST(strftime('%s', start) AS REAL) < ?
                ORDER BY start
                """,
                (range_start, range_end),
            ).fetchall()
    return [_occurrence_row(row) for row in rows]


def meeting_outcome_summary(occurrences: list[dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
    current = time_module.time() if now is None else float(now)
    tz = business_timezone()
    counts = {outcome: 0 for outcome in MEETING_OUTCOMES}
    pending = 0
    for occurrence in occurrences:
        outcome = str(occurrence.get("outcome") or "no_status")
        if outcome not in counts:
            outcome = "no_status"
        counts[outcome] += 1
        if outcome == "no_status":
            try:
                ended = _parse_datetime(
                    str(occurrence.get("end") or ""), "end", tz
                ).timestamp() <= current
            except CalendarBookingError:
                ended = False
            if ended:
                pending += 1
    decided = counts["attended"] + counts["no_show"]
    return {
        "scheduled": len(occurrences),
        "attended": counts["attended"],
        "no_show": counts["no_show"],
        "rescheduled": counts["rescheduled"],
        "no_status": counts["no_status"],
        "pending": pending,
        "attendance_rate": round((counts["attended"] / decided) * 100) if decided else None,
    }


def set_booking_outcome(
    *,
    event_id: str,
    start: str,
    outcome: str,
    source: str = "owner",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized = str(outcome or "").strip().lower()
    if normalized not in MEETING_OUTCOMES:
        raise CalendarBookingError("Status deve ser attended, no_show, no_status ou rescheduled.")
    if normalized == "rescheduled" and str(source or "").strip().lower() != "aya":
        raise CalendarBookingError("Remarque pela conversa para registrar também a nova data.")
    clean_event_id = str(event_id or "").strip()
    clean_start = str(start or "").strip()
    if not clean_event_id or not clean_start:
        raise CalendarBookingError("Evento e horário são obrigatórios para alterar o status.")
    path = bookings_db_path(db_path)
    now = time_module.time()
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            updated = conn.execute(
                """
                UPDATE booking_occurrences
                SET outcome=?, outcome_source=?, outcome_updated_at=?, updated_at=?
                WHERE event_id=? AND start=?
                """,
                (normalized, _clean_text(source, 40), now, now, clean_event_id, clean_start),
            )
            if updated.rowcount != 1:
                raise CalendarBookingError("Não encontrei essa ocorrência da reunião.")
            row = conn.execute(
                """
                SELECT event_id, summary, start, end, timezone, meet_link, html_link,
                       outcome, outcome_source, outcome_updated_at,
                       rescheduled_to_start, rescheduled_to_end,
                       followup_due_at, followup_sent_at
                FROM booking_occurrences WHERE event_id=? AND start=?
                """,
                (clean_event_id, clean_start),
            ).fetchone()
            conn.commit()
    return _occurrence_row(row)


def get_pending_outcome_occurrence(
    chat_id: str, *, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Última ocorrência cujo pedido de confirmação já foi enviado ao contato."""
    path = bookings_db_path(db_path)
    if not path.is_file():
        return None
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT event_id, summary, start, end, timezone, meet_link, html_link,
                       outcome, outcome_source, outcome_updated_at,
                       rescheduled_to_start, rescheduled_to_end,
                       followup_due_at, followup_sent_at
                FROM booking_occurrences
                WHERE chat_key=? AND outcome='no_status' AND followup_sent_at IS NOT NULL
                ORDER BY followup_sent_at DESC LIMIT 1
                """,
                (_booking_chat_key(chat_id),),
            ).fetchone()
    return _occurrence_row(row) if row else None


def due_outcome_followups(
    *,
    now: float | None = None,
    limit: int = 20,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Reuniões encerradas que ainda precisam da confirmação pós-reunião da AYA."""
    path = bookings_db_path(db_path)
    if not path.is_file():
        return []
    current = time_module.time() if now is None else float(now)
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT chat_key, event_id, summary, start, end, timezone, meet_link,
                       html_link, outcome, followup_due_at, followup_sent_at
                FROM booking_occurrences
                WHERE outcome='no_status' AND followup_due_at IS NOT NULL
                  AND followup_due_at BETWEEN ? AND ? AND followup_sent_at IS NULL
                ORDER BY followup_due_at LIMIT ?
                """,
                (current - 86400, current, max(1, min(int(limit), 100))),
            ).fetchall()
    return [dict(row) for row in rows]


def mark_outcome_followup_sent(
    *, event_id: str, start: str, sent_at: float | None = None,
    db_path: str | Path | None = None,
) -> bool:
    path = bookings_db_path(db_path)
    stamp = sent_at or time_module.time()
    with _BOOKING_DB_LOCK:
        _ensure_booking_store(path)
        with contextlib.closing(sqlite3.connect(path, timeout=10)) as conn:
            updated = conn.execute(
                """
                UPDATE booking_occurrences SET followup_sent_at=?, updated_at=?
                WHERE event_id=? AND start=? AND followup_sent_at IS NULL
                """,
                (stamp, stamp, event_id, start),
            )
            conn.commit()
    return updated.rowcount == 1


def get_booking(
    chat_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Recupera a reserva ativa sem depender do estado efêmero do processo."""
    path = bookings_db_path(db_path)
    if not path.is_file():
        return None
    with _BOOKING_DB_LOCK:
        with contextlib.closing(
            sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        ) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT event_id, start, end, timezone, meet_link, html_link,
                       status, created_at, updated_at
                FROM current_bookings
                WHERE chat_key = ? AND status = 'active'
                """,
                (_booking_chat_key(chat_id),),
            ).fetchone()
    return dict(row) if row is not None else None


def _token_payload() -> dict[str, Any]:
    path = calendar_config.token_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def calendar_ready() -> bool:
    """True só quando a agenda está habilitada e o token tem o escopo certo."""
    cfg = _cfg()
    return cfg.enabled and token_has_calendar_scope(_token_payload())


def _service():
    if not calendar_ready():
        raise CalendarBookingError("Google Calendar ainda não está autenticado com o escopo de agenda.")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise CalendarBookingError("Bibliotecas do Google Calendar não estão instaladas.") from exc

    path = calendar_config.token_path()
    try:
        creds = Credentials.from_authorized_user_file(str(path))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(json.dumps(json.loads(creds.to_json()), indent=2), encoding="utf-8")
            path.chmod(0o600)
        if not creds.valid:
            raise CalendarBookingError("Token do Google Calendar inválido; refaça a autorização.")
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except CalendarBookingError:
        raise
    except Exception as exc:
        raise CalendarBookingError(f"Falha ao autenticar no Google Calendar: {type(exc).__name__}") from exc


def _parse_date(value: str, field: str) -> datetime.date:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise CalendarBookingError(f"{field} deve estar no formato YYYY-MM-DD.") from exc


def _parse_datetime(value: str, field: str, tz: ZoneInfo) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CalendarBookingError(f"{field} deve ser ISO 8601 com fuso horário.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CalendarBookingError(f"{field} precisa incluir o fuso horário.")
    return parsed.astimezone(tz)


def _coerce_period(value: str) -> str:
    period = str(value or "any").strip().lower()
    aliases = {
        "qualquer": "any", "any": "any", "all": "any",
        "manha": "morning", "manhã": "morning", "morning": "morning",
        "tarde": "afternoon", "afternoon": "afternoon",
    }
    if period not in aliases:
        raise CalendarBookingError("period deve ser any, morning ou afternoon.")
    return aliases[period]


def _coerce_preferred_time(value: str | None) -> time | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise CalendarBookingError("preferred_time deve estar no formato HH:MM.") from exc


def _round_up(value: datetime, minutes: int = 30) -> datetime:
    value = value.replace(second=0, microsecond=0)
    remainder = value.minute % minutes
    if remainder:
        value += timedelta(minutes=minutes - remainder)
    return value


def _business_bounds(day, tz: ZoneInfo, period: str, cfg: CalendarConfig) -> tuple[datetime, datetime]:
    start = datetime.combine(day, cfg.open_time(), tz)
    end = datetime.combine(day, cfg.close_time(), tz)
    if period == "morning":
        end = min(end, datetime.combine(day, time(12, 0), tz))
    elif period == "afternoon":
        start = max(start, datetime.combine(day, time(12, 0), tz))
    return start, end


def _overlaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    return any(start < busy_end and end > busy_start for busy_start, busy_end in busy)


def _freebusy(service, cfg: CalendarConfig, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    tz = cfg.tz()
    payload = service.freebusy().query(body={
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": tz.key,
        "items": [{"id": cfg.calendar_id}],
    }).execute()
    calendar = (payload.get("calendars") or {}).get(cfg.calendar_id) or {}
    errors = calendar.get("errors") or []
    if errors:
        raise CalendarBookingError("Google Calendar recusou a consulta de disponibilidade.")
    busy: list[tuple[datetime, datetime]] = []
    for item in calendar.get("busy") or []:
        try:
            busy.append((_parse_datetime(item["start"], "busy.start", tz), _parse_datetime(item["end"], "busy.end", tz)))
        except (KeyError, CalendarBookingError):
            continue
    return busy


def _list_events(api, cfg: CalendarConfig, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Lista os eventos crus do intervalo, paginando até o limite de páginas."""
    items: list[dict[str, Any]] = []
    page_token = None
    for _ in range(_MAX_EVENT_PAGES):
        kwargs = {
            "calendarId": cfg.calendar_id,
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 250,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        payload = api.events().list(**kwargs).execute()
        items.extend(payload.get("items") or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return items


def _event_window(event: dict[str, Any], tz: ZoneInfo) -> tuple[datetime, datetime] | None:
    start_raw = event.get("start") or {}
    end_raw = event.get("end") or {}
    if "date" in start_raw or "date" in end_raw:
        return None  # evento de dia inteiro, não entra na conta
    start_value = str(start_raw.get("dateTime") or "")
    end_value = str(end_raw.get("dateTime") or "")
    if not start_value or not end_value:
        return None
    try:
        return _parse_datetime(start_value, "event.start", tz), _parse_datetime(end_value, "event.end", tz)
    except CalendarBookingError:
        return None


def _classify_explicit_events(
    events: list[dict[str, Any]],
    cfg: CalendarConfig,
    tz: ZoneInfo,
    *,
    ignore_event_id: str | None = None,
) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]]:
    """Separa os eventos crus em vagas (contêm slot_keyword) e bloqueios (todo o resto)."""
    slot_keyword = cfg.slot_keyword.lower()
    slots: list[tuple[datetime, datetime]] = []
    blocks: list[tuple[datetime, datetime]] = []
    for event in events:
        if str(event.get("status") or "").lower() == "cancelled":
            continue
        if ignore_event_id and str(event.get("id") or "") == ignore_event_id:
            continue
        window = _event_window(event, tz)
        if window is None:
            continue
        summary = str(event.get("summary") or "")
        if slot_keyword in summary.lower():
            slots.append(window)
        else:
            blocks.append(window)
    return slots, blocks


def _explicit_snapshot(
    api,
    cfg: CalendarConfig,
    start: datetime,
    end: datetime,
    *,
    ignore_event_id: str | None = None,
) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]]:
    events = _list_events(api, cfg, start, end)
    return _classify_explicit_events(events, cfg, cfg.tz(), ignore_event_id=ignore_event_id)


def _busy_intervals(
    api,
    cfg: CalendarConfig,
    start: datetime,
    end: datetime,
    *,
    ignore_event_id: str | None = None,
) -> list[tuple[datetime, datetime]]:
    """Bloqueios reais no intervalo — a vaga 'Livre' em si nunca conta como ocupado."""
    if cfg.availability_mode == "explicit_slots":
        _slots, blocks = _explicit_snapshot(api, cfg, start, end, ignore_event_id=ignore_event_id)
        return blocks
    return _freebusy(api, cfg, start, end)


def _window_within_slots(start: datetime, end: datetime, slots: list[tuple[datetime, datetime]]) -> bool:
    return any(slot_start <= start and end <= slot_end for slot_start, slot_end in slots)


def find_available_slots(
    *,
    date_from: str,
    date_to: str | None = None,
    period: str = "any",
    preferred_time: str | None = None,
    duration_minutes: int | None = None,
    max_slots: int = MAX_SLOTS,
    now: datetime | None = None,
    service=None,
) -> dict[str, Any]:
    """Retorna vagas reais dentro do expediente, sem expor detalhes dos eventos."""
    cfg = _cfg()
    tz = cfg.tz()
    first_day = _parse_date(date_from, "date_from")
    last_day = _parse_date(date_to or date_from, "date_to")
    if last_day < first_day:
        raise CalendarBookingError("date_to não pode ser anterior a date_from.")
    if (last_day - first_day).days >= cfg.search_days:
        raise CalendarBookingError(f"A busca pode cobrir no máximo {cfg.search_days} dias.")
    try:
        duration = cfg.duration_minutes if duration_minutes is None else int(duration_minutes)
        limit = max(1, min(int(max_slots), MAX_SLOTS))
    except (TypeError, ValueError) as exc:
        raise CalendarBookingError("Duração ou limite de horários inválido.") from exc
    if duration != cfg.duration_minutes:
        raise CalendarBookingError(f"As reuniões duram {cfg.duration_minutes} minutos.")
    normalized_period = _coerce_period(period)
    preferred_clock = _coerce_preferred_time(preferred_time)
    step = 30 if duration % 30 == 0 else duration

    current = (now or datetime.now(tz)).astimezone(tz)
    earliest = _round_up(current + timedelta(minutes=cfg.min_lead_minutes), 30)
    query_start = datetime.combine(first_day, cfg.open_time(), tz)
    query_end = datetime.combine(last_day, cfg.close_time(), tz)
    if query_end <= earliest:
        return {"status": "ok", "timezone": tz.key, "duration_minutes": duration, "slots": []}

    with _API_LOCK:
        api = service or _service()
        if cfg.availability_mode == "explicit_slots":
            vagas, busy = _explicit_snapshot(api, cfg, max(query_start, current), query_end)
        else:
            vagas = None
            busy = _freebusy(api, cfg, max(query_start, current), query_end)

    slots: list[dict[str, str]] = []
    if cfg.availability_mode == "explicit_slots":
        for vaga_start, vaga_end in sorted(vagas, key=lambda item: item[0]):
            if len(slots) >= limit:
                break
            day = vaga_start.date()
            if day < first_day or day > last_day or not cfg.is_business_day(day):
                continue
            window_start, window_end = _business_bounds(day, tz, normalized_period, cfg)
            cursor = vaga_start
            while cursor + timedelta(minutes=duration) <= vaga_end and len(slots) < limit:
                slot_end = cursor + timedelta(minutes=duration)
                valid = (
                    cursor >= window_start
                    and slot_end <= window_end
                    and cursor >= earliest
                    and not _overlaps(cursor, slot_end, busy)
                    and (preferred_clock is None or cursor.time() == preferred_clock)
                )
                if valid:
                    slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
                cursor += timedelta(minutes=duration)
    else:
        day = first_day
        while day <= last_day and len(slots) < limit:
            if cfg.is_business_day(day):
                window_start, window_end = _business_bounds(day, tz, normalized_period, cfg)
                if preferred_clock is not None:
                    cursor = datetime.combine(day, preferred_clock, tz)
                    slot_end = cursor + timedelta(minutes=duration)
                    if (
                        cursor >= window_start
                        and cursor >= earliest
                        and slot_end <= window_end
                        and not _overlaps(cursor, slot_end, busy)
                    ):
                        slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
                else:
                    cursor = _round_up(max(window_start, earliest), step)
                    while cursor + timedelta(minutes=duration) <= window_end and len(slots) < limit:
                        slot_end = cursor + timedelta(minutes=duration)
                        if not _overlaps(cursor, slot_end, busy):
                            slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
                        cursor += timedelta(minutes=step)
            day += timedelta(days=1)

    return {
        "status": "ok",
        "timezone": tz.key,
        "duration_minutes": duration,
        "slots": slots,
    }


def _clean_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text).strip()
    return text[:limit]


def _event_id(chat_id: str, start: datetime, end: datetime) -> str:
    material = f"{chat_id}|{start.isoformat()}|{end.isoformat()}".encode("utf-8")
    # IDs customizados do Google Calendar aceitam somente base32hex (0-9, a-v).
    # O digest SHA-256 hexadecimal já respeita isso; o prefixo também precisa respeitar.
    return "c" + hashlib.sha256(material).hexdigest()[:40]


def _existing_event(api, cfg: CalendarConfig, event_id: str) -> dict[str, Any] | None:
    """Busca apenas o ID determinístico da WhatsAYA; 404 significa ausente."""
    try:
        return api.events().get(calendarId=cfg.calendar_id, eventId=event_id).execute()
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            return None
        raise CalendarBookingError(
            f"Falha ao verificar reserva existente no Google Calendar: {type(exc).__name__}"
        ) from exc


def _event_matches_window(
    event: dict[str, Any] | None,
    start: datetime,
    end: datetime,
    tz: ZoneInfo,
) -> bool:
    payload = event or {}
    if str(payload.get("status") or "").lower() == "cancelled":
        return False
    try:
        remote_start = _parse_datetime(
            str((payload.get("start") or {}).get("dateTime") or ""),
            "event.start",
            tz,
        )
        remote_end = _parse_datetime(
            str((payload.get("end") or {}).get("dateTime") or ""),
            "event.end",
            tz,
        )
    except (AttributeError, CalendarBookingError):
        return False
    return remote_start == start and remote_end == end


def _safe_meet_link(event: dict[str, Any] | None) -> str:
    payload = event or {}
    candidates = [payload.get("hangoutLink")]
    conference = payload.get("conferenceData") or {}
    candidates.extend(
        entry.get("uri")
        for entry in conference.get("entryPoints") or []
        if isinstance(entry, dict) and entry.get("entryPointType") == "video"
    )
    for candidate in candidates:
        raw = str(candidate or "").strip()
        try:
            parsed = urllib.parse.urlparse(raw)
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.netloc.lower() == "meet.google.com"
            and parsed.path.strip("/")
        ):
            return urllib.parse.urlunparse(("https", "meet.google.com", parsed.path, "", "", ""))
    return ""


def _meet_conference_request(event_id: str) -> dict[str, Any]:
    return {
        "createRequest": {
            "requestId": f"whatsaya-{event_id}",
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def _ensure_event_meet(api, cfg: CalendarConfig, event: dict[str, Any], event_id: str) -> tuple[dict[str, Any], str]:
    meet_link = _safe_meet_link(event)
    if meet_link:
        return event, meet_link
    try:
        conference = event.get("conferenceData") or {}
        request = conference.get("createRequest") or {}
        status = str((request.get("status") or {}).get("statusCode") or "")
        if status == "failure":
            raise CalendarBookingError("O Google Calendar não conseguiu gerar o link do Google Meet.")
        if not request:
            event = api.events().patch(
                calendarId=cfg.calendar_id,
                eventId=event_id,
                body={"conferenceData": _meet_conference_request(event_id)},
                conferenceDataVersion=1,
                sendUpdates="none",
            ).execute()

        # A criação da conferência é assíncrona. A confirmação só pode sair depois
        # que o Google realmente devolver o entryPoint do Meet.
        wait_seconds = max(
            0.0,
            min(float(os.getenv("WHATSAPP_CALENDAR_MEET_WAIT_SECONDS", "6")), 15.0),
        )
        deadline = time_module.monotonic() + wait_seconds
        while not (meet_link := _safe_meet_link(event)):
            conference = event.get("conferenceData") or {}
            request = conference.get("createRequest") or {}
            status = str((request.get("status") or {}).get("statusCode") or "")
            if status == "failure" or time_module.monotonic() >= deadline:
                break
            time_module.sleep(min(0.4, max(0.0, deadline - time_module.monotonic())))
            refreshed = _existing_event(api, cfg, event_id)
            if refreshed is not None:
                event = refreshed
    except CalendarBookingError:
        raise
    except Exception as exc:
        raise CalendarBookingError(
            f"Falha ao gerar o link do Google Meet: {type(exc).__name__}"
        ) from exc
    if not meet_link:
        raise CalendarBookingError(
            "A reunião foi criada, mas o link do Google Meet ainda não ficou disponível; tente confirmar novamente."
        )
    return event, meet_link


def _validated_booking_window(
    start: str, end: str, cfg: CalendarConfig, tz: ZoneInfo
) -> tuple[datetime, datetime]:
    start_dt = _parse_datetime(start, "start", tz)
    end_dt = _parse_datetime(end, "end", tz)
    if end_dt <= start_dt:
        raise CalendarBookingError("O fim precisa ser posterior ao início.")
    if int((end_dt - start_dt).total_seconds() // 60) != cfg.duration_minutes:
        raise CalendarBookingError(f"A reserva precisa ter {cfg.duration_minutes} minutos.")
    if not cfg.is_business_day(start_dt.date()):
        raise CalendarBookingError("A reunião precisa ser em dia útil.")
    if start_dt.time() < cfg.open_time() or end_dt.time() > cfg.close_time():
        raise CalendarBookingError(
            f"A reunião precisa ficar entre {cfg.business_start} e {cfg.business_end} (fuso {tz.key})."
        )
    if start_dt <= datetime.now(tz):
        raise CalendarBookingError("Não é possível reservar um horário no passado.")
    return start_dt, end_dt


def create_booking(
    *,
    chat_id: str,
    start: str,
    end: str,
    lead_name: str = "",
    purpose: str = "",
    service=None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Revalida, cria Google Meet e persiste a reunião ativa de forma idempotente."""
    cfg = _cfg()
    tz = cfg.tz()
    start_dt, end_dt = _validated_booking_window(start, end, cfg, tz)

    event_id = _event_id(chat_id, start_dt, end_dt)
    digits = "".join(ch for ch in str(chat_id).split("@", 1)[0].split(":", 1)[0] if ch.isdigit())
    safe_name = _clean_text(lead_name, 100) or (f"+{digits}" if digits else "Lead")
    safe_purpose = _clean_text(purpose, 280) or cfg.event_title
    description = "\n".join([
        f"Origem: {cfg.origin_label}",
        f"Contato: {safe_name}",
        f"WhatsApp: +{digits}" if digits else f"Chat: {_clean_text(chat_id, 80)}",
        f"Assunto: {safe_purpose}",
    ])
    summary = f"{cfg.event_title} — {safe_name}"
    body = {
        "id": event_id,
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz.key},
        "conferenceData": _meet_conference_request(event_id),
        "extendedProperties": {"private": {
            "whatsayaBookingKey": event_id,
            "whatsayaChat": hashlib.sha256(str(chat_id).encode()).hexdigest()[:16],
        }},
    }

    with _API_LOCK:
        api = service or _service()
        # ID determinístico: se esse evento já existe com a mesma janela, é um
        # retry idempotente — nem consulta disponibilidade nem chama insert de novo.
        existing = _existing_event(api, cfg, event_id)
        if existing is not None and _event_matches_window(existing, start_dt, end_dt, tz):
            event, meet_link = _ensure_event_meet(api, cfg, existing, event_id)
            created = False
        else:
            if cfg.availability_mode == "explicit_slots":
                slots, blocks = _explicit_snapshot(api, cfg, start_dt, end_dt, ignore_event_id=event_id)
                if not _window_within_slots(start_dt, end_dt, slots):
                    raise CalendarBookingError(
                        "Esse horário não está mais marcado como Livre; consulte novas opções."
                    )
                busy = blocks
            else:
                busy = _busy_intervals(api, cfg, start_dt, end_dt, ignore_event_id=event_id)
            if _overlaps(start_dt, end_dt, busy):
                raise CalendarBookingError("Esse horário acabou de ficar ocupado; consulte novas opções.")
            try:
                event = api.events().insert(
                    calendarId=cfg.calendar_id,
                    body=body,
                    sendUpdates="none",
                    conferenceDataVersion=1,
                ).execute()
                created = True
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status != 409:
                    raise CalendarBookingError(f"Falha ao criar evento no Google Calendar: {type(exc).__name__}") from exc
                event = _existing_event(api, cfg, event_id)
                if event is None:
                    raise CalendarBookingError("O Google reportou conflito, mas a reserva existente não foi encontrada.")
                created = False
            event, meet_link = _ensure_event_meet(api, cfg, event, event_id)

    result = {
        "status": "created" if created else "already_exists",
        "event_id": event.get("id") or event_id,
        "summary": event.get("summary") or summary,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "timezone": tz.key,
        "meet_link": meet_link,
        "htmlLink": event.get("htmlLink") or "",
    }
    _persist_booking(chat_id=chat_id, result=result, db_path=db_path)
    return result


def reschedule_booking(
    *,
    chat_id: str,
    start: str,
    end: str,
    lead_name: str = "",
    purpose: str = "",
    service=None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Move o evento ativo do lead sem criar duplicata e mantém o mesmo Google Meet."""
    cfg = _cfg()
    tz = cfg.tz()
    current = get_booking(chat_id, db_path=db_path)
    if current is None:
        raise CalendarBookingError("Não encontrei uma reunião ativa para remarcar.")
    start_dt, end_dt = _validated_booking_window(start, end, cfg, tz)
    same_local_window = (
        current.get("start") == start_dt.isoformat()
        and current.get("end") == end_dt.isoformat()
    )
    current_meet_link = _safe_meet_link({"hangoutLink": current.get("meet_link")})
    if same_local_window and current_meet_link:
        return dict(current, status="already_exists")

    event_id = str(current.get("event_id") or "")
    if not event_id:
        raise CalendarBookingError("A reunião ativa está sem identificador do Google Calendar.")
    body: dict[str, Any] = {
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz.key},
    }
    if not current_meet_link:
        body["conferenceData"] = _meet_conference_request(event_id)

    with _API_LOCK:
        api = service or _service()
        already_rescheduled = False
        if same_local_window:
            event = _existing_event(api, cfg, event_id)
            if not _event_matches_window(event, start_dt, end_dt, tz):
                raise CalendarBookingError(
                    "A reunião ativa no Google Calendar não corresponde ao horário salvo."
                )
            already_rescheduled = True
        elif _overlaps(
            start_dt, end_dt, _busy_intervals(api, cfg, start_dt, end_dt, ignore_event_id=event_id)
        ):
            event = _existing_event(api, cfg, event_id)
            if not _event_matches_window(event, start_dt, end_dt, tz):
                raise CalendarBookingError("Esse horário acabou de ficar ocupado; consulte novas opções.")
            already_rescheduled = True
        else:
            try:
                event = api.events().patch(
                    calendarId=cfg.calendar_id,
                    eventId=event_id,
                    body=body,
                    sendUpdates="none",
                    conferenceDataVersion=1,
                ).execute()
            except Exception as exc:
                raise CalendarBookingError(
                    f"Falha ao remarcar no Google Calendar: {type(exc).__name__}"
                ) from exc
        if same_local_window:
            event, meet_link = _ensure_event_meet(api, cfg, event, event_id)
        else:
            meet_link = _safe_meet_link(event) or current_meet_link
            if not meet_link:
                event, meet_link = _ensure_event_meet(api, cfg, event, event_id)

    result = {
        "status": "already_rescheduled" if already_rescheduled else "rescheduled",
        "event_id": event.get("id") or event_id,
        "summary": event.get("summary") or cfg.event_title,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "timezone": tz.key,
        "meet_link": meet_link,
        "htmlLink": event.get("htmlLink") or str(current.get("html_link") or ""),
    }
    _persist_booking(chat_id=chat_id, result=result, previous=current, db_path=db_path)
    return result
