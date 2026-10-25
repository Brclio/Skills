#!/usr/bin/env python3
"""Import authorized .editor-show UI captures without rewriting their text.

Run repeatedly while captures are collected: python3 scripts/import_ui.py
Only lessons whose source URL matches course.json are imported. The original
HTML and capture JSON remain available separately from the local reading copy.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit

from export_public import Images, ROOT, write_json

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
BLOCKS = {"div", "p", "blockquote", "figure", "figcaption", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
SAFE = {"a", "abbr", "article", "aside", "audio", "b", "blockquote", "br", "caption", "cite", "code", "dd", "del", "details", "div", "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "kbd", "li", "main", "mark", "ol", "p", "pre", "s", "section", "small", "source", "span", "strong", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time", "tr", "u", "ul", "video"}
BLOCKED = {"script", "style", "head", "iframe", "object", "embed", "form", "input", "textarea", "select", "svg", "math", "template"}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class Tree(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(value)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def all_text(node):
    if isinstance(node, str):
        return node
    if node.tag in {"br", "hr"}:
        return "\n"
    text = "".join(all_text(child) for child in node.children)
    return text + ("\n" if node.tag in BLOCKS else "")


def canonical_text(value):
    return re.sub(r"\s+", "", html.unescape(value))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def clean(node, images, lesson_id, stats):
    if isinstance(node, str):
        return node
    style = node.attrs.get("style", "")
    classes = node.attrs.get("class", "").split()
    hidden = re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)(?:\s*;|\s*$)", style, re.I)
    editor_controls = any(name == "em-menu" or name.startswith("em-menu-") for name in classes)
    if node.tag in BLOCKED or hidden or editor_controls:
        stats["removed_ui_nodes"] += 1
        return None
    if node.tag == "font":
        node.tag = "span"
        stats["font_to_span"] += 1
    if node.tag == "button":
        # A media-control icon has no source prose. Keep any unexpected text.
        node.tag = "span"
    attrs = {}
    for name in ("alt", "title", "width", "height", "colspan", "rowspan", "start", "reversed", "controls", "preload", "class"):
        if node.attrs.get(name) is not None:
            attrs[name] = node.attrs[name]
    # Keep source typography and alignment, discarding editor overlay positioning.
    safe_styles = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        key, value = map(str.strip, declaration.split(":", 1))
        if key.lower() in {"color", "background-color", "font-size", "font-family", "font-weight", "font-style", "text-align", "white-space", "line-height", "text-decoration"} and not re.search(r"url\s*\(|expression\s*\(|javascript:", value, re.I):
            safe_styles.append(key + ": " + value)
    if safe_styles:
        attrs["style"] = "; ".join(safe_styles)
    if node.tag == "img":
        source = node.attrs.get("src", "")
        if not source:
            raise ValueError("Source image lacks a src attribute")
        local = images.save(source, "lesson-" + lesson_id)
        attrs["src"] = "../" + local
        stats["images"].append({"source_url": source, "path": local})
    if node.tag == "a":
        href = node.attrs.get("href", "")
        if href.startswith(("https://", "http://", "mailto:", "#")):
            attrs["href"] = href
    node.attrs = attrs
    node.children = [result for child in node.children if (result := clean(child, images, lesson_id, stats)) is not None]
    return node


def html_node(node):
    if isinstance(node, str):
        return html.escape(node)
    content = "".join(html_node(child) for child in node.children)
    if node.tag == "root" or node.tag not in SAFE:
        return content
    attrs = "".join(f' {name}="{html.escape(str(value), quote=True)}"' for name, value in node.attrs.items())
    start = "<" + node.tag + attrs + ">"
    return start if node.tag in VOID else start + content + "</" + node.tag + ">"


def markdown_node(node):
    if isinstance(node, str):
        return node
    content = "".join(markdown_node(child) for child in node.children)
    tag = node.tag
    if tag == "img":
        return f'![{node.attrs.get("alt", "")}]({node.attrs["src"]})'
    if tag == "br":
        return "<br>\n"
    if tag == "hr" or "split" in node.attrs.get("class", "").split():
        return "\n\n---\n\n"
    if tag in {"b", "strong"}:
        return "**" + content + "**"
    if tag in {"em", "i"}:
        return "*" + content + "*"
    if tag == "a" and node.attrs.get("href"):
        return f'[{content}]({node.attrs["href"]})'
    if tag == "span" and node.attrs.get("style"):
        return f'<span style="{html.escape(node.attrs["style"], quote=True)}">{content}</span>'
    if tag == "blockquote":
        return "\n\n" + "\n".join("> " + line for line in content.strip().splitlines()) + "\n\n"
    if re.fullmatch(r"h[1-6]", tag):
        return "\n\n" + "#" * int(tag[1]) + " " + content.strip() + "\n\n"
    if tag == "li":
        return "\n- " + content.strip()
    if tag in {"ul", "ol"}:
        return "\n" + content + "\n\n"
    if tag in {"table", "pre"}:
        return "\n\n" + html_node(node) + "\n\n"
    if tag == "p" and "text-align: center" in node.attrs.get("style", ""):
        return '\n\n<p style="text-align: center">' + content + "</p>\n\n"
    if tag in BLOCKS:
        return "\n\n" + content.strip() + "\n\n"
    return content


def source_identity(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.dedao.cn" or parsed.path != "/course/article":
        raise ValueError(f"Unexpected capture source: {url}")
    enid = parse_qs(parsed.query).get("id", [])
    if len(enid) != 1:
        raise ValueError("Capture source URL has no unique course article ID")
    return enid[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="*", type=Path, help="Specific capture JSONs; defaults to raw/ui/*.json")
    args = parser.parse_args()
    paths = args.captures or sorted((ROOT / "raw/ui").glob("*.json"))
    manifest_path = ROOT / "course.json"
    course = json.loads(manifest_path.read_text())
    by_enid = {lesson["enid"]: lesson for lesson in course["lessons"]}
    provenance_path = ROOT / "raw/import-manifest.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {"schema_version": 1, "lessons": {}}
    images = Images()
    updates, failures = {}, []
    for capture_path in paths:
        if not capture_path.is_absolute():
            capture_path = (ROOT / capture_path).resolve()
        try:
            capture_bytes = capture_path.read_bytes()
            capture = json.loads(capture_bytes)
            source_url = capture.get("source_url") or capture.get("url", "")
            enid = source_identity(source_url)
            lesson = by_enid.get(enid)
            if lesson is None:
                raise ValueError("Capture source is absent from the established source catalog")
            identifier = lesson["id"]
            if not capture.get("html", "").strip() or not capture.get("text", "").strip():
                raise ValueError("Capture must contain both .editor-show HTML and visible text")
            # Explicitly reject page-wide captures containing navigation or reviews.
            if re.search(r'class=["\'][^"\']*(?:course-list|article-comment-list|recommend-list)[^"\']*["\']', capture["html"]):
                raise ValueError("Capture contains page navigation, comments, or recommendations")
            raw_dir = ROOT / "raw/lessons"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_html_path = raw_dir / f"{identifier}.ui.html"
            raw_text_path = raw_dir / f"{identifier}.ui.txt"
            raw_html_path.write_text(capture["html"], encoding="utf-8")
            raw_text_path.write_text(capture["text"], encoding="utf-8")
            stats = {"removed_ui_nodes": 0, "font_to_span": 0, "images": []}
            tree = clean(Tree(capture["html"]).root, images, identifier, stats)
            source_text = canonical_text(capture["text"])
            imported_text = canonical_text(all_text(tree))
            if source_text != imported_text:
                raise ValueError(f"Visible prose mismatch: source {len(source_text)} chars, imported {len(imported_text)} chars")
            markup = html_node(tree)
            markdown = markdown_node(tree)
            markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"
            # The Markdown renderer must recover exactly the visible source prose.
            from build_site import markdown as render_markdown
            markdown_text = canonical_text(all_text(Tree(render_markdown(markdown)).root))
            if source_text != markdown_text:
                raise ValueError(f"Markdown prose mismatch: source {len(source_text)} chars, Markdown {len(markdown_text)} chars")
            stem = f'{lesson["order"]:04d}-{identifier}'
            content_dir = ROOT / "content"
            content_dir.mkdir(exist_ok=True)
            html_path = content_dir / (stem + ".html")
            markdown_path = content_dir / (stem + ".md")
            frontmatter = "---\n" + "\n".join([
                "title: " + json.dumps(lesson["title"], ensure_ascii=False),
                "source_url: " + json.dumps(source_url),
                "source_article_id: " + json.dumps(identifier),
                'body_status: "imported"',
                "audio_status: " + json.dumps(lesson.get("audio_status", "pending")),
                "raw_html_path: " + json.dumps("../" + raw_html_path.relative_to(ROOT).as_posix()),
            ]) + "\n---\n\n"
            html_path.write_text(markup + "\n", encoding="utf-8")
            markdown_path.write_text(frontmatter + "# " + lesson["title"] + "\n\n" + markdown, encoding="utf-8")
            relative = lambda path: path.relative_to(ROOT).as_posix()
            updates[identifier] = {
                "html_path": relative(html_path), "markdown_path": relative(markdown_path),
                "raw_html_path": relative(raw_html_path), "raw_text_path": relative(raw_text_path),
                "capture_path": relative(capture_path), "status": "imported",
                "images_status": "complete", "image_count": len(stats["images"]),
                "unique_image_count": len({item["path"] for item in stats["images"]}),
                "text_integrity": "verified", "import_source": "authorized_browser_ui",
            }
            audio_sources = [item for item in capture.get("audio", []) if item.get("src") or item.get("currentSrc")]
            if audio_sources:
                updates[identifier]["observed_audio_sources"] = audio_sources
            provenance["lessons"][identifier] = {
                "source_url": source_url, "capture_path": relative(capture_path),
                "capture_sha256": digest(capture_bytes),
                "capture_file_modified_at": datetime.fromtimestamp(capture_path.stat().st_mtime, timezone.utc).isoformat(),
                "raw_html_path": relative(raw_html_path), "raw_html_sha256": digest(capture["html"]),
                "html_path": relative(html_path), "html_sha256": digest(html_path.read_bytes()),
                "markdown_path": relative(markdown_path), "markdown_sha256": digest(markdown_path.read_bytes()),
                "visible_text_characters_without_whitespace": len(source_text),
                "text_integrity": "verified", "markdown_text_integrity": "verified",
                "removed_ui_nodes": stats["removed_ui_nodes"], "font_elements_converted_to_span": stats["font_to_span"],
                "images": stats["images"], "observed_audio_sources": audio_sources,
            }
            print(json.dumps({"id": identifier, "title": lesson["title"], "text_characters": len(source_text), "image_references": len(stats["images"]), "unique_images": updates[identifier]["unique_image_count"], "text_integrity": "verified"}, ensure_ascii=False))
        except Exception as error:
            failures.append({"capture": str(capture_path), "error": str(error)})
            print(json.dumps(failures[-1], ensure_ascii=False), file=sys.stderr)
    # Re-read immediately before saving so independently imported lessons survive.
    course = json.loads(manifest_path.read_text())
    for lesson in course["lessons"]:
        lesson.update(updates.get(lesson["id"], {}))
    write_json(manifest_path, course)
    write_json(provenance_path, provenance)
    write_json(ROOT / "assets/images/manifest.json", list(images.entries.values()))
    write_json(ROOT / "raw/import-ui-report.json", {"imported_in_run": len(updates), "failures": failures, "total_imported_bodies": sum(bool(lesson.get("markdown_path")) for lesson in course["lessons"]), "total_local_images": len(images.entries)})
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
