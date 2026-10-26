"""Core media audit: source originals, transformations, HLS objects and all streams."""
from collections import defaultdict
import hashlib
import json
import subprocess

from audit_evidence import local_file, media_report_paths
from media_validation import FreshMediaRun, verify_warning_review


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values(): yield from walk(child)
    elif isinstance(value, list):
        for child in value: yield from walk(child)


def metadata(row):
    return row.get('ffprobe') or row.get('probe', {}).get('data') or row.get('probe_metadata') or {}


def all_stream_evidence(row, kind):
    streams = metadata(row).get('streams', [])
    audio = [s for s in streams if s.get('codec_type') == 'audio' or kind == 'audio' and s.get('sample_rate') and s.get('channels')]
    video = [s for s in streams if s.get('codec_type') == 'video']
    decode = row.get('decode', {})
    explicit = row.get('all_streams_decoded') or kind == 'audio' and row.get('all_audio_streams_decoded') or decode.get('all_audio_video_streams') or decode.get('all_audio_streams')
    # A historical single-stream file has no alternative stream FFmpeg could omit.
    single = bool(audio) and len(audio) == 1 and (kind != 'video' or len(video) == 1)
    return bool(explicit or single)


def playable_tracks(course):
    for lesson in course.get('lessons', []):
        lid = str(lesson['id'])
        for role, kind in [('audio','audio'), ('video','video'), ('video_web_alternatives','video'), ('video_decrypted_original','video'), ('video_plaintext_original','video'), ('video_audio_components','audio')]:
            for track in lesson.get(role, []) or []:
                yield lid, role, kind, track
    for role, kind in [('course_intro_video','video'), ('course_intro_audio','audio')]:
        values = course.get(role) or []
        if isinstance(values, dict): values = [values]
        for track in values: yield None, role, kind, track


