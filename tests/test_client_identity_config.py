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


class ClientIdentityConfigTests(unittest.TestCase):
    def test_explicit_names_override_instance_defaults_and_legacy_profile_settings(self):
        with mock.patch.dict(os.environ, {
            "WHATSAPP_CONFIG_SUBDIR": "instance",
            "WHATSAPP_BUSINESS_NAME": "Cuidar Odontologia",
            "WHATSAPP_ASSISTANT_NAME": "AYA",
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": "/tmp/legacy-profile.json",
        }, clear=True):
            self.assertEqual(wm.config.whatsapp_business_name, "Cuidar Odontologia")
            self.assertEqual(wm.config.whatsapp_assistant_name, "AYA")

    def test_instance_uses_aya_defaults(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_CONFIG_SUBDIR": "instance"}, clear=True):
            self.assertEqual(wm.config.whatsapp_business_name, "WhatsAYA")
            self.assertEqual(wm.config.whatsapp_assistant_name, "AYA")

    def test_generic_installation_uses_generic_defaults_even_with_legacy_profile(self):
        with mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": "/tmp/legacy-profile.json",
        }, clear=True):
            self.assertEqual(wm.config.whatsapp_business_name, "esta empresa")
            self.assertEqual(wm.config.whatsapp_assistant_name, "Atendimento")


if __name__ == "__main__":
    unittest.main()
