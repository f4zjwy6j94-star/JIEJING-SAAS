# 捷境大陆支付上线控制统一实施计划

日期：2026-07-27

批准设计：`docs/superpowers/specs/2026-07-27-jiejing-launch-completion-program-design.md`

## 状态与目标

本计划实施总体方案 A 的第一阶段。目标不是重写微信支付，而是把现有微信支付 Native、国内订单、签名回调、主动查询、退款和权益证据汇总为一个大陆正式支付上线状态，并让付费审批包、产品 readiness、生产发布门禁和内部运营控制读取同一个后端真相。

本阶段不调用真实支付 API，不创建可支付订单，不执行退款，不改变公开收费状态，不进行 eBay OAuth 或平台写入。

## 不可协商约束

- 保留当前脏工作区，不 reset、clean、checkout、stash、覆盖或全盘格式化。
- 微信支付 Native 是大陆首发路线；Stripe 只作为未来国际路线和兼容信息。
- 一次受控支付只能证明提供者生命周期，不能自动批准公开收费。
- `public_charging_allowed=false`、`charge_now_allowed=false`、`triggers_real_charge=false` 和 `real_platform_writes_enabled=false` 必须保持。
- 不读取、打印或测试真实支付 Secret；测试只使用现有 fake transport、环境存在性布尔值和本地数据库证据。
- 保留 `calls_stripe_api=false` 等既有负向安全字段，不能把它们误删为“Stripe遗留”。
- 不修改独立 `ops.js`/`ops.html`；当前独立运营后台不消费 launch-control。本阶段真正消费者是后端 owner packet 与内部管理员可见的 `app.js` owner panel。
- 不新增第 108 个预云门禁项；扩展现有检查，完整门禁仍必须是 107/107。
- 本地实施完成不等于部署批准。部署前必须先解决远端 `main` 与当前完整已部署脏基线的版本身份一致性。

## Phase 0：允许使用的现有 API 与复制来源

### 支付策略和微信契约

- `jiejing_saas/billing_payment_options.py:21`：`build_mainland_payment_strategy(settings: SaaSSettings) -> dict[str, Any]`。复用其目标区域、国内提供者选择和未来国际路线结构。
- `jiejing_saas/billing_wechat_pay.py:46`：`build_wechat_pay_native_contract() -> dict[str, Any]`。只读取配置存在性和派生布尔值，不调用网络。
- `jiejing_saas/repository.py:5074`：`domestic_payment_acceptance_evidence()`。复用受控支付证明、验证支付计数和始终关闭公开收费的证据。
- `jiejing_saas/billing_domestic.py:134-1483`：复用国内订单、查询、关闭、退款审查和运营快照已经实现的能力标记，不重做状态机。

### 安全与测试模式

- `tools/test_jiejing_domestic_billing_production_completion.py:71-133`：使用 fake provider create/close，证明测试不调用外部支付。
- 同文件 `251-267`：受控实付证明不得打开公开收费。
- `tools/test_jiejing_fixed_launch_progress.py:112-134`：固定支付分保持 16/20，公开收费 4 分仍属于联合批准。
- `tools/test_jiejing_mainland_payment_strategy.py:184-187`：即使形式条件就绪，测试也必须保持不扣费。
- `jiejing_saas/paid_launch_approval_packet.py:341-400`：复用 `_step()` 和 `_external_item()` 的安全字段。
- `app.js:40122-40166`：内部 dossier 使用通用 section/action renderer；优先调整后端字段，不新增前端 provider 分支。

### 禁止模式

- 禁止只把 `stripe_live_cutover` 文本替换成微信，但继续用 Stripe rehearsal 判断 ready。
- 禁止把旧 `billing_ready_for_paid_launch` 的 Stripe external-provider 语义直接当作大陆上线真值。
- 禁止用 `refund_now_allowed` 单独证明退款已获正式批准。
- 禁止同时输出 canonical 和 legacy step 到主步骤集合，造成重复 blocker 和错误计分。
- 禁止删除旧接口 alias 或负向安全字段。
- 禁止为修 owner packet 改动独立运营后台的经营聚合接口。

## Phase 1：测试先行建立大陆支付单一状态

### 文件

- 修改 `jiejing_saas/billing_payment_options.py`。
- 扩展 `tools/test_jiejing_mainland_payment_strategy.py`。

选择在现有 provider-neutral 文件内增加聚合器，不新增运行时文件，从而避免部署白名单和 274 文件包契约无意义变化。

### RED

为新函数增加失败测试：

```python
build_mainland_payment_launch_status(
    settings: SaaSSettings,
    repository: SaaSRepository,
) -> dict[str, Any]
```

覆盖：

1. 主市场为大陆，`primary_provider=wechat_pay_native`。
2. `future_international_payment.provider=stripe`，但 Stripe 缺失不进入大陆 blockers。
3. 微信配置缺失时精确 blocked，不因异常或空字典假阳性。
4. 受控实付存在时 `controlled_acceptance_proven=true`，但公开收费仍 false。
5. 代码能力、配置存在、真实证据、主理人批准分别返回，不能合并成一个模糊布尔值。
6. 构建状态不调用任何 create/query/refund transport。
7. 序列化结果不包含 Secret、原始回调、订单、租户或资源标识。

