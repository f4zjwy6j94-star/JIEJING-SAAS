# 捷境官网「收纳包版本」恢复与现代化实施计划

日期：2026-08-29  
对应规格：`docs/superpowers/specs/2026-08-29-jiejing-homepage-restoration-modernization-design.md`

## Phase 0：文档发现与允许复用模式

### 已读取证据

- 项目边界和验证要求：`AGENTS.md:5-97`。
- 已批准设计：`docs/superpowers/specs/2026-08-29-jiejing-homepage-restoration-modernization-design.md:8-163`。
- 当前首页 DOM、内联样式、登录与跳转：`index.html:21-4037,4042-4357,5391-5442,5572-6074,6266-6306`。
- 收纳包旧首页：提交 `3f9967ec2e804be9030aa8ada0db6acb3925f39c` 的 `index.html:3918-4073,4416-4578`。
- 专业审查链：`docs/JIEJING_PROFESSIONAL_PROMPT_PLAYBOOK_20260628.md:50-140,283-304,349-356`。
- 首页静态和浏览器合同：
  - `tools/test_jiejing_homepage_maturity.py:14-48`
  - `tools/test_jiejing_merchant_surface_guard.py:223-325`
  - `tools/test_jiejing_frontend_staging_config.py:212-223`
  - `tools/test_jiejing_trial_pricing_entry.py:17-48`
  - `tools/codex_jiejing_homepage_maturity_browser_smoke.js:60-107`
  - `tools/codex_jiejing_public_pricing_responsive_smoke.py:91-133`
- 公共发布静态文件白名单：`deploy/apply-staging-patch.sh:104-130`、`tools/jiejing_prepare_public_staging_bundle.py:94-122`。

### 当前基线

- `test_jiejing_frontend_staging_config.py`：通过。
- `test_jiejing_merchant_surface_guard.py`：通过。
- 首页三视口浏览器 smoke：通过，六板块、三套餐、登录弹窗、无横向溢出和无页面错误均成立。
- `test_jiejing_trial_pricing_entry.py`：预先存在失败；测试仍要求旧顺序 `opened,multi,trial`，当前产品合同为 `trial,opened,multi` 对应 `free,single,multi`。这是旧测试漂移，不通过改产品顺序迁就。

### Allowed APIs / DOM patterns

- 主登录入口复用 `openWorkbenchOrAuth()`，不重写鉴权。
- 套餐和商家入口复用 `setPath()`、`setPlan()`、`.path-card[data-path][data-plan]`。
- 登录注册继续使用 `/auth/login`、`/auth/register`、Cookie session 和 `credentials: "include"`。
- 保留 `#topLogin`、`#nextStepModal`、`#entryLoginForm`、`#entryAuthEmail`、`#entryAuthPassword`、`#entryLoginSubmit`、`#entryRegisterSubmit`、`#entryModeGrid`。
- 页首主 CTA 使用 `#heroWorkbenchLogin`；页尾 CTA 使用 `#publicWorkbenchEnter`；套餐入口使用 `#choosePlan`。
- 图片复用 `<picture><source webp><img png fallback></picture>` 模式；公开 bundle 只新增必要 WebP。
- 六个公开内容板块继续以 `data-home-section` 做稳定合同，但更新为与新语义一致的值。

### Anti-pattern guards

- 不复制旧 `ceoTaskForm` 的前端模拟 AI 回复。
- 不用 `.flow-tab` 构造新六步展示，避免触发现有全局交互。
- 不用 `.path-card` 构造有货源/无货源说明，避免误改套餐状态。
- 不复制旧九个标签、固定排名、低退货、IP 通过、高转化、已完成等无证据表达。
- 不展示 `travel-compression-source.*`；来源和授权不明。
- 不放松登录后工作台、Listing、首次进入和部署门禁对固定示例商品的禁令。
- 不在静态官网宣称公开收费已开放；套餐购买仍进入登录后账单并读取后端状态。

## Phase 1：更新首页合同并建立 RED

### What to implement

