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
    primary = function_block(source, "renderSaasListingWizard({", "renderSaasListingComposerWorkspace")
    advanced = function_block(source, "renderSaasListingAdvancedWorkDetails", "renderSaasListingComposerWorkspace")
    workspace = function_block(source, "renderSaasListingComposerWorkspace", "renderSaasListingMinimalWorkspace")

    assert 'data-listing-wizard-step="${step}"' in primary
    for label in ("商品资料", "Listing 内容", "商品图片", "发布检查与确认"):
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
    assert "renderSaasListingWizard" in workspace
    assert "renderSaasListingNextActionPanel" not in workspace
    assert "renderSaasListingAdvancedWorkDetails" in primary
    assert 'step === 1 ?' in primary and 'step === 2 ?' in primary and 'step === 3 ?' in primary
    print("PASS jiejing_listing_progressive_disclosure")


if __name__ == "__main__":
    main()
