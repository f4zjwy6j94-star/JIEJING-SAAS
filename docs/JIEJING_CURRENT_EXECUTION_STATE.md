# 捷境当前执行状态

最后更新：2026-09-06。用途：中断、重启或压缩后从此处续接；不是公开产品文案，也不是线上状态证明。维护本文件，不另建同名意义的平行“最新状态”。旧日期交接仅用于按需追溯。

## 目标与本轮范围

最低成本完成 eBay-first AI CEO SaaS MVP：商家在捷境内留下真实对话、调研、商品资料、Listing、素材及审核记录，满足事实、图片权利与账号条件后，通过捷境保存 eBay 草稿并经动作时确认发布。不得用 Codex/API 直接造业务记录冒充商家 UI 验收。

用户最新要求（2026-09-05）：由主理人自主、有序持续推进，不再要求用户逐项指导常规方案；使用已安装设计技能，改善商家便利性与UI，保留eBay-first产品方向。当前有限目标是形成可验收MVP候选：W4b服务端可靠聊天归档 → W5批量无货源入口/W6商家反馈 → C1/C2版本绑定发布证据 → 当前页面设计审查和有界改进 → 专项/完整候选验证与同一商品续接。可并行独立修复；不把“持续优化”变成无边界重构，不以模型称号或任意百分比保证成熟度、盈利或零漏洞。

正常实现与方案选择已授权；本批主站正式部署已获准并完成，资金与eBay高风险动作仍需动作时确认。2026-09-06用户随后明确“允许”，批准旧ops仅前端、代理及API的SSH窄范围例外；不含主站、Worker、Vault、Cloudflared、DNS、私有配置及共享数据库变更，不重跑真实商品流程/OAuth/支付。W1–W6补丁已提交并部署；三项原有用户修改完整保留且未混入发布。

## 精确续接点

- 实际仓库：`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`。
- 分支：`codex/ai-ceo-real-merchant-loop`；当前产品发布提交：`1550105b53825a65f876808bff059a4e6d0c0a8a`（`test: align merchant onboarding and CI gate coverage`），包含`f2ce760`的W1–W6/C1/C2/UI及`0250ce6`测试/CI预算修订，均已提交并部署主站。原修复基线为`66032b3`；恢复时再次核对Git，后续纯证据文档提交不等于再次部署。
- 商家生产主机已部署 `1550105`，release=`20260905T184522Z-1550105b5382`（此前`4c26ebc`为可回滚上一版本）；完整门禁224/224、精确SHA GitHub CI、dry-run、apply及线上健康/资源/公开页面复核通过。独立ops在2026-09-06获准窄范围SSH同步后也已更新到1550105，见下方新收口；不能称整套退款运营链路已完成，旧ops的微信live/refund配置仍false且真实运营身份未验收。主工作区仍保留三项原有用户修改，不得重置、清理或覆盖。
- 三个原有用户修改文件不要顺手暂存/提交：`jiejing_saas/readiness.py`、`tools/test_jiejing_phase2_response_boundary_hardening.py`、`tools/test_jiejing_platform_trial_activation_guard.py`。
- 当前商品：平板电脑支架（折叠便携款）；项目 `listing-project-0ef70f19c079b4261e82`；报告 `report_19fcfc7b9f88f0eb`；候选 `candidate_1`。
- 调研、导入、商品资料模块和一次有缺陷的 Listing 生成已做。续接同项目，修复上线后再生成一次验证，不从选品重新开始。
- 本轮尚无该商品真实 FAL/eBay 操作完成证明；AI 生成资料不能冒充真实货源事实，不能因用户要求跑流程而编造可公开销售的参数。

## 商家生产主机已部署的修复

本地专项、完整候选门禁、商家主机生产部署和独立ops代码同步已通过；已登录生产商家的UI复验、真实运营身份与退款执行配置对齐未完成。

- Listing 买家文案/商品事实约束、敏感信息输入阻断、失败用量保留；eBay 写入前事实/兼容性边界。
- 商品图片识别只产生待确认建议；清空字段不被旧建议复活；生成失败仍保留来源与冲突元数据。
- 商品资料保存单飞与忙碌状态；按公司、店铺、项目、归一化内容在同事务内幂等保存任务/报告，修改内容才创建新版本。
- 额度激活不重置试用窗口；预留、消费、释放有状态记录；并发复用已释放名额增加数据库串行保护；实际模型调用后审计失败不再误释放额度。
- 部署白名单/语法检查已纳入新依赖及回归；JavaScript 不再误送 Python 编译。

已通过的关键专项：商品资料 UI 18/18、发布预填 11/11、5 并发 HTTP 同版本保存、修改新版本及租户/店铺/项目隔离、Listing 生成/事实/视觉/敏感文本、quota/window/lifecycle/HTTP concurrency、schema 15/15、SQLite→PostgreSQL rehearsal、secret scan、Python/Node 语法与 diff 检查。最终完整门禁211/211通过，但这不证明独立ops同步或真实商家全流程验收通过。

## 本轮权限审计：两端代码已部署，运营身份验收待完成

2026-09-05 代表性代码审计，本地假用户/假订单/假 provider 复现，真实退款调用为零：

