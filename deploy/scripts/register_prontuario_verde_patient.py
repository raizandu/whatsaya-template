#!/usr/bin/env python3
"""Operator-invoked, idempotent patient registration through the native PV form.

Reads a private request file containing confirmed name and phone. This command
is not a WhatsApp first-contact hook and never sends messages or books visits.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import re
import sys

from sync_prontuario_verde import (HermesBrowser, SyncError, PAGE_SCRIPT,
                                    collect_pages, extract_phones, sync_lock, write_snapshot)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from patient_directory import normalize_phone
from prontuario_verde_registration import RegistrationError, ensure_patient


class RegistrationBrowser:
    def __init__(self, browser, config, directory_path):
        self.browser = browser
        self.config = config
        self.directory_path = Path(directory_path)
        self.source_clinic_hash = browser.source_clinic_hash
        self.phone = self.name = None
        self.names = {}
        self.name_candidates = set()

    def open_patients(self):
        # Follow the actual navigation target; do not synthesize APEX checksums.
        href = self.browser.evaluate("[...document.querySelectorAll('a[role=treeitem]')].find(e=>e.textContent.trim()==='Pacientes')?.href")
        if not isinstance(href, str) or not href.startswith('https://app.prontuarioverde.com.br/ords/'):
            raise SyncError('patient_navigation_changed')
        result = json.loads(self.browser.tools.browser_navigate(href, task_id=self.browser.task))
        if not result.get('success'):
            raise SyncError('patient_navigation_failed')
        self.browser.command('wait', ['#report_table_resultadoPesquisaPaciente'])
        self.browser.read_clinic_identity()
        if self.browser.source_clinic_hash != self.config['source_clinic_hash']:
            raise SyncError('source_clinic_mismatch')

    def evaluate(self, expression):
        page = self.browser.evaluate(expression)
        if expression != PAGE_SCRIPT:
            return page
        phone_ids = [row['id'] for row in page['rows']
                     if row.get('id') and self.phone in extract_phones(row['phone_text'])]
        # Other patients' names stay in the browser. Only exact candidate IDs and
        # the name of the requested phone's record cross this boundary.
        details = self.browser.evaluate(r"""(() => {
          const ids = __IDS__, wanted = __NAME__;
          const norm = s => s.normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase();
          const rows = [...document.querySelectorAll('#report_table_resultadoPesquisaPaciente tr')].filter(r=>r.querySelector('td[headers=MENU_OPCOES] a'));
          const names = {}, candidates = [];
          for (const row of rows) {
            const id = (row.querySelector('td[headers=MENU_OPCOES] a').getAttribute('href') || '').match(/\bpac_id['"]?\s*:\s*['"]?(\d+)/)?.[1];
            if (!id) continue;
            const cell = row.querySelector('td[headers=NOME]');
            if (!cell) throw Error('patient_name_column_changed');
            const name = cell.innerText.trim();
            if (ids.includes(id)) names[id] = name;
            if (norm(name) === norm(wanted)) candidates.push(id);
          }
          return {names, candidates};
        })()""".replace('__IDS__', json.dumps(phone_ids)).replace('__NAME__', json.dumps(self.name)))
        self.names.update(details['names'])
        self.name_candidates.update(details['candidates'])
        return page

    def lookup(self, phone, name):
        self.phone, self.name = phone, name
        self.names, self.name_candidates = {}, set()
        self.open_patients()
        snapshot = collect_pages(self, self.config['clinic_id'], self.config['expected_clinic_name'],
                                 source_clinic_hash=self.config['source_clinic_hash'],
                                 on_progress=lambda pages, patients: print(json.dumps({'registration_stage':'checking_directory','pages':pages}), flush=True))
        write_snapshot(self.directory_path, snapshot)
        matches = [{**row, 'name': self.names.get(row['id'], '')}
                   for row in snapshot['patients'] if phone in row['phones']]
        print(json.dumps({'registration_stage':'lookup_completed', 'matches':len(matches), 'name_candidates':len(self.name_candidates)}), flush=True)
        return {'matches': matches, 'name_candidates': len(self.name_candidates)}

    def create(self, name, phone, before_submit):
        self.browser.evaluate("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Criar novo paciente');if(!b)throw Error('create_button_missing');b.click();return true})()")
        self.browser.command('wait', ['#P26_NOME_REGISTRO'])
        self.browser.read_clinic_identity()
        if self.browser.source_clinic_hash != self.config['source_clinic_hash']:
            raise SyncError('source_clinic_mismatch')
        if self.browser.evaluate("document.querySelector('#P26_ID')?.value || ''"):
            raise SyncError('existing_patient_form')
        self.browser.command('fill', ['#P26_NOME_REGISTRO', name])
        self.browser.command('fill', ['#P26_TELEFONE_CELULAR_FULL', '+' + phone])
        self.browser.command('press', ['Tab'])
        self.browser.evaluate("(()=>{for(const id of ['P26_RECEBER_COMUNICACAO_RECHAMADA','P26_RECEBER_COMUNICACAO_MARKETING','P26_RECEBER_COMUNICACAO_CRM']){const e=document.getElementById(id);if(!e)throw Error('communication_fields_changed');if(e.checked)e.click();}return true})()")
        values = self.browser.evaluate("({name:document.querySelector('#P26_NOME_REGISTRO').value,phone:document.querySelector('#P26_TELEFONE_CELULAR').value,communications:['P26_RECEBER_COMUNICACAO_RECHAMADA','P26_RECEBER_COMUNICACAO_MARKETING','P26_RECEBER_COMUNICACAO_CRM'].some(id=>document.getElementById(id).checked)})")
        if values['name'] != name or normalize_phone(values['phone']) != phone or values['communications']:
            raise SyncError('form_values_unverified')
        before_submit()
        self.browser.evaluate("(()=>{const b=[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='Criar novo paciente');if(!b)throw Error('save_button_missing');b.click();return true})()")
        result = self.browser.evaluate(r"""(async () => {
          const until=Date.now()+25000;
          while(Date.now()<until){
            const id=document.querySelector('#P4_PAC_ID')?.value || document.querySelector('#P26_ID')?.value;
            if(id && /^[1-9][0-9]*$/.test(id))return id;
            if(document.querySelector('.a-Notification--error,.t-Alert--danger'))return null;
            await new Promise(r=>setTimeout(r,250));
          }
          return null;
        })()""")
        if not isinstance(result, str) or not re.fullmatch(r'[1-9][0-9]*', result):
            raise SyncError('save_result_unverified')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=Path('/opt/data'))
    args = parser.parse_args(argv)
    logging.getLogger('hermes_cli.auth').setLevel(logging.CRITICAL)
    os.umask(0o077)
    browser = None
    try:
        if args.request_file.stat().st_mode & 0o077:
            raise SyncError('request_permissions')
        request = json.loads(args.request_file.read_text())
        if set(request) != {'name', 'phone', 'identity_confirmed'} or request['identity_confirmed'] is not True:
            raise SyncError('identity_not_confirmed')
        config = json.loads((args.data_dir / 'panel.config.json').read_text())['patient_directory']
        if config.get('enabled') is not True:
            raise SyncError('directory_disabled')
        secret = args.data_dir / '.hermes/secrets/prontuario-verde.json'
        if secret.stat().st_mode & 0o077:
            raise SyncError('credential_permissions')
        with sync_lock(args.data_dir / '.patient-directory-sync.lock'):
            browser = HermesBrowser()
            browser.login(json.loads(secret.read_text()))
            adapter = RegistrationBrowser(browser, config, args.data_dir / 'patient_directory.json')
            result = ensure_patient(adapter, name=request['name'], phone=request['phone'],
                                    clinic_id=config['clinic_id'], source_clinic_hash=config['source_clinic_hash'],
                                    journal_dir=args.data_dir / '.hermes/secrets/pv-registrations')
            print(json.dumps({k:v for k,v in result.items() if k != 'phone'}), flush=True)
        return 0
    except (SyncError, RegistrationError) as exc:
        code = getattr(exc, 'code', str(exc))
        print(json.dumps({'status':'failed', 'code':code if re.fullmatch(r'[a-z_]+', code) else 'registration_failed'}), flush=True)
        return 1
    except Exception:
        print(json.dumps({'status':'failed', 'code':'registration_failed'}), flush=True)
        return 1
    finally:
        if browser is not None:
            browser.close()


if __name__ == '__main__':
    raise SystemExit(main())
