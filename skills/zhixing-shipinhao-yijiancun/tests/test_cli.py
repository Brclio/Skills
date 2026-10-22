"""Offline CLI regression checks; Tencent responses and media are fixtures."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import core
import wx_video

MEDIA = b'\x00\x00\x00\x18ftypisom' + b'fixture' * 600


class OfflineCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.urls = []
        self.sessions = 0

        def open_context(wait):
            self.sessions += 1
            yield type('Context', (), {'request': self})(), self

        for patcher in (
            patch.object(wx_video, '_open_context', open_context),
            patch.object(Path, 'home', return_value=self.home),
            patch.object(core.urllib.request, 'build_opener', return_value=self),
            patch.object(socket, 'socket', side_effect=AssertionError('External network disabled')),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def evaluate(self, script, arguments):
        url = arguments['sourceUrl']
        self.urls.append(url)
        if url.endswith('Limit'):
            return {'status': 429, 'body': ''}
        return {'status': 200, 'body': json.dumps({
            'playable_url': 'https://channels.weixin.qq.com/finder-preview/pages/feed?token=fixtureToken&eid=fixtureEid'
        })}

    def post(self, endpoint, **kwargs):
        self.assertEqual(endpoint, 'https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info')
        self.assertEqual(kwargs['data']['exportId'], 'fixtureEid')
        payload = {'h264VideoInfo': {'videoUrl': 'https://video.qq.com/fixture.mp4'},
                   'description': 'Offline fixture'}
        return type('Response', (), {'status': 200, 'json': lambda response: payload})()

    def open(self, request, **kwargs):
        self.assertEqual(request.full_url, 'https://video.qq.com/fixture.mp4')
        response = io.BytesIO(MEDIA)
        response.headers = {'Content-Length': str(len(MEDIA))}
        return response

    def call_main(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = wx_video.main(arguments)
        return code, json.loads(output.getvalue())

    def test_single_download_on_clean_machine(self):
        code, result = self.call_main(['download', 'https://weixin.qq.com/sph/TestA'])
        self.assertEqual(code, 0)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(Path(result['file_path']).read_bytes(), MEDIA)
        self.assertEqual(result['sha256'], hashlib.sha256(MEDIA).hexdigest())
        self.assertEqual(self.sessions, 1)
        self.assertFalse((self.home / 'Library').exists())
        self.assertFalse(list(self.home.rglob('*.part')))

    def test_batch_download_deduplication_and_report(self):
        code, report = self.call_main(['batch',
            '--url', 'https://weixin.qq.com/sph/TestA',
            '--url', 'https://weixin.qq.com/sph/TestB',
            '--url', 'https://weixin.qq.com/sph/TestA',
            '--url', 'invalid'])
        self.assertEqual(code, 0)
        self.assertEqual((report['requested'], report['saved'], report['failed'], report['skipped']), (4, 2, 1, 1))
        self.assertEqual(self.sessions, 1)
        self.assertEqual(len(self.urls), 2)
        saved = json.loads(Path(report['report_path']).read_text())
        self.assertEqual(saved['saved'], 2)
        for item in report['items']:
            if item['status'] == 'success':
                self.assertEqual(Path(item['file_path']).read_bytes(), MEDIA)
        self.assertNotIn('fixtureToken', Path(report['report_path']).read_text())

    def test_platform_rate_limit_still_stops_later_links(self):
        code, report = self.call_main(['batch',
            '--url', 'https://weixin.qq.com/sph/Limit',
            '--url', 'https://weixin.qq.com/sph/TestB'])
        self.assertEqual(code, 2)
        self.assertEqual((report['saved'], report['failed'], report['skipped']), (0, 1, 1))
        self.assertEqual(len(self.urls), 1)
        self.assertEqual(report['items'][0]['code'], 'RATE_LIMITED')

    def test_invalid_link_still_rejected_before_browser(self):
        code, result = self.call_main(['download', 'https://example.com/video'])
        self.assertEqual(code, 2)
        self.assertEqual(result['code'], 'INVALID_LINK')
        self.assertEqual(self.sessions, 0)

    def test_tencent_login_still_required(self):
        def login_needed(wait):
            raise core.SkillError('LOGIN_REQUIRED', 'User must scan Tencent login QR code.')
            yield
        with patch.object(wx_video, '_open_context', login_needed):
            code, result = self.call_main(['download', 'https://weixin.qq.com/sph/TestA'])
        self.assertEqual(code, 2)
        self.assertEqual(result['code'], 'LOGIN_REQUIRED')

    def test_activation_commands_removed(self):
        for command in ['activate', 'activation-status']:
            with self.subTest(command=command), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    wx_video.main([command])
                self.assertEqual(error.exception.code, 2)

    def test_help_has_only_supported_free_workflows(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as error:
            wx_video.main(['--help'])
        self.assertEqual(error.exception.code, 0)
        self.assertIn('{doctor,download,batch}', output.getvalue())
        self.assertNotIn('activate', output.getvalue())
        self.assertNotIn('invite', sys.modules)


if __name__ == '__main__':
    unittest.main(verbosity=2)
