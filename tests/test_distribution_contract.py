from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class DistributionContractTests(unittest.TestCase):
    def test_compose_defaults_to_public_distribution_and_generic_config(self):
        compose = (ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn(
            "HERMES_SETUP_GITHUB_REPO=${HERMES_SETUP_GITHUB_REPO:-whatsaya-template}",
            compose,
        )
        self.assertIn(
            "HERMES_SETUP_GITHUB_REF=${HERMES_SETUP_GITHUB_REF:-main}", compose
        )
        self.assertIn(
            "WHATSAPP_CONFIG_SUBDIR=${WHATSAPP_CONFIG_SUBDIR:-generic}", compose
        )
        self.assertIn("WHATSAPP_PANEL_CONFIG=/opt/data/panel.config.json", compose)

    def test_plugin_distribution_ref_is_configurable_and_validated(self):
        import whatsapp_manager as wm

        keys = {
            "HERMES_SETUP_GITHUB_USER": "example",
            "HERMES_SETUP_GITHUB_REPO": "distribution",
            "HERMES_SETUP_GITHUB_REF": "v2026.09.08",
        }
        with patch.dict(os.environ, keys, clear=False):
            self.assertEqual(wm.config.plugin_github_ref, "v2026.09.08")
            self.assertEqual(
                wm.config.plugin_raw_root,
                "https://raw.githubusercontent.com/example/distribution/v2026.09.08",
            )

        with patch.dict(
            os.environ, {"HERMES_SETUP_GITHUB_REF": "--upload-pack=bad"}, clear=False
        ):
            self.assertEqual(wm.config.plugin_github_ref, "main")

    def test_public_builder_uses_an_allowlist(self):
        builder = (ROOT / "tools/build-public-template.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("paths=(", builder)
        self.assertNotIn("git archive --format=tar HEAD |", builder)
        self.assertIn("deploy/instance", builder)
        self.assertIn("graphify-out", builder)


if __name__ == "__main__":
    unittest.main()
