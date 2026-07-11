#!/usr/bin/env python3
"""Keep the merchant Listing surface focused on one four-step path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def main() -> None:
    source = (ROOT / "app.js").read_text(encoding="utf-8")
    primary = function_block(source, "renderSaasListingNextActionPanel", "renderSaasListingWorkflowProofPanel")
    advanced = function_block(source, "renderSaasListingAdvancedWorkDetails", "renderSaasListingComposerWorkspace")
    workspace = function_block(source, "renderSaasListingComposerWorkspace", "renderSaasListingMinimalWorkspace")

    assert 'data-listing-primary-flow="product-facts_draft_assets_confirmation_v1"' in primary
    for label in ("已选商品", "补齐发布资料", "素材工坊", "确认中心"):
        assert label in primary, label
    assert 'data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"' in advanced
    for detail in (
        "renderSaasListingWorkflowProofPanel",
        "renderSaasListingOpportunityPanel",
        "renderSaasListingEbayFieldCoveragePanel",
        "renderSaasListingPreflightBridgePanel",
        "renderSaasListingPublishFeedbackPanel",
        "renderSaasListingGapAndRiskPanel",
    ):
        assert detail in advanced, detail
        assert detail not in workspace, f"{detail} must not clutter the default Listing surface"
    assert "renderSaasListingNextActionPanel" in workspace
    assert "renderSaasListingAdvancedWorkDetails" in workspace
    print("PASS jiejing_listing_progressive_disclosure")


if __name__ == "__main__":
    main()
