# 捷境免费内测与正式收费 readiness 分离设计

## 1. 背景

捷境当前线上事实同时满足：

- `billing_ready_for_private_beta=true`
- `public_charging_allowed=false`
- `production_ready=false`
- `can_accept_real_customers=false`
- 微信支付正式连接仍有未完成门禁

但产品 readiness 把正式支付连接缺口记为 blocker，并让 `beta_ready=false`。这会把“免费邀请内测是否可用”和“能否向公众正式收费”错误合并成同一个结论。

本设计只纠正 readiness 语义，不打开支付、不降低正式上线标准，也不改变任何 eBay 状态。

## 2. 目标

- 当免费邀请内测所需的计费、套餐和额度边界已经满足时，正式支付尚未完成只作为 paid-launch warning，不阻塞 `beta_ready`。
- 正式收费相关缺口继续阻止 `production_ready` 和 `can_accept_real_customers`。
- 所有公开支付安全字段继续保持 false，包括 `public_charging_allowed`、`charge_now_allowed`、`triggers_real_charge` 和 `triggers_real_refund`。
- 支付状态缺失、合同损坏或安全字段矛盾时继续 fail closed，并阻塞 beta readiness。

## 3. 非目标

- 不设置或修改微信支付 Live API、扣款、退款或 owner paid-launch approval 开关。
- 不创建、查询、退款或重放任何真实支付订单。
- 不把 staging 改成 production。
- 不改变 eBay OAuth、Token、政策快照或真实写入状态。
- 不调整固定进度权重，不把 beta readiness 当作正式商业化进度。

## 4. 方案比较

### 方案 A：在 billing readiness item 中区分 private beta 与 paid launch（采用）

读取现有 `billing_ready_for_private_beta` 合同。当该合同明确为 true、支付状态合同有效且公开收费保持关闭时，正式支付未完成项使用 warning；支付合同不可用或安全边界异常仍使用 blocker。

优点：语义直接、输出自洽、改动集中；`production_ready` 仍会被 warning 阻止。缺点：需要为状态分类补充回归测试。

### 方案 B：打开支付运行开关以满足现有 blocker（拒绝）

这会把 readiness 数字与真实收费能力混在一起，并可能扩大外部支付 API 行为，不符合无扣款内测目标。

### 方案 C：保持 `beta_ready=false`（拒绝）

安全但不准确，会让已经可运行的免费邀请内测被 paid-launch 条件连坐，削弱运营判断价值。

## 5. 状态分类

### 5.1 免费内测可用、正式收费未完成

同时满足以下条件时，billing item 为 warning：

- `billing_ready_for_private_beta is True`
- canonical payment contract 可验证
- `public_charging_allowed is False`
- `charge_now_allowed is False`
- `triggers_real_charge is False`
- 当前缺口只属于正式 provider 连接、生产环境、退款控制、受控支付证明或公开 cutover

此时允许：

- `beta_ready=true`，前提是没有其他 blocker 且账号、店铺等现有 beta 条件满足

此时仍必须：

- `production_ready=false`
- `can_accept_real_customers=false`
- `public_charging_allowed=false`

### 5.2 支付状态不可用或安全合同损坏

以下情况继续使用 blocker：

- canonical payment status 不可用或格式不合法
- 安全布尔值缺失、类型错误或出现允许扣款/退款的矛盾状态
- private-beta 计费合同未明确为 true

系统不得通过字符串或数字真值强制转换来放行。

### 5.3 正式收费满足技术证据但等待主理人批准

即使支付连接、回调、退款、对账和受控验收均完成，也只允许进入 owner review。公开收费必须继续由独立商业发布批准控制，不能由本次改动自动开启。

## 6. 实现边界

主要修改点为 `jiejing_saas/readiness.py` 的 billing item 分类。实现应复用现有 canonical payment validator 和 `billing_ready_for_private_beta`，不新增第二套支付状态判断，不改变支付执行代码。

`beta_ready` 的总体计算方式保持不变：仍由所有 blocker、用户数和店铺数共同决定。通过正确分类 billing item 消除错误 blocker，而不是为 beta readiness 增加特殊绕过。

## 7. 测试设计

按 TDD 逐个完成以下行为：

1. 免费邀请内测合同为 true、正式 provider 连接未完成时，billing item 为 warning，不再是 blocker。
2. 在没有其他 blocker 且账号、店铺条件满足时，`beta_ready=true`。
3. 同一场景下 `production_ready=false`、`can_accept_real_customers=false`、`public_charging_allowed=false`。
4. canonical payment status 缺失或损坏时，billing item 继续为 blocker，`beta_ready=false`。
5. private-beta 计费合同不是严格布尔 true 时，不得放行。

测试优先走 `build_product_readiness` 公共产品接口，只在构造外部 provider 状态时使用边界 mock，不测试私有实现细节。

## 8. 安全审查

- 不读取、记录或返回微信支付凭证。
- 不改变后端密钥边界。
- 不调用外部支付 API。
- 不允许前端发放套餐权益或额度。
- 不改变确认中心和退款审批边界。
- malformed 或矛盾状态继续 fail closed。
- 线上验证只读取 health/readiness，不创建真实订单。

## 9. 验收标准

- 新增回归测试先失败，再由最小实现修复通过。
- 支付、readiness、安全和固定进度相关测试全部通过。
- 完整 precloud gate 通过且无 secret 泄露。
- 线上部署前先执行 GitHub Actions staging dry-run。
- staging apply 仍需要项目部署规则要求的单独批准。
- 部署后 `/health` 与 `/health/deep` 为 200，`beta_ready` 只在没有其他 blocker 时恢复，`production_ready`、`can_accept_real_customers` 和 `public_charging_allowed` 继续为 false。

## 10. 回滚

代码回滚只撤销本次 billing item 分类和对应测试，不触碰数据库、私有环境文件、支付证据、eBay 凭证或运行数据。若线上 readiness 出现任何安全字段异常，立即停止 apply 并保持公开收费关闭。
