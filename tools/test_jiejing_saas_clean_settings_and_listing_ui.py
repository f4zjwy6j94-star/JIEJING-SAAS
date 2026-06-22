from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
STYLES = ROOT / "styles.css"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    require(app_js, "saasSettingsTab", "settings tab state")
    require(app_js, "function renderSaasSettingsCleanLayout", "clean settings layout")
    require(app_js, "data-saas-settings-tab", "settings tab navigation")
    require(app_js, "renderSaasSettingsCleanLayout(ctx", "settings render path")

    require(app_js, "function saasListingSyncedProductRows", "eBay synced product extraction")
    require(app_js, "function renderSaasListingSyncedProductsPanel", "eBay synced product panel")
    require(app_js, "saas-listing-simple-head", "simple listing header")
    require(app_js, "function renderSaasListingComposerWorkspace", "Listing Composer workspace")
    require(app_js, "function saasListingComposerDraftFromText", "Listing Composer local draft builder")
    require(app_js, 'String(priceMatch[1] || priceMatch[0] || "").trim()', "Listing price parser fallback without capture group")
    require(app_js, "function saasListingDraftFromReport", "AI CEO report import into Listing")
    require(app_js, "function saasListingDraftFromSyncedProduct", "synced eBay product import into Listing")
    require(app_js, "function renderSaasListingSourceCards", "Listing three source entry cards")
    require(app_js, "function renderSaasListingStatusBar", "Listing compact status bar")
    require(app_js, "function renderSaasListingDraftEditor", "Listing editable draft editor")
    require(app_js, "function handleSaasListingComposeDraft", "Listing Composer action handler")
    require(app_js, "function handleSaasListingSourceAiReport", "Listing AI report source action")
    require(app_js, 'if (action === "listing-compose-draft")', "Listing Composer event wiring")
    require(app_js, 'if (action === "listing-source-ai-report")', "Listing AI report source event wiring")
    require(app_js, "saas-listing-input-panel", "Listing simple input panel")
    require(app_js, "商品资料入口", "Listing input entry label")
    require(app_js, "把你手上的资料直接放进来", "Listing low-learning-cost input headline")
    require(app_js, "data-saas-listing-input-chip", "Listing input quick chips")
    require(app_js, 'event.target.closest("[data-saas-listing-input-chip]")', "Listing input chip event wiring")
    require(app_js, 'draft ? renderSaasListingGapAndRiskPanel(draft, opportunity) : ""', "Listing risk cards hidden until a draft exists")
    require(app_js, "draft || reportsReady ? renderSaasListingOpportunityPanel(opportunity) : \"\"", "Listing opportunity card hidden until a real source exists")
    require(app_js, "saas-listing-v2-workbench", "Listing v2 first screen")
    require(app_js, "saas-listing-v2-status-bar", "Listing v2 compact status bar")
    require(app_js, "Listing 刊登状态", "Listing status aria label")
    require(app_js, 'title: "发布资料"', "Listing status includes publish data step")
    require(app_js, 'value: hasDraft ? "可补字段" : "等待草稿"', "Listing publish data status value")
    require(app_js, "saas-listing-v2-source-grid", "Listing v2 source selector")
    require(app_js, "saas-listing-v2-draft-editor", "Listing v2 draft editor")
    require(app_js, "data-saas-listing-draft-field", "Listing draft field persistence")
    require(app_js, "function localQaForcesSaasPublicMvpMode", "local-only public SaaS QA switch")
    require(app_js, 'qaMode === "public-saas" || qaMode === "listing-v2-workbench"', "local QA listing route")
    require(app_js, "saas-listing-publish-flow", "Listing direct publish check flow")
    require(app_js, "更多账号和后台状态已经归到设置", "Listing internal evidence moved to settings copy")
    require(app_js, "function renderSaasPublishConfirmationIntakePanel", "new product publish confirmation intake")
    require(app_js, "function saasPublishIntakePrefillValues", "Listing draft to publish form prefill")
    require(app_js, "function renderSaasPublishInputField", "publish form input helper")
    require(app_js, "function renderSaasPublishTextareaField", "publish form textarea helper")
    require(app_js, "function renderSaasPublishFormGroup", "publish form business grouping")
    require(app_js, "function renderSaasPublishPreflightGuide", "merchant publish preflight guide")
    require(app_js, "function renderSaasPublishPretestResultSlot", "Listing pretest result slot")
    require(app_js, "saas-listing-pretest-result", "Listing pretest result slot markup")
    require(app_js, "saas-publish-guide-panel", "publish guide panel")
    require(app_js, '<section class="saas-publish-raw-form-details" aria-label="完整字段表">', "expanded full publish form")
    require(app_js, "saas-publish-raw-form-head", "expanded full publish form head")
    require(app_js, "草稿会先自动带入", "draft auto-prefill copy")
    require(app_js, "基础信息", "publish form base group")
    require(app_js, "平台参数", "publish form platform group")
    require(app_js, "价格利润", "publish form finance group")
    require(app_js, "物流履约", "publish form fulfillment group")
    require(app_js, "素材描述", "publish form asset group")
    require(app_js, "fields.title || draft?.title", "draft title prefill source")
    require(app_js, "parseSaasKeyValueLines(itemSpecifics)", "item specifics prefill parser")
    require(app_js, "const evidenceText = [logisticsText, clean].filter(Boolean).join", "full merchant input logistics prefill source")
    require(app_js, 'clean.match(/https?:\\/\\/[^\\s,，；;]+/gi)', "image URL prefill from merchant input")
    require(app_js, "发布资料补全", "Listing publish data completion step")
    require(app_js, "先补完整字段，再做发布体检", "Listing ordered publish flow copy")
    require(app_js, "Market Report", "market report remains on Listing page")
    require(app_js, "Listing Package", "listing package remains on Listing page")
    require(app_js, "const productLabel = saasWorkflowProductLabel(latestTask) || saasModelValueProductLabel", "model value product label is defined before request")
    require(app_js, "function saasModelValueFailureMessage", "precise model value failure toast")
    require(app_js, "模型服务返回错误，可能是模型名不被接受", "merchant-facing model failure reason")
    require(app_js, "设置地图", "settings readable map")
    require(app_js, "AI 连接、素材生成和成本", "merchant-friendly model settings title")
    require(app_js, "function saasIsEnglishHeavyMerchantText", "legacy English report display guard")
    require(app_js, "旧记录的英文摘要已隐藏", "legacy English report summary hidden")
    require(app_js, "function saasWorkbenchFormatReportSectionValue", "report detail Chinese display guard")

    listing_start = app_js.index("function renderSaasProductListingCenter")
    listing_end = app_js.index("function renderProductListingCenter", listing_start)
    listing_body = app_js[listing_start:listing_end]
    disabled_internal_index = listing_body.find("${false ? `")
    active_listing_body = listing_body[:disabled_internal_index] if disabled_internal_index >= 0 else listing_body
    publish_intake_index = listing_body.index("renderSaasPublishConfirmationIntakePanel(ctx")
    minimal_index = listing_body.index("renderSaasListingComposerWorkspace")
    publish_flow_index = listing_body.index("saas-listing-publish-flow")
    boundary_index = listing_body.index("saas-listing-composer-boundary")
    if not (minimal_index < publish_flow_index < publish_intake_index < boundary_index):
        raise AssertionError("Listing daily surface must flow from composer to publish data completion to final confirmation boundary")
    composer_start = app_js.index("function renderSaasListingComposerWorkspace")
    composer_end = app_js.index("function renderSaasListingMinimalWorkspace", composer_start)
    composer_body = app_js[composer_start:composer_end]
    input_panel_index = composer_body.index("saas-listing-input-panel")
    source_cards_index = composer_body.index("renderSaasListingSourceCards")
    if not input_panel_index < source_cards_index:
        raise AssertionError("Listing source alternatives must stay below the primary product input")
    intake_start = app_js.index("function renderSaasPublishConfirmationIntakePanel")
    intake_end = app_js.index("function saasListingComposerDraftFromText", intake_start)
    intake_body = app_js[intake_start:intake_end]
    full_form_index = intake_body.index("saas-publish-raw-form-details")
    base_group_index = intake_body.index("基础信息")
    platform_group_index = intake_body.index("平台参数")
    finance_group_index = intake_body.index("价格利润")
    fulfillment_group_index = intake_body.index("物流履约")
    asset_group_index = intake_body.index("素材描述")
    pretest_index = intake_body.index("renderSaasPublishPretestResultSlot")
    if not (
        full_form_index
        < base_group_index
        < platform_group_index
        < finance_group_index
        < fulfillment_group_index
        < asset_group_index
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

    require(styles, "body.saas-public-mvp #appShell .main > .topbar", "topbar suppression")
    require(styles, "body.saas-public-mvp #appShell .global-flow-bar", "global flow suppression")
    require(styles, "body.saas-public-mvp .saas-settings-clean-shell", "clean settings styling")
    require(styles, "body.saas-public-mvp .saas-listing-simple-products", "simple listing products styling")
    require(styles, "body.saas-public-mvp .saas-listing-composer", "Listing Composer styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-status-bar", "Listing status bar styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-status-items", "Listing status items styling")
    require(styles, "grid-template-columns: repeat(5, minmax(0, 1fr));", "Listing five-step status grid")
    require(styles, "body.saas-public-mvp .saas-listing-v2-source-grid", "Listing v2 source styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-draft-editor", "Listing v2 editor styling")
    require(styles, "body.saas-public-mvp .saas-listing-v2-risk-panel", "Listing v2 risk styling")
    require(styles, "body.saas-public-mvp .saas-listing-publish-flow", "Listing direct publish flow styling")
    require(styles, "body.saas-public-mvp .saas-listing-input-panel", "Listing simple input panel styling")
    require(styles, "body.saas-public-mvp .saas-listing-input-chips button", "Listing input chip styling")
    require(styles, "body.saas-public-mvp .saas-listing-composer-input textarea", "Listing Composer main textarea styling")
    require(styles, ".saas-publish-guide-panel", "publish guide styling")
    require(styles, ".saas-publish-guide-grid", "publish guide grid styling")
    require(styles, ".saas-publish-raw-form-details", "publish raw form expanded panel styling")
    require(styles, ".saas-publish-raw-form-head", "publish raw form expanded head styling")
    require(styles, ".saas-publish-form-group", "publish form group styling")
    require(styles, ".saas-publish-form-fields", "publish form fields grid styling")
    require(styles, ".saas-publish-form-group-head", "publish form group heading styling")
    require(styles, ".saas-listing-pretest-result", "publish pretest result slot styling")
    require(styles, ".saas-listing-pretest-empty", "publish pretest empty state styling")
    require(styles, "body.saas-public-mvp[data-view=\"product\"] .saas-real-listing-header", "old Listing header hidden on daily surface")
    require(styles, "body.saas-public-mvp .saas-ceo-module-handoff", "handoff suppression")

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
