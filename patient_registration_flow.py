"""Deterministic identity intake before scheduling a PV registration job.

Never infer a legal name from a WhatsApp display name or an LLM response.
"""
from __future__ import annotations
import re
import unicodedata


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text).lower())
                   if not unicodedata.combining(c))


_THIRD_PARTY = re.compile(r"\b(?:filh[oa]|espos[oa]|marido|mulher|mae|pai|irma[oã]?|outra pessoa|para outra|pra outra|meu marido|minha familia|responsavel)\b")
_STOP = re.compile(r"\b(?:nao (?:e|era) (?:para|pra) mim|nao sou|numero errado|engano|nao quero|pare de|parar de|cancele meu cadastro|cancelar meu cadastro|exclua|apague|falar com (?:uma )?pessoa|falar com (?:a )?equipe|(?:falar|conversar) com (?:a )?(?:dra\.?|doutora|dentista|liliane|bruna)|atendente|humano)\b")
_CORRECTION = re.compile(r"\b(?:nome correto|corrigir.{0,20}nome|mudar.{0,20}nome|errei.{0,20}nome)\b")
_URGENT = re.compile(r"\b(?:dor|doendo|dolorid\w*|sangramento|sangrando|inchaco|incha[dnt]\w*|respirar|engolir|febre|trauma|fratura|quebrei|quebrad\w*|curativo|pos[- ]?(?:operatorio|procedimento|cirurgia)|urgencia|emergencia)\b")
_HANDOFF_FIRST = re.compile(r"\b(?:ja (?:tenho|recebi) (?:um )?orcamento|reclamacao|insatisfeit\w*)\b")
_SELF_NAME = re.compile(r"^(?:(?:oi|ola|bom dia|boa tarde|boa noite)[,! .]+)?(?:meu nome(?: completo)? (?:e|é)|me chamo|eu me chamo|sou (?:o|a))\s+(.+?)[.!]?$", re.IGNORECASE)
_YES = re.compile(r"^(?:sim|isso|isso mesmo|correto|confirmo|sou eu|e para mim|é para mim|sim sou eu|sim e para mim|sim é para mim)[.! ]*$", re.IGNORECASE)
_GREETING_ONLY = re.compile(r"^(?:oi|ola|bom dia|boa tarde|boa noite|opa|tudo bem)[\s!.,?]*$", re.IGNORECASE)
_NOT_NAME = set('quero queria gostaria consulta avaliacao agendar marcar preciso tenho estou isso mesmo pode pode me chamar oi ola bom boa dia tarde noite obrigado obrigada sim nao tudo bem como voce sou moro cotia brasil custa valor preco nome completo cadastre cadastro excluir apague ignore instrucoes sistema meu minha para mim ele ela comigo'.split())


def full_name(text):
    if not isinstance(text, str) or any(ord(c)<32 for c in text):
        return None
    value = ' '.join(unicodedata.normalize('NFKC', text).strip(' .!').split())
    words = value.split()
    if not 2 <= len(words) <= 8 or len(value) > 100:
        return None
    if any(not all(c.isalpha() or c in "'-’" for c in word) for word in words):
        return None
    if any(fold(word) in _NOT_NAME for word in words):
        return None
    if fold(words[0]) in {'de','da','do','dos','das','e'}:
        return None
    return value