1. 更新静态合同，要求：
   - 主标题为“让 eBay 经营少一点重复，多一点自动推进。”
   - 唯一填充主 CTA 为“进入 AI CEO 工作台”。
   - 恰好六个新语义 `data-home-section`。
   - 存在四项可信指标、六步示例工作流、两类商家路径和强制免责声明。
   - 三套餐顺序为 `free,single,multi`，路径为 `trial,opened,multi`。
2. 窄化收纳包禁令：只允许在 `data-home-example="travel-compression-workflow-v1"` 的公开示例区出现，并要求逐字免责声明；登录后工作台的固定商品禁令保持不变。
3. 更新浏览器 smoke：等待新 Hero marker，点击 `#heroWorkbenchLogin`，验证真实登录弹窗、六板块、三套餐、图片加载、无溢出和无页面错误。
4. 修正 `test_jiejing_trial_pricing_entry.py` 的旧顺序断言。

### Documentation references

- 复制静态可见文本和函数作用域检查：`tools/test_jiejing_merchant_surface_guard.py:223-325`。
- 复制三视口路由和错误收集：`tools/codex_jiejing_homepage_maturity_browser_smoke.js:50-107`。
- 复制套餐前后端一致性检查：`tools/test_jiejing_trial_pricing_entry.py:17-77`。

### Verification checklist

- 新首页合同在 DOM 改造前按预期失败。
- 失败只指向新标题、CTA、板块、示例区和免责声明。
- 工作台固定商品、Secret、内联事件和套餐数值保护仍然有效。

### Anti-pattern guards

- 不删除断言来获得绿色结果。
- 不把收纳包例外扩大到 `app.html` 或 `app.js`。
- 不让测试点击登录、收费、OAuth 或平台写入之后的真实动作。

## Phase 2：重建公开首页 DOM 与作用域样式

### What to implement

在 `index.html` 中定点重构公开首页，不整文件回滚：

1. 导航：产品能力、工作流程、适用商家、套餐；保留登录/注册。
2. Hero：恢复 AI CEO 完整定位、单主 CTA 和四步调度视觉。
3. 可信指标：只展示产品结构和确认边界，不展示虚构经营数据。
4. 产品能力：市场调研、商品资料与 Listing、图片与视频、客服订单、工作记录、确认中心。
5. 收纳包示例：使用 `main-v2 / scene-v2 / feature-v2 / detail-v2 / video-cover` 展示六步工作流，并显示强制免责声明；视频封面只称“视频脚本与封面示意”。
6. 商家路径：有货源直接整理商品事实；无货源先调研候选、商家自行找货后继续。
7. 套餐与 FAQ：保留当前三套餐数字、风险说明和登录后付款入口。
8. 页尾增加 `#publicWorkbenchEnter`，复用 session-aware 入口。

样式全部放在 `.public-home-v2` 作用域内，使用已批准系统：

- 颜色：`#fffefa / #f5f8f5 / #111d18 / #08766e / #064f49 / #b98228`。
- 字体：现有 Microsoft YaHei / PingFang SC / Noto Sans SC；不加载新 CDN 字体。
- 间距：8px 基础单位，主要区块 64–96px，卡片 24–32px。
- 圆角：8px 主基线，Hero 与商品图容器最多 20px，不使用满页胶囊。
- 阴影：最多两级；商品图和 Hero 使用柔和深墨色阴影。
- 动效：160–320ms `cubic-bezier(0.2,0.8,0.2,1)`，遵守 `prefers-reduced-motion`。

### Documentation references

- 文案和区块顺序：已批准规格 `:40-133`。
- 旧 Hero 结构参考：`3f9967e:index.html:3918-4017`。
- 旧素材墙 `<picture>` 结构参考：`3f9967e:index.html:4482-4551`。
- 当前套餐卡和行为：`index.html:4226-4248,6266-6306`。

### Verification checklist

- Phase 1 新合同全部转绿。
- 首屏十秒内能回答：产品是什么、主要服务哪个平台、AI 做什么、哪些动作需要确认。
- 收纳包只在标记示例区出现，图片旁可见免责声明。
- 登录弹窗、三套餐状态、工作台跳转不回退。

### Anti-pattern guards

