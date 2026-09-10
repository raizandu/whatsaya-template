from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "management_store.py"
SPEC = importlib.util.spec_from_file_location("management_store", MODULE_PATH)
assert SPEC and SPEC.loader
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


def _t(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 9, 1, 12, tzinfo=UTC) + timedelta(seconds=offset_seconds)


class ManagementStoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "management.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _client(self, **over) -> dict:
        fields = {"name": "Gustavo Vieira", "company": "Clínica GV", "monthly_cents": 149700,
                  "billing_day": 5, "chat_id": "5511999990001", "status": "active",
                  "activated_on": "2026-08-01", "now": _t()}
        fields.update(over)
        return store.create_client(self.db, **fields)


class SchemaTests(ManagementStoreCase):
    def test_ensure_schema_is_idempotent(self):
        store.ensure_schema(self.db)
        store.ensure_schema(self.db)
        conn = sqlite3.connect(str(self.db))
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        self.assertTrue({"clients", "client_events", "onboarding_steps", "tickets", "ticket_events",
                         "touchpoints", "charges", "cost_plans", "costs"} <= names)


class ClientTests(ManagementStoreCase):
    def test_create_records_status_event_and_canonical_chat(self):
        client = self._client(status="negotiation")
        self.assertEqual(client["chat_id"], "5511999990001@s.whatsapp.net")
        self.assertEqual(client["status"], "negotiation")
        full = store.get_client(self.db, client["id"])
        self.assertEqual([e["to_status"] for e in full["events"]], ["negotiation"])
        self.assertEqual(full["onboarding"], [])
        self.assertEqual(store.get_client_by_chat(self.db, "5511999990001")["id"], client["id"])

    def test_chat_id_is_unique_and_rejects_lid(self):
        self._client()
        with self.assertRaisesRegex(store.ManagementError, "vinculado"):
            self._client(name="Outro")
        with self.assertRaisesRegex(store.ManagementError, "LID"):
            self._client(name="Outro", chat_id="123@lid")

    def test_create_rejects_unknown_field_and_bad_values(self):
        with self.assertRaisesRegex(store.ManagementError, "desconhecido"):
            store.create_client(self.db, name="x", fit="alto")
        with self.assertRaisesRegex(store.ManagementError, "centavos"):
            store.create_client(self.db, name="x", monthly_cents=12.5)
        with self.assertRaisesRegex(store.ManagementError, "entre 1 e 28"):
            store.create_client(self.db, name="x", billing_day=31)
        with self.assertRaisesRegex(store.ManagementError, "YYYY-MM-DD"):
            store.create_client(self.db, name="x", started_on="01/09/2026")
        with self.assertRaisesRegex(store.ManagementError, "Status inválido"):
            store.create_client(self.db, name="x", status="ganho")

    def test_status_change_writes_event_seeds_onboarding_and_dates(self):
        client = self._client(status="negotiation", activated_on=None, chat_id=None)
        today = date(2026, 9, 2)
        store.set_client_status(self.db, client["id"], "onboarding", note="pagou", now=_t(1), today=today)
        full = store.get_client(self.db, client["id"])
        self.assertEqual(full["started_on"], "2026-09-02")
        self.assertEqual([s["title"] for s in full["onboarding"]], list(store.DEFAULT_ONBOARDING_STEPS))
        self.assertEqual(full["onboarding_total"], 8)
        self.assertEqual(full["onboarding_done"], 0)
        self.assertEqual(full["onboarding_pending"], "Entrada recebida")
        self.assertEqual((full["events"][0]["from_status"], full["events"][0]["to_status"], full["events"][0]["note"]),
                         ("negotiation", "onboarding", "pagou"))

        # voltar ao onboarding não duplica o checklist
        store.set_client_status(self.db, client["id"], "qa", now=_t(2), today=today)
        store.set_client_status(self.db, client["id"], "onboarding", now=_t(3), today=today)
        self.assertEqual(store.get_client(self.db, client["id"])["onboarding_total"], 8)

        store.set_client_status(self.db, client["id"], "active", now=_t(4), today=date(2026, 9, 10))
        self.assertEqual(store.get_client(self.db, client["id"])["activated_on"], "2026-09-10")
        store.set_client_status(self.db, client["id"], "cancelled", now=_t(5), today=date(2026, 12, 1))
        self.assertEqual(store.get_client(self.db, client["id"])["churned_on"], "2026-12-01")

        with self.assertRaisesRegex(store.ManagementError, "já está"):
            store.set_client_status(self.db, client["id"], "cancelled")

    def test_update_is_partial_and_note_is_an_event(self):
        client = self._client()
        updated = store.update_client(self.db, client["id"], monthly_cents=199700, notes="renegociado", now=_t(9))
        self.assertEqual((updated["monthly_cents"], updated["notes"], updated["company"]),
                         (199700, "renegociado", "Clínica GV"))
        store.add_client_note(self.db, client["id"], "ligou pedindo relatório", now=_t(10))
        events = store.get_client(self.db, client["id"])["events"]
        self.assertEqual((events[0]["kind"], events[0]["note"]), ("note", "ligou pedindo relatório"))
        with self.assertRaisesRegex(store.ManagementError, "não encontrado"):
            store.update_client(self.db, 999, name="x")

    def test_list_aggregates_open_tickets_and_health(self):
        client = self._client()
        store.create_ticket(self.db, title="lento", client_id=client["id"], now=_t())
        done = store.create_ticket(self.db, title="ok", client_id=client["id"], now=_t())
        store.set_ticket_status(self.db, done["id"], "resolved", resolution="feito", now=_t(1))
        store.create_touchpoint(self.db, client["id"], kind="checkin", done_on="2026-08-10", health="healthy", now=_t())
        store.create_touchpoint(self.db, client["id"], kind="checkin", done_on="2026-08-20", health="at_risk", now=_t())
        store.create_touchpoint(self.db, client["id"], kind="renewal", scheduled_on="2026-09-20", now=_t())
        rows = store.list_clients(self.db)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["open_tickets"], rows[0]["health"]), (1, "at_risk"))
        self.assertEqual(store.list_clients(self.db, status="paused"), [])


