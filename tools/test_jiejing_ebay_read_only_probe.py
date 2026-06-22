#!/usr/bin/env python3
"""Regression for the eBay read-only probe adapter shell."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import EbayReadOnlyProbeAdapter, EbayReadOnlyProbeConfig, MarketDataPacketBuilder
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    adapter = EbayReadOnlyProbeAdapter()
    snapshot = adapter.snapshot_from_responses(
        keyword="stainless steel tumbler",
        marketplace_id="EBAY_US",
        browse_response=sample_browse_response(),
        taxonomy_response=sample_taxonomy_response(),
    )
    if snapshot.get("status") != "ready":
        return fail("sample Browse response should normalize to a ready snapshot")
    metrics = snapshot.get("metrics", {})
    if metrics.get("sample_count") != 3:
        return fail("sample_count should be 3")
    if metrics.get("price_min") != 14.99 or metrics.get("price_max") != 22.5:
        return fail("price band normalization failed")
    if len(snapshot.get("required_aspects", [])) != 2:
        return fail("taxonomy required aspects should be normalized")

    pending = adapter.probe(EbayReadOnlyProbeConfig(keyword="stainless steel tumbler", live_enabled=False))
    if pending.get("status") != "pending_connector":
        return fail("live-disabled probe should stay pending_connector")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate eBay read-only probe snapshot handoff.",
            project_id="ebay-read-only-probe-regression",
            ebay_read_only_probe={
                "keyword": "stainless steel tumbler",
                "marketplace_id": "EBAY_US",
                "browse_response": sample_browse_response(),
                "taxonomy_response": sample_taxonomy_response(),
            },
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    probes = {probe.get("key"): probe for probe in data_packet.get("report", {}).get("probes", [])}
    ebay_probe = probes.get("ebay_read_only")
    if not ebay_probe or ebay_probe.get("status") != "ready":
        return fail("market.data_packet should accept eBay read-only probe snapshots")
    if any(item.get("input_id") == "live_market_data" for item in data_packet.get("missing_inputs", [])):
        return fail("ready eBay probe snapshot should remove live_market_data blocker")

    print("PASS ebay_read_only_probe_regression")
    return 0


def sample_browse_response() -> dict:
    return {
        "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=stainless+steel+tumbler",
        "total": 387,
        "itemSummaries": [
            {
                "itemId": "v1|111|0",
                "title": "30oz Stainless Steel Tumbler with Lid and Straw",
                "price": {"value": "18.99", "currency": "USD"},
                "itemWebUrl": "https://www.ebay.com/itm/111",
                "seller": {"username": "seller-one"},
                "condition": "New",
                "categories": [{"categoryId": "20687", "categoryName": "Travel Mugs"}],
            },
            {
                "itemId": "v1|222|0",
                "title": "20oz Insulated Travel Coffee Mug",
                "price": {"value": "14.99", "currency": "USD"},
                "itemWebUrl": "https://www.ebay.com/itm/222",
                "seller": {"username": "seller-two"},
                "condition": "New",
                "categories": [{"categoryId": "20687", "categoryName": "Travel Mugs"}],
            },
            {
                "itemId": "v1|333|0",
                "title": "40oz Tumbler Cup Handle Gift Set",
                "price": {"value": "22.50", "currency": "USD"},
                "itemWebUrl": "https://www.ebay.com/itm/333",
                "seller": {"username": "seller-three"},
                "condition": "New",
                "categories": [{"categoryId": "20687", "categoryName": "Travel Mugs"}],
            },
        ],
    }


def sample_taxonomy_response() -> dict:
    return {
        "aspects": [
            {
                "localizedAspectName": "Brand",
                "aspectConstraint": {
                    "aspectRequired": True,
                    "aspectMode": "FREE_TEXT",
                    "aspectDataType": "STRING",
                    "itemToAspectCardinality": "SINGLE",
                    "aspectUsage": "RECOMMENDED",
                },
                "aspectValues": [],
            },
            {
                "localizedAspectName": "Material",
                "aspectConstraint": {
                    "aspectRequired": True,
                    "aspectMode": "SELECTION_ONLY",
                    "aspectDataType": "STRING",
                    "itemToAspectCardinality": "SINGLE",
                    "aspectUsage": "RECOMMENDED",
                },
                "aspectValues": [{"localizedValue": "Stainless Steel"}, {"localizedValue": "Plastic"}],
            },
            {
                "localizedAspectName": "Color",
                "aspectConstraint": {
                    "aspectRequired": False,
                    "aspectMode": "FREE_TEXT",
                    "aspectDataType": "STRING",
                    "itemToAspectCardinality": "SINGLE",
                    "aspectUsage": "OPTIONAL",
                },
            },
        ]
    }


if __name__ == "__main__":
    raise SystemExit(main())
