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
import reactivation_store
from commercial_followups import CADENCES, TERMINAL_STAGES, render_contextual_message

STAGES = ("new", "qualification", "pricing", "proposal", "payment")
STAGE_LABEL = {
    "new": "Novo",
    "qualification": "Qualificação",
    "pricing": "Preço",
    "proposal": "Proposta",
    "payment": "Pagamento",
}

# Presets do funil do painel. Cada estágio é (id, label, engine_stage, terminal):
# `id`/`label` são o que o painel mostra; `engine_stage` é pra onde isso mapeia
# no FollowupEngine, que só conhece STAGES acima. O engine não ganha estágio
# novo — a gente só reaproveita os dele.
PIPELINES: dict[str, dict] = {
    "default": {
        "id": "default",
        "stages": (
            ("new", "Novo", "new", False),
            ("qualification", "Qualificação", "qualification", False),
            ("pricing", "Preço", "pricing", False),
            ("proposal", "Proposta", "proposal", False),
            ("payment", "Pagamento", "payment", False),
        ),
    },
    "therapify": {
        "id": "therapify",
        "stages": (
            ("new", "Novo", "new", False),
            ("in_funnel", "No funil", "qualification", False),
            ("scheduled_session", "Sessão agendada", "proposal", False),
            ("purchased_gravado", "Comprou R$47", "payment", True),
            ("purchased_protocolo_final", "Comprou R$27", "payment", True),
            ("lost", "Perdido", "lost", True),
        ),
        "session_price_brl": 247,
        "products": {
            "metodo_gravado": ("Método gravado", 47),
            "protocolo_final": ("Protocolo final", 27),
        },
    },
}


def pipeline(pipeline_id: str) -> dict:
    """Preset do funil pelo id; vazio ou desconhecido cai no `default`."""
    return PIPELINES.get(str(pipeline_id or "").strip()) or PIPELINES["default"]


def pipeline_from_config(custom: dict) -> dict:
    """Preset declarado em `panel.config.json` (`{"pipeline": "therapify"}`)."""
    custom = custom if isinstance(custom, dict) else {}
    return pipeline(str(custom.get("pipeline") or ""))


def resolve_pipeline_stage(
    preset: dict, *, contact_record: dict | None, lead_row: dict | None, therapify_row: dict | None
) -> str | None:
    """Etapa do preset pra um lead. `None` significa "fora do board" (paciente
    já existente, fora do funil comercial).

    Ordem de decisão: escolha explícita do painel > status bruto migrado do
    Therapify > mapa reverso do estágio do engine. Pro preset `default` só a
    escolha explícita e o mapa reverso valem — o estágio do engine já é o
    id do preset."""
    stage_ids = {stage_id for stage_id, _label, _engine_stage, _terminal in preset["stages"]}
    contact_record = contact_record or {}
    override = str(contact_record.get("pipeline_stage") or "").strip()
    if override in stage_ids:
        return override

    engine_stage = str((lead_row or {}).get("stage") or "").strip().lower()

    if preset["id"] == "therapify":
        therapify_row = therapify_row or {}
        status = str(therapify_row.get("status") or "").strip().lower()
        if status == "existing_patient" or bool(therapify_row.get("is_existing_patient")):
            return None
        if status in stage_ids:
            return status
        if engine_stage in ("won", "ganho", "concluido", "concluída"):
            return None
        if engine_stage in ("lost", "perdido", "cancelled", "cancelado"):
            return "lost"
        if engine_stage in ("qualification", "pricing", "proposal", "payment"):
            return "in_funnel"
        return "new"

    return engine_stage if engine_stage in stage_ids else "new"


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
    workspace_dir: Path = Path("/opt/data/.hermes/workspace")


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


# ── classificação da triagem ────────────────────────────────────────────────

_CLASSIFICATION_CACHE: dict[str, dict] = {}


