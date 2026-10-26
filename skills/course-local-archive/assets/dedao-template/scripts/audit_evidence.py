"""Evidence roles, stable presentation bindings and read-only archive checks.

Only declared producer reports are media evidence. A screenshot or QA JSON in
raw is post-final evidence, never an input to a download/build checkpoint.
"""
import hashlib
import json
from pathlib import Path

POST_FINAL_DIRS = {'qa', 'delivery', 'browser-qa-history', 'finalization-audits'}
MEDIA_REPORTS = (
    'raw/audio-archive/manifest.json', 'raw/audio-archive/media-manifest.json',
    'raw/video-archive-report.json', 'raw/web-video-archive-report.json',
    'raw/legacy-video-decryption-report.json', 'raw/course-extras-report.json',
    'raw/video-audio-components-report.json',
)
PRESENTATION_FILES = (
    'index.html', 'course-info.html', 'resources.html', 'web/app.js', 'web/app.css',
    'raw/authorized-course.json', 'raw/public/catalog.json', 'course-config.json',
    'raw/authorized-web-media.json', 'raw/authorized-extra-audio.json',
)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def sha_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def local_file(root, value):
    if not isinstance(value, str) or not value or '://' in value:
        raise ValueError('Expected an archive-relative file')
    root = Path(root).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Missing or escaping archive path: ' + value)
    return path


def is_post_final(value):
    parts = Path(value).parts
    if not parts or parts[0] != 'raw':
        return False
    if len(parts) > 1 and parts[1] in POST_FINAL_DIRS:
        return True
    name = parts[-1]
    return name == 'batch-local-state.json' or name == 'browser-qa.json' or name.startswith('browser-qa-') or name == 'image-load-recheck.json'


def media_report_paths(root):
    """Finite producer contracts plus an explicit hash-bound typed registry."""
    root = Path(root).resolve()
    paths = {root / value for value in MEDIA_REPORTS if (root / value).is_file()}
    for directory in ('raw/audio-archive/media', 'raw/audit-runs'):
        folder = root / directory
        if folder.is_dir():
            for path in folder.rglob('*.json'):
                if directory.endswith('media'):
                    paths.add(path)
                else:
                    try:
                        value = json.loads(path.read_text())
                    except (OSError, ValueError):
                        continue
                    if value.get('evidence_role') == 'media_validation' and value.get('producer') == 'audit_archive':
                        paths.add(path)
    registry = root / 'raw/evidence-index.json'
    if registry.is_file():
        index = json.loads(registry.read_text())
        for row in index.get('reports', []):
            if row.get('role') not in {'media_transform', 'media_validation'}:
                continue
            path = local_file(root, row.get('path'))
            if is_post_final(path.relative_to(root)) or sha_file(path) != row.get('sha256'):
                raise ValueError('Invalid typed media evidence registry entry')
            value = json.loads(path.read_text())
            if value.get('evidence_role') != row['role']:
                raise ValueError('Producer evidence role does not match registry')
            paths.add(path)
    return sorted(paths)


def content_manifest_sha(course):
    from media_inventory import content_manifest_digest
    return content_manifest_digest(course)


def presentation_snapshot(root):
    root = Path(root).resolve()
    course = json.loads((root / 'course.json').read_text())
    files = {}
    required = set(PRESENTATION_FILES[:7])
    for value in PRESENTATION_FILES:
        path = root / value
        if not path.is_file():
            if value in required:
                raise ValueError('Missing presentation input: ' + value)
            continue
        files[value] = {'sha256': sha_file(path), 'bytes': path.stat().st_size}
    result = {'schema_version': 1, 'course_enid': course['course_enid'],
              'content_manifest_sha256': content_manifest_sha(course), 'files': files}
    result['fingerprint'] = canonical_sha(result)
    return result


def verify_presentation_snapshot(root, snapshot):
    current = presentation_snapshot(root)
    if current != snapshot:
        raise ValueError('Current course/source/reader assets differ from browser QA inputs')
    return current


def verify_bound_audit(root, report):
    root = Path(root).resolve()
    if report.get('status') != 'passed' or report.get('errors') != [] or report.get('summary', {}).get('errors') != 0:
        raise ValueError('A passed local audit with no errors is required')
    if report.get('validation_schema_version', 0) < 2:
        raise ValueError('Run the upgraded local auditor before delivery')
    snapshots = report.get('input_snapshots', {})
    if not all(key in snapshots for key in ('manifest', 'source_archive', 'source_catalog')):
        raise ValueError('Local audit lacks source input snapshots')
    for row in [*snapshots.values(), *report.get('audited_files', [])]:
        value = row.get('path', '')
        if is_post_final(value):
            raise ValueError('Post-final QA evidence must not be a core audit input')
        path = local_file(root, value)
        if sha_file(path) != row.get('sha256') or row.get('bytes', path.stat().st_size) != path.stat().st_size:
            raise ValueError('Local audited file changed: ' + value)
    if not report.get('audited_files'):
        raise ValueError('Local audit lacks output file snapshots')
    return True
