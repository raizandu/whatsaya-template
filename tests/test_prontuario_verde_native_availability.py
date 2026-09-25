import copy
import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/scripts'))
from prontuario_verde_native_availability import normalize_openings, READ_OPENINGS, READ_DETAILS
from prontuario_verde_native_booking import NativeBookingError


SOURCE = {'unit_id':'22', 'step':'00:15:00', 'events':[
    {'id':'10','start':'2031-09-24T08:30:00-03:00','end':'2031-09-24T10:30:00-03:00','all_day':False},
]}
DETAILS = [{'id':'10','fields':{
    'P173_PROFISSIONAL':'77','P173_DT_BASE_INICIO':'24/09/2031',
    'P173_TURNO_1_INI':'08:30','P173_TURNO_1_FIM':'10:30','P173_DURACAO_LIVRE':'S',
}}]


def normalize(source=SOURCE, details=DETAILS):
    return normalize_openings(source, details, unit_id='22', professional_id='77', day=date(2031,9,24))


class NativeOpeningTests(unittest.TestCase):
    def test_actual_opening_and_its_grid_define_candidates(self):
        intervals, starts = normalize()
        self.assertEqual(len(intervals), 1)
        self.assertEqual(len(starts), 8)
        self.assertEqual(starts[0].isoformat(), SOURCE['events'][0]['start'])
        self.assertEqual(starts[-1].strftime('%H:%M'), '10:15')

    def test_empty_calendar_cannot_create_an_opening(self):
        self.assertEqual(normalize({**SOURCE,'events':[]}, []), ((), ()))

    def test_another_professionals_opening_is_not_offered(self):
        details=copy.deepcopy(DETAILS)
        details[0]['fields']['P173_PROFISSIONAL']='88'
        self.assertEqual(normalize(details=details), ((), ()))

    def test_incomplete_duplicate_wrong_unit_and_unverified_grid_fail_closed(self):
        for source, details in (
            (SOURCE, []), (SOURCE, DETAILS*2), ({**SOURCE,'events':SOURCE['events']*2}, DETAILS*2),
            ({**SOURCE,'unit_id':'23'}, DETAILS), ({**SOURCE,'step':'00:00:00'}, DETAILS),
            ({**SOURCE,'step':None}, DETAILS),
        ):
            with self.subTest(source=source), self.assertRaises(NativeBookingError):
                normalize(source, details)

    def test_calendar_and_detail_must_agree_on_exact_dated_interval(self):
        for field, value in (('P173_DT_BASE_INICIO','25/09/2031'),
                             ('P173_TURNO_1_INI','09:00'), ('P173_TURNO_1_FIM','11:00'),
                             ('P173_PROFISSIONAL',''), ('P173_DURACAO_LIVRE','N')):
            details=copy.deepcopy(DETAILS)
            details[0]['fields'][field]=value
            with self.subTest(field=field), self.assertRaises(NativeBookingError):
                normalize(details=details)

    def test_naive_invalid_and_all_day_events_are_not_openings(self):
        for update in ({'start':'2031-09-24T08:30:00'}, {'all_day':True}, {'id':'invalid'}):
            source=copy.deepcopy(SOURCE)
            source['events'][0].update(update)
            with self.subTest(update=update), self.assertRaises(NativeBookingError):
                normalize(source)



@unittest.skipUnless(shutil.which('node'), 'native JavaScript contract requires Node')
class NativeOpeningJavaScriptTests(unittest.TestCase):
    def run_js(self, script):
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True,check=True,timeout=10)
        return json.loads(result.stdout)

    def test_opening_source_must_finish_fetching_in_the_requested_scope(self):
        fixture=r"""
        const source={isFetching:false,fetchRange:{start:new Date('2031-09-22T00:00:00-03:00'),end:new Date('2031-09-29T00:00:00-03:00')}};
        const c={getEventSources:()=>[{internalEventSource:source}],view:{activeStart:source.fetchRange.start,activeEnd:source.fetchRange.end},
          getOption:()=> '00:15:00',getEvents:()=>[{id:'10',start:new Date('2031-09-24T08:30:00-03:00'),end:new Date('2031-09-24T10:30:00-03:00'),startStr:'2031-09-24T08:30:00-03:00',endStr:'2031-09-24T10:30:00-03:00',allDay:false}]};
        source._raw=(info,success)=>success(c.getEvents().map(e=>({id:e.id,start:e.startStr,end:e.endStr})));
        const $=()=>({data:()=>c});const apex={item:id=>({getValue:()=>id==='P172_UNIDADE'?'22':''})};
        """
        expression=READ_OPENINGS.replace('__DAY__',json.dumps('2031-09-24T00:00:00-03:00')).replace('__UNIT__','"22"')
        self.assertEqual(self.run_js(fixture+expression+'.then(r=>process.stdout.write(JSON.stringify(r)));'), SOURCE)
        for change in ('source.isFetching=true;', 'source.fetchRange.start={};',
                       "source.fetchRange.end=new Date('2031-09-23T00:00:00-03:00');"):
            self.assertIsNone(self.run_js(fixture+change+expression+'.then(r=>process.stdout.write(JSON.stringify(r)));'))
        for change in ("source._raw=(info,success,failure)=>failure();",
                       "source._raw=(info,success)=>success([]);"):
            result=self.run_js(fixture+change+expression+".then(()=>process.stdout.write(JSON.stringify({ok:true}))).catch(e=>process.stdout.write(JSON.stringify({error:e.message})))")
            self.assertIn(result.get('error'),('opening_read_failed','opening_changed'))


    def test_detail_reader_uses_only_ready_read_action_and_restores_selector(self):
        fixture=r"""
        let selected='10';const calls=[];
        const required=['P173_PROFISSIONAL','P173_DT_BASE_INICIO','P173_TURNO_1_INI','P173_TURNO_1_FIM','P173_DURACAO_LIVRE'];
        const action={action:'NATIVE_EXECUTE_PLSQL_CODE',attribute01:'#P173_ID_AGENDAMENTO',attribute02:required.map(id=>'#'+id).join(','),ajaxIdentifier:'read-fixture'};
        const apex={item:id=>({getValue:()=>id==='P173_TIPO'?'E':id==='P173_UNIDADE'?'22':selected,setValue:(v,unused,suppress)=>{if(!suppress)throw Error('change_fired');selected=v}}),
          da:{gEventList:[{bindEventType:'click',actionList:[{...action,ajaxIdentifier:'write-fixture'}]},{bindEventType:'ready',actionList:[action]}]},
          server:{plugin:async(id,args)=>{calls.push({id,selected});return {item:required.filter(x=>!incomplete||x!=='P173_PROFISSIONAL').map(id=>({id,value:'fixture'}))}}}};
        """
        expression=READ_DETAILS.replace('__UNIT__','"22"').replace('__IDS__','["10","11"]')
        ending=".then(rows=>process.stdout.write(JSON.stringify({rows,selected,calls}))).catch(e=>process.stdout.write(JSON.stringify({error:e.message,selected,calls})))"
        result=self.run_js('const incomplete=false;'+fixture+expression+ending)
        self.assertEqual(result['selected'],'10')
        self.assertEqual([row['id'] for row in result['rows']],['10','11'])
        self.assertEqual([call['id'] for call in result['calls']],['read-fixture']*2)
        result=self.run_js('const incomplete=true;'+fixture+expression+ending)
        self.assertEqual(result['error'],'detail_incomplete')
        self.assertEqual(result['selected'],'10')
        self.assertEqual(len(result['calls']),1)

if __name__ == '__main__':
    unittest.main()
