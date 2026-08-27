#!/usr/bin/env python3
"""Regression for the first settings-page split out of app.js."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "app.html"
APP_JS = ROOT / "app.js"
INDEX_HTML = ROOT / "index.html"
MODULE = ROOT / "assets" / "jiejing-settings-panels.js"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_html = APP_HTML.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    index_html = INDEX_HTML.read_text(encoding="utf-8")
    module_js = MODULE.read_text(encoding="utf-8")
    module_marker = "./assets/jiejing-settings-panels.js?v=20260822-public-commercial-release-v105"
    billing_panel_start = module_js.index("function renderBillingProviderPanel")
    billing_panel_end = module_js.index("\n  function ", billing_panel_start + 1)
    merchant_billing_panel = module_js[billing_panel_start:billing_panel_end]
    if module_marker in app_html:
        return fail("app.html must not eagerly load the settings-only module")
    if "jiejing-settings-panels.js" in index_html:
        return fail("public homepage must not prefetch the settings-only module")
    for lazy_marker in [
        f'const JIEJING_SETTINGS_PANELS_SRC = "{module_marker}";',
        "let jiejingSettingsPanelsLoadPromise = null;",
        "function ensureJiejingSettingsPanelsLoaded()",
        'script.dataset.jiejingSettingsPanels = "lazy";',
        "script.async = true;",
        "jiejingSettingsPanelsLoadPromise = null;",
    ]:
        if lazy_marker not in app_js:
            return fail(f"settings module lazy loader missing marker: {lazy_marker}")
    render_connect_start = app_js.index("function renderConnect()")
    render_connect_end = app_js.index("function riskText", render_connect_start)
    render_connect = app_js[render_connect_start:render_connect_end]
    for lazy_settings_entry_marker in [
        'if (state.view === "connect" && !window.JiejingSettingsPanels)',
        "ensureJiejingSettingsPanelsLoaded()",
        'if (state.view === "connect") renderConnect();',
    ]:
        if lazy_settings_entry_marker not in render_connect:
            return fail(f"settings view must finish lazy loading before rerender: {lazy_settings_entry_marker}")
    for marker in [
        "global.JiejingSettingsPanels",
        "renderBillingProviderPanel",
        "订阅与付款",
        "当前模式",
        "续费 / 取消",
        "AI / 素材用量",
        "欠费保护",
        "在线付款开放",
        "商家主动创建订单并微信扫码",
        "页面不展示任何支付密钥",
        "当前仅展示试用和订阅说明",
        "merchant_billing_copy_public_safe_v1",
    ]:
        if marker not in module_js:
            return fail(f"merchant settings module missing marker: {marker}")
    for marker in [
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
        "wechat_pay_native_cutover",
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
        "wechat_pay_signed_callback_resilience",
        "stable_domain_oauth_cors_alignment",
        "charge_now_allowed",
        "platform_write_now_allowed",
        "生产队列与深度健康",
        "正式上线行动清单",
    ]:
        if marker in module_js:
            return fail(f"merchant settings module contains internal marker: {marker}")
    for marker in [
        "billing live cutover",
        "stripe_billing_live_cutover_matrix",
        "stripe_domain_cutover_rehearsal",
        "billing_test_event_console",
        "no-charge test flow",
        "Billing provider",
        "Customer Portal",
        "Webhook",
        "provider cutover",
        "正式商户支付",
        "正式收款",
        "内测订阅",
        "公开收费入口",
        "大陆收款",
        "主体资料",
        "个人收款码",
        "测试付款",
        "审计证据",
        "模型 key",
        "eBay OAuth",
        "_renderBillingTestRehearsal(",
        "_renderSubscriptionQuotaShutdownClosure(",
        "_renderBillingDomainCutoverRehearsal(",
        "_renderBillingLiveCutoverStep(",
    ]:
        if marker in merchant_billing_panel:
            return fail(f"merchant billing panel exposes internal marker: {marker}")
    if "window.JiejingSettingsPanels?.renderBillingProviderPanel" not in app_js:
        return fail("app.js must continue to delegate merchant billing to its merchant settings module")
    for marker in [
        "window.JiejingSettingsPanels?.renderQueueHealthPanel",
        "window.JiejingSettingsPanels?.renderCommercialLaunchActionPlanPanel",
        "window.JiejingSettingsPanels?.renderEdgeCutoverReadinessPanel",
        "saasEdgeCutoverPreflight",
        "/owner/edge-cutover-preflight",
        '"/owner/edge-cutover-preflight", { edge_cutover_preflight: state.saasEdgeCutoverPreflight || null }, 15000',
        "edge_cutover_preflight: state.saasEdgeCutoverPreflight || null",
        "saasPaidLaunchApprovalPacket",
        "/owner/paid-launch-approval-packet",
        "mainland_payment_cutover",
        '`/commercial/launch-gate?store_id=${encodeURIComponent(store.store_id)}`, { commercial_launch_gate: state.saasCommercialLaunchGate || null }, 20000',
        "paid_launch_approval_packet: state.saasPaidLaunchApprovalPacket || null",
        "refreshLaunchGate = true",
    ]:
        if marker in app_js:
            return fail(f"merchant app must not delegate to internal settings control: {marker}")
    for retired in (
        "/owner/billing-domain-cutover-rehearsal",
        "/commercial/billing-domain-cutover-rehearsal",
        "/owner/billing-provider-evidence-register",
        "/commercial/billing-provider-evidence-register",
    ):
        if retired in app_js:
            return fail(f"current Settings flow must not fetch retired Stripe launch truth: {retired}")
    print("PASS jiejing_frontend_settings_module_split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
