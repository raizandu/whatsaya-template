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

import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

import contacts_store
import data as panel_data
import reactivation_store
from commercial_followups import FollowupEngine, MAX_ESTIMATED_VALUE_CENTS

FOLLOWUP_ACTIONS = ("pause", "resume", "cancel")
BLOCK_REASON = "panel_block"
UNBLOCK_PENDING_REASON = "panel_unblock_reset_pending"
LEGACY_AI_OFF_REASON = "legacy_history"
CONTACT_AI_POLICY_VERSION = 2

# Mesma lista de parentescos que o plugin usa pra privilegiar contato pessoal
# (`_PERSONAL_CONTACT_RELATIONSHIPS`/`_contact_record_is_personal` em
# whatsapp_manager.py) — o painel não importa o plugin (ver docstring acima),
# então repete a lista aqui.
_PERSONAL_RELATIONSHIP_TOKENS = frozenset({
    "amigo", "amiga", "amigoproximo", "parente", "familiar", "filho", "filha",
    "pessoal", "namorada", "namorado", "esposa", "marido", "mae", "pai",
    "irmao", "irma", "avo", "tio", "tia", "primo", "prima",
})


def _normalize_relationship(value: Any) -> str:
    text = str(value or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _is_personal_relationship(value: Any) -> bool:
    normalized = _normalize_relationship(value)
    tokens = set(re.findall(r"[a-z]+", normalized))
    compact = "".join(tokens) if len(tokens) == 1 else normalized.replace(" ", "")
    return bool(tokens & _PERSONAL_RELATIONSHIP_TOKENS) or compact in _PERSONAL_RELATIONSHIP_TOKENS


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


def set_ai_access(paths: panel_data.Paths, *, chat_id: str, enabled: bool) -> dict:
    """Liga/desliga a IA de um contato a pedido explícito do dono, pela tela de
    Contatos — legado, pessoal reclassificado ou qualquer outro que ele queira
    trazer de volta (ou tirar) do fluxo na mão."""
    key = str(chat_id or "").strip()
    if not key:
        raise ActionError("chat_id é obrigatório.")
    if not isinstance(enabled, bool):
        raise ActionError("enabled deve ser true ou false.")
    contacts = contacts_store.read_contacts(paths.contacts_json)
    if not isinstance(contacts.get(key), dict):
        raise ActionError("Contato não encontrado.")
    keys = _mirror_keys(contacts, key)
    records = [contacts[k] for k in keys if isinstance(contacts.get(k), dict)]
    if any(r.get("blocked") is True for r in records):
        raise ActionError("Desbloqueie primeiro.")
    if any(_is_personal_relationship(r.get("manual_relationship")) for r in records):
        raise ActionError("Contato pessoal não entra no fluxo.")
    if enabled:
        updated = _apply_ai_enable(paths, keys, flow_origin="owner_optin")
    else:
        updated = contacts_store.update_record(paths.contacts_json, keys, {
            "ai_enabled": False,
            "in_flow": False,
            "ai_disabled_reason": "owner_optout",
            "flow_origin": "owner_optout",
        })
    record = updated.get(key) if isinstance(updated.get(key), dict) else {}
    ai_enabled = record.get("ai_enabled") is True
    return {
        "chat_id": key,
        "keys": keys,
        "enabled": ai_enabled,
        "ai": panel_data._ai_status(
            kind="active", ai_enabled=ai_enabled, ai_disabled_reason=record.get("ai_disabled_reason"),
            human=False, automation=False, has_lead=False,
        ),
    }


# ── funil e follow-ups ──────────────────────────────────────────────────────

def set_stage(paths: panel_data.Paths, *, chat_id: str, stage: str, pipeline_id: str = "default") -> dict:
    stage = str(stage or "").strip().lower()
    preset = panel_data.pipeline(pipeline_id)
    stage_meta = {sid: (label, engine_stage, terminal) for sid, label, engine_stage, terminal in preset["stages"]}
    if stage not in stage_meta:
        raise ActionError(f"Etapa inválida: {stage!r}.")
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    engine = FollowupEngine(paths.followups_db)
    if not engine.get_lead(chat_id):
        raise ActionError("Lead não encontrado no funil.")
    _label, engine_stage, is_terminal = stage_meta[stage]
    engine.configure_lead(chat_id, stage=engine_stage, terminal=is_terminal)
    if preset["id"] != "default":
        contacts = contacts_store.read_contacts(paths.contacts_json)
        contacts_store.update_record(paths.contacts_json, _mirror_keys(contacts, chat_id), {"pipeline_stage": stage})
    return {"chat_id": chat_id, "stage": stage, "engine_stage": engine_stage, "lead": engine.get_lead(chat_id)}


def set_estimated_value(paths: panel_data.Paths, *, chat_id: str, value_brl: Any) -> dict:
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    text = str(value_brl if value_brl is not None else "").strip()
    if not text:
        amount_cents = None
    else:
        compact = re.sub(r"\s+", "", text.removeprefix("R$").strip())
        if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?|\d+(?:\.\d{1,2})?", compact):
            raise ActionError("Informe um valor válido, como 4800 ou 4.800,00.")
        grouped_pt = re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", compact)
        normalized = compact.replace(".", "").replace(",", ".") if grouped_pt or "," in compact else compact
        try:
            amount_cents = int(Decimal(normalized) * 100)
        except (InvalidOperation, ValueError):
            raise ActionError("Informe um valor válido, como 4800 ou 4.800,00.") from None
        if amount_cents < 0 or amount_cents > MAX_ESTIMATED_VALUE_CENTS:
            raise ActionError("O valor estimado deve ficar entre R$ 0 e R$ 99.999.999,99.")
    engine = FollowupEngine(paths.followups_db)
    if not engine.get_lead(chat_id):
        raise ActionError("Lead não encontrado no funil.")
    lead = engine.set_estimated_value(chat_id, amount_cents)
    return {"chat_id": chat_id, "estimated_value_cents": lead.get("estimated_value_cents")}


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


# ── reativação manual por etiqueta ──────────────────────────────────────────
#
# Só prepara a lista e guarda o texto — o envio continua 100% manual, pelo
# celular do dono. Nada aqui manda mensagem.

def reactivation_prepare(paths: panel_data.Paths, bridge, *, label: str, owner_number: str = "") -> dict:
    label = (label or "").strip()
    if not label:
        raise ActionError("Informe uma etiqueta.")
    status, payload = bridge.get_json_status("/labels/chats?name=" + quote(label, safe=""))
    if status == 404:
        raise ActionError(f"Nenhum contato com a etiqueta “{label}” — confira o nome no WhatsApp Business.")
    if status != 200 or not isinstance(payload, dict) or not payload.get("success"):
        raise ActionError("A ponte não respondeu ao pedido de preparar a lista.")

    chats = payload.get("chats") if isinstance(payload.get("chats"), list) else []
    contacts = contacts_store.read_contacts(paths.contacts_json)
    owner_digits = str(owner_number or "").strip()

    canonical_ids: list[str] = []
    aliases: dict[str, set[str]] = {}
    seen: set[str] = set()
    skipped_lid = 0
    skipped_blocked = 0
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        raw_id = str(chat.get("chatId") or "").strip()
        canonical = str(chat.get("canonicalChatId") or raw_id).strip()
        if not canonical:
            continue
        if canonical.endswith("@lid"):
            skipped_lid += 1
            continue
        if owner_digits and panel_data._digits(canonical) == owner_digits:
            continue
        record = contacts.get(canonical) if isinstance(contacts.get(canonical), dict) else {}
        if record.get("blocked") is True:
            skipped_blocked += 1
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        canonical_ids.append(canonical)
        aliases.setdefault(canonical, set()).update({canonical, raw_id})

    result = reactivation_store.prepare(paths.followups_db, canonical_ids, label=label)
    reenabled = _reenable_legacy_contacts(paths, canonical_ids, aliases)
    return {
        "label": label,
        "found": len(chats),
        "added": result["added"],
        "rearmed": result["rearmed"],
        "skipped_lid": skipped_lid,
        "skipped_blocked": skipped_blocked,
        "reenabled": reenabled,
        "total": result["total"],
    }


def _apply_ai_enable(paths: panel_data.Paths, keys: list[str], *, flow_origin: str) -> dict:
    """Liga a IA nas chaves dadas — os mesmos campos do opt-in de reativação,
    parametrizados pelo `flow_origin` de quem pediu (reativação em massa vs. o
    dono na tela do contato). Núcleo comum de `_reenable_legacy_contacts` e
    `set_ai_access`."""
    return contacts_store.update_record(paths.contacts_json, keys, {
        "ai_enabled": True,
        "in_flow": True,
        "flow_origin": flow_origin,
        "ai_disabled_reason": None,
        "ai_policy_version": CONTACT_AI_POLICY_VERSION,
        "commercial_scope_confirmed_at": time.time(),
    })


def _reenable_legacy_contacts(paths: panel_data.Paths, chat_ids: list[str], aliases: dict[str, set[str]] | None = None) -> int:
    """Preparar a reativação é o opt-in explícito do dono: contatos legados que
    estavam com a IA desligada só pelo histórico (`legacy_history`) voltam ao
    fluxo, para que a resposta do lead depois do primeiro envio manual seja
    atendida. Bloqueados, pessoais e outros motivos não mudam."""
    contacts = contacts_store.read_contacts(paths.contacts_json)
    count = 0
    for chat_id in chat_ids:
        # O histórico pode ter registrado o contato só pelo LID; o bridge devolve o id
        # bruto e o canônico, e qualquer alias desligado mantém a IA desligada.
        candidates = [k for k in dict.fromkeys([chat_id, *sorted((aliases or {}).get(chat_id, ()))]) if k]
        records = [contacts.get(k) for k in candidates if isinstance(contacts.get(k), dict)]
        if any(r.get("blocked") is True for r in records):
            continue
        if not any(r.get("ai_disabled_reason") == LEGACY_AI_OFF_REASON for r in records):
            continue
        keys: list[str] = []
        for k in candidates:
            keys.extend(_mirror_keys(contacts, k))
        keys = list(dict.fromkeys(keys))
        contacts = _apply_ai_enable(paths, keys, flow_origin="reactivation_optin")
        count += 1
    return count


def reactivation_suggest(paths: panel_data.Paths, *, chat_id: str) -> dict:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    try:
        entry = reactivation_store.get_entry(paths.followups_db, chat_id)
    except ValueError:
        entry = None
    if entry is None:
        raise ActionError("Contato não está na lista de reativação.")

    variant = (
        (int(entry.get("message_variant") or 0) + 1) % reactivation_store.SUGGESTION_VARIANTS
        if entry.get("message")
        else 0
    )
    contacts = contacts_store.read_contacts(paths.contacts_json)
    name = panel_data._contact_name(contacts, chat_id)
    if panel_data._is_placeholder_name(name) or name.strip() == "identidade LID":
        name = ""
    message = reactivation_store.suggest_message(chat_id, name, variant)
    updated = reactivation_store.set_message(paths.followups_db, chat_id, message, variant=variant)
    return {"chat_id": chat_id, "message": updated["message"], "message_variant": updated["message_variant"]}


def reactivation_message(paths: panel_data.Paths, *, chat_id: str, message: str) -> dict:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    try:
        updated = reactivation_store.set_message(paths.followups_db, chat_id, str(message or ""))
    except (KeyError, ValueError):
        raise ActionError("Contato não está na lista de reativação.") from None
    return {"chat_id": chat_id, "message": updated["message"], "message_variant": updated["message_variant"]}


def reactivation_sent(paths: panel_data.Paths, *, chat_id: str, sent: Any) -> dict:
    chat_id = str(chat_id or "").strip()
    if not chat_id:
        raise ActionError("chat_id é obrigatório.")
    if not isinstance(sent, bool):
        raise ActionError("sent deve ser true ou false.")
    try:
        updated = reactivation_store.mark_sent(paths.followups_db, chat_id, sent=sent)
    except (KeyError, ValueError):
        raise ActionError("Contato não está na lista de reativação.") from None
    return {"chat_id": chat_id, "sent_utc": updated["sent_utc"]}
