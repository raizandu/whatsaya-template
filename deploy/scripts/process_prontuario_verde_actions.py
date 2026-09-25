#!/usr/bin/env python3
"""Process administrator cancellation requests using the local Hermes browser."""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import re
import signal
import sqlite3
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
import unicodedata
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'panel'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prontuario_verde_actions as queue
import prontuario_verde_onboarding as registration_queue
import prontuario_verde_booking_queue as booking_queue
from panel import data as panel_data
from panel.prontuario_calendar import ScheduleUnavailable, load_schedule
from register_prontuario_verde_patient import RegistrationBrowser as RegistrationFormBrowser
from prontuario_verde_registration import RegistrationError, ensure_patient
from sync_prontuario_verde import HermesBrowser, sync_lock
from sync_prontuario_verde_schedule import refresh_schedule, invalidate_cancelled
from prontuario_verde_appointment_writer import (
    AppointmentWriteError, ProntuarioVerdeAppointmentWriter,
)
from appointment_policy import Appointment as PolicyAppointment, classify_booking

DATA = Path('/opt/data')
SPOOL = DATA / 'prontuario_verde_actions'
REGISTRATION_SPOOL = DATA / 'prontuario_verde_registrations'
BOOKING_SPOOL = DATA / 'prontuario_verde_booking'
CONFIG = DATA / 'panel.config.json'
CREDENTIALS = DATA / '.hermes/secrets/prontuario-verde.json'
REGISTRATION_JOURNAL = DATA / '.hermes/secrets/pv-registrations'
SYNC_LOCK = DATA / '.patient-directory-sync.lock'
SAO_PAULO = ZoneInfo('America/Sao_Paulo')


class CancelError(Exception):
    pass


class BookingError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _default_appointment_writer_factory(session, request, config):
    """Load the native port only when explicitly enabled and installed."""
    try:
        from prontuario_verde_native_booking import ProntuarioVerdeHermesPort
    except ImportError:
        return None
    browser = session.browser
    if browser is None:
        raise AppointmentWriteError('browser_unavailable')
    port = ProntuarioVerdeHermesPort(browser, config)
    return ProntuarioVerdeAppointmentWriter(port, config)


class _RevalidatingAppointmentPort:
    """Run the live inbound/contact guard at the final submit boundary."""
    def __init__(self, port, before_submit):
        self._port = port
        self._before_submit = before_submit
        self.guard_error = None
        self.submitted = False

    def prepare(self, request):
        return self._port.prepare(request)

    def submit_once(self, request):
        try:
            self._before_submit()
        except Exception as exc:
            self.guard_error = exc
            raise
        self.submitted = True
        return self._port.submit_once(request)

    def reconcile_after_save(self, request):
        return self._port.reconcile_after_save(request)


class RegistrationBrowser(RegistrationFormBrowser):
    """Track the one irreversible save boundary for conservative recovery."""
    def __init__(self, browser, config, directory_path):
        super().__init__(browser, config, directory_path)
        self.submitted = False
        self.before_submit_check = lambda: None

    def create(self, name, phone, before_submit):
        def mark_submitted():
            self.before_submit_check()
            before_submit()
            self.submitted = True
        return super().create(name, phone, mark_submitted)


def _normalized_name(value):
    if not isinstance(value, str):
        return None
    normalized = ' '.join(unicodedata.normalize('NFKC', value).split()).casefold()
    return normalized or None


_PERSONAL_RELATIONSHIPS = {
    'amigo', 'amiga', 'amigoproximo', 'parente', 'familiar', 'filho', 'filha',
    'pessoal', 'namorada', 'namorado', 'esposa', 'marido', 'mae', 'pai',
    'irmao', 'irma', 'avo', 'tio', 'tia', 'primo', 'prima',
}


def _is_personal_relationship(value):
    if not isinstance(value, str):
        return False
    normalized = unicodedata.normalize('NFKD', value).casefold()
    normalized = ''.join(char for char in normalized if not unicodedata.combining(char))
    tokens = set(re.findall(r'[a-z]+', normalized))
    compact = ''.join(tokens) if len(tokens) == 1 else normalized.replace(' ', '')
    return bool(tokens.intersection(_PERSONAL_RELATIONSHIPS) or compact in _PERSONAL_RELATIONSHIPS)


