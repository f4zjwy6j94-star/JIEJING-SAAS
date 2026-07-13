#!/usr/bin/env python3
"""Regression checks for managed Postgres/Redis/Vault readiness cutover."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository, SaaSSettings, build_product_readiness  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.queue_plan import build_queue_plan  # noqa: E402
from jiejing_saas.vault_adapter import build_vault_adapter_contract  # noqa: E402


OUT = ROOT / "output" / "jiejing-managed-infra-readiness-test"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_DATABASE_ENGINE",
    "JIEJING_DATABASE_ADAPTER",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
    "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
    "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED",
    "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_PROVIDER_METRICS_ENABLED",
    "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED",
    "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED",
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
    "JIEJING_EBAY_WRITE_LIVE",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    db_path = OUT / "readiness.sqlite"
    runtime_db_path = OUT / "runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "staging-managed-readiness-secret-long-enough",
                "JIEJING_CORS_ORIGIN": "https://mentioned-shake-inter-critical.trycloudflare.com",
                "JIEJING_DATABASE_ENGINE": "postgres",
                "JIEJING_DATABASE_ADAPTER": "postgres-managed",
                "JIEJING_DATABASE_URL": "postgresql://jiejing:super-secret-db@postgres:5432/jiejing",
                "JIEJING_QUEUE_PROVIDER": "redis_streams",
                "JIEJING_QUEUE_URL": "redis://:super-secret-redis@redis:6379/0",
                "JIEJING_VAULT_ENABLED": "true",
                "JIEJING_VAULT_PROVIDER": "vault",
                "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
                "JIEJING_VAULT_ADDR": "http://vault:8200",
                "JIEJING_VAULT_TOKEN": "super-secret-vault-token",
                "JIEJING_VAULT_MOUNT": "secret",
                "JIEJING_VAULT_KEYSPACE": "jiejing-staging",
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": "ap-guangzhou",
                "JIEJING_CLS_LOGSET_ID": "logset-staging",
                "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
                "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
                "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "true",
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "true",
                "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "true",
                "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_PROVIDER_METRICS_ENABLED": "true",
                "JIEJING_PROVIDER_LATENCY_ALERTS_CONFIGURED": "true",
                "JIEJING_PROVIDER_COST_ALERTS_CONFIGURED": "true",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "true",
                "JIEJING_EBAY_WRITE_LIVE": "true",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
            }
        )
        settings = SaaSSettings.from_env(
            db_path=db_path,
            runtime_db_path=runtime_db_path,
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        repo = SaaSRepository(settings.db_path, database_engine="sqlite")
        repo.initialize()
        queue_plan = build_queue_plan(settings, repo)
        vault_adapter = build_vault_adapter_contract(settings)
        readiness = build_product_readiness(settings, repo)
        launch_gate = build_commercial_launch_gate(settings, repo)
    finally:
        _restore_env(previous)

    dumped = json.dumps(
        {"queue_plan": queue_plan, "vault_adapter": vault_adapter, "readiness": readiness, "launch_gate": launch_gate},
        ensure_ascii=False,
    )
    for forbidden in ("super-secret-db", "super-secret-redis", "super-secret-vault-token"):
        if forbidden in dumped:
            return fail(f"managed infra readiness leaked secret marker {forbidden}")

    if queue_plan.get("worker_lifecycle_shape_ready") is not True:
        return fail("Redis Streams should satisfy worker lifecycle readiness")
    if queue_plan.get("distributed_queue_shape_ready") is not True:
        return fail("Redis Streams should expose distributed queue readiness")
    if queue_plan.get("production_blockers"):
        return fail(f"Redis Streams queue plan should not keep production blockers: {queue_plan.get('production_blockers')}")

    if vault_adapter.get("live_adapter_implemented") is not True:
        return fail("HashiCorp Vault live resolver should be recognized as implemented when configured")
    if vault_adapter.get("can_store_raw_secret") is not True:
        return fail("Configured backend Vault resolver should allow backend-only secret storage")
    if vault_adapter.get("contract_ready") is not True:
        return fail("Configured backend Vault resolver should satisfy the Vault contract readiness field")
    if vault_adapter.get("production_blockers"):
        return fail(f"staging Vault contract should not keep production blockers: {vault_adapter.get('production_blockers')}")

    readiness_items = {item.get("key"): item for item in readiness.get("items") or []}
    if readiness_items.get("database_adapter_contract", {}).get("status") != "managed_adapter_live":
        return fail("readiness should not keep stale managed database adapter next actions after Postgres cutover")
    if readiness_items.get("queue_adapter_contract", {}).get("status") != "managed_queue_live":
        return fail("readiness should not keep stale queue adapter next actions after Redis cutover")
    if readiness_items.get("queue_worker_plan", {}).get("status") != "ready":
        return fail("readiness should not keep the old queue_worker_plan blocker after Redis cutover")
    if readiness_items.get("vault_adapter_contract", {}).get("status") != "adapter_contract_ready":
        return fail("readiness should not keep the old Vault adapter blocker after live resolver configuration")
    if readiness_items.get("execution_service", {}).get("status") != "confirmation_gated_real_write_ready":
        return fail("readiness should show real writes as confirmation-gated when all live-write switches are enabled")
    if readiness_items.get("execution_service", {}).get("severity") != "info":
        return fail("confirmation-gated real writes should be production-safe info, not a warning")
    for expected_blocker in ("backup_restore", "billing_quota", "model_value_proof"):
        if readiness_items.get(expected_blocker, {}).get("severity") != "blocker":
            return fail(f"{expected_blocker} must remain a paid-launch blocker")
    if readiness.get("production_ready") is not False:
        return fail("managed infra cutover alone must not claim paid production readiness")
    if readiness.get("secret_exposed") is not False:
        return fail("readiness must not expose secrets")
    launch_groups = {item.get("key"): item for item in launch_gate.get("groups") or []}
    if launch_groups.get("managed_secret_boundary", {}).get("status") != "ready":
        return fail("commercial launch gate should recognize the configured managed Vault boundary")
    if launch_groups.get("monitoring_alerting", {}).get("status") != "ready":
        return fail("commercial launch gate should recognize the monitoring alert contract")
    for expected_blocked in ("backup_restore", "billing_quota", "model_agent_value"):
        if launch_groups.get(expected_blocked, {}).get("status") != "blocked":
            return fail(f"{expected_blocked} must remain blocked in this managed infra cutover test")

    print(
        json.dumps(
            {
                "queue_worker_plan": readiness_items.get("queue_worker_plan"),
                "vault_adapter_contract": readiness_items.get("vault_adapter_contract"),
                "remaining_blocker_count": readiness.get("blocker_count"),
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("PASS jiejing_managed_infra_readiness_cutover")
    return 0


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
