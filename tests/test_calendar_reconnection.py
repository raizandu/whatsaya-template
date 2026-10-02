from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import calendar_config
import calendar_reconnection
import calendar_service


class FakeBridge:
    def __init__(self, results=None):
        self.results = list(results or [{"success": True, "messageId": "msg-1"}])
        self.calls = []

    def post_json(self, path, body, *, timeout=None):
        self.calls.append((path, body, timeout))
        return self.results.pop(0) if self.results else {"success": True, "messageId": "msg-next"}


class CalendarReconnectionTests(unittest.TestCase):
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.token_path = self.root / "google_token.json"
        self.state_path = self.root / "calendar_reconnection_reminder.json"
        self.now = self.anchor
        self.config = calendar_config.CalendarConfig(oauth_testing_mode=True)
        self.bridge = FakeBridge()
        self._save_grant(self.anchor)

    def _save_grant(self, anchor: datetime | None):
        token = {"refresh_token": "refresh-test", "scopes": [calendar_service.CALENDAR_SCOPE]}
        if anchor is not None:
            token["authorized_at"] = anchor.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.token_path.write_text(json.dumps(token), encoding="utf-8")

    def _store(self):
        return calendar_service.TokenStore(self.token_path, now=lambda: self.now)

    def _monitor(self, *, bridge=None, config=None):
        return calendar_reconnection.CalendarReconnectionMonitor(
            config_loader=lambda: config or self.config,
            token_store=self._store(),
            bridge=bridge or self.bridge,
            owner_number="55 11 99999-0000",
            public_url="https://painel.example.com",
            state_path=self.state_path,
            epoch=lambda: self.now.timestamp(),
        )

    def test_sends_only_at_six_day_threshold_to_owner_with_internal_semantics(self):
        self.now = self.anchor + timedelta(days=6) - timedelta(seconds=1)
        self.assertEqual(self._monitor().tick(), "not_due")
        self.assertEqual(self.bridge.calls, [])

        self.now += timedelta(seconds=1)
        self.assertEqual(self._monitor().tick(), "delivered")
        path, body, timeout = self.bridge.calls[0]
        self.assertEqual(path, "/send")
        self.assertEqual(body["chatId"], "5511999990000@s.whatsapp.net")
        self.assertFalse(body["automation"])
        self.assertIn("agenda Google expira em 07/01/2026 às 21:00", body["message"])
        self.assertIn("https://painel.example.com/#agenda", body["message"])
        self.assertEqual(timeout, 30)

    def test_restart_deduplicates_successful_cycle_and_next_grant_can_remind(self):
        self.now = self.anchor + timedelta(days=6)
        self.assertEqual(self._monitor().tick(), "delivered")
        restarted = self._monitor()
        self.assertEqual(restarted.tick(), "already_delivered")
        self.assertEqual(len(self.bridge.calls), 1)

        new_anchor = self.anchor + timedelta(days=6, seconds=1)
        self._save_grant(new_anchor)
        self.now = new_anchor + timedelta(days=6)
        self.assertEqual(restarted.tick(), "delivered")
        self.assertEqual(len(self.bridge.calls), 2)

    def test_concurrent_ticks_deliver_only_once(self):
        self.now = self.anchor + timedelta(days=6)
        entered = threading.Event()
        release = threading.Event()

        class SlowBridge(FakeBridge):
            def post_json(self, path, body, *, timeout=None):
                self.calls.append((path, body, timeout))
                entered.set()
                release.wait(timeout=2)
                return {"success": True, "messageId": "msg-concurrent"}

        bridge = SlowBridge()
        monitor = self._monitor(bridge=bridge)
        results = []
        first = threading.Thread(target=lambda: results.append(monitor.tick()))
        second = threading.Thread(target=lambda: results.append(monitor.tick()))
        first.start()
        self.assertTrue(entered.wait(timeout=2))
        second.start()
        release.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertCountEqual(results, ["delivered", "already_delivered"])
        self.assertEqual(len(bridge.calls), 1)

    def test_expired_is_reminded_once(self):
        self.now = self.anchor + timedelta(days=7)
        self.assertEqual(self._monitor().tick(), "delivered")
        self.assertIn("agenda Google expirou em 07/01/2026 às 21:00", self.bridge.calls[0][1]["message"])

    def test_unknown_missing_anchor_and_disabled_mode_never_send(self):
        self._save_grant(None)
        self.now = self.anchor + timedelta(days=20)
        self.assertEqual(self._monitor().tick(), "not_due")
        self._save_grant(self.anchor)
        self.assertEqual(
            self._monitor(config=calendar_config.CalendarConfig(oauth_testing_mode=False)).tick(),
            "not_due",
        )
        self.assertEqual(self.bridge.calls, [])

    def test_failed_send_uses_five_minute_backoff_then_retries(self):
        self.now = self.anchor + timedelta(days=6)
        failed_bridge = FakeBridge([None, {"success": True, "messageId": "msg-2"}])
        monitor = self._monitor(bridge=failed_bridge)
        self.assertEqual(monitor.tick(), "failed")
        self.assertEqual(monitor.tick(), "retry_later")
        self.assertEqual(len(failed_bridge.calls), 1)
        self.now += timedelta(minutes=5)
        self.assertEqual(monitor.tick(), "delivered")
        self.assertEqual(len(failed_bridge.calls), 2)

    def test_exception_after_attempt_keeps_restart_backoff(self):
        self.now = self.anchor + timedelta(days=6)

        class RaisingBridge(FakeBridge):
            def post_json(self, path, body, *, timeout=None):
                self.calls.append((path, body, timeout))
                raise TimeoutError("remote outcome unknown")

        bridge = RaisingBridge()
        self.assertRaises(TimeoutError, self._monitor(bridge=bridge).tick)
        self.assertEqual(self._monitor(bridge=self.bridge).tick(), "retry_later")
        self.assertEqual(self.bridge.calls, [])

    def test_reconnection_before_delivery_abandons_old_grant(self):
        self.now = self.anchor + timedelta(days=6)
        self._save_grant(self.now)
        self.assertEqual(self._monitor().tick(), "not_due")
        self.assertEqual(self.bridge.calls, [])

    def test_alert_requires_safe_configured_https_base(self):
        monitor = self._monitor()
        monitor.public_url = "http://painel.example.com"
        self.now = self.anchor + timedelta(days=6)
        self.assertEqual(monitor.tick(), "invalid_config")
        self.assertEqual(self.bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
