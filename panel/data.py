"""Leitores puros do painel de operação.

Nada aqui envia mensagem, chama LLM ou importa o plugin. Cada função recebe os
caminhos que precisa e devolve dicionários prontos para virar JSON. O plugin
continua dono das escritas; este módulo só lê os mesmos arquivos que ele grava:
`personal_contacts.json`, `whatsapp_messages.db`, `commercial_followups.db`, o
`state.db` do Hermes e os logs espelhados.
"""
from __future__ import annotations

import json
import re
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
    """`5511999999999@s.whatsapp.net` → telefone BR formatado. LID fica como está."""
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


BLOCK_REASON_LABEL = {
    "panel_block": "bloqueado pelo painel",
    "owner_block": "bloqueado pelo dono",
    "owner_blocked": "bloqueado pelo dono",
    "personal_contact": "contato pessoal",
    "legacy_sync_not_in_flow": "sync antigo, fora do fluxo",
    "owner_unblock_reset_pending": "desbloqueio pendente",
    "panel_unblock_reset_pending": "desbloqueio pendente",
    "prompt_injection": "tentativa de prompt injection",
    "spam": "spam",
}


_PLACEHOLDER_NAME_RE = re.compile(r"^(?:contato\s*)?\+?[\d\s\-()]{6,}$", re.IGNORECASE)


def _is_placeholder_name(name: str) -> bool:
    """"Contato 5511999999999" e o próprio número não são nome de gente."""
    return bool(_PLACEHOLDER_NAME_RE.match(str(name or "").strip())) or not str(name or "").strip()


def build_identity_map(contacts: dict, lid_map: dict | None = None) -> dict[str, str]:
    """{chave do contato: identidade da pessoa}.

    O mesmo contato existe como telefone e como `@lid`, e o vínculo nem sempre
    está no campo `lid` do registro — em 24/08 nenhum dos dois números de teste
    tinha esse campo. A fonte confiável é o mapa `lidToPhone` do bridge; o campo
    declarado entra como reforço.
    """
    lid_map = {str(k): str(v) for k, v in (lid_map or {}).items()}
    identity: dict[str, str] = {}
    for key in contacts:
        digits = _digits(key)
        resolved = lid_map.get(digits)
        if resolved and resolved != digits:
            identity[key] = resolved
        elif str(key).endswith("@lid"):
            identity[key] = f"lid:{digits or key}"
        else:
            identity[key] = digits or str(key)
    for key, record in contacts.items():
        if not isinstance(record, dict) or str(key).endswith("@lid"):
            continue
        declared = str(record.get("lid") or "").strip()
        if declared and declared in identity:
            identity[declared] = identity[key]
    return identity


def blocked_contacts(contacts: dict, lid_map: dict | None = None) -> list[dict]:
    """Bloqueados pelo dono, uma linha por pessoa.

    Telefone e espelho `@lid` do mesmo contato viram uma linha só; a linha fica
    com a identidade do telefone e com o nome que não for placeholder.
    """
    identity_of = build_identity_map(contacts, lid_map)
    grouped: dict[str, dict] = {}
    for key, record in contacts.items():
        if not isinstance(record, dict) or record.get("blocked") is not True:
            continue
        identity = identity_of.get(key, str(key))
        reason = str(record.get("ai_disabled_reason") or record.get("manual_relationship") or "owner_block")
        phone = format_phone(identity) if not identity.startswith("lid:") else format_phone(key)
        row = {
            "chat_id": key,
            "identity": identity,
            "name": str(record.get("name") or "").strip() or phone,
            "phone": phone,
            "reason": BLOCK_REASON_LABEL.get(reason, reason.replace("_", " ")),
            "_placeholder": _is_placeholder_name(record.get("name")),
            "_is_lid": str(key).endswith("@lid"),
        }
        current = grouped.get(identity)
        if current is None:
            grouped[identity] = row
            continue
        # A chave de telefone manda na identidade; o nome de gente vence o placeholder.
        keep, drop = (row, current) if (current["_is_lid"] and not row["_is_lid"]) else (current, row)
        if keep["_placeholder"] and not drop["_placeholder"]:
            keep["name"], keep["_placeholder"] = drop["name"], False
        grouped[identity] = keep
    out = []
    for row in grouped.values():
        if row["_placeholder"]:
            row["name"] = row["phone"]
        out.append({k: v for k, v in row.items() if not k.startswith("_")})
    return sorted(out, key=lambda c: c["name"].lower())


