# OPS 对齐后续：旧断言与测试环境修复

2026-10-09，北京时间。负责端本地 10.0；经营者要求“持续推进”。正确干净 receive 起点与远端一致：`cfe28f1fa924410fc6b2163f920e35789b36f7a3`。不部署、不改腾讯云共享配置、不碰拼嘚、真实支付/eBay 或视频，不新增费用。

## 本轮已修复及证据

1. `agents_md_guardrails` 原先要求旧品牌固定原句。现核验当前已批准的“跨境运营 AI CEO SaaS、eBay 首发、未来平台不能冒充当前支持”三条；其他秘密、权限、商业证据及部署确认断言保持。没有改 AGENTS 来迁就测试。
2. `local_first_cloud_fallback_guardrails` 原先仍强制本地主、云备用。现核验已有 WORK_SYNC、负责端、正确分支、dirty 保全、receive/save、推送不等于对端接收及不授权部署。旧 June runbook 明确由当前双端规则取代，保留原文件入口、历史 Git 记录和手动自检 workflow 名称；没有修改/触发任何 GitHub workflow。
3. `tencent_runtime_env` 的真实错误是 `cls_log_pb2.py` 所需 `google.protobuf` 缺失，不是 Google 服务或凭据。原仓库锁已声明 `protobuf==5.29.6`。在 D 盘创建测试 venv，以只读方式继承原 Python 依赖；仅向该 venv 安装官方 PyPI 二进制 wheel，使用原锁的全部允许哈希和 `--require-hashes --no-deps`。不改全局 Python、不修改项目依赖版本、不装名为 google 的包。原测试的真实 protobuf 编解码、合成 CLS 客户端和拒绝任意上传元数据断言全部保留，实际复测 exit 0。

新增 `test_jiejing_instruction_continuity_regressions.py`：先观察两个当前规则正例失败，再修复至通过；逐条移除品牌边界、部署确认、云端文件/身份限制、保全/接续要求，以及插入定时/写权限/秘密配置时均拒绝。共 9 组 unittest，其中包括多个反例子测试，不把子测试数量冒称独立测试数量。

复核还发现本轮新增的 5 个 OPS 专项脚本尚未列入全量门禁。已保留原 274 项并追加这 5 项及上述接续回归，共 **280 项**；未删检查、改超时或重试策略。目录覆盖回归先观察缺失失败，再加入目录后通过。专项结果和全量结果分别记录，不拼接成虚假完整通过。

最新专项运行 `FOCUSED_CHECKS_FINAL.safe.json`：18 个检查命令全部 exit 0，包含接续 9、版本绑定 18、OPS 证据 3、统计 4、窄源码保存 5 组 Python unittest，以及两个 Node 专项、原三个失败、关联 GitHub/部署静态契约、秘密扫描、前端语法和 diff 检查。没有对外请求业务接口、部署、真实 CLS/COS 或服务器写入。初次专项回执 `FOCUSED_CHECKS.safe.json` 保留；首次 shell 引号错误未进入测试执行，后来改用独立本地 runner，不把它当业务失败或通过。

## 完整回归与保存方式

证据根目录：`D:/Codex-Verification/jiejing-ops-followup-20261009/`。

- `START_STATUS.safe.json` / `RECEIVE.safe.json`：真实开工接收。
- `FOCUSED_CHECKS_FINAL.safe.json`：本轮专项结果、实际解释器和 protobuf 位置。
- `SAVE_CANDIDATE.safe.json` / `STATUS_CANDIDATE.safe.json`：经审查正常保存候选到共用分支后的完整 HEAD 与远端读回；没有成功回执前不预称已推送。
- `full-gate/progress.safe.json`：若完整回归已启动，则记录实际进度；文件缺失不代表通过。
- `full-gate/SUMMARY.safe.json` / `full-gate/latest.json`：只在新完整运行结束后按真实结果记录。运行期间不改源码，绑定实际干净候选；不得将专项通过当作新全量已通过。

本地测试解释器是 `D:/Codex-Verification/jiejing-ops-followup-20261009/test-venv/Scripts/python.exe`。当前机器若仍调用原全局 Python，缺 protobuf 的错误会再次出现；本轮不是全机软件升级。云端使用自己实际核验的环境和原依赖锁，不能假定已收到此 D 盘 venv。

CHECKPOINT 只更新合法修改的执行索引对应 LF 源码哈希；Windows 工作副本的 CRLF 原始字节与云端 LF 不同是既知限制，不声称所有原始媒体/历史记录已通过完整迁移验收，不改媒体固定哈希。

## 生产证据接线的停止边界

已再次核对现有生产工具和 `backup_plan` 的实际代码。生产工具有严格 apply/dry-run 区分、source SHA、active-switch 与持久化回执，但没有明确完成时间或当前应用端的可信安全读回。旧回执含 stdout/stderr，不能整包转发到 OPS。PITR 仍只有最低策略要求；普通恢复时间不证明特定时间点恢复。

下一步的只读接收方案应将两项分开：

- 生产版本：可信 apply 回执白名单 → 与当前运行 release/source SHA 比对 → 仅显示已验证 SHA、实际完成时间、核对时间和状态；不接受 dry-run、本地包时间或浏览器自报证据。
- PITR：绑定正确数据库目标的恢复窗口/采集时间/指定恢复点及实测结果 → 分别显示能力与演练新鲜度；目标不符、过期、未来时间或缺字段均不得通过。

现阶段没有取得这两个可信输入，卡片继续未接入/未知。不把这解释为生产没有部署或没有 PITR，也不为变绿重做恢复、读凭据、改共享服务器或购买资源。本轮没有新增环境变量/证据认证入口，没有做生产 PostgreSQL 查询实测。后续要实施新的生产证据采集/持久化接线，须先确认来源和字段契约；任何实际部署仍需明确批准。

## 主理人复核

经营方向、既有导航和收费规则未变。当前规则不会退回旧品牌定位或旧“本地主”偏好；只读同步不扩展为实盘执行。新门禁增量覆盖防止未来回归遗漏，原失败证据不重写。原两份 assets 保存窄例外不扩大。源码交给共用分支不等于另一端已 receive，也不等于公众网站已经获得 OPS 修复。
