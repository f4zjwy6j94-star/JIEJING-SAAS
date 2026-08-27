#!/usr/bin/env python3
"""Static contract for mature merchant Listing, media, confirmation and records."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.js").read_text(encoding="utf-8")


def scope(start_marker: str, end_marker: str) -> str:
    start = APP.index(start_marker)
    end = APP.index(end_marker, start + len(start_marker))
    return APP[start:end]


def main() -> None:
    assert "const SAAS_MERCHANT_CONFIRMATION_ACTION_LABELS = Object.freeze" in APP
    for action_type in (
        "ebay_oauth_scope_change",
        "create_ebay_inventory_location",
        "save_ebay_listing_draft",
        "publish_listing",
        "bulk_publish_listing",
        "revise_listing",
        "change_price",
        "change_inventory",
        "open_ad_campaign",
        "change_ad_budget",
        "refund",
        "partial_refund",
        "procurement_payment",
        "purchase_order",
        "cleanup_test_listing",
        "change_shipping_policy",
        "change_payment_policy",
        "change_return_policy",
        "sensitive_customer_reply",
    ):
        assert f'{action_type}: ' in APP
    assert "稍后处理" not in APP

    readiness = scope("function renderSaasPublishReadinessStrip", "function renderSaasPublishConfirmationIntakePanel")
    assert "完成度" not in readiness
    assert "${done}/${total}" not in readiness
    assert '"已填写"' in readiness and '"待补"' in readiness

    coverage = scope("function renderSaasListingEbayFieldCoveragePanel", "function renderSaasListingPreflightBridgePanel")
    assert "字段完成度" not in coverage
    assert "${coverage.score}%" not in coverage
    assert "${escapeHtml(group.done)}/${escapeHtml(group.total)}" not in coverage
    assert "已填写" in coverage and "待补资料" in coverage

    facts = scope("function renderSaasMerchantProductFactsModule", "function renderSaasListingDraftEditor")
    assert "completion_percent" not in facts
    assert "已填写" in facts and "待补" in facts

    activity = scope("function renderSaasActivityCenter", "function renderActivities")
    assert "置信度" not in activity
    assert "当前项目" in activity and "历史项目" in activity
    assert "latestSaasReportByTypes" not in activity
    assert "saasConfirmationsForDisplay" in activity
    assert "reports.find" in activity

    assert "latestSaasMediaAssetJobWithManifest({ requireCurrentProject: true })" in APP
    print("PASS jiejing_core_workflow_maturity")


if __name__ == "__main__":
    main()
