import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pv_worker', Path(__file__).resolve().parents[1] / 'deploy/scripts/process_prontuario_verde_actions.py')
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)

REQUEST = dict(appointment_id='901', patient_id='123', professional_id='77',
               expected_start='2026-10-05T09:00:00-03:00', expected_end='2026-10-05T09:30:00-03:00',
               clinic_id='example', source_clinic_hash='a' * 64, request_id='example')
EVENT = dict(id='901', start=REQUEST['expected_start'], end=REQUEST['expected_end'], professionals=['77'], status='AGENDADO')


class WorkerTests(unittest.TestCase):
    def test_equivalent_timezones_match_but_naive_timestamps_do_not(self):
        self.assertTrue(worker.same_time(REQUEST['expected_start'], '2026-10-05T12:00:00Z'))
        self.assertFalse(worker.same_time(REQUEST['expected_start'], '2026-10-05T09:00:00'))

    def test_event_must_match_id_professional_and_exact_window(self):
        self.assertEqual(worker.validate_event(EVENT, REQUEST), EVENT)
        for changed in ({'id': '902'}, {'professionals': ['78']}, {'end': '2026-10-05T10:00:00-03:00'}):
            with self.subTest(changed=changed), self.assertRaises(worker.CancelError):
                worker.validate_event(dict(EVENT, **changed), REQUEST)

    def test_patient_changed_aborts_before_cancel(self):
        browser = unittest.mock.Mock()
        adapter = worker.CancellationBrowser(browser)
        adapter.wait = lambda *a: {'id': '901', 'patient': '999', 'status': 'AGE'}
        with self.assertRaisesRegex(worker.CancelError, 'patient_changed'):
            adapter.open_event(REQUEST)
        self.assertFalse(adapter.submitted)
        self.assertFalse(any('swal2-deny' in c.args[0] for c in browser.evaluate.call_args_list))

    def test_live_cancelled_label_is_recognized(self):
        self.assertTrue(worker.cancelled(dict(EVENT, status="CANCELOU")))
        self.assertFalse(worker.cancelled(EVENT))

    def test_already_cancelled_is_read_only(self):
        browser = unittest.mock.Mock()
        adapter = worker.CancellationBrowser(browser)
        adapter.open_calendar = lambda r: dict(EVENT, status='CANCELADO PELA CLINICA')
        adapter.open_event = lambda r: {'id': '901', 'patient': '123', 'status': 'CAN'}
        self.assertTrue(worker.cancelled(adapter.cancel(REQUEST, lambda: None)))
        browser.evaluate.assert_not_called()
        self.assertFalse(adapter.submitted)

    def test_cancellation_uses_only_deny_and_requires_independent_verification(self):
        browser = unittest.mock.Mock()
        adapter = worker.CancellationBrowser(browser)
        adapter.open_calendar = lambda r: EVENT
        adapter.open_event = lambda r: {'id': '901', 'patient': '123', 'status': 'AGE'}
        adapter.wait = lambda *a, **kw: True
        adapter.read_event = lambda r: EVENT
        adapter.open_calendar_after_reload = lambda r: EVENT
        with self.assertRaisesRegex(worker.CancelError, 'cancellation_unverified'):
            adapter.cancel(REQUEST, lambda: None)
        expressions = [call.args[0] for call in browser.evaluate.call_args_list]
        self.assertTrue(any('swal2-deny' in expression for expression in expressions))
        self.assertFalse(any('swal2-confirm' in expression for expression in expressions))
        self.assertTrue(adapter.submitted)

    def test_snapshot_update_preserves_other_patient_and_rejects_moved_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'appointments.json'
            row = dict(id='901', patient_id='123', start=REQUEST['expected_start'], end=REQUEST['expected_end'], status='agendado')
            other = dict(row, id='902', patient_id='456')
            source = dict(clinic_id='example', source_clinic_hash='a' * 64, appointments=[row, other])
            path.write_text(json.dumps(source))
            worker.record_cancelled(REQUEST, path)
            result = json.loads(path.read_text())
            self.assertEqual(result['appointments'][0]['status'], 'cancelado')
            self.assertEqual(result['appointments'][1], other)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            before = path.read_bytes()
            with self.assertRaises(worker.CancelError):
                worker.record_cancelled(dict(REQUEST, expected_start='2026-10-06T09:00:00-03:00'), path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
