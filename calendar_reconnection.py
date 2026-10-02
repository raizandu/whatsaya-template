"""Owner reminder for short lived Google Calendar OAuth testing grants.

The delivery marker lives beside, never inside, the OAuth token. A process lock
keeps multiple panel instances from scheduling the same reminder concurrently.
Bridge delivery is best effort: a timeout can leave the remote outcome unknown.
"""
from __future__ import annotations

import fcntl
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

INTERVAL_SECONDS = 60.0
RETRY_SECONDS = 300.0


def _public_agenda_url(raw: str) -> str | None:
    value = str(raw or "").strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        # The alert is sent to the owner outside the authenticated browser
        # session. Only configured HTTPS origins are acceptable here.
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.query or parsed.fragment:
            return None
        return f"{value}/#agenda"
    except ValueError:
        return None


def _expiry_text(value: str, timezone_name: str) -> str:
    stamp = str(value or "").strip()
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        raise ValueError("expiry sem fuso")
    return parsed.astimezone(ZoneInfo(timezone_name)).strftime("%d/%m/%Y às %H:%M")


def reminder_message(status: dict, timezone_name: str, public_url: str) -> str:
    expires = _expiry_text(str(status.get("expires_at") or ""), timezone_name)
    agenda_url = _public_agenda_url(public_url)
    if not agenda_url:
        raise ValueError("URL pública do painel inválida")
    if status.get("state") == "expired":
        timing = f"expirou em {expires}"
    else:
        timing = f"expira em {expires}"
    return (
        f"Oi, Rodrigo! A autorização da agenda Google {timing} (horário de Brasília). "
        f"Reconecte pelo painel para manter a agenda funcionando: {agenda_url}"
    )


class CalendarReconnectionMonitor(threading.Thread):
    """Poll the current calendar config and send one owner reminder per grant."""

    def __init__(
        self,
        *,
        config_loader: Callable[[], Any],
        token_store: Any,
        bridge: Any,
        owner_number: str,
        public_url: str,
        state_path: Path | str,
        interval_seconds: float = INTERVAL_SECONDS,
        retry_seconds: float = RETRY_SECONDS,
        epoch: Callable[[], float] = time.time,
        log: Callable[[str], None] = lambda text: print(text, flush=True),
    ):
        super().__init__(daemon=True, name="calendar-reconnection-monitor")
        self.config_loader = config_loader
        self.token_store = token_store
        self.bridge = bridge
        self.owner_number = "".join(char for char in str(owner_number or "") if char.isdigit())
        self.public_url = public_url
        self.state_path = Path(state_path)
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.retry_seconds = max(1.0, float(retry_seconds))
        self.epoch = epoch
        self.log = log

    def tick(self) -> str:
        """One pass, returning a compact outcome useful for monitoring/tests."""
        cfg = self.config_loader()
        status = self.token_store.reconnection_status(cfg)
        cycle = status.get("authorized_at")
        if not status.get("enabled") or status.get("state") not in ("due", "expired") or not cycle:
            return "not_due"
        if not self.owner_number:
            return "missing_owner"
        try:
            body = reminder_message(status, cfg.timezone, self.public_url)
        except (ValueError, KeyError, TypeError):
            return "invalid_config"

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            state = self._read_state()
            if state.get("delivered_authorized_at") == cycle:
                return "already_delivered"
            retry_after = state.get("retry_after") if state.get("authorized_at") == cycle else None
            try:
                if retry_after and float(retry_after) > self.epoch():
                    return "retry_later"
            except (TypeError, ValueError):
                pass

            # Re-read both config and token under the process lock. If Rodrigo
            # completed OAuth while the first read was in flight, this pass
            # abandons the stale reminder.
            cfg = self.config_loader()
            status = self.token_store.reconnection_status(cfg)
            if (
                not status.get("enabled")
                or status.get("state") not in ("due", "expired")
                or status.get("authorized_at") != cycle
            ):
                return "reconnected"
            try:
                body = reminder_message(status, cfg.timezone, self.public_url)
            except (ValueError, KeyError, TypeError):
                return "invalid_config"

            # Record the retry window before crossing the bridge boundary. If
            # post_json raises after an unknown remote outcome, process restart
            # still observes the backoff instead of sending again next tick.
            self._write_state({
                "authorized_at": cycle,
                "retry_after": self.epoch() + self.retry_seconds,
            })

            result = self.bridge.post_json(
                "/send",
                {
                    "chatId": f"{self.owner_number}@s.whatsapp.net",
                    "message": body,
                    "automation": False,
                },
                timeout=30,
            )
            if isinstance(result, dict) and result.get("success") and result.get("messageId"):
                self._write_state({"delivered_authorized_at": cycle})
                return "delivered"

            # A transport timeout may still have reached WhatsApp, so exactly
            # once cannot be guaranteed by this bridge API. Backoff prevents
            # repeated sends every polling tick after operational failures.
            return "failed"

    def _read_state(self) -> dict:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state(self, payload: dict) -> None:
        from calendar_config import atomic_write_json

        atomic_write_json(self.state_path, payload)

    def run(self) -> None:  # pragma: no cover - tick covers the monitor logic
        while True:
            try:
                self.tick()
            except Exception as exc:
                self.log(f"[calendar] lembrete de reconexão falhou ({type(exc).__name__}); nova tentativa no próximo ciclo")
            time.sleep(self.interval_seconds)
