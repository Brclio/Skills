# 思维训练绘本工坊

`thinking-picture-books` 把观察、分类、数感、空间、规律、推理与记忆任务编进原创绘本故事。先确定孩子要做的思考和可验证的答案，再生成角色与完整图文页，最后对成品图重新解题。

支持零参数创作、照片角色、系列作品和既有绘本修订。工作流入口是 [SKILL.md](SKILL.md)；本页说明安装、调用和交付。

## 使用前准备

- 制作绘本需要可使用内置图片生成工具的 Codex 环境，以及该环境提供的 `imagegen` Skill。安装本目录不会安装或开启图片生成服务。
- 可选参数脚本使用 Python 3 标准库，无需 `pip install`。脚本只生成配置初稿，不生成故事、图片或 PDF。
- 仅在要求 PDF 时使用当前环境的 PDF Skill，对最终图文页进行装订和渲染核查。
- 本目录不包含角色照片、参考书原图或已经生成的绘本。照片可在实际创作时提供；学习参考的机制总结保存在 [reference-lessons.md](references/reference-lessons.md)。

## 安装与更新

可以把下面的请求发给 Codex：

```text
请从 https://github.com/Brclio/Skills 安装 thinking-picture-books。
只安装 skills/thinking-picture-books/，不要改动其他 Skills。
若存在同名目录，先备份，再更新；完成后核对 SKILL.md、agents、references 和 scripts。
```

也可以在 macOS / Linux 使用 Git 和 rsync 手动安装。以下命令在当前目录创建 `Brclio-Skills`；若已有克隆，请直接进入该目录。若本地已有同名 Skill，先执行下方的备份步骤。

```bash
git clone https://github.com/Brclio/Skills.git Brclio-Skills
cd Brclio-Skills
picture_book_skill_dir="${CODEX_HOME:-$HOME/.codex}/skills/thinking-picture-books"
mkdir -p "$picture_book_skill_dir"
rsync -a skills/thinking-picture-books/ "$picture_book_skill_dir/"
test -f "$picture_book_skill_dir/SKILL.md" && echo "thinking-picture-books installed"
```

安装后新建 Codex 会话；若列表尚未刷新，重启 Codex。确认能选到 `thinking-picture-books`，且当前会话能使用内置图片生成工具。

更新时，在仓库根目录执行以下命令。备份放到 Skills 目录之外，避免备份被当作另一个 Skill 加载；同步范围始终是这个 Skill 的子目录。

```bash
git pull --ff-only
picture_book_skill_dir="${CODEX_HOME:-$HOME/.codex}/skills/thinking-picture-books"
picture_book_backup_dir="$(mktemp -d "${TMPDIR:-/tmp}/thinking-picture-books-backup.XXXXXX")"
cp -R "$picture_book_skill_dir" "$picture_book_backup_dir/thinking-picture-books"
printf '备份位置：%s\n' "$picture_book_backup_dir"
rsync -a skills/thinking-picture-books/ "$picture_book_skill_dir/"
```

## 快速调用

### 自动补全参数

```text
使用 $thinking-picture-books，做一本原创思维训练绘本。
```

默认假设为 **4–6 岁亲子共读、标准难度、简体中文、32 页**；角色、场景、主题和主要训练能力按规则补全。年龄是制作假设，不是对真实孩子的判断。

### 指定能力与题材

```text
使用 $thinking-picture-books，制作一本32页的海洋探索绘本。
面向5岁孩子，主要训练观察，辅助练习可见线索推理，难度入门。
成人读题，孩子指一指或说出线索，不要求识字和书写。
```

### 用照片建立角色

在会话中附上照片，或提供真实可读取的本地图片路径，然后发送：

```text
使用 $thinking-picture-books，把这张猫咪照片中的猫做成主角。
面向3岁孩子，训练分类；保持猫的毛色和斑纹，题目以指一指为主。
```

先检查参考图并生成角色设定图，再把该图作为后续页面的身份参考。保留可见特征，不根据外观推断真实性格。

### 制作系列或修订

```text
使用 $thinking-picture-books，同一个原创角色做3本绘本，分别训练观察、规律和空间。
先锁定角色DNA与系列表，各册规则和迁移任务要有实际差异。
```

```text
使用 $thinking-picture-books，修订 output/我的绘本-v1/。
保留角色和已确认规则，修复第8页的数量错误，另存为新版本并复检受影响页。
```

如果只想得到设计方案，请明确说“只做方案，不生成图片”。

## 页数、参数与生成规则

