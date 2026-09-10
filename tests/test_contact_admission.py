"""Admissão de contato novo ao funil: filtro genérico de escopo vs. flag do perfil."""
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

LEAD = "556281405459@s.whatsapp.net"
OPENINGS = [
    "Olá! Tenho interesse e queria mais informações, por favor.",
    "Qual valor da consulta?",
    "Olá Rodrigo, vim pelo seu anúncio e gostaria de marcar uma sessão.",
    "quero agendar uma sessão com o Dr. Rodrigo",
]


def _reset_profile_cache() -> None:
    wm._business_profile_cache["checked_at"] = 0.0
    wm._business_profile_cache["mtime"] = None
    wm._business_profile_cache["data"] = {}


class ContactAdmissionTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.contacts_path = tmp / "personal_contacts.json"
        self.enterContext(mock.patch.object(wm, "_PERSONAL_CONTACTS_PATH", self.contacts_path))
        self.enterContext(mock.patch.object(wm, "_is_contact_blocked", return_value=False))
        self.enterContext(mock.patch.object(wm, "_resolve_phone_from_jid", side_effect=lambda jid: jid))
        self.enterContext(mock.patch.object(wm, "_recent_inbound_has_commercial_scope", return_value=False))
        _reset_profile_cache()
        self.addCleanup(_reset_profile_cache)

    def _use_generic_profile(self):
        self.enterContext(mock.patch.dict(os.environ, {"WHATSAPP_BUSINESS_PROFILE": "generic"}))
        _reset_profile_cache()

    def _use_therapify_profile(self):
        self.enterContext(mock.patch.dict(os.environ, {
            "WHATSAPP_BUSINESS_PROFILE": "therapify",
            "WHATSAPP_BUSINESS_PROFILE_FILE": str(THERAPIFY_PROFILE_PATH),
        }))
        _reset_profile_cache()

    def _record(self):
        return json.loads(self.contacts_path.read_text(encoding="utf-8"))[LEAD]

    def test_generic_profile_keeps_scope_filter(self):
        self._use_generic_profile()
        allowed, reason = wm._ensure_contact_ai_access(LEAD, LEAD, message_text=OPENINGS[0])
        self.assertEqual((allowed, reason), (False, "commercial-scope-unconfirmed"))
        self.assertEqual(self._record()["flow_origin"], "scope_pending")

    def test_therapify_profile_declares_direct_admission(self):
        profile = json.loads(THERAPIFY_PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertIs(profile.get("admit_new_contacts_to_funnel"), True)

    def test_therapify_admits_any_first_message(self):
        self._use_therapify_profile()
        for text in OPENINGS:
            with self.subTest(text=text):
                self.contacts_path.unlink(missing_ok=True)
                allowed, reason = wm._ensure_contact_ai_access(LEAD, LEAD, message_text=text)
                self.assertEqual((allowed, reason), (True, "new-commercial-inbound"))
                record = self._record()
                self.assertTrue(record["ai_enabled"])
                self.assertTrue(record["in_flow"])
                self.assertEqual(record["flow_origin"], "new_live_commercial")

    def test_flag_promotes_contact_left_in_scope_pending(self):
        self._use_therapify_profile()
        self.contacts_path.write_text(json.dumps({LEAD: {
            "ai_enabled": False,
            "in_flow": False,
            "flow_origin": "scope_pending",
            "ai_policy_version": wm._CONTACT_AI_POLICY_VERSION,
            "ai_disabled_reason": "commercial_scope_unconfirmed",
        }}), encoding="utf-8")
        allowed, reason = wm._ensure_contact_ai_access(LEAD, LEAD, message_text="sim")
        self.assertEqual((allowed, reason), (True, "commercial-scope-confirmed"))
        self.assertNotIn("ai_disabled_reason", self._record())

    def test_legacy_record_under_lid_key_is_found_after_restart(self):
        # Registro legado só sob @lid, cache LID vazio (reinício): o telefone não pode
        # virar contato novo; o mapa é reconstruído pelas fontes persistidas.
        self._use_therapify_profile()
        saved = dict(wm._lid_to_phone)
        wm._lid_to_phone.clear()
        self.addCleanup(lambda: (wm._lid_to_phone.clear(), wm._lid_to_phone.update(saved)))
        lid_key = "187050221392039@lid"
        self.contacts_path.write_text(json.dumps({lid_key: {
            "name": "Bryan", "lid": lid_key, "ai_enabled": False, "in_flow": False,
            "flow_origin": "legacy_fullsync", "ai_disabled_reason": "legacy_history",
            "ai_policy_version": wm._CONTACT_AI_POLICY_VERSION,
        }}), encoding="utf-8")
        phone = "5528999298084@s.whatsapp.net"
        with mock.patch.object(wm, "_build_lid_phone_map", return_value={"187050221392039": "5528999298084"}):
            allowed, reason = wm._ensure_contact_ai_access(phone, phone, message_text="opa rodrigão!")
        self.assertEqual((allowed, reason), (False, "legacy-contact-disabled"))
        stored = json.loads(self.contacts_path.read_text(encoding="utf-8"))
        self.assertNotIn(phone, stored)
        self.assertEqual(stored[lid_key]["ai_disabled_reason"], "legacy_history")

    def test_flag_never_reenables_legacy_contact(self):
        self._use_therapify_profile()
        self.contacts_path.write_text(json.dumps({LEAD: {
            "ai_enabled": False,
            "in_flow": False,
            "flow_origin": "legacy_sync",
            "ai_policy_version": wm._CONTACT_AI_POLICY_VERSION,
            "ai_disabled_reason": "legacy_history",
        }}), encoding="utf-8")
        allowed, reason = wm._ensure_contact_ai_access(LEAD, LEAD, message_text=OPENINGS[0])
        self.assertEqual((allowed, reason), (False, "legacy-contact-disabled"))
        self.assertEqual(self._record()["ai_disabled_reason"], "legacy_history")


if __name__ == "__main__":
    unittest.main()