def current_registration(request, paths=None, config_path=CONFIG):
    """Recheck authorization, identity confirmation, and inbound provenance."""
    if not isinstance(request, dict):
        raise RegistrationError('invalid_request')
    try:
        created = datetime.fromisoformat(request['created_at'].replace('Z', '+00:00'))
        age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise RegistrationError('invalid_request') from None
    if age < timedelta(0) or age > timedelta(minutes=15):
        raise RegistrationError('request_expired')
    paths = paths or panel_data.Paths()
    try:
        config = json.loads(Path(config_path).read_text())['patient_directory']
    except (OSError, ValueError, KeyError, TypeError):
        raise RegistrationError('config_unavailable') from None
    if config.get('enabled') is not True or config.get('registration_enabled') is not True:
        raise RegistrationError('registration_disabled')
    if (config.get('clinic_id') != request.get('clinic_id')
            or config.get('source_clinic_hash') != request.get('source_clinic_hash')):
        raise RegistrationError('clinic_mismatch')

    contacts = panel_data.load_contacts(paths.contacts_json)
    chat_id = str(request.get('chat_id') or '')
    phone = request.get('phone')
    normalized_phone = panel_data.patient_directory.normalize_phone(phone) if isinstance(phone, str) else None
    aliases = panel_data._contact_aliases(contacts, chat_id)
    if normalized_phone:
        aliases.extend(key for key in contacts
                       if panel_data.patient_directory.normalize_phone(str(key)) == normalized_phone)
        aliases.extend((normalized_phone, normalized_phone + '@s.whatsapp.net'))
        national = normalized_phone[2:]
        if len(national) == 11 and national[2] == '9':
            legacy_phone = '55' + national[:2] + national[3:]
            aliases.extend((legacy_phone, legacy_phone + '@s.whatsapp.net'))
    aliases = list(dict.fromkeys(aliases))
    records = [contacts[key] for key in aliases if isinstance(contacts.get(key), dict)]
    if not records:
        raise RegistrationError('contact_unavailable')
    if (any(record.get('blocked') is True or record.get('ai_enabled') is False
            or record.get('in_flow') is False
            or _is_personal_relationship(record.get('manual_relationship'))
            for record in records)
            or not any(record.get('ai_enabled') is True for record in records)):
        raise RegistrationError('contact_not_eligible')

    registrations = [record.get('pv_registration') for record in records
                      if isinstance(record.get('pv_registration'), dict)]
    wanted_name = _normalized_name(request.get('name'))
    if not wanted_name or not registrations or any(
        state.get('phase') != 'queued'
        or _normalized_name(state.get('confirmed_name')) != wanted_name
        or state.get('source_message_id') != request.get('source_message_id')
        or state.get('clinic_id') != request.get('clinic_id')
        or state.get('source_clinic_hash') != request.get('source_clinic_hash')
        for state in registrations
    ):
        raise RegistrationError('identity_confirmation_changed')

    if paths.followups_db.is_file():
        lead_db = None
        try:
            lead_db = sqlite3.connect(f'file:{paths.followups_db}?mode=ro', uri=True, timeout=5)
            placeholders = ','.join('?' for _ in aliases)
            lead = lead_db.execute(
                'SELECT takeover, opt_out FROM lead_state WHERE chat_id IN (' + placeholders + ')',
                aliases,
            ).fetchall()
        except sqlite3.Error:
            raise RegistrationError('contact_state_unavailable') from None
        finally:
            if lead_db is not None:
                lead_db.close()
        if any(bool(row[0]) for row in lead):
            raise RegistrationError('human_takeover')
        if any(bool(row[1]) for row in lead):
            raise RegistrationError('contact_not_eligible')

    if paths.panel_db.is_file():
        attendance_db = None
        try:
            attendance_db = sqlite3.connect(f'file:{paths.panel_db}?mode=ro', uri=True, timeout=5)
            placeholders = ','.join('?' for _ in aliases)
            human = attendance_db.execute(
                "SELECT 1 FROM atendimentos WHERE contato IN (" + placeholders + ") "
                "AND status='aberto' AND responsavel_tipo IN ('atendente','dono') LIMIT 1",
                aliases,
            ).fetchone()
        except sqlite3.Error:
            raise RegistrationError('contact_state_unavailable') from None
        finally:
            if attendance_db is not None:
                attendance_db.close()
        if human:
            raise RegistrationError('human_takeover')

    # A real inbound row is required even when the spool payload was created by
    # an internal caller. This excludes synthetic IDs and stale imports.
    source_id = request.get('source_message_id')
    if (not isinstance(source_id, str) or not source_id.strip()
            or source_id.startswith(('synthetic:', 'at:'))):
        raise RegistrationError('source_message_missing')
    conn = None
    try:
        conn = sqlite3.connect(f'file:{paths.messages_db}?mode=ro', uri=True, timeout=5)
        placeholders = ','.join('?' for _ in aliases)
        row = conn.execute(
            'SELECT 1 FROM messages WHERE message_id=? AND chat_id IN (' + placeholders + ') '
            'AND from_me=0 AND is_historical=0 LIMIT 1',
            [source_id, *aliases],
        ).fetchone()
    except (sqlite3.Error, OSError):
        raise RegistrationError('source_message_unavailable') from None
    finally:
        if conn is not None:
            conn.close()
    if row is None:
        raise RegistrationError('source_message_missing')
    return config


