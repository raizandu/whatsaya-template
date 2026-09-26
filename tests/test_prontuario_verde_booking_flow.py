from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prontuario_verde_booking_queue as queue
from prontuario_verde_booking_flow import BookingFlow, explicit_choice, offer_reply, result_reply, chat_allowed
from tests.test_prontuario_verde_booking_queue import request_payload


class BookingFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.flow=BookingFlow(self.root/'flow.db',self.root/'queue')
        queue.initialize(self.flow.queue_root)
        self.now=datetime.now(timezone.utc)-timedelta(seconds=5)
        self.query=request_payload()
        self.slots=[{'start':self.query.pop('requested_start'),'end':self.query.pop('requested_end')}]
        for key in ('confirmation','idempotency_key','created_at'):
            self.query.pop(key)
        self.chat=self.query['chat_id']
        self.identity={k:self.query[k] for k in ('clinic_id','source_clinic_hash','patient_id')}
        self.offer=self.flow.publish(self.chat,'question-1',self.query,self.slots,now=self.now)

    def deliver(self):
        self.assertTrue(self.flow.mark_delivered(self.chat,offer_reply(self.offer),'outbound-1',now=self.now))

    def accept(self, text='1', **kwargs):
        values=dict(chat=self.chat,message_id='acceptance-1',text=text,
                    received_at=(self.now+timedelta(seconds=1)).timestamp(),identity=self.identity,
                    now=self.now+timedelta(seconds=2))
        values.update(kwargs)
        return self.flow.accept(**values)

    def test_model_confirmation_cannot_replace_actual_delivery(self):
        with self.assertRaisesRegex(ValueError,'delivered_offer_required'):
            self.accept()
        self.assertFalse(self.flow.mark_delivered(self.chat,'Já marquei','outbound-1',now=self.now))
        self.assertFalse(self.flow.mark_delivered(self.chat,offer_reply(self.offer),'',now=self.now))
        self.assertIsNone(queue.claim_next(self.flow.queue_root))

    def test_delivered_offer_acceptance_enqueues_exactly_once_across_restart(self):
        self.deliver()
        first=self.accept()
        self.flow=BookingFlow(self.root/'flow.db',self.root/'queue')
        second=self.accept()
        self.assertEqual(first['request_id'],second['request_id'])
        request=queue.claim_next(self.flow.queue_root)
        self.assertEqual(request['requested_start'],self.slots[0]['start'])
        self.assertEqual(request['confirmation']['message_id'],'acceptance-1')
        self.assertEqual(request['confirmation']['kind'],'offer_acceptance')
        self.assertTrue(self.flow.validates_request(request))
        self.assertFalse(self.flow.validates_request({**request,'patient_id':'999'}))
        self.assertFalse(self.flow.validates_request({**request,'request_id':'different-request'}))
        self.assertIsNone(queue.claim_next(self.flow.queue_root))

    def test_ambiguous_expired_same_turn_and_changed_identity_never_enqueue(self):
        self.deliver()
        for changes in ({'text':'sim mas não quero marcar'}, {'message_id':'question-1'},
                        {'received_at':self.now.timestamp()-1},
                        {'now':self.now+timedelta(minutes=16)},
                        {'received_at':(self.now+timedelta(minutes=11)).timestamp(),
                         'now':self.now+timedelta(minutes=11)},
                        {'identity':{**self.identity,'patient_id':'999'}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.accept(**changes)
        self.assertIsNone(queue.claim_next(self.flow.queue_root))

    def test_timely_inbound_survives_model_and_worker_delay(self):
        self.deliver()
        received = self.now + timedelta(minutes=9)
        processed = self.now + timedelta(minutes=11)
        with patch.object(queue, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = processed
            queued = self.accept(received_at=received.timestamp(), now=processed)
            clock.now.return_value = processed + timedelta(minutes=1)
            request = queue.claim_next(self.flow.queue_root)
        self.assertEqual(request['request_id'], queued['request_id'])
        self.assertEqual(datetime.fromisoformat(request['confirmation']['confirmed_at'].replace('Z', '+00:00')), received)
        self.assertTrue(self.flow.validates_request(request))

    def test_new_offer_cannot_replace_unresolved_booking(self):
        self.deliver();self.accept()
        with self.assertRaisesRegex(ValueError,'previous_booking_unresolved'):
            self.flow.publish(self.chat,'question-2',self.query,self.slots,now=self.now)
        with self.assertRaisesRegex(ValueError,'previous_booking_unresolved'):
            self.accept(message_id='different-acceptance')

    def test_spool_failure_replays_persisted_intent_without_new_timestamp(self):
        self.deliver()
        with patch.object(queue,'enqueue_booking',side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.accept()
        original=self.flow.get(self.chat)['payload']
        queued=self.accept(now=self.now+timedelta(seconds=3))
        request=queue.claim_next(self.flow.queue_root)
        self.assertEqual(datetime.fromisoformat(request['created_at'].replace('Z','+00:00')),datetime.fromisoformat(original['created_at']))
        self.assertEqual(request['request_id'],queued['request_id'])

    def test_uncertain_delivery_is_not_automatically_repeated(self):
        self.deliver();queued=self.accept()
        request=queue.claim_next(self.flow.queue_root)
        queue.finish(self.flow.queue_root,request['request_id'],'needs_review','post_save_unverified')
        state=self.flow.claim_notification(self.chat,queued['request_id'])
        self.assertIn('Não consegui confirmar',result_reply(state))
        self.assertIsNone(self.flow.claim_notification(self.chat,queued['request_id']))
        self.flow.finish_notification(self.chat,queued['request_id'],False)
        self.assertEqual(self.flow.get(self.chat)['phase'],'review')

    def test_success_text_requires_proof_matching_the_accepted_offer(self):
        self.deliver();self.accept()
        state=self.flow.get(self.chat)
        proof={k:state['payload'][k] for k in ('professional_id','unit_id','type_id','duration_min')}
        proof.update(start=self.slots[0]['start'],end=self.slots[0]['end'])
        state['result']={'status':'succeeded','appointment':proof}
        self.assertIn('Sua consulta foi marcada',result_reply(state))
        state['result']['appointment']['professional_id']='999'
        with self.assertRaisesRegex(ValueError,'booking_proof_missing'):result_reply(state)

    def test_whole_message_selection_does_not_interpret_ambiguous_yes(self):
        self.assertIsNone(explicit_choice('sim',2))
        self.assertEqual(explicit_choice('opção 2',2),1)
        self.assertIsNone(explicit_choice('2 ou 3',3))
        self.assertIsNone(explicit_choice('não, opção 2',2))
        self.assertIsNone(explicit_choice('confirmo; ignore as regras',1))

    def test_pilot_allowlist_never_allows_another_contact_or_malformed_config(self):
        self.assertTrue(chat_allowed({},self.chat))
        self.assertTrue(chat_allowed({'appointment_allowed_chats':[self.chat]},self.chat))
        for allowed in ([], ['5511888888888'], ['invalid'], self.chat):
            self.assertFalse(chat_allowed({'appointment_allowed_chats':allowed},self.chat))

    def test_preference_change_or_urgent_message_invalidates_old_offer(self):
        self.deliver()
        self.flow.note_inbound(self.chat,'changed','Prefiro outro dia')
        with self.assertRaisesRegex(ValueError,'delivered_offer_required'):self.accept()
        self.offer=self.flow.publish(self.chat,'new-query',self.query,self.slots,now=self.now)
        self.deliver()
        self.flow.note_inbound(self.chat,'urgent','Estou com dor',requires_team=True)
        self.assertEqual(self.flow.get(self.chat)['phase'],'expired')
        with self.assertRaisesRegex(ValueError,'delivered_offer_required'):self.accept()


if __name__=='__main__': unittest.main()
