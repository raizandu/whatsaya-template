import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


WRAPPER = Path(__file__).resolve().parents[1] / "deploy/scripts/tick_whatsapp_audit_local.sh"


class AuditLocalWrapperTests(unittest.TestCase):
    def _run_wrapper(self, profile="therapify", key_file=None, inherited_key=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / ".hermes"
            home.mkdir()
            source = home / "whatsapp_audit_openai_key"
            if key_file is not None:
                source.write_text(key_file, encoding="utf-8")
                source.chmod(0o600)
            capture = root / "capture.json"
            python = root / "python3"
            python.write_text(
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "pathlib.Path(os.environ['AUDIT_CAPTURE']).write_text(json.dumps({\n"
                "'argv': sys.argv[1:],\n"
                "'key': os.getenv('OPENAI_API_KEY'),\n"
                "'provider': os.getenv('WHATSAPP_AUDIT_PROVIDER'),\n"
                "'model': os.getenv('WHATSAPP_AUDIT_MODEL'),\n"
                "'enabled': os.getenv('WHATSAPP_AUDIT_ENABLED'),\n"
                "'client_provider': os.getenv('WHATSAPP_CLIENT_PROVIDER'),\n"
                "}))\n",
                encoding="utf-8",
            )
            python.chmod(0o700)
            env = {
                "PATH": str(root) + os.pathsep + os.defpath,
                "HERMES_HOME": str(home),
                "WHATSAPP_BUSINESS_PROFILE": profile,
                "WHATSAPP_AUDIT_PROVIDER": "openrouter",
                "WHATSAPP_AUDIT_MODEL": "configured-model",
                "WHATSAPP_CLIENT_PROVIDER": "openai-codex",
                "AUDIT_CAPTURE": str(capture),
            }
            if inherited_key is not None:
                env["OPENAI_API_KEY"] = inherited_key
            result = subprocess.run(
                ["/bin/sh", str(WRAPPER), "2026-11-03"],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            return json.loads(capture.read_text()), result.stderr

    def test_cron_without_inherited_key_loads_private_audit_key(self):
        captured, stderr = self._run_wrapper(key_file="sk-audit-test\n")
        self.assertEqual(captured["key"], "sk-audit-test")
        self.assertEqual(captured["provider"], "openai")
        self.assertEqual(captured["model"], "gpt-4.1")
        self.assertEqual(captured["client_provider"], "openai-codex")
        self.assertEqual(captured["argv"], [
            "/opt/data/.hermes/scripts/tick_whatsapp_audit.py", "--local-only", "2026-11-03",
        ])
        self.assertEqual(stderr, "")

    def test_explicit_key_has_priority_over_file(self):
        captured, _ = self._run_wrapper(key_file="sk-file-test\n", inherited_key="sk-explicit-test")
        self.assertEqual(captured["key"], "sk-explicit-test")

    def test_other_profiles_do_not_load_audit_key_or_change_provider(self):
        captured, stderr = self._run_wrapper(profile="other", key_file="sk-audit-test\n")
        self.assertIsNone(captured["key"])
        self.assertEqual(captured["provider"], "openrouter")
        self.assertEqual(captured["model"], "configured-model")
        self.assertEqual(stderr, "")

    def test_missing_key_keeps_report_path_and_warns_without_values(self):
        captured, stderr = self._run_wrapper()
        self.assertFalse(captured["key"])
        self.assertIn("OPENAI_API_KEY indisponível", stderr)
        self.assertIn("whatsapp_audit_openai_key", stderr)


if __name__ == "__main__":
    unittest.main()
