#!/usr/bin/env python3
"""Bind actual CUA/browser observations to current files; does not drive a browser.

--print-browser-probe prints a passive DOM expression to collect after approved
UI actions. Save its value plus action results/proofs under raw/qa, then use
--observation. Each proof needs a saved browser screenshot or tool snapshot.
"""
import argparse
import json
from pathlib import Path
from archive_state import atomic_json
from qa_evidence import record_observation, product_bindings

ROOT=Path(__file__).resolve().parents[1]
BROWSER_PROBE=r'''(() => ({captured_at_utc:new Date().toISOString(),browser:typeof navigator==="undefined"?null:navigator.userAgent,page_url:location.href,loaded_payload:JSON.parse(document.getElementById("course-data").textContent),runtime_urls:[...document.scripts].map(x=>x.src).concat([...document.querySelectorAll('link[rel="stylesheet"]')].map(x=>x.href)),runtime_markers:{...document.documentElement.dataset},current:{lesson_id:document.querySelector('[aria-current="page"][data-lesson-id]')?.dataset.lessonId||(location.hash.startsWith('#lesson=')?decodeURIComponent(location.hash.slice(8)):null),lesson_id_source:document.querySelector('[aria-current="page"][data-lesson-id]')?'visible_current_catalog_link':location.hash.startsWith('#lesson=')?'actual_location_hash':null,title:document.querySelector('.article-header h2')?.textContent,search_query:document.getElementById('search')?.value,result_lesson_ids:[...document.querySelectorAll('[data-lesson-id]')].map(x=>x.dataset.lessonId),font_px:parseFloat(getComputedStyle(document.querySelector('.article-body')||document.body).fontSize),font_faces_ready:document.fonts.status==='loaded',viewport_width:innerWidth,horizontal_overflow_px:document.documentElement.scrollWidth-innerWidth,failed_image_count:[...document.images].filter(x=>!x.complete||x.naturalWidth===0).length,media:[...document.querySelectorAll('audio,video')].map(x=>({path:x.getAttribute('src'),current_time:x.currentTime,ready_state:x.readyState,duration_seconds:x.duration,paused:x.paused,error:x.error?.code??null,video_width:x.videoWidth,video_height:x.videoHeight}))}}))()'''

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--observation');parser.add_argument('--output',default='raw/qa/browser-qa.json');parser.add_argument('--print-browser-probe',action='store_true');parser.add_argument('--reuse-qa',help='Retain only currently bound individual checks from this prior QA report');args=parser.parse_args()
    if args.print_browser_probe:print(BROWSER_PROBE);return 0
    if not args.observation:parser.error('--observation is required unless printing the passive browser probe')
    root=args.root.resolve();output=(root/args.output).resolve()
    if not output.is_relative_to(root/'raw/qa'):raise ValueError('Browser QA output must be inside raw/qa')
    source=(root/args.observation).resolve()
    if not source.is_relative_to(root/'raw/qa'):raise ValueError('Save the actual browser observation under raw/qa')
    report=record_observation(root,json.loads(source.read_text()));report['observation_source']={'path':source.relative_to(root).as_posix(),'sha256':__import__('archive_state').sha_file(source)}
    for proof in report['proofs']:proof['observation_source']=report['observation_source']
    if args.reuse_qa:
        from qa_evidence import proof_key
        from audit_evidence import local_file
        from archive_state import sha_file
        prior=json.loads(local_file(root,args.reuse_qa).read_text());bindings=product_bindings(root);fresh_keys={proof_key(p) for p in report['proofs']}
        for proof in prior.get('proofs',[]):
            category=proof.get('category');binding=bindings['media'].get(proof.get('path'),{}).get('binding') if str(category).startswith('media:') else bindings.get(category)
            try:
                all_current=all(sha_file(local_file(root,a['path']))==a['sha256'] for a in proof.get('artifacts',[]))
                origin=proof['observation_source'];origin_current=sha_file(local_file(root,origin['path']))==origin['sha256']
            except (KeyError,ValueError,OSError):continue
            if proof_key(proof) not in fresh_keys and proof.get('binding')==binding and all_current and origin_current:report['proofs'].append(proof)
    atomic_json(output,report);print(json.dumps({'status':report['status'],'proofs':len(report['proofs']),'output':args.output}));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError) as error:raise SystemExit(str(error))
