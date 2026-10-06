# 捷境正式生产部署手册（2026-08-23）

## 目标

本通道只面向捷境正式生产主机。它把“上传文件后临时手工操作”收口为：候选包校验、`dry_run`、原子切换、健康检查和失败自动回滚。

候选包只包含代码和公开资源，**不复制任何密钥**。生产环境变量、微信支付配置、eBay 凭据引用和 Vault token 继续留在服务器私有目录；日志和输出也不得打印这些值。

## 固定边界

- 默认动作是 `dry_run`，只验证候选发布，不切换线上服务。
- 正式应用必须输入完整确认语：`deploy app.jiejing.shop production`。
- 发布前 Git 工作区必须干净，候选包 SHA-256 必须与清单一致。
- 候选必须先在同一干净commit/tree完整运行当前门禁；新报告绑定检查有序清单、全部结果及开始/结束源状态。脏目录、运行中变化、assume-unchanged/skip-worktree隐藏修改、旧版/错源/缺项报告均不得打包。打包和部署前共同验证清单中的脱敏门禁证明；这不是线上健康或真实业务执行证明。
- 发布不会主动发起真实扣款、退款或 eBay 写入。
- 当前部署只重建 SaaS、Worker、商家前端、独立运营前端与边缘代理；不会删除数据库、Docker volume 或 Vault 数据。
- `dry_run` 不获取任何锁，不调用 `systemctl`，也不运行 COS/CLS 探针；它在创建 `/tmp/jiejing-production-dry-run-*.d` 之前安装清理 trap，完成 wrapper `bash -n`、固定 unit 合同和安装意图校验后自动删除；`HUP`、`INT`、`TERM` 和正常/异常退出均进入不可被二次可捕获信号打断的清理。成功必须精确输出 `CANDIDATE_RELEASE_PERSISTED=0`、`ACTIVE_SWITCHED=0` 以及不含值的 private env 权限规范化布尔，不会在 production release root 留下目录。
- 正式 apply 先持有 deploy-only `/run/lock/jiejing-production-deploy.lock`，再持有与证据刷新共享的 `/run/lock/jiejing-production-maintenance.lock`，避免两个部署互相穿插或刷新任务撞上容器切换。
- 正式 apply 必须先取得上述双锁，才允许读取 active release、容器环境文件标签和 private-dir 等 live snapshot，更不能提前在 production release root 创建永久候选目录。

## 旧机运营入口合并：候选合同（2026-09-13）

这是一份迁移候选要求，不是“已经完成迁移”的记录。配置归档、隔离恢复、运营域名切换和旧机停用分别验收；任一项通过都不能代替其余项。

