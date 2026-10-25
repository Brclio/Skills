# 得到整课归档

接口可能变化。字段、身份或状态不符时，先观察当前正常页面或官方公开客户端，不盲目套用旧请求。

## 目录与身份

课程入口 `/course/detail?id=<course_enid>`；章节入口 `/course/article?id=<article_enid>`，其正常 `article/info.class_enid` 或页面课程链接可解析所属课程。

初始化后在课程目录执行：

```text
python3 scripts/fetch_public_catalog.py --course-id <course_enid> --output raw/public
python3 scripts/export_public.py
```

公开接口均 POST：

| 路径 | 请求与响应 |
| --- | --- |
| `/pc/bauhinia/pc/class/info` | `{detail_id:course_enid,is_login:0}` → class_info、chapter_list、讲数和介绍 |
| `/pc/bauhinia/pc/class/free_article_list` | `{detail_id,chapter_id,count:0,max_id:0,max_order_num:0}` → 每章 article_list |

已验证版本 `count:0` 返回整章，仍须核对来源计数。出现分页/截断时，按当前响应分页语义补齐，不能把首批当完整。

## 登录页面内导出

在用户已登录的 `https://www.dedao.cn` 页面，通过获准浏览器工具执行技能 `scripts/export_dedao_in_page.js`。可先设置 `window.__courseArchiveOptions={courseId:<course_enid>}`；辅助脚本也从课程/章节入口解析。文件头定义实际调用与导出名。

正常请求使用当前页面 `csrfToken`、`Content-Type:application/json`、`Xi-DT:web`、`Xi-Csrf-Token`、`credentials:same-origin`。值仅留会话。必要时用 `capture_dedao_read_session.js` 捕获一次真实界面文章读取的请求形状，通过同源只读白名单复用；facade 为 `window.__courseArchiveReadSession`，inspect 只含字段名，结束后 clear。兼容已有 `__dedaoReadSession`，不导出请求头。

| 路径 | 正常调用 |
| --- | --- |
| POST `/pc/bauhinia/pc/article/info` | `{detail_id:article_enid}`；读取购买/访问状态、dd_article_token、article_info |
| GET `/pc/ddarticle/v1/article/get/v2` | 使用当前官方客户端的正文 token、sign、appid、is_new；content 为结构化正文 JSON 字符串 |
| POST `/pc/bauhinia/v1/audio/mutiget_by_alias` | `{get_extra_data:1,ids:exact_alias}` → c.list 中准确 alias 的音频 |
| POST `/media_gate/gate/api/v1/web` | `{media_id_str:article_info.dd_media_id_str,media_alias_id:'',security_token:media_base_info对应视频项.security_token}` → tracks[].formats[] |

`h.c===0` 才成功。HTTP 401/403/429、挑战或访问失败，停止依赖请求并保存 partial。请求保持间隔与超时。正文导出排除秘密 token/key/cookie 值，但保留 `token_version` 等格式字段。正文接口的 appid/sign 必须来自已观察的官方客户端版本，失效时核对源码。

正文 helper 下载 `dedao-course-<courseId>-<complete|partial>.json`，同时把脱敏正文留在 `window.__courseArchiveExport` 供媒体扫描。把成功授权正文导出放入 `raw/authorized-course.json`，运行：

```text
python3 scripts/import_authorized.py raw/authorized-course.json
```

导入器保存原始 info/body/content、各讲 HTML/Markdown、本地图片和报告。未知块/文字差异必须处理；不从别的课程借资料填缺。

## 媒体与合并

执行 `export_dedao_media_in_page.js`，取得完整 Web 视频 formats 和正文额外音频 alias 信息。下载 `dedao-web-media-<id>-<complete|partial>.json` 和 `dedao-extra-audio-<id>-<complete|partial>.json`，分别放入 `raw/authorized-web-media.json`、`raw/authorized-extra-audio.json`。不能把主音频误作正文额外 alias。

```text
python3 scripts/archive_all_audio.py --input raw/authorized-course.json
python3 scripts/archive_all_audio.py --apply
python3 scripts/link_local_audio.py
python3 scripts/link_local_audio.py --check
python3 scripts/archive_video.py
python3 scripts/archive_web_video.py --input raw/authorized-web-media.json
```

以脚本 `--help` 的真实选项执行媒体合并，等相关下载/导入完成后再写共享清单。音频下载器的 `-vn` 不能用来保存视频。

最高画质对照所有实际返回的 resolution 与 FFprobe 宽高。`is_drm:true` 不意味着所有播放线路都加密，下载成功不代表可播。HLS 保存全部分片和本地播放清单；`formats[].size` 可能只是 m3u8 大小，不是最终视频体积。显式保留画面和音轨并 `-c copy`，不重编码。

字幕、原文附件和外部 PDF 按明确来源保存，失效引用单独记录。`review_web_videos.py` 复核所有输出及来源分片，对首/中/末完整解码；`audit_archive.py` 核对当前目录、原文、媒体证据与网页依赖。
