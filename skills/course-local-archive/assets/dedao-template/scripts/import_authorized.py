#!/usr/bin/env python3
"""Import a same-origin course JSON export into local source files and media.

Writes course.json once after all text/image work. Audio is queued separately;
this importer does not download audio and preserves completed audio metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from export_public import ROOT, write_json
from archive_config import configured_course_id
from import_ui import Tree, all_text, canonical_text, markdown_node
from build_site import markdown as render_markdown


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def image_locations(value):
    """Yield parent/key pairs for rendered images, excluding ordinary links."""
    if isinstance(value, list):
        for child in value:
            yield from image_locations(child)
    elif isinstance(value, dict):
        kind = value.get("type")
        for key, child in list(value.items()):
            is_url = isinstance(child, str) and child.startswith(("https://", "http://"))
            if is_url and ((key == "url" and kind in {"image", "inline-image"}) or key in {"avatar", "cover", "cover_img", "coverImg", "poster", "index_img", "indexImg", "icon", "image", "img", "logo", "article_logo", "logo_iphonex", "square_img", "outline_img", "player_img", "lecturer_avatar"}):
                yield value, key
            elif isinstance(child, (dict, list)):
                yield from image_locations(child)


def download_image(url, old):
    if old and (ROOT / old["path"]).is_file():
        body = (ROOT / old["path"]).read_bytes()
        if sha(body) == old.get("sha256"):
            return old
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        body = response.read()
    if body.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif body.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif body.startswith((b"GIF87a", b"GIF89a")):
        suffix = ".gif"
    elif body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        suffix = ".webp"
    elif b"ftypavif" in body[:32] or b"ftypavis" in body[:32]:
        suffix = ".avif"
    else:
        raise ValueError("The image URL did not return a recognized raster image")
    target = ROOT / "assets/images" / (sha(url)[:16] + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {"source_url": url, "path": target.relative_to(ROOT).as_posix(), "bytes": len(body), "sha256": sha(body), "roles": list(old.get("roles", [])) if old else []}


def escape(value):
    return html.escape(str(value), quote=True)


def link_key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Renderer:
    def __init__(self, lesson, image_map, link_targets=None, external_routes=None):
        self.lesson = lesson
        self.image_map = image_map
        self.link_targets = link_targets or {}
        self.external_routes = external_routes or {}
        self.issues = []
        self.types = Counter()
        self.links = []

    def image(self, url, alt="", inline=False):
        image = self.image_map.get(url)
        if not image:
            self.issues.append({"kind": "missing_image", "source_url": url})
            return "", str(alt)
        markup = f'<img src="../{escape(image["path"])}" alt="{escape(alt)}">'
        return markup, ""

    def source_link(self, markup, raw):
        """Retain CMS route metadata verbatim; resolve only observed identities.

        Source type 6 IDs are legacy origin IDs, not the current article IDs.
        An exact (course product ID, legacy origin ID) match to an archived
        lesson is sufficient for a local link. Other route types remain fully
        represented as metadata until their original routing is established.
        """
        try:
            target = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            target = None
        metadata = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        details = {"source_link": target, "raw": metadata}
        if isinstance(target, dict) and target.get("type") == 6:
            destination = self.link_targets.get((str(target.get("cid", "")), str(target.get("typeid", ""))))
            if destination:
                self.links.append({**details, "resolution": "local_course_article", "lesson_id": destination["id"], "source_url": destination["source_url"]})
                return '<a href="../index.html#lesson=' + escape(destination["id"]) + '" data-dedao-link="' + escape(metadata) + '" data-source-url="' + escape(destination["source_url"]) + '">' + markup + '</a>'
        route = self.external_routes.get(link_key(target)) if isinstance(target, dict) else None
        if route:
            self.links.append({**details, "resolution": "verified_external_source_url", "source_url": route["url"], "route_evidence": route.get("evidence", {})})
            return '<a href="' + escape(route["url"]) + '" data-dedao-link="' + escape(metadata) + '">' + markup + '</a>'
        self.links.append({**details, "resolution": "source_metadata_preserved_route_unresolved"})
        return '<span class="source-link" data-dedao-link="' + escape(metadata) + '" data-link-resolution="unresolved">' + markup + '</span>'

    def inline(self, value):
        if value is None:
            return "", ""
        if isinstance(value, str):
            return escape(value), value
        if isinstance(value, list):
            rendered = [self.inline(item) for item in value]
            return "".join(item[0] for item in rendered), "".join(item[1] for item in rendered)
        kind = value.get("type")
        if kind == "text" or "text" in value:
            attributes = value.get("text", {})
            if isinstance(attributes, str):
                attributes = {"content": attributes}
            plain = attributes.get("content", "")
            markup = escape(plain)
            if attributes.get("bold"):
                markup = "<strong>" + markup + "</strong>"
            if attributes.get("italic"):
                markup = "<em>" + markup + "</em>"
            if attributes.get("underline"):
                markup = "<u>" + markup + "</u>"
            if attributes.get("strike") or attributes.get("strikethrough"):
                markup = "<s>" + markup + "</s>"
            if attributes.get("highlight"):
                markup = '<span style="color: rgb(255, 107, 0)">' + markup + "</span>"
            if attributes.get("link"):
                markup = self.source_link(markup, attributes["link"])
            return markup, plain
        if kind in {"image", "inline-image"}:
            return self.image(value.get("url", ""), value.get("legend", ""), inline=True)
        if kind in {"link", "hyperlink"}:
            label = value.get("contents", value.get("title", value.get("content", "")))
            markup, plain = self.inline(label)
            url = value.get("url") or value.get("href") or value.get("link", {}).get("url", "")
            if str(url).startswith(("https://", "http://", "mailto:", "#")):
                markup = f'<a href="{escape(url)}">{markup}</a>'
            return markup, plain
        self.issues.append({"kind": "unsupported_inline", "type": kind})
        fallback = value.get("content", "")
        return escape(fallback), str(fallback)

    def block(self, block, index):
        kind = block.get("type")
        self.types[kind] += 1
        # Lists render row by row below. Avoid rendering them twice, which
        # would duplicate link-resolution provenance for their text nodes.
        content, plain = self.inline(block.get("contents", [])) if kind != "list" else ("", "")
        expected = block.get("text") if isinstance(block.get("text"), str) else plain
        align = block.get("justify", "left")
        if align not in {"left", "right", "center", "justify"}:
            align = "left"
        if kind in {"paragraph", "salutation", "tip", "date", "wish", "header", "elite"}:
            level = block.get("level", 2)
            level = level if isinstance(level, int) and 1 <= level <= 6 else 2
            tag = "h" + str(level) if kind == "header" else "h2" if kind == "salutation" else "h3" if kind == "wish" else "h4" if kind == "date" else "p"
            markup = f'<{tag} style="text-align: {align}; white-space: pre-line">{content}</{tag}>'
            if kind == "elite":
                markup = '<aside class="source-elite">' + markup + '</aside>'
        elif kind == "list":
            tag = "ol" if block.get("ordered") else "ul"
            rows = [self.inline(row) for row in block.get("contents", [])]
            markup = f'<{tag} style="text-align: {align}; white-space: pre-line">' + "".join("<li>" + item[0] + "</li>" for item in rows) + f"</{tag}>"
            plain = "\n".join(item[1] for item in rows)
            expected = block.get("text", plain)
        elif kind in {"image", "inline-image"}:
            picture, _ = self.image(block.get("url", ""), block.get("legend", ""))
            dimensions = "".join(' ' + key + '="' + str(block[key]) + '"' for key in ("width", "height") if isinstance(block.get(key), (int, float)) and block[key] > 0)
            if dimensions:
                picture = picture.replace("<img ", '<img style="max-width: 100%; height: auto"' + dimensions + ' ', 1)
            old_link = block.get("oldLink") or {}
            image_link = block.get("jump") or (old_link.get("id") if old_link.get("type") == 10001 else "")
            if isinstance(image_link, str) and image_link.startswith(("https://", "http://")):
                picture = '<a href="' + escape(image_link) + '">' + picture + '</a>'
                self.links.append({"resolution": "source_image_url", "source_url": image_link})
            legend = block.get("legend", "")
            markup = "<figure>" + picture + ("<figcaption>" + escape(legend) + "</figcaption>" if legend else "") + "</figure>"
            expected = legend
        elif kind == "blockquote":
            subtype = block.get("subtype", 0)
            if subtype == 1:
                author = block.get("cite", {}).get("author", {})
                picture, _ = self.image(author["avatar"]) if author.get("avatar") else ("", "")
                name = author.get("name", "")
                markup = '<div class="source-quote"><div class="source-author">' + picture + "<p>" + escape(name) + '</p></div><blockquote style="white-space: pre-line"><p>' + content + "</p></blockquote></div>"
                expected = block.get("text", name + plain)
            elif subtype == 2:
                answer = block.get("answer", {})
                title = answer.get("title", "")
                asker = answer.get("askName", "")
                markup = '<div class="source-answer"><p>' + escape(title) + '</p><blockquote style="white-space: pre-line">' + (escape(asker) + " " if asker else "") + content + "</blockquote></div>"
                expected = block.get("text", title + asker + plain)
            else:
                markup = '<blockquote style="white-space: pre-line">' + content + "</blockquote>"
        elif kind == "hr":
            markup, expected = "<hr>", ""
        elif kind == "audio":
            title, description = block.get("title", ""), block.get("desc", "")
            main = (self.lesson.get("info", {}).get("article_info") or {}).get("audio") or {}
            same_audio = str(block.get("aliasId", block.get("alias_id", ""))) == str(main.get("alias_id", ""))
            path = ROOT / "assets/audio" / (self.lesson["id"] + ".m4a")
            player = f'<audio controls preload="none" src="../{path.relative_to(ROOT).as_posix()}"></audio>' if same_audio and path.is_file() else ""
            markup = '<div class="source-audio"><p>' + escape(title) + "</p><p>" + escape(description) + "</p>" + player + "</div>"
            expected = title + description
            if not same_audio:
                self.issues.append({"kind": "embedded_audio_requires_source", "alias_id": block.get("aliasId", block.get("alias_id", "")), "title": title})
        elif kind == "label-group":
            labels = block.get("labels", [])
            markup = '<p class="source-labels">' + " ".join(escape(label) for label in labels) + "</p>"
            expected = " ".join(labels)
        elif kind == "code-block":
            text = block.get("code", block.get("text", plain))
            markup, expected = "<pre><code>" + escape(text) + "</code></pre>", text
        else:
            self.issues.append({"kind": "unsupported_block", "type": kind, "block_index": index})
            markup = '<p style="white-space: pre-line">' + escape(expected) + "</p>"
        actual = canonical_text(all_text(Tree(markup).root))
        if actual != canonical_text(expected):
            self.issues.append({"kind": "text_mismatch", "type": kind, "block_index": index, "source_characters": len(canonical_text(expected)), "rendered_characters": len(actual)})
        return markup, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--course-id", help="Expected source course enid; otherwise read course-config.json")
    parser.add_argument("--image-workers", type=int, default=4)
    parser.add_argument("--render-only", action="store_true", help="Rebuild derived bodies using verified local images; never fetch media or rewrite raw source files")
    args = parser.parse_args()
    args.course_id = configured_course_id(args.course_id)
    archive_path = args.archive.resolve()
    archive_bytes = archive_path.read_bytes()
    archive = json.loads(archive_bytes)
    if archive.get("course", {}).get("enid") != args.course_id:
        parser.error("The archive does not match the requested source course")
    manifest_path = ROOT / "course.json"
    course = json.loads(manifest_path.read_text())
    catalog = {lesson["id"]: lesson for lesson in course["lessons"]}
    items = archive.get("lessons", [])
    if len({str(item["id"]) for item in items}) != len(items):
        parser.error("Duplicate lesson IDs in the archive")
    image_manifest_path = ROOT / "assets/images/manifest.json"
    image_manifest = json.loads(image_manifest_path.read_text()) if image_manifest_path.exists() else []
    image_map = {item["source_url"]: item for item in image_manifest}
    link_targets = {}
    for item in items:
        info = item.get("info", {})
        article = info.get("article_info") or {}
        origin_id = info.get("origin_article_id", article.get("origin_id"))
        product_id = info.get("pid", article.get("product_id"))
        if origin_id is not None and product_id is not None:
            identity = (str(product_id), str(origin_id))
            if identity in link_targets:
                parser.error("Duplicate legacy article identity makes source link resolution ambiguous")
            link_targets[identity] = item
    external_routes = {}
    route_path = ROOT / "raw/reverification-link-routes.json"
    if route_path.is_file():
        for route in json.loads(route_path.read_text()).get("routes", []):
            target = route.get("source_link", {})
            parsed = urllib.parse.urlsplit(route.get("url", ""))
            expected_path = {2: "/ebook/detail", 13: "/audioBook/detail", 6: "/course/article"}.get(target.get("type"))
            query = urllib.parse.parse_qs(parsed.query)
            evidence = route.get("evidence", {})
            if parsed.scheme != "https" or parsed.netloc != "www.dedao.cn" or parsed.path != expected_path or parsed.fragment or query != {"id": [route.get("enid")]} or not route.get("enid") or evidence.get("http_status") != 200 or evidence.get("api_code") != 0:
                parser.error("A recorded external link route lacks verified source identity or a supported URL")
            external_routes[link_key(target)] = route
    parsed, image_roles, audio_queue = {}, {}, []
    body_image_urls, metadata_image_urls = set(), set()
    for parent, key in image_locations(archive.get("course", {})):
        image_roles.setdefault(parent[key], set()).add("course-metadata")
        metadata_image_urls.add(parent[key])
    for item in items:
        item["id"] = str(item["id"])
        known = catalog.get(item["id"])
        if not known or known["enid"] != item["enid"] or known["title"] != item["title"]:
            parser.error("An archive lesson does not match the established source catalog")
        blocks = json.loads(item["body"]["content"])
        if not isinstance(blocks, list):
            parser.error("A source lesson body is not a block array")
        parsed[item["id"]] = blocks
        if not args.render_only:
            write_json(ROOT / "raw/authorized" / (item["id"] + ".info.json"), {"c": item["info"]})
            write_json(ROOT / "raw/authorized" / (item["id"] + ".body.json"), item["body"])
            write_json(ROOT / "raw/lessons" / (item["id"] + ".blocks.json"), blocks)
            (ROOT / "raw/lessons" / (item["id"] + ".content.json")).write_text(item["body"]["content"], encoding="utf-8")
        for parent, key in image_locations(blocks):
            image_roles.setdefault(parent[key], set()).add("lesson-" + item["id"])
            body_image_urls.add(parent[key])
        for parent, key in image_locations(item["info"]):
            image_roles.setdefault(parent[key], set()).add("lesson-" + item["id"] + "-metadata")
            metadata_image_urls.add(parent[key])
        audio = (item.get("info", {}).get("article_info") or {}).get("audio") or {}
        if audio.get("mp3_play_url"):
            audio_queue.append({"id": item["id"], "title": item["title"], "source_info_path": "raw/authorized/" + item["id"] + ".info.json", "audio_url": audio["mp3_play_url"], "expected_duration": audio.get("duration"), "alias_id": audio.get("alias_id")})
    if not args.render_only:
        write_json(ROOT / "raw/audio-download-queue.json", {"schema_version": 1, "lessons": audio_queue})
    print(json.dumps({"phase": "images", "lessons": len(items), "unique_source_images": len(image_roles), "audio_queue": len(audio_queue)}, ensure_ascii=False), flush=True)
    image_errors = []
    if args.render_only:
        for url in image_roles:
            entry = image_map.get(url)
            path = ROOT / entry["path"] if entry else None
            if not path or not path.is_file() or sha(path.read_bytes()) != entry.get("sha256"):
                image_errors.append({"source_url": url, "error": "Verified local image is absent; render-only mode cannot fetch it"})
        if image_errors:
            parser.error("Render-only mode requires all source images to exist and match their recorded hashes")
    else:
        with ThreadPoolExecutor(max_workers=max(1, min(args.image_workers, 6))) as executor:
            tasks = {executor.submit(download_image, url, image_map.get(url)): url for url in image_roles}
            for future in as_completed(tasks):
                url = tasks[future]
                try:
                    entry = future.result()
                    entry["roles"] = sorted(set(entry.get("roles", [])) | image_roles[url])
                    image_map[url] = entry
                except Exception as error:
                    image_errors.append({"source_url": url, "error": str(error)})
        write_json(image_manifest_path, list(image_map.values()))
    updates, reports = {}, {}
    block_types = Counter()
    for item in items:
        identifier = item["id"]
        known = catalog[identifier]
        blocks = parsed[identifier]
        renderer = Renderer(item, image_map, link_targets, external_routes)
        rendered = [renderer.block(block, index) for index, block in enumerate(blocks)]
        markup = "\n".join(block[0] for block in rendered) + "\n"
        source_text = "".join(block[1] for block in rendered)
        # Markdown permits raw HTML. Retain each source block as inline HTML so
        # adjacent bold runs, literal underscores, and numbered source prose
        # survive round-tripping without Markdown syntax changing their text.
        # Character references retain original line feeds inside each block.
        markdown = "\n\n".join(block[0].replace("\n", "&#10;") for block in rendered) + "\n"
        markdown_text = canonical_text(all_text(Tree(render_markdown(markdown)).root))
        html_text = canonical_text(all_text(Tree(markup).root))
        if markdown_text != html_text:
            renderer.issues.append({"kind": "markdown_text_mismatch", "html_characters": len(html_text), "markdown_characters": len(markdown_text)})
        stem = f'{known["order"]:04d}-{identifier}'
        html_path = ROOT / "content" / (stem + ".html")
        markdown_path = ROOT / "content" / (stem + ".md")
        html_path.write_text(markup, encoding="utf-8")
        frontmatter = "---\n" + "\n".join([
            "title: " + json.dumps(item["title"], ensure_ascii=False),
            "source_url: " + json.dumps(item["source_url"]),
            "source_article_id: " + json.dumps(identifier),
            'import_source: "authorized_same_origin_api"',
            'raw_blocks_path: "../raw/lessons/' + identifier + '.blocks.json"',
        ]) + "\n---\n\n"
        markdown_path.write_text(frontmatter + "# " + item["title"] + "\n\n" + markdown, encoding="utf-8")
        localized = copy.deepcopy(blocks)
        refs = []
        for parent, key in image_locations(localized):
            source = parent[key]
            refs.append(source)
            if source in image_map:
                parent["source_" + key] = source
                parent[key] = image_map[source]["path"]
        local_blocks_path = ROOT / "content" / (stem + ".blocks.local.json")
        write_json(local_blocks_path, localized)
        localized_info = copy.deepcopy(item["info"])
        metadata_refs = []
        for parent, key in image_locations(localized_info):
            source = parent[key]
            metadata_refs.append(source)
            if source in image_map:
                parent["source_" + key] = source
                parent[key] = image_map[source]["path"]
        localized_info_path = ROOT / "content" / (stem + ".info.local.json")
        write_json(localized_info_path, localized_info)
        missing_images = [source for source in refs + metadata_refs if source not in image_map]
        body_issues = [issue for issue in renderer.issues if issue["kind"] != "embedded_audio_requires_source"]
        updates[identifier] = {
            "html_path": html_path.relative_to(ROOT).as_posix(), "markdown_path": markdown_path.relative_to(ROOT).as_posix(),
            "raw_blocks_path": "raw/lessons/" + identifier + ".blocks.json", "localized_blocks_path": local_blocks_path.relative_to(ROOT).as_posix(),
            "source_info_path": "raw/authorized/" + identifier + ".info.json", "source_body_path": "raw/authorized/" + identifier + ".body.json",
            "localized_info_path": localized_info_path.relative_to(ROOT).as_posix(),
            "status": "partial" if body_issues else "imported", "images_status": "partial" if missing_images else "complete",
            "image_count": len(refs), "unique_image_count": len(set(refs)),
            "metadata_images": [{"source_url": source, "path": image_map[source]["path"]} for source in dict.fromkeys(metadata_refs) if source in image_map],
            "text_integrity": "mismatch" if any(issue["kind"] in {"text_mismatch", "markdown_text_mismatch"} for issue in renderer.issues) else "verified",
            "import_source": "authorized_same_origin_api",
        }
        reports[identifier] = {
            "source_url": item["source_url"], "source_blocks": len(blocks), "block_types": dict(renderer.types),
            "source_text_characters_without_whitespace": len(canonical_text(source_text)), "html_text_characters_without_whitespace": len(html_text),
            "raw_content_sha256": sha(item["body"]["content"]), "html_sha256": sha(markup), "markdown_sha256": sha(markdown_path.read_bytes()),
            "image_references": len(refs), "unique_images": len(set(refs)), "issues": renderer.issues,
            "metadata_image_references": len(metadata_refs), "unique_metadata_images": len(set(metadata_refs)),
            "source_links": renderer.links,
        }
        block_types.update(renderer.types)
    # One manifest write after reading the latest version preserves a separately
    # completed audio pipeline's fields and all untouched lesson imports.
    course = json.loads(manifest_path.read_text())
    for lesson in course["lessons"]:
        lesson.update(updates.get(lesson["id"], {}))
    course.pop("audio_policy", None)
    if image_errors or any(update["status"] != "imported" or update["images_status"] != "complete" for update in updates.values()):
        course["archive_status"] = "partial"
    elif not args.render_only and course.get("archive_status") != "complete":
        course["archive_status"] = "partial"
    write_json(manifest_path, course)
    directory = ["# " + course["title"], "", course.get("description", ""), "", "来源：" + course.get("source_url", ""), "", "[课程介绍、讲师简介与章节导读](课程信息.md)", ""]
    for section in course.get("sections", []):
        directory.extend(["## " + section["title"], ""])
        for lesson in course["lessons"]:
            if lesson.get("section_id") == section["id"]:
                destination = Path(lesson["markdown_path"]).name if lesson.get("markdown_path") else lesson["source_url"]
                directory.append("- [" + lesson["title"] + "](" + destination + ")")
        directory.append("")
    (ROOT / "content/目录.md").write_text("\n".join(directory), encoding="utf-8")
    report = {
        "archive_path": str(archive_path), "archive_sha256": sha(archive_bytes), "source_lessons": len(items),
        "imported_bodies": len(updates), "block_types": dict(block_types), "unique_source_images": len(image_roles),
        "body_unique_source_images": len(body_image_urls), "metadata_unique_source_images": len(metadata_image_urls),
        "downloaded_source_images": sum(url in image_map for url in image_roles), "image_errors": image_errors,
        "audio_queue_lessons": len(audio_queue), "lessons": reports,
        "external_route_evidence_path": route_path.relative_to(ROOT).as_posix() if external_routes else None,
        "external_route_evidence_sha256": sha(route_path.read_bytes()) if external_routes else None,
    }
    write_json(ROOT / "raw/authorized-import-report.json", report)
    issues = sum(len([issue for issue in lesson["issues"] if issue["kind"] != "embedded_audio_requires_source"]) for lesson in reports.values())
    print(json.dumps({"phase": "finished", "imported_bodies": len(updates), "body_issues": issues, "image_errors": len(image_errors), "audio_queue": len(audio_queue)}, ensure_ascii=False), flush=True)
    if image_errors or issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
