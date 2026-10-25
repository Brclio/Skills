#!/usr/bin/env python3
"""Inventory source attachments/captions and download only explicitly cited PDFs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
URL=re.compile(r'https?://[^\s<>"\u0027，。；、（）【】“”]+')

def urls(text):
    return [m.group(0).rstrip('.,;:)') for m in URL.finditer(text)]

def source_text(value):
    if isinstance(value,list):
        for child in value:yield from source_text(child)
    elif isinstance(value,dict):
        if value.get('type')=='text':
            field=value.get('text',{})
            yield field if isinstance(field,str) else str(field.get('content',''))
        else:
            for key,child in value.items():
                if key!='text':yield from source_text(child)

def download(row):
    row=dict(row); url=row['source_url'];dest=ROOT/'assets/attachments'
    filename=hashlib.sha256(url.encode()).hexdigest()[:16]+'.pdf'; path=dest/filename
    errors=[]
    for candidate in dict.fromkeys([url,url.replace('http://','https://',1)]):
        try:
            with urlopen(Request(candidate,headers={'User-Agent':'Mozilla/5.0'}),timeout=30) as response:
                data=response.read(100*1024*1024+1)
                if len(data)>100*1024*1024:raise ValueError('PDF exceeds 100 MiB')
                if not data.startswith(b'%PDF-'):raise ValueError('Source returned a non-PDF response')
                row['resolved_url']=response.url
            path.write_bytes(data)
            row.update(status='complete',path=path.relative_to(ROOT).as_posix(),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            return row
        except Exception as e:
            errors.append({'requested_url':candidate,'error':str(e)[:250]})
    row.update(status='unavailable',attempts=errors)
    return row

def main():
    archive=json.loads((ROOT/'raw/authorized-course.json').read_text())
    refs={};videos=[];fields=[];platform_attachments=[]
    for lesson in archive['lessons']:
        lid=str(lesson['id']); info=lesson['info'];article=info['article_info']
        for text in source_text(json.loads(lesson['body']['content'])):
            for url in urls(text):
                entry=refs.setdefault(url,{'source_url':url,'lesson_ids':[],'role':'external_source_citation'})
                if lid not in entry['lesson_ids']:entry['lesson_ids'].append(lid)
        for video in article.get('video',[]):
            videos.append({'lesson_id':lid,'video_id':str(video.get('dd_media_id_str') or video.get('dd_media_id','')),'caption_supplied':bool(video.get('caption')),'vtt_caption_supplied':bool(video.get('vtt_caption')),'separate_video_audio_supplied':bool(video.get('video_audio')),'media_files_supplied':bool(video.get('media_files'))})
        for key in ('extra','document_url','attachment','attachments','download_url','subtitle_url','caption_url'):
            value=info.get(key)
            if value:platform_attachments.append({'lesson_id':lid,'field':key,'value':value})
    for key in ('document_url','document_text','document_tips'):
        value=archive['course'].get(key)
        fields.append({'field':key,'supplied':bool(value)})
        if value:platform_attachments.append({'field':'course.'+key,'value':value})
    directory=ROOT/'assets/attachments';directory.mkdir(parents=True,exist_ok=True)
    candidates=[{**row,'role':'optional_external_reference_pdf'} for url,row in refs.items() if urlsplit(url).path.lower().endswith('.pdf')]
    with ThreadPoolExecutor(max_workers=3) as pool:attachments=list(pool.map(download,candidates))
    manifest={'schema_version':1,'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Only PDF URLs explicitly cited in source prose; external websites are not mirrored. These are reference documents, not additional course lessons.','attachments':attachments}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    report={'schema_version':1,'checked_at_utc':manifest['checked_at_utc'],'course_document_fields':fields,'platform_attachments':platform_attachments,'videos':videos,'external_citations':list(refs.values()),'reference_pdf_manifest':'assets/attachments/manifest.json','summary':{'lessons':len(archive['lessons']),'platform_attachments':len(platform_attachments),'video_metadata_entries':len(videos),'separate_caption_files':sum(row['caption_supplied'] or row['vtt_caption_supplied'] for row in videos),'external_citation_urls':len(refs),'reference_pdf_urls':len(candidates),'reference_pdfs_downloaded':sum(row['status']=='complete' for row in attachments)}}
    (ROOT/'raw/resource-inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 原文参考资料','',manifest['scope'],'','这些文件来自案例脚注中的外部 PDF 直链；原文引用保持原样。不可访问的旧链接记录在清单中。','']
    for row in attachments:
        lines.append('- ['+(Path(urlsplit(row['source_url']).path).name or 'PDF')+']('+row.get('path',row['source_url']).replace('assets/attachments/','')+') — '+('已保存，SHA-256 '+row['sha256'] if row['status']=='complete' else '原站旧链接当前不可访问'))
    (directory/'README.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False))

if __name__=='__main__':main()
