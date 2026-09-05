# 捷境当前执行状态

最后更新：2026-09-05。用途：中断、重启或压缩后从此处续接；不是公开产品文案，也不是线上状态证明。维护本文件，不另建同名意义的平行“最新状态”。旧日期交接仅用于按需追溯。

## 目标与本轮范围

最低成本完成 eBay-first AI CEO SaaS MVP：商家在捷境内留下真实对话、调研、商品资料、Listing、素材及审核记录，满足事实、图片权利与账号条件后，通过捷境保存 eBay 草稿并经动作时确认发布。不得用 Codex/API 直接造业务记录冒充商家 UI 验收。

用户最新要求：技能按任务自主使用，不等用户重复指挥；客观审查项目并修复漏洞、报告真实进度。接续已有本地修复并按既有授权验证/部署；没有因安装设计工具就开始新的全站重构。

## 精确续接点

- 实际仓库：`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`。
- 分支：`codex/ai-ceo-real-merchant-loop`；本轮修复前 HEAD：`10d7887`（`fix: make AI CEO project creation idempotent`）。本轮候选提交以当前 `git log` 为准；恢复时再次核对，不能将基线当永久 HEAD。
- 工作区有本轮未提交修复，不得重置、清理或覆盖。
- 三个原有用户修改文件不要顺手暂存/提交：`jiejing_saas/readiness.py`、`tools/test_jiejing_phase2_response_boundary_hardening.py`、`tools/test_jiejing_platform_trial_activation_guard.py`。
- 当前商品：平板电脑支架（折叠便携款）；项目 `listing-project-0ef70f19c079b4261e82`；报告 `report_19fcfc7b9f88f0eb`；候选 `candidate_1`。
- 调研、导入、商品资料模块和一次有缺陷的 Listing 生成已做。续接同项目，修复上线后再生成一次验证，不从选品重新开始。
- 本轮尚无该商品真实 FAL/eBay 操作完成证明；AI 生成资料不能冒充真实货源事实，不能因用户要求跑流程而编造可公开销售的参数。

## 已修复但尚未部署

本地专项验证由本轮执行记录确认；完整候选版本门禁与生产 UI 复验仍未完成。

- Listing 买家文案/商品事实约束、敏感信息输入阻断、失败用量保留；eBay 写入前事实/兼容性边界。
- 商品图片识别只产生待确认建议；清空字段不被旧建议复活；生成失败仍保留来源与冲突元数据。
- 商品资料保存单飞与忙碌状态；按公司、店铺、项目、归一化内容在同事务内幂等保存任务/报告，修改内容才创建新版本。
- 额度激活不重置试用窗口；预留、消费、释放有状态记录；并发复用已释放名额增加数据库串行保护；实际模型调用后审计失败不再误释放额度。
- 部署白名单/语法检查已纳入新依赖及回归；JavaScript 不再误送 Python 编译。

已通过的关键专项：商品资料 UI 18/18、发布预填 11/11、5 并发 HTTP 同版本保存、修改新版本及租户/店铺/项目隔离、Listing 生成/事实/视觉/敏感文本、quota/window/lifecycle/HTTP concurrency、schema 15/15、SQLite→PostgreSQL rehearsal、secret scan、Python/Node 语法与 diff 检查。完整门禁未完成，不能据此宣称整个 SaaS 或生产已通过。

## 本轮权限审计：专项修复通过，尚未部署

2026-09-05 代表性代码审计，本地假用户/假订单/假 provider 复现，真实退款调用为零：

1. P1：普通商家可申请、自批并执行自己的 SaaS 订阅退款。`api_server.py` 的 refund confirmation/execute 与 `billing_domestic.py` 共用商家 owner 权限，未要求平台内部审核者。应保留申请能力，将平台自身退款审批与执行限定内部运营权限，并校验审核依据；不能以关闭收费或退款开关代替修复。
2. P2：viewer 可取消任务、运行 worker、拒绝/修改确认单，部分变更入口缺岗位权限校验。
3. P2：团队邀请未执行套餐席位上限，需事务内统计占用/待接受席位及并发最后席位保护。

