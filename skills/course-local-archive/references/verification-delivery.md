# 本地核验、浏览器验收与批次恢复

## 单课阶段

完成采集后，先构建来源资源清单，再下载/合并补充资源：

```text
python3 scripts/media_inventory.py
python3 scripts/archive_course_extras.py
python3 scripts/archive_course_extras.py --apply
python3 scripts/media_inventory.py --verify
python3 scripts/link_local_audio.py
python3 scripts/link_local_audio.py --check
python3 scripts/link_local_video.py
python3 scripts/link_local_video.py --check
```

补充工具负责课程介绍、字幕和已验证来源的视频独立音轨；主音视频使用工作流中的专用工具。导入/下载与 apply 分开；preview 不更新清单。不能用仅预览命令宣称合并完成。

```text
python3 scripts/build_site.py
python3 scripts/build_course_info.py
python3 scripts/build_resources.py
python3 scripts/audit_archive.py --mode fresh --audit-run-id <unique-run-id>
python3 scripts/finalize_archive.py --apply
python3 scripts/audit_archive.py
```

`finalize` 默认只读，`--apply` 仅写 `local_verified`。第一次完整核查使用 fresh；最后一次增量审计绑定生命周期写入后的实际清单，避免重复全媒体解码。普通续存可用默认 incremental。一次 fresh 中断后，只有显式相同 `--audit-run-id` 加 `--resume-same-run` 才复用该轮已完成且当前 SHA 相同的结果；新 run ID 必须重新解码。`--decode` 是 fresh 的兼容别名。

图片核验比较当前字节与来源清单，并完整解码全部帧；同一 SHA 去重。音视频显式映射全部音视频流并要求成功到 EOF，保留 probe、progress 和完整 stderr。没有历史 decode 报告不妨碍 fresh 启动。来源元数据告警只有完整独立检查支持时接受，不吞掉真实流错误。

核心审计只绑定明确 producer 报告，QA/delivery 不加入媒体处理指纹。修改 UI 只重复受影响 UI 证明，修改媒体/来源则重做对应本地证据和审计，不靠旧的 passed 标记放行。

## 实际浏览器验收

用 `python3 scripts/serve.py --help` 选择本地端口；服务支持 Range，响应禁缓存。通过获准浏览器工具打开本地入口。JS/CSS URL 的内容哈希和运行时标记必须对应实际加载内容，单看磁盘文件不能证明页面已更新。首次连接只执行浏览器工具说明允许的入口，连接失败保存当前状态，不切到未授权的浏览器内部通道。

```text
python3 scripts/observe_reader.py --print-browser-probe
```

此命令仅打印被动 DOM 观察表达式，不执行浏览器操作。用浏览器工具在实际页面读取 loaded_payload、runtime_urls、runtime_markers 和 current；若获准的只读 DOM 环境不暴露 navigator，probe 的 browser 为 null，须以工具实际返回的浏览器名称/类型补充 browser 字段，不虚构 User-Agent。用真实 UI 操作并记录结果，不以脚本改 DOM 模拟成功。把原始工具快照/截图存到 `raw/qa/`。不得填造 proof 或用磁盘 payload 冒充浏览器加载值。

将实际观察保存为 `raw/qa/observation.json`，保留 probe 的顶层字段，加入 `proofs[]`；每项含 `kind`、实际 `observed` 和非空 `artifacts` 相对路径数组。字段的严格契约在 `scripts/qa_evidence.py`，要点如下：

| kind | 必需的真实观察 |
| --- | --- |
| navigation | catalog_count；首/中/末实际访问 visits 的 lesson_id、title |
| search | 非空 query；实际 result_lesson_ids 与来源内容预期一致 |
| font_control | before_px、after_px 有变化；font_faces_ready |
| layout | viewport_width、horizontal_overflow_px、failed_image_count、console_errors |
| info / resources | 实际 page_path、title、missing_resource_count |
| media | proof.path；ready_state、duration_seconds、播放前进量、seek目标与实际时间、error；视频含实际宽高 |
| download | proof.path；UI发起、实际下载 bytes、sha256 |

音频/视频各按当前本地可播清单动态抽取首/中/末；没有的类型无需伪造测试。至少实测一次下载，内容与当前文件一致。字幕、本地介绍及组件下载链接存在时一并实测，不能以文件存在代替 UI 可用。

```text
python3 scripts/observe_reader.py --observation raw/qa/observation.json
python3 scripts/verify_delivery.py --audit raw/archive-audit.json --qa raw/qa/browser-qa.json
```

前者验证并绑定真实观察，后者同时检查当前本地审计、来源资源清单和 UI 证据，仅写 `raw/delivery/status.json`。只有 `fully_delivered` 代表通过交付门；不回写 `course.json`，从而不使刚完成的 UI 证明失效。陈旧 loaded payload、runtime hash、核心文件或媒体均要求重验受影响项。工具限制导致无法实测时保留 incomplete 并说明实际边界。

## 批次恢复原则

批次协调器只接收本地已授权导出，不代管浏览器登录或凭据。每课的阶段状态、输入摘要、失败原因和退出码独立保存；同课只能一个协调器，跨课有界并发。共享清单写入持 manifest 锁并原子/CAS 更新；父协调器使用独立 lease，不能锁着 manifest 等子进程。

私有解密交接文件仅在归档外，必须先写完并完成核验，再发布 ready 状态。接收端重新验证当前来源/原件报告绑定，不因文件存在就开始。处理完成删除私有输入；失败保留脱敏状态，不能将其复制到课目录或技能。各课本地通过后仍需独立浏览器验收；批次 local_verified 不等于全部 fully_delivered。

`batch_local.py` 只处理已有完整本地导出的课程目录，`--dry-run` 先看选择；例如：

```text
python3 scripts/batch_local.py --courses-root <archives-parent> --stage audit --mode fresh --audit-run-id <batch-run-id> --workers 2 --dry-run
python3 scripts/batch_local.py --courses-root <archives-parent> --stage audit --mode fresh --audit-run-id <batch-run-id> --workers 2
```

`--course` 可重复；`--stage` 为 rebuild、audit、delivery 或 pipeline。pipeline 仅执行 rebuild→audit→delivery gate，不下载、不自动finalize、不接收/清理私有输入；缺少实际UI证据时保留 awaiting_delivery_evidence。真正采集、私有解密与生命周期应用仍由前述单课流程完成。该工具的一级目录发现不是已购课程清单，不能证明已覆盖全部购买。
