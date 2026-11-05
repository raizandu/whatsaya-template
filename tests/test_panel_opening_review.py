"""Conferência explícita de entregas incertas antes de reativar a IA."""
import json
import sys
import types
import unittest
import sqlite3
import urllib.parse
from unittest import mock

from tests.test_panel_actions import LEAD, LEAD_LID, PanelFixture, panel_actions
from tests import test_panel_login as panel_login
from tests import test_panel_actions as action_tests
import contacts_store
import users_store


class OpeningReviewActionsTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.impl = types.SimpleNamespace(
            inspect=mock.Mock(return_value={"items": []}),
            resolve=mock.Mock(return_value={"resolved": True}),
            resume_pending=mock.Mock(),
            review_chat_ids=mock.Mock(return_value=[]),
        )
        self.enterContext(mock.patch.dict(sys.modules, {"opening_resolution": self.impl}))

    def test_cannot_enable_while_uncertain_and_never_prepares_resume(self):
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        self.impl.inspect.return_value = {"items": [{"kind": "opening_bubble"}]}
        with self.assertRaisesRegex(panel_actions.ActionError, "entrega incerta"):
            panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True)
        self.impl.resume_pending.assert_not_called()
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_enable_records_resume_intent_only_after_all_items_cleared(self):
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        result = panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True)
        self.assertTrue(result["enabled"])
        self.assertEqual([c.args[1] for c in self.impl.resume_pending.call_args_list], [LEAD, LEAD_LID])

    def test_storage_failure_refuses_enable(self):
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        self.impl.inspect.side_effect = OSError("sensitive internal path")
        with self.assertRaisesRegex(panel_actions.ActionError, "Não foi possível consultar") as exc:
            panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True)
        self.assertNotIn("sensitive", str(exc.exception))
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_resume_preparation_failure_leaves_ai_disabled(self):
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        self.impl.resume_pending.side_effect = OSError("private error")
        with self.assertRaisesRegex(panel_actions.ActionError, "acesso à IA não foi alterado") as exc:
            panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True)
        self.assertNotIn("private error", str(exc.exception))
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_followup_cannot_hand_back_while_uncertain(self):
        self.impl.inspect.return_value = {"items": [{"kind": "deferred_reply"}]}
        with self.assertRaisesRegex(panel_actions.ActionError, "entrega incerta"):
            panel_actions.followup(self.paths, chat_id=LEAD, action="handback")

    def test_lid_pending_blocks_phone_enable_and_other_chat_cannot_be_resolved(self):
        self.impl.inspect.side_effect = lambda _paths, chat, **_kwargs: {"items": [{"kind": "opening_bubble", "item_id": "t", "version": "v", "display_text": "Oi"}]} if chat == LEAD_LID else {"items": []}
        items = panel_actions.opening_review(self.paths, chat_id=LEAD)["items"]
        self.assertEqual(items[0]["resolution_chat_id"], LEAD_LID)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True)
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.resolve_opening_review(self.paths, chat_id=LEAD, kind="opening_bubble", item_id="t", version="v", decision="sent", actor="admin", resolution_chat_id="5581999999999@s.whatsapp.net")
        self.impl.resolve.assert_not_called()
        panel_actions.resolve_opening_review(self.paths, chat_id=LEAD, kind="opening_bubble", item_id="t", version="v", decision="sent", actor="admin", resolution_chat_id=LEAD_LID)
        self.assertEqual(self.impl.resolve.call_args.args[1], LEAD_LID)

    def test_decisions_require_explicit_valid_kind_version_and_actor(self):
        for decision in ("", "maybe", "true"):
            with self.subTest(decision=decision), self.assertRaises(panel_actions.ActionError):
                panel_actions.resolve_opening_review(self.paths, chat_id=LEAD, kind="opening_bubble", item_id="x", version="v", decision=decision, actor="admin")
        self.impl.resolve.assert_not_called()
        result = panel_actions.resolve_opening_review(self.paths, chat_id=LEAD, kind="opening_bubble", item_id="x", version="v", decision="not_sent", actor="admin")
        self.assertTrue(result["resolved"])
        self.impl.resolve.assert_called_once_with(self.paths, LEAD, "opening_bubble", "x", "v", "not_sent", "admin")


