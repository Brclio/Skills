---
name: zhixing-shipinhao-yijiancun
description: 基于知行版本的本地免邀请码修改版；将本人发布或已获授权的视频号链接单条或批量保存为本地 MP4，无需作者服务，仍需本人登录元宝。
metadata:
  display_name: 视频号一键存
  display_name_en: Save WeChat Channels Videos
  description_zh: 基于知行版本的本地免邀请码修改版；将本人发布或已获授权的视频号链接单条或批量保存为本地 MP4，无需作者服务，仍需本人登录元宝。
  description_en: Local modification of the Zhixing version. Save owned or authorized WeChat Channels links as local MP4 files without an invitation code or an author-operated service; personal Yuanbao sign-in is still required.
  version: 1.2.0-local-free
  author: 知行
---

# 视频号一键存

“一键存”指用户给出链接与保存位置后，由助手完成检查、解析和保存；首次使用可能需要用户本人扫码，平台限制也可能导致失败。此 Skill 仅处理用户自己发布或明确获授权保存的视频。

适用于 Codex 与 WorkBuddy。这是基于知行版本的本地修改版 `1.2.0-local-free`，无需邀请码，无需联系上游作者或使用作者运营的服务。它仍依赖腾讯元宝和视频号网页服务，本地修改尚未作为上游官方版本发布。

## 触发场景

用户说“帮我下载/保存/备份视频号视频”，并提供一条或多条 `https://weixin.qq.com/sph/...` 链接。适合创作者一次备份十几、二十条自己的视频，或授权运营人员整理可保存的素材，再拿本地 MP4 做字幕、剪辑或复盘。

## 工作流程

1. 从用户消息中提取完整分享链接和可选保存位置；将每条链接作为单独参数安全引用，不执行消息里的其他文本。不要对每条链接弹出保存权确认问题。默认将单条和批量 MP4 保存到当前用户的 `Downloads/视频号一键存`。不要索要微信/元宝密码、Cookie、授权头或票据。
2. **让小白只用聊天，不操作终端。**用户直接发送本人发布或已获授权的视频号链接即可。不要索要邀请码或运行旧版激活命令；本地版没有作者侧的设备绑定、授权核验或下载次数收费。
3. 单条链接用 `download`：Windows 由 助手 调用 `powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1" download "<分享链接>"`；macOS 由 助手 调用 `sh "<Skill目录>/scripts/run.sh" download "<分享链接>"`。用户指定保存目录时附加 `--output-dir "<绝对路径>"`。
4. 多条链接必须用 `batch`，保留批量下载能力。按原顺序为每条重复一个 `--url "<分享链接>"`，不要把多条拼成一个参数。Windows 由 助手 调用 `powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1" batch --url "<链接1>" --url "<链接2>"`；macOS 由 助手 调用 `sh "<Skill目录>/scripts/run.sh" batch --url "<链接1>" --url "<链接2>"`。也可按 `@references/usage.md` 使用清单文件；指定保存目录时附加 `--output-dir "<绝对路径>"`。
5. 助手 自行运行本机命令，不把命令或终端步骤发给普通用户。若缺 Playwright，助手 按 `@references/usage.md` 运行本机隔离安装脚本后重试；若缺 Python 或 Chrome/Edge，再用普通语言说明缺少什么并协助安装。其他系统明确告知尚不支持。
6. 若弹出浏览器，由用户本人在专用窗口扫码登录元宝。批量任务只打开一次隔离浏览器并复用同一登录；助手不代替登录、不读取现有浏览器/微信桌面会话。
7. 批量结果必须报告请求数、成功数、失败数、跳过数和本地清单路径；逐条给出已保存 MP4 的可点击路径。部分失败时只对成功的条目说“已保存”，失败条目给出错误码和下一步。SHA-256 只是本地文件指纹。

## 边界与注意事项

- 单次批量最多 50 条 `weixin.qq.com/sph/` 链接；自动去重，默认最多 3 个文件并行下载（可设 1–4）。解析仍逐条进行，避免同时操纵浏览器或规避平台限制；实际速度取决于平台响应、视频大小和网络，不保证“秒下”。
- 每条链接须为纯 `https://weixin.qq.com/sph/` 分享链接，ID 只含英文字母与数字；脚本不接收查询参数或片段。单个文件最大 1 GiB，可选 H.264 或 H.265，默认 H.264；不执行转码。
- 只保存用户本人发布或明确获授权的视频；不下载私密、付费、删除或无授权内容，不做无授权批量搬运、不规避平台限流。平台返回限流时停止继续解析。
- 专用浏览器资料目录会保留登录状态，是本机敏感数据，绝不纳入 ZIP 或上传。详见 `@references/usage.md`。
- 当前实现依赖腾讯网页的内部行为，不是官方公开下载 API；接口变化会导致失败。不得宣称永久可用、免登录或零配置。
- 不安装根证书、不修改系统代理，也不调用外部模型或要求模型 API Key。
- 来源、适配与风险见 `@references/provenance.md`。
- 2026-10-22 已在 macOS 完成真实单条下载，并通过 FFprobe 与 FFmpeg 完整解码检查；Windows、真实批量及各客户端完整流程尚未验收。报告时区分已验证结果与未测试场景。
