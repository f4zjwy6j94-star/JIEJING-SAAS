#!/usr/bin/env python3
"""Ensure AI market research suggestions never become confirmed eBay facts."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import _ai_ceo_listing_handoff_fields  # noqa: E402


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "function saasListingSafeMaterialValue" in app_js, "missing frontend material fact guard"
    assert "function saasListingSafeItemSpecifics" in app_js, "missing final item specifics guard"
    assert "materialValue ? `Material: ${materialValue}` : \"Material: 待补\"" in app_js
    assert 'return material ? `Material: ${material}` : "Material: 待补"' in app_js
    assert "saasListingSafeItemSpecifics(handoffFields.item_specifics" in app_js
    assert "function saasListingEbayTitleFromProduct" in app_js
    assert 'const marketResearchHandoff = ["ai_ceo.market_research", "market.report"]' in app_js
    assert "selling_points: marketResearchHandoff ? [] : legacySellingPoints" in app_js
    assert 'marketResearchHandoff ? "" : fields.description_seed' in app_js
    assert "description: handoffFields.description_seed" in app_js
    assert "fields.description || draft.summary" not in app_js
    assert 'candidate_selection_contract: "candidate_switch_resets_unverified_fields_v1"' in app_js
    candidate_switch = app_js[app_js.index("function selectSaasListingMarketCandidate") : app_js.index("function renderSaasFirstRunAssuranceStrip")]
    assert 'selling_points: ""' in candidate_switch
    assert 'description: ""' in candidate_switch
    assert 'description_html: ""' in candidate_switch
    assert "function saasPublishConfirmationMatchesListingProject" in app_js
    assert "Legacy confirmations cannot be proven" in app_js
    for unsafe_phrase in ["风险", "描述", "认证", "合规", "缺口"]:
        assert unsafe_phrase in app_js[app_js.index("function saasListingSafeMaterialValue") : app_js.index("function saasListingComposerDraftFromText")]

    fields = _ai_ceo_listing_handoff_fields(
        product="硅胶折叠旅行杯",
        answer=(
            "候选商品 1：硅胶折叠旅行杯\n"
            "推荐度评分：88/100\n"
            "为什么有需求：轻小件，适合旅行收纳。\n"
            "价格带：$9.99-$13.99\n"
            "主要风险：材质、容量和食品接触声明需要供应商证明。"
        ),
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_1",
            "name": "硅胶折叠旅行杯",
            "score": 88,
            "price_band": "$9.99-$13.99",
            "selected": True,
        },
        product_candidates=[],
    )

    inventory = fields["ebay_inventory_item_draft"]
    offer = fields["ebay_offer_draft"]
    assert fields["condition"] == "", fields
    assert fields["condition_suggestion"] == "NEW", fields
    assert fields["quantity"] == "", fields
    assert inventory["condition"] == "", inventory
    assert inventory["availability"]["shipToLocationAvailability"]["quantity"] == 0, inventory
    assert offer["pricingSummary"]["price"]["value"] == "", offer
    assert offer["research_price_band"] == "$9.99-$13.99", offer
    assert fields["item_specifics"]["Brand"] == "待补", fields
    assert fields["item_specifics"]["MPN"] == "待补", fields
    assert fields["item_specifics"]["Type"].startswith("待"), fields
    assert fields["selling_points"] == [], fields
    assert fields["description_seed"] == "", fields
    assert fields["ebay_inventory_item_draft"]["product"]["description"] == "", fields
    assert fields["ebay_offer_draft"]["listingDescription"] == "", fields
    assert fields["market_rationale"], fields
    assert fields["buyer_copy_status"] == "waiting_for_merchant_product_facts", fields
    assert fields["merchant_question_contract"]["suggestions_are_not_confirmed_facts"] is True, fields
    assert fields["listing_readiness"]["ready_for_real_publish"] is False, fields
    assert any("真实可售数量" in question for question in fields["merchant_required_answers"]), fields
    assert fields["triggers_real_platform_write"] is False, fields
    assert fields["secret_exposed"] is False, fields
    print("PASS jiejing_ai_ceo_listing_fact_boundary")


if __name__ == "__main__":
    main()
