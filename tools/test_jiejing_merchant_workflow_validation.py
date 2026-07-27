#!/usr/bin/env python3
"""Regression for backend-derived real merchant workflow validation evidence."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository


OUT = ROOT / "output" / "jiejing-merchant-workflow-validation-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _create_path(
    repository: SaaSRepository,
    *,
    email: str,
    path_count: int,
    decided: bool = True,
) -> dict[str, str]:
    fixture = repository.create_user_with_company(
        email=email,
        password="local-test-password",
        company_name="Validation Merchant",
    )
    company_id = fixture["company"]["company_id"]
    user_id = fixture["user"]["user_id"]
    store = repository.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": "Validation Store", "marketplace": "EBAY_US"},
    )
    for index in range(path_count):
        task = repository.create_task(
            company_id=company_id,
            store_id=store["store_id"],
            user_id=user_id,
            task_type="product_workflow",
            title=f"Merchant workflow {index + 1}",
            input_data={"product": "merchant supplied product facts"},
        )
        task = repository.update_task_status(
            task_id=task["task_id"],
            company_id=company_id,
            status="completed",
            output={"validation_fixture": True},
        )
        repository.save_runtime_outputs(
            task=task,
            runtime_result={
                "run_id": f"run-{task['task_id']}",
                "results": [
                    {
                        "task_type": "listing_composer",
                        "summary": "Structured market report and Listing draft",
                        "status": "pass",
                    }
                ],
                "confirmations": [
                    {
                        "confirmation_id": f"publish-{index + 1}",
                        "action_type": "publish_listing",
                        "title": "Review Listing package",
                        "default_action": "hold",
                    }
                ],
            },
        )
        confirmation = repository.list_confirmations(company_id=company_id, limit=1)[0]
        if decided:
            repository.decide_confirmation(
                company_id=company_id,
                confirmation_id=confirmation["confirmation_id"],
                decision="modify" if index % 2 else "approve",
                decided_by=user_id,
                note="Merchant reviewed the generated package.",
            )
    return {"company_id": company_id, "user_id": user_id}


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    repository = SaaSRepository(OUT / "validation.sqlite")
    repository.initialize()

    initial = repository.merchant_workflow_validation_snapshot()
    if initial.get("passed") is not False or initial.get("validated_path_count") != 0:
        return fail(f"empty evidence must stay pending: {initial}")

    _create_path(repository, email="merchant-one@shop-one.cn", path_count=7)
    _create_path(repository, email="merchant-two@shop-two.cn", path_count=7)
    _create_path(repository, email="merchant-three@shop-three.cn", path_count=6)
    _create_path(repository, email="synthetic@example.test", path_count=20)
    _create_path(repository, email="merchant-incomplete@shop-four.cn", path_count=3, decided=False)

    snapshot = repository.merchant_workflow_validation_snapshot()
    if snapshot.get("contract_version") != "2026-07-14-real-merchant-workflow-validation-v1":
        return fail(f"unexpected contract: {snapshot}")
    if snapshot.get("passed") is not True or snapshot.get("status") != "threshold_met":
        return fail(f"three merchants and twenty decided paths should pass: {snapshot}")
    if snapshot.get("validated_merchant_count") != 3:
        return fail(f"synthetic and incomplete merchants must not count: {snapshot}")
    if snapshot.get("validated_path_count") != 20:
        return fail(f"only decided complete merchant paths should count: {snapshot}")
    if snapshot.get("required_merchant_count") != 3 or snapshot.get("required_path_count") != 20:
        return fail(f"thresholds changed unexpectedly: {snapshot}")
    if snapshot.get("synthetic_accounts_excluded") is not True:
        return fail(f"synthetic exclusion must be explicit: {snapshot}")
    if snapshot.get("customer_visible") is not False or snapshot.get("read_only") is not True:
        return fail(f"validation evidence must stay owner-only and read-only: {snapshot}")
    if snapshot.get("triggers_real_platform_write") is not False or snapshot.get("triggers_charge") is not False:
        return fail(f"validation snapshot must not trigger real actions: {snapshot}")

    serialized = json.dumps(snapshot, ensure_ascii=False).lower()
    for forbidden in ("shop-one", "shop-two", "shop-three", "company_", "user_", "store_", "password", "token", "secret"):
        if forbidden in serialized:
            return fail(f"snapshot leaked identifier or secret-like field: {forbidden}")

    print("PASS jiejing_merchant_workflow_validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
