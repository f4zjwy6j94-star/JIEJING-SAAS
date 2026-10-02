#!/usr/bin/env python3
"""Regression checks for grounded multi-image intake in AI CEO."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.product_vision import (  # noqa: E402
    FalProductVisionClient,
    build_product_vision_fact_packet,
)


def main() -> None:
    captured: dict[str, object] = {}

    def fake_transport(*, endpoint: str, authorization: str, payload: dict, timeout_seconds: int, proxy_url: str) -> dict:
        captured.update(
            endpoint=endpoint,
            authorization=authorization,
            payload=payload,
            timeout_seconds=timeout_seconds,
            proxy_url=proxy_url,
        )
        return {
            "output": json.dumps(
                {
                    "product_name": {"value": "禅意佛手莲花倒流香炉", "confidence": 0.98, "image_indexes": [1, 2, 4]},
                    "facts": {
                        "product_dimensions_cm": {"value": "16.2 x 7.7 x 17.9", "confidence": 0.99, "image_indexes": [6]},
                        "net_weight_g": {"value": "451", "confidence": 0.99, "image_indexes": [5]},
                        "product_origin": {"value": "中国福建德化", "confidence": 0.96, "image_indexes": [6]},
                        "supplier_item_number": {"value": "JC2023041300002", "confidence": 0.98, "image_indexes": [7]},
                    },
                    "conflicts": [
                        {
                            "field": "material",
                            "values": ["树脂", "紫砂"],
                            "image_indexes": [2, 7],
                            "reason": "来源图片文字互相冲突",
                        }
                    ],
                    "listing_copy": {
                        "title": "Zen Buddha Hand Lotus Backflow Incense Burner Home Decor",
                        "selling_points": ["Lotus-shaped backflow cone holder", "Decorative Buddha-hand silhouette"],
                        "description": "A decorative backflow incense burner for home or meditation spaces.",
                    },
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 1000, "completion_tokens": 400, "total_tokens": 1400, "cost": 0.0012},
        }

    client = FalProductVisionClient(
        credential="backend-only-key",
        transport=fake_transport,
        model="google/gemini-2.5-flash",
    )
    analysis = client.analyze(
        image_urls=["https://app.jiejing.shop/signed/one", "https://app.jiejing.shop/signed/two"],
        merchant_message="供应商链接 https://qr.1688.com/s/FqVegjLr，请识别后填入 Listing。",
    )
    assert captured["endpoint"] == "https://fal.run/openrouter/router/vision"
    assert captured["authorization"] == "Key backend-only-key"
    assert captured["payload"]["image_urls"] == [
        "https://app.jiejing.shop/signed/one",
        "https://app.jiejing.shop/signed/two",
    ]
    assert analysis["provider"] == "fal"
    assert analysis["model"] == "google/gemini-2.5-flash"

    packet = build_product_vision_fact_packet(
        analysis=analysis,
        merchant_message="供应商链接 https://qr.1688.com/s/FqVegjLr，请识别后填入 Listing。",
        source_assets=[
            {"asset_id": "media_src_one", "sha256": "a" * 64, "original_filename": "front.jpg", "width": 800, "height": 800},
            {"asset_id": "media_src_two", "sha256": "b" * 64, "original_filename": "spec.jpg", "width": 800, "height": 1000},
        ],
    )
    assert packet["source_confirmed_facts"] == {}, "AI vision output must never impersonate confirmed source facts"
    suggestions = packet["derived_listing_suggestions"]
    assert suggestions["product_name"] == "禅意佛手莲花倒流香炉"
    assert suggestions["product_dimensions_cm"] == "16.2 x 7.7 x 17.9"
    assert suggestions["net_weight_g"] == "451"
    assert suggestions["product_origin"] == "中国福建德化"
    assert suggestions["supplier_item_number"] == "JC2023041300002"
    assert suggestions["source_url"] == "https://qr.1688.com/s/FqVegjLr"
    assert "material" not in suggestions, "conflicting material must not become a suggested fact"
    assert "package_weight_g" not in suggestions, "net weight must not be relabeled as package weight"
    assert "item_location" not in suggestions, "product origin must not be relabeled as ship-from location"
    assert set(packet["unknown_facts"]) == {
        "product_name", "sku", "condition", "material", "package_weight_g",
        "package_length_cm", "package_width_cm", "package_height_cm", "unit_cost",
        "selling_price", "currency", "quantity", "item_location", "image_urls",
        "image_rights_confirmed", "source_url", "product_dimensions_cm", "net_weight_g",
        "product_origin", "supplier_item_number",
    }, "every unconfirmed required or vision-extracted value must remain unknown"
    assert packet["ready_for_listing_draft"] is True
    assert packet["listing_readiness"]["ready_for_real_publish"] is False
    assert packet["listing_copy"] == {}, "vision output must not become buyer-facing Listing copy"
    assert packet["buyer_copy_requires_validated_listing_generation"] is True
    assert "merchant_product_fact_conflict:material" in packet["blocked_by"]
    image_only_packet = build_product_vision_fact_packet(
        analysis=analysis,
        merchant_message="请识别这些商品图片并整理事实。",
        source_assets=[
            {"asset_id": "media_src_one", "sha256": "a" * 64, "original_filename": "front.jpg", "width": 800, "height": 800},
        ],
    )
    assert image_only_packet["source_mode"] == "merchant_images_supplied", (
        "uploading images alone must not claim merchant-owned-product provenance"
    )
    assert image_only_packet["source_confirmed_facts"] == {}
    assert "merchant_owned_product_confirmed" in image_only_packet["unknown_facts"]
    assert "merchant_product_source_unconfirmed" in image_only_packet["blocked_by"]
    serialized = json.dumps(packet, ensure_ascii=False)
    assert "signed/one" not in serialized and "signed/two" not in serialized
    assert "backend-only-key" not in serialized

    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'id="ceoAttachmentInput"' in app_js
    assert 'multiple accept="image/png,image/jpeg,image/webp"' in app_js
    assert "source_asset_ids: safeSourceAssetIds" in app_js
    assert "applySaasAiCeoProductFactPacket" in app_js
    api_source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    assert "read_for_provider(" in api_source
    assert "product_vision_fact_packet" in api_source
    vision_save_start = api_source.index("product_vision_report = self.repository.save_ai_ceo_semantic_product_facts(")
    vision_save_call = api_source[vision_save_start : vision_save_start + 1200]
    assert "listing_project_identity=listing_project_identity" in vision_save_call, (
        "product vision fact reports must persist the active Listing project identity"
    )
    assert "expected_fact_report_id=" in vision_save_call, "semantic vision persistence must retain the fact-version guard"
    assert api_source.index("turn_plan = plan_ai_ceo_turn(") < api_source.index("product_vision_report = self.repository.save_ai_ceo_semantic_product_facts("), (
        "semantic planning must precede any product vision fact save"
    )
    print("PASS jiejing_ai_ceo_product_image_intake")


if __name__ == "__main__":
    main()
