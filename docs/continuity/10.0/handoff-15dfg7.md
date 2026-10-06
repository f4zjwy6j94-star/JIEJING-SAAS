# 捷境接收拼嘚回传：共享资源映射与冲突对齐

日期：2026-10-06，Asia/Shanghai。
性质：内部交接补充；本轮只做本地资料核对与文档对齐，不是部署、修复、网络开放、资金操作或跨聊天发消息的授权。
本文件不是新的动态项目状态；捷境当前执行索引仍为：
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo\docs\JIEJING_CURRENT_EXECUTION_STATE.md

## 1. 来源、证据范围与原文保全

用户在“10.0”手动转交了拼嘚23节完整回传。必须保留其全部项目范围、进度、已做/未做、资源归属、保护清单与证据限定；不要只根据本摘要替代原文。

完整回传：
D:\Codex-Verification\pindd-cross-project-handoff-20261006\PINDD_RETURN_HANDOFF_20261006.txt
SHA256：0580ed1a31eb09961da99dc785bbff0bcd317997179f80dd855c97db0e4db377

拼嘚提供、捷境本轮已全文读取的安全摘要：
D:\Codex-Verification\pindd-cross-project-handoff-20261006\readonly-inventory.safe.json
SHA256：8b245cba1a6b3111314c686f0981b4744d046af8ceb6e3f64e9acdcd5d7fad13
嵌入serverUtc为2026-10-05T19:09:17.864143+00:00，即北京时间10-06约03:09:18。

D:\Codex-Verification\pindd-cross-project-handoff-20261006\console-and-dns.safe.json
SHA256：91376e5a86ad7a8f78d51c6e92ac1926697c0b98d004448992e2a06268f348e4
记录控制台、DNS及证书观察，checkedAt为2026-10-05T19:08:43.151Z。

上述内容是“对方在该时点采集，本轮读取并对照”的证据，不冒充本轮从服务器重新执行命令或独立复验。文件修改时间、文档撰写时间不替代嵌入采集时间。
本轮没有读取拼嘚源码/秘密/业务数据，没有登录云控制台、SSH、数据库或浏览器，没有重跑测试、健康探针、DNS查询。
完整回传中的历史TLS/恢复/微信审核通过等仍为历史证据，本轮未复跑。

之前的捷境交接与推广交接：
D:\Codex-Verification\handoff-cb5V76.md
D:\Codex-Verification\handoff-TWN9bz.md
它们的原时点证据仍保留；其中“待拼嘚回传”的数据库/域名/入口问题，按本补充更新。不要因已澄清事项再次询问用户。

## 2. 已对齐的归属与当前拓扑

| 对象 | 捷境 | 拼嘚 | 对齐结论与范围 |
| --- | --- | --- | --- |
| 主机 | Lighthouse lhins-gcoi2yb3 / 43.129.169.223 | 同一台主机 | 共享CPU、内存、根盘、内核、网络和宿主故障域，不是两个独立服务器 |
| 主机规格 | 2核/4GB/70GB/30Mbps | 共享上述规格 | 拼嘚4GiB镜像已占根盘，不是额外云盘 |
| 数据库 | 香港托管PG postgres-p2r6dxhh | 自管专用PG，127.0.0.1:55432，pindd_private_staging | 拼嘚当前私人API没有配置捷境托管PG；不能继续笼统写“共用同一个数据库” |
| 数据身份 | 捷境自己的后端凭据/租户体系 | runtime=pindd_runtime_staging，migration=pindd_migrate_staging | 不共享账号；schema pindd_private、管理角色及恢复库权限由对方源码/历史验收支持，非本轮登录数据库查询 |
| API | 现有Docker Compose project=deploy | systemd pindd-staging.service，127.0.0.1:8443 | 编排分离；拼嘚不用捷境Compose部署器 |
| 拼嘚版本 | 不适用 | /opt/pindd/releases/private-118/backend.cjs，runtime schema4 | 有效drop-in为release-118.conf；schema5只是候选，不能自动应用 |
| 业务域名 | 根域、app、ops、pilot | pindd-api.jiejing.shop | 归属清楚，但拼嘚域名此时尚无A/AAAA/CNAME业务解析 |
| TLS/入口 | 捷境Caddy占80/443，独立证书卷 | Node直接TLS，origin配置https://pindd-api.jiejing.shop:8443 | 该origin是内部身份配置，不是已开放公网服务 |
| Caddy依赖 | 捷境持久配置与受控部署 | 拼嘚未交付Caddy反代、隧道或动态路由 | 没有已登记的拼嘚Caddy依赖；未做全机运行时配置排查，不能扩大为绝对不存在第三方改动 |
| DNS | Cloudflare四条已代理A指向源站 | _dnsauth.pindd-api TXT仅用于证书验证 | TXT不等于业务代理；不改现有四条记录 |
| 网络/数据卷 | deploy内部网络、业务/Vault/证书卷 | 无Docker网络或卷，独立systemd用户和ext4镜像 | 双方不可加入对方内部网络或清理对方卷/目录 |
| 其他 | 捷境COS、CLS、Vault、队列、支付与eBay回调 | 拼嘚已交付架构不使用这些资源 | 不共享Cookie、签名密钥、支付商户能力和业务表；全面跨项目ACL仍未验收 |

