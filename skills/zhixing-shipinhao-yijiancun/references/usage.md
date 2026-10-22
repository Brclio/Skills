# 视频号一键存｜使用说明

## 给用户看的步骤

用户只需把本人发布或已获授权的视频号链接发给 助手。本地修改版 `1.2.0-local-free` 无需邀请码，无需联系上游作者或使用作者运营的服务。用户不需要打开终端、复制命令或准备激活文件。首次扫码登录元宝仍需用户本人在弹出的专用浏览器窗口完成；下载仍依赖腾讯网页服务及其访问规则。

本版本是基于知行版本的本地修改，尚未作为上游官方版本发布。

## 助手 内部准备

脚本面向 Windows 10/11 和 macOS；其他系统尚未适配。两种系统均需 Python 3.10+，以及已安装的 Microsoft Edge 或 Google Chrome。助手 先尝试下载命令；遇到缺依赖时自行诊断并运行对应隔离安装脚本，然后重试。若缺 Python 或浏览器，再向用户说明需要安装的应用。以下命令供 助手 内部调用，不应作为普通用户操作步骤展示。

Windows（PowerShell）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1" doctor
powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\setup.ps1"
```

macOS：

```sh
sh "<Skill目录>/scripts/run.sh" doctor
sh "<Skill目录>/scripts/setup.sh"
```

安装脚本只在本机专用目录创建 Python 虚拟环境，并安装 `requirements.txt` 中固定版本的 Playwright。Windows 目录为 `%LOCALAPPDATA%\zhixing-wxvideo-rd\runtime`；Mac 目录为 `~/Library/Application Support/zhixing-wxvideo-rd/runtime`。它不安装 Playwright 自带浏览器、不改根证书或系统代理。若公司设备限制安装，请联系本机管理员，不要关闭安全软件。

## 下载一条授权视频

每个输入项须为一条纯 `https://weixin.qq.com/sph/...` 链接，ID 只含英文字母与数字，不带查询参数或片段。助手 应从分享文案中提取链接后单独传入参数；以下示例 ID 需替换为真实链接。

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1" download "https://weixin.qq.com/sph/ExampleId123"
```

macOS：

```sh
sh "<Skill目录>/scripts/run.sh" download "https://weixin.qq.com/sph/ExampleId123"
```

本地版直接进入登录、解析与保存流程，不传入邀请码参数，不调用旧版激活或设备授权命令。

## 一次保存多条授权视频

把用户消息里的链接逐条传入；下面只展示两条，实际可继续追加 `--url`，每批最多 50 条。请仅保存本人发布或已获授权的内容；下载流程不逐条弹出确认。

Windows：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1" batch --url "https://weixin.qq.com/sph/FirstId123" --url "https://weixin.qq.com/sph/SecondId456"
```

macOS：

```sh
sh "<Skill目录>/scripts/run.sh" batch --url "https://weixin.qq.com/sph/FirstId123" --url "https://weixin.qq.com/sph/SecondId456"
```

未指定 `--output-dir` 时，自动保存到当前用户的 `Downloads/视频号一键存`；可加 `--output-dir "<自选绝对路径>"` 改位置。若已有长清单，也可先保存为 UTF-8 文本，每行一条链接，再用 `batch --links-file "<清单绝对路径>"`。清单最多 64 KiB；不要把登录信息写进去。

单条与批量命令均可用 `--codec h264` 或 `--codec h265` 选择平台返回的视频编码，默认 H.264；工具不执行转码，没有对应编码时可能返回 `NO_MEDIA`。单个文件最大 1 GiB；媒体地址须为校验允许的腾讯域名 HTTPS 地址。

整批共用一次专用浏览器登录；解析逐条进行，已解析出的文件默认最多 3 个同时下载，可用 `--workers 1` 到 `--workers 4` 调整。并发不代表保证固定速度，也不会绕过平台限流。重复链接自动跳过；单条失效不会取消其他正常链接。遇到平台限流会停止解析剩余链接，而已开始的下载会收尾。

