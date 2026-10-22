"""Visible-browser assistant runner. No existing browser profile is read."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import os
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

from core import SkillError, download_media, extract_ticket, media_from_feed, validate_share_url


PROFILE_SUBDIR = "zhixing-wxvideo-rd"
MAX_BATCH_LINKS = 50
MAX_BATCH_WORKERS = 4
PARSE_SCRIPT = """async ({sourceUrl}) => {
  const response = await fetch('/api/weixin/get_parse_result', {
    method: 'POST', credentials: 'include', redirect: 'error',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({type: 'video_channel_url', url: sourceUrl, scene: 1})
  });
  const body = await response.text();
  return {status: response.status, body: body.slice(0, 200000)};
}"""


def _platform_kind() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "unsupported"


def _browser_path() -> Path | None:
    if _platform_kind() == "windows":
        candidates = (
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        )
    elif _platform_kind() == "macos":
        candidates = tuple(
            root / app for root in (Path("/Applications"), Path.home() / "Applications")
            for app in (
                "Google Chrome.app/Contents/MacOS/Google Chrome",
                "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            )
        )
    else:
        return None
    return next((path for path in candidates if path.is_file()), None)


def _profile_path() -> Path:
    platform = _platform_kind()
    if platform == "windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise SkillError("LOCAL_DATA_MISSING", "未找到 Windows 本地应用数据目录。")
        return Path(base) / PROFILE_SUBDIR / "browser-profile"
    if platform == "macos":
        return Path.home() / "Library" / "Application Support" / PROFILE_SUBDIR / "browser-profile"
    raise SkillError("PLATFORM_UNSUPPORTED", "当前仅支持 Windows 和 macOS。")


def _setup_hint() -> str:
    if _platform_kind() == "macos":
        return "请先安装 Python 3.10+、Chrome/Edge，再运行 sh \"<Skill目录>/scripts/setup.sh\"。"
    return "请先安装 Python 3.10+、Edge/Chrome，再运行 scripts/setup.ps1。"


def doctor() -> dict[str, Any]:
    platform = _platform_kind()
    browser = _browser_path()
    try:
        import playwright.sync_api  # noqa: F401
        playwright_ready = True
    except ImportError:
        playwright_ready = False
    try:
        profile = str(_profile_path())
    except SkillError:
        profile = None
    ready = platform != "unsupported" and sys.version_info >= (3, 10) and bool(browser) and playwright_ready
    return {
        "status": "ready" if ready else "needs_setup",
        "platform": platform,
        "python": sys.version.split()[0],
        "playwright_installed": playwright_ready,
        "browser": str(browser) if browser else None,
        "profile_dir": profile,
        "next_step": "可执行下载" if ready else ("当前仅支持 Windows 和 macOS。" if platform == "unsupported" else _setup_hint()),
    }


def _logged_in(context) -> bool:
    """Check the visible account label without accessing browser credentials."""
    for page in context.pages:
        if page.is_closed() or not page.url.startswith("https://yuanbao.tencent.com/"):
            continue
        try:
            account_label = page.locator("p.nick-info-name:not(:empty)")
            if account_label.filter(has_not_text="未登录").count():
                return True
        except Exception:
            # The page may close or navigate while the user finishes QR login.
            continue
    return False


def _find_playable(payload: Any, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(payload, dict):
        for key in ("playable_url", "playableUrl"):
            if isinstance(payload.get(key), str):
                return payload[key]
        for value in payload.values():
            found = _find_playable(value, depth + 1)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload[:30]:
            found = _find_playable(value, depth + 1)
            if found:
                return found
    return None


def _open_context(wait_seconds: int):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SkillError("PLAYWRIGHT_MISSING", "尚未安装 Playwright。" + _setup_hint()) from exc
    profile = _profile_path()
    browser = _browser_path()
    if browser is None:
        raise SkillError("BROWSER_MISSING", "未找到 Edge 或 Chrome 浏览器。")
    profile.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), executable_path=str(browser), headless=False,
            accept_downloads=False, viewport={"width": 1180, "height": 760},
        )
    except Exception as exc:
        playwright.stop()
        raise SkillError("BROWSER_START_FAILED", "无法打开隔离浏览器；请关闭本工具旧窗口后重试。") from exc
    try:
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://yuanbao.tencent.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            raise SkillError("YUANBAO_UNAVAILABLE", "无法打开元宝登录页，请检查网络后重试。") from exc
        if not _logged_in(context):
            print("请在已打开的专用浏览器里自行扫码登录元宝；这里不会读取或显示密码、Cookie。", flush=True)
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if _logged_in(context):
                    break
                page.wait_for_timeout(1000)
            else:
                raise SkillError("LOGIN_REQUIRED", "等待登录超时；请重新运行并在浏览器里扫码。")
        # Login can open a fresh tab and close the original login page.
        live_pages = [p for p in context.pages if not p.is_closed()]
        yuanbao_pages = [p for p in live_pages if p.url.startswith("https://yuanbao.tencent.com/")]
        page = yuanbao_pages[-1] if yuanbao_pages else (live_pages[-1] if live_pages else context.new_page())
        try:
            page.goto("https://yuanbao.tencent.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            raise SkillError("YUANBAO_UNAVAILABLE", "登录后无法打开元宝主页。") from exc
        page.wait_for_timeout(2000)
        yield context, page
    finally:
        context.close()
        playwright.stop()


def _parse_source(page, share_url: str) -> tuple[str, str]:
    try:
        result = page.evaluate(PARSE_SCRIPT, {"sourceUrl": share_url})
    except Exception as exc:
        raise SkillError("PARSE_UNAVAILABLE", "元宝解析页面暂不可用，可能是网络或网页接口变化。" +
                         "（诊断：" + type(exc).__name__ + "）") from exc
    if isinstance(result, dict) and result.get("status") == 429:
        raise SkillError("RATE_LIMITED", "平台提示请求过于频繁；已停止解析后续链接。")
    if not isinstance(result, dict) or result.get("status") != 200:
        raise SkillError("PARSE_REJECTED", "元宝未接受此分享链接；请检查登录、链接和访问权限。")
    try:
        body = json.loads(result.get("body", ""))
    except (ValueError, TypeError) as exc:
        raise SkillError("PARSE_CHANGED", "元宝返回的数据格式发生变化。") from exc
    playable = _find_playable(body)
    if not playable:
        raise SkillError("NO_PLAYABLE_URL", "未取得可播放地址；可能是链接失效、无权限或平台接口变化。")
    return extract_ticket(playable)


def _fetch_feed_in_session(context, token: str, eid: str) -> dict[str, Any]:
    """Use only the isolated browser session; never copy its cookies to Python logs."""
    endpoint = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
    referer = "https://channels.weixin.qq.com/finder-preview/pages/feed?" + urllib.parse.urlencode(
        {"token": token, "eid": eid}
    )
    try:
        response = context.request.post(
            endpoint,
            headers={"Accept": "application/json, text/plain, */*",
                     "Origin": "https://channels.weixin.qq.com", "Referer": referer},
            data={"baseReq": {"generalToken": token}, "exportId": eid},
            timeout=30000, max_redirects=0,
        )
    except Exception as exc:
        raise SkillError("FEED_UNAVAILABLE", "视频号预览服务暂不可用。") from exc
    if not 200 <= response.status < 300:
        raise SkillError("FEED_HTTP_" + str(response.status),
                         "视频号预览服务拒绝访问（HTTP " + str(response.status) + "）。")
    try:
        payload = response.json()
    except Exception as exc:
        raise SkillError("FEED_INVALID", "视频信息响应格式异常。") from exc
    if not isinstance(payload, dict):
        raise SkillError("FEED_INVALID", "视频信息响应结构异常。")
    if payload.get("errCode", 0) not in (0, "0", None):
        raise SkillError("FEED_REJECTED", "视频号未提供视频信息；请检查链接和保存权限。")
    return payload


def run_download(share_url: str, output_dir: Path, codec: str, wait_seconds: int) -> dict[str, Any]:
    from contextlib import contextmanager

    # This wrapper ensures the visible browser always closes, including on Ctrl+C.
    with contextmanager(_open_context)(wait_seconds) as (context, page):
        token, eid = _parse_source(page, share_url)
        feed = _fetch_feed_in_session(context, token, eid)
        media_url, title = media_from_feed(feed, codec)
        result = download_media(media_url, output_dir)
    return {"status": "success", "title": title, "codec": codec, **result,
            "note": "SHA-256 是下载文件指纹；不代表平台提供了独立的原件校验值。"}


def _batch_inputs(direct_urls: list[str], links_file: Path | None) -> list[str]:
    urls = list(direct_urls)
    if links_file is not None:
        try:
            if links_file.stat().st_size > 65536:
                raise SkillError("LINKS_FILE_TOO_LARGE", "链接清单不能超过 64 KiB。")
            lines = links_file.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            raise SkillError("LINKS_FILE_UNREADABLE", "无法读取 UTF-8 链接清单；请确认文件存在且每行一条链接。") from exc
        urls.extend(line.strip() for line in lines if line.strip())
    if not urls:
        raise SkillError("NO_LINKS", "请提供至少一条视频号分享链接。")
    if len(urls) > MAX_BATCH_LINKS:
        raise SkillError("TOO_MANY_LINKS", f"每批最多 {MAX_BATCH_LINKS} 条链接，请分批处理。")
    return urls


def _prepare_batch(raw_urls: list[str]) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    records: list[dict[str, Any]] = []
    pending: list[tuple[int, str]] = []
    first_seen: dict[str, int] = {}
    for index, raw in enumerate(raw_urls, start=1):
        record: dict[str, Any] = {"index": index}
        try:
            url = validate_share_url(raw)
        except SkillError as exc:
            record.update(status="failed", code=exc.code, message=exc.message)
        else:
            record["source_url"] = url
            if url in first_seen:
                record.update(status="skipped", code="DUPLICATE_LINK",
                              message=f"与第 {first_seen[url]} 条重复，未重复下载。")
            else:
                first_seen[url] = index
                record["status"] = "pending"
                pending.append((index - 1, url))
        records.append(record)
    return records, pending


def _write_batch_report(report: dict[str, Any], output_dir: Path) -> str:
    """Write a local, atomic result list; never include cookies or media tickets."""
    output_dir = Path(output_dir).expanduser().resolve()
    temp_path: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = "wxvideo_batch_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8] + ".json"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".wxvideo_batch_",
                                         suffix=".part", dir=output_dir, delete=False) as file:
            temp_path = Path(file.name)
            json.dump(report, file, ensure_ascii=False, indent=2)
        target = output_dir / filename
        os.replace(temp_path, target)
        temp_path = None
        return str(target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run_batch(raw_urls: list[str], output_dir: Path, codec: str, wait_seconds: int,
              workers: int = 3) -> dict[str, Any]:
    """Parse sequentially in one browser; overlap bounded, independent media downloads."""
    from contextlib import contextmanager

    if not 1 <= workers <= MAX_BATCH_WORKERS:
        raise SkillError("INVALID_WORKERS", f"并行下载数须在 1 到 {MAX_BATCH_WORKERS} 之间。")
    raw_urls = _batch_inputs(raw_urls, None)
    records, pending = _prepare_batch(raw_urls)
    if pending:
        with contextmanager(_open_context)(wait_seconds) as (context, page):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_items = {}
                for position, (index, share_url) in enumerate(pending):
                    try:
                        token, eid = _parse_source(page, share_url)
                        feed = _fetch_feed_in_session(context, token, eid)
                        media_url, title = media_from_feed(feed, codec)
                    except SkillError as exc:
                        records[index].update(status="failed", code=exc.code, message=exc.message)
                        if exc.code in ("RATE_LIMITED", "FEED_HTTP_429"):
                            for remaining_index, _ in pending[position + 1:]:
                                records[remaining_index].update(status="skipped", code="RATE_LIMITED",
                                                                message="平台已限流，未继续请求此链接。")
                            break
                        continue
                    except Exception:
                        records[index].update(status="failed", code="PARSE_UNEXPECTED",
                                              message="解析时发生未预期错误；请单独重试此链接。")
                        continue
                    future = pool.submit(download_media, media_url, output_dir)
                    future_items[future] = (index, title)
                for future in as_completed(future_items):
                    index, title = future_items[future]
                    try:
                        saved = future.result()
                    except SkillError as exc:
                        records[index].update(status="failed", code=exc.code, message=exc.message)
                    except Exception:
                        records[index].update(status="failed", code="DOWNLOAD_UNEXPECTED",
                                              message="下载时发生未预期错误；请单独重试此链接。")
                    else:
                        records[index].update(status="success", title=title, codec=codec, **saved)
    saved_count = sum(item["status"] == "success" for item in records)
    failed_count = sum(item["status"] == "failed" for item in records)
    skipped_count = sum(item["status"] == "skipped" for item in records)
    report = {
        "status": "success" if saved_count == len(records) else ("partial_success" if saved_count else "error"),
        "requested": len(records), "saved": saved_count, "failed": failed_count,
        "skipped": skipped_count, "workers": workers, "items": records,
        "note": "同一批次只登录一次；SHA-256 是下载文件指纹。清单仅保存在本地，不含登录票据。",
    }
    try:
        report["report_path"] = _write_batch_report(report, output_dir)
    except OSError:
        report["report_path"] = None
        report["report_error"] = "结果清单写入失败；已下载的 MP4 仍保留，请按上述路径核对。"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="视频号本地保存工具（仅供有权保存的内容）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查当前环境，不登录、不访问视频号链接")
    download = sub.add_parser("download", help="下载一条有权保存的视频")
    download.add_argument("url")
    download.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads" / "视频号一键存",
                          help="保存目录；默认是当前用户的 Downloads/视频号一键存")
    download.add_argument("--codec", choices=("h264", "h265"), default="h264")
    download.add_argument("--confirm-rights", action="store_true", help=argparse.SUPPRESS)
    download.add_argument("--login-wait", type=int, default=240)
    batch = sub.add_parser("batch", help="共用一次登录，保存多条有权保存的视频")
    batch.add_argument("--url", action="append", default=[], help="一条分享链接；可重复传入，最多 50 条")
    batch.add_argument("--links-file", type=Path, help="UTF-8 文本文件，每行一条链接")
    batch.add_argument("--output-dir", type=Path, default=Path.home() / "Downloads" / "视频号一键存",
                       help="保存目录；默认是当前用户的 Downloads/视频号一键存")
    batch.add_argument("--codec", choices=("h264", "h265"), default="h264")
    batch.add_argument("--workers", type=int, default=3, help="并行文件下载数，1–4；默认 3")
    batch.add_argument("--confirm-rights", action="store_true", help=argparse.SUPPRESS)
    batch.add_argument("--login-wait", type=int, default=240)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = doctor()
        elif args.command == "download":
            share_url = validate_share_url(args.url)
            if not 30 <= args.login_wait <= 600:
                raise SkillError("INVALID_WAIT", "登录等待时间须在 30 到 600 秒之间。")
            result = run_download(share_url, args.output_dir, args.codec, args.login_wait)
        else:
            raw_urls = _batch_inputs(args.url, args.links_file)
            if not 30 <= args.login_wait <= 600:
                raise SkillError("INVALID_WAIT", "登录等待时间须在 30 到 600 秒之间。")
            result = run_batch(raw_urls, args.output_dir, args.codec, args.login_wait, args.workers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in ("success", "partial_success", "ready") else 2
    except SkillError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"status": "error", "code": "CANCELLED", "message": "用户已取消。"}, ensure_ascii=False))
        return 130
    except Exception:
        print(json.dumps({"status": "error", "code": "UNEXPECTED", "message": "发生未预期错误；未输出登录票据。"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
