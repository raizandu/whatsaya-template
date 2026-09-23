import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPTS = Path(__file__).resolve().parents[1] / 'deploy/scripts'
sys.path.insert(0, str(SCRIPTS))
import sync_prontuario_verde_schedule as schedule

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
CONFIG = dict(clinic_id='clinic', source_clinic_hash='a' * 64)
DIRECTORY = dict(source='prontuario_verde', complete=True, **CONFIG,
    generated_at=NOW.isoformat(), patients=[dict(id='123', record_number='403', phones=[])])
EVENT = dict(id='901', record_number='403', professional_id='77', status='AGENDADO',
    start='2026-09-24T09:30:00-03:00', end='2026-09-24T10:00:00-03:00')


def build(events=None, directory=None):
    return schedule.build_snapshot(dict(professionals=[dict(id='77', name='Dra. Exemplo')],
        events=events if events is not None else [EVENT]), directory or DIRECTORY, CONFIG,
        NOW, NOW + timedelta(days=366), now=NOW)


class ScheduleSyncTests(unittest.TestCase):
    def test_joins_only_exact_record_code_and_discards_patient_content(self):
        row = dict(EVENT, title='Private patient title', name='Private patient name')
        result = build([row])
        self.assertEqual(result['appointments'][0]['patient_id'], '123')
        self.assertNotIn('Private', json.dumps(result))
        self.assertEqual(result['appointments'][0]['professional_name'], 'Dra. Exemplo')

    def test_agenda_receives_patient_label_and_all_professionals(self):
        result = build([dict(EVENT, patient_name="Paciente Exemplo")])
        self.assertEqual(result['appointments'][0]['patient_name'], 'Paciente Exemplo')
        self.assertEqual(result['appointments'][0]['record_number'], '403')
        self.assertEqual(result['professionals'], [{'id': '77', 'name': 'Dra. Exemplo'}])
        self.assertEqual(build([])['professionals'], result['professionals'])

    def test_cancelled_unlinked_and_unknown_status_do_not_become_next_appointments(self):
        rows = [dict(EVENT, id='1', status='CANCELOU'), dict(EVENT, id='2', record_number=None),
                dict(EVENT, id='3', record_number='999'), dict(EVENT, id='4', status='UNKNOWN')]
        result = build(rows)
        self.assertEqual(result['appointments'], [])
        self.assertEqual(result['skipped_events'], 4)

    def test_duplicate_codes_events_stale_or_cross_clinic_fail_closed(self):
        for directory in (dict(DIRECTORY, clinic_id='other'),
                          dict(DIRECTORY, source_clinic_hash='b' * 64),
                          dict(DIRECTORY, complete=False),
                          dict(DIRECTORY, generated_at=(NOW - timedelta(hours=25)).isoformat()),
                          dict(DIRECTORY, patients=DIRECTORY['patients'] * 2)):
            with self.subTest(directory=directory), self.assertRaises(schedule.SyncError):
                build(directory=directory)
        with self.assertRaises(schedule.SyncError):
            build([EVENT, EVENT])

    def test_invalid_time_or_unknown_professional_is_not_published(self):
        for changes in ({'start': '2026-09-24T09:30:00'}, {'end': EVENT['start']},
                        {'professional_id': '999'}, {'start': '2028-01-01T09:30:00-03:00'}):
            with self.subTest(changes=changes), self.assertRaises(schedule.SyncError):
                build([dict(EVENT, **changes)])

    def test_cancellation_removes_only_its_row_without_extending_cache_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'schedule.json'
            snapshot = build([EVENT, dict(EVENT, id='902')])
            path.write_text(json.dumps(snapshot))
            schedule.invalidate_cancelled(dict(CONFIG, appointment_id='901'), path)
            result = json.loads(path.read_text())
            self.assertEqual([r['id'] for r in result['appointments']], ['902'])
            self.assertEqual(result['generated_at'], snapshot['generated_at'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
