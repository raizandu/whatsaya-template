"""O fuso nas respostas determinísticas de agenda vem do perfil de negócio."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

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

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
ONE_SLOT = {"slots": [{"start": "2999-01-07T08:00:00-03:00", "end": "2999-01-07T09:00:00-03:00"}]}


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class CalendarReplyLabelTest(unittest.TestCase):
    def setUp(self):
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def test_generic_profile_keeps_goiania(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            reply = wm._calendar_visible_reply(ONE_SLOT, "sim")
        self.assertIn("horário de Goiânia", reply)

    def test_therapify_profile_says_brasilia(self):
        with mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }):
            reply = wm._calendar_visible_reply(ONE_SLOT, "sim")
            booked = wm._calendar_visible_reply(
                {"reply_kind": "booked", "result": {"start": "2999-01-07T08:00:00-03:00", "meet_link": "https://meet.google.com/abc-defg-hij"}},
                "sim",
            )
        self.assertIn("horário de Brasília", reply)
        self.assertNotIn("Goiânia", reply)
        self.assertNotIn("Goiânia", booked)


if __name__ == "__main__":
    unittest.main()
