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
    facts = packet["source_confirmed_facts"]
    assert facts["product_name"] == "禅意佛手莲花倒流香炉"
    assert facts["product_dimensions_cm"] == "16.2 x 7.7 x 17.9"
    assert facts["net_weight_g"] == "451"
    assert facts["product_origin"] == "中国福建德化"
    assert facts["supplier_item_number"] == "JC2023041300002"
    assert "material" not in facts, "conflicting material must not become a confirmed fact"
    assert "package_weight_g" not in facts, "net weight must not be relabeled as package weight"
    assert "item_location" not in facts, "product origin must not be relabeled as ship-from location"
    assert packet["source_confirmed_facts"]["source_url"] == "https://qr.1688.com/s/FqVegjLr"
    assert packet["ready_for_listing_draft"] is True
    assert packet["listing_readiness"]["ready_for_real_publish"] is False
    assert "merchant_product_fact_conflict:material" in packet["blocked_by"]
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
    print("PASS jiejing_ai_ceo_product_image_intake")


if __name__ == "__main__":
    main()
