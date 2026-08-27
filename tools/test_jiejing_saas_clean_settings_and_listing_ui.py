import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
APP_HTML = ROOT / "app.html"
INDEX_HTML = ROOT / "index.html"
STYLES = ROOT / "styles.css"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    app_html = APP_HTML.read_text(encoding="utf-8")
    index_html = INDEX_HTML.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    require(app_js, "saasSettingsTab", "settings tab state")
    require(app_js, "function renderSaasSettingsCleanLayout", "clean settings layout")
    require(app_js, "function saasModelConnectionAttemptState", "truthful model connection state")
    require(app_js, "function saasModelSecretRefReady", "ready-only BYOK classification")
    require(app_js, "return refs.find((item) => saasModelSecretRefReady(item)) || null;", "blocked model refs never become active")
    require(app_js, "data-model-connection-state", "model connection progress state")
    require(app_js, "保存并检测 AI 连接", "model save and verify action")
    require(app_js, "重新检测连接", "model verification retry action")
    require(app_js, "function verifySaasModelConnectionFromWorkbench", "model verification retry flow")
    require(app_js, "saas-model-config-grid", "merchant model configuration field layout")
    require(app_js, "选择服务商后自动填写，通常不需要改。", "model base URL guidance")
    require(app_js, "连接一次，当前账号下的店铺都能使用", "account-scoped model setup copy")
    require(app_js, "formSource?.model", "failed model attempt keeps safe form metadata")
    require(app_js, 'id="saas-model-base-url"', "official model base URL field")
    require(styles, ".saas-model-connection-progress", "model connection progress styling")
    require(styles, ".saas-model-config-grid", "model configuration responsive styling")
    require(styles, ".saas-model-provider-panel .saas-merchant-evidence-grid", "model settings container-responsive cards")
    require(app_js, "data-saas-settings-tab", "settings tab navigation")
    require(app_js, "renderSaasSettingsCleanLayout(ctx", "settings render path")
    require(app_js, 'read_only_pending: "等待只读连接"', "merchant-readable pending eBay state")
    require(app_js, "连接只读数据", "clear eBay read-only connection action")
    require(app_js, "开通草稿权限", "clear eBay unpublished-draft permission action")
    require(app_js, 'detail: "角色 / 审批"', "team permissions navigation label")
    require(app_js, 'const connectionReady = isSaasAuthorizedConnectionStatus(connectionStatus);', "store data connection gate")
    require(app_js, "function trustedJiejingHtml", "trusted HTML sink guard")
    require(app_js, "function validateJiejingTrustedHtmlDocument", "DOM-level trusted HTML validation")
    require(app_js, "jiejingTrustedHtmlForbiddenTags", "dangerous dynamic HTML tag denylist")
    require(app_js, "jiejingTrustedHtmlUriAttributes", "dynamic HTML URL attribute validation")
    require(app_js, 'name.startsWith("on") || name === "srcdoc"', "event and srcdoc attribute blocking")
    require(app_js, 'normalizedValue.startsWith("data:text/html")', "HTML data URL blocking")
    require(app_js, r"\bon[a-z]+\s*=", "trusted HTML event handler boundary")
    require(app_js, "function setJiejingTrustedHtml", "trusted HTML set sink")
    require(app_js, "function insertJiejingTrustedHtml", "trusted HTML insert sink")
    require(app_js, "function replaceJiejingTrustedHtml", "trusted HTML replace sink")
    require(app_js, "function jiejingTrustedTemplate", "trusted dynamic template guard")
    require(app_js, '"ai_ceo.cockpit"', "AI CEO cockpit trusted template label")
    require(app_js, '"workflow_feedback.context"', "workflow feedback trusted context label")
    require(app_js, '"bulk.candidate_preview"', "bulk candidate trusted sink label")
    require(app_js, '"media.generated_assets"', "media generated assets trusted sink label")
    require(app_js, '"confirmation.center"', "confirmation center trusted template label")
    require(app_js, '"listing.product_center"', "Listing daily surface trusted sink label")
    require(app_js, '"settings.clean_layout"', "settings trusted sink label")
    require(app_js, '"settings.legacy_connect_status"', "legacy settings status trusted sink label")
    if "|on[a-z]+\\s*=" in app_js:
        raise AssertionError("trusted HTML guard must not match ordinary words ending in on")
    require(app_html, "店铺连接、AI 连接和经营资料会按账号空间显示状态，缺少资料会提示补齐", "merchant-facing login credential copy")
    require(app_html, "有真实任务、订单或确认事项后会自动出现在这里", "merchant-facing empty state copy")
    require(app_html, "请稍后重试，或回到设置查看连接状态；系统不会自动执行高风险动作", "merchant-facing error state copy")
    require(index_html, "高风险动作必须经过确认中心", "merchant-facing homepage footer trust boundary")
    require(index_html, "未连接前不会读取店铺数据，也不会执行高风险动作", "merchant-facing homepage auth copy")
    require(app_html, "不保存敏感凭证或平台账号资料", "merchant-facing feedback privacy copy")
    require(app_js, "不保存敏感凭证或平台账号资料", "workflow feedback avoids token/key wording")
    require(app_js, "已送达 JIEJING 团队；服务器已返回接收回执。", "server-receipt delivery copy")
    require(app_js, "意见已保存在本机", "honest queued feedback copy")
    require(app_js, "请实际修改意见类型或补充内容", "editable validation recovery copy")
    require(app_js, "已隔离且停止自动重试", "idempotency conflict copy")
    require(app_html, "data-workflow-feedback-retry", "manual product feedback retry action")
    require(styles, "body.saas-public-mvp[data-view=\"cockpit\"] .workflow-feedback-shell", "mobile-safe feedback placement")
    require(app_js, "套餐权益、商家模型、素材点和平台成本清楚可查", "billing pricing keeps software, BYOK, media, and platform costs separate")
    settings_data_body = app_js[app_js.index("function renderSaasSettingsDataPanel") : app_js.index("function renderSaasSettingsFocusPanel")]
    if "后端" in settings_data_body or "浏览器不能" in settings_data_body:
        raise AssertionError("merchant store data settings should not explain browser/backend implementation")
    require(index_html, "登录没有完成，请稍后重试；不会读取店铺资料或执行高风险动作。", "login error uses merchant-facing recovery wording")
    auth_shell_start = app_html.index('<div class="saas-auth-form-grid">')
    auth_shell_end = app_html.index('<div class="modal-backdrop" id="plansModal"', auth_shell_start)
    auth_shell_body = app_html[auth_shell_start:auth_shell_end]
    feedback_start = app_html.index('<div class="workflow-feedback-shell"')
    feedback_end = app_html.index('<div class="modal-backdrop" id="evidenceModal"', feedback_start)
    feedback_body = app_html[feedback_start:feedback_end]
    pricing_panel_start = app_js.index("function renderSaasMerchantPricingModelPanel")
    pricing_panel_end = app_js.index("function renderSaasMerchantSecurityBoundaryPanel", pricing_panel_start)
    pricing_panel_body = app_js[pricing_panel_start:pricing_panel_end]
    workflow_feedback_start = app_js.index("function renderWorkflowFeedbackWidget")
    workflow_feedback_end = app_js.index("function openSaasWorkflowFeedback", workflow_feedback_start)
    workflow_feedback_body = app_js[workflow_feedback_start:workflow_feedback_end]
    for surface_name, surface_body in [
        ("app auth shell", auth_shell_body),
        ("workflow feedback shell", feedback_body),
        ("workflow feedback runtime", workflow_feedback_body),
        ("merchant pricing panel", pricing_panel_body),
    ]:
        for internal_marker in ["模型 key", "token、key", "登录 token", "token 或服务商账单"]:
            if internal_marker in surface_body:
                raise AssertionError(f"{surface_name} should use merchant-facing credential/usage wording: {internal_marker}")
    index_auth_start = index_html.index('<div class="entry-auth-shell">')
    index_auth_end = index_html.index('<div class="toast" id="toast"', index_auth_start)
    index_auth_body = index_html[index_auth_start:index_auth_end]
    app_entry_state_start = app_html.index('<section class="empty-state" id="emptyState"')
    app_entry_state_end = app_html.index('<div class="modal-backdrop" id="authModal"', app_entry_state_start)
    app_entry_state_body = app_html[app_entry_state_start:app_entry_state_end]
    for surface_name, surface_body in [
        ("homepage auth modal", index_auth_body),
        ("app empty/error states", app_entry_state_body),
    ]:
        for internal_marker in [
            "后端",
            "登录凭证",
            "API",
            "provider",
            "webhook",
            "quota",
            "个人码",
            "个人收款码",
            "大陆收款",
            "个体工商户",
            "模型 key",
            "eBay token",
            "Source packet",
            "refresh success proof",
        ]:
            if internal_marker in surface_body:
                raise AssertionError(f"{surface_name} should stay merchant-facing: {internal_marker}")
    index_auth_script_start = index_html.index("function saveEntryAuthSession")
    index_auth_script_end = index_html.index("function showEntryLogin", index_auth_script_start)
    index_auth_script_body = index_html[index_auth_script_start:index_auth_script_end]
    cookie_session_contract = f"""
const values = new Map([
  ["jiejing_saas_backend_token", "legacy-token"],
]);
globalThis.localStorage = {{
  getItem: (key) => values.has(key) ? values.get(key) : null,
  setItem: (key, value) => values.set(key, String(value)),
  removeItem: (key) => values.delete(key),
}};
const sessionValues = new Map([["jiejing_saas_backend_token", "legacy-token"]]);
globalThis.sessionStorage = {{
  getItem: (key) => sessionValues.has(key) ? sessionValues.get(key) : null,
  setItem: (key, value) => sessionValues.set(key, String(value)),
  removeItem: (key) => sessionValues.delete(key),
}};
let remembered = false;
function rememberEntryAuthAccount(session, credentials) {{
  remembered = Boolean(session && credentials && credentials.email);
}}
{index_auth_script_body}
saveEntryAuthSession(
  {{ token_returned_to_frontend: false, store_id: "store-cookie-session" }},
  {{ email: "merchant@example.test" }},
);
if (localStorage.getItem("jiejing_saas_backend_session_hint") !== "1") {{
  throw new Error("cookie session hint was not saved");
}}
if (localStorage.getItem("jiejing_saas_backend_store_id") !== "store-cookie-session") {{
  throw new Error("cookie session store was not saved");
}}
if (localStorage.getItem("jiejing_saas_backend_token") !== null) {{
  throw new Error("legacy local token was not removed");
}}
if (sessionStorage.getItem("jiejing_saas_backend_token") !== null) {{
  throw new Error("legacy session token was not removed");
}}
if (!remembered) throw new Error("cookie session account was not remembered");
let malformedRejected = false;
try {{
  saveEntryAuthSession({{}}, {{ email: "merchant@example.test" }});
}} catch (error) {{
  malformedRejected = true;
}}
if (!malformedRejected) throw new Error("malformed session response was accepted");
"""
    cookie_session_result = subprocess.run(
        ["node", "-e", cookie_session_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if cookie_session_result.returncode != 0:
        raise AssertionError(
            "homepage login must accept an HttpOnly cookie session without exposing a token: "
            f"{cookie_session_result.stderr.strip()}"
        )
    for internal_marker in ["后端没有返回登录凭证", "登录凭证", "HTTP 401", "provider", "quota", "模型 key"]:
        if internal_marker in index_auth_script_body:
            raise AssertionError(f"homepage auth script should keep failure copy merchant-facing: {internal_marker}")
    for required_copy in [
        "敏感凭证只在后端安全保存",
        "不接触原始平台凭证",
        "不包含敏感凭证、买家敏感信息或平台账号资料",
        "店铺连接续期证明仍为 0",
        "账号自己的 AI 连接只在后端安全保存",
        "不保存敏感凭证、网页登录状态、买家敏感信息或平台写入资料",
        "页面只显示连接状态，执行层不读取原始凭证",
        "捷境试用 AI",
    ]:
        require(app_js, required_copy, "merchant-facing credential boundary copy")

    def scoped_body(start_marker: str, end_marker: str) -> str:
        start = app_js.index(start_marker)
        return app_js[start:app_js.index(end_marker, start)]

    legacy_product_label_source = scoped_body(
        "function isLegacySampleProductLabel",
        "function activeMediaDraftProfileForDisplay",
    )
    legacy_product_label_contract = f"""
{legacy_product_label_source}
const legitimateProducts = [
  "incense",
  "香炉",
  "倒流香",
  "Backflow Incense",
  "Incense Burner",
  "Zen Incense",
  "禅意佛手托莲花倒流香炉",
  "Zen Buddha Hand Lotus Backflow Incense Burner",
  "Handmade Ceramic Incense Burner for Home Decor",
];
for (const label of legitimateProducts) {{
  if (isLegacySampleProductLabel(label)) {{
    throw new Error(`legitimate merchant product was hidden: ${{label}}`);
  }}
}}
const historicalSamples = [
  "jj-backflow-incense-debug-full",
  "listing-jj-backflow-incense-debug-min",
  "JJ-DRAFT-PROOF-20260815-05",
  "assets/backflow-incense-hero.webp",
  "source-backflow-incense-burner",
];
for (const label of historicalSamples) {{
  if (!isLegacySampleProductLabel(label)) {{
    throw new Error(`known historical sample was shown: ${{label}}`);
  }}
}}
"""
    legacy_product_label_result = subprocess.run(
        ["node", "-e", legacy_product_label_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if legacy_product_label_result.returncode != 0:
        raise AssertionError(
            "Listing/media product labels must reject only known historical samples: "
            f"{legacy_product_label_result.stderr.strip()}"
        )

    legacy_media_key_source = scoped_body(
        "function isLegacySampleMediaDraftKey",
        "function isLegacySampleProductLabel",
    )
    legacy_media_key_contract = f"""
{legacy_media_key_source}
for (const key of ["incense", "backflow-incense", "zen-incense"]) {{
  if (!isLegacySampleMediaDraftKey(key)) {{
    throw new Error(`exact historical media key was accepted: ${{key}}`);
  }}
}}
for (const key of [
  " Incense ",
  "INCENSE",
  "Backflow Incense",
  "backflow-incense-burner",
  "禅意佛手托莲花倒流香炉",
]) {{
  if (isLegacySampleMediaDraftKey(key)) {{
    throw new Error(`non-exact media key was hidden: ${{key}}`);
  }}
}}
"""
    legacy_media_key_result = subprocess.run(
        ["node", "-e", legacy_media_key_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if legacy_media_key_result.returncode != 0:
        raise AssertionError(
            "Legacy media draft keys must retain their raw exact-match boundary: "
            f"{legacy_media_key_result.stderr.strip()}"
        )

    confirmation_execution_source = scoped_body(
        "function saasLatestExecutionResult",
        "function saasLatestPublishConfirmation",
    )
    confirmation_execution_contract = f"""
const state = {{
  saasExecutionResults: [
    {{
      execution_id: "exec-old-confirmation",
      confirmation_id: "confirm-old",
      action_type: "publish_listing",
      result: {{ action_type: "publish_listing" }},
    }},
    {{
      execution_id: "exec-result-confirmation",
      action_type: "publish_listing",
      result: {{
        action_type: "publish_listing",
        confirmation_id: "confirm-result",
      }},
    }},
    {{
      execution_id: "exec-audit-confirmation",
      action_type: "publish_listing",
      result: {{
        action_type: "publish_listing",
        audit: {{ confirmation_id: "confirm-audit" }},
      }},
    }},
    {{
      execution_id: "exec-intent-confirmation",
      action_type: "publish_listing",
      result: {{
        action_type: "publish_listing",
        audit: {{ execution_intent: {{ confirmation_id: "confirm-intent" }} }},
      }},
    }},
  ],
}};
{confirmation_execution_source}
const missingNew = saasExecutionResultForConfirmation("confirm-new", "publish_listing");
if (missingNew !== null) {{
  throw new Error("new confirmation borrowed an older confirmation execution");
}}
const matchedOld = saasExecutionResultForConfirmation("confirm-old", "publish_listing");
if (!matchedOld || matchedOld.execution_id !== "exec-old-confirmation") {{
  throw new Error("old confirmation did not resolve its own execution");
}}
for (const [confirmationId, executionId] of [
  ["confirm-result", "exec-result-confirmation"],
  ["confirm-audit", "exec-audit-confirmation"],
  ["confirm-intent", "exec-intent-confirmation"],
]) {{
  const matched = saasExecutionResultForConfirmation(confirmationId, "publish_listing");
  if (!matched || matched.execution_id !== executionId) {{
    throw new Error(`confirmation binding was missed: ${{confirmationId}}`);
  }}
}}
const latestFallback = saasExecutionResultForConfirmation("", "publish_listing");
if (!latestFallback || latestFallback.execution_id !== "exec-old-confirmation") {{
  throw new Error("empty confirmation id lost latest execution fallback");
}}
"""
    confirmation_execution_result = subprocess.run(
        ["node", "-e", confirmation_execution_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if confirmation_execution_result.returncode != 0:
        raise AssertionError(
            "Confirmation execution receipts must fail closed for a non-empty unmatched id: "
            f"{confirmation_execution_result.stderr.strip()}"
        )

    credential_copy_surfaces = [
        ("eBay sync status", scoped_body("function renderSaasEbaySyncStatusPanel", "function renderSaasLiveSnapshotPanel")),
        ("Listing entry", scoped_body("function renderSaasProductListingCenter", "function renderProductListingCenter")),
        ("AI CEO output", scoped_body("function renderSaasAiCeoOutputPanel", "function saasLatestExecutionResult")),
        ("merchant cockpit risk queue", scoped_body("function saasCockpitRiskQueue", "function renderSaasMerchantExecutiveCockpit")),
        ("merchant operating path", scoped_body("function renderSaasMerchantOperatingPath", "function renderSaasMerchantSetupGuidePanel")),
        ("merchant setup guide", scoped_body("function renderSaasMerchantSetupGuidePanel", "function saasPermissionLabel")),
        ("merchant workflow template", scoped_body("function renderSaasMerchantWorkflowTemplatePanel", "function renderSaasSourceRecordCollectorPanel")),
        ("source record collector", scoped_body("function renderSaasSourceRecordCollectorPanel", "function renderSaasMerchantPermissionPanel")),
        ("model connection save toast", scoped_body("async function saveSaasModelApiKeyFromWorkbench", "async function runSaasModelValueRehearsalFromWorkbench")),
    ]
    for surface_name, surface_body in credential_copy_surfaces:
        for internal_marker in [
            "AI 连接凭证",
            "eBay token",
            "原始 token",
            "不保存 token",
            "所有 token",
            "模型 key",
            "token、",
            "token 或",
            "refresh success proof",
            "Source packet",
        ]:
            if internal_marker in surface_body:
                raise AssertionError(f"{surface_name} should use merchant-facing credential wording: {internal_marker}")
    model_failure_start = app_js.index("function saasModelBlockedReasonText")
    model_failure_body = app_js[model_failure_start:app_js.index("function saasEbaySyncOverallStatus", model_failure_start)]
    ai_ceo_failure_start = app_js.index("function saasAiCeoMerchantSafeFailureText")
    ai_ceo_failure_body = app_js[ai_ceo_failure_start:app_js.index("function saasAiCeoProductizedAnswerText", ai_ceo_failure_start)]
    combined_ai_failure_body = model_failure_body + ai_ceo_failure_body
    for required_copy in [
        "AI 额度或连接状态挡住了本次回复",
        "不要重复填写连接信息，除非页面明确提示连接已失效",
        "敏感连接信息仍只在安全边界内处理",
        "实时数据源还没接通",
    ]:
        require(combined_ai_failure_body, required_copy, "merchant-facing AI failure copy")
    require(app_js, "AI 已接通，但实时数据源需要先恢复", "AI CEO realtime-source recovery copy")
    for internal_marker in [
        "服务商账单",
        "在前台重复粘贴凭证",
        "服务商明确拒绝认证",
        "后端暂时无法读取",
        "模型服务返回余额",
        "模型服务不接受",
        "模型服务网络请求",
    ]:
        if internal_marker in combined_ai_failure_body:
            raise AssertionError(f"AI failure copy should not expose implementation wording: {internal_marker}")

    require(app_js, "function renderSaasBulkCandidatePreview", "SaaS bulk simplified candidate preview")
    require(app_html, "先小批量筛，不一键乱铺", "bulk low-learning-cost headline")
    require(app_html, "小批量实验台", "bulk experiment lab framing")
    require(app_js, "生成三类候选", "bulk simple grouping action")
    require(app_js, "建议先测", "bulk test lane")
    require(app_js, "需要补资料", "bulk missing-info lane")
    require(app_js, "暂时不做", "bulk blocked lane")
    require(app_html, "用最小批次看清机会和风险", "bulk simple one-job copy")
    require(app_js, "bulk-import-preview", "bulk manual import preview markup")
    require(app_js, "bulk-saas-lane-list", "bulk grouped lane markup")
    require(app_js, "先导入真实候选，再生成三类结论", "bulk one-next-step empty state")
    require(app_html, "先小批量筛，不一键乱铺", "bulk shell simple headline")
    require(app_html, "小批量实验台", "bulk shell experiment lab framing")
    require(app_html, "本轮数量", "bulk shell merchant count metric")
    require(app_html, "来源资料", "bulk shell source metric")
    require(app_html, "已分组", "bulk shell grouped metric")
    require(app_html, "用最小批次看清机会和风险", "bulk shell simple one-job copy")
    require(app_html, "结果预览", "bulk result preview title")
    require(app_html, "等待生成三类候选", "bulk result preview empty heading")
    require(app_html, "先分组，再决定", "bulk static first-run copy")

    require(app_html, "把商品图变成可用素材包", "media simple headline")
    require(app_html, "选来源、选素材包、看预览、回写 Listing 草稿", "media simple workflow copy")
    require(app_html, "商品草稿 / 上传图片", "media source choice")
    require(app_html, "选择要做图的商品", "media draft selector copy")
    require(app_html, "先选要做什么图", "media package selection copy")
    require(app_html, "素材任务记录", "media asset job placeholder title")
    require(app_html, "素材清单（AssetManifest）", "media asset manifest placeholder copy")
    require(app_html, "不会把旧测试图当成真实生成结果", "media no fake generated proof placeholder")
    require(app_js, "function saasMediaTaskLabel", "media merchant-facing task labels")
    require(app_js, "等待商品草稿", "media waiting state copy")
    require(app_js, "saas-media-first-run-strip", "media first-run assurance strip")
    require(app_js, "没有商品或来源图时，不展示旧样例", "media no fake sample copy")
    require(app_js, "素材工坊只接商品草稿、图片需求或商家上传图", "media source boundary copy")
    require(app_js, "商家只需要看三件事：这张图用在哪里、能不能用、还缺什么", "media result readability copy")
    require(app_js, "先看草稿，再决定是否回写 Listing", "media quality board simple copy")
    require(app_js, "aria-label=\"素材进度\"", "media progress aria label")
    require(app_js, "saasMediaAssetJobsForDisplay", "media asset job display helper")
    require(app_js, "/media-asset-jobs?limit=8", "media asset jobs protected fetch")
    require(app_js, "素材清单（AssetManifest）", "media AssetManifest merchant copy")
    require(app_js, "没有清单就不能说已经可用于 Listing", "media manifest gate copy")
    require(app_js, "不会把旧测试图当成真实生成结果", "media no fake generated proof copy")
    require(app_js, "function saasCurrentListingProjectIdentity", "stable Listing project identity")
    require(app_js, "function saasMediaAssetJobMatchesListingProject", "media job current Listing match gate")
    require(app_js, "media_asset_job_product_mismatch_blocked_v1", "cross-product media writeback block contract")
    require(app_js, "function prepareSaasMediaStudioForCurrentListing", "Listing to media project handoff")
    require(app_js, "function sanitizeSaasListingComposerDraftSnapshot", "account-scoped Listing draft snapshot sanitizer")
    require(app_js, "2026-07-12-listing-media-restore-v3", "Listing and media refresh restore contract")
    require(app_js, "function restoreSaasListingComposerDraftFromBackendReports", "backend report Listing restore fallback")
    require(app_js, "function saasSafeListingAssetUrl", "safe same-origin media URL restore")
    require(app_js, "new URL(raw, window.location.origin)", "relative media URL canonicalization")
    require(app_js, "saveSaasProtectedStateSnapshot();", "media task updates persist account-scoped refresh state")
    require(app_js, "function scheduleSaasListingDraftSnapshotSave", "edited Listing drafts schedule account-scoped snapshot persistence")
    require(app_js, "可以导入为待补资料草稿", "fact-blocked AI CEO reports remain importable as blocked Listing drafts")
    require(app_js, "function resetSaasBulkWorkspaceForListingProject", "Listing product switch resets stale bulk state")
    require(app_js, "listing_project_key:", "media job snapshot keeps Listing project identity")

    require(app_js, "function saasListingSyncedProductRows", "eBay synced product extraction")
    require(app_js, "function renderSaasListingSyncedProductsPanel", "eBay synced product panel")
    require(app_js, "saas-listing-simple-head", "simple listing header")
    require(app_js, "function renderSaasListingComposerWorkspace", "Listing Composer workspace")
    require(app_js, "saasListingCeoHandoff", "AI CEO to Listing handoff state")
    require(app_js, "function shouldSaasCeoOfferListingHandoff", "AI CEO Listing handoff intent guard")
    require(app_js, "function syncSaasCeoCommandToListing", "AI CEO Listing handoff sync")
    require(app_js, 'return "general_chat"', "AI CEO ordinary consultation route")
    require(app_js, "function renderSaasCeoRoutingTaskCard", "AI CEO lightweight routing task card")
    require(app_js, "function isSaasAiCeoPlainConsultationTurn", "AI CEO plain consultation detail guard")
    require(app_js, "function shouldRecordSaasCeoCommandSourceRecord", "AI CEO plain consultation source-record guard")
    require(app_js, "!realtimeStatuses.includes(status)", "AI CEO realtime answers can still show source details")
    require(app_js, "function renderSaasAiCeoWorkRecordsMarkup", "AI CEO realtime answers can show work records")
    require(app_js, "function renderSaasAiCeoConfirmationItemsMarkup", "AI CEO realtime answers can show confirmation guidance")
    require(app_js, "真实动作不会绕过确认中心", "AI CEO confirmation guidance merchant copy")
    require(app_js, 'route !== "general_chat"', "AI CEO only records business commands as source records")
    require(app_js, "AI CEO 已接住", "AI CEO compact task card heading")
    require(app_js, "先去决策中心确认", "AI CEO compact risk handoff title")
    require(app_js, "saas-ceo-routing-main", "AI CEO compact task card layout")
    require(app_js, "ai_ceo_route_task_card_v2", "AI CEO route task card v2 marker")
    require(app_js, "下一步建议", "AI CEO route card next-step label")
    require(app_js, "不会自动执行真实动作", "AI CEO route card no-real-action copy")
    require(app_js, "点按钮后只打开对应工作台继续整理", "AI CEO route card clear next-step boundary")
    require(app_js, "function saasCeoRoutingWhyRows", "AI CEO routing why rows helper")
    require(app_js, "function saasCeoRoutingNextLine", "AI CEO routing next line helper")
    require(app_js, "AI CEO 路由确认", "AI CEO route card plain explanation aria label")
    require(app_js, "我理解", "AI CEO route card understood row")
    require(app_js, "推荐去", "AI CEO route card recommended module row")
    require(app_js, "安全边界", "AI CEO route card safety row")
    require(styles, ".saas-ceo-routing-why", "AI CEO route card three-row styling")
    require(app_js, "function saasCeoFirstDayClosureRows", "AI CEO first-day closure helper")
    require(app_js, "first_day_ai_ceo_closure_v1", "AI CEO first-day closure marker")
    require(app_js, "首日闭环", "AI CEO first-day closure copy")
    require(app_js, "先说目标", "AI CEO first-day starts with one goal")
    require(app_js, "去推荐模块", "AI CEO first-day route handoff")
    require(app_js, "回设置补连接", "AI CEO first-day settings continuation")
    require(styles, ".saas-ceo-route-closure", "AI CEO first-day closure styling")
    require(app_js, "继续小批量实验台", "AI CEO compact task card bulk next button")
    require(app_js, "一句话交给 AI CEO", "AI CEO low-learning-cost empty title")
    require(app_js, "first_day_ai_ceo_path_v2", "AI CEO first-day path marker")
    require(app_js, "比如：帮我调研这个商品，整理 Listing 草稿", "AI CEO low-learning-cost composer example")
    require(app_js, "也可以直接问普通问题。", "AI CEO low-learning-cost plain chat hint")
    require(app_js, "上传第一份商品资料", "AI CEO first-run blank workbench copy")
    require(app_js, "current.intent !== \"listing\"", "AI CEO prevents non-Listing intents from being hijacked by Listing")
    if "AI CEO 已收到，Listing 已接住这个目标。" in app_js:
        raise AssertionError("AI CEO Listing handoff should use the route card, not a mobile-covering toast")
    require(app_js, "请按市场结论 → Listing 草稿 → 素材/利润 → 发布确认的顺序整理；不要触发真实 eBay 写入。", "safe Listing handoff prompt")
    require(app_js, "来自 AI CEO", "Listing handoff merchant label")
    require(app_js, 'state.saasListingSourceMode = "ai_ceo_handoff"', "AI CEO handoff source mode")
    require(app_js, "function saasListingComposerDraftFromText", "Listing Composer local draft builder")
    require(app_js, 'String(priceMatch[1] || priceMatch[0] || "").trim()', "Listing price parser fallback without capture group")
    require(app_js, "function saasListingDraftFromReport", "AI CEO report import into Listing")
    require(
        app_js,
        "function saasAiCeoMarketReportCanStartBlockedListingDraft",
        "AI CEO candidate reports can enter Listing as blocked drafts before supplier facts are complete",
    )
    require(
        app_js,
        "ai_ceo_candidate_report_to_blocked_listing_draft_v1",
        "AI CEO candidate-to-blocked-Listing contract marker",
    )
    if 'if (handoff.ready_for_listing_draft !== true) return null;' in app_js:
        raise AssertionError(
            "AI CEO candidate reports must not be rejected from Listing only because publish facts are incomplete"
        )
    require(
        app_js,
        "候选商品已导入为待补资料草稿",
        "merchant sees that candidate import succeeded while publish facts remain blocked",
    )
    app_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", app_html)
    index_versions = re.findall(r"\./app\.js\?v=([A-Za-z0-9._-]+)", index_html)
    if len(app_versions) != 1 or index_versions != [app_versions[0], app_versions[0]]:
        raise AssertionError("public and workspace entries must share one current versioned Listing bundle")
    require(
        app_js,
        "function saasAccountScopedEbayPublishPrefillFromPacket",
        "new Listing reuses account-scoped eBay policies and location from the official packet",
    )
    require(
        app_js,
        "account_scoped_ebay_publish_prefill_v1",
        "account-scoped publish prefill contract marker",
    )
    require(
        app_js,
        "publishPrefill.merchant_location_key || accountPrefill.merchant_location_key",
        "official account inventory location prefills the new Listing form",
    )
    require(
        app_js,
        "publishPrefill.fulfillment_policy_id || accountPrefill.fulfillment_policy_id",
        "official fulfillment policy prefills the new Listing form",
    )
    require(app_js, "function selectSaasListingMarketCandidate", "merchant can select one AI CEO candidate")
    require(app_js, 'data-saas-listing-candidate-id="${escapeHtml(candidate.candidate_id)}"', "candidate selection control")
    require(app_js, 'aria-pressed="${candidate.name === opportunity.product ? "true" : "false"}"', "candidate selected state")
    require(app_js, "candidate_switch_resets_unverified_fields_v1", "candidate switch clears product-specific fields")
    require(app_js, "已切换到“${selected.name}”", "candidate switch merchant feedback")
    require(app_js, "function latestSaasActionableProductReportByTypes", "Listing prefers reports with a concrete product")
    require(app_js, "saas_report_import_prefers_concrete_product_v1", "concrete report selection contract")
    require(app_js, 'latestSaasActionableProductReportByTypes(["listing.package", "product.listing"])', "actionable Listing report selection")
    require(app_js, 'latestSaasActionableProductReportByTypes(["ai_ceo.market_research", "market.report", "market.data_packet"])', "actionable market report selection")
    require(app_js, "function saasAuthoritativeAiCeoMarketReportForTurn", "backend-authoritative AI CEO report resolver")
    require(app_js, 'const reportId = String(latest?.market_report_id || "").trim();', "exact backend report id authority")
    require(app_js, 'item?.report_id === reportId && item?.report_type === "ai_ceo.market_research"', "AI CEO authority forbids cross-report fallback")
    require(app_js, "我帮你选的品|产品名称", "legacy AI answer named product recovery")
    require(app_js, "text.match(/市场调研报告", "legacy AI report title product recovery")
    require(app_js, "saasIsConcreteProductLabel(draft.product)", "generic draft title cannot become a product")
    require(app_js, "if (!saasIsConcreteProductLabel(product)) return null;", "Listing import rejects unresolved product")
    require(app_js, "(?:这个选品|这个商品|这个产品)", "legacy follow-up product phrase recovery")
    require(app_js, "function saasListingDraftFromSyncedProduct", "synced eBay product import into Listing")
    require(app_js, "function renderSaasListingSourceCards", "Listing three source entry cards")
    require(app_js, "function renderSaasListingStatusBar", "Listing compact status bar")
    require(app_js, "function renderSaasListingDraftEditor", "Listing editable draft editor")
    require(app_js, "function renderSaasListingWorkflowProofPanel", "Listing workflow loop result panel")
    require(app_js, "function handleSaasListingComposeDraft", "Listing Composer action handler")
    require(app_js, "function startSaasListingBackendWorkflow", "Listing backend workflow action handler")
    require(app_js, "function buildSaasListingBackendWorkflowPayload", "Listing backend workflow payload builder")
    require(app_js, "function handleSaasListingSourceAiReport", "Listing AI report source action")
    require(app_js, 'if (action === "listing-compose-draft")', "Listing Composer event wiring")
    require(app_js, 'if (action === "listing-start-backend-workflow")', "Listing backend workflow event wiring")
    require(app_js, 'if (action === "listing-source-ai-report")', "Listing AI report source event wiring")
    require(app_js, 'data-saas-action="listing-start-backend-workflow"', "Listing backend workflow primary action")
    require(app_js, 'saasFetch("/tasks/product-workflow"', "Listing workflow calls product workflow backend")
    require(app_js, 'run_mode: "inline"', "Listing workflow runs inline safe backend loop")
    require(app_js, 'source_mode: "listing_composer"', "Listing workflow source mode")
    require(app_js, "listing_intake", "Listing workflow persists sanitized intake")
    require(app_js, "no_real_platform_write: true", "Listing workflow cannot be a platform write")
    require(app_js, "real_platform_writes_enabled: false", "Listing workflow explicitly disables real writes")
    require(app_js, "saas-listing-input-panel", "Listing simple input panel")
    require(app_js, "商品资料入口", "Listing input entry label")
    require(app_js, "把你手上的资料直接放进来", "Listing low-learning-cost input headline")
    require(app_js, "function renderSaasListingSourceIntake", "Listing source intake renderer")
    require(app_js, 'data-listing-source-details="listing_source_collapsed_after_draft_v1"', "Listing source intake collapses after draft")
    require(app_js, "更换或补充商品资料", "Listing collapsed source intake merchant label")
    require(app_js, "当前草稿已生成；只有换商品或补链接、图片、成本、规格时再展开", "Listing collapsed source intake guidance")
    require(app_js, "draft ? renderSaasListingSourceIntake", "Listing source intake switches to collapsed mode after draft")
    require(app_js, "data-saas-listing-input-chip", "Listing input quick chips")
    require(app_js, "function renderSaasFirstRunAssuranceStrip", "shared first-run assurance strip")
    require(app_js, "不用完整", "Listing simple first-run copy")
    require(app_js, "缺口会停住", "Listing gap stops copy")
    require(app_js, "不直接发布", "Listing no direct publish copy")
    require(app_js, 'event.target.closest("[data-saas-listing-input-chip]")', "Listing input chip event wiring")
    require(app_js, 'data-listing-primary-flow="product-facts_draft_assets_confirmation_v1"', "Listing default four-step merchant path")
    require(app_js, 'data-listing-advanced-checks="listing_advanced_checks_collapsed_v1"', "Listing advanced checks stay collapsed")
    require(app_js, "opportunity ? renderSaasListingGapAndRiskPanel(draft, opportunity) : \"\"", "Listing risk cards move to advanced details")
    require(app_js, "opportunity ? renderSaasListingOpportunityPanel(opportunity) : \"\"", "Listing opportunity card moves to advanced details")
    require(app_js, "saas-listing-v2-workbench", "Listing v2 first screen")
    require(app_js, "saas-listing-v2-status-bar", "Listing v2 compact status bar")
    require(app_js, "saas-listing-workflow-proof", "Listing workflow loop result styling hook")
    require(app_js, "经营链路已生成", "Listing workflow loop completed copy")
    require(app_js, "真实发布仍由决策中心放行", "Listing workflow confirmation boundary copy")
    require(app_js, "Listing 刊登状态", "Listing status aria label")
    require(app_js, 'title: "市场结论"', "Listing status includes market conclusion step")
    require(app_js, 'title: "素材/利润"', "Listing status includes asset/profit step")
    require(app_js, 'value: hasDraft ? "可补字段" : "等待草稿"', "Listing publish data status value")
    require(app_js, "saas-listing-v2-source-grid", "Listing v2 source selector")
    require(app_js, "saas-listing-v2-draft-editor", "Listing v2 draft editor")
    require(app_js, "saas-listing-v2-draft-layout", "Listing draft editor split layout")
    require(app_js, "saas-listing-v2-draft-primary", "Listing draft primary copy column")
    require(app_js, "saas-listing-v2-draft-side", "Listing draft compact parameter column")
    require(app_js, "saas-listing-v2-draft-side-grid", "Listing draft side field grid")
    require(app_js, "options.compact ? \"is-compact\" : \"\"", "Listing compact field styling hook")
    require(app_js, "data-saas-listing-draft-field", "Listing draft field persistence")
    require(app_js, "merchant_product_fact_packet_v1", "merchant product fact packet contract")
    require(app_js, "function saasMerchantProductFactPacket", "merchant product fact packet builder")
    require(app_js, "function renderSaasMerchantProductFactsModule", "merchant product facts module")
    require(app_js, "function saveSaasMerchantProductFacts", "merchant product facts save behavior")
    require(app_js, 'saasFetch(`/stores/${encodeURIComponent(store.store_id)}/product-facts`', "product facts persist to account work records")
    require(app_js, "data-saas-product-fact-field", "merchant product fact editable fields")
    require(app_js, 'data-saas-action="save-merchant-product-facts"', "merchant product fact save action")
    require(app_js, "来源资料", "product fact source-confirmed label")
    require(app_js, "商家确认", "product fact merchant-confirmed label")
    require(app_js, "AI 建议", "product fact AI suggestion label")
    require(app_js, "待补资料", "product fact unknown label")
    require(app_js, "图片商业使用权", "product image rights field")
    require(app_js, "不用去 eBay 手工填写", "Jiejing-first Listing editing copy")
    require(app_js, "function localQaForcesSaasPublicMvpMode", "local-only public SaaS QA switch")
    require(app_js, 'qaMode === "public-saas" || qaMode === "listing-v2-workbench" || qaMode === "ai-ceo-market-report-handoff"', "local QA listing route")
    require(app_js, 'params.get("onboarded") === "1"', "app direct route respects explicit onboarded query")
    require(app_js, "const saasProtectedViewAliases", "merchant URL aliases for protected SaaS views")
    require(app_js, 'listing: "product"', "Listing URL alias routes to product workspace")
    require(app_js, "saas-listing-publish-flow", "Listing direct publish check flow")
    require(app_js, "const safeListingDraft = saasListingDraftHasConcreteProduct(state.saasListingComposerDraft)", "Listing publish form validates concrete product facts")
    require(app_js, "const showPublishFlow = Boolean(safeListingDraft || hasLiveListing)", "Listing publish form hidden until a safe draft or listing package")
    require(app_js, "${showPublishFlow ? `", "Listing publish form is gated after a draft exists")
    require(app_js, "店铺连接和账号配置已经归到设置", "Listing internal evidence moved to settings copy")
    require(app_js, "function renderSaasPublishConfirmationIntakePanel", "new product publish confirmation intake")
    require(app_js, "function saasPublishIntakePrefillValues", "Listing draft to publish form prefill")
    require(app_js, "function renderSaasPublishInputField", "publish form input helper")
    require(app_js, "function renderSaasPublishTextareaField", "publish form textarea helper")
    require(app_js, "function renderSaasPublishFormGroup", "publish form business grouping")
    require(app_js, "function renderSaasPublishReadinessStrip", "publish form completion strip")
    require(app_js, "function renderSaasPublishPreflightGuide", "merchant publish preflight guide")
    require(app_js, "function renderSaasPublishPretestResultSlot", "Listing pretest result slot")
    require(app_js, "saas-listing-pretest-result", "Listing pretest result slot markup")
    require(app_js, "saas-publish-guide-panel", "publish guide panel")
    require(app_js, '<section class="saas-publish-raw-form-details" aria-label="上架资料补全清单">', "expanded publish completion form")
    require(app_js, "saas-publish-raw-form-head", "expanded full publish form head")
    require(app_js, "saas-publish-readiness-strip", "publish completion strip markup")
    require(app_js, "草稿会先自动带入", "draft auto-prefill copy")
    require(app_js, "把草稿变成可体检的发布包", "Listing publish completion product copy")
    require(app_js, "基础信息", "publish form base group")
    require(app_js, "平台参数", "publish form platform group")
    require(app_js, "价格利润", "publish form finance group")
    require(app_js, "物流履约", "publish form fulfillment group")
    require(app_js, "素材描述", "publish form asset group")
    require(app_js, "fields.title || draft?.title", "draft title prefill source")
    require(app_js, "parseSaasKeyValueLines(itemSpecifics)", "item specifics prefill parser")
    require(app_js, "const evidenceText = [logisticsText, clean].filter(Boolean).join", "full merchant input logistics prefill source")
    require(app_js, 'clean.match(/https?:\\/\\/[^\\s,，；;]+/gi)', "image URL prefill from merchant input")
    require(app_js, "上架资料补全", "Listing publish data completion step")
    require(app_js, "按基础、价格利润、素材描述、平台参数和物流履约往下补", "Listing ordered publish flow copy")
    require(app_js, "function saasListingMerchantSourceLabel", "Listing merchant-facing source label helper")
    require(app_js, "已有 AI CEO 市场结论或上架草稿，可以作为上架依据", "Listing report import uses merchant-facing copy")
    require(app_js, "店铺连接和授权配置在设置里", "Listing settings boundary copy")
    require(app_js, '<span class="pill green">草稿</span>', "Listing draft pill uses merchant-facing label")
    require(app_js, "const productLabel = saasWorkflowProductLabel(latestTask) || saasModelValueProductLabel", "model value product label is defined before request")
    require(app_js, "function saasModelValueFailureMessage", "precise model value failure toast")
    require(app_js, "AI 连接返回错误，可能是模型名、额度、账号状态或网络超时需要复核", "merchant-facing model failure reason")
    require(app_js, "设置总览", "settings readable overview")
    require(app_html, "只让你处理真正要拍板的事", "decision center low-learning-cost headline")
    require(app_html, "没有重要动作时，这里保持安静", "decision center quiet empty-state promise")
    require(app_html, "全部待办", "decision center non-technical secondary filter")
    require(app_html, "saas-confirm-action-model", "decision center light action model")
    require(app_html, "你没点头前不会执行", "decision center no-action-without-approval promise")
    require(app_js, "只让你处理真正要拍板的事", "rendered decision center low-learning-cost headline")
    require(app_js, "这里只做三种选择：同意、稍后、回去补资料。", "rendered decision center simple action copy")
    require(app_js, "刷新待办", "rendered decision center non-technical refresh copy")
    require(app_js, "saas-confirm-card-decision", "rendered decision card frontloads merchant choice")
    require(app_js, "saas-confirm-safety-detail", "rendered decision card folds backend evidence")
    require(app_js, 'data-saas-action="revise-confirmation"', "decision center offers a real revise action")
    require(app_js, "async function reviseSaasConfirmation", "decision center revise handler")
    require(app_js, 'decision: "modify"', "decision center revise records needs-revision semantics")
    revision_start = app_js.index("async function reviseSaasConfirmation")
    revision_end = app_js.index("async function approveFirstSaasConfirmation", revision_start)
    revision_block = app_js[revision_start:revision_end]
    if "/preflight" in revision_block or "/execute" in revision_block:
        return fail("decision center revise action must never enter preflight or execution")
    require(app_js, "为什么停住", "rendered decision card keeps evidence behind plain-language disclosure")
    require(app_js, "普通商家只看 5 个入口", "settings map merchant entrance boundary")
    require(app_js, "这里处理账号、店铺数据、AI、权限、套餐付款与安全", "settings home low-learning-cost copy")
    require(app_js, "不展示技术排查和部署细节", "settings home hides technical diagnostics")
    require(app_js, "商品、订单、政策、费用等来源可追溯", "settings status merchant-facing data copy")
    require(app_js, "店铺数据、来源记录和同步缺口", "settings data panel merchant-facing title")
    require(app_js, "什么时候需要打开设置", "settings usage-rule section")
    require(app_js, "主理人高级区", "settings workflow compact boundary")
    require(app_js, "登录、eBay 店铺连接和安全边界", "account settings uses merchant-facing connection copy")
    require(app_js, "官方连接返回地址", "account settings avoids callback wording")
    require(app_js, "权限围绕捷境确认中心设计", "governance settings uses Jiejing-owned permission copy")
    require(app_js, "AI 与素材", "merchant-friendly model settings title")
    require(app_js, "账号 AI 已连接", "model settings uses merchant-facing AI connection copy")
    require(app_js, "AI CEO 当前可使用捷境试用额度", "platform trial stays distinct from merchant account AI")
    require(app_js, ': !configured\n      ? "暂未开放"', "unavailable platform trial never shows a usable quota")
    require(app_js, "账号 AI 或捷境试用 AI", "merchant setup guide accepts account AI or platform trial AI")
    require(app_js, "优先用账号自己的 AI；没有账号 AI 时使用捷境试用 AI 的有限额度", "model value proof request uses BYOK first then trial AI")
    require(app_js, "图片和视频仍由素材工坊生成并审核", "model settings explains media review before listing use")
    require(app_js, "估算文字用量", "model usage ledger avoids raw token wording")
    require(app_js, "function saasIsEnglishHeavyMerchantText", "legacy English report display guard")
    require(app_js, "旧记录的英文摘要已隐藏", "legacy English report summary hidden")
    require(app_js, "function saasWorkbenchFormatReportSectionValue", "report detail Chinese display guard")

    listing_start = app_js.index("function renderSaasProductListingCenter")
    listing_end = app_js.index("function renderProductListingCenter", listing_start)
    listing_body = app_js[listing_start:listing_end]
    require(listing_body, "setJiejingTrustedHtml(", "Listing daily surface uses trusted HTML sink")
    require(listing_body, 'trustedJiejingHtml(`', "Listing daily surface wraps generated markup")
    if "view.innerHTML =" in listing_body:
        raise AssertionError("Listing daily surface must not write generated markup with raw view.innerHTML")
    disabled_internal_index = listing_body.find("${false ? `")
    active_listing_body = listing_body[:disabled_internal_index] if disabled_internal_index >= 0 else listing_body
    publish_intake_index = listing_body.index("renderSaasPublishConfirmationIntakePanel(ctx")
    minimal_index = listing_body.index("renderSaasListingComposerWorkspace")
    show_publish_flow_index = listing_body.index("const showPublishFlow = Boolean")
    publish_flow_index = listing_body.index("saas-listing-publish-flow")
    boundary_index = listing_body.index("saas-listing-composer-boundary")
    if not (show_publish_flow_index < minimal_index < publish_flow_index < publish_intake_index < boundary_index):
        raise AssertionError("Listing daily surface must flow from composer to publish data completion to final confirmation boundary")
    composer_start = app_js.index("function renderSaasListingComposerWorkspace")
    composer_end = app_js.index("function renderSaasListingMinimalWorkspace", composer_start)
    composer_body = app_js[composer_start:composer_end]
    source_intake_start = app_js.index("function renderSaasListingSourceIntake")
    source_intake_body = app_js[source_intake_start:composer_start]
    input_panel_index = source_intake_body.index("saas-listing-input-panel")
    source_cards_index = source_intake_body.index("renderSaasListingSourceCards")
    if not input_panel_index < source_cards_index:
        raise AssertionError("Listing source alternatives must stay below the primary product input")
    source_intake_call_index = composer_body.index("renderSaasListingSourceIntake")
    product_facts_index = composer_body.index("renderSaasMerchantProductFactsModule")
    draft_editor_index = composer_body.index("renderSaasListingDraftEditor")
    media_index = composer_body.index("renderSaasListingMediaWritebackPanel")
    next_action_index = composer_body.index("renderSaasListingNextActionPanel")
    advanced_index = composer_body.index("renderSaasListingAdvancedWorkDetails")
    if not (source_intake_call_index < product_facts_index < draft_editor_index < media_index < next_action_index < advanced_index):
        raise AssertionError("Listing daily surface must flow from source selection to product facts, draft, media, one next action, then collapsed advanced checks")
    next_action_start = app_js.index("function renderSaasListingNextActionPanel")
    next_action_end = app_js.index("function renderSaasListingWorkflowProofPanel", next_action_start)
    next_action_body = app_js[next_action_start:next_action_end]
    for receipt_marker in (
        "saasLatestPublishConfirmation()",
        "saasExecutionResultForConfirmation",
        "查看发布回执",
        "已记录安全交接",
        "已确认，等待回执",
    ):
        require(next_action_body, receipt_marker, "Listing visible confirmation and execution receipt state")
    for advanced_only in (
        "renderSaasListingStatusBar",
        "renderSaasListingWorkflowProofPanel",
        "renderSaasListingOpportunityPanel",
        "renderSaasListingGapAndRiskPanel",
    ):
        if advanced_only in composer_body:
            raise AssertionError(f"Listing default composer must not render advanced-only panel directly: {advanced_only}")
    for internal_marker in [
        "Listing Package",
        "Market Report",
        "数据包",
        "后台证据",
        "local draft",
        "可导入报告",
        "极简开始",
    ]:
        if internal_marker in composer_body:
            raise AssertionError(f"Listing daily composer should not show internal/debug copy: {internal_marker}")
    for internal_marker in [
        "后台岗位",
        "后台入口",
        "后台结果",
        "后台菜单",
        "后台工作模块",
        "后台可自动推进",
        "AI CEO汇总后台",
        "AI CEO 汇总后台",
    ]:
        if internal_marker in app_js + app_html:
            raise AssertionError(f"Core SaaS copy should not expose old internal workflow wording: {internal_marker}")
    confirm_start = app_html.index('id="view-confirm"')
    confirm_end = app_html.index('id="view-service"', confirm_start)
    confirm_body = app_html[confirm_start:confirm_end]
    rendered_confirm_start = app_js.index("function renderSaasConfirmPanel")
    rendered_confirm_end = app_js.index("function saasRealBackendBindingStatus", rendered_confirm_start)
    rendered_confirm_body = app_js[rendered_confirm_start:rendered_confirm_end]
    for internal_marker in [
        "高级细节",
        "上线检查",
        "后台",
        "运维",
        "preflight",
        "packet",
        "provider",
    ]:
        if internal_marker in confirm_body:
            raise AssertionError(f"Decision center should remain a simple confirmation surface: {internal_marker}")
        if internal_marker in rendered_confirm_body:
            raise AssertionError(f"Rendered decision center should remain a simple confirmation surface: {internal_marker}")
    settings_map_start = app_js.index("function renderSaasSettingsReadableMap")
    settings_map_end = app_js.index("function renderSaasBillingProviderPanel", settings_map_start)
    settings_map_body = app_js[settings_map_start:settings_map_end]
    for internal_marker in [
        "packet",
        "callback",
        "Provider Hub",
        "settings-only",
    ]:
        if internal_marker in settings_map_body:
            raise AssertionError(f"Settings map should use merchant-facing wording: {internal_marker}")
    account_panel_start = app_js.index("function renderSaasSettingsAccountPanel")
    account_panel_end = app_js.index("function renderSaasSettingsAccountAccessPanel", account_panel_start)
    account_panel_body = app_js[account_panel_start:account_panel_end]
    for internal_marker in [
        "正式回调地址",
        "回调地址",
        "eBay token",
        "token 和 AI 连接凭证",
        "callback",
        "OAuth",
        "secret_ref",
        "Vault",
    ]:
        if internal_marker in account_panel_body:
            raise AssertionError(f"Account settings panel should use merchant-facing wording: {internal_marker}")
    platform_panel_start = app_js.index("function renderSaasSettingsPlatformPanel")
    platform_panel_end = app_js.index("function renderSaasSettingsDataPanel", platform_panel_start)
    platform_panel_body = app_js[platform_panel_start:platform_panel_end]
    require(platform_panel_body, "当前只管理 eBay", "account settings stay eBay-first")
    for unopened_platform in ["Amazon", "TikTok Shop", "Temu / Shopify"]:
        if unopened_platform in platform_panel_body:
            raise AssertionError(f"Account settings should not advertise an unopened platform: {unopened_platform}")
    model_panel_start = app_js.index("function renderSaasMerchantModelProviderPanel")
    model_panel_end = app_js.index("function renderSaasMerchantMemoryPanel", model_panel_start)
    model_panel_body = app_js[model_panel_start:model_panel_end]
    require(model_panel_body, 'id="saas-model-provider"', "AI provider selector is visible in the setup flow")
    require(model_panel_body, 'provider.supported_live_adapter ? "" : "disabled"', "unsupported AI providers stay disabled")
    permission_panel_start = app_js.index("function renderSaasMerchantPermissionPanel")
    permission_panel_end = app_js.index("function renderSaasMerchantProviderHubPanel", permission_panel_start)
    permission_panel_body = app_js[permission_panel_start:permission_panel_end]
    for required_marker in [
        "saas-permission-current-role",
        "saas-permission-role-details",
        "查看其他岗位权限",
        "添加团队成员或调整分工时再查看完整岗位说明",
    ]:
        require(permission_panel_body, required_marker, "Permission settings default to the current merchant role")
    for internal_marker in [
        "借鉴 Shopify",
        "把 Shopify 加进捷境",
        "成熟的后台权限方法",
    ]:
        if internal_marker in permission_panel_body:
            raise AssertionError(f"Permission settings panel should stay Jiejing-owned: {internal_marker}")
    one_glance_start = app_js.index("function saasSettingsOneGlanceRows")
    one_glance_end = app_js.index("function renderSaasBillingProviderPanel", one_glance_start)
    one_glance_body = app_js[one_glance_start:one_glance_end]
    for required_marker in [
        "function renderSaasSettingsOneGlanceStrip",
        "saas-settings-one-glance",
        "本页重点",
        "先看状态，再处理需要补齐的项目",
        "普通聊天不进长期经营记忆",
        "只给主理人管理员",
    ]:
        require(one_glance_body, required_marker, "settings child pages have one-glance merchant summary")
    settings_def_start = app_js.index("function saasSettingsTabDefinitions")
    settings_def_end = app_js.index("function renderSaasSettingsCleanLayout", settings_def_start)
    settings_def_body = app_js[settings_def_start:settings_def_end]
    tab_labels = re.findall(r'\n\s*label:\s*"([^"]+)"', settings_def_body)
    expected_tab_labels = ["账号与店铺", "AI 与素材", "店铺数据", "团队权限", "套餐与付款"]
    if tab_labels != expected_tab_labels:
        raise AssertionError(f"Merchant Settings must expose exactly five merchant tabs: {tab_labels}")
    for required_marker in [
        "renderSaasSettingsAccountAccessPanel()",
        "renderSaasSettingsPlatformPanel(ctx)",
        "renderSaasSettingsAccountPanel(ctx, options)",
        "renderSaasMerchantModelProviderPanel(ctx)",
        "renderSaasSettingsDataPanel(ctx)",
        "renderSaasMerchantPermissionPanel()",
        "renderSaasMerchantBillingPlainSummaryPanel(ctx)",
        "renderSaasMerchantBillingCustomerTrustPanel(ctx)",
        "renderSaasMerchantPricingModelPanel(ctx)",
        "renderSaasMerchantBillingContinuityPanel(ctx)",
        "renderSaasMerchantSecurityBoundaryPanel()",
    ]:
        require(settings_def_body, required_marker, "settings five merchant tabs keep their merchant controls")
    for forbidden_marker in [
        'id: "general"',
        'id: "owner_ops"',
        "saasOwnerLaunchCanView()",
        "renderSaasOwnerLaunchControlPanel()",
        "renderSaasOwnerOperationsOverviewPanel()",
        "renderSaasBillingTransitionPathPanel(ctx)",
        "renderSaasManualBetaPaymentOrderPanel()",
        "renderSaasBillingDomainCutoverReviewPanel(ctx)",
        "renderSaasBillingPaidLaunchBlockersPanel(ctx)",
        "renderSaasMerchantBillingIncidentRunbookPanel(ctx)",
        "renderSaasMerchantFormalPaymentOpeningChecklistPanel(ctx)",
        "renderSaasPublicSecurityStatusPanel()",
        "renderSaasEdgeCutoverReadinessPanel()",
        "renderSaasQueueHealthPanel()",
        "renderSaasCommercialLaunchGatePanel()",
        "主理人高级区",
        "正式收费和公网安全",
        "运行可靠性",
        "主理人上线排查",
    ]:
        if forbidden_marker in settings_def_body:
            raise AssertionError(f"Merchant Settings must not contain internal owner control: {forbidden_marker}")
    billing_tab_start = settings_def_body.index('id: "billing"')
    billing_tab_body = settings_def_body[billing_tab_start:]
    for required_marker in [
        'title: "计费与安全说明"',
        'badge: "按需查看"',
    ]:
        require(billing_tab_body, required_marker, "merchant billing keeps secondary explanations collapsed")
    for forbidden_marker in [
        "renderSaasBillingTransitionPathPanel(ctx)",
        "renderSaasManualBetaPaymentOrderPanel()",
        "renderSaasMainlandPaymentStrategyPanel()",
        "renderSaasMerchantFormalPaymentOpeningChecklistPanel(ctx)",
    ]:
        if forbidden_marker in billing_tab_body:
            raise AssertionError(f"Ordinary merchant billing tab must not render internal payment operation panel: {forbidden_marker}")
    for forbidden_marker in [
        "renderSaasMainlandPaymentStrategyPanel()",
        "renderSaasBillingProviderPanel()",
        "renderSaasBillingProviderRehearsalPanel(ctx)",
    ]:
        if forbidden_marker in settings_def_body:
            raise AssertionError(f"Merchant settings must not render internal payment strategy: {forbidden_marker}")
    for removed_marker in [
        "/auth/qr-login/status",
        "qr-login-placeholder",
        "qr_login_boundary_v1",
        "authQrLogin",
        "entryQrLogin",
    ]:
        if removed_marker in app_js or removed_marker in index_html:
            raise AssertionError(f"QR login should not be exposed in the current login path: {removed_marker}")
    ordinary_settings_body = settings_def_body
    for redundant_marker in [
        "renderSaasSettingsAccountFocusPanel(ctx)",
        "renderSaasSettingsModelFocusPanel(ctx)",
        "renderSaasSettingsDataFocusPanel(ctx)",
        "renderSaasSettingsGovernanceFocusPanel()",
        "renderSaasSettingsBillingFocusPanel(ctx)",
        "renderSaasMerchantBillingCurrentStatusPanel(ctx)",
        "renderSaasBillingProviderRehearsalPanel(ctx)",
        "renderSaasBillingDomainCutoverReviewPanel(ctx)",
        "renderSaasBillingPaidLaunchBlockersPanel(ctx)",
        "renderSaasMerchantBillingIncidentRunbookPanel(ctx)",
        "账号健康和事故处理",
        "来源记录和可信度",
        "用量和成本",
        "风险、记忆和长期规则",
    ]:
        if redundant_marker in ordinary_settings_body:
            raise AssertionError(f"Ordinary settings tabs should not use folded diagnostic groups: {redundant_marker}")
    settings_layout_start = app_js.index("function renderSaasSettingsCleanLayout")
    settings_layout_end = app_js.index("function renderSaasConnectCenter", settings_layout_start)
    settings_layout_body = app_js[settings_layout_start:settings_layout_end]
    require(settings_layout_body, 'activeTab.id === "general"', "settings overview-only map guard")
    require(settings_layout_body, 'isOverview ? renderSaasSettingsReadableMap(activeTab.id) : ""', "settings child pages skip redundant map")
    require(settings_layout_body, 'isOverview ? renderSaasSettingsOneGlanceStrip(activeTab.id) : ""', "settings one-glance summary stays overview-only")
    settings_connect_start = app_js.index("function renderSaasConnectCenter")
    settings_connect_end = app_js.index("function renderConnect", settings_connect_start)
    settings_connect_body = app_js[settings_connect_start:settings_connect_end]
    settings_trusted_sink_index = settings_connect_body.index("setJiejingTrustedHtml(")
    executed_settings_connect_body = settings_connect_body[: settings_connect_body.index("return;", settings_trusted_sink_index)]
    require(executed_settings_connect_body, "setJiejingTrustedHtml(", "settings active render path uses trusted HTML sink")
    require(executed_settings_connect_body, '"settings.clean_layout"', "settings active render path trusted label")
    if "view.innerHTML =" in executed_settings_connect_body:
        raise AssertionError("Settings active render path must not use raw view.innerHTML")
    render_connect_start = app_js.index("function renderConnect")
    render_connect_end = app_js.index("function riskText", render_connect_start)
    render_connect_body = app_js[render_connect_start:render_connect_end]
    require(render_connect_body, '"settings.legacy_connect_status"', "settings legacy status trusted label")
    if "connectStatusEl.innerHTML" in render_connect_body:
        raise AssertionError("Settings legacy connection status must not use raw innerHTML")
    for internal_fetch_marker in [
        "function saasCanViewPlatformInternalFromPermissions",
        "const canViewPlatformInternal = saasCanViewPlatformInternalFromPermissions(corePermissions);",
        "/owner/launch-control",
        "/security/staging-gate",
        "/billing/payment-options",
        "/vault/status",
        "/database/plan",
        "/backup/plan",
        "/queue/plan",
        "/provider-job-contracts",
    ]:
        if internal_fetch_marker in app_js:
            raise AssertionError(f"Merchant app must not contain role-hidden internal fetch code: {internal_fetch_marker}")
    require(app_js, "function merchantSafeSaasBillingPlan", "ordinary merchant billing state sanitizer")
    require(app_js, "delete safePlan.payment_strategy;", "ordinary merchant billing plan must drop internal payment strategy")
    require(app_js, "delete safePlan.billing_live_cutover_matrix;", "ordinary merchant billing plan must drop internal live cutover matrix")
    require(app_js, "delete safePlan.billing_live_cutover_summary;", "ordinary merchant billing plan must drop internal live cutover summary")
    require(app_js, "state.saasBillingPlan = merchantSafeSaasBillingPlan(rawBillingPlan);", "billing plan must be sanitized before ordinary UI state")
    for billing_model_marker in [
        "基础订阅保留工作台",
        "AI 用量和素材生成单独核算",
        "subscription_ai_media_platform_v1",
        "saas-merchant-pricing-split",
        "用量计费路线",
        "套餐权益、商家模型、素材点和平台成本清楚可查",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "高成本联网任务",
        "付款前显示套餐、金额、30 天期限和用量边界",
        "订阅和用量总览",
        "付费套餐包含当期生图素材点",
        "当前是否扣费",
        "套餐决定店铺数、席位数、经营任务和批量上限",
        "DeepSeek、OpenAI 等文本模型由商家账号连接并直接承担模型费用",
        "merchant_billing_plain_summary_v1",
        "subscription_metering_clarity_v2",
        "billing_now_no_real_charge",
        "base_subscription_is_feature_fee=true",
        "merchant_media_points_v2",
        "platform_cost_not_collected_by_jiejing=true",
        "订阅开通路径",
        "试用先提交申请，正式付款开放后走安全支付页",
        "merchant_subscription_request_path_v1",
        "merchant_beta_request_no_real_charge",
        "merchant_request_requires_service_confirmation",
        "formal_checkout_uses_hosted_payment_page",
        "entitlement_grant_requires_billing_state",
        "试用订阅申请已生成",
        "订阅开通说明",
        "微信扫码、到账确认、权益开通和自主续购",
        "微信扫码付款可用",
        "商家主动微信扫码",
        "后端验签确认后开通",
        "到期后由商家自主续购",
        "浏览器不保存支付资料",
        "merchant_subscription_activation_path_v2",
        "quota_grant_not_frontend_driven",
        "static_qr_never_paid_launch_provider",
        "订阅和额度生效方式",
        "主动扫码付款，系统确认后开通",
        "每次购买 30 天",
        "系统确认到账后开通",
        "到期后由商家自主续购",
        "支付资料不进入浏览器",
        "账单恢复不重连店铺或 AI",
        "只停高成本任务",
        "merchant_billing_launch_path_v1",
        "payment_page_mode=",
        "backend_confirmation_required_before_entitlement=true",
        "frontend_cannot_grant_entitlement_or_quota",
        "billing_recovery_does_not_require_reconnecting_store_or_ai=true",
        "试用订阅申请",
        "申请开通基础套餐，确认后显示可用期限",
        "merchant_beta_subscription_request_v2",
        "当前阶段",
        "试用模式，不真实扣费",
        "高成本用量",
        "操作记录和账号设置继续保留",
        "不需要重复连接店铺，也不需要重填 AI 连接",
        "当前计费状态",
        "先看能不能继续用，再看哪些费用另算",
        "费用四分法",
        "平台经营成本",
        "eBay、物流、广告和退款由商家平台账户结算",
        "试用模式，不真实扣费",
        "merchant_visible_billing_status_v1",
        "merchant_subscription_shutdown_closure_v2",
        "billing_never_deletes_audit_records",
        "billing_blocks_metered_work_only",
        "no_repeat_oauth_for_billing_recovery",
        "no_model_key_reentry_for_billing_recovery",
        "merchant_billing_incident_runbook_v1",
        "wechat_order_expired",
        "wechat_callback_delayed",
        "payment_mode=",
        "refund_dispute_webhook_sets_payment_attention",
        "refund_or_dispute_cannot_be_frontend_executed",
        "payment_failed_cancel_blocks_metered_work",
        "quota_shutdown_keeps_history_visible",
        "browser_cannot_grant_or_restore_entitlement",
        "merchant_billing_customer_trust_packet_v2",
        "wechat_native_qr_payment_boundary",
        "merchant_confirmed_one_time_30_day_renewal",
        "payment_record_is_not_tax_invoice",
        "invoice_request_requires_paid_order_and_service_review",
        "billing_support_refund_links_visible",
        "entitlement_recovery_does_not_repeat_ebay_oauth",
        "正式支付接入前演练",
        "先证明后端查单 / 签名回调，再允许订阅和额度生效",
        "data-saas-action=\"billing-provider-rehearsal\"",
        "data-billing-provider-action=\"payment_failed\"",
        "backend_order_query_or_signed_webhook_before_entitlement",
        "browser_cannot_grant_quota",
        "no_real_checkout_no_external_api_no_charge",
        "mainland_payment_cutover_v2",
        "wechat_pay_native_cutover",
        "no_charge_launch_rehearsal",
        "payment_provider_secret_boundary=backend_env_or_vault_only",
        "signed_wechat_callback_or_authenticated_query_before_entitlement",
        "rollback_secret_scan_readiness_browser_smoke_required",
        "public_paid_launch_allowed=false",
        "creates_checkout_session=false",
        "calls_stripe_api=false",
        "triggers_real_charge=false",
        "paid_launch_cutover_blockers_control_room_v1",
        "wechat_pay_native_cutover",
        "no_charge_launch_rehearsal",
        "signed_wechat_callback_or_authenticated_query_before_entitlement",
        "owner_live_cutover_required_before_public_charge",
        "repeat_ebay_oauth_allowed=false",
        "frontend_gets_payment_secret=false",
        "openCurrentPublicHomepage",
    ]:
        require(app_js + index_html + app_html + styles, billing_model_marker, "settings billing model and homepage return copy")
    ordinary_billing_checks = [
        ("function renderSaasMerchantBillingPlainSummaryPanel", "function renderSaasBillingTransitionPathPanel"),
        ("function renderSaasMerchantBillingContinuityPanel", "function renderSaasMerchantBillingIncidentRunbookPanel"),
        ("function renderSaasMerchantSecurityBoundaryPanel", "function renderSaasBillingProviderPanel"),
    ]
    for start_marker, end_marker in ordinary_billing_checks:
        start = app_js.index(start_marker)
        ordinary_billing_body = app_js[start:app_js.index(end_marker, start)]
        for forbidden_marker in [
            "审计证据",
            "eBay OAuth",
            "模型 key",
            "等待演练模式",
            "测试付款",
            "provider cutover",
            "eBay token",
            "client secret",
            "内部部署项",
            "BYOK",
        ]:
            if forbidden_marker in ordinary_billing_body:
                raise AssertionError(f"Ordinary merchant billing copy should not expose internal wording: {forbidden_marker}")
    transition_start = app_js.index("function renderSaasBillingTransitionPathPanel")
    transition_body = app_js[transition_start:app_js.index("function renderSaasBillingProviderRehearsalPanel", transition_start)]
    for forbidden_marker in [
        "quota 只停",
        "不重复授权 / 不重填模型 key",
        "后台接入和审核材料",
    ]:
        if forbidden_marker in transition_body:
            raise AssertionError(f"Billing activation path should use customer-facing wording: {forbidden_marker}")
    draft_start = app_js.index("function renderSaasListingDraftEditor")
    draft_end = app_js.index("function renderSaasListingGapAndRiskPanel", draft_start)
    draft_body = app_js[draft_start:draft_end]
    primary_index = draft_body.index("saas-listing-v2-draft-primary")
    title_index = draft_body.index('"eBay 标题"')
    points_index = draft_body.index('"五点卖点"')
    description_index = draft_body.index('"商品描述"')
    side_index = draft_body.index("saas-listing-v2-draft-side")
    price_index = draft_body.index('"价格 / 成本线索"')
    category_index = draft_body.index('"类目建议"')
    item_specifics_index = draft_body.index('"Item specifics"')
    images_index = draft_body.index('"图片 / 素材需求"')
    logistics_index = draft_body.index('"物流 / 重量 / 尺寸"')
    if not (
        primary_index
        < title_index
        < points_index
        < description_index
        < side_index
        < price_index
        < category_index
        < item_specifics_index
        < images_index
        < logistics_index
    ):
        raise AssertionError("Listing draft editor must prioritize buyer-facing copy before compact platform parameters")
    intake_start = app_js.index("function renderSaasPublishConfirmationIntakePanel")
    intake_end = app_js.index("function saasListingComposerDraftFromText", intake_start)
    intake_body = app_js[intake_start:intake_end]
    full_form_index = intake_body.index("saas-publish-raw-form-details")
    form_start = intake_body.index('<form id="saasPublishIntakeForm"')
    base_group_index = intake_body.index("基础信息", form_start)
    platform_group_index = intake_body.index("平台参数", form_start)
    finance_group_index = intake_body.index("价格利润", form_start)
    fulfillment_group_index = intake_body.index("物流履约", form_start)
    asset_group_index = intake_body.index("素材描述", form_start)
    pretest_index = intake_body.index("renderSaasPublishPretestResultSlot")
    if not (
        full_form_index
        < base_group_index
        < finance_group_index
        < asset_group_index
        < platform_group_index
        < fulfillment_group_index
        < pretest_index
    ):
        raise AssertionError("Listing publish flow must show grouped publish fields in business order before pretest results")
    for internal_marker in [
        "saas-listing-advanced-details",
        "saas-listing-nested-details",
        "发布前运营检查",
        "账号与数据证据",
        "历史报告与同步商品",
        "renderSaasSevenStepLaunchGuidePanel(ctx)",
        "renderSaasPostPublishCockpitPanel({ showWhenEmpty: true })",
        "renderSaasListingSyncedProductsPanel(ctx)",
    ]:
        if internal_marker in active_listing_body:
            raise AssertionError(f"Listing daily surface should not render internal evidence drawer: {internal_marker}")

    bulk_start = app_js.index("function renderSaasBulkCandidatePreview")
    bulk_end = app_js.index("function renderBulkCandidatePreview", bulk_start)
    bulk_body = app_js[bulk_start:bulk_end]
    for internal_marker in [
        "renderSaasCeoModuleHandoffPanel(\"bulk\"",
        "真实账号批量质检",
        "官方数据包",
        "字段完整度",
        "批量前置检查",
        "质检槽位",
        "等待数据包",
        "账号、数据包、来源缺口和上线状态放在设置里",
        "后台检查清单",
        "后台状态",
        "Listing Package 和素材工坊",
    ]:
        if internal_marker in bulk_body:
            raise AssertionError(f"Bulk daily surface should not show internal evidence/debug copy: {internal_marker}")
    bulk_html_start = app_html.index('<section class="view" id="view-bulk"')
    bulk_html_end = app_html.index('<section class="view" id="view-activity"', bulk_html_start)
    bulk_html = app_html[bulk_html_start:bulk_html_end]
    for internal_marker in [
        "批量铺货 · 批量前质检",
        "官方资源",
        "类 eBay 只读数据",
        "等待前置质检",
        "官方 eBay packet",
        "发布前质检",
        "真实账号状态显示官方数据包",
        "账号、数据包、来源缺口和上线状态放在设置里",
    ]:
        if internal_marker in bulk_html:
            raise AssertionError(f"Bulk HTML shell should not show internal evidence/debug copy: {internal_marker}")
    bulk_stage_start = app_js.index("const bulkStageCopy")
    bulk_stage_end = app_js.index("function updateBulkPreview", bulk_stage_start)
    bulk_stage_body = app_js[bulk_stage_start:bulk_stage_end]
    for internal_marker in [
        "官方 eBay packet",
        "字段完整度",
        "通过质检",
        "发布前正在做风险校验",
    ]:
        if internal_marker in bulk_stage_body:
            raise AssertionError(f"Bulk stage copy should not show internal evidence/debug copy: {internal_marker}")
    for expected in [
        "function renderSaasBulkSourceRealityPanel",
        "批量铺货货源来源",
        "还没有导入真实货源时，只生成候选方向，不当作可采购货源。",
        "导入后才写入采购价、库存、发货地和包装尺寸。",
        "采购付款、下单、地址写入和真实发货不会自动执行。",
        "real_source_handoff_v1",
    ]:
        require(app_js, expected, f"Bulk source reality copy: {expected}")

    media_html_start = app_html.index('<section class="view" id="view-media"')
    media_html_end = app_html.index('<section class="view" id="view-bulk"', media_html_start)
    media_html = app_html[media_html_start:media_html_end]
    media_dynamic_start = app_js.index("function syncSaasMediaProjectDraft")
    media_dynamic_end = app_js.index("function renderMediaProjectTabs", media_dynamic_start)
    media_dynamic_body = app_js[media_dynamic_start:media_dynamic_end]
    for internal_marker in [
        "官方数据包",
        "Listing Package",
        "数据包可用",
        "等待数据包",
        "确认记录",
        "费用和用量",
        "素材状态拆分",
        "provider",
        "素材 brief",
        "后台证据",
        "后台状态",
        "素材清单已回写",
        "流程导入不需要本机路径",
    ]:
        if internal_marker in media_html:
            raise AssertionError(f"Media daily HTML should not show internal evidence/provider copy: {internal_marker}")
        if internal_marker in media_dynamic_body:
            raise AssertionError(f"Media daily dynamic copy should not show internal evidence/provider copy: {internal_marker}")
    for expected in [
        "function activeMediaDraftProfileForDisplay",
        "没有真实商品和素材清单时，不展示旧样例图",
        "不能用旧测试图片冒充真实生成",
        "function renderSaasMediaGenerationReadinessPanel",
        "素材工坊真实生成状态",
        "真实生成状态",
        "外部素材服务可用",
        "素材清单和人工审核",
        "每次生成可能计入外部素材服务用量",
        "media_live_service_readiness_v1",
    ]:
        require(app_js, expected, f"Media generation readiness copy: {expected}")

    service_html_start = app_html.index('<section class="view" id="view-service"')
    service_html_end = app_html.index('<section class="view" id="view-connect"', service_html_start)
    service_html = app_html[service_html_start:service_html_end]
    service_dynamic_start = app_js.index("function renderSaasServiceCenter")
    service_dynamic_end = app_js.index("function renderConversations", service_dynamic_start)
    service_dynamic_body = app_js[service_dynamic_start:service_dynamic_end]
    for expected in [
        "service_order_plain_workbench_v2",
        "今日客服与订单",
        "客服、物流和售后放在一页",
        "没有真实订单时不显示虚构买家",
        "当前没有待处理订单",
        "当前没有待处理内容",
    ]:
        require(service_html + service_dynamic_body, expected, f"Service simple daily copy: {expected}")
    for internal_marker in [
        "官方数据包",
        "Listing Package",
        "等待官方订单",
        "等待官方同步",
        "官方数据可用",
        "客服事实表",
        "Provider Hub",
        "provider",
        "后台排查",
        "连接和排查在设置",
        "去设置同步 eBay",
    ]:
        if internal_marker in service_html:
            raise AssertionError(f"Service daily HTML should not show internal evidence/provider copy: {internal_marker}")
        if internal_marker in service_dynamic_body:
            raise AssertionError(f"Service daily dynamic copy should not show internal evidence/provider copy: {internal_marker}")

    require(styles, "body.saas-public-mvp #appShell .main > .topbar", "topbar suppression")
    require(styles, "body.saas-public-mvp #appShell .global-flow-bar", "global flow suppression")
    require(styles, "body.saas-public-mvp .saas-settings-clean-shell", "clean settings styling")
    require(styles, "body.saas-public-mvp .saas-settings-home-hub", "settings home hub styling")
    require(styles, "body.saas-public-mvp .saas-settings-home-status", "settings compact status styling")
    require(styles, "body.saas-public-mvp .saas-listing-simple-products", "simple listing products styling")
    require(styles, "body.saas-public-mvp .saas-listing-composer", "Listing Composer styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-status-bar", "Listing status bar styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-status-items", "Listing status items styling")
    require(styles, "body.saas-public-mvp .saas-listing-workflow-proof", "Listing workflow loop result styling")
    require(styles, "body.saas-public-mvp .saas-listing-workflow-proof-grid", "Listing workflow loop grid styling")
    require(styles, ".saas-media-generation-readiness", "media generation readiness styling")
    require(styles, ".saas-media-generation-readiness-grid", "media generation readiness grid styling")
    require(styles, ".saas-media-generated-empty", "media generated empty state styling")
    require(styles, ".asset-preview-empty", "media asset pending preview styling")
    require(styles, ".bulk-source-reality-panel", "bulk source reality styling")
    require(styles, ".bulk-source-reality-grid", "bulk source reality grid styling")
    require(styles, "grid-template-columns: repeat(5, minmax(0, 1fr));", "Listing five-step status grid")
    require(styles, "body.saas-public-mvp .saas-listing-v2-source-grid", "Listing v2 source styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-draft-editor", "Listing v2 editor styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-draft-layout", "Listing draft split layout styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-draft-primary", "Listing draft primary column styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-draft-side", "Listing draft side column styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-field.is-compact", "Listing compact draft fields styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-risk-panel", "Listing v2 risk styling")
    require(styles, "body.saas-public-mvp .saas-listing-publish-flow", "Listing direct publish flow styling")
    require(styles, "body.saas-public-mvp .saas-listing-input-panel", "Listing simple input panel styling")
    require(styles, "body.saas-public-mvp .saas-first-run-strip", "shared first-run strip styling")
    require(styles, ".bulk-first-run-strip", "bulk first-run strip styling")
    require(styles, "body.saas-public-mvp .saas-listing-ai-handoff", "AI CEO to Listing handoff styling")
    require(styles, "body.saas-public-mvp .saas-listing-input-chips button", "Listing input chip styling")
    require(styles, "body.saas-public-mvp .saas-listing-composer-input textarea", "Listing Composer main textarea styling")
    require(styles, "body.saas-public-mvp .workflow-feedback-shell", "mobile feedback entry controlled separately")
    require(styles, "body.saas-public-mvp .workflow-feedback-drawer", "mobile feedback drawer avoids bottom navigation")
    require(styles, "display: none;", "mobile feedback toggle hidden to avoid blocking navigation")
    require(styles, "bottom: calc(70px + env(safe-area-inset-bottom, 0px));", "feedback drawer remains bottom-safe if opened")
    require(styles, ".saas-publish-guide-panel", "publish guide styling")
    require(styles, ".saas-publish-guide-grid", "publish guide grid styling")
    require(styles, ".saas-publish-raw-form-details", "publish raw form expanded panel styling")
    require(styles, ".saas-publish-raw-form-head", "publish raw form expanded head styling")
    require(styles, ".saas-publish-readiness-strip", "publish completion strip styling")
    require(styles, ".saas-publish-form-group", "publish form group styling")
    require(styles, ".saas-publish-form-fields", "publish form fields grid styling")
    require(styles, ".saas-publish-form-group-head", "publish form group heading styling")
    require(styles, ".saas-publish-form-step", "publish form step badge styling")
    require(styles, ".saas-listing-pretest-result", "publish pretest result slot styling")
    require(styles, ".saas-listing-pretest-empty", "publish pretest empty state styling")
    require(styles, ".bulk-saas-roadmap", "bulk simple roadmap styling")
    require(styles, ".bulk-saas-lane-list", "bulk lane list styling")
    require(styles, ".saas-media-asset-jobs", "media asset job panel styling")
    require(styles, ".saas-media-asset-summary", "media asset job summary styling")
    require(styles, ".saas-media-asset-list", "media asset job list styling")
    require(styles, "body.saas-public-mvp[data-view=\"product\"] .saas-real-listing-header", "old Listing header hidden on daily surface")
    require(styles, "body.saas-public-mvp .saas-ceo-module-handoff", "handoff suppression")
    require(styles, "2026-06-24 AI CEO minimal routing v2", "AI CEO minimal routing final override")
    for incident_style_marker in [
        ".saas-merchant-billing-incident-runbook",
        ".saas-merchant-billing-incident-grid",
        ".saas-merchant-billing-incident-note",
        ".saas-merchant-billing-trust-packet",
        ".saas-merchant-billing-trust-grid",
        ".saas-merchant-billing-trust-note",
        ".saas-merchant-subscription-activation",
    ]:
        require(styles, incident_style_marker, "billing incident runbook styling")

    forbidden_merchant_copy = [
        "上架主线",
        "Listing 四步主线",
        "商家只需要沿着这四步走",
        "先看体检",
        "再补字段",
        "最后确认",
        "默认不打扰上架主线",
        "provider 返回错误，可能是模型 key 被拒绝",
        "后端已拿到当前店铺 secret_ref",
        "live adapter",
        "模型与素材 provider",
        "Provider Hub",
        "素材 Provider",
        "等待保存 BYOK",
        "不触碰 token",
        "估算 token",
        "tokens ·",
        "value proof done",
        "value proof pending",
        "raw provider",
        "FAL</strong>",
    ]
    listing_surface_forbidden = forbidden_merchant_copy[:7]
    engineering_forbidden = forbidden_merchant_copy[7:]
    for needle in listing_surface_forbidden:
        if needle in active_listing_body:
            raise AssertionError(f"Listing daily surface should not show tutorial/internal copy: {needle}")
    for needle in engineering_forbidden:
        if needle in app_js:
            raise AssertionError(f"merchant-facing engineering copy should not remain: {needle}")
    if '<details class="saas-publish-raw-form-details">' in app_js:
        raise AssertionError("Listing full publish form must stay expanded, not folded in a details drawer")

    print("SAAS_CLEAN_SETTINGS_AND_LISTING_UI_OK")


if __name__ == "__main__":
    main()