拼嘚当前实际链路，依据对方配置摘要和部署记录：
主机内授权测试进程 → loopback 127.0.0.1:8443（Host/证书身份pindd-api.jiejing.shop）
→ Node私人API → TLS到127.0.0.1:55432专用PG。
删除记录另写拼嘚自己的SQLite文件。
微信登录DISABLED；没有交付公网入口、正式微信身份或真实公众云保存链路。

之前捷境约02:03的盘点早于拼嘚02:27:51启用private-118及02:30的TLS验证，是时间差，不是需要回滚版本或重做部署的冲突。
pindd-private-118、微信0.1.77、拼嘚Git HEAD c38eb13547ed968c7cf79f224e13bce22bd85002 与捷境源commit1e94f2b必须分开，不串包。

## 3. 新识别的风险与不能夸大的结论

### 高优先级：真实文件访问边界尚未验收

安全摘要显示拼嘚API与PG的InaccessiblePaths含-/opt/jiejing、-/srv/jiejing，没有显式列入捷境实际目录/opt/jiejing-production。
这是路径覆盖缺口，不直接证明可读取秘密，更不证明已有泄露。ProtectSystem=strict的写限制也不能当读隔离完成证据。
后续只能先读取目录属主/组/模式、有效unit属性、挂载命名空间和访问判定元数据；不得为了“证明能读”去读取.env、私钥、Vault文件或客户内容。
核实后如确需调整拼嘚unit或权限，由明确归属的项目提出最小补丁、重启影响、回滚和双项目后验，经具体授权再实施。本轮不修改。

### 高优先级：共享主机安全“风险”提示未知

console-and-dns.safe.json记录“风险; details not inspected”。
尚不知事件类型、对象、严重程度、时间或处置状态，不能认定入侵、归罪某项目或宣称已解决。
后续只读查看非秘密告警元数据，确认归属后再决定响应；本轮未打开控制台事件。

### 其他必须保留的限制

- 独立配置与用户/库存在，不等于所有运维账号及两边文件/数据库ACL互斥已认证。
- 拼嘚API仅允许回环不等于隔离所有宿主服务；拼嘚PG的systemd IPAddressDeny为空，监听/HBA与进程网络限制是不同控制。
- 拼嘚API/PG的Restart=no、unit为static，整机重启后的恢复和故障自愈未验收；不只凭static断言一定不会被依赖拉起。
- 拼嘚没有已验收的周期异地备份、PITR、生产RPO/RTO、备份告警或自动续证；单次合成数据恢复不代替连续运维。
- 两项目维护锁不互通；现有捷境deploy/maintenance锁不能阻止另一项目在同一宿主并发维护。
- 双项目联合CPU/IO/连接峰值和真实并发容量未验收；不要凭一次空闲快照确认可大规模投流。
- 这些结论不是本轮修复结果，不能标为“已关闭”。

