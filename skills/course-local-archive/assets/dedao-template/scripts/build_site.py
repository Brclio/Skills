#!/usr/bin/env python3
"""Build a dependency-free, file:// compatible reader from local course sources."""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
VOID = {"br", "hr", "img", "source", "wbr", "col"}
ALLOWED = set("a abbr address article aside audio b bdi bdo blockquote br caption cite code col colgroup dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img kbd li main mark ol p pre q s samp section small source span strong sub summary sup table tbody td tfoot th thead time tr u ul video wbr".split())
BLOCKED = {"script", "style", "head", "iframe", "object", "embed", "form", "button", "input", "textarea", "select", "template", "svg", "math"}
ATTRS = {"alt", "title", "width", "height", "colspan", "rowspan", "scope", "datetime", "start", "reversed", "type", "controls", "preload", "loop", "muted", "playsinline", "poster", "src", "href", "id", "class", "style", "lang", "dir", "open", "data-dedao-link", "data-source-url", "data-link-resolution"}


def esc(value):
    return html.escape(str(value), quote=True)


class Sources:
    def __init__(self, root):
        self.root = root.resolve()
        self.issues = []
        self.lesson = ""

    def issue(self, kind, path):
        item = {"lesson_id": self.lesson, "kind": kind, "path": str(path)}
        if item not in self.issues:
            self.issues.append(item)

    def local_file(self, name):
        candidate = (self.root / name).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"Source path escapes the course directory: {name}")
        return candidate

    def url(self, value, base, media=False):
        value = html.unescape(value).strip()
        parts = urlsplit(value)
        if parts.scheme == "data":
            if media and re.match(r"^data:image/(png|jpe?g|gif|webp);base64,", value, re.I):
                return value
            self.issue("unsupported_data_url", value[:80])
            return None
        if parts.scheme in {"http", "https", "mailto", "tel"} or parts.netloc:
            if media:
                self.issue("remote_media", value)
                return None
            return value
        if parts.scheme:
            self.issue("unsafe_url", value)
            return None
        if value.startswith("#"):
            return "#source-" + parts.fragment
        candidate = (base / unquote(parts.path)).resolve()
        if not candidate.is_relative_to(self.root):
            self.issue("path_outside_course", value)
            return None
        if not candidate.is_file():
            self.issue("missing_file", str(candidate.relative_to(self.root)))
            return None
        path = quote(candidate.relative_to(self.root).as_posix(), safe="/")
        return path + ("#" + parts.fragment if parts.fragment else "")


class SafeHTML(HTMLParser):
    """Keep readable source markup, removing executable and network-loaded content."""
    def __init__(self, sources, base):
        super().__init__(convert_charrefs=False)
        self.sources = sources
        self.base = base
        self.out = []
        self.skip = []

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag not in VOID:
                self.skip.append(tag)
            return
        if tag in BLOCKED:
            self.skip.append(tag)
            return
        if tag == "font":
            # Older course markup uses <font color> for source highlights.
            # Normalize it without dropping its text or highlight color.
            values = dict(attrs)
            declarations = values.get("style", "") or ""
            color = values.get("color", "") or ""
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([\d\s.,%]+\)", color):
                declarations += ";color:" + color
            attrs = [(key, value) for key, value in attrs if key not in {"color", "style"}]
            if declarations:
                attrs.append(("style", declarations.lstrip(";")))
            tag = "span"
        if tag not in ALLOWED:
            return
        clean = []
        missing = False
        for key, value in attrs:
            if key not in ATTRS or value is None:
                continue
            if key in {"src", "poster", "href"}:
                value = self.sources.url(value, self.base, media=key != "href")
                if value is None:
                    missing = key != "href" or missing
                    continue
            if key == "style" and re.search(r"url\s*\(|expression\s*\(|@import|javascript:|behavior\s*:", value, re.I):
                continue
            if key == "id":
                value = "source-" + value
            clean.append(f'{key}="{esc(value)}"')
        if tag in {"audio", "video"}:
            clean.extend(['controls="controls"', 'preload="none"'])
            if tag == "video":
                clean.append('playsinline="playsinline"')
        if tag == "a":
            clean.append('rel="noopener noreferrer"')
        if missing:
            clean.append('data-offline-missing="true"')
        self.out.append("<" + tag + (" " + " ".join(clean) if clean else "") + ">")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self.skip:
                self.skip = self.skip[:len(self.skip) - 1 - self.skip[::-1].index(tag)]
            return
        if tag == "font":
            tag = "span"
        if tag in ALLOWED and tag not in VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, value):
        if not self.skip:
            self.out.append(esc(value))

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")