class ServerAccessTests(ManagementStoreCase):
    def test_ssh_password_never_leaves_the_store_except_by_credentials_call(self):
        client = self._client(ssh_host="203.0.113.10", ssh_port=22, ssh_user="root", ssh_password="s3gr3d0")
        for row in (client, store.get_client(self.db, client["id"]), store.list_clients(self.db)[0],
                    store.get_client_by_chat(self.db, "5511999990001")):
            self.assertNotIn("ssh_password", row)
            self.assertIs(row["ssh_password_set"], True)
            self.assertEqual((row["ssh_host"], row["ssh_port"], row["ssh_user"]), ("203.0.113.10", 22, "root"))
        summary = store.finance_summary(self.db, "2026-09", today=date(2026, 9, 1))
        self.assertNotIn("ssh_password", str(summary))
        creds = store.get_ssh_credentials(self.db, client["id"])
        self.assertEqual((creds["ssh_host"], creds["ssh_user"], creds["ssh_password"]), ("203.0.113.10", "root", "s3gr3d0"))
        self.assertIsNone(store.get_ssh_credentials(self.db, 999))

    def test_blank_password_on_update_keeps_it_and_none_clears_it(self):
        client = self._client(ssh_host="vps", ssh_password="abc")
        kept = store.update_client(self.db, client["id"], ssh_password="", ssh_user="hermes")
        self.assertIs(kept["ssh_password_set"], True)
        self.assertEqual(kept["ssh_user"], "hermes")
        cleared = store.update_client(self.db, client["id"], ssh_password=None)
        self.assertIs(cleared["ssh_password_set"], False)
        self.assertIsNone(store.get_ssh_credentials(self.db, client["id"])["ssh_password"])
        with self.assertRaisesRegex(store.ManagementError, "Porta SSH"):
            store.update_client(self.db, client["id"], ssh_port=70000)

    def test_old_database_gains_the_ssh_columns_and_file_is_private(self):
        conn = sqlite3.connect(str(self.db))
        legacy = store.SCHEMA.replace(
            "  ssh_host TEXT,\n  ssh_port INTEGER,\n  ssh_user TEXT,\n  ssh_password TEXT,\n", "")
        self.assertNotIn("ssh_host", legacy.split("client_events")[0])
        conn.executescript(legacy)
        conn.close()
        client = self._client(ssh_host="vps")
        self.assertEqual(client["ssh_host"], "vps")
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)


