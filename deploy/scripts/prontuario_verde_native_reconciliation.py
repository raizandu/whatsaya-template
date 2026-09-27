"""Clinic-bound identity and persisted appointment reads for the native writer.

All navigation uses a separate authenticated browser. Patient names are kept
only in this operation's memory for autocomplete; raw appointment notes never
leave the browser. An absent old calendar ID alone is not proof of cancellation.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from patient_directory import normalize_phone
from register_prontuario_verde_patient import RegistrationBrowser
from prontuario_verde_native_availability import read_snapshot
from prontuario_verde_native_booking import NativeBookingError, ProntuarioVerdeHermesPort, SAO_PAULO, request_marker
from sync_prontuario_verde_schedule import open_calendar_page, select_calendar_scope, read_calendar_events, zoned


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
        open_calendar_page(self.browser)
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
            form = self.port._open_original_for_edit(inspect)
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
        form = self.port._open_original_for_edit(request)
        return {**form, "record_number": self.patient["record_number"]}

    def original_after_save(self, request):
        self._require_identity(request)
        # A fresh exact target with the original ID proves that this same
        # appointment moved. Changed IDs need an inactive old row or a verified
        # native future-ID replacement; calendar absence alone is insufficient.
        retained = [row for row in self.last_targets if row['appointment_id'] == str(request['appointment_id'])]
        moved = (len(retained) == 1
                 and zoned(retained[0]['start']) == zoned(request['requested_start'])
                 and zoned(retained[0]['start']) != zoned(request['expected_start']))
        if not moved:
            events = self._events(request, request['expected_start'])
            old = [e for e in events if e['id'] == str(request['appointment_id'])]
            inactive = (len(old) == 1 and old[0].get('record_number') == self.patient['record_number']
                        and str(old[0].get('status') or '').upper() in INACTIVE
                        and zoned(old[0]['start']) == zoned(request['expected_start'])
                        and zoned(old[0]['end']) == zoned(request['expected_end']))
            if not inactive and not self._verify_replaced_future_id(request, events):
                raise NativeBookingError('old_appointment_state_unverified')
        return {
            'old_appointment_id':str(request['appointment_id']), 'old_patient_id':str(request['patient_id']),
            'old_professional_id':str(request['professional_id']), 'old_unit_id':str(request['unit_id']),
            'old_type_id':str(request['type_id']), 'old_duration_min':int(request['duration_min']),
            'old_procedure_id':request.get('procedure_id'),
            'old_start':request['expected_start'], 'old_end':request['expected_end'],
            'old_appointment_active':False,
        }


    def _verify_replaced_future_id(self, request, old_events):
        # Cross-date native edits can replace the ID instead of leaving an
        # inactive calendar row. Absence alone still never proves replacement.
        if zoned(request['expected_start']) <= datetime.now(timezone.utc) or len(self.last_targets) != 1:
            return False
        target = self.last_targets[0]
        if (target.get('appointment_id') == str(request['appointment_id'])
                or target.get('request_marker') != request_marker(request)
                or any(str(target.get(k)) != str(request[k]) for k in
                       ('patient_id', 'professional_id', 'unit_id', 'type_id', 'duration_min'))
                or zoned(target['start']) != zoned(request['requested_start'])
                or zoned(target['end']) != zoned(request['requested_end'])):
            return False
        if any(e['id'] == str(request['appointment_id']) or
               (e.get('record_number') == self.patient['record_number']
                and str(e.get('status') or '').upper() not in INACTIVE
                and zoned(e['start']) < zoned(request['expected_end'])
                and zoned(request['expected_start']) < zoned(e['end'])) for e in old_events):
            return False
        # Positive control in the same authenticated native read: an empty or
        # expired session must not make a missing old ID look like success.
        current = self._read_native_identity(target['appointment_id'])
        expected = {'state':'present', 'appointment_id':target['appointment_id'],
                    'patient_id':str(request['patient_id']), 'unit_id':str(request['unit_id']),
                    'status':None, 'past':'N'}
        if (not isinstance(current, dict) or current.get('status') not in {'AGE','CON'}
                or any(current.get(k) != v for k,v in expected.items() if k != 'status')):
            return False
        missing = self._read_native_identity(str(request['appointment_id']))
        return missing == {'state':'empty'}

    def _read_native_identity(self, appointment_id):
        """Read only the observed event-selection action, never its write actions."""
        self.port._check_scope(self.request)
        if not re.fullmatch(r'[1-9][0-9]*', str(appointment_id)):
            raise NativeBookingError('old_appointment_state_unverified')
        script = r"""(async()=>{
          const actions=apex.da.gEventList.filter(e=>e.bindEventType==='SelecionouEventoAgendaJS')
            .flatMap(e=>e.actionList).filter(a=>a.action==='NATIVE_EXECUTE_PLSQL_CODE');
          if(actions.length!==1) return {state:'unavailable'};
          const a=actions[0];
          if(a.attribute01!=='#P41_AUX_ID_AGE_SEL'||a.attribute02!=='#P41_AUX_CAL_OBJ,#P41_AGEREC_ID')
            return {state:'unavailable'};
          apex.item('P41_AUX_ID_AGE_SEL').setValue(__ID__,null,true);
          const r=await apex.server.plugin(a.ajaxIdentifier,{pageItems:a.attribute01},{dataType:'json'});
          if(!r || Object.keys(r).length!==1 || !Array.isArray(r.item) || r.item.length!==2)
            return {state:'unavailable'};
          const obj=r.item.find(i=>i.id==='P41_AUX_CAL_OBJ');
          const recurrence=r.item.find(i=>i.id==='P41_AGEREC_ID');
          if(!obj||!recurrence||recurrence.value!=='') return {state:'unavailable'};
          if(obj.value==='') return {state:'empty'};
          if(typeof obj.value!=='string') return {state:'unavailable'};
          const m=/^apex\.event\.trigger\(document,'opcoesNavegacao', \{id: '([1-9][0-9]*)', dataPassada: '([SN])', altsit: '[SN]', id_paciente: '([1-9][0-9]*)', iduni: '([1-9][0-9]*)', situacao: '([A-Z]+)'\}\);$/.exec(obj.value);
          if(!m) return {state:'unavailable'};
          return {state:'present',appointment_id:m[1],past:m[2],patient_id:m[3],unit_id:m[4],status:m[5]};
        })()""".replace('__ID__', json.dumps(str(appointment_id)))
        result = self.browser.evaluate(script)
        self.browser.read_clinic_identity()
        self.port._check_scope(self.request)
        return result
