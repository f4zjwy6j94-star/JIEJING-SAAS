#!/usr/bin/env python3
"""Static release-contract guard for the product-grade merchant journey."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    runner = (ROOT / "tools" / "jiejing_product_grade_merchant_journey.py").read_text(encoding="utf-8")
    bulk = (ROOT / "tools" / "codex_jiejing_bulk_media_handoff_smoke.js").read_text(encoding="utf-8")
    publish = (ROOT / "tools" / "codex_jiejing_publish_confirmation_loop_smoke.js").read_text(encoding="utf-8")
    app = (ROOT / "app.js").read_text(encoding="utf-8")

    for marker in [
        "codex_jiejing_ai_ceo_market_listing_bridge_smoke.js",
        "codex_jiejing_bulk_media_handoff_smoke.js",
        "codex_jiejing_publish_confirmation_loop_smoke.js",
        '"JIEJING_ACCEPTANCE_PRODUCT": product',
        '"product_identity_ok"',
        '"real_platform_writes_enabled": False',
        '"triggers_real_charge": False',
        '"triggers_ebay_oauth": False',
    ]:
        assert marker in runner, marker
    assert "process.env.JIEJING_ACCEPTANCE_PRODUCT" in bulk
    assert "acceptance_product: acceptanceProduct" in bulk
    assert "process.env.JIEJING_ACCEPTANCE_PRODUCT" in publish
    assert "product: seed.product" in publish
    assert "const informational = /发布前|上架前|刊登前|核对项|规则|要求|规范|说明" in app
    assert "if (informational) return false;" in app
    assert "if (isSaasCeoHighRiskCommand(raw)) return \"confirm\";" in app
    assert 'fields.buyer_copy_status !== "waiting_for_merchant_product_facts"' in (
        ROOT / "tools" / "codex_jiejing_ai_ceo_market_listing_bridge_smoke.js"
    ).read_text(encoding="utf-8")
    assert "ui_has_truthful_listing_handoff" in (
        ROOT / "tools" / "codex_jiejing_ai_ceo_market_listing_bridge_smoke.js"
    ).read_text(encoding="utf-8")
    assert "payload = _structured_payload(completed.stderr)" in runner
    assert 'state: "attached"' in publish
    assert "uploading_grounded_media_source" in bulk
    assert "grounded_source_upload_ready" in bulk
    print("PASS jiejing_product_grade_journey_contract")


if __name__ == "__main__":
    main()
