#!/usr/bin/env python3
"""Independent checks of archived Web HLS video files; never modifies media."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def probe(path):
    completed = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, timeout=60)
    if completed.returncode:
        raise ValueError('FFprobe failed for ' + str(path.relative_to(ROOT)))
    return json.loads(completed.stdout)


def streams(data):
    return [dict((k, s[k]) for k in ['codec_type', 'codec_name', 'width', 'height', 'sample_rate', 'channels', 'duration'] if k in s) for s in data.get('streams', []) if s.get('codec_type') in {'video', 'audio'}]


def check(row):
    lid = str(row['lesson_id'])
    path = ROOT / 'assets/video' / (lid + '.mp4')
    record = {'lesson_id': lid, 'title': row['title'], 'path': str(path.relative_to(ROOT)), 'issues': []}
    try:
        data = probe(path)
        observed = streams(data)
        video = [s for s in observed if s['codec_type'] == 'video']
        audio = [s for s in observed if s['codec_type'] == 'audio']
        record.update(bytes=path.stat().st_size, sha256=digest(path), streams=observed, video_streams=len(video), audio_streams=len(audio), duration_seconds=float(data['format']['duration']))
        if not video or not audio:
            record['issues'].append('Output must contain both video and audio streams')
        source_tracks = row['media'].get('tracks', [])
        expected = next((float(t['duration']) for t in source_tracks if t.get('track_type') == 2 and t.get('duration')), None)
        best_resolution = max((int(f.get('resolution') or 0) for t in source_tracks for f in t.get('formats', []) if f.get('format') == 'm3u8'), default=0)
        record.update(expected_duration_seconds=expected, source_highest_resolution=best_resolution)
        if expected and abs(record['duration_seconds'] - expected) > max(3.0, expected * .02):
            record['issues'].append('Output duration differs from source')
        if video and best_resolution and max(s.get('height', 0) for s in video) != best_resolution:
            record['issues'].append('Output resolution differs from highest returned source resolution')
        source_dir = ROOT / 'raw/video-hls' / lid
        playlist = source_dir / 'source.m3u8'
        if playlist.is_file():
            text = playlist.read_text()
            record['source_playlist'] = {'sha256':digest(playlist), 'has_key_tag':'#EXT-X-KEY' in text, 'has_endlist':'#EXT-X-ENDLIST' in text, 'duration_seconds':sum(float(v) for v in re.findall(r'#EXTINF:([0-9.]+)', text)), 'segments':sum(bool(line.strip()) and not line.startswith('#') for line in text.splitlines())}
            if not record['source_playlist']['has_endlist']:
                record['issues'].append('Source playlist lacks ENDLIST')
        else:
            record['issues'].append('Source playlist missing')
        segments = sorted(source_dir.rglob('*.ts'))
        if segments:
            source_streams = streams(probe(segments[0]))
            record['first_source_segment_streams'] = source_streams
            for kind in ('video', 'audio'):
                before = [s for s in source_streams if s['codec_type'] == kind]
                after = [s for s in observed if s['codec_type'] == kind]
                if len(before) != len(after):
                    record['issues'].append('Source/output ' + kind + ' stream count differs')
                if sorted(s.get('codec_name', '') for s in before) != sorted(s.get('codec_name', '') for s in after):
                    record['issues'].append('Source/output ' + kind + ' codecs differ')
        else:
            record['issues'].append('No original source TS segments found')
    except Exception as error:
        record['issues'].append(type(error).__name__ + ': ' + str(error))
    record['status'] = 'passed' if not record['issues'] else 'failed'
    return record


def main():
    source = ROOT / 'raw/authorized-web-media.json'
    export = json.loads(source.read_text())
    rows = export['videos']
    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(check, rows))
    selected = list(dict.fromkeys([0, len(rows)//2, len(rows)-1])) if rows else []
    decodes = []
    for index in selected:
        row = rows[index]
        path = ROOT / 'assets/video' / (str(row['lesson_id']) + '.mp4')
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror', '-err_detect', 'explode', '-i', str(path), '-map', '0:v', '-map', '0:a', '-f', 'null', '-']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
            code = result.returncode
            error = result.stderr[:1200]
        except subprocess.TimeoutExpired:
            code, error = None, 'Full decode exceeded 300 seconds'
        decodes.append({'lesson_id':str(row['lesson_id']), 'course_video_index':index + 1, 'title':row['title'], 'full_video_and_audio_decode_exit_code':code, 'stderr':error, 'status':'passed' if code == 0 else 'failed'})
    report = {'schema_version':1, 'checked_at_utc':datetime.now(timezone.utc).isoformat(), 'scope':'Independent FFprobe and hashes for every output, first TS stream comparison, full audio/video decode for first/middle/last videos', 'source':str(source.relative_to(ROOT)), 'source_sha256':digest(source), 'summary':{'expected_videos':len(rows), 'probes_passed':sum(r['status']=='passed' for r in records), 'videos_with_both_audio_and_video':sum(r.get('video_streams',0)>0 and r.get('audio_streams',0)>0 for r in records), 'sample_full_decodes_passed':sum(r['status']=='passed' for r in decodes), 'sample_full_decodes':len(decodes)}, 'videos':records, 'sample_full_decodes':decodes}
    report['status'] = 'passed' if report['summary']['probes_passed'] == len(rows) and report['summary']['sample_full_decodes_passed'] == len(decodes) else 'failed'
    (ROOT/'raw/independent-web-video-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'], **report['summary']},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