def current_booking_request(request, paths=None, config_path=CONFIG):
    """Recheck a confirmed booking against current authorization and identity."""
    if not isinstance(request, dict) or request.get('operation') not in {'book', 'reschedule'}:
        raise BookingError('invalid_request')
    try:
        now = datetime.now(timezone.utc)
        created = datetime.fromisoformat(request['created_at'].replace('Z', '+00:00')).astimezone(timezone.utc)
        confirmation = request['confirmation']
        confirmed_at = datetime.fromisoformat(confirmation['confirmed_at'].replace('Z', '+00:00')).astimezone(timezone.utc)
        expires = datetime.fromisoformat(confirmation['offer_expires_at'].replace('Z', '+00:00')).astimezone(timezone.utc)
    except (KeyError, ValueError, TypeError, AttributeError):
        raise BookingError('invalid_request') from None
    if created > now or now - created > timedelta(minutes=15):
        raise BookingError('request_expired')
    if (confirmation.get('explicit') is not True
            or confirmation.get('kind') != 'offer_acceptance'
            or confirmation.get('chat_id') != request.get('chat_id')
            or confirmation.get('requested_start') != request.get('requested_start')
            or confirmation.get('requested_end') != request.get('requested_end')
            or confirmed_at > now or now - confirmed_at > timedelta(minutes=15)
            or expires <= now):
        raise BookingError('confirmation_changed')
    paths = paths or panel_data.Paths()
    try:
        root_config = json.loads(Path(config_path).read_text())
        config = root_config['patient_directory']
    except (OSError, ValueError, KeyError, TypeError):
        raise BookingError('config_unavailable') from None
    if config.get('enabled') is not True or config.get('appointment_write_enabled') is not True:
        raise BookingError('appointment_writes_disabled')
    if (config.get('clinic_id') != request.get('clinic_id')
            or config.get('source_clinic_hash') != request.get('source_clinic_hash')):
        raise BookingError('clinic_mismatch')
    appointment_policy = root_config.get('appointment_policy')

    chat_id = request.get('chat_id')
    source_id = confirmation.get('message_id')
    if not isinstance(chat_id, str) or not chat_id or not isinstance(source_id, str) or not source_id.strip():
        raise BookingError('source_message_missing')
    if source_id.startswith(('synthetic:', 'at:')):
        raise BookingError('source_message_missing')
    contacts = panel_data.load_contacts(paths.contacts_json)
    aliases = panel_data._contact_aliases(contacts, chat_id)
    aliases = list(dict.fromkeys(aliases))
    records = [contacts[key] for key in aliases if isinstance(contacts.get(key), dict)]
    if not records:
        raise BookingError('contact_unavailable')
    if (any(record.get('blocked') is True or record.get('ai_enabled') is False
            or record.get('in_flow') is False
            or _is_personal_relationship(record.get('manual_relationship'))
            for record in records)
            or not any(record.get('ai_enabled') is True for record in records)):
        raise BookingError('contact_not_eligible')

    if paths.followups_db.is_file():
        lead_db = None
        try:
            lead_db = sqlite3.connect(f'file:{paths.followups_db}?mode=ro', uri=True, timeout=5)
            placeholders = ','.join('?' for _ in aliases)
            lead = lead_db.execute(
                'SELECT takeover, opt_out FROM lead_state WHERE chat_id IN (' + placeholders + ')', aliases,
            ).fetchall()
        except sqlite3.Error:
            raise BookingError('contact_state_unavailable') from None
        finally:
            if lead_db is not None:
                lead_db.close()
        if any(bool(row[0]) for row in lead):
            raise BookingError('human_takeover')
        if any(bool(row[1]) for row in lead):
            raise BookingError('contact_not_eligible')

    if paths.panel_db.is_file():
        attendance_db = None
        try:
            attendance_db = sqlite3.connect(f'file:{paths.panel_db}?mode=ro', uri=True, timeout=5)
            placeholders = ','.join('?' for _ in aliases)
            human = attendance_db.execute(
                "SELECT 1 FROM atendimentos WHERE contato IN (" + placeholders + ") "
                "AND status='aberto' AND responsavel_tipo IN ('atendente','dono') LIMIT 1", aliases,
            ).fetchone()
        except sqlite3.Error:
            raise BookingError('contact_state_unavailable') from None
        finally:
            if attendance_db is not None:
                attendance_db.close()
        if human:
            raise BookingError('human_takeover')

    conn = None
    try:
        conn = sqlite3.connect(f'file:{paths.messages_db}?mode=ro', uri=True, timeout=5)
        placeholders = ','.join('?' for _ in aliases)
        inbound = conn.execute(
            'SELECT 1 FROM messages WHERE message_id=? AND chat_id IN (' + placeholders + ') '
            'AND from_me=0 AND is_historical=0 LIMIT 1', [source_id, *aliases],
        ).fetchone()
        latest_inbound = conn.execute(
            'SELECT message_id FROM messages WHERE chat_id IN (' + placeholders + ') '
            'AND from_me=0 AND is_historical=0 ORDER BY COALESCE(timestamp, 0) DESC, id DESC LIMIT 1',
            aliases,
        ).fetchone()
    except (sqlite3.Error, OSError):
        raise BookingError('source_message_unavailable') from None
    finally:
        if conn is not None:
            conn.close()
    if inbound is None:
        raise BookingError('source_message_missing')
    if latest_inbound is None or latest_inbound[0] != source_id:
        raise BookingError('confirmation_changed')

    try:
        detail = panel_data.patient_details(paths, chat_id, config)
    except Exception:
        raise BookingError('patient_identity_unavailable') from None
    identity = detail.get('patient_directory') or {}
    if identity.get('status') != 'matched' or str(identity.get('patient_id')) != str(request.get('patient_id')):
        raise BookingError('patient_changed')
    if request['operation'] == 'reschedule':
        if config.get('schedule_enabled') is not True:
            raise BookingError('schedule_unavailable')
        try:
            original_verified = datetime.fromisoformat(request['original_verified_at'].replace('Z', '+00:00')).astimezone(timezone.utc)
        except (KeyError, ValueError, TypeError, AttributeError):
            raise BookingError('original_appointment_unverified') from None
        if original_verified > now or now - original_verified > timedelta(minutes=5):
            raise BookingError('original_appointment_unverified')
        try:
            schedule = load_schedule(
                paths.prontuario_verde_schedule_json,
                request['clinic_id'], request['source_clinic_hash'], now=now,
            )
        except ScheduleUnavailable:
            raise BookingError('schedule_unavailable') from None
        rows = [row for row in schedule['events']
                if isinstance(row, dict) and row.get('id') == str(request.get('appointment_id'))]
        if (len(rows) != 1 or rows[0].get('patient_id') != str(request.get('patient_id'))
                or rows[0].get('professional_id') != str(request.get('professional_id'))
                or not same_time(rows[0].get('start'), request.get('expected_start'))
                or not same_time(rows[0].get('end'), request.get('expected_end'))
                or str(rows[0].get('status', '')).casefold() not in {'agendado', 'confirmado'}):
            raise BookingError('original_appointment_changed')
        _validate_booking_policy(request, appointment_policy, established_patient=True,
                                 original=PolicyAppointment(
                                     request['appointment_type'], request['professional_key'],
                                     request['duration_min'],
                                 ))
    else:
        _validate_booking_policy(request, appointment_policy, established_patient=True)
    return config


