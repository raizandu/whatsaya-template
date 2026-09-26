from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/scripts'))
import find_prontuario_verde_slots as finder
from prontuario_verde_availability import OpeningSnapshot, Interval


class FindSlotsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.schedule=Path(temporary.name)/'schedule.json'
        self.day=(datetime.now(finder.SAO_PAULO)+timedelta(days=2)).replace(hour=9,minute=0,second=0,microsecond=0)
        self.config={'patient_directory':{'enabled':True,'appointment_flow_enabled':True,'clinic_id':'test','source_clinic_hash':'a'*64},
                     'appointment_policy':{'professional_ids':{'professional':'22'},'unit_ids':['4'],'type_ids':{'evaluation':'44'},
                       'appointments':{'evaluation':{'auto_book':True,'eligible_professionals':['professional'],'duration_minutes':40}},
                       'reschedule':{'auto_book_known_original':True,'team_only_types':[]}}}
        self.args={'chat_id':'5511999999999@s.whatsapp.net','operation':'book','date':self.day.date().isoformat(),
                   'appointment_type':'evaluation','professional_key':'professional'}
        self.browser=Mock()
        self.original={'id':'61','patient_id':'81','professional_id':'22','start':self.day.isoformat(),
                       'end':(self.day+timedelta(minutes=40)).isoformat(),'status':'agendado'}
        self.form={'patient_id':'81','professional_id':'22','unit_id':'4','type_id':'44','duration_min':'40',
                   'start':self.original['start'],'end':self.original['end']}
        snapshot=OpeningSnapshot('a'*64,'22','4',self.day.date(),datetime.now(timezone.utc),
                                 (Interval(self.day,self.day+timedelta(hours=3)),),(),
                                 tuple(self.day+timedelta(minutes=15*i) for i in range(6)),True)
        for name,settings in (
            ('lookup_for_panel',{'return_value':{'status':'matched','patient_id':'81'}}),
            ('read_snapshot',{'return_value':snapshot}),('select_calendar_scope',{}),
            ('refresh_schedule',{'side_effect':lambda *a,**kw:self.schedule.write_text(json.dumps({'appointments':[self.original]}))}),
        ):
            patcher=patch.object(finder,name,**settings)
            patcher.start();self.addCleanup(patcher.stop)

    def call(self):
        return finder.find_slots(self.args,self.config,self.browser,schedule_path=self.schedule)

    def test_only_native_openings_produce_bounded_exact_duration_offers(self):
        result=self.call()
        self.assertEqual(len(result['slots']),3)
        self.assertEqual(result['query']['patient_id'],'81')
        self.assertEqual(result['query']['duration_min'],40)
        self.assertNotIn('requested_start',result['query'])
        self.assertEqual(result['slots'][0]['start'],self.day.isoformat())

    def test_unproved_treatment_and_wrong_professional_route_to_team(self):
        rule=self.config['appointment_policy']['appointments']['evaluation']
        rule['requires']=['in_treatment']
        with self.assertRaisesRegex(ValueError,'team_confirmation_required'):self.call()
        rule.pop('requires');self.args['professional_key']='another'
        with self.assertRaisesRegex(ValueError,'team_confirmation_required'):self.call()

    def test_reschedule_preserves_verified_original_and_never_offers_same_start(self):
        self.args.update(operation='reschedule',professional_key='invented',appointment_type='invented')
        with patch.object(finder,'ProntuarioVerdeHermesPort') as port:
            port.return_value.inspect_original_form.return_value=self.form
            result=self.call()
            port.return_value.submit_once.assert_not_called()
        self.assertEqual(result['query']['appointment_type'],'evaluation')
        self.assertEqual(result['query']['professional_key'],'professional')
        self.assertEqual(result['query']['appointment_id'],'61')
        self.assertTrue(all(s['start']!=self.original['start'] for s in result['slots']))
        self.assertIn('original_verified_at',result['query'])

    def test_reschedule_rejects_changed_patient_or_ambiguous_type(self):
        self.args['operation']='reschedule'
        with patch.object(finder,'ProntuarioVerdeHermesPort') as port:
            port.return_value.inspect_original_form.return_value={**self.form,'patient_id':'999'}
            with self.assertRaisesRegex(ValueError,'original_appointment_changed'):self.call()
            port.return_value.inspect_original_form.return_value=self.form
            self.config['appointment_policy']['type_ids']['other']='44'
            self.config['appointment_policy']['appointments']['other']=self.config['appointment_policy']['appointments']['evaluation']
            with self.assertRaisesRegex(ValueError,'original_appointment_type_ambiguous'):self.call()

    def test_unmatched_identity_or_disabled_flow_does_not_read_calendar(self):
        with patch.object(finder,'lookup_for_panel',return_value={'status':'ambiguous'}),patch.object(finder,'read_snapshot') as read:
            with self.assertRaisesRegex(ValueError,'patient_identity_unverified'):self.call()
            read.assert_not_called()
        self.config['patient_directory']['appointment_flow_enabled']=False
        with self.assertRaisesRegex(ValueError,'appointment_flow_disabled'):self.call()


if __name__=='__main__':unittest.main()