class OnboardingTests(ManagementStoreCase):
    def test_steps_toggle_add_and_delete(self):
        client = self._client(status="onboarding", activated_on=None)
        steps = store.get_client(self.db, client["id"])["onboarding"]
        first = store.set_onboarding_step(self.db, steps[0]["id"], done=True, now=_t(1))
        self.assertIsNotNone(first["done_utc"])
        noted = store.set_onboarding_step(self.db, steps[1]["id"], pending_note="faltam as envs", now=_t(2))
        self.assertEqual(noted["pending_note"], "faltam as envs")
        summary = store.get_client(self.db, client["id"])
        self.assertEqual((summary["onboarding_done"], summary["onboarding_pending"], summary["onboarding_pending_note"]),
                         (1, steps[1]["title"], "faltam as envs"))
        extra = store.add_onboarding_step(self.db, client["id"], "Treinar equipe", now=_t(3))
        self.assertEqual(extra["position"], 9)
        self.assertTrue(store.delete_onboarding_step(self.db, extra["id"]))
        self.assertFalse(store.delete_onboarding_step(self.db, extra["id"]))
        reopened = store.set_onboarding_step(self.db, steps[0]["id"], done=False, now=_t(4))
        self.assertIsNone(reopened["done_utc"])
        with self.assertRaisesRegex(store.ManagementError, "Nada"):
            store.set_onboarding_step(self.db, steps[0]["id"])


class TicketTests(ManagementStoreCase):
    def test_lifecycle_requires_resolution_and_keeps_timeline(self):
        ticket = store.create_ticket(self.db, title="Payment-gate sem reason=", kind="improvement",
                                     priority="medium", origin="audit", status="triage", now=_t())
        self.assertIsNone(ticket["client_id"])
        with self.assertRaisesRegex(store.ManagementError, "resolução"):
            store.set_ticket_status(self.db, ticket["id"], "resolved", now=_t(1))
        store.add_ticket_comment(self.db, ticket["id"], "reproduzido no container", now=_t(2))
        store.set_ticket_status(self.db, ticket["id"], "in_progress", now=_t(3))
        resolved = store.set_ticket_status(self.db, ticket["id"], "resolved", resolution="filtro determinístico", now=_t(4))
        self.assertEqual(resolved["resolved_utc"], store._iso(_t(4)))
        closed = store.set_ticket_status(self.db, ticket["id"], "closed", now=_t(5))
        self.assertEqual(closed["resolved_utc"], store._iso(_t(4)))
        reopened = store.set_ticket_status(self.db, ticket["id"], "open", note="voltou", now=_t(6))
        self.assertIsNone(reopened["resolved_utc"])
        self.assertEqual(reopened["resolution"], "filtro determinístico")

        full = store.get_ticket(self.db, ticket["id"])
        kinds = [(e["kind"], e["to_status"]) for e in full["events"]]
        self.assertEqual(kinds, [("status", "triage"), ("comment", None), ("status", "in_progress"),
                                 ("status", "resolved"), ("status", "closed"), ("status", "open")])

    def test_update_validates_fields_and_client(self):
        ticket = store.create_ticket(self.db, title="x", now=_t())
        with self.assertRaisesRegex(store.ManagementError, "desconhecido"):
            store.update_ticket(self.db, ticket["id"], status="open")
        with self.assertRaisesRegex(store.ManagementError, "Cliente não encontrado"):
            store.update_ticket(self.db, ticket["id"], client_id=42)
        client = self._client()
        updated = store.update_ticket(self.db, ticket["id"], client_id=client["id"], priority="critical", now=_t(1))
        self.assertEqual((updated["client_id"], updated["priority"]), (client["id"], "critical"))
        with self.assertRaisesRegex(store.ManagementError, "Prioridade inválido"):
            store.update_ticket(self.db, ticket["id"], priority="urgente")

    def test_list_orders_by_priority_and_filters(self):
        client = self._client()
        low = store.create_ticket(self.db, title="low", priority="low", now=_t(3))
        crit = store.create_ticket(self.db, title="crit", priority="critical", client_id=client["id"], now=_t(1))
        done = store.create_ticket(self.db, title="done", priority="high", now=_t(2))
        store.set_ticket_status(self.db, done["id"], "closed", resolution="ok", now=_t(4))
        self.assertEqual([t["title"] for t in store.list_tickets(self.db)], ["crit", "done", "low"])
        self.assertEqual([t["title"] for t in store.list_tickets(self.db, open_only=True)], ["crit", "low"])
        self.assertEqual([t["title"] for t in store.list_tickets(self.db, client_id=client["id"])], ["crit"])
        self.assertEqual(store.list_tickets(self.db, status="closed")[0]["id"], done["id"])
        self.assertEqual(store.list_tickets(self.db, client_id=client["id"])[0]["client_name"], "Gustavo Vieira")
        self.assertEqual(low["client_id"], None)


