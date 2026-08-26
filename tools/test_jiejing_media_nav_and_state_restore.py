#!/usr/bin/env python3
"""Static checks for the Jiejing merchant shell and media restore path."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def function_body(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles.css").read_text(encoding="utf-8")

    nav_start = app_html.index('<nav class="nav-list" id="navList"')
    nav_end = app_html.index("</nav>", nav_start)
    nav_html = app_html[nav_start:nav_end]
    nav_views = re.findall(r'data-view="([^"]+)"', nav_html)
    expected_nav_views = ["cockpit", "product", "bulk", "media", "confirm", "service", "activity", "connect"]
    if nav_views != expected_nav_views:
        return fail(f"left navigation should expose the merchant workflow plus account-scoped run records: {nav_views}")
    for removed_view in ["workflow", "report"]:
        if f'data-view="{removed_view}"' in nav_html:
            return fail(f"left navigation must not expose retired module: {removed_view}")
    for retained_view in ["view-workflow", "view-activity"]:
        if f'id="{retained_view}"' not in app_html:
            return fail(f"retired sidebar content must remain available for re-homing: {retained_view}")

    media_body = function_body(app_js, "renderMediaProjectTabs", "renderListingDraftGallery")
    for marker in [
        'restorePreservedViewMarkup("media", ".media-project-tabs")',
        "bindRestoredMediaStudioEvents()",
        "renderSaasMediaStudioStatus()",
    ]:
        if marker not in media_body:
            return fail(f"media workshop must restore preserved DOM before SaaS rendering: {marker}")
    for marker in [
        "function bindRestoredMediaStudioEvents",
        "function renderSaasMediaStudioStatus",
        "function renderSaasMediaGeneratedAssetsPanel",
        "function saasMediaAssetJobFailureDiagnostic",
        "private_media_source_asset_not_found",
        "private_media_source_asset_unavailable",
        "private_media_source_asset_scope_mismatch",
        "private_media_source_asset_expired",
        "private_media_source_asset_integrity_failed",
        "saasMediaAssetJobFailureDiagnostic(job)",
        "素材来源诊断：",
        "function syncSaasMediaProjectDraft",
        'data-media-saas-real="1"',
        "素材结果",
        "图片和视频脚本",
        "商家只需要看三件事：这张图用在哪里、能不能用、还缺什么",
        "saas-media-generated-assets",
        "saas-generated-assets-grid",
        'data-asset-preview="${escapeHtml(card.key)}"',
    ]:
        if marker not in app_js:
            return fail(f"media workshop missing real-state restore marker: {marker}")
    for merchant_visible_provider_copy in [
        "DeepSeek 负责想图，FAL 负责出图",
        "真正出主图、场景图、详情页图和视频封面时走 FAL 素材 provider",
        "function renderSaasMediaProviderPipeline",
    ]:
        if merchant_visible_provider_copy in app_js:
            return fail(f"media workshop must show generated assets, not provider explanation: {merchant_visible_provider_copy}")

    for marker in [
        "function normalizeSaasRecordStoreId",
        "function saasRecordStoreId",
        "function sortedSaasDataPackets",
        "function saasKnownStoreCandidates",
        "const latestPacketStoreId",
        "score += 240",
        "score += 35",
        "const official = storedPackets.find",
        "saasConnectionForStore(store)",
    ]:
        if marker not in app_js:
            return fail(f"store/packet restore should prefer authorized backend state over stale local state: {marker}")

    for marker in [
        "const ebayAuthorized = isSaasAuthorizedConnectionStatus",
        "不需要重新打开授权链接",
        'data-saas-action="plan-ebay-oauth" ${!hasSessionCandidate || ebayAuthorized ? "disabled" : ""}',
        'data-saas-action="plan-ebay-draft-oauth" ${!hasSessionCandidate || !ebayAuthorized || ebayDraftAuthorized ? "disabled" : ""}',
    ]:
        if marker not in app_js:
            return fail(f"settings must not prompt repeat eBay OAuth after authorization is restored: {marker}")

    if 'id="entryAuthCompany"' in index_html:
        return fail("entry login must not ask returning merchants for a store/company name")
    if "company_name: email.split(\"@\")[0]" not in index_html:
        return fail("registration should derive a placeholder company name without asking in the login form")
    for marker in [
        "markEntryOnboardingCompleted()",
        "function hasEntryOnboardingCompleted",
        "await loadEntryMerchantOnboarding()",
        "model?.progress?.preferences_saved",
        "openLoggedInExperience(activePath, { onboarded: true })",
    ]:
        if marker not in index_html:
            return fail(f"login restore must respect completed onboarding before reopening workbench: {marker}")

    for marker in [
        "saasLastCeoCommand",
        'ceoCommand: "jiejing_saas_ceo_command"',
        "function renderSaasCeoCommandConsole",
        "function handleSaasCeoCommandSubmit",
        "function buildSaasCeoCommand",
        "function renderSaasCeoModuleHandoffPanel",
        "function recordSaasCeoCommandSourceRecord",
        "function persistSaasCeoCommandToBackend",
        "function hydrateSaasCeoCommandFromBackend",
        "function backendSaasCeoCommandFromPayload",
        "saasLastCeoCommandPersistPromise",
        "saasLastCeoCommandHydratePromise",
        "coreCeoCommandMemory",
        "keepalive: true",
        "/merchant-ceo/commands",
        "merchant_ceo_command",
        "AI CEO 已接单",
        "saas-ceo-route-card",
        "saas-ceo-module-handoff",
        "handleSaasCeoCommandSubmit(text, { sourceAssetIds });",
    ]:
        if marker not in app_js:
            return fail(f"AI CEO command intake must persist and route real SaaS work: {marker}")
    service_body = function_body(app_js, "renderSaasServiceCenter", "renderConversations")
    if 'renderSaasCeoModuleHandoffPanel("service"' in service_body:
        return fail("service module should not render AI CEO handoff/status cards on the simplified daily surface")
    for marker in [
        "function renderSaasSettingsControlRoom",
        "function renderSaasSettingsSectionGroup",
        "saas-settings-control-room",
        "saas-settings-section-group",
        "日常状态",
        "来源与模型",
        "团队、记忆与风险",
    ]:
        if marker not in app_js + css:
            return fail(f"settings page must be grouped into a clear SaaS control room: {marker}")
    ceo_submit_body = function_body(app_js, "handleCeoFormSubmit", "bindCeoForm")
    if "if (isSaasPublicMvpMode())" not in ceo_submit_body:
        return fail("public SaaS AI CEO submit should use the real command routing path before legacy media demo routing")
    app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", app_html)
    index_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", index_html)
    if len(app_versions) != 1 or index_versions != [app_versions[0], app_versions[0]]:
        return fail("frontend entries must share one current versioned media UI bundle")
    for stale_asset_version in [
        "20260525-workflow-feedback-v1",
        "20260526-owner-publish-v1",
        "20260526-owner-publish-v2",
        "20260526-workflow-safety-v2",
        "20260526-readable-pages-v1",
        "20260526-media-fal-v1",
        "20260526-ai-ceo-media-v1",
        "20260526-ai-ceo-ui-v2",
        "20260526-ai-ceo-ui-v3",
        "20260527-realtime-search-v1",
        "20260527-global-ui-v1",
        "20260619-core-workbench-v1",
        "20260619-first-order-loop-v1",
        "20260619-confirmation-preflight-v1",
        "20260621-listing-ordered-flow-v14",
        "20260704-bulk-media-handoff-v20",
        "20260825-media-retry-confirm-v1",
        "20260825-listing-publish-truth-v1",
        "20260825-listing-media-restore-v1",
        "20260825-listing-media-restore-v2",
    ]:
        if stale_asset_version in app_html + index_html:
            return fail(f"frontend cache version must not keep stale asset after owner publish UI change: {stale_asset_version}")
    for marker in [
        'id="workflowFeedbackShell"',
        'id="workflowFeedbackToggle"',
        'id="workflowFeedbackDrawer"',
        "function buildSaasWorkflowFeedbackContext",
        "function submitSaasWorkflowFeedback",
        "function renderWorkflowFeedbackNodeControls",
        "product_improvement",
        "data-workflow-feedback-reason",
        "提交给 JIEJING 团队",
        "data-workflow-feedback-retry",
        'productFeedbackOutbox: "jiejing_saas_product_feedback_outbox_v1"',
        'productFeedbackReceipts: "jiejing_saas_product_feedback_receipts_v1"',
        'productFeedbackMigration: "jiejing_saas_product_feedback_migration_v1"',
        "function saasProductFeedbackStorageScope",
        "function migrateLegacySaasProductFeedback",
        "function flushSaasProductFeedbackOutbox",
        "function deliverSaasProductFeedbackItem",
        "saasProductFeedbackLiveIdentityConfirmed",
        "saasProductFeedbackLiveIdentityGeneration",
        "function markSaasProductFeedbackLiveIdentity",
        "function saasProductFeedbackContainsSecret",
        "function validateSaasProductFeedbackServerReceipt",
        "const saasProductFeedbackFlushPromises = new Map()",
        'delivery_state: "needs_edit"',
        'delivery_state: "conflict"',
        "next_retry_at",
        "processed_fingerprints",
        "next_index",
        "data-workflow-feedback-edit",
        "data-workflow-feedback-discard",
        'saasFetchWithTimeout(\n      "/product-feedback"',
        'status === 400',
        'status === 409',
        'status === 401 || status === 429 || status === 503',
    ]:
        if marker not in app_js + app_html + css:
            return fail(f"workflow feedback must be folded into the app flow, not a sidebar module: {marker}")
    feedback_start = app_js.index("function submitSaasWorkflowFeedback")
    feedback_end = app_js.index("function handleWorkflowFeedbackButton", feedback_start)
    feedback_body = app_js[feedback_start:feedback_end]
    if "recordSaasWorkflowFeedbackToMemory(record)" in feedback_body or "addCeoMessage(summary" in feedback_body:
        return fail("workflow feedback must go to product feedback, not AI CEO memory or chat replay")
    if "state.saasMerchantFeedback" in feedback_body or "persistSaasMerchantFeedback" in feedback_body:
        return fail("product improvement delivery must not mutate useful/not_useful/remember_rule merchant memory")
    if 'optionalSaasFetchFast("/product-feedback"' in app_js or "optionalSaasFetchFast('/product-feedback'" in app_js:
        return fail("product feedback writes must use the abortable authenticated timeout path")
    if "body.saas-public-mvp .workflow-feedback-shell {\n    display: none;" in css:
        return fail("mobile public workbench must keep the product feedback entry reachable")
    if 'data-view="feedback"' in nav_html or "意见箱" in nav_html:
        return fail("workflow feedback must not become an eighth sidebar module")
    for forbidden in ["state.saasToken", "refresh_token:", "api_key:", "model_key:"]:
        feedback_start = app_js.index("function buildSaasWorkflowFeedbackContext")
        feedback_end = app_js.index("function saasCeoCommandStorageScope", feedback_start)
        feedback_body = app_js[feedback_start:feedback_end]
        if forbidden in feedback_body:
            return fail(f"workflow feedback context must not capture secrets: {forbidden}")
    nav_start_public = index_html.index('<div class="navlinks"')
    nav_end_public = index_html.index("</div>", nav_start_public)
    public_nav = index_html[nav_start_public:nav_end_public]
    if 'href="./index.html?auth=login">AI CEO 工作台</a>' in public_nav:
        return fail("public AI CEO workbench nav must not jump directly to the login modal")
    for marker in (
        'href="#outcome">草稿内容</a>',
        'href="#logic">使用流程</a>',
        'href="#trust">安全边界</a>',
        'href="#paths">套餐方案</a>',
    ):
        if marker not in public_nav:
            return fail(f"public merchant navigation must retain the simplified homepage sections: {marker}")
    if 'href="./index.html?auth=register"' in index_html or 'href="./index.html?auth=login"' in index_html:
        return fail("public homepage must not use URL parameters to auto-open login/register")
    if "function openWorkbenchOrAuth" not in index_html or "function hasEntrySaasSessionCandidate" not in index_html:
        return fail("public workbench entry should open app when session exists and otherwise wait for an explicit login click")
    auth_function_start = index_html.index("function openAuthModalFromUrl")
    auth_function_end = index_html.index("function closeNextStepModal", auth_function_start)
    auth_function = index_html[auth_function_start:auth_function_end]
    if "openNextStepModal" in auth_function:
        return fail("old auth query URLs must not auto-open the login modal")
    for marker in [
        'id="ai-ceo-workbench"',
        "真实 SaaS 边界",
        "官方只读连接或资料导入",
        "AI 连接",
        "来源记录",
        "决策中心",
        'target.searchParams.set("view", activePlan === "free" ? "cockpit" : "connect")',
    ]:
        if marker not in index_html:
            return fail(f"public AI CEO workbench section missing SaaS-ready marker: {marker}")

    print("PASS jiejing_media_nav_and_state_restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