| 项目 | 默认与约束 |
| --- | --- |
| 正式书页 | 默认 32 页，常规最低 30 页；含封面、正文、答案与成人指南 |
| 不计入页数 | 角色设定图、提示词、核查图、废稿与制作说明 |
| 训练结构 | 一个主要能力，可带一至两个辅助能力；每页一个主要操作 |
| 适龄处理 | 按实际能力调整难度、单页负荷、章节和每次阅读量 |
| 视觉成品 | 角色、封面、正文、文字、页码、答案和指南均由内置 imagegen 生成 |
| 默认版式 | 横向单页约 3:2，全书一致；实际像素以生成结果为准 |
| 修订 | 保存新版本，不覆盖原版本 |

不能因低龄、零参数或赶时间自动缩短全书。后续用户明确覆写页数时，人工编排并记录要求；常规脚本仍拒绝小于 30 页。

文字会逐字写入图片生成提示词。不能使用 Pillow、SVG、HTML、Canvas 或排版工具后贴书内文字、重画题面。复制文件、检查与不新增视觉内容的 PDF 装订不受此限制。内置生成不可用时应报告实际状态；只有用户明确选择 CLI 时才走 imagegen 的官方备用流程。

完整字段、默认来源、冲突处理与多本约束见 [参数与默认策略](references/parameters.md)。

## 可选：先生成配置初稿

以下命令均从仓库根目录运行。没有 `--out` 时将 JSON 输出到终端：

```bash
python3 skills/thinking-picture-books/scripts/resolve_brief.py --seed 42
```

使用本目录的 [配置示例](examples/brief-input.json)，将结果写入一个尚不存在的文件：

```bash
python3 skills/thinking-picture-books/scripts/resolve_brief.py \
  --input skills/thinking-picture-books/examples/brief-input.json \
  --seed 42 \
  --out output/海洋观察-v1/brief.json
```

`--out` 会创建父目录，但拒绝覆盖已有文件。再次运行时请换新路径，或省略 `--out` 查看结果。将生成的 `brief.json` 交给创作会话继续完成教学设计、角色 DNA、分镜、出图和核查。

| 参数 | 作用 |
| --- | --- |
| `--input` | 可选 JSON 对象，支持中英字段名；年龄用数字或 `[下限, 上限]` |
| `--seed` | 可选整数，覆盖输入文件中的 seed；复现配置选择，不保证复现图像 |
| `--out` | 可选新文件路径；省略时输出 JSON 到标准输出 |

脚本保留显式参数并标记补全来源。未知字段会原样保留并提醒人工落实；它不会解释照片、验证图片路径、完成教学判断或保证多本训练机制互不重复。

## 交付与验收

正常完成后，在工作区或指定目录下得到：

```text
output/<书名>-vN/
├── brief.json           参数、来源、seed 和版本信息
├── character-dna.md     角色规格
├── characters/          imagegen 生成的角色参考
├── storyboard.md        分镜和精确文稿
├── page-specs.json      题面、规则、答案、理由和三层提示
├── pages/               按阅读顺序保存的最终完整图文页
├── prompts/             实际提示词和参考图映射
└── qa.md                逐页检查证据、修订和未解决问题
```

生成前验证题目可解性，生成后对成品图重新解题，核对文字、物件数量、空间关系与角色一致性。错字、数量错误、关键线索遮挡、多解或无解、身份漂移必须修复；未解决的页面只能标记未完成。

同页两次定向修复仍失败时，简化题面或重新生成；仍不合格则说明失败原因。不得将未生成的文件或未核验的页面标为交付完成。PDF 只在用户要求时另行导出。

这些是教学设计目标，尚不代表经过儿童实测的效果；不承诺提升智商或普遍迁移。

## 资料导航

- [参数与默认策略](references/parameters.md)：自然语言、JSON、页数、多本和冲突处理。
- [教学设计](references/learning-design.md)：能力、题型、难度与亲子支架。
- [角色 DNA](references/character-dna.md)：照片转角色与跨页身份一致性。
- [逐页规格与核查](references/page-contract.md)：题面契约、答案和验收。
- [imagegen 制作规范](references/image-production.md)：整页提示词、引用图片与修复。
- [参考学习结论](references/reference-lessons.md)：参考图的机制提炼与设计边界。
- [教育依据](references/evidence.md)：外部资料及设计推论，非效果验证。

发布内容包括工作流、代理入口、参考文档、参数脚本和输入示例；不包含本机缓存、个人照片或生成作品。参数脚本的验证不等于图片生成或儿童使用效果验证。
