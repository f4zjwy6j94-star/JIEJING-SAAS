# AI CEO 开放域对话与商品资料接力实施计划

日期：2026-08-24  
设计依据：`docs/superpowers/specs/2026-08-24-ai-ceo-open-domain-and-merchant-source-design.md`  
工作分支：`codex/ai-ceo-real-merchant-loop`

## Phase 1：结构化轮次计划

### What to implement

1. 在 `jiejing_saas/ai_ceo_chat.py` 新增 `ai_ceo_turn_plan_v1`，统一输出回答模式、实体、时效要求、研究深度、只读工具、模型档位、连续主题和确认边界。
2. 保留现有确定性高风险门禁；普通开放域问题不能因为不属于 eBay 被拒绝，也不能错误创建经营工件。
3. 从安全化的最近对话恢复股票代码、公司、地点或商品等连续实体；只把相关状态交给回答模型。
4. 将 turn plan 写入聊天结果和任务审计的安全字段，不记录 Secret 或原始 provider 响应。

### Verification

- “上海明天天气怎么样”走天气研究、不进入 eBay。
- “AAOI 基本面有什么问题”走深度公开研究和 Pro 档。
- 后续“它最近为什么波动”继续保持 AAOI。
- 简单翻译/写作走直接回答和 fast 档。
- eBay 轻小不带电选品仍走经营工作流并保持商品事实阻断。

## Phase 2：模型复杂度分层

### What to implement

1. `jiejing_saas/api_server.py` 在模型连接解析前读取后端 turn plan；前端不能指定权威模型档位。
2. 平台 DeepSeek 简单任务使用 Flash，复杂研究和 Listing 结构化任务使用 Pro；多步但规模较小的任务使用 Flash thinking。
3. 商家 BYOK 不静默更换计费模型，只在其现有 DeepSeek 模型支持时切换 thinking；能力与选择原因写入公开安全元数据。
4. `jiejing_runtime/model_clients.py` 只对 DeepSeek 官方端点投影 thinking 参数，其他 provider 保持现有协议。

### Verification

- 单元测试校验 fast/thinking/pro 选择与 DeepSeek 请求 payload。
- 模型临时错误 fallback 与复杂度升级字段分开。
- 计量仍覆盖实际模型调用，不回显密钥。

## Phase 3：商品资料模块

### What to implement

1. 在 `app.js` 的真实 Listing 工作台新增 `merchant_product_fact_packet_v1` 模块，分组展示商品身份、实物规格、价格库存、履约与图片权利。
2. 字段明确标注“来源资料”“商家确认”“AI 建议”“待补资料”；商家直接在捷境填写和修改，不要求打开 eBay。
3. 保存时同步到当前 Listing 草稿、发布预填与受保护本地快照；缺失字段保留为阻断，不用 AI 编造。
4. 已填字段不再通过 AI CEO 逐项重复询问；对话只概括仍缺的关键资料。
5. 不复用旧手机壳、旧 SKU、旧图片或演示货源预设。

### Verification

- 前端契约测试检查模块、分组、来源标签、未知项和保存行为。
- `node --check app.js`。
- 桌面与移动布局检查。

## Phase 4：回归、门禁与生产发布

### What to implement

1. 运行 AI CEO、Listing、模型连接和事实阻断专项测试。
2. 运行 JavaScript 语法检查、秘密扫描和完整 precloud gate。
3. 运行生产 dry-run，确认 manifest、private env 引用和所有真实写入开关保持原状。
4. 使用已获得的部署批准发布；随后验证健康、深度健康、产品 readiness、ops 隔离和前端资源版本。

### Success boundary

- 本轮只部署对话编排和商品资料接力，不执行 OAuth、支付、退款、真实收费或 eBay 写入。
- HTTP 200 只证明网站在线；公开收费、私测可用和真实平台写入继续按 readiness 的独立证据汇报。
