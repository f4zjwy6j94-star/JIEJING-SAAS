#!/usr/bin/env python3
"""Ensure AI market research suggestions never become confirmed eBay facts."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import (  # noqa: E402
    _ai_ceo_listing_handoff_fields,
    normalize_merchant_product_fact_packet,
)


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "function saasListingSafeMaterialValue" in app_js, "missing frontend material fact guard"
    assert "function saasListingSafeItemSpecifics" in app_js, "missing final item specifics guard"
    assert "materialValue ? `Material: ${materialValue}` : \"Material: 待补\"" in app_js
    assert 'return material ? `Material: ${material}` : "Material: 待补"' in app_js
    assert "saasListingSafeItemSpecifics(handoffFields.item_specifics" in app_js
    assert "merchant_product_fact_packet: merchantProductFactPacket" in app_js
    assert "applySaasMerchantProductFactPacketToDraft(importedDraft, handoffFields.merchant_product_fact_packet)" in app_js
    assert "explicitUnknownFacts.forEach((key) => delete derivedSuggestions[key])" not in app_js
    assert "const retainedDerivedSuggestions" in app_js
    assert "collected.explicitUnknownFacts.forEach((key) => {" in app_js
    assert "delete retainedSourceConfirmedFacts[key]" in app_js
    assert "delete retainedDerivedSuggestions[key]" in app_js
    assert '["ai_suggested", "vision_suggested"].includes(origin.state)' in app_js
    assert 'data-saas-action="confirm-product-fact-suggestion"' in app_js
    assert 'if (field.dataset.productFactConfirmed !== "true")' in app_js
    assert '["ai_suggested", "vision_suggested"].includes(originState)' in app_js
    assert "模拟演练资料" in app_js
    assert "simulation_only: state.saasListingComposerDraft?.merchant_product_fact_packet?.simulation_only === true" in app_js
    assert '["merchant_owned_product_confirmed", "自有商品归属确认"' in app_js
    assert 'if (key === "merchant_owned_product_confirmed") return value === true;' in app_js
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

    incense_message = (
        "这是我的真实供货商品，请新建独立商品项目和捷境内部待核对 Listing。"
        "货源：https://qr.1688.com/s/FqVegjLr；货号 JC2023041300002。"
        "已知事实：禅意佛手托莲花倒流香炉；约16.2×7.7×17.9cm；净重451g，不是包装重量；"
        "产地福建德化，不是eBay实际发货地；纸盒安全包装；工艺‘半手工半机械’和‘Handmade’冲突；"
        "东南亚禅意风格；材质‘树脂’和‘紫砂’冲突，必须待确认。"
        "不要上传、复用或发布任何原始图片；SKU、售价、库存、实际Item location、包装重量、材质继续阻断。"
    )
    incense_fields = _ai_ceo_listing_handoff_fields(
        product="禅意佛手托莲花倒流香炉",
        message=incense_message,
        answer=(
            "商品：禅意佛手托莲花倒流香炉\n"
            "货源：https://qr.1688.com/s/FqVegjLr\n"
            "商品尺寸：16.2 × 7.7 × 17.9 cm\n"
            "净重：451 g，不是包装重量\n"
            "包装：纸盒安全包装\n"
            "不要上传、复用或发布任何原始图片。"
        ),
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_1",
            "name": "禅意佛手托莲花倒流香炉",
            "score": 88,
            "selected": True,
        },
        product_candidates=[],
    )
    assert incense_fields["image_requirements"]["imageUrls"] == [], incense_fields
    assert incense_fields["item_specifics"]["Type"] == "待补", incense_fields
    logistics = incense_fields["logistics_requirements"]
    assert logistics["package_weight_g"] == "", logistics
    assert logistics["package_length_cm"] == "", logistics
    assert logistics["package_width_cm"] == "", logistics
    assert logistics["package_height_cm"] == "", logistics
    packet = incense_fields["merchant_product_fact_packet"]
    merchant_facts = packet["merchant_confirmed_facts"]
    assert merchant_facts["source_url"] == "https://qr.1688.com/s/FqVegjLr", packet
    assert merchant_facts["supplier_item_number"] == "JC2023041300002", packet
    assert merchant_facts["product_dimensions_cm"] == "16.2 x 7.7 x 17.9", packet
    assert merchant_facts["net_weight_g"] == "451", packet
    assert merchant_facts["product_origin"] == "福建德化", packet
    assert merchant_facts["packaging_type"] == "纸盒安全包装", packet
    assert merchant_facts["style"] == "东南亚禅意", packet
    assert "material" not in merchant_facts, packet
    assert "craft" not in merchant_facts, packet
    conflicts = {item["field"] for item in packet["fact_conflicts"]}
    assert {"material", "craft"}.issubset(conflicts), packet

    rehearsal_message = (
        "第二轮无货源模拟演练：请新建独立商品项目。"
        "可以生成一组明确标记为模拟演练的商品规格，用于测试 Listing 与素材流程；"
        "不得保存 eBay 草稿、公开发布或写入 eBay。"
    )
    rehearsal_answer = (
        "最终候选：复古黄铜书签（做旧工艺）\n"
        "SKU（演练用）：JJ-BOOKMARK-DRILL20260828-01\n"
        "| 字段 | 模拟演练值 |\n"
        "|---|---|\n"
        "| 品牌 | Unbranded |\n"
        "| 材质 | 做旧黄铜 |\n"
        "| 商品尺寸 | 12 x 3 x 0.1 cm |\n"
        "| 净重 | 18 g |\n"
        "| 包装重量 | 30 g |\n"
        "| 包装尺寸 | 15 x 5 x 0.5 cm |\n"
        "| 商品产地 | 中国 |\n"
        "| 单件成本 | 1.2 USD |\n"
        "| 建议售价 | 9.99 USD |\n"
        "| 建议库存 | 50 |\n"
        "| 实际 Item location | 待补（虚拟仓不可用） |\n"
    )
    rehearsal_fields = _ai_ceo_listing_handoff_fields(
        product="复古黄铜书签（做旧工艺）",
        message=rehearsal_message,
        answer=rehearsal_answer,
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_bookmark",
            "name": "复古黄铜书签（做旧工艺）",
            "score": 86,
            "selected": True,
        },
        product_candidates=[],
    )
    rehearsal_packet = rehearsal_fields["merchant_product_fact_packet"]
    assert rehearsal_packet["simulation_only"] is True, rehearsal_packet
    assert rehearsal_packet["fact_scope"] == "simulation_rehearsal", rehearsal_packet
    suggestions = rehearsal_packet["derived_listing_suggestions"]
    expected_suggestions = {
        "product_name": "复古黄铜书签（做旧工艺）",
        "sku": "JJ-BOOKMARK-DRILL20260828-01",
        "brand": "Unbranded",
        "material": "做旧黄铜",
        "product_dimensions_cm": "12 x 3 x 0.1",
        "net_weight_g": "18",
        "package_weight_g": "30",
        "package_length_cm": "15",
        "package_width_cm": "5",
        "package_height_cm": "0.5",
        "product_origin": "中国",
        "unit_cost": "1.2",
        "selling_price": "9.99",
        "currency": "USD",
        "quantity": "50",
    }
    for key, value in expected_suggestions.items():
        assert suggestions.get(key) == value, (key, suggestions, rehearsal_packet)
    assert "item_location" not in suggestions, suggestions
    assert not rehearsal_packet["source_confirmed_facts"], rehearsal_packet
    assert set(rehearsal_packet["merchant_confirmed_facts"]) == {"product_name"}, rehearsal_packet
    assert "sku" in rehearsal_packet["unknown_facts"], rehearsal_packet
    assert "simulation_only_product_facts" in rehearsal_packet["blocked_by"], rehearsal_packet
    assert rehearsal_packet["listing_readiness"]["ready_for_real_publish"] is False, rehearsal_packet

    ordinary_fields = _ai_ceo_listing_handoff_fields(
        product="复古黄铜书签（做旧工艺）",
        message="请调研这个商品并生成 Listing 建议。",
        answer=rehearsal_answer,
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_bookmark",
            "name": "复古黄铜书签（做旧工艺）",
            "score": 86,
            "selected": True,
        },
        product_candidates=[],
    )
    assert ordinary_fields["merchant_product_fact_packet"]["derived_listing_suggestions"] == {}, ordinary_fields

    unconfirmed_owned = normalize_merchant_product_fact_packet(
        {
            "merchant_confirmed_facts": {
                "product_name": "Merchant-owned sample",
                "merchant_owned_product_confirmed": False,
            }
        },
        source="authenticated_merchant_request",
    )
    assert unconfirmed_owned["source_mode"] == "source_missing", unconfirmed_owned
    assert "merchant_product_source_unconfirmed" in unconfirmed_owned["blocked_by"], unconfirmed_owned
    confirmed_owned = normalize_merchant_product_fact_packet(
        {
            "merchant_confirmed_facts": {
                "product_name": "Merchant-owned sample",
                "merchant_owned_product_confirmed": True,
            }
        },
        source="authenticated_merchant_request",
    )
    assert confirmed_owned["source_mode"] == "merchant_owned_product", confirmed_owned
    assert confirmed_owned["merchant_confirmed_facts"]["merchant_owned_product_confirmed"] is True, confirmed_owned

    inline_rehearsal_message = (
        "继续当前复古黄铜书签（做旧工艺）模拟演练项目，不新建重复项目、商品、SKU 或 Listing。"
        "品牌 Unbranded、材质 做旧黄铜、商品尺寸 12 x 3 x 0.1 cm、净重 18 g、"
        "包装重量 30 g、包装尺寸 15 x 5 x 0.5 cm、商品产地 中国、单件成本 1.2 USD、"
        "建议售价 9.99 USD、建议库存 50、SKU JJ-BOOKMARK-DRILL20260828-01、商品状态 NEW。"
        "实际 Item location 继续待补。以上仅为内部模拟演练资料，不得保存 eBay 草稿、公开发布或写入 eBay。"
    )
    inline_fields = _ai_ceo_listing_handoff_fields(
        product="复古黄铜书签（做旧工艺）",
        message=inline_rehearsal_message,
        answer=(
            "### 继续当前复古黄铜书签（做旧工艺）受控处理演练项目\n"
            "收到，本轮继续现有项目，不新建重复项目。\n"
            "### 受控处理演练规格\n|"
        ),
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_bookmark",
            "name": "复古黄铜书签（做旧工艺）",
            "score": 86,
            "selected": True,
        },
        product_candidates=[],
    )
    inline_packet = inline_fields["merchant_product_fact_packet"]
    assert inline_packet["simulation_only"] is True, inline_packet
    assert set(inline_packet["merchant_confirmed_facts"]) == {"product_name"}, inline_packet
    inline_suggestions = inline_packet["derived_listing_suggestions"]
    for key, value in expected_suggestions.items():
        assert inline_suggestions.get(key) == value, (key, inline_suggestions, inline_packet)
    assert "item_location" not in inline_suggestions, inline_suggestions
    assert inline_suggestions["product_origin"] == "中国", inline_suggestions

    certificate_gap_fields = _ai_ceo_listing_handoff_fields(
        product="复古黄铜书签（做旧工艺）",
        message="请整理当前商品 Listing，但不编造缺失资料。",
        answer=(
            "内部 Listing 草稿已建立。\n"
            "待补字段：材质证书、包装实拍、实际发货地、真实采购成本、最终售价、库存数量。\n"
            "这些字段仍需商家确认。"
        ),
        source_records=[],
        selected_candidate={
            "candidate_id": "candidate_bookmark",
            "name": "复古黄铜书签（做旧工艺）",
            "score": 86,
            "selected": True,
        },
        product_candidates=[],
    )
    assert certificate_gap_fields["item_specifics"]["Material"] == "待补", certificate_gap_fields

    api_server = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    assert 'if body.get("simulation_only") is True:' in api_server
    assert "simulation_only_listing_cannot_create_ebay_confirmation" in api_server
    assert "simulation_only_listing_cannot_execute_ebay_write" in api_server
    assert 'confirmation_item.get("simulation_only") is True' in api_server
    print("PASS jiejing_ai_ceo_listing_fact_boundary")


if __name__ == "__main__":
    main()
