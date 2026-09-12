# 旧40GB主机合并：三阶段实施清单

日期：2026-09-12。设计：`../specs/2026-09-12-old-host-consolidation-design.md`。用户已确认按推荐三个阶段推进。本计划不代表任何阶段已完成；实际结果只维护在当前执行索引。

## Phase 0：文档发现（已完成）

- SSH与不泄露原始输出的本地回执：任务目录`output/host-retirement-audit-20260912/audit_new_host_capacity.py`的`environment/main`；旧机SSH路径取同目录`audit_old_host_r3.py`。必须保留PROGRAMDATA、严格known_hosts、BatchMode、限定目标、固定错误分类。
- 流式hash：`tools/jiejing_production_deploy.py:774`；排他创建/fsync可参考`tools/jiejing_vault_recovery_drill.py:151`。禁止直接复用其整包read_bytes和自定义AESGCM格式。
- 本机GnuPG2.4.9、GNU tar1.35已存在于`D:/软件/Git/usr/bin`；D盘NTFS约239GiB空闲。Linux端版本/选项仍需只读核验。GPG用成熟OpenPGP格式；收件人恢复材料须先验证，不虚构已有恢复密钥。
- Windows专用目录ACL模式：`tools/jiejing_vault_production_grade_rehearsal.py:544`附近当前用户/SYSTEM/Administrators ACL设置和回读。只移植此模式，不运行E/F硬编码演练。
- 旧Vault `deploy/vault.public-staging.hcl`为file存储；归档一致性与新生产纸质解封材料是两个问题。旧材料可恢复性未证明前不停止旧Vault。
- `deploy/Caddyfile.production`/`deploy/docker-compose.production-pilot.yml`无ops/apex；`deploy/Caddyfile.public-staging.systemd`有apex308，`deploy/nginx.public-staging.conf`有ops精确方法/路径参考；仅复制ops合同，不直接启整份旧staging配置。
- `api_server.py:11880`精确ops Host与`:12686`内部名单+owner/admin规则；运行时同库/身份/存储兼容须单独核验。不执行worker CLI status、Repository.initialize或完整readiness builder作为只读身份探针。
- 官方生产deploy/runbook是唯一主站改动路径；不能靠新机临时热改Caddy或另起旧Compose规避未来部署覆盖和回滚。

## 第一阶段：迁移保全

1. 复制已审查SSH封装，新增固定新/旧目标的只读能力与容量补查工具；只输出GNU tar/GPG选项布尔、完整预算范围的计数/大小、固定类别缺口。不得输出原环境、进程参数、cron命令或文件内容。不重复已有5容器审计。
   可在控制台确认免费配额与无需关机后，创建唯一迁前系统盘快照作为临时保护；运行中快照不是应用一致性备份。Lighthouse实例销毁会连带删除快照，不能把它当退役后的独立副本（腾讯云`https://cloud.tencent.com/document/product/1207/48546`）。
2. 按实际证据完成持久路径范围及排除项；所有未分类用户数据保留，Docker overlay/日志/运行配置须明确归档或可验证重建策略。元信息预算不是最终可恢复归档。
3. 创建专用D盘受限恢复目录和新机私有归档目录，验证空间/ACL/无链接/排他写入。ACL不能只检查已有ACE，还需核对Owner、根继承保护、当前用户/SYSTEM/Administrators必需权限及路径链无重解析点。先确认成熟加密收件人材料及恢复路径，进行小型非业务样本的加密→传输→隔离还原；只返回结果，不回显密钥。工具自动生成保护口令，不要求用户自设；受保护私钥导出包/keyring与本机DPAPI密文保留，失败不自动覆盖重生成。先在新隔离keyring导入、关闭仅该keyring的agent缓存后，验证错误口令拒绝及DPAPI恢复口令解密成功；此样本只证明当前Windows身份的本机恢复，不证明跨机或Windows身份丢失后的灾备。独立恢复材料交接/托管未验证前，不完成第一阶段、不释放旧机。
4. 静态预归档；可变数据在旧写入者安全暂停并具备旧Vault恢复条件后作一致性备份。首轮恢复旧写入后标记增量待补。新机保留至少10GiB空闲，D盘另有独立密文副本。
5. 用固定清单与分段hash记录传输；中断不覆盖已验证段、不删除源。Linux恢复验证权限/ACL/xattr/链接/稀疏，不在Windows解包冒充完整恢复。

