#!/usr/bin/env python3
"""Static checks for Jiejing frontend staging API configuration."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


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
    refund_html = (ROOT / "refund-policy.html").read_text(encoding="utf-8")
    support_html = (ROOT / "support.html").read_text(encoding="utf-8")
    risk_html = (ROOT / "risk-disclosure.html").read_text(encoding="utf-8")

    if "document.write(" in app_js:
        return fail("frontend must not use document.write for report export or public rendering")
    if "onclick=" in index_html:
        return fail("public homepage must bind actions in script instead of inline event handlers")
    frontend_asset_version = "20260803-product-feedback-v1"
    app_js_asset_version = "20260814-ebay-inventory-location-v11"
    for expected_asset in [
        f"./app.js?v={app_js_asset_version}",
        f"./styles.css?v={frontend_asset_version}",
    ]:
        if expected_asset not in index_html + app_html:
            return fail(f"frontend entry files must bust owner publish cache with {expected_asset}")
    if f"./app.js?v={app_js_asset_version}" not in app_html or f"./app.js?v={app_js_asset_version}" not in index_html:
        return fail("both public and workbench entry files must reference the current app.js cache version")
    app_html_app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", app_html)
    index_html_app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", index_html)
    if app_html_app_versions != [app_js_asset_version]:
        return fail("workbench entry must contain exactly one current app.js cache version")
    if index_html_app_versions != [app_js_asset_version, app_js_asset_version]:
        return fail("public entry prefetch and lazy preload must both use the current app.js cache version")
    if "./app.js?v=20260810-safe-revise-confirmation-v1" in index_html + app_html:
        return fail("frontend entry files must not retain the stale pre-clock-skew app.js cache version")
    if "./app.js?v=20260812-ebay-oauth-clock-skew-v2" in index_html + app_html:
        return fail("frontend entry files must not retain the stale pre-terminal-recovery app.js cache version")
    if "./app.js?v=20260812-ebay-oauth-terminal-recovery-v3" in index_html + app_html:
        return fail("frontend entry files must not retain the stale single-terminal OAuth recovery cache version")
    if "./app.js?v=20260812-ebay-oauth-terminal-history-v4" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-sync-confirmation app.js cache version")
    if "./app.js?v=20260812-ebay-readonly-sync-confirmation-v5" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-listing-product-gate app.js cache version")
    if "./app.js?v=20260812-listing-concrete-product-gate-v6" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-confirmation-core-load app.js cache version")
    if "./app.js?v=20260813-confirmation-core-load-v7" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-draft-entry app.js cache version")
    if "./app.js?v=20260813-unpublished-draft-entry-v8" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-server-clock draft OAuth cache version")
    if "./app.js?v=20260814-server-clock-draft-oauth-v9" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-resumable-draft-oauth cache version")
    if "./app.js?v=20260814-draft-oauth-resume-v10" in index_html + app_html:
        return fail("frontend entry files must not retain the pre-inventory-location cache version")
    if "./app.js?v=20260803-product-feedback-v1" in index_html + app_html:
        return fail("frontend entry files must not retain the stale app.js cache version")
    for stale_asset_version in [
        "20260802-merchant-onboarding-v2",
        "20260802-merchant-onboarding-v1",
        "20260715-billing-recovery-renewal-v101",
        "20260715-listing-us-title-v98",
        "20260715-listing-copy-boundary-v97",
        "20260715-listing-copy-boundary-v96",
        "20260714-ebay-draft-save-v95",
        "20260712-publish-receipt-v75",
        "20260711-account-chat-sync-v48",
        "20260711-account-chat-sync-v47",
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
        "20260624-first-run-empty-v1",
        "20260624-bulk-media-v1",
        "20260624-confirm-v2",
        "20260624-settings-v1",
        "20260624-ceo-route-v2",
        "20260625-home-settings-v1",
        "20260625-billing-clarity-v2",
        "20260625-first-day-v3",
        "20260625-ai-ceo-pending-v4",
        "20260629-home-intents-v1",
        "20260629-onboarding-guard-v1",
        "20260629-onboarding-lite-v1",
        "20260701-payment-review-brief-v1",
        "20260701-media-asset-review-ui-v1",
        "20260702-merchant-entry-copy-v1",
        "20260702-merchant-subscription-request-v1",
        "20260702-internal-access-boundary-v1",
        "20260702-ai-ceo-route-card-v2",
        "20260710-ai-ceo-reliability-v34",
        "20260710-model-connection-v38",
        "20260711-ai-response-v39",
        "20260711-ai-response-v40",
        "20260711-product-context-v41",
        "20260711-actionable-report-v42",
        "20260711-legacy-report-recovery-v43",
        "20260711-concrete-import-v44",
        "20260711-media-project-v45",
        "20260711-account-chat-sync-v46",
        "20260510-ebay-policy-v1",
    ]:
        if stale_asset_version in index_html + app_html:
            return fail(f"frontend entry files still reference stale asset version: {stale_asset_version}")
    if 'document.documentElement.classList.remove("app-direct-start", "saas-public-direct-start")' not in app_js:
        return fail("returning from the workbench logo to the homepage must clear direct-start shell classes")
    for app_boot_guard in [
        'document.documentElement.classList.add("app-start-requested")',
        "html.app-start-requested:not(.app-ready) #entryShell",
        "html.app-start-requested:not(.app-ready) #appBootLoading[hidden]",
        "正在打开捷境工作台",
        'document.documentElement.classList.add("app-ready")',
    ]:
        if app_boot_guard not in app_html + app_js:
            return fail(f"app start must hide legacy entry shell before JS boot completes: {app_boot_guard}")
    if f'const JIEJING_SITE_VERSION = "{frontend_asset_version}"' not in index_html:
        return fail("public homepage must expose the current JIEJING site version marker")
    for logo_marker in [
        "width: 56px;",
        "height: 56px;",
        "width: 46px;",
        "height: 46px;",
        'center / 118% no-repeat',
    ]:
        if logo_marker not in index_html:
            return fail(f"public homepage logo must stay enlarged and centered: {logo_marker}")
    if "width: 50px;" not in styles_css or "height: 50px;" not in styles_css or 'center / 118% no-repeat' not in styles_css:
        return fail("SaaS brand mark must stay enlarged and centered with the JIEJING app icon")
    for homepage_intent_marker in [
        'data-home-intent-strip="homepage_ai_ceo_intents_v1"',
        'data-home-intent="listing"',
        'data-home-intent="bulk"',
        'data-home-intent="service"',
        'data-home-proof="goal"',
        "function setHomeIntent",
        "function setupHomeIntentStrip",
        "setupHomeIntentStrip();",
    ]:
        if homepage_intent_marker not in index_html:
            return fail(f"public homepage AI CEO intent entry missing marker: {homepage_intent_marker}")
    deploy_script = (ROOT / "tools" / "jiejing_deploy_frontend_staging_with_key.ps1").read_text(encoding="utf-8")
    if "Unable to derive frontend asset version from app.html" not in deploy_script or "DEPLOY_FRONTEND_VERSION=$frontendVersion" not in deploy_script:
        return fail("frontend deploy script must derive DEPLOY_FRONTEND_VERSION from app.html")
    for deploy_asset in [
        "favicon.ico",
        "assets/jiejing-app-icon.svg",
        "assets/jiejing-logo-lockup.svg",
        "assets/jiejing-logo-mark.svg",
    ]:
        if deploy_asset not in deploy_script:
            return fail(f"frontend deploy script must ship brand asset: {deploy_asset}")
    if 'background: url("./assets/jiejing-app-icon.svg?v=20260630-jeway-soft-black-gold-v1") center / contain no-repeat;' not in styles_css:
        return fail("public SaaS brand mark must use the JIEJING app icon instead of a black fallback block")
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
    for first_day_marker in [
        "login_onboarding_ai_ceo_v3",
        "saas-first-day-path-strip",
        'data-first-day-path="login_onboarding_ai_ceo_v3"',
        "刷新不会跳过向导",
        "一句话交给 AI CEO",
    ]:
        if first_day_marker not in app_js + app_html + styles_css:
            return fail(f"first-day login/onboarding/AI CEO path marker missing: {first_day_marker}")
    for ai_ceo_pending_marker in [
        "merchant_clear_pending_v4",
        "function scheduleSaasAiCeoPendingWatchdog",
        "function updateCeoAssistantPendingMessage",
        "model_response_delayed",
        "真实发布、付款、退款、广告、授权和敏感客服承诺不会自动执行",
        ".saas-ai-ceo-pending-status",
    ]:
        if ai_ceo_pending_marker not in app_js + styles_css:
            return fail(f"AI CEO merchant-safe pending marker missing: {ai_ceo_pending_marker}")
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

    compose_public = (ROOT / "deploy/docker-compose.public-staging.yml").read_text(encoding="utf-8")
    compose_https = (ROOT / "deploy/docker-compose.public-https-staging.yml").read_text(encoding="utf-8")
    managed_env_template = (ROOT / "deploy/jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8")
    deploy_script = (ROOT / "tools/jiejing_deploy_frontend_staging_with_key.ps1").read_text(encoding="utf-8")
    prelaunch_runbook = (ROOT / "docs/JIEJING_PRELAUNCH_INTERNAL_HARDENING_RUNBOOK_20260620.md").read_text(encoding="utf-8")
    public_staging_contracts = [
        (
            "docker-compose.public-staging.yml",
            compose_public,
            'JIEJING_EBAY_DRAFT_SAVE_LIVE: "false"',
            'JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "disabled_public_staging"',
        ),
        (
            "docker-compose.public-https-staging.yml",
            compose_https,
            'JIEJING_EBAY_DRAFT_SAVE_LIVE: "true"',
            'JIEJING_PUBLIC_STAGING_REAL_WRITE_POLICY: "controlled_unpublished_draft_only"',
        ),
    ]
    for compose_name, compose_text, draft_marker, policy_marker in public_staging_contracts:
        for marker in [
            'JIEJING_ENABLE_REAL_PLATFORM_WRITES: "false"',
            'JIEJING_EBAY_WRITE_LIVE: "false"',
            draft_marker,
            policy_marker,
        ]:
            if compose_text.count(marker) != 2:
                return fail(
                    "public staging API and worker must own the same narrow write contract: "
                    f"{compose_name} expected two declarations of {marker}"
                )
    with TemporaryDirectory() as temp_dir:
        candidate_deploy = Path(temp_dir) / "workspace" / "deploy"
        private_root = Path(temp_dir) / "private"
        candidate_deploy.mkdir(parents=True)
        private_root.mkdir()
        compose_path = candidate_deploy / "docker-compose.public-https-staging.yml"
        managed_path = private_root / "tencent-managed.env"
        secret_path = private_root / "jiejing-saas.staging-oauth.env"
        postgres_path = private_root / "postgres-localqueue.env"
        compose_path.write_text(compose_https, encoding="utf-8")
        managed_path.write_text(
            (ROOT / "deploy/jiejing-saas.tencent-managed.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        secret_path.write_text(
            (ROOT / "deploy/jiejing-saas.staging-oauth.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        postgres_path.write_text(
            (ROOT / "deploy/jiejing-saas.postgres-localqueue.env.example").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/jiejing_runtime_env_overlap_guard.py"),
                "check",
                "--compose",
                str(compose_path),
                "--managed-env",
                str(managed_path),
                "--secret-env",
                str(secret_path),
                "--postgres-env",
                str(postgres_path),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return fail(f"public HTTPS narrow draft-save ownership guard failed: {completed.stderr or completed.stdout}")
        guard_report = json.loads(completed.stdout)
        if not guard_report["ok"] or guard_report["blockers"] or guard_report["secret_exposed"]:
            return fail("public HTTPS narrow draft-save ownership guard did not pass safely")
    if "../privacy.html:/usr/share/nginx/html/privacy.html:ro" not in compose_https:
        return fail("public HTTPS staging frontend must serve privacy.html for eBay OAuth developer configuration")
    for mounted_page in [
        "../terms.html:/usr/share/nginx/html/terms.html:ro",
        "../refund-policy.html:/usr/share/nginx/html/refund-policy.html:ro",
        "../support.html:/usr/share/nginx/html/support.html:ro",
        "../risk-disclosure.html:/usr/share/nginx/html/risk-disclosure.html:ro",
    ]:
        if mounted_page not in compose_https:
            return fail(f"public HTTPS staging frontend must serve legal page: {mounted_page}")
    for deploy_page in ["privacy.html", "terms.html", "refund-policy.html", "support.html", "risk-disclosure.html"]:
        if deploy_page not in deploy_script:
            return fail(f"frontend deploy archive must sync legal page: {deploy_page}")
    for deploy_archive_marker in [
        '"tar"',
        "$patchArchive",
        "$remoteArchive",
        "tar -xzf",
        "install -m 0644",
    ]:
        if deploy_archive_marker not in deploy_script:
            return fail(f"frontend deploy script must use the atomic archive deploy path: {deploy_archive_marker}")
    for marker in [
        'JIEJING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_ONCALL_ALERT_ROUTE_CONFIGURED: "true"',
        'JIEJING_POST_PUBLISH_RECOVERY_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_BILLING_INCIDENT_RUNBOOK_PUBLISHED: "true"',
        'JIEJING_TEST_DATA_GOVERNANCE_REVIEWED: "true"',
    ]:
        if marker not in compose_https:
            return fail(f"public HTTPS staging compose missing prelaunch evidence flag: {marker}")
    for marker in [
        "JIEJING_BACKUP_RESTORE_DRILL_RUNBOOK_PUBLISHED=true",
        "JIEJING_DATABASE_ENDPOINT_INCIDENT_RUNBOOK_PUBLISHED=true",
    ]:
        if marker not in managed_env_template:
            return fail(f"managed runtime env template missing operations evidence flag: {marker}")
        compose_marker = marker.replace("=true", ': "true"')
        if compose_marker in compose_public or compose_marker in compose_https:
            return fail(f"operations evidence flag must not be owned by Compose: {compose_marker}")
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
        "当前在线付款尚未向所有商家开放",
        "eBay 授权凭证、模型连接凭证和支付连接密钥",
        "服务条款",
        "风险披露与确认中心边界",
    ]:
        if marker not in privacy_html:
            return fail(f"privacy page missing staging data-boundary marker: {marker}")
    for marker in [
        "捷境服务条款",
        "当前在线付款尚未向所有商家开放",
        "禁止自动执行的动作",
        "试用数据默认只标记和报告，不自动删除",
        "基础订阅是软件功能费",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "更新日期：2026-07-02",
    ]:
        if marker not in terms_html:
            return fail(f"terms page missing launch-boundary marker: {marker}")
    for marker in [
        "捷境退款政策",
        "当前在线付款尚未向所有商家开放",
        "受邀试用的订阅开通需要客服或后台确认",
        "eBay 成交费、广告费、店铺订阅费、物流费、采购款、买家退款",
        "后续会补充公开客服邮箱、工单和投诉升级路径",
        "更新日期：2026-07-02",
    ]:
        if marker not in refund_html:
            return fail(f"refund policy page missing payment-review marker: {marker}")
    for marker in [
        "捷境客服与反馈入口",
        "在线付款和公开工单入口会按实际开放状态展示",
        "意见箱只记录流程意见和上下文编号，不保存密钥、平台凭证或身份资料",
        "不会替商家直接发布商品、改价、改库存、退款、投广告",
        "后续会补充的客服信息",
        "更新日期：2026-07-02",
    ]:
        if marker not in support_html:
            return fail(f"support page missing payment-review marker: {marker}")
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
        "function isPlausibleJiejingApiBase",
        'url.protocol !== "https:"',
        "url.origin !== window.location.origin",
        "Public SaaS requests must stay on the current HTTPS origin",
        "function safeEbayOAuthAuthorizationUrl",
        '"auth.ebay.com"',
        '"auth.sandbox.ebay.com"',
        'url.pathname !== "/oauth2/authorize"',
        "url.port",
        "url.username",
        "url.password",
        "validatedSaasReadOnlyOAuthAuthorizationUrl(rawUrl, planScopes, planState)",
        "validatedSaasUnpublishedDraftOAuthAuthorizationUrl(value = \"\", expectedState = \"\")",
        "validatedSaasUnpublishedDraftOAuthPlanResponse(payload, store, existingConfirmation)",
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
        "function renderSaasModuleAiGoalStrip",
        "function renderSaasModuleAiGoalStripIntoView",
        'data-ai-ceo-module-goal-strip="ai_ceo_module_goal_v1"',
        "小批量实验目标已带入",
        "高风险动作已拦住",
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
        "<b>凭证安全</b>不在浏览器显示",
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
        "copy-ebay-return-url",
        "官方连接返回地址应保持一致",
        'productFeedbackOutbox: "jiejing_saas_product_feedback_outbox_v1"',
        'productFeedbackReceipts: "jiejing_saas_product_feedback_receipts_v1"',
        'productFeedbackMigration: "jiejing_saas_product_feedback_migration_v1"',
        "function saasProductFeedbackIdentityParts",
        "function prepareSaasProductFeedbackScopeAfterIdentity",
        'saasFetchWithTimeout(\n      "/product-feedback"',
        "window.addEventListener(\"online\"",
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
    if 'if (!hasSaasProtectedSessionCandidate()) {\n    refreshSaasPublicReadiness({ render: true });' in app_js:
        return fail("logged-in merchants must also receive current public provider readiness")
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
    for marker in [
        ".price {",
        "font-size: 38px;",
        "line-height: 1.08;",
        "white-space: nowrap;",
    ]:
        if marker not in index_html:
            return fail(f"public pricing cards must keep the full price on one stable line: {marker}")
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
        "onboardingDeferredSettingsFields",
        "onboarding-lite-path",
        "onboarding-lite-safety",
        "设置里可继续补接",
        "不需要一次配置完所有平台接口",
        "发布、改价、退款、广告预算、采购付款和买家承诺都会进入确认中心",
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
        "首日安全边界",
    ]:
        if onboarding_control_marker not in app_js + app_html + styles_css:
            return fail(f"missing onboarding control-room marker: {onboarding_control_marker}")
    if '"sourceApiMode",\n    "fulfillmentMode",' in app_js or '"returnPolicy",\n    "feeInsightMode",' in app_js:
        return fail("public first-day onboarding must keep advanced connection details in Settings instead of the main route")
    for billing_guardrail_marker in [
        "function renderSaasMerchantPricingModelPanel",
        "saas-merchant-pricing-model",
        "四档套餐只收软件使用费",
        "subscription_ai_media_platform_v1",
        "saas-merchant-pricing-split",
        "用量计费路线",
        "¥99 / 30 天",
        "¥0 / ¥99 / ¥199 / ¥299",
        "商家自带模型",
        "图片 / 视频",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "function renderSaasMerchantBillingCurrentStatusPanel",
        "function renderSaasMerchantBillingPlainSummaryPanel",
        "merchant_billing_plain_summary_v1",
        "订阅和用量总览",
        "软件套餐、商家模型、素材点和平台成本分开",
        "套餐只决定店铺数、席位数、经营任务和批量上限",
        "不消耗素材点",
        "生成前显示预计点数",
        "billing_now_no_real_charge",
        "base_subscription_is_feature_fee=true",
        "ai_media_usage_is_separate=true",
        "platform_cost_not_collected_by_jiejing=true",
        "saas-merchant-billing-current",
        "当前计费状态",
        "先看能不能继续用，再看哪些费用另算",
        "不真实扣费",
        "merchant_visible_billing_status_v1",
        "subscription_metering_clarity_v2",
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
        "function renderSaasBillingDomainCutoverReviewPanel",
        "billing_domain_cutover_review_v1",
        "stable_domain_checkout_portal_webhook_review_v1",
        "billing_domain_cutover_rehearsal",
        "payment_provider_secret_boundary=backend_env_or_vault_only",
        "checkout_success_cancel_urls_on_stable_domain",
        "customer_portal_return_url_on_stable_domain",
        "rollback_secret_scan_readiness_browser_smoke_required",
        "public_paid_launch_allowed=false",
        "owner_approval_required_for_reenable=true",
        'version: "2026-07-12-listing-media-restore-v3"',
        "statusPills.push(saasMerchantBillingStatusPill())",
    ]:
        if billing_guardrail_marker not in app_js + app_html + styles_css:
            return fail(f"missing merchant billing guardrail marker: {billing_guardrail_marker}")
    snapshot_start = app_js.index("function buildSaasProtectedStateSnapshot")
    snapshot_end = app_js.index("function saveSaasProtectedStateSnapshot", snapshot_start)
    snapshot_body = app_js[snapshot_start:snapshot_end]
    for forbidden_snapshot_marker in (
        "saasBillingCheckout",
        "saasBillingProviderRehearsal",
        "saasBillingDomainCutoverRehearsal",
        "saasEdgeCutoverPreflight",
        "saasPaidLaunchApprovalPacket",
        "saasCommercialLaunchGate",
    ):
        if forbidden_snapshot_marker in snapshot_body:
            return fail(f"browser fast-restore snapshot must not persist backend control state: {forbidden_snapshot_marker}")
    for homepage_return_marker in [
        "function currentPublicHomepageUrl",
        "function openCurrentPublicHomepage",
        'new URL("./index.html", window.location.href)',
        'target.searchParams.set("source", source)',
        'target.searchParams.set("start", "site")',
        'currentPublicHomepageUrl("intro", "workbench_logo")',
        '"app_embedded_site_return"',
        'target.hash = scrollTarget || "intro"',
    ]:
        if homepage_return_marker not in app_js:
            return fail(f"workbench logo should return to current public homepage: {homepage_return_marker}")
    reveal_start = app_js.index("function revealSite")
    reveal_end = app_js.index("function openCurrentPublicHomepage", reveal_start)
    reveal_body = app_js[reveal_start:reveal_end]
    if 'siteShell.classList.remove("is-hidden")' in reveal_body:
        return fail("embedded app.html homepage shell must not be exposed; return to index.html instead")
    if "currentPublicHomepageUrl(scrollTarget, \"app_embedded_site_return\")" not in reveal_body:
        return fail("embedded app homepage returns must delegate to the current public index.html")
    for app_entry_marker in [
        'publicHomeUrl.searchParams.set("source", "legacy_app_entry")',
        'publicHomeUrl.searchParams.set("start", "site")',
        "window.location.replace(publicHomeUrl.toString())",
    ]:
        if app_entry_marker not in app_html:
            return fail(f"legacy app.html marketing entry must redirect to current public homepage: {app_entry_marker}")
    refresh_start = app_js.index("async function refreshSaasState")
    refresh_end = app_js.index("async function refreshSaasPublicReadiness", refresh_start)
    refresh_body = app_js[refresh_start:refresh_end]
    if "const canFetchProtectedState = hasSaasProtectedSessionCandidate();" not in refresh_body:
        return fail("refreshSaasState must check for a real session or explicit operator bootstrap before protected reads")
    guard_index = refresh_body.find("if (!canFetchProtectedState)")
    store_fetch_index = refresh_body.find("const store = await ensureSaasDemoStoreAndConnection();")
    if guard_index < 0 or store_fetch_index < 0 or guard_index > store_fetch_index:
        return fail("refreshSaasState must skip protected store/report reads before ensuring a store")
    cached_restore_start = refresh_body.index("if (restoredCachedState)")
    cached_restore_end = refresh_body.index("\n  try", cached_restore_start)
    cached_restore_body = refresh_body[cached_restore_start:cached_restore_end]
    for cached_restore_marker in (
        'document.documentElement.classList.remove("app-auth-pending")',
        'openApp(activeSaasRefreshView("cockpit"))',
    ):
        if cached_restore_marker not in cached_restore_body:
            return fail(f"account-scoped fast restore must reveal the cached workbench immediately: {cached_restore_marker}")
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
    if "saasLatestOAuthUrl" not in app_js or "打开 eBay 官方授权页" not in app_js or 'target="_blank"' not in app_js:
        return fail("frontend should retain a clickable eBay authorization URL")
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
