"""Leitura da aba Marketing: funil das landing pages cruzado com o WhatsApp.

Módulo puro no molde de `daily_audit`: `summarize` recebe linhas já carregadas
e devolve o relatório; `report` só junta as fontes. Nada aqui escreve.

Duas origens de lead, e a distinção é o que a aba existe para mostrar:

- **LP**: a página manda o beacon com um `session_id` e põe o mesmo id no fim
  da mensagem do `wa.me` (`Origem: utm_source: instagram | id: ab3k9x`). A
  primeira mensagem viva do contato é onde esse id aparece; casou, o lead é
  daquela sessão e herda os UTMs dela.
- **Nativa**: anúncio Click-to-WhatsApp e afins chegam sem LP; o bridge extrai
  o referral e o plugin grava `origin` no contato (`FB_Ads`,
  `click_to_chat_link`...). Vale como origem quando não há id de LP.
"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from commercial_followups import TERMINAL_STAGES
from data import PERIOD_DAYS, _period_bounds, _ro

FUNNEL = ("view", "start", "complete", "whatsapp_click")
WON_STAGES = {"won", "ganho"}
_SESSION_IN_MESSAGE_RE = re.compile(r"\bid:\s*([A-Za-z0-9_-]{6,32})\b")


def session_id_from_message(body: str) -> str:
    """O id que a LP escreve no fim da mensagem; vazio quando não há."""
    match = _SESSION_IN_MESSAGE_RE.search(str(body or ""))
    return match.group(1) if match else ""


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _origin_key(source: str, medium: str, campaign: str) -> tuple[str, str, str]:
    return (source or "(sem origem)", medium or "", campaign or "")


def summarize(
    *,
    lp_events: list[dict],
    first_inbound: dict[str, dict],
    contacts: dict[str, dict],
    lead_states: dict[str, dict],
    start: datetime,
    end: datetime,
) -> dict:
    """`lp_events`: linhas de `lp_events` no período. `first_inbound`: por
    `chat_id`, `{body, at}` da primeira mensagem viva do contato (qualquer data;
    o corte por período é feito aqui). `contacts`: `personal_contacts.json`.
    `lead_states`: `chat_id` -> linha de `lead_state` do motor de follow-up."""
    tz = start.tzinfo or timezone.utc
    terminal = set(TERMINAL_STAGES)

    # Sessão -> o que ela fez e de onde veio. Contagem é por sessão, não por hit.
    sessions: dict[str, dict] = {}
    for row in lp_events:
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        sess = sessions.setdefault(sid, {
            "lp": str(row.get("lp") or ""), "events": set(), "first_at": None,
            "utm_source": "", "utm_medium": "", "utm_campaign": "", "utm_content": "",
        })
        sess["events"].add(str(row.get("event") or ""))
        at = _parse_ts(row.get("ts"))
        if at and (sess["first_at"] is None or at < sess["first_at"]):
            sess["first_at"] = at
        for field in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
            if not sess[field] and row.get(field):
                sess[field] = str(row[field])

    # Chegadas no WhatsApp dentro do período, com origem atribuível.
    arrivals: list[dict] = []
    for chat_id, first in first_inbound.items():
        at = _parse_ts(first.get("at"))
        if at is None or not (start <= at <= end):
            continue
        record = contacts.get(chat_id) or {}
        sid = session_id_from_message(first.get("body", ""))
        sess = sessions.get(sid) if sid else None
        if sess:
            source, medium, campaign = sess["utm_source"] or "lp", sess["utm_medium"], sess["utm_campaign"]
            kind = "lp"
        elif sid:
            source, medium, campaign, kind = "lp", "", "", "lp"
        elif record.get("origin"):
            source, medium, campaign, kind = str(record["origin"]), "nativa", "", "nativa"
        else:
            continue
        lead = lead_states.get(chat_id) or {}
        stage = str(lead.get("stage") or "")
        arrivals.append({
            "chat_id": chat_id,
            "name": str(record.get("name") or ""),
            "kind": kind,
            "session_id": sid,
            "source": source,
            "medium": medium,
            "campaign": campaign,
            "arrived_at": at.astimezone(tz).isoformat(timespec="minutes"),
            "stage": stage,
            "won": stage in WON_STAGES,
        })
    arrivals.sort(key=lambda a: a["arrived_at"], reverse=True)

    # Funil por LP: sessões únicas em cada passo.
    lp_funnel: dict[str, dict] = {}
    for sess in sessions.values():
        row = lp_funnel.setdefault(sess["lp"], {step: 0 for step in FUNNEL})
        for step in FUNNEL:
            if step in sess["events"]:
                row[step] += 1
    arrived_by_sid = {a["session_id"] for a in arrivals if a["session_id"]}
    for lp, row in lp_funnel.items():
        row["arrived"] = sum(1 for sid, s in sessions.items() if s["lp"] == lp and sid in arrived_by_sid)

    # Por origem: sessões e cliques vêm da LP; chegadas, funil e ganhos do WhatsApp.
    by_origin: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"sessions": 0, "clicks": 0, "arrived": 0, "in_funnel": 0, "won": 0}
    )
    for sess in sessions.values():
        row = by_origin[_origin_key(sess["utm_source"] or "lp", sess["utm_medium"], sess["utm_campaign"])]
        row["sessions"] += 1
        if "whatsapp_click" in sess["events"]:
            row["clicks"] += 1
    for arrival in arrivals:
        row = by_origin[_origin_key(arrival["source"], arrival["medium"], arrival["campaign"])]
        row["arrived"] += 1
        if arrival["stage"] and arrival["stage"] not in terminal:
            row["in_funnel"] += 1
        if arrival["won"]:
            row["won"] += 1
    origins = [
        {"source": key[0], "medium": key[1], "campaign": key[2], **row}
        for key, row in by_origin.items()
    ]
    origins.sort(key=lambda o: (-o["arrived"], -o["sessions"], o["source"]))

    # Série diária no fuso comercial: sessões, cliques e chegadas.
    days: dict[str, dict] = {}
    cursor = start.astimezone(tz).date()
    while cursor <= end.astimezone(tz).date():
        days[cursor.isoformat()] = {"date": cursor.isoformat(), "sessions": 0, "clicks": 0, "arrived": 0}
        cursor += timedelta(days=1)
    for sess in sessions.values():
        if sess["first_at"] is None:
            continue
        day = days.get(sess["first_at"].astimezone(tz).date().isoformat())
        if day is None:
            continue
        day["sessions"] += 1
        if "whatsapp_click" in sess["events"]:
            day["clicks"] += 1
    for arrival in arrivals:
        day = days.get(arrival["arrived_at"][:10])
        if day is not None:
            day["arrived"] += 1

    totals = {
        "sessions": len(sessions),
        "clicks": sum(1 for s in sessions.values() if "whatsapp_click" in s["events"]),
        "arrived": len(arrivals),
        "arrived_lp": sum(1 for a in arrivals if a["kind"] == "lp"),
        "arrived_native": sum(1 for a in arrivals if a["kind"] == "nativa"),
        "in_funnel": sum(1 for a in arrivals if a["stage"] and a["stage"] not in terminal),
        "won": sum(1 for a in arrivals if a["won"]),
    }
    return {
        "totals": totals,
        "lps": [{"lp": lp, **row} for lp, row in sorted(lp_funnel.items())],
        "origins": origins,
        "arrivals": arrivals[:200],
        "days": list(days.values()),
    }


# ── carga das fontes ────────────────────────────────────────────────────────

def load_lp_events(panel_db: Path, start: datetime, end: datetime) -> list[dict]:
    conn = _ro(panel_db)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT lp, event, session_id, step, utm_source, utm_medium, utm_campaign, utm_content, ts"
            " FROM lp_events WHERE ts >= ? AND ts <= ? ORDER BY id",
            (start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def load_first_inbound(messages_db: Path) -> dict[str, dict]:
    """Primeira mensagem viva (não histórica) recebida de cada chat, com corpo —
    é nela que a LP deixa o `id:`. Uma `GROUP BY` e uma busca em lote, como
    `_last_messages_all` do `data.py`."""
    conn = _ro(messages_db)
    if conn is None:
        return {}
    try:
        firsts = conn.execute(
            "SELECT chat_id, MIN(timestamp) AS at FROM messages"
            " WHERE from_me = 0 AND is_historical = 0 GROUP BY chat_id"
        ).fetchall()
        pairs = [(str(r["chat_id"]), r["at"]) for r in firsts if r["at"] is not None]
        out: dict[str, dict] = {}
        for offset in range(0, len(pairs), 400):
            chunk = pairs[offset:offset + 400]
            values_sql = ",".join("(?,?)" for _ in chunk)
            params: list[Any] = [v for pair in chunk for v in pair]
            for row in conn.execute(
                "SELECT chat_id, body, timestamp FROM messages"
                f" WHERE from_me = 0 AND (chat_id, timestamp) IN (VALUES {values_sql})",
                params,
            ).fetchall():
                out.setdefault(str(row["chat_id"]), {"body": str(row["body"] or ""), "at": float(row["timestamp"] or 0)})
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def load_lead_states(followups_db: Path) -> dict[str, dict]:
    conn = _ro(followups_db)
    if conn is None:
        return {}
    try:
        return {str(r["chat_id"]): dict(r) for r in conn.execute("SELECT chat_id, stage FROM lead_state")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def report(paths, period: str, *, contacts: dict[str, dict], now: datetime | None = None) -> dict:
    start, now = _period_bounds(period, now)
    result = summarize(
        lp_events=load_lp_events(paths.panel_db, start, now),
        first_inbound=load_first_inbound(paths.messages_db),
        contacts=contacts,
        lead_states=load_lead_states(paths.followups_db),
        start=start,
        end=now,
    )
    result["period"] = period if period in PERIOD_DAYS else "7d"
    return result
