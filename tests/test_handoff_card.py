import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from handoff_card import destination, context_lines


class HandoffCardTest(unittest.TestCase):
    def setUp(self):
        self.root = {"handoff": {"recipients": {"liliane": "+55 11 90000-0000"},
                                 "panel_base_url": "https://panel.example"},
                     "patient_directory": {"enabled": True, "clinic_id": "clinic", "source_clinic_hash": "hash"}}

    def test_explicit_route_does_not_change_owner_or_other_professional(self):
        self.assertEqual(destination(self.root, "liliane: verificar encaixe", "owner"),
                         ("5511900000000", "verificar encaixe"))
        self.assertEqual(destination(self.root, "bruna: verificar encaixe", "owner"),
                         ("owner", "bruna: verificar encaixe"))
        self.assertEqual(destination(self.root, "agendamento", "owner"), ("owner", "agendamento"))

    def test_invalid_destination_does_not_send_to_arbitrary_jid(self):
        self.root["handoff"]["recipients"]["liliane"] = "group@g.us"
        self.assertEqual(destination(self.root, "liliane: encaixe", "owner")[0], "owner")

    @patch("handoff_card.lookup_for_panel")
    def test_card_has_encoded_patient_link_and_cautious_chart_reference(self, lookup):
        lookup.return_value = {"status": "matched", "patient_id": "42"}
        lines = context_lines(self.root, "5511900000001@s.whatsapp.net", "directory")
        self.assertIn("/#atendimento-todas/5511900000001%40s.whatsapp.net", lines[0])
        self.assertIn("ID 42", lines[1])
        self.assertIn("conferir se pertence", lines[1])

    @patch("handoff_card.lookup_for_panel")
    def test_ambiguous_identity_never_selects_a_chart(self, lookup):
        lookup.return_value = {"status": "ambiguous", "patient_ids": ["42", "43"]}
        self.assertIn("vínculo não confirmado", context_lines(self.root, "chat", "directory")[1])

    @patch("handoff_card.lookup_for_panel", side_effect=OSError)
    def test_failed_directory_read_preserves_handoff_link(self, lookup):
        lines = context_lines(self.root, "chat", "directory")
        self.assertEqual(len(lines), 2)
        self.assertIn("indisponível", lines[1])

    def test_real_notifier_routes_delivers_and_silences_only_after_confirmation(self):
        import whatsapp_manager as wm
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "panel.config.json"
            config_path.write_text(json.dumps(self.root))
            with patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config_path), \
                 patch.object(wm, "_load_personal_contacts", return_value={}), \
                 patch.object(wm, "_handoff_sent_at", {}), \
                 patch.object(wm, "_human_send", return_value="verified-message") as send, \
                 patch.object(wm, "_silence_chat_after_handoff") as silence, \
                 patch("handoff_card.lookup_for_panel", return_value={"status":"matched", "patient_id":"42"}):
                self.assertTrue(wm._notify_owner_handoff("chat@s.whatsapp.net", "liliane: encaixe", "Pedido para outra pessoa."))
                self.assertEqual(send.call_args.args[0], "5511900000000@s.whatsapp.net")
                self.assertIn("ID 42", send.call_args.args[1])
                self.assertIn("panel.example", send.call_args.args[1])
                self.assertTrue(send.call_args.kwargs["operational_card"])
                self.assertIn("panel.example", wm._sanitize_operational_card(send.call_args.args[1]))
                silence.assert_called_once_with("chat@s.whatsapp.net")


if __name__ == "__main__":
    unittest.main()
