#!/usr/bin/env python3
"""Regression checks for Tencent SSM/KMS, CLS and COS readiness wiring."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.backup_plan import build_backup_plan  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.monitoring import build_monitoring_status  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.vault_adapter import build_vault_adapter_contract  # noqa: E402
import jiejing_saas.vault_secret_resolver as vault_resolver_module  # noqa: E402


OUT = ROOT / "output" / "jiejing-tencent-cloud-integrations-test"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_SAAS_SESSION_SECRET",
    "JIEJING_DATABASE_ENGINE",
    "JIEJING_DATABASE_ADAPTER",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_TENCENT_REGION",
    "JIEJING_TENCENT_SECRET_ID",
    "JIEJING_TENCENT_SECRET_KEY",
    "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED",
    "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED",
    "JIEJING_TENCENT_SSM_KEYSPACE",
    "JIEJING_BACKUP_STORAGE_PROVIDER",
    "JIEJING_BACKUP_POLICY_CONFIGURED",
    "JIEJING_RESTORE_DRILL_LAST_AT",
    "JIEJING_BACKUP_ALERTS_CONFIGURED",
    "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
    "JIEJING_COS_BACKUP_ENABLED",
    "JIEJING_COS_REGION",
    "JIEJING_COS_BUCKET",
    "JIEJING_COS_PREFIX",
    "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED",
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_CLS_LIVE_PROBE_REQUIRED",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED",
    "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
    "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED",
    "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED",
    "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    db_path = OUT / "integrations.sqlite"
    db_path.unlink(missing_ok=True)
    original_sdk_available = vault_resolver_module._tencent_ssm_sdk_available
    try:
        vault_resolver_module._tencent_ssm_sdk_available = lambda: True
        _clear_env()
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "staging-tencent-integrations-secret-long-enough",
                "JIEJING_DATABASE_ENGINE": "postgres",
                "JIEJING_DATABASE_ADAPTER": "postgres-managed",
                "JIEJING_DATABASE_URL": "postgresql://jiejing:db-secret@postgres:5432/jiejing",
                "JIEJING_QUEUE_PROVIDER": "redis_streams",
                "JIEJING_QUEUE_URL": "redis://:redis-secret@redis:6379/0",
                "JIEJING_VAULT_ENABLED": "true",
                "JIEJING_VAULT_PROVIDER": "tencent_ssm",
                "JIEJING_TENCENT_REGION": "ap-guangzhou",
                "JIEJING_TENCENT_SECRET_ID": "TENCENT-ID-MUST-NOT-LEAK",
                "JIEJING_TENCENT_SECRET_KEY": "TENCENT-KEY-MUST-NOT-LEAK",
                "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED": "true",
                "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED": "true",
                "JIEJING_TENCENT_SSM_KEYSPACE": "jiejing-staging",
                "JIEJING_BACKUP_STORAGE_PROVIDER": "cos",
                "JIEJING_BACKUP_POLICY_CONFIGURED": "true",
                "JIEJING_RESTORE_DRILL_LAST_AT": "2026-05-18T16:55:00+08:00",
                "JIEJING_BACKUP_ALERTS_CONFIGURED": "true",
                "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "true",
                "JIEJING_COS_BACKUP_ENABLED": "true",
                "JIEJING_COS_REGION": "ap-guangzhou",
                "JIEJING_COS_BUCKET": "jiejing-private-backups-1250000000",
                "JIEJING_COS_PREFIX": "jiejing/staging/backups",
                "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED": "true",
                "JIEJING_COS_BACKUP_LAST_SUCCESS_AT": "2026-05-18T16:56:00+08:00",
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": "ap-guangzhou",
                "JIEJING_CLS_LOGSET_ID": "logset-jiejing",
                "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
                "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
                "JIEJING_CLS_LIVE_PROBE_REQUIRED": "true",
                "JIEJING_CLS_LIVE_PROBE_LAST_AT": "2026-05-18T16:57:00+08:00",
                "JIEJING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED": "true",
                "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED": "true",
                "JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED": "true",
                "JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_CLOUD_BILLING_INCIDENT_RUNBOOK_PUBLISHED": "true",
                "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED": "true",
            }
        )
        settings = _settings(db_path)
        repo = SaaSRepository(settings.db_path, database_engine="sqlite")
        repo.initialize()

        backup = build_backup_plan(settings, repo)
        monitoring = build_monitoring_status(settings, repo)
        vault_adapter = build_vault_adapter_contract(settings)
        launch_gate = build_commercial_launch_gate(settings, repo)
    finally:
        vault_resolver_module._tencent_ssm_sdk_available = original_sdk_available
        _restore_env(previous)

    dumped = json.dumps(
        {"backup": backup, "monitoring": monitoring, "vault_adapter": vault_adapter, "launch_gate": launch_gate},
        ensure_ascii=False,
    )
    for forbidden in ("db-secret", "redis-secret", "TENCENT-ID-MUST-NOT-LEAK", "TENCENT-KEY-MUST-NOT-LEAK"):
        if forbidden in dumped:
            return fail(f"Tencent integration status leaked secret marker {forbidden}")

    if vault_adapter.get("live_adapter_implemented") is not True:
        return fail("Tencent SSM/KMS adapter should be recognized as a live managed secret adapter")
    if vault_adapter.get("can_store_raw_secret") is not True:
        return fail("Tencent SSM/KMS adapter should allow backend-only secret storage")
    if backup.get("backup_ready_for_paid_launch") is not True:
        return fail(f"COS backup plan should be ready when managed policy and restore drill are configured: {backup.get('blockers')}")
    if backup.get("object_storage", {}).get("target_ready") is not True:
        return fail("COS backup target should be ready when bucket, region and probe are configured")
    if monitoring.get("production_monitoring_ready") is not True:
        return fail(f"CLS monitoring should be ready when logset/topic and alert policy are configured: {monitoring.get('current_blockers')}")
    if monitoring.get("cloud_monitoring", {}).get("target_ready") is not True:
        return fail("CLS target should be ready")
    groups = {item.get("key"): item for item in launch_gate.get("groups") or []}
    if groups.get("monitoring_alerting", {}).get("status") != "ready":
        return fail("commercial launch gate should require and recognize the Tencent CLS monitoring target")

    print(
        json.dumps(
            {
                "vault_adapter": {
                    "selected": vault_adapter.get("selected_adapter", {}).get("key"),
                    "live_adapter_implemented": vault_adapter.get("live_adapter_implemented"),
                },
                "cos": backup.get("object_storage"),
                "cls": monitoring.get("cloud_monitoring"),
                "secret_exposed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("PASS jiejing_tencent_cloud_integrations")
    return 0


def _settings(db_path: Path) -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
