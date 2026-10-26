#!/usr/bin/env python3
"""Preserve source-declared introductions, captions, attachments and video audio.

Download/verify first; --apply merges only verified results while holding the
course manifest lock. Protected audio originals stay separate from losslessly
copied audio of a same-ID, already verified local video. This never decrypts an
audio source or reuses a different video's sound.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request,urlopen
from urllib.parse import urlsplit

from archive_state import course_lock,atomic_json,compare_and_write_manifest
from media_inventory import ROOT,load_inventory,public_inventory,digest,is_url
from hls_assets import preserve_hls,audit_hls,audio_packet_proof

ROLES={'subtitle','course_intro_video','course_intro_audio','course_intro_poster','video_audio_component','attachment'}

def now():return datetime.now(timezone.utc).isoformat()
def read(path,default=None):return json.loads(path.read_text()) if path.is_file() else default
def stem(value):return re.sub(r'[^A-Za-z0-9_-]','_',str(value or 'course'))
def safe(root,value):
    root=Path(root).resolve()
    p=(root/value).resolve()
    if not p.is_relative_to(root):raise ValueError('Asset path escapes archive')
    return p
def checked(root,row):
    if not isinstance(row,dict) or not row.get('path'):return False
    p=safe(root,row['path'])
    return p.is_file() and p.stat().st_size==row.get('bytes') and digest(p)==row.get('sha256')
def public_error(value):return re.sub(r'https?://[^\s"\'<>]+','[URL omitted]',str(value))[-1200:]
def run(argv,timeout=1800):
    p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    return {'exit_code':p.returncode,'stdout':p.stdout,'stderr':public_error(p.stderr)}
def probe(path):
    p=run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],60)
    if p['exit_code']:raise ValueError('Media probe failed: '+p['stderr'])
    return json.loads(p['stdout'])
def validate(path,kind):
    metadata=probe(path);streams=metadata.get('streams',[]);audio=[s for s in streams if s.get('codec_type')=='audio'];video=[s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')]
    if not audio or (kind=='video' and not video):raise ValueError('Expected audio/video stream absent')
    if kind=='audio' and video:raise ValueError('An independent audio resource unexpectedly includes video')
    duration=float(metadata.get('format',{}).get('duration') or 0)
    if duration<=0:raise ValueError('Media has no positive duration')
    command=['ffmpeg','-nostdin','-v','error','-xerror','-err_detect','explode','-threads','1','-i',str(path)]
    if kind=='video':command+=['-map','0:v']
    command+=['-map','0:a','-f','null','-'];decode=run(command)
    if decode['exit_code'] or decode['stderr'].strip():raise ValueError('Full media decode failed: '+decode['stderr'])
    return {'ffprobe':metadata,'duration':duration,'full_decode_exit_code':0,'all_audio_streams_decoded':True,'all_video_streams_decoded':kind=='video','decode_diagnostics':decode['stderr']}
def file_record(root,path):return {'path':path.relative_to(root).as_posix(),'bytes':path.stat().st_size,'sha256':digest(path)}
def download(root,url,target,timeout=60,max_bytes=10*1024**3):
    if not is_url(url):raise ValueError('Only source-declared HTTP(S) asset URLs may be downloaded')
    target.parent.mkdir(parents=True,exist_ok=True);part=target.with_name(target.name+'.part')
    try:
        with urlopen(Request(url,headers={'User-Agent':'CourseLocalArchive/1.0'}),timeout=timeout) as response:
            length=int(response.headers.get('Content-Length') or 0);etag=response.headers.get('ETag','').strip('"');content_type=response.headers.get('Content-Type','')
            if length>max_bytes:raise ValueError('Source exceeds configured maximum bytes')
            count=0;md5=hashlib.md5()
            with part.open('wb') as out:
                for chunk in iter(lambda:response.read(1024*1024),b''):
                    count+=len(chunk)
                    if count>max_bytes:raise ValueError('Source exceeds configured maximum bytes')
                    out.write(chunk);md5.update(chunk)
            if not count or (length and count!=length):raise ValueError('Incomplete source response bytes')
            if re.fullmatch(r'[a-fA-F0-9]{32}',etag) and md5.hexdigest().lower()!=etag.lower():raise ValueError('Source ETag MD5 mismatch')
        part.replace(target)
        return {**file_record(root,target),'http_content_length':length or None,'http_content_type':content_type,'etag_md5_verified':bool(re.fullmatch(r'[a-fA-F0-9]{32}',etag))}
    finally:part.unlink(missing_ok=True)
def packet_hash(path):
    result=run(['ffmpeg','-nostdin','-v','error','-i',str(path),'-map','0:a','-c','copy','-f','streamhash','-hash','sha256','-'])
    if result['exit_code']:raise ValueError('Audio packet hashing failed')
    lines=[line.strip() for line in result['stdout'].splitlines() if ',a,' in line]
    if not lines:raise ValueError('Audio packet hash absent')
    return lines
def validate_image(path):
    metadata=probe(path)
    pictures=[s for s in metadata.get('streams',[]) if s.get('codec_type')=='video' and int(s.get('width') or 0)>0 and int(s.get('height') or 0)>0]
    if not pictures:raise ValueError('Introduction poster has no decodable image dimensions')
    decoded=run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(path),'-map','0:v','-frames:v','1','-f','null','-'],60)
    if decoded['exit_code']:raise ValueError('Introduction poster pixel decode failed')
    return {'width':pictures[0]['width'],'height':pictures[0]['height'],'pixel_decode_exit_code':0}
def verified_video(root,resource,course,completed):
    mid=resource['source_media_id'];lid=resource.get('lesson_id')
    if lid is None:
        candidates=[r for r in completed if r.get('role')=='course_intro_video' and r.get('source_media_id')==mid]
        candidates += [course.get('course_intro_video',{})]
    else:
        lesson=next((l for l in course.get('lessons',[]) if str(l['id'])==lid),{})
        candidates=lesson.get('video',[])
    originals=(read(root/'raw/video-archive-report.json',{}) or {}).get('videos',[])
    for candidate in candidates:
        if not checked(root,candidate):continue
        if candidate.get('role')=='course_intro_video' and candidate.get('full_decode_exit_code')==0 and candidate.get('source_media_id')==mid:return candidate
        report=read(safe(root,candidate.get('archive_report','raw/course-extras-report.json')), {})
        proof_rows=report.get('videos',report.get('records',[]))
        for row in proof_rows:
            if row.get('path')!=candidate['path'] or row.get('sha256')!=candidate['sha256'] or row.get('bytes')!=candidate['bytes']:continue
            if row.get('status') not in {'complete','decrypted_verified'} or row.get('full_decode_exit_code',row.get('decode',{}).get('returncode'))!=0:continue
            if str(row.get('source_media_id') or '')==mid:return candidate
            origin=next((o for o in originals if str(o.get('lesson_id'))==lid and int(o.get('video_index',0))==resource.get('video_index',0) and str(o.get('source_media_id'))==mid),None)
            if origin and row.get('source_sha256')==origin.get('sha256') and row.get('source_path')==origin.get('path') and checked(root,origin):return candidate
    raise ValueError('No complete, current hash-bound video proof for the exact source media ID')
def archive_resource(root,resource,course,completed,previous):
    root=Path(root).resolve()
    rid=resource['resource_id'];role=resource['role'];record={**public_inventory(resource),'started_at_utc':now(),'status':'pending'}
    if previous and previous.get('status')=='complete' and checked(root,previous):
        protected_ok=not previous.get('encrypted_source') or checked(root,previous['encrypted_source'])
        derived=previous.get('derived_from_verified_video');input_ok=not derived or checked(root,derived)
        if protected_ok and input_ok:return {**previous,'reused_matching_current_hash':True}
    token=stem(resource.get('lesson_id'))+'-'+stem(resource.get('source_media_id'))+'-'+rid[:10]
    role_dir={'subtitle':'assets/subtitles','course_intro_video':'assets/video/course-intro','course_intro_audio':'assets/audio/course-intro','video_audio_component':'assets/audio/video-components','course_intro_poster':'assets/images','attachment':'assets/attachments'}[role]
    source_suffix=Path(urlsplit(resource.get('_url') or '').path).suffix.lstrip('.').lower()
    ext=resource.get('format') if role=='subtitle' else 'mp4' if role=='course_intro_video' else (source_suffix if source_suffix in {'mp3','m4a','aac','ogg','wav','flac'} else 'm4a') if role in {'course_intro_audio','video_audio_component'} else source_suffix if re.fullmatch('[a-z0-9]{1,8}',source_suffix) else 'bin'
    target=safe(root,role_dir+'/'+token+'.'+ext)
    try:
        if source_suffix=='m3u8' and role in {'course_intro_video','course_intro_audio','video_audio_component'}:
            record['hls']=preserve_hls(resource['_url'],root,role_dir+'/hls/'+token)
            playlist=safe(root,record['hls']['local_playlist_path'])
            target.parent.mkdir(parents=True,exist_ok=True)
            command=['ffmpeg','-nostdin','-v','error','-y','-allowed_extensions','ALL','-protocol_whitelist','file,crypto,data','-i',str(playlist)]
            if role=='course_intro_video':command+=['-map','0:v','-map','0:a']
            else:command+=['-map','0:a','-vn']
            remux=run(command+['-c','copy','-movflags','+faststart',str(target)])
            if remux['exit_code']:raise ValueError('Preserved standard HLS cannot be losslessly remuxed: '+remux['stderr'])
            record.update(file_record(root,target),output_origin='standard_hls_lossless_remux')
            record['hls_audio_packet_proof']=audio_packet_proof(root,record['hls'],target)
        else:record.update(download(root,resource.get('_url'),target))
        if role=='subtitle':
            text=target.read_text(encoding='utf-8-sig')
            if resource['format']=='vtt' and not text.startswith('WEBVTT'):raise ValueError('Source is not WebVTT')
            cues=re.findall(r'(?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{3}\s*-->\s*(?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{3}',text)
            if not cues:raise ValueError('Subtitle source contains no valid timing cues')
            record.update(cue_count=len(cues),text_encoding='utf-8',label=('WebVTT' if resource['format']=='vtt' else 'SRT')+' 字幕 · '+('正文版本' if resource.get('preferred') else '目录版本'))
        elif role=='course_intro_poster':
            with target.open('rb') as stream:raw=stream.read(32)
            if not (raw.startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n',b'GIF87a',b'GIF89a',b'BM')) or raw[:4]==b'RIFF'):raise ValueError('Introduction poster is not a recognized source raster image')
            record.update(validate_image(target))
            record['label']='课程介绍封面'
        elif role=='attachment':record['label']='来源附件'
        else:
            kind='video' if role=='course_intro_video' else 'audio'
            try:verification=validate(target,kind)
            except (ValueError,subprocess.TimeoutExpired) as failure:
                if record.get('hls'):raise
                with target.open('rb') as stream:raw=stream.read(512).lstrip().lower()
                if raw.startswith((b'<html',b'<!doctype',b'{',b'[')):raise ValueError('Source returned a non-media response; not an encrypted source')
                record['source_probe_or_decode_error']=public_error(failure)
                if not resource.get('source_declares_drm') and not re.search(r'(?:/|[_.-])drm(?:/|[_.-])',resource.get('_url') or '',re.I):
                    record['unplayable_source_original']={**file_record(root,target),'protection_status':'unknown; no protected-source assumption or derivation allowed'}
                    raise ValueError('Source media failed validation without observed protection evidence; original retained')
                protected=safe(root,role_dir+'/encrypted/'+token+'.'+ext+'.enc');protected.parent.mkdir(parents=True,exist_ok=True);target.replace(protected)
                record['encrypted_source']={**file_record(root,protected),'protection_status':'source_not_directly_playable_no_decryption_attempted'}
                if kind=='video':raise ValueError('Protected introduction video requires its own verified adapter; original retained')
                video=verified_video(root,resource,course,completed);video_path=safe(root,video['path'])
                validate(video_path,'video')
                # A protected .mp3 source may contain no directly usable MP3. Its
                # derived AAC file receives the actual M4A container extension.
                target=target.with_suffix('.m4a')
                copied=run(['ffmpeg','-nostdin','-v','error','-y','-i',str(video_path),'-map','0:a','-vn','-c','copy','-movflags','+faststart',str(target)])
                if copied['exit_code']:raise ValueError('Lossless video audio copy failed: '+copied['stderr'])
                before,after=packet_hash(video_path),packet_hash(target)
                if before!=after:raise ValueError('Copied video audio compressed packets differ')
                if not checked(root,video):raise ValueError('Verified video changed during lossless audio copy')
                record.update(output_origin='derived_from_verified_video',derived_from_verified_video={**file_record(root,video_path),'source_media_id':resource['source_media_id'],'codec_operation':'copy; no reencoding','all_audio_packets_exact_match':True,'input_audio_packet_hashes':before,'output_audio_packet_hashes':after,'source_audio_decryption_claimed':False})
                verification=validate(target,'audio')
            else:record.setdefault('output_origin','original_source_bytes')
            record.update(file_record(root,target));record.update(verification)
            declared=resource.get('duration')
            if declared is not None:
                difference=abs(float(verification['duration'])-float(declared))
                record.update(source_declared_duration_seconds=declared,source_duration_difference_seconds=round(difference,6),duration_warning=difference>3)
                if difference>3:record['source_warning']='Preserved source audio/video duration differs from the source declaration by over 3 seconds; no trimming or reencoding was performed.'
            if role=='course_intro_video':
                actual=max(s.get('height',0) for s in verification['ffprobe']['streams'] if s.get('codec_type')=='video')
                if actual<int(resource['resolution']):raise ValueError('Introduction video has less resolution than declared source')
            record['label']={'course_intro_video':'课程介绍视频','course_intro_audio':'课程介绍音频','video_audio_component':'视频音轨（无损复制）' if record['output_origin']=='derived_from_verified_video' else '视频音轨'}[role]
        record.update(status='complete',inventory_resource_ids=[rid])
    except Exception as error:record.update(status='failed',error=public_error(error))
    record['finished_at_utc']=now();return record

def apply_report(root,report):
    root=Path(root).resolve()
    if report.get('status')!='passed' or any(r.get('status')!='complete' for r in report.get('records',[])):raise ValueError('All expected supplemental resources must verify before apply')
    with course_lock(root):
        path=root/'course.json';before=digest(path);course=read(path);source=safe(root,report['source_archive_path'])
        if digest(source)!=report['source_archive_sha256']:raise ValueError('Authorized source changed before supplemental merge')
        if str(course.get('course_enid') or '')!=str(report['course_enid']):raise ValueError('Supplemental source course identity differs')
        expected={r['resource_id']:r for r in load_inventory(root,report['source_archive_path'])['resources'] if r['role'] in ROLES}
        actual={r['resource_id']:r for r in report['records']}
        if len(actual)!=len(report['records']) or set(expected)!=set(actual):raise ValueError('Supplemental report is not the full current source-driven resource set')
        for rid,resource in expected.items():
            if any(actual[rid].get(key)!=resource.get(key) for key in ('role','source_media_id','lesson_id','video_index','source_url_sha256')):raise ValueError('Supplemental record source identity differs')
        lessons={str(l['id']):l for l in course['lessons']}
        # Replace only this producer's known fields, preserving all ordinary aliases.
        for lesson in lessons.values():
            lesson.pop('subtitles',None);lesson.pop('video_audio_components',None)
        course.pop('course_intro_subtitles',None)
        for field in ('course_intro_video','course_intro_audio'):
            if (course.get(field) or {}).get('archive_report')=='raw/course-extras-report.json':course.pop(field,None)
        images=read(root/'assets/images/manifest.json',[]);attachments=read(root/'assets/attachments/manifest.json',[])
        images=images.get('images',list(images.values())) if isinstance(images,dict) else images
        attachments=attachments.get('attachments',[]) if isinstance(attachments,dict) else attachments
        for row in report['records']:
            if not checked(root,row):raise ValueError('Verified supplemental file changed')
            if row.get('encrypted_source') and not checked(root,row['encrypted_source']):raise ValueError('Supplemental protected original changed')
            item={k:v for k,v in row.items() if k not in {'started_at_utc','finished_at_utc','source_field_paths','required'}};item['archive_report']='raw/course-extras-report.json'
            role=row['role'];lesson=lessons.get(str(row.get('lesson_id')))
            if role=='subtitle':
                if lesson is not None:lesson.setdefault('subtitles',[]).append(item)
                else:course.setdefault('course_intro_subtitles',[]).append(item)
            elif role=='video_audio_component':
                if lesson is None:raise ValueError('Video audio component lesson absent')
                lesson.setdefault('video_audio_components',[]).append(item)
            elif role in {'course_intro_video','course_intro_audio'}:course[role]=item
            elif role=='course_intro_poster':
                value=source_value(read(source),row['source_field_paths'][0]);images=[x for x in images if x.get('source_url')!=value];images.append({'source_url':value,**file_record(root,safe(root,row['path'])),'roles':['course_intro_poster']})
                course.setdefault('images',{})['course_intro_poster']=row['path']
            elif role=='attachment':
                value=source_value(read(source),row['source_field_paths'][0]);attachments=[x for x in attachments if x.get('source_url')!=value];attachments.append({**item,'source_url':value})
        if course.get('course_intro_video'):
            if course.get('images',{}).get('course_intro_poster'):course['course_intro_video']['poster']=course['images']['course_intro_poster']
            course['course_intro_video']['subtitles']=course.get('course_intro_subtitles',[])
        atomic_json(root/'assets/images/manifest.json',images);atomic_json(root/'assets/attachments/manifest.json',{'schema_version':1,'attachments':attachments})
        compare_and_write_manifest(root,before,course)

def source_value(source,path):
    node=source
    for key in path:
        node=node[key]
        if key=='content' and isinstance(node,str):node=json.loads(node)
    return node

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--input',default='raw/authorized-course.json');parser.add_argument('--apply',action='store_true');args=parser.parse_args();root=args.root.resolve();report_path=root/'raw/course-extras-report.json'
    if args.apply:
        report=read(report_path);apply_report(root,report);print(json.dumps({'applied':True,'status':'passed','resources':len(report['records'])}));return 0
    inventory=load_inventory(root,args.input)
    if inventory['issues']:raise ValueError('Source inventory requires explicit adaptation: '+json.dumps(inventory['issues']))
    public=public_inventory(inventory);atomic_json(root/'raw/media-inventory.json',public)
    previous={r['resource_id']:r for r in (read(report_path,{}) or {}).get('records',[])};course=read(root/'course.json',{});records=[]
    ordered=sorted((r for r in inventory['resources'] if r['role'] in ROLES),key=lambda r:(0 if r['role']=='course_intro_video' else 1,r['resource_id']))
    report={'schema_version':1,'started_at_utc':now(),'course_enid':inventory['course_enid'],'source_archive_path':inventory['source_archive_path'],'source_archive_sha256':inventory['source_archive_sha256'],'records':records,'status':'running'}
    for resource in ordered:
        records.append(archive_resource(root,resource,course,records,previous.get(resource['resource_id'])));atomic_json(report_path,report)
    report.update(finished_at_utc=now(),status='passed' if all(r['status']=='complete' for r in records) else 'failed',summary={'expected':len(ordered),'completed':sum(r['status']=='complete' for r in records),'failed':sum(r['status']!='complete' for r in records)})
    atomic_json(report_path,report);print(json.dumps({'status':report['status'],'summary':report['summary']},ensure_ascii=False));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
