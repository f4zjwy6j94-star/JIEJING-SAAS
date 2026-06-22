# 捷境 Software Demo v0.1

打开 `index.html` 即可运行，无需构建步骤。

当前目标不是接入真实 eBay，而是验证产品前台结构。前台品牌叫“捷境”，内部项目代号仍可保留 Hermes：

- 进入网址后先看到两页前置入口：品牌封面 -> 卖家路径选择 -> 官网详情页。
- 第 1 页可向下滚动，讲产品介绍、故事和底层逻辑。
- 第 2 页选择卖家类型后，先进入对应流程说明页，再注册/登录。
- 每条路径会说明 AI 做什么、人要做什么，需要人工确认的地方可点开说明。
- 注册/登录后先进入网页式新手向导，不直接进入控制台。
- 新手向导可一步步完成 eBay 开店进度、API 准备、履约、素材、客服口吻和 AI 权限。
- 新手不想继续向导时，可“先保存退出，看控制台示例”。
- 官网首页先讲清楚“捷境是什么”，再让卖家动态预选自己的阶段。
- 首页核心口径更新为：一个 AI CEO 接住商家目标，把 eBay 重复流程拆成 SOP，再调度后台岗位协同执行。
- 后台岗位覆盖市场调研选品、商品图、商品视频、描述详情、商品参数、上架刊登、广告投流、店铺订阅、客服售后、收发货和财务复盘。
- 商家不用管理一堆 agent；结果统一回流到 AI CEO，由 CEO 汇总证据、风险、费用和人工确认项。
- 预选项会实时生成注册后路径；按路径注册后进入网页式向导第 2/12 步。
- 自动化边界向导已包含 eBay 开店进度和 eBay API 连接准备。
- 自动化边界向导新增 eBay 费用与广告授权：店铺订阅费、刊登费、成交费、广告费默认进入真实利润判断。
- 用户仍可跳过向导，直接进入系统详情页。
- AI CEO 工作台是主入口。
- AI CEO 支持文字布置任务，并预留语音布置入口；语音不会直接执行，需转文字后确认。
- 工作台顶部有店铺切换和简短 eBay 连接状态，多店铺从这里进入。
- 自动化规则承载商家差异，日常不放在控制台侧边栏。
- 自动化规则填完后放在“设置与账户”，可随时修改履约、利润、客服口吻和 AI 权限，也可逐步添加店铺/品类/团队规则模板。
- “设置与账户”新增 eBay 费用与广告授权中心，区分 Account API 订阅状态、Finances API 费用账单、Marketing API 广告只读和广告执行确认。
- 选品/上架项目支持多个项目并行：调研多个品、不同店铺走不同项目。
- 财务经理的利润公式包含：售价、货源成本、物流、eBay 成交/刊登费用、广告费、店铺订阅分摊和退货风险预留。
- AI 工作记录按项目展示，让商家看到每个项目里 AI 查了什么、做了什么。
- 后台 AI 岗位只作为透明执行记录出现。
- 确认中心负责 AI 自动化流程中的人工介入点。
- 客服与物流中心允许人接管 AI 草稿，旁边展示订单/物流窗口，避免 AI 和人工同时回复。
- eBay 连接状态移到“设置与账户”，日常只在顶部显示简短状态。
- 广告创建、调预算、暂停广告以及开通/取消店铺订阅默认进入确认中心，AI 不自动执行。
- eBay 页面全部为 Mock / 演示数据。
- 新增 `design-huashu.html`：基于 huashu-design 思路做的“少动效、高质感、顺滑交互”版本，不覆盖当前主 Demo。
- `design-huashu.html` 已补齐路径开始/保存反馈、订阅卡点击详情和 toast 反馈；主 Demo 首页新增入口“看 Huashu 新版”。
- `design-huashu.html` 继续升级为 Premium Interaction：新增顶部滚动进度、鼠标经过光感、滚轮响应的自动化信号波形、自动化链路总览色带和滚入视口动效。
- `design-huashu.html` 针对鼠标划过卡顿做了性能优化：全屏光效改为 GPU 位移，卡片光效改为 requestAnimationFrame 节流，canvas 不再每帧触发 CSS 重算；开始/订阅下一步改为明确弹层反馈。
- `design-huashu.html` 已升级为可体验 Demo Flow：路径/订阅下一步会模拟注册登录并进入 AI CEO 工作台；工作台支持语音转文字模拟、发送任务、生成素材任务包和人工确认清单。主 Demo 首页入口更新为“体验 Huashu Demo”。
- `design-huashu.html` 已把旧版小白自动化边界向导补回新版流程：路径选择 -> 注册/登录 Demo -> 自动化边界向导 -> AI CEO 工作台。自动化边界向导包含履约方式（1688 代发、自己发货、海外仓、混合履约）、eBay 开店进度、素材来源、客服口吻、AI 权限。

验证截图位于：

- `..\patch_work\software_demo_entry_desktop.png`
- `..\patch_work\software_demo_entry_route_desktop.png`
- `..\patch_work\software_demo_entry_mobile.png`
- `..\patch_work\software_demo_entry_route_mobile.png`
- `..\patch_work\software_demo_landing_desktop.png`
- `..\patch_work\software_demo_landing_mobile.png`
- `..\patch_work\software_demo_onboarding_newbie_desktop.png`
- `..\patch_work\software_demo_onboarding_desktop.png`
- `..\patch_work\software_demo_workflow_desktop.png`
- `..\patch_work\software_demo_activity_desktop.png`
- `..\patch_work\software_demo_service_desktop.png`
- `..\patch_work\software_demo_connect_desktop.png`
- `..\patch_work\design_huashu_demo_flow_desktop.png`
- `..\patch_work\design_huashu_demo_flow_mobile.png`
