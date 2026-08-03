# 捷境免费邀请内测与正式收费 readiness 分离实施计划

日期：2026-08-03

批准设计：`docs/superpowers/specs/2026-08-03-private-beta-paid-launch-readiness-separation-design.md`

## 目标与边界

本计划只修正产品 readiness 对计费状态的分类：当免费邀请内测合同已严格成立、canonical 大陆支付状态有效且公开扣款仍关闭时，只属于正式收费上线的剩余缺口应记为 warning，不再错误阻塞 `beta_ready`。

本次不启用微信支付 Live API，不创建、查询、关闭或退款任何真实订单，不改变 eBay OAuth、Token 或平台写入状态，不调整固定商业化进度权重，也不允许前端授予套餐权益或额度。`production_ready`、`can_accept_real_customers`、`public_charging_allowed`、`charge_now_allowed`、`triggers_real_charge` 与 `triggers_real_refund` 必须继续为 false。

## Phase 0：现有契约与复用来源

### 允许复用的实现

- `jiejing_saas/readiness.py:56`：`build_product_readiness(settings, repository)` 是公开产品 readiness 汇总入口；保留现有 `beta_ready` 和 `production_ready` 计算公式。
- `jiejing_saas/readiness.py:320`：`_billing_item(settings, repository)` 是唯一需要改变分类的实现点。
- `jiejing_saas/readiness.py:1497`：`_validated_public_mainland_payment(mainland)` 复用共享 canonical validator，不新增第二套支付真实性判断。
- `jiejing_saas/billing_payment_options.py:187`：`validate_mainland_payment_launch_for_public(value)` 已验证合同版本、提供商、配置计数、能力布尔值、受控验收结构及全部负向安全字段；非法、缺失或矛盾输入统一返回 `merchant_payment_status_unavailable`。
- `jiejing_saas/billing_plan.py:116`：`build_billing_plan(settings, repository)` 已提供严格布尔字段 `billing_ready_for_private_beta`。
- `tools/test_jiejing_phase2_response_boundary_hardening.py:23`：已有 canonical 大陆支付 fixture 和矛盾状态 fail-closed 模式。
- `tools/test_jiejing_billing_test_provider.py:149`：已有无扣款私测计费、商家路径、额度后端确认和公共响应负向安全断言。

### 禁止模式

- 禁止直接令 staging 的 billing item 一律 warning；必须同时满足严格私测合同和 canonical paid-launch-only blocker 白名单。
- 禁止用 `bool(value)` 接受字符串、数字或缺失字段；只有 `is True` 可以放行私测合同。
- 禁止把 `merchant_payment_status_unavailable`、配置不完整或后端安全能力不完整降级为 warning。
- 禁止修改 `build_product_readiness()` 的总分公式或为 `beta_ready` 增加绕过分支。
- 禁止在测试中读取真实支付凭证、调用支付网络、创建订单或改变线上环境。

## Phase 1：RED——固定正确分类

### 文件

- 修改 `tools/test_jiejing_phase2_response_boundary_hardening.py`。

### 失败测试

使用已有 canonical fixture 构造并验证以下场景：

1. `billing_ready_for_private_beta is True`，合同 9/9 且安全能力完整，但 `provider_checkout_ready=False`，validator 返回 `merchant_payment_provider_connection_not_ready`；billing item 必须是 warning。
2. 同一场景在没有其他 blocker、用户数与店铺数均满足时，通过公开 `build_product_readiness()` 得到 `beta_ready=true`。
3. 同一结果的 `production_ready=false`、`can_accept_real_customers=false`，公共 billing 的扣款、退款、前端发权益和平台写入字段全部保持 false。
4. canonical 合同损坏或安全字段矛盾时，billing item 必须是 blocker，公开 `beta_ready=false`。
5. `billing_ready_for_private_beta` 为 false、字符串或缺失时不得放行。

