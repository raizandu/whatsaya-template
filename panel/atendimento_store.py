"""Atendimentos no `panel.db`: episódio de atenção a um contato, com protocolo,
responsável e eventos (vocabulário em `CONTEXT.md`, decisão em ADR 0001).

Módulo puro no molde de `panel_store.py`: abre conexão curta e fecha, não
importa o plugin nem o servidor. Quem decide o que abrir, resolver ou
devolver é `atendimento_reconcile.py`; aqui só a forma e a integridade.

`rev` é um contador global do banco que avança a cada escrita; a listagem
aceita `desde_rev` para o polling do painel não reenviar tudo.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import daily_audit
from panel_store import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS atendimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo TEXT NOT NULL UNIQUE,
    contato TEXT NOT NULL,
    canal TEXT NOT NULL DEFAULT 'whatsapp',
    status TEXT NOT NULL,
    responsavel_tipo TEXT NOT NULL,
    responsavel_user TEXT,
    aberto_utc TEXT NOT NULL,
    primeira_resposta_utc TEXT,
    primeira_resposta_autor TEXT,
    primeira_resposta_user TEXT,
    assumido_utc TEXT,
    handoff_utc TEXT,
    resolvido_utc TEXT,
    resolvido_motivo TEXT,
    ultima_msg_utc TEXT,
    ultima_msg_autor TEXT,
    rev INTEGER NOT NULL,
    updated_utc TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_atendimentos_aberto
    ON atendimentos(contato) WHERE status = 'aberto';
CREATE INDEX IF NOT EXISTS idx_atendimentos_contato ON atendimentos(contato, id);
CREATE TABLE IF NOT EXISTS atendimento_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id),
    tipo TEXT NOT NULL,
    ator TEXT NOT NULL,
    detalhe TEXT,
    at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_atendimento_eventos_atd ON atendimento_eventos(atendimento_id, id);
CREATE TABLE IF NOT EXISTS atendimento_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

STATUS = ("aberto", "resolvido")
RESPONSAVEIS = ("ia", "atendente", "dono", "nenhum")
HUMANOS = ("atendente", "dono")
MOTIVOS_RESOLUCAO = ("manual", "inatividade", "bloqueio")


class AtendimentoAberto(ValueError):
    """Já existe atendimento aberto para o contato."""


def _iso(value: datetime | None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def ensure_schema(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _write(db_path: Path | str) -> Iterator[tuple[sqlite3.Connection, int]]:
    """Transação exclusiva que já avança o `rev`; devolve (conexão, rev novo)."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT value FROM atendimento_meta WHERE key='rev'").fetchone()
        new_rev = int(current["value"]) + 1 if current else 1
        conn.execute("INSERT OR REPLACE INTO atendimento_meta(key, value) VALUES ('rev', ?)", (str(new_rev),))
        yield conn, new_rev
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _read(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        yield conn
    finally:
        conn.close()


def _row(conn: sqlite3.Connection, atendimento_id: int) -> dict:
    row = conn.execute("SELECT * FROM atendimentos WHERE id=?", (int(atendimento_id),)).fetchone()
    if row is None:
        raise KeyError(f"atendimento {atendimento_id} não existe")
    return dict(row)


def _evento(conn: sqlite3.Connection, atendimento_id: int, tipo: str, ator: str, detalhe: str | None, at: datetime) -> None:
    conn.execute(
        "INSERT INTO atendimento_eventos(atendimento_id, tipo, ator, detalhe, at_utc) VALUES (?,?,?,?,?)",
        (int(atendimento_id), tipo, ator or "sistema", detalhe, _iso(at)),
    )


def _proximo_protocolo(conn: sqlite3.Connection, aberto_at: datetime) -> str:
    """`AAAAMMDD-NNN`, sequencial por dia comercial da instalação."""
    dia = aberto_at.astimezone(daily_audit.business_tz()).strftime("%Y%m%d")
    ultimo = conn.execute(
        "SELECT protocolo FROM atendimentos WHERE protocolo LIKE ? ORDER BY protocolo DESC LIMIT 1",
        (f"{dia}-%",),
    ).fetchone()
    seq = int(str(ultimo["protocolo"]).rsplit("-", 1)[1]) + 1 if ultimo else 1
    return f"{dia}-{seq:03d}"


def abrir(
    db_path: Path | str, *, contato: str, responsavel_tipo: str, aberto_at: datetime,
    responsavel_user: str | None = None, canal: str = "whatsapp", now: datetime | None = None,
    ultima_msg_autor: str | None = None,
) -> dict:
    if responsavel_tipo not in RESPONSAVEIS:
        raise ValueError(f"responsável inválido: {responsavel_tipo!r}")
    with _write(db_path) as (conn, rev):
        if conn.execute("SELECT 1 FROM atendimentos WHERE contato=? AND status='aberto'", (contato,)).fetchone():
            raise AtendimentoAberto(contato)
        cur = conn.execute(
            "INSERT INTO atendimentos(protocolo, contato, canal, status, responsavel_tipo, responsavel_user,"
            " aberto_utc, ultima_msg_utc, ultima_msg_autor, rev, updated_utc)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                _proximo_protocolo(conn, aberto_at), contato, canal, "aberto", responsavel_tipo,
                responsavel_user, _iso(aberto_at), _iso(aberto_at) if ultima_msg_autor else None,
                ultima_msg_autor, rev, _iso(now),
            ),
        )
        _evento(conn, cur.lastrowid, "aberto", "sistema", None, aberto_at)
        return _row(conn, cur.lastrowid)