## 4. 容量、账期、证书与保护对象

拼嘚对方03:09有效限制：
API CPU0.5核/MemoryMax384MiB/Tasks64；
PG CPU0.4核/MemoryMax448MiB/Tasks32；
日志CPU0.1核/MemoryMax64MiB/Tasks16；
父组CPU0.75核/MemoryHigh768MiB/MemoryMax896MiB/Tasks128，组内禁swap。
不能将子限额相加当可同时使用量，也不能将896MiB当已永久保留给它、其余主机容量已验收。

对方瞬时数据：
整个拼嘚组约73.1MiB，cgroup累计峰值约200.1MiB；
宿主MemAvailable约2.12GiB，根盘可用约23.11GiB，拼嘚镜像内约3.77GiB。
这不是压力测试或当前实时值。
PG max_connections=12，应用进程池max4、迁移池max1；不能混为捷境进程池max8或整机总连接数。

账期：
- 主机到期2026-10-22 11:21:49；对方观察自动续费已勾选，没有实际付款回执。
- 捷境托管PG此前最后已知旧到期2026-10-03 10:38:13。本轮仍没有新的控制台账期/订单证据；不能根据上轮健康GET宣称续费完成，也不能仅凭旧日期说已停服。
- 拼嘚PG无独立托管PG续费订单，但随宿主和磁盘受影响。
- 拼嘚API域名证书bLKNYIt2到期2027-01-03 23:59:59；不与主机续费、PG自身TLS或捷境Caddy ACME混为一谈。

绝对保护，具体路径与用途按完整23节回传：
/opt/pindd、/etc/pindd、/var/lib/pindd；
/var/lib/pindd-storage/staging.ext4；
API/PG数据、identity.key、deletion.sqlite；
专用证书与runtime-before-certificate-bLKNYIt2.json；
恢复105库、107主机外恢复材料、未批准退役release。
同样保护捷境/opt/jiejing-production、仍在引用的8月private/Vault目录、云备份、Docker命名/匿名卷。
不做全局Docker清理、通配符清理、重建库/seed、整体还原共享主机。

拼嘚源码及未提交改动：
C:\Users\57249\Documents\Codex\2026-09-29\dd-agents-md-00-start-here\outputs\pindd
D assets/brand/pindd-avatar-butterfly.png
?? docs/execution/iteration-17/native/fixtures/pin.png
本轮没有进入该仓库核改或恢复这些文件；原样保护。
大产物优先D/E/F，不搬整个项目或恢复资料。

## 5. 下一次共享操作前的待办与关闭标准

以下是待核对清单，不是本轮已执行的方案或新常驻任务。A/B/C/D在任何相关共享变更前处理，A/F/H应优先于扩大获客与容量承诺核查；具体风险若证实影响线上，再决定限制措施，不能未经核实关停。

| 编号 | 下一步最小核查 | 可关闭的证据 | 当前状态 |
| --- | --- | --- | --- |
| A 文件边界 | 对实际/opt/jiejing-production及仍引用的private/Vault路径做权限/命名空间元数据核对 | 明确两边服务身份的访问边界；有改动时附最小差异和双边后验 | 未验收，优先 |
| B 公网入口 | 明确pindd-api是否用443/Caddy/Cloudflare，核对微信端口及现有源站限制 | 用户批准的完整链路、持久配置归属、兼容Host/转发头策略和回滚 | 归属已对齐，未来方案未决；不自动开8443 |
| C 部署协调 | 明确双方维护责任人与窗口/锁协议 | 两边都使用或遵守的互斥流程证据 | 未实施联合互斥 |
| D DB权限/恢复 | 仅收集双方各自非秘密host/database/schema/role及有效ACL摘要 | 独立身份、拒绝跨项目访问和恢复范围证据 | 拼嘚单库目标已澄清，全面ACL未验 |
| E 拼嘚运维 | 由拼嘚任务处理自启、备份、删除重放、恢复告警、续证 | 对应生产范围演练和负责人 | 不是捷境本轮开发任务 |
| F 主机安全告警 | 只读看事件ID/类别/严重性/时间/处置状态 | 有归属与处置依据，不能只看“风险”字样 | 详情未看，优先 |
| G 联合容量 | 分项目连接预算、运行/部署峰值与告警 | 联合负载和告警证据 | 仅有快照与限额 |
| H 账期 | 捷境PG和共享主机新账期/订单安全回执 | 新到期日/实际续费状态；不含支付秘密 | 主机到期与自动续费有对方证据，PG新账期缺失 |
| I 保留与退役 | 列出依赖、数据/备份保留和每个退役目标 | 明确目标、可恢复性及具体删除授权 | 当前全部保护，不清理 |
| J 索引/浏览器/版本 | 更新捷境索引和交接入口 | 新旧来源、时间、版本分开 | 本轮文档对齐；不是远端变更 |

