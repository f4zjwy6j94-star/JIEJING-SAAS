# Codex 续接恢复快照 2026-05-15

这份文件用于防止 Codex 上下文压缩、卡顿、账号切换或会话丢失后方向偏移。新会话先读本文件，再继续做捷境 SaaS。

## 当前项目方向

- 捷境 Jiejing 是 eBay 优先的 AI CEO 跨境电商自动化 SaaS。
- 公开产品语言只讲捷境、AI CEO、工作记录、确认中心、连接账号，不把 Hermes 摊到官网上。
- 当前目标已经从演示页面转向正式产品级 SaaS：前端只是入口，真正链路是后端、数据库、队列、Vault/KMS、Jiejing Runtime、自研 Agent、确认中心、执行服务。
- 用户现在明确要求：逐步独立出 Hermes，建设自研 Jiejing Runtime / Agent 团队。Hermes 可以作为历史参考和早期验证对象，但不再是唯一底座。

## 当前工程状态

- SaaS 后端骨架已经有本地 MVP：登录、用户、公司、店铺、连接、任务、报告、确认中心、审计、队列、ExecutionService。
- Jiejing Runtime 已有 7 个自研电商 Agent 的本地结构化报告能力。
- Provider Jobs 已经把搜索、eBay、1688、物流、素材、模型等未来外部工具抽象成后端队列合同。
- eBay 只读链路已经做到合同层和本地预检层：不会假装同步，不会把 token 给前端或 Runtime。
- eBay 写入仍然关闭。发布、改价、退款、广告、政策修改、采购付款等都必须进入确认中心。

## 2026-05-15 最新改动

新增 eBay 只读凭证预检：

- `jiejing_saas/ebay_credential_preflight.py`
- `POST /stores/{store_id}/ebay-read-only/credential-preflight`
- `POST /stores/{store_id}/ebay-read-only/sync` 现在会内嵌同一份 `credential_preflight`
- `app.js` 的 SaaS 后端面板新增“eBay 凭证预检”
- `tools/jiejing_ebay_credential_preflight.py`
- `tools/test_jiejing_ebay_credential_preflight.py`
- `docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md` 已补充预检说明

## 最新验证结果

已通过：

- `python -m py_compile ...`
- `node --check app.js`
- `python tools/test_jiejing_ebay_credential_preflight.py`
- `python tools/test_jiejing_saas_backend_mvp.py`
- 全量 `tools/test_jiejing_*.py`
- `python tools/jiejing_productization_stage_gate.py`
- `python tools/jiejing_full_stack_smoke.py`
- `python tools/jiejing_runtime_self_check.py`

当前自检结论：

- `FULL_STACK_SMOKE`: `completed_with_blocks`
- `SCORE_AVERAGE`: `93`
- `PRODUCTION_READY`: `False`
- `EBAY_CREDENTIAL_PRESENT`: `False`

解释：工程合同和本地闭环已经很强，但当前运行环境没有 eBay 可用凭证，所以还没有真实读取店铺数据，更没有真实写 eBay。

## 下一步不要跑偏

在解决卡顿和续接安全之后，下一步是：

1. 打通 eBay 只读凭证，让 SaaS 后端真实读取店铺、Listing、订单、费用、三政策、类目字段。
2. 把真实读取结果标准化成 `platform_data_packet`，只把清洗后的数据交给 Runtime。
3. 让前端工作台逐步从静态演示数据切到 SaaS 后端和 Runtime 真实结果。
4. 再做 1688、物流、图片视频、搜索等 Provider Job 的真实适配器。
5. 最后才做确认中心后的真实 eBay 写入适配器。

## 卡顿处理原则

可以清理：

- `__pycache__`
- `output/browser-smoke`
- 反复运行测试产生的临时 SQLite、runtime-runs、旧 smoke 输出
- 可重新生成的截图、临时测试结果

2026-05-15 已执行一次轻量化：

- 临时归档位置：`C:\Users\57249\Documents\Codex\Jiejing_Codex_Light_Archive_20260515\software-demo`
- 已移出工作区但未删除：`artifacts/archive`、`output/playwright`、`output/browser-smoke`、`output/debug-team`、`output/debug-team-direct`、`output/jiejing-saas-backend/test`、`test-results`
- 已删除可再生成缓存：`jiejing_runtime/__pycache__`、`jiejing_saas/__pycache__`、`tools/__pycache__`

2026-05-15 第二次降卡处理：

- 停止了遗留的本地项目服务：Runtime `8765` 和 SaaS Backend `8788`。它们锁住 SQLite，也会拖慢当前 Codex。
- 已整体移出工作区但未删除：`output`、`artifacts`、`screenshots`。
- 归档位置同上，新增目录包括：`workspace_output` / `workspace_output-20260515-215604`、`workspace_artifacts`、`workspace_screenshots`。
- 当前工作区只保留源码、网页、文档、deploy、schemas、tools、`assets` 和一个空 `output` 目录。
- 新增 `.rgignore` 和 `.codexignore`，避免后续扫描输出目录、缓存、SQLite 和大媒体文件。

2026-05-15 第三次降卡处理：

- `.rgignore` / `.codexignore` 增加图片忽略：`*.png`、`*.webp`、`*.jpg`、`*.jpeg`。
- 顶层临时截图 `.codex-*.png` 已移到：`C:\Users\57249\Documents\Codex\Jiejing_Codex_Light_Archive_20260515\software-demo\top-level-temp-images`。
- 注意：`assets` 仍保留在工作区，因为官网和工作流页面直接引用这些商品图；只是让 Codex/搜索尽量不要扫描这些二进制图。

不要清理：

- `app.js`
- `styles.css`
- `index.html`
- `design-huashu.html`
- `jiejing_saas/`
- `jiejing_runtime/`
- `tools/`
- `docs/`
- `deploy/`
- `assets/` 中当前网页引用的图片
- 任何真实账号、token、业务政策、店铺数据、报告、PDF 交付文件

## 恢复方式

如果新账号或新会话接手：

1. 先读本文件。
2. 再读 `docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md`。
3. 再跑：

```powershell
python tools\jiejing_runtime_self_check.py
python tools\jiejing_productization_stage_gate.py
python tools\jiejing_ebay_credential_preflight.py
```

4. 如果都通过，再继续 eBay 只读真实同步。
