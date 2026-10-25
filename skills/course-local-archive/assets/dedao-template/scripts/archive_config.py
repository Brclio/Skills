"""Course identity and source-derived counts for a dedicated archive directory."""
from pathlib import Path
import json
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def config():
    return read_json(ROOT/'course-config.json', {})


def configured_course_id(override=None):
    cfg=config();manifest=read_json(ROOT/'course.json', {})
    catalog=read_json(ROOT/'raw/public/catalog.json', {})
    candidates=[v for v in [override,cfg.get('course_enid'),manifest.get('course_enid'),catalog.get('class_info',{}).get('enid')] if v]
    if not candidates:
        raise ValueError('A course id is required; initialize this archive with init_archive.py or provide --course-id')
    if len(set(candidates))!=1:
        raise ValueError('Course identities disagree; refusing to mix different courses in one folder')
    return str(candidates[0])


def expected_video_lesson_ids(course=None):
    source=read_json(ROOT/'raw/authorized-course.json', {})
    if source:
        if source.get('course',{}).get('enid')!=configured_course_id():
            raise ValueError('Authorized source belongs to a different course')
        if not source.get('complete') or source.get('errors'):
            raise ValueError('A complete error-free authorized source is required for whole-course video application')
        rows=source.get('lessons',[])
        ids=[str(row['id']) for row in rows]
        course=course or read_json(ROOT/'course.json', {})
        manifest={str(row['id']):row for row in course.get('lessons',[])}
        expected_count=course.get('expected_lesson_count') or config().get('expected_lesson_count') or source.get('course',{}).get('current_article_count')
        if len(ids)!=len(set(ids)) or (expected_count is not None and len(ids)!=int(expected_count)):
            raise ValueError('Authorized source does not contain the complete unique source-declared lesson count')
        if manifest and (set(ids)!=set(manifest) or any(row.get('enid')!=manifest[str(row['id'])].get('enid') for row in rows)):
            raise ValueError('Authorized source lesson identities do not match the established course catalog')
        for row in rows:
            if len((row.get('info',{}).get('article_info') or {}).get('video') or [])>1:
                raise ValueError('This helper supports one primary video per lesson; preserve and adapt multiple-video mappings explicitly')
        return {str(row['id']) for row in rows if (row.get('info',{}).get('article_info') or {}).get('video')}
    course=course or read_json(ROOT/'course.json', {})
    ids={str(row['id']) for row in course.get('lessons',[]) if row.get('video_encrypted_original')}
    if not ids:
        raise ValueError('No source-derived expected video identities are available')
    return ids
