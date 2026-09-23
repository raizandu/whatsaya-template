#!/usr/bin/env python3
"""Read the authorized patient list into a private, minimal local directory.

Runs inside Hermes using its local browser tools. No clinical records are opened.
An interrupted or filtered scan never replaces the previous directory.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class SyncError(Exception):
    """Only fixed, non-sensitive error codes may cross the CLI boundary."""


PAGE_SCRIPT = r"""(() => {
  const table = document.querySelector('#report_table_resultadoPesquisaPaciente');
  if (!table || document.title.trim() !== 'Pacientes') throw new Error('patient_page_missing');
  const rows = Array.from(table.rows).filter(r => r.querySelector('td'));
  const facets = document.querySelector('#R84306549000232539_fr');
  if (!facets || !facets.querySelector('input')) throw new Error('filters_missing');
  const next = Array.from(document.querySelectorAll('a')).find(e => e.textContent.trim() === 'Próximo');
  const technical = new Set(['P13_STATIC_TRIAL', 'P13_WHATSCOMMENSAGEM', 'P13_PAGINA_CONTRATE_WHATSAPP', 'P13_PAGINA_CONTRATE_PLANO']);
  const filters = Array.from(document.querySelectorAll('input[id^=P13_],select[id^=P13_]'))
    .filter(e => !technical.has(e.id) && !(e.id === 'P13_PRORC' && e.value === 'N'))
    .filter(e => e.value.trim() !== '').map(e => e.id);
  filters.push(...Array.from(facets.querySelectorAll('input,select'))
    .filter(e => ['radio','checkbox'].includes(e.type) ? e.checked : e.type !== 'hidden' && e.value.trim() !== '')
    .map(e => e.id));
  if (rows.some(r => !r.querySelector('td[headers=TELEFONES]') || !r.querySelector('td[headers=MENU_OPCOES] a'))) throw new Error('patient_columns_missing');
  return {
    rows: rows.map(r => ({id: (r.querySelector('td[headers=MENU_OPCOES] a').getAttribute('href') || '').match(/\bpac_id['"]?\s*:\s*['"]?(\d+)/)?.[1] || '',
                         appointment_id: (r.querySelector('td[headers=MENU_OPCOES] a').getAttribute('href') || '').match(/\bage_id['"]?\s*:\s*['"]?(\d+)/)?.[1] || '',
                         phone_text: r.querySelector('td[headers=TELEFONES]').innerText})),
    has_next: !!next,
    active_filters: filters,
    header: document.querySelector('.t-Header')?.innerText || '',
    total_label: document.querySelector('.a-FS-totalCount')?.textContent || ''
  };
})()"""

NEXT_SCRIPT = r"""(async () => {
  const codes = () => Array.from(document.querySelectorAll('#report_table_resultadoPesquisaPaciente td[headers=MENU_OPCOES] a')).map(e=>{const h=e.getAttribute('href') || ''; return (h.match(/\bpac_id['"]?\s*:\s*['"]?(\d+)/)?.[1] || '') + ':' + (h.match(/\bage_id['"]?\s*:\s*['"]?(\d+)/)?.[1] || '');}).join('|');
  const before = codes();
  const next = Array.from(document.querySelectorAll('a')).find(e => e.textContent.trim() === 'Próximo');
  if (!next) throw new Error('next_page_missing');
  next.click();
  const end = Date.now() + 20000;
  while (Date.now() < end) {
    await new Promise(resolve => setTimeout(resolve, 200));
    if (codes() && codes() !== before) return true;
  }
  throw new Error('pagination_timeout');
})()"""


def extract_phones(text: str) -> list[str]:
    from patient_directory import normalize_phone

    if not isinstance(text, str):
        raise SyncError('invalid_phone_cell')
    values = re.findall(r'(?<!\d)(?:\+?55[ .-]*)?\(?[1-9]\d\)?[ .-]*\d{4,5}[ .-]*\d{4}(?!\d)', text)
    return sorted({phone for value in values if (phone := normalize_phone(value))})


def collect_pages(browser, clinic_id: str, expected_clinic_name: str, max_pages: int = 1000, on_progress=None, source_clinic_hash=None) -> dict:
    patients = []
    seen = set()
    unlinked_appointments = set()
    expected = ' '.join(expected_clinic_name.upper().split())
    if not expected or not clinic_id:
        raise SyncError('clinic_config_missing')
    if not isinstance(source_clinic_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', source_clinic_hash):
        raise SyncError('source_clinic_binding_missing')
    if browser.source_clinic_hash != source_clinic_hash:
        raise SyncError('source_clinic_mismatch')
    for page_number in range(max_pages):
        page = browser.evaluate(PAGE_SCRIPT)
        if not isinstance(page, dict) or not isinstance(page.get('rows'), list):
            raise SyncError('invalid_patient_page')
        header_lines = [' '.join(line.upper().split()) for line in str(page.get('header', '')).splitlines()]
        if expected not in header_lines:
            raise SyncError('clinic_mismatch')
        if page.get('active_filters') != []:
            raise SyncError('patient_filters_active')
        if not page['rows']:
            raise SyncError('empty_patient_page')
        for row in page['rows']:
            patient_id = row.get('id') if isinstance(row, dict) else None
            if patient_id == '' and isinstance(row.get('appointment_id'), str) and re.fullmatch(r'[0-9]+', row['appointment_id']):
                if row['appointment_id'] in unlinked_appointments:
                    raise SyncError('duplicate_or_changed_pagination')
                # The UI also lists appointment rows without a patient ID. They
                # cannot establish patient registration and are counted only.
                extract_phones(row.get('phone_text'))
                unlinked_appointments.add(row['appointment_id'])
                continue
            if not isinstance(patient_id, str) or not patient_id.strip() or len(patient_id) > 100:
                raise SyncError('invalid_patient_id')
            if patient_id in seen:
                raise SyncError('duplicate_or_changed_pagination')
            seen.add(patient_id)
            patients.append({'id': patient_id, 'phones': extract_phones(row.get('phone_text'))})
        if on_progress and (page_number + 1) % 10 == 0:
            on_progress(page_number + 1, len(patients))
        if page.get('has_next') is False:
            return {
                'schema_version': 1, 'source': 'prontuario_verde', 'clinic_id': clinic_id,
                'source_clinic_hash': source_clinic_hash,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'complete': True, 'patients': patients,
                'unlinked_appointment_rows': len(unlinked_appointments),
            }
        if page.get('has_next') is not True:
            raise SyncError('invalid_pagination_state')
        browser.evaluate(NEXT_SCRIPT)
    raise SyncError('pagination_limit')


def write_snapshot(path: Path, snapshot: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(snapshot, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def sync_lock(path: Path):
    with path.open('a') as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError('sync_already_running') from None
        yield


class HermesBrowser:
    def __init__(self):
        from tools import browser_tool
        self.tools = browser_tool
        self.task = 'pv-patient-sync-' + uuid.uuid4().hex
        self.source_clinic_hash = None
        if self.tools._cloud._get_cloud_provider() is not None:
            raise SyncError('local_browser_required')

    def command(self, name: str, args: list[str]):
        result = self.tools._session._run_browser_command(self.task, name, args)
        if not result.get('success'):
            raise SyncError('browser_' + name + '_failed')
        return result.get('data', {})

    def evaluate(self, expression: str):
        return self.command('eval', [expression]).get('result')

    def login(self, credentials: dict, *, open_patients: bool = True):
        url = credentials.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'app.prontuarioverde.com.br' or parsed.username or parsed.password:
            raise SyncError('invalid_login_origin')
        if not all(isinstance(credentials.get(k), str) and credentials[k] for k in ('email', 'password')):
            raise SyncError('credentials_missing')
        result = json.loads(self.tools.browser_navigate(url, task_id=self.task))
        if not result.get('success'):
            raise SyncError('login_navigation_failed')
        snapshot = result.get('snapshot', '')
        for label, key in [('Email', 'email'), ('Senha', 'password')]:
            match = re.search(r'textbox "' + label + r'" \[ref=([^\]]+)\]', snapshot)
            if not match:
                raise SyncError('login_form_changed')
            typed = json.loads(self.tools.browser_type(match.group(1), credentials[key], task_id=self.task))
            if not typed.get('success'):
                raise SyncError('login_fill_failed')
        match = re.search(r'button "ACESSAR CONTA" \[ref=([^\]]+)\]', snapshot)
        if not match:
            raise SyncError('login_form_changed')
        self.tools.browser_click(match.group(1), task_id=self.task)
        self.command('wait', ['a[role=treeitem]'])
        self.read_clinic_identity()
        if open_patients:
            self.evaluate("Array.from(document.querySelectorAll('a[role=treeitem]')).find(e=>e.textContent.trim()==='Pacientes').click()")
            self.command('wait', ['#report_table_resultadoPesquisaPaciente'])

    def read_clinic_identity(self):
        cookies = self.command('cookies', ['get']).get('cookies', [])
        tokens = [c.get('value', '') for c in cookies
                  if c.get('name') == 'token' and c.get('domain', '').lstrip('.') == 'prontuarioverde.com.br']
        if len(tokens) != 1:
            raise SyncError('source_clinic_identity_missing')
        try:
            part = tokens[0].split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
            source_id = str(claims['cli_id'])
        except (KeyError, IndexError, ValueError, TypeError):
            raise SyncError('source_clinic_identity_invalid') from None
        if not re.fullmatch(r'[0-9]+', source_id):
            raise SyncError('source_clinic_identity_invalid')
        # Identity was supplied by the authenticated HTTPS login. This is not a
        # standalone JWT signature verifier, nor is the token reused as an API bearer.
        self.source_clinic_hash = hashlib.sha256(('prontuario_verde:cli_id:' + source_id).encode()).hexdigest()

    def refresh_authenticated(self):
        """Refresh from the server before trusting a retained session (never a cached DOM)."""
        url = self.evaluate('location.href')
        parsed = urlsplit(url or '')
        if parsed.scheme != 'https' or parsed.hostname != 'app.prontuarioverde.com.br':
            return False
        result = json.loads(self.tools.browser_navigate(url, task_id=self.task))
        if not result.get('success'):
            return False
        authenticated = self.evaluate("location.hostname==='app.prontuarioverde.com.br' && !!document.querySelector('a[role=treeitem]') && !document.querySelector('input[type=password]')")
        if not authenticated:
            return False
        self.read_clinic_identity()
        return True

    def close(self):
        try:
            self.tools._session._run_browser_command(self.task, 'close', [])
        except Exception:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('/opt/data'))
    parser.add_argument('--max-pages', type=int, default=1000)
    parser.add_argument('--inspect', action='store_true', help='Only report non-sensitive page metadata; do not write a snapshot.')
    args = parser.parse_args(argv)
    os.umask(0o077)
    browser = None
    try:
        cfg = json.loads((args.data_dir / 'panel.config.json').read_text()).get('patient_directory', {})
        if not isinstance(cfg, dict) or not cfg.get('clinic_id') or not cfg.get('expected_clinic_name'):
            raise SyncError('clinic_config_missing')
        credential_path = args.data_dir / '.hermes/secrets/prontuario-verde.json'
        if credential_path.stat().st_mode & 0o077:
            raise SyncError('credential_permissions')
        with sync_lock(args.data_dir / '.patient-directory-sync.lock'):
            credentials = json.loads(credential_path.read_text())
            browser = HermesBrowser()
            browser.login(credentials)
            if args.inspect:
                page = browser.evaluate(PAGE_SCRIPT)
                print(json.dumps({'rows': len(page['rows']), 'has_next': page['has_next'],
                                  'header': page['header'], 'active_filters': page['active_filters'],
                                  'total_label': page['total_label'], 'source_clinic_hash': browser.source_clinic_hash}))
                return 0
            snapshot = collect_pages(
                browser, cfg['clinic_id'], cfg['expected_clinic_name'], args.max_pages,
                on_progress=lambda pages, patients: print(json.dumps({'pages_read': pages, 'patients_read': patients}), flush=True),
                source_clinic_hash=cfg.get('source_clinic_hash'),
            )
            write_snapshot(args.data_dir / 'patient_directory.json', snapshot)
            counts = {}
            for patient in snapshot['patients']:
                for phone in patient['phones']:
                    counts[phone] = counts.get(phone, 0) + 1
            print(json.dumps({'ok': True, 'patients': len(snapshot['patients']), 'phones': len(counts),
                              'unlinked_appointment_rows': snapshot['unlinked_appointment_rows'],
                              'shared_phones': sum(n > 1 for n in counts.values()), 'complete': True}))
            return 0
    except SyncError as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        return 1
    except Exception:
        print(json.dumps({'ok': False, 'error': 'sync_failed'}))
        return 1
    finally:
        if browser is not None:
            browser.close()


if __name__ == '__main__':
    raise SystemExit(main())
