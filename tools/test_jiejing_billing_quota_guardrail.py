#!/usr/bin/env python3
"""Regression for merchant-visible billing usage and quota enforcement."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import build_billing_plan, build_billing_usage, evaluate_quota_action  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-quota-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "billing-quota.sqlite"
    runtime_db_path = OUT / "runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
        repo = SaaSRepository(db_path)
        fixture = repo.create_user_with_company(
            email="billing-quota@jiejing.local",
            password="billing-quota-password",
            company_name="Jiejing Billing Quota Test",
        )
        user = fixture["user"]
        company = fixture["company"]
        store = repo.create_store(
            company_id=company["company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "quota-store", "marketplace": "EBAY_US"},
        )

        plan = build_billing_plan(settings, repo)
        if plan.get("billing_ready_for_private_beta") is not True:
            return fail("manual_seed with published plans and quotas should satisfy private beta billing")
        if plan.get("billing_ready_for_paid_launch") is not False:
            return fail("manual_seed must not pretend to be a paid external billing provider")
        if plan.get("quota_contract", {}).get("hard_stop_on_quota_exhaustion") is not True:
            return fail("enabled quota enforcement should hard-stop exhausted metered units")

        usage = build_billing_usage(settings, repo, company_id=company["company_id"])
        if usage.get("usage", {}).get("connected_store_count") != 1:
            return fail("billing usage should count connected stores")
        if usage.get("blocked_units") != ["connected_store"]:
            return fail("starter plan should block adding a second connected store")
        store_quota = evaluate_quota_action(settings, repo, company_id=company["company_id"], action_unit="connected_store")
        if store_quota.get("allowed") is not False or "connected_store_quota" not in store_quota.get("reason", ""):
            return fail("connected_store quota should block the second store")

        for index in range(100):
            repo.create_task(
                company_id=company["company_id"],
                store_id=store["store_id"],
                user_id=user["user_id"],
                task_type="product_workflow",
                title=f"quota task {index}",
                input_data={"index": index},
            )
        task_quota = evaluate_quota_action(settings, repo, company_id=company["company_id"], action_unit="ai_ceo_task")
        if task_quota.get("allowed") is not False or "monthly_task_quota" not in task_quota.get("reason", ""):
            return fail("ai_ceo_task quota should block after monthly starter quota is exhausted")

        serialized = json.dumps({"plan": plan, "usage": usage, "task_quota": task_quota}, ensure_ascii=False)
        for forbidden in ["UNIT-PAYMENT-SECRET", "UNIT-WEBHOOK-SECRET", "access_token", "refresh_token", "client_secret"]:
            if forbidden in serialized:
                return fail(f"billing quota output leaked forbidden marker: {forbidden}")
        print("PASS jiejing_billing_quota_guardrail")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_DEFAULT_PLAN_KEY",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_DEFAULT_PLAN_KEY": "starter",
        }
    )
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
