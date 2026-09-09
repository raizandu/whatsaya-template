#!/usr/bin/env python3
"""Migra o SQLite do bot Therapify para os stores do WhatsAYA.

O comando lê uma cópia consistente do banco de origem, valida o schema antes de
qualquer escrita e usa IDs de origem para tornar todas as operações idempotentes.
Os dados são escritos apenas em ``data-dir``; o relatório contém contagens, nunca
telefones, mensagens ou valores de configuração.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import contacts_store


TABLE_REQUIREMENTS: dict[str, set[str]] = {
    "leads": {
        "phone",
        "profile_name",
        "full_name",
        "gender",
        "status",
        "is_existing_patient",
        "paused",
        "last_phase",
        "last_inbound_at",
        "last_outbound_at",
        "created_at",
        "updated_at",
    },
    "messages": {
        "id",
        "wamid",
        "phone",
        "direction",
        "role",
        "body",
        "context_wamid",
        "created_at",
    },
    "appointments": {
        "id",
        "phone",
        "slot_start",
        "slot_end",
        "kind",
        "status",
        "created_at",
    },
    "purchases": {"id", "phone", "product", "amount", "created_at"},
    "escalations": {"id", "phone", "reason", "resolved", "created_at"},
    "app_settings": {"key", "value"},
    "reactivation_progress": {"phone", "stage", "updated_at"},
}

TERMINAL_SOURCE_STATUSES = {
    "purchased_gravado",
    "purchased_protocolo_final",
    "existing_patient",
    "lost",
}
STAGE_MAP = {
    "new": "new",
    "in_funnel": "qualification",
    "scheduled_session": "proposal",
    "purchased_gravado": "payment",
    "purchased_protocolo_final": "payment",
    "existing_patient": "won",
    "lost": "lost",
}
SENSITIVE_SETTING_RE = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "refresh",
    "credential",
)


class MigrationError(RuntimeError):
    """Falha segura: nenhuma operação deve continuar após este erro."""


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _digits(value: Any) -> str:
    raw = str(value or "").strip()
    local = raw.split("@", 1)[0].split(":", 1)[0]
    return "".join(character for character in local if character.isdigit())


def canonical_chat_id(value: Any) -> str:
    """Converte telefone/JID da origem para o JID canônico do bridge."""
    raw = str(value or "").strip()
    if not raw:
        raise MigrationError("identidade vazia na origem")
    if "@" in raw:
        local, domain = raw.split("@", 1)
        local = local.strip()
        domain = domain.strip().lower()
        if not local:
            raise MigrationError("JID sem identificador na origem")
        if domain == "lid":
            return f"{local}@lid"
        if domain in {"s.whatsapp.net", "c.us"}:
            digits = _digits(local)
            if not digits:
                raise MigrationError("JID sem telefone na origem")
            return f"{digits}@s.whatsapp.net"
        return f"{local}@{domain}"
    digits = _digits(raw)
    if not digits:
        raise MigrationError("telefone inválido na origem")
    return f"{digits}@s.whatsapp.net"


def _owner_numbers(values: Iterable[str]) -> set[str]:
    numbers = {_digits(value) for value in values}
    return {value for value in numbers if value}


def _is_owner(value: Any, owners: set[str]) -> bool:
    return bool(owners and _digits(value) in owners)


def _uri_read_only(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(_uri_read_only(path), uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise MigrationError("não foi possível abrir o SQLite de origem") from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _snapshot_source(source: Path, directory: Path) -> Path:
    """Faz backup pela API SQLite; não copia .db enquanto WAL está em uso."""
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / "source-consistent.db"
    source_conn = _connect_read_only(source)
    destination = sqlite3.connect(snapshot)
    try:
        source_conn.backup(destination)
        destination.execute("PRAGMA journal_mode=DELETE")
        destination.commit()
    except sqlite3.Error as exc:
        raise MigrationError("snapshot consistente da origem falhou") from exc
    finally:
        source_conn.close()
        destination.close()
    return snapshot


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def validate_source(connection: sqlite3.Connection) -> dict[str, int]:
    """Valida integridade, tabelas e colunas exigidas; devolve contagens."""
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise MigrationError("não foi possível validar a integridade da origem") from exc
    if not integrity or str(integrity[0]).lower() != "ok":
        raise MigrationError("integrity_check da origem não passou")
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    available = {str(row[0]) for row in rows}
    missing_tables = sorted(set(TABLE_REQUIREMENTS) - available)
    if missing_tables:
        raise MigrationError("schema da origem sem tabelas obrigatórias")
    for table, required in TABLE_REQUIREMENTS.items():
        missing_columns = sorted(required - _table_columns(connection, table))
        if missing_columns:
            raise MigrationError(f"schema da origem incompatível em {table}")
    counts: dict[str, int] = {}
    for table in TABLE_REQUIREMENTS:
        counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return counts


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _parse_timestamp(value: Any) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = dt.datetime.strptime(raw, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def _source_fingerprint(counts: dict[str, int], rows: dict[str, list[dict[str, Any]]]) -> str:
    material = {
        "counts": counts,
        "ids": {
            table: [str(row.get("id") or row.get("phone") or row.get("key") or "") for row in items]
            for table, items in rows.items()
        },
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError("JSON canônico inválido") from exc
    if not isinstance(value, dict):
        raise MigrationError("JSON canônico precisa ter objeto na raiz")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.migration.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _backup_db(path: Path, destination: Path) -> bool:
    if not path.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
    except sqlite3.Error as exc:
        raise MigrationError("backup de store SQLite falhou") from exc
    finally:
        source.close()
        target.close()
    return True


def _backup_file(path: Path, destination: Path) -> bool:
    if not path.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(path, destination)
    except OSError as exc:
        raise MigrationError("backup de store JSON falhou") from exc
    return True


def _restore_target(path: Path, backup: Path, existed: bool) -> None:
    """Restaura somente o caminho explícito desta execução em caso de falha."""
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            path.with_name(path.name + suffix).unlink()
    if existed:
        temporary = path.with_name(f"{path.name}.{os.getpid()}.rollback.tmp")
        shutil.copy2(backup, temporary)
        os.replace(temporary, path)
    else:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _rollback_targets(
    *,
    backups: dict[str, bool],
    backup_root: Path,
    contacts_json: Path,
    sales_json: Path,
    handoff_outbox: Path,
    messages_db: Path,
    followups_db: Path,
) -> None:
    paths = {
        "contacts": (contacts_json, backup_root / "personal_contacts.json"),
        "sales": (sales_json, backup_root / "sales.json"),
        "outbox": (handoff_outbox, backup_root / "handoff_notification_outbox.json"),
        "messages": (messages_db, backup_root / "whatsapp_messages.db"),
        "followups": (followups_db, backup_root / "commercial_followups.db"),
    }
    failures: list[str] = []
    for name, (path, backup) in paths.items():
        try:
            _restore_target(path, backup, backups.get(name, False))
        except OSError:
            failures.append(name)
    if failures:
        raise MigrationError("rollback incompleto dos stores canônicos")


def _ensure_messages_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            sender_id TEXT,
            sender_name TEXT,
            message_id TEXT NOT NULL,
            message_type TEXT,
            body TEXT,
            timestamp REAL,
            from_me INTEGER NOT NULL DEFAULT 0,
            is_historical INTEGER NOT NULL DEFAULT 0,
            has_media INTEGER NOT NULL DEFAULT 0,
            media_type TEXT,
            sync_type TEXT,
            context_wamid TEXT,
            inserted_at REAL NOT NULL DEFAULT (strftime('%s','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_chat_ts ON messages(chat_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_message_id ON messages(message_id);
        CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_from_me ON messages(from_me, timestamp);
        """
    )
    columns = _table_columns(connection, "messages")
    additions = {
        "sender_id": "TEXT",
        "sender_name": "TEXT",
        "message_id": "TEXT",
        "message_type": "TEXT",
        "body": "TEXT",
        "timestamp": "REAL",
        "from_me": "INTEGER NOT NULL DEFAULT 0",
        "is_historical": "INTEGER NOT NULL DEFAULT 0",
        "has_media": "INTEGER NOT NULL DEFAULT 0",
        "media_type": "TEXT",
        "sync_type": "TEXT",
        "context_wamid": "TEXT",
        "inserted_at": "REAL NOT NULL DEFAULT 0",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")
    try:
        connection.execute(
            """
            DELETE FROM messages
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY chat_id, message_id
                        ORDER BY CASE WHEN body IS NULL OR TRIM(body) = '' THEN 1 ELSE 0 END, id
                    ) AS row_number
                    FROM messages
                ) WHERE row_number = 1
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_messages_unique "
            "ON messages(chat_id, message_id)"
        )
    except sqlite3.IntegrityError as exc:
        raise MigrationError("store de mensagens contém IDs duplicados") from exc


def _ensure_followup_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
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
        CREATE INDEX IF NOT EXISTS idx_followup_due ON followup_jobs(status, due_utc);
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
        CREATE TABLE IF NOT EXISTS therapify_leads (
            source_phone TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL UNIQUE,
            profile_name TEXT,
            full_name TEXT,
            gender TEXT,
            status TEXT NOT NULL,
            is_existing_patient INTEGER NOT NULL DEFAULT 0,
            paused INTEGER NOT NULL DEFAULT 0,
            last_phase TEXT,
            last_inbound_at TEXT,
            last_outbound_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            migrated_at TEXT NOT NULL,
            source_status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_phone TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            slot_start TEXT NOT NULL,
            slot_end TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            UNIQUE(source_id, source_phone)
        );
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_phone TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            product TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            UNIQUE(source_id, source_phone)
        );
        CREATE TABLE IF NOT EXISTS escalations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            source_phone TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            UNIQUE(source_id, source_phone)
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            source_value TEXT NOT NULL,
            redacted INTEGER NOT NULL DEFAULT 0,
            migrated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reactivation_progress (
            phone TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL UNIQUE,
            stage INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            migrated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS therapify_message_map (
            source_id TEXT PRIMARY KEY,
            source_phone TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            UNIQUE(source_phone, message_id)
        );
        CREATE TABLE IF NOT EXISTS migration_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL UNIQUE,
            dry_run INTEGER NOT NULL DEFAULT 0,
            counts_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    lead_columns = _table_columns(connection, "lead_state")
    for name, definition in {
        "source_status": "TEXT",
        "source_phone": "TEXT",
        "source_created_at": "TEXT",
        "source_updated_at": "TEXT",
        "source_paused": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if name not in lead_columns:
            connection.execute(f"ALTER TABLE lead_state ADD COLUMN {name} {definition}")
    settings_columns = _table_columns(connection, "app_settings")
    for name, definition in {
        "source_value": "TEXT NOT NULL DEFAULT ''",
        "redacted": "INTEGER NOT NULL DEFAULT 0",
        "migrated_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if name not in settings_columns:
            connection.execute(f"ALTER TABLE app_settings ADD COLUMN {name} {definition}")


def _stage_for(status: Any) -> str:
    return STAGE_MAP.get(str(status or "").strip().lower(), "qualification")


def _cadence_for(stage: str) -> str:
    return {"new": "silence", "qualification": "silence", "pricing": "proposal", "proposal": "proposal", "payment": "payment"}.get(stage, "silence")


def _is_sensitive_setting(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_SETTING_RE)


def _safe_setting(key: Any, value: Any) -> tuple[str, str, int]:
    clean_key = str(key or "").strip()
    if not clean_key:
        raise MigrationError("app_settings contém chave vazia")
    raw_value = str(value if value is not None else "")
    if _is_sensitive_setting(clean_key):
        return "[REDACTED]", "[REDACTED]", 1
    return raw_value[:8192], raw_value[:8192], 0


def _contact_fields(
    lead: dict[str, Any],
    chat_id: str,
    reactivation_stage: int | None,
    existing: dict[str, Any],
    enable_automation: bool,
) -> dict[str, Any]:
    status = str(lead.get("status") or "new")
    status_key = status.strip().lower()
    paused = bool(_safe_int(lead.get("paused")))
    terminal = status_key in TERMINAL_SOURCE_STATUSES
    name = str(lead.get("profile_name") or lead.get("full_name") or "").strip()
    result = dict(existing)
    if name and not result.get("name"):
        result["name"] = name
    for source_field in ("profile_name", "full_name", "gender", "last_phase", "created_at", "updated_at"):
        target_field = f"therapify_{source_field}"
        value = lead.get(source_field)
        if value not in (None, "") and target_field not in result:
            result[target_field] = value
    result.setdefault("flow_origin", "therapify_migration")
    result.setdefault("therapify_status", status)
    result.setdefault("therapify_is_existing_patient", bool(_safe_int(lead.get("is_existing_patient"))))
    result.setdefault("therapify_paused", paused)
    result.setdefault("commercial_stage", _stage_for(status))
    if reactivation_stage is not None:
        result.setdefault("reactivation_stage", reactivation_stage)
    if "ai_enabled" not in result:
        result["ai_enabled"] = bool(enable_automation and not paused and not terminal)
    if "in_flow" not in result:
        result["in_flow"] = bool(enable_automation and not paused and not terminal)
    if (
        enable_automation
        and not paused
        and not terminal
        and result.get("ai_disabled_reason") == "therapify_migration_pending_cutover"
        and result.get("blocked") is not True
    ):
        result["ai_enabled"] = True
        result["in_flow"] = True
        result.pop("ai_disabled_reason", None)
    if not result["ai_enabled"]:
        result.setdefault("ai_disabled_reason", "therapify_migration_pending_cutover")
    result.setdefault("ai_policy_version", 2)
    return result


def _sales_id(source_id: str) -> str:
    return f"therapify-{source_id}"


def _merge_sales(path: Path, purchases: list[dict[str, Any]], leads_by_phone: dict[str, dict[str, Any]], owners: set[str]) -> tuple[int, int]:
    sales = _load_json(path)
    added = 0
    skipped = 0
    for row in purchases:
        source_phone = str(row.get("phone") or "").strip()
        if _is_owner(source_phone, owners):
            skipped += 1
            continue
        chat_id = canonical_chat_id(source_phone)
        key = _sales_id(str(row.get("id")))
        if key in sales:
            skipped += 1
            continue
        lead = leads_by_phone.get(source_phone, {})
        created = str(row.get("created_at") or "")
        sales[key] = {
            "contact_key": chat_id,
            "contact_name": str(lead.get("profile_name") or lead.get("full_name") or ""),
            "product": str(row.get("product") or ""),
            "quantity": 1,
            "amount": row.get("amount"),
            "payment_datetime": created,
            "address": None,
            "receipt_path": None,
            "status": "confirmed",
            "detected_at": _parse_timestamp(created),
            "detected_at_str": created,
            "migration_source": "therapify",
            "source_purchase_id": str(row.get("id")),
        }
        added += 1
    if added:
        with contacts_store.file_lock(path):
            _write_json_atomic(path, sales)
    return added, skipped


def _merge_outbox(path: Path, escalations: list[dict[str, Any]], owners: set[str]) -> tuple[int, int]:
    outbox = _load_json(path)
    added = 0
    skipped = 0
    now = time.time()
    for row in escalations:
        source_phone = str(row.get("phone") or "").strip()
        if _is_owner(source_phone, owners) or _safe_int(row.get("resolved")):
            skipped += 1
            continue
        key = f"therapify-escalation-{row.get('id')}"
        if key in outbox:
            skipped += 1
            continue
        outbox[key] = {
            "chat_id": canonical_chat_id(source_phone),
            "kind": "handoff",
            "reason": str(row.get("reason") or "imported escalation")[:160],
            "summary": "",
            "attempts": 0,
            "next_at": now,
            "updated_at": _parse_timestamp(row.get("created_at")) or now,
            "migration_source": "therapify",
        }
        added += 1
    if added:
        with contacts_store.file_lock(path):
            _write_json_atomic(path, outbox)
    return added, skipped


def _target_counts(messages_db: Path, followups_db: Path, contacts_path: Path, sales_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if messages_db.exists():
        with sqlite3.connect(messages_db) as connection:
            for table in ("messages",):
                if table in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    counts[f"messages.{table}"] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    if followups_db.exists():
        with sqlite3.connect(followups_db) as connection:
            for table in ("lead_state", "therapify_leads", "appointments", "purchases", "escalations", "app_settings", "reactivation_progress", "therapify_message_map"):
                if table in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                    counts[f"followups.{table}"] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    counts["contacts"] = len(_load_json(contacts_path))
    counts["sales"] = len(_load_json(sales_path))
    return counts


def _post_validate(messages_db: Path, followups_db: Path, contacts_path: Path, sales_path: Path) -> None:
    for path in (messages_db, followups_db):
        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or str(result[0]).lower() != "ok":
                raise MigrationError("integrity_check do store canônico não passou")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    _load_json(contacts_path)
    _load_json(sales_path)


def _prepare_plan(
    rows: dict[str, list[dict[str, Any]]],
    owners: set[str],
) -> dict[str, Any]:
    plan = {"source_rows": {table: len(items) for table, items in rows.items()}, "owner_rows": {}, "eligible_rows": {}}
    for table, items in rows.items():
        owner_count = sum(1 for row in items if _is_owner(row.get("phone"), owners))
        plan["owner_rows"][table] = owner_count
        plan["eligible_rows"][table] = len(items) - owner_count
    return plan


def run_migration(
    *,
    source_db: Path,
    data_dir: Path,
    contacts_json: Path | None = None,
    messages_db: Path | None = None,
    followups_db: Path | None = None,
    sales_json: Path | None = None,
    handoff_outbox: Path | None = None,
    owner_numbers: Iterable[str] = (),
    enable_automation: bool = False,
    activate_escalations: bool = False,
    dry_run: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    source_db = source_db.resolve()
    data_dir = data_dir.resolve()
    contacts_json = (contacts_json or data_dir / "personal_contacts.json").resolve()
    messages_db = (messages_db or data_dir / ".hermes" / "whatsapp_messages.db").resolve()
    followups_db = (followups_db or data_dir / ".hermes" / "commercial_followups.db").resolve()
    sales_json = (sales_json or data_dir / "sales.json").resolve()
    handoff_outbox = (handoff_outbox or data_dir / ".hermes" / "handoff_notification_outbox.json").resolve()
    if not source_db.is_file():
        raise MigrationError("SQLite de origem não encontrado")
    owners = _owner_numbers([*owner_numbers, os.getenv("WHATSAPP_OWNER_NUMBER", "")])

    with tempfile.TemporaryDirectory(prefix="whatsaya-therapify-") as temporary:
        snapshot = _snapshot_source(source_db, Path(temporary))
        source_connection = sqlite3.connect(snapshot)
        source_connection.row_factory = sqlite3.Row
        try:
            source_counts = validate_source(source_connection)
            rows = {table: _rows(source_connection, table) for table in TABLE_REQUIREMENTS}
        finally:
            source_connection.close()

    fingerprint = _source_fingerprint(source_counts, rows)
    plan = _prepare_plan(rows, owners)
    report: dict[str, Any] = {
        "status": "dry-run" if dry_run else "planned",
        "source": "therapify-sqlite",
        "source_fingerprint": fingerprint,
        "plan": plan,
        "automation_enabled": bool(enable_automation),
        "escalations_activated": bool(activate_escalations),
    }
    if dry_run:
        report["status"] = "dry-run"
        report["target_before"] = _target_counts(messages_db, followups_db, contacts_json, sales_json)
        return report

    backup_root = (
        backup_dir
        or data_dir / ".hermes" / "migration-backups"
        / f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-{time.time_ns() % 1_000_000:06d}"
    ).resolve()
    backup_root.mkdir(parents=True, exist_ok=False)
    backups = {
        "contacts": _backup_file(contacts_json, backup_root / "personal_contacts.json"),
        "sales": _backup_file(sales_json, backup_root / "sales.json"),
        "outbox": _backup_file(handoff_outbox, backup_root / "handoff_notification_outbox.json"),
        "messages": _backup_db(messages_db, backup_root / "whatsapp_messages.db"),
        "followups": _backup_db(followups_db, backup_root / "commercial_followups.db"),
    }

    existing_contacts = _load_json(contacts_json)
    _load_json(sales_json)
    if activate_escalations:
        _load_json(handoff_outbox)
    leads_by_phone = {str(row.get("phone") or "").strip(): row for row in rows["leads"]}
    reactivation_by_phone = {
        str(row.get("phone") or "").strip(): _safe_int(row.get("stage"))
        for row in rows["reactivation_progress"]
    }
    migrated_at = _utc_now()
    migrated_contact_count = 0
    skipped_owner = 0
    for lead in rows["leads"]:
        source_phone = str(lead.get("phone") or "").strip()
        if _is_owner(source_phone, owners):
            skipped_owner += 1
            continue
        chat_id = canonical_chat_id(source_phone)
        current = existing_contacts.get(chat_id)
        existing = current if isinstance(current, dict) else {}
        existing_contacts[chat_id] = _contact_fields(
            lead,
            chat_id,
            reactivation_by_phone.get(source_phone),
            existing,
            enable_automation,
        )
        migrated_contact_count += 1

    messages_db.parent.mkdir(parents=True, exist_ok=True)
    followups_db.parent.mkdir(parents=True, exist_ok=True)
    messages_connection = sqlite3.connect(messages_db, timeout=30, isolation_level=None)
    followups_connection = sqlite3.connect(followups_db, timeout=30, isolation_level=None)
    messages_connection.execute("PRAGMA busy_timeout=30000")
    followups_connection.execute("PRAGMA busy_timeout=30000")
    migration_failure: Exception | None = None
    try:
        messages_connection.execute("PRAGMA journal_mode=WAL")
        followups_connection.execute("PRAGMA journal_mode=WAL")
        _ensure_messages_schema(messages_connection)
        _ensure_followup_schema(followups_connection)
        messages_connection.execute("BEGIN IMMEDIATE")
        followups_connection.execute("BEGIN IMMEDIATE")

        lead_count = 0
        for lead in rows["leads"]:
            source_phone = str(lead.get("phone") or "").strip()
            if _is_owner(source_phone, owners):
                continue
            chat_id = canonical_chat_id(source_phone)
            status = str(lead.get("status") or "new")
            mapped_stage = _stage_for(status)
            terminal = int(status.strip().lower() in TERMINAL_SOURCE_STATUSES)
            paused = int(bool(_safe_int(lead.get("paused"))))
            contact_record = existing_contacts.get(chat_id)
            blocked = isinstance(contact_record, dict) and contact_record.get("blocked") is True
            automation = int(bool(enable_automation and not paused and not terminal and not blocked))
            followups_connection.execute(
                """
                INSERT INTO lead_state(
                    chat_id, automation_enabled, stage, cadence_kind, takeover, terminal,
                    pause_reason, last_inbound_utc, last_outbound_utc, updated_utc,
                    source_status, source_phone, source_created_at, source_updated_at, source_paused
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    source_status=excluded.source_status,
                    source_phone=excluded.source_phone,
                    source_created_at=excluded.source_created_at,
                    source_updated_at=excluded.source_updated_at,
                    source_paused=excluded.source_paused,
                    automation_enabled=CASE
                        WHEN excluded.automation_enabled=1 AND lead_state.takeover=0 AND lead_state.terminal=0
                        THEN 1 ELSE lead_state.automation_enabled END,
                    pause_reason=CASE
                        WHEN excluded.automation_enabled=1 AND lead_state.takeover=0 AND lead_state.terminal=0
                        THEN NULL ELSE lead_state.pause_reason END,
                    terminal=MAX(lead_state.terminal, excluded.terminal),
                    last_inbound_utc=COALESCE(lead_state.last_inbound_utc, excluded.last_inbound_utc),
                    last_outbound_utc=COALESCE(lead_state.last_outbound_utc, excluded.last_outbound_utc),
                    updated_utc=excluded.updated_utc
                """,
                (
                    chat_id,
                    automation,
                    mapped_stage,
                    _cadence_for(mapped_stage),
                    paused,
                    terminal,
                    "therapify_migration_pending_cutover" if not automation else None,
                    lead.get("last_inbound_at"),
                    lead.get("last_outbound_at"),
                    str(lead.get("updated_at") or migrated_at),
                    status,
                    source_phone,
                    lead.get("created_at"),
                    lead.get("updated_at"),
                    paused,
                ),
            )
            followups_connection.execute(
                """
                INSERT INTO therapify_leads(
                    source_phone, chat_id, profile_name, full_name, gender, status,
                    is_existing_patient, paused, last_phase, last_inbound_at,
                    last_outbound_at, created_at, updated_at, migrated_at, source_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_phone) DO UPDATE SET
                    chat_id=excluded.chat_id, profile_name=excluded.profile_name,
                    full_name=excluded.full_name, gender=excluded.gender,
                    status=excluded.status, is_existing_patient=excluded.is_existing_patient,
                    paused=excluded.paused, last_phase=excluded.last_phase,
                    last_inbound_at=excluded.last_inbound_at, last_outbound_at=excluded.last_outbound_at,
                    created_at=excluded.created_at, updated_at=excluded.updated_at,
                    migrated_at=excluded.migrated_at, source_status=excluded.source_status
                """,
                (
                    source_phone,
                    chat_id,
                    lead.get("profile_name"),
                    lead.get("full_name"),
                    lead.get("gender"),
                    status,
                    _safe_int(lead.get("is_existing_patient")),
                    paused,
                    lead.get("last_phase"),
                    lead.get("last_inbound_at"),
                    lead.get("last_outbound_at"),
                    lead.get("created_at"),
                    lead.get("updated_at"),
                    migrated_at,
                    status,
                ),
            )
            lead_count += 1

        message_count = 0
        message_skipped = 0
        for row in rows["messages"]:
            source_phone = str(row.get("phone") or "").strip()
            if _is_owner(source_phone, owners):
                message_skipped += 1
                continue
            chat_id = canonical_chat_id(source_phone)
            source_id = str(row.get("id"))
            message_id = str(row.get("wamid") or "").strip() or f"therapify-{source_id}"
            direction = str(row.get("direction") or "in").lower()
            from_me = int(direction == "out")
            cursor = messages_connection.execute(
                """
                INSERT OR IGNORE INTO messages(
                    chat_id, sender_id, sender_name, message_id, message_type, body,
                    timestamp, from_me, is_historical, has_media, media_type, sync_type,
                    context_wamid, inserted_at
                ) VALUES (?, ?, ?, ?, 'text', ?, ?, ?, 1, 0, NULL, 'therapify-migration', ?, ?)
                """,
                (
                    chat_id,
                    chat_id,
                    ("owner" if from_me else str(leads_by_phone.get(source_phone, {}).get("profile_name") or "").strip()) or None,
                    message_id,
                    str(row.get("body") or ""),
                    _parse_timestamp(row.get("created_at")),
                    from_me,
                    row.get("context_wamid"),
                    time.time(),
                ),
            )
            if cursor.rowcount:
                message_count += 1
            else:
                message_skipped += 1
            followups_connection.execute(
                """
                INSERT INTO therapify_message_map(source_id, source_phone, chat_id, message_id, migrated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_phone=excluded.source_phone, chat_id=excluded.chat_id,
                    message_id=excluded.message_id, migrated_at=excluded.migrated_at
                """,
                (source_id, source_phone, chat_id, message_id, migrated_at),
            )

        extension_counts: dict[str, int] = {}
        for table in ("appointments", "purchases", "escalations"):
            inserted = 0
            for row in rows[table]:
                source_phone = str(row.get("phone") or "").strip()
                if _is_owner(source_phone, owners):
                    continue
                chat_id = canonical_chat_id(source_phone)
                source_id = str(row.get("id"))
                if table == "appointments":
                    statement = """
                        INSERT INTO appointments(source_id, source_phone, chat_id, slot_start, slot_end, kind, status, created_at, migrated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_id, source_phone) DO UPDATE SET
                            chat_id=excluded.chat_id, slot_start=excluded.slot_start, slot_end=excluded.slot_end,
                            kind=excluded.kind, status=excluded.status, created_at=excluded.created_at, migrated_at=excluded.migrated_at
                    """
                    parameters = (source_id, source_phone, chat_id, row.get("slot_start"), row.get("slot_end"), row.get("kind"), row.get("status"), row.get("created_at"), migrated_at)
                elif table == "purchases":
                    statement = """
                        INSERT INTO purchases(source_id, source_phone, chat_id, product, amount, created_at, migrated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_id, source_phone) DO UPDATE SET
                            chat_id=excluded.chat_id, product=excluded.product, amount=excluded.amount,
                            created_at=excluded.created_at, migrated_at=excluded.migrated_at
                    """
                    parameters = (source_id, source_phone, chat_id, row.get("product"), row.get("amount"), row.get("created_at"), migrated_at)
                else:
                    statement = """
                        INSERT INTO escalations(source_id, source_phone, chat_id, reason, resolved, created_at, migrated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_id, source_phone) DO UPDATE SET
                            chat_id=excluded.chat_id, reason=excluded.reason, resolved=excluded.resolved,
                            created_at=excluded.created_at, migrated_at=excluded.migrated_at
                    """
                    parameters = (source_id, source_phone, chat_id, row.get("reason"), _safe_int(row.get("resolved")), row.get("created_at"), migrated_at)
                followups_connection.execute(statement, parameters)
                inserted += 1
            extension_counts[table] = inserted

        setting_count = 0
        redacted_settings = 0
        for row in rows["app_settings"]:
            key = str(row.get("key") or "").strip()
            safe_value, source_value, redacted = _safe_setting(key, row.get("value"))
            target_key = key
            existing = followups_connection.execute(
                "SELECT source_value, migrated_at FROM app_settings WHERE key=?",
                (target_key,),
            ).fetchone()
            if existing and not (existing[0] or existing[1]):
                target_key = f"therapify.{key}"
            followups_connection.execute(
                """
                INSERT INTO app_settings(key, value, source_value, redacted, migrated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, source_value=excluded.source_value,
                    redacted=excluded.redacted, migrated_at=excluded.migrated_at
                """,
                (target_key, safe_value, source_value, redacted, migrated_at),
            )
            setting_count += 1
            redacted_settings += redacted

        reactivation_count = 0
        for row in rows["reactivation_progress"]:
            source_phone = str(row.get("phone") or "").strip()
            if _is_owner(source_phone, owners):
                continue
            chat_id = canonical_chat_id(source_phone)
            followups_connection.execute(
                """
                INSERT INTO reactivation_progress(phone, chat_id, stage, updated_at, migrated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    chat_id=excluded.chat_id, stage=MAX(reactivation_progress.stage, excluded.stage),
                    updated_at=excluded.updated_at, migrated_at=excluded.migrated_at
                """,
                (source_phone, chat_id, _safe_int(row.get("stage")), row.get("updated_at"), migrated_at),
            )
            reactivation_count += 1

        followups_connection.execute(
            "INSERT OR IGNORE INTO migration_runs(source_kind, source_fingerprint, dry_run, counts_json, created_at) VALUES (?, ?, 0, ?, ?)",
            ("therapify-sqlite", fingerprint, json.dumps(source_counts, sort_keys=True), migrated_at),
        )
        followups_connection.commit()
        messages_connection.commit()
    except Exception as exc:
        with contextlib.suppress(sqlite3.Error):
            followups_connection.rollback()
        with contextlib.suppress(sqlite3.Error):
            messages_connection.rollback()
        migration_failure = exc
    finally:
        followups_connection.close()
        messages_connection.close()

    if migration_failure is not None:
        try:
            _rollback_targets(
                backups=backups,
                backup_root=backup_root,
                contacts_json=contacts_json,
                sales_json=sales_json,
                handoff_outbox=handoff_outbox,
                messages_db=messages_db,
                followups_db=followups_db,
            )
        except MigrationError as rollback_error:
            raise MigrationError("transação falhou e o rollback dos stores ficou incompleto") from rollback_error
        if isinstance(migration_failure, MigrationError):
            raise migration_failure
        raise MigrationError("transação de migração falhou; stores restaurados") from migration_failure

    try:
        with contacts_store.file_lock(contacts_json):
            _write_json_atomic(contacts_json, existing_contacts)
        sales_added, sales_skipped = _merge_sales(sales_json, rows["purchases"], leads_by_phone, owners)
        outbox_added = outbox_skipped = 0
        if activate_escalations:
            outbox_added, outbox_skipped = _merge_outbox(handoff_outbox, rows["escalations"], owners)
        _post_validate(messages_db, followups_db, contacts_json, sales_json)
    except Exception as exc:
        _rollback_targets(
            backups=backups,
            backup_root=backup_root,
            contacts_json=contacts_json,
            sales_json=sales_json,
            handoff_outbox=handoff_outbox,
            messages_db=messages_db,
            followups_db=followups_db,
        )
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError("validação pós-escrita falhou; stores restaurados") from exc
    target_after = _target_counts(messages_db, followups_db, contacts_json, sales_json)
    report.update(
        {
            "status": "success",
            "backups": backups,
            "backup_created": True,
            "migrated": {
                "contacts": migrated_contact_count,
                "leads": lead_count,
                "messages_inserted": message_count,
                "messages_skipped": message_skipped,
                **extension_counts,
                "settings": setting_count,
                "settings_redacted": redacted_settings,
                "reactivation_progress": reactivation_count,
                "sales_inserted": sales_added,
                "sales_skipped": sales_skipped,
                "escalations_enqueued": outbox_added,
                "escalations_not_enqueued": outbox_skipped,
                "owner_rows_skipped": skipped_owner,
            },
            "target_after": target_after,
        }
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migra SQLite Therapify para os stores do WhatsAYA")
    parser.add_argument("--source-db", "--source", dest="source_db", required=True, type=Path)
    parser.add_argument("--data-dir", default=Path("data"), type=Path)
    parser.add_argument("--contacts-json", type=Path)
    parser.add_argument("--messages-db", type=Path)
    parser.add_argument("--followups-db", type=Path)
    parser.add_argument("--sales-json", type=Path)
    parser.add_argument("--handoff-outbox", type=Path)
    parser.add_argument("--owner-number", action="append", default=[])
    parser.add_argument("--enable-automation", action="store_true")
    parser.add_argument("--activate-escalations", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_migration(
            source_db=args.source_db,
            data_dir=args.data_dir,
            contacts_json=args.contacts_json,
            messages_db=args.messages_db,
            followups_db=args.followups_db,
            sales_json=args.sales_json,
            handoff_outbox=args.handoff_outbox,
            owner_numbers=args.owner_number,
            enable_automation=args.enable_automation,
            activate_escalations=args.activate_escalations,
            dry_run=args.dry_run,
            backup_dir=args.backup_dir,
        )
    except MigrationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