- 新机 `jiejing-ops-frontend` 只挂载 `ops.html`、`ops.js`、`ops.css`、两个品牌 SVG 和 `assets/jiejing-ops-panels.js` 六项公开资源。清单独立绑定六项 SHA-256，HTML 的三个实际样式/脚本引用必须同版本、唯一、来自本域。禁止把完整商家目录、private env 或 Vault volume 挂入运营前端。
- 专用 `jiejing_ops` 内部网络仅连接运营 Nginx、边缘 Caddy 和 SaaS API。Nginx 无宿主端口，不属于 Vault 网络；非 `ops.jiejing.shop` Host 默认 404。精确路径与方法继续沿用现有后台授权合同，内网代理明确传递 HTTPS。退款执行入口保留，但迁移验证不得发起真实退款或收费。
- `ops.jiejing.shop` 和 `jiejing.shop` 都必须在新源站正常验证 TLS。Caddy 继续托管 ACME；不得改为永久手工 `tls cert key`、关闭校验、切换 Cloudflare 代理模式或新增 DNS 凭据来绕过预检。旧 Caddy 中这两个准确域名的有效存储材料由另一批受审后端工具导入；本发布通道不读私钥正文、不创造证书或凭据。
- 创建正式候选目录前，发布脚本只检查新机 Caddy 固定存储中的公证书 SAN、公开链、至少七天有效期及私钥的文件类型/权限/身份元数据。材料缺失、过期、路径异常都拒绝；这一步不证明公私钥匹配，匹配须由后续正常 TLS 握手证明。
- 若上一发布不含独立 ops 与 apex，首次迁移 dry-run/apply 必须仍能确认 DNS-only `ops` 解析到旧机 `43.129.205.244`。这只是过渡保护，不是 apex 的代理 IP 证明；首次成功的新发布应成为后续完整回滚基线。
- 发布后先在新机 loopback 使用真实域名、正常链校验和 `--resolve` 校验六资产哈希、匿名 API 401/403、未知后台路径 404、商家域名下后台资产/API 404，并验证 apex 的精确 301 跳转及保留路径/查询参数的 Location。这里与 Caddy `permanent` 及 commit `3b20b33` 的受审验收一致，不再沿用旧文档的 308 要求；不是同时接受任意 3xx。成功回执包含 `OPS_STORED_CERTIFICATE_PREFLIGHT=1`、`OPS_LOCAL_TLS_ASSETS_ISOLATION_VERIFIED=1`；dry-run 后者必须为 0。loopback 验收不是外网可达性证明。
- 切 DNS 前另从外部以 `curl --noproxy '*' --resolve ops.jiejing.shop:443:43.129.169.223 https://ops.jiejing.shop/` 和同方式的 apex 检查正常 TLS，不加 `-k`，并复核六资产/匿名权限/商家隔离。先通过本地后台角色专项与外网源站检查，再按已批准迁移计划切换域名；不在此步骤登录后台执行资金动作。
- 故障回滚始终先恢复商家应用。上一发布支持 ops 时也恢复 ops 并重验本地 TLS/隔离；不支持时只停止本候选、经名称和 Compose 标签核对的精确运营容器 ID，不删除容器、卷或共享数据库。旧发布缺 ops/apex 时，即使 DNS-only `ops` 仍在旧机，也不能据此判断代理中的 apex 已回旧源站：输出 `APPLICATION_RELEASE_RESTORED=1` 与 `OPS_APEX_TRANSITION_ROLLBACK_REQUIRES_VERIFICATION=1`，整体回滚仍判失败，须核对两个准确 DNS 记录并复验。若 `ops` 不在旧机，另输出 `OPS_ROLLBACK_NEEDS_DNS_CUTBACK=1`。不得把商家恢复误报为全部恢复。
- 旧机退出前必须已有可独立恢复的材料保管、旧 Vault v3 材料匹配、所有未决数据保全和稳定观察证据，并至少有一个同时支持 ops/apex 的可回滚发布。此合同本身不授权停旧机、删除数据或放弃续费。

本地专项：`python tools/test_jiejing_production_ops_consolidation.py`，并继续运行部署通道、生产 Compose、后台权限与退款授权专项。完整发布门禁必须绑定最终干净候选；局部测试通过不能冒充完整门禁或生产发布成功。

运营缓存版本规则：固定三项 `assets/jiejing-ops-panels.js`、`ops.css`、`ops.js` 分别按 UTF-8 解码，将 CRLF/CR 规范为 LF 后计算完整 SHA-256；以名称为键排序、无多余空格 JSON 序列化，再取该 JSON SHA-256 的前 12 位组成 `ops-v1-<hash>`。三个真实加载 URL 必须使用这个准确版本。更新资源时必须同步更新 `ops.html` 三引用；仅更新 manifest 哈希而沿用旧 URL 会被拒绝，避免浏览器 immutable 缓存继续运行旧资源。清单中的文件哈希仍校验未经规范化的原始 bytes。

## 标准顺序

