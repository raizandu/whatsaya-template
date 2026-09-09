"""Lista de reativação manual por etiqueta do WhatsApp Business.

O dono marca conversas antigas com uma etiqueta (padrão "remarketing") no
WhatsApp Business; o painel prepara essas conversas nesta lista e ele manda a
primeira mensagem manualmente, pelo próprio celular — nada é enviado daqui.
Esse primeiro envio não pode contar como takeover humano (ver
`consume_first_manual`): o gate de silêncio do bridge é liberado sem que o
lead saia do fluxo automático assim que responder.

Tabela própria no mesmo SQLite operacional do `FollowupEngine`
(`commercial_followups.db`), mas sem nenhuma dependência dele — módulo puro,
sem estado em memória, só funções que abrem conexão curta e fecham.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS manual_reactivation (
  chat_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  prepared_utc TEXT NOT NULL,
  message TEXT,
  message_utc TEXT,
  message_variant INTEGER NOT NULL DEFAULT 0,
  sent_utc TEXT,
  first_manual_pending INTEGER NOT NULL DEFAULT 1,
  first_manual_consumed_utc TEXT,
  updated_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manual_reactivation_sent
    ON manual_reactivation(sent_utc, prepared_utc);
"""


def _ensure_utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("datetime precisa ter timezone")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _ensure_utc(value).isoformat(timespec="seconds")


def _canonical_chat_id(chat_id: str) -> str:
    """JID de telefone canônico. Rejeita `@lid` — quem chama já devia ter resolvido
    pro telefone antes (o painel faz isso via `canonicalChatId` do bridge)."""
    raw = str(chat_id or "").strip()
    if not raw:
        raise ValueError("chat_id vazio")
    if raw.endswith("@lid"):
        raise ValueError(f"chat_id LID não pode ser usado diretamente aqui: {raw!r}")
    if "@" not in raw:
        digits = "".join(c for c in raw if c.isdigit())
        if not digits:
            raise ValueError(f"chat_id inválido: {raw!r}")
        return f"{digits}@s.whatsapp.net"
    return raw


