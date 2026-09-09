from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import calendar_config as cc  # noqa: E402


class NormalizeCalendarConfigTests(unittest.TestCase):
    def test_missing_raw_returns_defaults(self):
        cfg = cc.normalize_calendar_config(None)
        self.assertEqual(cfg, cc.CalendarConfig())

    def test_invalid_values_fall_back_to_default(self):
        raw = {
            "enabled": "sim",
            "calendar_id": 123,
            "timezone": "Nao/Existe",
            "availability_mode": "outro_modo",
            "slot_keyword": "",
            "block_keyword": "x" * 41,
            "business_days": [8, 9],
            "business_start": "8h",
            "business_end": "18:00",
            "duration_minutes": 17,
            "min_lead_minutes": -1,
            "search_days": 999,
            "event_title": "a" * 81,
        }
        cfg = cc.normalize_calendar_config(raw)
        self.assertEqual(cfg, cc.CalendarConfig())

    def test_valid_values_are_kept(self):
        raw = {
            "enabled": False,
            "calendar_id": "time@group.calendar.google.com",
            "timezone": "UTC",
            "availability_mode": "explicit_slots",
            "slot_keyword": "Vago",
            "block_keyword": "Fechado",
            "business_days": [7, 1, 3],
            "business_start": "09:00",
            "business_end": "17:30",
            "duration_minutes": 45,
            "min_lead_minutes": 60,
            "search_days": 7,
            "event_title": "Consulta",
        }
        cfg = cc.normalize_calendar_config(raw)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.calendar_id, "time@group.calendar.google.com")
        self.assertEqual(cfg.timezone, "UTC")
        self.assertEqual(cfg.availability_mode, "explicit_slots")
        self.assertEqual(cfg.business_days, (1, 3, 7))
        self.assertEqual(cfg.duration_minutes, 45)

    def test_legacy_env_fallback_used_when_key_absent(self):
        env = {
            "WHATSAPP_CALENDAR_ID": "legacy@group.calendar.google.com",
            "WHATSAPP_CALENDAR_TZ": "America/Bahia",
            "WHATSAPP_CALENDAR_MIN_LEAD_MINUTES": "45",
        }
        cfg = cc.normalize_calendar_config({}, env=env)
        self.assertEqual(cfg.calendar_id, "legacy@group.calendar.google.com")
        self.assertEqual(cfg.timezone, "America/Bahia")
        self.assertEqual(cfg.min_lead_minutes, 45)

    def test_invalid_env_fallback_uses_default(self):
        env = {
            "WHATSAPP_CALENDAR_TZ": "Nao/Existe",
            "WHATSAPP_CALENDAR_MIN_LEAD_MINUTES": "nao-e-numero",
        }
        cfg = cc.normalize_calendar_config({}, env=env)
        self.assertEqual(cfg.timezone, cc.CalendarConfig().timezone)
        self.assertEqual(cfg.min_lead_minutes, cc.CalendarConfig().min_lead_minutes)

    def test_file_value_wins_over_env_var(self):
        env = {"WHATSAPP_CALENDAR_ID": "from-env@group.calendar.google.com"}
        cfg = cc.normalize_calendar_config({"calendar_id": "from-file"}, env=env)
        self.assertEqual(cfg.calendar_id, "from-file")

    def test_invalid_file_value_does_not_fall_back_to_env(self):
        # a chave está presente no raw (mesmo que inválida) -> não é "ausente",
        # então não cai pro fallback de env; vai direto pro default.
        env = {"WHATSAPP_CALENDAR_ID": "from-env@group.calendar.google.com"}
        cfg = cc.normalize_calendar_config({"calendar_id": ""}, env=env)
        self.assertEqual(cfg.calendar_id, cc.CalendarConfig().calendar_id)

    def test_duplicate_keywords_fall_back_to_defaults(self):
        cfg = cc.normalize_calendar_config({"slot_keyword": "livre", "block_keyword": "LIVRE"})
        self.assertEqual(cfg.slot_keyword, cc.CalendarConfig().slot_keyword)
        self.assertEqual(cfg.block_keyword, cc.CalendarConfig().block_keyword)

    def test_business_hours_out_of_order_falls_back_to_defaults(self):
        cfg = cc.normalize_calendar_config({"business_start": "18:00", "business_end": "08:00"})
        self.assertEqual(cfg.business_start, cc.CalendarConfig().business_start)
        self.assertEqual(cfg.business_end, cc.CalendarConfig().business_end)

    def test_origin_label_read_from_raw(self):
        cfg = cc.normalize_calendar_config({"origin_label": "Campanha X"})
        self.assertEqual(cfg.origin_label, "Campanha X")


