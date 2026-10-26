#!/usr/bin/env python3
"""Small, synthetic source-inventory/extras/reader regression fixtures (loopback only)."""
from __future__ import annotations
import argparse
from contextlib import contextmanager, redirect_stdout
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import importlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

SKILL=Path(__file__).resolve().parents[1]
TEMPLATE=SKILL/'assets/dedao-template'
sys.path.insert(0,str(TEMPLATE/'scripts'))
from media_inventory import canonical,content_manifest_digest,digest,discover_inventory,load_inventory,verify_inventory
from archive_course_extras import archive_resource,apply_report,file_record


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def run(root,*args):
    p=subprocess.run([sys.executable,str(root/'scripts'/args[0]),*args[1:]],capture_output=True,text=True)
    if p.returncode:raise AssertionError(p.stdout+'\n'+p.stderr)
    return p

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

@contextmanager
def serve(folder):
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(folder)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()

def make_assets(folder):
    folder.mkdir(parents=True,exist_ok=True)
    commands=[['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=c=blue:s=64x48:r=10:d=0.6','-f','lavfi','-i','sine=frequency=440:duration=0.6','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(folder/'tiny.mp4')],['ffmpeg','-nostdin','-v','error','-y','-i',str(folder/'tiny.mp4'),'-map','0:a','-c','copy',str(folder/'audio.m4a')],['ffmpeg','-nostdin','-v','error','-y','-i',str(folder/'tiny.mp4'),'-frames:v','1',str(folder/'poster.png')]]
    for command in commands:
        p=subprocess.run(command,capture_output=True,text=True)
        if p.returncode:raise AssertionError(p.stderr)
    p=subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(folder/'audio.m4a'),'-map','0:a','-c','copy','-hls_time','0.2','-hls_list_size','0',str(folder/'audio.m3u8')],capture_output=True,text=True)
    if p.returncode:raise AssertionError(p.stderr)
    (folder/'current.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:00.500\n正文字幕\n',encoding='utf-8')
    (folder/'catalog.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:00.500\n目录旧版本字幕\n',encoding='utf-8')
    (folder/'intro.vtt').write_text('WEBVTT\n\n00:00:00.000 --> 00:00:00.500\n课程介绍字幕\n',encoding='utf-8')
    (folder/'current.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\n正文字幕\n',encoding='utf-8')
    (folder/'protected.m4a').write_bytes(b'observed-protected-source-fixture\x00'*8)
    (folder/'notes.pdf').write_bytes(b'%PDF-1.4\n% exact synthetic attachment bytes\n%%EOF\n')

