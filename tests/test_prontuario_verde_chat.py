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
        self.assertIn('Com a Dra. Exemplo, tenho',text)
        self.assertNotIn('Cidade Exemplo',text)
        self.assertNotIn('avaliação geral',text)
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

    def test_existing_appointment_inquiry_does_not_start_availability_or_offer(self):
        for message in ['Quando é minha manutenção?', 'Quero confirmar minha consulta',
                        'Confirmo minha presença']:
            with self.subTest(message=message), patch.object(wm.subprocess,'run') as source:
                self.inbound={**self.inbound,'text':message}
                result=json.loads(wm._handle_pv_find_slots({'date':'2031-09-24','operation':'book'},session_id='session'))
                self.assertEqual(result['status'],'existing_appointment_inquiry')
                source.assert_not_called()
                self.assertIsNone(wm._pv_flow().get(self.chat))
                self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))

    def test_clinical_read_returns_bounded_facts_without_booking(self):
        evidence = {'planned': [{'title': 'REMOÇÃO', 'status': 'AG. APROVAÇÃO'}],
                    'performed': [{'title': 'CONSULTA', 'executed_on': '2025-07-09'}],
                    'evolutions': [], 'treatment_active': 'unknown'}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps({
            'status': 'ok', 'clinical_evidence': evidence}))
        with patch.object(wm.subprocess, 'run', return_value=completed):
            result = json.loads(wm._handle_pv_read_treatment({}, session_id='session'))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['clinical_evidence'], evidence)
        self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))

    def test_new_inbound_during_clinical_read_discards_old_facts(self):
        def source(*args, **kwargs):
            self.inbound = {'message_id': 'newer', 'text': 'Outro assunto',
                            'at': datetime.now(timezone.utc).timestamp()}
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'status': 'ok', 'clinical_evidence': {'planned': []}}))
        with patch.object(wm.subprocess, 'run', side_effect=source):
            result = json.loads(wm._handle_pv_read_treatment({}, session_id='session'))
        self.assertEqual(result['status'], 'error')

    def test_conditional_slot_result_preserves_reason_for_dentist_review(self):
        completed = SimpleNamespace(returncode=0, stdout=json.dumps({
            'status': 'team', 'code': 'team_confirmation_required',
            'clinical_evidence': {'previous_care_verified': True,
                                  'pending_approval_count': 3}}))
        with patch.object(wm.subprocess, 'run', return_value=completed):
            result = json.loads(wm._handle_pv_find_slots({'date': '2031-09-24', 'operation': 'book'},
                                                         session_id='session'))
        self.assertEqual(result['status'], 'team_confirmation_required')
        self.assertEqual(result['clinical_evidence']['pending_approval_count'], 3)
        self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))

    def test_expired_choice_explicitly_requests_fresh_availability(self):
        text=self.offer();wm._pv_flow().mark_delivered(self.chat,text,'real-outbound')
        flow=wm._pv_flow()
        with flow._db() as db:
            state=flow._load(db,self.chat)
            state['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            flow._save(db,self.chat,state)
        self.assertEqual(self.accept()['status'],'expired')
        self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))
        with patch.object(wm,'_pv_ready',return_value=True):
            prompt=wm._pv_booking_prompt_context(self.chat,self.inbound)
        self.assertIn('A oferta anterior expirou',prompt)
        self.assertIn('pv_find_slots',prompt)
        self.assertIn('pv_read_treatment',prompt)
        self.assertIn('"period": "any"',prompt)

    def test_uncertain_write_routes_to_team_without_success_or_replay(self):
        text=self.offer()
        wm._pv_flow().mark_delivered(self.chat,text,'real-outbound')
        self.accept()
        request=queue.claim_next(wm._PV_BOOKING_SPOOL)
        queue.finish(wm._PV_BOOKING_SPOOL,request['request_id'],'needs_review','post_save_unverified')
        with patch.object(wm,'_deliver_contact_reply',return_value='handoff-outbound') as deliver:
            wm._tick_pv_booking_results()
        self.assertIn('está em conferência',deliver.call_args.args[1])
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

    def test_thanks_stays_neutral_when_booking_completes_before_reply(self):
        text=self.offer();wm._pv_flow().mark_delivered(self.chat,text,'real-outbound');self.accept()
        request=queue.claim_next(wm._PV_BOOKING_SPOOL)
        thanks={'message_id':'thanks-message','text':'ok obrigado','at':datetime.now(timezone.utc).timestamp()}
        self.assertEqual(wm._pv_reply_for_inbound(self.chat,thanks),'Por nada!')
        queue.finish(wm._PV_BOOKING_SPOOL,request['request_id'],'succeeded','verified',verified_result(request))
        with patch.object(wm,'_deliver_contact_reply',return_value='result-outbound'):
            wm._tick_pv_booking_results()
        self.assertEqual(wm._pv_flow().get(self.chat)['phase'],'done')
        self.assertEqual(wm._pv_reply_for_inbound(self.chat,thanks),'Por nada!')
        prompt=wm._pv_booking_prompt_context(self.chat,thanks)
        self.assertIn('já foi confirmado',prompt)
        for message in ['obrigado, mas quero cancelar','obrigado, estou com dor','obrigado, qual o endereço?']:
            self.assertEqual(wm._pv_reply_for_inbound(self.chat,{**thanks,'text':message}),'')
        self.assertIsNone(queue.claim_next(wm._PV_BOOKING_SPOOL))


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


