"""Gestão da carteira da instância: clientes, onboarding, tickets, pós-venda e
financeiro. Substitui a Central de Operações que vivia no Notion.

Módulo puro no molde de `reactivation_store.py`: funções que abrem conexão
curta no `management.db` e fecham. Não importa o plugin nem o painel. Regras
de forma (enum, centavos, datas) vivem aqui porque são integridade do banco;
regras de fluxo (quem pode ir de que status para qual) ficam em
`panel/actions.py`.

Dinheiro é inteiro em centavos. Datas civis são texto `YYYY-MM-DD`; competência
é `YYYY-MM`; carimbos são UTC ISO em colunas `*_utc`.
"""
from __future__ import annotations

import calendar
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator

CLIENT_STATUSES = (
    "negotiation", "awaiting_payment", "onboarding", "implementation", "qa",
    "active", "paused", "cancelled",
)
CLIENT_KINDS = ("atendimento", "reativacao", "teste")
TICKET_KINDS = ("incident", "question", "request", "improvement", "billing", "other")
TICKET_PRIORITIES = ("critical", "high", "medium", "low")
TICKET_ORIGINS = ("whatsapp", "internal", "email", "audit", "other")
TICKET_STATUSES = (
    "open", "triage", "in_progress", "waiting_client", "waiting_third_party",
    "resolved", "closed",
)
TICKET_DONE = ("resolved", "closed")
TOUCHPOINT_KINDS = ("kickoff", "checkin", "usage_review", "renewal", "churn_risk", "other")
HEALTH_LEVELS = ("healthy", "attention", "at_risk")
CHARGE_KINDS = ("monthly", "setup", "adhoc")
CHARGE_STATUSES = ("expected", "paid", "cancelled")
COST_CATEGORIES = ("vps", "ai", "domain", "tools", "other")
DEFAULT_BILLING_DAY = 10

DEFAULT_ONBOARDING_STEPS = (
    "Entrada recebida",
    "Pendências do cliente (envs, personas, catálogo)",
    "VPS e domínio provisionados",
    "Configuração e pareamento",
    "QA interno",
    "Validação do cliente",
    "Ajustes",
    "Pronto para ativar",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT UNIQUE,
  name TEXT NOT NULL,
  company TEXT,
  segment TEXT,
  phone TEXT,
  email TEXT,
  status TEXT NOT NULL,
  kind TEXT,
  monthly_cents INTEGER NOT NULL DEFAULT 0,
  setup_cents INTEGER NOT NULL DEFAULT 0,
  billing_day INTEGER,
  started_on TEXT,
  activated_on TEXT,
  churned_on TEXT,
  environment_url TEXT,
  notes TEXT,
  ssh_host TEXT,
  ssh_port INTEGER,
  ssh_user TEXT,
  ssh_password TEXT,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  note TEXT,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_client_events_client ON client_events(client_id, created_utc);
CREATE TABLE IF NOT EXISTS onboarding_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  title TEXT NOT NULL,
  done_utc TEXT,
  pending_note TEXT,
  updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_onboarding_client ON onboarding_steps(client_id, position);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  description TEXT,
  kind TEXT NOT NULL,
  priority TEXT NOT NULL,
  origin TEXT NOT NULL,
  status TEXT NOT NULL,
  due_on TEXT,
  resolution TEXT,
  opened_utc TEXT NOT NULL,
  resolved_utc TEXT,
  updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, updated_utc);
CREATE TABLE IF NOT EXISTS ticket_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  note TEXT,
  created_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket ON ticket_events(ticket_id, created_utc);
CREATE TABLE IF NOT EXISTS touchpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  scheduled_on TEXT,
  done_on TEXT,
  health TEXT,
  summary TEXT,
  next_action TEXT,
  next_contact_on TEXT,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_touchpoints_client ON touchpoints(client_id, done_on);
CREATE TABLE IF NOT EXISTS charges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  period TEXT NOT NULL,
  kind TEXT NOT NULL,
  due_on TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'expected',
  paid_on TEXT,
  paid_cents INTEGER,
  note TEXT,
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_charges_recurring
    ON charges(client_id, period, kind) WHERE kind IN ('monthly', 'setup');
CREATE INDEX IF NOT EXISTS idx_charges_period ON charges(period, status);
CREATE TABLE IF NOT EXISTS cost_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  monthly_cents INTEGER NOT NULL,
  label TEXT,
  active_from TEXT NOT NULL,
  active_to TEXT,
  updated_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
  plan_id INTEGER REFERENCES cost_plans(id) ON DELETE SET NULL,
  period TEXT NOT NULL,
  category TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  currency_original TEXT,
  amount_original REAL,
  label TEXT,
  note TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_utc TEXT NOT NULL,
  updated_utc TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_costs_plan_period
    ON costs(plan_id, period) WHERE plan_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_costs_period ON costs(period, client_id);
