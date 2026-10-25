#!/usr/bin/env python3
"""Build an offline resource index and its Markdown companion."""
import json
from pathlib import Path
from urllib.parse import quote
from build_site import ROOT, esc


def main():
    course = json.loads((ROOT / 'course.json').read_text())
    attachments_path = ROOT / 'assets/attachments/manifest.json'
    attachments = json.loads(attachments_path.read_text()) if attachments_path.exists() else []
    if isinstance(attachments, dict):
        attachments = attachments.get('attachments', attachments.get('files', []))
    rows, md = [], ['# 本地资源目录', '', course['title'], '', '[返回课程目录](../index.html)', '', '## 课程文稿、视频与音频', '']
    decrypted_count = sum(item.get('path', '').startswith('assets/video/decrypted/') for lesson in course['lessons'] for item in lesson.get('video', []))
    web_count = sum(len({item['path'] for field in ['video', 'video_web_alternatives'] for item in lesson.get(field, []) if not item['path'].startswith('assets/video/decrypted/')}) for lesson in course['lessons'])
    encrypted_count = sum(len(lesson.get('video_encrypted_original', [])) for lesson in course['lessons'])
    video_note = ''
    if decrypted_count:
        note = f'已保存 {decrypted_count} 段解密原件 MP4，阅读器默认播放这些文件；另保留 {web_count} 段网页源 MP4 和 {encrypted_count} 份加密原件备份，可分别下载。'
        md.extend([note, ''])
        video_note = '<p>' + esc(note) + '</p>'
    def video_downloads(lesson):
        result, seen = [], set()
        for field in ['video', 'video_web_alternatives', 'video_encrypted_original']:
            for track in lesson.get(field, []):
                if track['path'] in seen:
                    continue
                seen.add(track['path'])
                label = '加密原件备份' if field == 'video_encrypted_original' else '解密原件 MP4' if track['path'].startswith('assets/video/decrypted/') else '网页源 MP4'
                if track.get('resolution'):
                    label += ' · ' + str(track['resolution']) + 'p'
                result.append({**track, 'label': label})
        return result
    def links(items, label):
        return '<br>'.join(f'<a href="{quote(x["path"], safe="/")}" download>{esc(x.get("label") or label)} ↓</a>' for x in items)
    for n, lesson in enumerate(course['lessons'], 1):
        doc = lesson.get('markdown_path')
        video, audio = video_downloads(lesson), lesson.get('audio', [])
        rows.append('<tr><td>' + str(n) + '</td><th scope="row"><a href="index.html#lesson=' + quote(lesson['id']) + '">' + esc(lesson['title']) + '</a></th><td>' + (f'<a href="{quote(doc, safe="/")}" download>Markdown ↓</a>' if doc else '未保存') + '</td><td>' + (links(video, '课程视频') or '本讲无视频') + '</td><td>' + (links(audio, '课程音频') or '本讲无音频') + '</td></tr>')
        md.extend(['### ' + str(n) + '. ' + lesson['title'], ''])
        if doc:
            md.append('- [Markdown](../' + doc + ')')
        for item in video:
            md.append('- [' + item['label'] + '](../' + quote(item['path'], safe='/') + ')')
        for item in audio:
            md.append('- [' + (item.get('label') or '音频') + '](../' + quote(item['path'], safe='/') + ')')
        md.append('')
    reference_rows = []
    md.extend(['## 原文参考资料', '', '以下是课程脚注所引用的外部 PDF。不可访问的旧链接保留来源与状态。', ''])
    for item in attachments:
        title = item.get('title') or (item.get('source_url') or item.get('url') or '参考资料').rsplit('/', 1)[-1]
        path = item.get('path')
        source = item.get('source_url') or item.get('url') or ''
        saved = bool(path and (ROOT / path).is_file())
        state = '已保存到本地' if saved else '原始旧链接当前不可访问'
        link = f'<a href="{quote(path, safe="/")}" download>下载 PDF ↓</a>' if saved else esc(state)
        reference_rows.append('<tr><th scope="row">' + esc(title) + '</th><td>' + link + '</td><td>' + (f'<a href="{esc(source)}" target="_blank" rel="noopener noreferrer">原始引用 ↗</a>' if source else '') + '</td></tr>')
        md.append('- ' + ('[' + title + '](../' + path + ')' if saved else title + '：' + state) + ('；[原始引用](' + source + ')' if source else ''))
    report_links=[]
    def add_report(label,*candidates):
        path=next((value for value in candidates if (ROOT/value).is_file()),None)
        if path:report_links.append((label,path))
    add_report('完整性核验','raw/archive-audit.json')
    add_report('音频核验','raw/audio-verification-summary.json','raw/audio-archive/manifest.json')
    add_report('网页源视频核验','raw/web-video-archive-report.json')
    add_report('加密原件保存记录','raw/video-archive-report.json')
    add_report('解密原件核验','raw/legacy-video-decryption-report.json')
    add_report('独立解密复核','raw/independent-legacy-decryption-review.json')
    add_report('原件与结果哈希复查','raw/decrypted-video-apply-report.json')
    add_report('解密结果说明','DECRYPTION_STATUS.md')
    if report_links:
        md.extend(['','## 核验记录',''])
        md.extend('- ['+label+'](../'+quote(path,safe='/')+')' for label,path in report_links)
    md.append('')
    (ROOT / 'content/本地资源.md').write_text('\n'.join(md))
    head = (ROOT / 'web/template.html').read_text().split('<body>', 1)[0].replace('__COURSE_TITLE__', '本地资源 · ' + esc(course['title']))
    page = head + '''<body><header class="app-header"><div class="header-brand"><span class="brand-mark" aria-hidden="true">读</span><h1>本地资源</h1></div><nav class="header-actions"><a class="button" href="index.html">返回课程目录</a></nav></header><main class="resources-main article-body"><p class="eyebrow">OFFLINE COURSE LIBRARY</p><h1>文稿、视频与音频</h1><p>所有下载链接指向当前文件夹中的本地文件。移动或备份时，请完整保留文件夹结构。</p>''' + video_note + '''<div class="resources-table"><table><thead><tr><th>讲次</th><th>课程标题</th><th>文稿</th><th>视频</th><th>音频</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div><h2>原文参考资料</h2><p>课程脚注引用的外部 PDF；旧链接的可访问性不影响已保存课程的阅读和播放。</p><div class="resources-table"><table><thead><tr><th>资料</th><th>本地文件</th><th>来源</th></tr></thead><tbody>''' + ''.join(reference_rows) + '''</tbody></table></div><footer class="reader-footer"><a href="content/%E6%9C%AC%E5%9C%B0%E8%B5%84%E6%BA%90.md" download>下载资源目录 Markdown</a><a href="index.html">课程目录</a><span>阅读样式：Brclio Design System</span></footer></main></body></html>'''
    if report_links:
        report_section='<h2>核验记录</h2><ul>'+''.join('<li><a href="'+quote(path,safe='/')+'">'+esc(label)+'</a></li>' for label,path in report_links)+'</ul>'
        page=page.replace('<footer class="reader-footer">',report_section+'<footer class="reader-footer">')
    page = page.replace('</head>', '<style>.resources-main{max-width:1400px;margin:auto;padding:40px clamp(20px,5vw,64px)}.resources-table{overflow-x:auto}.resources-table table{min-width:720px}.resources-table td,.resources-table th{font-size:14px}.resources-table th[scope="row"]{font-weight:500;min-width:240px}.resources-table td a{white-space:nowrap}.resources-main .reader-footer{flex-wrap:wrap}</style></head>')
    (ROOT / 'resources.html').write_text(page)
    print(json.dumps({'lessons':len(rows),'reference_documents':len(reference_rows),'decrypted_video_downloads':decrypted_count,'web_video_downloads':web_count,'encrypted_original_downloads':encrypted_count,'existing_verification_reports':len(report_links),'output':'resources.html'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