1. P1：普通商家可申请、自批并执行自己的 SaaS 订阅退款。`api_server.py` 的 refund confirmation/execute 与 `billing_domestic.py` 共用商家 owner 权限，未要求平台内部审核者。应保留申请能力，将平台自身退款审批与执行限定内部运营权限，并校验审核依据；不能以关闭收费或退款开关代替修复。
2. P2：viewer 可取消任务、运行 worker、拒绝/修改确认单，部分变更入口缺岗位权限校验。
3. P2：团队邀请未执行套餐席位上限，需事务内统计占用/待接受席位及并发最后席位保护。

独立复核又确认并修复了关联问题：退款查询恢复遗漏内部审核者名单、退款在途仍可撤销审批/并发重复请求 provider；新席位检查沿用的有效订阅判定漏认 `wechat_pay_native`，且未检查已过期的 `active_until`。前者有本地假 provider 复现；后者使用临时库复现。退款改为数据库发送前原子认领，不确定结果保留处理中并只查询；微信稳定退款请求号存在 provider 幂等保护，本地重复请求不等于已发生双倍真实退款。

收口专项：退款权限 13/13、席位与实际微信订阅 17/17；退款/素材点/provider/maintenance/merchant refund browser/ops console 既有回归通过。ops 浏览器桌面、平板、手机覆盖审核理由、精确金额确认、查询恢复。独立复验 paid→processing→refunded 权益分别保留/保留/撤销。所有资金 provider 均本地假实现，未真实退款；PostgreSQL 并发未实测。

适配了旧 `billing_test_provider` 对商家暴露 `merchant_launch_path` 的过时要求，改为当前正向允许字段与内部信息隔离断言，保留所有禁止真实收费和私测约束；4 类故意破坏投影均被测试拒绝。生产商家投影未因测试而修改。

完整审计范围、发现与验证限度见 `JIEJING_SECURITY_RELIABILITY_AUDIT_20260905.md`。首轮干净候选位于 `C:\Users\57249\Documents\Codex\2026-09-05\jiejing-release-security`，HEAD=`ca5a20d`，完整门禁结果 205/211（见该目录 `output/jiejing-precloud-deployment-gate/latest.json`），不是通过。

首轮六个失败项：merchant_copy_maturity、ai_ceo_routing_supplier_http、listing_media_writeback_persistence、domestic_billing_api、domestic_billing_merchant_ui、agents_md_guardrails。前三项补丁已提交 `801dc88`；退款旧测试已改为验证商家禁止自批/执行、内部运营审核及精确确认。AGENTS 旧测试曾强制写死旧账号冻结/收费false，现验证当前证据与续接索引、禁止旧状态固定化。六项各自修复后的专项通过，真实退款权限套件与支付回调/查询/维护均通过。

第二个干净目录 `C:\Users\57249\Documents\Codex\2026-09-05\jiejing-release-security-r2` 的旧候选 `7a92620` 不得部署：主线程部署前复核发现退款审核时间比较不兼容生产 PostgreSQL 返回的原生 datetime（SQLite 返回字符串）。审计 JSON 的时间文字与原生 datetime 直接比较会让合法审核失败，claim 的时间/JSON持久化也必须一起修。该版完整门禁在第54项通过后主动停止，不能算完整验证。

上述 PostgreSQL 类型问题已在主仓库修复并冻结：审批和 claim 都严格解析明确时区，按 UTC 同时刻比较，拒绝空值、非法、无时区或篡改时间，持久化统一 ISO 字符串。先复现失败，再通过退款权限 18/18（含原生日期贯穿完整 ops HTTP 执行）；既有计费API、微信退款provider、素材点与退款专项通过。独立 quota/seat/fact checkpoint 原生类型回放 4/4，未发现同类确定失败；以上均非真实PG或资金操作。

最终干净候选 `4c26ebc` 在第二目录完成完整门禁：211/211、失败0、用时1153.37秒，`status=pass_local_checks`，`secret_exposed=false`。证据为该目录 `output/jiejing-precloud-deployment-gate/latest.json`。代码门禁的 `ready_for_paid_commercial_launch=false` 只是其“不证明真实收费上线”的固定边界，不能覆盖本轮线上收费能力为true的证据。

本次新包为第二目录 `output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-110052.zip`（同名 `.manifest.json`），SOURCE_COMMIT=`4c26ebc487dd40ff1bae45336723eb2910af30fb`，451文件，SHA256=`1ce9ba644d3902677c27e4acee2b10ba9e4d6fdcd457417487a628f88e19bee1`。生产dry-run及apply均成功，MANIFEST_SHA256=`103371a476df86a273988cae3a8105c7071444ed709beb7fbd6a39095204d7bf`，不需要私有env权限规范化。正式release=`20260905T113551Z-4c26ebc487dd`，active已切换，首次oneshot与timer安装验证成功。不要因旧记录仍在而再次apply。

该目录生成的 `output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-104500.zip` 是旧 `7a92620` 候选，SHA256=`fc5a256cc5bebda6b8f2d40b495391a3472b962b23f87f5c5816861d0f8c5299`；仅已打包，没有dry-run/apply，不得继续部署这个包。修复后提交新候选、重跑完整门禁并重新打包。更早的 `801dc88` 在第12项停止的门禁也无完整验证效力。

这是有限代码审计，不是全局零漏洞证明。没有新增首页夸大能力或跨租户泄漏的确认发现。相关入口：`tools/test_jiejing_domestic_billing_refund.py`、`tools/test_jiejing_domestic_billing_refund_browser.py`；成员/确认/队列路由见 `jiejing_saas/api_server.py`。

