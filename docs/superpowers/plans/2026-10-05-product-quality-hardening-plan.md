# 五项产品质量加固实施计划

2026-10-05，用户已批准；基线9412cfd。不另建产品、改视觉/导航或开启真实写入。每个垂直切片先用实际接口/函数复现，再最小修复、验证。生产商家操作只经SaaS页面；本地合成HTTP测试不碰生产。

## Phase 0：现有合同发现（已完成）

读取AGENTS、当前执行索引、已批准质量审计。make-plan要求的两路只读发现确认：

- `ebay_write_adapter.py::build_publish_readiness`仅本地检查；`api_server.py` readonly_precheck在任务/确认/凭据前返回。不得暗加网络调用。
- `repository.py::normalize_merchant_product_fact_packet`（19355起）缩减来源字段；已有unknown/CAS/no-op合同必须保留。`listing_draft_generation.py::_listing_prompt_fact_packet`未带完整证据，`_validate_buyer_copy`只有有限规则，不是通用语义审查。
- `save_ai_ceo_market_research_report`对全部save_artifact使用粗market_research类型，报告保留turn_plan/semantic_dispatch；实际事实保存receipt应决定成果标签。后端历史、前端normalize和report恢复均需同步。
- 事实仅一个currency，前端成本与刊登币种混用；沿现有money/finance合同分离，不造新财务系统。

以上是代码发现，不是假定测试已通过。无生产模型或数据库调用。

## Phase 1：真实预检与可操作反馈

- 在`tools/test_jiejing_product_fact_auth_http.py::ProductFactAuthHttpTests`先增加真实隔离HTTP失败测试：已填类目/政策/位置/图片仍未平台核实；伪造verified不能变绿；四项副作用false。
- 最小修改只读readiness的状态/证据级别/下一步；保持正式执行确认边界。规格错误分别定位长宽高和单位，前端遗留重复消息去重。
- 验证HTTP、`test_jiejing_listing_confirmation_display_scope.js`和已有publish intake合同。

## Phase 2：事实、证据和币种

- 在现有fact HTTP保存/GET/CAS/no-op回归加来源摘录、证据角色、SKU与冲突追溯；有限字段归一化，不信任客户端权威标记。
- 沿已有unknown投影和冲突机制，避免旧值恢复；商家显式确认与新AI建议分层，不对遗留冲突一刀切。
- 分开采购成本币种和售价币种，明确汇率方向；缺币种或汇率不默认利润可用。跨保存、生成、表单、checkpoint复验。

## Phase 3：模型质量与成果类型

- 在原生成/重写链路增加有界语义主张审查，使用原模型/计量边界；完整事实/证据随同审查，异常闭合。既有数值、材料、安全规则保留，不能用两个关键词冒充通用理解。
- 测试未依据轻量/耐用/产地/件数与同义说法；接受有依据描述，保留旧稿/其他字段，拒绝失败不落新成果；重放不增加业务收费。
- 根据已校验计划及实际保存receipt输出明确成果kind，贯通即时响应→report→history→前端恢复。旧记录保守显示，真正研究仍是研究。
- 使用`test_jiejing_ai_ceo_semantic_http.py`现有事实更新/重放/历史恢复接缝和实际renderer，非仅改标题。

## Phase 4：恢复、隔离与商家验收

- 运行checkpoint HTTP/真实本地浏览器、登录超时、重复点击/请求重放、并发、跨租户测试；补新字段恢复与新审查失败场景。
- 渲染核对清单标签、未知/冲突/费用口径及下一步，不加新页面、不删能力。
- 审查Listing专家、商家可用性、计费、租户安全、可靠性与证据一致性。低风险同范围缺陷当批修复，外部证据缺口如实保留。

## Phase 5：发布与生产验收门槛

- 新候选冻结后syntax/secret/相关回归及完整同源precloud门禁；不得用941旧273/273替代。
- 本批发布须遵守现有动作批准、标准打包和同包dry/apply边界。未部署前不称线上已修。
- 同源后验证三个原商品至少两轮保存/刷新/跨商品字段、资产比较；不重复图片/业务模型调用，不清除simulation，不真实发布或付款。
- 完成状态按已改、已测、已部署、实页已验分列。正式收费/真实卖家闭环不能由内部测试替代。

## 执行记录

- 五项代码切片已实现，仍未部署；R无关dirty文档保留。所有代码由root统一修改，发现子代理只读结束。
- RED→GREEN覆盖：虚假平台校验状态、重复尺寸消息、资料来源摘录丢失、采购/售价混币、无向旧汇率、错误毛利显示、事实成果错标研究、语义审校拒绝/异常、旧资料无变更保存中断。前后端新增待确认来源字段不一致及新字段恢复顺序也已定位并修复。
- 局部验证：事实/预检HTTP16、语义HTTP33、checkpoint HTTP36、生成操作14、旧生成恢复13、语义审校4、文案重写14；浏览器cloud+事实UI186通过。重写HTTP整套曾40/41，唯一冷刷新续接失败已实际复现并修正，3个相关真实浏览器→HTTP场景通过；完整新源门禁仍须重跑，不能合并局部计数当作放行。
- 页面渲染已实际查看1280/919像素价格利润区域（R/output/product-quality-20261005）；明确成本/售价币种与汇率方向，保留现有视觉。生产三原商品不动，不重复图片/模型调用。
- 新审查使用同一后端计量客户端，每次成功生成新增一次有界模型复核；测试验证业务配额仍一次、实际模型请求及token照常记账。只有供应商边界夹具的语义合同证据，尚非真实DeepSeek质量效果或真实商家独立验收证明。
- 尚未完成：新冻结源完整274项门禁、正式部署审批/执行、三原商品新版本实页验收；不得声称已达付费推广或真实发布闭环。
- 第一轮冻结fe3566c完整门禁272/274，source稳定但不放行（run 1c1deb7904fe4693a59e176c8335fe1b）。发现simulation HTTP旧35字段断言及有效亏损被错误清空；后者保留原失败测试，并新增跨币种HTTP亏损/无效负成本区分，RED79420e→GREEN0e571b。事实HTTP16和原publish_evidence_preflight通过，simulation HTTP15通过（4256af）。修复后必须以新候选重新跑完整274，不能拼接上一轮272。
