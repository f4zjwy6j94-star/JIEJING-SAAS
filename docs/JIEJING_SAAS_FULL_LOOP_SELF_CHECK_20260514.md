# 捷境 SaaS 官网、向导、工作流与 Runtime 自检报告

日期：2026-05-14  
范围：官网主页、登录/向导、AI CEO 工作台、产品刊登、素材工坊、批量铺货、AI 汇报、待我确认、自动客服、连接账号、Jiejing Runtime 本地执行底座。

## 1. 本次结论

当前版本已达到：

- 网页演示闭环：100%（按本地演示合同，不代表真实 eBay 写入）。
- Runtime 后路底座：100%（按本地 Runtime MVP 合同，不代表可商用生产）。
- 生产级真实 SaaS：仍未达到 100%，因为还缺云端后端、多用户权限、密钥保险柜、真实 OAuth 执行层、真实图片/视频生成、真实 eBay 写入和真实物流/货源接口。

不能虚报的边界：

- 当前可以完整模拟“商家给目标 -> AI CEO 拆任务 -> 市场报告 -> 货源资料 -> 产品刊登 -> 素材任务 -> 客服学习 -> 财务复核 -> 确认中心 -> ExecutionService 记录执行交接”。
- 当前不会真实发布 eBay、不会付款、不会退款、不会开广告、不会改店铺政策。

## 2. eBay 真实流程对齐检查

已按 eBay 官方文档核对当前产品刊登主骨架。

正式发布一个 Inventory API offer 前，必须有：

- inventory location / merchantLocationKey。
- inventory item：SKU、condition、title、description、aspects、imageUrls 等。
- offer：availableQuantity、marketplaceId、format、categoryId、listingPolicies、merchantLocationKey、pricingSummary.price、listingDuration 等。
- 三类 business policies：paymentPolicyId、returnPolicyId、fulfillmentPolicyId。
- 类目动态 Item Specifics：必须按 Taxonomy API 的 getItemAspectsForCategory 返回值动态校验。

当前 SaaS 已覆盖：

- 产品刊登固定骨架。
- 类目动态字段说明。
- 三类店铺政策说明。
- 物流报价状态。
- 发布前缺口。
- 确认中心拦截真实发布、采购付款、改价、退款、广告、政策改动和敏感客服承诺。

当前仍需真实接入后补齐：

- eBay Taxonomy API 实时返回类目必填项。
- eBay Account API 读取真实 payment / return / fulfillment policies。
- inventory location / merchantLocationKey 的真实读取或创建。
- publishOffer / Trading API 发布前的后端执行服务。

## 3. 本次跑的 SaaS 模拟任务

测试商品：

`Stainless Steel Vacuum Insulated Water Bottle 20oz`

测试目标：

从 AI CEO 接目标开始，按捷境 SaaS 流程跑一条 eBay 测试链路。

Runtime run_id：

`saas-selfcheck-stainless-bottle-20260514`

初始结果：

- 任务数：11。
- 确认项：9。
- 运行状态：completed_with_blocks。
- 真实执行：全部 false。
- 原因：系统正确拦住了三类政策和发布相关缺口。

补齐演示刊登资料后：

- 刊登包校验：ready_for_confirmation_review。
- Runtime 校验：17 项 ready，0 项 blocked。
- 执行服务测试：确认真实发布动作后，ExecutionService 返回 `simulated_no_platform_write`。
- 结论：模拟闭环跑通，且没有真实写入 eBay。

## 4. 本次发现并修复的隐患

### 4.1 手动货源资料保存后仍提示缺重量

问题：

商家填了 `200g`，前端仍提示重量缺失。

原因：

手动资料表单没有字段标记，保存逻辑没有读取输入值，提示文案也是固定写死的。

修复：

- 给手动资料表单增加字段标记。
- 保存时读取包裹重量、包装尺寸、代发规则。
- 按实际缺口生成提示。
- 产品刊登的物流报价卡同步识别“重量已记录”。

### 4.2 前台 Runtime 面板暴露内部底座名称

问题：

商家可见区域出现内部执行底座相关名称。

修复：

- 前台显示改为“内部执行 SOP”“执行底座交接”“内部执行底座”。
- Runtime 返回的来源、报告正文和确认项在前端展示前做公开化处理。

### 4.3 Runtime 确认项对商家不够友好

问题：

Runtime 返回的确认项标题和原因偏工程化、英文多。

修复：

- publish_listing 显示为“确认真实发布”。
- procurement_payment 显示为“确认采购付款”。
- policy_edit 显示为“确认店铺业务政策”。
- change_price 显示为“确认价格策略”。
- sensitive_buyer_commitment 显示为“确认敏感客服承诺”。

## 5. 自动化测试结果

已通过：

- `node --check app.js`
- `python -m compileall jiejing_runtime tools`
- `test_jiejing_asset_manifest_validator.py`
- `test_jiejing_ceo_final_report_validator.py`
- `test_jiejing_confirmation_package_validator.py`
- `test_jiejing_cross_platform_reference_probe.py`
- `test_jiejing_customer_learning_validator.py`
- `test_jiejing_ebay_read_only_probe.py`
- `test_jiejing_finance_review_validator.py`
- `test_jiejing_listing_package_validator.py`
- `test_jiejing_logistics_estimate_probe.py`
- `test_jiejing_public_search_probe.py`
- `test_jiejing_runtime_knowledge.py`
- `test_jiejing_runtime_mvp.py`
- `test_jiejing_runtime_role_capabilities.py`
- `test_jiejing_runtime_workflow.py`
- `test_jiejing_sourcing_availability_probe.py`

结果：

`FINAL_ALL_TESTS_PASS`

## 6. 当前真实进度

按“本地演示合同”：

- 官网 -> 向导 -> 工作流：100% 可演示。
- SaaS 前端 -> Runtime API：100% 可演示。
- Runtime 任务拆分、报告合同、确认项、执行服务模拟：100% 可演示。

按“生产商用合同”：

- 前端产品体验：约 88%-92%。
- Runtime 架构底座：约 88%-92%。
- 替代内部执行底座的真实 Agent 能力：约 35%-40%。
- 正式 SaaS 后端：约 60%-65%。
- 真实 eBay 自动化闭环：约 30%-35%。
- 商业化生产级：约 25%。

## 7. 下一步建议

下一步不要继续堆页面，而是做三件事：

1. 把 Runtime API 输出真正接进所有前端模块，不再只作为顶部状态卡。
2. 做一个后端最小壳：用户、店铺、任务、报告、确认项、审计日志。
3. 先接 eBay 只读：店铺资料、Listing、订单、费用、三类政策、类目校验；发布写入继续保持关闭。

这三件事做完，捷境才会从“高保真演示 + 本地 Runtime”进入“正式 SaaS 内测骨架”。