## 2026-09-05 部署后只读线上校准

- `/health` 200，`status=ok`；`/health/deep` 200，`operational_health.status=ready`，database/queue/worker 均 ready。
- `/readiness/product-saas` 的 `readiness`：`production_ready=true`、`beta_ready=true`、`can_accept_real_customers=true`、blocker/warning 均 0；`real_platform_writes_enabled=false`。
- 后端微信支付能力合同只读选取布尔：`charge_now_allowed=true`、`real_checkout_ready=true`、`public_commercial_release_approved=true`、`refund_now_allowed=true`、`internal_admin_allowlist_configured=true`。没有切换开关，没有执行真实收费/退款。注意独立ops尚未同步，退款provider能力为真不等于当前运营UI完整可用。
- `effective_ebay_draft_save_enabled=true`、`effective_ebay_controlled_publish_enabled=true`；`effective_real_platform_writes_enabled=false`是全面写入开关，不能误报为所有受控eBay写入通道关闭。具体账号资格及本商品真实发布仍未验收。
- `ops.jiejing.shop` 200；`app.jiejing.shop/ops.html` 404；证据刷新 timer active，service Result=success、ExecMainStatus=0。
- active link 为 `/opt/jiejing-production/app`，指向 `releases/20260905T113551Z-4c26ebc487dd/app`；manifest SOURCE_COMMIT=`4c26ebc487dd40ff1bae45336723eb2910af30fb`。API/Worker compose 标签、发布目录、private env 引用一致；private仍引用 `releases/20260822-170619/private`，没有输出秘密值。
- 当前发布 BUNDLE_SHA256=`1ce9ba644d3902677c27e4acee2b10ba9e4d6fdcd457417487a628f88e19bee1`；MANIFEST_SHA256=`103371a476df86a273988cae3a8105c7071444ed709beb7fbd6a39095204d7bf`。API image=`sha256:428c1a727063216bcde8ea3950a9043060131ffdf3024fbd42382efa5b586fac`；Worker image=`sha256:a2a83e3bcdf5c6522539a578401578a9925fd326a6b45e59afb5de27a23102d3`。
- 商家app.html已引用本次 `20260905-permission-fact-boundary-v1` 资产。上述绿色状态不覆盖独立运营端的旧版本问题，不可宣称全站各入口均已同步。
- 本轮 CUA 仅发现空的内置浏览器，指定 Chrome 返回 `Browser is not available: chrome`。这不是用户登出证明；没有重复 OAuth/登录/重装，没有完成登录后生产页面的视觉审查或商家操作。局部本地浏览器测试不等于线上用户旅程验收。

## 独立ops：代码已同步，退款执行配置待对齐

2026-09-06本节后续授权已更新：用户明确允许仅旧ops前端、代理和API的SSH部署，以下“未授权/未同步”均为历史记录。本次窄范围apply已成功，不得重复执行：API/五文件已1550105同版，原Compose、私有配置、Worker/Vault/Cloudflared未变。旧ops运行时微信live_api/refund开关仍false，内部审核名单存在；此授权不包含将其打开或复制主站私有配置，代码同版不等于退款运营端到端已可用。

### 2026-09-06窄范围发布收口（当前）

- 复用r3已通过224/224及精确SHA CI的457文件包；本轮未重新打产品包、改业务代码、重跑既有完整门禁或主站发布。旧host的独立目录为`/opt/jiejing-staging/releases/20260906-ops-1550105`，同包/manifest摘要已逐文件验证；仅构建API，未启动候选入口作探测。
- 现场只读PG事务核对16/16迁移ledger/checksum、45/45表、52/52关键列、4/4索引、5/5约束，缺项0；启动同版代码跳过既有迁移，不执行补schema/业务回填。原Compose有效环境与运行环境、候选镜像环境完全相同（API211项/前端6项），没有秘密值输出或私有env修改。
- 原旧ops脚本无API更新/固定镜像回滚且硬编码旧版本，不能复用；全量staging脚本会碰Worker/Vault，亦未使用。本次独立辅助脚本位于本地忽略目录`output/ops-narrow-20260906/ops_switch.py`，SHA=`03e9da5c1f2892ee3e319116bf54b0a6d2bf71dc700fa6a0b8fa170cd74d282c`；14/14故障测试及独立重放通过。已修复部署后配置数组顺序变化会连带阻断回滚的问题；支持部分复制/健康失败/API创建失败恢复、环境漂移与重复执行拒绝。不是掉电级事务原子性或真实资金测试。
- schema只读辅助脚本SHA=`1325c14eb4b6f62d874e3e5fafe6c1977903f1f575f6120b1509e032ef850f02`，候选关键合同精确AST提取，17个隔离回放通过。第一次dry-run因10分钟schema证据过期而在切换前拒绝；刷新实际只读查询后dry-run通过，没有放宽时效校验。
- 正式apply会话76472已exit0，status=success。API容器`6406b470a2672057a6caf3f3bcd4beb17a1ec27b14031ff9d1075c11c8afe783`，image=`sha256:f9e867784ae0500006d3523a0b4a07d7fd63ad93b90fc12ee4fc22ad0e4912dd`；前端容器`465ac42d0923a9c1dbc18bd088478938e734160806a01e361a99fcb4da21cad7`，沿用原nginx image=`sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10`。
- 两服务Compose文件顺序是原`/opt/jiejing-staging/app/deploy/docker-compose.public-https-staging.yml`加`/opt/jiejing-staging/releases/20260906-ops-1550105/.ops-switch/apply.json`；项目仍deploy。只对这两服务使用`--no-deps --no-build --force-recreate`。以后不能忽略override而误回旧镜像；任何新部署均先按实际标签校准。
- 发布后读回：5文件逐字节等于manifest，API150个源码/依赖文件等于同包，深健康database ready；配置、端口/挂载/网络及3个非目标容器ID/镜像/运行状态不变。ops匿名列表401，3操作GET均405，商家域ops路径404。HTTP200或方法拒绝不证明真实内部账号已成功审批退款。
- 独立公网GET复核时间`2026-09-06T03:11:14Z`：ops根页200，HTML/CSS/JS/panels/两SVG共6/6等于冻结ZIP字节；退款列表401、3动作GET405，delete/多余路径/无关owner路径404；app域ops.html、panels和owner退款路径均404。`/ops`无扩展名200只是主站首页fallback，无运营内容，不误当越权。主站health/deep仍200及ok/ready，database/queue/worker均ready；公开收费/charge_now/paid_launch仍true，未关闭主站收费。证据`public-readback.json`；没有真实登录或POST验收。
- 五文件备份与状态在该release的`.ops-switch/backup`和`state.json`；原API/前端镜像固定hold=`jiejing-ops-rollback:20260906-api`/`20260906-frontend`。原API image=`sha256:322127b9826f8d1ef49e261b9fcaaa8a9171228b1adc16164dbcd603c3719beb`。root所有的helper/receipt旁挂在releases目录；回滚使用同一receipt和`.ops-switch/rollback.json`，不回滚共享DB。保留恢复材料，不清理旧版本/volume。
- 脱敏证据在本地`output/ops-narrow-20260906/{receipt,dry-run,apply,readback,environment-preflight}.json`。无新收费、退款、真实订单query、OAuth、eBay或商家工作流业务操作。下一项是审查并另获准对齐运营端现有微信执行配置/真实内部身份，不能再重复此次代码同步。

