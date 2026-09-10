from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import management_store as store  # noqa: E402

SPEC = importlib.util.spec_from_file_location("import_notion_management", ROOT / "deploy/scripts/import_notion_management.py")
assert SPEC and SPEC.loader
imp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(imp)


def _title(text):
    return {"type": "title", "title": [{"plain_text": text}]}


def _rich(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text}]}


def _select(name):
    return {"type": "select", "select": {"name": name} if name else None}


def _status(name):
    return {"type": "status", "status": {"name": name}}


def _date(start):
    return {"type": "date", "date": {"start": start} if start else None}


CLIENT_PAGE_ID = "3c051bcc-d195-81c8-9af1-d20cfef21738"
CLIENT_PAGE = {
    "id": CLIENT_PAGE_ID,
    "created_time": "2026-08-20T14:05:00.000Z",
    "properties": {
        "Cliente": _title("Ana Ribeiro"),
        "Empresa": _rich("Clínica Aurora"),
        "Segmento": _rich("Saúde"),
        "WhatsApp": _rich("+55 (11) 99999-0001"),
        "E-mail": {"type": "email", "email": "gv@example.com"},
        "Tipo": _select("IA ATENDIMENTO"),
        "Status": _status("Ativo"),
        "Mensalidade": {"type": "number", "number": 1497},
        "Próxima Cobrança": _date("2026-10-05"),
        "Data de Início da Implementação": _date("2026-08-01"),
        "Data da Ativação": _date("2026-08-10"),
        "Link Supabase": {"type": "url", "url": "https://painel.example.com"},
        "Pendência Atual": _rich("Trocar senha root: senha atual Abc123!@# e chave sk-or-v1-abcdefabcdefabcdefabcdef"),
    },
}
TICKET_PAGE = {
    "id": "t-1",
    "created_time": "2026-08-22T03:10:00.000Z",
    "properties": {
        "Ticket": _title("QA V1 da SDR — devolutiva dos 6 bloqueadores"),
        "Descrição": _rich("Cliente informou CPF 123.456.789-09 e pediu retorno. Preço R$ 1.497,00."),
        "Resolução": _rich(""),
        "Tipo": _select("Incidente"),
        "Prioridade": _select("Alta"),
        "Origem": _select("Interno"),
        "Status": _select("Aguardando cliente"),
        "Prazo": _date(None),
        "Cliente": {"type": "relation", "relation": [{"id": CLIENT_PAGE_ID}]},
    },
}
RESOLVED_TICKET_PAGE = {
    "id": "t-2",
    "created_time": "2026-08-21T10:00:00.000Z",
    "properties": {
        "Ticket": _title("Vendas — comandos de revisão quebram no teste"),
        "Tipo": _select("Solicitação"),
        "Prioridade": _select("Média"),
        "Origem": _select("Interno"),
        "Status": _select("Resolvido"),
        "Cliente": {"type": "relation", "relation": []},
    },
}


