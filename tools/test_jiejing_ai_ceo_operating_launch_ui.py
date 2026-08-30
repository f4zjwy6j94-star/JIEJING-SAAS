#!/usr/bin/env python3
"""Static regression guard for AI CEO operating replies and launch-readiness UI."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    adaptive_layout_markers = [
        ".saas-ai-ceo-chatgpt-layout.has-task-context",
        ".saas-ai-ceo-task-context",
        ".saas-ai-ceo-task-context-summary",
        ".is-task-context-collapsed",
        "@media (max-width: 1100px)",
        "@media (max-width: 700px)",
    ]
    for marker in adaptive_layout_markers:
        if marker not in styles:
            return fail(f"styles.css missing adaptive AI CEO layout marker: {marker}")
    desktop_task_rule = re.search(r"\.saas-ai-ceo-chatgpt-layout\.has-task-context\s*\{([^}]+)\}", styles, re.S)
    if not desktop_task_rule or "grid-template-columns" not in desktop_task_rule.group(1):
        return fail("desktop task-context selector must define a two-column grid; browser smoke verifies the 68/32 result")

    for guard_marker in [
        "has-task-context",
        "is-task-context-collapsed",
        'body.saas-public-mvp[data-view="cockpit"]',
    ]:
        if guard_marker not in app_html:
            return fail(f"app.html startup guard missing adaptive AI CEO marker: {guard_marker}")

    required_app_markers = [
        "function saasAiCeoTurnOperatingRows",
        "function renderSaasAiCeoOperatingRowsMarkup",
        "目标",
        "计划",
        "来源",
        "风险",
        "待确认动作",
        "执行结果",
        "function renderSaasCoreModuleDiagnosticsPanel",
        "复杂状态归到设置，工作台只保留经营动作",
        "设置里查看",
        "post_publish_cockpit",
        'renderSaasPublishInputField("eBay fee", "ebay_fee"',
        'renderSaasPublishInputField("退货预留", "return_risk_reserve"',
        'renderSaasPublishInputField("汇率", "exchange_rate"',
        "function renderSaasProfitBrainPanel",
        "function renderSaasPostPublishCockpitPlan",
        "saasPostPublishCockpit",
        "function renderSaasPostPublishCockpitEvidence",
        "post_publish_cockpit_backend",
        "function renderSaasFailureKnowledgePanel",
    ]
    for marker in required_app_markers:
        if marker not in app_js:
            return fail(f"app.js missing marker: {marker}")

    required_style_markers = [
        ".saas-ai-ceo-operating-brief",
        ".saas-profit-brain-strip",
        ".saas-post-publish-plan",
        ".saas-post-publish-evidence-strip",
        ".saas-failure-knowledge-strip",
        ".saas-core-module-diagnostics-grid",
        ".saas-settings-home-hub",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing marker: {marker}")

    required_app_html_markers = [
        'rel="stylesheet" href="./styles.css',
        'data-ui-generation="premium-merchant-workbench-v1"',
        'id="view-cockpit"',
    ]
    for marker in required_app_html_markers:
        if marker not in app_html:
            return fail(f"app.html missing cockpit layout guard marker: {marker}")

    forbidden_merchant_copy = [
        "DeepSeek 负责想图，FAL 负责出图",
        "DeepSeek / BYOK 已负责素材 brief",
        "FAL • openai/gpt-image-2",
        "文字模型不是图片模型",
    ]
    for marker in forbidden_merchant_copy:
        if marker in app_js:
            return fail(f"merchant-facing UI must not expose provider explanation: {marker}")

    print("PASS jiejing_ai_ceo_operating_launch_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
