#!/usr/bin/env python3
"""Listing model attempts must consume one merchant-visible trial/workflow unit."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import (
    PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV,
    SaaSBackendHandler,
)
from jiejing_saas.billing_plan import _company_usage
from jiejing_saas.repository import SaaSRepository


def _listing_attempt(
    repository: SaaSRepository,
    *,
    company_id: str,
    store_id: str,
    user_id: str,
    owner: str,
    requests: int,
    status: str,
) -> None:
    task = repository.create_task(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        task_type="listing_draft_generation",
        title="Listing quota attempt",
        input_data={
            "model_usage_owner": owner,
            "model_usage_required": True,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
    )
    repository.update_task_status(
        task_id=task["task_id"],
        company_id=company_id,
        status=status,
        output={
            "usage_consumed": requests > 0,
            "model_request_count": requests,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
        audit_summary="Listing quota regression attempt; no platform write.",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="jiejing-listing-trial-quota-", ignore_cleanup_errors=True) as temp_dir:
        repository = SaaSRepository(Path(temp_dir) / "saas.sqlite")
        account = repository.create_user_with_company(
            email="listing-trial-quota@local.invalid",
            password="listing-trial-quota-password",
            company_name="Listing Trial Quota",
        )
        company_id = account["company"]["company_id"]
        user_id = account["user"]["user_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user_id,
            payload={"platform": "ebay", "store_name": "Listing Trial Store", "marketplace": "EBAY_US"},
        )
        repository.upsert_platform_trial_activation(
            company_id=company_id,
            user_id=user_id,
            status="active",
            platform_trial_allowed=True,
            requires_challenge=True,
            challenge_attested=True,
            decision_reason="test_verified",
        )

        handler = object.__new__(SaaSBackendHandler)
        handler.repository = repository
        identity = {"company_id": company_id, "user_id": user_id}

        # A repaired failure can make two provider requests, but it is still one
        # merchant action under the published 20-call trial contract.
        _listing_attempt(
            repository,
            company_id=company_id,
            store_id=store["store_id"],
            user_id=user_id,
            owner="jiejing_platform_trial",
            requests=2,
            status="failed",
        )
        # BYOK is metered operationally but must not consume Jiejing-funded trial.
        _listing_attempt(
            repository,
            company_id=company_id,
            store_id=store["store_id"],
            user_id=user_id,
            owner="merchant_account_byok",
            requests=1,
            status="completed",
        )
        # A preflight-only task with no model request must not consume any unit.
        _listing_attempt(
            repository,
            company_id=company_id,
            store_id=store["store_id"],
            user_id=user_id,
            owner="jiejing_platform_trial",
            requests=0,
            status="blocked",
        )

        with patch.dict(os.environ, {PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV: "2"}, clear=False):
            first = handler._platform_model_trial_quota(identity=identity)
            if first.get("used") != 1 or first.get("remaining") != 1 or first.get("allowed") is not True:
                raise AssertionError(f"one failed Listing action should consume one trial unit: {first}")

            _listing_attempt(
                repository,
                company_id=company_id,
                store_id=store["store_id"],
                user_id=user_id,
                owner="jiejing_platform_trial",
                requests=1,
                status="completed",
            )
            exhausted = handler._platform_model_trial_quota(identity=identity)
            if exhausted.get("used") != 2 or exhausted.get("remaining") != 0:
                raise AssertionError(f"second Listing action should consume the final trial unit: {exhausted}")
            if exhausted.get("allowed") is not False or exhausted.get("blocked_by") != "platform_default_model_trial_exhausted":
                raise AssertionError(f"exhausted platform trial must block before another model call: {exhausted}")

        usage = _company_usage(repository, company_id=company_id)
        # All three real Listing model actions consume subscription workflow
        # capacity; the zero-request preflight does not.
        if usage.get("monthly_provider_job_count") != 3:
            raise AssertionError(f"Listing attempts were absent from subscription quota usage: {usage}")

        source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
        route_start = source.index('if len(parts) == 4 and parts[0] == "stores" and parts[2:] == ["listing-drafts", "generate"]:')
        route_end = source.index('if path == "tasks/product-workflow":', route_start)
        route = source[route_start:route_end]
        if 'model_resolution.get("mode") == "platform_managed_default"' not in route:
            raise AssertionError("Listing route does not enforce the platform-funded trial after model resolution")
        if "_platform_model_trial_quota(identity=identity)" not in route:
            raise AssertionError("Listing route does not reuse the backend platform trial quota")
        if route.index("_platform_model_trial_quota(identity=identity)") > route.index("generate_listing_draft("):
            raise AssertionError("Listing route checks the platform trial only after calling the model")

    print("PASS jiejing_listing_platform_trial_quota")


if __name__ == "__main__":
    main()
