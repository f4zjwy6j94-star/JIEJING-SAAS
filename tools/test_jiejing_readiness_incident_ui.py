#!/usr/bin/env python3
"""Regression checks for merchant-safe readiness incident UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL jiejing_readiness_incident_ui: {message}")
    return 1


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    try:
        for needle, label in [
            ("function saasReadinessServiceIncident", "readiness incident detector"),
            ("function saasReadinessMerchantStatus", "merchant status mapper"),
            ("function renderSaasReadinessIncidentStrip", "incident strip renderer"),
            ('data-saas-readiness-incident="database"', "database incident marker"),
            ('label: "系统维护"', "merchant-safe incident label"),
            ('title: "平台连接正在恢复"', "merchant-safe incident title"),
            ("不要重复授权店铺，也不要重新填写 AI 连接信息。", "no repeat store authorization or AI connection guidance"),
            ('primaryAction: "refresh"', "incident refresh action"),
            ("renderSaasReadinessIncidentStrip(readiness)", "truth panel incident placement"),
            ("function saasSellerOnboardingGuidance", "seller onboarding guidance mapper"),
            ("完成 eBay 卖家注册", "precise seller registration guidance"),
            ("无需重新授权", "no repeat OAuth guidance"),
            ("在 Seller Hub 启用 Business Policies", "business policy setup guidance"),
            ("data-saas-seller-onboarding", "seller onboarding UI marker"),
        ]:
            require(app_js, needle, label)

        next_action_start = app_js.index("function saasMerchantNextAction")
        next_action_end = app_js.index("function saasCockpitLaunchGateSummary", next_action_start)
        next_action_body = app_js[next_action_start:next_action_end]
        incident_index = next_action_body.index("readinessStatus.incident")
        login_index = next_action_body.index("!state.saasConnected")
        if incident_index > login_index:
            return fail("readiness incident must take precedence over normal login/eBay workflow prompts")

        launch_start = app_js.index("function saasCockpitLaunchGateSummary")
        launch_end = app_js.index("function saasCockpitPublishSummary", launch_start)
        launch_body = app_js[launch_start:launch_end]
        require(launch_body, "saasReadinessMerchantStatus(readiness)", "launch summary merchant mapper")
        for forbidden in ["billing=${provider}", "eBay refresh proof", "customers=${Boolean", "基础 readiness 未通过"]:
            if forbidden in launch_body:
                return fail(f"launch summary still exposes internal wording: {forbidden}")
    except AssertionError as exc:
        return fail(str(exc))

    print("PASS jiejing_readiness_incident_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
