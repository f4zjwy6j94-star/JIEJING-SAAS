"""Controlled bridge contract for the Jiejing SaaS runtime path.

The bridge contract is the production-facing map of how work moves through
Jiejing. It makes the approved paths explicit and keeps Hermes as a transitional
legacy adapter instead of a production dependency.
"""

from __future__ import annotations

from typing import Any

from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog

from .config import SaaSSettings
from .queue_plan import build_queue_plan
from .repository import SaaSRepository


FORMAL_BRIDGE_KEYS = {
    "RuntimeBridge",
    "ProviderAdapter",
    "QueueWorkerBridge",
    "ConfirmationExecutionBridge",
    "AuditMemoryBridge",
}


def build_controlled_bridge_contract(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    queue_plan = build_queue_plan(settings, repository)
    provider_catalog = build_provider_job_contract_catalog()
    bridges = [
        _runtime_bridge(settings),
        _provider_adapter(provider_catalog),
        _queue_worker_bridge(settings, queue_plan),
        _confirmation_execution_bridge(settings),
        _audit_memory_bridge(repository),
        _hermes_legacy_bridge(settings),
    ]
    formal = [item for item in bridges if item.get("key") in FORMAL_BRIDGE_KEYS]
    blockers: list[str] = []
    if settings.allow_hermes_adapters:
        blockers.append("hermes_legacy_bridge_enabled")
    if {item.get("key") for item in formal} != FORMAL_BRIDGE_KEYS:
        blockers.append("missing_formal_bridge")
    if any(item.get("guardrails", {}).get("frontend_gets_raw_secret") is not False for item in formal):
        blockers.append("frontend_secret_boundary_not_enforced")
    if any(item.get("guardrails", {}).get("runtime_gets_raw_secret") is not False for item in formal):
        blockers.append("runtime_secret_boundary_not_enforced")
    if any(item.get("guardrails", {}).get("bypasses_confirmation_center") is not False for item in formal):
        blockers.append("confirmation_center_bypass_allowed")
    if settings.is_production_like and not queue_plan.get("production_queue_ready"):
        blockers.append("queue_worker_bridge_not_production_ready")
    return {
        "contract_version": "2026-06-12-controlled-bridges",
        "product": "Jiejing SaaS",
        "position": "Backend-owned controlled bridges; Hermes legacy bridge is transitional only.",
        "formal_bridge_count": len(formal),
        "legacy_bridge_count": len([item for item in bridges if item.get("category") == "legacy_transition"]),
        "bridges": bridges,
        "production_blockers": blockers,
        "ready_for_paid_launch_path": settings.is_production_like and not blockers,
        "rules": {
            "frontend_direct_provider_call_allowed": False,
            "runtime_or_agents_get_raw_provider_secret": False,
            "provider_tokens_resolved_only_inside_backend": True,
            "high_risk_actions_require_confirmation_center": True,
            "queue_worker_claims_jobs_through_durable_bridge": True,
            "audit_and_memory_are_writeback_bridges": True,
            "hermes_legacy_bridge_can_be_production_dependency": False,
        },
        "secret_exposed": False,
    }


def _runtime_bridge(settings: SaaSSettings) -> dict[str, Any]:
    allowed_adapters = ["jiejing-local", "jiejing-llm", "jiejing-deepseek", "mock"]
    return {
        "key": "RuntimeBridge",
        "label": "RuntimeBridge",
        "category": "formal",
        "status": "ready" if not settings.allow_hermes_adapters else "blocked_hermes_adapter_allowed",
        "interface": "SaaS Backend -> RuntimeBridge -> Jiejing Runtime tasks/results",
        "owned_by": "jiejing_saas.runtime_bridge.RuntimeBridge",
        "allowed_adapters": allowed_adapters,
        "blocked_adapters": ["hermes-plan", "hermes-shadow", "hermes-file"],
        "inputs": ["task_id", "company_id", "store_id", "user_id", "sanitized task body"],
        "outputs": ["runtime reports", "confirmation items", "validation summary", "sanitized SaaS snapshot"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=False,
            audit=True,
            memory=False,
            raw_secret=False,
        ),
        "audit_events": ["task.workflow.started", "task.workflow.completed", "task.workflow.failed"],
        "next_action": "Keep Hermes adapters disabled for formal SaaS runtime execution.",
        "secret_exposed": False,
    }


def _provider_adapter(provider_catalog: dict[str, Any]) -> dict[str, Any]:
    provider_keys = [str(item.get("key")) for item in provider_catalog.get("contracts", [])]
    return {
        "key": "ProviderAdapter",
        "label": "ProviderAdapter",
        "category": "formal",
        "status": "ready" if len(provider_keys) >= 6 else "blocked_missing_provider_contracts",
        "interface": "Backend Secret Boundary -> ProviderAdapter -> normalized source/output packets",
        "owned_by": "jiejing_saas.provider_job_runner.ProviderJobRunner plus provider-specific adapters",
        "provider_job_keys": provider_keys,
        "inputs": ["secret_ref", "task scoped inputs", "provider contract key"],
        "outputs": ["normalized output packet", "source record", "merchant-visible status"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=False,
            audit=True,
            memory=False,
            raw_secret=False,
        ),
        "audit_events": ["provider_job.started", "provider_job.completed", "provider_job.failed"],
        "next_action": "Replace dry-run adapters one by one with live provider clients behind Vault/KMS, quota and audit.",
        "secret_exposed": False,
    }


def _queue_worker_bridge(settings: SaaSSettings, queue_plan: dict[str, Any]) -> dict[str, Any]:
    production_ready = bool(queue_plan.get("production_queue_ready"))
    status = "ready" if production_ready else "contract_ready_queue_not_production"
    if settings.queue_provider == "postgres_durable" and queue_plan.get("postgres_durable_queue_ready"):
        status = "ready"
    return {
        "key": "QueueWorkerBridge",
        "label": "QueueWorkerBridge",
        "category": "formal",
        "status": status,
        "interface": "SaaS Backend -> durable queue_jobs -> worker claim/heartbeat/retry/dead-letter",
        "owned_by": "jiejing_saas.repository plus tools/jiejing_worker_cli.py",
        "queue_provider": settings.queue_provider,
        "inputs": ["queued task", "provider job", "recovery request"],
        "outputs": ["worker result", "queue timeline", "dead-letter visibility", "stale recovery summary"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=False,
            audit=True,
            memory=False,
            raw_secret=False,
        ),
        "capabilities": {
            "concurrency_safe_claim": settings.queue_provider == "postgres_durable",
            "retry": True,
            "dead_letter": True,
            "heartbeat": True,
            "timeout_recovery": True,
            "worker_status_visible": True,
        },
        "production_blockers": list(queue_plan.get("production_blockers", [])),
        "audit_events": ["queue.job.created", "queue.job.claimed", "queue.job.completed", "queue.job.dead_lettered"],
        "next_action": "Monitor queue depth, stale running jobs and dead letters before increasing traffic.",
        "secret_exposed": False,
    }


def _confirmation_execution_bridge(settings: SaaSSettings) -> dict[str, Any]:
    return {
        "key": "ConfirmationExecutionBridge",
        "label": "ConfirmationExecutionBridge",
        "category": "formal",
        "status": "ready",
        "interface": "Confirmation Center -> ExecutionService -> provider write adapter",
        "owned_by": "jiejing_runtime.execution.ExecutionService and jiejing_saas.ebay_write_adapter",
        "execution_adapter": settings.execution_adapter,
        "real_platform_writes_enabled": settings.effective_real_platform_writes_enabled,
        "high_risk_actions": [
            "publish_listing",
            "revise_listing",
            "price_change",
            "inventory_change",
            "refund",
            "advertising_budget",
            "business_policy_edit",
            "procurement_payment",
            "sensitive_buyer_promise",
        ],
        "inputs": ["approved confirmation", "preflight result", "idempotency key", "payload hash"],
        "outputs": ["execution result", "duplicate guard", "audit record"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=True,
            audit=True,
            memory=True,
            raw_secret=False,
        ),
        "audit_events": ["confirmation.approve", "execution.preflight", "execution.completed", "execution.duplicate_suppressed"],
        "next_action": "Keep every real write behind confirmation center and account-health preflight.",
        "secret_exposed": False,
    }


def _audit_memory_bridge(repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    return {
        "key": "AuditMemoryBridge",
        "label": "AuditMemoryBridge",
        "category": "formal",
        "status": "ready",
        "interface": "Reports/confirmations/execution -> audit logs and merchant memory writeback",
        "owned_by": "jiejing_saas.repository.SaaSRepository",
        "counts": {
            "audit_logs": int(counts.get("audit_logs") or 0),
            "reports": int(counts.get("reports") or 0),
            "confirmations": int(counts.get("confirmations") or 0),
            "merchant_memory": int(counts.get("merchant_memory") or 0),
        },
        "memory_policy": {
            "ordinary_chat_long_term_memory": "only_when_user_explicitly_says_remember_this_rule",
            "merchant_rule_memory": "explicit_user_rule_only",
            "workflow_report_confirmation_execution_memory": "permanent_audit_and_operating_memory",
            "raw_secret_memory_allowed": False,
        },
        "inputs": ["report", "confirmation", "execution result", "explicit merchant rule"],
        "outputs": ["audit log", "merchant memory item", "source-linked work record"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=False,
            audit=True,
            memory=True,
            raw_secret=False,
        ),
        "audit_events": ["report.created", "merchant_memory.upserted", "audit.recorded"],
        "next_action": "Expose source labels and memory-write reasons beside AI CEO recommendations.",
        "secret_exposed": False,
    }


def _hermes_legacy_bridge(settings: SaaSSettings) -> dict[str, Any]:
    return {
        "key": "HermesLegacyBridge",
        "label": "Hermes legacy bridge",
        "category": "legacy_transition",
        "status": "blocked_for_formal_launch" if settings.allow_hermes_adapters else "disabled_transitional_only",
        "interface": "Optional internal transition adapter, not a formal production dependency",
        "owned_by": "legacy Hermes adapter paths only when explicitly enabled for local regression",
        "production_dependency_allowed": False,
        "merchant_visible_allowed": False,
        "allowed_in_environments": ["local_dev_regression_only"],
        "blocked_in_environments": ["staging", "production"],
        "guardrails": _guardrails(
            backend_only=True,
            confirmation=False,
            audit=True,
            memory=False,
            raw_secret=False,
        )
        | {
            "can_bypass_confirmation_center": False,
            "can_be_default_runtime_adapter": False,
            "can_be_credential_source_for_formal_saas": False,
        },
        "audit_events": ["legacy_bridge.blocked", "legacy_bridge.local_regression"],
        "next_action": "Keep Hermes disabled in formal SaaS; use it only for internal shadow comparison if explicitly approved.",
        "secret_exposed": False,
    }


def _guardrails(
    *,
    backend_only: bool,
    confirmation: bool,
    audit: bool,
    memory: bool,
    raw_secret: bool,
) -> dict[str, Any]:
    return {
        "backend_only": backend_only,
        "frontend_gets_raw_secret": raw_secret,
        "runtime_gets_raw_secret": raw_secret,
        "provider_token_stored_in_runtime": False,
        "bypasses_confirmation_center": False,
        "confirmation_required_for_high_risk_action": confirmation,
        "writes_audit_record": audit,
        "may_write_merchant_memory": memory,
        "secret_exposed": False,
    }
