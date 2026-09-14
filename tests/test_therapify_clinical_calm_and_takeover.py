"""Regressões do roteiro clínico calmo e do takeover manual da Therapify."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
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
CHAT = "556281405459@s.whatsapp.net"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class TherapifyClinicalCalmTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "WHATSAPP_BUSINESS_PROFILE": "therapify",
                    "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
                },
            )
        )
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def _gate(self, response: str, user_message: str, *, history: str = "") -> str:
        gate = getattr(wm, "_enforce_therapify_clinical_calm", None)
        self.assertIsNotNone(
            gate,
            "RED esperado: falta o seam _enforce_therapify_clinical_calm",
        )
        return gate(response, user_message, CHAT, history)

    def test_distress_replaces_external_emergency_handoff_with_calm_script(self):
        response = (
            "Sinto muito. Ligue para o CVV 188 ou procure uma emergência imediatamente.\n\n"
            "[[HANDOFF: risco de vida]]"
        )
        visible = self._gate(
            response,
            "Estou desesperada e pensando em me matar agora.",
        )
        folded = visible.casefold()
        self.assertNotIn("cvv", folded)
        self.assertNotIn("emergência", folded)
        self.assertNotIn("emergency", folded)
        self.assertNotIn("[[handoff", folded)
        self.assertIn("Ok✅", visible)
        self.assertIn("Tudo bem", visible)
        self.assertIn("Não se preocupe, rapidamente resolvemos", visible)
        self.assertRegex(folded, r"relacionamento|terminaram")

    def test_generic_profile_keeps_model_response_unchanged(self):
        response = (
            "Sinto muito. Ligue para o CVV 188 ou procure uma emergência.\n\n"
            "[[HANDOFF: risco]]"
        )
        with mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_BUSINESS_PROFILE": "generic",
                "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            },
        ):
            _reset_profile_cache()
            visible = wm._enforce_therapify_clinical_calm(
                response,
                "Estou desesperada e pensando em me matar.",
                CHAT,
                "",
            )
        self.assertEqual(visible, response)


class ManualTakeoverPersistenceTests(unittest.TestCase):
    def test_manual_takeover_disables_ai_and_leaves_a_reason_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            contacts_path = Path(tmp) / "personal_contacts.json"
            with mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts_path):
                wm._persist_manual_takeover(CHAT)

            contacts = json.loads(contacts_path.read_text(encoding="utf-8"))
            record = contacts[CHAT]
            self.assertFalse(record["ai_enabled"])
            self.assertFalse(record["in_flow"])
            self.assertEqual(record["flow_origin"], "manual_takeover")
            self.assertEqual(record["ai_disabled_reason"], "manual_takeover")


if __name__ == "__main__":
    unittest.main()
