"""Byte-preserving raster downloads and scoped course-metadata HTML images."""
from __future__ import annotations
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.request

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def download_image(root, url, old=None):
    if old and (root / old["path"]).is_file():
        body = (root / old["path"]).read_bytes()
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
    elif body.startswith(b"BM") and len(body) >= 26 and int.from_bytes(body[2:6], "little") == len(body):
        suffix = ".bmp"
    elif b"ftypavif" in body[:32] or b"ftypavis" in body[:32]:
        suffix = ".avif"
    else:
        raise ValueError("The image URL did not return a recognized raster image")
    target = root / "assets/images" / (sha(url)[:16] + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return {"source_url": url, "path": target.relative_to(root).as_posix(), "bytes": len(body), "sha256": sha(body), "roles": list(old.get("roles", [])) if old else []}


def metadata_sections(metadata):
    """Only explicit course information, never reviews or recommendations."""
    seen=set()
    for key in ('items','new_items'):
        for item in metadata.get(key) or []:
            if not isinstance(item,dict) or not isinstance(item.get('content'),str) or not item['content']:
                continue
            identity=(str(item.get('title') or '课程信息'),item['content'])
            if identity not in seen:
                seen.add(identity)
                yield identity

class _ImageHTML(HTMLParser):
    def __init__(self, image_map=None):
        super().__init__(convert_charrefs=False)
        self.image_map=image_map
        self.urls=[]
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        raw=self.get_starttag_text()
        if tag=='img':
            source=dict(attrs).get('src','')
            if source.startswith(('https://','http://')):
                self.urls.append(source)
                if self.image_map is not None:
                    if source not in self.image_map:raise ValueError('Course metadata image has no local copy')
                    local='../'+self.image_map[source]['path']
                    raw=re.sub(r"""(?i)(\bsrc\s*=\s*)(?:"[^"]*"|'[^']*'|[^\s>]+)""",lambda m:m[1]+'"'+html.escape(local,quote=True)+'"',raw,count=1)
        self.parts.append(raw)
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):self.parts.append('</'+tag+'>')
    def handle_data(self,data):self.parts.append(data)
    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')
    def handle_comment(self,data):self.parts.append('<!--'+data+'-->')
    def handle_decl(self,decl):self.parts.append('<!'+decl+'>')

def metadata_html_images(metadata):
    for _,content in metadata_sections(metadata):
        parser=_ImageHTML();parser.feed(content);parser.close()
        yield from parser.urls

def localize_html_images(content,image_map):
    parser=_ImageHTML(image_map);parser.feed(content);parser.close()
    return ''.join(parser.parts)
