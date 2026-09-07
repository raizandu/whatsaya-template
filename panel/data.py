"""Leitores puros do painel de operação.

Nada aqui envia mensagem, chama LLM ou importa o plugin. Cada função recebe os
caminhos que precisa e devolve dicionários prontos para virar JSON. O plugin
continua dono das escritas; este módulo só lê os mesmos arquivos que ele grava:
`personal_contacts.json`, `whatsapp_messages.db`, `commercial_followups.db`, o
`state.db` do Hermes e os logs espelhados.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import daily_audit
from commercial_followups import CADENCES, TERMINAL_STAGES, render_contextual_message

STAGES = ("new", "qualification", "pricing", "proposal", "payment")
STAGE_LABEL = {
    "new": "Novo",
    "qualification": "Qualificação",
    "pricing": "Preço",
    "proposal": "Proposta",
    "payment": "Pagamento",
}
CADENCE_LABEL = {
    "silence": "Silêncio",
    "proposal": "Proposta",
    "payment": "Pagamento",
    "post_sale": "Pós-venda",
}
CANCEL_REASON_LABEL = {
    "lead_replied": "lead respondeu antes",
    "human_takeover": "você assumiu a conversa",
    "policy_or_context_changed": "etapa ou contexto mudou",
    "lead_not_eligible": "lead saiu da automação",
}
PERIOD_DAYS = {"hoje": 1, "7d": 7, "30d": 30}


@dataclass(frozen=True)
class Paths:
    contacts_json: Path = Path("/opt/data/personal_contacts.json")
    messages_db: Path = Path("/opt/data/.hermes/whatsapp_messages.db")
    followups_db: Path = Path("/opt/data/.hermes/commercial_followups.db")
    state_db: Path = Path("/opt/data/.hermes/state.db")
    plugin_log: Path = Path("/opt/data/.hermes/logs/whatsapp_plugin.log")
    gateway_log: Path = Path("/opt/data/.hermes/logs/gateway.log")
    pricing_json: Path = Path(__file__).with_name("pricing.json")


# ── utilidades ──────────────────────────────────────────────────────────────

def _ro(path: Path) -> sqlite3.Connection | None:
    if not Path(path).is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "").split("@", 1)[0].split(":", 1)[0] if ch.isdigit())


def format_phone(chat_id: str) -> str:
    """`5547999414105@s.whatsapp.net` → `+55 47 9 9941-4105`. LID fica como está."""
    if "@lid" in str(chat_id):
        return "identidade LID"
    d = _digits(chat_id)
    if len(d) == 13 and d.startswith("55"):
        return f"+55 {d[2:4]} {d[4]} {d[5:9]}-{d[9:]}"
    if len(d) == 12 and d.startswith("55"):
        return f"+55 {d[2:4]} {d[4:8]}-{d[8:]}"
    return f"+{d}" if d else str(chat_id)


def _period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Início e fim do período no fuso comercial. `hoje` é o dia corrente."""
    tz = daily_audit.business_tz()
    now = (now or datetime.now(tz)).astimezone(tz)
    days = PERIOD_DAYS.get(period, 7)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _period_days(period: str, now: datetime | None = None) -> list[date]:
    start, end = _period_bounds(period, now)
    return [(start + timedelta(days=i)).date() for i in range((end.date() - start.date()).days + 1)]


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fmt_due(when: datetime | None, now: datetime) -> tuple[str, str]:
    """(`hoje 14:30`, `em 35 min`) no fuso comercial."""
    if when is None:
        return "", ""
    tz = daily_audit.business_tz()
    local = when.astimezone(tz)
    today = now.astimezone(tz).date()
    delta = local - now.astimezone(tz)
    if local.date() == today:
        day = "hoje"
    elif local.date() == today + timedelta(days=1):
        day = "amanhã"
    else:
        day = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[local.weekday()]
        if (local.date() - today).days >= 7:
            day = local.strftime("%d/%m")
    label = f"{day} {local.strftime('%H:%M')}"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 0:
        rel = "atrasado"
    elif minutes < 60:
        rel = f"em {minutes} min"
    elif minutes < 60 * 24:
        rel = f"em {minutes // 60} h {minutes % 60:02d}"
    else:
        rel = f"em {minutes // (60 * 24)} d"
    return label, rel


