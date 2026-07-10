#!/usr/bin/env python3
"""Validate the staging patch apply script stays scoped and data-safe."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "apply-staging-patch.sh"
BUNDLE = ROOT / "tools" / "jiejing_prepare_public_staging_bundle.py"
VAULT_INIT = ROOT / "deploy" / "staging-vault-init-unseal.sh"
HTTPS_COMPOSE = ROOT / "deploy" / "docker-compose.public-https-staging.yml"
HTTP_COMPOSE = ROOT / "deploy" / "docker-compose.public-staging.yml"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8") if SCRIPT.exists() else ""
    bundle = BUNDLE.read_text(encoding="utf-8") if BUNDLE.exists() else ""
    vault_init = VAULT_INIT.read_text(encoding="utf-8") if VAULT_INIT.exists() else ""
    compose_files = [
        HTTPS_COMPOSE.read_text(encoding="utf-8") if HTTPS_COMPOSE.exists() else "",
        HTTP_COMPOSE.read_text(encoding="utf-8") if HTTP_COMPOSE.exists() else "",
    ]
    required = [
        "FILES=(",
        "AGENTS.md",
        "Dockerfile.saas",
        "requirements.saas.txt",
        "deploy/staging-vault-init-unseal.sh",
        "deploy/github-actions/jiejing-runner-doctor.sh",
        "deploy/github-actions/jiejing-staging-deploy.sh",
        "deploy/github-actions/jiejing-staging-rollback.sh",
        "deploy/apply-cloudflare-origin-ufw.sh",
        "deploy/docker-compose.public-staging.yml",
        "deploy/docker-compose.public-https-staging.yml",
        "deploy/docker-compose.staging-infra.yml",
        "deploy/nginx.public-staging.conf",
        "deploy/Caddyfile.public-staging.systemd",
        "deploy/Caddyfile.production",
        "deploy/jiejing-saas.production.env.example",
        "deploy/jiejing-saas.infra.env.example",
        "deploy/tencentcloud-install-jiejing-ssh-key.sh",
        "docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md",
        "docs/JIEJING_COMMERCIAL_LAUNCH_RUNBOOK_20260526.md",
        "docs/JIEJING_DOMAIN_PENDING_PURCHASE_PREP_20260618.md",
        "docs/JIEJING_EDGE_WAF_ORIGIN_CALLBACK_PREP_20260618.md",
        "docs/JIEJING_ORIGIN_LOCK_STATUS_20260618.md",
        "docs/JIEJING_STAGING_DISK_CLEANUP_20260619.md",
        "docs/JIEJING_PUBLIC_WAF_ANTI_SCRAPE_RUNBOOK_20260618.md",
        "docs/JIEJING_MAINLAND_PAYMENT_COLLECTION_PLAN_20260629.md",
        "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md",
        "docs/JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md",
        "docs/superpowers/specs/2026-06-19-jiejing-first-order-loop-design.md",
        "docs/superpowers/specs/2026-06-19-jiejing-publish-preflight-resolution-design.md",
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
        "jiejing_saas/backup_plan.py",
        "jiejing_saas/billing_manual_beta.py",
        "jiejing_saas/billing_payment_options.py",
        "jiejing_saas/billing_plan.py",
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
        "jiejing_saas/infrastructure_drivers.py",
        "jiejing_saas/paid_launch_approval_packet.py",
        "jiejing_saas/production_evidence_ledger.py",
        "jiejing_saas/production_release_gate.py",
        "jiejing_saas/post_publish_cockpit.py",
        "jiejing_saas/owner_launch_control.py",
        "jiejing_saas/feasibility_review.py",
        "jiejing_saas/platform_authorization_strategy.py",
        "jiejing_saas/platform_registry.py",
        "jiejing_saas/provider_job_runner.py",
        "jiejing_saas/provider_workflow_plan.py",
        "jiejing_saas/media_asset_pipeline.py",
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
        "tools/jiejing_configure_tencent_runtime_env.py",
        "tools/jiejing_a_class_unattended_gate.py",
        "tools/jiejing_b_class_production_gate.py",
        "tools/jiejing_c_class_production_gate.py",
        "tools/test_jiejing_current_state_guard.py",
        "tools/test_jiejing_platform_model_readiness.py",
        "tools/test_jiejing_configure_tencent_runtime_env.py",
        "tools/test_jiejing_frontend_staging_config.py",
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
        "tools/test_jiejing_cost_saver_snapshot.py",
        "tools/test_jiejing_infra_cutover_rehearsal.py",
        "tools/jiejing_deploy_channel_doctor.py",
        "tools/jiejing_prepare_public_staging_bundle.py",
        "tools/jiejing_staging_deploy.py",
        "tools/test_jiejing_staging_deploy_channel_contract.py",
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
        "tools/test_jiejing_media_capability_router.py",
        "tools/test_jiejing_media_asset_pipeline.py",
        "tools/test_jiejing_media_asset_jobs.py",
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
        "COST_SAVER_OVERRIDE=",
        "JIEJING_USE_COST_SAVER_OVERRIDE",
        "COMPOSE_ARGS+=(-f \"$COST_SAVER_OVERRIDE\")",
        "docker compose \"${COMPOSE_ARGS[@]}\" build --no-cache jiejing-saas jiejing-worker",
        "docker volume create deploy_jiejing_public_staging_vault_data_v3",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps jiejing-worker",
        "docker compose \"${COMPOSE_ARGS[@]}\" up -d --no-deps --force-recreate jiejing-frontend",
        "install -m 0644 deploy/Caddyfile.public-staging.systemd /etc/caddy/Caddyfile",
        "caddy validate --config /etc/caddy/Caddyfile",
        "docker compose \"${COMPOSE_ARGS[@]}\" exec -T jiejing-saas",
        "urllib.request.urlopen('http://127.0.0.1:8788/health'",
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
