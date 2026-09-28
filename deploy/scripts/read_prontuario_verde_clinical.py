#!/usr/bin/env python3
"""Read one uniquely linked patient's clinical summaries for the current chat."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from patient_directory import lookup_for_panel
from prontuario_verde_booking_flow import chat_allowed
from prontuario_verde_clinical import read_chart, policy_context
from process_prontuario_verde_actions import BrowserSession, CONFIG, SYNC_LOCK
from sync_prontuario_verde import sync_lock

DIRECTORY = Path('/opt/data/patient_directory.json')


def conversation_evidence(facts):
    """Bound data sent to the assistant; no chart ID or navigation URL leaves here."""
    lists = (facts['evolutions'], facts['planned'], facts['performed'])
    if any(len(items) > 40 for items in lists):
        raise ValueError('clinical_record_too_large')
    notes = []
    for item in facts['evolutions']:
        text = item.get('text', '')
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError('clinical_record_too_large')
        notes.append({key: item.get(key, '') for key in ('source', 'index', 'title', 'aside', 'text')})
    return {
        'read_at': facts['read_at'], 'active_evolutions_only': facts['active_only'],
        'previous_care_verified': policy_context(facts)['established_patient'],
        'treatment_active': 'unknown', 'next_step_authorized': 'unknown',
        'evolutions': notes,
        'planned': [{key: item.get(key, '') for key in ('source', 'index', 'title', 'status')}
                    for item in facts['planned']],
        'performed': [{key: item.get(key, '') for key in ('source', 'index', 'title', 'executed_on')}
                      for item in facts['performed']],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    session = BrowserSession()
    try:
        request = json.loads(args.request_file.read_text())
        if not isinstance(request, dict) or set(request) != {'chat_id'}:
            raise ValueError('invalid_request')
        root = json.loads(CONFIG.read_text())
        cfg = root['patient_directory']
        if cfg.get('enabled') is not True or cfg.get('appointment_flow_enabled') is not True:
            raise ValueError('clinical_read_disabled')
        if not chat_allowed(cfg, request['chat_id']):
            raise ValueError('appointment_pilot_scope')
        identity = lookup_for_panel(DIRECTORY, cfg['clinic_id'], request['chat_id'],
                                    source_clinic_hash=cfg['source_clinic_hash'])
        if identity['status'] != 'matched':
            raise ValueError('patient_identity_unverified')
        with sync_lock(SYNC_LOCK):
            browser = session.acquire(cfg['source_clinic_hash'])
            facts = read_chart(browser, cfg, identity['patient_id'])
        print(json.dumps({'status': 'ok', 'clinical_evidence': conversation_evidence(facts)},
                         ensure_ascii=False), flush=True)
    except Exception as exc:
        code = getattr(exc, 'code', str(exc))
        if not isinstance(code, str) or not re.fullmatch(r'[a-z_]{1,64}', code):
            code = 'clinical_read_unavailable'
        print(json.dumps({'status': 'error', 'code': code}), flush=True)
    finally:
        session.close()


if __name__ == '__main__':
    main()
