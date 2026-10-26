"""Validate actual browser observations; never invent or execute UI actions.

The browser tool supplies the loaded DOM payload, runtime URLs/markers, action
results and local screenshot/snapshot evidence. This module binds them to the
current product. Post-final reports cannot become core media evidence.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

from archive_state import sha_file
from audit_evidence import canonical_sha, content_manifest_sha, local_file, is_post_final
from audit_media import playable_tracks


class PayloadParser(HTMLParser):
    def __init__(self,text):
        super().__init__();self.inside=False;self.parts=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='course-data':self.inside=True
    def handle_endtag(self,tag):
        if tag=='script':self.inside=False
    def handle_data(self,data):
        if self.inside:self.parts.append(data)


def current_payload(root):
    parser=PayloadParser((Path(root)/'index.html').read_text())
    return json.loads(''.join(parser.parts))


def file_binding(root,values,**metadata):
    files={}
    for value in sorted(set(values)):
        path=local_file(root,value);files[value]={'sha256':sha_file(path),'bytes':path.stat().st_size}
    state={'files':files,**metadata};return {'sha256':canonical_sha(state),'state':state}


def product_bindings(root):
    root=Path(root).resolve();course=json.loads((root/'course.json').read_text());payload=current_payload(root)
    reader_files=['index.html','web/app.js','web/app.css','raw/authorized-course.json','raw/public/catalog.json']
    # Fonts and all other declared runtime files affect visual/reading proof.
    for value in ('web/app.css',):
        for url in re.findall(r'url\(\s*[\'"]?([^\)\'"\s]+)',(root/value).read_text()):
            if not url.startswith('data:'):
                reader_files.append((Path(value).parent/unquote(urlsplit(url).path)).as_posix())
    result={'reader':file_binding(root,reader_files,content_manifest_sha256=content_manifest_sha(course)),
            'info':file_binding(root,['course-info.html']),
            'resources':file_binding(root,['resources.html','content/本地资源.md'])}
    media={}
    for lid,role,kind,track in playable_tracks(course):
        if track.get('path') and track['path'] not in media:
            media[track['path']]={'kind':kind,'binding':file_binding(root,[track['path']])}
    result['media']=media
    result['payload_sha256']=canonical_sha({k:v for k,v in payload.items() if k!='reader_payload_sha256'})
    result['runtime_versions']={'app_js':sha_file(root/'web/app.js'),'app_css':sha_file(root/'web/app.css')}
    return result


def required_media_samples(root):
    course=json.loads((Path(root)/'course.json').read_text());kinds={'audio':[],'video':[]}
    for lid,role,kind,track in playable_tracks(course):
        value=track.get('path')
        if value and value not in kinds[kind]:kinds[kind].append(value)
    return {kind:list(dict.fromkeys([values[0],values[len(values)//2],values[-1]])) if values else [] for kind,values in kinds.items()}


def validate_loaded(root,observation):
    payload=observation.get('loaded_payload');expected=current_payload(root);bindings=product_bindings(root)
    if not isinstance(payload,dict) or payload!=expected:raise ValueError('Actually loaded course payload differs from the current index.html; reload the reader')
    actual=canonical_sha({k:v for k,v in payload.items() if k!='reader_payload_sha256'})
    if payload.get('reader_payload_sha256')!=actual or actual!=bindings['payload_sha256']:raise ValueError('Loaded reader payload digest is missing or inconsistent')
    if payload.get('content_manifest_sha256')!=content_manifest_sha(json.loads((Path(root)/'course.json').read_text())):raise ValueError('Loaded content manifest digest differs from current course content')
    if payload.get('asset_versions')!=bindings['runtime_versions']:raise ValueError('Loaded payload runtime versions are stale')
    parts=urlsplit(observation.get('page_url',''))
    if not (parts.scheme=='file' or parts.scheme=='http' and parts.hostname in {'127.0.0.1','localhost','::1'}):raise ValueError('Browser QA must observe the local reader')
    urls=observation.get('runtime_urls',[])
    for name,key in [('app.js','app_js'),('app.css','app_css')]:
        if not any(urlsplit(url).path.endswith('/web/'+name) and parse_qs(urlsplit(url).query).get('v')==[bindings['runtime_versions'][key]] for url in urls):raise ValueError('Actually loaded runtime URL lacks its current content version: '+name)
    markers=observation.get('runtime_markers',{})
    if markers.get('readerPayloadSha256')!=actual or markers.get('appJsSha256')!=bindings['runtime_versions']['app_js'] or markers.get('appCssSha256')!=bindings['runtime_versions']['app_css']:raise ValueError('Current reader runtime did not execute or browser markers are stale')
    if not observation.get('browser') or not observation.get('captured_at_utc'):raise ValueError('Actual browser identity and capture timestamp are required')
    return bindings


def artifact_proof(root,artifacts):
    if not isinstance(artifacts,list) or not artifacts:raise ValueError('A browser screenshot or saved tool snapshot is required for each UI proof')
    result=[]
    for value in artifacts:
        path=local_file(root,value)
        if not is_post_final(path.relative_to(Path(root).resolve())):raise ValueError('UI artifacts must live in raw/qa or another post-final evidence directory')
        if not path.stat().st_size:raise ValueError('An empty browser artifact is not evidence')
        result.append({'path':path.relative_to(Path(root).resolve()).as_posix(),'bytes':path.stat().st_size,'sha256':sha_file(path)})
    return result


def proof_key(proof):return proof['kind']+(':'+proof['path'] if proof.get('path') else '')


def validate_actions(root,proofs,bindings):
    payload=current_payload(root);lessons=payload.get('lessons',[]);ids=[str(r['id']) for r in lessons]
    sample_ids=list(dict.fromkeys([ids[0],ids[len(ids)//2],ids[-1]])) if ids else []
    checked=[]
    for raw in proofs:
        proof=dict(raw);kind=proof.get('kind');data=proof.get('observed',{})
        if kind=='navigation':
            visits=data.get('visits',[])
            if data.get('catalog_count')!=len(ids) or not set(sample_ids).issubset({str(v.get('lesson_id')) for v in visits}):raise ValueError('Navigate first/middle/last lessons and record their loaded titles')
            titles={str(r['id']):r['title'] for r in lessons}
            if any(v.get('title')!=titles.get(str(v.get('lesson_id'))) for v in visits):raise ValueError('Navigation title differs from the source-backed reader')
        elif kind=='search':
            query=data.get('query','').strip();terms=query.lower().split()
            wanted=[str(r['id']) for r in lessons if all(t in (str(r.get('title',''))+' '+str(r.get('section',''))+' '+str(r.get('text',''))).lower() for t in terms)]
            if not query or not wanted or data.get('result_lesson_ids')!=wanted:raise ValueError('Search evidence does not match the actual source-backed results')
        elif kind=='font_control':
            if not isinstance(data.get('before_px'),(float,int)) or not isinstance(data.get('after_px'),(float,int)) or data['before_px']==data['after_px'] or data.get('font_faces_ready') is not True:raise ValueError('Record an actual font-size control change and ready local/system fonts')
        elif kind=='layout':
            if data.get('viewport_width',0)<300 or data.get('horizontal_overflow_px',999)>2 or data.get('failed_image_count')!=0 or data.get('console_errors')!=[]:raise ValueError('Record a readable viewport with loaded images and no browser errors')
        elif kind in {'info','resources'}:
            if data.get('page_path')!={'info':'course-info.html','resources':'resources.html'}[kind] or not data.get('title') or data.get('missing_resource_count')!=0:raise ValueError('Open the local information/resource page and record its rendered state')
        elif kind=='media':
            value=proof.get('path');current=bindings['media'].get(value)
            if not current:raise ValueError('Playback proof path is not a current playable archive track')
            if data.get('ready_state',0)<2 or data.get('duration_seconds',0)<=0 or data.get('playback_advanced_seconds',0)<=0 or data.get('error') is not None:raise ValueError('Playback must visibly advance without a media error')
            target=data.get('seek_target_seconds');actual=data.get('seek_actual_seconds')
            if not isinstance(target,(int,float)) or not isinstance(actual,(int,float)) or target<=0 or abs(target-actual)>2:raise ValueError('Record an actual seek and the resulting currentTime')
            if current['kind']=='video' and (data.get('video_width',0)<=0 or data.get('video_height',0)<=0):raise ValueError('Video playback needs actual decoded dimensions')
        elif kind=='download':
            value=proof.get('path');source=local_file(root,value)
            if data.get('bytes')!=source.stat().st_size or data.get('sha256')!=sha_file(source) or data.get('initiated_from_ui') is not True:raise ValueError('UI download must match the current local file bytes and hash')
        else:raise ValueError('Unknown UI proof kind: '+str(kind))
        category=kind if kind in {'info','resources'} else 'media:'+proof['path'] if kind in {'media','download'} and proof.get('path') in bindings['media'] else 'reader'
        binding=bindings['media'][proof['path']]['binding'] if category.startswith('media:') else bindings[category]
        proof.update({'category':category,'binding':binding,'artifacts':artifact_proof(root,proof.get('artifacts',[]))})
        checked.append(proof)
    return checked


def record_observation(root,observation):
    bindings=validate_loaded(root,observation)
    proofs=validate_actions(root,observation.get('proofs',[]),bindings)
    # Preserve actual observations, rather than upgrading claims into actions.
    return {'schema_version':2,'evidence_role':'browser_qa','status':'observed','captured_at_utc':observation['captured_at_utc'],'browser':observation['browser'],'page_url':observation['page_url'],'loaded_payload_sha256':bindings['payload_sha256'],'loaded_runtime_versions':bindings['runtime_versions'],'runtime_urls':observation['runtime_urls'],'proofs':proofs}


def verify_qa(root,report):
    if report.get('schema_version')!=2 or report.get('evidence_role')!='browser_qa':raise ValueError('Upgraded actual-observation QA evidence is required')
    origin=report.get('observation_source',{})
    source=local_file(root,origin.get('path'))
    if sha_file(source)!=origin.get('sha256'):raise ValueError('Original actual browser observation changed')
    validate_loaded(root,json.loads(source.read_text()))
    bindings=product_bindings(root);proofs=report.get('proofs',[]);stale=[]
    for proof in proofs:
        category=proof.get('category');current=bindings['media'].get(proof.get('path'),{}).get('binding') if str(category).startswith('media:') else bindings.get(category)
        if current!=proof.get('binding'):stale.append(proof_key(proof));continue
        origin=proof.get('observation_source',{})
        source=local_file(root,origin.get('path'))
        if sha_file(source)!=origin.get('sha256'):stale.append(proof_key(proof))
        for artifact in proof.get('artifacts',[]):
            path=local_file(root,artifact.get('path'))
            if sha_file(path)!=artifact.get('sha256') or path.stat().st_size!=artifact.get('bytes'):stale.append(proof_key(proof))
    if stale:raise ValueError('UI proofs are stale; repeat only affected checks: '+', '.join(sorted(set(stale))))
    # Revalidate action contents too, not just a passed boolean from a report.
    normalized=[{**p,'artifacts':[r['path'] for r in p.get('artifacts',[])]} for p in proofs]
    validate_actions(root,normalized,bindings)
    present={proof_key(p) for p in proofs};required={'navigation','search','font_control','layout','info','resources'}
    required.update('media:'+value for values in required_media_samples(root).values() for value in values)
    if not any(p.get('kind')=='download' for p in proofs):required.add('download')
    missing=required-present
    if missing:raise ValueError('Missing actual browser checks: '+', '.join(sorted(missing)))
    if report.get('loaded_payload_sha256')!=bindings['payload_sha256'] or report.get('loaded_runtime_versions')!=bindings['runtime_versions']:raise ValueError('Loaded browser payload/runtime versions are stale')
    return {'status':'passed','proofs':len(proofs),'required_media_samples':required_media_samples(root),'loaded_payload_sha256':bindings['payload_sha256'],'loaded_runtime_versions':bindings['runtime_versions']}
