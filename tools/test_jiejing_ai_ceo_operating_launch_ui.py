#!/usr/bin/env python3
"""Static regression guard for AI CEO operating replies and launch-readiness UI."""

from __future__ import annotations

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

    required_app_markers = [
        "function saasAiCeoTurnOperatingRows",
        "function renderSaasAiCeoOperatingRowsMarkup",
        "目标",
        "计划",
        "来源",
        "风险",
        "待确认动作",
        "执行结果",
        "function renderSaasCommercialLaunchGatePanel",
        "billing_quota",
        "stable_domain_tls",
        "publish_safety_system",
        "store_sync_visibility",
        "post_publish_cockpit",
        "final_commercial_smoke",
        "name=\"ebay_fee\"",
        "name=\"return_risk_reserve\"",
        "name=\"exchange_rate\"",
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
        ".saas-commercial-launch-grid",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing marker: {marker}")

    required_app_html_markers = [
        'id="jiejing-cockpit-layout-guard"',
        "grid-template-columns: minmax(0, 1fr)",
        "saas-ai-ceo-cockpit-status",
        "saas-first-order-loop",
        "body.saas-public-mvp[data-view=\"cockpit\"] .saas-ai-ceo-composer input",
    ]
    for marker in required_app_html_markers:
        if marker not in app_html:
            return fail(f"app.html missing cockpit layout guard marker: {marker}")

    stylesheet_index = app_html.find('rel="stylesheet" href="./styles.css')
    guard_index = app_html.find('id="jiejing-cockpit-layout-guard"')
    if stylesheet_index < 0 or guard_index < 0 or guard_index < stylesheet_index:
        return fail("cockpit layout guard must load after styles.css so legacy rules cannot collapse the composer")

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