# ── conversas ───────────────────────────────────────────────────────────────

def last_messages(messages_db: Path, chat_ids: list[str]) -> dict[str, dict]:
    """Última mensagem do lead (corpo e quando) por conversa. O que a AYA respondeu
    não vira prévia do card: o dono quer ver o que o lead disse por último."""
    conn = _ro(messages_db)
    if conn is None or not chat_ids:
        return {}
    out: dict[str, dict] = {}
    try:
        for chat_id in chat_ids:
            row = conn.execute(
                "SELECT body, timestamp, from_me FROM messages"
                " WHERE chat_id = ? AND is_historical = 0 AND from_me = 0"
                " AND body IS NOT NULL AND TRIM(body) != ''"
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

def _contact_aliases(contacts: dict, chat_id: str, lid_map: dict | None = None) -> list[str]:
    identities = build_identity_map(contacts, lid_map)
    identity = identities.get(chat_id)
    aliases = [chat_id]
    if identity:
        aliases.extend(key for key, value in identities.items() if value == identity and key != chat_id)
    return list(dict.fromkeys(aliases))


def _conversation_rows(messages_db: Path, chat_ids: list[str]) -> list[dict]:
    conn = _ro(messages_db)
    if conn is None or not chat_ids:
        return []
    try:
        placeholders = ",".join("?" for _chat_id in chat_ids)
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, chat_id, message_id, message_type, body, timestamp, from_me, has_media, media_type"
                f" FROM messages WHERE chat_id IN ({placeholders}) AND is_historical = 0"
                " AND timestamp IS NOT NULL ORDER BY timestamp, id",
                chat_ids,
            ).fetchall()
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    rank = {value: index for index, value in enumerate(chat_ids)}
    by_message_id: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("message_id") or row.get("id"))
        current = by_message_id.get(key)
        score = (bool(str(row.get("body") or "").strip()), -rank.get(str(row.get("chat_id")), len(rank)))
        current_score = (
            bool(str(current.get("body") or "").strip()),
            -rank.get(str(current.get("chat_id")), len(rank)),
        ) if current else None
        if current is None or score > current_score:
            by_message_id[key] = row
    return sorted(by_message_id.values(), key=lambda row: (float(row.get("timestamp") or 0), int(row.get("id") or 0)))


def _conversation_body(row: dict) -> str:
    body = str(row.get("body") or "").strip()
    if body:
        return body
    media = str(row.get("media_type") or row.get("message_type") or "").lower()
    if "audio" in media or "ptt" in media:
        return "Áudio recebido"
    if row.get("has_media"):
        return "Mídia recebida"
    return ""


def _conversation_log_events(log_path: Path, days: set[str]) -> list[daily_audit.AuditEvent]:
    if not days:
        return []
    base = Path(log_path)
    files = (
        [path for path in base.parent.glob(base.name + "*") if path.is_file()]
        if base.parent.is_dir()
        else []
    )
    lines: list[str] = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if len(line) >= 11 and line[:10] in days and line[10] == "T":
                    lines.append(line)
        except OSError:
            continue
    return daily_audit.parse_log_lines(lines)


