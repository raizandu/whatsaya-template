from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import calendar_booking as cb  # noqa: E402

TZ = ZoneInfo("America/Sao_Paulo")


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


# 2999-01-07 é segunda; 2999-01-08 terça; 2999-01-12 sábado — datas bem no futuro
# pra nunca cair na checagem de "horário no passado" sem precisar mockar datetime.now.


def _write_token(path: Path, *, scopes=(cb.CALENDAR_SCOPE,), refresh_token: str = "rt") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": "at",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csecret",
        "scopes": list(scopes),
        "expiry": "2999-12-31T00:00:00Z",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_config(path: Path, calendar: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calendar": calendar}), encoding="utf-8")


def _event(event_id: str, start: datetime, end: datetime, summary: str, *, status: str = "confirmed") -> dict:
    return {
        "id": event_id,
        "status": status,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }


class _FakeHttpError(Exception):
    class _Resp:
        def __init__(self, status: int):
            self.status = status

    def __init__(self, status: int, message: str = "erro simulado"):
        super().__init__(message)
        self.resp = self._Resp(status)


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _FakeEventsResource:
    def __init__(self, service: "FakeService"):
        self._service = service

    def list(self, **kwargs):
        return _Call(lambda: self._service._do_list(kwargs))

    def get(self, *, calendarId, eventId):
        return _Call(lambda: self._service._do_get(calendarId, eventId))

    def insert(self, *, calendarId, body, sendUpdates=None, conferenceDataVersion=None):
        return _Call(lambda: self._service._do_insert(calendarId, body))

    def patch(self, *, calendarId, eventId, body, sendUpdates=None, conferenceDataVersion=None):
        return _Call(lambda: self._service._do_patch(calendarId, eventId, body))


class FakeService:
    """Emula o subconjunto do client googleapiclient usado por calendar_booking."""

    def __init__(
        self,
        *,
        events=None,
        freebusy_busy=None,
        calendar_id: str = "primary",
        auto_meet_link: bool = True,
        page_size: int = 250,
        simulate_race_conflict: bool = False,
    ):
        self.events_store: dict[str, dict] = {e["id"]: dict(e) for e in (events or [])}
        self._freebusy_busy = list(freebusy_busy or [])
        self._calendar_id = calendar_id
        self.auto_meet_link = auto_meet_link
        self._page_size = page_size
        self.simulate_race_conflict = simulate_race_conflict
        self._raced_ids: set[str] = set()
        self.insert_calls: list[dict] = []
        self.patch_calls: list[tuple[str, dict]] = []
        self.list_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.freebusy_calls: list[dict] = []

    def freebusy(self):
        return self

    def query(self, body):
        self.freebusy_calls.append(dict(body))
        return _Call(lambda: {"calendars": {self._calendar_id: {"busy": list(self._freebusy_busy)}}})

    def events(self):
        return _FakeEventsResource(self)

    def _do_list(self, kwargs):
        self.list_calls.append(dict(kwargs))
        ordered = sorted(
            self.events_store.values(),
            key=lambda e: (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date") or "",
        )
        token = kwargs.get("pageToken")
        start_idx = int(token) if token else 0
        page = ordered[start_idx:start_idx + self._page_size]
        response = {"items": page}
        next_idx = start_idx + self._page_size
        if next_idx < len(ordered):
            response["nextPageToken"] = str(next_idx)
        return response

    def _do_get(self, calendarId, eventId):
        self.get_calls.append(eventId)
        event = self.events_store.get(eventId)
        if event is None:
            raise _FakeHttpError(404)
        return dict(event)

    def _do_insert(self, calendarId, body):
        self.insert_calls.append(dict(body))
        event_id = str(body.get("id") or f"generated-{len(self.events_store) + 1}")
        if self.simulate_race_conflict and event_id not in self._raced_ids:
            self._raced_ids.add(event_id)
            raced = dict(body)
            raced["id"] = event_id
            raced.setdefault("status", "confirmed")
            raced["htmlLink"] = f"https://www.google.com/calendar/event?eid={event_id}"
            if self.auto_meet_link:
                raced["hangoutLink"] = f"https://meet.google.com/{event_id[:10]}"
            self.events_store[event_id] = raced
            raise _FakeHttpError(409)
        if event_id in self.events_store:
            raise _FakeHttpError(409)
        event = dict(body)
        event["id"] = event_id
        event.setdefault("status", "confirmed")
        event["htmlLink"] = f"https://www.google.com/calendar/event?eid={event_id}"
        if self.auto_meet_link:
            event["hangoutLink"] = f"https://meet.google.com/{event_id[:10]}"
        self.events_store[event_id] = event
        return dict(event)

    def _do_patch(self, calendarId, eventId, body):
        self.patch_calls.append((eventId, dict(body)))
        event = dict(self.events_store.get(eventId) or {"id": eventId, "status": "confirmed"})
        event.update(body)
        if self.auto_meet_link and not event.get("hangoutLink"):
            event["hangoutLink"] = f"https://meet.google.com/{eventId[:10]}"
        event["htmlLink"] = event.get("htmlLink") or f"https://www.google.com/calendar/event?eid={eventId}"
        self.events_store[eventId] = event
        return dict(event)


_DEFAULT_CAL = {
    "enabled": True,
    "calendar_id": "primary",
    "timezone": "America/Sao_Paulo",
    "availability_mode": "freebusy_gaps",
    "slot_keyword": "Livre",
    "block_keyword": "Bloqueada",
    "business_days": [1, 2, 3, 4, 5],
    "business_start": "08:00",
    "business_end": "18:00",
    "duration_minutes": 30,
    "min_lead_minutes": 0,
    "search_days": 14,
    "event_title": "Reunião WhatsAYA",
    "origin_label": "WhatsApp / AYA",
}


class _CalendarTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.config_path = base / "panel.config.json"
        self.token_path = base / "google_token.json"
        self.bookings_db = base / "bookings.db"
        patcher = mock.patch.dict(
            os.environ,
            {
                "WHATSAPP_PANEL_CONFIG": str(self.config_path),
                "WHATSAPP_CALENDAR_TOKEN_PATH": str(self.token_path),
                "WHATSAPP_CALENDAR_BOOKINGS_DB": str(self.bookings_db),
                "WHATSAPP_CALENDAR_MEET_WAIT_SECONDS": "0",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        _write_token(self.token_path)

    def _set_config(self, **overrides):
        payload = dict(_DEFAULT_CAL)
        payload.update(overrides)
        _write_config(self.config_path, payload)


class CalendarReadyTests(_CalendarTestCase):
    def test_disabled_even_with_valid_token(self):
        self._set_config(enabled=False)
        self.assertFalse(cb.calendar_ready())

    def test_enabled_with_scope_is_ready(self):
        self._set_config(enabled=True)
        self.assertTrue(cb.calendar_ready())

    def test_enabled_without_scope_is_not_ready(self):
        self._set_config(enabled=True)
        _write_token(self.token_path, scopes=("https://www.googleapis.com/auth/drive",))
        self.assertFalse(cb.calendar_ready())


class ValidationMessagesTests(_CalendarTestCase):
    def test_window_message_uses_config_hours(self):
        self._set_config(
            availability_mode="freebusy_gaps",
            business_start="09:00",
            business_end="22:00",
            duration_minutes=60,
        )
        start = _dt(2999, 1, 7, 8, 0)  # antes das 09:00
        end = start + timedelta(minutes=60)
        with self.assertRaises(cb.CalendarBookingError) as ctx:
            cb.create_booking(
                chat_id="5511999990000",
                start=start.isoformat(),
                end=end.isoformat(),
                service=FakeService(),
            )
        message = str(ctx.exception)
        self.assertIn("09:00", message)
        self.assertIn("22:00", message)
        self.assertNotIn("Goiânia", message)

    def test_wrong_duration_message_uses_config_value(self):
        self._set_config(duration_minutes=45)
        start = _dt(2999, 1, 7, 10, 0)
        end = start + timedelta(minutes=30)
        with self.assertRaises(cb.CalendarBookingError) as ctx:
            cb.create_booking(chat_id="c1", start=start.isoformat(), end=end.isoformat(), service=FakeService())
        self.assertIn("45", str(ctx.exception))

    def test_non_business_day_rejected(self):
        self._set_config()
        start = _dt(2999, 1, 12, 10, 0)  # sábado
        end = start + timedelta(minutes=30)
        with self.assertRaises(cb.CalendarBookingError):
            cb.create_booking(chat_id="c2", start=start.isoformat(), end=end.isoformat(), service=FakeService())


class FindSlotsFreebusyGapsTests(_CalendarTestCase):
    def test_respects_window_business_day_and_lead(self):
        self._set_config(min_lead_minutes=120)
        now = _dt(2999, 1, 7, 8, 0)  # segunda, 08:00
        result = cb.find_available_slots(
            date_from="2999-01-07",
            date_to="2999-01-07",
            now=now,
            service=FakeService(),
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [s["start"] for s in result["slots"]],
            [
                _dt(2999, 1, 7, 10, 0).isoformat(),
                _dt(2999, 1, 7, 10, 30).isoformat(),
                _dt(2999, 1, 7, 11, 0).isoformat(),
            ],
        )

    def test_period_afternoon_starts_at_noon(self):
        self._set_config()
        now = _dt(2999, 1, 7, 7, 0)
        result = cb.find_available_slots(
            date_from="2999-01-07", period="afternoon", now=now, max_slots=1, service=FakeService(),
        )
        self.assertEqual(result["slots"][0]["start"], _dt(2999, 1, 7, 12, 0).isoformat())

    def test_preferred_time_filters_and_skips_weekend(self):
        self._set_config()
        now = _dt(2999, 1, 7, 7, 0)
        result = cb.find_available_slots(
            date_from="2999-01-07",
            date_to="2999-01-12",  # segunda a sábado
            preferred_time="14:00",
            now=now,
            max_slots=3,
            service=FakeService(),
        )
        starts = [s["start"] for s in result["slots"]]
        self.assertTrue(starts)
        self.assertTrue(all(s.endswith("14:00:00-03:00") for s in starts))
        self.assertFalse(any(s.startswith("2999-01-12") for s in starts))  # sábado nunca aparece

    def test_min_lead_pushes_to_next_business_day(self):
        self._set_config(min_lead_minutes=120)
        now = _dt(2999, 1, 7, 17, 0)  # segunda 17:00; +2h = 19:00, depois do expediente
        result = cb.find_available_slots(
            date_from="2999-01-07", date_to="2999-01-08", now=now, max_slots=1, service=FakeService(),
        )
        self.assertEqual(result["slots"][0]["start"], _dt(2999, 1, 8, 8, 0).isoformat())

    def test_config_duration_generates_correct_step(self):
        self._set_config(duration_minutes=60)
        now = _dt(2999, 1, 7, 7, 0)
        result = cb.find_available_slots(date_from="2999-01-07", now=now, max_slots=3, service=FakeService())
        self.assertEqual(
            [s["start"] for s in result["slots"]],
            [
                _dt(2999, 1, 7, 8, 0).isoformat(),
                _dt(2999, 1, 7, 8, 30).isoformat(),
                _dt(2999, 1, 7, 9, 0).isoformat(),
            ],
        )
        for slot in result["slots"]:
            start = datetime.fromisoformat(slot["start"])
            end = datetime.fromisoformat(slot["end"])
            self.assertEqual((end - start).total_seconds(), 3600)

    def test_duration_mismatch_raises(self):
        self._set_config(duration_minutes=30)
        with self.assertRaises(cb.CalendarBookingError) as ctx:
            cb.find_available_slots(date_from="2999-01-07", duration_minutes=45, service=FakeService())
        self.assertIn("30", str(ctx.exception))


class FindSlotsExplicitSlotsTests(_CalendarTestCase):
    def _set_therapify_config(self, **overrides):
        payload = dict(
            availability_mode="explicit_slots",
            business_start="09:00",
            business_end="22:00",
            duration_minutes=60,
            slot_keyword="Livre",
            block_keyword="Bloqueada",
        )
        payload.update(overrides)
        self._set_config(**payload)

    def test_only_livre_events_become_vagas(self):
        self._set_therapify_config()
        events = [
            _event("vaga-1", _dt(2999, 1, 7, 14, 0), _dt(2999, 1, 7, 16, 0), "Livre"),
            _event("bloqueio-1", _dt(2999, 1, 7, 10, 0), _dt(2999, 1, 7, 11, 0), "Bloqueada"),
            _event("paciente-1", _dt(2999, 1, 7, 18, 0), _dt(2999, 1, 7, 19, 0), "Maria Souza"),
        ]
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 7, 0), max_slots=3,
            service=FakeService(events=events),
        )
        starts = [s["start"] for s in result["slots"]]
        self.assertEqual(
            starts,
            [_dt(2999, 1, 7, 14, 0).isoformat(), _dt(2999, 1, 7, 15, 0).isoformat()],
        )
        self.assertNotIn(_dt(2999, 1, 7, 10, 0).isoformat(), starts)
        self.assertNotIn(_dt(2999, 1, 7, 18, 0).isoformat(), starts)

    def test_vaga_overlapping_patient_is_not_offered(self):
        self._set_therapify_config()
        events = [
            _event("vaga-2", _dt(2999, 1, 7, 10, 0), _dt(2999, 1, 7, 11, 0), "Livre"),
            _event("paciente-2", _dt(2999, 1, 7, 10, 0), _dt(2999, 1, 7, 11, 0), "Maria Souza"),
        ]
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 7, 0), service=FakeService(events=events),
        )
        self.assertEqual(result["slots"], [])

    def test_vaga_outside_business_hours_is_offered(self):
        # Quem marca "Livre" decidiu atender ali; o expediente 09:00–22:00 não recorta a vaga.
        self._set_therapify_config()
        events = [
            _event("vaga-3a", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre"),
            _event("vaga-3b", _dt(2999, 1, 7, 23, 0), _dt(2999, 1, 8, 0, 0), "Livre"),
        ]
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 5, 0), max_slots=3, service=FakeService(events=events),
        )
        self.assertEqual(
            [s["start"] for s in result["slots"]],
            [_dt(2999, 1, 7, 8, 0).isoformat(), _dt(2999, 1, 7, 23, 0).isoformat()],
        )

    def test_vaga_under_bloqueada_is_not_offered(self):
        self._set_therapify_config()
        events = [
            _event("bloqueio-madrugada", _dt(2999, 1, 7, 0, 0), _dt(2999, 1, 7, 7, 59), "Bloqueada"),
            _event("vaga-6h", _dt(2999, 1, 7, 6, 0), _dt(2999, 1, 7, 7, 0), "Livre"),
            _event("vaga-8h", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre"),
        ]
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 3, 0), max_slots=3, service=FakeService(events=events),
        )
        self.assertEqual([s["start"] for s in result["slots"]], [_dt(2999, 1, 7, 8, 0).isoformat()])

    def test_vaga_on_weekend_is_offered(self):
        self._set_therapify_config()
        events = [_event("vaga-sab", _dt(2999, 1, 12, 10, 0), _dt(2999, 1, 12, 11, 0), "Livre")]  # sábado
        result = cb.find_available_slots(
            date_from="2999-01-12", now=_dt(2999, 1, 12, 7, 0), service=FakeService(events=events),
        )
        self.assertEqual([s["start"] for s in result["slots"]], [_dt(2999, 1, 12, 10, 0).isoformat()])

    def test_preferred_time_filters_candidates(self):
        self._set_therapify_config()
        events = [_event("vaga-4", _dt(2999, 1, 7, 14, 0), _dt(2999, 1, 7, 16, 0), "Livre")]
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 7, 0), preferred_time="15:00",
            service=FakeService(events=events),
        )
        self.assertEqual([s["start"] for s in result["slots"]], [_dt(2999, 1, 7, 15, 0).isoformat()])

    def test_max_slots_limits_results(self):
        self._set_therapify_config()
        events = [
            _event("vaga-5a", _dt(2999, 1, 7, 9, 0), _dt(2999, 1, 7, 12, 0), "Livre"),
            _event("vaga-5b", _dt(2999, 1, 8, 9, 0), _dt(2999, 1, 8, 12, 0), "Livre"),
        ]
        result = cb.find_available_slots(
            date_from="2999-01-07", date_to="2999-01-08", now=_dt(2999, 1, 7, 7, 0), max_slots=2,
            service=FakeService(events=events),
        )
        self.assertEqual(len(result["slots"]), 2)

    def test_pagination_collects_all_pages(self):
        self._set_therapify_config()
        events = [
            _event("vaga-p1", _dt(2999, 1, 7, 9, 0), _dt(2999, 1, 7, 10, 0), "Livre"),
            _event("bloqueio-p", _dt(2999, 1, 7, 11, 0), _dt(2999, 1, 7, 12, 0), "Bloqueada"),
            _event("vaga-p2", _dt(2999, 1, 7, 13, 0), _dt(2999, 1, 7, 14, 0), "Livre"),
        ]
        fake = FakeService(events=events, page_size=1)
        result = cb.find_available_slots(
            date_from="2999-01-07", now=_dt(2999, 1, 7, 7, 0), max_slots=3, service=fake,
        )
        self.assertGreater(len(fake.list_calls), 1)
        self.assertEqual(
            [s["start"] for s in result["slots"]],
            [_dt(2999, 1, 7, 9, 0).isoformat(), _dt(2999, 1, 7, 13, 0).isoformat()],
        )


