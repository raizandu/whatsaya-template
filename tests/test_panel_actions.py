"""Escritas do painel: contatos, funil, follow-ups e bridge."""
from __future__ import annotations

import base64
import json
import sqlite3
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "panel"))

import contacts_store  # noqa: E402
from commercial_followups import FollowupEngine  # noqa: E402
from panel import actions as panel_actions  # noqa: E402
from panel import data as panel_data  # noqa: E402
from panel import server as panel_server  # noqa: E402
from tests.test_panel_data import BLOCKED, LEAD, LEAD2, LEAD_LID, NOW, PanelFixture  # noqa: E402

OWNER_DIGITS = "5547999414100"


class FakeBridge:
    """Registra o que o painel pediu ao bridge e responde como o bridge real."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.down = False
        self.silence_down = False
        self.send_response: dict | None = None
        self.settings = {"rejectCalls": False, "groupsEnabled": False, "debounceInitialMs": 8000}

    def get_json(self, path):
        if self.down:
            return None
        if path == "/runtime-settings":
            return {"success": True, "settings": self.settings.copy()}
        return None

    def post_json(self, path, body, timeout=None):
        self.calls.append((path, body))
        if self.down:
            return None
        if path == "/send":
            if self.send_response is not None:
                return self.send_response
            message_id = f"panel-out-{len(self.calls)}"
            return {"success": True, "messageId": message_id, "messageIds": [message_id]}
        if path == "/bot-pause":
            return {"success": True, "botPaused": body["paused"]}
        if path == "/chat-silence":
            if self.silence_down:
                return {"success": False}
            return {"success": True, "chatId": body["chatId"], "silencedUntil": 1, "timeLeftSeconds": 600}
        if path == "/chat-unsilence":
            return {"success": True, "chatId": body["chatId"]}
        if path == "/runtime-settings":
            self.settings = body.copy()
            return {"success": True, "settings": self.settings.copy()}
        return None


class ContactActionsTest(PanelFixture):
    def _contacts(self):
        return contacts_store.read_contacts(self.paths.contacts_json)

    def test_block_by_chat_id_marks_phone_and_lid_and_cancels_followups(self):
        result = panel_actions.block(self.paths, chat_id=LEAD, owner_number=OWNER_DIGITS)
        self.assertEqual(set(result["keys"]), {LEAD, LEAD_LID})
        data = self._contacts()
        for key in (LEAD, LEAD_LID):
            self.assertIs(data[key]["blocked"], True, key)
            self.assertIs(data[key]["ai_enabled"], False, key)
            self.assertEqual(data[key]["ai_disabled_reason"], "panel_block")
        self.assertIn("Mariana Lopes", [b["name"] for b in result["blocked"]])
        jobs = FollowupEngine(self.paths.followups_db).get_jobs(LEAD)
        self.assertFalse([j for j in jobs if j["status"] in ("pending", "leased")], "toques abertos devem ser cancelados")
        self.assertTrue(contacts_store.lock_path_for(self.paths.contacts_json).exists())

    def test_block_by_name_and_by_digits(self):
        by_name = panel_actions.block(self.paths, query="rafael", owner_number=OWNER_DIGITS)
        self.assertEqual(by_name["chat_id"], LEAD2)
        by_digits = panel_actions.block(self.paths, query="+55 47 9 9941-4105", owner_number=OWNER_DIGITS)
        self.assertEqual(by_digits["chat_id"], LEAD)
        unknown = panel_actions.block(self.paths, query="5599911112222", owner_number=OWNER_DIGITS)
        self.assertEqual(unknown["chat_id"], "5599911112222@s.whatsapp.net")
        self.assertIs(self._contacts()["5599911112222@s.whatsapp.net"]["blocked"], True)

    def test_block_refuses_owner_and_unknown_name(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query=OWNER_DIGITS, owner_number=OWNER_DIGITS)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query="ninguém", owner_number=OWNER_DIGITS)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.block(self.paths, query="", owner_number=OWNER_DIGITS)

    def test_unblock_only_records_the_intent_and_keeps_ai_off(self):
        result = panel_actions.unblock(self.paths, chat_id=BLOCKED)
        self.assertTrue(result["pending_reset"])
        record = self._contacts()[BLOCKED]
        self.assertIs(record["blocked"], False)
        self.assertIs(record["ai_enabled"], False)
        self.assertIs(record["session_reset_pending"], True)
        self.assertEqual(record["ai_disabled_reason"], "panel_unblock_reset_pending")
        self.assertEqual(result["blocked"], [])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.unblock(self.paths, chat_id="inexistente@s.whatsapp.net")


class FunnelActionsTest(PanelFixture):
    def test_set_stage_moves_lead_and_cancels_open_jobs(self):
        result = panel_actions.set_stage(self.paths, chat_id=LEAD, stage="proposal")
        self.assertEqual(result["lead"]["stage"], "proposal")
        board = panel_data.leads(self.paths, now=NOW)
        by_stage = {c["id"]: [x["name"] for x in c["cards"]] for c in board["stages"]}
        self.assertIn("Mariana Lopes", by_stage["proposal"])
        open_jobs = [j for j in FollowupEngine(self.paths.followups_db).get_jobs(LEAD) if j["status"] == "pending"]
        self.assertEqual(open_jobs, [])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id=LEAD, stage="ganho")
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_stage(self.paths, chat_id="nao@s.whatsapp.net", stage="new")

    def test_followup_handback_clears_takeover_and_resumes_automation(self):
        engine = FollowupEngine(self.paths.followups_db)
        engine.note_human_takeover(LEAD2)
        assert engine.get_lead(LEAD2)["takeover"] == 1

        result = panel_actions.followup(self.paths, chat_id=LEAD2, action="handback")

        self.assertEqual(result["action"], "handback")
        self.assertFalse(result["takeover"])
        self.assertTrue(result["automation_enabled"])
        lead = engine.get_lead(LEAD2)
        self.assertEqual(lead["takeover"], 0)
        self.assertEqual(lead["automation_enabled"], 1)

    def test_followup_pause_resume_and_cancel(self):
        paused = panel_actions.followup(self.paths, chat_id=LEAD2, action="pause")
        self.assertFalse(paused["automation_enabled"])
        self.assertEqual(paused["open_jobs"], 0)
        resumed = panel_actions.followup(self.paths, chat_id=LEAD2, action="resume")
        self.assertTrue(resumed["automation_enabled"])
        engine = FollowupEngine(self.paths.followups_db)
        engine.note_outbound(LEAD2, message_id="out-3", at=NOW)
        self.assertTrue([j for j in engine.get_jobs(LEAD2) if j["status"] == "pending"])
        cancelled = panel_actions.followup(self.paths, chat_id=LEAD2, action="cancel")
        self.assertTrue(cancelled["automation_enabled"], "cancelar não desliga a automação")
        self.assertEqual(cancelled["open_jobs"], 0)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.followup(self.paths, chat_id=LEAD2, action="explode")

    def test_estimated_value_accepts_brl_formats_and_can_be_cleared(self):
        for value in ("4.800,00", "4800", "4800.00"):
            result = panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl=value)
            self.assertEqual(result["estimated_value_cents"], 480_000)
        cleared = panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl="")
        self.assertIsNone(cleared["estimated_value_cents"])
        for value in ("quatro mil", "12,345", "100000000"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.set_estimated_value(self.paths, chat_id=LEAD, value_brl=value)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_estimated_value(self.paths, chat_id="inexistente@s.whatsapp.net", value_brl="10")


class ReplyActionTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()

    def _message_count(self, chat_id):
        conn = sqlite3.connect(self.paths.messages_db)
        try:
            return conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_reply_sends_persists_autoria_and_silences(self):
        before = self._message_count(LEAD)

        result = panel_actions.reply(
            self.paths, self.bridge, chat_id=LEAD, message="Pode ser quinta às 14h.",
            sent_by="Anthony", sent_by_user="dono", owner_number=OWNER_DIGITS,
        )

        self.assertEqual(result["chat_id"], LEAD)
        self.assertEqual(result["sent_by"], "Anthony")
        self.assertEqual(result["sent_by_user"], "dono")
        self.assertIs(result["silenced"], True)
        self.assertNotIn("warning", result)
        self.assertEqual(self._message_count(LEAD), before + 1)

        conn = sqlite3.connect(self.paths.messages_db)
        row = conn.execute(
            "SELECT from_me, sender_name, message_type, body FROM messages WHERE message_id=?",
            (result["message_id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(row, (1, "Anthony", "text", "Pode ser quinta às 14h."))

        self.assertEqual([c[0] for c in self.bridge.calls], ["/send", "/chat-silence"])
        send_body = self.bridge.calls[0][1]
        self.assertEqual(send_body["chatId"], LEAD)
        self.assertIs(send_body["automation"], False)
        self.assertEqual(self.bridge.calls[1][1]["chatId"], LEAD)

        # Autoria própria mesmo sem nenhum `[human-send]` no log daquele dia.
        detail = panel_data.lead_detail(self.paths, LEAD, now=NOW)
        item = next(
            item for item in detail["timeline"] if item["type"] == "message"
            and any(b["message_id"] == result["message_id"] for b in item["bubbles"])
        )
        self.assertEqual(item["owner"], "owner")
        self.assertEqual(item["sent_by"], "Anthony")

    def test_reply_fails_closed_when_bridge_is_down(self):
        self.bridge.down = True
        before = self._message_count(LEAD)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self._message_count(LEAD), before)
        self.assertFalse(Path(self.paths.panel_db).exists())

    def test_reply_without_message_id_persists_nothing(self):
        self.bridge.send_response = {"success": True, "info": "blocked"}
        before = self._message_count(LEAD)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self._message_count(LEAD), before)
        self.assertFalse(Path(self.paths.panel_db).exists())

    def test_reply_persists_message_even_when_silence_fails(self):
        self.bridge.silence_down = True
        before = self._message_count(LEAD)

        result = panel_actions.reply(
            self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono",
        )

        self.assertEqual(self._message_count(LEAD), before + 1)
        self.assertIsNone(result["silenced"])
        self.assertIn("warning", result)

    def test_reply_refuses_blocked_contact_before_reaching_the_bridge(self):
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.reply(self.paths, self.bridge, chat_id=BLOCKED, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_refuses_empty_blank_or_too_long_message(self):
        for text in ("", "   ", "x" * 4097):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message=text, sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_refuses_group_chats_and_chat_ids_without_a_valid_suffix(self):
        for bad in ("120363012345678901@g.us", "5547999414105", "", "5547999414105@broadcast"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.reply(self.paths, self.bridge, chat_id=bad, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(self.bridge.calls, [])

    def test_reply_marks_takeover_when_the_lead_is_in_the_funnel(self):
        engine = FollowupEngine(self.paths.followups_db)
        self.assertFalse(engine.get_lead(LEAD)["takeover"])

        panel_actions.reply(self.paths, self.bridge, chat_id=LEAD, message="oi", sent_by="Anthony", sent_by_user="dono")

        self.assertTrue(engine.get_lead(LEAD)["takeover"])

    def test_reply_does_not_break_when_contact_has_no_lead_in_the_funnel(self):
        chat_id = "5599988887777@s.whatsapp.net"
        result = panel_actions.reply(self.paths, self.bridge, chat_id=chat_id, message="oi", sent_by="Anthony", sent_by_user="dono")
        self.assertEqual(result["chat_id"], chat_id)
        self.assertIsNone(FollowupEngine(self.paths.followups_db).get_lead(chat_id))


class BridgeActionsTest(unittest.TestCase):
    def test_pause_and_silence_go_through_the_bridge(self):
        bridge = FakeBridge()
        self.assertEqual(panel_actions.pause(bridge, paused=True), {"paused": True})
        self.assertEqual(panel_actions.silence(bridge, chat_id=LEAD, minutes=20)["time_left_s"], 600)
        self.assertEqual(panel_actions.unsilence(bridge, chat_id=LEAD)["silenced"], False)
        self.assertEqual([c[0] for c in bridge.calls], ["/bot-pause", "/chat-silence", "/chat-unsilence"])
        self.assertEqual(bridge.calls[1][1], {"chatId": LEAD, "minutes": 20})
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.pause(bridge, paused="sim")
        bridge.down = True
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.pause(bridge, paused=False)

    def test_whatsapp_settings_are_validated_before_reaching_the_bridge(self):
        bridge = FakeBridge()
        result = panel_actions.whatsapp_settings(
            bridge, reject_calls=True, groups_enabled=False, debounce_seconds=12,
        )
        self.assertEqual(result, {
            "reject_calls": True, "groups_enabled": False, "debounce_seconds": 12,
        })
        self.assertEqual(bridge.calls[-1], ("/runtime-settings", {
            "rejectCalls": True, "groupsEnabled": False, "debounceInitialMs": 12000,
        }))
        for seconds in (-1, 1, 61, "oito"):
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.whatsapp_settings(
                    bridge, reject_calls=True, groups_enabled=False, debounce_seconds=seconds,
                )
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.whatsapp_settings(
                bridge, reject_calls="sim", groups_enabled=False, debounce_seconds=8,
            )


class ActionRoutesTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = FakeBridge()
        config = panel_server.Config(
            username="dono", password="segredo-forte", bridge_url="http://127.0.0.1:1",
            bridge_host_header="", minutes_per_resolved=6, hourly_rate_brl=38, owner_number=OWNER_DIGITS,
            hermes_dashboard_url="http://127.0.0.1:1", whatsapp_mode="bot", whatsapp_allowed_users="*",
            google_client_id="", google_client_secret="", public_url="",
        )
        handler = panel_server.make_handler(config, self.paths, self.bridge)
        self.httpd = panel_server.PanelServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def _post(self, path, body, auth="dono:segredo-forte", raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            try:
                return exc.code, json.loads(raw_body or b"{}")
            except ValueError:
                return exc.code, {"text": raw_body.decode("utf-8", "replace")}

    def _get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        req.add_header("Authorization", "Basic " + base64.b64encode(b"dono:segredo-forte").decode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    def test_routes_require_auth_and_validate(self):
        self.assertEqual(self._post("/api/actions/pause", {"paused": True}, auth=None)[0], 401)
        self.assertEqual(self._post("/api/actions/nada", {})[0], 404)
        self.assertEqual(self._post("/api/outra", {})[0], 404)
        status, body = self._post("/api/actions/stage", {}, raw=b"{nao json")
        self.assertEqual((status, body["error"]), (400, "bad_request"))
        status, body = self._post("/api/actions/stage", {"chat_id": LEAD, "stage": "ganho"})
        self.assertEqual((status, body["error"]), (400, "rejected"))

    def test_routes_apply_actions(self):
        status, body = self._post("/api/actions/block", {"query": "rafael"})
        self.assertEqual(status, 200)
        self.assertEqual(body["chat_id"], LEAD2)
        status, body = self._post("/api/actions/unblock", {"chat_id": LEAD2})
        self.assertTrue(body["pending_reset"])
        status, body = self._post("/api/actions/stage", {"chat_id": LEAD, "stage": "payment"})
        self.assertEqual(body["lead"]["stage"], "payment")
        status, body = self._post("/api/actions/value", {"chat_id": LEAD, "value_brl": "4.800,00"})
        self.assertEqual((status, body["estimated_value_cents"]), (200, 480_000))
        status, body = self._post("/api/actions/followup", {"chat_id": LEAD, "action": "pause"})
        self.assertFalse(body["automation_enabled"])
        status, body = self._post("/api/actions/pause", {"paused": True})
        self.assertEqual((status, body["paused"]), (200, True))
        self.assertEqual(self.bridge.calls[-1], ("/bot-pause", {"paused": True}))
        status, body = self._get("/api/whatsapp-settings")
        self.assertEqual((status, body["known"], body["debounce_seconds"]), (200, True, 8))
        status, body = self._post("/api/actions/whatsapp-settings", {
            "reject_calls": True, "groups_enabled": False, "debounce_seconds": 10,
        })
        self.assertEqual((status, body["reject_calls"], body["debounce_seconds"]), (200, True, 10))

    def test_route_reply_sends_authenticates_and_validates(self):
        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"}, auth=None)
        self.assertEqual(status, 401)

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"}, raw=b"{nao json")
        self.assertEqual((status, body["error"]), (400, "bad_request"))

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": "Oi!"})
        self.assertEqual(status, 200)
        self.assertEqual(body["chat_id"], LEAD)
        self.assertEqual(body["sent_by"], "dono")
        self.assertIs(body["silenced"], True)
        self.assertEqual(self.bridge.calls[0][0], "/send")

        status, body = self._post("/api/actions/reply", {"chat_id": LEAD, "message": ""})
        self.assertEqual((status, body["error"]), (400, "rejected"))


if __name__ == "__main__":
    unittest.main()