def sanitize(value, sources, base):
    parser = SafeHTML(sources, base)
    parser.feed(value)
    parser.close()
    return "".join(parser.out)


def inline(value):
    """Small Markdown inline renderer. Raw HTML remains available to preserve sources."""
    tokens = []

    def token(content):
        tokens.append(content)
        return f"\x00{len(tokens)-1}\x00"

    value = re.sub(r"`([^`]+)`", lambda m: token("<code>" + esc(m[1]) + "</code>"), value)
    value = re.sub(r"<[^>]+>", lambda m: token(m[0]), value)
    value = esc(value)
    value = re.sub(r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+&quot;([^\n]*?)&quot;)?\)", lambda m: token(f'<img src="{m[2]}" alt="{m[1]}"' + (f' title="{m[3]}"' if m[3] else "") + ">"), value)
    value = re.sub(r"\[([^\]]+)\]\(([^\s)]+)(?:\s+&quot;([^\n]*?)&quot;)?\)", lambda m: token(f'<a href="{m[2]}">{m[1]}</a>'), value)
    value = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: "<strong>" + (m[1] or m[2]) + "</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", value)
    value = re.sub(r"~~(.+?)~~", r"<del>\1</del>", value)
    # A token may contain other tokens, e.g. an image inside a link.
    for _ in range(3):
        value = re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m[1])], value)
    return value


