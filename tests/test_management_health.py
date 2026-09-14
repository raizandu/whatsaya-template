from __future__ import annotations

import io
import json
import tempfile
import urllib.error
import unittest
from datetime import UTC, datetime
from pathlib import Path

import management_health
import management_store


class _Response:
    def __init__(self, payload: object):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _Opener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return _Response(self.outcome)


class ManagementHealthTest(unittest.TestCase):
    key = "a" * 64
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)

    def test_poll_uses_bearer_and_normalizes_healthy_response(self):
        opener = _Opener({
            "ok": True,
            "service": "whatsaya",
            "release_ref": "v1.2.3",
            "whatsapp": {"connection": "connected"},
        })
        result = management_health.poll(
            "http://127.0.0.1:9120/", self.key, opener=opener, now=self.now, allow_http=True,
        )
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["checked_utc"], "2026-09-13T12:00:00+00:00")
        self.assertEqual(opener.request.full_url, "http://127.0.0.1:9120/api/health")
        self.assertEqual(opener.request.get_header("Authorization"), f"Bearer {self.key}")
        self.assertNotIn(self.key, str(result))

    def test_degraded_and_incompatible_responses_are_distinct(self):
        degraded = management_health.poll(
            "https://cliente.example", self.key,
            opener=_Opener({"ok": False, "service": "whatsaya"}), now=self.now,
        )
        invalid = management_health.poll(
            "https://cliente.example", self.key,
            opener=_Opener({"ok": True, "service": "outro"}), now=self.now,
        )
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(invalid["status"], "invalid_response")

    def test_auth_and_network_failures_become_safe_states(self):
        unauthorized_error = urllib.error.HTTPError(
            "https://cliente.example/api/health", 403, "Forbidden", {}, io.BytesIO(b"secret upstream body"),
        )
        network_error = urllib.error.URLError("hostname with internal detail")
        unauthorized = management_health.poll(
            "https://cliente.example", self.key, opener=_Opener(unauthorized_error), now=self.now,
        )
        unreachable = management_health.poll(
            "https://cliente.example", self.key, opener=_Opener(network_error), now=self.now,
        )
        self.assertEqual(unauthorized["status"], "unauthorized")
        self.assertEqual(unreachable["status"], "unreachable")
        self.assertNotIn("internal detail", str(unreachable))

    def test_requires_https_and_strong_key(self):
        with self.assertRaisesRegex(management_health.HealthConfigError, "https"):
            management_health.poll("http://cliente.example", self.key)
        with self.assertRaisesRegex(management_health.HealthConfigError, "32"):
            management_health.poll("https://cliente.example", "curta")

    def test_monitor_ticks_configured_clients_and_persists_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "management.db"
            client = management_store.create_client(
                db,
                name="Marina Costa",
                status="active",
                environment_url="https://painel-marina.example",
                health_api_key=self.key,
            )
            calls = []

            def fake_poll(url, key):
                calls.append((url, key))
                return {
                    "status": "healthy",
                    "detail": None,
                    "checked_utc": "2026-09-13T12:00:00+00:00",
                    "payload": {"service": "whatsaya", "ok": True},
                }

            monitor = management_health.HealthMonitor(db, poll_fn=fake_poll)

            self.assertEqual(monitor.tick(), 1)
            self.assertEqual(calls, [("https://painel-marina.example", self.key)])
            saved = management_store.get_client(db, client["id"])
            self.assertEqual(saved["health_status"], "healthy")
            self.assertEqual(saved["health_payload"], {"service": "whatsaya", "ok": True})

    def test_monitor_rejects_intervals_below_one_minute(self):
        with self.assertRaisesRegex(ValueError, "60 segundos"):
            management_health.HealthMonitor("management.db", interval_seconds=59)


if __name__ == "__main__":
    unittest.main()
