# 捷境权限与可靠性专项审计（2026-09-05）

本报告记录本轮有界检查，不是“零漏洞”或完整商家闭环证明。当前执行与部署结果统一见 `JIEJING_CURRENT_EXECUTION_STATE.md`。

## 范围与结论

检查了认证、代表性租户查询、前端不可信输出、SaaS 退款、确认单与队列权限、套餐席位、Listing 事实与失败用量边界，以及当前生产运行状态。没有运行真实收费、退款、eBay 写入，也没有重复 OAuth。

网站健康和收费能力合同为真，但代码审计仍发现应修复的权限问题。因此不能用健康接口绿色或测试总数宣称成熟度达到某个百分比。

## 已确认的问题与修复要求

| 编号 | 影响 | 证据入口 | 修复与回归边界 |
| --- | --- | --- | --- |
| S1 | 商家能审批并执行自己的平台订阅退款 | `api_server.py` 原 `billing/domestic/orders/*/refund-execute`、`confirmations/*/decision`；`billing_domestic.py:execute_approved_domestic_billing_refund` | 商家仅申请/查询；内部 ops 审核，绑定订单、公司、金额、理由及当前审核身份；执行前精确金额确认；拒绝旧自批证据与跨公司错配。 |
| S2 | 只读成员可以改变部分确认单和任务状态 | `api_server.py` 的 workers、queue-jobs、confirmation decision 路由 | 所有变更动作校验岗位权限；高风险商家业务仍走原确认边界，不把 eBay 审批误封成平台内部专用。 |
| S3 | 团队邀请未限制套餐席位 | `repository.py` 团队邀请与 `_team_seat_quota_in_transaction` | 成员和待邀请共同占席；相同邮箱幂等；最后一席事务串行化；待邀请转成员重新校验；客户端不能自定限额或用重邀更改角色。 |
| S4 | 共享订阅判定漏认真实微信套餐及有效期 | `billing_plan.py:_entitlement_active` | 支持受信任的真实微信订阅；检查状态与到期时间；过期标记未刷新也不能继续授予付费权益。测试不能只用 mock 支付提供方。 |
| S5 | 退款授权修复会影响查询恢复；原退款发送存在在途状态竞态 | `billing_domestic.py` execute/query、`repository.py` 内部审核 | 查询沿用有效内部审批上下文；发送前原子认领；在途不能撤销成“已拒绝”，并发不能重复发送；不确定结果走查询，不自动重发资金动作。 |
| S6 | 新退款审核时间比较不兼容 PostgreSQL 原生日期对象 | `billing_domestic.py:_approved_domestic_refund_confirmation`、`repository.py:claim_platform_refund_execution` | 审核与确认时间按明确时区解析为同一 UTC 时刻；拒绝无效、无时区或被改动的时间；订单和审计 JSON 只保存标准 ISO 字符串。 |

S1 首次使用本地假商家、假订单与假 provider 复现：未具备平台内部身份的商家能够申请、自批并到达退款 provider。真实外部调用为零。

S5 独立复核使用临时库与阻塞假 provider 复现：两个并发执行可到达 provider 两次；请求在途时另一运营审核拒绝成功，之后订单却成为退款处理中。微信固定退款请求号具备 provider 层幂等，因此没有把该证据表述为“双倍真实退款”。

S4 使用临时库复现：有效 `wechat_pay_native` 付费订阅被新席位入口当作免费；另一已到期订阅在 active 标记尚未清理时仍可增加成员。修复必须覆盖共享判定，不仅修改界面文案。

S6 在部署前代码复核发现：SQLite 返回时间字符串，生产 PostgreSQL 驱动返回原生 datetime，直接比较会拒绝合法审核。旧候选已停止门禁且未部署。新增回归在数据库游标边界注入原生日期对象，覆盖等价时区、时间篡改、无效/无时区时间及认领证据 JSON 序列化；它不是一次真实生产退款。

## 代表性保护已验证

- 认证会话校验、撤销、生产 HttpOnly Cookie 与跨域写入来源限制。
- 聊天、素材、数据包和确认单的代表性查询带公司作用域；聊天进一步限制用户；前端缓存按租户隔离。
- 前端同源 HTTPS API 限制、Markdown/来源输出转义与危险链接协议拦截；本地 Chromium 恶意输入测试通过。
- 无已确认的新 P0 或跨租户泄漏，但本轮没有逐一覆盖所有 HTTP 路由、部署网络边缘或依赖链。

## 续接规则的旧状态固化

完整门禁还发现旧 AGENTS 测试强制要求写入“旧 eBay 账号被冻结”和 `ready_for_paid_commercial_launch=false`。这会把历史快照固化成后续执行规则，与用户要求按当前证据接续冲突。本轮没有为了通过测试恢复这些旧结论，而是要求测试验证当前执行索引、实时核对账号/收费状态，以及不同类型证据不得互相冒充；同时阻止这两条固定历史状态重新进入 AGENTS。

## 验证入口和证据限度

新增核心回归：`tools/test_jiejing_refund_operator_authorization.py`、`tools/test_jiejing_team_seat_quota.py`。既有支付/素材点退款、会话、租户缓存、Listing、额度、迁移和部署合同继续参加候选版本门禁。

SQLite 并发测试和 PostgreSQL 锁/迁移合同是不同证据。本轮未在真实托管 PostgreSQL 上运行并发压力测试。自动化本地浏览器合同也不等于已登录生产商家的完整 UI 操作。

quota、seat、fact checkpoint 的新增路径另经独立原生行契约回放，日期、JSONB 与整数类型四项通过，未发现同类确定失败；这不等于真实 PostgreSQL SQL 与并发执行通过。

本轮 Chrome 控制连接不可用，未重新登录、重装或用旧截图伪造当前视觉审查。平板支架项目仍从已有报告/资料/Listing 步骤续接；没有真实发布完成证明。部署是否完成、完整门禁结果及下一步以当前执行索引为准。
