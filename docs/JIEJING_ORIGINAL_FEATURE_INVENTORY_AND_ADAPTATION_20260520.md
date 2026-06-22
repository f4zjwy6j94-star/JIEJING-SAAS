# 捷境原 SaaS 功能盘点与新版工作流归位 2026-05-20

## 结论

原先 SaaS 设计不能被压缩成几个简单菜单。它已经包含一套完整跨境商家工作台雏形：

- 官网与信任说明
- 登录、注册、身份向导
- AI CEO 工作台
- 产品刊登
- 素材工坊
- 批量铺货
- AI 汇报 / 工作记录
- 待我确认 / 确认中心
- 自动客服
- 连接账号 / 设置
- eBay 官方只读数据、货源、物流、费用、广告、政策、模型、记忆、团队权限等后台能力

新版设计不是删掉这些功能，而是把它们归位到“eBay-first AI CEO 商家 SaaS”的日常使用结构里。

## 新版主导航建议

第一层只给商家看到 6 个主入口，避免复杂：

```text
今日经营
Listing 工厂
素材工坊
AI CEO 汇报
决策队列
设置
```

高级能力放到二级页或右侧面板，不一上来占满左侧导航。

## 原功能保留与归位表

| 原功能 | 保留方式 | 新位置 | 当前阶段重点 |
| --- | --- | --- | --- |
| 官网首页 | 保留 | 登录前官网 | 继续突出 eBay-first、AI CEO、只读授权、确认边界，不展示 Hermes |
| 登录/注册 | 保留 | 登录入口 | 正式商家账号优先，公开 demo-session 继续禁用 |
| 身份向导 | 保留 | 设置/首次进入前置流程 | 新手、已开店、有订单、多店铺四条路径继续保留 |
| AI CEO 工作台 | 保留并升级 | 今日经营 | 商家每天先看状态、机会、风险、待确认和下一步 |
| 产品刊登 | 保留 | Listing 工厂 | eBay 字段、标题、类目、item specifics、政策、价格、库存、发布阻断 |
| 素材工坊 | 必须保留为核心模块 | 素材工坊 | 主图、场景图、详情页、尺寸图、视频封面、口播脚本、分镜、素材真实性 |
| 批量铺货 | 保留但不默认压给新手 | Listing 工厂二级 / 今日经营推荐 | 从“一键铺货”改成“批量前质检”：筛选、分组、草稿、抽检、分批确认 |
| AI 汇报 / 工作记录 | 保留并产品化 | AI CEO 汇报 | 市场、刊登、素材、风控、客服、财务、确认等报告统一沉淀 |
| 待我确认 | 保留并升级语言 | 决策队列 | 后端仍是 confirmations；前台只讲“老板需要拍板的事” |
| 自动客服 | 保留 | 设置二级 / 今日经营异常入口 | 先吃商品档案，再处理订单、物流、退款、差评和承诺风险 |
| 连接账号 | 保留 | 设置 | eBay、1688、物流、广告费用、模型 BYOK、团队权限、数据源状态 |
| eBay 官方数据 | 保留 | 设置 / 数据与来源面板 | official_api、packet_id、六类资源、freshness、字段缺口 |
| 货源/1688 | 保留为 Provider | Listing 工厂 / 设置 | 先手动链接/图片/表格，后续接 1688 只读；采购付款必须确认 |
| 费用/广告授权 | 保留 | 设置 / Listing 工厂利润页 | 只读费用、广告表现；预算和投放动作进决策队列 |
| eBay 政策控制台 | 保留 | Listing 工厂 / 设置 | 三类 business policies 只读/选择，修改政策必须确认 |
| 数据源健康 | 保留 | 设置 / 右侧证据栏 | 区分 eBay official、公开搜索、货源链接、上传文件、AI 推断 |
| 模型设置/BYOK | 保留 | 设置 | 商家自带 API key，捷境只保存 secret_ref，不回显 key |
| 记忆库 | 保留但不做主菜单 | 设置 / AI CEO 汇报 / 今日经营侧栏 | 老板偏好、素材标准、客服边界、利润底线、确认规则永久沉淀 |
| 团队权限 | 保留 | 设置 | Owner/Operator/Finance/Support/Viewer，确认高风险动作要权限 |
| 审计日志 | 保留为底层能力 | AI CEO 汇报 / 设置 | task、报告、确认、执行交接、secret_ref 操作全留痕 |