def _mark_conversation_owners(
    rows: list[dict], plugin_log: Path, chat_ids: list[str]
) -> list[daily_audit.AuditEvent]:
    tz = daily_audit.business_tz()
    paired: list[tuple[dict, daily_audit.Turn]] = []
    for row in rows:
        if not _conversation_body(row):
            continue
        turn = daily_audit.Turn(
            chat_id=chat_ids[0],
            at=datetime.fromtimestamp(float(row.get("timestamp") or 0), tz),
            from_me=bool(row.get("from_me")),
            body=str(row.get("body") or "").strip(),
        )
        paired.append((row, turn))
    days = {turn.at.date().isoformat() for _row, turn in paired}
    events = [
        event
        for event in _conversation_log_events(plugin_log, days)
        if event.chat_id in chat_ids
    ]
    owner_ids: set[int] = set()
    for day in days:
        day_turns = [turn for _row, turn in paired if turn.at.date().isoformat() == day]
        day_events = [
            daily_audit.AuditEvent(
                tag=event.tag,
                fields=event.fields,
                raw=event.raw,
                chat_id=chat_ids[0],
                at=event.at,
            )
            for event in events
            if event.at is not None and event.at.date().isoformat() == day
        ]
        _bot, owner = daily_audit.split_owner_manual(day_turns, day_events)
        owner_ids.update(id(turn) for turn in owner)
    for row, turn in paired:
        row["owner"] = "lead" if not turn.from_me else "owner" if id(turn) in owner_ids else "aya"
    return events


def _message_timeline(rows: list[dict], flow_events: list[dict] | None = None) -> list[dict]:
    atoms: list[dict] = list(flow_events or [])
    tz = daily_audit.business_tz()
    for row in rows:
        body = _conversation_body(row)
        if not body:
            continue
        at = datetime.fromtimestamp(float(row.get("timestamp") or 0), tz)
        owner = str(row.get("owner") or ("aya" if row.get("from_me") else "lead"))
        bubble = {
            "message_id": str(row.get("message_id") or ""),
            "body": body,
            "media_type": str(row.get("media_type") or (row.get("message_type") if row.get("has_media") else "") or ""),
        }
        atoms.append({
            "type": "message",
            "owner": owner,
            "at": at.isoformat(),
            "last_at": at.isoformat(),
            "bubbles": [bubble],
        })
    atoms.sort(key=lambda item: item["at"])
    timeline: list[dict] = []
    for item in atoms:
        previous = timeline[-1] if timeline else None
        if (
            item["type"] == "message"
            and previous
            and previous["type"] == "message"
            and previous["owner"] == item["owner"]
            and (
                datetime.fromisoformat(item["at"]) - datetime.fromisoformat(previous["last_at"])
            ).total_seconds() <= daily_audit.REPLY_GAP_S
        ):
            previous["bubbles"].extend(item["bubbles"])
            previous["last_at"] = item["last_at"]
            continue
        timeline.append(item)
    return timeline


def _flow_timeline(paths: Paths, chat_id: str, events: list[daily_audit.AuditEvent]) -> list[dict]:
    tz = daily_audit.business_tz()
    timeline = [
        {
            "type": "event",
            "event": "handoff",
            "at": event.at.isoformat(),
            "label": "Conversa encaminhada para você",
            "reason": daily_audit._unquote(event.fields.get("motivo", "")),
        }
        for event in events
        if event.tag == "handoff" and event.at is not None and "motivo" in event.fields
    ]
    followup_labels = {
        "sent": "Toque de follow-up enviado",
        "cancelled": "Toque de follow-up cancelado",
        "failed": "Falha no toque de follow-up",
        "manual_review": "Follow-up enviado para revisão",
        "uncertain": "Envio do follow-up incerto",
    }
    for job in _job_rows(paths.followups_db):
        status = str(job.get("status") or "")
        if job.get("chat_id") != chat_id or status not in followup_labels:
            continue
        at = _parse_utc(job.get("updated_utc"))
        if at is None:
            continue
        timeline.append({
            "type": "event",
            "event": "followup",
            "at": at.astimezone(tz).isoformat(),
            "label": followup_labels[status],
            "status": status,
            "step": int(job.get("step_no") or 0),
            "cadence": CADENCE_LABEL.get(str(job.get("cadence_kind") or ""), ""),
            "reason": CANCEL_REASON_LABEL.get(str(job.get("last_error") or ""), str(job.get("last_error") or "")),
        })
    return timeline


