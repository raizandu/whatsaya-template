"""Painel de operação do WhatsAYA — servidor HTTP.

Só stdlib: `http.server` + `sqlite3` + `urllib`. Roda num container próprio ao
lado do `hermes`, lê os mesmos arquivos do volume `/opt/data` e fala com o
bridge pela rede interna. Autenticação é HTTP Basic com o mesmo usuário e senha
do dashboard do Hermes; sem senha, ou com o fallback `admin123`, o processo se
recusa a subir em vez de expor a operação.

    python3 panel/server.py            # porta 9120
"""
from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import data as panel_data  # noqa: E402

STATIC_DIR = Path(__file__).resolve().with_name("static")
CONFIG_PATH = Path(__file__).resolve().with_name("panel.config.json")
WEAK_PASSWORDS = {"", "admin123", "admin", "password", "senha"}


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    bridge_url: str
    bridge_host_header: str
    minutes_per_resolved: float
    hourly_rate_brl: float
    owner_number: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = env if env is not None else os.environ
        password = (env.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD") or env.get("HERMES_DASHBOARD_PASSWORD") or "").strip()
        return cls(
            username=(env.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME") or "admin").strip(),
            password=password,
            bridge_url=(env.get("WHATSAPP_BRIDGE_URL") or "http://hermes:3000").rstrip("/"),
            bridge_host_header=(env.get("WHATSAPP_BRIDGE_HOST_HEADER") or "").strip(),
            minutes_per_resolved=float(env.get("WHATSAPP_PANEL_MINUTES_PER_RESOLVED") or 6),
            hourly_rate_brl=float(env.get("WHATSAPP_PANEL_HOURLY_RATE_BRL") or 38),
            owner_number="".join(ch for ch in (env.get("WHATSAPP_OWNER_NUMBER") or "") if ch.isdigit()),
        )


def paths_from_env(env: dict | None = None) -> panel_data.Paths:
    env = env if env is not None else os.environ
    default = panel_data.Paths()
    return panel_data.Paths(
        contacts_json=Path(env.get("WHATSAPP_CONTACTS_PATH") or default.contacts_json),
        messages_db=Path(env.get("WHATSAPP_HISTORY_DB_PATH") or default.messages_db),
        followups_db=Path(env.get("WHATSAPP_FOLLOWUP_DB") or default.followups_db),
        state_db=Path(env.get("HERMES_STATE_DB") or default.state_db),
        plugin_log=Path(env.get("WHATSAPP_PLUGIN_LOG") or default.plugin_log),
        gateway_log=Path(env.get("HERMES_GATEWAY_LOG") or default.gateway_log),
        pricing_json=Path(env.get("WHATSAPP_PANEL_PRICING") or default.pricing_json),
    )


class BridgeClient:
    """Chamadas ao bridge com timeout curto. Falha vira estado, não exceção."""

    def __init__(self, base_url: str, host_header: str = "", timeout: float = 4.0):
        self.base_url = base_url
        self.host_header = host_header
        self.timeout = timeout
        # Rede interna: nunca passa por proxy de ambiente (e a detecção de proxy do
        # sistema no macOS custa segundos por chamada).
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, *, method: str = "GET", body: dict | None = None):
        req = urllib.request.Request(self.base_url + path, method=method)
        if self.host_header:
            req.add_header("Host", self.host_header)
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        return self._opener.open(req, payload, timeout=self.timeout)

    def get_json(self, path: str) -> dict | None:
        try:
            with self._request(path) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode("utf-8"))
            except Exception:
                return None
        except Exception:
            return None

    def get_bytes(self, path: str) -> tuple[bytes, str] | None:
        try:
            with self._request(path) as resp:
                return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
        except Exception:
            return None


def build_status(bridge: BridgeClient) -> dict:
    status = bridge.get_json("/whatsapp/status")
    bot = bridge.get_json("/bot-status")
    if status is None and bot is None:
        return {"bridge": "unreachable", "connection": "unknown", "paused": None, "qr_available": False, "uptime_s": 0}
    connection = str((status or {}).get("status") or "unknown")
    return {
        "bridge": "up",
        "connection": connection,
        "connected": bool((status or {}).get("connected")),
        "qr_available": bool((status or {}).get("qrAvailable")),
        "qr_at": (status or {}).get("currentQrAt"),
        "paused": bool((bot or {}).get("botPaused")) if bot else None,
        "uptime_s": int((bot or {}).get("uptime") or 0) if bot else 0,
    }


