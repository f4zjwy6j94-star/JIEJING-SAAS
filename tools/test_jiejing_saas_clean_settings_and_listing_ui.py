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
    require(app_js, "data-saas-settings-tab", "settings tab navigation")
    require(app_js, "renderSaasSettingsCleanLayout(ctx", "settings render path")

    require(app_js, "function renderSaasBulkCandidatePreview", "SaaS bulk simplified candidate preview")
    require(app_js, "先小批量筛，不一键乱铺", "bulk low-learning-cost headline")
    require(app_js, "小批量实验台", "bulk experiment lab framing")
    require(app_js, "生成三类候选", "bulk simple grouping action")
    require(app_js, "建议先测", "bulk test lane")
    require(app_js, "需要补资料", "bulk missing-info lane")
    require(app_js, "暂时不做", "bulk blocked lane")
    require(app_js, "用最小批次看清机会和风险", "bulk simple one-job copy")
    require(app_js, "bulk-saas-roadmap", "bulk simple roadmap markup")
    require(app_js, "bulk-saas-lane-list", "bulk grouped lane markup")
    require(app_js, "bulk-first-run-strip", "bulk first-run assurance strip")
    require(app_js, "不会乱铺", "bulk no-random-publish copy")
    require(app_js, "不直接执行", "bulk no-direct-execution copy")
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
    require(app_js, "function saasMediaTaskLabel", "media merchant-facing task labels")
    require(app_js, "等待商品草稿", "media waiting state copy")
    require(app_js, "saas-media-first-run-strip", "media first-run assurance strip")
    require(app_js, "没有商品或来源图时，不展示旧样例", "media no fake sample copy")
    require(app_js, "素材工坊只接商品草稿、图片需求或商家上传图", "media source boundary copy")
    require(app_js, "商家只需要看三件事：这张图用在哪里、能不能用、还缺什么", "media result readability copy")
    require(app_js, "先看草稿，再决定是否回写 Listing", "media quality board simple copy")
    require(app_js, "aria-label=\"素材进度\"", "media progress aria label")

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
    require(app_js, 'route !== "general_chat"', "AI CEO only records business commands as source records")
    require(app_js, "AI CEO 已接住", "AI CEO compact task card heading")
    require(app_js, "先去决策中心确认", "AI CEO compact risk handoff title")
    require(app_js, "saas-ceo-routing-main", "AI CEO compact task card layout")
    require(app_js, "function saasCeoRoutingWhyRows", "AI CEO routing why rows helper")
    require(app_js, "AI CEO 路由确认", "AI CEO route card plain explanation aria label")
    require(app_js, "我理解", "AI CEO route card understood row")
    require(app_js, "推荐去", "AI CEO route card recommended module row")
    require(app_js, "安全边界", "AI CEO route card safety row")
    require(styles, ".saas-ceo-routing-why", "AI CEO route card three-row styling")
    require(app_js, "继续小批量实验台", "AI CEO compact task card bulk next button")
    require(app_js, "一句话交给 AI CEO", "AI CEO low-learning-cost empty title")
    require(app_js, "比如：帮我调研这个商品，整理 Listing 草稿", "AI CEO low-learning-cost composer example")
    require(app_js, "也可以直接问普通问题。", "AI CEO low-learning-cost plain chat hint")
    require(app_js, "current.intent !== \"listing\"", "AI CEO prevents non-Listing intents from being hijacked by Listing")
    if "AI CEO 已收到，Listing 已接住这个目标。" in app_js:
        raise AssertionError("AI CEO Listing handoff should use the route card, not a mobile-covering toast")
    require(app_js, "请按市场结论 → Listing 草稿 → 素材/利润 → 发布确认的顺序整理；不要触发真实 eBay 写入。", "safe Listing handoff prompt")
    require(app_js, "来自 AI CEO", "Listing handoff merchant label")
    require(app_js, 'state.saasListingSourceMode = "ai_ceo_handoff"', "AI CEO handoff source mode")
    require(app_js, "function saasListingComposerDraftFromText", "Listing Composer local draft builder")
    require(app_js, 'String(priceMatch[1] || priceMatch[0] || "").trim()', "Listing price parser fallback without capture group")
    require(app_js, "function saasListingDraftFromReport", "AI CEO report import into Listing")
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
    require(app_js, "data-saas-listing-input-chip", "Listing input quick chips")
    require(app_js, "function renderSaasFirstRunAssuranceStrip", "shared first-run assurance strip")
    require(app_js, "不用完整", "Listing simple first-run copy")
    require(app_js, "缺口会停住", "Listing gap stops copy")
    require(app_js, "不直接发布", "Listing no direct publish copy")
    require(app_js, 'event.target.closest("[data-saas-listing-input-chip]")', "Listing input chip event wiring")
    require(app_js, 'draft ? renderSaasListingGapAndRiskPanel(draft, opportunity) : ""', "Listing risk cards hidden until a draft exists")
    require(app_js, "showOpportunity ? renderSaasListingOpportunityPanel(opportunity) : \"\"", "Listing opportunity card hidden until a real source exists")
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
    require(app_js, "function localQaForcesSaasPublicMvpMode", "local-only public SaaS QA switch")
    require(app_js, 'qaMode === "public-saas" || qaMode === "listing-v2-workbench"', "local QA listing route")
    require(app_js, "saas-listing-publish-flow", "Listing direct publish check flow")
    require(app_js, "const showPublishFlow = Boolean(state.saasListingComposerDraft || hasLiveListing)", "Listing publish form hidden until draft or listing package")
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
    require(app_js, "已有市场结论或上架草稿，可以作为上架依据", "Listing report import uses merchant-facing copy")
    require(app_js, "店铺连接和授权配置在设置里", "Listing settings boundary copy")
    require(app_js, '<span class="pill green">草稿</span>', "Listing draft pill uses merchant-facing label")
    require(app_js, "const productLabel = saasWorkflowProductLabel(latestTask) || saasModelValueProductLabel", "model value product label is defined before request")
    require(app_js, "function saasModelValueFailureMessage", "precise model value failure toast")
    require(app_js, "模型服务返回错误，可能是模型名不被接受", "merchant-facing model failure reason")
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
    require(app_js, "为什么停住", "rendered decision card keeps evidence behind plain-language disclosure")
    require(app_js, "普通商家只看 5 个入口", "settings map merchant entrance boundary")
    require(app_js, "这里处理账号、店铺数据、AI、权限、订阅与安全", "settings home low-learning-cost copy")
    require(app_js, "不展示技术排查和部署细节", "settings home hides technical diagnostics")
    require(app_js, "商品、订单、政策、费用等来源可追溯", "settings status merchant-facing data copy")
    require(app_js, "店铺数据、来源记录和同步缺口", "settings data panel merchant-facing title")
    require(app_js, "什么时候需要打开设置", "settings usage-rule section")
    require(app_js, "主理人高级区", "settings workflow compact boundary")
    require(app_js, "AI 与素材", "merchant-friendly model settings title")
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
    show_publish_flow_index = listing_body.index("const showPublishFlow = Boolean")
    publish_flow_index = listing_body.index("saas-listing-publish-flow")
    boundary_index = listing_body.index("saas-listing-composer-boundary")
    if not (show_publish_flow_index < minimal_index < publish_flow_index < publish_intake_index < boundary_index):
        raise AssertionError("Listing daily surface must flow from composer to publish data completion to final confirmation boundary")
    composer_start = app_js.index("function renderSaasListingComposerWorkspace")
    composer_end = app_js.index("function renderSaasListingMinimalWorkspace", composer_start)
    composer_body = app_js[composer_start:composer_end]
    input_panel_index = composer_body.index("saas-listing-input-panel")
    source_cards_index = composer_body.index("renderSaasListingSourceCards")
    if not input_panel_index < source_cards_index:
        raise AssertionError("Listing source alternatives must stay below the primary product input")
    status_index = composer_body.index("renderSaasListingStatusBar")
    workflow_index = composer_body.index("renderSaasListingWorkflowProofPanel")
    opportunity_index = composer_body.index("renderSaasListingOpportunityPanel")
    draft_editor_index = composer_body.index("renderSaasListingDraftEditor")
    gap_index = composer_body.index("renderSaasListingGapAndRiskPanel")
    if not (source_cards_index < status_index < workflow_index < opportunity_index < draft_editor_index < gap_index):
        raise AssertionError("Listing C+ surface must flow from source selection to market conclusion to draft to asset/profit gaps")
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
    for required_marker in [
        "renderSaasSettingsAccountFocusPanel(ctx)",
        "renderSaasSettingsModelFocusPanel(ctx)",
        "renderSaasSettingsDataFocusPanel(ctx)",
        "renderSaasSettingsGovernanceFocusPanel()",
        "renderSaasSettingsBillingFocusPanel(ctx)",
        "renderSaasMerchantPricingModelPanel(ctx)",
        "renderSaasMerchantBillingCurrentStatusPanel(ctx)",
        "主理人高级区",
        "正式收费和公网安全",
        "运行可靠性",
        "主理人上线排查",
        "renderSaasMerchantSecurityBoundaryPanel()",
    ]:
        require(settings_def_body, required_marker, "settings ordinary tabs stay focused while owner area keeps advanced controls")
    ordinary_settings_body = settings_def_body[: settings_def_body.index("if (saasOwnerLaunchCanView())")]
    for redundant_marker in [
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
    for billing_model_marker in [
        "基础订阅保留工作台",
        "AI 用量和素材生成单独核算",
        "subscription_ai_media_platform_v1",
        "saas-merchant-pricing-split",
        "用量计费路线",
        "基础订阅不包含无限模型",
        "eBay 费用、广告费、物流和退款不是捷境代扣",
        "高成本联网任务",
        "正式收费前，商家必须能看清套餐、金额、续费/取消入口和用量记录",
        "等待演练模式",
        "当前计费状态",
        "先看能不能继续用，再看哪些费用另算",
        "内测演练，不真实扣费",
        "merchant_visible_billing_status_v1",
        "merchant_subscription_shutdown_closure_v2",
        "billing_never_deletes_audit_records",
        "billing_blocks_metered_work_only",
        "no_repeat_oauth_for_billing_recovery",
        "no_model_key_reentry_for_billing_recovery",
        "frontend_gets_payment_secret=false",
        "openCurrentPublicHomepage",
    ]:
        require(app_js + index_html + app_html + styles, billing_model_marker, "settings billing model and homepage return copy")
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

    service_html_start = app_html.index('<section class="view" id="view-service"')
    service_html_end = app_html.index('<section class="view" id="view-connect"', service_html_start)
    service_html = app_html[service_html_start:service_html_end]
    service_dynamic_start = app_js.index("function renderSaasServiceCenter")
    service_dynamic_end = app_js.index("function renderConversations", service_dynamic_start)
    service_dynamic_body = app_js[service_dynamic_start:service_dynamic_end]
    for expected in [
        "买家消息先整理，关键承诺你确认",
        "买家问什么、订单到哪、回复怎么说",
        "消息、订单、回复",
        "没有真实订单时保持空白",
        "暂无真实订单或消息",
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
    require(styles, "body.saas-public-mvp[data-view=\"product\"] .saas-real-listing-header", "old Listing header hidden on daily surface")
    require(styles, "body.saas-public-mvp .saas-ceo-module-handoff", "handoff suppression")
    require(styles, "2026-06-24 AI CEO minimal routing v2", "AI CEO minimal routing final override")

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
