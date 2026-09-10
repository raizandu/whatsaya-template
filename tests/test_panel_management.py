"""Módulo de gestão da carteira: rotas do painel (`panel/data.py`, `panel/actions.py`,
`panel/server.py`). O store puro (`management_store.py`) já é coberto em
`tests/test_management_store.py` — aqui só a camada do painel: flag,
tradução HTTP, regras de fluxo e o vínculo lead → cliente.
"""
from __future__ import annotations

import base64
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import management_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402
from panel import actions as panel_actions  # noqa: E402
from panel import data as panel_data  # noqa: E402
from panel import server as panel_server  # noqa: E402
from tests.test_panel_actions import FakeBridge, OWNER_DIGITS  # noqa: E402
from tests.test_panel_data import LEAD, LEAD2, LEAD_LID, NOW, PanelFixture  # noqa: E402


class _ManagementServerCase(PanelFixture):
    """Sobe o servidor do painel com `management_db` num arquivo temporário e a
    flag `features.management` ligada por padrão (via `panel.config.json`
    apontado para um caminho temporário)."""

    def setUp(self):
        super().setUp()
        self.paths = replace(self.paths, management_db=Path(self.tmp.name) / "management.db")
        self.config_path = Path(self.tmp.name) / "panel.config.json"
        self._set_management_flag(True)
        self._config_patch = patch.object(panel_server, "CONFIG_PATH", self.config_path)
        self._config_patch.start()
        self.bridge = FakeBridge()
        config = panel_server.Config(
            username="dono", password="segredo-forte", bridge_url="http://127.0.0.1:1",
            bridge_host_header="", minutes_per_resolved=6, hourly_rate_brl=38, owner_number=OWNER_DIGITS,
            hermes_dashboard_url="http://127.0.0.1:1", whatsapp_mode="bot", whatsapp_allowed_users="*",
            google_client_id="", google_client_secret="", public_url="",
        )
        handler = panel_server.make_handler(config, self.paths, self.bridge)
        self.httpd = panel_server.PanelServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._config_patch.stop()
        super().tearDown()

    def _set_management_flag(self, enabled: bool) -> None:
        self.config_path.write_text(json.dumps({"features": {"management": enabled}}), encoding="utf-8")

    def _request(self, method: str, path: str, body=None, auth="dono:segredo-forte", raw=None):
        data = None
        if method == "POST":
            data = raw if raw is not None else json.dumps(body or {}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if method == "POST":
            req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            try:
                return exc.code, json.loads(raw_body or b"{}")
            except ValueError:
                return exc.code, {"text": raw_body.decode("utf-8", "replace")}

    def _get(self, path, auth="dono:segredo-forte"):
        return self._request("GET", path, auth=auth)

    def _post(self, path, body, auth="dono:segredo-forte", raw=None):
        return self._request("POST", path, body=body, auth=auth, raw=raw)

    def _create_client(self, **fields) -> dict:
        body = {"name": "Cliente Teste"}
        body.update(fields)
        status, resp = self._post("/api/actions/management/client-create", body)
        assert status == 200, resp
        return resp["client"]


class ManagementFeatureFlagTest(_ManagementServerCase):
    def test_flag_off_hides_read_and_write_routes(self):
        self._set_management_flag(False)
        status, _ = self._get("/api/management/clients")
        self.assertEqual(status, 404)
        status, _ = self._post("/api/actions/management/client-create", {"name": "Fulano"})
        self.assertEqual(status, 404)
        status, body = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(body["management"], {"enabled": False})

    def test_flag_on_exposes_config_with_client_status_labels(self):
        status, body = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertTrue(body["management"]["enabled"])
        self.assertEqual(body["management"]["labels"]["client_status"]["active"], "Ativo")
        self.assertEqual(body["management"]["labels"]["client_status"]["cancelled"], "Cancelado")


class ManagementReadRoutesTest(_ManagementServerCase):
    def test_clients_list_has_counts_and_mrr(self):
        self._create_client(name="Ana Ativa", status="active", monthly_cents=120_000, activated_on="2026-08-01")
        self._create_client(name="Beto Negociando")
        status, body = self._get("/api/management/clients")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["clients"]), 2)
        self.assertEqual(body["counts"]["active"], 1)
        self.assertEqual(body["counts"]["negotiation"], 1)
        self.assertEqual(body["mrr_cents"], 120_000)

    def test_client_detail_found_and_not_found(self):
        client = self._create_client(name="Carla Cliente")
        status, body = self._get(f"/api/management/client/{client['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "Carla Cliente")
        self.assertIn("events", body)
        status, _ = self._get("/api/management/client/999999")
        self.assertEqual(status, 404)
        status, _ = self._get("/api/management/client/abc")
        self.assertEqual(status, 404)

    def test_tickets_list_filters_by_status_client_and_open(self):
        client = self._create_client(name="Dora Cliente")
        status, open_ticket = self._post("/api/actions/management/ticket-create", {
            "title": "Erro no bridge", "kind": "incident", "priority": "high",
            "origin": "internal", "client_id": client["id"],
        })
        self.assertEqual(status, 200)
        status, internal_ticket = self._post("/api/actions/management/ticket-create", {
            "title": "Dúvida interna", "kind": "question",
        })
        self.assertEqual(status, 200)
        status, _ = self._post("/api/actions/management/ticket-status", {
            "id": internal_ticket["ticket"]["id"], "status": "resolved", "resolution": "Respondido",
        })
        self.assertEqual(status, 200)

        status, body = self._get("/api/management/tickets?status=open")
        self.assertEqual(status, 200)
        ids = {t["id"] for t in body["tickets"]}
        self.assertIn(open_ticket["ticket"]["id"], ids)
        self.assertNotIn(internal_ticket["ticket"]["id"], ids)

        status, body = self._get(f"/api/management/tickets?client_id={client['id']}")
        self.assertEqual(status, 200)
        self.assertEqual([t["id"] for t in body["tickets"]], [open_ticket["ticket"]["id"]])

        status, body = self._get("/api/management/tickets?open=1")
        self.assertEqual(status, 200)
        ids = {t["id"] for t in body["tickets"]}
        self.assertIn(open_ticket["ticket"]["id"], ids)
        self.assertNotIn(internal_ticket["ticket"]["id"], ids)

    def test_ticket_detail_found_and_not_found(self):
        status, created = self._post("/api/actions/management/ticket-create", {"title": "Ticket solto"})
        self.assertEqual(status, 200)
        ticket_id = created["ticket"]["id"]
        status, body = self._get(f"/api/management/ticket/{ticket_id}")
        self.assertEqual(status, 200)
        self.assertIn("events", body)
        status, _ = self._get("/api/management/ticket/999999")
        self.assertEqual(status, 404)

    def test_finance_materializes_active_client_charge(self):
        self._create_client(
            name="Elisa Ativa", status="active", monthly_cents=150_000,
            activated_on="2026-08-15", billing_day=15,
        )
        status, body = self._get("/api/management/finance?period=2026-09")
        self.assertEqual(status, 200)
        self.assertEqual(body["mrr_cents"], 150_000)
        self.assertEqual(body["expected_cents"], 150_000)
        self.assertIn("cost_plans", body)


class ManagementActionRoutesTest(_ManagementServerCase):
    def test_client_create_success_and_rejects_invalid_body(self):
        status, body = self._post("/api/actions/management/client-create", {"name": "Fabio Fundador"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["client"]["status"], "negotiation")

        status, body = self._post("/api/actions/management/client-create", {"company": "Sem nome"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")
        self.assertIn("obrigatório", body["detail"])

    def test_client_status_follows_allowed_transitions(self):
        client = self._create_client(name="Ana Progressão")
        client_id = client["id"]

        def move(target, note=None):
            body = {"id": client_id, "status": target}
            if note:
                body["note"] = note
            return self._post("/api/actions/management/client-status", body)

        for target in ("awaiting_payment", "onboarding"):
            status, body = move(target)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["client"]["status"], target)

        detail = panel_data.management_client(self.paths, client_id)
        self.assertEqual(len(detail["onboarding"]), 8)

        for target in ("implementation", "qa"):
            status, body = move(target)
            self.assertEqual(status, 200, body)

        status, body = move("onboarding")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")

        status, body = move("active")
        self.assertEqual(status, 200, body)
        status, body = move("paused", note="cliente pediu pausa")
        self.assertEqual(status, 200, body)
        status, body = move("active")
        self.assertEqual(status, 200, body)
        status, body = move("cancelled")
        self.assertEqual(status, 200, body)
        status, body = move("active")
        self.assertEqual(status, 400)

    def test_client_note_records_event(self):
        client = self._create_client(name="Helena Nota")
        status, body = self._post("/api/actions/management/client-note", {
            "id": client["id"], "note": "Ligou perguntando sobre fatura.",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["event"]["note"], "Ligou perguntando sobre fatura.")
        self.assertEqual(body["client"]["id"], client["id"])

    def test_onboarding_step_three_modes(self):
        client = self._create_client(name="Igor Onboarding")
        client_id = client["id"]
        self._post("/api/actions/management/client-status", {"id": client_id, "status": "awaiting_payment"})
        status, body = self._post("/api/actions/management/client-status", {"id": client_id, "status": "onboarding"})
        self.assertEqual(status, 200, body)
        detail = panel_data.management_client(self.paths, client_id)
        first_step = detail["onboarding"][0]

        status, body = self._post("/api/actions/management/onboarding-step", {"id": first_step["id"], "done": True})
        self.assertEqual(status, 200)
        self.assertIsNotNone(body["step"]["done_utc"])

        status, body = self._post("/api/actions/management/onboarding-step", {
            "client_id": client_id, "title": "Passo extra combinado com o cliente",
        })
        self.assertEqual(status, 200)
        new_step_id = body["step"]["id"]
        self.assertEqual(body["step"]["title"], "Passo extra combinado com o cliente")

        status, body = self._post("/api/actions/management/onboarding-step", {
            "id": new_step_id, "delete": True,
        })
        self.assertEqual(status, 200)
        self.assertIsNone(body["step"])
        final = panel_data.management_client(self.paths, client_id)
        self.assertEqual(len(final["onboarding"]), 8)

    def test_ticket_lifecycle_over_http(self):
        status, created = self._post("/api/actions/management/ticket-create", {
            "title": "Erro no bridge", "kind": "incident", "priority": "high", "origin": "internal",
        })
        self.assertEqual(status, 200)
        ticket_id = created["ticket"]["id"]

        status, body = self._post("/api/actions/management/ticket-status", {
            "id": ticket_id, "status": "resolved",
        })
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")

        status, body = self._post("/api/actions/management/ticket-status", {
            "id": ticket_id, "status": "resolved", "resolution": "Corrigido no deploy X",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["ticket"]["status"], "resolved")

        status, body = self._post("/api/actions/management/ticket-comment", {
            "id": ticket_id, "note": "Cliente confirmou a correção.",
        })
        self.assertEqual(status, 200)

        status, body = self._post("/api/actions/management/ticket-update", {
            "id": ticket_id, "priority": "critical",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["ticket"]["priority"], "critical")

    def test_touchpoint_create_and_update(self):
        client = self._create_client(name="Julia Pós-venda")
        status, body = self._post("/api/actions/management/touchpoint-create", {
            "client_id": client["id"], "kind": "checkin", "scheduled_on": "2026-09-20",
        })
        self.assertEqual(status, 200)
        tp_id = body["touchpoint"]["id"]

        status, body = self._post("/api/actions/management/touchpoint-update", {
            "id": tp_id, "done_on": "2026-09-21",
        })
        self.assertEqual(status, 400, "saúde deveria ser obrigatória quando o contato é marcado como realizado")

        status, body = self._post("/api/actions/management/touchpoint-update", {
            "id": tp_id, "done_on": "2026-09-21", "health": "healthy",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["touchpoint"]["health"], "healthy")

    def test_charge_lifecycle_over_http(self):
        client = self._create_client(
            name="Karina Financeiro", status="active", monthly_cents=100_000,
            activated_on="2026-08-01", billing_day=10,
        )
        status, finance = self._get("/api/management/finance?period=2026-09")
        self.assertEqual(status, 200)
        charge = next(c for c in finance["clients"] if c["client_id"] == client["id"])["charges"][0]

        status, body = self._post("/api/actions/management/charge-pay", {
            "id": charge["id"], "paid_on": "2026-09-10", "paid_cents": 100_000,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["charge"]["status"], "paid")

        status, body = self._post("/api/actions/management/charge-reopen", {"id": charge["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["charge"]["status"], "expected")

        status, body = self._post("/api/actions/management/charge-cancel", {"id": charge["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["charge"]["status"], "cancelled")

        status, body = self._post("/api/actions/management/charge-adhoc", {
            "client_id": client["id"], "period": "2026-09", "due_on": "2026-09-25",
            "amount_cents": 5000, "note": "Ajuste pontual",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["charge"]["kind"], "adhoc")

    def test_cost_plan_materializes_and_manual_adjustment(self):
        client = self._create_client(
            name="Lucas Custo", status="active", monthly_cents=100_000, activated_on="2026-08-01",
        )
        status, body = self._post("/api/actions/management/cost-plan-upsert", {
            "client_id": client["id"], "category": "ai", "monthly_cents": 5000,
            "label": "IA mensal", "active_from": "2026-09",
        })
        self.assertEqual(status, 200)

        status, finance = self._get("/api/management/finance?period=2026-09")
        self.assertEqual(status, 200)
        self.assertEqual(finance["costs_by_category"]["ai"], 5000)
        cost_row = next(c for c in finance["clients"] if c["client_id"] == client["id"])["costs"][0]
        self.assertEqual(cost_row["source"], "plan")

        status, body = self._post("/api/actions/management/cost-upsert", {
            "id": cost_row["id"], "amount_cents": 6000,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["cost"]["source"], "manual")
        self.assertEqual(body["cost"]["amount_cents"], 6000)

        status, body = self._post("/api/actions/management/cost-delete", {"id": cost_row["id"]})
        self.assertEqual(status, 200)
        self.assertTrue(body["deleted"])

    def test_unknown_management_action_is_not_found(self):
        status, _ = self._post("/api/actions/management/nada", {})
        self.assertEqual(status, 404)


class ServerAccessRoutesTest(_ManagementServerCase):
    def test_ssh_password_is_write_only_through_the_api(self):
        status, body = self._post("/api/actions/management/client-create", {
            "name": "Clínica Aurora", "ssh_host": "203.0.113.10", "ssh_port": 22, "ssh_user": "root", "ssh_password": "s3gr3d0",
        })
        self.assertEqual(status, 200, body)
        client = body["client"]
        self.assertNotIn("ssh_password", client)
        self.assertIs(client["ssh_password_set"], True)
        for path in (f"/api/management/client/{client['id']}", "/api/management/clients", "/api/management/finance?period=2026-09"):
            code, payload = self._get(path)
            self.assertEqual(code, 200)
            self.assertNotIn("s3gr3d0", json.dumps(payload))
            self.assertNotIn('"ssh_password"', json.dumps(payload))
        status, body = self._post("/api/actions/management/client-update", {"id": client["id"], "ssh_password": "", "ssh_user": "hermes"})
        self.assertEqual((status, body["client"]["ssh_password_set"], body["client"]["ssh_user"]), (200, True, "hermes"))
        self.assertEqual(management_store.get_ssh_credentials(self.paths.management_db, client["id"])["ssh_password"], "s3gr3d0")


class ClientStatusAllowedTest(unittest.TestCase):
    def test_transition_table(self):
        cases = [
            ("negotiation", "awaiting_payment", True),
            ("negotiation", "qa", True),  # avanço livre, não precisa ser adjacente
            ("qa", "onboarding", False),
            ("implementation", "qa", True),
            ("active", "paused", True),
            ("paused", "active", True),
            ("paused", "onboarding", False),
            ("implementation", "paused", False),
            ("negotiation", "cancelled", True),
            ("active", "cancelled", True),
            ("cancelled", "active", False),
            ("cancelled", "cancelled", False),
            ("active", "active", False),
            ("onboarding", "negotiation", False),
        ]
        for current, target, expected in cases:
            with self.subTest(current=current, target=target):
                self.assertEqual(panel_actions.client_status_allowed(current, target), expected)


class ClientFromLeadTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.paths = replace(self.paths, management_db=Path(self.tmp.name) / "management.db")

    def test_creates_awaiting_payment_client_and_marks_lead_won(self):
        engine = FollowupEngine(self.paths.followups_db)
        engine.set_estimated_value(LEAD, 480_000, now=NOW)

        result = panel_actions.client_from_lead(self.paths, {"chat_id": LEAD})

        client = result["client"]
        self.assertEqual(client["status"], "awaiting_payment")
        self.assertEqual(client["name"], "Mariana Lopes")
        self.assertTrue(client["phone"].isdigit())
        self.assertEqual(client["monthly_cents"], 480_000)
        self.assertTrue(result["lead_marked_won"])

        lead = engine.get_lead(LEAD)
        self.assertEqual(lead["stage"], "won")
        self.assertTrue(lead["terminal"])

        board = panel_data.leads(self.paths, now=NOW)
        self.assertEqual(board["terminal"]["won"], 1)
        names_on_board = [card["name"] for stage in board["stages"] for card in stage["cards"]]
        self.assertNotIn("Mariana Lopes", names_on_board)

    def test_explicit_monthly_cents_overrides_lead_estimate(self):
        engine = FollowupEngine(self.paths.followups_db)
        engine.set_estimated_value(LEAD2, 300_000, now=NOW)
        result = panel_actions.client_from_lead(self.paths, {"chat_id": LEAD2, "monthly_cents": 199_700})
        self.assertEqual(result["client"]["monthly_cents"], 199_700)

    def test_second_call_for_same_chat_is_rejected(self):
        panel_actions.client_from_lead(self.paths, {"chat_id": LEAD})
        with self.assertRaisesRegex(panel_actions.ActionError, "já é o cliente"):
            panel_actions.client_from_lead(self.paths, {"chat_id": LEAD})

    def test_lid_chat_id_is_rejected(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.client_from_lead(self.paths, {"chat_id": LEAD_LID})

    def test_unknown_contact_still_creates_client_without_marking_lead(self):
        chat_id = "5511900000000@s.whatsapp.net"
        result = panel_actions.client_from_lead(self.paths, {"chat_id": chat_id})
        self.assertFalse(result["lead_marked_won"])
        self.assertEqual(result["client"]["status"], "awaiting_payment")


class LeadDetailClientLinkTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.management_db = Path(self.tmp.name) / "management.db"
        self.paths = replace(self.paths, management_db=self.management_db)

    def test_client_is_none_before_linking_and_reading_does_not_create_the_db(self):
        self.assertFalse(self.management_db.exists())
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        self.assertIsNone(detail["client"])
        self.assertFalse(self.management_db.exists(), "só ler o lead não pode criar o banco de gestão")

    def test_client_appears_after_client_from_lead(self):
        panel_actions.client_from_lead(self.paths, {"chat_id": LEAD})
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        self.assertEqual(set(detail["client"]), {"id", "name", "status", "status_label"})
        self.assertEqual(detail["client"]["status"], "awaiting_payment")
        self.assertEqual(detail["client"]["status_label"], "Aguardando pagamento")


if __name__ == "__main__":
    unittest.main()
