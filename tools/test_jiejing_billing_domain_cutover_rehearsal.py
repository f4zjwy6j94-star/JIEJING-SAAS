#!/usr/bin/env python3
"""Regression for no-charge Stripe and stable-domain cutover rehearsal."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal  # noqa: E402
from jiejing_saas.billing_plan import STRIPE_CURRENT_API_VERSION  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-domain-cutover-rehearsal-test"
EXPECTED_STAGES = {
    "stripe_live_provider_selected",
    "stripe_live_price_ids_verified",
    "stable_domain_dns_tls_headers",
    "stripe_checkout_return_urls_on_stable_domain",
    "stripe_customer_portal_return_url_on_stable_domain",
    "stripe_signed_webhook_on_stable_domain",
    "stripe_api_webhook_version_pinned",
    "stripe_webhook_resilience_rehearsed",
    "subscription_state_and_quota_lifecycle_rehearsed",
    "cutover_rollback_audit_packet_recorded",
}
EXPECTED_NO_CHARGE_EVIDENCE_ITEMS = {
    "checkout_return_url_smoke",
    "customer_portal_return_url_smoke",
    "signed_webhook_smoke",
    "subscription_quota_lifecycle_smoke",
    "secret_scan_and_browser_smoke",
    "rollback_audit_packet",
    "no_charge_evidence_id_recorded",
}


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
        if blocked.get("status") != "blocked" or blocked.get("ready_for_owner_approval") is not False:
            return fail(f"blocked fixture should not be owner-approved: {blocked.get('summary')}")
        if blocked.get("charge_now_allowed") is not False or blocked.get("calls_stripe_api") is not False:
            return fail("rehearsal must not allow charging or Stripe API calls")
        stages = {item.get("key"): item for item in blocked.get("stages", []) if isinstance(item, dict)}
        if set(stages) != EXPECTED_STAGES:
            return fail(f"unexpected blocked stages: {sorted(stages)}")
        for key in ("stripe_live_provider_selected", "stable_domain_dns_tls_headers"):
            if stages[key].get("status") != "blocked":
                return fail(f"{key} should stay blocked in manual_seed/trycloudflare fixture")
        no_charge_packet = blocked.get("no_charge_live_domain_evidence_packet") if isinstance(blocked.get("no_charge_live_domain_evidence_packet"), dict) else {}
        if no_charge_packet.get("contract_version") != "2026-07-02-no-charge-live-domain-rehearsal-evidence-packet":
            return fail(f"no-charge live-domain evidence packet missing: {no_charge_packet}")
        if no_charge_packet.get("status") != "blocked" or no_charge_packet.get("ready_for_owner_review") is not False:
            return fail(f"blocked fixture must keep no-charge evidence packet blocked: {no_charge_packet.get('summary')}")
        no_charge_items = {item.get("key"): item for item in no_charge_packet.get("evidence_items", []) if isinstance(item, dict)}
        if set(no_charge_items) != EXPECTED_NO_CHARGE_EVIDENCE_ITEMS:
            return fail(f"no-charge evidence items missing or unexpected: {sorted(no_charge_items)}")
        for key, item in no_charge_items.items():
            for flag in ("creates_checkout_session", "calls_stripe_api", "triggers_real_charge", "charge_now_allowed", "triggers_ebay_oauth", "triggers_real_platform_write"):
                if item.get(flag) is not False:
                    return fail(f"no-charge evidence item must be side-effect free: {key}.{flag}={item.get(flag)}")
            if item.get("secret_exposed") is not False or item.get("frontend_gets_payment_secret") is not False:
                return fail(f"no-charge evidence item must not expose payment secrets: {key}")
        if blocked.get("triggers_ebay_oauth") is not False or blocked.get("repeat_ebay_oauth_allowed") is not False:
            return fail("rehearsal must not trigger or permit repeated eBay OAuth")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        ready = _build("ready.sqlite", seed_subscription=True)
        if ready.get("status") != "ready_for_owner_approval" or ready.get("ready_for_owner_approval") is not True:
            return fail(f"ready fixture should reach owner approval: {ready.get('summary')}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("ready_count") != len(EXPECTED_STAGES) or summary.get("blocked_count") != 0:
            return fail(f"all cutover stages should be ready in fixture: {summary}")
        if summary.get("no_charge_evidence_packet_status") != "ready" or summary.get("no_charge_evidence_blocked_count") != 0:
            return fail(f"ready fixture should include ready no-charge evidence packet summary: {summary}")
        urls = ready.get("required_urls") if isinstance(ready.get("required_urls"), dict) else {}
        if urls.get("ebay_oauth_callback_url") != "https://app.jiejing.example/oauth/ebay/callback":
            return fail(f"eBay callback URL should use stable domain: {urls}")
        if ready.get("public_paid_launch_allowed") is not False or ready.get("charge_now_allowed") is not False:
            return fail("owner approval packet must still not directly allow public charging")
        ready_stages = {item.get("key"): item for item in ready.get("stages", []) if isinstance(item, dict)}
        if "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID" not in ready_stages["stripe_webhook_resilience_rehearsed"].get("environment_keys", []):
            return fail("webhook resilience stage must require a failure-path evidence id")
        if "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID" not in ready_stages["subscription_state_and_quota_lifecycle_rehearsed"].get("environment_keys", []):
            return fail("subscription lifecycle stage must require a portal failure-path evidence id")
        if "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID" not in ready_stages["cutover_rollback_audit_packet_recorded"].get("environment_keys", []):
            return fail("rollback stage must require a rollback audit packet id")
        ready_no_charge_packet = ready.get("no_charge_live_domain_evidence_packet") if isinstance(ready.get("no_charge_live_domain_evidence_packet"), dict) else {}
        if ready_no_charge_packet.get("status") != "ready" or ready_no_charge_packet.get("ready_for_owner_review") is not True:
            return fail(f"ready fixture should make no-charge evidence packet ready: {ready_no_charge_packet}")
        ready_no_charge_items = {item.get("key"): item for item in ready_no_charge_packet.get("evidence_items", []) if isinstance(item, dict)}
        if set(ready_no_charge_items) != EXPECTED_NO_CHARGE_EVIDENCE_ITEMS:
            return fail(f"ready no-charge evidence items missing or unexpected: {sorted(ready_no_charge_items)}")
        if "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID" not in ready_no_charge_items["no_charge_evidence_id_recorded"].get("environment_keys", []):
            return fail("no-charge evidence packet must require a rehearsal evidence id")
        os.environ.pop("JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID", None)
        missing_packet = _build("missing-rollback-packet.sqlite", seed_subscription=True)
        missing_packet_stages = {item.get("key"): item for item in missing_packet.get("stages", []) if isinstance(item, dict)}
        if missing_packet_stages["cutover_rollback_audit_packet_recorded"].get("status") != "blocked":
            return fail("missing rollback audit packet id must block owner approval")
        os.environ["JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID"] = "rollback_audit_packet_cutover_unit"
        os.environ.pop("JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID", None)
        missing_no_charge_id = _build("missing-no-charge-evidence.sqlite", seed_subscription=True)
        missing_no_charge_packet = missing_no_charge_id.get("no_charge_live_domain_evidence_packet") if isinstance(missing_no_charge_id.get("no_charge_live_domain_evidence_packet"), dict) else {}
        missing_no_charge_items = {item.get("key"): item for item in missing_no_charge_packet.get("evidence_items", []) if isinstance(item, dict)}
        if missing_no_charge_packet.get("status") != "blocked":
            return fail("missing no-charge rehearsal evidence id must block the evidence packet")
        if missing_no_charge_items["no_charge_evidence_id_recorded"].get("status") != "blocked":
            return fail("missing no-charge rehearsal evidence id must block its evidence item")
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "authorization: bearer", "refresh_token=", "access_token=", "client_secret="):
            if forbidden in serialized:
                return fail(f"rehearsal leaked forbidden marker: {forbidden}")
        print("PASS jiejing_billing_domain_cutover_rehearsal")
        return 0
    finally:
        _restore_env(previous)


def _build(name: str, *, seed_subscription: bool = False) -> dict[str, object]:
    db_path = OUT / name
    runtime_db_path = OUT / f"runtime-{name}"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path)
    repo.initialize()
    if seed_subscription:
        fixture = repo.create_user_with_company(email="billing-domain-cutover@example.test", password="local-test-password", company_name="Billing Domain Cutover")
        company_id = fixture["company"]["company_id"]
        applied = repo.apply_billing_webhook_event(
            event={
                "provider": "stripe",
                "event_id": "evt_cutover_active",
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
    return build_billing_domain_cutover_rehearsal(settings, repo)


def _set_blocked_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
        }
    )
    return previous


def _set_ready_env() -> dict[str, str | None]:
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
            "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID": "stripe_webhook_failure_path_cutover_unit",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED": "1",
            "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED": "1",
            "JIEJING_STRIPE_INVOICE_PAID_TESTED": "1",
            "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED": "1",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID": "stripe_portal_failure_path_cutover_unit",
            "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED": "1",
            "JIEJING_CUTOVER_ROLLBACK_VERIFIED": "1",
            "JIEJING_SECRET_SCAN_PASSED": "1",
            "JIEJING_READINESS_SNAPSHOT_RECORDED": "1",
            "JIEJING_BROWSER_SMOKE_PASSED": "1",
            "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID": "rollback_audit_packet_cutover_unit",
            "JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID": "no_charge_live_domain_cutover_unit",
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
        "JIEJING_SELECTED_DOMAIN",
        "JIEJING_ROOT_DOMAIN",
        "JIEJING_PENDING_DOMAIN",
        "JIEJING_DOMAIN_REGISTRATION_STATUS",
        "JIEJING_DOMAIN_PURCHASE_STATUS",
        "JIEJING_DOMAIN_REGISTERED",
        "JIEJING_DOMAIN_PURCHASED",
        "JIEJING_TARGET_APP_HOST",
        "JIEJING_APP_HOST",
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
        "JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED",
        "JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED",
        "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED",
        "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED",
        "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
