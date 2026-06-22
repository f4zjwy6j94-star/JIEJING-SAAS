#!/usr/bin/env python3
"""Guard the workflow UI against drifting away from the current Jiejing direction."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


WORKFLOW_FUNCTIONS = [
    "saasWorkflowStageRows",
    "saasWorkflowCapabilityCardsMarkup",
    "renderSaasWorkflowCenter",
    "saasMerchantWorkflowTemplateRoles",
    "renderSaasMerchantWorkflowTemplatePanel",
    "saasEbaySkillPackRows",
    "renderSaasEbaySkillPackCenter",
]


REQUIRED_MARKERS = [
    "AI CEO 四种路由",
    "直接回答",
    "eBay 经营任务",
    "实时数据",
    "等待确认",
    "发布体检报告",
    "类目、item specifics、图片、VeRO/IP、禁售词、GPSR/法规字段、库存位置、business policy、卖家额度、预计费用和利润",
    "费用利润大脑",
    "贡献毛利",
    "发布后驾驶舱",
    "1 小时、24 小时、7 天",
    "失败知识库",
    "可信来源",
    "记住这个规则",
    "决策中心",
]


FORBIDDEN_MARKERS = [
    "通用智能体玩具",
    "自由创建任意 Agent",
    "泛 Agent",
    "BYOK ready",
    "等待 BYOK",
    "模型 key",
    "live model value proof",
    "等待 live 输出",
    "live 模型",
    "倒流香炉",
    "Backflow",
]


def function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    next_match = re.search(r"\nfunction\s+\w+\(", source[start + len(marker) :])
    if not next_match:
        return source[start:]
    end = start + len(marker) + next_match.start()
    return source[start:end]


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    workflow_scope = "\n".join(function_scope(app_js, name) for name in WORKFLOW_FUNCTIONS)

    for marker in REQUIRED_MARKERS:
        if marker not in workflow_scope:
            raise AssertionError(f"workflow direction marker missing: {marker}")

    for marker in FORBIDDEN_MARKERS:
        if marker in workflow_scope:
            raise AssertionError(f"workflow still leaks stale direction marker: {marker}")

    for skill_key in [
        "publish_health_report",
        "gpsr_regulatory",
        "post_publish_cockpit",
        "failure_knowledge_base",
        "trusted_source_ui",
        "merchant_rule_memory",
    ]:
        if skill_key not in workflow_scope:
            raise AssertionError(f"missing eBay operating skill pack: {skill_key}")

    print("JIEJING_WORKFLOW_DIRECTION_GUARD_OK")


if __name__ == "__main__":
    main()
