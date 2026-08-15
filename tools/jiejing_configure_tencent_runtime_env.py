#!/usr/bin/env python3
"""Safely update the private Tencent Cloud runtime env for Jiejing staging.

This tool is intentionally conservative:
- it writes only the operator-provided private env file;
- it redacts secret values in all output;
- it does not switch the active Vault provider to Tencent SSM unless explicitly
  requested, because existing eBay refresh tokens may still live in HashiCorp
  Vault and must be migrated first.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
import stat
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.operations_metering import (  # noqa: E402
    PROVIDER_MONITOR_AGGREGATE_KEYS,
    PROVIDER_MONITOR_CONTRACT_VERSION,
    PROVIDER_MONITOR_EVENT_TYPE,
    build_provider_monitoring_aggregate_event,
)


DEFAULT_ENV_FILE = Path("/opt/jiejing-staging/private/tencent-managed.env")
DEFAULT_REGION = "ap-guangzhou"
DEFAULT_SSM_KEYSPACE = "jiejing-staging"
DEFAULT_COS_PREFIX = "jiejing/staging/backups"
DEFAULT_SECRET_TEMPLATE = "{keyspace}-{company_id}-{store_id}-{purpose}-{secret_ref}"
DEFAULT_CLS_PROBE_MAX_AGE_HOURS = 24.0
EVIDENCE_MAX_FUTURE_SKEW_MINUTES = 5.0
PROVIDER_LATENCY_ALARM_NAME = "jiejing-provider-reliability-v1"
PROVIDER_COST_ALARM_NAME = "jiejing-provider-cost-v1"
PROVIDER_ALARM_NAMES = (PROVIDER_LATENCY_ALARM_NAME, PROVIDER_COST_ALARM_NAME)
PROVIDER_ALARM_INDEX_KEYS = {"event_type", "contract_version", "probe", "reliability_status", "cost_status"}
PROVIDER_ALARM_QUERY_WINDOW_MINUTES = 5
PROVIDER_ALARM_REPEAT_MINUTES = 15
PROVIDER_ALARM_PAGE_LIMIT = 100
PROVIDER_ALARM_MAX_PAGES = 5
VAULT_BACKUP_ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{15,239}$")
PROVIDER_CONTROL_ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_TENCENT_REGION",
    "JIEJING_TENCENT_SECRET_ID",
    "JIEJING_TENCENT_SECRET_KEY",
    "JIEJING_TENCENT_TOKEN",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_PROVIDER_ALARM_NOTICE_ID",
)

SENSITIVE_FRAGMENTS = ("SECRET", "TOKEN", "PASSWORD", "DATABASE_URL", "QUEUE_URL", "KEY")
PRIVATE_STATUS_KEYS = {
    "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
    "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
}
KNOWN_KEYS = (
    "JIEJING_TENCENT_REGION",
    "JIEJING_TENCENT_SECRET_ID",
    "JIEJING_TENCENT_SECRET_KEY",
    "JIEJING_TENCENT_TOKEN",
    "JIEJING_POSTGRES_DRIVER_CHECK_LIVE",
    "JIEJING_REDIS_DRIVER_CHECK_LIVE",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED",
    "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED",
    "JIEJING_TENCENT_SSM_KEYSPACE",
    "JIEJING_TENCENT_SSM_SECRET_NAME_TEMPLATE",
    "JIEJING_BACKUP_STORAGE_PROVIDER",
    "JIEJING_COS_BACKUP_ENABLED",
    "JIEJING_COS_REGION",
    "JIEJING_COS_BUCKET",
    "JIEJING_COS_PREFIX",
    "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED",
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_BACKUP_PROBE_MAX_AGE_HOURS",
    "JIEJING_BACKUP_POLICY_CONFIGURED",
    "JIEJING_BACKUP_ALERTS_CONFIGURED",
    "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
    "JIEJING_VAULT_BACKUP_ARTIFACT_ID",
    "JIEJING_VAULT_RESTORE_DRILL_LAST_AT",
    "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED",
    "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED",
    "JIEJING_RESTORE_DRILL_LAST_AT",
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
    "JIEJING_PROVIDER_METRICS_ENABLED",
    "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED",
    "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS",
    "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES",
    "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS",
    "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES",
    "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
    "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
    "JIEJING_PROVIDER_ALARM_NOTICE_ID",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS",
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env_file = Path(args.env_file)
    existing, lines = _read_env_file(env_file)

    provider_control_modes = (
        args.provider_index_status,
        args.dry_run_provider_index,
        args.apply_provider_index,
        args.provider_alarm_status,
        args.dry_run_provider_alarms,
        args.apply_provider_alarms,
        args.verify_provider_cls_probe,
    )
    if sum(bool(value) for value in provider_control_modes) > 1:
        print(json.dumps({"status": "blocked", "blockers": ["select_one_provider_control_mode"], "secret_exposed": False}))
        return 2

    if args.verify_provider_cls_probe:
        return _run_provider_probe_cli(args=args, env_file=env_file, existing=existing, lines=lines)

    if args.provider_index_status or args.dry_run_provider_index or args.apply_provider_index:
        return _run_provider_index_cli(args=args, existing=existing)

    if args.provider_alarm_status or args.dry_run_provider_alarms or args.apply_provider_alarms:
        return _run_provider_alarm_cli(args=args, env_file=env_file, existing=existing, lines=lines)

    if args.record_cls_ingestion_probe_now and not (
        args.enable_cls or existing.get("JIEJING_CLS_ENABLED", "").lower() == "true"
    ):
        raise SystemExit("CLS must be enabled before recording verified ingestion evidence.")

    if args.status and not args.apply:
        _print_status(env_file, existing)
        return 0

    updates = _build_updates(args, existing)
    if not updates:
        _print_status(env_file, existing)
        print("NO_UPDATES=1")
        return 0

    if not args.apply:
        preview = {key: _redact_value(key, value) for key, value in updates.items()}
        print(json.dumps({"status": "dry_run", "env_file": str(env_file), "updates": preview}, ensure_ascii=False, indent=2))
        print("Pass --apply to write these values.")
        return 0

    merged = {**existing, **updates}
    backup_path = _write_env_file(env_file, lines, updates)
    _print_status(env_file, merged)
    print(f"UPDATED=1")
    print(f"ENV_FILE={env_file}")
    print(f"BACKUP_FILE={backup_path}")
    print("SECRET_EXPOSED=false")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure Jiejing Tencent Cloud private runtime env safely.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--status", action="store_true", help="Print redacted env readiness without writing.")
    parser.add_argument("--apply", action="store_true", help="Write updates to the private env file.")

    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--enable-ssm", action="store_true", help="Configure Tencent SSM env keys without switching provider.")
    parser.add_argument(
        "--switch-vault-provider",
        action="store_true",
        help="Explicitly set JIEJING_VAULT_PROVIDER=tencent_ssm. Use only after Vault secrets are migrated.",
    )
    parser.add_argument("--ssm-keyspace", default=DEFAULT_SSM_KEYSPACE)
    parser.add_argument("--ssm-secret-name-template", default=DEFAULT_SECRET_TEMPLATE)
    parser.add_argument("--tencent-secret-id-env", help="Read Tencent SecretId from this process env var.")
    parser.add_argument("--tencent-secret-key-env", help="Read Tencent SecretKey from this process env var.")
    parser.add_argument("--tencent-token-env", help="Read temporary Tencent token from this process env var.")
    parser.add_argument("--prompt-tencent-credentials", action="store_true", help="Prompt for Tencent credentials without echoing SecretKey.")
    parser.add_argument(
        "--enable-managed-db-queue-live-checks",
        action="store_true",
        help="Persist live driver checks for managed Postgres and Redis status.",
    )

    parser.add_argument("--enable-cos", action="store_true")
    parser.add_argument("--cos-bucket")
    parser.add_argument("--cos-region", default=DEFAULT_REGION)
    parser.add_argument("--cos-prefix", default=DEFAULT_COS_PREFIX)
    parser.add_argument("--record-cos-probe-now", action="store_true")

    parser.add_argument("--enable-cls", action="store_true")
    parser.add_argument("--cls-logset-id")
    parser.add_argument("--cls-topic-id")
    parser.add_argument("--cls-region", default=DEFAULT_REGION)
    parser.add_argument("--cls-alert-policy-configured", action="store_true")
    parser.add_argument("--record-cls-probe-now", action="store_true")
    parser.add_argument(
        "--cls-probe-max-age-hours",
        default=str(int(DEFAULT_CLS_PROBE_MAX_AGE_HOURS)),
        help="Maximum age for verified CLS control-plane and ingestion evidence (default: 24).",
    )
    parser.add_argument(
        "--record-cls-ingestion-probe-now",
        action="store_true",
        help="Record evidence only after a synthetic CLS upload was successfully found by SearchLog.",
    )
    parser.add_argument(
        "--provider-index-status",
        action="store_true",
        help="Read the additive provider index contract without changing cloud or env state.",
    )
    parser.add_argument(
        "--dry-run-provider-index",
        action="store_true",
        help="Plan the additive provider index merge using read-only CLS calls.",
    )
    parser.add_argument(
        "--apply-provider-index",
        action="store_true",
        help="Explicitly add only missing provider aggregate index keys, then read them back.",
    )
    parser.add_argument(
        "--provider-alarm-status",
        action="store_true",
        help="Read the provider alarm/index contract without changing cloud or env state.",
    )
    parser.add_argument(
        "--dry-run-provider-alarms",
        action="store_true",
        help="Plan provider alarm create/modify/noop actions using read-only CLS calls.",
    )
    parser.add_argument(
        "--apply-provider-alarms",
        action="store_true",
        help="Explicitly create/modify only the two provider aggregate alarms, then read them back.",
    )
    parser.add_argument(
        "--provider-alarm-notice-id-env",
        help="Read an existing CLS notice-route identifier from a process env var without printing it.",
    )
    parser.add_argument(
        "--verify-provider-cls-probe",
        action="store_true",
        help="Explicitly upload one safe probe aggregate and verify it with SearchLog; it cannot match provider alarms.",
    )

    parser.add_argument("--backup-policy-configured", action="store_true")
    parser.add_argument("--backup-alerts-configured", action="store_true")
    parser.add_argument("--vault-backup-policy-configured", action="store_true")
    parser.add_argument(
        "--record-vault-recovery-evidence",
        action="store_true",
        help="Record a completed encrypted Vault backup and isolated restore/unseal/sentinel drill.",
    )
    parser.add_argument(
        "--record-vault-restore-drill-evidence",
        action="store_true",
        help=(
            "Record an actually completed encrypted Vault backup and isolated restore/unseal/sentinel drill "
            "without claiming the production 3-share/2-threshold offline-custody boundary."
        ),
    )
    parser.add_argument(
        "--vault-backup-artifact-id-env",
        help="Read the verified private backup artifact identifier from this process env var.",
    )
    parser.add_argument(
        "--vault-unseal-key-shares",
        type=int,
        default=0,
        help="Value-free evidence of the initialized Vault key-share count; paid launch requires at least 3.",
    )
    parser.add_argument(
        "--vault-unseal-key-threshold",
        type=int,
        default=0,
        help="Value-free evidence of the Vault unseal threshold; paid launch requires at least 2.",
    )
    parser.add_argument(
        "--vault-offline-share-custody-verified",
        action="store_true",
        help="Confirm that unseal shares are split across operator-controlled encrypted offline storage.",
    )
    parser.add_argument("--record-restore-drill-now", action="store_true")
    parser.add_argument(
        "--production-release-charge-flag-reviewed",
        action="store_true",
        help="Record that the public charging switch was reviewed; this does not enable charging.",
    )
    parser.add_argument(
        "--production-release-real-write-flag-reviewed",
        action="store_true",
        help="Record that the real-platform-write switch was reviewed; this does not enable writes.",
    )
    parser.add_argument(
        "--production-support-refund-policy-reviewed",
        action="store_true",
        help="Record review of the published support and refund policy surfaces.",
    )
    parser.add_argument(
        "--production-merchant-surface-copy-scan-passed",
        action="store_true",
        help="Record a passed merchant-surface internal-copy scan.",
    )
    return parser.parse_args(argv)


def _read_env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.exists():
        return {}, []
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values, lines


def _provider_control_values(existing: dict[str, str]) -> dict[str, str]:
    """Return only allowlisted control-plane values; private env-file values win."""

    values: dict[str, str] = {}
    for key in PROVIDER_CONTROL_ENV_KEYS:
        value = str(existing.get(key) or os.environ.get(key) or "")
        if value:
            values[key] = value
    return values


def _build_updates(args: argparse.Namespace, existing: dict[str, str]) -> dict[str, str]:
    now = _now_iso()
    updates: dict[str, str] = {"JIEJING_TENCENT_REGION": args.region}

    if args.enable_ssm or args.switch_vault_provider:
        updates.update(
            {
                "JIEJING_VAULT_ENABLED": "true",
                "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED": "true",
                "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED": "true",
                "JIEJING_TENCENT_SSM_KEYSPACE": args.ssm_keyspace,
                "JIEJING_TENCENT_SSM_SECRET_NAME_TEMPLATE": args.ssm_secret_name_template,
            }
        )
    if args.switch_vault_provider:
        updates["JIEJING_VAULT_PROVIDER"] = "tencent_ssm"
    elif "JIEJING_VAULT_PROVIDER" not in existing:
        updates["JIEJING_VAULT_PROVIDER"] = "vault"

    secret_id, secret_key, token = _resolve_tencent_credentials(args)
    if secret_id:
        updates["JIEJING_TENCENT_SECRET_ID"] = secret_id
    if secret_key:
        updates["JIEJING_TENCENT_SECRET_KEY"] = secret_key
    if token:
        updates["JIEJING_TENCENT_TOKEN"] = token

    if args.enable_managed_db_queue_live_checks:
        updates["JIEJING_POSTGRES_DRIVER_CHECK_LIVE"] = "true"
        updates["JIEJING_REDIS_DRIVER_CHECK_LIVE"] = "true"

    if args.enable_cos or args.cos_bucket:
        updates.update(
            {
                "JIEJING_BACKUP_STORAGE_PROVIDER": "cos",
                "JIEJING_COS_BACKUP_ENABLED": "true",
                "JIEJING_COS_REGION": args.cos_region,
                "JIEJING_COS_PREFIX": args.cos_prefix.strip("/"),
                "JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED": "true",
            }
        )
        if args.cos_bucket:
            updates["JIEJING_COS_BUCKET"] = args.cos_bucket.strip()
    if args.record_cos_probe_now:
        updates["JIEJING_COS_BACKUP_LAST_SUCCESS_AT"] = now

    cls_action = bool(
        args.enable_cls
        or args.cls_logset_id
        or args.cls_topic_id
        or args.cls_alert_policy_configured
        or args.record_cls_probe_now
        or args.record_cls_ingestion_probe_now
    )
    if args.enable_cls or args.cls_logset_id or args.cls_topic_id:
        updates.update(
            {
                "JIEJING_CLS_ENABLED": "true",
                "JIEJING_CLS_REGION": args.cls_region,
                "JIEJING_CLS_LIVE_PROBE_REQUIRED": "true",
            }
        )
        if args.cls_logset_id:
            updates["JIEJING_CLS_LOGSET_ID"] = args.cls_logset_id.strip()
        if args.cls_topic_id:
            updates["JIEJING_CLS_TOPIC_ID"] = args.cls_topic_id.strip()
    if args.cls_alert_policy_configured:
        updates["JIEJING_CLS_ALERT_POLICY_CONFIGURED"] = "true"
    if args.record_cls_probe_now:
        updates["JIEJING_CLS_LIVE_PROBE_LAST_AT"] = now
    if args.record_cls_ingestion_probe_now:
        updates["JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED"] = "true"
        updates["JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT"] = now
    if cls_action:
        updates["JIEJING_CLS_PROBE_MAX_AGE_HOURS"] = _normalized_positive_float_arg(
            args.cls_probe_max_age_hours,
            "--cls-probe-max-age-hours",
        )

    if args.backup_policy_configured:
        updates["JIEJING_BACKUP_POLICY_CONFIGURED"] = "true"
    if args.backup_alerts_configured:
        updates["JIEJING_BACKUP_ALERTS_CONFIGURED"] = "true"
    if args.vault_backup_policy_configured:
        updates["JIEJING_VAULT_BACKUP_POLICY_CONFIGURED"] = "true"
    if args.record_vault_restore_drill_evidence or args.record_vault_recovery_evidence:
        artifact_id = _read_named_env(args.vault_backup_artifact_id_env)
        if not _valid_vault_backup_artifact_id(artifact_id):
            raise SystemExit("Vault backup artifact evidence is missing or invalid.")
        if args.record_vault_recovery_evidence:
            if (
                args.vault_unseal_key_shares < 3
                or args.vault_unseal_key_threshold < 2
                or args.vault_unseal_key_threshold > args.vault_unseal_key_shares
                or not args.vault_offline_share_custody_verified
            ):
                raise SystemExit("Vault recovery evidence requires 3-or-more shares, a 2-or-more threshold, and offline custody.")
        elif (
            args.vault_unseal_key_shares < 1
            or args.vault_unseal_key_threshold < 1
            or args.vault_unseal_key_threshold > args.vault_unseal_key_shares
        ):
            raise SystemExit("Vault restore-drill evidence requires the actual positive share count and threshold.")
        updates.update(
            {
                "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED": "true",
                "JIEJING_VAULT_BACKUP_ARTIFACT_ID": artifact_id,
                "JIEJING_VAULT_RESTORE_DRILL_LAST_AT": now,
                "JIEJING_VAULT_RESTORE_MANUAL_UNSEAL_VERIFIED": "true",
                "JIEJING_VAULT_RESTORE_SENTINEL_RESOLVE_VERIFIED": "true",
                "JIEJING_VAULT_UNSEAL_KEY_SHARES": str(args.vault_unseal_key_shares),
                "JIEJING_VAULT_UNSEAL_KEY_THRESHOLD": str(args.vault_unseal_key_threshold),
                "JIEJING_VAULT_OFFLINE_SHARE_CUSTODY_VERIFIED": (
                    "true" if args.vault_offline_share_custody_verified else "false"
                ),
            }
        )
    if args.record_restore_drill_now:
        updates["JIEJING_RESTORE_DRILL_LAST_AT"] = now
    if args.production_release_charge_flag_reviewed:
        updates["JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED"] = "true"
    if args.production_release_real_write_flag_reviewed:
        updates["JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED"] = "true"
    if args.production_support_refund_policy_reviewed:
        updates["JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED"] = "true"
    if args.production_merchant_surface_copy_scan_passed:
        updates["JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED"] = "true"

    return {key: value for key, value in updates.items() if value != existing.get(key)}


def _resolve_tencent_credentials(args: argparse.Namespace) -> tuple[str, str, str]:
    secret_id = _read_named_env(args.tencent_secret_id_env)
    secret_key = _read_named_env(args.tencent_secret_key_env)
    token = _read_named_env(args.tencent_token_env)
    if args.prompt_tencent_credentials:
        if not secret_id:
            secret_id = input("Tencent SecretId: ").strip()
        if not secret_key:
            secret_key = getpass.getpass("Tencent SecretKey: ").strip()
        if not token:
            token = getpass.getpass("Tencent temporary token (optional, press Enter if none): ").strip()
    return secret_id, secret_key, token


def _read_named_env(name: str | None) -> str:
    if not name:
        return ""
    return os.environ.get(name, "").strip()


def _valid_vault_backup_artifact_id(value: str) -> bool:
    return bool(
        VAULT_BACKUP_ARTIFACT_ID_PATTERN.fullmatch(value)
        and ".." not in value
        and "//" not in value
        and not value.endswith("/")
    )


def _write_env_file(path: Path, original_lines: list[str], updates: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError("refusing to write private env through a symbolic link")
    backup_suffix = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{time.time_ns() % 1_000_000_000}"
    if path.exists():
        backup = path.with_name(f"{path.name}.bak.{backup_suffix}")
        _write_private_text(backup, path.read_text(encoding="utf-8"), exclusive=True)
    else:
        backup = path.with_name(f"{path.name}.bak.created.{backup_suffix}")
        _write_private_text(backup, "", exclusive=True)

    pending = dict(updates)
    rendered: list[str] = []
    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in pending:
                rendered.append(f"{key}={pending.pop(key)}")
                continue
        rendered.append(line)

    if pending:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.append("# Managed Tencent Cloud runtime binding. Written by jiejing_configure_tencent_runtime_env.py.")
        for key in KNOWN_KEYS:
            if key in pending:
                rendered.append(f"{key}={pending.pop(key)}")
        for key in sorted(pending):
            rendered.append(f"{key}={pending[key]}")

    content = "\n".join(rendered).rstrip() + "\n"
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    try:
        _write_private_text(temporary, content, exclusive=True)
        os.replace(temporary, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def _write_private_text(path: Path, content: str, *, exclusive: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _print_status(env_file: Path, values: dict[str, str]) -> None:
    groups = {
        "tencent_api_credentials": [
            "JIEJING_TENCENT_SECRET_ID",
            "JIEJING_TENCENT_SECRET_KEY",
        ],
        "managed_database_queue": [
            "JIEJING_POSTGRES_DRIVER_CHECK_LIVE",
            "JIEJING_REDIS_DRIVER_CHECK_LIVE",
        ],
        "tencent_ssm": [
            "JIEJING_VAULT_PROVIDER",
            "JIEJING_TENCENT_SSM_LIVE_RESOLVE_ENABLED",
            "JIEJING_TENCENT_SSM_LIVE_WRITE_ENABLED",
            "JIEJING_TENCENT_SSM_KEYSPACE",
        ],
        "cos_backup": [
            "JIEJING_COS_BACKUP_ENABLED",
            "JIEJING_COS_REGION",
            "JIEJING_COS_BUCKET",
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
        ],
        "cls_monitoring": [
            "JIEJING_CLS_ENABLED",
            "JIEJING_CLS_REGION",
            "JIEJING_CLS_LOGSET_ID",
            "JIEJING_CLS_TOPIC_ID",
            "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
            "JIEJING_CLS_LIVE_PROBE_LAST_AT",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
        ],
        "provider_monitoring": [
            "JIEJING_PROVIDER_METRICS_ENABLED",
            "JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED",
            "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS",
            "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES",
            "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS",
            "JIEJING_PROVIDER_MONITOR_EVIDENCE_MAX_AGE_MINUTES",
            "JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR",
            "JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR",
            "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
            "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
            "JIEJING_PROVIDER_ALARM_VERIFICATION_MAX_AGE_DAYS",
        ],
    }
    evidence_now = datetime.now(timezone.utc)
    cls_probe_evidence = _cls_probe_evidence_status(values, evidence_now)
    status = {
        "env_file": str(env_file),
        "exists": env_file.exists(),
        "groups": {name: _group_status(values, keys) for name, keys in groups.items()},
        "cls_probe_evidence": cls_probe_evidence,
        "blockers": _blockers(values, cls_probe_evidence),
        "active_vault_provider": values.get("JIEJING_VAULT_PROVIDER", ""),
        "safe_to_switch_vault_provider": False,
        "secret_exposed": False,
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))


def _group_status(values: dict[str, str], keys: list[str]) -> dict[str, Any]:
    items = {key: _redact_value(key, values.get(key, "")) for key in keys}
    return {
        "ready": all(bool(values.get(key)) for key in keys),
        "items": items,
    }


def _blockers(values: dict[str, str], cls_probe_evidence: dict[str, Any]) -> list[str]:
    blockers = []
    if not values.get("JIEJING_TENCENT_SECRET_ID") or not values.get("JIEJING_TENCENT_SECRET_KEY"):
        blockers.append("tencent_api_credentials_missing")
    if values.get("JIEJING_COS_BACKUP_ENABLED", "").lower() == "true":
        if not values.get("JIEJING_COS_BUCKET"):
            blockers.append("JIEJING_COS_BUCKET")
        if values.get("JIEJING_COS_BACKUP_LIVE_PROBE_REQUIRED", "").lower() == "true" and not values.get(
            "JIEJING_COS_BACKUP_LAST_SUCCESS_AT"
        ):
            blockers.append("cos_backup_probe_not_recorded")
    else:
        blockers.append("cos_backup_not_enabled")
    if values.get("JIEJING_CLS_ENABLED", "").lower() == "true":
        if not values.get("JIEJING_CLS_LOGSET_ID"):
            blockers.append("JIEJING_CLS_LOGSET_ID")
        if not values.get("JIEJING_CLS_TOPIC_ID"):
            blockers.append("JIEJING_CLS_TOPIC_ID")
        if values.get("JIEJING_CLS_ALERT_POLICY_CONFIGURED", "").lower() != "true":
            blockers.append("JIEJING_CLS_ALERT_POLICY_CONFIGURED")
        if values.get("JIEJING_CLS_LIVE_PROBE_REQUIRED", "").lower() == "true":
            control_plane = cls_probe_evidence["control_plane"]
            ingestion = cls_probe_evidence["ingestion"]
            if not control_plane["timestamp_present"]:
                blockers.append("tencent_cls_live_probe_not_recorded")
            elif not control_plane["timestamp_valid"]:
                blockers.append("tencent_cls_live_probe_timestamp_invalid")
            elif control_plane["timestamp_in_future"]:
                blockers.append("tencent_cls_live_probe_timestamp_in_future")
            elif not control_plane["fresh"]:
                blockers.append("tencent_cls_live_probe_stale")
            if not (
                values.get("JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED", "").lower() == "true"
                and ingestion["timestamp_present"]
            ):
                blockers.append("tencent_cls_ingestion_live_probe_not_passed")
            elif not ingestion["timestamp_valid"]:
                blockers.append("tencent_cls_ingestion_live_probe_timestamp_invalid")
            elif ingestion["timestamp_in_future"]:
                blockers.append("tencent_cls_ingestion_live_probe_timestamp_in_future")
            elif not ingestion["fresh"]:
                blockers.append("tencent_cls_ingestion_live_probe_stale")
    else:
        blockers.append("cls_not_enabled")
    if values.get("JIEJING_PROVIDER_METRICS_ENABLED", "").lower() != "true":
        blockers.append("provider_metrics_not_enabled")
    if values.get("JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED", "").lower() != "true":
        blockers.append("provider_monitor_scheduler_not_enabled")
    if not _valid_provider_cost_budgets(values):
        blockers.append("provider_cost_budget_not_configured")
    if not values.get("JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT"):
        blockers.append("provider_latency_alarm_verification_not_recorded")
    if not values.get("JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT"):
        blockers.append("provider_cost_alarm_verification_not_recorded")
    if values.get("JIEJING_VAULT_PROVIDER") != "tencent_ssm":
        blockers.append("vault_provider_not_switched_to_tencent_ssm")
    return blockers


def _redact_value(key: str, value: str) -> str:
    if not value:
        return ""
    upper_key = key.upper()
    if (
        any(fragment in upper_key for fragment in SENSITIVE_FRAGMENTS)
        or upper_key.endswith("_ID")
        or upper_key.endswith("_AT")
        or key in PRIVATE_STATUS_KEYS
    ):
        return "[set]"
    return value


def _valid_provider_cost_budgets(values: dict[str, str]) -> bool:
    try:
        warning = int(str(values.get("JIEJING_PROVIDER_DAILY_COST_WARNING_MINOR") or "").strip())
        critical = int(str(values.get("JIEJING_PROVIDER_DAILY_COST_CRITICAL_MINOR") or "").strip())
    except (TypeError, ValueError):
        return False
    return warning > 0 and critical >= warning


def _normalized_positive_float_arg(raw: str, option_name: str) -> str:
    try:
        value = float(str(raw).strip())
    except ValueError as exc:
        raise SystemExit(f"{option_name} must be a positive finite number.") from exc
    if not math.isfinite(value) or value <= 0:
        raise SystemExit(f"{option_name} must be a positive finite number.")
    return f"{value:g}"


def _positive_float(value: str, default: float) -> float:
    try:
        parsed = float(str(value or "").strip())
    except ValueError:
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        return default
    return parsed


def _cls_probe_evidence_status(values: dict[str, str], now_utc: datetime) -> dict[str, Any]:
    max_age_hours = _positive_float(
        values.get("JIEJING_CLS_PROBE_MAX_AGE_HOURS", ""),
        DEFAULT_CLS_PROBE_MAX_AGE_HOURS,
    )
    return {
        "max_age_hours": max_age_hours,
        "control_plane": _timestamp_evidence_status(
            values.get("JIEJING_CLS_LIVE_PROBE_LAST_AT", "").strip(),
            max_age_hours,
            now_utc,
        ),
        "ingestion": _timestamp_evidence_status(
            values.get("JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT", "").strip(),
            max_age_hours,
            now_utc,
        ),
    }


def _timestamp_evidence_status(value: str, max_age_hours: float, now_utc: datetime) -> dict[str, Any]:
    age_hours: float | None = None
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            age_hours = (now_utc.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
    timestamp_valid = bool(value and age_hours is not None)
    timestamp_in_future = bool(
        timestamp_valid and age_hours is not None and age_hours < -(EVIDENCE_MAX_FUTURE_SKEW_MINUTES / 60)
    )
    return {
        "timestamp_present": bool(value),
        "timestamp_valid": timestamp_valid,
        "timestamp_in_future": timestamp_in_future,
        "fresh": bool(
            timestamp_valid
            and age_hours is not None
            and not timestamp_in_future
            and age_hours <= max_age_hours
        ),
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
    }


def provider_alarm_specs(*, logset_id: str, topic_id: str, notice_id: str = "") -> dict[str, dict[str, Any]]:
    """Return the two deterministic CLS alarm payloads without provider or merchant dimensions."""

    queries = {
        "latency": (
            f'event_type:"{PROVIDER_MONITOR_EVENT_TYPE}" AND probe:"false" AND '
            '(reliability_status:"attention" OR reliability_status:"critical")'
        ),
        "cost": (
            f'event_type:"{PROVIDER_MONITOR_EVENT_TYPE}" AND probe:"false" AND '
            '(cost_status:"attention" OR cost_status:"critical")'
        ),
    }
    names = {"latency": PROVIDER_LATENCY_ALARM_NAME, "cost": PROVIDER_COST_ALARM_NAME}
    specs: dict[str, dict[str, Any]] = {}
    for key in ("latency", "cost"):
        payload: dict[str, Any] = {
            "Name": names[key],
            "AlarmTargets": [
                {
                    "LogsetId": logset_id,
                    "TopicId": topic_id,
                    "Query": queries[key],
                    "Number": 1,
                    "StartTimeOffset": -PROVIDER_ALARM_QUERY_WINDOW_MINUTES,
                    "EndTimeOffset": 0,
                }
            ],
            "MonitorTime": {"Type": "Period", "Time": PROVIDER_ALARM_QUERY_WINDOW_MINUTES},
            "TriggerCount": 1,
            "AlarmPeriod": PROVIDER_ALARM_REPEAT_MINUTES,
            "Condition": "$1.__QUERYCOUNT__ > 0",
            "AlarmLevel": 0,
            "Status": True,
            "GroupTriggerStatus": False,
            "MonitorObjectType": 0,
        }
        if notice_id:
            payload["AlarmNoticeIds"] = [notice_id]
        specs[key] = payload
    return specs


def operate_provider_cls_alarms(
    *,
    client: Any,
    request_factory: Any,
    logset_id: str,
    topic_id: str,
    notice_id: str = "",
    mode: str = "status",
) -> dict[str, Any]:
    """Describe, plan or explicitly apply the two provider aggregate alarms."""

    if mode not in {"status", "dry_run", "apply"}:
        raise ValueError("unsupported provider alarm operator mode")
    index = _describe_provider_index(client, request_factory, topic_id)
    alarms, inventory_complete = _describe_provider_alarms(client, request_factory)
    specs = provider_alarm_specs(logset_id=logset_id, topic_id=topic_id, notice_id=notice_id)
    index_status = _provider_index_status(index)
    plans, blockers = _plan_provider_alarms(
        alarms=alarms,
        specs=specs,
        notice_id=notice_id,
        index_ready=index_status["ready"],
        inventory_complete=inventory_complete,
    )
    result = {
        "status": "blocked" if blockers else ("planned" if mode == "dry_run" else "verified"),
        "mode": mode,
        "index": index_status,
        "alarms": [_safe_alarm_plan(key, plans[key]) for key in ("latency", "cost")],
        "blockers": blockers,
        "cloud_write_performed": False,
        "alarm_readback_verified": False,
        "notification_test_sent": False,
        "index_modified": False,
        "resource_ids_exposed": False,
        "secret_exposed": False,
    }
    if mode != "apply" or blockers:
        if mode == "status" and not blockers and all(plans[key]["readback_ready"] for key in plans):
            result["alarm_readback_verified"] = True
        return result

    for key in ("latency", "cost"):
        plan = plans[key]
        action = plan["action"]
        if action == "create":
            client.CreateAlarm(request_factory("CreateAlarmRequest", specs[key]))
        elif action == "modify":
            current = plan["current"]
            payload = dict(specs[key])
            payload["AlarmId"] = str(current.get("AlarmId") or "")
            notice_field, notice_value = _alarm_notice_binding(current)
            payload.pop("AlarmNoticeIds", None)
            if notice_field:
                payload[notice_field] = notice_value
            client.ModifyAlarm(request_factory("ModifyAlarmRequest", payload))
    result["cloud_write_performed"] = any(plans[key]["action"] in {"create", "modify"} for key in plans)

    readback_alarms, readback_complete = _describe_provider_alarms(client, request_factory)
    readback_plans, readback_blockers = _plan_provider_alarms(
        alarms=readback_alarms,
        specs=specs,
        notice_id=notice_id,
        index_ready=index_status["ready"],
        inventory_complete=readback_complete,
        readback_only=True,
    )
    result["alarms"] = [_safe_alarm_plan(key, readback_plans[key]) for key in ("latency", "cost")]
    result["blockers"] = readback_blockers
    result["alarm_readback_verified"] = not readback_blockers and all(
        readback_plans[key]["readback_ready"] for key in readback_plans
    )
    result["status"] = "verified" if result["alarm_readback_verified"] else "blocked"
    return result


def operate_provider_cls_index(
    *,
    client: Any,
    request_factory: Any,
    topic_id: str,
    mode: str = "status",
) -> dict[str, Any]:
    """Describe or plan an additive-only provider aggregate index migration."""

    if mode not in {"status", "dry_run", "apply"}:
        raise ValueError("unsupported provider index operator mode")
    index = _describe_provider_index(client, request_factory, topic_id)
    rule = index.get("Rule") if isinstance(index.get("Rule"), dict) else {}
    key_value = rule.get("KeyValue") if isinstance(rule.get("KeyValue"), dict) else {}
    existing_rows = [item for item in (key_value.get("KeyValues") or []) if isinstance(item, dict)]
    existing_names = [str(item.get("Key") or "") for item in existing_rows if item.get("Key")]
    duplicate_names = sorted({name for name in existing_names if existing_names.count(name) > 1})
    missing_keys = sorted(PROVIDER_ALARM_INDEX_KEYS - set(existing_names))
    type_mismatch_keys = _provider_index_required_type_mismatches(existing_rows)
    fulltext_enabled = isinstance(rule.get("FullText"), dict)
    blockers: list[str] = []
    if index.get("Status") is not True:
        blockers.append("provider_index_not_enabled")
    if fulltext_enabled:
        blockers.append("provider_index_fulltext_must_remain_disabled")
    if duplicate_names:
        blockers.append("provider_index_duplicate_key_names")
    if type_mismatch_keys:
        blockers.append("provider_index_required_key_type_mismatch")
    if mode == "status" and missing_keys:
        blockers.append("provider_index_required_keys_missing")
    status = "blocked" if blockers else ("planned" if mode == "dry_run" and missing_keys else "verified")
    result = {
        "status": status,
        "mode": mode,
        "existing_key_count": len(existing_rows),
        "required_key_count": len(PROVIDER_ALARM_INDEX_KEYS),
        "configured_required_key_count": len(PROVIDER_ALARM_INDEX_KEYS) - len(missing_keys) - len(type_mismatch_keys),
        "add_key_count": len(missing_keys),
        "missing_keys": missing_keys,
        "duplicate_key_count": len(duplicate_names),
        "type_mismatch_key_count": len(type_mismatch_keys),
        "preserves_existing_fields": True,
        "delete_key_count": 0,
        "fulltext_enabled": fulltext_enabled,
        "fulltext_will_change": False,
        "cloud_write_performed": False,
        "index_modified": False,
        "index_readback_verified": not missing_keys and not blockers,
        "blockers": blockers,
        "resource_ids_exposed": False,
        "secret_exposed": False,
    }
    if mode != "apply" or blockers or not missing_keys:
        return result

    merged_rule = deepcopy(rule)
    merged_key_value = deepcopy(key_value)
    value_template = _provider_index_text_value_template(existing_rows)
    merged_key_value["KeyValues"] = deepcopy(existing_rows) + [
        {"Key": key, "Value": deepcopy(value_template)} for key in missing_keys
    ]
    merged_rule["KeyValue"] = merged_key_value
    payload: dict[str, Any] = {"TopicId": topic_id, "Status": True, "Rule": merged_rule}
    for optional_field in ("IncludeInternalFields", "MetadataFlag", "CoverageField"):
        if optional_field in index:
            payload[optional_field] = deepcopy(index[optional_field])
    client.ModifyIndex(request_factory("ModifyIndexRequest", payload))
    readback = _describe_provider_index(client, request_factory, topic_id)
    readback_rule = readback.get("Rule") if isinstance(readback.get("Rule"), dict) else {}
    readback_key_value = (
        readback_rule.get("KeyValue") if isinstance(readback_rule.get("KeyValue"), dict) else {}
    )
    readback_rows = [
        item for item in (readback_key_value.get("KeyValues") or []) if isinstance(item, dict)
    ]
    original_by_name = {str(item.get("Key") or ""): item for item in existing_rows if item.get("Key")}
    readback_by_name = {str(item.get("Key") or ""): item for item in readback_rows if item.get("Key")}
    readback_names = {str(item.get("Key") or "") for item in readback_rows if item.get("Key")}
    readback_missing = sorted(PROVIDER_ALARM_INDEX_KEYS - readback_names)
    readback_type_mismatches = _provider_index_required_type_mismatches(readback_rows)
    existing_fields_preserved = all(readback_by_name.get(key) == item for key, item in original_by_name.items())
    deleted_key_count = len([key for key in original_by_name if key not in readback_by_name])
    fulltext_preserved = isinstance(readback_rule.get("FullText"), dict) == fulltext_enabled
    readback_blockers: list[str] = []
    if readback.get("Status") is not True:
        readback_blockers.append("provider_index_readback_not_enabled")
    if readback_missing:
        readback_blockers.append("provider_index_readback_required_keys_missing")
    if readback_type_mismatches:
        readback_blockers.append("provider_index_readback_required_key_type_mismatch")
    if not existing_fields_preserved:
        readback_blockers.append("provider_index_readback_existing_fields_changed")
    if not fulltext_preserved:
        readback_blockers.append("provider_index_readback_fulltext_changed")
    result.update(
        {
            "status": "blocked" if readback_blockers else "verified",
            "configured_required_key_count": len(PROVIDER_ALARM_INDEX_KEYS)
            - len(readback_missing)
            - len(readback_type_mismatches),
            "missing_keys": readback_missing,
            "type_mismatch_key_count": len(readback_type_mismatches),
            "preserves_existing_fields": existing_fields_preserved,
            "delete_key_count": deleted_key_count,
            "fulltext_will_change": not fulltext_preserved,
            "cloud_write_performed": True,
            "index_modified": True,
            "index_readback_verified": not readback_blockers,
            "blockers": readback_blockers,
        }
    )
    return result


def _provider_index_text_value_template(existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    for item in existing_rows:
        value = item.get("Value") if isinstance(item.get("Value"), dict) else {}
        if str(value.get("Type") or "").lower() != "text":
            continue
        template = {"Type": "text"}
        for field in ("Tokenizer", "SqlFlag", "ContainZH", "OpenIndexForChildOnly"):
            if field in value:
                template[field] = deepcopy(value[field])
        return template
    return {
        "Type": "text",
        "Tokenizer": "@&?|#=()'\",;:<>[]{}/ \n\t\r",
        "SqlFlag": True,
        "ContainZH": False,
    }


def _provider_index_required_type_mismatches(existing_rows: list[dict[str, Any]]) -> list[str]:
    mismatches: list[str] = []
    for item in existing_rows:
        key = str(item.get("Key") or "")
        if key not in PROVIDER_ALARM_INDEX_KEYS:
            continue
        value = item.get("Value") if isinstance(item.get("Value"), dict) else {}
        if str(value.get("Type") or "").lower() != "text":
            mismatches.append(key)
    return sorted(set(mismatches))


def _describe_provider_index(client: Any, request_factory: Any, topic_id: str) -> dict[str, Any]:
    response = client.DescribeIndex(request_factory("DescribeIndexRequest", {"TopicId": topic_id}))
    return _plain_response(response)


def _describe_provider_alarms(client: Any, request_factory: Any) -> tuple[list[dict[str, Any]], bool]:
    alarms: list[dict[str, Any]] = []
    total_count = 0
    for page in range(PROVIDER_ALARM_MAX_PAGES):
        payload = {"Offset": page * PROVIDER_ALARM_PAGE_LIMIT, "Limit": PROVIDER_ALARM_PAGE_LIMIT}
        response = _plain_response(client.DescribeAlarms(request_factory("DescribeAlarmsRequest", payload)))
        page_alarms = response.get("Alarms") if isinstance(response.get("Alarms"), list) else []
        alarms.extend(item for item in page_alarms if isinstance(item, dict))
        total_count = max(total_count, _safe_int_value(response.get("TotalCount")))
        if len(page_alarms) < PROVIDER_ALARM_PAGE_LIMIT or len(alarms) >= total_count:
            return alarms, True
    return alarms, bool(total_count and len(alarms) >= total_count)


def _provider_index_status(index: dict[str, Any]) -> dict[str, Any]:
    rule = index.get("Rule") if isinstance(index.get("Rule"), dict) else {}
    key_value = rule.get("KeyValue") if isinstance(rule.get("KeyValue"), dict) else {}
    configured = {
        str(item.get("Key") or "")
        for item in (key_value.get("KeyValues") or [])
        if isinstance(item, dict) and item.get("Key")
    }
    missing = sorted(PROVIDER_ALARM_INDEX_KEYS - configured)
    enabled = index.get("Status") is True
    return {
        "ready": bool(enabled and not missing),
        "enabled": enabled,
        "fulltext_enabled": isinstance(rule.get("FullText"), dict),
        "required_key_count": len(PROVIDER_ALARM_INDEX_KEYS),
        "configured_required_key_count": len(PROVIDER_ALARM_INDEX_KEYS) - len(missing),
        "missing_keys": missing,
        "modified": False,
    }


def _plan_provider_alarms(
    *,
    alarms: list[dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    notice_id: str,
    index_ready: bool,
    inventory_complete: bool,
    readback_only: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    plans: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    if not index_ready:
        blockers.append("provider_alarm_index_contract_incomplete")
    if not inventory_complete:
        blockers.append("provider_alarm_inventory_truncated")
    for key, spec in specs.items():
        matches = [alarm for alarm in alarms if str(alarm.get("Name") or "") == str(spec["Name"])]
        plan: dict[str, Any] = {
            "action": "blocked",
            "match_count": len(matches),
            "readback_ready": False,
            "current": matches[0] if len(matches) == 1 else {},
            "drift_fields": [],
        }
        prefix = f"provider_{key}_alarm"
        if len(matches) > 1:
            blockers.append(f"{prefix}_duplicate_name")
        elif len(matches) == 0:
            if readback_only:
                blockers.append(f"{prefix}_readback_missing")
            elif not notice_id:
                blockers.append(f"{prefix}_notice_route_required_for_create")
            else:
                plan["action"] = "create"
        else:
            current = matches[0]
            notice_field, notice_value = _alarm_notice_binding(current)
            notice_ready = bool(notice_field and notice_value)
            if not notice_ready:
                blockers.append(f"{prefix}_notice_route_missing")
            drift_fields = _alarm_drift_fields(current, spec)
            plan["drift_fields"] = drift_fields
            plan["readback_ready"] = not drift_fields and notice_ready
            if plan["readback_ready"]:
                plan["action"] = "noop"
            elif notice_ready and not readback_only:
                plan["action"] = "modify"
            elif readback_only:
                blockers.append(f"{prefix}_readback_mismatch")
        if not index_ready or not inventory_complete:
            plan["action"] = "blocked"
        plans[key] = plan
    return plans, list(dict.fromkeys(blockers))


def _alarm_notice_binding(alarm: dict[str, Any]) -> tuple[str, Any]:
    notice_ids = alarm.get("AlarmNoticeIds") if isinstance(alarm.get("AlarmNoticeIds"), list) else []
    if notice_ids:
        return "AlarmNoticeIds", list(notice_ids)
    monitor_notice = alarm.get("MonitorNotice") if isinstance(alarm.get("MonitorNotice"), dict) else {}
    if monitor_notice:
        return "MonitorNotice", dict(monitor_notice)
    return "", None


def _alarm_drift_fields(current: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    drift: list[str] = []
    scalar_fields = ("Name", "TriggerCount", "AlarmPeriod", "Condition", "AlarmLevel", "Status", "GroupTriggerStatus", "MonitorObjectType")
    for field in scalar_fields:
        if current.get(field) != desired.get(field):
            drift.append(field)
    current_monitor = current.get("MonitorTime") if isinstance(current.get("MonitorTime"), dict) else {}
    desired_monitor = desired["MonitorTime"]
    if current_monitor.get("Type") != desired_monitor.get("Type") or current_monitor.get("Time") != desired_monitor.get("Time"):
        drift.append("MonitorTime")
    current_targets = current.get("AlarmTargets") if isinstance(current.get("AlarmTargets"), list) else []
    desired_targets = desired["AlarmTargets"]
    if len(current_targets) != 1:
        drift.append("AlarmTargets")
    else:
        fields = ("LogsetId", "TopicId", "Query", "Number", "StartTimeOffset", "EndTimeOffset")
        if any(current_targets[0].get(field) != desired_targets[0].get(field) for field in fields):
            drift.append("AlarmTargets")
    return drift


def _safe_alarm_plan(key: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "action": str(plan.get("action") or "blocked"),
        "match_count": max(0, _safe_int_value(plan.get("match_count"))),
        "readback_ready": bool(plan.get("readback_ready")),
        "drift_field_count": len(plan.get("drift_fields") or []),
    }


def _plain_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    serializer = getattr(response, "to_json_string", None)
    if callable(serializer):
        parsed = json.loads(serializer())
        return parsed if isinstance(parsed, dict) else {}
    serializer = getattr(response, "ToJsonString", None)
    if callable(serializer):
        parsed = json.loads(serializer())
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _safe_int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _cls_request_factory(model_name: str, payload: dict[str, Any]) -> Any:
    from tencentcloud.cls.v20201016 import models

    request = getattr(models, model_name)()
    request.from_json_string(json.dumps(payload, ensure_ascii=False))
    return request


def _build_cls_control_client(values: dict[str, str]) -> Any:
    from tencentcloud.cls.v20201016 import cls_client
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile

    secret_id = values.get("JIEJING_TENCENT_SECRET_ID") or os.environ.get("TENCENTCLOUD_SECRET_ID") or ""
    secret_key = values.get("JIEJING_TENCENT_SECRET_KEY") or os.environ.get("TENCENTCLOUD_SECRET_KEY") or ""
    token = values.get("JIEJING_TENCENT_TOKEN") or os.environ.get("TENCENTCLOUD_TOKEN") or ""
    if not secret_id or not secret_key:
        raise RuntimeError("tencent credentials unavailable")
    cred = credential.Credential(secret_id, secret_key, token) if token else credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "cls.tencentcloudapi.com"
    http_profile.reqTimeout = 10
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    region = values.get("JIEJING_CLS_REGION") or values.get("JIEJING_TENCENT_REGION") or DEFAULT_REGION
    return cls_client.ClsClient(cred, region, client_profile)


def _run_provider_alarm_cli(
    *,
    args: argparse.Namespace,
    env_file: Path,
    existing: dict[str, str],
    lines: list[str],
) -> int:
    selected = [args.provider_alarm_status, args.dry_run_provider_alarms, args.apply_provider_alarms]
    if sum(bool(value) for value in selected) != 1:
        print(json.dumps({"status": "blocked", "blockers": ["select_one_provider_alarm_mode"], "secret_exposed": False}))
        return 2
    if args.apply_provider_alarms and not args.apply:
        print(json.dumps({"status": "blocked", "blockers": ["provider_alarm_apply_confirmation_missing"], "secret_exposed": False}))
        return 2
    mode = "apply" if args.apply_provider_alarms else ("dry_run" if args.dry_run_provider_alarms else "status")
    control = _provider_control_values(existing)
    notice_id = _read_named_env(args.provider_alarm_notice_id_env) or control.get("JIEJING_PROVIDER_ALARM_NOTICE_ID", "")
    logset_id = control.get("JIEJING_CLS_LOGSET_ID", "")
    topic_id = control.get("JIEJING_CLS_TOPIC_ID", "")
    missing = []
    if not logset_id:
        missing.append("JIEJING_CLS_LOGSET_ID")
    if not topic_id:
        missing.append("JIEJING_CLS_TOPIC_ID")
    if not control.get("JIEJING_TENCENT_SECRET_ID") or not control.get("JIEJING_TENCENT_SECRET_KEY"):
        missing.append("tencent_api_credentials_missing")
    if missing:
        print(json.dumps({"status": "blocked", "mode": mode, "blockers": missing, "secret_exposed": False}, ensure_ascii=False))
        return 2
    try:
        result = operate_provider_cls_alarms(
            client=_build_cls_control_client(control),
            request_factory=_cls_request_factory,
            logset_id=logset_id,
            topic_id=topic_id,
            notice_id=notice_id,
            mode=mode,
        )
    except Exception:
        print(json.dumps({"status": "blocked", "mode": mode, "blockers": ["provider_alarm_operator_failed"], "secret_exposed": False}))
        return 2
    updates = provider_alarm_verification_updates(result) if mode == "apply" else {}
    if updates:
        _write_env_file(env_file, lines, updates)
        result["verification_evidence_recorded"] = True
    else:
        result["verification_evidence_recorded"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "blocked" else 2


def _run_provider_index_cli(*, args: argparse.Namespace, existing: dict[str, str]) -> int:
    selected = [args.provider_index_status, args.dry_run_provider_index, args.apply_provider_index]
    if sum(bool(value) for value in selected) != 1:
        print(json.dumps({"status": "blocked", "blockers": ["select_one_provider_index_mode"], "secret_exposed": False}))
        return 2
    if args.apply_provider_index and not args.apply:
        print(json.dumps({"status": "blocked", "blockers": ["provider_index_apply_confirmation_missing"], "secret_exposed": False}))
        return 2
    mode = "apply" if args.apply_provider_index else ("dry_run" if args.dry_run_provider_index else "status")
    control = _provider_control_values(existing)
    topic_id = control.get("JIEJING_CLS_TOPIC_ID", "")
    missing = []
    if not topic_id:
        missing.append("JIEJING_CLS_TOPIC_ID")
    if not control.get("JIEJING_TENCENT_SECRET_ID") or not control.get("JIEJING_TENCENT_SECRET_KEY"):
        missing.append("tencent_api_credentials_missing")
    if missing:
        print(json.dumps({"status": "blocked", "mode": mode, "blockers": missing, "secret_exposed": False}, ensure_ascii=False))
        return 2
    try:
        result = operate_provider_cls_index(
            client=_build_cls_control_client(control),
            request_factory=_cls_request_factory,
            topic_id=topic_id,
            mode=mode,
        )
    except Exception:
        print(json.dumps({"status": "blocked", "mode": mode, "blockers": ["provider_index_operator_failed"], "secret_exposed": False}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") != "blocked" else 2


def provider_alarm_verification_updates(
    result: dict[str, Any],
    *,
    verified_at: str | None = None,
) -> dict[str, str]:
    if result.get("status") != "verified" or result.get("alarm_readback_verified") is not True:
        return {}
    timestamp = verified_at or _now_iso()
    return {
        "JIEJING_CLS_ALERT_POLICY_CONFIGURED": "true",
        "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT": timestamp,
        "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT": timestamp,
    }


def verify_provider_cls_probe(
    *,
    client: Any,
    request_factory: Any,
    uploader: Any,
    topic_id: str,
    environment: str,
    now_epoch_ms: int | None = None,
    search_attempts: int = 3,
    waiter: Any = time.sleep,
) -> dict[str, Any]:
    """Upload one safe probe and prove it is searchable without matching either alarm."""

    event = build_provider_monitoring_aggregate_event(
        reliability_summary={"status": "insufficient_data", "evaluated_count": 0},
        cost_summary={
            "status": "blocked",
            "cost_coverage_complete": False,
            "budget_configured": False,
            "cost_total_minor": 0,
        },
        environment=environment,
        probe=True,
    )
    alarm_queries_exclude_probe = all(
        'probe:"false"' in spec["AlarmTargets"][0]["Query"]
        for spec in provider_alarm_specs(logset_id="private", topic_id="private").values()
    )
    uploaded = bool(alarm_queries_exclude_probe and uploader(event))
    searchable = False
    if uploaded:
        current_ms = int(now_epoch_ms if now_epoch_ms is not None else time.time() * 1000)
        query = (
            f'event_type:"{PROVIDER_MONITOR_EVENT_TYPE}" AND '
            f'contract_version:"{PROVIDER_MONITOR_CONTRACT_VERSION}" AND probe:"true"'
        )
        for attempt in range(max(1, min(5, int(search_attempts)))):
            request = request_factory(
                "SearchLogRequest",
                {
                    "TopicId": topic_id,
                    "From": current_ms - 600_000,
                    "To": current_ms + 60_000,
                    "QueryString": query,
                    "QuerySyntax": 1,
                    "Limit": 1,
                    "Sort": "desc",
                    "HighLight": False,
                },
            )
            response = _plain_response(client.SearchLog(request))
            results = response.get("Results") if isinstance(response.get("Results"), list) else []
            if results:
                searchable = True
                break
            if attempt + 1 < max(1, min(5, int(search_attempts))):
                waiter(2)
    return {
        "status": "verified" if uploaded and searchable and alarm_queries_exclude_probe else "blocked",
        "probe_uploaded": uploaded,
        "probe_searchable": searchable,
        "alarm_queries_exclude_probe": alarm_queries_exclude_probe,
        "event_field_count": len(event),
        "event_allowlist_exact": set(event) == PROVIDER_MONITOR_AGGREGATE_KEYS,
        "notification_test_sent": False,
        "resource_ids_exposed": False,
        "secret_exposed": False,
    }


def _upload_provider_probe_to_cls(event: dict[str, Any], values: dict[str, str]) -> bool:
    try:
        from tencentcloud.log.cls_pb2 import LogGroupList
        from tencentcloud.log.logclient import LogClient

        if set(event) != PROVIDER_MONITOR_AGGREGATE_KEYS or event.get("probe") is not True:
            return False
        region = values.get("JIEJING_CLS_REGION") or values.get("JIEJING_TENCENT_REGION") or ""
        topic_id = values.get("JIEJING_CLS_TOPIC_ID") or ""
        secret_id = values.get("JIEJING_TENCENT_SECRET_ID") or ""
        secret_key = values.get("JIEJING_TENCENT_SECRET_KEY") or ""
        if not all((region, topic_id, secret_id, secret_key)):
            return False
        packet = LogGroupList()
        group = packet.logGroupList.add()
        log = group.logs.add()
        log.time = int(time.time() * 1_000_000)
        for key in sorted(PROVIDER_MONITOR_AGGREGATE_KEYS):
            content = log.contents.add()
            content.key = key
            value = event[key]
            content.value = str(value).lower() if isinstance(value, bool) else str(value)
        client = LogClient(f"https://{region}.cls.tencentcs.com", secret_id, secret_key)
        client.timeout = 5
        client.put_log_raw(topic_id, packet)
        return True
    except Exception:
        return False


def _run_provider_probe_cli(
    *,
    args: argparse.Namespace,
    env_file: Path,
    existing: dict[str, str],
    lines: list[str],
) -> int:
    if not args.apply:
        print(json.dumps({"status": "blocked", "blockers": ["provider_cls_probe_apply_confirmation_missing"], "secret_exposed": False}))
        return 2
    control = _provider_control_values(existing)
    missing = []
    for key in ("JIEJING_CLS_TOPIC_ID", "JIEJING_TENCENT_SECRET_ID", "JIEJING_TENCENT_SECRET_KEY"):
        if not control.get(key):
            missing.append(key)
    if missing:
        print(json.dumps({"status": "blocked", "blockers": missing, "secret_exposed": False}))
        return 2
    try:
        result = verify_provider_cls_probe(
            client=_build_cls_control_client(control),
            request_factory=_cls_request_factory,
            uploader=lambda event: _upload_provider_probe_to_cls(event, control),
            topic_id=control["JIEJING_CLS_TOPIC_ID"],
            environment=control.get("JIEJING_SAAS_ENV") or "staging",
        )
    except Exception:
        print(json.dumps({"status": "blocked", "blockers": ["provider_cls_probe_failed"], "secret_exposed": False}))
        return 2
    if result.get("status") == "verified":
        verified_at = _now_iso()
        updates = {
            "JIEJING_CLS_LIVE_PROBE_LAST_AT": verified_at,
            "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED": "true",
            "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT": verified_at,
        }
        _write_env_file(env_file, lines, updates)
        result["verification_evidence_recorded"] = True
    else:
        result["verification_evidence_recorded"] = False
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "verified" else 2


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


if __name__ == "__main__":
    raise SystemExit(main())
