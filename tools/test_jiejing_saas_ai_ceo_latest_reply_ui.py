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
        "saasAiCeoLatestTurn",
        "saasAiCeoThread",
        "ceoThread: \"jiejing_saas_ceo_thread\"",
        "function saasProtectedSnapshotStorageKey",
        "function hydrateSaasCeoAccountScopedLocalState",
        "function clearStoredSaasStoreContext",
        "localStorage.setItem(saasProtectedSnapshotStorageKey()",
        "for (const key of saasProtectedSnapshotStorageKeys())",
        "const raw = localStorage.getItem(key)",
        "localStorage.removeItem(saasProtectedSnapshotStorageKey())",
        "AI 用量或服务商账单挡住了本次回复",
        "不用在前台重复粘贴凭证",
        "本次不会扣捷境费用、不会写入 eBay",
        "function saasAiCeoMerchantSafeFailureText",
        "function renderSaasAiCeoRecoveryHintMarkup",
        "merchant_safe_ai_recovery_v1",
        'data-global-flow-key="model"',
        "function renderSaasAiCeoLatestReplyMarkup",
        'id="ceoChat"',
        "updateSaasAiCeoLatestReply({",
        "function renderSaasAiCeoChatTurnMarkup",
        "function renderSaasAiCeoThreadMarkup",
        "function upsertSaasAiCeoThreadTurn",
        "function shouldKeepSaasAiCeoThreadTurn",
        "function updateCeoAssistantMessage(messageId, text, status = \"\", model = null, sourceRecords = [])",
        "updateCeoAssistantMessage(pendingMessageId, answer, chat?.status || \"\", chat?.model_client || null, sourceRecords)",
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
        "AI CEO 路由确认",
        "我理解",
        "推荐去",
        "安全边界",
        "只整理草稿，真实动作仍确认",
        "先确认，未点头不执行",
        "function renderSaasAiCeoSourceRecordsMarkup",
        "function renderSaasAiCeoWorkDetailMarkup",
        "function shouldShowSaasAiCeoWorkDetail",
        "function isSaasAiCeoPlainConsultationTurn",
        "function shouldRecordSaasCeoCommandSourceRecord",
        "saas-ai-ceo-work-detail",
        "查看工作详情",
        "source_records",
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
        "merchant-ceo/chat?fresh=${Date.now()}",
        '"cache-control": "no-store"',
        "pragma: \"no-cache\"",
        "正在处理...",
        "这是一条旧消息：当时没有保存可展示回复。",
        "external_data_source_required",
        "function renderSaasAiCeoFirstRunHandoff",
        "first_run_ai_ceo_handoff_v1",
        'data-does-not-trigger-real-write="true"',
        "直接说经营目标，不用先找功能",
        "点一句只会填入输入框",
        "我还没接 eBay，先用资料跑草稿",
    ]
    for needle in required_app:
        if needle not in app:
            return fail(f"missing AI CEO latest-reply app contract: {needle}")

    required_css = [
        ".saas-ai-ceo-chat-stream",
        ".saas-ai-ceo-message-body",
        ".saas-ai-ceo-work-detail",
        ".saas-ai-ceo-recovery-hint",
        ".saas-ai-ceo-source-list",
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
        ".saas-ceo-routing-main",
        ".saas-ceo-routing-why",
        "box-shadow: 0 14px 34px rgba(22, 50, 44, 0.08)",
        ".saas-ai-ceo-first-run-handoff",
        ".saas-ai-ceo-first-run-actions",
        "border-radius: 999px;",
    ]
    for needle in required_css:
        if needle not in css:
            return fail(f"missing AI CEO latest-reply CSS contract: {needle}")

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

    print("PASS jiejing_saas_ai_ceo_latest_reply_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
