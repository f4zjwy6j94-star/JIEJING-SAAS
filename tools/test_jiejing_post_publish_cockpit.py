#!/usr/bin/env python3
"""Regression guard for the read-only post-publish cockpit packet."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.post_publish_cockpit import build_post_publish_cockpit


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    empty = build_post_publish_cockpit(execution_results=[], confirmations=[], audit_logs=[])
    if empty.get("status") != "dry_run_ready_no_live_listing":
        return fail(f"empty cockpit should be dry-run ready, not launch-ready: {empty}")
    if empty.get("published") is not False:
        return fail(f"empty cockpit must not claim a real publish: {empty}")
    if empty.get("safety", {}).get("triggers_real_platform_write") is not False:
        return fail(f"cockpit must be read-only: {empty}")
    if empty.get("safety", {}).get("triggers_ebay_oauth") is not False:
        return fail(f"cockpit must not trigger eBay OAuth: {empty}")
    if empty.get("safety", {}).get("triggers_real_charge") is not False:
        return fail(f"cockpit must not trigger real charge: {empty}")
    if empty.get("paid_launch_claim_allowed") is not False or empty.get("production_ready_claim_allowed") is not False:
        return fail(f"dry-run cockpit must not imply paid launch readiness: {empty}")

    published = build_post_publish_cockpit(
        execution_results=[
            {
                "execution_id": "exec_publish_1",
                "confirmation_id": "confirm_publish_1",
                "task_id": "task_publish_1",
                "action_type": "publish_listing",
                "status": "published_to_ebay",
                "created_at": "2026-06-20T00:00:00Z",
                "result": {
                    "status": "published_to_ebay",
                    "action_type": "publish_listing",
                    "platform_result": {
                        "listing_id": "127879396514",
                        "offer_id": "172743146011",
                        "sku": "JJ-NEW-SMOKE-001",
                    },
                    "publish_recovery": {
                        "sku": "JJ-NEW-SMOKE-001",
                        "published_offer": {"listing_id": "127879396514", "offer_id": "172743146011"},
                        "cleanup_plan": {
                            "status": "plan_only",
                            "confirmation_required": True,
                            "operations": [
                                {"operation": "end_listing", "listing_id": "127879396514", "writes_to_ebay": True},
                                {"operation": "delete_offer", "offer_id": "172743146011", "writes_to_ebay": True},
                            ],
                        },
                    },
                    "secret_exposed": False,
                },
            }
        ],
        confirmations=[
            {
                "confirmation_id": "confirm_publish_1",
                "task_id": "task_publish_1",
                "store_id": "store_1",
                "action_type": "publish_listing",
                "status": "approved",
                "title": "Confirm publish",
                "created_at": "2026-06-20T00:00:00Z",
                "high_risk": True,
            }
        ],
        audit_logs=[{"action_type": "execution_service.result", "summary": "ExecutionService returned a result."}],
    )
    if published.get("status") != "ready_with_execution_result" or published.get("published") is not True:
        return fail(f"published cockpit should be ready with execution result: {published}")
    if published.get("latest_listing", {}).get("listing_id") != "127879396514":
        return fail(f"published cockpit should expose sanitized listing id: {published}")
    cleanup = published.get("cleanup_plan_boundary", {})
    if cleanup.get("requires_confirmation_center") is not True or cleanup.get("execution_allowed_now") is not False:
        return fail(f"cleanup boundary must remain confirmation-gated: {published}")
    if not cleanup.get("operations"):
        return fail(f"cleanup operations should be visible as plan-only evidence: {published}")
    for window in published.get("review_windows", []):
        if window.get("real_change_allowed_without_confirmation") is not False:
            return fail(f"review windows must preserve confirmation boundary: {published}")

    dumped = json.dumps(published, ensure_ascii=False)
    forbidden = ["refresh_token", "access_token", "client_secret", "sk_live", "sk_test"]
    if any(marker in dumped for marker in forbidden):
        return fail(f"cockpit leaked a secret-looking marker: {dumped}")
    print("PASS jiejing_post_publish_cockpit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