独立复核又确认并修复了关联问题：退款查询恢复遗漏内部审核者名单、退款在途仍可撤销审批/并发重复请求 provider；新席位检查沿用的有效订阅判定漏认 `wechat_pay_native`，且未检查已过期的 `active_until`。前者有本地假 provider 复现；后者使用临时库复现。退款改为数据库发送前原子认领，不确定结果保留处理中并只查询；微信稳定退款请求号存在 provider 幂等保护，本地重复请求不等于已发生双倍真实退款。

收口专项：退款权限 13/13、席位与实际微信订阅 17/17；退款/素材点/provider/maintenance/merchant refund browser/ops console 既有回归通过。ops 浏览器桌面、平板、手机覆盖审核理由、精确金额确认、查询恢复。独立复验 paid→processing→refunded 权益分别保留/保留/撤销。所有资金 provider 均本地假实现，未真实退款；PostgreSQL 并发未实测。

适配了旧 `billing_test_provider` 对商家暴露 `merchant_launch_path` 的过时要求，改为当前正向允许字段与内部信息隔离断言，保留所有禁止真实收费和私测约束；4 类故意破坏投影均被测试拒绝。生产商家投影未因测试而修改。

完整审计范围、发现与验证限度见 `JIEJING_SECURITY_RELIABILITY_AUDIT_20260905.md`。当前正在准备干净候选提交及 211 项完整门禁，不能据专项通过宣称生产修复完成。

这是有限代码审计，不是全局零漏洞证明。没有新增首页夸大能力或跨租户泄漏的确认发现。相关入口：`tools/test_jiejing_domestic_billing_refund.py`、`tools/test_jiejing_domestic_billing_refund_browser.py`；成员/确认/队列路由见 `jiejing_saas/api_server.py`。

## 2026-09-05 只读线上校准

- `/health` 200，`status=ok`；`/health/deep` 200，`operational_health.status=ready`，database/queue/worker 均 ready。
- `/readiness/product-saas` 的 `readiness`：`production_ready=true`、`beta_ready=true`、`can_accept_real_customers=true`、blocker/warning 均 0；`real_platform_writes_enabled=false`。
- 后端微信支付能力合同只读选取布尔：`charge_now_allowed=true`、`real_checkout_ready=true`、`public_commercial_release_approved=true`、`refund_now_allowed=true`。没有切换开关，没有执行真实收费/退款。
- `ops.jiejing.shop` 200；`app.jiejing.shop/ops.html` 404；证据刷新 timer active，service Result=success、ExecMainStatus=0。
- active link 为 `/opt/jiejing-production/app`，指向 `releases/20260831T203536Z-10d7887d6e73/app`；manifest SOURCE_COMMIT 与本轮修复前 HEAD 一致。API/Worker compose 标签、发布目录、private env 引用一致；没有读取或输出秘密值。
- 当前发布 BUNDLE_SHA256=`ae3a6f28f7e8a8e949eb915e8902e8a0618694a5b1aed489ac8a21849bd5a4b5`；MANIFEST_SHA256=`35dbbd2e3eac72dd86f018ee88d04a1ac90b105a693474d4859fd1ab4123fe7a`。
- 上述绿色运行状态不覆盖本次刚发现的权限缺陷；不可宣称已修复上线。
- 本轮 CUA 仅发现空的内置浏览器，指定 Chrome 返回 `Browser is not available: chrome`。这不是用户登出证明；没有重复 OAuth/登录/重装，没有完成登录后生产页面的视觉审查或商家操作。局部本地浏览器测试不等于线上用户旅程验收。

## 下一步（按顺序，不另起产品方向）

1. 权限、席位与关联恢复问题专项已收口；不再重做复现或新增产品范围。保留现有支付、退款和商家业务能力，不通过盲目切开关掩盖问题。
2. 静态资源 hash 已更新：app `f27e73cdae74`，styles `9e2a50d2359c`，ops `d205c9c5f13b`；精确提交本轮文件，保留三项用户原有修改。
3. 在干净提交检出目录运行完整门禁与生产 bundle/dry-run。既有部署授权适用于本任务代码发布；不等于真实收费、退款或 eBay 发布授权。执行 `docs/JIEJING_PRODUCTION_DEPLOY_RUNBOOK_20260823.md`，不混用旧 staging 路径。
4. 部署后核对 release/manifest/源码提交、health、deep、product-saas readiness、ops 域200和 app 的 ops.html 404。网站在线、私测可用、公开收费可用、平台写入可用分别报告。
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
