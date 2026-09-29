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
        for forbidden in [
            "function saasReadinessServiceIncident",
            "function saasReadinessMerchantStatus",
            "function renderSaasReadinessIncidentStrip",
            'data-saas-readiness-incident="database"',
            "function renderSaasMerchantProjectStatusStrip",
            "mountSaasMerchantProjectStatusStrip",
            'data-merchant-project-status="merchant_project_status_v1"',
        ]:
            if forbidden in app_js:
                return fail(f"merchant surface still exposes internal readiness incident UI: {forbidden}")
        for needle, label in [
            ("function refreshSaasMerchantProjectStatus", "backend project status refresh"),
            ("function commitSaasActiveListingProjectContext", "current project continuity"),
            ("function syncSaasProjectRoute", "current project route"),
            ("function saasSellerOnboardingGuidance", "seller onboarding guidance mapper"),
            ("完成 eBay 卖家注册", "precise seller registration guidance"),
            ("无需重新授权", "no repeat OAuth guidance"),
            ("在 Seller Hub 启用 Business Policies", "business policy setup guidance"),
            ("data-saas-seller-onboarding", "seller onboarding UI marker"),
        ]:
            require(app_js, needle, label)
    except AssertionError as exc:
        return fail(str(exc))

    print("PASS jiejing_readiness_incident_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
