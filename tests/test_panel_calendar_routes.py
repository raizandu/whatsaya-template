from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = REPO_ROOT / "panel"
for _p in (str(REPO_ROOT), str(PANEL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import calendar_service as csvc  # noqa: E402
import data as panel_data  # noqa: E402


def _load_server_module():
    """(Re)carrega `panel/server.py` do zero — o módulo lê `CONFIG_PATH` na
    importação, então cada teste precisa da sua própria execução, depois de
    apontar as env vars pro diretório temporário dele."""
    spec = importlib.util.spec_from_file_location("panel_server_under_test", PANEL_DIR / "server.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["panel_server_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _paths(tmp_dir: Path) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=tmp_dir / "personal_contacts.json",
        messages_db=missing / "messages.db",
        followups_db=missing / "commercial_followups.db",
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
    )


class FakeBridge:
    """O bridge não entra em nenhuma rota de agenda; só precisa existir."""

    def get_json(self, path):
        return None

    def get_json_status(self, path):
        return None, None

    def post_json(self, path, body):
        return None

    def get_bytes(self, path):
        return None


class FakeCalendarHttp:
    """Substitui o `http` do `calendar_service`: despacha por host/caminho e
    `grant_type`, sem tocar a rede de verdade."""

    def __init__(self):
        self.calendar_summary = "Agenda do Rodrigo"
        self.calendar_timezone = "America/Sao_Paulo"
        self.events: list[dict] = []
        self.probe_status = 200
        self.events_status = 200
        self.refresh_status = 200
        self.refresh_access_token = "access-renovado"
        self.exchange_status = 200
        self.exchange_response = {
            "access_token": "novo-access-token",
            "refresh_token": "refresh-secreto-fake",
            "expires_in": 3600,
            "scope": csvc.CALENDAR_SCOPE,
            "token_type": "Bearer",
        }
        self.raise_events_timeout = False
        self.requests: list = []

    def __call__(self, req: urllib.request.Request, timeout: float):
        self.requests.append(req)
        parts = urllib.parse.urlsplit(req.full_url)
        if parts.netloc == "oauth2.googleapis.com":
            body = (req.data or b"").decode("utf-8")
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(body).items()}
            if params.get("grant_type") == "authorization_code":
                if self.exchange_status != 200:
                    return self.exchange_status, json.dumps({"error": "invalid_grant"}).encode()
                return 200, json.dumps(self.exchange_response).encode()
            if self.refresh_status != 200:
                return self.refresh_status, json.dumps({"error": "invalid_grant"}).encode()
            return 200, json.dumps({"access_token": self.refresh_access_token, "expires_in": 3600}).encode()
        if parts.path.endswith("/events"):
            if self.raise_events_timeout:
                raise TimeoutError("timeout simulado")
            return self.events_status, json.dumps({"items": self.events}).encode()
        if self.probe_status != 200:
            return self.probe_status, json.dumps({"error": {"message": "erro simulado"}}).encode()
        return 200, json.dumps({"summary": self.calendar_summary, "timeZone": self.calendar_timezone}).encode()


def _write_token(
    path: Path,
    *,
    scopes,
    expiry_in: int = 3600,
    refresh_token: str = "refresh-abc",
    client_id: str = "cid-123",
    client_secret: str = "secret-123",
    account: str = "",
) -> dict:
    payload = {
        "token": "access-abc",
        "refresh_token": refresh_token,
        "token_uri": csvc.DEFAULT_TOKEN_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": scopes,
        "expiry": (datetime.now(timezone.utc) + timedelta(seconds=expiry_in)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "universe_domain": "googleapis.com",
        "account": account,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CalendarRoutesTestCase(unittest.TestCase):
    """Sobe um `PanelServer` de verdade numa porta efêmera, por teste."""

    default_google_client_id = "cid-123"
    default_google_client_secret = "secret-123"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.config_path = self.tmp_dir / "panel.config.json"
        self.token_path = self.tmp_dir / "google_token.json"
        self.http = FakeCalendarHttp()
        self.username = "admin"
        self.password = "S3nhaSuperForte#2026"
        self.auth_header = "Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode("utf-8")
        ).decode("ascii")
        self._server = None
        self._thread = None

    def tearDown(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)

    def start_server(
        self,
        *,
        google_client_id=None,
        google_client_secret=None,
        public_url: str = "",
        calendar_config_raw=None,
        extra_config=None,
    ):
        payload = {"brand": "Therapify"}
        if extra_config:
            payload.update(extra_config)
        if calendar_config_raw is not None:
            payload["calendar"] = calendar_config_raw
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")

        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_PANEL_CONFIG": str(self.config_path),
            "WHATSAPP_CALENDAR_TOKEN_PATH": str(self.token_path),
        }))
        server_module = _load_server_module()

        config = server_module.Config(
            username=self.username,
            password=self.password,
            bridge_url="http://hermes.invalid:3000",
            bridge_host_header="",
            hermes_dashboard_url="http://hermes.invalid:9119",
            whatsapp_mode="bot",
            whatsapp_allowed_users="*",
            minutes_per_resolved=6.0,
            hourly_rate_brl=38.0,
            owner_number="",
            google_client_id=self.default_google_client_id if google_client_id is None else google_client_id,
            google_client_secret=(
                self.default_google_client_secret if google_client_secret is None else google_client_secret
            ),
            public_url=public_url,
        )
        paths = _paths(self.tmp_dir)
        bridge = FakeBridge()
        handler = server_module.make_handler(config, paths, bridge, None, calendar_http=self.http)
        server = server_module.PanelServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        host, port = server.server_address[:2]
        self.base_url = f"http://127.0.0.1:{port}"
        self.server_module = server_module
        return server_module

    # ── HTTP helpers ────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, body=None, auth: bool = True, extra_headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        if auth:
            req.add_header("Authorization", self.auth_header)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (extra_headers or {}).items():
            req.add_header(key, value)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def _status(self, method: str, path: str, *, auth: bool = True, body=None) -> int:
        status, _raw, _headers = self._request(method, path, auth=auth, body=body)
        return status

    def _get(self, path: str, *, auth: bool = True):
        status, raw, _headers = self._request("GET", path, auth=auth)
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return status, parsed

    def _post(self, path: str, body: dict, *, auth: bool = True):
        status, raw, _headers = self._request("POST", path, body=body, auth=auth)
        parsed = json.loads(raw.decode("utf-8")) if raw else None
        return status, parsed

    def _get_redirect(self, path: str, *, host=None, auth: bool = True):
        extra = {"Host": host} if host else None
        status, _raw, headers = self._request("GET", path, auth=auth, extra_headers=extra)
        return status, headers.get("Location")


