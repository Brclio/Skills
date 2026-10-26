#!/usr/bin/env python3
"""Archive audio URLs in saved authorized course responses; apply results separately.

Download: python3 scripts/archive_all_audio.py --input raw/authorized-course.json
Merge:    python3 scripts/archive_all_audio.py --apply

Reports contain audio aliases and URL fingerprints, never signed URLs or keys.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from hls_assets import preserve_hls, audit_hls, audio_packet_proof

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "raw/audio-archive"
MEDIA_DIR = ROOT / "assets/audio"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def public_error(error):
    if isinstance(error, subprocess.TimeoutExpired):
        return "Media operation exceeded its configured timeout."
    value = re.sub(r"(?:https?|file)://[^\s\]\)\"'<>]+", "[URL redacted]", str(error))
    value = re.sub(r"(?i)(token|signature|authorization|key)=([^\s&]+)", r"\1=[redacted]", value)
    return value[-1600:]


def unwrap(value):
    while isinstance(value, dict) and "c" in value and "article_info" not in value:
        value = value["c"]
    return value if isinstance(value, dict) else {}


def duration_seconds(value):
    try:
        if isinstance(value, str) and ":" in value:
            result = 0.0
            for part in value.split(":"):
                result = result * 60 + float(part)
            return result
        result = float(value or 0)
        return result if result > 0 else None
    except (ValueError, TypeError):
        return None


def normalize_aliases(value):
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return list(dict.fromkeys(str(alias) for alias in value if alias))


def embedded_audio_blocks(body):
    content = body.get("content", []) if isinstance(body, dict) else []
    if isinstance(content, str):
        content = json.loads(content)
    result = []
    def walk(value):
        if isinstance(value, dict):
            if str(value.get("type", "")).lower() == "audio":
                alias = value.get("aliasId") or value.get("alias_id")
                if alias and not any(item["alias_id"] == str(alias) for item in result):
                    result.append({"alias_id": str(alias), "title": value.get("title", ""), "aid": str(value.get("aid", "")), "expected_duration_seconds": duration_seconds(value.get("duration"))})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(content)
    return result


def load_lessons(path):
    """Accept a full export, the importer's queue, or per-lesson saved info."""
    if path.is_dir():
        result = []
        for info_path in sorted(path.glob("*.info.json")):
            result.extend(load_lessons(info_path))
        return result
    saved = json.loads(path.read_text(encoding="utf-8"))
    rows = saved.get("lessons") if isinstance(saved, dict) else None
    if rows is None:
        info = unwrap(saved)
        article = info.get("article_info", info)
        rows = [{"id": article.get("id"), "title": article.get("title"), "info": info}]
    result, seen = [], set()
    for row in rows:
        info = unwrap(row.get("info", {}))
        if not info and row.get("source_info_path"):
            info_path = (ROOT / row["source_info_path"]).resolve()
            if not info_path.is_relative_to(ROOT):
                raise ValueError("Source info path is outside the course directory")
            if info_path.is_file():
                info = unwrap(json.loads(info_path.read_text(encoding="utf-8")))
        article = info.get("article_info", info)
        lesson_id = str(row.get("id") or article.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", lesson_id):
            raise ValueError("Every audio entry must have a valid lesson ID")
        if lesson_id in seen:
            raise ValueError(f"Duplicate lesson ID: {lesson_id}")
        seen.add(lesson_id)
        audio = article.get("audio")
        audio = audio if isinstance(audio, dict) else {}
        aliases = normalize_aliases(article.get("audio_alias_ids") or row.get("audio_alias_ids"))
        embedded = embedded_audio_blocks(row.get("body"))
        for block in embedded:
            if block["alias_id"] not in aliases:
                aliases.append(block["alias_id"])
        alias_id = str(audio.get("alias_id") or row.get("audio_alias_id") or "")
        if not alias_id and len(aliases) == 1:
            alias_id = aliases[0]
        if alias_id and alias_id not in aliases:
            aliases.append(alias_id)
        url = audio.get("mp3_play_url") or row.get("audio_url") or ""
        if url and urlsplit(url).scheme not in {"https", "http"}:
            raise ValueError(f"Unsupported media URL scheme in lesson {lesson_id}")
        expected = duration_seconds(audio.get("duration") or row.get("expected_duration"))
        observed_audio_field = "audio" in article
        # The current server omits ``audio`` for text-only lessons but explicitly
        # returns an empty audio_alias_ids array. Treat that observed declaration
        # as no audio only when the body also contains no embedded audio alias.
        declared_empty_aliases = isinstance(article.get("audio_alias_ids"), list) and not article["audio_alias_ids"]
        no_audio_declared = not aliases and not audio and (observed_audio_field or declared_empty_aliases)
        state = "pending" if url else ("no_audio" if no_audio_declared else "metadata_unavailable")
        result.append({
            "lesson_id": lesson_id,
            "title": str(row.get("title") or article.get("title") or lesson_id),
            "label": str(audio.get("title") or row.get("audio_title") or row.get("title") or lesson_id),
            "audio_alias_id": alias_id,
            "declared_audio_alias_ids": aliases,
            "unresolved_audio_alias_ids": [alias for alias in aliases if alias != alias_id],
            "embedded_audio": embedded,
            "expected_duration_seconds": expected,
            "source_info_path": row.get("source_info_path") or relative(path),
            "status": state,
            "_url": url,
        })
    return result


def command(args, timeout):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(public_error(result.stderr) or f"Media command exited {result.returncode}")
    return result


def validate(path, expected, timeout, cached=None):
    if not path.is_file() or not path.stat().st_size:
        raise ValueError("Local audio file is absent or empty")
    sha256 = digest(path)
    if cached and cached.get("status") == "complete" and cached.get("sha256") == sha256 and cached.get("full_decode_exit_code") == 0 and cached.get('validation_schema_version') == 2 and cached.get('all_audio_streams_decoded') is True and cached.get('full_decode', {}).get('reached_eof') is True:
        metadata = cached["ffprobe"]
        probe_stderr = cached.get('ffprobe_stderr', '')
        decode_evidence = cached['full_decode']
        reused_validation = True
    else:
        probe = command(["ffprobe", "-v", "error", "-protocol_whitelist", "file,crypto,data", "-show_entries", "format=duration,size,format_name:stream=index,codec_type,codec_name,sample_rate,channels,duration", "-of", "json", str(path)], min(timeout, 60))
        metadata = json.loads(probe.stdout)
        probe_stderr = public_error(probe.stderr)
        if not any(stream.get('codec_type') == 'audio' for stream in metadata.get("streams", [])):
            raise ValueError("No audio stream was found")
        decoded = command(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-err_detect", "explode", "-protocol_whitelist", "file,crypto,data", "-i", str(path), "-map", "0:a", "-progress", "pipe:1", "-nostats", "-f", "null", "-"], timeout)
        reached_eof = 'progress=end' in decoded.stdout.splitlines()
        if not reached_eof: raise ValueError('Audio decoder did not report end of file')
        decode_evidence = {'returncode':decoded.returncode, 'stderr':public_error(decoded.stderr), 'mapped_audio_streams':'all', 'reached_eof':reached_eof}
        reused_validation = False
    actual = duration_seconds(metadata.get("format", {}).get("duration"))
    if not actual:
        raise ValueError("Local audio has no positive duration")
    difference = abs(actual - expected) if expected else None
    tolerance = max(3.0, expected * 0.02) if expected else None
    if difference is not None and difference > tolerance:
        raise ValueError(f"Audio duration mismatch: expected {expected:.3f}s, saved {actual:.3f}s, tolerance {tolerance:.3f}s")
    return {"bytes": path.stat().st_size, "sha256": sha256, "duration_seconds": actual, "expected_duration_seconds": expected, "duration_difference_seconds": difference, "duration_check": "passed" if expected else "not_available", "ffprobe": metadata, 'ffprobe_stderr':probe_stderr, 'full_decode':decode_evidence, "full_decode_exit_code": 0, "cached_validation_reused": reused_validation, 'validation_schema_version':2, 'all_audio_streams_decoded':True, 'audio_stream_count':sum(stream.get('codec_type') == 'audio' for stream in metadata.get('streams', []))}


def download_direct(url, destination, timeout):
    started = time.monotonic()
    request = Request(url, headers={"User-Agent": "CourseLocalArchive/1.0"})
    with urlopen(request, timeout=min(timeout, 45)) as response, destination.open("wb") as output:
        expected = int(response.headers.get('Content-Length') or 0) or None
        while True:
            if time.monotonic() - started > timeout:
                raise TimeoutError("Media download exceeded its configured timeout.")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    if expected is not None and destination.stat().st_size != expected:
        raise ValueError('Original audio download Content-Length differs from actual bytes')


def archive_media(job, report_dir, timeout, retries):
    entry = job["entry"]
    lesson_id, url = entry["lesson_id"], entry["_url"]
    url_path = urlsplit(url).path.lower()
    suffix = Path(url_path).suffix
    direct = suffix in {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus"}
    suffix = suffix if direct else ".m4a"
    target = MEDIA_DIR / (job.get("filename_stem", lesson_id) + suffix)
    report_path = report_dir / "media" / (job["media_id"] + ".json")
    previous = json.loads(report_path.read_text()) if report_path.is_file() else None
    report = {"media_id": job["media_id"], "lesson_ids": job["lesson_ids"], "audio_alias_id": entry["audio_alias_id"], "source_url_sha256": hashlib.sha256(url.encode()).hexdigest(), "source_info_path": entry["source_info_path"], "label": entry["label"], "path": relative(target), "method": "original_bytes" if direct else "standard_hls_lossless_audio_remux", "persistent_key_files_saved": False}
    if not direct:
        report['hls'] = preserve_hls(url, ROOT, Path('raw/audio-hls') / job['media_id'], timeout=min(timeout, 60))
        report['persistent_key_files_saved'] = bool(report['hls']['keys'])
        report['raw_audio_hls_preservation'] = audit_hls(ROOT, report['hls'])
    # A prior successful file is still hashed on every run; a matching full-decode
    # report may avoid decoding it twice. Existing legacy files are decoded once.
    if target.is_file():
        try:
            if direct and (not previous or previous.get('source_url_sha256') != report['source_url_sha256']):
                raise ValueError('Original-byte audio reuse requires a current source URL fingerprint')
            if previous and previous.get("audio_alias_id") != entry["audio_alias_id"]:
                raise ValueError("The saved audio alias differs from the requested alias")
            report.update(validate(target, entry["expected_duration_seconds"], timeout, previous))
            if not direct:
                report['hls_audio_packet_proof'] = audio_packet_proof(ROOT, report['hls'], target, timeout)
            report.update({"status": "complete", "attempts": 0, "download_reused": True})
            write_json(report_path, report)
            return report
        except Exception:
            pass
    temporary = target.with_name(target.stem + ".part" + target.suffix)
    errors = []
    for attempt in range(retries + 1):
        try:
            temporary.unlink(missing_ok=True)
            if direct:
                download_direct(url, temporary, timeout)
            else:
                command(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-allowed_extensions", "ALL", "-protocol_whitelist", "file,crypto,data", "-i", str(ROOT / report['hls']['local_playlist_path']), "-map", "0:a", "-vn", "-c:a", "copy", "-movflags", "+faststart", str(temporary)], timeout)
            verification = validate(temporary, entry["expected_duration_seconds"], timeout)
            if not direct:
                report['hls_audio_packet_proof'] = audio_packet_proof(ROOT, report['hls'], temporary, timeout)
            temporary.replace(target)
            if not direct:
                report['hls_audio_packet_proof']['output_path'] = relative(target)
            report.update(verification)
            report.update({"status": "complete", "attempts": attempt + 1, "download_reused": False})
            write_json(report_path, report)
            return report
        except Exception as error:
            errors.append(public_error(error))
            temporary.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2 ** (attempt + 1), 8))
    report.update({"status": "failed", "attempts": retries + 1, "errors": errors})
    write_json(report_path, report)
    return report


def public_entry(entry):
    return {key: value for key, value in entry.items() if not key.startswith("_")}


def load_extra_audio(path):
    if not path or not path.is_file():
        return {}
    saved = json.loads(path.read_text(encoding="utf-8"))
    rows = saved.get("audios", saved.get("audio", [])) if isinstance(saved, dict) else saved
    if not isinstance(rows, list):
        raise ValueError("Supplemental audio export must contain an audios array")
    result = {}
    for row in rows:
        audio = row.get("audio", row)
        alias = str(audio.get("alias_id") or row.get("alias_id") or "")
        url = audio.get("mp3_play_url") or row.get("audio_url")
        if not alias or not url or urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Supplemental audio requires an observed alias and HTTP playback URL")
        result[alias] = {"audio_alias_id": alias, "label": audio.get("title") or row.get("title"), "_url": url, "lesson_id": str(row.get("lesson_id", "")), "expected_duration_seconds": duration_seconds(audio.get("duration") or row.get("expected_duration")), "source_info_path": relative(path)}
    return result


def run_download(input_path, report_dir, workers, timeout, retries, extra_path=None):
    lessons = load_lessons(input_path)
    extra = load_extra_audio(extra_path)
    jobs = {}

    def add_track(entry, track, filename_stem):
        identity = track["audio_alias_id"] or track["_url"]
        media_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        job = jobs.setdefault(media_id, {"media_id": media_id, "entry": track, "filename_stem": filename_stem, "lesson_ids": []})
        if entry["lesson_id"] not in job["lesson_ids"]:
            job["lesson_ids"].append(entry["lesson_id"])
        entry["_tracks"].append({"media_id": media_id, "label": track["label"], "audio_alias_id": track["audio_alias_id"], "expected_duration_seconds": track["expected_duration_seconds"]})

    for entry in lessons:
        entry["_tracks"] = []
        unresolved = list(entry["declared_audio_alias_ids"])
        if entry["_url"]:
            add_track(entry, entry, entry["lesson_id"])
            if entry["audio_alias_id"] in unresolved:
                unresolved.remove(entry["audio_alias_id"])
        for alias in list(unresolved):
            if alias not in extra:
                continue
            supplemental = dict(extra[alias])
            if supplemental["lesson_id"] and supplemental["lesson_id"] != entry["lesson_id"]:
                raise ValueError("Supplemental audio alias belongs to a different lesson")
            block = next((block for block in entry["embedded_audio"] if block["alias_id"] == alias), {})
            supplemental["lesson_id"] = entry["lesson_id"]
            supplemental["label"] = supplemental.get("label") or block.get("title") or entry["title"]
            supplemental["expected_duration_seconds"] = supplemental.get("expected_duration_seconds") or block.get("expected_duration_seconds")
            stem = entry["lesson_id"] if alias == entry["audio_alias_id"] else entry["lesson_id"] + "-" + re.sub(r"[^A-Za-z0-9_-]", "_", alias)
            add_track(entry, supplemental, stem)
            unresolved.remove(alias)
        entry["unresolved_audio_alias_ids"] = unresolved
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(archive_media, job, report_dir, timeout, retries): media_id for media_id, job in jobs.items()}
        for future in as_completed(futures):
            media_id = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"media_id": media_id, "status": "failed", "errors": [public_error(error)], "lesson_ids": jobs[media_id]["lesson_ids"]}
            results[media_id] = result
            print(json.dumps({"done": len(results), "total_media": len(jobs), "lesson_ids": result["lesson_ids"], "status": result["status"]}, ensure_ascii=False), flush=True)
    public_lessons = []
    for entry in lessons:
        record = public_entry(entry)
        tracks, errors = [], []
        for track in entry["_tracks"]:
            media = results[track["media_id"]]
            if media["status"] != "complete":
                errors.extend(media.get("errors", []))
                continue
            expected = track["expected_duration_seconds"]
            if expected and abs(media["duration_seconds"] - expected) > max(3.0, expected * 0.02):
                errors.append("Shared audio alias has inconsistent expected duration metadata")
                continue
            tracks.append({"path": media["path"], "label": track["label"], "audio_alias_id": track["audio_alias_id"], "media_id": track["media_id"], "source_url_sha256":media["source_url_sha256"], "bytes":media["bytes"], "sha256":media["sha256"], "duration":media["duration_seconds"], "archive_report":relative(report_dir / "media" / (track["media_id"] + ".json"))})
        record["audio"] = tracks
        if tracks:
            record["status"] = "partial" if errors or entry["unresolved_audio_alias_ids"] else "complete"
        elif errors:
            record["status"] = "failed"
        else:
            record["status"] = "no_audio" if entry["status"] == "no_audio" else "metadata_unavailable"
        if errors:
            record["errors"] = errors
        write_json(report_dir / "lessons" / (entry["lesson_id"] + ".json"), record)
        public_lessons.append(record)
    summary = {"lessons": len(lessons), "unique_media": len(jobs), "downloaded_media": sum(r["status"] == "complete" and not r.get("download_reused") for r in results.values()), "reused_media": sum(r["status"] == "complete" and r.get("download_reused", False) for r in results.values()), "unresolved_audio_aliases": sum(len(entry["unresolved_audio_alias_ids"]) for entry in public_lessons)}
    for status in ("complete", "partial", "no_audio", "metadata_unavailable", "failed"):
        summary[status + "_lessons"] = sum(entry["status"] == status for entry in public_lessons)
    manifest = {"schema_version": 1, "checked_at_utc": datetime.now(timezone.utc).isoformat(), "input_path": relative(input_path), "extra_audio_path": relative(extra_path) if extra_path and extra_path.is_file() else None, "summary": summary, "lessons": public_lessons, "media": list(results.values())}
    write_json(report_dir / "manifest.json", manifest)
    write_json(report_dir / "media-manifest.json", {"schema_version": 1, "media": manifest["media"]})
    print(json.dumps({"manifest_path": relative(report_dir / "manifest.json"), "summary": summary}, ensure_ascii=False), flush=True)
    return manifest