def load_classification(workspace_dir: Path) -> dict[str, dict]:
    """Índice `{identidade: record}` de `whatsapp_classification.json` (skill de
    triagem do histórico). `{}` quando o arquivo não existe ou é inválido.

    Cada record casa por telefone-dígitos e, quando o `chat_id` original é um
    `@lid`, também pela chave `@lid` inteira — mesma dualidade que
    `build_identity_map` resolve pros contatos. Reparseia só quando o mtime do
    arquivo muda; entre uma chamada e outra dentro de 60 s nem olha o disco de
    novo (a base tem ~1.600 identidades, não vale a pena bater `stat()` a cada
    request do painel)."""
    path = Path(workspace_dir) / "whatsapp_classification.json"
    cache_key = str(path)
    cached = _CLASSIFICATION_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached["checked_at"] < 60:
        return cached["index"]
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _CLASSIFICATION_CACHE[cache_key] = {"checked_at": now, "mtime": None, "index": {}}
        return {}
    if cached and cached.get("mtime") == mtime:
        cached["checked_at"] = now
        return cached["index"]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    records = raw.get("records") if isinstance(raw, dict) else None
    index: dict[str, dict] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        chat_id = str(record.get("chat_id") or "").strip()
        if not chat_id:
            continue
        digits = _digits(chat_id)
        if digits:
            index[digits] = record
        if chat_id.endswith("@lid"):
            index[chat_id] = record
    _CLASSIFICATION_CACHE[cache_key] = {"checked_at": now, "mtime": mtime, "index": index}
    return index


def _triage_lookup(classification: dict, aliases: list[str]) -> dict | None:
    """Registro de classificação de uma identidade, tentando cada alias (telefone
    ou `@lid`) que ela tiver."""
    for alias in aliases:
        alias = str(alias or "")
        if not alias:
            continue
        digits = _digits(alias)
        if digits and digits in classification:
            return classification[digits]
        if alias.endswith("@lid") and alias in classification:
            return classification[alias]
    return None


def _triage_public(record: dict | None, *, include_evidence: bool = False) -> dict | None:
    """Recorte da classificação pra virar JSON: só os campos que a tela usa."""
    if not record:
        return None
    out = {
        "flag": record.get("flag"),
        "stage": record.get("stage"),
        "confidence": record.get("confidence"),
        "summary": record.get("summary"),
        "next_action": record.get("next_action"),
        "automation": record.get("automation"),
    }
    if include_evidence:
        out["evidence"] = [str(item) for item in (record.get("evidence") or []) if str(item or "").strip()]
    return out


_AI_LABEL = {
    "blocked": "Bloqueado",
    "human": "Com humano",
    "reactivation": "Reativação",
    "scope_pending": "Aguardando escopo",
    "off": "IA desligada (legado)",
    "paused": "Follow-up pausado",
    "on": "AYA atendendo",
}


def _contact_kind(*, blocked: bool, flow_origin: str, ai_disabled_reason: str | None, reactivation_pending: bool) -> str:
    """`blocked|reactivation|legacy|active` — mesma prioridade em todo lugar que
    classifica um contato (diretório e detalhe do lead)."""
    if blocked:
        return "blocked"
    if flow_origin == "reactivation_optin" or reactivation_pending:
        return "reactivation"
    if ai_disabled_reason == "legacy_history":
        return "legacy"
    return "active"


def _ai_status(
    *, kind: str, ai_enabled: bool, ai_disabled_reason: str | None, human: bool, automation: bool, has_lead: bool,
) -> dict:
    """`{"enabled", "reason", "label"}` — o mesmo objeto pro diretório e pro
    detalhe do lead. Ordem de prioridade: bloqueio > humano na conversa >
    reativação em andamento > motivo específico de IA desligada > follow-up
    pausado > atendendo normalmente."""
    reason = ai_disabled_reason if not ai_enabled else None
    if kind == "blocked":
        return {"enabled": False, "reason": reason or "owner_block", "label": _AI_LABEL["blocked"]}
    if human:
        return {"enabled": ai_enabled, "reason": reason, "label": _AI_LABEL["human"]}
    if kind == "reactivation":
        return {"enabled": ai_enabled, "reason": reason, "label": _AI_LABEL["reactivation"]}
    if not ai_enabled:
        if reason == "commercial_scope_unconfirmed":
            return {"enabled": False, "reason": reason, "label": _AI_LABEL["scope_pending"]}
        if reason == "legacy_history":
            return {"enabled": False, "reason": reason, "label": _AI_LABEL["off"]}
        return {"enabled": False, "reason": reason, "label": "IA desligada"}
    if has_lead and not automation:
        return {"enabled": True, "reason": None, "label": _AI_LABEL["paused"]}
    return {"enabled": True, "reason": None, "label": _AI_LABEL["on"]}


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


