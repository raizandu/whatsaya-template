from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import prontuario_verde_booking_queue as queue
from tests.test_prontuario_verde_booking_queue import request_payload

SPEC = importlib.util.spec_from_file_location(
    "pv_worker_booking",
    Path(__file__).resolve().parents[1] / "deploy/scripts/process_prontuario_verde_actions.py",
)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class FakePort:
    def __init__(self, on_prepare=None):
        self.submissions = 0
        self.on_prepare = on_prepare

    def prepare(self, request):
        if self.on_prepare:
            self.on_prepare()
        return {
            "clinic_id": request["clinic_id"],
            "source_clinic_hash": request["source_clinic_hash"],
            "patient_id": request["patient_id"],
            "professional_id": request["professional_id"],
            "unit_id": request["unit_id"],
            "type_id": request["type_id"],
            "procedure_id": request.get("procedure_id"),
            "duration_min": request["duration_min"],
            "start": request["requested_start"],
            "end": request["requested_end"],
            "target_matches": [],
            "availability": {
                "status": "available",
                "professional_id": request["professional_id"],
                "unit_id": request["unit_id"],
                "source_clinic_hash": request["source_clinic_hash"],
                "start": request["requested_start"],
                "end": request["requested_end"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    def submit_once(self, request):
        self.submissions += 1

    def reconcile_after_save(self, request):
        return {
            "clinic_id": request["clinic_id"],
            "source_clinic_hash": request["source_clinic_hash"],
            "matches": [{
                "appointment_id": "998",
                "patient_id": request["patient_id"],
                "professional_id": request["professional_id"],
                "unit_id": request["unit_id"],
                "type_id": request["type_id"],
                "procedure_id": request.get("procedure_id"),
                "duration_min": request["duration_min"],
                "start": request["requested_start"],
                "end": request["requested_end"],
                "status": "AGENDADO",
            }],
        }


class BookingWorkerTests(unittest.TestCase):
    def setUp(self):
        live_guard = patch.object(worker, "require_live_booking_authorization")
        self.live_guard = live_guard.start()
        self.addCleanup(live_guard.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.spool = root / "booking"
        self.contacts = root / "contacts.json"
        self.messages = root / "messages.db"
        self.schedule = root / "schedule.json"
        self.config = root / "panel.config.json"
        self.lock = root / "sync.lock"
        payload = request_payload()
        payload["confirmation"]["kind"] = "offer_acceptance"
        self.chat = payload["chat_id"]
        self.source_id = payload["confirmation"]["message_id"]
        self.clinic = payload["clinic_id"]
        self.config.write_text(json.dumps({
            "patient_directory": {
                "enabled": True,
                "appointment_write_enabled": True,
                "clinic_id": self.clinic,
                "source_clinic_hash": payload["source_clinic_hash"],
            },
            "appointment_policy": {
                "appointments": {"evaluation": {
                    "duration_minutes": 40,
                    "eligible_professionals": ["liliane"],
                    "auto_book": True,
                }},
                "professional_ids": {"liliane": "22"},
                "type_ids": {"evaluation": "44"},
                "unit_ids": ["4"],
            },
        }))
        self.contacts.write_text(json.dumps({self.chat: {"ai_enabled": True}}))
        db = sqlite3.connect(self.messages)
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_id TEXT, message_id TEXT, from_me INTEGER, is_historical INTEGER, timestamp REAL)")
        db.execute("INSERT INTO messages (chat_id, message_id, from_me, is_historical, timestamp) VALUES (?, ?, 0, 0, ?)",
                   (self.chat, self.source_id, datetime.now(timezone.utc).timestamp()))
        db.commit()
        db.close()
        self.paths = worker.panel_data.Paths(
            contacts_json=self.contacts,
            messages_db=self.messages,
            followups_db=root / "followups.db",
            panel_db=root / "panel.db",
            patient_directory_json=root / "patients.json",
            prontuario_verde_schedule_json=self.schedule,
        )
        self.payload = payload

    def _claim(self):
        queue.initialize(self.spool)
        queued = queue.enqueue_booking(self.spool, self.payload)
        return queue.claim_next(self.spool), queued

    def _factory(self, port):
        from prontuario_verde_appointment_writer import ProntuarioVerdeAppointmentWriter
        return lambda _session, _request, config: ProntuarioVerdeAppointmentWriter(port, config)

    @patch.object(worker.panel_data, "patient_details")
    def test_worker_revalidates_and_only_reports_writer_proof(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        request, queued = self._claim()
        port = FakePort()
        session = Mock()
        worker.process_booking(request, root=self.spool, session=session, paths=self.paths,
                               config_path=self.config, writer_factory=self._factory(port),
                               sync_lock_path=self.lock)
        result = queue.get_result(self.spool, queued["request_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(port.submissions, 1)
        self.assertEqual(patient_details.call_count, 2)

    @patch.object(worker.panel_data, "patient_details")
    def test_contact_change_after_preflight_stops_before_submit(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        request, queued = self._claim()

        def block_contact():
            self.contacts.write_text(json.dumps({self.chat: {"ai_enabled": True, "blocked": True}}))

        port = FakePort(on_prepare=block_contact)
        worker.process_booking(request, root=self.spool, session=Mock(), paths=self.paths,
                               config_path=self.config, writer_factory=self._factory(port),
                               sync_lock_path=self.lock)
        self.assertEqual(port.submissions, 0)
        result = queue.get_result(self.spool, queued["request_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "contact_not_eligible")
        self.assertEqual(port.submissions, 0)

    @patch.object(worker.panel_data, "patient_details")
    def test_missing_write_flag_fails_closed_without_opening_browser(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        self.config.write_text(json.dumps({"patient_directory": {
            "enabled": True, "clinic_id": self.clinic,
            "source_clinic_hash": self.payload["source_clinic_hash"],
        }}))
        request, queued = self._claim()
        session = Mock()
        worker.process_booking(request, root=self.spool, session=session, paths=self.paths,
                               config_path=self.config, writer_factory=self._factory(FakePort()),
                               sync_lock_path=self.lock)
        result = queue.get_result(self.spool, queued["request_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "appointment_writes_disabled")
        session.acquire.assert_not_called()

    @patch.object(worker.panel_data, "patient_details")
    def test_payload_cannot_assert_treatment_or_chart_verification(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        payload = dict(self.payload)
        payload["appointment_type"] = "cleaning"
        payload["type_id"] = "45"
        payload["duration_min"] = 60
        from datetime import timedelta
        start = datetime.fromisoformat(payload["requested_start"].replace("Z", "+00:00"))
        payload["requested_end"] = (start + timedelta(minutes=60)).isoformat()
        payload["confirmation"]["requested_start"] = payload["requested_start"]
        payload["confirmation"]["requested_end"] = payload["requested_end"]
        payload["policy_context"] = {
            "established_patient": True, "in_treatment": True,
            "no_added_procedure": True, "chart_verified": True,
        }
        payload["idempotency_key"] += ":cleaning"
        root_policy = json.loads(self.config.read_text())
        root_policy["appointment_policy"]["type_ids"]["cleaning"] = "45"
        root_policy["appointment_policy"]["appointments"]["cleaning"] = {
            "duration_minutes": 60,
            "eligible_professionals": ["liliane"],
            "auto_book": True,
            "requires": ["established_patient", "in_treatment", "chart_verified"],
        }
        self.config.write_text(json.dumps(root_policy))
        queue.initialize(self.spool)
        queued = queue.enqueue_booking(self.spool, payload)
        request = queue.claim_next(self.spool)
        port = FakePort()
        worker.process_booking(request, root=self.spool, session=Mock(), paths=self.paths,
                               config_path=self.config, writer_factory=self._factory(port),
                               sync_lock_path=self.lock)
        result = queue.get_result(self.spool, queued["request_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "team_confirmation_required")
        self.assertEqual(port.submissions, 0)

    @patch.object(worker.panel_data, "patient_details")
    def test_newer_inbound_invalidates_old_slot_confirmation(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        request, queued = self._claim()
        db = sqlite3.connect(self.messages)
        db.execute("INSERT INTO messages (chat_id, message_id, from_me, is_historical, timestamp) VALUES (?, ?, 0, 0, ?)",
                   (self.chat, "inbound-newer", datetime.now(timezone.utc).timestamp() + 1))
        db.commit()
        db.close()
        port = FakePort()
        worker.process_booking(request, root=self.spool, session=Mock(), paths=self.paths,
                               config_path=self.config, writer_factory=self._factory(port),
                               sync_lock_path=self.lock)
        result = queue.get_result(self.spool, queued["request_id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "confirmation_changed")
        self.assertEqual(port.submissions, 0)

    @patch.object(worker.panel_data, "patient_details")
    def test_reschedule_uses_fresh_complete_schedule_snapshot(self, patient_details):
        patient_details.return_value = {"patient_directory": {"status": "matched", "patient_id": "81"}, "pv_appointments": []}
        request_data = request_payload("reschedule")
        request_data["confirmation"]["kind"] = "offer_acceptance"
        config = json.loads(self.config.read_text())
        config["patient_directory"]["schedule_enabled"] = True
        config["appointment_policy"]["reschedule"] = {
            "auto_book_known_original": True,
            "team_only_types": [],
        }
        self.config.write_text(json.dumps(config))
        self.schedule.write_text(json.dumps({
            "schema_version": 1,
            "source": "prontuario_verde",
            "complete": True,
            "clinic_id": self.clinic,
            "source_clinic_hash": self.payload["source_clinic_hash"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "coverage_start": datetime.now(timezone.utc).isoformat(),
            "coverage_end": datetime.fromisoformat(request_data["expected_end"].replace("Z", "+00:00")).replace(
                year=datetime.now(timezone.utc).year + 1
            ).isoformat(),
            "professionals": [{"id": "22", "name": "Liliane"}],
            "appointments": [{
                "id": "55", "patient_id": "81", "professional_id": "22",
                "professional_name": "Liliane", "start": request_data["expected_start"],
                "end": request_data["expected_end"], "status": "agendado",
            }],
        }))
        self.assertEqual(worker.current_booking_request(request_data, self.paths, self.config)["clinic_id"], self.clinic)


if __name__ == "__main__":
    unittest.main()


class LiveBookingAuthorizationTests(unittest.TestCase):
    @patch("panel.server.BridgeClient")
    def test_requires_explicit_live_permission_for_every_alias(self, client):
        client.return_value.get_json_status.side_effect = [(200, {"botPaused": False}), (200, {"isSilenced": False}), (200, {"isSilenced": True})]
        with self.assertRaisesRegex(worker.BookingError, "chat_silenced_or_unavailable"):
            worker.require_live_booking_authorization(["123@s.whatsapp.net", "456@lid"])
        self.assertEqual(client.return_value.get_json_status.call_count, 3)

    @patch("panel.server.BridgeClient")
    def test_unknown_or_paused_global_state_never_authorizes(self, client):
        for response in [(None, None), (200, {}), (200, {"botPaused": 0}), (200, {"botPaused": True}), (503, {"botPaused": False})]:
            with self.subTest(response=response):
                client.return_value.get_json_status.return_value = response
                with self.assertRaisesRegex(worker.BookingError, "bot_paused_or_unavailable"):
                    worker.require_live_booking_authorization(["123@s.whatsapp.net"])

    @patch("panel.server.BridgeClient")
    def test_all_clear_reads_are_repeated_without_cache(self, client):
        client.return_value.get_json_status.side_effect = [(200, {"botPaused": False}), (200, {"isSilenced": False})] * 2
        worker.require_live_booking_authorization(["123@s.whatsapp.net"])
        worker.require_live_booking_authorization(["123@s.whatsapp.net"])
        self.assertEqual(client.return_value.get_json_status.call_count, 4)