def _validate_booking_policy(request, policy, *, established_patient=False, original=None):
    """Recompute the client policy and bind semantic keys to PV identifiers."""
    if not isinstance(policy, dict):
        raise BookingError('booking_policy_unavailable')
    professionals = policy.get('professional_ids')
    type_ids = policy.get('type_ids')
    unit_ids = policy.get('unit_ids')
    if (not isinstance(professionals, dict) or not isinstance(type_ids, dict)
            or not isinstance(unit_ids, list) or not unit_ids):
        raise BookingError('booking_policy_unavailable')
    professional_id = professionals.get(request.get('professional_key'))
    type_id = type_ids.get(request.get('appointment_type'))
    if (not isinstance(professional_id, (str, int)) or isinstance(professional_id, bool)
            or not re.fullmatch(r'[1-9][0-9]{0,19}', str(professional_id))
            or str(professional_id) != str(request.get('professional_id'))):
        raise BookingError('professional_policy_mismatch')
    if (not isinstance(type_id, (str, int)) or isinstance(type_id, bool)
            or not re.fullmatch(r'[1-9][0-9]{0,19}', str(type_id))
            or str(type_id) != str(request.get('type_id'))):
        raise BookingError('appointment_type_policy_mismatch')
    allowed_units = {
        str(value) for value in unit_ids
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        and re.fullmatch(r'[1-9][0-9]{0,19}', str(value))
    }
    if not allowed_units or str(request.get('unit_id')) not in allowed_units:
        raise BookingError('unit_policy_mismatch')
    context = request.get('policy_context')
    if not isinstance(context, dict):
        raise BookingError('booking_policy_context_missing')
    if request.get('operation') == 'book' and request.get('procedure_id') is not None:
        raise BookingError('team_confirmation_required')
    # Only the unique current patient-directory match is independent evidence
    # here. Treatment, chart verification, and added-procedure claims stay false
    # until the worker has an authoritative live source for each fact.
    decision = classify_booking(
        request.get('appointment_type'), policy=policy,
        professional=request.get('professional_key'),
        established_patient=established_patient,
        in_treatment=False, no_added_procedure=False, chart_verified=False,
        reschedule_of=original,
    )
    if (not decision.auto_book or decision.professional != request.get('professional_key')
            or decision.duration_minutes != request.get('duration_min')):
        raise BookingError('team_confirmation_required')


