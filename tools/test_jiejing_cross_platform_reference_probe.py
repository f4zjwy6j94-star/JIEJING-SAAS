#!/usr/bin/env python3
"""Regression for cross-platform reference probe normalization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import CrossPlatformReferenceAdapter, CrossPlatformReferenceConfig, MarketDataPacketBuilder
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    adapter = CrossPlatformReferenceAdapter()
    snapshot = adapter.probe(CrossPlatformReferenceConfig(product="Stainless Steel Travel Tumbler", references=sample_references()))
    if snapshot.get("status") != "ready":
        return fail("cross-platform sample should normalize to ready")
    metrics = snapshot.get("metrics", {})
    if metrics.get("reference_count") != 4:
        return fail("reference_count should be 4")
    platforms = {item.get("platform") for item in metrics.get("platform_distribution", [])}
    if not {"Amazon", "1688", "Taobao", "Shopify"}.issubset(platforms):
        return fail("platform aliases should be normalized")
    if "sourcing" not in metrics.get("useful_for", []):
        return fail("1688 reference should be useful for sourcing")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate cross-platform reference handoff.",
            project_id="cross-platform-reference-regression",
            cross_platform_reference_probe={"references": sample_references()},
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    probes = {probe.get("key"): probe for probe in data_packet.get("report", {}).get("probes", [])}
    cross_probe = probes.get("cross_platform_reference")
    if not cross_probe or cross_probe.get("status") != "ready":
        return fail("market.data_packet should accept cross-platform reference snapshots")
    if any(item.get("input_id") == "cross_platform_reference" for item in data_packet.get("missing_inputs", [])):
        return fail("ready cross-platform snapshot should remove cross_platform_reference blocker")

    print("PASS cross_platform_reference_probe_regression")
    return 0


def sample_references() -> list[dict]:
    return [
        {
            "platform": "Amazon",
            "title": "Insulated tumbler gift set buyer language",
            "url": "https://www.amazon.com/example-tumbler",
            "summary": "Reviews mention leakage, lid fit, gift packaging, and color mismatch.",
        },
        {
            "platform": "1688",
            "title": "304 stainless steel tumbler wholesale supplier",
            "url": "https://detail.1688.com/offer/example.html",
            "summary": "Wholesale page with MOQ, price tiers, supplier, and factory packaging.",
        },
        {
            "platform": "淘宝",
            "title": "便携保温杯场景图参考",
            "url": "https://item.taobao.com/item.htm?id=example",
            "summary": "Lifestyle image language and domestic buyer concerns.",
        },
        {
            "platform": "Shopify",
            "title": "DTC tumbler landing page visual merchandising",
            "url": "https://example-store.myshopify.com/products/tumbler",
            "summary": "Brand story, bundles, FAQ, and product photography reference.",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
