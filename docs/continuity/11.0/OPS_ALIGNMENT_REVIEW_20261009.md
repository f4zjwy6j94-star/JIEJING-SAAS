# OPS与首版交付状态对齐：只读评估

日期2026-10-09，负责端本地10.0。用户询问是否需要对齐/修复，未要求本轮直接修复或部署。开工status/receive正确干净且equal，起点 `7e294872267a9e8c6e47fd89869a70684d539453`。

## 结论

需要定点对齐。经营数据页上一轮已读取真实聚合数，不能说整个后台失效；本轮确认部分证据卡片取数与状态显示有问题。原约定首版8/8交付属于历史完成范围，不据本轮把整个项目重开，也不能扩张成当前所有状态全部通过。

## 实际证据与优先级

1. **优先修状态与健康字段。** 本机Chrome“运行与安全”实际显示运行健康=`private_beta_ready_public_launch_blocked`，DOM类却是`ops-reliability-item is-ready`，公网与Worker为unknown。`assets/jiejing-ops-panels.js:8`先匹配ready再匹配blocked，复合字符串被判为ready；`62-64`未拿到operational_readiness时回退总对象，使上线门禁被当成运行健康。
2. **优先修备份/运行证据接线。** 实际备份、PITR、恢复演练三卡unknown。前端`57-64`预期顶层backup_recovery/database_recovery/operational_readiness；后端`jiejing_saas/owner_launch_control.py:347-394`返回evidence，相关安全摘要在`evidence.backup/operational/edge`（约1019-1045）。不能只改字段名后假装细分PITR/Worker证据已齐；须按真实安全合同接线并保留缺失/过期状态。
3. **核对上线证据来源。** 线上总门禁显示公开上线阻断，发布历史no_local_release_artifacts；复核包显示新生成时间。源码`owner_launch_control.py:1541-1566,1622-1678`仅查output下旧staging包和staging-patch-backups，不是production active release权威读回。“没找到本地包”不等于“从没部署”。应分开首版交付、当前已部署版本、当前健康/收费条件、动作授权，展示证据时间与具体原因。尚未核实当前总门禁的全部真实阻断项，不能称全部是假告警。
4. **统计口径修正/说明。** 参见既有OPS_ANALYTICS_READONLY_20261009.md：流量北京时间与订单/任务UTC起点不同，总览UV和趋势事件集合不同，累计商家和期间新增混在同一总览。应统一可比窗口和标签，保留历史数据。
5. **运营增强，不等于故障。** 现无抖音来源归因、人工自测区分不完整；可在另获实施授权后用最少必要的非敏感来源字段和内部流量标记补齐，不自动接第三方追踪或增加费用。模型高延迟/缺成本记录独立评估，不清告警来制造正常。

## 本地复现（非生产调用）

Node vm只读装载现有OPS纯渲染模块，以合成control传入顶层blocked总状态及evidence内ready摘要；命令退出0，输出：blocked_status_has_ready_style=true、runtime_uses_overall_gate=true、runtime_unknown_cards=2、backup_unknown_cards=3。这是确认显示逻辑问题的复现，不是修复通过，也不证明真实生产备份/Worker健康。

## 未验证项与本轮边界

Chrome直接打开`https://app.jiejing.shop/readiness/product-saas`返回准确错误`net::ERR_BLOCKED_BY_CLIENT`。未换浏览器、走终端代取或规避限制；未获得本轮公开production_ready/can_accept_real_customers/public_charging_allowed读回。因此当前精确上线阻断原因留待核对，既不以旧8/8替代新证据，也不以错位OPS卡片否定历史交付。

截图仅在 `D:/Codex-Verification/jiejing-ops-alignment-20261009/`：launch-panel.png、backup-panel.png、runtime-panel.png，不入Git。不读秘密、Cookie、原始日志或客户内容；不点支付验收、部署/恢复按钮，不改产品代码、统计数据、线上配置、安全权限、eBay或拼嘚。

下一步建议：经营者明确要求实施后，先在本地为复合状态/缺失字段/真实后端合同补回归，修OPS适配和安全证据展示，再评估统计及推广归因；单独审查发布范围，部署另确认，不为对齐清空数据/修改成功标志/重跑三品。
