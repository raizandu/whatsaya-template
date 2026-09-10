"""Fase 3 automática: prova social, reframe e agenda depois da última linha do diagnóstico."""
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
TRIGGER_TURN = "[[CITA: 1]] Ok✅\n\n[[CITA: 2]] Tudo bem\n\nTudo bem\n\nRapidamente a gente muda isso"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class _ImmediateThread:
    def __init__(self, *, target, args=(), daemon=None, name=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class PlaybookCompletionTest(unittest.TestCase):
    def setUp(self):
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        wm._calendar_turn_state.pop(CHAT, None)

    def test_config_comes_from_profile(self):
        cfg = wm._playbook_completion_config()
        self.assertEqual(cfg["media_key"], "social_proof")
        self.assertEqual(len(cfg["lines"]), 3)
        self.assertTrue(cfg["lines"][-1].startswith("Tudo bem"))
        self.assertIn("confortável", cfg["schedule_question"])
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            _reset_profile_cache()
            self.assertEqual(wm._playbook_completion_config(), {})

    def test_trigger_matches_only_as_last_bubble(self):
        pattern = wm._playbook_completion_config()["trigger_regex"]
        self.assertTrue(wm._last_bubble_matches(TRIGGER_TURN, pattern))
        self.assertTrue(wm._last_bubble_matches("Rapidamente você muda isso!", pattern))
        self.assertFalse(wm._last_bubble_matches("Rapidamente a gente muda isso\n\nQual horário?", pattern))
        self.assertFalse(wm._last_bubble_matches("", pattern))

    def test_order_guard_reads_bot_lines_only(self):
        history = "Dr. Rodrigo Melo: Isso vem te afetando no trabalho em outros momento também?\nLead: sim"
        with mock.patch.object(wm, "_fetch_chat_history", return_value=history):
            self.assertTrue(wm._chat_bot_sent_matching(CHAT, "afetando no trabalho"))
        with mock.patch.object(wm, "_fetch_chat_history", return_value="Lead: isso afetando no trabalho"):
            self.assertFalse(wm._chat_bot_sent_matching(CHAT, "afetando no trabalho"))
        self.assertTrue(wm._chat_bot_sent_matching(CHAT, ""))

    def test_media_items_skip_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"; video.write_bytes(b"x")
            img = Path(tmp) / "1.jpeg"; img.write_bytes(b"x")
            manifest = Path(tmp) / "media-manifest.json"
            manifest.write_text(json.dumps({"social_proof": {"items": [
                {"type": "video", "path": str(video)},
                {"type": "image", "path": str(img), "caption": ""},
                {"type": "image", "path": str(Path(tmp) / "missing.jpeg")},
                {"type": "audio", "path": str(img)},
            ]}}), encoding="utf-8")
            items = wm._load_media_items("social_proof", manifest_path=manifest)
        self.assertEqual([(i["type"], Path(i["path"]).name) for i in items], [("video", "v.mp4"), ("image", "1.jpeg")])
        self.assertEqual(wm._load_media_items("nope", manifest_path=Path("/nao/existe.json")), [])

    def test_sequence_runs_once_per_lead(self):
        cfg = wm._playbook_completion_config()
        runs = []
        record = {}
        with mock.patch.object(wm, "_contact_record_for_chat", side_effect=lambda cid, contacts=None: dict(record)), \
             mock.patch.object(wm, "_merge_contact_record_atomic", side_effect=lambda key, fields, **kw: record.update(fields)), \
             mock.patch.object(wm, "_chat_bot_sent_matching", return_value=True), \
             mock.patch.object(wm, "_run_playbook_completion", side_effect=lambda *a: runs.append(a)), \
             mock.patch.object(wm.threading, "Thread", _ImmediateThread):
            self.assertTrue(wm._maybe_start_playbook_completion(CHAT, TRIGGER_TURN, ("m1", 1.0)))
            self.assertFalse(wm._maybe_start_playbook_completion(CHAT, TRIGGER_TURN, ("m2", 2.0)))
            self.assertFalse(wm._maybe_start_playbook_completion(CHAT, "Olá! Atendimento 100% online", ("m3", 3.0)))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][1]["media_key"], cfg["media_key"])
        self.assertIn(wm._PLAYBOOK_COMPLETION_FIELD, record)

    def test_sequence_blocked_before_diagnostic(self):
        with mock.patch.object(wm, "_chat_bot_sent_matching", return_value=False), \
             mock.patch.object(wm, "_playbook_completion_claim") as claim:
            self.assertFalse(wm._maybe_start_playbook_completion(CHAT, TRIGGER_TURN, None))
        claim.assert_not_called()

    def test_run_sends_media_then_reframe_then_agenda(self):
        cfg = wm._playbook_completion_config()
        sent = []
        with mock.patch.object(wm, "_load_media_items", return_value=[
                {"path": "/m/v.mp4", "type": "video", "caption": ""}, {"path": "/m/1.jpeg", "type": "image", "caption": ""}]), \
             mock.patch.object(wm, "_send_bridge_media", side_effect=lambda cid, path, kind: sent.append(("media", kind)) or "id"), \
             mock.patch.object(wm, "_human_send", side_effect=lambda cid, text, **kw: sent.append(("text", text)) or "id"), \
             mock.patch.object(wm, "_playbook_offer_slots", side_effect=lambda *a: sent.append(("agenda", None)) or True), \
             mock.patch.object(wm.time, "sleep"):
            wm._run_playbook_completion(CHAT, cfg, ("m1", 1.0))
        self.assertEqual([s[0] for s in sent], ["media", "media", "text", "agenda"])
        self.assertEqual(sent[0][1], "video")
        self.assertEqual(sent[2][1], "\n\n".join(cfg["lines"]))

    def test_offer_publishes_slots_and_asks_playbook_question(self):
        cfg = dict(wm._playbook_completion_config(), schedule_style="nearest")
        slots = [
            {"start": "2999-01-07T08:00:00-03:00", "end": "2999-01-07T09:00:00-03:00"},
            {"start": "2999-01-07T11:00:00-03:00", "end": "2999-01-07T12:00:00-03:00"},
        ]
        sent = []
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), \
             mock.patch.object(wm, "find_available_slots", return_value={"slots": slots, "timezone": "America/Sao_Paulo"}), \
             mock.patch.object(wm, "_current_inbound_record", return_value={}), \
             mock.patch.object(wm, "_human_send", side_effect=lambda cid, text, **kw: sent.append(text) or "id"):
            self.assertTrue(wm._playbook_offer_slots(CHAT, cfg, ("m1", 1.0)))
        state = wm._calendar_turn_state[CHAT]
        self.assertEqual(state["kind"], "offered")
        self.assertEqual(state["slots"], slots)
        self.assertEqual(state["inbound_token"], ("m1", 1.0))
        self.assertIn("1. ", sent[0])
        self.assertIn("horário de Brasília", sent[0])
        self.assertTrue(sent[0].endswith(cfg["schedule_question"]))
        self.assertEqual(wm._calendar_selected_slot("o segundo", slots), slots[1])

    def test_offer_skips_when_newer_message_arrived(self):
        cfg = dict(wm._playbook_completion_config(), schedule_style="nearest")
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), \
             mock.patch.object(wm, "find_available_slots", return_value={"slots": [{"start": "2999-01-07T08:00:00-03:00", "end": "2999-01-07T09:00:00-03:00"}]}), \
             mock.patch.object(wm, "_current_inbound_record", return_value={"message_id": "novo", "text": "oi"}), \
             mock.patch.object(wm, "_inbound_record_token", return_value=("novo", 9.0)), \
             mock.patch.object(wm, "_human_send") as send:
            self.assertFalse(wm._playbook_offer_slots(CHAT, cfg, ("m1", 1.0)))
        send.assert_not_called()
        self.assertNotIn(CHAT, wm._calendar_turn_state)


