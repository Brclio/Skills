# CodexSkills

这是个人维护的 Codex Skills 仓库，用来沉淀可复用的 Codex 工作流。

公开仓库地址：

- 个人仓库：[AndersonHJB/CodexSkills](https://github.com/AndersonHJB/CodexSkills)
- 组织仓库：[Brclio/Skills](https://github.com/Brclio/Skills)

本次同步保留 Git 提交历史和全部分支、标签；后续更新需分别推送，两个仓库不会自动同步。

## Skills 列表

- `course-local-archive`：将已登录、已购或获授权的课程完整保存为原文 Markdown、HTML、图片、音频、视频与离线阅读网站；保留网页片源、原始 HLS 清单与分片、加密原件和经过验证的实际解密版本，附完整性审计。内置得到适配及旧版 v1 MP4 解密流程；其他平台按已验证适配处理。安装与调用见下方「课程完整离线归档」，工作流见 [`skills/course-local-archive/SKILL.md`](skills/course-local-archive/SKILL.md)。
- `zhixing-shipinhao-yijiancun`：视频号一键存免邀请码版，将本人发布或已获授权的视频号链接保存为本地 MP4；支持单条、最多 50 条批量、去重、有限并发和结果清单。无需作者侧激活或在线核验，首次仍需本人扫码登录腾讯元宝。安装、调用、排错与实测边界见 [`skills/zhixing-shipinhao-yijiancun/README.md`](skills/zhixing-shipinhao-yijiancun/README.md)。
- `blindbox-ip-skill-4styles`：将个人或品牌描述转化为可复用的内容配图角色，提供治愈绘本手绘、极简符号卡通、盲盒潮玩公仔和日常扁平漫画四种画风；交付角色价值观、视觉 DNA、正面图、三视图、角色参考板、分层提示词和一致性测试图。使用说明见 [`skills/blindbox-ip-skill-4styles/README.md`](skills/blindbox-ip-skill-4styles/README.md)，授权范围见该目录下的 `LICENSE`。
- `generate-personal-ip-avatars`：为零基础用户打造可配置个人 IP 盲盒；支持随机与浅色主题、8 张行业全身形象、官方高校/机构 VI 配色扩展、动作、八角度、24 种情绪、总拼图和离线 HTML 选择画廊。没有明确功能控制时默认全部开启。
- `wechat-article-pipeline`：微信公众号文章流水线，支持文章重写、吸金标题与摘要、教程插图、公众号封面、图片上传 PicGoImage、Markdown 图片链接替换、文章归档、公众号可复制 HTML 排版。
- `xiaohongshu-post-imagegen`：小红书帖子图生成工作流，支持按主题生成多张轮播插图、图片内中文文案、整帖统一发布文案、标题备选、互动引导和标签组合。
- `wechat-chat-to-xiaohongshu`：微信聊天截图转小红书工作流，支持截图排序、OCR、证据核对、严格匿名化、1080×1440 轮播排版、标题正文标签和隐私质检。
- `build-wechat-sticker-pack`：从一张或多张参考图片，全流程生成 20 张独立 Q 版微信表情、发布横幅/封面/聊天图标、填写文案、含义词、QA 报告、原图归档及双压缩包。
- `cola-voice-delivery`：使用 ListenHub 将文本或播客转成晓曼与 Cola 两种中文女生声，按输入长度动态分段，交付每个片段和两种音声的完整拼接 MP3。
- `bornforthis-illustrations`：为中文文章生成与 Esther／不二插画相同蜡笔绘本视觉体系的 Bornforthis 16:9 正文配图；内置 2 张身份锚点与 14 张完成度样例，固定短蓝碎发、外扩圆耳、纸白圆方脸和黄色圆脸颊身份，服装、耳机等配饰随场景变化。安装与使用见 [`skills/bornforthis-illustrations/README.md`](skills/bornforthis-illustrations/README.md)。
- `video-publish-pipeline`：给一个视频即可交付可核验的完整五平台发布包：先确认开场姓名/品牌，再制作居中中英字幕、最左上章节卡、置底分段进度条与源规格成片；封面按当前内容独立创作 16:9、3:4、4:3 三种构图并锁定暖纸张拼贴视觉；同时联网研究同题市场，输出微信视频号、哔哩哔哩、小红书、抖音、YouTube 的推荐标题、A/B 标题、原生文案、标签、章节、置顶评论、封面映射和来源齐全的 Markdown，并分别完成发布素材与整包 QA。
- `video-platform-publishing`：参考同题与同形式视频的市场表现和封面规律，为微信视频号、抖音、哔哩哔哩、YouTube、小红书生成平台适配的封面、标题、正文、标签、置顶评论和发布提醒；支持单独使用，也供 `video-publish-pipeline` 调用。工作流见 [`skills/video-platform-publishing/SKILL.md`](skills/video-platform-publishing/SKILL.md)。
- `short-drama-pack`：给一个剧本，一次性交付 AI 短剧的全部文字物料，每样都是独立文件。默认国漫 3D 半写实、电影宽银幕 21:9。内容包括：
  - 角色多视图提示词、道具图。
  - 可交给出图 AI 按编号批量生成的场景提示词，以及场景分组与父子关联表。
  - 角色音色与逐句表演指令。
  - 按视频平台「片段 → 分镜」格式写好的分镜脚本、后期清单。
  - 一键复制的离线 HTML 查看页。

  所有内容出自同一份数据，渲染时自动核对引用名、台词覆盖、时长和连续性。使用说明见 [`skills/short-drama-pack/README.md`](skills/short-drama-pack/README.md)。

## 课程完整离线归档

`course-local-archive` 适合提供一个课程或章节链接后，保存整门课程的原文与实际素材。每门课使用独立目录，支持同课续存，保留原始正文字符串、Markdown、HTML、图片、全部音轨、视频与附件，并生成带搜索和本地播放器的离线阅读器。

当前模板 v2 按来源资源清单核对正文与元数据图片、课程介绍媒体、主/额外音频、视频独立音轨、字幕各版本和明确附件，支持已购课程逐课独立归档及本地批次续验。字幕进入本地播放器与下载页，课程介绍中的内嵌图片同样本地化。

遇到视频时选择来源实际返回的最高画质，完整保留原始 HLS 清单、分片、适用的标准 AES 资源密钥及本地 URI 映射，再无损封装。明文原件、加密原件、经过验证的实际解密 MP4 和独立网页源分别保存，避免覆盖；混合明密课程只对真实密文子集解密，再核对完整来源集合。

全面复核使用 fresh 模式完整解码图片全部帧及全部音视频流；同轮中断可显式续验。`local_verified` 仅表示本地通过，实际加载的数据、JS/CSS 版本及浏览器操作证据通过独立交付门后才标记 `fully_delivered`。详细步骤见 [核验与交付流程](skills/course-local-archive/references/verification-delivery.md)。

让 Codex 安装：

```text
请从 https://github.com/Brclio/Skills 安装 skills/course-local-archive，
放入 ~/.codex/skills/course-local-archive，并检查 Skill 与媒体工具依赖。
```

安装后在下一轮对话调用：

```text
使用 $course-local-archive 完整归档这个课程：<课程链接>。
保留所有原始素材、加密原件及可验证的实际解密版本，生成 Markdown 和离线网页。
```

需要当前账号正常具有课程访问权限；登录及媒体授权材料只供本次会话使用，不存入技能或公开归档。离线建站与基础审计使用 Python 3，媒体保存和核验需要 FFmpeg/FFprobe。当前实际验证的旧 v1 解密原语采用 macOS CommonCrypto；其他系统、加密版本和平台须验证对应适配。极客时间通过同级已安装的 `geekbang-course-archive` 专门技能处理。

技能包含浏览器采集助手、动态课程初始化器、下载/解密/核验脚本与离线网站模板。官方原生库仅作为带来源和 SHA 的静态算法参考。完整步骤与边界见 [得到归档流程](skills/course-local-archive/references/dedao-workflow.md)、[旧 v1 解密流程](skills/course-local-archive/references/dedao-legacy-decryption.md) 和 [数据与证据契约](skills/course-local-archive/references/archive-contract.md)。

## 视频号一键存（免邀请码）

`zhixing-shipinhao-yijiancun` 面向 macOS 与 Windows 10/11，使用 Python 3.10+、Playwright 和本机 Chrome/Edge。安装后，将本人发布或已获授权的 `https://weixin.qq.com/sph/...` 分享链接发给 Codex 或 WorkBuddy，即可由助手完成检查、解析和本地保存；需要登录时由本人在专用窗口扫码。

直接发送下面的提示词即可让 Codex 安装：

```text
请从 https://github.com/Brclio/Skills 安装 skills/zhixing-shipinhao-yijiancun，
放入 ~/.codex/skills/zhixing-shipinhao-yijiancun，并运行当前系统的 setup 脚本检查依赖。
```

安装后在新会话中发送：

```text
使用 $zhixing-shipinhao-yijiancun 下载下面这条我已获授权的视频号视频，保存到默认目录：
<完整分享链接>
```

默认保存到 `Downloads/视频号一键存`。批量任务复用同一登录，每批最多 50 条，默认 3 路文件下载，并生成逐条结果清单。完整的两平台安装命令、批量调用、隐私目录与故障排查见 [中文说明](skills/zhixing-shipinhao-yijiancun/README.md)。

本版本已移除邀请码和作者服务器依赖；解析仍依赖腾讯网页内部接口。2026-10-22 已在 macOS 完成真实单条下载与完整解码检查；Windows 和真实批量下载尚未完成实测。来源和修改范围见 [来源说明](skills/zhixing-shipinhao-yijiancun/references/provenance.md)。

## 个人 IP 角色批量生成 Skill

`generate-personal-ip-avatars` 主要面向没有绘画基础、没有艺术细胞、不会配色，但想拥有专属 IP 角色的用户。它会从一张清晰人物参考照中提取脸型、五官、发长、发质、轮廓、年龄感、姿态和真实配饰，再把这些特征转译为统一手绘语言的方形个人 IP。

一次生成大量方案并不是浪费生成能力，而是把插画设计中的试色、动作提案、行业全身形象、角色转面和情绪设计一次性可视化。默认无机构输入时生成 459 张：11 套完整主题共 451 张，加 8 张行业全身 IP。用户提供官方高校、机构或品牌 VI 后，默认再追加 8 套完整系列、增加 328 张；一套官方 VI 输入的默认总数为 787。只有用户明确给出功能开关或开启/关闭指令时才进入控制模式。完整中文教程和可复制配置见 [`skills/generate-personal-ip-avatars/README.md`](skills/generate-personal-ip-avatars/README.md)。

主要能力：

- 自动分析人物的可见呈现线索，但不会把外观推断表述成确定性别，也不要求用户自报性别；
- 同时适用于男性、女性、中性、非二元或外观线索不明确的人物照片；
- 线索不明确时自动采用 `presentation-neutral` 中性设计，不擅自添加蝴蝶结、领带、首饰或其他性别化元素；
- 内置参考图只约束蜡笔质感、稚拙比例、白色剪纸轮廓和随手涂鸦等视觉语言，不会覆盖用户的身份、发型、配饰或主题色；
- 黄色与钴蓝只属于经典基准组，不会被误判成用户偏好；完整模式每次都会随机抽取新的 8 套主题色，形成真正的主题盲盒；
- 用户说明喜欢的颜色或主题时，会在随机 8 套之后追加对应主题，不会替换随机盲盒；默认全开时每个追加主题增加 41 张，关闭模块后按实际启用数量计算；
- 每个主题默认包含 8 张动作设计、1 张正面全身、8 张不同角度和 24 张完整情绪图；
- 默认额外生成 8 张不同行业的装饰全身 IP，用服装、姿态、道具和涂鸦体现行业，不冒充真实资质；
- 用户提供官方高校、机构或品牌 VI 时，核对官方色值后默认追加 8 套完整主题；只借鉴颜色与抽象语言，不默认复制 Logo、校徽或标准字；
- 经典主题、随机主题、浅色主题、行业全身、机构品牌、基础动作、正面全身、八角度、情绪包、分组拼图、全部拼图和 HTML 选择页均可独立开启或关闭；
- 已有经典 8 张时先冻结基准，新增内容写入独立目录，不覆盖、不重命名、不重新压缩原图；
- 每张图独立生成，并使用 ImageMagick 制作模块/主题总览和包含全部交付原图的最终拼图；
- 默认生成带 Bornforthis AI实验室 Logo 与一对一招生信息的离线 HTML 画廊，支持搜索、筛选、收藏、淘汰、放大预览、浏览器持久保存申请和 JSON 选择清单导出；
- 最终保存独立原图、各组总览、功能配置 `FEATURES.json`、完整 `PROMPTS.md` 和可审计的 `QA.md`。

安装：

```bash
git clone https://github.com/AndersonHJB/CodexSkills.git
mkdir -p ~/.codex/skills/generate-personal-ip-avatars
rsync -a CodexSkills/skills/generate-personal-ip-avatars/ ~/.codex/skills/generate-personal-ip-avatars/
```

安装完成后重启 Codex 或新建会话，上传一张清晰的人物参考图并发送：

```text
使用 $generate-personal-ip-avatars，根据这张人物参考图设计完整个人 IP 系列。
默认启用全部功能：保留经典主题并随机抽取 8 套主题色；每个主题生成 8 张动作设计、1 张正面全身、8 张不同角度和 24 张情绪图。
请自动适配人物呈现，不要从风格参考图复制不属于这个人的性别特征、配饰或颜色偏好。
最后把全部原图拼成一张总览图，方便我直接比较和挑选。
```

默认全开且没有机构 VI 输入时生成 459 张；提供一套机构 VI 并使用默认 8 套扩展时生成 787 张。若只需要原来的基础 72 张，需要关闭浅色、行业、机构品牌、正面全身、八角度和情绪包；若只想测试一个主题的完整系统，可关闭其他主题与行业组，生成 41 张。详细开关模板请直接复制专属中文 README 中的示例。

从人物与画风 DNA、首轮 8 稿、完整角色系统到 Skill 结构、测试、安装和 HTML 选图的零基础教程，见 [`zero-to-personal-ip-skill-tutorial.md`](skills/generate-personal-ip-avatars/references/zero-to-personal-ip-skill-tutorial.md)。

拼图功能依赖 ImageMagick。启用“分组拼图”或“全部图片拼图”时，请确保系统可以运行 `magick`；如未安装，可先关闭两个拼图开关，其余独立图片仍可正常生成。

## Bornforthis 正文配图 Skill

`bornforthis-illustrations` 用于把中文文章中的关键判断、流程、结构、状态和隐喻转化为 16:9 蜡笔手绘正文配图。视觉上保持纯白背景、可见斜线笔触、深蓝晃动描边、少量中文短标注与大量留白；Bornforthis 必须亲自参与核心动作。

角色身份稳定为钴蓝短刺发、外扩圆耳、纸白圆方脸、黄色圆脸颊和极简蓝色五官。衣服、耳机、鞋、相机、包和书都不是固定设定，会随每张图的语义重新设计。Skill 内置 2 张身份锚点和 14 张完成度校准图，并明确禁止把这些图片当作服装或构图模板。

安装：

```bash
git clone https://github.com/AndersonHJB/CodexSkills.git
mkdir -p ~/.codex/skills/bornforthis-illustrations
rsync -a --delete CodexSkills/skills/bornforthis-illustrations/ ~/.codex/skills/bornforthis-illustrations/
```

安装后新建 Codex 会话，并发送：

```text
使用 $bornforthis-illustrations，为这篇中文文章设计并生成 Bornforthis 蜡笔手绘正文配图。服装与配饰根据每张图的主题变化，不要默认添加耳机。
```

完整说明、参考图机制和更多调用示例见 [`skills/bornforthis-illustrations/README.md`](skills/bornforthis-illustrations/README.md)。

## 微信聊天截图转小红书 Skill

`wechat-chat-to-xiaohongshu` 适合把私教沟通、客户咨询、课程规划等微信聊天截图整理成可发布的小红书帖子。默认保留真实截图作为证据主体，不让图片模型重绘聊天文字。

主要能力：

- 自动盘点截图并结合时间、文件名和对话连续性重建顺序；
- 使用 macOS Vision OCR 建立可检索文本，同时要求逐图核对；
- 建立证据台账，区分双方表述、已核实事实、编辑推断和不可发布内容；
- 默认隐藏昵称、头像、账号、电话、链接、二维码、交易与排课信息；
- 确定性生成 1080×1440 轮播图、总览图、标题、统一正文、标签和图片顺序；
- 最终 OCR 扫描隐私屏蔽词，并生成可审计的质检报告；
- 保持原始素材目录和文件字节不变。

安装后，给出包含原始微信截图的文件夹路径并发送：

```text
使用 $wechat-chat-to-xiaohongshu，把这个微信聊天截图文件夹做成可发布的小红书帖子：
/绝对路径/聊天截图文件夹

请自动完成聊天排序、OCR、隐私脱敏、轮播设计与生成，并提供标题、整帖文案、标签、图片顺序和质检报告。
```

只有 Finder 文件列表截图无法读取聊天内容，需要提供实际截图文件或文件夹路径。

## 微信表情包全流程 Skill

`build-wechat-sticker-pack` 适合希望“只提供参考图片，其余交给 Codex”的场景。每次固定生成 20 张独立表情，但文案、动作、表情与道具会结合当前人物和主题动态规划，不会机械复用一套内容。

主要能力：

- 原始参考图片逐字节保留，保留原文件名、扩展名、EXIF，并写入 SHA-256；
- 先生成无字角色锚点，再通过 20 次独立图片生成保持人物一致性；
- 图片生成阶段不直接生成中文，最终文字由本地确定性排版，降低错字风险；
- 输出 20 张 `240×240` 独立表情，以及微信发布所需横幅、透明封面和聊天图标；
- 自动生成名称、介绍、版权、20 个含义词、AI/版权声明和可直接填写的发布材料；
- 严格检查数量、尺寸、大小、透明度、重复图、文字、来源哈希、人工复核与版权门禁；
- 同时生成仅供上传的 submission ZIP，以及包含原图、源图、提示词、生成账本和 QA 的 full archive ZIP。

安装后，在新的 Codex 会话中上传参考图片并发送：

```text
使用 $build-wechat-sticker-pack，根据这张参考图片生成完整的20张微信表情及发布提交包。
```

首次使用前，请把 `~/.codex/skills/build-wechat-sticker-pack/assets/creator-profile.json` 中的 `copyright_holder` 改成真实提交者或版权方名称。公开模板不会预填他人的版权身份；设置一次后，后续自有素材通常只需提供参考图片。

也可以附加风格或主题要求：

```text
使用 $build-wechat-sticker-pack，根据这些参考图片制作一套校园日常主题的20张微信表情，整体软萌、白色背景，并生成完整发布材料。
```

正常完成后会得到：

```text
00-reference-originals/       原图无损归档与哈希
01-plan/                      20张内容计划、人物/风格设定、冻结提示词
02-source-assets/             角色锚点、20张高分源图、发布素材、生成账本
03-submission/                可提交表情、发布图片、填写材料、QA
04-preview/                   内部审阅总览图
archives/*-submission.zip     仅上传材料
archives/*-full-archive.zip   原图与完整生产资料
```

注意：full archive 会保留原始图片字节，因此可能保留 EXIF/GPS；公开提交或分享时优先使用 submission ZIP。真人、第三方图片、品牌角色或版权不明素材会触发授权确认，未确认时只生成明确标记的草稿存档，不生成可提交 ZIP。

## Cola 双音声长文朗读 Skill

`cola-voice-delivery` 适合把一份文本、文本文件或播客内容直接生成两套中文朗读音频。调用 Skill 并提供内容即可，Skill 会自行读取、转写（播客音频时）、动态分段、生成、下载、拼接和核查，不要求手动拆分或合并。

固定使用两个 ListenHub 音色：

- 晓曼：`chat-girl-105-cn`
- Cola：`chatb812x-500306f5`

它会根据文本长度和章节边界动态决定片段数量，不假设固定 11 段。每个音色都会交付：

- 全部有序 MP3 片段；
- 一个独立命名的完整拼接 MP3；
- 生成状态、下载结果、音频时长和文件大小核查。

简单调用：

```text
使用 $cola-voice-delivery，把这个文本生成完整音频：
/绝对路径/播客稿.txt

请交付晓曼和 Cola 两个音声的全部片段，以及各自的完整拼接音频。
```

也可以直接附带文本内容。长文本会按章节或自然段动态拆分；如果 ListenHub 的输入接口要求 HTML，Skill 会准备 HTML 备用输入，失败时回退到逐段直接文本生成。

## AI 短剧制作包 Skill

`short-drama-pack` 把一个剧本一次性做成 AI 视频生产包：角色、道具、场景、场景关联、音色、分镜、后期，各一个独立文件，外加一个离线 HTML 查看页。分镜按视频平台的「片段 → 分镜」格式输出，每个片段不超过 30 秒、最多 5 个分镜，片段可以整段粘贴。

安装：

```bash
git clone https://github.com/AndersonHJB/CodexSkills.git
mkdir -p ~/.codex/skills/short-drama-pack
rsync -a --delete CodexSkills/skills/short-drama-pack/ ~/.codex/skills/short-drama-pack/
```

安装后新建 Codex 会话，并发送：

```text
使用 $short-drama-pack，把这个剧本做成完整的制作包：/path/to/剧本.txt
风格用国漫3D半写实，画幅 21:9。
```

只需要 Python 3，没有第三方依赖。交付文件、校验项和修改方法见 [`skills/short-drama-pack/README.md`](skills/short-drama-pack/README.md)。

## 目录结构

```text
CodexSkills/
├── README.md
└── skills/
    └── <skill-name>/
        ├── SKILL.md
        ├── agents/
        ├── assets/
        ├── references/
        └── scripts/
```

每个 Skill 都放在 `skills/<skill-name>/` 目录下。安装到本机时，需要复制到：

```text
~/.codex/skills/<skill-name>/
```

## 准备工作

本机需要有 `git` 和 `rsync`。macOS 通常自带。

先克隆仓库：

```bash
git clone https://github.com/AndersonHJB/CodexSkills.git
cd CodexSkills
```

## 直接安装 Cola Skill

macOS 或 Linux 用户可以直接复制下面的命令。它会克隆或更新仓库，只安装 `cola-voice-delivery`，不会覆盖其他 Skill：

```bash
repo_dir="${TMPDIR:-/tmp}/CodexSkills"
if [ -d "$repo_dir/.git" ]; then git -C "$repo_dir" pull --ff-only; else git clone https://github.com/AndersonHJB/CodexSkills.git "$repo_dir"; fi
mkdir -p "$HOME/.codex/skills/cola-voice-delivery"
rsync -a "$repo_dir/skills/cola-voice-delivery/" "$HOME/.codex/skills/cola-voice-delivery/"
test -f "$HOME/.codex/skills/cola-voice-delivery/SKILL.md" && echo "cola-voice-delivery installed"
```

安装完成后，重启 Codex 或新建一个会话，让 Skill 列表重新加载。

## 让 Codex 自动安装

如果你正在使用 Codex，也可以不手动敲命令，直接把下面的提示词发给 Codex，让它帮你安装。

### 让 Codex 单独安装一个 Skill

把这段发给 Codex：

```text
请帮我从 https://github.com/AndersonHJB/CodexSkills 安装 wechat-article-pipeline 这个 Codex Skill。
要求：
1. 克隆或更新这个仓库。
2. 将 skills/wechat-article-pipeline/ 复制到 ~/.codex/skills/wechat-article-pipeline/。
3. 如果本地已存在同名 Skill，请先告诉我会覆盖哪些文件，再执行覆盖。
4. 安装后检查 ~/.codex/skills/wechat-article-pipeline/SKILL.md 是否存在。
5. 最后告诉我是否需要重启 Codex 或新建会话。
```

安装小红书帖子图生成 Skill 时，把 Skill 名称换成：

```text
xiaohongshu-post-imagegen
```

安装微信聊天截图转小红书 Skill 时，把 Skill 名称换成：

```text
wechat-chat-to-xiaohongshu
```

安装微信表情包 Skill 时，把上面的 `wechat-article-pipeline` 替换为 `build-wechat-sticker-pack` 即可。

安装个人 IP 角色批量生成 Skill 时，把 Skill 名称替换为：

```text
generate-personal-ip-avatars
```

安装 Cola 双音声长文朗读 Skill 时，把上面的 Skill 名称替换为：

```text
cola-voice-delivery
```

也可以直接发送：

```text
请从 https://github.com/AndersonHJB/CodexSkills 安装 cola-voice-delivery。
只安装这个 Skill，不要影响 ~/.codex/skills 下的其他 Skill。
安装后检查 ~/.codex/skills/cola-voice-delivery/SKILL.md 是否存在，并提醒我新建会话使它生效。
```

### 让 Codex 批量安装全部 Skills

把这段发给 Codex：

```text
请帮我从 https://github.com/AndersonHJB/CodexSkills 批量安装全部 Codex Skills。
要求：
1. 克隆或更新这个仓库。
2. 遍历仓库里的 skills/*/ 目录。
3. 将每个 Skill 分别复制到 ~/.codex/skills/<skill-name>/。
4. 如果本地已有同名 Skill，请先列出将被覆盖的 Skill 名称，再执行覆盖。
5. 安装后列出 ~/.codex/skills 下已经安装的 Skills。
6. 最后提醒我重启 Codex 或新建会话，让 Skills 生效。
```

如果你希望 Codex 直接覆盖本地同名 Skill，也可以在提示词里加一句：

```text
允许直接覆盖本地同名 Skill，不需要逐个确认。
```

## 单独安装一个 Skill

以 `wechat-article-pipeline` 为例：

```bash
mkdir -p ~/.codex/skills/wechat-article-pipeline
rsync -a skills/wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

安装 `xiaohongshu-post-imagegen`：

```bash
mkdir -p ~/.codex/skills/xiaohongshu-post-imagegen
rsync -a skills/xiaohongshu-post-imagegen/ ~/.codex/skills/xiaohongshu-post-imagegen/
```

安装 `wechat-chat-to-xiaohongshu`：

```bash
mkdir -p ~/.codex/skills/wechat-chat-to-xiaohongshu
rsync -a skills/wechat-chat-to-xiaohongshu/ ~/.codex/skills/wechat-chat-to-xiaohongshu/
```

安装微信表情包 Skill：

```bash
mkdir -p ~/.codex/skills/build-wechat-sticker-pack
rsync -a skills/build-wechat-sticker-pack/ ~/.codex/skills/build-wechat-sticker-pack/
```

安装个人 IP 角色批量生成 Skill：

```bash
mkdir -p ~/.codex/skills/generate-personal-ip-avatars
rsync -a skills/generate-personal-ip-avatars/ ~/.codex/skills/generate-personal-ip-avatars/
```

安装 Cola 双音声长文朗读 Skill：

```bash
mkdir -p ~/.codex/skills/cola-voice-delivery
rsync -a skills/cola-voice-delivery/ ~/.codex/skills/cola-voice-delivery/
```

安装视频平台发布物料 Skill：

```bash
mkdir -p ~/.codex/skills/video-platform-publishing
rsync -a skills/video-platform-publishing/ ~/.codex/skills/video-platform-publishing/
```

安装后，重启 Codex 或新建一个会话，让 Skill 列表重新加载。

## 批量安装全部 Skills

如果你想一次安装仓库里的全部 Skills：

```bash
mkdir -p ~/.codex/skills
for skill_dir in skills/*/; do
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$HOME/.codex/skills/$skill_name"
  rsync -a "$skill_dir" "$HOME/.codex/skills/$skill_name/"
done
```

安装后，重启 Codex 或新建一个会话。

## 覆盖式更新已安装 Skills

如果你已经安装过，想用仓库版本覆盖本地版本：

```bash
git pull
rsync -a --delete skills/wechat-article-pipeline/ ~/.codex/skills/wechat-article-pipeline/
```

批量覆盖更新全部 Skills：

```bash
git pull
for skill_dir in skills/*/; do
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$HOME/.codex/skills/$skill_name"
  rsync -a --delete "$skill_dir" "$HOME/.codex/skills/$skill_name/"
done
```

注意：`--delete` 会删除本地目标目录里仓库不存在的文件。如果你在本地改过 Skill，先备份或提交到自己的仓库。

## 验证安装结果

检查本地是否已经安装：

```bash
ls ~/.codex/skills
ls ~/.codex/skills/wechat-article-pipeline
ls ~/.codex/skills/xiaohongshu-post-imagegen
ls ~/.codex/skills/wechat-chat-to-xiaohongshu
ls ~/.codex/skills/build-wechat-sticker-pack
ls ~/.codex/skills/generate-personal-ip-avatars
```

也可以检查 Skill 文件是否存在：

```bash
test -f ~/.codex/skills/wechat-article-pipeline/SKILL.md && echo "installed"
test -f ~/.codex/skills/xiaohongshu-post-imagegen/SKILL.md && echo "installed"
test -f ~/.codex/skills/wechat-chat-to-xiaohongshu/SKILL.md && echo "installed"
test -f ~/.codex/skills/build-wechat-sticker-pack/SKILL.md && echo "installed"
test -f ~/.codex/skills/generate-personal-ip-avatars/SKILL.md && echo "installed"
```

在 Codex 中新建会话后，如果任务匹配 Skill 的描述，Codex 会自动使用对应 Skill。

## 卸载一个 Skill

```bash
rm -rf ~/.codex/skills/wechat-article-pipeline
```

卸载 `xiaohongshu-post-imagegen`：

```bash
rm -rf ~/.codex/skills/xiaohongshu-post-imagegen
```

卸载 `wechat-chat-to-xiaohongshu`：

```bash
rm -rf ~/.codex/skills/wechat-chat-to-xiaohongshu
```

卸载 `build-wechat-sticker-pack`：

```bash
rm -rf ~/.codex/skills/build-wechat-sticker-pack
```

卸载后重启 Codex 或新建会话。

## 维护者：新增或更新 Skill

从本机 Codex Skills 目录同步到仓库：

```bash
rsync -a --delete ~/.codex/skills/<skill-name>/ skills/<skill-name>/
git add skills/<skill-name>
git commit -m "Update <skill-name> skill"
git push
```

新增 Skill 时：

```bash
mkdir -p skills/<skill-name>
rsync -a ~/.codex/skills/<skill-name>/ skills/<skill-name>/
git add skills/<skill-name> README.md
git commit -m "Add <skill-name> skill"
git push
```
