"""transform_llm_output chega sem turn_id no Hermes v2026.7.20; o plugin reutiliza o do pre_llm_call."""
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


class HookTurnIdTest(unittest.TestCase):
    def setUp(self):
        wm._session_core_turns.clear()
        self.enterContext(mock.patch.object(wm, "_runtime_turn_for_session", return_value=None))

    def test_direct_turn_id_is_remembered_for_hooks_without_it(self):
        self.assertEqual(wm._hook_turn_id("sess-1", {"turn_id": "turn-A"}), "turn-A")
        self.assertEqual(wm._hook_turn_id("sess-1", {}), "turn-A")
        self.assertEqual(wm._hook_turn_id("sess-1", {"platform": "whatsapp"}), "turn-A")

    def test_memory_is_per_session_and_follows_newest_turn(self):
        wm._hook_turn_id("sess-1", {"turn_id": "turn-A"})
        wm._hook_turn_id("sess-2", {"turn_id": "turn-B"})
        self.assertEqual(wm._hook_turn_id("sess-1", {}), "turn-A")
        self.assertEqual(wm._hook_turn_id("sess-2", {}), "turn-B")
        wm._hook_turn_id("sess-1", {"turn_id": "turn-C"})
        self.assertEqual(wm._hook_turn_id("sess-1", {}), "turn-C")

    def test_unknown_session_and_expired_memory_yield_empty(self):
        self.assertEqual(wm._hook_turn_id("sess-9", {}), "")
        wm._hook_turn_id("sess-1", {"turn_id": "turn-A"})
        with mock.patch.object(wm.time, "time", return_value=wm.time.time() + wm._CORE_TURN_BINDING_TTL_S + 1):
            self.assertEqual(wm._hook_turn_id("sess-1", {}), "")


if __name__ == "__main__":
    unittest.main()
