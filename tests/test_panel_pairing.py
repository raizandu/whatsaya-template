from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "panel" / "pairing.py"
SPEC = importlib.util.spec_from_file_location("panel_pairing", MODULE_PATH)
assert SPEC and SPEC.loader
panel_pairing = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel_pairing
SPEC.loader.exec_module(panel_pairing)

SERVER_MODULE_PATH = Path(__file__).resolve().parents[1] / "panel" / "server.py"
SERVER_SPEC = importlib.util.spec_from_file_location("panel_server", SERVER_MODULE_PATH)
assert SERVER_SPEC and SERVER_SPEC.loader
panel_server = importlib.util.module_from_spec(SERVER_SPEC)
sys.modules[SERVER_SPEC.name] = panel_server
SERVER_SPEC.loader.exec_module(panel_server)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _Opener:
    def __init__(self, payloads: list[dict]):
        self.payloads = iter(payloads)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        return _Response(next(self.payloads))


class FakeDashboard:
    """Dublê de HermesDashboardClient com respostas roteirizadas por método.
    Cada entrada de `script[method]` é um dict (devolvido) ou uma Exception
    (levantada). `login` não precisa de roteiro: por padrão só devolve um
    opener bobo."""

    def __init__(self, **script):
        self._script = {name: list(values) for name, values in script.items()}
        self.calls: list[tuple] = []

    def _next(self, method: str):
        queue = self._script.get(method)
        if not queue:
            raise AssertionError(f"sem resposta roteirizada para {method!r}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def login(self):
        self.calls.append(("login",))
        if self._script.get("login"):
            return self._next("login")
        return object()

    def start(self, opener, *, mode, allowed_users):
        self.calls.append(("start", mode, allowed_users))
        return self._next("start")

    def get(self, opener, pairing_id):
        self.calls.append(("get", pairing_id))
        return self._next("get")

    def apply(self, opener, pairing_id, *, mode, allowed_users):
        self.calls.append(("apply", pairing_id, mode, allowed_users))
        return self._next("apply")

    def gateway_start(self, opener):
        self.calls.append(("gateway_start",))
        if self._script.get("gateway_start"):
            return self._next("gateway_start")
        return {"ok": True}

    def calls_of(self, method: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == method]


class FakeClock:
    def __init__(self, start: float = 1_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StatusBox:
    """status_fn roteirizável: os testes mutam `.value` entre ticks."""

    def __init__(self, **initial):
        self.value = dict(initial)

    def __call__(self) -> dict:
        return dict(self.value)


class PairingSupervisorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_path = Path(self._tmpdir.name) / "panel_pairing.json"
        self.clock = FakeClock()

    def _write_state(self, **fields) -> None:
        base = {
            "pairing": None,
            "applied_utc": None,
            "last_connection": "unknown",
            "last_start_ts": 0.0,
            "unreachable_since_ts": None,
            "updated_utc": None,
        }
        base.update(fields)
        self.state_path.write_text(json.dumps(base), encoding="utf-8")

    def _supervisor(self, dashboard, status_fn, **overrides):
        kwargs = dict(
            dashboard=dashboard,
            status_fn=status_fn,
            state_path=self.state_path,
            mode="bot",
            allowed_users="*",
            auto_start=True,
            cooldown=30.0,
            unreachable_grace=60.0,
            sleep=lambda _s: None,
            clock=self.clock,
            log=lambda _msg: None,
        )
        kwargs.update(overrides)
        return panel_pairing.PairingSupervisor(**kwargs)

    def _persisted(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    # 1. resume após restart -----------------------------------------------
    def test_resume_after_restart_applies_persisted_pairing(self):
        self._write_state(pairing={
            "pairing_id": "pair-old",
            "mode": "self-chat",
            "allowed_users": "5511999999999",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": 500.0,
            "last_status": "waiting",
            "last_error": None,
        })
        dashboard = FakeDashboard(apply=[{"ok": True}])
        status = StatusBox(bridge="up", connected=True, connection="connected", qr_available=False)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()

        apply_calls = dashboard.calls_of("apply")
        self.assertEqual(len(apply_calls), 1)
        _, pairing_id, mode, allowed_users = apply_calls[0]
        self.assertEqual(pairing_id, "pair-old")
        self.assertEqual(mode, "self-chat")
        self.assertEqual(allowed_users, "5511999999999")
        self.assertIsNone(supervisor.state["pairing"])
        self.assertIsNotNone(supervisor.state["applied_utc"])
        persisted = self._persisted()
        self.assertIsNone(persisted["pairing"])
        self.assertIsNotNone(persisted["applied_utc"])

    # 2. waiting mantém o registro -------------------------------------------
    def test_waiting_keeps_record_and_does_not_start_another(self):
        self._write_state(pairing={
            "pairing_id": "pair-1",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now,
            "last_status": "starting",
            "last_error": None,
        })
        dashboard = FakeDashboard(get=[{"status": "waiting"}])
        status = StatusBox(bridge="up", connected=False, connection="waiting", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()

        self.assertIsNotNone(supervisor.state["pairing"])
        self.assertEqual(supervisor.state["pairing"]["last_status"], "waiting")
        self.assertEqual(dashboard.calls_of("start"), [])

    # 3. expirado (PairingGone) -> só reinicia depois da folga -------------
    def test_expired_pairing_waits_cooldown_and_grace_before_new_start(self):
        self._write_state(pairing={
            "pairing_id": "pair-expired",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now,
            "last_status": "waiting",
            "last_error": None,
        })
        dashboard = FakeDashboard(
            get=[panel_pairing.PairingGone("expirou")],
            start=[{"pairing_id": "pair-new", "status": "starting"}],
        )
        status = StatusBox(bridge="unreachable", connected=False, connection="unknown", qr_available=False)
        supervisor = self._supervisor(dashboard, status, cooldown=30.0, unreachable_grace=60.0)

        supervisor.tick()  # limpa o registro expirado, mas ainda não é hora de reiniciar
        self.assertIsNone(supervisor.state["pairing"])
        self.assertEqual(dashboard.calls_of("start"), [])

        self.clock.advance(30)  # passou o cooldown mas não a folga de "sem sessão"
        supervisor.tick()
        self.assertEqual(dashboard.calls_of("start"), [])

        self.clock.advance(31)  # agora passou os 60s de folga também
        supervisor.tick()
        self.assertEqual(len(dashboard.calls_of("start")), 1)
        self.assertIsNotNone(supervisor.state["pairing"])
        self.assertEqual(supervisor.state["pairing"]["pairing_id"], "pair-new")

    # 4. ponte de pé com QR de terceiros -> nunca inicia sozinho ------------
    def test_bridge_up_with_qr_available_never_auto_starts(self):
        dashboard = FakeDashboard()
        status = StatusBox(bridge="up", connected=False, connection="waiting", qr_available=True)
        supervisor = self._supervisor(dashboard, status, cooldown=1.0, unreachable_grace=1.0)

        for _ in range(5):
            self.clock.advance(5)
            supervisor.tick()

        self.assertEqual(dashboard.calls_of("start"), [])
        self.assertIsNone(supervisor.state["pairing"])

    # 5. já conectado sem registro -> reconcilia uma vez só -----------------
    def test_connected_with_no_record_reconciles_once(self):
        dashboard = FakeDashboard(
            start=[{"pairing_id": "pair-existing", "status": "connected"}],
            apply=[{"ok": True}],
        )
        status = StatusBox(bridge="up", connected=True, connection="connected", qr_available=False)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()
        self.assertIsNotNone(supervisor.state["applied_utc"])
        self.assertEqual(len(dashboard.calls_of("start")), 1)
        self.assertEqual(len(dashboard.calls_of("apply")), 1)

        calls_before = len(dashboard.calls)
        supervisor.tick()
        self.assertEqual(len(dashboard.calls), calls_before)

    # 6. já conectado e já aplicado -> não faz nada --------------------------
    def test_connected_with_applied_utc_does_nothing(self):
        self._write_state(applied_utc="2026-01-01T00:00:00+00:00")
        dashboard = FakeDashboard()
        status = StatusBox(bridge="up", connected=True, connection="connected", qr_available=False)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()

        self.assertEqual(dashboard.calls, [])

    # 7. hermes fora do ar ao consultar -> mantém registro, não quebra ------
    def test_hermes_unreachable_during_get_keeps_record(self):
        self._write_state(pairing={
            "pairing_id": "pair-1",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now,
            "last_status": "waiting",
            "last_error": None,
        })
        dashboard = FakeDashboard(get=[panel_pairing.PairingStartError("hermes fora do ar")])
        status = StatusBox(bridge="unreachable", connected=False, connection="unknown", qr_available=False)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()  # não deve levantar

        self.assertIsNotNone(supervisor.state["pairing"])
        self.assertEqual(supervisor.state["pairing"]["pairing_id"], "pair-1")

    # 8. request_start manual -------------------------------------------------
    def test_request_start_already_waiting_then_idle_starts(self):
        self._write_state(pairing={
            "pairing_id": "pair-1",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now - 10,
            "last_status": "waiting",
            "last_error": None,
        })
        dashboard = FakeDashboard()
        status = StatusBox(bridge="up", connected=False, connection="waiting", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        result = supervisor.request_start()
        self.assertEqual(result, {"status": "already_waiting"})
        self.assertEqual(dashboard.calls_of("start"), [])

        supervisor.state["pairing"] = None
        dashboard._script["start"] = [{"pairing_id": "pair-new", "status": "starting", "expires_at": "later"}]
        result = supervisor.request_start()
        self.assertEqual(result, {"status": "starting", "pairing_id": "pair-new", "expires_at": "later"})
        self.assertIsNotNone(supervisor.state["pairing"])
        self.assertEqual(supervisor.state["pairing"]["pairing_id"], "pair-new")

    # 10. snapshot nunca expõe o pairing_id ----------------------------------
    def test_snapshot_never_contains_pairing_id(self):
        self._write_state(pairing={
            "pairing_id": "super-secret-id",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now,
            "last_status": "waiting",
            "last_error": None,
        })
        dashboard = FakeDashboard()
        status = StatusBox(bridge="up", connected=False, connection="waiting", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        snapshot = supervisor.snapshot()

        self.assertNotIn("pairing_id", json.dumps(snapshot))
        self.assertEqual(snapshot["pairing"]["status"], "waiting")
        self.assertEqual(snapshot["supervisor"], "running")


class HermesDashboardClientTestCase(unittest.TestCase):
    def setUp(self):
        self.client = panel_server.HermesDashboardClient(
            "http://hermes:9119", "admin", "secret-password"
        )

    def test_start_pairing_logs_in_and_posts_start_without_thread(self):
        opener = _Opener([{"ok": True}, {"pairing_id": "pair-test", "status": "starting"}])

        with mock.patch.object(panel_pairing.urllib.request, "build_opener", return_value=opener):
            result = self.client.start_pairing(mode="bot", allowed_users="*")

        self.assertEqual(result, {"pairing_id": "pair-test", "status": "starting"})
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(opener.requests[0][0].full_url.endswith("/auth/password-login"))
        self.assertTrue(opener.requests[1][0].full_url.endswith("/api/messaging/whatsapp/onboarding/start"))
        self.assertEqual(json.loads(opener.requests[1][0].data), {"mode": "bot", "allowed_users": "*"})



class PairingSupervisorSessionTests(PairingSupervisorTestCase):
    """O Hermes limita logins (HTTP 429): a sessão precisa ser reaproveitada."""

    def _waiting_state(self):
        self._write_state(pairing={
            "pairing_id": "pair-1",
            "mode": "bot",
            "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "started_ts": self.clock.now,
            "last_status": "waiting",
            "last_error": None,
        })

    def test_logs_in_once_across_ticks(self):
        self._waiting_state()
        dashboard = FakeDashboard(get=[{"status": "waiting"}] * 3)
        status = StatusBox(bridge="up", connected=False, connection="disconnected", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        for _ in range(3):
            supervisor.tick()
            self.clock.advance(5)

        self.assertEqual(len(dashboard.calls_of("login")), 1)
        self.assertEqual(len(dashboard.calls_of("get")), 3)

    def test_relogins_after_401(self):
        self._waiting_state()
        dashboard = FakeDashboard(get=[panel_pairing.PairingAuthError("sessão expirou"), {"status": "waiting"}])
        status = StatusBox(bridge="up", connected=False, connection="disconnected", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()
        supervisor.tick()

        self.assertEqual(len(dashboard.calls_of("login")), 2)
        self.assertEqual(supervisor.state["pairing"]["pairing_id"], "pair-1")

    def test_outage_is_logged_once_and_recovery_once(self):
        self._waiting_state()
        dashboard = FakeDashboard(get=[panel_pairing.PairingStartError("fora")] * 3 + [{"status": "waiting"}])
        status = StatusBox(bridge="up", connected=False, connection="disconnected", qr_available=True)
        logs: list[str] = []
        supervisor = self._supervisor(dashboard, status, log=logs.append)

        for _ in range(4):
            supervisor.tick()

        self.assertEqual(sum("indisponível" in line for line in logs), 1)
        self.assertEqual(sum("voltou a responder" in line for line in logs), 1)
        self.assertEqual(len(dashboard.calls_of("login")), 1)



class PairingSupervisorApplyLoopTests(PairingSupervisorTestCase):
    """Depois de aplicar, o gateway precisa de tempo pra subir; reaplicar em
    loop foi o bug que derrubou o pareamento real."""

    def test_no_auto_start_during_apply_grace(self):
        self._write_state(applied_utc="2026-01-01T00:00:00+00:00", applied_ts=self.clock.now - 10,
                          unreachable_since_ts=self.clock.now - 120, last_start_ts=0.0)
        dashboard = FakeDashboard(start=[{"pairing_id": "p-late", "status": "waiting"}])
        status = StatusBox(bridge="unreachable", connected=False, connection="unknown", qr_available=False)
        supervisor = self._supervisor(dashboard, status, apply_grace=300.0)

        supervisor.tick()
        self.clock.advance(200); supervisor.tick()

        self.assertEqual(dashboard.calls_of("start"), [])
        self.clock.advance(200); supervisor.tick()  # 410 s depois: carência venceu
        self.assertEqual(len(dashboard.calls_of("start")), 1)

    def test_connected_credentials_are_not_reapplied_within_backoff(self):
        self._write_state(applied_utc="2026-01-01T00:00:00+00:00", applied_ts=self.clock.now - 400,
                          unreachable_since_ts=self.clock.now - 120, last_start_ts=0.0)
        dashboard = FakeDashboard(start=[{"pairing_id": "p-again", "status": "connected"}])
        status = StatusBox(bridge="unreachable", connected=False, connection="unknown", qr_available=False)
        logs: list[str] = []
        supervisor = self._supervisor(dashboard, status, apply_grace=300.0, reapply_backoff=900.0, log=logs.append)

        supervisor.tick()

        self.assertEqual(len(dashboard.calls_of("start")), 1)
        self.assertEqual(dashboard.calls_of("apply"), [])
        self.assertIsNone(supervisor.state["pairing"])
        # sobe o gateway em vez de reaplicar, e não repete o pedido a cada tick
        self.assertEqual(len(dashboard.calls_of("gateway_start")), 1)
        self.assertTrue(any("gateway start solicitado" in line for line in logs))
        self.clock.advance(35); dashboard._script["start"] = [{"pairing_id": "p-again", "status": "connected"}]
        supervisor.tick()
        self.assertEqual(len(dashboard.calls_of("gateway_start")), 1)
        self.clock.advance(120); dashboard._script["start"] = [{"pairing_id": "p-again", "status": "connected"}]
        supervisor.tick()
        self.assertEqual(len(dashboard.calls_of("gateway_start")), 2)

    def test_apply_requests_gateway_start(self):
        self._write_state(pairing={
            "pairing_id": "pair-1", "mode": "bot", "allowed_users": "*",
            "started_utc": "2026-01-01T00:00:00+00:00", "started_ts": self.clock.now,
            "last_status": "waiting", "last_error": None,
        })
        dashboard = FakeDashboard(get=[{"status": "connected"}], apply=[{"ok": True}])
        status = StatusBox(bridge="up", connected=False, connection="disconnected", qr_available=True)
        supervisor = self._supervisor(dashboard, status)

        supervisor.tick()

        self.assertEqual(len(dashboard.calls_of("apply")), 1)
        self.assertEqual(len(dashboard.calls_of("gateway_start")), 1)
        self.assertIsNotNone(supervisor.state["applied_ts"])

    def test_applied_ts_survives_restart(self):
        self._write_state(applied_utc="2026-01-01T00:00:00+00:00", applied_ts=123.5)
        dashboard = FakeDashboard()
        status = StatusBox(bridge="up", connected=True, connection="connected", qr_available=False)
        supervisor = self._supervisor(dashboard, status)
        self.assertEqual(supervisor.state["applied_ts"], 123.5)


if __name__ == "__main__":
    unittest.main()
