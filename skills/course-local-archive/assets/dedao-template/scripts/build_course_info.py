#!/usr/bin/env python3
"""Render content/课程信息.md into a local, dependency-free course information page."""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import unquote, urlsplit

from build_site import ROOT, Sources, esc, markdown, sanitize


class ResourceHTML(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.resources = []
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"img", "audio", "video", "source", "script"} and attrs.get("src"):
            self.resources.append(attrs["src"])
        if tag == "video" and attrs.get("poster"):
            self.resources.append(attrs["poster"])
        if tag == "link" and attrs.get("href"):
            self.resources.append(attrs["href"])


def main():
    source = ROOT / "content/课程信息.md"
    if not source.is_file():
        raise SystemExit("Missing course information Markdown: content/课程信息.md")
    course = json.loads((ROOT / "course.json").read_text(encoding="utf-8"))
    destination = ROOT / "course-info.html"
    sources = Sources(ROOT)
    sources.lesson = "course-information"
    body = sanitize(markdown(source.read_text(encoding="utf-8")), sources, source.parent)
    template = (ROOT / "web/template.html").read_text(encoding="utf-8")
    head = template.split("<body>", 1)[0]
    head = head.replace("__COURSE_TITLE__", esc("课程信息 · " + course.get("title", "本地课程库")))
    head = head.replace("</head>", """  <style>
    .course-info-main{margin:0 auto;max-width:1060px;padding:28px clamp(20px,5vw,80px) 50px}
    .course-info-main .article-body{font-size:17px}
    .course-info-main .article-body h1{margin-top:0}
    .course-info-main .article-body img{max-height:100vh;object-fit:contain}
    .course-info-main .reader-footer{font-size:11px;flex-wrap:wrap}
    @media(max-width:600px){.course-info-main .article-body{font-size:16px}}
    </style>
</head>""")
    page = head + """<body>
  <a class="skip-link" href="#course-information">跳到正文</a>
  <header class="app-header">
    <div class="header-brand"><span class="brand-mark" aria-hidden="true">读</span><h1>课程信息</h1></div>
    <nav class="header-actions" aria-label="课程导航"><a class="button" href="resources.html">本地资源</a><a class="button" href="index.html">返回课程目录</a></nav>
  </header>
  <main class="course-info-main" id="course-information" tabindex="-1">
    <article class="article-body">
""" + body + """
    </article>
    <footer class="reader-footer"><a href="content/%E8%AF%BE%E7%A8%8B%E4%BF%A1%E6%81%AF.md" download>下载 Markdown</a><span>阅读样式：<a href="https://github.com/Brclio/brclio-design-system">Brclio Design System</a></span><a href="index.html">课程目录</a></footer>
  </main>
</body>
</html>
"""
    destination.write_text(page, encoding="utf-8")
    checks = []
    for value in ResourceHTML(page).resources:
        parts = urlsplit(value)
        if parts.scheme == "data":
            checks.append({"path": "data:image", "local": True, "exists": True})
            continue
        path = (ROOT / unquote(parts.path)).resolve()
        checks.append({"path": value, "local": not parts.scheme and not parts.netloc, "exists": path.is_file() and path.is_relative_to(ROOT)})
    report = {
        "source": str(source.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "output": str(destination.relative_to(ROOT)),
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "issues": sources.issues,
        "resources": checks,
        "status": "passed" if not sources.issues and all(r["local"] and r["exists"] for r in checks) else "failed",
    }
    (ROOT / "web/course-info-build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
