"""Database adapter contract for local and production Jiejing SaaS."""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings


DATABASE_ADAPTERS = [
    {
        "key": "sqlite-local",
        "engine": "sqlite",
        "label": "Local SQLite",
        "status": "implemented_for_local_dev",
        "driver_implemented": True,
        "allowed_environments": ["local_dev", "test"],
        "stores_secrets": False,
        "production_allowed": False,
    },
    {
        "key": "postgres-managed",
        "engine": "postgres",
        "label": "Managed PostgreSQL",
        "status": "implemented_for_staging_cutover",
        "driver_implemented": True,
        "allowed_environments": ["staging", "production"],
        "stores_secrets": False,
        "production_allowed": True,
        "recommended_targets": ["TencentDB for PostgreSQL", "Aliyun RDS PostgreSQL"],
    },
    {
        "key": "mysql-managed",
        "engine": "mysql",
        "label": "Managed MySQL",
        "status": "contract_reserved",
        "driver_implemented": False,
        "allowed_environments": ["staging", "production"],
        "stores_secrets": False,
        "production_allowed": True,
        "recommended_targets": ["TencentDB for MySQL", "Aliyun RDS MySQL"],
    },
]


def build_database_adapter_contract(settings: SaaSSettings) -> dict[str, Any]:
    selected = next((item for item in DATABASE_ADAPTERS if item["key"] == settings.database_adapter), None)
    selected = selected or next((item for item in DATABASE_ADAPTERS if item["engine"] == settings.database_engine), None)
    selected = selected or DATABASE_ADAPTERS[0]

    blockers: list[str] = []
    if settings.is_production_like and not selected.get("production_allowed"):
        blockers.append("selected_database_adapter_not_allowed_for_production")
    if selected.get("production_allowed") and not settings.database_url_configured:
        blockers.append("missing_database_url")
    if selected["key"] == "postgres-managed" and not selected.get("driver_implemented"):
        blockers.append("postgres_http_driver_not_implemented")
    if selected["key"] == "mysql-managed" and not selected.get("driver_implemented"):
        blockers.append("mysql_driver_not_implemented")

    return {
        "contract_version": "2026-05-15-database-adapter-contract",
        "selected_adapter": selected,
        "available_adapters": DATABASE_ADAPTERS,
        "database_url_configured": settings.database_url_configured,
        "local_sqlite_path": str(settings.db_path),
        "migration_files": [
            {
                "adapter": "postgres-managed",
                "path": "jiejing_saas/migrations/001_initial_schema_postgres.sql",
                "status": "prepared_not_applied",
            }
        ],
        "runtime_rules": {
            "frontend_never_connects_to_database": True,
            "runtime_never_connects_to_database_directly": True,
            "api_server_owns_tenant_checks": True,
            "database_must_not_store_raw_secrets": True,
        },
        "production_blockers": blockers,
        "secret_exposed": False,
    }
