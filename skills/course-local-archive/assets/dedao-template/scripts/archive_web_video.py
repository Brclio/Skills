#!/usr/bin/env python3
"""Archive the authorized Web player's returned HLS at its highest resolution.

Keep source playlists and every referenced TS/key object locally; losslessly
remux the standard HLS into MP4 and decode every retained audio/video stream.
Only source-returned URLs are used. No alternate-path discovery is performed.
"""
from __future__ import annotations

import argparse
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
    assets_path = folder / "assets.json"
    old = json.loads(assets_path.read_text()) if assets_path.exists() else []
    previous = {entry["source_url"]: entry for entry in old}
    assets = []
    source = download(source_url, folder / "source.m3u8", previous.get(source_url))
    assets.append(source)
    text = (folder / "source.m3u8").read_text(encoding="utf-8-sig")
    if not text.startswith("#EXTM3U"):
        raise ValueError("Source did not return a standard HLS playlist")
    if "#EXT-X-STREAM-INF" in text:
        raise ValueError("Expected returned format to be a media playlist, received a master playlist")
    if "#EXT-X-BYTERANGE" in text:
        raise ValueError("Byte-range HLS requires explicit local range handling")
    if 'METHOD=SAMPLE-AES' in text or 'KEYFORMAT=' in text:
        raise ValueError("Source HLS uses a protected format beyond standard AES-128")
    durations = [float(x) for x in re.findall(r"#EXTINF:([0-9.]+)", text)]
    encryption_methods = sorted(set(re.findall(r"#EXT-X-KEY:METHOD=([^,\r\n]+)", text)))
    names = set()
    saved = {}

    def local_resource(uri, kind="segment"):
        url = urllib.parse.urljoin(source_url, uri)
        if url in saved:
            return saved[url]
        name = Path(urllib.parse.urlparse(uri).path).name
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name or "") or name in names or name in {"source.m3u8", "local.m3u8", "assets.json", "ffprobe.json"}:
            extension = Path(name).suffix if name else (".key" if kind == "key" else ".ts")
            name = kind + "-" + hashlib.sha256(url.encode()).hexdigest()[:16] + extension
        names.add(name)
        metadata = download(url, folder / name, previous.get(url))
        metadata["kind"] = kind
        assets.append(metadata)
        # Persist after each resource so rerunning resumes verified resources.
        write_json(assets_path, assets)
        saved[url] = name
        return name

    lines = []
    segment_count = 0
    for line in text.splitlines():
        if line.startswith("#") and 'URI="' in line:
            kind = "key" if line.startswith("#EXT-X-KEY") else "initialization"
            line = re.sub(r'URI="([^\"]+)"', lambda match: 'URI="' + local_resource(match.group(1), kind) + '"', line)
        elif line and not line.startswith("#"):
            line = local_resource(line.strip())
            segment_count += 1
        lines.append(line)
    if not segment_count or not durations or "#EXT-X-ENDLIST" not in text:
        raise ValueError("Source playlist was incomplete or not a finite VOD")
    if segment_count != len(durations):
        raise ValueError("HLS segment/duration count mismatch")
    local = folder / "local.m3u8"
    local.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(assets_path, assets)
    return {"source_playlist": source, "local_playlist_path": local.relative_to(ROOT).as_posix(), "local_playlist_sha256": digest(local), "assets_manifest_path": assets_path.relative_to(ROOT).as_posix(), "segments": segment_count, "segment_bytes": sum(a["bytes"] for a in assets if a.get("kind") == "segment"), "playlist_duration": sum(durations), "encryption_methods": encryption_methods}


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
            mux = command(["ffmpeg", "-nostdin", "-y", "-v", "error", "-allowed_extensions", "ALL", "-i", str(ROOT / result["hls"]["local_playlist_path"]), "-map", "0:v", "-map", "0:a", "-c", "copy", "-movflags", "+faststart", str(temporary)], timeout=600)
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
        decode = command(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(target), "-map", "0:v", "-map", "0:a", "-f", "null", "-"])
        result["decode"] = {"returncode": decode["returncode"], "stderr": decode["stderr"], "mapping": ["0:v", "0:a"]}
        if decode["returncode"] != 0:
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
        result.update({"status": "complete", "playable": True, "download_complete": True, "path": target.relative_to(ROOT).as_posix(), "bytes": target.stat().st_size, "sha256": digest(target), "duration": duration, "duration_difference_from_playlist": difference, "probe": {"returncode": 0, "data": probe_data}, "video_stream_count": len(video), "audio_stream_count": len(audio), "all_streams_decoded": True, "conversion": "lossless_remux"})
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    log(f"web video {lid}: {result['status']} {result.get('bytes', 0):,} bytes")
    return result


def apply_report():
    report = json.loads(REPORT.read_text())
    records = {str(v["lesson_id"]): v for v in report["videos"]}
    if len(records) != report["expected_video_count"] or not all(v.get("status") == "complete" and v.get("playable") and v.get("all_streams_decoded") for v in records.values()):
        raise ValueError("Only a complete, fully decoded video report may be applied")
    for video in records.values():
        if not verified_existing(ROOT / video["path"], video):
            raise ValueError("Output bytes no longer match the verified video report")
    source = json.loads((ROOT / "raw/authorized-course.json").read_text())
    expected_ids = {str(l["id"]) for l in source["lessons"] if (l.get("info", {}).get("article_info") or {}).get("video")}
    if set(records) != expected_ids:
        raise ValueError("Verified videos do not match the source's complete video lesson set")
    original_report = ROOT / "raw/video-archive-report.json"
    originals = {str(v["lesson_id"]): v for v in json.loads(original_report.read_text()).get("videos", [])} if original_report.exists() else {}
    course = json.loads((ROOT / "course.json").read_text())
    for lesson in course["lessons"]:
        lid = str(lesson["id"])
        record = records.get(lid)
        if record:
            poster = ""
            if lesson.get("localized_info_path"):
                info = json.loads((ROOT / lesson["localized_info_path"]).read_text())
                videos = (info.get("article_info") or {}).get("video") or []
                poster = videos[0].get("cover_img", "") if videos else ""
            video = {"path": record["path"], "label": f"课程视频 · {record['resolution_selected']}p", "duration": record["duration"], "resolution": record["resolution_selected"], "bytes": record["bytes"], "sha256": record["sha256"], "archive_report": REPORT.relative_to(ROOT).as_posix()}
            if poster and (ROOT / poster).is_file():
                video["poster"] = poster
            lesson["video"] = [video]
            lesson["video_status"] = "complete"
        else:
            lesson["video"] = []
            lesson["video_status"] = "not_applicable"
        original = originals.get(lid)
        if original and original.get("download_complete"):
            lesson["video_encrypted_original"] = [{key: original[key] for key in ("path", "bytes", "sha256", "source_media_id", "source_url", "status") if key in original}]
    write_json(ROOT / "course.json", course)
    log(f"Applied {len(records)} verified videos; {len(course['lessons']) - len(records)} source lessons have no video")


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
