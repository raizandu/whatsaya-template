from __future__ import annotations

import io
import sys
import tempfile
import time
import unittest
import urllib.error
from types import SimpleNamespace
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "deploy" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import fish_tts


class _SyntheticResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FishTtsTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input_path = self.root / "input.txt"
        self.output_path = self.root / "nested" / "output.ogg"
        self.input_path.write_text("Frase sintética de teste.", encoding="utf-8")
        self.argv = ["fish_tts.py", str(self.input_path), str(self.output_path), "ogg"]
        self.environment = patch.dict(fish_tts.os.environ, {"FISH_API_KEY": "synthetic-key"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _run(self, urlopen_side_effect, clock_values):
        stderr = io.StringIO()
        with (
            patch.object(fish_tts.sys, "argv", self.argv),
            patch.object(fish_tts.urllib.request, "urlopen", side_effect=urlopen_side_effect),
            patch.object(time, "monotonic", side_effect=clock_values),
            redirect_stderr(stderr),
        ):
            result = fish_tts.main()
        return result, stderr.getvalue()

    def test_synthetic_success_logs_stage_durations_without_spoken_text(self):
        result, logs = self._run(
            lambda *args, **kwargs: _SyntheticResponse(b"synthetic-audio-bytes"),
            [10.0, 10.125, 20.0, 20.025],
        )

        self.assertEqual(result, 0)
        self.assertEqual(self.output_path.read_bytes(), b"synthetic-audio-bytes")
        self.assertIn("stage=fish_api_synthesis status=ok duration_ms=125", logs)
        self.assertIn("stage=local_output_write status=ok duration_ms=25", logs)
        self.assertNotIn("Frase sintética de teste", logs)

    def test_http_failure_logs_duration_and_code_without_response_body(self):
        error = urllib.error.HTTPError(
            "https://api.fish.audio/v1/tts", 503, "unavailable", {},
            io.BytesIO(b"synthetic response body must stay private"),
        )

        result, logs = self._run(
            lambda *args, **kwargs: (_ for _ in ()).throw(error),
            [30.0, 30.250],
        )

        self.assertEqual(result, 1)
        self.assertIn("stage=fish_api_synthesis status=error duration_ms=250 error=http_503", logs)
        self.assertNotIn("synthetic response body", logs)
        self.assertFalse(self.output_path.exists())

    def test_local_output_failure_logs_stage_and_duration_without_path(self):
        self.output_path.parent.write_text("not a directory", encoding="utf-8")

        result, logs = self._run(
            lambda *args, **kwargs: _SyntheticResponse(b"synthetic-audio-bytes"),
            [1.0, 1.1, 2.0, 2.150],
        )

        self.assertEqual(result, 1)
        self.assertIn("stage=fish_api_synthesis status=ok duration_ms=100", logs)
        self.assertIn(
            "stage=local_output_write status=error duration_ms=150 error=filesystem_error",
            logs,
        )
        self.assertNotIn(str(self.output_path), logs)


class VoiceTimingForwardingTests(unittest.TestCase):
    def test_voice_delivery_forwards_only_structured_stage_metrics(self):
        import whatsapp_manager as wm
        def synthesize(args, **kwargs):
            Path(args[3]).write_bytes(b"a" * 80)
            return SimpleNamespace(returncode=0, stderr=(
                "fish_tts stage=fish_api_synthesis status=ok duration_ms=125\n"
                "private synthetic text\n"
                "fish_tts stage=other status=ok duration_ms=123 secret=value\n"))
        with (
            patch.object(wm, "_voice_reply_allowed_for", return_value=True),
            patch.object(wm, "_fish_tts_path", return_value=Path("synthetic-script.py")),
            patch.object(wm, "_fish_call", return_value=None),
            patch.object(wm, "_prepare_spoken_for_tts", return_value="Texto sintético."),
            patch.object(wm.urllib.request, "urlopen", return_value=_SyntheticResponse(b"")),
            patch.object(wm.subprocess, "run", side_effect=synthesize),
            patch.object(wm, "_send_bridge_media", return_value="synthetic-message-id") as send,
            patch.object(wm.logger, "info") as log,
        ):
            result = wm._maybe_send_voice("5511999999999@s.whatsapp.net", "Texto sintético.")
        self.assertEqual(result, "synthetic-message-id")
        self.assertEqual(send.call_count, 1)
        metrics = [call for call in log.call_args_list if call.args[0] == "[voice-timing] %s"]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].args[1], "fish_tts stage=fish_api_synthesis status=ok duration_ms=125")


if __name__ == "__main__":
    unittest.main()
