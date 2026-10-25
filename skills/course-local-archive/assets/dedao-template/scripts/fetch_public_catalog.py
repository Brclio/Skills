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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", help="Course id; otherwise read course-config.json")
    parser.add_argument("--output", type=Path, default=ROOT / "raw/public")
    args = parser.parse_args()
    args.course_id = configured_course_id(args.course_id)
    args.output.mkdir(parents=True, exist_ok=True)

    info = post("/pc/bauhinia/pc/class/info", {
        "detail_id": args.course_id, "is_login": 0,
    })
    if info.get("c", {}).get("class_info", {}).get("enid") != args.course_id:
        raise ValueError("Returned public metadata belongs to a different course")
    (args.output / "class-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    course = info["c"]
    chapters = []
    for chapter in course["chapter_list"]:
        result = post("/pc/bauhinia/pc/class/free_article_list", {
            "detail_id": args.course_id,
            "chapter_id": chapter.get("id_str") or str(chapter["id"]),
            "count": 0, "max_id": 0, "max_order_num": 0,
        })
        (args.output / f"chapter-{chapter['id']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        articles = result["c"]["article_list"]
        chapters.append({**chapter, "article_list": articles})
        print(chapter["name"], len(articles))
        time.sleep(0.4)

    catalog = {"class_info": course["class_info"], "chapter_list": chapters}
    (args.output / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(len(c["article_list"]) for c in chapters)
    identities = [str(row.get("id_str") or row["id"]) for c in chapters for row in c["article_list"]]
    expected = int(course["class_info"].get("current_article_count") or total)
    if total != expected or len(set(identities)) != total:
        raise ValueError("Public source catalog is incomplete; counts do not match")
    cfg = config()
    if cfg:
        cfg["expected_lesson_count"] = expected
        (ROOT / "course-config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Total:", total)


if __name__ == "__main__":
    main()
