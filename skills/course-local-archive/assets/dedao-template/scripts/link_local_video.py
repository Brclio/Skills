#!/usr/bin/env python3
"""Link source video blocks to the verified local track, preserving block position."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FIGURE = re.compile(r'<figure class="source-video" data-source-media-id="([^"]+)">(.*?)</figure>', re.S)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def local(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("Missing or nonlocal video resource")
    return path


def write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    course = load(ROOT / "course.json")
    image_map = {row["source_url"]: row for row in load(ROOT / "assets/images/manifest.json")}
    updates, records = [], []
    report = load(ROOT / "raw/authorized-import-report.json")
    for lesson in course["lessons"]:
        blocks = [row for row in load(local(lesson["raw_blocks_path"])) if row.get("type") == "video"]
        source = load(local(lesson["source_info_path"]))["c"]
        declared = (source.get("article_info") or {}).get("video") or []
        tracks = lesson.get("video") or []
        for kind, key in (("html", "html_path"), ("markdown", "markdown_path")):
            path = local(lesson[key])
            original = path.read_text(encoding="utf-8")
            matches = list(FIGURE.finditer(original))
            if len(matches) != len(blocks):
                raise ValueError("Source video block count differs from its rendered placeholders")
            replacements = []
            for block, match in zip(blocks, matches):
                media_id = str(block.get("mediaId", ""))
                if html.unescape(match[1]) != media_id or len(declared) != 1 or len(tracks) != 1 or str(declared[0].get("dd_media_id_str") or declared[0].get("dd_media_id")) != media_id:
                    raise ValueError("Source video identity has no unique local track mapping")
                track = tracks[0]
                target = local(track["path"])
                if track.get("sha256") and digest(target) != track["sha256"]:
                    raise ValueError("Local video hash differs from the verified manifest")
                src = Path(os.path.relpath(target, path.parent)).as_posix()
                title = html.escape(str(block.get("title", "")), quote=True)
                poster = ""
                if block.get("poster"):
                    image = image_map.get(block["poster"])
                    if not image or digest(local(image["path"])) != image["sha256"]:
                        raise ValueError("Source video poster is missing or changed")
                    poster = ' poster="' + html.escape(Path(os.path.relpath(local(image["path"]), path.parent)).as_posix(), quote=True) + '"'
                inner = '<video controls playsinline preload="none" src="' + html.escape(src, quote=True) + '"' + poster + '></video><figcaption>' + title + '</figcaption>'
                if kind == "markdown":
                    inner = inner.replace("\n", "&#10;")
                replacements.append((match.start(2), match.end(2), inner))
                records.append({"lesson_id": str(lesson["id"]), "kind": kind, "source_media_id": media_id, "path": track["path"]})
            linked = original
            for start, end, replacement in reversed(replacements):
                linked = linked[:start] + replacement + linked[end:]
            if args.check and linked != original:
                raise ValueError("A source video block needs relinking to the current local track")
            if linked != original:
                updates.append((path, linked))
            entry = report["lessons"][str(lesson["id"])]
            entry[kind + "_sha256"] = hashlib.sha256(linked.encode()).hexdigest()
    if not args.check:
        for path, content in updates:
            path.write_text(content, encoding="utf-8")
        write(ROOT / "raw/authorized-import-report.json", report)
        write(ROOT / "raw/video-inline-link-report.json", {"status": "passed", "checked_at_utc": datetime.now(timezone.utc).isoformat(), "method": "Source mediaId matched uniquely to declared video and verified local track; body positions and source titles retained", "linked_blocks": records, "changed_files": len(updates)})
    print(json.dumps({"check_only": args.check, "linked_blocks": len(records), "changed_files": len(updates)}))


if __name__ == "__main__":
    main()
