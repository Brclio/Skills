"""Independent, testable safety and file-handling core for the R&D downloader."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


MAX_BYTES = 1_073_741_824  # 1 GiB; do not let an unexpected response fill a disk.
MEDIA_SUFFIXES = ("qq.com", "qpic.cn", "myqcloud.com", "tencent.com", "gtimg.com")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"


class SkillError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_share_url(raw: str) -> str:
    """Accept only a single, plain WeChat Channels share link."""
    if not isinstance(raw, str) or len(raw) > 1024 or any(c.isspace() for c in raw):
        raise SkillError("INVALID_LINK", "请只提供一条完整的视频号分享链接。")
    try:
        parts = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise SkillError("INVALID_LINK", "分享链接格式不正确。") from exc
    if (parts.scheme.lower() != "https" or parts.netloc.lower() != "weixin.qq.com"
            or not re.fullmatch(r"/sph/[A-Za-z0-9]+/?", parts.path)
            or parts.query or parts.fragment):
        raise SkillError("INVALID_LINK", "目前只支持 https://weixin.qq.com/sph/... 格式的单条链接。")
    return urllib.parse.urlunsplit(("https", "weixin.qq.com", parts.path.rstrip("/"), "", ""))


def _allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return any(host == suffix or host.endswith("." + suffix) for suffix in MEDIA_SUFFIXES)


def validate_media_url(raw: str) -> str:
    try:
        parts = urllib.parse.urlsplit(raw)
        host, port = parts.hostname, parts.port
    except (TypeError, ValueError, AttributeError) as exc:
        raise SkillError("UNTRUSTED_MEDIA_URL", "视频地址格式异常，已停止下载。") from exc
    if (not isinstance(raw, str) or len(raw) > 8192 or parts.scheme.lower() != "https"
            or not host or not _allowed_host(host) or port not in (None, 443)
            or parts.username or parts.password):
        raise SkillError("UNTRUSTED_MEDIA_URL", "视频地址不在允许的腾讯域名范围内，已停止下载。")
    return raw


def extract_ticket(playable_url: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(playable_url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    except (TypeError, ValueError) as exc:
        raise SkillError("PARSE_CHANGED", "平台返回的视频票据格式已变化。") from exc
    if parsed.scheme != "https" or parsed.hostname != "channels.weixin.qq.com":
        raise SkillError("PARSE_CHANGED", "平台返回的视频票据来源异常。")
    token, eid = params.get("token", []), params.get("eid", [])
    if len(token) != 1 or len(eid) != 1 or not token[0] or not eid[0]:
        raise SkillError("PARSE_CHANGED", "平台返回的视频票据缺少必要字段。")
    if len(token[0]) > 4096 or len(eid[0]) > 1024:
        raise SkillError("PARSE_CHANGED", "平台返回的视频票据长度异常。")
    return token[0], eid[0]


def _walk_dicts(value: Any, depth: int = 0):
    if depth > 8:
        return
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item, depth + 1)
    elif isinstance(value, list):
        for item in value[:30]:
            yield from _walk_dicts(item, depth + 1)


def media_from_feed(payload: Any, codec: str) -> tuple[str, str]:
    key = "h264VideoInfo" if codec == "h264" else "h265VideoInfo"
    for obj in _walk_dicts(payload):
        candidate = obj.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("videoUrl"), str):
            url = validate_media_url(candidate["videoUrl"])
            title = obj.get("description") or obj.get("title") or "视频号视频"
            return url, str(title)[:120]
    raise SkillError("NO_MEDIA", "未找到可下载的视频；可能是链接失效、无权限或平台接口变化。")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > 3:
            raise SkillError("TOO_MANY_REDIRECTS", "视频下载重定向过多。")
        validate_media_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_media(url: str, output_dir: Path, *, max_bytes: int = MAX_BYTES,
                   opener=None) -> dict[str, Any]:
    """Stream a validated media URL into an exclusive temp file, then publish it."""
    validate_media_url(url)
    if max_bytes < 1024:
        raise ValueError("max_bytes too small")
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / ("wxvideo_" + uuid.uuid4().hex[:16] + ".mp4")
    redirect_guard = _GuardedRedirect()
    opener = opener or urllib.request.build_opener(redirect_guard)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "video/mp4,*/*"})
    temp_path = None
    try:
        try:
            response = opener.open(request, timeout=45)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SkillError("DOWNLOAD_UNAVAILABLE", "视频源暂不可达或拒绝下载。") from exc
        with response:
            declared = response.headers.get("Content-Length")
            try:
                declared_int = int(declared) if declared is not None else None
            except ValueError:
                raise SkillError("BAD_RESPONSE", "视频源返回了异常文件长度。")
            if declared_int is not None and (declared_int < 1024 or declared_int > max_bytes):
                raise SkillError("SIZE_LIMIT", "视频大小超出允许范围。")
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".wxvideo_", suffix=".part",
                                             dir=output_dir, delete=False) as file:
                temp_path = Path(file.name)
                digest = hashlib.sha256()
                count = 0
                first = b""
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > max_bytes:
                        raise SkillError("SIZE_LIMIT", "视频下载超过大小限制，已停止。")
                    if len(first) < 12:
                        first += chunk[:12 - len(first)]
                    file.write(chunk)
                    digest.update(chunk)
        if count < 1024 or len(first) < 8 or first[4:8] != b"ftyp":
            raise SkillError("INVALID_MP4", "下载结果不是有效的 MP4 文件头。")
        if declared_int is not None and count != declared_int:
            raise SkillError("INCOMPLETE_DOWNLOAD", "下载字节数与服务器声明不符。")
        os.rename(temp_path, target)  # Windows refuses to replace an existing target.
        temp_path = None
        return {"file_path": str(target), "bytes": count, "sha256": digest.hexdigest()}
    except OSError as exc:
        raise SkillError("FILE_WRITE_FAILED", "本地写入失败；请检查目录权限和剩余空间。") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