def audit_media(root, course, expected_video, args, load, sha, fail, summary):
    evidence = defaultdict(list)
    fresh = FreshMediaRun(root, args.audit_run_id, args.resume_same_run, warning_report=args.source_warning_review) if args.mode == 'fresh' else None
    # Current fresh-run report is mutable until this stage ends; bind it only then.
    for report_path in media_report_paths(root):
        if fresh and report_path == fresh.path: continue
        saved = load(report_path, {})
        for node in walk(saved):
            if isinstance(node, dict) and isinstance(node.get('path'), str) and node['path'].startswith(('assets/audio/','assets/video/')) and node.get('sha256'):
                evidence[node['path']].append((node, report_path.relative_to(root).as_posix()))
    def current(row, path_key='path', sha_key='sha256', size_key='bytes'):
        try:
            path = local_file(root, row.get(path_key))
            return path.stat().st_size == row.get(size_key) and sha(path) == row.get(sha_key)
        except (OSError, ValueError): return False
    originals = load(root/'raw/video-archive-report.json', {}).get('videos', [])
    source_lookup = {(str(row.get('lesson_id')),str(row.get('source_media_id'))):row for row in originals}
    encrypted = []
    transform = load(root/'raw/legacy-video-decryption-report.json', {})
    decrypted = transform.get('videos', [])
    review = load(root/'raw/independent-legacy-decryption-review.json', {})
    for lid, rows in expected_video.items():
        for source in rows:
            mid = str(source.get('dd_media_id_str') or source.get('dd_media_id') or '')
            row = source_lookup.get((lid, mid), {})
            valid = bool(row.get('download_complete') and current(row))
            summary['video_source_files_verified'] += valid
            if not valid:
                fail('video_source_file_unverified',lesson_id=lid,source_media_id=mid);continue
            if row.get('playable') is not True:
                if row.get('status')!='drm_source_saved_unplayable' or not row.get('source_declares_drm'):fail('unplayable_source_is_not_verified_ciphertext',lesson_id=lid,source_media_id=mid)
                encrypted.append(row)
    for row in originals:
        valid = current(row);summary['historical_video_backups_verified'] += valid
        if not valid:fail('historical_video_backup_hash_mismatch',lesson_id=str(row.get('lesson_id')),path=row.get('path'))
    for origin in encrypted:
        lid = str(origin.get('lesson_id'));mid = str(origin.get('source_media_id'))
        matches = [r for r in decrypted if str(r.get('lesson_id')) == lid and str(r.get('source_media_id',mid)) == mid and r.get('source_path') == origin.get('path')]
        row = matches[0] if len(matches) == 1 else {}
        valid = (row.get('status') == 'decrypted_verified' and current(row) and current(row,'source_path','source_sha256','source_bytes') and row.get('source_sha256') == origin.get('sha256') and row.get('original_unchanged') is True and row.get('conversion') == 'exact_native_cipher_transform_without_remux' and row.get('source_bytes') == row.get('bytes') and all_stream_evidence(row,'video') and row.get('decode',{}).get('returncode') == 0)
        kept = [t for lesson in course.get('lessons',[]) if str(lesson['id']) == lid for role in ('video','video_decrypted_original') for t in lesson.get(role,[]) or [] if t.get('path') == row.get('path')]
        provenance = transform.get('official_algorithm_evidence',{})
        config = load(root/'course-config.json',{})
        pinned = config.get('protocol_library',{}).get('sha256') or config.get('legacy_video_official_library_sha256') or config.get('official_library_sha256')
        if pinned and provenance.get('library_sha256') != pinned: valid=False
        if not provenance.get('library_sha256') or transform.get('keys_or_tokens_saved_in_report') is not False: valid=False
        independent = [r for r in review.get('videos',[]) if str(r.get('lesson_id')) == lid and r.get('source_sha256') == origin.get('sha256') and r.get('output_sha256') == row.get('sha256') and r.get('status') == 'passed']
        if not valid or not kept or review.get('status') != 'passed' or len(independent) != 1:
            fail('ciphertext_source_decryption_or_independent_review_unverified',lesson_id=lid,source_media_id=mid)
        else:summary['decrypted_source_originals_verified'] += 1
    if encrypted and review.get('summary',{}).get('passed_videos') != len(encrypted):fail('independent_legacy_review_ciphertext_subset_count_mismatch')
    # A plaintext original must be preserved and remain playable as its own role.
    for origin in originals:
        if origin.get('playable') is True:
            kept = [t for lesson in course.get('lessons',[]) if str(lesson['id']) == str(origin.get('lesson_id')) for role in ('video','video_plaintext_original') for t in lesson.get(role,[]) or [] if t.get('path') == origin.get('path')]
            if not kept:fail('plaintext_source_original_not_retained',path=origin.get('path'))
    web_rows = load(root/'raw/web-video-archive-report.json',{}).get('videos',[])
    if sum(map(len,expected_video.values())):
        exported = load(root/'raw/authorized-web-media.json',{})
        if not exported.get('complete') or exported.get('errors'):fail('authorized_web_media_export_incomplete')
        sources = {(str(r.get('lesson_id')),str(r.get('source_media_id'))):r for r in exported.get('videos',[])}
        if len(web_rows) != sum(map(len,expected_video.values())):fail('web_video_report_count_mismatch')
        for row in web_rows:
            source = sources.get((str(row.get('lesson_id')),str(row.get('source_media_id'))),{})
            formats = [f for t in source.get('media',{}).get('tracks',[]) for f in t.get('formats',[]) if f.get('type') == 'video' and f.get('format') == 'm3u8' and f.get('url')]
            largest = max([int(f.get('resolution',0)) for f in formats],default=0)
            selected = [f for f in formats if f.get('url') == row.get('source_url') and int(f.get('resolution',0)) == int(row.get('resolution_selected') or 0)]
            if not selected or largest != int(row.get('resolution_selected') or 0):fail('web_video_source_identity_or_resolution_mismatch',lesson_id=str(row.get('lesson_id')))
            if row.get('conversion') != 'lossless_remux' or not current(row):fail('web_video_lossless_output_unverified',path=row.get('path'))
    # Both audio and video HLS use the reusable finite URI/object verifier.
    from hls_assets import audit_hls
    hls_done = set()
    for candidates in evidence.values():
        for row, where in candidates:
            hls = row.get('hls')
            if not hls:continue
            key = json.dumps(hls,sort_keys=True)
            if key in hls_done:continue
            hls_done.add(key)
            try:
                result = audit_hls(root,hls)
                if result.get('status') != 'passed':raise ValueError('HLS audit did not pass')
                for value in (hls.get('original_playlist_path'),hls.get('local_playlist_path'),hls.get('assets_manifest_path')):
                    if value:sha(local_file(root,value))
                assets = hls.get('assets',[])
                if hls.get('assets_manifest_path'):assets=load(local_file(root,hls['assets_manifest_path']),[])
                for asset in assets:sha(local_file(root,asset['path']))
                if row.get('method') == 'standard_hls_lossless_audio_remux' or row.get('output_origin') == 'standard_hls_lossless_remux':
                    proof = row.get('hls_audio_packet_proof',{})
                    if proof.get('status') != 'passed' or proof.get('all_audio_packets_exact_match') is not True or proof.get('output_sha256') != row.get('sha256') or proof.get('output_path') != row.get('path') or not current(row):raise ValueError('Lossless all-audio packet equivalence is absent or stale')
                summary['hls_sources_verified'] += 1
            except (OSError, ValueError, KeyError) as error:fail('local_hls_source_or_packet_proof_failed',report=where,error=str(error))
    from media_inventory import load_inventory
    for required in load_inventory(root,args.archive).get('resources',[]):
        if required.get('role') not in {'main_audio','extra_audio','video_audio_component','course_intro_audio'} or '.m3u8' not in str(required.get('_url','')).split('?',1)[0]:continue
        identity=required.get('source_url_sha256')
        rows=[row for candidates in evidence.values() for row,where in candidates if row.get('source_url_sha256')==identity and (row.get('method')=='standard_hls_lossless_audio_remux' or row.get('output_origin')=='standard_hls_lossless_remux') and row.get('hls') and current(row)]
        if not rows:fail('source_declared_audio_hls_missing_raw_or_lossless_proof',resource_id=required['resource_id'])
    checks=[];verified={}
    for lid, role, kind, track in playable_tracks(course):
        protected=track.get('encrypted_source')
        if protected:
            valid=current(protected);summary['protected_audio_source_backups_verified']+=valid
            if not valid:fail('protected_audio_source_backup_changed',path=protected.get('path'))
        derived=track.get('derived_from_verified_video')
        if derived:
            valid=(current(derived) and derived.get('source_media_id')==track.get('source_media_id') and derived.get('all_audio_packets_exact_match') is True and derived.get('source_audio_decryption_claimed') is False and bool(derived.get('input_audio_packet_hashes')) and derived.get('input_audio_packet_hashes')==derived.get('output_audio_packet_hashes'))
            summary['derived_video_audio_inputs_verified']+=valid
            if not valid:fail('derived_video_audio_input_or_packet_proof_changed',path=derived.get('path'))
        value=track.get('path','')
        if value in verified:
            if role in {'audio','video'}:summary[kind+'_track_references_verified']+=verified[value]
            continue
        try:path=local_file(root,value)
        except ValueError:fail('missing_local_media',lesson_id=lid,media_kind=kind,path=value);continue
        digest=sha(path);size=path.stat().st_size
        matches=[(r,w) for r,w in evidence.get(value,[]) if r.get('sha256') == digest and r.get('bytes') == size and r.get('full_decode_exit_code',r.get('decode',{}).get('returncode')) == 0 and r.get('status') in {'complete','decrypted_verified'} and all_stream_evidence(r,kind)]
        if not fresh:
            reviewed=[]
            for row,where in matches:
                diagnostic=row.get('decode',{}).get('stderr','') or row.get('decoder_stderr','')
                probe_diagnostic=row.get('probe',{}).get('stderr','')
                if diagnostic.strip() or probe_diagnostic.strip():
                    candidate={**row,'kind':kind,'decode':{**row.get('decode',{}),'stderr':diagnostic}}
                    review=verify_warning_review(root,args.source_warning_review,candidate)
                    if not review:continue
                    sha(local_file(root,review['path']))
                    sha(local_file(root,review['counterpart_path']))
                reviewed.append((row,where))
            matches=reviewed
        if fresh:
            record=fresh.validate(value,kind);matches=[(record,fresh.path.relative_to(root).as_posix())] if record.get('status')=='complete' else []
            if not matches:fail('fresh_all_stream_decode_failed',path=value,error=record.get('error'))
        elif not matches:fail('missing_matching_all_stream_decode_evidence',path=value)
        record=matches[0][0] if matches else {};meta=metadata(record)
        if args.probe_media and not fresh:
            probe=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,timeout=90)
            if probe.returncode or probe.stderr.strip():fail('independent_media_probe_diagnostic',path=value,returncode=probe.returncode,stderr=probe.stderr)
            meta=json.loads(probe.stdout) if probe.returncode==0 else {}
        streams=meta.get('streams',[]);required=[s for s in streams if s.get('codec_type')==kind or kind=='audio' and s.get('sample_rate') and s.get('channels')]
        duration=float(meta.get('format',{}).get('duration') or 0)
        valid=bool(matches and required and duration>0)
        if not required or duration<=0:fail('invalid_media_probe',path=value,media_kind=kind)
        expected=next((r.get('expected_duration_seconds') or r.get('expected_duration') or r.get('source_duration') for r,w in evidence.get(value,[]) if r.get('sha256')==digest),None)
        if expected and abs(duration-float(expected))>max(3,float(expected)*.02):valid=False;fail('media_duration_mismatch',path=value)
        verified[value]=valid;summary[kind+'_media_verified']+=valid
        if role in {'audio','video'}:summary[kind+'_track_references_verified']+=valid
        checks.append({'path':value,'kind':kind,'role':role,'bytes':size,'sha256':digest,'duration_seconds':duration,'status':'verified' if valid else 'failed','full_decode_evidence_reports':list(dict.fromkeys(w for r,w in matches)),'probe_metadata':meta,'probe_origin':'fresh_independent_ffprobe' if fresh else 'matching_all_stream_decode_report','all_streams_decoded':bool(matches),'full_decode_repeated':bool(fresh)})
    if fresh:
        fresh.save();sha(fresh.path)
        for row in fresh.records.values():
            review=row.get('source_metadata_warning_review')
            if review:
                sha(local_file(root,review['path']));sha(local_file(root,review['counterpart_path']))
    return checks,fresh
