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
# Only administrative fields leave the browser; titles, names and phones are discarded.
READ_SCRIPT = r"""(async () => {
  const sources = calendar.getEventSources();
  if (sources.length !== 1) throw Error('source_changed');
  const m = sources[0].internalEventSource.meta;
  if (m.url !== 'https://app.prontuarioverde.com.br/ords/prontuario/agendaProfissional/buscar' ||
      m.method !== 'POST' || m.extraParams.profissional_id !== '' || m.extraParams.unidade_id !== '')
    throw Error('source_changed');
  const response = await fetch(m.url, {
    method: 'POST', signal: AbortSignal.timeout(20000),
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({...m.extraParams, start: __START__, end: __END__})
  });
  if (!response.ok) throw Error('schedule_fetch_failed');
  const events = await response.json();
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
        appointments.append(dict(id=event_id, patient_id=patient_id, professional_id=professional_id,
            professional_name=professionals[professional_id], start=begin.isoformat(), end=finish.isoformat(),
            status=status.lower()))
    return dict(schema_version=1, source='prontuario_verde', clinic_id=config['clinic_id'],
        source_clinic_hash=config['source_clinic_hash'], complete=True, generated_at=now.isoformat(),
        coverage_start=start.isoformat(), coverage_end=end.isoformat(),
        appointments=appointments, skipped_events=skipped)


def refresh_schedule(browser, config, directory_path=Path('/opt/data/patient_directory.json'), target=SCHEDULE_PATH):
    if browser.source_clinic_hash != config['source_clinic_hash']:
        raise SyncError('clinic_mismatch')
    directory = json.loads(Path(directory_path).read_text())
    today = datetime.now(SAO_PAULO).replace(hour=0, minute=0, second=0, microsecond=0)
    end = today + timedelta(days=366)
    browser.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Agenda').click();true")
    browser.command('wait', ['#P41_PROFISSIONAL'])
    browser.evaluate("apex.item('P41_PROFISSIONAL').setValue('');apex.item('P41_UNIDADE_FILTRO').setValue('');true")
    browser.command('wait', ['2000'])
    data = browser.evaluate(READ_SCRIPT.replace('__START__', json.dumps(today.isoformat())).replace('__END__', json.dumps(end.isoformat())))
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