class MappingTests(unittest.TestCase):
    def test_client_mapping_translates_status_money_dates_and_redacts_pending(self):
        mapped = imp.map_client(CLIENT_PAGE)
        f = mapped["fields"]
        self.assertEqual(mapped["status"], "active")
        self.assertEqual(mapped["page_id"], CLIENT_PAGE_ID)
        self.assertEqual(mapped["created"].isoformat(), "2026-08-20T14:05:00+00:00")
        self.assertEqual((f["name"], f["company"], f["segment"], f["kind"]), ("Ana Ribeiro", "Clínica Aurora", "Saúde", "atendimento"))
        self.assertEqual((f["monthly_cents"], f["billing_day"]), (149700, 5))
        self.assertEqual((f["started_on"], f["activated_on"]), ("2026-08-01", "2026-08-10"))
        self.assertEqual(f["environment_url"], "https://painel.example.com")
        self.assertEqual(f["phone"], "+55 (11) 99999-0001")  # o store reduz a dígitos
        # a pendência do Notion nunca entra: é onde a credencial de produção vivia
        self.assertEqual(f["notes"], imp.PENDING_NOTICE)
        self.assertNotIn("Abc123", f["notes"])
        empty = dict(CLIENT_PAGE, properties={**CLIENT_PAGE["properties"], "Pendência Atual": _rich("")})
        self.assertIsNone(imp.map_client(empty)["fields"]["notes"])

    def test_ticket_text_drops_tokens_but_keeps_price(self):
        page = dict(TICKET_PAGE, properties={**TICKET_PAGE["properties"],
                    "Descrição": _rich("chave sk-or-v1-abcdefabcdefabcdefabcdef e ntn_123456789abc, preço R$ 997,00"),
                    "Resolução": _rich("rotacionada para ghp_abcdefghijklmnop")})
        mapped = imp.map_ticket(page, {})
        self.assertNotIn("sk-or-v1", mapped["fields"]["description"])
        self.assertNotIn("ntn_1234", mapped["fields"]["description"])
        self.assertIn("R$ 997,00", mapped["fields"]["description"])
        self.assertEqual(mapped["resolution"], "rotacionada para [chave]")

    def test_client_status_fallbacks(self):
        for notion, ours in (("Onboarding Pendente", "onboarding"), ("QA Final", "qa"), ("Aguardando Aprovação", "qa"),
                             ("Cancelado", "cancelled"), ("", "negotiation"), ("Coisa nova", "negotiation")):
            page = {"id": "x", "properties": {"Cliente": _title("A"), "Status": _status(notion) if notion else {}}}
            self.assertEqual(imp.map_client(page)["status"], ours, notion)
        late = {"id": "x", "properties": {"Cliente": _title("A"), "Próxima Cobrança": _date("2026-10-31")}}
        self.assertEqual(imp.map_client(late)["fields"]["billing_day"], 28)

    def test_ticket_mapping_links_client_redacts_and_fills_missing_resolution(self):
        mapped = imp.map_ticket(TICKET_PAGE, {CLIENT_PAGE_ID: 7})
        f = mapped["fields"]
        self.assertEqual((mapped["status"], mapped["client_id"], mapped["resolution"]), ("waiting_client", 7, None))
        self.assertEqual((f["kind"], f["priority"], f["origin"], f["due_on"]), ("incident", "high", "internal", None))
        self.assertNotIn("123.456.789-09", f["description"])
        self.assertIn("R$ 1.497,00", f["description"])
        resolved = imp.map_ticket(RESOLVED_TICKET_PAGE, {})
        self.assertEqual((resolved["status"], resolved["client_id"], resolved["resolution"]),
                         ("resolved", None, imp.MISSING_RESOLUTION))
        unknown_client = imp.map_ticket(TICKET_PAGE, {})
        self.assertIsNone(unknown_client["client_id"])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "management.db"

    def test_import_is_idempotent_and_keeps_notion_timestamps(self):
        client_id, created = imp.import_client(self.db, imp.map_client(CLIENT_PAGE))
        self.assertTrue(created)
        again, created_again = imp.import_client(self.db, imp.map_client(CLIENT_PAGE))
        self.assertEqual((again, created_again), (client_id, False))

        by_page = {CLIENT_PAGE_ID: client_id}
        ticket_id, created = imp.import_ticket(self.db, imp.map_ticket(TICKET_PAGE, by_page))
        self.assertTrue(created)
        self.assertEqual(imp.import_ticket(self.db, imp.map_ticket(TICKET_PAGE, by_page)), (ticket_id, False))
        resolved_id, _ = imp.import_ticket(self.db, imp.map_ticket(RESOLVED_TICKET_PAGE, by_page))

        client = store.get_client(self.db, client_id)
        self.assertEqual((client["status"], client["phone"], client["monthly_cents"]), ("active", "5511999990001", 149700))
        self.assertEqual(client["created_utc"], "2026-08-20T14:05:00+00:00")
        self.assertEqual(client["open_tickets"], 1)
        self.assertTrue(any("notion:" in (e["note"] or "") for e in client["events"]))

        ticket = store.get_ticket(self.db, ticket_id)
        self.assertEqual((ticket["status"], ticket["client_id"], ticket["opened_utc"]), ("waiting_client", client_id, "2026-08-22T03:10:00+00:00"))
        self.assertEqual([e["to_status"] for e in ticket["events"] if e["kind"] == "status"], ["open", "waiting_client"])
        resolved = store.get_ticket(self.db, resolved_id)
        self.assertEqual((resolved["status"], resolved["resolution"], resolved["client_id"]),
                         ("resolved", imp.MISSING_RESOLUTION, None))
        self.assertEqual(len(store.list_tickets(self.db)), 2)


if __name__ == "__main__":
    unittest.main()
