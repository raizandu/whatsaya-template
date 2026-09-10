from __future__ import annotations

import base64
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = REPO_ROOT / "panel"
for _p in (str(REPO_ROOT), str(PANEL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data as panel_data  # noqa: E402


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
    def get_json(self, path):
        return None
    def get_json_status(self, path):
        return None, None
    def post_json(self, path, body):
        return None
    def get_bytes(self, path):
        return None


class FakeCalendarHttp:
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PanelLoginTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)
        self.config_path = self.tmp_dir / "panel.config.json"
        self.username = "admin"
        self.password = "TesteLogin#2026"
        self.auth_header = "Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode("utf-8")
        ).decode("ascii")

        self.config_path.write_text(json.dumps({"brand": "Therapify"}), encoding="utf-8")

        import server as server_module

        # O painel lê a marca de CONFIG_PATH (módulo); sem este patch o teste
        # dependia do panel.config.json real da máquina.
        config_patch = mock.patch.object(server_module, "CONFIG_PATH", self.config_path)
        config_patch.start()
        self.addCleanup(config_patch.stop)

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
            google_client_id="",
            google_client_secret="",
            public_url="https://painel-therapify.agenteaya.com",
        )
        paths = _paths(self.tmp_dir)
        bridge = FakeBridge()
        handler = server_module.make_handler(config, paths, bridge, None, calendar_http=FakeCalendarHttp())
        server = server_module.PanelServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    def tearDown(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)

    def _request(self, method: str, path: str, *, headers=None, data=None, follow_redirects=False):
        url = urllib.parse.urljoin(self.base_url, path)
        req = urllib.request.Request(url, method=method, data=data)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)

        opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req)
            return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def test_login_page_public_access(self):
        status, headers, body = self._request("GET", "/login")
        self.assertEqual(status, 200)
        content = body.decode("utf-8")
        self.assertIn("Entrar no painel", content)
        self.assertIn("login.css", content)
        self.assertIn("Therapify", content)

    def test_static_assets_public_access(self):
        status, _, _ = self._request("GET", "/static/theme.css")
        self.assertEqual(status, 200)
        status, _, _ = self._request("GET", "/static/login.css")
        self.assertEqual(status, 200)

    def test_favicon_endpoints(self):
        status, headers, body = self._request("GET", "/favicon.ico")
        self.assertEqual(status, 200)
        self.assertTrue(len(body) > 0)
        status, headers, body = self._request("GET", "/static/favicon.svg")
        self.assertEqual(status, 200)
        self.assertIn("<svg", body.decode("utf-8"))

    def test_public_config(self):
        status, _, body = self._request("GET", "/api/public-config")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("brand"), "Therapify")

    def test_unauthenticated_browser_redirects_to_login(self):
        status, headers, _ = self._request(
            "GET", "/", headers={"Accept": "text/html,application/xhtml+xml"}
        )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/login")

    def test_unauthenticated_api_returns_401(self):
        status, headers, body = self._request("GET", "/api/status")
        self.assertEqual(status, 401)
        self.assertIn("Basic realm=", headers.get("WWW-Authenticate", ""))

    def test_login_failure(self):
        payload = json.dumps({"username": "admin", "password": "wrong_password"}).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/login",
            headers={"Content-Type": "application/json"},
            data=payload,
        )
        self.assertEqual(status, 401)
        data = json.loads(body.decode("utf-8"))
        self.assertFalse(data.get("ok"))
        self.assertIn("incorretos", data.get("error"))

    def test_login_success_and_session_flow(self):
        # 1. Login com sucesso
        payload = json.dumps({"username": "admin", "password": "TesteLogin#2026"}).encode("utf-8")
        status, headers, body = self._request(
            "POST", "/api/login",
            headers={"Content-Type": "application/json"},
            data=payload,
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("redirect"), "/")

        cookie = headers.get("Set-Cookie")
        self.assertIsNotNone(cookie)
        self.assertIn("whatsaya_session=", cookie)
        session_val = cookie.split(";")[0]

        # 2. Acessa raiz com cookie de sessão -> 200 index.html
        status, _, body = self._request(
            "GET", "/",
            headers={"Cookie": session_val, "Accept": "text/html"},
        )
        self.assertEqual(status, 200)
        self.assertIn("Painel WhatsAYA", body.decode("utf-8"))

        # 3. Acessa /login quando já autenticado -> 302 para /
        status, headers, _ = self._request(
            "GET", "/login",
            headers={"Cookie": session_val},
        )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/")

        # 4. Logout limpa o cookie e manda para /login?logged_out=1
        status, headers, _ = self._request(
            "GET", "/logout",
            headers={"Cookie": session_val},
        )
        self.assertEqual(status, 302)
        self.assertIn("/login?logged_out=1", headers.get("Location"))
        logout_cookie = headers.get("Set-Cookie")
        self.assertIn("Max-Age=0", logout_cookie)

    def test_basic_auth_still_works(self):
        status, _, body = self._request(
            "GET", "/api/config",
            headers={"Authorization": self.auth_header},
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("brand"), "Therapify")


if __name__ == "__main__":
    unittest.main()
