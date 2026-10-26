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

先请求 `count:0`，仍核对来源计数与 has_more；有分页时沿当前返回的 ID/order 游标补齐。无 chapter_list 的平铺课程使用已观察的 chapter_id=0 路径。游标不前进、重复身份冲突、数量不符或首批截断均失败，不能把首批当完整。

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
python3 scripts/archive_web_video.py --apply-only
```

以脚本 `--help` 的真实选项执行媒体合并，等相关下载/导入完成后再写共享清单。音频下载器的 `-vn` 不能用来保存视频。

最高画质对照所有实际返回的 resolution 与 FFprobe 宽高。`is_drm:true` 不意味着所有播放线路都加密，下载成功不代表可播。HLS 保存全部分片和本地播放清单；`formats[].size` 可能只是 m3u8 大小，不是最终视频体积。显式保留画面和音轨并 `-c copy`，不重编码。

媒体下载后运行来源资源清单与补充资源工具（见脚本 `--help`），补齐 metadata.class_video、字幕各版本和没有主音频 alias 的独立视频音轨。课程介绍 items/new_items 内 img 也下载并替换本地引用。额外音频导出仍按准确 alias 匹配，不把派生视频音轨塞进主音频身份。

视频合并/解密后运行 `python3 scripts/link_local_video.py` 及 `--check`，保持正文视频原位与来源 media ID 对应；音频同理使用 link_local_audio。字幕、附件和外部 PDF 按明确来源保存，失效引用单独记录。`review_web_videos.py` 独立复核输出/分片与样本，全面核查另用 `audit_archive.py --mode fresh` 解码全部媒体，流程见 [verification-delivery.md](verification-delivery.md)。

## 全部已购与批处理

从当前已购页面枚举课程与分页，保存每课真实 ID/标题/来源 URL 和 inventory 完整性；不能将本地已有文件夹当成已购总清单。课程清单枚举未完成时总任务保持 partial。每课独立来源导出与目录、独立恢复点；付费访问仍仅使用当前已登录获准页面。

浏览器 helper 以获准工具支持的页面函数执行，不能把字符串 eval、直接读取浏览器内部状态、另起未授权 CDP/Playwright 作为连接超时的绕路。连接恢复后先读取一个小状态确认，再做有界批次和检查点。下载/验证可跨课并行，每课清单单写者；本地 batch runner 的界限与交付要求见 [verification-delivery.md](verification-delivery.md)。
