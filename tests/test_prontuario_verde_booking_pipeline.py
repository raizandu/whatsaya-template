"""Queue/writer contract test with a simulated PV port and no browser writes."""

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import prontuario_verde_booking_queue as queue
from tests.test_prontuario_verde_booking_queue import request_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "scripts"))
from prontuario_verde_appointment_writer import ProntuarioVerdeAppointmentWriter  # noqa: E402


class SimulatedPort:
    def __init__(self):
        self.submissions = 0

    def prepare(self, request):
        result = {
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
        if request["operation"] == "reschedule":
            result["original_appointment"] = {
                "appointment_id": request["appointment_id"],
                "patient_id": request["patient_id"],
                "professional_id": request["professional_id"],
                "unit_id": request["unit_id"],
                "type_id": request["type_id"],
                "procedure_id": request.get("procedure_id"),
                "duration_min": request["duration_min"],
                "start": request["expected_start"],
                "end": request["expected_end"],
            }
        return result

    def submit_once(self, request):
        self.submissions += 1
        raise TimeoutError("simulated response loss after save")

    def reconcile_after_save(self, request):
        result = {
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
        if request["operation"] == "reschedule":
            result.update({
                "old_appointment_id": request["appointment_id"],
                "old_patient_id": request["patient_id"],
                "old_professional_id": request["professional_id"],
                "old_unit_id": request["unit_id"],
                "old_type_id": request["type_id"],
                "old_procedure_id": request.get("procedure_id"),
                "old_duration_min": request["duration_min"],
                "old_start": request["expected_start"],
                "old_end": request["expected_end"],
                "old_appointment_active": False,
            })
        return result


class BookingPipelineContractTests(unittest.TestCase):
    def test_exact_reconciliation_is_accepted_by_durable_queue(self):
        for operation in ("book", "reschedule"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                queue.initialize(root)
                payload = request_payload(operation)
                enqueue = queue.enqueue_reschedule if operation == "reschedule" else queue.enqueue_booking
                queued = enqueue(root, payload)
                claimed = queue.claim_next(root)
                port = SimulatedPort()
                writer = ProntuarioVerdeAppointmentWriter(port, {
                    "enabled": True,
                    "appointment_write_enabled": True,
                    "clinic_id": claimed["clinic_id"],
                    "source_clinic_hash": claimed["source_clinic_hash"],
                })
                proof = writer.reschedule(claimed) if operation == "reschedule" else writer.book(claimed)
                finished = queue.finish(root, queued["request_id"], "succeeded", "verified", proof)
                self.assertEqual(finished["status"], "succeeded")
                self.assertEqual(port.submissions, 1)


if __name__ == "__main__":
    unittest.main()
