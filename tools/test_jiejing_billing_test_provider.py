#!/usr/bin/env python3
"""Regression for no-charge billing rehearsal without a real Stripe account."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_checkout import (  # noqa: E402
    build_billing_checkout_contract,
    create_stripe_checkout_session,
    create_stripe_customer_portal_session,
)
from jiejing_saas.billing_plan import build_billing_plan, build_billing_usage, evaluate_quota_action  # noqa: E402
from jiejing_saas.billing_test_provider import apply_test_billing_event  # noqa: E402
from jiejing_saas.billing_webhook import build_billing_provider_contract, handle_billing_webhook  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


_TEMP_ROOT = tempfile.TemporaryDirectory(prefix="jiejing-billing-test-provider-", ignore_cleanup_errors=True)
OUT = Path(_TEMP_ROOT.name)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        repo = SaaSRepository(OUT / "saas.sqlite")
        fixture = repo.create_user_with_company(
            email="billing-test-provider@jiejing.local",
            password="local-test-password",
            company_name="Billing Test Provider Merchant",
        )
        company_id = fixture["company"]["company_id"]
        user_id = fixture["user"]["user_id"]

        provider_contract = build_billing_provider_contract()
        if provider_contract.get("provider") != "stripe_test_mock" or provider_contract.get("test_provider_ready") is not True:
            return fail(f"test provider contract should be ready without Stripe credentials: {provider_contract}")
        if provider_contract.get("api_key_required") is not False or provider_contract.get("webhook_secret_required") is not False:
            return fail(f"test provider must not require Stripe API key or webhook secret: {provider_contract}")
        if provider_contract.get("paid_provider_ready") is not False:
            return fail("test provider must not satisfy live paid provider readiness")

        public_webhook = handle_billing_webhook(raw_body=b"{}", headers={})
        if public_webhook.get("ok") is not False or "billing_test_provider_public_webhook_disabled" not in public_webhook.get("blocked_by", []):
            return fail(f"public webhook should be disabled for test provider: {public_webhook}")

        checkout_contract = build_billing_checkout_contract()
        checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
        if checkout_contract.get("ready_for_test_billing_rehearsal") is not True:
            return fail(f"checkout contract should support no-charge rehearsal: {checkout_contract}")
        if checkout_contract.get("ready_for_paid_launch") is not False:
            return fail("test checkout contract must not be paid-launch ready")
        if checkout_sessions.get("calls_stripe_api") is not False or checkout_sessions.get("creates_real_checkout_session") is not False:
            return fail(f"test checkout must not call Stripe or create real session: {checkout_sessions}")

        checkout = create_stripe_checkout_session(
            repo,
            company_id=company_id,
            user_id=user_id,
            plan_key="operator",
        )
        if checkout.get("ok") is not True or checkout.get("status") != "test_checkout_session_created":
            return fail(f"mock checkout session should be created: {checkout}")
        if checkout.get("calls_stripe_api") is not False or checkout.get("triggers_real_charge") is not False:
            return fail(f"mock checkout must be no-charge and offline: {checkout}")
        checkout_url = checkout.get("checkout_session", {}).get("url") if isinstance(checkout.get("checkout_session"), dict) else ""
        if "billing_test_session=" not in checkout_url or "billing_test_mode=1" not in checkout_url:
            return fail(f"mock checkout URL should carry test markers: {checkout_url}")

        blocked_override = create_stripe_checkout_session(
            repo,
            company_id=company_id,
            user_id=user_id,
            plan_key="operator",
            success_url="https://evil.example/app.html",
        )
        if blocked_override.get("ok") is not False or "billing_success_url_not_allowed" not in blocked_override.get("blocked_by", []):
            return fail(f"mock checkout should still block unconfigured return URLs: {blocked_override}")

        activated = apply_test_billing_event(
            repo,
            company_id=company_id,
            user_id=user_id,
            plan_key="operator",
            action="activate",
        )
        if activated.get("ok") is not True:
            return fail(f"activate event should apply: {activated}")
        usage = build_billing_usage(settings, repo, company_id=company_id)
        if usage.get("plan", {}).get("key") != "operator" or usage.get("subscription", {}).get("entitlement_active") is not True:
            return fail(f"activated test subscription should drive usage and quota: {usage}")

        portal = create_stripe_customer_portal_session(repo, company_id=company_id, user_id=user_id)
        if portal.get("ok") is not True or portal.get("status") != "test_customer_portal_session_created":
            return fail(f"mock portal should be available after activation: {portal}")
        if portal.get("calls_stripe_api") is not False or portal.get("triggers_real_charge") is not False:
            return fail(f"mock portal must not call Stripe or charge: {portal}")

        failed = apply_test_billing_event(
            repo,
            company_id=company_id,
            user_id=user_id,
            plan_key="operator",
            action="payment_failed",
        )
        if failed.get("ok") is not True:
            return fail(f"payment_failed event should apply: {failed}")
        quota = evaluate_quota_action(settings, repo, company_id=company_id, action_unit="ai_ceo_task")
        if quota.get("allowed") is not False or quota.get("reason") != "billing_subscription_not_active":
            return fail(f"payment failure should hard-stop paid work: {quota}")

        canceled = apply_test_billing_event(
            repo,
            company_id=company_id,
            user_id=user_id,
            plan_key="operator",
            action="cancel",
        )
        if canceled.get("ok") is not True:
            return fail(f"cancel event should apply: {canceled}")
        canceled_usage = build_billing_usage(settings, repo, company_id=company_id)
        if canceled_usage.get("subscription", {}).get("status") != "canceled":
            return fail(f"cancel should persist canceled subscription state: {canceled_usage}")

        plan = build_billing_plan(settings, repo)
        if plan.get("billing_ready_for_private_beta") is not True:
            return fail(f"test provider should satisfy private beta rehearsal: {plan.get('blockers')}")
        if plan.get("billing_ready_for_paid_launch") is not False or "test_billing_provider_not_allowed_for_paid_launch" not in plan.get("paid_launch_blockers", []):
            return fail(f"test provider must keep public paid launch blocked: {plan.get('paid_launch_blockers')}")
        merchant_launch_path = plan.get("merchant_launch_path") if isinstance(plan.get("merchant_launch_path"), dict) else {}
        if merchant_launch_path.get("current_stage") != "invited_beta_no_real_charge":
            return fail(f"test provider should expose invited-beta no-charge merchant launch path: {merchant_launch_path}")
        if (
            merchant_launch_path.get("public_paid_launch_allowed") is not False
            or merchant_launch_path.get("triggers_real_charge") is not False
            or merchant_launch_path.get("frontend_can_grant_quota") is not False
            or merchant_launch_path.get("backend_confirmation_required_before_entitlement") is not True
        ):
            return fail(f"merchant launch path must preserve billing safety flags: {merchant_launch_path}")
        step_keys = {item.get("key") for item in merchant_launch_path.get("steps", []) if isinstance(item, dict)}
        for required_step in {
            "current_charge_status",
            "hosted_payment_page",
            "backend_confirmation_before_entitlement",
            "quota_from_subscription_state",
        }:
            if required_step not in step_keys:
                return fail(f"merchant launch path missing step {required_step}: {merchant_launch_path}")
        safe_merchant_plan = SaaSBackendHandler._merchant_safe_billing_plan(plan)
        safe_merchant_provider = (
            safe_merchant_plan.get("provider") if isinstance(safe_merchant_plan.get("provider"), dict) else {}
        )
        # Private-beta proof remains in the internal plan checked above. Settings
        # receives the merchant contract, not the project's launch-stage report.
        expected_merchant_fields = {
            "contract_version", "provider", "plan_catalog", "add_on_catalog", "quota_contract",
            "mainland_payment", "confirmation_boundary", "public_charging_allowed", "charge_now_allowed",
            "triggers_real_charge", "triggers_real_refund", "calls_external_payment_api",
            "real_platform_writes_enabled", "frontend_gets_payment_secret", "frontend_can_grant_entitlement",
            "frontend_can_grant_quota", "customer_visible", "secret_exposed",
        }
        if set(safe_merchant_plan) != expected_merchant_fields:
            return fail(f"merchant billing response must use the current positive field allowlist: {set(safe_merchant_plan)}")
        safe_catalog = safe_merchant_plan.get("plan_catalog", [])
        if [(item.get("key"), item.get("amount_minor"), item.get("team_member_quota")) for item in safe_catalog] != [
            ("free", 0, 1), ("starter", 9900, 2), ("operator", 19900, 5),
        ]:
            return fail(f"merchant projection must retain current catalog prices and total seats: {safe_catalog}")
        if (safe_merchant_provider.get("provider"), safe_merchant_provider.get("checkout_mode"),
            safe_merchant_provider.get("billing_mode"), safe_merchant_provider.get("customer_visible")) != (
            "wechat_pay_native", "native_qr", "one_time_30_day_plan", True,
        ):
            return fail(f"merchant payment description must retain the current mainland checkout contract: {safe_merchant_provider}")
        safe_quota = safe_merchant_plan.get("quota_contract", {})
        if not all(safe_quota.get(key) is True for key in (
            "enabled", "hard_stop_on_quota_exhaustion", "merchant_visible_usage_required",
        )) or not {"connected_store", "ai_ceo_task", "provider_job", "model_report_assist"}.issubset(safe_quota.get("metered_units", [])):
            return fail(f"merchant projection must retain enforced and visible usage limits: {safe_quota}")
        safe_boundary = safe_merchant_plan.get("confirmation_boundary", {})
        if not all(safe_boundary.get(key) is True for key in (
            "billing_changes_need_owner_or_admin", "real_platform_writes_not_included_in_any_current_plan",
            "refunds_and_payment_disputes_need_human_operator",
        )):
            return fail(f"merchant projection must retain billing and refund approval boundaries: {safe_boundary}")
        for packet in (safe_merchant_plan, safe_merchant_provider, safe_merchant_plan.get("mainland_payment", {})):
            for key in ("public_charging_allowed", "charge_now_allowed", "triggers_real_charge", "triggers_real_refund",
                        "calls_external_payment_api", "real_platform_writes_enabled", "frontend_gets_payment_secret",
                        "frontend_can_grant_entitlement", "frontend_can_grant_quota", "secret_exposed"):
                if key in packet and packet[key] is not False:
                    return fail(f"no-charge rehearsal merchant projection must keep {key}=false")
        if safe_merchant_plan.get("customer_visible") is not True or safe_merchant_provider.get("available") is not False:
            return fail("no-charge rehearsal must expose merchant information without offering a real checkout")
        internal_fields = {
            "merchant_launch_path", "current_stage", "mainland_payment_launch", "future_international_payment",
            "billing_test_rehearsal_summary", "subscription_quota_shutdown_closure", "billing_incident_runbook",
            "customer_billing_trust_packet", "paid_launch_blockers", "internal_launch_evidence_visible",
            "external_paid_provider_configured", "test_billing_provider_configured", "payment_flow_test_mode",
            "manual_beta_private_provider_configured", "signed_webhook_configured", "provider_plan_id",
        }
        pending_values = [safe_merchant_plan]
        while pending_values:
            value = pending_values.pop()
            if isinstance(value, dict):
                leaked = internal_fields.intersection(value)
                if leaked:
                    return fail(f"merchant projection exposed internal billing fields: {sorted(leaked)}")
                pending_values.extend(value.values())
            elif isinstance(value, list):
                pending_values.extend(value)
        if "invited_beta_no_real_charge" in json.dumps(safe_merchant_plan):
            return fail("merchant Settings must not display the internal invited-beta launch stage")
        readiness = build_product_readiness(settings, repo)
        public_billing = (
            readiness.get("provider_status", {}).get("billing", {})
            if isinstance(readiness.get("provider_status"), dict)
            else {}
        )
        if public_billing.get("billing_ready_for_private_beta") is not True:
            return fail(f"public readiness should keep private-beta billing truth: {public_billing}")
        if (
            public_billing.get("billing_ready_for_paid_launch") is not False
            or public_billing.get("public_charging_allowed") is not False
            or public_billing.get("charge_now_allowed") is not False
            or public_billing.get("triggers_real_charge") is not False
            or public_billing.get("frontend_can_grant_quota") is not False
        ):
            return fail(f"public readiness must not claim paid launch or frontend quota control: {public_billing}")
        if public_billing.get("quota_enforcement_enabled") is not True or public_billing.get("paid_launch_blocker_count", 0) < 1:
            return fail(f"public readiness should expose quota and paid-launch blocker summary: {public_billing}")
        public_launch_path = public_billing.get("merchant_launch_path") if isinstance(public_billing.get("merchant_launch_path"), dict) else {}
        if (
            public_launch_path.get("current_stage") != "invited_beta_no_real_charge"
            or public_launch_path.get("quota_grant_source") != "backend_subscription_state"
            or public_launch_path.get("frontend_can_grant_entitlement") is not False
        ):
            return fail(f"public readiness should expose safe merchant launch path summary: {public_launch_path}")
        serialized_readiness = SaaSBackendHandler._public_readiness_summary(readiness, authenticated=False)
        serialized_public_billing = serialized_readiness.get("provider_status", {}).get("billing", {})
        if serialized_public_billing.get("merchant_launch_path", {}).get("current_stage") != "invited_beta_no_real_charge":
            return fail(
                "public readiness serializer must preserve private-beta compatibility without legacy diagnostics: "
                f"{serialized_public_billing}"
            )
        for internal_key in (
            "external_paid_provider_configured",
            "test_billing_provider_configured",
            "checkout_ready",
            "customer_portal_ready",
            "signed_webhook_configured",
        ):
            if internal_key in serialized_public_billing:
                return fail(f"public readiness serializer exposed legacy provider diagnostic {internal_key}")
        rehearsal = plan.get("billing_test_rehearsal_summary") if isinstance(plan.get("billing_test_rehearsal_summary"), dict) else {}
        if rehearsal.get("ready") is not True or rehearsal.get("calls_stripe_api") is not False or rehearsal.get("triggers_real_charge") is not False:
            return fail(f"billing test rehearsal summary should be ready and no-charge: {rehearsal}")
        shutdown_closure = (
            plan.get("subscription_quota_shutdown_closure")
            if isinstance(plan.get("subscription_quota_shutdown_closure"), dict)
            else {}
        )
        if shutdown_closure.get("ready_for_no_charge_rehearsal") is not True or shutdown_closure.get("ready_for_live_cutover") is not False:
            return fail(f"test provider should prove no-charge quota shutdown closure only: {shutdown_closure}")
        if shutdown_closure.get("mode") != "no_charge_test_provider":
            return fail(f"test provider shutdown closure should report no-charge mode: {shutdown_closure}")
        operator_summary = shutdown_closure.get("operator_summary") if isinstance(shutdown_closure.get("operator_summary"), dict) else {}
        if operator_summary.get("status") != "ready" or operator_summary.get("secret_exposed") is not False:
            return fail(f"shutdown closure should expose safe operator summary: {operator_summary}")
        guards = shutdown_closure.get("shutdown_guards") if isinstance(shutdown_closure.get("shutdown_guards"), dict) else {}
        if (
            guards.get("hard_stop_on_inactive_subscription") is not True
            or guards.get("payment_failure_blocks_metered_work") is not True
            or guards.get("cancellation_blocks_metered_work") is not True
            or guards.get("owner_approval_required_for_reenable") is not True
            or guards.get("secret_exposed") is not False
        ):
            return fail(f"shutdown guards should prove unpaid work hard-stop: {guards}")
        shutdown_keys = {item.get("key") for item in shutdown_closure.get("steps", []) if isinstance(item, dict)}
        for required in {
            "payment_failed_disables_entitlement",
            "subscription_cancel_disables_entitlement",
            "quota_guardrail_blocks_metered_work",
            "provider_cutover_no_real_charge_safety",
        }:
            if required not in shutdown_keys:
                return fail(f"shutdown closure missing step {required}: {shutdown_keys}")
        if (
            shutdown_closure.get("creates_checkout_session") is not False
            or shutdown_closure.get("calls_stripe_api") is not False
            or shutdown_closure.get("triggers_real_charge") is not False
            or shutdown_closure.get("frontend_gets_payment_secret") is not False
        ):
            return fail(f"shutdown closure must stay no-charge/no-secret: {shutdown_closure}")
        shutdown_state = canceled_usage.get("subscription_quota_shutdown_state") if isinstance(canceled_usage.get("subscription_quota_shutdown_state"), dict) else {}
        if shutdown_state.get("blocks_metered_work_when_inactive") is not True or shutdown_state.get("block_reason") != "billing_subscription_not_active":
            return fail(f"canceled test subscription should expose quota shutdown state: {shutdown_state}")

        serialized = json.dumps(
            {
                "provider_contract": provider_contract,
                "checkout_contract": checkout_contract,
                "checkout": checkout,
                "portal": portal,
                "activated": activated,
                "failed": failed,
                "canceled": canceled,
                "plan": plan,
                "usage": canceled_usage,
                "audits": repo.list_audit_logs(company_id=company_id, limit=20),
            },
            ensure_ascii=False,
        )
        for forbidden in ("sk_test", "whsec", "card_number", "card_token", "payment_method_secret", "client_secret", "refresh_token", "access_token"):
            if forbidden in serialized:
                return fail(f"billing test provider output leaked forbidden marker: {forbidden}")
        print("PASS jiejing_billing_test_provider")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_BILLING_SUCCESS_URL",
        "JIEJING_BILLING_CANCEL_URL",
        "JIEJING_BILLING_PORTAL_RETURN_URL",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe_test_mock",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_BILLING_SUCCESS_URL": "https://app.example.test/app.html?start=app&view=connect&billing=success",
            "JIEJING_BILLING_CANCEL_URL": "https://app.example.test/app.html?start=app&view=connect&billing=cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": "https://app.example.test/app.html?start=app&view=connect&billing=portal",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_STRIPE_SECRET_KEY": "",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "",
            "STRIPE_SECRET_KEY": "",
            "STRIPE_WEBHOOK_SECRET": "",
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