def apply_manifest(report_dir, course_path):
    from archive_state import course_lock
    with course_lock(ROOT):
        return _apply_manifest_locked(report_dir, course_path)


def _apply_manifest_locked(report_dir, course_path):
    manifest_path = report_dir / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    manifest = json.loads(manifest_before)
    before = course_path.read_bytes()
    course = json.loads(before)
    lookup = {str(lesson["id"]): lesson for lesson in course["lessons"]}
    media = {item["media_id"]: item for item in manifest["media"]}
    checked_media = set()
    for entry in manifest["lessons"]:
        if entry["lesson_id"] not in lookup:
            raise ValueError("Audio manifest contains a lesson absent from course.json")
        lesson = lookup[entry["lesson_id"]]
        if entry["status"] in {"complete", "partial"}:
            for track in entry["audio"]:
                item = media[track["media_id"]]
                if item.get('status') != 'complete' or item.get('audio_alias_id') != track.get('audio_alias_id') or item.get('path') != track.get('path'):
                    raise ValueError('Audio track differs from its completed alias/source report')
                track.update(source_url_sha256=item['source_url_sha256'], bytes=item['bytes'], sha256=item['sha256'], duration=item['duration_seconds'], archive_report=relative(report_dir / 'media' / (item['media_id'] + '.json')))
                if item['media_id'] in checked_media:
                    continue
                path = (ROOT / item["path"]).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file() or digest(path) != item["sha256"]:
                    raise ValueError("A verified audio file changed; refusing to apply the manifest")
                if item.get('method') == 'standard_hls_lossless_audio_remux':
                    if not item.get('hls'):
                        raise ValueError('Old audio HLS reports require rerunning the downloader to preserve raw source objects')
                    audit_hls(ROOT, item['hls'])
                    packet = item.get('hls_audio_packet_proof', {})
                    if item['hls'].get('source_url_sha256') != item.get('source_url_sha256') or packet.get('status') != 'passed' or packet.get('all_audio_packets_exact_match') is not True or packet.get('output_path') != item['path'] or packet.get('output_sha256') != item['sha256']:
                        raise ValueError('Audio HLS/source-output packet proof is absent or not current')
                checked_media.add(item['media_id'])
            lesson["audio"] = entry["audio"]
        elif entry["status"] == "no_audio":
            lesson["audio"] = []
        lesson["audio_status"] = "not_applicable" if entry["status"] == "no_audio" else entry["status"]
        lesson["audio_archive"] = {"report_path": relative(report_dir / "lessons" / (entry["lesson_id"] + ".json")), "audio_alias_id": entry["audio_alias_id"], "declared_audio_alias_ids": entry["declared_audio_alias_ids"], "unresolved_audio_alias_ids": entry["unresolved_audio_alias_ids"]}
    if course_path.read_bytes() != before or manifest_path.read_bytes() != manifest_before:
        raise RuntimeError("course.json changed during the merge; retry after the other import finishes")
    course.pop("audio_policy", None)
    write_json(course_path, course)
    print(json.dumps({"applied": True, "manifest_path": relative(manifest_path), "summary": manifest["summary"]}, ensure_ascii=False))


