#!/usr/bin/env python3
"""Mark an archive complete only after a fresh audit of the current same-course inputs.

Default: validate and preview. --apply atomically writes the completed manifest.
The auditor remains read-only; rerun it after finalization to bind the new file.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def file_digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def local_path(value):
    if not isinstance(value,str) or not value or '://' in value:
        raise ValueError('An audit input must use a local archive path')
    path=(ROOT/value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('An audit input is absent or outside this archive: '+str(value))
    return path


def prepare(report,course,audit_bytes,max_age):
    if report.get('status')!='passed' or report.get('archive_status')!='complete' or report.get('errors')!=[] or report.get('summary',{}).get('errors')!=0:
        raise ValueError('A passed audit with an explicit empty errors array is required')
    try:
        checked=datetime.fromisoformat(report['checked_at_utc'].replace('Z','+00:00'))
        age=(datetime.now(timezone.utc)-checked).total_seconds()
    except (KeyError,TypeError,ValueError):
        raise ValueError('The audit must contain a valid timezone-aware checked_at_utc') from None
    if age < -60 or age > max_age:
        raise ValueError('The audit is expired or future-dated; run audit_archive.py again')
    snapshots=report.get('input_snapshots',{})
    if any(role not in snapshots for role in ('manifest','source_archive','source_catalog')):
        raise ValueError('The audit lacks required input snapshots; rerun the current auditor')
    bound={}
    for role,snapshot in snapshots.items():
        path=local_path(snapshot.get('path'))
        body=path.read_bytes()
        if not snapshot.get('sha256') or digest(body)!=snapshot['sha256']:
            raise ValueError('Current '+role+' differs from the audited snapshot; audit again')
        bound[role]=(path,body)
    audited_files=report.get('audited_files')
    if not isinstance(audited_files,list) or not audited_files:
        raise ValueError('The audit lacks bound output-file snapshots; rerun the current auditor')
    output_states={}
    for snapshot in audited_files:
        path=local_path(snapshot.get('path'))
        stat=path.stat();before_state=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        if path.stat().st_size!=snapshot.get('bytes') or file_digest(path)!=snapshot.get('sha256'):
            raise ValueError('An audited output changed; run audit_archive.py again: '+snapshot['path'])
        stat=path.stat();output_states[path]=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
        if output_states[path]!=before_state:
            raise ValueError('An audited output changed during hash verification; audit again')
    if bound['manifest'][0]!=ROOT/'course.json' or report.get('manifest_snapshot_sha256')!=digest(bound['manifest'][1]):
        raise ValueError('The audit is not bound to the current course.json')
    for role in ('source_archive','source_catalog'):
        if report.get(role)!=snapshots[role]:
            raise ValueError('The audit has inconsistent source hash bindings')
    if bound['source_catalog'][0]!=ROOT/'raw/public/catalog.json':
        raise ValueError('The audit is not bound to the established source catalog')
    source=json.loads(bound['source_archive'][1]);catalog=json.loads(bound['source_catalog'][1])
    cfg=json.loads(bound['course_config'][1]) if 'course_config' in bound else {}
    enid=course.get('course_enid')
    identities=[enid,source.get('course',{}).get('enid'),catalog.get('class_info',{}).get('enid'),report.get('course_identity',{}).get('course_enid')]
    if cfg:identities.append(cfg.get('course_enid'))
    if not enid or any(value!=enid for value in identities):
        raise ValueError('The audited course identities disagree')
    lessons=course.get('lessons',[]);ids=[str(row['id']) for row in lessons]
    catalog_ids=[str(row.get('id_str') or row['id']) for chapter in catalog.get('chapter_list',[]) for row in chapter.get('article_list',[])]
    count=int(catalog.get('class_info',{}).get('current_article_count') or 0)
    summary=report['summary']
    if not count or len(ids)!=count or len(set(ids))!=count or ids!=catalog_ids or ids!=[str(row['id']) for row in source.get('lessons',[])] or ids!=report.get('course_identity',{}).get('lesson_ids') or course.get('expected_lesson_count')!=count:
        raise ValueError('The complete ordered source lesson set is required')
    if not source.get('complete',source.get('summary',{}).get('complete')) or source.get('errors'):
        raise ValueError('The authorized source export is incomplete')
    for key in ('expected_lessons','catalog_lessons','exported_full_bodies','local_lesson_entries','raw_content_bytes_verified','html_text_verified','markdown_text_verified','website_bodies_verified'):
        if summary.get(key)!=count:
            raise ValueError('The audit does not verify every expected lesson: '+key)
    if any(row.get('status')!='imported' or row.get('text_integrity')!='verified' or row.get('images_status')!='complete' or row.get('audio_status') not in {'complete','not_applicable'} or row.get('video_status') not in {'complete','not_applicable'} for row in lessons):
        raise ValueError('Every lesson must have verified text, images and complete or inapplicable media')
    result=copy.deepcopy(course)
    result['archive_status']='complete'
    result['archive_summary']={
        'lessons':count,
        'audio':sum(len(row.get('audio') or []) for row in lessons),
        'video':sum(len(row.get('video') or []) for row in lessons),
        'images':int(summary.get('source_images_verified',0)),
        'reference_pdfs':int(summary.get('reference_pdfs_verified',0)),
        'unavailable_external_reference_pdfs':sum(row.get('kind')=='optional_external_reference_unavailable' for row in report.get('warnings',[])),
        'video_decrypted':sum(track.get('path','').startswith('assets/video/decrypted/') for row in lessons for track in row.get('video',[])),
        'video_web_alternatives':sum(len(row.get('video_web_alternatives') or []) for row in lessons),
        'video_encrypted_originals':sum(len(row.get('video_encrypted_original') or []) for row in lessons),
    }
    if result['archive_summary']['audio']!=int(summary.get('audio_track_references_verified',0)) or result['archive_summary']['video']!=int(summary.get('video_track_references_verified',0)):
        raise ValueError('Current media references do not match the audited totals')
    audit_sha=digest(audit_bytes)
    result['archive_finalization']={'status':'complete','audit_path':'raw/finalization-audits/'+audit_sha+'.json','audit_checked_at_utc':report['checked_at_utc'],'audit_sha256':audit_sha,'audited_manifest_sha256':report['manifest_snapshot_sha256'],'source_archive_sha256':snapshots['source_archive']['sha256'],'source_catalog_sha256':snapshots['source_catalog']['sha256']}
    return result,bound,output_states


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',default='raw/archive-audit.json')
    parser.add_argument('--max-audit-age-seconds',type=int,default=3600)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.max_audit_age_seconds<=0:raise ValueError('The maximum audit age must be positive')
    audit_path=local_path(args.audit);audit_bytes=audit_path.read_bytes();report=json.loads(audit_bytes)
    manifest=ROOT/'course.json';before=manifest.read_bytes();course=json.loads(before)
    updated,bound,output_states=prepare(report,course,audit_bytes,args.max_audit_age_seconds)
    if audit_path.read_bytes()!=audit_bytes or manifest.read_bytes()!=before or any(path.read_bytes()!=body for path,body in bound.values()):
        raise ValueError('An audited input changed during finalization; retry after a fresh audit')
    for path,expected in output_states.items():
        stat=path.stat()
        if (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=expected:
            raise ValueError('An audited output changed during finalization; audit again')
    if not args.apply:
        print(json.dumps({'applied':False,'status':'ready','archive_status':'complete','summary':updated['archive_summary']},ensure_ascii=False));return 0
    saved_audit=ROOT/updated['archive_finalization']['audit_path']
    saved_audit.parent.mkdir(parents=True,exist_ok=True)
    if saved_audit.exists() and saved_audit.read_bytes()!=audit_bytes:
        raise ValueError('The preserved audit snapshot differs from its expected SHA-256')
    if not saved_audit.exists():saved_audit.write_bytes(audit_bytes)
    temporary=manifest.with_name('course.json.finalize-'+str(os.getpid()))
    temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temporary.replace(manifest)
    print(json.dumps({'applied':True,'archive_status':'complete','summary':updated['archive_summary'],'next_step':'Rerun audit_archive.py to bind the completed manifest'},ensure_ascii=False))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError) as error:raise SystemExit(str(error))