"""

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Colunas adicionadas depois do primeiro esquema: `CREATE TABLE IF NOT EXISTS`
# não altera tabela existente, então cada banco antigo recebe o ALTER aqui.
_MIGRATIONS = {
    "clients": {
        "ssh_host": "TEXT",
        "ssh_port": "INTEGER",
        "ssh_user": "TEXT",
        "ssh_password": "TEXT",
    },
}
SECRET_FIELDS = ("ssh_password",)


class ManagementError(ValueError):
    """Entrada inválida. Mensagem pronta para mostrar ao operador."""


# ── infraestrutura ──────────────────────────────────────────────────────────

def _ensure_utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("datetime precisa ter timezone")
    return value.astimezone(UTC)


def _iso(value: datetime | None = None) -> str:
    return _ensure_utc(value).isoformat(timespec="seconds")


def _connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # O banco guarda credencial de acesso às VPSs dos clientes: só o dono do
    # processo lê o arquivo, como o `.env`.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in _MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


@contextmanager
def _read(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        _apply_schema(conn)
        yield conn
    finally:
        conn.close()


@contextmanager
def _write(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        _apply_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def ensure_schema(conn_or_path: sqlite3.Connection | Path | str) -> None:
    if isinstance(conn_or_path, sqlite3.Connection):
        _apply_schema(conn_or_path)
        return
    conn = _connect(conn_or_path)
    try:
        _apply_schema(conn)
    finally:
        conn.close()


def _rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def _one(cursor) -> dict | None:
    row = cursor.fetchone()
    return dict(row) if row else None


def _public(row: dict | None) -> dict | None:
    """Tira a credencial da linha antes de ela sair do store. Quem precisa do
    valor chama `get_ssh_credentials`."""
    if not row:
        return row
    for field in SECRET_FIELDS:
        if field in row:
            row[f"{field}_set"] = bool(row.pop(field))
    return row


# ── validação de forma ──────────────────────────────────────────────────────

def _enum(value: Any, allowed: tuple, field: str, *, required: bool = True) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        if required:
            raise ManagementError(f"{field} é obrigatório.")
        return None
    if text not in allowed:
        raise ManagementError(f"{field} inválido: {text!r}.")
    return text


def _cents(value: Any, field: str, *, required: bool = True) -> int | None:
    if value is None or value == "":
        if required:
            raise ManagementError(f"{field} é obrigatório.")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManagementError(f"{field} precisa ser inteiro em centavos.")
    if value < 0:
        raise ManagementError(f"{field} não pode ser negativo.")
    return value


def _civil_date(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise ManagementError(f"{field} é obrigatório.")
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise ManagementError(f"{field} precisa ser uma data YYYY-MM-DD.") from None


def _period(value: Any) -> str:
    text = str(value or "").strip()
    if not _PERIOD_RE.match(text):
        raise ManagementError(f"Competência inválida: {text!r} (esperado YYYY-MM).")
    return text


def _text(value: Any, field: str, *, required: bool = False, cap: int = 4000) -> str | None:
    text = str(value if value is not None else "").strip()
    if not text:
        if required:
            raise ManagementError(f"{field} é obrigatório.")
        return None
    return text[:cap]


def _billing_day(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 28:
        raise ManagementError("Dia de vencimento precisa estar entre 1 e 28.")
    return value


def _port(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ManagementError("Porta SSH precisa estar entre 1 e 65535.")
    return value


def _canonical_chat_id(chat_id: Any) -> str | None:
    raw = str(chat_id or "").strip()
    if not raw:
        return None
    if raw.endswith("@lid"):
        raise ManagementError(f"chat_id LID não pode vincular cliente: {raw!r}")
    if "@" in raw:
        return raw
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        raise ManagementError(f"chat_id inválido: {raw!r}")
    return f"{digits}@s.whatsapp.net"


def _period_bounds(period: str) -> tuple[str, str]:
    year, month = int(period[:4]), int(period[5:7])
    last = calendar.monthrange(year, month)[1]
    return f"{period}-01", f"{period}-{last:02d}"


# ── clientes ────────────────────────────────────────────────────────────────

_CLIENT_FIELDS = {
    "name": lambda v: _text(v, "Nome", required=True, cap=200),
    "company": lambda v: _text(v, "Empresa", cap=200),
    "segment": lambda v: _text(v, "Segmento", cap=120),
    "phone": lambda v: ("".join(c for c in str(v or "") if c.isdigit()) or None),
    "email": lambda v: _text(v, "E-mail", cap=200),
    "kind": lambda v: _enum(v, CLIENT_KINDS, "Tipo", required=False),
    "monthly_cents": lambda v: _cents(v, "Mensalidade", required=False) or 0,
    "setup_cents": lambda v: _cents(v, "Implementação", required=False) or 0,
    "billing_day": _billing_day,
    "started_on": lambda v: _civil_date(v, "Início"),
    "activated_on": lambda v: _civil_date(v, "Ativação"),
    "churned_on": lambda v: _civil_date(v, "Encerramento"),
    "environment_url": lambda v: _text(v, "Link do ambiente", cap=500),
    "notes": lambda v: _text(v, "Observações"),
    "chat_id": _canonical_chat_id,
    "ssh_host": lambda v: _text(v, "Host SSH", cap=253),
    "ssh_port": _port,
    "ssh_user": lambda v: _text(v, "Usuário SSH", cap=64),
    "ssh_password": lambda v: _text(v, "Senha SSH", cap=256),
}


def _client_values(fields: dict, *, partial: bool) -> dict:
    unknown = set(fields) - set(_CLIENT_FIELDS)
    if unknown:
        raise ManagementError(f"Campo desconhecido: {', '.join(sorted(unknown))}.")
    values = {}
    for key, clean in _CLIENT_FIELDS.items():
        if partial and key not in fields:
            continue
        # Senha em branco no update é "não mexer": o formulário nunca a
        # reexibe, então vazio não pode significar apagar. Apagar é `None`.
        if partial and key in SECRET_FIELDS and fields.get(key) == "":
            continue
        values[key] = clean(fields.get(key))
    return values


def create_client(db_path: Path | str, *, status: str = "negotiation", now: datetime | None = None, **fields) -> dict:
    values = _client_values(fields, partial=False)
    status = _enum(status, CLIENT_STATUSES, "Status")
    stamp = _iso(now)
    with _write(db_path) as conn:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        try:
            cur = conn.execute(
                f"INSERT INTO clients ({cols}, status, created_utc, updated_utc) VALUES ({marks}, ?, ?, ?)",
                (*values.values(), status, stamp, stamp),
            )
        except sqlite3.IntegrityError:
            raise ManagementError("Já existe cliente vinculado a esse chat.") from None
        client_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO client_events (client_id, kind, to_status, created_utc) VALUES (?, 'status', ?, ?)",
            (client_id, status, stamp),
        )
        if status == "onboarding":
            _seed_onboarding(conn, client_id, stamp)
        return _client_row(conn, client_id)


def update_client(db_path: Path | str, client_id: int, *, now: datetime | None = None, **fields) -> dict:
    values = _client_values(fields, partial=True)
    if not values:
        raise ManagementError("Nada para atualizar.")
    with _write(db_path) as conn:
        _require_client(conn, client_id)
        sets = ", ".join(f"{k} = ?" for k in values)
        try:
            conn.execute(
                f"UPDATE clients SET {sets}, updated_utc = ? WHERE id = ?",
                (*values.values(), _iso(now), client_id),
            )
        except sqlite3.IntegrityError:
            raise ManagementError("Já existe cliente vinculado a esse chat.") from None
        return _client_row(conn, client_id)


def set_client_status(
    db_path: Path | str, client_id: int, status: str, *, note: str | None = None,
    now: datetime | None = None, today: date | None = None,
) -> dict:
    status = _enum(status, CLIENT_STATUSES, "Status")
    stamp = _iso(now)
    civil = (today or _ensure_utc(now).date()).isoformat()
    with _write(db_path) as conn:
        current = _require_client(conn, client_id)
        if current["status"] == status:
            raise ManagementError(f"Cliente já está em {status}.")
        sets = {"status": status}
        if status == "active" and not current["activated_on"]:
            sets["activated_on"] = civil
        if status == "cancelled" and not current["churned_on"]:
            sets["churned_on"] = civil
        if status in ("awaiting_payment", "onboarding") and not current["started_on"]:
            sets["started_on"] = civil
        conn.execute(
            f"UPDATE clients SET {', '.join(f'{k} = ?' for k in sets)}, updated_utc = ? WHERE id = ?",
            (*sets.values(), stamp, client_id),
        )
        conn.execute(
            "INSERT INTO client_events (client_id, kind, from_status, to_status, note, created_utc)"
            " VALUES (?, 'status', ?, ?, ?, ?)",
            (client_id, current["status"], status, _text(note, "Nota"), stamp),
        )
        if status == "onboarding":
            _seed_onboarding(conn, client_id, stamp)
        return _client_row(conn, client_id)


def add_client_note(db_path: Path | str, client_id: int, note: str, *, now: datetime | None = None) -> dict:
    text = _text(note, "Nota", required=True)
    stamp = _iso(now)
    with _write(db_path) as conn:
        _require_client(conn, client_id)
        cur = conn.execute(
            "INSERT INTO client_events (client_id, kind, note, created_utc) VALUES (?, 'note', ?, ?)",
            (client_id, text, stamp),
        )
        return _one(conn.execute("SELECT * FROM client_events WHERE id = ?", (cur.lastrowid,)))


def _require_client(conn: sqlite3.Connection, client_id: Any) -> dict:
    row = _one(conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)))
    if not row:
        raise ManagementError("Cliente não encontrado.")
    return row


def _client_row(conn: sqlite3.Connection, client_id: int) -> dict:
    row = _public(_one(conn.execute(_CLIENT_LIST_SQL + " WHERE c.id = ?", (client_id,))))
    assert row is not None
    return row


def get_ssh_credentials(db_path: Path | str, client_id: int) -> dict | None:
    """Único caminho que devolve a senha. Para o poller de saúde, não para a API."""
    with _read(db_path) as conn:
        row = _one(conn.execute(
            "SELECT id, name, ssh_host, ssh_port, ssh_user, ssh_password FROM clients WHERE id = ?", (client_id,)))
    if not row or not row["ssh_host"]:
        return None
    return row


_CLIENT_LIST_SQL = """
SELECT c.*,
  (SELECT COUNT(*) FROM tickets t WHERE t.client_id = c.id
     AND t.status NOT IN ('resolved', 'closed')) AS open_tickets,
  (SELECT COUNT(*) FROM onboarding_steps s WHERE s.client_id = c.id) AS onboarding_total,
  (SELECT COUNT(*) FROM onboarding_steps s WHERE s.client_id = c.id AND s.done_utc IS NOT NULL) AS onboarding_done,
  (SELECT s.title FROM onboarding_steps s WHERE s.client_id = c.id AND s.done_utc IS NULL
     ORDER BY s.position LIMIT 1) AS onboarding_pending,
  (SELECT s.pending_note FROM onboarding_steps s WHERE s.client_id = c.id AND s.done_utc IS NULL
     ORDER BY s.position LIMIT 1) AS onboarding_pending_note,
  (SELECT tp.health FROM touchpoints tp WHERE tp.client_id = c.id AND tp.done_on IS NOT NULL
     ORDER BY tp.done_on DESC, tp.id DESC LIMIT 1) AS health,
  (SELECT COUNT(*) FROM charges ch WHERE ch.client_id = c.id AND ch.status = 'expected') AS open_charges