def _registration_needs_review(exc, adapter):
    code = getattr(exc, 'code', '')
    return bool(adapter and adapter.submitted) or code in {
        'outcome_uncertain', 'needs_review', 'lookup_failed',
    }


def process_registration(request, root=REGISTRATION_SPOOL, session=None, *, paths=None,
                         config_path=CONFIG, journal_dir=REGISTRATION_JOURNAL,
                         sync_lock_path=SYNC_LOCK):
    own_session = session is None
    session = session or BrowserSession()
    adapter = None
    try:
        config = current_registration(request, paths=paths, config_path=config_path)
        browser = session.acquire(request['source_clinic_hash'])
        directory_path = (paths or panel_data.Paths()).patient_directory_json
        adapter = RegistrationBrowser(browser, config, directory_path)
        adapter.before_submit_check = lambda: current_registration(
            request, paths=paths, config_path=config_path,
        )
        with sync_lock(sync_lock_path):
            result = ensure_patient(
                adapter,
                name=request['name'],
                phone=request['phone'],
                clinic_id=request['clinic_id'],
                source_clinic_hash=request['source_clinic_hash'],
                journal_dir=journal_dir,
            )
        if result.get('status') not in ('created', 'existing'):
            raise RegistrationError('invalid_registration_result')
        registration_queue.finish(root, request['request_id'], 'succeeded',
                                  result['status'], patient_id=result.get('patient_id'))
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if not isinstance(code, str) or not code.replace('_', '').isalnum():
            code = 'registration_failed'
        state = 'needs_review' if _registration_needs_review(exc, adapter) else 'failed'
        registration_queue.finish(root, request['request_id'], state, code)
        session.close()
    finally:
        if own_session:
            session.close()


def same_time(left, right):
    try:
        a = datetime.fromisoformat(left.replace('Z', '+00:00'))
        b = datetime.fromisoformat(right.replace('Z', '+00:00'))
        return a.tzinfo is not None and b.tzinfo is not None and a == b
    except (ValueError, TypeError, AttributeError):
        return False


def validate_event(event, request):
    if not isinstance(event, dict) or (
        event.get('id') != request['appointment_id']
        or not same_time(event.get('start'), request['expected_start'])
        or not same_time(event.get('end'), request['expected_end'])
        or event.get('professionals') != [request['professional_id']]
    ):
        raise CancelError('appointment_changed')
    return event


def cancelled(event):
    status = str(event.get('status', '')).strip().upper()
    return status == 'CANCELOU' or status.startswith('CANCELAD')