class CalendarRoutesAuthTests(CalendarRoutesTestCase):
    def test_all_new_routes_require_auth(self):
        self.start_server()
        for route in (
            "/api/calendar/status",
            "/api/calendar/events",
            "/api/calendar/settings",
            "/api/calendar/oauth/start",
            "/api/calendar/oauth/callback",
        ):
            with self.subTest(route=route):
                self.assertEqual(self._status("GET", route, auth=False), 401)
        self.assertEqual(
            self._status("POST", "/api/actions/calendar-settings", auth=False, body={}), 401,
        )


class CalendarStatusTests(CalendarRoutesTestCase):
    def test_not_configured_without_token(self):
        self.start_server()
        status, body = self._get("/api/calendar/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "not_configured")
        self.assertFalse(body["connected"])
        self.assertIn("redirect_uri", body)

    def test_connected_with_valid_token_and_probe_ok(self):
        self.start_server()
        _write_token(self.token_path, scopes=[csvc.CALENDAR_SCOPE])
        self.http.calendar_summary = "Agenda do Rodrigo"
        status, body = self._get("/api/calendar/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "connected")
        self.assertTrue(body["ready"])
        self.assertEqual(body["calendar_label"], "Agenda do Rodrigo")

    def test_probe_401_maps_to_token_expired(self):
        self.start_server()
        _write_token(self.token_path, scopes=[csvc.CALENDAR_SCOPE])
        self.http.probe_status = 401
        status, body = self._get("/api/calendar/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "token_expired")


class CalendarEventsTests(CalendarRoutesTestCase):
    def test_events_success_returns_aya_and_busy(self):
        self.start_server()
        _write_token(self.token_path, scopes=[csvc.CALENDAR_SCOPE])
        self.http.events = [
            {
                "id": "evt-aya-1",
                "status": "confirmed",
                "summary": "Reunião WhatsAYA — Fulano",
                "start": {"dateTime": "2026-09-14T09:00:00-03:00"},
                "end": {"dateTime": "2026-09-14T09:30:00-03:00"},
                "extendedProperties": {"private": {"whatsayaBookingKey": "abc"}},
                "hangoutLink": "https://meet.google.com/xyz-abcd-efg",
                "htmlLink": "https://www.google.com/calendar/event?eid=xyz",
                "description": "Isso nunca deveria aparecer na resposta.",
            },
            {
                "id": "evt-busy-1",
                "status": "confirmed",
                "summary": "Fulano de Tal",
                "start": {"dateTime": "2026-09-14T14:00:00-03:00"},
                "end": {"dateTime": "2026-09-14T15:00:00-03:00"},
                "description": "Nome do paciente — não pode vazar.",
            },
        ]
        status, body = self._get(
            "/api/calendar/events?from=2026-09-14T00:00:00-03:00&to=2026-09-20T23:59:59-03:00"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["counts"], {"aya": 1, "external": 1})
        events = body["events"]
        self.assertEqual(len(events), 2)
        expected_keys = {
            "id", "start", "end", "all_day", "source", "kind", "title", "status", "meet_link", "html_link",
        }
        for event in events:
            self.assertEqual(set(event.keys()), expected_keys)
            self.assertNotIn("description", event)
        aya = next(e for e in events if e["source"] == "aya")
        busy = next(e for e in events if e["source"] == "external")
        self.assertEqual(aya["kind"], "booking")
        self.assertEqual(aya["meet_link"], "https://meet.google.com/xyz-abcd-efg")
        self.assertEqual(busy["kind"], "busy")
        self.assertEqual(busy["title"], "Ocupado")
        self.assertEqual(busy["meet_link"], "")

    def test_events_without_token_returns_409(self):
        self.start_server()
        status, body = self._get("/api/calendar/events")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "calendar_not_ready")
        self.assertEqual(body["state"], "not_configured")

    def test_events_bad_range_inverted(self):
        self.start_server()
        status, body = self._get(
            "/api/calendar/events?from=2026-09-20T00:00:00-03:00&to=2026-09-14T00:00:00-03:00"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "bad_range")

    def test_events_bad_range_too_long(self):
        self.start_server()
        status, body = self._get(
            "/api/calendar/events?from=2026-01-01T00:00:00-03:00&to=2026-04-01T00:00:00-03:00"
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "bad_range")

    def test_events_upstream_timeout_returns_503(self):
        self.start_server()
        _write_token(self.token_path, scopes=[csvc.CALENDAR_SCOPE])
        self.http.raise_events_timeout = True
        status, body = self._get("/api/calendar/events")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "calendar_unavailable")


class CalendarSettingsGetTests(CalendarRoutesTestCase):
    def test_defaults_when_no_calendar_section(self):
        self.start_server()
        status, body = self._get("/api/calendar/settings")
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "defaults")
        self.assertEqual(body["settings"]["calendar_id"], "primary")

    def test_from_file_when_calendar_section_present(self):
        self.start_server(calendar_config_raw={"calendar_id": "custom@group.calendar.google.com"})
        status, body = self._get("/api/calendar/settings")
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "file")
        self.assertEqual(body["settings"]["calendar_id"], "custom@group.calendar.google.com")


