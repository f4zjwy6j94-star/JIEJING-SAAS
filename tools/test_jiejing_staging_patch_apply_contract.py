#!/usr/bin/env python3
"""Validate the staging patch apply script stays scoped and data-safe."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
DOCKERFILE = ROOT / "Dockerfile.saas"
BUNDLE = ROOT / "tools" / "jiejing_prepare_public_staging_bundle.py"
VAULT_INIT = ROOT / "deploy" / "staging-vault-init-unseal.sh"
HTTPS_COMPOSE = ROOT / "deploy" / "docker-compose.public-https-staging.yml"
HTTP_COMPOSE = ROOT / "deploy" / "docker-compose.public-staging.yml"
PRECLOUD_GATE = ROOT / "tools" / "jiejing_precloud_deployment_gate.py"
GITATTRIBUTES = ROOT / ".gitattributes"
RUNTIME_ENV_RESOLUTION_MANIFEST = (
    ROOT / "deploy" / "jiejing-staging-runtime-env-resolution-manifest.example.json"
)
RUNTIME_ENV_GUARD = ROOT / "tools" / "jiejing_runtime_env_overlap_guard.py"
STAGING_CHECKLIST = ROOT / "deploy" / "tencentcloud-public-staging-checklist.md"
RUNNER_RUNBOOK = ROOT / "docs" / "JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8") if DOCKERFILE.exists() else ""
    bundle = BUNDLE.read_text(encoding="utf-8") if BUNDLE.exists() else ""
    vault_init = VAULT_INIT.read_text(encoding="utf-8") if VAULT_INIT.exists() else ""
    precloud_gate = PRECLOUD_GATE.read_text(encoding="utf-8") if PRECLOUD_GATE.exists() else ""
    runtime_env_guard = RUNTIME_ENV_GUARD.read_text(encoding="utf-8") if RUNTIME_ENV_GUARD.exists() else ""
    staging_checklist = STAGING_CHECKLIST.read_text(encoding="utf-8") if STAGING_CHECKLIST.exists() else ""
    runner_runbook = RUNNER_RUNBOOK.read_text(encoding="utf-8") if RUNNER_RUNBOOK.exists() else ""
    gitattributes = GITATTRIBUTES.read_text(encoding="utf-8") if GITATTRIBUTES.exists() else ""
    compose_files = [
        HTTPS_COMPOSE.read_text(encoding="utf-8") if HTTPS_COMPOSE.exists() else "",
        HTTP_COMPOSE.read_text(encoding="utf-8") if HTTP_COMPOSE.exists() else "",
    ]
    required = [
        "FILES=(",
        ".gitattributes",
        "AGENTS.md",
        "Dockerfile.saas",
        "requirements.saas.txt",
        "deploy/bootstrap.public-staging.ubuntu.sh",
        "deploy/staging-vault-init-unseal.sh",
        "deploy/github-actions/jiejing-runner-doctor.sh",
        "deploy/github-actions/jiejing-staging-deploy.sh",
        "deploy/github-actions/jiejing-staging-rollback.sh",
        "deploy/apply-cloudflare-origin-ufw.sh",
        "deploy/docker-compose.public-staging.yml",
        "deploy/docker-compose.public-https-staging.yml",
        "deploy/docker-compose.staging-infra.yml",
        "deploy/jiejing-saas.postgres-localqueue.env.example",
        "deploy/jiejing-staging-runtime-env-resolution-manifest.example.json",
        "deploy/nginx.public-staging.conf",
        "deploy/Caddyfile.public-staging.systemd",
        "deploy/Caddyfile.production",
        "deploy/jiejing-saas.production.env.example",
        "deploy/jiejing-saas.infra.env.example",
        "deploy/tencentcloud-install-jiejing-ssh-key.sh",
        "deploy/tencentcloud-public-staging-checklist.md",
        "docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md",
        "docs/JIEJING_COMMERCIAL_LAUNCH_RUNBOOK_20260526.md",
        "docs/JIEJING_DOMAIN_PENDING_PURCHASE_PREP_20260618.md",
        "docs/JIEJING_EDGE_WAF_ORIGIN_CALLBACK_PREP_20260618.md",
        "docs/JIEJING_ORIGIN_LOCK_STATUS_20260618.md",
        "docs/JIEJING_STAGING_DISK_CLEANUP_20260619.md",
        "docs/JIEJING_PUBLIC_WAF_ANTI_SCRAPE_RUNBOOK_20260618.md",
        "docs/JIEJING_MAINLAND_PAYMENT_COLLECTION_PLAN_20260629.md",
        "docs/JIEJING_WECHAT_PAY_PRODUCTION_RUNBOOK_20260713.md",
        "docs/superpowers/specs/2026-07-14-billing-operations-maintenance-design.md",
        "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md",
        "docs/JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md",
        "docs/superpowers/specs/2026-06-19-jiejing-first-order-loop-design.md",
        "docs/superpowers/specs/2026-06-19-jiejing-publish-preflight-resolution-design.md",
        "docs/superpowers/specs/2026-08-03-real-merchant-feedback-closure-design.md",
        "docs/superpowers/plans/2026-08-03-real-merchant-feedback-closure-implementation-plan.md",
        "docs/superpowers/specs/2026-08-04-runtime-env-single-source-and-overlap-guard-design.md",
        "docs/superpowers/plans/2026-08-04-runtime-env-overlap-guard-implementation-plan.md",
        "favicon.ico",
        "index.html",
        "app.html",
        "privacy.html",
        "terms.html",
        "refund-policy.html",
        "support.html",
        "risk-disclosure.html",
        "robots.txt",
        "app.js",
        "styles.css",
        "assets/jiejing-app-icon.svg",
        "assets/jiejing-logo-lockup.svg",
        "assets/jiejing-logo-mark.svg",
        "jiejing_saas/merchant_onboarding.py",
        "jiejing_saas/backup_plan.py",
        "jiejing_saas/cos_backup_probe.py",
        "jiejing_saas/billing_manual_beta.py",
        "jiejing_saas/billing_operations_maintenance.py",
        "jiejing_saas/billing_payment_options.py",
        "jiejing_saas/billing_plan.py",
        "jiejing_saas/registration_challenge.py",
        "jiejing_saas/billing_provider_evidence_register.py",
        "jiejing_saas/billing_provider_rehearsal.py",
        "jiejing_saas/billing_webhook.py",
        "jiejing_saas/billing_domain_cutover_rehearsal.py",
        "jiejing_saas/commercial_launch_gate.py",
        "jiejing_saas/domain_readiness.py",
        "jiejing_saas/edge_cutover_preflight.py",
        "jiejing_saas/database_adapter.py",
        "jiejing_saas/queue_adapter.py",
        "jiejing_saas/repository.py",
        "jiejing_saas/product_feedback.py",
        "jiejing_saas/infrastructure_drivers.py",
        "jiejing_saas/paid_launch_approval_packet.py",
        "jiejing_saas/production_evidence_ledger.py",
        "jiejing_saas/production_release_gate.py",
        "jiejing_saas/post_publish_cockpit.py",
        "jiejing_saas/launch_progress.py",
        "deploy/release-evidence.json",
        "jiejing_saas/owner_launch_control.py",
        "jiejing_saas/feasibility_review.py",
        "jiejing_saas/platform_authorization_strategy.py",
        "jiejing_saas/platform_registry.py",
        "jiejing_saas/provider_job_runner.py",
        "jiejing_saas/provider_workflow_plan.py",
        "jiejing_saas/media_asset_pipeline.py",
        "jiejing_saas/media_source_assets.py",
        "jiejing_saas/platform_model_status.py",
        "jiejing_saas/model_value_gate.py",
        "jiejing_saas/model_value_rehearsal.py",
        "jiejing_saas/monitoring.py",
        "jiejing_saas/postgres_repository_runtime.py",
        "jiejing_saas/redis_queue_runtime.py",
        "jiejing_saas/ebay_data_packet.py",
        "jiejing_saas/worker.py",
        "jiejing_saas/workflow_plan.py",
        "jiejing_saas/migrations/001_initial_schema_postgres.sql",
        "tools/jiejing_current_state_guard.py",
        "tools/jiejing_external_launch_blocker_gate.py",
        "tools/jiejing_configure_tencent_runtime_env.py",
        "tools/jiejing_runtime_env_overlap_guard.py",
        "tools/jiejing_cos_backup_probe.py",
        "tools/jiejing_a_class_unattended_gate.py",
        "tools/jiejing_b_class_production_gate.py",
        "tools/jiejing_c_class_production_gate.py",
        "tools/test_jiejing_current_state_guard.py",
        "tools/test_jiejing_external_launch_blocker_gate.py",
        "tools/test_jiejing_historical_ebay_readiness.py",
        "tools/test_jiejing_merchant_onboarding_state.py",
        "tools/test_jiejing_merchant_onboarding_frontend.py",
        "tools/test_jiejing_platform_model_readiness.py",
        "tools/test_jiejing_configure_tencent_runtime_env.py",
        "tools/test_jiejing_runtime_env_overlap_guard.py",
        "tools/test_jiejing_runtime_env_public_contract.py",
        "tools/test_jiejing_cos_backup_probe.py",
        "tools/test_jiejing_frontend_staging_config.py",
        "tools/test_jiejing_media_nav_and_state_restore.py",
        "tools/test_jiejing_saas_clean_settings_and_listing_ui.py",
        "tools/test_jiejing_product_feedback_closure.py",
        "tools/test_jiejing_platform_operations_overview.py",
        "tools/test_jiejing_public_staging_proxy_contract.py",
        "tools/codex_jiejing_operations_console_smoke.js",
        "tools/codex_jiejing_product_feedback_smoke.js",
        "tools/test_jiejing_staging_ebay_oauth_flow_tool.py",
        "tools/test_jiejing_ebay_live_read_http_client.py",
        "tools/test_jiejing_agent_model_assist.py",
        "tools/test_jiejing_model_value_rehearsal.py",
        "tools/test_jiejing_billing_provider_webhook.py",
        "tools/test_jiejing_billing_webhook_subscription_state.py",
        "tools/test_jiejing_billing_domain_cutover_rehearsal.py",
        "tools/test_jiejing_mainland_payment_strategy.py",
        "tools/test_jiejing_manual_beta_payment_flow.py",
        "tools/test_jiejing_billing_provider_evidence_register.py",
        "tools/test_jiejing_billing_provider_rehearsal.py",
        "tools/test_jiejing_domain_launch_gate.py",
        "tools/test_jiejing_monitoring_runbook_gate.py",
        "tools/test_jiejing_chinese_report_source.py",
        "tools/test_jiejing_infrastructure_drivers.py",
        "tools/test_jiejing_postgres_repository_cutover.py",
        "tools/test_jiejing_redis_worker_cutover.py",
        "tools/jiejing_sqlite_to_postgres_rehearsal.py",
        "tools/jiejing_cost_saver_snapshot.py",
        "tools/jiejing_infra_cutover_rehearsal.py",
        "tools/jiejing_worker_cli.py",
        "tools/test_jiejing_worker_cli_contract.py",
        "tools/test_jiejing_domestic_billing_maintenance.py",
        "tools/test_jiejing_cost_saver_snapshot.py",
        "tools/test_jiejing_infra_cutover_rehearsal.py",
        "tools/jiejing_deploy_channel_doctor.py",
        "tools/jiejing_prepare_public_staging_bundle.py",
        "tools/jiejing_staging_deploy.py",
        "tools/test_jiejing_staging_deploy_channel_contract.py",
        "tools/test_jiejing_staging_deploy_disk_guard.py",
        "tools/test_jiejing_agents_md_guardrails.py",
        "tools/test_jiejing_github_actions_deploy_guardrails.py",
        "tools/test_jiejing_github_runner_doctor_guardrails.py",
        "tools/jiejing_billing_provider_evidence_register.py",
        "tools/jiejing_paid_launch_approval_packet.py",
        "tools/jiejing_production_evidence_ledger.py",
        "tools/jiejing_production_release_gate.py",
        "tools/jiejing_domain_pending_purchase_preflight.py",
        "tools/jiejing_edge_cutover_preflight.py",
        "tools/test_jiejing_paid_launch_approval_packet.py",
        "tools/test_jiejing_production_evidence_ledger.py",
        "tools/test_jiejing_production_release_gate.py",
        "tools/test_jiejing_domain_pending_purchase_preflight.py",
        "tools/test_jiejing_edge_cutover_preflight.py",
        "tools/test_jiejing_public_anti_scrape_hardening.py",
        "tools/test_jiejing_first_order_launch_loop_ui.py",
        "tools/test_jiejing_publish_preflight_resolution_ui.py",
        "tools/test_jiejing_owner_launch_control.py",
        "tools/test_jiejing_owner_launch_control_access.py",
        "tools/test_jiejing_owner_launch_control_ui.py",
        "tools/test_jiejing_fixed_launch_progress.py",
        "tools/test_jiejing_merchant_workflow_validation.py",
        "tools/test_jiejing_version_bound_release_evidence.py",
        "tools/test_jiejing_media_capability_router.py",
        "tools/test_jiejing_media_asset_pipeline.py",
        "tools/test_jiejing_media_asset_jobs.py",
        "tools/test_jiejing_expensive_api_rate_limit.py",
        "tools/test_jiejing_platform_trial_activation_guard.py",
        "tools/test_jiejing_registration_challenge_ui.py",
        "tools/test_jiejing_ai_ceo_scroll_retention.py",
        "tools/test_jiejing_ai_ceo_history_pagination.py",
        "tools/test_jiejing_billing_quota_guardrail.py",
        "tools/test_jiejing_session_revocation.py",
        "tools/test_jiejing_global_security_hardening.py",
        "tools/test_jiejing_platform_authorization_strategy.py",
        "tools/test_jiejing_provider_job_contracts.py",
        "tools/test_jiejing_agent_provider_plan.py",
        "tools/test_jiejing_saas_provider_jobs.py",
        "tools/test_jiejing_long_term_memory_and_creative.py",
        "tools/test_jiejing_publish_cleanup_plan.py",
        "tools/test_jiejing_post_publish_cockpit.py",
        "tools/codex_jiejing_owner_launch_control_smoke.js",
        "tools/codex_jiejing_all_modules_clean_smoke.js",
        "tools/codex_jiejing_paid_cutover_decision_smoke.js",
        "jiejing_runtime/policies.py",
        "jiejing_runtime/owned_agents.py",
        "jiejing_runtime/agent_team.py",
        "jiejing_runtime/__init__.py",
        "jiejing_runtime/agent_provider_plan.py",
        "jiejing_runtime/creative_capabilities.py",
        "jiejing_runtime/media_capability_router.py",
        "jiejing_runtime/provider_job_contracts.py",
        "jiejing_runtime/replacement_readiness.py",
        "tools/test_jiejing_merchant_byok_model_and_memory.py",
        "python3 -m py_compile",
        "COMPOSE_ARGS=(-f \"$COMPOSE_FILE\")",
        "cost_saver_override=",
        "JIEJING_USE_COST_SAVER_OVERRIDE",
        "COMPOSE_ARGS+=(-f \"$cost_saver_override\")",
        "docker compose \"${COMPOSE_ARGS[@]}\" build --no-cache jiejing-saas jiejing-worker",
        "docker volume create deploy_jiejing_public_staging_vault_data_v3",
        "api_health_ready=false",
        'if [[ "$api_health_ready" != "true" ]]',
        "Refusing to start the worker before the API health check passes.",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps jiejing-worker",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps --force-recreate jiejing-frontend",
        "install -m 0644 deploy/Caddyfile.public-staging.systemd /etc/caddy/Caddyfile",
        "caddy validate --config /etc/caddy/Caddyfile",
        "docker compose \"${COMPOSE_ARGS[@]}\" exec -T jiejing-saas",
        "urllib.request.urlopen('http://127.0.0.1:8788/health'",
        'NODE_BIN="${JIEJING_NODE_BIN:-node}"',
        '"$NODE_BIN" --check app.js',
        "BACKUP_DIR=",
        "COMPOSE_FILES=",
        "PUBLIC_ASSET_RETIREMENTS=(",
        "assets/demo-cable-organizer.svg",
        "assets/demo-candle-set.svg",
        "assets/demo-jewelry-case.svg",
    ]
    missing = [marker for marker in required if marker not in text]
    if missing:
        return fail("patch apply script missing markers: " + ",".join(missing))
    if "*.sh text eol=lf" not in gitattributes:
        return fail("shell scripts must be pinned to LF in .gitattributes")
    for shell_script in (
        SCRIPT,
        ROOT / "deploy" / "github-actions" / "jiejing-staging-deploy.sh",
        ROOT / "deploy" / "github-actions" / "jiejing-runner-doctor.sh",
    ):
        if b"\r" in shell_script.read_bytes():
            return fail(f"shell script contains CR bytes: {shell_script.name}")
    guard_call = text.index('run_runtime_env_guard "$candidate_compose" "$runtime_compose"')
    first_backup = text.index('mkdir -p "$BACKUP_DIR"')
    first_copy = text.index('cp "$APP_DIR/$rel" "$BACKUP_DIR/$rel"')
    first_install = text.index('install -D -m 0644 "$PATCH_DIR/$rel" "$APP_DIR/$rel"')
    first_docker = text.index('docker compose "${COMPOSE_ARGS[@]}" build')
    if not guard_call < min(first_backup, first_copy, first_install, first_docker):
        return fail("candidate runtime env guard must run before every patch mutation")
    manifest_entry = text.index(
        '"deploy/jiejing-staging-runtime-env-resolution-manifest.example.json"'
    )
    checklist_entry = text.index('"deploy/tencentcloud-public-staging-checklist.md"')
    if manifest_entry >= checklist_entry:
        return fail("runtime env resolution manifest must be copied before the checklist that uses it")
    try:
        resolution_manifest = json.loads(RUNTIME_ENV_RESOLUTION_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fail("runtime env resolution manifest must be readable JSON")
    decisions = resolution_manifest.get("decisions") if isinstance(resolution_manifest, dict) else None
    if not isinstance(decisions, list) or len(decisions) != 24:
        return fail("runtime env resolution manifest must contain the reviewed 24 decisions")
    if any(
        not isinstance(decision, dict)
        or not set(decision).issubset(
            {"key", "authoritative_role", "donor_role", "resolution_action"}
        )
        for decision in decisions
    ):
        return fail("runtime env resolution manifest decisions must remain value-free key/role/action-only")
    compose_donor_keys = {
        decision.get("key")
        for decision in decisions
        if decision.get("donor_role") == "compose"
    }
    if compose_donor_keys != {
        "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED",
        "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED",
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED",
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED",
    }:
        return fail("runtime env resolution manifest must pin the four reviewed Compose donors")
    retire_decisions = {
        decision.get("key"): (
            decision.get("authoritative_role"),
            decision.get("donor_role"),
            decision.get("resolution_action"),
        )
        for decision in decisions
        if "resolution_action" in decision
    }
    expected_retire = (
        "secret",
        "compose",
        "retire_equal_compose_donor_keep_authoritative",
    )
    if retire_decisions != {
        "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": expected_retire,
        "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": expected_retire,
    }:
        return fail("runtime env resolution manifest must explicitly pin the two reviewed media retire actions")
    for marker in (
        'RESOLUTION_APPLY_CONFIRMATION = "APPLY_JIEJING_RUNTIME_ENV_RESOLUTION"',
        '"resolution-apply",',
        "def apply_runtime_env_resolution(",
        'resolution_apply_parser.add_argument("--confirm")',
        '"operation": "resolution-apply"',
        "def _guarded_apply_after_post_validation(",
        "def _encode_runtime_env_file_literal(",
        "def _decode_runtime_env_file_rhs(",
        "def _runtime_env_file_rhs_style(",
        'private_value_style != "single_quoted"',
        "compose_environment_container",
        "compose_scalar_style",
        'declaration.compose_environment_container != "mapping"',
        "donor_service_counts",
        "set(plan.required_runtime_services)",
        '"resolution_apply_value_unrepresentable"',
        "import unicodedata",
        'unicodedata.category(character) in {"Cc", "Zl", "Zp"}',
        "def _validate_rendered_private_candidate(",
        "_parse_env_payload(candidate_payload, snapshot.source)",
        '"apply_candidate_preflight_failed"',
        'text = payload.decode("utf-8")',
        'if character == "\\r":',
        'text[cursor + 1] != "\\n"',
        "lines = text.splitlines()",
    ):
        if marker not in runtime_env_guard:
            return fail("runtime env guard missing independent resolution apply marker: " + marker)
    if 'resolution_parser.add_argument("--apply"' in runtime_env_guard:
        return fail("resolution-plan must never gain an apply flag")
    migration_start = runtime_env_guard.index("def _resolution_migration_plan(")
    migration_end = runtime_env_guard.index("def apply_runtime_env_resolution(", migration_start)
    resolution_migration = runtime_env_guard[migration_start:migration_end]
    if resolution_migration.index('compose_environment_container != "mapping"') > resolution_migration.index(
        "if action.action == RETIRE_EQUAL_COMPOSE_DONOR_ACTION:"
    ):
        return fail("Compose donor mapping-only validation must precede retire action dispatch")
    apply_start = runtime_env_guard.index("def _apply_migration_plan_locked(")
    apply_locked = runtime_env_guard[apply_start:]
    if apply_locked.index("_validate_rendered_private_candidate(") > apply_locked.index(
        "_commit_candidate("
    ):
        return fail("complete rendered private candidate preflight must precede commit")
    env_parse_start = runtime_env_guard.index("def _parse_env_payload(")
    env_parse_end = runtime_env_guard.index("def _parse_env_file(", env_parse_start)
    env_parse = runtime_env_guard[env_parse_start:env_parse_end]
    if 'payload.decode("utf-8").splitlines()' in env_parse:
        return fail("private env payload must be scanned as complete decoded text before splitlines")
    if env_parse.index('unicodedata.category(character) in {"Cc", "Zl", "Zp"}') > env_parse.index(
        "lines = text.splitlines()"
    ):
        return fail("private env Unicode boundary scan must precede splitlines")
    for document_name, document in (
        ("staging checklist", staging_checklist),
        ("runner runbook", runner_runbook),
    ):
        for marker in (
            "resolution-apply",
            "APPLY_JIEJING_RUNTIME_ENV_RESOLUTION",
            "does not",
            "deploy",
            "restart",
            "final readonly",
            "single-quoted `env_file`",
            "single-quoted source",
            "Compose environment list",
            "mapping-only",
            "including evidence-only retire",
            "Unicode `Cc`",
            "`Zl` line separators",
            "`Zp` paragraph separators",
            "fully rendered private candidate",
            "exactly once",
            "complete text before `splitlines`",
            "physical LF and CRLF",
            "lone CR",
            "mixed LF/CRLF",
        ):
            if marker not in document:
                return fail(f"{document_name} missing resolution apply safety marker: {marker}")
    for marker in (
        'TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"',
        "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1",
        "REFUSE_UNTRUSTED_COST_SAVER_OVERRIDE=1",
        'trusted_guard_resolved="$(readlink -f -- "$TRUSTED_RUNTIME_ENV_GUARD"',
        "stat -c '%u %a'",
        '[[ -f "$path" && ! -L "$path" ]]',
        '(( (8#$mode & 0022) == 0 ))',
        'current="$(dirname -- "$path")"',
        '[[ -d "$current" && ! -L "$current" ]]',
        'private_dir="$deploy_root/private"',
        '--managed-env "$private_dir/tencent-managed.env"',
        '--secret-env "$private_dir/jiejing-saas.staging-oauth.env"',
        '--postgres-env "$private_dir/postgres-localqueue.env"',
        '--compose-runtime-path "$runtime_compose_path"',
        '--required-runtime-service jiejing-saas',
        '--required-runtime-service jiejing-worker',
        '--compose-override "$cost_saver_override"',
        "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1",
        "RUNTIME_ENV_GUARD_STATUS=passed",
    ):
        if marker not in text:
            return fail(f"patch apply runtime env guard missing marker: {marker}")
    if "jiejing_runtime_env_overlap_guard.py\" migrate" in text:
        return fail("patch apply must never migrate private env files automatically")
    if '$PATCH_DIR/tools/jiejing_runtime_env_overlap_guard.py' in text:
        return fail("patch apply must never execute a candidate runtime env guard")
    compiled_or_checked = {
        "jiejing_saas/product_feedback.py": 2,
        "tools/test_jiejing_product_feedback_closure.py": 2,
        "tools/test_jiejing_media_nav_and_state_restore.py": 2,
        "tools/test_jiejing_saas_clean_settings_and_listing_ui.py": 2,
        "tools/test_jiejing_platform_operations_overview.py": 2,
        "tools/test_jiejing_public_staging_proxy_contract.py": 2,
        "tools/codex_jiejing_operations_console_smoke.js": 2,
        "tools/codex_jiejing_product_feedback_smoke.js": 2,
    }
    for marker, minimum_count in compiled_or_checked.items():
        if text.count(marker) < minimum_count:
            return fail(f"patch apply script must whitelist and syntax-check the feedback closure file: {marker}")
    for marker in [
        '("product_feedback_closure", [sys.executable, "tools/test_jiejing_product_feedback_closure.py"])',
        '("product_feedback_browser_smoke", ["node", "tools/codex_jiejing_product_feedback_smoke.js"])',
        '("runtime_env_overlap_guard", [sys.executable, "tools/test_jiejing_runtime_env_overlap_guard.py"])',
        '("runtime_env_public_contract", [sys.executable, "tools/test_jiejing_runtime_env_public_contract.py"])',
    ]:
        if marker not in precloud_gate:
            return fail(f"precloud gate missing product-feedback closure check: {marker}")
    if 'python -c "import jiejing_saas.api_server; import jiejing_saas.repository"' not in dockerfile:
        return fail("SaaS image must import its backend entry points during build")
    api_start = text.index('up -d --no-deps jiejing-saas')
    health_gate = text.index('if [[ "$api_health_ready" != "true" ]]', api_start)
    worker_start = text.index('up -d --no-deps jiejing-worker', api_start)
    if not api_start < health_gate < worker_start:
        return fail("worker startup must remain behind the API health gate")
    forbidden = [
        "rm -rf /",
        "docker volume rm",
        "docker compose down -v",
        "truncate",
        "DROP DATABASE",
        "/data/saas.sqlite",
    ]
    present = [marker for marker in forbidden if marker in text]
    if present:
        return fail("patch apply script contains forbidden destructive marker: " + ",".join(present))
    for marker in [
        "JIEJING_VAULT_READY_WAIT_SECONDS",
        'while [ "$attempt" -lt "$wait_seconds" ]',
        'if [ "$ready_count" -ge 2 ]',
        "STAGING_VAULT_STATUS=blocked_not_ready",
        'while [ "$unseal_attempt" -lt 10 ]',
        "STAGING_VAULT_STATUS=blocked_unseal_failed",
        'init_tmp="${INIT_FILE}.tmp.$$"',
        'result_tmp="${TOKEN_FILE}.tmp.$$"',
        'mv -f "$init_tmp" "$INIT_FILE"',
        'mv -f "$result_tmp" "$TOKEN_FILE"',
    ]:
        if marker not in vault_init:
            return fail(f"vault init must wait for the container readiness signal: {marker}")
    for compose in compose_files:
        for service, next_service in (("jiejing-saas", "jiejing-worker"), ("jiejing-worker", "jiejing-vault")):
            service_start = compose.index(f"  {service}:")
            service_end = compose.index(f"  {next_service}:", service_start)
            service_block = compose[service_start:service_end]
            managed_env = "../../private/tencent-managed.env"
            if service_block.count(managed_env) != 1:
                return fail(f"{service} must consume the single private Tencent-managed env path")
            if "../../private/jiejing-saas.staging-oauth.env" in service_block:
                if service_block.index(managed_env) > service_block.index("../../private/jiejing-saas.staging-oauth.env"):
                    return fail(f"{service} must load the broad Tencent env before the narrower OAuth env")
        vault_start = compose.index("  jiejing-vault:")
        vault_end = compose.index("  jiejing-frontend:", vault_start)
        if "env_file:" in compose[vault_start:vault_end]:
            return fail("Vault service must not inherit the SaaS provider secret environment")
    bundle_required = [
        "public_staging_patch_whitelist_v1",
        'APPLY_SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"',
        "def _apply_patch_file_list",
        "unable to parse FILES whitelist",
        "apply patch script must include itself",
        '"full_assets_included": False',
        'manifest["zip_path"] = zip_path.relative_to(ROOT).as_posix()',
    ]
    missing_bundle = [marker for marker in bundle_required if marker not in bundle]
    if missing_bundle:
        return fail("public staging bundle script missing whitelist scope markers: " + ",".join(missing_bundle))
    for forbidden_bundle_marker in [
        'INCLUDE_DIRS = [',
        '"assets",',
        'base.rglob("*")',
    ]:
        if forbidden_bundle_marker in bundle:
            return fail(f"public staging bundle must not include broad directory packaging: {forbidden_bundle_marker}")
    print("PASS jiejing_staging_patch_apply_contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
