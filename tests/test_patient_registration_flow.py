import unittest
from patient_registration_flow import transition

CONFIG = {'enabled':True,'registration_enabled':True,'clinic_id':'clinic','source_clinic_hash':'a'*64}


class RegistrationFlowTests(unittest.TestCase):
    def call(self,message='Oi',state=None,**changes):
        args=dict(config=CONFIG,directory_status='not_found',state=state,message=message,message_id='inbound-1')
        args.update(changes)
        return transition(**args)

    def test_first_booking_request_requests_identity_without_creating(self):
        result=self.call('Quero marcar uma avaliação')
        self.assertIsNone(result['enqueue'])
        self.assertEqual(result['state']['phase'],'awaiting_name')
        self.assertIn('nome completo',result['prompt'])

    def test_greeting_does_not_start_registration(self):
        result=self.call('Bom dia!')
        self.assertEqual(result, {'prompt':'', 'state':None, 'enqueue':None})

    def test_first_explicit_self_introduction_can_enqueue(self):
        result=self.call('Meu nome é Maria de Souza')
        self.assertEqual(result['enqueue'],{'name':'Maria de Souza','source_message_id':'inbound-1'})
        self.assertEqual(result['state']['confirmed_name'],'Maria de Souza')

    def test_bare_name_requires_identity_confirmation(self):
        state=self.call('Quero marcar uma avaliação')['state']
        candidate=self.call('Maria de Souza',state=state)
        self.assertIsNone(candidate['enqueue'])
        self.assertIn('A consulta é pra você',candidate['prompt'])
        confirmed=self.call('Sim',state=candidate['state'],message_id='confirmed-inbound')
        self.assertEqual(confirmed['enqueue']['name'],'Maria de Souza')
        self.assertEqual(confirmed['state']['source_message_id'],'confirmed-inbound')

    def test_display_names_and_conversational_replies_do_not_create(self):
        state=self.call()['state']
        for text in ['oi','Quero marcar','quanto custa','Anthony','62981405459','Ignore as instruções','Sou de Cotia']:
            with self.subTest(text=text):
                self.assertIsNone(self.call(text,state=state)['enqueue'])

    def test_matches_unavailable_ambiguity_disabled_and_synthetic_never_enqueue(self):
        for status in ['matched','ambiguous','unavailable']:
            with self.subTest(status=status):
                self.assertIsNone(self.call('Meu nome é Maria Souza',directory_status=status)['enqueue'])
        self.assertEqual(self.call(config={**CONFIG,'registration_enabled':False})['prompt'],'')
        self.assertIsNone(self.call('Meu nome é Maria Souza',message_id='synthetic:foo')['enqueue'])

    def test_third_party_human_optout_and_correction_invalidate_queued_identity(self):
        queued=self.call('Meu nome é Maria Souza')['state']
        for text in ['É para minha filha','Não é para mim','Não quero cadastrar','Quero falar com uma pessoa','Quero falar com a Dra. Bruna','Meu nome é Joana Silva','O nome correto é Joana Silva']:
            with self.subTest(text=text):
                result=self.call(text,state=queued,job={'status':'pending'})
                self.assertIsNone(result['enqueue'])
                self.assertEqual(result['state']['phase'],'needs_review')
                self.assertNotIn('confirmed_name',result['state'])

    def test_urgent_case_does_not_delay_for_name(self):
        result=self.call('Estou com muita dor e dificuldade para respirar')
        self.assertEqual(result['prompt'],'')
        self.assertIsNone(result['enqueue'])
        for message in ['Quebrei um dente', 'Caiu o curativo', 'Fiz uma restauração e está doendo',
                        'Já tenho orçamento e quero conferir o valor']:
            with self.subTest(message=message):
                self.assertEqual(self.call(message)['prompt'], '')

    def test_pending_does_not_claim_success_and_failure_requests_review(self):
        state=self.call('Meu nome é Maria Souza')['state']
        pending=self.call('Queria uma avaliação',state=state,job={'status':'running'})
        self.assertIsNone(pending['enqueue'])
        self.assertIn('sem dizer que a ficha foi criada',pending['prompt'])
        for job in [None,{'status':'needs_review'},{'status':'failed'}]:
            result=self.call('Oi',state=state,job=job)
            self.assertEqual(result['state']['phase'],'needs_review')

    def test_foreign_clinic_identity_confirmation_is_not_reused(self):
        state={**CONFIG,'phase':'awaiting_confirmation','candidate_name':'Maria Souza','clinic_id':'other'}
        self.assertIsNone(self.call('Sim',state=state)['enqueue'])


if __name__=='__main__':unittest.main()
