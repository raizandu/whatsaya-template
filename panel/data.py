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
from urllib.parse import quote
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import atendimento_store
import calendar_booking
import daily_audit
import management_store
import panel_store
import reactivation_store
import users_store
from commercial_followups import CADENCES, TERMINAL_STAGES, render_contextual_message

STAGES = ("new", "qualification", "pricing", "proposal", "payment")
STAGE_LABEL = {
    "new": "Novo",
    "qualification": "Qualificação",
    "pricing": "Preço",
    "proposal": "Proposta",
    "payment": "Pagamento",
}

# Preset do funil do painel. Cada estágio é (id, label, engine_stage, terminal):
# `id`/`label` são o que o painel mostra; `engine_stage` é pra onde isso mapeia
# no FollowupEngine, que só conhece STAGES acima. O engine não ganha estágio
# novo — a gente só reaproveita os dele. Só o `default` vive no código: um
# funil de cliente é declarado inteiro no `panel.config.json` (ver
# `pipeline_from_config`), nunca com nome de cliente aqui.
DEFAULT_PIPELINE: dict = {
    "id": "default",
    "stages": (
        ("new", "Novo", "new", False),
        ("qualification", "Qualificação", "qualification", False),
        ("pricing", "Preço", "pricing", False),
        ("proposal", "Proposta", "proposal", False),
        ("payment", "Pagamento", "payment", False),
    ),
    "engine_stage_map": {},
    "imported": None,
    "commercial_metrics": False,
    "session_price_brl": None,
    "products": {},
    "_normalized": True,
}

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ENGINE_STAGES = {"new", "qualification", "pricing", "proposal", "payment", "lost", "won"} | set(TERMINAL_STAGES)


def _custom_pipeline(spec: dict) -> dict | None:
    """Normaliza um funil declarado em config; `None` se estiver inválido (cai no default).

    Formato:
        {"id": "clinica",
         "stages": [{"id": "in_funnel", "label": "No funil", "engine_stage": "qualification"},
                    {"id": "won_a", "label": "Comprou", "engine_stage": "payment", "terminal": true}, ...],
         "engine_stage_map": {"qualification": "in_funnel", "won": null},
         "imported": {"table": "legacy_leads", "status_column": "status",
                      "excluded_statuses": ["existing_customer"], "excluded_flag": "is_existing_customer",
                      "excluded_label": "clientes antigos"},
         "commercial_metrics": true, "session_price_brl": 200,
         "products": {"product_a": ["Produto A", 47]}}
    `imported` é uma tabela de status vinda de um sistema anterior no mesmo
    `commercial_followups.db`; `engine_stage_map` diz em que coluna cai cada
    estágio do engine (null = fora do funil)."""
    pid = str(spec.get("id") or "").strip().lower()
    if not _IDENT_RE.match(pid) or pid == "default":
        return None
    stages: list[tuple[str, str, str, bool]] = []
    for raw in spec.get("stages") or []:
        if not isinstance(raw, dict):
            return None
        sid = str(raw.get("id") or "").strip().lower()
        label = " ".join(str(raw.get("label") or "").split())[:40]
        engine_stage = str(raw.get("engine_stage") or sid).strip().lower()
        if not _IDENT_RE.match(sid) or not label or engine_stage not in _ENGINE_STAGES:
            return None
        stages.append((sid, label, engine_stage, bool(raw.get("terminal"))))
    if not stages or len({sid for sid, *_ in stages}) != len(stages):
        return None
    stage_ids = {sid for sid, *_ in stages}
    engine_map: dict[str, str | None] = {}
    for key, value in (spec.get("engine_stage_map") or {}).items():
        key = str(key).strip().lower()
        if key not in _ENGINE_STAGES:
            return None
        if value is None:
            engine_map[key] = None
        elif str(value) in stage_ids:
            engine_map[key] = str(value)
        else:
            return None
    imported = None
    raw_imported = spec.get("imported")
    if isinstance(raw_imported, dict) and raw_imported.get("table"):
        table = str(raw_imported.get("table") or "").strip()
        status_column = str(raw_imported.get("status_column") or "status").strip()
        flag = str(raw_imported.get("excluded_flag") or "").strip() or None
        if not _IDENT_RE.match(table) or not _IDENT_RE.match(status_column) or (flag and not _IDENT_RE.match(flag)):
            return None
        imported = {
            "table": table,
            "status_column": status_column,
            "excluded_statuses": {str(x).strip().lower() for x in (raw_imported.get("excluded_statuses") or [])},
            "excluded_flag": flag,
            "excluded_label": " ".join(str(raw_imported.get("excluded_label") or "fora do funil").split())[:40],
        }
    products: dict[str, tuple[str, float]] = {}
    for key, value in (spec.get("products") or {}).items():
        if isinstance(value, (list, tuple)) and len(value) == 2 and _IDENT_RE.match(str(key)):
            try:
                products[str(key)] = (str(value[0]), float(value[1]))
            except (TypeError, ValueError):
                return None
    price = spec.get("session_price_brl")
    return {
        "id": pid,
        "stages": tuple(stages),
        "engine_stage_map": engine_map,
        "imported": imported,
        "commercial_metrics": bool(spec.get("commercial_metrics")),
        "session_price_brl": float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
        "products": products,
        "_normalized": True,
    }


def pipeline(spec) -> dict:
    """Preset do funil: dict já normalizado ou declarado; qualquer outra coisa
    (string, vazio, inválido) cai no `default`."""
    if isinstance(spec, dict):
        if spec.get("_normalized"):
            return spec
        return _custom_pipeline(spec) or DEFAULT_PIPELINE
    return DEFAULT_PIPELINE


def pipeline_from_config(custom: dict) -> dict:
    """Preset declarado em `panel.config.json`: `"pipeline": "default"` ou o objeto
    descrito em `_custom_pipeline`."""
    custom = custom if isinstance(custom, dict) else {}
    return pipeline(custom.get("pipeline"))


def resolve_pipeline_stage(
    preset: dict, *, contact_record: dict | None, lead_row: dict | None, imported_row: dict | None
) -> str | None:
    """Etapa do preset pra um lead. `None` significa "fora do board" (por exemplo
    um cliente antigo importado, fora do funil comercial).

    Ordem de decisão: escolha explícita do painel > status importado do sistema
    anterior > `engine_stage_map` do preset > estágio do engine quando ele é uma
    coluna. Pro preset `default` só a escolha explícita e o estágio do engine
    valem — o estágio do engine já é o id do preset."""
    stage_ids = {stage_id for stage_id, _label, _engine_stage, _terminal in preset["stages"]}
    contact_record = contact_record or {}
    override = str(contact_record.get("pipeline_stage") or "").strip()
    if override in stage_ids:
        return override

    engine_stage = str((lead_row or {}).get("stage") or "").strip().lower()
    imported_cfg = preset.get("imported")
    if imported_cfg and imported_row:
        status = str(imported_row.get("status") or "").strip().lower()
        if status in imported_cfg["excluded_statuses"] or bool(imported_row.get("excluded")):
            return None
        if status in stage_ids:
            return status
    engine_map = preset.get("engine_stage_map") or {}
    if engine_stage in engine_map:
        return engine_map[engine_stage]
    return engine_stage if engine_stage in stage_ids else "new"


CADENCE_LABEL = {
    "silence": "Silêncio",
    "proposal": "Proposta",
    "payment": "Pagamento",
    "post_sale": "Pós-venda",
    "resume": "Retomada",
    "reactivation": "Reativação",
}
CANCEL_REASON_LABEL = {
    "lead_replied": "lead respondeu antes",
    "human_takeover": "você assumiu a conversa",
    "policy_or_context_changed": "etapa ou contexto mudou",
    "lead_not_eligible": "lead saiu da automação",
    "nothing_pending": "nada pendente na retomada",
    "downsell_ja_oferecido": "R$47 já oferecido",
    "reactivation_step_missing": "toque sem texto no profile",
}
# Motivo do job `resume` (ADR 0001): vem do sufixo de `basis_outbound_id`, `resume:<reason>`.
RESUME_REASON_LABEL = {
    "lead_novo": "lead novo",
    "fila_manha": "fila da manhã",
    "sintomas": "esperando sintomas",
}
# Toque da Fase 7 (reativação): `step_no` 1/2/3 vira D1/D2/toque final na tela.
REACTIVATION_STEP_LABEL = {1: "D1", 2: "D2", 3: "toque final"}
# Mesmo mapeamento, pela chave que o profile usa em `reactivation.steps[].name`.
REACTIVATION_STEP_LABEL_BY_NAME = {"d1": "D1", "d2": "D2", "final": "toque final"}
PERIOD_DAYS = {"hoje": 1, "7d": 7, "30d": 30}


