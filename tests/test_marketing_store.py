"""Eventos da landing page: validação do beacon e rota pública do painel."""
from __future__ import annotations

import json
import sys
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
