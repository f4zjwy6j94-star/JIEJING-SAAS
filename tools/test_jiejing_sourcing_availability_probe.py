#!/usr/bin/env python3
"""Regression for sourcing availability probe normalization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import MarketDataPacketBuilder, SourcingAvailabilityAdapter, SourcingAvailabilityConfig
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    adapter = SourcingAvailabilityAdapter()
    snapshot = adapter.probe(
        SourcingAvailabilityConfig(
            product="Stainless Steel Travel Tumbler",
            route="manual_or_1688",
            candidates=sample_candidates(),
        )
    )
    if snapshot.get("status") != "ready":
        return fail("complete sourcing candidates should normalize to ready")
    metrics = snapshot.get("metrics", {})
    if metrics.get("candidate_count") != 2:
        return fail("candidate_count should be 2")
    if metrics.get("lowest_unit_cost") != 18.8:
        return fail("lowest unit cost should be normalized")
    if metrics.get("blockers"):
        return fail("complete candidates should not have blockers")

    incomplete = adapter.probe(
        SourcingAvailabilityConfig(
            product="Stainless Steel Travel Tumbler",
            route="manual_or_1688",
            candidates=[{"title": "incomplete candidate", "url": "https://detail.1688.com/offer/incomplete.html"}],
        )
    )
    if incomplete.get("status") != "partial":
        return fail("incomplete sourcing candidate should be partial")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate sourcing availability handoff.",
            project_id="sourcing-availability-regression",
            sourcing_availability_probe={"route": "manual_or_1688", "candidates": sample_candidates()},
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    probes = {probe.get("key"): probe for probe in data_packet.get("report", {}).get("probes", [])}
    source_probe = probes.get("sourcing_availability")
    if not source_probe or source_probe.get("status") != "ready":
        return fail("market.data_packet should accept sourcing availability snapshots")
    if any(item.get("input_id") == "supplier_or_source_candidates" for item in data_packet.get("missing_inputs", [])):
        return fail("ready sourcing snapshot should remove supplier_or_source_candidates blocker")

    print("PASS sourcing_availability_probe_regression")
    return 0


def sample_candidates() -> list[dict]:
    return [
        {
            "source_platform": "1688",
            "title": "304 stainless steel tumbler 30oz with straw",
            "source_url": "https://detail.1688.com/offer/111.html",
            "supplier_name": "Yiwu Cup Factory",
            "unit_cost": 18.8,
            "currency": "CNY",
            "moq": 2,
            "stock": 5000,
            "ship_from": "Zhejiang Jinhua",
            "domestic_shipping_cost": 6.0,
            "package_weight_g": 520,
            "package_dimensions_cm": "11x11x24",
            "material": "304 stainless steel",
            "packaging": "color box + bubble wrap",
        },
        {
            "source_platform": "1688",
            "title": "insulated tumbler gift set 20oz",
            "source_url": "https://detail.1688.com/offer/222.html",
            "supplier_name": "Yongkang Drinkware",
            "unit_cost": 21.5,
            "currency": "CNY",
            "moq": 1,
            "stock": 3200,
            "ship_from": "Zhejiang Yongkang",
            "domestic_shipping_cost": 5.5,
            "package_weight_g": 470,
            "package_dimensions_cm": "10x10x22",
            "material": "304 stainless steel",
            "packaging": "gift box",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
