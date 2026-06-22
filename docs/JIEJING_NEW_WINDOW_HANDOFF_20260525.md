# 捷境新窗口迁移文件 2026-05-25

生成时间：2026-05-25 21:45 Asia/Shanghai  
项目目录：`C:\Users\57249\Documents\Codex\2026-04-29\hermes-agents\software-demo`  
当前 staging：`https://individually-buffalo-prescribed-blocking.trycloudflare.com`  
当前原则：不要用旧状态；不要重复 eBay OAuth；不要要求用户重复配置模型 key；不要暴露密码、token、eBay refresh token、模型 key。

## 1. 产品方向铁规则

捷境是 eBay-first AI CEO SaaS，不是通用 ERP，不是通用 Agent 市场。

核心闭环：

商家给 AI CEO 下文字指令 -> 后端 agents 分配任务 -> 市场调研/批量选品/IP 防侵权 -> Listing 资料 -> 素材工坊 -> 客服学习 -> 财务履约与费用统计 -> 决策中心确认 -> 执行 -> 报告/来源/记忆/审计回流 AI CEO。

真实发布、采购付款、改价、库存、退款、广告、政策、敏感客服承诺必须进入决策中心。真实写入可以开启，但不能绕过确认中心。

## 2. 本轮已验证的当前状态

### Public staging

已执行：

- `Invoke-RestMethod https://individually-buffalo-prescribed-blocking.trycloudflare.com/health`
- `Invoke-RestMethod https://individually-buffalo-prescribed-blocking.trycloudflare.com/readiness/product-saas`
- `curl.exe -I -L --max-time 30 https://individually-buffalo-prescribed-blocking.trycloudflare.com/app.html?...`

结果：

- `/health` 返回 `status=ok`
- `environment=staging`
- `database_startup_status=ready`
- `real_platform_writes_enabled=true`
- `requested_real_platform_writes=true`
- `secret_exposed=false`
- `Cache-Control: no-store`
- `/readiness/product-saas` 返回 `beta_ready=true`
- `production_ready=false`
- `can_accept_real_customers=false`
- `blocker_count=0`
- `warning_count=2`
- 最新 public readiness packet：`packet_2fc16b08e7bb4955`
- packet 来源：`official_api`
- packet 状态：`packet_cached_sanitized`
- packet 资源：6/6，缺口 0
- reports：139
- confirmations：106
- secret_refs：15
- model_secret_refs：5

注意：readiness 同时显示 `provider_status.model.configured=true`，但 `provider_status.model.model=""`；`provider_status.model_value.model_configured=false`。这和用户截图里的“模型验证失败”高度相关，下个窗口必须优先查这个状态映射，不要直接让用户重填 key。

### 本地检查

已执行并通过：

- `python -m py_compile jiejing_saas\ai_ceo_chat.py jiejing_saas\api_server.py`
- `node --check app.js`
- `python tools\test_jiejing_saas_ai_ceo_chat_model_boundary.py`
- `python tools\test_jiejing_saas_ai_ceo_latest_reply_ui.py`
- `python tools\test_jiejing_saas_clean_settings_and_listing_ui.py`
- `python tools\test_jiejing_session_restore_and_ebay_ops_ui.py`
- `python tools\test_jiejing_media_nav_and_state_restore.py`
- `python tools\test_jiejing_merchant_surface_guard.py`
- `python tools\test_jiejing_model_value_rehearsal.py`

浏览器 smoke：

- `node tools\codex_jiejing_all_modules_clean_smoke.js`
- 本轮结果 `ok=false`，唯一失败是图片请求 `assets/backflow-incense-burner-hero.webp net::ERR_ABORTED`
- DOM 检查实际通过：7 个左侧模块存在；登录弹窗未出现；AI CEO 最新回复在输入框上方；Listing 简洁页存在；素材工坊 tabs 存在；设置页 7 个 tab 存在。
- 处理建议：下个窗口先不要因为这个 smoke 失败大改 UI，先把图片 abort 作为测试脚本容错或静态资源问题单独处理。

### SSH/远端日志

本轮用已知 `agentuser@42.194.158.47` 连接远端查日志，两次超时。public health/readiness 正常，所以不要先判定服务挂了。下个窗口需要继续用 agentuser 通道重试，不要先走 root 或腾讯云 QR。

已知稳定 SSH 参数：

`-o KexAlgorithms=ecdh-sha2-nistp256 -o Ciphers=aes128-ctr -o MACs=hmac-sha2-256 -o IPQoS=none`

## 3. 用户要求完成情况

### 已完成或基本完成

