#!/usr/bin/env python3
"""Serve a local archive on loopback, including byte ranges for media seeking."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import webbrowser


class ArchiveHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        self.byte_range = None
        path = Path(self.translate_path(self.path))
        requested = self.headers.get('Range')
        if not requested or not path.is_file():
            return super().send_head()
        length = path.stat().st_size
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
        if not match or not any(match.groups()) or not length:
            return self.range_error(length)
        left, right = match.groups()
        if left:
            start = int(left)
            end = min(int(right), length - 1) if right else length - 1
        else:
            start = max(0, length - int(right))
            end = length - 1
        if start >= length or end < start:
            return self.range_error(length)
        try:
            source = path.open('rb')
        except OSError:
            self.send_error(404)
            return None
        self.byte_range = (start, end)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Content-Range', f'bytes {start}-{end}/{length}')
        self.send_header('Last-Modified', self.date_time_string(path.stat().st_mtime))
        self.end_headers()
        return source

    def range_error(self, length):
        self.send_response(416)
        self.send_header('Content-Range', f'bytes */{length}')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return None

    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def copyfile(self, source, output):
        if self.byte_range is None:
            return super().copyfile(source, output)
        start, end = self.byte_range
        source.seek(start)
        remaining = end - start + 1
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            output.write(chunk)
            remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--open', action='store_true', help='Open the local reader when the user runs this launcher')
    args = parser.parse_args()
    handler = partial(ArchiveHandler, directory=str(args.root.resolve()))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError:
        if not args.open:
            raise
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    url = f'http://127.0.0.1:{server.server_port}/index.html'
    print(f'Local course: {url}', flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
