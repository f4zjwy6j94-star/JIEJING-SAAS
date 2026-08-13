#!/usr/bin/env python3
"""Regression checks for deep operational health readiness."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.operational_health import build_operational_health  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-operational-health-test"
DB = OUT / "saas.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()

    settings = SaaSSettings(
        environment="local_dev",
        session_secret_configured=True,
        session_secret_is_default=False,
        requested_real_platform_writes=False,
        database_engine="sqlite",
        database_url_configured=False,
        database_adapter="sqlite-local",
        queue_provider="local_worker",
        queue_url_configured=False,
        vault_provider="secret_ref_only",
        vault_enabled=False,
        execution_adapter="demo_no_platform_write",
        ebay_oauth_environment="production",
        ebay_client_id="",
        ebay_ru_name="",
        ebay_client_secret_configured=False,
        ebay_account_deletion_endpoint_url="https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion",
        ebay_account_deletion_verification_token_configured=False,
        ebay_access_token_configured=False,
        ebay_refresh_token_configured=False,
        ebay_oauth_live_exchange_enabled=False,
        ebay_token_refresh_live_enabled=False,
        ebay_read_only_live_enabled=False,
        ebay_write_live_enabled=False,
        ebay_draft_save_live_enabled=False,
        allow_hermes_adapters=False,
        cors_origin="*",
        internal_admin_emails=(),
        host="127.0.0.1",
        port=8788,
        db_path=DB,
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
    )
    repository = SaaSRepository(DB, database_engine="sqlite")
    account = repository.create_user_with_company(
        email="operational-health@example.com",
        password="unit-test-password",
        company_name="Operational Health Test",
    )
    company = account["company"]
    user = account["user"]
    store = repository.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "Operational Health Store", "marketplace": "EBAY_US"},
    )
    task = repository.create_task(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="market_report",
        title="Operational health queue job",
        input_data={"source": "unit_test"},
    )
    job = repository.create_queue_job(
        company_id=company["company_id"],
        task_id=task["task_id"],
        job_data={"kind": "workflow_task", "task_id": task["task_id"]},
    )
    heartbeat = repository.record_worker_heartbeat(
        worker_id="worker:test-operational-health",
        status="idle",
        queue_provider=settings.queue_provider,
        process_started_at="2026-06-17T00:00:00+00:00",
        process_id=123,
        details={"source": "unit_test"},
    )
    if not heartbeat.get("heartbeat_at"):
        return fail(f"worker heartbeat should be persisted: {heartbeat}")
    restarted = repository.record_worker_heartbeat(
        worker_id="worker:test-operational-health",
        status="idle",
        queue_provider=settings.queue_provider,
        process_started_at="2026-06-17T00:01:00+00:00",
        process_id=124,
        details={"source": "unit_test_restart"},
    )
    if restarted.get("restart_count_estimate") != 1:
        return fail(f"worker restart estimate should increment when process_started_at changes: {restarted}")

    health = build_operational_health(settings, repository)
    if health.get("database_live_probe", {}).get("status") != "ready":
        return fail(f"sqlite repository probe should be ready: {health}")
    if health.get("queue_runtime", {}).get("counts", {}).get("queued") != 1:
        return fail(f"queue health should expose queued jobs: {health}")
    if health.get("worker_runtime", {}).get("restart_count_source") != "application_worker_heartbeat":
        return fail(f"restart count should come from application worker heartbeat when orchestrator metrics are absent: {health}")
    if health.get("worker_runtime", {}).get("restart_count") != 1:
        return fail(f"changed process_started_at should report one estimated restart: {health}")
    if health.get("worker_runtime", {}).get("restart_count_warning_threshold") != 20:
        return fail(f"application heartbeat restart estimate should use a wider default threshold: {health}")
    if health.get("worker_runtime", {}).get("heartbeat_status") != "ready":
        return fail(f"registered worker heartbeat should make worker status ready: {health}")
    if not health.get("worker_runtime", {}).get("latest_registered_worker_heartbeat_at"):
        return fail(f"worker runtime should expose the registered heartbeat timestamp: {health}")
    if health.get("secret_exposed") is not False:
        return fail("operational health must keep secret_exposed=false")

    readiness = build_product_readiness(settings, repository)
    items = {item["key"]: item for item in readiness.get("items", [])}
    for key in {"database_live_probe", "queue_runtime_health", "worker_runtime_health"}:
        if key not in items:
            return fail(f"readiness should include {key}: {items.keys()}")
    provider_status = readiness.get("provider_status", {}).get("operational_health", {})
    if provider_status.get("queued") != 1 or provider_status.get("worker_restart_count_source") != "application_worker_heartbeat":
        return fail(f"public provider status should summarize operational health: {provider_status}")
    if not provider_status.get("latest_worker_heartbeat_at") or provider_status.get("registered_worker_status") != "idle":
        return fail(f"public provider status should expose worker heartbeat without secrets: {provider_status}")

    for minute in range(2, 23):
        repository.record_worker_heartbeat(
            worker_id="worker:test-operational-health",
            status="idle",
            queue_provider=settings.queue_provider,
            process_started_at=f"2026-06-17T00:{minute:02d}:00+00:00",
            process_id=200 + minute,
            details={"source": "unit_test_planned_restart_estimate"},
        )
    default_high_restart_health = build_operational_health(settings, repository)
    if default_high_restart_health.get("worker_runtime", {}).get("restart_count", 0) < 20:
        return fail(f"test setup should exercise high application heartbeat restart estimates: {default_high_restart_health}")
    if default_high_restart_health.get("worker_runtime", {}).get("restart_count_status") != "ready":
        return fail(f"default application heartbeat restart estimates should remain observational: {default_high_restart_health}")
    if "worker_restart_count_high" in default_high_restart_health.get("warnings", []):
        return fail(f"default application heartbeat restart estimates should not add high-restart warnings: {default_high_restart_health}")

    os.environ["JIEJING_WORKER_RESTART_WARNING_THRESHOLD"] = "1"
    try:
        threshold_health = build_operational_health(settings, repository)
    finally:
        os.environ.pop("JIEJING_WORKER_RESTART_WARNING_THRESHOLD", None)
    if threshold_health.get("worker_runtime", {}).get("restart_count_status") != "attention_required":
        return fail(f"operator-configured restart threshold should still trigger attention: {threshold_health}")

    repository.update_queue_job(
        job_id=job["job_id"],
        company_id=company["company_id"],
        status="dead_letter",
        details={"error": "unit test dead letter"},
    )
    dead_health = build_operational_health(settings, repository)
    if dead_health.get("queue_runtime", {}).get("counts", {}).get("dead_letter") != 1:
        return fail(f"dead letters should be visible in deep health: {dead_health}")
    if "dead_letter_jobs_present" not in dead_health.get("warnings", []):
        return fail(f"dead letters should become an operational warning: {dead_health}")

    print("PASS jiejing_operational_health_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
