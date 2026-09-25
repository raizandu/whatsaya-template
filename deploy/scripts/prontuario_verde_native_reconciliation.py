"""Clinic-bound identity and persisted appointment reads for the native writer.

All navigation uses a separate authenticated browser. Patient names are kept
only in this operation's memory for autocomplete; raw appointment notes never
leave the browser. An absent old ID is not proof of cancellation.
"""
from datetime import timedelta
import re

from patient_directory import normalize_phone
from register_prontuario_verde_patient import RegistrationBrowser
from prontuario_verde_native_availability import read_snapshot
from prontuario_verde_native_booking import NativeBookingError, ProntuarioVerdeHermesPort, SAO_PAULO
from sync_prontuario_verde_schedule import select_calendar_scope, read_calendar_events, zoned


INACTIVE = {'CANCELOU', 'CANCELADO', 'CANCELADA', 'REMARCADO', 'REMARCADA'}


class NativeBookingReader:
    def __init__(self, browser, config, request, directory_path):
        self.browser = browser
        self.config = config
        self.request = request
        self.directory_path = directory_path
        self.port = ProntuarioVerdeHermesPort(browser, config)
        self.patient = None
        self.last_targets = []

    def select_patient(self, writer_browser, patient_id):
        if writer_browser is self.browser or str(patient_id) != str(self.request['patient_id']):
            raise NativeBookingError('patient_selection_unverified')
        self.port._check_scope(self.request)
        phone = normalize_phone(self.request.get('chat_id'))
        if phone is None:
            raise NativeBookingError('patient_phone_unverified')
        # Full existing directory read validates uniqueness and obtains only the
        # requested phone's name. This path never invokes RegistrationBrowser.create.
        found = RegistrationBrowser(self.browser, self.config, self.directory_path).lookup(phone, '')
        matches = found.get('matches') if isinstance(found, dict) else None
        if not isinstance(matches, list) or len(matches) != 1:
            raise NativeBookingError('patient_identity_unverified')
        patient = matches[0]
        if (patient.get('id') != str(patient_id) or phone not in patient.get('phones', [])
                or not isinstance(patient.get('name'), str) or not patient['name'].strip()
                or not re.fullmatch(r'[1-9][0-9]*', str(patient.get('record_number', '')))):
            raise NativeBookingError('patient_identity_unverified')
        self.patient = patient
        return ProntuarioVerdeHermesPort(writer_browser, self.config).select_patient(
            str(patient_id), patient['name'], phone,
        )

    def opening(self, request):
        self._require_identity(request)
        return read_snapshot(self.browser, self.config, request)

    def _require_identity(self, request):
        self.port._check_scope(request)
        if self.patient is None or self.patient['id'] != str(request['patient_id']):
            raise NativeBookingError('patient_identity_unverified')

    def _events(self, request, timestamp):
        self._require_identity(request)
        self.browser.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda').click();true")
        self.port._wait("typeof calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
        select_calendar_scope(self.browser, str(request['professional_id']), str(request['unit_id']))
        start = zoned(timestamp).astimezone(SAO_PAULO).replace(hour=0, minute=0, second=0, microsecond=0)
        return read_calendar_events(self.browser, self.config, start, start+timedelta(days=1),
                                    professional_id=str(request['professional_id']), unit_id=str(request['unit_id']))['events']

    def targets(self, request):
        self.last_targets = []
        events = self._events(request, request['requested_start'])
        candidates = [e for e in events if e.get('record_number') == self.patient['record_number']
                      and str(e.get('status') or '').upper() not in INACTIVE
                      and zoned(e['start']) == zoned(request['requested_start'])
                      and zoned(e['end']) == zoned(request['requested_end'])]
        rows = []
        for event in candidates:
            if any(other['id'] != event['id'] and str(other.get('status') or '').upper() not in INACTIVE
                   and zoned(other['start']) < zoned(event['end'])
                   and zoned(event['start']) < zoned(other['end']) for other in events):
                raise NativeBookingError('post_save_conflict')
            if str(event.get('status') or '').upper() not in {'AGENDADO', 'CONFIRMADO'}:
                raise NativeBookingError('target_state_unverified')
            inspect = {**request, 'operation':'reschedule', 'appointment_id':event['id'],
                       'expected_start':request['requested_start'], 'expected_end':request['requested_end']}
            self.port._open_original_for_edit(inspect)
            form = self.port._read_form()
            self.port._validate_original_form(form, inspect)
            rows.append({
                'appointment_id':event['id'], 'patient_id':form['patient_id'],
                'professional_id':form['professional_id'], 'unit_id':form['unit_id'],
                'type_id':form['type_id'], 'duration_min':int(form['duration_min']),
                'start':form['start'], 'end':form['end'], 'status':event['status'],
                'request_marker':form['request_marker'],
            })
        self.last_targets = rows
        return {'complete':True, 'clinic_id':request['clinic_id'],
                'source_clinic_hash':request['source_clinic_hash'], 'rows':rows}

    def original_before_save(self, request):
        events = self._events(request, request['expected_start'])
        rows = [event for event in events if event['id'] == str(request['appointment_id'])]
        if (len(rows) != 1 or rows[0].get('record_number') != self.patient['record_number']
                or str(rows[0].get('status') or '').upper() not in {'AGENDADO', 'CONFIRMADO'}):
            raise NativeBookingError('original_appointment_changed')
        self.port._open_original_for_edit(request)
        form = self.port._read_form()
        self.port._validate_original_form(form, request)
        return {**form, "record_number": self.patient["record_number"]}

    def original_after_save(self, request):
        self._require_identity(request)
        # A fresh exact target with the original ID proves that this same
        # appointment moved. If PV changed IDs, require an explicit inactive old
        # row; its absence from this date's feed is deliberately insufficient.
        retained = [row for row in self.last_targets if row['appointment_id'] == str(request['appointment_id'])]
        moved = (len(retained) == 1
                 and zoned(retained[0]['start']) == zoned(request['requested_start'])
                 and zoned(retained[0]['start']) != zoned(request['expected_start']))
        if not moved:
            events = self._events(request, request['expected_start'])
            old = [e for e in events if e['id'] == str(request['appointment_id'])]
            if (len(old) != 1 or old[0].get('record_number') != self.patient['record_number']
                    or str(old[0].get('status') or '').upper() not in INACTIVE
                    or zoned(old[0]['start']) != zoned(request['expected_start'])
                    or zoned(old[0]['end']) != zoned(request['expected_end'])):
                raise NativeBookingError('old_appointment_state_unverified')
        return {
            'old_appointment_id':str(request['appointment_id']), 'old_patient_id':str(request['patient_id']),
            'old_professional_id':str(request['professional_id']), 'old_unit_id':str(request['unit_id']),
            'old_type_id':str(request['type_id']), 'old_duration_min':int(request['duration_min']),
            'old_procedure_id':request.get('procedure_id'),
            'old_start':request['expected_start'], 'old_end':request['expected_end'],
            'old_appointment_active':False,
        }
