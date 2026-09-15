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
import users_store  # noqa: E402


def _paths(tmp_dir: Path) -> "panel_data.Paths":
    missing = tmp_dir / "missing"
    return panel_data.Paths(
        contacts_json=tmp_dir / "personal_contacts.json",
        # `reply()` abre `messages_db` direto por `sqlite3.connect`, sem criar
        # diretório — precisa de um pai que já existe (ao contrário dos outros
        # bancos abaixo, que toleram caminho ausente nas rotas de leitura).
        messages_db=tmp_dir / "whatsapp_messages.db",
        followups_db=missing / "commercial_followups.db",
        state_db=missing / "state.db",
        plugin_log=missing / "plugin.log",
        gateway_log=missing / "gateway.log",
        pricing_json=missing / "pricing.json",
        panel_db=tmp_dir / "panel.db",
        users_json=tmp_dir / "panel_users.json",
    )


class FakeBridge:
    """Como o bridge real responde a `/send` e `/chat-silence`, pro fluxo de
    resposta do atendente ter algo para chamar."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, path):
        return None
    def get_json_status(self, path):
        return None, None
    def post_json(self, path, body, timeout=None):
        self.calls.append((path, body))
        if path == "/send":
            message_id = f"login-out-{len(self.calls)}"
            return {"success": True, "messageId": message_id, "messageIds": [message_id]}
        if path == "/chat-silence":
            return {"success": True, "chatId": body.get("chatId"), "silencedUntil": 1, "timeLeftSeconds": 600}
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
            health_api_key="health-test-" + "a" * 40,
            release_ref="v1.2.3",
            hermes_image_tag="v2026.7.20",
        )
        self.paths = _paths(self.tmp_dir)
        self.bridge = FakeBridge()
        paths = self.paths
        bridge = self.bridge
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

    def test_health_accepts_its_own_bearer_without_exposing_business_data(self):
        status, _, body = self._request(
            "GET", "/api/health",
            headers={"Authorization": "Bearer health-test-" + "a" * 40},
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["service"], "whatsaya")
        self.assertEqual(data["release_ref"], "v1.2.3")
        self.assertEqual(data["status"], "degraded")
        self.assertNotIn("connected_number", json.dumps(data))

        status, _, _ = self._request(
            "GET", "/api/health", headers={"Authorization": "Bearer " + "x" * 64},
        )
        self.assertEqual(status, 401)

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

    def test_env_admin_login_still_works(self):
        payload = json.dumps({"username": self.username, "password": self.password}).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/login", headers={"Content-Type": "application/json"}, data=payload,
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body.decode("utf-8")).get("ok"))

    # ── usuários e papéis (Fase 3a) ────────────────────────────────────────

    def _login_and_get_cookie(self, username: str, password: str) -> str:
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        status, headers, body = self._request(
            "POST", "/api/login", headers={"Content-Type": "application/json"}, data=payload,
        )
        self.assertEqual(status, 200, body)
        return headers.get("Set-Cookie").split(";")[0]

    def _create_attendant(self, username="ana.silva", name="Ana Silva", password="SenhaForte#2026"):
        return users_store.create_user(
            self.paths.users_json, username=username, name=name, password=password, role="atendente",
        )

    def test_attendant_login_via_json_and_form(self):
        self._create_attendant()

        payload = json.dumps({"username": "ana.silva", "password": "SenhaForte#2026"}).encode("utf-8")
        status, headers, _ = self._request(
            "POST", "/api/login", headers={"Content-Type": "application/json"}, data=payload,
        )
        self.assertEqual(status, 200)
        self.assertIn("whatsaya_session=", headers.get("Set-Cookie", ""))

        form = urllib.parse.urlencode({"username": "ana.silva", "password": "SenhaForte#2026"}).encode("utf-8")
        status, headers, _ = self._request(
            "POST", "/api/login",
            headers={"Content-Type": "application/x-www-form-urlencoded"}, data=form,
        )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/")
        self.assertIn("whatsaya_session=", headers.get("Set-Cookie", ""))

    def test_me_endpoint_for_admin_and_attendant(self):
        self._create_attendant()

        status, _, body = self._request("GET", "/api/me", headers={"Authorization": self.auth_header})
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body.decode("utf-8")), {"username": "admin", "name": "admin", "role": "admin"},
        )

        cookie = self._login_and_get_cookie("ana.silva", "SenhaForte#2026")
        status, _, body = self._request("GET", "/api/me", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data, {"username": "ana.silva", "name": "Ana Silva", "role": "atendente"})

    def test_attendant_gets_403_on_block_action(self):
        self._create_attendant()
        cookie = self._login_and_get_cookie("ana.silva", "SenhaForte#2026")
        payload = json.dumps({"chat_id": "5547999999999@s.whatsapp.net"}).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/actions/block",
            headers={"Content-Type": "application/json", "Cookie": cookie},
            data=payload,
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body.decode("utf-8")).get("error"), "forbidden")

    def test_attendant_reply_sends_with_own_name(self):
        self._create_attendant()
        cookie = self._login_and_get_cookie("ana.silva", "SenhaForte#2026")
        payload = json.dumps(
            {"chat_id": "5547999999999@s.whatsapp.net", "message": "Oi! Já te respondo."}
        ).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/actions/reply",
            headers={"Content-Type": "application/json", "Cookie": cookie},
            data=payload,
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("sent_by"), "Ana Silva")
        self.assertEqual(data.get("sent_by_user"), "ana.silva")
        self.assertIs(data.get("silenced"), True)
        self.assertTrue(any(call[0] == "/send" for call in self.bridge.calls))
        self.assertTrue(any(call[0] == "/chat-silence" for call in self.bridge.calls))

    def test_deactivated_user_loses_session_immediately(self):
        self._create_attendant()
        cookie = self._login_and_get_cookie("ana.silva", "SenhaForte#2026")
        status, _, _ = self._request("GET", "/api/me", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

        users_store.set_active(self.paths.users_json, "ana.silva", False)
        status, headers, _ = self._request("GET", "/api/status", headers={"Cookie": cookie})
        self.assertEqual(status, 401)
        self.assertIn("Basic realm=", headers.get("WWW-Authenticate", ""))

    def test_users_create_forbidden_for_attendant(self):
        self._create_attendant()
        cookie = self._login_and_get_cookie("ana.silva", "SenhaForte#2026")
        payload = json.dumps({
            "username": "outro.user", "name": "Outro", "password": "SenhaForte#2026", "role": "atendente",
        }).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/actions/users/create",
            headers={"Content-Type": "application/json", "Cookie": cookie},
            data=payload,
        )
        self.assertEqual(status, 403)

    def test_users_create_as_admin_and_weak_password_rejected(self):
        payload = json.dumps({
            "username": "carlos.souza", "name": "Carlos Souza", "password": "SenhaForte#2026", "role": "atendente",
        }).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/actions/users/create",
            headers={"Content-Type": "application/json", "Authorization": self.auth_header},
            data=payload,
        )
        self.assertEqual(status, 200, body)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data.get("username"), "carlos.souza")
        self.assertNotIn("pbkdf2", data)

        weak_payload = json.dumps({
            "username": "user.fraco", "name": "Usuário Fraco", "password": "123", "role": "atendente",
        }).encode("utf-8")
        status, _, body = self._request(
            "POST", "/api/actions/users/create",
            headers={"Content-Type": "application/json", "Authorization": self.auth_header},
            data=weak_payload,
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body.decode("utf-8")).get("error"), "rejected")


if __name__ == "__main__":
    unittest.main()