class CalendarConfigMethodsTests(unittest.TestCase):
    def test_tz_open_close_and_business_day(self):
        cfg = cc.CalendarConfig()
        self.assertEqual(str(cfg.tz()), "America/Sao_Paulo")
        self.assertEqual(cfg.open_time().isoformat(), "08:00:00")
        self.assertEqual(cfg.close_time().isoformat(), "18:00:00")

        import datetime

        monday = datetime.date(2026, 9, 7)
        sunday = datetime.date(2026, 9, 6)
        self.assertTrue(cfg.is_business_day(monday))
        self.assertFalse(cfg.is_business_day(sunday))

    def test_to_public_dict_is_json_safe(self):
        cfg = cc.CalendarConfig()
        data = cfg.to_public_dict()
        self.assertIsInstance(data["business_days"], list)
        json.dumps(data)  # não pode levantar


class LoadCalendarConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "panel.config.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_returns_defaults(self):
        cfg = cc.load_calendar_config(path=self.path)
        self.assertEqual(cfg, cc.CalendarConfig())

    def test_invalid_json_returns_defaults(self):
        self.path.write_text("{nao e json", encoding="utf-8")
        cfg = cc.load_calendar_config(path=self.path)
        self.assertEqual(cfg, cc.CalendarConfig())

    def test_reads_calendar_section(self):
        self.path.write_text(
            json.dumps({"brand": "X", "calendar": {"duration_minutes": 45}}),
            encoding="utf-8",
        )
        cfg = cc.load_calendar_config(path=self.path)
        self.assertEqual(cfg.duration_minutes, 45)

    def test_cache_invalidates_when_file_changes(self):
        self.path.write_text(json.dumps({"calendar": {"duration_minutes": 45}}), encoding="utf-8")
        first = cc.load_calendar_config(path=self.path)
        self.assertEqual(first.duration_minutes, 45)

        cached_again = cc.load_calendar_config(path=self.path)
        self.assertEqual(cached_again.duration_minutes, 45)

        time.sleep(0.01)
        self.path.write_text(json.dumps({"calendar": {"duration_minutes": 60}}), encoding="utf-8")
        os.utime(self.path, None)
        second = cc.load_calendar_config(path=self.path)
        self.assertEqual(second.duration_minutes, 60)


