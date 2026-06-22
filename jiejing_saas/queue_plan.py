"""Queue and worker production readiness plan for Jiejing SaaS."""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .queue_adapter import build_queue_adapter_contract
from .repository import SaaSRepository


WORKFLOW_JOB_STATES = ["queued", "running", "completed", "failed", "cancelled"]


QUEUE_CAPABILITY_CONTRACT = [
    {
        "key": "merchant_request_acceptance",
        "label": "Accept merchant request without blocking the browser",
        "current_status": "ready",
    },
    {
        "key": "split_steps",
        "label": "Split one product workflow into traceable role steps",
        "current_status": "ready",
    },
    {
        "key": "retry_cancel",
        "label": "Retry or cancel a queued job with audit records",
        "current_status": "ready",
    },
    {
        "key": "timeline",
        "label": "Show task, queue, step, report, confirmation and audit timeline",
        "current_status": "ready",
    },
    {
        "key": "distributed_workers",
        "label": "Run multiple cloud workers safely",
        "current_status": "pending_cloud_queue",
    },
    {
        "key": "dead_letter_queue",
        "label": "Move repeated failures into a dead-letter queue",
        "current_status": "pending_cloud_queue",
    },
    {
        "key": "worker_heartbeat",
        "label": "Detect stuck workers and timed-out jobs",
        "current_status": "pending_cloud_queue",
    },
]


PRODUCTION_QUEUE_STEPS = [
    {
        "step": "choose_queue_provider",
        "label": "Choose Redis or managed cloud queue",
        "recommended_targets": ["Tencent Cloud TDMQ/CMQ", "Aliyun Message Queue", "Redis Streams"],
    },
    {
        "step": "worker_service",
        "label": "Run Jiejing Runtime workers as cloud services",
        "required": ["worker_id", "heartbeat", "max_concurrency", "role_step_timeout", "graceful_shutdown"],
    },
    {
        "step": "retry_policy",
        "label": "Define retry and dead-letter rules",
        "required": ["max_attempts", "retry_backoff", "dead_letter_queue", "merchant_visible_failure_reason"],
    },
    {
        "step": "idempotency",
        "label": "Make execution idempotent",
        "why": "A retried job must not duplicate a listing publish, refund, procurement payment or buyer message.",
    },
    {
        "step": "monitoring",
        "label": "Monitor latency, failures and stuck jobs",
        "required": ["queue_depth", "oldest_job_age", "failure_rate", "worker_health", "step_timeout_count"],
    },
]


def build_queue_plan(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    status_counts = repository.queue_status_counts()
    adapter_contract = build_queue_adapter_contract(settings)
    selected_adapter = adapter_contract.get("selected_adapter", {})
    local_provider = settings.queue_provider in {"local_inline", "local_worker"}
    postgres_durable_provider = settings.queue_provider == "postgres_durable"
    production_blockers: list[str] = []
    if local_provider:
        production_blockers.append("local_queue_provider")
    if not settings.queue_url_configured and not local_provider and not postgres_durable_provider:
        production_blockers.append("missing_queue_url")
    if postgres_durable_provider and settings.database_engine != "postgres":
        production_blockers.append("postgres_durable_queue_requires_postgres")
    if local_provider:
        production_blockers.extend(
            [
                "missing_distributed_workers",
                "missing_dead_letter_queue",
                "missing_worker_heartbeat",
                "missing_cloud_timeout_reaper",
            ]
        )
    for blocker in adapter_contract.get("production_blockers") or []:
        if blocker not in production_blockers:
            production_blockers.append(blocker)
    distributed_queue_shape_ready = bool(
        not local_provider
        and (settings.queue_url_configured or postgres_durable_provider)
        and selected_adapter.get("driver_implemented")
        and selected_adapter.get("supports_distributed_workers")
        and selected_adapter.get("supports_dead_letter_queue")
        and selected_adapter.get("supports_heartbeat")
        and (not postgres_durable_provider or settings.database_engine == "postgres")
    )
    worker_lifecycle_shape_ready = bool(settings.queue_provider == "local_worker" or distributed_queue_shape_ready)

    return {
        "plan_version": "2026-05-15-queue-worker-boundary",
        "adapter_contract": adapter_contract,
        "queue_provider": settings.queue_provider,
        "queue_url_configured": settings.queue_url_configured,
        "local_queue_shape_ready": settings.queue_provider == "local_worker",
        "postgres_durable_queue_ready": bool(postgres_durable_provider and distributed_queue_shape_ready),
        "distributed_queue_shape_ready": distributed_queue_shape_ready,
        "worker_lifecycle_shape_ready": worker_lifecycle_shape_ready,
        "production_queue_ready": not production_blockers and settings.is_production_like,
        "production_blockers": production_blockers,
        "job_status_counts": {state: int(status_counts.get(state, 0)) for state in WORKFLOW_JOB_STATES},
        "capability_contract": QUEUE_CAPABILITY_CONTRACT,
        "production_steps": PRODUCTION_QUEUE_STEPS,
        "merchant_visible_rules": {
            "show_waiting": True,
            "show_running": True,
            "show_failed_with_reason": True,
            "allow_retry": True,
            "never_hide_stuck_jobs": True,
        },
        "high_risk_execution_rule": {
            "queue_can_prepare": True,
            "queue_cannot_execute_high_risk_without_confirmation": True,
            "execution_service_requires_approved_confirmation": True,
        },
        "secret_exposed": False,
    }
