"""Read dated PV openings and busy intervals in a dedicated reader session.

This reader navigates away from any appointment form. Never bind it to the
writer's browser: its authenticated session must be owned separately. It does
not click opening/appointment save controls or expose signed URLs/checksums.
"""
from datetime import datetime, timedelta, timezone
import json
import re

from prontuario_verde_availability import Interval, OpeningSnapshot
from prontuario_verde_native_booking import NativeBookingError, ProntuarioVerdeHermesPort, SAO_PAULO
from sync_prontuario_verde_schedule import read_calendar_events, select_calendar_scope, zoned


READ_OPENINGS = r"""(async()=>{
  const c=$('#regdesk_calendar').data('fullCalendar');
  const sources=c.getEventSources();
  if(sources.length!==1||sources[0].internalEventSource.isFetching) return null;
  const range=sources[0].internalEventSource.fetchRange;
  const day=new Date(__DAY__);
  if(!range||![+range.start,+range.end,+c.view.activeStart,+c.view.activeEnd,+day].every(Number.isFinite)||+range.start>+day||+range.end<=+day||+c.view.activeStart>+day||+c.view.activeEnd<=+day)return null;
  if(String(apex.item('P172_UNIDADE').getValue())!==__UNIT__||String(apex.item('P172_AUX_PROFISSIONAL_SEL').getValue())!=='')throw Error('scope_changed');
  const events=c.getEvents().filter(e=>+e.start<+day+86400000&&+e.end>+day);
  if(events.length>100)throw Error('opening_limit');
  const raw=sources[0].internalEventSource._raw;
  if(typeof raw!=='function')throw Error('opening_source_changed');
  const fresh=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('opening_timeout')),15000);
    raw({start:day,end:new Date(+day+86400000)},rows=>{clearTimeout(timer);resolve(rows)},()=>{clearTimeout(timer);reject(Error('opening_read_failed'))});
  });
  if(!Array.isArray(fresh)||fresh.length!==events.length||fresh.some(row=>{
    const matches=events.filter(e=>String(e.id)===String(row.id));
    return matches.length!==1||+matches[0].start!==+new Date(row.start)||+matches[0].end!==+new Date(row.end);
  }))throw Error('opening_changed');
  if(String(apex.item('P172_UNIDADE').getValue())!==__UNIT__||String(apex.item('P172_AUX_PROFISSIONAL_SEL').getValue())!=='')throw Error('scope_changed');
  return {unit_id:String(apex.item('P172_UNIDADE').getValue()),step:c.getOption('slotDuration'),
    events:events.map(e=>({id:String(e.id),start:e.startStr,end:e.endStr,all_day:e.allDay}))};
})()"""

DETAIL_READY = r"""(()=>{
  if(typeof apex==='undefined'||typeof jQuery==='undefined'||jQuery.active!==0||!Array.isArray(apex.da?.gEventList))return false;
  if(!document.querySelector('#P173_ID_AGENDAMENTO')||String(apex.item('P173_TIPO').getValue())!=='E'||String(apex.item('P173_UNIDADE').getValue())!==__UNIT__)return false;
  return apex.da.gEventList.some(e=>e.bindEventType==='ready'&&e.actionList.some(a=>a.action==='NATIVE_EXECUTE_PLSQL_CODE'&&a.attribute01==='#P173_ID_AGENDAMENTO'));
})()"""


