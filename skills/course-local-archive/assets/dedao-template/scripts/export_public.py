#!/usr/bin/env python3
"""Initialize a course from its observed public catalog and localize course images.

Existing lesson imports and media metadata are preserved on reruns. Does not
request lesson bodies or playback metadata.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import shutil
import urllib.parse
import urllib.request

from archive_config import configured_course_id

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw/public"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Images:
    def __init__(self):
        self.entries = {}
        self.directory = ROOT / "assets/images"
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest = self.directory / "manifest.json"
        if manifest.exists():
            self.entries = {entry["source_url"]: entry for entry in json.loads(manifest.read_text())}

    def save(self, url: str, role: str) -> str:
        if url in self.entries:
            if role not in self.entries[url]["roles"]:
                self.entries[url]["roles"].append(role)
            return self.entries[url]["path"]
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not (parsed.hostname == "umiwi.com" or (parsed.hostname or "").endswith(".umiwi.com")):
            raise ValueError(f"Unexpected image origin: {url}")
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            raise ValueError(f"Unexpected image format: {url}")
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + suffix
        target = self.directory / name
        if not target.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=40) as response:
                content_type = response.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    raise ValueError(f"Image returned {content_type}: {url}")
                data = response.read()
            target.write_bytes(data)
        data = target.read_bytes()
        if not data:
            raise ValueError(f"Empty image: {url}")
        relative = target.relative_to(ROOT).as_posix()
        self.entries[url] = {
            "source_url": url, "path": relative, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "roles": [role],
        }
        return relative



def main():
    catalog = json.loads((RAW / "catalog.json").read_text(encoding="utf-8"))
    metadata = json.loads((RAW / "class-info.json").read_text(encoding="utf-8"))["c"]
    info = catalog["class_info"]
    expected_enid = configured_course_id()
    if info.get("enid") != expected_enid:
        raise ValueError("The public catalog belongs to a different course")
    images = Images()
    fields = ("index_img", "logo", "logo_iphonex", "square_img", "outline_img", "player_img", "lecturer_avatar")
    course_images = {field: images.save(info[field], "course-" + field) for field in fields if info.get(field)}
    old_path = ROOT / "course.json"
    previous = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else {}
    if previous.get("course_enid") and previous["course_enid"] != expected_enid:
        raise ValueError("Existing course manifest belongs to a different course")
    old_lessons = {str(row["id"]): row for row in previous.get("lessons", [])}
    sections, lessons = [], []
    for chapter in catalog["chapter_list"]:
        sid = str(chapter.get("id_str") or chapter["id"])
        sections.append({"id": sid, "title": chapter["name"], "description": chapter.get("intro", ""), "lesson_count": len(chapter["article_list"])})
        for row in chapter["article_list"]:
            identifier = str(row.get("id_str") or row["id"])
            lesson = {"id": identifier, "enid": row["enid"], "title": row["title"], "section": chapter["name"], "section_id": sid, "source_url": "https://www.dedao.cn/course/article?id=" + row["enid"], "summary": row.get("summary", ""), "publish_time": row.get("publish_time"), "markdown_path": None, "html_path": None, "status": "pending", "audio": [], "video": [], "audio_status": "pending", "video_status": "pending", "images_status": "pending", "order": len(lessons) + 1}
            if identifier in old_lessons:
                lesson.update(old_lessons[identifier])
                lesson.update({"title": row["title"], "section": chapter["name"], "section_id": sid, "order": len(lessons) + 1})
            lessons.append(lesson)
    expected = int(info["current_article_count"])
    if len(lessons) != expected or len({row["id"] for row in lessons}) != expected:
        raise ValueError("Public catalog count does not match source course count")
    manifest = {**previous, "schema_version": 1, "title": info["name"], "description": info.get("intro", ""), "source_url": "https://www.dedao.cn/course/detail?id=" + info["enid"], "course_enid": info["enid"], "expected_lesson_count": expected, "cover_path": course_images.get("index_img"), "images": course_images, "sections": sections, "lessons": lessons, "archive_status": previous.get("archive_status", "partial")}
    write_json(old_path, manifest)
    write_json(ROOT / "assets/images/manifest.json", list(images.entries.values()))
    (ROOT / "content").mkdir(parents=True, exist_ok=True)
    lines = ["# " + info["name"], "", info.get("intro", ""), "", "来源：[得到课程页面](" + manifest["source_url"] + ")", "", "目录共 " + str(expected) + " 讲；正文和媒体状态以 course.json 为准。", "", "[课程介绍与讲师简介](课程信息.md)", ""]
    for section in sections:
        lines += ["## " + section["title"], ""]
        for lesson in lessons:
            if lesson["section_id"] == section["id"]:
                destination = Path(lesson["markdown_path"]).name if lesson.get("markdown_path") else lesson["source_url"]
                lines.append("- [" + lesson["title"] + "](" + destination + ")")
        lines.append("")
    (ROOT / "content/目录.md").write_text("\n".join(lines), encoding="utf-8")
    details = ["# " + info["name"], "", info.get("intro", ""), "", "来源：[得到课程页面](" + manifest["source_url"] + ")", ""]
    if course_images.get("index_img"):
        details += ["![课程封面](../" + course_images["index_img"] + ")", ""]
    details += ["## 课程亮点", "", info.get("highlight", ""), "", "## 讲师简介", "", "### " + info.get("lecturer_name", "讲师"), "", info.get("lecturer_title", ""), ""]
    if course_images.get("lecturer_avatar"):
        details += ["![讲师头像](../" + course_images["lecturer_avatar"] + ")", ""]
    details += [info.get("lecturer_intro", ""), "", "## 课程大纲", ""]
    if course_images.get("outline_img"):
        details += ["![课程大纲](../" + course_images["outline_img"] + ")", ""]
    for section in sections:
        details += ["### " + section["title"], "", section.get("description", ""), ""]
    for item in metadata.get("items", []):
        if item.get("content") and item.get("title") != "课程亮点":
            details += ["## " + item.get("title", "课程信息"), "", item["content"], ""]
    (ROOT / "content/课程信息.md").write_text("\n".join(details), encoding="utf-8")
    write_json(RAW / "export-report.json", {"catalog_lessons": len(lessons), "catalog_sections": len(sections), "expected_lessons": expected, "downloaded_course_images": len(images.entries), "downloaded_image_bytes": sum(row["bytes"] for row in images.entries.values())})
    print(json.dumps({"lessons": len(lessons), "sections": len(sections), "course_images": len(images.entries)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
