#!/usr/bin/env python3
"""Archive a media URL already returned by an authorized Dedao lesson response.

Uses ffmpeg's standard HLS handling and copies the audio stream into M4A. No
key discovery, guessing, credential extraction, or access-control bypass occurs.
Signed playback URLs and cryptographic key URLs are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from export_public import ROOT, write_json


def public_error(value):
    return re.sub(r"https?://[^\s\]\)\"']+", "[media URL redacted]", value)[-1600:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson-id", required=True)
    parser.add_argument("--info", type=Path, required=True, help="Saved authorized article/info response")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not args.lesson_id.isdigit():
        parser.error("--lesson-id must be a numeric catalog ID")
    info_path = args.info if args.info.is_absolute() else ROOT / args.info
    response = json.loads(info_path.read_text())
    info = response.get("c", response)
    article = info.get("article_info", info)
    if str(article.get("id", info.get("article_id", ""))) != args.lesson_id:
        parser.error("The saved response does not match the requested lesson ID")
    url = article.get("audio", {}).get("mp3_play_url", "")
    if not url.startswith("https://"):
        parser.error("The saved response contains no observed HTTPS audio URL")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        parser.error("ffmpeg and ffprobe are required")
    target = ROOT / "assets/audio" / (args.lesson_id + ".m4a")
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"lesson_id": args.lesson_id, "source_info_path": info_path.relative_to(ROOT).as_posix(), "method": "standard_hls_lossless_audio_remux", "path": target.relative_to(ROOT).as_posix(), "persistent_key_files_saved": False}
    try:
        if not target.is_file() or not target.stat().st_size:
            temporary = target.with_suffix(".part.m4a")
            result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", url, "-vn", "-c:a", "copy", "-movflags", "+faststart", str(temporary)], capture_output=True, text=True, timeout=args.timeout)
            if result.returncode:
                raise RuntimeError(public_error(result.stderr))
            temporary.replace(target)
        probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,sample_rate,channels", "-of", "json", str(target)], capture_output=True, text=True, timeout=30)
        if probe.returncode:
            raise RuntimeError(public_error(probe.stderr))
        metadata = json.loads(probe.stdout)
        decode = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(target), "-f", "null", "-"], capture_output=True, text=True, timeout=args.timeout)
        if decode.returncode:
            raise RuntimeError(public_error(decode.stderr))
        report.update({"status": "complete", "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "ffprobe": metadata, "full_decode_exit_code": decode.returncode})
        course_path = ROOT / "course.json"
        course = json.loads(course_path.read_text())
        for lesson in course["lessons"]:
            if lesson["id"] == args.lesson_id:
                lesson["audio"] = [{"path": report["path"], "label": article.get("audio", {}).get("title") or lesson["title"]}]
                lesson["audio_status"] = "complete"
        course.pop("audio_policy", None)
        write_json(course_path, course)
    except Exception as error:
        report.update({"status": "failed", "error": public_error(str(error))})
    write_json(ROOT / "raw" / f"audio-{args.lesson_id}-report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "complete":
        sys.exit(1)


if __name__ == "__main__":
    main()
