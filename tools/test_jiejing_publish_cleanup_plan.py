from __future__ import annotations

import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.execution import ExecutionRequest, ExecutionService
from jiejing_runtime.policies import HIGH_RISK_ACTIONS as RUNTIME_HIGH_RISK_ACTIONS

from jiejing_saas.api_server import _apply_publish_recovery_execution_context, _cleanup_confirmation_id
from jiejing_saas.repository import HIGH_RISK_ACTIONS as SAAS_HIGH_RISK_ACTIONS
from jiejing_saas.repository import SaaSRepository


OUT = Path("output/test-jiejing-publish-cleanup-plan")


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    repo = SaaSRepository(OUT / "cleanup-plan.sqlite", database_engine="sqlite")
    account = repo.create_user_with_company(
        email=f"cleanup-{int(time.time())}@example.com",
        password="Password123!",
        company_name="Cleanup Test",
    )
    user = account["user"]
    store = repo.create_store(
        company_id=user["default_company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "cleanup store", "marketplace": "EBAY_US"},
    )
    task = repo.create_task(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="product.workflow",
        title="Cleanup confirmation flow",
        input_data={"product": "Backflow incense burner"},
    )
    repo.save_runtime_outputs(
        task=task,
        runtime_result={
            "run": {"run_id": "run_cleanup"},
            "confirmations": [
                {
                    "confirmation_id": "confirm_publish",
                    "action_type": "publish_listing",
                    "title": "Confirm publish",
                    "default_action": "hold",
                }
            ],
        },
    )
    publish_confirmation = repo.list_confirmations(company_id=user["default_company_id"], limit=1)[0]
    cleanup_plan = {
        "status": "plan_only",
        "confirmation_required": True,
        "operations": [
            {"operation": "end_listing", "listing_id": "127879396514", "writes_to_ebay": True},
            {"operation": "delete_offer", "offer_id": "172743146011", "writes_to_ebay": True},
            {"operation": "delete_inventory_item", "sku": "JJ-BACKFLOW-20260523-003", "writes_to_ebay": True},
        ],
        "secret_exposed": False,
    }
    cleanup_confirmation = repo.create_confirmation(
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        task_id=task["task_id"],
        runtime_run_id=publish_confirmation["runtime_run_id"],
        action_type="cleanup_test_listing",
        title="Confirm test listing cleanup",
        item={
            "source": "unit_test_publish_recovery",
            "source_publish_confirmation_id": publish_confirmation["confirmation_id"],
            "cleanup_plan": cleanup_plan,
            "secret_exposed": False,
        },
        created_by=user["user_id"],
        confirmation_id=_cleanup_confirmation_id(
            publish_confirmation_id=publish_confirmation["confirmation_id"],
            publish_recovery={"sku": "JJ-BACKFLOW-20260523-003", "published_offer": {"listing_id": "127879396514"}},
        ),
    )
    if cleanup_confirmation.get("action_type") != "cleanup_test_listing":
        return fail(f"cleanup confirmation action not persisted: {cleanup_confirmation}")
    if cleanup_confirmation.get("high_risk") is not True:
        return fail(f"cleanup confirmation must be high risk: {cleanup_confirmation}")
    if cleanup_confirmation.get("item", {}).get("cleanup_plan", {}).get("confirmation_required") is not True:
        return fail(f"cleanup confirmation must carry plan details: {cleanup_confirmation}")
    if "cleanup_test_listing" not in SAAS_HIGH_RISK_ACTIONS or "cleanup_test_listing" not in RUNTIME_HIGH_RISK_ACTIONS:
        return fail("cleanup_test_listing must be high risk in both SaaS and Runtime policy sets")

    approved = repo.decide_confirmation(
        company_id=user["default_company_id"],
        confirmation_id=cleanup_confirmation["confirmation_id"],
        decision="approve",
        decided_by=user["user_id"],
        note="unit cleanup approval",
    )
    request = ExecutionRequest(
        action_type="cleanup_test_listing",
        task_id=task["task_id"],
        user_id=user["user_id"],
        company_id=user["default_company_id"],
        store_id=store["store_id"],
        platform="ebay",
        payload={"cleanup_plan": cleanup_plan},
        confirmation_id=approved["confirmation_id"],
        confirmed_by=approved["decided_by"],
        confirmed_at=approved["decided_at"],
        idempotency_key="cleanup-unit-idempotency",
    )
    preflight = ExecutionService(demo_mode=False).preflight(request)
    if preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"cleanup preflight should pass with plan, confirmation and idempotency: {preflight}")
    if preflight.get("real_execution_allowed") is not False:
        return fail(f"preflight must not claim direct real execution: {preflight}")
    execution = ExecutionService(demo_mode=False).execute(request).to_dict()
    if execution.get("status") != "ready_for_platform_adapter":
        return fail(f"cleanup execution should stop at platform adapter boundary: {execution}")
    if execution.get("audit", {}).get("real_execution", {}).get("published_to_ebay") is not False:
        return fail(f"cleanup execution audit must not claim publish or cleanup execution: {execution}")
    recovered_payload = _apply_publish_recovery_execution_context(
        payload={"listing": {"sku": "WRONG-REPORT-INFERRED-SKU"}},
        confirmation_id=publish_confirmation["confirmation_id"],
        execution_results=[
            {
                "confirmation_id": publish_confirmation["confirmation_id"],
                "execution_id": "exec_partial_publish",
                "result": {
                    "status": "blocked_platform_error",
                    "steps": [
                        {
                            "step": "create_or_replace_inventory_item",
                            "path": "/sell/inventory/v1/inventory_item/JJ-PARTIAL-PUBLISH-001",
                            "status": "ok",
                        },
                        {
                            "step": "publish_offer",
                            "path": "/sell/inventory/v1/offer/173441259011/publish",
                            "status": "http_error",
                        },
                    ],
                    "audit": {
                        "idempotency": {"idempotency_key": "publish-JJ-PARTIAL-PUBLISH-001"},
                        "secret_exposed": False,
                    },
                    "secret_exposed": False,
                },
            }
        ],
    )
    if recovered_payload.get("listing", {}).get("sku") != "JJ-PARTIAL-PUBLISH-001":
        return fail(f"recovery context must prefer execution SKU over report-inferred SKU: {recovered_payload}")
    if recovered_payload.get("publish_recovery_source", {}).get("execution_id") != "exec_partial_publish":
        return fail(f"recovery source should point at the execution record: {recovered_payload}")
    print("PASS jiejing_publish_cleanup_plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
