"""Eventos da landing page: validação do beacon e rota pública do painel."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))
import marketing_store  # noqa: E402
from tests.test_panel_actions import LiveServerFixture  # noqa: E402

VALID = {"lp": "quiz-v4", "event": "step", "session_id": "ab3k9x", "step": 2,
         "utm_source": "instagram", "utm_medium": "bio"}


class MarketingStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "panel.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_only_funnel_fields(self):
        marketing_store.record_event(self.db, {**VALID, "nome": "Fulano", "telefone": "5511999"})
        rows = marketing_store.events_for_session(self.db, "ab3k9x")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "step")
        self.assertEqual(rows[0]["step"], 2)
        self.assertEqual(rows[0]["utm_source"], "instagram")
        self.assertIsNone(rows[0]["utm_campaign"])
        self.assertNotIn("nome", rows[0])
        self.assertEqual(oct(self.db.stat().st_mode & 0o777), "0o600")

    def test_rejects_garbage(self):
        for bad in (
            {**VALID, "event": "signup"},
            {**VALID, "lp": "../x"},
            {**VALID, "session_id": "abc"},
            {**VALID, "step": "2"},
            {**VALID, "step": 99},
            "not a dict",
        ):
            with self.assertRaises(ValueError, msg=bad):
                marketing_store.record_event(self.db, bad)
        self.assertEqual(marketing_store.events_for_session(self.db, "ab3k9x"), [])

    def test_answers_become_a_lead_only_on_complete_or_click(self):
        answers = {"nome": "Marcos Lima", "telefone": "(62) 99999-0000", "niche": "Revenda de carros",
                   "negocio": "Motos", "atendimento": "Sim, bastante", "volume": "50 a 100", "equipe": "Equipe", "problema": "Conversas se perdem"}
        marketing_store.record_event(self.db, {**VALID, "event": "step", "answers": answers})
        self.assertIsNone(marketing_store.get_lead(self.db, "ab3k9x"), "step não cria lead")
        marketing_store.record_event(self.db, {**VALID, "event": "complete", "step": None, "answers": answers},
                                     now=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc))
        lead = marketing_store.get_lead(self.db, "ab3k9x")
        self.assertEqual((lead["name"], lead["phone"], lead["answers"]["negocio"]), ("Marcos Lima", "62999990000", "Motos"))
        self.assertEqual(lead["completed_at"], "2026-09-16T12:00:00Z")
        self.assertIsNone(lead["clicked_at"])
        marketing_store.record_event(self.db, {**VALID, "event": "whatsapp_click", "step": None, "answers": {**answers, "telefone": "+55 62 99999-0000"}},
                                     now=datetime(2026, 9, 16, 12, 5, tzinfo=timezone.utc))
        lead = marketing_store.get_lead(self.db, "ab3k9x")
        self.assertEqual((lead["completed_at"], lead["clicked_at"]), ("2026-09-16T12:00:00Z", "2026-09-16T12:05:00Z"))
        self.assertEqual(lead["phone"], "62999990000", "55 na frente é removido")
        self.assertEqual([l["session_id"] for l in marketing_store.list_leads(self.db)], ["ab3k9x"])
        marketing_store.mark_contacted(self.db, "ab3k9x", status="sent", message_id="m-1")
        self.assertEqual(marketing_store.get_lead(self.db, "ab3k9x")["contact_status"], "sent")

    def test_bad_answers_are_ignored_not_rejected(self):
        for bad in ({"nome": "M", "telefone": "62999990000"}, {"nome": "Marcos", "telefone": "999"}, "x"):
            row = marketing_store.record_event(self.db, {**VALID, "event": "complete", "step": None, "answers": bad})
            self.assertIsNone(row["lead"], bad)
        self.assertEqual(marketing_store.list_leads(self.db), [])
        self.assertEqual(len(marketing_store.events_for_session(self.db, "ab3k9x")), 3, "o evento do funil entra mesmo assim")

    def test_caps_events_per_session(self):
        for _ in range(marketing_store.MAX_EVENTS_PER_SESSION):
            marketing_store.record_event(self.db, VALID)
        with self.assertRaises(ValueError):
            marketing_store.record_event(self.db, VALID)


class LpEventRouteTest(LiveServerFixture):
    def _beacon(self, body, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/lp/event", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_public_route_records_without_session(self):
        status, body = self._beacon(VALID)
        self.assertEqual((status, body), (204, b""))
        rows = marketing_store.events_for_session(self.paths.panel_db, "ab3k9x")
        self.assertEqual([r["event"] for r in rows], ["step"])

    def test_public_route_rejects_bad_payload_and_big_body(self):
        status, _ = self._beacon({**VALID, "event": "signup"})
        self.assertEqual(status, 400)
        status, _ = self._beacon(None, raw=b"{" + b" " * 3000 + b"}")
        self.assertEqual(status, 400)
        self.assertEqual(marketing_store.events_for_session(self.paths.panel_db, "ab3k9x"), [])


if __name__ == "__main__":
    unittest.main()
