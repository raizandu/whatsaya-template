"""Pareamento do WhatsApp: cliente do onboarding do Hermes e o supervisor que
mantém o monitoramento vivo enquanto o WhatsApp não está conectado.

O painel nunca expõe o Hermes ao navegador — toda a conversa com
`/api/messaging/whatsapp/onboarding/*` fica aqui, atrás de uma sessão de
cookie obtida com usuário/senha do próprio painel.

O `PairingSupervisor` substitui a thread solta de antes (`_watch_and_apply`,
180 tentativas de 2 s e depois desiste): ele roda o tempo todo que o painel
estiver de pé, guarda o que está fazendo num arquivo de estado (sobrevive a
restart) e pede um QR novo sozinho quando a ponte fica sem sessão e sem
ninguém cuidando dela.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

WAITING_STATUSES = {"starting", "installing", "waiting"}
TERMINAL_STATUSES = {"error", "cancelled", "expired"}
REQUEST_START_STALE_S = 9 * 60


class PairingGone(Exception):
    """A sessão de pareamento não existe mais no Hermes (HTTP 404/410)."""


class PairingStartError(RuntimeError):
    """Hermes inacessível, ou respondeu de um jeito que não dá pra usar."""


class PairingAuthError(PairingStartError):
    """O cookie de sessão do painel não vale mais (HTTP 401): refazer login."""


class HermesDashboardClient:
    """Fala com o onboarding de WhatsApp do Hermes por trás de uma sessão de
    cookie própria do painel. Sem estado entre chamadas: quem chama guarda o
    `opener` (login) e o `pairing_id` enquanto durar o fluxo."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 10.0):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.timeout = timeout

    def _request(self, opener, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise PairingGone(f"pareamento não encontrado (HTTP {exc.code})") from exc
            if exc.code == 401:
                raise PairingAuthError("A sessão com o serviço de conexão expirou.") from exc
            if exc.code == 429:
                raise PairingStartError("O serviço de conexão limitou as tentativas de login.") from exc
            raise PairingStartError("Não foi possível falar com o serviço de conexão.") from exc
        except (OSError, ValueError) as exc:
            raise PairingStartError("Não foi possível falar com o serviço de conexão.") from exc
        if not isinstance(result, dict):
            raise PairingStartError("O serviço de conexão respondeu de forma inválida.")
        return result

    def login(self):
        """Autentica com usuário/senha do painel e devolve um opener com a
        sessão de cookie do Hermes, pronto pras próximas chamadas."""
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(cookies),
        )
        login = self._request(opener, "/auth/password-login", method="POST", body={
            "provider": "basic",
            "username": self.username,
            "password": self.password,
            "next": "/",
        })
        if login.get("ok") is not True:
            raise PairingStartError("Não foi possível autenticar o serviço de conexão.")
        return opener

    def start(self, opener, *, mode: str, allowed_users: str) -> dict:
        """Abre (ou reabre) uma sessão de pareamento. Se `creds.json` já existe
        no Hermes, devolve `status: "connected"` na hora, sem processo novo."""
        normalized_mode = mode if mode in {"bot", "self-chat"} else "bot"
        normalized_users = allowed_users or "*"
        pairing = self._request(
            opener,
            "/api/messaging/whatsapp/onboarding/start",
            method="POST",
            body={"mode": normalized_mode, "allowed_users": normalized_users},
        )
        if not pairing.get("pairing_id"):
            raise PairingStartError("O serviço não criou uma sessão de conexão.")
        return pairing

    def gateway_start(self, opener) -> dict:
        """`hermes gateway start` via dashboard. No container o gateway roda sob
        s6 e sai com código 78 quando não está pareado; o s6 então deixa o
        serviço parado e o `restart` que o `apply` dispara vira um no-op. Só o
        `start` (s6-svc -u) levanta o serviço de novo — sem isso a sessão
        pareada nunca chega ao painel."""
        return self._request(opener, "/api/gateway/start", method="POST", body={})

    def gateway_restart(self, opener) -> dict:
        """`hermes gateway restart` via dashboard. Último recurso do supervisor:
        derruba a ponte junto, então só quando ela já está morta há tempo."""
        return self._request(opener, "/api/gateway/restart", method="POST", body={})

    def get(self, opener, pairing_id: str) -> dict:
        """Levanta `PairingGone` quando o Hermes já esqueceu essa sessão
        (expirou ou nunca existiu)."""
        return self._request(opener, f"/api/messaging/whatsapp/onboarding/{pairing_id}")

    def apply(self, opener, pairing_id: str, *, mode: str, allowed_users: str) -> dict:
        normalized_mode = mode if mode in {"bot", "self-chat"} else "bot"
        normalized_users = allowed_users or "*"
        return self._request(
            opener,
            f"/api/messaging/whatsapp/onboarding/{pairing_id}/apply",
            method="POST",
            body={"mode": normalized_mode, "allowed_users": normalized_users},
        )

    def start_pairing(self, *, mode: str, allowed_users: str) -> dict:
        """Compatibilidade com o botão "Gerar QR Code" quando não há supervisor
        (ex.: testes): login + start numa chamada, sem thread de monitor —
        quem chama decide o que fazer com o pareamento devolvido."""
        opener = self.login()
        return self.start(opener, mode=mode, allowed_users=allowed_users)


