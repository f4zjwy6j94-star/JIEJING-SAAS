#!/usr/bin/env python3
"""Static checks for Jiejing frontend staging API configuration."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    styles_css = (ROOT / "styles.css").read_text(encoding="utf-8")
    privacy_html = (ROOT / "privacy.html").read_text(encoding="utf-8")
    terms_html = (ROOT / "terms.html").read_text(encoding="utf-8")
    risk_html = (ROOT / "risk-disclosure.html").read_text(encoding="utf-8")

    if "document.write(" in app_js:
        return fail("frontend must not use document.write for report export or public rendering")
    frontend_asset_version = "20260624-first-run-empty-v1"
    for expected_asset in [
        f"./app.js?v={frontend_asset_version}",
        f"./styles.css?v={frontend_asset_version}",
    ]:
        if expected_asset not in index_html + app_html:
            return fail(f"frontend entry files must bust owner publish cache with {expected_asset}")
    for stale_asset_version in [
        "20260525-workflow-feedback-v1",
        "20260526-owner-publish-v1",
        "20260526-owner-publish-v2",
        "20260526-workflow-safety-v2",
        "20260526-readable-pages-v1",
        "20260526-media-fal-v1",
        "20260526-ai-ceo-media-v1",
        "20260526-ai-ceo-ui-v2",
        "20260527-realtime-search-v1",
        "20260527-global-ui-v1",
        "20260619-core-workbench-v1",
        "20260619-first-order-loop-v1",
        "20260619-confirmation-preflight-v1",
        "20260620-onboarding-control-v3",
        "20260620-billing-guardrail-v1",
        "20260620-billing-rehearsal-v2",
        "20260620-owner-cutover-checklist-v1",
        "20260621-final-rehearsal-record-v1",
        "20260621-prelaunch-report-v1",
        "20260621-brand-overlap-v1",
        "20260621-interactive-command-v1",
        "20260621-orbit-command-v1",
        "20260621-minimal-ai-ceo-v1",
        "20260621-minimal-listing-v1",
        "20260621-listing-composer-v1",
        "20260621-core-modules-clean-flow-v9",
        "20260621-core-modules-clean-flow-v11",
        "20260621-listing-input-clarity-v12",
        "20260621-listing-full-form-open-v13",
        "20260621-listing-ordered-flow-v14",
        "20260622-listing-form-prefill-groups-v15",
        "20260623-settings-simplified-v2",
        "20260623-settings-merchant-v3",
        "20260623-settings-child-clean-v4",
        "20260623-settings-five-clean-v5",
        "20260623-ai-ceo-routing-v1",
        "20260624-ai-ceo-minimal-v2",
        "20260624-clean-core-workflows-v1",
    ]:
        if stale_asset_version in index_html + app_html:
            return fail(f"frontend entry files still reference stale asset version: {stale_asset_version}")
    for forbidden_brand in [
        "捷境 Jiejing",
        "Jiejing / 捷境",
        "Jiejing AI CEO",
        "Jiejing Merchant",
    ]:
        if forbidden_brand in index_html + app_html + privacy_html:
            return fail(f"public static pages must use uppercase JIEJING brand: {forbidden_brand}")
    for expected_brand in [
        "捷境 JIEJING",
        "JIEJING / 捷境",
        "JIEJING AI CEO",
    ]:
        if expected_brand not in index_html + app_html + privacy_html:
            return fail(f"public static pages missing uppercase JIEJING brand marker: {expected_brand}")
    for expected_runtime_brand in [
        r'[/\bJingjing\b/g, "JIEJING"]',
        r'[/\bJiejing\b/g, "JIEJING"]',
        "JIEJING AI CEO eBay SaaS",
        "JIEJING SaaS status",
    ]:
        if expected_runtime_brand not in app_js:
            return fail(f"runtime UI missing uppercase JIEJING brand guard: {expected_runtime_brand}")
    for expected_interaction_marker in [
        "--tilt-x",
        "--core-drift-x",
        ".hero-ops-board article:hover",
        ".hero-ops-board article",
        ".flow-line",
        "border-radius: 50%",
    ]:
        if expected_interaction_marker not in index_html:
            return fail(f"homepage AI CEO command-room interaction marker missing: {expected_interaction_marker}")
    if 'localStorage.getItem("jiejing_saas_backend_token")' in app_html:
        return fail("public app entry must not accept legacy localStorage bearer tokens")
    for forbidden_frontend_secret in [
        "jiejing-demo-password",
        "demo@jiejing.local",
    ]:
        if forbidden_frontend_secret in app_js + app_html + index_html:
            return fail(f"public frontend must not carry default demo credential: {forbidden_frontend_secret}")
    for relative_path in [
        "deploy/Caddyfile.public-staging",
        "deploy/nginx.public-staging.conf",
        "deploy/jiejing-route-a-edge.env.example",
        "deploy/jiejing-saas.infra.env.example",
        "deploy/jiejing-saas.tencent-managed.env.example",
        "tools/jiejing_deploy_channel_doctor.py",
        "tools/jiejing_staging_deploy.py",
        "tools/jiejing_deploy_frontend_staging_with_key.ps1",
        "tools/jiejing_prepare_stable_deploy_key.ps1",
    ]:
        active_text = (ROOT / relative_path).read_text(encoding="utf-8")
        if "42.194.158.47" in active_text or "mentioned-shake-inter-critical.trycloudflare.com" in active_text:
            return fail(f"active deploy config still points at retired Guangzhou staging route: {relative_path}")

    compose_https = (ROOT / "deploy/docker-compose.public-https-staging.yml").read_text(encoding="utf-8")
    deploy_script = (ROOT / "tools/jiejing_deploy_frontend_staging_with_key.ps1").read_text(encoding="utf-8")
    prelaunch_runbook = (ROOT / "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md").read_text(encoding="utf-8")
    if "../privacy.html:/usr/share/nginx/html/privacy.html:ro" not in compose_https:
        return fail("public HTTPS staging frontend must serve privacy.html for eBay OAuth developer configuration")
    for mounted_page in [
        "../terms.html:/usr/share/nginx/html/terms.html:ro",
        "../risk-disclosure.html:/usr/share/nginx/html/risk-disclosure.html:ro",
    ]:
        if mounted_page not in compose_https:
            return fail(f"public HTTPS staging frontend must serve legal page: {mounted_page}")
    if "jiejing-privacy.html" not in deploy_script:
        return fail("frontend deploy script must sync privacy.html with other static frontend assets")
    for deploy_page in ["jiejing-terms.html", "jiejing-risk-disclosure.html"]:
        if deploy_page not in deploy_script:
            return fail(f"frontend deploy script must sync legal page: {deploy_page}")
    for marker in [
        'JIEJING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED: "true"',
        'JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_TEST_DATA_GOVERNANCE_REVIEWED: "true"',
    ]:
        if marker not in compose_https:
            return fail(f"public HTTPS staging compose missing prelaunch evidence flag: {marker}")
    for marker in [
        "Do not create live Stripe Checkout sessions.",
        "Do not start or repeat eBay OAuth.",
        "Do not delete smoke data automatically.",
        "Access logs must not record request bodies.",
        "High-cost API groups are rate-limited.",
        "Cleanup is not automatic.",
    ]:
        if marker not in prelaunch_runbook:
            return fail(f"prelaunch hardening runbook missing marker: {marker}")
    for marker in [
        "隐私与数据边界说明",
        "当前环境用于受控 beta 和上线前演练，不是正式公开收费上线状态",
        "secret_ref",
        "服务条款",
        "风险披露与确认中心边界",
    ]:
        if marker not in privacy_html:
            return fail(f"privacy page missing staging data-boundary marker: {marker}")
    for marker in [
        "捷境服务条款",
        "当前捷境仍不是正式公开收费上线状态",
        "禁止自动执行的动作",
        "测试数据默认只标记和报告，不自动删除",
    ]:
        if marker not in terms_html:
            return fail(f"terms page missing launch-boundary marker: {marker}")
    for marker in [
        "风险披露与确认中心边界",
        "所有高风险动作都必须由商家或授权管理员确认",
        "红色阻断",
        "绿色只表示当前证据满足系统预检",
    ]:
        if marker not in risk_html:
            return fail(f"risk disclosure page missing confirmation-boundary marker: {marker}")

    if 'runtimeApiBase: "http://127.0.0.1:8765"' in app_js:
        return fail("runtime API base is still hardcoded in initial state")
    if 'saasApiBase: "http://127.0.0.1:8788"' in app_js:
        return fail("SaaS API base is still hardcoded in initial state")
    for marker in [
        "resolveJiejingApiBase",
        "window.JIEJING_CONFIG",
        "__JIEJING_CONFIG__",
        "jiejing_saas_api_base",
        "jiejing_runtime_api_base",
        "jiejing-saas-api-base",
        "jiejing-runtime-api-base",
        "jiejing-saas-operator-bootstrap",
        "inferJiejingSameOriginApiBase",
        "defaultJiejingDemoBootstrapEnabled",
        "saasDemoBootstrapEnabled",
        "当前公网页面需要已有捷境账号会话",
        "Public auth gate",
        "/secret-refs?store_id=",
        "OAuth Status",
        "托管凭证",
        'optionalSaasFetchFast(`/data-packets?platform=ebay&limit=5`',
        "function getLatestSaasDataPacketRecord",
        "function saasKnownStoreCandidates",
        'saasFetch("/reports?limit=24")',
        'saasFetch("/confirmations?limit=40")',
        "renderSaasEbaySyncStatusPanel",
        "renderSaasAiCeoOutputPanel",
        "renderSaasConfirmPanel",
        "saasRealBackendBindingStatus",
        "真实 API 来源",
        "saasWorkbenchReportDetailMarkup",
        "saasWorkbenchConfirmationDetailMarkup",
        "saas-ai-report-detail",
        "saas-confirm-detail",
        "shouldShowLegacyDemoControls",
        "blockLegacyDemoPublishAction",
        "isPublicJiejingOrigin",
        "renderSaasWorkbenchTruthPanel",
        "renderSaasMerchantEvidencePanel",
        "saasModelValueGate",
        "Market Report",
        "Listing Package",
        "真实写入",
        "renderSaasLoginCard",
        "data-saas-login-card",
        "function renderSaasMerchantExecutiveCockpit",
        "saas-executive-cockpit",
        "saas-cockpit-risk-queue",
        "saas-executive-evidence-rail",
        "frontend_never_gets_token",
        "function saasBackendPublishImpact",
        "function saasBackendPublishDecisionGate",
        "function renderSaasPublishCommandSummaryPanel",
        "saas-backend-preflight-route",
        "saas-publish-command-summary",
        "confirmation_required_no_direct_write",
        "register-session",
        "product_evidence",
        "latest_ebay_packet_id",
        "refreshSaasPublicReadiness",
        "refreshSaasPublicReadiness({ render: true })",
        "hasSaasProtectedSessionCandidate",
        "shouldAttachSaasBearerToken",
        "purgeLegacySaasStoredBearerToken",
        "operatorBootstrapEmail",
        "operatorBootstrapPassword",
        "resetSaasProtectedWorkbenchState",
        "saasLastPublicRefreshSkippedProtectedFetch",
        "shouldFetchDirectRuntimeApi",
        "refreshSaasEbayDiagnostics",
        "isSaasEbayReadOnlyAuthorized",
        "saasEbayReadOnlyResourcePayload",
        "eBay 只读授权已经完成；不会再次生成授权链接",
        "saasAiCeoStageCoverage",
        "saas-ai-stage-strip",
        "freshness.status",
        "route_health",
        "currentSaasEbayCallbackUrl",
        "copy-ebay-callback-url",
        "eBay Developer callback 必须配置为",
    ]:
        if marker not in app_js + app_html:
            return fail(f"missing frontend staging config marker: {marker}")
    for endpoint in ["/model/value-gate", "/commercial/launch-gate", "/backup/plan"]:
        if (
            f'saasFetch("{endpoint}")' not in app_js + app_html
            and f'optionalSaasFetch("{endpoint}"' not in app_js + app_html
            and f'optionalSaasFetchFast("{endpoint}"' not in app_js + app_html
        ):
            return fail(f"missing frontend staging config marker: {endpoint} fetch")
    for marker in [
        "cursorGlow",
        "signalCanvas",
        "merchant-guide",
        "entryModeGrid",
        "pointermove",
        "openLoggedInExperience",
        "./app.html",
    ]:
        if marker not in index_html:
            return fail(f"missing interactive homepage/onboarding marker: {marker}")
    if "体验流程会用倒流香炉跑一遍" in index_html:
        return fail("homepage onboarding copy must not route real testing through a fixed sample product")
    for stale_public_copy in [
        "主页、向导和工作台只讲同一条",
        "不是通用 ERP，也不是通用 Agent 市场",
    ]:
        if stale_public_copy in index_html + app_html:
            return fail(f"public product copy should avoid abstract internal positioning: {stale_public_copy}")
    for owner_grade_copy in [
        "从一个商品目标开始",
        "先把 eBay 真实经营做深，再把同一套经营能力扩展到 Amazon",
    ]:
        if owner_grade_copy not in index_html + app_html:
            return fail(f"public product copy should explain the operating outcome: {owner_grade_copy}")
    if "真实工作流以你的 eBay 只读数据和商家资料为准" not in index_html:
        return fail("homepage onboarding copy should point real testing at merchant eBay read-only data")
    for onboarding_control_marker in [
        "onboardingLaunchMapMarkup",
        "onboardingControlStripMarkup",
        "onboardingChoiceContextMarkup",
        "onboardingSummaryMetricsMarkup",
        "onboardingLaunchReadinessMarkup",
        "onboarding-launch-map",
        "onboarding-control-strip",
        "onboarding-choice-context",
        "onboarding-summary-metrics",
        "onboarding-summary-launch",
        "官方只读优先",
        "可跳过授权继续",
        "确认中心兜底",
        "首单上线检查",
    ]:
        if onboarding_control_marker not in app_js + app_html + styles_css:
            return fail(f"missing onboarding control-room marker: {onboarding_control_marker}")
    for billing_guardrail_marker in [
        "renderSaasMerchantBillingGuardrailPanel",
        "saasMerchantBillingGuardrailState",
        "saasMerchantBillingStatusPill",
        "saas-merchant-billing-guardrail",
        "subscription_quota_shutdown_state",
        "billing_subscription_not_active",
        "blocks_metered_work_when_inactive",
        "creates_checkout_session=false",
        "charge_now_allowed=false",
        "frontend_gets_payment_secret=false",
        "高成本任务暂停",
        "查看历史和确认中心",
        "no_real_charge_rehearsal_ui_v2",
        "latest_no_charge_billing_event",
        "saas-merchant-billing-rehearsal",
        "saas-merchant-billing-rehearsal-actions",
        'data-billing-test-action="${escapeHtml(action)}"',
        '["activate",',
        '["invoice_paid",',
        '["payment_failed",',
        '["cancel",',
        "creates_real_checkout_session=false",
        "calls_stripe_api=false",
        "triggers_real_charge=false",
        "owner_approval_required_for_reenable=true",
        "billing_plan: state.saasBillingPlan || null",
        "state.saasBillingUsage = snapshot.billing_usage || state.saasBillingUsage || null",
        "statusPills.push(saasMerchantBillingStatusPill())",
    ]:
        if billing_guardrail_marker not in app_js + app_html + styles_css:
            return fail(f"missing merchant billing guardrail marker: {billing_guardrail_marker}")
    refresh_start = app_js.index("async function refreshSaasState")
    refresh_end = app_js.index("async function refreshSaasPublicReadiness", refresh_start)
    refresh_body = app_js[refresh_start:refresh_end]
    if "const canFetchProtectedState = hasSaasProtectedSessionCandidate();" not in refresh_body:
        return fail("refreshSaasState must check for a real session or explicit operator bootstrap before protected reads")
    guard_index = refresh_body.find("if (!canFetchProtectedState)")
    store_fetch_index = refresh_body.find("const store = await ensureSaasDemoStoreAndConnection();")
    if guard_index < 0 or store_fetch_index < 0 or guard_index > store_fetch_index:
        return fail("refreshSaasState must skip protected store/report reads before ensuring a store")
    for endpoint in [
        "live-read-plan",
        "http-client-dry-run",
        "credential-preflight",
    ]:
        if endpoint in refresh_body and 'method: "POST"' in refresh_body:
            return fail(f"default refreshSaasState must not POST {endpoint}; diagnostics must be explicit")
    for forbidden in [
        "saas_frontend_demo_input",
        "Front-end demo approval. ExecutionService remains demo/no-platform-write.",
        "public_demo: true",
    ]:
        if forbidden in app_js:
            return fail(f"SaaS production path still carries demo-only marker: {forbidden}")
    if "https://api.ebay.com/oauth/api_scope/sell.finances" not in app_js:
        return fail("frontend eBay OAuth scopes must include sell.finances for the first read-only packet")
    if "saasLatestOAuthUrl" not in app_js or "Open eBay OAuth" not in app_js or 'target="_blank"' not in app_js:
        return fail("frontend should retain a clickable eBay OAuth authorization URL")
    if "API Base" not in app_js:
        return fail("frontend should surface configured API bases in the SaaS backend panel")
    if '["blocked", "pending", "published"].includes(state.publishFlow.status) &&\n    shouldShowLegacyDemoControls()' not in app_js:
        return fail("legacy publish confirmation card must be hidden from real SaaS merchant mode")
    if "if (blockLegacyDemoPublishAction()) return;" not in app_js:
        return fail("legacy demo publish actions must be blocked in real SaaS merchant mode")
    if 'start === "landing"' not in app_js or 'params.get("entry") === "1"' not in app_js:
        return fail("public workbench default must keep an explicit marketing-page override")
    if "(isPublicJiejingOrigin() && !start && !explicitMarketingEntry)" in app_js:
        return fail("public root must not auto-open the workbench; homepage must be the default")
    if 'start === "app" ||\n    params.get("onboarded") === "1"' not in app_js:
        return fail("workbench must remain available through an explicit app/onboarded route")
    if 'saasFetch("/auth/register"' not in app_js:
        return fail("workbench must support real SaaS account registration instead of a demo-only auth path")
    if "state.saasReadiness = null" in app_js:
        return fail("public readiness evidence should survive session-required failures")
    workbench_start = app_js.index("function renderSaasMerchantWorkbenchPanel")
    workbench_end = app_js.index("function renderSaasMerchantPublicMvpPanel", workbench_start)
    workbench_body = app_js[workbench_start:workbench_end]
    public_mvp_start = app_js.index("function renderSaasMerchantPublicMvpPanel")
    public_mvp_end = app_js.index("function renderSaasWorkbenchTruthPanel", public_mvp_start)
    public_mvp_body = app_js[public_mvp_start:public_mvp_end]
    for advanced_panel in [
        "renderSaasMerchantProviderHubPanel(ctx)",
        "renderSaasMerchantPermissionPanel()",
        "renderSaasMerchantIpRiskPanel()",
        "renderSaasMerchantMemoryPanel()",
        "renderSaasMerchantModelProviderPanel(ctx)",
    ]:
        if advanced_panel in workbench_body or advanced_panel in public_mvp_body:
            return fail(f"merchant workbench should keep advanced/settings panel out of the daily MVP path: {advanced_panel}")
    settings_start = app_js.index("function renderSaasConnectCenter")
    settings_end = app_js.index("function renderConnect", settings_start)
    settings_body = app_js[settings_start:settings_end]
    for settings_panel in [
        "renderSaasMerchantModelProviderPanel(ctx)",
        "renderSaasCostAndRunLedgerPanel()",
        "renderSaasMerchantPermissionPanel()",
        "renderSaasMerchantIpRiskPanel()",
        "renderSaasMerchantMemoryPanel()",
        "renderSaasMerchantProviderHubPanel(ctx)",
    ]:
        if settings_panel not in settings_body:
            return fail(f"settings center must retain advanced SaaS configuration panel: {settings_panel}")
    runtime_start = app_js.index("async function refreshRuntimeState")
    runtime_end = app_js.index("async function createRuntimeRunFromSaas", runtime_start)
    runtime_body = app_js[runtime_start:runtime_end]
    if "if (!shouldFetchDirectRuntimeApi())" not in runtime_body:
        return fail("public workbench must not auto-fetch direct Runtime API before an operator/local route")
    for visible_residue in [
        "演示版",
        "演示估算",
        "演示草稿",
        "演示批次",
        "Demo 生成",
        "内测试用",
        "演示样例",
        "演示口径",
        "演示状态",
        "演示字段",
        "演示目标",
    ]:
        if visible_residue in app_html:
            return fail(f"workbench HTML still carries visible demo residue: {visible_residue}")
    for forbidden_marker in [
        "workflow-demo-grid",
        "mockPreview",
        "bulk-demo-note",
        "mediaGenerateImagesDemo",
    ]:
        if forbidden_marker in app_js + app_html:
            return fail(f"public UI still carries old demo/mock DOM marker: {forbidden_marker}")
    print("PASS jiejing_frontend_staging_config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