- `ops.jiejing.shop` 实际仍由 `43.129.205.244:2222` 旧主机提供，前端版本 `20260828-ops-performance-v2`；缓存区分参数请求仍旧，不是简单浏览器缓存问题。
- 旧API容器持续13天、镜像 `sha256:322127b9826f8d1ef49e261b9fcaaa8a9171228b1adc16164dbcd603c3719beb`；没有 `review_platform_refund_confirmation`。旧ops Nginx反代本机旧API，未开放新退款列表/审核/执行/查询路由，不能仅复制新的ops.js。
- 两主机连接目标字符串指纹不同，但只读SQL的 current_database / inet_server_addr / inet_server_port 组合指纹相同，确认同一PostgreSQL数据库；不需要凭此进行数据库或DNS迁移。没有读取或输出连接凭据。
- 专用旧ops脚本只同步五个静态/代理文件，硬编码旧版本，不能更新API；不能作为完整退款链路发布证明。
- 既有AGENTS要求staging自动部署走GitHub手动通道，workflow仅允许main执行；本轮 `gh auth status` 未认证，本地origin/main为旧 `d809cfb`。未强推/合并main、未绕过规范用旧SSH staging全量apply；直接SSH更新旧ops前后端属于需要明确例外授权的路径。
- ops精确代理补丁已本地完成：仅GET退款列表、仅POST指定订单的review/execute/query，保留商家域owner路径404。`test_jiejing_operations_console.py` 的代理合同与本地HTTP匿名401/商家403/错误Host403/运营列表200/不存在订单404通过，`codex_jiejing_merchant_ops_surface_isolation_smoke.js` 离线矩阵通过；5种内存规则变异及独立泛路径变异被拒绝。只修改上述配置与两测试文件，尚未部署旧运营端，尚未实测真实Nginx新配置。
- 旧专用部署脚本/旧API同步仍待处理；没有新建绕过手动发布规范的路径。主站已完成的4c26ebc发布不要重跑。后续HEAD里的ops补丁只有专项通过，211/211证据只对应已部署4c26ebc，不能混为同一候选。
- 2026-09-06只读复查通道范围：GitHub白名单能包含新ops/API，但实际apply还更新Worker、Vault/边缘并处理两项私有配置，不是仅退款UI发布；旧ops专用脚本仅五静态/代理文件和前端，不含API。若以后获准窄范围SSH例外，必须另审具体执行：仅旧主机ops前端/代理/对应API，保存并验证旧API/前端实际镜像和文件、Compose身份，禁止碰主站、DNS、Vault/私有配置、Worker及共享PG恢复；回滚不能回滚共享数据库。现有GitHub回滚未明确恢复旧镜像，不能当成已验证窄范围恢复方案。本轮未连接服务器、未改脚本、未获得或使用该例外。

## 2026-09-05 结构/续接审查基线

