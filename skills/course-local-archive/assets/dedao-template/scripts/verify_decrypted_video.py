#!/usr/bin/env python3
"""Verify a new candidate produced from an archived legacy encrypted MP4.

This script performs no decryption and accepts no keys or session tokens. A
playable MP4 alone does not prove it came from the encrypted original. The
optional operation report must bind the actual transform to both file hashes.
Original media, the reader and course.json are never modified.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def safe_path(value):
    path=(ROOT/value).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('All paths must be inside this course folder')
    return path

def container_boxes(path):
    result=[];total=path.stat().st_size;offset=0
    with path.open('rb') as stream:
        while offset<total:
            stream.seek(offset);header=stream.read(16)
            if len(header)<8:raise ValueError('Incomplete MP4 box header')
            size,kind=struct.unpack('>I4s',header[:8]);header_size=8
            if size==1:
                if len(header)<16:raise ValueError('Incomplete extended MP4 box header')
                size=struct.unpack('>Q',header[8:16])[0];header_size=16
            if size==0:size=total-offset
            if size<header_size or offset+size>total:raise ValueError('MP4 box boundaries exceed the candidate file')
            result.append({'type':kind.decode('ascii',errors='replace'),'offset':offset,'bytes':size});offset+=size
    kinds={row['type'] for row in result}
    if not {'ftyp','moov','mdat'}.issubset(kinds):raise ValueError('Candidate lacks required MP4 ftyp/moov/mdat boxes')
    return result

def clean_error(text):return re.sub(r'https?://[^\s]+','[URL omitted]',text)[-3000:]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lesson-id',required=True)
    parser.add_argument('--candidate',required=True,type=safe_path)
    parser.add_argument('--operation-report',type=safe_path,help='Transform provenance with algorithm/source_path/source_sha256/output_path/output_sha256; do not include keys')
    parser.add_argument('--report',type=safe_path)
    parser.add_argument('--timeout',type=int,default=900)
    args=parser.parse_args();lid=str(args.lesson_id)
    manifest=json.loads((ROOT/'raw/video-archive-report.json').read_text())
    record=next((row for row in manifest['videos'] if str(row['lesson_id'])==lid),None)
    if not record:parser.error('Lesson has no archived legacy encrypted original')
    source=safe_path(record['path']);candidate=args.candidate
    if candidate==source:parser.error('Candidate must be a separate file; original ciphertext must remain unchanged')
    if not source.is_file() or not candidate.is_file():parser.error('Both original and candidate must exist')
    report_path=args.report or ROOT/'raw/decrypted-video-validation'/f'{lid}.json'
    if report_path in {source,candidate,ROOT/'course.json'}:parser.error('Report must not overwrite media or course.json')
    if report_path.suffix!='.json':parser.error('Verification report must be a JSON file')
    if report_path.exists() and report_path.parent!=ROOT/'raw/decrypted-video-validation':parser.error('Refusing to overwrite an existing file outside the validation report folder')
    before=digest(source);candidate_hash=digest(candidate);errors=[]
    if before!=record.get('sha256') or source.stat().st_size!=record.get('bytes'):errors.append('Original ciphertext differs from archived source evidence')
    report={'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'lesson_id':lid,'source_path':source.relative_to(ROOT).as_posix(),'source_sha256_before':before,'expected_source_sha256':record.get('sha256'),'candidate_path':candidate.relative_to(ROOT).as_posix(),'candidate_sha256':candidate_hash,'candidate_bytes':candidate.stat().st_size,'source_bytes':source.stat().st_size}
    try:report['mp4_boxes']=container_boxes(candidate)
    except ValueError as error:errors.append(str(error))
    probe=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(candidate)],capture_output=True,text=True,timeout=min(args.timeout,90))
    metadata=json.loads(probe.stdout) if probe.returncode==0 else {}
    keep={'index','codec_name','codec_type','profile','width','height','sample_rate','channels','duration','bit_rate','nb_frames','r_frame_rate','avg_frame_rate'}
    streams=[{key:value for key,value in row.items() if key in keep} for row in metadata.get('streams',[])]
    videos=[row for row in streams if row.get('codec_type')=='video'];audios=[row for row in streams if row.get('codec_type')=='audio']
    report['probe']={'returncode':probe.returncode,'streams':streams,'format':{key:metadata.get('format',{}).get(key) for key in ['format_name','duration','size','bit_rate']},'stderr':clean_error(probe.stderr)}
    if probe.returncode or not videos or not audios:errors.append('Candidate must contain both a playable video stream and an audio stream')
    expected=float(record.get('source_duration') or 0);actual=float(metadata.get('format',{}).get('duration') or 0)
    report['expected_duration_seconds']=expected;report['actual_duration_seconds']=actual
    if not actual or expected and abs(actual-expected)>max(2,expected*.002):errors.append('Candidate duration differs from archived source duration')
    resolution=int(record.get('resolution_selected') or 0)
    if max([row.get('height',0) for row in videos],default=0)<resolution:errors.append('Candidate resolution is lower than selected source')
    if videos and audios and not probe.returncode:
        decode=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-err_detect','explode','-i',str(candidate),'-map','0:v?','-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=args.timeout)
        report['full_decode']={'returncode':decode.returncode,'mapping':['0:v?','0:a?'],'video_streams_checked':len(videos),'audio_streams_checked':len(audios),'stderr':clean_error(decode.stderr)}
        if decode.returncode:errors.append('One or more video/audio streams failed complete decoding')
    else:report['full_decode']={'returncode':None,'reason':'No complete candidate audio/video streams'}
    after=digest(source);report['source_sha256_after']=after;report['original_unchanged']=before==after==record.get('sha256')
    if not report['original_unchanged']:errors.append('Original ciphertext hash changed during verification')
    report['candidate_unchanged']=digest(candidate)==candidate_hash
    if not report['candidate_unchanged']:errors.append('Candidate changed during verification')
    web=json.loads((ROOT/'raw/web-video-archive-report.json').read_text())
    previous=next((row for row in web.get('videos',[]) if str(row.get('lesson_id'))==lid),{})
    report['matches_existing_web_mp4_bytes']=candidate_hash==previous.get('sha256')
    provenance=False
    if args.operation_report:
        operation=json.loads(args.operation_report.read_text())
        if isinstance(operation,dict) and isinstance(operation.get('videos'),list):
            rows=[row for row in operation['videos'] if str(row.get('lesson_id'))==lid]
            if len(rows)!=1:raise ValueError('Batch transform report must contain exactly one matching lesson')
            row=rows[0]
            if row.get('status')!='decrypted_verified' or not row.get('original_unchanged'):
                raise ValueError('Batch transform report does not claim a verified unchanged-source transformation')
            operation={'algorithm':row.get('conversion'),'source_path':row.get('source_path'),'source_sha256':row.get('source_sha256'),'output_path':row.get('path'),'output_sha256':row.get('sha256')}
        accepted={key:operation.get(key) for key in ['algorithm','source_path','source_sha256','output_path','output_sha256']}
        report['operation_report_path']=args.operation_report.relative_to(ROOT).as_posix()
        provenance=bool(isinstance(accepted['algorithm'],str) and re.fullmatch(r'[A-Za-z0-9_.:/ +()-]{1,120}',accepted['algorithm']) and isinstance(accepted['source_path'],str) and isinstance(accepted['output_path'],str) and accepted['source_sha256']==before and accepted['output_sha256']==candidate_hash and safe_path(accepted['source_path'])==source and safe_path(accepted['output_path'])==candidate)
        report['operation_provenance']=accepted
        if not provenance:errors.append('Operation provenance does not bind this source and output')
    report['actual_transform_provenance_verified']=provenance
    report['status']='failed' if errors else 'verified_transform_output' if provenance else 'candidate_media_verified_provenance_unestablished'
    report['errors']=errors
    report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'original_unchanged':report['original_unchanged'],'video_streams':len(videos),'audio_streams':len(audios),'full_decode_exit_code':report['full_decode']['returncode'],'operation_provenance_verified':provenance,'report':report_path.relative_to(ROOT).as_posix()},ensure_ascii=False))
    return 1 if errors else 0 if provenance else 2

if __name__=='__main__':raise SystemExit(main())
