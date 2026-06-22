#!/usr/bin/env python3
"""Regression checks for the private Tencent runtime env configurator."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-configure-tencent-runtime-env-test"
TOOL = ROOT / "tools" / "jiejing_configure_tencent_runtime_env.py"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    env_path = OUT / "tencent-managed.env"
    env_path.write_text(
        "\n".join(
            [
                "JIEJING_DATABASE_ENGINE=postgres",
                "JIEJING_DATABASE_URL=postgresql://jiejing:DB_SECRET_SHOULD_NOT_LEAK@172.16.0.12:5432/jiejing",
                "JIEJING_QUEUE_URL=redis://:REDIS_SECRET_SHOULD_NOT_LEAK@172.16.0.15:6379/0",
                "JIEJING_VAULT_PROVIDER=vault",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["JIEJING_TEST_TENCENT_ID"] = "TENCENT_ID_SHOULD_NOT_LEAK"
    env["JIEJING_TEST_TENCENT_KEY"] = "TENCENT_KEY_SHOULD_NOT_LEAK"

    apply_cmd = [
        sys.executable,
        str(TOOL),
        "--env-file",
        str(env_path),
        "--apply",
        "--enable-ssm",
        "--tencent-secret-id-env",
        "JIEJING_TEST_TENCENT_ID",
        "--tencent-secret-key-env",
        "JIEJING_TEST_TENCENT_KEY",
        "--enable-cos",
        "--cos-bucket",
        "jiejing-staging-backup-1423900563",
        "--record-cos-probe-now",
        "--enable-cls",
        "--cls-logset-id",
        "logset-jiejing-staging",
        "--cls-topic-id",
        "topic-saas-backend",
        "--cls-alert-policy-configured",
        "--record-cls-probe-now",
        "--backup-policy-configured",
        "--backup-alerts-configured",
        "--vault-backup-policy-configured",
        "--record-restore-drill-now",
        "--enable-managed-db-queue-live-checks",
    ]
    applied = subprocess.run(apply_cmd, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if applied.returncode != 0:
        return fail(applied.stderr or applied.stdout)
    combined = applied.stdout + applied.stderr
    for forbidden in (
        "TENCENT_ID_SHOULD_NOT_LEAK",
        "TENCENT_KEY_SHOULD_NOT_LEAK",
        "DB_SECRET_SHOULD_NOT_LEAK",
        "REDIS_SECRET_SHOULD_NOT_LEAK",
    ):
        if forbidden in combined:
            return fail(f"configurator leaked secret marker {forbidden}")

    text = env_path.read_text(encoding="utf-8")
    if "JIEJING_VAULT_PROVIDER=vault" not in text:
        return fail("configurator must not switch Vault provider unless explicitly requested")
    if "JIEJING_TENCENT_SECRET_ID=TENCENT_ID_SHOULD_NOT_LEAK" not in text:
        return fail("configurator did not write Tencent SecretId to private env")
    if "JIEJING_COS_BUCKET=jiejing-staging-backup-1423900563" not in text:
        return fail("configurator did not write COS bucket")
    if "JIEJING_CLS_LOGSET_ID=logset-jiejing-staging" not in text:
        return fail("configurator did not write CLS logset")
    if "JIEJING_POSTGRES_DRIVER_CHECK_LIVE=true" not in text or "JIEJING_REDIS_DRIVER_CHECK_LIVE=true" not in text:
        return fail("configurator did not write managed database/queue live-check flags")

    status = subprocess.run(
        [sys.executable, str(TOOL), "--env-file", str(env_path), "--status"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0:
        return fail(status.stderr or status.stdout)
    for forbidden in (
        "TENCENT_ID_SHOULD_NOT_LEAK",
        "TENCENT_KEY_SHOULD_NOT_LEAK",
        "DB_SECRET_SHOULD_NOT_LEAK",
        "REDIS_SECRET_SHOULD_NOT_LEAK",
    ):
        if forbidden in status.stdout + status.stderr:
            return fail(f"status leaked secret marker {forbidden}")
    payload = json.loads(status.stdout)
    if "vault_provider_not_switched_to_tencent_ssm" not in payload.get("blockers", []):
        return fail("status should keep Tencent SSM switch blocked until explicit migration")

    switch = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--env-file",
            str(env_path),
            "--apply",
            "--switch-vault-provider",
            "--tencent-secret-id-env",
            "JIEJING_TEST_TENCENT_ID",
            "--tencent-secret-key-env",
            "JIEJING_TEST_TENCENT_KEY",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if switch.returncode != 0:
        return fail(switch.stderr or switch.stdout)
    if "JIEJING_VAULT_PROVIDER=tencent_ssm" not in env_path.read_text(encoding="utf-8"):
        return fail("explicit switch should set Tencent SSM provider")

    print("PASS jiejing_configure_tencent_runtime_env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
