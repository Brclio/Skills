"""Atomic local archive state and one-writer leases (no browser or network access)."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


def sha_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.tmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def course_lock(root, *, blocking=True, lease='manifest'):
    """Hold through read, verification and write. Never hold over child stages.

    A coordinator uses its own lease; child merge commands take the manifest
    lease themselves. This avoids a parent/child lock deadlock.
    """
    if lease not in {'manifest', 'coordinator'}:
        raise ValueError('Unknown archive lock role')
    path = Path(root) / 'raw' / ('.course-manifest.lock' if lease == 'manifest' else '.coordinator.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), flags)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def compare_and_write_manifest(root, expected_sha, value):
    """Compare-and-swap; caller must hold course_lock across the initial read."""
    path = Path(root) / 'course.json'
    if sha_file(path) != expected_sha:
        raise ValueError('Manifest changed before apply; reload and verify again')
    atomic_json(path, value)