FROM clients c
"""


def get_client(db_path: Path | str, client_id: int) -> dict | None:
    with _read(db_path) as conn:
        row = _public(_one(conn.execute(_CLIENT_LIST_SQL + " WHERE c.id = ?", (client_id,))))
        if not row:
            return None
        row["events"] = _rows(conn.execute(
            "SELECT * FROM client_events WHERE client_id = ? ORDER BY created_utc DESC, id DESC", (client_id,)))
        row["onboarding"] = _rows(conn.execute(
            "SELECT * FROM onboarding_steps WHERE client_id = ? ORDER BY position, id", (client_id,)))
        row["tickets"] = _rows(conn.execute(
            "SELECT * FROM tickets WHERE client_id = ? ORDER BY updated_utc DESC, id DESC", (client_id,)))
        row["touchpoints"] = _rows(conn.execute(
            "SELECT * FROM touchpoints WHERE client_id = ?"
            " ORDER BY COALESCE(done_on, scheduled_on) DESC, id DESC", (client_id,)))
        row["charges"] = _rows(conn.execute(
            "SELECT * FROM charges WHERE client_id = ? ORDER BY period DESC, due_on DESC, id DESC", (client_id,)))
        row["costs"] = _rows(conn.execute(
            "SELECT * FROM costs WHERE client_id = ? ORDER BY period DESC, category, id", (client_id,)))
        return row


def get_client_by_chat(db_path: Path | str, chat_id: str) -> dict | None:
    canonical = _canonical_chat_id(chat_id)
    if not canonical:
        return None
    with _read(db_path) as conn:
        return _public(_one(conn.execute(_CLIENT_LIST_SQL + " WHERE c.chat_id = ?", (canonical,))))


def list_clients(db_path: Path | str, *, status: str | None = None) -> list[dict]:
    status = _enum(status, CLIENT_STATUSES, "Status", required=False)
    with _read(db_path) as conn:
        if status:
            rows = _rows(conn.execute(_CLIENT_LIST_SQL + " WHERE c.status = ? ORDER BY c.name", (status,)))
        else:
            rows = _rows(conn.execute(_CLIENT_LIST_SQL + " ORDER BY c.name"))
        return [_public(row) for row in rows]


# ── onboarding ──────────────────────────────────────────────────────────────

def _seed_onboarding(conn: sqlite3.Connection, client_id: int, stamp: str) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM onboarding_steps WHERE client_id = ?", (client_id,)).fetchone()[0]
    if existing:
        return
    conn.executemany(
        "INSERT INTO onboarding_steps (client_id, position, title, updated_utc) VALUES (?, ?, ?, ?)",
        [(client_id, pos, title, stamp) for pos, title in enumerate(DEFAULT_ONBOARDING_STEPS, start=1)],
    )


def add_onboarding_step(db_path: Path | str, client_id: int, title: str, *, now: datetime | None = None) -> dict:
    text = _text(title, "Título", required=True, cap=200)
    stamp = _iso(now)
    with _write(db_path) as conn:
        _require_client(conn, client_id)
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM onboarding_steps WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO onboarding_steps (client_id, position, title, updated_utc) VALUES (?, ?, ?, ?)",
            (client_id, position, text, stamp),
        )
        return _one(conn.execute("SELECT * FROM onboarding_steps WHERE id = ?", (cur.lastrowid,)))


def set_onboarding_step(
    db_path: Path | str, step_id: int, *, done: bool | None = None, pending_note: str | None = None,
    now: datetime | None = None,
) -> dict:
    if done is None and pending_note is None:
        raise ManagementError("Nada para atualizar.")
    stamp = _iso(now)
    with _write(db_path) as conn:
        row = _one(conn.execute("SELECT * FROM onboarding_steps WHERE id = ?", (step_id,)))
        if not row:
            raise ManagementError("Passo de onboarding não encontrado.")
        sets: dict[str, Any] = {}
        if done is not None:
            sets["done_utc"] = stamp if done else None
        if pending_note is not None:
            sets["pending_note"] = _text(pending_note, "Pendência", cap=1000)
        conn.execute(
            f"UPDATE onboarding_steps SET {', '.join(f'{k} = ?' for k in sets)}, updated_utc = ? WHERE id = ?",
            (*sets.values(), stamp, step_id),
        )
        return _one(conn.execute("SELECT * FROM onboarding_steps WHERE id = ?", (step_id,)))


def delete_onboarding_step(db_path: Path | str, step_id: int) -> dict | None:
    """Devolve o passo apagado (quem chama precisa do `client_id`) ou None."""
    with _write(db_path) as conn:
        row = _one(conn.execute("SELECT * FROM onboarding_steps WHERE id = ?", (step_id,)))
        if row:
            conn.execute("DELETE FROM onboarding_steps WHERE id = ?", (step_id,))
        return row


# ── tickets ─────────────────────────────────────────────────────────────────

def create_ticket(
    db_path: Path | str, *, title: str, description: str | None = None, kind: str = "other",
    priority: str = "medium", origin: str = "internal", status: str = "open", client_id: int | None = None,
    due_on: Any = None, now: datetime | None = None,
) -> dict:
    stamp = _iso(now)
    values = (
        client_id, _text(title, "Título", required=True, cap=300), _text(description, "Descrição", cap=20000),
        _enum(kind, TICKET_KINDS, "Tipo"), _enum(priority, TICKET_PRIORITIES, "Prioridade"),
        _enum(origin, TICKET_ORIGINS, "Origem"), _enum(status, TICKET_STATUSES, "Status"),
        _civil_date(due_on, "Prazo"), stamp, stamp,
    )
    with _write(db_path) as conn:
        if client_id is not None:
            _require_client(conn, client_id)
        cur = conn.execute(
            "INSERT INTO tickets (client_id, title, description, kind, priority, origin, status, due_on,"
            " opened_utc, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values,
        )
        ticket_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, kind, to_status, created_utc) VALUES (?, 'status', ?, ?)",
            (ticket_id, values[6], stamp),
        )
        return _one(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))


_TICKET_FIELDS = {
    "title": lambda v: _text(v, "Título", required=True, cap=300),
    "description": lambda v: _text(v, "Descrição", cap=20000),
    "kind": lambda v: _enum(v, TICKET_KINDS, "Tipo"),
    "priority": lambda v: _enum(v, TICKET_PRIORITIES, "Prioridade"),
    "origin": lambda v: _enum(v, TICKET_ORIGINS, "Origem"),
    "due_on": lambda v: _civil_date(v, "Prazo"),
    "resolution": lambda v: _text(v, "Resolução", cap=20000),
    "client_id": lambda v: v,
}


def update_ticket(db_path: Path | str, ticket_id: int, *, now: datetime | None = None, **fields) -> dict:
    unknown = set(fields) - set(_TICKET_FIELDS)
    if unknown:
        raise ManagementError(f"Campo desconhecido: {', '.join(sorted(unknown))}.")
    if not fields:
        raise ManagementError("Nada para atualizar.")
    values = {k: _TICKET_FIELDS[k](v) for k, v in fields.items()}
    with _write(db_path) as conn:
        _require_ticket(conn, ticket_id)
        if values.get("client_id") is not None:
            _require_client(conn, values["client_id"])
        conn.execute(
            f"UPDATE tickets SET {', '.join(f'{k} = ?' for k in values)}, updated_utc = ? WHERE id = ?",
            (*values.values(), _iso(now), ticket_id),
        )
        return _one(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))


def set_ticket_status(
    db_path: Path | str, ticket_id: int, status: str, *, note: str | None = None,
    resolution: str | None = None, now: datetime | None = None,
) -> dict:
    status = _enum(status, TICKET_STATUSES, "Status")
    stamp = _iso(now)
    with _write(db_path) as conn:
        current = _require_ticket(conn, ticket_id)
        if current["status"] == status:
            raise ManagementError(f"Ticket já está em {status}.")
        sets: dict[str, Any] = {"status": status}
        final_resolution = _text(resolution, "Resolução", cap=20000) or current["resolution"]
        if status in TICKET_DONE:
            if not final_resolution:
                raise ManagementError("Resolver ou fechar exige a resolução preenchida.")
            sets["resolution"] = final_resolution
            sets["resolved_utc"] = current["resolved_utc"] or stamp
        elif current["status"] in TICKET_DONE:
            sets["resolved_utc"] = None
        conn.execute(
            f"UPDATE tickets SET {', '.join(f'{k} = ?' for k in sets)}, updated_utc = ? WHERE id = ?",
            (*sets.values(), stamp, ticket_id),
        )
        conn.execute(
            "INSERT INTO ticket_events (ticket_id, kind, from_status, to_status, note, created_utc)"
            " VALUES (?, 'status', ?, ?, ?, ?)",
            (ticket_id, current["status"], status, _text(note, "Nota"), stamp),
        )
        return _one(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))


def add_ticket_comment(db_path: Path | str, ticket_id: int, note: str, *, now: datetime | None = None) -> dict:
    text = _text(note, "Comentário", required=True, cap=20000)
    stamp = _iso(now)
    with _write(db_path) as conn:
        _require_ticket(conn, ticket_id)
        cur = conn.execute(
            "INSERT INTO ticket_events (ticket_id, kind, note, created_utc) VALUES (?, 'comment', ?, ?)",
            (ticket_id, text, stamp),
        )
        conn.execute("UPDATE tickets SET updated_utc = ? WHERE id = ?", (stamp, ticket_id))
        return _one(conn.execute("SELECT * FROM ticket_events WHERE id = ?", (cur.lastrowid,)))


def _require_ticket(conn: sqlite3.Connection, ticket_id: Any) -> dict:
    row = _one(conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)))
    if not row:
        raise ManagementError("Ticket não encontrado.")
    return row


_TICKET_LIST_SQL = """
SELECT t.*, c.name AS client_name, c.company AS client_company
FROM tickets t LEFT JOIN clients c ON c.id = t.client_id
"""


def get_ticket(db_path: Path | str, ticket_id: int) -> dict | None:
    with _read(db_path) as conn:
        row = _one(conn.execute(_TICKET_LIST_SQL + " WHERE t.id = ?", (ticket_id,)))
        if not row:
            return None
        row["events"] = _rows(conn.execute(
            "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY created_utc, id", (ticket_id,)))
        return row


def list_tickets(
    db_path: Path | str, *, status: str | None = None, client_id: int | None = None, open_only: bool = False,
) -> list[dict]:
    status = _enum(status, TICKET_STATUSES, "Status", required=False)
    where, params = [], []
    if status:
        where.append("t.status = ?"); params.append(status)
    elif open_only:
        where.append("t.status NOT IN ('resolved', 'closed')")
    if client_id is not None:
        where.append("t.client_id = ?"); params.append(client_id)
    sql = _TICKET_LIST_SQL + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END," \
           " t.updated_utc DESC, t.id DESC"
    with _read(db_path) as conn:
        return _rows(conn.execute(sql, params))


# ── pós-venda ───────────────────────────────────────────────────────────────

_TOUCHPOINT_FIELDS = {
    "kind": lambda v: _enum(v, TOUCHPOINT_KINDS, "Tipo"),
    "scheduled_on": lambda v: _civil_date(v, "Agendado para"),
    "done_on": lambda v: _civil_date(v, "Realizado em"),
    "health": lambda v: _enum(v, HEALTH_LEVELS, "Saúde", required=False),
    "summary": lambda v: _text(v, "Resumo", cap=4000),
    "next_action": lambda v: _text(v, "Próxima ação", cap=1000),
    "next_contact_on": lambda v: _civil_date(v, "Próximo contato"),
}


def create_touchpoint(db_path: Path | str, client_id: int, *, kind: str, now: datetime | None = None, **fields) -> dict:
    fields["kind"] = kind
    unknown = set(fields) - set(_TOUCHPOINT_FIELDS)
    if unknown:
        raise ManagementError(f"Campo desconhecido: {', '.join(sorted(unknown))}.")
    values = {k: _TOUCHPOINT_FIELDS[k](fields.get(k)) for k in _TOUCHPOINT_FIELDS}
    if not values["scheduled_on"] and not values["done_on"]:
        raise ManagementError("Informe a data agendada ou a data realizada.")
    if values["done_on"] and not values["health"]:
        raise ManagementError("Contato realizado precisa da avaliação de saúde.")
    stamp = _iso(now)
    with _write(db_path) as conn:
        _require_client(conn, client_id)
        cols = ", ".join(values)
        cur = conn.execute(
            f"INSERT INTO touchpoints (client_id, {cols}, created_utc, updated_utc)"
            f" VALUES (?, {', '.join('?' for _ in values)}, ?, ?)",
            (client_id, *values.values(), stamp, stamp),
        )
        return _one(conn.execute("SELECT * FROM touchpoints WHERE id = ?", (cur.lastrowid,)))


def update_touchpoint(db_path: Path | str, touchpoint_id: int, *, now: datetime | None = None, **fields) -> dict:
    unknown = set(fields) - set(_TOUCHPOINT_FIELDS)
    if unknown:
        raise ManagementError(f"Campo desconhecido: {', '.join(sorted(unknown))}.")
    if not fields:
        raise ManagementError("Nada para atualizar.")
    values = {k: _TOUCHPOINT_FIELDS[k](v) for k, v in fields.items()}
    with _write(db_path) as conn:
        current = _one(conn.execute("SELECT * FROM touchpoints WHERE id = ?", (touchpoint_id,)))
        if not current:
            raise ManagementError("Acompanhamento não encontrado.")
        merged = {**current, **values}
        if merged["done_on"] and not merged["health"]:
            raise ManagementError("Contato realizado precisa da avaliação de saúde.")
        conn.execute(
            f"UPDATE touchpoints SET {', '.join(f'{k} = ?' for k in values)}, updated_utc = ? WHERE id = ?",
            (*values.values(), _iso(now), touchpoint_id),
        )
        return _one(conn.execute("SELECT * FROM touchpoints WHERE id = ?", (touchpoint_id,)))


# ── cobranças ───────────────────────────────────────────────────────────────

def ensure_period(db_path: Path | str, period: str, *, now: datetime | None = None) -> dict:
    """Materializa, sem duplicar, a mensalidade de cada cliente ativo, a
    implementação na competência de início e os planos de custo vigentes."""
    period = _period(period)
    start, end = _period_bounds(period)
    stamp = _iso(now)
    created = {"monthly": 0, "setup": 0, "costs": 0}
    with _write(db_path) as conn:
        active = _rows(conn.execute(
            "SELECT * FROM clients WHERE status = 'active' AND monthly_cents > 0"
            " AND (activated_on IS NULL OR activated_on <= ?)", (end,)))
        for client in active:
            due = f"{period}-{(client['billing_day'] or DEFAULT_BILLING_DAY):02d}"
            cur = conn.execute(
                "INSERT OR IGNORE INTO charges (client_id, period, kind, due_on, amount_cents, created_utc, updated_utc)"
                " VALUES (?, ?, 'monthly', ?, ?, ?, ?)",
                (client["id"], period, due, client["monthly_cents"], stamp, stamp),
            )
            created["monthly"] += cur.rowcount
        setups = _rows(conn.execute(
            "SELECT * FROM clients WHERE setup_cents > 0 AND started_on BETWEEN ? AND ?"
            " AND status NOT IN ('negotiation', 'cancelled')", (start, end)))
        for client in setups:
            cur = conn.execute(
                "INSERT OR IGNORE INTO charges (client_id, period, kind, due_on, amount_cents, created_utc, updated_utc)"
                " VALUES (?, ?, 'setup', ?, ?, ?, ?)",
                (client["id"], period, client["started_on"], client["setup_cents"], stamp, stamp),
            )
            created["setup"] += cur.rowcount
        plans = _rows(conn.execute(
            "SELECT * FROM cost_plans WHERE active_from <= ? AND (active_to IS NULL OR active_to >= ?)",
            (period, period)))
        for plan in plans:
            cur = conn.execute(
                "INSERT OR IGNORE INTO costs (client_id, plan_id, period, category, amount_cents, label, source,"
                " created_utc, updated_utc) VALUES (?, ?, ?, ?, ?, ?, 'plan', ?, ?)",
                (plan["client_id"], plan["id"], period, plan["category"], plan["monthly_cents"], plan["label"],
                 stamp, stamp),
            )
            created["costs"] += cur.rowcount
    return created


def add_adhoc_charge(
    db_path: Path | str, client_id: int, *, period: str, due_on: Any, amount_cents: int,
    note: str | None = None, now: datetime | None = None,
) -> dict:
    stamp = _iso(now)
    with _write(db_path) as conn:
        _require_client(conn, client_id)
        cur = conn.execute(
            "INSERT INTO charges (client_id, period, kind, due_on, amount_cents, note, created_utc, updated_utc)"
            " VALUES (?, ?, 'adhoc', ?, ?, ?, ?, ?)",
            (client_id, _period(period), _civil_date(due_on, "Vencimento", required=True),
             _cents(amount_cents, "Valor"), _text(note, "Nota", cap=1000), stamp, stamp),
        )
        return _one(conn.execute("SELECT * FROM charges WHERE id = ?", (cur.lastrowid,)))


def pay_charge(
    db_path: Path | str, charge_id: int, *, paid_on: Any, paid_cents: int | None = None,
    note: str | None = None, now: datetime | None = None,
) -> dict:
    with _write(db_path) as conn:
        charge = _one(conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)))
        if not charge:
            raise ManagementError("Cobrança não encontrada.")
        if charge["status"] == "cancelled":
            raise ManagementError("Cobrança cancelada não recebe baixa.")
        amount = _cents(paid_cents, "Valor recebido", required=False)
        conn.execute(
            "UPDATE charges SET status = 'paid', paid_on = ?, paid_cents = ?, note = COALESCE(?, note),"
            " updated_utc = ? WHERE id = ?",
            (_civil_date(paid_on, "Data do recebimento", required=True),
             charge["amount_cents"] if amount is None else amount, _text(note, "Nota", cap=1000),
             _iso(now), charge_id),
        )
        return _one(conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)))


def cancel_charge(db_path: Path | str, charge_id: int, *, note: str | None = None, now: datetime | None = None) -> dict:
    with _write(db_path) as conn:
        charge = _one(conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)))
        if not charge:
            raise ManagementError("Cobrança não encontrada.")
        if charge["status"] == "paid":
            raise ManagementError("Cobrança já recebida não pode ser cancelada.")
        conn.execute(
            "UPDATE charges SET status = 'cancelled', note = COALESCE(?, note), updated_utc = ? WHERE id = ?",
            (_text(note, "Nota", cap=1000), _iso(now), charge_id),
        )
        return _one(conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)))


def reopen_charge(db_path: Path | str, charge_id: int, *, now: datetime | None = None) -> dict:
    """Desfaz baixa ou cancelamento (clique errado)."""
    with _write(db_path) as conn:
        if not _one(conn.execute("SELECT id FROM charges WHERE id = ?", (charge_id,))):
            raise ManagementError("Cobrança não encontrada.")
        conn.execute(
            "UPDATE charges SET status = 'expected', paid_on = NULL, paid_cents = NULL, updated_utc = ? WHERE id = ?",
            (_iso(now), charge_id),
        )
        return _one(conn.execute("SELECT * FROM charges WHERE id = ?", (charge_id,)))


# ── custos ──────────────────────────────────────────────────────────────────

def upsert_cost_plan(
    db_path: Path | str, *, plan_id: int | None = None, client_id: int | None = None, category: str,
    monthly_cents: int, label: str | None = None, active_from: str, active_to: str | None = None,
    now: datetime | None = None,
) -> dict:
    values = (
        client_id, _enum(category, COST_CATEGORIES, "Categoria"), _cents(monthly_cents, "Valor mensal"),
        _text(label, "Descrição", cap=200), _period(active_from), _period(active_to) if active_to else None,
        _iso(now),
    )
    with _write(db_path) as conn:
        if client_id is not None:
            _require_client(conn, client_id)
        if plan_id is None:
            cur = conn.execute(
                "INSERT INTO cost_plans (client_id, category, monthly_cents, label, active_from, active_to, updated_utc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)", values,
            )
            plan_id = int(cur.lastrowid)
        else:
            changed = conn.execute(
                "UPDATE cost_plans SET client_id = ?, category = ?, monthly_cents = ?, label = ?, active_from = ?,"
                " active_to = ?, updated_utc = ? WHERE id = ?", (*values, plan_id),
            ).rowcount
            if not changed:
                raise ManagementError("Plano de custo não encontrado.")
        return _one(conn.execute("SELECT * FROM cost_plans WHERE id = ?", (plan_id,)))


def end_cost_plan(db_path: Path | str, plan_id: int, *, active_to: str, now: datetime | None = None) -> dict:
    with _write(db_path) as conn:
        changed = conn.execute(
            "UPDATE cost_plans SET active_to = ?, updated_utc = ? WHERE id = ?",
            (_period(active_to), _iso(now), plan_id),
        ).rowcount
        if not changed:
            raise ManagementError("Plano de custo não encontrado.")
        return _one(conn.execute("SELECT * FROM cost_plans WHERE id = ?", (plan_id,)))


def list_cost_plans(db_path: Path | str, *, period: str | None = None) -> list[dict]:
    sql = "SELECT p.*, c.name AS client_name FROM cost_plans p LEFT JOIN clients c ON c.id = p.client_id"
    params: tuple = ()
    if period:
        period = _period(period)
        sql += " WHERE p.active_from <= ? AND (p.active_to IS NULL OR p.active_to >= ?)"
        params = (period, period)
    with _read(db_path) as conn:
        return _rows(conn.execute(sql + " ORDER BY p.client_id IS NOT NULL, c.name, p.category, p.id", params))


def upsert_cost(
    db_path: Path | str, *, cost_id: int | None = None, client_id: int | None = None, period: str | None = None,
    category: str | None = None, amount_cents: int, label: str | None = None, note: str | None = None,
    currency_original: str | None = None, amount_original: float | None = None, now: datetime | None = None,
) -> dict:
    """Lançamento manual. Com `cost_id` ajusta um existente (inclusive o que veio
    de plano, que passa a `manual`); sem, cria um novo."""
    amount = _cents(amount_cents, "Valor")
    stamp = _iso(now)
    currency = (_text(currency_original, "Moeda", cap=8) or "").upper() or None
    if amount_original is not None and (isinstance(amount_original, bool) or amount_original < 0):
        raise ManagementError("Valor original inválido.")
    with _write(db_path) as conn:
        if cost_id is not None:
            changed = conn.execute(
                "UPDATE costs SET amount_cents = ?, label = COALESCE(?, label), note = COALESCE(?, note),"
                " currency_original = COALESCE(?, currency_original),"
                " amount_original = COALESCE(?, amount_original), source = 'manual', updated_utc = ? WHERE id = ?",
                (amount, _text(label, "Descrição", cap=200), _text(note, "Nota", cap=1000), currency,
                 amount_original, stamp, cost_id),
            ).rowcount
            if not changed:
                raise ManagementError("Custo não encontrado.")
        else:
            if client_id is not None:
                _require_client(conn, client_id)
            cur = conn.execute(
                "INSERT INTO costs (client_id, period, category, amount_cents, currency_original, amount_original,"
                " label, note, source, created_utc, updated_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
                (client_id, _period(period), _enum(category, COST_CATEGORIES, "Categoria"), amount, currency,
                 amount_original, _text(label, "Descrição", cap=200), _text(note, "Nota", cap=1000), stamp, stamp),
            )
            cost_id = int(cur.lastrowid)
        return _one(conn.execute("SELECT * FROM costs WHERE id = ?", (cost_id,)))


def delete_cost(db_path: Path | str, cost_id: int) -> bool:
    with _write(db_path) as conn:
        return conn.execute("DELETE FROM costs WHERE id = ?", (cost_id,)).rowcount > 0


# ── agregados ───────────────────────────────────────────────────────────────

def finance_summary(db_path: Path | str, period: str, *, today: date | None = None) -> dict:
    """Placar da competência. Não materializa nada: chame `ensure_period` antes
    quando a tela abrir o mês."""
    period = _period(period)
    today_iso = (today or datetime.now(UTC).date()).isoformat()
    start, end = _period_bounds(period)
    with _read(db_path) as conn:
        clients = [_public(row) for row in _rows(conn.execute("SELECT * FROM clients ORDER BY name"))]
        charges = _rows(conn.execute(
            "SELECT ch.*, c.name AS client_name FROM charges ch JOIN clients c ON c.id = ch.client_id"
            " WHERE ch.period = ? OR (ch.status = 'paid' AND ch.paid_on BETWEEN ? AND ?)"
            " ORDER BY ch.due_on, ch.id", (period, start, end)))
        overdue_all = _rows(conn.execute(
            "SELECT ch.*, c.name AS client_name FROM charges ch JOIN clients c ON c.id = ch.client_id"
            " WHERE ch.status = 'expected' AND ch.due_on < ? ORDER BY ch.due_on, ch.id", (today_iso,)))
        costs = _rows(conn.execute(
            "SELECT co.*, c.name AS client_name FROM costs co LEFT JOIN clients c ON c.id = co.client_id"
            " WHERE co.period = ? ORDER BY co.client_id IS NOT NULL, c.name, co.category, co.id", (period,)))

    mrr = sum(c["monthly_cents"] for c in clients if c["status"] == "active")
    expected = sum(ch["amount_cents"] for ch in charges if ch["period"] == period and ch["status"] == "expected")
    received = sum(ch["paid_cents"] or 0 for ch in charges
                   if ch["status"] == "paid" and start <= (ch["paid_on"] or "") <= end)
    overdue_period = [ch for ch in charges if ch["period"] == period and ch["status"] == "expected"
                      and ch["due_on"] < today_iso]
    by_category = {cat: 0 for cat in COST_CATEGORIES}
    for co in costs:
        by_category[co["category"]] += co["amount_cents"]
    total_costs = sum(by_category.values())
    shared_costs = sum(co["amount_cents"] for co in costs if co["client_id"] is None)

    per_client = []
    for client in clients:
        cid = client["id"]
        c_received = sum(ch["paid_cents"] or 0 for ch in charges
                         if ch["client_id"] == cid and ch["status"] == "paid"
                         and start <= (ch["paid_on"] or "") <= end)
        c_costs = sum(co["amount_cents"] for co in costs if co["client_id"] == cid)
        c_charges = [ch for ch in charges if ch["client_id"] == cid and ch["period"] == period]
        c_cost_rows = [co for co in costs if co["client_id"] == cid]
        if client["status"] not in ("active", "paused") and not c_charges and not c_cost_rows and not c_received:
            continue
        per_client.append({
            "client_id": cid, "name": client["name"], "company": client["company"], "status": client["status"],
            "monthly_cents": client["monthly_cents"],
            "received_cents": c_received, "costs_cents": c_costs, "margin_cents": c_received - c_costs,
            "charges": c_charges, "costs": c_cost_rows,
            "overdue": any(ch["status"] == "expected" and ch["due_on"] < today_iso for ch in c_charges),
        })

    return {
        "period": period,
        "mrr_cents": mrr,
        "active_clients": sum(1 for c in clients if c["status"] == "active"),
        "expected_cents": expected,
        "received_cents": received,
        "overdue_cents": sum(ch["amount_cents"] for ch in overdue_period),
        "overdue_count": len(overdue_period),
        "overdue_all_cents": sum(ch["amount_cents"] for ch in overdue_all),
        "overdue_all": overdue_all,
        "costs_cents": total_costs,
        "costs_by_category": by_category,
        "shared_costs": [co for co in costs if co["client_id"] is None],
        "shared_costs_cents": shared_costs,
        "margin_cents": received - total_costs,
        "clients": per_client,
    }
