#!/usr/bin/env python3
"""Static deployment contract checks for first real eBay OAuth staging."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    compose = (ROOT / "deploy" / "docker-compose.oauth-staging.yml").read_text(encoding="utf-8")
    managed_example = (ROOT / "deploy" / "jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8")
    secret_example = (ROOT / "deploy" / "jiejing-saas.staging-oauth.env.example").read_text(encoding="utf-8")
    postgres_example = (ROOT / "deploy" / "jiejing-saas.postgres-localqueue.env.example").read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "deploy" / "bootstrap.public-staging.ubuntu.sh").read_text(encoding="utf-8")
    checklist = (ROOT / "deploy" / "tencentcloud-public-staging-checklist.md").read_text(encoding="utf-8")

    env_file_contract = """    env_file:
      - ../../private/tencent-managed.env
      - ../../private/jiejing-saas.staging-oauth.env
      - ../../private/postgres-localqueue.env
"""
    if env_file_contract not in compose:
        return fail("oauth staging compose should load managed, secret and postgres env files in the canonical order")
    for marker in (
        'JIEJING_SAAS_ENV: "staging"',
        'JIEJING_CORS_ORIGIN: "https://app.jiejing.shop"',
        'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "false"',
        'JIEJING_EBAY_WRITE_LIVE: "false"',
        'JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "disabled_public_staging"',
        'JIEJING_BILLING_PROVIDER: "stripe_test_mock"',
    ):
        if marker not in compose:
            return fail(f"oauth staging compose missing static/safety contract: {marker}")
    if "postgres:" in compose or "redis:" in compose:
        return fail("oauth staging compose should consume managed database/queue connections, not start local database services")
    with TemporaryDirectory() as temp_dir:
        candidate_deploy = Path(temp_dir) / "workspace" / "deploy"
        private_root = Path(temp_dir) / "private"
        candidate_deploy.mkdir(parents=True)
        private_root.mkdir()
        compose_path = candidate_deploy / "docker-compose.oauth-staging.yml"
        managed_path = private_root / "tencent-managed.env"
        secret_path = private_root / "jiejing-saas.staging-oauth.env"
        postgres_path = private_root / "postgres-localqueue.env"
        compose_path.write_text(compose, encoding="utf-8")
        managed_path.write_text(managed_example, encoding="utf-8")
        secret_path.write_text(secret_example, encoding="utf-8")
        postgres_path.write_text(postgres_example, encoding="utf-8")
        for operation in ("check", "migrate"):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "jiejing_runtime_env_overlap_guard.py"),
                    operation,
                    "--compose",
                    str(compose_path),
                    "--managed-env",
                    str(managed_path),
                    "--secret-env",
                    str(secret_path),
                    "--postgres-env",
                    str(postgres_path),
                    "--required-runtime-service",
                    "jiejing-saas",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                return fail(f"OAuth SaaS-only ownership {operation} command failed: {completed.stderr}")
            guard_report = json.loads(completed.stdout)
            if not guard_report["ok"] or guard_report["blockers"]:
                return fail(
                    f"OAuth staging should pass the SaaS-only ownership {operation}: "
                    f"{guard_report['blockers']}"
                )
            if operation == "migrate" and guard_report.get("mode") != "dry_run":
                return fail("OAuth ownership migration rehearsal must remain a dry-run")
    if "JIEJING_VAULT_ENABLED=true" not in managed_example or "JIEJING_VAULT_PROVIDER=tencent_ssm" not in managed_example:
        return fail("managed env example should own the active Vault enable/provider selection")
    for forbidden in ("JIEJING_VAULT_ENABLED=", "JIEJING_VAULT_PROVIDER=", "JIEJING_SAAS_ENV=", "JIEJING_CORS_ORIGIN="):
        if forbidden in secret_example:
            return fail(f"secret env example must not own managed/static setting: {forbidden}")
    if "JIEJING_DATABASE_URL=<inject-private-postgres-url>" not in postgres_example:
        return fail("postgres env example should own the private database connection placeholder")
    if "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE=true" not in secret_example:
        return fail("staging OAuth env example should enable live OAuth exchange")
    if "JIEJING_EBAY_REFRESH_TOKEN=" not in secret_example:
        return fail("staging OAuth env example should explicitly keep env refresh token empty")
    if "JIEJING_ENABLE_HERMES_EBAY_BRIDGE=false" not in secret_example:
        return fail("staging OAuth env example should keep Hermes bridge disabled")
    if "docker-compose.oauth-staging.yml" not in runbook:
        return fail("runbook should mention the OAuth staging compose profile")
    if "jiejing_staging_ebay_oauth_readonly_flow.py doctor" not in runbook:
        return fail("runbook should include the staging backend doctor before seller OAuth")
    if "not the final paid SaaS deployment" not in runbook:
        return fail("runbook should state that OAuth staging is not final paid SaaS deployment")
    oauth_start = runbook.index("Start this backend-only validation profile")
    oauth_end = runbook.index("That backend-only compose file", oauth_start)
    oauth_startup = runbook[oauth_start:oauth_end]
    check_command = "python tools\\jiejing_runtime_env_overlap_guard.py check"
    migrate_command = "python tools\\jiejing_runtime_env_overlap_guard.py migrate"
    build_command = "docker compose -f deploy/docker-compose.oauth-staging.yml build"
    up_command = "docker compose -f deploy/docker-compose.oauth-staging.yml up"
    for marker in (
        check_command,
        migrate_command,
        "--compose deploy\\docker-compose.oauth-staging.yml",
        "--managed-env ..\\private\\tencent-managed.env",
        "--secret-env ..\\private\\jiejing-saas.staging-oauth.env",
        "--postgres-env ..\\private\\postgres-localqueue.env",
        "--required-runtime-service jiejing-saas",
        "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
        build_command,
        up_command,
    ):
        if marker not in oauth_startup:
            return fail(f"OAuth PowerShell startup path missing fail-closed guard marker: {marker}")
    if not (
        oauth_startup.index(check_command)
        < oauth_startup.index(migrate_command)
        < oauth_startup.index(build_command)
        < oauth_startup.index(up_command)
    ):
        return fail("OAuth guard check and migration dry-run must run before every compose operation")
    if oauth_startup.count("--required-runtime-service jiejing-saas") != 2:
        return fail("both OAuth guard commands must select the SaaS-only runtime profile")
    if oauth_startup.count("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }") < 2:
        return fail("OAuth startup must stop after either guard command fails")
    for private_name in (
        "tencent-managed.env",
        "jiejing-saas.staging-oauth.env",
        "postgres-localqueue.env",
    ):
        if private_name not in bootstrap or private_name not in checklist:
            return fail(f"bootstrap and checklist must cover all three private env files: {private_name}")
    for marker in (
        "install -d -m 0700",
        "install -m 0600",
        "stat -c '%a'",
        "Refusing symlink private env directory",
        "Refusing symlink private env target",
        'TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"',
        'python3 "$TRUSTED_RUNTIME_ENV_GUARD" check',
        'python3 "$TRUSTED_RUNTIME_ENV_GUARD" migrate',
        "trusted_root_owned_path_chain_is_safe",
        'current="$(dirname -- "$path")"',
        '[[ -d "$current" && ! -L "$current" ]]',
        "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1",
        "--managed-env",
        "--secret-env",
        "--postgres-env",
    ):
        if marker not in bootstrap:
            return fail(f"bootstrap missing safe three-source validation marker: {marker}")
    if 'source "$PRIVATE_DIR' in bootstrap or 'cat "$PRIVATE_DIR' in bootstrap:
        return fail("bootstrap must never source or print private env files")
    if '$APP_DIR/tools/jiejing_runtime_env_overlap_guard.py' in bootstrap:
        return fail("bootstrap must never execute the candidate app guard")
    trust_gate = bootstrap.index('if ! trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD"')
    first_bootstrap_side_effect = bootstrap.index("sudo apt-get update")
    if not trust_gate < first_bootstrap_side_effect:
        return fail("bootstrap must validate the preinstalled trusted guard before side effects")
    for marker in (
        "jiejing_runtime_env_overlap_guard.py check",
        "jiejing_runtime_env_overlap_guard.py migrate",
        "chmod 600",
        "managed -> secret -> postgres",
        "supersedes the older single-file OAuth staging instruction",
    ):
        if marker not in checklist:
            return fail(f"Tencent staging checklist missing current ownership flow marker: {marker}")
    print("PASS jiejing_oauth_staging_deploy_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
