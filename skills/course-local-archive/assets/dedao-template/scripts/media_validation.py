"""Fresh all-stream validation, resumable only inside one explicitly named run."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

from archive_state import atomic_json, sha_file


def now(): return datetime.now(timezone.utc).isoformat()


class FreshMediaRun:
    def __init__(self, root, run_id=None, resume=False, timeout=3600, warning_report=None):
        self.root = Path(root).resolve()
        self.run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.run_id):
            raise ValueError('Unsafe audit run ID')
        self.path = self.root / 'raw/audit-runs' / self.run_id / 'media-validation.json'
        self.timeout = timeout
        self.warning_report = warning_report
        self.report = {'schema_version': 2, 'evidence_role': 'media_validation',
                       'producer': 'audit_archive', 'audit_run_id': self.run_id,
                       'started_at_utc': now(), 'course_enid': json.loads((self.root / 'course.json').read_text()).get('course_enid'),
                       'settings': {'all_streams_mapped': True, 'strict_error_detection': True, 'decoder_threads': 2}, 'media': []}
        if self.path.exists():
            if not resume:
                raise ValueError('Run ID already exists; use --resume-same-run or a new ID')
            previous = json.loads(self.path.read_text())
            if previous.get('audit_run_id') != self.run_id or previous.get('course_enid') != self.report['course_enid'] or previous.get('settings') != self.report['settings']:
                raise ValueError('Cannot resume another course or validation policy')
            self.report = previous
        elif resume:
            raise ValueError('Requested same-run resume evidence does not exist')
        self.records = {row['path']: row for row in self.report['media']}
        self.reused = 0
        self.executed = 0

    def save(self):
        self.report['media'] = list(self.records.values())
        self.report['updated_at_utc'] = now()
        self.report['summary'] = {'completed': sum(row.get('status') == 'complete' for row in self.records.values()),
                                  'failed': sum(row.get('status') != 'complete' for row in self.records.values()),
                                  'fresh_decodes_this_invocation': self.executed, 'same_run_results_reused_this_invocation': self.reused}
        atomic_json(self.path, self.report)

    def validate(self, value, kind):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ValueError('Missing or escaping media path')
        before = (path.stat().st_size, sha_file(path))
        old = self.records.get(value)
        if old and old.get('status') == 'complete' and old.get('audit_run_id') == self.run_id and old.get('sha256') == before[1] and old.get('bytes') == before[0] and old.get('all_streams_decoded') and old.get('kind') == kind:
            review=old.get('source_metadata_warning_review')
            if review:
                current=verify_warning_review(self.root,self.warning_report or review.get('path'),old)
                if current!=review:raise ValueError('Same-run source metadata warning review changed')
            self.reused += 1
            self.save()
            return old
        row = {'path': value, 'kind': kind, 'audit_run_id': self.run_id, 'sha256': before[1], 'bytes': before[0], 'started_at_utc': now(), 'status': 'failed'}
        self.executed += 1
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, timeout=90)
            row['probe'] = {'returncode': probe.returncode, 'stderr': probe.stderr, 'data': json.loads(probe.stdout) if probe.returncode == 0 else {}}
            streams = row['probe']['data'].get('streams', [])
            videos = [s for s in streams if s.get('codec_type') == 'video']
            audios = [s for s in streams if s.get('codec_type') == 'audio']
            if probe.returncode or (not videos if kind == 'video' else not audios):
                raise ValueError('Expected media streams are absent or FFprobe failed')
            argv = ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error', '-xerror', '-err_detect', 'explode', '-threads', '2', '-i', str(path)]
            if kind == 'video': argv += ['-map', '0:v']
            argv += ['-map', '0:a?' if kind == 'video' else '0:a', '-progress', 'pipe:1', '-f', 'null', '-']
            decoded = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout)
            row['decode'] = {'returncode': decoded.returncode, 'stderr': decoded.stderr, 'command': argv[:-1] + ['-'], 'progress': decoded.stdout}
            row['full_decode_exit_code'] = decoded.returncode
            progress=dict(line.split('=',1) for line in decoded.stdout.splitlines() if '=' in line)
            row['video_frames_decoded']=int(progress.get('frame','0').strip() or 0)
            row['decode_progress_fields']=progress
            row['all_streams_decoded'] = decoded.returncode == 0 and 'progress=end' in decoded.stdout
            row['audio_stream_count'], row['video_stream_count'] = len(audios), len(videos)
            if not row['all_streams_decoded'] or kind == 'video' and row['video_frames_decoded']<=0:
                raise ValueError('Strict all-stream decode failed or did not reach EOF')
            if decoded.stderr.strip() or probe.stderr.strip():
                review = verify_warning_review(self.root, self.warning_report, row)
                if not review:
                    raise ValueError('Media diagnostic requires a current independent source-warning review')
                row['source_metadata_warning_review'] = review
            if before != (path.stat().st_size, sha_file(path)):
                raise ValueError('Media changed during complete validation')
            row['status'] = 'complete'
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            row['error'] = str(error)
        row['finished_at_utc'] = now()
        self.records[value] = row
        self.save()
        return row


def verify_warning_review(root, report_path, decoded):
    """No warning string/lesson-ID whitelist. Review binds exact current bytes.

    The external independent review must include container-structure evidence,
    expected/decoded frames, EOF, and current all-stream compressed equivalence
    to a separately verified source. Diagnostics are retained verbatim.
    """
    if not report_path:
        return None
    path = (Path(root) / report_path).resolve()
    if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
        raise ValueError('Source warning review must be inside this archive')
    from audit_evidence import is_post_final
    if is_post_final(path.relative_to(Path(root).resolve())):raise ValueError('Source metadata verification is core evidence, not post-final UI QA')
    report = json.loads(path.read_text())
    if report.get('evidence_role') != 'source_metadata_verification' or report.get('status') != 'passed':
        return None
    stderr_sha = hashlib.sha256(decoded['decode']['stderr'].encode()).hexdigest()
    for row in report.get('media', []):
        if row.get('path') != decoded['path'] or row.get('sha256') != decoded['sha256'] or row.get('stderr_sha256') != stderr_sha or (decoded.get('probe', {}).get('stderr', '').strip() and row.get('probe_stderr_sha256') != hashlib.sha256(decoded['probe']['stderr'].encode()).hexdigest()):
            continue
        checks = row.get('checks', {})
        expected = checks.get('expected_video_frames')
        if not checks.get('container_structure_verified') or not checks.get('all_streams_compared') or not checks.get('all_compressed_packets_equal') or not checks.get('decode_reached_eof'):
            continue
        if decoded['kind'] == 'video' and (not isinstance(expected, int) or expected <= 0 or checks.get('decoded_video_frames') != expected or decoded.get('video_frames_decoded') is not None and decoded.get('video_frames_decoded') != expected):
            continue
        counterpart = (Path(root) / str(row.get('counterpart_path', ''))).resolve()
        if not counterpart.is_relative_to(Path(root).resolve()) or not counterpart.is_file() or sha_file(counterpart) != row.get('counterpart_sha256'):
            continue
        # The independent report is a review boundary, not an automatic stderr exemption.
        return {'path': path.relative_to(Path(root).resolve()).as_posix(), 'sha256': sha_file(path), 'classification': 'source_container_metadata_warning', 'checks': checks, 'counterpart_path': row['counterpart_path'], 'counterpart_sha256': row['counterpart_sha256']}
    return None
