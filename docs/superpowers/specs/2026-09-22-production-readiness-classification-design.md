# 生产证据采集与营业准入的有界分离

日期：2026-09-22。用户在已披露推荐方案后要求继续推进，本批获准本地实现与验证。本文是部署协议设计，不替代 `docs/JIEJING_CURRENT_EXECUTION_STATE.md`，不证明已部署或营业已获准。

## 问题与范围

生产刷新任务已完成 COS、CLS、告警读回、六项证据快照和运行身份检查后，仍会因公开 `backup_restore` blocker 返回 exit 2。正式部署的首次 oneshot 据此回滚，即使故障来自既有恢复演练的营业准入条件。

保留一个公开 JSON 解析器，在完整安全契约通过后区分营业状态。仅修改生产刷新脚本、生产 apply 的首次验收、部署 CLI 回执及两份对应测试；不修改后端 readiness、systemd units、证据时效或业务开关。不影响旧 staging 的独立 CLS 通道。

## 三种结果

| 结果 | 必须满足的事实 | 刷新进程及部署 |
| --- | --- | --- |
| success | 全部采集、持久化、运行检查和公开契约成功，营业准入满足 | exit 0，commercial ready |
| blocked | 全部采集、持久化、运行检查和公开契约成功，合法营业阻断仍存在 | exit 0，commercial blocked，保留原字段 |
| error | 任一采集、持久化、健康、身份、安全或公开契约检查失败 | 非零失败，首次验收回滚 |

既有刷新错误仍输出 `JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked` 和明确失败原因，exit 2 保持失败语义。商业 `blocked` 采用独立的 `COMMERCIAL_*` 字段，不能作为接受任意 exit 2 的例外。锁竞争的 `skipped/exit 0` 仍不能通过首次验收。

本批支持三个准确投影：

1. 公开收费已配置，0 blocker / 0 warning，production / beta / customer 全 true：commercial ready。
2. 公开收费已配置，唯一 item 为 `backup_restore`、`blocked_backup_restore_not_ready`、blocker，1 blocker / 0 warning，三项准入全 false：commercial blocked。
3. 既有合法 billing_quota warning，0 blocker / 1 warning，production=false、beta=true、customer=false、公开收费=false：commercial blocked。

第二种只接受完整既有公共字段、严格类型、正确计数、固定标签及非空有界说明；未知 item/status、额外 blocker、监控未就绪和不一致投影均拒绝。它不判断具体备份失败原因：该公开 status 也可能代表其他备份缺口，不能单独证明 Vault 演练过期，更不能证明恢复已经完成。

## 输出与首次验收

`public_readiness_ready()` 保留单一解析器，将有效结果存入只包含九个固定字段的 `PUBLIC_READINESS_REPORT`。每次读取前清空旧值；HTTP/JSON/契约错误不能沿用上一轮报告。原有有界重试保留，合法营业阻断可以完成收敛，不等待阻断自行消失。

只有最后一次 `verify_unchanged_runtime()` 通过，main 才输出 `PUBLIC_READINESS_CONTRACT_STATUS=verified`、商业状态、原因、两个计数和四个实际布尔，随后输出刷新 success。错误路径不打印原始公共 JSON、provider 输出、秘密值或伪造的营业分类。

apply 仍要求新且准确的 InvocationID、systemctl start 成功、Result=success、ExecMainStatus=0；不增加 `SuccessExitStatus=2`。该 Invocation 的日志须具备恰一次 live guard、COS、告警、CLS、snapshot success，两次 API/Worker unchanged，恰一次刷新 success 和 SECRET_EXPOSED=false，以及唯一且相互一致的九字段报告。缺失、重复、冲突、未知分类或任何 refresh blocker/skipped 均拒绝。安装、锁、最终镜像检查、timer 启动和事务回滚顺序不变。

正式部署完成后才将已核验的同一报告带入 stdout；CLI 严格解析为独立 `commercial_readiness` 对象。dry-run 不运行采集，不能声称取得商业状态。`status=deployed` 仅描述部署；systemd success 仅证明证据刷新，本次商业阻断应从该报告、公开 readiness 和内部运营状态读取，不能再以 unit success 推断营业。

## 不可放宽的边界

- 健康检查、运行容器/image/Compose 标签、只读挂载、精确私有路径及权限、非证据配置 digest 不变。
- COS、CLS、告警、双写和最终身份任一步失败，均不能被商业 blocked 掩盖。
- 既有六字段快照白名单不扩展；Vault/PG 演练日期、有效期及证据来源不改，不执行恢复或伪造时间。
- eBay、即时收费/退款、前端凭据、额度、确认中心等全部安全布尔检查保留；收费配置 true 不等于全局接客准入 true。
- 用户原七项 dirty 不属于本批；不提交、不建立新候选、不运行完整门禁、不 SSH 或部署，直至主审完成本轮复核。

## 本地验证设计

- 真实公开解析 seam：合法 backup blocker 的旧代码 exit 2，修复后保留三项准入 false 和收费配置 true；错误类型、未知/重复/额外 item、安全布尔变更仍拒绝。
- 真实有界等待：网络失败、坏 JSON 后收敛到合法商业 blocked；持续网络或 JSON 错误失败且清空旧报告。
- 真实 main 与现有隔离 Docker/provider 夹具：完整采集后商业 blocked 成功；COS/告警/CLS/snapshot/最终身份失败始终 exit 2，无商业分类或刷新 success。该测试的云和运行环境使用替身，不是生产探针证明。
- 真实首次 oneshot 函数，外部 systemctl/journalctl/sleep 替身：三种允许投影、不同/错误 InvocationID、服务失败/exit 2、缺失/重复/冲突日志与状态全部有用例。
- CLI 回执：商业 blocked 与 deployed 分开保存，未知/缺失/冲突分类及 dry-run 伪造观察拒绝。

新源码须通过两份完整专项和语法/秘密检查，再由主审复核。R5 的既有全门禁、CI、ZIP及 manifest仅对应旧源码，不能给本修复背书；后续获准形成干净候选后再取得新同源发布证据。
