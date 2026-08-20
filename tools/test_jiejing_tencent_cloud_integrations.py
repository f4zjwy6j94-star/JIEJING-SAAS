#!/usr/bin/env python3
"""Regression checks for Tencent SSM/KMS, CLS and COS readiness wiring."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.backup_plan import build_backup_plan  # noqa: E402
from jiejing_saas.commercial_launch_gate import build_commercial_launch_gate  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.monitoring import build_monitoring_status  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
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
    "JIEJING_VAULT_BACKUP_ARTIFACT_ID",
    "JIEJING_VAULT_RESTORE_DRILL_LAST_AT",
    "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED",
    "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED",
    "JIEJING_VAULT_UNSEAL_KEY_SHARES",
    "JIEJING_VAULT_UNSEAL_KEY_THRESHOLD",
    "JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED",
    "JIEJING_VAULT_OFFLINE_CUSTODY_UNIT_COUNT",
    "JIEJING_VAULT_OFFLINE_MAX_SHARES_PER_CUSTODY_UNIT",
    "JIEJING_COS_BACKUP_ENABLED",
    "JIEJING_COS_REGION",
    "JIEJING_COS_BUCKET",
    "JIEJING_COS_PREFIX",
    "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED",
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_BACKUP_PROBE_MAX_AGE_HOURS",
    "JIEJING_RESTORE_DRILL_MAX_AGE_DAYS",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_CLS_LIVE_PROBE_REQUIRED",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_PROBE_MAX_AGE_HOURS",
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
    "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED",
    "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES",
    "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
    "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS",
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
        now = datetime.now(timezone.utc).replace(microsecond=0)
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
                "JIEJING_RESTORE_DRILL_LAST_AT": (now - timedelta(days=1)).isoformat(),
                "JIEJING_BACKUP_ALERTS_CONFIGURED": "true",
                "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "true",
                "JIEJING_VAULT_BACKUP_ARTIFACT_ID": "vault-backup-artifact-fixture",
                "JIEJING_VAULT_RESTORE_DRILL_LAST_AT": (now - timedelta(days=1)).isoformat(),
                "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED": "true",
                "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED": "true",
                "JIEJING_VAULT_UNSEAL_KEY_SHARES": "3",
                "JIEJING_VAULT_UNSEAL_KEY_THRESHOLD": "2",
                "JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED": "true",
                "JIEJING_VAULT_OFFLINE_CUSTODY_UNIT_COUNT": "3",
                "JIEJING_VAULT_OFFLINE_MAX_SHARES_PER_CUSTODY_UNIT": "1",
                "JIEJING_COS_BACKUP_ENABLED": "true",
                "JIEJING_COS_REGION": "ap-guangzhou",
                "JIEJING_COS_BUCKET": "jiejing-private-backups-1250000000",
                "JIEJING_COS_PREFIX": "jiejing/staging/backups",
                "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED": "true",
                "JIEJING_COS_BACKUP_LAST_SUCCESS_AT": (now - timedelta(hours=1)).isoformat(),
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": "ap-guangzhou",
                "JIEJING_CLS_LOGSET_ID": "logset-jiejing",
                "JIEJING_CLS_TOPIC_ID": "topic-saas-backend",
                "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
                "JIEJING_CLS_LIVE_PROBE_REQUIRED": "true",
                "JIEJING_CLS_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=2)).isoformat(),
                "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED": "true",
                "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": (now - timedelta(minutes=1)).isoformat(),
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
                "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED": "true",
                "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES": "15",
                "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR": "10000",
                "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR": "20000",
                "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
                "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT": (now - timedelta(minutes=1)).isoformat(),
                "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS": "7",
            }
        )
        settings = _settings(db_path)
        repo = SaaSRepository(settings.db_path, database_engine="sqlite")
        repo.initialize()
        _seed_provider_monitoring_state(repo, now)

        backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
        vault_settings = _settings(db_path)
        os.environ["JIEJING_VAULT_OFFLINE_CUSTODY_UNIT_COUNT"] = "2"
        os.environ["JIEJING_VAULT_OFFLINE_MAX_SHARES_PER_CUSTODY_UNIT"] = "2"
        concentrated_vault_custody = build_backup_plan(vault_settings, repo)
        os.environ["JIEJING_VAULT_OFFLINE_CUSTODY_UNIT_COUNT"] = "3"
        os.environ["JIEJING_VAULT_OFFLINE_MAX_SHARES_PER_CUSTODY_UNIT"] = "1"
        os.environ.pop("JIEJING_VAULT_BACKUP_ARTIFACT_ID")
        missing_vault_artifact = build_backup_plan(vault_settings, repo)
        os.environ["JIEJING_VAULT_BACKUP_ARTIFACT_ID"] = "vault-backup-artifact-fixture"
        os.environ["JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED"] = "false"
        missing_vault_sentinel = build_backup_plan(vault_settings, repo)
        os.environ["JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED"] = "true"
        os.environ["JIEJING_VAULT_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=31)).isoformat()
        stale_vault_restore = build_backup_plan(vault_settings, repo)
        os.environ["JIEJING_VAULT_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=1)).isoformat()
        os.environ["JIEJING_VAULT_UNSEAL_KEY_SHARES"] = "1"
        os.environ["JIEJING_VAULT_UNSEAL_KEY_THRESHOLD"] = "1"
        os.environ["JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED"] = "false"
        weak_vault_unseal_boundary = build_backup_plan(vault_settings, repo)
        weak_vault_readiness = build_product_readiness(vault_settings, repo)
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=37)).isoformat()
        weak_vault_stale_backup_readiness = build_product_readiness(vault_settings, repo)
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=1)).isoformat()
        os.environ["JIEJING_VAULT_UNSEAL_KEY_SHARES"] = "3"
        os.environ["JIEJING_VAULT_UNSEAL_KEY_THRESHOLD"] = "2"
        os.environ["JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED"] = "true"
        os.environ["JIEJING_VAULT_PROVIDER"] = "tencent_ssm"
        monitoring = build_monitoring_status(settings, repo, now_utc=now)
        vault_adapter = build_vault_adapter_contract(settings)
        launch_gate = build_commercial_launch_gate(settings, repo)
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=25)).isoformat()
        stale_cls_control = build_monitoring_status(settings, repo, now_utc=now)
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=2)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=25)).isoformat()
        stale_cls_ingestion = build_monitoring_status(settings, repo, now_utc=now)
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = "not-an-iso-timestamp"
        invalid_cls_ingestion = build_monitoring_status(settings, repo, now_utc=now)
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now + timedelta(minutes=6)).isoformat()
        future_cls_ingestion = build_monitoring_status(settings, repo, now_utc=now)
        os.environ["JIEJING_CLS_PROBE_MAX_AGE_HOURS"] = "2"
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=3)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        custom_cls_age = build_monitoring_status(settings, repo, now_utc=now)
        os.environ["JIEJING_CLS_PROBE_MAX_AGE_HOURS"] = "nan"
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(hours=23)).isoformat()
        fallback_cls_age = build_monitoring_status(settings, repo, now_utc=now)
        os.environ.pop("JIEJING_CLS_PROBE_MAX_AGE_HOURS", None)
        os.environ["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=2)).isoformat()
        os.environ["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = (now - timedelta(minutes=1)).isoformat()
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=37)).isoformat()
        stale_cos_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=1)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=31)).isoformat()
        stale_restore_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=1)).isoformat()
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = "not-an-iso-timestamp"
        invalid_cos_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=1)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = "not-an-iso-timestamp"
        invalid_restore_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=1)).isoformat()
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now + timedelta(minutes=10)).isoformat()
        future_cos_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=1)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now + timedelta(minutes=10)).isoformat()
        future_restore_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=1)).isoformat()
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=3)).isoformat()
        os.environ["JIEJING_BACKUP_PROBE_MAX_AGE_HOURS"] = "2"
        custom_cos_age_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_BACKUP_PROBE_MAX_AGE_HOURS"] = "36"
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=1)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=8)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_MAX_AGE_DAYS"] = "7"
        custom_restore_age_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_RESTORE_DRILL_MAX_AGE_DAYS"] = "30"
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=1)).isoformat()
        os.environ["JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED"] = "false"
        os.environ.pop("JIEJING_COS_BACKUP_LAST_SUCCESS_AT", None)
        missing_cos_backup = build_backup_plan(settings, repo)
        os.environ["JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED"] = "true"
        os.environ["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = (now - timedelta(hours=37)).isoformat()
        os.environ["JIEJING_RESTORE_DRILL_LAST_AT"] = (now - timedelta(days=31)).isoformat()
        stale_evidence_readiness = build_product_readiness(settings, repo)
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
    if backup.get("vault", {}).get("recovery_proof_ready") is not True:
        return fail(f"Vault recovery must require artifact, manual unseal and sentinel proof: {backup.get('vault')}")
    concentrated_blockers = concentrated_vault_custody.get("blockers") or []
    if (
        concentrated_vault_custody.get("backup_ready_for_paid_launch") is not False
        or "vault_offline_share_custody_distribution_unsafe" not in concentrated_blockers
        or concentrated_vault_custody.get("vault", {}).get("production_unseal_boundary_ready") is not False
    ):
        return fail(
            "one custody unit must never hold enough shares to meet the unseal threshold: "
            f"{concentrated_vault_custody.get('vault')} {concentrated_blockers}"
        )
    if missing_vault_artifact.get("backup_ready_for_paid_launch") is not False or "vault_backup_artifact_not_recorded" not in (missing_vault_artifact.get("blockers") or []):
        return fail("missing Vault backup artifact evidence must block paid launch")
    if missing_vault_sentinel.get("backup_ready_for_paid_launch") is not False or "vault_restore_sentinel_resolve_not_verified" not in (missing_vault_sentinel.get("blockers") or []):
        return fail("missing Vault sentinel resolution proof must block paid launch")
    if stale_vault_restore.get("backup_ready_for_paid_launch") is not False or "vault_restore_drill_overdue" not in (stale_vault_restore.get("blockers") or []):
        return fail("stale Vault recovery drill evidence must block paid launch")
    weak_blockers = weak_vault_unseal_boundary.get("blockers") or []
    if (
        weak_vault_unseal_boundary.get("backup_ready_for_paid_launch") is not False
        or "vault_unseal_key_shares_below_production_minimum" not in weak_blockers
        or "vault_unseal_key_threshold_below_production_minimum" not in weak_blockers
        or "vault_offline_share_custody_not_verified" not in weak_blockers
    ):
        return fail(f"1-of-1 or server-resident Vault shares must block paid launch: {weak_blockers}")
    weak_vault_items = {item.get("key"): item for item in weak_vault_readiness.get("items") or []}
    weak_vault_public = weak_vault_items.get("backup_restore") or {}
    if weak_vault_public.get("status") != "blocked_vault_unseal_custody_not_ready":
        return fail(f"public readiness must identify the remaining Vault share custody blocker: {weak_vault_public}")
    if "Vault recovery shares" not in str(weak_vault_public.get("detail") or ""):
        return fail(f"public readiness must describe the Vault recovery boundary truthfully: {weak_vault_public}")
    if "three independent custody units" not in str(weak_vault_public.get("next_action") or "").lower():
        return fail(f"public readiness must prevent threshold shares from being concentrated: {weak_vault_public}")
    if "managed Postgres" in str(weak_vault_public.get("next_action") or ""):
        return fail(f"Vault-only debt must not direct the operator back to completed Postgres work: {weak_vault_public}")
    weak_vault_stale_items = {
        item.get("key"): item for item in weak_vault_stale_backup_readiness.get("items") or []
    }
    weak_vault_stale_public = weak_vault_stale_items.get("backup_restore") or {}
    if weak_vault_stale_public.get("status") != "blocked_vault_unseal_custody_and_backup_evidence_stale":
        return fail(
            "public readiness must identify both Vault custody and stale backup evidence: "
            f"{weak_vault_stale_public}"
        )
    if "managed Postgres" in str(weak_vault_stale_public.get("next_action") or ""):
        return fail(
            "combined Vault and freshness debt must not direct the operator to completed Postgres work: "
            f"{weak_vault_stale_public}"
        )
    if "three independent custody units" not in str(weak_vault_stale_public.get("next_action") or "").lower():
        return fail(
            "combined readiness must still describe the independent Vault custody requirement: "
            f"{weak_vault_stale_public}"
        )
    if backup.get("object_storage", {}).get("target_ready") is not True:
        return fail("COS backup target should be ready when bucket, region and probe are configured")
    if stale_cos_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("COS backup evidence older than 36 hours must block paid launch")
    if "cos_backup_probe_stale" not in (stale_cos_backup.get("blockers") or []):
        return fail(f"stale COS backup evidence should report cos_backup_probe_stale: {stale_cos_backup.get('blockers')}")
    if "run_non_secret_cos_backup_probe_and_record_success_time" not in (stale_cos_backup.get("next_actions") or []):
        return fail("stale COS evidence should direct operators to record a new non-secret probe")
    if stale_restore_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("restore drill evidence older than 30 days must block paid launch")
    if "restore_drill_overdue" not in (stale_restore_backup.get("blockers") or []):
        return fail(f"stale restore drill evidence should report restore_drill_overdue: {stale_restore_backup.get('blockers')}")
    if invalid_cos_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("invalid COS backup evidence timestamp must block paid launch")
    if "cos_backup_probe_timestamp_invalid" not in (invalid_cos_backup.get("blockers") or []):
        return fail(f"invalid COS timestamp should report cos_backup_probe_timestamp_invalid: {invalid_cos_backup.get('blockers')}")
    if invalid_restore_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("invalid restore drill timestamp must block paid launch")
    if "restore_drill_timestamp_invalid" not in (invalid_restore_backup.get("blockers") or []):
        return fail(f"invalid restore timestamp should report restore_drill_timestamp_invalid: {invalid_restore_backup.get('blockers')}")
    if future_cos_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("COS backup evidence more than five minutes in the future must block paid launch")
    if "cos_backup_probe_timestamp_in_future" not in (future_cos_backup.get("blockers") or []):
        return fail(f"future COS timestamp should report cos_backup_probe_timestamp_in_future: {future_cos_backup.get('blockers')}")
    if future_restore_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("restore drill evidence more than five minutes in the future must block paid launch")
    if "restore_drill_timestamp_in_future" not in (future_restore_backup.get("blockers") or []):
        return fail(f"future restore timestamp should report restore_drill_timestamp_in_future: {future_restore_backup.get('blockers')}")
    if "cos_backup_probe_stale" not in (custom_cos_age_backup.get("blockers") or []):
        return fail(f"custom two-hour COS threshold should block three-hour-old evidence: {custom_cos_age_backup.get('blockers')}")
    if custom_cos_age_backup.get("object_storage", {}).get("live_probe_max_age_hours") != 2.0:
        return fail("COS backup plan should expose the configured freshness threshold")
    if "restore_drill_overdue" not in (custom_restore_age_backup.get("blockers") or []):
        return fail(f"custom seven-day restore threshold should block eight-day-old evidence: {custom_restore_age_backup.get('blockers')}")
    if custom_restore_age_backup.get("restore", {}).get("restore_drill_max_age_days") != 7.0:
        return fail("backup plan should expose the configured restore drill freshness threshold")
    if missing_cos_backup.get("backup_ready_for_paid_launch") is not False:
        return fail("paid-launch backup readiness must require recent COS success evidence even when the optional live-probe flag is false")
    if "cos_backup_probe_not_recorded" not in (missing_cos_backup.get("blockers") or []):
        return fail(f"missing paid-launch COS evidence should report cos_backup_probe_not_recorded: {missing_cos_backup.get('blockers')}")
    stale_readiness_items = {item.get("key"): item for item in stale_evidence_readiness.get("items") or []}
    stale_backup_item = stale_readiness_items.get("backup_restore") or {}
    if stale_backup_item.get("status") != "paid_launch_backup_evidence_stale":
        return fail(f"staging should identify freshness-only backup debt without regressing beta: {stale_backup_item}")
    if stale_backup_item.get("severity") != "warning":
        return fail(f"freshness-only backup debt should remain a paid-launch warning in staging: {stale_backup_item}")
    if monitoring.get("production_monitoring_ready") is not True:
        return fail(f"CLS monitoring should be ready when logset/topic and alert policy are configured: {monitoring.get('current_blockers')}")
    if monitoring.get("cloud_monitoring", {}).get("target_ready") is not True:
        return fail("CLS target should be ready")
    if "tencent_cls_live_probe_stale" not in (stale_cls_control.get("cloud_monitoring", {}).get("blocked_by") or []):
        return fail("stale CLS control-plane evidence must block the integrated monitoring contract")
    if "tencent_cls_ingestion_live_probe_stale" not in (
        stale_cls_ingestion.get("cloud_monitoring", {}).get("blocked_by") or []
    ):
        return fail("stale CLS ingestion evidence must block the integrated monitoring contract")
    if "tencent_cls_ingestion_live_probe_timestamp_invalid" not in (
        invalid_cls_ingestion.get("cloud_monitoring", {}).get("blocked_by") or []
    ):
        return fail("invalid CLS ingestion evidence must block the integrated monitoring contract")
    if "tencent_cls_ingestion_live_probe_timestamp_in_future" not in (
        future_cls_ingestion.get("cloud_monitoring", {}).get("blocked_by") or []
    ):
        return fail("future CLS ingestion evidence must block the integrated monitoring contract")
    if "tencent_cls_live_probe_stale" not in (custom_cls_age.get("cloud_monitoring", {}).get("blocked_by") or []):
        return fail("custom CLS evidence threshold must flow through the integrated monitoring contract")
    if custom_cls_age.get("cloud_monitoring", {}).get("live_probe_max_age_hours") != 2.0:
        return fail("integrated CLS status must expose the custom freshness threshold")
    if fallback_cls_age.get("cloud_monitoring", {}).get("target_ready") is not True:
        return fail("invalid integrated CLS threshold must fall back to the safe 24-hour default")
    if fallback_cls_age.get("cloud_monitoring", {}).get("live_probe_max_age_hours") != 24.0:
        return fail("integrated CLS status must expose the fallback freshness threshold")
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


def _seed_provider_monitoring_state(repo: SaaSRepository, now: datetime) -> None:
    owner_hash = "tencent-cloud-integrations-fixture"
    repo.acquire_provider_monitoring_lease(
        scheduler_key="provider-monitor",
        owner_hash=owner_hash,
        lease_seconds=300,
        now_epoch=int(now.timestamp()) - 60,
    )
    repo.complete_provider_monitoring_evaluation(
        scheduler_key="provider-monitor",
        owner_hash=owner_hash,
        evaluated_at=(now - timedelta(minutes=1)).isoformat(),
        exported_at=(now - timedelta(minutes=1)).isoformat(),
        outcome="exported",
        snapshot={"reliability_status": "insufficient_data", "cost_status": "healthy"},
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
