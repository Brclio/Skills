# 得到旧 v1 加密 MP4

本流程已在整门课全部原密文验证：等长转换为合法 MP4，严格全音画解码通过，画面 VCL 与 AAC 压缩数据和独立 HLS 来源精确一致。不能自动外推到新版本。

## 适用与来源

- 正常已购响应 `article_info.video[]` 有 token_version=1；外层 token 是 Base64 JSON `{tk,v:1}`。
- `.mp4.enc` 原始字节已保存并核对来源大小、ETag/MD5、SHA。
- 以 `assets/vendor/` provenance 校验官方库 SHA。验证来源为官方 Android 13.7.0，APK SHA `8db39224960a3e8b0a842f7e459b884fdbdfa7a5e9f0389aea0d8c5ef8c38b23`。脚本只静态读取库，不装 App、不执行该 .so。
- 库哈希、格式、字段不匹配时，先核对当前官方实现；不能忽略验证强行输出。

## 确切变换

`libddd_ff_protocol.so` v1 路径恢复 RSA-1024 包装，验证 PKCS#1 v1.5 BT2 和内层 JSON `{k,u,d,t}`。k 是 Base64 媒体 key，其他字段属于身份/设备/时间检查，不是 URL。真实值不写报告。

1. Base64 解码 k，AES-128 使用 keyBytes 前16字节。
2. 完整 keyBytes 求 MD5，再逐字节生成 `seed[i]=((MD5[i] XOR 6)+5) mod 256`。
3. counter 为 `seed[0:4] + BE32(offset/16) + seed[4:12]`。
4. AES(counter) 与原始字节 XOR；只递增 counter 的第4–7字节，不能直接套默认末尾递增 CTR。

静态位置：参数 VA0x5d010、解混淆表0x5d220、函数0xfc50；v1 消费者0xef68；内容入口0x1d7e0；AES schedule0x1f8fc；CTR XOR0x1db70；计数递增0x1da3c。脚本记录对应库哈希、地址与输入输出哈希，不记录真实 key。

## 私有输入与执行

用 `export_dedao_private_tokens_in_page.js` 在已购页面取得媒体 token，不能导出账户 Cookie。先将 `window.__courseArchiveOptions.mode='private_tokens'`（保留其中 courseId 等配置）；仅在本次归档已要求原件解密时启用此模式。导出名为 `dedao-private-video-tokens-<courseId>-<complete|partial>.json`，先核对 complete 与当前原件报告中真实密文子集（来源 media ID/index 一致），不要要求明文视频也带解密 token。以创建时即0600的临时文件和0700目录接收；浏览器先落 Downloads 时立即受限搬移并删除原下载，不能放课程 raw 或技能包。

最小输入：`{"videos":[{"lesson_id":"source id","token":"current media token"}]}`。只报告数量、状态、类型/长度、哈希和验证结果。内层对象可留页面内存，不在 Console 展开。

先验证一个真实样本前缀，再批量：

```text
python3 scripts/decrypt_legacy_video.py --root <course-root> --library <verified-lib> --expected-library-sha256 <provenance-hash> --token-input <private-json> --lesson-id <observed-id> --prefix-only
python3 scripts/decrypt_legacy_video.py --root <course-root> --library <verified-lib> --expected-library-sha256 <provenance-hash> --token-input <private-json> --workers 3
python3 scripts/review_legacy_decrypted.py --decode-samples
python3 scripts/apply_decrypted_videos.py --apply
```

当前经过验证的 AES 系统原语是 macOS CommonCrypto，另需 FFmpeg/FFprobe。其他系统先接入标准 AES block 原语并跑已知向量和真实前缀测试，不声称未经测试的平台已兼容。

输出为 `assets/video/decrypted/<id>.mp4`，不覆盖原件或 Web MP4。已有结果只有输入/输出哈希及验证证据都匹配才复用。真实密文子集全部通过解密审计后，另核对明文原件与密文来源并集覆盖完整视频清单，再选择默认播放器。Web 更高画质可保持默认；同画质优先原件。video_decrypted_original 始终独立保留，不被 Web 默认覆盖。

## 验收

- 原件哈希处理前后不变；本算法输出等长。
- 合法 MP4 盒、预期尺寸/时长、视频及音轨；所有 AV 流在 `-map 0:v -map 0:a` 下严格完整解码0。
- 与独立 HLS 对照 H264 图片 VCL 与 AAC 压缩流，解释非图片 NAL 包装差异。
- 独立核验真实变换来源绑定，不能把已有 HLS 文件冒充解密结果；无来源证据只证明候选可播。
- 删除私有临时输入、重复下载及页面临时对象；确认没有进交付包。保留不含秘密值的来源、变换和独立核验报告。

主音频、课程介绍音频或独立视频音轨应先按正常可用来源保存；不能因课内存在 v1 视频，把同课全部媒体强行套入此解密流程。标准 identity AES HLS 使用其清单资源密钥，并保留本地资源映射，不采用这里的私有 v1 token 算法。
