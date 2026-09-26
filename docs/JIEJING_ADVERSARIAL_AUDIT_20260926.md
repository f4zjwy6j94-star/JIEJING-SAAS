# 2026-09-26 捷境全局对抗式自检

## 结论与边界

用户睡前新增本轮全方面自检；不是重新开启迁移、重新注册或无限改版。检查基于已正式部署的 `2e1a0ce91ecf20c374b83006a01f7340694a6bca`，并保留原有未提交文档。

本轮确认 **5 类缺陷**，均已在本地修复并增加回归保护。**截至自检结束时尚未提交、尚未部署**；本报告随修复归档，之后的提交、门禁和发布状态以 `JIEJING_CURRENT_EXECUTION_STATE.md` 当前接续摘要及对应回执为准。不能把本地结果说成正式网站已包含这些修复。发布前仍需本批干净同源版本的完整门禁、预演、明确部署批准和上线验收。原版245/245只证明原版本，不是本批的发布凭证。

现有架构的主路径符合已确定方向：eBay-first AI CEO → 有来源的商品资料 → Listing → 素材审核 → 确认中心。无货源路径只给调研建议；不自动编造库存、图片权利或可售商品。文字模型、视觉服务与生图服务分工，套餐、AI额度、素材点分别管理。没有为了自检改变这些产品逻辑。

这不是“证明没有任何漏洞”：本轮是主要业务域的代码边界、异常路径与定向自动化审查，复用最近的真实商家页面验收。没有进行生产破坏测试、压力测试、全互联网渗透测试或新的真实交易。

## 确认并修复的问题

| 编号 / 严重度 | 确认证据和影响 | 修复与回归 |
| --- | --- | --- |
| A1 / P2 | 官网 `entrySaasApiBase()` 接受查询参数/本地保存的API地址；真实登录函数的合成测试证明可选择外部登录目标。**生产CSP `connect-src 'self'`另有防护，未发现凭据已外泄的证据**。该缺口可能被恶意链接用于破坏登录，且不应只依赖CSP兜底。 | 公网登录固定同源，地址覆盖仅保留给明确的本地开发主机。10个真实登录函数场景覆盖恶意查询、保存值、meta、相似域名、存储不可用和合法本地开发。 |
| A2 / P2 | 工作台有HttpOnly会话续期，官网入口没有；访问令牌到期即要求重新登录。临时错误的中文“登录状态”还会被宽泛匹配误当会话失效。 | 官网加入有界读取、与工作台相同的跨标签页锁、单次续期合并；仅401认定失效，503/网络失败/403保留重试机会。不读凭据、不自动重放业务写入、不在仅访问官网时自动登录。11个场景通过。 |
| A3 / P2 | `JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED=false` 时，未配置供应商或供应商未执行仍会进入内置备用搜索。合成网络拦截证明主开关关闭仍可能传输查询。 | 主开关在读取凭据/发请求前拦截，默认联网上下文也不能绕过开关复用旧搜索缓存。配置有/无、缓存已有结果的反例通过；测试没有访问真实搜索服务。 |
| A4 / P2 | 设置里的联网搜索状态由聊天/报告历史推断：新账号无历史被误报“待恢复”，历史成功也不能代表现在已配置或可用。能力自述还把备用开关当成独立于总开关。 | 现有登录后最小能力接口增加安全配置投影；UI与AI能力自述读取同一规则。区分已配置、基础搜索、暂停、未配置、未知；明确配置不是实时健康探测，不新增真实查询或泄露凭据元数据。8个后端组合、8个UI状态通过。 |
| A5 / P2 | 外部来源质量边界不足：无效IPv6链接会抛异常中断整理；伪造 `domain=ebay.com` 的外站链接可被排为官方；`notebayinc.com` 后缀误中官方；无效/无链接可按标题入选；遥远未来日期被判最新。全部用合成来源复现。 | 有效HTTP(S)链接才计入可引用来源，排除用户信息/控制字符/非法端口；域名由实际URL确定，官方后缀严格匹配；解析失败跳过而非崩溃；明显未来时间标为未知。异常来源、伪造域名、相似域名、可执行URL、缺链接、真实官方链接与未来时间回归通过。该规则提升来源归属可靠性，不声称已验证每个网页事实。 |

