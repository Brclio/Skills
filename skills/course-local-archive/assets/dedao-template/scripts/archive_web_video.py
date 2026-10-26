#!/usr/bin/env python3
"""Archive the authorized Web player's returned HLS at its highest resolution.

Keep source playlists and every referenced TS/key object locally; losslessly
remux the standard HLS into MP4 and decode every retained audio/video stream.
Only source-returned URLs are used. No alternate-path discovery is performed.
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request

from archive_config import expected_video_lesson_ids
from hls_assets import preserve_hls, audit_hls

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "raw/web-video-archive-report.json"
PRINT_LOCK = threading.Lock()


def log(message):
    with PRINT_LOCK:
        print(message, flush=True)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def verified_existing(path, metadata):
    return bool(metadata and path.is_file() and path.stat().st_size == metadata.get("bytes") and digest(path) == metadata.get("sha256"))


def download(url, target, previous=None):
    if previous and previous.get("source_url") == url and verified_existing(target, previous):
        return previous
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.dedao.cn/"})
            with urllib.request.urlopen(request, timeout=90) as response:
                expected = int(response.headers.get("Content-Length") or 0) or None
                etag = response.headers.get("ETag", "").strip('"')
                with part.open("wb") as f:
                    while b := response.read(1024 * 1024):
                        f.write(b)
            size = part.stat().st_size
            if expected is not None and size != expected:
                raise ValueError(f"Incomplete source bytes {size}/{expected}")
            md5 = digest(part, "md5")
            etag_matches = md5.lower() == etag.lower() if re.fullmatch(r"[a-fA-F0-9]{32}", etag) else None
            if etag_matches is False:
                raise ValueError("Source ETag MD5 mismatch")
            part.replace(target)
            return {"source_url": url, "path": target.relative_to(ROOT).as_posix(), "bytes": size, "sha256": digest(target), "md5": md5, "etag": etag, "content_length": expected, "content_length_matches": size == expected if expected else None, "etag_md5_matches": etag_matches}
        except Exception:
            if attempt == 3:
                raise
            time.sleep(attempt)


def command(args, timeout=900):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr[:6000]}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": f"Operation exceeded {timeout} seconds"}


def localize_playlist(folder, source_url):
    report = preserve_hls(source_url, ROOT, folder, timeout=90)
    rows = json.loads((ROOT / report['assets_manifest_path']).read_text())
    report['segment_bytes'] = sum(row['bytes'] for row in rows if row['kind'] == 'segment')
    return report


def archive(item, old):
    lid = str(item["lesson_id"])
    result = {"key": lid, "lesson_id": lid, "title": item["title"], "source_media_id": item.get("source_media_id"), "status": "failed", "playable": False}
    try:
        formats = [(track, form) for track in item["media"].get("tracks", []) for form in track.get("formats", []) if form.get("type") == "video" and form.get("format") == "m3u8" and form.get("url")]
        track, form = max(formats, key=lambda x: int(x[1].get("resolution", 0)))
        result.update({"resolution_selected": form.get("resolution"), "source_duration": track.get("duration"), "source_url": form["url"], "available_resolutions": sorted({f.get("resolution") for _, f in formats})})
        folder = ROOT / "raw/video-hls" / lid
        folder.mkdir(parents=True, exist_ok=True)
        result["hls"] = localize_playlist(folder, form["url"])
        target = ROOT / "assets/video" / (lid + ".mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (old and old.get("source_url") == form["url"] and verified_existing(target, old)):
            temporary = target.with_suffix(".part.mp4")
            mux = command(["ffmpeg", "-nostdin", "-y", "-v", "error", "-allowed_extensions", "ALL", "-protocol_whitelist", "file,crypto,data", "-i", str(ROOT / result["hls"]["local_playlist_path"]), "-map", "0:v", "-map", "0:a", "-c", "copy", "-movflags", "+faststart", str(temporary)], timeout=600)
            result["remux"] = {"returncode": mux["returncode"], "stderr": mux["stderr"], "codec_mode": "copy", "mapping": ["0:v", "0:a"]}
            if mux["returncode"] != 0:
                raise ValueError("Lossless HLS remux failed: " + mux["stderr"][:1500])
            temporary.replace(target)
        else:
            result["remux"] = old.get("remux", {"codec_mode": "copy", "mapping": ["0:v", "0:a"], "reused_verified_output": True})
        probe = command(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)])
        if probe["returncode"] != 0:
            raise ValueError("MP4 probe failed: " + probe["stderr"][:1500])
        probe_data = json.loads(probe["stdout"])
        write_json(folder / "ffprobe.json", probe_data)
        video = [s for s in probe_data["streams"] if s["codec_type"] == "video"]
        audio = [s for s in probe_data["streams"] if s["codec_type"] == "audio"]
        if not video or not audio:
            raise ValueError("Output lacks a required video or audio stream")
        decode = command(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode", "-protocol_whitelist", "file,crypto,data", "-i", str(target), "-map", "0:v", "-map", "0:a", "-progress", "pipe:1", "-nostats", "-f", "null", "-"])
        eof = "progress=end" in decode["stdout"].splitlines()
        result["decode"] = {"returncode": decode["returncode"], "stderr": decode["stderr"], "mapping": ["0:v", "0:a"], "all_audio_video_streams": decode["returncode"] == 0 and eof, "reached_eof": eof, "err_detect":"explode"}
        if decode["returncode"] != 0 or not eof:
            raise ValueError("Complete video/audio decoding failed: " + decode["stderr"][:1500])
        duration = float(probe_data["format"]["duration"])
        difference = abs(duration - result["hls"]["playlist_duration"])
        if difference > 2:
            raise ValueError(f"Duration does not match complete playlist ({difference}s)")
        source_duration = float(result.get("source_duration") or duration)
        if abs(duration - source_duration) > 2:
            raise ValueError(f"Duration differs from source ({duration}/{source_duration})")
        if max(s.get("height", 0) for s in video) < int(form.get("resolution", 0)):
            raise ValueError("Output has less resolution than the selected source format")
        result.update({"status": "complete", "playable": True, "download_complete": True, "path": target.relative_to(ROOT).as_posix(), "bytes": target.stat().st_size, "sha256": digest(target), "duration": duration, "duration_difference_from_playlist": difference, "probe": {"returncode": 0, "stderr":probe["stderr"], "data": probe_data}, "video_stream_count": len(video), "audio_stream_count": len(audio), "all_streams_decoded": True, "conversion": "lossless_remux"})
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    log(f"web video {lid}: {result['status']} {result.get('bytes', 0):,} bytes")
    return result


def _current_track(track):
    value = track.get('path', '')
    path = (ROOT / value).resolve()
    return bool(value and path.is_relative_to(ROOT.resolve()) and verified_existing(path, track))


def _decrypted_tracks(lesson, lid, evidence):
    candidates = lesson.get('video_decrypted_original') or [track for track in lesson.get('video', []) if track.get('path') == f'assets/video/decrypted/{lid}.mp4']
    result = []
    for track in candidates:
        rows = [row for row in evidence if str(row.get('lesson_id')) == lid and row.get('path') == track.get('path')]
        if len(rows) != 1: raise ValueError('Retained decrypted original lacks unique verification evidence')
        row = rows[0]
        source = {'path':row.get('source_path'),'bytes':row.get('source_bytes'),'sha256':row.get('source_sha256')}
        if not (_current_track(track) and _current_track(source) and track.get('path') == f'assets/video/decrypted/{lid}.mp4' and row.get('source_path') == f'assets/video/encrypted/{lid}.mp4.enc' and row.get('decode',{}).get('err_detect') == 'explode' and row.get('status') == 'decrypted_verified' and row.get('sha256') == track.get('sha256') and row.get('bytes') == track.get('bytes') and row.get('source_bytes') == row.get('bytes') and row.get('original_unchanged') is True and row.get('conversion') == 'exact_native_cipher_transform_without_remux' and row.get('probe',{}).get('returncode') == 0 and row.get('decode',{}).get('returncode') == 0 and row.get('decode',{}).get('all_audio_video_streams') is True and row.get('normalized_stream_comparison',{}).get('exact_vcl_and_audio_match') is True):
            raise ValueError('Retained decrypted original differs from verified source/transform evidence')
        result.append(copy.deepcopy(track))
    return result


def apply_report():
    from archive_state import course_lock, compare_and_write_manifest
    with course_lock(ROOT):
        watched = [ROOT/'course.json', REPORT, ROOT/'raw/authorized-course.json', ROOT/'raw/video-archive-report.json', ROOT/'raw/legacy-video-decryption-report.json', ROOT/'course-config.json']
        before = {path:path.read_bytes() if path.exists() else None for path in watched}
        course = json.loads(before[ROOT/'course.json'])
        report = json.loads(before[REPORT])
        rows = report.get('videos', [])
        records = {str(v['lesson_id']):v for v in rows}
        if len(records) != len(rows) or len(records) != report['expected_video_count'] or set(records) != expected_video_lesson_ids(course):
            raise ValueError('Web video report must exactly cover the source-declared lesson set')
        authorized = json.loads(before[ROOT/'raw/authorized-course.json'])
        source_videos = {str(row['id']): (row.get('info',{}).get('article_info') or {}).get('video',[None])[0] for row in authorized['lessons'] if (row.get('info',{}).get('article_info') or {}).get('video')}
        originals_list = json.loads(before[ROOT/'raw/video-archive-report.json']).get('videos', []) if before[ROOT/'raw/video-archive-report.json'] else []
        originals = {str(v['lesson_id']):v for v in originals_list}
        if len(originals) != len(originals_list): raise ValueError('Duplicate source video identities require a separate adapter')
        decrypted_evidence = json.loads(before[ROOT/'raw/legacy-video-decryption-report.json']).get('videos', []) if before[ROOT/'raw/legacy-video-decryption-report.json'] else []
        for lesson in course['lessons']:
            lid = str(lesson['id']); record = records.get(lid)
            if not record:
                lesson['video'] = [];lesson['video_status'] = 'not_applicable'
                continue
            if not (record.get('status') == 'complete' and record.get('playable') and record.get('all_streams_decoded') and _current_track(record)):
                raise ValueError('Only current complete fully decoded Web output may be applied')
            audit_hls(ROOT,record.get('hls',{}))
            poster = ''
            if lesson.get('localized_info_path'):
                info = json.loads((ROOT/lesson['localized_info_path']).read_text())
                videos = (info.get('article_info') or {}).get('video') or []
                poster = videos[0].get('cover_img','') if videos else ''
            web = {'path':record['path'],'label':f"网页源 MP4 · {record['resolution_selected']}p",'duration':record['duration'],'resolution':record['resolution_selected'],'bytes':record['bytes'],'sha256':record['sha256'],'archive_report':REPORT.relative_to(ROOT).as_posix()}
            if poster and (ROOT/poster).is_file(): web['poster'] = poster
            lesson['video_web_alternatives'] = [web]
            choices = [(int(web.get('resolution') or 0), 0, web)]
            original = originals.get(lid)
            if not original or not original.get('download_complete') or not _current_track(original):
                raise ValueError('Current exact source original is required before applying Web output')
            source_video = source_videos[lid]
            current_source_url = source_video.get('bitrate_' + str(original.get('resolution_selected')))
            if int(original.get('video_index',0)) != 0 or str(original.get('source_media_id','')) != str(source_video.get('dd_media_id_str') or source_video.get('dd_media_id') or '') or not current_source_url or original.get('source_url') != current_source_url:
                raise ValueError('Original source URL/media ID/index differs from the authorized source')
            track = {key:original[key] for key in ('path','bytes','sha256','source_media_id','source_url_sha256','video_index','status','source_role') if key in original}
            track['archive_report'] = 'raw/video-archive-report.json'
            if original.get('playable'):
                streams = original.get('probe',{}).get('data',{}).get('streams',[])
                if not (original['path'] == f'assets/video/original/{lid}.mp4' and original.get('source_role') == 'plaintext_original' and original.get('probe',{}).get('returncode') == 0 and original.get('decode',{}).get('returncode') == 0 and original.get('decode',{}).get('all_audio_video_streams') is True and any(s.get('codec_type') == 'audio' for s in streams) and any(s.get('codec_type') == 'video' for s in streams)):
                    raise ValueError('Plaintext source must be independently verified in its dedicated original directory')
                height = max(int(s.get('height') or 0) for s in streams if s.get('codec_type') == 'video')
                track.update(label=f'明文原件 MP4 · {height}p', resolution=height, duration=original['duration'])
                lesson['video_plaintext_original'] = [track]
                lesson.pop('video_encrypted_original', None)
                choices.append((height,1,track))
            elif original.get('source_declares_drm') and original.get('source_role','encrypted_original') == 'encrypted_original' and original.get('status') == 'drm_source_saved_unplayable' and original['path'] == f'assets/video/encrypted/{lid}.mp4.enc':
                lesson['video_encrypted_original'] = [track]
                lesson.pop('video_plaintext_original', None)
            else:
                raise ValueError('Unclassified unplayable source cannot be counted as a verified ciphertext original')
            decrypted = _decrypted_tracks(lesson,lid,decrypted_evidence)
            if decrypted:
                lesson['video_decrypted_original'] = decrypted
                choices += [(int(t.get('resolution') or 0),2,t) for t in decrypted]
            lesson['video'] = [max(choices,key=lambda item:(item[0],item[1]))[2]]
            lesson['video_status'] = 'complete'
        if any((path.read_bytes() if path.exists() else None) != value for path,value in before.items()):
            raise ValueError('Manifest or source evidence changed while applying Web outputs')
        compare_and_write_manifest(ROOT,hashlib.sha256(before[ROOT/'course.json']).hexdigest(),course)
    log(f'Applied {len(records)} verified Web outputs with independent original roles')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "raw/authorized-web-media.json")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--apply-only", action="store_true", help="Apply an existing fully verified report to course.json without network requests")
    args = parser.parse_args()
    if args.apply_only:
        apply_report()
        return
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not data.get("complete") or data.get("errors"):
        raise ValueError("An error-free complete source media export is required")
    previous = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    previous_by_lesson = {v["lesson_id"]: v for v in previous.get("videos", [])}
    ids = [str(v["lesson_id"]) for v in data["videos"]]
    if set(ids) != expected_video_lesson_ids():
        raise ValueError("Web media export differs from the source-declared video lesson set")
    if len(ids) != len(set(ids)):
        raise ValueError("Source video lesson IDs must be unique")
    report = {"schema_version": 1, "source": "authorized same-origin Web media formats", "expected_video_count": len(ids), "videos": [], "summary": {}}
    def update():
        videos = report["videos"]
        report["summary"] = {"processed": len(videos), "downloaded": sum(v.get("download_complete", False) for v in videos), "playable": sum(v.get("playable", False) for v in videos), "failed": sum(v["status"] != "complete" for v in videos), "bytes": sum(v.get("bytes", 0) for v in videos), "hls_segments": sum(v.get("hls", {}).get("segments", 0) for v in videos), "hls_segment_bytes": sum(v.get("hls", {}).get("segment_bytes", 0) for v in videos), "all_have_video_and_audio": all(v.get("video_stream_count", 0) > 0 and v.get("audio_stream_count", 0) > 0 for v in videos), "all_fully_decoded": all(v.get("all_streams_decoded", False) for v in videos)}
        report["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_json(REPORT, report)
    with ThreadPoolExecutor(max_workers=max(1, min(3, args.workers))) as executor:
        futures = [executor.submit(archive, item, previous_by_lesson.get(str(item["lesson_id"]))) for item in data["videos"]]
        for future in as_completed(futures):
            report["videos"].append(future.result())
            update()
    order = {lid: i for i, lid in enumerate(ids)}
    report["videos"].sort(key=lambda v: order[v["lesson_id"]])
    update()
    log(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
