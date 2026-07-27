#!/usr/bin/env python3
"""Keep market-research rationale out of buyer-visible Listing copy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"\nfunction {next_name}", start)
    return source[start:end]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    candidate_description = function_body(
        app_js,
        "saasListingDescriptionFromCandidate",
        "saasListingEbayTitleFromProduct",
    )
    assert 'return "";' in candidate_description, candidate_description
    for internal_phrase in ("推荐理由", "主要风险", "发布前必须补齐"):
        assert internal_phrase not in candidate_description, candidate_description

    chat_import = function_body(
        app_js,
        "saasListingDraftFromAiCeoMarketTurn",
        "sanitizeSaasListingWorkflowField",
    )
    assert 'description: ""' in chat_import, chat_import
    assert 'selling_points: ""' in chat_import, chat_import
    assert "const ebayTitle = saasListingEbayTitleFromProduct(product);" in chat_import, chat_import
    assert "title: ebayTitle" in chat_import.split("fields:", 1)[1], chat_import
    assert "saasListingDescriptionFromCandidate" not in chat_import, chat_import
    assert "selectedCandidate.reasons.join" not in chat_import, chat_import

    bulk_import = function_body(
        app_js,
        "saasBulkCandidateToListingDraft",
        "renderSaasBulkSourceRealityPanel",
    )
    assert 'description: ""' in bulk_import, bulk_import
    assert 'selling_points: ""' in bulk_import, bulk_import
    assert "candidate.reasons || []" not in bulk_import.split("fields:", 1)[1], bulk_import

    catalog_import = function_body(
        app_js,
        "saasListingComposerDraftFromCatalogDraft",
        "saasListingMerchantSourceLabel",
    )
    assert 'sourceType === "bulk_handoff" ? "" : reportReasons.join("\\n")' in catalog_import, catalog_import
    assert 'sourceType === "bulk_handoff" ? "" : description' in catalog_import, catalog_import

    publish_prefill = function_body(
        app_js,
        "saasPublishIntakePrefillValues",
        "renderSaasPublishInputField",
    )
    for locked_source in ("ai_ceo_market_chat", "ai_ceo_market_report", "bulk_handoff"):
        assert f'"{locked_source}"' in publish_prefill, publish_prefill
    assert "buyerCopyRequiresMerchantFacts ? \"\" : clean" in publish_prefill, publish_prefill
    assert "|| clean," not in publish_prefill, publish_prefill

    print("PASS jiejing_ai_ceo_listing_buyer_copy_boundary")


if __name__ == "__main__":
    main()
