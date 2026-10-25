# 数据与证据契约

每门课程独立存储，所有名称、ID、数量来自当前来源。

```text
course-config.json       当前课程身份与适配/工具配置
course.json              原始顺序、正文和本地媒体状态
index.html               内嵌课程数据的阅读入口
course-info.html         课程与讲师介绍
resources.html           全部本地文件与引用状态
content/                 各讲 Markdown/HTML、本地结构化正文、目录
assets/images/           图片和哈希清单
assets/audio/            实际可播音频
assets/video/            正常 Web 来源 MP4
assets/video/encrypted/  原始加密文件，保留字节
assets/video/decrypted/  从上述密文实际解密的 MP4
assets/attachments/      明确附件及成功/失败清单
raw/                     原始响应、全部 HLS 原件、核验报告
scripts/                 该课程的处理与审计工具
web/                     本地样式、脚本、模板与构建报告
```

`course.json.lessons[]` 至少有唯一 id、原始 title、section/section_id、order、source_url；来源提供时保留 enid。正文使用 markdown_path/html_path，媒体使用 `audio[]/video[]:{path,label,...}`。路径相对课程根；正文内链接相对其源文件；路径不得逃出课程目录。

lessons 数组就是阅读顺序。imported 仅用于真实非空正文；媒体 complete/partial/not_applicable 分别表示已验证、有缺失/失败、来源明确没有。解密默认 video[] 与保留的 video_web_alternatives[] 都可下载，主页面只渲染一份播放器。

证据各有边界：目录数不证明正文落盘；哈希不证明内容无漏；FFprobe 不代替全流完整解码；HLS 另一片源不代替原密文解密。实际解密报告绑定输入/输出路径与 SHA、算法版本来源、原件未改和严格解码证据，独立工具再次读取当前文件。

H264 VCL 图片 NAL 与 AAC 压缩流对照比容器字节更准确：TS 的 AUD/SPS/PPS/SEI 包装可能导致原 streamhash 不同。不得因此伪报画质损失，也不得忽略真正画面/音轨差异。

技能包不携带课程正文、用户/设备标识、Cookie、媒体 token 或内容 key。官方库仅作有来源和哈希的只读算法参考，不安装运行整个 App。私有输入不进入归档/Git/压缩包/日志，处理后删除。