def _ago(at: datetime | None, now: datetime) -> str:
    if at is None:
        return ""
    seconds = max(0, int((now - at).total_seconds()))
    if seconds < 60:
        return "agora"
    if seconds < 3600:
        return f"há {seconds // 60} min"
    if seconds < 86400:
        return f"há {seconds // 3600} h"
    days = seconds // 86400
    return "ontem" if days == 1 else f"há {days} dias"


# ── contatos ────────────────────────────────────────────────────────────────

def load_contacts(path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _contact_name(contacts: dict, chat_id: str) -> str:
    record = contacts.get(chat_id)
    if isinstance(record, dict) and record.get("name"):
        return str(record["name"])
    digits = _digits(chat_id)
    for key, record in contacts.items():
        if isinstance(record, dict) and record.get("name") and digits and _digits(key) == digits:
            return str(record["name"])
        if isinstance(record, dict) and record.get("name") and record.get("lid") and str(record["lid"]) == chat_id:
            return str(record["name"])
    return format_phone(chat_id)


def blocked_contacts(contacts: dict) -> list[dict]:
    """Bloqueados pelo dono, um por identidade (o mirror `@lid` do mesmo telefone é agrupado)."""
    seen: set[str] = set()
    out: list[dict] = []
    for key, record in contacts.items():
        if not isinstance(record, dict) or record.get("blocked") is not True:
            continue
        identity = _digits(key) if "@lid" not in key else str(record.get("phone") or key)
        if identity in seen:
            continue
        seen.add(identity)
        out.append({
            "chat_id": key,
            "name": str(record.get("name") or format_phone(key)),
            "phone": format_phone(key),
            "reason": str(record.get("ai_disabled_reason") or record.get("manual_relationship") or "bloqueado pelo dono"),
        })
    return sorted(out, key=lambda c: c["name"].lower())


# ── conversas ───────────────────────────────────────────────────────────────

def last_messages(messages_db: Path, chat_ids: list[str]) -> dict[str, dict]:
    """Última mensagem (corpo, quando, quem) por conversa."""
    conn = _ro(messages_db)
    if conn is None or not chat_ids:
        return {}
    out: dict[str, dict] = {}
    try:
        for chat_id in chat_ids:
            row = conn.execute(
                "SELECT body, timestamp, from_me FROM messages"
                " WHERE chat_id = ? AND is_historical = 0 AND body IS NOT NULL AND TRIM(body) != ''"
                " ORDER BY COALESCE(timestamp, 0) DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if row:
                out[chat_id] = {
                    "body": str(row["body"]),
                    "at": float(row["timestamp"] or 0),
                    "from_me": bool(row["from_me"]),
                }
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    return out


def recent_chats(messages_db: Path, since: datetime, limit: int = 30) -> list[dict]:
    """Conversas com mensagem de lead desde `since`, mais recente primeiro."""
    conn = _ro(messages_db)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT chat_id, MAX(COALESCE(timestamp, 0)) AS last_at, COUNT(*) AS n"
            " FROM messages WHERE is_historical = 0 AND from_me = 0 AND timestamp >= ?"
            " GROUP BY chat_id ORDER BY last_at DESC LIMIT ?",
            (since.timestamp(), limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [{"chat_id": r["chat_id"], "last_at": float(r["last_at"]), "inbound": int(r["n"])} for r in rows]


# ── funil e follow-ups ──────────────────────────────────────────────────────

def _lead_rows(followups_db: Path) -> list[dict]:
    conn = _ro(followups_db)
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM lead_state ORDER BY updated_utc DESC").fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _job_rows(followups_db: Path) -> list[dict]:
    conn = _ro(followups_db)
    if conn is None:
        return []
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM followup_jobs ORDER BY due_utc").fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def leads(paths: Paths, now: datetime | None = None) -> dict:
    """Kanban: leads por etapa, com nome, última mensagem e próximo follow-up."""
    now = now or datetime.now(timezone.utc)
    contacts = load_contacts(paths.contacts_json)
    rows = _lead_rows(paths.followups_db)
    jobs = _job_rows(paths.followups_db)
    next_due: dict[str, datetime] = {}
    for job in jobs:
        if job.get("status") in ("pending", "leased"):
            due = _parse_utc(job.get("due_utc"))
            if due and (job["chat_id"] not in next_due or due < next_due[job["chat_id"]]):
                next_due[job["chat_id"]] = due
    last = last_messages(paths.messages_db, [r["chat_id"] for r in rows])
    columns = {stage: [] for stage in STAGES}
    terminal = {"won": 0, "lost": 0}
    for row in rows:
        chat_id = row["chat_id"]
        stage = str(row.get("stage") or "new").lower()
        record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
        if record.get("blocked") is True:
            continue
        if stage in TERMINAL_STAGES or row.get("terminal"):
            terminal["won" if stage in ("ganho", "won", "concluido", "concluída") else "lost"] += 1
            continue
        if stage not in columns:
            stage = "new"
        msg = last.get(chat_id) or {}
        due = next_due.get(chat_id)
        due_label, due_rel = _fmt_due(due, now)
        columns[stage].append({
            "chat_id": chat_id,
            "name": _contact_name(contacts, chat_id),
            "phone": format_phone(chat_id),
            "stage": stage,
            "preview": msg.get("body", "")[:140],
            "last_at": msg.get("at", 0),
            "last": _ago(datetime.fromtimestamp(msg["at"], timezone.utc), now) if msg.get("at") else "",
            "human": bool(row.get("takeover")),
            "automation": bool(row.get("automation_enabled")),
            "next_followup": due_label,
            "next_followup_rel": due_rel,
            "cadence": CADENCE_LABEL.get(str(row.get("cadence_kind") or ""), ""),
        })
    for stage in columns:
        columns[stage].sort(key=lambda c: -c["last_at"])
    return {
        "stages": [{"id": s, "label": STAGE_LABEL[s], "cards": columns[s]} for s in STAGES],
        "terminal": terminal,
        "total": sum(len(v) for v in columns.values()),
    }


def followups(paths: Paths, period: str = "7d", now: datetime | None = None) -> dict:
    """Fila (pendentes), histórico (enviados e cancelados no período) e placar por cadência."""
    now = now or datetime.now(timezone.utc)
    start, _end = _period_bounds(period, now)
    contacts = load_contacts(paths.contacts_json)
    lead_by_chat = {r["chat_id"]: r for r in _lead_rows(paths.followups_db)}
    jobs = _job_rows(paths.followups_db)

    queue: list[dict] = []
    history: list[dict] = []
    per_cadence: dict[str, dict[str, int]] = {k: {"sent": 0, "replied": 0} for k in CADENCES}
    stats = {"sent": 0, "replied": 0, "cancelled": 0, "cancelled_replied": 0}

    for job in jobs:
        chat_id = job["chat_id"]
        lead = lead_by_chat.get(chat_id, {})
        status = str(job.get("status") or "")
        cadence = str(job.get("cadence_kind") or "")
        name = _contact_name(contacts, chat_id)
        base = {
            "id": job["id"],
            "chat_id": chat_id,
            "name": name,
            "stage": STAGE_LABEL.get(str(lead.get("stage") or "new"), "Novo"),
            "cadence": CADENCE_LABEL.get(cadence, cadence),
            "step": int(job.get("step_no") or 1),
        }
        if status in ("pending", "leased"):
            due = _parse_utc(job.get("due_utc"))
            due_label, due_rel = _fmt_due(due, now)
            paused = not bool(lead.get("automation_enabled", 1))
            try:
                text = render_contextual_message({**job, "stage": lead.get("stage")})
            except Exception:
                text = ""
            queue.append({
                **base,
                "due": due_label,
                "due_rel": due_rel,
                "due_utc": due.isoformat() if due else "",
                "soon": bool(due and due - now < timedelta(hours=4)),
                "paused": paused,
                "text": text,
            })
            continue

        updated = _parse_utc(job.get("updated_utc"))
        if updated is None or updated < start:
            continue
        replied = False
        last_inbound = _parse_utc(lead.get("last_inbound_utc"))
        if status == "sent" and last_inbound and last_inbound > updated:
            replied = True
        if status == "sent":
            stats["sent"] += 1
            per_cadence.setdefault(cadence, {"sent": 0, "replied": 0})["sent"] += 1
            if replied:
                stats["replied"] += 1
                per_cadence[cadence]["replied"] += 1
                minutes = int((last_inbound - updated).total_seconds() // 60)
                result, kind = (f"Respondeu em {minutes} min" if minutes < 120 else f"Respondeu em {minutes // 60} h"), "replied"
            else:
                result, kind = "Sem resposta ainda", "waiting"
        elif status == "cancelled":
            stats["cancelled"] += 1
            reason = str(job.get("last_error") or "")
            if reason == "lead_replied":
                stats["cancelled_replied"] += 1
            result, kind = f"Cancelado: {CANCEL_REASON_LABEL.get(reason, reason or 'sem motivo')}", "cancelled"
        elif status == "failed":
            result, kind = f"Falhou: {str(job.get('last_error') or '')[:80]}", "cancelled"
        else:
            continue
        history.append({**base, "when": _ago(updated, now), "at": updated.isoformat(), "result": result, "kind": kind})

    history.sort(key=lambda h: h["at"], reverse=True)
    queue.sort(key=lambda q: q["due_utc"] or "9")
    return {
        "queue": queue,
        "history": history[:40],
        "stats": stats,
        "cadences": [
            {
                "id": k,
                "label": CADENCE_LABEL.get(k, k),
                "steps": " · ".join(f"{n} min" if unit == "business_minutes" and n < 60 else f"{n // 60} h" if unit == "business_minutes" else f"{n} d" for unit, n in CADENCES[k]) + " úteis",
                "sent": v["sent"],
                "replied": v["replied"],
                "rate": round(100 * v["replied"] / v["sent"]) if v["sent"] else 0,
            }
            for k, v in per_cadence.items() if k in CADENCES
        ],
    }


# ── atendimentos (por dia, do log e do banco) ───────────────────────────────

_DAY_CACHE: dict[tuple[str, str], dict] = {}


def day_metrics(paths: Paths, day: date, *, today: date | None = None) -> dict:
    """Um dia de atendimento. Dias passados são imutáveis e ficam em cache no processo."""
    today = today or datetime.now(daily_audit.business_tz()).date()
    key = (str(paths.messages_db), day.isoformat())
    if day < today and key in _DAY_CACHE:
        return _DAY_CACHE[key]

    turns = daily_audit.read_day_turns(paths.messages_db, day)
    events = daily_audit.parse_log_lines(daily_audit.read_day_log_lines(paths.plugin_log, day))
    gateway = daily_audit.parse_gateway_lines(daily_audit.read_gateway_day_lines(paths.gateway_log, day))
    _bot, owner = daily_audit.split_owner_manual(turns, events)
    score = daily_audit.aggregate_events(events)

    chats = {t.chat_id for t in turns if not t.from_me}
    human_chats = {t.chat_id for t in owner} | {chat for chat, _reason in score.handoffs}
    handoffs = []
    owner_after: dict[str, datetime] = {}
    for t in owner:
        owner_after[t.chat_id] = max(owner_after.get(t.chat_id, t.at), t.at)
    for event in events:
        if event.tag != "handoff" or "motivo" not in event.fields:
            continue
        answered = event.chat_id in owner_after and event.at is not None and owner_after[event.chat_id] > event.at
        handoffs.append({
            "chat_id": event.chat_id,
            "reason": daily_audit._unquote(event.fields["motivo"]),
            "at": event.at.isoformat() if event.at else "",
            "answered": answered,
        })
    result = {
        "day": day.isoformat(),
        "chats": len(chats),
        "ai_resolved": len(chats - human_chats),
        "human": len(chats & human_chats),
        "lead_messages": sum(1 for t in turns if not t.from_me),
        "owner_manual": len(owner),
        "handoffs": handoffs,
        "unanswered": [{"chat_id": u.chat_id, "waited_s": u.waited_s} for u in score.unanswered],
        "model_seconds": round(sum(t.seconds for t in gateway), 1),
        "api_calls": sum(t.api_calls for t in gateway),
    }
    if day < today:
        _DAY_CACHE[key] = result
    return result


def metrics(paths: Paths, period: str = "7d", now: datetime | None = None, *, minutes_per_resolved: float = 6.0) -> dict:
    """Agrega os dias do período para a visão geral."""
    tz = daily_audit.business_tz()
    now = (now or datetime.now(tz)).astimezone(tz)
    days = _period_days(period, now)
    per_day = [day_metrics(paths, d, today=now.date()) for d in days]
    contacts = load_contacts(paths.contacts_json)
    total = sum(d["chats"] for d in per_day)
    ai = sum(d["ai_resolved"] for d in per_day)
    pending = [
        {**h, "name": _contact_name(contacts, h["chat_id"]), "phone": format_phone(h["chat_id"])}
        for d in per_day for h in d["handoffs"] if not h["answered"]
    ]
    pending.sort(key=lambda h: h["at"], reverse=True)
    return {
        "period": period,
        "total": total,
        "ai_resolved": ai,
        "human": total - ai,
        "lead_messages": sum(d["lead_messages"] for d in per_day),
        "minutes_saved": round(ai * minutes_per_resolved),
        "api_calls": sum(d["api_calls"] for d in per_day),
        "model_seconds": round(sum(d["model_seconds"] for d in per_day), 1),
        "handoffs_pending": pending[:10],
        "unanswered": [u for d in per_day[-1:] for u in d["unanswered"]],
        "series": [
            {
                "day": d["day"],
                "label": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[date.fromisoformat(d["day"]).weekday()] if period != "30d" else date.fromisoformat(d["day"]).strftime("%d/%m"),
                "ai": d["ai_resolved"],
                "human": d["human"],
            }
            for d in per_day
        ],
    }


# ── tokens e custo (state.db do Hermes) ─────────────────────────────────────

def load_pricing(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"usd_brl": 5.0, "models": {}}
    if not isinstance(raw, dict):
        return {"usd_brl": 5.0, "models": {}}
    raw.setdefault("models", {})
    raw.setdefault("usd_brl", 5.0)
    return raw


def _price(pricing: dict, model: str, tokens: dict) -> tuple[float, bool]:
    """Custo em US$ pela tabela; (0, False) quando o modelo não tem preço preenchido."""
    table = pricing.get("models", {}).get(model) or pricing.get("models", {}).get(model.split("/")[-1])
    if not isinstance(table, dict):
        return 0.0, False
    if not any(float(table.get(k) or 0) > 0 for k in ("input", "output", "cached_input")):
        return 0.0, False
    fresh_input = max(0, tokens["input"] - tokens["cache_read"])
    usd = (
        fresh_input * float(table.get("input") or 0)
        + tokens["cache_read"] * float(table.get("cached_input") or 0)
        + (tokens["output"] + tokens["reasoning"]) * float(table.get("output") or 0)
    ) / 1_000_000
    return usd, True


def usage(paths: Paths, period: str = "7d", now: datetime | None = None) -> dict:
    """Tokens por modelo das sessões de WhatsApp no período, com custo pela tabela de preços."""
    tz = daily_audit.business_tz()
    now = (now or datetime.now(tz)).astimezone(tz)
    start, _end = _period_bounds(period, now)
    pricing = load_pricing(paths.pricing_json)
    conn = _ro(paths.state_db)
    rows: list[sqlite3.Row] = []
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT u.model, u.billing_provider, u.billing_mode, u.api_call_count,"
                " u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens,"
                " u.reasoning_tokens, u.estimated_cost_usd, u.actual_cost_usd, u.last_seen"
                " FROM session_model_usage u JOIN sessions s ON s.id = u.session_id"
                " WHERE s.source = 'whatsapp' AND u.last_seen >= ?",
                (start.timestamp(),),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()

    by_model: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    for r in rows:
        model = str(r["model"] or "?")
        entry = by_model.setdefault(model, {
            "model": model,
            "provider": str(r["billing_provider"] or ""),
            "included": str(r["billing_mode"] or "") == "subscription_included",
            "calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0,
            "reported_usd": 0.0,
        })
        entry["calls"] += int(r["api_call_count"] or 0)
        for col, key in (("input_tokens", "input"), ("output_tokens", "output"), ("cache_read_tokens", "cache_read"),
                         ("cache_write_tokens", "cache_write"), ("reasoning_tokens", "reasoning")):
            entry[key] += int(r[col] or 0)
        entry["reported_usd"] += float(r["actual_cost_usd"] or r["estimated_cost_usd"] or 0)
        day = datetime.fromtimestamp(float(r["last_seen"] or 0), tz).date().isoformat()
        d = by_day.setdefault(day, {"day": day, "input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "usd": 0.0, "priced": True})
        for key in ("input", "output", "cache_read", "reasoning"):
            d[key] += int(r[{"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_tokens", "reasoning": "reasoning_tokens"}[key]] or 0)
        usd, priced = _price(pricing, model, {
            "input": int(r["input_tokens"] or 0), "output": int(r["output_tokens"] or 0),
            "cache_read": int(r["cache_read_tokens"] or 0), "reasoning": int(r["reasoning_tokens"] or 0),
        })
        if not priced and entry["reported_usd"] > 0 and not entry["included"]:
            usd, priced = float(r["actual_cost_usd"] or r["estimated_cost_usd"] or 0), True
        d["usd"] += usd
        d["priced"] = d["priced"] and priced

    total_usd = 0.0
    any_unpriced = False
    models = []
    for entry in by_model.values():
        usd, priced = _price(pricing, entry["model"], entry)
        if not priced and entry["reported_usd"] > 0 and not entry["included"]:
            usd, priced = entry["reported_usd"], True
        any_unpriced = any_unpriced or not priced
        total_usd += usd
        models.append({**entry, "usd": round(usd, 4), "priced": priced, "tokens": entry["input"] + entry["output"] + entry["reasoning"]})
    models.sort(key=lambda m: -m["tokens"])
    usd_brl = float(pricing.get("usd_brl") or 0)
    days = _period_days(period, now)
    series = []
    for d in days:
        row = by_day.get(d.isoformat(), {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "usd": 0.0, "priced": True})
        series.append({
            "day": d.isoformat(),
            "label": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[d.weekday()] if period != "30d" else d.strftime("%d/%m"),
            "tokens": row["input"] + row["output"] + row["reasoning"],
            "usd": round(row["usd"], 4),
            "brl": round(row["usd"] * usd_brl, 2),
        })
    return {
        "period": period,
        "models": models,
        "input": sum(m["input"] for m in models),
        "output": sum(m["output"] for m in models),
        "cache_read": sum(m["cache_read"] for m in models),
        "reasoning": sum(m["reasoning"] for m in models),
        "calls": sum(m["calls"] for m in models),
        "usd": round(total_usd, 4),
        "brl": round(total_usd * usd_brl, 2),
        "usd_brl": usd_brl,
        "unpriced": any_unpriced,
        "subscription_brl_month": float(pricing.get("codex_subscription_brl_month") or 0),
        "series": series,
    }