class ValidateCalendarSettingsTests(unittest.TestCase):
    def test_rejects_unknown_key(self):
        with self.assertRaises(cc.CalendarConfigError):
            cc.validate_calendar_settings({"nao_existe": 1})

    def test_missing_fields_get_calendar_config_defaults(self):
        out = cc.validate_calendar_settings({"duration_minutes": 45})
        defaults = cc.CalendarConfig()
        self.assertEqual(set(out), set(cc.EDITABLE_FIELDS))
        self.assertEqual(out["duration_minutes"], 45)
        self.assertEqual(out["calendar_id"], defaults.calendar_id)
        self.assertEqual(out["timezone"], defaults.timezone)
        self.assertEqual(out["business_days"], list(defaults.business_days))

    def test_enabled_must_be_bool(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "enabled precisa ser true ou false"):
            cc.validate_calendar_settings({"enabled": "sim"})

    def test_calendar_id_rejects_spaces(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "calendar_id inválido"):
            cc.validate_calendar_settings({"calendar_id": "com espaco"})

    def test_calendar_id_rejects_too_long(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "calendar_id inválido"):
            cc.validate_calendar_settings({"calendar_id": "a" * 201})

    def test_timezone_must_be_valid(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "Fuso horário inválido"):
            cc.validate_calendar_settings({"timezone": "Nao/Existe"})

    def test_availability_mode_must_be_known(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "availability_mode precisa ser"):
            cc.validate_calendar_settings({"availability_mode": "outro"})

    def test_slot_keyword_length(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "slot_keyword precisa ter"):
            cc.validate_calendar_settings({"slot_keyword": ""})

    def test_block_keyword_length(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "block_keyword precisa ter"):
            cc.validate_calendar_settings({"block_keyword": "x" * 41})

    def test_slot_and_block_keyword_must_differ(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "não podem ser iguais"):
            cc.validate_calendar_settings({"slot_keyword": "Livre", "block_keyword": "livre"})

    def test_business_days_rejects_empty(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_days precisa ser"):
            cc.validate_calendar_settings({"business_days": []})

    def test_business_days_rejects_out_of_range(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_days precisa ser"):
            cc.validate_calendar_settings({"business_days": [0, 8]})

    def test_business_days_rejects_duplicates(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_days precisa ser"):
            cc.validate_calendar_settings({"business_days": [1, 1, 2]})

    def test_business_days_sorted_when_valid(self):
        out = cc.validate_calendar_settings({"business_days": [5, 1, 3]})
        self.assertEqual(out["business_days"], [1, 3, 5])

    def test_business_start_format(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_start precisa estar no formato"):
            cc.validate_calendar_settings({"business_start": "8:00"})

    def test_business_end_format(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_end precisa estar no formato"):
            cc.validate_calendar_settings({"business_end": "25:00"})

    def test_business_start_must_be_before_end(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "business_start precisa ser antes"):
            cc.validate_calendar_settings({"business_start": "18:00", "business_end": "08:00"})

    def test_duration_minutes_range(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "duration_minutes precisa ser"):
            cc.validate_calendar_settings({"duration_minutes": 10})

    def test_duration_minutes_must_be_multiple_of_5(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "duration_minutes precisa ser"):
            cc.validate_calendar_settings({"duration_minutes": 32})

    def test_min_lead_minutes_range(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "min_lead_minutes precisa ser"):
            cc.validate_calendar_settings({"min_lead_minutes": 10081})

    def test_search_days_range(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "search_days precisa ser"):
            cc.validate_calendar_settings({"search_days": 0})

    def test_event_title_length(self):
        with self.assertRaisesRegex(cc.CalendarConfigError, "event_title precisa ter"):
            cc.validate_calendar_settings({"event_title": "a" * 81})


class SaveCalendarSettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "panel.config.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_file_with_mode_0600_when_missing(self):
        cfg = cc.save_calendar_settings({"duration_minutes": 45}, path=self.path)
        self.assertEqual(cfg.duration_minutes, 45)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["calendar"]["duration_minutes"], 45)

    def test_preserves_other_top_level_and_calendar_keys(self):
        self.path.write_text(
            json.dumps(
                {
                    "brand": "AYA.Clínicas",
                    "pipeline": "therapify",
                    "calendar": {
                        "origin_label": "Campanha Y",
                        "duration_minutes": 30,
                    },
                }
            ),
            encoding="utf-8",
        )
        cfg = cc.save_calendar_settings({"duration_minutes": 60}, path=self.path)
        self.assertEqual(cfg.duration_minutes, 60)
        self.assertEqual(cfg.origin_label, "Campanha Y")

        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["brand"], "AYA.Clínicas")
        self.assertEqual(data["pipeline"], "therapify")
        self.assertEqual(data["calendar"]["origin_label"], "Campanha Y")
        self.assertEqual(data["calendar"]["duration_minutes"], 60)

    def test_rejects_invalid_settings_without_touching_file(self):
        self.path.write_text(json.dumps({"calendar": {"duration_minutes": 30}}), encoding="utf-8")
        with self.assertRaises(cc.CalendarConfigError):
            cc.save_calendar_settings({"duration_minutes": 999}, path=self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["calendar"]["duration_minutes"], 30)

    def test_atomic_write_leaves_no_tmp_file(self):
        cc.save_calendar_settings({"duration_minutes": 45}, path=self.path)
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])


class AtomicWriteJsonTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "arquivo.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_file_uses_requested_mode(self):
        cc.atomic_write_json(self.path, {"a": 1}, mode=0o640)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"a": 1})

    def test_preserves_mode_of_existing_file(self):
        self.path.write_text("{}", encoding="utf-8")
        os.chmod(self.path, 0o644)
        cc.atomic_write_json(self.path, {"a": 2})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"a": 2})

    def test_no_leftover_tmp_file(self):
        cc.atomic_write_json(self.path, {"a": 1})
        cc.atomic_write_json(self.path, {"a": 2})
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
