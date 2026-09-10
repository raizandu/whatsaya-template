"""Qualificação do lead: campos do playbook extraídos após a reserva, no evento e no banco."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("WHATSAPP_HUMAN_TEST_MODE", "1")

import calendar_booking as cb  # noqa: E402
from tests.test_calendar_booking import FakeService, _CalendarTestCase, _dt, _event  # noqa: E402

MODULE_PATH = REPO_ROOT / "whatsapp_manager.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_manager", MODULE_PATH)
assert SPEC and SPEC.loader
wm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wm
SPEC.loader.exec_module(wm)

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
ITEMS = [
    {"key": "tempo_termino", "label": "Tempo do término", "value": "mais ou menos 1 mês"},
    {"key": "ansiedade_0_10", "label": "Ansiedade (0 a 10)", "value": "9"},
    {"key": "vazio", "label": "Vazio", "value": ""},
]


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class QualificationBlockTests(unittest.TestCase):
    def test_block_lists_only_filled_fields(self):
        block = cb.format_qualification_block(ITEMS)
        self.assertEqual(block.split("\n"), [cb.QUALIFICATION_MARKER, "Tempo do término: mais ou menos 1 mês", "Ansiedade (0 a 10): 9"])
        self.assertEqual(cb.format_qualification_block([]), "")
        self.assertEqual(cb.format_qualification_block([{"label": "X", "value": " "}]), "")


class QualificationStoreAndEventTests(_CalendarTestCase):
    def _therapify(self):
        self._set_config(
            availability_mode="explicit_slots", business_start="09:00", business_end="22:00",
            duration_minutes=60, slot_keyword="Livre", block_keyword="Bloqueada", event_title="Sessão Therapify",
        )

    def test_roundtrip_drops_empty_values(self):
        cb.save_lead_qualification("5511999990040", ITEMS, event_id="ev", db_path=self.bookings_db)
        stored = cb.get_lead_qualification("5511999990040", db_path=self.bookings_db)
        self.assertEqual([i["key"] for i in stored], ["tempo_termino", "ansiedade_0_10"])
        self.assertEqual(cb.get_lead_qualification("5511999990099", db_path=self.bookings_db), [])

    def test_apply_writes_block_below_header_and_replaces_old_block(self):
        self._therapify()
        fake = FakeService(events=[_event("vaga", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre")])
        created = cb.create_booking(
            chat_id="5511999990041", start=_dt(2999, 1, 7, 8, 0).isoformat(),
            end=_dt(2999, 1, 7, 9, 0).isoformat(), lead_name="Ana", service=fake,
        )
        base = fake.events_store[created["event_id"]]["description"]
        self.assertIn("Origem:", base)
        self.assertTrue(cb.apply_qualification_to_event("5511999990041", ITEMS, service=fake, db_path=self.bookings_db))
        first = fake.patch_calls[-1][1]["description"]
        self.assertTrue(first.startswith(base + "\n\n" + cb.QUALIFICATION_MARKER))
        self.assertIn("Ansiedade (0 a 10): 9", first)
        cb.apply_qualification_to_event(
            "5511999990041", [{"key": "tempo_termino", "label": "Tempo do término", "value": "2 meses"}],
            service=fake, db_path=self.bookings_db,
        )
        second = fake.patch_calls[-1][1]["description"]
        self.assertEqual(second.count(cb.QUALIFICATION_MARKER), 1)
        self.assertIn("2 meses", second)
        self.assertNotIn("Ansiedade", second)
        self.assertEqual(cb.get_lead_qualification("5511999990041", db_path=self.bookings_db)[0]["value"], "2 meses")

    def test_apply_without_active_booking_only_stores(self):
        self._therapify()
        self.assertFalse(cb.apply_qualification_to_event("5511999990042", ITEMS, service=FakeService(), db_path=self.bookings_db))
        self.assertEqual(len(cb.get_lead_qualification("5511999990042", db_path=self.bookings_db)), 2)


class QualificationExtractionTests(unittest.TestCase):
    def setUp(self):
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
            "OPENAI_API_KEY": "sk-test",
        }))

    def test_fields_come_from_profile(self):
        keys = [f["key"] for f in wm._qualification_fields()]
        self.assertEqual(keys[:2], ["tempo_termino", "como_lida"])
        self.assertIn("ansiedade_0_10", keys)
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            _reset_profile_cache()
            self.assertEqual(wm._qualification_fields(), [])

    def test_parse_keeps_playbook_order_and_skips_empty(self):
        fields = wm._qualification_fields()
        items = wm._parse_qualification_response(
            json.dumps({"ansiedade_0_10": "9", "tempo_termino": " mais ou menos 1 mês ", "sintomas": "", "inventado": "x", "alimentacao": None}),
            fields,
        )
        self.assertEqual([(i["key"], i["value"]) for i in items], [("tempo_termino", "mais ou menos 1 mês"), ("ansiedade_0_10", "9")])
        self.assertEqual(wm._parse_qualification_response("não é json", fields), [])

    def test_extract_uses_history_and_classifier_model(self):
        seen = {}

        def fake_call(url, headers, payload, extract_fn, timeout=30):
            seen["payload"] = payload
            return json.dumps({"tempo_termino": "1 mês", "como_lida": "difícil", "sintomas": "ansiedade", "alimentacao": "mal", "ansiedade_0_10": "9", "impacto_trabalho": "sim", "observacoes": ""})

        with mock.patch.object(wm, "_fetch_chat_history", return_value="Lead: Bom tem sido dificil\nLead: 9"), \
             mock.patch.object(wm, "_call_llm_api", side_effect=fake_call):
            items = wm._extract_lead_qualification("556281405459@s.whatsapp.net")
        self.assertEqual(len(items), 6)
        self.assertEqual(items[0]["label"], "Tempo do término")
        self.assertEqual(seen["payload"]["response_format"], {"type": "json_object"})
        self.assertIn("Bom tem sido dificil", seen["payload"]["messages"][0]["content"])

    def test_extract_without_key_or_history_is_empty(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertEqual(wm._extract_lead_qualification("x"), [])
        with mock.patch.object(wm, "_fetch_chat_history", return_value=""):
            self.assertEqual(wm._extract_lead_qualification("x"), [])


class PanelStoredQualificationTests(unittest.TestCase):
    def test_panel_prefers_stored_fields_over_loose_sentences(self):
        panel_dir = REPO_ROOT / "panel"
        for extra in (str(REPO_ROOT), str(panel_dir)):
            if extra not in sys.path:
                sys.path.insert(0, extra)
        spec = importlib.util.spec_from_file_location("data", panel_dir / "data.py")
        assert spec and spec.loader
        panel_data = importlib.util.module_from_spec(spec)
        sys.modules["data"] = panel_data
        spec.loader.exec_module(panel_data)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "calendar_bookings.db"
            self.assertEqual(panel_data._stored_qualification(db, ["5511999990050"]), [])
            cb.save_lead_qualification("5511999990050", ITEMS, db_path=db)
            self.assertEqual(
                panel_data._stored_qualification(db, ["111@lid", "5511999990050"]),
                ["Tempo do término: mais ou menos 1 mês", "Ansiedade (0 a 10): 9"],
            )


if __name__ == "__main__":
    unittest.main()
