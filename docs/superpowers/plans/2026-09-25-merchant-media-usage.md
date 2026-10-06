# 素材点明细实施与证据

基线a6b6a08已部署；原主仓8项dirty保持。本批不重复上批243门禁或生产操作。

1. 已完成：只读校准，确定现有bucket/预留/终结记录为唯一事实源；没有现成商家明细。
2. 已完成：隔离SQLite公共repository操作驱动15项回归，新增只读白名单投影；预留与终结证据配对，不修改扣点算法。
3. 已完成：只有已认证的`/billing/media-credits`显式加载usage；余额/配额调用保持轻量。前端默认折叠、商家用语及安全降级，不加导航或支付入口。
4. 已完成：接口/浏览器专项，实际1440/820截图与交互，秘密/语法/缓存检查，专业审查；证据见下。
5. 已完成：实现15文件提交177309b；主仓既有8项dirty不夹带。用户后续已承接本批发布批准，发布状态以当前执行索引为准。

设计梳理与TDD的重复逐步确认环节按用户最新自主推进指令省略；无新的产品方向决策。writing-plans未在当前可用技能中，按仓库原计划格式记录，不安装新技能或启动代理。

## 本地验证证据（2026-09-25；不是线上验收）

- TDD：先确认缺少usage报错，再实现基础投影；部分成功用例先失败，再配对实际结算与释放；缺少同公司任务编号先失败，再关联现有任务；前端缺少折叠明细先失败，再增加渲染。没有通过降低原业务门槛让测试变绿。
- `test_jiejing_merchant_media_usage.py`最终15/15，13.313秒，session54649 exit0：预留非消耗、部分成功与幂等、失败释放、到期释放不恢复余额、内部额度隔离、账号隔离、退款冻结非生图消耗、旧证据不足、终结证据缺失、其他公司bucket引用、混合内部来源、结果上限、同公司任务关联/跨公司拒绝、100条扫描与读取不修改账本。
- `test_jiejing_domestic_billing_api.py`通过：未登录401、当前公司80点占用、篡改company查询参数无法跨账号、常规quota响应不重复加载历史。
- `test_jiejing_domestic_billing_merchant_ui.py`通过（最终session30464 exit0）：真实fetch合并与渲染、展开/收起、待结算/部分成功/全量释放、空结果、局部缺测、无有效summary安全降级、恶意编号不注入DOM。
- 相关专项通过：merchant_surface_isolation、billing_entitlement_projection（11/11）、commercial_entitlements、media_credit_purchase、media_queue_setup_recovery（8/8）、saas_clean_settings_and_listing_ui、frontend_staging_config、homepage_maturity、secret_scan、两JS语法及diff检查。
- 本地合成预览（9051，网络fetch关闭）CUA实测1440×1000与820×1180。document宽分别1425/805，无横向溢出；默认折叠、展开三种结算结果、收起均成功，console error/warn为空；截图已目视。临时tab19已关闭、viewport已reset、server session76310已主动停止。未操作正式网站的支付/退款/生图。
- app.js LF规范化SHA为`6d174041fb765e0e8a63ca227e1fddf6c7e2de408c90ddd1d8056d64d45cca1a`，两HTML三个引用同步。CSS及官网主题不变。

## 主理人复核与边界

- 产品/UX：只补已有套餐页缺口，默认折叠、不恢复运行记录导航；“暂时占用”与“实际消耗”明确分开。
- 计费：沿用原账本，终结不匹配显示待核对；释放不冒充现金退款或已恢复余额。付款退款及套餐权益算法未改。
- 隔离/安全：所有关联按公司过滤，账本/bucket/提供商/内部额度原文不返回；原始异常和密钥不进入明细。只暴露白名单字段。
- 性能：最近100次图片预留有界扫描，bucket按400一批、无逐行查询；完整历史/累计消费未实现，页面明确标注截断与缺测。
- 上线：新回归已加入统一门禁；本轮未运行完整244项门禁，不能复用a6b6a08的243/243证明本批可发布。未打包、预演或部署，生产基线未改。
- 后续顺序：本批明确部署批准→干净同源候选完整门禁/打包/预演→apply→生产版本/健康/隔离与真实明细页面验收。随后才单独加固CLS探针的短暂检索延迟，不把历史故障称已永久消除。

## 发布包校正

发布前检查发现177309b遗漏了部署白名单中的新模块。原有`staging_patch_apply_contract`已能明确报错`patch apply whitelist must carry the complete SaaS Python package: jiejing_saas/media_credit_activity.py`；此前专项未包括该发布合同，不能把专项通过当成包完整。正在运行的177309b完整门禁93826已主动终止，未产生通过证据，也未打包/部署。

按TDD保留该RED，再补入新模块、明细回归、设计和实施文档共4个白名单项；两Python文件加入语法检查。扩展原发布合同，要求这些依赖恰好一次进入包、Python检查及明细门禁不漏接。合同GREEN后用新干净commit重新完整验证，不从中途拼接旧检查结果。此修正属于当前明细功能的发布完整性，不改变生产业务或监控算法。
