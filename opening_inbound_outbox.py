"""Fila durável por ID para mensagens recebidas durante a abertura Therapify."""
from __future__ import annotations

import sqlite3
import fcntl
import os
import threading
from functools import wraps
import time
import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path


_state_thread_lock = threading.RLock()
_state_held = threading.local()


@contextmanager
def opening_state_lock(root: str | Path):
    """Serializa revisão/ativação e mutações da abertura entre processos.

    Lock separado de contacts_store: nunca substitui os flocks dos arquivos.
    Chame antes dos locks de contato/cursor e nunca durante transporte HTTP.
    """
    path = Path(root) / "opening-state-coordination.lock"
    with _state_thread_lock:
        held = getattr(_state_held, "paths", {})
        key = str(path.resolve())
        if key in held:
            held[key] += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(fd)
                raise
            held[key] = 1
            _state_held.paths = held
        try:
            yield
        finally:
            held[key] -= 1
            if not held[key]:
                del held[key]
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


def _coordinate_outbox(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with opening_state_lock(self.path.parent):
            return method(self, *args, **kwargs)
    return guarded


def conversation_lock_path(root: str | Path, chat_id: str) -> Path:
    key = hashlib.sha256(str(chat_id).encode()).hexdigest()
    return Path(root) / ("opening-attempt-" + key)


class OpeningInboundOutbox:
    """Guarda entradas até abertura confirmada e confirma cada resposta por ID."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS opening_inbound_outbox (
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    opening_turn TEXT NOT NULL,
                    body TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    batch_key TEXT NOT NULL,
                    batch_index INTEGER NOT NULL,
                    close_at REAL NOT NULL,
                    opening_completed INTEGER NOT NULL,
                    manual_only INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    queue_id TEXT,
                    outbound_id TEXT,
                    turn_key TEXT,
                    attempt_id TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, message_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS opening_outbox_state ON opening_inbound_outbox(state, received_at)")
            conn.execute("CREATE TABLE IF NOT EXISTS opening_resolution_audit (id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL, version TEXT NOT NULL, decision TEXT NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL, occurred_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS opening_resume_intent (chat_id TEXT PRIMARY KEY, requested_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS opening_clearance (chat_id TEXT PRIMARY KEY, authorized_at REAL NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS opening_authorized_turn (turn_key TEXT PRIMARY KEY, chat_id TEXT NOT NULL, authorized_at REAL NOT NULL)")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @_coordinate_outbox
    def defer(self, chat_id: str, message_id: str, opening_turn: str, body: str, received_at: float) -> bool:
        if not all((chat_id, message_id, opening_turn, body.strip())) or received_at <= 0:
            raise ValueError("identidade e texto do inbound são obrigatórios")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO opening_inbound_outbox VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, 0, 'waiting', NULL, NULL, NULL, NULL, ?)",
                (chat_id, message_id, opening_turn, body, float(received_at), self._batch_key([message_id]), time.time(), time.time()),
            )
            return bool(cur.rowcount)

    @_coordinate_outbox
    def defer_batch(self, chat_id: str, opening_turn: str, parts: list[tuple[str, str]], received_at: float, *, coalesce_s: float = 0, initial_state: str = "waiting", manual_only: bool = False) -> None:
        if not chat_id or not opening_turn or received_at <= 0 or not parts or any(not mid or not body.strip() for mid, body in parts):
            raise ValueError("todos os fragmentos devem ter ID e texto")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ids = [mid for mid, _body in parts]
            placeholders = ",".join("?" for _ in ids)
            existing = conn.execute(
                f"SELECT message_id,batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id IN ({placeholders})",
                (chat_id, *ids),
            ).fetchall()
            if existing and len(existing) == len(ids):
                return
            if existing:
                raise ValueError("fragmentos repetidos pertencem a outro lote")
            now = time.time()
            previous = conn.execute(
                "SELECT batch_key, MAX(batch_index) AS idx, state FROM opening_inbound_outbox WHERE chat_id=? AND opening_turn=? AND state IN ('waiting','ready') AND close_at>? GROUP BY batch_key ORDER BY MAX(updated_at) DESC LIMIT 1",
                (chat_id, opening_turn, now),
            ).fetchone() if coalesce_s > 0 else None
            batch_key = previous["batch_key"] if previous else self._batch_key(ids)
            start = int(previous["idx"]) + 1 if previous else 0
            if initial_state not in {"waiting", "ready", "uncertain"}:
                raise ValueError("estado inicial inválido")
            state = previous["state"] if previous else initial_state
            close_at = now + max(0, float(coalesce_s))
            conn.execute("UPDATE opening_inbound_outbox SET close_at=?, updated_at=? WHERE chat_id=? AND batch_key=? AND state IN ('waiting','ready')", (close_at, now, chat_id, batch_key))
            conn.executemany(
                "INSERT OR IGNORE INTO opening_inbound_outbox VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?)",
                [(chat_id, mid, opening_turn, body, float(received_at), batch_key, start + index, close_at, int(initial_state == "ready" or bool(previous and previous["state"] == "ready")), int(manual_only), state, now)
                 for index, (mid, body) in enumerate(parts)],
            )

    @staticmethod
    def _batch_key(ids: list[str]) -> str:
        return hashlib.sha256("\0".join(ids).encode()).hexdigest()

    @_coordinate_outbox
    def mark_opening_complete(self, opening_turn: str, *, hold_for_resume: bool = False) -> int:
        with self._connect() as conn:
            return conn.execute(
                "UPDATE opening_inbound_outbox SET state=CASE WHEN state IN ('waiting','ready') THEN ? ELSE state END, opening_completed=1, updated_at=? WHERE opening_turn=? AND state IN ('waiting','ready','uncertain','approved_retry')",
                ("approved_retry" if hold_for_resume else "ready", time.time(), opening_turn),
            ).rowcount

    @_coordinate_outbox
    def mark_opening_uncertain(self, opening_turn: str) -> int:
        with self._connect() as conn:
            return conn.execute(
                "UPDATE opening_inbound_outbox SET state='uncertain', updated_at=? WHERE opening_turn=? AND state IN ('waiting','ready')",
                (time.time(), opening_turn),
            ).rowcount

    @_coordinate_outbox
    def flag_manual_review(self, chat_id: str) -> int:
        with self._connect() as conn:
            return conn.execute(
                "UPDATE opening_inbound_outbox SET state='uncertain', updated_at=? WHERE chat_id=? AND state IN ('waiting','ready')",
                (time.time(), chat_id),
            ).rowcount

    def contains_all(self, chat_id: str, ids: list[str]) -> bool:
        ids = list(dict.fromkeys(str(mid) for mid in ids if mid))
        if not ids:
            return True
        marks = ",".join("?" for _ in ids)
        with self._connect() as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM opening_inbound_outbox WHERE chat_id=? AND message_id IN ({marks})",
                (chat_id, *ids),
            ).fetchone()[0]
        return count == len(ids)

    def active_opening(self, chat_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT opening_turn,state FROM opening_inbound_outbox WHERE chat_id=? AND state NOT IN ('done','resolved_sent','cancelled') ORDER BY received_at,rowid LIMIT 1",
                (chat_id,),
            ).fetchone()
            return dict(row) if row else None

    def active_openings(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT chat_id FROM opening_inbound_outbox WHERE state NOT IN ('done','resolved_sent','cancelled') GROUP BY chat_id ORDER BY MIN(received_at)"
            )]

    def has_inflight(self, chat_id: str) -> bool:
        with self._connect() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM opening_inbound_outbox WHERE chat_id=? AND state IN ('dispatching','dispatched','processing') LIMIT 1", (chat_id,)
            ).fetchone())

    def attempt_is_processing(self, chat_id: str, message_id: str, attempt_id: str) -> bool:
        if not attempt_id:
            return False
        with self._connect() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM opening_inbound_outbox WHERE chat_id=? AND message_id=? AND attempt_id=? AND state='processing'", (chat_id, message_id, attempt_id)
            ).fetchone())

    @staticmethod
    def _version(rows: list[dict]) -> str:
        payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def uncertain_batches(self, chat_id: str, *, include_pending: bool = False) -> list[dict]:
        states = ("uncertain", "waiting", "ready") if include_pending else ("uncertain",)
        placeholders = ",".join("?" for _ in states)
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                f"SELECT message_id,batch_key,batch_index,body,state,manual_only,updated_at FROM opening_inbound_outbox WHERE chat_id=? AND state IN ({placeholders}) ORDER BY received_at,batch_index", (chat_id, *states)
            )]
        batches: dict[str, list[dict]] = {}
        for row in rows:
            batches.setdefault(row["batch_key"], []).append(row)
        return [{"kind": "deferred_reply", "item_id": group[0]["message_id"],
                 "version": self._version(group), "display_text": "\n".join(row["body"] for row in group),
                 "can_retry": all(row["state"] in {"waiting", "ready"} and not row["manual_only"] for row in group)}
                for group in batches.values()]

    @_coordinate_outbox
    def resolve_batch(self, chat_id: str, item_id: str, version: str, decision: str, actor: str) -> bool | str:
        if decision not in {"sent", "not_sent"} or not actor.strip():
            raise ValueError("decisão ou responsável inválido")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            key = conn.execute("SELECT batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id=? AND state IN ('uncertain','waiting','ready')", (chat_id, item_id)).fetchone()
            if not key:
                return False
            rows = [dict(r) for r in conn.execute(
                "SELECT message_id,batch_key,batch_index,body,state,manual_only,updated_at FROM opening_inbound_outbox WHERE chat_id=? AND batch_key=? AND state IN ('uncertain','waiting','ready') ORDER BY received_at,batch_index", (chat_id, key["batch_key"])
            )]
            if not rows or self._version(rows) != version:
                return False
            if decision == "not_sent" and any(row["manual_only"] for row in rows):
                conn.execute("INSERT INTO opening_resolution_audit(chat_id,kind,item_id,version,decision,actor,status,occurred_at) VALUES (?, 'deferred_reply', ?, ?, ?, ?, 'manual_required', ?)", (chat_id, item_id, version, decision, actor, time.time()))
                return "manual_required"
            if decision == "not_sent" and any(row["state"] == "uncertain" for row in rows):
                conn.execute("INSERT INTO opening_resolution_audit(chat_id,kind,item_id,version,decision,actor,status,occurred_at) VALUES (?, 'deferred_reply', ?, ?, ?, ?, 'manual_required', ?)", (chat_id, item_id, version, decision, actor, time.time()))
                return "manual_required"
            state = "resolved_sent" if decision == "sent" else "approved_retry"
            conn.execute("UPDATE opening_inbound_outbox SET state=?, updated_at=? WHERE chat_id=? AND batch_key=? AND state IN ('uncertain','waiting','ready')", (state, time.time(), chat_id, key["batch_key"]))
            conn.execute("INSERT INTO opening_resolution_audit(chat_id,kind,item_id,version,decision,actor,status,occurred_at) VALUES (?, 'deferred_reply', ?, ?, ?, ?, 'applied', ?)", (chat_id, item_id, version, decision, actor, time.time()))
            return True

    @_coordinate_outbox
    def request_resume(self, chat_id: str, turns: list[str] | None = None) -> None:
        with self._connect() as conn:
            now = time.time()
            conn.execute("INSERT INTO opening_resume_intent(chat_id,requested_at) VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET requested_at=excluded.requested_at", (chat_id, now))
            conn.execute("INSERT INTO opening_clearance(chat_id,authorized_at) VALUES (?,?) ON CONFLICT(chat_id) DO UPDATE SET authorized_at=excluded.authorized_at", (chat_id, now))
            for turn in turns or []:
                conn.execute("INSERT INTO opening_authorized_turn(turn_key,chat_id,authorized_at) VALUES (?,?,?) ON CONFLICT(turn_key) DO UPDATE SET authorized_at=excluded.authorized_at", (turn, chat_id, now))

    @_coordinate_outbox
    def consume_turn_authorization(self, turn_key: str) -> bool:
        with self._connect() as conn:
            return bool(conn.execute("DELETE FROM opening_authorized_turn WHERE turn_key=?", (turn_key,)).rowcount)

    def turn_authorized(self, turn_key: str) -> bool:
        with self._connect() as conn:
            return bool(conn.execute("SELECT 1 FROM opening_authorized_turn WHERE turn_key=?", (turn_key,)).fetchone())

    def resume_requested_at(self, chat_id: str) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT authorized_at FROM opening_clearance WHERE chat_id=?", (chat_id,)).fetchone()
            return float(row[0]) if row else 0.0

    def pending_resumes(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute("SELECT chat_id,requested_at FROM opening_resume_intent ORDER BY requested_at")]

    def approved_retry_turns(self, chat_id: str) -> list[str]:
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT message_id,batch_key,batch_index,body,turn_key FROM opening_inbound_outbox WHERE chat_id=? AND state='approved_retry' ORDER BY received_at,batch_index", (chat_id,)
            )]
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["batch_key"], []).append(row)
        result = []
        for rows in groups.values():
            turn_keys = {str(row["turn_key"]) for row in rows if row.get("turn_key")}
            if len(turn_keys) > 1:
                raise ValueError("lote contém chaves de turno conflitantes")
            result.extend(turn_keys)
        return result

    @_coordinate_outbox
    def consume_resume(self, chat_id: str, requested_at: float) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("DELETE FROM opening_resume_intent WHERE chat_id=? AND requested_at=?", (chat_id, requested_at))
            if cur.rowcount:
                conn.execute("UPDATE opening_inbound_outbox SET state=CASE WHEN opening_completed=1 THEN 'ready' ELSE 'waiting' END,close_at=?,updated_at=? WHERE chat_id=? AND state='approved_retry'", (time.time(), time.time(), chat_id))
            return bool(cur.rowcount)

    @_coordinate_outbox
    def claim_next(self, *, exclude_chat_ids: tuple[str, ...] = ()) -> dict | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            excluded = " AND a.chat_id NOT IN (" + ",".join("?" for _ in exclude_chat_ids) + ")" if exclude_chat_ids else ""
            row = conn.execute("""
                SELECT * FROM opening_inbound_outbox a WHERE state='ready' AND close_at<=?
                  AND NOT EXISTS (SELECT 1 FROM opening_inbound_outbox b
                    WHERE b.chat_id=a.chat_id AND b.state IN ('dispatching','dispatched','processing','uncertain','approved_retry'))
            """ + excluded + " ORDER BY received_at, rowid LIMIT 1", (time.time(), *exclude_chat_ids)).fetchone()
            if not row:
                return None
            members = conn.execute(
                "SELECT message_id,body FROM opening_inbound_outbox WHERE chat_id=? AND batch_key=? AND state='ready' ORDER BY batch_index",
                (row['chat_id'], row['batch_key']),
            ).fetchall()
            attempt_id = uuid.uuid4().hex
            conn.execute("UPDATE opening_inbound_outbox SET state='dispatching', attempt_id=?, updated_at=? WHERE chat_id=? AND batch_key=? AND state='ready'", (attempt_id, time.time(), row['chat_id'], row['batch_key']))
            item = dict(row)
            item['attempt_id'] = attempt_id
            item['message_ids'] = [member['message_id'] for member in members]
            item['body_parts'] = [member['body'] for member in members]
            item['body'] = "\n".join(item['body_parts'])
            return item

    @_coordinate_outbox
    def dispatch_result(self, chat_id: str, message_id: str, *, queue_id: str = "", retry: bool = False, attempt_id: str = "") -> bool:
        state = "dispatched" if queue_id else "ready" if retry else "uncertain"
        with self._connect() as conn:
            # ACK may arrive before the HTTP result; never regress it.
            return bool(conn.execute(
                "UPDATE opening_inbound_outbox SET state=?, queue_id=?, updated_at=? WHERE chat_id=? AND batch_key=(SELECT batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id=?) AND state='dispatching' AND (?='' OR attempt_id=?)",
                (state, queue_id or None, time.time(), chat_id, chat_id, message_id, attempt_id, attempt_id),
            ).rowcount)

    @_coordinate_outbox
    def acknowledge(self, chat_id: str, message_id: str, outbound_id: str, *, attempt_id: str = "") -> bool:
        if not outbound_id:
            return False
        with self._connect() as conn:
            return bool(conn.execute(
                "UPDATE opening_inbound_outbox SET state='done', outbound_id=?, updated_at=? WHERE chat_id=? AND batch_key=(SELECT batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id=?) AND state IN ('dispatching','dispatched','processing','uncertain','approved_retry','ready') AND (?='' OR attempt_id=?)",
                (outbound_id, time.time(), chat_id, chat_id, message_id, attempt_id, attempt_id),
            ).rowcount)

    @_coordinate_outbox
    def claim_processing(self, chat_id: str, message_id: str, *, attempt_id: str = "") -> bool:
        with self._connect() as conn:
            return bool(conn.execute(
                "UPDATE opening_inbound_outbox SET state='processing', updated_at=? WHERE chat_id=? AND batch_key=(SELECT batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id=?) AND state IN ('dispatching','dispatched') AND (?='' OR attempt_id=?)",
                (time.time(), chat_id, chat_id, message_id, attempt_id, attempt_id),
            ).rowcount)

    @_coordinate_outbox
    def bind_turn(self, chat_id: str, message_id: str, turn_key: str, *, attempt_id: str = "") -> bool:
        if not turn_key:
            return False
        with self._connect() as conn:
            return bool(conn.execute(
                "UPDATE opening_inbound_outbox SET turn_key=?,updated_at=? WHERE chat_id=? AND batch_key=(SELECT batch_key FROM opening_inbound_outbox WHERE chat_id=? AND message_id=?) AND state='processing' AND (?='' OR attempt_id=?)",
                (turn_key, time.time(), chat_id, chat_id, message_id, attempt_id, attempt_id),
            ).rowcount)

    @_coordinate_outbox
    def mark_expired_uncertain(self, *, before: float) -> list[dict]:
        """Uma fila/entrega sem ACK após queda exige conciliação, não retry cego."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM opening_inbound_outbox WHERE state IN ('dispatching','dispatched','processing') AND updated_at < ? GROUP BY chat_id,batch_key",
                (float(before),),
            )]
            conn.execute(
                "UPDATE opening_inbound_outbox SET state='uncertain', updated_at=? WHERE state IN ('dispatching','dispatched','processing') AND updated_at < ?",
                (time.time(), float(before)),
            )
            return rows

    def waiting_openings(self, *, before: float) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT chat_id, opening_turn FROM opening_inbound_outbox WHERE state='waiting' AND updated_at < ? GROUP BY chat_id, opening_turn",
                (float(before),),
            )]
