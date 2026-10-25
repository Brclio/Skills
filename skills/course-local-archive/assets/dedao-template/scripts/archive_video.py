#!/usr/bin/env python3
"""Save source-provided course videos and validate their exact bytes.

This downloader never discovers alternate URLs or removes media protection.
DRM source files that fail standard decoding remain clearly labelled .enc.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "raw/video-archive-report.json"
PRINT_LOCK = threading.Lock()


def log(message):
    with PRINT_LOCK:
        print(message, flush=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, target, previous=None):
    """Range-resume incomplete downloads; reuse only previously hashed files."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if previous and target.is_file() and target.stat().st_size == previous.get("bytes"):
        if digest(target) == previous.get("sha256"):
            return {key: previous[key] for key in ("bytes", "sha256", "md5", "etag", "content_length", "content_length_matches", "etag_md5_matches") if key in previous}
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, 4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.dedao.cn/"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                append = response.status == 206 and offset > 0
                length = int(response.headers.get("Content-Length") or 0)
                expected = (offset if append else 0) + length if length else None
                content_range = response.headers.get("Content-Range", "")
                if append and "/" in content_range:
                    expected = int(content_range.rsplit("/", 1)[1])
                etag = response.headers.get("ETag", "").strip('"')
                started = time.monotonic()
                with part.open("ab" if append else "wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        if time.monotonic() - started > 300:
                            raise TimeoutError("Download exceeded 300 seconds")
            size = part.stat().st_size
            if expected is not None and size != expected:
                raise ValueError(f"Incomplete source bytes: {size}/{expected}")
            md5 = digest(part, "md5")
            etag_matches = md5.lower() == etag.lower() if re.fullmatch(r"[a-fA-F0-9]{32}", etag) else None
            if etag_matches is False:
                part.unlink()
                raise ValueError("Source ETag MD5 did not match the downloaded bytes")
            part.replace(target)
            return {"bytes": size, "sha256": digest(target), "md5": md5, "etag": etag, "content_length": expected, "content_length_matches": expected == size, "etag_md5_matches": etag_matches}
        except Exception as error:
            if attempt == 3:
                raise
            log(f"retry {target.name} {attempt}: {type(error).__name__}")
            time.sleep(attempt)


def run(command, timeout=300):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr[:3000]}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "Validation exceeded 300 seconds"}


def archive(item, previous):
    lid, index, title, video = item
    key = f"{lid}-{index}"
    old = previous.get(key)
    resolution = next((n for n in (1080, 720, 480) if video.get(f"bitrate_{n}")), None)
    result = {"key": key, "lesson_id": lid, "video_index": index, "title": title, "source_media_id": str(video.get("dd_media_id_str") or video.get("dd_media_id") or ""), "source_declares_drm": bool(video.get("is_drm")), "source_duration": video.get("duration"), "resolution_selected": resolution, "available_resolutions": [n for n in (1080, 720, 480) if video.get(f"bitrate_{n}")], "subtitles": []}
    if not resolution:
        return {**result, "status": "source_url_missing", "playable": False}
    url = video[f"bitrate_{resolution}"]
    name = lid + (f"-{index}" if index else "")
    target = ROOT / "assets/video/encrypted" / (name + ".mp4.enc")
    # Before the report existed, the shortest source was retained for the probe.
    initial_sample = ROOT / "assets/video" / (name + ".mp4")
    if initial_sample.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        initial_sample.replace(target)
    try:
        result.update(download(url, target, old))
        result.update({"source_url": url, "path": target.relative_to(ROOT).as_posix(), "download_complete": True})
        with target.open("rb") as f:
            prefix = f.read(16)
        result["has_mp4_ftyp_header"] = prefix[4:8] == b"ftyp"
        probe = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)])
        decode = run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(target), "-f", "null", "-"])
        result["probe"] = {"returncode": probe["returncode"], "stderr": probe["stderr"]}
        if probe["returncode"] == 0:
            result["probe"]["data"] = json.loads(probe["stdout"])
        result["decode"] = {"returncode": decode["returncode"], "stderr": decode["stderr"]}
        result["playable"] = probe["returncode"] == 0 and decode["returncode"] == 0
        if result["playable"]:
            final = ROOT / "assets/video" / (name + ".mp4")
            target.replace(final)
            result["path"] = final.relative_to(ROOT).as_posix()
            result["status"] = "complete"
        else:
            result["status"] = "drm_source_saved_unplayable" if result["source_declares_drm"] else "source_saved_unplayable"
        for field in ("caption", "vtt_caption"):
            caption = video.get(field)
            if isinstance(caption, str) and caption.startswith(("https://", "http://")):
                caption_target = ROOT / "assets/subtitles" / (name + (".vtt" if field == "vtt_caption" else ".srt"))
                metadata = download(caption, caption_target)
                result["subtitles"].append({"field": field, "source_url": caption, "path": caption_target.relative_to(ROOT).as_posix(), **metadata})
    except Exception as error:
        result.update({"status": "failed", "playable": False, "error": f"{type(error).__name__}: {error}"})
    log(f"video {key}: {result['status']} {result.get('bytes', 0):,} bytes")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "raw/authorized-course.json")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    previous_report = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    previous = {entry["key"]: entry for entry in previous_report.get("videos", [])}
    items = [(str(lesson["id"]), i, lesson["title"], video) for lesson in data["lessons"] for i, video in enumerate((lesson.get("info", {}).get("article_info") or {}).get("video") or [])]
    items.sort(key=lambda item: item[3].get("duration", 0))
    if args.limit:
        items = items[:args.limit]
    report = {"schema_version": 1, "source": "authorized-course.json article_info.video", "source_course_url": data["source_url"], "expected_video_count": sum(len((l.get("info", {}).get("article_info") or {}).get("video") or []) for l in data["lessons"]), "videos": [], "summary": {}}
    def update():
        videos = report["videos"]
        report["summary"] = {"processed": len(videos), "downloaded": sum(v.get("download_complete", False) for v in videos), "playable": sum(v.get("playable", False) for v in videos), "drm_source_saved_unplayable": sum(v["status"] == "drm_source_saved_unplayable" for v in videos), "failed": sum(v["status"] == "failed" for v in videos), "bytes": sum(v.get("bytes", 0) for v in videos), "subtitles": sum(len(v.get("subtitles", [])) for v in videos)}
        report["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_json(REPORT, report)
    with ThreadPoolExecutor(max_workers=max(1, min(3, args.workers))) as executor:
        futures = [executor.submit(archive, item, previous) for item in items]
        for future in as_completed(futures):
            report["videos"].append(future.result())
            update()
    report["videos"].sort(key=lambda v: (int(v["lesson_id"]), v["video_index"]))
    update()
    log(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