def _last_messages_all(messages_db: Path) -> dict[str, dict]:
    """Última mensagem (viva ou histórica) de cada `chat_id` da base inteira, numa
    passada só: uma `GROUP BY` pra achar o `MAX(timestamp)` de cada chat, depois
    uma busca em lote pelo corpo dessas linhas. A base tem ~84 mil linhas e 908
    chats — nunca uma query por contato aqui."""
    conn = _ro(messages_db)
    if conn is None:
        return {}
    try:
        max_rows = conn.execute(
            "SELECT chat_id, MAX(timestamp) AS at FROM messages"
            " WHERE body IS NOT NULL AND TRIM(body) != '' GROUP BY chat_id"
        ).fetchall()
        pairs = [(str(row["chat_id"]), row["at"]) for row in max_rows if row["at"] is not None]
        if not pairs:
            return {}
        out: dict[str, dict] = {}
        chunk_size = 400
        for offset in range(0, len(pairs), chunk_size):
            chunk = pairs[offset:offset + chunk_size]
            values_sql = ",".join("(?,?)" for _ in chunk)
            params: list[Any] = [value for pair in chunk for value in pair]
            rows = conn.execute(
                "SELECT chat_id, body, timestamp, is_historical FROM messages"
                f" WHERE (chat_id, timestamp) IN (VALUES {values_sql})",
                params,
            ).fetchall()
            for row in rows:
                chat_id = str(row["chat_id"])
                at = float(row["timestamp"] or 0)
                current = out.get(chat_id)
                if current is None or at >= current["at"]:
                    out[chat_id] = {
                        "body": str(row["body"] or ""),
                        "at": at,
                        "historical": bool(row["is_historical"]),
                    }
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


# ── funil e follow-ups ──────────────────────────────────────────────────────

def _contact_aliases(contacts: dict, chat_id: str, lid_map: dict | None = None) -> list[str]:
    identities = build_identity_map(contacts, lid_map)
    identity = identities.get(chat_id)
    aliases = [chat_id]
    if identity:
        aliases.extend(key for key, value in identities.items() if value == identity and key != chat_id)
    return list(dict.fromkeys(aliases))


def _dedupe_and_sort_rows(rows: list[dict], chat_ids: list[str]) -> list[dict]:
    """Uma linha por `message_id` (o histórico pode repetir a mesma mensagem sob o
    telefone e o `@lid`), cronológica. Entre duplicatas, prefere a que tem corpo e,
    empatado, a do alias mais à frente em `chat_ids`."""
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
    return _dedupe_and_sort_rows(rows, chat_ids)


def _historical_rows(messages_db: Path, chat_ids: list[str], limit: int = 200) -> list[dict]:
    """As últimas `limit` mensagens do histórico importado (fullsync) da conversa,
    cronológicas, cada uma marcada `historical=True`."""
    conn = _ro(messages_db)
    if conn is None or not chat_ids:
        return []
    try:
        placeholders = ",".join("?" for _chat_id in chat_ids)
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT id, chat_id, message_id, message_type, body, timestamp, from_me, has_media, media_type"
                f" FROM messages WHERE chat_id IN ({placeholders}) AND is_historical = 1"
                " AND timestamp IS NOT NULL ORDER BY timestamp DESC, id DESC LIMIT ?",
                [*chat_ids, limit],
            ).fetchall()
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    for row in rows:
        row["historical"] = True
    return _dedupe_and_sort_rows(rows, chat_ids)


