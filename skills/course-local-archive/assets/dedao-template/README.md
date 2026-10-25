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

默认合并命令仅检查。只有来源声明的全部视频均已验证、原件和结果哈希一致、完整音画解码及独立网页源内容对照通过后，`--apply` 才会更新默认视频。保留的网页源文件列在 `video_web_alternatives`，原始密文保持不变。

构建与检查：

```bash
python3 scripts/build_site.py
python3 scripts/build_course_info.py
python3 scripts/build_resources.py
python3 scripts/audit_archive.py
python3 scripts/finalize_archive.py --apply
python3 scripts/audit_archive.py
```

`finalize_archive.py` 默认仅预览；显式 `--apply` 才更新 `course.json.archive_status` 和来源推导的统计。它要求一小时内通过的审计、同课目录与正文身份、当前输入及交付文件哈希全部匹配，并检查逐讲状态。审计后文件改变时先重新审计。原审计按 SHA 保存在 `raw/finalization-audits/`，完成后再次运行审计以绑定最终清单。

归档完成以实际文件、来源计数、哈希、完整解码和核验报告为准。课程没有提供的媒体与下载失败分开记录；无法访问的外部参考链接保留具体状态。

阅读器基于 [Brclio Design System](https://github.com/Brclio/brclio-design-system)，设计署名 Brclio（黄家宝），页面设计遵循 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。课程与媒体版权归各自作者。
