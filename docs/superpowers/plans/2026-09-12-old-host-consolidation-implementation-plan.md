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
   C组一致性判定按9月15日设计澄清：先对确切条目绑定来源/归属证据；业务及未知项继续原完整稳定final合同。仅确认的OS运行日志研究原生日志导出或已支持的快照路线，保留完整历史并记录活动数据的明确捕获截止；成熟工具产出的稳定文件仍进入既有tar/GPG/副本及恢复验证。路线确定和测试主审前不capture、不把当前条目标为已保全；不按`/var/cache`或`/tmp`名称排除，不停sshd/journald、不ignore tar警告、不删源或新增付费服务。截止后的运行日志仍在旧机，不能凭这个判定澄清直接退役。
3. 创建专用D盘受限恢复目录和新机私有归档目录，验证空间/ACL/无链接/排他写入。ACL不能只检查已有ACE，还需核对Owner、根继承保护、当前用户/SYSTEM/Administrators必需权限及路径链无重解析点。先确认成熟加密收件人材料及恢复路径，进行小型非业务样本的加密→传输→隔离还原；只返回结果，不回显密钥。工具自动生成保护口令，不要求用户自设；受保护私钥导出包/keyring与本机DPAPI密文保留，失败不自动覆盖重生成。先在新隔离keyring导入、关闭仅该keyring的agent缓存后，验证错误口令拒绝及DPAPI恢复口令解密成功；此样本只证明当前Windows身份的本机恢复，不证明跨机或Windows身份丢失后的灾备。独立恢复材料交接/托管未验证前，不完成第一阶段、不释放旧机。
4. 静态预归档；可变数据在旧写入者安全暂停并具备旧Vault恢复条件后作一致性备份。首轮恢复旧写入后标记增量待补。新机保留至少10GiB空闲，D盘另有独立密文副本。
5. 用固定清单与分段hash记录传输；中断不覆盖已验证段、不删除源。Linux恢复验证权限/ACL/xattr/链接/稀疏，不在Windows解包冒充完整恢复。

验证：本地fixture覆盖无工具/错误host/输出拒绝/超时/文件冲突/空间不足；执行前固定工具hash并独立审查；受控真实回执；零服务变更探针与备份阶段分别标记。最终业务归档与keyring均不进Git。

禁止：整盘覆盖生产、docker down -v、卷删除、rsync --delete、打印原日志/密钥、未核验即解包或执行旧程序。阶段验收缺失则保留旧机运行。

## 第二阶段：切换验证

2026-09-16 顺序澄清（独立审查后采用）：OLD vendor历史归档不是R3运行输入，可先在NEW正式apply并验证R3，暂不调整DNS，不再把全部最终保全机械地作为此次NEW apply前置。第一阶段最终保全并未豁免；双副本/隔离还原、最后源截止及停旧后12h观察仍是退役、删源和不续费的必要门槛。B当前YDService强制退出需要用户针对具体动作确认，尚未收到；其余四个逐进程TERM未发，不为先部署而补发信号。

实际状态简记：两次独立受审official apply未通过，首次3c6ef2保留；a772入口attempt2回执1a39bd明确失败于ops TLS/资产/匿名隔离验收，1f5ad4真实读回主站active456、四业务标签/running正确、locks free、deep ready，DNS未改。隔离v2只create/connect未start、tests为空，停止该辅助路线，不称17项通过或产品故障；下一步窄读实际Nginx检查请求日志。AH/final未开始，不VM停机/删源/取消续费；详细证据只在当前执行索引维护，本计划不作为完成证明。

