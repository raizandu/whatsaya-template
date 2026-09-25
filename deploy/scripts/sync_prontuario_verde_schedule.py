"""Read the calendar's own data source into a minimal, clinic-bound schedule cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from sync_prontuario_verde import SyncError, write_snapshot

SAO_PAULO = ZoneInfo('America/Sao_Paulo')
SCHEDULE_PATH = Path('/opt/data/prontuario_verde_schedule.json')

# Parameters come from the authenticated calendar, including its temporary checksum.
# Only administrative fields leave the browser; raw titles, phones and procedures are discarded.
# Patient labels are used by the authenticated staff agenda, never by the bot prompt.
READ_SCRIPT = r"""(async () => {
  const sources = calendar.getEventSources();
  if (sources.length !== 1) throw Error('source_changed');
  const source = sources[0].internalEventSource;
  const m = source.meta;
  const parameters = JSON.stringify(m.extraParams);
  const scopeMatches = () => String(apex.item('P41_PROFISSIONAL').getValue()) === __PROFESSIONAL__ &&
    String(apex.item('P41_UNIDADE_FILTRO').getValue()) === __UNIT__ &&
    m.extraParams.profissional_id === __PROFESSIONAL__ && m.extraParams.unidade_id === __UNIT__;
  if (!scopeMatches()) throw Error('source_scope_changed');
  if (m.url !== 'https://app.prontuarioverde.com.br/ords/prontuario/agendaProfissional/buscar' ||
      m.method !== 'POST')
    throw Error('source_changed');
  const response = await fetch(m.url, {
    method: 'POST', signal: AbortSignal.timeout(20000),
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({...m.extraParams, start: __START__, end: __END__})
  });
  if (!response.ok) throw Error('schedule_fetch_failed');
  const events = await response.json();
  const current = calendar.getEventSources();
  if (current.length !== 1 || current[0].internalEventSource !== source ||
      !scopeMatches() || JSON.stringify(m.extraParams) !== parameters)
    throw Error('source_scope_changed');
  if (!Array.isArray(events) || events.length > 10000) throw Error('schedule_limit');
  return {
    professionals: Array.from(document.querySelector('#P41_PROFISSIONAL').options)
      .filter(o => /^[1-9][0-9]*$/.test(o.value)).map(o => ({id: o.value, name: o.text.trim()})),
    events: events.map(e => {
      const holder = document.createElement('div'); holder.innerHTML = e.title || '';
      const detail = document.createElement('div');
      detail.innerHTML = (holder.querySelector('[title]')?.getAttribute('title') || e.title || '').replace(/<br\s*\/?>/gi, '\n');
      const text = detail.textContent;
      return {id: String(e.id), professional_id: String(e.resourceId), start: e.start, end: e.end,
        record_number: /\(([1-9][0-9]*)\)\s*$/.exec(text.split('\n')[0])?.[1] || null,
        ...(__INCLUDE_LABELS__ ? {patient_name: text.split('\n')[0].replace(/\([1-9][0-9]*\)\s*$/, '').trim()} : {}),
        status: /SITUA[ÇC][ÃÂA]O:\s*([^\n]+)/i.exec(text)?.[1]?.trim() || null};
    })
  };
})()"""


def zoned(value):
    if not isinstance(value, str):
        raise SyncError('schedule_timestamp_invalid')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise SyncError('schedule_timestamp_invalid') from None
    if parsed.tzinfo is None:
        raise SyncError('schedule_timezone_missing')
    return parsed



def select_calendar_scope(browser, professional_id='', unit_id=''):
    """Apply native filters in dependency order, then await their signed source."""
    for value in (professional_id, unit_id):
        if not isinstance(value, str) or (value and not re.fullmatch(r'[1-9][0-9]*', value)):
            raise SyncError('schedule_scope_invalid')
    script = r"""(async()=>{
      const professional=__PROFESSIONAL__,unit=__UNIT__;
      const deadline=Date.now()+15000;
      const wait=async(test)=>{while(!test()){if(Date.now()>deadline)throw Error('scope_timeout');await new Promise(r=>setTimeout(r,100))}};
      const select=(id,value)=>{const e=document.getElementById(id);if(!e||!Array.from(e.options).some(o=>o.value===value))throw Error('filter_changed');apex.item(id).setValue(value)};
      select('P41_UNIDADE_FILTRO',unit);
      await wait(()=>jQuery.active===0);
      select('P41_PROFISSIONAL',professional);
      await wait(()=>{const s=calendar.getEventSources();return jQuery.active===0&&s.length===1&&
        s[0].internalEventSource.meta.extraParams.profissional_id===professional&&
        s[0].internalEventSource.meta.extraParams.unidade_id===unit&&
        String(apex.item('P41_PROFISSIONAL').getValue())===professional&&
        String(apex.item('P41_UNIDADE_FILTRO').getValue())===unit});
      return true;
    })()"""
    script = script.replace('__PROFESSIONAL__', json.dumps(professional_id)).replace('__UNIT__', json.dumps(unit_id))
    try:
        if browser.evaluate(script) is not True:
            raise SyncError('schedule_scope_unverified')
    except Exception:
        raise SyncError('schedule_scope_unverified') from None


def read_calendar_events(browser, config, start, end, *, professional_id='', unit_id='', include_labels=False):
    """Read the current native scope without rewriting signed source parameters.

    The caller selects filters through APEX and waits for its source to settle.
    All statuses are retained: this read is useful for blockers as well as the
    staff schedule, whose later projection deliberately hides inactive rows.
    No opening or duplicate completeness is inferred from an empty result.
    """
    if (not isinstance(config, dict) or not config.get('source_clinic_hash')
            or browser.source_clinic_hash != config['source_clinic_hash']):
        raise SyncError('clinic_mismatch')
    for value in (professional_id, unit_id):
        if not isinstance(value, str) or (value and not re.fullmatch(r'[1-9][0-9]*', value)):
            raise SyncError('schedule_scope_invalid')
    if (not isinstance(start, datetime) or not isinstance(end, datetime)
            or start.tzinfo is None or end.tzinfo is None
            or not timedelta(0) < end - start <= timedelta(days=366)):
        raise SyncError('schedule_window_invalid')
    script = READ_SCRIPT
    for token, value in (('__START__', start.isoformat()), ('__END__', end.isoformat()),
                         ('__PROFESSIONAL__', professional_id), ('__UNIT__', unit_id),
                         ('__INCLUDE_LABELS__', include_labels is True)):
        script = script.replace(token, json.dumps(value))
    try:
        data = browser.evaluate(script)
    except Exception:
        raise SyncError('schedule_read_failed') from None
    if (not isinstance(data, dict) or not isinstance(data.get('events'), list)
            or not isinstance(data.get('professionals'), list)):
        raise SyncError('schedule_shape_changed')
    seen = set()
    for event in data['events']:
        if not isinstance(event, dict):
            raise SyncError('schedule_shape_changed')
        event_id, professional = event.get('id'), event.get('professional_id')
        if (not isinstance(event_id, str) or not re.fullmatch(r'[1-9][0-9]*', event_id)
                or event_id in seen or not isinstance(professional, str)
                or not re.fullmatch(r'[1-9][0-9]*', professional)
                or (professional_id and professional != professional_id)):
            raise SyncError('schedule_scope_changed')
        seen.add(event_id)
        begin, finish = zoned(event.get('start')), zoned(event.get('end'))
        if finish <= begin or begin >= end or finish <= start:
            raise SyncError('appointment_window_invalid')
    if browser.source_clinic_hash != config['source_clinic_hash']:
        raise SyncError('clinic_mismatch')
    return data


def build_snapshot(data, directory, config, start, end, now=None):
    now = now or datetime.now(timezone.utc)
    if (directory.get('source') != 'prontuario_verde' or directory.get('complete') is not True
            or directory.get('clinic_id') != config['clinic_id']
            or directory.get('source_clinic_hash') != config['source_clinic_hash']
            or not timedelta(0) <= now - zoned(directory.get('generated_at')) <= timedelta(hours=24)):
        raise SyncError('patient_directory_unavailable')
    codes = {}
    for patient in directory.get('patients', []):
        code, patient_id = patient.get('record_number'), patient.get('id')
        if not code:
            continue
        if (not isinstance(code, str) or not re.fullmatch(r'[1-9][0-9]*', code)
                or not isinstance(patient_id, str) or not re.fullmatch(r'[1-9][0-9]*', patient_id)
                or code in codes):
            raise SyncError('patient_code_invalid')
        codes[code] = patient_id
    if not codes:
        raise SyncError('patient_codes_missing')
    professionals = {p['id']: p['name'] for p in data['professionals']}
    if not professionals or any(not re.fullmatch(r'[1-9][0-9]*', p) or not name.strip() for p, name in professionals.items()):
        raise SyncError('professionals_invalid')
    appointments, seen, skipped = [], set(), 0
    for event in data['events']:
        event_id = event.get('id')
        if not isinstance(event_id, str) or not re.fullmatch(r'[1-9][0-9]*', event_id) or event_id in seen:
            raise SyncError('appointment_id_invalid')
        seen.add(event_id)
        status = str(event.get('status') or '').strip().upper()
        if status not in ('AGENDADO', 'CONFIRMADO'):
            skipped += 1
            continue
        patient_id = codes.get(event.get('record_number'))
        if not patient_id:
            skipped += 1
            continue
        professional_id = event.get('professional_id')
        begin, finish = zoned(event.get('start')), zoned(event.get('end'))
        if professional_id not in professionals or finish <= begin or not start <= begin < end:
            raise SyncError('appointment_window_invalid')
        row = dict(id=event_id, patient_id=patient_id, record_number=event['record_number'],
            professional_id=professional_id, professional_name=professionals[professional_id],
            start=begin.isoformat(), end=finish.isoformat(), status=status.lower())
        name = event.get('patient_name')
        if name is not None:
            if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name):
                raise SyncError('patient_label_invalid')
            row['patient_name'] = name.strip()
        appointments.append(row)
    return dict(schema_version=1, source='prontuario_verde', clinic_id=config['clinic_id'],
        source_clinic_hash=config['source_clinic_hash'], complete=True, generated_at=now.isoformat(),
        coverage_start=start.isoformat(), coverage_end=end.isoformat(),
        appointments=appointments, skipped_events=skipped,
        professionals=[{'id': key, 'name': value} for key, value in professionals.items()])


def refresh_schedule(browser, config, directory_path=Path('/opt/data/patient_directory.json'), target=SCHEDULE_PATH):
    if browser.source_clinic_hash != config['source_clinic_hash']:
        raise SyncError('clinic_mismatch')
    directory = json.loads(Path(directory_path).read_text())
    today = datetime.now(SAO_PAULO).replace(hour=0, minute=0, second=0, microsecond=0)
    end = today + timedelta(days=366)
    browser.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda').click();true")
    browser.command('wait', ['#P41_PROFISSIONAL'])
    select_calendar_scope(browser)
    data = read_calendar_events(browser, config, today, end, include_labels=True)
    snapshot = build_snapshot(data, directory, config, today, end)
    write_snapshot(Path(target), snapshot)
    return {'appointments': len(snapshot['appointments']), 'skipped_events': snapshot['skipped_events']}


def invalidate_cancelled(request, path=SCHEDULE_PATH):
    """Update only the affected appointment; do not pretend the rest was refreshed."""
    path = Path(path)
    if not path.exists():
        return
    snapshot = json.loads(path.read_text())
    if snapshot.get('clinic_id') != request['clinic_id'] or snapshot.get('source_clinic_hash') != request['source_clinic_hash']:
        return
    snapshot['appointments'] = [a for a in snapshot.get('appointments', []) if a['id'] != request['appointment_id']]
    write_snapshot(path, snapshot)