class DayScheduleDisplayTest(unittest.TestCase):
    def setUp(self):
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        wm._calendar_turn_state.pop(CHAT, None)

    def _days(self):
        import datetime as dt
        tz = dt.timezone(dt.timedelta(hours=-3))
        d = lambda day, h: dt.datetime(2999, 1, day, h, 0, tzinfo=tz)
        return [
            {"date": dt.date(2999, 1, 7), "slots": [
                {"start": d(7, 8), "end": d(7, 9), "status": "occupied", "name": "Tony"},
                {"start": d(7, 11), "end": d(7, 12), "status": "free", "name": ""},
                {"start": d(7, 13), "end": d(7, 14), "status": "occupied", "name": "Almir"},
                {"start": d(7, 16), "end": d(7, 17), "status": "free", "name": ""},
                {"start": d(7, 19), "end": d(7, 20), "status": "free", "name": ""},
            ]},
            {"date": dt.date(2999, 1, 8), "slots": [
                {"start": d(8, 9), "end": d(8, 10), "status": "free", "name": ""},
                {"start": d(8, 10), "end": d(8, 11), "status": "occupied", "name": ""},
            ]},
        ], d

    def test_format_matches_legacy_playbook(self):
        import datetime as dt
        days, d = self._days()
        formatted = wm._format_day_schedule(days, d(7, 7))
        self.assertEqual(formatted[0]["message"].split("\n"), [
            "📅 Segunda-feira, 07/01/2999:",
            "08:00 – ❌ Consulta Tony",
            "11:00 – ✅ Disponível",
            "13:00 – ❌ Atendimento Almir",
            "16:00 – ✅ Disponível",
            "19:00 – ✅ Disponível",
        ])
        self.assertEqual(formatted[0]["free_summary"], "Hoje ainda venho a ter disponibilidade 11:00, 16:00 ou 19:00")
        self.assertEqual(formatted[1]["message"].split("\n")[-1], "10:00 – ❌ Ocupado")
        self.assertEqual(formatted[1]["free_summary"], "Amanhã venho a ter disponibilidade 09:00")
        later = wm._format_day_schedule(days[1:], d(7, 7) - dt.timedelta(days=3))
        self.assertTrue(later[0]["free_summary"].startswith("Terça venho a ter"))

    def test_day_schedule_offer_sends_bubbles_and_publishes_free_slots(self):
        cfg = wm._playbook_completion_config()
        self.assertEqual(cfg["schedule_style"], "day_schedule")
        days, d = self._days()
        sent = []
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), \
             mock.patch.object(wm, "day_schedule", return_value=days), \
             mock.patch.object(wm, "_current_inbound_record", return_value={}), \
             mock.patch.object(wm, "_human_send", side_effect=lambda cid, text, **kw: sent.append(text) or "id"):
            self.assertTrue(wm._playbook_offer_slots(CHAT, cfg, ("m1", 1.0)))
        bubbles = sent[0].split("\n\n")
        # Primeiro dia tem livre: só ele vai (padrão mais comum no histórico real).
        self.assertEqual(len(bubbles), 3)
        self.assertTrue(bubbles[0].startswith("📅 "))
        self.assertTrue(bubbles[1].startswith("Segunda venho a ter disponibilidade 11:00"))
        self.assertEqual(bubbles[-1], cfg["schedule_question"])
        state = wm._calendar_turn_state[CHAT]
        self.assertEqual(state["kind"], "offered")
        self.assertEqual([s["start"][11:16] for s in state["slots"]], ["11:00", "16:00", "19:00"])
        self.assertEqual(wm._calendar_selected_slot("pode ser às 16", state["slots"]), state["slots"][1])

    def test_day_schedule_extends_when_first_day_is_full(self):
        cfg = wm._playbook_completion_config()
        days, d = self._days()
        days[0]["slots"] = [s for s in days[0]["slots"] if s["status"] == "occupied"]
        sent = []
        with mock.patch.object(wm, "_calendar_is_ready", return_value=True), \
             mock.patch.object(wm, "day_schedule", return_value=days), \
             mock.patch.object(wm, "_current_inbound_record", return_value={}), \
             mock.patch.object(wm, "_human_send", side_effect=lambda cid, text, **kw: sent.append(text) or "id"):
            self.assertTrue(wm._playbook_offer_slots(CHAT, cfg, ("m1", 1.0)))
        bubbles = sent[0].split("\n\n")
        self.assertEqual(sum(b.startswith("📅 ") for b in bubbles), 2)
        self.assertEqual([s["start"][11:16] for s in wm._calendar_turn_state[CHAT]["slots"]], ["09:00"])


if __name__ == "__main__":
    unittest.main()
