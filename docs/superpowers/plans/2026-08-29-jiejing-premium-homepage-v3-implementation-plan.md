# 捷境高级官网 V3 实施计划

日期：2026-08-29  
对应规范：`docs/superpowers/specs/2026-08-29-jiejing-premium-homepage-v3-design.md`  
实施边界：只修改公开官网、官网测试与确有需要的公开资源清单；不修改登录后工作台、后端、计费、OAuth 或 eBay 写入

## Phase 0：文档与现有合同发现

### 已读取来源

- V3 设计规范：`docs/superpowers/specs/2026-08-29-jiejing-premium-homepage-v3-design.md:1-185`
- 当前官网结构与样式：`index.html:4039-4863`
- 当前官网交互：`index.html:5758-5906,5919-5959,6600-6640,6842-6886,6977-7011`
- 旧版连线 Hero：提交 `3f9967ec2e804be9030aa8ada0db6acb3925f39c` 的 `index.html:505-707,3960-4017`
- 静态合同：
  - `tools/test_jiejing_homepage_maturity.py:14-56`
  - `tools/test_jiejing_merchant_surface_guard.py:190-308`
  - `tools/test_jiejing_frontend_staging_config.py:190-305,618-653`
  - `tools/test_jiejing_trial_pricing_entry.py:18-103`
- 浏览器验收：
  - `tools/codex_jiejing_homepage_maturity_browser_smoke.js:50-146`
  - `tools/codex_jiejing_public_pricing_responsive_smoke.py:38-160`
- 发布清单：`deploy/apply-staging-patch.sh:104-129`

### 允许复用的 API 与模式

- `#heroWorkbenchLogin` → `openWorkbenchOrAuth()`
- `#topLogin` → `openRealSaasEntry()`
- `#publicWorkbenchEnter` → `openWorkbenchOrAuth()`
- `#choosePlan` → `openRealSaasEntry()`
- `.path-card[data-path][data-plan]` 与 `setPath(key)` / `setPlan(key)`
- `openLoggedInExperience(key, options)` 的现有路由合同
- `.command-room`、`.role-node`、`.ceo-core`、`.flow-line` 的历史结构
- `bindSurfaceLight()` 的现有 CSS 变量交互
- 语义化按钮、`data-*` 状态、`.is-active`、`aria-pressed`、`:focus-visible`
- 现有 5 张 `travel-compression-*-v2.webp`/`video-cover.webp` 公开资源

### 禁止模式

- 不重写认证、Cookie session、套餐映射或工作台跳转。
- 不恢复旧版广告、财务等六节点技术架构。
- 不恢复“留记录、证据链、项目完成度”等内部表达。
- 不使用内联 `onclick`，不引入外部字体/CDN 或重型动画库。
- 不使用 `travel-compression-source.webp`。
- 不虚构销量、转化、素材权利审核或真实发布结果。
- 不为了保持旧测试通过而禁止新版连线 Hero。

## Phase 1：先更新官网 V3 合同测试（Red）

### 实现内容

修改以下测试，使其准确表达已批准的 V3，而不是当前 V2：

- `tools/test_jiejing_homepage_maturity.py`
- `tools/test_jiejing_merchant_surface_guard.py`
- `tools/test_jiejing_frontend_staging_config.py`
- `tools/codex_jiejing_homepage_maturity_browser_smoke.js`

新增/更新断言：

- body 版本标记为 `public-home-v3`；
- 六个 section 顺序不变；
- 唯一主 CTA、三套餐顺序和现有认证路径不变；
- Hero 精确包含一个 AI CEO 核心、五个批准节点和对应 SVG 连线；
- 官网不再出现“工作记录”营销文案；
- 素材工坊包含输入、四个生成方向、审核画布和进入 Listing 的状态；
- 边界文案逐字为 `流程示例｜实际结果以商家提供的商品资料与审核为准。`；
- 素材按钮可键盘操作并具有选择状态；
- `prefers-reduced-motion` 有静态降级；
- 浏览器检查继续覆盖图片加载、无横向溢出、无 console/page errors、无 5xx。

### 参考

- 复制现有浏览器路由与错误收集模式：`tools/codex_jiejing_homepage_maturity_browser_smoke.js:50-104`
- 保留现有套餐/认证合同：`tools/test_jiejing_trial_pricing_entry.py:18-103`

### 验证

先运行并确认至少 V3 新合同因页面尚未实现而失败：

```powershell
python tools/test_jiejing_homepage_maturity.py
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_frontend_staging_config.py
```

### 防错

- 不放宽 `app.html`/`app.js` 的固定商品和商家语言保护。
- 不删除现有 Secret、认证、套餐和越权动作断言。

## Phase 2：实现高级视觉母版与连线 Hero（Green 1）

### 实现内容

- 将 body 作用域从 `.public-home-v2` 更新为 `.public-home-v3`。
- 在 `index.html:4039-4638` 的单一官网作用域内重写 V3 tokens、排版、表面、响应式和动效；不继续追加无作用域覆盖。
- 在 `index.html:4661-4705` 复用旧版连线结构骨架，改成：
  - 中心 `AI CEO`；
  - `市场判断`、`商品资料`、`Listing`、`素材工坊`、`发布确认` 五个节点；
  - 五条中心到节点的关系线；
  - 节点 hover、focus、touch 的对应连线高亮。
