# OPS受限恢复回执：登录已恢复，收费门槛未解除

操作日期：2026-10-09；文档收尾：2026-10-10凌晨，北京时间；负责端本地10.0。经营者本轮明确回复“同意，现在恢复”。授权范围为临时暂停收款/退款、按既有受限模式恢复API及OPS，不含生产数据恢复、重建、资金执行或拼嘚变更。

## 实际结果

- 本机Chrome原OPS页面已完成真实登录，经营总览显示“真实数据已更新”；不是仅以静态首页200判定成功。
- API健康；Worker运行；匿名OPS `/permissions/me` 返回应有的401，不再502。
- 生产仍是R1 `d57e230524b0577bee98217a49a5ea8cb3e2a51e`，活动目录 `/opt/jiejing-production/releases/20261009T090923Z-d57e230524b0/app`。没有再次部署R2或替换镜像版本。
- 真实收款和退款暂停。新鲜公开readiness仍为 `production_ready=false`、`can_accept_real_customers=false`，1项阻断、1项警告。可登录不等于正式收费已恢复。

## 两段故障及最小修复

1. PG恢复演练 `2026-09-09T10:00:45.075504+00:00` 在10月9日北京时间18:00:45超过30天；新旧API冷启动都拒绝过期证据。按已有受控运行契约，仅将 `JIEJING_WECHAT_PAY_CHARGE_ALLOWED` 和 `JIEJING_WECHAT_PAY_REFUND_ALLOWED` 从true改成false，其余配置字节保持。原文件只备份于服务器已有private目录内，0700目录/0600文件，未下载秘密。
2. 持有既有部署锁与维护锁，仅以同一R1镜像重建API/Worker，使两者读取资金暂停配置。API恢复后，OPS仍502；只读探针查明Nginx持有重建前API地址，直连现API为401、OPS代理为502。
3. 对OPS Nginx先做配置语法检查，再一次平滑reload，未编辑代理配置、未重建OPS容器。代理恢复401，然后实际登录成功。

变更前第一次计划调用因缺少私有目录的路径环境变量而失败，没有发生变更；纠正环境路径后才执行成功计划和一次apply。失败及中间状态保留，不用最终成功抹去。

服务器记录资金暂停/API恢复完成UTC15:23:36、OPS代理reload UTC15:26:05。服务器时钟比本机约快216秒，本轮没有改时钟；不同来源的时间不可直接混算。

## 没有改变的边界

- 未修改演练日期、30天阈值、启动保护或把readiness硬写为通过；未做真实数据库恢复/迁移/重建。
- 原eBay受确认中心约束的草稿/发布通道配置保持；广义真实写入开关仍false。不能称“所有平台写入关闭”。本轮未执行任何eBay、订单、退款、支付动作。
- 拼嘚API/PG、其他五个捷境容器（含Vault/renewer、edge）的身份和启动时间保持，Caddy文件及运行配置不变；没有整机重启、DNS/防火墙/端口变更、续费或新增费用。
- OPS容器身份、启动时间及配置SHA保持；平滑reload仅更新其Nginx工作进程。

## 验证

独立恢复核对26/26通过，最新公开探针在本机UTC `2026-10-09T15:42:59.6768839Z`：app health200、readiness200、OPS首页200、OPS匿名权限401。实际Chrome登录及聚合数据页面另行核对。

本地 `test_jiejing_saas_production_guardrails.py` 386个负例及HTTP启动场景通过；secret scan、app.js/ops.js语法检查exit0。源码280项全量于UTC `2026-10-09T16:09:36.605019Z`（北京时间10月10日00:09:36）完成，280/280通过、exit0、source_stable/release_eligible=true，耗时2976.98秒；断言、超时、重试未改。原始完整结果在 `full-gate-node2420/SUMMARY.safe.json`，只代表对应本地源码候选，不是生产收费或新部署证明。冻结基线为commit `302ce54828bd6f38dc2107a5d2ee757953dbed20` / tree `f9044abd89a81bba09e4d89f040a88de93303dc5`；本轮没有改应用源码。

## 当前可见经营数据

后台30天窗口为2026-09-10 00:00至2026-10-09 23:26（服务器北京时间，今日未完）：访客标识42、累计商家9、窗口注册完成事件1、活跃订阅0、商业订单0、实收0元。标识可能含经营者测试；累计商家和期间注册不同口径，不计算1/42转化率、不强行归因抖音。成本覆盖不完整，6个提供商未定价，不能把显示0成本当利润证明。

## 接续事项

1. PG恢复演练过期仍是实际阻断；后续需在隔离环境开展真实恢复验收，另行明确范围，不操作/覆盖当前生产库。完成验收前不自动恢复收费开关。
2. 发布流程需补时间性冷启动检查，以及API容器换址后的OPS代理验证/解析生命周期处理；本轮只记录缺口，未宣称防复发代码已实现或部署。
3. R2显示细节修订仍未上线；不要因为受限恢复成功而重跑失败apply。
4. 全量完成后已据真实结果整理当前索引、WORK_SYNC、OPS当前状态及推广上下文，按明确路径save；成功与完整SHA以D盘 `HANDOFF_SAVE.safe.json` / `STATUS_AFTER_SAVE.safe.json` 为准，另一端需要实际receive。媒体、截图、原始日志、第三方全文只留D盘。

证据根：`D:/Codex-Verification/jiejing-ops-restricted-recovery-20261009/`。安全主回执 `RECOVERY_APPLY.safe.json`、`OPS_PROXY_RELOAD.safe.json`、`RECOVERY_VERIFICATION.safe.json`；登录截图 `OPS_LOGIN_RECOVERED.png`。本文件是安全摘要，不含密码、Cookie、环境文件内容或客户明细。