- 审查 HEAD=`66032b3`；没有业务代码变更。详细证据与有限完成标准见 `JIEJING_WORKFLOW_CONTINUITY_AUDIT_20260905.md`，该文件不是新的状态索引。
- 新复现 W1/W2/W3：Listing在途切换店铺后旧响应覆盖当前编辑区；旧图片事实在跨设备恢复时遮住较新的Listing文案；先取全局最近窗口再筛项目使旧项目随任务增多误判证据缺失。未证明跨租户泄露、数据库记录被删或真实误发布。
- 初始W4/W5/W6发现：历史聊天只能浏览最近30条，且临时库确认账户同步删除超过50条的旧聊天；批量“还没有货源”按钮没有动作；Settings仍有要求商家看后端日志等运维式反馈。W4保留/分页已在下方本地收口，新增W4b同步失败归档边界待修；W5/W6未变。未证明生产哪些记录受影响。
- 防漂移 C1/C2：门禁结果未机器绑定源版本/候选；门禁固定“下一步”仍有旧SSH、准备数据库和Vault/KMS建议。不要执行这些过时建议；以本索引和AGENTS的现行规则为准。
- 本轮线上只读复核：健康/深健康正常；production_ready、beta_ready、can_accept_real_customers及billing.public_charging_allowed/charge_now_allowed为true；ops仍为20260828旧资产，app域ops路径404。没有本商品FAL/eBay或退款端到端的新证明。
- 当前仍未连接Chrome，未采集工作流新截图；按Product Design要求，未完成视觉审查，不拿旧截图作为当前UI缺陷证明。当前源码保留批量入口、桌面聊天优先/平板单列布局；需实页验收。
- 首批获准范围W1/W2/W3，随后“继续推进”接续W4，修复结果见下方；先W4b再W5/W6，C1/C2在下一次发布前处理。先修可重复的流程缺陷，再对AI CEO/Listing一处定视觉方案；不重新选品或全站换皮。

## 2026-09-05 W1/W2/W3修复收口（本地，未提交、未部署）

- W1：Listing在途请求绑定公司/用户/店铺/项目/请求代次；切走再返回也不能旧回包覆盖；新编辑保留，重复请求受限，旧失败不能清新请求忙碌态；同商品仅切换模块不取消结果。
- W2：较新已验证Listing不被旧vision空草稿遮住；按时间合并事实，清空/来源/冲突保留；当前文案编辑不覆盖，另一设备的新事实不能给本机旧文案错误授信。
- W3：项目证据先限定作用域/cutoff再取窗口；源调研/任务与执行父确认按受限主键恢复。其他任务及同项目版本增长、混合次级身份、显式冲突来源有回归，未提高真实写入权限。
- 已有本地证据：生成browser桌面/平板各16场景；恢复7组、商品资料UI18/18、发布预填11/11、路由HTTP30/30；项目证据新增9组及既有状态断言。完整测试范围、红灯与限度见 `JIEJING_WORKFLOW_CONTINUITY_AUDIT_20260905.md` 的“获准修复收口”。本地隔离数据/受控模型响应不是生产商家验收。
- 新恢复工具已接入门禁，清单212项但**未执行完整212项门禁**；旧211/211仅属于已部署4c26ebc。未打包、dry-run或apply，不重复既有部署。
- W1/W2/W3冻结时资产family=`20260905-workflow-recovery-v1`，app=`2c04c1daa279`、styles=`9e2a50d2359c`；后续W4已更新本地引用，见下方。首页/导航/布局不变，线上仍为上一轮版本。
- 当时下一项W4红灯：临时库依次sync1/30/20共51条，第一条SQL计数1→0，总数50；该DELETE在后续W4已移除，不再重复修复。不承诺已清理的生产聊天能自动恢复。
- 三项原有用户文件仍未改动/暂存；本批没有OAuth、真实模型/FAL、收费、退款或eBay操作；独立ops的GitHub发布/SSH例外权限问题仍未解除。

## 2026-09-05 W4历史保留与分页收口（本地，未提交、未部署）

- 账户同步只合并，不再按50条删除旧聊天。创建时间锚点固定；GET/SYNC保留旧字段并返回受公司/用户隔离的游标分页，默认30、最多50条。非法或其他账号游标统一400，空同步不代表清空历史；合法eBay账号删除流程的合规清理未移除。
- 沿用AI CEO顶部“查看更早对话”，近期30条同步缓存与按需加载的显示归档分离，模型仍取最近8轮。翻历史不触发模型/FAL/平台操作；错误就地重试、单飞、滚动锚、空过滤页、初始短历史增长和跨设备大量新消息缺口均有回归。
- 历史刷新/同步/分页及首次工作台加载绑定账号与请求代次；切A→B→A仍拒绝旧回包，旧401不再续期或登出新账号；旧finally不清新请求。共享fetch只增加可选的请求有效性检查，现有会话续期回归通过，没有更换登录架构。
- 后端7组新增临时库/PG原生类型适配器回放及76条HTTP流程通过；最后独立复核另拦住UTC转换越界日期使同步失败，两个极端日期先红后按服务器时间安全回退，7组复跑通过。桌面1440/平板1024各20场景通过，146轮完整可见、去重且模型8/同步30不变。相邻历史/租户缓存/会话续期、旧resilience、backend MVP、PG schema15/15、PG cutover、W3聊天相邻回归和账号删除兼容性通过。真实PG执行/性能及生产账号UI未验收。
- 新历史browser runner与既有W2恢复runner已接门禁、部署白名单及Node语法检查；只读清单213项、名称无重复，**未跑完整213项门禁**。未执行打包、生产dry-run/apply，也未再次部署旧版本。没有新增gate `--list` CLI（现工具不支持，统计通过只读import完成）。
- 本地资产family=`20260905-chat-history-archive-v1`，app=`d8b1c8c284bf`、styles=`9e2a50d2359c`；7处缓存引用与实际内容hash合同通过。部署/runner/local-first合同、语法、秘密扫描和diff检查见审查文件。三项原有用户修改保留，未暂存任何文件。
- **W4b剩余边界（不能称零丢失）**：本地实函数回放31条完成对话且历史同步持续失败，页面内存有31，但本地持久缓存和补同步载荷只有30；关页后可能缺第一条聊天档案。后端请求任务已保存脱敏响应，不等于聊天档案已可靠落库。下一批先补这一最小可靠归档路径及失败重试回归；不新增记忆插件/RAG、不扩大模型上下文、不静默建新的归档服务。已被旧逻辑删除的生产历史需另查可恢复来源，不能自动承诺找回。

