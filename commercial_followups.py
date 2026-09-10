"""Motor transacional e fail-closed de follow-up comercial da WhatsAYA.

Este módulo não conhece o gateway nem envia mensagens. Ele mantém estado, agenda,
lease e idempotência em SQLite. O chamador precisa revalidar o job imediatamente
antes do envio e registrar o resultado real retornado pela bridge.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BUSINESS_TZ = ZoneInfo("America/Sao_Paulo")
BUSINESS_OPEN = time(8, 0)
BUSINESS_CLOSE = time(18, 0)
TERMINAL_STAGES = {"ganho", "perdido", "cancelado", "concluido", "concluída", "won", "lost", "cancelled"}
CONTEXT_KINDS = {"business", "pain", "question", "objection", "proposal", "payment", "next_step"}
MAX_ESTIMATED_VALUE_CENTS = 9_999_999_999
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_LONG_DIGITS_RE = re.compile(r"\d{6,}")
_FOLLOWUP_GREETING_RE = re.compile(
    r"^(?:(?:oi|ol[aá]|opa|bom\s+dia|boa\s+tarde|boa\s+noite)[!,.\s:—-]*)+",
    re.IGNORECASE,
)
_FOLLOWUP_INTENT_RE = re.compile(
    r"^(?:eu\s+)?(?:queria|quero|gostaria(?:\s+de)?|"
    r"preciso(?:\s+de)?|precisava(?:\s+de)?)\s+(?P<subject>.+)$",
    re.IGNORECASE,
)
_FOLLOWUP_POSSESSION_RE = re.compile(
    r"^tenho\s+(?P<article>uma|um)\s+(?P<topic>.+)$",
    re.IGNORECASE,
)
# Copy por (stage, kind, step). Sempre cita o fato verificado; nunca ping genérico.
_FOLLOWUP_COPY = {
    ("qualification", "pain", 1):
        "Você falou de {fact}. Posso te mostrar como a AYA entra nisso, sem enrolação.",
    ("qualification", "pain", 2):
        "Ainda vale {fact}? A gente resolve isso numa call curta.",
    ("qualification", "pain", 3):
        "Último toque: {fact}. Se saiu da pauta, sem problema.",
    ("pricing", "question", 1):
        "Ficou pendente {fact}. A proposta é personalizada e fecha numa call curta — quer que eu encaixe?",
    ("pricing", "question", 2):
        "Sobre o investimento ({fact}): sem tabela neste chat, a gente fecha na call. Prefere um horário?",
    ("pricing", "question", 3):
        "Se {fact} ainda importa, me fala um período que o time te encaixa.",
    ("proposal", "next_step", 1):
        "A gente tinha ficado em {fact}. Me fala um período pra call da proposta.",
    ("proposal", "next_step", 2):
        "Ainda vale {fact}? O time encaixa a call no período que você passar.",
    ("proposal", "next_step", 3):
        "Se {fact} saiu da pauta, sem problema — é só responder por aqui.",
    ("payment", "payment", 1):
        "Os dados oficiais já foram, sobre {fact}. Qualquer trava no pagamento, me chama aqui.",
    ("payment", "payment", 2):
        "Retomando o pagamento de {fact}. Se já fez, manda o comprovante; se não, te ajudo.",
    ("payment", "payment", 3):
        "Último aviso sobre {fact}. Se fechou por outro canal, me confirma.",
}
CADENCES: dict[str, tuple[tuple[str, int], ...]] = {
    "silence": (("business_minutes", 30), ("business_days", 1), ("business_days", 3)),
    "proposal": (("business_days", 1), ("business_days", 3), ("business_days", 7)),
    "payment": (("business_minutes", 240), ("business_days", 1), ("business_days", 3)),
    "post_sale": (("business_days", 1), ("business_days", 7), ("business_days", 30)),
}
OUTBOX_WHITELIST = {
    "chat_id", "stage", "cadence_kind", "automation_enabled", "next_action",
    "next_followup_utc", "attempt_count", "followup_status", "last_error",
}
_SECRET_RE = re.compile(
    r"(?:api[_ -]?key|token|senha|password|secret|bearer|sk-[a-z0-9]|\b\d{16}\b)",
    re.IGNORECASE,
)
NOTION_LEAD_STAGES = ("new", "qualification", "pricing", "proposal", "payment")
NOTION_LEAD_CADENCES = ("silence", "proposal", "payment", "post_sale")
_NOTION_TEXT_CAP = 1900


class ContextGateError(ValueError):
    """O contexto não é seguro/suficiente para mensagem automática."""


def _ensure_utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("datetime precisa ter timezone")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _ensure_utc(value).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_HOLIDAY_RE = re.compile(r"^(?:\d{4}-)?(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


def _parse_zone(value: Any) -> ZoneInfo | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _parse_hhmm(value: Any) -> time | None:
    if not isinstance(value, str):
        return None
    match = _HHMM_RE.match(value.strip())
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)))


@dataclass(frozen=True)
class BusinessHours:
    """Horário comercial de um cliente: fuso, janela e feriados.

    Feriados em `holidays` são `"MM-DD"` (se repete todo ano) ou `"YYYY-MM-DD"`
    (data avulsa). `DEFAULT_HOURS` mantém o comportamento genérico (8h-18h, sem
    feriado) para quem não tem `business_profile.json`.
    """

    tz: ZoneInfo
    open: time
    close: time
    holidays: frozenset[str] = frozenset()

    def is_off_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return True
        return d.strftime("%m-%d") in self.holidays or d.isoformat() in self.holidays

    def is_within_hours(self, dt: datetime) -> bool:
        local = _ensure_utc(dt).astimezone(self.tz)
        return self.open <= local.time() < self.close

    @classmethod
    def from_profile(cls, profile: dict | None) -> "BusinessHours":
        schedule = profile.get("schedule") if isinstance(profile, dict) else None
        if not isinstance(schedule, dict):
            return DEFAULT_HOURS
        holidays: set[str] = set()
        for key in ("holidays_fixed", "holidays_extra"):
            values = schedule.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, str) and _HOLIDAY_RE.match(item.strip()):
                    holidays.add(item.strip())
        return cls(
            tz=_parse_zone(schedule.get("timezone")) or DEFAULT_HOURS.tz,
            open=_parse_hhmm(schedule.get("open")) or DEFAULT_HOURS.open,
            close=_parse_hhmm(schedule.get("close")) or DEFAULT_HOURS.close,
            holidays=frozenset(holidays),
        )


DEFAULT_HOURS = BusinessHours(tz=BUSINESS_TZ, open=BUSINESS_OPEN, close=BUSINESS_CLOSE, holidays=frozenset())


def is_business_time(value: datetime, hours: BusinessHours = DEFAULT_HOURS) -> bool:
    local = _ensure_utc(value).astimezone(hours.tz)
    return not hours.is_off_day(local.date()) and hours.is_within_hours(local)


def next_business_time(value: datetime, hours: BusinessHours = DEFAULT_HOURS) -> datetime:
    """Retorna o próprio instante se válido; senão, próxima abertura comercial."""
    return next_window_open(value, hours, skip_off_days=True)


def next_window_open(value: datetime, hours: BusinessHours = DEFAULT_HOURS, *, skip_off_days: bool) -> datetime:
    """Como `next_business_time`, mas com feriado/fim de semana opcional.

    Com `skip_off_days=False`, sábado/domingo/feriado contam como dia válido —
    usado na regra de fim de semana ("sábado 23h -> abre domingo 9h").
    """
    local = _ensure_utc(value).astimezone(hours.tz)
    while True:
        if skip_off_days and hours.is_off_day(local.date()):
            local = datetime.combine(local.date() + timedelta(days=1), hours.open, hours.tz)
            continue
        if local.time() < hours.open:
            return datetime.combine(local.date(), hours.open, hours.tz).astimezone(UTC)
        if local.time() >= hours.close:
            local = datetime.combine(local.date() + timedelta(days=1), hours.open, hours.tz)
            continue
        return local.astimezone(UTC)


def add_business_minutes(value: datetime, minutes: int, hours: BusinessHours = DEFAULT_HOURS) -> datetime:
    if minutes < 0:
        raise ValueError("minutes precisa ser >= 0")
    current = next_business_time(value, hours).astimezone(hours.tz)
    remaining = int(minutes)
    if remaining == 0:
        return current.astimezone(UTC)
    while True:
        close = datetime.combine(current.date(), hours.close, hours.tz)
        available = int((close - current).total_seconds() // 60)
        if remaining < available:
            return (current + timedelta(minutes=remaining)).astimezone(UTC)
        remaining -= available
        current = next_business_time((close + timedelta(seconds=1)).astimezone(UTC), hours).astimezone(hours.tz)


def add_business_days(value: datetime, days: int, hours: BusinessHours = DEFAULT_HOURS) -> datetime:
    if days < 0:
        raise ValueError("days precisa ser >= 0")
    local = next_business_time(value, hours).astimezone(hours.tz)
    target_date = local.date()
    remaining = int(days)
    while remaining:
        target_date += timedelta(days=1)
        if not hours.is_off_day(target_date):
            remaining -= 1
    candidate = datetime.combine(target_date, local.timetz().replace(tzinfo=None), hours.tz)
    return next_business_time(candidate.astimezone(UTC), hours)


def cadence_due_times(
    cadence_kind: str,
    basis: datetime,
    *,
    cadences: dict[str, tuple[tuple[str, int], ...]] | None = None,
    hours: BusinessHours = DEFAULT_HOURS,
) -> list[datetime]:
    cadence = (cadences if cadences is not None else CADENCES).get(cadence_kind)
    if not cadence:
        raise ValueError(f"cadência inválida: {cadence_kind}")
    base = _ensure_utc(basis)
    due: list[datetime] = []
    for mode, amount in cadence:
        if mode == "business_minutes":
            due.append(add_business_minutes(base, amount, hours))
        else:
            due.append(add_business_days(base, amount, hours))
    return due


def engine_options_from_profile(profile: dict | None) -> dict[str, Any]:
    """kwargs para `FollowupEngine(...)` a partir do `business_profile.json` do cliente.

    Perfil ausente ou sem `schedule`/`followup_cadences` cai nos padrões genéricos
    (`DEFAULT_HOURS`, `CADENCES`, `resume_per_tick=2`). Cadência inválida no profile é
    ignorada — aquele nome fica com a definição de `CADENCES`, o resto do dict some.
    `fixed_text_cadences` lista as cadências cujo texto é literal do profile (Fase 7 da
    Therapify): elas não passam pelo gate de contexto.
    """
    options: dict[str, Any] = {"hours": BusinessHours.from_profile(profile)}
    schedule = profile.get("schedule") if isinstance(profile, dict) else None
    if isinstance(schedule, dict):
        resume_per_tick = schedule.get("resume_per_tick")
        if (
            isinstance(resume_per_tick, int)
            and not isinstance(resume_per_tick, bool)
            and 1 <= resume_per_tick <= 20
        ):
            options["resume_per_tick"] = resume_per_tick
    cadences_raw = profile.get("followup_cadences") if isinstance(profile, dict) else None
    if isinstance(cadences_raw, dict):
        overrides: dict[str, tuple[tuple[str, int], ...]] = {}
        for name, steps in cadences_raw.items():
            if not isinstance(name, str) or not isinstance(steps, list) or not steps:
                continue
            parsed: list[tuple[str, int]] = []
            for step in steps:
                if not (isinstance(step, list) and len(step) == 2):
                    parsed = []
                    break
                mode, amount = step
                if mode not in ("business_minutes", "business_days"):
                    parsed = []
                    break
                if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                    parsed = []
                    break
                parsed.append((mode, amount))
            if parsed:
                overrides[name] = tuple(parsed)
        if overrides:
            merged = dict(CADENCES)
            merged.update(overrides)
            options["cadences"] = merged
    fixed_raw = profile.get("fixed_text_cadences") if isinstance(profile, dict) else None
    if isinstance(fixed_raw, list):
        fixed = frozenset(
            name.strip() for name in fixed_raw if isinstance(name, str) and name.strip()
        )
        if fixed:
            options["fixed_text_cadences"] = fixed
    return options


def validate_context(
    kind: str | None,
    fact: str | None,
    source_message_id: str | None = None,
    verified: bool = False,
) -> tuple[str, str, str]:
    clean_kind = (kind or "").strip().lower()
    clean_fact = " ".join((fact or "").strip().split())
    clean_source = (source_message_id or "").strip()
    if not verified:
        raise ContextGateError("contexto não foi verificado")
    if not clean_source:
        raise ContextGateError("context_source_message_id obrigatório")
    if clean_kind not in CONTEXT_KINDS:
        raise ContextGateError("context_kind ausente ou inválido")
    if len(clean_fact) < 4 or len(clean_fact) > 180:
        raise ContextGateError("context_fact precisa ter entre 4 e 180 caracteres")
    if _SECRET_RE.search(clean_fact):
        raise ContextGateError("context_fact parece conter segredo ou dado sensível")
    return clean_kind, clean_fact, clean_source


def sanitize_followup_fact(text: str) -> str:
    """Recorta a fala do lead para caber no follow. Sem credencial, sem ping vazio."""
    clean = " ".join(str(text or "").split())
    clean = _LONG_DIGITS_RE.sub("[DIGITS]", clean)
    clean = _EMAIL_RE.sub("[EMAIL]", clean)
    if _SECRET_RE.search(clean):
        return ""
    if len(clean) < 4:
        return ""
    if len(clean) > 180:
        clipped = clean[:177].rsplit(" ", 1)[0].rstrip(".,;:")
        clean = (clipped or clean[:177]).rstrip() + "…"
    return clean


def followup_policy(
    *,
    asked_price: bool,
    wants_call: bool,
    wants_pay: bool,
    wants_human: bool,
) -> dict[str, Any]:
    """Estágio/cadência a partir do turno — sem LLM. Takeover cancela automação."""
    if wants_human:
        return {"takeover": True}
    if wants_pay:
        return {
            "takeover": False,
            "stage": "payment",
            "cadence_kind": "payment",
            "context_kind": "payment",
        }
    if wants_call:
        return {
            "takeover": False,
            "stage": "proposal",
            "cadence_kind": "proposal",
            "context_kind": "next_step",
        }
    if asked_price:
        return {
            "takeover": False,
            "stage": "pricing",
            "cadence_kind": "proposal",
            "context_kind": "question",
        }
    return {
        "takeover": False,
        "stage": "qualification",
        "cadence_kind": "silence",
        "context_kind": "business",
    }


def _stage_from_kind(kind: str) -> str:
    return {
        "question": "pricing",
        "next_step": "proposal",
        "proposal": "proposal",
        "payment": "payment",
        "pain": "qualification",
        "business": "qualification",
        "objection": "pricing",
    }.get(kind, "qualification")


def _short_followup_topic(value: str) -> str:
    """Primeiro assunto verificável, sem repetir a fala inteira do lead."""
    topic = re.split(
        r"[,.;!?]|\s+(?:mas|porque)\s+|\s+e\s+(?=(?:eu\s+)?(?:recebo|tenho|"
        r"preciso|quero|gostaria|estou)\b)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" \"'.,;:!?—-")
    if len(topic) > 96:
        topic = topic[:96].rsplit(" ", 1)[0].rstrip(".,;:")
    return topic


def _business_followup_recap(fact: str) -> tuple[str, str]:
    """Converte a fala bruta em intenção ou tópico para uma retomada coloquial."""
    clean = _FOLLOWUP_GREETING_RE.sub("", str(fact or "").strip())
    clean = clean.strip(" \"'.,;:!?—-")

    intent = _FOLLOWUP_INTENT_RE.match(clean)
    if intent:
        subject = _short_followup_topic(intent.group("subject"))
        if subject:
            return "intent", subject

    possession = _FOLLOWUP_POSSESSION_RE.match(clean)
    if possession:
        topic = _short_followup_topic(possession.group("topic"))
        if topic:
            prefix = "sua" if possession.group("article").lower() == "uma" else "seu"
            return "topic", f"{prefix} {topic}"

    possessive = re.match(r"^(?P<owner>minha|meu)\s+(?P<topic>.+)$", clean, re.IGNORECASE)
    if possessive:
        topic = _short_followup_topic(possessive.group("topic"))
        if topic:
            prefix = "sua" if possessive.group("owner").lower() == "minha" else "seu"
            return "topic", f"{prefix} {topic}"

    return "topic", _short_followup_topic(clean)


def _render_business_followup(fact: str, step: int) -> str:
    mode, subject = _business_followup_recap(fact)
    if mode == "intent":
        if step == 1:
            return (
                f"Opa! Você queria {subject}, né? Então, antes de tudo, "
                "me diz o que mais trava no atendimento hoje."
            )
        if step == 2:
            return f"Retomando o que você queria: {subject}. Faz sentido olhar isso numa call curta?"
        return f"Último toque sobre {subject}. Se não for o momento, é só falar."

    if subject.lower().startswith("sua "):
        talking_about = f"da {subject}"
    elif subject.lower().startswith("seu "):
        talking_about = f"do {subject}"
    else:
        talking_about = f"sobre {subject}"
    if step == 1:
        return (
            f"Opa! A gente estava falando {talking_about}, né? Antes de tudo, "
            "me diz o que mais trava no atendimento hoje."
        )
    if step == 2:
        return f"Retomando o assunto {talking_about}. Faz sentido olhar isso numa call curta?"
    return f"Último toque sobre {subject}. Se não for o momento, é só falar."


def render_contextual_message(job: dict[str, Any]) -> str:
    """Copy determinística; nunca gera promessa, desconto ou dado não verificado."""
    kind, fact, _source = validate_context(
        job.get("context_kind"),
        job.get("context_fact"),
        job.get("context_source_message_id"),
        bool(job.get("context_verified")),
    )
    step = max(1, min(int(job.get("step_no") or 1), 3))
    stage = str(job.get("stage") or "").strip().lower() or _stage_from_kind(kind)
    fact = fact.rstrip(" .!?;:")
    if stage == "qualification" and kind == "business":
        return _render_business_followup(fact, step)
    template = _FOLLOWUP_COPY.get((stage, kind, step))
    if not template:
        template = "{fact} — se ainda estiver na pauta, me diz por onde retomar."
    return template.format(fact=fact)


def mask_chat_tail(chat_id: str) -> str:
    """Só os 4 últimos dígitos — a outbox local pode ter o JID, o Notion não."""
    digits = "".join(c for c in str(chat_id or "") if c.isdigit())
    if len(digits) < 4:
        return "…????"
    return "…" + digits[-4:]


def notion_lead_payload(
    snapshot: dict[str, Any],
    database_id: str,
    *,
    api_version: str = "2022-06-28",
) -> dict | None:
    """Página mínima na base de leads. Sem telefone inteiro, sem fato da conversa.

    Propriedades travadas (select inexistente derruba a página inteira):
    título `Lead`; rich_text `Resumo`. Estágio/cadência vão no resumo, não em
    select — a base de tickets já ensinou que opção inventada some o card.
    """
    alvo = str(database_id or "").strip()
    if not alvo or not isinstance(snapshot, dict):
        return None
    stage = str(snapshot.get("stage") or "new").strip().lower()
    if stage not in NOTION_LEAD_STAGES:
        stage = "qualification"
    cadence = str(snapshot.get("cadence_kind") or "").strip().lower()
    if cadence and cadence not in NOTION_LEAD_CADENCES:
        cadence = ""
    tail = mask_chat_tail(str(snapshot.get("chat_id") or ""))
    titulo = f"{tail} · {stage}"[:_NOTION_TEXT_CAP]
    resumo = (
        f"estágio={stage}"
        + (f" cadência={cadence}" if cadence else "")
        + f" próximo={snapshot.get('next_followup_utc') or '—'}"
        + f" ação={snapshot.get('next_action') or '—'}"
        + f" chat={tail}"
    )[:_NOTION_TEXT_CAP]
    pai = (
        {"data_source_id": alvo}
        if str(api_version) >= "2025-09-03"
        else {"database_id": alvo}
    )
    return {
        "parent": pai,
        "properties": {
            "Lead": {"title": [{"type": "text", "text": {"content": titulo}}]},
            "Resumo": {"rich_text": [{"type": "text", "text": {"content": resumo}}]},
        },
    }


class FollowupEngine:
    def __init__(
        self,
        db_path: str | Path,
        *,
        hours: BusinessHours = DEFAULT_HOURS,
        cadences: dict[str, tuple[tuple[str, int], ...]] | None = None,
        resume_per_tick: int = 2,
        fixed_text_cadences: frozenset[str] = frozenset(),
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.hours = hours
        self.cadences = cadences if cadences is not None else CADENCES
        self.resume_per_tick = resume_per_tick
        self.fixed_text_cadences = frozenset(fixed_text_cadences)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        return con

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _init_schema(self) -> None:
        con = self._connect()
        try:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS lead_state (
                    chat_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL DEFAULT 0,
                    lead_version INTEGER NOT NULL DEFAULT 0,
                    automation_enabled INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT 'new',
                    estimated_value_cents INTEGER,
                    cadence_kind TEXT,
                    context_kind TEXT,
                    context_fact TEXT,
                    context_source_message_id TEXT,
                    context_verified INTEGER NOT NULL DEFAULT 0,
                    takeover INTEGER NOT NULL DEFAULT 0,
                    opt_out INTEGER NOT NULL DEFAULT 0,
                    terminal INTEGER NOT NULL DEFAULT 0,
                    pause_reason TEXT,
                    last_inbound_id TEXT,
                    last_inbound_utc TEXT,
                    last_outbound_id TEXT,
                    last_outbound_utc TEXT,
                    updated_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS followup_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL REFERENCES lead_state(chat_id) ON DELETE CASCADE,
                    generation INTEGER NOT NULL,
                    cadence_kind TEXT NOT NULL,
                    step_no INTEGER NOT NULL,
                    due_utc TEXT NOT NULL,
                    basis_outbound_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_until_utc TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    bridge_message_id TEXT,
                    context_kind TEXT,
                    context_fact TEXT,
                    context_source_message_id TEXT,
                    context_verified INTEGER NOT NULL DEFAULT 0,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    UNIQUE(chat_id, generation, cadence_kind, step_no)
                );
                CREATE INDEX IF NOT EXISTS idx_followup_due
                    ON followup_jobs(status, due_utc);
                CREATE TABLE IF NOT EXISTS crm_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    lead_version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_utc TEXT,
                    last_error TEXT,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    UNIQUE(chat_id, lead_version)
                );
                """
            )
            migrations = {
                "lead_state": {
                    "context_source_message_id": "TEXT",
                    "context_verified": "INTEGER NOT NULL DEFAULT 0",
                    "pause_reason": "TEXT",
                    "estimated_value_cents": "INTEGER",
                },
                "followup_jobs": {
                    "lease_token": "TEXT",
                    "context_kind": "TEXT",
                    "context_fact": "TEXT",
                    "context_source_message_id": "TEXT",
                    "context_verified": "INTEGER NOT NULL DEFAULT 0",
                    "off_days_ok": "INTEGER NOT NULL DEFAULT 0",
                },
            }
            for table, columns in migrations.items():
                existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
                for column, definition in columns.items():
                    if column not in existing:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        finally:
            con.close()

    @staticmethod
    def _ensure_lead(con: sqlite3.Connection, chat_id: str, now: datetime) -> None:
        con.execute(
            "INSERT OR IGNORE INTO lead_state(chat_id, updated_utc) VALUES (?, ?)",
            (chat_id, _iso(now)),
        )

    @staticmethod
    def _cancel_open(
        con: sqlite3.Connection, chat_id: str, now: datetime, reason: str, *, exclude_cadence: str | None = None
    ) -> int:
        query = """
            UPDATE followup_jobs
               SET status='cancelled', last_error=?, lease_owner=NULL,
                   lease_until_utc=NULL, updated_utc=?
             WHERE chat_id=? AND status IN ('pending', 'leased')
        """
        params: list[Any] = [reason, _iso(now), chat_id]
        if exclude_cadence:
            query += " AND cadence_kind<>?"
            params.append(exclude_cadence)
        cur = con.execute(query, params)
        return int(cur.rowcount)

    def configure_lead(
        self,
        chat_id: str,
        *,
        automation_enabled: bool | None = None,
        stage: str | None = None,
        cadence_kind: str | None = None,
        context_kind: str | None = None,
        context_fact: str | None = None,
        context_source_message_id: str | None = None,
        context_verified: bool | None = None,
        takeover: bool | None = None,
        opt_out: bool | None = None,
        terminal: bool | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _ensure_utc(now)
        clean_id = chat_id.strip()
        if not clean_id:
            raise ValueError("chat_id obrigatório")
        if cadence_kind is not None and cadence_kind not in self.cadences:
            raise ValueError(f"cadência inválida: {cadence_kind}")
        if any(value is not None for value in (
            context_kind, context_fact, context_source_message_id, context_verified,
        )):
            context_kind, context_fact, context_source_message_id = validate_context(
                context_kind,
                context_fact,
                context_source_message_id,
                bool(context_verified),
            )
        fields: dict[str, Any] = {}
        if automation_enabled is not None:
            fields["automation_enabled"] = int(bool(automation_enabled))
        if stage is not None:
            fields["stage"] = stage.strip().lower()
            if fields["stage"] in TERMINAL_STAGES:
                fields["terminal"] = 1
        if cadence_kind is not None:
            fields["cadence_kind"] = cadence_kind
        if context_kind is not None:
            fields["context_kind"] = context_kind
            fields["context_fact"] = context_fact
            fields["context_source_message_id"] = context_source_message_id
            fields["context_verified"] = 1
        if takeover is not None:
            fields["takeover"] = int(bool(takeover))
        if opt_out is not None:
            fields["opt_out"] = int(bool(opt_out))
        if terminal is not None:
            fields["terminal"] = int(bool(terminal))
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            if fields:
                self._cancel_open(con, clean_id, current, "policy_or_context_changed")
                assignments = [f"{name}=?" for name in fields]
                values = list(fields.values())
                assignments.extend(["lead_version=lead_version+1", "updated_utc=?"])
                values.extend([_iso(current), clean_id])
                con.execute(f"UPDATE lead_state SET {', '.join(assignments)} WHERE chat_id=?", values)
            row = dict(con.execute("SELECT * FROM lead_state WHERE chat_id=?", (clean_id,)).fetchone())
            if not self._row_eligible(row):
                self._cancel_open(con, clean_id, current, "lead_not_eligible")
            return row

    def set_estimated_value(
        self,
        chat_id: str,
        amount_cents: int | None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _ensure_utc(now)
        clean_id = chat_id.strip()
        if not clean_id:
            raise ValueError("chat_id obrigatório")
        if isinstance(amount_cents, bool) or (
            amount_cents is not None and (
                not isinstance(amount_cents, int) or amount_cents < 0 or amount_cents > MAX_ESTIMATED_VALUE_CENTS
            )
        ):
            raise ValueError("valor estimado inválido")
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            con.execute(
                "UPDATE lead_state SET estimated_value_cents=?, "
                "lead_version=lead_version+1, updated_utc=? WHERE chat_id=?",
                (amount_cents, _iso(current), clean_id),
            )
            return dict(con.execute("SELECT * FROM lead_state WHERE chat_id=?", (clean_id,)).fetchone())

    @staticmethod
    def _row_eligible(row: dict[str, Any] | sqlite3.Row) -> bool:
        stage = str(row["stage"] or "").lower()
        return bool(row["automation_enabled"]) and not any(
            (bool(row["takeover"]), bool(row["opt_out"]), bool(row["terminal"]), stage in TERMINAL_STAGES)
        )

    def _fixed_text(self, cadence_kind: Any) -> bool:
        """Cadência de texto literal do profile (Fase 7 da Therapify). O gate de
        contexto existe para o follow genérico, que cita um fato do lead; aqui o texto
        já está escrito e não passa pelo modelo, então não há fato a verificar."""
        return str(cadence_kind or "") in self.fixed_text_cadences

    def _job_sendable_now(self, row: dict[str, Any], current: datetime) -> tuple[bool, datetime]:
        """(pode sair agora?, quando abre de novo). Só `resume` com `off_days_ok`
        pode sair em fim de semana/feriado; todo o resto segue o horário comercial."""
        skip_off_days = not (row["cadence_kind"] == "resume" and bool(row.get("off_days_ok")))
        opens = next_window_open(current, self.hours, skip_off_days=skip_off_days)
        return opens == _ensure_utc(current), opens

    @staticmethod
    def _resume_eligible(row: dict[str, Any] | sqlite3.Row) -> bool:
        """Job `resume` roda o pipeline de resposta, não a automação comercial: não
        depende de `automation_enabled`, `terminal` nem stage — só takeover/opt_out
        cancelam."""
        return not bool(row["takeover"]) and not bool(row["opt_out"])

    def note_inbound(
        self,
        chat_id: str,
        *,
        message_id: str | None = None,
        at: datetime | None = None,
    ) -> int:
        current = _ensure_utc(at)
        clean_id = chat_id.strip()
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            row = con.execute("SELECT last_inbound_id FROM lead_state WHERE chat_id=?", (clean_id,)).fetchone()
            if message_id and row and row["last_inbound_id"] == message_id:
                return 0
            con.execute(
                """
                UPDATE lead_state
                   SET generation=generation+1, lead_version=lead_version+1,
                       last_inbound_id=?, last_inbound_utc=?, updated_utc=?
                 WHERE chat_id=?
                """,
                (message_id, _iso(current), _iso(current), clean_id),
            )
            # mensagem nova à noite não cancela a retomada da manhã (ADR 0001)
            return self._cancel_open(con, clean_id, current, "lead_replied", exclude_cadence="resume")

    def note_human_takeover(self, chat_id: str, *, at: datetime | None = None) -> int:
        current = _ensure_utc(at)
        clean_id = chat_id.strip()
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            con.execute(
                """
                UPDATE lead_state
                   SET generation=generation+1, lead_version=lead_version+1,
                       takeover=1, updated_utc=?
                 WHERE chat_id=?
                """,
                (_iso(current), clean_id),
            )
            return self._cancel_open(con, clean_id, current, "human_takeover")

    def schedule_resume(
        self,
        chat_id: str,
        *,
        due: datetime,
        reason: str,
        at: datetime | None = None,
        off_days_ok: bool = False,
        extend_cap_s: int | None = None,
    ) -> int | None:
        """Agenda a retomada do pipeline de resposta às `due` (ADR 0001): Lead Novo,
        fila da manhã, debounce de sintomas. Não é uma cadência de texto — não passa
        por `self.cadences` nem pelo gate de contexto, e uma mensagem nova do lead não
        a cancela (`note_inbound`). Recusa só quando o lead está em takeover ou opt-out.

        Um resume aberto por chat, não por generation: se já existe um job `pending`
        ou `leased`, uma nova chamada não insere outro. `extend_cap_s` é o caso do
        debounce de sintomas (trailing) — em vez de recusar, empurra o vencimento do
        job `pending` existente para `min(due, created_utc + extend_cap_s)`, sem
        nunca passar do teto contado a partir da criação original. Um job `leased`
        (já sendo processado) não é alterado; a chamada retorna `None`.

        `off_days_ok=True` é a retomada que pode sair em fim de semana ou feriado dentro
        da janela (a Fase 1 de um Lead Novo); as demais só saem em dia útil."""
        current = _ensure_utc(at)
        due_utc = _ensure_utc(due)
        clean_id = chat_id.strip()
        if not clean_id:
            raise ValueError("chat_id obrigatório")
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise ValueError("reason obrigatório")
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            lead = con.execute(
                "SELECT generation, takeover, opt_out FROM lead_state WHERE chat_id=?", (clean_id,)
            ).fetchone()
            if bool(lead["takeover"]) or bool(lead["opt_out"]):
                return None
            open_job = con.execute(
                """
                SELECT id, status, created_utc FROM followup_jobs
                 WHERE chat_id=? AND cadence_kind='resume' AND status IN ('pending', 'leased')
                 ORDER BY id DESC LIMIT 1
                """,
                (clean_id,),
            ).fetchone()
            if open_job:
                if extend_cap_s is None or open_job["status"] != "pending":
                    return None
                created = datetime.fromisoformat(open_job["created_utc"])
                capped_due = min(due_utc, created + timedelta(seconds=extend_cap_s))
                con.execute(
                    "UPDATE followup_jobs SET due_utc=?, updated_utc=? WHERE id=?",
                    (_iso(capped_due), _iso(current), open_job["id"]),
                )
                return int(open_job["id"])
            cur = con.execute(
                """
                INSERT OR IGNORE INTO followup_jobs(
                    chat_id, generation, cadence_kind, step_no, due_utc, basis_outbound_id,
                    status, context_verified, off_days_ok, created_utc, updated_utc
                ) VALUES (?, ?, 'resume', 1, ?, ?, 'pending', 1, ?, ?, ?)
                """,
                (
                    clean_id, lead["generation"], _iso(due_utc), f"resume:{clean_reason}",
                    int(bool(off_days_ok)), _iso(current), _iso(current),
                ),
            )
            if cur.rowcount and cur.lastrowid is not None:
                return int(cur.lastrowid)
            return None

    def note_outbound(
        self,
        chat_id: str,
        *,
        message_id: str,
        at: datetime | None = None,
        cadence_kind: str | None = None,
        context_kind: str | None = None,
        context_fact: str | None = None,
        context_source_message_id: str | None = None,
        context_verified: bool | None = None,
    ) -> list[int]:
        current = _ensure_utc(at)
        clean_id = chat_id.strip()
        if not message_id:
            raise ValueError("message_id real da bridge é obrigatório")
        if any(value is not None for value in (
            context_kind, context_fact, context_source_message_id, context_verified,
        )):
            context_kind, context_fact, context_source_message_id = validate_context(
                context_kind, context_fact, context_source_message_id, bool(context_verified)
            )
        with self._tx() as con:
            self._ensure_lead(con, clean_id, current)
            previous = con.execute("SELECT * FROM lead_state WHERE chat_id=?", (clean_id,)).fetchone()
            if previous["last_outbound_id"] == message_id:
                return []
            selected_cadence = cadence_kind or previous["cadence_kind"]
            if selected_cadence is not None and selected_cadence not in self.cadences:
                raise ValueError(f"cadência inválida: {selected_cadence}")
            updates = [
                "generation=generation+1", "lead_version=lead_version+1",
                "last_outbound_id=?", "last_outbound_utc=?", "updated_utc=?",
            ]
            values: list[Any] = [message_id, _iso(current), _iso(current)]
            if selected_cadence is not None:
                updates.append("cadence_kind=?")
                values.append(selected_cadence)
            if context_kind is not None:
                updates.extend([
                    "context_kind=?", "context_fact=?",
                    "context_source_message_id=?", "context_verified=1",
                ])
                values.extend([context_kind, context_fact, context_source_message_id])
            values.append(clean_id)
            con.execute(f"UPDATE lead_state SET {', '.join(updates)} WHERE chat_id=?", values)
            self._cancel_open(con, clean_id, current, "new_outbound")
            state = dict(con.execute("SELECT * FROM lead_state WHERE chat_id=?", (clean_id,)).fetchone())
            if not self._row_eligible(state) or not selected_cadence:
                return []
            if not self._fixed_text(selected_cadence):
                try:
                    validate_context(
                        state.get("context_kind"), state.get("context_fact"),
                        state.get("context_source_message_id"), bool(state.get("context_verified")),
                    )
                except ContextGateError:
                    return []
            ids: list[int] = []
            due_times = cadence_due_times(selected_cadence, current, cadences=self.cadences, hours=self.hours)
            for step, due in enumerate(due_times, start=1):
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO followup_jobs(
                        chat_id, generation, cadence_kind, step_no, due_utc,
                        basis_outbound_id, status, context_kind, context_fact,
                        context_source_message_id, context_verified, created_utc, updated_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id, state["generation"], selected_cadence, step, _iso(due),
                        message_id, state["context_kind"], state["context_fact"],
                        state["context_source_message_id"], int(bool(state["context_verified"])),
                        _iso(current), _iso(current),
                    ),
                )
                if cur.rowcount and cur.lastrowid is not None:
                    ids.append(int(cur.lastrowid))
            if ids:
                payload = {
                    "chat_id": clean_id,
                    "stage": str(state.get("stage") or ""),
                    "cadence_kind": selected_cadence,
                    "automation_enabled": bool(state.get("automation_enabled")),
                    "next_action": "followup_step_1",
                    "next_followup_utc": _iso(due_times[0]) if due_times else "",
                    "attempt_count": 0,
                    "followup_status": "pending",
                }
                con.execute(
                    """
                    INSERT OR IGNORE INTO crm_outbox(
                        chat_id, lead_version, payload_json, status, created_utc, updated_utc
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        clean_id,
                        int(state["lead_version"]),
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        _iso(current),
                        _iso(current),
                    ),
                )
            return ids

    def claim_due(
        self,
        *,
        now: datetime | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 90,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        current = _ensure_utc(now)
        worker = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        lease_until = current + timedelta(seconds=max(15, lease_seconds))
        claimed: list[dict[str, Any]] = []
        with self._tx() as con:
            expired = con.execute(
                """
                SELECT id, chat_id, generation, cadence_kind, step_no
                  FROM followup_jobs
                 WHERE status='leased' AND lease_until_utc < ?
                """,
                (_iso(current),),
            ).fetchall()
            for stale in expired:
                con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='uncertain', lease_owner=NULL, lease_token=NULL,
                           lease_until_utc=NULL, last_error='lease_expired_ambiguous', updated_utc=?
                     WHERE id=? AND status='leased'
                    """,
                    (_iso(current), stale["id"]),
                )
                con.execute(
                    """
                    UPDATE lead_state
                       SET automation_enabled=0, pause_reason='lease_expired_ambiguous',
                           lead_version=lead_version+1, updated_utc=?
                     WHERE chat_id=?
                    """,
                    (_iso(current), stale["chat_id"]),
                )
                con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='cancelled', last_error='prior_lease_expired', updated_utc=?
                     WHERE chat_id=? AND generation=? AND cadence_kind=?
                       AND step_no>? AND status IN ('pending', 'leased')
                    """,
                    (
                        _iso(current), stale["chat_id"], stale["generation"],
                        stale["cadence_kind"], stale["step_no"],
                    ),
                )
            resume_rows = con.execute(
                """
                SELECT j.*, s.automation_enabled, s.stage, s.context_kind,
                       s.context_fact, s.takeover, s.opt_out, s.terminal,
                       s.generation AS live_generation
                  FROM followup_jobs j
                  JOIN lead_state s ON s.chat_id=j.chat_id
                 WHERE j.status='pending' AND j.due_utc <= ? AND j.cadence_kind='resume'
                 ORDER BY j.due_utc, j.id
                 LIMIT ?
                """,
                (_iso(current), max(1, self.resume_per_tick)),
            ).fetchall()
            general_rows = con.execute(
                """
                SELECT j.*, s.automation_enabled, s.stage, s.context_kind,
                       s.context_fact, s.takeover, s.opt_out, s.terminal,
                       s.generation AS live_generation
                  FROM followup_jobs j
                  JOIN lead_state s ON s.chat_id=j.chat_id
                 WHERE j.status='pending' AND j.due_utc <= ? AND j.cadence_kind<>'resume'
                   AND NOT EXISTS (
                       SELECT 1 FROM followup_jobs earlier
                        WHERE earlier.chat_id=j.chat_id
                          AND earlier.generation=j.generation
                          AND earlier.cadence_kind=j.cadence_kind
                          AND earlier.step_no < j.step_no
                          AND earlier.status NOT IN ('sent', 'skipped')
                   )
                 ORDER BY j.due_utc, j.id
                 LIMIT ?
                """,
                (_iso(current), max(1, limit)),
            ).fetchall()
            for raw in (*resume_rows, *general_rows):
                row = dict(raw)
                is_resume = row["cadence_kind"] == "resume"
                # resume não cancela por troca de generation (mensagem nova à noite não
                # deve matar a retomada da manhã) nem passa pelo gate de contexto — é
                # pipeline de resposta, não texto fixo citando um fato do lead.
                if is_resume:
                    eligible = self._resume_eligible(row)
                else:
                    eligible = row["generation"] == row["live_generation"] and self._row_eligible(row)
                if not eligible:
                    con.execute(
                        "UPDATE followup_jobs SET status='cancelled', last_error='stale_or_ineligible', updated_utc=? WHERE id=?",
                        (_iso(current), row["id"]),
                    )
                    continue
                if not is_resume and not self._fixed_text(row["cadence_kind"]):
                    try:
                        validate_context(
                            row.get("context_kind"), row.get("context_fact"),
                            row.get("context_source_message_id"), bool(row.get("context_verified")),
                        )
                    except ContextGateError as exc:
                        con.execute(
                            "UPDATE followup_jobs SET status='manual_review', last_error=?, updated_utc=? WHERE id=?",
                            (str(exc), _iso(current), row["id"]),
                        )
                        continue
                sendable, opens = self._job_sendable_now(row, current)
                if not sendable:
                    con.execute(
                        "UPDATE followup_jobs SET due_utc=?, updated_utc=? WHERE id=?",
                        (_iso(opens), _iso(current), row["id"]),
                    )
                    continue
                lease_token = uuid.uuid4().hex
                updated = con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='leased', lease_owner=?, lease_token=?, lease_until_utc=?,
                           attempts=attempts+1, updated_utc=?
                     WHERE id=? AND status='pending'
                    """,
                    (worker, lease_token, _iso(lease_until), _iso(current), row["id"]),
                )
                if updated.rowcount:
                    row.update(
                        status="leased", lease_owner=worker, lease_token=lease_token,
                        lease_until_utc=_iso(lease_until),
                    )
                    claimed.append(row)
        return claimed

    def revalidate_claim(
        self, job_id: int, lease_token: str, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        current = _ensure_utc(now)
        with self._tx() as con:
            raw = con.execute(
                """
                SELECT j.*, s.automation_enabled, s.stage, s.context_kind,
                       s.context_fact, s.takeover, s.opt_out, s.terminal,
                       s.generation AS live_generation
                  FROM followup_jobs j JOIN lead_state s ON s.chat_id=j.chat_id
                 WHERE j.id=? AND j.lease_token=?
                """,
                (job_id, lease_token),
            ).fetchone()
            if not raw or raw["status"] != "leased":
                return None
            row = dict(raw)
            is_resume = row["cadence_kind"] == "resume"
            eligible = (
                self._resume_eligible(row)
                if is_resume
                else row["generation"] == row["live_generation"] and self._row_eligible(row)
            )
            if not eligible:
                con.execute(
                    "UPDATE followup_jobs SET status='cancelled', last_error='revalidation_failed', updated_utc=? WHERE id=?",
                    (_iso(current), job_id),
                )
                return None
            if not is_resume and not self._fixed_text(row["cadence_kind"]):
                try:
                    validate_context(
                        row.get("context_kind"), row.get("context_fact"),
                        row.get("context_source_message_id"), bool(row.get("context_verified")),
                    )
                except ContextGateError as exc:
                    con.execute(
                        "UPDATE followup_jobs SET status='manual_review', last_error=?, updated_utc=? WHERE id=?",
                        (str(exc), _iso(current), job_id),
                    )
                    return None
            sendable, opens = self._job_sendable_now(row, current)
            if not sendable:
                con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='pending', due_utc=?, lease_owner=NULL,
                           lease_token=NULL, lease_until_utc=NULL, updated_utc=?
                     WHERE id=?
                    """,
                    (_iso(opens), _iso(current), job_id),
                )
                return None
            return row

    def mark_sent(
        self, job_id: int, bridge_message_id: str, lease_token: str, *, at: datetime | None = None
    ) -> None:
        if not bridge_message_id:
            raise ValueError("bridge_message_id obrigatório")
        current = _ensure_utc(at)
        with self._tx() as con:
            con.execute(
                """
                UPDATE followup_jobs
                   SET status='sent', bridge_message_id=?, lease_owner=NULL,
                       lease_token=NULL, lease_until_utc=NULL, last_error=NULL, updated_utc=?
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                (bridge_message_id, _iso(current), job_id, lease_token),
            )

    def mark_uncertain(
        self, job_id: int, error: str, lease_token: str, *, at: datetime | None = None
    ) -> None:
        current = _ensure_utc(at)
        with self._tx() as con:
            job = con.execute(
                """
                SELECT chat_id, generation, cadence_kind, step_no
                  FROM followup_jobs
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                (job_id, lease_token),
            ).fetchone()
            con.execute(
                """
                UPDATE followup_jobs
                   SET status='uncertain', last_error=?, lease_owner=NULL, lease_token=NULL,
                       lease_until_utc=NULL, updated_utc=?
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                (error[:500], _iso(current), job_id, lease_token),
            )
            if job:
                con.execute(
                    """
                    UPDATE lead_state
                       SET automation_enabled=0, pause_reason='delivery_uncertain',
                           lead_version=lead_version+1, updated_utc=?
                     WHERE chat_id=?
                    """,
                    (_iso(current), job["chat_id"]),
                )
                con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='cancelled', last_error='prior_send_uncertain', updated_utc=?
                     WHERE chat_id=? AND generation=? AND cadence_kind=?
                       AND step_no>? AND status IN ('pending', 'leased')
                    """,
                    (_iso(current), job["chat_id"], job["generation"], job["cadence_kind"], job["step_no"]),
                )

    def mark_failed(
        self, job_id: int, error: str, lease_token: str, *, at: datetime | None = None
    ) -> None:
        current = _ensure_utc(at)
        with self._tx() as con:
            job = con.execute(
                """
                SELECT chat_id, generation, cadence_kind, step_no
                  FROM followup_jobs
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                (job_id, lease_token),
            ).fetchone()
            con.execute(
                """
                UPDATE followup_jobs
                   SET status='failed', last_error=?, lease_owner=NULL, lease_token=NULL,
                       lease_until_utc=NULL, updated_utc=?
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                (error[:500], _iso(current), job_id, lease_token),
            )
            if job:
                con.execute(
                    """
                    UPDATE lead_state
                       SET automation_enabled=0, pause_reason='delivery_failed',
                           lead_version=lead_version+1, updated_utc=?
                     WHERE chat_id=?
                    """,
                    (_iso(current), job["chat_id"]),
                )
                con.execute(
                    """
                    UPDATE followup_jobs
                       SET status='cancelled', last_error='prior_send_failed', updated_utc=?
                     WHERE chat_id=? AND generation=? AND cadence_kind=?
                       AND step_no>? AND status IN ('pending', 'leased')
                    """,
                    (_iso(current), job["chat_id"], job["generation"], job["cadence_kind"], job["step_no"]),
                )

    def cancel_claimed(
        self, job_id: int, lease_token: str, reason: str, *, at: datetime | None = None
    ) -> bool:
        """Cancela um job `leased` sem marcar falha de entrega — o caso do replay de
        resume que não achou mensagem pendente do lead (o Rodrigo respondeu pelo
        celular). Ao contrário de `mark_failed`, não desliga `automation_enabled` do
        lead nem cancela outros jobs: não houve tentativa de envio, só a constatação
        de que não havia nada para reenviar. Retorna se algo mudou."""
        current = _ensure_utc(at)
        with self._tx() as con:
            cur = con.execute(
                """
                UPDATE followup_jobs
                   SET status='cancelled', last_error=?, lease_owner=NULL,
                       lease_token=NULL, lease_until_utc=NULL, updated_utc=?
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                ((reason or "")[:500], _iso(current), job_id, lease_token),
            )
            return bool(cur.rowcount)

    def skip_step(
        self, job_id: int, lease_token: str, reason: str, *, at: datetime | None = None
    ) -> bool:
        """Fecha um passo `leased` sem enviar nada, deixando a cadência seguir — o caso
        do D2 da Fase 7 para quem já recebeu a oferta do método gravado. Diferente de
        `cancel_claimed`, os passos seguintes continuam elegíveis: `claim_due` trata
        `skipped` como um passo resolvido, igual a `sent`."""
        current = _ensure_utc(at)
        with self._tx() as con:
            cur = con.execute(
                """
                UPDATE followup_jobs
                   SET status='skipped', last_error=?, lease_owner=NULL,
                       lease_token=NULL, lease_until_utc=NULL, updated_utc=?
                 WHERE id=? AND status='leased' AND lease_token=?
                """,
                ((reason or "")[:500], _iso(current), job_id, lease_token),
            )
            return bool(cur.rowcount)

    def enqueue_outbox(self, chat_id: str, lead_version: int, payload: dict[str, Any], *, at: datetime | None = None) -> bool:
        invalid = set(payload) - OUTBOX_WHITELIST
        if invalid:
            raise ValueError(f"campos não permitidos na outbox: {sorted(invalid)}")
        current = _ensure_utc(at)
        with self._tx() as con:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO crm_outbox(
                    chat_id, lead_version, payload_json, status, created_utc, updated_utc
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (chat_id, int(lead_version), json.dumps(payload, ensure_ascii=False, sort_keys=True), _iso(current), _iso(current)),
            )
            return bool(cur.rowcount)

    def claim_outbox(self, *, limit: int = 10, at: datetime | None = None) -> list[dict[str, Any]]:
        current = _ensure_utc(at)
        cap = max(1, min(int(limit), 50))
        with self._tx() as con:
            rows = con.execute(
                """
                SELECT * FROM crm_outbox
                 WHERE status='pending'
                   AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?)
                 ORDER BY id
                 LIMIT ?
                """,
                (_iso(current), cap),
            ).fetchall()
            claimed = [dict(row) for row in rows]
            if claimed:
                placeholders = ",".join("?" for _ in claimed)
                con.execute(
                    f"""
                    UPDATE crm_outbox
                       SET status='leased', attempts=attempts+1, updated_utc=?
                     WHERE id IN ({placeholders}) AND status='pending'
                    """,
                    [_iso(current), *(int(row["id"]) for row in claimed)],
                )
            return claimed

    def mark_outbox_sent(self, outbox_id: int, notion_url: str, *, at: datetime | None = None) -> None:
        current = _ensure_utc(at)
        with self._tx() as con:
            con.execute(
                """
                UPDATE crm_outbox
                   SET status='sent', last_error=?, updated_utc=?
                 WHERE id=? AND status='leased'
                """,
                (str(notion_url or "")[:500], _iso(current), int(outbox_id)),
            )

    def mark_outbox_failed(self, outbox_id: int, error: str, *, at: datetime | None = None) -> None:
        current = _ensure_utc(at)
        with self._tx() as con:
            con.execute(
                """
                UPDATE crm_outbox
                   SET status='pending', last_error=?, next_attempt_utc=?, updated_utc=?
                 WHERE id=? AND status='leased'
                """,
                (str(error or "")[:500], _iso(current + timedelta(minutes=15)), _iso(current), int(outbox_id)),
            )

    def get_lead(self, chat_id: str) -> dict[str, Any] | None:
        con = self._connect()
        try:
            row = con.execute("SELECT * FROM lead_state WHERE chat_id=?", (chat_id,)).fetchone()
            return dict(row) if row else None
        finally:
            con.close()

    def get_jobs(self, chat_id: str | None = None) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            if chat_id:
                rows = con.execute("SELECT * FROM followup_jobs WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
            else:
                rows = con.execute("SELECT * FROM followup_jobs ORDER BY id").fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()
