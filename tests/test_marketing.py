"""Aba Marketing: funil da LP cruzado com a chegada no WhatsApp."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))
import history_store  # noqa: E402
import lp_pages  # noqa: E402
import marketing  # noqa: E402
import marketing_store  # noqa: E402
from panel import data as panel_data  # noqa: E402
from panel import server as panel_server  # noqa: E402
from tests.test_panel_actions import LiveServerFixture  # noqa: E402
from tests.test_panel_data import LEAD2, NOW, PanelFixture  # noqa: E402

LEAD3 = "5521999990000@s.whatsapp.net"
LP_MESSAGE = (
    "Oi, sou Carla e vim pelo site da AYA.\n\nMeu negócio: Clínica\n\n"
    "Origem: utm_source: instagram | utm_medium: bio | id: ab3k9x"
)


def seed_marketing(fixture: PanelFixture) -> None:
    """Carla veio da LP (sessão ab3k9x); Rafael veio de anúncio nativo; Mariana
    não tem origem nenhuma. Uma segunda sessão da LP só viu a página."""
    contacts = json.loads(fixture.paths.contacts_json.read_text())
    contacts[LEAD2]["origin"] = "FB_Ads"
    contacts[LEAD3] = {"name": "Carla Dias", "blocked": False, "ai_enabled": True}
    fixture.paths.contacts_json.write_text(json.dumps(contacts))

    conn = history_store.connect(str(fixture.paths.messages_db))
    conn.execute(
        "INSERT INTO messages (chat_id, sender_id, sender_name, message_id, message_type, body, timestamp, from_me)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (LEAD3, LEAD3, "Carla", "m9", "text", LP_MESSAGE, (NOW - timedelta(minutes=30)).timestamp(), 0),
    )
    conn.commit()
    conn.close()

    at = NOW - timedelta(minutes=40)
    session = {"lp": "quiz-v4", "session_id": "ab3k9x", "utm_source": "instagram", "utm_medium": "bio"}
    for event, step in (("view", None), ("start", None), ("step", 3), ("complete", None), ("whatsapp_click", None)):
        marketing_store.record_event(fixture.paths.panel_db, {**session, "event": event, "step": step}, now=at)
    marketing_store.record_event(
        fixture.paths.panel_db, {"lp": "quiz-v4", "session_id": "zz9999", "event": "view"}, now=at,
    )


class MarketingReportTest(PanelFixture):
    def setUp(self):
        super().setUp()
        seed_marketing(self)

    def test_session_id_in_message(self):
        self.assertEqual(marketing.session_id_from_message(LP_MESSAGE), "ab3k9x")
        self.assertEqual(marketing.session_id_from_message("Oi, quero saber o preço"), "")

    def test_report_crosses_lp_sessions_with_whatsapp_arrivals(self):
        report = marketing.report(
            self.paths, "7d", contacts=panel_data.load_contacts(self.paths.contacts_json), now=NOW,
        )
        self.assertEqual(report["totals"], {
            "sessions": 2, "clicks": 1, "arrived": 2, "arrived_lp": 1, "arrived_native": 1,
            "in_funnel": 1, "won": 0,
        }, "Carla ainda não entrou no motor de follow-up; só Rafael conta no funil")
        self.assertEqual(report["lps"], [{
            "lp": "quiz-v4", "view": 2, "start": 1, "complete": 1, "whatsapp_click": 1, "arrived": 1,
        }])
        by_source = {o["source"]: o for o in report["origins"]}
        self.assertEqual(by_source["instagram"], {
            "source": "instagram", "medium": "bio", "campaign": "",
            "sessions": 1, "clicks": 1, "arrived": 1, "in_funnel": 0, "won": 0,
        })
        self.assertEqual(by_source["FB_Ads"]["medium"], "nativa")
        self.assertEqual((by_source["FB_Ads"]["sessions"], by_source["FB_Ads"]["arrived"]), (0, 1))
        self.assertEqual(by_source["lp"]["sessions"], 1)
        arrivals = {a["chat_id"]: a for a in report["arrivals"]}
        self.assertEqual(set(arrivals), {LEAD2, LEAD3}, "Mariana não tem origem e fica de fora")
        self.assertEqual(arrivals[LEAD3]["session_id"], "ab3k9x")
        self.assertEqual(arrivals[LEAD3]["name"], "Carla Dias")
        self.assertEqual(arrivals[LEAD2]["stage"], "new")
        self.assertEqual(sum(d["arrived"] for d in report["days"]), 2)
        self.assertEqual(report["period"], "7d")

    def test_source_filter_keeps_only_the_channel(self):
        contacts = panel_data.load_contacts(self.paths.contacts_json)
        lp = marketing.report(self.paths, "7d", contacts=contacts, now=NOW, source="lp")
        self.assertEqual((lp["totals"]["sessions"], lp["totals"]["arrived"], lp["totals"]["arrived_native"]), (2, 1, 0))
        meta = marketing.report(self.paths, "7d", contacts=contacts, now=NOW, source="meta")
        self.assertEqual(meta["totals"]["sessions"], 1, "só a sessão vinda do Instagram é Meta")
        self.assertEqual({a["chat_id"] for a in meta["arrivals"]}, {LEAD2, LEAD3}, "FB_Ads nativo e LP do Instagram são Meta")
        wpp = marketing.report(self.paths, "7d", contacts=contacts, now=NOW, source="whatsapp")
        self.assertEqual((wpp["totals"]["sessions"], wpp["totals"]["arrived_native"], wpp["totals"]["arrived_lp"]), (0, 1, 0))
        self.assertEqual(marketing.report(self.paths, "7d", contacts=contacts, now=NOW, source="x")["source"], "all")

    def test_period_cuts_old_arrivals(self):
        report = marketing.report(
            self.paths, "hoje", contacts=panel_data.load_contacts(self.paths.contacts_json),
            now=NOW + timedelta(days=3),
        )
        self.assertEqual(report["totals"]["arrived"], 0)
        self.assertEqual(report["totals"]["sessions"], 0)


class PageInsightTest(unittest.TestCase):
    def _stats(self, **kw):
        report = {"lps": [{"lp": "psicologos", "view": 100, "start": 80, "complete": 60, "whatsapp_click": 40, "arrived": 30, **kw}]}
        return marketing.page_stats(report, {"slug": "psicologos"})

    def test_rates_and_root_maps_to_home(self):
        stats = self._stats()
        self.assertEqual((stats["start_rate"], stats["complete_rate"], stats["click_rate"], stats["arrive_rate"]), (80, 75, 40, 75))
        root = marketing.page_stats({"lps": [{"lp": "home", "view": 5}]}, {"slug": ""})
        self.assertEqual((root["view"], root["start_rate"]), (5, 0))

    def test_insight_names_the_biggest_drop(self):
        page = {"slug": "psicologos", "proofs": []}
        self.assertEqual(marketing.page_insight(self._stats(view=0, start=0, complete=0, whatsapp_click=0, arrived=0), page)["tone"], "off")
        self.assertIn("começam o quiz", marketing.page_insight(self._stats(start=20), page)["text"])
        self.assertIn("terminam o quiz", marketing.page_insight(self._stats(complete=30), page)["text"])
        self.assertIn("clicam no WhatsApp", marketing.page_insight(self._stats(whatsapp_click=10, arrived=9), page)["text"])
        self.assertIn("não enviam", marketing.page_insight(self._stats(arrived=10), page)["text"])
        healthy = marketing.page_insight(self._stats(), page)
        self.assertEqual(healthy["tone"], "ok")
        self.assertIn("Falta prova social", healthy["text"])
        self.assertNotIn("Falta prova social", marketing.page_insight(self._stats(), {**page, "proofs": [{"quote": "x"}]})["text"])


class MarketingRouteTest(LiveServerFixture):
    def setUp(self):
        super().setUp()
        seed_marketing(self)
        self.config_path = Path(self.tmp.name) / "panel.config.json"

    def test_route_is_404_without_flag_and_reports_with_it(self):
        self.config_path.write_text(json.dumps({"features": {}}))
        with patch.object(panel_server, "CONFIG_PATH", self.config_path):
            status, _ = self._get("/api/marketing?period=7d")
        self.assertEqual(status, 404)
        self.config_path.write_text(json.dumps({"features": {"marketing": True}}))
        with patch.object(panel_server, "CONFIG_PATH", self.config_path):
            status, body = self._get("/api/marketing?period=30d&source=whatsapp")
        self.assertEqual(status, 200)
        self.assertEqual((body["period"], body["source"]), ("30d", "whatsapp"))
        self.assertEqual(body["lps"], [], "filtro WhatsApp não tem sessão de LP")
        self.assertEqual(body["totals"]["arrived_native"], 1)

    def test_pages_are_admin_only_and_saving_publishes_the_site(self):
        base = Path(self.tmp.name)
        template = base / "quiz.template.html"
        template.write_text("<title>{{title}}</title><h1>{{h1}}</h1><h2>{{question}}</h2>{{!options}}{{js:lp_id}}", encoding="utf-8")
        self.config_path.write_text(json.dumps({
            "features": {"marketing": True},
            "marketing": {"base_url": "https://agenteaya.com", "www_dir": str(base / "www"), "template": str(template)},
        }))
        page = {"slug": "psicologos", "niche": "Psicologia", "title": "AYA para psicólogos", "description": "d",
                "h1": "H", "question": "Qual sua atuação?", "options": "Clínico\nOrganizacional"}
        with patch.object(panel_server, "CONFIG_PATH", self.config_path):
            status, body = self._post("/api/actions/marketing/page-save", page)
            self.assertEqual(status, 200, body)
            self.assertFalse(body["published"], "sem a raiz cadastrada a publicação avisa em vez de gerar")
            self.assertIn("raiz", body["warning"])
            status, body = self._post("/api/actions/marketing/page-save", lp_pages.ROOT_PAGE)
            self.assertEqual(status, 200, body)
            self.assertTrue(body["published"], body)
            status, listing = self._get("/api/marketing/pages")
        self.assertEqual(status, 200)
        self.assertEqual([p["slug"] for p in listing["pages"]], ["", "psicologos"])
        self.assertTrue(listing["template_ready"])
        self.assertEqual(listing["pages"][1]["stats"]["view"], 0)
        self.assertEqual(listing["pages"][1]["insight"]["tone"], "off")
        self.assertEqual(listing["period"], "30d")
        self.assertIn("Qual sua atuação?", (base / "www" / "psicologos" / "index.html").read_text())
        self.assertIn("<loc>https://agenteaya.com/psicologos/</loc>", (base / "www" / "sitemap.xml").read_text())
        self.assertNotIn("marketing/page-save", panel_server.ATTENDANT_ACTIONS)
        self.assertNotIn("marketing/page-delete", panel_server.ATTENDANT_ACTIONS)
        with patch.object(panel_server, "CONFIG_PATH", self.config_path):
            status, body = self._post("/api/actions/marketing/page-save", {**page, "slug": "api"})
            self.assertEqual(status, 400, body)
            status, body = self._post("/api/actions/marketing/page-delete", {"slug": "psicologos"})
            self.assertEqual(status, 200, body)
        self.assertFalse((base / "www" / "psicologos").exists())
        self.config_path.write_text(json.dumps({"features": {}}))
        with patch.object(panel_server, "CONFIG_PATH", self.config_path):
            status, _ = self._get("/api/marketing/pages")
        self.assertEqual(status, 404)
