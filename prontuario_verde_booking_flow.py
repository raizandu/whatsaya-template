"""Durable delivered offers and explicit acceptance for the clinical PV queue.

This module never infers a booking from LLM prose. Only a delivered offer can
produce a queue request; only the worker's exact proof can produce success.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid
from zoneinfo import ZoneInfo

import prontuario_verde_booking_queue as queue
from patient_directory import normalize_phone

DEFAULT_PATH = Path('/opt/data/prontuario_verde_booking_flow.db')
ZONE = ZoneInfo('America/Sao_Paulo')


def chat_allowed(config, chat):
    """An optional deployment allowlist limits a pilot without changing policy."""
    allowed = config.get('appointment_allowed_chats')
    if allowed is None:
        return True
    phone = normalize_phone(chat)
    return (isinstance(allowed, list) and phone is not None
            and all(isinstance(value,str) and normalize_phone(value) is not None for value in allowed)
            and phone in {normalize_phone(value) for value in allowed})


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('invalid_timestamp')
    return result


def explicit_choice(text, count):
    """Whole-message matches only; negation, extra instructions and ambiguity fail."""
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(text)) if not unicodedata.combining(c))
    text = ' '.join(text.lower().strip().rstrip('.!').split())
    number = re.fullmatch(r'(?:opcao |quero a opcao |confirmo a opcao )?([1-3])', text)
    if number and 1 <= int(number[1]) <= count:
        return int(number[1])-1
    ordinals = {'a primeira': 0, 'a segunda': 1, 'a terceira': 2}
    if text in ordinals and ordinals[text] < count:
        return ordinals[text]
    if count == 1 and text in {'sim', 'pode ser', 'confirmo', 'pode marcar', 'pode agendar', 'esse horario funciona'}:
        return 0
    return None


class BookingFlow:
    def __init__(self, path=DEFAULT_PATH, queue_root=queue.DEFAULT_ROOT):
        self.path, self.queue_root = Path(path), Path(queue_root)

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('CREATE TABLE IF NOT EXISTS conversations (chat_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _load(db, chat):
        row = db.execute('SELECT payload FROM conversations WHERE chat_id=?', (chat,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def _save(db, chat, state):
        db.execute('INSERT OR REPLACE INTO conversations VALUES (?,?)', (chat, json.dumps(state)))

    def get(self, chat):
        with self._db() as db:
            return self._load(db, chat)

    def note_inbound(self, chat, message_id, text, *, requires_team=False):
        """An intervening preference/correction cannot later accept an old offer."""
        with self._db() as db:
            state = self._load(db, chat)
            if not state or state['phase'] not in {'offered','available'} or message_id==state['source_message_id']:
                return
            if requires_team:
                state['phase']='expired'
            elif state['phase']=='offered' or explicit_choice(text,len(state['slots'])) is None:
                state['phase']='expired'
            else:
                return
            self._save(db,chat,state)

    def publish(self, chat, source_message_id, query, slots, *, location_label="na clínica", professional_label="", appointment_label="consulta", now=None):
        now = now or datetime.now(timezone.utc)
        if (not source_message_id or source_message_id.startswith(('synthetic:', 'at:'))
                or not isinstance(slots, list) or not 1 <= len(slots) <= 3
                or query.get('chat_id') != chat):
            raise ValueError('offer_unverified')
        for slot in slots:
            start, end = instant(slot['start']), instant(slot['end'])
            if start <= now or end-start != timedelta(minutes=query['duration_min']):
                raise ValueError('offer_unverified')
        with self._db() as db:
            previous = self._load(db, chat)
            if previous and previous['phase'] in {'enqueuing', 'queued', 'notifying', 'review'}:
                raise ValueError('previous_booking_unresolved')
            expires = now+timedelta(minutes=10)
            if query.get('operation') == 'reschedule':
                expires = min(expires, instant(query['original_verified_at'])+timedelta(minutes=5))
            if expires <= now:
                raise ValueError('original_appointment_unverified')
            state = dict(phase='offered', offer_id=str(uuid.uuid4()), chat_id=chat,
                         source_message_id=source_message_id, query=query, slots=slots,
                         location_label=location_label, professional_label=professional_label, appointment_label=appointment_label,
                         created_at=now.isoformat(), expires_at=expires.isoformat())
            self._save(db, chat, state)
            return state

    def mark_delivered(self, chat, text, message_id, *, now=None):
        if not message_id:
            return False
        now = now or datetime.now(timezone.utc)
        with self._db() as db:
            state = self._load(db, chat)
            if (not state or state['phase'] != 'offered' or text != offer_reply(state)
                    or instant(state['expires_at']) <= now):
                return False
            state.update(phase='available', delivered_message_id=message_id, delivered_at=now.isoformat())
            self._save(db, chat, state)
            return True

    def accept(self, chat, message_id, text, received_at, identity, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self._db() as db:
            state = self._load(db, chat)
            if not state or state['phase'] not in {'available', 'enqueuing', 'queued'}:
                raise ValueError('delivered_offer_required')
            if state['phase'] in {'enqueuing', 'queued'}:
                if state['acceptance_message_id'] != message_id:
                    raise ValueError('previous_booking_unresolved')
                payload = state['payload']
            else:
                index = explicit_choice(text, len(state['slots']))
                query = state['query']
                if (index is None or instant(state['expires_at']) <= now
                        or not isinstance(received_at,(int,float)) or isinstance(received_at,bool)
                        or not math.isfinite(received_at) or received_at > now.timestamp()+1
                        or instant(state['delivered_at']).timestamp() >= received_at
                        or message_id == state['source_message_id'] or not message_id
                        or message_id.startswith(('synthetic:', 'at:'))
                        or any(str(identity.get(k)) != str(query.get(k)) for k in ('patient_id', 'clinic_id', 'source_clinic_hash'))):
                    raise ValueError('explicit_current_acceptance_required')
                slot = state['slots'][index]
                payload = {**query, 'requested_start':slot['start'], 'requested_end':slot['end'],
                    'idempotency_key': 'pv-offer:' + state['offer_id'], 'created_at':now.isoformat(),
                    'confirmation':dict(chat_id=chat, message_id=message_id, offer_id=state['offer_id'],
                        slot_id=str(index+1), requested_start=slot['start'], requested_end=slot['end'],
                        offer_expires_at=state['expires_at'], confirmed_at=now.isoformat(), explicit=True, kind='offer_acceptance')}
                state.update(phase='enqueuing', acceptance_message_id=message_id, payload=payload)
                # Persist intent before crossing the separate spool boundary. A
                # replay uses identical payload/timestamps and the same key.
                self._save(db, chat, state)
                db.commit()
                db.execute('BEGIN IMMEDIATE')
            queued = (queue.enqueue_booking(self.queue_root, payload) if payload['operation']=='book'
                      else queue.enqueue_reschedule(self.queue_root, payload))
            state.update(phase='queued', request_id=queued['request_id'])
            self._save(db, chat, state)
            return queued

    def pending_results(self):
        with self._db() as db:
            states = [json.loads(row[0]) for row in db.execute('SELECT payload FROM conversations')]
        return [s for s in states if s['phase']=='queued']

    def validates_request(self, request):
        state = self.get(request.get('chat_id'))
        if (not state or state['phase'] not in {'enqueuing', 'queued'}
                or not state.get('delivered_message_id')
                or state.get('request_id', request.get('request_id')) != request.get('request_id')):
            return False
        expected = state.get('payload') or {}
        timestamps = {'requested_start', 'requested_end', 'created_at', 'expected_start',
                      'expected_end', 'original_verified_at', 'offer_expires_at', 'confirmed_at'}
        try:
            for key, value in expected.items():
                if key == 'idempotency_key':
                    continue
                if key == 'confirmation':
                    actual = request.get(key) or {}
                    if set(value) != set(actual):
                        return False
                    if any((instant(v) != instant(actual[k])) if k in timestamps else v != actual[k]
                           for k, v in value.items()):
                        return False
                elif key in timestamps:
                    if instant(value) != instant(request.get(key)):
                        return False
                elif value != request.get(key):
                    return False
            confirmation = expected['confirmation']
            selected = state['slots'][int(confirmation['slot_id'])-1]
            return (confirmation['offer_id'] == state['offer_id']
                    and confirmation['message_id'] == state['acceptance_message_id']
                    and confirmation['message_id'] != state['source_message_id']
                    and instant(confirmation['confirmed_at']) > instant(state['delivered_at'])
                    and instant(confirmation['requested_start']) == instant(selected['start'])
                    and instant(confirmation['requested_end']) == instant(selected['end']))
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return False

    def claim_notification(self, chat, request_id):
        with self._db() as db:
            state = self._load(db, chat)
            if not state or state['phase']!='queued' or state['request_id']!=request_id:
                return None
            result = queue.get_result(self.queue_root, request_id)
            if not result or result['status'] not in {'succeeded', 'failed', 'needs_review'}:
                return None
            if (result['status']=='succeeded'
                    and datetime.now(timezone.utc)-instant(result['updated_at']) > timedelta(minutes=5)):
                result = {**result, 'status':'needs_review', 'code':'confirmation_stale'}
            state.update(phase='notifying', result=result)
            self._save(db, chat, state)
            return state

    def finish_notification(self, chat, request_id, delivered):
        with self._db() as db:
            state = self._load(db, chat)
            if state and state.get('request_id')==request_id and state['phase']=='notifying':
                state['phase'] = 'done' if delivered and state['result']['status'] in {'succeeded','failed'} else 'review'
                self._save(db, chat, state)


def offer_reply(state):
    labels=[]
    for index, slot in enumerate(state['slots'], 1):
        start=instant(slot['start']).astimezone(ZONE)
        labels.append(f'{index}. {start:%d/%m às %H:%M}')
    professional = (' com ' + state['professional_label']) if state.get('professional_label') else ''
    return ('Para '+state['appointment_label']+' de '+str(state['query']['duration_min'])+' minutos '
            + state['location_label'] + professional + ', encontrei:\n'+'\n'.join(labels)
            +'\nQual opção você confirma? Vou conferir a vaga novamente antes de marcar.')


def result_reply(state):
    result=state['result']
    if result.get('status')!='succeeded':
        return 'Não consegui confirmar a alteração na agenda. Vou encaminhar à equipe para conferir.'
    proof=result.get('appointment') or {}
    expected=state['payload']
    if (not proof.get('start') or not proof.get('end')
            or instant(proof['start']) != instant(expected['requested_start'])
            or instant(proof['end']) != instant(expected['requested_end'])
            or any(str(proof.get(k)) != str(expected.get(k)) for k in ('professional_id', 'unit_id', 'type_id', 'duration_min'))):
        raise ValueError('booking_proof_missing')
    start=instant(proof['start']).astimezone(ZONE)
    verb='remarcada' if state['query']['operation']=='reschedule' else 'marcada'
    return f'Sua consulta foi {verb} para {start:%d/%m às %H:%M}. Até lá!'
