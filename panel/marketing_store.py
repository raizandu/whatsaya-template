"""Eventos das landing pages, no `panel.db`.

Módulo puro no molde de `panel_store.py`: abre conexão curta e fecha, não
importa o plugin. A LP manda `sendBeacon` para `POST /api/lp/event` (rota
pública do painel) e só a etapa do funil e a origem entram aqui — nunca nome,
telefone ou resposta do quiz, que já chegam inteiros na mensagem do WhatsApp.
O `session_id` é o mesmo que a LP põe no fim da mensagem do `wa.me`; é o que
liga "clicou na LP" a "chegou no WhatsApp" sem adivinhação.
"""
from __future__ import annotations

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
"""

EVENTS = ("view", "start", "step", "complete", "whatsapp_click")
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


def record_event(db_path: Path | str, payload: dict, *, now: datetime | None = None) -> dict:
    row = clean_event(payload)
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
        conn.commit()
    finally:
        conn.close()
    return row


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
