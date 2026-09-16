"""Contato ativo com quem terminou o quiz da LP e não chamou no WhatsApp.

Módulo puro, no molde de `daily_audit`: decide quem está na hora e escreve a
primeira mensagem; quem envia é `actions.lp_outreach`, e quem agenda é
`marketing_service`. A regra é conservadora de propósito:

- Só lead com nome e WhatsApp válidos (é o que `lp_leads` guarda).
- Só depois de `delay_min` sem nenhuma mensagem do lead com o id da sessão —
  quem clicou e chegou não recebe mensagem fria por cima da conversa.
- Uma vez por sessão: `contacted_at` preenchido encerra o assunto, mesmo que
  o envio tenha falhado (o status diz o que houve; ninguém insiste sozinho).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def chat_id_for(phone: str) -> str:
    """WhatsApp brasileiro: 55 + DDD + celular, sufixo do bridge."""
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) == 11:
        digits = "55" + digits
    return f"{digits}@s.whatsapp.net"


def due(leads: list[dict], arrived_session_ids: set[str], *, now: datetime, delay_min: int = 30) -> list[dict]:
    """Leads na hora de receber a primeira mensagem, do mais antigo para o mais novo."""
    cutoff = now - timedelta(minutes=max(1, int(delay_min)))
    out = []
    for lead in leads:
        if lead.get("contacted_at") or lead.get("session_id") in arrived_session_ids:
            continue
        reached_end = _parse(lead.get("completed_at")) or _parse(lead.get("clicked_at"))
        if reached_end is None or reached_end > cutoff:
            continue
        out.append(lead)
    out.sort(key=lambda lead: lead.get("completed_at") or lead.get("clicked_at") or "")
    return out


def first_message(lead: dict, *, assistant_name: str = "AYA", site: str = "agenteaya.com") -> str:
    """Curta, pelo nome, citando o que a pessoa respondeu, sem promessa.
    Termina com uma pergunta para a conversa continuar do outro lado."""
    first = (lead.get("name") or "").strip().split()[0] if (lead.get("name") or "").strip() else ""
    answers = lead.get("answers") or {}
    niche = (answers.get("niche") or "").strip()
    business = (answers.get("negocio") or "").strip()
    pain = (answers.get("problema") or "").strip()
    what = " · ".join(part for part in (niche, business) if part)

    lines = [f"Oi{', ' + first if first else ''}! Aqui é a {assistant_name}, do site {site}."]
    context = []
    if what:
        context.append(f"você contou que atua com {what}")
    if pain:
        context.append(f"que o que mais pesa hoje é \"{pain[0].lower() + pain[1:]}\"")
    if context:
        lines.append("Você respondeu o quiz e " + " e ".join(context) + ".")
    lines.append("Estou te chamando pelo número que você deixou, como combinado lá.")
    lines.append("Quer que eu te mostre, em duas mensagens, como eu entraria no seu WhatsApp para resolver isso?")
    return "\n".join(lines)


def status_of(lead: dict, arrived_session_ids: set[str], *, now: datetime, delay_min: int = 30) -> str:
    """Rótulo para a lista do painel."""
    if lead.get("session_id") in arrived_session_ids:
        return "chegou"
    if lead.get("contacted_at"):
        return {"sent": "aya_chamou", "blocked": "bloqueado", "failed": "falhou"}.get(lead.get("contact_status") or "", "aya_chamou")
    reached_end = _parse(lead.get("completed_at")) or _parse(lead.get("clicked_at"))
    if reached_end and reached_end > now - timedelta(minutes=max(1, int(delay_min))):
        return "aguardando"
    return "na_fila"