@dataclass(frozen=True)
class Paths:
    contacts_json: Path = Path("/opt/data/personal_contacts.json")
    messages_db: Path = Path("/opt/data/.hermes/whatsapp_messages.db")
    followups_db: Path = Path("/opt/data/.hermes/commercial_followups.db")
    bookings_db: Path = Path("/opt/data/.hermes/calendar_bookings.db")
    state_db: Path = Path("/opt/data/.hermes/state.db")
    plugin_log: Path = Path("/opt/data/.hermes/logs/whatsapp_plugin.log")
    gateway_log: Path = Path("/opt/data/.hermes/logs/gateway.log")
    pricing_json: Path = Path(__file__).with_name("pricing.json")
    workspace_dir: Path = Path("/opt/data/.hermes/workspace")
    management_db: Path = Path("/opt/data/.hermes/management.db")
    panel_db: Path = Path("/opt/data/.hermes/panel.db")
    users_json: Path = Path("/opt/data/panel_users.json")
    business_profile_json: Path = Path("/opt/data/business_profile.json")
    hermes_env: Path = Path("/opt/data/.hermes/.env")
    followup_cron_log: Path = Path("/opt/data/.hermes/logs/whatsapp_followup_cron.log")


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


_WEEKDAY_ABBR = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


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
        day = _WEEKDAY_ABBR[local.weekday()]
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


def _fmt_due_local(when: datetime | None) -> str:
    """`sex 11/09 14:35` no fuso comercial — tooltip/subtexto do cronômetro da fila."""
    if when is None:
        return ""
    local = when.astimezone(daily_audit.business_tz())
    return f"{_WEEKDAY_ABBR[local.weekday()]} {local.strftime('%d/%m %H:%M')}"


def _job_kind(cadence: str) -> str:
    """`resume`/`reactivation` têm rótulo e cor próprios; o resto é `generic`."""
    return cadence if cadence in ("resume", "reactivation") else "generic"


def _resume_reason_label(job: dict) -> str:
    basis = str(job.get("basis_outbound_id") or "")
    reason = basis.split(":", 1)[1] if ":" in basis else basis
    return RESUME_REASON_LABEL.get(reason, reason)


def _reactivation_step_label(job: dict) -> str:
    step = int(job.get("step_no") or 1)
    return REACTIVATION_STEP_LABEL.get(step, f"toque {step}")


def _job_action_label(job: dict, kind: str) -> str:
    """Frase de uma linha pra 'próxima ação' do lead (tela de detalhe) — o
    mesmo `kind`/`reason_label`/step da fila, num formato de sentença."""
    cadence = str(job.get("cadence_kind") or "")
    if kind == "resume":
        reason_label = _resume_reason_label(job)
        return f"Retomada ({reason_label})" if reason_label else "Retomada"
    if kind == "reactivation":
        return f"Reativação {_reactivation_step_label(job)}"
    step = int(job.get("step_no") or 1)
    return f"{CADENCE_LABEL.get(cadence, cadence)} · toque {step} de 3"


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


def load_business_hours(path: Path) -> dict[str, str] | None:
    """`schedule.open`/`schedule.close` do `business_profile.json` do cliente ativo (mesmo
    arquivo que `whatsapp_manager._business_profile()` lê), só para exibição no painel.
    Perfil ausente ou sem horário: None, e quem chama cai no texto genérico."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    schedule = raw.get("schedule") if isinstance(raw, dict) else None
    if not isinstance(schedule, dict):
        return None
    opens, closes = schedule.get("open"), schedule.get("close")
    if not isinstance(opens, str) or not isinstance(closes, str):
        return None
    return {"open": opens, "close": closes}


def load_ritmo_config(path: Path) -> dict | None:
    """Card "Ritmo" do painel: horário, humanização e reativação lidos direto do
    `business_profile.json` do cliente (docs/specs/2026-09-10-ritmo-e-horario-therapify.md).
    Leitura pura, como `load_business_hours`: perfil ausente ou sem os blocos
    `schedule`/`humanization` — que carregam o horário e as faixas de delay — vira
    None e quem chama esconde o card."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    schedule_raw = raw.get("schedule")
    humanization_raw = raw.get("humanization")
    if not isinstance(schedule_raw, dict) or not isinstance(humanization_raw, dict):
        return None
    opens, closes = schedule_raw.get("open"), schedule_raw.get("close")
    if not isinstance(opens, str) or not isinstance(closes, str):
        return None

    schedule = {
        "open": opens,
        "close": closes,
        "holidays_fixed": [h for h in schedule_raw.get("holidays_fixed") or [] if isinstance(h, str)],
        "holidays_extra": [h for h in schedule_raw.get("holidays_extra") or [] if isinstance(h, str)],
    }
    reply_delay = humanization_raw.get("reply_delay_s")
    humanization = {
        "first_reply": {
            "min_s": humanization_raw.get("first_reply_min_s"),
            "max_s": humanization_raw.get("first_reply_max_s"),
        },
        "diagnostic_debounce": {
            "min_s": humanization_raw.get("diagnostic_debounce_min_s"),
            "max_s": humanization_raw.get("diagnostic_debounce_max_s"),
            "cap_s": humanization_raw.get("diagnostic_debounce_cap_s"),
        },
        "reply_delay_s": reply_delay if isinstance(reply_delay, dict) else {},
    }

    reactivation_raw = raw.get("reactivation")
    reactivation_raw = reactivation_raw if isinstance(reactivation_raw, dict) else {}
    cadences_raw = raw.get("followup_cadences")
    offsets = (cadences_raw or {}).get("reactivation") if isinstance(cadences_raw, dict) else None
    steps_raw = reactivation_raw.get("steps")
    steps = []
    for i, step in enumerate(steps_raw if isinstance(steps_raw, list) else []):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        offset = None
        if isinstance(offsets, list) and i < len(offsets):
            pair = offsets[i]
            if isinstance(pair, list) and len(pair) == 2 and pair[0] == "business_days":
                offset = pair[1]
        bubbles = [b for b in step.get("bubbles") or [] if isinstance(b, str)]
        bubbles_after_media = [b for b in step.get("bubbles_after_media") or [] if isinstance(b, str)]
        steps.append({
            "name": name,
            "label": REACTIVATION_STEP_LABEL_BY_NAME.get(name, name.upper() or f"toque {i + 1}"),
            "offset": offset,
            "bubbles": bubbles,
            "bubbles_after_media": bubbles_after_media,
            "media_key": step.get("media_key"),
        })

    return {
        "schedule": schedule,
        "humanization": humanization,
        "reactivation": {"enabled": bool(reactivation_raw.get("enabled")), "steps": steps},
    }


_FOLLOWUP_CRON_LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\S+\s+tick sent=(\d+)")
_FOLLOWUP_ENV_ENABLED_RE = re.compile(r"^WHATSAPP_FOLLOWUP_ENABLED\s*=\s*(.*)$")


def _ritmo_engine_status(paths: Paths, now: datetime) -> dict:
    """Motor de follow-up (tique do cron do Hermes): liga/desliga do `.env` e a
    hora do último tique do log, direto dos arquivos da VPS. Nunca lança —
    arquivo ausente ou linha sem o formato esperado vira None nos campos."""
    enabled = None
    try:
        for line in Path(paths.hermes_env).read_text(encoding="utf-8").splitlines():
            match = _FOLLOWUP_ENV_ENABLED_RE.match(line.strip())
            if match:
                enabled = match.group(1).strip().strip('"').strip("'").lower() in ("1", "true", "yes", "on")
    except OSError:
        enabled = None

    last_tick_utc: datetime | None = None
    last_tick_sent: int | None = None
    try:
        lines = Path(paths.followup_cron_log).read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            match = _FOLLOWUP_CRON_LOG_RE.match(line.strip())
            if match:
                local = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                last_tick_utc = local.replace(tzinfo=daily_audit.business_tz()).astimezone(timezone.utc)
                last_tick_sent = int(match.group(2))
                break
    except OSError:
        pass

    return {
        "enabled": enabled,
        "last_tick_utc": last_tick_utc.isoformat() if last_tick_utc else None,
        "last_tick_sent": last_tick_sent,
        "last_tick_rel": _ago(last_tick_utc, now) if last_tick_utc else "",
        "stalled": bool(last_tick_utc and now - last_tick_utc > timedelta(minutes=3)),
    }


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
    "label_client": "etiqueta de cliente no WhatsApp",
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
    "client": "Cliente (etiqueta)",
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
        if reason == "label_client":
            return {"enabled": False, "reason": reason, "label": _AI_LABEL["client"]}
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
                f"SELECT * FROM messages WHERE chat_id IN ({placeholders}) AND is_historical = 0"
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
                f"SELECT * FROM messages WHERE chat_id IN ({placeholders}) AND is_historical = 1"
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


MEDIA_KINDS = ("image", "video", "audio", "document")


def media_kind(mime: str, media_type: str = "") -> str:
    """image | video | audio | document, pelo mime e, no empate, pelo tipo da mensagem."""
    base = str(mime or "").split(";")[0].strip().lower()
    for kind in ("image", "video", "audio"):
        if base.startswith(kind + "/"):
            return kind
    media_type = str(media_type or "").lower()
    if media_type in ("ptt", "audio"):
        return "audio"
    if media_type in ("image", "video"):
        return media_type
    return "document"