def _now_iso(clock: Callable[[], float]) -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat()


class PairingSupervisor(threading.Thread):
    """Thread daemon que mantém o pareamento do WhatsApp vivo.

    Enquanto o WhatsApp não está conectado, monitora o `pairing_id` ativo e
    aplica a sessão assim que ela conecta; quando não há nenhum pareamento em
    andamento e a ponte está sem sessão por tempo demais, pede um QR novo
    sozinha. O estado fica num arquivo (tmp+rename, igual ao
    `contacts_store`), então um restart do painel retoma de onde parou em vez
    de esperar mais 6 minutos como a thread antiga fazia.
    """

    def __init__(
        self,
        *,
        dashboard: HermesDashboardClient,
        status_fn: Callable[[], dict],
        state_path: Path,
        mode: str,
        allowed_users: str,
        auto_start: bool = True,
        interval: float = 5.0,
        cooldown: float = 30.0,
        unreachable_grace: float = 60.0,
        apply_grace: float = 300.0,
        reapply_backoff: float = 900.0,
        restart_after: float = 600.0,
        gateway_nudge_interval: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        log: Callable[[str], None] = lambda msg: print(msg, flush=True),
    ):
        super().__init__(daemon=True, name="pairing-supervisor")
        self.dashboard = dashboard
        self.status_fn = status_fn
        self.state_path = Path(state_path)
        self.mode = mode
        self.allowed_users = allowed_users
        self.auto_start = auto_start
        self.interval = interval
        self.cooldown = cooldown
        self.unreachable_grace = unreachable_grace
        self.apply_grace = apply_grace          # depois de mexer no gateway, dá tempo dele subir
        self.reapply_backoff = reapply_backoff  # intervalo mínimo entre dois restarts do gateway
        self.restart_after = restart_after      # ponte morta há tanto tempo => restart é aceitável
        self.gateway_nudge_interval = gateway_nudge_interval  # `gateway start` no máximo a cada N s
        self._last_gateway_start_ts: float | None = None
        self._sleep = sleep
        self._clock = clock
        self.log = log
        self._lock = threading.RLock()
        self._opener = None  # sessão (cookie) do Hermes, reaproveitada entre ticks
        self._hermes_down = False
        self.state = self._load_state()

    # ── sessão com o Hermes ──────────────────────────────────────────
    def _session(self):
        """Login uma vez e reaproveita o cookie: o Hermes limita tentativas de
        login (HTTP 429), então logar a cada tick derruba a própria consulta."""
        if self._opener is None:
            self._opener = self.dashboard.login()
        return self._opener

    def _drop_session(self) -> None:
        self._opener = None

    def _mark_applied(self, now: float, opener=None) -> None:
        self.state["applied_utc"] = _now_iso(self._clock)
        self.state["applied_ts"] = now
        self.state["pairing"] = None
        self.log("[pareamento] sessão aplicada, gateway reiniciando")
        self._ensure_gateway_up(now, opener, reason="sessão aplicada", force=True)

    def _ensure_gateway_up(self, now: float, opener=None, *, reason: str, force: bool = False) -> None:
        """Pede `gateway start` ao dashboard (idempotente: serviço já de pé é no-op)."""
        last = self._last_gateway_start_ts
        if not force and last is not None and (now - last) < self.gateway_nudge_interval:
            return
        self._last_gateway_start_ts = now
        try:
            self.dashboard.gateway_start(opener or self._session())
            self.log(f"[pareamento] gateway start solicitado ({reason})")
        except PairingAuthError:
            self._drop_session()
        except PairingStartError as exc:
            self.log(f"[pareamento] falha ao pedir gateway start: {exc}")

    def _applied_recently(self, now: float, window: float) -> bool:
        applied_ts = self.state.get("applied_ts")
        return applied_ts is not None and (now - float(applied_ts)) < window

    def _note_hermes_up(self) -> None:
        if self._hermes_down:
            self.log("[pareamento] hermes voltou a responder")
        self._hermes_down = False

    # ── ciclo da thread ────────────────────────────────────────────────
    def run(self) -> None:  # pragma: no cover (exercitado via tick() nos testes)
        while True:
            try:
                self.tick()
            except Exception as exc:  # nunca deixa uma exceção matar o supervisor
                self.log(f"[pareamento] tick falhou: {exc}")
            self._sleep(self.interval)

    # ── uma iteração, sem thread nem sleep — testável direto ────────────
    def tick(self) -> None:
        with self._lock:
            try:
                st = self.status_fn() or {}
            except Exception as exc:
                self.log(f"[pareamento] falha ao consultar status da ponte: {exc}")
                return
            now = self._clock()
            connected = bool(st.get("connected")) or str(st.get("connection")) == "connected"

            if connected:
                self._handle_connected(now)
                self._persist()
                return

            self.state["last_connection"] = "unknown" if st.get("bridge") == "unreachable" else "disconnected"
            self._update_unreachable_timer(st, now)

            pairing = self.state.get("pairing")
            if pairing:
                self._tick_pairing(pairing, now)
            if self.state.get("pairing") is None and self.auto_start:
                self._maybe_start(st, now)
            self._persist()

    # ── conectado ────────────────────────────────────────────────────
    def _handle_connected(self, now: float) -> None:
        self.state["last_connection"] = "connected"
        self.state["unreachable_since_ts"] = None
        pairing = self.state.get("pairing")
        if pairing:
            try:
                self._apply_and_clear(pairing, now)
            except PairingStartError as exc:
                self.log(f"[pareamento] falha ao aplicar sessão conectada: {exc}")
            return
        if self.state.get("applied_utc") is None:
            # Conectado sem pareamento nosso em andamento: a ponte é a do
            # gateway. Em `--pair-only` o bridge encerra 2 s depois de conectar,
            # então "conectado e ninguém aplicou" não é um estado que dure — e
            # o `apply` reinicia o gateway. Foi assim que a produção caiu em
            # 09/09/2026: o supervisor subiu sem estado, viu o WhatsApp
            # conectado e derrubou um gateway saudável para "reconciliar".
            # Se as credenciais existirem e a ponte cair, `_maybe_start` cobre.
            self.state["applied_utc"] = _now_iso(self._clock)
            self.state["applied_ts"] = None
            self.log("[pareamento] ponte já conectada; nada a aplicar")

    def _apply_and_clear(self, pairing: dict, now: float, opener=None) -> None:
        """Aplica o pareamento ativo e limpa o registro. Se o Hermes já
        derrubou a sessão (`PairingGone`), pede uma nova — que volta
        `connected` na hora porque as credenciais já existem — e aplica essa."""
        opener = opener or self._session()
        pairing_id = pairing["pairing_id"]
        mode = pairing.get("mode") or self.mode
        allowed_users = pairing.get("allowed_users") or self.allowed_users
        try:
            self.dashboard.apply(opener, pairing_id, mode=mode, allowed_users=allowed_users)
        except PairingAuthError:
            self._drop_session()
            raise
        except PairingGone:
            result = self.dashboard.start(opener, mode=mode, allowed_users=allowed_users)
            pairing_id = str(result.get("pairing_id") or pairing_id)
            self.dashboard.apply(opener, pairing_id, mode=mode, allowed_users=allowed_users)
        self._mark_applied(now, opener)

    # ── não conectado, pareamento nosso em andamento ────────────────────
    def _tick_pairing(self, pairing: dict, now: float) -> None:
        try:
            opener = self._session()
            result = self.dashboard.get(opener, pairing["pairing_id"])
        except PairingGone as exc:
            self._note_hermes_up()
            self.log(f"[pareamento] sessão de pareamento expirou: {exc}")
            self.state["pairing"] = None
            return
        except PairingAuthError:
            self._drop_session()  # relogin no próximo tick, sem alarde
            return
        except PairingStartError as exc:
            if not self._hermes_down:
                self.log(f"[pareamento] hermes indisponível ao consultar pareamento: {exc}")
            self._hermes_down = True
            return  # mantém o registro, tenta de novo no próximo tick
        self._note_hermes_up()

        status = str(result.get("status") or "")
        if status == "connected":
            try:
                self._apply_and_clear(pairing, now, opener=opener)
            except PairingStartError as exc:
                self.log(f"[pareamento] falha ao aplicar pareamento concluído: {exc}")
            return
        if status in TERMINAL_STATUSES:
            self.log(f"[pareamento] pareamento encerrado (status={status})")
            self.state["pairing"] = None
            return
        pairing["last_status"] = status or pairing.get("last_status")
        self.state["pairing"] = pairing

    # ── não conectado, sem pareamento nosso ──────────────────────────
    def _update_unreachable_timer(self, st: dict, now: float) -> None:
        eligible = st.get("bridge") == "unreachable" or (
            st.get("bridge") == "up" and not bool(st.get("qr_available"))
        )
        if eligible:
            if self.state.get("unreachable_since_ts") is None:
                self.state["unreachable_since_ts"] = now
        else:
            self.state["unreachable_since_ts"] = None

    def _maybe_start(self, st: dict, now: float) -> None:
        since = self.state.get("unreachable_since_ts")
        if since is None or (now - since) < self.unreachable_grace:
            return
        if (now - float(self.state.get("last_start_ts") or 0.0)) < self.cooldown:
            return
        if self._applied_recently(now, self.apply_grace):
            return  # o gateway ainda está subindo com a sessão aplicada
        reason = "ponte inacessível" if st.get("bridge") == "unreachable" else "sessão perdida sem QR"
        self._start_new_pairing(now, reason=reason)

    def _start_new_pairing(self, now: float, *, reason: str) -> dict:
        self.state["last_start_ts"] = now
        try:
            opener = self._session()
            result = self.dashboard.start(opener, mode=self.mode, allowed_users=self.allowed_users)
        except PairingAuthError as exc:
            self._drop_session()
            return {"status": "error", "detail": str(exc)}
        except PairingStartError as exc:
            self.log(f"[pareamento] falha ao pedir novo QR: {exc}")
            return {"status": "error", "detail": str(exc)}

        if result.get("status") == "connected":
            # Credenciais já existem no disco: não há o que aplicar. `apply`
            # reinicia o gateway, e o gateway leva até um minuto para subir
            # (npm install do bridge) — reaplicar nesse meio era o loop de
            # 30 s de antes, e em 09/09/2026 derrubou um gateway que estava
            # justamente subindo. O que pode faltar é o serviço estar de pé.
            self.state["pairing"] = None
            self._recover_gateway(now, opener)
        else:
            self.state["pairing"] = {
                "pairing_id": str(result.get("pairing_id") or ""),
                "mode": self.mode,
                "allowed_users": self.allowed_users,
                "started_utc": _now_iso(self._clock),
                "started_ts": now,
                "last_status": str(result.get("status") or "starting"),
                "last_error": None,
            }
            self.log(f"[pareamento] novo QR solicitado (motivo: {reason})")
        return result

    def _recover_gateway(self, now: float, opener) -> None:
        """Credenciais no disco, ponte fora do ar. Primeiro só levanta o serviço
        (no-op se já está de pé; ele sai com código 78 quando não pareado).
        Reiniciar é o último recurso: só com a ponte morta há `restart_after`
        e no máximo um restart a cada `reapply_backoff`."""
        self._ensure_gateway_up(now, opener, reason="credenciais no disco, ponte fora do ar")
        since = self.state.get("unreachable_since_ts")
        if since is None or (now - float(since)) < self.restart_after:
            return
        if self._applied_recently(now, self.reapply_backoff):
            return
        try:
            self.dashboard.gateway_restart(opener)
        except PairingAuthError:
            self._drop_session()
            return
        except PairingStartError as exc:
            self.log(f"[pareamento] falha ao reiniciar gateway: {exc}")
            return
        self.state["applied_utc"] = _now_iso(self._clock)
        self.state["applied_ts"] = now
        self.log(f"[pareamento] gateway reiniciado (ponte fora do ar há {int(now - float(since))}s)")

    # ── ação manual: botão "Gerar QR Code" ──────────────────────────
    def request_start(self, *, force: bool = True) -> dict:
        with self._lock:
            now = self._clock()
            pairing = self.state.get("pairing")
            if pairing and pairing.get("last_status") in WAITING_STATUSES:
                started_ts = pairing.get("started_ts")
                age = (now - float(started_ts)) if started_ts is not None else REQUEST_START_STALE_S
                if age < REQUEST_START_STALE_S:
                    return {"status": "already_waiting"}
            if not force:
                since = self.state.get("unreachable_since_ts")
                grace_ok = since is not None and (now - since) >= self.unreachable_grace
                cooldown_ok = (now - float(self.state.get("last_start_ts") or 0.0)) >= self.cooldown
                if not (grace_ok and cooldown_ok):
                    return {"status": "already_waiting"}
            result = self._start_new_pairing(now, reason="pedido manual" if force else "pedido programático")
            self._persist()
            return {
                "status": result.get("status"),
                "pairing_id": result.get("pairing_id"),
                "expires_at": result.get("expires_at"),
            }

    # ── snapshot pra /api/status — nunca expõe o pairing_id ao navegador ──
    def snapshot(self) -> dict:
        with self._lock:
            pairing = self.state.get("pairing")
            pairing_payload = None
            if pairing:
                pairing_payload = {
                    "status": pairing.get("last_status"),
                    "started_utc": pairing.get("started_utc"),
                }
            return {
                "supervisor": "running",
                "auto_start": self.auto_start,
                "pairing": pairing_payload,
                "applied_utc": self.state.get("applied_utc"),
                "last_connection": self.state.get("last_connection"),
            }

    # ── estado em disco ──────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        pairing = raw.get("pairing")
        return {
            "pairing": pairing if isinstance(pairing, dict) else None,
            "applied_utc": raw.get("applied_utc"),
            "applied_ts": float(raw["applied_ts"]) if raw.get("applied_ts") is not None else None,
            "last_connection": raw.get("last_connection") or "unknown",
            "last_start_ts": float(raw.get("last_start_ts") or 0.0),
            "unreachable_since_ts": raw.get("unreachable_since_ts"),
            "updated_utc": raw.get("updated_utc"),
        }

    def _persist(self) -> None:
        self.state["updated_utc"] = _now_iso(self._clock)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(f"{self.state_path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.state, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_path)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
