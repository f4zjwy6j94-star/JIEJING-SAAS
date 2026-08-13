"""Product-grade readiness checks for Jiejing SaaS."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from jiejing_runtime.ebay_provider_status import EbayProviderStatus
from jiejing_runtime.media_generation import MediaGenerationAdapter
from jiejing_runtime.model_clients import model_client_status_from_env
from jiejing_runtime.public_search import PublicSearchProbeAdapter
from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog

from .backup_plan import build_backup_plan
from .billing_plan import build_billing_plan
from .billing_payment_options import validate_mainland_payment_launch_for_public
from .config import SaaSSettings
from .controlled_bridges import build_controlled_bridge_contract
from .database_adapter import build_database_adapter_contract
from .database_plan import build_database_plan
from .ebay_live_read_adapter import build_live_read_adapter_status
from .ebay_token_refresh_adapter import build_ebay_token_refresh_adapter_status
from .infrastructure_drivers import build_infrastructure_driver_status
from .model_value_gate import build_model_value_gate
from .monitoring import build_monitoring_status
from .operational_health import build_operational_health
from .platform_registry import registry_summary
from .platform_model_status import build_platform_default_model_status
from .queue_adapter import build_queue_adapter_contract
from .queue_plan import build_queue_plan
from .repository import SaaSRepository
from .vault_adapter import build_vault_adapter_contract


_PRIVATE_BETA_PAID_LAUNCH_ONLY_BLOCKERS = frozenset(
    {
        "merchant_payment_provider_connection_not_ready",
        "merchant_payment_production_environment_required",
        "merchant_payment_refund_not_ready",
        "merchant_payment_controlled_acceptance_not_proven",
        "merchant_payment_public_cutover_not_approved",
    }
)


@dataclass(slots=True)
class ReadinessItem:
    key: str
    label: str
    status: str
    severity: str
    detail: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "severity": self.severity,
            "detail": self.detail,
            "next_action": self.next_action,
        }


def validate_paid_owner_product_readiness(
    raw_readiness: Any,
    *,
    mainland_payment_ready_for_owner_approval: bool,
) -> dict[str, Any]:
    """Accept only the final-ready state or the exact public-charge hold state."""

    readiness = raw_readiness if isinstance(raw_readiness, dict) else {}
    booleans_valid = isinstance(raw_readiness, dict) and all(
        type(readiness.get(key)) is bool
        for key in ("production_ready", "beta_ready", "can_accept_real_customers")
    )
    counts_valid = all(
        type(readiness.get(key)) is int and readiness.get(key) >= 0
        for key in ("blocker_count", "warning_count")
    )
    raw_items = readiness.get("items")
    items_valid = isinstance(raw_items, list) and all(
        isinstance(item, dict)
        and all(
            isinstance(item.get(key), str) and bool(item.get(key).strip())
            for key in ("key", "label", "status", "severity", "detail", "next_action")
        )
        and item.get("severity") in {"info", "warning", "blocker"}
        for item in (raw_items if isinstance(raw_items, list) else [])
    )
    items = raw_items if items_valid and isinstance(raw_items, list) else []
    blockers = [
        item
        for item in items
        if item.get("severity") == "blocker" and item.get("status") != "ready"
    ]
    warnings = [
        item
        for item in items
        if item.get("severity") == "warning" and item.get("status") != "ready"
    ]
    counts_match = bool(
        counts_valid
        and readiness.get("blocker_count") == len(blockers)
        and readiness.get("warning_count") == len(warnings)
    )
    canonical_owner_ready = mainland_payment_ready_for_owner_approval is True
    final_ready = bool(
        booleans_valid
        and items_valid
        and counts_match
        and readiness.get("production_ready") is True
        and readiness.get("beta_ready") is True
        and readiness.get("can_accept_real_customers") is True
        and readiness.get("reason") == "ready"
        and not blockers
        and not warnings
    )
    exact_public_charge_hold = bool(
        booleans_valid
        and items_valid
        and counts_match
        and readiness.get("production_ready") is False
        and readiness.get("beta_ready") is True
        and readiness.get("can_accept_real_customers") is False
        and readiness.get("reason") == "expected_public_charge_approval_hold"
        and not blockers
        and len(warnings) == 1
        and warnings[0].get("key") == "billing_quota"
        and warnings[0].get("status") == "mainland_payment_ready_for_owner_approval"
        and warnings[0].get("severity") == "warning"
    )
    contract_valid = bool(booleans_valid and counts_valid and items_valid and counts_match)
    ready = bool(contract_valid and canonical_owner_ready and (final_ready or exact_public_charge_hold))
    if ready:
        blockers_codes: list[str] = []
    elif not contract_valid:
        blockers_codes = ["readiness_contract_invalid"]
    elif not canonical_owner_ready:
        blockers_codes = ["mainland_payment_not_ready_for_owner_approval"]
    else:
        blockers_codes = ["product_readiness_state_not_approved"]
    return {
        "contract_valid": contract_valid,
        "counts_match": counts_match,
        "canonical_mainland_payment_owner_ready": canonical_owner_ready,
        "final_ready": final_ready,
        "expected_public_charge_approval_hold": exact_public_charge_hold,
        "ready_for_owner_approval": ready,
        "state": (
            "final_ready"
            if ready and final_ready
            else "expected_public_charge_approval_hold"
            if ready and exact_public_charge_hold
            else "blocked"
        ),
        "blockers": blockers_codes,
    }


def build_product_readiness(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    evidence = repository.product_readiness_evidence()
    operational_health = build_operational_health(settings, repository)
    ebay = EbayProviderStatus().to_dict()
    model_status = model_client_status_from_env()
    platform_model_status = build_platform_default_model_status()
    items = [
        _environment_item(settings),
        _session_secret_item(settings),
        _cors_item(settings),
        _team_permission_item(counts),
        _database_item(settings),
        _database_adapter_item(settings),
        _database_migration_item(settings, repository),
        _queue_item(settings),
        _queue_adapter_item(settings),
        _queue_worker_plan_item(settings, repository),
        *_operational_health_items(operational_health),
        _infrastructure_driver_item(settings),
        _monitoring_item(settings, repository),
        _backup_item(settings, repository),
        _billing_item(settings, repository),
        _provider_job_runner_item(),
        _independent_runtime_item(settings),
        _controlled_bridge_item(settings, repository),
        _vault_item(settings),
        _vault_adapter_item(settings),
        _runtime_item(settings),
        _model_item(model_status, platform_model_status, evidence),
        _model_value_item(settings, repository),
        _platform_registry_item(),
        _ebay_account_deletion_item(settings, evidence),
        _ebay_oauth_item(settings, evidence),
        _ebay_token_refresh_item(settings, evidence),
        _ebay_read_adapter_item(settings, evidence),
        _ebay_live_read_adapter_item(settings),
        _data_packet_cache_item(counts, evidence),
        _real_saas_loop_item(evidence),
        _ebay_read_item(ebay, evidence),
        _account_health_incident_item(evidence),
        _ebay_policy_item(ebay, evidence),
        _execution_item(settings, evidence),
        _tenant_audit_item(counts),
    ]
    critical_blockers = [item for item in items if item.severity == "blocker" and item.status != "ready"]
    warnings = [item for item in items if item.severity == "warning" and item.status != "ready"]
    production_ready = not critical_blockers and not warnings and settings.is_production_like
    beta_ready = not critical_blockers and counts.get("users", 0) >= 1 and counts.get("stores", 0) >= 1
    expected_public_charge_approval_hold = bool(
        settings.is_production_like
        and beta_ready
        and not critical_blockers
        and len(warnings) == 1
        and warnings[0].key == "billing_quota"
        and warnings[0].status == "mainland_payment_ready_for_owner_approval"
        and warnings[0].severity == "warning"
    )
    return {
        "service": "jiejing-saas-backend",
        "readiness_version": "2026-05-15-product-saas",
        "environment": settings.environment,
        "production_ready": production_ready,
        "beta_ready": beta_ready,
        "can_accept_real_customers": False if not production_ready else True,
        "reason": (
            "ready"
            if production_ready
            else "expected_public_charge_approval_hold"
            if expected_public_charge_approval_hold
            else "readiness_blocked"
        ),
        "real_platform_writes_enabled": settings.effective_real_platform_writes_enabled,
        "ebay_draft_save_enabled": settings.effective_ebay_draft_save_enabled,
        "requested_real_platform_writes": settings.requested_real_platform_writes,
        "blocker_count": len(critical_blockers),
        "warning_count": len(warnings),
        "items": [item.to_dict() for item in items],
        "counts": counts,
        "product_evidence": evidence,
        "provider_status": {
            "model": _public_model_status(model_status, platform_model_status, evidence),
            "ebay": _public_ebay_status(ebay),
            "platform_registry": _public_platform_registry_status(),
            "provider_jobs": _public_provider_job_status(),
            "controlled_bridges": _public_controlled_bridge_status(settings, repository),
            "backup": _public_backup_status(settings, repository),
            "billing": _public_billing_status(settings, repository),
            "model_value": _public_model_value_status(settings, repository),
            "ai_ceo_platform_model": _ai_ceo_platform_model_status(platform_model_status),
            "public_search": _public_search_status(),
            "media_generation": _public_media_generation_status(),
            "operational_health": _public_operational_health_status(operational_health),
        },
        "operational_health": operational_health,
        "next_minimum_actions": _next_minimum_actions(items),
        "secret_exposed": False,
    }


def build_product_readiness_or_degraded(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    try:
        return build_product_readiness(settings, repository)
    except Exception as exc:
        return build_degraded_product_readiness(settings=settings, exc=exc)


def build_degraded_product_readiness(*, settings: SaaSSettings, exc: Exception) -> dict[str, Any]:
    error_type = type(exc).__name__ or "ReadinessError"
    database_item = ReadinessItem(
        "database_reachability",
        "Database reachability",
        "degraded_database_unavailable",
        "blocker",
        "Readiness could not query the SaaS database within the request boundary.",
        "Check managed Postgres connectivity, security group rules, connection timeout, and current database load; do not retry eBay writes while readiness is degraded.",
    )
    environment_item = _environment_item(settings)
    items = [environment_item, database_item]
    return {
        "service": "jiejing-saas-backend",
        "readiness_version": "2026-05-24-product-saas-degraded",
        "environment": settings.environment,
        "status": "degraded",
        "degraded": True,
        "degraded_reason": "database_unavailable",
        "database_error_type": error_type,
        "production_ready": False,
        "beta_ready": False,
        "can_accept_real_customers": False,
        "real_platform_writes_enabled": settings.effective_real_platform_writes_enabled,
        "requested_real_platform_writes": settings.requested_real_platform_writes,
        "blocker_count": 1,
        "warning_count": 0 if environment_item.status == "ready" else 1,
        "items": [item.to_dict() for item in items],
        "counts": {},
        "product_evidence": {
            "read_only_authorized_connections": 0,
            "ebay_secret_refs": 0,
            "latest_ebay_packet_id": "",
            "latest_ebay_packet_status": "",
            "latest_ebay_packet_source_mode": "",
            "latest_ebay_packet_created_at": "",
            "latest_ebay_packet_present_resource_keys": [],
            "latest_ebay_packet_missing_resource_keys": [],
            "model_secret_refs": 0,
            "report_count": 0,
            "confirmation_count": 0,
            "secret_exposed": False,
        },
        "provider_status": {
            "model": {"configured": False, "status": "unknown_readiness_degraded"},
            "ebay": {"status": "unknown_readiness_degraded"},
            "platform_registry": _public_platform_registry_status(),
            "provider_jobs": _public_provider_job_status(),
            "backup": {"ready": False, "status": "unknown_readiness_degraded"},
            "billing": {"ready": False, "status": "unknown_readiness_degraded"},
            "model_value": {"ready": False, "status": "unknown_readiness_degraded"},
            "ai_ceo_platform_model": _ai_ceo_platform_model_status(),
            "public_search": _public_search_status(),
            "media_generation": _public_media_generation_status(),
        },
        "next_minimum_actions": [database_item.next_action],
        "secret_exposed": False,
    }


def _platform_registry_item() -> ReadinessItem:
    summary = registry_summary()
    if summary.get("platform_count", 0) < 2:
        return ReadinessItem(
            "platform_registry",
            "Platform connector registry",
            "missing_reserved_platforms",
            "warning",
            "The backend still looks single-platform; future connectors need a shared contract.",
            "Add reserved connector definitions before implementing live adapters.",
        )
    return ReadinessItem(
        "platform_registry",
        "Platform connector registry",
        "reserved_contract_ready",
        "info",
        "The backend exposes eBay-first plus reserved domestic and international connector contracts without live calls.",
        "Next implement live adapters one by one behind Vault, queue, audit, and confirmation center.",
    )


def _provider_job_runner_item() -> ReadinessItem:
    catalog = build_provider_job_contract_catalog()
    keys = {item.get("key") for item in catalog.get("contracts", [])}
    required = {
        "public_search.market_research",
        "ebay.read_only_snapshot",
        "sourcing.1688_availability",
        "logistics.orange_connex_quote",
        "media.asset_generation",
        "model.role_report_assist",
    }
    if not required.issubset(keys):
        return ReadinessItem(
            "provider_job_runner",
            "Provider job runner",
            "blocked_missing_provider_jobs",
            "blocker",
            "The SaaS backend lacks a complete provider job contract set for search, eBay, sourcing, logistics, media and model calls.",
            "Define all provider job contracts before wiring live tools into merchant workflows.",
        )
    return ReadinessItem(
        "provider_job_runner",
        "Provider job runner",
        "dry_run_contract_ready",
        "info",
        "Provider jobs now have queue contracts and a local dry-run worker boundary; failures and missing inputs become merchant-visible task output.",
        "Next replace each dry-run provider with a production adapter behind Vault/KMS, quota checks, retry policy and audit logs.",
    )


def _controlled_bridge_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    contract = build_controlled_bridge_contract(settings, repository)
    blockers = contract.get("production_blockers") if isinstance(contract.get("production_blockers"), list) else []
    if settings.allow_hermes_adapters:
        return ReadinessItem(
            "controlled_bridges",
            "Controlled bridge contract",
            "blocked_hermes_legacy_bridge_enabled",
            "blocker",
            "Hermes legacy bridge is enabled. Formal SaaS launch cannot depend on Hermes as a runtime or credential bridge.",
            "Disable JIEJING_ALLOW_HERMES_ADAPTERS and keep formal work on RuntimeBridge, ProviderAdapter, QueueWorkerBridge, ConfirmationExecutionBridge and AuditMemoryBridge.",
        )
    if settings.is_production_like and blockers:
        return ReadinessItem(
            "controlled_bridges",
            "Controlled bridge contract",
            "configured_bridge_contract_with_blockers",
            "blocker",
            "Formal bridge seams are visible, but at least one production bridge still has a launch blocker.",
            "Clear bridge blockers before paid launch: " + ", ".join(str(item) for item in blockers),
        )
    return ReadinessItem(
        "controlled_bridges",
        "Controlled bridge contract",
        "ready",
        "info",
        "Formal bridges are fixed as RuntimeBridge, ProviderAdapter, QueueWorkerBridge, ConfirmationExecutionBridge and AuditMemoryBridge; Hermes legacy bridge is transitional only.",
        "Keep this contract in readiness so future adapters cannot bypass backend secrets, durable queue, confirmation center, audit or memory boundaries.",
    )


def _backup_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    plan = build_backup_plan(settings, repository)
    if plan.get("backup_ready_for_paid_launch"):
        return ReadinessItem(
            "backup_restore",
            "Backup and restore",
            "ready",
            "info",
            "Managed database backup policy, restore drill evidence and backup alerts are configured.",
            "Keep restore drills scheduled and alert recovery owners before paid launch.",
        )
    blockers = {str(item) for item in (plan.get("blockers") or []) if str(item)}
    freshness_only_blockers = {"cos_backup_probe_stale", "restore_drill_overdue"}
    if settings.environment == "staging" and blockers and blockers.issubset(freshness_only_blockers):
        return ReadinessItem(
            "backup_restore",
            "Backup and restore",
            "paid_launch_backup_evidence_stale",
            "warning",
            "Managed backup controls remain configured, but the latest backup and restore evidence is outside the paid-launch freshness windows.",
            "Record a recent successful backup probe and run a new restore drill before paid launch.",
        )
    return ReadinessItem(
        "backup_restore",
        "Backup and restore",
        "blocked_backup_restore_not_ready" if settings.is_production_like else "contract_ready_external_policy_pending",
        "blocker" if settings.is_production_like else "warning",
        "The backend exposes the backup/restore contract, but managed backups, restore drills or alerts are not fully proven.",
        "Configure managed Postgres backup/PITR, run a restore drill, and wire backup failure alerts before paid launch.",
    )


def _billing_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    plan = build_billing_plan(settings, repository)
    mainland = plan.get("mainland_payment_launch") if isinstance(plan.get("mainland_payment_launch"), dict) else {}
    payment = _validated_public_mainland_payment(mainland)
    configured_count = payment["configured_component_count"]
    required_count = payment["required_component_count"]
    private_beta_ready = plan.get("billing_ready_for_private_beta") is True
    if payment["mainland_payment_ready_for_owner_approval"] is True:
        return ReadinessItem(
            "billing_quota",
            "Billing and quota",
            (
                "mainland_payment_ready_for_owner_approval"
                if private_beta_ready
                else "blocked_private_beta_billing_not_ready"
            ),
            "warning" if private_beta_ready else "blocker",
            "WeChat Pay Native configuration, signed callbacks, authenticated order query and controlled acceptance evidence are ready; public charging remains closed.",
            (
                "Complete the separate owner commercial-release review before approving public payment cutover."
                if private_beta_ready
                else "Restore the strict private-beta billing contract before inviting merchants or reviewing public payment cutover."
            ),
        )
    if payment["next_paid_launch_blocker"] == "merchant_payment_status_unavailable":
        return ReadinessItem(
            "billing_quota",
            "Billing and quota",
            "blocked_mainland_payment_status_unavailable",
            "blocker" if settings.is_production_like else "warning",
            "The public mainland payment status is unavailable or malformed; public charging remains closed.",
            "Restore the canonical backend payment status before any payment cutover review.",
        )
    if payment["next_paid_launch_blocker"] == "merchant_payment_provider_configuration_incomplete":
        return ReadinessItem(
            "billing_quota",
            "Billing and quota",
            "blocked_mainland_payment_not_ready" if settings.is_production_like else "mainland_payment_configuration_in_progress",
            "blocker" if settings.is_production_like else "warning",
            f"WeChat Pay Native has {configured_count}/{required_count} required backend components configured; public charging remains closed.",
            "Complete the current backend payment configuration before relying on historical acceptance evidence.",
        )
    paid_launch_only_gap = payment["next_paid_launch_blocker"] in _PRIVATE_BETA_PAID_LAUNCH_ONLY_BLOCKERS
    if private_beta_ready and paid_launch_only_gap:
        return ReadinessItem(
            "billing_quota",
            "Billing and quota",
            "private_beta_ready_paid_launch_pending",
            "warning",
            f"Free invited-beta billing controls are ready; WeChat Pay Native has {configured_count}/{required_count} required backend components configured, while public charging remains closed.",
            "Complete the next controlled mainland payment gate before the separate public paid-launch approval.",
        )
    return ReadinessItem(
        "billing_quota",
        "Billing and quota",
        "mainland_payment_provider_configured",
        "blocker" if settings.is_production_like else "warning",
        f"WeChat Pay Native has {configured_count}/{required_count} required backend components configured; public charging remains closed.",
        "Complete the next controlled mainland payment gate before public cutover.",
    )


def _model_value_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    gate = build_model_value_gate(settings, repository)
    if gate.get("ready_for_paid_value_claim"):
        return ReadinessItem(
            "model_value_proof",
            "Model-backed Agent value",
            "ready",
            "info",
            "Market Report and Listing Package have live-model evidence over sanitized data packets.",
            "Continue quality review and cost controls for model-backed reports.",
        )
    return ReadinessItem(
        "model_value_proof",
        "Model-backed Agent value",
        "blocked_live_model_value_not_proven" if settings.is_production_like else "contract_ready_value_pending",
        "blocker" if settings.is_production_like else "warning",
        "Owned Agents have contracts, but paid SaaS value still needs live model-backed Market Report and Listing Package evidence.",
        "Run controlled live model reports over sanitized official eBay packets and review quality before paid launch.",
    )


def _infrastructure_driver_item(settings: SaaSSettings) -> ReadinessItem:
    status = build_infrastructure_driver_status(settings)
    blockers = status.get("cutover_blockers") if isinstance(status.get("cutover_blockers"), list) else []
    if status.get("ready_for_runtime_cutover"):
        return ReadinessItem(
            "infrastructure_drivers",
            "Postgres/Redis drivers",
            "ready",
            "info",
            "Postgres repository runtime and Redis Streams worker runtime have dependencies, live probes, and redacted connection configuration in place.",
            "Continue monitoring live database and queue probes before increasing merchant traffic.",
        )
    if settings.is_production_like and blockers:
        return ReadinessItem(
            "infrastructure_drivers",
            "Postgres/Redis drivers",
            "configured_cutover_blocked",
            "blocker",
            "Postgres/Redis driver status is visible, but the SaaS repository and distributed worker runtime are not cut over yet.",
            "Install driver dependencies, run live probes, migrate data, then switch the repository and worker call sites behind tests.",
        )
    return ReadinessItem(
        "infrastructure_drivers",
        "Postgres/Redis drivers",
        "driver_status_visible",
        "warning",
        "The backend exposes Postgres/Redis driver status and migration runner shape without claiming runtime cutover.",
        "Use /infrastructure/drivers during staging infra rehearsal and keep current SQLite/local-worker runtime until cutover tests pass.",
    )


def _monitoring_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    if settings.is_production_like:
        monitoring = build_monitoring_status(settings, repository)
        if monitoring.get("production_monitoring_ready") is True:
            return ReadinessItem(
                "monitoring_alerting",
                "Monitoring and alerting",
                "cloud_monitoring_ready",
                "info",
                "Production-like environments enable safe access logs and point the monitoring contract at Tencent CLS without request bodies or raw tokens.",
                "Continue checking the passive provider monitor, OAuth/Vault/eBay sync and backup alerts before increasing merchant traffic.",
            )
        return ReadinessItem(
            "monitoring_alerting",
            "Monitoring and alerting",
            "blocked_provider_monitoring_evidence",
            "warning",
            "Production monitoring evidence is incomplete. Public readiness intentionally withholds internal provider diagnostics.",
            "Complete the internal passive monitoring, cloud alert verification and incident-response evidence before paid launch.",
        )
    return ReadinessItem(
        "monitoring_alerting",
        "Monitoring and alerting",
        "contract_ready_external_tools_pending",
        "warning",
        "The backend exposes monitoring status and safe-log rules, but external error capture, cloud metrics and backup alerts are not configured in local/staging.",
        "Before paid launch, configure Sentry-style error capture, queue-depth metrics, OAuth/Vault/eBay sync alerts and backup restore alerts.",
    )


def _cls_env_ready() -> bool:
    return (
        str(os.environ.get("JIEJING_CLS_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
        and bool(os.environ.get("JIEJING_CLS_REGION") or os.environ.get("JIEJING_TENCENT_REGION"))
        and bool(os.environ.get("JIEJING_CLS_LOGSET_ID") or os.environ.get("JIEJING_CLS_LOGSET"))
        and bool(os.environ.get("JIEJING_CLS_TOPIC_ID") or os.environ.get("JIEJING_CLS_TOPIC"))
        and str(os.environ.get("JIEJING_CLS_ALERT_POLICY_CONFIGURED") or "").strip().lower() in {"1", "true", "yes", "on"}
    )


def _independent_runtime_item(settings: SaaSSettings) -> ReadinessItem:
    if settings.allow_hermes_adapters:
        return ReadinessItem(
            "independent_runtime",
            "Jiejing independent Runtime",
            "blocked_hermes_adapter_allowed",
            "blocker",
            "Hermes adapters are enabled. This violates the current independent SaaS target.",
            "Keep JIEJING_ALLOW_HERMES_ADAPTERS unset/false and route SaaS work through jiejing-local, jiejing-llm, or jiejing-deepseek.",
        )
    return ReadinessItem(
        "independent_runtime",
        "Jiejing independent Runtime",
        "ready",
        "info",
        "The SaaS backend defaults to Jiejing-owned Runtime adapters and does not require Hermes for workflow execution.",
        "Continue replacing dry-run provider jobs with production adapters behind Vault/KMS and confirmation center.",
    )


def _team_permission_item(counts: dict[str, int]) -> ReadinessItem:
    if counts.get("team_members", 0) < counts.get("companies", 0):
        return ReadinessItem(
            "team_permission_boundary",
            "Team and permission boundary",
            "blocked_missing_company_owner",
            "blocker",
            "At least one company has no team member owner boundary.",
            "Ensure every company is created with an owner team member before accepting merchant data.",
        )
    return ReadinessItem(
        "team_permission_boundary",
        "Team and permission boundary",
        "role_boundary_ready",
        "info",
        "Companies now have team-member role records; owner/admin/operator/viewer permissions can gate stores, tasks, confirmations and audits.",
        "Next wire this boundary into every sensitive endpoint and future paid-team management UI.",
    )


def _database_adapter_item(settings: SaaSSettings) -> ReadinessItem:
    contract = build_database_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.is_production_like and contract.get("production_blockers"):
        return ReadinessItem(
            "database_adapter_contract",
            "Database adapter contract",
            "blocked_adapter_not_production_ready",
            "blocker",
            f"Selected database adapter {selected.get('key')} is not production-ready.",
            "Select a managed Postgres/MySQL adapter, configure the database URL through Vault/KMS, and run migrations.",
        )
    if settings.is_production_like and selected.get("production_allowed") and contract.get("database_url_configured"):
        return ReadinessItem(
            "database_adapter_contract",
            "Database adapter contract",
            "managed_adapter_live",
            "info",
            f"Selected database adapter {selected.get('key')} is configured for the current staging/production-like environment.",
            "Keep migration, backup, restore drill and slow-query monitoring on the launch checklist; do not report this as a missing managed database adapter.",
        )
    return ReadinessItem(
        "database_adapter_contract",
        "Database adapter contract",
        "adapter_contract_ready",
        "info",
        "The backend now exposes a replaceable database adapter contract instead of treating SQLite as the final production database.",
        "Implement the managed Postgres adapter and apply the prepared migration before staging.",
    )


def _database_migration_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    plan = build_database_plan(settings, repository)
    missing_tables = plan.get("critical_tables", {}).get("missing", [])
    missing_indexes = plan.get("critical_indexes", {}).get("missing", [])
    if missing_tables or missing_indexes or not plan.get("migrations"):
        return ReadinessItem(
            "database_migration_plan",
            "Database migration and index plan",
            "blocked_missing_database_governance",
            "blocker",
            "The backend schema is missing migration records, critical tables, or indexes required before real merchant data.",
            "Repair schema migrations and critical tenant/task/report/confirmation indexes before staging.",
        )
    return ReadinessItem(
        "database_migration_plan",
        "Database migration and index plan",
        "migration_shape_ready",
        "info",
        "The local schema now has a migration record and critical indexes for stores, secrets, connections, tasks, queue jobs, reports, confirmations and audit logs.",
        "Next replace SQLite with managed Postgres/MySQL and run the same migration contract there.",
    )


def _queue_adapter_item(settings: SaaSSettings) -> ReadinessItem:
    contract = build_queue_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.is_production_like and contract.get("production_blockers"):
        return ReadinessItem(
            "queue_adapter_contract",
            "Queue adapter contract",
            "blocked_queue_adapter_not_production_ready",
            "blocker",
            f"Selected queue adapter {selected.get('key')} is not production-ready.",
            "Select Redis or a managed cloud queue, configure the queue URL through Vault/KMS, and enable worker heartbeat and dead-letter handling.",
        )
    if settings.is_production_like and selected.get("production_allowed") and (
        contract.get("queue_url_configured") or selected.get("key") == "postgres_durable"
    ):
        return ReadinessItem(
            "queue_adapter_contract",
            "Queue adapter contract",
            "managed_queue_live",
            "info",
            f"Selected queue adapter {selected.get('key')} is configured with distributed worker, heartbeat and dead-letter support.",
            "Keep worker lag, failed-job replay and idempotency checks on the launch checklist; do not report this as a missing Redis/cloud queue adapter.",
        )
    return ReadinessItem(
        "queue_adapter_contract",
        "Queue adapter contract",
        "adapter_contract_ready",
        "info",
        "The backend now exposes a replaceable queue adapter contract instead of binding product workflows permanently to the local worker.",
        "Implement Redis/cloud queue workers before inviting real merchants.",
    )


def _queue_worker_plan_item(settings: SaaSSettings, repository: SaaSRepository) -> ReadinessItem:
    plan = build_queue_plan(settings, repository)
    contract = build_queue_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.queue_provider not in {"local_inline", "local_worker", "postgres_durable"} and not selected.get("driver_implemented"):
        return ReadinessItem(
            "queue_worker_plan",
            "Queue worker lifecycle plan",
            "cloud_queue_driver_pending",
            "blocker",
            "A cloud/distributed queue provider is selected, but the worker still uses the local database queue implementation.",
            "Implement queue publish/claim/ack, heartbeat, dead-letter and timeout reaper before switching real merchant jobs to this provider.",
        )
    if not plan.get("worker_lifecycle_shape_ready"):
        return ReadinessItem(
            "queue_worker_plan",
            "Queue worker lifecycle plan",
            "blocked_missing_local_worker_shape",
            "blocker",
            "The backend cannot yet separate request acceptance from Runtime execution.",
            "Keep product workflows queued first, then let workers claim and report status.",
        )
    if plan.get("production_blockers"):
        return ReadinessItem(
            "queue_worker_plan",
            "Queue worker lifecycle plan",
            "local_worker_shape_ready",
            "info",
            "The local worker shape supports queued jobs, retry, cancellation, timeline and merchant-visible failures, but still needs a cloud queue for production.",
            "Replace local worker with Redis/cloud queue, dead-letter queue, heartbeat and timeout reaper before real merchants.",
        )
    return ReadinessItem(
        "queue_worker_plan",
        "Queue worker lifecycle plan",
        "ready",
        "info",
        "Queue provider and worker lifecycle are production-shaped with asynchronous dispatch, retry visibility, dead-letter and heartbeat support.",
        "Continue monitoring queue depth, stuck jobs, dead-letter jobs and retry rates.",
    )


def _operational_health_items(health: dict[str, Any]) -> list[ReadinessItem]:
    database = health.get("database_live_probe") if isinstance(health.get("database_live_probe"), dict) else {}
    queue = health.get("queue_runtime") if isinstance(health.get("queue_runtime"), dict) else {}
    worker = health.get("worker_runtime") if isinstance(health.get("worker_runtime"), dict) else {}
    queue_counts = queue.get("counts") if isinstance(queue.get("counts"), dict) else {}

    database_ready = database.get("status") == "ready"
    stale_count = int(queue.get("stale_running_count") or 0)
    dead_letter_count = int(queue_counts.get("dead_letter") or 0)
    worker_attention = worker.get("status") != "ready"

    return [
        ReadinessItem(
            "database_live_probe",
            "数据库 live probe",
            "ready" if database_ready else "blocked_database_live_probe",
            "info" if database_ready else "blocker",
            "数据库实时探针通过；Postgres 环境执行 select 1，SQLite/本地环境执行仓库计数查询。"
            if database_ready
            else "数据库实时探针失败，不能继续真实写入或收费上线验证。",
            "继续把 DB 探针接入监控告警。"
            if database_ready
            else "检查 TencentDB/Postgres endpoint、端口、安全组、账号权限和连接池；恢复前暂停真实写入。",
        ),
        ReadinessItem(
            "queue_runtime_health",
            "队列运行健康",
            "ready" if not stale_count and not dead_letter_count else "attention_queue_runtime",
            "info" if not stale_count and not dead_letter_count else "warning",
            f"队列可见：queued={int(queue_counts.get('queued') or 0)} running={int(queue_counts.get('running') or 0)} failed={int(queue_counts.get('failed') or 0)} dead_letter={dead_letter_count} stale_running={stale_count}。",
            "持续监控 queue depth、stale running、dead letter 和 retry 成功率。"
            if not stale_count and not dead_letter_count
            else "先恢复 stale running job，处理 dead-letter 失败原因，再允许新真实执行批次。",
        ),
        ReadinessItem(
            "worker_runtime_health",
            "Worker 运行指标",
            "ready" if not worker_attention else "attention_worker_runtime",
            "info" if not worker_attention else "warning",
            f"worker heartbeat={worker.get('heartbeat_status') or 'unknown'}，restart_count={worker.get('restart_count') if worker.get('restart_count') is not None else 'not_connected'}。",
            "把容器 restart count 和 worker heartbeat 接入腾讯云监控/CLS 告警。"
            if not worker_attention
            else "检查 worker 是否仍在处理 running job；如果 restart count 过高，先修复崩溃原因再扩大测试。",
        ),
    ]


def _ebay_live_read_adapter_item(settings: SaaSSettings) -> ReadinessItem:
    status = build_live_read_adapter_status(settings)
    if status.get("blocked_by"):
        return ReadinessItem(
            "ebay_live_read_adapter",
            "eBay live read adapter",
            "contract_only",
            "warning",
            "The backend has a live read adapter contract and route map, but real eBay HTTP reads remain disabled.",
            "Implement Vault token resolver, access-token cache, eBay HTTP client and live raw-response mapping before enabling live reads.",
        )
    return ReadinessItem(
        "ebay_live_read_adapter",
        "eBay live read adapter",
        "ready",
        "info",
        "eBay live read adapter is ready.",
        "Run queued read jobs and cache sanitized data packets.",
    )


def _environment_item(settings: SaaSSettings) -> ReadinessItem:
    if settings.environment in {"local_dev", "test"}:
        return ReadinessItem(
            "environment",
            "运行环境",
            "not_production",
            "warning",
            "当前仍是本地/测试环境，适合开发和内测，不适合开放真实商家。",
            "准备腾讯云/阿里云 staging 环境，并把 JIEJING_SAAS_ENV 设置为 staging。",
        )
    return ReadinessItem("environment", "运行环境", "ready", "info", "环境已按预上线或生产标记。", "继续检查数据库、队列、Vault 和执行服务。")


def _session_secret_item(settings: SaaSSettings) -> ReadinessItem:
    if settings.session_secret_is_default:
        return ReadinessItem(
            "session_secret",
            "登录会话密钥",
            "blocked_default_secret",
            "blocker",
            "当前使用默认本地 session secret。正式 SaaS 不能用默认密钥签登录 token。",
            "在云端密钥管理中生成 JIEJING_SAAS_SESSION_SECRET，并且长度至少 32 字符。",
        )
    return ReadinessItem("session_secret", "登录会话密钥", "ready", "info", "登录 token 签名密钥已由环境变量提供。", "后续接入轮换和失效策略。")


def _cors_item(settings: SaaSSettings) -> ReadinessItem:
    if settings.environment == "production" and settings.cors_allows_wildcard:
        return ReadinessItem(
            "cors_origin",
            "CORS origin policy",
            "blocked_wildcard_in_production",
            "blocker",
            "Production cannot use wildcard CORS origins.",
            "Set JIEJING_CORS_ORIGIN to the exact SaaS frontend origin before production startup.",
        )
    if settings.environment == "staging" and settings.cors_allows_wildcard:
        return ReadinessItem(
            "cors_origin",
            "CORS origin policy",
            "staging_wildcard_origin",
            "warning",
            "Staging is still using wildcard CORS; this is acceptable only for isolated local verification.",
            "Set JIEJING_CORS_ORIGIN to the staging frontend origin before real seller OAuth testing.",
        )
    return ReadinessItem(
        "cors_origin",
        "CORS origin policy",
        "ready",
        "info",
        "CORS origin is configured without a production wildcard.",
        "Keep JIEJING_CORS_ORIGIN aligned with the deployed frontend domain.",
    )


def _database_item(settings: SaaSSettings) -> ReadinessItem:
    contract = build_database_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.database_adapter == "sqlite-local" or settings.database_engine == "sqlite":
        return ReadinessItem(
            "database",
            "生产数据库",
            "blocked_sqlite",
            "blocker",
            "当前仍使用本地 SQLite。它适合开发，不适合多用户正式 SaaS。",
            "接 Postgres/MySQL，启用迁移、备份、恢复和最小权限账号。",
        )
    if not settings.database_url_configured:
        return ReadinessItem(
            "database",
            "生产数据库",
            "blocked_missing_database_url",
            "blocker",
            "数据库引擎已切换，但没有数据库连接配置。",
            "配置 JIEJING_DATABASE_URL，并把密钥放入 Vault/KMS。",
        )
    if selected.get("production_allowed") and not selected.get("driver_implemented"):
        return ReadinessItem(
            "database",
            "Production database",
            "configured_driver_pending",
            "blocker",
            f"{selected.get('label') or selected.get('key')} is selected and a database URL is configured, but the SaaS runtime still uses the SQLite repository path.",
            "Apply the Postgres migration, implement the backend repository/connection driver, then switch runtime reads and writes away from SQLite.",
        )
    return ReadinessItem("database", "生产数据库", "ready", "info", "生产数据库配置已提供。", "继续做迁移脚本、备份和恢复演练。")


def _queue_item(settings: SaaSSettings) -> ReadinessItem:
    contract = build_queue_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.queue_provider == "local_inline":
        return ReadinessItem(
            "queue",
            "任务队列",
            "local_split_steps_only",
            "blocker",
            "当前已经把工作流拆成可追踪步骤，但执行仍在本地请求中同步完成；真实商家多了以后会超时，也无法可靠重试。",
            "接 Redis / 云队列，把市场、刊登、素材、客服、财务拆成异步 job。",
        )
    if settings.queue_provider == "local_worker":
        return ReadinessItem(
            "queue",
            "任务队列",
            "local_worker_queue_shape",
            "blocker",
            "当前已经是“先入队、worker 再认领执行”的本地形态，可以验证任务状态、失败反馈和审计；但它还不是可多机扩展的生产队列。",
            "接 Redis / 云队列，把本地 worker 替换成云端 worker，并加入重试、死信队列和超时告警。",
        )
    if settings.queue_provider == "postgres_durable":
        if settings.database_engine != "postgres" or not settings.database_url_configured:
            return ReadinessItem(
                "queue",
                "Task queue",
                "blocked_postgres_durable_queue_without_postgres",
                "blocker",
                "Postgres durable queue is selected, but the runtime is not connected to managed Postgres.",
                "Set JIEJING_DATABASE_ENGINE=postgres and configure JIEJING_DATABASE_URL before using Postgres as the durable queue.",
            )
        return ReadinessItem(
            "queue",
            "Task queue",
            "postgres_durable_queue_ready",
            "info",
            "Postgres durable queue is selected: queued jobs, row-locked claim, heartbeat, timeout recovery and dead-letter visibility use the managed Postgres boundary.",
            "Monitor queue depth, stale running jobs, dead letters and worker heartbeat before paid launch.",
        )
    if not settings.queue_url_configured:
        return ReadinessItem("queue", "任务队列", "blocked_missing_queue_url", "blocker", "队列 provider 已设置，但没有队列连接。", "配置 JIEJING_QUEUE_URL 或云队列凭据。")
    if selected.get("production_allowed") and not selected.get("driver_implemented"):
        return ReadinessItem(
            "queue",
            "Task queue",
            "configured_driver_pending",
            "blocker",
            f"{selected.get('label') or selected.get('key')} is selected and a queue URL is configured, but workers still claim jobs from the local database queue.",
            "Implement the Redis/cloud queue adapter, heartbeat, retry, dead-letter queue, and timeout reaper before real merchants use it.",
        )
    return ReadinessItem("queue", "任务队列", "ready", "info", "异步任务队列配置已提供。", "继续增加重试、死信队列和超时拆分。")


def _vault_item(settings: SaaSSettings) -> ReadinessItem:
    if not settings.vault_enabled or settings.vault_provider == "secret_ref_only":
        return ReadinessItem(
            "vault",
            "密钥保险柜",
            "blocked_secret_ref_only",
            "blocker",
            "当前只保存 secret_ref，不保存真实密钥。这个边界是对的，但还没有接云端 Vault/KMS。",
            "接腾讯云 KMS / 阿里云 KMS / Vault，把 eBay、模型、物流、采购 token 全部放进去。",
        )
    return ReadinessItem("vault", "密钥保险柜", "ready", "info", "Vault/KMS 已配置。", "继续做密钥轮换、访问审计和最小权限策略。")


def _vault_adapter_item(settings: SaaSSettings) -> ReadinessItem:
    contract = build_vault_adapter_contract(settings)
    selected = contract.get("selected_adapter", {})
    if settings.is_production_like and contract.get("production_blockers"):
        return ReadinessItem(
            "vault_adapter_contract",
            "Vault/KMS adapter contract",
            "blocked_vault_adapter_not_production_ready",
            "blocker",
            f"Selected Vault adapter {selected.get('key')} cannot resolve, rotate, or revoke secrets in production yet.",
            "Implement the managed KMS/Vault client, backend-only secret resolver, rotation, revoke and audit hooks before staging.",
        )
    return ReadinessItem(
        "vault_adapter_contract",
        "Vault/KMS adapter contract",
        "adapter_contract_ready",
        "info",
        "The backend now exposes a replaceable Vault/KMS adapter contract with secret resolve, rotation, revoke and audit boundaries.",
        "Next implement the managed cloud client; keep raw tokens out of frontend, database, Runtime, Hermes and reports.",
    )


def _runtime_item(settings: SaaSSettings) -> ReadinessItem:
    if "local" in str(settings.runtime_db_path).lower() or settings.environment in {"local_dev", "test"}:
        return ReadinessItem(
            "runtime_workers",
            "Runtime Worker",
            "local_runtime_only",
            "warning",
            "当前 Runtime 在本机运行，可用于内测，不适合真实商家 24 小时使用。",
            "部署云端 Runtime Worker，并通过队列领取任务，不让前端直接访问。",
        )
    return ReadinessItem("runtime_workers", "Runtime Worker", "ready", "info", "Runtime 已按云端 worker 方向配置。", "继续做水平扩容和 worker 健康检查。")


def _model_item(
    model_status: dict[str, Any],
    platform_model_status: dict[str, Any],
    evidence: dict[str, Any],
) -> ReadinessItem:
    merchant_byok_secret_refs = int(evidence.get("model_secret_refs") or 0)
    if merchant_byok_secret_refs:
        return ReadinessItem(
            "model_provider",
            "大模型能力",
            "merchant_byok_secret_ref_ready",
            "info",
            "商家 BYOK 模型 key 已按 secret_ref 边界保存；前端、报告和 Runtime 不接收原始 key。",
            "继续做调用费用、限流、失败重试和商家可见的运行账本。",
        )
    if platform_model_status.get("configured"):
        return ReadinessItem(
            "model_provider",
            "大模型能力",
            "platform_default_model_ready",
            "info",
            "捷境试用 AI 已在后端安全边界内配置，商家也可以保存自己的账号模型。",
            "继续监控试用额度、调用成本、响应时间和失败降级。",
        )
    if not model_status.get("configured"):
        return ReadinessItem(
            "model_provider",
            "大模型能力",
            "rule_based_fallback",
            "warning",
            "当前可用规则兜底，但产品级 Agent 需要稳定大模型 provider。",
            "配置 JIEJING_MODEL_API_KEY / JIEJING_MODEL_BASE_URL / JIEJING_MODEL，并设置费用和超时控制。",
        )
    return ReadinessItem("model_provider", "大模型能力", "ready", "info", "模型 provider 已配置，未暴露密钥。", "继续做调用费用、限流和降级策略。")


def _ebay_oauth_item(settings: SaaSSettings, evidence: dict[str, Any]) -> ReadinessItem:
    if evidence.get("read_only_authorized_connections"):
        return ReadinessItem(
            "ebay_oauth_readonly",
            "eBay read-only OAuth",
            "read_only_authorized",
            "info",
            "At least one eBay read-only platform connection is authorized through the backend secret_ref boundary.",
            "Continue token refresh monitoring and seller-facing reauthorization recovery.",
        )
    missing = []
    if not settings.ebay_client_id:
        missing.append("client_id")
    if not settings.ebay_ru_name:
        missing.append("ru_name")
    if missing:
        return ReadinessItem(
            "ebay_oauth_readonly",
            "eBay 只读授权入口",
            "blocked_missing_oauth_config",
            "warning",
            "后端已有只读 OAuth 授权计划接口，但还缺少正式 eBay App ID / RuName 配置，不能生成真实授权跳转。",
            "配置 JIEJING_EBAY_CLIENT_ID 和 JIEJING_EBAY_RU_NAME；回调换 token 时必须写入 Vault/KMS，不进前端。",
        )
    return ReadinessItem(
        "ebay_oauth_readonly",
        "eBay 只读授权入口",
        "ready_to_redirect",
        "info",
        "后端可以生成 eBay 只读授权 URL，并记录 state、scope、store 和用户。",
        "下一步实现 OAuth callback：校验 state，后端换 token，refresh token 写入 Vault/KMS。",
    )


def _ebay_account_deletion_item(settings: SaaSSettings, evidence: dict[str, Any]) -> ReadinessItem:
    blockers = []
    if not settings.ebay_account_deletion_endpoint_url.startswith("https://"):
        blockers.append("https_endpoint")
    if not settings.ebay_account_deletion_verification_token_configured:
        blockers.append("verification_token")
    if not settings.ebay_client_id or not settings.ebay_client_secret_configured:
        blockers.append("ebay_application_credentials")
    if blockers:
        return ReadinessItem(
            "ebay_account_deletion_notifications",
            "eBay account deletion notifications",
            "blocked_missing_compliance_config",
            "warning",
            "The eBay account deletion endpoint is implemented but its backend-only production configuration is incomplete.",
            "Configure the HTTPS endpoint, verification token and eBay application credentials, then complete Developer Portal validation.",
        )
    active_connections = int(evidence.get("active_ebay_identity_connections") or 0)
    mapped_connections = int(evidence.get("mapped_ebay_identity_connections") or 0)
    if int(evidence.get("duplicate_ebay_identity_store_count") or 0) > 0:
        return ReadinessItem(
            "ebay_account_deletion_notifications",
            "eBay account deletion notifications",
            "duplicate_identity_review_required",
            "warning",
            "One immutable eBay seller identity is attached to more than one Jiejing store, so automatic deletion cannot safely choose a single store.",
            "Resolve the duplicate store ownership before enabling production onboarding; do not delete across tenants by inference.",
        )
    if mapped_connections < active_connections:
        return ReadinessItem(
            "ebay_account_deletion_notifications",
            "eBay account deletion notifications",
            "identity_mapping_pending",
            "warning",
            "The notification endpoint is configured, but one or more active eBay connections do not yet have an immutable backend identity selector.",
            "Reconnect only the affected seller account with the commerce.identity.readonly scope, then verify the identity mapping status.",
        )
    return ReadinessItem(
        "ebay_account_deletion_notifications",
        "eBay account deletion notifications",
        "operational_ready" if active_connections else "ready_for_portal_validation",
        "info",
        "Challenge validation, official-format signature verification, idempotent intake and scoped deletion processing are configured.",
        "Keep the Developer Portal subscription active and monitor verified delivery, retry, revocation and scoped deletion receipts."
        if active_connections
        else "Validate the endpoint in eBay Developer Portal and send a test notification.",
    )


def _ebay_token_refresh_item(settings: SaaSSettings, evidence: dict[str, Any]) -> ReadinessItem:
    adapter = build_ebay_token_refresh_adapter_status(settings)
    has_successful_refresh_probe = int(evidence.get("ebay_token_refresh_success_count") or 0) > 0
    if (
        evidence.get("read_only_authorized_connections")
        and evidence.get("ebay_secret_refs")
        and has_successful_refresh_probe
        and settings.ebay_token_refresh_live_enabled
        and settings.vault_enabled
        and adapter.get("status") == "ready"
    ):
        return ReadinessItem(
            "ebay_token_refresh",
            "eBay token refresh",
            "vault_backed_refresh_adapter_ready",
            "info",
            "Refresh-token handling is wired through the backend Vault-backed adapter; no raw token is exposed to frontend or Runtime.",
            "Keep monitoring refresh failures such as invalid_grant and expired seller authorization.",
        )
    if (
        evidence.get("read_only_authorized_connections")
        and evidence.get("ebay_secret_refs")
        and settings.ebay_token_refresh_live_enabled
        and settings.vault_enabled
        and adapter.get("status") == "ready"
        and not has_successful_refresh_probe
    ):
        return ReadinessItem(
            "ebay_token_refresh",
            "eBay token refresh",
            "refresh_adapter_probe_pending",
            "warning",
            "The backend Vault-backed refresh adapter is configured, but no successful refresh probe has been recorded in audit evidence yet.",
            "Run one backend-only refresh probe through /stores/{store_id}/ebay-oauth/refresh-now after the new seller account is connected; do not expose access or refresh tokens.",
        )
    missing = []
    if not settings.ebay_client_id:
        missing.append("client_id")
    if not settings.ebay_client_secret_configured:
        missing.append("client_secret")
    if not settings.vault_enabled or settings.vault_provider == "secret_ref_only":
        missing.append("vault")
    if not settings.ebay_token_refresh_live_enabled:
        missing.append("refresh_live_switch")
    missing.extend(str(item) for item in adapter.get("blocked_by") or [] if item not in missing)
    return ReadinessItem(
        "ebay_token_refresh",
        "eBay token 自动续期",
        "refresh_adapter_pending" if evidence.get("ebay_secret_refs") else "refresh_blocked",
        "warning",
        "后端已有 token refresh 计划接口；本地 MVP 不读取 refresh token，也不向前端返回 access token。",
        "接入 Vault/KMS 后，再实现后端 refresh-token 读取、eBay token endpoint 调用、短期 access token 缓存和审计。" if missing else "继续接真实 Vault 读取和 eBay refresh HTTP adapter。",
    )


def _has_current_official_ebay_packet(evidence: dict[str, Any]) -> bool:
    current_marker = evidence.get("latest_ebay_packet_current_connection")
    packet_is_current = True if current_marker is None else bool(current_marker)
    return bool(
        packet_is_current
        and evidence.get("latest_ebay_packet_source_mode") == "official_api"
        and evidence.get("latest_ebay_packet_present_resource_keys")
    )


def _ebay_read_adapter_item(settings: SaaSSettings, evidence: dict[str, Any]) -> ReadinessItem:
    if (
        _has_current_official_ebay_packet(evidence)
        and settings.ebay_read_only_live_enabled
    ):
        return ReadinessItem(
            "ebay_read_only_adapter",
            "eBay read-only adapter",
            "official_read_completed",
            "info",
            "The backend has completed an official eBay read-only sync and cached a sanitized standard packet.",
            "Continue route-level retry, packet freshness checks, and seller-visible failure recovery.",
        )
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "ebay_read_only_adapter",
            "eBay read-only adapter",
            "historical_packet_not_current",
            "info",
            "A previous seller packet remains archived, but it is not accepted as evidence for the current store connection.",
            "Wait for operator-approved authorization of the clean seller account, then create a new read-only packet.",
        )
    missing = []
    if not settings.ebay_read_only_live_enabled:
        missing.append("read_live_switch")
    if not settings.ebay_token_refresh_live_enabled:
        missing.append("token_refresh")
    if not settings.vault_enabled or settings.vault_provider == "secret_ref_only":
        missing.append("vault")
    return ReadinessItem(
        "ebay_read_only_adapter",
        "eBay 只读 Adapter",
        "read_adapter_contract_ready",
        "warning",
        "后端已有 eBay 只读资源目录和 probe plan 接口；本地 MVP 不读取真实店铺、订单、费用或政策数据。",
        "接入 Vault/KMS、token refresh、HTTP adapter、缓存和脱敏日志后，再开启真实只读读取。" if missing else "继续实现真实只读 HTTP adapter 和缓存层。",
    )


def _data_packet_cache_item(counts: dict[str, int], evidence: dict[str, Any]) -> ReadinessItem:
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "platform_data_packets",
            "只读数据包缓存",
            "historical_packet_archived",
            "info",
            "旧卖家数据包仍保留用于审计，但不会作为当前店铺、Listing 或发布判断的依据。",
            "新账号完成只读授权后生成新的脱敏数据包；不要复用历史账号证据。",
        )
    if counts.get("platform_data_packets", 0) < 1:
        return ReadinessItem(
            "platform_data_packets",
            "只读数据包缓存",
            "contract_ready_not_exercised",
            "warning",
            "后端已有只读数据包表和 API，但当前库里还没有生成过数据包。",
            "跑一次 eBay read-only data-packet 流程，确认脱敏、来源标注、审计和 Runtime 输入边界。",
        )
    return ReadinessItem(
        "platform_data_packets",
        "只读数据包缓存",
        "exercised",
        "info",
        "已生成过只读数据包，可作为 Runtime 报告和草稿的受控输入。",
        "下一步接真实只读 adapter 后，把官方 API 数据也统一写入这个数据包结构。",
    )


def _real_saas_loop_item(evidence: dict[str, Any]) -> ReadinessItem:
    present = evidence.get("latest_ebay_packet_present_resource_keys") or []
    missing = evidence.get("latest_ebay_packet_missing_resource_keys") or []
    has_reports = int(evidence.get("report_count") or 0) > 0
    has_confirmations = int(evidence.get("confirmation_count") or 0) > 0
    if _has_current_official_ebay_packet(evidence) and has_reports and has_confirmations:
        return ReadinessItem(
            "real_saas_loop_evidence",
            "Real SaaS loop evidence",
            "official_packet_reports_confirmations",
            "info",
            f"Official eBay packet {evidence.get('latest_ebay_packet_id')} has {len(present)} resource sections, {len(missing)} source gaps, reports, and confirmation records.",
            "Next make this evidence the frontend source of truth and remove old demo fallbacks from production mode.",
        )
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "real_saas_loop_evidence",
            "Real SaaS loop evidence",
            "historical_loop_archived_not_current",
            "info",
            "The archived seller packet, reports and confirmations cannot prove the workflow for the current seller account.",
            "Re-run the read-only packet to confirmation path only after the clean account is explicitly approved.",
        )
    return ReadinessItem(
        "real_saas_loop_evidence",
        "Real SaaS loop evidence",
        "partial_or_missing",
        "warning",
        "The backend has not yet proven the full official packet -> reports -> confirmations loop in the current database.",
        "Run eBay read-only sync, then run AI CEO workflow, then refresh /data-packets, /reports, and /confirmations.",
    )


def _ebay_read_item(ebay: dict[str, Any], evidence: dict[str, Any]) -> ReadinessItem:
    if _has_current_official_ebay_packet(evidence):
        return ReadinessItem(
            "ebay_read",
            "eBay read-only access",
            "official_packet_ready",
            "info",
            "Official eBay read-only data is present as a sanitized backend packet; Runtime and frontend still do not receive raw tokens.",
            "Continue packet freshness, route health, and token refresh failure recovery.",
        )
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "ebay_read",
            "eBay read-only access",
            "historical_packet_not_current",
            "info",
            "Official data from a previous seller account is archived, but current eBay read access is not proven.",
            "Do not repeat OAuth until the operator approves a clean account; then prove read-only access and token refresh.",
        )
    if not ebay.get("credential_present"):
        status = "expired_or_missing" if ebay.get("refresh_required") else "missing"
        return ReadinessItem(
            "ebay_read",
            "eBay 只读接入",
            status,
            "warning",
            "当前后端没有稳定可用的 eBay 只读 token，市场和店铺数据会依赖样本或人工输入。",
            "先做 OAuth 只读授权闭环，自动刷新 access token，不开放写入。",
        )
    return ReadinessItem("ebay_read", "eBay 只读接入", "ready", "info", "eBay 只读凭据可被后端解析，未暴露 token。", "继续做只读调用缓存和错误恢复。")


def _account_health_incident_item(evidence: dict[str, Any]) -> ReadinessItem:
    present = set(evidence.get("latest_ebay_packet_present_resource_keys") or [])
    has_official_packet = _has_current_official_ebay_packet(evidence)
    if has_official_packet and "store_profile" in present:
        return ReadinessItem(
            "account_health_incident_mode",
            "Account health incident mode",
            "packet_backed_gate_ready",
            "info",
            "Latest official eBay packet includes store_profile, so publish preflight can derive an account-health gate without exposing tokens.",
            "Keep missing or abnormal account health as a real-write blocker and show the evidence package in Settings and publish health.",
        )
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "account_health_incident_mode",
            "Account health incident mode",
            "historical_snapshot_archived_block_by_default",
            "info",
            "The available account-health snapshot belongs to historical seller evidence, so real writes remain blocked by default.",
            "Create a fresh store_profile snapshot only after the clean seller account is explicitly authorized.",
        )
    if evidence.get("latest_ebay_packet_id"):
        return ReadinessItem(
            "account_health_incident_mode",
            "Account health incident mode",
            "store_profile_missing_from_packet",
            "warning",
            "The latest eBay packet exists, but store_profile is missing, so account suspension, restriction, payout hold, and seller limit status cannot be trusted.",
            "Run a read-only sync that includes store_profile before any real publish test.",
        )
    return ReadinessItem(
        "account_health_incident_mode",
        "Account health incident mode",
        "account_health_snapshot_missing",
        "warning",
        "No current eBay account-health snapshot is available; incident mode must block real writes by default.",
        "Connect or restore eBay read-only access, then sync store_profile before using a new seller account for live publish testing.",
    )


def _ebay_policy_item(ebay: dict[str, Any], evidence: dict[str, Any]) -> ReadinessItem:
    present = set(evidence.get("latest_ebay_packet_present_resource_keys") or [])
    if _has_current_official_ebay_packet(evidence) and "account_business_policies" in present:
        return ReadinessItem(
            "ebay_business_policies",
            "eBay business policies",
            "official_policy_packet_ready",
            "info",
            "Business policy data is present in the latest official eBay read-only packet.",
            "Continue mapping policy IDs into listing-package validation and confirmation center previews.",
        )
    if evidence.get("historical_ebay_packet_present"):
        return ReadinessItem(
            "ebay_business_policies",
            "eBay business policies",
            "historical_policy_packet_archived",
            "info",
            "Previous seller policy IDs remain archived and are not reusable for the current seller account.",
            "Read the clean account policies after approved authorization; never copy policy IDs across seller accounts.",
        )
    if not ebay.get("policy_snapshot_present"):
        return ReadinessItem(
            "ebay_business_policies",
            "eBay 三类政策",
            "snapshot_missing",
            "warning",
            "物流、支付、退货政策还不能稳定从后端读取。真实发布前必须有 policyId。",
            "先接 Account Policy 只读或导入店铺 policy 快照，再映射到刊登包。",
        )
    return ReadinessItem("ebay_business_policies", "eBay 三类政策", "ready", "info", "后端可读取到业务政策快照。", "继续把 policyId 写入产品刊登校验。")


def _execution_item(settings: SaaSSettings, evidence: dict[str, Any]) -> ReadinessItem:
    if settings.effective_real_platform_writes_enabled:
        return ReadinessItem(
            "execution_service",
            "Real execution service",
            "confirmation_gated_real_write_ready",
            "info",
            "Real eBay writes are enabled only behind the confirmation center, execution preflight, idempotency and audit boundary.",
            "Continue low-volume real publish tests with recovery checks and cleanup confirmations; keep payments, refunds, ads, policy edits and buyer promises confirmation-gated.",
        )
    if settings.effective_ebay_draft_save_enabled and int(evidence.get("ebay_unpublished_draft_save_proof_count") or 0) > 0:
        return ReadinessItem(
            "execution_service",
            "Controlled eBay draft save",
            "unpublished_ebay_draft_save_proven",
            "info",
            "One confirmation-gated eBay Inventory API draft was saved with an UNPUBLISHED offer receipt; public publish remains disabled.",
            "Keep publishOffer disabled. Review the merchant-visible draft and retain the one-shot execution and manual-reconcile boundary.",
        )
    if settings.effective_ebay_draft_save_enabled:
        return ReadinessItem(
            "execution_service",
            "Controlled eBay draft save",
            "ebay_draft_save_live_proof_pending",
            "warning",
            "The draft-only adapter is enabled, but no current-store UNPUBLISHED eBay receipt has passed the evidence contract yet.",
            "Create one exact draft confirmation, let the merchant approve it, save it once, and verify no public listing exists.",
        )
    if settings.requested_real_platform_writes:
        return ReadinessItem(
            "execution_service",
            "真实执行服务",
            "blocked_real_write_request",
            "blocker",
            "检测到有人请求打开真实写入，但当前执行适配器仍是演示安全模式，必须拒绝。",
            "先完成 eBay 只读、确认中心、审计、Vault、队列和生产数据库，再逐项开放写入 adapter。",
        )
    return ReadinessItem(
        "execution_service",
        "真实执行服务",
        "ebay_draft_save_adapter_ready_disabled",
        "warning",
        "eBay 未发布草稿适配器已接入确认、预检、幂等和审计边界，但当前开关关闭，不会写入 eBay；付款、退款、采购等动作也仍未开放。",
        "账号准备好后，先做一次受控的 eBay 未发布草稿保存证明，确认没有公开 Listing，再考虑单商品发布。",
    )


def _tenant_audit_item(counts: dict[str, int]) -> ReadinessItem:
    if counts.get("users", 0) < 1 or counts.get("companies", 0) < 1:
        return ReadinessItem(
            "tenant_audit",
            "租户与审计",
            "not_exercised",
            "warning",
            "还没有本地租户数据，无法证明数据隔离和审计写入。",
            "跑一遍 SaaS 后端端到端测试，至少创建两个公司并验证不能串店铺。",
        )
    return ReadinessItem("tenant_audit", "租户与审计", "ready", "info", "已有租户、店铺、任务和审计记录。", "继续增加权限角色和审计查询。")


def _public_model_status(
    model_status: dict[str, Any],
    platform_model_status: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    merchant_byok_secret_refs = int(evidence.get("model_secret_refs") or 0)
    env_configured = bool(model_status.get("configured"))
    platform_default_configured = bool(platform_model_status.get("configured"))
    if merchant_byok_secret_refs > 0:
        mode = "merchant_byok"
    elif platform_default_configured:
        mode = "platform_managed_default"
    else:
        mode = "environment_provider"
    return {
        "client": model_status.get("client") if env_configured else "platform-managed-default" if platform_default_configured else model_status.get("client"),
        "model": platform_model_status.get("model") if platform_default_configured else model_status.get("model"),
        "configured": env_configured or platform_default_configured or merchant_byok_secret_refs > 0,
        "env_provider_configured": env_configured,
        "platform_default_configured": platform_default_configured,
        "merchant_byok_configured": merchant_byok_secret_refs > 0,
        "merchant_byok_secret_ref_count": merchant_byok_secret_refs,
        "mode": mode,
        "frontend_gets_model_api_key": False,
        "runtime_gets_model_api_key": False,
        "reports_get_model_api_key": False,
        "secret_exposed": False,
    }


def _public_ebay_status(ebay: dict[str, Any]) -> dict[str, Any]:
    return {
        "credential_present": bool(ebay.get("credential_present")),
        "access_token_status": ebay.get("access_token_status"),
        "refresh_required": bool(ebay.get("refresh_required")),
        "policy_snapshot_present": bool(ebay.get("policy_snapshot_present")),
        "listing_rules_snapshot_present": bool(ebay.get("listing_rules_snapshot_present")),
        "secret_exposed": False,
    }


def _public_platform_registry_status() -> dict[str, Any]:
    summary = registry_summary()
    return {
        "version": summary.get("version"),
        "current_primary": summary.get("current_primary"),
        "platform_count": summary.get("platform_count"),
        "platform_keys": [item.get("key") for item in summary.get("platforms", [])],
        "no_live_calls": summary.get("guardrails", {}).get("no_live_calls"),
        "all_writes_confirmation_gated": summary.get("guardrails", {}).get("all_writes_confirmation_gated"),
        "secret_exposed": False,
    }


def _public_provider_job_status() -> dict[str, Any]:
    catalog = build_provider_job_contract_catalog()
    return {
        "contract_version": catalog.get("contract_version"),
        "contract_count": catalog.get("contract_count"),
        "provider_families": catalog.get("provider_families", []),
        "queue_rules": catalog.get("queue_rules", {}),
        "secret_exposed": False,
        "real_execution_allowed": False,
    }


def _public_controlled_bridge_status(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    contract = build_controlled_bridge_contract(settings, repository)
    return {
        "contract_version": contract.get("contract_version"),
        "ready": not bool(contract.get("production_blockers")),
        "formal_bridge_count": contract.get("formal_bridge_count"),
        "legacy_bridge_count": contract.get("legacy_bridge_count"),
        "production_blockers": contract.get("production_blockers", []),
        "hermes_legacy_bridge_can_be_production_dependency": contract.get("rules", {}).get(
            "hermes_legacy_bridge_can_be_production_dependency"
        ),
        "secret_exposed": False,
    }


def _public_backup_status(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    plan = build_backup_plan(settings, repository)
    return {
        "contract_version": plan.get("contract_version"),
        "backup_ready_for_paid_launch": bool(plan.get("backup_ready_for_paid_launch")),
        "blockers": plan.get("blockers", []),
        "secret_exposed": False,
    }


def _public_billing_status(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    plan = build_billing_plan(settings, repository)
    mainland = plan.get("mainland_payment_launch") if isinstance(plan.get("mainland_payment_launch"), dict) else {}
    quota = plan.get("quota_contract") if isinstance(plan.get("quota_contract"), dict) else {}
    payment = _validated_public_mainland_payment(mainland)
    legacy_provider = plan.get("provider") if isinstance(plan.get("provider"), dict) else {}
    legacy_launch_path = plan.get("merchant_launch_path") if isinstance(plan.get("merchant_launch_path"), dict) else {}
    private_beta_test_active = all(
        (
            plan.get("billing_ready_for_private_beta") is True,
            legacy_provider.get("test_billing_provider_configured") is True,
            legacy_launch_path.get("contract_version") == "2026-07-03-merchant-billing-launch-path-v1",
            legacy_launch_path.get("current_stage") == "invited_beta_no_real_charge",
            legacy_launch_path.get("public_paid_launch_allowed") is False,
            legacy_launch_path.get("charge_now_allowed") is False,
            legacy_launch_path.get("triggers_real_charge") is False,
            legacy_launch_path.get("frontend_can_grant_entitlement") is False,
            legacy_launch_path.get("frontend_can_grant_quota") is False,
            legacy_launch_path.get("backend_confirmation_required_before_entitlement") is True,
            legacy_launch_path.get("secret_exposed") is False,
        )
    )
    public_paid_launch_blockers = [payment["next_paid_launch_blocker"]]
    return {
        "contract_version": plan.get("contract_version"),
        "billing_ready_for_private_beta": plan.get("billing_ready_for_private_beta") is True,
        "billing_ready_for_paid_launch": False,
        "mainland_payment_ready_for_owner_approval": payment["mainland_payment_ready_for_owner_approval"],
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "provider_configured": payment["provider_configured"],
        "payment_path_status": payment["payment_path_status"],
        "configured_component_count": payment["configured_component_count"],
        "required_component_count": payment["required_component_count"],
        "verified_paid_order_count": payment["verified_paid_order_count"],
        "plan_count": len(plan.get("plan_catalog")) if isinstance(plan.get("plan_catalog"), list) else 0,
        "quota_enforcement_enabled": quota.get("enabled") is True,
        "paid_launch_blockers": public_paid_launch_blockers,
        "paid_launch_blocker_count": len(public_paid_launch_blockers),
        "next_paid_launch_blocker": public_paid_launch_blockers[0] if public_paid_launch_blockers else "",
        "merchant_launch_path": {
            "contract_version": (
                "2026-07-03-merchant-billing-launch-path-v1"
                if private_beta_test_active
                else "2026-07-27-merchant-mainland-payment-path-v1"
            ),
            "current_stage": (
                "invited_beta_no_real_charge" if private_beta_test_active else payment["payment_path_status"]
            ),
            "headline": "merchant_payment_status_available_in_billing_control_room",
            "current_charge_status": "no_real_charge_now",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "hosted_payment_page_required_for_formal_payment": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "quota_grant_source": "backend_subscription_state",
            "history_visible_after_billing_problem": True,
            "metered_work_only_blocks_on_billing_problem": True,
            "secret_exposed": False,
        },
        "domestic_payment": {
            "provider": "wechat_pay_native",
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "status": payment["domestic_payment_status"],
            "configured_component_count": payment["configured_component_count"],
            "required_component_count": payment["required_component_count"],
            "controlled_acceptance_proven": payment["controlled_acceptance_proven"],
            "verified_paid_order_count": payment["verified_paid_order_count"],
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "frontend_can_grant_quota": False,
        "secret_exposed": False,
}


def _validated_public_mainland_payment(mainland: dict[str, Any]) -> dict[str, Any]:
    """Validate the canonical internal contract before exposing aggregate facts."""
    return validate_mainland_payment_launch_for_public(mainland)


def _safe_public_count(value: Any) -> int:
    if type(value) is not int or value < 0:
        return 0
    return value


def _public_model_value_status(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    gate = build_model_value_gate(settings, repository)
    model_client = gate.get("model_client") if isinstance(gate.get("model_client"), dict) else {}
    merchant_byok = gate.get("merchant_byok_model") if isinstance(gate.get("merchant_byok_model"), dict) else {}
    platform_default = gate.get("platform_default_model") if isinstance(gate.get("platform_default_model"), dict) else {}
    env_configured = bool(model_client.get("configured"))
    merchant_byok_configured = bool(merchant_byok.get("configured"))
    platform_default_configured = bool(platform_default.get("configured"))
    return {
        "contract_version": gate.get("contract_version"),
        "ready_for_paid_value_claim": bool(gate.get("ready_for_paid_value_claim")),
        "model_configured": env_configured or platform_default_configured or merchant_byok_configured,
        "env_provider_configured": env_configured,
        "platform_default_configured": platform_default_configured,
        "merchant_byok_configured": merchant_byok_configured,
        "merchant_byok_secret_ref_count": int(merchant_byok.get("ready_secret_ref_count") or 0),
        "live_model_report_types": (gate.get("evidence") or {}).get("live_model_report_types", []),
        "blockers": gate.get("blockers", []),
        "secret_exposed": False,
    }


def _public_operational_health_status(health: dict[str, Any]) -> dict[str, Any]:
    database = health.get("database_live_probe") if isinstance(health.get("database_live_probe"), dict) else {}
    queue = health.get("queue_runtime") if isinstance(health.get("queue_runtime"), dict) else {}
    worker = health.get("worker_runtime") if isinstance(health.get("worker_runtime"), dict) else {}
    queue_counts = queue.get("counts") if isinstance(queue.get("counts"), dict) else {}
    return {
        "status": health.get("status") or "unknown",
        "database_status": database.get("status") or "unknown",
        "queue_status": queue.get("status") or "unknown",
        "queue_provider": queue.get("queue_provider") or worker.get("queue_provider") or "",
        "queued": int(queue_counts.get("queued") or 0),
        "running": int(queue_counts.get("running") or 0),
        "failed": int(queue_counts.get("failed") or 0),
        "dead_letter": int(queue_counts.get("dead_letter") or 0),
        "stale_running_count": int(queue.get("stale_running_count") or 0),
        "latest_worker_heartbeat_at": (
            queue.get("latest_worker_heartbeat_at")
            or worker.get("latest_job_heartbeat_at")
            or worker.get("latest_registered_worker_heartbeat_at")
            or ""
        ),
        "worker_heartbeat_status": worker.get("heartbeat_status") or "unknown",
        "registered_worker_status": worker.get("registered_worker_status") or "",
        "registered_process_started_at": worker.get("registered_process_started_at") or "",
        "worker_restart_count": worker.get("restart_count"),
        "worker_restart_count_source": worker.get("restart_count_source") or "not_connected",
        "blockers": list(health.get("blockers") or []),
        "warnings": list(health.get("warnings") or []),
        "secret_exposed": False,
    }


def _public_media_generation_status() -> dict[str, Any]:
    provider = (os.environ.get("JIEJING_MEDIA_GENERATION_PROVIDER") or "fal").strip() or "fal"
    status = MediaGenerationAdapter().provider_status(provider)
    driver_configured = bool(status.get("configured"))
    live_enabled = _env_enabled("JIEJING_MEDIA_LIVE_PROVIDER_ENABLED", default=False)
    video_enabled = _env_enabled("JIEJING_MEDIA_LIVE_VIDEO_ENABLED", default=False)
    live_calls_allowed = bool(live_enabled and driver_configured)
    if live_calls_allowed:
        public_status = "live_generation_ready_waiting_asset_review"
        customer_visible_summary = "素材真实生成通道已可用；输出仍必须先进入素材清单、权利审核和 Listing 复核。"
        next_action = "继续审核素材清单、成本记录和 Listing 使用状态；不要跳过人工确认。"
    elif driver_configured:
        public_status = "dry_run_review_chain_ready_live_generation_disabled"
        customer_visible_summary = "素材审核链路已就绪；当前不会真实消耗生图或生视频额度。"
        next_action = "上线真实生成前，先打开后台开关、额度保护和素材审核流程。"
    else:
        public_status = "dry_run_review_chain_ready_missing_media_driver"
        customer_visible_summary = "当前可以生成素材需求、脚本和素材清单演练；还没有启用真实生图/生视频通道。"
        next_action = "配置后台素材生成通道后，再用全新商品和全新素材做受控测试。"
    return {
        "contract_version": "2026-07-05-media-generation-readiness",
        "configured": driver_configured,
        "status": public_status,
        "live_generation_enabled": live_enabled,
        "live_image_generation_enabled": live_calls_allowed,
        "live_video_generation_enabled": bool(live_calls_allowed and video_enabled),
        "live_provider_calls_allowed": live_calls_allowed,
        "asset_manifest_required": True,
        "asset_review_required": True,
        "fact_review_required": True,
        "human_review_required_before_listing": True,
        "cost_guard_required": True,
        "spend_now_allowed": False,
        "listing_use_requires_review": True,
        "customer_visible_summary": customer_visible_summary,
        "next_action": next_action,
        "frontend_gets_media_api_key": False,
        "runtime_gets_raw_secret": False,
        "reports_get_raw_provider_response": False,
        "raw_provider_response_stored": False,
        "secret_exposed": False,
    }


def _public_search_status() -> dict[str, Any]:
    status = PublicSearchProbeAdapter().provider_status("tavily")
    realtime_enabled = str(os.environ.get("JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED") or "true").strip().lower() not in {"0", "false", "no", "off"}
    builtin_public_web_enabled = (
        str(os.environ.get("JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED") or "true").strip().lower()
        not in {"0", "false", "no", "off"}
    )
    return {
        "provider": status.get("provider"),
        "configured": bool(status.get("configured")),
        "endpoint_host": status.get("endpoint_host"),
        "credential_present": bool(status.get("credential_present")),
        "credential_source": status.get("credential_source") if status.get("credential_present") else "missing",
        "ai_ceo_realtime_search_enabled": realtime_enabled,
        "builtin_public_web_fallback_enabled": builtin_public_web_enabled,
        "builtin_stock_quote_fallback_enabled": builtin_public_web_enabled,
        "frontend_gets_search_api_key": False,
        "runtime_gets_search_api_key": False,
        "secret_exposed": False,
    }


def _ai_ceo_platform_model_status(platform_model_status: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_status = dict(platform_model_status or build_platform_default_model_status())
    monthly_limit = _nonnegative_int_env("JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT", 20)
    safe_status.update({
        "contract_version": "2026-07-10-ai-ceo-platform-model-trial",
        "trial_monthly_limit": monthly_limit,
        "trial_quota_source": "backend_task_audit",
        "trial_quota_scope": "account_month",
        "usage_owner": "jiejing_platform_trial",
        "usage_owner_label": "捷境试用 AI",
        "quota_checked_by_backend": True,
        "hard_stop_on_exhaustion": True,
        "exhaustion_blocker": "platform_default_model_trial_exhausted",
        "hard_stop_scope": "platform_managed_default_ai_only",
        "merchant_byok_preferred": True,
        "merchant_byok_not_counted_against_platform_trial": True,
        "byok_bypasses_platform_trial": True,
        "customer_visible_next_action": "save_account_ai_or_upgrade_plan",
        "operator_cost_monitoring_required": True,
        "frontend_can_grant_quota": False,
        "frontend_gets_model_api_key": False,
        "runtime_gets_model_api_key": False,
        "secret_exposed": False,
    })
    return safe_status


def _env_enabled(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _nonnegative_int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _next_minimum_actions(items: list[ReadinessItem]) -> list[str]:
    ordered = [item.next_action for item in items if item.status != "ready"]
    return ordered[:6]
