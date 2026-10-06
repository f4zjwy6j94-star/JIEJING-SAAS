#!/usr/bin/env python3
"""Staging infrastructure gate for Jiejing SaaS.

This gate verifies that the repo is prepared for the next infrastructure step:
Postgres migration rehearsal, Redis queue provisioning, repository/worker
runtime cutover code, and honest readiness that still blocks paid launch until
dependencies, live probes, Vault/KMS, OAuth, monitoring and billing are ready.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository, SaaSSettings, build_product_readiness  # noqa: E402
from jiejing_saas.database_plan import CRITICAL_INDEXES, CRITICAL_TABLES  # noqa: E402
from jiejing_saas.infrastructure_drivers import POSTGRES_MIGRATION_MANIFEST, build_infrastructure_driver_status  # noqa: E402
from jiejing_sqlite_to_postgres_rehearsal import generate_rehearsal  # noqa: E402


OUT = ROOT / "output" / "jiejing-infrastructure-stage-gate"
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
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_ALLOW_HERMES_ADAPTERS",
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
    "JIEJING_BACKUP_POLICY_CONFIGURED",
    "JIEJING_RESTORE_DRILL_LAST_AT",
    "JIEJING_BACKUP_ALERTS_CONFIGURED",
    "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
    "JIEJING_BILLING_PROVIDER",
    "JIEJING_BILLING_WEBHOOK_CONFIGURED",
    "JIEJING_BILLING_PLANS_PUBLISHED",
    "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
    "JIEJING_MODEL_PROVIDER",
    "JIEJING_MODEL_DISABLE_LIVE",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        checks = [
            _check_staging_infra_compose(),
            _check_staging_infra_env_example(),
            _check_runtime_driver_dependency_shape(),
            _check_postgres_migration_shape(),
            _check_sqlite_to_postgres_rehearsal_tool(),
            _check_managed_readiness_stays_blocked_until_drivers_exist(),
        ]
    finally:
        _restore_env(previous)

    failed = [item for item in checks if not item["pass"]]
    summary = {
        "product": "Jiejing SaaS",
        "gate": "infrastructure_stage_gate",
        "status": "pass" if not failed else "failed",
        "checks": checks,
        "ready_for_postgres_migration_rehearsal": not failed,
        "ready_for_paid_commercial_launch": False,
        "next_driver_work": [
            "install_runtime_driver_dependencies_in_staging_image",
            "run_sqlite_to_postgres_data_migration_rehearsal",
            "run_live_postgres_and_redis_driver_probes",
            "configure_managed_backup_policy_and_restore_drill",
            "configure_billing_provider_webhook_and_quota_enforcement",
            "prove_market_and_listing_reports_with_live_model_over_sanitized_packets",
            "switch_public_staging_to_managed_database_and_redis_after_live_probe",
        ],
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    output_path = OUT / "latest.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output_path}")
    return 0 if not failed else 1


def _check_staging_infra_compose() -> dict[str, Any]:
    path = ROOT / "deploy" / "docker-compose.staging-infra.yml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    required = [
        "postgres:16-alpine",
        "redis:7-alpine",
        "jiejing-db-migrate",
        "pg_isready",
        "001_initial_schema_postgres.sql",
        "service_healthy",
        "service_completed_successfully",
        "healthcheck:",
        "jiejing-saas.infra.env",
        "jiejing-worker:",
        "tools/jiejing_worker_cli.py",
    ]
    missing = [marker for marker in required if marker not in text]
    return {
        "key": "staging_infra_compose",
        "pass": not missing,
        "path": str(path.relative_to(ROOT)),
        "missing": missing,
    }


def _check_staging_infra_env_example() -> dict[str, Any]:
    path = ROOT / "deploy" / "jiejing-saas.infra.env.example"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    required = [
        "JIEJING_SAAS_ENV=staging",
        "JIEJING_DATABASE_ENGINE=postgres",
        "JIEJING_DATABASE_ADAPTER=postgres-managed",
        "JIEJING_DATABASE_URL=postgresql://",
        "JIEJING_QUEUE_PROVIDER=redis_streams",
        "JIEJING_QUEUE_URL=redis://",
        "JIEJING_VAULT_ENABLED=true",
        "JIEJING_EBAY_READ_ONLY_LIVE=true",
        "JIEJING_ENABLE_HERMES_EBAY_BRIDGE=false",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES=false",
    ]
    forbidden = [
        "JIEJING_ALLOW_HERMES_ADAPTERS=true",
        "JIEJING_ENABLE_REAL_PLATFORM_WRITES=true",
        "JIEJING_EBAY_ACCESS_TOKEN=live_",
        "JIEJING_EBAY_REFRESH_TOKEN=v^",
    ]
    missing = [marker for marker in required if marker not in text]
    present_forbidden = [marker for marker in forbidden if marker in text]
    return {
        "key": "staging_infra_env_example",
        "pass": not missing and not present_forbidden,
        "path": str(path.relative_to(ROOT)),
        "missing": missing,
        "forbidden": present_forbidden,
        "secret_exposed": False,
    }


def _check_runtime_driver_dependency_shape() -> dict[str, Any]:
    requirements = ROOT / "requirements.saas.txt"
    dockerfile = ROOT / "Dockerfile.saas"
    requirements_text = requirements.read_text(encoding="utf-8") if requirements.exists() else ""
    dockerfile_text = dockerfile.read_text(encoding="utf-8") if dockerfile.exists() else ""
    requirements_copy_index = dockerfile_text.find("COPY requirements.saas.lock.txt /app/requirements.saas.lock.txt")
    pip_install_index = dockerfile_text.find("RUN pip install --no-cache-dir --no-index /wheels/*.whl")
    source_copy_index = dockerfile_text.find("COPY . /app")
    required = {
        "requirements_psycopg": "psycopg[binary]" in requirements_text,
        "requirements_redis": "redis" in requirements_text,
        "docker_installs_requirements": "pip install --no-cache-dir --no-index /wheels/*.whl" in dockerfile_text,
        "docker_requirements_cache_before_source_copy": (
            requirements_copy_index >= 0
            and pip_install_index > requirements_copy_index
            and source_copy_index > pip_install_index
        ),
        "docker_uses_staging_pip_mirror": "PIP_INDEX_URL=https://mirrors.tencent.com/pypi/simple/" in dockerfile_text,
        "docker_compiles_worker_cli": "tools/jiejing_worker_cli.py" in dockerfile_text,
        "docker_compiles_driver": "jiejing_saas/infrastructure_drivers.py" in dockerfile_text,
        "docker_compiles_postgres_runtime": "jiejing_saas/postgres_repository_runtime.py" in dockerfile_text,
        "docker_compiles_redis_runtime": "jiejing_saas/redis_queue_runtime.py" in dockerfile_text,
        "docker_compiles_backup_plan": "jiejing_saas/backup_plan.py" in dockerfile_text,
        "docker_compiles_billing_plan": "jiejing_saas/billing_plan.py" in dockerfile_text,
        "docker_compiles_model_value_gate": "jiejing_saas/model_value_gate.py" in dockerfile_text,
    }
    return {
        "key": "runtime_driver_dependency_shape",
        "pass": all(required.values()),
        "expected": required,
        "requirements_path": str(requirements.relative_to(ROOT)),
        "dockerfile_path": str(dockerfile.relative_to(ROOT)),
    }


def _check_postgres_migration_shape() -> dict[str, Any]:
    migration_root = ROOT / "jiejing_saas" / "migrations"
    migration_paths = [spec.path for spec in POSTGRES_MIGRATION_MANIFEST]
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in migration_paths
        if path.exists()
    )
    missing_tables = [table for table in CRITICAL_TABLES if f"create table if not exists {table}" not in text]
    missing_indexes = [index for index in CRITICAL_INDEXES if f"create index if not exists {index}" not in text]
    return {
        "key": "postgres_migration_shape",
        "pass": all(path.exists() for path in migration_paths) and not missing_tables and not missing_indexes,
        "path": str(migration_root.relative_to(ROOT)),
        "migration_paths": [str(path.relative_to(ROOT)) for path in migration_paths],
        "missing_migration_files": [str(path.relative_to(ROOT)) for path in migration_paths if not path.exists()],
        "missing_tables": missing_tables,
        "missing_indexes": missing_indexes,
    }


def _check_sqlite_to_postgres_rehearsal_tool() -> dict[str, Any]:
    db_path = OUT / "sqlite-to-postgres-gate-fixture.sqlite"
    out_sql = OUT / "sqlite-to-postgres-gate-fixture.sql"
    summary_path = OUT / "sqlite-to-postgres-gate-fixture.json"
    for path in (db_path, out_sql, summary_path):
        path.unlink(missing_ok=True)
    repo = SaaSRepository(db_path)
    fixture = repo.create_user_with_company(
        email="infra-gate-migration@jiejing.local",
        password="local-infra-gate-password",
        company_name="Jiejing Infra Gate Migration",
    )
    user = fixture["user"]
    company = fixture["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "northvalesource staging", "marketplace": "EBAY_US"},
    )
    repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "created",
            "resource_count": 6,
            "sections": [{"resource": "store_profile", "source_type": "official_api"}],
        },
    )
    summary = generate_rehearsal(sqlite_path=db_path, out_sql_path=out_sql, summary_path=summary_path)
    sql = out_sql.read_text(encoding="utf-8") if out_sql.exists() else ""
    expected = {
        "status_ready": summary.get("status") == "ready_for_isolated_postgres_import",
        "has_company_rows": int(summary.get("table_counts", {}).get("companies") or 0) >= 1,
        "has_packet_rows": int(summary.get("table_counts", {}).get("platform_data_packets") or 0) >= 1,
        "casts_jsonb": "::jsonb" in sql,
        "append_safe": "on conflict do nothing" in sql,
        "does_not_print_rows": summary.get("raw_rows_printed") is False,
        "no_secret_exposure": summary.get("secret_exposed") is False,
    }
    return {
        "key": "sqlite_to_postgres_rehearsal_tool",
        "pass": all(expected.values()),
        "expected": expected,
        "summary_path": str(summary_path.relative_to(ROOT)),
        "sql_path": str(out_sql.relative_to(ROOT)),
        "table_count": len(summary.get("table_counts", {})),
        "row_count": summary.get("total_rows"),
        "secret_exposed": False,
    }


def _check_managed_readiness_stays_blocked_until_drivers_exist() -> dict[str, Any]:
    _clear_env()
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SAAS_SESSION_SECRET": "staging-infra-gate-session-secret-long-enough",
            "JIEJING_CORS_ORIGIN": "https://mentioned-shake-inter-critical.trycloudflare.com",
            "JIEJING_DATABASE_ENGINE": "postgres",
            "JIEJING_DATABASE_ADAPTER": "postgres-managed",
            "JIEJING_DATABASE_URL": "postgresql://jiejing:placeholder@postgres:5432/jiejing",
            "JIEJING_QUEUE_PROVIDER": "redis_streams",
            "JIEJING_QUEUE_URL": "redis://redis:6379/0",
            "JIEJING_VAULT_ENABLED": "true",
            "JIEJING_VAULT_PROVIDER": "vault",
            "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "true",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
            "JIEJING_EBAY_READ_ONLY_LIVE": "true",
            "JIEJING_ALLOW_HERMES_ADAPTERS": "false",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
        }
    )
    db_path = OUT / "infra-readiness.sqlite"
    runtime_db_path = OUT / "infra-runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    settings = SaaSSettings.from_env(
        db_path=db_path,
        runtime_db_path=runtime_db_path,
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    repo = SaaSRepository(settings.db_path, database_engine="sqlite")
    repo.initialize()
    readiness = build_product_readiness(settings, repo)
    driver_status = build_infrastructure_driver_status(settings)
    items = {item["key"]: item for item in readiness.get("items") or []}
    database_plan = next((item for item in readiness.get("items") or [] if item.get("key") == "database"), {})
    queue_plan = next((item for item in readiness.get("items") or [] if item.get("key") == "queue"), {})
    database_adapter = items.get("database_adapter_contract", {})
    queue_adapter = items.get("queue_adapter_contract", {})
    backup = items.get("backup_restore", {})
    billing = items.get("billing_quota", {})
    model_value = items.get("model_value_proof", {})
    provider_status = readiness.get("provider_status", {})
    expected = {
        "database_driver_ready": database_plan.get("status") == "ready",
        "queue_driver_ready": queue_plan.get("status") == "ready",
        "database_adapter_ready": database_adapter.get("status")
        in {"adapter_contract_ready", "managed_adapter_live"},
        "queue_adapter_ready": queue_adapter.get("status")
        in {"adapter_contract_ready", "managed_queue_live"},
        "postgres_runtime_switch_visible": driver_status.get("postgres", {}).get("repository_runtime_switch_implemented") is True,
        "redis_worker_switch_visible": driver_status.get("redis", {}).get("worker_runtime_switch_implemented") is True,
        "driver_dependency_status_visible": "dependency" in driver_status.get("postgres", {})
        and "dependency" in driver_status.get("redis", {}),
        "cutover_not_ready_without_live_probes": driver_status.get("ready_for_runtime_cutover") is False,
        "backup_gate_visible": backup.get("status") == "blocked_backup_restore_not_ready",
        "billing_gate_visible": billing.get("status") == "blocked_mainland_payment_not_ready",
        "model_value_gate_visible": model_value.get("status") == "blocked_live_model_value_not_proven",
        "provider_status_backup_visible": "backup" in provider_status,
        "provider_status_billing_visible": "billing" in provider_status,
        "provider_status_model_value_visible": "model_value" in provider_status,
        "production_not_ready": readiness.get("production_ready") is False,
        "no_real_writes": readiness.get("real_platform_writes_enabled") is False,
        "no_secret_exposure": readiness.get("secret_exposed") is False,
    }
    return {
        "key": "managed_readiness_driver_boundary",
        "pass": all(expected.values()),
        "expected": expected,
        "blocker_count": readiness.get("blocker_count"),
        "warning_count": readiness.get("warning_count"),
    }


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