class TouchpointTests(ManagementStoreCase):
    def test_requires_date_and_health_when_done(self):
        client = self._client()
        with self.assertRaisesRegex(store.ManagementError, "data"):
            store.create_touchpoint(self.db, client["id"], kind="checkin")
        with self.assertRaisesRegex(store.ManagementError, "saúde"):
            store.create_touchpoint(self.db, client["id"], kind="checkin", done_on="2026-09-01")
        tp = store.create_touchpoint(self.db, client["id"], kind="kickoff", scheduled_on="2026-09-03",
                                     next_action="enviar acesso", now=_t())
        with self.assertRaisesRegex(store.ManagementError, "saúde"):
            store.update_touchpoint(self.db, tp["id"], done_on="2026-09-03")
        done = store.update_touchpoint(self.db, tp["id"], done_on="2026-09-03", health="attention",
                                       summary="dúvidas no catálogo", now=_t(1))
        self.assertEqual((done["health"], done["next_action"]), ("attention", "enviar acesso"))
        self.assertEqual(store.list_clients(self.db)[0]["health"], "attention")


class ChargeTests(ManagementStoreCase):
    def test_ensure_period_is_idempotent_and_skips_inactive(self):
        active = self._client()
        self._client(name="Setup só", chat_id=None, status="awaiting_payment", monthly_cents=99700,
                     setup_cents=300000, started_on="2026-09-15", activated_on=None)
        self._client(name="Negociando", chat_id=None, status="negotiation", monthly_cents=50000,
                     setup_cents=100000, started_on="2026-09-20", activated_on=None)
        self._client(name="Futuro", chat_id=None, status="active", monthly_cents=50000, activated_on="2026-10-01")
        store.upsert_cost_plan(self.db, client_id=active["id"], category="vps", monthly_cents=4500,
                               label="Contabo", active_from="2026-08", now=_t())
        store.upsert_cost_plan(self.db, category="domain", monthly_cents=800, label="raizandu.com",
                               active_from="2026-01", active_to="2026-08", now=_t())

        first = store.ensure_period(self.db, "2026-09", now=_t())
        self.assertEqual(first, {"monthly": 1, "setup": 1, "costs": 1})
        second = store.ensure_period(self.db, "2026-09", now=_t(1))
        self.assertEqual(second, {"monthly": 0, "setup": 0, "costs": 0})

        charges = store.get_client(self.db, active["id"])["charges"]
        self.assertEqual([(c["kind"], c["due_on"], c["amount_cents"]) for c in charges],
                         [("monthly", "2026-09-05", 149700)])
        setup = store.finance_summary(self.db, "2026-09", today=date(2026, 9, 1))
        setup_rows = [ch for cl in setup["clients"] for ch in cl["charges"] if ch["kind"] == "setup"]
        self.assertEqual([(c["due_on"], c["amount_cents"]) for c in setup_rows], [("2026-09-15", 300000)])
        self.assertEqual(store.ensure_period(self.db, "2026-10", now=_t(2))["monthly"], 2)

        with self.assertRaisesRegex(store.ManagementError, "Competência"):
            store.ensure_period(self.db, "09/2026")

    def test_default_billing_day_when_unset(self):
        self._client(billing_day=None)
        store.ensure_period(self.db, "2026-09", now=_t())
        row = store.finance_summary(self.db, "2026-09", today=date(2026, 9, 1))["clients"][0]["charges"][0]
        self.assertEqual(row["due_on"], "2026-09-10")

    def test_pay_cancel_reopen(self):
        client = self._client()
        store.ensure_period(self.db, "2026-09", now=_t())
        charge = store.get_client(self.db, client["id"])["charges"][0]
        with self.assertRaisesRegex(store.ManagementError, "Data do recebimento"):
            store.pay_charge(self.db, charge["id"], paid_on="")
        paid = store.pay_charge(self.db, charge["id"], paid_on="2026-09-04", now=_t(1))
        self.assertEqual((paid["status"], paid["paid_cents"]), ("paid", 149700))
        with self.assertRaisesRegex(store.ManagementError, "já recebida"):
            store.cancel_charge(self.db, charge["id"])
        reopened = store.reopen_charge(self.db, charge["id"], now=_t(2))
        self.assertEqual((reopened["status"], reopened["paid_on"], reopened["paid_cents"]), ("expected", None, None))
        partial = store.pay_charge(self.db, charge["id"], paid_on="2026-09-06", paid_cents=140000, note="desconto", now=_t(3))
        self.assertEqual((partial["paid_cents"], partial["note"]), (140000, "desconto"))
        store.reopen_charge(self.db, charge["id"], now=_t(4))
        cancelled = store.cancel_charge(self.db, charge["id"], note="cortesia", now=_t(5))
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaisesRegex(store.ManagementError, "cancelada"):
            store.pay_charge(self.db, charge["id"], paid_on="2026-09-07")
        adhoc = store.add_adhoc_charge(self.db, client["id"], period="2026-09", due_on="2026-09-30",
                                       amount_cents=25000, note="horas extras", now=_t(6))
        self.assertEqual(adhoc["kind"], "adhoc")
        with self.assertRaisesRegex(store.ManagementError, "não encontrada"):
            store.pay_charge(self.db, 999, paid_on="2026-09-07")