浏览器ID和标签号仅为各次会话观察，不能据Chrome3/4或tab22判断同一个页面。操作前按Profile、网址、标题、会话和归属重新识别，不刷新/关闭对方工作页。
拼嘚Codex自动化“拼嘚持续开发与上线准备”据对方记录PAUSED；不重启。不要动捷境production-evidence-refresh.timer。

## 6. 软件进度、宣传与11.0的影响

捷境8/8的软件首版交付、274/274历史门禁及此前线上证据继续按原范围保留；本轮没有重测、改分或取得新的线上就绪回执。
拼嘚47/100是它约定的完整商业范围；微信0.1.77代码审核、云端private-118和本地商业开发不能相互替代，捷境也不将自己100%套给拼嘚。

新增共享风险不等于推倒重做捷境，也不能为了维护“100%”口径隐瞒。
正确表述：捷境已约定的软件首版交付完成；共享宿主的完整跨项目访问隔离、告警详情、联合容量和最新账期仍有明确待核查项。
宣传不能据原8/8宣称跨项目安全百分百或商业收益已达成。

11.0继续脚本、分镜、风格样片及合规内容制作，不接管拼嘚、不修改SaaS架构或云资源。大规模投流/流量承诺前应由产品/运维侧核查高优先级安全、账期和承接风险；不把这项核查变成无限重测商品。
原11.0启动文本指向的handoff-TWN9bz.md已加入本回传路由；即便用户仍复制原文本，新对话完整读取原文件也应得到更新。
如果11.0已经在更早时刻读过资料，应让其重新读取当前索引顶部与本补充；本轮没有自动向任何其他聊天发消息。

## 7. 本轮范围、保留状态与验证要求

捷境实际仓库：
C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo
本轮读取的分支codex/ai-ceo-real-merchant-loop，HEAD1e94f2b798b158c8d34f224185151fcb95aaf912。

只创建本文件并增补：
- 当前执行索引；
- handoff-cb5V76.md的最新补充入口；
- handoff-TWN9bz.md的最新补充入口与共享资源说明。
拼嘚原始TXT、安全JSON及两项目业务文件不修改，原有dirty状态不回退。
没有commit/push、云端检查或配置修改、部署/重启、数据库操作、购买/续费、广告、eBay/付款/退款或跨聊天消息。

交付前验证本文件/引用路径、两个JSON解析、原证据SHA未变、只修改声明的文档、Git diff whitespace检查和HEAD保持。
这只是文档验证，不替代线上健康或安全验收。

## 8. 下次接手技能与授权

文档续接：handoff及verification-before-completion，先读实际AGENTS/当前索引。
真实问题只读诊断：采用diagnose，并按相关安全/运维范围读取所需技能；不得把技能当修改共享资源授权。
需要UI核对控制台时先读computer-use技能与当前工具文档，只访问明确归属页；不要使用旧标签号猜目标。
若核查证实需要代码或systemd/DNS/Caddy/数据库变更，另列最小方案、双项目影响、回滚和验收，取得该动作所需批准后实施。
本轮无需新建自动化、子代理、新聊天或对方源码任务。
