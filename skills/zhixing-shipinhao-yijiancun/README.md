# 视频号一键存

把本人发布或已获授权保存的视频号分享链接下载为本地 MP4，支持单条、批量、去重和结果清单。此版本为 `1.2.0-local-free`：已移除上游作者侧的邀请码、激活、设备绑定和在线授权核验，可直接使用，不设作者侧下载次数收费。**首次仍需用户本人在专用 Chrome/Edge 窗口扫码登录腾讯元宝。**

适用于 Codex 和 WorkBuddy。脚本面向 macOS、Windows 10/11；两者均需 Python 3.10+、Chrome 或 Edge。解析依赖腾讯网页内部接口，平台变化可能导致失败，不承诺永久可用或免登录。

## 安装

安装前准备 Git、Python 和浏览器。主仓库为 [Brclio/Skills](https://github.com/Brclio/Skills)，同步来源为 [AndersonHJB/CodexSkills](https://github.com/AndersonHJB/CodexSkills)。以下命令从尚无同名目录的位置执行；已有安装时先备份，避免混入旧版文件。

macOS：

```sh
git clone https://github.com/Brclio/Skills.git Skills
mkdir -p "$HOME/.codex/skills"
cp -R Skills/skills/zhixing-shipinhao-yijiancun "$HOME/.codex/skills/"
sh "$HOME/.codex/skills/zhixing-shipinhao-yijiancun/scripts/setup.sh"
```

Windows PowerShell（Python 须在 PATH 中）：

```powershell
git clone https://github.com/Brclio/Skills.git Skills
$skill = Join-Path $HOME '.codex\skills\zhixing-shipinhao-yijiancun'
New-Item -ItemType Directory -Force (Split-Path $skill) | Out-Null
Copy-Item -Recurse 'Skills\skills\zhixing-shipinhao-yijiancun' $skill
powershell -NoProfile -ExecutionPolicy Bypass -File "$skill\scripts\setup.ps1"
```

安装脚本创建独立 Python 环境并安装固定版本 Playwright；使用本机现有浏览器，不安装自带浏览器。完成后重新打开 Codex 或新建会话。WorkBuddy 用户将同一完整技能文件夹放入 WorkBuddy 的技能目录，再运行对应安装脚本即可。

## 直接用聊天调用

向 Codex 或 WorkBuddy 发送：

> 使用「视频号一键存」下载下面这条我已获授权的视频，保存到默认目录：〈完整分享链接〉

也可以一次提供多条链接，或让助手读取 UTF-8 清单。助手检查环境、调用脚本并报告保存结果；用户只需在需要时本人扫码，不应提供密码、Cookie 或票据。

## 命令与批量清单

以 macOS 为例，`<Skill目录>` 替换为安装位置；Windows 使用 `powershell -NoProfile -ExecutionPolicy Bypass -File "<Skill目录>\scripts\run.ps1"` 作为入口，后续参数相同。

```sh
sh "<Skill目录>/scripts/run.sh" doctor
sh "<Skill目录>/scripts/run.sh" download "<完整分享链接>"
sh "<Skill目录>/scripts/run.sh" batch --url "<链接1>" --url "<链接2>"
sh "<Skill目录>/scripts/run.sh" batch --links-file "<清单绝对路径>" --output-dir "<保存绝对路径>"
```

链接须为纯 `https://weixin.qq.com/sph/…` 格式，不带查询参数。清单每行一条，最大 64 KiB；每批最多 50 条。默认保存到 `Downloads/视频号一键存`，可用 `--output-dir` 更改；批量另生成 `wxvideo_batch_*.json`，记录成功、失败、跳过和文件路径。`--codec h264|h265` 选择编码（默认 H.264，不转码），批量 `--workers 1–4` 调整并行文件下载数（默认 3）。

## 排查与隐私

- 缺依赖：运行对应 `setup` 脚本；`BROWSER_MISSING` 时安装 Chrome/Edge。
- 登录失败：检查网络，在专用窗口本人扫码；浏览器启动失败时先关闭此前的专用窗口。
- `INVALID_LINK`：核对纯分享链接；解析错误可能源于链接失效或腾讯接口变化。
- `RATE_LIMITED` / `FEED_HTTP_429`：稍后再试；批量失败可从清单取出失败项重试。
- 文件写入失败：检查目录权限与磁盘空间。详细错误码见 [使用说明](references/usage.md)。

专用登录资料位于 macOS 的 `~/Library/Application Support/zhixing-wxvideo-rd/browser-profile` 或 Windows 的 `%LOCALAPPDATA%\zhixing-wxvideo-rd\browser-profile`。**登录资料、运行环境、下载视频、清单及日志均留在本机，不提交 Git，不打包分享。**清单包含分享链接与本地路径。

## 来源与验证

上游署名为知行；这是基于其版本的本地修改，并非上游官方发布。保留来源记录，不对上游代码重新许可；“免费”指移除本工具作者侧授权收费，不能据此推断再分发权或内容使用权，详见 [来源说明](references/provenance.md)。

2026-10-22：7 项离线 CLI 测试通过；macOS 单条真实下载保存了 23,099,407 字节 MP4（468.811 秒，H.264 1280×720、AAC 双声道），FFprobe 检查及 FFmpeg 完整解码均通过。Windows、真实多链接批量及各客户端完整流程尚未完成实测。仅保存本人发布或明确获授权的内容，遵守平台规则与内容授权。


## 离线回归测试

从仓库根目录运行（Windows 将 `python3` 换成 `python`）：

```sh
python3 -B -m unittest discover -s skills/zhixing-shipinhao-yijiancun/tests -v
```

测试使用模拟的腾讯响应和媒体数据，不访问网络、不打开浏览器，也不需要登录资料。真实接口可用性仍需用有权保存的视频链接单独验证。