def _atualizar(conn: sqlite3.Connection, rev: int, atendimento_id: int, now: datetime | None, **campos: Any) -> dict:
    campos["rev"] = rev
    campos["updated_utc"] = _iso(now)
    sets = ", ".join(f"{k}=?" for k in campos)
    conn.execute(f"UPDATE atendimentos SET {sets} WHERE id=?", (*campos.values(), int(atendimento_id)))
    return _row(conn, atendimento_id)


def definir_responsavel(
    db_path: Path | str, atendimento_id: int, *, tipo: str, user: str | None, ator: str,
    evento: str, detalhe: str | None = None, now: datetime | None = None,
) -> dict:
    """Assumir, devolver, reatribuir ou tirar responsável; o `evento` diz qual."""
    if tipo not in RESPONSAVEIS:
        raise ValueError(f"responsável inválido: {tipo!r}")
    at = now or datetime.now(timezone.utc)
    with _write(db_path) as (conn, rev):
        row = _atualizar(
            conn, rev, atendimento_id, at,
            responsavel_tipo=tipo,
            responsavel_user=user if tipo == "atendente" else None,
            assumido_utc=_iso(at) if tipo in HUMANOS else None,
            handoff_utc=None if tipo != "nenhum" else _row(conn, atendimento_id)["handoff_utc"],
        )
        _evento(conn, atendimento_id, evento, ator, detalhe, at)
        return row


def marcar_handoff(db_path: Path | str, atendimento_id: int, *, ator: str = "ia", detalhe: str | None = None, now: datetime | None = None) -> dict:
    """A IA pediu um humano: fica sem responsável até alguém assumir, devolver ou o prazo expirar."""
    at = now or datetime.now(timezone.utc)
    with _write(db_path) as (conn, rev):
        row = _atualizar(conn, rev, atendimento_id, at, responsavel_tipo="nenhum", responsavel_user=None, assumido_utc=None, handoff_utc=_iso(at))
        _evento(conn, atendimento_id, "handoff", ator, detalhe, at)
        return row


def resolver(db_path: Path | str, atendimento_id: int, *, motivo: str, ator: str, now: datetime | None = None) -> dict:
    if motivo not in MOTIVOS_RESOLUCAO:
        raise ValueError(f"motivo inválido: {motivo!r}")
    at = now or datetime.now(timezone.utc)
    with _write(db_path) as (conn, rev):
        atual = _row(conn, atendimento_id)
        if atual["status"] == "resolvido":
            return atual
        row = _atualizar(conn, rev, atendimento_id, at, status="resolvido", resolvido_utc=_iso(at), resolvido_motivo=motivo)
        _evento(conn, atendimento_id, "resolvido", ator, motivo, at)
        return row


