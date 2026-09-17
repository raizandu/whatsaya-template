#!/usr/bin/env python3
"""Importação única da Central de Operações do Notion para o `management.db`.

Traz os clientes da base "Clientes AYA" (data source "Clientes - WhatsAYA") e
os tickets de "Tickets — Suporte". Nada mais: CRM e follow-ups já vivem no
painel, onboarding e pós-venda no Notion estavam vazios.

Dry-run por padrão; `--apply` grava. Idempotente: cada linha importada deixa
um evento `notion:<page_id>` e a segunda rodada pula o que já entrou.

Corpo de ticket passa por `daily_audit.redact` mais um corte de token antes
de gravar. "Pendência Atual" do cliente **não é importada**: é o campo que tinha
credencial de produção em texto aberto (TKT-1), e detector de senha livre não
existe — entra só um aviso de que havia pendência no Notion. O conteúdo das
páginas (blocos filhos) não é lido de propósito.

Roda dentro do container `hermes`, onde estão a chave e o volume:

    docker exec hermes python3 /opt/data/.hermes/plugins/whatsapp-manager/deploy/scripts/import_notion_management.py
    docker exec hermes python3 .../import_notion_management.py --apply

Env: `NOTION_API_KEY` (integração interna), `WHATSAPP_MANAGEMENT_DB` (padrão
/opt/data/.hermes/management.db). Os ids das bases têm default e aceitam
override por `--clients-db` / `--tickets-db`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import daily_audit  # noqa: E402
import management_store as store  # noqa: E402

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
DEFAULT_CLIENTS_DB = "3bf51bcc-d195-801c-a82d-cc653ead6654"
DEFAULT_TICKETS_DB = "dba0f3b3-ae8e-4e8a-a796-af02a86c9740"
CLIENTS_SOURCE_NAME = "Clientes - WhatsAYA"

CLIENT_STATUS_MAP = {
    "Negociação": "negotiation",
    "Aguardando Pagamento": "awaiting_payment",
    "Onboarding": "onboarding",
    "Onboarding Pendente": "onboarding",
    "Onboarding Preenchido": "onboarding",
    "Implementação": "implementation",
    "QA Interno": "qa",
    "Ajustes": "qa",
    "QA Final": "qa",
    "Aguardando Aprovação": "qa",
    "Ativo": "active",
    "Pausado": "paused",
    "Cancelado": "cancelled",
}
CLIENT_KIND_MAP = {"IA ATENDIMENTO": "atendimento", "Reativação": "reativacao", "Teste": "teste"}
TICKET_KIND_MAP = {
    "Incidente": "incident", "Dúvida": "question", "Solicitação": "request",
    "Melhoria": "improvement", "Financeiro": "billing", "Outro": "other",
}
TICKET_PRIORITY_MAP = {"Crítica": "critical", "Alta": "high", "Média": "medium", "Baixa": "low"}
TICKET_ORIGIN_MAP = {"WhatsApp": "whatsapp", "Interno": "internal", "E-mail": "email", "Outro": "other"}
TICKET_STATUS_MAP = {
    "Aberto": "open", "Triagem": "triage", "Em andamento": "in_progress",
    "Aguardando cliente": "waiting_client", "Aguardando terceiro": "waiting_third_party",
    "Resolvido": "resolved", "Fechado": "closed",
}
MISSING_RESOLUTION = "(importado do Notion sem resolução registrada)"
PENDING_NOTICE = "Havia uma pendência técnica registrada no card do Notion; confira lá antes de descartar o card."
# Token com prefixo conhecido ou sequência longa sem espaço: `redact` cobre
# documento, telefone, e-mail e UUID, não chave de API.
_TOKEN_RE = re.compile(r"\b(?:sk-[\w-]{8,}|ntn_\w{8,}|secret_\w{8,}|ghp_\w{8,}|AKIA\w{12,}|[A-Za-z0-9_\-]{40,})\b")


def scrub(text: str) -> str:
    return _TOKEN_RE.sub("[chave]", daily_audit.redact(text))


# ── leitura de propriedades do Notion ───────────────────────────────────────

def prop_text(props: dict, name: str) -> str:
    value = props.get(name) or {}
    kind = value.get("type")
    parts = value.get(kind) if kind in ("title", "rich_text") else None
    if not isinstance(parts, list):
        return ""
    return "".join(p.get("plain_text", "") for p in parts).strip()


def prop_select(props: dict, name: str) -> str:
    value = props.get(name) or {}
    kind = value.get("type")
    inner = value.get(kind) if kind in ("select", "status") else None
    return str((inner or {}).get("name") or "").strip()


def prop_date(props: dict, name: str) -> str | None:
    value = props.get(name) or {}
    inner = value.get("date") if value.get("type") == "date" else None
    start = (inner or {}).get("start")
    return str(start)[:10] if start else None


def prop_number(props: dict, name: str):
    value = props.get(name) or {}
    return value.get("number") if value.get("type") == "number" else None


def prop_email(props: dict, name: str) -> str:
    value = props.get(name) or {}
    return str(value.get("email") or "").strip() if value.get("type") == "email" else ""


def prop_url(props: dict, name: str) -> str:
    value = props.get(name) or {}
    return str(value.get("url") or "").strip() if value.get("type") == "url" else ""


def prop_relation_ids(props: dict, name: str) -> list[str]:
    value = props.get(name) or {}
    rel = value.get("relation") if value.get("type") == "relation" else None
    return [str(r.get("id")) for r in (rel or []) if r.get("id")]


def _created(page: dict) -> datetime:
    raw = str(page.get("created_time") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


# ── mapeamento (puro, testável) ─────────────────────────────────────────────

def map_client(page: dict) -> dict:
    props = page.get("properties") or {}
    status = CLIENT_STATUS_MAP.get(prop_select(props, "Status"), "negotiation")
    monthly = prop_number(props, "Mensalidade") or 0
    next_charge = prop_date(props, "Próxima Cobrança")
    billing_day = None
    if next_charge:
        day = int(next_charge[8:10])
        billing_day = day if 1 <= day <= 28 else 28
    pending = PENDING_NOTICE if prop_text(props, "Pendência Atual") else None
    return {
        "page_id": str(page.get("id") or ""),
        "created": _created(page),
        "status": status,
        "fields": {
            "name": prop_text(props, "Cliente") or "Sem nome",
            "company": prop_text(props, "Empresa") or None,
            "segment": prop_text(props, "Segmento") or None,
            "phone": prop_text(props, "WhatsApp") or None,
            "email": prop_email(props, "E-mail") or None,
            "kind": CLIENT_KIND_MAP.get(prop_select(props, "Tipo")),
            "monthly_cents": int(round(float(monthly) * 100)),
            "billing_day": billing_day,
            "started_on": prop_date(props, "Data de Início da Implementação") or prop_date(props, "Data do Onboarding"),
            "activated_on": prop_date(props, "Data da Ativação"),
            "environment_url": prop_url(props, "Link Supabase") or None,
            "notes": pending,
        },
    }


def map_ticket(page: dict, client_ids_by_page: dict[str, int]) -> dict:
    props = page.get("properties") or {}
    status = TICKET_STATUS_MAP.get(prop_select(props, "Status"), "open")
    resolution = scrub(prop_text(props, "Resolução"))
    if status in store.TICKET_DONE and not resolution:
        resolution = MISSING_RESOLUTION
    related = prop_relation_ids(props, "Cliente")
    client_id = next((client_ids_by_page[r] for r in related if r in client_ids_by_page), None)
    return {
        "page_id": str(page.get("id") or ""),
        "created": _created(page),
        "status": status,
        "resolution": resolution or None,
        "client_id": client_id,
        "fields": {
            "title": prop_text(props, "Ticket") or "Sem título",
            "description": scrub(prop_text(props, "Descrição")) or None,
            "kind": TICKET_KIND_MAP.get(prop_select(props, "Tipo"), "other"),
            "priority": TICKET_PRIORITY_MAP.get(prop_select(props, "Prioridade"), "medium"),
            "origin": TICKET_ORIGIN_MAP.get(prop_select(props, "Origem"), "other"),
            "due_on": prop_date(props, "Prazo"),
        },
    }


# ── gravação (idempotente) ──────────────────────────────────────────────────

def _marker(page_id: str) -> str:
    return f"notion:{page_id}"


def already_imported(db_path, table: str, page_id: str) -> int | None:
    """Devolve o id local (cliente ou ticket) se a página já entrou."""
    column, kind = ("client_id", "note") if table == "client_events" else ("ticket_id", "comment")
    with store._read(db_path) as conn:
        row = conn.execute(
            f"SELECT {column} FROM {table} WHERE kind = ? AND note LIKE ? LIMIT 1",
            (kind, f"%{_marker(page_id)}%"),
        ).fetchone()
    return int(row[0]) if row else None


def import_client(db_path, mapped: dict) -> tuple[int, bool]:
    existing = already_imported(db_path, "client_events", mapped["page_id"])
    if existing:
        return existing, False
    client = store.create_client(db_path, status=mapped["status"], now=mapped["created"], **mapped["fields"])
    store.add_client_note(db_path, client["id"], f"Importado do Notion ({_marker(mapped['page_id'])})", now=mapped["created"])
    return client["id"], True


def import_ticket(db_path, mapped: dict) -> tuple[int, bool]:
    existing = already_imported(db_path, "ticket_events", mapped["page_id"])
    if existing:
        return existing, False
    ticket = store.create_ticket(
        db_path, client_id=mapped["client_id"], status="open", now=mapped["created"], **mapped["fields"],
    )
    if mapped["status"] != "open":
        store.set_ticket_status(
            db_path, ticket["id"], mapped["status"], resolution=mapped["resolution"], now=mapped["created"],
            note="status trazido do Notion",
        )
    elif mapped["resolution"]:
        store.update_ticket(db_path, ticket["id"], resolution=mapped["resolution"])
    store.add_ticket_comment(db_path, ticket["id"], f"Importado do Notion ({_marker(mapped['page_id'])})", now=mapped["created"])
    return ticket["id"], True


# ── Notion ──────────────────────────────────────────────────────────────────

class NotionClient:
    def __init__(self, key: str):
        self.key = key

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            NOTION_API + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.key}", "Notion-Version": NOTION_VERSION,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise SystemExit(f"Notion {exc.code} em {path}: {detail}") from exc

    def data_source_id(self, database_id: str, prefer_name: str | None = None) -> str:
        db = self.call("GET", f"/databases/{database_id}")
        sources = db.get("data_sources") or []
        if not sources:
            raise SystemExit(f"Base {database_id} sem data source visível (a integração está compartilhada?).")
        if prefer_name:
            for source in sources:
                if source.get("name") == prefer_name:
                    return str(source["id"])
        return str(sources[0]["id"])

    def query_all(self, data_source_id: str) -> list[dict]:
        pages, cursor = [], None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            result = self.call("POST", f"/data_sources/{data_source_id}/query", body)
            pages.extend(result.get("results") or [])
            if not result.get("has_more"):
                return pages
            cursor = result.get("next_cursor")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="grava no banco (padrão: só mostra)")
    parser.add_argument("--db", default=os.environ.get("WHATSAPP_MANAGEMENT_DB") or "/opt/data/.hermes/management.db")
    parser.add_argument("--clients-db", default=DEFAULT_CLIENTS_DB)
    parser.add_argument("--tickets-db", default=DEFAULT_TICKETS_DB)
    args = parser.parse_args(argv)

    key = (os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN") or "").strip()
    if not key:
        print("NOTION_API_KEY ausente.", file=sys.stderr)
        return 2
    notion = NotionClient(key)

    clients_source = notion.data_source_id(args.clients_db, prefer_name=CLIENTS_SOURCE_NAME)
    tickets_source = notion.data_source_id(args.tickets_db)
    client_pages = notion.query_all(clients_source)
    ticket_pages = notion.query_all(tickets_source)

    mode = "APLICANDO" if args.apply else "DRY-RUN"
    print(f"[{mode}] banco={args.db} · {len(client_pages)} clientes e {len(ticket_pages)} tickets no Notion")

    client_ids_by_page: dict[str, int] = {}
    summary = {"clients_new": 0, "clients_skipped": 0, "tickets_new": 0, "tickets_skipped": 0}
    for page in client_pages:
        mapped = map_client(page)
        f = mapped["fields"]
        print(f"  cliente · {f['name']!r} ({f['company'] or '—'}) status={mapped['status']} mensalidade={f['monthly_cents']/100:.2f}"
              f" venc={f['billing_day']} ativado={f['activated_on']}")
        if args.apply:
            client_id, created = import_client(args.db, mapped)
            client_ids_by_page[mapped["page_id"]] = client_id
            summary["clients_new" if created else "clients_skipped"] += 1
        else:
            client_ids_by_page[mapped["page_id"]] = -1

    for page in ticket_pages:
        mapped = map_ticket(page, client_ids_by_page)
        f = mapped["fields"]
        who = "cliente vinculado" if mapped["client_id"] else "sem cliente"
        print(f"  ticket · {f['title'][:60]!r} {f['kind']}/{f['priority']}/{f['origin']} status={mapped['status']} {who}")
        if args.apply:
            _tid, created = import_ticket(args.db, mapped)
            summary["tickets_new" if created else "tickets_skipped"] += 1

    if args.apply:
        print(f"[ok] {summary}")
    else:
        print("[dry-run] nada gravado. Rode com --apply para importar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
