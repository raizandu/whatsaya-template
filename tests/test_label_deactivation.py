"""Etiqueta "Novo cliente" no WhatsApp desliga a IA do contato, na hora e na varredura."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("WHATSAPP_HUMAN_TEST_MODE", "1")

MODULE_PATH = REPO_ROOT / "whatsapp_manager.py"
SPEC = importlib.util.spec_from_file_location("whatsapp_manager", MODULE_PATH)
assert SPEC and SPEC.loader
wm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = wm
SPEC.loader.exec_module(wm)

THERAPIFY_PROFILE_PATH = REPO_ROOT / "deploy" / "clients" / "therapify" / "business_profile.json"
PHONE = "5511999990060@s.whatsapp.net"
LID = "123450000000001@lid"
OTHER = "5511999990061@s.whatsapp.net"


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class LabelDeactivationTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.contacts_path = tmp / "personal_contacts.json"
        self.labels_path = tmp / "labels_state.json"
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", self.contacts_path))
        self.enterContext(mock.patch.object(wm, "_LABELS_STATE_PATH", self.labels_path))
        self.enterContext(mock.patch.object(wm, "_is_contact_blocked", return_value=False))
        self.enterContext(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
        self.enterContext(mock.patch.object(wm, "_recent_inbound_has_commercial_scope", return_value=False))
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)
        wm._labels_state_cache["mtime"] = None
        wm._labels_state_cache["data"] = {}
        saved = dict(wm._lid_to_phone)
        wm._lid_to_phone.clear()
        wm._lid_to_phone[LID.split("@")[0]] = PHONE.split("@")[0]
        self.addCleanup(lambda: (wm._lid_to_phone.clear(), wm._lid_to_phone.update(saved)))
        self._write_labels({LID: ["1"], OTHER: ["4"]})

    def _write_labels(self, chats):
        self.labels_path.write_text(json.dumps({
            "version": 1, "updatedAt": "x",
            "labels": {"1": {"id": "1", "name": "Novo cliente", "deleted": False}, "4": {"id": "4", "name": "Pago", "deleted": False}},
            "chats": chats,
        }), encoding="utf-8")
        wm._labels_state_cache["mtime"] = None

    def _contacts(self):
        return json.loads(self.contacts_path.read_text(encoding="utf-8"))

    def test_profile_lists_novo_cliente(self):
        self.assertEqual(wm._disable_ai_labels(), {"novo cliente"})
        self.assertEqual(wm._disabling_label_chats(), {LID: "Novo cliente"})

    def test_inbound_from_labeled_chat_is_blocked_even_if_funnel_active(self):
        self.contacts_path.write_text(json.dumps({PHONE: {
            "ai_enabled": True, "in_flow": True, "flow_origin": "new_live_commercial",
            "ai_policy_version": wm._CONTACT_AI_POLICY_VERSION,
        }}), encoding="utf-8")
        allowed, reason = wm._ensure_contact_ai_access(PHONE, PHONE, message_text="oi, sou cliente agora")
        self.assertEqual((allowed, reason), (False, "label-client"))
        record = self._contacts()[PHONE]
        self.assertFalse(record["ai_enabled"])
        self.assertEqual(record["ai_disabled_reason"], "label_client")
        self.assertEqual(record["ai_disabled_label"], "Novo cliente")

    def test_unknown_labeled_contact_never_enters_funnel(self):
        allowed, reason = wm._ensure_contact_ai_access(PHONE, PHONE, message_text="Olá! Tenho interesse")
        self.assertEqual((allowed, reason), (False, "label-client"))
        self.assertFalse(self._contacts()[PHONE]["ai_enabled"])

    def test_other_label_does_not_block(self):
        allowed, reason = wm._ensure_contact_ai_access(
            OTHER,
            OTHER,
            message_text="Olá! Tenho interesse na consulta com o Dr. Rodrigo",
        )
        self.assertEqual((allowed, reason), (True, "new-commercial-inbound"))

    def test_sweep_deactivates_and_cancels_followups_once(self):
        self.contacts_path.write_text(json.dumps({PHONE: {
            "ai_enabled": True, "in_flow": True, "flow_origin": "new_live_commercial",
            "ai_policy_version": wm._CONTACT_AI_POLICY_VERSION,
        }}), encoding="utf-8")
        with mock.patch.object(wm, "_followup_cancel") as cancel:
            self.assertEqual(wm._sweep_label_deactivations(), 1)
            self.assertEqual(wm._sweep_label_deactivations(), 0)
        cancel.assert_called_once_with(PHONE)
        self.assertEqual(self._contacts()[PHONE]["ai_disabled_reason"], "label_client")

    def test_generic_profile_ignores_labels(self):
        with mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}):
            _reset_profile_cache()
            self.assertEqual(wm._disabling_label_chats(), {})
            self.assertEqual(wm._sweep_label_deactivations(), 0)


if __name__ == "__main__":
    unittest.main()