```powershell
python tools/jiejing_secret_scan.py
python tools/test_jiejing_production_deploy_channel.py
python tools/jiejing_precloud_deployment_gate.py
python tools/jiejing_prepare_public_staging_bundle.py

python tools/jiejing_production_deploy.py `
  --bundle output/jiejing-public-staging-bundle/<bundle>.zip `
  --manifest output/jiejing-public-staging-bundle/<bundle>.manifest.json `
  --mode dry_run
```

只有 dry-run、CI 和生产前验证全部通过后，才允许执行：

```powershell
python tools/jiejing_production_deploy.py `
  --bundle output/jiejing-public-staging-bundle/<bundle>.zip `
  --manifest output/jiejing-public-staging-bundle/<bundle>.manifest.json `
  --mode apply `
  --confirm "deploy app.jiejing.shop production"
```

## 验收标准

部署脚本必须验证：

- `/health` 为 `status=ok`；
- `/health/deep` 为 `status=ready`；
- `/readiness/product-saas` 不暴露密钥；
- 正式收口时进一步要求 `production_ready=true`、`can_accept_real_customers=true`、`warning_count=0`；
- 失败自动回滚到上一个发布目录；
- 当前符号链接、容器 Compose 标签和发布清单指向同一版本。

真实扣款、退款或 eBay 写入不属于部署验收。即使部署通过，这些动作仍必须进入确认中心并在动作前获得单独确认。

## 独立运营后台不是本通道的自动发布目标

`ops.jiejing.shop` 当前由旧运营主机提供；本通道更新 `app.jiejing.shop` 的生产发布目录，不会自动更新旧主机的静态文件、API或代理规则。主站成功不能直接表述为“全站前后端已同步”。

当修改 `ops.html`、`ops.js`、`ops.css`、`assets/jiejing-ops-panels.js`、运营代理规则或运营专用API时，整体功能验收还必须核对：

- 实际运营页面引用的版本和返回资产哈希与候选一致；不能只检查HTTP 200或页面标题。
- 运营端实际反代的API包含本次处理器；静态文件更新不能替代后端更新。
- 所需路径和HTTP方法在ops域精确开放，未登录/非运营身份仍被拒绝，商家域内部路径仍404。
- 退款provider能力布尔与“运营界面能完整申请/审核/执行/查询”分开记录；禁止为验证部署而实际退款。

独立运营端按既有GitHub手动发布规范处理；不要发现版本不一致后盲目运行旧SSH staging全量覆盖脚本。若需使用规范外的专门SSH发布，先获得明确例外授权并准备前后端同版校验和可恢复方案。只读确认是同一数据库时，不因连接地址文字不同就迁移数据库或修改DNS。

## 证据刷新 unit 独立事务

应用健康并切换 active link 后，部署才原子安装证据刷新 wrapper（`0755 root:root`）和两个 unit（`0644 root:root`）。安装过程执行 `systemd-analyze verify`、`daemon-reload` 和 timer enable，但不会在维护锁释放前启动探针。

维护锁释放后，部署手工启动一次 oneshot，并以本次 `InvocationID` 对应 journal 中的 `JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success`、service `Result=success`、`ExecMainStatus=0` 为真实成功条件。随后才启动 timer，并确认 enabled、active 且 `NextElapseUSecRealtime` 有值。

oneshot 会分别捕获当前 SaaS API 与 Worker 的实际 image ID；两个 ID 可以不同，但必须各自为可检查的 `sha256`，且各自的 image reference、Compose project/service/config/workdir/environment-file label 和运行状态都与 active release 精确一致。COS、CLS 和探针工具存在性检查明确只运行在已验证的 API 镜像中。证据快照版本不再例行重建 API/Worker：探针前校验双镜像协议和固定只读目录挂载，全部探针成功后导出六项证据；刷新后及公共健康等待后均要求原容器 ID、原镜像及挂载未变，任一缺失、漂移或交叉交换都会 fail-closed。

## 证据快照首次迁移与日常刷新（2026-09-08）

候选构建并取得精确 API/Worker 镜像后，必须先验证或创建 `/opt/jiejing-production/runtime-evidence`（`root:root 0755`），校验双镜像协议，再以候选 API 镜像、无网络、私有目录只读挂载生成 `current.json`（`root:root 0644`）。只有固定脱敏回执校验通过才输出 `EVIDENCE_SNAPSHOT_INITIALIZED=1` 并启动候选服务；它只是导出已有真实证据，不执行探针、不更新成功时间。dry-run 对应标记为 `0`，不创建证据目录或快照。现有目录权限不可信时停止，不自动修复覆盖。

API/Worker 将整个目录只读挂到 `/run/jiejing-production-evidence`，使用固定 `JIEJING_RUNTIME_EVIDENCE_FILE`；不能改成单文件挂载，否则原子替换后会仍读到旧 inode。备份与监控每次构造从完整快照读取；显式配置后文件缺失、损坏、字段不符或权限不可信均视为证据不可用，不回落进程旧 env。旧镜像没有配置该选择器时继续使用旧 env，便于回滚。

日常保留原探针、锁、时效与环境漂移保护，探针成功写回原 env 后才原子发布六项非秘密快照。env 与快照不是双文件事务：中途失败保留真实已取得的 env 证据，不伪造整轮成功；rename 前失败保留旧快照，rename 后目录 fsync 失败可能已可见完整新文件，但仍不报告成功或保证掉电持久性。应用回滚保留 env、快照、数据库与恢复材料，不删除或倒退真实证据。此方案减少日常维护重启，不承诺代码发布零停机或所有历史502已解决。

安装后必须确认 service 与 timer 的实际属性都严格返回单行 `DropInPaths=`；缺少该属性或返回任何路径都会 fail-closed，拒绝来自 `/etc`、`/run` 或 `/usr/lib` 的旧 drop-in 覆盖固定 `ExecStart` 与沙箱合同。生产 apply 的 SSH 客户端超时预算固定为 `3600` 秒，以覆盖最长 20 分钟 oneshot、应用健康等待与镜像构建余量。

apply 会在构建前从当前 release manifest 唯一解析 `PRIVATE_DIR`，与运行容器的 environment-file label 交叉验证，并只通过 `O_NOFOLLOW` 文件描述符把该目录规范为 `root:root 0700`、两个 env 文件规范为 `root:root 0600`；不会读取或输出文件内容。SaaS 与 Worker 会分别保存构建后实际 image ID；两个 ID 可以不同，但候选启动和最终收口都必须逐服务匹配各自已保存的 ID、Compose labels、workdir、environment-file 和健康状态。

构建前，当前 SaaS 与 Worker image ID 会分别固定到 root 控制的 `jiejing-production-rollback-api:previous` 和 `jiejing-production-rollback-worker:previous`；固定、回读或半创建恢复失败都会在 build、容器、active link 和 unit 变更前停止。这两个 hold refs 至少保留到完整成功或完整回滚，并作为最近一版人工回滚证据；部署路径禁止 image prune。若 wrapper/unit 安装、首次 oneshot 或 timer 验收失败，部署会从 hold refs 恢复 live image refs，同时恢复三个 root 文件、原 timer 状态和旧 active release。失败输出包含 `TIMER_INSTALL_ROLLED_BACK=1`、`APPLICATION_RELEASE_RETAINED=0` 和 `JIEJING_PRODUCTION_ROLLBACK_APPLIED=1`；只有完整验证旧双 image ID、容器 labels 与健康状态后才允许报告回滚成功。

unit 事务期间的 `HUP`、`INT`、`TERM` 和异常 `EXIT` 会进入同一独立回滚；回滚时忽略二次可捕获信号，避免递归。`SIGKILL` 和整机断电无法被 shell 捕获，因此部署后仍必须按本节 markers、root 文件和 timer 状态完成验收。
