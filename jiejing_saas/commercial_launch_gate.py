"""Commercial launch gate for Jiejing SaaS."""

from __future__ import annotations

import os
from typing import Any

from .backup_plan import build_backup_plan
from .billing_plan import STRIPE_CURRENT_API_VERSION, build_billing_plan, stripe_webhook_api_version, stripe_webhook_api_version_aligned
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .infrastructure_drivers import build_infrastructure_driver_status
from .model_value_gate import build_model_value_gate
from .monitoring import build_monitoring_status
from .readiness import build_product_readiness
from .repository import SaaSRepository
from .vault_adapter import build_vault_adapter_contract


def build_commercial_launch_gate(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    readiness = build_product_readiness(settings, repository)
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else repository.product_readiness_evidence()
    counts = readiness.get("counts") if isinstance(readiness.get("counts"), dict) else repository.system_counts()
    infrastructure = build_infrastructure_driver_status(settings)
    backup = build_backup_plan(settings, repository)
    billing = build_billing_plan(settings, repository)
    model_value = build_model_value_gate(settings, repository)
    monitoring = build_monitoring_status(settings, repository)
    domain = build_domain_readiness(settings)
    vault = build_vault_adapter_contract(settings)
    groups = [
        _group(
            "official_ebay_read_loop",
            "Official eBay read-only loop",
            _official_packet_ready(evidence),
            "Connect seller account, keep OAuth callback complete, and preserve the six-resource official packet.",
            evidence={
                "latest_ebay_packet_id": evidence.get("latest_ebay_packet_id"),
                "present_resource_keys": evidence.get("latest_ebay_packet_present_resource_keys", []),
                "missing_resource_keys": evidence.get("latest_ebay_packet_missing_resource_keys", []),
                "optional_missing_resource_keys": _official_packet_optional_missing(evidence),
                "read_only_authorized_connections": evidence.get("read_only_authorized_connections"),
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
            "Billing and quota",
            bool(billing.get("billing_ready_for_paid_launch")),
            "Choose billing provider, publish plan IDs, configure webhook, and enforce merchant-visible quotas.",
            evidence={"provider": (billing.get("provider") or {}).get("selected"), "blockers": billing.get("blockers", [])},
        ),
        _group(
            "publish_safety_system",
            "Publishing safety report",
            _publish_safety_ready(evidence, counts),
            "Keep category, item specifics, images, VeRO/IP, prohibited terms, GPSR, location, policy, seller limits, fees and profit in the merchant-visible publish health report.",
            evidence={
                "confirmation_count": counts.get("confirmations", 0),
                "execution_result_count": counts.get("execution_results", 0),
                "official_packet_ready": _official_packet_ready(evidence),
                "red_items_block_publish": True,
                "real_writes_confirmation_gated": True,
            },
        ),
        _group(
            "store_sync_visibility",
            "Store sync visibility",
            _official_packet_ready(evidence),
            "Show store name, product/offer/order/policy counts, latest sync time and packet id before any IP or publishing claim.",
            evidence={
                "latest_ebay_packet_id": evidence.get("latest_ebay_packet_id"),
                "present_resource_keys": evidence.get("latest_ebay_packet_present_resource_keys", []),
                "store_count": counts.get("stores", 0),
                "platform_connection_count": counts.get("platform_connections", 0),
            },
        ),
        _group(
            "post_publish_cockpit",
            "Post-publish cockpit",
            int(counts.get("execution_results") or 0) > 0,
            "After publish, run 1h, 24h and 7d reviews for exposure, clicks, watchers, sales, fees, profit and support risk; price, inventory, end listing and ads still require confirmation.",
            evidence={
                "execution_result_count": counts.get("execution_results", 0),
                "review_windows": ["1h", "24h", "7d"],
                "real_changes_confirmation_gated": True,
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
            _readiness_status_ready(readiness, "ebay_token_refresh", {"vault_backed_refresh_adapter_ready"}),
            "Prove backend-only refresh through the Vault/KMS secret_ref adapter; never expose access or refresh tokens to frontend, Runtime, reports or memory.",
            evidence={
                "readiness_status": _readiness_item(readiness, "ebay_token_refresh").get("status", ""),
                "readiness_severity": _readiness_item(readiness, "ebay_token_refresh").get("severity", ""),
                "secret_refs_present": bool(evidence.get("ebay_secret_refs")),
                "successful_refresh_probe_count": int(evidence.get("ebay_token_refresh_success_count") or 0),
                "latest_successful_refresh_probe_at": evidence.get("latest_ebay_token_refresh_success_at") or "",
                "frontend_gets_raw_token": False,
                "runtime_gets_raw_token": False,
            },
        ),
        _group(
            "new_ebay_account_low_risk_smoke",
            "Clean new eBay account smoke",
            _env_bool("JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_PASSED"),
            "After the merchant has a clean new eBay seller account, run the low-risk sequence: new OAuth, official packet, account health, publish health, confirmation center, real publish, cockpit and cleanup.",
            evidence={
                "old_frozen_account_reuse_allowed": False,
                "new_account_smoke_passed": _env_bool("JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_PASSED"),
                "smoke_evidence_id": os.environ.get("JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_SMOKE_EVIDENCE_ID", "").strip(),
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
    )
    return {
        "contract_version": "2026-05-18-c-class-commercial-launch-gate",
        "environment": settings.environment,
        "paid_commercial_launch_ready": paid_launch_ready,
        "seed_merchant_beta_ready": _seed_beta_ready(groups),
        "readiness": {
            "production_ready": readiness.get("production_ready"),
            "beta_ready": readiness.get("beta_ready"),
            "blocker_count": readiness.get("blocker_count"),
            "warning_count": readiness.get("warning_count"),
        },
        "groups": groups,
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
        and int(counts.get("confirmations") or 0) > 0
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
    )
    new_account_smoke_runbook = _build_new_ebay_account_smoke_runbook(
        action_items=action_items,
        readiness=readiness,
        evidence=evidence,
        counts=counts,
    )
    cutover_checklist = _build_paid_launch_cutover_checklist(
        groups_by_key=by_key,
        drills={item["key"]: item for item in drills},
        billing=billing,
        domain=domain,
        evidence=evidence,
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
    billing_provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    billing_test = billing.get("billing_test_rehearsal_summary") if isinstance(billing.get("billing_test_rehearsal_summary"), dict) else {}
    quota_shutdown = billing.get("subscription_quota_shutdown_closure") if isinstance(billing.get("subscription_quota_shutdown_closure"), dict) else {}
    no_charge_ready = bool(billing_test.get("ready")) or bool(quota_shutdown.get("ready_for_no_charge_rehearsal"))
    readiness_snapshot_ready = (
        readiness.get("beta_ready") is True
        and int(readiness.get("blocker_count") or 0) == 0
        and _readiness_item(readiness, "database_live_probe").get("status") == "ready"
        and _readiness_item(readiness, "queue_runtime_health").get("status") == "ready"
        and _readiness_item(readiness, "worker_runtime_health").get("status") == "ready"
    )
    external_deferred = [
        _prelaunch_external_deferred_item(
            "formal_payment_deferred",
            "Formal payment provider cutover deferred",
            owner="founder_operator",
            category="billing",
            next_action="Keep live Stripe or alternative payment cutover frozen until the owner supplies a verified payment account, live price IDs, live webhook secret, and stable-domain URLs.",
            evidence_summary=_compact_drill_evidence(
                provider=billing_provider.get("selected") or "not_selected",
                billing_paid_ready=bool(billing.get("billing_ready_for_paid_launch")),
                paid_launch_blockers=len(billing.get("paid_launch_blockers") or []),
                cutover_status=cutover_decision.get("status") or "blocked",
            ),
            verification=["/billing/plans", "/commercial/launch-gate", "tools/test_jiejing_billing_test_provider.py"],
        ),
        _prelaunch_external_deferred_item(
            "clean_ebay_account_validation_deferred",
            "Clean new eBay account real validation deferred",
            owner="founder_operator",
            category="ebay",
            next_action="Do not repeat OAuth or run any real eBay write until a clean new seller account and fresh real test product assets are ready.",
            evidence_summary=_compact_drill_evidence(
                old_frozen_account_reuse_allowed=False,
                refresh_probe_success=int(evidence.get("ebay_token_refresh_success_count") or 0),
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
            "No-real-charge billing and quota rehearsal",
            no_charge_ready,
            owner="billing_ops",
            category="billing",
            next_action=billing_test.get("next_step") or quota_shutdown.get("next_step") or "Keep the stripe_test_mock billing path able to rehearse activate, payment_failed, cancel and quota hard-stop without real Stripe.",
            evidence_summary=_compact_drill_evidence(
                test_provider_ready=bool(billing_test.get("ready")),
                quota_shutdown_ready=bool(quota_shutdown.get("ready_for_no_charge_rehearsal")),
                provider=billing_provider.get("selected") or "not_selected",
            ),
            verification=["tools/test_jiejing_billing_test_provider.py", "tools/test_jiejing_billing_webhook_subscription_state.py"],
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
            verification=["/domain/edge-cutover-preflight", "/rate-limit/status", "tools/test_jiejing_public_anti_scrape_hardening.py"],
        ),
        _prelaunch_internal_work_item(
            "test_data_governance_review",
            "Staging smoke data governance review",
            _env_bool("JIEJING_TEST_DATA_GOVERNANCE_REVIEWED"),
            owner="release_manager",
            category="data_governance",
            next_action="Review smoke/demo markers and keep deletion disabled by default; real cleanup remains confirmation-gated and data-safe.",
            evidence_summary=_compact_drill_evidence(
                users=int(counts.get("users") or 0),
                stores=int(counts.get("stores") or 0),
                tasks=int(counts.get("tasks") or 0),
                reviewed=_env_bool("JIEJING_TEST_DATA_GOVERNANCE_REVIEWED"),
            ),
            verification=["/owner/launch-control", "repository smoke data governance report"],
            confirmation_center_required=True,
        ),
        _prelaunch_internal_work_item(
            "confirmation_center_copy_and_rollback",
            "Confirmation center, rollback, and audit packet",
            int(counts.get("confirmations") or 0) > 0 and bool((cutover_decision.get("rollback_plan") or [])),
            owner="release_manager",
            category="release",
            next_action="Keep every real publish, cleanup, refund, pricing, inventory, ad, policy or sensitive customer promise behind confirmation and rollback evidence.",
            evidence_summary=_compact_drill_evidence(
                confirmations=int(counts.get("confirmations") or 0),
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
                blocker_count=int(readiness.get("blocker_count") or 0),
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
) -> list[dict[str, Any]]:
    _ = groups_by_key
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    provider_contract = provider.get("signed_webhook_contract") if isinstance(provider.get("signed_webhook_contract"), dict) else {}
    checkout_contract = provider.get("checkout_portal_contract") if isinstance(provider.get("checkout_portal_contract"), dict) else {}
    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    billing_ready = bool(billing.get("billing_ready_for_paid_launch"))
    domain_ready = bool(domain.get("production_domain_ready"))
    token_ready = (action_items.get("ebay_token_refresh_vault_adapter") or {}).get("status") == "ready"
    account_health_ready = (action_items.get("account_health_incident_mode") or {}).get("status") == "ready"
    publish_safety_ready = (action_items.get("publish_safety_system") or {}).get("status") == "ready"
    new_account_ready = (action_items.get("new_ebay_account_low_risk_smoke") or {}).get("status") == "ready"
    final_smoke_ready = (action_items.get("final_commercial_smoke") or {}).get("status") == "ready"

    return [
        _hardening_drill(
            "stripe_billing_live_mode",
            "Stripe paid billing live-mode drill",
            billing_ready and provider.get("selected") == "stripe",
            owner="platform_ops",
            next_action=(action_items.get("billing_quota") or {}).get("next_action") or "Configure Stripe Billing, Checkout, Customer Portal, signed webhook, plan IDs, and quota enforcement.",
            evidence_summary=_compact_drill_evidence(
                provider=provider.get("selected") or "not_selected",
                stripe_api_version=checkout_contract.get("stripe_api_version") or "",
                checkout_ready=bool(checkout_sessions.get("ready")),
                portal_ready=bool(customer_portal.get("ready")),
                webhook_configured=bool(provider.get("webhook_configured")),
                quota_enabled=bool((billing.get("quota_contract") or {}).get("enabled")),
            ),
            evidence={
                "selected_provider": provider.get("selected") or "not_selected",
                "stripe_api_version": checkout_contract.get("stripe_api_version") or "",
                "checkout_sessions_ready": bool(checkout_sessions.get("ready")),
                "checkout_mode": checkout_sessions.get("mode") or "",
                "customer_portal_ready": bool(customer_portal.get("ready")),
                "signed_webhook_configured": bool(provider.get("webhook_configured")),
                "plan_ids_present": provider_contract.get("plan_ids") or {},
                "quota_enforcement_enabled": bool((billing.get("quota_contract") or {}).get("enabled")),
                "frontend_gets_api_key": False,
                "raw_payment_secret_exposed": False,
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
                refresh_success=int(evidence.get("ebay_token_refresh_success_count") or 0),
            ),
            evidence={
                "readiness_status": (_readiness_item(readiness, "ebay_token_refresh") or {}).get("status") or "",
                "secret_refs_present": bool(evidence.get("ebay_secret_refs")),
                "successful_refresh_probe_count": int(evidence.get("ebay_token_refresh_success_count") or 0),
                "latest_successful_refresh_probe_at": evidence.get("latest_ebay_token_refresh_success_at") or "",
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
                "latest_packet_id": evidence.get("latest_ebay_packet_id") or "",
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
                "confirmation_count": int(counts.get("confirmations") or 0),
                "execution_result_count": int(counts.get("execution_results") or 0),
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
) -> list[dict[str, Any]]:
    account_health_ready = (action_items.get("account_health_incident_mode") or {}).get("status") == "ready"
    publish_safety_ready = (action_items.get("publish_safety_system") or {}).get("status") == "ready"
    post_publish_ready = (action_items.get("post_publish_cockpit") or {}).get("status") == "ready"
    official_packet_ready = _official_packet_ready(evidence)
    health_public_ready = (
        readiness.get("beta_ready") is True
        and int(readiness.get("blocker_count") or 0) == 0
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
                blocker_count=int(readiness.get("blocker_count") or 0),
                warning_count=int(readiness.get("warning_count") or 0),
            ),
            verification=["/health", "/health/deep", "/readiness/product-saas", "tools/jiejing_new_ebay_account_low_risk_check.py"],
        ),
        _new_account_smoke_step(
            "clean_new_account_declared",
            "Clean new eBay account boundary",
            _env_bool("JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN"),
            owner="founder_operator",
            category="account",
            next_action="Confirm the test uses a clean new eBay seller account and does not reuse the frozen old account, old listing, old SKU, old images, old report or old OAuth attempt.",
            evidence_summary=_compact_drill_evidence(
                clean_account_confirmed=_env_bool("JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN"),
                old_frozen_account_reuse_allowed=False,
                old_demo_assets_allowed=False,
            ),
            verification=["docs/JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_RUNBOOK_20260617.md", "operator audit note"],
        ),
        _new_account_smoke_step(
            "new_account_oauth_authorization_gate",
            "New-account OAuth authorization gate",
            _env_bool("JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED"),
            owner="backend_secret_boundary",
            category="oauth",
            next_action="Only after the owner explicitly starts the clean-account test, run OAuth through the SaaS backend and store refresh capability behind Vault/KMS secret_ref.",
            evidence_summary=_compact_drill_evidence(
                oauth_completed=_env_bool("JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED"),
                repeat_oauth_allowed=False,
                raw_token_visible=False,
            ),
            verification=["/stores/{store_id}/ebay-oauth/start", "audit log", "Vault/KMS secret_ref metadata"],
            triggers_ebay_oauth=False,
            repeat_oauth_allowed=False,
        ),
        _new_account_smoke_step(
            "official_packet_account_health_snapshot",
            "Official packet and account health snapshot",
            official_packet_ready and account_health_ready,
            owner="publishing_safety",
            category="account_health",
            next_action="Run official read-only sync, then show store, policy, inventory/offer/order, finance, taxonomy and account-health evidence before any publish attempt.",
            evidence_summary=_compact_drill_evidence(
                packet=evidence.get("latest_ebay_packet_id") or "missing",
                official_packet_ready=official_packet_ready,
                account_health_ready=account_health_ready,
            ),
            verification=["/readiness/product-saas", "/stores/{store_id}/account-health"],
        ),
        _new_account_smoke_step(
            "new_product_duplicate_guard",
            "New product duplicate guard",
            _env_bool("JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED"),
            owner="publishing_safety",
            category="product",
            next_action="Use only a fresh product, fresh SKU, fresh images and fresh report; reject any match against old demo listing IDs, image hashes, SKUs or report IDs.",
            evidence_summary=_compact_drill_evidence(
                duplicate_guard_passed=_env_bool("JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED"),
                old_sku_allowed=False,
                old_image_allowed=False,
            ),
            verification=["publish health report", "source record", "image/SKU/report duplicate check"],
        ),
        _new_account_smoke_step(
            "publish_health_confirmation_gate",
            "Publish health report and confirmation gate",
            publish_safety_ready,
            owner="publishing_safety",
            category="publish_health",
            next_action="Generate the red/yellow/green publish report; red blocks publish, yellow requires review, and real publish must enter confirmation center.",
            evidence_summary=_compact_drill_evidence(
                publish_safety_ready=publish_safety_ready,
                confirmation_count=int(counts.get("confirmations") or 0),
                red_items_block_publish=True,
            ),
            verification=["/stores/{store_id}/publish-confirmation", "/confirmations", "/confirmations/{id}/preflight"],
            confirmation_center_required=True,
        ),
        _new_account_smoke_step(
            "controlled_real_publish_probe",
            "Controlled real publish probe",
            _env_bool("JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"),
            owner="founder_operator",
            category="real_publish",
            next_action="After confirmation approval, execute one low-risk real publish, then record listing ID, offer ID, SKU, platform result and audit evidence.",
            evidence_summary=_compact_drill_evidence(
                real_publish_passed=_env_bool("JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"),
                platform_write_confirmation_gated=True,
            ),
            verification=["/confirmations/{id}/decision", "/confirmations/{id}/execute", "/execution-results"],
            confirmation_center_required=True,
            real_platform_write_step=True,
        ),
        _new_account_smoke_step(
            "post_publish_cockpit_cleanup_gate",
            "Post-publish cockpit and test cleanup gate",
            post_publish_ready and _env_bool("JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED"),
            owner="release_manager",
            category="post_publish",
            next_action="Run 1h/24h/7d cockpit checks and create a confirmation-gated cleanup plan for any live test listing; do not silently end or delete live eBay state.",
            evidence_summary=_compact_drill_evidence(
                post_publish_ready=post_publish_ready,
                cleanup_confirmed=_env_bool("JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED"),
                execution_results=int(counts.get("execution_results") or 0),
            ),
            verification=["post-publish cockpit", "/confirmations/{id}/publish-cleanup-plan", "/execution-results"],
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
) -> list[dict[str, Any]]:
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    checkout_contract = provider.get("checkout_portal_contract") if isinstance(provider.get("checkout_portal_contract"), dict) else {}
    provider_contract = provider.get("signed_webhook_contract") if isinstance(provider.get("signed_webhook_contract"), dict) else {}
    token_drill = drills.get("ebay_refresh_vault_probe") or {}
    return [
        _cutover_item(
            "billing_provider_live_contract",
            "Stripe subscription billing contract",
            (drills.get("stripe_billing_live_mode") or {}).get("status") == "ready",
            owner="platform_ops",
            category="billing",
            next_action="Select the external paid provider, publish live Price IDs, enable quota enforcement, and verify Checkout, Portal and signed webhook evidence before charging.",
            evidence_summary=_compact_drill_evidence(
                provider=provider.get("selected") or "not_selected",
                checkout_ready=bool((checkout_contract.get("checkout_sessions") or {}).get("ready")),
                portal_ready=bool((checkout_contract.get("customer_portal") or {}).get("ready")),
                webhook_ready=bool(provider_contract.get("webhook_configured")),
                quota_enabled=bool((billing.get("quota_contract") or {}).get("enabled")),
            ),
            environment_keys=[
                "JIEJING_BILLING_PROVIDER",
                "JIEJING_BILLING_PLANS_PUBLISHED",
                "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
                "JIEJING_STRIPE_PRICE_STARTER_ID",
                "JIEJING_STRIPE_PRICE_OPERATOR_ID",
                "JIEJING_STRIPE_PRICE_TEAM_ID",
                "JIEJING_BILLING_WEBHOOK_URL",
                "JIEJING_BILLING_SUCCESS_URL",
                "JIEJING_BILLING_CANCEL_URL",
                "JIEJING_BILLING_PORTAL_RETURN_URL",
            ],
            verification=[
                "/billing/plans",
                "/billing/checkout-contract",
                "tools/test_jiejing_stripe_checkout_portal.py",
                "tools/test_jiejing_billing_provider_webhook.py",
            ],
            external_resource_required=True,
            triggers_real_charge=False,
            confirmation_center_required=False,
        ),
        _cutover_item(
            "stripe_api_webhook_version_alignment",
            "Stripe API and webhook version alignment",
            checkout_contract.get("stripe_api_version") == STRIPE_CURRENT_API_VERSION and stripe_webhook_api_version_aligned(),
            owner="platform_ops",
            category="billing",
            next_action="Create or update the Stripe webhook endpoint with the same pinned API version and record verification; do not rely on dashboard defaults silently drifting.",
            evidence_summary=_compact_drill_evidence(
                request_api_version=checkout_contract.get("stripe_api_version") or "missing",
                expected_api_version=STRIPE_CURRENT_API_VERSION,
                recorded_webhook_api_version=stripe_webhook_api_version() or "missing",
                webhook_endpoint_version_verified=_env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"),
                webhook_endpoint_version_aligned=stripe_webhook_api_version() == STRIPE_CURRENT_API_VERSION,
            ),
            environment_keys=["JIEJING_STRIPE_WEBHOOK_API_VERSION", "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"],
            verification=["Stripe Workbench/webhook endpoint metadata", "tools/test_jiejing_stripe_checkout_portal.py"],
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
            token_drill.get("status") == "ready" and int((token_drill.get("evidence") or {}).get("successful_refresh_probe_count") or 0) > 0,
            owner="backend_secret_boundary",
            category="ebay",
            next_action="After a clean new eBay seller account is connected, run one backend-only refresh probe through Vault/KMS secret_ref and record audit evidence.",
            evidence_summary=_compact_drill_evidence(
                refresh_success=int(evidence.get("ebay_token_refresh_success_count") or 0),
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


def _build_billing_domain_cutover_runbook(
    *,
    cutover_checklist: list[dict[str, Any]],
    billing: dict[str, Any],
    domain: dict[str, Any],
) -> list[dict[str, Any]]:
    by_key = {str(item.get("key") or ""): item for item in cutover_checklist if isinstance(item, dict)}
    provider = billing.get("provider") if isinstance(billing.get("provider"), dict) else {}
    checkout_contract = provider.get("checkout_portal_contract") if isinstance(provider.get("checkout_portal_contract"), dict) else {}
    provider_contract = provider.get("signed_webhook_contract") if isinstance(provider.get("signed_webhook_contract"), dict) else {}
    checkout_sessions = checkout_contract.get("checkout_sessions") if isinstance(checkout_contract.get("checkout_sessions"), dict) else {}
    customer_portal = checkout_contract.get("customer_portal") if isinstance(checkout_contract.get("customer_portal"), dict) else {}
    quota = billing.get("quota_contract") if isinstance(billing.get("quota_contract"), dict) else {}
    stripe_docs = [
        "https://docs.stripe.com/get-started/checklist/go-live",
        "https://docs.stripe.com/billing/testing",
        "https://docs.stripe.com/api/versioning",
    ]
    resilience_env = [
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
    ]
    portal_env = [
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
    ]
    rollback_env = [
        "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_READINESS_SNAPSHOT_RECORDED",
        "JIEJING_BROWSER_SMOKE_PASSED",
    ]
    return [
        _runbook_step(
            "stripe_account_live_mode_contract",
            "Stripe account and live-mode contract",
            (by_key.get("billing_provider_live_contract") or {}).get("status") == "ready",
            owner="platform_ops",
            category="billing",
            next_action="Switch only after Stripe is the selected live provider, live Price IDs are present, Checkout/Portal are ready, signed webhook is configured, and quota enforcement is enabled.",
            evidence_summary=_compact_drill_evidence(
                provider=provider.get("selected") or "not_selected",
                api_key_configured=bool(provider_contract.get("api_key_configured")),
                plan_ids_present=provider_contract.get("plan_ids") or {},
                checkout_ready=bool(checkout_sessions.get("ready")),
                portal_ready=bool(customer_portal.get("ready")),
                return_url_overrides_locked=bool((checkout_contract.get("urls") or {}).get("request_override_must_match_configured_url")),
                quota_enabled=bool(quota.get("enabled")),
            ),
            environment_keys=[
                "JIEJING_BILLING_PROVIDER",
                "JIEJING_BILLING_PLANS_PUBLISHED",
                "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
                "JIEJING_STRIPE_PRICE_STARTER_ID",
                "JIEJING_STRIPE_PRICE_OPERATOR_ID",
                "JIEJING_STRIPE_PRICE_TEAM_ID",
            ],
            verification=["/billing/plans", "/billing/checkout-contract", "tools/test_jiejing_stripe_checkout_portal.py"],
            docs=[stripe_docs[0], stripe_docs[1]],
            external_resource_required=True,
        ),
        _runbook_step(
            "stripe_api_webhook_version_contract",
            "Stripe API and webhook version contract",
            (by_key.get("stripe_api_webhook_version_alignment") or {}).get("status") == "ready",
            owner="platform_ops",
            category="billing",
            next_action="Pin API requests and the production webhook endpoint to the same reviewed Stripe API version; record endpoint metadata before public charging.",
            evidence_summary=_compact_drill_evidence(
                request_api_version=checkout_contract.get("stripe_api_version") or "missing",
                expected_api_version=STRIPE_CURRENT_API_VERSION,
                recorded_webhook_api_version=stripe_webhook_api_version() or "missing",
                webhook_endpoint_version_verified=_env_bool("JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"),
                webhook_endpoint_version_aligned=stripe_webhook_api_version() == STRIPE_CURRENT_API_VERSION,
            ),
            environment_keys=["JIEJING_STRIPE_WEBHOOK_API_VERSION", "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED"],
            verification=["Stripe webhook endpoint metadata", "tools/test_jiejing_stripe_checkout_portal.py"],
            docs=[stripe_docs[0], stripe_docs[2]],
            external_resource_required=True,
        ),
        _runbook_step(
            "stripe_live_webhook_resilience",
            "Stripe live webhook resilience",
            bool(provider_contract.get("webhook_configured")) and all(_env_bool(name) for name in resilience_env),
            owner="platform_ops",
            category="billing",
            next_action="Test signed production webhook handling for duplicate, delayed, out-of-order and payment-failure events before accepting paid customers.",
            evidence_summary=_compact_drill_evidence(
                signed_webhook=bool(provider_contract.get("webhook_configured")),
                duplicate_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED"),
                delayed_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED"),
                out_of_order_tested=_env_bool("JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED"),
                payment_failure_tested=_env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED"),
            ),
            environment_keys=resilience_env,
            verification=["tools/test_jiejing_billing_provider_webhook.py", "tools/test_jiejing_billing_webhook_subscription_state.py"],
            docs=[stripe_docs[1]],
            external_resource_required=True,
        ),
        _runbook_step(
            "stripe_customer_portal_failure_paths",
            "Stripe Customer Portal and failure paths",
            bool(customer_portal.get("ready")) and all(_env_bool(name) for name in portal_env),
            owner="platform_ops",
            category="billing",
            next_action="Verify Portal self-service, cancellation, invoice paid provisioning and payment failure recovery without exposing payment secrets to the frontend.",
            evidence_summary=_compact_drill_evidence(
                portal_ready=bool(customer_portal.get("ready")),
                portal_tested=_env_bool("JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED"),
                cancel_tested=_env_bool("JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED"),
                invoice_paid_tested=_env_bool("JIEJING_STRIPE_INVOICE_PAID_TESTED"),
                payment_failure_tested=_env_bool("JIEJING_STRIPE_PAYMENT_FAILURE_TESTED"),
            ),
            environment_keys=portal_env,
            verification=["/billing/customer-portal", "tools/test_jiejing_stripe_checkout_portal.py", "tools/test_jiejing_billing_webhook_subscription_state.py"],
            docs=[stripe_docs[1]],
            external_resource_required=True,
        ),
        _runbook_step(
            "stable_domain_dns_tls_headers",
            "Stable domain DNS, TLS, and security headers",
            (by_key.get("stable_domain_dns_tls_callback") or {}).get("status") == "ready" and bool(domain.get("security_headers_verified")),
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
            next_action="Align the stable HTTPS origin, CORS allowlist and eBay callback URL; do not rerun eBay OAuth until the owner explicitly starts a clean new account test.",
            evidence_summary=_compact_drill_evidence(
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
                repeat_oauth_allowed=False,
            ),
            environment_keys=["JIEJING_CORS_ORIGIN", "JIEJING_EBAY_CALLBACK_VERIFIED"],
            verification=["/domain/status", "eBay developer callback configuration screenshot or audit note"],
            docs=[],
            external_resource_required=True,
            repeat_oauth_allowed=False,
            triggers_ebay_oauth=False,
        ),
        _runbook_step(
            "cutover_rollback_audit_packet",
            "Cutover rollback and audit packet",
            (by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") == "ready" and all(_env_bool(name) for name in rollback_env),
            owner="release_manager",
            category="release",
            next_action="Record rollback plan, secret scan, readiness snapshots and browser smoke evidence before owner approval for paid public launch.",
            evidence_summary=_compact_drill_evidence(
                final_smoke=(by_key.get("final_paid_launch_smoke_evidence") or {}).get("status") or "missing",
                rollback_verified=_env_bool("JIEJING_CUTOVER_ROLLBACK_VERIFIED"),
                secret_scan=_env_bool("JIEJING_SECRET_SCAN_PASSED"),
                readiness_snapshot=_env_bool("JIEJING_READINESS_SNAPSHOT_RECORDED"),
                browser_smoke=_env_bool("JIEJING_BROWSER_SMOKE_PASSED"),
            ),
            environment_keys=rollback_env,
            verification=["tools/jiejing_secret_scan.py", "/health", "/health/deep", "/readiness/product-saas", "output/browser-smoke"],
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
    runbook = _build_billing_domain_cutover_runbook(cutover_checklist=cutover_checklist, billing=billing, domain=domain)
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
        "public_paid_launch_allowed": ready_for_owner_approval,
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
        "billing_live_contract_ready": (by_key.get("billing_provider_live_contract") or {}).get("status") == "ready",
        "stable_domain_ready": (by_key.get("stable_domain_dns_tls_callback") or {}).get("status") == "ready",
        "stripe_webhook_version_verified": (by_key.get("stripe_api_webhook_version_alignment") or {}).get("status") == "ready",
        "ebay_refresh_proof_ready": (by_key.get("ebay_refresh_probe_after_new_account") or {}).get("status") == "ready",
        "rollback_plan": [
            "keep_current_staging_url_available_until_stable_domain_smoke_passes",
            "do_not_enable_public_checkout_until_billing_domain_legal_and_final_smoke_are_ready",
            "disable_quota_enforcement_or_billing_provider_flags_if_checkout_or_webhook_smoke_fails",
            "keep_real_ebay_writes_confirmation_gated_after_cutover",
        ],
        "evidence_to_record": [
            "domain_status_json",
            "billing_checkout_contract_json",
            "signed_webhook_contract_json",
            "stripe_webhook_endpoint_api_version",
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
        "billing_quota": "正式收费系统",
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
        "billing_quota": "接正式 Stripe/Paddle/Lemon Squeezy provider，发布真实 plan、quota、签名 webhook、欠费停用和发票/用量账单。",
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
        provider = (billing.get("provider") or {}).get("selected") or "not_selected"
        blockers = billing.get("paid_launch_blockers") or []
        return f"provider={provider}; paid_blockers={len(blockers)}"
    if key == "stable_domain_tls":
        blockers = domain.get("blockers") or []
        return f"domain={domain.get('stable_domain') or 'not_selected'}; blockers={len(blockers)}"
    if key == "ebay_token_refresh_vault_adapter":
        return (
            f"readiness={readiness_item.get('status') or 'missing'}; "
            f"secret_refs_present={bool(evidence.get('ebay_secret_refs'))}; "
            f"refresh_probe_success={int(evidence.get('ebay_token_refresh_success_count') or 0)}"
        )
    if key == "account_health_incident_mode":
        return f"readiness={readiness_item.get('status') or 'missing'}; packet={evidence.get('latest_ebay_packet_id') or 'missing'}"
    if key == "new_ebay_account_low_risk_smoke":
        return "old_frozen_account_reuse_allowed=false"
    if key == "publish_safety_system":
        return f"confirmations={int(counts.get('confirmations') or 0)}; official_packet={_official_packet_ready(evidence)}"
    if key == "store_sync_visibility":
        return f"packet={evidence.get('latest_ebay_packet_id') or 'missing'}; stores={int(counts.get('stores') or 0)}"
    if key == "post_publish_cockpit":
        return f"execution_results={int(counts.get('execution_results') or 0)}"
    if key == "legal_risk_boundary":
        return "privacy/terms/risk/confirmation flags required"
    if key == "final_commercial_smoke":
        return f"passed={_env_bool('JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED')}"
    return str(group.get("status") or readiness_item.get("status") or "waiting")


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
