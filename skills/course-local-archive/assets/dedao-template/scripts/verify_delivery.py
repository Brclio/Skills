#!/usr/bin/env python3
"""Gate complete delivery on current local audit, source inventory and actual UI QA.

Only writes post-final raw/delivery/status.json. It never rewrites course.json,
so recording delivery cannot invalidate the verified reader or its UI evidence.
"""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
from archive_state import atomic_json, sha_file
from audit_evidence import local_file, verify_bound_audit
from media_inventory import load_inventory, verify_inventory
from qa_evidence import verify_qa

ROOT=Path(__file__).resolve().parents[1]

def verify_delivery(root,audit_path='raw/archive-audit.json',qa_path='raw/qa/browser-qa.json'):
    root=Path(root).resolve();errors=[];result={'schema_version':2,'evidence_role':'delivery_status','checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'incomplete','errors':errors}
    for role,value in [('local_audit',audit_path),('browser_qa',qa_path)]:
        try:
            path=local_file(root,value);report=json.loads(path.read_text());result[role]={'path':value,'sha256':sha_file(path)}
            if role=='local_audit':
                verify_bound_audit(root,report)
                inventory=verify_inventory(root,load_inventory(root))
                if inventory.get('status')!='passed':raise ValueError('Current source-driven expected resource inventory is incomplete')
                result['inventory']={key:inventory[key] for key in ('status','expected_resources','verified_resources')}
            else:result['browser_checks']=verify_qa(root,report)
        except (ValueError,KeyError,OSError) as error:errors.append({'stage':role,'error':str(error)})
    if not errors:result['status']='fully_delivered'
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--audit',default='raw/archive-audit.json');parser.add_argument('--qa',default='raw/qa/browser-qa.json');parser.add_argument('--output',default='raw/delivery/status.json');args=parser.parse_args()
    root=args.root.resolve();output=(root/args.output).resolve()
    if not output.is_relative_to(root/'raw/delivery'):raise ValueError('Delivery status must live under raw/delivery')
    report=verify_delivery(root,args.audit,args.qa);atomic_json(output,report);print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='fully_delivered' else 1

if __name__=='__main__':raise SystemExit(main())
