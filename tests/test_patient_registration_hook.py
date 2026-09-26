import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import whatsapp_manager as wm
import prontuario_verde_onboarding as queue

JID = "556281405459@s.whatsapp.net"

class RegistrationHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contacts = self.root / "contacts.json"
        self.config = self.root / "config.json"
        self.snapshot = self.root / "directory.json"
        self.spool = self.root / "jobs"
        self.contacts.write_text(json.dumps({JID: {"ai_enabled": True, "in_flow": True}}))
        self.cfg = {"enabled": True, "registration_enabled": True, "clinic_id": "test", "source_clinic_hash": "a" * 64}
        self.config.write_text(json.dumps({"patient_directory": self.cfg}))
        self.snapshot.write_text(json.dumps({"schema_version": 1, "source": "prontuario_verde", "clinic_id": "test", "source_clinic_hash": "a" * 64, "generated_at": datetime.now(timezone.utc).isoformat(), "complete": True, "patients": []}))
        for key, value in {"_PERSONAL_CONTACTS_PATH": self.contacts, "_PATIENT_DIRECTORY_CONFIG_PATH": self.config, "_PATIENT_DIRECTORY_SNAPSHOT_PATH": self.snapshot, "_PATIENT_REGISTRATION_SPOOL": self.spool}.items():
            patcher = patch.object(wm, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, message, mid="MID-1", **extra):
        return wm._patient_registration_prompt_context(JID, message, {"message_id": mid, **extra})

    def job(self):
        return queue.get_for_contact(self.spool, "test", JID)

    def test_name_confirmation_persists_before_queue_and_deduplicates(self):
        self.assertIn("nome completo", self.call("Quero marcar uma avaliação"))
        self.assertIsNone(self.job())
        self.call("Anthony Aya", "MID-2")
        self.assertEqual(self.job()["status"], "pending")
        state = json.loads(self.contacts.read_text())[JID]["pv_registration"]
        self.assertEqual(state["source_message_id"], "MID-2")
        self.assertEqual(state["confirmed_name"], "Anthony Aya")
        request_id = self.job()["request_id"]
        self.call("qual horario?", "MID-4")
        self.assertEqual(self.job()["request_id"], request_id)
        self.call("é para minha filha", "MID-5")
        self.assertEqual(json.loads(self.contacts.read_text())[JID]["pv_registration"]["phase"], "needs_review")

    def test_booking_name_instruction_is_last_in_the_real_prompt(self):
        registration = self.call("Quero uma avaliação para aparelho invisível")
        prompt = wm._build_support_prompt(
            "persona", "regras de agenda", "histórico", chat_id=JID,
            conversation_state="estado da conversa", patient_directory_context=registration,
        )["context"]
        self.assertIn("nome completo", prompt)
        self.assertGreater(prompt.index("### CADASTRO AUTOMÁTICO ###"), prompt.index("estado da conversa"))

    def test_reply_gate_keeps_answer_and_replaces_competing_booking_question(self):
        self.call("Quero uma avaliação para aparelho invisível", "MID-booking")
        contact = json.loads(self.contacts.read_text())[JID]
        reply = wm._enforce_registration_question(
            "Fazemos sim. A clínica fica em Cotia, tá na sua rota? Terça ou quinta?\n\n"
            "[[HANDOFF: agendamento || RESUMO: preferência pendente]]",
            contact, {"message_id": "MID-booking"},
        )
        self.assertIn("Fazemos sim.", reply)
        self.assertIn("nome completo", reply)
        self.assertNotIn("Terça ou quinta", reply)
        self.assertNotIn("HANDOFF", reply)
        self.assertEqual(wm._enforce_registration_question(reply, contact, {"message_id": "other"}), reply)
        premature = wm._enforce_registration_question(
            "Fazemos sim. Me passa seu nome completo? E prefere terça?\n\n"
            "[[HANDOFF: agendamento || RESUMO: pendente]]",
            contact, {"message_id": "MID-booking"},
        )
        self.assertEqual(premature.count("?"), 1)
        self.assertNotIn("HANDOFF", premature)

    def test_name_reply_queues_and_does_not_force_another_question(self):
        self.call("Quero marcar uma avaliação", "MID-1")
        self.call("Maria de Souza", "MID-name")
        contact = json.loads(self.contacts.read_text())[JID]
        reply = "A clínica fica no Centro de Cotia. Fica bom pra você?"
        self.assertEqual(wm._enforce_registration_question(reply, contact, {"message_id":"MID-name"}), reply)
        self.assertEqual(self.job()["status"], "pending")

    def test_pv_reply_cannot_claim_an_unverified_booking(self):
        result = wm._enforce_pv_booking_confirmation(
            "Sua avaliação ficou agendada para terça com a Dra. Bruna.",
        )
        self.assertIn("antes de te confirmar", result)
        self.assertNotIn("ficou agendada", result)
        self.assertIn("antes de te confirmar", wm._enforce_pv_booking_confirmation(
            "Pronto, remarquei para terça-feira.",
        ))
        self.assertEqual(
            wm._enforce_pv_booking_confirmation(
                "A Dra. Bruna faz avaliação de aparelho.",
            ),
            "A Dra. Bruna faz avaliação de aparelho.",
        )

    def test_explicit_first_message_can_enqueue(self):
        self.call("Meu nome é Anthony Aya")
        self.assertEqual(self.job()["status"], "pending")

    def test_synthetic_and_injection_do_not_enqueue(self):
        self.call("Meu nome é Anthony Aya", "synthetic:1")
        self.call("Meu nome é Anthony Aya", prompt_injection_kind="direct")
        self.assertIsNone(self.job())

    def test_disabled_contact_does_not_enqueue(self):
        self.contacts.write_text(json.dumps({JID: {"ai_enabled": False, "in_flow": True}}))
        self.assertEqual(self.call("Meu nome é Anthony Aya"), "")
        self.assertIsNone(self.job())

    def test_existing_patient_is_reused(self):
        data = json.loads(self.snapshot.read_text())
        data["patients"] = [{"id": "123", "phones": ["5562981405459"]}]
        self.snapshot.write_text(json.dumps(data))
        self.assertEqual(self.call("Meu nome é Anthony Aya"), "")
        self.assertIsNone(self.job())

    def test_ambiguous_prior_queue_binding_prevents_new_registration(self):
        with patch.object(queue, "get_for_contact", return_value={"status": "needs_review", "code": "source_clinic_ambiguous"}):
            self.assertIn("conferência", self.call("Meu nome é Anthony Aya"))
        self.assertIsNone(self.job())
        self.assertEqual(json.loads(self.contacts.read_text())[JID]["pv_registration"]["phase"], "needs_review")