def current_request(request, paths=None, config_path=CONFIG):
    if request.get('operation') != 'cancel':
        raise CancelError('invalid_request')
    created = datetime.fromisoformat(request['created_at'].replace('Z', '+00:00'))
    age = datetime.now(timezone.utc) - created
    if age < timedelta(0) or age > timedelta(minutes=15):
        raise CancelError('request_expired')
    paths = paths or panel_data.Paths()
    config = json.loads(Path(config_path).read_text())['patient_directory']
    if config.get('enabled') is not True or config.get('cancellation_enabled') is not True:
        raise CancelError('cancellation_disabled')
    if config.get('clinic_id') != request['clinic_id'] or config.get('source_clinic_hash') != request['source_clinic_hash']:
        raise CancelError('clinic_mismatch')
    detail = panel_data.patient_details(paths, request['chat_id'], config)
    identity = detail.get('patient_directory') or {}
    if identity.get('status') != 'matched' or identity.get('patient_id') != request['patient_id']:
        raise CancelError('patient_changed')
    rows = [r for r in detail.get('pv_appointments', []) if r['id'] == request['appointment_id']]
    if len(rows) != 1 or rows[0].get('professional_id') != request['professional_id']:
        raise CancelError('appointment_changed')
    row = rows[0]
    if not same_time(row['start'], request['expected_start']) or not same_time(row['end'], request['expected_end']):
        raise CancelError('appointment_changed')
    if row['status'] not in ('agendado', 'cancelado'):
        raise CancelError('status_not_cancellable')
    return config


