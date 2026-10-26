#!/usr/bin/env python3
"""Verify the complete ciphertext subset plus retained plaintext and Web originals.

Default: validate and preview only, without writing any course or page files.
Use --apply after every actual ciphertext source has a complete decryption report.
Original encrypted files, Web MP4s, and HLS sources are never modified.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from archive_config import expected_video_lesson_ids

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'raw/legacy-video-decryption-report.json'
COURSE = ROOT / 'course.json'
APPLY_REPORT = ROOT / 'raw/decrypted-video-apply-report.json'


def sha_file(path):
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def local_file(value):
    if not isinstance(value, str) or not value or '://' in value:
        raise ValueError('Expected a nonempty local course path')
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError('A required local archive file is absent or outside the course')
    return path


def verified_file(value, expected_sha, expected_bytes):
    path = local_file(value)
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError('Expected SHA-256 is absent')
    if path.stat().st_size != int(expected_bytes or 0) or sha_file(path) != expected_sha:
        raise ValueError('A saved file differs from its expected size or SHA-256: ' + value)
    return path


def verified_web(lesson, lid):
    web = copy.deepcopy(lesson.get('video_web_alternatives') or [track for track in lesson.get('video', []) if track.get('path') == f'assets/video/{lid}.mp4'])
    if len(web) != 1 or web[0].get('path') != f'assets/video/{lid}.mp4':
        raise ValueError('Expected exactly one retained Web MP4 alternative for ' + lid)
    verified_file(web[0]['path'], web[0].get('sha256'), web[0].get('bytes'))
    return web


def prepare(course, report):
    expected = {str(lesson['id']): lesson for lesson in course['lessons'] if lesson.get('video_encrypted_original')}
    plaintext = {str(lesson['id']): lesson for lesson in course['lessons'] if lesson.get('video_plaintext_original')}
    source_ids = expected_video_lesson_ids(course)
    expected_count = len(expected)
    if not source_ids or set(expected) & set(plaintext) or set(expected) | set(plaintext) != source_ids:
        raise ValueError('Ciphertext and verified plaintext originals must partition the complete source-declared video lesson set')
    rows = report.get('videos', [])
    ids = [str(row.get('lesson_id', '')) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('The decryption report contains duplicate lesson IDs')
    lookup = {str(row['lesson_id']): row for row in rows}
    missing = set(expected) - set(lookup)
    extra = set(lookup) - set(expected)
    if missing or extra or len(rows) != expected_count:
        raise ValueError(f'All {expected_count} expected decryption records are required before applying; missing={len(missing)}, unexpected={len(extra)}, observed={len(rows)}')
    if report.get('keys_or_tokens_saved_in_report') is not False:
        raise ValueError('Decryption evidence must explicitly exclude keys and tokens')
    if any(row.get('status') != 'decrypted_verified' for row in rows):
        raise ValueError('Every expected video must have status decrypted_verified before applying')
    output_course = copy.deepcopy(course)
    output_lessons = {str(lesson['id']): lesson for lesson in output_course['lessons']}
    checks = []
    raw_originals_path = ROOT / 'raw/video-archive-report.json'
    raw_originals = json.loads(raw_originals_path.read_text()).get('videos',[]) if raw_originals_path.is_file() else []
    source_rows = json.loads((ROOT/'raw/authorized-course.json').read_text())['lessons']
    source_videos = {str(row['id']):row['info']['article_info']['video'][0] for row in source_rows if row['info']['article_info'].get('video')}
    for origin in raw_originals:
        lid = str(origin.get('lesson_id'))
        if lid not in source_ids: raise ValueError('Original video report includes a source outside the authorized video set')
        source_video = source_videos[lid]
        if int(origin.get('video_index',0)) != 0 or str(origin.get('source_media_id','')) != str(source_video.get('dd_media_id_str') or source_video.get('dd_media_id') or '') or not origin.get('source_url') or origin.get('source_url') != source_video.get('bitrate_' + str(origin.get('resolution_selected'))):
            raise ValueError('Original source URL/media ID/index differs from the current authorized source')
    for lid, lesson in expected.items():
        record = lookup[lid]
        expected_source = f'assets/video/encrypted/{lid}.mp4.enc'
        expected_output = f'assets/video/decrypted/{lid}.mp4'
        if record.get('source_path') != expected_source or record.get('path') != expected_output:
            raise ValueError('Decryption report paths differ from dedicated source/output locations for ' + lid)
        original = next((item for item in lesson['video_encrypted_original'] if item.get('path') == expected_source), None)
        if not original or original.get('sha256') != record.get('source_sha256') or original.get('bytes') != record.get('source_bytes'):
            raise ValueError('Decryption source differs from the original course backup for ' + lid)
        source_rows = [row for row in raw_originals if str(row.get('lesson_id')) == lid]
        if len(source_rows) != 1 or not (source_rows[0].get('download_complete') and not source_rows[0].get('playable') and source_rows[0].get('source_declares_drm') and source_rows[0].get('status') == 'drm_source_saved_unplayable' and source_rows[0].get('source_role','encrypted_original') == 'encrypted_original' and source_rows[0].get('path') == expected_source and source_rows[0].get('sha256') == record.get('source_sha256') and source_rows[0].get('bytes') == record.get('source_bytes')):
            raise ValueError('Actual ciphertext source report does not bind the original for ' + lid)
        verified_file(expected_source, record.get('source_sha256'), record.get('source_bytes'))
        output = verified_file(expected_output, record.get('sha256'), record.get('bytes'))
        if record.get('source_bytes') != record.get('bytes'):
            raise ValueError('The exact native transform must preserve the original file length for ' + lid)
        if record.get('original_unchanged') is not True or record.get('conversion') != 'exact_native_cipher_transform_without_remux':
            raise ValueError('Missing original-preservation or direct-transform evidence for ' + lid)
        with output.open('rb') as handle:
            if handle.read(8)[4:8] != b'ftyp':
                raise ValueError('The saved decrypted original lacks its MP4 ftyp header for ' + lid)
        probe = record.get('probe', {})
        stream_list = probe.get('data', {}).get('streams', [])
        videos = [s for s in stream_list if s.get('codec_type') == 'video']
        audios = [s for s in stream_list if s.get('codec_type') == 'audio']
        decode = record.get('decode', {})
        match = record.get('normalized_stream_comparison', {})
        if probe.get('returncode') != 0 or not videos or not audios:
            raise ValueError('Missing positive audio/video probe evidence for ' + lid)
        if decode.get('returncode') != 0 or decode.get('all_audio_video_streams') is not True or decode.get('err_detect') != 'explode':
            raise ValueError('Missing full strict audio/video decode evidence for ' + lid)
        if match.get('exact_vcl_and_audio_match') is not True:
            raise ValueError('Decrypted picture/audio content differs from the independent Web source for ' + lid)
        current = output_lessons[lid]
        web = verified_web(current, lid)
        track = copy.deepcopy(web[0])
        height = max(int(s.get('height', 0)) for s in videos)
        duration = float(record.get('duration') or 0)
        if duration <= 0 or abs(duration - float(web[0].get('duration') or duration)) > 2:
            raise ValueError('Decrypted duration does not match the retained Web MP4 for ' + lid)
        track.update(path=expected_output, label=f'解密原件 MP4 · {height}p', duration=duration, resolution=height, bytes=record['bytes'], sha256=record['sha256'], archive_report='raw/legacy-video-decryption-report.json', decryption_status='decrypted_verified', source_encrypted_path=expected_source, source_encrypted_sha256=record['source_sha256'])
        current['video_decrypted_original'] = [track]
        current['video'] = [track if height >= int(web[0].get('resolution') or 0) else web[0]]
        current['video_web_alternatives'] = web
        current['video_status'] = 'complete'
        current['video_decryption_status'] = 'decrypted_verified'
        current['video_decryption_archive'] = {'report_path':'raw/legacy-video-decryption-report.json','source_path':expected_source,'source_sha256':record['source_sha256'],'output_path':expected_output,'output_sha256':record['sha256'],'strict_audio_video_decode':True,'exact_picture_and_audio_match':True}
        checks.append({'lesson_id':lid,'source_path':expected_source,'source_sha256':record['source_sha256'],'source_bytes':record['source_bytes'],'output_path':expected_output,'output_sha256':record['sha256'],'output_bytes':record['bytes'],'web_alternative_path':web[0]['path'],'web_alternative_sha256':web[0]['sha256'],'resolution':height,'duration':duration,'strict_decode_passed':True,'exact_picture_and_audio_match':True})
    # Plaintext originals are separately verified; they never enter the cipher set.
    original_report = ROOT / 'raw/video-archive-report.json'
    original_rows = json.loads(original_report.read_text()).get('videos', []) if original_report.is_file() else []
    plain_checks = []
    for lid in plaintext:
        current = output_lessons[lid]
        originals = current['video_plaintext_original']
        if len(originals) != 1 or originals[0].get('path') != f'assets/video/original/{lid}.mp4':
            raise ValueError('Expected one dedicated plaintext original for ' + lid)
        original = originals[0]
        verified_file(original['path'], original.get('sha256'), original.get('bytes'))
        evidence = [r for r in original_rows if str(r.get('lesson_id')) == lid and r.get('path') == original['path']]
        if len(evidence) != 1:
            raise ValueError('Missing unique plaintext source verification report for ' + lid)
        evidence = evidence[0]
        streams = evidence.get('probe', {}).get('data', {}).get('streams', [])
        if not (evidence.get('source_role') == 'plaintext_original' and evidence.get('status') == 'complete' and evidence.get('playable') is True and evidence.get('sha256') == original['sha256'] and evidence.get('bytes') == original['bytes'] and evidence.get('probe', {}).get('returncode') == 0 and evidence.get('decode', {}).get('returncode') == 0 and evidence.get('decode', {}).get('all_audio_video_streams') is True and any(s.get('codec_type') == 'audio' for s in streams) and any(s.get('codec_type') == 'video' for s in streams)):
            raise ValueError('Plaintext original lacks bound complete audio/video evidence for ' + lid)
        web = verified_web(current, lid)
        height = max(int(s.get('height') or 0) for s in streams if s.get('codec_type') == 'video')
        duration = float(evidence.get('duration') or 0)
        if duration <= 0 or abs(duration - float(web[0].get('duration') or duration)) > 2:
            raise ValueError('Plaintext source duration differs from Web output for ' + lid)
        track = copy.deepcopy(original)
        track.update(label=f'明文原件 MP4 · {height}p', resolution=height, duration=duration, archive_report='raw/video-archive-report.json', source_role='plaintext_original')
        current['video_plaintext_original'] = [track]
        current['video_web_alternatives'] = web
        current['video'] = [track if height >= int(web[0].get('resolution') or 0) else web[0]]
        current['video_status'] = 'complete'
        current['video_decryption_status'] = 'not_applicable_plaintext'
        plain_checks.append({'lesson_id':lid,'path':track['path'],'sha256':track['sha256'],'bytes':track['bytes'],'strict_decode_passed':True,'web_alternative_path':web[0]['path'],'web_alternative_sha256':web[0]['sha256']})
    now = datetime.now(timezone.utc).isoformat()
    output_course['video_decryption_status'] = 'complete'
    output_course['video_decryption_completed_at'] = now
    output_course['video_decryption_summary'] = {'expected':expected_count,'expected_source_videos':len(source_ids),'decrypted_verified':len(checks),'verified_plaintext_originals':len(plain_checks),'sources_unchanged':True,'full_audio_video_decodes_passed':len(checks),'exact_picture_audio_matches':len(checks),'report_path':'raw/legacy-video-decryption-report.json','apply_report_path':'raw/decrypted-video-apply-report.json'}
    summary = output_course.setdefault('archive_summary', {})
    summary.update(video=len(source_ids), video_decrypted=len(checks), video_plaintext_originals=len(plain_checks), video_web_alternatives=sum(len(l.get('video_web_alternatives', [])) for l in output_course['lessons']), video_encrypted_originals=sum(len(l.get('video_encrypted_original', [])) for l in output_course['lessons']))
    return output_course, checks


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Apply only after all source-declared records and local files pass validation')
    args = parser.parse_args()
    from archive_state import course_lock
    with course_lock(ROOT):
        return apply_locked(args)


def apply_locked(args):
    before = COURSE.read_bytes()
    source_report_bytes = REPORT.read_bytes()
    plain_report = ROOT / 'raw/video-archive-report.json'
    plain_before = plain_report.read_bytes() if plain_report.exists() else None
    watched = {path:path.read_bytes() if path.exists() else None for path in (ROOT/'raw/authorized-course.json',ROOT/'course-config.json')}
    course = json.loads(before)
    report = json.loads(source_report_bytes)
    updated, checks = prepare(course, report)
    if COURSE.read_bytes() != before or REPORT.read_bytes() != source_report_bytes or (plain_report.read_bytes() if plain_report.exists() else None) != plain_before or any((path.read_bytes() if path.exists() else None) != content for path,content in watched.items()):
        raise ValueError('Course or decryption evidence changed during verification; retry after the batch completes')
    if not args.apply:
        print(json.dumps({'applied':False,'status':'ready','verified_videos':len(checks),'source_files_unchanged':True,'course_sha256':sha_bytes(before)},ensure_ascii=False))
        return 0
    backup = ROOT / 'raw/course-before-decrypted-videos.json'
    if not backup.exists():
        backup.write_bytes(before)
    after = (json.dumps(updated, ensure_ascii=False, indent=2) + '\n').encode()
    from archive_state import compare_and_write_manifest
    compare_and_write_manifest(ROOT,sha_bytes(before),updated)
    apply_report = {'schema_version':1,'applied_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed','source_decryption_report':'raw/legacy-video-decryption-report.json','source_decryption_report_sha256':sha_bytes(source_report_bytes),'course_before_sha256':sha_bytes(before),'course_after_sha256':sha_bytes(after),'course_backup_path':str(backup.relative_to(ROOT)),'summary':{'expected_videos':len(checks),'expected_source_videos':updated['video_decryption_summary']['expected_source_videos'],'verified_plaintext_originals':updated['video_decryption_summary']['verified_plaintext_originals'],'decrypted_default_videos':sum(any(t.get('path','').startswith('assets/video/decrypted/') for t in l.get('video',[])) for l in updated['lessons']),'retained_web_alternatives':updated['archive_summary']['video_web_alternatives'],'sources_unchanged':True,'all_strict_decodes_passed':True,'all_picture_audio_matches':True},'videos':checks,'keys_or_tokens_saved_in_report':False}
    write_json(APPLY_REPORT, apply_report)
    (ROOT/'DECRYPTION_STATUS.md').write_text(f'''# 原始视频解密结果\n\n全部 {len(checks)} 段加密视频原件已直接转换为可播放 MP4。阅读器在已核验原件与网页源中选择较高清晰度，同清晰度优先原件。结果位于 `assets/video/decrypted/`；每个文件与对应加密原件等长，原 `.enc` 文件保持不变。\n\n加密子集全部通过音画完整解码；明文原件另行独立核验并保留。压缩画面切片与音频包还与独立保存的网页播放源逐项比对一致，转换过程没有重编码或重新封装。\n\n网页源 MP4 继续保存在 `assets/video/`，可从 `resources.html` 或 `content/本地资源.md` 与解密原件分别下载。每讲默认只显示一个最高质量的已核验播放器；原件与网页源保持独立。\n\n证据：\n\n- [逐文件解密与解码报告](raw/legacy-video-decryption-report.json)\n- [原件、结果与网页源哈希复查及默认视频合并](raw/decrypted-video-apply-report.json)\n\n报告仅记录结果、文件哈希和核验状态，不包含密钥或令牌值。\n''',encoding='utf-8')
    print(json.dumps({'applied':True,'status':'passed','verified_videos':len(checks),'course_sha256':sha_bytes(after),'apply_report':str(APPLY_REPORT.relative_to(ROOT))},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(str(error))
