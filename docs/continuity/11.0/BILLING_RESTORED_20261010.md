# 2026-10-10 微信收费、退款与后台恢复回执

负责端：本地10.0。此为当前恢复结果；`BILLING_REOPEN_20261010.md` / safe.json保留凌晨诊断与待确认时点，不再代表当前资金开关状态。

## 结论与授权

经营者先说“按这个方案修复”，经范围澄清后明确“后台收复恢复”。按已提出的有界方案，已实际完成隔离逻辑恢复验证、登记真实成功时间、恢复既有微信收费和退款开关，以及原镜像API/Worker切换。没有实际扣款/退款，没有R2应用代码部署。

本机北京时间11:13的独立线上核验：`production_ready=true`、`can_accept_real_customers=true`，blocker/warning均0；三项公开收费状态 `billing_ready_for_paid_launch`、`public_charging_allowed`、`charge_now_allowed`均true。后端单独核验 `real_checkout_ready`、`charge_now_allowed`、`refund_now_allowed`均true。45/45独立恢复核对通过。

生产源提交仍为 `d57e230524b0577bee98217a49a5ea8cb3e2a51e`，活动目录仍为 `/opt/jiejing-production/releases/20261009T090923Z-d57e230524b0/app`。本地本轮开工status/receive均确认 `6ee37cd23253e0bf33f047f86f6807b046985d20` 干净一致；它是交接源版本，不是新生产部署。

## 真实恢复演练

- 成功run：`20261010T030752Z-d412e063`。
- 源PG14.23；连接身份摘要与旧演练一致。显式REPEATABLE READ READ ONLY导出同一快照，不做源库DDL/DML。
- 使用现有PG14镜像，不拉取。备份客户端256MiB/0.3CPU；恢复容器768MiB、禁swap、0.35CPU、128进程，数据tmpfs512MiB。两阶段不叠加，无网络、无端口、无宿主/持久数据卷。
- 新逻辑备份29,510,900字节；SHA256 `a6793626ce022d8ae6f32ad130b3eef3414a2d4609a02744bca5343d5c8a10bb`。只在服务器既有private新run目录保留，目录0700、文件0600；没有下载数据库或输出客户原始行。
- 同一快照47张表、113,070行：完整表集合、逐表行数与内容摘要相同；173项约束匹配，未验证约束0；dump/restore警告0。
- 真实服务器完成时间 `2026-10-10T03:13:15.135023+00:00`。本机收到成功回执为 `03:09:38 UTC`；服务器比本机快约217秒，保留双时间，不改系统时钟。
- 前三次适配中因Docker tmpfs元数据和Alpine `/var/run/postgresql`→`/run/postgresql`路径的保护性校验误判而停止，未登记成功。通过只读实际挂载证据修正校验并回归后，第四次完整通过。失败备份与回执全部保留；每次仅移除本run名称/标签/镜像精确匹配的临时容器，现无遗留演练容器。

此为真实逻辑备份恢复，不是PITR、整机灾备或COS异地恢复验收。

## 资金开关切换与失败保护

切换前用实际生产代码和只读库连接，在隔离的检查进程中验证候选三值：真实恢复完成时间、收费true、退款true。预检production_ready及收费退款全部通过才应用。

只改 `JIEJING_RESTORE_DRILL_LAST_AT`、`JIEJING_WECHAT_PAY_CHARGE_ALLOWED`、`JIEJING_WECHAT_PAY_REFUND_ALLOWED`。其他env字节、有效环境及eBay原确认边界保持；30天阈值没有放宽。原env备份只留服务器私有目录，没有整体恢复旧配置。预留失败回到资金暂停服务的分支，本次未触发，不冒充失败回滚演练通过。

