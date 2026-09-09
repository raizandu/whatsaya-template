from __future__ import annotations

import json
import sys
import unittest
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calendar_config import CalendarConfig  # noqa: E402

import calendar_service as cs  # noqa: E402


def _future_expiry(seconds=3600):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_expiry(seconds=3600):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class FakeHttp:
    """Substitui a rede: devolve (status, body) ou levanta a exceção enfileirada."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, req: urllib.request.Request, timeout: float):
        self.requests.append(req)
        if not self._responses:
            raise AssertionError("FakeHttp sem respostas suficientes na fila")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _json_response(status: int, payload: dict) -> tuple[int, bytes]:
    return status, json.dumps(payload).encode("utf-8")


def make_config(**overrides) -> CalendarConfig:
    return CalendarConfig(**overrides)


class TokenHasCalendarScopeTests(unittest.TestCase):
    def test_scopes_as_list(self):
        payload = {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]}
        self.assertTrue(cs.token_has_calendar_scope(payload))

    def test_scopes_as_string(self):
        payload = {"refresh_token": "r1", "scope": f"openid {cs.CALENDAR_EVENTS_SCOPE}"}
        self.assertTrue(cs.token_has_calendar_scope(payload))

    def test_missing_refresh_token(self):
        payload = {"scopes": [cs.CALENDAR_SCOPE]}
        self.assertFalse(cs.token_has_calendar_scope(payload))

    def test_wrong_scope(self):
        payload = {"refresh_token": "r1", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}
        self.assertFalse(cs.token_has_calendar_scope(payload))


class TokenStoreLoadReadyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"

    def test_load_missing_file(self):
        store = cs.TokenStore(self.path)
        self.assertEqual(store.load(), {})

    def test_load_invalid_json(self):
        self.path.write_text("{ isso nao é json", encoding="utf-8")
        store = cs.TokenStore(self.path)
        self.assertEqual(store.load(), {})

    def test_ready_true_with_list_scopes(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})
        store = cs.TokenStore(self.path)
        self.assertTrue(store.ready())

    def test_ready_true_with_string_scope(self):
        _write_json(self.path, {"refresh_token": "r1", "scope": cs.CALENDAR_EVENTS_SCOPE})
        store = cs.TokenStore(self.path)
        self.assertTrue(store.ready())

    def test_ready_false_without_scope(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": []})
        store = cs.TokenStore(self.path)
        self.assertFalse(store.ready())


class TokenStoreAccessTokenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"

    def test_valid_cached_token_skips_http(self):
        _write_json(
            self.path,
            {
                "token": "cached-token",
                "refresh_token": "r1",
                "client_id": "cid",
                "client_secret": "csecret",
                "expiry": _future_expiry(),
                "scopes": [cs.CALENDAR_SCOPE],
            },
        )
        http = FakeHttp([])
        store = cs.TokenStore(self.path, http=http)
        self.assertEqual(store.access_token(), "cached-token")
        self.assertEqual(http.requests, [])

    def test_refresh_when_expired_posts_grant_type_and_persists(self):
        _write_json(
            self.path,
            {
                "token": "old-token",
                "refresh_token": "r1",
                "client_id": "cid",
                "client_secret": "csecret",
                "expiry": _past_expiry(),
                "scopes": [cs.CALENDAR_SCOPE],
                "account": "rodrigo@example.com",
            },
        )
        http = FakeHttp([_json_response(200, {"access_token": "new-token", "expires_in": 3600})])
        self.assertFalse(hasattr(cs, "logging"), "calendar_service não deve importar logging")
        store = cs.TokenStore(self.path, http=http)
        token = store.access_token()
        self.assertEqual(token, "new-token")

        self.assertEqual(len(http.requests), 1)
        body = http.requests[0].data.decode("utf-8")
        parsed_body = urllib.parse.parse_qs(body)
        self.assertEqual(parsed_body["grant_type"], ["refresh_token"])
        self.assertEqual(parsed_body["refresh_token"], ["r1"])

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["token"], "new-token")
        self.assertIn("expiry", saved)
        self.assertEqual(saved["refresh_token"], "r1")
        self.assertEqual(saved["client_id"], "cid")
        self.assertEqual(saved["client_secret"], "csecret")
        self.assertEqual(saved["account"], "rodrigo@example.com")

    def test_no_cached_token_forces_refresh(self):
        _write_json(
            self.path,
            {"refresh_token": "r1", "client_id": "cid", "client_secret": "csecret"},
        )
        http = FakeHttp([_json_response(200, {"access_token": "brand-new", "expires_in": 1800})])
        store = cs.TokenStore(self.path, http=http)
        self.assertEqual(store.access_token(), "brand-new")

    def test_invalid_grant_raises_token_expired(self):
        _write_json(
            self.path,
            {
                "refresh_token": "r1",
                "client_id": "cid",
                "client_secret": "csecret",
                "expiry": _past_expiry(),
                "token": "old",
            },
        )
        http = FakeHttp([_json_response(400, {"error": "invalid_grant"})])
        store = cs.TokenStore(self.path, http=http)
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            store.access_token()
        self.assertEqual(ctx.exception.code, "token_expired")

    def test_timeout_raises_unavailable(self):
        _write_json(
            self.path,
            {"refresh_token": "r1", "client_id": "cid", "client_secret": "csecret"},
        )
        http = FakeHttp([TimeoutError("timed out")])
        store = cs.TokenStore(self.path, http=http)
        with self.assertRaises(cs.CalendarServiceError) as ctx:
            store.access_token()
        self.assertEqual(ctx.exception.code, "unavailable")

    def test_no_refresh_token_raises_not_configured(self):
        _write_json(self.path, {})
        store = cs.TokenStore(self.path, http=FakeHttp([]))
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            store.access_token()
        self.assertEqual(ctx.exception.code, "not_configured")


class TokenStoreSaveAuthorizedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"

    def test_normalizes_google_auth_format(self):
        store = cs.TokenStore(self.path, http=FakeHttp([]))
        response = {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "scope": f"{cs.CALENDAR_SCOPE} openid",
            "expires_in": 3600,
        }
        saved = store.save_authorized(response, client_id="cid", client_secret="csecret", account="a@b.com")

        expected_keys = {
            "token", "refresh_token", "token_uri", "client_id", "client_secret",
            "scopes", "expiry", "universe_domain", "account",
        }
        self.assertEqual(set(saved.keys()), expected_keys)
        self.assertEqual(saved["token"], "at-1")
        self.assertEqual(saved["refresh_token"], "rt-1")
        self.assertEqual(saved["token_uri"], cs.DEFAULT_TOKEN_URI)
        self.assertIsInstance(saved["scopes"], list)
        self.assertIn(cs.CALENDAR_SCOPE, saved["scopes"])
        self.assertTrue(saved["expiry"].endswith("Z"))
        self.assertEqual(saved["universe_domain"], "googleapis.com")
        self.assertEqual(saved["account"], "a@b.com")

        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, saved)

    def test_keeps_old_refresh_token_when_response_omits_it(self):
        _write_json(self.path, {"refresh_token": "old-refresh", "token": "old-token"})
        store = cs.TokenStore(self.path, http=FakeHttp([]))
        response = {"access_token": "at-2", "expires_in": 3600}
        saved = store.save_authorized(response, client_id="cid", client_secret="csecret")
        self.assertEqual(saved["refresh_token"], "old-refresh")

    def test_no_refresh_token_anywhere_raises(self):
        store = cs.TokenStore(self.path, http=FakeHttp([]))
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            store.save_authorized({"access_token": "at-3"}, client_id="cid", client_secret="csecret")
        self.assertEqual(ctx.exception.code, "no_refresh_token")


class CalendarServiceListEventsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"
        _write_json(
            self.path,
            {
                "token": "cached-token",
                "refresh_token": "r1",
                "client_id": "cid",
                "client_secret": "csecret",
                "expiry": _future_expiry(),
                "scopes": [cs.CALENDAR_SCOPE],
            },
        )
        self.config = make_config(calendar_id="rodrigo cal@example.com")
        self.start = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
        self.end = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)

    def _service(self, http):
        store = cs.TokenStore(self.path, http=http)
        return cs.CalendarService(self.config, store, http=http)

    def test_builds_url_with_expected_query(self):
        http = FakeHttp([_json_response(200, {"items": []})])
        service = self._service(http)
        service.list_events(self.start, self.end)

        req = http.requests[0]
        parsed = urllib.parse.urlparse(req.full_url)
        self.assertIn(urllib.parse.quote(self.config.calendar_id, safe=""), parsed.path)
        self.assertNotIn(" ", parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["singleEvents"], ["true"])
        self.assertEqual(query["orderBy"], ["startTime"])
        self.assertEqual(query["timeMin"], [self.start.isoformat()])
        self.assertEqual(query["timeMax"], [self.end.isoformat()])
        self.assertEqual(query["timeZone"], [self.config.timezone])

    def test_paginates_up_to_four_pages(self):
        responses = [
            _json_response(200, {"items": [{"id": f"e{i}"}], "nextPageToken": f"tok{i}"})
            for i in range(1, 5)
        ]
        http = FakeHttp(responses)
        service = self._service(http)
        events = service.list_events(self.start, self.end)

        self.assertEqual(len(http.requests), 4)
        self.assertEqual(len(events), 4)

    def test_401_refreshes_once_and_retries(self):
        responses = [
            (401, b"{}"),
            _json_response(200, {"access_token": "fresh-token", "expires_in": 3600}),
            _json_response(200, {"items": [{"id": "ok"}]}),
        ]
        http = FakeHttp(responses)
        service = self._service(http)
        events = service.list_events(self.start, self.end)
        self.assertEqual(events, [{"id": "ok"}])
        self.assertEqual(len(http.requests), 3)

    def test_persistent_401_raises_token_expired(self):
        http = FakeHttp(
            [
                (401, b"{}"),
                _json_response(200, {"access_token": "fresh-token", "expires_in": 3600}),
                (401, b"{}"),
            ]
        )
        service = self._service(http)
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            service.list_events(self.start, self.end)
        self.assertEqual(ctx.exception.code, "token_expired")

    def test_403_raises_permission(self):
        http = FakeHttp([(403, b"{}")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            service.list_events(self.start, self.end)
        self.assertEqual(ctx.exception.code, "permission")

    def test_404_raises_calendar_not_found(self):
        http = FakeHttp([(404, b"{}")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarServiceError) as ctx:
            service.list_events(self.start, self.end)
        self.assertEqual(ctx.exception.code, "calendar_not_found")

    def test_5xx_raises_unavailable(self):
        http = FakeHttp([(503, b"{}")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarServiceError) as ctx:
            service.list_events(self.start, self.end)
        self.assertEqual(ctx.exception.code, "unavailable")

    def test_timeout_raises_unavailable(self):
        http = FakeHttp([TimeoutError("timed out")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarServiceError) as ctx:
            service.list_events(self.start, self.end)
        self.assertEqual(ctx.exception.code, "unavailable")


class CalendarServiceProbeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"
        _write_json(
            self.path,
            {
                "token": "cached-token",
                "refresh_token": "r1",
                "client_id": "cid",
                "client_secret": "csecret",
                "expiry": _future_expiry(),
                "scopes": [cs.CALENDAR_SCOPE],
            },
        )
        self.config = make_config()

    def _service(self, http):
        store = cs.TokenStore(self.path, http=http)
        return cs.CalendarService(self.config, store, http=http)

    def test_probe_success(self):
        http = FakeHttp([_json_response(200, {"summary": "Agenda Rodrigo", "timeZone": "America/Sao_Paulo"})])
        service = self._service(http)
        result = service.probe()
        self.assertEqual(result, {"ok": True, "summary": "Agenda Rodrigo", "time_zone": "America/Sao_Paulo"})

    def test_probe_404_raises_calendar_not_found(self):
        http = FakeHttp([(404, b"{}")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarServiceError) as ctx:
            service.probe()
        self.assertEqual(ctx.exception.code, "calendar_not_found")

    def test_probe_permission(self):
        http = FakeHttp([(403, b"{}")])
        service = self._service(http)
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            service.probe()
        self.assertEqual(ctx.exception.code, "permission")


def _raw_event(**overrides):
    base = {
        "id": "evt-1",
        "status": "confirmed",
        "start": {"dateTime": "2026-09-09T10:00:00-03:00"},
        "end": {"dateTime": "2026-09-09T10:30:00-03:00"},
        "summary": "Maria Silva",
    }
    base.update(overrides)
    return base


class ClassifyEventTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_aya_via_whatsaya_key(self):
        raw = _raw_event(
            summary="Reunião WhatsAYA — João",
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["source"], "aya")
        self.assertEqual(result["kind"], "booking")
        self.assertEqual(result["title"], "Reunião WhatsAYA — João")

    def test_aya_via_therapify_key(self):
        raw = _raw_event(extendedProperties={"private": {"therapifyBookingKey": "xyz"}})
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["source"], "aya")
        self.assertEqual(result["kind"], "booking")

    def test_aya_meet_link_valid(self):
        raw = _raw_event(
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
            hangoutLink="https://meet.google.com/abc-defg-hij",
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["meet_link"], "https://meet.google.com/abc-defg-hij")

    def test_aya_meet_link_wrong_host_discarded(self):
        raw = _raw_event(
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
            hangoutLink="https://evil.com/abc-defg-hij",
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["meet_link"], "")

    def test_aya_html_link_valid(self):
        raw = _raw_event(
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
            htmlLink="https://calendar.google.com/calendar/event?eid=abc",
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["html_link"], "https://calendar.google.com/calendar/event?eid=abc")

    def test_aya_html_link_invalid_host_discarded(self):
        raw = _raw_event(
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
            htmlLink="https://evil.com/event?eid=abc",
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["html_link"], "")

    def test_aya_html_link_http_scheme_discarded(self):
        raw = _raw_event(
            extendedProperties={"private": {"whatsayaBookingKey": "abc"}},
            htmlLink="http://calendar.google.com/calendar/event?eid=abc",
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["html_link"], "")

    def test_external_slot_keyword_case_insensitive(self):
        for summary in ("Livre", "livre para agendar", "LIVRE"):
            raw = _raw_event(summary=summary)
            result = cs.classify_event(raw, self.config)
            self.assertEqual(result["kind"], "slot")
            self.assertEqual(result["title"], self.config.slot_keyword)

    def test_external_block_keyword(self):
        raw = _raw_event(summary="Bloqueada - almoço")
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["kind"], "block")
        self.assertEqual(result["title"], "Bloqueado")

    def test_external_other_is_busy_with_no_leaked_fields(self):
        raw = _raw_event(
            summary="Maria Silva",
            description="Anotações confidenciais do paciente",
            attendees=[{"email": "maria@example.com"}],
            extendedProperties={"private": {"foo": "bar"}},
            hangoutLink="https://meet.google.com/xyz-abcd-efg",
            location="Consultório 2",
            creator={"email": "rodrigo@example.com"},
            organizer={"email": "rodrigo@example.com"},
        )
        result = cs.classify_event(raw, self.config)
        self.assertEqual(result["kind"], "busy")
        self.assertEqual(result["title"], "Ocupado")
        self.assertEqual(result["source"], "external")
        expected_keys = {
            "id", "start", "end", "all_day", "source", "kind", "title", "status", "meet_link", "html_link",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result["meet_link"], "")
        self.assertEqual(result["html_link"], "")

    def test_cancelled_returns_none(self):
        raw = _raw_event(status="cancelled")
        self.assertIsNone(cs.classify_event(raw, self.config))

    def test_missing_start_returns_none(self):
        raw = _raw_event(start={}, end={})
        self.assertIsNone(cs.classify_event(raw, self.config))

    def test_all_day_event(self):
        raw = _raw_event(start={"date": "2026-09-09"}, end={"date": "2026-09-10"})
        result = cs.classify_event(raw, self.config)
        self.assertTrue(result["all_day"])
        self.assertEqual(result["start"], "2026-09-09")


class SanitizedEventsTests(unittest.TestCase):
    def test_orders_by_start(self):
        config = make_config()
        raw_items = [
            _raw_event(id="c", start={"dateTime": "2026-09-09T15:00:00-03:00"}, end={"dateTime": "2026-09-09T15:30:00-03:00"}),
            _raw_event(id="a", start={"dateTime": "2026-09-09T08:00:00-03:00"}, end={"dateTime": "2026-09-09T08:30:00-03:00"}),
            _raw_event(id="cancelled", status="cancelled"),
            _raw_event(id="b", start={"dateTime": "2026-09-09T10:00:00-03:00"}, end={"dateTime": "2026-09-09T10:30:00-03:00"}),
        ]
        result = cs.sanitized_events(raw_items, config)
        self.assertEqual([e["id"] for e in result], ["a", "b", "c"])


class CalendarStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "token.json"
        self.config = make_config()

    def _store(self):
        return cs.TokenStore(self.path, http=FakeHttp([]))

    def _assert_error_is_safe(self, result):
        lowered = result["error"].lower()
        for forbidden in ("token", "refresh", "secret"):
            self.assertNotIn(forbidden, lowered)

    def test_disabled(self):
        config = make_config(enabled=False)
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})
        result = cs.calendar_status(config, self._store(), oauth_configured=True)
        self.assertEqual(result["state"], "disabled")
        self._assert_error_is_safe(result)

    def test_not_configured(self):
        _write_json(self.path, {})
        result = cs.calendar_status(self.config, self._store(), oauth_configured=True)
        self.assertEqual(result["state"], "not_configured")
        self.assertFalse(result["connected"])
        self._assert_error_is_safe(result)

    def test_insufficient_scope(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": []})
        result = cs.calendar_status(self.config, self._store(), oauth_configured=True)
        self.assertEqual(result["state"], "insufficient_scope")
        self.assertTrue(result["connected"])
        self.assertFalse(result["ready"])
        self._assert_error_is_safe(result)

    def test_connected_without_verify(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})
        result = cs.calendar_status(self.config, self._store(), oauth_configured=True)
        self.assertEqual(result["state"], "connected")
        self.assertTrue(result["ready"])
        self._assert_error_is_safe(result)

    def test_connected_with_successful_verify(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})
        result = cs.calendar_status(
            self.config, self._store(), oauth_configured=True, verify=lambda: {"summary": "Agenda Rodrigo"}
        )
        self.assertEqual(result["state"], "connected")
        self.assertEqual(result["calendar_label"], "Agenda Rodrigo")
        self._assert_error_is_safe(result)

    def test_token_expired_via_verify(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})

        def verify():
            raise cs.CalendarAuthError("token_expired", "não deve vazar isso")

        result = cs.calendar_status(self.config, self._store(), oauth_configured=True, verify=verify)
        self.assertEqual(result["state"], "token_expired")
        self._assert_error_is_safe(result)

    def test_permission_via_verify(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})

        def verify():
            raise cs.CalendarAuthError("permission", "sem acesso")

        result = cs.calendar_status(self.config, self._store(), oauth_configured=True, verify=verify)
        self.assertEqual(result["state"], "permission")
        self._assert_error_is_safe(result)

    def test_unavailable_via_verify(self):
        _write_json(self.path, {"refresh_token": "r1", "scopes": [cs.CALENDAR_SCOPE]})

        def verify():
            raise cs.CalendarServiceError("unavailable", "fora do ar")

        result = cs.calendar_status(self.config, self._store(), oauth_configured=True, verify=verify)
        self.assertEqual(result["state"], "unavailable")
        self._assert_error_is_safe(result)


class OAuthAuthorizationUrlTests(unittest.TestCase):
    def test_expected_params(self):
        url = cs.oauth_authorization_url(
            client_id="cid",
            redirect_uri="https://painel.example.com/api/calendar/oauth/callback",
            state="state-123",
            extra_scopes=["https://www.googleapis.com/auth/calendar.events"],
        )
        parsed = urllib.parse.urlparse(url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", cs._AUTH_BASE_URL)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["client_id"], ["cid"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(
            query["scope"],
            [f"{cs.CALENDAR_SCOPE} https://www.googleapis.com/auth/calendar.events"],
        )
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["include_granted_scopes"], ["true"])
        self.assertEqual(query["state"], ["state-123"])

    def test_dedupes_extra_scope_equal_to_base(self):
        url = cs.oauth_authorization_url(
            client_id="cid", redirect_uri="https://x", state="s", extra_scopes=[cs.CALENDAR_SCOPE]
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["scope"], [cs.CALENDAR_SCOPE])


class OAuthExchangeCodeTests(unittest.TestCase):
    def test_posts_expected_fields(self):
        http = FakeHttp([_json_response(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})])
        result = cs.oauth_exchange_code(
            code="the-code",
            client_id="cid",
            client_secret="csecret",
            redirect_uri="https://painel.example.com/cb",
            http=http,
        )
        self.assertEqual(result["access_token"], "at")
        req = http.requests[0]
        self.assertEqual(req.full_url, cs.DEFAULT_TOKEN_URI)
        body = urllib.parse.parse_qs(req.data.decode("utf-8"))
        self.assertEqual(body["grant_type"], ["authorization_code"])
        self.assertEqual(body["code"], ["the-code"])
        self.assertEqual(body["client_id"], ["cid"])
        self.assertEqual(body["client_secret"], ["csecret"])
        self.assertEqual(body["redirect_uri"], ["https://painel.example.com/cb"])

    def test_error_does_not_leak_raw_body(self):
        secret_marker = "SECRET_LEAK_MARKER_XYZ"
        http = FakeHttp([(400, json.dumps({"error": "invalid_grant", "error_description": secret_marker}).encode())])
        with self.assertRaises(cs.CalendarAuthError) as ctx:
            cs.oauth_exchange_code(
                code="bad-code",
                client_id="cid",
                client_secret="csecret",
                redirect_uri="https://painel.example.com/cb",
                http=http,
            )
        self.assertEqual(ctx.exception.code, "oauth_exchange_failed")
        self.assertNotIn(secret_marker, str(ctx.exception))


class OAuthStateTokenTests(unittest.TestCase):
    def test_generates_url_safe_random_tokens(self):
        first = cs.oauth_state_token()
        second = cs.oauth_state_token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main()