class CalendarSettingsPostTests(CalendarRoutesTestCase):
    def test_valid_persists_and_keeps_existing_brand(self):
        self.start_server()
        status, body = self._post(
            "/api/actions/calendar-settings",
            {"duration_minutes": 45, "calendar_id": "novo@grupo.com"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["settings"]["duration_minutes"], 45)
        self.assertEqual(body["settings"]["calendar_id"], "novo@grupo.com")
        on_disk = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["calendar"]["duration_minutes"], 45)
        self.assertEqual(on_disk["brand"], "Therapify")

    def test_unknown_field_rejected_pt_br(self):
        self.start_server()
        status, body = self._post("/api/actions/calendar-settings", {"nao_existe": 1})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")
        self.assertIn("nao_existe", body["detail"])

    def test_invalid_duration_rejected(self):
        self.start_server()
        status, body = self._post("/api/actions/calendar-settings", {"duration_minutes": 7})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")
        self.assertIn("duration_minutes", body["detail"])

    def test_start_after_end_rejected(self):
        self.start_server()
        status, body = self._post(
            "/api/actions/calendar-settings",
            {"business_start": "18:00", "business_end": "08:00"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "rejected")


class CalendarOAuthStartTests(CalendarRoutesTestCase):
    def test_redirects_with_state_and_calendar_scope_host_derived(self):
        self.start_server(public_url="")
        status, location = self._get_redirect("/api/calendar/oauth/start", host="panel.example.com")
        self.assertEqual(status, 302)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        self.assertIn("state", params)
        self.assertIn(csvc.CALENDAR_SCOPE, params["scope"][0].split())
        self.assertEqual(params["redirect_uri"][0], "https://panel.example.com/api/calendar/oauth/callback")

    def test_redirect_uri_from_public_url_when_set(self):
        self.start_server(public_url="https://painel.therapify.com.br")
        status, location = self._get_redirect("/api/calendar/oauth/start")
        self.assertEqual(status, 302)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        self.assertEqual(
            params["redirect_uri"][0], "https://painel.therapify.com.br/api/calendar/oauth/callback",
        )

    def test_without_credentials_returns_409(self):
        self.start_server(google_client_id="", google_client_secret="")
        status, body = self._get("/api/calendar/oauth/start")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "oauth_not_configured")