def _historical_message_count(messages_db: Path, chat_ids: list[str]) -> int:
    conn = _ro(messages_db)
    if conn is None or not chat_ids:
        return 0
    placeholders = ",".join("?" for _ in chat_ids)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM messages WHERE chat_id IN ({placeholders}) AND is_historical=1",
            chat_ids,
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


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
            "historical": bool(row.get("historical")),
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
            and previous.get("historical") == item.get("historical")
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
    paths: Paths, chat_id: str, now: datetime | None = None, *, lid_map: dict | None = None,
    pipeline_id: str = "default",
) -> dict:
    """Conversa de um lead (viva + histórico importado), pronta para a tela de
    detalhe."""
    preset = pipeline(pipeline_id)
    contacts = load_contacts(paths.contacts_json)
    record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
    chat_ids = _contact_aliases(contacts, chat_id, lid_map)
    live_rows = _conversation_rows(paths.messages_db, chat_ids)
    historical_rows = _historical_rows(paths.messages_db, chat_ids, limit=200)
    events = _mark_conversation_owners(live_rows, paths.plugin_log, chat_ids)
    combined_rows = sorted(
        historical_rows + live_rows,
        key=lambda row: (float(row.get("timestamp") or 0), int(row.get("id") or 0)),
    )[-200:]
    timeline = _message_timeline(combined_rows, _flow_timeline(paths, chat_id, events))
    lead = next((row for row in _lead_rows(paths.followups_db) if row.get("chat_id") == chat_id), {})
    open_jobs = [
        job for job in _job_rows(paths.followups_db)
        if job.get("chat_id") == chat_id and job.get("status") in ("pending", "leased")
    ]
    next_job = min(open_jobs, key=lambda job: str(job.get("due_utc") or "9"), default={})
    engine_stage = str(lead.get("stage") or "new")
    imported = _therapify_context(paths.followups_db, chat_id)
    imported["historical_messages"] = _historical_message_count(paths.messages_db, chat_ids)
    therapify_row = {"status": imported.get("status", ""), "is_existing_patient": imported.get("is_existing_patient", False)}
    stage = resolve_pipeline_stage(preset, contact_record=record, lead_row=lead, therapify_row=therapify_row) or "new"
    stage_label = next((label for sid, label, _e, _t in preset["stages"] if sid == stage), stage.replace("_", " ").title())

    blocked = record.get("blocked") is True
    ai_disabled_reason = record.get("ai_disabled_reason")
    reactivation_pending = False
    if not blocked:
        try:
            entry = reactivation_store.get_entry(paths.followups_db, chat_id)
        except (ValueError, sqlite3.Error):
            entry = None
        reactivation_pending = bool(entry and entry.get("sent_utc") is None)
    kind = _contact_kind(
        blocked=blocked, flow_origin=str(record.get("flow_origin") or ""),
        ai_disabled_reason=ai_disabled_reason, reactivation_pending=reactivation_pending,
    )
    ai = _ai_status(
        kind=kind, ai_enabled=record.get("ai_enabled", True) is not False,
        ai_disabled_reason=ai_disabled_reason, human=bool(lead.get("takeover")),
        automation=bool(lead.get("automation_enabled")), has_lead=bool(lead),
    )
    classification = load_classification(paths.workspace_dir)
    triage = _triage_public(_triage_lookup(classification, chat_ids), include_evidence=True)

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
            "stage_label": stage_label,
            "engine_stage": engine_stage,
            "estimated_value_cents": lead.get("estimated_value_cents"),
            "cadence": CADENCE_LABEL.get(str(lead.get("cadence_kind") or ""), ""),
            "automation_enabled": bool(lead.get("automation_enabled")),
            "takeover": bool(lead.get("takeover")),
            "blocked": blocked,
            "next_followup_utc": str(next_job.get("due_utc") or ""),
            "next_followup_step": int(next_job.get("step_no") or 0),
            "source_status": imported.get("status", ""),
            "source_paused": bool(imported.get("paused")),
        },
        "imported_history": imported,
        "usage": _session_usage_for_chat(paths.state_db, chat_ids),
        "timeline": timeline,
        "ai": ai,
        "triage": triage,
        "legacy": kind == "legacy",
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


