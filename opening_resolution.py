"""Resolução explícita de entregas incertas da abertura, acionada pelo painel."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import contacts_store
from opening_inbound_outbox import OpeningInboundOutbox, conversation_lock_path, opening_state_lock


def _root(paths) -> Path:
    return Path(paths.followups_db).parent


def _cursor_path(paths) -> Path:
    return _root(paths) / "partial_reply_state.json"


def _outbox(paths) -> OpeningInboundOutbox:
    return OpeningInboundOutbox(_root(paths) / "opening_inbound_outbox.db")


def _read_cursors(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("estado de abertura inválido")
    return value


def _version(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _parts(text: str) -> list[str]:
    return [part.strip() for part in str(text).split("\n\n") if part.strip()]


def review_chat_ids(paths) -> list[str]:
    """Identidades com cursores ou entradas ainda não resolvidas, sem criá-las."""
    ids: set[str] = set()
    cursor_path = _cursor_path(paths)
    if cursor_path.is_file():
        with contacts_store.file_lock(cursor_path):
            records = _read_cursors(cursor_path)
        ids.update(str(record.get("chat_id")) for record in records.values()
                   if isinstance(record, dict) and record.get("opening") and record.get("chat_id"))
    outbox_path = _root(paths) / "opening_inbound_outbox.db"
    if outbox_path.is_file():
        conn = sqlite3.connect(f"file:{outbox_path}?mode=ro", uri=True, timeout=5)
        try:
            ids.update(str(row[0]) for row in conn.execute(
                "SELECT DISTINCT chat_id FROM opening_inbound_outbox WHERE state NOT IN ('done','resolved_sent','cancelled')"
            ) if row[0])
        finally:
            conn.close()
    return sorted(ids)


def inspect(paths, chat_id: str, *, include_pending: bool = False) -> dict:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise ValueError("conversa inválida")
    items = []
    cursor_path = _cursor_path(paths)
    if cursor_path.is_file():
        with contacts_store.file_lock(cursor_path):
            records = _read_cursors(cursor_path)
        for key, record in records.items():
            if isinstance(record, dict) and record.get("opening") and record.get("send_in_flight") and record.get("chat_id") == chat_id:
                parts = _parts(record.get("remaining_text") or "")
                if not parts:
                    raise ValueError("cursor de abertura sem bolha")
                items.append({"kind": "opening_bubble", "item_id": key, "version": _version(record), "display_text": parts[0], "can_retry": False})
    if (_root(paths) / "opening_inbound_outbox.db").is_file():
        contacts_path = getattr(paths, "contacts_json", None)
        if contacts_path and Path(contacts_path).is_file():
            records = contacts_store.read_contacts(contacts_path)
            contact = records.get(chat_id) if isinstance(records, dict) else None
            include_pending = include_pending or (isinstance(contact, dict) and contact.get("ai_enabled") is False)
        items.extend(_outbox(paths).uncertain_batches(chat_id, include_pending=include_pending))
    return {"items": items}


def _audit(outbox: OpeningInboundOutbox, chat_id: str, kind: str, item_id: str, version: str, decision: str, actor: str, status: str) -> None:
    with outbox._connect() as conn:
        conn.execute("INSERT INTO opening_resolution_audit(chat_id,kind,item_id,version,decision,actor,status,occurred_at) VALUES (?,?,?,?,?,?,?,?)",
                     (chat_id, kind, item_id, version, decision, actor, status, time.time()))


def _pending_decision(outbox: OpeningInboundOutbox, chat_id: str, item_id: str, version: str) -> str:
    with outbox._connect() as conn:
        row = conn.execute(
            "SELECT decision FROM opening_resolution_audit WHERE chat_id=? AND kind='opening_bubble' AND item_id=? AND version=? AND status='requested' ORDER BY id LIMIT 1",
            (chat_id, item_id, version),
        ).fetchone()
        return str(row[0]) if row else ""


def _write_cursors(path: Path, records: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def resolve(paths, chat_id: str, kind: str, item_id: str, version: str, decision: str, actor: str) -> dict:
    with opening_state_lock(_root(paths)):
        return _resolve_locked(paths, chat_id, kind, item_id, version, decision, actor)


def _resolve_locked(paths, chat_id: str, kind: str, item_id: str, version: str, decision: str, actor: str) -> dict:
    if not chat_id or not item_id or not actor or decision not in {"sent", "not_sent"}:
        raise ValueError("dados de resolução inválidos")
    outbox = _outbox(paths)
    if kind == "deferred_reply":
        with contacts_store.file_lock(conversation_lock_path(_root(paths), chat_id)):
            result = outbox.resolve_batch(chat_id, item_id, version, decision, actor)
            if result == "manual_required":
                return {"resolved": False, "manual_required": True}
            if not result:
                raise ValueError("o item mudou; atualize a conversa e confira novamente")
        return {"resolved": True}
    if kind != "opening_bubble":
        raise ValueError("tipo de resolução inválido")
    path = _cursor_path(paths)
    with contacts_store.file_lock(path):
        records = _read_cursors(path)
        record = records.get(item_id)
        if (not isinstance(record, dict) or record.get("chat_id") != chat_id
                or not record.get("opening") or not record.get("send_in_flight")
                or _version(record) != version):
            raise ValueError("o item mudou; atualize a conversa e confira novamente")
        parts = _parts(record.get("remaining_text") or "")
        if not parts:
            raise ValueError("cursor de abertura sem bolha")
        if decision == "not_sent":
            _audit(outbox, chat_id, kind, item_id, version, decision, actor, "manual_required")
            return {"resolved": False, "manual_required": True}
        previous = _pending_decision(outbox, chat_id, item_id, version)
        if previous and previous != decision:
            raise ValueError("há uma decisão anterior registrada; confirme novamente a mesma escolha")
        if not previous:
            _audit(outbox, chat_id, kind, item_id, version, decision, actor, "requested")
        if decision == "sent":
            parts = parts[1:]
        if parts:
            record["remaining_text"] = "\n\n".join(parts)
            record["send_in_flight"] = False
            record["resolved_pending_resume"] = True
            record["updated_at"] = time.time()
            records[item_id] = record
        else:
            # O operador confirmou a última bolha; entradas posteriores já podem
            # aguardar a retomada, mas nunca antes dessa decisão.
            outbox.mark_opening_complete(item_id, hold_for_resume=True)
            records.pop(item_id, None)
        _write_cursors(path, records)
        _audit(outbox, chat_id, kind, item_id, version, decision, actor, "applied")
    return {"resolved": True}


def resume_pending(paths, chat_id: str) -> dict:
    if inspect(paths, chat_id)["items"]:
        raise ValueError("resolva os envios incertos antes de retomar")
    if (_root(paths) / "opening_inbound_outbox.db").is_file() and _outbox(paths).has_inflight(chat_id):
        raise ValueError("há resposta em processamento; aguarde a confirmação antes de retomar")
    path = _cursor_path(paths)
    turns = []
    if path.is_file():
        with contacts_store.file_lock(path):
            records = _read_cursors(path)
            turns = [key for key, record in records.items() if isinstance(record, dict)
                     and record.get("opening") and record.get("chat_id") == chat_id
                     and not record.get("send_in_flight")]
    outbox = _outbox(paths)
    turns.extend(outbox.approved_retry_turns(chat_id))
    outbox.request_resume(chat_id, list(dict.fromkeys(turns)))
    return {"requested": True}