def make_course(root,assets,base):
    shutil.copytree(TEMPLATE,root,dirs_exist_ok=True)
    for directory in ['raw','content','assets/video/original','assets/video/decrypted','assets/images']:(root/directory).mkdir(parents=True,exist_ok=True)
    for path in ['assets/video/lesson.mp4','assets/video/original/lesson.mp4','assets/video/decrypted/lesson.mp4']:shutil.copyfile(assets/'tiny.mp4',root/path)
    shutil.copyfile(assets/'poster.png',root/'assets/images/cover.png')
    lesson_video={'dd_media_id_str':'lesson-media','bitrate_48':base+'/tiny.mp4','bitrate_48_audio':base+'/protected.m4a','is_drm':True,'vtt_caption':base+'/current.vtt','caption':base+'/current.srt','duration':0.6}
    source={'complete':True,'errors':[],'course':{'enid':'fixture-course','title':'脱敏课程','index_img':base+'/poster.png'},'metadata':{'class_video':{'dd_media_id_str':'intro-media','bitrate_48':base+'/tiny.mp4','bitrate_48_audio':base+'/audio.m4a','cover_img':base+'/poster.png','vtt_caption':base+'/intro.vtt','duration':0.6}},'lessons':[{'id':'lesson-1','info':{'article_info':{'audio_alias_ids':[],'video':[lesson_video]}},'catalog':{'video':[{'dd_media_id_str':'lesson-media','vtt_caption':base+'/catalog.vtt'}]},'body':{'content':[{'type':'text','text':'保留源文稿。'},{'type':'attachment','url':base+'/notes.pdf'}]}}]}
    write_json(root/'raw/authorized-course.json',source)
    primary={**file_record(root,root/'assets/video/lesson.mp4'),'source_media_id':'lesson-media','video_index':0,'resolution':48,'label':'课程视频','archive_report':'raw/web-video-archive-report.json'}
    lesson={'id':'lesson-1','title':'第一讲','source_url':'https://example.invalid/lesson','markdown_path':'content/lesson.md','html_path':'content/lesson.html','audio':[],'video':[primary],'video_decrypted_original':[{**file_record(root,root/'assets/video/decrypted/lesson.mp4'),'resolution':48}],'video_plaintext_original':[{**file_record(root,root/'assets/video/original/lesson.mp4'),'resolution':48}]}
    (root/'content/lesson.md').write_text('# 原文标题\n\n保留源文稿。\n',encoding='utf-8')
    (root/'content/lesson.html').write_text('<h1>原文标题</h1><p>保留源文稿。</p><figure class="source-video"><video controls src="../assets/video/lesson.mp4"></video><figcaption>原文位置视频</figcaption></figure>',encoding='utf-8')
    (root/'content/课程信息.md').write_text('# 脱敏课程介绍\n\n原始介绍保持不变。\n',encoding='utf-8')
    course={'title':'脱敏课程','course_enid':'fixture-course','source_url':'https://example.invalid/course','cover_path':'assets/images/cover.png','lessons':[lesson]}
    write_json(root/'course.json',course)
    write_json(root/'raw/public/catalog.json',{'class_info':{'enid':'fixture-course','current_article_count':1},'chapter_list':[{'article_list':[{'id':'lesson-1'}]}]})
    write_json(root/'assets/images/manifest.json',[{'source_url':base+'/poster.png',**file_record(root,root/'assets/images/cover.png')}])
    write_json(root/'raw/web-video-archive-report.json',{'videos':[{**primary,'status':'complete','full_decode_exit_code':0}]})
    write_json(root/'raw/video-archive-report.json',{'videos':[{**file_record(root,root/'assets/video/original/lesson.mp4'),'lesson_id':'lesson-1','source_media_id':'lesson-media','video_index':0,'source_url_sha256':hashlib.sha256((base+'/tiny.mp4').encode()).hexdigest()}]})
    return source,course

def complete_course(root):
    run(root,'archive_course_extras.py');run(root,'archive_course_extras.py','--apply')
    for builder in ['build_course_info.py','build_resources.py','build_site.py']:run(root,builder)

class InventoryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='course-synthetic-tests-');cls.base=Path(cls.temp.name);cls.assets=cls.base/'source-assets';make_assets(cls.assets)
        cls.server=serve(cls.assets);cls.url=cls.server.__enter__()
    @classmethod
    def tearDownClass(cls):cls.server.__exit__(None,None,None);cls.temp.cleanup()
    def setUp(self):
        self.root=self.base/self._testMethodName;self.source,self.course=make_course(self.root,self.assets,self.url)
    def test_expected_inventory_is_source_driven_and_exact(self):
        inventory=load_inventory(self.root);roles=[r['role'] for r in inventory['resources']]
        self.assertEqual(roles.count('video_audio_component'),1);self.assertEqual(roles.count('subtitle'),4)
        self.assertIn('course_intro_video',roles);self.assertIn('course_intro_audio',roles);self.assertIn('attachment',roles)
        self.assertEqual(verify_inventory(self.root,inventory)['status'],'failed')
        source=json.loads(json.dumps(self.source));source['lessons'][0]['info']['article_info']['video'].append(source['lessons'][0]['info']['article_info']['video'][0])
        self.assertIn('multiple_video_requires_explicit_adapter',[r['kind'] for r in discover_inventory(source)['issues']])
        source['metadata']['items']=[{'content':'<img src="https://example.invalid/a.png" srcset="https://example.invalid/b.png 2x"><p style="background:url(https://example.invalid/bg.png)">x</p>'}]
        inventory=discover_inventory(source);self.assertTrue(any(r['kind']=='metadata_embedded_media_requires_adapter' for r in inventory['issues']))
        self.assertTrue(any(r.get('embedded_source_format')=='html_img_src' for r in inventory['resources']))
    def test_complete_local_extras_and_reader_contract(self):
        before_md=digest(self.root/'content/lesson.md');before_info=digest(self.root/'content/课程信息.md');complete_course(self.root)
        course=json.loads((self.root/'course.json').read_text());report=json.loads((self.root/'raw/course-extras-report.json').read_text())
        self.assertEqual(report['status'],'passed');self.assertEqual(course['lessons'][0]['audio'],[])
        component=course['lessons'][0]['video_audio_components'][0]
        self.assertEqual(component['output_origin'],'derived_from_verified_video');self.assertTrue(component['derived_from_verified_video']['all_audio_packets_exact_match']);self.assertFalse(component['derived_from_verified_video']['source_audio_decryption_claimed'])
        self.assertEqual((self.root/component['encrypted_source']['path']).read_bytes(),(self.assets/'protected.m4a').read_bytes())
        self.assertEqual(verify_inventory(self.root)['status'],'passed')
        self.assertEqual(digest(self.root/'content/lesson.md'),before_md);self.assertEqual(digest(self.root/'content/课程信息.md'),before_info)
        html=(self.root/'index.html').read_text();payload=json.loads(html.split('<script id="course-data" type="application/json">')[1].split('</script>')[0])
        expected=payload.pop('reader_payload_sha256');self.assertEqual(expected,hashlib.sha256(canonical(payload)).hexdigest());self.assertEqual(payload['summary']['audio'],1)
        self.assertEqual(len(payload['lessons'][0]['subtitles']),3)
        self.assertIn('web/app.js?v='+digest(self.root/'web/app.js'),html);self.assertIn('web/app.css?v='+digest(self.root/'web/app.css'),html)
        resources=(self.root/'resources.html').read_text();self.assertIn('明文原件 MP4',resources);self.assertIn('解密原件 MP4',resources);self.assertIn(component['encrypted_source']['path'],resources)
        intro=(self.root/'course-info.html').read_text();self.assertIn('<track kind="subtitles"',intro);self.assertIn('下载课程介绍音频',intro);self.assertEqual(intro.count('<video '),1);self.assertNotIn('<audio ',intro)
        run(self.root,'archive_course_extras.py','--apply');again=json.loads((self.root/'course.json').read_text());self.assertEqual(len(again['course_intro_subtitles']),1);self.assertEqual(len(again['lessons'][0]['subtitles']),3)
        self.assertEqual(json.loads((self.root/'web/course-info-build-report.json').read_text())['status'],'passed')
    def test_protected_audio_rejects_wrong_video_and_unknown_protection(self):
        resource=next(r for r in load_inventory(self.root)['resources'] if r['role']=='video_audio_component')
        wrong={**resource,'source_media_id':'another-media'};result=archive_resource(self.root,wrong,self.course,[],None)
        self.assertEqual(result['status'],'failed');self.assertIn('exact source media ID',result['error']);self.assertTrue((self.root/result['encrypted_source']['path']).is_file())
        unknown={**resource,'source_declares_drm':False};result=archive_resource(self.root,unknown,self.course,[],None)
        self.assertEqual(result['status'],'failed');self.assertIn('without observed protection evidence',result['error']);self.assertIn('unplayable_source_original',result)
    def test_changed_video_or_incomplete_report_cannot_apply(self):
        complete_course(self.root);report=json.loads((self.root/'raw/course-extras-report.json').read_text())
        report['records'].pop()
        with self.assertRaisesRegex(ValueError,'full current source-driven'):apply_report(self.root,report)
        resource=next(r for r in load_inventory(self.root)['resources'] if r['role']=='video_audio_component')
        (self.root/'assets/video/lesson.mp4').write_bytes(b'changed-current-default')
        result=archive_resource(self.root,resource,self.course,[],None);self.assertEqual(result['status'],'failed')
    def test_exact_audio_alias_does_not_accept_different_source_url(self):
        source=json.loads(json.dumps(self.source));source['lessons'][0]['info']['article_info']['audio']={'alias_id':'alias-1','mp3_play_url':self.url+'/audio.m4a'}
        inventory=discover_inventory(source);resource=next(r for r in inventory['resources'] if r['role']=='main_audio')
        self.course['lessons'][0]['audio']=[{**file_record(self.root,self.root/'assets/video/lesson.mp4'),'audio_alias_id':'alias-1','source_url_sha256':'wrong-source'}]
        report=verify_inventory(self.root,inventory,self.course)
        self.assertTrue(any(e.get('resource_id')==resource['resource_id'] and e['kind']=='required_resource_missing_or_hash_mismatch' for e in report['errors']))
    def test_asset_hash_refresh_and_stable_content_digest(self):
        run(self.root,'build_site.py');first=json.loads((self.root/'web/build-report.json').read_text());course=json.loads((self.root/'course.json').read_text());stable=content_manifest_digest(course)
        course.update(archive_status='local_verified',archive_summary={'local':True},archive_finalization={'time':'fixture'})
        self.assertEqual(content_manifest_digest(course),stable);write_json(self.root/'course.json',course)
        (self.root/'web/app.js').write_text((self.root/'web/app.js').read_text()+'\n// fixture asset edit\n')
        run(self.root,'build_site.py');second=json.loads((self.root/'web/build-report.json').read_text());self.assertNotEqual(first['asset_versions'],second['asset_versions']);self.assertNotEqual(first['reader_payload_sha256'],second['reader_payload_sha256']);self.assertNotEqual(first['source_manifest_sha256'],second['source_manifest_sha256'])
    def test_subtitle_and_corrupt_poster_fail_closed(self):
        resource=next(r for r in load_inventory(self.root)['resources'] if r['role']=='subtitle');broken={**resource,'_url':self.url+'/notes.pdf'}
        self.assertEqual(archive_resource(self.root,broken,self.course,[],None)['status'],'failed')
        poster=next(r for r in load_inventory(self.root)['resources'] if r['role']=='course_intro_poster');broken={**poster,'_url':self.url+'/notes.pdf'}
        self.assertEqual(archive_resource(self.root,broken,self.course,[],None)['status'],'failed')
    def test_supplemental_standard_hls_keeps_source_objects_and_packet_proof(self):
        resource=next(r for r in load_inventory(self.root)['resources'] if r['role']=='course_intro_audio')
        url=self.url+'/audio.m3u8';resource={**resource,'_url':url,'source_url_sha256':hashlib.sha256(url.encode()).hexdigest()}
        result=archive_resource(self.root,resource,self.course,[],None)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['output_origin'],'standard_hls_lossless_remux')
        self.assertTrue(result['hls_audio_packet_proof']['all_audio_packets_exact_match']);self.assertGreater(result['hls']['segments'],0)
        self.assertTrue((self.root/result['hls']['source_playlist']['path']).is_file())