def _therapify_context(followups_db: Path, chat_id: str) -> dict[str, Any]:
    """Leitura somente leitura do estado comercial importado do Therapify."""
    empty = {
        "status": "", "is_existing_patient": False, "appointments": [], "purchases": [],
        "escalations": [], "reactivation_stage": None,
    }
    conn = _ro(followups_db)
    if conn is None:
        return dict(empty)
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        context: dict[str, Any] = dict(empty)
        if "therapify_leads" in tables:
            row = conn.execute(
                "SELECT status, is_existing_patient, paused, created_at, updated_at FROM therapify_leads WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
            if row is not None:
                context.update({
                    "status": str(row[0] or ""),
                    "is_existing_patient": bool(row[1]),
                    "paused": bool(row[2]),
                    "created_at": row[3],
                    "updated_at": row[4],
                })
        for table, key in (("appointments", "appointments"), ("purchases", "purchases"), ("escalations", "escalations")):
            if table in tables:
                context[key] = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE chat_id=? ORDER BY created_at", (chat_id,)).fetchall()]
        if "reactivation_progress" in tables:
            row = conn.execute("SELECT stage, updated_at FROM reactivation_progress WHERE chat_id=?", (chat_id,)).fetchone()
            if row is not None:
                context["reactivation_stage"] = int(row[0])
                context["reactivation_updated_at"] = row[1]
        return context
    except sqlite3.Error:
        return dict(empty)
    finally:
        conn.close()


def _therapify_lead_rows(followups_db: Path) -> dict[str, dict]:
    """`therapify_leads` inteira, por chat_id — pra resolver o estágio do board sem
    uma query por card."""
    conn = _ro(followups_db)
    if conn is None:
        return {}
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "therapify_leads" not in tables:
            return {}
        rows = conn.execute("SELECT chat_id, status, is_existing_patient FROM therapify_leads").fetchall()
        return {str(row["chat_id"]): dict(row) for row in rows}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def leads(paths: Paths, now: datetime | None = None, *, pipeline_id: str = "default") -> dict:
    """Kanban: leads por etapa, com nome, última mensagem e próximo follow-up."""
    now = now or datetime.now(timezone.utc)
    preset = pipeline(pipeline_id)
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
    therapify_rows = _therapify_lead_rows(paths.followups_db) if preset["id"] == "therapify" else {}
    stage_ids = [stage_id for stage_id, _label, _engine_stage, _terminal in preset["stages"]]
    columns: dict[str, list[dict]] = {stage_id: [] for stage_id in stage_ids}
    terminal = {"won": 0, "lost": 0}
    excluded = {"existing_patients": 0, "blocked": 0}
    for row in rows:
        chat_id = row["chat_id"]
        record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
        if record.get("blocked") is True:
            excluded["blocked"] += 1
            continue
        engine_stage = str(row.get("stage") or "new").lower()
        if preset["id"] == "default":
            # Preserva o comportamento de sempre: etapa terminal do engine some do
            # board e vira contagem à parte.
            if engine_stage in TERMINAL_STAGES or row.get("terminal"):
                terminal["won" if engine_stage in ("ganho", "won", "concluido", "concluída") else "lost"] += 1
                continue
            stage = engine_stage if engine_stage in columns else "new"
        else:
            stage = resolve_pipeline_stage(
                preset, contact_record=record, lead_row=row, therapify_row=therapify_rows.get(chat_id),
            )
            if stage is None:
                excluded["existing_patients"] += 1
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
            "estimated_value_cents": row.get("estimated_value_cents"),
            "preview": msg.get("body", "")[:140],
            "last_at": msg.get("at", 0),
            "last": _ago(datetime.fromtimestamp(msg["at"], timezone.utc), now) if msg.get("at") else "",
            "human": bool(row.get("takeover")),
            "automation": bool(row.get("automation_enabled")),
            "next_followup": due_label,
            "next_followup_rel": due_rel,
            "cadence": CADENCE_LABEL.get(str(row.get("cadence_kind") or ""), ""),
        })
    for stage_id in columns:
        columns[stage_id].sort(key=lambda c: -c["last_at"])
    stage_meta = {stage_id: (label, is_terminal) for stage_id, label, _engine_stage, is_terminal in preset["stages"]}
    return {
        "pipeline": preset["id"],
        "stages": [
            {"id": stage_id, "label": stage_meta[stage_id][0], "terminal": stage_meta[stage_id][1], "cards": columns[stage_id]}
            for stage_id in stage_ids
        ],
        "terminal": terminal,
        "excluded": excluded,
        "total": sum(len(columns[stage_id]) for stage_id in stage_ids if not stage_meta[stage_id][1]),
    }


def _excluded_contact_key(key: str) -> bool:
    return key.endswith("@g.us") or key.endswith("@broadcast")


