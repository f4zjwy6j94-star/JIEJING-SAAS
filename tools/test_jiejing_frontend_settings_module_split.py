#!/usr/bin/env python3
"""Regression for the first settings-page split out of app.js."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "app.html"
APP_JS = ROOT / "app.js"
MODULE = ROOT / "assets" / "jiejing-settings-panels.js"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_html = APP_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    module_js = MODULE.read_text(encoding="utf-8")
    module_marker = "./assets/jiejing-settings-panels.js?v=20260620-prelaunch-deferred-v1"
    app_marker = "./app.js?v="
    if module_marker not in app_html:
        return fail("app.html should load the settings panels module")
    if app_html.index(module_marker) > app_html.index(app_marker):
        return fail("settings panels module must load before app.js so init can use it")
    for marker in [
        "global.JiejingSettingsPanels",
        "renderBillingProviderPanel",
        "billing_live_cutover_matrix",
        "stripe_billing_live_cutover_matrix",
        "stripe_domain_cutover_rehearsal",
        "billing_test_rehearsal_summary",
        "no_charge_billing_rehearsal",
        "no-charge test flow",
        "subscription_quota_shutdown_closure",
        "saas-subscription-quota-shutdown-closure",
        "payment_failed_disables_entitlement",
        "subscription_cancel_disables_entitlement",
        "quota_guardrail_blocks_metered_work",
        "provider_cutover_no_real_charge_safety",
        "quota_shutdown_state",
        "blocks_metered_work_when_inactive",
        "_renderBillingTestRehearsal",
        "_renderSubscriptionQuotaShutdownClosure",
        "ready_without_stripe_account",
        "saas-billing-domain-cutover-rehearsal",
        "_renderBillingDomainCutoverRehearsal",
        "_renderBillingDomainCutoverStage",
        "stripe_checkout_return_urls_on_stable_domain",
        "stripe_signed_webhook_on_stable_domain",
        "subscription_state_and_quota_lifecycle_rehearsed",
        "creates_checkout_session",
        "calls_stripe_api",
        "_renderBillingLiveCutoverStep",
        "stripe_live_provider_selected",
        "stripe_signed_webhook_contract",
        "stripe_entitlement_quota_lifecycle",
        "renderCommercialLaunchActionPlanPanel",
        "renderEdgeCutoverReadinessPanel",
        "saas-edge-cutover-readiness",
        "edge_cutover_preflight",
        "stable_domain_purchase_confirmed",
        "waf_edge_onboarded",
        "origin_direct_access_locked",
        "ebay_stripe_callbacks_on_stable_domain",
        "charge_now_allowed=${Boolean(packet.charge_now_allowed)}",
        "triggers_ebay_oauth=${Boolean(packet.triggers_ebay_oauth)}",
        "triggers_real_platform_write=${Boolean(packet.triggers_real_platform_write)}",
        "paid_launch_approval_packet",
        "saas-paid-launch-approval-packet",
        "_renderPaidLaunchApprovalPacket",
        "_renderPaidLaunchApprovalStep",
        "_renderPaidLaunchExternalItem",
        "stable_domain_hardening",
        "stripe_live_cutover",
        "no_charge_launch_rehearsal",
        "renderQueueHealthPanel",
        "renderPublicSecurityStatusPanel",
        "saas-owner-public-security-status",
        "High-cost API rate limit",
        "not_customer_visible=true",
        "commercial_hardening_drills",
        "paid_launch_cutover_checklist",
        "paid_launch_cutover_decision",
        "billing_domain_cutover_runbook",
        "new_ebay_account_smoke_runbook",
        "prelaunch_deferred_strategy",
        "formal_payment_deferred",
        "clean_ebay_account_validation_deferred",
        "autonomous_internal_prelaunch_work",
        "can_continue_without_payment=${Boolean(strategy.can_continue_without_payment)}",
        "can_continue_without_new_ebay_account=${Boolean(strategy.can_continue_without_new_ebay_account)}",
        "saas-prelaunch-deferred-strategy",
        "_renderPrelaunchDeferredStrategy",
        "_renderPrelaunchStrategyItem",
        "_renderCommercialHardeningDrill",
        "_renderNewEbayAccountSmokeStep",
        "_renderPaidLaunchCutoverItem",
        "_renderPaidLaunchCutoverDecision",
        "_renderPaidLaunchCutoverLane",
        "_renderPaidLaunchRunbookStep",
        "saas-commercial-hardening-drills",
        "saas-new-ebay-smoke-runbook",
        "saas-paid-launch-cutover-checklist",
        "saas-paid-launch-cutover-decision",
        "saas-paid-launch-runbook",
        "clean_new_account_declared",
        "new_account_oauth_authorization_gate",
        "post_publish_cockpit_cleanup_gate",
        "stripe_live_webhook_resilience",
        "stable_domain_oauth_cors_alignment",
        "charge_now_allowed",
        "platform_write_now_allowed",
        "生产队列与深度健康",
        "正式计费",
        "正式上线行动清单",
    ]:
        if marker not in module_js:
            return fail(f"settings module missing marker: {marker}")
    for marker in [
        "window.JiejingSettingsPanels?.renderQueueHealthPanel",
        "window.JiejingSettingsPanels?.renderBillingProviderPanel",
        "window.JiejingSettingsPanels?.renderCommercialLaunchActionPlanPanel",
        "window.JiejingSettingsPanels?.renderEdgeCutoverReadinessPanel",
        "saasEdgeCutoverPreflight",
        "/domain/edge-cutover-preflight",
        '"/domain/edge-cutover-preflight", { edge_cutover_preflight: state.saasEdgeCutoverPreflight || null }, 15000',
        "edge_cutover_preflight: state.saasEdgeCutoverPreflight || null",
        "saasPaidLaunchApprovalPacket",
        "/commercial/paid-launch-approval-packet",
        '"/commercial/paid-launch-approval-packet", { paid_launch_approval_packet: null }, 20000',
        '"/commercial/billing-domain-cutover-rehearsal", { billing_domain_cutover_rehearsal: null }, 15000',
        '"/commercial/launch-gate", { commercial_launch_gate: state.saasCommercialLaunchGate || null }, 20000',
        "paid_launch_approval_packet: state.saasPaidLaunchApprovalPacket || null",
        "refreshLaunchGate = true",
    ]:
        if marker not in app_js:
            return fail(f"app.js wrapper should delegate to settings module: {marker}")
    print("PASS jiejing_frontend_settings_module_split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
