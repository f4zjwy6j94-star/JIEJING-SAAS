"""Backup and restore readiness contract for Jiejing SaaS.

The plan is intentionally read-only. It never opens database connections beyond
the repository inventory call, never exports data, and never prints secret
values. Its job is to make the paid-SaaS backup gap explicit before real
merchant data is accepted.
"""

from __future__ import annotations

import os
from typing import Any

from .config import SaaSSettings
from .repository import SaaSRepository


def build_backup_plan(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    database_managed = settings.database_engine == "postgres" and settings.database_adapter == "postgres-managed"
    cos_target = _cos_backup_target_status()
    policy_configured = _env_bool("JIEJING_BACKUP_POLICY_CONFIGURED")
    restore_drill_at = os.environ.get("JIEJING_RESTORE_DRILL_LAST_AT", "").strip()
    alerts_configured = _env_bool("JIEJING_BACKUP_ALERTS_CONFIGURED")
    vault_backup_configured = _env_bool("JIEJING_VAULT_BACKUP_POLICY_CONFIGURED")
    blockers: list[str] = []
    if not database_managed:
        blockers.append("managed_postgres_not_selected")
    if not settings.database_url_configured:
        blockers.append("missing_database_url")
    if not policy_configured:
        blockers.append("backup_policy_not_configured")
    if not restore_drill_at:
        blockers.append("restore_drill_not_recorded")
    if not alerts_configured:
        blockers.append("backup_alerts_not_configured")
    if settings.vault_enabled and settings.vault_provider != "secret_ref_only" and not vault_backup_configured:
        blockers.append("vault_backup_policy_not_configured")
    for item in cos_target["blocked_by"]:
        if item not in blockers:
            blockers.append(item)

    return {
        "contract_version": "2026-05-18-backup-restore-boundary",
        "environment": settings.environment,
        "backup_ready_for_paid_launch": settings.is_production_like and not blockers,
        "database": {
            "engine": settings.database_engine,
            "adapter": settings.database_adapter,
            "managed_database_selected": database_managed,
            "database_url_configured": settings.database_url_configured,
            "minimum_policy": {
                "automated_backup": "daily",
                "point_in_time_recovery": True,
                "point_in_time_recovery_policy": "required_for_paid_launch",
                "retention_days_minimum": 14,
                "restore_drill": "required_before_beta_or_paid_merchant_data",
            },
        },
        "object_storage": cos_target,
        "vault": {
            "provider": settings.vault_provider,
            "vault_enabled": settings.vault_enabled,
            "backup_policy_configured": vault_backup_configured,
            "raw_secret_export_allowed": False,
        },
        "restore": {
            "last_restore_drill_at": restore_drill_at,
            "restore_drill_recorded": bool(restore_drill_at),
            "must_verify_tables": [
                "users",
                "companies",
                "stores",
                "platform_connections",
                "secret_refs",
                "platform_data_packets",
                "tasks",
                "reports",
                "confirmations",
                "audit_logs",
            ],
        },
        "alerts": {
            "configured": alerts_configured,
            "required_signals": [
                "backup_job_failed",
                "restore_drill_overdue",
                "database_storage_growth",
                "vault_snapshot_failed",
            ],
        },
        "current_data_shape": {
            "table_counts": counts,
            "merchant_data_tables_present": bool(counts.get("stores") or counts.get("platform_data_packets")),
        },
        "blockers": blockers,
        "next_actions": _next_actions(blockers),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _next_actions(blockers: list[str]) -> list[str]:
    if not blockers:
        return ["schedule_recurring_restore_drill_and_monitor_backup_alerts"]
    actions = []
    if "managed_postgres_not_selected" in blockers:
        actions.append("switch_staging_database_to_managed_postgres_before_paid_launch")
    if "backup_policy_not_configured" in blockers:
        actions.append("configure_daily_backup_and_point_in_time_recovery")
    if "restore_drill_not_recorded" in blockers:
        actions.append("run_restore_drill_and_record_JIEJING_RESTORE_DRILL_LAST_AT")
    if "backup_alerts_not_configured" in blockers:
        actions.append("wire_backup_failure_and_restore_overdue_alerts")
    if "vault_backup_policy_not_configured" in blockers:
        actions.append("configure_vault_snapshot_or_managed_kms_recovery_policy")
    if "cos_backup_target_not_configured" in blockers:
        actions.append("configure_private_cos_bucket_for_backup_artifacts")
    if "cos_backup_probe_not_recorded" in blockers:
        actions.append("run_non_secret_cos_backup_probe_and_record_success_time")
    return actions


def _cos_backup_target_status() -> dict[str, Any]:
    enabled = _env_bool("JIEJING_COS_BACKUP_ENABLED")
    provider = (os.environ.get("JIEJING_BACKUP_STORAGE_PROVIDER") or ("cos" if enabled else "unconfigured")).strip().lower()
    region = os.environ.get("JIEJING_COS_REGION") or os.environ.get("JIEJING_TENCENT_REGION") or "ap-guangzhou"
    bucket = os.environ.get("JIEJING_COS_BUCKET", "").strip()
    prefix = (os.environ.get("JIEJING_COS_PREFIX") or "jiejing/staging/backups").strip().strip("/")
    probe_at = os.environ.get("JIEJING_COS_BACKUP_LAST_SUCCESS_AT", "").strip()
    live_probe_required = _env_bool("JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED")
    credentials_configured = bool(_tencent_secret_id()) and bool(_tencent_secret_key())
    blockers: list[str] = []
    if provider == "cos" or enabled:
        if not enabled:
            blockers.append("cos_backup_target_not_enabled")
        if not bucket:
            blockers.append("cos_backup_target_not_configured")
        if not region:
            blockers.append("JIEJING_COS_REGION")
        if live_probe_required and not probe_at:
            blockers.append("cos_backup_probe_not_recorded")
    return {
        "provider": provider,
        "enabled": enabled,
        "target_ready": bool(enabled and bucket and region and (probe_at or not live_probe_required)),
        "region": region,
        "bucket_configured": bool(bucket),
        "prefix_configured": bool(prefix),
        "credentials_configured": credentials_configured,
        "live_probe_required": live_probe_required,
        "last_successful_probe_at": probe_at,
        "stores_raw_secret_values": False,
        "raw_secret_export_allowed": False,
        "blocked_by": blockers,
        "secret_exposed": False,
    }


def _tencent_secret_id() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID") or ""


def _tencent_secret_key() -> str:
    return os.environ.get("JIEJING_TENCENT_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY") or ""


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}
