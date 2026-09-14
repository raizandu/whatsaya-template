"""Regressões da fronteira de admissão e do takeover manual da Therapify."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime
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

from commercial_followups import FollowupEngine  # noqa: E402


THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
CHAT = "556281405459@s.whatsapp.net"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class TherapifyScopeAdmissionTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.contacts_path = tmp / "personal_contacts.json"
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", self.contacts_path))
        self.enterContext(mock.patch.object(wm, "_is_contact_blocked", return_value=False))
        self.enterContext(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
        self.enterContext(mock.patch.object(wm, "_recent_inbound_has_commercial_scope", return_value=False))
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def _record(self) -> dict:
        return json.loads(self.contacts_path.read_text(encoding="utf-8"))[CHAT]

    def test_unknown_without_metadata_does_not_enter_fase1(self):
        allowed, reason = wm._ensure_contact_ai_access(
            CHAT,
            CHAT,
            message_text="Oi, tudo bem?",
            commercial_metadata={},
        )
        self.assertEqual((allowed, reason), (False, "commercial-scope-unconfirmed"))
        record = self._record()
        self.assertFalse(record["ai_enabled"])
        self.assertFalse(record["in_flow"])
        self.assertEqual(record["flow_origin"], "scope_pending")

    def test_generic_meta_ads_origin_does_not_prove_therapify_campaign(self):
        with mock.patch.object(wm, "_admit_new_contacts_to_funnel", return_value=False):
            allowed, reason = wm._ensure_contact_ai_access(
                CHAT,
                CHAT,
                message_text="Oi, tudo bem?",
                commercial_metadata={"origin": "meta_ads"},
            )
        self.assertEqual((allowed, reason), (False, "commercial-scope-unconfirmed"))
        record = self._record()
        self.assertFalse(record["ai_enabled"])
        self.assertFalse(record["in_flow"])
        self.assertEqual(record["flow_origin"], "scope_pending")

    def test_generic_clinical_words_do_not_prove_therapify_campaign(self):
        for text in ("Quero uma consulta geral", "Estou desesperado", "Meu ex me chamou"):
            with self.subTest(text=text):
                self.assertFalse(
                    wm._contact_has_profile_scope_signal(
                        text,
                        {"origin": "meta_ads", "campaign": "consulta geral"},
                    )
                )

    def test_campaign_metadata_must_identify_therapify_scope(self):
        allowed, reason = wm._ensure_contact_ai_access(
            CHAT,
            CHAT,
            message_text="Oi, tudo bem?",
            commercial_metadata={
                "origin": "meta_ads",
                "campaign": "Therapify - Dependência emocional - Rodrigo",
            },
        )
        self.assertEqual((allowed, reason), (True, "new-commercial-inbound"))
        self.assertTrue(self._record()["ai_enabled"])

    def test_native_ad_title_can_identify_therapify_when_campaign_id_is_opaque(self):
        allowed, reason = wm._ensure_contact_ai_access(
            CHAT,
            CHAT,
            message_text="Olá! Tenho interesse e queria mais informações, por favor.",
            commercial_metadata={
                "origin": "FB_Ads",
                "campaign": "120099999999999999",
                "ad_title": "Tratamento para dependência emocional com Dr. Rodrigo",
            },
        )
        self.assertEqual((allowed, reason), (True, "new-commercial-inbound"))
        self.assertTrue(self._record()["ai_enabled"])

    def test_old_unverified_auto_admission_is_quarantined(self):
        self.contacts_path.write_text(json.dumps({CHAT: {
            "ai_enabled": True,
            "in_flow": True,
            "flow_origin": "new_live_commercial",
            "ai_policy_version": 2,
        }}), encoding="utf-8")
        allowed, reason = wm._ensure_contact_ai_access(
            CHAT,
            CHAT,
            message_text="Quero falar sobre a minha transmissão ao vivo",
            commercial_metadata={},
        )
        self.assertEqual((allowed, reason), (False, "commercial-scope-unconfirmed"))
        record = self._record()
        self.assertFalse(record["ai_enabled"])
        self.assertEqual(record["flow_origin"], "scope_pending")

    def test_stale_auto_admission_has_no_fast_path_access_before_migration(self):
        self.contacts_path.write_text(json.dumps({CHAT: {
            "ai_enabled": True,
            "in_flow": True,
            "flow_origin": "new_live_commercial",
            "ai_policy_version": 2,
        }}), encoding="utf-8")

        self.assertFalse(wm._contact_has_explicit_ai_access(CHAT, CHAT))

    def test_missing_therapify_admission_profile_fails_closed(self):
        with mock.patch.object(wm, "_profile_lookup", return_value=None):
            self.assertFalse(
                wm._contact_has_profile_scope_signal(
                    "Quero uma consulta",
                    {"origin": "meta_ads", "campaign": "consulta geral"},
                )
            )


class OwnerTakeoverPersistenceTests(unittest.TestCase):
    def test_takeover_stays_until_explicit_reenable(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = FollowupEngine(Path(tmp) / "followups.db")
            now = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
            engine.configure_lead(
                CHAT,
                automation_enabled=True,
                stage="qualification",
                now=now,
            )
            engine.note_human_takeover(CHAT, at=now)

            engine.configure_lead(CHAT, automation_enabled=True, now=now)
            still_taken_over = engine.get_lead(CHAT)
            self.assertIsNotNone(still_taken_over)
            self.assertTrue(bool(still_taken_over["takeover"]))
            self.assertFalse(engine._row_eligible(still_taken_over))

            engine.configure_lead(
                CHAT,
                automation_enabled=True,
                takeover=False,
                now=now,
            )
            reenabled = engine.get_lead(CHAT)
            self.assertIsNotNone(reenabled)
            self.assertFalse(bool(reenabled["takeover"]))
            self.assertTrue(engine._row_eligible(reenabled))


if __name__ == "__main__":
    unittest.main()
