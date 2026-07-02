#!/usr/bin/env python3
"""Regression for paid public launch approval packet."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.billing_plan import STRIPE_CURRENT_API_VERSION  # noqa: E402
from jiejing_saas.paid_launch_approval_packet import build_paid_launch_approval_packet  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-paid-launch-approval-packet-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    previous = _set_blocked_env()
    try:
        blocked = _build("blocked.sqlite")
        if blocked.get("contract_version") != "2026-06-18-paid-launch-approval-packet":
            return fail("approval packet contract version missing")
        if blocked.get("status") != "blocked" or blocked.get("ready_for_owner_approval") is not False:
            return fail(f"blocked fixture should stay blocked: {blocked.get('summary')}")
        if blocked.get("charge_now_allowed") is not False or blocked.get("calls_stripe_api") is not False:
            return fail("approval packet must not allow charging or Stripe API calls")
        if blocked.get("triggers_ebay_oauth") is not False or blocked.get("repeat_ebay_oauth_allowed") is not False:
            return fail("approval packet must not trigger or permit repeated eBay OAuth")
        steps = {item.get("key"): item for item in blocked.get("steps", []) if isinstance(item, dict)}
        if set(steps) != {
            "stable_domain_hardening",
            "stripe_live_cutover",
            "no_charge_launch_rehearsal",
            "new_ebay_account_low_risk_smoke",
        }:
            return fail(f"approval packet steps missing or unexpected: {sorted(steps)}")
        if steps["stable_domain_hardening"].get("status") != "blocked":
            return fail("trycloudflare fixture must keep stable domain blocked")
        external = {item.get("key"): item for item in blocked.get("external_configuration_needed", []) if isinstance(item, dict)}
        for key in {
            "stable_domain_dns_tls_callback",
            "stripe_live_products_prices_webhook",
            "no_charge_rehearsal_evidence_flags",
            "clean_new_ebay_account_and_fresh_product",
        }:
            if key not in external:
                return fail(f"external configuration item missing: {key}")
        for item in external.values():
            if item.get("frontend_gets_secret") is not False or item.get("secret_exposed") is not False:
                return fail(f"external config item leaked frontend secret surface: {item}")
    finally:
        _restore_env(previous)

    previous = _set_stripe_domain_ready_env()
    try:
        readyish = _build("stripe-domain-ready.sqlite", seed_subscription=True)
        steps = {item.get("key"): item for item in readyish.get("steps", []) if isinstance(item, dict)}
        if steps["stable_domain_hardening"].get("status") != "ready":
            return fail(f"stable domain should be ready in configured fixture: {steps['stable_domain_hardening']}")
        if steps["stripe_live_cutover"].get("status") != "ready":
            return fail(f"Stripe cutover should be ready in configured fixture: {steps['stripe_live_cutover']}")
        external = {item.get("key"): item for item in readyish.get("external_configuration_needed", []) if isinstance(item, dict)}
        stripe_external_keys = (external.get("stripe_live_products_prices_webhook") or {}).get("environment_keys", [])
        if "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID" not in stripe_external_keys:
            return fail("approval packet must require webhook failure-path evidence id before paid launch")
        if "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID" not in stripe_external_keys:
            return fail("approval packet must require Customer Portal failure-path evidence id before paid launch")
        for required_stripe_go_live_key in {
            "JIEJING_STRIPE_ACCOUNT_ACTIVATED",
            "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED",
            "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID",
            "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED",
            "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID",
        }:
            if required_stripe_go_live_key not in stripe_external_keys:
                return fail(f"approval packet must require Stripe go-live evidence key: {required_stripe_go_live_key}")
        rehearsal_external_keys = (external.get("no_charge_rehearsal_evidence_flags") or {}).get("environment_keys", [])
        if "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID" not in rehearsal_external_keys:
            return fail("approval packet must require rollback audit packet id before paid launch")
        new_account_keys = set((external.get("clean_new_ebay_account_and_fresh_product") or {}).get("environment_keys", []))
        for required_key in {
            "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
            "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
            "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
            "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
            "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
            "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
            "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
            "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
            "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
            "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
            "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
            "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
            "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
        }:
            if required_key not in new_account_keys:
                return fail(f"approval packet must require new-account evidence key: {required_key}")
        if readyish.get("public_paid_launch_allowed") is not False or readyish.get("charge_now_allowed") is not False:
            return fail("approval packet must still require owner approval and never directly enable charging")
        serialized = json.dumps(readyish, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "authorization: bearer", "refresh_token=", "access_token=", "client_secret="):
            if forbidden in serialized:
                return fail(f"approval packet leaked forbidden marker: {forbidden}")
        print("PASS jiejing_paid_launch_approval_packet")
        return 0
    finally:
        _restore_env(previous)


def _build(name: str, *, seed_subscription: bool = False) -> dict[str, object]:
    db_path = OUT / name
    runtime_db_path = OUT / f"runtime-{name}"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path)
    repo.initialize()
    fixture = repo.create_user_with_company(email=f"{name}@example.test", password="local-test-password", company_name="Launch Approval")
    company_id = fixture["company"]["company_id"]
    user_id = fixture["user"]["user_id"]
    repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": "Approval Packet Store", "marketplace": "EBAY_US", "stage": "store_opened"},
    )
    if seed_subscription:
        applied = repo.apply_billing_webhook_event(
            event={
                "provider": "stripe",
                "event_id": f"evt_{name}",
                "event_type": "customer.subscription.updated",
                "company_id": company_id,
                "provider_customer_id": "cus_cutover_unit",
                "provider_subscription_id": "sub_cutover_unit",
                "provider_plan_id": "price_starter_live_unit",
                "plan_key": "starter",
                "subscription_status": "active",
                "quota_recalculation_required": True,
                "payment_attention_required": False,
                "secret_exposed": False,
            }
        )
        if applied.get("status") not in {"applied", "applied_duplicate_ignored"}:
            raise AssertionError(f"failed to seed billing subscription: {applied}")
    return build_paid_launch_approval_packet(settings, repo)


def _set_blocked_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
        }
    )
    return previous


def _set_stripe_domain_ready_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    stable = "https://app.jiejing.example"
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_STRIPE_SECRET_KEY": "sk_live_unit_secret",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_live_unit_secret",
            "JIEJING_BILLING_WEBHOOK_URL": f"{stable}/billing/webhook",
            "JIEJING_STRIPE_PRICE_STARTER_ID": "price_starter_live_unit",
            "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_operator_live_unit",
            "JIEJING_STRIPE_PRICE_TEAM_ID": "price_team_live_unit",
            "JIEJING_BILLING_SUCCESS_URL": f"{stable}/billing/success",
            "JIEJING_BILLING_CANCEL_URL": f"{stable}/billing/cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": f"{stable}/settings/billing",
            "JIEJING_PUBLIC_BASE_URL": stable,
            "JIEJING_STABLE_DOMAIN": "app.jiejing.example",
            "JIEJING_CORS_ORIGIN": stable,
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRICES_VERIFIED": "1",
            "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG": "1",
            "JIEJING_STRIPE_WEBHOOK_API_VERSION": STRIPE_CURRENT_API_VERSION,
            "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED": "1",
            "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID": "stripe_webhook_failure_path_approval_unit",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED": "1",
            "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED": "1",
            "JIEJING_STRIPE_INVOICE_PAID_TESTED": "1",
            "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED": "1",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID": "stripe_portal_failure_path_approval_unit",
            "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED": "1",
            "JIEJING_CUTOVER_ROLLBACK_VERIFIED": "1",
            "JIEJING_SECRET_SCAN_PASSED": "1",
            "JIEJING_READINESS_SNAPSHOT_RECORDED": "1",
            "JIEJING_BROWSER_SMOKE_PASSED": "1",
            "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID": "rollback_audit_packet_approval_unit",
        }
    )
    return previous


def _keys() -> list[str]:
    return [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_STRIPE_PRICE_STARTER_ID",
        "JIEJING_STRIPE_PRICE_OPERATOR_ID",
        "JIEJING_STRIPE_PRICE_TEAM_ID",
        "JIEJING_BILLING_SUCCESS_URL",
        "JIEJING_BILLING_CANCEL_URL",
        "JIEJING_BILLING_PORTAL_RETURN_URL",
        "JIEJING_PUBLIC_BASE_URL",
        "JIEJING_STABLE_DOMAIN",
        "JIEJING_CORS_ORIGIN",
        "JIEJING_DOMAIN_DNS_VERIFIED",
        "JIEJING_TLS_VERIFIED",
        "JIEJING_EBAY_CALLBACK_VERIFIED",
        "JIEJING_DEPLOYMENT_HARDENED",
        "JIEJING_SECURITY_HEADERS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRICES_VERIFIED",
        "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
        "JIEJING_STRIPE_WEBHOOK_API_VERSION",
        "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED",
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
        "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED",
        "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_READINESS_SNAPSHOT_RECORDED",
        "JIEJING_BROWSER_SMOKE_PASSED",
        "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
