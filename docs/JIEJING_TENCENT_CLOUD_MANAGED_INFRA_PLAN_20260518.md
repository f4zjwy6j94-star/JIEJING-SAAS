# 捷境腾讯云托管基础设施计划

日期：2026-05-18

目标：把当前 staging 从“单机 SQLite / local worker / 本地或自管密钥”推进到低成本、可扩展、可恢复的腾讯云托管底座。范围只包括 4 项：PostgreSQL、Redis、SSM/KMS、CLS/COS 监控备份。

## 当前事实

- 当前公网 staging：`https://mentioned-shake-inter-critical.trycloudflare.com`
- 当前服务器：腾讯云广州，`ap-guangzhou`，可用区 `ap-guangzhou-4`
- 当前内网 IP：`10.1.0.11`
- 当前部署通道：`agentuser@42.194.158.47`
- 当前 eBay OAuth 和官方只读同步已经完成，不重复授权、不重复同步。
- 当前真实平台写入仍关闭：`JIEJING_ENABLE_REAL_PLATFORM_WRITES=false`

## 总原则

1. 先 staging，后 production。
2. 先低成本，能跑通后再升级。
3. PostgreSQL、Redis 和服务器保持同地域、同 VPC，优先走内网。
4. 数据库和 Redis 不开公网访问，除非临时排障且有明确关闭时间。
5. eBay token、模型 key、搜索 key 不进入前端、不进入 Runtime、不进入数据库原文字段。
6. 任何真实 eBay 写入、付款、退款、广告、政策修改仍必须走确认中心。

## 1. PostgreSQL

用途：替换 SQLite，保存用户、公司、店铺、授权连接、标准数据包、任务、报告、确认中心、审计日志。

推荐腾讯云产品：云数据库 PostgreSQL（TencentDB for PostgreSQL）。

低成本建议：

- 地域：广州 `ap-guangzhou`
- 可用区：优先选择和服务器同可用区 `ap-guangzhou-4`，如果页面没有同区可选，选择同地域广州即可。
- 网络：选择当前服务器所在 VPC 和子网。
- 计费：前期优先按量计费或最短周期包年包月，确认稳定后再长期购买。
- 规格：选择最低可用生产规格，能支持连接池和自动备份即可。
- 存储：小容量起步，后续按实际标准数据包和报告数量扩容。
- 访问：只允许内网访问，不开放公网。
- 备份：开启自动备份，保留至少 7-14 天；正式商用前需要恢复演练。

捷境环境变量：

```env
JIEJING_DATABASE_ENGINE=postgres
JIEJING_DATABASE_ADAPTER=postgres-managed
JIEJING_DATABASE_URL=postgresql://<user>:<password>@<postgres-private-host>:5432/<db>
JIEJING_POSTGRES_DRIVER_CHECK_LIVE=true
```

切换步骤：

1. 创建 PostgreSQL 实例。
2. 创建 `jiejing` 数据库和专用账号。
3. 服务器内网连接测试。
4. 运行 `001_initial_schema_postgres.sql`。
5. 用迁移工具把 SQLite staging 数据导入 PostgreSQL。
6. 开启后端 Postgres adapter。
7. 验证登录、店铺、标准数据包、报告、确认中心、审计日志。

## 2. Redis / 云队列

用途：替换 local worker 队列，让 eBay 同步、AI CEO 报告、provider jobs 进入稳定排队系统。

推荐腾讯云产品：云数据库 Redis（TencentDB for Redis）。

低成本建议：

- 地域：广州 `ap-guangzhou`
- 网络：和服务器同 VPC。
- 架构：前期选择低配标准版即可，不需要一开始上大集群。
- 访问：只允许内网访问。
- 密码：启用访问密码，放入 SSM/Vault，不写入代码。
- 备份：开启默认备份。

捷境环境变量：

```env
JIEJING_QUEUE_PROVIDER=redis_streams
JIEJING_QUEUE_URL=redis://:<password>@<redis-private-host>:6379/0
JIEJING_REDIS_STREAM=jiejing:queue
JIEJING_REDIS_DEAD_LETTER_STREAM=jiejing:queue:dead
JIEJING_REDIS_DRIVER_CHECK_LIVE=true
```

切换步骤：

1. 创建 Redis 实例。
2. 服务器内网 `PING` 测试。
3. worker 切换到 Redis Streams。
4. 发起一个非写入任务，确认任务进入队列、被 worker 消费、失败能进入 dead-letter。
5. 前端展示任务状态：排队中、执行中、成功、失败原因。

## 3. 正式保险箱：SSM + KMS

用途：保存 eBay refresh token、eBay client secret、模型 key、搜索 key、物流/采购 key。

推荐腾讯云产品：