- Hero 左侧删除“工作记录”，保留唯一主 CTA 与现有辅助文字链接。
- 移动端将关系图整理成紧凑阶段序列；即使隐藏装饰线，也保留完整五节点语义。

### 参考

- 结构骨架：`3f9967e:index.html:3960-4017`
- 连线和节点 CSS：`3f9967e:index.html:505-707`
- 当前可复用 interaction variables：`index.html:5809-5847`
- 当前初始化位置：`index.html:7003-7011`

### 验证

```powershell
python tools/test_jiejing_homepage_maturity.py
python tools/test_jiejing_frontend_staging_config.py
```

页面内联 JS 语法继续由仓库既有前端语法合同验证，不把 HTML 直接当 Node 模块执行。

### 防错

- 不使用黑色 Hero、紫色渐变球、霓虹或大圆角模板。
- 不让 Canvas/SVG 拦截点击。
- 不把节点写成可触发真实任务的按钮；它们只展示产品关系。

## Phase 3：实现可交互素材工坊演示（Green 2）

### 实现内容

- 替换 `index.html:4759-4794` 的静态画廊和六步列表。
- 新结构包含：
  - 商品输入栏；
  - 四个生成方向状态；
  - 审核画布；
  - 五个素材选择按钮；
  - “进入 Listing 草稿”状态说明。
- 增加 `setupHomepageMediaStudio()`：
  - 从内联只读配置切换图片、标题、用途和状态；
  - 默认显示白底主图；
  - 约 6 秒自动切换一次；
  - 用户第一次点击、触摸或键盘选择后永久停止本页自动切换；
  - 减少动态偏好下不自动切换；
  - JS 失效时首个素材和完整文案仍可见。
- 统一使用：`流程示例｜实际结果以商家提供的商品资料与审核为准。`

### 参考

- 现有 5 张白名单资源：`deploy/apply-staging-patch.sh:125-129`
- 现有图片加载 smoke：`tools/codex_jiejing_homepage_maturity_browser_smoke.js:65-88`
- 现有初始化区：`index.html:7003-7011`

### 验证

- 点击每个素材按钮，主画布、用途与 `aria-pressed` 同步。
- 用 Tab/Enter/Space 完成同样切换。
- 模拟减少动态偏好，确认不自动轮播。
- 无 JS 时首个方案仍显示。

### 防错

- 不称视频封面为真实生成视频。
- 不展示来源不明的 `travel-compression-source.webp`。
- 不使用“完成、已审核、高转化、已发布”等无证据状态。

## Phase 4：商家文案与剩余版式统一

### 实现内容

- 清理 `index.html` 中所有官网/向导可见的“工作记录”营销表达，改为结果、来源、确认或账号内留痕的商家语言。
- 第六类核心能力改为“发布确认”或“店铺协同”，不重复 Hero 节点说明。
- Proof、能力、商家路径、套餐、FAQ 使用同一排版节奏和 6px/8px 表面体系。
- 删除长篇“该商品不代表……”解释；边界只在素材演示区保留一行，在风险区保留必要事实说明。
- 保留当前三套餐数字和路径，不静态宣称公开收费已经可用。

### 参考

- 当前可见问题位置：`index.html:4666,4725,4755,4765`
- 套餐行为：`index.html:5971-6022,6842-6886`
- 设计语言：V3 规范第 7–9 节。

### 验证

```powershell
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_trial_pricing_entry.py
python tools/test_jiejing_merchant_pricing_media_copy.py
```

### 防错

- 不删除后台工作记录数据或 `app.*` 能力。
- 不引入“全自动、保证销量、保证发布”承诺。
- 不把模型、Vault、API Key 或项目状态带回官网。

## Phase 5：浏览器视觉、交互与可访问性验收

### 实现内容

- 更新并运行 `tools/codex_jiejing_homepage_maturity_browser_smoke.js`。
- 运行套餐响应式 smoke。
- 输出桌面、平板、手机全页截图，以及 Hero 和素材工坊重点截图。
- 人工检查视觉比例、节点连线、素材切换、焦点状态和移动端阅读顺序。

### 验证

```powershell
node tools/codex_jiejing_homepage_maturity_browser_smoke.js
python -m http.server 8799 --bind 127.0.0.1
python tools/codex_jiejing_public_pricing_responsive_smoke.py --url http://127.0.0.1:8799/index.html#plans
```

验收视口：1440×1000、1024×900、820×1180、390×844。

### 防错

- 不以截图好看替代 console、5xx、图片自然宽度和实际交互检查。
- 不让 hover 成为理解内容的唯一方式。

## Phase 6：完整验证与部署边界

### 验证顺序

```powershell
git diff --check
python tools/jiejing_secret_scan.py
python tools/test_jiejing_homepage_maturity.py
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_trial_pricing_entry.py
python tools/test_jiejing_merchant_pricing_media_copy.py
python tools/test_jiejing_frontend_staging_config.py
node tools/codex_jiejing_homepage_maturity_browser_smoke.js
python tools/jiejing_prepare_public_staging_bundle.py --dry-run
python tools/jiejing_precloud_deployment_gate.py
```

### 完成条件

- 专项与完整门禁全部通过；
- 工作树只包含本计划允许的文件；
- 不包含 Secret；
- 未触发收费、退款、OAuth 或 eBay 写入；
- 形成独立提交；
- 生产部署前重新执行线上只读校准，并取得新的明确部署确认。