P2表示需要随下批发布修复；不能据此虚构已发生安全事件。本轮未复现P0/P1事故，但这不等于排除了全部潜在严重缺陷。

## 全局检查覆盖

| 范围 | 检查内容 / 结果 |
| --- | --- |
| 登录、注册、试用 | 本轮重新执行注册组件、向导持久化、会话回归；复用同一正式新账号的20/20次数、7天、不自动续费、空白工作台证据，不重建账号。新增A1/A2已修复。 |
| 账号与店铺隔离 | 后端HTTP、前端租户缓存、账号AI设置隔离专项通过；抽查报告/确认/草稿读取由服务端身份绑定公司，跨公司商店返回拒绝。未发现本轮用例中的串号。不是所有API的穷举证明。 |
| AI / 外部来源 | 模型账号边界、事实/文案生成边界、来源指令降权及质量专项通过；新增A3–A5。没有为验收消耗真实模型/搜索额度。 |
| 商品资料 / Listing | 草稿检查点HTTP保存、版本冲突、产品身份隔离及事实校验通过；复用正式原平板项目83字段刷新保留的验收，不覆盖旧资料或再造演练项目。 |
| 素材 | 概念图禁止冒充商品可发布素材的门禁通过；复用真实素材记录、来源/权利/事实审核和点数明细证据，不重复FAL生成。 |
| 支付 / 配额 / 退款 | 额度检查与退款专项通过。抽查退款必须绑定审批和平台操作员，原子领取执行权、已处理状态与回调幂等；篡改金额/重复回调不重复执行。未发生真实扣费或退款。 |
| eBay发布 | 发布确认专项通过；抽查执行载荷来自已批准快照而非浏览器覆盖；店铺、SKU、Offer、执行记录相互绑定。没有开启写入、OAuth、同步或真实发布。 |
| 网页安全 / 内部信息 | Cookie/SameSite/CSRF、BYOK目标地址、脱敏日志、商家文案与ops隔离专项通过；抽查来源链接、HTML模板转义及报告路径。新增A1；不是对所有HTML写入点的完整形式化证明。 |
| 发布 / 运维 | 发布白名单补入两份新增JS回归文件，发布合同和通道测试通过；未运行部署脚本。线上健康/readiness/ops只读刷新见下。 |
| 维护性 | `app.js`、API路由和CSS体积较大，后续应沿稳定边界逐步拆分；本轮不做大重构，以免改变已验证业务。用户后置的视觉换肤仍后置。 |

## 本轮验证

本地 **23个不同专项全部通过**（重跑不重复计数）：

- `test_jiejing_saas_backend_mvp.py`
- `test_jiejing_saas_ai_ceo_chat_model_boundary.py`
- `test_jiejing_ai_ceo_source_quality.py`
- `test_jiejing_listing_grounding_security.py`
- `test_jiejing_listing_draft_checkpoint_api.py`
- `test_jiejing_publish_confirmation_intake.py`
- `test_jiejing_media_placeholder_review_gate.py`
- `test_jiejing_domestic_billing_refund.py`
- `test_jiejing_billing_quota_guardrail.py`
- `test_jiejing_saas_p0_security_guardrails.py`
- `test_jiejing_global_security_hardening.py`
- `test_jiejing_frontend_tenant_cache_scope.py`
- `test_jiejing_ai_settings_tenant_scope.py`
- `test_jiejing_merchant_onboarding_state.py`
- `test_jiejing_merchant_onboarding_frontend.py`
- `test_jiejing_merchant_ai_media_capabilities.py`
- `test_jiejing_ai_ceo_builtin_web_search.py`
- `test_jiejing_registration_challenge_ui.py`
- `test_jiejing_frontend_rotating_browser_sessions.py`
- `test_jiejing_staging_patch_apply_contract.py`
- `test_jiejing_production_deploy_channel.py`
- `test_jiejing_saas_clean_settings_and_listing_ui.py`
- `test_jiejing_frontend_staging_config.py`

