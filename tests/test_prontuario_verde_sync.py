import importlib.util
from functools import partial
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/scripts/sync_prontuario_verde.py'
spec = importlib.util.spec_from_file_location('pv_sync', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
collect = partial(sync.collect_pages, source_clinic_hash="a" * 64)


def page(patient_id='1', *, has_next=False, header='CUIDAR ODONTOLOGIA', filters=None):
    return {'rows': [{'id': patient_id, 'phone_text': '(11) 99999-1234\n(11) 4444-1234',
                      'name': 'Must never persist', 'cpf': 'Must never persist'}],
            'has_next': has_next, 'header': header, 'active_filters': filters or []}


class Browser:
    source_clinic_hash = "a" * 64
    def __init__(self, pages):
        self.pages = iter(pages)
        self.advances = 0

    def evaluate(self, expression):
        if expression == sync.NEXT_SCRIPT:
            self.advances += 1
            return True
        return next(self.pages)


class DirectorySyncTests(unittest.TestCase):
    def test_appointment_without_patient_id_is_counted_but_never_matched(self):
        p = page('')
        p['rows'][0]['appointment_id'] = '321'
        result = collect(Browser([p]), 'clinic', 'CUIDAR ODONTOLOGIA')
        self.assertEqual(result['patients'], [])
        self.assertEqual(result['unlinked_appointment_rows'], 1)
        self.assertNotIn('321', json.dumps(result))

    def test_duplicate_unlinked_appointment_aborts_scan(self):
        p = page('', has_next=True)
        p['rows'][0]['appointment_id'] = '321'
        with self.assertRaisesRegex(sync.SyncError, 'duplicate_or_changed_pagination'):
            collect(Browser([p, p]), 'clinic', 'CUIDAR ODONTOLOGIA')

    def test_source_account_id_is_bound_independently_of_display_name(self):
        browser = Browser([page()])
        browser.source_clinic_hash = 'b' * 64
        with self.assertRaisesRegex(sync.SyncError, 'source_clinic_mismatch'):
            collect(browser, 'clinic', 'CUIDAR ODONTOLOGIA')

    def test_collects_complete_pages_with_only_required_fields(self):
        browser = Browser([page(has_next=True), page('2')])
        snapshot = collect(browser, 'clinic', 'Cuidar Odontologia')
        self.assertTrue(snapshot['complete'])
        self.assertEqual(browser.advances, 1)
        self.assertEqual(len(snapshot['patients']), 2)
        self.assertEqual(snapshot['patients'][0],
                         {'id': '1', 'phones': ['551144441234', '5511999991234']})
        self.assertNotIn('Must never persist', json.dumps(snapshot))

    def test_wrong_clinic_or_filtered_result_cannot_be_published(self):
        for invalid in [page(header='ANOTHER CLINIC'), page(filters=['P13_SEARCH'])]:
            with self.subTest(invalid=invalid), self.assertRaises(sync.SyncError):
                collect(Browser([invalid]), 'clinic', 'Cuidar Odontologia')

    def test_header_substring_does_not_authorize_another_clinic(self):
        with self.assertRaisesRegex(sync.SyncError, 'clinic_mismatch'):
            collect(Browser([page(header='OTHER CUIDAR ODONTOLOGIA')]),
                               'clinic', 'CUIDAR ODONTOLOGIA')

    def test_repeated_patient_id_aborts_instead_of_trusting_pagination(self):
        with self.assertRaisesRegex(sync.SyncError, 'duplicate_or_changed_pagination'):
            collect(Browser([page(has_next=True), page()]), 'clinic', 'CUIDAR ODONTOLOGIA')

    def test_partial_scan_at_page_limit_is_rejected(self):
        with self.assertRaisesRegex(sync.SyncError, 'pagination_limit'):
            collect(Browser([page(has_next=True)]), 'clinic', 'CUIDAR ODONTOLOGIA', 1)

    def test_empty_or_malformed_page_is_not_complete(self):
        for invalid in [None, {}, {**page(), 'rows': []}, {**page(), 'has_next': None},
                        {**page(), 'rows': [{'id': '', 'phone_text': '123'}]}]:
            with self.subTest(invalid=invalid), self.assertRaises(sync.SyncError):
                collect(Browser([invalid]), 'clinic', 'CUIDAR ODONTOLOGIA')

    def test_missing_phone_is_kept_as_unmatchable_patient(self):
        p = page()
        p['rows'][0]['phone_text'] = ''
        snapshot = collect(Browser([p]), 'clinic', 'CUIDAR ODONTOLOGIA')
        self.assertEqual(snapshot['patients'][0]['phones'], [])

    def test_parse_does_not_invent_ninth_digit_or_use_local_number_without_ddd(self):
        self.assertEqual(sync.extract_phones('99999-1234'), [])
        self.assertEqual(sync.extract_phones('+55 (11) 8888-1234'), ['551188881234'])
        self.assertEqual(sync.extract_phones('(11) 99999-1234 / (11) 99999-1234'), ['5511999991234'])

    def test_atomic_file_has_private_permissions_and_replaces_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'patient_directory.json'
            target.write_text('old')
            snapshot = collect(Browser([page()]), 'clinic', 'CUIDAR ODONTOLOGIA')
            sync.write_snapshot(target, snapshot)
            self.assertEqual(json.loads(target.read_text()), snapshot)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(d).iterdir()), [target])

    def test_failure_during_scan_leaves_previous_snapshot_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'patient_directory.json'
            target.write_text('previous')
            with self.assertRaises(sync.SyncError):
                snapshot = collect(Browser([page(filters=['P13_SEARCH'])]),
                                              'clinic', 'CUIDAR ODONTOLOGIA')
                sync.write_snapshot(target, snapshot)
            self.assertEqual(target.read_text(), 'previous')


if __name__ == '__main__':
    unittest.main()
