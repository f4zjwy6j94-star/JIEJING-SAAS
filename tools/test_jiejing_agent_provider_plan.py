#!/usr/bin/env python3
"""Regression for Owned Agent provider execution planning."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ProductWorkflowRequest, build_agent_provider_execution_plan, build_product_workflow  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Lightweight eBay household test product",
            merchant_goal="Verify that every Jiejing role has a provider-job execution plan.",
            project_id="agent-provider-plan-regression",
            source_mode="manual_or_1688",
        )
    )
    plan = build_agent_provider_execution_plan(tasks)
    if plan.get("status") != "ready":
        return fail("agent provider plan should be ready when all contracts exist")
    if plan.get("task_count") != len(tasks) or plan.get("planned_task_count") != len(tasks):
        return fail("agent provider plan should cover every workflow task")
    required_families = {"public_search", "ebay", "sourcing", "logistics", "media", "model"}
    if not required_families.issubset(set(plan.get("provider_families", []))):
        return fail("agent provider plan should cover all external capability families")
    if plan.get("provider_job_count", 0) < 10:
        return fail("agent provider plan should expose repeated provider work units across the workflow")
    if plan.get("runtime_boundary", {}).get("provider_jobs_are_backend_queued") is not True:
        return fail("provider jobs must remain backend queued")
    if plan.get("runtime_boundary", {}).get("runtime_gets_raw_secret") is not False:
        return fail("Runtime must not receive raw secrets")
    if plan.get("real_execution_allowed") is not False or plan.get("secret_exposed") is not False:
        return fail("agent provider plan must not allow real execution or expose secrets")
    listing = next((item for item in plan.get("planned_tasks", []) if item.get("task_type") == "listing.package"), {})
    listing_keys = {job.get("provider_job_key") for job in listing.get("provider_jobs", [])}
    if not {"ebay.read_only_snapshot", "model.role_report_assist"}.issubset(listing_keys):
        return fail("listing package should require eBay metadata and model report provider jobs")
    asset = next((item for item in plan.get("planned_tasks", []) if item.get("task_type") == "asset.brief"), {})
    asset_keys = {job.get("provider_job_key") for job in asset.get("provider_jobs", [])}
    if "media.asset_generation" not in asset_keys:
        return fail("asset brief should require the provider-neutral media asset job")
    print("PASS jiejing_agent_provider_plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
