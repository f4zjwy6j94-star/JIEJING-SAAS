"""Database migration and production readiness plan for Jiejing SaaS."""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .database_adapter import build_database_adapter_contract
from .repository import SaaSRepository


CRITICAL_TABLES = [
    "users",
    "user_refresh_sessions",
    "user_refresh_token_history",
    "user_sessions",
    "companies",
    "team_members",
    "team_invitations",
    "stores",
    "secret_refs",
    "platform_connections",
    "oauth_authorization_requests",
    "platform_data_packets",
    "tasks",
    "queue_jobs",
    "task_steps",
    "reports",
    "confirmations",
    "external_execution_claims",
    "execution_results",
    "audit_logs",
    "media_credit_buckets",
    "schema_migrations",
]


CRITICAL_INDEXES = [
    "idx_user_refresh_sessions_owner",
    "idx_user_refresh_token_history_session",
    "idx_user_sessions_refresh_session",
    "idx_user_sessions_user_expiry",
    "idx_stores_company_platform_created",
    "idx_team_members_company_role",
    "idx_team_invitations_company_status_created",
    "idx_secret_refs_company_store_provider_purpose",
    "idx_platform_connections_company_store_platform_status",
    "idx_oauth_requests_company_store_status_updated",
    "idx_platform_data_packets_company_store_platform_created",
    "idx_tasks_company_store_status_updated",
    "idx_queue_jobs_company_status_updated",
    "idx_queue_jobs_task_status",
    "idx_task_steps_company_task_order",
    "idx_reports_task_type_created",
    "idx_confirmations_company_status_created",
    "idx_confirmations_task_status",
    "idx_execution_results_task_created",
    "idx_audit_logs_company_created",
    "idx_audit_logs_target",
    "idx_media_credit_buckets_company_status",
]


PRODUCTION_DATABASE_STEPS = [
    {
        "step": "choose_managed_database",
        "label": "Choose managed Postgres or MySQL",
        "why": "SQLite is fine for local development, but formal SaaS needs backups, concurrent writes, monitoring, point-in-time recovery and managed operations.",
        "recommended_target": "TencentDB for PostgreSQL or Aliyun RDS PostgreSQL",
    },
    {
        "step": "run_schema_migrations",
        "label": "Run versioned schema migrations",
        "why": "Schema changes must be repeatable and auditable before real merchant data is stored.",
        "required_tables": CRITICAL_TABLES,
    },
    {
        "step": "enforce_tenant_scoping",
        "label": "Enforce user/company/store scoping",
        "why": "Every read or write must be scoped by company_id and store_id so one merchant cannot see another merchant's store, task, report or confirmation item.",
        "minimum_columns": ["company_id", "store_id", "user_id", "task_id"],
    },
    {
        "step": "backup_restore_drill",
        "label": "Enable backup and restore drills",
        "why": "A real SaaS must be able to recover store data, task history, reports and audit logs after failure.",
        "minimum_policy": "daily backups plus restore test before beta users",
    },
    {
        "step": "least_privilege_accounts",
        "label": "Use least-privilege DB accounts",
        "why": "Runtime workers, API servers and operators should not share one unlimited database credential.",
        "minimum_accounts": ["api_read_write", "worker_read_write", "migration_owner", "readonly_audit"],
    },
]


def build_database_plan(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    inventory = repository.database_inventory()
    adapter_contract = build_database_adapter_contract(settings)
    table_names = {str(item.get("table")) for item in inventory.get("tables", []) if isinstance(item, dict)}
    index_names = {str(item.get("index_name")) for item in inventory.get("indexes", []) if isinstance(item, dict)}

    missing_tables = [table for table in CRITICAL_TABLES if table not in table_names]
    missing_indexes = [index for index in CRITICAL_INDEXES if index not in index_names]
    sqlite_local = settings.database_adapter == "sqlite-local" or settings.database_engine == "sqlite"
    production_blockers: list[str] = []
    if sqlite_local:
        production_blockers.append("sqlite_local_database")
    if not settings.database_url_configured and not sqlite_local:
        production_blockers.append("missing_database_url")
    if missing_tables:
        production_blockers.append("missing_critical_tables")
    if missing_indexes:
        production_blockers.append("missing_critical_indexes")

    migration_count = int(inventory.get("migration_count") or 0)
    if migration_count < 1:
        production_blockers.append("missing_schema_migration_record")
    for blocker in adapter_contract.get("production_blockers") or []:
        if blocker not in production_blockers:
            production_blockers.append(blocker)

    return {
        "plan_version": "2026-05-15-db-migration-boundary",
        "adapter_contract": adapter_contract,
        "current_engine": settings.database_engine,
        "current_adapter": settings.database_adapter,
        "database_url_configured": settings.database_url_configured,
        "local_db_path": str(settings.db_path),
        "production_database_ready": not production_blockers and settings.is_production_like,
        "staging_migration_shape_ready": not missing_tables and not missing_indexes and migration_count >= 1,
        "production_blockers": production_blockers,
        "critical_tables": {
            "required": CRITICAL_TABLES,
            "present_count": len(CRITICAL_TABLES) - len(missing_tables),
            "missing": missing_tables,
        },
        "critical_indexes": {
            "required": CRITICAL_INDEXES,
            "present_count": len(CRITICAL_INDEXES) - len(missing_indexes),
            "missing": missing_indexes,
        },
        "migrations": inventory.get("migrations", []),
        "migration_files": [
            {
                "database": "postgres",
                "path": "jiejing_saas/migrations/001_initial_schema_postgres.sql",
                "status": "prepared_not_applied",
            },
            {
                "database": "postgres",
                "path": "jiejing_saas/migrations/002_media_credit_buckets_postgres.sql",
                "status": "prepared_not_applied",
            },
            {
                "database": "postgres",
                "path": "jiejing_saas/migrations/003_runtime_schema_reconciliation_postgres.sql",
                "status": "prepared_not_applied",
            },
            {
                "database": "postgres",
                "path": "jiejing_saas/migrations/004_platform_model_trial_reservations_postgres.sql",
                "status": "prepared_not_applied",
            },
        ],
        "production_steps": PRODUCTION_DATABASE_STEPS,
        "tenant_isolation_contract": {
            "rule": "All merchant data reads and writes must be scoped by company_id plus store_id or task_id.",
            "frontend_never_talks_to_database": True,
            "runtime_never_gets_full_customer_database": True,
            "secrets_stay_out_of_database": True,
        },
        "backup_restore_contract": {
            "required_before_beta": True,
            "minimum_backup": "daily managed backup",
            "minimum_restore_test": "restore rehearsal before inviting real merchants",
            "audit_logs_retained": True,
        },
        "secret_exposed": False,
    }
