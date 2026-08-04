#!/usr/bin/env bash
set -euo pipefail

# Apply a whitelisted Jiejing SaaS staging patch after it has been uploaded and
# extracted on the server. This script does not touch data volumes or secrets.

APP_DIR="${JIEJING_APP_DIR:-/opt/jiejing-staging/app}"
PATCH_DIR="${1:-}"
TRUSTED_RUNTIME_ENV_GUARD="${JIEJING_TRUSTED_RUNTIME_ENV_GUARD:-/usr/local/libexec/jiejing/jiejing_runtime_env_overlap_guard.py}"

if [[ -z "$PATCH_DIR" ]]; then
  echo "Usage: bash deploy/apply-staging-patch.sh /path/to/extracted/patch" >&2
  exit 2
fi

cd "$APP_DIR"
APP_DIR="$(pwd -P)"
PATCH_DIR="$(cd "$PATCH_DIR" && pwd)"
BACKUP_DIR="$APP_DIR/output/staging-patch-backups/$(date +%Y%m%d-%H%M%S)"

FILES=(
  ".gitattributes"
  "AGENTS.md"
  "Dockerfile.saas"
  "requirements.saas.txt"
  "deploy/apply-staging-patch.sh"
  "deploy/bootstrap.public-staging.ubuntu.sh"
  "deploy/staging-vault-init-unseal.sh"
  "deploy/github-actions/jiejing-runner-doctor.sh"
  "deploy/github-actions/jiejing-staging-deploy.sh"
  "deploy/github-actions/jiejing-staging-rollback.sh"
  "deploy/apply-cloudflare-origin-ufw.sh"
  "deploy/docker-compose.public-staging.yml"
  "deploy/docker-compose.public-https-staging.yml"
  "deploy/docker-compose.staging-infra.yml"
  "deploy/jiejing-saas.postgres-localqueue.env.example"
  "deploy/nginx.public-staging.conf"
  "deploy/Caddyfile.public-staging"
  "deploy/Caddyfile.public-staging.systemd"
  "deploy/Caddyfile.route-a-edge"
  "deploy/Caddyfile.production"
  "deploy/jiejing-saas.env.example"
  "deploy/jiejing-saas.production.env.example"
  "deploy/jiejing-route-a-edge.env.example"
  "deploy/jiejing-saas.infra.env.example"
  "deploy/jiejing-saas.tencent-managed.env.example"
  "deploy/tencentcloud-install-jiejing-ssh-key.sh"
  "deploy/tencentcloud-public-staging-checklist.md"
  "docs/JIEJING_INDEPENDENT_SAAS_DEPLOYMENT_RUNBOOK.md"
  "docs/JIEJING_COMMERCIAL_LAUNCH_RUNBOOK_20260526.md"
  "docs/JIEJING_DOMAIN_PENDING_PURCHASE_PREP_20260618.md"
  "docs/JIEJING_EDGE_WAF_ORIGIN_CALLBACK_PREP_20260618.md"
  "docs/JIEJING_ORIGIN_LOCK_STATUS_20260618.md"
  "docs/JIEJING_STAGING_DISK_CLEANUP_20260619.md"
  "docs/JIEJING_PUBLIC_WAF_ANTI_SCRAPE_RUNBOOK_20260618.md"
  "docs/JIEJING_NO_CHARGE_BILLING_REHEARSAL_20260618.md"
  "docs/JIEJING_MAINLAND_PAYMENT_COLLECTION_PLAN_20260629.md"
  "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md"
  "docs/JIEJING_GITHUB_SELF_HOSTED_RUNNER_DEPLOY_RUNBOOK_20260622.md"
  "docs/JIEJING_GITHUB_CI_STATUS_20260617.md"
  "docs/JIEJING_FRONTEND_SPLIT_STATUS_20260617.md"
  "docs/JIEJING_NEW_EBAY_ACCOUNT_LOW_RISK_RUNBOOK_20260617.md"
  "docs/JIEJING_EBAY_MARKETPLACE_ACCOUNT_DELETION_DESIGN_20260713.md"
  "docs/JIEJING_WECHAT_PAY_PRODUCTION_RUNBOOK_20260713.md"
  "docs/superpowers/specs/2026-07-14-billing-operations-maintenance-design.md"
  "docs/superpowers/specs/2026-07-14-operations-metering-design.md"
  "docs/superpowers/specs/2026-07-15-independent-operations-console-design.md"
  "docs/superpowers/specs/2026-06-19-jiejing-first-order-loop-design.md"
  "docs/superpowers/specs/2026-06-19-jiejing-publish-preflight-resolution-design.md"
  "docs/superpowers/specs/2026-08-03-real-merchant-feedback-closure-design.md"
  "docs/superpowers/plans/2026-08-03-real-merchant-feedback-closure-implementation-plan.md"
  "docs/superpowers/specs/2026-08-04-runtime-env-single-source-and-overlap-guard-design.md"
  "docs/superpowers/plans/2026-08-04-runtime-env-overlap-guard-implementation-plan.md"
  "favicon.ico"
  "index.html"
  "app.html"
  "ops.html"
  "privacy.html"
  "terms.html"
  "refund-policy.html"
  "support.html"
  "risk-disclosure.html"
  "robots.txt"
  "app.js"
  "ops.js"
  "styles.css"
  "ops.css"
  "assets/jiejing-app-icon.svg"
  "assets/jiejing-logo-lockup.svg"
  "assets/jiejing-logo-mark.svg"
  "assets/jiejing-first-party-analytics.js"
  "assets/jiejing-settings-panels.js"
  "jiejing_saas/account_health.py"
  "jiejing_saas/merchant_onboarding.py"
  "jiejing_saas/backup_plan.py"
  "jiejing_saas/cos_backup_probe.py"
  "jiejing_saas/billing_checkout.py"
  "jiejing_saas/billing_domestic.py"
  "jiejing_saas/billing_operations_maintenance.py"
  "jiejing_saas/billing_domain_cutover_rehearsal.py"
  "jiejing_saas/billing_manual_beta.py"
  "jiejing_saas/billing_payment_options.py"
  "jiejing_saas/billing_plan.py"
  "jiejing_saas/billing_provider_evidence_register.py"
  "jiejing_saas/billing_provider_rehearsal.py"
  "jiejing_saas/billing_test_provider.py"
  "jiejing_saas/billing_webhook.py"
  "jiejing_saas/billing_wechat_pay.py"
  "jiejing_saas/ai_ceo_chat.py"
  "jiejing_saas/commercial_launch_gate.py"
  "jiejing_saas/controlled_bridges.py"
  "jiejing_saas/domain_readiness.py"
  "jiejing_saas/edge_cutover_preflight.py"
  "jiejing_saas/database_adapter.py"
  "jiejing_saas/queue_adapter.py"
  "jiejing_saas/queue_plan.py"
  "jiejing_saas/repository.py"
  "jiejing_saas/product_feedback.py"
  "jiejing_saas/infrastructure_drivers.py"
  "jiejing_saas/operational_health.py"
  "jiejing_saas/operations_metering.py"
  "jiejing_saas/launch_progress.py"
  "deploy/release-evidence.json"
  "jiejing_saas/owner_launch_control.py"
  "jiejing_saas/feasibility_review.py"
  "jiejing_saas/platform_authorization_strategy.py"
  "jiejing_saas/platform_registry.py"
  "jiejing_saas/paid_launch_approval_packet.py"
  "jiejing_saas/production_evidence_ledger.py"
  "jiejing_saas/production_release_gate.py"
  "jiejing_saas/post_publish_cockpit.py"
  "jiejing_saas/media_asset_pipeline.py"
  "jiejing_saas/media_credits.py"
  "jiejing_saas/media_source_assets.py"
  "jiejing_saas/provider_job_runner.py"
  "jiejing_saas/provider_workflow_plan.py"
  "jiejing_saas/model_provider_catalog.py"
  "jiejing_saas/platform_model_status.py"
  "jiejing_saas/model_value_gate.py"
  "jiejing_saas/model_value_rehearsal.py"
  "jiejing_saas/monitoring.py"
  "jiejing_saas/staging_security_gate.py"
  "jiejing_saas/vault_secret_resolver.py"
  "jiejing_saas/vault_adapter.py"
  "jiejing_saas/postgres_repository_runtime.py"
  "jiejing_saas/redis_queue_runtime.py"
  "jiejing_saas/ebay_data_packet.py"
  "jiejing_saas/ebay_account_deletion.py"
  "jiejing_saas/worker.py"
  "jiejing_saas/api_server.py"
  "jiejing_saas/registration_challenge.py"
  "jiejing_saas/security.py"
  "jiejing_saas/readiness.py"
  "jiejing_saas/config.py"
  "jiejing_saas/ebay_credential_preflight.py"
  "jiejing_saas/ebay_http_client.py"
  "jiejing_saas/ebay_token_refresh_adapter.py"
  "jiejing_saas/ebay_read_normalizers.py"
  "jiejing_saas/ebay_live_read_adapter.py"
  "jiejing_saas/ebay_oauth.py"
  "jiejing_saas/ebay_oauth_callback.py"
  "jiejing_saas/ebay_write_adapter.py"
  "jiejing_saas/workflow_plan.py"
  "jiejing_saas/migrations/001_initial_schema_postgres.sql"
  "jiejing_runtime/execution_preflight.py"
  "jiejing_runtime/__init__.py"
  "jiejing_runtime/agent_provider_plan.py"
  "jiejing_runtime/agent_team.py"
  "jiejing_runtime/creative_capabilities.py"
  "jiejing_runtime/media_capability_router.py"
  "jiejing_runtime/media_generation.py"
  "jiejing_runtime/model_clients.py"
  "jiejing_runtime/owned_agents.py"
  "jiejing_runtime/policies.py"
  "jiejing_runtime/provider_job_contracts.py"
  "jiejing_runtime/replacement_readiness.py"
  "jiejing_runtime/adapters.py"
  "tools/jiejing_sqlite_to_postgres_rehearsal.py"
  "tools/jiejing_cost_saver_snapshot.py"
  "tools/jiejing_infra_cutover_rehearsal.py"
  "tools/jiejing_worker_cli.py"
  "tools/jiejing_upsert_private_env_secret.py"
  "tools/jiejing_wechat_pay_noncharge_acceptance.py"
  "tools/jiejing_wechat_pay_live_acceptance.py"
  "tools/jiejing_wechat_pay_acceptance_verify.py"
  "tools/test_jiejing_sqlite_to_postgres_rehearsal.py"
  "tools/test_jiejing_cost_saver_snapshot.py"
  "tools/test_jiejing_infra_cutover_rehearsal.py"
  "tools/test_jiejing_worker_cli_contract.py"
  "tools/test_jiejing_domestic_billing_maintenance.py"
  "tools/test_jiejing_ebay_account_deletion.py"
  "tools/test_jiejing_operations_console.py"
  "tools/jiejing_infrastructure_stage_gate.py"
  "tools/jiejing_deploy_channel_doctor.py"
  "tools/jiejing_deploy_frontend_staging_with_key.ps1"
  "tools/jiejing_prepare_stable_deploy_key.ps1"
  "tools/jiejing_prepare_public_staging_bundle.py"
  "tools/jiejing_staging_deploy.py"
  "tools/jiejing_current_state_guard.py"
  "tools/jiejing_external_launch_blocker_gate.py"
  "tools/jiejing_configure_tencent_runtime_env.py"
  "tools/jiejing_runtime_env_overlap_guard.py"
  "tools/jiejing_cos_backup_probe.py"
  "tools/jiejing_a_class_unattended_gate.py"
  "tools/jiejing_b_class_production_gate.py"
  "tools/jiejing_c_class_production_gate.py"
  "tools/test_jiejing_deploy_channel_doctor.py"
  "tools/test_jiejing_staging_deploy_channel_contract.py"
  "tools/test_jiejing_staging_deploy_disk_guard.py"
  "tools/test_jiejing_agents_md_guardrails.py"
  "tools/test_jiejing_github_actions_deploy_guardrails.py"
  "tools/test_jiejing_github_runner_doctor_guardrails.py"
  "tools/jiejing_precloud_deployment_gate.py"
  "tools/test_jiejing_current_state_guard.py"
  "tools/test_jiejing_external_launch_blocker_gate.py"
  "tools/test_jiejing_historical_ebay_readiness.py"
  "tools/test_jiejing_merchant_onboarding_state.py"
  "tools/test_jiejing_merchant_onboarding_frontend.py"
  "tools/test_jiejing_configure_tencent_runtime_env.py"
  "tools/test_jiejing_runtime_env_overlap_guard.py"
  "tools/test_jiejing_runtime_env_public_contract.py"
  "tools/test_jiejing_cos_backup_probe.py"
  "tools/test_jiejing_frontend_staging_config.py"
  "tools/test_jiejing_media_nav_and_state_restore.py"
  "tools/test_jiejing_saas_clean_settings_and_listing_ui.py"
  "tools/test_jiejing_product_feedback_closure.py"
  "tools/test_jiejing_platform_operations_overview.py"
  "tools/test_jiejing_public_staging_proxy_contract.py"
  "tools/codex_jiejing_operations_console_smoke.js"
  "tools/codex_jiejing_product_feedback_smoke.js"
  "tools/test_jiejing_saas_p0_security_guardrails.py"
  "tools/test_jiejing_runtime_knowledge.py"
  "tools/test_jiejing_runtime_mvp.py"
  "tools/test_jiejing_staging_ebay_oauth_flow_tool.py"
  "tools/test_jiejing_ebay_live_read_http_client.py"
  "tools/test_jiejing_agent_model_assist.py"
  "tools/jiejing_controlled_model_value_proof.py"
  "tools/test_jiejing_controlled_model_value_proof.py"
  "tools/test_jiejing_model_value_rehearsal.py"
  "tools/test_jiejing_billing_provider_webhook.py"
  "tools/test_jiejing_billing_test_provider.py"
  "tools/test_jiejing_billing_domain_cutover_rehearsal.py"
  "tools/test_jiejing_billing_webhook_subscription_state.py"
  "tools/test_jiejing_mainland_payment_strategy.py"
  "tools/test_jiejing_manual_beta_payment_flow.py"
  "tools/test_jiejing_billing_provider_evidence_register.py"
  "tools/test_jiejing_billing_provider_rehearsal.py"
  "tools/test_jiejing_ebay_vault_token_refresh_adapter.py"
  "tools/test_jiejing_domain_launch_gate.py"
  "tools/test_jiejing_monitoring_runbook_gate.py"
  "tools/test_jiejing_chinese_report_source.py"
  "tools/test_jiejing_merchant_byok_model_and_memory.py"
  "tools/test_jiejing_platform_model_readiness.py"
  "tools/test_jiejing_ebay_refresh_secret_readiness.py"
  "tools/test_jiejing_infrastructure_drivers.py"
  "tools/test_jiejing_postgres_durable_queue_adapter.py"
  "tools/test_jiejing_controlled_bridges.py"
  "tools/test_jiejing_postgres_repository_cutover.py"
  "tools/test_jiejing_redis_worker_cutover.py"
  "tools/test_jiejing_vault_secret_resolver.py"
  "tools/test_jiejing_tencent_cloud_integrations.py"
  "tools/test_jiejing_managed_infra_readiness_cutover.py"
  "tools/test_jiejing_saas_backend_mvp.py"
  "tools/test_jiejing_ebay_write_adapter.py"
  "tools/test_jiejing_publish_cleanup_plan.py"
  "tools/test_jiejing_post_publish_cockpit.py"
  "tools/jiejing_productization_stage_gate.py"
  "tools/jiejing_secret_scan.py"
  "tools/jiejing_new_ebay_account_low_risk_check.py"
  "tools/jiejing_billing_provider_evidence_register.py"
  "tools/jiejing_paid_launch_approval_packet.py"
  "tools/jiejing_production_evidence_ledger.py"
  "tools/jiejing_production_release_gate.py"
  "tools/jiejing_domain_pending_purchase_preflight.py"
  "tools/jiejing_registered_domain_cutover_status.py"
  "tools/jiejing_edge_cutover_preflight.py"
  "tools/test_jiejing_staging_patch_apply_contract.py"
  "tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py"
  "tools/test_jiejing_saas_ai_ceo_platform_model_fallback.py"
  "tools/test_jiejing_operational_health_readiness.py"
  "tools/test_jiejing_stripe_checkout_portal.py"
  "tools/test_jiejing_queue_recovery_heartbeat.py"
  "tools/test_jiejing_account_health_incident_mode.py"
  "tools/test_jiejing_frontend_settings_module_split.py"
  "tools/test_jiejing_media_asset_pipeline.py"
  "tools/test_jiejing_media_asset_jobs.py"
  "tools/test_jiejing_media_capability_router.py"
  "tools/test_jiejing_platform_authorization_strategy.py"
  "tools/test_jiejing_provider_job_contracts.py"
  "tools/test_jiejing_agent_provider_plan.py"
  "tools/test_jiejing_saas_provider_jobs.py"
  "tools/test_jiejing_long_term_memory_and_creative.py"
  "tools/test_jiejing_new_ebay_account_low_risk_runbook.py"
  "tools/test_jiejing_paid_launch_approval_packet.py"
  "tools/test_jiejing_production_evidence_ledger.py"
  "tools/test_jiejing_production_release_gate.py"
  "tools/test_jiejing_domain_pending_purchase_preflight.py"
  "tools/test_jiejing_registered_domain_cutover_status.py"
  "tools/test_jiejing_edge_cutover_preflight.py"
  "tools/test_jiejing_expensive_api_rate_limit.py"
  "tools/test_jiejing_platform_trial_activation_guard.py"
  "tools/test_jiejing_registration_challenge_ui.py"
  "tools/test_jiejing_ai_ceo_scroll_retention.py"
  "tools/test_jiejing_ai_ceo_history_pagination.py"
  "tools/test_jiejing_billing_quota_guardrail.py"
  "tools/test_jiejing_session_revocation.py"
  "tools/test_jiejing_public_anti_scrape_hardening.py"
  "tools/test_jiejing_public_security_status_ui.py"
  "tools/test_jiejing_saas_readable_decision_service_settings_ui.py"
  "tools/test_jiejing_first_order_launch_loop_ui.py"
  "tools/test_jiejing_publish_preflight_resolution_ui.py"
  "tools/test_jiejing_owner_launch_control.py"
  "tools/test_jiejing_owner_launch_control_access.py"
  "tools/test_jiejing_owner_launch_control_ui.py"
  "tools/test_jiejing_fixed_launch_progress.py"
  "tools/test_jiejing_merchant_workflow_validation.py"
  "tools/test_jiejing_version_bound_release_evidence.py"
  "tools/codex_jiejing_owner_launch_control_smoke.js"
  "tools/codex_jiejing_all_modules_clean_smoke.js"
  "tools/codex_jiejing_paid_cutover_decision_smoke.js"
)

