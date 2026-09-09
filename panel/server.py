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
import html as html_lib
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
import hashlib
import secrets
from http.cookies import SimpleCookie

import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import actions as panel_actions  # noqa: E402
import calendar_config  # noqa: E402
import calendar_service  # noqa: E402
import data as panel_data  # noqa: E402
from pairing import (  # noqa: E402
    HermesDashboardClient,
    PairingStartError,
    PairingSupervisor,
)

SESSION_COOKIE_NAME = "whatsaya_session"
SESSION_TTL_S = 30 * 86400  # 30 dias
STATIC_DIR = Path(__file__).resolve().with_name("static")
CONFIG_PATH = Path(
    os.environ.get("WHATSAPP_PANEL_CONFIG")
    or Path(__file__).resolve().with_name("panel.config.json")
)
WEAK_PASSWORDS = {"", "admin123", "admin", "password", "senha"}
DEFAULT_SUBSCRIPTION = {
    "name": "Plano mensal",
    "price_brl": None,
    "billing": "mensal",
    "included": [
        "Atendimento automatizado no WhatsApp",
        "Funil comercial e histórico das conversas",
        "Follow-ups automáticos",
        "Gestão de contatos e bloqueios",
        "Painel de acompanhamento da operação",
    ],
}


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    bridge_url: str
    bridge_host_header: str
    hermes_dashboard_url: str
    whatsapp_mode: str
    whatsapp_allowed_users: str
    minutes_per_resolved: float
    hourly_rate_brl: float
    owner_number: str
    google_client_id: str
    google_client_secret: str
    public_url: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Config":
        env = env if env is not None else os.environ
        password = (env.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD") or env.get("HERMES_DASHBOARD_PASSWORD") or "").strip()
        return cls(
            username=(env.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME") or "admin").strip(),
            password=password,
            bridge_url=(env.get("WHATSAPP_BRIDGE_URL") or "http://hermes:3000").rstrip("/"),
            bridge_host_header=(env.get("WHATSAPP_BRIDGE_HOST_HEADER") or "").strip(),
            hermes_dashboard_url=(env.get("HERMES_DASHBOARD_INTERNAL_URL") or "http://hermes:9119").strip().rstrip("/"),
            whatsapp_mode=(env.get("WHATSAPP_MODE") or "bot").strip(),
            whatsapp_allowed_users=(env.get("WHATSAPP_ALLOWED_USERS") or "*").strip(),
            minutes_per_resolved=float(env.get("WHATSAPP_PANEL_MINUTES_PER_RESOLVED") or 6),
            hourly_rate_brl=float(env.get("WHATSAPP_PANEL_HOURLY_RATE_BRL") or 38),
            owner_number="".join(ch for ch in (env.get("WHATSAPP_OWNER_NUMBER") or "") if ch.isdigit()),
            google_client_id=(env.get("GOOGLE_CLIENT_ID") or "").strip(),
            google_client_secret=(env.get("GOOGLE_CLIENT_SECRET") or "").strip(),
            public_url=(env.get("WHATSAPP_PANEL_PUBLIC_URL") or "").strip().rstrip("/"),
        )


def paths_from_env(env: dict | None = None) -> panel_data.Paths:
    env = env if env is not None else os.environ
    default = panel_data.Paths()
    return panel_data.Paths(
        contacts_json=Path(env.get("WHATSAPP_CONTACTS_PATH") or default.contacts_json),
        messages_db=Path(env.get("WHATSAPP_HISTORY_DB_PATH") or default.messages_db),
        followups_db=Path(env.get("WHATSAPP_FOLLOWUP_DB") or default.followups_db),
        bookings_db=Path(env.get("WHATSAPP_CALENDAR_BOOKINGS_DB") or default.bookings_db),
        state_db=Path(env.get("HERMES_STATE_DB") or default.state_db),
        plugin_log=Path(env.get("WHATSAPP_PLUGIN_LOG") or default.plugin_log),
        gateway_log=Path(env.get("HERMES_GATEWAY_LOG") or default.gateway_log),
        pricing_json=Path(env.get("WHATSAPP_PANEL_PRICING") or default.pricing_json),
    )


CALENDAR_MAX_RANGE_DAYS = 42


def _parse_calendar_iso(value: str, cfg: calendar_config.CalendarConfig) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=cfg.tz())
    return parsed


def _default_calendar_week(cfg: calendar_config.CalendarConfig) -> tuple[datetime, datetime]:
    now_local = datetime.now(cfg.tz())
    monday = (now_local - timedelta(days=now_local.isoweekday() - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sunday_end = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday_end


def _parse_calendar_range(query: dict, cfg: calendar_config.CalendarConfig) -> tuple[datetime, datetime]:
    """`from`/`to` da querystring (ISO 8601, aceita `Z`); ausentes → semana atual."""
    raw_from = query.get("from")
    raw_to = query.get("to")
    default_start, default_end = _default_calendar_week(cfg)
    try:
        start = _parse_calendar_iso(raw_from, cfg) if raw_from else default_start
        end = _parse_calendar_iso(raw_to, cfg) if raw_to else default_end
    except ValueError as exc:
        raise ValueError(
            "Datas inválidas; use o formato ISO 8601 (ex.: 2026-09-08T00:00:00-03:00)."
        ) from exc
    if end <= start:
        raise ValueError("O período final precisa ser depois do início.")
    if end - start > timedelta(days=CALENDAR_MAX_RANGE_DAYS):
        raise ValueError(f"Período máximo de {CALENDAR_MAX_RANGE_DAYS} dias.")
    return start, end


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

    def get_json_status(self, path: str) -> tuple[int | None, dict | None]:
        """Como `get_json`, mas devolve o status HTTP junto — pra distinguir
        "etiqueta não encontrada" (404) de "ponte indisponível" (o resto)."""
        try:
            with self._request(path) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except Exception:
                return exc.code, None
        except Exception:
            return None, None

    def post_json(self, path: str, body: dict) -> dict | None:
        try:
            with self._request(path, method="POST", body=body) as resp:
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


_LID_CACHE: dict[str, Any] = {"at": 0.0, "map": {}}


def lid_map(bridge: BridgeClient, *, ttl: float = 60.0) -> dict:
    """Mapa lidToPhone do bridge, com cache curto. Ponte fora do ar devolve o
    último mapa conhecido (ou vazio) em vez de derrubar a rota."""
    now = time.monotonic()
    if now - float(_LID_CACHE["at"]) < ttl and _LID_CACHE["map"]:
        return _LID_CACHE["map"]
    payload = bridge.get_json("/bot-status") or {}
    fresh = payload.get("lidToPhone")
    if isinstance(fresh, dict) and fresh:
        _LID_CACHE["map"] = fresh
        _LID_CACHE["at"] = now
    return _LID_CACHE["map"]


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


def build_whatsapp_settings(bridge: BridgeClient) -> dict:
    payload = bridge.get_json("/runtime-settings")
    settings = payload.get("settings") if isinstance(payload, dict) else None
    if not isinstance(settings, dict):
        return {"known": False, "reject_calls": False, "groups_enabled": False, "debounce_seconds": 0}
    debounce_ms = settings.get("debounceInitialMs")
    if (
        not isinstance(settings.get("rejectCalls"), bool)
        or not isinstance(settings.get("groupsEnabled"), bool)
        or isinstance(debounce_ms, bool)
        or not isinstance(debounce_ms, int)
    ):
        return {"known": False, "reject_calls": False, "groups_enabled": False, "debounce_seconds": 0}
    return {
        "known": True,
        "reject_calls": settings["rejectCalls"],
        "groups_enabled": settings["groupsEnabled"],
        "debounce_seconds": debounce_ms // 1000,
    }


def build_subscription(custom: dict) -> dict:
    raw = custom.get("subscription") if isinstance(custom.get("subscription"), dict) else {}
    name = str(raw.get("name") or DEFAULT_SUBSCRIPTION["name"]).strip()[:80]
    billing = str(raw.get("billing") or DEFAULT_SUBSCRIPTION["billing"]).strip()[:40]
    raw_price = raw.get("price_brl")
    price = (
        float(raw_price)
        if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool) and raw_price >= 0
        else None
    )
    if price is not None and price.is_integer():
        price = int(price)
    raw_included = raw.get("included")
    included = (
        [str(item).strip()[:120] for item in raw_included if isinstance(item, str) and item.strip()][:12]
        if isinstance(raw_included, list)
        else list(DEFAULT_SUBSCRIPTION["included"])
    )
    return {"name": name, "price_brl": price, "billing": billing, "included": included}


def _custom_config() -> dict:
    """Conteúdo de `panel.config.json`; `{}` quando falta o arquivo ou o JSON é
    inválido."""
    if not CONFIG_PATH.is_file():
        return {}
    try:
        custom = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return custom if isinstance(custom, dict) else {}


def _reactivation_config(custom: dict) -> dict:
    """`{"reactivation": {"label": ...}}` de `panel.config.json`; `remarketing`
    quando ausente ou vazio."""
    raw = custom.get("reactivation") if isinstance(custom.get("reactivation"), dict) else {}
    label = str(raw.get("label") or "").strip() or "remarketing"
    return {"label": label}


def build_chat_silence(bridge: BridgeClient, chat_id: str) -> dict:
    payload = bridge.get_json("/chat-status/" + quote(chat_id, safe=""))
    if not isinstance(payload, dict):
        return {"known": False, "silenced": False, "time_left_s": 0}
    return {
        "known": True,
        "silenced": bool(payload.get("silenced")),
        "time_left_s": int(payload.get("timeLeftSeconds") or 0),
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


def make_handler(
    config: Config,
    paths: panel_data.Paths,
    bridge: BridgeClient,
    supervisor: PairingSupervisor | None = None,
    *,
    calendar_http=None,
):
    expected = base64.b64encode(f"{config.username}:{config.password}".encode("utf-8")).decode("ascii")
    dashboard = HermesDashboardClient(config.hermes_dashboard_url, config.username, config.password)

    session_secret = hashlib.sha256(
        f"whatsaya-session-auth:{config.username}:{config.password}".encode("utf-8")
    ).digest()

    def _create_session() -> str:
        now = int(time.time())
        nonce = secrets.token_hex(12)
        payload = f"{config.username}:{now}:{nonce}"
        sig = hmac.new(session_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}:{sig}"

    def _verify_session(token: str) -> bool:
        if not token or not isinstance(token, str):
            return False
        parts = token.split(":")
        if len(parts) != 4:
            return False
        username, ts_str, nonce, sig = parts
        if not hmac.compare_digest(username, config.username):
            return False
        try:
            ts = int(ts_str)
        except ValueError:
            return False
        now = int(time.time())
        if ts > now + 300:
            return False
        if now - ts > SESSION_TTL_S:
            return False
        payload = f"{username}:{ts_str}:{nonce}"
        expected_sig = hmac.new(session_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)


    # ── agenda (Google Calendar) ───────────────────────────────────────────
    # Um TokenStore só (é quem lê/escreve o token em disco); a config recarrega
    # a cada request porque o painel pode editá-la sem reiniciar o processo.
    calendar_token_store = calendar_service.TokenStore(calendar_config.token_path(), http=calendar_http)
    _probe_cache: dict[str, tuple[float, tuple[str, Any]]] = {}
    _oauth_lock = threading.Lock()
    _oauth_pending: dict[str, float] = {}
    OAUTH_STATE_TTL_S = 600.0
    OAUTH_MAX_PENDING = 20
    PROBE_CACHE_TTL_S = 60.0

    def _oauth_credentials() -> tuple[str, str]:
        if config.google_client_id and config.google_client_secret:
            return config.google_client_id, config.google_client_secret
        saved = calendar_token_store.load()
        return (
            str(saved.get("client_id") or "").strip(),
            str(saved.get("client_secret") or "").strip(),
        )

    def _oauth_configured() -> bool:
        client_id, client_secret = _oauth_credentials()
        return bool(client_id and client_secret)

    def _register_oauth_state(state: str) -> None:
        now = time.monotonic()
        with _oauth_lock:
            for expired in [s for s, exp in _oauth_pending.items() if exp <= now]:
                del _oauth_pending[expired]
            _oauth_pending[state] = now + OAUTH_STATE_TTL_S
            while len(_oauth_pending) > OAUTH_MAX_PENDING:
                oldest = min(_oauth_pending, key=lambda s: _oauth_pending[s])
                del _oauth_pending[oldest]

    def _consume_oauth_state(state: str) -> bool:
        now = time.monotonic()
        with _oauth_lock:
            expires_at = _oauth_pending.pop(state, None)
        return expires_at is not None and expires_at > now

    def _probe(cfg: calendar_config.CalendarConfig) -> dict:
        now = time.monotonic()
        cached = _probe_cache.get(cfg.calendar_id)
        if cached is not None and now - cached[0] < PROBE_CACHE_TTL_S:
            kind, payload = cached[1]
            if kind == "ok":
                return payload
            raise payload
        service = calendar_service.CalendarService(cfg, calendar_token_store, http=calendar_http)
        try:
            result = service.probe()
        except (calendar_service.CalendarAuthError, calendar_service.CalendarServiceError) as exc:
            _probe_cache[cfg.calendar_id] = (now, ("error", exc))
            raise
        _probe_cache[cfg.calendar_id] = (now, ("ok", result))
        return result

    def _agenda_redirect(code: str) -> str:
        return f"/#agenda?oauth_error={code}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "WhatsAYAPanel/1.0"

        def log_message(self, fmt, *args):  # silencia o log por requisição
            return

        # ── helpers ─────────────────────────────────────────────────────
        def _session_cookie(self) -> str:
            raw = self.headers.get("Cookie", "")
            if not raw:
                return ""
            try:
                cookie = SimpleCookie()
                cookie.load(raw)
                if SESSION_COOKIE_NAME in cookie:
                    return cookie[SESSION_COOKIE_NAME].value
            except Exception:
                return ""
            return ""

        def _is_secure_conn(self) -> bool:
            if self.headers.get("X-Forwarded-Proto") == "https":
                return True
            if "https" in self.headers.get("CF-Visitor", ""):
                return True
            if config.public_url and config.public_url.startswith("https://"):
                return True
            return False

        def _build_cookie_header(self, token: str, max_age: int) -> str:
            parts = [
                f"{SESSION_COOKIE_NAME}={token}",
                "Path=/",
                f"Max-Age={max_age}",
                "HttpOnly",
                "SameSite=Lax",
            ]
            if self._is_secure_conn():
                parts.append("Secure")
            return "; ".join(parts)

        def _authorized(self) -> bool:
            token = self._session_cookie()
            if token and _verify_session(token):
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Basic "):
                return hmac.compare_digest(header[6:].strip(), expected)
            return False

        def _deny(self):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="WhatsAYA"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized","detail":"Autentica\xc3\xa7\xc3\xa3o necess\xc3\xa1ria."}')

        def _logout(self):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login?logged_out=1")
            self.send_header("Set-Cookie", self._build_cookie_header("", 0))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _public_config_payload(self) -> dict:
            cfg = self._config_payload()
            return {
                "brand": cfg.get("brand") or "WhatsAYA",
                "assistant_name": cfg.get("assistant_name") or "AYA",
                "theme": cfg.get("theme") or {},
            }

        def _login_page(self):
            """login.html com a marca do cliente já no HTML: sem esperar o JS
            buscar a config, e sem a marca do produto piscando antes."""
            target = STATIC_DIR / "login.html"
            if not target.is_file():
                return self._json({"error": "not found"}, 404)
            brand = html_lib.escape(str(self._public_config_payload()["brand"]))
            page = target.read_text(encoding="utf-8")
            page = page.replace("<title>Login · WhatsAYA</title>", f"<title>Login · {brand}</title>")
            page = page.replace('<span id="brand-title-text">WhatsAYA</span>', f'<span id="brand-title-text">{brand}</span>')
            self._bytes(page.encode("utf-8"), "text/html; charset=utf-8", cache="no-cache")

        def _handle_login(self):
            content_type = self.headers.get("Content-Type", "")
            is_json = "application/json" in content_type
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                return self._json({"ok": False, "error": "corpo grande demais"}, 400)
            raw = self.rfile.read(length) if length > 0 else b""
            username = ""
            password = ""
            if is_json:
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    data = {}
                username = str(data.get("username") or "").strip()
                password = str(data.get("password") or "")
            else:
                try:
                    data = parse_qs(raw.decode("utf-8", errors="replace"))
                except Exception:
                    data = {}
                username = (data.get("username", [""])[0] or "").strip()
                password = data.get("password", [""])[0] or ""

            valid_user = hmac.compare_digest(username, config.username)
            valid_pass = hmac.compare_digest(password, config.password)

            if valid_user and valid_pass:
                token = _create_session()
                cookie_hdr = self._build_cookie_header(token, SESSION_TTL_S)
                if is_json:
                    resp_body = json.dumps({"ok": True, "redirect": "/"}).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Set-Cookie", cookie_hdr)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                else:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", cookie_hdr)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
            else:
                if is_json:
                    resp_body = json.dumps({
                        "ok": False,
                        "error": "Usuário ou senha incorretos.",
                    }).encode("utf-8")
                    self.send_response(HTTPStatus.UNAUTHORIZED)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                else:
                    self.send_response(HTTPStatus.FOUND)
                    self.send_header("Location", "/login?error=invalid")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()

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

        def _redirect(self, location: str):
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _oauth_redirect_uri(self) -> str:
            if config.public_url:
                return config.public_url + "/api/calendar/oauth/callback"
            proto = self.headers.get("X-Forwarded-Proto") or "https"
            host = self.headers.get("Host") or ""
            return f"{proto}://{host}/api/calendar/oauth/callback"

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
            url = urlsplit(self.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            period = query.get("period") if query.get("period") in panel_data.PERIOD_DAYS else "7d"
            route = url.path

            # ── rotas públicas ──
            if route == "/login":
                if self._authorized():
                    return self._redirect("/")
                return self._login_page()
            if route == "/logout":
                return self._logout()
            if route == "/favicon.ico":
                return self._static("favicon.ico")
            if route.startswith("/static/"):
                return self._static(route[len("/static/"):])
            if route == "/api/public-config":
                return self._json(self._public_config_payload())

            # ── rotas protegidas ──
            if not self._authorized():
                if route.startswith("/api/"):
                    return self._deny()
                accept = self.headers.get("Accept", "")
                if "text/html" in accept or route in ("/", "/index.html"):
                    return self._redirect("/login")
                return self._deny()

            try:
                if route == "/" or route == "/index.html":
                    return self._static("index.html")
                if route == "/api/config":
                    return self._json(self._config_payload())
                if route == "/api/status":
                    payload = build_status(bridge)
                    if supervisor is not None:
                        payload["pairing"] = supervisor.snapshot()
                    return self._json(payload)
                if route == "/api/whatsapp-settings":
                    return self._json(build_whatsapp_settings(bridge))
                if route == "/api/qr.png":
                    got = bridge.get_bytes("/whatsapp/qr?format=png")
                    if got is None:
                        return self._json({"error": "qr_unavailable"}, 404)
                    return self._bytes(got[0], got[1])
                if route == "/api/metrics":
                    pipeline_id = panel_data.pipeline_from_config(_custom_config())
                    return self._json(panel_data.metrics(
                        paths, period, minutes_per_resolved=config.minutes_per_resolved,
                        pipeline_id=pipeline_id, owner_number=config.owner_number,
                    ))
                if route == "/api/leads":
                    pipeline_id = panel_data.pipeline_from_config(_custom_config())
                    return self._json(panel_data.leads(paths, pipeline_id=pipeline_id))
                if route.startswith("/api/lead/"):
                    chat_id = unquote(route[len("/api/lead/"):]).strip()
                    if not chat_id:
                        return self._json({"error": "not found"}, 404)
                    pipeline_id = panel_data.pipeline_from_config(_custom_config())
                    detail = panel_data.lead_detail(paths, chat_id, lid_map=lid_map(bridge), pipeline_id=pipeline_id)
                    detail["silence"] = build_chat_silence(bridge, chat_id)
                    return self._json(detail)
                if route == "/api/followups":
                    return self._json(panel_data.followups(paths, period))
                if route == "/api/reactivation":
                    custom = _custom_config()
                    pipeline_id = panel_data.pipeline_from_config(custom)
                    label = _reactivation_config(custom)["label"]
                    return self._json(panel_data.reactivation(paths, label=label, pipeline_id=pipeline_id))
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
                    return self._json({"blocked": panel_data.blocked_contacts(contacts, lid_map(bridge)), "recent": recent})
                if route == "/api/usage":
                    return self._json(panel_data.usage(paths, period))
                if route == "/api/health":
                    return self._json({"ok": True, "now": datetime.now(timezone.utc).isoformat()})
                if route == "/api/calendar/status":
                    cfg = calendar_config.load_calendar_config()
                    payload = calendar_service.calendar_status(
                        cfg, calendar_token_store,
                        oauth_configured=_oauth_configured(),
                        verify=lambda: _probe(cfg),
                    )
                    payload["redirect_uri"] = self._oauth_redirect_uri()
                    return self._json(payload)
                if route == "/api/calendar/events":
                    cfg = calendar_config.load_calendar_config()
                    try:
                        start, end = _parse_calendar_range(query, cfg)
                    except ValueError as exc:
                        return self._json({"error": "bad_range", "detail": str(exc)}, 400)
                    if not cfg.enabled or not calendar_token_store.ready():
                        state = calendar_service.calendar_status(
                            cfg, calendar_token_store, oauth_configured=_oauth_configured(),
                        )["state"]
                        return self._json(
                            {"error": "calendar_not_ready", "state": state, "detail": "A agenda ainda não está pronta."},
                            409,
                        )
                    service = calendar_service.CalendarService(cfg, calendar_token_store, http=calendar_http)
                    try:
                        raw_items = service.list_events(start, end)
                    except calendar_service.CalendarAuthError as exc:
                        return self._json(
                            {"error": "calendar_not_ready", "state": exc.code, "detail": str(exc)}, 409,
                        )
                    except calendar_service.CalendarServiceError as exc:
                        return self._json({"error": "calendar_unavailable", "detail": str(exc)}, 503)
                    events = calendar_service.sanitized_events(raw_items, cfg)
                    counts = {"aya": 0, "external": 0}
                    for event in events:
                        counts[event["source"]] = counts.get(event["source"], 0) + 1
                    return self._json({
                        "timezone": cfg.timezone,
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                        "events": events,
                        "counts": counts,
                    })
                if route == "/api/calendar/settings":
                    cfg = calendar_config.load_calendar_config()
                    custom = _custom_config()
                    source = "file" if isinstance(custom.get("calendar"), dict) else "defaults"
                    return self._json({"settings": cfg.to_public_dict(), "source": source})
                if route == "/api/calendar/oauth/start":
                    client_id, client_secret = _oauth_credentials()
                    if not client_id or not client_secret:
                        return self._json(
                            {
                                "error": "oauth_not_configured",
                                "detail": "Configure GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no servidor, "
                                          "ou gere o token pelo terminal (deploy/scripts/authorize_google.py).",
                            },
                            409,
                        )
                    saved = calendar_token_store.load()
                    raw_scopes = saved.get("scopes")
                    if raw_scopes is None:
                        raw_scopes = saved.get("scope") or []
                    extra_scopes = raw_scopes.split() if isinstance(raw_scopes, str) else [str(s) for s in raw_scopes]
                    state = calendar_service.oauth_state_token()
                    _register_oauth_state(state)
                    url = calendar_service.oauth_authorization_url(
                        client_id=client_id,
                        redirect_uri=self._oauth_redirect_uri(),
                        state=state,
                        extra_scopes=extra_scopes,
                    )
                    return self._redirect(url)
                if route == "/api/calendar/oauth/callback":
                    if query.get("error"):
                        return self._redirect(_agenda_redirect("denied"))
                    state = query.get("state") or ""
                    if not state or not _consume_oauth_state(state):
                        return self._redirect(_agenda_redirect("invalid_state"))
                    code = query.get("code") or ""
                    client_id, client_secret = _oauth_credentials()
                    try:
                        token_response = calendar_service.oauth_exchange_code(
                            code=code,
                            client_id=client_id,
                            client_secret=client_secret,
                            redirect_uri=self._oauth_redirect_uri(),
                            http=calendar_http,
                        )
                    except calendar_service.CalendarAuthError:
                        return self._redirect(_agenda_redirect("exchange_failed"))
                    try:
                        calendar_token_store.save_authorized(
                            token_response, client_id=client_id, client_secret=client_secret,
                        )
                    except calendar_service.CalendarAuthError as exc:
                        return self._redirect(_agenda_redirect(exc.code))
                    except Exception:
                        return self._redirect(_agenda_redirect("save_failed"))
                    _probe_cache.clear()
                    return self._redirect("/#agenda?connected=1")
            except Exception as exc:  # o painel nunca derruba; devolve o erro
                return self._json({"error": type(exc).__name__, "detail": str(exc)[:200]}, 500)
            return self._json({"error": "not found"}, 404)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 64 * 1024:
                raise ValueError("corpo grande demais")
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8") or "{}")
            return body if isinstance(body, dict) else {}

        def do_POST(self):
            route = urlsplit(self.path).path
            if route == "/api/login":
                return self._handle_login()
            if route == "/api/logout":
                return self._logout()
            if not self._authorized():
                return self._deny()
            if not route.startswith("/api/actions/"):
                return self._json({"error": "not found"}, 404)
            try:
                body = self._read_json_body()
            except (ValueError, UnicodeDecodeError) as exc:
                return self._json({"error": "bad_request", "detail": str(exc)[:200]}, 400)
            action = route[len("/api/actions/"):]
            try:
                if action == "block":
                    result = panel_actions.block(
                        paths, chat_id=str(body.get("chat_id") or ""), query=str(body.get("query") or body.get("name") or ""),
                        owner_number=config.owner_number,
                    )
                elif action == "unblock":
                    result = panel_actions.unblock(paths, chat_id=str(body.get("chat_id") or ""))
                elif action == "stage":
                    pipeline_id = panel_data.pipeline_from_config(_custom_config())
                    result = panel_actions.set_stage(
                        paths, chat_id=str(body.get("chat_id") or ""), stage=str(body.get("stage") or ""),
                        pipeline_id=pipeline_id,
                    )
                elif action == "value":
                    result = panel_actions.set_estimated_value(
                        paths, chat_id=str(body.get("chat_id") or ""), value_brl=body.get("value_brl"),
                    )
                elif action == "followup":
                    result = panel_actions.followup(paths, chat_id=str(body.get("chat_id") or ""), action=str(body.get("action") or ""))
                elif action == "pause":
                    result = panel_actions.pause(bridge, paused=body.get("paused"))
                elif action == "whatsapp-settings":
                    result = panel_actions.whatsapp_settings(
                        bridge,
                        reject_calls=body.get("reject_calls"),
                        groups_enabled=body.get("groups_enabled"),
                        debounce_seconds=body.get("debounce_seconds"),
                    )
                elif action == "start-pairing":
                    if supervisor is not None:
                        result = supervisor.request_start()
                    else:
                        result = dashboard.start_pairing(
                            mode=config.whatsapp_mode,
                            allowed_users=config.whatsapp_allowed_users,
                        )
                elif action == "silence":
                    result = panel_actions.silence(bridge, chat_id=str(body.get("chat_id") or ""), minutes=body.get("minutes"))
                elif action == "unsilence":
                    result = panel_actions.unsilence(bridge, chat_id=str(body.get("chat_id") or ""))
                elif action == "reactivation_prepare":
                    default_label = _reactivation_config(_custom_config())["label"]
                    result = panel_actions.reactivation_prepare(
                        paths, bridge, label=str(body.get("label") or "").strip() or default_label,
                        owner_number=config.owner_number,
                    )
                elif action == "reactivation_suggest":
                    result = panel_actions.reactivation_suggest(paths, chat_id=str(body.get("chat_id") or ""))
                elif action == "reactivation_message":
                    result = panel_actions.reactivation_message(
                        paths, chat_id=str(body.get("chat_id") or ""), message=str(body.get("message") or ""),
                    )
                elif action == "reactivation_sent":
                    result = panel_actions.reactivation_sent(
                        paths, chat_id=str(body.get("chat_id") or ""), sent=body.get("sent"),
                    )
                elif action == "calendar-settings":
                    current = {
                        k: v for k, v in calendar_config.load_calendar_config().to_public_dict().items()
                        if k in calendar_config.EDITABLE_FIELDS
                    }
                    unknown = [k for k in body if k not in calendar_config.EDITABLE_FIELDS]
                    if unknown:
                        raise panel_actions.ActionError(f"campo desconhecido: {unknown[0]}")
                    merged = {**current, **{k: v for k, v in body.items() if k in calendar_config.EDITABLE_FIELDS}}
                    try:
                        cfg = calendar_config.save_calendar_settings(merged, path=CONFIG_PATH)
                    except calendar_config.CalendarConfigError as exc:
                        raise panel_actions.ActionError(str(exc)) from exc
                    _probe_cache.clear()
                    result = {"settings": cfg.to_public_dict()}
                else:
                    return self._json({"error": "not found"}, 404)
            except panel_actions.ActionError as exc:
                return self._json({"error": "rejected", "detail": str(exc)}, 400)
            except PairingStartError as exc:
                return self._json({"error": "pairing_unavailable", "detail": str(exc)}, 503)
            except Exception as exc:
                return self._json({"error": type(exc).__name__, "detail": str(exc)[:200]}, 500)
            return self._json({"ok": True, **result})

        def _config_payload(self) -> dict:
            custom = _custom_config()
            preset = panel_data.pipeline_from_config(custom)
            payload = {
                "brand": custom.get("brand") or "WhatsAYA",
                # Nome do atendimento automatizado como o cliente o chama: as telas
                # usam isto em vez de "AYA" fixo.
                "assistant_name": custom.get("assistant_name") or "AYA",
                "theme": custom.get("theme") or {},
                "minutes_per_resolved": config.minutes_per_resolved,
                "hourly_rate_brl": config.hourly_rate_brl,
                "features": custom.get("features") or {},
                "subscription": build_subscription(custom),
                "pipeline": {
                    "id": preset["id"],
                    "stages": [
                        {"id": sid, "label": label, "terminal": terminal}
                        for sid, label, _engine_stage, terminal in preset["stages"]
                    ],
                    "commercial_metrics": bool(preset.get("commercial_metrics")),
                    "excluded_label": (preset.get("imported") or {}).get("excluded_label") or "fora do funil",
                },
                "reactivation": _reactivation_config(custom),
                "calendar": {"enabled": calendar_config.load_calendar_config().enabled},
            }
            if preset.get("session_price_brl") is not None:
                payload["session_price_brl"] = preset["session_price_brl"]
            return payload

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
    paths = paths_from_env()
    bridge = BridgeClient(config.bridge_url, config.bridge_host_header)
    dashboard = HermesDashboardClient(config.hermes_dashboard_url, config.username, config.password)
    auto_start = (os.environ.get("WHATSAPP_PANEL_AUTO_PAIR") or "true").lower() not in {"0", "false", "no"}
    supervisor = PairingSupervisor(
        dashboard=dashboard,
        status_fn=lambda: build_status(bridge),
        state_path=Path(paths.followups_db).parent / "panel_pairing.json",
        mode=config.whatsapp_mode,
        allowed_users=config.whatsapp_allowed_users,
        auto_start=auto_start,
    )
    supervisor.start()
    print(f"[painel] supervisor de pareamento ativo (auto={auto_start})", flush=True)
    server = PanelServer((host, port), make_handler(config, paths, bridge, supervisor))
    print(f"[painel] no ar em http://{host}:{port} · bridge={config.bridge_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
