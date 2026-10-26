#!/usr/bin/env python3
"""Build a local download index for every preserved media role."""
import json
from urllib.parse import quote
from build_site import ROOT, Sources, esc, versioned_template
from media_inventory import digest

VIDEO_LABELS = {'video_decrypted_original':'解密原件 MP4','video_plaintext_original':'明文原件 MP4','video_web_alternatives':'网页源 MP4','video_encrypted_original':'加密原件备份','video':'默认播放视频'}

def items(value):
    return [value] if isinstance(value,dict) else value or []

def video_downloads(lesson):
    result, seen = [], set()
    for field,label in VIDEO_LABELS.items():
        for track in items(lesson.get(field)):
            if track.get('path') in seen:continue
            seen.add(track.get('path'))
            if field=='video' and '/decrypted/' in track.get('path',''):label='解密原件 MP4'
            result.append({**track,'label':label + (' · '+str(track['resolution'])+'p' if track.get('resolution') else '')})
    return result

def audio_downloads(lesson):
    result=[]
    for track in items(lesson.get('audio'))+items(lesson.get('video_audio_components')):
        result.append(track)
        if track.get('encrypted_source'):result.append({**track['encrypted_source'],'label':'源音频备份（不可直接播放）'})
    return result

def main():
    root=ROOT.resolve();course=json.loads((root/'course.json').read_text(encoding='utf-8'));sources=Sources(root)
    attachments_path=root/'assets/attachments/manifest.json';attachments=json.loads(attachments_path.read_text()) if attachments_path.is_file() else []
    if isinstance(attachments,dict):attachments=attachments.get('attachments',attachments.get('files',[]))
    md=['# 本地资源目录','',course['title'],'','[返回课程目录](../index.html)','','## 课程文稿、视频、音频与字幕',''];rows=[];counts={'video':0,'audio':0,'subtitle':0}
    def links(tracks,label):
        result=[];seen=set()
        for track in items(tracks):
            if not track.get('path') or track['path'] in seen:continue
            seen.add(track['path']);url=sources.url(track['path'],root,media=True)
            if not url:continue
            name=track.get('label') or label
            result.append(f'<a href="{url}" download>{esc(name)} ↓</a>')
            md.append('- ['+name+'](../'+url+')')
        return '<br>'.join(result)
    intro=items(course.get('course_intro_video'))+items(course.get('course_intro_audio'))+items(course.get('course_intro_subtitles'))
    for track in items(course.get('course_intro_audio')):
        if track.get('encrypted_source'):intro.append({**track['encrypted_source'],'label':'介绍音频源备份（不可直接播放）'})
    intro_html=''
    if intro:
        md.extend(['## 课程介绍素材','']);intro_html='<h2>课程介绍素材</h2><p>'+links(intro,'课程介绍素材')+'</p>';md.extend(['','## 逐讲资源',''])
    for n,lesson in enumerate(course.get('lessons',[]),1):
        sources.lesson=str(lesson['id']);md.extend(['### '+str(n)+'. '+lesson['title'],''])
        documents=[{'path':lesson[key],'label':label} for key,label in [('markdown_path','Markdown'),('html_path','保存的正文 HTML')] if lesson.get(key)]
        video=video_downloads(lesson);audio=audio_downloads(lesson);subtitles=items(lesson.get('subtitles'))
        counts['video']+=len(video);counts['audio']+=len(audio);counts['subtitle']+=len(subtitles)
        cells=[links(documents,'文稿') or '未保存',links(video,'课程视频') or '本讲无视频',links(audio,'课程音频') or '本讲无音频',links(subtitles,'字幕') or '来源未提供字幕']
        rows.append('<tr><td>'+str(n)+'</td><th scope="row"><a href="index.html#lesson='+quote(str(lesson['id']))+'">'+esc(lesson['title'])+'</a></th>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>');md.append('')
    sources.lesson='';reference_rows=[];md.extend(['## 原文附件与参考资料','','仅列入来源明确提供或文稿引用的附件；原始引用链接保留其来源。',''])
    for item in attachments:
        title=item.get('title') or item.get('label') or (item.get('source_url') or item.get('url') or '参考资料').rsplit('/',1)[-1]
        source=item.get('source_url') or item.get('url') or '';path=item.get('path');local=links([{'path':path,'label':title}],'来源附件') if path else ''
        state='来源链接当前不可访问' if not local else ''
        reference_rows.append('<tr><th scope="row">'+esc(title)+'</th><td>'+(local or state)+'</td><td>'+(f'<a href="{esc(source)}" target="_blank" rel="noopener noreferrer">原始引用 ↗</a>' if source else '')+'</td></tr>')
        if not local:md.append('- '+title+'：'+state)
    report_links=[]
    for label,candidates in [('完整性核验',['raw/archive-audit.json']),('资源预期与本地覆盖',['raw/media-inventory-audit.json']),('课程介绍与字幕核验',['raw/course-extras-report.json']),('音频核验',['raw/audio-verification-summary.json','raw/audio-archive/manifest.json']),('网页源视频核验',['raw/web-video-archive-report.json']),('来源视频原件保存记录',['raw/video-archive-report.json']),('解密原件核验',['raw/legacy-video-decryption-report.json']),('独立解密复核',['raw/independent-legacy-decryption-review.json']),('原件与结果哈希复查',['raw/decrypted-video-apply-report.json']),('解密结果说明',['DECRYPTION_STATUS.md'])]:
        path=next((p for p in candidates if (root/p).is_file()),None)
        if path:report_links.append((label,path))
    reports=''
    if report_links:
        md.extend(['','## 核验记录','']);md.extend('- ['+label+'](../'+quote(path,safe='/')+')' for label,path in report_links)
        reports='<h2>核验记录</h2><ul>'+''.join('<li><a href="'+quote(path,safe='/')+'">'+esc(label)+'</a></li>' for label,path in report_links)+'</ul>'
    md.append('');(root/'content').mkdir(exist_ok=True);(root/'content/本地资源.md').write_text('\n'.join(md),encoding='utf-8')
    template,versions=versioned_template(root);head=template.split('<body>',1)[0].replace('__COURSE_TITLE__','本地资源 · '+esc(course['title']))
    head=head.replace('</head>','<style>.resources-main{max-width:1400px;margin:auto;padding:40px clamp(20px,5vw,64px)}.resources-table{overflow-x:auto}.resources-table table{min-width:800px}.resources-table td,.resources-table th{font-size:14px}.resources-table th[scope="row"]{font-weight:500;min-width:240px}.resources-table td a{white-space:nowrap}.resources-main .reader-footer{flex-wrap:wrap}</style></head>')
    page=head+'''<body><header class="app-header"><div class="header-brand"><span class="brand-mark" aria-hidden="true">读</span><h1>本地资源</h1></div><nav class="header-actions"><a class="button" href="course-info.html">课程介绍</a><a class="button" href="index.html">返回课程目录</a></nav></header><main class="resources-main article-body"><p class="eyebrow">OFFLINE COURSE LIBRARY</p><h1>文稿、视频、音频与字幕</h1><p>所有下载链接指向当前课程文件夹。默认播放文件、网页源与原件分别保留，下载标签说明其用途。</p>'''+intro_html+'''<div class="resources-table"><table><thead><tr><th>讲次</th><th>课程标题</th><th>文稿</th><th>视频</th><th>音频</th><th>字幕</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table></div><h2>原文附件与参考资料</h2><div class="resources-table"><table><thead><tr><th>资料</th><th>本地文件</th><th>来源</th></tr></thead><tbody>'''+''.join(reference_rows)+'''</tbody></table></div>'''+reports+'''<footer class="reader-footer"><a href="content/%E6%9C%AC%E5%9C%B0%E8%B5%84%E6%BA%90.md" download>下载资源目录 Markdown</a><a href="index.html">课程目录</a></footer></main></body></html>'''
    destination=root/'resources.html';destination.write_text(page,encoding='utf-8');report={'status':'passed' if not sources.issues else 'failed','lessons':len(rows),'reference_documents':len(reference_rows),'download_counts':counts,'asset_versions':versions,'source_manifest_sha256':digest(root/'course.json'),'output_sha256':digest(destination),'issues':sources.issues}
    (root/'web/resources-build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False));return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