class OpeningReviewRoutesTest(unittest.TestCase):
    def test_resolution_requires_admin_and_audits_authenticated_user(self):
        harness = panel_login.PanelLoginTestCase(methodName="test_login_page_public_access")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        self.addCleanup(harness.tearDown)
        impl = types.SimpleNamespace(inspect=mock.Mock(return_value={"items": []}), resolve=mock.Mock(return_value={"resolved": True}), resume_pending=mock.Mock(), review_chat_ids=mock.Mock(return_value=[]))
        payload = {"chat_id": "5511999999999@s.whatsapp.net", "kind": "opening_bubble", "item_id": "turn", "version": "hash", "decision": "sent", "actor": "forged"}
        encoded = json.dumps(payload).encode()
        with mock.patch.dict(sys.modules, {"opening_resolution": impl}):
            status, _, _ = harness._request("POST", "/api/actions/opening-review", headers={"Content-Type": "application/json"}, data=encoded)
            self.assertEqual(status, 401)
            harness._create_attendant()
            cookie = harness._login_and_get_cookie("ana.silva", "SenhaForte#2026")
            status, _, _ = harness._request("POST", "/api/actions/opening-review", headers={"Content-Type": "application/json", "Cookie": cookie}, data=encoded)
            self.assertEqual(status, 403)
            status, _, body = harness._request("POST", "/api/actions/opening-review", headers={"Content-Type": "application/json", "Authorization": harness.auth_header}, data=encoded)
            self.assertEqual(status, 200, body)
            self.assertEqual(impl.resolve.call_args.args[-1], "admin")
            self.assertNotIn("forged", impl.resolve.call_args.args)


class OpeningReviewRealFlowTest(PanelFixture):
    def setUp(self):
        super().setUp()
        self.bridge = mock.Mock()
        self.bridge.get_json.return_value = {"lidToPhone": {LEAD_LID.split("@")[0]: LEAD.split("@")[0]}}

    def test_cursor_decision_is_audited_and_never_enables_ai_by_itself(self):
        import opening_resolution
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD, LEAD_LID], {"ai_enabled": False})
        cursor_path = self.paths.followups_db.parent / "partial_reply_state.json"
        original = {"chat_id": LEAD, "opening": True, "send_in_flight": True,
                    "remaining_text": "Bolha incerta\n\nBolha restante", "updated_at": 100}
        cursor_path.write_text(json.dumps({"turn": original}), encoding="utf-8")
        review = panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)
        self.assertEqual(len(review["items"]), 1)
        item = review["items"][0]
        self.assertEqual((item["kind"], item["display_text"]), ("opening_bubble", "Bolha incerta"))
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, bridge=self.bridge, chat_id=LEAD, enabled=True)

        result = panel_actions.resolve_opening_review(
            self.paths, bridge=self.bridge, chat_id=LEAD, kind=item["kind"], item_id=item["item_id"],
            version=item["version"], decision="sent", actor="admin",
            resolution_chat_id=item["resolution_chat_id"],
        )
        self.assertTrue(result["resolved"])
        persisted = json.loads(cursor_path.read_text())["turn"]
        self.assertEqual(persisted["remaining_text"], "Bolha restante")
        self.assertFalse(persisted["send_in_flight"])
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        with outbox._connect() as conn:
            rows = conn.execute("SELECT decision, actor, status FROM opening_resolution_audit ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("sent", "admin", "requested"), ("sent", "admin", "applied")])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.resolve_opening_review(self.paths, bridge=self.bridge, chat_id=LEAD, kind=item["kind"], item_id=item["item_id"], version=item["version"], decision="sent", actor="admin")

        self.assertTrue(panel_actions.set_ai_access(self.paths, bridge=self.bridge, chat_id=LEAD, enabled=True)["enabled"])
        self.assertTrue(outbox.turn_authorized("turn"))

    def test_deferred_reply_not_sent_waits_for_explicit_resume(self):
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        outbox.defer(LEAD, "in-1", "turn", "Minha pergunta", 100)
        outbox.mark_opening_complete("turn")
        outbox.claim_next()
        outbox.dispatch_result(LEAD, "in-1", retry=False)
        items = panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)["items"]
        item = next(item for item in items if item["kind"] == "deferred_reply")
        result = panel_actions.resolve_opening_review(self.paths, bridge=self.bridge, chat_id=LEAD, kind=item["kind"], item_id=item["item_id"], version=item["version"], decision="not_sent", actor="admin")
        self.assertEqual(result, {"resolved": False, "manual_required": True})
        self.assertIsNone(outbox.claim_next())
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])
        self.assertTrue(panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)["items"])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, bridge=self.bridge, chat_id=LEAD, enabled=True)

    def test_waiting_inbound_is_reviewed_when_ai_is_off_and_sent_does_not_invent_id(self):
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        outbox.defer(LEAD, "in-1", "turn", "Minha pergunta", 100)
        items = panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)["items"]
        item = next(item for item in items if item["kind"] == "deferred_reply")
        panel_actions.resolve_opening_review(self.paths, bridge=self.bridge, chat_id=LEAD, kind=item["kind"], item_id=item["item_id"], version=item["version"], decision="sent", actor="admin")
        with outbox._connect() as conn:
            row = conn.execute("SELECT state,outbound_id FROM opening_inbound_outbox WHERE chat_id=? AND message_id=?", (LEAD, "in-1")).fetchone()
            audit = conn.execute("SELECT decision,actor,status FROM opening_resolution_audit").fetchall()
        self.assertEqual((row["state"], row["outbound_id"]), ("resolved_sent", None))
        self.assertEqual([tuple(row) for row in audit], [("sent", "admin", "applied")])
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_proven_unsent_inbound_waits_for_explicit_resume(self):
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        outbox.defer(LEAD, "in-safe", "turn", "Minha pergunta", 100)
        item = next(item for item in panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)["items"] if item["kind"] == "deferred_reply")
        self.assertTrue(item["can_retry"])
        result = panel_actions.resolve_opening_review(self.paths, bridge=self.bridge, chat_id=LEAD, kind=item["kind"], item_id=item["item_id"], version=item["version"], decision="not_sent", actor="admin")
        self.assertTrue(result["resolved"])
        self.assertIsNone(outbox.claim_next())
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_pending_phone_is_visible_when_only_lid_is_disabled(self):
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": True})
        contacts_store.update_record(self.paths.contacts_json, [LEAD_LID], {"ai_enabled": False})
        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        outbox.defer(LEAD, "phone-in", "turn", "Pergunta", 100)
        items = panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD)["items"]
        self.assertEqual([item["resolution_chat_id"] for item in items], [LEAD])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, bridge=self.bridge, chat_id=LEAD, enabled=True)

    def test_pending_lid_is_visible_when_only_phone_is_disabled(self):
        import opening_inbound_outbox
        contacts_store.update_record(self.paths.contacts_json, [LEAD], {"ai_enabled": False})
        contacts_store.update_record(self.paths.contacts_json, [LEAD_LID], {"ai_enabled": True})
        outbox = opening_inbound_outbox.OpeningInboundOutbox(self.paths.followups_db.parent / "opening_inbound_outbox.db")
        outbox.defer(LEAD_LID, "lid-in", "turn", "Pergunta", 100)
        items = panel_actions.opening_review(self.paths, bridge=self.bridge, chat_id=LEAD_LID)["items"]
        self.assertEqual([item["resolution_chat_id"] for item in items], [LEAD_LID])
        with self.assertRaises(panel_actions.ActionError):
            panel_actions.set_ai_access(self.paths, bridge=self.bridge, chat_id=LEAD_LID, enabled=True)


