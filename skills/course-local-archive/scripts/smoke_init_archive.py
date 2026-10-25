#!/usr/bin/env python3
"""Offline smoke: isolated initialization, safe resumption and dynamic catalogs.

Uses only synthetic in-memory fixtures and temporary folders. No live account,
network endpoint, real course text or real media is used.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parents[1]
ENV = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}


def run(arguments, cwd=None, expected=0):
    result = subprocess.run([sys.executable, *map(str, arguments)], cwd=cwd,
                            env=ENV, text=True, capture_output=True, timeout=60)
    if result.returncode != expected:
        raise AssertionError(f'Unexpected exit {result.returncode}: {result.stderr[-1500:]}')
    return result


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def fixture(directory, course_id, count):
    rows = [{'id': str(index+1), 'enid': f'{course_id}Lesson{index+1}',
             'title': f'Synthetic lesson {index+1}'} for index in range(count)]
    info = {'enid': course_id, 'name': f'Synthetic offline course {course_id}',
            'current_article_count': count, 'intro': 'Synthetic offline fixture.'}
    chapter = {'id': 'synthetic-section', 'id_str': 'synthetic-section',
               'name': 'Synthetic section', 'article_list': rows}
    save(directory/'raw/public/catalog.json', {'class_info': info, 'chapter_list': [chapter]})
    save(directory/'raw/public/class-info.json', {'h': {'c': 0}, 'c': {'class_info': info, 'chapter_list': [chapter]}})
    run(['scripts/export_public.py'], directory)
    lessons=[]
    for row in rows:
        blocks=[{'type':'paragraph','contents':[{'type':'text','text':{'content':f'Synthetic offline paragraph {row["id"]}.'}}]}]
        lessons.append({**row,'section_id':'synthetic-section','section':'Synthetic section',
                        'source_url':f'https://www.dedao.cn/course/article?id={row["enid"]}',
                        'info':{'class_enid':course_id,'article_info':{'id':row['id'],'enid':row['enid'],'title':row['title'],'video':[]}},
                        'body':{'article':{},'content':json.dumps(blocks)}})
    save(directory/'raw/authorized-course.json', {'complete':True,'errors':[], 'course':info,'lessons':lessons})
    run(['scripts/import_authorized.py','raw/authorized-course.json'], directory)
    for builder in ('build_site.py','build_course_info.py','build_resources.py'):
        run(['scripts/'+builder], directory)
    manifest=json.loads((directory/'course.json').read_text())
    assert manifest['course_enid']==course_id
    assert manifest['expected_lesson_count']==count
    assert len(manifest['lessons'])==count
    assert all(row['status']=='imported' and row['text_integrity']=='verified' for row in manifest['lessons'])
    assert len(list((directory/'content').glob('[0-9]*.md')))==count
    assert all((directory/name).is_file() for name in ('index.html','resources.html','course-info.html'))
    # Source video set is derived from this fixture, never a prior course count.
    check="import sys;sys.path.insert(0,'scripts');from archive_config import expected_video_lesson_ids;assert expected_video_lesson_ids()==set()"
    run(['-c',check],directory)
    source=json.loads((directory/'raw/authorized-course.json').read_text())
    video_ids={row['id'] for row in source['lessons'][::2]}
    for row in source['lessons']:
        if row['id'] in video_ids:
            row['info']['article_info']['video']=[{'synthetic_metadata_only':True}]
    save(directory/'raw/authorized-course.json',source)
    check="import sys;sys.path.insert(0,'scripts');from archive_config import expected_video_lesson_ids;assert expected_video_lesson_ids()=="+repr(video_ids)
    run(['-c',check],directory)
    full_lessons=source['lessons'];source['lessons']=full_lessons[:-1]
    save(directory/'raw/authorized-course.json',source)
    rejected=run(['-c',check],directory,expected=1)
    assert 'complete unique source-declared lesson count' in rejected.stderr
    source['lessons']=full_lessons;save(directory/'raw/authorized-course.json',source)
    return {'course_enid':course_id,'lessons':count,'imported_markdown':count,
            'source_derived_video_lessons':len(video_ids),'incomplete_source_refused':True,'builders_passed':True}


def main():
    initializer=SKILL/'scripts/init_archive.py'
    with tempfile.TemporaryDirectory(prefix='course-skill-offline-smoke-') as folder:
        base=Path(folder);alpha=base/'alpha';beta=base/'beta'
        alpha_url='https://www.dedao.cn/course/detail?id=SyntheticCourseAlpha'
        beta_url='https://www.dedao.cn/course/detail?id=SyntheticCourseBeta'
        run([initializer,'--url',alpha_url,'--output',alpha,'--title','Synthetic Alpha'])
        manifest=alpha/'course.json';data=json.loads(manifest.read_text());data['synthetic_sentinel']='keep'
        save(manifest,data);before=manifest.read_bytes()
        marker=alpha/'README.md';marker.write_text('Synthetic user-owned file.\n')
        run([initializer,'--url',alpha_url,'--output',alpha])
        assert manifest.read_bytes()==before and marker.read_text()=='Synthetic user-owned file.\n'
        before_config=(alpha/'course-config.json').read_bytes()
        rejected=run([initializer,'--url',beta_url,'--output',alpha],expected=1)
        assert 'different course' in rejected.stderr
        assert manifest.read_bytes()==before and (alpha/'course-config.json').read_bytes()==before_config
        orphan=base/'nonempty';orphan.mkdir();(orphan/'keep.txt').write_text('keep')
        run([initializer,'--url',alpha_url,'--output',orphan],expected=1)
        assert not (orphan/'course-config.json').exists()
        run([initializer,'--url',beta_url,'--output',beta])
        assert json.loads((alpha/'course-config.json').read_text())['course_enid']!=json.loads((beta/'course-config.json').read_text())['course_enid']
        results=[fixture(alpha,'SyntheticCourseAlpha',2),fixture(beta,'SyntheticCourseBeta',3)]
        for directory in (alpha,beta):
            assert not list(directory.rglob('__pycache__'))
        library=SKILL/'assets/vendor/libddd_ff_protocol.so'
        provenance=json.loads((library.parent/'provenance.json').read_text())
        assert hashlib.sha256(library.read_bytes()).hexdigest()==provenance['sha256']
        print(json.dumps({'status':'passed','network_requests':0,'live_account_accessed':False,
                          'same_course_preserves_files':True,'different_course_refused_without_mutation':True,
                          'nonempty_unbound_directory_refused':True,'dynamic_course_fixtures':results,
                          'vendor_hash_verified':True},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
