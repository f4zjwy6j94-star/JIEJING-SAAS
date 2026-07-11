#!/usr/bin/env python3
"""Static release-contract guard for the product-grade merchant journey."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    runner = (ROOT / "tools" / "jiejing_product_grade_merchant_journey.py").read_text(encoding="utf-8")
    bulk = (ROOT / "tools" / "codex_jiejing_bulk_media_handoff_smoke.js").read_text(encoding="utf-8")
    publish = (ROOT / "tools" / "codex_jiejing_publish_confirmation_loop_smoke.js").read_text(encoding="utf-8")

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
    print("PASS jiejing_product_grade_journey_contract")


if __name__ == "__main__":
    main()
