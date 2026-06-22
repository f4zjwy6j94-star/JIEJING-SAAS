#!/usr/bin/env python3
"""Validate GitHub runner maintenance stays manual, scoped, and recoverable."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-runner-maintenance.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-runner-maintenance.yml"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if not SCRIPT.exists() or not WORKFLOW.exists() or not RUNBOOK.exists():
        return fail("runner maintenance file missing")
    script = SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    required_script = [
        "EXPECTED_CONFIRM=\"cleanup app.jiejing.shop runner\"",
        "JIEJING_RUNNER_MAINTENANCE_DRY_RUN",
        "JIEJING_RUNNER_MAINTENANCE_CONFIRM",
        "JIEJING_RUNNER_MAINTENANCE_KEEP_LATEST",
        "JIEJING_RUNNER_MAINTENANCE_ARCHIVE_AFTER_DAYS",
        "/opt/jiejing-staging/github-action-releases",
        "/opt/jiejing-staging/github-action-release-archives",
        "REFUSE_RELEASE_ROOT_OUTSIDE_STAGING",
        "REFUSE_ARCHIVE_ROOT_OUTSIDE_STAGING",
        "find \"$resolved_release_root\" -mindepth 1 -maxdepth 1 -type d -name 'github-*'",
        "tar -C \"$resolved_release_root\" -czf",
        "tar -tzf",
        "ARCHIVE_APPLIED=0",
        "ARCHIVE_APPLIED=1",
        "SECRET_EXPOSED=false",
    ]
    required_workflow = [
        "workflow_dispatch:",
        "dry_run:",
        "keep_latest:",
        "archive_after_days:",
        "confirm_runner_maintenance",
        "cleanup app.jiejing.shop runner",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: false",
        "github.ref == 'refs/heads/main'",
        "runs-on: [self-hosted, jiejing-staging]",
        "JIEJING_RUNNER_MAINTENANCE_DRY_RUN",
        "bash deploy/github-actions/jiejing-runner-maintenance.sh",
    ]
    required_runbook = [
        "Jiejing Staging Runner Maintenance",
        "cleanup app.jiejing.shop runner",
        "ARCHIVE_APPLIED=0",
        "ARCHIVE_APPLIED=1",
        "github-action-release-archives",
        "It does not touch the running app, backups, private env files, databases, Docker volumes, Vault material, eBay OAuth state, or billing/provider secrets.",
    ]

    missing: list[str] = []
    for marker in required_script:
        if marker not in script:
            missing.append(f"script:{marker}")
    for marker in required_workflow:
        if marker not in workflow:
            missing.append(f"workflow:{marker}")
    for marker in required_runbook:
        if marker not in runbook:
            missing.append(f"runbook:{marker}")
    if missing:
        return fail("runner maintenance guardrail missing markers: " + ",".join(missing))

    forbidden_workflow = [
        "schedule:",
        "pull_request_target",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    forbidden_script = [
        "docker compose down",
        "docker volume rm",
        "DROP DATABASE",
        "/opt/jiejing-staging/app/",
        "/opt/jiejing-staging/private",
        "github-action-backups",
        ".env",
        "*.env",
        "printenv",
        "env |",
        "set -x",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    present: list[str] = []
    for marker in forbidden_workflow:
        if marker in workflow:
            present.append(f"workflow:{marker}")
    for marker in forbidden_script:
        if marker in script:
            present.append(f"script:{marker}")
    if present:
        return fail("runner maintenance contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_github_runner_maintenance_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
