"""Integração com o Google Calendar via chamadas HTTP diretas (stdlib only).

Usado pelo painel (`panel/server.py`), que roda num container sem as libs
Google. Todo acesso à API é feito com `urllib`; o parâmetro `http` de
`TokenStore` e `CalendarService` existe para os testes injetarem um
substituto sem rede.
"""
from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from calendar_config import CalendarConfig, atomic_write_json, token_path

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
AYA_PROPERTY_KEYS = ("whatsayaBookingKey", "therapifyBookingKey")

DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_EVENTS_API_BASE = "https://www.googleapis.com/calendar/v3/calendars"
_TOKEN_REQUEST_TIMEOUT = 10.0
_TOKEN_EXPIRY_MARGIN_SECONDS = 60
_MAX_EVENT_PAGES = 4

_ERR_NOT_CONFIGURED = "O Google Agenda ainda não foi conectado."
_ERR_MISSING_CREDENTIALS = "Credenciais do Google Agenda ausentes na configuração."
_ERR_EXPIRED = "A conexão com o Google Agenda expirou; reconecte."
_ERR_UNAVAILABLE_REFRESH = "Não foi possível renovar a conexão com o Google Agenda."
_ERR_BAD_REFRESH_RESPONSE = "Resposta inválida do Google ao renovar a conexão."
_ERR_NO_REFRESH = (
    "O Google não concedeu acesso permanente à agenda; reconecte e aceite o acesso offline."
)
_ERR_PERMISSION = "Sem permissão para acessar essa agenda no Google."
_ERR_NOT_FOUND = "Agenda não encontrada no Google."
_ERR_UNAVAILABLE = "Google Agenda está indisponível no momento."
_ERR_UPSTREAM = "Falha ao consultar o Google Agenda."
_ERR_OAUTH_FAILED = "Não foi possível concluir a conexão com o Google Agenda."
_ERR_OAUTH_DENIED = "O Google recusou a autorização; tente novamente."
_ERR_OAUTH_BAD_RESPONSE = "Resposta inválida do Google ao concluir a conexão."


