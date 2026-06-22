#!/usr/bin/env python3
"""Ensure official eBay inventory packets keep product rows for UI and IP screening."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ebay_data_packet import build_ebay_read_only_data_packet  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    packet = build_ebay_read_only_data_packet(
        company_id="company_test",
        store={"store_id": "store_test", "store_name": "northvalesource", "marketplace": "EBAY_US"},
        user_id="user_test",
        source_mode="official_api",
        probe_plan={
            "live_read_performed": True,
            "resources": [
                {"key": "inventory_and_offers", "label": "Inventory", "api_family": "sell.inventory"},
                {"key": "taxonomy_listing_metadata", "label": "Taxonomy", "api_family": "commerce.taxonomy"},
            ],
        },
        sample_payload={
            "inventory_and_offers": {
                "inventory_items": [
                    {
                        "sku": "SKU-1",
                        "title": "Unbranded Silicone Door Stopper",
                        "description": "Soft silicone door stopper.",
                        "condition": "NEW",
                        "quantity": 5,
                        "image_urls": ["https://example.test/door-stopper.webp"],
                        "aspects": {"Brand": ["Unbranded"], "Material": ["Silicone"]},
                    }
                ],
                "offers": [
                    {
                        "offer_id": "offer-1",
                        "listing_id": "1234567890",
                        "sku": "SKU-1",
                        "price": {"value": "12.99", "currency": "USD"},
                        "listing_status": "PUBLISHED",
                    }
                ],
                "inventory_item_count": 1,
                "offer_count": 1,
            },
            "taxonomy_listing_metadata": {
                "category_id": "123",
                "leaf_category": "Door Stops",
                "required_aspects": ["Brand", "Material"],
            },
        },
    )
    sections = {section.get("key"): section for section in packet.get("sections", [])}
    inventory = sections.get("inventory_and_offers", {}).get("data", {})
    if not inventory.get("inventory_items"):
        return fail("inventory_items should survive sanitization for product table rows")
    if not inventory.get("offers"):
        return fail("offers should survive sanitization for listing/offer rows")
    serialized = str(packet)
    for forbidden in ["UNIT-ACCESS-TOKEN-MUST-NOT-PERSIST", "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST", "password", "buyer@example.com"]:
        if forbidden in serialized.lower():
            return fail(f"packet leaked forbidden marker: {forbidden}")
    print("PASS jiejing_ebay_packet_inventory_arrays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