验证：本地fixture覆盖无工具/错误host/输出拒绝/超时/文件冲突/空间不足；执行前固定工具hash并独立审查；受控真实回执；零服务变更探针与备份阶段分别标记。最终业务归档与keyring均不进Git。

禁止：整盘覆盖生产、docker down -v、卷删除、rsync --delete、打印原日志/密钥、未核验即解包或执行旧程序。阶段验收缺失则保留旧机运行。

## 第二阶段：切换验证

1. Cloudflare正确账户与4条A记录已只读取得，回滚值见任务`output/host-retirement-audit-20260912/cloudflare-domain-readonly.json`。仅根域/ops从旧机迁至新机，保留根域proxied、ops DNS-only及各自Auto TTL，app/pilot不动；不新增www/AAAA/CNAME。根域已有边缘HTTPS 301跳app，保留规则，不推断所有根域请求到旧源；旧cloudflared职责仍需单独确认。ops保持DNS-only，须先证明新机可提供浏览器可信证书和公网可达；与app/apex/pilot源站保护成对验收，不能套全局CF-only规则或直接运行旧UFW脚本。后者实际默认放行全部IPv4的80/443，不能被脚本名误导。核对云防火墙、宿主过滤和Docker转发，只补实际缺口，切换前再次核对回滚值。
2. 核对生产ops资格、DB身份、Vault引用、退款能力配置及旧Worker/runner/cron职责，只读且不调provider。未知即不切换。
3. 在现有生产部署路径版本化加入apex/ops Caddy、专用ops Nginx与最小隔离服务；同步apply/rollback/后验合同，保证之后主站更新仍保留ops。API/Worker保留单一production-pilot.yml身份，不临时追加override。首次迁移前的生产release没有ops/apex，不能当切DNS后合法回滚基线；切换前必须取得已验证的入口保留合同，或在失败时明确同时回滚DNS至仍可恢复的旧机。不删除旧API能力，不触碰原三用户dirty。
4. 本地专项→干净候选完整门禁/精确CI→核包→官方dry-run→本批正式切换确认。不得复用456e245门禁或运行旧ops_switch代替此过程。
5. 候选准备完成后才进入最终停写窗口；先取得新机维护任务的等效覆盖证据，再停用旧机调度入口并排空运行/排队任务，绑定最后源截止点、补最终一致归档。特别注意旧`jiejing-cls-probe-auto-refresh.yml`在远端默认main分支仍声明每12小时调度，其脚本会`--force-recreate`旧API和Worker；若仅手动停容器而保留runner/调度，最终封存可能被后台任务破坏。停用具体工作流/runner后须读回状态，不以本地改YAML代表线上已停。失败恢复旧服务则封存验收失效，须重新补全。
6. 一次切换；核对主站/ops精确资产、管理员/匿名隔离、回调地址、readiness各状态，原商品记录只读保留。失败只回滚本次路由/版本，不用旧库覆盖共享业务数据库。

验证引用：`tools/test_jiejing_production_pilot_contract.py`、`tools/test_jiejing_production_deploy_channel.py`、`tools/test_jiejing_operations_console.py`、`tools/test_jiejing_refund_operator_authorization.py`及`tools/codex_jiejing_merchant_ops_surface_isolation_smoke.js`，完整门禁按当时源码读取。独立ops资产验证不能被主站HTTP200代替。

## 第三阶段：旧机退役

1. 先确认独立任务/cron/runner已替代或停用、队列任务安全退出、最终归档与源截止一致，原恢复材料保留。
2. 针对准确旧实例获停机动作确认，可回滚停止旧机；新机独立覆盖至少一个关键维护周期（现知12h，加抖动/执行预算）。停机前证据不能证明已脱离旧机。
3. 用产品已有等待/自动化机制持续观察；若已有相同自动化则更新而非重复创建。仅完成/异常/需操作时通知，不承诺工具外后台运行。
4. 独立运行通过后核对旧机准确账期和自动续费，按用户确认关闭旧机自动续费。失败先恢复旧机；临近到期仍未完成才展示实际短期续费选项，不擅自付款。
5. 实例释放或删除数据单独确认；“不续费”不等于立即销毁。释放前还必须验证一个不依赖旧机、仍保留ops/apex的合法回滚基线，过渡期回DNS旧机不能作为永久回滚方案。完成后给出数据副本、恢复证明、域名/服务/定时任务脱离旧机证据。

## 最终核验

检查实施与以上已阅读源合同一致，禁止反模式，跑变更对应测试；完整业务发布、真实退款和eBay写入仍未因迁移而验收。最终只报告有证据的阶段，不报主观百分比。