def markdown(value):
    """Render common Markdown; original .md files are never modified."""
    lines = value.replace("\r\n", "\n").splitlines()
    if lines and lines[0] == "---":
        try:
            lines = lines[lines.index("---", 1) + 1:]
        except ValueError:
            pass
    out, paragraph, listing = [], [], None
    i = 0

    def flush():
        if paragraph:
            out.append("<p>" + "<br>".join(inline(s) for s in paragraph) + "</p>")
            paragraph.clear()

    def close_list():
        nonlocal listing
        if listing:
            out.append(f"</{listing}>")
            listing = None

    while i < len(lines):
        line = lines[i]
        if line.startswith(("```", "~~~")):
            flush(); close_list()
            fence = line[:3]
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith(fence):
                code.append(lines[i]); i += 1
            out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
        elif not line.strip():
            flush(); close_list()
        elif re.match(r"^#{1,6}\s", line):
            flush(); close_list()
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{level}>" + inline(line[level:].strip()) + f"</h{level}>")
        elif re.match(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$", line):
            flush(); close_list(); out.append("<hr>")
        elif line.lstrip().startswith(">"):
            flush(); close_list()
            quoted = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quoted.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append("<blockquote>" + markdown("\n".join(quoted)) + "</blockquote>")
            continue
        elif re.match(r"^\s*(?:[-+*]|\d+\.)\s+", line):
            flush()
            match = re.match(r"^\s*([-+*]|\d+\.)\s+(.*)", line)
            kind = "ol" if match[1][0].isdigit() else "ul"
            if kind != listing:
                close_list(); listing = kind
                start = f' start="{match[1][:-1]}"' if kind == "ol" else ""
                out.append(f"<{kind}{start}>")
            out.append("<li>" + inline(match[2]) + "</li>")
        elif "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i+1]):
            flush(); close_list()
            cells = lambda s: [inline(x.strip()) for x in s.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join("<th>" + c + "</th>" for c in cells(line)) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                out.append("<tr>" + "".join("<td>" + c + "</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        elif line.lstrip().startswith("<"):
            flush(); close_list(); out.append(line)
        else:
            close_list(); paragraph.append(line)
        i += 1
    flush(); close_list()
    return "\n".join(out)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, value):
        self.parts.append(value)


def build(root, manifest, output):
    root = root.resolve()
    course = json.loads(manifest.read_text(encoding="utf-8"))
    sources = Sources(root)
    lessons = []
    ids = set()
    for index, original in enumerate(course.get("lessons", [])):
        lesson = dict(original)
        lesson["id"] = str(lesson.get("id", index + 1))
        if lesson["id"] in ids:
            raise ValueError(f"Duplicate lesson ID: {lesson['id']}")
        ids.add(lesson["id"])
        sources.lesson = lesson["id"]
        lesson["title"] = str(lesson.get("title", f"第 {index+1} 讲"))
        lesson["html"] = ""
        source_exists = False
        for key in ("html_path", "markdown_path"):
            if not lesson.get(key):
                continue
            source = sources.local_file(lesson[key])
            if not source.is_file():
                sources.issue("missing_source", lesson[key]); continue
            raw = source.read_text(encoding="utf-8")
            if raw.strip():
                lesson["html"] = sanitize(raw if key == "html_path" else markdown(raw), sources, source.parent)
                source_exists = True
                break
        lesson["imported"] = source_exists
        lesson["status"] = str(lesson.get("status", "imported" if source_exists else "pending"))
        text_parser = PlainText(); text_parser.feed(lesson["html"])
        lesson["text"] = " ".join(text_parser.parts)
        for media_kind, default_label in (("audio", "课程音频"), ("video", "课程视频"), ("video_web_alternatives", "网页源 MP4")):
            media_items = lesson.get(media_kind, []) or []
            if isinstance(media_items, (str, dict)):
                media_items = [media_items]
            lesson[media_kind] = []
            for track in media_items:
                track = {"path": track} if isinstance(track, str) else dict(track)
                path = sources.url(track.get("path") or track.get("url") or "", root, media=True)
                if path:
                    saved = {"path": path, "label": str(track.get("label", default_label))}
                    for metadata_key in ("duration", "resolution", "bytes", "sha256", "archive_report", "decryption_status"):
                        if metadata_key in track:
                            saved[metadata_key] = track[metadata_key]
                    if media_kind in {"video", "video_web_alternatives"} and track.get("poster"):
                        poster = sources.url(track["poster"], root, media=True)
                        if poster:
                            saved["poster"] = poster
                    lesson[media_kind].append(saved)
        for key in ("markdown_path", "html_path"):
            if lesson.get(key):
                source = sources.local_file(lesson[key])
                lesson[key] = quote(source.relative_to(root).as_posix(), safe="/") if source.is_file() else None
        lessons.append(lesson)
    sources.lesson = ""
    cover = sources.url(course["cover_path"], root, media=True) if course.get("cover_path") else None
    data = {"title": course.get("title", "本地课程库"), "source_url": course.get("source_url", ""), "description": course.get("description", ""), "cover_path": cover, "lessons": lessons, "issues": sources.issues}
    data["summary"] = {"total": len(lessons), "imported": sum(x["imported"] for x in lessons), "audio": sum(len(x["audio"]) for x in lessons), "video": sum(len(x["video"]) for x in lessons), "issues": len(sources.issues)}
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (root / "web/template.html").read_text(encoding="utf-8")
    output.write_text(template.replace("__COURSE_TITLE__", esc(data["title"])).replace("__COURSE_DATA__", payload), encoding="utf-8")
    report = {"summary": data["summary"], "issues": sources.issues}
    (root / "web/build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **report}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="course.json", help="Course manifest, relative to project root")
    parser.add_argument("--output", default="index.html", help="Reader filename in project root")
    args = parser.parse_args()
    root = ROOT.resolve()
    if Path(args.output).parent != Path("."):
        parser.error("--output must be a filename in the project root so media paths remain valid")
    manifest = (root / args.manifest).resolve()
    if not manifest.is_relative_to(root):
        parser.error("--manifest must be inside the project root")
    build(root, manifest, root / args.output)


if __name__ == "__main__":
    main()