class CalendarOAuthCallbackTests(CalendarRoutesTestCase):
    def _obtain_state(self) -> str:
        status, location = self._get_redirect("/api/calendar/oauth/start")
        self.assertEqual(status, 302)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        return params["state"][0]

    def test_invalid_state_redirects_with_code(self):
        self.start_server()
        status, location = self._get_redirect("/api/calendar/oauth/callback?code=abc&state=nao-existe")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/#agenda?oauth_error=invalid_state")

    def test_error_from_google_maps_to_denied(self):
        self.start_server()
        status, location = self._get_redirect("/api/calendar/oauth/callback?error=access_denied&state=x")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/#agenda?oauth_error=denied")

    def test_exchange_failure_redirects_with_code(self):
        self.start_server()
        state = self._obtain_state()
        self.http.exchange_status = 400
        status, location = self._get_redirect(f"/api/calendar/oauth/callback?code=abc&state={state}")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/#agenda?oauth_error=exchange_failed")

    def test_no_refresh_token_in_response_and_none_previously_saved(self):
        self.start_server()
        state = self._obtain_state()
        self.http.exchange_response = {
            "access_token": "tok", "expires_in": 3600, "scope": csvc.CALENDAR_SCOPE,
        }
        status, location = self._get_redirect(f"/api/calendar/oauth/callback?code=abc&state={state}")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/#agenda?oauth_error=no_refresh_token")

    def test_success_saves_token_hides_secret_and_state_is_single_use(self):
        self.start_server()
        state = self._obtain_state()
        stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            status, location = self._get_redirect(f"/api/calendar/oauth/callback?code=abc123&state={state}")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/#agenda?connected=1")

        saved = json.loads(self.token_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["refresh_token"], self.http.exchange_response["refresh_token"])
        self.assertIn(csvc.CALENDAR_SCOPE, saved["scopes"])
        mode = self.token_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

        refresh_token = self.http.exchange_response["refresh_token"]
        combined_output = stdout_buf.getvalue() + stderr_buf.getvalue()
        self.assertNotIn(refresh_token, combined_output)
        self.assertNotIn(refresh_token, location or "")

        # state de uso único: reusar o mesmo state falha.
        status2, location2 = self._get_redirect(f"/api/calendar/oauth/callback?code=abc123&state={state}")
        self.assertEqual(status2, 302)
        self.assertEqual(location2, "/#agenda?oauth_error=invalid_state")


if __name__ == "__main__":
    unittest.main()