- SSM 凭据管理系统：保存、读取、更新、删除凭据。
- KMS 密钥管理系统：为 SSM 凭据提供加密密钥底座。

重要判断：

- KMS 主要管理“加密钥匙”。
- eBay token 这种字符串凭证更应该放 SSM。
- 所以本项目实际要开的是“SSM 凭据管理”，并确认它使用 KMS 加密。

低成本建议：

- 地域：广州 `ap-guangzhou`
- 凭据命名：统一 `jiejing/staging/<company_id>/<store_id>/<purpose>/<secret_ref>`
- 权限：只给 staging 服务器角色读取必要凭据。
- 禁止：前端、Runtime、Agent 直接读取 SSM。

捷境目标环境变量：

```env
JIEJING_VAULT_ENABLED=true
JIEJING_VAULT_PROVIDER=tencent_ssm
JIEJING_TENCENT_REGION=ap-guangzhou
JIEJING_TENCENT_SECRET_ID_REF=<server-role-or-ssm-ref>
JIEJING_TENCENT_SECRET_KEY_REF=<server-role-or-ssm-ref>
JIEJING_VAULT_KEYSPACE=jiejing-staging
JIEJING_VAULT_LIVE_RESOLVE_ENABLED=true
```

当前代码状态：

- HashiCorp Vault resolver 已实现。
- Tencent KMS/SSM 目前是 adapter contract，还需要实现真实 SSM HTTP/API client 后，才能把 `JIEJING_VAULT_PROVIDER=tencent_ssm` 作为生产路径。
- 如果要最快跑通 staging，可以先在腾讯云服务器上继续用 HashiCorp Vault；如果目标是腾讯云托管保险箱，则下一步必须补 Tencent SSM resolver。

切换步骤：

1. 开通 SSM。
2. 创建 KMS 默认或专用加密密钥。
3. 创建测试凭据。
4. 实现并测试 Tencent SSM resolver。
5. OAuth callback 写 refresh token 到 SSM。
6. eBay 同步时后端按 `secret_ref` 读取 SSM，Runtime 只拿标准数据包。

## 4. 监控和备份：CLS + COS

用途：发现错误、追踪同步失败、保留审计线索、保存备份导出。

推荐腾讯云产品：

- CLS 日志服务：采集应用日志，做检索、告警、仪表盘。
- COS 对象存储：保存数据库导出、恢复演练记录、长期归档。

低成本建议：

- CLS：
  - 只采集 SaaS backend、worker、nginx/frontend 关键日志。
  - 日志保留先设置较短周期，例如 7-14 天。
  - 只建关键告警，不做大规模日志分析。
- COS：
  - 建一个私有 bucket。
  - 生命周期规则：旧备份转低频/归档或定期删除。
  - 不公开访问。

必须告警：

- `/health` 不可用
- OAuth callback 失败
- eBay sync 失败
- Redis 队列堆积或 worker 无心跳
- PostgreSQL 连接失败
- Vault/SSM 读取失败
- 备份任务失败

捷境环境变量：

```env
JIEJING_LOG_PROVIDER=cls
JIEJING_CLS_REGION=ap-guangzhou
JIEJING_CLS_LOGSET=jiejing-staging
JIEJING_CLS_TOPIC=saas-backend

JIEJING_BACKUP_PROVIDER=cos
JIEJING_COS_REGION=ap-guangzhou
JIEJING_COS_BUCKET=jiejing-staging-backups-<account>
JIEJING_BACKUP_POLICY_CONFIGURED=true
JIEJING_BACKUP_ALERTS_CONFIGURED=true
```

切换步骤：

1. 创建 CLS logset/topic。
2. 配置服务器日志采集。
3. 创建基础告警策略。
4. 创建 COS 私有 bucket。
5. 配置数据库导出/备份记录投递。
6. 做一次恢复演练，并记录 `JIEJING_RESTORE_DRILL_LAST_AT`。

## 开通顺序

1. PostgreSQL
2. Redis
3. SSM + KMS
4. CLS
5. COS

## 控制台购买前检查

- 是否是广州地域。
- 是否和服务器同 VPC。
- 是否关闭公网访问。
- 是否选择最低可用规格。
- 是否开启自动备份。
- 是否没有开启不必要的高可用、大集群、跨地域复制、长保留日志。
- 是否没有把密码、token 填进前端或 Git 文件。

## 完成标准

这 4 项真正完成，不是“页面上买了资源”，而是：

```text
Postgres live check = ok
Redis live check = ok
SSM/Vault live resolve = ok
CLS receives backend/worker logs
COS has backup artifact
restore drill recorded
precloud gate still passes
ready_for_paid_commercial_launch 仍可能 false，但生产基础设施百分比应明显提升
```