def contacts_directory(
    paths: Paths, *, owner_number: str = "", lid_map: dict | None = None,
    pipeline_id: str = "default", now: datetime | None = None,
) -> dict:
    """Diretório completo de contatos — uma linha por identidade (telefone + `@lid`
    colapsados como `build_identity_map` faz), incluindo o legado com IA desligada
    e a classificação da triagem. É o que sustenta a tela Contatos."""
    now = now or datetime.now(timezone.utc)
    preset = pipeline(pipeline_id)
    contacts = load_contacts(paths.contacts_json)
    identity_of = build_identity_map(contacts, lid_map)
    classification = load_classification(paths.workspace_dir)

    groups: dict[str, dict] = {}
    for key, record in contacts.items():
        if not isinstance(record, dict) or _excluded_contact_key(key):
            continue
        identity = identity_of.get(key, key)
        if owner_number and identity == owner_number:
            continue
        group = groups.setdefault(identity, {"keys": [], "records": []})
        group["keys"].append(key)
        group["records"].append(record)

    pending_phone_digits: set[str] = set()
    try:
        reactivation_store.ensure_schema(paths.followups_db)
        entries = reactivation_store.list_entries(paths.followups_db)
        pending_phone_digits = {_digits(str(row.get("chat_id") or "")) for row in entries.get("pending", [])}
    except sqlite3.Error:
        pending_phone_digits = set()

    lead_by_chat = {row["chat_id"]: row for row in _lead_rows(paths.followups_db)}
    jobs = _job_rows(paths.followups_db)
    next_due: dict[str, datetime] = {}
    for job in jobs:
        if job.get("status") in ("pending", "leased"):
            due = _parse_utc(job.get("due_utc"))
            if due and (job["chat_id"] not in next_due or due < next_due[job["chat_id"]]):
                next_due[job["chat_id"]] = due
    therapify_rows = _therapify_lead_rows(paths.followups_db) if preset["id"] == "therapify" else {}
    last_all = _last_messages_all(paths.messages_db)

    rows_out: list[dict] = []
    flag_counts: dict[str, int] = {}
    counts = {"all": 0, "attention": 0, "human": 0, "aya": 0, "legacy": 0, "blocked": 0, "reactivation": 0}

    for identity, group in groups.items():
        keys = group["keys"]
        records = group["records"]
        phone_idx = next((i for i, k in enumerate(keys) if not k.endswith("@lid")), None)
        primary = records[phone_idx] if phone_idx is not None else records[0]
        canonical_key = keys[phone_idx] if phone_idx is not None else keys[0]

        def _coalesce(field: str, default: Any = None) -> Any:
            value = primary.get(field)
            if value not in (None, ""):
                return value
            for other in records:
                value = other.get(field)
                if value not in (None, ""):
                    return value
            return default

        blocked = any(r.get("blocked") is True for r in records)
        ai_enabled_values = [r.get("ai_enabled") for r in records if "ai_enabled" in r]
        ai_enabled = False if False in ai_enabled_values else True
        ai_disabled_reason = _coalesce("ai_disabled_reason")
        flow_origin = str(_coalesce("flow_origin", "") or "")
        relationship = str(_coalesce("manual_relationship", "") or _coalesce("relationship", "") or "")
        pipeline_stage_override = _coalesce("pipeline_stage")
        legacy_last_message_at = _coalesce("legacy_last_message_at")

        reactivation_pending = not identity.startswith("lid:") and identity in pending_phone_digits
        kind = _contact_kind(
            blocked=blocked, flow_origin=flow_origin, ai_disabled_reason=ai_disabled_reason,
            reactivation_pending=reactivation_pending,
        )

        lead = next((lead_by_chat[k] for k in keys if k in lead_by_chat), None)
        human = bool((lead or {}).get("takeover"))
        automation = bool((lead or {}).get("automation_enabled"))
        stage = stage_label = None
        estimated_value_cents = None
        next_followup, next_followup_rel = "", ""
        if lead is not None:
            lead_chat_id = lead["chat_id"]
            stage = resolve_pipeline_stage(
                preset,
                contact_record={"pipeline_stage": pipeline_stage_override} if pipeline_stage_override else {},
                lead_row=lead, therapify_row=therapify_rows.get(lead_chat_id),
            )
            if stage:
                stage_label = next(
                    (label for sid, label, _e, _t in preset["stages"] if sid == stage),
                    stage.replace("_", " ").title(),
                )
            estimated_value_cents = lead.get("estimated_value_cents")
            next_followup, next_followup_rel = _fmt_due(next_due.get(lead_chat_id), now)

        ai = _ai_status(
            kind=kind, ai_enabled=ai_enabled, ai_disabled_reason=ai_disabled_reason,
            human=human, automation=automation, has_lead=lead is not None,
        )

        last_candidates = [last_all[k] for k in keys if k in last_all]
        best_last = max(last_candidates, key=lambda item: item["at"], default=None)
        if best_last is not None:
            last_at = best_last["at"]
            last = _ago(datetime.fromtimestamp(last_at, timezone.utc), now)
            last_historical = bool(best_last["historical"])
            preview = best_last["body"][:140]
        elif legacy_last_message_at:
            # O fullsync grava ISO-8601 (com fuso); versões antigas gravavam epoch.
            try:
                last_at = float(legacy_last_message_at)
            except (TypeError, ValueError):
                parsed = _parse_utc(legacy_last_message_at)
                last_at = parsed.timestamp() if parsed else 0.0
            last = _ago(datetime.fromtimestamp(last_at, timezone.utc), now) if last_at else ""
            last_historical = True
            preview = ""
        else:
            last_at, last, last_historical, preview = 0.0, "", False, ""

        triage_record = _triage_lookup(classification, keys)
        triage = _triage_public(triage_record)
        if triage_record:
            flag = str(triage_record.get("flag") or "").strip()
            if flag:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1

        rows_out.append({
            "chat_id": canonical_key,
            "aliases": keys,
            "name": _contact_name(contacts, canonical_key),
            "phone": format_phone(identity) if not identity.startswith("lid:") else format_phone(canonical_key),
            "kind": kind,
            "ai": ai,
            "human": human,
            "automation": automation,
            "stage": stage,
            "stage_label": stage_label,
            "estimated_value_cents": estimated_value_cents,
            "next_followup": next_followup,
            "next_followup_rel": next_followup_rel,
            "preview": preview,
            "last_at": last_at,
            "last": last,
            "last_historical": last_historical,
            "triage": triage,
            "relationship": relationship,
            "legacy": kind == "legacy",
        })

        counts["all"] += 1
        if kind == "blocked":
            counts["blocked"] += 1
        elif kind == "reactivation":
            counts["reactivation"] += 1
        elif kind == "legacy":
            counts["legacy"] += 1
        if human:
            counts["human"] += 1
        if automation and not human:
            counts["aya"] += 1
        if human or next_followup_rel == "atrasado":
            counts["attention"] += 1

    rows_out.sort(key=lambda r: (0, -r["last_at"]) if r["last_at"] else (1, r["name"].lower()))
    return {"total": counts["all"], "counts": counts, "flags": flag_counts, "contacts": rows_out}


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