class CalendarServiceError(RuntimeError):
    """Erro seguro pra mostrar no painel — nunca carrega credenciais."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


class CalendarAuthError(CalendarServiceError):
    """Falha de autenticação/autorização com o Google."""


def token_has_calendar_scope(payload: Mapping) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if not str(payload.get("refresh_token") or "").strip():
        return False
    raw_scopes = payload.get("scopes")
    if raw_scopes is None:
        raw_scopes = payload.get("scope")
    if isinstance(raw_scopes, str):
        scopes = set(raw_scopes.split())
    elif isinstance(raw_scopes, (list, tuple, set)):
        scopes = {str(item) for item in raw_scopes}
    else:
        scopes = set()
    return CALENDAR_SCOPE in scopes or CALENDAR_EVENTS_SCOPE in scopes


def _default_http(req: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _parse_expiry(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_expiry(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_body(body: bytes) -> dict:
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class TokenStore:
    """Lê/renova o token OAuth salvo em disco, no formato do google-auth."""

    def __init__(self, path: Path, *, http=None, now=None):
        self._path = Path(path)
        self._http = http or _default_http
        self._now = now or (lambda: datetime.now(timezone.utc))

    def load(self) -> dict:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def ready(self) -> bool:
        return token_has_calendar_scope(self.load())

    def access_token(self) -> str:
        payload = self.load()
        cached = self._cached_token(payload)
        if cached is not None:
            return cached
        return self._refresh(payload)

    def _cached_token(self, payload: Mapping) -> str | None:
        if not str(payload.get("refresh_token") or "").strip():
            raise CalendarAuthError("not_configured", _ERR_NOT_CONFIGURED)
        token = str(payload.get("token") or "").strip()
        expiry = _parse_expiry(str(payload.get("expiry") or ""))
        if token and expiry is not None:
            if expiry - timedelta(seconds=_TOKEN_EXPIRY_MARGIN_SECONDS) > self._now():
                return token
        return None

    def _refresh(self, payload: Mapping | None = None) -> str:
        payload = self.load() if payload is None else payload
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if not refresh_token:
            raise CalendarAuthError("not_configured", _ERR_NOT_CONFIGURED)
        client_id = str(payload.get("client_id") or "").strip()
        client_secret = str(payload.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            raise CalendarAuthError("not_configured", _ERR_MISSING_CREDENTIALS)
        token_uri = str(payload.get("token_uri") or "").strip() or DEFAULT_TOKEN_URI

        data = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            token_uri,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            status, body = self._http(req, _TOKEN_REQUEST_TIMEOUT)
        except (CalendarAuthError, CalendarServiceError):
            raise
        except Exception as exc:
            raise CalendarServiceError("unavailable", _ERR_UNAVAILABLE_REFRESH) from exc

        if status in (400, 401):
            raise CalendarAuthError("token_expired", _ERR_EXPIRED)
        if status >= 400:
            raise CalendarServiceError("unavailable", _ERR_UNAVAILABLE_REFRESH)

        parsed = _load_json_body(body)
        new_token = str(parsed.get("access_token") or "").strip()
        if not new_token:
            raise CalendarServiceError("unavailable", _ERR_BAD_REFRESH_RESPONSE)
        try:
            expires_in = int(parsed.get("expires_in"))
        except (TypeError, ValueError):
            expires_in = 3600

        updated = dict(payload)
        updated["token"] = new_token
        updated["expiry"] = _format_expiry(self._now() + timedelta(seconds=expires_in))
        atomic_write_json(self._path, updated)
        return new_token

    def save_authorized(
        self, token_response: Mapping, *, client_id: str, client_secret: str, account: str = ""
    ) -> dict:
        response = dict(token_response or {})
        refresh_token = str(response.get("refresh_token") or "").strip()
        if not refresh_token:
            refresh_token = str(self.load().get("refresh_token") or "").strip()
        if not refresh_token:
            raise CalendarAuthError("no_refresh_token", _ERR_NO_REFRESH)

        access_token = str(response.get("access_token") or response.get("token") or "").strip()
        scope_raw = response.get("scope")
        if scope_raw is None:
            scope_raw = response.get("scopes") or []
        scopes = scope_raw.split() if isinstance(scope_raw, str) else [str(s) for s in scope_raw]
        try:
            expires_in = int(response.get("expires_in"))
        except (TypeError, ValueError):
            expires_in = 3600

        normalized = {
            "token": access_token,
            "refresh_token": refresh_token,
            "token_uri": DEFAULT_TOKEN_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": scopes,
            "expiry": _format_expiry(self._now() + timedelta(seconds=expires_in)),
            "universe_domain": "googleapis.com",
            "account": account,
        }
        atomic_write_json(self._path, normalized)
        return normalized


def _safe_meet_link(raw: Mapping) -> str:
    candidates = [raw.get("hangoutLink")]
    conference = raw.get("conferenceData") or {}
    candidates.extend(
        entry.get("uri")
        for entry in (conference.get("entryPoints") or [])
        if isinstance(entry, dict) and entry.get("entryPointType") == "video"
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value:
            continue
        try:
            parsed = urllib.parse.urlparse(value)
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.netloc.lower() == "meet.google.com" and parsed.path.strip("/"):
            return urllib.parse.urlunparse(("https", "meet.google.com", parsed.path, "", "", ""))
    return ""


def _safe_html_link(raw: Mapping) -> str:
    value = str(raw.get("htmlLink") or "").strip()
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError:
        return ""
    host = parsed.netloc.lower()
    if parsed.scheme == "https" and (host == "google.com" or host.endswith(".google.com")):
        return value
    return ""


def _clean_title(value: str) -> str:
    return " ".join(str(value or "").split())[:120]


def classify_event(raw: Mapping, config: CalendarConfig) -> dict | None:
    if str(raw.get("status") or "").lower() == "cancelled":
        return None
    start = raw.get("start") or {}
    end = raw.get("end") or {}
    all_day = "date" in start
    if all_day:
        start_value = str(start.get("date") or "")
        end_value = str(end.get("date") or "")
    else:
        start_value = str(start.get("dateTime") or "")
        end_value = str(end.get("dateTime") or "")
    if not start_value or not end_value:
        return None

    status = str(raw.get("status") or "confirmed")
    event_id = str(raw.get("id") or "")
    private_props = (raw.get("extendedProperties") or {}).get("private") or {}
    is_aya = isinstance(private_props, Mapping) and any(key in private_props for key in AYA_PROPERTY_KEYS)

    if is_aya:
        return {
            "id": event_id,
            "start": start_value,
            "end": end_value,
            "all_day": all_day,
            "source": "aya",
            "kind": "booking",
            "title": _clean_title(raw.get("summary") or ""),
            "status": status,
            "meet_link": _safe_meet_link(raw),
            "html_link": _safe_html_link(raw),
        }

    summary_lower = str(raw.get("summary") or "").lower()
    if config.slot_keyword.lower() in summary_lower:
        kind, title = "slot", config.slot_keyword
    elif config.block_keyword.lower() in summary_lower:
        kind, title = "block", "Bloqueado"
    else:
        kind, title = "busy", "Ocupado"

    return {
        "id": event_id,
        "start": start_value,
        "end": end_value,
        "all_day": all_day,
        "source": "external",
        "kind": kind,
        "title": title,
        "status": status,
        "meet_link": "",
        "html_link": "",
    }


def _event_sort_key(event: dict) -> tuple[datetime, int]:
    value = event["start"]
    if event["all_day"]:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = datetime.min.replace(tzinfo=timezone.utc)
        return (parsed, 0)
    parsed = _parse_expiry(value) or datetime.min.replace(tzinfo=timezone.utc)
    return (parsed, 1)


def sanitized_events(raw_items: Iterable[Mapping], config: CalendarConfig) -> list[dict]:
    events = [event for event in (classify_event(item, config) for item in raw_items) if event is not None]
    events.sort(key=_event_sort_key)
    return events


class CalendarService:
    def __init__(self, config: CalendarConfig, store: TokenStore, *, http=None, timeout: float = 8.0):
        self._config = config
        self._store = store
        self._http = http or _default_http
        self._timeout = timeout

    def _calendar_url(self, *suffix: str) -> str:
        encoded_id = urllib.parse.quote(self._config.calendar_id, safe="")
        parts = "/".join((encoded_id, *suffix)) if suffix else encoded_id
        return f"{_EVENTS_API_BASE}/{parts}"

    def _get(self, url: str) -> dict:
        already_refreshed = False
        while True:
            token = self._store.access_token()
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            try:
                status, body = self._http(req, self._timeout)
            except (CalendarAuthError, CalendarServiceError):
                raise
            except Exception as exc:
                raise CalendarServiceError("unavailable", _ERR_UNAVAILABLE) from exc

            if status == 200:
                return _load_json_body(body)
            if status == 401 and not already_refreshed:
                already_refreshed = True
                self._store._refresh()
                continue
            if status == 401:
                raise CalendarAuthError("token_expired", _ERR_EXPIRED)
            if status == 403:
                raise CalendarAuthError("permission", _ERR_PERMISSION)
            if status == 404:
                raise CalendarServiceError("calendar_not_found", _ERR_NOT_FOUND)
            if status >= 500:
                raise CalendarServiceError("unavailable", _ERR_UNAVAILABLE)
            raise CalendarServiceError("upstream", _ERR_UPSTREAM)

    def list_events(self, start: datetime, end: datetime) -> list[dict]:
        params = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "maxResults": "250",
            "timeZone": self._config.timezone,
        }
        base = self._calendar_url("events")
        items: list[dict] = []
        page_token = ""
        for _ in range(_MAX_EVENT_PAGES):
            query = dict(params)
            if page_token:
                query["pageToken"] = page_token
            data = self._get(f"{base}?{urllib.parse.urlencode(query)}")
            items.extend(data.get("items") or [])
            page_token = str(data.get("nextPageToken") or "")
            if not page_token:
                break
        return items

    def probe(self) -> dict:
        data = self._get(self._calendar_url())
        return {
            "ok": True,
            "summary": str(data.get("summary") or ""),
            "time_zone": str(data.get("timeZone") or ""),
        }


_STATE_ERROR_MESSAGES = {
    "insufficient_scope": "Reconecte o Google Agenda para liberar o acesso necessário.",
    "token_expired": _ERR_EXPIRED,
    "permission": _ERR_PERMISSION,
    "unavailable": _ERR_UNAVAILABLE,
}


def calendar_status(
    config: CalendarConfig,
    store: TokenStore,
    *,
    oauth_configured: bool,
    verify: Callable[[], dict] | None = None,
) -> dict:
    payload = store.load()
    connected = bool(str(payload.get("refresh_token") or "").strip())
    scopes_ok = token_has_calendar_scope(payload)
    ready = bool(config.enabled and connected and scopes_ok)

    result = {
        "enabled": bool(config.enabled),
        "connected": connected,
        "ready": ready,
        "state": "disabled",
        "account_label": str(payload.get("account") or ""),
        "calendar_id": config.calendar_id,
        "calendar_label": config.calendar_id,
        "timezone": config.timezone,
        "scopes_ok": scopes_ok,
        "oauth_available": bool(oauth_configured),
        "error": "",
    }

    if not config.enabled:
        return result
    if not connected:
        result["state"] = "not_configured"
        return result
    if not scopes_ok:
        result["state"] = "insufficient_scope"
        result["error"] = _STATE_ERROR_MESSAGES["insufficient_scope"]
        return result
    if verify is None:
        result["state"] = "connected"
        return result

    try:
        probed = verify()
    except CalendarAuthError as exc:
        state = exc.code if exc.code in ("token_expired", "permission") else "unavailable"
        result["state"] = state
        result["error"] = _STATE_ERROR_MESSAGES.get(state, _ERR_UNAVAILABLE)
        return result
    except CalendarServiceError:
        result["state"] = "unavailable"
        result["error"] = _ERR_UNAVAILABLE
        return result

    result["state"] = "connected"
    result["calendar_label"] = str(probed.get("summary") or "") or config.calendar_id
    return result


def oauth_authorization_url(
    *, client_id: str, redirect_uri: str, state: str, extra_scopes: Iterable[str] = ()
) -> str:
    scopes = list(dict.fromkeys([CALENDAR_SCOPE, *extra_scopes]))
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{_AUTH_BASE_URL}?{urllib.parse.urlencode(params)}"


def oauth_exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http=None,
    timeout: float = 10.0,
) -> dict:
    do_http = http or _default_http
    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        DEFAULT_TOKEN_URI,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        status, body = do_http(req, timeout)
    except Exception as exc:
        raise CalendarAuthError("oauth_exchange_failed", _ERR_OAUTH_FAILED) from exc

    if status != 200:
        raise CalendarAuthError("oauth_exchange_failed", _ERR_OAUTH_DENIED)

    parsed = _load_json_body(body)
    if not parsed.get("access_token"):
        raise CalendarAuthError("oauth_exchange_failed", _ERR_OAUTH_BAD_RESPONSE)
    return parsed


def oauth_state_token() -> str:
    return secrets.token_urlsafe(32)
