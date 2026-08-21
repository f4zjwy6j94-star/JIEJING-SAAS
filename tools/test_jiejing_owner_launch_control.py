#!/usr/bin/env python3
"""Regression for the platform-internal launch-control packet."""

from __future__ import annotations

import json
import inspect
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.owner_launch_control import (  # noqa: E402
    _owner_mainland_billing_view,
    _owner_mainland_cutover_view,
    _owner_mainland_edge_view,
    _portable_artifact_filename,
    build_owner_launch_control,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-owner-launch-control-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if _portable_artifact_filename(r"C:\\private\\bundle.zip", fallback="fallback.zip") != "bundle.zip":
        return fail("release history must normalize Windows artifact paths without exposing internal directories")
    governance_source = inspect.getsource(SaaSRepository.test_data_governance_snapshot).lower()
    if " like '" in governance_source:
        return fail("test-data governance LIKE patterns must be parameterized for PostgreSQL")
    canonical_packet = {
        "summary": {"mainland_payment_ready_for_owner_approval": True},
        "steps": [
            {"key": "wechat_pay_native_cutover", "status": "ready", "blocked_by": []},
            {"key": "no_charge_launch_rehearsal", "status": "ready", "blocked_by": []},
        ],
        "external_configuration_needed": [
            {"key": "no_charge_rehearsal_evidence_flags", "environment_keys": ["SAFE_FLAG"]}
        ],
        "future_international_payment": {
            "provider": "stripe",
            "blocks_mainland_launch": False,
            "calls_stripe_api": False,
        },
    }
    billing_view = _owner_mainland_billing_view(
        billing={"provider": {"selected": "stripe"}, "billing_ready_for_paid_launch": False},
        paid_packet=canonical_packet,
    )
    if (billing_view.get("provider") or {}).get("selected") != "wechat_pay_native":
        return fail(f"owner billing view must use canonical mainland provider: {billing_view}")
    if billing_view.get("mainland_payment_ready_for_owner_approval") is not True:
        return fail(f"owner billing view ignored canonical owner-ready state: {billing_view}")
    cutover_view = _owner_mainland_cutover_view(
        paid_packet=canonical_packet,
        legacy_billing_cutover={"status": "blocked_by_stripe"},
    )
    if cutover_view.get("status") != "ready_for_owner_approval":
        return fail(f"legacy Stripe rehearsal must not block mainland owner view: {cutover_view}")
    edge_view = _owner_mainland_edge_view(
        edge={
            "status": "blocked_by_stripe_callback",
            "summary": {"waf_ready": True, "origin_locked": True, "callbacks_ready": False},
            "callback_cutover": {"ebay_callback_verified": True, "stripe_urls_verified_in_dashboard": False},
            "required_callback_urls": {"ebay_oauth_callback": "https://app.jiejing.shop/oauth/ebay/callback"},
        },
        paid_packet=canonical_packet,
    )
    if edge_view.get("status") != "ready_for_owner_approval":
        return fail(f"Stripe callback state must not block the mainland owner edge view: {edge_view}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_blocked_env()
    try:
        packet = _build_packet()
    finally:
        _restore_env(previous)

    if packet.get("contract_version") != "2026-08-10-owner-launch-control-v9":
        return fail("owner launch control contract version missing")
    if packet.get("audience") != "platform_internal_admin" or packet.get("customer_visible") is not False:
        return fail("owner launch control must stay platform-internal")
    if packet.get("public_paid_launch_allowed") is not False:
        return fail("owner launch control must not directly allow paid public launch")
    fixed_progress = packet.get("fixed_launch_progress") if isinstance(packet.get("fixed_launch_progress"), dict) else {}
    if fixed_progress.get("contract_version") != "2026-08-20-fixed-public-launch-progress-v2":
        return fail("fixed launch progress contract missing from owner control")
    if fixed_progress.get("fixed_denominator") is not True or fixed_progress.get("total_points") != 100:
        return fail("owner progress must use the fixed 100-point denominator")
    if fixed_progress.get("customer_visible") is not False:
        return fail("fixed launch progress must remain internal")
    if not isinstance(fixed_progress.get("remaining_actions"), list):
        return fail("fixed launch progress must expose a deterministic remaining queue")
    merchant_validation = packet.get("merchant_workflow_validation") if isinstance(packet.get("merchant_workflow_validation"), dict) else {}
    if merchant_validation.get("contract_version") != "2026-07-14-real-merchant-workflow-validation-v1":
        return fail("real merchant workflow validation contract missing from owner control")
    if merchant_validation.get("passed") is not False or merchant_validation.get("customer_visible") is not False:
        return fail("synthetic owner fixture must not earn real merchant validation evidence")
    if merchant_validation.get("blocks_owner_private_pilot") is not False:
        return fail("future scale validation must not block the founder's private owner pilot")
    owner_pilot = packet.get("owner_pilot_workflow_validation") if isinstance(packet.get("owner_pilot_workflow_validation"), dict) else {}
    if owner_pilot.get("contract_version") != "2026-08-10-owner-pilot-workflow-validation-v1":
        return fail("owner pilot validation contract missing from owner control")
    if owner_pilot.get("passed") is not False or owner_pilot.get("blocks_owner_private_pilot") is not True:
        return fail("synthetic owner fixture must still require one real owner pilot path")
    if owner_pilot.get("required_account_count") != 1 or owner_pilot.get("required_path_count") != 1:
        return fail("owner pilot acceptance must stay one account and one complete path")
    for marker in (
        "charge_now_allowed",
        "calls_stripe_api",
        "triggers_real_charge",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if packet.get(marker) is not False:
            return fail(f"owner launch control unsafe flag should be false: {marker}")

    safety = packet.get("safety") if isinstance(packet.get("safety"), dict) else {}
    for marker in (
        "owner_admin_only",
        "platform_internal_admin_only",
        "not_customer_visible",
        "confirmation_center_required_for_real_risk_actions",
    ):
        if safety.get(marker) is not True:
            return fail(f"safety marker should be true: {marker}")
    for marker in (
        "frontend_gets_secret",
        "frontend_gets_raw_ebay_token",
        "frontend_gets_payment_secret",
        "runtime_gets_raw_ebay_token",
        "charge_now_allowed",
        "platform_write_now_allowed",
        "repeat_ebay_oauth_allowed",
        "old_frozen_ebay_account_reuse_allowed",
        "old_demo_product_or_sku_allowed",
        "secret_exposed",
    ):
        if safety.get(marker) is not False:
            return fail(f"safety marker should be false: {marker}")

    lane_keys = {item.get("key") for item in packet.get("lanes", []) if isinstance(item, dict)}
    for key in {
        "launch_gate",
        "ebay_account",
        "billing",
        "subscription_shutdown",
        "domain_security",
        "runtime_queue",
        "publish_safety",
        "ops_observability",
        "backup_restore",
        "no_charge_rehearsal",
    }:
        if key not in lane_keys:
            return fail(f"lane missing: {key}")

    external_keys = {item.get("key") for item in packet.get("external_blockers", []) if isinstance(item, dict)}
    for key in {
        "stable_domain_waf_callbacks",
        "vault_offline_custody",
        "wechat_pay_native_production_cutover",
        "clean_new_ebay_account",
        "fresh_real_test_product_assets",
        "no_charge_rehearsal_evidence",
    }:
        if key not in external_keys:
            return fail(f"external blocker missing: {key}")

    vault_custody = next(
        (
            item
            for item in packet.get("external_blockers", [])
            if isinstance(item, dict) and item.get("key") == "vault_offline_custody"
        ),
        {},
    )
    if vault_custody.get("status") != "blocked":
        return fail(f"missing independent Vault media must remain an explicit external blocker: {vault_custody}")
    if vault_custody.get("owner") != "founder_operator":
        return fail(f"Vault custody must be presented as a founder-owned physical action: {vault_custody}")
    if vault_custody.get("triggers_real_charge") is not False or vault_custody.get("secret_exposed") is not False:
        return fail(f"Vault custody guidance must stay value-free and non-financial: {vault_custody}")

    work_keys = {item.get("key") for item in packet.get("internal_work_queue", []) if isinstance(item, dict)}
    for key in {
        "owner_launch_control",
        "secret_scan",
        "browser_smoke",
        "free_waf_bot_evidence",
        "ops_observability",
        "quota_state_visibility",
        "no_charge_rehearsal",
    }:
        if key not in work_keys:
            return fail(f"internal work item missing: {key}")

    summary = packet.get("summary") if isinstance(packet.get("summary"), dict) else {}
    if summary.get("latest_official_ebay_packet_id") == "":
        return fail("latest official eBay packet evidence should be surfaced")
    if int(summary.get("ebay_token_refresh_success_count") or 0) != 0:
        return fail("fixture must not fake eBay refresh proof")
    if "test_data_candidate_count" not in summary or "test_data_governance_status" not in summary:
        return fail("summary should expose test data governance status")
    if "subscription_shutdown_ready_count" not in summary or "subscription_shutdown_total_count" not in summary:
        return fail("summary should expose subscription shutdown closure counts")

    war_room = packet.get("war_room") if isinstance(packet.get("war_room"), dict) else {}
    if war_room.get("contract_version") != "2026-06-20-owner-war-room-v3":
        return fail("war room v2 contract missing")
    if war_room.get("customer_visible") is not False:
        return fail("war room must stay internal")
    war_keys = {item.get("key") for item in war_room.get("sections", []) if isinstance(item, dict)}
    for key in {"entry_security", "billing_revenue", "ebay_account", "operations", "ops_observability", "test_data", "confirmation_center"}:
        if key not in war_keys:
            return fail(f"war room section missing: {key}")
    launch_decision = war_room.get("launch_decision") if isinstance(war_room.get("launch_decision"), dict) else {}
    for marker in ("public_paid_launch_allowed", "charge_now_allowed", "platform_write_now_allowed", "repeat_ebay_oauth_allowed"):
        if launch_decision.get(marker) is not False:
            return fail(f"war room launch decision should keep {marker}=false")

    test_data = packet.get("test_data_governance") if isinstance(packet.get("test_data_governance"), dict) else {}
    if test_data.get("contract_version") != "2026-06-20-test-data-governance":
        return fail("test data governance contract missing")
    if test_data.get("scope") != "current_company_only" or test_data.get("global_tenant_scan_exposed") is not False:
        return fail("test data governance must stay current-company scoped")
    if int(test_data.get("candidate_count") or 0) < 1:
        return fail("test data governance should detect marked smoke data in fixture")
    cleanup_policy = test_data.get("cleanup_policy") if isinstance(test_data.get("cleanup_policy"), dict) else {}
    if cleanup_policy.get("delete_now_allowed") is not False or cleanup_policy.get("automatic_delete_allowed") is not False:
        return fail("test data governance must not allow automatic delete")

    ops = packet.get("operations_observability") if isinstance(packet.get("operations_observability"), dict) else {}
    if ops.get("contract_version") != "2026-06-20-owner-ops-observability-v1":
        return fail("operations observability contract missing")
    if ops.get("audience") != "platform_internal_admin" or ops.get("customer_visible") is not False:
        return fail("operations observability must stay internal")
    ops_keys = {item.get("key") for item in ops.get("cards", []) if isinstance(item, dict)}
    for key in {
        "queue_worker_runtime",
        "backup_restore_drill",
        "high_cost_api_protection",
        "post_publish_dry_run",
        "subscription_quota_shutdown",
        "test_data_governance",
    }:
        if key not in ops_keys:
            return fail(f"operations observability card missing: {key}")
    ops_safety = ops.get("safety") if isinstance(ops.get("safety"), dict) else {}
    for marker in (
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "triggers_ebay_oauth",
        "triggers_real_platform_write",
        "frontend_gets_secret",
        "secret_exposed",
    ):
        if ops_safety.get(marker) is not False:
            return fail(f"operations observability unsafe flag should be false: {marker}")

    resilience = packet.get("resilience_war_room") if isinstance(packet.get("resilience_war_room"), dict) else {}
    if resilience.get("contract_version") != "2026-06-20-owner-resilience-war-room-v1":
        return fail("resilience war room contract missing")
    if resilience.get("audience") != "platform_internal_admin" or resilience.get("customer_visible") is not False:
        return fail("resilience war room must stay internal")
    resilience_keys = {item.get("key") for item in resilience.get("cards", []) if isinstance(item, dict)}
    for key in {
        "backup_restore_rehearsal",
        "incident_runbook_coverage",
        "alert_route_and_cls",
        "queue_worker_incident_mode",
        "billing_quota_incident_mode",
        "ebay_write_incident_containment",
        "test_data_rollback_boundary",
    }:
        if key not in resilience_keys:
            return fail(f"resilience war room card missing: {key}")
    resilience_safety = resilience.get("safety") if isinstance(resilience.get("safety"), dict) else {}
    for marker in (
        "exports_database",
        "exports_raw_secret",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "triggers_ebay_oauth",
        "triggers_real_platform_write",
        "frontend_gets_secret",
        "secret_exposed",
    ):
        if resilience_safety.get(marker) is not False:
            return fail(f"resilience war room unsafe flag should be false: {marker}")

    shutdown = packet.get("subscription_shutdown_control") if isinstance(packet.get("subscription_shutdown_control"), dict) else {}
    if shutdown.get("contract_version") != "2026-06-20-owner-subscription-shutdown-control-v1":
        return fail("subscription shutdown control contract missing")
    if shutdown.get("audience") != "platform_internal_admin" or shutdown.get("customer_visible") is not False:
        return fail("subscription shutdown control must stay internal")
    shutdown_summary = shutdown.get("summary") if isinstance(shutdown.get("summary"), dict) else {}
    if int(shutdown_summary.get("card_count") or 0) < 6:
        return fail(f"subscription shutdown control should expose closure cards: {shutdown_summary}")
    shutdown_keys = {item.get("key") for item in shutdown.get("cards", []) if isinstance(item, dict)}
    for key in {
        "payment_failed_disables_entitlement",
        "subscription_cancel_disables_entitlement",
        "quota_guardrail_blocks_metered_work",
        "provider_cutover_no_real_charge_safety",
        "current_company_shutdown_state",
    }:
        if key not in shutdown_keys:
            return fail(f"subscription shutdown card missing: {key}")
    shutdown_safety = shutdown.get("safety") if isinstance(shutdown.get("safety"), dict) else {}
    for marker in (
        "customer_visible",
        "public_charging_allowed",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "triggers_real_platform_write",
        "frontend_gets_payment_secret",
        "frontend_gets_api_key",
        "secret_exposed",
    ):
        if shutdown_safety.get(marker) is not False:
            return fail(f"subscription shutdown unsafe flag should be false: {marker}")

    owner_review = packet.get("owner_review_packet") if isinstance(packet.get("owner_review_packet"), dict) else {}
    if owner_review.get("contract_version") != "2026-06-20-owner-review-packet-v1":
        return fail("owner review packet contract missing")
    if owner_review.get("audience") != "platform_internal_admin" or owner_review.get("customer_visible") is not False:
        return fail("owner review packet must stay internal")
    if owner_review.get("download_allowed_for_internal_admin") is not True:
        return fail("owner review packet should be downloadable only for internal admin")
    review_summary = owner_review.get("summary") if isinstance(owner_review.get("summary"), dict) else {}
    if int(review_summary.get("review_item_count") or 0) < 10:
        return fail(f"owner review packet should expose launch review items: {review_summary}")
    review_keys = {item.get("key") for item in owner_review.get("review_items", []) if isinstance(item, dict)}
    for key in {
        "paid_launch_gate",
        "billing_cutover",
        "subscription_shutdown",
        "stable_domain_waf_callbacks",
        "ebay_account_refresh",
        "backup_restore",
        "operations_observability",
        "resilience_war_room",
        "test_data_governance",
        "confirmation_center",
    }:
        if key not in review_keys:
            return fail(f"owner review item missing: {key}")
    owner_review_safety = owner_review.get("safety") if isinstance(owner_review.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if owner_review_safety.get(marker) is not True:
            return fail(f"owner review safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if owner_review.get(marker) is not False and owner_review_safety.get(marker) is not False:
            return fail(f"owner review unsafe flag should be false: {marker}")

    audit = packet.get("launch_rehearsal_audit_packet") if isinstance(packet.get("launch_rehearsal_audit_packet"), dict) else {}
    if audit.get("contract_version") != "2026-06-20-launch-rehearsal-audit-v1":
        return fail("launch rehearsal audit packet contract missing")
    if audit.get("audience") != "platform_internal_admin" or audit.get("customer_visible") is not False:
        return fail("launch rehearsal audit must stay internal")
    if audit.get("download_allowed_for_internal_admin") is not True:
        return fail("launch rehearsal audit should be downloadable only for internal admin")
    audit_summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    if int(audit_summary.get("check_count") or 0) < 10:
        return fail(f"launch rehearsal audit should expose enough checks: {audit_summary}")
    audit_keys = {item.get("key") for item in audit.get("checks", []) if isinstance(item, dict)}
    for key in {
        "predeploy_health_readiness_snapshot",
        "secret_scan_evidence",
        "browser_smoke_evidence",
        "owner_review_packet_snapshot",
        "billing_no_charge_rehearsal",
        "edge_waf_callback_snapshot",
        "subscription_shutdown_snapshot",
        "paid_launch_approval_snapshot",
        "rollback_controls_verified",
        "ops_resilience_snapshot",
    }:
        if key not in audit_keys:
            return fail(f"launch rehearsal audit check missing: {key}")
    audit_safety = audit.get("safety") if isinstance(audit.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if audit_safety.get(marker) is not True:
            return fail(f"launch rehearsal audit safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if audit.get(marker) is not False and audit_safety.get(marker) is not False:
            return fail(f"launch rehearsal audit unsafe flag should be false: {marker}")
    rollback_controls = audit.get("rollback_controls") if isinstance(audit.get("rollback_controls"), list) else []
    for marker in {
        "keep_current_database_and_merchant_records_unchanged",
        "rollback_only_application_bundle_or_runtime_config_when_needed",
        "keep_public_checkout_disabled_until_owner_approval",
        "keep_real_ebay_writes_confirmation_gated_after_cutover",
    }:
        if marker not in rollback_controls:
            return fail(f"launch rehearsal audit rollback control missing: {marker}")

    release_history = packet.get("release_history") if isinstance(packet.get("release_history"), dict) else {}
    if release_history.get("contract_version") != "2026-06-20-owner-release-history-v1":
        return fail("owner release history contract missing")
    if release_history.get("audience") != "platform_internal_admin" or release_history.get("customer_visible") is not False:
        return fail("owner release history must stay internal")
    if release_history.get("download_allowed_for_internal_admin") is not True:
        return fail("owner release history should be downloadable only for internal admin")
    release_summary = release_history.get("summary") if isinstance(release_history.get("summary"), dict) else {}
    if int(release_summary.get("bundle_record_count") or 0) < 1:
        return fail(f"owner release history should include seeded bundle manifest: {release_summary}")
    if int(release_summary.get("rollback_point_count") or 0) < 1:
        return fail(f"owner release history should include seeded rollback point: {release_summary}")
    release_records = release_history.get("records") if isinstance(release_history.get("records"), list) else []
    if not any(isinstance(item, dict) and item.get("zip_sha256") == "unit-release-sha256" for item in release_records):
        return fail("owner release history should surface sanitized bundle sha256")
    release_checks = {item.get("key") for item in release_history.get("release_checks", []) if isinstance(item, dict)}
    for key in {
        "latest_bundle_manifest",
        "frontend_asset_version",
        "rollback_backup_pointer",
        "readiness_snapshot",
        "ebay_refresh_proof_snapshot",
        "billing_public_charge_block",
    }:
        if key not in release_checks:
            return fail(f"owner release history check missing: {key}")
    release_safety = release_history.get("safety") if isinstance(release_history.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if release_safety.get(marker) is not True:
            return fail(f"owner release history safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "secret_exposed",
    ):
        if release_history.get(marker) is not False and release_safety.get(marker) is not False:
            return fail(f"owner release history unsafe flag should be false: {marker}")

    handoff = packet.get("continuity_handoff_digest") if isinstance(packet.get("continuity_handoff_digest"), dict) else {}
    if handoff.get("contract_version") != "2026-06-20-owner-continuity-handoff-v1":
        return fail("owner continuity handoff contract missing")
    if handoff.get("audience") != "platform_internal_admin" or handoff.get("customer_visible") is not False:
        return fail("owner continuity handoff must stay internal")
    if handoff.get("download_allowed_for_internal_admin") is not True:
        return fail("owner continuity handoff should be downloadable only for internal admin")
    handoff_summary = handoff.get("summary") if isinstance(handoff.get("summary"), dict) else {}
    if int(handoff_summary.get("current_state_count") or 0) < 5:
        return fail(f"owner continuity handoff should expose current state lines: {handoff_summary}")
    if int(handoff_summary.get("do_not_do_count") or 0) < 5:
        return fail(f"owner continuity handoff should expose no-go rules: {handoff_summary}")
    state_keys = {item.get("key") for item in handoff.get("current_state", []) if isinstance(item, dict)}
    for key in {"public_entry", "readiness", "ebay_refresh_proof", "billing", "latest_release"}:
        if key not in state_keys:
            return fail(f"owner continuity handoff state missing: {key}")
    action_keys = {item.get("key") for item in handoff.get("next_external_actions", []) if isinstance(item, dict)}
    if "wechat_pay_native_production_cutover" not in action_keys:
        return fail(f"owner continuity handoff should preserve external blocker actions: {action_keys}")
    handoff_text = handoff.get("handoff_text") or ""
    for marker in (
        "public_paid_launch_allowed=false",
        "charge_now_allowed=false",
        "platform_write_now_allowed=false",
        "repeat_ebay_oauth_allowed=false",
        "secret_exposed=false",
    ):
        if marker not in handoff_text:
            return fail(f"owner continuity handoff text missing marker: {marker}")
    handoff_safety = handoff.get("safety") if isinstance(handoff.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if handoff_safety.get(marker) is not True:
            return fail(f"owner continuity handoff safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "secret_exposed",
    ):
        if handoff.get(marker) is not False and handoff_safety.get(marker) is not False:
            return fail(f"owner continuity handoff unsafe flag should be false: {marker}")

    cutover = packet.get("cutover_decision_checklist") if isinstance(packet.get("cutover_decision_checklist"), dict) else {}
    if cutover.get("contract_version") != "2026-06-20-cutover-decision-checklist-v1":
        return fail("cutover decision checklist contract missing")
    if cutover.get("audience") != "platform_internal_admin" or cutover.get("customer_visible") is not False:
        return fail("cutover decision checklist must stay internal")
    if cutover.get("download_allowed_for_internal_admin") is not True:
        return fail("cutover decision checklist should be downloadable only for internal admin")
    cutover_summary = cutover.get("summary") if isinstance(cutover.get("summary"), dict) else {}
    if cutover_summary.get("recommended_next_step") not in {
        "continue_internal_hardening",
        "wait_for_founder_external_console",
        "run_final_no_real_charge_rehearsal",
        "prepare_owner_live_cutover_approval",
        "keep_public_paid_launch_blocked",
    }:
        return fail(f"cutover decision checklist next step invalid: {cutover_summary}")
    if cutover_summary.get("public_paid_launch_allowed") is not False:
        return fail("cutover decision checklist must not allow paid public launch")
    if cutover_summary.get("charge_now_allowed") is not False or cutover_summary.get("platform_write_now_allowed") is not False:
        return fail("cutover decision checklist must keep charge/write disabled")
    phase_keys = {item.get("key") for item in cutover.get("phase_checklist", []) if isinstance(item, dict)}
    for key in {
        "current_beta_state",
        "codex_internal_continuation",
        "founder_external_console",
        "final_no_real_charge_rehearsal",
        "live_paid_public_launch",
    }:
        if key not in phase_keys:
            return fail(f"cutover decision phase missing: {key}")
    founder_keys = {item.get("key") for item in cutover.get("founder_external_actions", []) if isinstance(item, dict)}
    for key in {"wechat_pay_native_production_cutover", "clean_new_ebay_account"}:
        if key not in founder_keys:
            return fail(f"cutover decision should preserve founder external action: {key}")
    internal_keys = {item.get("key") for item in cutover.get("codex_internal_actions", []) if isinstance(item, dict)}
    if not {"secret_scan", "browser_smoke", "no_charge_rehearsal"}.intersection(internal_keys):
        return fail(f"cutover decision should preserve internal continuation actions: {internal_keys}")
    if len(cutover.get("forbidden_actions", [])) < 5:
        return fail("cutover decision checklist should expose no-go actions")
    cutover_safety = cutover.get("safety") if isinstance(cutover.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if cutover_safety.get(marker) is not True:
            return fail(f"cutover decision safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if cutover.get(marker) is not False and cutover_safety.get(marker) is not False:
            return fail(f"cutover decision checklist unsafe flag should be false: {marker}")

    final_record = (
        packet.get("final_launch_rehearsal_execution_record")
        if isinstance(packet.get("final_launch_rehearsal_execution_record"), dict)
        else {}
    )
    if final_record.get("contract_version") != "2026-06-21-final-launch-rehearsal-execution-record-v1":
        return fail("final launch rehearsal execution record contract missing")
    if final_record.get("audience") != "platform_internal_admin" or final_record.get("customer_visible") is not False:
        return fail("final launch rehearsal execution record must stay internal")
    if final_record.get("download_allowed_for_internal_admin") is not True:
        return fail("final launch rehearsal execution record should be downloadable only for internal admin")
    final_summary = final_record.get("summary") if isinstance(final_record.get("summary"), dict) else {}
    if final_summary.get("recommended_next_step") not in {
        "founder_finish_external_console_prerequisites",
        "run_internal_no_real_charge_rehearsal",
        "prepare_owner_live_cutover_approval",
        "keep_public_paid_launch_blocked",
    }:
        return fail(f"final launch rehearsal next step invalid: {final_summary}")
    for marker in ("public_paid_launch_allowed", "charge_now_allowed", "platform_write_now_allowed", "repeat_ebay_oauth_allowed", "secret_exposed"):
        if final_summary.get(marker) is not False:
            return fail(f"final launch rehearsal summary unsafe marker should be false: {marker}")
    step_keys = {item.get("key") for item in final_record.get("execution_steps", []) if isinstance(item, dict)}
    for key in {
        "predeploy_health_readiness_snapshot",
        "secret_scan_snapshot",
        "browser_smoke_snapshot",
        "bundle_integrity_and_sha",
        "rollback_backup_pointer",
        "owner_review_packet_attached",
        "cutover_decision_checklist_attached",
        "no_real_charge_billing_rehearsal",
        "edge_waf_callback_snapshot",
        "ebay_new_account_refresh_proof",
        "final_owner_approval_hold",
    }:
        if key not in step_keys:
            return fail(f"final launch rehearsal execution step missing: {key}")
    final_external_keys = {item.get("key") for item in final_record.get("remaining_external_blockers", []) if isinstance(item, dict)}
    for key in {"wechat_pay_native_production_cutover", "clean_new_ebay_account"}:
        if key not in final_external_keys:
            return fail(f"final launch rehearsal should preserve external blocker action: {key}")
    final_internal_keys = {item.get("key") for item in final_record.get("remaining_internal_actions", []) if isinstance(item, dict)}
    if not {"secret_scan", "browser_smoke", "no_charge_rehearsal"}.intersection(final_internal_keys):
        return fail(f"final launch rehearsal should preserve internal continuation actions: {final_internal_keys}")
    rollback_keys = {item.get("key") for item in final_record.get("rollback_controls", []) if isinstance(item, dict)}
    for key in {"staging_patch_backup_pointer", "latest_bundle_sha256", "readiness_public_launch_hold"}:
        if key not in rollback_keys:
            return fail(f"final launch rehearsal rollback control missing: {key}")
    final_safety = final_record.get("safety") if isinstance(final_record.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if final_safety.get(marker) is not True:
            return fail(f"final launch rehearsal safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if final_record.get(marker) is not False and final_safety.get(marker) is not False:
            return fail(f"final launch rehearsal unsafe flag should be false: {marker}")

    approval_dossier = (
        packet.get("owner_paid_launch_approval_dossier")
        if isinstance(packet.get("owner_paid_launch_approval_dossier"), dict)
        else {}
    )
    if approval_dossier.get("contract_version") != "2026-07-02-owner-paid-launch-approval-dossier-v1":
        return fail("owner paid launch approval dossier contract missing")
    if approval_dossier.get("audience") != "platform_internal_admin" or approval_dossier.get("customer_visible") is not False:
        return fail("owner paid launch approval dossier must stay internal")
    if approval_dossier.get("ordinary_merchant_visible") is not False or approval_dossier.get("merchant_surface_safe") is not True:
        return fail("owner paid launch approval dossier must not be ordinary merchant visible")
    if approval_dossier.get("download_allowed_for_internal_admin") is not True:
        return fail("owner paid launch approval dossier should be downloadable only for internal admin")
    dossier_summary = approval_dossier.get("summary") if isinstance(approval_dossier.get("summary"), dict) else {}
    if dossier_summary.get("decision") != "do_not_enable_paid_public_launch_yet":
        return fail(f"owner paid launch approval dossier must block paid launch: {dossier_summary}")
    if not isinstance(dossier_summary.get("readiness_score_percent"), int):
        return fail(f"owner paid launch approval dossier should expose integer readiness score: {dossier_summary}")
    for marker in ("public_paid_launch_allowed", "charge_now_allowed", "platform_write_now_allowed", "repeat_ebay_oauth_allowed", "secret_exposed"):
        if dossier_summary.get(marker) is not False:
            return fail(f"owner paid launch approval dossier summary unsafe marker should be false: {marker}")
    dossier_section_keys = {item.get("key") for item in approval_dossier.get("sections", []) if isinstance(item, dict)}
    for key in {
        "public_readiness_truth",
        "mainland_payment_truth",
        "no_charge_live_domain_evidence",
        "new_ebay_account_refresh_proof",
        "paid_launch_packet_truth",
        "final_rehearsal_and_rollback",
    }:
        if key not in dossier_section_keys:
            return fail(f"owner paid launch approval dossier section missing: {key}")
    no_charge_item_keys = {item.get("key") for item in approval_dossier.get("no_charge_evidence_items", []) if isinstance(item, dict)}
    for key in {"no_charge_rehearsal_evidence_flags"}:
        if key not in no_charge_item_keys:
            return fail(f"owner paid launch approval dossier should include no-charge evidence item: {key}")
    dossier_safety = approval_dossier.get("safety") if isinstance(approval_dossier.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "merchant_surface_safe", "download_allowed_for_internal_admin"):
        if dossier_safety.get(marker) is not True:
            return fail(f"owner paid launch approval dossier safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "ordinary_merchant_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if approval_dossier.get(marker) is not False and dossier_safety.get(marker) is not False:
            return fail(f"owner paid launch approval dossier unsafe flag should be false: {marker}")

    prelaunch_report = (
        packet.get("prelaunch_acceptance_report")
        if isinstance(packet.get("prelaunch_acceptance_report"), dict)
        else {}
    )
    if prelaunch_report.get("contract_version") != "2026-06-21-prelaunch-acceptance-report-v1":
        return fail("prelaunch acceptance report contract missing")
    if prelaunch_report.get("audience") != "platform_internal_admin" or prelaunch_report.get("customer_visible") is not False:
        return fail("prelaunch acceptance report must stay internal")
    if prelaunch_report.get("download_allowed_for_internal_admin") is not True:
        return fail("prelaunch acceptance report should be downloadable only for internal admin")
    report_summary = prelaunch_report.get("summary") if isinstance(prelaunch_report.get("summary"), dict) else {}
    if report_summary.get("decision") != "do_not_launch_paid_public_yet":
        return fail(f"prelaunch report decision must block paid launch: {report_summary}")
    if not isinstance(report_summary.get("readiness_score_percent"), int):
        return fail(f"prelaunch report should expose integer readiness score: {report_summary}")
    for marker in ("public_paid_launch_allowed", "charge_now_allowed", "platform_write_now_allowed", "repeat_ebay_oauth_allowed", "secret_exposed"):
        if report_summary.get(marker) is not False:
            return fail(f"prelaunch report summary unsafe marker should be false: {marker}")
    report_item_keys = {item.get("key") for item in prelaunch_report.get("report_items", []) if isinstance(item, dict)}
    for key in {
        "public_entry_and_domain",
        "operational_health",
        "billing_provider",
        "ebay_refresh_proof",
        "confirmation_center_boundary",
        "secret_and_data_boundary",
        "release_artifact_and_rollback",
        "final_rehearsal_record",
        "owner_paid_launch_approval_dossier",
    }:
        if key not in report_item_keys:
            return fail(f"prelaunch report item missing: {key}")
    if report_summary.get("owner_paid_launch_approval_dossier_status") != approval_dossier.get("status"):
        return fail(f"prelaunch report should summarize approval dossier status: {report_summary}")
    report_founder_keys = {item.get("key") for item in prelaunch_report.get("founder_required_actions", []) if isinstance(item, dict)}
    for key in {"wechat_pay_native_production_cutover", "clean_new_ebay_account"}:
        if key not in report_founder_keys:
            return fail(f"prelaunch report should preserve founder required action: {key}")
    decision_record = prelaunch_report.get("decision_record") if isinstance(prelaunch_report.get("decision_record"), dict) else {}
    if decision_record.get("paid_public_launch_allowed") is not False:
        return fail("prelaunch report decision must not allow paid public launch")
    report_markdown = prelaunch_report.get("report_markdown") or ""
    for marker in (
        "# Jiejing prelaunch acceptance report",
        "decision: do_not_launch_paid_public_yet",
        "public_paid_launch_allowed: False",
        "charge_now_allowed: False",
        "Do not create a payable QR or call a live payment provider",
        "Do not run or repeat eBay OAuth",
    ):
        if marker not in report_markdown:
            return fail(f"prelaunch report markdown missing marker: {marker}")
    report_safety = prelaunch_report.get("safety") if isinstance(prelaunch_report.get("safety"), dict) else {}
    for marker in ("read_only", "platform_internal_admin_only", "download_allowed_for_internal_admin"):
        if report_safety.get(marker) is not True:
            return fail(f"prelaunch report safety marker should be true: {marker}")
    for marker in (
        "customer_visible",
        "exports_database",
        "exports_raw_secret",
        "includes_raw_tokens",
        "includes_payment_secret",
        "reads_env_secret_values",
        "calls_stripe_api",
        "creates_checkout_session",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_secret",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "secret_exposed",
    ):
        if prelaunch_report.get(marker) is not False and report_safety.get(marker) is not False:
            return fail(f"prelaunch report unsafe flag should be false: {marker}")

    feasibility = packet.get("feasibility_review") if isinstance(packet.get("feasibility_review"), dict) else {}
    if feasibility.get("contract_version") != "2026-07-01-expert-feasibility-review-v1":
        return fail("expert feasibility review contract missing")
    if feasibility.get("audience") != "platform_internal_admin" or feasibility.get("customer_visible") is not False:
        return fail("expert feasibility review must stay internal")
    feasibility_summary = feasibility.get("summary") if isinstance(feasibility.get("summary"), dict) else {}
    if feasibility_summary.get("feasible_for_paid_public_launch") is not False:
        return fail(f"expert feasibility review must block paid public launch: {feasibility_summary}")
    if feasibility_summary.get("recommended_decision") != "continue_private_beta_do_not_charge_publicly":
        return fail(f"expert feasibility review should recommend private beta only: {feasibility_summary}")
    expert_keys = {item.get("key") for item in feasibility.get("expert_reviews", []) if isinstance(item, dict)}
    for key in {
        "product_market_fit",
        "billing_subscription_revenue",
        "architecture_operations",
        "security_compliance",
        "ai_value_delivery",
    }:
        if key not in expert_keys:
            return fail(f"expert feasibility review missing expert card: {key}")
    top_risks = set(feasibility.get("top_risks", []) if isinstance(feasibility.get("top_risks"), list) else [])
    for key in {"backend_refresh_success_proof_missing", "merchant_willingness_to_pay_and_unit_economics_unproven"}:
        if key not in top_risks:
            return fail(f"expert feasibility review should surface top risk: {key}")
    operating_model = feasibility.get("operating_model_review") if isinstance(feasibility.get("operating_model_review"), dict) else {}
    operating_evidence = operating_model.get("evidence") if isinstance(operating_model.get("evidence"), dict) else {}
    if operating_model.get("status") != "private_beta_operating_model_ready_paid_launch_still_blocked":
        return fail("expert feasibility review should expose the operating model review")
    if operating_evidence.get("manual_import_is_valid_beta_lane") is not True:
        return fail("operating model should keep manual/import as valid beta fallback")
    if operating_evidence.get("read_only_before_write") is not True or operating_evidence.get("writes_require_confirmation_center") is not True:
        return fail("operating model should enforce read-only before write and confirmation-gated writes")
    if operating_evidence.get("asset_manifest_required") is not True or operating_evidence.get("brief_is_not_generated_media") is not True:
        return fail("operating model should require AssetManifest review before listing use")
    if "let_merchant_model_choice_bypass_asset_manifest" not in operating_model.get("must_not_do", []):
        return fail("operating model should block merchant model choice bypassing AssetManifest")
    feasibility_safety = feasibility.get("safety") if isinstance(feasibility.get("safety"), dict) else {}
    for marker in (
        "public_charging_allowed",
        "creates_checkout_session",
        "calls_stripe_api",
        "triggers_real_charge",
        "charge_now_allowed",
        "triggers_ebay_oauth",
        "repeat_ebay_oauth_allowed",
        "triggers_real_platform_write",
        "platform_write_now_allowed",
        "frontend_gets_payment_secret",
        "frontend_gets_ebay_token",
        "exports_raw_secret",
        "exports_database",
        "secret_exposed",
    ):
        if feasibility.get(marker) is not False and feasibility_safety.get(marker) is not False:
            return fail(f"expert feasibility review unsafe flag should be false: {marker}")

    serialized = json.dumps(packet, ensure_ascii=False).lower()
    for forbidden in (
        "sk_live_unit_secret",
        "whsec_live_unit_secret",
        "authorization: bearer",
        "refresh_token=",
        "access_token=",
        "client_secret=",
        "automatic_delete_allowed=true",
        "global_tenant_scan_exposed=true",
        "exports_database=true",
        "exports_raw_secret=true",
        "includes_raw_tokens=true",
        "includes_payment_secret=true",
        "public_charging_allowed=true",
        "creates_checkout_session=true",
        "charge_now_allowed=true",
        "platform_write_now_allowed=true",
        "reads_env_secret_values=true",
    ):
        if forbidden in serialized:
            return fail(f"owner launch control leaked forbidden marker: {forbidden}")

    print("PASS jiejing_owner_launch_control")
    return 0


def _build_packet() -> dict[str, object]:
    db_path = OUT / "owner-launch-control.sqlite"
    runtime_db_path = OUT / "runtime-owner-launch-control.sqlite"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path)
    repo.initialize()
    fixture = repo.create_user_with_company(
        email="owner-launch-control@example.test",
        password="local-test-password",
        company_name="Owner Launch Control",
    )
    company_id = fixture["company"]["company_id"]
    user_id = fixture["user"]["user_id"]
    store = repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": "Owner Control Store", "marketplace": "EBAY_US", "stage": "store_opened"},
    )
    repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={
            "platform": "ebay",
            "store_name": "Codex Owner Launch Smoke Store",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
            "settings": {"created_from": "codex_owner_launch_control_smoke"},
        },
    )
    repo.create_platform_data_packet(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        packet={
            "platform": "ebay",
            "packet_type": "official_read_snapshot",
            "source_mode": "official_api",
            "status": "ready",
            "present_resource_keys": [
                "store_profile",
                "account_business_policies",
                "inventory_and_offers",
                "orders_and_fulfillment",
                "finances",
                "taxonomy_listing_metadata",
            ],
            "missing_resource_keys": [],
            "secret_exposed": False,
        },
    )
    _seed_release_artifacts(OUT)
    return build_owner_launch_control(settings, repo, company_id=company_id, store_id=store["store_id"])


def _seed_release_artifacts(root: Path) -> None:
    bundle_dir = root / "jiejing-public-staging-bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "jiejing-public-staging-20990101-010101.manifest.json").write_text(
        json.dumps(
            {
                "product": "Jiejing SaaS",
                "bundle": "public_staging",
                "created_at": "2099-01-01T01:01:01Z",
                "file_count": 7,
                "zip_sha256": "unit-release-sha256",
                "zip_path": str(bundle_dir / "jiejing-public-staging-20990101-010101.zip"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    backup_dir = root / "staging-patch-backups" / "20990101-010101"
    backup_dir.mkdir(parents=True, exist_ok=True)


def _set_blocked_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
            "JIEJING_STRIPE_SECRET_KEY": "sk_live_unit_secret",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_live_unit_secret",
        }
    )
    return previous


def _keys() -> list[str]:
    return [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_PUBLIC_BASE_URL",
        "JIEJING_CORS_ORIGIN",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "JIEJING_FRESH_REAL_TEST_PRODUCT_ASSETS_READY",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_BROWSER_SMOKE_PASSED",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
