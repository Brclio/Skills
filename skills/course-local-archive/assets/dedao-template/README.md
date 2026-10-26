# 本地课程归档

此目录是一门课程的独立归档。`course-config.json` 绑定来源课程；文稿、媒体、原始响应和核验报告均保存在本目录。不要把另一门课程的数据导入同一目录。

完成导入与构建后可打开 `index.html` 阅读，或查看 `resources.html` 下载本地文稿、音视频及参考资料。网页使用相对路径和内嵌课程数据，不依赖 CDN、在线字体或读取接口。移动时完整保留目录结构。

## 文件与来源

- `course-config.json`：课程身份、来源 URL、来源确认后的计数，以及只读协议参考库配置。
- `course.json`：课程顺序和实际本地文件清单；初始化时没有课程正文。
- `raw/`：原始响应、来源播放清单及核验报告。
- `content/`：Markdown、HTML 和结构化正文。
- `assets/`：实际下载的图片、音视频和附件。
- `web/`：本地阅读器模板、样式和交互。

## 可复用命令

公开目录与介绍（不读取登录信息）：

```bash
python3 scripts/fetch_public_catalog.py
python3 scripts/export_public.py
```

将已授权页面导出的 JSON 放到 `raw/authorized-course.json` 后导入正文与图片：

```bash
python3 scripts/import_authorized.py raw/authorized-course.json
```

音频下载、结果合并和原位播放器关联分别执行：

```bash
python3 scripts/archive_all_audio.py --input raw/authorized-course.json
python3 scripts/archive_all_audio.py --apply
python3 scripts/link_local_audio.py
```

视频原件与正常网页播放源独立归档：

```bash
python3 scripts/archive_video.py
python3 scripts/archive_web_video.py
python3 scripts/archive_web_video.py --apply-only
```

正常媒体接口导出文件使用 `raw/authorized-web-media.json`。网页源脚本只接受完整来源集合；同一讲有多个独立视频时，需要按真实媒体身份扩展映射，不能仅保存其中一段后声称完整。

若用户要求处理已保存的旧格式加密原件，可使用经核验的本地协议参数解析和转换脚本。临时输入只包含被授权课程的媒体令牌，须位于课程归档外、权限为 `0600`，处理后删除；正文、报告和技能目录中不要保留这些值。该脚本只静态读取配置指定的官方参考库，不安装或执行它。当前 AES 后端使用 macOS 系统 CommonCrypto：

```bash
python3 scripts/decrypt_legacy_video.py --token-input /absolute/private-temporary-input.json
python3 scripts/review_legacy_decrypted.py --decode-samples
python3 scripts/apply_decrypted_videos.py
python3 scripts/apply_decrypted_videos.py --apply
```

默认合并命令仅检查。只有真实密文子集及来源明文/密文并集均已验证、原件和结果哈希一致、完整音画解码及独立网页源内容对照通过后，`--apply` 才会更新默认视频。明文、解密、网页及密文独立保存在 `video_plaintext_original`、`video_decrypted_original`、`video_web_alternatives`、`video_encrypted_original`；Web更高画质可默认，同画质优先原件。

课程介绍、字幕及独立视频音轨补齐（默认下载/检查，显式合并）：

```bash
python3 scripts/media_inventory.py
python3 scripts/archive_course_extras.py
python3 scripts/archive_course_extras.py --apply
python3 scripts/media_inventory.py --verify
python3 scripts/link_local_video.py
python3 scripts/link_local_video.py --check
```

HLS 先保存原清单、分片、适用标准AES密钥及本地URI映射，再从本地输入无损封装。主音频与额外 alias 不互换；独立音轨标注派生源。

构建与检查：

```bash
python3 scripts/build_site.py
python3 scripts/build_course_info.py
python3 scripts/build_resources.py
python3 scripts/audit_archive.py --mode fresh --audit-run-id <unique-run-id>
python3 scripts/finalize_archive.py --apply
python3 scripts/audit_archive.py
```

`finalize_archive.py` 默认只读；`--apply` 仅标记 `local_verified`。增量核验只复用当前SHA匹配的完整证据；fresh重新解码全部图片帧及全部音视频流。中断续验只允许显式相同 run ID 加 `--resume-same-run`。核验保留完整stderr，不按课程ID或宽泛错误文本豁免。

使用 `serve.py` 启动支持Range的禁缓存本地服务，在获准浏览器中实测目录、首中末切换、搜索、字号、图片、音视频播放/拖动、字幕、介绍和下载。`observe_reader.py --print-browser-probe` 给出实际已加载payload和JS/CSS版本的被动读取表达式；把真实观察、逐项proofs和工具快照/截图保存在 `raw/qa/`。不能使用合成proof宣称实际UI通过。

```bash
python3 scripts/observe_reader.py --observation raw/qa/observation.json
python3 scripts/verify_delivery.py
```

交付门仅写 `raw/delivery/status.json`，只有 `fully_delivered` 表示本地核验、来源资源清单和实际UI证据均通过。当前页面加载旧数据、缺资源或旧证明时失败，不改核心清单。移动时保留目录结构；无法实测或外部引用失效时如实记录。

阅读器基于 [Brclio Design System](https://github.com/Brclio/brclio-design-system)，设计署名 Brclio（黄家宝），页面设计遵循 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。课程与媒体版权归各自作者。
