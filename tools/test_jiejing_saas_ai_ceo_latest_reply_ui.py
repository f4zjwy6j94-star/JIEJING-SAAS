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
        "function renderSaasAiCeoLatestReplyMarkup",
        'id="ceoChat"',
        "updateSaasAiCeoLatestReply({",
        "function renderSaasAiCeoChatTurnMarkup",
        "function renderSaasAiCeoThreadMarkup",
        "function upsertSaasAiCeoThreadTurn",
        "function shouldKeepSaasAiCeoThreadTurn",
        "function updateCeoAssistantMessage(messageId, text, status = \"\", model = null, sourceRecords = [])",
        "updateCeoAssistantMessage(pendingMessageId, answer, chat?.status || \"\", chat?.model_client || null, sourceRecords)",
        "直接说，我来处理",
        "普通问题直接回答；eBay 经营任务会拆成工作流",
        "需要最新信息会联网查来源",
        "问问题，或发商品/链接/图片",
        "function renderSaasAiCeoSourceRecordsMarkup",
        "function renderSaasAiCeoWorkDetailMarkup",
        "function shouldShowSaasAiCeoWorkDetail",
        "saas-ai-ceo-work-detail",
        "查看工作详情",
        "source_records",
        "latest.model?.provider_label",
        "route_label",
        "memory_policy",
        "general_chat",
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
    ]
    for needle in required_app:
        if needle not in app:
            return fail(f"missing AI CEO latest-reply app contract: {needle}")

    required_css = [
        ".saas-ai-ceo-chat-stream",
        ".saas-ai-ceo-message-body",
        ".saas-ai-ceo-work-detail",
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
        "状态：${latest.status}",
    ]
    for needle in forbidden_chat_copy:
        if needle in app:
            return fail(f"AI CEO chat must not expose implementation copy: {needle}")

    print("PASS jiejing_saas_ai_ceo_latest_reply_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
