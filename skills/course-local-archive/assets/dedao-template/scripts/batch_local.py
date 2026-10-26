#!/usr/bin/env python3
"""Coordinate bounded local stages for existing exported course folders.

No account/browser/token access, network stages, schedulers or background jobs.
Each course has a distinct coordinator lease; merge subprocesses acquire their
own manifest lock. Stage completion is never labeled complete delivery.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from archive_state import atomic_json, course_lock, sha_file
from audit_evidence import canonical_sha, local_file


def ready_handoff(folder,course_enid):
    """Verify a private producer handoff; absence/incomplete files is not ready.

    Producer writes payloads, then proof.json, then ready.json atomically last.
    Files remain private and are not automatically merged into an archive.
    """
    folder=Path(folder).resolve();ready=json.loads((folder/'ready.json').read_text())
    if ready.get('ready') is not True or ready.get('course_enid')!=course_enid:raise ValueError('Private handoff is not ready for this course')
    proof_path=local_file(folder,ready.get('proof_path'))
    if sha_file(proof_path)!=ready.get('proof_sha256'):raise ValueError('Private handoff proof hash changed')
    proof=json.loads(proof_path.read_text())
    if proof.get('course_enid')!=course_enid or proof.get('status')!='complete' or proof.get('errors')!=[]:raise ValueError('Private handoff proof is incomplete')
    verified=[]
    for row in proof.get('files',[]):
        path=local_file(folder,row.get('path'))
        if sha_file(path)!=row.get('sha256') or path.stat().st_size!=row.get('bytes'):raise ValueError('Private handoff payload is absent or changed')
        verified.append({'path':path.as_posix(),'sha256':row['sha256'],'bytes':row['bytes']})
    archives=[r for r in verified if Path(r['path']).name=='authorized-course.json']
    if len(archives)!=1:raise ValueError('A unique complete authorized-course.json handoff is required')
    source=json.loads(Path(archives[0]['path']).read_text())
    if source.get('course',{}).get('enid')!=course_enid or not source.get('complete',source.get('summary',{}).get('complete')) or source.get('errors') or not source.get('lessons'):raise ValueError('Authorized handoff payload is not a complete same-course export')
    return {'status':'ready_verified','proof_sha256':ready['proof_sha256'],'files':verified}


def stage_commands(root,stage,mode,run_id,resume):
    commands=[]
    if stage in {'rebuild','pipeline'}:
        commands.extend([['build_course_info.py'],['build_site.py'],['build_resources.py']])
    if stage in {'audit','pipeline'}:
        argv=['audit_archive.py','--mode',mode]
        if run_id:argv+=['--audit-run-id',run_id]
        if resume:argv+=['--resume-same-run']
        commands.append(argv)
    if stage in {'delivery','pipeline'}:commands.append(['verify_delivery.py'])
    return [[sys.executable,str(root/'scripts'/argv[0]),*argv[1:]] for argv in commands]


def _run_locked(root,stage,mode,run_id,resume,timeout):
    state_path=root/'raw/batch-local-state.json'
    state={'schema_version':1,'evidence_role':'local_stage_state','stage_requested':stage,'mode':mode,'audit_run_id':run_id,'started_at_utc':datetime.now(timezone.utc).isoformat(),'status':'running','stages':[]}
    atomic_json(state_path,state)
    try:
        course=json.loads((root/'course.json').read_text());state['course_enid']=course['course_enid']
        source=local_file(root,'raw/authorized-course.json');export=json.loads(source.read_text())
        if not export.get('complete',export.get('summary',{}).get('complete')) or export.get('errors'):raise ValueError('A complete locally exported course is required')
        state['source_archive_sha256']=sha_file(source);core_passed=True
        for command in stage_commands(root,stage,mode,run_id,resume):
            script=Path(command[1]);row={'script':script.name,'status':'running'};state['stages'].append(row);atomic_json(state_path,state)
            if not script.is_file():raise ValueError('Upgrade this course scripts before running local stages: '+script.name)
            completed=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=timeout)
            row.update(exit_code=completed.returncode,stdout=completed.stdout,stderr=completed.stderr,status='passed' if completed.returncode==0 else 'failed');atomic_json(state_path,state)
            if completed.returncode:
                if script.name=='verify_delivery.py':state['status']='awaiting_delivery_evidence'
                else:state['status']='failed';core_passed=False
                break
        else:state['status']='local_stages_passed'
        if core_passed and stage in {'pipeline','delivery'}:
            from verify_delivery import verify_delivery
            current=verify_delivery(root);atomic_json(root/'raw/delivery/status.json',current)
            if current['status']=='fully_delivered':state['status']='fully_delivered'
            elif state['status']!='failed':state['status']='awaiting_delivery_evidence'
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        state.update(status='failed',error=str(error))
        if state['stages'] and state['stages'][-1]['status']=='running':state['stages'][-1].update(status='failed',error=str(error))
    state['finished_at_utc']=datetime.now(timezone.utc).isoformat();atomic_json(state_path,state)
    return {'course':root.as_posix(),'status':state['status'],'state':state_path.relative_to(root).as_posix(),**({'error':state['error']} if state.get('error') else {})}


def run_course(root,stage='pipeline',mode='incremental',run_id=None,resume=False,timeout=7200):
    root=Path(root).resolve()
    try:
        with course_lock(root,blocking=False,lease='coordinator'):
            return _run_locked(root,stage,mode,run_id,resume,timeout)
    except BlockingIOError:return {'course':root.as_posix(),'status':'writer_busy'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--courses-root',type=Path);parser.add_argument('--course',type=Path,action='append',default=[]);parser.add_argument('--workers',type=int,default=2);parser.add_argument('--stage',choices=('audit','rebuild','delivery','pipeline'),default='pipeline');parser.add_argument('--mode',choices=('incremental','fresh'),default='incremental');parser.add_argument('--audit-run-id');parser.add_argument('--resume-same-run',action='store_true');parser.add_argument('--timeout',type=int,default=7200);parser.add_argument('--dry-run',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.resume_same_run and (args.mode!='fresh' or not args.audit_run_id):parser.error('Same-run resume requires fresh mode and an explicit audit run ID')
    courses={p.resolve() for p in args.course}
    if args.courses_root:
        courses.update(p.parent.resolve() for p in args.courses_root.resolve().glob('*/course.json') if (p.parent/'raw/authorized-course.json').is_file())
    if not courses:parser.error('Pass --course or --courses-root containing locally exported courses')
    if args.dry_run:
        print(json.dumps({'courses':[str(p) for p in sorted(courses)],'stage':args.stage,'workers':max(1,min(args.workers,4))},ensure_ascii=False));return 0
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,min(args.workers,4))) as pool:
        for future in as_completed([pool.submit(run_course,p,args.stage,args.mode,args.audit_run_id,args.resume_same_run,args.timeout) for p in sorted(courses)]):results.append(future.result())
    report={'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'courses':sorted(results,key=lambda r:r['course'])}
    if args.output:atomic_json(args.output,report)
    print(json.dumps(report,ensure_ascii=False));return int(any(row['status'] in {'failed','writer_busy'} for row in results))

if __name__=='__main__':raise SystemExit(main())
