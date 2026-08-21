#!/usr/bin/env python3
"""Validate the scheduled CLS evidence refresh has a minimal safe entrypoint."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "jiejing-cls-probe-auto-refresh.yml"
SCRIPT = ROOT / "deploy" / "github-actions" / "jiejing-cls-probe-auto-refresh.sh"
PATCH_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
PRECLOUD_GATE = ROOT / "tools" / "jiejing_precloud_deployment_gate.py"
RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    required_paths = (WORKFLOW, SCRIPT, PATCH_SCRIPT, PRECLOUD_GATE, RUNBOOK)
    if any(not path.exists() for path in required_paths):
        return fail("CLS auto-refresh workflow, script and release integration files must exist")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    patch_script = PATCH_SCRIPT.read_text(encoding="utf-8")
    precloud_gate = PRECLOUD_GATE.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    required_workflow = [
        "name: Jiejing CLS Probe Auto-Refresh",
        "schedule:",
        "cron: \"17 */12 * * *\"",
        "workflow_dispatch:",
        "permissions:",
        "contents: read",
        "concurrency:",
        "cancel-in-progress: false",
        "runs-on: [self-hosted, jiejing-staging]",
        "timeout-minutes: 10",
        "uses: actions/checkout@v6",
        "fetch-depth: 0",
        "bash deploy/github-actions/jiejing-cls-probe-auto-refresh.sh",
    ]
    required_script = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "SECRET_EXPOSED=false",
    ]
    missing = [f"workflow:{item}" for item in required_workflow if item not in workflow]
    missing.extend(f"script:{item}" for item in required_script if item not in script)
    if missing:
        return fail("CLS auto-refresh entrypoint missing markers: " + ",".join(missing))

    forbidden_workflow = [
        "inputs:",
        "pull_request_target",
        "permissions: write-all",
        "ubuntu-latest",
    ]
    forbidden_shared = [
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "WECHAT_PAY",
        "STRIPE_SECRET_KEY",
        "OPENAI_API_KEY",
        "git credential",
    ]
    present = [f"workflow:{item}" for item in forbidden_workflow if item in workflow]
    present.extend(
        f"shared:{item}" for item in forbidden_shared if item in workflow or item in script
    )
    if present:
        return fail("CLS auto-refresh entrypoint contains forbidden markers: " + ",".join(present))

    required_live_guard = [
        'APP_DIR="/opt/jiejing-staging/app"',
        'DEPLOY_ROOT="/opt/jiejing-staging"',
        'MANAGED_ENV="$PRIVATE_DIR/tencent-managed.env"',
        'RUNTIME_COMPOSE="$APP_DIR/deploy/docker-compose.public-https-staging.yml"',
        'TRUSTED_RUNTIME_ENV_GUARD="/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py"',
        "readlink -f --",
        "stat -c '%u %a'",
        '[[ -f "$MANAGED_ENV" && ! -L "$MANAGED_ENV" ]]',
        '[[ "$private_owner" == "0" && "$private_mode" == "600" ]]',
        'candidate_sha="$(git -C "$resolved_workspace" rev-parse --verify HEAD',
        '[[ "$candidate_sha" == "$GITHUB_SHA" ]]',
        "JIEJING_GITHUB_ACTION_DEPLOY_MANIFEST.txt",
        '[[ "$manifest_dry_run" == "0" ]]',
        '[[ "$live_release_sha" == "$GITHUB_SHA" ]]',
        'cmp -s -- "$RUNTIME_COMPOSE" "$live_release_compose"',
        'com.docker.compose.project=deploy',
        'com.docker.compose.service=jiejing-saas',
        'com.docker.compose.project.config_files',
        'com.docker.compose.project.working_dir',
        '[[ "$runtime_working_dir" == "/app" ]]',
        'sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check',
        '--required-runtime-service jiejing-saas',
        '--required-runtime-service jiejing-worker',
        'LIVE_RELEASE_GUARD_STATUS=ready',
    ]
    missing_live_guard = [item for item in required_live_guard if item not in script]
    if missing_live_guard:
        return fail("trusted live-release guard missing markers: " + ",".join(missing_live_guard))

    guard_ready_index = script.index('LIVE_RELEASE_GUARD_STATUS=ready')
    forbidden_script = [
        "docker compose down",
        "docker volume rm",
        "rm -rf",
        "printenv",
        "env |",
        "set -x",
        'source "$MANAGED_ENV"',
        'cat "$MANAGED_ENV"',
        "$GITHUB_WORKSPACE/tools/jiejing_runtime_env_overlap_guard.py",
    ]
    unsafe_script = [item for item in forbidden_script if item in script]
    if unsafe_script:
        return fail("trusted live-release guard contains forbidden markers: " + ",".join(unsafe_script))

    required_probe = [
        'sudo -n docker run --rm -w /app "$runtime_image" python -c',
        "importlib.util.find_spec('tencentcloud')",
        "Path('tools/jiejing_configure_tencent_runtime_env.py').is_file()",
        'probe_output="$(sudo -n docker run --rm --network bridge',
        '--mount "type=bind,src=$PRIVATE_DIR,dst=/private"',
        '-w /app "$runtime_image" python tools/jiejing_configure_tencent_runtime_env.py',
        "--env-file /private/tencent-managed.env",
        "--verify-provider-cls-probe --apply",
        'probe_result="$(python3 -c',
        'payload.get("status") == "verified"',
        'payload.get("probe_uploaded") is True',
        'payload.get("probe_searchable") is True',
        'payload.get("alarm_queries_exclude_probe") is True',
        'payload.get("event_field_count") == 12',
        'payload.get("event_allowlist_exact") is True',
        'payload.get("notification_test_sent") is False',
        'payload.get("resource_ids_exposed") is False',
        'payload.get("secret_exposed") is False',
        'payload.get("verification_evidence_recorded") is True',
        'unset probe_output',
        'CLS_PROBE_STATUS=verified',
    ]
    missing_probe = [item for item in required_probe if item not in script]
    if missing_probe:
        return fail("verified container probe contract missing markers: " + ",".join(missing_probe))

    guard_index = script.index('LIVE_RELEASE_GUARD_STATUS=ready')
    probe_index = script.index('probe_output="$(sudo -n docker run --rm --network bridge')
    probe_ready_index = script.index('CLS_PROBE_STATUS=verified')
    if not guard_index < probe_index < probe_ready_index:
        return fail("probe must run only after the trusted live-release guard")

    forbidden_probe = [
        "pip install",
        "pip3 install",
        "apt install",
        "apt-get install",
        "python3 tools/jiejing_configure_tencent_runtime_env.py",
        "echo \"$probe_output\"",
        "printf '%s' \"$probe_output\"",
        "notification_test_sent\") is True",
    ]
    unsafe_probe = [item for item in forbidden_probe if item in script]
    if unsafe_probe:
        return fail("verified container probe contains forbidden markers: " + ",".join(unsafe_probe))

    required_reload = [
        'COMPOSE_ARGS=(-p deploy -f "$RUNTIME_COMPOSE")',
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-saas',
        'API_RELOAD_STATUS=ready',
        'http://127.0.0.1:18080/health',
        'https://app.jiejing.shop/health',
        'https://app.jiejing.shop/health/deep',
        'payload.get("status") == "ok"',
        'payload.get("database_startup_status") == "ready"',
        'payload.get("real_platform_writes_enabled") is False',
        'payload.get("requested_real_platform_writes") is False',
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-worker',
        'WORKER_RELOAD_STATUS=ready',
        'https://app.jiejing.shop/readiness/product-saas',
        'operational.get("status") == "ready"',
        'operational.get("database", {}).get("status") == "ready"',
        'operational.get("queue", {}).get("status") == "ready"',
        'operational.get("worker", {}).get("status") == "ready"',
        'item_by_key.get("monitoring_alerting", {}).get("status") == "cloud_monitoring_ready"',
        'item_by_key.get("billing_quota", {}).get("status") == "private_beta_ready_paid_launch_pending"',
        'billing.get("public_charging_allowed") is False',
        'billing.get("charge_now_allowed") is False',
        'billing.get("triggers_real_charge") is False',
        'billing.get("triggers_real_refund") is False',
        'billing.get("real_platform_writes_enabled") is False',
        'billing.get("secret_exposed") is False',
        'readiness.get("production_ready") is False',
        'readiness.get("can_accept_real_customers") is False',
        'READINESS_STATUS=verified',
        'JIEJING_CLS_PROBE_AUTO_REFRESH_STATUS=success',
    ]
    missing_reload = [item for item in required_reload if item not in script]
    if missing_reload:
        return fail("ordered API/worker reload contract missing markers: " + ",".join(missing_reload))

    no_healthcheck_fallback = """if [[ "$state" == "running" && "$health_status" == "none" ]] \\
        && health_contract_ready 'http://127.0.0.1:18080/health'; then"""
    if no_healthcheck_fallback not in script:
        return fail(
            "API containers without a Docker healthcheck must wait for the exact local health contract"
        )
    if '[[ "$state" == "running" && "$health_status" == "none" ]]' in script and (
        no_healthcheck_fallback not in script
    ):
        return fail("Docker health status none must never be accepted without the local health contract")

    api_command_index = script.index(
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-saas'
    )
    api_ready_index = script.index('API_RELOAD_STATUS=ready')
    worker_command_index = script.index(
        'docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-worker'
    )
    worker_ready_index = script.index('WORKER_RELOAD_STATUS=ready')
    readiness_index = script.index('READINESS_STATUS=verified')
    success_index = script.index('JIEJING_CLS_PROBE_AUTO_REFRESH_STATUS=success')
    if not (
        probe_ready_index
        < api_command_index
        < api_ready_index
        < worker_command_index
        < worker_ready_index
        < readiness_index
        < success_index
    ):
        return fail("probe, API, worker and readiness phases must be strictly ordered")

    forbidden_reload = [
        "force-recreate jiejing-vault",
        "force-recreate jiejing-frontend",
        "restart jiejing-vault",
        "restart jiejing-frontend",
        "jiejing-cloudflared",
        "docker compose restart",
    ]
    unsafe_reload = [item for item in forbidden_reload if item in script]
    if unsafe_reload:
        return fail("ordered API/worker reload contains forbidden markers: " + ",".join(unsafe_reload))

    required_release_markers = [
        "deploy/github-actions/jiejing-cls-probe-auto-refresh.sh",
        "tools/test_jiejing_cls_probe_auto_refresh_guardrails.py",
        "docs/superpowers/specs/2026-08-21-cls-probe-auto-refresh-design.md",
        "docs/superpowers/plans/2026-08-21-cls-probe-auto-refresh-implementation-plan.md",
    ]
    missing_release = [item for item in required_release_markers if item not in patch_script]
    if missing_release:
        return fail("staging release whitelist missing CLS auto-refresh files: " + ",".join(missing_release))
    if patch_script.count("tools/test_jiejing_cls_probe_auto_refresh_guardrails.py") < 2:
        return fail("staging patch must whitelist and compile the CLS auto-refresh guardrail test")
    if 'bash -n deploy/github-actions/jiejing-cls-probe-auto-refresh.sh' not in patch_script:
        return fail("staging patch must syntax-check the installed CLS auto-refresh script")

    precloud_marker = (
        '("cls_probe_auto_refresh_guardrails", '
        '[sys.executable, "tools/test_jiejing_cls_probe_auto_refresh_guardrails.py"])'
    )
    if precloud_marker not in precloud_gate:
        return fail("precloud gate must execute the CLS auto-refresh guardrail test")

    required_runbook = [
        "Jiejing CLS Probe Auto-Refresh",
        "LIVE_RELEASE_GUARD_STATUS=ready",
        "CLS_PROBE_STATUS=verified",
        "API_RELOAD_STATUS=ready",
        "WORKER_RELOAD_STATUS=ready",
        "READINESS_STATUS=verified",
        "JIEJING_CLS_PROBE_AUTO_REFRESH_STATUS=success",
        "Probe or guard failure does not restart any service",
        "does not enable public charging or real platform writes",
    ]
    missing_runbook = [item for item in required_runbook if item not in runbook]
    if missing_runbook:
        return fail("runner runbook missing CLS auto-refresh contract: " + ",".join(missing_runbook))

    print("PASS jiejing_cls_probe_auto_refresh_guardrails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
