# 捷境 SaaS 产品化六阶段进度

更新时间：2026-05-15

## 当前推进方式

不再按固定时间自动运行。改为按完成度推进：阶段 1 达到可验证标准后，再进入阶段 2。每次只做当前阶段最关键的增量，必须测试通过，不能虚报真实接入。

## 阶段 1：正式 SaaS 后端中控

当前进度：90%-92%

本轮完成：

- 暂停了每小时定时自动化，避免盲跑和重复改动。
- 新增团队角色权限合同：`owner`、`admin`、`operator`、`viewer`。
- 新增团队邀请表 `team_invitations`。
- 新增团队成员、邀请、公司切换、当前权限接口。
- 新增高风险确认权限边界：`operator` 不能批准发布、退款、改价、广告、采购付款等高风险确认项。
- 新增 PostgreSQL 生产初始迁移脚本：`jiejing_saas/migrations/001_initial_schema_postgres.sql`。
- 数据库计划接口现在会暴露已准备好的 PostgreSQL migration 文件。
- 新增数据库 adapter 合同：`sqlite-local`、`postgres-managed`、`mysql-managed`。
- 新增队列 adapter 合同：`local_worker`、`redis_streams`、`tencent_cloud_queue`、`aliyun_message_queue`。
- 新增完成度门禁脚本：`tools/jiejing_productization_stage_gate.py`。它不按时间跑，只按阶段验收项判断是否可以进入下一阶段。

已验证：

- 本地注册、登录、公司、成员、角色、切换公司、邀请流程通过。
- 租户隔离仍然有效。
- 任务队列、Runtime 回写报告、确认中心、执行服务模拟链路没有被破坏。
- 生产环境 guardrail 仍然会阻止本地 SQLite/本地队列/Vault 未接入状态下启动为 production。
- `operator` 角色无法批准高风险确认项。
- 阶段 1 门禁已可检查：团队权限、数据库 adapter、PostgreSQL 迁移、队列 adapter、本地 worker 形态、确认中心执行边界。

仍未完成：

- 还没有真的连接托管 Postgres / MySQL。阶段 1 已完成 adapter 和 migration 形态，真实连接属于部署/云资源落地。
- 还没有云队列 / Redis / 死信队列 / worker heartbeat。阶段 1 已完成 adapter 合同，真实连接属于部署/云资源落地。
- 还没有正式登录体系、MFA、密码找回、企业成员邀请邮件。
- 还没有把团队权限 UI 做到正式产品级。
- 还没有正式部署到腾讯云或阿里云。

下一步：

1. 跑阶段门禁脚本，确认阶段 1 是否允许进入阶段 2。
2. 若门禁通过，进入阶段 2：eBay 只读接入。
3. 阶段 2 第一批只做只读 data packet，不做任何真实写入。

## 阶段 2：eBay 只读接入

当前进度：73%-76%

本轮新增：

- 增加 `store_profile` 只读资源，用于读取店铺身份、站点、额度和账号状态。
- 增加 eBay 只读 workflow plan：先检查租户/店铺权限，再走 Vault token、短期 access token、资源读取、脱敏、缓存 data packet、交给 Runtime。
- data packet 增加 `present_resource_keys`、`missing_resource_keys`、`section_summary` 和 `readiness_for_modules`。
- Runtime 只能拿到脱敏后的 data packet，不能拿原始 eBay response 或 access token。
- 新增 eBay 只读字段合同：`store_profile`、`account_business_policies`、`inventory_and_offers`、`orders_and_fulfillment`、`finances`、`taxonomy_listing_metadata`、`marketing_readonly`。
- data packet 会记录每个资源缺哪些 required fields，避免报告把不完整样本当成真实数据。
- 新增 eBay live read adapter 合同：定义正式读取时的 route、standardizer、guardrail 和 blocker，但当前保持禁用。
- 新增 eBay read normalizers：把 eBay/导入样本字段标准化成捷境统一字段，再脱敏进 data packet。

已覆盖的只读目标：

- 读取店铺基础信息。
- 读取 Listing / Inventory / Offers。
- 读取订单和履约状态。
- 读取费用和交易流水。
- 读取物流、支付、退货三类 policy。
- 读取 Taxonomy / Category / Item Specifics。
- 所有读取结果进入 data packet，不直接散落到前端。

仍未完成：

- 还没有真实调用 eBay API。
- 还没有从 Vault/KMS 解析 refresh token。
- 还没有实现 eBay live read HTTP adapter。当前只有 route contract 和 normalizer，真实 HTTP client 仍为 blocker。
- 还没有把真实读取任务放入云队列。

下一步：

1. 增加 eBay 只读 live adapter 的接口文件，但默认保持关闭。
2. 增加各资源的 endpoint mapping、请求参数和标准化函数骨架。
3. 在没有真实 token 时继续返回 source_gap，不能假装读到了真实数据。

## 阶段 3：Vault/KMS 密钥边界

当前进度：55%-60%

下一阶段目标：

- 接腾讯云 KMS、阿里云 KMS 或 Vault 的真实 adapter。
- 数据库只保存 `secret_ref`。
- eBay refresh token、模型 key、搜索 key、图片视频 key、物流/采购 key 不进前端、不进普通数据库、不进报告。

## 阶段 4：Runtime 驱动前端工作流

当前进度：88%-90%（Runtime 底座），前端动态接入仍未完全完成。

下一阶段目标：

- 首页、产品刊登、素材工坊、批量铺货、AI 汇报、确认中心、自动客服、连接账号逐步改成读 SaaS Backend / Runtime 输出。
- 静态演示数据保留为 fallback，不再作为主路径。

## 阶段 5：自研 Agent 替代 Hermes 能力

当前进度：55%-60%

下一阶段目标：

- 市场、产品、素材、客服、财务、风控、AI CEO 继续沉淀为捷境自研 Agent。
- 与 Hermes 同题双跑，质量稳定后替代低风险任务。
- Hermes 保持内部执行底座，不作为公开产品名。

## 阶段 6：真实 eBay 自动化闭环

当前进度：35%-40%

下一阶段目标：

- 顺序必须是：只读接入 -> AI 报告 -> 刊登草稿 -> 人工确认 -> 保存草稿/低风险执行 -> 真实发布/改价/退款/广告等高风险动作。
- 所有真实发布、改价、库存、退款、广告预算、采购付款、policy 修改和敏感客服承诺必须进入确认中心。
