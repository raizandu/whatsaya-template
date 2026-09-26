from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import whatsapp_manager as wm
import prontuario_verde_booking_queue as queue
from prontuario_verde_booking_flow import offer_reply
from tests.test_prontuario_verde_booking_queue import request_payload, verified_result


class ClinicalChatTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.payload=request_payload()
        self.chat=self.payload['chat_id']
        self.identity={k:self.payload[k] for k in ('clinic_id','source_clinic_hash','patient_id')}
        self.config={'patient_directory':{'enabled':True,'appointment_write_enabled':True,
                                         'appointment_flow_enabled':True,**self.identity},
                     'appointment_policy':{'location_label':'na clínica em Cidade Exemplo',
                                            'appointment_labels':{'evaluation':'avaliação geral'},
                                            'professional_labels':{'liliane':'Dra. Exemplo'}}}
        self.inbound={'message_id':'query-message','text':'Quero uma avaliação amanhã','at':datetime.now(timezone.utc).timestamp()}
        self.token=wm._inbound_record_token(self.inbound)
        self.context=lambda *_: (self.chat,self.inbound,wm._inbound_record_token(self.inbound),self.config,self.identity)
        for target,value in (('_PV_FLOW_PATH',self.root/'flow.db'),('_PV_BOOKING_SPOOL',self.root/'queue')):
            p=patch.object(wm,target,value);p.start();self.addCleanup(p.stop)
        for target,kwargs in (('_pv_ready',{'return_value':True}),('_pv_context',{'side_effect':self.context}),
                              ('_pv_config',{'return_value':self.config}),
                              ('_current_inbound_record',{'side_effect':lambda *_:dict(self.inbound)}),
                              ('_assert_delivery_allowed',{'return_value':None})):
            p=patch.object(wm,target,**kwargs);p.start();self.addCleanup(p.stop)
        queue.initialize(wm._PV_BOOKING_SPOOL)

    def offer(self):
        query={k:v for k,v in self.payload.items() if k not in {'confirmation','created_at','idempotency_key','requested_start','requested_end'}}
        slots=[{'start':self.payload['requested_start'],'end':self.payload['requested_end']}]
        completed=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'ok','query':query,'slots':slots}))
        with patch.object(wm.subprocess,'run',return_value=completed):
            result=json.loads(wm._handle_pv_find_slots({'date':'2031-09-24','operation':'book'},session_id='session'))
        self.assertEqual(result['status'],'offered')
        text=wm._pv_reply_for_inbound(self.chat,self.inbound)
        self.assertIn('Cidade Exemplo',text)
        self.assertNotIn('foi marcada',text)
        return text

    def accept(self):
        self.inbound={'message_id':'accepted-message','text':'1','at':datetime.now(timezone.utc).timestamp()}
        return json.loads(wm._handle_pv_accept_offer({},session_id='session'))

    def test_find_delivery_acceptance_queue_proof_and_reply(self):
        text=self.offer()
        self.assertTrue(wm._pv_flow().mark_delivered(self.chat,text,'real-outbound'))
        self.assertEqual(self.accept()['status'],'pending')
        self.assertIn('conferindo',wm._pv_reply_for_inbound(self.chat,self.inbound))
        request=queue.claim_next(wm._PV_BOOKING_SPOOL)
        self.assertTrue(wm._pv_flow().validates_request(request))
        queue.finish(wm._PV_BOOKING_SPOOL,request['request_id'],'succeeded','verified',verified_result(request))
        with patch.object(wm,'_deliver_contact_reply',return_value='result-outbound') as deliver:
            wm._tick_pv_booking_results()
            wm._tick_pv_booking_results()
        deliver.assert_called_once()
        self.assertIn('Sua consulta foi marcada',deliver.call_args.args[1])
        self.assertEqual(wm._pv_flow().get(self.chat)['phase'],'done')

    def test_acceptance_before_delivery_never_reaches_worker(self):
        self.offer()
        self.assertEqual(self.accept()['status'],'error')
        self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))

    def test_uncertain_write_routes_to_team_without_success_or_replay(self):
        text=self.offer()
        wm._pv_flow().mark_delivered(self.chat,text,'real-outbound')
        self.accept()
        request=queue.claim_next(wm._PV_BOOKING_SPOOL)
        queue.finish(wm._PV_BOOKING_SPOOL,request['request_id'],'needs_review','post_save_unverified')
        with patch.object(wm,'_deliver_contact_reply',return_value='handoff-outbound') as deliver:
            wm._tick_pv_booking_results()
        self.assertIn('Não consegui confirmar',deliver.call_args.args[1])
        self.assertIsNotNone(deliver.call_args.kwargs['handoff_details'])
        self.assertEqual(wm._pv_flow().get(self.chat)['phase'],'review')

    def test_new_inbound_during_source_read_discards_old_offer(self):
        query={k:v for k,v in self.payload.items() if k not in {'confirmation','created_at','idempotency_key','requested_start','requested_end'}}
        def source(*args,**kwargs):
            self.inbound={'message_id':'newer','text':'Não quero mais','at':datetime.now(timezone.utc).timestamp()}
            return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'ok','query':query,'slots':[{'start':self.payload['requested_start'],'end':self.payload['requested_end']}]}))
        with patch.object(wm.subprocess,'run',side_effect=source):
            result=json.loads(wm._handle_pv_find_slots({'date':'2031-09-24'},session_id='session'))
        self.assertEqual(result['status'],'error')
        self.assertIsNone(wm._pv_flow().get(self.chat))

    def test_paused_contact_does_not_consume_notification(self):
        text=self.offer();wm._pv_flow().mark_delivered(self.chat,text,'real-outbound');self.accept()
        request=queue.claim_next(wm._PV_BOOKING_SPOOL)
        queue.finish(wm._PV_BOOKING_SPOOL,request['request_id'],'needs_review','post_save_unverified')
        with patch.object(wm,'_assert_delivery_allowed',side_effect=ValueError('paused')),patch.object(wm,'_deliver_contact_reply') as deliver:
            wm._tick_pv_booking_results()
        deliver.assert_not_called()
        self.assertEqual(wm._pv_flow().get(self.chat)['phase'],'queued')


