#!/usr/bin/env python3
"""Regression checks for the internal Listing draft execution boundary."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.controlled_bridges import build_controlled_bridge_contract  # noqa: E402
from jiejing_saas.platform_registry import get_platform_definition  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "test-jiejing-execution-draft-boundary"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    service = ExecutionService(demo_mode=False)
    incomplete = ExecutionRequest(
        action_type="prepare_listing_draft",
        task_id="draft-boundary-task",
        user_id="user_draft_boundary",
        company_id="company_draft_boundary",
        store_id="store_draft_boundary",
        platform="ebay",
        payload={"listing": {"title": "Travel mosquito repeller"}},
    )
    incomplete_preflight = service.preflight(incomplete)
    if incomplete_preflight.get("status") != "blocked_missing_execution_facts":
        return fail(f"incomplete internal draft should be blocked by missing draft facts: {incomplete_preflight}")
    if incomplete_preflight.get("platform_adapter_required") is not False:
        return fail(f"internal draft must not require a platform adapter: {incomplete_preflight}")
    if "listing.description_html" not in incomplete_preflight.get("missing_fields", []):
        return fail(f"internal draft should require a merchant-visible description source: {incomplete_preflight}")

    complete = ExecutionRequest(
        action_type="save_listing_draft",
        task_id="draft-boundary-task",
        user_id="user_draft_boundary",
        company_id="company_draft_boundary",
        store_id="store_draft_boundary",
        platform="ebay",
        payload={
            "listing": {
                "title": "Travel mosquito repeller",
                "description_html": "<p>Draft only. Facts still need review before publish.</p>",
                "draft_source": "ai_ceo.market_research",
            },
            "source_records": [
                {"title": "AI CEO market research", "source_type": "ai_ceo.market_research"},
            ],
        },
    )
    complete_preflight = service.preflight(complete)
    if complete_preflight.get("canonical_action_type") != "prepare_listing_draft":
        return fail(f"save_listing_draft should canonicalize to prepare_listing_draft: {complete_preflight}")
    if complete_preflight.get("status") != "ready_low_risk":
        return fail(f"complete internal draft should be ready_low_risk: {complete_preflight}")
    result = service.execute(complete).to_dict()
    if result.get("status") != "ready_low_risk_internal_handoff":
        return fail(f"production boundary should accept the internal draft handoff without executing eBay: {result}")
    intent = result.get("audit", {}).get("execution_intent", {})
    if intent.get("platform_adapter") != "jiejing_internal.prepare_listing_draft":
        return fail(f"internal draft should use the Jiejing internal adapter label: {intent}")
    for key in ("platform_adapter_called", "creates_public_listing", "writes_to_ebay"):
        if intent.get(key) is not False:
            return fail(f"internal draft should keep {key}=False: {intent}")
    if intent.get("stores_internal_draft_only") is not True:
        return fail(f"internal draft should be marked as internal-only: {intent}")
    if intent.get("requires_confirmation") is not False:
        return fail(f"internal draft should not require confirmation until public publish: {intent}")
    if intent.get("confirmation_center_required_before_public_publish") is not True:
        return fail(f"public publish after draft should still require confirmation center: {intent}")
    if any((result.get("audit", {}).get("real_execution") or {}).values()):
        return fail(f"internal draft must not flip any real execution flags: {result}")

    repo = SaaSRepository(OUT / "draft-boundary.sqlite")
    repo.initialize()
    settings = SaaSSettings.from_env(
        db_path=OUT / "draft-boundary.sqlite",
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    bridge = build_controlled_bridge_contract(settings, repo)
    confirmation_bridge = next((item for item in bridge.get("bridges", []) if item.get("key") == "ConfirmationExecutionBridge"), {})
    low_risk_actions = confirmation_bridge.get("low_risk_internal_actions") or []
    draft_contract = next((item for item in low_risk_actions if item.get("action_type") == "prepare_listing_draft"), None)
    if not draft_contract:
        return fail(f"controlled bridge should expose the internal draft contract: {confirmation_bridge}")
    if draft_contract.get("writes_to_ebay") is not False or draft_contract.get("creates_public_listing") is not False:
        return fail(f"internal draft bridge must not look like an eBay write: {draft_contract}")
    external_actions = confirmation_bridge.get("confirmation_gated_external_actions") or []
    ebay_draft_contract = next(
        (item for item in external_actions if item.get("action_type") == "save_ebay_listing_draft"),
        None,
    )
    if not ebay_draft_contract:
        return fail(f"controlled bridge should expose the confirmation-gated eBay draft contract: {confirmation_bridge}")
    expected_external_boundary = {
        "writes_to_ebay": True,
        "creates_public_listing": False,
        "calls_publish_offer": False,
        "requires_confirmation": True,
    }
    for key, expected in expected_external_boundary.items():
        if ebay_draft_contract.get(key) is not expected:
            return fail(f"eBay draft bridge should keep {key}={expected}: {ebay_draft_contract}")

    ebay = get_platform_definition("ebay") or {}
    write_capabilities = set(ebay.get("write_capabilities") or [])
    if "internal_listing_draft_no_ebay_write" not in write_capabilities:
        return fail(f"eBay platform registry should distinguish internal drafts from real writes: {ebay}")
    if "save_ebay_listing_draft_after_confirmation" not in write_capabilities:
        return fail(f"eBay platform registry should expose the explicit unpublished draft capability: {ebay}")
    if "draft_listing" in write_capabilities:
        return fail(f"ambiguous draft_listing capability should not remain in the eBay registry: {ebay}")

    print("PASS jiejing_execution_draft_boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
