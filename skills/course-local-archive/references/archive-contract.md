# 数据与证据契约

所有名称、ID、数量从当前来源推导；每门课独立目录，路径不得逃出课程根。

| 路径 | 内容 |
| --- | --- |
| `course-config.json` | 来源身份、工具版本与适配配置 |
| `course.json` | 来源顺序、正文和当前本地媒体角色 |
| `index.html` / `course-info.html` / `resources.html` | 本地阅读、介绍与下载入口 |
| `content/` | 原文 Markdown/HTML、本地结构化正文及目录 |
| `assets/images/` | 未转码图片、来源 URL 与当前 SHA 清单 |
| `assets/audio/` | 主/额外音频、明确标注的视频音轨派生件 |
| `assets/video/original/` | 明文视频原件 |
| `assets/video/encrypted/` | 原始密文，不修改 |
| `assets/video/decrypted/` | 实际从密文转换的结果 |
| `assets/video/` | 独立 Web 来源默认文件 |
| `assets/subtitles/` / `assets/attachments/` | 来源字幕各版本及明确附件 |
| `raw/` | 原始响应、原始 HLS/分片/适用资源密钥、媒体/核验证据 |
| `raw/delivery/` | 绑定当前归档与实际浏览器观察的独立交付状态 |
| `scripts/` / `web/` | 本地工具、阅读器与构建证据 |

`lessons[]` 的顺序就是阅读顺序，唯一 id、title、section/section_id、order、source_url 来自目录。正文路径相对课程根；正文内嵌链接相对正文文件。源端没有媒体记 `not_applicable`，有源未保存记缺失，不能互换。

默认 `audio[]/video[]` 与 `video_plaintext_original[]`、`video_decrypted_original[]`、`video_web_alternatives[]`、`video_encrypted_original[]` 保持不同角色；下载页按角色展示，正文仅呈现选定播放器。课程级 intro、字幕与视频音轨组件同样进入来源清单和核验。

目录数量不证明正文落盘；哈希不证明内容无漏；FFprobe 不代替完整解码；另一 HLS 片源不证明原密文解密。HLS 必须绑定原清单、URI 映射、各文件当前 SHA、无损输出与全音轨 packet proof。TS 包装与 MP4 容器字节不同应比较实际 H264 VCL/AAC 包，不能仅凭容器 hash 判断损失。

图片元数据告警只有在结构性检查与完整像素解码支持时才可分类为来源告警；保留全部 stderr 和原字节。真正 CRC/像素/编解码错误仍失败。不得按课程、讲 ID 或笼统 stderr 文本豁免。

来源/核心文件、producer 媒体报告、post-final QA/delivery 报告有独立角色。只白名单绑定 producer 报告；不递归把 raw 下全部 QA 纳入核心指纹。阅读器使用稳定内容投影 SHA（不含顶层生命周期字段）、实际内嵌 payload SHA、真实 JS/CSS SHA，避免 finalize 与页面构建循环。

技能包不携带课程正文、用户/设备标识、Cookie、私有媒体 token 或内容 key。官方库仅作有来源和哈希的静态算法参考。私有令牌留归档外 0700/0600 临时位置，清理后不进入 Git、交付包、报告或日志；标准 identity HLS 密钥属于保全资源，仅在对应课程目录受限保存，不打印值。