class ClinicalContextTests(unittest.TestCase):
    def test_clinic_prompt_uses_pv_status_without_inactive_google_instruction(self):
        args=dict(name_block="",whatsapp_soul="persona",contact_block="",rules_content="regras",
                  chat_id="fixture",calendar_enabled=False,history_section="preferência antiga",
                  conversation_state="",language_hint="",patient_directory_context="contexto PV")
        with patch.object(wm,'_pv_enabled_for_chat',return_value=True):
            prompt=wm._build_generic_support_context(**args)['context']
        self.assertIn('AGENDA CLÍNICA PV ATIVA',prompt)
        self.assertIn('pv_find_slots',prompt)
        self.assertIn('preferência antiga não é uma confirmação atual',prompt)
        self.assertNotIn('AGENDA INATIVA',prompt)
        self.assertNotIn('AGENDA COMERCIAL',prompt)
        self.assertIn('contexto PV',prompt)
        with patch.object(wm,'_pv_enabled_for_chat',return_value=False):
            inactive=wm._build_generic_support_context(**args)['context']
        self.assertIn('AGENDA INATIVA',inactive)
        self.assertNotIn('AGENDA CLÍNICA PV ATIVA',inactive)

    def test_clinical_status_applies_only_to_pilot_contact(self):
        cfg={'patient_directory':{'appointment_allowed_chats':['5511999999999@s.whatsapp.net']}}
        with patch.object(wm,'_pv_config',return_value=cfg):
            self.assertTrue(wm._pv_enabled_for_chat('5511999999999@s.whatsapp.net'))
            self.assertFalse(wm._pv_enabled_for_chat('5511888888888@s.whatsapp.net'))
        with patch.object(wm,'_pv_config',side_effect=ValueError('disabled')):
            self.assertFalse(wm._pv_enabled_for_chat('5511999999999@s.whatsapp.net'))

    def test_live_context_rejects_other_chat_urgent_and_stale_messages(self):
        chat='5511999999999@s.whatsapp.net'
        inbound={'message_id':'real-inbound','text':'Quero uma avaliação','at':1}
        token=wm._inbound_record_token(inbound)
        config={'patient_directory':{'appointment_allowed_chats':[chat],
                'clinic_id':'clinic','source_clinic_hash':'a'*64}}
        identity={'status':'matched','patient_id':'31'}
        with patch.object(wm,'_pv_config',return_value=config), \
             patch.object(wm,'_calendar_tool_context',return_value=(chat,inbound,token)), \
             patch.object(wm,'_current_inbound_record',return_value=inbound) as current, \
             patch.object(wm,'_assert_delivery_allowed') as gate, \
             patch.object(wm,'_pv_flow') as flow, \
             patch.object(wm.patient_directory,'lookup_for_panel',return_value=identity):
            self.assertEqual(wm._pv_context({})[4]['patient_id'],'31')
            gate.assert_called_once_with(chat,require_ai_access=True)
            config['patient_directory']['appointment_allowed_chats']=[]
            with self.assertRaisesRegex(ValueError,'appointment_pilot_scope'):
                wm._pv_context({})
            config['patient_directory']['appointment_allowed_chats']=[chat]
            current.return_value={**inbound,'message_id':'newer'}
            with self.assertRaisesRegex(ValueError,'current_message_required'):
                wm._pv_context({})
            current.return_value=inbound
            inbound['text']='quero falar com uma pessoa'
            with self.assertRaisesRegex(ValueError,'team_confirmation_required'):
                wm._pv_context({})
            self.assertTrue(flow.return_value.note_inbound.call_args.kwargs['requires_team'])


if __name__=='__main__':unittest.main()