if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--demo',type=Path);args,remaining=parser.parse_known_args()
    if args.demo:
        # A persistent, fully local reader fixture for actual browser smoke QA.
        destination=args.demo.resolve();assets=destination.parent/(destination.name+'-source-assets');make_assets(assets)
        with serve(assets) as base:
            source,course=make_course(destination,assets,base)
            for number,text in [(2,'可搜索的第二讲正文。'),(3,'最后一讲，用于目录切换与恢复。')]:
                lid='lesson-'+str(number);path='content/lesson-'+str(number)+'.md'
                (destination/path).write_text('# 第'+str(number)+'讲\n\n'+text+'\n',encoding='utf-8')
                course['lessons'].append({'id':lid,'title':'第'+str(number)+'讲','markdown_path':path,'audio':[],'video':[]})
                source['lessons'].append({'id':lid,'info':{'article_info':{}},'body':{'content':[{'type':'text','text':text}]}})
            write_json(destination/'course.json',course);write_json(destination/'raw/authorized-course.json',source)
            write_json(destination/'raw/public/catalog.json',{'class_info':{'enid':'fixture-course','current_article_count':3},'chapter_list':[{'article_list':[{'id':l['id']} for l in course['lessons']]}]})
            complete_course(destination)
        print(destination)
    else:unittest.main(argv=[sys.argv[0],*remaining])
