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
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_ENV_FILE = Path("/opt/jiejing-staging/private/tencent-managed.env")
DEFAULT_REGION = "ap-guangzhou"
DEFAULT_SSM_KEYSPACE = "jiejing-staging"
DEFAULT_COS_PREFIX = "jiejing/staging/backups"
DEFAULT_SECRET_TEMPLATE = "{keyspace}-{company_id}-{store_id}-{purpose}-{secret_ref}"

SENSITIVE_FRAGMENTS = ("SECRET", "TOKEN", "PASSWORD", "DATABASE_URL", "QUEUE_URL", "KEY")
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
    "JIEJING_BACKUP_POLICY_CONFIGURED",
    "JIEJING_BACKUP_ALERTS_CONFIGURED",
    "JIEJING_VAULT_BACKUP_POLICY_CONFIGURED",
    "JIEJING_RESTORE_DRILL_LAST_AT",
    "JIEJING_CLS_ENABLED",
    "JIEJING_CLS_REGION",
    "JIEJING_CLS_LOGSET_ID",
    "JIEJING_CLS_TOPIC_ID",
    "JIEJING_CLS_ALERT_POLICY_CONFIGURED",
    "JIEJING_CLS_LIVE_PROBE_REQUIRED",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env_file = Path(args.env_file)
    existing, lines = _read_env_file(env_file)

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

    parser.add_argument("--backup-policy-configured", action="store_true")
    parser.add_argument("--backup-alerts-configured", action="store_true")
    parser.add_argument("--vault-backup-policy-configured", action="store_true")
    parser.add_argument("--record-restore-drill-now", action="store_true")
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

    if args.backup_policy_configured:
        updates["JIEJING_BACKUP_POLICY_CONFIGURED"] = "true"
    if args.backup_alerts_configured:
        updates["JIEJING_BACKUP_ALERTS_CONFIGURED"] = "true"
    if args.vault_backup_policy_configured:
        updates["JIEJING_VAULT_BACKUP_POLICY_CONFIGURED"] = "true"
    if args.record_restore_drill_now:
        updates["JIEJING_RESTORE_DRILL_LAST_AT"] = now

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


def _write_env_file(path: Path, original_lines: list[str], updates: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        backup = path.with_name(f"{path.name}.bak.created")
        backup.write_text("", encoding="utf-8")

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

    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return backup


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
        ],
    }
    status = {
        "env_file": str(env_file),
        "exists": env_file.exists(),
        "groups": {name: _group_status(values, keys) for name, keys in groups.items()},
        "blockers": _blockers(values),
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


def _blockers(values: dict[str, str]) -> list[str]:
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
        if values.get("JIEJING_CLS_LIVE_PROBE_REQUIRED", "").lower() == "true" and not values.get(
            "JIEJING_CLS_LIVE_PROBE_LAST_AT"
        ):
            blockers.append("cls_probe_not_recorded")
    else:
        blockers.append("cls_not_enabled")
    if values.get("JIEJING_VAULT_PROVIDER") != "tencent_ssm":
        blockers.append("vault_provider_not_switched_to_tencent_ssm")
    return blockers


def _redact_value(key: str, value: str) -> str:
    if not value:
        return ""
    if any(fragment in key.upper() for fragment in SENSITIVE_FRAGMENTS):
        return "[set]"
    return value


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


if __name__ == "__main__":
    raise SystemExit(main())
