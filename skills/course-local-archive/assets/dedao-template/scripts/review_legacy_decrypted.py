#!/usr/bin/env python3
"""Independently audit all legacy decrypted MP4s and optional first/middle/last samples.

Always hashes originals and outputs and verifies MP4 structure. Full-decode
reports are cross-checked against current hashes; only three representative
outputs need an additional independent complete decode.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys

from verify_decrypted_video import ROOT,container_boxes,digest,safe_path
from archive_config import expected_video_lesson_ids

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decode-samples',action='store_true')
    args=parser.parse_args()
    source=json.loads((ROOT/'raw/authorized-course.json').read_text())
    source_ids=expected_video_lesson_ids()
    identities={str(row['id']): row['info']['article_info']['video'][0] for row in source['lessons'] if row['info']['article_info'].get('video')}
    immutable=json.loads((ROOT/'raw/video-archive-report.json').read_text())
    all_originals=immutable['videos'];old={str(row['lesson_id']):row for row in all_originals}
    if len(old)!=len(all_originals) or set(old)!=source_ids: raise ValueError('Source original report must exactly cover the complete source video identities')
    for lid,origin in old.items():
        source_video=identities[lid]
        if int(origin.get('video_index',0))!=0 or str(origin.get('source_media_id',''))!=str(source_video.get('dd_media_id_str') or source_video.get('dd_media_id') or '') or not origin.get('source_url') or origin.get('source_url')!=source_video.get('bitrate_'+str(origin.get('resolution_selected'))): raise ValueError('Source video index/media ID differs from the authorized response')
        if not origin.get('download_complete'): raise ValueError('Source original backup is incomplete')
        if not origin.get('playable') and not (origin.get('source_declares_drm') and origin.get('status')=='drm_source_saved_unplayable' and origin.get('source_role','encrypted_original')=='encrypted_original'): raise ValueError('An unclassified source cannot be counted as actual ciphertext')
    ids=[lid for lid in identities if not old[lid].get('playable')]
    transform_path=ROOT/'raw/legacy-video-decryption-report.json'
    transform=json.loads(transform_path.read_text())
    rows=transform.get('videos',[]);lookup={str(row['lesson_id']):row for row in rows}
    errors=[];checked=[]
    if len(rows)!=len(lookup) or len(rows)!=len(ids) or set(lookup)!=set(ids):errors.append({'kind':'decrypted_lesson_set_mismatch','expected':len(ids),'saved':len(rows)})
    if transform.get('keys_or_tokens_saved_in_report') is not False:errors.append({'kind':'transform_report_does_not_explicitly_exclude_keys_or_tokens'})
    for lid in ids:
        row=lookup.get(lid);origin=old[lid]
        if not row:continue
        issues=[];original=safe_path(origin['path']);output=safe_path(row.get('path',''))
        if not original.is_file() or not output.is_file():errors.append({'kind':'missing_media','lesson_id':lid});continue
        source_sha=digest(original);output_sha=digest(output)
        if original==output:issues.append('Output overwrites original ciphertext')
        if row.get('status')!='decrypted_verified':issues.append('Transform did not complete')
        if row.get('source_path')!=origin['path'] or source_sha!=origin['sha256'] or source_sha!=row.get('source_sha256') or original.stat().st_size!=origin['bytes'] or original.stat().st_size!=row.get('source_bytes'):issues.append('Original ciphertext identity/size/hash mismatch')
        if not row.get('original_unchanged'):issues.append('Transform does not affirm unchanged source')
        if output_sha!=row.get('sha256') or output.stat().st_size!=row.get('bytes'):issues.append('Candidate size/hash differs from full-decode evidence')
        if output.stat().st_size!=original.stat().st_size:issues.append('Exact stream transform changed byte length')
        if row.get('conversion')!='exact_native_cipher_transform_without_remux':issues.append('Conversion is not the documented native ciphertext transform')
        try:boxes=container_boxes(output)
        except ValueError as error:boxes=[];issues.append(str(error))
        probe=row.get('probe',{});metadata=probe.get('data',{});streams=metadata.get('streams',[])
        video=[stream for stream in streams if stream.get('codec_type')=='video'];audio=[stream for stream in streams if stream.get('codec_type')=='audio']
        if probe.get('returncode')!=0 or not video or not audio or len(video)!=row.get('video_stream_count') or len(audio)!=row.get('audio_stream_count'):issues.append('Expected source video/audio stream metadata is absent or inconsistent')
        if max([stream.get('height',0) for stream in video],default=0)<int(origin.get('resolution_selected') or 0):issues.append('Decrypted source resolution dropped')
        duration=float(metadata.get('format',{}).get('duration') or 0);expected=float(origin.get('source_duration') or 0)
        if duration<=0 or expected and abs(duration-expected)>max(2,expected*.002):issues.append('Source duration mismatch')
        decode=row.get('decode',{})
        if decode.get('returncode')!=0 or not decode.get('all_audio_video_streams') or decode.get('err_detect')!='explode':issues.append('Full strict AV decode evidence absent')
        normalized=row.get('normalized_stream_comparison')
        if normalized is not None and normalized.get('exact_vcl_and_audio_match') is not True:issues.append('Normalized picture/audio content differs from authorized Web archive')
        record={'lesson_id':lid,'source_media_id':origin.get('source_media_id'),'video_index':origin.get('video_index',0),'status':'passed' if not issues else 'failed','source_path':origin['path'],'source_bytes':original.stat().st_size,'source_sha256':source_sha,'original_unchanged':source_sha==origin['sha256'],'output_path':row['path'],'output_bytes':output.stat().st_size,'output_sha256':output_sha,'mp4_top_level_boxes':boxes,'video_streams':len(video),'audio_streams':len(audio),'width':video[0].get('width') if video else None,'height':video[0].get('height') if video else None,'duration_seconds':duration,'strict_full_decode_report_matches_current_hash':decode.get('returncode')==0 and output_sha==row.get('sha256'),'normalized_vcl_and_audio_match':normalized.get('exact_vcl_and_audio_match') if normalized else None,'issues':issues}
        checked.append(record)
        if issues:errors.append({'kind':'candidate_validation_failed','lesson_id':lid,'issues':issues})
    samples=list(dict.fromkeys([ids[0],ids[len(ids)//2],ids[-1]])) if ids else []
    sample_results=[]
    if args.decode_samples and not errors:
        for lid in samples:
            row=lookup[lid];report_path=ROOT/f'raw/independent-legacy-decryption-{lid}.json'
            earlier=json.loads(report_path.read_text()) if report_path.is_file() else {}
            reused=bool(earlier.get('status')=='verified_transform_output' and earlier.get('candidate_sha256')==row['sha256'] and earlier.get('source_sha256_before')==row['source_sha256'] and earlier.get('source_sha256_after')==row['source_sha256'] and earlier.get('full_decode',{}).get('returncode')==0 and earlier.get('actual_transform_provenance_verified'))
            if not reused:
                if report_path.exists():report_path=ROOT/'raw/decrypted-video-validation'/f'{lid}.json'
                result=subprocess.run([sys.executable,str(ROOT/'scripts/verify_decrypted_video.py'),'--lesson-id',lid,'--candidate',row['path'],'--operation-report',str(transform_path),'--report',str(report_path)],capture_output=True,text=True,timeout=1000)
                if result.returncode:errors.append({'kind':'independent_sample_failed','lesson_id':lid,'exit_code':result.returncode,'stderr':result.stderr[-1000:]})
            sample=json.loads(report_path.read_text()) if report_path.is_file() else {}
            sample_results.append({'lesson_id':lid,'report':report_path.relative_to(ROOT).as_posix(),'status':sample.get('status'),'source_and_output_hashes_match':sample.get('candidate_sha256')==row['sha256'] and sample.get('source_sha256_before')==row['source_sha256'],'all_audio_video_decode_exit_code':sample.get('full_decode',{}).get('returncode'),'existing_independent_check_reused':reused})
    report={'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed' if not errors else 'failed','source_transform_report':'raw/legacy-video-decryption-report.json','method':'Independent current SHA256 of every immutable encrypted original and decrypted output; exact source binding, equal lengths, full MP4 box boundaries and recorded strict decode/probe evidence are cross-checked. Optional independent full AV decode of first, middle and last outputs; matching prior independent sample checks are reused.','summary':{'expected_videos':len(ids),'expected_source_videos':len(source_ids),'plaintext_source_videos':len(source_ids)-len(ids),'reviewed_videos':len(checked),'passed_videos':sum(row['status']=='passed' for row in checked),'originals_unchanged':sum(row['original_unchanged'] for row in checked),'video_and_audio_evidence_verified':sum(row['strict_full_decode_report_matches_current_hash'] for row in checked),'normalized_picture_and_audio_match':sum(row['normalized_vcl_and_audio_match'] is True for row in checked),'output_bytes':sum(row['output_bytes'] for row in checked),'independent_full_decode_samples':len(sample_results),'errors':len(errors)},'videos':checked,'independent_samples':sample_results,'errors':errors}
    path=ROOT/'raw/independent-legacy-decryption-review.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'summary':report['summary'],'report':path.relative_to(ROOT).as_posix()},ensure_ascii=False))
    return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(main())