def _session_usage_for_chat(state_db: Path, chat_ids: list[str]) -> dict:
    empty = {"sessions": 0, "calls": 0, "tokens": 0, "model": ""}
    conn = _ro(state_db)
    if conn is None:
        return empty
    try:
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if not {"id", "source", "user_id"}.issubset(session_columns):
            return empty
        user_placeholders = ",".join("?" for _chat_id in chat_ids)
        identity_terms = [f"s.user_id IN ({user_placeholders})"]
        params: list[Any] = list(chat_ids)
        if "chat_id" in session_columns:
            identity_terms.append(f"s.chat_id IN ({user_placeholders})")
            params.extend(chat_ids)
        rows = conn.execute(
            "SELECT s.id, u.model, u.api_call_count, u.input_tokens, u.output_tokens, u.reasoning_tokens"
            " FROM sessions s JOIN session_model_usage u ON u.session_id = s.id"
            " WHERE s.source = 'whatsapp' AND (" + " OR ".join(identity_terms) + ")",
            params,
        ).fetchall()
    except sqlite3.Error:
        return empty
    finally:
        conn.close()
    if not rows:
        return empty
    by_model: dict[str, int] = {}
    for row in rows:
        model = str(row["model"] or "")
        tokens = int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0) + int(row["reasoning_tokens"] or 0)
        by_model[model] = by_model.get(model, 0) + tokens
    return {
        "sessions": len({str(row["id"]) for row in rows}),
        "calls": sum(int(row["api_call_count"] or 0) for row in rows),
        "tokens": sum(by_model.values()),
        "model": max(by_model, key=by_model.get) if by_model else "",
    }