# The observed ready action reads one existing opening by ID. Its session-issued
# identifier remains in the browser; no save/change action chain is executed.
READ_DETAILS = r"""(async()=>{
  if(String(apex.item('P173_TIPO').getValue())!=='E'||String(apex.item('P173_UNIDADE').getValue())!==__UNIT__)throw Error('scope_changed');
  const required=['P173_PROFISSIONAL','P173_DT_BASE_INICIO','P173_TURNO_1_INI','P173_TURNO_1_FIM','P173_DURACAO_LIVRE'];
  const actions=apex.da.gEventList.filter(e=>e.bindEventType==='ready').flatMap(e=>e.actionList)
    .filter(a=>a.action==='NATIVE_EXECUTE_PLSQL_CODE'&&a.attribute01==='#P173_ID_AGENDAMENTO'&&required.every(id=>a.attribute02?.split(',').includes('#'+id)));
  if(actions.length!==1)throw Error('read_contract_changed');
  const action=actions[0], original=apex.item('P173_ID_AGENDAMENTO').getValue(), rows=[];
  try{
    for(const id of __IDS__){
      apex.item('P173_ID_AGENDAMENTO').setValue(id,null,true);
      const r=await apex.server.plugin(action.ajaxIdentifier,{pageItems:action.attribute01},{dataType:'json',timeout:10000});
      if(!Array.isArray(r.item)||required.some(id=>r.item.filter(x=>x.id===id).length!==1))throw Error('detail_incomplete');
      rows.push({id,fields:Object.fromEntries(r.item.filter(x=>required.includes(x.id)).map(x=>[x.id,x.value]))});
    }
  }finally{apex.item('P173_ID_AGENDAMENTO').setValue(original,null,true)}
  return rows;
})()"""


def normalize_openings(source, details, *, unit_id, professional_id, day):
    """Cross-check every dated calendar event against its native detail."""
    if (not isinstance(source, dict) or source.get('unit_id') != unit_id
            or not isinstance(source.get('events'), list) or not isinstance(details, list)
            or len(details) != len(source['events'])):
        raise NativeBookingError('opening_incomplete')
    step = source.get('step')
    if not isinstance(step, str) or not re.fullmatch(r'00:[0-5][0-9]:00', step):
        raise NativeBookingError('opening_grid_unverified')
    minutes = int(step[3:5])
    if minutes <= 0:
        raise NativeBookingError('opening_grid_unverified')
    indexed = {}
    for detail in details:
        if not isinstance(detail, dict) or detail.get('id') in indexed:
            raise NativeBookingError('opening_incomplete')
        indexed[detail.get('id')] = detail.get('fields')
    intervals, starts, seen = [], [], set()
    for event in source['events']:
        if not isinstance(event, dict):
            raise NativeBookingError('opening_incomplete')
        event_id = event.get('id')
        if (not isinstance(event_id, str) or not re.fullmatch(r'[1-9][0-9]*', event_id)
                or event_id in seen or event.get('all_day') is not False):
            raise NativeBookingError('opening_incomplete')
        seen.add(event_id)
        fields = indexed.get(event_id)
        if not isinstance(fields, dict):
            raise NativeBookingError('opening_incomplete')
        try:
            begin, end = zoned(event['start']).astimezone(SAO_PAULO), zoned(event['end']).astimezone(SAO_PAULO)
            detail_day = datetime.strptime(fields['P173_DT_BASE_INICIO'], '%d/%m/%Y').date()
            detail_start = datetime.strptime(fields['P173_DT_BASE_INICIO']+' '+fields['P173_TURNO_1_INI'], '%d/%m/%Y %H:%M').replace(tzinfo=SAO_PAULO)
            detail_end = datetime.strptime(fields['P173_DT_BASE_INICIO']+' '+fields['P173_TURNO_1_FIM'], '%d/%m/%Y %H:%M').replace(tzinfo=SAO_PAULO)
        except Exception:
            raise NativeBookingError('opening_detail_unverified') from None
        if (begin != detail_start or end != detail_end or end <= begin
                or begin.date() != day or end.date() != day or detail_day != day
                or not re.fullmatch(r'[1-9][0-9]*', str(fields.get('P173_PROFISSIONAL', '')))):
            raise NativeBookingError('opening_detail_unverified')
        if fields['P173_PROFISSIONAL'] != professional_id:
            continue
        # Restricted-duration openings need a separate duration contract.
        if fields.get('P173_DURACAO_LIVRE') != 'S':
            raise NativeBookingError('opening_duration_unverified')
        intervals.append(Interval(begin, end))
        at = begin
        while at < end:
            starts.append(at)
            at += timedelta(minutes=minutes)
    return tuple(intervals), tuple(sorted(set(starts)))