def registrar_mensagem(db_path: Path | str, atendimento_id: int, *, at: datetime, autor: str, user: str | None, now: datetime | None = None) -> dict:
    """Carimba primeira resposta (qualquer autor que não o contato) e última mensagem.
    Mensagem mais antiga que a última já vista não retrocede nada (replay do histórico)."""
    with _write(db_path) as (conn, rev):
        atual = _row(conn, atendimento_id)
        campos: dict[str, Any] = {}
        if autor != "contato" and not atual["primeira_resposta_utc"]:
            campos["primeira_resposta_utc"] = _iso(at)
            campos["primeira_resposta_autor"] = autor
            campos["primeira_resposta_user"] = user
        if not atual["ultima_msg_utc"] or _iso(at) > atual["ultima_msg_utc"]:
            campos["ultima_msg_utc"] = _iso(at)
            campos["ultima_msg_autor"] = autor
        if not campos:
            return atual
        return _atualizar(conn, rev, atendimento_id, now, **campos)


def adicionar_evento(db_path: Path | str, atendimento_id: int, *, tipo: str, ator: str, detalhe: str | None = None, now: datetime | None = None) -> None:
    with _write(db_path) as (conn, rev):
        _atualizar(conn, rev, atendimento_id, now)
        _evento(conn, atendimento_id, tipo, ator, detalhe, now or datetime.now(timezone.utc))


def obter(db_path: Path | str, atendimento_id: int) -> dict | None:
    with _read(db_path) as conn:
        try:
            return _row(conn, atendimento_id)
        except KeyError:
            return None


def listar_abertos(db_path: Path | str, *, desde_rev: int | None = None) -> list[dict]:
    with _read(db_path) as conn:
        if desde_rev is None:
            rows = conn.execute("SELECT * FROM atendimentos WHERE status='aberto' ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM atendimentos WHERE status='aberto' AND rev > ? ORDER BY id", (int(desde_rev),)).fetchall()
        return [dict(r) for r in rows]


def aberto_do_contato(db_path: Path | str, contato: str) -> dict | None:
    with _read(db_path) as conn:
        row = conn.execute("SELECT * FROM atendimentos WHERE contato=? AND status='aberto'", (contato,)).fetchone()
        return dict(row) if row else None


def listar_do_contato(db_path: Path | str, contato: str, *, limit: int = 50) -> list[dict]:
    """Histórico do contato, mais recente primeiro."""
    with _read(db_path) as conn:
        rows = conn.execute("SELECT * FROM atendimentos WHERE contato=? ORDER BY id DESC LIMIT ?", (contato, int(limit))).fetchall()
        return [dict(r) for r in rows]


def eventos(db_path: Path | str, atendimento_id: int) -> list[dict]:
    with _read(db_path) as conn:
        rows = conn.execute("SELECT * FROM atendimento_eventos WHERE atendimento_id=? ORDER BY id", (int(atendimento_id),)).fetchall()
        return [dict(r) for r in rows]


def rev(db_path: Path | str) -> int:
    with _read(db_path) as conn:
        row = conn.execute("SELECT value FROM atendimento_meta WHERE key='rev'").fetchone()
        return int(row["value"]) if row else 0


def meta_get(db_path: Path | str, key: str) -> str | None:
    with _read(db_path) as conn:
        row = conn.execute("SELECT value FROM atendimento_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def meta_set(db_path: Path | str, key: str, value: str) -> None:
    """Cursor da reconciliação e afins. Não passa por `_write` de propósito: não é
    mudança de atendimento e não deve avançar o `rev` do polling."""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR REPLACE INTO atendimento_meta(key, value) VALUES (?,?)", (key, value))
        conn.commit()
    finally:
        conn.close()
