"""Eventos das landing pages, no `panel.db`.

Módulo puro no molde de `panel_store.py`: abre conexão curta e fecha, não
importa o plugin. A LP manda `sendBeacon` para `POST /api/lp/event` (rota
pública do painel). `lp_events` guarda só a etapa do funil e a origem; em
`complete` e `whatsapp_click` a LP manda também nome, WhatsApp e respostas,
que viram um registro em `lp_leads` — é o que permite saber quem terminou o
quiz e não chamou, e a AYA iniciar a conversa por esse número (decisão de
16/09/2026, com consentimento no formulário). O `session_id` é o mesmo que a
LP põe no fim da mensagem do `wa.me`; é o que liga "clicou na LP" a "chegou
no WhatsApp" sem adivinhação.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from panel_store import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS lp_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lp TEXT NOT NULL,
    event TEXT NOT NULL,
    session_id TEXT NOT NULL,
    step INTEGER,
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lp_events_session ON lp_events(session_id);
CREATE INDEX IF NOT EXISTS idx_lp_events_ts ON lp_events(ts);
CREATE TABLE IF NOT EXISTS lp_leads (
    session_id TEXT PRIMARY KEY,
    lp TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    answers TEXT NOT NULL DEFAULT '{}',
    utm_source TEXT,
    utm_medium TEXT,
    utm_campaign TEXT,
    utm_content TEXT,
    completed_at TEXT,
    clicked_at TEXT,
    contacted_at TEXT,
    contact_message_id TEXT,
    contact_status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lp_leads_completed ON lp_leads(completed_at);
"""

EVENTS = ("view", "start", "step", "complete", "whatsapp_click")
LEAD_EVENTS = ("complete", "whatsapp_click")
ANSWER_FIELDS = ("niche", "negocio", "atendimento", "volume", "equipe", "problema")
UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
MAX_EVENTS_PER_SESSION = 200

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def clean_event(payload: dict) -> dict:
    """Valida o corpo vindo do navegador; tudo é entrada não confiável."""
    if not isinstance(payload, dict):
        raise ValueError("corpo inválido")
    lp = str(payload.get("lp") or "").strip().lower()
    if not _SLUG_RE.match(lp):
        raise ValueError("lp inválida")
    event = str(payload.get("event") or "").strip().lower()
    if event not in EVENTS:
        raise ValueError("evento desconhecido")
    session_id = str(payload.get("session_id") or "").strip()
    if not _SESSION_RE.match(session_id):
        raise ValueError("session_id inválido")
    step = payload.get("step")
    if step is not None:
        if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step <= 50:
            raise ValueError("step inválido")
    row = {"lp": lp, "event": event, "session_id": session_id, "step": step}
    for field in UTM_FIELDS:
        value = payload.get(field)
        row[field] = " ".join(str(value).split())[:100] if isinstance(value, str) and value.strip() else None
    return row


def clean_answers(raw) -> dict | None:
    """Nome, WhatsApp e respostas do quiz; só chegam em `complete` e
    `whatsapp_click`. Telefone é 11 dígitos (DDD + celular) já sem o 55; o
    lead sem nome ou sem telefone válido não é lead, é sessão."""
    if not isinstance(raw, dict):
        return None
    name = " ".join(str(raw.get("nome") or "").split())[:80]
    phone = re.sub(r"\D", "", str(raw.get("telefone") or ""))
    if phone.startswith("55") and len(phone) in (12, 13):
        phone = phone[2:]
    if len(name) < 2 or len(phone) != 11:
        return None
    answers = {}
    for field in ANSWER_FIELDS:
        value = raw.get(field)
        if isinstance(value, str) and value.strip():
            answers[field] = " ".join(value.split())[:120]
    return {"name": name, "phone": phone, "answers": answers}


def record_event(db_path: Path | str, payload: dict, *, now: datetime | None = None) -> dict:
    row = clean_event(payload)
    lead = clean_answers(payload.get("answers")) if row["event"] in LEAD_EVENTS else None
    row["ts"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # ponytail: teto por sessão, sem rate limit por IP; o Cloudflare segura volume.
        count = conn.execute(
            "SELECT COUNT(*) FROM lp_events WHERE session_id = ?", (row["session_id"],)
        ).fetchone()[0]
        if count >= MAX_EVENTS_PER_SESSION:
            raise ValueError("sessão estourou o limite de eventos")
        conn.execute(
            "INSERT INTO lp_events (lp, event, session_id, step, utm_source, utm_medium,"
            " utm_campaign, utm_content, ts) VALUES (?,?,?,?,?,?,?,?,?)",
            (row["lp"], row["event"], row["session_id"], row["step"], row["utm_source"],
             row["utm_medium"], row["utm_campaign"], row["utm_content"], row["ts"]),
        )
        if lead:
            stamp_col = "completed_at" if row["event"] == "complete" else "clicked_at"
            conn.execute(
                "INSERT INTO lp_leads (session_id, lp, name, phone, answers, utm_source, utm_medium,"
                f" utm_campaign, utm_content, {stamp_col}, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(session_id) DO UPDATE SET name = excluded.name, phone = excluded.phone,"
                " answers = excluded.answers, lp = excluded.lp,"
                f" {stamp_col} = COALESCE(lp_leads.{stamp_col}, excluded.{stamp_col}),"
                " updated_at = excluded.updated_at",
                (row["session_id"], row["lp"], lead["name"], lead["phone"],
                 json.dumps(lead["answers"], ensure_ascii=False), row["utm_source"], row["utm_medium"],
                 row["utm_campaign"], row["utm_content"], row["ts"], row["ts"], row["ts"]),
            )
        conn.commit()
    finally:
        conn.close()
    row["lead"] = lead
    return row


def _row_to_lead(r: sqlite3.Row) -> dict:
    lead = dict(r)
    lead["answers"] = json.loads(lead.get("answers") or "{}")
    return lead


def get_lead(db_path: Path | str, session_id: str) -> dict | None:
    if not Path(db_path).is_file():
        return None
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        r = conn.execute("SELECT * FROM lp_leads WHERE session_id = ?", (session_id,)).fetchone()
        return _row_to_lead(r) if r else None
    finally:
        conn.close()


def list_leads(db_path: Path | str, *, since: str | None = None, limit: int = 200) -> list[dict]:
    """Leads da LP mais recentes primeiro; `since` é ISO UTC."""
    if not Path(db_path).is_file():
        return []
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            "SELECT * FROM lp_leads WHERE (? IS NULL OR updated_at >= ?) ORDER BY updated_at DESC LIMIT ?",
            (since, since, limit),
        ).fetchall()
        return [_row_to_lead(r) for r in rows]
    finally:
        conn.close()


def mark_contacted(db_path: Path | str, session_id: str, *, status: str, message_id: str = "",
                   now: datetime | None = None) -> None:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "UPDATE lp_leads SET contacted_at = COALESCE(contacted_at, ?), contact_status = ?,"
            " contact_message_id = COALESCE(NULLIF(?, ''), contact_message_id), updated_at = ? WHERE session_id = ?",
            (stamp, status, message_id, stamp, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def events_for_session(db_path: Path | str, session_id: str) -> list[dict]:
    if not Path(db_path).is_file():
        return []
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        rows = conn.execute(
            "SELECT * FROM lp_events WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
