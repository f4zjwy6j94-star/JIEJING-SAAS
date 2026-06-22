#!/usr/bin/env python3
"""Regression for logistics estimate probe normalization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import LogisticsEstimateAdapter, LogisticsEstimateConfig, MarketDataPacketBuilder
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    adapter = LogisticsEstimateAdapter()
    snapshot = adapter.probe(
        LogisticsEstimateConfig(
            product="Stainless Steel Travel Tumbler",
            origin="Zhejiang Jinhua, China",
            destination="United States",
            package_weight_g=620,
            package_dimensions_cm="12x12x26",
            route="SpeedPAK/Orange Connex estimate",
            estimates=sample_estimates(),
        )
    )
    if snapshot.get("status") != "ready":
        return fail("complete logistics estimate should normalize to ready")
    metrics = snapshot.get("metrics", {})
    if metrics.get("lowest_shipping_cost") != 58.5:
        return fail("lowest shipping cost should be normalized")
    if metrics.get("fastest_eta_days") != 8:
        return fail("fastest eta should be normalized")

    partial = adapter.probe(
        LogisticsEstimateConfig(
            product="Stainless Steel Travel Tumbler",
            package_weight_g=620,
            estimates=[],
        )
    )
    if partial.get("status") != "partial":
        return fail("package facts without estimates should be partial")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate logistics estimate handoff.",
            project_id="logistics-estimate-regression",
            logistics_estimate_probe={
                "origin": "Zhejiang Jinhua, China",
                "destination": "United States",
                "package_weight_g": 620,
                "package_dimensions_cm": "12x12x26",
                "route": "SpeedPAK/Orange Connex estimate",
                "estimates": sample_estimates(),
            },
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    probes = {probe.get("key"): probe for probe in data_packet.get("report", {}).get("probes", [])}
    logistics_probe = probes.get("logistics_estimate")
    if not logistics_probe or logistics_probe.get("status") != "ready":
        return fail("market.data_packet should accept logistics estimate snapshots")
    if any(item.get("input_id") == "logistics_quote" for item in data_packet.get("missing_inputs", [])):
        return fail("ready logistics snapshot should remove logistics_quote blocker")

    print("PASS logistics_estimate_probe_regression")
    return 0


def sample_estimates() -> list[dict]:
    return [
        {
            "carrier": "Orange Connex",
            "service_name": "SpeedPAK Economy",
            "shipping_cost": 58.5,
            "currency": "CNY",
            "eta_min_days": 10,
            "eta_max_days": 22,
            "tracking": True,
            "source": "manual quote snapshot",
        },
        {
            "carrier": "Orange Connex",
            "service_name": "SpeedPAK Standard",
            "shipping_cost": 72.0,
            "currency": "CNY",
            "eta_min_days": 8,
            "eta_max_days": 15,
            "tracking": True,
            "source": "manual quote snapshot",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
