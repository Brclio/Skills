#!/usr/bin/env python3
"""Independently audit a local Dedao course, its source fidelity and offline reader.

No network requests or course writes. Existing full-decode evidence is accepted
only when the current local media hash still matches that evidence. --probe-media
reruns FFprobe; --decode additionally repeats the full media decode.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote,urlsplit

from build_site import markdown

ROOT=Path(__file__).resolve().parents[1]
IMAGE_FIELDS={'avatar','cover','cover_img','coverImg','poster','index_img','indexImg','icon','image','img','logo','article_logo','logo_iphonex','square_img','outline_img','player_img','lecturer_avatar','index_img_applet','special_logo','logo_for_lecture'}
SUPPORTED={'paragraph','salutation','tip','date','wish','header','elite','list','image','inline-image','blockquote','hr','audio','label-group','code-block'}
FILE_SNAPSHOTS={}
HASH_CACHE={}
CHANGED_FILES=set()
EXCLUDED_FILES=set()

def remember(path,digest,size):
    path=path.resolve()
    if path in EXCLUDED_FILES or 'finalization-audits' in path.parts:return
    value={'path':path.relative_to(ROOT).as_posix(),'sha256':digest,'bytes':size}
    previous=FILE_SNAPSHOTS.get(value['path'])
    if previous and previous!=value:CHANGED_FILES.add(value['path'])
    FILE_SNAPSHOTS[value['path']]=value

def read_bytes(path):
    value=path.read_bytes();remember(path,hashlib.sha256(value).hexdigest(),len(value));return value

def read_text(path,encoding='utf-8'):return read_bytes(path).decode(encoding)

def load(path,default=None):
    if not path.is_file():return default
    return json.loads(read_text(path))

def sha(path):
    path=path.resolve();stat=path.stat();marker=(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
    cached=HASH_CACHE.get(path)
    if cached and cached[0]==marker:return cached[1]
    value=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk);size+=len(chunk)
    result=value.hexdigest();remember(path,result,size);HASH_CACHE[path]=(marker,result);return result

def canonical(text):return re.sub(r'\s+','',html.unescape(text))

def walk(value):
    yield value
    if isinstance(value,list):
        for child in value:yield from walk(child)
    elif isinstance(value,dict):
        for child in value.values():yield from walk(child)

class Parsed(HTMLParser):
    def __init__(self,value):
        super().__init__(convert_charrefs=True);self.text=[];self.resources=[];self.links=[];self.scripts=[];self.course_data=None;self.skip=[];self._payload=[];self.feed(value)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':
            self.scripts.append(attrs)
            if attrs.get('id')=='course-data':self._payload=[]
            self.skip.append(tag)
        elif tag in {'style','template'}:self.skip.append(tag)
        if tag in {'img','audio','video','source','track','script','iframe','embed'} and attrs.get('src'):self.resources.append((tag+'.src',attrs['src']))
        if attrs.get('poster'):self.resources.append((tag+'.poster',attrs['poster']))
        if tag=='link' and attrs.get('href'):self.resources.append(('link.href',attrs['href']))
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
        if attrs.get('srcset'):
            for part in attrs['srcset'].split(','):self.resources.append(('srcset',part.strip().split(' ')[0]))
    def handle_endtag(self,tag):
        if tag=='script' and self.skip and self.skip[-1]=='script' and self._payload:
            try:self.course_data=json.loads(''.join(self._payload))
            except ValueError:pass
        if self.skip and self.skip[-1]==tag:self.skip.pop()
    def handle_data(self,value):
        if self.skip:
            if self.skip[-1]=='script':self._payload.append(value)
        else:self.text.append(value)

def inline(value,unknown):
    if isinstance(value,list):return ''.join(inline(child,unknown) for child in value)
    if isinstance(value,str):return value
    if not isinstance(value,dict):return ''
    kind=value.get('type')
    if kind=='text':
        field=value.get('text',{})
        return field if isinstance(field,str) else str(field.get('content',''))
    if kind in {'image','inline-image'}:return str(value.get('legend',''))
    if kind not in {'link','hyperlink',None}:unknown.append({'kind':'inline','type':kind})
    return inline(value.get('contents',value.get('content','')),unknown)

def expected_text(blocks,unknown):
    text=[]
    for block in blocks:
        kind=block.get('type')
        if kind not in SUPPORTED:unknown.append({'kind':'block','type':kind})
        if kind=='audio':value=str(block.get('title',''))+str(block.get('desc',''))
        elif kind in {'image','inline-image'}:value=str(block.get('legend',''))
        elif kind=='hr':value=''
        elif kind=='label-group':value=' '.join(block.get('labels',[]))
        elif kind=='code-block':value=str(block.get('code',block.get('text','')))
        else:
            value=inline(block.get('contents',[]),unknown)
            if kind=='blockquote':
                if block.get('subtype')==2:
                    answer=block.get('answer',{});value=str(answer.get('title',''))+str(answer.get('askName',''))+value
                elif block.get('subtype')==1:value=str(block.get('cite',{}).get('author',{}).get('name',''))+value
        text.append(value)
    return ''.join(text)

def image_urls(value):
    found=set()
    for node in walk(value):
        if not isinstance(node,dict):continue
        for key,child in node.items():
            if isinstance(child,str) and child.startswith(('http://','https://')) and (key in IMAGE_FIELDS or key=='url' and node.get('type') in {'image','inline-image'}):found.add(child)
    return found

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',default='raw/authorized-course.json');parser.add_argument('--output',default='raw/archive-audit.json');parser.add_argument('--decode',action='store_true');parser.add_argument('--probe-media',action='store_true',help='Repeat FFprobe instead of using matching prior evidence');args=parser.parse_args()
    EXCLUDED_FILES.add((ROOT/args.output).resolve())
    errors=[];warnings=[];summary=Counter();resource_checks=0;unknown=[];media_checks=[];lesson_checks=[]
    def fail(kind,**data):errors.append({'kind':kind,**data})
    def local(value,base=ROOT):
        if not isinstance(value,str) or not value:return None
        parts=urlsplit(value)
        if parts.scheme or parts.netloc:return None
        target=(base/unquote(parts.path)).resolve()
        return target if target.is_relative_to(ROOT) else None
    def refs(value,label,base=ROOT):
        nonlocal resource_checks
        parsed=Parsed(value)
        for role,src in parsed.resources:
            resource_checks+=1
            if src.startswith('data:image/'):continue
            path=local(src,base)
            if not path:fail('nonlocal_resource',source=label,role=role,value=src[:150])
            elif not path.is_file() or not path.stat().st_size:fail('missing_resource',source=label,role=role,path=str(path.relative_to(ROOT)))
            else:sha(path)
        return parsed
    input_snapshots={}
    for role,value in [('manifest','course.json'),('source_archive',args.archive),('source_catalog','raw/public/catalog.json'),('course_config','course-config.json')]:
        path=local(value)
        if path and path.is_file():
            content=read_bytes(path)
            input_snapshots[role]={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(content).hexdigest()}
        elif role!='course_config':
            fail('missing_audit_input',role=role,path=value)
    archive=load(ROOT/args.archive,{})
    course=load(ROOT/'course.json',{})
    catalog=load(ROOT/'raw/public/catalog.json',{})
    expected=[str(row.get('id_str') or row['id']) for section in catalog.get('chapter_list',[]) for row in section.get('article_list',[])]
    count=int(catalog.get('class_info',{}).get('current_article_count',0))
    actual=[str(row['id']) for row in course.get('lessons',[])];exported=[str(row['id']) for row in archive.get('lessons',[])]
    summary.update(expected_lessons=count,catalog_lessons=len(expected),exported_full_bodies=len(exported),local_lesson_entries=len(actual))
    if count<=0 or len(expected)!=count or len(set(expected))!=count:fail('source_catalog_count_mismatch')
    if actual!=expected or exported!=expected:fail('lesson_identity_or_order_mismatch')
    if course.get('expected_lesson_count')!=count:fail('manifest_count_mismatch')
    if len({archive.get('course',{}).get('enid'),course.get('course_enid'),catalog.get('class_info',{}).get('enid')})!=1:fail('course_identity_mismatch')
    if not archive.get('complete',archive.get('summary',{}).get('complete')) or archive.get('errors'):fail('source_export_incomplete')
    local_lessons={str(row['id']):row for row in course.get('lessons',[])}
    all_images=image_urls(archive.get('course',{}));expected_audio={};expected_video={}
    for source in archive.get('lessons',[]):
        lid=str(source['id']);lesson=local_lessons.get(lid)
        if lesson is None:continue
        blocks=json.loads(source['body']['content']);raw_content=ROOT/'raw/lessons'/f'{lid}.content.json'
        exact=raw_content.is_file() and read_bytes(raw_content)==source['body']['content'].encode('utf-8')
        if not exact:fail('raw_content_bytes_mismatch',lesson_id=lid)
        summary['raw_content_bytes_verified']+=exact
        saved_body=load(ROOT/'raw/authorized'/f'{lid}.body.json')
        if saved_body!=source['body']:fail('raw_body_object_mismatch',lesson_id=lid)
        saved_info=load(ROOT/'raw/authorized'/f'{lid}.info.json',{})
        if saved_info.get('c',saved_info)!=source['info']:fail('raw_info_object_mismatch',lesson_id=lid)
        expected_prose=canonical(expected_text(blocks,unknown));record={'lesson_id':lid,'raw_content_bytes_verified':exact,'characters_without_whitespace':len(expected_prose)}
        for kind,key in [('html','html_path'),('markdown','markdown_path')]:
            path=local(lesson.get(key))
            if not path or not path.is_file():fail('missing_lesson_source',lesson_id=lid,source=kind);continue
            text=read_text(path)
            if kind=='markdown':
                text=re.sub(r'^---\n.*?\n---\n','',text,count=1,flags=re.S);text=re.sub(r'^\s*# [^\n]+\n','',text,count=1);text=markdown(text)
            parsed=refs(text,kind+'-'+lid,path.parent);valid=canonical(''.join(parsed.text))==expected_prose
            record[kind+'_text_verified']=valid;summary[kind+'_text_verified']+=valid
            if not valid:fail(kind+'_text_mismatch',lesson_id=lid)
        article=source['info'].get('article_info',{})
        aliases={str(node.get('aliasId') or node.get('alias_id')) for node in walk(blocks) if isinstance(node,dict) and node.get('type')=='audio' and (node.get('aliasId') or node.get('alias_id'))}
        aliases.update(str(alias) for alias in article.get('audio_alias_ids',[]) if alias)
        main_audio=article.get('audio') or {}
        if main_audio.get('alias_id'):aliases.add(str(main_audio['alias_id']))
        expected_audio[lid]=aliases
        tracks=lesson.get('audio',[]) or [];saved_aliases={str(row.get('audio_alias_id') or row.get('alias_id') or '') for row in tracks}
        if saved_aliases!=aliases or len(tracks)!=len(aliases):fail('audio_alias_mapping_mismatch',lesson_id=lid,expected=sorted(aliases),saved=sorted(saved_aliases))
        source_videos=article.get('video',[]) or [];expected_video[lid]=source_videos
        if len(lesson.get('video',[]) or [])!=len(source_videos):fail('video_count_mismatch',lesson_id=lid,expected=len(source_videos),saved=len(lesson.get('video',[]) or []))
        all_images.update(image_urls(blocks));all_images.update(image_urls(source['info']));lesson_checks.append(record)
    if unknown:fail('unknown_source_nodes',nodes=unknown)
    image_manifest=load(ROOT/'assets/images/manifest.json',[]);image_map={row['source_url']:row for row in image_manifest}
    for url in sorted(all_images):
        row=image_map.get(url);path=local(row.get('path')) if row else None
        valid=bool(path and path.is_file() and path.stat().st_size==row.get('bytes') and sha(path)==row.get('sha256'))
        summary['source_images_verified']+=valid
        if not valid:fail('source_image_missing_or_hash_mismatch',url_sha256=hashlib.sha256(url.encode()).hexdigest())
    summary['source_images_expected']=len(all_images)
    # Records may live in a manifest or in per-media reports; keep only rows
    # bearing a complete media hash and full-decode evidence.
    evidence=defaultdict(list)
    video_backup_report=load(ROOT/'raw/video-archive-report.json',{})
    video_source_report=load(ROOT/'raw/web-video-archive-report.json',{})
    video_source_rows=video_source_report.get('videos',[])
    web_media=load(ROOT/'raw/authorized-web-media.json',{})
    if not web_media.get('complete') or web_media.get('errors'):fail('authorized_web_media_export_incomplete')
    web_by_lesson={str(row.get('lesson_id')):row for row in web_media.get('videos',[])}
    if len(video_source_rows)!=sum(len(row) for row in expected_video.values()):fail('web_video_report_count_mismatch')
    for row in video_source_rows:
        source=web_by_lesson.get(str(row.get('lesson_id')),{});formats=[form for track in source.get('media',{}).get('tracks',[]) for form in track.get('formats',[]) if form.get('type')=='video' and form.get('format')=='m3u8' and form.get('url')]
        largest=max([int(form.get('resolution',0)) for form in formats],default=0)
        selected=[form for form in formats if form.get('url')==row.get('source_url') and int(form.get('resolution',0))==int(row.get('resolution_selected') or 0)]
        if not selected or int(row.get('resolution_selected') or 0)!=largest or str(row.get('source_media_id'))!=str(source.get('source_media_id')):
            fail('web_video_source_identity_or_resolution_mismatch',lesson_id=str(row.get('lesson_id')))
        if row.get('status')=='complete' and (not row.get('all_streams_decoded') or not row.get('video_stream_count') or not row.get('audio_stream_count') or row.get('conversion')!='lossless_remux'):
            fail('web_video_stream_decode_or_remux_evidence_inconsistent',lesson_id=str(row.get('lesson_id')))
    video_source_lookup={(str(row.get('lesson_id')),str(row.get('source_media_id'))):row for row in video_source_rows}
    for row in video_backup_report.get('videos',[]):
        path=local(row.get('path'))
        valid=bool(path and path.is_file() and path.stat().st_size==row.get('bytes') and sha(path)==row.get('sha256'))
        summary['historical_video_backups_verified']+=valid
        if not valid:fail('historical_video_backup_hash_mismatch',lesson_id=str(row.get('lesson_id')),path=row.get('path'))
    for lid,source_rows in expected_video.items():
        for source_row in source_rows:
            source_id=str(source_row.get('dd_media_id_str') or source_row.get('dd_media_id') or '')
            row=video_source_lookup.get((lid,source_id))
            path=local(row.get('path')) if row else None
            valid=bool(row and row.get('download_complete') and path and path.is_file() and path.stat().st_size==row.get('bytes') and sha(path)==row.get('sha256'))
            summary['video_source_files_verified']+=valid
            if not valid:fail('video_source_file_unverified',lesson_id=lid,source_media_id=source_id)
            elif not row.get('playable') or row.get('decode',{}).get('returncode')!=0:
                summary['video_source_saved_unplayable']+=1
                fail('video_source_saved_unplayable',lesson_id=lid,source_media_id=source_id,path=row.get('path'),source_declares_drm=row.get('source_declares_drm'),decode_returncode=row.get('decode',{}).get('returncode'))
    for row in video_source_rows:
        hls=row.get('hls',{});playlist=local(hls.get('local_playlist_path'))
        if not playlist or not playlist.is_file() or sha(playlist)!=hls.get('local_playlist_sha256'):
            fail('local_hls_playlist_missing_or_hash_mismatch',lesson_id=str(row.get('lesson_id')));continue
        assets_path=local(hls.get('assets_manifest_path'));assets=load(assets_path,[]) if assets_path else []
        if not assets:fail('missing_local_hls_assets_manifest',lesson_id=str(row.get('lesson_id')))
        for asset in assets:
            path=local(asset.get('path'));valid=bool(path and path.is_file() and path.stat().st_size==asset.get('bytes') and sha(path)==asset.get('sha256'))
            summary['hls_assets_verified']+=valid
            if asset.get('kind')=='segment':summary['hls_segments_verified']+=valid
            if not valid:fail('local_hls_asset_hash_mismatch',lesson_id=str(row.get('lesson_id')),path=asset.get('path'))
        lines=read_text(playlist,encoding='utf-8-sig').splitlines()
        segment_refs=[]
        for line in lines:
            refs_in_line=re.findall(r'URI="([^"]+)"',line) if line.startswith('#') else ([line.strip()] if line.strip() else [])
            for value in refs_in_line:
                target=local(value,playlist.parent)
                if not target or not target.is_file():fail('nonlocal_or_missing_hls_reference',lesson_id=str(row.get('lesson_id')),value=value[:150])
                if not line.startswith('#'):segment_refs.append(value)
        if len(segment_refs)!=hls.get('segments') or '#EXT-X-ENDLIST' not in lines:fail('local_hls_segment_count_or_end_marker_mismatch',lesson_id=str(row.get('lesson_id')))
    for report_path in (ROOT/'raw').rglob('*.json'):
        if report_path.resolve() in EXCLUDED_FILES or 'finalization-audits' in report_path.parts or report_path.name.endswith('.info.json') or report_path.name.endswith('.body.json') or 'lessons' in report_path.parts:continue
        try:saved=load(report_path,{})
        except (ValueError,OSError):continue
        for node in walk(saved):
            if isinstance(node,dict) and isinstance(node.get('path'),str) and node['path'].startswith(('assets/audio/','assets/video/')) and node.get('sha256'):
                evidence[node['path']].append((node,str(report_path.relative_to(ROOT))))
    verified_paths={}
    for lesson in course.get('lessons',[]):
        lid=str(lesson['id'])
        for kind in ('audio','video'):
            for track in lesson.get(kind,[]) or []:
                value=track.get('path','');path=local(value)
                if not path or not path.is_file() or not path.stat().st_size:fail('missing_local_media',lesson_id=lid,media_kind=kind,path=value);continue
                if value in verified_paths:summary[kind+'_track_references_verified']+=verified_paths[value];continue
                digest=sha(path)
                matches=[(row,where) for row,where in evidence.get(value,[]) if row.get('sha256')==digest and row.get('bytes')==path.stat().st_size and row.get('full_decode_exit_code',row.get('decode',{}).get('returncode'))==0 and row.get('status') in {'complete','decrypted_verified'}]
                valid=bool(matches)
                if not matches:fail('missing_matching_full_decode_evidence',lesson_id=lid,media_kind=kind,path=value)
                if args.probe_media or args.decode:
                    probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels','-of','json',str(path)],capture_output=True,text=True,timeout=60)
                    metadata=json.loads(probe.stdout) if probe.returncode==0 else {};probe_origin='independent_ffprobe'
                else:
                    record=matches[0][0] if matches else {}
                    metadata=record.get('ffprobe') or record.get('probe',{}).get('data') or {};probe_origin='matching_full_decode_report'
                streams=metadata.get('streams',[])
                required='video' if kind=='video' else 'audio'
                stream_valid=any(row.get('codec_type')==required or kind=='audio' and row.get('codec_name') and row.get('sample_rate') and row.get('channels') for row in streams)
                duration=float(metadata.get('format',{}).get('duration',0))
                if kind=='video':
                    stream_valid=stream_valid and any(row.get('codec_type')=='audio' for row in streams)
                    selected_resolution=int(matches[0][0].get('resolution_selected') or 0) if matches else 0
                    stream_valid=stream_valid and max([int(row.get('height',0)) for row in streams if row.get('codec_type')=='video'],default=0)>=selected_resolution
                if not stream_valid or duration<=0:valid=False;fail('invalid_media_probe',path=value,media_kind=kind)
                expected_duration=(matches[0][0].get('expected_duration_seconds') or matches[0][0].get('expected_duration') or matches[0][0].get('source_duration')) if matches else None
                if expected_duration and abs(duration-float(expected_duration))>max(3,float(expected_duration)*.02):valid=False;fail('media_duration_mismatch',path=value)
                if args.decode:
                    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(path),'-f','null','-'],capture_output=True,text=True,timeout=600)
                    if result.returncode:valid=False;fail('full_decode_failed',path=value)
                verified_paths[value]=valid;summary[kind+'_media_verified']+=valid;summary[kind+'_track_references_verified']+=valid
                media_checks.append({'path':value,'kind':kind,'bytes':path.stat().st_size,'sha256':digest,'duration_seconds':duration,'status':'verified' if valid else 'failed','full_decode_evidence_reports':list(dict.fromkeys(where for _,where in matches)),'probe_metadata':metadata,'probe_origin':probe_origin,'full_decode_repeated':args.decode})
    web_by_lid={str(row.get('lesson_id')):row for row in video_source_rows}
    decrypted_report=load(ROOT/'raw/legacy-video-decryption-report.json',{})
    decrypted_by_lid={str(row.get('lesson_id')):row for row in decrypted_report.get('videos',[])}
    using_decrypted_defaults=False
    for lesson in course.get('lessons',[]):
        lid=str(lesson['id']);tracks=lesson.get('video',[]) or []
        if any(track.get('path','').startswith('assets/video/decrypted/') for track in tracks):
            using_decrypted_defaults=True
            record=decrypted_by_lid.get(lid,{})
            if len(tracks)!=1 or tracks[0].get('path')!=record.get('path') or record.get('status')!='decrypted_verified':
                fail('decrypted_default_media_mapping_mismatch',lesson_id=lid)
            else:summary['decrypted_default_videos_verified']+=1
        for alternative in lesson.get('video_web_alternatives',[]) or []:
            record=web_by_lid.get(lid,{})
            path=local(alternative.get('path'))
            valid=bool(path and path.is_file() and alternative.get('path')==record.get('path') and path.stat().st_size==record.get('bytes') and sha(path)==record.get('sha256') and record.get('status')=='complete' and record.get('decode',{}).get('returncode')==0)
            summary['retained_web_video_alternatives_verified']+=valid
            if not valid:fail('retained_web_video_alternative_invalid',lesson_id=lid,path=alternative.get('path'))
    if using_decrypted_defaults:
        expected_videos=sum(len(row) for row in expected_video.values())
        if summary['decrypted_default_videos_verified']!=expected_videos or summary['retained_web_video_alternatives_verified']!=expected_videos:
            fail('decrypted_default_or_web_alternative_count_mismatch')
        review=load(ROOT/'raw/independent-legacy-decryption-review.json',{})
        if review.get('status')!='passed' or review.get('summary',{}).get('passed_videos')!=expected_videos or review.get('summary',{}).get('independent_full_decode_samples')!=min(3,expected_videos):
            fail('missing_complete_independent_legacy_decryption_review')
        for record in review.get('videos',[]):
            live=decrypted_by_lid.get(str(record.get('lesson_id')),{})
            if record.get('output_sha256')!=live.get('sha256') or record.get('source_sha256')!=live.get('source_sha256'):
                fail('independent_legacy_review_hash_binding_mismatch',lesson_id=str(record.get('lesson_id')))
    summary['expected_audio_aliases']=len(set().union(*expected_audio.values())) if expected_audio else 0
    summary['expected_video_entries']=sum(len(row) for row in expected_video.values())
    index=ROOT/'index.html';embedded=None
    if not index.is_file():fail('missing_offline_index')
    else:
        text=read_text(index);parsed=refs(text,'index.html');embedded=parsed.course_data
        if not embedded:fail('missing_embedded_course_data')
        else:
            rows=embedded.get('lessons',[])
            if [str(row['id']) for row in rows]!=expected:fail('website_lesson_identity_or_order_mismatch')
            for row in rows:
                lid=str(row['id']);source=next((item for item in archive['lessons'] if str(item['id'])==lid),None)
                if source:
                    want=canonical(expected_text(json.loads(source['body']['content']),[]));parsed_body=refs(row.get('html',''),'website-'+lid)
                    same=canonical(''.join(parsed_body.text))==want;summary['website_bodies_verified']+=same
                    if not same:fail('website_text_mismatch',lesson_id=lid)
                for kind in ('audio','video'):
                    actual_paths=[track.get('path') for track in row.get(kind,[])];wanted_paths=[track.get('path') for track in local_lessons[lid].get(kind,[])]
                    if actual_paths!=wanted_paths:fail('website_media_mapping_mismatch',lesson_id=lid,media_kind=kind)
                    for track in row.get(kind,[]):refs('<'+kind+' src="'+html.escape(track['path'],quote=True)+'"></'+kind+'>','website-'+kind+'-'+lid)
            if embedded.get('cover_path'):refs('<img src="'+html.escape(embedded['cover_path'],quote=True)+'">','website-cover')
            if embedded.get('issues'):fail('website_build_issues',issues=embedded['issues'])
        if "connect-src 'none'" not in text:fail('website_missing_offline_connect_policy')
    if (ROOT/'course-info.html').is_file():refs(read_text(ROOT/'course-info.html'),'course-info.html')
    else:fail('missing_course_information_page')
    if (ROOT/'resources.html').is_file():
        resources_page=refs(read_text(ROOT/'resources.html'),'resources.html')
        for href in resources_page.links:
            if urlsplit(href).scheme or urlsplit(href).netloc or href.startswith('#'):continue
            target=local(href)
            if not target or not target.is_file():fail('resource_index_missing_link',path=href)
            else:sha(target)
    else:fail('missing_resource_index')
    resource_markdown=ROOT/'content/本地资源.md'
    if resource_markdown.is_file():
        for href in re.findall(r'(?<!!)\[[^\]]*\]\(([^\n)]+)\)',read_text(resource_markdown)):
            if urlsplit(href).scheme or urlsplit(href).netloc or href.startswith('#'):continue
            target=local(href,resource_markdown.parent)
            if not target or not target.is_file():fail('resource_markdown_missing_link',path=href)
            else:sha(target)
    else:fail('missing_resource_markdown')
    for path in (ROOT/'web').glob('*.css'):
        text=read_text(path)
        for url in re.findall(r'url\(\s*[\'"]?([^\)\'"\s]+)',text):
            if url.startswith('data:'):continue
            target=local(url,path.parent)
            if not target or not target.is_file():fail('nonlocal_or_missing_css_resource',path=str(path.relative_to(ROOT)))
            else:sha(target)
        if re.search(r'@import\s',text):fail('css_import_requires_review',path=str(path.relative_to(ROOT)))
    for path in (ROOT/'web').glob('*.js'):
        if re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(',read_text(path)):fail('reader_network_api_present',path=str(path.relative_to(ROOT)))
    attachments=load(ROOT/'assets/attachments/manifest.json',{}).get('attachments',[])
    for row in attachments:
        if row.get('status')!='complete':warnings.append({'kind':'optional_external_reference_unavailable','source_url':row.get('source_url')});continue
        path=local(row.get('path'));valid=bool(path and path.is_file() and sha(path)==row.get('sha256') and path.stat().st_size==row.get('bytes'))
        summary['reference_pdfs_verified']+=valid
        if not valid:fail('reference_pdf_hash_mismatch',path=row.get('path'))
    for role,snapshot in input_snapshots.items():
        path=local(snapshot['path'])
        if not path or not path.is_file() or sha(path)!=snapshot['sha256']:fail('input_changed_during_audit',role=role)
    if CHANGED_FILES:fail('files_changed_during_audit',paths=sorted(CHANGED_FILES))
    summary['resource_references_checked']=resource_checks;summary['errors']=len(errors);summary['warnings']=len(warnings)
    report={'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed' if not errors else 'failed','archive_status':'complete' if not errors else 'partial','method':{'text':'Independently extract source contents and quote metadata, compare characters in order after whitespace normalization. Retain exact UTF-8 original content bytes.','media':'Current file hashes and sizes must match full-decode reports with zero exit status; matching probe metadata is cross-checked. Optional flags repeat FFprobe or full decode. Source HLS assets and local playlists are independently hash-checked; historical encrypted source backups are retained separately.','offline':'Check HTML/embedded lesson bodies/CSS/media references, local assets and reader network APIs; external citation links are not reader media dependencies.'},'summary':dict(summary),'source_archive':{'path':args.archive,'sha256':sha(ROOT/args.archive)},'lessons':lesson_checks,'media':media_checks,'errors':errors,'warnings':warnings}
    report.update({'manifest_snapshot_sha256':input_snapshots.get('manifest',{}).get('sha256'),'source_archive':input_snapshots.get('source_archive',{}),'source_catalog':input_snapshots.get('source_catalog',{}),'input_snapshots':input_snapshots,'audited_files':[FILE_SNAPSHOTS[key] for key in sorted(FILE_SNAPSHOTS)],'course_identity':{'course_enid':course.get('course_enid'),'source_url':course.get('source_url'),'lesson_ids':actual}})
    output=ROOT/args.output;output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'archive_status':report['archive_status'],'summary':report['summary'],'output':args.output},ensure_ascii=False))
    return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(main())