class PanelServer(ThreadingHTTPServer):
    """`HTTPServer.server_bind` resolve o FQDN do host por DNS reverso; num container
    sem DNS reverso (ou no macOS) isso trava dezenas de segundos no boot. O nome
    do servidor não é usado por nenhuma rota, então fica o host literal."""

    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def make_handler(config: Config, paths: panel_data.Paths, bridge: BridgeClient):
    expected = base64.b64encode(f"{config.username}:{config.password}".encode("utf-8")).decode("ascii")

    class Handler(BaseHTTPRequestHandler):
        server_version = "WhatsAYAPanel/1.0"

        def log_message(self, fmt, *args):  # silencia o log por requisição
            return

        # ── helpers ─────────────────────────────────────────────────────
        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            return hmac.compare_digest(header[6:].strip(), expected)

        def _deny(self):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="WhatsAYA"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Autenticação necessária.".encode("utf-8"))

        def _json(self, payload, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, body: bytes, content_type: str, status: int = 200, cache: str = "no-store"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self, rel: str):
            target = (STATIC_DIR / rel).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                return self._json({"error": "not found"}, 404)
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self._bytes(target.read_bytes(), ctype, cache="no-cache")

        # ── rotas ───────────────────────────────────────────────────────
        def do_GET(self):
            if not self._authorized():
                return self._deny()
            url = urlsplit(self.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            period = query.get("period") if query.get("period") in panel_data.PERIOD_DAYS else "7d"
            route = url.path
            try:
                if route == "/" or route == "/index.html":
                    return self._static("index.html")
                if route.startswith("/static/"):
                    return self._static(route[len("/static/"):])
                if route == "/api/config":
                    return self._json(self._config_payload())
                if route == "/api/status":
                    return self._json(build_status(bridge))
                if route == "/api/qr.png":
                    got = bridge.get_bytes("/whatsapp/qr?format=png")
                    if got is None:
                        return self._json({"error": "qr_unavailable"}, 404)
                    return self._bytes(got[0], got[1])
                if route == "/api/metrics":
                    return self._json(panel_data.metrics(paths, period, minutes_per_resolved=config.minutes_per_resolved))
                if route == "/api/leads":
                    return self._json(panel_data.leads(paths))
                if route == "/api/followups":
                    return self._json(panel_data.followups(paths, period))
                if route == "/api/blocked":
                    contacts = panel_data.load_contacts(paths.contacts_json)
                    since = datetime.now(timezone.utc).timestamp() - 86400
                    recent = []
                    for chat in panel_data.recent_chats(paths.messages_db, datetime.fromtimestamp(since, timezone.utc)):
                        record = contacts.get(chat["chat_id"]) if isinstance(contacts.get(chat["chat_id"]), dict) else {}
                        if record.get("blocked") is True or panel_data._digits(chat["chat_id"]) == config.owner_number:
                            continue
                        recent.append({
                            **chat,
                            "name": panel_data._contact_name(contacts, chat["chat_id"]),
                            "phone": panel_data.format_phone(chat["chat_id"]),
                        })
                    return self._json({"blocked": panel_data.blocked_contacts(contacts), "recent": recent})
                if route == "/api/usage":
                    return self._json(panel_data.usage(paths, period))
                if route == "/api/health":
                    return self._json({"ok": True, "now": datetime.now(timezone.utc).isoformat()})
            except Exception as exc:  # o painel nunca derruba; devolve o erro
                return self._json({"error": type(exc).__name__, "detail": str(exc)[:200]}, 500)
            return self._json({"error": "not found"}, 404)

        def _config_payload(self) -> dict:
            custom = {}
            if CONFIG_PATH.is_file():
                try:
                    custom = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                except ValueError:
                    custom = {}
            return {
                "brand": custom.get("brand") or "WhatsAYA",
                "theme": custom.get("theme") or {},
                "minutes_per_resolved": config.minutes_per_resolved,
                "hourly_rate_brl": config.hourly_rate_brl,
                "features": custom.get("features") or {},
            }

    return Handler


def main(argv: list[str] | None = None) -> int:
    config = Config.from_env()
    if config.password in WEAK_PASSWORDS:
        print(
            "[painel] HERMES_DASHBOARD_BASIC_AUTH_PASSWORD ausente ou fraca; o painel não sobe sem senha.",
            file=sys.stderr,
        )
        return 2
    host = os.environ.get("WHATSAPP_PANEL_HOST") or "0.0.0.0"
    port = int(os.environ.get("WHATSAPP_PANEL_PORT") or 9120)
    bridge = BridgeClient(config.bridge_url, config.bridge_host_header)
    server = PanelServer((host, port), make_handler(config, paths_from_env(), bridge))
    print(f"[painel] no ar em http://{host}:{port} · bridge={config.bridge_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