# ── reativação manual por etiqueta ──────────────────────────────────────────

def reactivation(
    paths: Paths, *, label: str, now: datetime | None = None, pipeline_id: str = "default",
) -> dict:
    """Lista de reativação manual: pendentes e já contatados, prontos pra tela.

    `label` aqui é só o rótulo mostrado no topo (etiqueta configurada) — cada
    linha guarda a etiqueta com que foi preparada; a lista em si vive em
    `manual_reactivation` (`reactivation_store.py`), que este módulo só lê."""
    now = now or datetime.now(timezone.utc)
    reactivation_store.ensure_schema(paths.followups_db)
    entries = reactivation_store.list_entries(paths.followups_db)
    preset = pipeline(pipeline_id)
    contacts = load_contacts(paths.contacts_json)
    lead_by_chat = {row["chat_id"]: row for row in _lead_rows(paths.followups_db)}
    therapify_rows = _therapify_lead_rows(paths.followups_db) if preset["id"] == "therapify" else {}

    def _item(row: dict) -> dict:
        chat_id = row["chat_id"]
        record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
        lead_row = lead_by_chat.get(chat_id)
        stage = resolve_pipeline_stage(
            preset, contact_record=record, lead_row=lead_row, therapify_row=therapify_rows.get(chat_id),
        )
        stage_label = next((lbl for sid, lbl, _e, _t in preset["stages"] if sid == stage), None) or "Novo"
        last_inbound_at = _parse_utc((lead_row or {}).get("last_inbound_utc"))
        return {
            "chat_id": chat_id,
            "name": _contact_name(contacts, chat_id),
            "phone": format_phone(chat_id),
            "stage_label": stage_label,
            "prepared_utc": row.get("prepared_utc"),
            "message": row.get("message") or "",
            "message_variant": int(row.get("message_variant") or 0),
            "sent_utc": row.get("sent_utc"),
            "first_manual_pending": bool(row.get("first_manual_pending")),
            "last_inbound": _ago(last_inbound_at, now) if last_inbound_at else "",
            "takeover": bool((lead_row or {}).get("takeover")),
        }

    pending = [_item(row) for row in entries["pending"]]
    sent = [_item(row) for row in entries["sent"]]
    return {
        "label": label,
        "pending": pending,
        "sent": sent,
        "counts": {"pending": len(pending), "sent": len(sent)},
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


def _commercial_metrics(paths: Paths, preset: dict, start: datetime, *, owner_number: str = "") -> dict:
    """KPIs comerciais do Therapify: leads, sessões, downsells e escalonamentos.
    Sempre presente na resposta de `metrics`, zerado quando as tabelas migradas
    ainda não existem."""
    result: dict[str, Any] = {
        "leads_total": 0,
        "leads_period": 0,
        "appointments_total": 0,
        "appointments_period": 0,
        "session_price_brl": preset.get("session_price_brl"),
        "appointments_potential_brl": 0,
        "purchases_total_brl": 0.0,
        "purchases_period_brl": 0.0,
        "purchases_count": 0,
        "purchases_by_product": [],
        "escalations_open": 0,
    }
    conn = _ro(paths.followups_db)
    if conn is None:
        return result
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "lead_state" in tables:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(lead_state)")}
            has_source_created = "source_created_at" in columns
            select = "chat_id, last_inbound_utc, updated_utc" + (", source_created_at" if has_source_created else "")
            contacts = load_contacts(paths.contacts_json)
            total = period = 0
            for row in conn.execute(f"SELECT {select} FROM lead_state").fetchall():
                chat_id = row["chat_id"]
                if owner_number and _digits(chat_id) == owner_number:
                    continue
                record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
                if record.get("blocked") is True:
                    continue
                total += 1
                source_created = row["source_created_at"] if has_source_created else None
                when = _parse_utc(source_created or row["last_inbound_utc"] or row["updated_utc"])
                if when and when >= start:
                    period += 1
            result["leads_total"] = total
            result["leads_period"] = period
        if "appointments" in tables:
            appt_created = [_parse_utc(r["created_at"]) for r in conn.execute("SELECT created_at FROM appointments").fetchall()]
            result["appointments_total"] = len(appt_created)
            result["appointments_period"] = sum(1 for when in appt_created if when and when >= start)
        price = preset.get("session_price_brl")
        if price is not None:
            result["appointments_potential_brl"] = result["appointments_total"] * price
        if "purchases" in tables:
            purchase_rows = conn.execute("SELECT product, amount, created_at FROM purchases").fetchall()
            result["purchases_count"] = len(purchase_rows)
            result["purchases_total_brl"] = sum(float(r["amount"] or 0) for r in purchase_rows)
            result["purchases_period_brl"] = sum(
                float(r["amount"] or 0) for r in purchase_rows
                if (when := _parse_utc(r["created_at"])) and when >= start
            )
            products_map = preset.get("products") or {}
            by_product: dict[str, dict] = {}
            for r in purchase_rows:
                agg = by_product.setdefault(str(r["product"] or ""), {"count": 0, "total": 0.0})
                agg["count"] += 1
                agg["total"] += float(r["amount"] or 0)
            ordered = [key for key in products_map if key in by_product] + sorted(
                key for key in by_product if key not in products_map
            )
            result["purchases_by_product"] = [
                {
                    "product": key,
                    "label": products_map.get(key, (key, None))[0],
                    "unit_price_brl": products_map.get(key, (key, None))[1],
                    "count": by_product[key]["count"],
                    "total_brl": by_product[key]["total"],
                }
                for key in ordered
            ]
        if "escalations" in tables:
            row = conn.execute("SELECT COUNT(*) FROM escalations WHERE resolved = 0").fetchone()
            result["escalations_open"] = int(row[0] or 0)
        return result
    except sqlite3.Error:
        return result
    finally:
        conn.close()


def metrics(
    paths: Paths, period: str = "7d", now: datetime | None = None, *, minutes_per_resolved: float = 6.0,
    pipeline_id: str = "default", owner_number: str = "",
) -> dict:
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
    # A visão operacional prioriza quem espera há mais tempo. O total fica
    # separado da amostra para o painel não subcontar filas maiores que 10.
    pending.sort(key=lambda h: h["at"])
    period_start, _period_end = _period_bounds(period, now)
    return {
        "period": period,
        "total": total,
        "ai_resolved": ai,
        "human": total - ai,
        "lead_messages": sum(d["lead_messages"] for d in per_day),
        "minutes_saved": round(ai * minutes_per_resolved),
        "api_calls": sum(d["api_calls"] for d in per_day),
        "model_seconds": round(sum(d["model_seconds"] for d in per_day), 1),
        "handoffs_pending_total": len(pending),
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
        "commercial": _commercial_metrics(paths, pipeline(pipeline_id), period_start, owner_number=owner_number),
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
