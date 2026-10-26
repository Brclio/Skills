#!/usr/bin/env python3
"""Offline contract fixtures; never reads an installed skill or a real course."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'assets/dedao-template/scripts'
sys.path.insert(0,str(SCRIPTS))
from archive_state import atomic_json,course_lock,compare_and_write_manifest,sha_file
from audit_evidence import canonical_sha,media_report_paths,verify_bound_audit
from media_validation import FreshMediaRun,verify_warning_review
from qa_evidence import record_observation,verify_qa,product_bindings
from batch_local import ready_handoff,run_course


def put(root,path,value):
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
    if isinstance(value,(dict,list)):atomic_json(target,value)
    else:target.write_text(value)
    return target


def reader_fixture(root):
    course={'course_enid':'fixture-course','title':'Fixture','archive_status':'partial','expected_lesson_count':1,'lessons':[{'id':'one','title':'Lesson One','audio':[],'video':[]}]}
    put(root,'course.json',course);put(root,'web/app.js','/* fixture runtime */');put(root,'web/app.css','body{font-family:serif}')
    put(root,'raw/authorized-course.json',{'course':{'enid':'fixture-course'},'complete':True,'lessons':[{'id':'one'}]});put(root,'raw/public/catalog.json',{'class_info':{'enid':'fixture-course'}})
    put(root,'course-info.html','<title>Information</title>');put(root,'resources.html','<title>Resources</title>');put(root,'content/本地资源.md','Fixture resources')
    from media_inventory import content_manifest_digest
    versions={'app_js':sha_file(root/'web/app.js'),'app_css':sha_file(root/'web/app.css')}
    payload={'title':'Fixture','content_manifest_sha256':content_manifest_digest(course),'source_manifest_sha256':sha_file(root/'course.json'),'asset_versions':versions,'lessons':[{'id':'one','title':'Lesson One','text':'Fixture source prose','section':'Fixture'}]}
    payload['reader_payload_sha256']=canonical_sha(payload)
    put(root,'index.html','<script id="course-data" type="application/json">'+json.dumps(payload)+'</script>')
    snapshot=put(root,'raw/qa/snapshot.txt','Synthetic browser fixture state (not a real UI claim)')
    common={'artifacts':['raw/qa/snapshot.txt']}
    proofs=[{'kind':'navigation','observed':{'catalog_count':1,'visits':[{'lesson_id':'one','title':'Lesson One'}]},**common},
            {'kind':'search','observed':{'query':'Fixture','result_lesson_ids':['one']},**common},
            {'kind':'font_control','observed':{'before_px':18,'after_px':19,'font_faces_ready':True},**common},
            {'kind':'layout','observed':{'viewport_width':1200,'horizontal_overflow_px':0,'failed_image_count':0,'console_errors':[]},**common},
            {'kind':'info','observed':{'page_path':'course-info.html','title':'Information','missing_resource_count':0},**common},
            {'kind':'resources','observed':{'page_path':'resources.html','title':'Resources','missing_resource_count':0},**common},
            {'kind':'download','path':'content/本地资源.md','observed':{'bytes':(root/'content/本地资源.md').stat().st_size,'sha256':sha_file(root/'content/本地资源.md'),'initiated_from_ui':True},**common}]
    observation={'captured_at_utc':datetime.now(timezone.utc).isoformat(),'browser':'offline-fixture','page_url':'http://127.0.0.1:8766/index.html','loaded_payload':payload,'runtime_urls':['http://127.0.0.1:8766/web/app.js?v='+versions['app_js'],'http://127.0.0.1:8766/web/app.css?v='+versions['app_css']],'runtime_markers':{'readerPayloadSha256':payload['reader_payload_sha256'],'appJsSha256':versions['app_js'],'appCssSha256':versions['app_css']},'proofs':proofs}
    source=put(root,'raw/qa/observation.json',observation);report=record_observation(root,observation)
    report['observation_source']={'path':'raw/qa/observation.json','sha256':sha_file(source)}
    for proof in report['proofs']:proof['observation_source']=report['observation_source']
    return course,observation,report


class Contracts(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_stale_loaded_runtime_and_partial_product_binding(self):
        _,observation,qa=reader_fixture(self.root)
        self.assertEqual(verify_qa(self.root,qa)['status'],'passed')
        before=product_bindings(self.root)
        put(self.root,'course-info.html','<title>Changed information</title>')
        after=product_bindings(self.root)
        self.assertEqual(before['reader'],after['reader'])
        self.assertNotEqual(before['info'],after['info'])
        with self.assertRaisesRegex(ValueError,'info'):verify_qa(self.root,qa)
        wrong=copy.deepcopy(observation);wrong['runtime_markers']['appJsSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'runtime'):record_observation(self.root,wrong)

    def test_lifecycle_only_rebind_preserves_ui_content(self):
        course,observation,qa=reader_fixture(self.root);before=product_bindings(self.root)
        course.update(archive_status='local_verified',archive_summary={'lessons':1},archive_finalization={'status':'local_verified'})
        put(self.root,'course.json',course)
        self.assertEqual(before,product_bindings(self.root))
        self.assertEqual(verify_qa(self.root,qa)['status'],'passed')

    def test_qa_write_does_not_pollute_media_inputs_or_core_audit(self):
        reader_fixture(self.root)
        producer=put(self.root,'raw/audio-archive/manifest.json',{'media':[]})
        baseline=media_report_paths(self.root)
        put(self.root,'raw/qa/contrived-media.json',{'media':[{'path':'assets/audio/fake.m4a','sha256':'x'}]})
        put(self.root,'raw/browser-qa-old.json',{'media':[{'path':'assets/audio/fake.m4a','sha256':'x'}]})
        put(self.root,'raw/delivery/status.json',{'status':'fully_delivered'})
        self.assertEqual(baseline,media_report_paths(self.root))
        self.assertIn(producer.resolve(),baseline)
        snapshots={role:{'path':path,'sha256':sha_file(self.root/path)} for role,path in [('manifest','course.json'),('source_archive','raw/authorized-course.json'),('source_catalog','raw/public/catalog.json')]}
        report={'status':'passed','errors':[],'summary':{'errors':0},'validation_schema_version':2,'input_snapshots':snapshots,'audited_files':[{'path':'index.html','sha256':sha_file(self.root/'index.html'),'bytes':(self.root/'index.html').stat().st_size}]}
        self.assertTrue(verify_bound_audit(self.root,report))
        put(self.root,'raw/qa/contrived-media.json',{'changed':True})
        self.assertTrue(verify_bound_audit(self.root,report))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg/FFprobe unavailable')
    def test_fresh_decodes_both_audio_tracks_and_resumes_same_hash(self):
        put(self.root,'course.json',{'course_enid':'fixture-course'})
        target=self.root/'assets/audio/multi.m4a';target.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.3','-f','lavfi','-i','sine=frequency=660:duration=0.3','-map','0:a','-map','1:a','-c:a','aac','-threads','1',str(target)],check=True,capture_output=True)
        run=FreshMediaRun(self.root,'fixture-run');row=run.validate('assets/audio/multi.m4a','audio')
        self.assertEqual(row['status'],'complete');self.assertEqual(row['audio_stream_count'],2);self.assertTrue(row['all_streams_decoded'])
        self.assertIn('0:a',row['decode']['command']);self.assertIn('progress=end',row['decode']['progress']);self.assertIn('stderr',row['decode'])
        resumed=FreshMediaRun(self.root,'fixture-run',resume=True);again=resumed.validate('assets/audio/multi.m4a','audio')
        self.assertEqual(again['sha256'],row['sha256']);self.assertEqual(resumed.reused,1);self.assertEqual(resumed.executed,0)
        with self.assertRaisesRegex(ValueError,'already exists'):FreshMediaRun(self.root,'fixture-run')
        changed=self.root/'assets/audio/changed.m4a'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','sine=frequency=880:duration=0.3','-c:a','aac','-threads','1',str(changed)],check=True,capture_output=True)
        changed.replace(target)
        new=FreshMediaRun(self.root,'fixture-run',resume=True);newrow=new.validate('assets/audio/multi.m4a','audio')
        self.assertNotEqual(newrow['sha256'],row['sha256']);self.assertEqual(new.executed,1);self.assertEqual(new.reused,0)

    def test_source_warning_review_exact_diagnostics_and_current_counterpart(self):
        put(self.root,'assets/video/source.mp4','immutable counterpart fixture')
        stderr='source diagnostic retained verbatim'
        decoded={'path':'assets/video/decoded.mp4','sha256':'a'*64,'kind':'video','video_frames_decoded':4,'decode':{'stderr':stderr}}
        checks={'container_structure_verified':True,'all_streams_compared':True,'all_compressed_packets_equal':True,'decode_reached_eof':True,'expected_video_frames':4,'decoded_video_frames':4}
        review={'evidence_role':'source_metadata_verification','status':'passed','media':[{'path':decoded['path'],'sha256':decoded['sha256'],'stderr_sha256':hashlib.sha256(stderr.encode()).hexdigest(),'counterpart_path':'assets/video/source.mp4','counterpart_sha256':sha_file(self.root/'assets/video/source.mp4'),'checks':checks}]}
        put(self.root,'raw/source-metadata-review.json',review)
        self.assertTrue(verify_warning_review(self.root,'raw/source-metadata-review.json',decoded))
        changed=copy.deepcopy(decoded);changed['video_frames_decoded']=3
        self.assertIsNone(verify_warning_review(self.root,'raw/source-metadata-review.json',changed))
        put(self.root,'assets/video/source.mp4','changed')
        self.assertIsNone(verify_warning_review(self.root,'raw/source-metadata-review.json',decoded))

    def test_single_writer_lock_and_manifest_compare_and_swap(self):
        put(self.root,'course.json',{'course_enid':'fixture-course','marker':'old'});before=sha_file(self.root/'course.json')
        with course_lock(self.root):
            with self.assertRaises(BlockingIOError):
                with course_lock(self.root,blocking=False):pass
            compare_and_write_manifest(self.root,before,{'course_enid':'fixture-course','marker':'new'})
            with self.assertRaisesRegex(ValueError,'changed'):compare_and_write_manifest(self.root,before,{'marker':'lost update'})
        self.assertEqual(json.loads((self.root/'course.json').read_text())['marker'],'new')

    def test_private_handoff_requires_atomic_ready_and_exact_proof_hash(self):
        folder=self.root/'private';source=put(folder,'authorized-course.json',{'course':{'enid':'fixture-course'},'complete':True,'lessons':[{'id':'one'}],'errors':[]})
        proof=put(folder,'proof.json',{'course_enid':'fixture-course','status':'complete','errors':[],'files':[{'path':'authorized-course.json','sha256':sha_file(source),'bytes':source.stat().st_size}]})
        with self.assertRaises(FileNotFoundError):ready_handoff(folder,'fixture-course')
        put(folder,'ready.json',{'ready':True,'course_enid':'fixture-course','proof_path':'proof.json','proof_sha256':sha_file(proof)})
        self.assertEqual(ready_handoff(folder,'fixture-course')['status'],'ready_verified')
        put(folder,'proof.json',{'modified':True})
        with self.assertRaisesRegex(ValueError,'hash'):ready_handoff(folder,'fixture-course')

    def test_batch_core_failure_cannot_promote_old_delivery_and_exception_is_persistent(self):
        reader_fixture(self.root);put(self.root,'raw/delivery/status.json',{'status':'fully_delivered'})
        put(self.root,'scripts/build_course_info.py','raise SystemExit(2)')
        with patch('verify_delivery.verify_delivery',return_value={'status':'fully_delivered'}) as gate:
            result=run_course(self.root,stage='pipeline');self.assertEqual(result['status'],'failed');gate.assert_not_called()
        state=json.loads((self.root/'raw/batch-local-state.json').read_text());self.assertEqual(state['status'],'failed');self.assertIn('finished_at_utc',state)
        result=run_course(self.root,stage='audit')
        self.assertEqual(result['status'],'failed');state=json.loads((self.root/'raw/batch-local-state.json').read_text());self.assertIn('error',state);self.assertIn('finished_at_utc',state)

if __name__=='__main__':unittest.main()
