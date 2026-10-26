#!/usr/bin/env python3
"""Discover expected course assets from source, independently of downloaded files.

Private ``_url`` members are only execution inputs. Public inventories contain
URL fingerprints and exact source-field paths, never account credentials.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_FIELDS = {'archive_status', 'archive_summary', 'archive_finalization'}
IMAGE_FIELDS = {'index_img','index_img_applet','indexImg','special_logo','logo','logo_for_lecture','logo_iphonex','square_img','outline_img','player_img','lecturer_avatar','cover','cover_img','poster'}

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()

def content_manifest_digest(course):
    return hashlib.sha256(canonical({k:v for k,v in course.items() if k not in LIFECYCLE_FIELDS})).hexdigest()

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def read(path,default=None):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else default

def public_inventory(value):
    if isinstance(value,list):return [public_inventory(v) for v in value]
    if isinstance(value,dict):return {k:public_inventory(v) for k,v in value.items() if not k.startswith('_')}
    return value

def is_url(value):
    return isinstance(value,str) and urlsplit(value).scheme in {'http','https'} and bool(urlsplit(value).netloc)

def highest_video(video):
    candidates=[(int(k.split('_')[1]),k,v) for k,v in video.items() if re.fullmatch(r'bitrate_\d+',k) and is_url(v)]
    return max(candidates,default=(None,None,None))

def decode_body(row):
    value=row.get('body',{}).get('content',[])
    return json.loads(value) if isinstance(value,str) else value

def walk(value,path=()):
    yield path,value
    if isinstance(value,dict):
        for k,v in value.items():yield from walk(v,path+(k,))
    elif isinstance(value,list):
        for k,v in enumerate(value):yield from walk(v,path+(k,))

def discover_inventory(source,extra_audio=None,web_media=None):
    """Return required resources even when none have been downloaded yet."""
    resources={};issues=[];course_id=str(source.get('course',{}).get('enid') or '')
    web_resolutions={}
    for entry in (web_media or {}).get('videos',[]):
        key=(str(entry.get('lesson_id')),str(entry.get('source_media_id') or ''),int(entry.get('video_index',0)))
        values=[int(f.get('resolution') or 0) for t in (entry.get('media') or {}).get('tracks',[]) for f in t.get('formats',[]) if f.get('type')=='video' and f.get('format')=='m3u8' and is_url(f.get('url'))]
        if values:web_resolutions[key]=max(values)
    def add(role,url=None,path=(),lesson_id=None,source_media_id=None,video_index=None,alias_id=None,**metadata):
        identity={'role':role,'lesson_id':lesson_id,'source_media_id':source_media_id,'video_index':video_index,'alias_id':alias_id,'url_sha256':hashlib.sha256(url.encode()).hexdigest() if is_url(url) else None}
        rid=hashlib.sha256(canonical(identity)).hexdigest()[:24]
        item=resources.setdefault(rid,{'resource_id':rid,'role':role,'required':True,**{k:v for k,v in identity.items() if k!='url_sha256' and v is not None},'source_url_sha256':identity['url_sha256'],'source_field_paths':[],**metadata,'_url':url if is_url(url) else None})
        if list(path) not in item['source_field_paths']:item['source_field_paths'].append(list(path))
        return item
    def captions(video,path,lesson_id,media_id,index):
        for key,fmt in [('caption','srt'),('vtt_caption','vtt')]:
            if is_url(video.get(key)):
                item=add('subtitle',video[key],path+(key,),lesson_id,media_id,index,format=fmt)
                item['preferred']=item.get('preferred',False) or 'article_info' in path or lesson_id is None
    def video_asset(video,path,lesson_id=None,index=0):
        if not isinstance(video,dict):return
        mid=str(video.get('dd_media_id_str') or video.get('dd_media_id') or '')
        resolution,key,url=highest_video(video)
        if not mid and any(is_url(v) for v in video.values()):issues.append({'kind':'video_identity_missing','source_field_path':list(path)})
        if url:
            add('lesson_video' if lesson_id is not None else 'course_intro_video',url,path+(key,),lesson_id,mid,index,resolution=max(resolution or 0,web_resolutions.get((lesson_id,mid,index),0)),expected_web_video=(lesson_id,mid,index) in web_resolutions,duration=video.get('duration'),source_declares_drm=bool(video.get('is_drm')))
        elif mid:issues.append({'kind':'video_source_url_missing','source_media_id':mid,'lesson_id':lesson_id})
        captions(video,path,lesson_id,mid,index)
        if lesson_id is None:
            audio_key=next((k for k in [f'bitrate_{resolution}_audio','bitrate_720_audio','bitrate_480_audio','video_audio'] if is_url(video.get(k))),None)
            if audio_key:add('course_intro_audio',video[audio_key],path+(audio_key,),None,mid,index,duration=video.get('duration'),source_declares_drm=bool(video.get('is_drm')))
            if is_url(video.get('cover_img')):add('course_intro_poster',video['cover_img'],path+('cover_img',),None,mid,index)
    extra={}
    for p,v in walk(extra_audio or {}):
        if isinstance(v,dict) and v.get('alias_id') and is_url(v.get('mp3_play_url')):
            alias=str(v['alias_id']);previous=extra.get(alias)
            if previous and previous['_url']!=v['mp3_play_url']:issues.append({'kind':'conflicting_exact_audio_alias','alias_id':alias})
            extra[alias]={'_url':v['mp3_play_url'],'source_path':['authorized-extra-audio',*p,'mp3_play_url']}
    lessons=source.get('lessons',[]);seen=set()
    for index,row in enumerate(lessons):
        lid=str(row.get('id') or '');path=('lessons',index)
        if not lid or lid in seen:issues.append({'kind':'lesson_identity_missing_or_duplicate','lesson_id':lid})
        seen.add(lid);article=row.get('info',{}).get('article_info') or {};audio=article.get('audio') or {};audio=audio if isinstance(audio,dict) else {}
        aliases=article.get('audio_alias_ids') or [];aliases=[aliases] if isinstance(aliases,str) else list(aliases)
        alias=str(audio.get('alias_id') or '')
        if not alias and len(aliases)==1:alias=str(aliases[0])
        main_url=audio.get('mp3_play_url')
        if alias or is_url(main_url):add('main_audio',main_url,path+('info','article_info','audio','mp3_play_url'),lid,alias_id=alias or None,duration=audio.get('duration'))
        body=decode_body(row)
        for bp,block in walk(body):
            if not isinstance(block,dict):continue
            if block.get('type')=='audio':
                extra_alias=block.get('aliasId') or block.get('alias_id')
                if extra_alias:aliases.append(str(extra_alias))
            if block.get('type') in {'image','inline-image'} and is_url(block.get('url')):add('image',block['url'],path+('body','content',*bp,'url'))
            if block.get('type')=='blockquote':
                author=block.get('cite',{}).get('author',{})
                if is_url(author.get('avatar')):add('image',author['avatar'],path+('body','content',*bp,'cite','author','avatar'))
            if block.get('type')=='product-item' and is_url((block.get('info') or {}).get('cover')):add('image',block['info']['cover'],path+('body','content',*bp,'info','cover'))
            if block.get('type') in {'attachment','document','file'}:
                u=block.get('url') or block.get('download_url')
                if is_url(u):add('attachment',u,path+('body','content',*bp,'url' if block.get('url') else 'download_url'),lid)
            if block.get('type')=='video' and is_url(block.get('poster')):add('image',block['poster'],path+('body','content',*bp,'poster'))
        for declared in dict.fromkeys(str(a) for a in aliases if a):
            if declared==alias:continue
            entry=extra.get(declared,{})
            add('extra_audio',entry.get('_url'),entry.get('source_path',path+('info','article_info','audio_alias_ids')),lid,alias_id=declared)
        videos=article.get('video') or []
        if len(videos)>1:issues.append({'kind':'multiple_video_requires_explicit_adapter','lesson_id':lid,'count':len(videos)})
        for vi,video in enumerate(videos):
            vp=path+('info','article_info','video',vi);video_asset(video,vp,lid,vi)
            mid=str(video.get('dd_media_id_str') or video.get('dd_media_id') or '')
            if not alias and not is_url(main_url):
                res,_,_=highest_video(video)
                key=next((k for k in [f'bitrate_{res}_audio','bitrate_720_audio','bitrate_480_audio','video_audio'] if is_url(video.get(k))),None)
                if key:add('video_audio_component',video[key],vp+(key,),lid,mid,vi,duration=video.get('duration'),source_declares_drm=bool(video.get('is_drm')))
            if is_url(video.get('cover_img')):add('image',video['cover_img'],vp+('cover_img',))
        for vi,video in enumerate((row.get('catalog') or {}).get('video') or []):captions(video,path+('catalog','video',vi),lid,str(video.get('dd_media_id_str') or video.get('dd_media_id') or ''),vi)
    for index,row in enumerate(source.get('catalog',[])):
        lid=str(row.get('id') or '');catalog=row.get('catalog') or row
        for vi,video in enumerate(catalog.get('video') or []):captions(video,('catalog',index,'catalog','video',vi),lid,str(video.get('dd_media_id_str') or video.get('dd_media_id') or ''),vi)
    metadata=source.get('metadata') or {}
    if isinstance(metadata.get('class_video'),dict):video_asset(metadata['class_video'],('metadata','class_video'))
    for index,video in enumerate((metadata.get('intro_article') or {}).get('video') or []):
        article=metadata['intro_article'];lid=str(article.get('id_str') or article.get('id') or '')
        if lid in seen:captions(video,('metadata','intro_article','video',index),lid,str(video.get('dd_media_id_str') or video.get('dd_media_id') or ''),index)
    for key,url in (source.get('course') or {}).items():
        if key in IMAGE_FIELDS and is_url(url):add('image',url,('course',key))
        if key in {'document_url','attachment_url'} and is_url(url):add('attachment',url,('course',key))
    class RuntimeHTML(HTMLParser):
        def __init__(self,field_path):super().__init__();self.field_path=field_path
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='img' and is_url(attrs.get('src')):add('image',attrs['src'],self.field_path,embedded_source_format='html_img_src')
            unsupported = [(key,value) for key,value in attrs.items() if (key=='srcset' and re.search(r'https?://',value or '')) or (key=='style' and re.search(r'url\s*\([^)]*https?://',value or '',re.I)) or (tag in {'video','audio','iframe','source','object','embed','link','script'} and key in {'src','href','data','poster'} and is_url(value))]
            for key,value in unsupported:issues.append({'kind':'metadata_embedded_media_requires_adapter','tag':tag,'attribute':key,'source_field_path':list(self.field_path),'source_url_sha256':hashlib.sha256(value.encode()).hexdigest()})
        def handle_data(self,value):
            if re.search(r'(?:url\s*\([^)]*|@import\s+["\']?)https?://',value,re.I):issues.append({'kind':'metadata_css_dependency_requires_adapter','source_field_path':list(self.field_path)})
    for field in ('items','new_items'):
        for i,item in enumerate(metadata.get(field) or []):
            if isinstance(item,dict) and isinstance(item.get('content'),str):RuntimeHTML(('metadata',field,i,'content')).feed(item['content'])
    return {'schema_version':1,'course_enid':course_id,'source_driven':True,'resources':list(resources.values()),'issues':issues,'summary':{'expected_resources':len(resources),'by_role':{role:sum(r['role']==role for r in resources.values()) for role in sorted({r['role'] for r in resources.values()})}}}

def load_inventory(root=ROOT,source_path='raw/authorized-course.json'):
    root=Path(root).resolve();source_file=(root/source_path).resolve()
    if not source_file.is_relative_to(root):raise ValueError('Source inventory path escapes archive')
    source=read(source_file)
    if not source or not source.get('complete') or source.get('errors'):raise ValueError('A complete authorized source is required')
    inventory=discover_inventory(source,read(root/'raw/authorized-extra-audio.json',{}),read(root/'raw/authorized-web-media.json',{}))
    inventory.update(source_archive_path=source_file.relative_to(root).as_posix(),source_archive_sha256=digest(source_file))
    return inventory

def verify_inventory(root=ROOT,inventory=None,course=None):
    """Check required current paths and exact source identities; no network/codecs."""
    root=Path(root).resolve();inventory=inventory or load_inventory(root);course=course or read(root/'course.json',{})
    errors=list(inventory.get('issues',[]));rows=[];by_lid={str(l['id']):l for l in course.get('lessons',[])}
    original_rows=(read(root/'raw/video-archive-report.json',{}) or {}).get('videos',[])
    image_manifest=read(root/'assets/images/manifest.json',{})
    image_rows=image_manifest if isinstance(image_manifest,list) else image_manifest.get('images',[]) if 'images' in image_manifest else list(image_manifest.values())
    attachment_manifest=read(root/'assets/attachments/manifest.json',{})
    attachment_rows=attachment_manifest if isinstance(attachment_manifest,list) else attachment_manifest.get('attachments',[])
    checked={}
    def check_file(track,rid):
        if not isinstance(track,dict) or not track.get('path'):return False
        p=(root/track['path']).resolve()
        if not p.is_relative_to(root) or not p.is_file():return False
        h=checked.setdefault(p,digest(p)) if p not in checked else checked[p]
        return bool(track.get('sha256')==h and track.get('bytes')==p.stat().st_size)
    for resource in inventory['resources']:
        role=resource['role'];lesson=by_lid.get(str(resource.get('lesson_id')),{});tracks=[];rid=resource['resource_id']
        if role in {'main_audio','extra_audio'}:
            tracks=[t for t in lesson.get('audio',[]) if str(t.get('audio_alias_id') or '')==str(resource.get('alias_id') or '') and t.get('source_url_sha256')==resource.get('source_url_sha256') and resource.get('source_url_sha256')]
        elif role=='lesson_video':
            tracks=list(lesson.get('video',[]))
            original=[r for r in original_rows if str(r.get('lesson_id'))==resource.get('lesson_id') and str(r.get('source_media_id'))==resource.get('source_media_id') and int(r.get('video_index',0))==resource.get('video_index',0)]
            if len(original)!=1 or not check_file(original[0],rid):errors.append({'kind':'source_video_original_missing_or_unbound','resource_id':rid})
            if resource.get('expected_web_video') and not any(check_file(t,rid) for t in lesson.get('video_web_alternatives',[])+[t for t in tracks if str(t.get('path','')).startswith('assets/video/') and '/decrypted/' not in t['path'] and '/original/' not in t['path']]):errors.append({'kind':'independent_web_video_missing','resource_id':rid})
            if tracks and int(tracks[0].get('resolution',0))<int(resource.get('resolution') or 0):errors.append({'kind':'default_video_below_source_resolution','resource_id':rid})
        elif role=='video_audio_component':tracks=[t for t in lesson.get('video_audio_components',[]) if t.get('source_media_id')==resource.get('source_media_id') and int(t.get('video_index',0))==resource.get('video_index',0)]
        elif role=='subtitle':tracks=[t for t in (lesson.get('subtitles',[]) if resource.get('lesson_id') is not None else course.get('course_intro_subtitles',[])) if t.get('source_url_sha256')==resource.get('source_url_sha256') or (is_url(t.get('source_url')) and hashlib.sha256(t['source_url'].encode()).hexdigest()==resource.get('source_url_sha256'))]
        elif role in {'course_intro_video','course_intro_audio'}:
            field=role;track=course.get(field)
            if track and track.get('source_media_id')==resource.get('source_media_id'):tracks=[track]
        elif role in {'image','course_intro_poster'}:
            tracks=[t for t in image_rows if isinstance(t,dict) and is_url(t.get('source_url')) and hashlib.sha256(t['source_url'].encode()).hexdigest()==resource.get('source_url_sha256')]
        elif role=='attachment':tracks=[t for t in attachment_rows if is_url(t.get('source_url')) and hashlib.sha256(t['source_url'].encode()).hexdigest()==resource.get('source_url_sha256')]
        valid=bool(tracks) and all(check_file(t,rid) and (not t.get('encrypted_source') or check_file(t['encrypted_source'],rid)) and (not t.get('derived_from_verified_video') or check_file(t['derived_from_verified_video'],rid)) for t in tracks)
        if role in {'subtitle','course_intro_video','course_intro_audio','video_audio_component'} and valid:
            if not any(rid in t.get('inventory_resource_ids',[]) for t in tracks):valid=False
        if not valid:errors.append({'kind':'required_resource_missing_or_hash_mismatch','role':role,'resource_id':rid,'lesson_id':resource.get('lesson_id')})
        rows.append({'resource_id':rid,'role':role,'lesson_id':resource.get('lesson_id'),'status':'verified' if valid else 'missing_or_unbound','paths':[t.get('path') for t in tracks]+[t['encrypted_source']['path'] for t in tracks if t.get('encrypted_source')]})
    return {'schema_version':1,'status':'passed' if not errors else 'failed','source_archive_sha256':inventory.get('source_archive_sha256'),'expected_resources':len(rows),'verified_resources':sum(r['status']=='verified' for r in rows),'resources':rows,'errors':errors}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--input',default='raw/authorized-course.json');parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    inv=load_inventory(args.root,args.input);folder=args.root/'raw';folder.mkdir(exist_ok=True,parents=True)
    (folder/'media-inventory.json').write_text(json.dumps(public_inventory(inv),ensure_ascii=False,indent=2)+'\n')
    result=verify_inventory(args.root,inv) if args.verify else public_inventory(inv)
    if args.verify:(folder/'media-inventory-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','expected_resources','verified_resources','summary','issues','errors') if k in result},ensure_ascii=False))
    return 1 if result.get('errors') or result.get('issues') else 0

if __name__=='__main__':raise SystemExit(main())
