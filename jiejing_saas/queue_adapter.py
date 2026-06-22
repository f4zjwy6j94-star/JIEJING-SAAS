"""Queue adapter contract for local and production Jiejing SaaS workers."""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings


QUEUE_ADAPTERS = [
    {
        "key": "local_worker",
        "label": "Local in-process worker",
        "status": "implemented_for_local_dev",
        "driver_implemented": True,
        "allowed_environments": ["local_dev", "test"],
        "production_allowed": False,
        "supports_distributed_workers": False,
        "supports_dead_letter_queue": False,
        "supports_heartbeat": False,
    },
    {
        "key": "redis_streams",
        "label": "Redis Streams",
        "status": "implemented_for_staging_cutover",
        "driver_implemented": True,
        "allowed_environments": ["staging", "production"],
        "production_allowed": True,
        "supports_distributed_workers": True,
        "supports_dead_letter_queue": True,
        "supports_heartbeat": True,
    },
    {
        "key": "postgres_durable",
        "label": "Postgres durable queue",
        "status": "implemented_for_beta_cutover",
        "driver_implemented": True,
        "allowed_environments": ["staging", "production"],
        "production_allowed": True,
        "supports_distributed_workers": True,
        "supports_dead_letter_queue": True,
        "supports_heartbeat": True,
        "requires_database_engine": "postgres",
    },
    {
        "key": "tencent_cloud_queue",
        "label": "Tencent Cloud queue",
        "status": "contract_reserved_driver_pending",
        "driver_implemented": False,
        "allowed_environments": ["staging", "production"],
        "production_allowed": True,
        "supports_distributed_workers": True,
        "supports_dead_letter_queue": True,
        "supports_heartbeat": True,
    },
    {
        "key": "aliyun_message_queue",
        "label": "Aliyun Message Queue",
        "status": "contract_reserved_driver_pending",
        "driver_implemented": False,
        "allowed_environments": ["staging", "production"],
        "production_allowed": True,
        "supports_distributed_workers": True,
        "supports_dead_letter_queue": True,
        "supports_heartbeat": True,
    },
]


def build_queue_adapter_contract(settings: SaaSSettings) -> dict[str, Any]:
    selected = next((item for item in QUEUE_ADAPTERS if item["key"] == settings.queue_provider), None)
    selected = selected or QUEUE_ADAPTERS[0]

    blockers: list[str] = []
    if settings.is_production_like and not selected.get("production_allowed"):
        blockers.append("selected_queue_adapter_not_allowed_for_production")
    if selected["key"] == "postgres_durable" and settings.database_engine != "postgres":
        blockers.append("postgres_durable_queue_requires_postgres")
    if selected.get("production_allowed") and selected["key"] != "postgres_durable" and not settings.queue_url_configured:
        blockers.append("missing_queue_url")
    if selected["key"] not in {"local_worker", "postgres_durable"} and not selected.get("driver_implemented"):
        blockers.append("cloud_queue_driver_not_implemented")
    if not selected.get("supports_distributed_workers"):
        blockers.append("missing_distributed_worker_support")
    if not selected.get("supports_dead_letter_queue"):
        blockers.append("missing_dead_letter_queue")
    if not selected.get("supports_heartbeat"):
        blockers.append("missing_worker_heartbeat")

    return {
        "contract_version": "2026-05-15-queue-adapter-contract",
        "selected_adapter": selected,
        "available_adapters": QUEUE_ADAPTERS,
        "queue_url_configured": settings.queue_url_configured,
        "worker_contract": {
            "worker_claims_job": True,
            "worker_reports_step_status": True,
            "worker_reports_failure_reason": True,
            "retry_must_be_idempotent": True,
            "high_risk_actions_require_confirmation": True,
            "frontend_never_runs_worker_directly_in_production": True,
        },
        "production_blockers": blockers,
        "secret_exposed": False,
    }