## 第一屏：今日经营

今日经营不是普通 Dashboard。它应该回答：

```text
我的 eBay 店现在安全吗？
AI CEO 发现了什么机会？
哪些事可以自动继续？
哪些事需要我确认？
今天最该做哪 3 件事？
```

保留原先能力：

- 经营状态卡
- 当前项目进度
- AI CEO 对话入口
- 后台岗位工作记录摘要
- 待确认数量
- eBay 连接和数据包状态

改造重点：

- 不再把所有模块堆在首页。
- 首页只做“下一步调度”。
- 今日经营可以把商家带去 Listing 工厂、素材工坊、AI CEO 汇报或决策队列。

## Listing 工厂

Listing 工厂是原“产品刊登 + 部分批量铺货 + eBay 字段检查”的核心归位。

必须保留：

- 商品刊登队列
- eBay 已填写草稿
- 标题、类目、Format、Condition、Price、Quantity
- item specifics
- Description HTML
- 三类业务政策
- 图片与视频需求
- 包裹重量、尺寸、发货地
- 发布前 blocker
- 批量候选转入草稿
- IP/合规风险扫描
- 利润与履约检查

界面主流程：

```text
商品输入
-> 市场/机会判断
-> eBay 字段草稿
-> 素材需求
-> IP/合规风险
-> 利润/履约
-> 上架包
-> 决策队列
```

当前阶段仍然只生成草稿和报告，不写入真实 eBay。

## 素材工坊

素材工坊不是“附属按钮”，是捷境原 SaaS 的核心模块，必须作为主入口保留。

两条入口继续保留：

```text
流程导入：市场报告 + Listing 草稿完成后自动进入素材工坊
独立上传：临时货源图单独处理，只生成素材草稿，不默认代表可销售
```

素材标准继续保留：

- eBay 主图 1600x1600
- 白底主图
- 场景图
- 细节图
- 尺寸图
- 包装清单图
- 详情页长图
- 视频封面
- 15-30 秒产品展示 / 口播视频脚本
- 分镜、字幕、卖点节奏
- 平台预设：eBay 优先，Amazon/Shopify/TikTok/独立站只做预留规格
- 真实商品结构不能被 AI 改掉
- 商用授权、来源、实物一致性进入确认

底层 Agent 归位：

```text
Asset Manager / Media Agent
Image Agent
Video Agent
Creative Agent
Compliance Agent
Evidence Agent
```

底层已有合同：

- `asset.brief`
- `MediaGenerationAdapter`
- `MediaGenerationConfig`
- asset manifest
- image/video provider seam

当前差距：

- 前端素材工坊偏完整体验稿。
- Runtime 有媒体生成合同。
- 真正 live 图片/视频 provider、asset manifest 入库和商家 BYOK/Provider 选择还没有完全闭环。

## AI CEO 汇报

原“AI 汇报 / 工作记录”应保留并升级成“商家可读经营档案”。

汇报来源：

- 今日经营
- Listing 工厂
- 素材工坊
- 批量铺货
- 自动客服
- 决策队列
- Runtime reports
- confirmations
- audit logs
- merchant memory

每条汇报必须显示：

```text
做了什么
用了哪些来源
结论是什么
缺口是什么
下一步交给哪里
是否需要确认
是否已沉淀记忆
```

PDF 导出保留为“留档动作”，不是主要阅读入口。

## 决策队列

原“待我确认/确认中心”全部保留，前台语言升级为“决策队列”。

必须继续后端强制：

- 发布 Listing
- 改价
- 改库存
- 修改政策
- 退款
- 广告预算
- 采购付款
- 地址写入
- 敏感客服承诺
- OAuth/高权限授权

卡片只说人话：

```text
AI 想继续做什么
为什么需要你确认
不确认会怎样
确认后会发生什么
是否写入真实平台
```

当前状态必须继续显示：

```text
真实平台写入：关闭
```

## 设置

设置不是垃圾桶，而是所有“不需要每天盯着，但必须安全可查”的后台能力入口。

保留：

- eBay 连接
- eBay 官方数据包和六类资源
- 数据源健康
- 1688 / 货源接口
- 物流接口
- 费用 / 广告授权
- eBay 三类业务政策
- 模型设置 / BYOK
- 团队权限
- 商家记忆规则
- secret_ref 状态
- 备份、监控、readiness 只给管理员看

