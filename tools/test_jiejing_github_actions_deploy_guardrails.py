#!/usr/bin/env python3
"""Validate GitHub self-hosted staging deploy stays manual and data-safe."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-deploy.yml"
ROLLBACK_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-rollback.yml"
DEPLOY_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-deploy.sh"
ROLLBACK_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-rollback.sh"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"
PATCH_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
DOCTOR_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-runner-doctor.sh"
BOOTSTRAP_SCRIPT = ROOT / "deploy" / "bootstrap.public-staging.ubuntu.sh"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def extract_shell_function(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


def main() -> int:
    try:
        deploy_workflow = read(DEPLOY_WORKFLOW)
        rollback_workflow = read(ROLLBACK_WORKFLOW)
        deploy_script = read(DEPLOY_SCRIPT)
        rollback_script = read(ROLLBACK_SCRIPT)
        runbook = read(RUNBOOK)
    except FileNotFoundError as exc:
        return fail(f"missing deploy guardrail file: {exc}")

    required_deploy_workflow = [
        "workflow_dispatch:",
        "deploy_mode:",
        "preflight_only",
        "dry_run",
        "apply",
        "confirm_staging_deploy",
        "deploy app.jiejing.shop staging",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: false",
        "github.ref == 'refs/heads/main'",
        "python tools/jiejing_secret_scan.py",
        "node --check app.js",
        "python tools/test_jiejing_github_actions_deploy_guardrails.py",
        "python tools/jiejing_precloud_deployment_gate.py",
        "runs-on: [self-hosted, jiejing-staging]",
        "Set up Node for frontend syntax check",
        "node-version: \"20\"",
        "npm install --prefix output/codex-playwright-deps --no-save --no-package-lock --ignore-scripts playwright-core@1.59.1",
        "JIEJING_DEPLOY_DRY_RUN",
        "JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN: ${{ secrets.JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN }}",
        "JIEJING_EBAY_CLIENT_SECRET: ${{ secrets.JIEJING_EBAY_CLIENT_SECRET }}",
        "bash deploy/github-actions/jiejing-staging-deploy.sh",
    ]
    required_rollback_workflow = [
        "workflow_dispatch:",
        "backup_name:",
        "dry_run:",
        "confirm_staging_rollback",
        "rollback app.jiejing.shop staging",
        "permissions:",
        "contents: read",
        "concurrency:",
        "github.ref == 'refs/heads/main'",
        "runs-on: [self-hosted, jiejing-staging]",
        "JIEJING_ROLLBACK_DRY_RUN",
        "bash deploy/github-actions/jiejing-staging-rollback.sh",
    ]
    required_deploy_script = [
        "EXPECTED_CONFIRM=\"deploy app.jiejing.shop staging\"",
        "JIEJING_DEPLOY_DRY_RUN",
        "JIEJING_STAGING_DEPLOY_CONFIRM",
        "/opt/jiejing-staging/app",
        "github-action-backups",
        "github-action-releases",
        "readlink -f --",
        "REFUSE_APP_DIR_OUTSIDE_STAGING",
        "REFUSE_DEPLOY_ROOT_OUTSIDE_STAGING",
        "rsync -a --delete",
        "--exclude '/output/private-backups/'",
        "--exclude '/output/deploy-backups/'",
        "--exclude '/output/staging-patch-backups/'",
        "--exclude '.git/'",
        "--exclude '.env'",
        "--exclude '*.env'",
        "--exclude '*.pem'",
        "--exclude '*.key'",
        "python3 tools/jiejing_secret_scan.py",
        "node --check app.js",
        "JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt",
        "PATCH_APPLIED=0",
        'TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"',
        "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1",
        'trusted_guard_resolved="$(readlink -f -- "$TRUSTED_RUNTIME_ENV_GUARD"',
        "stat -c '%u %a'",
        '[[ -f "$path" && ! -L "$path" ]]',
        '(( (8#$mode & 0022) == 0 ))',
        'current="$(dirname -- "$path")"',
        '[[ -d "$current" && ! -L "$current" ]]',
        'candidate_compose="$WORKSPACE/deploy/docker-compose.public-https-staging.yml"',
        'runtime_compose="$resolved_app_dir/deploy/$(basename -- "$candidate_compose")"',
        'private_dir="$resolved_deploy_root/private"',
        'candidate_managed="$WORKSPACE/deploy/jiejing-saas.tencent-managed.env.example"',
        'candidate_secret="$WORKSPACE/deploy/jiejing-saas.staging-oauth.env.example"',
        'candidate_postgres="$WORKSPACE/deploy/jiejing-saas.postgres-localqueue.env.example"',
        '--managed-runtime-path "$private_dir/tencent-managed.env"',
        '--secret-runtime-path "$private_dir/jiejing-saas.staging-oauth.env"',
        '--postgres-runtime-path "$private_dir/postgres-localqueue.env"',
        '--compose-runtime-path "$runtime_compose_path"',
        'run_dry_run_runtime_env_guard',
        'run_apply_runtime_env_guard',
        'python3 "$TRUSTED_RUNTIME_ENV_GUARD" check',
        'sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check',
        'JIEJING_USE_COST_SAVER_OVERRIDE',
        '--compose-override "$cost_saver_override"',
        '--required-runtime-service jiejing-saas',
        '--required-runtime-service jiejing-worker',
        "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1",
        "RUNTIME_ENV_GUARD_STATUS=passed",
        "REFUSE_MISSING_EBAY_CLIENT_SECRET=1",
        "JIEJING_EBAY_CLIENT_SECRET",
        "unset JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN JIEJING_EBAY_CLIENT_SECRET",
        'NODE_BIN="$(command -v node)"',
        'JIEJING_NODE_BIN="$NODE_BIN"',
        "sudo -n JIEJING_APP_DIR=",
        "deploy/apply-staging-patch.sh",
    ]
    required_rollback_script = [
        "EXPECTED_CONFIRM=\"rollback app.jiejing.shop staging\"",
        "JIEJING_ROLLBACK_DRY_RUN",
        "JIEJING_STAGING_ROLLBACK_CONFIRM",
        "JIEJING_STAGING_ROLLBACK_BACKUP",
        "github-action-backups",
        "REFUSE_SELECTED_BACKUP_OUTSIDE_ROOT",
        "ROLLBACK_APPLIED=0",
        "rsync -a --delete",
        "--exclude '/output/private-backups/'",
        "--exclude '/output/deploy-backups/'",
        "--exclude '/output/staging-patch-backups/'",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps jiejing-saas",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps jiejing-worker",
    ]
    required_runbook = [
        "GitHub private repo is the source of truth",
        "The runner must only deploy after a manual workflow dispatch",
        "It does not run eBay OAuth.",
        "It does not write Stripe live keys, eBay refresh tokens, model keys, or SSH private keys into GitHub.",
        "deploy_mode: dry_run",
        "deploy_mode: apply",
        "dry_run: true",
        "dry_run: false",
        "Current state remains beta/public-staging oriented, not paid commercial launch.",
        "/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py",
        "Bootstrap, deploy, patch and",
        "every parent directory through `/` must be owned by uid 0",
        "candidate bundle may",
        "separately approved trusted-guard",
        "without sudo",
        "without reading the server-private env files",
        "/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml",
    ]

    missing: list[str] = []
    for marker in required_deploy_workflow:
        if marker not in deploy_workflow:
            missing.append(f"deploy_workflow:{marker}")
    for marker in required_rollback_workflow:
        if marker not in rollback_workflow:
            missing.append(f"rollback_workflow:{marker}")
    for marker in required_deploy_script:
        if marker not in deploy_script:
            missing.append(f"deploy_script:{marker}")
    for marker in required_rollback_script:
        if marker not in rollback_script:
            missing.append(f"rollback_script:{marker}")
    for marker in required_runbook:
        if marker not in runbook:
            missing.append(f"runbook:{marker}")
    if missing:
        return fail("github actions deploy guardrail missing markers: " + ",".join(missing))

    forbidden_workflow = [
        "pull_request_target",
        "schedule:",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    forbidden_scripts = [
        "rm -rf /",
        "docker compose down -v",
        "docker volume rm",
        "DROP DATABASE",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    present: list[str] = []
    workflows = deploy_workflow + "\n" + rollback_workflow
    scripts = deploy_script + "\n" + rollback_script
    for marker in forbidden_workflow:
        if marker in workflows:
            present.append(f"workflow:{marker}")
    for marker in forbidden_scripts:
        if marker in scripts:
            present.append(f"script:{marker}")
    if present:
        return fail("github actions deploy guardrail contains forbidden marker: " + ",".join(present))

    verifier_name = "trusted_root_owned_path_chain_is_safe"
    verifier = extract_shell_function(deploy_script, verifier_name)
    for verifier_script in (PATCH_SCRIPT, DOCTOR_SCRIPT, BOOTSTRAP_SCRIPT):
        if verifier not in read(verifier_script):
            return fail(f"trusted path-chain verifier drifted in {verifier_script.name}")
    verifier_contract = verifier + r'''
root="$(pwd -P)/output/jiejing-trusted-path-test-$$"
trap 'rm -rf -- "$root"' EXIT
mkdir -p "$root/one/two"
touch "$root/one/two/guard.py"
stat() {
  local target="${@: -1}"
  if [[ -n "${FAKE_UNSAFE_PARENT:-}" && "$target" == "$FAKE_UNSAFE_PARENT" ]]; then
    printf '%s\n' '0 0777'
  else
    printf '%s\n' '0 0755'
  fi
}
trusted_root_owned_path_chain_is_safe "$root/one/two/guard.py" || exit 81
if FAKE_UNSAFE_PARENT="$root/one" trusted_root_owned_path_chain_is_safe "$root/one/two/guard.py"; then
  exit 82
fi
'''
    verifier_contract_path = ROOT / "output" / f"jiejing-trusted-path-verifier-{os.getpid()}.sh"
    verifier_contract_path.parent.mkdir(parents=True, exist_ok=True)
    verifier_contract_path.write_bytes(verifier_contract.encode("utf-8"))
    try:
        verifier_result = subprocess.run(
            ["bash", verifier_contract_path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        verifier_contract_path.unlink(missing_ok=True)
    if verifier_result.returncode != 0:
        return fail(
            "trusted path-chain verifier safe/unsafe-parent contract failed "
            f"(returncode={verifier_result.returncode}, stderr={verifier_result.stderr[-800:]!r})"
        )

    guard_call = deploy_script.index("\nrun_runtime_env_guard\n")
    first_release_mutation = deploy_script.index('mkdir -p "$RELEASE_ROOT" "$BACKUP_ROOT"')
    first_copy = deploy_script.index("rsync -a --delete")
    first_secret_upsert = deploy_script.index("jiejing_upsert_private_env_secret.py")
    first_patch_mutation = deploy_script.index("deploy/apply-staging-patch.sh", first_secret_upsert)
    if not guard_call < min(first_release_mutation, first_copy, first_secret_upsert, first_patch_mutation):
        return fail("runtime env guard must run before every staging deploy side effect")
    if "jiejing_runtime_env_overlap_guard.py\" migrate" in deploy_script:
        return fail("staging deploy must not auto-apply or auto-plan a private env migration")
    for forbidden_guard in (
        '$WORKSPACE/tools/jiejing_runtime_env_overlap_guard.py',
        '$release_dir/tools/jiejing_runtime_env_overlap_guard.py',
        "/opt/jiejing-staging/bin/jiejing_runtime_env_overlap_guard.py",
    ):
        if forbidden_guard in deploy_script:
            return fail("deploy must never execute a candidate runtime env guard")
    dry_guard_start = deploy_script.index("run_dry_run_runtime_env_guard()")
    dry_guard_end = deploy_script.index("run_apply_runtime_env_guard()", dry_guard_start)
    dry_guard = deploy_script[dry_guard_start:dry_guard_end]
    if "sudo" in dry_guard or '--managed-env "$private_dir/' in dry_guard:
        return fail("dry-run runtime guard must not sudo or read private env files")
    if 'if [[ "$DRY_RUN" == "0" ]]; then\n    python3 tools/jiejing_secret_scan.py' not in deploy_script:
        return fail("self-hosted dry-run must not execute the candidate secret scanner")

    workflow_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(WORKFLOW_DIR.glob("jiejing-*.yml"))
    )
    required_supported_actions = [
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/setup-node@v6",
    ]
    missing_supported_actions = [marker for marker in required_supported_actions if marker not in workflow_sources]
    if missing_supported_actions:
        return fail("github actions Node 24 runtime upgrades are missing: " + ",".join(missing_supported_actions))
    deprecated_actions = [
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/setup-node@v4",
    ]
    present_deprecated_actions = [marker for marker in deprecated_actions if marker in workflow_sources]
    if present_deprecated_actions:
        return fail("github actions still use deprecated Node 20 runtimes: " + ",".join(present_deprecated_actions))

    print("PASS jiejing_github_actions_deploy_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
