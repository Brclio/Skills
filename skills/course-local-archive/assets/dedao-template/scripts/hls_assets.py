"""Retain and audit finite standard HLS objects before offline lossless remuxing.

Only source-declared HTTP(S) URIs are followed. Standard identity AES-128 key
objects are course media assets; account credentials and private DRM inputs are
never discovered here. Unsupported HLS features fail before a complete report.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.tmp-{os.getpid()}-{threading.get_ident()}')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def local(root, value):
    root = Path(root).resolve()
    if not isinstance(value, str) or not value or urlsplit(value).scheme or urlsplit(value).netloc:
        raise ValueError('HLS asset must be a local course-relative file')
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('HLS asset is absent or outside the course')
    return path


def _media_lines(text):
    if not text.startswith('#EXTM3U') or '#EXT-X-ENDLIST' not in text:
        raise ValueError('HLS must be a complete finite VOD playlist')
    if any(tag in text for tag in ('#EXT-X-STREAM-INF', '#EXT-X-I-FRAME-STREAM-INF', '#EXT-X-BYTERANGE', 'BYTERANGE=', '#EXT-X-GAP')):
        raise ValueError('Master or byte-range HLS requires a separate explicit adapter')
    methods = set(re.findall(r'#EXT-X-KEY:.*?METHOD=([^,\r\n]+)', text))
    if methods - {'NONE', 'AES-128'} or any(x != 'identity' for x in re.findall(r'KEYFORMAT="([^"]+)"', text)):
        raise ValueError('Only standard identity AES-128 HLS is supported')
    for key_tag in (line for line in text.splitlines() if line.startswith('#EXT-X-KEY:')):
        method = re.findall(r'(?:^|[:,])METHOD=([^,\r\n]+)', key_tag)
        if len(method) != 1 or method[0] not in ('NONE','AES-128'):
            raise ValueError('HLS key method must be explicit standard identity AES-128 or NONE')
        if 'KEYFORMAT=' in key_tag and 'KEYFORMAT="identity"' not in key_tag:
            raise ValueError('Unsupported HLS key format')
        if method[0] == 'AES-128' and len(re.findall(r'URI="([^"]+)"', key_tag)) != 1:
            raise ValueError('Standard AES-128 HLS key must have one declared URI')
        if method[0] == 'NONE' and 'URI=' in key_tag:
            raise ValueError('HLS NONE key must not declare a key URI')
    durations = [float(value) for value in re.findall(r'#EXTINF:([0-9.]+)', text)]
    if not durations or any(value <= 0 for value in durations):
        raise ValueError('HLS has no complete positive segment duration list')
    refs = []
    for line in text.splitlines():
        if line.startswith('#') and 'URI=' in line:
            if not line.startswith(('#EXT-X-KEY:', '#EXT-X-MAP:')):
                raise ValueError('Unsupported HLS URI-bearing tag')
            found = re.findall(r'URI="([^"]+)"', line)
            if len(found) != 1:
                raise ValueError('HLS URI must be one quoted source reference')
            refs.append(('key' if line.startswith('#EXT-X-KEY:') else 'initialization', found[0]))
        elif line.strip() and not line.startswith('#'):
            refs.append(('segment', line.strip()))
    if sum(kind == 'segment' for kind, _ in refs) != len(durations):
        raise ValueError('HLS segment and duration counts differ')
    return refs, durations, sorted(methods)


def _download(url, target, root, timeout, previous=None):
    if urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('Observed HLS source must use HTTP or HTTPS')
    target.parent.mkdir(parents=True, exist_ok=True)
    source_sha = fingerprint(url)
    if previous and previous.get('path') == target.relative_to(root).as_posix() and previous.get('source_url_sha256') == source_sha and target.is_file() and target.stat().st_size == previous.get('bytes') and digest(target) == previous.get('sha256'):
        return previous
    temporary = target.with_name(target.name + '.part')
    request = Request(url, headers={'User-Agent': 'CourseLocalArchive/1.0'})
    try:
        with urlopen(request, timeout=timeout) as response, temporary.open('wb') as output:
            expected = int(response.headers.get('Content-Length') or 0) or None
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if not temporary.stat().st_size or expected is not None and temporary.stat().st_size != expected:
            raise ValueError('HLS source object download is incomplete')
        temporary.replace(target)
        return {'path': target.relative_to(root).as_posix(), 'source_url_sha256': source_sha, 'bytes': target.stat().st_size, 'sha256': digest(target)}
    finally:
        temporary.unlink(missing_ok=True)


def preserve_hls(url, root, destination, timeout=60):
    root = Path(root).resolve()
    folder = Path(destination)
    if not folder.is_absolute(): folder = root / folder
    folder = folder.resolve()
    if not folder.is_relative_to(root): raise ValueError('HLS destination escapes the course')
    manifest_path = folder / 'assets.json'
    previous_rows = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    previous = {row.get('source_url_sha256'): row for row in previous_rows}
    source = _download(url, folder / 'source.m3u8', root, timeout, previous.get(fingerprint(url)))
    source['kind'] = 'playlist'
    text = (folder / 'source.m3u8').read_text(encoding='utf-8-sig')
    refs, durations, methods = _media_lines(text)
    assets, saved, uri_map = [source], {}, []
    for kind, uri in refs:
        resolved = urljoin(url, uri)
        identity = fingerprint(resolved)
        if identity not in saved:
            suffix = Path(urlsplit(resolved).path).suffix
            if not re.fullmatch(r'\.[A-Za-z0-9]{1,8}', suffix): suffix = '.key' if kind == 'key' else '.bin'
            filename = kind + '-' + identity[:24] + suffix
            item = _download(resolved, folder / filename, root, timeout, previous.get(identity))
            item['kind'] = kind
            if kind == 'key':
                if item['bytes'] != 16: raise ValueError('Standard AES-128 HLS key object must contain 16 bytes')
                os.chmod(folder / filename, 0o600)
            assets.append(item); saved[identity] = item
            write_json(manifest_path, assets)
        item = saved[identity]
        if item['kind'] != kind: raise ValueError('One source HLS object has conflicting media roles')
        uri_map.append({'kind': kind, 'source_uri_sha256': fingerprint(uri), 'source_url_sha256': identity, 'path': item['path']})
    cursor = iter(uri_map)
    lines = []
    for line in text.splitlines():
        if line.startswith('#') and 'URI=' in line:
            item = next(cursor)
            relative = os.path.relpath(root / item['path'], folder)
            line = re.sub(r'URI="([^"]+)"', lambda _: 'URI="' + relative + '"', line)
        elif line.strip() and not line.startswith('#'):
            line = os.path.relpath(root / next(cursor)['path'], folder)
        lines.append(line)
    playlist = folder / 'local.m3u8'
    playlist.write_text('\n'.join(lines) + '\n')
    write_json(manifest_path, assets)
    report = {'schema_version': 1, 'source_url_sha256': fingerprint(url), 'source_playlist': source, 'local_playlist_path': playlist.relative_to(root).as_posix(), 'local_playlist_sha256': digest(playlist), 'assets_manifest_path': manifest_path.relative_to(root).as_posix(), 'assets_manifest_sha256': digest(manifest_path), 'segments': len(durations), 'keys': sum(row['kind'] == 'key' for row in assets), 'playlist_duration': sum(durations), 'encryption_methods': methods, 'uri_map': uri_map}
    audit_hls(root, report)
    return report


def audit_hls(root, report):
    """Freshly read every source object and verify the complete offline graph."""
    root = Path(root).resolve()
    if report.get('schema_version') != 1: raise ValueError('Missing current HLS preservation schema')
    source = report.get('source_playlist', {})
    source_path = local(root, source.get('path'))
    if source_path.stat().st_size != source.get('bytes') or digest(source_path) != source.get('sha256') or source.get('source_url_sha256') != report.get('source_url_sha256'):
        raise ValueError('Original HLS playlist does not match its source report')
    source_text = source_path.read_text(encoding='utf-8-sig')
    refs, durations, _ = _media_lines(source_text)
    manifest_path = local(root, report.get('assets_manifest_path'))
    if digest(manifest_path) != report.get('assets_manifest_sha256'): raise ValueError('HLS object manifest changed')
    assets = json.loads(manifest_path.read_text())
    objects = {}
    for item in assets:
        path = local(root, item.get('path'))
        if path.stat().st_size != item.get('bytes') or digest(path) != item.get('sha256'): raise ValueError('An original HLS source object changed')
        if item.get('kind') == 'key' and item.get('bytes') != 16: raise ValueError('Invalid standard HLS key length')
        if item['path'] in objects: raise ValueError('Duplicate HLS object manifest path')
        objects[item['path']] = item
    playlist = local(root, report.get('local_playlist_path'))
    if digest(playlist) != report.get('local_playlist_sha256'): raise ValueError('Local HLS playlist changed')
    localized, local_durations, _ = _media_lines(playlist.read_text())
    mapping = report.get('uri_map', [])
    if len(refs) != len(localized) or len(refs) != len(mapping) or durations != local_durations: raise ValueError('Source/local HLS structure differs')
    for (kind, uri), (local_kind, local_uri), item in zip(refs, localized, mapping):
        path = (playlist.parent / local_uri).resolve()
        if urlsplit(local_uri).scheme or urlsplit(local_uri).netloc or not path.is_relative_to(root): raise ValueError('Local HLS still contains remote or escaping URI')
        relative = path.relative_to(root).as_posix()
        if kind != local_kind or kind != item.get('kind') or fingerprint(uri) != item.get('source_uri_sha256') or relative != item.get('path') or relative not in objects or objects[relative].get('kind') != kind or objects[relative].get('source_url_sha256') != item.get('source_url_sha256'):
            raise ValueError('HLS source/local URI identity differs')
    expected_lines = []
    mapped = iter(mapping)
    for line in source_text.splitlines():
        if line.startswith('#') and 'URI=' in line:
            item = next(mapped)
            relative = os.path.relpath(root / item['path'], playlist.parent)
            line = re.sub(r'URI="([^"]+)"', lambda _: 'URI="' + relative + '"', line)
        elif line.strip() and not line.startswith('#'):
            line = os.path.relpath(root / next(mapped)['path'], playlist.parent)
        expected_lines.append(line)
    if playlist.read_text().splitlines() != expected_lines: raise ValueError('Local HLS changed source tags, key IV, sequence or ordering')
    if set(objects) != {source['path']} | {item['path'] for item in mapping}: raise ValueError('HLS object manifest includes undeclared or missing source objects')
    segments = sum(kind == 'segment' for kind, _ in refs)
    keys = sum(row.get('kind') == 'key' for row in assets)
    if segments != report.get('segments') or keys != report.get('keys') or abs(sum(durations)-float(report.get('playlist_duration', -1))) > .001: raise ValueError('HLS source object totals differ')
    return {'status': 'passed', 'segments': segments, 'keys': keys, 'objects': len(assets), 'source_playlist_sha256': source['sha256'], 'local_playlist_sha256': report['local_playlist_sha256']}


def audio_packet_proof(root, report, output, timeout=300):
    """Compare all compressed audio packets, normalizing AAC ADTS framing."""
    root = Path(root).resolve(); audit_hls(root, report)
    output = Path(output).resolve()
    if not output.is_relative_to(root) or not output.is_file(): raise ValueError('Audio output is absent or outside the course')
    output_sha = digest(output)
    probe = subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,codec_name','-of','json',str(output)],capture_output=True,text=True,timeout=min(timeout,60))
    if probe.returncode: raise ValueError('Saved audio cannot be probed')
    audio = [s for s in json.loads(probe.stdout).get('streams',[]) if s.get('codec_type') == 'audio']
    if not audio: raise ValueError('Saved audio has no audio stream')
    hashes, diagnostics = [], []
    for source in (local(root, report['local_playlist_path']), output):
        command = ['ffmpeg','-nostdin','-v','error']
        if source.suffix == '.m3u8': command += ['-allowed_extensions','ALL']
        command += ['-protocol_whitelist','file,crypto,data','-i',str(source),'-map','0:a','-c','copy']
        if all(s.get('codec_name') == 'aac' for s in audio): command += ['-bsf:a','aac_adtstoasc']
        command += ['-f','streamhash','-hash','sha256','-']
        process = subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        if process.returncode: raise ValueError('Local HLS/audio compressed packet comparison failed: ' + re.sub(r'https?://[^\s]+','[URL redacted]',process.stderr)[-3000:])
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        if len(lines) != len(audio): raise ValueError('Compressed packet comparison omitted an audio stream')
        hashes.append(lines)
        diagnostics.append(re.sub(r'https?://[^\s]+','[URL redacted]',process.stderr))
    if hashes[0] != hashes[1] or digest(output) != output_sha: raise ValueError('Saved audio does not exactly match all original HLS audio packets')
    return {'status':'passed','source_playlist_sha256':report['source_playlist']['sha256'],'local_playlist_sha256':report['local_playlist_sha256'],'output_path':output.relative_to(root).as_posix(),'output_sha256':output_sha,'source_audio_compressed_streamhashes':hashes[0],'saved_audio_compressed_streamhashes':hashes[1],'source_packet_stderr':diagnostics[0],'saved_packet_stderr':diagnostics[1],'all_audio_packets_exact_match':True,'audio_stream_count':len(audio),'comparison':'all compressed audio packets; AAC ADTS framing normalized; no reencoding'}
