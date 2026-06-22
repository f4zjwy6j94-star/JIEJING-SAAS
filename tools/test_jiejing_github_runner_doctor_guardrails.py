#!/usr/bin/env python3
"""Validate the GitHub self-hosted runner doctor remains read-only and scoped."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-runner-doctor.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-staging-runner-doctor.yml"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if not SCRIPT.exists() or not WORKFLOW.exists() or not RUNBOOK.exists():
        return fail("runner doctor file missing")
    script = SCRIPT.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    required_script = [
        "/opt/jiejing-staging/app",
        "github-action-backups",
        "github-action-releases",
        "readlink -f --",
        "deploy_root_outside_staging",
        "app_dir_outside_staging",
        "docker compose version",
        "sudo -n true",
        "rsync_missing",
        "DISK_USED_PERCENT=",
        "JIEJING_RUNNER_DOCTOR_STATUS=",
        "JIEJING_RUNNER_DOCTOR_BLOCKERS",
        "SECRET_EXPOSED=false",
    ]
    required_workflow = [
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "runs-on: [self-hosted, jiejing-staging]",
        "bash deploy/github-actions/jiejing-runner-doctor.sh",
    ]
    required_runbook = [
        "Jiejing Staging Runner Doctor",
        "JIEJING_RUNNER_DOCTOR_STATUS=ready",
        "docker_cli_missing",
        "sudo_noninteractive_unavailable",
        "disk_usage_at_or_above_90_percent",
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
        return fail("runner doctor guardrail missing markers: " + ",".join(missing))

    forbidden = [
        "docker compose down",
        "docker volume rm",
        "rm -rf",
        "DROP DATABASE",
        "printenv",
        "env |",
        "set -x",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    present = [marker for marker in forbidden if marker in script or marker in workflow]
    if present:
        return fail("runner doctor contains forbidden marker: " + ",".join(present))

    print("PASS jiejing_github_runner_doctor_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
