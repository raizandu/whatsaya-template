import json
import unittest
import urllib.parse
from tests import test_panel_actions as action_tests
from unittest import mock
from tests.test_panel_actions import LEAD, LEAD_LID, PanelFixture, panel_actions
import contacts_store


class IdentityOpeningTest(PanelFixture):
    def setUp(self):
        super().setUp()
        records = contacts_store.read_contacts(self.paths.contacts_json)
        for rec in records.values():
            if isinstance(rec, dict):
                rec.pop("lid", None)
        records[LEAD]["ai_enabled"] = False
        contacts_store.write_contacts_atomic(self.paths.contacts_json, records)
        self.bridge = mock.Mock()
        self.bridge.get_json.return_value = {"lidToPhone": {LEAD_LID.split("@")[0]: LEAD.split("@")[0]}}
        self.cursor = self.paths.followups_db.parent / "partial_reply_state.json"
        self.cursor.write_text(json.dumps({"turn": {"chat_id": LEAD_LID, "opening": True, "send_in_flight": True, "remaining_text": "Olá"}}))

    def test_bridge_identity_finds_unlisted_lid_and_blocks_enable(self):
        review = panel_actions.opening_review(self.paths, chat_id=LEAD, bridge=self.bridge)
        self.assertEqual(review["items"][0]["resolution_chat_id"], LEAD_LID)
        with self.assertRaisesRegex(panel_actions.ActionError, "entrega incerta"):
            panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True, bridge=self.bridge)
        self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])

    def test_bridge_unavailable_and_unlinked_pending_fail_closed(self):
        for value in (None, {}, {"lidToPhone": {}}):
            self.bridge.get_json.return_value = value
            self.assertTrue(panel_actions.opening_review(self.paths, chat_id=LEAD, bridge=self.bridge)["unavailable"])
            with self.assertRaises(panel_actions.ActionError):
                panel_actions.set_ai_access(self.paths, chat_id=LEAD, enabled=True, bridge=self.bridge)
            self.assertFalse(contacts_store.read_contacts(self.paths.contacts_json)[LEAD]["ai_enabled"])


    def test_unmapped_lid_can_be_reviewed_exactly_without_exposing_to_other_contact(self):
        self.bridge.get_json.return_value = {"lidToPhone": {}}
        other = "5511888888888@s.whatsapp.net"
        other_review = panel_actions.opening_review(self.paths, chat_id=other, bridge=self.bridge)
        self.assertEqual(other_review["items"], [])
        self.assertTrue(other_review["unavailable"])
        exact = panel_actions.opening_review(self.paths, chat_id=LEAD_LID, bridge=self.bridge)
        self.assertEqual(exact["items"][0]["resolution_chat_id"], LEAD_LID)
        self.assertTrue(exact["unavailable"])
        item = exact["items"][0]
        result = panel_actions.resolve_opening_review(self.paths, bridge=self.bridge, chat_id=LEAD_LID,
            kind=item["kind"], item_id=item["item_id"], version=item["version"],
            decision="sent", actor="admin", resolution_chat_id=LEAD_LID)
        self.assertTrue(result["resolved"])


class IdentityOpeningHttpTest(unittest.TestCase):
    def test_get_and_enable_use_fresh_bridge_map_and_fail_closed_when_down(self):
        harness = action_tests.LiveServerFixture(methodName="runTest")
        harness.setUp()
        self.addCleanup(harness.tearDown)
        contacts = contacts_store.read_contacts(harness.paths.contacts_json)
        for rec in contacts.values():
            if isinstance(rec, dict):
                rec.pop("lid", None)
        contacts[LEAD]["ai_enabled"] = False
        contacts_store.write_contacts_atomic(harness.paths.contacts_json, contacts)
        path = harness.paths.followups_db.parent / "partial_reply_state.json"
        path.write_text(json.dumps({"turn": {"chat_id": LEAD_LID, "opening": True, "send_in_flight": True, "remaining_text": "Olá"}}))
        original = harness.bridge.get_json
        harness.bridge.get_json = lambda path: {"lidToPhone": {LEAD_LID.split("@")[0]: LEAD.split("@")[0]}} if path == "/bot-status" else original(path)
        status, detail = harness._get("/api/lead/" + urllib.parse.quote(LEAD, safe=""))
        self.assertEqual(status, 200)
        self.assertEqual(detail["opening_review"]["items"][0]["resolution_chat_id"], LEAD_LID)
        status, result = harness._post("/api/actions/ai-access", {"chat_id": LEAD, "enabled": True})
        self.assertEqual(status, 400, result)
        harness.bridge.get_json = lambda path: None
        status, detail = harness._get("/api/lead/" + urllib.parse.quote(LEAD, safe=""))
        self.assertTrue(detail["opening_review"]["unavailable"])
        status, result = harness._post("/api/actions/ai-access", {"chat_id": LEAD, "enabled": True})
        self.assertEqual(status, 400, result)

if __name__ == "__main__":
    unittest.main()
