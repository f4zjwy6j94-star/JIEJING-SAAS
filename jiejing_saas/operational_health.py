"""Deep operational health for Jiejing SaaS.

The public readiness packet already answers product readiness. This module
keeps the ops layer explicit: database live probe, queue stuck/dead-letter
visibility, and worker telemetry. It never returns raw credentials.
"""

from __future__ import annotations

import os
import json
import urllib.request
from typing import Any

from .config import SaaSSettings
from .infrastructure_drivers import run_postgres_live_probe
from .infrastructure_drivers import _redis_live_check
from .repository import SaaSRepository


def build_operational_health(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str | None = None,
    stale_after_seconds: int = 900,
) -> dict[str, Any]:
    database = _database_live_probe(settings, repository)
    queue = (
        repository.queue_health_summary(company_id=company_id, stale_after_seconds=stale_after_seconds)
        if company_id
        else repository.global_queue_health_summary(stale_after_seconds=stale_after_seconds)
    )
    worker = _worker_runtime_status(settings, queue, repository.latest_worker_heartbeat())
    redis = _redis_runtime_probe(settings)
    vault = _vault_runtime_probe(settings)
    blockers = _blockers(settings=settings, database=database, queue=queue, worker=worker)
    if redis.get("status") != "ready":
        blockers.append("queue_live_probe_failed")
    if vault.get("status") != "ready":
        blockers.append("vault_live_probe_failed")
    warnings = _warnings(settings=settings, database=database, queue=queue, worker=worker)
    status = "ready"
    if blockers:
        status = "blocked"
    elif warnings:
        status = "attention_required"
    return {
        "contract_version": "2026-06-17-deep-operational-health",
        "status": status,
        "environment": settings.environment,
        "database_live_probe": database,
        "queue_runtime": queue,
        "worker_runtime": worker,
        "redis_live_probe": redis,
        "vault_live_probe": vault,
        "blockers": blockers,
        "warnings": warnings,
        "secret_exposed": False,
    }


def _redis_runtime_probe(settings: SaaSSettings) -> dict[str, Any]:
    if settings.queue_provider != "redis_streams":
        return {"status": "ready", "required": False, "secret_exposed": False}
    live_check = _redis_live_check(settings)
    return {
        "status": "ready" if live_check.get("status") == "ok" else "blocked",
        "required": True,
        "secret_exposed": False,
    }