class CostTests(ManagementStoreCase):
    def test_plan_cost_becomes_manual_when_adjusted(self):
        client = self._client()
        plan = store.upsert_cost_plan(self.db, client_id=client["id"], category="ai", monthly_cents=10000,
                                      label="OpenRouter", active_from="2026-09", now=_t())
        store.ensure_period(self.db, "2026-09", now=_t())
        cost = store.get_client(self.db, client["id"])["costs"][0]
        self.assertEqual((cost["source"], cost["plan_id"], cost["amount_cents"]), ("plan", plan["id"], 10000))
        adjusted = store.upsert_cost(self.db, cost_id=cost["id"], amount_cents=13250, currency_original="usd",
                                     amount_original=24.9, now=_t(1))
        self.assertEqual((adjusted["source"], adjusted["amount_cents"], adjusted["currency_original"], adjusted["label"]),
                         ("manual", 13250, "USD", "OpenRouter"))
        # reprocessar a competência não recria o custo já ajustado
        self.assertEqual(store.ensure_period(self.db, "2026-09", now=_t(2))["costs"], 0)
        self.assertEqual(store.get_client(self.db, client["id"])["costs"][0]["amount_cents"], 13250)

        ended = store.end_cost_plan(self.db, plan["id"], active_to="2026-09", now=_t(3))
        self.assertEqual(ended["active_to"], "2026-09")
        self.assertEqual(store.ensure_period(self.db, "2026-10", now=_t(4))["costs"], 0)
        self.assertEqual(store.list_cost_plans(self.db, period="2026-10"), [])
        self.assertEqual(store.list_cost_plans(self.db, period="2026-09")[0]["client_name"], "Gustavo Vieira")

    def test_manual_cost_and_delete(self):
        with self.assertRaisesRegex(store.ManagementError, "Categoria inválido"):
            store.upsert_cost(self.db, period="2026-09", category="hosting", amount_cents=100)
        shared = store.upsert_cost(self.db, period="2026-09", category="domain", amount_cents=800, label="DNS", now=_t())
        self.assertIsNone(shared["client_id"])
        self.assertTrue(store.delete_cost(self.db, shared["id"]))
        self.assertFalse(store.delete_cost(self.db, shared["id"]))
        with self.assertRaisesRegex(store.ManagementError, "Custo não encontrado"):
            store.upsert_cost(self.db, cost_id=999, amount_cents=1)