def transition(*, config, directory_status, state, message, message_id, job=None):
    """Return prompt, replacement identity state and optional confirmed enqueue data."""
    empty = {'prompt':'', 'state':None, 'enqueue':None}
    if (config.get('enabled') is not True or config.get('registration_enabled') is not True
            or not isinstance(message_id,str) or not message_id
            or message_id.startswith(('synthetic:', 'at:'))):
        return empty
    binding = {'clinic_id':config.get('clinic_id'), 'source_clinic_hash':config.get('source_clinic_hash')}
    previous = state if isinstance(state,dict) and all(state.get(k)==v for k,v in binding.items()) else {}
    text = str(message or '').strip()
    normalized = fold(text)
    phase = previous.get('phase')
    intro = _SELF_NAME.fullmatch(text)
    introduced = full_name(intro.group(1)) if intro else None
    changed_name = (phase=='queued' and introduced and
                    fold(introduced)!=fold(previous.get('confirmed_name','')))
    if _THIRD_PARTY.search(normalized) or _STOP.search(normalized) or changed_name or (phase=='queued' and _CORRECTION.search(normalized)):
        # Clear confirmed identity before the worker can submit a pending job.
        return {'prompt':'O cadastro automático está suspenso neste atendimento. Não criar nem prometer cadastro; encaminhar a conferência de identidade à equipe sem atrasar a necessidade principal.',
                'state':{**binding,'phase':'needs_review'}, 'enqueue':None}
    if directory_status == 'matched':
        return empty
    if (directory_status == 'ambiguous' or phase=='needs_review'
            or (job or {}).get('status') in {'failed', 'needs_review'}):
        return {'prompt':'Há uma identidade cadastral que exige conferência. Não escolher paciente nem criar outra ficha. Confirmar para quem é o atendimento e encaminhar à equipe.',
                'state':{**binding,'phase':'needs_review'},'enqueue':None}
    if directory_status != 'not_found':
        return {'prompt':'A consulta cadastral está indisponível ou desatualizada. Não interpretar isso como ausência de ficha nem prometer criação; continuar o atendimento e encaminhar a conferência à equipe.', 'state':None,'enqueue':None}
    if phase == 'queued':
        status = (job or {}).get('status')
        if status == 'succeeded':
            return {'prompt':'O serviço confirmou o cadastro. Não confundir cadastro com consulta agendada. Não divulgar identificadores internos.', 'state':None,'enqueue':None}
        if status in {None,'failed','needs_review'}:
            return {'prompt':'Não foi possível concluir o cadastro automático com segurança. Não afirmar que criou a ficha. Encaminhar a conferência para a equipe.', 'state':{**binding,'phase':'needs_review'},'enqueue':None}
        return {'prompt':'Cadastro em conferência automática. Continuar a conversa normalmente, sem dizer que a ficha foi criada ou que há consulta agendada até confirmação do serviço.', 'state':None,'enqueue':None}
    if _URGENT.search(normalized) or _HANDOFF_FIRST.search(normalized):
        return empty
    if not phase and _GREETING_ONLY.fullmatch(normalized):
        return empty
    confirmed = introduced
    if phase == 'awaiting_confirmation' and _YES.fullmatch(text):
        confirmed = full_name(previous.get('candidate_name'))
    if confirmed:
        updated = {**binding,'phase':'queued','confirmed_name':confirmed,'source_message_id':message_id}
        return {'prompt':'Nome e identidade informados pela própria pessoa. O cadastro será conferido automaticamente; continuar o atendimento sem prometer gravação ou agendamento antes da confirmação do serviço.',
                'state':updated,'enqueue':{'name':confirmed,'source_message_id':message_id}}
    candidate = full_name(text) if phase in {'awaiting_name','awaiting_confirmation'} else None
    if candidate:
        return {'prompt':f'Antes de cadastrar, confirmar uma única vez: "O atendimento é para você e posso cadastrar seu nome como {candidate}?" Não criar enquanto a pessoa não confirmar.',
                'state':{**binding,'phase':'awaiting_confirmation','candidate_name':candidate,
                         'prompt_message_id':message_id},'enqueue':None}
    return {'prompt':'Ainda não foi localizado cadastro neste telefone. Na próxima resposta, acolher a necessidade e pedir o nome completo para conferir o cadastro, deixando claro que é o nome da própria pessoa atendida. Se for outra pessoa, encaminhar a conferência à equipe. Não usar nome de exibição, apelido ou número como nome de registro. Não atrasar urgência ou handoff por essa pergunta.',
            'state':{**binding,'phase':'awaiting_name','prompt_message_id':message_id},'enqueue':None}
