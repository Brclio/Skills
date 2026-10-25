#!/usr/bin/env python3
"""Link archived lesson audio at its original HTML and Markdown block positions.

Reads immutable source blocks and course.json; never downloads media or changes
those inputs. Each generated source-audio block must match its source title and
description in order before its player can be inserted or replaced.
"""
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
BLOCK = re.compile(r'<div class="source-audio">(.*?)</div>', re.S)
PLAYER = re.compile(r'\s*(?:<audio\b[^>]*>\s*</audio>)?\s*', re.S)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def local_path(value):
    if not isinstance(value, str) or not value or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value):
        raise ValueError("An expected course-local path is absent or has a URL scheme")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("An expected local path is outside the course directory")
    return path


def write_json(path, value):
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def link_body(original, blocks, tracks, path, kind):
    matches = list(BLOCK.finditer(original))
    if len(matches) != len(blocks):
        raise ValueError(f"{path.relative_to(ROOT)}: source-audio block count differs from source")
    replacements, verified = [], []
    for block, match in zip(blocks, matches):
        alias = str(block.get("aliasId") or block.get("alias_id") or "")
        expected_prefix = "<p>" + html.escape(str(block.get("title", "")), quote=True) + "</p><p>" + html.escape(str(block.get("desc", "")), quote=True) + "</p>"
        if kind == "markdown":
            expected_prefix = expected_prefix.replace("\n", "&#10;")
        inner = match.group(1)
        if not inner.startswith(expected_prefix) or not PLAYER.fullmatch(inner[len(expected_prefix):]):
            raise ValueError(f"{path.relative_to(ROOT)}: audio title, description or structure differs from source for {alias}")
        track = tracks.get(alias)
        if track is None:
            raise ValueError(f"{path.relative_to(ROOT)}: no archived lesson track maps to {alias}")
        media_path = local_path(track.get("path"))
        if not media_path.is_file() or media_path.stat().st_size == 0:
            raise ValueError(f"{path.relative_to(ROOT)}: audio file is absent or empty for {alias}")
        src = Path(os.path.relpath(media_path, path.parent)).as_posix()
        player = '<audio controls preload="none" src="' + html.escape(src, quote=True) + '"></audio>'
        replacements.append((match.start(), match.end(), '<div class="source-audio">' + expected_prefix + player + '</div>'))
        verified.append({"alias_id": alias, "path": media_path.relative_to(ROOT).as_posix(), "title": block.get("title", "")})
    changed = original
    for start, end, replacement in reversed(replacements):
        changed = changed[:start] + replacement + changed[end:]
    return changed, verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify every inline audio block without writing files")
    args = parser.parse_args()
    course = load(ROOT / "course.json")
    updates, lessons, verified_aliases = [], [], set()
    for lesson in course["lessons"]:
        source = load(local_path(lesson["raw_blocks_path"]))
        blocks = [block for block in source if block.get("type") == "audio"]
        tracks = {}
        for track in lesson.get("audio", []):
            alias = str(track.get("audio_alias_id") or track.get("alias_id") or "")
            if not alias or alias in tracks:
                raise ValueError(f"Lesson {lesson['id']}: missing or duplicate local audio alias")
            tracks[alias] = track
        record = {"id": str(lesson["id"]), "source_audio_blocks": len(blocks), "files": {}}
        for kind, key in (("html", "html_path"), ("markdown", "markdown_path")):
            path = local_path(lesson[key])
            original = path.read_text(encoding="utf-8")
            linked, verified = link_body(original, blocks, tracks, path, kind)
            if args.check and linked != original:
                raise ValueError(f"{path.relative_to(ROOT)}: one or more source audio players need updating")
            record["files"][kind] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(linked.encode("utf-8")), "players_verified": len(verified), "changed": linked != original}
            if linked != original:
                updates.append((path, linked))
            verified_aliases.update(item["alias_id"] for item in verified)
        lessons.append(record)
    # Validate the entire plan first so missing or ambiguous media cannot cause a
    # partial rewrite. Derived provenance is refreshed; raw source files stay put.
    if not args.check:
        for path, content in updates:
            path.write_text(content, encoding="utf-8")
        import_path = ROOT / "raw/authorized-import-report.json"
        report = load(import_path)
        for lesson in lessons:
            entry = report.get("lessons", {}).get(lesson["id"])
            if entry is None:
                continue
            entry["html_sha256"] = lesson["files"]["html"]["sha256"]
            entry["markdown_sha256"] = lesson["files"]["markdown"]["sha256"]
            resolved = [issue for issue in entry.get("issues", []) if issue.get("kind") == "embedded_audio_requires_source" and issue.get("alias_id") in verified_aliases]
            if resolved:
                entry["issues"] = [issue for issue in entry["issues"] if issue not in resolved]
                entry.setdefault("resolved_issues", []).extend({**issue, "resolution": "Exact source alias linked to an archived local audio file", "report_path": "raw/audio-inline-link-report.json"} for issue in resolved)
        report["local_audio_link_report"] = "raw/audio-inline-link-report.json"
        write_json(import_path, report)
        write_json(ROOT / "raw/audio-inline-link-report.json", {"schema_version": 1, "checked_at_utc": datetime.now(timezone.utc).isoformat(), "status": "passed", "source": "Immutable source audio blocks matched by order, title and description; archived lesson tracks matched by exact alias", "summary": {"lessons": len(lessons), "source_audio_blocks": sum(item["source_audio_blocks"] for item in lessons), "unique_audio_aliases": len(verified_aliases), "html_players_verified": sum(item["files"]["html"]["players_verified"] for item in lessons), "markdown_players_verified": sum(item["files"]["markdown"]["players_verified"] for item in lessons), "changed_files": len(updates)}, "lessons": lessons})
    print(json.dumps({"check_only": args.check, "lessons": len(lessons), "unique_audio_aliases": len(verified_aliases), "source_audio_blocks": sum(item["source_audio_blocks"] for item in lessons), "changed_files": len(updates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
