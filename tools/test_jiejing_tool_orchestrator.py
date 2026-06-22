#!/usr/bin/env python3
"""Regression for Jiejing ToolOrchestrator and role tool handoffs."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import JiejingAgentAdapter, JiejingToolOrchestrator  # noqa: E402
from jiejing_runtime.models import JiejingTask  # noqa: E402
from jiejing_runtime.tool_orchestrator import ToolPlan  # noqa: E402
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate tool orchestration across market, source, listing, asset, and finance roles.",
            project_id="tool-orchestrator-regression",
            public_search_probe={
                "results": [
                    {
                        "title": "Travel tumbler eBay sold examples",
                        "url": "https://www.ebay.com/sch/i.html?_nkw=stainless+travel+tumbler",
                        "snippet": "Public eBay search page with travel tumbler listings.",
                    }
                ]
            },
            ebay_read_only_probe={
                "keyword": "stainless travel tumbler",
                "browse_response": {"total": 18, "itemSummaries": [{"title": "20oz tumbler", "price": {"value": "14.99", "currency": "USD"}}]},
            },
            sourcing_availability_probe={
                "candidates": [
                    {
                        "source_platform": "1688",
                        "title": "20oz stainless tumbler with lid",
                        "source_url": "https://detail.1688.com/offer/demo-tumbler",
                        "supplier_name": "Demo Zhejiang Drinkware Factory",
                        "unit_cost": 18.8,
                        "moq": 2,
                        "stock": 5000,
                        "ship_from": "Zhejiang",
                        "package_weight_g": 360,
                        "package_dimensions_cm": "9 x 9 x 22",
                        "material": "Stainless steel, PP lid, silicone ring",
                    }
                ]
            },
            listing_metadata_probe={
                "marketplace_id": "EBAY_US",
                "category_id": "20687",
                "taxonomy_response": sample_taxonomy(),
                "fulfillment_policy_response": {"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful_1", "name": "SpeedPAK Default"}]},
                "payment_policy_response": {"paymentPolicies": [{"paymentPolicyId": "pay_1", "name": "Managed Payments"}]},
                "return_policy_response": {"returnPolicies": [{"returnPolicyId": "ret_1", "name": "14 Day Returns"}]},
            },
            media_generation_probe={
                "asset_manifest": {
                    "provider": "unit-test-media",
                    "assets": [
                        {"asset_type": "main_image", "url": "https://example.test/tumbler-main.jpg", "dimensions": "1600x1600"},
                        {"asset_type": "detail_page", "url": "https://example.test/tumbler-detail.jpg", "dimensions": "1200x3600"},
                    ],
                }
            },
            logistics_estimate_probe={
                "origin": "Zhejiang, China",
                "destination": "United States",
                "package_weight_g": 360,
                "package_dimensions_cm": "9 x 9 x 22",
                "estimates": [
                    {
                        "carrier": "Orange Connex",
                        "service_name": "SpeedPAK Economy",
                        "shipping_cost": 58.5,
                        "currency": "CNY",
                        "eta_min_days": 12,
                        "eta_max_days": 25,
                        "tracking": True,
                    }
                ],
            },
        )
    )
    adapter = JiejingAgentAdapter()
    checks = [
        (2, "market_data_packet", "market_data_packet_probe"),
        (3, "sourcing_availability", "sourcing_availability_probe"),
        (4, "ebay_listing_metadata", "listing_metadata_probe"),
        (5, "media_generation", "media_generation_probe"),
        (7, "logistics_estimate", "logistics_estimate_probe"),
    ]
    for task_index, section_key, probe_key in checks:
        result = adapter.execute(JiejingTask(tasks[task_index]))
        report = result.get("report", {})
        if section_key not in report.get("sections", {}):
            return fail(f"missing tool section: {section_key}")
        orchestration = report.get("tool_orchestration", {})
        if orchestration.get("orchestrator") != "jiejing-tool-orchestrator":
            return fail(f"missing orchestrator envelope for {section_key}")
        if orchestration.get("executed_count") != 1:
            return fail(f"expected one tool execution for {section_key}")
        execution = orchestration.get("executions", [{}])[0]
        if execution.get("real_execution_allowed") is not False or execution.get("secret_exposed") is not False:
            return fail(f"tool boundary flags wrong for {section_key}")
        if not report.get(probe_key):
            return fail(f"missing probe payload: {probe_key}")
        owned_execution = report.get("owned_agent_execution", {})
        if owned_execution.get("uses_external_tools") is not True:
            return fail(f"owned execution should mark external tool usage for {section_key}")
        driven = owned_execution.get("tool_driven_sections", {})
        if section_key in {"sourcing_availability", "ebay_listing_metadata", "media_generation", "logistics_estimate"}:
            if not isinstance(driven, dict) or not driven.get(section_key):
                return fail(f"tool output did not drive report sections for {section_key}")
        serialized = json.dumps(report, ensure_ascii=False)
        if "unit-secret-token" in serialized or "access_token" in serialized:
            return fail("tool report exposed a secret-looking value")

        sections = report.get("sections", {})
        if section_key == "sourcing_availability" and "Demo Zhejiang Drinkware Factory" not in serialized:
            return fail("source.match report did not absorb supplier candidate data")
        if section_key == "ebay_listing_metadata":
            if "ful_1" not in serialized or "Brand" not in json.dumps(sections.get("item_specifics"), ensure_ascii=False):
                return fail("listing.package report did not absorb policy/aspect metadata")
        if section_key == "media_generation":
            if "https://example.test/tumbler-main.jpg" not in serialized:
                return fail("asset.brief report did not absorb generated asset manifest")
        if section_key == "logistics_estimate":
            if "SpeedPAK Economy" not in serialized or "58.5" not in serialized:
                return fail("finance.review report did not absorb logistics estimate")

    timeout_result = JiejingToolOrchestrator()._run_plan(
        ToolPlan(
            name="unit_timeout_tool",
            label="Unit timeout tool",
            timeout_seconds=1,
            max_attempts=1,
            runner=lambda: _slow_tool(),
        ),
        JiejingTask(tasks[0]),
    )
    if timeout_result.get("tool_status") != "timeout":
        return fail("orchestrator should record timeout instead of hanging")

    print("PASS tool_orchestrator_regression")
    return 0


def _slow_tool() -> dict:
    time.sleep(2)
    return {"status": "ready", "summary": "too late"}


def sample_taxonomy() -> dict:
    return {
        "aspects": [
            {
                "localizedAspectName": "Brand",
                "aspectConstraint": {"aspectRequired": True},
                "aspectValues": [{"localizedValue": "Unbranded"}],
            },
            {
                "localizedAspectName": "Material",
                "aspectConstraint": {"aspectRequired": True},
                "aspectValues": [{"localizedValue": "Stainless Steel"}],
            },
        ]
    }


if __name__ == "__main__":
    raise SystemExit(main())