先运行并确认缺少新函数而失败：

```powershell
python tools/test_jiejing_mainland_payment_strategy.py
```

### GREEN

实现 `build_mainland_payment_launch_status()`，复用：

- `build_mainland_payment_strategy(settings)`；
- `build_wechat_pay_native_contract()`；
- `repository.domestic_payment_acceptance_evidence()`。

契约版本使用 `2026-07-27-mainland-payment-launch-v1`。核心字段至少包括：

- `market=mainland_china`；
- `primary_provider=wechat_pay_native`；
- `future_international_payment`；
- 配置完成计数；
- 签名支付和退款回调能力；
- 真实订单与主动查询能力；
- 受控支付证明；
- 额度和权益持久化能力；
- 生产环境与主理人批准状态；
- 精确 `paid_launch_blockers`；
- `public_charging_allowed=false`；
- 全部负向安全字段。

将真实可支付提供者条件命名为 `provider_checkout_ready`，不要将它直接命名为公开收费许可。公开收费仍由更高层商业发布门禁和主理人批准控制。

## Phase 2：统一 billing plan 与公共 readiness

### 文件

- 修改 `jiejing_saas/billing_plan.py`。
- 修改 `jiejing_saas/readiness.py`。
- 扩展 `tools/test_jiejing_domestic_billing_production_completion.py`。
- 扩展 `tools/test_jiejing_fixed_launch_progress.py`。

### RED

增加回归，证明：

- 微信完整或受控证明存在而 Stripe 未配置时，公共 billing 状态不再返回 `external_paid_subscription_provider_not_configured` 等大陆无关 blocker。
- `provider=wechat_pay_native`、`checkout_mode=native_qr`。
- `hosted_payment_page_required_for_formal_payment=false`，使用短期 Native QR。
- 支付和退款签名能力来自微信契约，不来自 Stripe webhook/Portal。
- 固定支付得分仍为 16/20；主理人公开收费批准仍为 0/4。

### GREEN

- `build_billing_plan()` 增加 `mainland_payment_launch` 字段，但保留现有 Stripe subscription 数据作为 `future_international_payment` 兼容信息。
- `_billing_item()` 和 `_public_billing_status()` 改读统一聚合器。
- 公共 readiness 只返回商家可理解的提供者、状态、计数和下一阻塞，不暴露内部环境键、证据 ID 或提供者诊断。
- `billing_ready_for_paid_launch` 保留兼容字段；新增明确的 `mainland_payment_ready_for_owner_approval`，后续内部消费者只读新字段。

## Phase 3：迁移付费上线审批包

### 文件

- 修改 `jiejing_saas/paid_launch_approval_packet.py`。
- 修改 `tools/test_jiejing_paid_launch_approval_packet.py`。

### RED

迁移 exact-set 断言，主步骤必须是：

1. `stable_domain_hardening`；
2. `wechat_pay_native_cutover`；
3. `no_charge_launch_rehearsal`；
4. `new_ebay_account_low_risk_smoke`。

外部配置键将 `stripe_live_products_prices_webhook` 替换为 `wechat_pay_native_production_cutover`。测试必须证明 Stripe 只存在于 `future_international_payment`，且不参与 `blocked_count`、`next_step` 或主序列。

### GREEN

- 合同版本升级为 `2026-07-27-paid-launch-approval-packet-v2`。
- `_build_steps()` 的大陆支付步骤只读取统一聚合器。
- `_external_configuration_items()` 只输出微信生产切换所需环境键名称和派生布尔值，不输出值。
- 旧 `summary.stripe_rehearsal_status` 可作为 deprecated 兼容字段保留，但不能参与 ready 判定。
- 保留 `calls_stripe_api=false`、旧 `/commercial/...` API alias 和所有 no-charge/no-write 安全标志。
- 本地 docs 指向已批准微信规格和生产运行手册；Stripe 文档只属于未来国际信息。

## Phase 4：原子迁移内部 owner 控制消费者

### 文件

- 修改 `jiejing_saas/owner_launch_control.py`。
- 修改 `assets/jiejing-settings-panels.js`。
- 修改 `tools/test_jiejing_owner_launch_control.py`。
- 修改 `tools/test_jiejing_owner_launch_control_access.py`。
- 修改 `tools/test_jiejing_owner_launch_control_ui.py`。
- 修改 `tools/test_jiejing_frontend_settings_module_split.py`。
- 修改 `tools/codex_jiejing_owner_launch_control_smoke.js`。
- 修改 `tools/codex_jiejing_paid_cutover_decision_smoke.js`。

### RED

将所有 old exact key、步骤和 founder action 断言迁移为微信 canonical key。保留并重新验证：

- owner/admin-only；
- 商家 403；
- legacy commercial route 兼容；
- dossier copy/download 不泄漏 Secret；
- 不创建真实 Checkout、不调用支付 API；
- 主站不会公开运营诊断。

### GREEN

