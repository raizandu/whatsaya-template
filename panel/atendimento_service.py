"""Serviço de atendimento do painel: monta o `Snapshot` a partir dos bancos e do
bridge, aplica as mudanças da reconciliação no store e no bridge, e lista as
filas para a tela.

É o único módulo do painel que lê e escreve no mesmo lugar: a reconciliação é
o que mantém `panel.db` e o silêncio do bridge coerentes (ADR 0001), então
roda numa thread de fundo a cada 10 s e sob demanda ao listar, com trava de
5 s. Se o bridge não responde, nada é reconciliado — um mundo sem silêncios
visíveis devolveria à IA todo handoff em curso.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import atendimento_reconcile as reconcile
import atendimento_store as store
import data as panel_data
import panel_store
import users_store

logger = logging.getLogger("panel.atendimento")

FILAS = ("meus", "sem_responsavel", "com_ia", "todos")
JANELA_BOOTSTRAP = timedelta(days=7)
INTERVALO_S = 10.0
TRAVA_S = 5.0


def canonical_contato(chat_id: str, contacts: dict, lid_map: dict | None) -> str | None:
    """Telefone `digits@s.whatsapp.net` quando dá para resolver o `@lid`; grupo e
    broadcast ficam de fora (nunca abrem atendimento)."""
    chat_id = str(chat_id or "")
    if not chat_id or chat_id.endswith("@g.us") or "broadcast" in chat_id:
        return None
    if not chat_id.endswith("@lid"):
        return chat_id
    digits = panel_data._digits(chat_id)
    phone = (lid_map or {}).get(digits)
    if not phone:
        for key, record in contacts.items():
            if isinstance(record, dict) and str(record.get("lid") or "") == chat_id and not str(key).endswith("@lid"):
                return str(key)
        return chat_id
    return f"{phone}@s.whatsapp.net"


def hold(bridge, contato: str, ligado: bool) -> bool:
    """Hold do painel no bridge (motivo `painel`) ou liberação. Único ponto: ações e
    reconciliação passam por aqui."""
    if ligado:
        resp = bridge.post_json("/chat-silence", {"chatId": contato, "hold": True, "reason": "painel"})
    else:
        resp = bridge.post_json("/chat-unsilence", {"chatId": contato})
    return isinstance(resp, dict) and bool(resp.get("success"))


class AtendimentoService:
    def __init__(
        self, paths: panel_data.Paths, bridge, *, inatividade_h: float = 24.0,
        sla_primeira_min: int = 15, sla_resolucao_h: int = 24, usuarios_extra: tuple[str, ...] = (),
    ):
        self.paths = paths
        self.bridge = bridge
        self.inatividade_h = float(inatividade_h)
        self.sla_primeira_min = int(sla_primeira_min)
        self.sla_resolucao_h = int(sla_resolucao_h)
        self.usuarios_extra = tuple(usuarios_extra)
        self._lock = threading.Lock()
        self._ultima_execucao = 0.0
        self._executando = False
        self.silenciados: dict[str, dict] = {}
        self.bot_paused = False
        self.lid_map: dict[str, str] = {}
        self._stop = threading.Event()

    # ── snapshot ────────────────────────────────────────────────────────────

    def _bridge_state(self) -> bool:
        status = self.bridge.get_json("/bot-status")
        silence = self.bridge.get_json("/chat-silence")
        if not isinstance(status, dict) or not isinstance(silence, dict):
            return False
        self.bot_paused = bool(status.get("botPaused"))
        self.lid_map = {str(k): str(v) for k, v in (status.get("lidToPhone") or {}).items()}
        contacts = panel_data.load_contacts(self.paths.contacts_json)
        silenciados: dict[str, dict] = {}
        for item in silence.get("silencedChats") or []:
            contato = canonical_contato(item.get("chatId"), contacts, self.lid_map)
            if not contato:
                continue
            until = item.get("silencedUntil") or 0
            silenciados[contato] = {
                "hold": bool(item.get("hold")),
                "reason": str(item.get("reason") or ""),
                "until": datetime.fromtimestamp(until / 1000, timezone.utc) if until else None,
            }
        self.silenciados = silenciados
        return True

    def _contatos(self, contacts: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for key, record in contacts.items():
            if not isinstance(record, dict):
                continue
            contato = canonical_contato(key, contacts, self.lid_map)
            if not contato:
                continue
            atual = out.setdefault(contato, {"blocked": False, "ai_enabled": True})
            atual["blocked"] = atual["blocked"] or record.get("blocked") is True
            if record.get("ai_enabled") is False:
                atual["ai_enabled"] = False
        return out

    def _mensagens(self, contacts: dict, desde_ts: float, ate_ts: float) -> tuple[list[reconcile.Mensagem], float]:
        conn = panel_data._ro(self.paths.messages_db)
        if conn is None:
            return [], desde_ts
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, chat_id, message_id, message_type, body, timestamp, from_me, has_media, media_type"
                " FROM messages WHERE is_historical = 0 AND timestamp > ? AND timestamp <= ? ORDER BY timestamp, id",
                (desde_ts, ate_ts),
            ).fetchall()]
        finally:
            conn.close()
        por_contato: dict[str, list[dict]] = {}
        for row in rows:
            contato = canonical_contato(row.get("chat_id"), contacts, self.lid_map)
            if contato:
                por_contato.setdefault(contato, []).append(row)
        outbound = panel_store.outbound_for_chats(self.paths.panel_db, list(por_contato))
        mensagens: list[reconcile.Mensagem] = []
        maior = desde_ts
        for contato, lista in por_contato.items():
            aliases = list(dict.fromkeys([contato, *(r["chat_id"] for r in lista)]))
            if any(r.get("from_me") for r in lista):
                # Dono × IA só se distingue pelo log `[human-send]`, como na timeline.
                panel_data._mark_conversation_owners(lista, self.paths.plugin_log, aliases)
            vistos: set[str] = set()
            for row in lista:
                mid = str(row.get("message_id") or "")
                if mid in vistos:
                    continue  # mesma mensagem sob telefone e @lid
                vistos.add(mid)
                ts = float(row.get("timestamp") or 0)
                maior = max(maior, ts)
                if not row.get("from_me"):
                    autor, user = "contato", None
                elif mid in outbound:
                    autor, user = "painel", str(outbound[mid].get("sent_by_user") or "") or None
                elif row.get("owner") == "owner":
                    autor, user = "dono", None
                else:
                    autor, user = "ia", None
                mensagens.append(reconcile.Mensagem(
                    contato=contato, at=datetime.fromtimestamp(ts, timezone.utc), autor=autor, user=user, message_id=mid,
                ))
        return mensagens, maior

    def _usuarios_ativos(self) -> set[str]:
        ativos = {u["username"] for u in users_store.list_users(self.paths.users_json) if u.get("active")}
        ativos.update(self.usuarios_extra)
        return ativos

    def snapshot(self, now: datetime) -> tuple[reconcile.Snapshot, float] | None:
        """`None` quando o bridge não respondeu: sem silêncios visíveis não se reconcilia."""
        if not self._bridge_state():
            return None
        contacts = panel_data.load_contacts(self.paths.contacts_json)
        cursor = store.meta_get(self.paths.panel_db, "msg_cursor")
        desde = float(cursor) if cursor else (now - JANELA_BOOTSTRAP).timestamp()
        mensagens, maior = self._mensagens(contacts, desde, now.timestamp())
        snap = reconcile.Snapshot(
            now=now,
            abertos=store.listar_abertos(self.paths.panel_db),
            mensagens=mensagens,
            silenciados=self.silenciados,
            contatos=self._contatos(contacts),
            usuarios_ativos=self._usuarios_ativos(),
            ultima_resolucao=store.ultima_resolucao(self.paths.panel_db),
            inatividade_h=self.inatividade_h,
        )
        return snap, maior

    # ── aplicação ───────────────────────────────────────────────────────────

    def hold(self, contato: str, ligado: bool) -> bool:
        ok = hold(self.bridge, contato, ligado)
        if not ok:
            logger.warning("[atendimento] bridge não aplicou hold=%s em %s", ligado, contato)
        return ok

    def aplicar(self, mudancas: list[dict[str, Any]], now: datetime) -> dict[str, int]:
        db = self.paths.panel_db
        contagem: dict[str, int] = {}
        for m in mudancas:
            op = m["op"]
            contato = m["contato"]
            try:
                if op == "abrir":
                    store.abrir(db, contato=contato, responsavel_tipo=m["responsavel_tipo"], aberto_at=m["aberto_at"],
                                ultima_msg_autor=m.get("ultima_msg_autor"), now=now)
                elif op == "hold":
                    if not self.hold(contato, m["ligado"]):
                        continue
                else:
                    atual = store.aberto_do_contato(db, contato)
                    if not atual:
                        continue
                    if op == "mensagem":
                        store.registrar_mensagem(db, atual["id"], at=m["at"], autor=m["autor"], user=m.get("user"), now=now)
                    elif op == "responsavel":
                        store.definir_responsavel(db, atual["id"], tipo=m["tipo"], user=m.get("user"), ator=m["ator"],
                                                  evento=m["evento"], detalhe=m.get("detalhe"), now=now)
                    elif op == "handoff":
                        store.marcar_handoff(db, atual["id"], now=now)
                    elif op == "resolver":
                        store.resolver(db, atual["id"], motivo=m["motivo"], ator="sistema", now=now)
            except store.AtendimentoAberto:
                continue
            except Exception as err:  # uma mudança ruim não derruba as outras
                logger.warning("[atendimento] falha ao aplicar %s em %s: %s", op, contato, err)
                continue
            contagem[op] = contagem.get(op, 0) + 1
        return contagem

    def reconciliar(self, now: datetime | None = None, *, force: bool = False) -> dict[str, Any]:
        """Uma execução por vez; quem chega durante outra (ou dentro da trava) pula.
        O lock cobre só a decisão — o I/O de banco e bridge roda fora dele, para a
        rota de listagem não enfileirar atrás de uma ponte lenta."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._executando or (not force and time.monotonic() - self._ultima_execucao < TRAVA_S):
                return {"skipped": True}
            self._executando = True
            self._ultima_execucao = time.monotonic()
        try:
            montado = self.snapshot(now)
            if montado is None:
                return {"skipped": True, "bridge": "unreachable"}
            snap, cursor = montado
            mudancas = reconcile.reconciliar(snap)
            aplicado = self.aplicar(mudancas, now)
            store.meta_set(self.paths.panel_db, "msg_cursor", repr(cursor))
            return {"skipped": False, "mudancas": len(mudancas), "aplicado": aplicado}
        finally:
            with self._lock:
                self._executando = False

    def start_background(self, interval_s: float = INTERVALO_S) -> threading.Thread:
        def loop():
            while not self._stop.wait(interval_s):
                try:
                    self.reconciliar()
                except Exception as err:
                    logger.warning("[atendimento] reconciliação falhou: %s", err)
        thread = threading.Thread(target=loop, daemon=True, name="atendimento-reconcile")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    # ── leitura ─────────────────────────────────────────────────────────────

    def _previews(self, contatos: list[str], contacts: dict) -> dict[str, str]:
        """Última mensagem com corpo de cada contato aberto (telefone e `@lid`),
        numa consulta só — nunca uma por contato."""
        if not contatos:
            return {}
        reverso: dict[str, list[str]] = {}
        for lid, phone in self.lid_map.items():
            reverso.setdefault(phone, []).append(f"{lid}@lid")
        aliases: dict[str, str] = {}
        for contato in contatos:
            aliases[contato] = contato
            for lid in reverso.get(panel_data._digits(contato), []):
                aliases[lid] = contato
            record = contacts.get(contato)
            if isinstance(record, dict) and record.get("lid"):
                aliases[str(record["lid"])] = contato
        conn = panel_data._ro(self.paths.messages_db)
        if conn is None:
            return {}
        try:
            placeholders = ",".join("?" for _ in aliases)
            rows = conn.execute(
                "SELECT m.chat_id, m.body, m.timestamp FROM messages m JOIN ("
                "  SELECT chat_id, MAX(timestamp) AS at FROM messages"
                f"  WHERE chat_id IN ({placeholders}) AND is_historical = 0 AND body IS NOT NULL AND TRIM(body) != ''"
                "  GROUP BY chat_id"
                ") x ON x.chat_id = m.chat_id AND x.at = m.timestamp",
                list(aliases),
            ).fetchall()
        except Exception:
            return {}
        finally:
            conn.close()
        melhor: dict[str, tuple[float, str]] = {}
        for row in rows:
            contato = aliases.get(str(row["chat_id"]))
            if not contato:
                continue
            at = float(row["timestamp"] or 0)
            if contato not in melhor or at > melhor[contato][0]:
                melhor[contato] = (at, str(row["body"] or "").strip())
        return {contato: body for contato, (_at, body) in melhor.items()}

    def sla(self, row: dict, now: datetime | None = None) -> dict:
        """Os dois relógios do atendimento; `estourado` é só destaque na tela."""
        now = now or datetime.now(timezone.utc)
        aberto = datetime.fromisoformat(row["aberto_utc"])
        primeira = datetime.fromisoformat(row["primeira_resposta_utc"]) if row.get("primeira_resposta_utc") else None
        fim = datetime.fromisoformat(row["resolvido_utc"]) if row.get("resolvido_utc") else now
        primeira_s = int(((primeira or fim) - aberto).total_seconds())
        resolucao_s = int((fim - aberto).total_seconds())
        return {
            "primeira": {"alvo_min": self.sla_primeira_min, "decorrido_s": primeira_s,
                         "estourado": primeira_s > self.sla_primeira_min * 60, "cumprida": primeira is not None},
            "resolucao": {"alvo_h": self.sla_resolucao_h, "decorrido_s": resolucao_s,
                          "estourado": resolucao_s > self.sla_resolucao_h * 3600},
        }

    def _item(self, row: dict, contacts: dict, now: datetime, preview: str = "", avatars: dict | None = None) -> dict:
        aberto = datetime.fromisoformat(row["aberto_utc"])
        ultima = datetime.fromisoformat(row["ultima_msg_utc"]) if row.get("ultima_msg_utc") else aberto
        aguardando = row.get("ultima_msg_autor") == "contato"
        sil = self.silenciados.get(row["contato"]) or {}
        return {
            "id": row["id"],
            "protocolo": row["protocolo"],
            "contato": row["contato"],
            "nome": panel_data._contact_name(contacts, row["contato"]),
            "telefone": panel_data.format_phone(row["contato"]),
            "avatar_url": panel_data.avatar_url(avatars, row["contato"]),
            "preview": preview[:140],
            "canal": row["canal"],
            "status": row["status"],
            "responsavel": {"tipo": row["responsavel_tipo"], "user": row.get("responsavel_user")},
            "aberto_utc": row["aberto_utc"],
            "assumido_utc": row.get("assumido_utc"),
            "handoff_utc": row.get("handoff_utc"),
            "ultima_msg_utc": ultima.isoformat(),
            "ultima_msg_autor": row.get("ultima_msg_autor"),
            "aguardando_nos": aguardando,
            "espera_s": int((now - ultima).total_seconds()) if aguardando else 0,
            "sla": self.sla(row, now),
            "silencio": {"ativo": bool(sil), "hold": bool(sil.get("hold")), "motivo": sil.get("reason"),
                         "ate_utc": sil["until"].isoformat() if sil.get("until") else None},
            "rev": row["rev"],
        }

    @staticmethod
    def fila_de(item: dict, username: str) -> set[str]:
        tipo, user = item["responsavel"]["tipo"], item["responsavel"]["user"]
        filas = {"todos"}
        if tipo == "atendente" and user == username:
            filas.add("meus")
        if tipo == "nenhum":
            filas.add("sem_responsavel")
        if tipo == "ia":
            filas.add("com_ia")
        return filas

    def listar(self, *, fila: str, username: str, ver_todos: bool, desde_rev: int | None = None,
               now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if fila not in FILAS:
            raise ValueError(f"fila desconhecida: {fila!r}")
        if fila in ("com_ia", "todos") and not ver_todos:
            raise PermissionError(fila)
        contacts = panel_data.load_contacts(self.paths.contacts_json)
        abertos = store.listar_abertos(self.paths.panel_db)
        previews = self._previews([r["contato"] for r in abertos], contacts)
        avatars = (self.bridge.get_json("/avatars") or {}).get("avatars") if self.bridge else None
        itens = [self._item(r, contacts, now, previews.get(r["contato"], ""), avatars) for r in abertos]
        contagens = {f: 0 for f in FILAS}
        aguardando = 0
        for item in itens:
            filas = self.fila_de(item, username)
            for f in filas:
                contagens[f] += 1
            if item["aguardando_nos"] and filas & {"meus", "sem_responsavel"}:
                aguardando += 1
        if not ver_todos:
            contagens = {f: n for f, n in contagens.items() if f in ("meus", "sem_responsavel")}
        selecionados = [i for i in itens if fila in self.fila_de(i, username)]
        if desde_rev is not None:
            selecionados = [i for i in selecionados if i["rev"] > int(desde_rev)]
        # Aguardando nós primeiro, quem espera há mais tempo no topo; os demais, última mensagem mais recente primeiro.
        selecionados.sort(key=lambda i: (
            not i["aguardando_nos"], -i["espera_s"], -datetime.fromisoformat(i["ultima_msg_utc"]).timestamp(),
        ))
        return {
            "fila": fila,
            "itens": selecionados,
            "contagens": contagens,
            "aguardando": aguardando,
            "rev": store.rev(self.paths.panel_db),
            "bot_paused": self.bot_paused,
        }
