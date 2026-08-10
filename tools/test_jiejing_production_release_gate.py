#!/usr/bin/env python3
"""Regression for the production release gate."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import STRIPE_CURRENT_API_VERSION  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.production_release_gate import (  # noqa: E402
    PRODUCTION_RELEASE_GATE_VERSION,
    _billing_section,
    _ebay_section,
    build_production_release_gate,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = Path(tempfile.mkdtemp(prefix="jiejing-production-release-gate-test-"))
EXPECTED_SECTIONS = {
    "deployment_artifact_and_rollback",
    "stable_domain_edge_origin_callbacks",
    "managed_data_plane_and_secret_boundary",
    "backup_restore_dr_and_secret_recovery",
    "mainland_wechat_payment_and_refund_controls",
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
    contradictory = _ready_mainland_payment()
    contradictory["refund_now_allowed"] = False
    malformed_section = _billing_section(
        mainland_payment=contradictory,
        approval_packet=_ready_paid_launch_packet(),
    )
    if malformed_section.get("status") != "blocked":
        return fail(f"refund-not-ready canonical state must fail closed: {malformed_section}")
    if malformed_section.get("checks", {}).get("refund_controls_ready") is not False:
        return fail(f"refund readiness blocker must remain explicit: {malformed_section}")
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

        os.environ.update(
            {
                "JIEJING_PROVIDER_METRICS_ENABLED": "1",
                "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED": "1",
                "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED": "1",
            }
        )
        legacy_only = _build("legacy-provider-booleans.sqlite")
        legacy_sections = {
            item.get("key"): item for item in legacy_only.get("sections", []) if isinstance(item, dict)
        }
        legacy_monitoring = legacy_sections.get("monitoring_alerts_incidents_and_customer_support", {})
        if legacy_monitoring.get("checks", {}).get("provider_latency_and_cost_monitoring_ready") is not False:
            return fail("legacy provider alert booleans alone must not prove production monitoring readiness")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        env_only_ebay = _ebay_section(
            evidence={
                "latest_ebay_packet_status": "created",
                "latest_ebay_packet_source_mode": "official_api",
                "ebay_token_refresh_success_count": 1,
            },
            approval_packet={
                "old_frozen_ebay_account_reuse_allowed": False,
                "old_demo_product_or_sku_allowed": False,
                "triggers_real_platform_write": False,
            },
        )
        if env_only_ebay.get("checks", {}).get("new_account_oauth_completed_with_owner_approval") is not False:
            return fail("production release gate must not accept OAuth completion env flags without backend proof")
        if env_only_ebay.get("checks", {}).get("official_packet_present") is not False:
            return fail("global or cross-store official packet evidence must not satisfy production release")
        if env_only_ebay.get("checks", {}).get("backend_refresh_success_proven") is not False:
            return fail("global or cross-store refresh count must not satisfy production release")
        if env_only_ebay.get("checks", {}).get("controlled_publish_and_cleanup_recorded") is not False:
            return fail("production release must not accept global/env publish-cleanup flags without current-store action evidence")
        cross_store_packet = _ready_paid_launch_packet()
        cross_store_packet["current_store_oauth_boundary"] = {
            **cross_store_packet["current_store_oauth_boundary"],
            "store_id_sha256": "store-a-hash",
            "connection_id_sha256": "connection-a-hash",
        }
        cross_store_packet["current_store_ebay_evidence"] = {
            **cross_store_packet["current_store_ebay_evidence"],
            "store_id_sha256": "store-b-hash",
            "connection_id_sha256": "connection-b-hash",
        }
        cross_store_section = _ebay_section(evidence={}, approval_packet=cross_store_packet)
        if cross_store_section.get("status") != "blocked":
            return fail("production release must reject all-true OAuth/evidence assembled from different store/connection hashes")
        for unsafe_count in (True, 5.0, float("nan"), float("inf"), "5", [5], {"value": 5}):
            unsafe_packet = _ready_paid_launch_packet()
            unsafe_packet["current_store_ebay_evidence"] = {
                **unsafe_packet["current_store_ebay_evidence"],
                "refresh_success_count": unsafe_count,
            }
            try:
                unsafe_section = _ebay_section(evidence={}, approval_packet=unsafe_packet)
                json.dumps(unsafe_section, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError, OverflowError) as exc:
                return fail(f"production release malformed counts must return stable JSON: {type(exc).__name__}")
            if unsafe_section.get("checks", {}).get("backend_refresh_success_proven") is not False:
                return fail("production release refresh proof must accept only genuine JSON positive integers")
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
        backup_checks = sections["backup_restore_dr_and_secret_recovery"].get("checks", {})
        if backup_checks.get("restore_drill_fresh") is not True:
            return fail(f"ready backup section should expose fresh restore-drill evidence: {backup_checks}")
        if backup_checks.get("recent_backup_probe_fresh") is not True:
            return fail(f"ready backup section should expose recent backup success evidence: {backup_checks}")
        monitoring_env_keys = set(
            sections["monitoring_alerts_incidents_and_customer_support"].get("environment_keys") or []
        )
        required_cls_evidence_keys = {
            "JIEJING_CLS_LIVE_PROBE_REQUIRED",
            "JIEJING_CLS_LIVE_PROBE_LAST_AT",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
            "JIEJING_CLS_PROBE_MAX_AGE_HOURS",
            "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED",
            "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS",
            "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES",
            "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS",
            "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES",
            "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
            "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
            "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
            "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
            "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS",
        }
        if not required_cls_evidence_keys.issubset(monitoring_env_keys):
            return fail(
                "production release monitoring evidence must name every CLS freshness input: "
                f"{sorted(required_cls_evidence_keys - monitoring_env_keys)}"
            )
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
        external_evidence = {
            item.get("key"): item
            for item in ready.get("required_external_evidence", [])
            if isinstance(item, dict)
        }
        if "wechat_pay_native_production_cutover" not in external_evidence:
            return fail(f"WeChat production evidence bucket is missing: {sorted(external_evidence)}")
        if "stripe_live_billing" in external_evidence:
            return fail("Stripe evidence must not remain a mainland production release requirement")
        _assert_unsafe_flags_false(ready, "ready gate")
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "unit-vault-token", "test-client-secret", "refresh_token="):
            if forbidden in serialized:
                return fail(f"production release gate leaked forbidden marker: {forbidden}")

        removed_stripe = {
            key: os.environ.pop(key)
            for key in list(os.environ)
            if key.startswith("JIEJING_STRIPE_")
        }
        os.environ["JIEJING_BILLING_PROVIDER"] = "manual_seed"
        try:
            no_stripe = _build("ready-without-stripe.sqlite", seed_ready_data=True)
        finally:
            os.environ.update(removed_stripe)
            os.environ["JIEJING_BILLING_PROVIDER"] = "stripe"
        no_stripe_sections = {
            item.get("key"): item for item in no_stripe.get("sections", []) if isinstance(item, dict)
        }
        if no_stripe_sections.get("mainland_wechat_payment_and_refund_controls", {}).get("status") != "ready":
            return fail(
                "missing Stripe must not block the canonical mainland production billing section: "
                f"{no_stripe_sections.get('mainland_wechat_payment_and_refund_controls')}"
            )

        os.environ["JIEJING_QUEUE_PROVIDER"] = "postgres_durable"
        os.environ.pop("JIEJING_QUEUE_URL", None)
        os.environ.pop("JIEJING_REDIS_LIVE_PROBE_PASSED", None)
        os.environ["JIEJING_POSTGRES_DURABLE_QUEUE_LIVE_PROBE_PASSED"] = "1"
        postgres_durable = _build("ready-postgres-durable.sqlite", seed_ready_data=True)
        durable_sections = {
            item.get("key"): item for item in postgres_durable.get("sections", []) if isinstance(item, dict)
        }
        durable_data_plane = durable_sections.get("managed_data_plane_and_secret_boundary", {})
        if durable_data_plane.get("status") != "ready":
            return fail(
                "production release gate should accept the production-allowed Postgres durable queue "
                f"without requiring Redis: {durable_data_plane}"
            )
        durable_external = [
            item for item in postgres_durable.get("required_external_evidence", []) if isinstance(item, dict)
        ]
        durable_queue_evidence = next(
            (item for item in durable_external if str(item.get("key") or "").startswith("managed_postgres_")),
            {},
        )
        durable_env_keys = set(durable_queue_evidence.get("environment_keys") or [])
        if "JIEJING_POSTGRES_DURABLE_QUEUE_LIVE_PROBE_PASSED" not in durable_env_keys:
            return fail(f"Postgres durable external evidence key is missing: {durable_queue_evidence}")
        if "JIEJING_REDIS_LIVE_PROBE_PASSED" in durable_env_keys:
            return fail(f"Postgres durable external evidence must not require Redis: {durable_queue_evidence}")
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
        with patch(
            "jiejing_saas.production_release_gate.build_mainland_payment_launch_status",
            return_value=_ready_mainland_payment(),
        ), patch(
            "jiejing_saas.production_release_gate.build_paid_launch_approval_packet",
            return_value=_ready_paid_launch_packet(),
        ):
            return build_production_release_gate(settings, repo)
    return build_production_release_gate(settings, repo)


def _ready_paid_launch_packet() -> dict[str, object]:
    return {
        "contract_version": "2026-07-27-paid-launch-approval-packet-v2",
        "status": "ready_for_owner_approval",
        "ready_for_owner_approval": True,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "triggers_real_platform_write": False,
        "old_frozen_ebay_account_reuse_allowed": False,
        "old_demo_product_or_sku_allowed": False,
        "current_store_oauth_boundary": {
            "status": "authorized",
            "authorized": True,
            "current_store_selected": True,
            "strong_identity_ready": True,
            "backend_provenance_ready": True,
            "connection_id_sha256": "unit-connection-hash",
            "store_id_sha256": "unit-store-hash",
            "secret_exposed": False,
        },
        "current_store_ebay_evidence": {
            "status": "ready",
            "current_store_selected": True,
            "store_id_sha256": "unit-store-hash",
            "connection_id_sha256": "unit-connection-hash",
            "official_packet_ready": True,
            "backend_worker_provenance_ready": True,
            "same_oauth_connection_ready": True,
            "account_health_ready": True,
            "refresh_success_ready": True,
            "refresh_same_connection_ready": True,
            "refresh_success_count": 1,
            "new_account_action_evidence": {
                "contract_version": "2026-06-18-new-ebay-account-low-risk-smoke",
                "company_store_bound": True,
                "publish_health_confirmation_ready": True,
                "controlled_real_publish_ready": True,
                "post_publish_cleanup_ready": True,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        },
        "steps": [
            {"key": "wechat_pay_native_cutover", "status": "ready", "blocked_by": []},
            {"key": "new_ebay_account_low_risk_smoke", "status": "ready", "blocked_by": []},
        ],
    }


def _ready_mainland_payment() -> dict[str, object]:
    return {
        "contract_version": "2026-07-27-mainland-payment-launch-v1",
        "market": "mainland_china",
        "primary_provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "configuration": {"required_count": 9, "completed_count": 9, "complete": True},
        "code_capabilities": {
            "signed_payment_callback_implemented": True,
            "signed_refund_callback_implemented": True,
            "real_order_creation_implemented": True,
            "authenticated_order_query_implemented": True,
            "quota_entitlement_persistence_implemented": True,
            "high_risk_confirmation_boundary_implemented": True,
        },
        "acceptance_evidence": {
            "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
            "provider": "wechat_pay_native",
            "acceptance_kind": "owner_approved_one_cny_live_acceptance",
            "controlled_acceptance_proven": True,
            "verified_paid_order_count": 1,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "calls_external_payment_api": False,
            "secret_exposed": False,
        },
        "controlled_acceptance_proven": True,
        "provider_checkout_ready": True,
        "production_environment": True,
        "refund_now_allowed": True,
        "mainland_payment_ready_for_owner_approval": True,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "calls_stripe_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


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
    now = datetime.now(timezone.utc).replace(microsecond=0)
    repo.acquire_provider_monitoring_lease(
        scheduler_key="provider-monitor",
        owner_hash="production-release-gate-fixture",
        lease_seconds=300,
        now_epoch=int(now.timestamp()) - 60,
    )
    repo.complete_provider_monitoring_evaluation(
        scheduler_key="provider-monitor",
        owner_hash="production-release-gate-fixture",
        evaluated_at=(now - timedelta(minutes=1)).isoformat(),
        exported_at=(now - timedelta(minutes=1)).isoformat(),
        outcome="exported",
        snapshot={
            "event_type": "jiejing_provider_monitor_aggregate",
            "contract_version": "2026-07-17-provider-monitor-aggregate-v1",
            "environment": "staging",
            "probe": False,
            "reliability_status": "insufficient_data",
            "reliability_evaluated_count": 0,
            "reliability_attention_count": 0,
            "reliability_critical_count": 0,
            "cost_status": "healthy",
            "cost_coverage_complete": True,
            "cost_budget_configured": True,
            "cost_total_minor": 0,
        },
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
    now = datetime.now(timezone.utc).replace(microsecond=0)
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
            "JIEJING_RESTORE_DRILL_LAST_AT": (now - timedelta(days=1)).isoformat(),
            "JIEJING_BACKUP_ALERTS_CONFIGURED": "1",
            "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "1",
            "JIEJING_COS_BACKUP_ENABLED": "1",
            "JIEJING_COS_BUCKET": "jiejing-release-backup",
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT": (now - timedelta(hours=1)).isoformat(),
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
            "JIEJING_CLS_LIVE_PROBE_REQUIRED": "1",
            "JIEJING_CLS_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=2)).isoformat(),
            "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED": "1",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=1)).isoformat(),
            "JIEJING_CLS_PROBE_MAX_AGE_HOURS": "24",
            "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "1",
            "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "1",
            "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "1",
            "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "1",
            "JIEJING_PROVIDER_METRICS_ENABLED": "1",
            "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED": "1",
            "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED": "1",
            "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED": "1",
            "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS": "300",
            "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES": "30",
            "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS": "24",
            "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES": "15",
            "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR": "10000",
            "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR": "20000",
            "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
            "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
            "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS": "7",
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