- owner control 合同升级为 `2026-07-27-owner-launch-control-v8`。
- summary、lanes、external blockers、internal queue、cutover checklist、dossier、war room 和导出报告全部读取 canonical 大陆支付字段。
- 清除所有把 Stripe 描述成大陆前置条件的文案。
- 保留 `calls_stripe_api=false` 和“禁止创建真实支付”的 provider-neutral安全提示。
- 不修改独立 `ops.js`/`ops.html`；`app.js` 通用 renderer 无需 provider switch 时也不修改。

## Phase 5：迁移生产发布门禁

### 文件

- 修改 `jiejing_saas/production_release_gate.py`。
- 修改 `tools/test_jiejing_production_release_gate.py`。
- 修改 `tools/test_jiejing_external_launch_blocker_gate.py`，仅在现有断言覆盖旧支付键时。

### RED

证明：

- production billing section 使用大陆聚合器和微信审批包；
- `_required_external_evidence()` 不再要求 `stripe_live_billing`，改为微信生产切换证据；
- 微信配置或退款证据不足时精确 blocked；
- Stripe 缺失不阻塞大陆门禁；
- 全部递归危险标志仍为 false；
- production/staging、最终商家、eBay和主理人门禁不因本阶段自动通过。

### GREEN

- production release gate 合同升级为 `2026-07-27-production-release-gate-v2`。
- `_billing_section()` 读取 canonical 状态，不再把 Stripe rehearsal/provider register 当大陆真值。
- Stripe rehearsal/provider evidence 作为未来国际扩展附加信息保留，不计入大陆 section checks。
- external evidence 改为微信后端凭证存在、签名回调/查询/退款验证、生产环境和主理人批准所需的环境键名称。

## Phase 6：目标回归与完整门禁

先运行语法检查和目标测试：

```powershell
python -m py_compile jiejing_saas/billing_payment_options.py jiejing_saas/billing_plan.py jiejing_saas/readiness.py jiejing_saas/paid_launch_approval_packet.py jiejing_saas/owner_launch_control.py jiejing_saas/production_release_gate.py
python tools/test_jiejing_mainland_payment_strategy.py
python tools/test_jiejing_domestic_billing_production_completion.py
python tools/test_jiejing_paid_launch_approval_packet.py
python tools/test_jiejing_fixed_launch_progress.py
python tools/test_jiejing_owner_launch_control.py
python tools/test_jiejing_owner_launch_control_access.py
python tools/test_jiejing_owner_launch_control_ui.py
python tools/test_jiejing_frontend_settings_module_split.py
python tools/test_jiejing_production_release_gate.py
python tools/test_jiejing_external_launch_blocker_gate.py
python tools/test_jiejing_domestic_billing_api.py
python tools/test_jiejing_domestic_billing_orders.py
python tools/test_jiejing_domestic_billing_refund.py
python tools/test_jiejing_domestic_billing_operations.py
python tools/test_jiejing_domestic_billing_maintenance.py
python tools/test_jiejing_wechat_pay_callback.py
python tools/test_jiejing_wechat_pay_checkout_flow.py
python tools/test_jiejing_wechat_pay_refund_provider.py
python tools/test_jiejing_wechat_pay_recovery.py
node tools/codex_jiejing_owner_launch_control_smoke.js
node tools/codex_jiejing_paid_cutover_decision_smoke.js
```

然后运行：

```powershell
python tools/jiejing_secret_scan.py
node --check app.js
node --check ops.js
python tools/test_jiejing_staging_patch_apply_contract.py
python tools/jiejing_precloud_deployment_gate.py
```

完整门禁要求：

- checks=107；
- passed=107；
- failed=0；
- `ready_for_public_staging_code_handoff=true`；
- `ready_for_paid_commercial_launch=false`；
- `real_platform_writes_enabled=false`；
- `secret_exposed=false`。

## Phase 7：新部署包与发布身份门禁

完整门禁通过后：

1. 运行 `python tools/jiejing_prepare_public_staging_bundle.py --dry-run`；
2. 确认修改文件均在白名单；
3. 生成新包；
4. 独立计算 SHA256；
5. 核对 manifest、文件数量、唯一路径和 Secret 文件排除。

当前远端 `main` 不包含完整脏工作区基线，而 GitHub staging workflow 只从远端 `main` checkout，不消费本地 ZIP。因此本阶段完成后可以形成可信本地包，但不能直接执行 staging apply。

在部署前另行完成无损发布身份整理：逐文件确认当前线上基线和本地脏工作区，形成可复现的远端提交。禁止 `git add -A`。只有 GitHub deploy dry-run 通过并取得单独的 staging apply 批准后，才可部署。

## 完成定义

- 大陆支付有且只有一个 canonical 上线状态来源。
- 微信 Native 是大陆主提供者；Stripe 只作为未来国际支付信息。
- 所有大陆主步骤、blocker、owner报告和生产发布门禁不再由 Stripe rehearsal 驱动。
- 受控支付不自动开启公开收费，所有危险标志保持 false。
- 旧安全字段和内部路由兼容保留。
- 目标测试、Secret Scan 和 107/107 完整门禁通过。
- 新部署包、manifest 和 SHA256 独立验证通过。
- 在远端发布身份未无损整理前，不执行 staging apply。
