"""Reconciliação do atendimento: recebe o mundo e devolve as mudanças a aplicar.

Módulo puro no molde de `daily_audit.py`: não lê banco, não chama o bridge, não
envia mensagem. O servidor do painel monta o `Snapshot` (mensagens novas desde
o cursor, silenciados do bridge, contatos, usuários ativos, atendimentos
abertos) e aplica a lista de mudanças em ordem no store e no bridge.

Passos, idempotentes e nesta ordem (spec, "Reconciliação"):
1. mensagem recebida sem atendimento aberto abre um, na hora da mensagem;
2. mensagem enviada pelo Dono (nem painel, nem IA) assume, se não havia humano;
3. atendimento da IA cujo chat está silenciado por handoff fica sem responsável;
   sem humano e sem silêncio de handoff, volta para a IA com evento automático;
4. IA e Dono resolvem por inatividade;
5. bloqueio resolve qualquer um;
6. atendente inativo perde o atendimento;
7. hold do bridge casa com o responsável: humano sem hold recebe hold; hold do
   painel sem humano é liberado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

HUMANOS = ("atendente", "dono")
AUTORES = ("contato", "ia", "dono", "painel")


@dataclass(frozen=True)
class Mensagem:
    contato: str
    at: datetime
    autor: str  # contato | ia | dono | painel
    user: str | None = None
    message_id: str = ""


@dataclass
class Snapshot:
    now: datetime
    abertos: list[dict]
    mensagens: list[Mensagem]
    silenciados: dict[str, dict]  # contato -> {"hold": bool, "reason": str, "until": datetime | None}
    contatos: dict[str, dict]  # contato -> {"blocked": bool, "ai_enabled": bool}
    usuarios_ativos: set[str]
    ultima_resolucao: dict[str, datetime] = field(default_factory=dict)
    inatividade_h: float = 24.0


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def reconciliar(snap: Snapshot) -> list[dict[str, Any]]:
    mudancas: list[dict[str, Any]] = []
    estado: dict[str, dict] = {row["contato"]: dict(row) for row in snap.abertos if row.get("status") == "aberto"}

    def contato_info(contato: str) -> tuple[bool, bool]:
        info = snap.contatos.get(contato) or {}
        return bool(info.get("blocked")), info.get("ai_enabled", True) is not False

    def hold_painel(contato: str) -> bool:
        sil = snap.silenciados.get(contato) or {}
        return bool(sil.get("hold")) and sil.get("reason") == "painel"

    def liberar_hold_se_painel(contato: str) -> None:
        if hold_painel(contato):
            mudancas.append({"op": "hold", "contato": contato, "ligado": False})

    # 1 e 2: mensagens em ordem cronológica.
    for m in sorted(snap.mensagens, key=lambda x: x.at):
        bloqueado, ia_ligada = contato_info(m.contato)
        row = estado.get(m.contato)
        if row is None:
            resolvido_em = snap.ultima_resolucao.get(m.contato)
            if m.autor != "contato" or bloqueado or (resolvido_em and m.at <= resolvido_em):
                continue
            tipo = "ia" if ia_ligada else "nenhum"
            mudancas.append({"op": "abrir", "contato": m.contato, "responsavel_tipo": tipo,
                             "aberto_at": m.at, "ultima_msg_autor": "contato"})
            estado[m.contato] = {
                "contato": m.contato, "status": "aberto", "responsavel_tipo": tipo, "responsavel_user": None,
                "aberto_utc": _iso(m.at), "primeira_resposta_utc": None, "assumido_utc": None,
                "handoff_utc": None, "ultima_msg_utc": _iso(m.at), "ultima_msg_autor": "contato",
            }
            continue
        mudancas.append({"op": "mensagem", "contato": m.contato, "at": m.at, "autor": m.autor, "user": m.user})
        if m.autor != "contato" and not row.get("primeira_resposta_utc"):
            row["primeira_resposta_utc"] = _iso(m.at)
        if not row.get("ultima_msg_utc") or _iso(m.at) > row["ultima_msg_utc"]:
            row["ultima_msg_utc"] = _iso(m.at)
            row["ultima_msg_autor"] = m.autor
        if m.autor == "dono" and row["responsavel_tipo"] not in HUMANOS:
            mudancas.append({"op": "responsavel", "contato": m.contato, "tipo": "dono", "user": None,
                             "ator": "dono", "evento": "assumido", "detalhe": None})
            row.update(responsavel_tipo="dono", responsavel_user=None, assumido_utc=_iso(m.at), handoff_utc=None)

    # 3 a 6: cada atendimento aberto, na ordem da spec.
    limite = snap.now - timedelta(hours=float(snap.inatividade_h))
    for contato, row in list(estado.items()):
        bloqueado, ia_ligada = contato_info(contato)
        sil = snap.silenciados.get(contato) or {}
        tipo = row["responsavel_tipo"]

        em_handoff = sil.get("reason") == "handoff" and not sil.get("hold")
        if tipo == "ia" and em_handoff:
            mudancas.append({"op": "handoff", "contato": contato})
            row.update(responsavel_tipo="nenhum", handoff_utc=_iso(snap.now))
            tipo = "nenhum"
        elif tipo == "nenhum" and row.get("handoff_utc") and not em_handoff and ia_ligada and not bloqueado:
            mudancas.append({"op": "responsavel", "contato": contato, "tipo": "ia", "user": None, "ator": "sistema",
                             "evento": "devolvido_auto", "detalhe": "prazo do handoff expirou"})
            row.update(responsavel_tipo="ia", handoff_utc=None)
            tipo = "ia"

        if tipo in ("ia", "dono"):
            ultima = _dt(row.get("ultima_msg_utc")) or _dt(row.get("aberto_utc"))
            if ultima and ultima <= limite:
                mudancas.append({"op": "resolver", "contato": contato, "motivo": "inatividade"})
                liberar_hold_se_painel(contato)
                continue

        if bloqueado:
            mudancas.append({"op": "resolver", "contato": contato, "motivo": "bloqueio"})
            liberar_hold_se_painel(contato)
            continue

        if tipo == "atendente" and row.get("responsavel_user") not in snap.usuarios_ativos:
            mudancas.append({"op": "responsavel", "contato": contato, "tipo": "nenhum", "user": None,
                             "ator": "sistema", "evento": "responsavel_removido", "detalhe": row.get("responsavel_user")})
            row.update(responsavel_tipo="nenhum", responsavel_user=None, assumido_utc=None)
            tipo = "nenhum"

        if tipo in HUMANOS and not sil.get("hold"):
            mudancas.append({"op": "hold", "contato": contato, "ligado": True})
        elif tipo not in HUMANOS:
            liberar_hold_se_painel(contato)

    return mudancas
