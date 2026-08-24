#!/usr/bin/env python3
"""Static guard for the AI CEO continuous chat surface."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.js"
CSS = ROOT / "styles.css"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app = APP.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    required_app = [
        "const jiejingTrustedHtmlBlockedPattern = /<script\\b",
        "function trustedJiejingHtml",
        "function setJiejingTrustedHtml",
        "function insertJiejingTrustedHtml",
        "function replaceJiejingTrustedHtml",
        'trustedJiejingHtml(renderSaasCeoRoutingTaskCard(command), "ai_ceo.route_task_card")',
        'trustedJiejingHtml(renderSaasAiCeoLatestReplyMarkup(latest), "ai_ceo.latest_reply")',
        "replaceJiejingTrustedHtml(consoleNode, trustedJiejingHtml(renderSaasCeoCommandConsole",
        'trustedJiejingHtml(renderSaasAiCeoChatTurnMarkup({ assistant_text: productizeJiejingProductCopy(text) }), "ai_ceo.chat_turn.assistant_only")',
        '"ai_ceo.chat_turn.user_and_assistant"',
        '"ai_ceo.chat_turn.recovery_and_detail"',
        '"ai_ceo.chat_turn.pending_status"',
        "saasAiCeoLatestTurn",
        "saasAiCeoThread",
        "ceoThread: \"jiejing_saas_ceo_thread\"",
        "function saasProtectedSnapshotStorageKey",
        "function hydrateSaasCeoAccountScopedLocalState",
        "function clearStoredSaasStoreContext",
        "state.saasLastCeoCommand = null",
        "state.saasAiCeoThread = []",
        "state.saasAiCeoLatestTurn = null",
        "const previousAccountAliases = new Set(saasAccountStorageAliases())",
        "shouldPreserveActiveCeoThread",
        '"ai_ceo.thread.preserve_on_auth"',
        "function clearSaasSessionFromStorage(options = {})",
        "clearSaasSessionFromStorage({ preserveCeoThread: true })",
        "activeCeoThreadBeforeRefresh",
        "shouldPreserveActiveCeoState",
        "activeCeoThreadAtCoreApply",
        "activeCeoThreadAtExtendedApply",
        "uniqueSaasAiCeoThreadTurns([",
        "...activeCeoThreadAtCoreApply",
        "...activeCeoThreadAtExtendedApply",
        "localStorage.setItem(saasProtectedSnapshotStorageKey()",
        "for (const key of saasProtectedSnapshotStorageKeys())",
        "const raw = localStorage.getItem(key)",
        "localStorage.removeItem(saasProtectedSnapshotStorageKey())",
        "AI 额度或连接状态挡住了本次回复",
        "不要重复填写连接信息，除非页面明确提示连接已失效",
        "本次不会产生捷境收费、不会写入 eBay",
        "function saasAiCeoMerchantSafeFailureText",
        "function saasAiCeoProductizedAnswerText",
        "捷境后端接口",
        "const rawAnswer = saasAiCeoProductizedAnswerText(chat?.answer || \"\", chat?.status || \"\")",
        "const dependencyBlockedWithoutUsage =",
        "本次未调用模型、未消耗次数、未生成草稿。",
        "const safeText = saasAiCeoProductizedAnswerText(text || \"AI CEO 暂时没有返回可展示内容。\", status)",
        "function renderSaasAiCeoRecoveryHintMarkup",
        "merchant_safe_ai_recovery_v1",
        "AI 已收到，但模型额度需要先恢复",
        "AI 已收到，但需要先恢复店铺状态",
        "AI 已接通，但实时数据源需要先恢复",
        "普通咨询和 eBay 工作流可以继续",
        "去账号与店铺",
        'data-saas-action="refresh"',
        'if (key === "account") state.saasSettingsTab = "account";',
        "function renderSaasAiCeoPendingStatusMarkup",
        "function renderSaasAiCeoPendingPreviewMarkup",
        "quick_then_full_report_v1",
        "先给你一个临时方向",
        'ebay_workflow: "product"',
        'confirmation_required: "confirm"',
        "function scheduleSaasAiCeoPendingWatchdog",
        "function updateCeoAssistantPendingMessage",
        "function saasFetchWithTimeout",
        "AI CEO response timed out after",
        "60000,",
        "Promise.race([request, timeout])",
        "single_black_thinking_dot_v1",
        "saas-ai-ceo-thinking-dot",
        "function ensureCeoAssistantAnswerBody",
        "function saasAiCeoConversationHistoryForRequest",
        "conversation_history: saasAiCeoConversationHistoryForRequest()",
        "不消耗捷境试用额度",
        "正在使用账号自己的 AI",
        "当前对话优先使用账号自己的 AI",
        "jiejing_saas_ceo_market_turn",
        "function rememberLatestSaasAiCeoMarketResearchTurn",
        "function applySaasAiCeoMarketTurnToListing",
        "function renderSaasAiCeoMarketReportDeliveryMarkup",
        "ai_ceo_market_report_delivery_v1",
        "市场调研已保存",
        "function renderSaasAiCeoPerformanceSummaryMarkup",
        "merchant_visible_latency_v1",
        "已查 ${sourceCount} 条公开来源",
        "AI 整理约 ${modelLatency}",
        "敏感连接信息不会在页面展示",
        "model_response_delayed",
        "route: intent,",
        "route_label: primaryRoute.label",
        "真实发布、付款、退款、广告、授权和敏感客服承诺不会自动执行",
        'const primaryKey = isAccountBlock ? "account" : "model";',
        'const primaryLabel = isAccountBlock ? "去账号与店铺" : "去 AI 与素材";',
        "function renderSaasAiCeoLatestReplyMarkup",
        'target="_blank" rel="noopener noreferrer"',
        '/\\[([^\\]]+?)\\]\\((https:\\/\\/[^\\s)]+)\\)/g',
        'id="ceoChat"',
        "updateSaasAiCeoLatestReply({",
        "function renderSaasAiCeoChatTurnMarkup",
        "function renderSaasAiCeoThreadMarkup",
        "const latestPendingIndex = visibleTurns.reduce(",
        "suppressPendingAssistant: Boolean(turn.pending && index !== latestPendingIndex)",
        'node.classList.remove("is-pending", "is-superseded-pending")',
        "function upsertSaasAiCeoThreadTurn",
        "function shouldKeepSaasAiCeoThreadTurn",
        "function updateCeoAssistantMessage(messageId, text, status = \"\", model = null, sourceRecords = [], workflowDetails = {})",
        "updateCeoAssistantMessage(pendingMessageId, answer, chat?.status || \"\", chat?.model_client || null, sourceRecords, {",
        "一句话交给 AI CEO",
        "问问题直接答；说商品、链接、图片或订单，我会自动带到对应流程；真实发布、付款、退款和广告先问你。",
        "比如：帮我调研这个商品，整理 Listing 草稿",
        "也可以直接问普通问题。",
        "自动进入 Listing、批量、素材、客服或决策中心",
        "AI CEO 已接住",
        "先去决策中心确认",
        "继续 Listing",
        "function saasCeoRouteSimpleReason",
        "function saasCeoRoutingWhyRows",
        "function saasCeoModuleGoalView",
        "function renderSaasModuleAiGoalStrip",
        "function renderSaasModuleAiGoalStripIntoView",
        'data-ai-ceo-module-goal-strip="ai_ceo_module_goal_v1"',
        "小批量实验目标已带入",
        "素材目标已带入",
        "客服订单目标已带入",
        "高风险动作已拦住",
        "AI CEO 路由确认",
        "我理解",
        "推荐去",
        "安全边界",
        "只整理草稿，真实动作仍确认",
        "先确认，未点头不执行",
        '<details class="saas-ceo-route-closure"',
        "查看处理步骤",
        "function renderSaasAiCeoSourceRecordsMarkup",
        "function normalizeSaasAiCeoWorkRecords",
        "function normalizeSaasAiCeoConfirmationItems",
        "function renderSaasAiCeoWorkRecordsMarkup",
        "function renderSaasAiCeoConfirmationItemsMarkup",
        "function renderSaasAiCeoWorkDetailMarkup",
        "function shouldShowSaasAiCeoWorkDetail",
        "function isSaasAiCeoPlainConsultationTurn",
        "function shouldRecordSaasCeoCommandSourceRecord",
        "saas-ai-ceo-work-detail",
        "查看工作详情",
        "source_records",
        "work_records",
        "confirmation_items",
        "source_policy",
        "search_max_results",
        "search_cache_status",
        "search_used_for_model_prompt",
        "最多 ${searchMaxResults} 条",
        "秒预算",
        "market_report_delivery",
        "normalizeSaasAiCeoMarketReportDelivery",
        "真实动作不会绕过确认中心",
        "latest.model?.provider_label",
        "route_label",
        "memory_policy",
        "general_chat",
        'route === "general_chat"',
        "!realtimeStatuses.includes(status)",
        "!latest.decision_center_required",
        "!latest.long_term_memory",
        "!latest.writes_merchant_rule",
        'route !== "general_chat"',
        "current.decision_center_required",
        "current.long_term_memory",
        "current.writes_merchant_rule",
        "confirmation_required",
        "merchant_rule_memory",
        "function buildSaasLocalClockAnswer",
        "local_clock_answered",
        "capability_status_answered",
        "realtime_search_answered",
        "merchant-ceo/chat?stream=1&fresh=${Date.now()}",
        '"cache-control": "no-store"',
        "pragma: \"no-cache\"",
        "正在处理...",
        "这是一条旧消息：当时没有保存可展示回复。",
        "external_data_source_required",
        "function renderSaasAiCeoFirstRunHandoff",
        "first_run_ai_ceo_handoff_v1",
        "first_day_ai_ceo_path_v2",
        'data-does-not-trigger-real-write="true"',
        "上传第一份商品资料",
        "默认空白工作台",
        "先提交自己的商品资料，不使用预置商品",
        "function renderSaasMerchantLaunchReadinessPath",
        "merchant_launch_readiness_path_v1",
        "正式经营准备",
        "没有完成店铺连接和正式收款前，也可以先把商品经营链路准备好",
        "先用 AI CEO",
        "沉淀商品项目",
        "补店铺与收款",
        "确认后再执行",
        "我还没接 eBay，先帮我规划上线前能做什么",
        "first_day_one_task_focus_v1",
        "提交资料",
        "核对草稿",
        "决定下一步",
        "添加商品图片、货源链接或文字说明。",
        "saas-ai-ceo-one-task-option",
        'data-ceo-prompt="${escapeHtml(prompt)}"',
        "我有商品图片，请先整理资料缺口",
        "我有货源链接，请生成一份待核对草稿",
        "我先用文字说明商品，请告诉我还缺什么",
    ]
    for needle in required_app:
        if needle not in app:
            return fail(f"missing AI CEO latest-reply app contract: {needle}")

    required_css = [
        ".saas-ai-ceo-chat-stream",
        ".saas-ai-ceo-message-body",
        ".saas-ai-ceo-work-detail",
        ".saas-ai-ceo-recovery-hint",
        ".saas-ai-ceo-market-report-delivery",
        ".saas-ai-ceo-recovery-actions",
        ".saas-ai-ceo-pending-status",
        ".saas-ai-ceo-pending-status.is-compact",
        ".message.ai.is-pending.is-superseded-pending",
        ".saas-ai-ceo-thinking-dot",
        "@keyframes saas-ai-ceo-thinking-pulse",
        ".saas-ai-ceo-source-list",
        ".saas-ai-ceo-work-record-list",
        ".saas-ai-ceo-confirmation-guidance",
        "AI CEO ChatGPT-style restoration",
        ".saas-ai-ceo-thread-intro.is-compact",
        "grid-template-rows: auto minmax(0, 1fr) auto",
        "width: min(96vw, 1320px);",
        "width: min(100%, 1120px);",
        "width: min(100%, 1040px);",
        "min-height: 64px;",
        "overflow-y: auto",
        "min-height: 0;",
        "2026-06-24 AI CEO minimal routing v2",
        ".saas-ai-ceo-input-hint",
        ".saas-ai-ceo-one-task-focus",
        ".saas-ai-ceo-one-task-grid",
        ".saas-ai-ceo-one-task-option",
        ".saas-ai-ceo-launch-readiness-path",
        ".saas-ai-ceo-launch-readiness-grid",
        ".saas-ai-ceo-launch-readiness-actions",
        ".saas-ceo-routing-main",
        ".saas-ceo-routing-why",
        ".saas-ceo-route-closure summary",
        ".saas-module-ai-goal-strip",
        ".saas-module-ai-goal-steps",
        "box-shadow: 0 14px 34px rgba(22, 50, 44, 0.08)",
        ".saas-ai-ceo-first-run-handoff",
        ".saas-ai-ceo-first-day-path",
        ".saas-ai-ceo-first-run-actions",
        "2026-06-26 mobile AI CEO handoff polish",
        ".saas-ai-ceo-thread .message.ai > span",
        ".saas-ai-ceo-thread .message.ai .saas-ai-ceo-pending-status span",
        "border-radius: 999px;",
    ]
    for needle in required_css:
        if needle not in css:
            return fail(f"missing AI CEO latest-reply CSS contract: {needle}")

    for obsolete_wait_contract in [
        "compact_wait_v1",
        "@keyframes saas-ai-ceo-wait-dot",
        ".saas-ai-ceo-pending-status.is-compact > i b",
    ]:
        if obsolete_wait_contract in app or obsolete_wait_contract in css:
            return fail(f"AI CEO must not keep the obsolete three-dot wait contract: {obsolete_wait_contract}")

    for forbidden_selector in [
        ".saas-ai-ceo-thread .message.ai span {",
        ".saas-ai-ceo-thread .message span {",
    ]:
        if forbidden_selector in css:
            return fail(f"AI CEO avatar selector must not style nested status labels: {forbidden_selector}")

    if app.index('id="ceoChat"') > app.index('id="ceoForm"'):
        return fail("AI CEO chat stream must render above the composer form")
    if "今天要捷境帮你处理什么？" in app:
        return fail("AI CEO first screen must not use the old generic greeting")
    if "直接告诉 AI CEO 你的目标" in app:
        return fail("AI CEO first screen must use the updated continuous-chat title")
    if 'id="saasAiCeoHistory"' in app or "<summary>历史对话</summary>" in app:
        return fail("AI CEO must not hide the conversation in a collapsed history section")
    if "project?.title || activeListingDraft()?.titleCn" in app:
        return fail("AI CEO workflow must not seed fresh tasks from old demo listing drafts")
    forbidden_chat_copy = [
        "正在调用后端模型",
        "正在调用后端 BYOK 模型",
        "后端模型回复尚未返回",
        "后端模型已返回",
        "当前新消息会重新调用后端模型",
        "后端模型请求失败",
        "AI CEO 暂时没有返回结果：${publicRuntimeText",
        "状态：${latest.status}",
    ]
    for needle in forbidden_chat_copy:
        if needle in app:
            return fail(f"AI CEO chat must not expose implementation copy: {needle}")

    ai_ceo_safe_write_start = app.index("function refreshSaasCeoRoutingTaskCard")
    ai_ceo_safe_write_end = app.index("function isMediaGenerationRequest", ai_ceo_safe_write_start)
    ai_ceo_safe_write_body = app[ai_ceo_safe_write_start:ai_ceo_safe_write_end]
    for forbidden_sink in [
        "slot.innerHTML = renderSaasCeoRoutingTaskCard",
        "consoleNode.outerHTML = renderSaasCeoCommandConsole",
        "panel.innerHTML = renderSaasAiCeoLatestReplyMarkup",
        "chat.insertAdjacentHTML(",
        "body.insertAdjacentHTML(\"afterend\", renderSaasAiCeo",
    ]:
        if forbidden_sink in ai_ceo_safe_write_body:
            return fail(f"AI CEO dynamic markup must use trusted JIEJING HTML sinks: {forbidden_sink}")

    print("PASS jiejing_saas_ai_ceo_latest_reply_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