def _vault_runtime_probe(settings: SaaSSettings) -> dict[str, Any]:
    if not settings.vault_enabled or settings.vault_provider != "vault":
        return {"status": "ready", "required": False, "secret_exposed": False}
    addr = str(os.environ.get("JIEJING_VAULT_ADDR") or "").rstrip("/")
    token_file = str(os.environ.get("JIEJING_VAULT_TOKEN_FILE") or "")
    try:
        if token_file:
            with open(token_file, "r", encoding="utf-8") as token_handle:
                token = token_handle.read().strip()
        else:
            token = str(os.environ.get("JIEJING_VAULT_TOKEN") or "")
    except OSError:
        token = ""
    if not addr or not token:
        return {"status": "blocked", "required": True, "secret_exposed": False}
    try:
        health_request = urllib.request.Request(f"{addr}/v1/sys/health")
        with urllib.request.urlopen(health_request, timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
        lookup_request = urllib.request.Request(
            f"{addr}/v1/auth/token/lookup-self",
            headers={"X-Vault-Token": token},
        )
        with urllib.request.urlopen(lookup_request, timeout=3) as response:
            lookup = json.loads(response.read().decode("utf-8"))
        ready = bool(
            health.get("initialized") is True
            and health.get("sealed") is False
            and isinstance(lookup.get("data"), dict)
            and lookup.get("data", {}).get("id")
            and lookup.get("data", {}).get("renewable") is True
            and int(lookup.get("data", {}).get("period") or 0) > 0
        )
    except Exception:
        ready = False
    return {
        "status": "ready" if ready else "blocked",
        "required": True,
        "initialized_unsealed": ready,
        "token_authenticated": ready,
        "secret_exposed": False,
    }


def _database_live_probe(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    if settings.database_engine == "postgres" or settings.database_adapter == "postgres-managed":
        probe = run_postgres_live_probe(settings)
        return {
            "status": "ready" if probe.get("status") == "ok" else "blocked",
            "engine": "postgres",
            "probe": probe,
            "secret_exposed": False,
        }
    try:
        counts = repository.system_counts()
    except Exception as exc:  # pragma: no cover - defensive degraded path.
        return {
            "status": "blocked",
            "engine": settings.database_engine,
            "error_type": type(exc).__name__,
            "message": str(exc)[:180],
            "secret_exposed": False,
        }
    return {
        "status": "ready",
        "engine": settings.database_engine,
        "probe": "repository_counts_query",
        "table_count": len(counts),
        "secret_exposed": False,
    }


def _worker_runtime_status(settings: SaaSSettings, queue: dict[str, Any], latest_registered_heartbeat: dict[str, Any]) -> dict[str, Any]:
    restart_count = _optional_int_env("JIEJING_WORKER_RESTART_COUNT", "JIEJING_WORKER_CONTAINER_RESTART_COUNT")
    restart_count_source = "orchestrator_env" if restart_count is not None else "not_connected"
    if restart_count is None and latest_registered_heartbeat.get("restart_count_source") == "application_worker_heartbeat":
        restart_count = _int_or_none(latest_registered_heartbeat.get("restart_count_estimate"))
        if restart_count is not None:
            restart_count_source = "application_worker_heartbeat"
    env_heartbeat_at = (
        os.environ.get("JIEJING_WORKER_LAST_HEARTBEAT_AT")
        or os.environ.get("JIEJING_WORKER_HEARTBEAT_AT")
        or ""
    ).strip()
    latest_job_heartbeat_at = str(queue.get("latest_worker_heartbeat_at") or "")
    registered_heartbeat_at = str(latest_registered_heartbeat.get("heartbeat_at") or "")
    registered_worker_status = str(latest_registered_heartbeat.get("status") or "")
    registered_worker_id = str(latest_registered_heartbeat.get("worker_id") or os.environ.get("JIEJING_WORKER_ID") or "")
    registered_process_started_at = str(latest_registered_heartbeat.get("process_started_at") or "")
    running_count = int((queue.get("counts") or {}).get("running", 0) or 0)
    restart_status = "not_reported"
    configured_restart_warning_threshold = _configured_restart_warning_threshold()
    restart_warning_threshold = _restart_warning_threshold(restart_count_source, configured_restart_warning_threshold)
    if restart_count is not None:
        app_heartbeat_default_observation = (
            restart_count_source == "application_worker_heartbeat" and configured_restart_warning_threshold is None
        )
        if app_heartbeat_default_observation:
            restart_status = "ready"
        else:
            restart_status = "attention_required" if restart_count >= restart_warning_threshold else "ready"
    heartbeat_status = "ready"
    if running_count and not latest_job_heartbeat_at and not env_heartbeat_at and not registered_heartbeat_at:
        heartbeat_status = "missing_running_job_heartbeat"
    elif not running_count and not env_heartbeat_at and not registered_heartbeat_at:
        heartbeat_status = "idle_no_running_jobs"
    return {
        "status": "attention_required"
        if heartbeat_status == "missing_running_job_heartbeat" or restart_status == "attention_required"
        else "ready",
        "queue_provider": settings.queue_provider,
        "worker_id": registered_worker_id,
        "heartbeat_status": heartbeat_status,
        "latest_job_heartbeat_at": latest_job_heartbeat_at,
        "latest_registered_worker_heartbeat_at": registered_heartbeat_at,
        "registered_worker_status": registered_worker_status,
        "registered_process_started_at": registered_process_started_at,
        "env_heartbeat_at": env_heartbeat_at,
        "restart_count": restart_count,
        "restart_count_status": restart_status,
        "restart_count_source": restart_count_source,
        "restart_count_warning_threshold": restart_warning_threshold,
        "restart_count_threshold_configured": configured_restart_warning_threshold is not None,
        "secret_exposed": False,
    }


def _blockers(
    *,
    settings: SaaSSettings,
    database: dict[str, Any],
    queue: dict[str, Any],
    worker: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if database.get("status") != "ready":
        blockers.append("database_live_probe_failed")
    if int(queue.get("stale_running_count") or 0) > 0:
        blockers.append("queue_stale_running_jobs")
    if worker.get("heartbeat_status") == "missing_running_job_heartbeat":
        blockers.append("worker_heartbeat_missing_for_running_job")
    if settings.is_production_like and int((queue.get("counts") or {}).get("dead_letter", 0) or 0) > 0:
        blockers.append("dead_letter_jobs_present")
    return blockers


def _warnings(
    *,
    settings: SaaSSettings,
    database: dict[str, Any],
    queue: dict[str, Any],
    worker: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if int((queue.get("counts") or {}).get("dead_letter", 0) or 0) > 0 and "dead_letter_jobs_present" not in warnings:
        warnings.append("dead_letter_jobs_present")
    if settings.is_production_like and worker.get("restart_count_source") == "not_connected":
        warnings.append("worker_restart_count_not_connected")
    if settings.is_production_like and not worker.get("latest_registered_worker_heartbeat_at") and not worker.get("env_heartbeat_at"):
        warnings.append("worker_runtime_heartbeat_not_seen")
    if worker.get("restart_count_status") == "attention_required":
        warnings.append("worker_restart_count_high")
    if database.get("engine") != "postgres" and settings.is_production_like:
        warnings.append("non_postgres_database_in_production")
    return warnings


def _optional_int_env(*names: str) -> int | None:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or not raw.strip():
            continue
        try:
            return max(0, int(raw))
        except ValueError:
            return None
    return None


def _configured_restart_warning_threshold() -> int | None:
    configured = _optional_int_env("JIEJING_WORKER_RESTART_WARNING_THRESHOLD")
    if configured is not None and configured > 0:
        return configured
    return None


def _restart_warning_threshold(source: str, configured: int | None = None) -> int:
    if configured is not None:
        return configured
    if source == "application_worker_heartbeat":
        return 20
    return 5


def _int_or_none(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
