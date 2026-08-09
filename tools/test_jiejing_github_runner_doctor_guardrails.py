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
        "JIEJING_RUNNER_DOCTOR_PUBLIC_HEALTH_URL",
        "PUBLIC_HEALTH=",
        "JIEJING_RUNNER_DOCTOR_STATUS=",
        "JIEJING_RUNNER_DOCTOR_BLOCKERS",
        "RUNTIME_ENV_GUARD_STATUS=",
        "runtime_env_guard_missing",
        "runtime_env_guard_untrusted",
        "runtime_env_compose_missing",
        'TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"',
        'app_dir_safe="false"',
        'app_dir_safe="true"',
        'if [[ "$app_dir_safe" != "true" ||',
        "stat -c '%u %a'",
        '[[ -f "$path" && ! -L "$path" ]]',
        '(( (8#$mode & 0022) == 0 ))',
        'current="$(dirname -- "$path")"',
        '[[ -d "$current" && ! -L "$current" ]]',
        'sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check',
        'candidate_workspace="${GITHUB_WORKSPACE:-}"',
        'candidate_compose="$resolved_candidate_workspace/deploy/docker-compose.public-https-staging.yml"',
        'candidate_compose_is_safe',
        '[[ -n "$candidate_workspace" && ! -L "$candidate_workspace" ]]',
        'git -C "$resolved_candidate_workspace" diff --cached --quiet --exit-code -- "$tracked_path"',
        'git -C "$resolved_candidate_workspace" hash-object -- "$candidate_compose"',
        'candidate_checkout_sha_is_exact',
        'live_release_sha_is_verified',
        'git -C "$resolved_candidate_workspace" merge-base --is-ancestor "$live_release_sha" "$candidate_sha"',
        '--compose "$candidate_compose"',
        '--compose-runtime-path "$runtime_compose"',
        'runtime_env_candidate_guard_blocked',
        'runtime_env_live_transition_unverified',
        'runtime_env_live_compose_transition_detected',
        '--managed-env "$private_dir/tencent-managed.env"',
        '--secret-env "$private_dir/jiejing-saas.staging-oauth.env"',
        '--postgres-env "$private_dir/postgres-localqueue.env"',
        '--required-runtime-service jiejing-saas',
        '--required-runtime-service jiejing-worker',
        'JIEJING_USE_COST_SAVER_OVERRIDE',
        '--compose-override "$cost_saver_override"',
        "SECRET_EXPOSED=false",
    ]
    required_workflow = [
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "runs-on: [self-hosted, jiejing-staging]",
        "fetch-depth: 0",
        "bash deploy/github-actions/jiejing-runner-doctor.sh",
    ]
    required_runbook = [
        "Jiejing Staging Runner Doctor",
        "JIEJING_RUNNER_DOCTOR_STATUS=ready",
        "PUBLIC_HEALTH=ready",
        "local_health_unreachable",
        "docker_cli_missing",
        "sudo_noninteractive_unavailable",
        "disk_usage_at_or_above_90_percent",
        "/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py",
        "never install or update this file",
        "/opt/jiejing-staging/private/docker-compose.cost-saver-local.yml",
        "RUNTIME_ENV_GUARD_STATUS=ready_transition",
        "runtime_env_live_compose_transition_detected",
        "candidate Compose",
        "--compose-runtime-path",
        "current live release SHA",
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
        '$resolved_candidate_workspace/tools/jiejing_runtime_env_overlap_guard.py',
    ]
    present = [marker for marker in forbidden if marker in script or marker in workflow]
    if present:
        return fail("runner doctor contains forbidden marker: " + ",".join(present))
    if 'cat /tmp/jiejing-runner-doctor-runtime-env-guard' in script:
        return fail("runner doctor must not print the runtime env guard payload")
    if "RUNTIME_ENV_GUARD_PATH=" in script or "RUNTIME_ENV_GUARD_REPORT=" in script:
        return fail("runner doctor runtime env status must not expose paths or report bodies")
    if '$resolved_app_dir/tools/jiejing_runtime_env_overlap_guard.py' in script:
        return fail("runner doctor must never execute the deployed app copy of the guard")
    if '$resolved_candidate_workspace/tools/jiejing_runtime_env_overlap_guard.py' in script:
        return fail("runner doctor must never execute the candidate checkout copy of the guard")
    app_safe = script.index('app_dir_safe="true"')
    guard_call = script.index('sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check')
    if not app_safe < guard_call:
        return fail("runner doctor must validate app_dir before any privileged guard invocation")

    print("PASS jiejing_github_runner_doctor_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