## 自主推进批次收口状态（2026-09-05，本地）

- W4b服务端可靠归档、W5批量无货源入口、W6商家反馈与请求归属已冻结。W4b后端15组及HTTP、浏览器桌面/平板各26场景通过；独立后端7组、12并发claim和10并发旧SYNC不覆盖终态通过。W5/W6实际页面17组通过。不是生产用户操作或真实PostgreSQL并发证明。
- 新协议将请求终态与聊天归档同事务提交；浏览器未确认终态不SYNC，断流按精确ID恢复，旧缓存不能覆盖终态。旧客户端与纯本地时钟快捷回答仍沿用旧同步，不承诺任何场景零丢失或找回已删除历史。
- C1/C2已冻结：完整检查结果绑定源commit/tree及检查清单，拒绝脏目录、运行中变化、隐藏Git跟踪标记和错源/缺项证明；16组证据专项、候选微型包和部署/回滚合同通过。门禁清单216项；第二候选`0250ce6`已完整216/216通过，证据见下方，不能用历史211通过替代。
- 官网保留已批准内容/圆形AI CEO图/六板块/套餐，调整中文标题排印；修复手机登录被桌面双栏挤压、顶部关闭不可达及小平板输入过窄。桌面/平板/手机首页交互与320–1024共8组登录宽度/填写/关闭通过，无真实登录或POST。首页browser已加入门禁与部署白名单。
- 本地完整app截图确认的1024平板空状态输入裁切、任务摘要遮首条消息均已修复；桌面收起态同因遮挡一起修，桌面展开仍聊天746px/任务351px。复用历史browser runner增加4个实际app布局场景及展开/收起按钮、输入下沿hit-test，26历史场景与4布局场景通过。仅CSS位置/占位，不改业务/导航/聊天主次；平板展开仍沿用既有抽屉行为。
- 本次公开只读刷新：health=ok、deep=ready；production_ready/beta_ready/can_accept_real_customers=true，billing.public_charging_allowed/charge_now_allowed/billing_ready_for_paid_launch=true；blocker/warning=0。全面real_platform_writes_enabled=false，不代表受控通道关闭。公开投影没有退款执行结论；独立ops仍20260828旧资产，app域ops.html=404。没有重新核验/执行真实退款或eBay操作。
- app.js冻结LF内容hash=`d2dcc7345056`、styles=`885b316fada8`，7处引用family=`20260905-workflow-reliability-v1`。三项原有用户文件差异仍29/0、1/0、10/1，不进入候选。本批已提交为`f2ce760`；独立干净候选位于`C:\Users\57249\Documents\Codex\2026-09-06\jiejing-release-workflow`，完整216项结果214通过/2失败，1463.71秒，source_stable=true、release_eligible=false，证据在该目录`output/jiejing-precloud-deployment-gate/latest.json`。该候选不得打包/部署；session72669已结束exit1。
- 两个失败为merchant_surface_guard（旧正文匹配不接受标题span排印）与ai_ceo_phase0_contracts（两个抽取submit函数的fixture缺新history request context依赖，在行为断言前ReferenceError）。前者按真实h1可见语义修复，保留错标题/非h1不能替代的负向断言，专项通过；后者抽取真实scope/epoch/canonical依赖，完整21项及stream_error8、streaming合同、历史26+4布局通过，未改生产JS。另仅将GitHub完整preflight上限25→45分钟：实际24分24秒之外还需安装依赖，属于预算风险而非已发生CI超时；job定向7负例及四部署专项通过，权限/分支/runner/命令不变，未触发CI。即将提交这些回归/预算修订，另建`jiejing-release-workflow-r2`跑完整216项，不复用214项旧结果充数。

## 下一步（按顺序，不另起产品方向）