另有secret scan、JS语法及diff空白检查通过。测试日志位于 ignored `output/jiejing-adversarial-audit-20260926/`。曾误输入不带`saas_`的文案测试文件名（文件不存在、exit2）；已改为真实现有测试并通过，不把失败伪装成执行成功。发布前静态缓存合同检测出本地改动需更新脚本指纹，已同步官网预取/预加载与工作台脚本版本为`195796d0074d`并通过，避免下一次部署后浏览器继续使用旧脚本。

浏览器本地验收：实际官网源码 + 合成后端，从仅打开首页（未自动跳转）→点击工作台→GET向导401→GET身份401→一次POST续期→GET向导成功→免费路径跳转；终点页明确为合成占位，不冒充正式账号验收。搜索卡使用实际状态函数、模板和工作台样式核对已配置/暂停/未知及展开说明，无console错误/告警。不是整站新版视觉验收。临时页面与回环服务已关闭，正式账号工作台保留。

### 发布门禁补充（09-26）

首次cab7f82完整门禁在已输出50项时发现两项失败，已主动停止（session55047退出1），没有可发布的成功报告。定向复现证实是两处旧fixture假设冲突：官网过期会话用例没有模拟新加入的`/me`与`/auth/refresh`，网络失败应保留会话而非判过期；货源HTTP fixture关闭搜索总开关却同时要求出现其注入的合成来源。仅修正测试夹具：明确模拟401续期拒绝并断言准确GET/GET/POST链路；合成搜索测试开启总开关、保留fake来源并拒绝任何外部URL请求。产品逻辑和旧断言不放宽，关闭搜索不调用及11种会话情形仍保留。最终发布必须绑定包含这些夹具修正的新commit重新完整验证，不把已停止的门禁算通过。

## 当前线上状态（只读）

北京时间2026-09-26约01:53–01:58（UTC 09-25 17:53–17:58）：

- `/health` HTTP200、status=ok；`/health/deep` HTTP200、operational_health.status=ready。
- readiness：`production_ready=true`、`beta_ready=true`、`can_accept_real_customers=true`、`provider_status.billing.public_charging_allowed=true`，blocker/warning均0。
- `real_platform_writes_enabled=false`；不把收费可用当成eBay写入可用。
- ops域HTTP200；主站`/ops.html` HTTP404，隔离保持。
- 退款能力复用本次前序正式发布的独立只读9/9证据；本轮没有再次调用真实退款或声称重新完成实款验证。

证据：`readiness-safe.json`、`online-fields-safe.json`的深度健康字段、`online-safe.json`的HTTP状态。最初采样错误地按响应顶层读取嵌套字段；相应null和数组计数不可用于判定故障，已依真实接口结构重取。最终以`readiness-safe.json`为准，不把解析错误当线上回退。

## 仍须明确保留的限制与下一步

1. **本批修复待发布**：已有本地回归，不宣称已上线；按本批干净同源版本完成完整门禁→预演→获明确部署批准→受控发布→现场验证。没有重新配置密钥、收费开关或eBay权限的必要。
2. **真实eBay商业闭环未完成**：仍需真实可售商品、合法素材/事实和可用卖家账号，以及动作时确认。用户账号当前条件不足，不能用代码测试替代真实成功发布。
3. 买家消息自动接入/自动发送、素材点加购尚未开放；已在产品页面说明。不要宣传为全自动客服或全自动卖货。
4. 本轮自检到此收口，不拿持续“还能优化”替代交付。后续先发布确证缺陷修复，再由用户查看正式网站；UI另批评审，不重开整套产品设计。
