#!/usr/bin/env python3
"""Validate GitHub self-hosted staging deploy stays manual and data-safe."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-deploy.yml"
ROLLBACK_WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-manual-rollback.yml"
DEPLOY_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-deploy.sh"
ROLLBACK_SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-staging-rollback.sh"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


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
        "JIEJING_DEPLOY_DRY_RUN",
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
        "--exclude '.git/'",
        "--exclude '.env'",
        "--exclude '*.env'",
        "--exclude '*.pem'",
        "--exclude '*.key'",
        "python3 tools/jiejing_secret_scan.py",
        "node --check app.js",
        "JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt",
        "PATCH_APPLIED=0",
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

    print("PASS jiejing_github_actions_deploy_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