## 自动客服和物流

自动客服不能删。它从主导航降级为“今日经营异常入口 + 设置二级页”，但业务能力保留。

保留逻辑：

```text
产品档案
-> FAQ
-> 物流承诺边界
-> 普通问题自动草稿/低风险回复
-> 退款/补偿/差评/纠纷/明确到货承诺进决策队列
```

当前阶段不要宣传“全自动客服”。应说：

```text
普通问题 AI 先起草；高风险回复必须确认。
```

## 批量铺货

批量铺货保留，但定位要从“一键铺货”改为“批量前质检”。

正确流程：

```text
货源池 / 市场机会
-> AI 初筛
-> 去掉侵权、低利润、履约不稳、素材不足、规格不清
-> 分组
-> 批量生成草稿
-> 抽检
-> 分批确认
-> 回流 Listing 工厂和素材工坊
```

它适合已有店铺、多店铺、有经验商家。新手默认先跑一个商品项目。

## 底层 Agents 归位

前台不展示一堆 Agent，但底层必须完整保留：

```text
AI CEO Orchestrator
Market Agent
Finance / Supply Agent
Product Listing Agent
Asset / Media Agent
Image Agent
Video Agent
Customer Service Agent
IP / Compliance Agent
Evidence Agent
Memory Agent
Confirmation Agent
Audit Agent
```

原来的“市场、刊登、素材、客服、财务、确认”工作记录不是丢掉，而是汇总进 AI CEO 汇报和项目时间线。

## 后端真实能力对应

已经有支撑的后端能力：

- 用户、公司、店铺、团队权限
- stores
- secret_refs
- platform connections
- eBay OAuth 只读计划与 callback
- eBay 只读数据包
- tasks
- queue_jobs
- worker
- reports
- confirmations
- execution_results
- audit_logs
- merchant_memory
- model providers catalog
- BYOK model api-key secret_ref
- model value rehearsal
- provider job contracts
- backup/monitoring/readiness gates

还没有完全产品闭环的能力：

- live model-backed Market Report / Listing Package 价值证明
- live 图片/视频 provider 生产级接入
- asset manifest 入库和素材来源审计 UI
- public/eBay/1688 批量市场采集的合规生产链路
- 客服自动发送真实写入
- 真实 eBay 写入
- billing
- 正式域名 callback

## 当前最优落地顺序

不要重做全部页面。先按“保留旧能力 + 对齐新版主导航”做四步：

1. **信息架构归位**
   - 左侧主导航改成：今日经营、Listing 工厂、素材工坊、AI CEO 汇报、决策队列、设置。
   - 旧功能不删除，全部挂到对应入口。

2. **真实流程优先**
   - 今日经营展示现有 eBay packet、六类资源、BYOK 状态、model_value_proof blocker。
   - Listing 工厂优先接 live model-backed Listing Package。
   - 素材工坊先读取 Listing Package 的图片/视频需求，不先做孤立画图工具。

3. **素材标准回归核心**
   - 素材工坊保留流程导入和独立上传两条线。
   - 图片/视频输出必须有 asset manifest、来源、实物一致性和风险确认。

4. **工作记录和记忆闭环**
   - Market Report、Listing Package、Asset Brief、客服档案、确认项全部写入 AI CEO 汇报。
   - 重要商家偏好和规则写入 merchant_memory。

## 不能再漏的旧功能清单

后续任何工作流设计都必须检查这些项：

- 素材工坊
- 作图
- 视频
- 详情页长图
- 口播脚本
- 素材真实性
- 批量铺货
- 自动客服
- 订单/物流异常
- 货源/1688
- 费用/广告
- eBay 三类业务政策
- 数据源健康
- BYOK 模型设置
- 商家长期记忆
- 团队权限
- 审计日志
- 确认中心后端强制

## 最终判断

新版不是替换原 SaaS，而是把原 SaaS 重新组织成：

```text
今日经营调度
-> Listing 工厂生产上架包
-> 素材工坊生产图片/视频/详情页
-> AI CEO 汇报沉淀报告和证据
-> 决策队列拦住高风险动作
-> 设置管理连接、模型、记忆、权限和数据源
```

这套结构保留原先所有关键能力，同时降低普通商家的复杂感。