- 读取并遵守 2026-05-20 四个状态文档：已完成，后续不能用更旧状态覆盖当前 readiness。
- 不重复 eBay OAuth：当前没有重复打开 OAuth。
- 不要求重复配置模型 key：当前只检查状态，未要求用户重新填。
- 左侧模块重构为 7 个：AI CEO、Listing、批量铺货、素材工坊、决策中心、客服与订单、设置。浏览器 smoke 显示 `navCount=7`。
- 素材工坊空白：已恢复，smoke 显示 `has_media_tabs=true`，保留“流程导入”和“外部独立生成”两条线。
- 批量铺货空白：已恢复为批量前质检/机会/货源/字段/IP/确认边界，不再用旧演示商品冒充真实数据。
- 设置页单独归类：已做 clean settings shell，7 个 tab：常规、账号、数据、模型、工作流、权限、上线。
- Listing 页面简化：已改为市场报告、刊登资料、eBay 同步商品；授权、模型、packet、权限配置移入设置。
- AI CEO 对话布局：已改成 ChatGPT-like 干净入口；最新回复显示在输入框上方；历史对话折叠到下方；请求带 `cache: no-store` 和 fresh 参数。
- 官网工作流方向：`index.html` 已同步 AI CEO 指令 -> 调研/批量/IP -> Listing/素材 -> 客服/财务 -> 决策中心/复盘，并已加入批量选品和 IP 防侵权。
- 意见箱：已加入 workflow feedback 相关入口和样式，不作为第 8 个左侧模块。
- 真实写入开关：当前 staging 显示开启，但仍在确认中心边界后。

### 未完成，必须继续

1. 模型验证失败必须查清真实原因。

用户截图 toast：`live 模型证明失败：请检查 API key、模型名和 provider 余额。`

当前初步判断：

- 不是前端纯文案问题。
- public readiness 显示 BYOK secret_ref 存在，但 `provider_status.model_value.model_configured=false`。
- `jiejing_saas\model_value_rehearsal.py` 仍先取 `model_client_status_from_env()`，如果没有注入 BYOK model_client 或注入链路失败，会被判定为 model provider 不可用。
- `app.js` catch 里只显示泛化 toast，没有把后端真实 `blocked_by` 或错误类型翻译成商家能懂的中文。

下个窗口继续做：

- 用远端日志确认 `/stores/{store_id}/model/value-rehearsal` 最近失败原因。
- 检查 `api_server.py` 中 BYOK `model_secret_ref` 解析是否正确注入到 `run_model_value_rehearsal(...)`。
- 统一 `model_value_gate`、`model_value_rehearsal`、`readiness.provider_status.model_value` 对 merchant BYOK 的判断。
- 前端 toast 改成中文精确原因，例如：模型 key 不可用、模型名不被 provider 接受、provider 返回余额/额度不足、网络超时、后端未拿到当前店铺 secret_ref。
- 不要让用户重填 key，除非后端明确返回 key 已失效或 provider 拒绝认证。

2. Listing 报告英文必须修。

用户截图中 Market Report 和 Listing Package 是英文。这个不符合中文商家 SaaS。

下个窗口继续做：

- 在模型 prompt 层硬约束输出中文，位置优先查：
  - `jiejing_saas\model_value_rehearsal.py`
  - `jiejing_runtime\workflow_templates.py`
  - `jiejing_runtime\adapters.py`
- 报告保存前增加中文质量检查：标题、摘要、下一步、风险说明都必须中文；英文专有名词如 eBay、SKU、Listing、Market Report 可保留。
- 前端渲染层不要硬翻译技术 ID，但商家可见标题/摘要必须中文。
- 加回归测试：生成的 `market.report` 和 `listing.package` 不应以长英文段落为主。

3. AI CEO 对话还要继续优化速度和真实感。

已完成：最新回复在输入框上方、历史折叠、no-store。

还未完成：

- 需要流式/更快的 loading 状态，不要让用户误以为没连模型。
- 当前 temp smoke 账号没有 BYOK，所以显示 `blocked_before_model_chat` 是合理的测试账号状态，不代表用户账号一定没连。
- 真实用户账号必须再跑一次浏览器级验证：发一条新指令，看返回是否来自后端 BYOK，并显示 provider/model 元信息。

4. 官网不自动弹登录需要再回归。

代码和页面文案已朝“点击店家入口才登录”改过，但本轮没有完整浏览器复验首页入口。下个窗口先开 staging 首页确认：

- 打开 `/index.html` 不应自动弹登录。
- 点击“登录/进入工作台/商家入口”才弹登录。
- 顶部 `AI CEO 工作台` 不能跳旧模拟 login 参数，应该进入正式官网介绍锚点或受控登录入口。