def within_root(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise argparse.ArgumentTypeError("Path must be inside the course directory")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="raw/authorized-course.json", type=within_root)
    parser.add_argument("--report-dir", default=REPORT_DIR, type=within_root)
    parser.add_argument("--extra-audio", default="raw/authorized-extra-audio.json", type=within_root, help="Optional saved playback metadata for embedded audio aliases")
    parser.add_argument("--course", default="course.json", type=within_root)
    parser.add_argument("--workers", default=4, type=int)
    parser.add_argument("--timeout", default=300, type=int, help="Timeout seconds for each download or validation operation")
    parser.add_argument("--retries", default=3, type=int, help="Maximum retries after the first attempt")
    parser.add_argument("--apply", action="store_true", help="Merge an existing manifest only; performs no downloads")
    args = parser.parse_args()
    try:
        if args.apply:
            apply_manifest(args.report_dir, args.course)
            return
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            parser.error("ffmpeg and ffprobe are required")
        if args.workers < 1 or args.workers > 8 or args.timeout < 1 or args.retries < 0 or args.retries > 3:
            parser.error("Use 1-8 workers, a positive timeout, and 0-3 retries")
        manifest = run_download(args.input, args.report_dir, args.workers, args.timeout, args.retries, args.extra_audio)
        if manifest["summary"]["failed_lessons"] or manifest["summary"]["metadata_unavailable_lessons"] or manifest["summary"]["partial_lessons"]:
            sys.exit(2)
    except Exception as error:
        print(public_error(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