class ClinicalAdmissionTests(unittest.TestCase):
    def test_patient_intent_and_greeting_enter_only_configured_clinic(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/"config.json"
            contacts=Path(folder)/"contacts.json"
            config.write_text(json.dumps({"patient_directory":{"enabled":True,"clinic_id":"test-clinic"}}))
            with patch.object(wm,"_PATIENT_DIRECTORY_CONFIG_PATH",config), patch.object(wm,"_PERSONAL_CONTACTS_PATH",contacts), patch.object(wm,"_is_contact_blocked",return_value=False):
                for text in ("Oi, queria marcar uma avaliação", "Oi", "Quero remarcar minha consulta", "Meu dente está doendo"):
                    contacts.write_text("{}")
                    allowed,_=wm._ensure_contact_ai_access("5511999999999@s.whatsapp.net","5511999999999@s.whatsapp.net",message_text=text)
                    self.assertTrue(allowed,text)
                self.assertFalse(wm._has_commercial_scope_signal("Qual a capital da França?"))
                self.assertFalse(wm._ensure_contact_ai_access("5511999999999@s.whatsapp.net","5511999999999@s.whatsapp.net",message_text="Quero avaliação",is_historical=True)[0])
                contacts.write_text(json.dumps({"5511999999999@s.whatsapp.net":{"ai_enabled":False,"in_flow":False,"ai_disabled_reason":"owner_optout","ai_policy_version":2}}))
                self.assertFalse(wm._ensure_contact_ai_access("5511999999999@s.whatsapp.net","5511999999999@s.whatsapp.net",message_text="Quero avaliação")[0])
                config.write_text("{}")
                self.assertFalse(wm._has_commercial_scope_signal("Oi, queria marcar uma avaliação"))
                self.assertFalse(wm._has_commercial_scope_signal("Oi"))
                self.assertTrue(wm._has_commercial_scope_signal("Quero contratar a AYA"))

    def test_imported_test_pause_resumes_only_for_clinic_evidence_and_all_safe_aliases(self):
        phone = "5511999999999@s.whatsapp.net"
        lid = "123456789@lid"
        paused = {"ai_enabled": False, "in_flow": False,
                  "flow_origin": "fullsync_test_pause", "ai_disabled_reason": "test_mode",
                  "ai_policy_version": 2}
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            contacts = Path(folder) / "contacts.json"
            config.write_text(json.dumps({"patient_directory": {
                "enabled": True, "clinic_id": "test-clinic",
                "source_clinic_hash": "a" * 64,
            }}))
            contacts.write_text(json.dumps({phone: {**paused, "lid": lid}, lid: dict(paused)}))
            with patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config), \
                 patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts), \
                 patch.object(wm, "_is_contact_blocked", return_value=False), \
                 patch.object(wm.patient_directory, "lookup_patient", return_value={"status": "matched"}) as lookup:
                allowed, reason = wm._ensure_contact_ai_access(phone, phone, message_text="Preciso de ajuda")
                self.assertTrue(allowed)
                self.assertEqual(reason, "clinic-import-inbound")
                self.assertEqual(lookup.call_count, 1)
                resumed = json.loads(contacts.read_text())
                for key in (phone, lid):
                    self.assertTrue(resumed[key]["ai_enabled"])
                    self.assertTrue(resumed[key]["in_flow"])
                    self.assertNotIn("ai_disabled_reason", resumed[key])

    def test_imported_test_pause_keeps_optouts_and_unrelated_messages_off(self):
        phone = "5511999999999@s.whatsapp.net"
        lid = "123456789@lid"
        paused = {"ai_enabled": False, "in_flow": False,
                  "flow_origin": "fullsync_test_pause", "ai_disabled_reason": "test_mode"}
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            contacts = Path(folder) / "contacts.json"
            config.write_text(json.dumps({"patient_directory": {"enabled": True, "clinic_id": "test-clinic"}}))
            with patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config), \
                 patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts), \
                 patch.object(wm, "_is_contact_blocked", return_value=False), \
                 patch.object(wm.patient_directory, "lookup_patient", return_value={"status": "not_found"}):
                contacts.write_text(json.dumps({phone: dict(paused)}))
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Oi")[0])
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Preciso de ajuda")[0])
                self.assertTrue(wm._ensure_contact_ai_access(phone, phone, message_text="Quero marcar consulta")[0])
                contacts.write_text(json.dumps({phone: {**paused, "lid": lid},
                                                lid: {**paused, "ai_disabled_reason": "owner_optout",
                                                      "flow_origin": "owner_optout"}}))
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Quero marcar consulta")[0])
                self.assertEqual(json.loads(contacts.read_text())[phone]["ai_enabled"], False)
                contacts.write_text(json.dumps({phone: {**paused, "lid": lid},
                                                lid: {**paused, "manual_relationship": "pessoal"}}))
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Quero marcar consulta")[0])
                self.assertEqual(json.loads(contacts.read_text())[phone]["ai_enabled"], False)
                contacts.write_text(json.dumps({phone: dict(paused)}))
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Quero marcar consulta", is_historical=True)[0])
                config.write_text("{}")
                self.assertFalse(wm._ensure_contact_ai_access(phone, phone, message_text="Quero marcar consulta")[0])

    def test_imported_test_pause_allows_shared_family_phone_without_assuming_identity(self):
        phone = "5511999999999@s.whatsapp.net"
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            contacts = Path(folder) / "contacts.json"
            config.write_text(json.dumps({"patient_directory": {"enabled": True, "clinic_id": "test-clinic"}}))
            contacts.write_text(json.dumps({phone: {"ai_enabled": False, "in_flow": False,
                                                    "flow_origin": "fullsync_test_pause",
                                                    "ai_disabled_reason": "test_mode"}}))
            with patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config), \
                 patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts), \
                 patch.object(wm, "_is_contact_blocked", return_value=False), \
                 patch.object(wm.patient_directory, "lookup_patient", return_value={"status": "ambiguous"}):
                self.assertTrue(wm._ensure_contact_ai_access(phone, phone, message_text="Bom dia, tudo bem?")[0])
                self.assertEqual(json.loads(contacts.read_text())[phone]["flow_origin"], "clinic_import_inbound")

    def test_legacy_sync_default_off_resumes_for_known_patient(self):
        phone = "5511999999999@s.whatsapp.net"
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.json"
            contacts = Path(folder) / "contacts.json"
            config.write_text(json.dumps({"patient_directory": {"enabled": True, "clinic_id": "test-clinic"}}))
            contacts.write_text(json.dumps({phone: {"ai_enabled": False, "in_flow": False,
                                                    "flow_origin": "legacy_sync",
                                                    "ai_disabled_reason": "legacy_sync_not_in_flow"}}))
            with patch.object(wm, "_PATIENT_DIRECTORY_CONFIG_PATH", config), \
                 patch.object(wm, "_PERSONAL_CONTACTS_PATH", contacts), \
                 patch.object(wm, "_is_contact_blocked", return_value=False), \
                 patch.object(wm.patient_directory, "lookup_patient", return_value={"status": "matched"}):
                self.assertTrue(wm._ensure_contact_ai_access(phone, phone, message_text="Tudo bem?")[0])
                self.assertEqual(json.loads(contacts.read_text())[phone]["flow_origin"], "clinic_import_inbound")


class BookingNotificationPollingTests(unittest.TestCase):
    def test_results_are_polled_every_five_seconds_independently_of_sync(self):
        with patch.object(wm, "_tick_pv_booking_results", side_effect=[ValueError("temporary"), None]) as tick, patch.object(wm.time, "sleep", side_effect=[None, StopIteration]) as sleep:
            with self.assertRaises(StopIteration):
                wm._run_pv_booking_notifications()
        self.assertEqual(tick.call_count, 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 5])
