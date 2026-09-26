#!/usr/bin/env python3
"""Read eligible PV openings for one authenticated contact; never submit forms."""
from datetime import date, datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from appointment_policy import Appointment, classify_booking
from patient_directory import lookup_for_panel
from prontuario_verde_availability import available_starts
from prontuario_verde_booking_flow import chat_allowed
from prontuario_verde_native_availability import read_snapshot
from prontuario_verde_native_booking import ProntuarioVerdeHermesPort, SAO_PAULO
from sync_prontuario_verde import sync_lock
from sync_prontuario_verde_schedule import refresh_schedule, select_calendar_scope
from process_prontuario_verde_actions import BrowserSession, CONFIG, SYNC_LOCK

DIRECTORY = Path('/opt/data/patient_directory.json')
SCHEDULE = Path('/opt/data/prontuario_verde_schedule.json')


def find_slots(args, root_config, browser, *, directory_path=DIRECTORY, schedule_path=SCHEDULE):
    cfg, policy = root_config['patient_directory'], root_config['appointment_policy']
    if cfg.get('enabled') is not True or cfg.get('appointment_flow_enabled') is not True:
        raise ValueError('appointment_flow_disabled')
    if not chat_allowed(cfg,args.get('chat_id')):
        raise ValueError('appointment_pilot_scope')
    day = date.fromisoformat(args['date'])
    if not datetime.now(SAO_PAULO).date() <= day <= datetime.now(SAO_PAULO).date()+timedelta(days=90):
        raise ValueError('invalid_search_date')
    period = args.get('period', 'any')
    if period not in {'any', 'morning', 'afternoon'}:
        raise ValueError('invalid_period')
    identity = lookup_for_panel(directory_path, cfg['clinic_id'], args['chat_id'],
                                source_clinic_hash=cfg['source_clinic_hash'])
    if identity['status'] != 'matched':
        raise ValueError('patient_identity_unverified')
    units = policy.get('unit_ids')
    if not isinstance(units,list) or len(units)!=1 or not re.fullmatch(r'[1-9][0-9]*',str(units[0])):
        raise ValueError('unit_policy_unavailable')
    operation = args.get('operation','book')
    professional = args.get('professional_key')
    appointment_type = args.get('appointment_type')
    query = dict(chat_id=args['chat_id'], patient_id=identity['patient_id'], clinic_id=cfg['clinic_id'],
                 source_clinic_hash=cfg['source_clinic_hash'], unit_id=str(units[0]), operation=operation,
                 policy_context={'established_patient':True,'in_treatment':False,
                                 'chart_verified':False,'no_added_procedure':False})
    original = None
    if operation == 'reschedule':
        refresh_schedule(browser,cfg,directory_path=directory_path,target=schedule_path)
        snapshot=json.loads(Path(schedule_path).read_text())
        rows=[row for row in snapshot['appointments'] if row['patient_id']==identity['patient_id']
              and row['status'] in {'agendado','confirmado'}
              and datetime.fromisoformat(row['start'])>datetime.now(timezone.utc)]
        if len(rows)!=1:
            raise ValueError('original_appointment_ambiguous')
        row=rows[0]
        select_calendar_scope(browser,row['professional_id'],query['unit_id'])
        query.update(appointment_id=row['id'], professional_id=row['professional_id'],
                     expected_start=row['start'], expected_end=row['end'])
        form=ProntuarioVerdeHermesPort(browser,cfg).inspect_original_form(query)
        if (form['patient_id']!=identity['patient_id'] or form['unit_id']!=query['unit_id']
                or form['professional_id']!=row['professional_id']
                or datetime.fromisoformat(form['start']) != datetime.fromisoformat(row['start'])
                or datetime.fromisoformat(form['end']) != datetime.fromisoformat(row['end'])):
            raise ValueError('original_appointment_changed')
        matching_types=[key for key,value in policy.get('type_ids',{}).items()
                        if str(value)==form['type_id']
                        and policy.get('appointments',{}).get(key,{}).get('duration_minutes')==int(form['duration_min'])]
        matching_professionals=[key for key,value in policy.get('professional_ids',{}).items()
                                if str(value)==form['professional_id']]
        if len(matching_types)!=1 or len(matching_professionals)!=1:
            raise ValueError('original_appointment_type_ambiguous')
        appointment_type,professional=matching_types[0],matching_professionals[0]
        original=Appointment(appointment_type,professional,int(form['duration_min']))
        query['original_verified_at']=datetime.now(timezone.utc).isoformat()
    elif operation != 'book':
        raise ValueError('operation_unsupported')
    decision=classify_booking(appointment_type,policy=policy,professional=professional,
                              established_patient=True,reschedule_of=original)
    if not decision.auto_book or not professional or professional not in decision.eligible_professionals:
        raise ValueError('team_confirmation_required')
    professional_id=policy.get('professional_ids',{}).get(professional)
    type_id=policy.get('type_ids',{}).get(appointment_type)
    if any(not re.fullmatch(r'[1-9][0-9]*',str(value)) for value in (professional_id,type_id)):
        raise ValueError('booking_policy_unavailable')
    query.update(professional_key=professional,professional_id=str(professional_id),
                 appointment_type=appointment_type,type_id=str(type_id),duration_min=decision.duration_minutes)
    start=datetime.combine(day,datetime.min.time(),tzinfo=SAO_PAULO)
    snapshot=read_snapshot(browser,cfg,{**query,'requested_start':start.isoformat()})
    starts=available_starts(snapshot,source_clinic_hash=cfg['source_clinic_hash'],
                            professional_id=query['professional_id'],unit_id=query['unit_id'],
                            day=day,duration_minutes=decision.duration_minutes,now=datetime.now(timezone.utc))
    starts=[s for s in starts if period=='any' or (s.hour<12)==(period=='morning')]
    if operation == 'reschedule':
        starts = [s for s in starts if s != datetime.fromisoformat(query['expected_start'])]
    slots=[dict(start=s.isoformat(),end=(s+timedelta(minutes=decision.duration_minutes)).isoformat()) for s in starts[:3]]
    return {'query':query,'slots':slots}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file',required=True)
    args=parser.parse_args()
    os.umask(0o077)
    request=json.loads(Path(args.request_file).read_text())
    root=json.loads(CONFIG.read_text())
    session=BrowserSession()
    try:
        with sync_lock(SYNC_LOCK):
            browser=session.acquire(root['patient_directory']['source_clinic_hash'])
            result=find_slots(request,root,browser)
        print(json.dumps({'status':'ok',**result}),flush=True)
    except Exception as exc:
        code=getattr(exc,'code',str(exc))
        if not re.fullmatch(r'[a-z_]{1,64}',code):
            code='availability_unavailable'
        print(json.dumps({'status':'error','code':code}),flush=True)
    finally:
        session.close()


if __name__=='__main__': main()
