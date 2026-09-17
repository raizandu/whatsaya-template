"""Contato ativo da LP: quem está na hora, o que a AYA escreve, e o envio fail-closed."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))
import contacts_store  # noqa: E402
import marketing_outreach  # noqa: E402
import marketing_service  # noqa: E402
import marketing_store  # noqa: E402
import panel_store  # noqa: E402
from panel import actions as panel_actions  # noqa: E402
from panel import server as panel_server  # noqa: E402
from tests.test_panel_actions import FakeBridge, LiveServerFixture  # noqa: E402
from tests.test_panel_data import NOW, PanelFixture  # noqa: E402

ANSWERS = {"nome": "Marcos Lima", "telefone": "62999990000", "niche": "Revenda de carros", "negocio": "Motos",
           "atendimento": "Sim, bastante", "volume": "50 a 100", "equipe": "Equipe", "problema": "Conversas acabam se perdendo"}


def seed_lead(db, session_id="hr5ump", *, at=NOW - timedelta(minutes=45), event="complete", answers=ANSWERS):
    marketing_store.record_event(db, {"lp": "carros", "event": event, "session_id": session_id,
                                      "utm_source": "instagram", "answers": answers}, now=at)
    return marketing_store.get_lead(db, session_id)


class OutreachRulesTest(PanelFixture):
    def test_due_waits_delay_skips_arrived_and_contacted(self):
        fresh = seed_lead(self.paths.panel_db, "fresh1", at=NOW - timedelta(minutes=5))
        old = seed_lead(self.paths.panel_db, "old001")
        arrived = seed_lead(self.paths.panel_db, "arriv1")
        done = seed_lead(self.paths.panel_db, "done01")
        marketing_store.mark_contacted(self.paths.panel_db, "done01", status="sent")
        leads = marketing_store.list_leads(self.paths.panel_db)
        due = marketing_outreach.due(leads, {"arriv1"}, now=NOW, delay_min=30)
        self.assertEqual([lead["session_id"] for lead in due], ["old001"])
        self.assertEqual(marketing_outreach.status_of(fresh, set(), now=NOW), "aguardando")
        self.assertEqual(marketing_outreach.status_of(old, set(), now=NOW), "na_fila")
        self.assertEqual(marketing_outreach.status_of(arrived, {"arriv1"}, now=NOW), "chegou")
        self.assertEqual(marketing_outreach.status_of(marketing_store.get_lead(self.paths.panel_db, "done01"), set(), now=NOW), "aya_chamou")

    def test_first_message_uses_name_niche_and_pain_without_promises(self):
        lead = seed_lead(self.paths.panel_db)
        text = marketing_outreach.first_message(lead, assistant_name="AYA", site="agenteaya.com")
        self.assertTrue(text.startswith("Oi, Marcos! Aqui é a AYA, do site agenteaya.com."))
        self.assertIn("Revenda de carros · Motos", text)
        self.assertIn('"conversas acabam se perdendo"', text)
        self.assertIn("número que você deixou", text)
        for banned in ("garant", "grátis", "promoção"):
            self.assertNotIn(banned, text.lower())
        self.assertEqual(marketing_outreach.chat_id_for("(62) 99999-0000"), "5562999990000@s.whatsapp.net")


class OutreachActionTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def test_sends_records_history_creates_contact_and_marks_once(self):
        lead = seed_lead(self.paths.panel_db)
        result = panel_actions.lp_outreach(self.paths, self.bridge, lead, assistant_name="AYA", owner_number="5547999414100")
        self.assertEqual(result["status"], "sent")
        path, body = self.bridge.calls[-1]
        self.assertEqual((path, body["chatId"], body["automation"]), ("/send", "5562999990000@s.whatsapp.net", True))
        conn = sqlite3.connect(self.paths.messages_db)
        row = conn.execute("SELECT sender_name, from_me, body FROM messages WHERE chat_id = ?", ("5562999990000@s.whatsapp.net",)).fetchone()
        conn.close()
        self.assertEqual((row[0], row[1]), ("AYA", 1))
        self.assertIn("Marcos", row[2])
        outbound = panel_store.outbound_for_chats(self.paths.panel_db, ["5562999990000@s.whatsapp.net"])
        self.assertEqual(list(outbound.values())[0]["sent_by_user"], "aya-outreach")
        contact = contacts_store.read_contacts(self.paths.contacts_json)["5562999990000@s.whatsapp.net"]
        self.assertEqual((contact["name"], contact["origin"], contact["ai_enabled"], contact["lp_session_id"]), ("Marcos Lima", "landing_page", True, "hr5ump"))
        self.assertEqual(marketing_store.get_lead(self.paths.panel_db, "hr5ump")["contact_status"], "sent")
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.lp_outreach(self.paths, self.bridge, marketing_store.get_lead(self.paths.panel_db, "hr5ump"))
        self.assertEqual(len([c for c in self.bridge.calls if c[0] == "/send"]), 1, "uma tentativa por sessão")

    def test_bridge_refusal_marks_blocked_and_failure_marks_failed(self):
        lead = seed_lead(self.paths.panel_db, "blk001")
        self.bridge.send_response = {"error": "automation_blocked", "reason": "bot_paused"}
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.lp_outreach(self.paths, self.bridge, lead)
        self.assertEqual(marketing_store.get_lead(self.paths.panel_db, "blk001")["contact_status"], "blocked")
        lead2 = seed_lead(self.paths.panel_db, "fail01")
        self.bridge.send_response = {"success": False}
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.lp_outreach(self.paths, self.bridge, lead2)
        self.assertEqual(marketing_store.get_lead(self.paths.panel_db, "fail01")["contact_status"], "failed")
        self.assertNotIn("5562999990000@s.whatsapp.net", contacts_store.read_contacts(self.paths.contacts_json), "sem envio, sem contato")

    def test_service_tick_contacts_only_due_and_respects_enabled(self):
        seed_lead(self.paths.panel_db, "old001")
        seed_lead(self.paths.panel_db, "fresh1", at=NOW - timedelta(minutes=2))
        service = marketing_service.OutreachService(self.paths, self.bridge, delay_min=30, enabled=False)
        self.assertEqual(service.tick(now=NOW), [])
        service.enabled = True
        results = service.tick(now=NOW)
        self.assertEqual([r["session_id"] for r in results], ["old001"])
        self.assertEqual(service.tick(now=NOW), [], "segunda passada não repete")


class LeadsRouteTest(LiveServerFixture):
    def test_leads_route_and_manual_contact(self):
        seed_lead(self.paths.panel_db, "old001", at=datetime.now(timezone.utc) - timedelta(minutes=45))
        config_path = Path(self.tmp.name) / "panel.config.json"
        config_path.write_text(json.dumps({"features": {"marketing": True}, "marketing": {"base_url": "https://agenteaya.com"}}))
        with patch.object(panel_server, "CONFIG_PATH", config_path):
            status, body = self._get("/api/marketing/leads?period=7d")
            self.assertEqual(status, 200)
            self.assertEqual(body["outreach_enabled"], False, "desligado por padrão")
            self.assertEqual(body["leads"][0]["status"], "na_fila")
            self.assertEqual(body["leads"][0]["chat_id"], "5562999990000@s.whatsapp.net")
            status, result = self._post("/api/actions/marketing/lead-contact", {"session_id": "old001"})
            self.assertEqual(status, 200, result)
            self.assertEqual(result["status"], "sent")
            status, body = self._get("/api/marketing/leads?period=7d")
            self.assertEqual(body["leads"][0]["status"], "aya_chamou")
        self.assertNotIn("marketing/lead-contact", panel_server.ATTENDANT_ACTIONS)