class OpeningReviewHttpFlowTest(unittest.TestCase):
    def test_api_review_decision_and_explicit_ai_resume(self):
        import opening_inbound_outbox
        harness = action_tests.LiveServerFixture(methodName="runTest")
        harness.setUp()
        self.addCleanup(harness.tearDown)
        contacts_store.update_record(harness.paths.contacts_json, [LEAD, LEAD_LID], {"ai_enabled": False})
        cursor_path = harness.paths.followups_db.parent / "partial_reply_state.json"
        cursor_path.write_text(json.dumps({"turn": {"chat_id": LEAD, "opening": True, "send_in_flight": True,
                                                   "remaining_text": "Bolha incerta\n\nBolha restante", "updated_at": 100}}))
        status, detail = harness._get("/api/lead/" + urllib.parse.quote(LEAD, safe=""))
        self.assertEqual(status, 200, detail)
        item = detail["opening_review"]["items"][0]
        self.assertEqual(item["display_text"], "Bolha incerta")
        status, result = harness._post("/api/actions/ai-access", {"chat_id": LEAD, "enabled": True})
        self.assertEqual(status, 400, result)
        self.assertFalse(contacts_store.read_contacts(harness.paths.contacts_json)[LEAD]["ai_enabled"])
        status, result = harness._post("/api/actions/opening-review", {
            "chat_id": LEAD, "resolution_chat_id": item["resolution_chat_id"], "kind": item["kind"],
            "item_id": item["item_id"], "version": item["version"], "decision": "not_sent",
        })
        self.assertEqual(status, 200, result)
        self.assertTrue(result["manual_required"])
        self.assertFalse(contacts_store.read_contacts(harness.paths.contacts_json)[LEAD]["ai_enabled"])
        self.assertEqual(json.loads(cursor_path.read_text())["turn"]["remaining_text"], "Bolha incerta\n\nBolha restante")
        status, result = harness._post("/api/actions/ai-access", {"chat_id": LEAD, "enabled": True})
        self.assertEqual(status, 400, result)
        status, result = harness._post("/api/actions/opening-review", {
            "chat_id": LEAD, "resolution_chat_id": item["resolution_chat_id"], "kind": item["kind"],
            "item_id": item["item_id"], "version": item["version"], "decision": "sent",
        })
        self.assertEqual(status, 200, result)
        self.assertEqual(json.loads(cursor_path.read_text())["turn"]["remaining_text"], "Bolha restante")
        status, result = harness._post("/api/actions/ai-access", {"chat_id": LEAD, "enabled": True})
        self.assertEqual(status, 200, result)
        outbox = opening_inbound_outbox.OpeningInboundOutbox(harness.paths.followups_db.parent / "opening_inbound_outbox.db")
        self.assertTrue(outbox.turn_authorized("turn"))
