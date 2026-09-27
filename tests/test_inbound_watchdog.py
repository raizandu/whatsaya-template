import unittest
from unittest.mock import patch

import whatsapp_manager as wm


class InboundWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.chat = '5511999999999@s.whatsapp.net'
        self.inbound = {'message_id': 'request', 'at': 1000.0,
                        'text': 'Primeiro horário disponível', 'preview': 'Primeiro horário disponível'}
        for key, value in [('_pending_inbound', {self.chat: self.inbound}),
                           ('_pending_inbound_queue', {self.chat: [self.inbound]}),
                           ('_sender_to_chat', {})]:
            p = patch.object(wm, key, value)
            p.start(); self.addCleanup(p.stop)

    def test_slow_pv_search_remains_authorized_after_watchdog_alert(self):
        token = wm._inbound_record_token(self.inbound)
        config = {'patient_directory': {'appointment_allowed_chats': [self.chat],
                  'clinic_id': 'test', 'source_clinic_hash': 'a' * 64}}
        with patch.object(wm, '_unanswered_alert_seconds', return_value=180), \
             patch.object(wm, '_pv_config', return_value=config), \
             patch.object(wm, '_calendar_tool_context', return_value=(self.chat, dict(self.inbound), token)), \
             patch.object(wm, '_assert_delivery_allowed'), patch.object(wm, '_pv_flow'), \
             patch.object(wm.patient_directory, 'lookup_for_panel', return_value={'status': 'matched', 'patient_id': '31'}):
            self.assertEqual(len(wm._sweep_unanswered(now=1220)), 1)
            self.assertEqual(wm._pv_context({})[2], token)
            self.assertEqual(wm._inbound_record_token(wm._current_inbound_record(self.chat)), token)
            self.assertEqual(wm._sweep_unanswered(now=1300), [])
            with patch.object(wm.time, 'time', return_value=1301):
                wm._track_inbound(self.chat, 'newer', 'Não quero mais')
            with self.assertRaisesRegex(ValueError, 'current_message_required'):
                wm._pv_context({})

    def test_failed_alert_retries_without_changing_message_identity(self):
        with patch.object(wm, '_unanswered_alert_seconds', return_value=180):
            stale = wm._sweep_unanswered(now=1220)
            wm._requeue_unanswered(*stale[0])
            self.assertEqual(len(wm._sweep_unanswered(now=1300)), 1)
            self.assertEqual(wm._inbound_record_token(wm._current_inbound_record(self.chat)), ('request', 1000.0))

    def test_failed_alert_cannot_resurrect_a_delivered_message(self):
        with patch.object(wm, '_unanswered_alert_seconds', return_value=180):
            stale = wm._sweep_unanswered(now=1220)
            wm._clear_inbound(self.chat, expected_token=('request', 1000.0))
            wm._requeue_unanswered(*stale[0])
            self.assertEqual(wm._current_inbound_record(self.chat), {})
            self.assertEqual(wm._sweep_unanswered(now=1300), [])

    def test_legacy_map_also_retains_identity_and_deduplicates_alert(self):
        wm._pending_inbound_queue.clear()
        with patch.object(wm, '_unanswered_alert_seconds', return_value=180):
            self.assertEqual(len(wm._sweep_unanswered(now=1220)), 1)
            self.assertEqual(wm._current_inbound_record(self.chat)['message_id'], 'request')
            self.assertEqual(wm._sweep_unanswered(now=1300), [])
