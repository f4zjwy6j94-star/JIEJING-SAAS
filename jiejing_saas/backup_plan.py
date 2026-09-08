"""Backup and restore readiness contract for Jiejing SaaS.

The plan is intentionally read-only. It never opens database connections beyond
the repository inventory call, never exports data, and never prints secret
values. Its job is to make the paid-SaaS backup gap explicit before real
merchant data is accepted.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
import os
from typing import Any

from .config import SaaSSettings
from .repository import SaaSRepository
from .runtime_evidence import RuntimeEvidenceError, read_runtime_evidence


BACKUP_PROBE_MAX_AGE_HOURS = 36.0
RESTORE_DRILL_MAX_AGE_DAYS = 30.0
EVIDENCE_MAX_FUTURE_SKEW_MINUTES = 5.0


def build_backup_plan(settings: SaaSSettings, repository: SaaSRepository) -> dict[str, Any]:
    counts = repository.system_counts()
    database_managed = settings.database_engine == "postgres" and settings.database_adapter == "postgres-managed"
    evidence_unavailable = False
    try:
        evidence = read_runtime_evidence()
    except RuntimeEvidenceError:
        evidence, evidence_unavailable = {}, True
    cos_target = _cos_backup_target_status(require_fresh_probe=settings.is_production_like, runtime_evidence=evidence)
    if evidence_unavailable:
        cos_target["target_ready"] = False
        cos_target["blocked_by"].append("runtime_evidence_unavailable")
    policy_configured = _env_bool("JIEJING_BACKUP_POLICY_CONFIGURED")
    restore_drill_at = os.environ.get("JIEJING_RESTORE_DRILL_LAST_AT", "").strip()
    restore_drill_max_age_days = _env_bounded_float(
        "JIEJING_RESTORE_DRILL_MAX_AGE_DAYS", RESTORE_DRILL_MAX_AGE_DAYS, minimum=1.0, maximum=365.0
    )
    restore_drill_age_hours = _timestamp_age_hours(restore_drill_at)
    restore_drill_timestamp_valid = bool(restore_drill_at and restore_drill_age_hours is not None)
    restore_drill_timestamp_in_future = bool(
        restore_drill_timestamp_valid and restore_drill_age_hours < -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60)
    )
    restore_drill_fresh = bool(
        restore_drill_timestamp_valid
        and not restore_drill_timestamp_in_future
        and restore_drill_age_hours <= restore_drill_max_age_days * 24
    )
    alerts_configured = _env_bool("JIEJING_BACKUP_ALERTS_CONFIGURED")
    vault_backup_configured = _env_bool("JIEJING_VAULT_BACKUP_POLICY_CONFIGURED")
    vault_backup_artifact_id = os.environ.get("JIEJING_VAULT_BACKUP_ARTIFACT_ID", "").strip()
    vault_restore_at = os.environ.get("JIEJING_VAULT_RESTORE_DRILL_LAST_AT", "").strip()
    vault_restore_age_hours = _timestamp_age_hours(vault_restore_at)
    vault_restore_fresh = bool(
        vault_restore_at
        and vault_restore_age_hours is not None
        and vault_restore_age_hours >= -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60)
        and vault_restore_age_hours <= restore_drill_max_age_days * 24
    )
    vault_manual_unseal_verified = _env_bool("JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED")
    vault_sentinel_resolve_verified = _env_bool("JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED")
    vault_unseal_key_shares = _env_nonnegative_int("JIEJING_VAULT_UNSEAL_KEY_SHARES")
    vault_unseal_key_threshold = _env_nonnegative_int("JIEJING_VAULT_UNSEAL_KEY_THRESHOLD")
    vault_offline_share_custody_verified = _env_bool("JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED")
    vault_offline_custody_unit_count = _env_nonnegative_int("JIEJING_VAULT_OFFLINE_CUSTODY_UNIT_COUNT")
    vault_offline_max_shares_per_custody_unit = _env_nonnegative_int(
        "JIEJING_VAULT_OFFLINE_MAX_SHARES_PER_CUSTODY_UNIT"
    )
    vault_offline_share_distribution_safe = bool(
        vault_unseal_key_shares >= 3
        and vault_unseal_key_threshold >= 2
        and 1 <= vault_offline_max_shares_per_custody_unit < vault_unseal_key_threshold
        and vault_offline_custody_unit_count >= math.ceil(
            vault_unseal_key_shares / vault_offline_max_shares_per_custody_unit
        )
        and vault_offline_custody_unit_count <= vault_unseal_key_shares
    )
    vault_production_unseal_boundary_ready = bool(
        vault_unseal_key_shares >= 3
        and vault_unseal_key_threshold >= 2
        and vault_unseal_key_threshold <= vault_unseal_key_shares
        and vault_offline_share_custody_verified
        and vault_offline_share_distribution_safe
    )
    vault_recovery_required = settings.vault_enabled and settings.vault_provider == "vault"
    blockers: list[str] = []
    if not database_managed:
        blockers.append("managed_postgres_not_selected")
    if not settings.database_url_configured:
        blockers.append("missing_database_url")
    if not policy_configured:
        blockers.append("backup_policy_not_configured")
    if not restore_drill_at:
        blockers.append("restore_drill_not_recorded")
    if restore_drill_at and not restore_drill_timestamp_valid:
        blockers.append("restore_drill_timestamp_invalid")
    if restore_drill_timestamp_in_future:
        blockers.append("restore_drill_timestamp_in_future")
    if (
        restore_drill_at
        and restore_drill_age_hours is not None
        and not restore_drill_fresh
        and not restore_drill_timestamp_in_future
    ):
        blockers.append("restore_drill_overdue")
    if not alerts_configured:
        blockers.append("backup_alerts_not_configured")
    if settings.vault_enabled and settings.vault_provider != "secret_ref_only" and not vault_backup_configured:
        blockers.append("vault_backup_policy_not_configured")
    if vault_recovery_required:
        if not vault_backup_artifact_id:
            blockers.append("vault_backup_artifact_not_recorded")
        if not vault_restore_at:
            blockers.append("vault_restore_drill_not_recorded")
        elif vault_restore_age_hours is None:
            blockers.append("vault_restore_drill_timestamp_invalid")
        elif vault_restore_age_hours < -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60):
            blockers.append("vault_restore_drill_timestamp_in_future")
        elif not vault_restore_fresh:
            blockers.append("vault_restore_drill_overdue")
        if not vault_manual_unseal_verified:
            blockers.append("vault_restore_manual_unseal_not_verified")
        if not vault_sentinel_resolve_verified:
            blockers.append("vault_restore_sentinel_resolve_not_verified")
        if vault_unseal_key_shares < 3:
            blockers.append("vault_unseal_key_shares_below_production_minimum")
        if vault_unseal_key_threshold < 2 or vault_unseal_key_threshold > vault_unseal_key_shares:
            blockers.append("vault_unseal_key_threshold_below_production_minimum")
        if not vault_offline_share_custody_verified:
            blockers.append("vault_offline_share_custody_not_verified")
        if not vault_offline_share_distribution_safe:
            blockers.append("vault_offline_share_custody_distribution_unsafe")
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
            "backup_artifact_recorded": bool(vault_backup_artifact_id),
            "backup_artifact_id_sha256": _evidence_id_sha256(vault_backup_artifact_id),
            "restore_drill_at": vault_restore_at,
            "restore_drill_fresh": vault_restore_fresh,
            "manual_unseal_verified": vault_manual_unseal_verified,
            "sentinel_resolve_verified": vault_sentinel_resolve_verified,
            "unseal_key_shares": vault_unseal_key_shares,
            "unseal_key_threshold": vault_unseal_key_threshold,
            "offline_share_custody_verified": vault_offline_share_custody_verified,
            "offline_custody_unit_count": vault_offline_custody_unit_count,
            "offline_max_shares_per_custody_unit": vault_offline_max_shares_per_custody_unit,
            "offline_share_distribution_safe": vault_offline_share_distribution_safe,
            "production_unseal_boundary_ready": vault_production_unseal_boundary_ready,
            "recovery_proof_ready": bool(
                not vault_recovery_required
                or (
                    vault_backup_configured
                    and vault_backup_artifact_id
                    and vault_restore_fresh
                    and vault_manual_unseal_verified
                    and vault_sentinel_resolve_verified
                    and vault_production_unseal_boundary_ready
                )
            ),
            "raw_secret_export_allowed": False,
        },
        "restore": {
            "last_restore_drill_at": restore_drill_at,
            "restore_drill_recorded": bool(restore_drill_at),
            "restore_drill_timestamp_valid": restore_drill_timestamp_valid,
            "restore_drill_timestamp_in_future": restore_drill_timestamp_in_future,
            "restore_drill_fresh": restore_drill_fresh,
            "restore_drill_age_days": (
                round(restore_drill_age_hours / 24, 3) if restore_drill_age_hours is not None else None
            ),
            "restore_drill_max_age_days": restore_drill_max_age_days,
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
    if any(
        item in blockers
        for item in (
            "restore_drill_not_recorded",
            "restore_drill_timestamp_invalid",
            "restore_drill_timestamp_in_future",
            "restore_drill_overdue",
        )
    ):
        actions.append("run_restore_drill_and_record_JIEJING_RESTORE_DRILL_LAST_AT")
    if "backup_alerts_not_configured" in blockers:
        actions.append("wire_backup_failure_and_restore_overdue_alerts")
    if "vault_backup_policy_not_configured" in blockers:
        actions.append("configure_vault_snapshot_or_managed_kms_recovery_policy")
    if any(
        item.startswith("vault_restore_")
        or item.startswith("vault_unseal_")
        or item == "vault_backup_artifact_not_recorded"
        or item == "vault_offline_share_custody_not_verified"
        or item == "vault_offline_share_custody_distribution_unsafe"
        for item in blockers
    ):
        actions.append("run_isolated_vault_restore_unseal_and_sentinel_drill")
    if "cos_backup_target_not_configured" in blockers:
        actions.append("configure_private_cos_bucket_for_backup_artifacts")
    if any(
        item in blockers
        for item in (
            "cos_backup_probe_not_recorded",
            "cos_backup_probe_timestamp_invalid",
            "cos_backup_probe_timestamp_in_future",
            "cos_backup_probe_stale",
        )
    ):
        actions.append("run_non_secret_cos_backup_probe_and_record_success_time")
    return actions


def _evidence_id_sha256(value: str) -> str:
    if not value:
        return ""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cos_backup_target_status(*, require_fresh_probe: bool = False, runtime_evidence: dict[str, str] | None = None) -> dict[str, Any]:
    evidence = read_runtime_evidence() if runtime_evidence is None else runtime_evidence
    enabled = _env_bool("JIEJING_COS_BACKUP_ENABLED")
    provider = (os.environ.get("JIEJING_BACKUP_STORAGE_PROVIDER") or ("cos" if enabled else "unconfigured")).strip().lower()
    region = os.environ.get("JIEJING_COS_REGION") or os.environ.get("JIEJING_TENCENT_REGION") or "ap-guangzhou"
    bucket = os.environ.get("JIEJING_COS_BUCKET", "").strip()
    prefix = (os.environ.get("JIEJING_COS_PREFIX") or "jiejing/staging/backups").strip().strip("/")
    probe_at = evidence.get("JIEJING_COS_BACKUP_LAST_SUCCESS_AT", "").strip()
    probe_max_age_hours = _env_bounded_float(
        "JIEJING_BACKUP_PROBE_MAX_AGE_HOURS", BACKUP_PROBE_MAX_AGE_HOURS, minimum=1.0, maximum=168.0
    )
    probe_age_hours = _timestamp_age_hours(probe_at)
    probe_timestamp_valid = bool(probe_at and probe_age_hours is not None)
    probe_timestamp_in_future = bool(
        probe_timestamp_valid and probe_age_hours < -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60)
    )
    probe_fresh = bool(
        probe_timestamp_valid and not probe_timestamp_in_future and probe_age_hours <= probe_max_age_hours
    )
    live_probe_required = _env_bool("JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED")
    fresh_probe_required = bool(require_fresh_probe or live_probe_required)
    credentials_configured = bool(_tencent_secret_id()) and bool(_tencent_secret_key())
    blockers: list[str] = []
    if provider == "cos" or enabled:
        if not enabled:
            blockers.append("cos_backup_target_not_enabled")
        if not bucket:
            blockers.append("cos_backup_target_not_configured")
        if not region:
            blockers.append("JIEJING_COS_REGION")
        if fresh_probe_required and not probe_at:
            blockers.append("cos_backup_probe_not_recorded")
        if fresh_probe_required and probe_at and not probe_timestamp_valid:
            blockers.append("cos_backup_probe_timestamp_invalid")
        if fresh_probe_required and probe_timestamp_in_future:
            blockers.append("cos_backup_probe_timestamp_in_future")
        if (
            fresh_probe_required
            and probe_at
            and probe_age_hours is not None
            and not probe_fresh
            and not probe_timestamp_in_future
        ):
            blockers.append("cos_backup_probe_stale")
    return {
        "provider": provider,
        "enabled": enabled,
        "target_ready": bool(enabled and bucket and region and (probe_fresh or not fresh_probe_required)),
        "region": region,
        "bucket_configured": bool(bucket),
        "prefix_configured": bool(prefix),
        "credentials_configured": credentials_configured,
        "live_probe_required": live_probe_required,
        "fresh_probe_required_for_paid_launch": bool(require_fresh_probe),
        "fresh_probe_required": fresh_probe_required,
        "last_successful_probe_at": probe_at,
        "live_probe_timestamp_valid": probe_timestamp_valid,
        "live_probe_timestamp_in_future": probe_timestamp_in_future,
        "live_probe_fresh": probe_fresh,
        "live_probe_age_hours": round(probe_age_hours, 3) if probe_age_hours is not None else None,
        "live_probe_max_age_hours": probe_max_age_hours,
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


def _env_nonnegative_int(name: str) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if value >= 0 else 0


def _env_bounded_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or value < minimum or value > maximum:
        return default
    return value


def _timestamp_age_hours(value: str) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
