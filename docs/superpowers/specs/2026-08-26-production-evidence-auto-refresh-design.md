# 捷境生产备份与监控证据自动刷新设计

## 目标

为 `app.jiejing.shop` 的正式生产主机建立每 12 小时一次的低成本证据刷新，避免 COS 备份探针和腾讯云 CLS 探针超过 24～36 小时有效期后，让产品 readiness 再次回退。

本功能只维护生产可靠性证据，不扩大业务权限。它不得调用 eBay、微信支付、退款、模型、搜索或素材服务，不得读取或输出商家内容，不得打开公开收费或真实平台写入。

## 与既有自动刷新的区别

既有 `.github/workflows/jiejing-cls-probe-auto-refresh.yml` 面向旧预发布主机和 `/opt/jiejing-staging`，依赖 self-hosted GitHub Runner，只刷新预发布 CLS 证据。

本设计面向正式生产主机和 `/opt/jiejing-production`，由本机 systemd timer 执行，同时刷新：

- COS 合成上传、读回、哈希校验和删除证据；
- CLS 合成日志上传、SearchLog 可检索和告警排除证据。

两套机制不能互相冒充，也不能共享“最近成功”时间。

## 方案选择

采用生产机 systemd timer，每 12 小时执行一次。它不依赖旧预发布主机、GitHub Runner 或人工登录，基础设施费用为零，故障边界最短。

不采用以下替代方案：

- GitHub Actions 驱动生产：依赖旧 Runner 和跨主机 SSH，增加单点与权限面；
- 人工刷新：已经证明会导致证据过期和 readiness 回退；
- 放宽 freshness 阈值：掩盖失效，不产生新证据。

## 组件

### 版本化入口

仓库新增一个生产专用刷新脚本、一个 oneshot service 和一个 timer。部署通道负责校验并把它们安装到 root 控制的位置；候选包、安装文件和当前 Git 提交必须一致。

timer 使用：

- `OnBootSec=15min`；
- `OnUnitActiveSec=12h`；
- 小范围随机延迟，避免与部署或云端整点任务重叠；
- persistent 模式，主机错过执行窗口后会补跑；
- 单实例锁，禁止两轮重叠。

### 运行时信任边界

每次运行先验证：

- `/opt/jiejing-production/app` 指向 releases 目录内的有效发布；
- SaaS 容器唯一、健康，Compose 标签与当前发布一致；
- 私有环境文件从当前容器 Compose label 解析，位于允许的 production private 目录；
- 私有环境文件为 root 所有、0600、普通文件且不是符号链接；
- 探针使用当前 SaaS 容器的精确镜像和当前发布内的工具；
- 运行前后都不打印环境变量、资源 ID、Token 或 Secret。

任一 guard 失败即结束，不运行探针、不更新时间、不重启容器。

## 数据流

1. 获取单实例锁并完成信任边界检查。
2. 在精确 live SaaS 镜像中执行 COS 合成探针。
3. 只有上传、读回哈希、删除均通过，才原子记录新的 COS 成功时间。
4. 在同一精确镜像中执行 CLS 合成探针。
5. 只有上传、可检索、字段 allowlist、告警排除和无通知发送全部通过，才原子记录 CLS 控制面与摄取成功时间。
6. 串行重建 SaaS、等待健康，再重建 Worker、等待深度健康。
7. 验证公开 `/health`、`/health/deep` 和 `/readiness/product-saas`：备份 blocker 和监控 warning 必须消失；支付 warning 可以保留；公开收费和广义真实写入仍必须为 false。

探针只使用随机合成数据。COS 对象必须在同一次运行内删除；CLS 合成事件必须带专用标记且不能命中业务告警。

## 失败与恢复

- COS 或 CLS 探针失败：不伪造对应成功时间，service 返回失败。
- COS 已成功而 CLS 失败：保留真实 COS 成功证据，但不宣称整轮成功；下一轮继续刷新 CLS。
- 环境文件更新使用现有 0600 备份和原子替换逻辑。
- API 重载失败：不继续重载 Worker，service 失败并保留旧发布目录与数据库。
- Worker 重载或最终健康失败：service 失败，可靠性告警可见；不得重放业务动作。
- 定时任务失败不会改变 eBay、收费、退款或商家配额开关。

日志只允许输出固定状态、错误分类、时间和布尔值；不得输出原始探针 JSON、环境值或云资源标识。

## 部署与回滚

生产部署 dry-run 只验证文件、权限意图和 unit 合同，不安装或启动 timer。apply 成功切换并通过健康检查后，才原子安装脚本和 units，执行 daemon-reload 并启用 timer。

首次安装后手动运行一次 oneshot 作为验收。若安装或首次运行失败，保持应用版本在线，但 timer 不得被标记为健康；回滚可禁用 timer 并恢复上一个 root 控制脚本和 unit 版本。

## 验证标准

- 静态合同覆盖路径、权限、精确镜像、合成探针、无业务 provider、无 Secret 输出和失败短路。
- 测试覆盖 COS 失败、CLS 失败、JSON 非法、文件权限错误、容器标签错误、API/Worker 健康失败和重复运行锁。
- `node --check app.js`、专项测试、Secret 扫描和完整 precloud gate 全部通过。
- 生产 deploy dry-run 与 apply 均通过。
- systemd timer 显示 enabled/active 且下一次执行时间存在。
- 首次 oneshot 成功后，公开 readiness 为 0 blocker，且不再包含 monitoring warning。
- `public_charging_allowed=false`、`real_platform_writes_enabled=false`、`secret_exposed=false` 保持不变。

## 非目标

- 不执行或重试 eBay Offer 发布；
- 不重复 OAuth 或 eBay 只读同步；
- 不执行真实收费或退款；
- 不修改 PostgreSQL 备份策略、PITR 策略或恢复演练记录；
- 不替代每月恢复演练；
- 不把 HTTP 200 当作公开收费或真实发布就绪。