先运行并确认测试因当前 billing item 仍返回 blocker 而失败：

```powershell
python tools/test_jiejing_phase2_response_boundary_hardening.py
```

测试只 mock 与本议题无关的 readiness item；被测路径必须经过公开 `build_product_readiness()` 和真实 canonical validator。

## Phase 2：GREEN——最小实现

### 文件

- 修改 `jiejing_saas/readiness.py`。

### 实现

在 billing item 附近定义明确的 paid-launch-only blocker 集合：

- `merchant_payment_provider_connection_not_ready`
- `merchant_payment_production_environment_required`
- `merchant_payment_refund_not_ready`
- `merchant_payment_controlled_acceptance_not_proven`
- `merchant_payment_public_cutover_not_approved`

仅当以下条件全部成立时返回 warning：

1. `plan.get("billing_ready_for_private_beta") is True`；
2. canonical validator 没有返回 `merchant_payment_status_unavailable`；
3. `next_paid_launch_blocker` 精确属于上述白名单。

配置不完整、后端安全能力不完整、未知 blocker、状态不可用或合同矛盾继续使用 blocker。owner-ready 分支继续是 warning，但仍只表示进入独立商业发布审批，不代表公开收费获准。

实现不得触碰支付执行、退款执行、额度发放、公开收费开关或总 readiness 公式。

## Phase 3：REFACTOR 与安全回归

保持分类判断集中、命名表达 paid-launch-only 语义，不复制 validator 的字段级检查。运行：

```powershell
python -m py_compile jiejing_saas/readiness.py tools/test_jiejing_phase2_response_boundary_hardening.py
python tools/test_jiejing_phase2_response_boundary_hardening.py
python tools/test_jiejing_billing_test_provider.py
python tools/test_jiejing_billing_quota_guardrail.py
python tools/test_jiejing_mainland_payment_strategy.py
python tools/test_jiejing_saas_backend_mvp.py
python tools/test_jiejing_saas_p0_security_guardrails.py
python tools/test_jiejing_fixed_launch_progress.py
python tools/test_jiejing_production_release_gate.py
```

验收时特别确认：

- malformed/contradictory canonical payment 仍 fail closed；
- 私测 warning 不能令 `production_ready=true`；
- `can_accept_real_customers=false`；
- 所有真实扣款、退款、公开收费、前端发额度和 eBay 写入字段保持 false；
- 测试输出不包含 Secret、Token、证书或支付凭证。

## Phase 4：完整门禁与部署准备

按仓库要求运行：

```powershell
python tools/jiejing_secret_scan.py
node --check app.js
python tools/test_jiejing_staging_patch_apply_contract.py
python tools/jiejing_precloud_deployment_gate.py
```

完整门禁必须保持全部通过、`ready_for_paid_commercial_launch=false`、`real_platform_writes_enabled=false` 与 `secret_exposed=false`。随后生成或核对新的 staging bundle、manifest 与 SHA256。

部署严格分两步：先执行 GitHub Actions staging dry-run；只有 dry-run 成功且取得针对本提交的单独 apply 批准后，才可部署到 `app.jiejing.shop`。部署后只进行浏览器风格 User-Agent 的只读 `/health`、`/health/deep`、`/readiness/product-saas` 验证，不创建真实支付订单或触发 eBay 写入。

## 完成定义

- public readiness 对免费邀请内测和正式收费上线给出不同但一致的结论。
- 当前合法 provider-connection 缺口不再成为 beta blocker。
- 任意支付合同损坏、安全字段矛盾、配置或后端安全能力不完整仍阻塞 beta。
- `beta_ready` 只在其他既有 blocker 全部消失且用户/店铺条件满足时为 true。
- 正式收费、真实客户接入、退款、eBay 写入和主理人最终批准状态没有被本改动打开。
- 目标回归、安全检查、完整 precloud gate 和 staging dry-run 全部通过；apply 前保留独立批准门槛。