5. 设置页还需要继续打磨。

已归类，但用户要求像 Codex 设置一样干净。下个窗口继续：

- 去掉主模块顶部重复账号卡。
- 设置页保持左侧 tab、右侧内容，减少大标题和密集卡片。
- 把 eBay 授权、BYOK、packet、billing、权限、上线门禁放设置，不在 Listing/素材/批量页重复堆状态。

## 4. 当前重要文件

核心前端：

- `app.js`
- `styles.css`
- `index.html`
- `app.html`

后端：

- `jiejing_saas\api_server.py`
- `jiejing_saas\ai_ceo_chat.py`
- `jiejing_saas\model_value_rehearsal.py`
- `jiejing_saas\model_value_gate.py`
- `jiejing_saas\readiness.py`
- `jiejing_saas\repository.py`

运行时/agent：

- `jiejing_runtime\adapters.py`
- `jiejing_runtime\workflow_templates.py`
- `jiejing_runtime\model_clients.py`

测试：

- `tools\test_jiejing_saas_ai_ceo_chat_model_boundary.py`
- `tools\test_jiejing_saas_ai_ceo_latest_reply_ui.py`
- `tools\test_jiejing_saas_clean_settings_and_listing_ui.py`
- `tools\test_jiejing_session_restore_and_ebay_ops_ui.py`
- `tools\test_jiejing_media_nav_and_state_restore.py`
- `tools\test_jiejing_merchant_surface_guard.py`
- `tools\test_jiejing_model_value_rehearsal.py`
- `tools\codex_jiejing_all_modules_clean_smoke.js`
- `tools\codex_real_jiejing_flow_smoke.js`

最新 bundle：

- `output\jiejing-public-staging-bundle\jiejing-public-staging-20260525-105852.zip`
- manifest：`output\jiejing-public-staging-bundle\jiejing-public-staging-20260525-105852.manifest.json`

## 5. 下个窗口第一优先级执行顺序

严格按这个顺序，不要跳：

1. 重新校准当前状态。
   - 读本文件。
   - 读 2026-05-20 四个状态文档。
   - 查 `/health` 和 `/readiness/product-saas`。
   - 不重复 OAuth，不要求用户重配模型 key。

2. 修模型验证失败。
   - 先查远端日志和接口返回。
   - 统一 BYOK 注入、model value gate、readiness 映射。
   - 前端显示精确中文原因。
   - 用真实用户账号做一次 AI CEO chat 和 model value rehearsal 验证。

3. 修 Listing 报告英文。
   - prompt 层强制中文。
   - 保存前中文质量检查。
   - 前端报告卡中文展示。
   - 加回归测试。

4. 复验 UI 主链路。
   - 首页不自动登录。
   - AI CEO 对话最新回复在输入框上方，不需要向下翻。
   - Listing 只显示市场报告/刊登资料/eBay 同步商品。
   - 批量铺货显示批量前质检。
   - 素材工坊显示流程导入/外部独立生成。
   - 决策中心只处理高风险确认。
   - 客服与订单只显示真实订单/商品档案/客服边界。
   - 设置页集中管理账号、授权、BYOK、packet、权限、上线。

5. 通过测试后再部署。
   - `python -m py_compile jiejing_saas\ai_ceo_chat.py jiejing_saas\api_server.py`
   - `node --check app.js`
   - 相关 Python 测试
   - Playwright smoke
   - 再打 bundle、部署 staging、复验 public health/readiness。

## 6. 禁止事项

- 禁止把 token、refresh token、模型 key、密码写入文件或回复。
- 禁止用旧模拟商品填真实工作台。
- 禁止因为模型验证失败就让用户重新配置 key；必须先查后端 secret_ref 和 provider 返回。
- 禁止重复 eBay OAuth。
- 禁止把真实发布、付款、退款、广告、改价、库存、政策、敏感客服承诺绕过决策中心。
- 禁止把捷境改成通用 ERP、通用 Agent 市场或只会聊天的工具。

## 7. 给下个窗口的简短开场提示

继续捷境项目，先读：

`docs\JIEJING_NEW_WINDOW_HANDOFF_20260525.md`

然后读取 2026-05-20 四个状态文档，不要用旧状态，不要重复 eBay OAuth，不要要求我重复配置模型 key。

当前最急：

1. 查清并修复 `live 模型证明失败` 的真实原因，统一 BYOK/model value/readiness 映射，错误提示必须中文精确。
2. Listing 的 Market Report / Listing Package 不能是英文，商家可见内容必须中文。
3. 继续复验 AI CEO、Listing、批量铺货、素材工坊、决策中心、客服与订单、设置、首页不自动弹登录。

