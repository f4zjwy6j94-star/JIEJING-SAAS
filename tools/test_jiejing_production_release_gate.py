#!/usr/bin/env python3
"""Regression for the production release gate."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import STRIPE_CURRENT_API_VERSION  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.production_release_gate import PRODUCTION_RELEASE_GATE_VERSION, build_production_release_gate  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-production-release-gate-test"
EXPECTED_SECTIONS = {
    "deployment_artifact_and_rollback",
    "stable_domain_edge_origin_callbacks",
    "managed_data_plane_and_secret_boundary",
    "backup_restore_dr_and_secret_recovery",
    "subscription_billing_webhook_and_quota",
    "ebay_clean_account_refresh_and_write_boundary",
    "monitoring_alerts_incidents_and_customer_support",
    "final_owner_approval_and_launch_switch_hold",
}
UNSAFE_FLAGS = (
    "public_paid_launch_allowed",
    "charge_now_allowed",
    "creates_checkout_session",
    "calls_stripe_api",
    "triggers_real_charge",
    "triggers_ebay_oauth",
    "repeat_ebay_oauth_allowed",
    "triggers_real_platform_write",
    "platform_write_now_allowed",
    "frontend_gets_payment_secret",
    "frontend_gets_provider_secret",
    "frontend_gets_ebay_token",
    "secret_exposed",
)


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
        if blocked.get("contract_version") != PRODUCTION_RELEASE_GATE_VERSION:
            return fail("production release gate contract missing")
        if blocked.get("status") != "blocked" or blocked.get("ready_for_owner_approval") is not False:
            return fail(f"blocked fixture should stay blocked: {blocked.get('summary')}")
        sections = {item.get("key"): item for item in blocked.get("sections", []) if isinstance(item, dict)}
        if set(sections) != EXPECTED_SECTIONS:
            return fail(f"production release sections missing or unexpected: {sorted(sections)}")
        if sections["ebay_clean_account_refresh_and_write_boundary"].get("checks", {}).get("backend_refresh_success_proven") is not False:
            return fail("blocked gate must not invent eBay refresh proof")
        _assert_unsafe_flags_false(blocked, "blocked gate")
        for item in blocked.get("sections", []):
            if isinstance(item, dict):
                _assert_unsafe_flags_false(item, f"blocked section {item.get('key')}")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        ready = _build("ready.sqlite", seed_ready_data=True)
        if ready.get("status") != "ready_for_owner_approval" or ready.get("ready_for_owner_approval") is not True:
            return fail(f"ready fixture should reach owner approval, not launch: {ready.get('summary')}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("decision") != "ready_for_owner_approval_not_auto_launch":
            return fail(f"ready fixture should not auto-launch: {summary}")
        if summary.get("ebay_token_refresh_success_count") != 1:
            return fail(f"ready fixture must use backend refresh audit proof: {summary}")
        sections = {item.get("key"): item for item in ready.get("sections", []) if isinstance(item, dict)}
        for key in EXPECTED_SECTIONS:
            if sections.get(key, {}).get("status") != "ready":
                return fail(f"ready section should be ready: {key} {sections.get(key)}")
        if len(ready.get("final_cutover_sequence", [])) != 6:
            return fail("production release gate should expose final cutover sequence")
        for step in ready.get("final_cutover_sequence", []):
            if not isinstance(step, dict):
                continue
            if step.get("status") != "ready":
                return fail(f"ready cutover step should be ready: {step}")
            _assert_unsafe_flags_false(step, f"ready cutover step {step.get('key')}")
        if len(ready.get("required_external_evidence", [])) < 6:
            return fail("production release gate should list external evidence buckets")
        _assert_unsafe_flags_false(ready, "ready gate")
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "unit-vault-token", "test-client-secret", "refresh_token="):
            if forbidden in serialized:
                return fail(f"production release gate leaked forbidden marker: {forbidden}")
        print("PASS jiejing_production_release_gate")
        return 0
    finally:
        _restore_env(previous)


def _assert_unsafe_flags_false(payload: dict[str, object], label: str) -> None:
    for flag in UNSAFE_FLAGS:
        if payload.get(flag) is not False:
            raise AssertionError(f"{label} unsafe flag should be false: {flag}")


def _build(name: str, *, seed_ready_data: bool = False) -> dict[str, object]:
    db_path = OUT / name
    runtime_db_path = OUT / f"runtime-{name}"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path, database_engine="sqlite", database_url="")
    repo.initialize()
    if seed_ready_data:
        _seed_ready_repository(repo)
    return build_production_release_gate(settings, repo)


def _seed_ready_repository(repo: SaaSRepository) -> None:
    account = repo.create_user_with_company(
        email="production-release-ready@example.test",
        password="local-test-password",
        company_name="Production Release Ready",
    )
    user = account["user"]
    company = account["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "release-ready-store", "marketplace": "EBAY_US"},
    )
    secret_ref = repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={"credential_owner": "jiejing_saas_backend", "refresh_token_stored_in_database": False},
    )
    repo.create_platform_connection(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "purpose": "ebay_refresh_token",
            "secret_ref": secret_ref["secret_ref"],
            "metadata": {"credential_source": "jiejing_vault_secret_ref"},
        },
    )
    repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "created",
            "resource_count": 6,
            "present_resource_keys": [
                "store_profile",
                "account_business_policies",
                "inventory_and_offers",
                "orders_and_fulfillment",
                "finances",
                "taxonomy_listing_metadata",
            ],
            "missing_resource_keys": [],
            "safe_for_real_platform_write": False,
            "secret_exposed": False,
        },
    )
    repo.write_audit(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        actor_type="system",
        action_type="oauth.token_refresh.executed",
        target_type="store",
        target_id=store["store_id"],
        summary="eBay token refresh proof recorded through backend Vault-backed adapter.",
        details={
            "ok": True,
            "status": "refreshed",
            "source": "backend_vault_secret_ref_refresh",
            "secret_ref_present": True,
            "access_token_returned_to_frontend": False,
            "refresh_token_returned_to_frontend": False,
            "secret_exposed": False,
        },
    )
    repo.apply_billing_webhook_event(
        event={
            "provider": "stripe",
            "event_id": "evt_release_gate_unit",
            "event_type": "customer.subscription.updated",
            "company_id": company["company_id"],
            "provider_customer_id": "cus_release_gate_unit",
            "provider_subscription_id": "sub_release_gate_unit",
            "provider_plan_id": "price_starter_live_unit",
            "plan_key": "starter",
            "subscription_status": "active",
            "quota_recalculation_required": True,
            "payment_attention_required": False,
            "secret_exposed": False,
        }
    )


def _set_blocked_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    _clear_keys()
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SAAS_SESSION_SECRET": "release-gate-blocked-session-secret",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
        }
    )
    return previous


def _set_ready_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    _clear_keys()
    stable = "https://app.jiejing.example"
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SAAS_SESSION_SECRET": "release-gate-ready-session-secret",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:placeholder@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "redis_streams",
            "JIEJING_QUEUE_URL": "redis://redis:6379/0",
            "JIEJING_VAULT_ENABLED": "1",
            "JIEJING_VAULT_PROVIDER": "vault",
            "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "1",
            "JIEJING_VAULT_ADDR": "https://vault.example.test",
            "JIEJING_VAULT_TOKEN": "unit-vault-token",
            "JIEJING_EBAY_CLIENT_ID": "test-client-id",
            "JIEJING_EBAY_CLIENT_SECRET": "test-client-secret",
            "JIEJING_EBAY_RU_NAME": "test-ru-name",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "1",
            "JIEJING_EBAY_READ_ONLY_LIVE": "1",
            "JIEJING_POSTGRES_LIVE_PROBE_PASSED": "1",
            "JIEJING_REDIS_LIVE_PROBE_PASSED": "1",
            "JIEJING_VAULT_LIVE_PROBE_PASSED": "1",
            "JIEJING_BACKUP_POLICY_CONFIGURED": "1",
            "JIEJING_RESTORE_DRILL_LAST_AT": "2026-07-02T00:00:00Z",
            "JIEJING_BACKUP_ALERTS_CONFIGURED": "1",
            "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "1",
            "JIEJING_COS_BACKUP_ENABLED": "1",
            "JIEJING_COS_BUCKET": "jiejing-release-backup",
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT": "2026-07-02T00:00:00Z",
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
            "JIEJING_SELECTED_DOMAIN": "jiejing.example",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "registered",
            "JIEJING_CORS_ORIGIN": stable,
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
            "JIEJING_EDGE_PROVIDER": "cloudflare",
            "JIEJING_EDGE_DOMAIN_ADDED": "1",
            "JIEJING_EDGE_DNS_PROXIED": "1",
            "JIEJING_BOT_PROTECTION_ENABLED": "1",
            "JIEJING_WAF_RATE_LIMITS_ENABLED": "1",
            "JIEJING_AI_CRAWLER_CONTROL_ENABLED": "1",
            "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "1",
            "JIEJING_ORIGIN_HTTP_HTTPS_EDGE_ONLY": "1",
            "JIEJING_ORIGIN_DIRECT_IP_BLOCKED": "1",
            "JIEJING_ORIGIN_SSH_OPERATOR_ONLY": "1",
            "JIEJING_ORIGIN_EDGE_IP_ALLOWLIST_SOURCE": "cloudflare_ips",
            "JIEJING_STRIPE_CALLBACK_URLS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRICES_VERIFIED": "1",
            "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG": "1",
            "JIEJING_STRIPE_ACCOUNT_ACTIVATED": "1",
            "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED": "1",
            "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID": "stripe_go_live_checklist_release_unit",
            "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED": "1",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED": "1",
            "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED": "1",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID": "stripe_tax_invoice_receipt_release_unit",
            "JIEJING_STRIPE_WEBHOOK_API_VERSION": STRIPE_CURRENT_API_VERSION,
            "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED": "1",
            "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID": "stripe_webhook_failure_release_unit",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED": "1",
            "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED": "1",
            "JIEJING_STRIPE_INVOICE_PAID_TESTED": "1",
            "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED": "1",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID": "stripe_portal_failure_release_unit",
            "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED": "1",
            "JIEJING_NO_CHARGE_CHECKOUT_RETURN_URL_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_PORTAL_RETURN_URL_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED": "1",
            "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID": "no_charge_release_unit",
            "JIEJING_CUTOVER_ROLLBACK_VERIFIED": "1",
            "JIEJING_SECRET_SCAN_PASSED": "1",
            "JIEJING_READINESS_SNAPSHOT_RECORDED": "1",
            "JIEJING_BROWSER_SMOKE_PASSED": "1",
            "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID": "rollback_release_unit",
            "JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED": "1",
            "JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID": "final_smoke_release_unit",
            "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID": "paid_launch_owner_release_unit",
            "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN": "1",
            "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED": "1",
            "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED": "1",
            "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED": "1",
            "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED": "1",
            "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED": "1",
            "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE": "1",
            "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED": "1",
            "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY": "1",
            "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED": "1",
            "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED": "1",
            "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED": "1",
            "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED": "1",
            "JIEJING_CLS_ENABLED": "1",
            "JIEJING_CLS_REGION": "ap-hongkong",
            "JIEJING_CLS_LOGSET_ID": "release-logset",
            "JIEJING_CLS_TOPIC_ID": "release-topic",
            "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "1",
            "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "1",
            "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "1",
            "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "1",
            "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256": "a" * 64,
            "JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED": "1",
            "JIEJING_PRODUCTION_ROLLBACK_POINT_ID": "rollback_point_release_unit",
            "JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED": "1",
            "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID": "owner_final_release_unit",
            "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED": "1",
            "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED": "1",
            "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED": "1",
            "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED": "1",
        }
    )
    return previous


def _keys() -> list[str]:
    return [
        key
        for key in os.environ
        if key.startswith("JIEJING_")
    ] + ["TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY"]


def _clear_keys() -> None:
    for key in list(os.environ):
        if key.startswith("JIEJING_") or key in {"TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY"}:
            os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    _clear_keys()
    for key, value in previous.items():
        if value is not None:
            os.environ[key] = value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        raise SystemExit(fail(str(exc)))
