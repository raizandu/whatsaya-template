from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/scripts'))
from prontuario_verde_native_reconciliation import NativeBookingReader
from prontuario_verde_native_booking import NativeBookingError, request_marker
from tests.test_prontuario_verde_native_booking import FakeBrowser, CONFIG, request


class NativeReconciliationTests(unittest.TestCase):
    def reader(self):
        req=request(operation='reschedule', appointment_id='61',
                    expected_start='2031-09-24T09:00:00-03:00', expected_end='2031-09-24T09:30:00-03:00',
                    chat_id='5511999999999@s.whatsapp.net')
        reader=NativeBookingReader(FakeBrowser(),CONFIG,req,'unused')
        reader.patient={'id':'31','record_number':'403','phones':['5511999999999'],'name':'Pessoa Exemplo'}
        return reader,req

    def test_patient_selection_requires_a_separate_browser_and_unique_live_identity(self):
        reader,req=self.reader()
        with self.assertRaisesRegex(NativeBookingError,'patient_selection_unverified'):
            reader.select_patient(reader.browser,'31')
        with patch('prontuario_verde_native_reconciliation.RegistrationBrowser') as registration:
            registration.return_value.lookup.return_value={'matches':[reader.patient]}
            with patch('prontuario_verde_native_reconciliation.ProntuarioVerdeHermesPort.select_patient',return_value='31') as select:
                self.assertEqual(reader.select_patient(FakeBrowser(),'31'),'31')
                select.assert_called_once_with('31','Pessoa Exemplo','5511999999999')
            registration.return_value.lookup.return_value={'matches':[reader.patient,reader.patient]}
            with self.assertRaisesRegex(NativeBookingError,'patient_identity_unverified'):
                reader.select_patient(FakeBrowser(),'31')

    def test_original_patient_change_stops_before_editing_or_saving(self):
        reader,req=self.reader()
        event={"id":"61","record_number":"404","status":"AGENDADO"}
        with patch.object(reader,"_events",return_value=[event]),patch.object(reader.port,"_open_original_for_edit") as opening:
            with self.assertRaisesRegex(NativeBookingError,"original_appointment_changed"):
                reader.original_before_save(req)
            opening.assert_not_called()

    def test_changed_id_requires_explicit_inactive_original_not_absence(self):
        reader,req=self.reader()
        old={'id':'61','record_number':'403','status':'CANCELOU','start':req['expected_start'],'end':req['expected_end']}
        for rows in ([], [{**old,'status':'AGENDADO'}], [{**old,'record_number':'404'}]):
            with self.subTest(rows=rows),patch.object(reader,'_events',return_value=rows):
                with self.assertRaisesRegex(NativeBookingError,'old_appointment_state_unverified'):
                    reader.original_after_save(req)
        with patch.object(reader,'_events',return_value=[old]):
            result=reader.original_after_save(req)
        self.assertFalse(result['old_appointment_active'])
        self.assertEqual(result['old_patient_id'],'31')

    def test_verified_retained_id_proves_the_original_moved(self):
        reader,req=self.reader()
        reader.last_targets=[{'appointment_id':'61','start':req['requested_start']}]
        with patch.object(reader,'_events') as events:
            self.assertFalse(reader.original_after_save(req)['old_appointment_active'])
            events.assert_not_called()

    def test_concurrent_conflict_cannot_be_reported_as_success(self):
        reader,req=self.reader()
        event={"id":"72","record_number":"403","start":req["requested_start"],"end":req["requested_end"],"status":"AGENDADO"}
        with patch.object(reader,"_events",return_value=[event,{**event,"id":"73","record_number":"404"}]):
            with self.assertRaisesRegex(NativeBookingError,"post_save_conflict"):
                reader.targets(req)
        self.assertEqual(reader.last_targets,[])

    def test_targets_use_exact_record_time_and_persisted_identity(self):
        reader,req=self.reader()
        event={'id':'72','record_number':'403','start':req['requested_start'],'end':req['requested_end'],'status':'AGENDADO'}
        form={'agenda_id':'72','patient_id':'31','professional_id':'12','unit_id':'22','type_id':'42',
              'duration_min':30,'start':req['requested_start'],'end':req['requested_end'],'request_marker':request_marker(req)}
        with patch.object(reader,'_events',return_value=[event,{**event,'id':'73','record_number':'404','start':req['expected_start'],'end':req['expected_end']}]), \
             patch.object(reader.port,'inspect_original_form',return_value=form):
            result=reader.targets(req)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['request_marker'],request_marker(req))
        self.assertTrue(result['complete'])
        with patch.object(reader,'_events',return_value=[event]), \
             patch.object(reader.port,'inspect_original_form',return_value={**form,'patient_id':'99'}):
            with self.assertRaisesRegex(NativeBookingError,'original_appointment_changed'):
                reader.targets(req)
        self.assertEqual(reader.last_targets,[])


if __name__ == '__main__':
    unittest.main()
