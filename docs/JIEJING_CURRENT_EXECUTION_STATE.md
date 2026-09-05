# 捷境当前执行状态

最后更新：2026-09-05。用途：中断、重启或压缩后从此处续接；不是公开产品文案，也不是线上状态证明。维护本文件，不另建同名意义的平行“最新状态”。旧日期交接仅用于按需追溯。

## 目标与本轮范围

最低成本完成 eBay-first AI CEO SaaS MVP：商家在捷境内留下真实对话、调研、商品资料、Listing、素材及审核记录，满足事实、图片权利与账号条件后，通过捷境保存 eBay 草稿并经动作时确认发布。不得用 Codex/API 直接造业务记录冒充商家 UI 验收。

用户最新要求：技能按任务自主使用，不等用户重复指挥；客观审查项目并修复漏洞、报告真实进度。接续已有本地修复并按既有授权验证/部署；没有因安装设计工具就开始新的全站重构。

## 精确续接点

- 实际仓库：`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`。
- 分支：`codex/ai-ceo-real-merchant-loop`；本轮修复前 HEAD：`10d7887`（`fix: make AI CEO project creation idempotent`）。本轮候选提交以当前 `git log` 为准；恢复时再次核对，不能将基线当永久 HEAD。
- 商家生产主机已部署 `4c26ebc487dd40ff1bae45336723eb2910af30fb`（包含此前 `ca5a20d`、`801dc88`、`7a92620` 修复）；完整门禁211/211、dry-run、apply和线上健康复核通过。独立ops仍是旧前后端，见下方新确认阻断；不能称整套退款运营链路已完成。主工作区仍保留三项原有用户修改，不得重置、清理或覆盖。
- 三个原有用户修改文件不要顺手暂存/提交：`jiejing_saas/readiness.py`、`tools/test_jiejing_phase2_response_boundary_hardening.py`、`tools/test_jiejing_platform_trial_activation_guard.py`。
- 当前商品：平板电脑支架（折叠便携款）；项目 `listing-project-0ef70f19c079b4261e82`；报告 `report_19fcfc7b9f88f0eb`；候选 `candidate_1`。
- 调研、导入、商品资料模块和一次有缺陷的 Listing 生成已做。续接同项目，修复上线后再生成一次验证，不从选品重新开始。
- 本轮尚无该商品真实 FAL/eBay 操作完成证明；AI 生成资料不能冒充真实货源事实，不能因用户要求跑流程而编造可公开销售的参数。

## 商家生产主机已部署的修复

本地专项、完整候选门禁和商家主机生产部署已通过；独立ops同步和已登录生产商家的UI复验未完成。

- Listing 买家文案/商品事实约束、敏感信息输入阻断、失败用量保留；eBay 写入前事实/兼容性边界。
- 商品图片识别只产生待确认建议；清空字段不被旧建议复活；生成失败仍保留来源与冲突元数据。
- 商品资料保存单飞与忙碌状态；按公司、店铺、项目、归一化内容在同事务内幂等保存任务/报告，修改内容才创建新版本。
- 额度激活不重置试用窗口；预留、消费、释放有状态记录；并发复用已释放名额增加数据库串行保护；实际模型调用后审计失败不再误释放额度。
- 部署白名单/语法检查已纳入新依赖及回归；JavaScript 不再误送 Python 编译。

已通过的关键专项：商品资料 UI 18/18、发布预填 11/11、5 并发 HTTP 同版本保存、修改新版本及租户/店铺/项目隔离、Listing 生成/事实/视觉/敏感文本、quota/window/lifecycle/HTTP concurrency、schema 15/15、SQLite→PostgreSQL rehearsal、secret scan、Python/Node 语法与 diff 检查。最终完整门禁211/211通过，但这不证明独立ops同步或真实商家全流程验收通过。

## 本轮权限审计：商家主机已部署，独立ops待同步

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

## 新确认阻断：独立ops未同步

- `ops.jiejing.shop` 实际仍由 `43.129.205.244:2222` 旧主机提供，前端版本 `20260828-ops-performance-v2`；缓存区分参数请求仍旧，不是简单浏览器缓存问题。
- 旧API容器持续13天、镜像 `sha256:322127b9826f8d1ef49e261b9fcaaa8a9171228b1adc16164dbcd603c3719beb`；没有 `review_platform_refund_confirmation`。旧ops Nginx反代本机旧API，未开放新退款列表/审核/执行/查询路由，不能仅复制新的ops.js。
- 两主机连接目标字符串指纹不同，但只读SQL的 current_database / inet_server_addr / inet_server_port 组合指纹相同，确认同一PostgreSQL数据库；不需要凭此进行数据库或DNS迁移。没有读取或输出连接凭据。
- 专用旧ops脚本只同步五个静态/代理文件，硬编码旧版本，不能更新API；不能作为完整退款链路发布证明。
- 既有AGENTS要求staging自动部署走GitHub手动通道，workflow仅允许main执行；本轮 `gh auth status` 未认证，本地origin/main为旧 `d809cfb`。未强推/合并main、未绕过规范用旧SSH staging全量apply；直接SSH更新旧ops前后端属于需要明确例外授权的路径。
- ops精确代理补丁已本地完成：仅GET退款列表、仅POST指定订单的review/execute/query，保留商家域owner路径404。`test_jiejing_operations_console.py` 的代理合同与本地HTTP匿名401/商家403/错误Host403/运营列表200/不存在订单404通过，`codex_jiejing_merchant_ops_surface_isolation_smoke.js` 离线矩阵通过；5种内存规则变异及独立泛路径变异被拒绝。只修改上述配置与两测试文件，尚未部署旧运营端，尚未实测真实Nginx新配置。
- 旧专用部署脚本/旧API同步仍待处理；没有新建绕过手动发布规范的路径。主站已完成的4c26ebc发布不要重跑。后续HEAD里的ops补丁只有专项通过，211/211证据只对应已部署4c26ebc，不能混为同一候选。

## 下一步（按顺序，不另起产品方向）

1. 本地ops精确路由回归已收口；通过现有GitHub手动通道规划并执行运营端前后端同版发布，或取得针对旧运营主机的明确SSH部署例外授权。不能仅凭HTTP200、静态更新或refund能力布尔宣布成功。
2. 商家主机的完整门禁、dry-run、apply和健康复核已完成，不重做。当前 app hash=`1f4d60564877`，styles=`9e2a50d2359c`，候选ops=`d205c9c5f13b`但独立ops尚未提供此版本；保留三项用户原有修改。
3. 运营端后续发布要核对前端资产、后端代码、精确退款API路径、内部身份限制及app域ops路径404。不得执行真实收费/退款作为默认部署测试。
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
