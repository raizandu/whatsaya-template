import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

SCRIPTS = Path(__file__).resolve().parents[1] / 'deploy/scripts'
sys.path.insert(0, str(SCRIPTS))
import sync_prontuario_verde_schedule as schedule

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
CONFIG = dict(clinic_id='clinic', source_clinic_hash='a' * 64)
DIRECTORY = dict(source='prontuario_verde', complete=True, **CONFIG,
    generated_at=NOW.isoformat(), patients=[dict(id='123', record_number='403', phones=[])])
EVENT = dict(id='901', record_number='403', professional_id='77', status='AGENDADO',
    start='2026-09-24T09:30:00-03:00', end='2026-09-24T10:00:00-03:00')


def build(events=None, directory=None):
    return schedule.build_snapshot(dict(professionals=[dict(id='77', name='Dra. Exemplo')],
        events=events if events is not None else [EVENT]), directory or DIRECTORY, CONFIG,
        NOW, NOW + timedelta(days=366), now=NOW)


class ScheduleSyncTests(unittest.TestCase):
    def test_joins_only_exact_record_code_and_discards_patient_content(self):
        row = dict(EVENT, title='Private patient title', name='Private patient name')
        result = build([row])
        self.assertEqual(result['appointments'][0]['patient_id'], '123')
        self.assertNotIn('Private', json.dumps(result))
        self.assertEqual(result['appointments'][0]['professional_name'], 'Dra. Exemplo')

    def test_agenda_receives_patient_label_and_all_professionals(self):
        result = build([dict(EVENT, patient_name="Paciente Exemplo")])
        self.assertEqual(result['appointments'][0]['patient_name'], 'Paciente Exemplo')
        self.assertEqual(result['appointments'][0]['record_number'], '403')
        self.assertEqual(result['professionals'], [{'id': '77', 'name': 'Dra. Exemplo'}])
        self.assertEqual(build([])['professionals'], result['professionals'])

    def test_cancelled_unlinked_and_unknown_status_do_not_become_next_appointments(self):
        rows = [dict(EVENT, id='1', status='CANCELOU'), dict(EVENT, id='2', record_number=None),
                dict(EVENT, id='3', record_number='999'), dict(EVENT, id='4', status='UNKNOWN')]
        result = build(rows)
        self.assertEqual(result['appointments'], [])
        self.assertEqual(result['skipped_events'], 4)

    def test_duplicate_codes_events_stale_or_cross_clinic_fail_closed(self):
        for directory in (dict(DIRECTORY, clinic_id='other'),
                          dict(DIRECTORY, source_clinic_hash='b' * 64),
                          dict(DIRECTORY, complete=False),
                          dict(DIRECTORY, generated_at=(NOW - timedelta(hours=25)).isoformat()),
                          dict(DIRECTORY, patients=DIRECTORY['patients'] * 2)):
            with self.subTest(directory=directory), self.assertRaises(schedule.SyncError):
                build(directory=directory)
        with self.assertRaises(schedule.SyncError):
            build([EVENT, EVENT])

    def test_invalid_time_or_unknown_professional_is_not_published(self):
        for changes in ({'start': '2026-09-24T09:30:00'}, {'end': EVENT['start']},
                        {'professional_id': '999'}, {'start': '2028-01-01T09:30:00-03:00'}):
            with self.subTest(changes=changes), self.assertRaises(schedule.SyncError):
                build([dict(EVENT, **changes)])

    def test_cancellation_removes_only_its_row_without_extending_cache_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'schedule.json'
            snapshot = build([EVENT, dict(EVENT, id='902')])
            path.write_text(json.dumps(snapshot))
            schedule.invalidate_cancelled(dict(CONFIG, appointment_id='901'), path)
            result = json.loads(path.read_text())
            self.assertEqual([r['id'] for r in result['appointments']], ['902'])
            self.assertEqual(result['generated_at'], snapshot['generated_at'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)



@unittest.skipUnless(shutil.which('node'), 'native JavaScript contract requires Node')
class ScopedCalendarReadTests(unittest.TestCase):
    def read(self, mode='ok', include_labels=False, events=None):
        class Browser:
            source_clinic_hash = CONFIG['source_clinic_hash']
            def evaluate(inner, expression):
                fixture = r"""
                const params={profissional_id:'77',unidade_id:'22',checksum:'fixture'};
                const source={meta:{url:'https://app.prontuarioverde.com.br/ords/prontuario/agendaProfissional/buscar',method:'POST',extraParams:params}};
                let current=source;
                const calendar={getEventSources:()=>[{internalEventSource:current}]};
                const apex={item:id=>({getValue:()=>id==='P41_PROFISSIONAL'?(mode==='dom_mismatch'?'88':'77'):'22'})};
                if(mode==='source_mismatch')params.profissional_id='88';
                const document={
                  querySelector:()=>({options:[{value:'77',text:'Profissional de teste'}]}),
                  createElement:()=>({innerHTML:'',querySelector:()=>null,get textContent(){return this.innerHTML.replace(/<[^>]+>/g,'')}})
                };
                const fetch=async(url,options)=>{
                  if(new URLSearchParams(options.body).get('profissional_id')!=='77')throw Error('params_rewritten');
                  if(mode==='changed_checksum')params.checksum='changed';
                  if(mode==='replaced_source')current={...source};
                  return {ok:true,json:async()=>rows};
                };
                """
                rows = events if events is not None else [{
                    'id':'901', 'resourceId':'77', 'title':'Pessoa Exemplo (403)<br>SITUAÇÃO: AGENDADO',
                    'start':EVENT['start'], 'end':EVENT['end'],
                }]
                script = 'const mode=' + json.dumps(mode) + ';const rows=' + json.dumps(rows) + ';' + fixture
                script += expression + ".then(r=>process.stdout.write(JSON.stringify({data:r}))).catch(e=>process.stdout.write(JSON.stringify({error:e.message})))"
                result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True,
                                        text=True, check=True, timeout=10)
                value = json.loads(result.stdout)
                if 'error' in value:
                    raise RuntimeError(value['error'])
                return value['data']
        return schedule.read_calendar_events(Browser(), CONFIG, NOW, NOW+timedelta(days=2),
                                             professional_id='77', unit_id='22', include_labels=include_labels)

    def test_filter_selection_waits_for_unit_before_professional(self):
        class Browser:
            def evaluate(inner, expression):
                fixture=r"""
                const values={P41_UNIDADE_FILTRO:'',P41_PROFISSIONAL:''};const calls=[];
                const params={unidade_id:'',profissional_id:''};const jQuery={active:0};
                const document={getElementById:id=>({options:[{value:''},{value:id==='P41_UNIDADE_FILTRO'?'22':'77'}]})};
                const apex={item:id=>({getValue:()=>values[id],setValue:value=>{
                  calls.push(id);values[id]=value;
                  if(id==='P41_UNIDADE_FILTRO'){
                    jQuery.active++;setTimeout(()=>{params.unidade_id=value;params.profissional_id='';values.P41_PROFISSIONAL='';jQuery.active--},5);
                  }else params.profissional_id=value;
                }})};
                const calendar={getEventSources:()=>[{internalEventSource:{meta:{extraParams:params}}}]};
                """
                result=subprocess.run([shutil.which('node'),'-e',fixture+expression+
                    '.then(ok=>process.stdout.write(JSON.stringify({ok,calls,values})))'],
                    capture_output=True,text=True,check=True,timeout=10)
                inner.result=json.loads(result.stdout)
                return inner.result['ok']
        browser=Browser()
        schedule.select_calendar_scope(browser,'77','22')
        self.assertEqual(browser.result['calls'],['P41_UNIDADE_FILTRO','P41_PROFISSIONAL'])
        self.assertEqual(browser.result['values']['P41_PROFISSIONAL'],'77')

    def test_native_scope_keeps_all_events_and_omits_patient_labels_by_default(self):
        result = self.read()
        self.assertEqual(result['events'], [EVENT])
        self.assertNotIn('Pessoa Exemplo', json.dumps(result))
        self.assertEqual(self.read(include_labels=True)['events'][0]['patient_name'], 'Pessoa Exemplo')

    def test_mismatched_or_changed_signed_scope_never_becomes_empty_availability(self):
        for mode in ('dom_mismatch', 'source_mismatch', 'changed_checksum', 'replaced_source'):
            with self.subTest(mode=mode), self.assertRaisesRegex(schedule.SyncError, 'schedule_read_failed'):
                self.read(mode)

    def test_empty_native_response_is_read_without_claiming_opening_completeness(self):
        result = self.read(events=[])
        self.assertEqual(result['events'], [])
        self.assertNotIn('complete', result)

    def test_foreign_professional_and_malformed_intervals_fail_closed(self):
        for changes in ({'resourceId':'88'}, {'end':EVENT['start']},
                        {'start':'2026-09-24T09:30:00'}):
            row = {'id':'901','resourceId':'77','title':'Pessoa (403)<br>SITUAÇÃO: AGENDADO',
                   'start':EVENT['start'],'end':EVENT['end'],**changes}
            with self.subTest(changes=changes), self.assertRaises(schedule.SyncError):
                self.read(events=[row])

if __name__ == '__main__':
    unittest.main()
