"""Testes da retomada suave de fim de semana/feriado (step_no=0 da Fase 7)."""
from __future__ import annotations

import contextlib
import datetime
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("WHATSAPP_HUMAN_TEST_MODE", "1")

MODULE_PATH = REPO_ROOT / "whatsapp_manager.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_manager", MODULE_PATH)
assert SPEC and SPEC.loader
wm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wm
SPEC.loader.exec_module(wm)

from commercial_followups import BusinessHours, next_business_day_open  # noqa: E402

PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
HOURS = BusinessHours.from_profile(PROFILE)
BRT = ZoneInfo("America/Sao_Paulo")
CHAT = "554797232779@s.whatsapp.net"


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class WeekendOpeningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

        wm._business_profile_cache["checked_at"] = 0.0
        wm._business_profile_cache["mtime"] = None
        wm._business_profile_cache["data"] = {}

        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(PROFILE_PATH),
            "WHATSAPP_FOLLOWUP_ENABLED": "true",
        }))
        self.enterContext(mock.patch.object(wm, "_FOLLOWUP_DB_PATH", self.tmp / "followups.db"))
        wm._FOLLOWUP_ENGINE = None
        self.addCleanup(setattr, wm, "_FOLLOWUP_ENGINE", None)

        self.record: dict = {"name": "Maria Silva"}
        self.enterContext(mock.patch.object(
            wm, "_contact_record_for_chat", side_effect=lambda cid, contacts=None: dict(self.record)
        ))
        self.enterContext(mock.patch.object(wm, "_session_is_owner", return_value=False))
        self.enterContext(mock.patch.object(
            wm, "_contact_effect_identity_lock", side_effect=lambda *a, **k: contextlib.nullcontext()
        ))
        self.enterContext(mock.patch.object(wm, "_assert_delivery_allowed"))
        self.enterContext(mock.patch.object(wm.time, "sleep"))

        self.posts: list[dict] = []
        self.enterContext(mock.patch.object(wm.urllib.request, "urlopen", side_effect=self._urlopen))

    def _urlopen(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8")) if req.data else {}
        self.posts.append({"url": req.full_url, "body": body})
        return _FakeResp(json.dumps({"messageId": f"wamid.{len(self.posts)}"}).encode())

    def sent(self) -> list[str]:
        return [p["body"]["message"] for p in self.posts if p["url"].endswith("/send")]

    def test_next_business_day_open_cases(self):
        fri = datetime.datetime(2026, 11, 27, 14, 30, tzinfo=BRT)
        self.assertEqual(
            next_business_day_open(fri, HOURS).astimezone(BRT),
            datetime.datetime(2026, 11, 30, 9, 0, tzinfo=BRT),
        )
        hol = datetime.datetime(2026, 11, 20, 16, 20, tzinfo=BRT)
        self.assertEqual(
            next_business_day_open(hol, HOURS).astimezone(BRT),
            datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT),
        )
        sat = datetime.datetime(2026, 11, 21, 16, 30, tzinfo=BRT)
        self.assertEqual(
            next_business_day_open(sat, HOURS).astimezone(BRT),
            datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT),
        )
        mon_early = datetime.datetime(2026, 11, 23, 8, 30, tzinfo=BRT)
        self.assertEqual(
            next_business_day_open(mon_early, HOURS).astimezone(BRT),
            datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT),
        )

    def test_weekend_opening_qualification(self):
        sat = datetime.datetime(2026, 11, 21, 16, 30, tzinfo=BRT).astimezone(datetime.UTC)
        fri_am = datetime.datetime(2026, 11, 27, 10, 0, tzinfo=BRT).astimezone(datetime.UTC)
        fri_pm = datetime.datetime(2026, 11, 27, 14, 0, tzinfo=BRT).astimezone(datetime.UTC)
        tue = datetime.datetime(2026, 11, 24, 15, 0, tzinfo=BRT).astimezone(datetime.UTC)

        self.assertIsNone(wm._weekend_opening_due(sat, opening_delivery=False))
        self.assertIsNone(wm._weekend_opening_due(tue, opening_delivery=True))
        self.assertIsNone(wm._weekend_opening_due(fri_am, opening_delivery=True))
        self.assertEqual(
            wm._weekend_opening_due(fri_pm, opening_delivery=True).astimezone(BRT),
            datetime.datetime(2026, 11, 30, 9, 0, tzinfo=BRT),
        )
        self.assertEqual(
            wm._weekend_opening_due(sat, opening_delivery=True).astimezone(BRT),
            datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT),
        )

    def test_full_4_step_cadence_and_delivery(self):
        sat = datetime.datetime(2026, 11, 21, 16, 30, tzinfo=BRT).astimezone(datetime.UTC)
        mon9 = datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT).astimezone(datetime.UTC)
        tue9 = datetime.datetime(2026, 11, 24, 9, 0, tzinfo=BRT).astimezone(datetime.UTC)
        wed9 = datetime.datetime(2026, 11, 25, 9, 0, tzinfo=BRT).astimezone(datetime.UTC)
        thu9 = datetime.datetime(2026, 11, 26, 9, 0, tzinfo=BRT).astimezone(datetime.UTC)

        engine = wm._followup_engine()
        engine.configure_lead(CHAT, automation_enabled=True, stage="qualification", cadence_kind="reactivation", now=sat)
        ids = engine.note_outbound(CHAT, message_id="out-f1", at=sat, opening_step_due=mon9)
        self.assertEqual(len(ids), 4)

        jobs = {j["step_no"]: j for j in engine.get_jobs(CHAT) if j["cadence_kind"] == "reactivation"}
        self.assertEqual(sorted(jobs.keys()), [0, 1, 2, 3])
        self.assertEqual(datetime.datetime.fromisoformat(jobs[0]["due_utc"]), mon9)
        self.assertEqual(datetime.datetime.fromisoformat(jobs[1]["due_utc"]), tue9)
        self.assertEqual(datetime.datetime.fromisoformat(jobs[2]["due_utc"]), wed9)
        self.assertEqual(datetime.datetime.fromisoformat(jobs[3]["due_utc"]), thu9)

        claimed = engine.claim_due(now=mon9, worker_id="t1")
        self.assertEqual([c["step_no"] for c in claimed], [0])
        with mock.patch.object(wm, "_hum_now", return_value=mon9):
            ok = wm._send_reactivation_step(engine, claimed[0])
        self.assertTrue(ok)
        self.assertEqual(self.sent(), [
            "Olá 👋",
            "Bom dia Maria, tudo bem?",
            "Vamos lhe passar maiores informações ℹ️",
            "Atualmente o relacionamento encerrou, ou segue em uma relação?",
        ])
        self.assertFalse(bool(engine.get_lead(CHAT)["terminal"]))

        self.posts.clear()
        claimed1 = engine.claim_due(now=tue9, worker_id="t1")
        self.assertEqual([c["step_no"] for c in claimed1], [1])
        with mock.patch.object(wm, "_hum_now", return_value=tue9):
            ok1 = wm._send_reactivation_step(engine, claimed1[0])
        self.assertTrue(ok1)
        self.assertEqual(self.sent(), ["Olá 👋", "Desistiu do tratamento?"])

    def test_lead_reply_after_step0_cancels_desistiu(self):
        sat = datetime.datetime(2026, 11, 21, 16, 30, tzinfo=BRT).astimezone(datetime.UTC)
        mon9 = datetime.datetime(2026, 11, 23, 9, 0, tzinfo=BRT).astimezone(datetime.UTC)
        mon10 = datetime.datetime(2026, 11, 23, 10, 0, tzinfo=BRT).astimezone(datetime.UTC)

        engine = wm._followup_engine()
        engine.configure_lead(CHAT, automation_enabled=True, stage="qualification", cadence_kind="reactivation", now=sat)
        engine.note_outbound(CHAT, message_id="out-f1", at=sat, opening_step_due=mon9)
        claimed = engine.claim_due(now=mon9, worker_id="t1")
        with mock.patch.object(wm, "_hum_now", return_value=mon9):
            wm._send_reactivation_step(engine, claimed[0])

        cancelled = engine.note_inbound(CHAT, message_id="in-reply", at=mon10)
        self.assertEqual(cancelled, 3)
        jobs = {j["step_no"]: j["status"] for j in engine.get_jobs(CHAT)}
        self.assertEqual(jobs, {0: "sent", 1: "cancelled", 2: "cancelled", 3: "cancelled"})

    def test_afternoon_without_name_salutation(self):
        self.record = {}
        mon14 = datetime.datetime(2026, 11, 23, 14, 0, tzinfo=BRT).astimezone(datetime.UTC)
        engine = wm._followup_engine()
        engine.configure_lead(CHAT, automation_enabled=True, stage="qualification", cadence_kind="reactivation", now=mon14)
        engine.note_outbound(CHAT, message_id="out-f1", at=mon14, opening_step_due=mon14)
        claimed = engine.claim_due(now=mon14, worker_id="t1")
        with mock.patch.object(wm, "_hum_now", return_value=mon14):
            wm._send_reactivation_step(engine, claimed[0])
        self.assertEqual(self.sent()[1], "Boa tarde, tudo bem?")


if __name__ == "__main__":
    unittest.main()
