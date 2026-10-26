#!/usr/bin/env python3
"""Read-only image hashing and complete pixel/frame decoding, with scoped reuse."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        for part in iter(lambda:source.read(1024*1024),b''):value.update(part)
    return value.hexdigest()

def png_structure(path):
    """Ancillary metadata CRC problems are distinct from critical pixel chunks."""
    warnings=[]
    with path.open('rb') as source:
        if source.read(8)!=b'\x89PNG\r\n\x1a\n':return warnings
        ended=False
        while not ended:
            header=source.read(8)
            if len(header)!=8:raise ValueError('Truncated PNG chunk header')
            length,kind=struct.unpack('>I4s',header)
            if length>path.stat().st_size:raise ValueError('PNG chunk length exceeds file')
            crc=zlib.crc32(kind);remaining=length
            while remaining:
                part=source.read(min(remaining,1024*1024))
                if not part:raise ValueError('Truncated PNG chunk')
                crc=zlib.crc32(part,crc);remaining-=len(part)
            stored=source.read(4)
            if len(stored)!=4:raise ValueError('Truncated PNG CRC')
            if struct.unpack('>I',stored)[0]!=(crc&0xffffffff):
                if not(kind[0]&32):raise ValueError('Critical PNG chunk CRC mismatch: '+kind.decode('ascii','replace'))
                warnings.append({'kind':'source_png_ancillary_crc_warning','chunk':kind.decode('ascii','replace')})
            ended=kind==b'IEND'
        if source.read(1):warnings.append({'kind':'source_png_trailing_bytes'})
    return warnings

def decode(path,timeout=120):
    warnings=png_structure(path)
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,codec_name,width,height:format=format_name','-of','json',str(path)],capture_output=True,text=True,timeout=min(timeout,60))
    if probe.returncode:raise ValueError('Image probe failed: '+probe.stderr[-2000:])
    metadata=json.loads(probe.stdout)
    if not any(s.get('codec_type')=='video' for s in metadata.get('streams',[])):raise ValueError('Image has no decodable pixel stream')
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-err_detect','explode','-threads','1','-i',str(path),'-map','0:v','-fps_mode','passthrough','-progress','pipe:1','-nostats','-f','null','-'],capture_output=True,text=True,timeout=timeout)
    progress={}
    for line in result.stdout.splitlines():
        if '=' in line:
            key,value=line.split('=',1);progress[key]=value.strip()
    frames=int(progress.get('frame','0'))
    if result.returncode or frames<1 or progress.get('progress')!='end':raise ValueError('Image full decode failed: '+result.stderr[-2000:])
    if result.stderr.strip() and not warnings:raise ValueError('Image decoder diagnostics require review: '+result.stderr[-2000:])
    return {'status':'verified_with_source_warnings' if warnings else 'verified','frames_decoded':frames,'full_decode_exit_code':result.returncode,'all_frames_decoded':True,'probe':metadata,'decoder_stderr':result.stderr,'source_metadata_warnings':warnings}

def run_validation(root=ROOT, *, fresh=False, audit_run_id=None, resume_same_run=False, workers=2, timeout=120, output=None):
    root=Path(root).resolve();output=Path(output) if output else root/'raw/image-verification.json'
    audit_run_id=audit_run_id or uuid.uuid4().hex
    if not audit_run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in audit_run_id):raise ValueError('Unsafe audit run id')
    previous=json.loads(output.read_text()) if output.is_file() else {}
    may_reuse=not fresh or resume_same_run and previous.get('audit_run_id')==audit_run_id
    cached={row['sha256']:row for row in previous.get('images',[]) if may_reuse and row.get('status') in ('verified','verified_with_source_warnings') and row.get('all_frames_decoded') and row.get('full_decode_exit_code')==0}
    manifest=root/'assets/images/manifest.json'
    records=json.loads(manifest.read_text()) if manifest.is_file() else []
    if isinstance(records,dict):records=records.get('images',records.get('files',[]))
    expected={row['path']:row for row in records if isinstance(row,dict) and row.get('path')}
    physical={str(p.relative_to(root)):p for p in (root/'assets/images').rglob('*') if p.is_file() and p.name!='manifest.json' and p.suffix not in ('.part','.tmp')}
    rows=[];unique={}
    for value in sorted(set(expected)|set(physical)):
        row={'path':value}
        try:
            path=(root/value).resolve()
            if not path.is_relative_to(root) or not path.is_file():raise ValueError('Missing or escaping image path')
            stat=path.stat();signature=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
            row.update(bytes=stat.st_size,sha256=digest(path),_state=signature)
            old=expected.get(value,{})
            if old.get('sha256') and old['sha256']!=row['sha256'] or old.get('bytes') is not None and old['bytes']!=row['bytes']:raise ValueError('Image differs from source image manifest')
            unique.setdefault(row['sha256'],path)
        except Exception as error:row.update(status='failed',error=str(error))
        rows.append(row)
    results={};attempted=0;reused=0
    def one(item):
        content,path=item
        if content in cached:
            return content,{k:v for k,v in cached[content].items() if k not in ('path','bytes','sha256','_state','decode_reused','reuse_origin')},True
        try:return content,decode(path,timeout),False
        except Exception as error:return content,{'status':'failed','error':str(error)},False
    with ThreadPoolExecutor(max_workers=max(1,min(int(workers),4))) as pool:
        for future in as_completed([pool.submit(one,item) for item in unique.items()]):
            content,value,did_reuse=future.result();results[content]=(value,did_reuse)
            if did_reuse:reused+=1
            else:attempted+=1
    for row in rows:
        if row.get('status')=='failed':
            row.pop('_state',None)
            continue
        value,did_reuse=results[row['sha256']];row.update(value,decode_reused=did_reuse,reuse_origin='same_audit_run' if did_reuse and fresh else 'matching_prior_full_decode' if did_reuse else None)
        try:
            stat=(root/row['path']).stat()
            if (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=row['_state']:raise ValueError('Image changed during verification')
        except Exception as error:row.update(status='failed',error=str(error))
        row.pop('_state',None)
    failed=sum(row.get('status')=='failed' for row in rows);warnings=sum(bool(row.get('source_metadata_warnings')) for row in rows)
    report={'schema_version':1,'audit_run_id':audit_run_id,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'mode':'fresh' if fresh else 'incremental','status':'failed' if failed else 'passed_with_source_warnings' if warnings else 'passed','image_manifest_sha256':digest(manifest) if manifest.is_file() else None,'summary':{'images':len(rows),'unique_content_sha256':len(unique),'fresh_unique_decodes':attempted,'reused_unique_decodes':reused,'failed':failed,'source_warning_paths':warnings},'images':rows}
    output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_name(output.name+'.tmp');temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');temporary.replace(output)
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--fresh',action='store_true');p.add_argument('--audit-run-id');p.add_argument('--resume-same-run',action='store_true');p.add_argument('--workers',type=int,default=2);p.add_argument('--timeout',type=float,default=120);p.add_argument('--output',type=Path)
    a=p.parse_args();result=run_validation(a.root,fresh=a.fresh,audit_run_id=a.audit_run_id,resume_same_run=a.resume_same_run,workers=a.workers,timeout=a.timeout,output=a.output)
    print(json.dumps({'status':result['status'],'summary':result['summary']},ensure_ascii=False));return int(result['status']=='failed')
if __name__=='__main__':raise SystemExit(main())
