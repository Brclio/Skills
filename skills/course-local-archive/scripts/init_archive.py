#!/usr/bin/env python3
"""Create or safely resume an isolated Dedao archive; makes no network requests."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.parse import parse_qs, urlencode, urlsplit

SKILL=Path(__file__).resolve().parents[1]
TEMPLATE=SKILL/'assets/dedao-template'
VENDOR=SKILL/'assets/vendor/libddd_ff_protocol.so'
PROVENANCE=SKILL/'assets/vendor/provenance.json'


def identity(url):
    parts=urlsplit(url)
    values=parse_qs(parts.query).get('id',[])
    if parts.scheme!='https' or parts.hostname not in {'www.dedao.cn','dedao.cn'} or parts.path!='/course/detail' or len(values)!=1 or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',values[0]):
        raise ValueError('Use the supplied HTTPS Dedao course/detail URL with one id; other platform adapters are not included in this template')
    return values[0], 'https://www.dedao.cn/course/detail?'+urlencode({'id':values[0]})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--title')
    args=parser.parse_args();course_id,url=identity(args.url)
    output=args.output.expanduser().resolve();config_path=output/'course-config.json';existing={}
    if output.exists():
        if not output.is_dir():raise ValueError('Output must be a directory')
        if config_path.is_file():
            existing=json.loads(config_path.read_text(encoding='utf-8'))
            if existing.get('platform')!='dedao' or existing.get('course_enid')!=course_id:
                raise ValueError('This folder is bound to a different course; select a new output directory')
        elif any(output.iterdir()):
            raise ValueError('Refusing to adopt a nonempty directory without a matching course-config.json')
        manifest=output/'course.json'
        if manifest.is_file() and json.loads(manifest.read_text(encoding='utf-8')).get('course_enid')!=course_id:
            raise ValueError('Existing manifest belongs to a different course')
    provenance=json.loads(PROVENANCE.read_text(encoding='utf-8'))
    library_sha=hashlib.sha256(VENDOR.read_bytes()).hexdigest()
    if library_sha!=provenance['sha256']:
        raise ValueError('Bundled read-only protocol library differs from its verified provenance')
    output.mkdir(parents=True,exist_ok=True)
    copied,retained=[],[]
    for source in sorted(TEMPLATE.rglob('*')):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix=='.pyc':continue
        relative=source.relative_to(TEMPLATE);target=output/relative
        if target.exists():retained.append(relative.as_posix());continue
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);copied.append(relative.as_posix())
    for name in ['raw/public','raw/authorized','raw/lessons','raw/audio-archive','content','assets/images','assets/audio','assets/video/original','assets/video/encrypted','assets/video/decrypted','assets/subtitles','assets/attachments']:
        (output/name).mkdir(parents=True,exist_ok=True)
    title=args.title or existing.get('title') or '本地课程归档'
    available_version=json.loads((TEMPLATE/'template-metadata.json').read_text(encoding='utf-8')).get('template_version',1)
    retained_version=existing.get('template_version',available_version)
    cfg={**existing,'schema_version':1,'platform':'dedao','course_enid':course_id,'source_url':url,'title':title,'expected_lesson_count':existing.get('expected_lesson_count'),'expected_video_count':existing.get('expected_video_count'),'protocol_library':{'path':str(VENDOR),'sha256':library_sha,'provenance':str(PROVENANCE),'mode':'read_only_static_parameter_parsing'},'template_version':retained_version,'available_template_version':available_version,'template_update_available':retained_version!=available_version}
    cfg.setdefault('created_at_utc',datetime.now(timezone.utc).isoformat())
    config_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest=output/'course.json'
    if not manifest.exists():
        manifest.write_text(json.dumps({'schema_version':1,'title':title,'source_url':url,'course_enid':course_id,'expected_lesson_count':None,'sections':[],'lessons':[],'archive_status':'not_imported'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'course_enid':course_id,'source_url':url,'copied_files':len(copied),'retained_existing_files':len(retained),'network_requests':0,'authentication_accessed':False,'read_only_protocol_library_sha256':library_sha},ensure_ascii=False))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except ValueError as error:raise SystemExit(str(error))