PUBLIC_ASSET_RETIREMENTS=(
  "assets/demo-cable-organizer.svg"
  "assets/demo-candle-set.svg"
  "assets/demo-jewelry-case.svg"
)

for rel in "${FILES[@]}"; do
  if [[ "$rel" == *".."* || "$rel" = /* ]]; then
    echo "Refusing unsafe path: $rel" >&2
    exit 3
  fi
  if [[ ! -f "$PATCH_DIR/$rel" ]]; then
    echo "Patch is missing required file: $rel" >&2
    exit 4
  fi
done

candidate_compose="$PATCH_DIR/deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$candidate_compose" ]]; then
  candidate_compose="$PATCH_DIR/deploy/docker-compose.public-staging.yml"
fi
runtime_compose="$APP_DIR/deploy/$(basename -- "$candidate_compose")"
deploy_root="$(cd "$APP_DIR/.." && pwd -P)"
private_dir="$deploy_root/private"
cost_saver_override=""

trusted_root_owned_path_chain_is_safe() {
  local path="$1"
  local resolved current metadata owner mode
  case "$path" in
    /*) ;;
    *) return 1 ;;
  esac
  [[ -f "$path" && ! -L "$path" ]] || return 1
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ -n "$resolved" && "$resolved" == "$path" ]] || return 1
  metadata="$(stat -c '%u %a' -- "$path" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "0" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 )) || return 1

  current="$(dirname -- "$path")"
  while :; do
    [[ -d "$current" && ! -L "$current" ]] || return 1
    metadata="$(stat -c '%u %a' -- "$current" 2>/dev/null || true)"
    read -r owner mode <<<"$metadata"
    [[ "$owner" == "0" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
    (( (8#$mode & 0022) == 0 )) || return 1
    [[ "$current" == "/" ]] && break
    current="$(dirname -- "$current")"
  done
}

if ! trusted_root_owned_path_chain_is_safe "$TRUSTED_RUNTIME_ENV_GUARD"; then
  echo "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1" >&2
  exit 7
fi
trusted_guard_resolved="$(readlink -f -- "$TRUSTED_RUNTIME_ENV_GUARD" 2>/dev/null || true)"
[[ "$trusted_guard_resolved" == "$TRUSTED_RUNTIME_ENV_GUARD" ]] || {
  echo "REFUSE_UNTRUSTED_RUNTIME_ENV_GUARD=1" >&2
  exit 7
}

if [[ "${JIEJING_USE_COST_SAVER_OVERRIDE:-false}" == "true" ]]; then
  cost_saver_override="${JIEJING_COST_SAVER_COMPOSE_OVERRIDE:-$private_dir/docker-compose.cost-saver-local.yml}"
  if [[ "$cost_saver_override" != "$private_dir/docker-compose.cost-saver-local.yml" ]] || \
    ! trusted_root_owned_path_chain_is_safe "$cost_saver_override"; then
    echo "REFUSE_UNTRUSTED_COST_SAVER_OVERRIDE=1" >&2
    exit 8
  fi
fi

run_runtime_env_guard() {
  local candidate_compose_path="$1"
  local runtime_compose_path="$2"
  local override_args=()
  if [[ -n "$cost_saver_override" ]]; then
    override_args+=(--compose-override "$cost_saver_override")
  fi
  if [[ ! -f "$candidate_compose_path" ]]; then
    echo "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1" >&2
    exit 9
  fi
  if ! sudo -n python3 "$TRUSTED_RUNTIME_ENV_GUARD" check \
    --compose "$candidate_compose_path" \
    --compose-runtime-path "$runtime_compose_path" \
    --managed-env "$private_dir/tencent-managed.env" \
    --secret-env "$private_dir/jiejing-saas.staging-oauth.env" \
    --postgres-env "$private_dir/postgres-localqueue.env" \
    --required-runtime-service jiejing-saas \
    --required-runtime-service jiejing-worker \
    "${override_args[@]}"; then
    echo "REFUSE_RUNTIME_ENV_OWNERSHIP_GUARD=1" >&2
    exit 9
  fi
  echo "RUNTIME_ENV_GUARD_STATUS=passed"
}

run_runtime_env_guard "$candidate_compose" "$runtime_compose"

mkdir -p "$BACKUP_DIR"
for rel in "${FILES[@]}"; do
  mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
  if [[ -f "$APP_DIR/$rel" ]]; then
    cp "$APP_DIR/$rel" "$BACKUP_DIR/$rel"
  fi
  install -D -m 0644 "$PATCH_DIR/$rel" "$APP_DIR/$rel"
done
for rel in "${PUBLIC_ASSET_RETIREMENTS[@]}"; do
  if [[ "$rel" == *".."* || "$rel" = /* ]]; then
    echo "Refusing unsafe retired asset path: $rel" >&2
    exit 5
  fi
  rm -f "$APP_DIR/$rel"
done

python3 -m py_compile \
  jiejing_saas/database_adapter.py \
  jiejing_saas/account_health.py \
  jiejing_saas/merchant_onboarding.py \
  jiejing_saas/backup_plan.py \
  jiejing_saas/cos_backup_probe.py \
  jiejing_saas/billing_checkout.py \
  jiejing_saas/billing_domestic.py \
  jiejing_saas/billing_operations_maintenance.py \
  jiejing_saas/billing_domain_cutover_rehearsal.py \
  jiejing_saas/billing_manual_beta.py \
  jiejing_saas/billing_payment_options.py \
  jiejing_saas/billing_plan.py \
  jiejing_saas/billing_provider_evidence_register.py \
  jiejing_saas/billing_provider_rehearsal.py \
  jiejing_saas/billing_test_provider.py \
  jiejing_saas/billing_webhook.py \
  jiejing_saas/billing_wechat_pay.py \
  jiejing_saas/ai_ceo_chat.py \
  jiejing_saas/commercial_launch_gate.py \
  jiejing_saas/controlled_bridges.py \
  jiejing_saas/domain_readiness.py \
  jiejing_saas/edge_cutover_preflight.py \
  jiejing_saas/queue_adapter.py \
  jiejing_saas/queue_plan.py \
  jiejing_saas/repository.py \
  jiejing_saas/product_feedback.py \
  jiejing_saas/monitoring.py \
  jiejing_saas/vault_secret_resolver.py \
  jiejing_saas/vault_adapter.py \
  jiejing_saas/infrastructure_drivers.py \
  jiejing_saas/operational_health.py \
  jiejing_saas/operations_metering.py \
  jiejing_saas/launch_progress.py \
  jiejing_saas/owner_launch_control.py \
  jiejing_saas/feasibility_review.py \
  jiejing_saas/platform_authorization_strategy.py \
  jiejing_saas/platform_registry.py \
  jiejing_saas/paid_launch_approval_packet.py \
  jiejing_saas/production_evidence_ledger.py \
  jiejing_saas/production_release_gate.py \
  jiejing_saas/post_publish_cockpit.py \
  jiejing_saas/media_asset_pipeline.py \
  jiejing_saas/media_credits.py \
  jiejing_saas/media_source_assets.py \
  jiejing_saas/provider_job_runner.py \
  jiejing_saas/provider_workflow_plan.py \
  jiejing_saas/model_provider_catalog.py \
  jiejing_saas/platform_model_status.py \
  jiejing_saas/model_value_gate.py \
  jiejing_saas/model_value_rehearsal.py \
  jiejing_saas/staging_security_gate.py \
  jiejing_saas/postgres_repository_runtime.py \
  jiejing_saas/redis_queue_runtime.py \
  jiejing_saas/ebay_data_packet.py \
  jiejing_saas/ebay_account_deletion.py \
  jiejing_saas/worker.py \
  jiejing_saas/api_server.py \
  jiejing_saas/registration_challenge.py \
  jiejing_saas/security.py \
  jiejing_saas/readiness.py \
  jiejing_saas/config.py \
  jiejing_saas/ebay_credential_preflight.py \
  jiejing_saas/ebay_http_client.py \
  jiejing_saas/ebay_token_refresh_adapter.py \
  jiejing_saas/ebay_read_normalizers.py \
  jiejing_saas/ebay_live_read_adapter.py \
  jiejing_saas/ebay_oauth.py \
  jiejing_saas/ebay_oauth_callback.py \
  jiejing_saas/ebay_write_adapter.py \
  jiejing_saas/workflow_plan.py \
  jiejing_runtime/execution_preflight.py \
  jiejing_runtime/__init__.py \
  jiejing_runtime/agent_provider_plan.py \
  jiejing_runtime/agent_team.py \
  jiejing_runtime/creative_capabilities.py \
  jiejing_runtime/media_capability_router.py \
  jiejing_runtime/media_generation.py \
  jiejing_runtime/model_clients.py \
  jiejing_runtime/owned_agents.py \
  jiejing_runtime/policies.py \
  jiejing_runtime/provider_job_contracts.py \
  jiejing_runtime/replacement_readiness.py \
  jiejing_runtime/adapters.py \
  tools/jiejing_sqlite_to_postgres_rehearsal.py \
  tools/jiejing_cost_saver_snapshot.py \
  tools/jiejing_infra_cutover_rehearsal.py \
    tools/jiejing_worker_cli.py \
    tools/jiejing_upsert_private_env_secret.py \
    tools/jiejing_wechat_pay_noncharge_acceptance.py \
    tools/jiejing_wechat_pay_live_acceptance.py \
    tools/jiejing_wechat_pay_acceptance_verify.py \
  tools/test_jiejing_sqlite_to_postgres_rehearsal.py \
  tools/test_jiejing_cost_saver_snapshot.py \
  tools/test_jiejing_infra_cutover_rehearsal.py \
  tools/test_jiejing_worker_cli_contract.py \
  tools/test_jiejing_domestic_billing_maintenance.py \
  tools/test_jiejing_ebay_account_deletion.py \
  tools/jiejing_infrastructure_stage_gate.py \
  tools/jiejing_deploy_channel_doctor.py \
  tools/jiejing_prepare_public_staging_bundle.py \
  tools/jiejing_staging_deploy.py \
  tools/jiejing_current_state_guard.py \
  tools/jiejing_external_launch_blocker_gate.py \
  tools/jiejing_configure_tencent_runtime_env.py \
  tools/jiejing_runtime_env_overlap_guard.py \
  tools/jiejing_cos_backup_probe.py \
  tools/jiejing_a_class_unattended_gate.py \
  tools/jiejing_b_class_production_gate.py \
  tools/jiejing_c_class_production_gate.py \
  tools/test_jiejing_deploy_channel_doctor.py \
  tools/test_jiejing_staging_deploy_channel_contract.py \
  tools/test_jiejing_staging_deploy_disk_guard.py \
  tools/test_jiejing_agents_md_guardrails.py \
  tools/test_jiejing_github_actions_deploy_guardrails.py \
  tools/test_jiejing_github_runner_doctor_guardrails.py \
  tools/jiejing_precloud_deployment_gate.py \
  tools/test_jiejing_current_state_guard.py \
  tools/test_jiejing_external_launch_blocker_gate.py \
  tools/test_jiejing_historical_ebay_readiness.py \
  tools/test_jiejing_configure_tencent_runtime_env.py \
  tools/test_jiejing_runtime_env_overlap_guard.py \
  tools/test_jiejing_runtime_env_public_contract.py \
  tools/test_jiejing_cos_backup_probe.py \
  tools/test_jiejing_frontend_staging_config.py \
  tools/test_jiejing_media_nav_and_state_restore.py \
  tools/test_jiejing_saas_clean_settings_and_listing_ui.py \
  tools/test_jiejing_product_feedback_closure.py \
  tools/test_jiejing_platform_operations_overview.py \
  tools/test_jiejing_public_staging_proxy_contract.py \
  tools/test_jiejing_saas_p0_security_guardrails.py \
  tools/test_jiejing_runtime_knowledge.py \
  tools/test_jiejing_runtime_mvp.py \
  tools/test_jiejing_staging_ebay_oauth_flow_tool.py \
  tools/test_jiejing_ebay_live_read_http_client.py \
  tools/test_jiejing_agent_model_assist.py \
  tools/jiejing_controlled_model_value_proof.py \
  tools/test_jiejing_controlled_model_value_proof.py \
  tools/test_jiejing_model_value_rehearsal.py \
  tools/test_jiejing_billing_provider_webhook.py \
  tools/test_jiejing_billing_test_provider.py \
  tools/test_jiejing_billing_webhook_subscription_state.py \
  tools/test_jiejing_mainland_payment_strategy.py \
  tools/test_jiejing_manual_beta_payment_flow.py \
  tools/test_jiejing_billing_provider_evidence_register.py \
  tools/test_jiejing_ebay_vault_token_refresh_adapter.py \
  tools/test_jiejing_domain_launch_gate.py \
  tools/test_jiejing_monitoring_runbook_gate.py \
  tools/test_jiejing_chinese_report_source.py \
  tools/test_jiejing_merchant_byok_model_and_memory.py \
  tools/test_jiejing_platform_model_readiness.py \
  tools/test_jiejing_ebay_refresh_secret_readiness.py \
  tools/test_jiejing_infrastructure_drivers.py \
  tools/test_jiejing_postgres_durable_queue_adapter.py \
  tools/test_jiejing_controlled_bridges.py \
  tools/test_jiejing_postgres_repository_cutover.py \
  tools/test_jiejing_redis_worker_cutover.py \
  tools/test_jiejing_vault_secret_resolver.py \
  tools/test_jiejing_tencent_cloud_integrations.py \
  tools/test_jiejing_managed_infra_readiness_cutover.py \
  tools/test_jiejing_saas_backend_mvp.py \
  tools/test_jiejing_ebay_write_adapter.py \
  tools/test_jiejing_publish_cleanup_plan.py \
  tools/jiejing_productization_stage_gate.py \
  tools/jiejing_secret_scan.py \
  tools/jiejing_new_ebay_account_low_risk_check.py \
  tools/jiejing_billing_provider_evidence_register.py \
  tools/jiejing_paid_launch_approval_packet.py \
  tools/jiejing_production_evidence_ledger.py \
  tools/jiejing_production_release_gate.py \
  tools/jiejing_domain_pending_purchase_preflight.py \
  tools/jiejing_registered_domain_cutover_status.py \
  tools/jiejing_edge_cutover_preflight.py \
  tools/test_jiejing_staging_patch_apply_contract.py \
  tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py \
  tools/test_jiejing_saas_ai_ceo_platform_model_fallback.py \
  tools/test_jiejing_operational_health_readiness.py \
  tools/test_jiejing_stripe_checkout_portal.py \
  tools/test_jiejing_queue_recovery_heartbeat.py \
  tools/test_jiejing_account_health_incident_mode.py \
  tools/test_jiejing_frontend_settings_module_split.py \
  tools/test_jiejing_media_asset_pipeline.py \
  tools/test_jiejing_media_asset_jobs.py \
  tools/test_jiejing_media_capability_router.py \
  tools/test_jiejing_platform_authorization_strategy.py \
  tools/test_jiejing_provider_job_contracts.py \
  tools/test_jiejing_agent_provider_plan.py \
  tools/test_jiejing_saas_provider_jobs.py \
  tools/test_jiejing_long_term_memory_and_creative.py \
  tools/test_jiejing_new_ebay_account_low_risk_runbook.py \
  tools/test_jiejing_paid_launch_approval_packet.py \
  tools/test_jiejing_production_evidence_ledger.py \
  tools/test_jiejing_production_release_gate.py \
  tools/test_jiejing_domain_pending_purchase_preflight.py \
  tools/test_jiejing_registered_domain_cutover_status.py \
  tools/test_jiejing_edge_cutover_preflight.py \
  tools/test_jiejing_expensive_api_rate_limit.py \
  tools/test_jiejing_platform_trial_activation_guard.py \
  tools/test_jiejing_registration_challenge_ui.py \
  tools/test_jiejing_ai_ceo_scroll_retention.py \
  tools/test_jiejing_ai_ceo_history_pagination.py \
  tools/test_jiejing_billing_quota_guardrail.py \
  tools/test_jiejing_session_revocation.py \
  tools/test_jiejing_public_anti_scrape_hardening.py \
  tools/test_jiejing_public_security_status_ui.py \
  tools/test_jiejing_saas_readable_decision_service_settings_ui.py \
  tools/test_jiejing_first_order_launch_loop_ui.py \
  tools/test_jiejing_publish_preflight_resolution_ui.py \
  tools/test_jiejing_owner_launch_control.py \
  tools/test_jiejing_owner_launch_control_access.py \
  tools/test_jiejing_owner_launch_control_ui.py \
  tools/test_jiejing_fixed_launch_progress.py \
  tools/test_jiejing_merchant_workflow_validation.py \
  tools/test_jiejing_version_bound_release_evidence.py

NODE_BIN="${JIEJING_NODE_BIN:-node}"
"$NODE_BIN" --check app.js
"$NODE_BIN" --check ops.js
"$NODE_BIN" --check tools/codex_jiejing_operations_console_smoke.js
"$NODE_BIN" --check tools/codex_jiejing_product_feedback_smoke.js

COMPOSE_FILE="deploy/docker-compose.public-https-staging.yml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  COMPOSE_FILE="deploy/docker-compose.public-staging.yml"
fi
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
if [[ -n "$cost_saver_override" ]]; then
  COMPOSE_ARGS+=(-f "$cost_saver_override")
fi

docker compose "${COMPOSE_ARGS[@]}" build --no-cache jiejing-saas jiejing-worker
if [[ "$COMPOSE_FILE" == "deploy/docker-compose.public-https-staging.yml" ]]; then
  docker volume inspect deploy_jiejing_public_staging_vault_data_v3 >/dev/null 2>&1 || \
    docker volume create deploy_jiejing_public_staging_vault_data_v3 >/dev/null
fi
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps jiejing-vault
if [[ -f "deploy/staging-vault-init-unseal.sh" ]]; then
  JIEJING_COMPOSE_FILE="$COMPOSE_FILE" \
  JIEJING_VAULT_PATCH_ENV=true \
  JIEJING_VAULT_ENV_FILE="$APP_DIR/../private/jiejing-saas.staging-oauth.env" \
    sh deploy/staging-vault-init-unseal.sh
fi
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps jiejing-saas
api_health_ready=false
for attempt in $(seq 1 15); do
  if docker compose "${COMPOSE_ARGS[@]}" exec -T jiejing-saas \
    python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=10).read().decode())" \
    >/tmp/jiejing-health.json 2>/tmp/jiejing-health.err; then
    api_health_ready=true
    break
  fi
  sleep 2
done
if [[ "$api_health_ready" != "true" ]]; then
  echo "Refusing to start the worker before the API health check passes." >&2
  tail -c 1000 /tmp/jiejing-health.err >&2 || true
  exit 6
fi
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps jiejing-worker
docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-frontend
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet caddy; then
  sudo -n install -m 0644 deploy/Caddyfile.public-staging.systemd /etc/caddy/Caddyfile
  if command -v caddy >/dev/null 2>&1; then
    sudo -n caddy validate --config /etc/caddy/Caddyfile
  fi
  sudo -n systemctl reload caddy
else
  docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --force-recreate jiejing-edge
fi

echo "PATCH_APPLIED=1"
echo "BACKUP_DIR=$BACKUP_DIR"
echo "COMPOSE_FILE=$COMPOSE_FILE"
echo "COMPOSE_FILES=${COMPOSE_ARGS[*]}"
cat /tmp/jiejing-health.json