def _media_of(row: dict) -> dict | None:
    """Mídia guardada no R2 (fase MIDIA_SPEC). Sem `media_key`, a bolha fica só com texto."""
    key = str(row.get("media_key") or "").strip()
    if not key:
        return None
    message_id = str(row.get("message_id") or "")
    return {
        "url": f"/api/media/{quote(message_id, safe='')}",
        "kind": media_kind(row.get("media_mime"), row.get("media_type")),
        "mime": str(row.get("media_mime") or ""),
        "name": str(row.get("media_name") or ""),
        "size": int(row.get("media_size") or 0),
    }


def media_lookup(messages_db: Path, message_id: str) -> dict | None:
    """Chave e chat da mídia de uma mensagem, para `/api/media/<id>` validar acesso e assinar."""
    conn = _ro(messages_db)
    if conn is None or not message_id:
        return None
    try:
        row = conn.execute(
            "SELECT chat_id, message_id, media_key, media_mime, media_name, media_size FROM messages"
            " WHERE message_id = ? AND media_key IS NOT NULL AND media_key != '' LIMIT 1",
            (message_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return dict(row) if row else None


def avatar_url(avatars: dict | None, *chat_ids: str) -> str | None:
    """`/api/avatar/<digitos>` quando o bridge tem a foto do contato (por qualquer alias)."""
    if not avatars:
        return None
    for chat_id in chat_ids:
        digits = _digits(str(chat_id or ""))
        if digits and avatars.get(digits):
            return f"/api/avatar/{digits}"
    return None


def lead_media(paths: Paths, chat_id: str, *, lid_map: dict | None = None, limit: int = 200) -> list[dict]:
    """Aba Mídias: tudo que o chat (telefone e `@lid`) tem guardado, mais recente primeiro."""
    contacts = load_contacts(paths.contacts_json)
    chat_ids = _contact_aliases(contacts, chat_id, lid_map)
    conn = _ro(paths.messages_db)
    if conn is None or not chat_ids:
        return []
    try:
        placeholders = ",".join("?" for _ in chat_ids)
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM messages WHERE chat_id IN ({placeholders})"
            " AND media_key IS NOT NULL AND media_key != '' ORDER BY timestamp DESC, id DESC LIMIT ?",
            [*chat_ids, limit],
        ).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    tz = daily_audit.business_tz()
    seen: set[str] = set()
    items = []
    for row in rows:
        message_id = str(row.get("message_id") or "")
        if message_id in seen:
            continue
        seen.add(message_id)
        items.append({
            "message_id": message_id,
            "at": datetime.fromtimestamp(float(row.get("timestamp") or 0), tz).isoformat(),
            "from_me": bool(row.get("from_me")),
            "caption": str(row.get("body") or "").strip(),
            **(_media_of(row) or {}),
        })
    return items


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
        media = _media_of(row)
        body = str(row.get("body") or "").strip() if media else _conversation_body(row)
        if not body and not media:
            continue
        at = datetime.fromtimestamp(float(row.get("timestamp") or 0), tz)
        owner = str(row.get("owner") or ("aya" if row.get("from_me") else "lead"))
        sent_by = row.get("sent_by") or None
        bubble = {
            "message_id": str(row.get("message_id") or ""),
            "body": body,
            "media_type": str(row.get("media_type") or (row.get("message_type") if row.get("has_media") else "") or ""),
        }
        if media:
            bubble["media"] = media
        if sent_by:
            bubble["sent_by"] = sent_by
        atom = {
            "type": "message",
            "owner": owner,
            "historical": bool(row.get("historical")),
            "at": at.isoformat(),
            "last_at": at.isoformat(),
            "bubbles": [bubble],
        }
        if sent_by:
            atom["sent_by"] = sent_by
        atoms.append(atom)
    atoms.sort(key=lambda item: item["at"])
    timeline: list[dict] = []
    for item in atoms:
        previous = timeline[-1] if timeline else None
        if (
            item["type"] == "message"
            and previous
            and previous["type"] == "message"
            and previous["owner"] == item["owner"]
            and previous.get("sent_by") == item.get("sent_by")
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


_GENERIC_JOB_LABEL = {
    "sent": "Toque de follow-up enviado",
    "cancelled": "Toque de follow-up cancelado",
    "failed": "Falha no toque de follow-up",
    "manual_review": "Follow-up enviado para revisão",
    "uncertain": "Envio do follow-up incerto",
    "skipped": "Toque de follow-up pulado",
}
_RESUME_JOB_LABEL = {
    "sent": "Retomada ({reason}): mensagem do lead devolvida ao bot para responder",
    "cancelled": "Retomada ({reason}) cancelada",
    "failed": "Falha na retomada ({reason})",
    "uncertain": "Retomada ({reason}) incerta",
}
_REACTIVATION_JOB_LABEL = {
    "sent": "Fase 7: {step} enviado",
    "cancelled": "Fase 7: {step} cancelado",
    "failed": "Fase 7: falha no {step}",
    "manual_review": "Fase 7: {step} enviado para revisão",
    "uncertain": "Fase 7: envio do {step} incerto",
    "skipped": "Fase 7: {step} pulado (R$47 já oferecido)",
}


def _timeline_job_label(job: dict, status: str) -> str:
    """Rótulo da timeline por tipo de job. Retomada não é toque: é o turno voltando
    ao bot (Lead Novo, fila da manhã, sintomas); a Fase 7 mostra o passo."""
    kind = _job_kind(str(job.get("cadence_kind") or ""))
    if kind == "resume":
        template = _RESUME_JOB_LABEL.get(status)
        return template.format(reason=_resume_reason_label(job)) if template else ""
    if kind == "reactivation":
        template = _REACTIVATION_JOB_LABEL.get(status)
        return template.format(step=_reactivation_step_label(job)) if template else ""
    return _GENERIC_JOB_LABEL.get(status, "")


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
    for job in _job_rows(paths.followups_db):
        status = str(job.get("status") or "")
        label = _timeline_job_label(job, status)
        if job.get("chat_id") != chat_id or not label:
            continue
        at = _parse_utc(job.get("updated_utc"))
        if at is None:
            continue
        timeline.append({
            "type": "event",
            "event": "followup",
            "at": at.astimezone(tz).isoformat(),
            "label": label,
            "status": status,
            "step": int(job.get("step_no") or 0),
            "cadence": CADENCE_LABEL.get(str(job.get("cadence_kind") or ""), ""),
            "reason": CANCEL_REASON_LABEL.get(str(job.get("last_error") or ""), str(job.get("last_error") or "")),
        })
    return timeline


# ── fluxo (SOP) ─────────────────────────────────────────────────────────────
# `flow_status` confere o SOP declarado em `flow` do business_profile.json contra
# evidência real (mensagens, jobs, contato, reserva). O profile diz o que provar;
# aqui só compara. Ver docs/specs — bloco "Fluxo" da ficha do lead.

def _flow_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _flow_duration(seconds: float) -> str:
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min" if secs == 0 else f"{minutes} min {secs} s"
    hours, mm = divmod(minutes, 60)
    return f"{hours}h{mm:02d}"


def _flow_duration_minutes(seconds: float) -> str:
    """Como `_flow_duration`, mas arredondado pro minuto — pro delay randomizado
    de Lead Novo/retomada, onde segundo é ruído."""
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, mm = divmod(minutes, 60)
    return f"{hours}h{mm:02d}"


def _flow_short_label(label: str) -> str:
    return re.split(r" · | \(", label, maxsplit=1)[0].strip()


def _first_inbound_evidence(lead_rows: list[dict]) -> tuple[str, datetime | None, str, str | None]:
    if not lead_rows:
        return "pending", None, "", None
    return "done", _flow_ts(lead_rows[0].get("timestamp")), "", None


def _resume_job_evidence(
    jobs: list[dict], reason: str, bot_rows: list[dict], now: datetime,
) -> tuple[str, datetime | None, str, str | None]:
    job = next(
        (j for j in jobs if j.get("cadence_kind") == "resume" and j.get("basis_outbound_id") == f"resume:{reason}"),
        None,
    )
    if job is not None:
        status = str(job.get("status") or "")
        if status == "sent":
            return "done", _parse_utc(job.get("updated_utc")), "", None
        if status in ("pending", "leased"):
            due = _parse_utc(job.get("due_utc"))
            _, rel = _fmt_due(due, now) if due else ("", "")
            return "pending", None, f"retomada {rel}".strip(), due.isoformat() if due else None
        return "pending", None, "", None
    if bot_rows:
        return "na", None, "", None
    return "pending", None, "", None


def _bot_bubbles_evidence(
    bot_rows: list[dict], regex: str, expected: int,
) -> tuple[str, datetime | None, str, str | None]:
    pattern = re.compile(regex, re.I)
    matches = [row for row in bot_rows if pattern.search(str(row.get("body") or ""))]
    count = len(matches)
    detail = f"{count} de {expected} bolhas"
    if count == 0:
        return "pending", None, detail, None
    return "done", _flow_ts(matches[-1].get("timestamp")), detail, None


def _lead_after_step_evidence(
    lead_rows: list[dict], after_id: str, computed: dict[str, dict], now: datetime,
) -> tuple[str, datetime | None, str, str | None]:
    after_at = (computed.get(after_id) or {}).get("at")
    if after_at is None:
        return "pending", None, "", None
    for row in lead_rows:
        at = _flow_ts(row.get("timestamp"))
        if at and at > after_at:
            return "done", at, "", None
    return "pending", None, f"aguardando resposta do lead {_ago(after_at, now)}", None


def _contact_field_evidence(record: dict, field: str) -> tuple[str, datetime | None, str, str | None]:
    value = record.get(field)
    if not value:
        return "pending", None, "", None
    at = _flow_ts(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return "done", at, "", None


def _booking_evidence(booking: dict | None) -> tuple[str, datetime | None, str, str | None]:
    if not booking:
        return "pending", None, "", None
    return "done", _parse_utc(booking.get("created_at")), "", None


def _reactivation_jobs_evidence(jobs: list[dict], now: datetime) -> tuple[str, datetime | None, str, str | None]:
    steps = [j for j in jobs if j.get("cadence_kind") == "reactivation"]
    if not steps:
        return "pending", None, "", None
    settled = [j for j in steps if j.get("status") in ("sent", "skipped")]
    if settled:
        last = max(settled, key=lambda j: str(j.get("updated_utc") or ""))
        verb = "enviado" if last.get("status") == "sent" else "pulado"
        return "done", _parse_utc(last.get("updated_utc")), f"{_reactivation_step_label(last)} {verb}", None
    open_jobs = [j for j in steps if j.get("status") in ("pending", "leased")]
    if open_jobs:
        nxt = min(open_jobs, key=lambda j: str(j.get("due_utc") or "9"))
        due = _parse_utc(nxt.get("due_utc"))
        _, rel = _fmt_due(due, now) if due else ("", "")
        return "pending", None, f"{_reactivation_step_label(nxt)} {rel}".strip(), due.isoformat() if due else None
    last_cancel = max(steps, key=lambda j: str(j.get("updated_utc") or ""))
    reason = CANCEL_REASON_LABEL.get(str(last_cancel.get("last_error") or ""), str(last_cancel.get("last_error") or ""))
    return "na", None, f"cancelada: {reason}" if reason else "cancelada", None


def _outcome_evidence(booking: dict | None, record: dict, lead_state: dict) -> tuple[str, datetime | None, str, str | None]:
    if booking:
        return "done", _parse_utc(booking.get("created_at")), "agendou", None
    # `relationship: Cliente` é o padrão de todo lead admitido, não prova nada. Paciente
    # de verdade é a etiqueta "Novo cliente" (label_client); contato histórico é manual.
    reason = str(record.get("ai_disabled_reason") or "")
    if reason == "label_client":
        return "done", None, "virou paciente", None
    if reason == "legacy_history":
        return "done", None, "contato histórico · atendimento manual", None
    if lead_state.get("terminal"):
        return "done", _parse_utc(lead_state.get("updated_utc")), "encerrado (Fase 7 completa)", None
    if lead_state.get("takeover"):
        return "done", _parse_utc(lead_state.get("updated_utc")), "Rodrigo assumiu", None
    return "pending", None, "", None


def _evaluate_flow_evidence(evidence: dict, ctx: dict) -> tuple[str, datetime | None, str, str | None]:
    etype = evidence.get("type")
    if etype == "first_inbound":
        return _first_inbound_evidence(ctx["lead_rows"])
    if etype == "resume_job":
        return _resume_job_evidence(ctx["jobs"], str(evidence.get("reason") or ""), ctx["bot_rows"], ctx["now"])
    if etype == "bot_bubbles":
        return _bot_bubbles_evidence(ctx["bot_rows"], str(evidence.get("regex") or ""), int(evidence.get("expected") or 1))
    if etype == "lead_after_step":
        return _lead_after_step_evidence(ctx["lead_rows"], str(evidence.get("after") or ""), ctx["computed"], ctx["now"])
    if etype == "contact_field":
        return _contact_field_evidence(ctx["record"], str(evidence.get("field") or ""))
    if etype == "booking":
        return _booking_evidence(ctx["booking"])
    if etype == "reactivation_jobs":
        return _reactivation_jobs_evidence(ctx["jobs"], ctx["now"])
    if etype == "outcome":
        return _outcome_evidence(ctx["booking"], ctx["record"], ctx["lead_state"])
    if etype == "any":
        for sub in evidence.get("of") or []:
            if not isinstance(sub, dict):
                continue
            result = _evaluate_flow_evidence(sub, ctx)
            if result[0] == "done":
                return result
        return "pending", None, "", None
    return "pending", None, "", None


def _check_first_reply_window(check: dict, evidence: dict, ctx: dict) -> dict | None:
    lead_rows, bot_rows, jobs, now = ctx["lead_rows"], ctx["bot_rows"], ctx["jobs"], ctx["now"]
    if not lead_rows:
        return None
    t0 = _flow_ts(lead_rows[0].get("timestamp"))
    fase1_regex = str((ctx["steps_by_id"].get("fase1") or {}).get("evidence", {}).get("regex") or "")
    fase1_pattern = re.compile(fase1_regex, re.I) if fase1_regex else None
    t1 = None
    if fase1_pattern:
        for row in bot_rows:
            if fase1_pattern.search(str(row.get("body") or "")):
                t1 = _flow_ts(row.get("timestamp"))
                break
    if t1 is None and bot_rows:
        t1 = _flow_ts(bot_rows[0].get("timestamp"))
    if t0 is None or t1 is None:
        return None
    min_s, max_s = int(check.get("min_s") or 0), int(check.get("max_s") or 0)
    min_m, max_m = round(min_s / 60), round(max_s / 60)
    reason = str(evidence.get("reason") or "")
    job = next(
        (j for j in jobs if j.get("cadence_kind") == "resume" and j.get("basis_outbound_id") == f"resume:{reason}"),
        None,
    )
    if job is not None and job.get("due_utc"):
        due = _parse_utc(job.get("due_utc"))
        grace_s = int(check.get("grace_s") or 0)
        ok = bool(due and due <= t1 <= due + timedelta(seconds=grace_s))
        duration = _flow_duration_minutes((due - t0).total_seconds()) if due else "?"
        label = f"{duration} (esperado {min_m} a {max_m})"
        if not ok:
            label += " — retomada atrasada"
        return {"ok": ok, "label": label}
    ok = min_s <= (t1 - t0).total_seconds() <= max_s
    duration = _flow_duration_minutes((t1 - t0).total_seconds())
    return {"ok": ok, "label": f"{duration} (esperado {min_m} a {max_m})"}


def _check_bubble_count(check: dict, evidence: dict, ctx: dict) -> dict | None:
    regex = str(evidence.get("regex") or "")
    expected = int(evidence.get("expected") or 1)
    pattern = re.compile(regex, re.I)
    count = sum(1 for row in ctx["bot_rows"] if pattern.search(str(row.get("body") or "")))
    ok = count >= expected
    label = f"{count} de {expected}" if ok else f"⚠ {count} de {expected} (abertura truncada)"
    return {"ok": ok, "label": label}


def _check_debounce_before_reaction(check: dict, evidence: dict, ctx: dict) -> dict | None:
    bot_rows, lead_rows = ctx["bot_rows"], ctx["lead_rows"]
    regex_reaction = str(check.get("regex_reaction") or "")
    pattern = re.compile(regex_reaction, re.I) if regex_reaction else None
    reaction_at = None
    if pattern:
        for row in bot_rows:
            if pattern.search(str(row.get("body") or "")):
                reaction_at = _flow_ts(row.get("timestamp"))
                break
    if reaction_at is None:
        return None
    prior_lead = [row for row in lead_rows if (_flow_ts(row.get("timestamp")) or reaction_at) < reaction_at]
    if not prior_lead:
        return None
    lead_at = _flow_ts(prior_lead[-1].get("timestamp"))
    if lead_at is None:
        return None
    elapsed = (reaction_at - lead_at).total_seconds()
    min_s = int(check.get("min_s") or 0)
    ok = elapsed >= min_s
    duration = _flow_duration(elapsed)
    return {"ok": ok, "label": f"esperou {duration}" if ok else f"⚠ respondeu em {duration}"}


def _evaluate_flow_check(check: dict, evidence: dict, ctx: dict) -> dict | None:
    ctype = check.get("type")
    if ctype == "first_reply_window":
        return _check_first_reply_window(check, evidence, ctx)
    if ctype == "bubble_count":
        return _check_bubble_count(check, evidence, ctx)
    if ctype == "debounce_before_reaction":
        return _check_debounce_before_reaction(check, evidence, ctx)
    return None


def flow_status(paths: Paths, chat_id: str, *, now: datetime | None = None) -> dict | None:
    """Stepper "Fluxo" da ficha do lead: confere o SOP declarado em `flow` do
    business_profile.json contra evidência real. Perfil sem o bloco `flow` -> None,
    e quem chama esconde o card."""
    now = now or datetime.now(timezone.utc)
    try:
        raw_profile = json.loads(Path(paths.business_profile_json).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    flow_raw = raw_profile.get("flow") if isinstance(raw_profile, dict) else None
    steps_raw = [s for s in (flow_raw.get("steps") if isinstance(flow_raw, dict) else []) or [] if isinstance(s, dict)]
    if not steps_raw:
        return None
    steps_by_id = {str(s.get("id") or ""): s for s in steps_raw}

    contacts = load_contacts(paths.contacts_json)
    record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
    chat_ids = _contact_aliases(contacts, chat_id)
    live_rows = _conversation_rows(paths.messages_db, chat_ids)
    lead_rows = [row for row in live_rows if not row.get("from_me")]
    bot_rows = [row for row in live_rows if row.get("from_me")]
    jobs = [job for job in _job_rows(paths.followups_db) if job.get("chat_id") == chat_id]
    lead_state = next((row for row in _lead_rows(paths.followups_db) if row.get("chat_id") == chat_id), {})
    booking = _booking_for_chats(paths.bookings_db, chat_ids)

    ctx = {
        "lead_rows": lead_rows, "bot_rows": bot_rows, "jobs": jobs, "record": record,
        "lead_state": lead_state, "booking": booking, "now": now, "steps_by_id": steps_by_id,
        "computed": {},
    }
    tz = daily_audit.business_tz()
    results: list[dict] = []
    for raw_step in steps_raw:
        step_id = str(raw_step.get("id") or "")
        if not step_id:
            continue
        label = str(raw_step.get("label") or step_id)
        optional = bool(raw_step.get("optional"))
        evidence = raw_step.get("evidence") if isinstance(raw_step.get("evidence"), dict) else {}
        state, at, detail, due_utc = _evaluate_flow_evidence(evidence, ctx)
        ctx["computed"][step_id] = {"state": state, "at": at}
        check_raw = raw_step.get("check") if isinstance(raw_step.get("check"), dict) else None
        check = _evaluate_flow_check(check_raw, evidence, ctx) if check_raw and state == "done" else None
        results.append({
            "id": step_id,
            "label": label,
            "optional": optional,
            "state": state,
            "at": at.astimezone(tz).isoformat() if at else None,
            "detail": detail,
            "due_utc": due_utc,
            "check": check,
        })

    current_idx = next(
        (i for i, step in enumerate(results) if not step["optional"] and step["state"] == "pending"), None,
    )
    if current_idx is not None:
        results[current_idx]["state"] = "current"

    visible = []
    for step in results:
        if step["optional"] and step["state"] in ("pending", "na") and not step["due_utc"]:
            continue
        visible.append(step)

    anchor = results[current_idx] if current_idx is not None else results[-1]
    short = _flow_short_label(anchor["label"])
    tail = anchor["detail"] or {"done": "concluído", "pending": "aguardando", "na": "não se aplica"}.get(anchor["state"], "")
    summary = f"{short} · {tail}" if tail else short

    return {"steps": visible, "summary": summary}


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


def _booking_for_chats(bookings_db: Path, chat_ids: list[str]) -> dict | None:
    """Reserva ativa do lead no banco da agenda (chaveado por hash do número)."""
    conn = _ro(bookings_db)
    if conn is None:
        return None
    try:
        keys = []
        for cid in chat_ids:
            try:
                keys.append(calendar_booking._booking_chat_key(cid))
            except Exception:
                continue
        if not keys:
            return None
        marks = ",".join("?" for _ in keys)
        row = conn.execute(
            f"SELECT event_id, start, end, timezone, meet_link, html_link, status, created_at "
            f"FROM current_bookings WHERE chat_key IN ({marks}) AND status='active' "
            f"ORDER BY updated_at DESC LIMIT 1",
            keys,
        ).fetchone()
        occurrence = None
        if row:
            try:
                occurrence = conn.execute(
                    """
                    SELECT outcome, outcome_source, outcome_updated_at,
                           rescheduled_to_start, rescheduled_to_end,
                           followup_due_at, followup_sent_at
                    FROM booking_occurrences WHERE event_id=? AND start=?
                    """,
                    (row["event_id"], row["start"]),
                ).fetchone()
            except sqlite3.Error:
                occurrence = None
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    tz = daily_audit.business_tz()
    created = datetime.fromtimestamp(float(row["created_at"] or 0), tz)
    payload = {
        "event_id": str(row["event_id"] or ""),
        "start": str(row["start"] or ""),
        "end": str(row["end"] or ""),
        "timezone": str(row["timezone"] or ""),
        "meet_link": str(row["meet_link"] or ""),
        "html_link": str(row["html_link"] or ""),
        "status": str(row["status"] or ""),
        "created_at": created.isoformat(),
    }
    if occurrence:
        payload.update({
            "outcome": str(occurrence["outcome"] or "no_status"),
            "outcome_source": str(occurrence["outcome_source"] or ""),
            "outcome_updated_at": occurrence["outcome_updated_at"],
            "rescheduled_to_start": str(occurrence["rescheduled_to_start"] or ""),
            "rescheduled_to_end": str(occurrence["rescheduled_to_end"] or ""),
            "outcome_followup_sent": bool(occurrence["followup_sent_at"]),
        })
    else:
        payload.update({"outcome": "no_status", "outcome_source": "", "outcome_followup_sent": False})
    end_at = _parse_utc(payload["end"])
    payload["outcome_pending"] = bool(
        payload["outcome"] == "no_status"
        and end_at
        and end_at <= datetime.now(timezone.utc)
    )
    return payload


def _bookings_for_leads(
    bookings_db: Path, chat_ids: list[str], *, now: datetime | None = None
) -> dict[str, dict]:
    """Carrega reuniões em uma ida ao SQLite; a chave devolvida é o chat_id original."""
    if not chat_ids:
        return {}
    key_to_chats: dict[str, list[str]] = {}
    for chat_id in chat_ids:
        try:
            key_to_chats.setdefault(calendar_booking._booking_chat_key(chat_id), []).append(chat_id)
        except Exception:
            continue
    conn = _ro(bookings_db)
    if conn is None or not key_to_chats:
        return {}
    try:
        marks = ",".join("?" for _ in key_to_chats)
        rows = conn.execute(
            f"""
            SELECT c.chat_key, c.event_id, c.start, c.end, c.timezone, c.meet_link,
                   c.html_link, COALESCE(o.outcome, 'no_status') AS outcome,
                   o.rescheduled_to_start, o.followup_sent_at
            FROM current_bookings c
            LEFT JOIN booking_occurrences o
              ON o.event_id=c.event_id AND o.start=c.start
            WHERE c.chat_key IN ({marks}) AND c.status='active'
            """,
            list(key_to_chats),
        ).fetchall()
    except sqlite3.Error:
        try:
            rows = conn.execute(
                f"""
                SELECT chat_key, event_id, start, end, timezone, meet_link, html_link,
                       'no_status' AS outcome, '' AS rescheduled_to_start,
                       NULL AS followup_sent_at
                FROM current_bookings
                WHERE chat_key IN ({marks}) AND status='active'
                """,
                list(key_to_chats),
            ).fetchall()
        except sqlite3.Error:
            return {}
    finally:
        conn.close()
    result: dict[str, dict] = {}
    current = now or datetime.now(timezone.utc)
    for row in rows:
        end_at = _parse_utc(row["end"])
        meeting = {
            "event_id": str(row["event_id"] or ""),
            "start": str(row["start"] or ""),
            "end": str(row["end"] or ""),
            "meet_link": str(row["meet_link"] or ""),
            "outcome": str(row["outcome"] or "no_status"),
            "rescheduled_to_start": str(row["rescheduled_to_start"] or ""),
            "outcome_followup_sent": bool(row["followup_sent_at"]),
        }
        meeting["outcome_pending"] = bool(
            meeting["outcome"] == "no_status" and end_at and end_at <= current
        )
        for chat_id in key_to_chats.get(str(row["chat_key"]), []):
            result[chat_id] = meeting
    return result


_QUALIFICATION_NOISE_RE = re.compile(
    r"^(?:oi+|ol[aá]|opa|bom\s+dia|boa\s+tarde|boa\s+noite|sim|isso|isso\s+mesmo|ok|blz|beleza|"
    r"claro|pode|pode\s+ser|funciona|perfeito|show|t[aá]\s+bom|obrigad[oa])[\s!.,]*$",
    re.IGNORECASE,
)


def _stored_qualification(bookings_db: Path, chat_ids: list[str]) -> list[str]:
    """Campos do playbook extraídos após a reserva (ver calendar_booking). Quando
    existem, valem mais que as frases soltas do lead."""
    for cid in chat_ids:
        try:
            items = calendar_booking.get_lead_qualification(cid, db_path=bookings_db)
        except Exception:
            items = []
        facts = [
            f"{item.get('label') or item.get('key')}: {item.get('value')}"
            for item in items if str(item.get("value") or "").strip()
        ]
        if facts:
            return facts
    return []


def _lead_qualification(rows: list[dict], limit: int = 3) -> list[str]:
    """Falas do lead que descrevem o caso dele: o que o dono quer ver na ficha e
    na reunião, sem depender de classificador."""
    facts: list[str] = []
    for row in rows:
        if row.get("from_me"):
            continue
        body = " ".join(str(row.get("body") or "").split())
        if len(body) < 15 or _QUALIFICATION_NOISE_RE.match(body):
            continue
        clean = body[:160]
        if clean not in facts:
            facts.append(clean)
        if len(facts) >= limit:
            break
    return facts


def lead_detail(
    paths: Paths, chat_id: str, now: datetime | None = None, *, lid_map: dict | None = None,
    pipeline_id: str = "default", avatars: dict | None = None,
) -> dict:
    """Conversa de um lead (viva + histórico importado), pronta para a tela de
    detalhe."""
    now = now or datetime.now(timezone.utc)
    preset = pipeline(pipeline_id)
    contacts = load_contacts(paths.contacts_json)
    record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
    chat_ids = _contact_aliases(contacts, chat_id, lid_map)
    live_rows = _conversation_rows(paths.messages_db, chat_ids)
    historical_rows = _historical_rows(paths.messages_db, chat_ids, limit=200)
    events = _mark_conversation_owners(live_rows, paths.plugin_log, chat_ids)
    outbound = panel_store.outbound_for_chats(paths.panel_db, chat_ids)
    if outbound:
        # Resposta mandada pelo painel: autoria própria, não a inferência por log
        # (`_mark_conversation_owners` marcaria "aya" num dia sem `[human-send]`).
        for row in live_rows:
            entry = outbound.get(str(row.get("message_id") or ""))
            if entry:
                row["owner"] = "owner"
                row["sent_by"] = entry["sent_by"]
    combined_rows = sorted(
        historical_rows + live_rows,
        key=lambda row: (float(row.get("timestamp") or 0), int(row.get("id") or 0)),
    )[-200:]
    meeting = _booking_for_chats(paths.bookings_db, chat_ids)
    flow_events = _flow_timeline(paths, chat_id, events)
    if meeting:
        when = _parse_utc(meeting["start"])
        flow_events.append({
            "type": "event",
            "event": "booking",
            "at": meeting["created_at"],
            "label": "Reunião marcada pela AYA",
            "reason": when.astimezone(daily_audit.business_tz()).strftime("%d/%m às %H:%M") if when else meeting["start"],
        })
    timeline = _message_timeline(combined_rows, flow_events)
    lead = next((row for row in _lead_rows(paths.followups_db) if row.get("chat_id") == chat_id), {})
    open_jobs = [
        job for job in _job_rows(paths.followups_db)
        if job.get("chat_id") == chat_id and job.get("status") in ("pending", "leased")
    ]
    next_job = min(open_jobs, key=lambda job: str(job.get("due_utc") or "9"), default={})
    next_action = None
    if next_job:
        next_due = _parse_utc(next_job.get("due_utc"))
        next_job_kind = _job_kind(str(next_job.get("cadence_kind") or ""))
        next_action = {
            "kind": next_job_kind,
            "label": _job_action_label(next_job, next_job_kind),
            "due_utc": next_due.isoformat() if next_due else "",
            "due_local": _fmt_due_local(next_due),
            "waiting_window": bool(next_due and next_due < now and next_job.get("status") == "pending"),
        }
    engine_stage = str(lead.get("stage") or "new")
    imported = _imported_context(paths.followups_db, chat_id, preset)
    imported["historical_messages"] = _historical_message_count(paths.messages_db, chat_ids)
    imported_row = {"status": imported.get("status", ""), "excluded": imported.get("excluded", False)}
    stage = resolve_pipeline_stage(preset, contact_record=record, lead_row=lead, imported_row=imported_row) or "new"
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
        "avatar_url": avatar_url(avatars, *chat_ids),
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
            "next_action": next_action,
            "source_status": imported.get("status", ""),
            "source_paused": bool(imported.get("paused")),
        },
        "meeting": meeting,
        "qualification": _stored_qualification(paths.bookings_db, chat_ids) or _lead_qualification(live_rows),
        "imported_history": imported,
        "usage": _session_usage_for_chat(paths.state_db, chat_ids),
        "timeline": timeline,
        "flow": flow_status(paths, chat_id, now=now),
        "ai": ai,
        "triage": triage,
        "legacy": kind == "legacy",
        "client": management_client_for_chat(paths, chat_ids),
        "origin_metadata": {
            "origin": str(record.get("origin") or ""),
            "campaign": str(record.get("campaign") or ""),
            "ad_id": str(record.get("ad_id") or ""),
            "ad_title": str(record.get("ad_title") or ""),
            "ad_body": str(record.get("ad_body") or ""),
            "ad_source_app": str(record.get("ad_source_app") or ""),
            "ad_source_type": str(record.get("ad_source_type") or ""),
            "ad_url": str(record.get("ad_url") or ""),
            "ctwa_clid": str(record.get("ctwa_clid") or ""),
            "conversion_delay_seconds": record.get("conversion_delay_seconds"),
            "flow_origin": str(record.get("flow_origin") or ""),
        },
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


def _imported_context(followups_db: Path, chat_id: str, preset: dict) -> dict[str, Any]:
    """Estado comercial de um sistema anterior do cliente, somente leitura:
    status na tabela declarada em `imported` e, com `commercial_metrics`, o
    histórico de agendamentos, compras e escalonamentos migrados."""
    empty = {
        "status": "", "excluded": False, "appointments": [], "purchases": [],
        "escalations": [], "reactivation_stage": None,
    }
    imported_cfg = preset.get("imported")
    if not imported_cfg and not preset.get("commercial_metrics"):
        return dict(empty)
    conn = _ro(followups_db)
    if conn is None:
        return dict(empty)
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        context: dict[str, Any] = dict(empty)
        if imported_cfg and imported_cfg["table"] in tables:
            flag = imported_cfg["excluded_flag"]
            select = f"{imported_cfg['status_column']}" + (f", {flag}" if flag else "")
            row = conn.execute(
                f"SELECT {select} FROM {imported_cfg['table']} WHERE chat_id=?", (chat_id,)
            ).fetchone()
            if row is not None:
                context["status"] = str(row[0] or "")
                context["excluded"] = bool(row[1]) if flag else False
        if preset.get("commercial_metrics"):
            for table in ("appointments", "purchases", "escalations"):
                if table in tables:
                    context[table] = [
                        dict(row) for row in conn.execute(
                            f"SELECT * FROM {table} WHERE chat_id=? ORDER BY created_at", (chat_id,)
                        ).fetchall()
                    ]
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


def _imported_lead_rows(followups_db: Path, preset: dict) -> dict[str, dict]:
    """Tabela importada inteira, por chat_id — pra resolver o estágio do board
    sem uma query por card. Vazio quando o preset não declara `imported`."""
    imported_cfg = preset.get("imported")
    if not imported_cfg:
        return {}
    conn = _ro(followups_db)
    if conn is None:
        return {}
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if imported_cfg["table"] not in tables:
            return {}
        flag = imported_cfg["excluded_flag"]
        select = f"chat_id, {imported_cfg['status_column']} AS status" + (f", {flag} AS excluded" if flag else ", 0 AS excluded")
        rows = conn.execute(f"SELECT {select} FROM {imported_cfg['table']}").fetchall()
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
    imported_rows = _imported_lead_rows(paths.followups_db, preset)
    meetings = _bookings_for_leads(
        paths.bookings_db, [str(row["chat_id"]) for row in rows], now=now,
    )
    stage_ids = [stage_id for stage_id, _label, _engine_stage, _terminal in preset["stages"]]
    columns: dict[str, list[dict]] = {stage_id: [] for stage_id in stage_ids}
    terminal = {"won": 0, "lost": 0}
    excluded = {"outside_funnel": 0, "blocked": 0}
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
                preset, contact_record=record, lead_row=row, imported_row=imported_rows.get(chat_id),
            )
            if stage is None:
                excluded["outside_funnel"] += 1
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
            "meeting": meetings.get(chat_id),
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
        "excluded_label": (preset.get("imported") or {}).get("excluded_label") or "fora do funil",
        "total": sum(len(columns[stage_id]) for stage_id in stage_ids if not stage_meta[stage_id][1]),
    }


def _excluded_contact_key(key: str) -> bool:
    return key.endswith("@g.us") or key.endswith("@broadcast")


def contacts_directory(
    paths: Paths, *, owner_number: str = "", lid_map: dict | None = None,
    pipeline_id: str = "default", now: datetime | None = None, avatars: dict | None = None,
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
    imported_rows = _imported_lead_rows(paths.followups_db, preset)
    last_all = _last_messages_all(paths.messages_db)
    meetings = _bookings_for_leads(paths.bookings_db, list(lead_by_chat), now=now)

    rows_out: list[dict] = []
    flag_counts: dict[str, int] = {}
    counts = {"all": 0, "attention": 0, "human": 0, "aya": 0, "sem_responsavel": 0, "legacy": 0, "blocked": 0, "reactivation": 0}
    # Os escopos que falam de IA leem o atendimento aberto, não a heurística do funil.
    abertos = {row["contato"]: row for row in atendimento_store.listar_abertos(paths.panel_db)}
    nomes_usuarios = {u["username"]: u["name"] for u in users_store.list_users(paths.users_json)}

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
        aberto = next((abertos[k] for k in keys if k in abertos), None)
        automation = bool((lead or {}).get("automation_enabled"))
        # Fonte única: com atendimento aberto, "humano" e "com a IA" vêm dele; sem
        # atendimento (contato fora da janela do primeiro boot), a heurística antiga do funil.
        if aberto is not None:
            tipo = aberto["responsavel_tipo"]
            user = aberto.get("responsavel_user")
            atendimento = {
                "protocolo": aberto["protocolo"],
                "responsavel_tipo": tipo,
                "responsavel_user": user,
                "responsavel_nome": nomes_usuarios.get(user, user) if user else None,
                "aguardando_nos": aberto.get("ultima_msg_autor") == "contato",
            }
            human, com_ia, sem_responsavel = tipo in atendimento_store.HUMANOS, tipo == "ia", tipo == "nenhum"
        else:
            atendimento = None
            human = bool((lead or {}).get("takeover"))
            com_ia, sem_responsavel = automation and not human, False
        stage = stage_label = None
        estimated_value_cents = None
        next_followup, next_followup_rel = "", ""
        meeting = None
        if lead is not None:
            lead_chat_id = lead["chat_id"]
            meeting = meetings.get(lead_chat_id)
            stage = resolve_pipeline_stage(
                preset,
                contact_record={"pipeline_stage": pipeline_stage_override} if pipeline_stage_override else {},
                lead_row=lead, imported_row=imported_rows.get(lead_chat_id),
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
            "avatar_url": avatar_url(avatars, canonical_key, *keys),
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
            "meeting": meeting,
            "preview": preview,
            "last_at": last_at,
            "last": last,
            "last_historical": last_historical,
            "triage": triage,
            "relationship": relationship,
            "legacy": kind == "legacy",
            "atendimento": atendimento,
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
        if com_ia:
            counts["aya"] += 1
        if sem_responsavel:
            counts["sem_responsavel"] += 1
        if human or next_followup_rel == "atrasado" or bool(meeting and meeting.get("outcome_pending")):
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
            kind = _job_kind(cadence)
            reason_label = _resume_reason_label(job) if kind == "resume" else ""
            step_label = _reactivation_step_label(job) if kind == "reactivation" else ""
            created = _parse_utc(job.get("created_utc"))
            queue.append({
                **base,
                "due": due_label,
                "due_rel": due_rel,
                "due_utc": due.isoformat() if due else "",
                "due_local": _fmt_due_local(due),
                "created_utc": created.isoformat() if created else "",
                "waiting_window": bool(due and due < now and status == "pending"),
                "soon": bool(due and due - now < timedelta(hours=4)),
                "paused": paused,
                "text": text,
                "kind": kind,
                "reason_label": reason_label,
                "step_label": step_label,
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
    ritmo_cfg = load_ritmo_config(paths.business_profile_json)
    ritmo = {**ritmo_cfg, "engine": _ritmo_engine_status(paths, now)} if ritmo_cfg is not None else None
    return {
        "queue": queue,
        "history": history[:40],
        "stats": stats,
        "schedule": load_business_hours(paths.business_profile_json),
        "ritmo": ritmo,
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
    imported_rows = _imported_lead_rows(paths.followups_db, preset)

    def _item(row: dict) -> dict:
        chat_id = row["chat_id"]
        record = contacts.get(chat_id) if isinstance(contacts.get(chat_id), dict) else {}
        lead_row = lead_by_chat.get(chat_id)
        stage = resolve_pipeline_stage(
            preset, contact_record=record, lead_row=lead_row, imported_row=imported_rows.get(chat_id),
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
    """KPIs comerciais de um sistema anterior migrado (agendamentos, compras e
    escalonamentos). Sempre presente na resposta de `metrics`; só lê as tabelas
    quando o preset liga `commercial_metrics`, e fica zerado quando elas não
    existem."""
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
    if not preset.get("commercial_metrics"):
        return result
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


# ── gestão da carteira (só a instância; ver `management_enabled`) ───────────

CLIENT_STATUS_LABEL = {
    "negotiation": "Negociação",
    "awaiting_payment": "Aguardando pagamento",
    "onboarding": "Onboarding",
    "implementation": "Implementação",
    "qa": "QA",
    "active": "Ativo",
    "paused": "Pausado",
    "cancelled": "Cancelado",
}
CLIENT_KIND_LABEL = {"atendimento": "IA de atendimento", "reativacao": "Reativação", "teste": "Teste"}
TICKET_KIND_LABEL = {
    "incident": "Incidente", "question": "Dúvida", "request": "Solicitação",
    "improvement": "Melhoria", "billing": "Financeiro", "other": "Outro",
}
TICKET_PRIORITY_LABEL = {"critical": "Crítica", "high": "Alta", "medium": "Média", "low": "Baixa"}
TICKET_ORIGIN_LABEL = {
    "whatsapp": "WhatsApp", "internal": "Interno", "email": "E-mail", "audit": "Auditoria", "other": "Outro",
}
TICKET_STATUS_LABEL = {
    "open": "Aberto", "triage": "Triagem", "in_progress": "Em andamento",
    "waiting_client": "Aguardando cliente", "waiting_third_party": "Aguardando terceiro",
    "resolved": "Resolvido", "closed": "Fechado",
}
TOUCHPOINT_KIND_LABEL = {
    "kickoff": "Kickoff", "checkin": "Check-in", "usage_review": "Revisão de uso",
    "renewal": "Renovação", "churn_risk": "Risco de cancelamento", "other": "Outro",
}
HEALTH_LABEL = {"healthy": "Saudável", "attention": "Atenção", "at_risk": "Em risco"}
COST_CATEGORY_LABEL = {"vps": "VPS", "ai": "IA", "domain": "Domínio", "tools": "Ferramentas", "other": "Outro"}
COST_PERIODICITY_LABEL = {
    "monthly": "Mensal",
    "annual": "Anual (renovação)",
    "annual_amortized": "Anual (amortizado)",
    "one_off": "Avulso",
}
COST_STATUS_LABEL = {"pending": "A pagar", "paid": "Pago"}
CHARGE_KIND_LABEL = {"monthly": "Mensalidade", "setup": "Implementação", "adhoc": "Avulsa"}


def management_enabled(custom: dict) -> bool:
    """`{"features": {"management": true}}` em `panel.config.json`. Instalação de
    cliente nunca liga isto: é a carteira da própria instância."""
    features = custom.get("features") if isinstance(custom.get("features"), dict) else {}
    return features.get("management") is True


def marketing_enabled(custom: dict) -> bool:
    """`{"features": {"marketing": true}}`: funil das landing pages cruzado com o
    WhatsApp. Só na instância da própria AYA, que é quem tem LP."""
    features = custom.get("features") if isinstance(custom.get("features"), dict) else {}
    return features.get("marketing") is True


def management_labels() -> dict:
    return {
        "client_status": CLIENT_STATUS_LABEL,
        "client_kind": CLIENT_KIND_LABEL,
        "ticket_kind": TICKET_KIND_LABEL,
        "ticket_priority": TICKET_PRIORITY_LABEL,
        "ticket_origin": TICKET_ORIGIN_LABEL,
        "ticket_status": TICKET_STATUS_LABEL,
        "touchpoint_kind": TOUCHPOINT_KIND_LABEL,
        "health": HEALTH_LABEL,
        "cost_category": COST_CATEGORY_LABEL,
        "cost_periodicity": COST_PERIODICITY_LABEL,
        "cost_status": COST_STATUS_LABEL,
        "charge_kind": CHARGE_KIND_LABEL,
        "onboarding_defaults": list(management_store.DEFAULT_ONBOARDING_STEPS),
    }


def management_client_for_chat(paths: Paths, chat_ids: list[str] | str) -> dict | None:
    """Vínculo lead → cliente para a tela do lead. `@lid` não vincula; usa o
    telefone da lista de aliases."""
    if isinstance(chat_ids, str):
        chat_ids = [chat_ids]
    if not Path(paths.management_db).is_file():
        return None  # instalação sem o módulo: não cria o banco por tabela
    for chat_id in chat_ids:
        if not chat_id or chat_id.endswith("@lid"):
            continue
        try:
            found = management_store.get_client_by_chat(paths.management_db, chat_id)
        except management_store.ManagementError:
            continue
        if found:
            return {"id": found["id"], "name": found["name"], "status": found["status"],
                    "status_label": CLIENT_STATUS_LABEL.get(found["status"], found["status"])}
    return None


def management_clients(paths: Paths, *, status: str | None = None) -> dict:
    rows = management_store.list_clients(paths.management_db, status=status)
    for row in rows:
        row["status_label"] = CLIENT_STATUS_LABEL.get(row["status"], row["status"])
        row["phone_display"] = format_phone(row["chat_id"]) if row.get("chat_id") else (row.get("phone") or "")
    counts = {sid: 0 for sid in management_store.CLIENT_STATUSES}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "clients": rows,
        "counts": counts,
        "mrr_cents": sum(r["monthly_cents"] for r in rows if r["status"] == "active"),
        "statuses": [{"id": sid, "label": CLIENT_STATUS_LABEL[sid]} for sid in management_store.CLIENT_STATUSES],
    }


def management_client(paths: Paths, client_id: int) -> dict | None:
    row = management_store.get_client(paths.management_db, client_id)
    if not row:
        return None
    row["status_label"] = CLIENT_STATUS_LABEL.get(row["status"], row["status"])
    row["phone_display"] = format_phone(row["chat_id"]) if row.get("chat_id") else (row.get("phone") or "")
    row["cost_plans"] = [p for p in management_store.list_cost_plans(paths.management_db) if p["client_id"] == client_id]
    return row


def management_tickets(paths: Paths, *, status: str | None = None, client_id: int | None = None,
                       open_only: bool = False) -> dict:
    rows = management_store.list_tickets(paths.management_db, status=status, client_id=client_id, open_only=open_only)
    counts = {sid: 0 for sid in management_store.TICKET_STATUSES}
    for row in management_store.list_tickets(paths.management_db):
        counts[row["status"]] += 1
    return {"tickets": rows, "counts": counts,
            "open": sum(v for k, v in counts.items() if k not in management_store.TICKET_DONE)}


def management_ticket(paths: Paths, ticket_id: int) -> dict | None:
    return management_store.get_ticket(paths.management_db, ticket_id)


def management_finance(paths: Paths, period: str, *, today: date | None = None) -> dict:
    """Abre a competência: materializa cobranças e planos de custo (idempotente)
    e devolve o placar com os planos vigentes para edição."""
    created = management_store.ensure_period(paths.management_db, period)
    summary = management_store.finance_summary(paths.management_db, period, today=today)
    summary["created"] = created
    summary["cost_plans"] = management_store.list_cost_plans(paths.management_db, period=period)
    summary["all_cost_plans"] = management_store.list_cost_plans(paths.management_db)
    summary["cash_calibrations"] = management_store.list_cash_calibrations(paths.management_db)
    return summary
def ads_report(paths: Paths, now: datetime | None = None) -> dict:
    """Relatório analítico de atribuição de tráfego de anúncios (Meta Ads / CTWA).
    
    Analisa os contatos em personal_contacts.json, identifica leads originados
    de anúncios pagos, cruza com agendamentos no Google Calendar / SQLite
    e quantifica conversões e receita gerada por anúncio e por canal.
    """
    now = now or datetime.now(timezone.utc)
    contacts = load_contacts(paths.contacts_json)

    conn_b = _ro(paths.bookings_db)
    active_bookings_by_key = {}
    if conn_b is not None:
        try:
            for row in conn_b.execute(
                "SELECT chat_key, event_id, start, status, created_at FROM current_bookings WHERE status='active'"
            ).fetchall():
                active_bookings_by_key[row["chat_key"]] = dict(row)
        except sqlite3.Error:
            pass
        finally:
            conn_b.close()

    session_ticket_brl = 247.0

    ad_leads = []
    for chat_id, record in contacts.items():
        if not isinstance(record, dict):
            continue
        origin = str(record.get("origin") or "").strip()
        ad_id = str(record.get("ad_id") or "").strip()
        ad_title = str(record.get("ad_title") or "").strip()
        flow_origin = str(record.get("flow_origin") or "").strip()

        is_ad_lead = bool(
            origin in ("FB_Ads", "Instagram_Ads", "Meta_Ads", "Facebook_Ads")
            or ad_id
            or ad_title
            or record.get("ctwa_clid")
            or flow_origin == "new_live_commercial"
        )
        if not is_ad_lead:
            continue

        booked = False
        booking_info = None
        try:
            chat_key = calendar_booking._booking_chat_key(chat_id)
            if chat_key in active_bookings_by_key:
                booked = True
                booking_info = active_bookings_by_key[chat_key]
        except Exception:
            pass

        if not booked:
            if record.get("commercial_stage") == "SCHEDULED" or record.get("playbook_completion_at"):
                booked = True

        source_app = str(record.get("ad_source_app") or "").lower()
        if "insta" in source_app:
            channel = "Instagram Ads"
        elif "face" in source_app or origin == "FB_Ads":
            channel = "Facebook Ads" if "face" in source_app else "Meta Ads"
        else:
            channel = "Meta Ads (Instagram / FB)"

        campaign_name = str(record.get("campaign") or "").strip() or "Campanha Padrão"
        creative_title = ad_title or (f"Anúncio #{ad_id}" if ad_id else "Click-to-WhatsApp Padrão")

        first_at = record.get("first_live_inbound_at") or record.get("therapify_created_at") or record.get("last_interaction")
        try:
            created_iso = datetime.fromtimestamp(float(first_at), timezone.utc).isoformat() if first_at else ""
        except (ValueError, TypeError, OSError):
            created_iso = ""

        ad_leads.append({
            "chat_id": chat_id,
            "name": _contact_name(contacts, chat_id),
            "phone": format_phone(chat_id),
            "origin": origin or "FB_Ads",
            "campaign": campaign_name,
            "ad_id": ad_id or "—",
            "ad_title": creative_title,
            "channel": channel,
            "source_app": source_app or "meta",
            "ctwa_clid": str(record.get("ctwa_clid") or ""),
            "conversion_delay_seconds": record.get("conversion_delay_seconds"),
            "created_at": created_iso,
            "created_timestamp": float(first_at) if first_at else 0.0,
            "stage": str(record.get("commercial_stage") or "NEW"),
            "booked": booked,
            "booking_start": booking_info["start"] if booking_info else None,
            "revenue_brl": session_ticket_brl if booked else 0.0,
        })

    ad_leads.sort(key=lambda l: l["created_timestamp"], reverse=True)

    by_ad_dict = {}
    for lead in ad_leads:
        key = lead["ad_title"]
        if key not in by_ad_dict:
            by_ad_dict[key] = {
                "ad_title": lead["ad_title"],
                "ad_id": lead["ad_id"],
                "channel": lead["channel"],
                "campaign": lead["campaign"],
                "leads_count": 0,
                "booked_count": 0,
                "revenue_brl": 0.0,
                "leads": [],
            }
        group = by_ad_dict[key]
        group["leads_count"] += 1
        if lead["booked"]:
            group["booked_count"] += 1
            group["revenue_brl"] += lead["revenue_brl"]
        group["leads"].append({
            "chat_id": lead["chat_id"],
            "name": lead["name"],
            "phone": lead["phone"],
            "created_at": lead["created_at"],
            "booked": lead["booked"],
        })

    by_ad = []
    for item in by_ad_dict.values():
        cnt = item["leads_count"]
        b_cnt = item["booked_count"]
        conv_rate = round((b_cnt / cnt) * 100, 1) if cnt > 0 else 0.0
        by_ad.append({
            **item,
            "conversion_rate_pct": conv_rate,
        })
    by_ad.sort(key=lambda a: (a["booked_count"], a["leads_count"]), reverse=True)

    by_channel_dict = {}
    for lead in ad_leads:
        ch = lead["channel"]
        if ch not in by_channel_dict:
            by_channel_dict[ch] = {"channel": ch, "leads_count": 0, "booked_count": 0, "revenue_brl": 0.0}
        by_channel_dict[ch]["leads_count"] += 1
        if lead["booked"]:
            by_channel_dict[ch]["booked_count"] += 1
            by_channel_dict[ch]["revenue_brl"] += lead["revenue_brl"]

    by_channel = []
    for item in by_channel_dict.values():
        cnt = item["leads_count"]
        b_cnt = item["booked_count"]
        by_channel.append({
            **item,
            "conversion_rate_pct": round((b_cnt / cnt) * 100, 1) if cnt > 0 else 0.0,
        })
    by_channel.sort(key=lambda c: c["leads_count"], reverse=True)

    total_leads = len(ad_leads)
    total_booked = sum(1 for l in ad_leads if l["booked"])
    total_revenue = total_booked * session_ticket_brl
    global_conversion = round((total_booked / total_leads) * 100, 1) if total_leads > 0 else 0.0

    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp()
    d7_start = today_start - (7 * 86400)
    leads_today = sum(1 for l in ad_leads if l["created_timestamp"] >= today_start)
    leads_7d = sum(1 for l in ad_leads if l["created_timestamp"] >= d7_start)

    return {
        "summary": {
            "total_ad_leads": total_leads,
            "total_booked": total_booked,
            "conversion_rate_pct": global_conversion,
            "total_revenue_brl": round(total_revenue, 2),
            "session_ticket_brl": session_ticket_brl,
            "leads_today": leads_today,
            "leads_7d": leads_7d,
        },
        "by_ad": by_ad,
        "by_channel": by_channel,
        "leads": ad_leads,
    }
