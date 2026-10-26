#!/usr/bin/env python3
"""Offline media regression fixtures. Uses synthetic media and a loopback server only.

The mixed-source fixture tests merge invariants with synthetic transform records;
it does not claim to exercise the provider's native cipher algorithm.
"""
from __future__ import annotations
import copy
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'assets/dedao-template/scripts'
sys.path.insert(0, str(SCRIPTS))
import archive_all_audio as audio
import archive_video as original
import archive_web_video as web
import archive_config as config
import apply_decrypted_videos as merge
import hls_assets as hls


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode: raise RuntimeError(result.stderr)
    return result


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def metadata(path, root):
    return {'path':path.relative_to(root).as_posix(),'bytes':path.stat().st_size,'sha256':hls.digest(path)}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Local ffmpeg and ffprobe are required')
class MediaCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='course-media-fixtures-')
        cls.base = Path(cls.temp.name); cls.source = cls.base/'source'; cls.source.mkdir()
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(cls.source)))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.video = cls.source/'source.mp4'
        run('ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(cls.video))
        cls.video_probe = json.loads(run('ffprobe','-v','error','-show_format','-show_streams','-of','json',str(cls.video)).stdout)
        cls.two = cls.source/'two.m4a'
        run('ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','sine=frequency=440','-f','lavfi','-i','sine=frequency=880','-t','2','-map','0:a','-map','1:a','-c:a','aac',str(cls.two))
        key = cls.source/'media.key';key.write_bytes(bytes(range(16)))
        keyinfo = cls.source/'keyinfo';keyinfo.write_text('media.key\n'+str(key)+'\n00112233445566778899AABBCCDDEEFF\n')
        run('ffmpeg','-nostdin','-y','-v','error','-f','lavfi','-i','sine=frequency=440','-t','2','-c:a','aac','-f','hls','-hls_time','0.5','-hls_key_info_file',str(keyinfo),'-hls_playlist_type','vod','-hls_segment_filename',str(cls.source/'part-%03d.ts'),str(cls.source/'audio.m3u8'))
        run('ffmpeg','-nostdin','-y','-v','error','-i',str(cls.video),'-c','copy','-f','hls','-hls_playlist_type','vod',str(cls.source/'video.m3u8'))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.workspace.name).resolve()
        for module in (audio, original, web, config, merge): module.ROOT = self.root
        audio.MEDIA_DIR = self.root/'assets/audio';audio.MEDIA_DIR.mkdir(parents=True)
        audio.REPORT_DIR = self.root/'raw/audio-archive'
        original.REPORT = self.root/'raw/video-archive-report.json'
        web.REPORT = self.root/'raw/web-video-archive-report.json'
        merge.REPORT = self.root/'raw/legacy-video-decryption-report.json';merge.COURSE = self.root/'course.json';merge.APPLY_REPORT = self.root/'raw/decrypted-video-apply-report.json'

    def tearDown(self): self.workspace.cleanup()

    def test_aes_hls_raw_graph_and_missing_or_modified_assets(self):
        report = hls.preserve_hls(self.url+'/audio.m3u8',self.root,'raw/hls')
        self.assertEqual(report['keys'],1); self.assertGreater(report['segments'],1)
        self.assertEqual(hls.audit_hls(self.root,report)['status'],'passed')
        rows = json.loads((self.root/report['assets_manifest_path']).read_text())
        key = next(row for row in rows if row['kind']=='key');path = self.root/key['path'];before = path.read_bytes();path.unlink()
        with self.assertRaises(ValueError): hls.audit_hls(self.root,report)
        path.write_bytes(before)
        segment = self.root/next(row['path'] for row in rows if row['kind']=='segment');saved = segment.read_bytes();segment.write_bytes(saved+b'X')
        with self.assertRaises(ValueError): hls.audit_hls(self.root,report)
        segment.write_bytes(saved)
        playlist = self.root/report['local_playlist_path'];playlist.write_text(playlist.read_text().replace('IV=0x','IV=0xF'))
        report['local_playlist_sha256'] = hls.digest(playlist)
        with self.assertRaisesRegex(ValueError,'IV'): hls.audit_hls(self.root,report)

    def test_hls_existing_output_gets_raw_backfill_and_exact_packets(self):
        target = audio.MEDIA_DIR/'1.m4a'
        # Legacy output predates raw retention and has no current validation report.
        run('ffmpeg','-nostdin','-y','-v','error','-allowed_extensions','ALL','-i',str(self.source/'audio.m3u8'),'-map','0:a','-c','copy',str(target))
        before = hls.digest(target)
        entry = {'lesson_id':'1','_url':self.url+'/audio.m3u8','audio_alias_id':'fixture-alias','source_info_path':'raw/info.json','label':'fixture','expected_duration_seconds':2.0}
        report = audio.archive_media({'entry':entry,'media_id':'fixture-hls','lesson_ids':['1']},audio.REPORT_DIR,60,0)
        self.assertEqual(report['status'],'complete',report)
        self.assertTrue(report['download_reused']);self.assertEqual(before,hls.digest(target))
        self.assertTrue(report['hls_audio_packet_proof']['all_audio_packets_exact_match'])
        self.assertEqual(hls.audit_hls(self.root,report['hls'])['keys'],1)
        again = audio.archive_media({'entry':entry,'media_id':'fixture-hls','lesson_ids':['1']},audio.REPORT_DIR,60,0)
        self.assertTrue(again['cached_validation_reused'])

    def test_every_audio_stream_decoded_and_legacy_cache_upgraded(self):
        path = audio.MEDIA_DIR/'two.m4a';shutil.copyfile(self.two,path)
        old = {'status':'complete','sha256':hls.digest(path),'full_decode_exit_code':0,'ffprobe':{'streams':[{'codec_type':'audio'}]}}
        report = audio.validate(path,2,60,old)
        self.assertEqual(report['audio_stream_count'],2);self.assertFalse(report['cached_validation_reused'])
        self.assertTrue(report['full_decode']['reached_eof']);self.assertEqual(report['full_decode']['mapped_audio_streams'],'all')
        self.assertIn('stderr',report['full_decode']);self.assertIn('ffprobe_stderr',report)

    def test_direct_audio_does_not_reuse_a_different_source_url(self):
        path = audio.MEDIA_DIR/'7.m4a';shutil.copyfile(self.video,path)
        old = {**metadata(path,self.root),'status':'complete','audio_alias_id':'direct-alias','source_url_sha256':'0'*64}
        save_json(audio.REPORT_DIR/'media/direct.json',old)
        entry = {'lesson_id':'7','_url':self.url+'/two.m4a','audio_alias_id':'direct-alias','source_info_path':'raw/info.json','label':'fixture','expected_duration_seconds':2.0}
        report = audio.archive_media({'entry':entry,'media_id':'direct','lesson_ids':['7']},audio.REPORT_DIR,60,0)
        self.assertEqual(report['status'],'complete',report);self.assertFalse(report['download_reused'])
        self.assertEqual(path.read_bytes(),self.two.read_bytes());self.assertEqual(report['audio_stream_count'],2)

    def test_plaintext_original_download_does_not_overwrite_web(self):
        target = self.root/'assets/video/9.mp4';target.parent.mkdir(parents=True);target.write_bytes(b'web-sentinel')
        record = original.archive(('9',0,'fixture',{'dd_media_id_str':'media-9','bitrate_2160':self.url+'/source.mp4','bitrate_480':self.url+'/missing.mp4','duration':2,'is_drm':False}),{})
        self.assertEqual(record['status'],'complete',record)
        self.assertEqual(record['path'],'assets/video/original/9.mp4');self.assertEqual(record['source_role'],'plaintext_original')
        self.assertEqual(target.read_bytes(),b'web-sentinel');self.assertEqual((self.root/record['path']).read_bytes(),self.video.read_bytes())
        again = original.archive(('9',0,'fixture',{'dd_media_id_str':'media-9','bitrate_2160':self.url+'/source.mp4','bitrate_480':self.url+'/missing.mp4','duration':2,'is_drm':False}),{'9-0':record})
        self.assertEqual(record['sha256'],again['sha256']);self.assertEqual(target.read_bytes(),b'web-sentinel')

    def mixed(self):
        lessons=[];origins=[];transforms=[];source=[]
        for number in range(1,6):
            lid=str(number);webpath=self.root/f'assets/video/{lid}.mp4';webpath.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.video,webpath)
            track={**metadata(webpath,self.root),'duration':2.0,'resolution':90}
            lesson={'id':lid,'enid':'lesson-'+lid,'video':[track],'video_web_alternatives':[copy.deepcopy(track)]}
            identity={'dd_media_id_str':'media-'+lid,'is_drm':number<5,'duration':2.0,'bitrate_480':self.url+'/source.mp4'}
            source.append({'id':lid,'enid':lesson['enid'],'info':{'article_info':{'video':[identity]}}})
            if number<5:
                enc=self.root/f'assets/video/encrypted/{lid}.mp4.enc';enc.parent.mkdir(parents=True,exist_ok=True);enc.write_bytes(b'X'*self.video.stat().st_size)
                decrypted=self.root/f'assets/video/decrypted/{lid}.mp4';decrypted.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.video,decrypted)
                origin={**metadata(enc,self.root),'lesson_id':lid,'video_index':0,'source_media_id':'media-'+lid,'source_role':'encrypted_original','source_declares_drm':True,'status':'drm_source_saved_unplayable','playable':False,'download_complete':True}
                lesson['video_encrypted_original']=[copy.deepcopy(origin)]
                transforms.append({**metadata(decrypted,self.root),'lesson_id':lid,'status':'decrypted_verified','source_path':origin['path'],'source_sha256':origin['sha256'],'source_bytes':origin['bytes'],'original_unchanged':True,'conversion':'exact_native_cipher_transform_without_remux','duration':2.0,'probe':{'returncode':0,'data':self.video_probe},'decode':{'returncode':0,'all_audio_video_streams':True,'err_detect':'explode'},'normalized_stream_comparison':{'exact_vcl_and_audio_match':True}})
            else:
                plain=self.root/f'assets/video/original/{lid}.mp4';plain.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.video,plain)
                origin={**metadata(plain,self.root),'lesson_id':lid,'video_index':0,'source_media_id':'media-'+lid,'source_role':'plaintext_original','source_declares_drm':False,'status':'complete','playable':True,'download_complete':True,'duration':2.0,'probe':{'returncode':0,'data':self.video_probe},'decode':{'returncode':0,'all_audio_video_streams':True,'reached_eof':True,'err_detect':'explode'}}
                lesson['video_plaintext_original']=[copy.deepcopy(origin)]
            origin.update(source_url=self.url+'/source.mp4',source_url_sha256=hashlib.sha256((self.url+'/source.mp4').encode()).hexdigest(),resolution_selected=480)
            origins.append(origin);lessons.append(lesson)
        course={'course_enid':'fixture','expected_lesson_count':5,'lessons':lessons}
        save_json(self.root/'course.json',course);save_json(self.root/'course-config.json',{'course_enid':'fixture','expected_lesson_count':5})
        save_json(self.root/'raw/authorized-course.json',{'complete':True,'errors':[],'course':{'enid':'fixture'},'lessons':source})
        save_json(self.root/'raw/video-archive-report.json',{'videos':origins})
        return course,{'keys_or_tokens_saved_in_report':False,'videos':transforms}

    def test_mixed_four_cipher_one_plain_only_cipher_subset_required(self):
        course,report=self.mixed();original_bytes=(self.root/'assets/video/original/5.mp4').read_bytes()
        updated,checks=merge.prepare(course,report)
        self.assertEqual(len(checks),4);self.assertEqual(updated['video_decryption_summary']['expected'],4)
        self.assertEqual(updated['video_decryption_summary']['expected_source_videos'],5);self.assertEqual(updated['video_decryption_summary']['verified_plaintext_originals'],1)
        self.assertEqual(updated['lessons'][4]['video'][0]['path'],'assets/video/original/5.mp4')
        self.assertEqual(len(updated['lessons'][0]['video_decrypted_original']),1)
        self.assertEqual((self.root/'assets/video/original/5.mp4').read_bytes(),original_bytes)
        for broken in ('missing','extra_plain','transform','hash'):
            bad=copy.deepcopy(report)
            if broken=='missing':bad['videos'].pop()
            elif broken=='extra_plain':bad['videos'].append({**bad['videos'][0],'lesson_id':'5'})
            elif broken=='transform':bad['videos'][0]['conversion']='remux'
            else:bad['videos'][0]['source_sha256']='0'*64
            with self.assertRaises(ValueError,msg=broken):merge.prepare(course,bad)
        course['lessons'][0]['video_web_alternatives'][0]['resolution']=180
        updated,_=merge.prepare(course,report)
        self.assertEqual(updated['lessons'][0]['video'][0]['path'],'assets/video/1.mp4')
        self.assertEqual(updated['lessons'][0]['video_decrypted_original'][0]['path'],'assets/video/decrypted/1.mp4')

    def test_web_apply_preserves_mixed_roles_and_original_priority(self):
        course,report=self.mixed();updated,_=merge.prepare(course,report)
        save_json(self.root/'course.json',updated);save_json(merge.REPORT,report)
        preserved={path:hls.digest(path) for path in self.root.glob('assets/video/original/*')}
        local_hls=hls.preserve_hls(self.url+'/video.m3u8',self.root,'raw/video-hls/fixture')
        rows=[]
        for lesson in course['lessons']:
            track=lesson['video_web_alternatives'][0]
            rows.append({**track,'lesson_id':lesson['id'],'status':'complete','playable':True,'all_streams_decoded':True,'resolution_selected':90,'hls':local_hls})
        save_json(web.REPORT,{'expected_video_count':5,'videos':rows})
        web.apply_report();result=json.loads((self.root/'course.json').read_text())
        self.assertEqual(result['lessons'][0]['video'][0]['path'],'assets/video/decrypted/1.mp4')
        self.assertEqual(result['lessons'][4]['video'][0]['path'],'assets/video/original/5.mp4')
        self.assertNotIn('video_encrypted_original',result['lessons'][4])
        self.assertEqual(preserved,{path:hls.digest(path) for path in preserved})


if __name__=='__main__':unittest.main(verbosity=2)
