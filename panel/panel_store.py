"""Estado próprio do painel: quem mandou cada mensagem enviada por ele.

Módulo puro no molde de `management_store.py`: abre conexão curta no
`panel.db` e fecha, não importa o plugin. Existe porque
`_mark_conversation_owners` (`panel/data.py`) só distingue dono × AYA pelo
log `[human-send]` do plugin, e uma resposta mandada pelo painel nunca passa
por ali — sem essa tabela, a mensagem do painel viraria "aya" na timeline
num dia sem nenhum envio da AYA naquele chat.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbound_messages (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_by TEXT NOT NULL,
    sent_by_user TEXT NOT NULL,
    sent_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_chat ON outbound_messages(chat_id);
"""


def _connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    # Mesmo cuidado do `management_store`: o arquivo mora ao lado de bancos com
    # dado de cliente, só o dono do processo lê.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return conn


def ensure_schema(conn_or_path: sqlite3.Connection | Path | str) -> None:
    if isinstance(conn_or_path, sqlite3.Connection):
        conn_or_path.executescript(SCHEMA)
        return
    conn = _connect(conn_or_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def record_outbound(
    db_path: Path | str, *, message_id: str, chat_id: str, body: str,
    sent_by: str, sent_by_user: str, sent_utc: str,
) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR REPLACE INTO outbound_messages"
            " (message_id, chat_id, body, sent_by, sent_by_user, sent_utc)"
            " VALUES (?,?,?,?,?,?)",
            (message_id, chat_id, body, sent_by, sent_by_user, sent_utc),
        )
        conn.commit()
    finally:
        conn.close()


def outbound_for_chats(db_path: Path | str, chat_ids: list[str]) -> dict[str, dict[str, Any]]:
    """`message_id` -> linha, para as conversas dadas. Nunca cria o arquivo à toa
    — leitura de tela não deve materializar um banco vazio."""
    if not chat_ids or not Path(db_path).is_file():
        return {}
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        placeholders = ",".join("?" for _ in chat_ids)
        rows = conn.execute(
            f"SELECT * FROM outbound_messages WHERE chat_id IN ({placeholders})",
            chat_ids,
        ).fetchall()
        return {str(row["message_id"]): dict(row) for row in rows}
    finally:
        conn.close()