按deploy→maintenance顺序持锁，只停止/重建捷境API和Worker，`--no-build --pull never --no-deps`。没有重启整机、edge、Vault或拼嘚。新API ID为 `6b06dde64d82c34abe24e9016083d298b243f9c6f1776d4bab3ebd7939a05521`；Worker为 `4ef00273bc7a79bddba6a5726b56d27be0b2a8527779a595b0197b72af733112`，两者原镜像SHA不变。

OPS直连和代理 `/permissions/me` 前后均返回预期匿名401；本轮无需Nginx reload。其余五容器、拼嘚两服务的身份/启动时间保持。正式数据库未覆盖，源代码未更换。

## 独立验收与实际界面

- 公网5个匿名GET无重试：app health/deep/readiness200，OPS首页200，OPS权限接口401。数据库、队列、Worker均ready。
- 不注入候选env的独立后端采集器再核验：收费退款均true、原9/9配置齐全、原批准记录仍在；`verified_paid_order_count=1`未增加，不是新付款验收。
- 本机Chrome现有登录重新加载后仍为“主理人·内部权限”，经营总览可读；上线页当前生产/接客已就绪，备份页整体/恢复演练已就绪。未登录其他账号或读取客户、支付明细。
- 护栏单元回归7+1项通过；独立恢复比对45/45通过；秘密扫描通过。
- 完整本地门禁280/280、exit0，于北京时间11:45:03结束，耗时2890.84秒；`source_stable=true`、`release_eligible=true`。绑定干净源提交 `6ee37cd23253e0bf33f047f86f6807b046985d20`、tree `f717d5e3fdbad96f1494ec9ad2a04dd3dd08c676`，冻结期间没有修改源码、HEAD或索引。未改测试清单、断言、超时或重试；使用既有D盘隔离Node24.20.0，不改全局环境。此为本地源码证据，不能冒充新生产部署或真实付款。

截图仅留D盘：`OPS_READINESS_RESTORED.png`、`OPS_BACKUP_RESTORED.png`；不进Git。安全原件目录 `D:/Codex-Verification/jiejing-billing-restore-20261010-1058/`，对应PREFLIGHT、RESTORE_V4、REOPEN_PLAN、REOPEN_APPLY、POSTFLIGHT、PUBLIC_AFTER、INDEPENDENT_VERIFICATION及CHROME_VERIFY回执。

## 保留的独立待办

1. 部分OPS历史上线/审批/交接面板仍显示其独立证据链的blocked/default状态，生产部署回执尚未接入；当前已读到的实际收费开关不是false。不能因此写整个后台全部收口，也不把R2未部署的展示改进说成已上线。
2. 系统可靠性有1项模型高延迟关注告警：所选窗口样本100、完整P75约21,931ms、首段P75约1,672ms、失败/超时0%；不是本轮资金故障，也不清掉告警伪造全绿。
3. 部署前时效性冷启动检查和OPS上游DNS生命周期的代码防复发项，仍按原工程发布流程单独推进，本轮没有扩张部署。
4. 持续备份、真实恢复演练及Vault等证据应到期前维护，不能用修改日期/TTL解决。按当前30天门槛和服务器证据时间，Vault恢复证据将于北京时间10月24日08:44:44超过窗口；本次PG恢复证据将于11月9日11:13:15超过窗口。应预留提前维护时间，不能等截止后再处理；这不是新建或启用了自动恢复任务。独立PITR证据仍未提供。
5. 本轮没有新真实付款/退款、eBay或拼嘚操作、新费用、视频制作/投稿；恢复收费不等于新增营收、平台保证或永久零故障。

## 接续与防重复

本次收费应用只执行一次且已成功，不再重复应用、重建或恢复。完整门禁结束、源码仍干净后才更新当前执行索引及所改文件pins，按WORK_SYNC明确路径保存原工作分支；最终本地/远端完整SHA以D盘 `SAVE.safe.json` 和 `STATUS_AFTER_SAVE.safe.json` 为准。另一端需要实际receive。媒体/截图/原始日志/备份/凭据不上传；不宣称两端已自动同步。
