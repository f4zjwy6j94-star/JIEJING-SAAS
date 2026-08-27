#!/usr/bin/env python3
"""Behavior regression for the authoritative merchant billing catalog."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_checkout import create_stripe_checkout_session  # noqa: E402
from jiejing_saas.billing_domestic import create_domestic_billing_order  # noqa: E402
from jiejing_saas.billing_plan import build_billing_plan, build_billing_usage  # noqa: E402
from jiejing_saas.billing_test_provider import apply_test_billing_event  # noqa: E402
from jiejing_saas.billing_webhook import build_billing_provider_contract  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    env_keys = (
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_STRIPE_PRICE_STARTER_ID",
        "JIEJING_STRIPE_PRICE_OPERATOR_ID",
        "JIEJING_STRIPE_PRICE_TEAM_ID",
    )
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="jiejing-plan-catalog-", ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            settings = SaaSSettings.from_env(
                db_path=root / "saas.sqlite",
                runtime_db_path=root / "runtime.sqlite",
                output_root=root,
                host="127.0.0.1",
                port=8788,
            )
            repository = SaaSRepository(settings.db_path)
            repository.initialize()
            billing_plan = build_billing_plan(settings, repository)
            catalog = billing_plan.get("plan_catalog", [])

            if [plan.get("key") for plan in catalog] != ["free", "starter", "operator"]:
                return fail(f"public catalog must contain exactly free/starter/operator: {catalog}")

            by_key = {str(plan.get("key")): plan for plan in catalog}
            expected = {
                "free": {
                    "label": "免费体验",
                    "amount_minor": 0,
                    "duration_days": 7,
                    "connected_store_quota": 1,
                    "team_member_quota": 1,
                    "monthly_task_quota": 20,
                    "media_points_included": 0,
                },
                "starter": {
                    "label": "有店铺",
                    "amount_minor": 9900,
                    "duration_days": 30,
                    "connected_store_quota": 1,
                    "team_member_quota": 2,
                    "monthly_task_quota": 100,
                    "media_points_included": 1000,
                },
                "operator": {
                    "label": "多店铺",
                    "amount_minor": 19900,
                    "duration_days": 30,
                    "connected_store_quota": 3,
                    "team_member_quota": 5,
                    "monthly_task_quota": 500,
                    "media_points_included": 3000,
                },
            }
            for key, fields in expected.items():
                actual = by_key[key]
                mismatches = {name: (actual.get(name), value) for name, value in fields.items() if actual.get(name) != value}
                if mismatches:
                    return fail(f"{key} public terms are not authoritative: {mismatches}")
            quota_contract = billing_plan.get("quota_contract", {})
            if quota_contract.get("media_points_are_not_bundled_with_subscription") is not False:
                return fail(f"paid plans include their approved media points: {quota_contract}")

            api_source = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
            register_start = api_source.index('if path == "auth/register":')
            register_end = api_source.index('if path == "auth/refresh":', register_start)
            register_scope = api_source[register_start:register_end]
            if "paid_plan_checkout_required" not in register_scope or "apply_test_billing_event(" in register_scope:
                return fail("registration must not create paid or retired entitlements without checkout")

            fixture = repository.create_user_with_company(
                email="legacy-team-plan@example.test",
                password="Legacy-team-plan-2026",
                company_name="Legacy Team Plan",
            )
            company_id = str(fixture["company"]["company_id"])
            user_id = str(fixture["user"]["user_id"])

            os.environ["JIEJING_BILLING_PROVIDER"] = "stripe_test_mock"
            blocked_test_team = apply_test_billing_event(
                repository,
                company_id=company_id,
                user_id=user_id,
                plan_key="team",
                action="activate",
            )
            if "billing_plan_key_not_supported" not in blocked_test_team.get("blocked_by", []):
                return fail(f"retired team plan must not be activated by the test provider: {blocked_test_team}")

            os.environ.update(
                {
                    "JIEJING_BILLING_PROVIDER": "stripe",
                    "JIEJING_STRIPE_PRICE_STARTER_ID": "price_live_starter_fixture",
                    "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_live_operator_fixture",
                }
            )
            os.environ.pop("JIEJING_STRIPE_PRICE_TEAM_ID", None)
            provider_contract = build_billing_provider_contract()
            if provider_contract.get("missing_plan_ids"):
                return fail(f"retired team Price ID must not block current paid readiness: {provider_contract}")
            if provider_contract.get("required_plan_ids") != {"starter": True, "operator": True}:
                return fail(f"current paid readiness must require exactly starter/operator: {provider_contract}")

            os.environ["JIEJING_BILLING_PROVIDER"] = "manual_seed"
            for retired_key in ("free", "team"):
                blocked_domestic = create_domestic_billing_order(
                    repository,
                    company_id=company_id,
                    user_id=user_id,
                    provider="wechat_pay_native",
                    plan_key=retired_key,
                    idempotency_key=f"blocked-{retired_key}-checkout",
                    rehearsal=True,
                )
                if blocked_domestic.get("reason") != "domestic_billing_plan_not_supported":
                    return fail(f"{retired_key} must not create a new domestic order: {blocked_domestic}")

                blocked_stripe = create_stripe_checkout_session(
                    repository,
                    company_id=company_id,
                    user_id=user_id,
                    plan_key=retired_key,
                )
                if "billing_plan_key_not_supported" not in blocked_stripe.get("blocked_by", []):
                    return fail(f"{retired_key} must not create a new Stripe checkout: {blocked_stripe}")

            for paid_key, display_name in (
                ("starter", "捷境有店铺 30 天"),
                ("operator", "捷境多店铺 30 天"),
            ):
                paid_order = create_domestic_billing_order(
                    repository,
                    company_id=company_id,
                    user_id=user_id,
                    provider="wechat_pay_native",
                    plan_key=paid_key,
                    idempotency_key=f"approved-{paid_key}-checkout",
                    rehearsal=True,
                )
                if paid_order.get("ok") is not True or paid_order.get("display_name") != display_name:
                    return fail(f"{paid_key} checkout should use the merchant catalog name: {paid_order}")

            historical_order = repository.create_domestic_billing_order_record(
                order_id="legacy_team_order_read_only",
                company_id=company_id,
                user_id=user_id,
                provider="wechat_pay_native",
                plan_key="team",
                amount_minor=29900,
                currency="CNY",
                duration_days=30,
                status="paid",
                idempotency_key_hash="legacy-team-order-fixture",
                order={"display_name": "捷境团队版 30 天", "historical_read_only": True},
            )
            if historical_order.get("plan_key") != "team":
                return fail(f"historical team order must remain readable: {historical_order}")

            applied = repository.apply_billing_webhook_event(
                event={
                    "provider": "manual_seed",
                    "event_id": "evt_legacy_team_active",
                    "event_type": "customer.subscription.updated",
                    "company_id": company_id,
                    "provider_customer_id": "legacy-team-customer",
                    "provider_subscription_id": "legacy-team-subscription",
                    "provider_plan_id": "legacy-team-29900",
                    "plan_key": "team",
                    "subscription_status": "active",
                    "quota_recalculation_required": True,
                    "payment_attention_required": False,
                    "secret_exposed": False,
                }
            )
            if applied.get("status") != "applied":
                return fail(f"existing team subscription fixture should remain readable: {applied}")
            legacy_usage = build_billing_usage(settings, repository, company_id=company_id)
            legacy_plan = legacy_usage.get("plan", {})
            if legacy_plan.get("key") != "team" or legacy_plan.get("team_member_quota") != 5:
                return fail(f"existing team entitlement must retain its original quota: {legacy_plan}")
            if legacy_plan.get("batch_row_quota") != 1000:
                return fail(f"existing team batch entitlement must not be downgraded: {legacy_plan}")

            print("PASS jiejing_billing_plan_catalog")
            return 0
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