def read_snapshot(browser, config, request):
    """Read only the requested day; absence of bookings never invents openings."""
    port = ProntuarioVerdeHermesPort(browser, config)
    port._check_scope(request)
    unit, professional = str(request['unit_id']), str(request['professional_id'])
    if not all(re.fullmatch(r'[1-9][0-9]*', value) for value in (unit, professional)):
        raise NativeBookingError('opening_scope_invalid')
    day_start = zoned(request['requested_start']).astimezone(SAO_PAULO).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    browser.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Configurações').click();true")
    port._wait("Array.from(document.querySelectorAll('a')).some(e=>e.textContent.trim()==='Abertura de agenda')")
    browser.evaluate("Array.from(document.querySelectorAll('a')).find(e=>e.textContent.trim()==='Abertura de agenda').click();true")
    port._wait("!!document.querySelector('#B569175643209798813')")
    browser.evaluate("document.querySelector('#B569175643209798813').click();true")
    port._wait("typeof window.jQuery==='function' && !!jQuery('#regdesk_calendar').data('fullCalendar')")
    port._set_select('P172_UNIDADE', unit)
    port._wait("jQuery.active===0")
    browser.evaluate("$('#regdesk_calendar').data('fullCalendar').gotoDate("+json.dumps(day_start.date().isoformat())+");true")
    observed_at = datetime.now(timezone.utc)
    source = port._wait(READ_OPENINGS.replace('__DAY__', json.dumps(day_start.isoformat())).replace('__UNIT__', json.dumps(unit)))
    details = []
    if source.get('events'):
        ids = [event.get('id') for event in source['events'] if isinstance(event, dict)]
        if len(ids) != len(source['events']) or not all(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) for value in ids):
            raise NativeBookingError('opening_incomplete')
        browser.evaluate("(()=>{const c=$('#regdesk_calendar').data('fullCalendar');const e=c.getEvents().find(e=>String(e.id)==="+json.dumps(ids[0])+");if(!e)throw Error('opening_changed');c.getOption('eventClick')({event:e,el:document.querySelector('.fc-event'),jsEvent:{preventDefault(){}}});return true})()")
        port._wait(DETAIL_READY.replace('__UNIT__', json.dumps(unit)))
        details = port._eval(READ_DETAILS.replace('__IDS__', json.dumps(ids)).replace('__UNIT__', json.dumps(unit)))
    openings, starts = normalize_openings(source, details, unit_id=unit, professional_id=professional, day=day_start.date())
    browser.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda').click();true")
    port._wait("typeof calendar!=='undefined' && !!document.querySelector('#P41_PROFISSIONAL')")
    select_calendar_scope(browser, professional, unit)
    events = read_calendar_events(browser, config, day_start, day_end, professional_id=professional, unit_id=unit)['events']
    blocking = []
    for event in events:
        if str(event.get('status') or '').upper() in {'CANCELOU', 'CANCELADO', 'CANCELADA', 'REMARCADO', 'REMARCADA'}:
            continue
        if request.get('operation') == 'reschedule' and event['id'] == str(request.get('appointment_id')):
            if zoned(event['start']) != zoned(request['expected_start']) or zoned(event['end']) != zoned(request['expected_end']):
                raise NativeBookingError('original_appointment_changed')
            continue
        blocking.append(Interval(zoned(event['start']), zoned(event['end'])))
    port._check_scope(request)
    return OpeningSnapshot(request['source_clinic_hash'], professional, unit, day_start.date(),
                           observed_at, openings, tuple(blocking), starts, True)
