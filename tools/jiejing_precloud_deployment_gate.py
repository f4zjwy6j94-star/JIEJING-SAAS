#!/usr/bin/env python3
"""Pre-cloud deployment gate for Jiejing SaaS.

This local regression gate binds its checks to one clean source candidate.
It does not prove current production health, commercial readiness, or permission
to repeat OAuth, payments, refunds, or platform writes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from jiejing_release_gate_evidence import build_gate_evidence, capture_source_state, utc_now
except ModuleNotFoundError:
    from tools.jiejing_release_gate_evidence import build_gate_evidence, capture_source_state, utc_now


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-precloud-deployment-gate"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


CHECKS: list[tuple[str, list[str]]] = [
    ("frontend_js_syntax", ["node", "--check", "app.js"]),
    ("operations_console_js_syntax", ["node", "--check", "ops.js"]),
    ("current_state_guard", [sys.executable, "tools/test_jiejing_current_state_guard.py"]),
    (
        "phase2_response_boundary_hardening",
        [sys.executable, "tools/test_jiejing_phase2_response_boundary_hardening.py"],
    ),
    ("frontend_staging_config", [sys.executable, "tools/test_jiejing_frontend_staging_config.py"]),
    ("workbench_contract_freeze", [sys.executable, "tools/test_jiejing_workbench_contract_freeze.py"]),
    ("workflow_closure_ui", [sys.executable, "tools/test_jiejing_workflow_closure_ui.py"]),
    ("frontend_wechat_zero_charge_rehearsal", [sys.executable, "tools/test_jiejing_frontend_wechat_zero_charge_rehearsal.py"]),
    ("frontend_read_only_oauth_confirmation", [sys.executable, "tools/test_jiejing_frontend_oauth_confirmation_flow.py"]),
    ("ebay_current_store_refresh_proof", [sys.executable, "tools/test_jiejing_ebay_refresh_proof_ui.py"]),
    ("frontend_unpublished_draft_oauth", [sys.executable, "tools/test_jiejing_frontend_unpublished_draft_oauth.py"]),
    ("frontend_ebay_inventory_location", [sys.executable, "tools/test_jiejing_frontend_ebay_inventory_location.py"]),
    ("browser_read_only_oauth_confirmation", ["node", "tools/codex_jiejing_oauth_confirmation_flow_smoke.js"]),
    ("browser_unpublished_draft_oauth", ["node", "tools/codex_jiejing_unpublished_draft_oauth_smoke.js"]),
    ("browser_ebay_inventory_location", ["node", "tools/codex_jiejing_ebay_inventory_location_smoke.js"]),
    ("product_feedback_browser_smoke", ["node", "tools/codex_jiejing_product_feedback_smoke.js"]),
    ("frontend_settings_lazy_load", [sys.executable, "tools/test_jiejing_frontend_settings_module_split.py"]),
    ("frontend_performance_analytics", [sys.executable, "tools/test_jiejing_frontend_performance_analytics.py"]),
    ("merchant_surface_guard", [sys.executable, "tools/test_jiejing_merchant_surface_guard.py"]),
    ("merchant_surface_isolation", [sys.executable, "tools/test_jiejing_merchant_surface_isolation.py"]),
    ("core_workflow_maturity", [sys.executable, "tools/test_jiejing_core_workflow_maturity.py"]),
    ("homepage_maturity", [sys.executable, "tools/test_jiejing_homepage_maturity.py"]),
    ("public_design_release", [sys.executable, "tools/test_jiejing_public_design_release.py"]),
    ("workbench_finish", [sys.executable, "tools/test_jiejing_workbench_finish.py"]),
    ("browser_workbench_finish", ["node", "tools/codex_jiejing_workbench_finish_browser_smoke.js"]),
    ("browser_homepage_maturity", ["node", "tools/codex_jiejing_homepage_maturity_browser_smoke.js"]),
    ("production_empty_state", [sys.executable, "tools/test_jiejing_production_empty_state.py"]),
    ("merchant_role_labels", [sys.executable, "tools/test_jiejing_merchant_role_labels.py"]),
    ("merchant_source_paths_copy", [sys.executable, "tools/test_jiejing_merchant_source_paths_copy.py"]),
    ("merchant_pricing_media_copy", [sys.executable, "tools/test_jiejing_merchant_pricing_media_copy.py"]),
    ("clean_settings_and_listing_ui", [sys.executable, "tools/test_jiejing_saas_clean_settings_and_listing_ui.py"]),
    ("settings_account_workspace_ui", [sys.executable, "tools/test_jiejing_settings_account_workspace_ui.py"]),
    ("ai_ceo_copy_fidelity", [sys.executable, "tools/test_jiejing_ai_ceo_copy_fidelity.py"]),
    ("merchant_copy_maturity", [sys.executable, "tools/test_jiejing_merchant_copy_maturity.py"]),
    ("workbench_boot_efficiency", [sys.executable, "tools/test_jiejing_workbench_boot_efficiency.py"]),
    ("workbench_subscription_entry", [sys.executable, "tools/test_jiejing_workbench_subscription_entry.py"]),
    ("product_grade_journey_contract", [sys.executable, "tools/test_jiejing_product_grade_journey_contract.py"]),
    (
        "product_grade_journey_session_cookie",
        [sys.executable, "tools/test_jiejing_product_grade_journey_session_cookie.py"],
    ),
    ("ai_ceo_browser_streaming", [sys.executable, "tools/test_jiejing_ai_ceo_browser_streaming_contract.py"]),
    ("model_streaming_client", [sys.executable, "tools/test_jiejing_model_streaming_client.py"]),
    ("ai_ceo_private_empty_answer", [sys.executable, "tools/test_jiejing_ai_ceo_private_empty_answer.py"]),
    ("ai_ceo_private_answer_capture", [sys.executable, "tools/test_jiejing_ai_ceo_private_answer_capture.py"]),
    ("ai_ceo_product_search_evidence", [sys.executable, "tools/test_jiejing_ai_ceo_product_search_evidence.py"]),
    ("ai_ceo_source_quality", [sys.executable, "tools/test_jiejing_ai_ceo_source_quality.py"]),
    ("public_search_temporal_metadata", [sys.executable, "tools/test_jiejing_public_search_temporal_metadata.py"]),
    ("market_quote_evidence", [sys.executable, "tools/test_jiejing_market_quote_evidence.py"]),
    ("ai_ceo_market_quote_boundary", [sys.executable, "tools/test_jiejing_ai_ceo_market_quote_boundary.py"]),
    ("ai_ceo_timely_evidence", [sys.executable, "tools/test_jiejing_ai_ceo_timely_evidence.py"]),
    ("ai_ceo_answer_rendering", [sys.executable, "tools/test_jiejing_ai_ceo_answer_rendering.py"]),
    ("ai_ceo_answer_quality_gate", [sys.executable, "tools/test_jiejing_ai_ceo_answer_quality_gate.py"]),
    ("ai_ceo_project_trace", [sys.executable, "tools/test_jiejing_ai_ceo_project_trace.py"]),
    ("current_project_archive_ui", [sys.executable, "tools/test_jiejing_current_project_archive_ui.py"]),
    ("ai_ceo_open_domain_turn_plan", [sys.executable, "tools/test_jiejing_ai_ceo_open_domain_turn_plan.py"]),
    ("ai_ceo_semantic_dispatch", [sys.executable, "tools/test_jiejing_ai_ceo_semantic_dispatch.py"]),
    ("ai_ceo_semantic_chat", [sys.executable, "tools/test_jiejing_ai_ceo_semantic_chat.py"]),
    ("ai_ceo_semantic_http", [sys.executable, "tools/test_jiejing_ai_ceo_semantic_http.py"]),
    ("ai_ceo_semantic_dispatch_frontend", ["node", "tools/test_jiejing_ai_ceo_semantic_dispatch_frontend.js"]),
    ("ai_ceo_bound_product_navigation", ["node", "tools/test_jiejing_ai_ceo_bound_product_navigation.js"]),
    ("ai_ceo_command_text_fidelity", ["node", "tools/test_jiejing_ai_ceo_command_text_fidelity.js"]),
    ("ai_ceo_simulation_request", [sys.executable, "tools/test_jiejing_ai_ceo_simulation_request.py"]),
    ("ai_ceo_simulation_request_http", [sys.executable, "tools/test_jiejing_ai_ceo_simulation_request_http.py"]),
    ("ai_ceo_frontend_intent", ["node", "tools/test_jiejing_ai_ceo_frontend_intent.js"]),
    ("ai_ceo_frontend_stream_error", ["node", "tools/test_jiejing_ai_ceo_frontend_stream_error.js"]),
    ("ai_ceo_platform_model_fallback", [sys.executable, "tools/test_jiejing_saas_ai_ceo_platform_model_fallback.py"]),
    ("ai_ceo_chat_model_boundary", [sys.executable, "tools/test_jiejing_saas_ai_ceo_chat_model_boundary.py"]),
    ("ai_ceo_latest_reply_ui", [sys.executable, "tools/test_jiejing_saas_ai_ceo_latest_reply_ui.py"]),
    ("ai_ceo_product_image_intake", [sys.executable, "tools/test_jiejing_ai_ceo_product_image_intake.py"]),
    ("ai_ceo_routing_supplier_http", [sys.executable, "tools/test_jiejing_ai_ceo_routing_supplier_http_red.py"]),
    ("ai_ceo_phase0_contracts", [sys.executable, "tools/test_jiejing_ai_ceo_phase0_red_contracts.py"]),
    ("ai_ceo_listing_fact_boundary", [sys.executable, "tools/test_jiejing_ai_ceo_listing_fact_boundary.py"]),
    ("supplier_intake_rehearsal", [sys.executable, "tools/test_jiejing_supplier_intake_rehearsal.py"]),
    ("listing_publish_prefill_truth", ["node", "--test", "tools/test_jiejing_listing_publish_prefill_truth.js"]),
    ("listing_media_writeback_persistence", ["node", "--test", "tools/test_jiejing_listing_media_writeback_persistence.js"]),
    ("unpublished_draft_receipt_ui", [sys.executable, "tools/test_jiejing_unpublished_draft_receipt_ui.py"]),
    ("activity_execution_records_ui", [sys.executable, "tools/test_jiejing_activity_execution_records_ui.py"]),
    ("ai_ceo_listing_buyer_copy_boundary", [sys.executable, "tools/test_jiejing_ai_ceo_listing_buyer_copy_boundary.py"]),
    ("listing_draft_generation", [sys.executable, "tools/test_jiejing_listing_draft_generation.py"]),
    ("listing_buyer_copy_rewrite", [sys.executable, "tools/test_jiejing_listing_buyer_copy_rewrite.py"]),
    ("listing_buyer_copy_rewrite_api", [sys.executable, "tools/test_jiejing_listing_buyer_copy_rewrite_api.py"]),
    ("listing_generation_operations", [sys.executable, "tools/test_jiejing_listing_generation_operations.py"]),
    ("listing_generation_legacy_recovery", [sys.executable, "tools/test_jiejing_listing_generation_legacy_recovery.py"]),
    ("listing_draft_buyer_copy_quality", [sys.executable, "tools/test_jiejing_listing_draft_buyer_copy_quality.py"]),
    ("listing_grounding_security", [sys.executable, "tools/test_jiejing_listing_grounding_security.py"]),
    ("listing_draft_generation_api", [sys.executable, "tools/test_jiejing_listing_draft_generation_api.py"]),
    ("listing_draft_checkpoint_api", [sys.executable, "tools/test_jiejing_listing_draft_checkpoint_api.py"]),
    ("product_fact_auth_http", [sys.executable, "tools/test_jiejing_product_fact_auth_http.py"]),
    ("listing_platform_trial_quota", [sys.executable, "tools/test_jiejing_listing_platform_trial_quota.py"]),
    (
        "listing_platform_trial_concurrency",
        [sys.executable, "tools/test_jiejing_listing_platform_trial_concurrency.py"],
    ),
    (
        "platform_trial_reservation_lifecycle",
        [sys.executable, "tools/test_jiejing_platform_trial_reservation_lifecycle.py"],
    ),
    ("platform_trial_window", [sys.executable, "tools/test_jiejing_platform_trial_window.py"]),
    ("model_connection_save_contract", [sys.executable, "tools/test_jiejing_model_connection_save_contract.py"]),
    ("postgres_schema_contract", [sys.executable, "tools/test_jiejing_postgres_schema_contract.py"]),
    ("listing_ai_generation_browser", ["node", "tools/codex_jiejing_listing_ai_generation_browser_smoke.js"]),
    ("listing_backend_restore_browser", ["node", "tools/test_jiejing_listing_backend_restore.js"]),
    ("listing_cloud_checkpoint_frontend", ["node", "tools/test_jiejing_listing_cloud_checkpoint_frontend.js"]),
    ("listing_buyer_copy_rewrite_frontend", ["node", "--test", "tools/test_jiejing_listing_buyer_copy_rewrite_frontend.js"]),
    ("listing_session_expiry_recovery", ["node", "--test", "tools/test_jiejing_listing_session_expiry_recovery.js"]),
    ("auth_reveal_boundary", ["node", "--test", "tools/test_jiejing_auth_reveal_boundary.js"]),
    ("recent_product_tasks_browser", ["node", "tools/test_jiejing_recent_product_tasks.js"]),
    ("listing_product_fact_confirmation_ui", ["node", "tools/test_jiejing_listing_product_fact_confirmation_ui.js"]),
    ("listing_confirmation_display_scope", ["node", "tools/test_jiejing_listing_confirmation_display_scope.js"]),
    ("merchant_content_workspace", ["node", "--test", "tools/test_jiejing_merchant_content_workspace.js"]),
    ("media_result_hierarchy", ["node", "tools/test_jiejing_media_result_hierarchy.js"]),
    ("media_project_source_entry", ["node", "tools/test_jiejing_media_project_source_entry.js"]),
    ("media_review_session_preflight", ["node", "tools/test_jiejing_media_review_session_preflight.js"]),
    ("listing_concrete_product_gate", [sys.executable, "tools/test_jiejing_listing_concrete_product_gate.py"]),
    ("ai_ceo_product_label_extraction", [sys.executable, "tools/test_jiejing_ai_ceo_product_label_extraction.py"]),
    ("ai_ceo_candidate_fact_consistency", [sys.executable, "tools/test_jiejing_ai_ceo_frontend_candidate_consistency.py"]),
    ("ai_ceo_listing_import_target", [sys.executable, "tools/test_jiejing_ai_ceo_listing_import_target.py"]),
    ("ai_settings_tenant_scope", [sys.executable, "tools/test_jiejing_ai_settings_tenant_scope.py"]),
    ("listing_progressive_disclosure", [sys.executable, "tools/test_jiejing_listing_progressive_disclosure.py"]),
    ("listing_single_progress", [sys.executable, "tools/test_jiejing_listing_single_progress.py"]),
    ("listing_wizard_frontend", ["node", "--test", "tools/test_jiejing_listing_wizard_frontend.js"]),
    ("browser_listing_wizard", ["node", "tools/codex_jiejing_listing_wizard_browser_smoke.js"]),
    ("product_progress_clarity", [sys.executable, "tools/test_jiejing_product_progress_clarity.py"]),
    ("ebay_write_adapter", [sys.executable, "tools/test_jiejing_ebay_write_adapter.py"]),
    ("merchant_project_status_browser", ["node", "tools/codex_jiejing_merchant_project_status_browser_smoke.js"]),
    ("media_version_rework_ui", [sys.executable, "tools/test_jiejing_media_version_rework_ui.py"]),
    ("media_quality_control", [sys.executable, "tools/test_jiejing_media_quality_control.py"]),
    ("media_live_provider_gate", [sys.executable, "tools/test_jiejing_media_live_provider_gate.py"]),
    ("media_openai_adapter", [sys.executable, "tools/test_jiejing_media_openai_adapter.py"]),
    ("media_placeholder_review_gate", [sys.executable, "tools/test_jiejing_media_placeholder_review_gate.py"]),
    ("media_asset_jobs", [sys.executable, "tools/test_jiejing_media_asset_jobs.py"]),
    ("media_controlled_acceptance", [sys.executable, "tools/test_jiejing_media_controlled_acceptance_red.py"]),
    ("owner_media_testing", [sys.executable, "tools/test_jiejing_owner_media_testing.py"]),
    ("media_queue_setup_recovery", [sys.executable, "tools/test_jiejing_media_queue_setup_recovery.py"]),
    ("media_source_assets", [sys.executable, "tools/test_jiejing_media_source_assets.py"]),
    ("media_source_upload_http", [sys.executable, "tools/test_jiejing_media_source_upload_http.py"]),
    ("media_source_grounding_gate", [sys.executable, "tools/test_jiejing_media_source_grounding_gate.py"]),
    ("ai_ceo_cross_device_history", [sys.executable, "tools/test_jiejing_ai_ceo_cross_device_history.py"]),
    ("ai_ceo_scroll_retention", [sys.executable, "tools/test_jiejing_ai_ceo_scroll_retention.py"]),
    ("ai_ceo_history_pagination", [sys.executable, "tools/test_jiejing_ai_ceo_history_pagination.py"]),
    ("ai_ceo_history_pagination_browser", ["node", "tools/codex_jiejing_ai_ceo_history_pagination_browser_smoke.js"]),
    ("ai_ceo_cross_device_refresh", [sys.executable, "tools/test_jiejing_ai_ceo_cross_device_refresh_contract.py"]),
    ("bulk_partial_success", [sys.executable, "tools/test_jiejing_bulk_partial_success_contract.py"]),
    ("bulk_candidate_lane", [sys.executable, "tools/test_jiejing_bulk_candidate_lane.py"]),
    ("external_launch_blocker_gate", [sys.executable, "tools/test_jiejing_external_launch_blocker_gate.py"]),
    ("historical_ebay_readiness", [sys.executable, "tools/test_jiejing_historical_ebay_readiness.py"]),
    ("readiness_incident_ui", [sys.executable, "tools/test_jiejing_readiness_incident_ui.py"]),
    ("first_day_account_smoke", [sys.executable, "tools/test_jiejing_first_day_account_smoke.py"]),
    ("merchant_onboarding_state", [sys.executable, "tools/test_jiejing_merchant_onboarding_state.py"]),
    ("merchant_onboarding_frontend", [sys.executable, "tools/test_jiejing_merchant_onboarding_frontend.py"]),
    ("account_health_incident_mode", [sys.executable, "tools/test_jiejing_account_health_incident_mode.py"]),
    ("account_health_preflight", [sys.executable, "tools/test_jiejing_account_health_preflight.py"]),
    (
        "provider_restriction_resolution_http",
        [sys.executable, "tools/test_jiejing_provider_restriction_resolution_http.py"],
    ),
    ("oauth_staging_deploy_contract", [sys.executable, "tools/test_jiejing_oauth_staging_deploy_contract.py"]),
    ("public_staging_proxy_contract", [sys.executable, "tools/test_jiejing_public_staging_proxy_contract.py"]),
    ("staging_oauth_operator_flow_tool", [sys.executable, "tools/test_jiejing_staging_ebay_oauth_flow_tool.py"]),
    ("p0_security_guardrails", [sys.executable, "tools/test_jiejing_saas_p0_security_guardrails.py"]),
    ("global_security_hardening", [sys.executable, "tools/test_jiejing_global_security_hardening.py"]),
    ("shared_expensive_api_rate_limit", [sys.executable, "tools/test_jiejing_expensive_api_rate_limit.py"]),
    ("platform_trial_activation_guard", [sys.executable, "tools/test_jiejing_platform_trial_activation_guard.py"]),
    ("registration_challenge_ui", [sys.executable, "tools/test_jiejing_registration_challenge_ui.py"]),
    ("billing_quota_guardrail", [sys.executable, "tools/test_jiejing_billing_quota_guardrail.py"]),
    ("team_seat_quota", [sys.executable, "tools/test_jiejing_team_seat_quota.py"]),
    ("commercial_entitlements", [sys.executable, "tools/test_jiejing_commercial_entitlements.py"]),
    ("media_credit_purchase", [sys.executable, "tools/test_jiejing_media_credit_purchase.py"]),
    ("merchant_media_usage", [sys.executable, "tools/test_jiejing_merchant_media_usage.py"]),
    ("billing_entitlement_projection", [sys.executable, "tools/test_jiejing_billing_entitlement_projection.py"]),
    ("operations_metering", [sys.executable, "tools/test_jiejing_operations_metering.py"]),
    ("platform_operations_overview", [sys.executable, "tools/test_jiejing_platform_operations_overview.py"]),
    ("operations_console", [sys.executable, "tools/test_jiejing_operations_console.py"]),
    ("browser_operations_console", ["node", "tools/codex_jiejing_operations_console_smoke.js"]),
    ("product_feedback_closure", [sys.executable, "tools/test_jiejing_product_feedback_closure.py"]),
    ("reliability_alert_api", [sys.executable, "tools/test_jiejing_reliability_alert_api.py"]),
    ("domestic_billing_api", [sys.executable, "tools/test_jiejing_domestic_billing_api.py"]),
    ("stripe_checkout_portal", [sys.executable, "tools/test_jiejing_stripe_checkout_portal.py"]),
    ("domestic_billing_orders", [sys.executable, "tools/test_jiejing_domestic_billing_orders.py"]),
    ("domestic_billing_refund", [sys.executable, "tools/test_jiejing_domestic_billing_refund.py"]),
    ("refund_operator_authorization", [sys.executable, "tools/test_jiejing_refund_operator_authorization.py"]),
    ("domestic_billing_refund_browser", [sys.executable, "tools/test_jiejing_domestic_billing_refund_browser.py"]),
    ("domestic_billing_production_completion", [sys.executable, "tools/test_jiejing_domestic_billing_production_completion.py"]),
    ("domestic_billing_merchant_ui", [sys.executable, "tools/test_jiejing_domestic_billing_merchant_ui.py"]),
    ("domestic_billing_operations", [sys.executable, "tools/test_jiejing_domestic_billing_operations.py"]),
    ("domestic_billing_maintenance", [sys.executable, "tools/test_jiejing_domestic_billing_maintenance.py"]),
    ("wechat_pay_callback", [sys.executable, "tools/test_jiejing_wechat_pay_callback.py"]),
    ("wechat_pay_refund_provider", [sys.executable, "tools/test_jiejing_wechat_pay_refund_provider.py"]),
    ("wechat_pay_recovery", [sys.executable, "tools/test_jiejing_wechat_pay_recovery.py"]),
    ("wechat_pay_live_client", [sys.executable, "tools/test_jiejing_wechat_pay_live_client.py"]),
    ("wechat_pay_checkout_flow", [sys.executable, "tools/test_jiejing_wechat_pay_checkout_flow.py"]),
    ("wechat_pay_live_acceptance", [sys.executable, "tools/test_jiejing_wechat_pay_live_acceptance.py"]),
    ("wechat_pay_acceptance_verify", [sys.executable, "tools/test_jiejing_wechat_pay_acceptance_verify.py"]),
    ("wechat_pay_zero_charge_rehearsal", [sys.executable, "tools/test_jiejing_wechat_pay_zero_charge_rehearsal.py"]),
    ("wechat_pay_zero_charge_rehearsal_http", [sys.executable, "tools/test_jiejing_wechat_pay_zero_charge_rehearsal_http.py"]),
    ("session_revocation", [sys.executable, "tools/test_jiejing_session_revocation.py"]),
    ("rotating_browser_sessions", [sys.executable, "tools/test_jiejing_rotating_browser_sessions.py"]),
    ("rotating_browser_session_http", [sys.executable, "tools/test_jiejing_rotating_browser_session_http.py"]),
    ("frontend_rotating_browser_sessions", [sys.executable, "tools/test_jiejing_frontend_rotating_browser_sessions.py"]),
    ("browser_rotating_browser_sessions", ["node", "tools/codex_jiejing_rotating_browser_session_smoke.js"]),
    ("browser_ai_ceo_frontend_resilience", ["node", "tools/codex_jiejing_ai_ceo_frontend_resilience_smoke.js"]),
    ("session_restore_and_ebay_ops_ui", [sys.executable, "tools/test_jiejing_session_restore_and_ebay_ops_ui.py"]),
    ("monitoring_runbook_gate", [sys.executable, "tools/test_jiejing_monitoring_runbook_gate.py"]),
    ("oauth_callback_vault", [sys.executable, "tools/test_jiejing_ebay_oauth_callback_vault.py"]),
    ("ebay_account_deletion", [sys.executable, "tools/test_jiejing_ebay_account_deletion.py"]),
    ("oauth_callback_postgres_datetime", [sys.executable, "tools/test_jiejing_ebay_oauth_callback_postgres_datetime.py"]),
    ("ebay_unpublished_draft_oauth", [sys.executable, "tools/test_jiejing_ebay_unpublished_draft_oauth.py"]),
    ("controlled_existing_draft_publish", [sys.executable, "tools/test_jiejing_controlled_existing_draft_publish.py"]),
    ("controlled_existing_draft_publish_http", [sys.executable, "tools/test_jiejing_controlled_existing_draft_publish_http.py"]),
    ("ebay_inventory_location_confirmation", [sys.executable, "tools/test_jiejing_ebay_inventory_location_confirmation.py"]),
    ("unpublished_draft_claim_capability", [sys.executable, "tools/test_jiejing_unpublished_draft_claim_capability.py"]),
    ("ebay_draft_save_readiness", [sys.executable, "tools/test_jiejing_ebay_draft_save_readiness.py"]),
    ("new_ebay_account_publish_http_chain", [sys.executable, "tools/test_jiejing_new_ebay_account_publish_http_chain.py"]),
    ("new_ebay_account_low_risk_runbook", [sys.executable, "tools/test_jiejing_new_ebay_account_low_risk_runbook.py"]),
    ("postgres_oauth_datetime_contract", [sys.executable, "tools/test_jiejing_postgres_oauth_datetime_contract.py"]),
    ("vault_secret_resolver", [sys.executable, "tools/test_jiejing_vault_secret_resolver.py"]),
    ("ebay_credential_preflight", [sys.executable, "tools/test_jiejing_ebay_credential_preflight.py"]),
    ("ebay_live_read_http_client", [sys.executable, "tools/test_jiejing_ebay_live_read_http_client.py"]),
    ("execution_draft_boundary", [sys.executable, "tools/test_jiejing_execution_draft_boundary.py"]),
    ("ebay_draft_save_adapter", [sys.executable, "tools/test_jiejing_ebay_draft_save_adapter.py"]),
    ("ebay_inventory_location_adapter", [sys.executable, "tools/test_jiejing_ebay_inventory_location_adapter.py"]),
    ("synthetic_ebay_identity_retirement", [sys.executable, "tools/test_jiejing_synthetic_ebay_identity_retirement.py"]),
    ("publish_confirmation_intake", [sys.executable, "tools/test_jiejing_publish_confirmation_intake.py"]),
    ("publish_source_rights_evidence", [sys.executable, "tools/test_jiejing_publish_source_rights_evidence.py"]),
    ("publish_evidence_preflight", [sys.executable, "tools/test_jiejing_publish_evidence_preflight.py"]),
    ("publish_intake_evidence_refs", [sys.executable, "tools/test_jiejing_publish_intake_evidence_refs.py"]),
    ("publish_claim_prewrite_abort", [sys.executable, "tools/test_jiejing_publish_claim_prewrite_abort.py"]),
    ("manual_source_new_project_reset", [sys.executable, "tools/test_jiejing_manual_source_new_project_reset.py"]),
    ("saas_backend_mvp", [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"]),
    ("operational_health_readiness", [sys.executable, "tools/test_jiejing_operational_health_readiness.py"]),
    ("queue_recovery_heartbeat", [sys.executable, "tools/test_jiejing_queue_recovery_heartbeat.py"]),
    ("postgres_durable_queue_adapter", [sys.executable, "tools/test_jiejing_postgres_durable_queue_adapter.py"]),
    ("infrastructure_drivers", [sys.executable, "tools/test_jiejing_infrastructure_drivers.py"]),
    ("managed_infra_readiness_cutover", [sys.executable, "tools/test_jiejing_managed_infra_readiness_cutover.py"]),
    ("tencent_cloud_integrations", [sys.executable, "tools/test_jiejing_tencent_cloud_integrations.py"]),
    ("tencent_runtime_env", [sys.executable, "tools/test_jiejing_configure_tencent_runtime_env.py"]),
    ("postgres_repository_cutover", [sys.executable, "tools/test_jiejing_postgres_repository_cutover.py"]),
    ("redis_worker_cutover", [sys.executable, "tools/test_jiejing_redis_worker_cutover.py"]),
    ("worker_cli_contract", [sys.executable, "tools/test_jiejing_worker_cli_contract.py"]),
    ("agent_model_assist", [sys.executable, "tools/test_jiejing_agent_model_assist.py"]),
    ("infra_cutover_rehearsal", [sys.executable, "tools/test_jiejing_infra_cutover_rehearsal.py"]),
    ("sqlite_to_postgres_rehearsal", [sys.executable, "tools/test_jiejing_sqlite_to_postgres_rehearsal.py"]),
    ("infrastructure_stage_gate", [sys.executable, "tools/jiejing_infrastructure_stage_gate.py"]),
    ("deploy_channel_doctor_parser", [sys.executable, "tools/test_jiejing_deploy_channel_doctor.py"]),
    ("staging_deploy_channel_contract", [sys.executable, "tools/test_jiejing_staging_deploy_channel_contract.py"]),
    ("production_deploy_channel_contract", [sys.executable, "tools/test_jiejing_production_deploy_channel.py"]),
    ("production_ops_consolidation_contract", [sys.executable, "tools/test_jiejing_production_ops_consolidation.py"]),
    ("staging_deploy_disk_guard", [sys.executable, "tools/test_jiejing_staging_deploy_disk_guard.py"]),
    ("staging_patch_apply_contract", [sys.executable, "tools/test_jiejing_staging_patch_apply_contract.py"]),
    ("runtime_env_overlap_guard", [sys.executable, "tools/test_jiejing_runtime_env_overlap_guard.py"]),
    ("runtime_env_public_contract", [sys.executable, "tools/test_jiejing_runtime_env_public_contract.py"]),
    ("agents_md_guardrails", [sys.executable, "tools/test_jiejing_agents_md_guardrails.py"]),
    ("secret_scan", [sys.executable, "tools/jiejing_secret_scan.py"]),
    ("github_actions_deploy_guardrails", [sys.executable, "tools/test_jiejing_github_actions_deploy_guardrails.py"]),
    ("cls_probe_auto_refresh_guardrails", [sys.executable, "tools/test_jiejing_cls_probe_auto_refresh_guardrails.py"]),
    (
        "production_evidence_auto_refresh_guardrails",
        [sys.executable, "tools/test_jiejing_production_evidence_auto_refresh_guardrails.py"],
    ),
    ("runtime_evidence_snapshot", [sys.executable, "tools/test_jiejing_runtime_evidence.py"]),
    ("controlled_media_proof_workflow", [sys.executable, "tools/test_jiejing_controlled_media_proof_workflow.py"]),
    ("github_runner_doctor_guardrails", [sys.executable, "tools/test_jiejing_github_runner_doctor_guardrails.py"]),
    ("github_runner_maintenance_guardrails", [sys.executable, "tools/test_jiejing_github_runner_maintenance_guardrails.py"]),
    ("local_first_cloud_fallback_guardrails", [sys.executable, "tools/test_jiejing_local_first_cloud_fallback_guardrails.py"]),
    ("mainland_payment_strategy", [sys.executable, "tools/test_jiejing_mainland_payment_strategy.py"]),
    (
        "wechat_pay_provider_connection_proof",
        [sys.executable, "tools/test_jiejing_wechat_pay_provider_connection_proof.py"],
    ),
    ("manual_beta_payment_flow", [sys.executable, "tools/test_jiejing_manual_beta_payment_flow.py"]),
    ("billing_provider_rehearsal", [sys.executable, "tools/test_jiejing_billing_provider_rehearsal.py"]),
    ("billing_provider_evidence_register", [sys.executable, "tools/test_jiejing_billing_provider_evidence_register.py"]),
    ("cos_backup_probe", [sys.executable, "tools/test_jiejing_cos_backup_probe.py"]),
    ("production_release_gate", [sys.executable, "tools/test_jiejing_production_release_gate.py"]),
    ("production_pilot_contract", [sys.executable, "tools/test_jiejing_production_pilot_contract.py"]),
    (
        "vault_sealed_paper_ceremony_contract",
        [sys.executable, "tools/test_jiejing_vault_sealed_paper_ceremony.py"],
    ),
    ("vault_recovery_drill", [sys.executable, "tools/test_jiejing_vault_recovery_drill.py"]),
    (
        "vault_production_grade_rehearsal_contract",
        [sys.executable, "tools/test_jiejing_vault_production_grade_rehearsal.py"],
    ),
    ("production_evidence_ledger", [sys.executable, "tools/test_jiejing_production_evidence_ledger.py"]),
    ("fixed_launch_progress", [sys.executable, "tools/test_jiejing_fixed_launch_progress.py"]),
    ("merchant_workflow_validation", [sys.executable, "tools/test_jiejing_merchant_workflow_validation.py"]),
    ("version_bound_release_evidence", [sys.executable, "tools/test_jiejing_version_bound_release_evidence.py"]),
    ("source_bound_release_gate_evidence", [sys.executable, "tools/test_jiejing_release_gate_evidence.py"]),
    ("workflow_entry_feedback", ["node", "tools/test_jiejing_workflow_entry_feedback.js"]),
    ("workbench_boot_recovery", ["node", "--test", "tools/test_jiejing_workbench_boot_recovery.js"]),
    ("owner_launch_control", [sys.executable, "tools/test_jiejing_owner_launch_control.py"]),
    ("owner_launch_control_access", [sys.executable, "tools/test_jiejing_owner_launch_control_access.py"]),
    ("billing_provider_webhook", [sys.executable, "tools/test_jiejing_billing_provider_webhook.py"]),
    ("billing_webhook_subscription_state", [sys.executable, "tools/test_jiejing_billing_webhook_subscription_state.py"]),
    ("jiejing_owned_credential_chain", [sys.executable, "tools/jiejing_ebay_jiejing_credential_chain_smoke.py"]),
    ("productization_stage_gate", [sys.executable, "tools/jiejing_productization_stage_gate.py"]),
]


def main() -> int:
    started = time.time()
    started_at = utc_now()
    source_before = capture_source_state(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    results = [_run_check(key, command) for key, command in CHECKS]
    source_after = capture_source_state(ROOT)
    evidence = build_gate_evidence(CHECKS, results, source_before, source_after, started_at, utc_now(), ROOT)
    docker_path = shutil.which("docker")
    local_pass = evidence["checks_passed"]
    external_blockers = []
    if not docker_path:
        external_blockers.append("docker_cli_not_available_on_this_machine")
    staging_verification = _latest_staging_verification()
    summary: dict[str, Any] = {
        "product": "Jiejing SaaS",
        "gate": "precloud_deployment_gate",
        "status": "pass_local_checks" if local_pass else "failed_local_checks",
        "ready_for_public_staging_code_handoff": evidence["release_eligible"],
        "release_gate_evidence": evidence,
        "ready_for_paid_commercial_launch": False,
        "checks": results,
        "external_blockers": external_blockers,
        "docker_available": bool(docker_path),
        "docker_path": docker_path or "",
        "latest_public_staging_verification": staging_verification,
        "next_external_steps": _next_external_steps(staging_verification),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    output_path = OUT / "latest.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT={output_path}")
    # Publish preflights also consume the exit status, not only the JSON flag.
    return 0 if evidence["release_eligible"] else 1


def _latest_staging_verification() -> dict[str, Any]:
    path = ROOT / "output" / "jiejing-deploy-channel-doctor" / "latest.json"
    if not path.exists():
        return {"status": "not_checked", "public_staging_reachable": False, "deploy_channel_ready": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid_doctor_output", "public_staging_reachable": False, "deploy_channel_ready": False}
    return {
        "status": "historical_verified" if payload.get("deploy_channel_ready") and payload.get("public_staging_reachable") else "historical_blocked",
        "current_state_verified": False,
        "evidence_scope": "historical_unbound_doctor_output_not_current_deploy_authority",
        "deploy_channel_ready": payload.get("deploy_channel_ready") is True,
        "public_staging_reachable": payload.get("public_staging_reachable") is True,
        "public_health_service": (payload.get("public_health") or {}).get("service"),
        "real_platform_writes_enabled": (payload.get("public_health") or {}).get("real_platform_writes_enabled"),
        "secret_exposed": False,
    }


def _next_external_steps(staging_verification: dict[str, Any]) -> list[str]:
    # A historical doctor file is a hint, not current state or deploy authority.
    return [
        "read_docs/JIEJING_CURRENT_EXECUTION_STATE.md_and_AGENTS.md_before_selecting_any_next_action",
        "recheck_current_target_release_and_readiness_only_when_needed_do_not_treat_local_or_historical_evidence_as_live_state",
        "follow_the_target_environment_runbook_staging_uses_manual_github_dry_run_then_explicitly_approved_apply",
        "repair_only_current_missing_or_expired_backup_restore_monitoring_evidence_without_assuming_new_infrastructure_is_needed",
        "do_not_repeat_oauth_unless_the_user_explicitly_approves_new_ebay_account",
        "do_not_repeat_live_sync_payment_refund_or_ebay_proof_just_to_recover_progress",
    ]


def _run_check(key: str, command: list[str]) -> dict[str, Any]:
    started = time.time()
    attempts = 0
    try:
        while True:
            attempts += 1
            check_env = os.environ.copy()
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                env=check_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                # This API suite also exercises full browser recovery journeys.
                # These full suites exceed three minutes on a loaded Windows
                # host (53 browser scenarios / high-volume scoped DB fixtures).
                # Keep every assertion and fail closed if this bound is hit.
                timeout=(600 if key in {"listing_buyer_copy_rewrite_frontend", "listing_single_progress"}
                         else 300 if key.startswith("browser_") or key == "listing_buyer_copy_rewrite_api" else 180),
                check=False,
            )
            combined_output = f"{completed.stdout}\n{completed.stderr}"
            transient_windows_abort = completed.returncode != 0 and (
                "WinError 10053" in combined_output or "ConnectionAbortedError" in combined_output
            )
            if not transient_windows_abort or attempts >= 2:
                break
            time.sleep(0.5)
    except FileNotFoundError as exc:
        return {
            "key": key,
            "pass": False,
            "returncode": 127,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": f"command_not_found: {exc.filename}",
        }
    except subprocess.TimeoutExpired:
        return {
            "key": key,
            "pass": False,
            "returncode": 124,
            "elapsed_seconds": round(time.time() - started, 2),
            "error": "timeout",
        }
    return {
        "key": key,
        "pass": completed.returncode == 0,
        "returncode": completed.returncode,
        "attempts": attempts,
        "elapsed_seconds": round(time.time() - started, 2),
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


if __name__ == "__main__":
    raise SystemExit(main())