- 不恢复复杂的六节点放射图或多主按钮。
- 不新增假数字、客户 Logo、成功案例或销量指标。
- 不用 CSS 隐藏旧公开内容冒充删除；公开 DOM 直接保持六个清晰板块。
- 不继续追加无作用域的 `.hero/.command-room` 尾部覆盖。

## Phase 3：静态资源与发布清单

### What to implement

1. 首页只引用五张必要 WebP：
   - `assets/travel-compression-main-v2.webp`
   - `assets/travel-compression-scene-v2.webp`
   - `assets/travel-compression-feature-v2.webp`
   - `assets/travel-compression-detail-v2.webp`
   - `assets/travel-compression-video-cover.webp`
2. 更新 `deploy/apply-staging-patch.sh` 的 `FILES` 白名单，确保部署后图片不会 404。
3. 不加入 `travel-compression-source.*`，不扩大 bundle 到整组历史样例资产。

### Documentation references

- 生产 assets 挂载：`deploy/docker-compose.production-pilot.yml:215-227`。
- 发布白名单：`deploy/apply-staging-patch.sh:104-130`。
- bundle 契约：`tools/jiejing_prepare_public_staging_bundle.py:94-122`。

### Verification checklist

- 五张 WebP 均被 Git 跟踪且能由本地静态路由返回 200。
- public staging dry-run bundle 包含 `index.html`、更新测试/清单和五张图片。
- 没有把 PNG、大型历史素材或 Secret 加入发布包。

### Anti-pattern guards

- 不假设生产机器已经有这些图片。
- 不将视频封面描述为真实生成的视频文件。
- 不把 staging dry-run 说成已经部署。

## Phase 4：响应式、交互和专业复盘

### What to implement

1. 覆盖桌面 1440×1000、平板 1024×900/820×1180、手机 390×844。
2. 检查键盘焦点、触摸目标、图片 alt、无文字溢出、无横向滚动。
3. 检查主 CTA、登录、套餐选择、FAQ 和页尾 CTA。
4. 按 Beginner UX、UI Design Polish、Product Owner、Reality Checker 顺序复盘。

### Verification checklist

- 浏览器 console 和 pageerror 为零，所有五张图片加载成功。
- 三档价格单行显示，CTA 不遮挡，手机端商品图和文字顺序合理。
- 页面不出现项目完成度、Runtime、Vault、provider、preflight、测试编号或开发汇报。
- 页面不宣称收纳包正在销售、已取得授权、已有销量或已生成真实视频。

### Anti-pattern guards

- 不以截图通过代替交互和错误检查。
- 不因为桌面效果好而跳过移动端。
- 不在审核中顺手修改登录后工作台。

## Phase 5：聚焦测试、全量门禁与交付边界

### Verification commands

```powershell
git diff --check
python tools/test_jiejing_homepage_maturity.py
python tools/test_jiejing_merchant_surface_guard.py
python tools/test_jiejing_trial_pricing_entry.py
python tools/test_jiejing_merchant_pricing_media_copy.py
python tools/test_jiejing_frontend_staging_config.py
node tools/codex_jiejing_homepage_maturity_browser_smoke.js
python tools/jiejing_prepare_public_staging_bundle.py --dry-run
python tools/jiejing_secret_scan.py
python tools/jiejing_precloud_deployment_gate.py
```

如响应式 Python smoke 需要真实 HTTP 服务，使用本地静态服务，不指向生产进行登录或数据写入。

### Completion criteria

- 聚焦测试、浏览器 smoke、Secret 扫描和最新门禁通过。
- 变更只包含官网、对应测试和五张图片发布白名单；`app.html/app.js` 与后端业务逻辑未修改。
- 本地完成只表述为“代码与本地验证完成”。
- 正式部署前提供 dry-run、变更摘要和当前 readiness，取得针对本次部署的明确确认后才 apply。

### Stop conditions

- 任何登录、套餐、图片加载、浏览器错误或 Secret 检查失败即停止部署。
- 本轮不触发真实支付、退款、eBay OAuth、草稿保存、发布、广告或采购付款。
- 页面上线不等于 readiness、公开收费或真实平台写入状态发生改变。
