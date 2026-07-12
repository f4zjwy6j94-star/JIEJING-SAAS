"""Production release gate for Jiejing SaaS.

This gate is a read-only go/no-go packet for the final production deployment
path. It does not call payment APIs, does not create Checkout sessions, does
not start eBay OAuth, and does not perform platform writes.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .backup_plan import build_backup_plan
from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .billing_plan import build_billing_plan
from .billing_provider_evidence_register import build_billing_provider_evidence_register
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .edge_cutover_preflight import build_edge_cutover_preflight
from .infrastructure_drivers import build_infrastructure_driver_status
from .monitoring import build_monitoring_status
from .paid_launch_approval_packet import build_paid_launch_approval_packet
from .readiness import build_product_readiness_or_degraded
from .repository import SaaSRepository


PRODUCTION_RELEASE_GATE_VERSION = "2026-07-02-production-release-gate-v1"


def build_production_release_gate(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    """Build a production launch packet that is safe for internal automation."""

    readiness = build_product_readiness_or_degraded(settings, repository)
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
    domain = build_domain_readiness(settings)
    edge = build_edge_cutover_preflight(settings)
    infrastructure = build_infrastructure_driver_status(settings)
    backup = build_backup_plan(settings, repository)
    monitoring = build_monitoring_status(settings, repository)
    billing = build_billing_plan(settings, repository)
    rehearsal = build_billing_domain_cutover_rehearsal(settings, repository)
    provider_register = build_billing_provider_evidence_register(settings, repository)
    approval_packet = build_paid_launch_approval_packet(settings, repository)

    sections = [
        _deployment_section(),
        _domain_edge_section(domain=domain, edge=edge),
        _managed_data_plane_section(settings=settings, infrastructure=infrastructure),
        _backup_restore_section(backup=backup),
        _billing_section(billing=billing, rehearsal=rehearsal, provider_register=provider_register),
        _ebay_section(evidence=evidence, approval_packet=approval_packet),
        _monitoring_section(monitoring=monitoring),
        _owner_final_section(approval_packet=approval_packet),
    ]
    blocked = [section for section in sections if section.get("status") != "ready"]
    ready_for_owner_approval = not blocked
    return {
        "contract_version": PRODUCTION_RELEASE_GATE_VERSION,
        "mode": "internal_admin_read_only_no_charge_no_write",
        "audience": "platform_internal_admin",
        "environment": settings.environment,
        "status": "ready_for_owner_approval" if ready_for_owner_approval else "blocked",
        "ready_for_owner_approval": ready_for_owner_approval,
        "summary": {
            "decision": "ready_for_owner_approval_not_auto_launch" if ready_for_owner_approval else "keep_public_launch_blocked",
            "ready_count": len(sections) - len(blocked),
            "total_count": len(sections),
            "blocked_count": len(blocked),
            "blocked_keys": [str(section.get("key") or "") for section in blocked],
            "next_step": str((blocked[0] if blocked else {}).get("key") or ""),
            "beta_ready": bool(readiness.get("beta_ready")),
            "production_ready": bool(readiness.get("production_ready")),
            "can_accept_real_customers": bool(readiness.get("can_accept_real_customers")),
            "ebay_token_refresh_success_count": _as_int(evidence.get("ebay_token_refresh_success_count")),
            "billing_ready_for_paid_launch": bool(billing.get("billing_ready_for_paid_launch")),
            "provider_register_status": provider_register.get("status") or "unknown",
            "paid_launch_approval_status": approval_packet.get("status") or "unknown",
            "backup_ready_for_paid_launch": bool(backup.get("backup_ready_for_paid_launch")),
            "monitoring_ready": bool(monitoring.get("production_monitoring_ready")),
            "domain_ready": bool(domain.get("production_domain_ready")),
            "edge_ready": edge.get("status") == "ready_for_owner_approval",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "platform_write_now_allowed": False,
            "repeat_ebay_oauth_allowed": False,
            "secret_exposed": False,
        },
        "sections": sections,
        "final_cutover_sequence": _final_cutover_sequence(sections),
        "required_external_evidence": _required_external_evidence(),
        "forbidden_actions": [
            "Do not enable public paid launch from this gate alone.",
            "Do not create Stripe Checkout Sessions while building this gate.",
            "Do not call Stripe or payment-provider APIs while building this gate.",
            "Do not run or repeat eBay OAuth from this gate.",
            "Do not perform real eBay writes, refunds, ads, procurement, price, inventory or policy changes.",
            "Do not expose payment, eBay, model or cloud secrets to frontend, reports, logs or memory.",
        ],
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "frontend_gets_ebay_token": False,
        "exports_raw_secret": False,
        "includes_raw_tokens": False,
        "secret_exposed": False,
    }


def _deployment_section() -> dict[str, Any]:
    checks = {
        "artifact_sha256_recorded": bool(re.fullmatch(r"[0-9a-fA-F]{64}", _env_text("JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256"))),
        "deployment_dry_run_passed": _env_bool("JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED"),
        "rollback_point_recorded": bool(_env_text("JIEJING_PRODUCTION_ROLLBACK_POINT_ID")),
        "post_deploy_health_smoke_passed": _env_bool("JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED"),
        "secret_scan_passed": _env_bool("JIEJING_SECRET_SCAN_PASSED"),
        "browser_smoke_passed": _env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
    }
    return _section(
        "deployment_artifact_and_rollback",
        "Deployment artifact, dry run, health smoke and rollback point",
        checks,
        env_keys=[
            "JIEJING_PRODUCTION_RELEASE_ARTIFACT_SHA256",
            "JIEJING_PRODUCTION_DEPLOYMENT_DRY_RUN_PASSED",
            "JIEJING_PRODUCTION_ROLLBACK_POINT_ID",
            "JIEJING_PRODUCTION_POST_DEPLOY_HEALTH_SMOKE_PASSED",
            "JIEJING_SECRET_SCAN_PASSED",
            "JIEJING_BROWSER_SMOKE_PASSED",
        ],
        next_action="Record the exact deploy bundle SHA256, dry-run result, rollback point, health smoke, secret scan and browser smoke before final release review.",
        verification=["tools/jiejing_prepare_public_staging_bundle.py", "tools/jiejing_staging_deploy.py", "tools/jiejing_secret_scan.py"],
        external_resource_required=False,
    )


def _domain_edge_section(*, domain: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    summary = edge.get("summary") if isinstance(edge.get("summary"), dict) else {}
    checks = {
        "stable_domain_ready": bool(domain.get("production_domain_ready")),
        "edge_preflight_ready": edge.get("status") == "ready_for_owner_approval",
        "waf_ready": bool(summary.get("waf_ready")),
        "origin_locked": bool(summary.get("origin_locked")),
        "callbacks_ready": bool(summary.get("callbacks_ready")),
        "security_headers_verified": bool(domain.get("security_headers_verified")),
    }
    return _section(
        "stable_domain_edge_origin_callbacks",
        "Stable domain, WAF, origin lock and eBay/Stripe callbacks",
        checks,
        env_keys=[
            "JIEJING_PUBLIC_BASE_URL",
            "JIEJING_STABLE_DOMAIN",
            "JIEJING_CORS_ORIGIN",
            "JIEJING_DOMAIN_DNS_VERIFIED",
            "JIEJING_TLS_VERIFIED",
            "JIEJING_EBAY_CALLBACK_VERIFIED",
            "JIEJING_STRIPE_CALLBACK_URLS_VERIFIED",
            "JIEJING_EDGE_DOMAIN_ADDED",
            "JIEJING_EDGE_DNS_PROXIED",
            "JIEJING_ORIGIN_DIRECT_IP_BLOCKED",
        ],
        next_action=str(summary.get("next_action") or "Finish stable-domain DNS/TLS/WAF/origin-lock/callback proof before final release review."),
        verification=["/domain/status", "/owner/edge-cutover-preflight", "/health/deep"],
        external_resource_required=True,
    )


def _managed_data_plane_section(*, settings: SaaSSettings, infrastructure: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "managed_postgres_selected": settings.database_engine == "postgres" and settings.database_adapter == "postgres-managed",
        "database_url_configured": settings.database_url_configured,
        "redis_queue_selected": settings.queue_provider == "redis_streams" and settings.queue_url_configured,
        "vault_enabled": settings.vault_enabled and settings.vault_provider != "secret_ref_only",
        "postgres_live_probe_passed": _env_bool("JIEJING_POSTGRES_LIVE_PROBE_PASSED"),
        "redis_live_probe_passed": _env_bool("JIEJING_REDIS_LIVE_PROBE_PASSED"),
        "vault_live_probe_passed": _env_bool("JIEJING_VAULT_LIVE_PROBE_PASSED"),
        "runtime_cutover_contract_visible": bool(infrastructure.get("postgres", {}).get("repository_runtime_switch_implemented"))
        and bool(infrastructure.get("redis", {}).get("worker_runtime_switch_implemented")),
    }
    return _section(
        "managed_data_plane_and_secret_boundary",
        "Managed Postgres, Redis queue, Vault/KMS and live probes",
        checks,
        env_keys=[
            "JIEJING_DATABASE_ENGINE",
            "JIEJING_DATABASE_ADAPTER",
            "JIEJING_DATABASE_URL",
            "JIEJING_QUEUE_PROVIDER",
            "JIEJING_QUEUE_URL",
            "JIEJING_VAULT_ENABLED",
            "JIEJING_VAULT_PROVIDER",
            "JIEJING_POSTGRES_LIVE_PROBE_PASSED",
            "JIEJING_REDIS_LIVE_PROBE_PASSED",
            "JIEJING_VAULT_LIVE_PROBE_PASSED",
        ],
        next_action="Run live Postgres, Redis and Vault probes in the target production-like network; keep raw secrets inside backend Vault/env only.",
        verification=["/infrastructure/drivers", "tools/test_jiejing_infrastructure_drivers.py", "tools/jiejing_infra_cutover_rehearsal.py"],
        external_resource_required=True,
    )


def _backup_restore_section(*, backup: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "backup_ready_for_paid_launch": bool(backup.get("backup_ready_for_paid_launch")),
        "managed_database_backup_policy": bool((backup.get("database") or {}).get("managed_database_selected")),
        "restore_drill_recorded": bool((backup.get("restore") or {}).get("restore_drill_recorded")),
        "backup_alerts_configured": bool((backup.get("alerts") or {}).get("configured")),
        "raw_secret_export_blocked": (backup.get("vault") or {}).get("raw_secret_export_allowed") is False,
    }
    return _section(
        "backup_restore_dr_and_secret_recovery",
        "Backup, restore drill, backup alerts and secret recovery",
        checks,
        env_keys=[
            "JIEJING_BACKUP_POLICY_CONFIGURED",
            "JIEJING_RESTORE_DRILL_LAST_AT",
            "JIEJING_BACKUP_ALERTS_CONFIGURED",
            "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
            "JIEJING_COS_BACKUP_ENABLED",
            "JIEJING_COS_BUCKET",
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
        ],
        next_action="Configure managed backup/PITR, run a restore drill, wire backup alerts and verify secret recovery without exporting raw secrets.",
        verification=["/backup/plan", "tools/test_jiejing_infra_cutover_rehearsal.py"],
        external_resource_required=True,
    )


def _billing_section(*, billing: dict[str, Any], rehearsal: dict[str, Any], provider_register: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "billing_ready_for_paid_launch": bool(billing.get("billing_ready_for_paid_launch")),
        "billing_rehearsal_ready": rehearsal.get("status") == "ready_for_owner_approval",
        "provider_register_ready": provider_register.get("ready_for_owner_review") is True,
        "provider_register_no_charge": provider_register.get("charge_now_allowed") is False,
        "provider_register_no_checkout": provider_register.get("creates_checkout_session") is False,
        "provider_register_no_stripe_call": provider_register.get("calls_stripe_api") is False,
        "provider_register_no_frontend_secret": provider_register.get("frontend_gets_payment_secret") is False,
    }
    return _section(
        "subscription_billing_webhook_and_quota",
        "Subscription billing, signed webhook, portal, quota and no-charge rehearsal",
        checks,
        env_keys=[
            "JIEJING_BILLING_PROVIDER",
            "JIEJING_BILLING_PLANS_PUBLISHED",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
            "JIEJING_STRIPE_SECRET_KEY",
            "JIEJING_STRIPE_WEBHOOK_SECRET",
            "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
            "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID",
            "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
        ],
        next_action="Finish live subscription provider evidence, signed webhook failure paths, no-charge live-domain rehearsal and quota lifecycle proof.",
        verification=["/billing/plans", "/owner/billing-provider-evidence-register", "/owner/billing-domain-cutover-rehearsal"],
        external_resource_required=True,
    )


def _ebay_section(*, evidence: dict[str, Any], approval_packet: dict[str, Any]) -> dict[str, Any]:
    refresh_success = _as_int(evidence.get("ebay_token_refresh_success_count"))
    checks = {
        "official_packet_present": bool(evidence.get("latest_ebay_packet_status") == "created"),
        "official_packet_source": evidence.get("latest_ebay_packet_source_mode") == "official_api",
        "backend_refresh_success_proven": refresh_success > 0,
        "clean_new_account_confirmed": _env_all(
            [
                "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
                "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
            ]
        ),
        "new_account_oauth_completed_with_owner_approval": _env_all(
            [
                "JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED",
                "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
            ]
        ),
        "fresh_product_sku_assets_declared": _env_all(
            [
                "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
                "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
                "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
            ]
        ),
        "controlled_publish_and_cleanup_recorded": _env_all(
            [
                "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
                "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
                "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
            ]
        ),
        "old_frozen_account_reuse_forbidden": approval_packet.get("old_frozen_ebay_account_reuse_allowed") is False,
        "old_demo_product_or_sku_forbidden": approval_packet.get("old_demo_product_or_sku_allowed") is False,
        "real_write_still_confirmation_gated": approval_packet.get("triggers_real_platform_write") is False,
    }
    return _section(
        "ebay_clean_account_refresh_and_write_boundary",
        "Clean eBay account, backend refresh proof, fresh product and write boundary",
        checks,
        env_keys=[
            "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
            "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
            "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED",
            "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
            "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
        ],
        next_action="Use only a clean new eBay account and fresh product/SKU/assets; prove backend Vault-backed token refresh success before real customer launch.",
        verification=["/readiness/product-saas", "tools/jiejing_new_ebay_account_low_risk_check.py --checklist-only", "audit_logs.oauth.token_refresh.executed"],
        external_resource_required=True,
        evidence_summary=f"refresh_success={refresh_success}; latest_packet={evidence.get('latest_ebay_packet_status') or 'missing'}",
    )


def _monitoring_section(*, monitoring: dict[str, Any]) -> dict[str, Any]:
    runbooks = monitoring.get("incident_runbooks") if isinstance(monitoring.get("incident_runbooks"), dict) else {}
    provider_observability = (
        monitoring.get("provider_observability") if isinstance(monitoring.get("provider_observability"), dict) else {}
    )
    checks = {
        "production_monitoring_ready": bool(monitoring.get("production_monitoring_ready")),
        "safe_access_logs_enabled": bool((monitoring.get("safe_access_logs") or {}).get("enabled")),
        "cloud_monitoring_target_ready": bool((monitoring.get("cloud_monitoring") or {}).get("target_ready")),
        "incident_runbooks_ready": bool(runbooks.get("runbook_ready")),
        "provider_latency_and_cost_monitoring_ready": bool(provider_observability.get("ready")),
        "request_body_not_logged": (monitoring.get("safe_access_logs") or {}).get("records_request_body") is False,
        "authorization_header_not_logged": (monitoring.get("safe_access_logs") or {}).get("records_authorization_header") is False,
    }
    return _section(
        "monitoring_alerts_incidents_and_customer_support",
        "Monitoring, alerts, incident runbooks and support readiness",
        checks,
        env_keys=[
            "JIEJING_CLS_ENABLED",
            "JIEJING_CLS_LOGSET_ID",
            "JIEJING_CLS_TOPIC_ID",
            "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
            "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
            "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
            "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
            "JIEJING_PROVIDER_METRICS_ENABLED",
            "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED",
            "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED",
        ],
        next_action="Enable safe access logs, cloud monitoring, alert policies and incident runbooks for OAuth, billing, database, backup and model-cost failures.",
        verification=["/monitoring/status", "tools/test_jiejing_monitoring_runbook_gate.py"],
        external_resource_required=True,
    )


def _owner_final_section(*, approval_packet: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "paid_launch_approval_packet_contract_visible": approval_packet.get("contract_version") == "2026-06-18-paid-launch-approval-packet",
        "production_release_owner_approval_recorded": bool(_env_text("JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID")),
        "public_charge_flag_reviewed": _env_bool("JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED"),
        "real_write_flag_reviewed": _env_bool("JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED"),
        "support_refund_policy_reviewed": _env_bool("JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED"),
        "merchant_surface_internal_copy_scan_passed": _env_bool("JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED"),
    }
    return _section(
        "final_owner_approval_and_launch_switch_hold",
        "Final owner approval and launch-switch hold",
        checks,
        env_keys=[
            "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID",
            "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED",
            "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED",
            "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED",
            "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED",
        ],
        next_action="Record final owner approval and keep charge/write launch switches separate until the deploy-time release step.",
        verification=["/owner/paid-launch-approval-packet", "/owner/launch-control", "node tools/codex_jiejing_all_modules_clean_smoke.js"],
        external_resource_required=False,
    )


def _section(
    key: str,
    title: str,
    checks: dict[str, bool],
    *,
    env_keys: list[str],
    next_action: str,
    verification: list[str],
    external_resource_required: bool,
    evidence_summary: str = "",
) -> dict[str, Any]:
    blocked = [name for name, ready in checks.items() if not ready]
    return {
        "key": key,
        "title": title,
        "status": "ready" if not blocked else "blocked",
        "severity": "info" if not blocked else "blocker",
        "ready_count": len(checks) - len(blocked),
        "total_count": len(checks),
        "blocked_checks": blocked,
        "checks": checks,
        "environment_keys": env_keys,
        "next_action": next_action,
        "verification": verification,
        "external_resource_required": external_resource_required,
        "evidence_summary": evidence_summary or "; ".join(f"{name}={value}" for name, value in checks.items())[:900],
        "customer_visible": False,
        "ordinary_merchant_visible": False,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "platform_write_now_allowed": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_provider_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _final_cutover_sequence(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {str(section.get("key") or ""): section for section in sections}
    sequence = [
        ("freeze_staging_baseline", ["deployment_artifact_and_rollback"]),
        ("verify_edge_data_and_backup", ["stable_domain_edge_origin_callbacks", "managed_data_plane_and_secret_boundary", "backup_restore_dr_and_secret_recovery"]),
        ("verify_paid_subscription_and_no_charge_rehearsal", ["subscription_billing_webhook_and_quota"]),
        ("verify_ebay_clean_account_and_refresh", ["ebay_clean_account_refresh_and_write_boundary"]),
        ("verify_monitoring_support_and_incident_routes", ["monitoring_alerts_incidents_and_customer_support"]),
        ("record_owner_approval_keep_switches_separate", ["final_owner_approval_and_launch_switch_hold"]),
    ]
    output: list[dict[str, Any]] = []
    for key, required_sections in sequence:
        missing = [section_key for section_key in required_sections if (by_key.get(section_key) or {}).get("status") != "ready"]
        output.append(
            {
                "key": key,
                "status": "ready" if not missing else "blocked",
                "required_sections": required_sections,
                "blocked_sections": missing,
                "public_paid_launch_allowed": False,
                "charge_now_allowed": False,
                "creates_checkout_session": False,
                "calls_stripe_api": False,
                "triggers_real_charge": False,
                "triggers_ebay_oauth": False,
                "repeat_ebay_oauth_allowed": False,
                "triggers_real_platform_write": False,
                "platform_write_now_allowed": False,
                "frontend_gets_payment_secret": False,
                "frontend_gets_provider_secret": False,
                "frontend_gets_ebay_token": False,
                "secret_exposed": False,
            }
        )
    return output


def _required_external_evidence() -> list[dict[str, Any]]:
    return [
        _evidence_item("stable_domain_edge_origin", ["JIEJING_DOMAIN_DNS_VERIFIED", "JIEJING_TLS_VERIFIED", "JIEJING_ORIGIN_DIRECT_IP_BLOCKED"]),
        _evidence_item("managed_postgres_redis_vault", ["JIEJING_POSTGRES_LIVE_PROBE_PASSED", "JIEJING_REDIS_LIVE_PROBE_PASSED", "JIEJING_VAULT_LIVE_PROBE_PASSED"]),
        _evidence_item("backup_restore_drill", ["JIEJING_BACKUP_POLICY_CONFIGURED", "JIEJING_RESTORE_DRILL_LAST_AT", "JIEJING_BACKUP_ALERTS_CONFIGURED"]),
        _evidence_item("stripe_live_billing", ["JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID", "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID"]),
        _evidence_item("new_ebay_account_refresh", ["audit_logs.oauth.token_refresh.executed", "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"]),
        _evidence_item("monitoring_incident_support", ["JIEJING_CLS_ALERT_POLICY_CONFIGURED", "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED"]),
        _evidence_item("final_owner_approval", ["JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID"]),
    ]


def _evidence_item(key: str, env_keys: list[str]) -> dict[str, Any]:
    return {
        "key": key,
        "environment_keys": env_keys,
        "secret_values_required_in_backend_only": True,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _by_key(items: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        return {}
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict)}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_all(names: list[str]) -> bool:
    return all(_env_bool(name) for name in names)


def _env_text(name: str) -> str:
    return os.environ.get(name, "").strip()
