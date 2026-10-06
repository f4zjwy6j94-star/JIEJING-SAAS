# 恢复演练证据过期与 HTTP 冷启动的最小分离

本文件是 2026-09-23 生产事故修复设计，不替代当前执行索引，也不表示修复已部署。

## 已确认的问题

旧 456 与 R6 的 API 冷启动函数相同：任何 readiness blocker 都拒绝启动。已运行服务可以继续返回健康，但重启时过期的 Vault 恢复演练证据会使同一镜像无法再启动；回滚旧镜像不能消除这个时间相关故障。生产只读诊断确认唯一备份原因是 `vault_restore_drill_overdue`，并非数据库、当前备份、Vault 解封或保管失效。

## 最小修复范围

只修改 API 的冷启动分类；既有收费、退款、eBay、候选启动和受控草稿启动边界不改。仅允许一个严格例外：

- 生产环境，production/beta/customer 仍严格为 false，reason 仍为 readiness_blocked，1 blocker / 0 warning。
- readiness items 字段合法、key 唯一，唯一非 info 项是原 backup_restore blocker；核心身份、租户、CORS、PG/迁移、队列、Worker、Vault、监控和执行桥状态有效。
- 内部 backup contract 保持原版本和 paid-launch false；真实 blocker 列表精确为一个 `vault_restore_drill_overdue`，其他缺策略、缺备份、保管不安全、无效时间等均拒绝。
- 内部 operational health 仍整体 ready、无 blockers/warnings，数据库、队列和 Vault 实时探针均 ready，secret_exposed 为 false。
- broad platform writes 仍为 false；不修改、刷新或延长任何恢复证据，不更改环境变量或业务数据。

不硬编码所有业务 info 项必须叫 ready，也不依赖脏工作树中未部署的 registration_trial_challenge 新项。基线来自冻结 456/R6 的 38 项构造；未来新增 blocker 仍按原安全逻辑拒绝。

HTTP 恢复会恢复事故前已获授权的既有服务能力，不是只读模式。收费/退款/eBay 请求分别有自己的权限、配置和确认边界，总 production_ready 并非它们的运行时总开关。本修复不增加或执行任何商业动作，公开上线准入仍阻断。

## 回归边界

现有 production_guardrails 增加完整冻结 38 项依赖投影夹具，经真实 serve_forever 分支和真实 loopback HTTP 验证 /health、/health/startup、/readiness/product-saas。外部生产依赖状态使用替身，持久化仅本地测试 SQLite；不是生产依赖集成测试。冻结原函数出现精确 blocked-production-candidate RuntimeError，修复后 HTTP 可用且准入 false、备份 blocker 和原业务 flags 未变。

负例覆盖字段/类型/重复项/缺核心项、未知或额外 backup blocker、额外 warning、安全状态及三个实时探针失败；原 candidate 与 controlled draft 测试保留。另核原 Tencent integration 中真实 build_backup_plan 的 Vault overdue 与保管故障分支。正式 apply、镜像恢复和完整部署门禁由主审在隔离同源候选上另行执行，不把脏树检查称为生产完成。
