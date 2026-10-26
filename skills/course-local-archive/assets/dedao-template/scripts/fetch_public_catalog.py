#!/usr/bin/env python3
"""Fetch Dedao's public course metadata and catalog without credentials.

Uses only endpoints called by the site's public web client. It does not fetch
paid lesson bodies, credentials, encryption keys, or media segments.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

from archive_config import ROOT, configured_course_id, config

BASE = "https://www.dedao.cn"


def secret_name(key):
    normalized=re.sub(r'([a-z])([A-Z])',r'\1_\2',str(key))
    normalized=re.sub(r'[^a-z0-9]+','_',normalized.lower())
    if normalized in {'token_version','drm_version','has_play_auth'}:return False
    if normalized in {'tk','gat','xi_gat','sid','isid','jwt','play_auth','play_auth_id'}:return True
    return bool(re.search(r'(?:^|_)(?:token|key|secret|security|authorization|cookie|csrf|password|credential|session)(?:_|$)',normalized))


def clean_public_response(value):
    """Remove secret-valued fields recursively; leave prose and other strings exact."""
    if isinstance(value,list):return [clean_public_response(child) for child in value]
    if isinstance(value,dict):return {key:clean_public_response(child) for key,child in value.items() if not secret_name(key)}
    return value


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("h", {}).get("c") != 0:
        raise RuntimeError(clean_public_response(result.get("h", {})))
    return clean_public_response(result)


def collect_catalog(course_id, reader=post, delay=0.4):
    """Read source-declared sections, including a flat course and paged chapters."""
    info = reader('/pc/bauhinia/pc/class/info', {'detail_id': course_id, 'is_login': 0})
    metadata = info.get('c', {})
    course = metadata.get('class_info', {})
    if course.get('enid') != course_id:
        raise ValueError('Returned public metadata belongs to a different course')
    expected = int(course.get('current_article_count') or 0)
    if expected < 1:
        raise ValueError('Source must declare a positive current article count')
    source_sections = metadata.get('chapter_list') or [{'id': 0, 'id_str': '0', 'name': course.get('name', '课程')}]
    sections, seen, enids, raw_pages = [], {}, {}, []

    def more_flag(data):
        for key in ('has_more', 'has_more_article_list', 'has_next', 'has_more_flat_article_list'):
            if key in data:
                value = data[key]
                if value in (True, 1, '1'): return True
                if value in (False, 0, '0', None): return False
                raise ValueError('Unrecognized source pagination flag')
        return None

    def page(section, first):
        payload = {'detail_id': course_id, 'chapter_id': section['id_str'], 'count': 0 if first else 100, 'max_id': section['_max_id'], 'max_order_num': section['_max_order_num']}
        result = reader('/pc/bauhinia/pc/class/free_article_list', payload)
        data = result.get('c', {})
        rows = data.get('article_list')
        if not isinstance(rows, list): raise ValueError('Source catalog page is not a list')
        raw_pages.append({'section_id': section['id_str'], 'page': section['_pages']+1, 'response': result})
        added = 0
        for row in rows:
            identity = str(row.get('id_str') or row.get('id') or '')
            if not identity or not row.get('enid') or not row.get('title'): raise ValueError('Source catalog lesson identity is incomplete')
            if row.get('class_enid') and row['class_enid'] != course_id: raise ValueError('Source catalog contains another course')
            fingerprint = (str(row['enid']), str(row['title']), section['id_str'])
            if identity in seen:
                if seen[identity] != fingerprint: raise ValueError('Conflicting source catalog duplicate')
                continue
            if str(row['enid']) in enids:
                raise ValueError('Source catalog has duplicate article enids')
            enids[str(row['enid'])] = identity
            seen[identity] = fingerprint; section['article_list'].append(row); added += 1
        flag = more_flag(data)
        last = rows[-1] if rows else {}
        next_id = str(data.get('next_max_id', data.get('max_id', last.get('id_str', last.get('id', section['_max_id'])))))
        next_order = data.get('next_max_order_num', data.get('max_order_num', last.get('order_num', section['_max_order_num'])))
        advanced = next_id != str(section['_max_id']) or str(next_order) != str(section['_max_order_num'])
        section['_pages'] += 1
        section['_max_id'], section['_max_order_num'], section['_more'] = next_id, next_order, flag
        section['_exhausted'] = flag is False or not rows or (not first and added == 0 and flag is not True)
        if flag is True and (not added or not advanced): raise ValueError('Source catalog pagination did not advance')
        if len(seen) > expected or section['_pages'] > 10000: raise ValueError('Source catalog exceeds its declared bounds')
        if delay: time.sleep(delay)
        return added

    for original in source_sections:
        sid = str(original.get('id_str') or original.get('id', ''))
        if not sid or any(s['id_str'] == sid for s in sections): raise ValueError('Source section identities are missing or duplicate')
        section = {**original, 'id_str': sid, 'article_list': [], '_max_id': 0, '_max_order_num': 0, '_pages': 0, '_more': None, '_exhausted': False}
        sections.append(section); page(section, True)
    while any(s['_more'] is True or len(seen) < expected and not s['_exhausted'] for s in sections):
        added = 0
        for section in sections:
            if section['_exhausted'] or section['_more'] is not True and len(seen) >= expected: continue
            added += page(section, False)
        if not added and not any(s['_more'] is True for s in sections): break
    if len(seen) != expected or any(s['_more'] is True for s in sections):
        raise ValueError('Public source catalog is incomplete; counts do not match')
    chapters = [{k: v for k, v in section.items() if not k.startswith('_')} for section in sections]
    return info, {'class_info': course, 'chapter_list': chapters}, raw_pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", help="Course id; otherwise read course-config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "raw/public")
    args = parser.parse_args()
    args.course_id = configured_course_id(args.course_id)
    args.output.mkdir(parents=True, exist_ok=True)

    info, catalog, pages = collect_catalog(args.course_id)
    (args.output / "class-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for page in pages:
        sid = re.sub(r'[^A-Za-z0-9_-]', '_', page['section_id'])
        (args.output / f"chapter-{sid}-page-{page['page']}.json").write_text(json.dumps(page['response'], ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (args.output / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(len(c["article_list"]) for c in catalog['chapter_list'])
    identities = [str(row.get("id_str") or row["id"]) for c in catalog['chapter_list'] for row in c["article_list"]]
    expected = int(catalog['class_info']["current_article_count"])
    if total != expected or len(set(identities)) != total:
        raise ValueError("Public source catalog is incomplete; counts do not match")
    cfg = config()
    if cfg:
        cfg["expected_lesson_count"] = expected
        (ROOT / "course-config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Total:", total)


if __name__ == "__main__":
    main()