def lead_detail(
    paths: Paths, chat_id: str, now: datetime | None = None, *, lid_map: dict | None = None
) -> dict:
    """Conversa viva de um lead, pronta para a tela de detalhe."""
    contacts = load_contacts(paths.contacts_json)
    record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
    chat_ids = _contact_aliases(contacts, chat_id, lid_map)
    rows = _conversation_rows(paths.messages_db, chat_ids)
    events = _mark_conversation_owners(rows, paths.plugin_log, chat_ids)
    timeline = _message_timeline(rows, _flow_timeline(paths, chat_id, events))
    lead = next((row for row in _lead_rows(paths.followups_db) if row.get("chat_id") == chat_id), {})
    open_jobs = [
        job for job in _job_rows(paths.followups_db)
        if job.get("chat_id") == chat_id and job.get("status") in ("pending", "leased")
    ]
    next_job = min(open_jobs, key=lambda job: str(job.get("due_utc") or "9"), default={})
    stage = str(lead.get("stage") or "new")
    return {
        "chat_id": chat_id,
        "name": _contact_name(contacts, chat_id),
        "phone": format_phone(chat_id),
        "profile": {
            "relationship": str(record.get("manual_relationship") or record.get("relationship") or ""),
            "notes": str(record.get("notes") or ""),
            "summary": str(record.get("summary") or record.get("full_summary") or ""),
            "tone": str(record.get("tone") or ""),
        },
        "lead": {
            "stage": stage,
            "stage_label": STAGE_LABEL.get(stage, stage.replace("_", " ").title()),
            "cadence": CADENCE_LABEL.get(str(lead.get("cadence_kind") or ""), ""),
            "automation_enabled": bool(lead.get("automation_enabled")),
            "takeover": bool(lead.get("takeover")),
            "blocked": record.get("blocked") is True,
            "next_followup_utc": str(next_job.get("due_utc") or ""),
            "next_followup_step": int(next_job.get("step_no") or 0),
        },
        "usage": _session_usage_for_chat(paths.state_db, chat_ids),
        "timeline": timeline,
    }


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
        d = by_day.setdefault(day, {"day": day, "input": 0, "output": 0, "cache_read": 0, "reasoning": 0,
                                    "usd": 0.0, "usd_billed": 0.0, "priced": True})
        for key in ("input", "output", "cache_read", "reasoning"):
            d[key] += int(r[{"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_tokens", "reasoning": "reasoning_tokens"}[key]] or 0)
        usd, priced = _price(pricing, model, {
            "input": int(r["input_tokens"] or 0), "output": int(r["output_tokens"] or 0),
            "cache_read": int(r["cache_read_tokens"] or 0), "reasoning": int(r["reasoning_tokens"] or 0),
        })
        if not priced and entry["reported_usd"] > 0 and not entry["included"]:
            usd, priced = float(r["actual_cost_usd"] or r["estimated_cost_usd"] or 0), True
        d["usd"] += usd
        if not entry["included"]:
            d["usd_billed"] = d.get("usd_billed", 0.0) + usd
        d["priced"] = d["priced"] and priced

    # Dois totais, e a diferença entre eles é a pergunta que o painel responde:
    # `billed` é dinheiro que sai por token; `equivalent` é quanto o mesmo tráfego
    # custaria se tudo fosse API, incluindo o que hoje entra na assinatura.
    equivalent_usd = 0.0
    billed_usd = 0.0
    any_unpriced = False
    models = []
    for entry in by_model.values():
        usd, priced = _price(pricing, entry["model"], entry)
        if not priced and entry["reported_usd"] > 0 and not entry["included"]:
            usd, priced = entry["reported_usd"], True
        any_unpriced = any_unpriced or not priced
        equivalent_usd += usd
        if not entry["included"]:
            billed_usd += usd
        models.append({**entry, "usd": round(usd, 4), "priced": priced, "tokens": entry["input"] + entry["output"] + entry["reasoning"]})
    models.sort(key=lambda m: -m["tokens"])
    usd_brl = float(pricing.get("usd_brl") or 0)
    subscription_usd = float(pricing.get("subscription_usd_month") or 0)
    days = _period_days(period, now)
    series = []
    for d in days:
        row = by_day.get(d.isoformat(), {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0,
                                         "usd": 0.0, "usd_billed": 0.0, "priced": True})
        series.append({
            "day": d.isoformat(),
            "label": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")[d.weekday()] if period != "30d" else d.strftime("%d/%m"),
            "tokens": row["input"] + row["output"] + row["reasoning"],
            "usd": round(row["usd"], 4),
            "brl": round(row["usd"] * usd_brl, 2),
            "brl_billed": round(row.get("usd_billed", 0.0) * usd_brl, 2),
        })
    return {
        "period": period,
        "models": models,
        "input": sum(m["input"] for m in models),
        "output": sum(m["output"] for m in models),
        "cache_read": sum(m["cache_read"] for m in models),
        "reasoning": sum(m["reasoning"] for m in models),
        "calls": sum(m["calls"] for m in models),
        "usd": round(equivalent_usd, 4),
        "brl": round(equivalent_usd * usd_brl, 2),
        "usd_billed": round(billed_usd, 4),
        "brl_billed": round(billed_usd * usd_brl, 2),
        "usd_brl": usd_brl,
        "unpriced": any_unpriced,
        "pricing_updated_at": str(pricing.get("updated_at") or ""),
        # A assinatura é guardada em dólar e convertida aqui: assim trocar o câmbio
        # move os dois números juntos, em vez de deixá-los desencontrados.
        "subscription_usd_month": subscription_usd,
        "subscription_brl_month": round(subscription_usd * usd_brl, 2),
        "subscription_plan": str(pricing.get("subscription_plan") or ""),
        "series": series,
    }
