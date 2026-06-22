from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ip_risk_screening import screen_ip_logo_brand_risk  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    risky = screen_ip_logo_brand_risk(
        {
            "packet_id": "packet_test",
            "store_id": "store_test",
            "platform": "ebay",
            "source_mode": "official_api",
            "packet": {
                "source_label": "official_api",
                "sections": [
                    {
                        "key": "inventory_and_offers",
                        "data": {
                            "items": [
                                {
                                    "sku": "sku-1",
                                    "title": "Disney Mickey logo guitar strap",
                                    "description": "New strap for bass guitar.",
                                    "pictures": ["https://example.test/disney-logo.jpg"],
                                    "condition": "New",
                                    "price": "12.99",
                                    "quantity": 3,
                                    "item_specifics": {"Brand": "Disney", "Type": "Guitar Strap"},
                                }
                            ]
                        },
                        "field_evaluation": {"missing_required_fields": []},
                    },
                    {
                        "key": "taxonomy_listing_metadata",
                        "data": {"category_id": "4713", "leaf_category": "Bass Guitars", "required_aspects": ["Brand", "Type"]},
                    },
                ],
            },
        }
    )
    if risky.get("status") != "needs_rights_review":
        return fail("brand/logo hits should require rights review")
    if risky.get("risk_level") not in {"high", "medium"}:
        return fail("risk level should be elevated")
    if not any(item.get("risk_id") == "protected_brand_term" for item in risky.get("risk_items", [])):
        return fail("protected brand term should be flagged")
    if not risky.get("required_inputs") or not all(item.get("status") == "ready" for item in risky["required_inputs"]):
        return fail("complete packet should expose ready IP screening input requirements")
    if risky.get("real_platform_writes_enabled") is not False or risky.get("secret_exposed") is not False:
        return fail("screening must preserve no-write and no-secret boundary")

    missing = screen_ip_logo_brand_risk(
        {
            "packet_id": "packet_missing",
            "store_id": "store_test",
            "platform": "ebay",
            "source_mode": "official_api",
            "packet": {
                "source_label": "official_api",
                "sections": [
                    {
                        "key": "inventory_and_offers",
                        "data": {"marketplace_id": "EBAY_US"},
                        "field_evaluation": {"missing_required_fields": ["sku", "title", "price", "quantity", "condition"]},
                    }
                ],
            },
        }
    )
    if missing.get("status") != "blocked_missing_listing_content":
        return fail("missing listing title should block complete screening")
    if "listing_title_not_available_for_scan" not in missing.get("coverage_gaps", []):
        return fail("missing title gap should be visible")
    if "listing_brand_or_item_specifics_not_available_for_scan" not in missing.get("coverage_gaps", []):
        return fail("missing brand/item specifics gap should be visible")
    if not any(item.get("key") == "inventory_offer" and item.get("status") == "missing" for item in missing.get("required_inputs", [])):
        return fail("missing inventory/offer input should be visible")

    print("PASS jiejing_ip_risk_screening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