1. Cloudflare正确账户与4条A记录基线见任务`output/host-retirement-audit-20260912/cloudflare-domain-readonly.json`。2026-09-23实际完成根域/ops迁NEW，app/pilot不动；不新增www/AAAA/CNAME，根域边缘HTTPS 301跳app规则保留。原“ops保持DNS-only”方案已由本日用户具体批准及实际结果取代：NEW既有`inet jiejing_origin_lock`只允许Cloudflare访问80/443，故ops改proxied/Auto，不放开源站。公网可信TLS200、五静态文件及HTML仅已识别CF脚本差异、匿名管理401/no-store、主站后台路由404均已验；详见`dns-ops-cutover-20260923.json`。不运行旧UFW脚本、不关闭保护，不将DNS完成等同全机迁移完成。旧A/DNS-only基线保留为历史，恢复OLD业务需另行核验，不能承诺仅改回DNS即服务恢复。
2. 核对生产ops资格、DB身份、Vault引用、退款能力配置及旧Worker/runner/cron职责，只读且不调provider。未知即不切换。
3. 在现有生产部署路径版本化加入apex/ops Caddy、专用ops Nginx与最小隔离服务；同步apply/rollback/后验合同，保证之后主站更新仍保留ops。API/Worker保留单一production-pilot.yml身份，不临时追加override。首次迁移前的生产release没有ops/apex，不能当切DNS后合法回滚基线；切换前必须取得已验证的入口保留合同，或在失败时明确同时回滚DNS至仍可恢复的旧机。不删除旧API能力，不触碰原三用户dirty。
4. 本地专项→干净候选完整门禁/精确CI→核包→官方dry-run→本批正式切换确认。不得复用456e245门禁或运行旧ops_switch代替此过程。已完成R3同源门禁/CI/dry-run不重复；本次按e4392f新鲜容量及绑定核验，仅授权独立R3 apply：NEW空闲33.212GiB，规划4GiB用于本次candidate/build/rollback并保留至少10GiB；4GiB是规划值，不是实证或强制资源上限。全部剩余迁移峰值尚未证明，不再作为这次独立apply的已满足前置，也不宣称全迁移容量GO；后续各归档/恢复阶段分别刷新容量。当前release、private引用、证书、artifact、source与CI绑定须完整不漂移，部署不与归档/恢复并发；本阶段容量或绑定不明则不apply，不靠清删旧证据换空间。
   此次apply失败只按官方路径恢复NEW原release；ops保持当前维护态，不宣称ops无缝回滚。首次旧release没有ops能力，不能把主站release回滚当作ops恢复；原OLD必要时业务回退需独立按既有runbook处理，不自动恢复旧writer或伪造最终封存有效。
5. 候选准备完成后才进入最终停写窗口；先取得新机维护任务的等效覆盖证据，再停用旧机调度入口并排空运行/排队任务，绑定最后源截止点、补最终一致归档。特别注意旧`jiejing-cls-probe-auto-refresh.yml`在远端默认main分支仍声明每12小时调度，其脚本会`--force-recreate`旧API和Worker；若仅手动停容器而保留runner/调度，最终封存可能被后台任务破坏。停用具体工作流/runner后须读回状态，不以本地改YAML代表线上已停。失败恢复旧服务则封存验收失效，须重新补全。
6. NEW apply与DNS分开验收和决策：先在DNS仍保留原值时确认浏览器可信TLS、六项精确ops资产、管理员/匿名隔离及主站健康/readiness，再单独决定仅apex/ops的源站指向调整，app/pilot不动。原商品记录只读保留；失败只回滚本次路由/版本，不用旧库覆盖共享业务数据库。DNS调整成功也不替代最终保全、双副本还原或第三阶段独立运行观察，不据此删除/退役旧机或取消续费。

验证引用：`tools/test_jiejing_production_pilot_contract.py`、`tools/test_jiejing_production_deploy_channel.py`、`tools/test_jiejing_operations_console.py`、`tools/test_jiejing_refund_operator_authorization.py`及`tools/codex_jiejing_merchant_ops_surface_isolation_smoke.js`，完整门禁按当时源码读取。独立ops资产验证不能被主站HTTP200代替。

### 2026-09-15 最终停写窗口细化（本地方案，尚未实施）

不再增加runner角色探针：已知loaded unit、Invocation/MainPID、稳定cgroup及shell→包装进程→Listener链足以限定服务目标；一个包装进程的工具分类unknown不等于新增未知业务职责。原unit文件可写安全债与`unit_file_trusted_for_execution=false`保留，不执行其当前文件内容或以本段授权停机。

