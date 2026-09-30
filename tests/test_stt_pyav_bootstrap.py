from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "deploy" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ensure_stt_pyav


class PyAVBootstrapTests(unittest.TestCase):
    def test_compatible_target_is_left_alone(self):
        with patch.object(ensure_stt_pyav, "_installed_version", return_value="18.1.0"):
            self.assertFalse(ensure_stt_pyav.ensure_pyav(Path("/tmp/lazy"), uv="uv"))

    def test_incompatible_transitive_version_is_replaced_in_lazy_target(self):
        versions = iter((None, "19.0.0", "18.1.0"))
        run = Mock(return_value=SimpleNamespace(returncode=0))
        with (
            patch.object(ensure_stt_pyav, "_installed_version", side_effect=lambda target: next(versions)),
            patch.object(ensure_stt_pyav.sys, "executable", "/hermes/python"),
        ):
            self.assertTrue(ensure_stt_pyav.ensure_pyav(Path("/lazy"), uv="/bin/uv", run=run))
        self.assertEqual(
            run.call_args.args[0],
            ["/bin/uv", "pip", "install", "--python", "/hermes/python", "--target", "/lazy", "--no-deps", "av==18.1.0"],
        )

    def test_failed_install_raises_a_sanitized_code(self):
        versions = iter((None, "19.0.0"))
        run = Mock(return_value=SimpleNamespace(returncode=1, stderr="private output"))
        with patch.object(ensure_stt_pyav, "_installed_version", side_effect=lambda target: next(versions)):
            with self.assertRaisesRegex(RuntimeError, "pyav_install_failed"):
                ensure_stt_pyav.ensure_pyav(Path("/lazy"), uv="/bin/uv", run=run)


try:
    import av
    from faster_whisper.audio import decode_audio
except ImportError as exc:
    if os.environ.get("AYA_REQUIRE_STT_DEPS") == "1":
        raise
    _stt_import_error = str(exc)
else:
    _stt_import_error = None


@unittest.skipIf(_stt_import_error is not None, f"optional STT dependencies unavailable: {_stt_import_error}")
class PyAVDecodeTests(unittest.TestCase):
    def test_faster_whisper_decodes_synthetic_wav_with_pinned_pyav(self):
        import io
        import wave

        wav = io.BytesIO()
        with wave.open(wav, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 1600)
        wav.seek(0)

        decoded = decode_audio(wav)

        self.assertEqual(av.__version__, ensure_stt_pyav.PYAV_VERSION)
        self.assertEqual(decoded.shape, (1600,))
        self.assertEqual(float(decoded.max()), 0.0)


if __name__ == "__main__":
    unittest.main()