class CreateBookingExplicitSlotsTests(_CalendarTestCase):
    def _set_therapify_config(self, **overrides):
        payload = dict(
            availability_mode="explicit_slots",
            business_start="09:00",
            business_end="22:00",
            duration_minutes=60,
            slot_keyword="Livre",
            block_keyword="Bloqueada",
            event_title="Sessão Therapify",
            origin_label="WhatsApp / Therapify",
        )
        payload.update(overrides)
        self._set_config(**payload)

    def test_booking_inside_vaga_creates_event(self):
        self._set_therapify_config()
        fake = FakeService(events=[_event("vaga-1", _dt(2999, 1, 7, 14, 0), _dt(2999, 1, 7, 16, 0), "Livre")])
        start = _dt(2999, 1, 7, 14, 0)
        end = _dt(2999, 1, 7, 15, 0)
        result = cb.create_booking(
            chat_id="5511999990010", start=start.isoformat(), end=end.isoformat(),
            lead_name="Ana Souza", purpose="", service=fake,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(fake.insert_calls), 1)
        body = fake.insert_calls[0]
        self.assertEqual(body["summary"], "Sessão Therapify — Ana Souza")
        self.assertIn("Origem: WhatsApp / Therapify", body["description"])
        self.assertEqual(body["extendedProperties"]["private"]["whatsayaBookingKey"], body["id"])
        self.assertTrue(result["meet_link"].startswith("https://meet.google.com/"))

    def test_booking_before_business_start_inside_vaga(self):
        self._set_therapify_config()
        fake = FakeService(events=[_event("vaga-8h", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre")])
        result = cb.create_booking(
            chat_id="5511999990012", start=_dt(2999, 1, 7, 8, 0).isoformat(),
            end=_dt(2999, 1, 7, 9, 0).isoformat(), lead_name="Tony", service=fake,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(fake.insert_calls), 1)

    def test_active_future_booking_is_moved_instead_of_duplicated(self):
        self._set_therapify_config()
        old_id = "c" + "7" * 40
        old_start, old_end = _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0)
        fake = FakeService(events=[
            _event("vaga-8h", old_start, old_end, "Livre"),
            _event("vaga-16h", _dt(2999, 1, 7, 16, 0), _dt(2999, 1, 7, 17, 0), "Livre"),
            _event(old_id, old_start, old_end, "Sessão Therapify — Tony"),
        ])
        fake.events_store[old_id]["hangoutLink"] = "https://meet.google.com/old-link-abc"
        cb._persist_booking(
            chat_id="5511999990013",
            result={
                "event_id": old_id, "start": old_start.isoformat(), "end": old_end.isoformat(),
                "timezone": "America/Sao_Paulo", "meet_link": "https://meet.google.com/old-link-abc",
                "htmlLink": "https://www.google.com/calendar/event?eid=x",
            },
            db_path=self.bookings_db,
        )
        result = cb.create_booking(
            chat_id="5511999990013", start=_dt(2999, 1, 7, 16, 0).isoformat(),
            end=_dt(2999, 1, 7, 17, 0).isoformat(), lead_name="Tony", service=fake,
        )
        self.assertEqual(result["status"], "rescheduled")
        self.assertEqual(result["meet_link"], "https://meet.google.com/old-link-abc")
        self.assertEqual(fake.insert_calls, [])
        self.assertEqual(len(fake.patch_calls), 1)
        self.assertEqual(cb.get_booking("5511999990013", db_path=self.bookings_db)["start"], _dt(2999, 1, 7, 16, 0).isoformat())

    def test_past_booking_does_not_block_new_booking(self):
        self._set_therapify_config()
        cb._persist_booking(
            chat_id="5511999990014",
            result={
                "event_id": "c" + "8" * 40, "start": "2000-01-03T08:00:00-03:00", "end": "2000-01-03T09:00:00-03:00",
                "timezone": "America/Sao_Paulo", "meet_link": "https://meet.google.com/old-link-def", "htmlLink": "",
            },
            db_path=self.bookings_db,
        )
        fake = FakeService(events=[_event("vaga-14h", _dt(2999, 1, 7, 14, 0), _dt(2999, 1, 7, 15, 0), "Livre")])
        result = cb.create_booking(
            chat_id="5511999990014", start=_dt(2999, 1, 7, 14, 0).isoformat(),
            end=_dt(2999, 1, 7, 15, 0).isoformat(), service=fake,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(fake.insert_calls), 1)

    def test_booking_is_ahead(self):
        self.assertTrue(cb.booking_is_ahead({"end": "2999-01-07T09:00:00-03:00"}))
        self.assertFalse(cb.booking_is_ahead({"end": "2000-01-07T09:00:00-03:00"}))
        self.assertFalse(cb.booking_is_ahead({"end": "não-é-data"}))
        self.assertFalse(cb.booking_is_ahead(None))

    def test_conflict_with_bloqueada_raises(self):
        self._set_therapify_config()
        fake = FakeService(events=[
            _event("vaga-2", _dt(2999, 1, 7, 10, 0), _dt(2999, 1, 7, 11, 0), "Livre"),
            _event("bloqueio-2", _dt(2999, 1, 7, 10, 0), _dt(2999, 1, 7, 11, 0), "Bloqueada"),
        ])
        start = _dt(2999, 1, 7, 10, 0)
        end = _dt(2999, 1, 7, 11, 0)
        with self.assertRaises(cb.CalendarBookingError):
            cb.create_booking(chat_id="5511999990011", start=start.isoformat(), end=end.isoformat(), service=fake)
        self.assertEqual(fake.insert_calls, [])

    def test_outside_vaga_raises(self):
        self._set_therapify_config()
        fake = FakeService(events=[])
        start = _dt(2999, 1, 7, 12, 0)
        end = _dt(2999, 1, 7, 13, 0)
        with self.assertRaises(cb.CalendarBookingError) as ctx:
            cb.create_booking(chat_id="5511999990012", start=start.isoformat(), end=end.isoformat(), service=fake)
        self.assertIn("Livre", str(ctx.exception))
        self.assertEqual(fake.insert_calls, [])

    def test_retry_same_window_is_idempotent(self):
        self._set_therapify_config()
        fake = FakeService(events=[_event("vaga-3", _dt(2999, 1, 7, 14, 0), _dt(2999, 1, 7, 16, 0), "Livre")])
        start = _dt(2999, 1, 7, 14, 0)
        end = _dt(2999, 1, 7, 15, 0)
        first = cb.create_booking(
            chat_id="5511999990013", start=start.isoformat(), end=end.isoformat(), service=fake,
        )
        second = cb.create_booking(
            chat_id="5511999990013", start=start.isoformat(), end=end.isoformat(), service=fake,
        )
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "already_exists")
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(len(fake.insert_calls), 1)


class MeetingOutcomeMirrorTests(_CalendarTestCase):
    def _therapify(self):
        self._set_config(
            availability_mode="explicit_slots", business_start="09:00", business_end="22:00",
            duration_minutes=60, slot_keyword="Livre", block_keyword="Bloqueada",
            event_title="Sessão Therapify",
        )

    def test_outcome_event_patch_colors(self):
        self.assertEqual(cb.outcome_event_patch("attended", "Sessão — Ana")["colorId"], "10")
        self.assertEqual(cb.outcome_event_patch("no_show", "Sessão — Ana")["colorId"], "11")
        self.assertEqual(cb.outcome_event_patch("rescheduled", "Sessão — Ana")["colorId"], "5")
        cancelled = cb.outcome_event_patch("cancelled", "Sessão — Ana")
        self.assertEqual(cancelled["colorId"], "11")
        self.assertEqual(cancelled["transparency"], "transparent")
        self.assertEqual(cancelled["summary"], "[Cancelada] Sessão — Ana")
        self.assertEqual(cancelled["extendedProperties"]["private"][cb.OUTCOME_PROPERTY], "cancelled")
        # Voltar para comparecida tira o prefixo e volta a ocupar o horário.
        back = cb.outcome_event_patch("attended", "[Cancelada] Sessão — Ana")
        self.assertEqual(back["summary"], "Sessão — Ana")
        self.assertEqual(back["transparency"], "opaque")
        with self.assertRaises(cb.CalendarBookingError):
            cb.outcome_event_patch("whatever")

    def test_transparent_livre_is_not_released(self):
        # O dono cria "Livre" como disponível (transparent) no Google; isso não é cancelamento.
        livre = dict(_event("livre", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre"), transparency="transparent")
        self.assertFalse(cb.event_is_released(livre))
        bot = dict(_event("s", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Sessão"), transparency="transparent",
                   extendedProperties={"private": {"whatsayaBookingKey": "s"}})
        self.assertTrue(cb.event_is_released(bot))
        self._therapify()
        slots = cb.find_available_slots(date_from="2999-01-07", now=_dt(2999, 1, 7, 5, 0), service=FakeService(events=[livre]))
        self.assertEqual([s["start"] for s in slots["slots"]], [_dt(2999, 1, 7, 8, 0).isoformat()])

    def test_cancelled_releases_slot_and_active_booking(self):
        self._therapify()
        fake = FakeService(events=[_event("vaga-8h", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre")])
        created = cb.create_booking(
            chat_id="5511999990020", start=_dt(2999, 1, 7, 8, 0).isoformat(),
            end=_dt(2999, 1, 7, 9, 0).isoformat(), lead_name="Ana", service=fake,
        )
        busy_now = cb.find_available_slots(date_from="2999-01-07", now=_dt(2999, 1, 7, 5, 0), service=fake)
        self.assertEqual(busy_now["slots"], [])
        meeting = cb.set_booking_outcome(
            event_id=created["event_id"], start=created["start"], outcome="cancelled", db_path=self.bookings_db,
        )
        self.assertEqual(meeting["outcome"], "cancelled")
        self.assertIsNone(cb.get_booking("5511999990020", db_path=self.bookings_db))
        # O painel espelha o status no Google; o evento continua lá, vermelho e liberado.
        fake.events_store[created["event_id"]].update(cb.outcome_event_patch("cancelled", created["summary"]))
        freed = cb.find_available_slots(date_from="2999-01-07", now=_dt(2999, 1, 7, 5, 0), service=fake)
        self.assertEqual([s["start"] for s in freed["slots"]], [_dt(2999, 1, 7, 8, 0).isoformat()])
        summary = cb.meeting_outcome_summary([meeting])
        self.assertEqual(summary["cancelled"], 1)
        self.assertIsNone(summary["attendance_rate"])

    def test_reschedule_paints_event_yellow_and_keeps_booking_key(self):
        self._therapify()
        old_id = "c" + "9" * 40
        fake = FakeService(events=[
            _event("vaga-a", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Livre"),
            _event("vaga-b", _dt(2999, 1, 7, 16, 0), _dt(2999, 1, 7, 17, 0), "Livre"),
            _event(old_id, _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 9, 0), "Sessão Therapify — Ana"),
        ])
        fake.events_store[old_id]["hangoutLink"] = "https://meet.google.com/aaa-bbbb-ccc"
        cb._persist_booking(chat_id="5511999990021", result={
            "event_id": old_id, "start": _dt(2999, 1, 7, 8, 0).isoformat(), "end": _dt(2999, 1, 7, 9, 0).isoformat(),
            "timezone": "America/Sao_Paulo", "meet_link": "https://meet.google.com/aaa-bbbb-ccc", "htmlLink": "",
        }, db_path=self.bookings_db)
        cb.reschedule_booking(
            chat_id="5511999990021", start=_dt(2999, 1, 7, 16, 0).isoformat(),
            end=_dt(2999, 1, 7, 17, 0).isoformat(), service=fake,
        )
        body = fake.patch_calls[0][1]
        self.assertEqual(body["colorId"], "5")
        self.assertEqual(body["extendedProperties"]["private"]["whatsayaBookingKey"], old_id)
        self.assertEqual(body["extendedProperties"]["private"][cb.OUTCOME_PROPERTY], "rescheduled")

    def test_old_store_without_cancelled_is_migrated(self):
        self._therapify()
        import sqlite3
        self.bookings_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.bookings_db)
        conn.execute("""CREATE TABLE current_bookings (chat_key TEXT PRIMARY KEY, event_id TEXT NOT NULL,
            start TEXT NOT NULL, end TEXT NOT NULL, timezone TEXT NOT NULL, meet_link TEXT NOT NULL,
            html_link TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        conn.execute("""CREATE TABLE booking_occurrences (id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key TEXT NOT NULL, event_id TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
            start TEXT NOT NULL, end TEXT NOT NULL, timezone TEXT NOT NULL,
            meet_link TEXT NOT NULL DEFAULT '', html_link TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL DEFAULT 'no_status'
                CHECK(outcome IN ('no_status', 'attended', 'no_show', 'rescheduled')),
            outcome_source TEXT NOT NULL DEFAULT '', outcome_updated_at REAL,
            rescheduled_to_start TEXT NOT NULL DEFAULT '', rescheduled_to_end TEXT NOT NULL DEFAULT '',
            followup_due_at REAL, followup_sent_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(event_id, start))""")
        conn.execute("""INSERT INTO booking_occurrences (chat_key, event_id, summary, start, end, timezone,
            outcome, created_at, updated_at) VALUES ('k1', 'ev1', 'Sessão', '2999-01-07T08:00:00-03:00',
            '2999-01-07T09:00:00-03:00', 'America/Sao_Paulo', 'attended', 1, 1)""")
        conn.commit(); conn.close()
        meeting = cb.set_booking_outcome(
            event_id="ev1", start="2999-01-07T08:00:00-03:00", outcome="cancelled", db_path=self.bookings_db,
        )
        self.assertEqual(meeting["outcome"], "cancelled")
        self.assertEqual(meeting["summary"], "Sessão")


class DayScheduleTests(_CalendarTestCase):
    def setUp(self):
        super().setUp()
        self._set_config(
            availability_mode="explicit_slots", business_start="09:00", business_end="22:00",
            duration_minutes=60, slot_keyword="Livre", block_keyword="Bloqueada", event_title="Sessão Therapify",
        )

    def test_display_name_uses_first_name_only(self):
        self.assertEqual(cb.display_name_from_summary("Lucas Ferreira Monteiro"), "Lucas")
        self.assertEqual(cb.display_name_from_summary("Consulta Almir Mendes Vida"), "Almir")
        self.assertEqual(cb.display_name_from_summary("Sessão Therapify — Ana Souza", "Sessão Therapify"), "Ana")
        self.assertEqual(cb.display_name_from_summary("Gustavo Oliveira Premium 4W"), "Gustavo")
        self.assertEqual(cb.display_name_from_summary("Ana Souza", name_format="full"), "Ana Souza")
        self.assertEqual(cb.display_name_from_summary("8W"), "")

    def test_day_schedule_merges_livre_sessions_and_patients(self):
        # 2999-01-07 é segunda; 2999-01-08 terça; 2999-01-10 quinta.
        d = lambda h, m=0, day=7: _dt(2999, 1, day, h, m)
        session_id = "c" + "3" * 40
        events = [
            _event("bloq", d(0), _dt(2999, 1, 7, 7, 59), "Bloqueada"),
            _event("livre-8", d(8), d(9), "Livre"),
            _event(session_id, d(8), d(9), "Sessão Therapify — Tony Anthony"),
            _event("pac-10", d(10), d(11), "Gustavo Oliveira Premium 4W"),
            _event("livre-11", d(11), d(13), "Livre"),
            _event("pac-13", d(13), d(14), "Consulta Almir Mendes"),
            _event("cancel", d(16), d(17), "[Cancelada] Sessão Therapify — Bia"),
            _event("livre-16", d(16), d(17), "Livre"),
            _event("livre-amanha", d(9, day=8), d(10, day=8), "Livre"),
            _event("livre-sab", d(9, day=10), d(10, day=10), "Livre"),
            _event("dentista", d(17), d(18), "Dentista Dr. Paulo"),
            dict(_event("privado", d(18), d(19), "Maria Souza"), visibility="private"),
        ]
        events[6].update(cb.outcome_event_patch("cancelled", events[6]["summary"]))
        days = cb.day_schedule(2, now=d(7, 30), service=FakeService(events=events), private_words=("dentista",))
        self.assertEqual([day["date"].isoformat() for day in days], ["2999-01-07", "2999-01-08"])
        first = [(s["start"].strftime("%H:%M"), s["status"], s["name"]) for s in days[0]["slots"]]
        self.assertEqual(first, [
            ("08:00", "occupied", "Tony"),
            ("10:00", "occupied", "Gustavo"),
            ("11:00", "free", ""),
            ("12:00", "free", ""),
            ("13:00", "occupied", "Almir"),
            ("16:00", "free", ""),
            ("17:00", "occupied", ""),
            ("18:00", "occupied", ""),
        ])
        self.assertEqual([(s["start"].strftime("%H:%M"), s["status"]) for s in days[1]["slots"]], [("09:00", "free")])

    def test_day_schedule_respects_min_lead(self):
        self._set_config(availability_mode="explicit_slots", duration_minutes=60, min_lead_minutes=120,
                         slot_keyword="Livre", block_keyword="Bloqueada")
        events = [_event("livre", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 12, 0), "Livre")]
        days = cb.day_schedule(1, now=_dt(2999, 1, 7, 7, 30), service=FakeService(events=events))
        self.assertEqual([s["start"].strftime("%H:%M") for s in days[0]["slots"]], ["10:00", "11:00"])

    def test_day_schedule_skips_past_hours(self):
        events = [_event("livre", _dt(2999, 1, 7, 8, 0), _dt(2999, 1, 7, 12, 0), "Livre")]
        days = cb.day_schedule(1, now=_dt(2999, 1, 7, 9, 30), service=FakeService(events=events))
        self.assertEqual([s["start"].strftime("%H:%M") for s in days[0]["slots"]], ["10:00", "11:00"])


class CreateBookingFreebusyGapsTests(_CalendarTestCase):
    def test_creates_when_free(self):
        self._set_config()
        start = _dt(2999, 1, 7, 10, 0)
        end = start + timedelta(minutes=30)
        fake = FakeService()
        result = cb.create_booking(
            chat_id="5511999991000", start=start.isoformat(), end=end.isoformat(), service=fake,
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(fake.insert_calls), 1)

    def test_freebusy_conflict_without_own_event_raises(self):
        self._set_config()
        start = _dt(2999, 1, 7, 10, 0)
        end = start + timedelta(minutes=30)
        fake = FakeService(freebusy_busy=[{"start": start.isoformat(), "end": end.isoformat()}])
        with self.assertRaises(cb.CalendarBookingError):
            cb.create_booking(chat_id="5511999991001", start=start.isoformat(), end=end.isoformat(), service=fake)
        self.assertEqual(fake.insert_calls, [])

    def test_409_on_insert_resolves_via_existing_event(self):
        self._set_config()
        start = _dt(2999, 1, 7, 10, 0)
        end = start + timedelta(minutes=30)
        fake = FakeService(simulate_race_conflict=True)
        result = cb.create_booking(
            chat_id="5511999991002", start=start.isoformat(), end=end.isoformat(), service=fake,
        )
        self.assertEqual(result["status"], "already_exists")
        self.assertEqual(len(fake.insert_calls), 1)


class RescheduleBookingTests(_CalendarTestCase):
    def _seed_current_booking(self, chat_id, event_id, start, end, meet_link):
        cb._persist_booking(
            chat_id=chat_id,
            result={
                "event_id": event_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timezone": "America/Sao_Paulo",
                "meet_link": meet_link,
                "htmlLink": f"https://www.google.com/calendar/event?eid={event_id}",
            },
            db_path=self.bookings_db,
        )

    def test_reschedule_keeps_meet_link_and_does_not_duplicate(self):
        self._set_config()
        event_id = "c" + "0" * 40
        old_start = _dt(2999, 1, 7, 10, 0)
        old_end = old_start + timedelta(minutes=30)
        meet_link = "https://meet.google.com/abc-defg-hij"
        self._seed_current_booking("5511999992000", event_id, old_start, old_end, meet_link)
        fake = FakeService(events=[_event(event_id, old_start, old_end, "Reunião WhatsAYA — Lead")])
        fake.events_store[event_id]["hangoutLink"] = meet_link
        new_start = old_start + timedelta(hours=1)
        new_end = old_end + timedelta(hours=1)
        result = cb.reschedule_booking(
            chat_id="5511999992000", start=new_start.isoformat(), end=new_end.isoformat(), service=fake,
        )
        self.assertEqual(result["status"], "rescheduled")
        self.assertEqual(result["meet_link"], meet_link)
        self.assertEqual(len(fake.patch_calls), 1)
        self.assertNotIn("conferenceData", fake.patch_calls[0][1])
        self.assertEqual(fake.insert_calls, [])

    def test_reschedule_conflict_raises(self):
        self._set_config()
        event_id = "c" + "1" * 40
        old_start = _dt(2999, 1, 7, 10, 0)
        old_end = old_start + timedelta(minutes=30)
        meet_link = "https://meet.google.com/xyz-defg-hij"
        self._seed_current_booking("5511999992001", event_id, old_start, old_end, meet_link)
        new_start = old_start + timedelta(hours=2)
        new_end = old_end + timedelta(hours=2)
        fake = FakeService(
            events=[_event(event_id, old_start, old_end, "Reunião WhatsAYA — Lead")],
            freebusy_busy=[{"start": new_start.isoformat(), "end": new_end.isoformat()}],
        )
        fake.events_store[event_id]["hangoutLink"] = meet_link
        with self.assertRaises(cb.CalendarBookingError):
            cb.reschedule_booking(
                chat_id="5511999992001", start=new_start.isoformat(), end=new_end.isoformat(), service=fake,
            )

    def test_reschedule_ignores_own_event_on_partial_overlap_explicit_slots(self):
        self._set_config(
            availability_mode="explicit_slots",
            business_start="09:00",
            business_end="22:00",
            duration_minutes=60,
            slot_keyword="Livre",
            block_keyword="Bloqueada",
        )
        event_id = "c" + "2" * 40
        old_start = _dt(2999, 1, 7, 14, 0)
        old_end = old_start + timedelta(minutes=60)
        meet_link = "https://meet.google.com/aaa-bbbb-ccc"
        self._seed_current_booking("5511999992002", event_id, old_start, old_end, meet_link)
        new_start = old_start + timedelta(minutes=30)  # se sobrepõe parcialmente à janela antiga
        new_end = old_end + timedelta(minutes=30)
        fake = FakeService(events=[_event(event_id, old_start, old_end, "Sessão Therapify — Lead")])
        fake.events_store[event_id]["hangoutLink"] = meet_link
        result = cb.reschedule_booking(
            chat_id="5511999992002", start=new_start.isoformat(), end=new_end.isoformat(), service=fake,
        )
        self.assertEqual(result["status"], "rescheduled")
        self.assertEqual(len(fake.patch_calls), 1)


if __name__ == "__main__":
    unittest.main()