1. **先完成开发，再进窗口。** 复用任务证据目录中`old_pause_preconditions_readonly.py`的`container_state`、`runner_roles_readonly.py`的unit/PID/cgroup检查及`worker_running_count_candidate.py`的只读COUNT。窗口前固定五个OLD容器完整ID、PID/starttime/image及原restart策略；动作紧邻刷新GitHub五种未完成状态、cgroup与Worker/job，并要求共享running COUNT=0。它是保守前置，不是OLD归属计数或无竞态锁；新任务/新代际则退出本次动作，不清job/lease。
2. **核loaded停止动作，不加载可写unit。** 用既有GetUnit及原生typed数组方式读固定Service的`ExecStopPost`；正确空数组才继续，非空只报count并暂停解释，不输出命令。复核loaded Invocation、Restart=no及无触发入口。旧`ExecStop`空数组证据不代替该项。已禁用的具体GitHub workflow须在窗口前重核；核准fixed loaded Names、精确enable链接和无`Also/Alias`外扩后，采用dirfd持有父目录、原链接身份/目标复核，再仅unlink这些链接并fsync，保存原目标/身份用于精确回滚。此候选不调用可扩展unit当前内容的systemctl disable，不reload；未闭合则不执行宽泛disable/mask/revert。
3. **Runner只给已识别Listener一次SIGINT。** `os.pidfd_open(pid, 0)`后再次绑定原PID代际/cgroup并检查无新job，再由`signal.pidfd_send_signal(fd, SIGINT, None, 0)`发一次，等unit及完整cgroup自然退出并确认不重启。pidfd不可用、超时、新job或重启均notfinal；不得降级普通PID猜测、向未知wrapper发送TERM或升级KILL。官方[RunnerService.js](https://raw.githubusercontent.com/actions/runner/main/src/Misc/layoutbin/RunnerService.js)含收到停止信号后的30秒KILL定时器，因此不信号该wrapper。也不采用`set-property --runtime SendSIGKILL=no`：systemd v255的[kill属性setter调用](https://raw.githubusercontent.com/systemd/systemd/v255/src/core/dbus-service.c)受transient/stub分支限制，不能假定可作用于这个已加载服务。
4. **业务容器只操作OLD固定ID。** NEW主站保持运行；先闭合旧入口不再产生本地写入，保存并设`docker update --restart=no <固定ID>`后复核。使用`docker stop --timeout=-1 <固定ID>`保留已核镜像的正常StopSignal，按固定角色允许清单验收；不假定nginx/Vault都为TERM，不覆盖信号、不使用Docker默认超时KILL。控制器有等待上限但超时不杀目标。顺序为旧tunnel、frontend、worker、API、Vault；Vault必须先满足已验retained-clone材料恢复前置，此前置不是完整cold备份。不compose down、不动NEW、不删容器/卷。具体动作仍须driver主审后授权，不把共享COUNT快照称为原子drain。
5. **停后从独立渠道取证。** OLD原PID代际全部退出、cgroup空、容器Running=false/restart=no、runner inactive且入口不重启；OLD API退出后不能再docker exec它查DB。复用`runtime_compatibility_preflight.py`的只读事务/短超时/rollback/close，在NEW同库渠道查共享running及已绑定OLD数据库client_addr的连接数。数据库实际看到的地址必须先核准，不能拿SSH路由IP代替；权限/代理归属未知不报0。`persistent_archive_batches.py:399 validate_quiescence`旧合同另要求lease=0及四类cron全停，现有COUNT不直接证明lease，且已分类系统维护不必全停：后续薄适配须按本批必要writer闭合真实字段，不能伪填0或把仍运行vendorcron写成stopped。
6. **最终封存与回退。** 绑定同一pause_id及所选源前后元信息，复用现有tar/GPG→D/NEW全hash→Linux隔离恢复。必要业务/封存writer保持停止；C仅逐项已核OS日志按原截止例外，不宣称全OS静止。若回退，仅恢复本次确实改变的restart策略/精确入口链接及已停原容器，runner重启须先处理可写unit执行信任问题；恢复旧业务写入即撤销对应final并补delta，不回滚共享DB或删除源。旧VM停机、续费和删机仍是后续独立动作。

以上命令语义依据[systemctl](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml)、[Python pidfd信号](https://docs.python.org/3.12/library/signal.html#signal.pidfd_send_signal)、[Docker stop](https://docs.docker.com/reference/cli/docker/container/stop/)及[restart策略](https://docs.docker.com/engine/containers/start-containers-automatically/)。固定[old_final_pause.py候选](C:/Users/57249/Documents/Codex/2026-08-24/jiejing-ebay-first-ai-ceo-saas/output/host-retirement-audit-20260912/old_final_pause.py)已有16个focused本地测试；preflight、runner、business三份排他回执前后SHA绑定，默认offline，尚无实际执行证据。单次preflight还仅读docker.service/docker.socket/containerd.service的loaded停止钩子计数、停止策略、PID/cgroup及配置可信姿态；socket按原生TimeoutUSec/ControlPID/ExecStopPre+Post投影，缺项独立partial，不伪空、不遮DB。五容器停止不等于daemon已停，须据现场结果审定后续正常graceful方案，所有当前阶段仍quiescence/retirement=false。

**B/D/E最少归档复用，不另造格式：** 下列工具均在任务`output/host-retirement-audit-20260912/`；是既有能力与缺口清单，不是已完成归档或可直接重复旧actual的许可。

| 范围 | 已有入口/原语 | 最少尚缺 |
| --- | --- | --- |
| B `/usr/local` | `usr_local_unit_archive.py`的collect/plan/selected前后、两控制文件和成熟首包tar/GPG；attempt2只增加错误定位。 | 新的唯一cold/final回执与真实pause绑定；原两次输出不覆盖。当前plan硬要求1 socket，停止相关writer后若socket消失须按精确运行时元信息合同处理，不能预先排掉持久项。`runtime-exclusions.json`及`selected-metadata.json`在parts外也要保全。还原可薄接`opt_unit1_restore_escrow.py`的escrow/full-auth/cleanup并组合G正洞修正及B精确范围，当前没有已验B恢复wrapper。 |
| D 22个Docker volumes | `persistent_archive_batches.py`固定catalog；`bg_subarchive_prepare.py`的generic collect_root与`persistent_subarchives.py`的≤4GiB/hardlink原子组可复用，B/G CLI本身不接受D。 | 固定D scope的薄create/restore；原计量有1 block节点，需仅节点元信息、nodev隔离与精确恢复合同，绝不读取块设备内容，F char0证明不能代替。旧Vault file存储须cold一致。 |
| E Docker control | 同generic collector/planner与G/F成熟封包恢复生命周期；已证明5个overlay视图backing在保留的F范围。 | 与D共用小型固定scope表：保留Docker控制/日志/配置，仅扣已覆盖D卷及已证明的派生view，不丢writable层。五业务容器停止不等于Docker daemon元信息稳定，需在最终窗口锁定必要daemon writer处置或具体一致捕获；不能为变绿忽略tar警告。 |

旧`persistent_archive_batches.py`的B/D/E仍有未定预算及`execution_prepared=false`，其旧create是nonfinal，不能直接当最终引擎。上述缺口在停写前实现并测试；设备/硬链恢复未闭合的批次保持未完成，不先停业务等待开发。

## 第三阶段：旧机退役

1. 先确认独立任务/cron/runner已替代或停用、队列任务安全退出、最终归档与源截止一致，原恢复材料保留。
2. 针对准确旧实例获停机动作确认，可回滚停止旧机；新机独立覆盖至少一个关键维护周期。2026-09-23用户最新更正观察期为12小时：从保全验收通过且旧机实际停机的时间起算，覆盖维护执行结果并记录缺测；停机前的NEW在线预观察不能证明已脱离旧机，也不能计入退订倒计时。
3. 用产品已有等待/自动化机制持续观察；若已有相同自动化则更新而非重复创建。仅完成/异常/需操作时通知，不承诺工具外后台运行。
4. 独立运行通过后核对旧机准确账期和自动续费，按用户确认关闭旧机自动续费。失败先恢复旧机；临近到期仍未完成才展示实际短期续费选项，不擅自付款。
5. 实例释放或删除数据单独确认；“不续费”不等于立即销毁。释放前还必须验证一个不依赖旧机、仍保留ops/apex的合法回滚基线，过渡期回DNS旧机不能作为永久回滚方案。完成后给出数据副本、恢复证明、域名/服务/定时任务脱离旧机证据。

## 最终核验

检查实施与以上已阅读源合同一致，禁止反模式，跑变更对应测试；完整业务发布、真实退款和eBay写入仍未因迁移而验收。最终只报告有证据的阶段，不报主观百分比。