任务结束会返回成功、失败、跳过数量、各视频 MP4 路径，并在保存目录生成 `wxvideo_batch_*.json` 清单。清单含分享链接和本地文件路径，请留在本机；它不包含登录 Cookie、票据或视频媒体地址。`partial_success` 表示只有部分视频保存成功，不能把整批说成成功。可从清单挑出失败链接单独重试。

## 登录状态和保存结果

首次可能弹出 Edge/Chrome 专用窗口，由用户本人扫码登录元宝。登录状态只保存在本机专用浏览器资料目录：Windows 为 `%LOCALAPPDATA%\zhixing-wxvideo-rd\browser-profile`，Mac 为 `~/Library/Application Support/zhixing-wxvideo-rd/browser-profile`。这是敏感目录，不要打包、同步到公开云盘或分享给他人。需要退出本工具的登录状态时，请先关闭该专用窗口，再由用户本人删除对应专用目录；这不会影响日常浏览器配置。

成功会返回 MP4 绝对路径、字节数、SHA-256 和标题；失败返回错误码。失败时会清理临时 `.part` 文件，不会把未完成文件伪装成 MP4。SHA-256 是下载文件指纹，不是平台提供的原件校验值。

## 常见失败

- `PLATFORM_UNSUPPORTED`：目前只适配 Windows 与 macOS。
- `PLAYWRIGHT_MISSING` / `BROWSER_MISSING`：运行本系统的安装脚本，或安装 Chrome/Edge 后重试。
- `BROWSER_START_FAILED`：关闭本工具此前打开的专用浏览器窗口，再重试。
- `YUANBAO_UNAVAILABLE` / `LOGIN_REQUIRED`：检查网络并重新运行，在可见的专用浏览器窗口内由用户本人扫码。
- `INVALID_LINK`：每个输入项必须是一条格式符合要求的 `https://weixin.qq.com/sph/...` 链接；批量时重复传 `--url`，不要把多条拼进一个参数。
- `NO_LINKS` / `TOO_MANY_LINKS`：批量命令没有链接，或超过每批 50 条。
- `LINKS_FILE_TOO_LARGE` / `LINKS_FILE_UNREADABLE`：确认清单为可读取的 UTF-8 文件，且不超过 64 KiB。
- `INVALID_WAIT` / `INVALID_WORKERS`：登录等待时间须为 30–600 秒，批量并行文件下载数须为 1–4。
- `RATE_LIMITED` / `FEED_HTTP_429`：平台限流；本次已停止后续解析，稍后由用户决定是否重试，不得通过换账号或代理规避限制。
- `PARSE_UNAVAILABLE` / `PARSE_REJECTED` / `PARSE_CHANGED` / `NO_PLAYABLE_URL`：检查网络、元宝登录和链接可访问性；也可能是腾讯网页接口变化。
- `FEED_UNAVAILABLE` / `FEED_REJECTED` / `FEED_INVALID` / `FEED_HTTP_*` / `NO_MEDIA`：检查链接可访问性、保存权和所选编码；也可能是平台接口变化，不要绕过权限。
- `UNTRUSTED_MEDIA_URL` / `TOO_MANY_REDIRECTS`：来源未通过媒体安全校验；先人工核对，不应关闭校验。
- `DOWNLOAD_UNAVAILABLE` / `INCOMPLETE_DOWNLOAD` / `BAD_RESPONSE`：检查网络和服务器响应，再重试一次。
- `SIZE_LIMIT` / `INVALID_MP4`：文件超过大小限制，或返回内容未通过 MP4 文件头检查。
- `FILE_WRITE_FAILED`：检查保存目录权限和剩余磁盘空间。

## 验证状态

2026-10-22，`1.2.0-local-free` 在 macOS 使用真实链接完成单条下载：生成 23,099,407 字节 MP4，时长 468.811 秒，H.264 1280×720 视频及 AAC 双声道音频。FFprobe 检查和 FFmpeg 完整解码均通过。另有 7 项离线 CLI 回归通过，覆盖单条、批量清单、去重、链接校验、限流停止和登录要求；这些测试中的腾讯接口与媒体响应为模拟。Windows、真实多链接批量及各客户端完整流程尚未实测。
