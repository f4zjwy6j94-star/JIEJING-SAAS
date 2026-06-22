"""Task-scoped secret grant planning for SaaS provider jobs.

This module does not resolve or read any raw secret. It turns a provider-job
preflight plan into backend-only grant requests, so the SaaS can later ask a
real Vault/KMS for a short-lived credential per task and per provider job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def build_task_secret_grant_plan(
    *,
    task: dict[str, Any],
    provider_job_plan: dict[str, Any],
    secret_refs: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    vault_status: dict[str, Any],
) -> dict[str, Any]:
    provider_steps = provider_job_plan.get("provider_steps") if isinstance(provider_job_plan.get("provider_steps"), list) else []
    refs_by_purpose = _refs_by_purpose(secret_refs=secret_refs, connections=connections)
    grant_requests: list[dict[str, Any]] = []
    for step in provider_steps:
        purpose = str(step.get("required_secret_purpose") or "").strip()
        if not purpose:
            continue
        matching_ref = _choose_secret_ref(
            purpose=purpose,
            provider_family=str(step.get("provider_family") or ""),
            refs_by_purpose=refs_by_purpose,
        )
        grant_requests.append(
            _build_grant_request(
                task=task,
                provider_step=step,
                purpose=purpose,
                secret_ref=matching_ref,
                vault_status=vault_status,
            )
        )

    ready_contract_count = sum(1 for item in grant_requests if item.get("status") == "grant_contract_ready")
    blocked_count = sum(1 for item in grant_requests if str(item.get("status") or "").startswith("blocked"))
    return {
        "task_id": task.get("task_id"),
        "store_id": task.get("store_id"),
        "company_id": task.get("company_id"),
        "grant_request_count": len(grant_requests),
        "grant_contract_ready_count": ready_contract_count,
        "blocked_count": blocked_count,
        "secret_purposes_required": sorted({str(item.get("required_secret_purpose")) for item in grant_requests}),
        "grant_requests": grant_requests,
        "vault_status": {
            "provider": vault_status.get("provider"),
            "enabled": vault_status.get("enabled"),
            "secret_ref_only": vault_status.get("secret_ref_only"),
            "can_store_raw_secret": vault_status.get("can_store_raw_secret"),
            "production_ready": vault_status.get("production_ready"),
        },
        "rules": {
            "task_scoped_secret_lease_required": True,
            "one_provider_job_one_grant": True,
            "grant_ttl_seconds_max": 900,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "database_stores_raw_secret": False,
            "real_provider_call_requires_live_vault_resolution": True,
        },
        "blocked_actions": [
            "return_raw_secret_to_frontend",
            "pass_customer_refresh_token_to_runtime",
            "reuse_a_secret_grant_across_tasks",
            "call_live_provider_without_vault_resolution",
            "use_provider_job_secret_for_platform_write",
        ],
        "summary": _summary(ready_contract_count=ready_contract_count, blocked_count=blocked_count, grant_requests=grant_requests),
        "live_secret_resolved": False,
        "raw_secret_returned": False,
        "frontend_gets_raw_secret": False,
        "runtime_gets_raw_secret": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _build_grant_request(
    *,
    task: dict[str, Any],
    provider_step: dict[str, Any],
    purpose: str,
    secret_ref: dict[str, Any] | None,
    vault_status: dict[str, Any],
) -> dict[str, Any]:
    timeout_seconds = int(provider_step.get("timeout_seconds") or 300)
    ttl_seconds = min(900, max(120, timeout_seconds + 60))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    status = "grant_contract_ready" if secret_ref else "blocked_missing_secret_ref"
    live_resolution_ready = bool(secret_ref and vault_status.get("production_ready") and not vault_status.get("secret_ref_only"))
    if secret_ref and not live_resolution_ready:
        live_blockers = ["managed_vault_not_enabled"]
    elif not secret_ref:
        live_blockers = ["missing_secret_ref"]
    else:
        live_blockers = []
    return {
        "provider_job_key": provider_step.get("provider_job_key"),
        "provider_family": provider_step.get("provider_family"),
        "queue": provider_step.get("queue"),
        "task_type": provider_step.get("task_type"),
        "required_secret_purpose": purpose,
        "status": status,
        "secret_ref": secret_ref.get("secret_ref") if secret_ref else None,
        "secret_provider": secret_ref.get("provider") if secret_ref else None,
        "secret_ref_status": secret_ref.get("status") if secret_ref else None,
        "grant_id": _grant_id(
            task_id=str(task.get("task_id") or ""),
            provider_job_key=str(provider_step.get("provider_job_key") or ""),
            secret_ref=str(secret_ref.get("secret_ref") if secret_ref else "missing"),
        ),
        "lease": {
            "ttl_seconds": ttl_seconds,
            "expires_at": expires_at.isoformat(),
            "reuse_allowed": False,
            "revocation_required_after_job": True,
        },
        "allowed_scope": {
            "company_id": task.get("company_id"),
            "store_id": task.get("store_id"),
            "task_id": task.get("task_id"),
            "provider_job_key": provider_step.get("provider_job_key"),
            "source_record_type": provider_step.get("source_record_type"),
            "output_packet": provider_step.get("output_packet"),
        },
        "runtime_handoff": {
            "runtime_receives_grant_id_only": True,
            "runtime_gets_raw_secret": False,
            "provider_job_gets_backend_scoped_credential": live_resolution_ready,
        },
        "backend_resolution": {
            "live_resolution_ready": live_resolution_ready,
            "blocked_by": live_blockers,
            "raw_secret_returned": False,
            "audit_required": True,
        },
        "queueable_when_inputs_ready": bool(provider_step.get("queueable")) and bool(secret_ref),
        "live_provider_call_allowed": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _refs_by_purpose(*, secret_refs: list[dict[str, Any]], connections: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in secret_refs:
        purpose = str(item.get("purpose") or "").strip()
        if purpose:
            grouped.setdefault(purpose, []).append(item)
    for connection in connections:
        secret_ref = connection.get("secret_ref")
        if not secret_ref:
            continue
        purpose = str(connection.get("purpose") or connection.get("connection_type") or "platform_connection").strip()
        grouped.setdefault(purpose, []).append(
            {
                "secret_ref": secret_ref,
                "provider": connection.get("platform"),
                "purpose": purpose,
                "status": connection.get("status"),
                "company_id": connection.get("company_id"),
                "store_id": connection.get("store_id"),
                "secret_exposed": False,
            }
        )
    return grouped


def _choose_secret_ref(
    *,
    purpose: str,
    provider_family: str,
    refs_by_purpose: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    if refs := refs_by_purpose.get(purpose):
        return refs[0]
    fallback_purposes = []
    if provider_family in {"sales_channel", "ebay"}:
        fallback_purposes = ["platform_connection", "oauth", "ebay_refresh_token"]
    elif provider_family in {"ai_model", "model"}:
        fallback_purposes = ["model_api_key"]
    elif provider_family in {"research_tool", "public_search"}:
        fallback_purposes = ["public_search_api_key"]
    elif provider_family in {"creative_tool", "media"}:
        fallback_purposes = ["media_generation_api_key"]
    elif provider_family in {"sourcing_channel", "sourcing"}:
        fallback_purposes = ["sourcing_api_secret"]
    elif provider_family in {"fulfillment_channel", "logistics"}:
        fallback_purposes = ["logistics_api_secret"]
    for fallback in fallback_purposes:
        if refs := refs_by_purpose.get(fallback):
            return refs[0]
    return None


def _grant_id(*, task_id: str, provider_job_key: str, secret_ref: str) -> str:
    safe_job_key = provider_job_key.replace(".", "_").replace("/", "_")
    safe_ref = secret_ref.replace(".", "_").replace("/", "_")
    return f"grant_{task_id}_{safe_job_key}_{safe_ref}"[:180]


def _summary(*, ready_contract_count: int, blocked_count: int, grant_requests: list[dict[str, Any]]) -> str:
    if not grant_requests:
        return "This task has no provider jobs that require secrets yet."
    if blocked_count:
        missing = [
            str(item.get("required_secret_purpose"))
            for item in grant_requests
            if item.get("status") == "blocked_missing_secret_ref"
        ]
        return f"{ready_contract_count} secret grants have references; {blocked_count} are blocked by missing secret refs: {', '.join(sorted(set(missing)))}."
    return f"All {ready_contract_count} provider secret grants have task-scoped contracts. Live resolution still depends on managed Vault/KMS."