def _connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _read(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _write(db_path: Path | str) -> Iterator[sqlite3.Connection]:
    """Transação curta e exclusiva (BEGIN IMMEDIATE), como o `_tx` do FollowupEngine."""
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def ensure_schema(conn_or_path: sqlite3.Connection | Path | str) -> None:
    """Cria `manual_reactivation` se não existir. Idempotente, chamável à vontade."""
    if isinstance(conn_or_path, sqlite3.Connection):
        conn_or_path.executescript(SCHEMA)
        return
    conn = _connect(conn_or_path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def prepare(
    db_path: Path | str,
    chat_ids: Iterable[str],
    *,
    label: str,
    now: datetime | None = None,
) -> dict:
    """Adiciona chats à lista de reativação (idempotente).

    Chat novo: insere pendente. Chat já pendente (sent_utc NULL): rearma
    `first_manual_pending` e atualiza a etiqueta, mas nunca mexe em
    `prepared_utc`/`message`/`sent_utc`. Chat já contatado: intocado — um
    segundo envio manual pra quem já foi contatado é takeover de verdade.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("label vazio")
    ts = _iso(_ensure_utc(now))

    canonical_ids: list[str] = []
    seen: set[str] = set()
    for raw in chat_ids:
        chat_id = _canonical_chat_id(raw)
        if chat_id in seen:
            continue
        seen.add(chat_id)
        canonical_ids.append(chat_id)

    ensure_schema(db_path)
    added = 0
    rearmed = 0
    with _write(db_path) as conn:
        for chat_id in canonical_ids:
            row = conn.execute(
                "SELECT sent_utc FROM manual_reactivation WHERE chat_id=?", (chat_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO manual_reactivation (chat_id, label, prepared_utc, updated_utc) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, label, ts, ts),
                )
                added += 1
            elif row["sent_utc"] is None:
                conn.execute(
                    "UPDATE manual_reactivation SET label=?, first_manual_pending=1, updated_utc=? "
                    "WHERE chat_id=?",
                    (label, ts, chat_id),
                )
                rearmed += 1
    return {"added": added, "rearmed": rearmed, "total": len(canonical_ids)}


def list_entries(db_path: Path | str) -> dict:
    """`{"pending": [...], "sent": [...]}` — pendentes do mais antigo pro mais novo
    preparado, contatados do envio mais recente pro mais antigo."""
    with _read(db_path) as conn:
        pending = conn.execute(
            "SELECT * FROM manual_reactivation WHERE sent_utc IS NULL "
            "ORDER BY prepared_utc ASC"
        ).fetchall()
        sent = conn.execute(
            "SELECT * FROM manual_reactivation WHERE sent_utc IS NOT NULL "
            "ORDER BY sent_utc DESC"
        ).fetchall()
    return {"pending": [dict(row) for row in pending], "sent": [dict(row) for row in sent]}


def get_entry(db_path: Path | str, chat_id: str) -> dict | None:
    canonical = _canonical_chat_id(chat_id)
    with _read(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM manual_reactivation WHERE chat_id=?", (canonical,)
        ).fetchone()
    return dict(row) if row else None


def set_message(
    db_path: Path | str,
    chat_id: str,
    message: str,
    *,
    variant: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Salva o texto (editado ou sugerido). Vazio limpa a mensagem. Levanta
    `KeyError` se o chat não estiver preparado."""
    canonical = _canonical_chat_id(chat_id)
    text = (message or "").strip()[:1000]
    ts = _iso(_ensure_utc(now))
    with _write(db_path) as conn:
        row = conn.execute(
            "SELECT chat_id FROM manual_reactivation WHERE chat_id=?", (canonical,)
        ).fetchone()
        if row is None:
            raise KeyError(canonical)
        if variant is None:
            conn.execute(
                "UPDATE manual_reactivation SET message=?, message_utc=?, updated_utc=? "
                "WHERE chat_id=?",
                (text, ts, ts, canonical),
            )
        else:
            conn.execute(
                "UPDATE manual_reactivation SET message=?, message_utc=?, message_variant=?, "
                "updated_utc=? WHERE chat_id=?",
                (text, ts, int(variant), ts, canonical),
            )
        updated = conn.execute(
            "SELECT * FROM manual_reactivation WHERE chat_id=?", (canonical,)
        ).fetchone()
    return dict(updated)


def mark_sent(db_path: Path | str, chat_id: str, *, sent: bool, now: datetime | None = None) -> dict:
    """Marca/desmarca "mandei". Marcar também limpa `first_manual_pending` (o dono
    confirmou o envio; se o eco chegar depois não precisa de tratamento especial —
    quem faz o trabalho de verdade é `consume_first_manual`). Desmarcar rearma."""
    canonical = _canonical_chat_id(chat_id)
    ts = _iso(_ensure_utc(now))
    with _write(db_path) as conn:
        row = conn.execute(
            "SELECT chat_id FROM manual_reactivation WHERE chat_id=?", (canonical,)
        ).fetchone()
        if row is None:
            raise KeyError(canonical)
        if sent:
            conn.execute(
                "UPDATE manual_reactivation SET sent_utc=?, first_manual_pending=0, updated_utc=? "
                "WHERE chat_id=?",
                (ts, ts, canonical),
            )
        else:
            conn.execute(
                "UPDATE manual_reactivation SET sent_utc=NULL, first_manual_pending=1, updated_utc=? "
                "WHERE chat_id=?",
                (ts, canonical),
            )
        updated = conn.execute(
            "SELECT * FROM manual_reactivation WHERE chat_id=?", (canonical,)
        ).fetchone()
    return dict(updated)


def consume_first_manual(
    db_path: Path | str, chat_ids: Iterable[str], *, now: datetime | None = None
) -> str | None:
    """Consome o flag one-shot de "primeiro envio manual" pra QUALQUER um dos
    aliases dados (telefone e/ou LID do mesmo contato — quem chama não precisa
    saber qual alias bate). Atômico: a segunda chamada, mesmo em paralelo,
    retorna None — a checagem e a gravação vivem na mesma transação exclusiva.

    Tolera tabela ausente (instalação sem a feature de reativação ainda usada):
    retorna None em vez de propagar o erro, pra nunca quebrar o caminho normal
    de takeover no plugin.
    """
    aliases = [str(c).strip() for c in chat_ids if str(c or "").strip()]
    if not aliases:
        return None
    ts = _iso(_ensure_utc(now))
    placeholders = ",".join("?" for _ in aliases)
    try:
        with _write(db_path) as conn:
            row = conn.execute(
                f"SELECT chat_id FROM manual_reactivation "
                f"WHERE chat_id IN ({placeholders}) AND first_manual_pending=1 LIMIT 1",
                aliases,
            ).fetchone()
            if row is None:
                return None
            chat_id = row["chat_id"]
            conn.execute(
                "UPDATE manual_reactivation SET first_manual_pending=0, "
                "first_manual_consumed_utc=?, sent_utc=COALESCE(sent_utc, ?), updated_utc=? "
                "WHERE chat_id=? AND first_manual_pending=1",
                (ts, ts, ts, chat_id),
            )
            return chat_id
    except sqlite3.OperationalError as err:
        if "no such table" in str(err):
            return None
        raise


def first_manual_pending(db_path: Path | str, chat_ids: Iterable[str] | str) -> bool:
    """Helper de leitura: algum dos aliases dados ainda está com o flag armado?"""
    ids = [chat_ids] if isinstance(chat_ids, str) else list(chat_ids)
    aliases = [str(c).strip() for c in ids if str(c or "").strip()]
    if not aliases:
        return False
    placeholders = ",".join("?" for _ in aliases)
    with _read(db_path) as conn:
        row = conn.execute(
            f"SELECT 1 FROM manual_reactivation "
            f"WHERE chat_id IN ({placeholders}) AND first_manual_pending=1 LIMIT 1",
            aliases,
        ).fetchone()
    return row is not None


# Sugestão de mensagem — reescrita determinística, sem rede e sem LLM. Só
# reabre o papo em tom baixa pressão; NUNCA inventa preço, link, garantia ou
# qualquer conteúdo que não esteja nos textos abaixo. O envio continua 100%
# manual, um de cada vez, pelo próprio dono (ver Component A2/painel).
#
# 3 templates-base (o primeiro de cada trinca é o texto original de
# reactivationMessages.ts) + 2 paráfrases escritas à mão por base, mesmo
# sentido, sem emoji/preço/link/promessa, 1-2 frases, tom casual e caloroso.
_BASE_TEMPLATES = (
    (
        "Oi {nome}, tudo bem? Vi aqui que a gente tinha conversado antes e acabou "
        "ficando pra depois — ainda faz sentido resolver aquela questão que você "
        "me contou?",
        "Oi {nome}, tudo bem? Lembrei que a gente chegou a conversar e ficou meio "
        "em aberto — ainda faz sentido cuidar daquilo que você me contou?",
        "Oi {nome}, como vai? A gente conversou faz um tempo e acabou não seguindo "
        "adiante — ainda quer resolver aquilo que você comentou comigo?",
    ),
    (
        "Oi {nome}! Passando rapidinho pra saber como você está — ainda tá naquela "
        "situação que comentou comigo, ou já melhorou?",
        "Oi {nome}! Só passando pra saber notícias suas — a situação que você me "
        "contou continua a mesma, ou já deu uma melhorada?",
        "Oi {nome}, tudo bem por aí? Fiquei curioso pra saber como você está — "
        "ainda é aquela mesma situação de antes, ou já mudou algo?",
    ),
    (
        "Oi {nome}, tudo certo? Fiquei pensando em você aqui — ainda quer dar "
        "aquele passo que a gente conversou, ou prefere deixar pra outra hora?",
        "Oi {nome}, tudo certo por aí? Você me veio à cabeça hoje — ainda pretende "
        "dar aquele passo que combinamos, ou prefere deixar pra depois?",
        "Oi {nome}, como você tá? Lembrei da nossa conversa — ainda faz sentido "
        "seguir com aquele passo, ou melhor deixar pra outro momento?",
    ),
)
_ALL_TEMPLATES = tuple(text for base in _BASE_TEMPLATES for text in base)
SUGGESTION_VARIANTS = len(_ALL_TEMPLATES)


def _stable_hash(seed: str) -> int:
    """Mesmo algoritmo do legado (reactivationMessages.ts): hash*31 + charCode,
    32 bits sem sinal — mesmo chat_id sempre cai no mesmo template-base."""
    value = 0
    for ch in str(seed or ""):
        value = (value * 31 + ord(ch)) & 0xFFFFFFFF
    return value


def _apply_name(template: str, name: str) -> str:
    name = (name or "").strip()
    text = template.replace("{nome}", name) if name else template.replace(" {nome}", "")
    return re.sub(r"\s{2,}", " ", text).strip()


def suggest_message(chat_id: str, name: str, variant: int) -> str:
    """Sugestão determinística pro `chat_id`: escolhe o template-base por hash
    estável do chat_id e o texto dentro das 9 combinações (3 bases x 3 textos)
    pela `variant` — cada "gerar outra" muda o texto, sempre."""
    base = _stable_hash(chat_id) % len(_BASE_TEMPLATES)
    idx = (base * len(_BASE_TEMPLATES) + int(variant)) % SUGGESTION_VARIANTS
    first_name = name.strip().split()[0] if (name or "").strip() else ""
    return _apply_name(_ALL_TEMPLATES[idx], first_name)