def record_cancelled(request, path=None):
    path = Path(path or panel_data.Paths().prontuario_verde_appointments_json)
    snapshot = json.loads(path.read_text())
    if snapshot['clinic_id'] != request['clinic_id'] or snapshot['source_clinic_hash'] != request['source_clinic_hash']:
        raise CancelError('clinic_mismatch')
    rows = [r for r in snapshot['appointments'] if r['id'] == request['appointment_id']]
    if len(rows) != 1 or rows[0]['patient_id'] != request['patient_id'] or not same_time(rows[0]['start'], request['expected_start']) or not same_time(rows[0]['end'], request['expected_end']):
        raise CancelError('appointment_changed')
    rows[0].update(status='cancelado', verified_at=datetime.now(timezone.utc).isoformat())
    fd, name = tempfile.mkstemp(prefix='.pv-appointments-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(snapshot, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class CancellationBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.submitted = False

    def evaluate(self, expression):
        return self.browser.evaluate(expression)

    def wait(self, expression, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            self.browser.command('wait', ['500'])
        raise CancelError('page_not_ready')

    def open_calendar(self, request):
        self.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda').click();true")
        self.wait("typeof window.calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
        professional = json.dumps(request['professional_id'])
        found = self.evaluate(f"Array.from(document.querySelector('#P41_PROFISSIONAL').options).some(o=>o.value==={professional})")
        if not found:
            raise CancelError('professional_missing')
        self.evaluate(f"apex.item('P41_PROFISSIONAL').setValue({professional});true")
        self.browser.command('wait', ['1500'])
        self.evaluate("(()=>{const e=document.querySelector('#P41_EXIBIR_CANCELAMENTOS');if(!e.checked)e.click();return true})()")
        date = datetime.fromisoformat(request['expected_start']).astimezone(SAO_PAULO).date().isoformat()
        self.evaluate(f"calendar.gotoDate({json.dumps(date)});calendar.refetchEvents();true")
        self.wait(f"calendar.getDate().toISOString().slice(0,10)==={json.dumps(date)} && apex.item('P41_PROFISSIONAL').getValue()==={professional}")
        return self.read_event(request)

    def read_event(self, request):
        appointment = json.dumps(request['appointment_id'])
        event = self.wait("""(()=>{const e=calendar.getEvents().find(e=>e.id===""" + appointment + """);if(!e)return null;
          const holder=document.createElement('div');holder.innerHTML=e.title;
          const detail=document.createElement('div');detail.innerHTML=(holder.querySelector('[title]')?.getAttribute('title')||e.title).replace(/<br\\s*\\/?>/gi,'\\n');
          const status=/SITUA[ÇC][ÃÂA]O:\\s*([^\\n]+)/i.exec(detail.textContent)?.[1]?.trim();
          return {id:e.id,start:e.startStr,end:e.endStr,professionals:e.getResources().map(r=>r.id),status:status||''};})()""")
        return validate_event(event, request)

    def open_event(self, request):
        appointment = json.dumps(request['appointment_id'])
        self.evaluate(f"calendar.getOption('eventClick')({{event:calendar.getEvents().find(e=>e.id==={appointment})}});true")
        identity = self.wait("(()=>{const id=apex.item('P41_OPCAO_ID_AGENDAMENTO').getValue();return id?{id,patient:apex.item('P41_OPCAO_ID_PACIENTE').getValue(),status:apex.item('P41_OPCAO_SITUACAO').getValue()}:null})()")
        if identity['id'] != request['appointment_id'] or identity['patient'] != request['patient_id']:
            raise CancelError('patient_changed')
        return identity

    def cancel(self, request, revalidate):
        event = self.open_calendar(request)
        identity = self.open_event(request)
        if cancelled(event):
            return event  # An earlier uncertain attempt already reached the target state.
        if identity['status'] != 'AGE' or event['status'].upper() != 'AGENDADO':
            raise CancelError('status_not_cancellable')
        self.evaluate("document.querySelector('#LINK_ALTERAR_SITUCAO').click();true")
        self.wait("document.querySelector('#LINK_SITUACAO_CANCELADO')?.getClientRects().length>0")
        self.evaluate("document.querySelector('#LINK_SITUACAO_CANCELADO').click();true")
        self.wait("document.querySelector('.swal2-deny')?.textContent.trim()==='Apenas cancelar'")
        revalidate()  # Config/identity may have changed while login was running.
        self.read_event(request)
        self.submitted = True  # Never automatically repeat a click with an uncertain outcome.
        self.evaluate("(()=>{const b=document.querySelector('.swal2-deny');if(b?.textContent.trim()!=='Apenas cancelar')throw Error('modal_changed');b.click();return true})()")
        self.browser.command('wait', ['1500'])
        self.evaluate('location.reload();true')
        self.wait("typeof window.calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
        event = self.open_calendar_after_reload(request)
        if not cancelled(event):
            raise CancelError('cancellation_unverified')
        self.open_event(request)
        return event

    def open_calendar_after_reload(self, request):
        # Reload normally preserves the date; explicitly restore it before reading.
        professional = json.dumps(request['professional_id'])
        self.evaluate(f"apex.item('P41_PROFISSIONAL').setValue({professional});true")
        self.browser.command('wait', ['1000'])
        self.evaluate("(()=>{const e=document.querySelector('#P41_EXIBIR_CANCELAMENTOS');if(!e.checked)e.click();return true})()")
        date = datetime.fromisoformat(request['expected_start']).astimezone(SAO_PAULO).date().isoformat()
        self.evaluate(f"calendar.gotoDate({json.dumps(date)});calendar.refetchEvents();true")
        self.browser.command('wait', ['1500'])
        return self.read_event(request)


class BrowserSession:
    """One authenticated browser, owned by the serial worker; credentials stay server-side."""
    def __init__(self):
        self.browser = None
        self.last_activity = 0.0

    def close(self):
        browser, self.browser = self.browser, None
        if browser:
            browser.close()

    def acquire(self, expected_clinic_hash):
        started = time.monotonic()
        reused = False
        if self.browser:
            try:
                reused = self.browser.refresh_authenticated()
            except Exception:
                reused = False
            if not reused:
                self.close()
        try:
            if not self.browser:
                self.browser = HermesBrowser()
                self.browser.login(json.loads(CREDENTIALS.read_text()), open_patients=False)
            if self.browser.source_clinic_hash != expected_clinic_hash:
                raise CancelError('clinic_mismatch')
        except Exception:
            self.close()
            raise
        self.last_activity = time.monotonic()
        print(json.dumps({'session': 'reused' if reused else 'authenticated',
                          'seconds': round(time.monotonic() - started, 2)}), flush=True)
        return self.browser

    def keep_local(self):
        # A local JS command also keeps agent-browser's daemon alive. Touching only
        # Hermes's Python lifecycle timestamp does not prevent daemon idle expiry.
        if self.browser and time.monotonic() - self.last_activity >= 45:
            try:
                self.browser.evaluate('true')
                self.last_activity = time.monotonic()
            except Exception:
                self.close()  # Reauthenticate on demand, never loop logins while idle.


def process(request, root=SPOOL, session=None):
    own_session = session is None
    session = session or BrowserSession()
    adapter = None
    try:
        current_request(request)
        adapter = CancellationBrowser(session.acquire(request['source_clinic_hash']))
        adapter.cancel(request, lambda: current_request(request))
        record_cancelled(request)
        invalidate_cancelled(request)
        queue.finish(root, request['request_id'], 'succeeded', 'cancelled')
    except Exception as exc:
        code = str(exc) if isinstance(exc, CancelError) else 'browser_unavailable'
        state = 'needs_review' if adapter and adapter.submitted else 'failed'
        queue.finish(root, request['request_id'], state, code)
        session.close()  # Discard uncertain UI state. Never replay a submitted action.
    finally:
        if own_session:
            session.close()


def process_booking(request, root=BOOKING_SPOOL, session=None, *, paths=None,
                    config_path=CONFIG, writer_factory=None,
                    sync_lock_path=SYNC_LOCK):
    """Process one confirmed booking without retries or unverified success."""
    own_session = session is None
    session = session or BrowserSession()
    factory = writer_factory or _default_appointment_writer_factory
    try:
        config = current_booking_request(request, paths=paths, config_path=config_path)
        session.acquire(request['source_clinic_hash'])
        writer = factory(session, request, config)
        if not isinstance(writer, ProntuarioVerdeAppointmentWriter):
            booking_queue.finish(root, request['request_id'], 'failed', 'writer_unavailable')
            session.close()
            return
        writer.port = _RevalidatingAppointmentPort(
            writer.port,
            lambda: current_booking_request(request, paths=paths, config_path=config_path),
        )
        guarded_port = writer.port
        with sync_lock(sync_lock_path):
            result = (writer.book(request) if request['operation'] == 'book'
                      else writer.reschedule(request))
        if guarded_port.guard_error is not None:
            exc = guarded_port.guard_error
            code = getattr(exc, 'code', 'authorization_changed')
            booking_queue.finish(root, request['request_id'], 'failed', code)
            session.close()
            return
        if isinstance(result, dict) and result.get('status') == 'verified':
            booking_queue.finish(root, request['request_id'], 'succeeded', 'verified', verified_result=result)
        elif isinstance(result, dict) and result.get('status') == 'needs_review':
            code = result.get('code')
            if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', code):
                code = 'post_save_unverified'
            booking_queue.finish(root, request['request_id'], 'needs_review', code)
            session.close()
        else:
            booking_queue.finish(root, request['request_id'], 'needs_review', 'post_save_unverified')
            session.close()
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if not isinstance(code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', code):
            code = 'booking_worker_failed'
        # The writer absorbs failures beyond its one submit boundary. An
        # unexpected exception here has uncertain side effects, so never retry.
        state = 'failed' if isinstance(exc, (BookingError, AppointmentWriteError)) else 'needs_review'
        try:
            booking_queue.finish(root, request['request_id'], state, code)
        except (ValueError, OSError):
            pass
        session.close()
    finally:
        if own_session:
            session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.getLogger('hermes_cli.auth').setLevel(logging.CRITICAL)
    os.umask(0o007)
    SPOOL.mkdir(mode=0o2770, parents=True, exist_ok=True)
    os.chmod(SPOOL, 0o2770)
    with (SPOOL / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue.initialize(SPOOL)
        registration_queue.initialize(REGISTRATION_SPOOL)
        booking_queue.initialize(BOOKING_SPOOL)
        session = BrowserSession()
        def request_stop(signum, frame):
            # Exit through finally, leaving an interrupted running item for review
            # at startup rather than waiting past systemd's stop deadline.
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        try:
            # Warm once at startup. No periodic login/HTTP keepalive when idle.
            config = json.loads(CONFIG.read_text()).get('patient_directory', {})
            if config.get('enabled') is True and (
                config.get('cancellation_enabled') is True
                or config.get('schedule_enabled') is True
                or config.get('registration_enabled') is True
            ):
                try:
                    session.acquire(config['source_clinic_hash'])
                except Exception:
                    print(json.dumps({'session': 'warmup_failed'}), flush=True)
            next_sync = 0.0
            while True:
                request = queue.claim_next(SPOOL)
                registration_request = None
                booking_request = None
                if request:
                    process(request, session=session)
                else:
                    registration_request = registration_queue.claim_next(REGISTRATION_SPOOL)
                    if registration_request:
                        process_registration(registration_request, session=session)
                    else:
                        booking_request = booking_queue.claim_next(BOOKING_SPOOL)
                        if booking_request:
                            process_booking(booking_request, session=session)
                if args.once:
                    return
                if not request and not registration_request and not booking_request and time.monotonic() >= next_sync:
                    next_sync = time.monotonic() + 1800
                    try:
                        config = json.loads(CONFIG.read_text()).get('patient_directory', {})
                        if config.get('enabled') is True and config.get('schedule_enabled') is True:
                            result = refresh_schedule(session.acquire(config['source_clinic_hash']), config)
                            print(json.dumps({'schedule_sync': 'succeeded', **result}), flush=True)
                    except Exception:
                        next_sync = time.monotonic() + 300
                        session.close()
                        print(json.dumps({'schedule_sync': 'failed'}), flush=True)
                session.keep_local()
                time.sleep(2)
        finally:
            session.close()


if __name__ == '__main__':
    main()