2026-09-06用户明确“批准，继续推进”，批准本批主站修复部署。以下为发布前过程记录，最终上线证据见本节“正式apply已成功”：当时HEAD/候选/包/216项证明/dry_run均未漂移，主站active仍`20260905T113551Z-4c26ebc487dd`，健康、私测与公开收费为true，ops仍旧版、app域ops路径404。生产手册另要求CI；普通`Jiejing CI`支持codex/** push，无需合并main或操作staging。虽然`gh auth status`未认证，但应用GitHub连接及Git凭据通道可用，不应再次把CLI未登录说成所有GitHub通道不可用，也不需要用户重新登录。

发布前历史扫描覆盖`d809cfb..0250ce6`的177提交、1019个唯一新增文本blob约294MB（含18个超2.5MB旧文本），283关联/134新增路径；无禁止路径或秘密规则命中。已将`0250ce6`推送到既有私有仓库`f4zjwy6j94-star/JIEJING-SAAS`的新`codex/ai-ceo-real-merchant-loop`远端分支，未改main。普通CI run=`33982650298`，URL=`https://github.com/f4zjwy6j94-star/JIEJING-SAAS/actions/runs/33982650298`，精确SHA相同，**失败**：旧`test_jiejing_new_ebay_account_low_risk_runbook.py`仍要求`renderSaasNewEbayAccountOnboardingPanel`。已本地复现；历史`d2158a6`为商家/运营隔离主动删除该内部验收面板，而当前merchant_surface_isolation正向禁止它，属于测试相互冲突，不是Linux差异或已确认业务缺陷。不要恢复面板、不要将旧216通过当成CI通过，`0250ce6`暂不可apply。

当前只修验证代码：旧runbook测试改为禁止内部面板回流并保留当前店铺连接证据，原checker的OAuth/写入/动作确认合同未改；18个负例和跨模块移动正例、原专项/商家隔离/OAuth UI专项通过。独立AST审查确认原checker调用及其后32条语句完全不变。另8个普通CI专项均已补入门禁，现224项、224个唯一名称，26个普通CI Python脚本全部覆盖；增加实际run脚本子集检查及漏接/错误解释器负例。部署四专项、版本绑定证据16/16及其余7个新接专项通过，部署白名单本来齐全无需修改。下一候选须重新完整224项并通过精确SHA的CI。app.js/CSS/后端/生产配置未改，本批已批准的产品内容没有扩大。尚未正式部署；Chrome明确不可用，不是用户登出证明，未重复登录或安装。

上述两项回归修正和CI预算已提交`0250ce6`。第二个独立干净候选`C:\Users\57249\Documents\Codex\2026-09-06\jiejing-release-workflow-r2`已完整216/216通过，失败0，耗时1445.32秒，source_stable/release_eligible均true、secret_exposed=false，session73812已结束exit0。不要修改此目录或重跑同一检查。门禁run_id=`0bbaca06fb64436fadb4c0e3996cb9cc`，source_tree=`5e5900cb14eef85fc9743f24ac813e16120dd06a`，UTC开始/结束`2026-09-05T16:44:27.565227Z`/`2026-09-05T17:08:32.877065Z`；证据`output/jiejing-precloud-deployment-gate/latest.json`。

对应457文件发布包`output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-170914.zip`及同名`.manifest.json`已生成；BUNDLE_SHA256=`4d9549f2acac2efc3aef221b2476cc6f7daa328411a6a414c22eb5eb36210f87`，MANIFEST_SHA256=`60f44d5fbc05a3f33c98246cf3ec9eda4ff0f4e4446c2eb325ba019f8a9c6a26`。生产dry_run已通过、session49208 exit0：candidate_release_persisted=false、active_switched=false、private_env_normalization_required/applied=false，仍为原`20260905T113551Z-4c26ebc487dd`发布。工具实际输出的脱敏副本为该候选`output/jiejing-production-deploy/dry-run-20260905-170914.json`。后续CI失败已使此候选停止apply；该旧包与dry_run只保留为历史证据，不重复运行或冒充下一候选证明。未更新独立ops、未跑生产用户商品流程。

独立只读包审查通过：216项唯一且全通过；manifest证明/原报告SHA/源文件指纹/检查清单一致；457个ZIP条目逐文件摘要及Git blob等于`0250ce6`；无私有env、output、截图、数据库或第三方依赖目录（六个公开`.env.example`模板例外）。三项用户原有修改未混入包。候选仍干净；主仓库两份执行/审查文档为本批验证结果更新，尚未提交，三项原用户修改原样保留。

正式部署授权已收到；先冻结本次验证修订的新提交，在第三个独立干净候选`C:\Users\57249\Documents\Codex\2026-09-06\jiejing-release-workflow-r3`并行执行完整224项与GitHub普通CI，两者通过后重新打包/dry_run/apply。不是重新申请普通方案或扩张产品范围。独立ops仍需既有GitHub通道或明确例外，不能把主站生产dry_run解释为该权限。W1–W6及C1/C2已处理的缺陷不要重做，不重新部署已完成的旧商家版本，也不重新选品。

第三候选已冻结并推送`1550105b53825a65f876808bff059a4e6d0c0a8a`，tree=`5f8e28631bac95aae9fc27297cf30c3c9e160b45`。普通GitHub CI run=`33983427176`、job=`101352603809`已全部15步骤success，北京时间2026-09-06 02:15:25完成，URL=`https://github.com/f4zjwy6j94-star/JIEJING-SAAS/actions/runs/33983427176`。完整224/224通过、失败0、1468.03秒，run_id=`33a289f802b64f8bb668e7cc0738fd3f`，source_stable/release_eligible=true，session86769已结束exit0；证据在r3的`output/jiejing-precloud-deployment-gate/latest.json`。不要重复门禁或修改r3候选文件。

新包457文件：r3的`output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-183707.zip`及同名manifest；BUNDLE_SHA256=`ebe782eed7dd2df8819a5f51b99a9ed2c5ed0e85a0993b8c88fa0159402d3e99`，MANIFEST_SHA256=`d37a70eec570a2fa628548cf70024a36b6110dafb6f099613c69168b3df6b795`。独立逐文件/源blob/门禁proof验证通过；相对0250包仅3个测试/门禁成员变化，生产内容逐字节不变。生产dry_run通过、session76803结束exit0、未永久落候选/切active/改私有配置，回执保存为r3的`output/jiejing-production-deploy/dry-run-20260905-183707.json`。

**正式apply已成功，session44184结束exit0，不得重复执行。** release=`20260905T184522Z-1550105b5382`；回执为r3的`output/jiejing-production-deploy/apply-20260905-183707.json`，含`TIMER_FIRST_ONESHOT_VERIFIED=1`、`TIMER_INSTALL_APPLIED=1`、`CANDIDATE_RUNTIME_IMAGE_COHERENCE=verified`及持久化/切换成功；私有env权限规范化required/planned/applied均false。此次只面向主站，资金/平台真实操作为零。

部署后独立读回证据为r3的`output/jiejing-production-deploy/readback-20260905-183707.json`：active/manifest两个SHA/四服务Compose标签与新release一致，DRY_RUN=0；API健康，API image=`sha256:5f8f06231ad8cb899232c22fd930c4b43371d33e202b49b56bb81533cb6b5e80`、Worker image=`sha256:df91875a5d258a83baef1eba86423729204a54fcbd65ace2539d248c3650b500`。两旧image hold分别匹配上版API/Worker。service success/0、timer enabled/active且有下次时间，service/timer无drop-in；三个安装文件与新包内容一致。private仍原引用，目录0700、两env0600且均root所有/无符号链接，未读取秘密值。

本次生产GET：health/deep均200及ok/ready；production_ready/beta_ready/can_accept_real_customers和billing公开收费/charge_now/paid_launch均true，blocker/warning=0。仅读7个非秘密键计算effective：全面写入false、受控草稿保存true、受控既有草稿发布true。ops仍200及20260828旧资产，app域ops.html=404；真实退款运营UI、具体账号资格和本商品发布仍未验收。

公开UI使用可用的Codex内置浏览器验收：1440×1000、1024×900、390×844；标题按短语排印、圆形AI CEO图和既有内容保留；工作流程链接到#workflow，05素材演示可切换；手机主入口打开登录，输入宽328.8px，填写/清空测试邮箱与关闭成功，没有提交登录/注册。控制台未见相关error/warn，实页截图在本任务工具证据中。JS/CSS归一化SHA等于新包；index.html和带start=app的app.html去除唯一Cloudflare统计script行后逐字相等，未带start参数的app.html按既有规范重定向首页，不误判资产漂移。Chrome不可用仍未解除；上述不是登录后商品流程验收。

1. 运营端前后端同版发布已在本轮明确SSH例外授权后完成，见上方收口，不得重复。当前下一项是对齐旧ops的微信执行配置和真实内部身份验收；live/refund运行时仍false，不得私自改私有配置、转移秘密或发起真实退款来补证据。
2. 商家主机新增W1–W6/C1/C2/UI批次已随`1550105`部署并复核，不重做。线上app hash=`d2dcc7345056`、styles=`885b316fada8`，family=`20260905-workflow-reliability-v1`；独立ops现已提供`d205c9c5f13b`同版资源；保留三项用户原有修改。
3. 本轮已核对运营端前端资产、后端代码、精确退款API路径及app域ops路径404；内部运营已登录GET列表200仍需实际既有会话，不伪造身份/改allowlist。不得执行真实收费/退款作为默认部署测试。
4. 网站在线、私测可用、公开收费可用、退款端到端可用、受控eBay通道启用及真实发布验收分别报告。
5. Chrome 接续同一个平板支架项目，全程通过捷境 UI 复验生成、素材与发布前检查；真实来源或账号资格不满足时停在该明确阻断，不造成功回执，不重复 OAuth/支付/退款。
6. 设计工具用于有证据的当前界面审查、选定方向与视觉对照验收。保持已批准产品逻辑；先检查实际页面，再作有界调整，不凭参考库重搭全站。

## 设计工具与防漂移

- `grill-me` 已有：方案推敲，能从代码找到答案就先查，不把每次实现变成对用户的长问卷。
- `gh-fix-ci`、`gh-address-comments`：2026-09-05 从 `openai/skills` 安装，CI/审查辅助，不是视觉能力。
- Product Design：官方市场插件 `product-design@openai-curated-remote`，已安装 0.1.53。用于流程截图审查、视觉探索、原型对照；不代表自动提升生产质量。
- Awesome DESIGN.md：参考库 `VoltAgent/awesome-design-md`，固定提交 `8147538b4226ae41e2487a9179e3bcc1f68e8554`。本地在当前 Codex 任务目录的 `references/awesome-design-md`，不在生产仓库/部署包内，不是可执行 Skill。
- `jiejing-design-system` 已移除旧四套餐、新手入口、工作记录主导航规则；`open-design` 不再把技能当产品事实来源。产品决定以本仓库 AGENTS 和用户最新要求为准。
- 没有安装第三方记忆后台钩子，没有关闭压缩/放宽权限，没有导出完整聊天或凭据。文件降低漂移风险，但不能保证零遗漏；每次恢复仍需只读校准。

## 报告纪律

不要用任意百分比、模型等级或历史测试数证明成熟度。只报告本轮证据、尚未验证项和下一具体动作。新增状态须带日期；旧状态不可自动变“当前”。出现信息矛盾时保留现有数据，局部查证，不重新开始项目。
