"""Escritas do painel. Cada função faz uma coisa e devolve o estado novo.

Regras que valem para todas:
- Contato: sempre pelo `contacts_store` (flock partilhado com o plugin), sempre
  no telefone e no espelho `@lid` juntos, nunca no número do dono.
- Funil e follow-up: pelo `FollowupEngine`, que já cancela os toques abertos
  quando a política muda. Nada de UPDATE direto na tabela.
- Desbloquear não liga a IA: grava a intenção e o plugin conclui na próxima
  mensagem do contato, depois de encerrar as sessões antigas (fail-closed).
- Pausa global e silêncio por chat: pelo bridge, que é dono desse estado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import contacts_store
import data as panel_data
from commercial_followups import FollowupEngine

STAGES = panel_data.STAGES
FOLLOWUP_ACTIONS = ("pause", "resume", "cancel")
BLOCK_REASON = "panel_block"
UNBLOCK_PENDING_REASON = "panel_unblock_reset_pending"


class ActionError(ValueError):
    """Pedido inválido ou recusado. A mensagem vai para o dono como está."""


# ── identidade ──────────────────────────────────────────────────────────────

def _mirror_keys(contacts: dict, key: str) -> list[str]:
    """Telefone e `@lid` do mesmo contato, para gravar os dois de uma vez."""
    keys = [key]
    record = contacts.get(key) if isinstance(contacts.get(key), dict) else {}
    if key.endswith("@lid"):
        for other, rec in contacts.items():
            if isinstance(rec, dict) and rec.get("lid") == key and other != key:
                keys.append(other)
    else:
        lid = record.get("lid")
        if lid and lid != key:
            keys.append(str(lid))
        digits = panel_data._digits(key)
        for other, rec in contacts.items():
            if other != key and isinstance(rec, dict) and "@lid" not in other and digits and panel_data._digits(other) == digits:
                keys.append(other)
    return list(dict.fromkeys(keys))


def resolve_contact(paths: panel_data.Paths, *, chat_id: str = "", query: str = "", owner_number: str = "") -> str:
    """Chave do contato a partir de um JID ou de um texto (número ou nome)."""
    contacts = contacts_store.read_contacts(paths.contacts_json)
    candidate = str(chat_id or "").strip()
    if not candidate:
        text = str(query or "").strip()
        if not text:
            raise ActionError("Informe o número ou o nome do contato.")
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 8:
            for key in contacts:
                if panel_data._digits(key) and (digits in panel_data._digits(key) or panel_data._digits(key) in digits):
                    candidate = key
                    break
            if not candidate:
                for chat in panel_data.recent_chats(paths.messages_db, panel_data.datetime.fromtimestamp(0, panel_data.timezone.utc), limit=500):
                    if digits in panel_data._digits(chat["chat_id"]):
                        candidate = chat["chat_id"]
                        break
            if not candidate:
                candidate = f"{digits}@s.whatsapp.net"
        else:
            folded = text.casefold()
            matches = [k for k, r in contacts.items() if isinstance(r, dict) and str(r.get("name") or "").casefold() == folded]
            if not matches:
                matches = [k for k, r in contacts.items() if isinstance(r, dict) and folded in str(r.get("name") or "").casefold()]
            if not matches:
                raise ActionError(f"Nenhum contato chamado '{text}'.")
            phones = [k for k in matches if "@lid" not in k]
            candidate = (phones or matches)[0]
    if owner_number and panel_data._digits(candidate) == owner_number:
        raise ActionError("O número do dono não pode ser bloqueado.")
    return candidate


# ── contatos ────────────────────────────────────────────────────────────────

def block(paths: panel_data.Paths, *, chat_id: str = "", query: str = "", owner_number: str = "") -> dict:
    key = resolve_contact(paths, chat_id=chat_id, query=query, owner_number=owner_number)
    contacts = contacts_store.read_contacts(paths.contacts_json)
    keys = _mirror_keys(contacts, key)
    updated = contacts_store.update_record(paths.contacts_json, keys, {
        "blocked": True,
        "ai_enabled": False,
        "in_flow": False,
        "ai_disabled_reason": BLOCK_REASON,
        "session_reset_pending": None,
    })
    # Toques abertos morrem junto: bloqueado não recebe follow-up.
    if Path(paths.followups_db).exists():
        engine = FollowupEngine(paths.followups_db)
        for k in keys:
            if engine.get_lead(k):
                engine.configure_lead(k, automation_enabled=False)
    return {"chat_id": key, "keys": keys, "blocked": panel_data.blocked_contacts(updated)}


def unblock(paths: panel_data.Paths, *, chat_id: str) -> dict:
    key = str(chat_id or "").strip()
    if not key:
        raise ActionError("chat_id é obrigatório.")
    contacts = contacts_store.read_contacts(paths.contacts_json)
    if not isinstance(contacts.get(key), dict):
        raise ActionError("Contato não encontrado.")
    keys = _mirror_keys(contacts, key)
    updated = contacts_store.update_record(paths.contacts_json, keys, {
        "blocked": False,
        "ai_enabled": False,
        "in_flow": False,
        "ai_disabled_reason": UNBLOCK_PENDING_REASON,
        "session_reset_pending": True,
    })
    return {"chat_id": key, "keys": keys, "pending_reset": True, "blocked": panel_data.blocked_contacts(updated)}


# ── funil e follow-ups ──────────────────────────────────────────────────────

def set_stage(paths: panel_data.Paths, *, chat_id: str, stage: str) -> dict:
    stage = str(stage or "").strip().lower()
    if stage not in STAGES:
        raise ActionError(f"Etapa inválida: {stage!r}.")
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    engine = FollowupEngine(paths.followups_db)
    if not engine.get_lead(chat_id):
        raise ActionError("Lead não encontrado no funil.")
    engine.configure_lead(chat_id, stage=stage)
    return {"chat_id": chat_id, "lead": engine.get_lead(chat_id)}


def followup(paths: panel_data.Paths, *, chat_id: str, action: str) -> dict:
    action = str(action or "").strip().lower()
    if action not in FOLLOWUP_ACTIONS:
        raise ActionError(f"Ação inválida: {action!r}.")
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    engine = FollowupEngine(paths.followups_db)
    if not engine.get_lead(chat_id):
        raise ActionError("Lead não encontrado no funil.")
    if action == "pause":
        engine.configure_lead(chat_id, automation_enabled=False)
    elif action == "resume":
        engine.configure_lead(chat_id, automation_enabled=True)
    else:
        # Cancelar mata só os toques abertos; a automação continua para o próximo
        # silêncio. Desligar e religar é o caminho oficial para cancelar no engine.
        engine.configure_lead(chat_id, automation_enabled=False)
        engine.configure_lead(chat_id, automation_enabled=True)
    lead = engine.get_lead(chat_id)
    open_jobs = [j for j in engine.get_jobs(chat_id) if j.get("status") in ("pending", "leased")]
    return {"chat_id": chat_id, "action": action, "automation_enabled": bool(lead and lead.get("automation_enabled")), "open_jobs": len(open_jobs)}


# ── bridge ──────────────────────────────────────────────────────────────────

def pause(bridge, *, paused: Any) -> dict:
    if not isinstance(paused, bool):
        raise ActionError("paused deve ser true ou false.")
    result = bridge.post_json("/bot-pause", {"paused": paused})
    if not result or not result.get("success"):
        raise ActionError("A ponte não respondeu ao pedido de pausa.")
    return {"paused": bool(result.get("botPaused"))}


def whatsapp_settings(
    bridge, *, reject_calls: Any, groups_enabled: Any, debounce_seconds: Any
) -> dict:
    if not isinstance(reject_calls, bool) or not isinstance(groups_enabled, bool):
        raise ActionError("As opções de ligação e grupos devem ser true ou false.")
    if isinstance(debounce_seconds, bool) or not isinstance(debounce_seconds, int):
        raise ActionError("O tempo de agrupamento deve ser um número inteiro de segundos.")
    if debounce_seconds < 0 or debounce_seconds > 60 or 0 < debounce_seconds < 2:
        raise ActionError("Use 0 para desligar ou um tempo entre 2 e 60 segundos.")
    result = bridge.post_json("/runtime-settings", {
        "rejectCalls": reject_calls,
        "groupsEnabled": groups_enabled,
        "debounceInitialMs": debounce_seconds * 1000,
    })
    settings = result.get("settings") if isinstance(result, dict) else None
    if not result or not result.get("success") or not isinstance(settings, dict):
        raise ActionError("A ponte não salvou as configurações do WhatsApp.")
    return {
        "reject_calls": bool(settings.get("rejectCalls")),
        "groups_enabled": bool(settings.get("groupsEnabled")),
        "debounce_seconds": int(settings.get("debounceInitialMs") or 0) // 1000,
    }


def silence(bridge, *, chat_id: str, minutes: Any = None) -> dict:
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    body = {"chatId": chat_id}
    if minutes is not None:
        body["minutes"] = minutes
    result = bridge.post_json("/chat-silence", body)
    if not result or not result.get("success"):
        raise ActionError("A ponte não respondeu ao pedido de silêncio.")
    return {"chat_id": chat_id, "silenced_until": result.get("silencedUntil"), "time_left_s": result.get("timeLeftSeconds")}


def unsilence(bridge, *, chat_id: str) -> dict:
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    result = bridge.post_json("/chat-unsilence", {"chatId": chat_id})
    if not result or not result.get("success"):
        raise ActionError("A ponte não respondeu ao pedido de retomada.")
    return {"chat_id": chat_id, "silenced": False}
