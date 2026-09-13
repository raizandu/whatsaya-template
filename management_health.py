"""Consulta autenticada do health de uma instalação WhatsAYA.

Este módulo pertence ao plano de controle interno: recebe a URL pública do
painel e uma chave exclusiva de monitoramento, faz uma leitura curta e devolve
um resultado sanitizado pronto para persistência. Nunca devolve a chave.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

HEALTH_STATUSES = ("healthy", "degraded", "unreachable", "unauthorized", "invalid_response")


class HealthConfigError(ValueError):
    """Configuração incompleta ou insegura para consultar uma instalação."""


def _health_url(environment_url: str, *, allow_http: bool = False) -> str:
    raw = str(environment_url or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise HealthConfigError("Link do ambiente inválido.") from None
    allowed_schemes = {"https"} | ({"http"} if allow_http else set())
    if parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password:
        scheme_hint = "http ou https" if allow_http else "https"
        raise HealthConfigError(f"Link do ambiente precisa ser uma URL {scheme_hint} válida.")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/health"):
        path += "/api/health"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _stamp(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        raise ValueError("datetime precisa ter timezone")
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _result(status: str, detail: str, *, checked_utc: str, payload: dict | None = None) -> dict:
    return {
        "status": status,
        "detail": str(detail or "")[:500] or None,
        "checked_utc": checked_utc,
        "payload": payload if isinstance(payload, dict) else None,
    }


def poll(
    environment_url: str,
    api_key: str,
    *,
    timeout: float = 6.0,
    opener: Any = None,
    now: datetime | None = None,
    allow_http: bool = False,
) -> dict:
    """Consulta `/api/health`; falha operacional vira estado, não exceção."""
    url = _health_url(environment_url, allow_http=allow_http)
    key = str(api_key or "").strip()
    if len(key) < 32:
        raise HealthConfigError("Chave de health ausente ou curta; use pelo menos 32 caracteres.")

    checked_utc = _stamp(now)
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "WhatsAYA-ControlPlane/1.0",
    })
    client = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with client.open(request, timeout=timeout) as response:
            raw = response.read(64 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return _result("unauthorized", "A instalação recusou a chave de health.", checked_utc=checked_utc)
        return _result("unreachable", f"A instalação respondeu HTTP {exc.code}.", checked_utc=checked_utc)
    except (OSError, TimeoutError, urllib.error.URLError):
        return _result("unreachable", "Não foi possível alcançar a instalação.", checked_utc=checked_utc)

    if len(raw) > 64 * 1024:
        return _result("invalid_response", "Resposta de health grande demais.", checked_utc=checked_utc)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _result("invalid_response", "A instalação não devolveu JSON válido.", checked_utc=checked_utc)
    if not isinstance(payload, dict) or payload.get("service") != "whatsaya":
        return _result("invalid_response", "A resposta não é de uma instalação WhatsAYA compatível.", checked_utc=checked_utc)
    status = "healthy" if payload.get("ok") is True else "degraded"
    detail = None if status == "healthy" else "Painel acessível, mas WhatsApp ou bridge requer atenção."
    return _result(status, detail, checked_utc=checked_utc, payload=payload)
