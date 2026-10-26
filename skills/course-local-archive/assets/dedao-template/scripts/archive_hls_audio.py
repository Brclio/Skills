#!/usr/bin/env python3
"""Save one observed lesson audio using the same complete-source pipeline.

Finite HLS playlists, segments and standard identity AES keys are retained before
offline lossless remuxing. This compatibility CLI merges only the primary track;
the batch audio command remains preferable for main plus embedded alias sets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from archive_all_audio import ROOT, archive_media, public_error, write_json, unwrap, duration_seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lesson-id', required=True)
    parser.add_argument('--info', type=Path, required=True, help='Saved authorized article/info response')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--retries', type=int, default=2)
    args = parser.parse_args()
    if not args.lesson_id.isdigit() or args.timeout <= 0 or not 0 <= args.retries <= 3:
        parser.error('Use a numeric catalog ID, positive timeout and 0–3 retries')
    info_path = (args.info if args.info.is_absolute() else ROOT / args.info).resolve()
    if not info_path.is_relative_to(ROOT) or not info_path.is_file():
        parser.error('Saved lesson info must be inside this course')
    info = unwrap(json.loads(info_path.read_text()))
    article = info.get('article_info', info)
    if str(article.get('id', info.get('article_id', ''))) != args.lesson_id:
        parser.error('The saved response does not match the requested lesson ID')
    audio = article.get('audio') or {}
    url = audio.get('mp3_play_url') or ''
    if not url.startswith(('http://','https://')):
        parser.error('The saved response contains no observed HTTP(S) audio URL')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        parser.error('ffmpeg and ffprobe are required')
    alias = str(audio.get('alias_id') or '')
    identity = alias or url
    entry = {'lesson_id':args.lesson_id,'audio_alias_id':alias,'_url':url,'label':audio.get('title') or article.get('title') or args.lesson_id,'expected_duration_seconds':duration_seconds(audio.get('duration')),'source_info_path':info_path.relative_to(ROOT).as_posix()}
    job = {'entry':entry,'media_id':hashlib.sha256(identity.encode()).hexdigest()[:24],'filename_stem':args.lesson_id,'lesson_ids':[args.lesson_id]}
    report = archive_media(job, ROOT/'raw/audio-archive', args.timeout, args.retries)
    if report.get('status') == 'complete':
        from archive_state import course_lock
        with course_lock(ROOT):
            path = ROOT/'course.json';before=path.read_bytes();course=json.loads(before)
            lessons=[lesson for lesson in course['lessons'] if str(lesson['id'])==args.lesson_id]
            if len(lessons)!=1: raise ValueError('The requested lesson is not unique in course.json')
            lesson=lessons[0]
            preserved=[track for track in lesson.get('audio',[]) if track.get('audio_alias_id') != alias and Path(track.get('path','')).stem != args.lesson_id]
            lesson['audio']=[{'path':report['path'],'label':entry['label'],'audio_alias_id':alias,'source_url_sha256':report['source_url_sha256'],'bytes':report['bytes'],'sha256':report['sha256'],'duration':report['duration_seconds'],'archive_report':'raw/audio-archive/media/'+job['media_id']+'.json'}]+preserved
            lesson['audio_status']='complete';course.pop('audio_policy',None)
            if path.read_bytes()!=before: raise ValueError('Course manifest changed while merging primary audio')
            write_json(path,course)
    write_json(ROOT/'raw'/('audio-'+args.lesson_id+'-report.json'),report)
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report.get('status')=='complete' else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as error:
        print(public_error(error),file=sys.stderr);raise SystemExit(1)
