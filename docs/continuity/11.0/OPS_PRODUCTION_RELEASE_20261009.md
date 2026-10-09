# OPS优化受控生产发布：2026-10-09

负责端：本地10.0。经营者本轮明确批准部署现有后台优化并继续修复。接收起点 `4749bc048d151d294e4629ed5e5c5df49a7e81dc`，同工作分支，正常fetch/fast-forward。本文记录准备时状态，后续以实际生成回执为准；不是预先宣称上线完成。

## 17点实际结果与收尾修订

第一候选 `d57e230524b0577bee98217a49a5ea8cb3e2a51e`（tree `7287f6185f0dae8b2ba9151c0e88ff6247ee7260`）已完整通过280/280，耗时2948.19秒，source_stable/release_eligible均true。全量报告在 `full-gate-ssd/`，旧仓库报告原样保全SHA `f613d8760668bc3db07d80a34ad4af0646d509fa73f204c0f5d4499a176b3a13`。

556文件白名单包SHA `9bd900be803fa31743223708fee9a47c09002a9ad8a0c2e4d6bc0c5db0cb284c`；manifest SHA `56109bb9742f055c156d59968e47db781242709d4c50f6511b6c4e53ddf0b941`。dry-run及apply各执行一次并exit0，apply本机UTC09:05:11–09:08:03。服务器活动路径为 `/opt/jiejing-production/releases/20261009T090923Z-d57e230524b0/app`；主机与本机时钟约有4分钟差异，保留不同来源，不改共享主机时间。部署工具已核验TLS、OPS资源原子性、匿名OPS拒绝和商家入口内部路径隔离；新生产就绪快照ready、阻断0、警告0、public_charging_allowed=true，不是新增付费订单或真实eBay成功证据。

主机前后独立21项比对全部通过，Pindd API/PG、Vault及renewer未因这次发布重启。拼嘚在另一任务先行升级了release-166，因此本次apply前基线是其新PID/启动时间；不使用本轮最早的release-158元数据夸大“整段时间无变化”。Caddy完整规范化配置SHA相同，未改其持久配置、网络或DNS。生产8组新PG查询以只读EXPLAIN（非ANALYZE）验证类型/语法，均通过，无业务行输出或改表。

Chrome实页确认新统计口径、来源表、实际健康、备份记录时间。30天42访客标识、完成注册1、累计商家9；7天13标识/23会话/114PV、注册0；订阅、商业订单及实收均0，来源全未知。口径更新与旧43/14不可直接视为流失。独立PITR输入与生产已应用回执的API接线仍未完成，界面明确显示未知/尚未接入；已获得主机回执不代表自动接线已完成。

新增收尾发现：原卡片把包含国际支付准备项的edge_cutover_preflight叫作“公网边界”，把资源标识叫作“当前代码版本”，容易与已上线现状混淆。本地已分离实时健康与“域名与回调切换预检”，将独立审批/交接包单独命名，所有blocked/unknown保留，旧复核时间统一北京时间。3个新测试先失败，修正后Node6/6、旧UI与资源版本检查通过。修订OPS版本 `ops-v1-3aaef3240f19`，尚未通过本轮新完整门禁/部署；不复用第一候选证据来冒称已上线。

完整安全摘要见同目录 `OPS_PRODUCTION_RELEASE_20261009.safe.json`。下面的准备清单是第一候选历史步骤，实际完成以本节和后续真实回执为准。

## 范围和不可越过的边界

允许捷境OPS修复的正常打包、部署dry-run、上线及只读验证。先检查共享主机、当前配置和维护锁；不改拼嘚服务/端口/存储，不重启整机，不清理全局Docker、卷或历史版本。无数据库重建/恢复、真实支付退款、eBay发布、付费投流或视频动作。失败回退只能按原部署工具的代码/配置回退边界，不回退业务数据。

完整280项是代码门禁命令，不是280个客户或商业100%。必须全部通过且source稳定/干净，随后独立核验线上实际版本、健康、资源及访问隔离。其他真实业务或PITR未测项目不得被本轮代码PASS覆盖。

## 环境诊断与被保留的失败

D盘HDD临时库这一轮07:05:32Z启动，完成104/280后受控中断。5项失败：semantic HTTP、simulation request HTTP、buyer-copy rewrite API、draft checkpoint API、listing AI browser；176项未完成，没有最终全量报告。进度所示耗时与180/600秒上限一致，但当时驱动未逐项持久化返回码，不伪造返回码证据。旧原样进度及SHA保留，状态另改为interrupted，不能继续显示running。

仅停止该轮本地测试驱动及核验归属的合成测试进程，未关闭用户Chrome/Codex，未动两项目线上。原件/失败资料不删。

单变量试验使用完全相同语义HTTP用例和断言：venv+D临时库13.223秒，base Python+D临时库14.172秒，venv+C临时库4.368秒，均exit0。SQLite提交中位D=34.708ms、C=3.474ms，回环HTTP约2ms。C为SSD，D/E/F共用同块HDD；只换到E/F不能解决此IO特征。该证据支持改测试环境，不证明五套全量都已通过。

新测试运行采用现有base Python，进程级PYTHONPATH复用D盘已锁定protobuf 5.29.6，相关腾讯运行测试已exit0；不装全局包。只在C创建新小型合成临时目录，每个检查前读磁盘余量，低于1.5GiB即停止，不删旧文件。报告/媒体/安装包留D盘。原280命令、断言、超时和重试完全保留；不改正式数据持久化设置、不关闭SQLite持久化来凑性能。

## 当前仍待真实完成

1. 审查/保存新的干净候选并读回完整SHA。
2. 同一候选完整280项通过，报告source_stable及release_eligible为真。
3. 生产只读预检共享资源、已应用版本、维护锁、持久Caddy配置及拼嘚边界；有并发维护/不明路由即不apply。
4. 原白名单工具打包，dry-run通过后受控apply；读回部署结果和独立健康/匿名隔离/OPS资源版本，用户Chrome核对显示。
5. 将实际完成或失败边界续写，保存到原分支。部署版本与后续文档提交要区分，不把文档HEAD冒称运行版本。

生产版本/时间安全回执与独立PITR目标、时间窗、恢复实测证据仍按原接收契约核对；缺失就显示缺失，不能用整体backup-ready或本地测试替代。

## 证据位置

- `D:/Codex-Verification/jiejing-ops-release-20261009/`：本轮授权、正常receive、DIAGNOSIS.safe.json、新全量与后续部署回执（未产生的回执不能预称存在）。
- `D:/Codex-Verification/jiejing-ops-followup-20261009/full-gate/progress.before-interruption.safe.json`：原104/280进度，SHA256 `cf8cc2e00727520e7d35ca101e7c8123cef717758f34d83e564d01d92a300425`。
- 原13:39–14:30的270/274失败及dirty源证据仍在原implementation目录；不重写为成功。

## 冻结期间待交接记录已保留

15:44 OPS聚合：`OPS_OBSERVATION_20261009_1544.safe.json`；每两小时任务：`GROWTH_AUTOMATION_20261009.safe.json`；新增内容策略技能：`GROWTH_TOOLKIT_ADDITION_20261009.safe.json`；V13首次2.5小时数据：`marketing/douyin-studio/operations/reviews/20261009-v13-2hour.safe.json`。它们是对应时点事实；旧记录中的pending表示当时冻结，本文合并后以实际WORK_SYNC保存回执判断是否已交出。
