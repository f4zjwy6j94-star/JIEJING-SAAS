# 捷境统一公开收费收口：正式上线交付记录

日期：2026-10-05 至 2026-10-06，北京时间。用户最新决定：补齐最后交付项，正式推广上线；本轮已执行。

## 当前结论

**10-06 01:43 最终结论：本次统一收口版已正式部署，独立线上验收通过。**
固定首版软件交付清单关闭 **8/8 项 = 100%**，包括最后 D1 的正式部署及线上后验。
这代表约定的公开收费首版软件交付完成，不代表已经盈利、永久零缺陷，或代商家完成真实刊登/交易。
正式推广地址：[捷境官网](https://jiejing.shop/)；已核对跳转 [商家正式站](https://app.jiejing.shop/)，HTTP200及捷境标题正确。

| 本版验证 | 最终结果 |
| --- | --- |
| 冻结源码 | `1e94f2b798b158c8d34f224185151fcb95aaf912` / tree `724d445bb62fe2446e00d420e909d909ad32c59b`，R/C 相同，发布 checkout clean |
| 完整门禁 | **274/274，0 失败**；session 48319 已 exit0，门禁实际 2756.05 秒；原检查和时限不变 |
| 独立同源核验 | canonical verifier 通过，source_stable/release_eligible=true，运行前后源码未变 |
| 标准包 | 556 文件，标准打包及独立候选校验通过，已按 exact hash pair 移 D |
| 非切换部署预演 | 01:16:53 dry_run_passed / exit0；active_switched=false、candidate_release_persisted=false、secret_exposed=false |
| 正式上线 | **01:29:29 apply 成功、线上已切换本版**；独立active/API/Worker同源校验及外网后验通过，未push |

唯一最终 run：`D:/Codex-Verification/jiejing-unified-closeout-20261005/settings-contract-fix/run-20261006-002741`。
run_id `cb2c4b9bae514d5fa614f4063508a785`；独立证据为 `verified-gate-summary.json`、`verified-local-bundle.json`。
预演回执位于 `D:/Codex-Verification/jiejing-unified-closeout-20261005/settings-contract-fix/dry_run.safe.json`。

- 完整报告 SHA256：`2b3d10753000e3f7751a9c8da0b5e84304d364091293246b7230b514d4e54450`。
- 标准 zip：`release-artifacts/jiejing-public-staging-20261005-171449.zip`，7897387 字节，SHA256 `c64464afdb69970d0a2628d0e4c35de2dd39a3c5b29a3d73a15807612fe19f81`。
- 同名 manifest：143000 字节，SHA256 `88827e218f7b5d37dacf2918764b8a273b6c9c3ebd79a2b13b02bf360ff13251`。
- 最终证据绑定复核 `681de7`：源码、门禁、包、manifest 与预演完全一致。全部会话已结束，不重复运行。

01:17:18 部署前 GET 基线保留在 `settings-contract-fix/public-readonly-final.safe.json`。
**01:32—01:40 部署后独立 GET**：health=ok、deep=ready，production_ready、can_accept_real_customers、public_charging_allowed、billing_ready_for_paid_launch 均 true，阻断和警告均 0。
全面写入标志仍 false；01:42 单独只读核对 API 和 Worker 的受控 eBay 发布能力均 true，没有关闭通过捷境正式发布的方向。
具体账号资格、商品预检、商家确认与平台返回仍是每次实际刊登的条件；本轮未调用真实 eBay、付款、退款或广告接口。

### 正式部署与独立后验

- `settings-contract-fix/apply.safe.json`：session 94018，exit0，status=deployed，active_switched/candidate_release_persisted/evidence_snapshot_initialized/ops_local_tls_assets_isolation_verified 均 true；secret_exposed=false。
- `settings-contract-fix/delivery-20261005-173229.safe.json`：active `/opt/jiejing-production/releases/20261005T173039Z-1e94f2b798b1/app`；active/API/Worker 的 8 个关键代码文件与候选 SHA 全一致，公共主脚本一致，health/deep ready。服务器目录时间戳与本地完成时刻独立记录，不据此改写。
- `settings-contract-fix/public-release-verified.safe.json`：10 个公开文件及客服邮箱通过；JS/CSS 原字节 SHA 一致，HTML 经已明确观察的 Cloudflare 注入/邮箱保护还原后全文一致；商家域 ops.html/ops.js/ops.css 三项404。
- `settings-contract-fix/controlled-publish-lane.safe.json`：仅读取明确非秘密能力布尔，API/Worker effective_controlled_publish_enabled=true，未读取账号/密钥、未请求eBay、未改开关。
- 01:43:21—22 公网 GET：jiejing.shop 跳 app.jiejing.shop，两个正式地址最终200；标题“捷境 · 跨境电商 AI 经营工作台”。

### 线上浏览器 QA

环境：真实生产 https://app.jiejing.shop/；匿名新上下文，桌面1440×1000、手机390×844，现有项目 Playwright/Chrome headless。
Browser 插件未列出，使用项目已经配置的浏览器运行库，无新增依赖；只拦截 `/analytics/events` 和 `/cdn-cgi/rum` 的统计POST，所有被验收业务内容均从真实网站读取，不模拟业务接口。

| 检查 | 桌面 | 手机 |
| --- | --- | --- |
| URL、标题、有效内容、无错误遮层 | 通过 | 通过 |
| 页面异常与console警告/错误 | 0 | 0 |
| 免费/99元/199元方案切换 | 通过 | 通过 |
| 多店铺选择带入登录说明 | 通过 | 通过 |
| 登录框、关闭按钮、支持入口无横溢 | 通过 | 通过 |
| 点击客服→支持页面→正确邮箱 | 通过 | 通过 |
| 匿名直达工作台→首页登录保护 | 通过 | 通过 |
| 注册/登录/支付/刊登请求提交 | 未执行 | 未执行 |

实际交互：官网 → 选择多店铺 → 进入登录 → 点击客服链接 → 看到 zongshuding4@gmail.com → 关闭弹窗 → 有店铺/免费双向切换 → 匿名访问 app.html?start=app → 按保护转回首页 → 再打开登录。
回执 `settings-contract-fix/public-browser-corrected.safe.json`；最终桌面/手机截图已查看，不是本地夹具图。Chrome上下文和浏览器均已关闭，用户原浏览器不受影响。

关键验证顺序：原 `jiejing_production_deploy.py --mode apply` → `verify-delivery.py` → `verify-public-release.py` → `public-browser-smoke.cjs`；浏览器执行 goto、可见内容快照、套餐click、弹窗/支持popup断言、截图、匿名重定向检查。未运行真实注册或支付表单。
最终交付汇总 `e5acb2` 重新核对 apply、后端、10项公共资源、2个视口、收费就绪和eBay能力回执全部同源且通过；发布checkout clean（7b4074），文档diff检查通过（f74ece）。

首次外部脚本失败已保留，不混作通过：原始HTML hash误判边缘注入、把正常匿名转首页当登录框丢失、阻断RUM产生console噪声。之后仅修验收适配，没有产品代码或权限改动。
支持与退款页对邮箱href/span分别编码，不能要求编码串相同；修复前独立键反例 RED，修复后11种控制通过，仍拒绝未知脚本、改价、错邮箱和额外事件处理器。辅助脚本还曾有一次Python保留字语法错误，在运行请求前修正。原失败回执 `public-release-final.safe.json`、`public-release-corrected.safe.json`、`public-browser-final.safe.json` 和诊断 `html-difference-diagnosis.safe.json` 均保留。

本轮采用完成前验证及诊断方法：未用部署回执代替客户可见页面验证，未通过放宽产品权限来让验收通过。
剩余风险：未新增真实注册、收费、退款或eBay刊登，沿用既有业务验收；未把两个浏览器尺寸当作所有设备/账号情形保证，也未发布广告或宣传消息。

### 首次失败和修复记录

171d 首次完整检查为 **273/274**，唯一失败是延迟加载测试仍要求 8 月固定 URL，是上一轮缓存修复遗漏的测试合同，不应被隐藏。
仅修改 `tools/test_jiejing_frontend_settings_module_split.py`（13+/2-）为当前内容指纹校验，提交 1e94f2b；业务文件与 171d 完全相同。
现有入口先 RED 后 GREEN；8 个 CLI 入口文件变异控制全部符合预期，包含旧 URL、内容变更未换版本、提前加载、公共预取、重复源、错误路径和丢失重置。
未删除测试、跳项或改时限。新 274/274 是独立完整运行，不是把旧 273 与单项修复拼接。
失败旧报告 SHA `50f02590e9ed43ea1e34a809bba9060665384fb83f13ae4a8e7ccb78d70b9be0` 保留于 `run-20261005-233344`。

两次完成运行各自的 C 临时目录均核全量 SHA 后可恢复移到各自 D run：旧 run 328 文件/192139957 字节，新 run 329 文件/192917788 字节；未动项目/业务数据。
新门禁最低 C 空间 1.487 GiB，未触发 1 GiB 保护；结束归档后约1.708 GiB。打包后曾有一次只读 PowerShell hash 查询语法错误，修正后读取、精确移包及独立验证全部通过，不涉及产物改写。

## 上一轮产品修复基线（10-05 22:34 历史快照）

以下状态是上一轮当时的记录；当前候选、包及预演状态以顶部最终结论为准：

本轮五类公开收费体验缺陷已修复并提交为本地版本
`171d0eaa4be704e1bfae373f52a1d94c07763f8a`，tree
`a9486dfe5213d6531c46f3118ebe92617a69f66e`。未 push、未打包、未 dry-run、未 apply。
仅 7 个明确文件纳入提交，原有脏文档及两个未跟踪文档保留。

源码仓库：C:/Users/57249/Documents/Codex/2026-04-29/hermes-agents/software-demo。
旧 release checkout 仍为干净 acfa285，旧 274/274、标准包和 dry-run 保留而未复用为新版本通过凭证。
本轮未改变生产。上一轮生产 48054ba 和 21:42 公开 readiness 证据是历史基线，本记录不把它们冒充当前新版本上线结果。

## 五项验收线索

| 维度 | 已有证据和本轮核对 | 边界 |
| --- | --- | --- |
| 客户独立使用 | 沿用 09-26 普通账号注册、20 次领取、空白空间及重入验收；本轮身份揭示/账号切换 35/35、入口/恢复反馈 18/18、官网浏览器回归通过 | 没有重复真实注册、登录凭据输入或新账号领取；不是新商家使用数据 |
| 收费与权益 | 本轮价格、套餐选择、支付不可用、恢复后续购、缺失账单信息、素材点说明和缓存版本回归通过；后台权益投影 11/11 | 无新实款交易、退款或权益写入；价格/额度/续购规则未改 |
| 商品到 eBay | 沿用原商品/Listing/素材质量与保存回写证据；当前真实 JS 发布状态渲染 8 个场景、受控已有草稿发布 HTTP 回归通过 | HTTP 测试使用本地服务及替身，不是本轮真实 eBay 刊登；确认、账号与资料预检不绕过 |
| 数据与权限 | 当前 P0 安全、身份隔离、密钥扫描通过；备份/Vault/恢复/任务证据沿用 acfa285 完整门禁及执行索引 | 未改凭据、数据库或生产配置；不是新的渗透测试或容量压测 |
| 支持与运营 | 当前反馈闭环回归通过，包含权限/重复提交/限流/数据库异常；真实模板按钮打开“套餐与付款·订阅与发票支持” | 未提交真实反馈或邮件；意见箱进入内部后台，不自动转发 Gmail |

## 五类修复

1. 两档套餐可选，但信任说明只写 99 元：改为从同一套餐目录展示有店铺 99 元、多店铺 199 元。
2. 支付不可用被当成试用、引导旧人工试用申请：保留已知付费套餐和到期日，统一显示付款暂不可用，使用现有刷新入口；恢复可用后仍续购原套餐。
3. 付费价格缺失、零值、负值、无效值被当成 0 元，缺少套餐被猜成有店铺：现在显示待核对；已确认免费体验的零价格仍保留。
4. 套餐/官网/设置无条件承诺素材加购：统一注明加购可用性以页面状态为准，未开启任何付费开关。
5. 设置延迟加载模块沿用旧缓存地址：使用当前内容哈希，并补测试防止后续模块修改不刷新缓存。

主要 JS 的 LF SHA256：`699d704f43e15c16062bddb23bcc1d4301bd94930f5e9b653cecb772b38eae37`。
app.html 和 index.html 三处入口版本：`20261005-quality-699d704f43e1`。
设置模块 SHA256：`df0d9aec39f9c778f263d10287093b1af65f582618de7cb964648bb83f8906c4`。

## 回归结果

以下 14 个不同检查入口是产品修复阶段的定向通过记录；语法和 diff 检查另列，不用它们膨胀测试数量。
这部分本身不是 274 项门禁；后续新同源完整 274/274 的终态已单独记录在顶部。

| 检查入口 | 结果 |
| --- | --- |
| tools/test_jiejing_domestic_billing_merchant_ui.py | PASS，执行完整 main；新增两套餐、付款缺失/关闭/恢复、账单缺失及价格反例 |
| tools/test_jiejing_merchant_pricing_media_copy.py | PASS，六个说明位置与延迟加载缓存哈希 |
| tools/test_jiejing_homepage_maturity.py | PASS |
| tools/test_jiejing_saas_clean_settings_and_listing_ui.py | SAAS_CLEAN_SETTINGS_AND_LISTING_UI_OK |
| tools/test_jiejing_merchant_copy_maturity.py | PASS，发布能力 8 场景；执行权限不变 |
| tools/test_jiejing_frontend_staging_config.py | PASS，最终入口指纹及同一前端发布族 |
| tools/test_jiejing_auth_reveal_boundary.js | 35/35 |
| tools/test_jiejing_workflow_entry_feedback.js | 18/18 |
| tools/test_jiejing_billing_entitlement_projection.py | 11/11 |
| tools/test_jiejing_saas_p0_security_guardrails.py | PASS |
| tools/test_jiejing_controlled_existing_draft_publish_http.py | PASS，全部本地 HTTP 与替身 |
| tools/test_jiejing_product_feedback_closure.py | PASS，异常日志是主动注入反例，不是线上故障 |
| tools/codex_jiejing_homepage_maturity_browser_smoke.js | ok=true；桌面/平板/手机、键盘、触屏、减少动态、无 JS、登录尺寸回归；unexpected_requests=[] |
| tools/jiejing_secret_scan.py | PASS，不输出密钥值 |

`node --check app.js`、`node --check assets/jiejing-settings-panels.js`、`git diff --check` 通过。

## 实际页面验证

工具：Codex 内置浏览器（CUA）；沿用实际前端源码与真实事件处理器，本地合成账号/账单，不连接生产。
服务器仅允许本地静态文件与 GET，业务写入被拒绝。最终预览服务请求记录为 21 次 GET，业务写入 0。
桌面首次观察为默认视口，最终 1280×900；手机 390×844（文档宽 375，scrollWidth 375，无横向溢出）。

1. 套餐与付款 → 点击多店铺 → 摘要变成 199 元，开通按钮同步为多店铺；切回有店铺恢复 99 元。
2. 展开退款/安全说明 → 同时显示两档准确价格 → 联系捷境支持 → 打开订阅与发票支持意见箱；没有提交。
3. 合成支付不可用 → 仍显示多店铺 199 元、已知到期日、套餐可用 → 展示刷新付款状态，不出现人工试用申请。
4. 手机宽度重新加载最终源码 → 套餐状态、服务范围、金额、恢复按钮可读；观察到的 console warn/error 为空。

| QA 检查 | 结论 |
| --- | --- |
| 页面身份 | 标题为“捷境 · AI CEO eBay SaaS”，本地 billing fixture 路径 |
| 非空白 / 错误遮层 | 最终桌面与手机均有完整内容，无框架错误遮层 |
| 控制台 | 已观察的最终页面 warn/error 为空 |
| 交互 | 套餐双向切换、说明展开、支持抽屉通过；未点击真实资金/发布操作 |
| 截图 | 最终桌面及手机实际截图已查看；合成状态明确标注 |

截图：

- `payment-unavailable-desktop-final.png`：最终源码、桌面，保留权益并给出恢复入口。
- `payment-unavailable-mobile-final.png`：最终源码、手机，金额、期限与刷新按钮。
- `subscription-support-after.png`：订阅支持抽屉与两档价格。
- `billing-before-full.png`：修复前单一 99 元说明。

过程中保留的失败不能当通过：各新增反例先 RED 后 GREEN；一次漏改内部显示引用触发 ReferenceError，已修复并完整回归；一次前端版本族不一致被合同拒绝，已对齐；手机首次空白来自测试夹具隐藏优先级，修复夹具后以最终截图重新验收。早期 `payment-unavailable-mobile.png` 不作为通过证据。

## 下一步和停止线

五类产品缺陷及遗漏的旧测试合同已修复。最终统一候选完整门禁、独立同源核验、标准包、独立包校验及非切换预演均已完成。
用户本轮正式上线批准已执行：原171449包已经标准apply，线上源码/资源/运行健康/收费就绪与匿名入口均后验通过。无需再次部署。
下一步转入真实运营和有证据的用户反馈迭代，不再以无限增加开发清单代替对外开放。现有7天免费、99/199元30天方案与真实eBay确认发布路径保持；未承诺收益，也未发起推广花费。
不重复已经完成的门禁、打包、预演、apply或本次页面验收；如果之后源码/环境发生变化，先只读核对具体影响，再决定需要刷新哪些证据。
不以新的商家招募、重复三个品、OAuth、实款/真实刊登演练作为这批软件收口的前置。
也不把本地回归改称真实商业收入闭环：具体 eBay 刊登仍以用户确认后平台返回的结果为准。
当前无门禁、打包、校验、预演或部署任务在途。上一轮预览进程 PID 23756 和临时验收 tab 30 已结束；本轮独立匿名浏览器已关闭，用户原项目页面保留。
正式部署许可不等于真实 eBay 刊登、收费或退款许可；客服邮箱仍为 zongshuding4@gmail.com，意见箱由内部后台收件，不自动转发 Gmail。

## 历史起点：10-05 23:33 启动统一完整验收

当时延续既有首版交付范围，不新增功能清单，部署保持暂停。
当时唯一完整门禁 session 9827 / gate PID 27396，源 171d0ea，run-20261005-233344；沿用 274 项原检查与时限。该运行后来以 273/274 失败结束，已在顶部记录原因及新运行结果。
23:36:13 公网只读 health=ok、deep=ready、production_ready/can_accept_real_customers/public_charging_allowed=true，blocker/warning=0。
该在线基线不是新版本部署或真实扣款/刊登证明；安全摘要见 public-readonly-2336.safe.json。

## 最终进度口径固定

沿用当前执行索引中已经确定的 R1/J1/J2/J3/J4/B1/C1/D1 八项首版软件交付标准，按已关闭项目数计完成率，不把它说成工时比例或收入达成率。
本轮新增修复和完整回归分别属于 B1/C1 和 D1，不通过增加分母或另立架构目标无限延期。
R1、J1–J4、B1、C1 沿用已验收事实与对应回归；新版本的 D1 已完成完整门禁、同源发布准备、正式部署和线上后验，现已关闭。
X1 真实经营刊登/收入单独列示；不通过软件百分比伪造它已完成。最终百分比已依据本次验收终态核对如下。

| 固定项 | 本轮使用的证据 | 交付计数 |
| --- | --- | --- |
| R1 运行证据可靠性 | 既有独立日志探针/维护验收，01:17 线上健康 ready、零阻断；新同源完整 274/274 | 已关闭 |
| J1 登录、重入、账号隔离 | 09-26 普通账号实页；身份边界 35/35，最新完整回归通过 | 已关闭 |
| J2 对话、报告、商品、Listing 保存续接 | 原三品各两轮保存/冷刷新/跨商品核对，每次 37/37；最新完整回归通过，不重复模型调用 | 已关闭 |
| J3 素材审核、回写、点数 | 既有素材实页与权益验收，保留概念图/授权保护；最新完整回归通过 | 已关闭 |
| J4 发布前检查、确认、幂等 | 原三品只读预检、受控发布本地 HTTP 及最新完整回归；本地替身不冒充真实刊登 | 已关闭 |
| B1 套餐、试用、扣点、退款保护 | 普通账号 20/20 实页、既有收费退款记录；账单异常及权益修复经定向和完整回归通过 | 已关闭 |
| C1 官网与商家能力说明 | 公开客服/eBay 发布说明/两档价格/付款异常/加购边界；实际模板桌面/手机及完整回归通过 | 已关闭 |
| D1 最终同源发布及线上后验 | 新版274/274、同源556文件包、dry_run、正式apply、线上active/API/Worker与公共资源、匿名桌面/手机、收费就绪后验均通过 | 已关闭 |

计数口径：已有七项验收经完整回归复核保留；D1新版部署后验本轮完成，因此 **8/8 = 100%**。这是固定首版软件交付清单关闭率，不因测试次数增加机械加分，也不等于收益达成率。
本次同源完整结果未留下失败项；这不保证所有未来环境和真实交易必然成功。X1 真实经营刊登/收入仍独立记录，不把它伪造成已经实现。

## 线上截图

桌面与手机：真实官网选择多店铺后进入登录，显示正确的后续付款路径；均未提交表单。

![线上桌面入口](/D:/Codex-Verification/jiejing-unified-closeout-20261005/settings-contract-fix/verified-public-desktop-entry.png)
![线上手机入口](/D:/Codex-Verification/jiejing-unified-closeout-20261005/settings-contract-fix/verified-public-mobile-entry.png)