class FinanceSummaryTests(ManagementStoreCase):
    def test_summary_numbers(self):
        a = self._client()  # 1497, vence dia 5
        b = self._client(name="Bia", chat_id=None, monthly_cents=99700, billing_day=20)
        self._client(name="Pausado", chat_id=None, status="paused", monthly_cents=50000)
        store.upsert_cost_plan(self.db, client_id=a["id"], category="vps", monthly_cents=4500, active_from="2026-09", now=_t())
        store.upsert_cost_plan(self.db, category="domain", monthly_cents=800, active_from="2026-09", now=_t())
        store.ensure_period(self.db, "2026-08", now=_t())
        store.ensure_period(self.db, "2026-09", now=_t())
        store.upsert_cost(self.db, client_id=b["id"], period="2026-09", category="ai", amount_cents=3200, now=_t())

        a_charges = {c["period"]: c for c in store.get_client(self.db, a["id"])["charges"]}
        # agosto pago em setembro conta no recebido de setembro
        store.pay_charge(self.db, a_charges["2026-08"]["id"], paid_on="2026-09-02", now=_t(1))
        store.pay_charge(self.db, a_charges["2026-09"]["id"], paid_on="2026-09-05", now=_t(2))

        s = store.finance_summary(self.db, "2026-09", today=date(2026, 9, 25))
        self.assertEqual(s["mrr_cents"], 149700 + 99700)
        self.assertEqual(s["active_clients"], 2)
        self.assertEqual(s["received_cents"], 149700 * 2)
        self.assertEqual(s["expected_cents"], 99700)
        self.assertEqual((s["overdue_cents"], s["overdue_count"]), (99700, 1))
        self.assertEqual(s["overdue_all_cents"], 99700 * 2)  # agosto da Bia também está aberto
        self.assertEqual(s["costs_by_category"], {"vps": 4500, "ai": 3200, "domain": 800, "tools": 0, "other": 0})
        self.assertEqual((s["shared_costs_cents"], s["costs_cents"]), (800, 8500))
        self.assertEqual(s["margin_cents"], 149700 * 2 - 8500)

        by_name = {c["name"]: c for c in s["clients"]}
        self.assertEqual(set(by_name), {"Gustavo Vieira", "Bia", "Pausado"})
        self.assertEqual((by_name["Gustavo Vieira"]["received_cents"], by_name["Gustavo Vieira"]["costs_cents"],
                          by_name["Gustavo Vieira"]["margin_cents"], by_name["Gustavo Vieira"]["overdue"]),
                         (149700 * 2, 4500, 149700 * 2 - 4500, False))
        self.assertEqual((by_name["Bia"]["margin_cents"], by_name["Bia"]["overdue"]), (-3200, True))
        self.assertEqual(by_name["Pausado"]["charges"], [])

    def test_summary_before_due_has_no_overdue(self):
        self._client()
        store.ensure_period(self.db, "2026-09", now=_t())
        s = store.finance_summary(self.db, "2026-09", today=date(2026, 9, 1))
        self.assertEqual((s["overdue_count"], s["expected_cents"], s["received_cents"]), (0, 149700, 0))


if __name__ == "__main__":
    unittest.main()
