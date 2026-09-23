#!/usr/bin/env python3
"""Process administrator cancellation requests using the local Hermes browser."""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'panel'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prontuario_verde_actions as queue
from panel import data as panel_data
from sync_prontuario_verde import HermesBrowser

DATA = Path('/opt/data')
SPOOL = DATA / 'prontuario_verde_actions'
CONFIG = DATA / 'panel.config.json'
CREDENTIALS = DATA / '.hermes/secrets/prontuario-verde.json'
SAO_PAULO = ZoneInfo('America/Sao_Paulo')


class CancelError(Exception):
    pass


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
    return str(event.get('status', '')).upper().startswith('CANCELAD')


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


def process(request, root=SPOOL):
    browser = None
    adapter = None
    try:
        current_request(request)
        browser = HermesBrowser()
        browser.login(json.loads(CREDENTIALS.read_text()))
        if browser.source_clinic_hash != request['source_clinic_hash']:
            raise CancelError('clinic_mismatch')
        adapter = CancellationBrowser(browser)
        adapter.cancel(request, lambda: current_request(request))
        record_cancelled(request)
        queue.finish(root, request['request_id'], 'succeeded', 'cancelled')
    except Exception as exc:
        code = str(exc) if isinstance(exc, CancelError) else 'browser_unavailable'
        state = 'needs_review' if adapter and adapter.submitted else 'failed'
        queue.finish(root, request['request_id'], state, code)
    finally:
        if browser:
            browser.close()


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
        while True:
            request = queue.claim_next(SPOOL)
            if request:
                process(request)
            if args.once:
                return
            time.sleep(2)


if __name__ == '__main__':
    main()
