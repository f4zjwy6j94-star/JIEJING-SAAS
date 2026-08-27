"""Commercial launch gate for Jiejing SaaS."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from .account_health import build_account_health_snapshot
from .backup_plan import build_backup_plan
from .billing_plan import build_billing_plan
from .billing_payment_options import (
    build_mainland_payment_launch_status,
    validate_mainland_payment_launch_for_public,
)
from .billing_wechat_pay_rehearsal import (
    WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION,
    WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID,
    WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE,
    current_deployment_build_artifact_id,
)
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .infrastructure_drivers import build_infrastructure_driver_status
from .model_value_gate import build_model_value_gate
from .monitoring import build_monitoring_status
from .readiness import build_product_readiness
from .repository import SaaSRepository
from .vault_adapter import build_vault_adapter_contract


NEW_EBAY_ACCOUNT_BOUNDARY_FLAGS = [
    "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
    "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
]
NEW_EBAY_FRESH_PRODUCT_FLAGS = [
    "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
    "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
    "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
]
NEW_EBAY_PUBLISH_CONFIRMATION_FLAGS = [
    "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
    "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
]
NEW_EBAY_REAL_PUBLISH_FLAGS = [
    "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
]
NEW_EBAY_CLEANUP_FLAGS = [
    "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
]


def build_commercial_launch_gate(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    readiness = build_product_readiness(settings, repository)
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else repository.product_readiness_evidence()
    counts = readiness.get("counts") if isinstance(readiness.get("counts"), dict) else repository.system_counts()
    infrastructure = build_infrastructure_driver_status(settings)
    backup = build_backup_plan(settings, repository)
    legacy_billing = build_billing_plan(settings, repository)
    mainland_payment = validate_mainland_payment_launch_for_public(
        build_mainland_payment_launch_status(settings, repository)
    )
    billing = {
        **legacy_billing,
        "mainland_payment_launch": mainland_payment,
        "wechat_zero_charge_rehearsal_evidence": _wechat_zero_charge_rehearsal_evidence(
            repository=repository,
            company_id=company_id,
        ),
    }
    model_value = build_model_value_gate(settings, repository)
    monitoring = build_monitoring_status(settings, repository)
    domain = build_domain_readiness(settings)
    vault = build_vault_adapter_contract(settings)
    current_store_ebay_evidence = build_current_store_ebay_evidence(
        repository=repository,
        company_id=company_id,
        store_id=store_id,
    )
    current_store_oauth = (
        current_store_ebay_evidence.get("oauth_boundary")
        if isinstance(current_store_ebay_evidence.get("oauth_boundary"), dict)
        else {}
    )
    current_store_action_evidence = (
        current_store_ebay_evidence.get("new_account_action_evidence")
        if isinstance(current_store_ebay_evidence.get("new_account_action_evidence"), dict)
        else {}
    )
    current_store_action_context_ready = bool(
        current_store_ebay_evidence.get("current_store_selected") is True
        and current_store_action_evidence.get("company_store_bound") is True
    )
    current_store_publish_health_ready = bool(
        current_store_action_context_ready
        and current_store_action_evidence.get("publish_health_confirmation_ready") is True
    )
    current_store_controlled_publish_ready = bool(
        current_store_action_context_ready
        and current_store_action_evidence.get("controlled_real_publish_ready") is True
    )
    current_store_cleanup_ready = bool(
        current_store_action_context_ready
        and current_store_action_evidence.get("post_publish_cleanup_ready") is True
    )
    groups = [
        _group(
            "official_ebay_read_loop",
            "Official eBay read-only loop",
            current_store_ebay_evidence.get("official_packet_ready") is True,
            "Connect seller account, keep OAuth callback complete, and preserve the six-resource official packet.",
            evidence={
                "packet_id_sha256": current_store_ebay_evidence.get("packet_id_sha256") or "",
                "present_resource_keys": current_store_ebay_evidence.get("present_resource_keys", []),
                "missing_resource_keys": current_store_ebay_evidence.get("missing_resource_keys", []),
                "backend_worker_provenance_ready": current_store_ebay_evidence.get("backend_worker_provenance_ready") is True,
                "same_oauth_connection_ready": current_store_ebay_evidence.get("same_oauth_connection_ready") is True,
            },
        ),
        _group(
            "managed_database_queue",
            "Managed Postgres and queue",
            bool(infrastructure.get("ready_for_runtime_cutover")),
            "Run live Postgres and Redis/cloud-queue probes, migrate data, then cut repository and worker runtime over.",
            evidence={
                "postgres_dependency": (infrastructure.get("postgres") or {}).get("dependency", {}),
                "redis_dependency": (infrastructure.get("redis") or {}).get("dependency", {}),
                "cutover_blockers": infrastructure.get("cutover_blockers", []),
            },
        ),
        _group(
            "managed_secret_boundary",
            "Managed Vault/KMS",
            _vault_ready(settings, vault),
            "Use managed Vault/KMS for production secret resolution; keep frontend and Runtime away from raw secrets.",
            evidence={
                "vault_provider": settings.vault_provider,
                "vault_enabled": settings.vault_enabled,
                "available_adapters": [item.get("key") for item in vault.get("available_adapters", [])],
            },
        ),
        _group(
            "stable_domain_tls",
            "Stable domain, TLS, callback, and CORS",
            bool(domain.get("production_domain_ready")),
            "Point a stable HTTPS domain at the edge, align CORS and eBay callback, then verify deployment hardening.",
            evidence={
                "stable_domain": domain.get("stable_domain"),
                "dns_verified": domain.get("dns_verified"),
                "tls_verified": domain.get("tls_verified"),
                "ebay_callback_verified": domain.get("ebay_callback_verified"),
                "cors_origin_aligned": domain.get("cors_origin_aligned"),
                "blockers": domain.get("blockers", []),
            },
        ),
        _group(
            "backup_restore",
            "Backup, restore, and recovery",
            bool(backup.get("backup_ready_for_paid_launch")),
            "Configure managed backup/PITR, record restore drill evidence, and alert on backup failures.",
            evidence={"blockers": backup.get("blockers", []), "restore": backup.get("restore", {})},
        ),
        _group(
            "monitoring_alerting",
            "Monitoring and alerting",
            _monitoring_ready(monitoring),
            "Keep safe access logs and wire OAuth, Vault, eBay sync, queue, model, and backup alerts.",
            evidence={
                "safe_access_logs": monitoring.get("safe_access_logs", {}),
                "alert_count": len(monitoring.get("alert_contracts", []) or []),
            },
        ),
        _group(
            "billing_quota",
            "Mainland WeChat payment and quota",
            mainland_payment.get("mainland_payment_ready_for_owner_approval") is True,
            "Complete backend-only WeChat production configuration, verified payment/refund evidence, and merchant-visible quota enforcement while public charging stays closed.",
            evidence={
                "provider": "wechat_pay_native",
                "mainland_payment_ready_for_owner_approval": (
                    mainland_payment.get("mainland_payment_ready_for_owner_approval") is True
                ),
                "provider_configured": mainland_payment.get("provider_configured") is True,
                "controlled_acceptance_proven": mainland_payment.get("controlled_acceptance_proven") is True,
                "verified_paid_order_count": _safe_nonnegative_int(
                    mainland_payment.get("verified_paid_order_count")
                ),
                "public_charging_allowed": False,
                "next_paid_launch_blocker": mainland_payment.get("next_paid_launch_blocker") or "",
            },
        ),
        _group(
            "publish_safety_system",
            "Publishing safety report",
            current_store_publish_health_ready,
            "Keep category, item specifics, images, VeRO/IP, prohibited terms, GPSR, location, policy, seller limits, fees and profit in the merchant-visible publish health report.",
            evidence={
                "confirmation_count": _safe_nonnegative_int(counts.get("confirmations")),
                "execution_result_count": _safe_nonnegative_int(counts.get("execution_results")),
                "official_packet_ready": _official_packet_ready(evidence),
                "red_items_block_publish": True,
                "real_writes_confirmation_gated": True,
                "current_store_action_evidence_required": True,
                "current_store_publish_health_ready": current_store_publish_health_ready,
            },
        ),
        _group(
            "account_health_incident_mode",
            "Account health incident mode",
            current_store_ebay_evidence.get("account_health_ready") is True,
            "Use the current-store official packet and fail closed on restricted, suspended, payout-hold, quota-limited, or unknown seller health.",
            evidence={
                "status": current_store_ebay_evidence.get("account_health_status") or "unknown",
                "incident_mode": current_store_ebay_evidence.get("incident_mode") is True,
                "can_execute_real_writes": current_store_ebay_evidence.get("can_execute_real_writes") is True,
                "same_packet_ready": current_store_ebay_evidence.get("account_health_same_packet_ready") is True,
            },
        ),
        _group(
            "store_sync_visibility",
            "Store sync visibility",
            current_store_ebay_evidence.get("official_packet_ready") is True,
            "Show store name, product/offer/order/policy counts, latest sync time and packet id before any IP or publishing claim.",
            evidence={
                "packet_id_sha256": current_store_ebay_evidence.get("packet_id_sha256") or "",
                "present_resource_keys": current_store_ebay_evidence.get("present_resource_keys", []),
                "store_count": _safe_nonnegative_int(counts.get("stores")),
                "platform_connection_count": _safe_nonnegative_int(counts.get("platform_connections")),
            },
        ),
        _group(
            "post_publish_cockpit",
            "Post-publish cockpit",
            current_store_controlled_publish_ready and current_store_cleanup_ready,
            "After publish, run 1h, 24h and 7d reviews for exposure, clicks, watchers, sales, fees, profit and support risk; price, inventory, end listing and ads still require confirmation.",
            evidence={
                "execution_result_count": _safe_nonnegative_int(counts.get("execution_results")),
                "review_windows": ["1h", "24h", "7d"],
                "real_changes_confirmation_gated": True,
                "current_store_action_evidence_required": True,
                "current_store_controlled_publish_ready": current_store_controlled_publish_ready,
                "current_store_cleanup_ready": current_store_cleanup_ready,
            },
        ),
        _group(
            "model_agent_value",
            "Model-backed Agent value",
            bool(model_value.get("ready_for_paid_value_claim")),
            "Prove Market Report and Listing Package with live model output over sanitized official packets.",
            evidence={
                "live_model_report_types": (model_value.get("evidence") or {}).get("live_model_report_types", []),
                "blockers": model_value.get("blockers", []),
            },
        ),
        _group(
            "ebay_token_refresh_vault_adapter",
            "eBay Vault-backed token refresh",
            (
                _readiness_status_ready(readiness, "ebay_token_refresh", {"vault_backed_refresh_adapter_ready"})
                and current_store_ebay_evidence.get("refresh_success_ready") is True
            ),
            "Prove backend-only refresh through the Vault/KMS secret_ref adapter; never expose access or refresh tokens to frontend, Runtime, reports or memory.",
            evidence={
                "readiness_status": _readiness_item(readiness, "ebay_token_refresh").get("status", ""),
                "readiness_severity": _readiness_item(readiness, "ebay_token_refresh").get("severity", ""),
                "secret_refs_present": bool(evidence.get("ebay_secret_refs")),
                "successful_refresh_probe_count": _safe_nonnegative_int(current_store_ebay_evidence.get("refresh_success_count")),
                "latest_successful_refresh_probe_at": current_store_ebay_evidence.get("latest_refresh_success_at") or "",
                "same_oauth_connection_ready": current_store_ebay_evidence.get("refresh_same_connection_ready") is True,
                "frontend_gets_raw_token": False,
                "runtime_gets_raw_token": False,
            },
        ),
        _group(
            "new_ebay_account_low_risk_smoke",
            "Clean new eBay account smoke",
            (
                current_store_publish_health_ready
                and current_store_controlled_publish_ready
                and current_store_cleanup_ready
            ),
            "After the merchant has a clean new eBay seller account, run the low-risk sequence: new OAuth, official packet, account health, publish health, confirmation center, real publish, cockpit and cleanup.",
            evidence={
                "old_frozen_account_reuse_allowed": False,
                "new_account_smoke_passed": bool(
                    current_store_publish_health_ready
                    and current_store_controlled_publish_ready
                    and current_store_cleanup_ready
                ),
                "current_store_action_evidence_required": True,
                "publish_confirmation_id_sha256": current_store_action_evidence.get("publish_confirmation_id_sha256") or "",
                "publish_execution_id_sha256": current_store_action_evidence.get("publish_execution_id_sha256") or "",
                "cleanup_execution_id_sha256": current_store_action_evidence.get("cleanup_execution_id_sha256") or "",
                "checklist_tool": "tools/jiejing_new_ebay_account_low_risk_check.py",
            },
        ),
        _group(
            "legal_risk_boundary",
            "Commercial responsibility boundary",
            _legal_risk_boundary_ready(),
            "Publish privacy policy, terms, risk disclosure and merchant confirmation language so platform-account risk, billing, audit and responsibility boundaries are explicit.",
            evidence={
                "privacy_policy_verified": _env_bool("JIEJING_PRIVACY_POLICY_VERIFIED"),
                "terms_verified": _env_bool("JIEJING_TERMS_VERIFIED"),
                "risk_disclosure_verified": _env_bool("JIEJING_RISK_DISCLOSURE_VERIFIED"),
                "confirmation_terms_visible": _env_bool("JIEJING_CONFIRMATION_TERMS_VISIBLE"),
            },
        ),
        _group(
            "final_commercial_smoke",
            "Final commercial smoke",
            _env_bool("JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED"),
            "Before charging publicly, run and record register, login, connect eBay, generate packet, report, confirmation center, real execution and audit-return smoke.",
            evidence={
                "register_login_connect_ebay_packet_report_confirm_execute_audit": _env_bool("JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED"),
                "smoke_evidence_id": os.environ.get("JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID", "").strip(),
            },
        ),
    ]
    blockers = [item for item in groups if item["status"] != "ready"]
    paid_launch_ready = settings.is_production_like and not blockers and readiness.get("production_ready") is True
    action_plan = _build_launch_action_plan(
        groups=groups,
        readiness=readiness,
        billing=billing,
        domain=domain,
        monitoring=monitoring,
        evidence=evidence,
        counts=counts,
        paid_launch_ready=paid_launch_ready,
        current_store_oauth=current_store_oauth,
        current_store_ebay_evidence=current_store_ebay_evidence,
    )
    return {
        "contract_version": "2026-05-18-c-class-commercial-launch-gate",
        "environment": settings.environment,
        "paid_commercial_launch_ready": paid_launch_ready,
        "seed_merchant_beta_ready": _seed_beta_ready(groups),
        "readiness": {
            "production_ready": readiness.get("production_ready"),
            "beta_ready": readiness.get("beta_ready"),
            "blocker_count": _safe_nonnegative_int(readiness.get("blocker_count")),
            "warning_count": _safe_nonnegative_int(readiness.get("warning_count")),
        },
        "groups": groups,
        "current_store_oauth_boundary": current_store_oauth,
        "current_store_ebay_evidence": current_store_ebay_evidence,
        "launch_action_plan": action_plan,
        "prelaunch_deferred_strategy": action_plan.get("prelaunch_deferred_strategy", {}),
        "commercial_hardening_drills": action_plan.get("commercial_hardening_drills", []),
        "new_ebay_account_smoke_runbook": action_plan.get("new_ebay_account_smoke_runbook", []),
        "paid_launch_cutover_checklist": action_plan.get("paid_launch_cutover_checklist", []),
        "paid_launch_cutover_decision": action_plan.get("paid_launch_cutover_decision", {}),
        "blockers": [item["key"] for item in blockers],
        "next_actions": [item["next_action"] for item in blockers][:8],
        "operator_or_paid_resource_required": [
            item["key"]
            for item in groups
            if item["key"] in {
                "managed_database_queue",
                "managed_secret_boundary",
                "stable_domain_tls",
                "backup_restore",
                "billing_quota",
                "ebay_token_refresh_vault_adapter",
                "new_ebay_account_low_risk_smoke",
                "legal_risk_boundary",
                "publish_safety_system",
                "store_sync_visibility",
                "post_publish_cockpit",
                "model_agent_value",
                "final_commercial_smoke",
            }
            and item["status"] != "ready"
        ],
        "runtime_gets_raw_ebay_token": False,
        "frontend_gets_raw_secret": False,
        "real_platform_writes_enabled": settings.effective_real_platform_writes_enabled,
        "secret_exposed": False,
    }


def _group(key: str, label: str, ready: bool, next_action: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "ready" if ready else "blocked",
        "next_action": next_action,
        "evidence": evidence,
        "secret_exposed": False,
    }


def build_current_store_ebay_evidence(
    *,
    repository: SaaSRepository,
    company_id: str | None,
    store_id: str | None,
) -> dict[str, Any]:
    oauth_boundary = (
        repository.current_ebay_read_only_oauth_boundary(company_id=company_id, store_id=store_id)
        if company_id
        else {
            "status": "current_store_unselected",
            "authorized": False,
            "current_store_selected": False,
            "strong_identity_ready": False,
            "backend_provenance_ready": False,
            "connection_id_sha256": "",
            "secret_exposed": False,
        }
    )
    return {
        **_build_current_store_ebay_evidence(
            repository=repository,
            company_id=company_id,
            store_id=store_id,
            oauth_boundary=oauth_boundary,
        ),
        "oauth_boundary": oauth_boundary,
        "secret_exposed": False,
    }


def build_current_store_ebay_refresh_evidence(
    *,
    repository: SaaSRepository,
    company_id: str | None,
    store_id: str | None,
) -> dict[str, Any]:
    """Build the small merchant-safe proof used by the explicit refresh action.

    The full commercial launch gate joins every launch domain and can be slow on
    a live store.  This proof deliberately reads only the selected OAuth
    boundary and its latest backend refresh audit.
    """

    base = {
        "status": "blocked",
        "current_store_selected": False,
        "authorized": False,
        "strong_identity_ready": False,
        "backend_provenance_ready": False,
        "store_id_sha256": "",
        "connection_id_sha256": "",
        "refresh_success_ready": False,
        "refresh_same_connection_ready": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    normalized_company_id = str(company_id or "").strip()
    selected_store_id = str(store_id or "").strip()
    if not normalized_company_id or not selected_store_id:
        return base
    store = repository.get_store_for_company(
        company_id=normalized_company_id,
        store_id=selected_store_id,
    )
    if not store or str(store.get("platform") or "").strip().lower() != "ebay":
        return base

    store_hash = hashlib.sha256(selected_store_id.encode("utf-8")).hexdigest()
    oauth_boundary = repository.current_ebay_read_only_oauth_boundary(
        company_id=normalized_company_id,
        store_id=selected_store_id,
    )
    connection_hash = str(oauth_boundary.get("connection_id_sha256") or "").strip().lower()
    oauth_ready = bool(
        oauth_boundary.get("authorized") is True
        and oauth_boundary.get("current_store_selected") is True
        and oauth_boundary.get("strong_identity_ready") is True
        and oauth_boundary.get("backend_provenance_ready") is True
        and str(oauth_boundary.get("store_id_sha256") or "").strip().lower() == store_hash
        and _is_sha256(connection_hash)
        and oauth_boundary.get("secret_exposed") is False
    )
    refresh_audit = repository.find_latest_audit_log_by_target(
        company_id=normalized_company_id,
        store_id=selected_store_id,
        action_type="oauth.token_refresh.executed",
        target_type="store",
        target_id=selected_store_id,
    )
    refresh_details = (
        refresh_audit.get("details")
        if isinstance(refresh_audit, dict) and isinstance(refresh_audit.get("details"), dict)
        else {}
    )
    refresh_same_connection_ready = bool(
        oauth_ready
        and refresh_audit
        and str(refresh_audit.get("company_id") or "") == normalized_company_id
        and str(refresh_audit.get("store_id") or "") == selected_store_id
        and str(refresh_audit.get("actor_type") or "") == "system"
        and str(refresh_audit.get("target_id") or "") == selected_store_id
        and str(refresh_details.get("connection_id_sha256") or "").strip().lower() == connection_hash
        and _is_sha256(refresh_details.get("credential_ref_sha256"))
    )
    refresh_ready = bool(
        refresh_same_connection_ready
        and refresh_details.get("ok") is True
        and str(refresh_details.get("status") or "") == "refreshed"
        and str(refresh_details.get("source") or "") == "backend_vault_secret_ref_refresh"
        and refresh_details.get("secret_exposed") is False
        and _launch_fresh(_launch_timestamp(refresh_audit.get("created_at") if refresh_audit else None))
    )
    return {
        **base,
        "status": "verified" if refresh_ready else "pending" if oauth_ready else "blocked",
        "current_store_selected": True,
        "authorized": oauth_ready,
        "strong_identity_ready": oauth_ready,
        "backend_provenance_ready": oauth_ready,
        "store_id_sha256": store_hash,
        "connection_id_sha256": connection_hash if oauth_ready else "",
        "refresh_success_ready": refresh_ready,
        "refresh_same_connection_ready": refresh_same_connection_ready,
    }


def _build_current_store_ebay_evidence(
    *,
    repository: SaaSRepository,
    company_id: str | None,
    store_id: str | None,
    oauth_boundary: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "status": "blocked",
        "current_store_selected": False,
        "store_id_sha256": "",
        "connection_id_sha256": str(oauth_boundary.get("connection_id_sha256") or ""),
        "official_packet_ready": False,
        "packet_id_sha256": "",
        "present_resource_keys": [],
        "missing_resource_keys": [],
        "backend_worker_provenance_ready": False,
        "same_oauth_connection_ready": False,
        "account_health_ready": False,
        "account_health_status": "unknown",
        "account_health_same_packet_ready": False,
        "incident_mode": True,
        "can_execute_real_writes": False,
        "refresh_success_ready": False,
        "refresh_same_connection_ready": False,
        "refresh_success_count": 0,
        "latest_refresh_success_at": "",
        "new_account_action_evidence": {
            "publish_health_confirmation_ready": False,
            "controlled_real_publish_ready": False,
            "post_publish_cleanup_ready": False,
            "secret_exposed": False,
        },
        "blockers": ["current_store_unselected"],
        "secret_exposed": False,
    }
    normalized_company_id = str(company_id or "").strip()
    selected_store_id = str(store_id or "").strip()
    if normalized_company_id and not selected_store_id:
        onboarding = repository.get_merchant_onboarding_state(company_id=normalized_company_id) or {}
        selected_store_id = str(onboarding.get("store_id") or "").strip()
    store = (
        repository.get_store_for_company(company_id=normalized_company_id, store_id=selected_store_id)
        if normalized_company_id and selected_store_id
        else None
    )
    if not store or str(store.get("platform") or "").strip().lower() != "ebay":
        return base

    store_hash = hashlib.sha256(selected_store_id.encode("utf-8")).hexdigest()
    connection_hash = str(oauth_boundary.get("connection_id_sha256") or "")
    oauth_ready = bool(
        oauth_boundary.get("authorized") is True
        and oauth_boundary.get("current_store_selected") is True
        and oauth_boundary.get("strong_identity_ready") is True
        and oauth_boundary.get("backend_provenance_ready") is True
        and str(oauth_boundary.get("store_id_sha256") or "") == store_hash
        and connection_hash
    )
    packets = repository.list_platform_data_packets(
        company_id=normalized_company_id,
        store_id=selected_store_id,
        platform="ebay",
        limit=1,
    )
    latest = packets[0] if packets else {}
    packet = latest.get("packet") if isinstance(latest.get("packet"), dict) else {}
    packet_id = str(latest.get("packet_id") or "")
    present = _safe_string_list(packet.get("present_resource_keys"))
    missing = _safe_string_list(packet.get("missing_resource_keys"))
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    packet_time = _launch_timestamp(latest.get("created_at"))
    inner_packet_time = _launch_timestamp(packet.get("created_at"))
    freshness = packet.get("freshness") if isinstance(packet.get("freshness"), dict) else {}
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    packet_shape_ready = bool(
        oauth_ready
        and packet_id
        and str(latest.get("company_id") or "") == normalized_company_id
        and str(latest.get("store_id") or "") == selected_store_id
        and str(latest.get("platform") or "").lower() == "ebay"
        and str(latest.get("source_mode") or "") == "official_api"
        and str(packet.get("company_id") or "") == normalized_company_id
        and str(packet.get("store_id") or "") == selected_store_id
        and str(packet.get("platform") or "").lower() == "ebay"
        and str(packet.get("source_mode") or "") == "official_api"
        and str(packet.get("source_label") or "") == "official_api"
        and required.issubset(set(present))
        and _launch_fresh(packet_time)
        and inner_packet_time is not None
        and _launch_times_close(packet_time, inner_packet_time)
        and _strict_positive_int(freshness.get("official_request_count"))
        and _strict_positive_int(freshness.get("route_success_count"))
        and _strict_zero_int(freshness.get("route_failure_count"))
        and lineage.get("probe_live_read_performed") is True
        and lineage.get("access_token_returned_to_frontend") is False
        and lineage.get("raw_ebay_response_stored") is False
        and packet.get("safe_for_real_platform_write") is False
        and packet.get("secret_exposed") is False
    )

    worker_ready = False
    same_connection_ready = False
    if packet_shape_ready:
        for job in repository.list_queue_jobs(company_id=normalized_company_id, status="completed", limit=200):
            job_id = str(job.get("job_id") or "")
            job_body = job.get("job") if isinstance(job.get("job"), dict) else {}
            live_plan = job_body.get("live_read_plan") if isinstance(job_body.get("live_read_plan"), dict) else {}
            token_boundary = live_plan.get("token_boundary") if isinstance(live_plan.get("token_boundary"), dict) else {}
            bound_connection_id = str(token_boundary.get("connection_id") or "")
            if not (
                job_id
                and str(job.get("company_id") or "") == normalized_company_id
                and str(job.get("status") or "") == "completed"
                and str(job_body.get("kind") or "") == "ebay_read_only_live_plan"
                and str(job_body.get("store_id") or live_plan.get("store_id") or "") == selected_store_id
                and bound_connection_id
                and hashlib.sha256(bound_connection_id.encode("utf-8")).hexdigest() == connection_hash
            ):
                continue
            updates = job_body.get("updates") if isinstance(job_body.get("updates"), list) else []
            matching_update = next(
                (
                    update
                    for update in reversed(updates)
                    if isinstance(update, dict)
                    and str(update.get("data_packet_id") or "") == packet_id
                    and update.get("live_read_performed") is True
                    and _strict_positive_int(update.get("request_count"))
                    and _launch_times_close(packet_time, _launch_timestamp(update.get("created_at")))
                ),
                {},
            )
            audit = repository.find_latest_audit_log_by_target(
                company_id=normalized_company_id,
                store_id=selected_store_id,
                action_type="ebay.read_only.live.completed",
                target_type="queue_job",
                target_id=job_id,
            )
            audit_details = audit.get("details") if isinstance(audit, dict) and isinstance(audit.get("details"), dict) else {}
            audit_ready = bool(
                audit
                and str(audit.get("company_id") or "") == normalized_company_id
                and str(audit.get("store_id") or "") == selected_store_id
                and str(audit.get("actor_type") or "") == "system"
                and str(audit.get("target_id") or "") == job_id
                and str(audit_details.get("data_packet_id") or "") == packet_id
                and _strict_positive_int(audit_details.get("request_count"))
                and audit_details.get("raw_response_stored") is False
                and audit_details.get("secret_exposed") is False
                and _launch_times_close(packet_time, _launch_timestamp(audit.get("created_at")))
            )
            same_connection_ready = True
            worker_ready = bool(matching_update and audit_ready)
            if worker_ready:
                break

    account_health = build_account_health_snapshot(
        repository,
        company_id=normalized_company_id,
        store_id=selected_store_id,
    )
    health_package = account_health.get("evidence_package") if isinstance(account_health.get("evidence_package"), dict) else {}
    account_health_same_packet_ready = bool(
        packet_id
        and str(account_health.get("company_id") or "") == normalized_company_id
        and str(account_health.get("store_id") or "") == selected_store_id
        and str(health_package.get("packet_id") or "") == packet_id
        and health_package.get("official_packet_present") is True
    )
    account_health_ready = bool(
        packet_shape_ready
        and worker_ready
        and account_health_same_packet_ready
        and str(account_health.get("status") or "") == "normal"
        and account_health.get("incident_mode") is False
        and account_health.get("can_execute_real_writes") is True
    )

    refresh_audit = repository.find_latest_audit_log_by_target(
        company_id=normalized_company_id,
        store_id=selected_store_id,
        action_type="oauth.token_refresh.executed",
        target_type="store",
        target_id=selected_store_id,
    )
    refresh_details = (
        refresh_audit.get("details")
        if isinstance(refresh_audit, dict) and isinstance(refresh_audit.get("details"), dict)
        else {}
    )
    refresh_same_connection_ready = bool(
        oauth_ready
        and refresh_audit
        and str(refresh_audit.get("company_id") or "") == normalized_company_id
        and str(refresh_audit.get("store_id") or "") == selected_store_id
        and str(refresh_audit.get("actor_type") or "") == "system"
        and str(refresh_audit.get("target_id") or "") == selected_store_id
        and str(refresh_details.get("connection_id_sha256") or "") == connection_hash
        and str(refresh_details.get("credential_ref_sha256") or "")
    )
    refresh_ready = bool(
        refresh_same_connection_ready
        and refresh_details.get("ok") is True
        and str(refresh_details.get("status") or "") == "refreshed"
        and str(refresh_details.get("source") or "") == "backend_vault_secret_ref_refresh"
        and refresh_details.get("secret_exposed") is False
        and _launch_fresh(_launch_timestamp(refresh_audit.get("created_at") if refresh_audit else None))
    )
    official_packet_ready = bool(packet_shape_ready and worker_ready and same_connection_ready)
    new_account_action_evidence = _build_current_store_new_account_action_evidence(
        repository=repository,
        company_id=normalized_company_id,
        store_id=selected_store_id,
    )
    blockers = []
    if not oauth_ready:
        blockers.append("current_store_strong_oauth_missing")
    if not packet_shape_ready:
        blockers.append("current_store_official_packet_missing_or_invalid")
    elif not worker_ready:
        blockers.append("current_store_packet_worker_provenance_missing")
    if not account_health_ready:
        blockers.append("current_store_account_health_not_safe")
    if not refresh_ready:
        blockers.append("current_store_refresh_proof_missing")
    return {
        **base,
        "status": "ready" if official_packet_ready and account_health_ready and refresh_ready else "blocked",
        "current_store_selected": True,
        "store_id_sha256": store_hash,
        "connection_id_sha256": connection_hash,
        "official_packet_ready": official_packet_ready,
        "packet_id_sha256": hashlib.sha256(packet_id.encode("utf-8")).hexdigest() if packet_id else "",
        "present_resource_keys": present,
        "missing_resource_keys": missing,
        "backend_worker_provenance_ready": worker_ready,
        "same_oauth_connection_ready": same_connection_ready,
        "account_health_ready": account_health_ready,
        "account_health_status": str(account_health.get("status") or "unknown"),
        "account_health_same_packet_ready": account_health_same_packet_ready,
        "incident_mode": account_health.get("incident_mode") is True,
        "can_execute_real_writes": account_health.get("can_execute_real_writes") is True,
        "refresh_success_ready": refresh_ready,
        "refresh_same_connection_ready": refresh_same_connection_ready,
        "refresh_success_count": 1 if refresh_ready else 0,
        "latest_refresh_success_at": str(refresh_audit.get("created_at") or "") if refresh_ready and refresh_audit else "",
        "new_account_action_evidence": new_account_action_evidence,
        "blockers": blockers,
        "secret_exposed": False,
    }


def _build_current_store_new_account_action_evidence(
    *,
    repository: SaaSRepository,
    company_id: str,
    store_id: str,
) -> dict[str, Any]:
    contract_version = "2026-06-18-new-ebay-account-low-risk-smoke"
    confirmations = [
        item
        for item in repository.list_confirmations(company_id=company_id, limit=200)
        if str(item.get("store_id") or "") == store_id
    ]
    executions = repository.list_execution_results(company_id=company_id, limit=200)
    audits = [
        item
        for item in repository.list_audit_logs(company_id=company_id, limit=500)
        if str(item.get("store_id") or "") == store_id
    ]

    def exact_confirmation(action_type: str, statuses: set[str]) -> dict[str, Any]:
        return next(
            (
                item
                for item in confirmations
                if str(item.get("action_type") or "") == action_type
                and str(item.get("status") or "") in statuses
                and str(item.get("confirmation_id") or "")
                and str(item.get("decided_by") or "")
                and isinstance(item.get("item"), dict)
                and str(item["item"].get("source") or "") == "new_ebay_account_low_risk_smoke"
                and str(item["item"].get("runbook_contract_version") or "") == contract_version
                and str(item["item"].get("store_id") or store_id) == store_id
            ),
            {},
        )

    def exact_execution(
        confirmation: dict[str, Any],
        *,
        allowed_statuses: set[str],
        real_execution_flag: str,
    ) -> dict[str, Any]:
        confirmation_id = str(confirmation.get("confirmation_id") or "")
        candidate = next(
            (
                item
                for item in executions
                if confirmation_id
                and str(item.get("confirmation_id") or "") == confirmation_id
                and str(item.get("execution_id") or "")
                and str(item.get("status") or "") in allowed_statuses
                and isinstance(item.get("result"), dict)
                and str(item["result"].get("runbook_contract_version") or "") == contract_version
                and str(item["result"].get("store_id") or "") == store_id
                and item["result"].get("secret_exposed") is False
            ),
            {},
        )
        if not candidate:
            return {}
        audit = next(
            (
                item
                for item in audits
                if str(item.get("actor_type") or "") == "system"
                and str(item.get("action_type") or "") == "execution_service.result"
                and str(item.get("target_type") or "") == "execution"
                and str(item.get("target_id") or "") == str(candidate.get("execution_id") or "")
                and isinstance(item.get("details"), dict)
                and isinstance(item["details"].get("real_execution"), dict)
                and item["details"]["real_execution"].get(real_execution_flag) is True
            ),
            {},
        )
        return candidate if audit else {}

    publish_confirmation = exact_confirmation("publish_listing", {"approved", "executed"})
    publish_item = publish_confirmation.get("item") if isinstance(publish_confirmation.get("item"), dict) else {}
    publish_health_ready = bool(publish_confirmation and publish_item.get("publish_health_ready") is True)
    publish_execution = exact_execution(
        publish_confirmation,
        allowed_statuses={"published_to_ebay"},
        real_execution_flag="published_to_ebay",
    )
    publish_result = publish_execution.get("result") if isinstance(publish_execution.get("result"), dict) else {}
    platform_result = publish_result.get("platform_result") if isinstance(publish_result.get("platform_result"), dict) else {}
    controlled_publish_ready = bool(
        publish_execution
        and str(platform_result.get("listing_id") or platform_result.get("listingId") or "")
        and str(platform_result.get("offer_id") or platform_result.get("offerId") or "")
    )
    cleanup_confirmation = exact_confirmation("cleanup_test_listing", {"executed"})
    cleanup_execution = exact_execution(
        cleanup_confirmation,
        allowed_statuses={"completed", "cleanup_completed", "ended_listing", "deleted_test_listing"},
        real_execution_flag="cleanup_test_listing",
    )
    cleanup_ready = bool(controlled_publish_ready and cleanup_execution)
    return {
        "contract_version": contract_version,
        "company_store_bound": True,
        "publish_health_confirmation_ready": publish_health_ready,
        "controlled_real_publish_ready": controlled_publish_ready,
        "post_publish_cleanup_ready": cleanup_ready,
        "publish_confirmation_id_sha256": (
            hashlib.sha256(str(publish_confirmation.get("confirmation_id") or "").encode("utf-8")).hexdigest()
            if publish_confirmation
            else ""
        ),
        "publish_execution_id_sha256": (
            hashlib.sha256(str(publish_execution.get("execution_id") or "").encode("utf-8")).hexdigest()
            if publish_execution
            else ""
        ),
        "cleanup_execution_id_sha256": (
            hashlib.sha256(str(cleanup_execution.get("execution_id") or "").encode("utf-8")).hexdigest()
            if cleanup_execution
            else ""
        ),
        "secret_exposed": False,
    }


def _launch_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _launch_fresh(value: datetime | None) -> bool:
    if value is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - value).total_seconds()
    return -300 <= age_seconds <= 6 * 60 * 60


def _launch_times_close(left: datetime | None, right: datetime | None) -> bool:
    return bool(left and right and abs((left - right).total_seconds()) <= 10 * 60)


def _strict_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _strict_zero_int(value: Any) -> bool:
    return type(value) is int and value == 0


def _safe_nonnegative_int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()][:30]


def _official_packet_ready(evidence: dict[str, Any]) -> bool:
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    present = set(evidence.get("latest_ebay_packet_present_resource_keys") or [])
    return bool(evidence.get("latest_ebay_packet_id")) and required.issubset(present)


def _official_packet_optional_missing(evidence: dict[str, Any]) -> list[str]:
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    missing = set(evidence.get("latest_ebay_packet_missing_resource_keys") or [])
    return sorted(missing - required)


def _vault_ready(settings: SaaSSettings, vault: dict[str, Any]) -> bool:
    if not settings.is_production_like:
        return False
    return (
        settings.vault_enabled
        and settings.vault_provider in {"vault", "tencent_kms", "tencent_ssm", "aliyun_kms"}
        and vault.get("contract_ready") is True
        and vault.get("can_store_raw_secret") is True
    )


def _wechat_zero_charge_rehearsal_evidence(
    *,
    repository: SaaSRepository,
    company_id: str | None,
    now: datetime | None = None,
    expected_build_artifact_id: str | None = None,
) -> dict[str, Any]:
    blocked = {
        "ready": False,
        "evidence_code": "zero_charge_rehearsal_evidence_missing",
        "step_count": 0,
        "fake_transport_call_count": 0,
        "fresh": False,
        "build_bound": False,
    }
    normalized_company = str(company_id or "").strip()
    if not normalized_company:
        return blocked
    expected_build = str(expected_build_artifact_id or current_deployment_build_artifact_id()).strip().lower()
    if not _is_sha256(expected_build):
        return {**blocked, "evidence_code": "deployment_build_artifact_unavailable"}
    evaluated_at = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)
    evaluated_at = evaluated_at.astimezone(timezone.utc)
    try:
        item = repository.find_latest_audit_log_by_target(
            company_id=normalized_company,
            store_id=None,
            action_type="billing.wechat_pay.zero_charge_rehearsal.completed",
            target_type=WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE,
            target_id=WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID,
        )
    except Exception:
        return {**blocked, "evidence_code": "zero_charge_rehearsal_audit_unavailable"}
    if not isinstance(item, dict):
        return blocked
    if (
        item.get("action_type") != "billing.wechat_pay.zero_charge_rehearsal.completed"
        or item.get("actor_type") != "user"
        or item.get("target_type") != WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE
        or item.get("target_id") != WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID
    ):
        return {**blocked, "evidence_code": "zero_charge_rehearsal_target_mismatch"}
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    step_count = _safe_nonnegative_int(details.get("step_count"))
    fake_transport_call_count = _safe_nonnegative_int(details.get("fake_transport_call_count"))
    created_at = _parse_utc_datetime(item.get("created_at"))
    age_seconds = (evaluated_at - created_at).total_seconds() if created_at is not None else None
    fresh = age_seconds is not None and -300 <= age_seconds <= 24 * 60 * 60
    contract_valid = details.get("contract_version") == WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION
    build_bound = str(details.get("build_artifact_id") or "").strip().lower() == expected_build
    safety_ready = all(
        details.get(key) is False
        for key in (
            "creates_real_order",
            "calls_external_api",
            "calls_external_payment_api",
            "triggers_real_charge",
            "triggers_real_refund",
            "charge_allowed",
            "public_charging_allowed",
            "secret_exposed",
        )
    )
    ready = bool(
        contract_valid
        and build_bound
        and fresh
        and details.get("ready") is True
        and step_count == 5
        and fake_transport_call_count == 1
        and safety_ready
    )
    return {
        "ready": ready,
        "evidence_code": "ready" if ready else "zero_charge_rehearsal_binding_invalid",
        "step_count": step_count,
        "fake_transport_call_count": fake_transport_call_count,
        "fresh": fresh,
        "build_bound": build_bound,
    }


def _parse_utc_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _monitoring_ready(monitoring: dict[str, Any]) -> bool:
    alerts = {item.get("key") for item in monitoring.get("alert_contracts", []) if isinstance(item, dict)}
    required = {
        "oauth_callback_failure",
        "vault_resolution_failure",
        "ebay_sync_failure",
        "queue_backlog_or_stuck_job",
        "platform_write_failure",
        "billing_webhook_failure",
        "backup_restore_drill_overdue",
    }
    return (
        monitoring.get("safe_access_logs", {}).get("records_authorization_header") is False
        and required.issubset(alerts)
        and monitoring.get("incident_runbooks", {}).get("runbook_ready") is True
        and monitoring.get("cloud_monitoring", {}).get("target_ready") is True
        and not monitoring.get("current_blockers")
    )


def _monitoring_runbook_ready(monitoring: dict[str, Any]) -> bool:
    """Internal runbook evidence can be ready before the paid-launch monitoring target is live."""

    alerts = {item.get("key") for item in monitoring.get("alert_contracts", []) if isinstance(item, dict)}
    required = {
        "oauth_callback_failure",
        "vault_resolution_failure",
        "ebay_sync_failure",
        "queue_backlog_or_stuck_job",
        "platform_write_failure",
        "billing_webhook_failure",
        "backup_restore_drill_overdue",
    }
    safe_logs = monitoring.get("safe_access_logs") if isinstance(monitoring.get("safe_access_logs"), dict) else {}
    runbooks = monitoring.get("incident_runbooks") if isinstance(monitoring.get("incident_runbooks"), dict) else {}
    return (
        safe_logs.get("records_request_body") is False
        and safe_logs.get("records_authorization_header") is False
        and safe_logs.get("records_raw_tokens") is False
        and required.issubset(alerts)
        and runbooks.get("runbook_ready") is True
        and monitoring.get("secret_exposed") is False
    )


def _public_security_evidence_ready(domain: dict[str, Any]) -> bool:
    return (
        bool(domain.get("stable_host"))
        and bool(domain.get("dns_verified"))
        and bool(domain.get("https_only"))
        and bool(domain.get("tls_verified"))
        and bool(domain.get("deployment_hardened"))
        and bool(domain.get("security_headers_verified"))
    )


def _seed_beta_ready(groups: list[dict[str, Any]]) -> bool:
    by_key = {item["key"]: item for item in groups}
    return (
        by_key.get("official_ebay_read_loop", {}).get("status") == "ready"
        and by_key.get("model_agent_value", {}).get("status") == "ready"
        and by_key.get("managed_secret_boundary", {}).get("status") == "ready"
    )


def _publish_safety_ready(evidence: dict[str, Any], counts: dict[str, Any]) -> bool:
    return (
        _official_packet_ready(evidence)
        and _strict_positive_int(counts.get("confirmations"))
        and evidence.get("latest_ebay_packet_source_mode") == "official_api"
    )


def _readiness_item(readiness: dict[str, Any], key: str) -> dict[str, Any]:
    for item in readiness.get("items") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return {}


def _readiness_status_ready(readiness: dict[str, Any], key: str, ready_statuses: set[str]) -> bool:
    status = str(_readiness_item(readiness, key).get("status") or "")
    return status == "ready" or status in ready_statuses


def _legal_risk_boundary_ready() -> bool:
    required = (
        "JIEJING_PRIVACY_POLICY_VERIFIED",
        "JIEJING_TERMS_VERIFIED",
        "JIEJING_RISK_DISCLOSURE_VERIFIED",
        "JIEJING_CONFIRMATION_TERMS_VISIBLE",
    )
    return all(_env_bool(name) for name in required)


def _build_launch_action_plan(
    *,
    groups: list[dict[str, Any]],
    readiness: dict[str, Any],
    billing: dict[str, Any],
    domain: dict[str, Any],
    monitoring: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
    paid_launch_ready: bool,
    current_store_oauth: dict[str, Any],
    current_store_ebay_evidence: dict[str, Any],
) -> dict[str, Any]:
    by_key = {item["key"]: item for item in groups}
    ordered_keys = [
        "billing_quota",
        "stable_domain_tls",
        "ebay_token_refresh_vault_adapter",
        "account_health_incident_mode",
        "new_ebay_account_low_risk_smoke",
        "publish_safety_system",
        "store_sync_visibility",
        "post_publish_cockpit",
        "legal_risk_boundary",
        "final_commercial_smoke",
    ]
    items = [
        _action_plan_item(
            key,
            by_key=by_key,
            readiness=readiness,
            billing=billing,
            domain=domain,
            evidence=evidence,
            counts=counts,
        )
        for key in ordered_keys
    ]
    action_items = {item["key"]: item for item in items}
    drills = _build_commercial_hardening_drills(
        groups_by_key=by_key,
        action_items=action_items,
        readiness=readiness,
        billing=billing,
        domain=domain,
        evidence=evidence,
        counts=counts,
        current_store_ebay_evidence=current_store_ebay_evidence,
    )
    new_account_smoke_runbook = _build_new_ebay_account_smoke_runbook(
        action_items=action_items,
        readiness=readiness,
        evidence=evidence,
        counts=counts,
        current_store_oauth=current_store_oauth,
        current_store_ebay_evidence=current_store_ebay_evidence,
    )
    cutover_checklist = _build_paid_launch_cutover_checklist(
        groups_by_key=by_key,
        drills={item["key"]: item for item in drills},
        billing=billing,
        domain=domain,
        evidence=evidence,
        current_store_ebay_evidence=current_store_ebay_evidence,
    )
    cutover_decision = _build_paid_launch_cutover_decision(
        cutover_checklist=cutover_checklist,
        billing=billing,
        domain=domain,
        paid_launch_ready=paid_launch_ready,
    )
    prelaunch_deferred_strategy = _build_prelaunch_deferred_strategy(
        groups_by_key=by_key,
        action_items=action_items,
        drills={item["key"]: item for item in drills},
        cutover_checklist={item["key"]: item for item in cutover_checklist},
        cutover_decision=cutover_decision,
        readiness=readiness,
        billing=billing,
        domain=domain,
        monitoring=monitoring,
        evidence=evidence,
        counts=counts,
    )
    ready_count = sum(1 for item in items if item["status"] == "ready")
    blocked_items = [item for item in items if item["status"] != "ready"]
    ready_drill_count = sum(1 for item in drills if item["status"] == "ready")
    blocked_drills = [item for item in drills if item["status"] != "ready"]
    ready_new_account_smoke_count = sum(1 for item in new_account_smoke_runbook if item["status"] == "ready")
    blocked_new_account_smoke = [item for item in new_account_smoke_runbook if item["status"] != "ready"]
    ready_cutover_count = sum(1 for item in cutover_checklist if item["status"] == "ready")
    blocked_cutover = [item for item in cutover_checklist if item["status"] != "ready"]
    internal_work = prelaunch_deferred_strategy.get("autonomous_internal_work", [])
    internal_ready = [item for item in internal_work if isinstance(item, dict) and item.get("status") == "ready"]
    internal_blocked = [item for item in internal_work if isinstance(item, dict) and item.get("status") != "ready"]
    external_deferred = prelaunch_deferred_strategy.get("external_deferred_items", [])
    return {
        "contract_version": "2026-06-18-launch-action-plan",
        "public_paid_launch_ready": paid_launch_ready,
        "current_phase": "paid_public_ready" if paid_launch_ready else "private_beta_hardening",
        "summary": {
            "ready_count": ready_count,
            "total_count": len(items),
            "blocked_count": len(blocked_items),
            "hardening_drill_ready_count": ready_drill_count,
            "hardening_drill_total_count": len(drills),
            "hardening_drill_blocked_count": len(blocked_drills),
            "next_drill": blocked_drills[0]["key"] if blocked_drills else "",
            "new_account_smoke_ready_count": ready_new_account_smoke_count,
            "new_account_smoke_total_count": len(new_account_smoke_runbook),
            "new_account_smoke_blocked_count": len(blocked_new_account_smoke),
            "next_new_account_smoke_step": blocked_new_account_smoke[0]["key"] if blocked_new_account_smoke else "",
            "cutover_ready_count": ready_cutover_count,
            "cutover_total_count": len(cutover_checklist),
            "cutover_blocked_count": len(blocked_cutover),
            "next_cutover_item": blocked_cutover[0]["key"] if blocked_cutover else "",
            "cutover_decision_status": cutover_decision.get("status") or "blocked",
            "runbook_ready_count": cutover_decision.get("runbook_ready_count", 0),
            "runbook_total_count": cutover_decision.get("runbook_total_count", 0),
            "runbook_blocked_count": cutover_decision.get("runbook_blocked_count", 0),
            "next_runbook_step": (cutover_decision.get("next_runbook_step") or {}).get("key") or "",
            "deferred_external_count": len(external_deferred),
            "autonomous_internal_ready_count": len(internal_ready),
            "autonomous_internal_total_count": len(internal_work),
            "autonomous_internal_blocked_count": len(internal_blocked),
            "autonomous_internal_next_step": internal_blocked[0]["key"] if internal_blocked else "",
            "top_blockers": [item["key"] for item in blocked_items[:5]],
            "plain_status": "付费公开上线门禁已通过。" if paid_launch_ready else "可以继续私测和硬化；仍不能公开收费上线。",
        },
        "prelaunch_deferred_strategy": prelaunch_deferred_strategy,
        "commercial_hardening_drills": drills,
        "new_ebay_account_smoke_runbook": new_account_smoke_runbook,
        "paid_launch_cutover_checklist": cutover_checklist,
        "paid_launch_cutover_decision": cutover_decision,
        "sections": [
            {
                "key": "paid_launch_must_have",
                "label": "公开收费前必须补齐",
                "items": [
                    item
                    for item in items
                    if item["key"] in {"billing_quota", "stable_domain_tls", "legal_risk_boundary", "final_commercial_smoke"}
                ],
            },
            {
                "key": "ebay_risk_and_publish",
                "label": "eBay 账号与发布安全",
                "items": [
                    item
                    for item in items
                    if item["key"]
                    in {
                        "ebay_token_refresh_vault_adapter",
                        "account_health_incident_mode",
                        "new_ebay_account_low_risk_smoke",
                        "publish_safety_system",
                        "store_sync_visibility",
                    }
                ],
            },
            {
                "key": "operate_after_publish",
                "label": "发布后经营闭环",
                "items": [item for item in items if item["key"] == "post_publish_cockpit"],
            },
        ],
        "next_actions": [item["next_action"] for item in blocked_items[:6]],
        "frontend_gets_secret": False,
        "runtime_gets_raw_ebay_token": False,
        "secret_exposed": False,
    }


def _build_prelaunch_deferred_strategy(
    *,
    groups_by_key: dict[str, dict[str, Any]],
    action_items: dict[str, dict[str, Any]],
    drills: dict[str, dict[str, Any]],
    cutover_checklist: dict[str, dict[str, Any]],
    cutover_decision: dict[str, Any],
    readiness: dict[str, Any],
    billing: dict[str, Any],
    domain: dict[str, Any],
    monitoring: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
) -> dict[str, Any]:
    mainland_payment = (
        billing.get("mainland_payment_launch")
        if isinstance(billing.get("mainland_payment_launch"), dict)
        else {}
    )
    rehearsal_evidence = (
        billing.get("wechat_zero_charge_rehearsal_evidence")
        if isinstance(billing.get("wechat_zero_charge_rehearsal_evidence"), dict)
        else {}
    )
    no_charge_ready = rehearsal_evidence.get("ready") is True
    readiness_snapshot_ready = (
        readiness.get("beta_ready") is True
        and _strict_zero_int(readiness.get("blocker_count"))
        and type(readiness.get("warning_count")) is int
        and readiness.get("warning_count") >= 0
        and _readiness_item(readiness, "database_live_probe").get("status") == "ready"
        and _readiness_item(readiness, "queue_runtime_health").get("status") == "ready"
        and _readiness_item(readiness, "worker_runtime_health").get("status") == "ready"
    )
    external_deferred = [
        _prelaunch_external_deferred_item(
            "formal_payment_deferred",
            "Mainland WeChat production cutover deferred",
            owner="founder_operator",
            category="billing",
            next_action="Keep WeChat public charging closed until backend-only production configuration, zero-charge rehearsal evidence, final release proof, and exact owner approval are complete.",
            evidence_summary=_compact_drill_evidence(
                provider="wechat_pay_native",
                mainland_payment_ready_for_owner_approval=(
                    mainland_payment.get("mainland_payment_ready_for_owner_approval") is True
                ),
                public_charging_allowed=False,
                next_paid_launch_blocker=mainland_payment.get("next_paid_launch_blocker") or "",
                cutover_status=cutover_decision.get("status") or "blocked",
            ),
            verification=[
                "/billing/payment-options",
                "/commercial/launch-gate",
                "tools/test_jiejing_wechat_pay_zero_charge_rehearsal.py",
            ],
        ),
        _prelaunch_external_deferred_item(
            "clean_ebay_account_validation_deferred",
            "Clean new eBay account real validation deferred",
            owner="founder_operator",
            category="ebay",
            next_action="Do not repeat OAuth or run any real eBay write until a clean new seller account and fresh real test product assets are ready.",
            evidence_summary=_compact_drill_evidence(
                old_frozen_account_reuse_allowed=False,
                refresh_probe_success=_safe_nonnegative_int(evidence.get("ebay_token_refresh_success_count")),
                low_risk_smoke_status=(drills.get("new_ebay_account_low_risk_smoke") or {}).get("status") or "blocked",
                real_publish_requires_confirmation_center=True,
            ),
            verification=["docs/JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_RUNBOOK_20260617.md", "tools/jiejing_new_ebay_account_low_risk_check.py"],
        ),
    ]
    internal_work = [
        _prelaunch_internal_work_item(
            "legal_risk_boundary_docs",
            "Legal, risk, and confirmation copy boundary",
            (groups_by_key.get("legal_risk_boundary") or {}).get("status") == "ready",
            owner="commercial_ops",
            category="legal",
            next_action=(action_items.get("legal_risk_boundary") or {}).get("next_action") or "Verify privacy, terms, risk disclosure and confirmation copy.",
            evidence_summary=(action_items.get("legal_risk_boundary") or {}).get("evidence_summary") or "privacy/terms/risk/confirmation flags required",
            verification=["/commercial/launch-gate", "privacy.html", "confirmation center UI"],
            confirmation_center_required=True,
        ),
        _prelaunch_internal_work_item(
            "monitoring_incident_runbooks",
            "Monitoring, alerting, and incident runbooks",
            _monitoring_runbook_ready(monitoring),
            owner="platform_ops",
            category="reliability",
            next_action=(groups_by_key.get("monitoring_alerting") or {}).get("next_action") or "Wire safe access logs, alert routes and incident runbooks for OAuth, Vault, eBay sync, queue, model, billing and backup failures.",
            evidence_summary=_compact_drill_evidence(
                monitoring=(groups_by_key.get("monitoring_alerting") or {}).get("status") or "missing",
                runbooks_ready=bool((monitoring.get("incident_runbooks") or {}).get("runbook_ready")),
                cloud_target_ready=bool((monitoring.get("cloud_monitoring") or {}).get("target_ready")),
                runbook_expected=True,
            ),
            verification=["/health/deep", "/commercial/launch-gate", "tools/test_jiejing_monitoring_runbook_gate.py"],
        ),
        _prelaunch_internal_work_item(
            "backup_restore_drill_evidence",
            "Backup, restore, and recovery evidence",
            (groups_by_key.get("backup_restore") or {}).get("status") == "ready",
            owner="platform_ops",
            category="reliability",
            next_action=(groups_by_key.get("backup_restore") or {}).get("next_action") or "Record backup policy, restore drill evidence and recovery runbook before public customers.",
            evidence_summary=_compact_drill_evidence(
                backup=(groups_by_key.get("backup_restore") or {}).get("status") or "missing",
                cutover_item=(cutover_checklist.get("backup_monitoring_restore_drill") or {}).get("status") or "blocked",
            ),
            verification=["/backup/plan", "/commercial/launch-gate", "restore drill evidence"],
        ),
        _prelaunch_internal_work_item(
            "no_charge_billing_rehearsal",
            "WeChat zero-charge payment and entitlement rehearsal",
            no_charge_ready,
            owner="billing_ops",
            category="billing",
            next_action="Run the exact-phrase isolated WeChat rehearsal; keep the production charge switch false.",
            evidence_summary=_compact_drill_evidence(
                provider="wechat_pay_native",
                zero_charge_rehearsal_ready=no_charge_ready,
                step_count=_safe_nonnegative_int(rehearsal_evidence.get("step_count")),
                calls_external_api=False,
                triggers_real_charge=False,
            ),
            verification=["tools/test_jiejing_wechat_pay_zero_charge_rehearsal.py"],
        ),
        _prelaunch_internal_work_item(
            "public_security_evidence_capture",
            "Public security and anti-scrape evidence",
            _public_security_evidence_ready(domain),
            owner="platform_security",
            category="security",
            next_action="Keep free WAF/Bot evidence, noindex headers, source-map blocking and backend high-cost API rate limits visible for the platform owner.",
            evidence_summary=_compact_drill_evidence(
                stable_domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                security_headers=bool(domain.get("security_headers_verified")),
                callback=bool(domain.get("ebay_callback_verified")),
                expensive_api_backend_limit=True,
            ),
            verification=["/owner/edge-cutover-preflight", "/rate-limit/status", "tools/test_jiejing_public_anti_scrape_hardening.py"],
        ),
        _prelaunch_internal_work_item(
            "test_data_governance_review",
            "Staging smoke data governance review",
            _env_bool("JIEJING_TEST_DATA_GOVERNANCE_REVIEWED"),
            owner="release_manager",
            category="data_governance",
            next_action="Review smoke/demo markers and keep deletion disabled by default; real cleanup remains confirmation-gated and data-safe.",
            evidence_summary=_compact_drill_evidence(
                users=_safe_nonnegative_int(counts.get("users")),
                stores=_safe_nonnegative_int(counts.get("stores")),
                tasks=_safe_nonnegative_int(counts.get("tasks")),
                reviewed=_env_bool("JIEJING_TEST_DATA_GOVERNANCE_REVIEWED"),
            ),
            verification=["/owner/launch-control", "repository smoke data governance report"],
            confirmation_center_required=True,
        ),
        _prelaunch_internal_work_item(
            "confirmation_center_copy_and_rollback",
            "Confirmation center, rollback, and audit packet",
            _strict_positive_int(counts.get("confirmations")) and bool((cutover_decision.get("rollback_plan") or [])),
            owner="release_manager",
            category="release",
            next_action="Keep every real publish, cleanup, refund, pricing, inventory, ad, policy or sensitive customer promise behind confirmation and rollback evidence.",
            evidence_summary=_compact_drill_evidence(
                confirmations=_safe_nonnegative_int(counts.get("confirmations")),
                rollback_steps=len(cutover_decision.get("rollback_plan") or []),
                publish_safety=(action_items.get("publish_safety_system") or {}).get("status") or "blocked",
            ),
            verification=["confirmation center", "/commercial/launch-gate", "audit records"],
            confirmation_center_required=True,
        ),
        _prelaunch_internal_work_item(
            "browser_smoke_and_readiness_snapshot",
            "Readiness snapshot and browser smoke",
            readiness_snapshot_ready and _env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
            owner="release_manager",
            category="release",
            next_action="After each important deploy, record /health, /health/deep, readiness, secret scan and browser smoke evidence on app.jiejing.shop.",
            evidence_summary=_compact_drill_evidence(
                beta_ready=bool(readiness.get("beta_ready")),
                blocker_count=_safe_nonnegative_int(readiness.get("blocker_count")),
                browser_smoke=_env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
            ),
            verification=["/health", "/health/deep", "/readiness/product-saas", "browser smoke output"],
        ),
    ]
    blocked_internal = [item for item in internal_work if item["status"] != "ready"]
    return {
        "contract_version": "2026-06-20-prelaunch-deferred-strategy-v1",
        "mode": "formal_payment_and_clean_ebay_real_validation_deferred",
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "formal_payment_deferred": True,
        "clean_ebay_account_validation_deferred": True,
        "can_continue_without_payment": True,
        "can_continue_without_new_ebay_account": True,
        "summary": {
            "external_deferred_count": len(external_deferred),
            "autonomous_internal_ready_count": len(internal_work) - len(blocked_internal),
            "autonomous_internal_total_count": len(internal_work),
            "autonomous_internal_blocked_count": len(blocked_internal),
            "next_autonomous_internal_step": blocked_internal[0]["key"] if blocked_internal else "",
            "public_paid_launch_allowed": False,
            "plain_status": "Formal payment and clean eBay real validation are intentionally deferred; continue internal prelaunch hardening only.",
        },
        "external_deferred_items": external_deferred,
        "autonomous_internal_work": internal_work,
        "safety_contract": {
            "triggers_real_charge": False,
            "triggers_ebay_oauth": False,
            "repeat_ebay_oauth_allowed": False,
            "triggers_real_platform_write": False,
            "frontend_gets_secret": False,
            "frontend_gets_payment_secret": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _prelaunch_external_deferred_item(
    key: str,
    title: str,
    *,
    owner: str,
    category: str,
    next_action: str,
    evidence_summary: str,
    verification: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "deferred",
        "severity": "external_dependency",
        "owner": owner,
        "category": category,
        "blocks_public_paid_launch": True,
        "deferred_by_owner_request": True,
        "external_dependency_deferred": True,
        "can_continue_without_payment": True,
        "can_continue_without_new_ebay_account": True,
        "can_continue_internal_prelaunch_work": True,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "runtime_gets_raw_ebay_token": False,
        "verification": verification,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "secret_exposed": False,
    }


def _prelaunch_internal_work_item(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    category: str,
    next_action: str,
    evidence_summary: str,
    verification: list[str],
    confirmation_center_required: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "pending",
        "severity": "info" if ready else "attention_required",
        "owner": owner,
        "category": category,
        "can_continue_without_payment": True,
        "can_continue_without_new_ebay_account": True,
        "external_dependency_deferred": False,
        "blocked_by_deferred_external_item": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "confirmation_center_required": confirmation_center_required,
        "frontend_gets_secret": False,
        "frontend_gets_payment_secret": False,
        "runtime_gets_raw_ebay_token": False,
        "verification": verification,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "secret_exposed": False,
    }


def _build_commercial_hardening_drills(
    *,
    groups_by_key: dict[str, dict[str, Any]],
    action_items: dict[str, dict[str, Any]],
    readiness: dict[str, Any],
    billing: dict[str, Any],
    domain: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
    current_store_ebay_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    _ = groups_by_key
    mainland_payment = (
        billing.get("mainland_payment_launch")
        if isinstance(billing.get("mainland_payment_launch"), dict)
        else {}
    )
    rehearsal_evidence = (
        billing.get("wechat_zero_charge_rehearsal_evidence")
        if isinstance(billing.get("wechat_zero_charge_rehearsal_evidence"), dict)
        else {}
    )
    mainland_owner_ready = mainland_payment.get("mainland_payment_ready_for_owner_approval") is True
    domain_ready = bool(domain.get("production_domain_ready"))
    token_ready = (action_items.get("ebay_token_refresh_vault_adapter") or {}).get("status") == "ready"
    account_health_ready = (action_items.get("account_health_incident_mode") or {}).get("status") == "ready"
    publish_safety_ready = (action_items.get("publish_safety_system") or {}).get("status") == "ready"
    new_account_ready = (action_items.get("new_ebay_account_low_risk_smoke") or {}).get("status") == "ready"
    final_smoke_ready = (action_items.get("final_commercial_smoke") or {}).get("status") == "ready"

    return [
        _hardening_drill(
            "wechat_pay_zero_charge_production_rehearsal",
            "WeChat Pay production contract and zero-charge rehearsal",
            mainland_owner_ready and rehearsal_evidence.get("ready") is True,
            owner="platform_ops",
            next_action=(action_items.get("billing_quota") or {}).get("next_action") or "Complete canonical WeChat production evidence and run the isolated zero-charge rehearsal; keep public charging closed.",
            evidence_summary=_compact_drill_evidence(
                provider="wechat_pay_native",
                mainland_payment_ready_for_owner_approval=mainland_owner_ready,
                zero_charge_rehearsal_ready=rehearsal_evidence.get("ready") is True,
                public_charging_allowed=False,
            ),
            evidence={
                "provider": "wechat_pay_native",
                "mainland_payment_ready_for_owner_approval": mainland_owner_ready,
                "provider_configured": mainland_payment.get("provider_configured") is True,
                "controlled_acceptance_proven": mainland_payment.get("controlled_acceptance_proven") is True,
                "verified_paid_order_count": _safe_nonnegative_int(mainland_payment.get("verified_paid_order_count")),
                "zero_charge_rehearsal_ready": rehearsal_evidence.get("ready") is True,
                "zero_charge_rehearsal_step_count": _safe_nonnegative_int(rehearsal_evidence.get("step_count")),
                "fake_transport_call_count": _safe_nonnegative_int(rehearsal_evidence.get("fake_transport_call_count")),
                "public_charging_allowed": False,
                "frontend_gets_payment_secret": False,
            },
            requires_confirmation_center=False,
        ),
        _hardening_drill(
            "stable_domain_cutover",
            "Stable domain, TLS, callback, and CORS cutover drill",
            domain_ready,
            owner="platform_ops",
            next_action=(action_items.get("stable_domain_tls") or {}).get("next_action") or "Bind a stable HTTPS domain, verify DNS/TLS, align CORS, and update the eBay callback domain.",
            evidence_summary=_compact_drill_evidence(
                domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
            ),
            evidence={
                "stable_domain": domain.get("stable_domain") or "",
                "required_callback_url": domain.get("required_callback_url") or "",
                "dns_verified": bool(domain.get("dns_verified")),
                "tls_verified": bool(domain.get("tls_verified")),
                "ebay_callback_verified": bool(domain.get("ebay_callback_verified")),
                "cors_origin_aligned": bool(domain.get("cors_origin_aligned")),
                "deployment_hardened": bool(domain.get("deployment_hardened")),
                "security_headers_verified": bool(domain.get("security_headers_verified")),
                "blockers": domain.get("blockers") or [],
            },
            requires_confirmation_center=False,
        ),
        _hardening_drill(
            "ebay_refresh_vault_probe",
            "Vault-backed eBay refresh probe drill",
            token_ready,
            owner="backend_secret_boundary",
            next_action=(action_items.get("ebay_token_refresh_vault_adapter") or {}).get("next_action") or "After a clean new seller account is connected, run one backend-only refresh probe through the Vault-backed adapter.",
            evidence_summary=_compact_drill_evidence(
                readiness=(_readiness_item(readiness, "ebay_token_refresh") or {}).get("status") or "missing",
                secret_refs=bool(evidence.get("ebay_secret_refs")),
                refresh_success=_safe_nonnegative_int(current_store_ebay_evidence.get("refresh_success_count")),
            ),
            evidence={
                "readiness_status": (_readiness_item(readiness, "ebay_token_refresh") or {}).get("status") or "",
                "secret_refs_present": bool(evidence.get("ebay_secret_refs")),
                "successful_refresh_probe_count": _safe_nonnegative_int(current_store_ebay_evidence.get("refresh_success_count")),
                "latest_successful_refresh_probe_at": current_store_ebay_evidence.get("latest_refresh_success_at") or "",
                "same_oauth_connection_ready": current_store_ebay_evidence.get("refresh_same_connection_ready") is True,
                "repeat_oauth_allowed": False,
                "frontend_gets_raw_token": False,
                "runtime_gets_raw_token": False,
            },
            requires_confirmation_center=False,
        ),
        _hardening_drill(
            "account_health_incident_mode",
            "Account health and incident-mode drill",
            account_health_ready,
            owner="publishing_safety",
            next_action=(action_items.get("account_health_incident_mode") or {}).get("next_action") or "Refresh the read-only account health packet and keep abnormal accounts in incident mode before any real write.",
            evidence_summary=(action_items.get("account_health_incident_mode") or {}).get("evidence_summary") or "account_health_snapshot_missing",
            evidence={
                "readiness_status": (_readiness_item(readiness, "account_health_incident_mode") or {}).get("status") or "",
                "packet_id_sha256": current_store_ebay_evidence.get("packet_id_sha256") or "",
                "same_oauth_connection_ready": current_store_ebay_evidence.get("same_oauth_connection_ready") is True,
                "incident_mode_blocks_real_writes": True,
                "confirmation_center_still_required_when_clear": True,
                "blocked_real_actions": [
                    "publish",
                    "revise_price",
                    "change_inventory",
                    "refund",
                    "ads",
                    "policy_change",
                    "procurement_payment",
                    "sensitive_customer_commitment",
                ],
            },
            requires_confirmation_center=True,
        ),
        _hardening_drill(
            "new_ebay_account_low_risk_smoke",
            "Clean new eBay account low-risk smoke drill",
            new_account_ready,
            owner="founder_operator",
            next_action=(action_items.get("new_ebay_account_low_risk_smoke") or {}).get("next_action") or "Run the low-risk smoke only after a clean new eBay seller account is available.",
            evidence_summary=(action_items.get("new_ebay_account_low_risk_smoke") or {}).get("evidence_summary") or "old_frozen_account_reuse_allowed=false",
            evidence={
                "old_frozen_account_reuse_allowed": False,
                "uses_old_demo_product_or_sku": False,
                "checklist_tool": "tools/jiejing_new_ebay_account_low_risk_check.py",
                "smoke_passed": _env_bool("JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_PASSED"),
                "smoke_evidence_id_present": bool(os.environ.get("JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_EVIDENCE_ID", "").strip()),
                "publish_requires_confirmation_center": True,
            },
            requires_confirmation_center=True,
        ),
        _hardening_drill(
            "publish_health_confirmation_drill",
            "Publish health report and confirmation-center drill",
            publish_safety_ready,
            owner="publishing_safety",
            next_action=(action_items.get("publish_safety_system") or {}).get("next_action") or "Keep category, item specifics, images, policy, seller limits, fees, profit, and account health in the red/yellow/green report.",
            evidence_summary=(action_items.get("publish_safety_system") or {}).get("evidence_summary") or "waiting_for_publish_health_evidence",
            evidence={
                "confirmation_count": _safe_nonnegative_int(counts.get("confirmations")),
                "execution_result_count": _safe_nonnegative_int(counts.get("execution_results")),
                "official_packet_ready": _official_packet_ready(evidence),
                "red_items_block_publish": True,
                "real_writes_confirmation_gated": True,
            },
            requires_confirmation_center=True,
        ),
        _hardening_drill(
            "final_commercial_smoke",
            "Final paid-launch smoke drill",
            final_smoke_ready,
            owner="release_manager",
            next_action=(action_items.get("final_commercial_smoke") or {}).get("next_action") or "Record register, login, eBay connect, official packet, report, confirmation, execution, and audit-return evidence before public charging.",
            evidence_summary=(action_items.get("final_commercial_smoke") or {}).get("evidence_summary") or "final_smoke_not_recorded",
            evidence={
                "register_login_connect_packet_report_confirm_execute_audit": _env_bool("JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED"),
                "smoke_evidence_id_present": bool(os.environ.get("JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID", "").strip()),
                "public_paid_launch_requires_all_drills": True,
            },
            requires_confirmation_center=True,
        ),
    ]


def _build_new_ebay_account_smoke_runbook(
    *,
    action_items: dict[str, dict[str, Any]],
    readiness: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
    current_store_oauth: dict[str, Any],
    current_store_ebay_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    account_health_ready = current_store_ebay_evidence.get("account_health_ready") is True
    official_packet_ready = current_store_ebay_evidence.get("official_packet_ready") is True
    action_evidence = current_store_ebay_evidence.get("new_account_action_evidence")
    if not isinstance(action_evidence, dict):
        action_evidence = {}
    publish_health_confirmation_ready = action_evidence.get("publish_health_confirmation_ready") is True
    controlled_real_publish_ready = action_evidence.get("controlled_real_publish_ready") is True
    post_publish_cleanup_ready = action_evidence.get("post_publish_cleanup_ready") is True
    health_public_ready = (
        readiness.get("beta_ready") is True
        and _strict_zero_int(readiness.get("blocker_count"))
        and type(readiness.get("warning_count")) is int
        and readiness.get("warning_count") >= 0
        and _readiness_item(readiness, "database_live_probe").get("status") == "ready"
        and _readiness_item(readiness, "queue_runtime_health").get("status") == "ready"
        and _readiness_item(readiness, "worker_runtime_health").get("status") == "ready"
    )
    return [
        _new_account_smoke_step(
            "public_preflight_ready",
            "Public SaaS preflight is healthy",
            health_public_ready,
            owner="release_manager",
            category="preflight",
            next_action="Verify /health, /health/deep and /readiness/product-saas immediately before starting any clean-account test.",
            evidence_summary=_compact_drill_evidence(
                beta_ready=bool(readiness.get("beta_ready")),
                blocker_count=_safe_nonnegative_int(readiness.get("blocker_count")),
                warning_count=_safe_nonnegative_int(readiness.get("warning_count")),
            ),
            verification=["/health", "/health/deep", "/readiness/product-saas", "tools/jiejing_new_ebay_account_low_risk_check.py"],
        ),
        _new_account_smoke_step(
            "clean_new_account_declared",
            "Clean new eBay account boundary",
            _env_all(NEW_EBAY_ACCOUNT_BOUNDARY_FLAGS),
            owner="founder_operator",
            category="account",
            next_action="Confirm the test uses a clean new eBay seller account and does not reuse the frozen old account, old listing, old SKU, old images, old report or old OAuth attempt.",
            evidence_summary=_compact_drill_evidence(
                clean_account_confirmed=_env_bool("JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN"),
                old_frozen_account_rejected=_env_bool("JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED"),
                old_frozen_account_reuse_allowed=False,
                old_demo_assets_allowed=False,
            ),
            verification=["docs/JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_RUNBOOK_20260617.md", "operator audit note", *NEW_EBAY_ACCOUNT_BOUNDARY_FLAGS],
        ),
        _new_account_smoke_step(
            "new_account_oauth_authorization_gate",
            "New-account OAuth authorization gate",
            (
                current_store_oauth.get("authorized") is True
                and current_store_oauth.get("current_store_selected") is True
                and current_store_oauth.get("strong_identity_ready") is True
                and current_store_oauth.get("backend_provenance_ready") is True
            ),
            owner="backend_secret_boundary",
            category="oauth",
            next_action="First verify the authenticated current-store connection. If it is already authorized, do not create another plan or repeat OAuth. Only when evidence is missing and the owner approves this exact external step may the backend create a read-only plan.",
            evidence_summary=_compact_drill_evidence(
                backend_status=current_store_oauth.get("status") or "missing",
                current_store_selected=current_store_oauth.get("current_store_selected") is True,
                strong_identity_ready=current_store_oauth.get("strong_identity_ready") is True,
                backend_provenance_ready=current_store_oauth.get("backend_provenance_ready") is True,
                repeat_oauth_allowed=False,
                raw_token_visible=False,
            ),
            verification=[
                "/connections?store_id={store_id}",
                "/stores/{store_id}/ebay-oauth/read-only-status",
                "/stores/{store_id}/ebay-oauth/read-only-plan",
                "audit log",
                "Vault/KMS secret_ref metadata",
            ],
            triggers_ebay_oauth=False,
            repeat_oauth_allowed=False,
        ),
        _new_account_smoke_step(
            "official_packet_account_health_snapshot",
            "Official packet and account health snapshot",
            official_packet_ready and account_health_ready,
            owner="publishing_safety",
            category="account_health",
            next_action="Verify the existing current-store packet, account health, OAuth identity, completed backend worker job and system audit. Run an official read-only sync only when that evidence is missing and this exact external step is approved.",
            evidence_summary=_compact_drill_evidence(
                packet_sha256=current_store_ebay_evidence.get("packet_id_sha256") or "missing",
                official_packet_ready=official_packet_ready,
                account_health_ready=account_health_ready,
                same_oauth_connection_ready=current_store_ebay_evidence.get("same_oauth_connection_ready") is True,
            ),
            verification=[
                "/readiness/product-saas",
                "/stores/{store_id}/account-health",
                "/connections?store_id={store_id}",
                "/stores/{store_id}/ebay-oauth/read-only-status",
                "/data-packets?store_id={store_id}&platform=ebay&limit=1",
                "/queue-jobs?status=completed&limit=200",
                "/audit-logs?limit=200",
            ],
        ),
        _new_account_smoke_step(
            "new_product_duplicate_guard",
            "New product duplicate guard",
            _env_all(NEW_EBAY_FRESH_PRODUCT_FLAGS),
            owner="publishing_safety",
            category="product",
            next_action="Use only a fresh product, fresh SKU, fresh images and fresh report; reject any match against old demo listing IDs, image hashes, SKUs or report IDs.",
            evidence_summary=_compact_drill_evidence(
                fresh_product_declared=_env_bool("JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED"),
                fresh_sku_declared=_env_bool("JIEJING_NEW_EBAY_FRESH_SKU_DECLARED"),
                fresh_assets_declared=_env_bool("JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED"),
                no_old_listing_or_report_reuse=_env_bool("JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE"),
                duplicate_guard_passed=_env_bool("JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED"),
                old_sku_allowed=False,
                old_image_allowed=False,
            ),
            verification=["publish health report", "source record", "image/SKU/report duplicate check", *NEW_EBAY_FRESH_PRODUCT_FLAGS],
        ),
        _new_account_smoke_step(
            "publish_health_confirmation_gate",
            "Publish health report and confirmation gate",
            official_packet_ready and account_health_ready and publish_health_confirmation_ready,
            owner="publishing_safety",
            category="publish_health",
            next_action="Generate the red/yellow/green publish report; red blocks publish, yellow requires review, and real publish must enter confirmation center.",
            evidence_summary=_compact_drill_evidence(
                publish_health_confirmation_ready=publish_health_confirmation_ready,
                publish_confirmation_id_sha256=action_evidence.get("publish_confirmation_id_sha256") or "missing",
                red_items_block_publish=True,
            ),
            verification=["/stores/{store_id}/publish-confirmation", "/confirmations", "/confirmations/{id}/preflight", "/audit-logs?limit=200"],
            confirmation_center_required=True,
        ),
        _new_account_smoke_step(
            "controlled_real_publish_probe",
            "Controlled real publish probe",
            controlled_real_publish_ready,
            owner="founder_operator",
            category="real_publish",
            next_action="After confirmation approval, execute one low-risk real publish, then record listing ID, offer ID, SKU, platform result and audit evidence.",
            evidence_summary=_compact_drill_evidence(
                controlled_real_publish_ready=controlled_real_publish_ready,
                publish_execution_id_sha256=action_evidence.get("publish_execution_id_sha256") or "missing",
                platform_write_confirmation_gated=True,
            ),
            verification=["/confirmations/{id}/decision", "/confirmations/{id}/execute", "/execution-results", "/audit-logs?limit=200"],
            confirmation_center_required=True,
            real_platform_write_step=True,
        ),
        _new_account_smoke_step(
            "post_publish_cockpit_cleanup_gate",
            "Post-publish cockpit and test cleanup gate",
            post_publish_cleanup_ready,
            owner="release_manager",
            category="post_publish",
            next_action="Run 1h/24h/7d cockpit checks and create a confirmation-gated cleanup plan for any live test listing; do not silently end or delete live eBay state.",
            evidence_summary=_compact_drill_evidence(
                post_publish_cleanup_ready=post_publish_cleanup_ready,
                cleanup_execution_id_sha256=action_evidence.get("cleanup_execution_id_sha256") or "missing",
            ),
            verification=["post-publish cockpit", "/confirmations/{id}/publish-cleanup-plan", "/execution-results", "/audit-logs?limit=200"],
            confirmation_center_required=True,
            real_platform_write_step=True,
        ),
    ]


def _build_paid_launch_cutover_checklist(
    *,
    groups_by_key: dict[str, dict[str, Any]],
    drills: dict[str, dict[str, Any]],
    billing: dict[str, Any],
    domain: dict[str, Any],
    evidence: dict[str, Any],
    current_store_ebay_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    mainland_payment = (
        billing.get("mainland_payment_launch")
        if isinstance(billing.get("mainland_payment_launch"), dict)
        else {}
    )
    rehearsal_evidence = (
        billing.get("wechat_zero_charge_rehearsal_evidence")
        if isinstance(billing.get("wechat_zero_charge_rehearsal_evidence"), dict)
        else {}
    )
    token_drill = drills.get("ebay_refresh_vault_probe") or {}
    return [
        _cutover_item(
            "mainland_wechat_payment_contract",
            "Mainland WeChat production payment contract",
            (drills.get("wechat_pay_zero_charge_production_rehearsal") or {}).get("status") == "ready",
            owner="platform_ops",
            category="billing",
            next_action="Complete canonical WeChat production evidence and the isolated zero-charge rehearsal, then keep the real charge switch closed until exact owner approval.",
            evidence_summary=_compact_drill_evidence(
                provider="wechat_pay_native",
                mainland_payment_ready_for_owner_approval=(
                    mainland_payment.get("mainland_payment_ready_for_owner_approval") is True
                ),
                zero_charge_rehearsal_ready=rehearsal_evidence.get("ready") is True,
                public_charging_allowed=False,
            ),
            environment_keys=[
                "JIEJING_SAAS_ENV",
                "JIEJING_WECHAT_PAY_APP_ID",
                "JIEJING_WECHAT_PAY_MCH_ID",
                "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_API_V3_KEY",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
                "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
                "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
                "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
            ],
            verification=[
                "/billing/payment-options",
                "POST /owner/billing/wechat-pay/zero-charge-rehearsal",
                "tools/test_jiejing_wechat_pay_zero_charge_rehearsal.py",
            ],
            external_resource_required=True,
            triggers_real_charge=False,
            confirmation_center_required=False,
        ),
        _cutover_item(
            "stable_domain_dns_tls_callback",
            "Stable domain, TLS, CORS, and eBay callback",
            (drills.get("stable_domain_cutover") or {}).get("status") == "ready",
            owner="platform_ops",
            category="domain",
            next_action="Bind a stable HTTPS domain, verify DNS/TLS/security headers, align CORS, and update eBay RuName callback to the stable domain.",
            evidence_summary=_compact_drill_evidence(
                domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
            ),
            environment_keys=[
                "JIEJING_PUBLIC_BASE_URL",
                "JIEJING_STABLE_DOMAIN",
                "JIEJING_CORS_ORIGIN",
                "JIEJING_DOMAIN_DNS_VERIFIED",
                "JIEJING_TLS_VERIFIED",
                "JIEJING_EBAY_CALLBACK_VERIFIED",
                "JIEJING_DEPLOYMENT_HARDENED",
                "JIEJING_SECURITY_HEADERS_VERIFIED",
            ],
            verification=["/domain/status", "/commercial/launch-gate", "tools/test_jiejing_domain_launch_gate.py"],
            external_resource_required=True,
            triggers_real_charge=False,
            confirmation_center_required=False,
        ),
        _cutover_item(
            "backup_monitoring_restore_drill",
            "Backup, monitoring, and restore drill",
            (groups_by_key.get("backup_restore") or {}).get("status") == "ready" and (groups_by_key.get("monitoring_alerting") or {}).get("status") == "ready",
            owner="platform_ops",
            category="reliability",
            next_action="Keep managed backup/PITR, restore drill evidence, safe access logs and billing/eBay/queue/model/backup alerts ready before accepting paid merchants.",
            evidence_summary=_compact_drill_evidence(
                backup=(groups_by_key.get("backup_restore") or {}).get("status") or "missing",
                monitoring=(groups_by_key.get("monitoring_alerting") or {}).get("status") or "missing",
            ),
            environment_keys=[
                "JIEJING_BACKUP_PROVIDER",
                "JIEJING_BACKUP_POLICY_CONFIGURED",
                "JIEJING_RESTORE_DRILL_LAST_AT",
                "JIEJING_MONITORING_PROVIDER",
                "JIEJING_ALERT_WEBHOOK_CONFIGURED",
            ],
            verification=["/backup/plan", "/health/deep", "/commercial/launch-gate"],
            external_resource_required=True,
            triggers_real_charge=False,
            confirmation_center_required=False,
        ),
        _cutover_item(
            "legal_risk_boundary_docs",
            "Commercial legal and responsibility boundary",
            (groups_by_key.get("legal_risk_boundary") or {}).get("status") == "ready",
            owner="commercial_ops",
            category="legal",
            next_action="Publish privacy policy, terms, risk disclosure and confirmation-center copy that explains platform-account, billing, audit and responsibility boundaries.",
            evidence_summary=(groups_by_key.get("legal_risk_boundary") or {}).get("next_action") or "privacy/terms/risk/confirmation flags required",
            environment_keys=[
                "JIEJING_PRIVACY_POLICY_VERIFIED",
                "JIEJING_TERMS_VERIFIED",
                "JIEJING_RISK_DISCLOSURE_VERIFIED",
                "JIEJING_CONFIRMATION_TERMS_VISIBLE",
            ],
            verification=["/commercial/launch-gate", "public privacy/terms pages"],
            external_resource_required=False,
            triggers_real_charge=False,
            confirmation_center_required=True,
        ),
        _cutover_item(
            "ebay_refresh_probe_after_new_account",
            "eBay refresh proof after clean new account",
            token_drill.get("status") == "ready"
            and _strict_positive_int(
                token_drill.get("evidence", {}).get("successful_refresh_probe_count")
                if isinstance(token_drill.get("evidence"), dict)
                else None
            ),
            owner="backend_secret_boundary",
            category="ebay",
            next_action="After a clean new eBay seller account is connected, run one backend-only refresh probe through Vault/KMS secret_ref and record audit evidence.",
            evidence_summary=_compact_drill_evidence(
                refresh_success=_safe_nonnegative_int(current_store_ebay_evidence.get("refresh_success_count")),
                same_oauth_connection_ready=current_store_ebay_evidence.get("refresh_same_connection_ready") is True,
                repeat_oauth_allowed=False,
            ),
            environment_keys=[
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
                "JIEJING_VAULT_ENABLED",
                "JIEJING_VAULT_PROVIDER",
                "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
            ],
            verification=["/readiness/product-saas", "/stores/{store_id}/ebay-oauth/refresh-now"],
            external_resource_required=True,
            triggers_real_charge=False,
            confirmation_center_required=False,
            repeat_oauth_allowed=False,
        ),
        _cutover_item(
            "final_paid_launch_smoke_evidence",
            "Final paid-launch smoke evidence",
            (groups_by_key.get("final_commercial_smoke") or {}).get("status") == "ready",
            owner="release_manager",
            category="release",
            next_action="Record the full register, login, connect eBay, packet, report, confirmation center, execution and audit-return smoke before public charging.",
            evidence_summary=_compact_drill_evidence(
                smoke_passed=_env_bool("JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED"),
                evidence_id_present=bool(os.environ.get("JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID", "").strip()),
            ),
            environment_keys=["JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED", "JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID"],
            verification=["/commercial/launch-gate", "output/browser-smoke"],
            external_resource_required=False,
            triggers_real_charge=False,
            confirmation_center_required=True,
        ),
    ]


def _build_wechat_domain_cutover_runbook(
    *,
    cutover_checklist: list[dict[str, Any]],
    billing: dict[str, Any],
    domain: dict[str, Any],
) -> list[dict[str, Any]]:
    by_key = {str(item.get("key") or ""): item for item in cutover_checklist if isinstance(item, dict)}
    mainland_payment = (
        billing.get("mainland_payment_launch")
        if isinstance(billing.get("mainland_payment_launch"), dict)
        else {}
    )
    rehearsal = (
        billing.get("wechat_zero_charge_rehearsal_evidence")
        if isinstance(billing.get("wechat_zero_charge_rehearsal_evidence"), dict)
        else {}
    )
    rollback_env = [
        "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_READINESS_SNAPSHOT_RECORDED",
        "JIEJING_BROWSER_SMOKE_PASSED",
    ]
    rollback_audit_packet_id = "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID"
    return [
        _runbook_step(
            "wechat_pay_production_contract",
            "WeChat Pay production contract",
            (by_key.get("mainland_wechat_payment_contract") or {}).get("status") == "ready",
            owner="platform_ops",
            category="billing",
            next_action="Complete canonical WeChat production configuration and verified payment/refund evidence while public charging remains closed.",
            evidence_summary=_compact_drill_evidence(
                provider="wechat_pay_native",
                owner_ready=mainland_payment.get("mainland_payment_ready_for_owner_approval") is True,
                provider_configured=mainland_payment.get("provider_configured") is True,
                controlled_acceptance=mainland_payment.get("controlled_acceptance_proven") is True,
                public_charging_allowed=False,
            ),
            environment_keys=[
                "JIEJING_SAAS_ENV",
                "JIEJING_WECHAT_PAY_APP_ID",
                "JIEJING_WECHAT_PAY_MCH_ID",
                "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_API_V3_KEY",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
                "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
            ],
            verification=["/billing/payment-options", "tools/test_jiejing_mainland_payment_strategy.py"],
            docs=[],
            external_resource_required=True,
        ),
        _runbook_step(
            "wechat_pay_zero_charge_rehearsal_evidence",
            "WeChat Pay isolated zero-charge rehearsal evidence",
            rehearsal.get("ready") is True,
            owner="platform_ops",
            category="billing",
            next_action="Run the authenticated exact-phrase WeChat zero-charge rehearsal and retain its value-free backend audit evidence.",
            evidence_summary=_compact_drill_evidence(
                ready=rehearsal.get("ready") is True,
                step_count=_safe_nonnegative_int(rehearsal.get("step_count")),
                fake_transport_call_count=_safe_nonnegative_int(rehearsal.get("fake_transport_call_count")),
                calls_external_api=False,
                triggers_real_charge=False,
            ),
            environment_keys=[],
            verification=[
                "POST /owner/billing/wechat-pay/zero-charge-rehearsal",
                "tools/test_jiejing_wechat_pay_zero_charge_rehearsal.py",
            ],
            docs=[],
            external_resource_required=False,
        ),
        _runbook_step(
            "wechat_pay_public_charge_approval_hold",
            "WeChat Pay public-charge approval hold",
            not _env_bool("JIEJING_WECHAT_PAY_CHARGE_ALLOWED"),
            owner="founder_operator",
            category="billing",
            next_action="Keep the charge switch false until the version-bound paid-launch and production-release approvals are recorded; never treat owner-ready as public charging.",
            evidence_summary=_compact_drill_evidence(
                charge_switch_closed=not _env_bool("JIEJING_WECHAT_PAY_CHARGE_ALLOWED"),
                paid_launch_owner_packet_present=_env_present("JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID"),
                production_release_owner_packet_present=_env_present("JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID"),
                public_charging_allowed=False,
            ),
            environment_keys=[
                "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
                "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
                "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID",
            ],
            verification=["/owner/paid-launch-approval-packet", "/owner/production-release-gate"],
            docs=[],
            external_resource_required=False,
            owner_approval_required=True,
        ),
        _runbook_step(
            "stable_domain_dns_tls_headers",
            "Stable domain DNS, TLS, and security headers",
            (by_key.get("stable_domain_dns_tls_callback") or {}).get("status") == "ready"
            and bool(domain.get("security_headers_verified")),
            owner="platform_ops",
            category="domain",
            next_action="Keep DNS, TLS, deployment hardening and security headers verified on the stable HTTPS domain before routing public paid traffic.",
            evidence_summary=_compact_drill_evidence(
                domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                hardened=bool(domain.get("deployment_hardened")),
                security_headers=bool(domain.get("security_headers_verified")),
            ),
            environment_keys=[
                "JIEJING_PUBLIC_BASE_URL",
                "JIEJING_STABLE_DOMAIN",
                "JIEJING_DOMAIN_DNS_VERIFIED",
                "JIEJING_TLS_VERIFIED",
                "JIEJING_DEPLOYMENT_HARDENED",
                "JIEJING_SECURITY_HEADERS_VERIFIED",
            ],
            verification=["/domain/status", "/health/deep", "tools/test_jiejing_domain_launch_gate.py"],
            docs=[],
            external_resource_required=True,
        ),
        _runbook_step(
            "stable_domain_oauth_cors_alignment",
            "Stable domain OAuth callback and CORS alignment",
            bool(domain.get("stable_host"))
            and bool(domain.get("https_only"))
            and bool(domain.get("ebay_callback_verified"))
            and bool(domain.get("cors_origin_aligned")),
            owner="platform_ops",
            category="domain",
            next_action="Align stable HTTPS CORS and eBay callback evidence without repeating OAuth.",
            evidence_summary=_compact_drill_evidence(
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
                repeat_oauth_allowed=False,
            ),
            environment_keys=["JIEJING_CORS_ORIGIN", "JIEJING_EBAY_CALLBACK_VERIFIED"],
            verification=["/domain/status", "eBay callback audit evidence"],
            docs=[],
            external_resource_required=True,
            repeat_oauth_allowed=False,
            triggers_ebay_oauth=False,
        ),
        _runbook_step(
            "cutover_rollback_audit_packet",
            "Cutover rollback and audit packet",
            (by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") == "ready"
            and all(_env_bool(name) for name in rollback_env)
            and _env_present(rollback_audit_packet_id),
            owner="release_manager",
            category="release",
            next_action="Record rollback plan, secret scan, readiness snapshots and browser smoke evidence before owner approval.",
            evidence_summary=_compact_drill_evidence(
                final_smoke=(by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") or "missing",
                rollback_verified=_env_bool("JIEJING_CUTOVER_ROLLBACK_VERIFIED"),
                secret_scan=_env_bool("JIEJING_SECRET_SCAN_PASSED"),
                readiness_snapshot=_env_bool("JIEJING_READINESS_SNAPSHOT_RECORDED"),
                browser_smoke=_env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
                audit_packet_id_present=_env_present(rollback_audit_packet_id),
            ),
            environment_keys=[*rollback_env, rollback_audit_packet_id],
            verification=["tools/jiejing_secret_scan.py", "/health/deep", "/readiness/product-saas"],
            docs=[],
            external_resource_required=False,
            owner_approval_required=True,
        ),
    ]


def _build_paid_launch_cutover_decision(
    *,
    cutover_checklist: list[dict[str, Any]],
    billing: dict[str, Any],
    domain: dict[str, Any],
    paid_launch_ready: bool,
) -> dict[str, Any]:
    by_key = {str(item.get("key") or ""): item for item in cutover_checklist if isinstance(item, dict)}
    blocked_items = [item for item in cutover_checklist if isinstance(item, dict) and item.get("status") != "ready"]
    runbook = _build_wechat_domain_cutover_runbook(
        cutover_checklist=cutover_checklist,
        billing=billing,
        domain=domain,
    )
    blocked_runbook = [item for item in runbook if isinstance(item, dict) and item.get("status") != "ready"]
    ready_for_owner_approval = paid_launch_ready and not blocked_items and not blocked_runbook
    next_item = blocked_items[0] if blocked_items else {}
    next_runbook = blocked_runbook[0] if blocked_runbook else {}
    lane_order = ["billing", "domain", "reliability", "legal", "ebay", "release"]
    lanes = [_cutover_decision_lane(category, cutover_checklist=cutover_checklist) for category in lane_order]
    return {
        "contract_version": "2026-06-18-paid-launch-cutover-decision",
        "source": "paid_launch_cutover_checklist",
        "status": "ready_for_owner_approval" if ready_for_owner_approval else "blocked",
        "public_paid_launch_allowed": False,
        "final_owner_approval_recorded": False,
        "public_charging_gate_open": False,
        "charge_now_allowed": False,
        "platform_write_now_allowed": False,
        "repeat_ebay_oauth_allowed": False,
        "owner_approval_required": True,
        "confirmation_center_required_for_real_risk_actions": True,
        "blocked_keys": [str(item.get("key") or "") for item in blocked_items],
        "ready_count": len(cutover_checklist) - len(blocked_items),
        "total_count": len(cutover_checklist),
        "next_operator_step": _cutover_next_operator_step(next_item),
        "lanes": lanes,
        "billing_domain_cutover_runbook": runbook,
        "blocked_runbook_keys": [str(item.get("key") or "") for item in blocked_runbook],
        "runbook_ready_count": len(runbook) - len(blocked_runbook),
        "runbook_total_count": len(runbook),
        "runbook_blocked_count": len(blocked_runbook),
        "next_runbook_step": _cutover_next_operator_step(next_runbook),
        "billing_live_contract_ready": (by_key.get("mainland_wechat_payment_contract") or {}).get("status") == "ready",
        "stable_domain_ready": (by_key.get("stable_domain_dns_tls_callback") or {}).get("status") == "ready",
        "wechat_zero_charge_rehearsal_ready": (
            billing.get("wechat_zero_charge_rehearsal_evidence") or {}
        ).get("ready") is True,
        "ebay_refresh_proof_ready": (by_key.get("ebay_refresh_probe_after_new_account") or {}).get("status") == "ready",
        "rollback_plan": [
            "keep_current_staging_url_available_until_stable_domain_smoke_passes",
            "do_not_enable_public_checkout_until_billing_domain_legal_and_final_smoke_are_ready",
            "close_wechat_charge_switch_if_signed_callback_query_refund_or_entitlement_smoke_fails",
            "keep_real_ebay_writes_confirmation_gated_after_cutover",
        ],
        "evidence_to_record": [
            "domain_status_json",
            "mainland_wechat_payment_contract_json",
            "wechat_zero_charge_rehearsal_audit",
            "wechat_charge_approval_hold_json",
            "commercial_launch_gate_json",
            "browser_smoke_output",
            "secret_scan_output",
        ],
        "secret_exposed": False,
    }


def _cutover_decision_lane(category: str, *, cutover_checklist: list[dict[str, Any]]) -> dict[str, Any]:
    items = [item for item in cutover_checklist if isinstance(item, dict) and item.get("category") == category]
    ready_count = sum(1 for item in items if item.get("status") == "ready")
    blocked = [str(item.get("key") or "") for item in items if item.get("status") != "ready"]
    return {
        "category": category,
        "status": "ready" if items and not blocked else "blocked",
        "ready_count": ready_count,
        "total_count": len(items),
        "blocked_keys": blocked,
        "secret_exposed": False,
    }


def _cutover_next_operator_step(item: dict[str, Any]) -> dict[str, Any]:
    if not item:
        return {
            "key": "",
            "title": "owner_approval",
            "owner": "release_manager",
            "category": "release",
            "next_action": "All cutover evidence is ready; require owner approval before public charging.",
            "environment_keys": [],
            "verification": ["/commercial/launch-gate"],
            "secret_exposed": False,
        }
    return {
        "key": item.get("key") or "",
        "title": item.get("title") or item.get("key") or "",
        "owner": item.get("owner") or "platform_ops",
        "category": item.get("category") or "cutover",
        "next_action": item.get("next_action") or "",
        "environment_keys": list(item.get("environment_keys") or [])[:8],
        "verification": list(item.get("verification") or [])[:6],
        "secret_exposed": False,
    }


def _cutover_item(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    category: str,
    next_action: str,
    evidence_summary: str,
    environment_keys: list[str],
    verification: list[str],
    external_resource_required: bool,
    triggers_real_charge: bool,
    confirmation_center_required: bool,
    repeat_oauth_allowed: bool | None = None,
) -> dict[str, Any]:
    item = {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "owner": owner,
        "category": category,
        "blocks_paid_launch": not ready,
        "external_resource_required": external_resource_required,
        "triggers_real_charge": triggers_real_charge,
        "triggers_real_platform_write": False,
        "confirmation_center_required": confirmation_center_required,
        "environment_keys": environment_keys,
        "verification": verification,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "secret_exposed": False,
    }
    if repeat_oauth_allowed is not None:
        item["repeat_oauth_allowed"] = repeat_oauth_allowed
    return item


def _runbook_step(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    category: str,
    next_action: str,
    evidence_summary: str,
    environment_keys: list[str],
    verification: list[str],
    docs: list[str],
    external_resource_required: bool,
    repeat_oauth_allowed: bool | None = None,
    triggers_ebay_oauth: bool = False,
    owner_approval_required: bool = False,
) -> dict[str, Any]:
    item = {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "owner": owner,
        "category": category,
        "blocks_paid_launch": not ready,
        "external_resource_required": external_resource_required,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "triggers_ebay_oauth": triggers_ebay_oauth,
        "owner_approval_required": owner_approval_required,
        "confirmation_center_required": False,
        "environment_keys": environment_keys,
        "verification": verification,
        "docs": docs,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "secret_exposed": False,
    }
    if repeat_oauth_allowed is not None:
        item["repeat_oauth_allowed"] = repeat_oauth_allowed
    return item


def _new_account_smoke_step(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    category: str,
    next_action: str,
    evidence_summary: str,
    verification: list[str],
    confirmation_center_required: bool = False,
    triggers_ebay_oauth: bool = False,
    repeat_oauth_allowed: bool = False,
    real_platform_write_step: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "owner": owner,
        "category": category,
        "blocks_paid_launch": not ready,
        "requires_clean_new_ebay_account": True,
        "old_frozen_account_reuse_allowed": False,
        "old_demo_product_or_sku_allowed": False,
        "triggers_ebay_oauth": triggers_ebay_oauth,
        "repeat_oauth_allowed": repeat_oauth_allowed,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "real_platform_write_step": real_platform_write_step,
        "confirmation_center_required": confirmation_center_required,
        "permanent_audit_required": True,
        "verification": verification,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "secret_exposed": False,
    }


def _hardening_drill(
    key: str,
    title: str,
    ready: bool,
    *,
    owner: str,
    next_action: str,
    evidence_summary: str,
    evidence: dict[str, Any],
    requires_confirmation_center: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "owner": owner,
        "blocks_paid_launch": not ready,
        "requires_confirmation_center": requires_confirmation_center,
        "next_action": next_action,
        "evidence_summary": evidence_summary,
        "evidence": {**evidence, "secret_exposed": False},
        "secret_exposed": False,
    }


def _compact_drill_evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())


def _action_plan_item(
    key: str,
    *,
    by_key: dict[str, dict[str, Any]],
    readiness: dict[str, Any],
    billing: dict[str, Any],
    domain: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
) -> dict[str, Any]:
    group = by_key.get(key) or {}
    readiness_item = _readiness_item(readiness, key)
    ready_statuses = {"ready", "packet_backed_gate_ready", "vault_backed_refresh_adapter_ready"}
    status = "ready" if group.get("status") == "ready" or readiness_item.get("status") in ready_statuses else "blocked"
    titles = {
        "billing_quota": "大陆微信支付与额度",
        "stable_domain_tls": "稳定域名与 OAuth callback",
        "ebay_token_refresh_vault_adapter": "eBay 授权自动续期",
        "account_health_incident_mode": "账号健康与事故模式",
        "new_ebay_account_low_risk_smoke": "新 eBay 账号低风险演练",
        "publish_safety_system": "发布体检报告",
        "store_sync_visibility": "真实店铺同步可视化",
        "post_publish_cockpit": "发布后驾驶舱",
        "legal_risk_boundary": "商业责任边界",
        "final_commercial_smoke": "最终商业 smoke",
    }
    owners = {
        "billing_quota": "平台运营",
        "stable_domain_tls": "平台运维",
        "ebay_token_refresh_vault_adapter": "后端密钥边界",
        "account_health_incident_mode": "发布安全系统",
        "new_ebay_account_low_risk_smoke": "主理人测试",
        "publish_safety_system": "Listing 安全系统",
        "store_sync_visibility": "eBay 数据同步",
        "post_publish_cockpit": "经营复盘系统",
        "legal_risk_boundary": "商业与合规",
        "final_commercial_smoke": "发布经理",
    }
    next_actions = {
        "billing_quota": "完成微信支付生产证据和隔离零扣款演练；在最终书面批准前保持公开收费关闭。",
        "stable_domain_tls": "绑定稳定域名，完成 DNS/TLS、CORS、eBay callback、部署硬化和安全头验证。",
        "ebay_token_refresh_vault_adapter": "用后端 Vault/KMS secret_ref 跑一次真实 refresh 证明；前端、Runtime、报告和记忆都不能拿到原始 token。",
        "account_health_incident_mode": "每次真实写入前读取账号健康快照；冻结、受限、付款冻结、额度不足时进入事故模式，只允许诊断和证据包。",
        "new_ebay_account_low_risk_smoke": "等新账号可用后，按低风险顺序跑新 OAuth、官方 packet、账号健康、发布体检、确认中心、真实发布、复盘和清理。",
        "publish_safety_system": "把类目、item specifics、图片、VeRO/IP、禁售词、GPSR、policy、卖家额度、费用和利润做成红黄绿发布体检。",
        "store_sync_visibility": "设置页和工作台清楚显示店铺名、商品/offer/订单/policy 数、packet ID 和最后同步时间。",
        "post_publish_cockpit": "发布后 1 小时、24 小时、7 天复盘曝光、点击、收藏、售出、费用、利润和客服风险。",
        "legal_risk_boundary": "完善隐私政策、服务条款、风险披露、确认中心文案和审计证据，明确平台账号风险责任边界。",
        "final_commercial_smoke": "正式收费前记录注册、登录、连 eBay、生成 packet、跑报告、确认中心、真实执行和审计回流的完整证据。",
    }
    return {
        "key": key,
        "title": titles.get(key, key),
        "status": status,
        "severity": "info" if status == "ready" else "blocker",
        "owner": owners.get(key, "平台"),
        "affects_paid_launch": True,
        "next_action": next_actions.get(key) or group.get("next_action") or readiness_item.get("next_action") or "",
        "evidence_summary": _action_evidence_summary(
            key,
            readiness_item=readiness_item,
            group=group,
            billing=billing,
            domain=domain,
            evidence=evidence,
            counts=counts,
        ),
        "source": "commercial_launch_gate" if group else "product_readiness",
        "secret_exposed": False,
    }


def _action_evidence_summary(
    key: str,
    *,
    readiness_item: dict[str, Any],
    group: dict[str, Any],
    billing: dict[str, Any],
    domain: dict[str, Any],
    evidence: dict[str, Any],
    counts: dict[str, Any],
) -> str:
    if key == "billing_quota":
        payment = (
            billing.get("mainland_payment_launch")
            if isinstance(billing.get("mainland_payment_launch"), dict)
            else {}
        )
        rehearsal = (
            billing.get("wechat_zero_charge_rehearsal_evidence")
            if isinstance(billing.get("wechat_zero_charge_rehearsal_evidence"), dict)
            else {}
        )
        return (
            "provider=wechat_pay_native; "
            f"owner_ready={payment.get('mainland_payment_ready_for_owner_approval') is True}; "
            f"zero_charge_rehearsal_ready={rehearsal.get('ready') is True}; "
            "public_charging_allowed=false"
        )
    if key == "stable_domain_tls":
        blockers = domain.get("blockers") or []
        return f"domain={domain.get('stable_domain') or 'not_selected'}; blockers={len(blockers)}"
    if key == "ebay_token_refresh_vault_adapter":
        return (
            f"readiness={readiness_item.get('status') or 'missing'}; "
            f"secret_refs_present={bool(evidence.get('ebay_secret_refs'))}; "
            f"refresh_probe_success={_safe_nonnegative_int(evidence.get('ebay_token_refresh_success_count'))}"
        )
    if key == "account_health_incident_mode":
        return f"readiness={readiness_item.get('status') or 'missing'}; packet={evidence.get('latest_ebay_packet_id') or 'missing'}"
    if key == "new_ebay_account_low_risk_smoke":
        return "old_frozen_account_reuse_allowed=false"
    if key == "publish_safety_system":
        return f"confirmations={_safe_nonnegative_int(counts.get('confirmations'))}; official_packet={_official_packet_ready(evidence)}"
    if key == "store_sync_visibility":
        return f"packet={evidence.get('latest_ebay_packet_id') or 'missing'}; stores={_safe_nonnegative_int(counts.get('stores'))}"
    if key == "post_publish_cockpit":
        return f"execution_results={_safe_nonnegative_int(counts.get('execution_results'))}"
    if key == "legal_risk_boundary":
        return "privacy/terms/risk/confirmation flags required"
    if key == "final_commercial_smoke":
        return f"passed={_env_bool('JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED')}"
    return str(group.get("status") or readiness_item.get("status") or "waiting")


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_all(names: list[str]) -> bool:
    return all(_env_bool(name) for name in names)


def _env_present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())
