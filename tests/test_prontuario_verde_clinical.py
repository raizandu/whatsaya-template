from datetime import date
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

from prontuario_verde_clinical import ClinicalReadError, policy_context, read_chart

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/scripts'))
from read_prontuario_verde_clinical import conversation_evidence


class ClinicalReadTests(TestCase):
    def setUp(self):
        self.config = {'source_clinic_hash': 'a' * 64, 'expected_clinic_name': 'Clínica Teste'}
        self.browser = Mock(source_clinic_hash='a' * 64)
        self.browser.evaluate.side_effect = [True, True,
            {'id': '81', 'origin': 'https://app.prontuarioverde.com.br'},
            {'activeFilter': 'S', 'lists': [
                {'empty': True, 'items': []},
                {'empty': False, 'items': [{
                    'title': 'REMOÇÃO DE APARELHO', 'aside': '',
                    'status': 'AG. APROVAÇÃO', 'text': 'REMOÇÃO DE APARELHO'}]},
                {'empty': False, 'items': [{
                    'title': 'CONSULTA ORTODONTIA', 'aside': 'Executado em 09/07/2025 - Particular',
                    'status': '', 'text': 'CONSULTA ORTODONTIA'}]},
            ]}]
        row = {'id': '81', 'record_number': '123'}
        self.page = patch('prontuario_verde_clinical._page_row', return_value=row)
        self.page.start()
        self.addCleanup(self.page.stop)
        self.open = patch('register_prontuario_verde_patient.RegistrationBrowser.open_patients')
        self.open.start()
        self.addCleanup(self.open.stop)

    def test_pending_plan_and_dated_execution_remain_distinct(self):
        facts = read_chart(self.browser, self.config, '81')
        self.assertEqual(facts['record_number'], '123')
        self.assertEqual(facts['planned'][0]['status'], 'AG. APROVAÇÃO')
        self.assertEqual(facts['performed'][0]['executed_on'], '2025-07-09')
        self.assertEqual(policy_context(facts), {
            'established_patient': True, 'in_treatment': False,
            'no_added_procedure': False, 'chart_verified': False,
        })

    def test_wrong_chart_identity_blocks_all_facts(self):
        self.browser.evaluate.side_effect = [True, True,
            {'id': '82', 'origin': 'https://app.prontuarioverde.com.br'}]
        with self.assertRaisesRegex(ClinicalReadError, 'chart_identity_unverified'):
            read_chart(self.browser, self.config, '81')

    def test_unloaded_tab_is_not_empty_chart(self):
        self.browser.evaluate.side_effect = [True, True,
            {'id': '81', 'origin': 'https://app.prontuarioverde.com.br'}, None]
        with self.assertRaisesRegex(ClinicalReadError, 'chart_load_incomplete'):
            read_chart(self.browser, self.config, '81')

    def test_undated_or_future_execution_does_not_prove_prior_care(self):
        facts = {'performed': [{'source': 'tratamentosParticulares_jqm_list_view', 'title': 'CONSULTA'},
                               {'source': 'tratamentosParticulares_jqm_list_view', 'title': 'CONSULTA',
                                'executed_on': f'{date.today().year + 1}-01-01'}]}
        self.assertFalse(policy_context(facts)['established_patient'])

    def test_conversation_evidence_keeps_sources_without_chart_identity(self):
        facts = read_chart(self.browser, self.config, '81')
        summary = conversation_evidence(facts)
        self.assertNotIn('patient_id', summary)
        self.assertNotIn('record_number', summary)
        self.assertEqual(summary['treatment_active'], 'unknown')
        self.assertEqual(summary['planned'][0]['status'], 'AG. APROVAÇÃO')
        self.assertEqual(summary['performed'][0]['executed_on'], '2025-07-09')
