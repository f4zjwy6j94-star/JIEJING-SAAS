"""Model-backed AI CEO chat for the Jiejing SaaS workbench.

This module is intentionally backend-only. It accepts sanitized merchant text,
adds store/workflow context, calls the resolved merchant model client, and returns
a merchant-facing answer without exposing AI credentials or eBay tokens.
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from urllib.parse import urlparse
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jiejing_runtime.models import now_iso
from jiejing_runtime.public_search import PublicSearchProbeAdapter, PublicSearchProbeConfig


AI_CEO_ROUTE_GENERAL = "general_chat"
AI_CEO_ROUTE_EBAY_WORKFLOW = "ebay_workflow"
AI_CEO_ROUTE_EXTERNAL_REALTIME = "external_realtime"
AI_CEO_ROUTE_CONFIRMATION = "confirmation_required"
AI_CEO_ROUTE_MERCHANT_RULE = "merchant_rule_memory"

MEMORY_POLICY_TRANSIENT = "transient_no_long_term_memory"
MEMORY_POLICY_OPERATING = "permanent_operating_memory"
MEMORY_POLICY_MERCHANT_RULE = "merchant_rule"


def run_ai_ceo_chat(
    *,
    repository: Any,
    company_id: str,
    store_id: str,
    user_id: str,
    message: str,
    model_client: Any,
    client_now: str = "",
    client_timezone: str = "",
    command: dict[str, Any] | None = None,
    model_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the merchant model for an AI CEO chat turn."""
    safe_message = _safe_text(message, limit=900)
    if not safe_message:
        return {
            "status": "blocked_before_model_chat",
            "blocked_by": ["empty_message"],
            "answer": "没有收到可处理的指令。",
            **ai_ceo_route_metadata(""),
            "frontend_gets_model_api_key": False,
            "secret_exposed": False,
        }
    context = build_ai_ceo_chat_context(
        repository=repository,
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        client_now=client_now,
        client_timezone=client_timezone,
    )
    model_context = _public_model_context(None, model_client, model_resolution)
    realtime_kind = _classify_external_realtime_request(safe_message)
    route = _classify_ai_ceo_route(safe_message, realtime_kind=realtime_kind)
    route_meta = ai_ceo_route_metadata(safe_message, route=route, realtime_kind=realtime_kind)
    local_clock_kind = _classify_local_clock_request(safe_message)
    if local_clock_kind:
        return {
            "status": "local_clock_answered",
            "answer": _local_clock_answer(
                kind=local_clock_kind,
                client_now=client_now,
                client_timezone=client_timezone,
            ),
            "context": context,
            "model_client": model_context,
            **route_meta,
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }
    capability_kind = _classify_ai_ceo_capability_request(safe_message)
    if capability_kind:
        return {
            "status": "capability_status_answered",
            "answer": _ai_ceo_capability_answer(model_context),
            "context": context,
            "model_client": model_context,
            **ai_ceo_route_metadata(safe_message, route=AI_CEO_ROUTE_GENERAL),
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }
    if realtime_kind:
        realtime_search = _run_realtime_search(kind=realtime_kind, message=safe_message)
        if realtime_search.get("status") == "ready":
            use_model_synthesis = _env_enabled("JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED", default=False)
            if realtime_search.get("provider") == "stooq_public_quote" or not use_model_synthesis:
                return {
                    "status": "realtime_search_answered_without_model",
                    "answer": _fallback_realtime_search_answer(realtime_kind, realtime_search),
                    "context": context,
                    "model_client": model_context,
                    "realtime_search": realtime_search,
                    "source_records": realtime_search.get("source_records") or [],
                    **route_meta,
                    "route_label": "实时搜索",
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_raw_ebay_token": False,
                    "secret_exposed": False,
                }
            search_prompt = build_ai_ceo_realtime_search_prompts(
                message=safe_message,
                context=context,
                model_context=model_context,
                route_meta=route_meta,
                realtime_search=realtime_search,
            )
            try:
                result = model_client.generate_text(
                    system_prompt=search_prompt[0],
                    user_prompt=search_prompt[1],
                    temperature=0.1,
                )
                answer = _clean_answer(result.get("text") if isinstance(result, dict) else "")
                if not answer:
                    raise RuntimeError("empty_realtime_search_answer")
                status = "realtime_search_answered"
            except Exception:
                result = {}
                answer = _fallback_realtime_search_answer(realtime_kind, realtime_search)
                status = "realtime_search_answered_without_model"
            return {
                "status": status,
                "answer": answer,
                "context": context,
                "model_client": _public_model_context(result, model_client, model_resolution) if result else model_context,
                "realtime_search": realtime_search,
                "source_records": realtime_search.get("source_records") or [],
                **route_meta,
                "route_label": "实时搜索",
                "frontend_gets_model_api_key": False,
                "runtime_gets_raw_ebay_token": False,
                "secret_exposed": False,
            }
        return {
            "status": "external_data_source_required",
            "blocked_by": realtime_search.get("blocked_by") or ["public_search_provider_not_configured"],
            "answer": _external_realtime_answer(realtime_kind, model_context, realtime_search),
            "context": context,
            "model_client": model_context,
            "realtime_search": realtime_search,
            **route_meta,
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }

    system_prompt, user_prompt = build_ai_ceo_chat_prompts(
        message=safe_message,
        context=context,
        command=command,
        model_context=model_context,
        route=route,
        route_meta=route_meta,
    )
    try:
        result = model_client.generate_text(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.2)
    except Exception as exc:  # pragma: no cover - provider dependent
        failure_code, failure_reason = _classify_model_failure(exc)
        return {
            "status": "model_call_failed",
            "blocked_by": [failure_code],
            "answer": _model_unavailable_fallback_answer(route_meta, failure_reason),
            "context": context,
            "model_client": model_context,
            "provider_error_type": failure_code,
            **route_meta,
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }

    answer = _clean_answer(result.get("text") if isinstance(result, dict) else "")
    if not answer:
        return {
            "status": "model_call_failed",
            "blocked_by": ["empty_model_answer"],
            "answer": _model_unavailable_fallback_answer(route_meta, "模型服务这次没有返回可展示内容。"),
            "context": context,
            "model_client": _public_model_context(result, model_client, model_resolution),
            **route_meta,
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }
    model_mode = str((result or {}).get("model_mode") or "")
    status = "model_answered" if model_mode.startswith("live_") else "model_answered_non_live"
    return {
        "status": status,
        "answer": answer,
        "context": context,
        "model_client": _public_model_context(result, model_client, model_resolution),
        **route_meta,
        "frontend_gets_model_api_key": False,
        "runtime_gets_raw_ebay_token": False,
        "secret_exposed": False,
    }


class _FastRouteModelContext:
    name = "ai_ceo_fast_route"
    model = ""
    endpoint = ""


def run_ai_ceo_fast_turn(
    *,
    repository: Any,
    company_id: str,
    store_id: str,
    user_id: str,
    message: str,
    client_now: str = "",
    client_timezone: str = "",
) -> dict[str, Any] | None:
    """Answer routes that do not need merchant model secret resolution."""
    safe_message = _safe_text(message, limit=900)
    if not safe_message:
        return None
    context = build_ai_ceo_chat_context(
        repository=repository,
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        client_now=client_now,
        client_timezone=client_timezone,
    )
    model_context = _public_model_context(
        None,
        _FastRouteModelContext(),
        {
            "provider_key": "fast_route",
            "provider_label": "AI CEO",
            "model": "",
            "merchant_pays_provider_directly": False,
        },
    )
    realtime_kind = _classify_external_realtime_request(safe_message)
    route = _classify_ai_ceo_route(safe_message, realtime_kind=realtime_kind)
    route_meta = ai_ceo_route_metadata(safe_message, route=route, realtime_kind=realtime_kind)
    if not realtime_kind:
        return None
    realtime_search = _run_realtime_search(kind=realtime_kind, message=safe_message)
    if realtime_search.get("status") == "ready":
        return {
            "status": "realtime_search_answered_without_model",
            "answer": _fallback_realtime_search_answer(realtime_kind, realtime_search),
            "context": context,
            "model_client": model_context,
            "realtime_search": realtime_search,
            "source_records": realtime_search.get("source_records") or [],
            **route_meta,
            "route_label": "实时搜索",
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "secret_exposed": False,
        }
    return {
        "status": "external_data_source_required",
        "blocked_by": realtime_search.get("blocked_by") or ["public_search_provider_not_configured"],
        "answer": _external_realtime_answer(realtime_kind, model_context, realtime_search),
        "context": context,
        "model_client": model_context,
        "realtime_search": realtime_search,
        **route_meta,
        "frontend_gets_model_api_key": False,
        "runtime_gets_raw_ebay_token": False,
        "secret_exposed": False,
    }


def ai_ceo_route_metadata(
    message: str,
    *,
    route: str = "",
    realtime_kind: str = "",
) -> dict[str, Any]:
    """Return public route and memory metadata for a chat message."""
    safe_message = _safe_text(message, limit=900)
    realtime = realtime_kind or _classify_external_realtime_request(safe_message)
    selected_route = route or _classify_ai_ceo_route(safe_message, realtime_kind=realtime)
    labels = {
        AI_CEO_ROUTE_GENERAL: "直接回答",
        AI_CEO_ROUTE_EBAY_WORKFLOW: "已进入经营任务",
        AI_CEO_ROUTE_EXTERNAL_REALTIME: "实时搜索",
        AI_CEO_ROUTE_CONFIRMATION: "等待确认",
        AI_CEO_ROUTE_MERCHANT_RULE: "已记录规则",
    }
    if selected_route == AI_CEO_ROUTE_MERCHANT_RULE:
        memory_policy = MEMORY_POLICY_MERCHANT_RULE
    elif selected_route in {AI_CEO_ROUTE_EBAY_WORKFLOW, AI_CEO_ROUTE_CONFIRMATION}:
        memory_policy = MEMORY_POLICY_OPERATING
    else:
        memory_policy = MEMORY_POLICY_TRANSIENT
    return {
        "route": selected_route,
        "route_label": labels.get(selected_route, "直接回答"),
        "memory_policy": memory_policy,
        "long_term_memory": memory_policy != MEMORY_POLICY_TRANSIENT,
        "writes_merchant_rule": memory_policy == MEMORY_POLICY_MERCHANT_RULE,
        "decision_center_required": selected_route == AI_CEO_ROUTE_CONFIRMATION,
        "audit_required": selected_route in {AI_CEO_ROUTE_EBAY_WORKFLOW, AI_CEO_ROUTE_CONFIRMATION},
        "realtime_kind": realtime,
    }


def build_ai_ceo_chat_context(
    *,
    repository: Any,
    company_id: str,
    store_id: str,
    user_id: str,
    client_now: str = "",
    client_timezone: str = "",
) -> dict[str, Any]:
    store = repository.get_store_for_company(company_id=company_id, store_id=store_id) or {}
    packets = repository.list_platform_data_packets(company_id=company_id, store_id=store_id, platform="ebay", limit=1)
    latest_packet = packets[0] if packets else {}
    confirmations = repository.list_confirmations(company_id=company_id, status="pending", limit=50)
    store_tasks = repository.list_tasks(company_id=company_id, store_id=store_id, limit=8)
    reports = repository.list_reports(company_id=company_id, limit=8)
    packet = latest_packet.get("packet") if isinstance(latest_packet.get("packet"), dict) else {}
    return {
        "server_now": now_iso(),
        "client_now": _safe_text(client_now, limit=80),
        "client_timezone": _safe_text(client_timezone, limit=80),
        "store": {
            "store_id": store_id,
            "platform": _safe_text(store.get("platform") or "ebay", limit=40),
            "store_name": _safe_text(store.get("store_name") or "", limit=160),
            "marketplace": _safe_text(store.get("marketplace") or "", limit=60),
            "connection_status": _safe_text(
                store.get("connection_status") or store.get("status") or "",
                limit=80,
            ),
        },
        "latest_packet": {
            "packet_id": _safe_text(latest_packet.get("packet_id") or "", limit=120),
            "source_mode": _safe_text(latest_packet.get("source_mode") or packet.get("source_mode") or "", limit=80),
            "status": _safe_text(latest_packet.get("status") or packet.get("status") or "", limit=80),
            "resource_summary": _safe_packet_summary(packet),
        },
        "reports": {
            "recent_count": len(reports),
            "recent_types": [_safe_text(item.get("report_type") or "", limit=80) for item in reports[:6]],
        },
        "confirmations": {
            "pending_count": len(confirmations),
            "pending_titles": [_safe_text(item.get("title") or item.get("action_type") or "", limit=120) for item in confirmations[:6]],
        },
        "recent_tasks": {
            "count": len(store_tasks),
            "types": [_safe_text(item.get("task_type") or "", limit=80) for item in store_tasks[:6]],
        },
        "user_id_present": bool(user_id),
        "secret_exposed": False,
    }


def build_ai_ceo_chat_prompts(
    *,
    message: str,
    context: dict[str, Any],
    command: dict[str, Any] | None = None,
    model_context: dict[str, Any] | None = None,
    route: str = AI_CEO_ROUTE_GENERAL,
    route_meta: dict[str, Any] | None = None,
) -> tuple[str, str]:
    system_prompt = (
        "你是捷境 Jiejing 的 AI CEO，产品定位是 eBay-first AI 经营工作台，不是通用 ERP、Agent 市场或普通聊天机器人。"
        "但你必须具备完整文字大模型的普通咨询能力：翻译、写作、解释概念、经营常识、沟通话术、利润算法、非实时政策理解和普通知识问答，都要自然直接回答，不能因为问题不属于 eBay 就拒答。"
        "你的职业感来自把对话导向经营闭环：普通咨询先回答清楚，如确实相关，可以简短补一句可基于当前店铺、Listing 或 packet 做进一步诊断。"
        "用户不需要知道路由细节，你要自己判断。"
        "eBay 经营任务包括选品、Market Report、IP/VeRO、防侵权、Listing、素材工坊、客服与订单、财务履约、费用利润、发布体检、确认中心和复盘。"
        "真实发布、采购付款、改价、库存、退款、广告、政策、敏感客服承诺必须停在决策中心，不能绕过确认中心。"
        "实时股价、新闻、汇率、天气、网页搜索等必须走外部实时搜索或专用数据源；有来源时按来源回答，没有来源时诚实说明缺口，不能编最新数值。"
        "记忆边界必须清楚：普通闲聊、经验咨询、卖货建议、店铺泛问默认不写长期经营记忆；只有用户明确说“记住这个规则”“以后都按这个做”等，才写商家规则。"
        "eBay 工作流、确认、真实执行、报告必须写入审计和永久经营记忆。"
        "不要要求用户重复 eBay OAuth 或重复配置 AI 连接，除非上下文明确显示缺失或模型服务明确拒绝。"
        "不要暴露 AI 连接凭证、eBay token、refresh token、密码或任何 secret。"
        "商家可见回答不要出现“正在调用模型”“后端模型已返回”“BYOK 模型已返回”等实现过程文案；只展示直接回答、经营任务、实时数据缺口或等待确认等产品状态。"
        "商家可见回答必须使用简体中文；eBay、SKU、Listing、Market Report、Listing Package 等专有名词可以保留英文。"
        "回答要像产品级 SaaS 工作台里的 AI CEO：清楚、具体、可执行，不空泛。"
    )
    if route == AI_CEO_ROUTE_GENERAL:
        system_prompt += " 当前路由是普通咨询：像 DeepSeek 一样直接回答，不创建经营任务，不写长期经营记忆。"
    elif route == AI_CEO_ROUTE_EBAY_WORKFLOW:
        system_prompt += " 当前路由是 eBay 经营任务：输出目标、计划、来源/缺口、风险、需要确认的动作、下一步，并保持真实写入确认边界。"
    elif route == AI_CEO_ROUTE_CONFIRMATION:
        system_prompt += " 当前路由是高风险动作：不要声称已执行，只说明需要进入决策中心确认，并列出发布/改价/库存/退款/广告/政策等执行前检查项。"
    elif route == AI_CEO_ROUTE_MERCHANT_RULE:
        system_prompt += " 当前路由是商家规则记忆：确认已理解规则，说明适用范围、例外情况和后续如何在经营任务中使用。"

    payload = {
        "merchant_message": message,
        "route": route,
        "route_meta": route_meta or {},
        "current_context": _prompt_context_for_route(context, route),
        "current_model_client": model_context or {},
        "frontend_command_plan": _safe_command(command) if route != AI_CEO_ROUTE_GENERAL else {},
        "response_rules": [
            "先回答用户当前问题，再给必要的下一步。",
            "普通咨询不写长期经营记忆。",
            "只有明确要求记住规则时才写商家规则。",
            "经营任务体现来源记录、确认中心和审计回流。",
            "没有实时来源记录时不要编造最新外部数据。",
        ],
    }
    return system_prompt, json.dumps(payload, ensure_ascii=False, default=str)


def build_ai_ceo_realtime_search_prompts(
    *,
    message: str,
    context: dict[str, Any],
    model_context: dict[str, Any] | None = None,
    route_meta: dict[str, Any] | None = None,
    realtime_search: dict[str, Any],
) -> tuple[str, str]:
    system_prompt = (
        "你是捷境 Jiejing 的 AI CEO。现在这轮问题已经通过后端实时搜索拿到公开网页来源。"
        "你必须只依据 source_records 回答，不得把训练记忆当成实时来源，也不得编造股价、新闻、汇率、天气或网页内容。"
        "如果来源片段不足以确认精确数值，就明确说无法从当前来源确认精确值，并给出可继续查证的来源。"
        "商家可见回答必须使用简体中文；eBay、SKU、Listing、Market Report、Listing Package、NASDAQ、NYSE 等专有名词可以保留英文。"
        "回答要短、直接、带时间感和来源；不要出现“调用模型”“后端模型”“BYOK”“Tavily API key”等实现词。"
        "需要执行真实发布、改价、库存、退款、广告、政策、付款或敏感客服承诺时，必须停在决策中心。"
        "普通实时咨询默认不写长期经营记忆。"
    )
    source_records = realtime_search.get("source_records") if isinstance(realtime_search.get("source_records"), list) else []
    payload = {
        "merchant_message": message,
        "route_meta": route_meta or {},
        "current_context": _prompt_context_for_route(context, AI_CEO_ROUTE_EXTERNAL_REALTIME),
        "current_model_client": model_context or {},
        "realtime_search": {
            "status": realtime_search.get("status"),
            "provider": realtime_search.get("provider"),
            "query": realtime_search.get("query"),
            "captured_at": realtime_search.get("captured_at"),
            "source_records": source_records[:5],
            "secret_exposed": False,
        },
        "response_rules": [
            "先给直接答案；再用 1-3 条列出来源和限制。",
            "每个来源尽量带标题、域名或 URL。",
            "没有足够证据时说清楚缺口，不要编数字。",
            "不要写入长期商家记忆，除非用户明确说记住规则。",
        ],
    }
    return system_prompt, json.dumps(payload, ensure_ascii=False, default=str)


def _prompt_context_for_route(context: dict[str, Any], route: str) -> dict[str, Any]:
    if route != AI_CEO_ROUTE_GENERAL:
        return context
    return {
        "server_now": context.get("server_now"),
        "client_now": context.get("client_now"),
        "client_timezone": context.get("client_timezone"),
        "store": context.get("store") or {},
        "secret_exposed": False,
    }


def _classify_ai_ceo_route(message: str, *, realtime_kind: str = "") -> str:
    text = _normalized_text(message)
    if realtime_kind:
        return AI_CEO_ROUTE_EXTERNAL_REALTIME
    if _looks_like_explicit_rule_memory(text):
        return AI_CEO_ROUTE_MERCHANT_RULE
    if _looks_like_high_risk_action(text):
        return AI_CEO_ROUTE_CONFIRMATION
    if _looks_like_ebay_workflow(text):
        return AI_CEO_ROUTE_EBAY_WORKFLOW
    return AI_CEO_ROUTE_GENERAL


def _classify_local_clock_request(message: str) -> str:
    text = _normalized_text(message)
    if not text:
        return ""
    if any(marker in text for marker in ("现在几点", "几点了", "当前时间", "现在时间", "北京时间", "what time", "current time", "time is it")):
        return "time"
    if any(marker in text for marker in ("今天几号", "今天日期", "今天是几号", "今天星期几", "今天周几", "current date", "today's date", "date today")):
        return "date"
    return ""


def _classify_ai_ceo_capability_request(message: str) -> str:
    text = _normalized_text(message)
    if not text:
        return ""
    subject_markers = ("你", "ai", "aiceo", "ai ceo", "捷境", "deepseek", "大模型")
    capability_markers = (
        "连接网络",
        "接网络",
        "有联网",
        "能联网",
        "联网了吗",
        "联网搜索",
        "实时搜索",
        "连接大模型",
        "接大模型",
        "接 deepseek",
        "连 deepseek",
        "连接 deepseek",
        "connected to the internet",
        "web search",
        "deepseek connected",
    )
    question_markers = ("吗", "有没有", "是否", "现在", "状态", "能不能", "可以不", "?")
    if any(subject in text for subject in subject_markers) and any(marker in text for marker in capability_markers):
        return "capability_status"
    if any(marker in text for marker in capability_markers) and any(marker in text for marker in question_markers):
        return "capability_status"
    return ""


def _ai_ceo_capability_answer(model_context: dict[str, Any]) -> str:
    provider = _safe_text(model_context.get("provider_label") or model_context.get("provider_key") or model_context.get("name") or "AI", limit=80) or "AI"
    model = _safe_text(model_context.get("model") or "", limit=80)
    ai_label = f"{provider} / {model}" if model else provider
    search_status = PublicSearchProbeAdapter().provider_status("tavily")
    generic_search_ready = bool(search_status.get("configured")) and _env_enabled("JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED", default=True)
    builtin_web_ready = _env_enabled("JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED", default=True)
    if generic_search_ready:
        search_line = "通用实时搜索已接入：最新新闻、网页资料、公开市场信息会先查来源，再给结论。"
    elif builtin_web_ready:
        search_line = "实时联网兜底已启用：通用网页、新闻 RSS 和公开股票报价会走后端公共来源检索，前端不会拿到任何搜索 key。"
    else:
        search_line = "通用实时搜索 provider 还没配置；需要最新网页信息时我会说明缺口，不会编。"
    return (
        f"AI 已接通：{ai_label}。\n\n"
        f"{search_line}\n\n"
        "普通咨询、翻译、写作、解释概念可以直接答；eBay 经营任务会进入捷境工作流；发布、改价、库存、退款、广告、政策和敏感客服承诺仍必须进决策中心。"
    )


def _local_clock_answer(*, kind: str, client_now: str = "", client_timezone: str = "") -> str:
    tz_name = _safe_text(client_timezone, limit=80) or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = "Asia/Shanghai"
        tz = timezone(timedelta(hours=8))
    now = _parse_client_now(client_now, tz) or datetime.now(tz)
    label = "北京时间" if tz_name == "Asia/Shanghai" else f"{tz_name} 时间"
    weekday = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")[now.weekday()]
    date_text = f"{now.year}年{now.month}月{now.day}日 {weekday}"
    if kind == "time":
        return f"现在{label}是 {date_text} {now.hour:02d}:{now.minute:02d} 左右。"
    return f"今天是 {date_text}（{label}）。"


def _parse_client_now(client_now: str, tz: tzinfo) -> datetime | None:
    raw = _safe_text(client_now, limit=120)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _classify_external_realtime_request(message: str) -> str:
    text = _normalized_text(message)
    if not text:
        return ""
    current_markers = ("现在", "当前", "实时", "最新", "今天", "此刻", "刚刚", "now", "current", "latest", "today")
    stock_markers = ("股价", "股票", "行情", "报价", "盘前", "盘后", "涨跌", "收盘", "市值", "share price", "stock price", "quote")
    market_entities = (
        "英伟达",
        "nvidia",
        "nvda",
        "特斯拉",
        "tesla",
        "tsla",
        "苹果",
        "aapl",
        "纳斯达克",
        "nasdaq",
        "标普",
        "s&p",
    )
    if any(marker in text for marker in stock_markers) and (
        any(entity in text for entity in market_entities) or any(marker in text for marker in current_markers)
    ):
        return "stock_quote"
    if any(marker in text for marker in ("最新新闻", "今天新闻", "实时新闻", "刚刚发生", "热搜", "news today", "latest news")):
        return "news_search"
    if any(marker in text for marker in ("汇率", "exchange rate", "fx rate")) and any(marker in text for marker in current_markers):
        return "exchange_rate"
    if any(marker in text for marker in ("天气", "weather")) and any(marker in text for marker in current_markers + ("明天", "tomorrow")):
        return "weather"
    if any(marker in text for marker in ("联网搜索", "上网查", "帮我查", "查一下", "搜索最新", "实时搜索", "web search", "search web")):
        return "web_search"
    if any(marker in text for marker in ("最新", "实时", "今天", "现在", "刚刚", "latest", "today", "current")) and any(
        marker in text for marker in ("新闻", "政策", "规则", "变动", "资料", "信息", "news", "policy", "update")
    ):
        return "news_search"
    if any(marker in text for marker in ("帮我搜", "联网查", "搜索一下", "google 一下", "google一下", "web search", "search web")):
        return "web_search"
    return ""


def _run_realtime_search(*, kind: str, message: str) -> dict[str, Any]:
    provider = _safe_text(
        os.environ.get("JIEJING_AI_CEO_SEARCH_PROVIDER")
        or os.environ.get("JIEJING_PUBLIC_SEARCH_PROVIDER")
        or "tavily",
        limit=60,
    )
    adapter = PublicSearchProbeAdapter()
    query = _realtime_search_query(kind=kind, message=message)
    timeout_seconds = _env_int("JIEJING_AI_CEO_SEARCH_TIMEOUT_SECONDS", default=8, minimum=3, maximum=20)
    max_results = _env_int("JIEJING_AI_CEO_SEARCH_MAX_RESULTS", default=5, minimum=1, maximum=8)
    live_enabled = _env_enabled("JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED", default=True)
    captured_at = now_iso()
    status = adapter.provider_status(provider)
    if not status.get("configured"):
        builtin = _run_builtin_public_realtime_source(kind=kind, message=message, query=query, captured_at=captured_at)
        if builtin.get("status") == "ready":
            return builtin
        return {
            "status": "blocked",
            "blocked_by": ["public_search_provider_not_configured"],
            "provider": provider,
            "provider_status": status,
            "query": query,
            "captured_at": captured_at,
            "source_records": [],
            "frontend_gets_search_api_key": False,
            "secret_exposed": False,
        }
    snapshot = adapter.probe(
        PublicSearchProbeConfig(
            query=query,
            provider=provider,
            marketplace_context="eBay merchant realtime web context",
            live_enabled=live_enabled,
            timeout_seconds=timeout_seconds,
            max_results=max_results,
            search_depth=_safe_text(os.environ.get("JIEJING_AI_CEO_SEARCH_DEPTH") or "basic", limit=24) or "basic",
        )
    )
    snapshot_status = _safe_text(snapshot.get("status") or "", limit=80)
    records = _source_records_from_search_snapshot(snapshot)
    if snapshot_status in {"ready", "partial"} and records:
        return {
            "status": "ready",
            "provider": _safe_text(snapshot.get("provider") or provider, limit=60),
            "provider_status": status,
            "query": _safe_text(snapshot.get("query") or query, limit=300),
            "captured_at": captured_at,
            "summary": _safe_text(snapshot.get("summary") or "", limit=500),
            "source_records": records,
            "frontend_gets_search_api_key": False,
            "secret_exposed": False,
        }
    builtin = _run_builtin_public_realtime_source(kind=kind, message=message, query=query, captured_at=captured_at)
    if builtin.get("status") == "ready":
        return builtin
    blocked_by = ["public_search_provider_error"] if snapshot_status == "failed_tool" else ["public_search_no_results"]
    if not live_enabled:
        blocked_by = ["public_search_disabled"]
    return {
        "status": "blocked",
        "blocked_by": blocked_by,
        "provider": provider,
        "provider_status": status,
        "query": query,
        "captured_at": captured_at,
        "summary": _safe_text(snapshot.get("summary") or snapshot.get("error") or "", limit=500),
        "source_records": records,
        "frontend_gets_search_api_key": False,
        "secret_exposed": False,
    }


def _realtime_search_query(*, kind: str, message: str) -> str:
    text = _safe_text(message, limit=260)
    lowered = text.lower()
    if kind == "stock_quote":
        if any(marker in lowered for marker in ("英伟达", "nvidia", "nvda")):
            return "NVDA NVIDIA current stock price today quote official market source"
        if any(marker in lowered for marker in ("特斯拉", "tesla", "tsla")):
            return "TSLA Tesla current stock price today quote official market source"
        if any(marker in lowered for marker in ("苹果", "apple", "aapl")):
            return "AAPL Apple current stock price today quote official market source"
        return f"{text} current stock price quote official market source"
    if kind == "exchange_rate":
        return f"{text} current exchange rate official source"
    if kind == "weather":
        return f"{text} current weather official forecast"
    if kind == "news_search":
        return f"{text} latest news reliable sources"
    return f"{text} reliable web sources"


def _run_builtin_public_realtime_source(*, kind: str, message: str, query: str, captured_at: str) -> dict[str, Any]:
    if not _env_enabled("JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED", default=True):
        return {
            "status": "blocked",
            "blocked_by": ["builtin_public_web_fallback_disabled"],
            "provider": "builtin_public_web",
            "query": query,
            "captured_at": captured_at,
            "source_records": [],
            "secret_exposed": False,
        }
    if kind == "stock_quote":
        return _run_stooq_stock_quote(message=message, query=query, captured_at=captured_at)
    if kind == "news_search":
        news = _run_builtin_news_search(query=query, captured_at=captured_at)
        if news.get("status") == "ready":
            return news
    web = _run_builtin_web_search(query=query, captured_at=captured_at)
    if web.get("status") == "ready":
        return web
    return {
        "status": "blocked",
        "blocked_by": ["public_search_provider_not_configured"],
        "provider": "builtin_public_web",
        "query": query,
        "captured_at": captured_at,
        "source_records": [],
        "secret_exposed": False,
    }


def _run_builtin_news_search(*, query: str, captured_at: str) -> dict[str, Any]:
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    )
    try:
        raw = _http_get_text(url, accept="application/rss+xml, application/xml, text/xml")
        root = ET.fromstring(raw)
    except Exception as exc:  # pragma: no cover - network/provider dependent
        return {
            "status": "blocked",
            "blocked_by": ["public_news_source_error"],
            "provider": "google_news_rss",
            "query": query,
            "captured_at": captured_at,
            "summary": _safe_text(exc, limit=160),
            "source_records": [],
            "secret_exposed": False,
        }
    records: list[dict[str, Any]] = []
    for item in root.findall("./channel/item")[:5]:
        title = _plain_public_text(item.findtext("title") or "")
        link = _normalize_public_search_url(item.findtext("link") or "")
        snippet = _plain_public_text(item.findtext("description") or "")
        source_name = _plain_public_text(item.findtext("source") or "")
        published_at = _plain_public_text(item.findtext("pubDate") or "")
        if not (title or link or snippet):
            continue
        records.append(
            {
                "title": _safe_text(title, limit=180),
                "url": _safe_text(link, limit=500),
                "domain": _safe_text(_domain_from_url(link) or source_name, limit=160),
                "snippet": _safe_text(snippet, limit=520),
                "captured_at": _safe_text(published_at or captured_at, limit=100),
                "source_type": "live_public_news_search",
                "provider": "google_news_rss",
                "confidence": "public_news_source",
                "secret_exposed": False,
            }
        )
    if records:
        return {
            "status": "ready",
            "provider": "builtin_public_news",
            "provider_status": {
                "provider": "google_news_rss",
                "configured": True,
                "credential_present": False,
                "credential_source": "no_key_public_news_source",
                "secret_exposed": False,
            },
            "query": query,
            "captured_at": captured_at,
            "summary": f"Public news source returned {len(records)} source records.",
            "source_records": records,
            "frontend_gets_search_api_key": False,
            "secret_exposed": False,
        }
    return {
        "status": "blocked",
        "blocked_by": ["public_news_no_results"],
        "provider": "google_news_rss",
        "query": query,
        "captured_at": captured_at,
        "source_records": [],
        "secret_exposed": False,
    }


def _run_builtin_web_search(*, query: str, captured_at: str) -> dict[str, Any]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "us-en"})
    records: list[dict[str, Any]] = []
    try:
        raw = _http_get_text(url, accept="text/html,application/xhtml+xml")
        records = _duckduckgo_html_records(raw, captured_at=captured_at)
    except Exception:
        records = []
    if not records:
        records = _duckduckgo_instant_answer_records(query=query, captured_at=captured_at)
    if records:
        return {
            "status": "ready",
            "provider": "builtin_public_web",
            "provider_status": {
                "provider": "duckduckgo_public",
                "configured": True,
                "credential_present": False,
                "credential_source": "no_key_public_web_source",
                "secret_exposed": False,
            },
            "query": query,
            "captured_at": captured_at,
            "summary": f"Public web source returned {len(records)} source records.",
            "source_records": records[:5],
            "frontend_gets_search_api_key": False,
            "secret_exposed": False,
        }
    return {
        "status": "blocked",
        "blocked_by": ["public_web_no_results"],
        "provider": "duckduckgo_public",
        "query": query,
        "captured_at": captured_at,
        "source_records": [],
        "secret_exposed": False,
    }


def _duckduckgo_html_records(raw: str, *, captured_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    title_pattern = re.compile(
        r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'(?:class="[^"]*result__snippet[^"]*"[^>]*>)(.*?)</(?:a|div)>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = [_plain_public_text(match.group(1)) for match in snippet_pattern.finditer(raw)]
    for index, match in enumerate(title_pattern.finditer(raw)):
        title = _plain_public_text(match.group(2))
        link = _normalize_public_search_url(match.group(1))
        if not (title or link):
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        records.append(
            {
                "title": _safe_text(title, limit=180),
                "url": _safe_text(link, limit=500),
                "domain": _safe_text(_domain_from_url(link), limit=160),
                "snippet": _safe_text(snippet, limit=520),
                "captured_at": captured_at,
                "source_type": "live_public_web_search",
                "provider": "duckduckgo_public",
                "confidence": "public_web_source",
                "secret_exposed": False,
            }
        )
        if len(records) >= 5:
            break
    return records


def _duckduckgo_instant_answer_records(*, query: str, captured_at: str) -> list[dict[str, Any]]:
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": "1", "no_redirect": "1", "skip_disambig": "1"}
    )
    try:
        data = json.loads(_http_get_text(url, accept="application/json"))
    except Exception:  # pragma: no cover - network/provider dependent
        return []
    records: list[dict[str, Any]] = []
    abstract = _plain_public_text(data.get("AbstractText") or data.get("Answer") or "")
    abstract_url = _normalize_public_search_url(data.get("AbstractURL") or "")
    abstract_source = _plain_public_text(data.get("AbstractSource") or "")
    if abstract or abstract_url:
        records.append(
            {
                "title": _safe_text(abstract_source or data.get("Heading") or "DuckDuckGo instant answer", limit=180),
                "url": _safe_text(abstract_url, limit=500),
                "domain": _safe_text(_domain_from_url(abstract_url) or abstract_source, limit=160),
                "snippet": _safe_text(abstract, limit=520),
                "captured_at": captured_at,
                "source_type": "live_public_web_search",
                "provider": "duckduckgo_public",
                "confidence": "public_instant_answer",
                "secret_exposed": False,
            }
        )
    for item in _iter_duckduckgo_related_topics(data.get("RelatedTopics")):
        if len(records) >= 5:
            break
        title = _plain_public_text(item.get("Text") or "")
        link = _normalize_public_search_url(item.get("FirstURL") or "")
        if not (title or link):
            continue
        records.append(
            {
                "title": _safe_text(title.split(" - ")[0], limit=180),
                "url": _safe_text(link, limit=500),
                "domain": _safe_text(_domain_from_url(link), limit=160),
                "snippet": _safe_text(title, limit=520),
                "captured_at": captured_at,
                "source_type": "live_public_web_search",
                "provider": "duckduckgo_public",
                "confidence": "public_related_topic",
                "secret_exposed": False,
            }
        )
    return records


def _iter_duckduckgo_related_topics(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return items
    for item in value:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("Topics"), list):
            items.extend(_iter_duckduckgo_related_topics(item.get("Topics")))
        else:
            items.append(item)
    return items


def _http_get_text(url: str, *, accept: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "accept": accept,
            "user-agent": "Jiejing-AI-CEO/1.0 (+https://jiejing.ai)",
        },
    )
    timeout = _env_int("JIEJING_AI_CEO_SEARCH_TIMEOUT_SECONDS", default=6, minimum=3, maximum=20)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(1_200_000).decode("utf-8", errors="replace")


def _plain_public_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_public_search_url(value: Any) -> str:
    url = html.unescape(str(value or "").strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return url


def _run_stooq_stock_quote(*, message: str, query: str, captured_at: str) -> dict[str, Any]:
    symbol = _stock_symbol_from_message(message)
    if not symbol:
        return {
            "status": "blocked",
            "blocked_by": ["stock_symbol_not_detected"],
            "provider": "stooq",
            "query": query,
            "captured_at": captured_at,
            "source_records": [],
            "secret_exposed": False,
        }
    stooq_symbol = f"{symbol.lower()}.us"
    url = f"https://stooq.com/q/l/?s={urllib.parse.quote(stooq_symbol)}&f=sd2t2ohlcv&h&e=csv"
    try:
        request = urllib.request.Request(url, headers={"accept": "text/csv", "user-agent": "Jiejing-AI-CEO/1.0"})
        with urllib.request.urlopen(request, timeout=_env_int("JIEJING_AI_CEO_SEARCH_TIMEOUT_SECONDS", default=8, minimum=3, maximum=20)) as response:
            raw = response.read().decode("utf-8", errors="replace")
        rows = list(csv.DictReader(io.StringIO(raw)))
    except Exception as exc:  # pragma: no cover - network dependent
        return {
            "status": "blocked",
            "blocked_by": ["stock_quote_public_source_error"],
            "provider": "stooq",
            "query": query,
            "captured_at": captured_at,
            "summary": _safe_text(exc, limit=160),
            "source_records": [],
            "secret_exposed": False,
        }
    row = rows[0] if rows else {}
    close = _safe_text(row.get("Close") or "", limit=40)
    if not close or close.upper() == "N/D":
        return {
            "status": "blocked",
            "blocked_by": ["stock_quote_not_available"],
            "provider": "stooq",
            "query": query,
            "captured_at": captured_at,
            "source_records": [],
            "secret_exposed": False,
        }
    source_time = " ".join([_safe_text(row.get("Date") or "", limit=40), _safe_text(row.get("Time") or "", limit=40)]).strip()
    snippet = (
        f"{_safe_text(row.get('Symbol') or symbol, limit=40)} 公开报价：最新/收盘价 {close} USD；"
        f"开盘 {_safe_text(row.get('Open') or '', limit=40)}，最高 {_safe_text(row.get('High') or '', limit=40)}，"
        f"最低 {_safe_text(row.get('Low') or '', limit=40)}，成交量 {_safe_text(row.get('Volume') or '', limit=60)}。"
        f"来源时间：{source_time}；公开行情可能存在延迟。"
    )
    return {
        "status": "ready",
        "provider": "stooq_public_quote",
        "provider_status": {
            "provider": "stooq",
            "configured": True,
            "credential_present": False,
            "credential_source": "no_key_public_quote_source",
            "secret_exposed": False,
        },
        "query": query,
        "captured_at": captured_at,
        "summary": f"Public stock quote source returned {symbol} quote data.",
        "source_records": [
            {
                "title": f"{symbol} public stock quote",
                "url": url,
                "domain": "stooq.com",
                "snippet": snippet,
                "captured_at": source_time or captured_at,
                "source_type": "live_public_stock_quote",
                "provider": "stooq",
                "confidence": "public_quote_source",
                "secret_exposed": False,
            }
        ],
        "frontend_gets_search_api_key": False,
        "secret_exposed": False,
    }


def _stock_symbol_from_message(message: str) -> str:
    text = _normalized_text(message)
    if any(marker in text for marker in ("英伟达", "nvidia", "nvda")):
        return "NVDA"
    if any(marker in text for marker in ("特斯拉", "tesla", "tsla")):
        return "TSLA"
    if any(marker in text for marker in ("苹果", "apple", "aapl")):
        return "AAPL"
    symbol_match = re.search(r"\b([A-Z]{1,5})\b", _safe_text(message, limit=120).upper())
    return symbol_match.group(1) if symbol_match else ""


def _source_records_from_search_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    results = snapshot.get("results") if isinstance(snapshot.get("results"), list) else []
    provider = _safe_text(snapshot.get("provider") or "", limit=60)
    records: list[dict[str, Any]] = []
    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        title = _safe_text(item.get("title") or "", limit=180)
        url = _safe_text(item.get("url") or "", limit=500)
        snippet = _safe_text(item.get("snippet") or "", limit=520)
        domain = _safe_text(item.get("domain") or _domain_from_url(url), limit=160)
        if not (title or url or snippet):
            continue
        records.append(
            {
                "title": title,
                "url": url,
                "domain": domain,
                "snippet": snippet,
                "captured_at": _safe_text(item.get("captured_at") or "", limit=80),
                "source_type": "live_public_search",
                "provider": provider,
                "confidence": _safe_text(item.get("confidence") or item.get("score") or snapshot.get("confidence") or "", limit=80),
                "secret_exposed": False,
            }
        )
    return records


def _fallback_realtime_search_answer(kind: str, realtime_search: dict[str, Any]) -> str:
    records = realtime_search.get("source_records") if isinstance(realtime_search.get("source_records"), list) else []
    captured_at = _safe_text(realtime_search.get("captured_at") or "", limit=80)
    if not records:
        return "我尝试了实时搜索，但当前没有拿到足够来源。这个问题不能用旧知识硬答，需要换一个搜索词或检查后端搜索 provider。"
    intro = "我已查到公开网页来源，但当前来源片段不足以让我直接确认精确实时数值。" if kind == "stock_quote" else "我已查到公开网页来源，先按来源给你一个简短结论。"
    source_lines = []
    for index, record in enumerate(records[:3], start=1):
        label = _safe_text(record.get("title") or record.get("domain") or record.get("url") or f"来源 {index}", limit=120)
        domain = _safe_text(record.get("domain") or _domain_from_url(str(record.get("url") or "")), limit=120)
        snippet = _safe_text(record.get("snippet") or "", limit=180)
        source_lines.append(f"{index}. {label}{f'（{domain}）' if domain else ''}：{snippet}")
    suffix = f"\n\n搜索时间：{captured_at}" if captured_at else ""
    return f"{intro}\n\n来源：\n" + "\n".join(source_lines) + suffix


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    return urlparse(url if "://" in url else f"https://{url}").netloc.lower().removeprefix("www.")


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(float(os.environ.get(name, "")))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _looks_like_explicit_rule_memory(text: str) -> bool:
    explicit_markers = (
        "记住这个规则",
        "记住这条规则",
        "记住这个偏好",
        "以后都按这个做",
        "以后都这样做",
        "以后默认",
        "以后遇到",
        "以后帮我默认",
        "作为规则",
        "写入规则",
        "长期记住",
        "remember this rule",
        "from now on",
    )
    return any(marker in text for marker in explicit_markers)


def _looks_like_high_risk_action(text: str) -> bool:
    high_risk_patterns = (
        r"(现在|马上|直接|立刻|真实|正式).{0,12}(发布|上架|刊登|publish|list it)",
        r"(发布|上架|刊登|publish).{0,12}(到|去)?\s*ebay",
        r"(改价|调整价格|change price|revise price)",
        r"(改库存|调整库存|change inventory|revise inventory)",
        r"(退款|退钱|refund|partial refund)",
        r"(广告|ad campaign|广告预算|投广告|开广告)",
        r"(付款|采购付款|打款|purchase order|procurement payment)",
        r"(修改政策|付款政策|物流政策|退货政策|payment policy|fulfillment policy|return policy)",
        r"(承诺买家|保证送达|敏感客服承诺|promise buyer)",
        r"(下架|结束 listing|end listing|delete offer|cleanup test listing)",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in high_risk_patterns)


def _looks_like_ebay_workflow(text: str) -> bool:
    concrete_verbs = (
        "生成",
        "创建",
        "跑",
        "做",
        "拆",
        "整理",
        "导入",
        "同步",
        "诊断",
        "体检",
        "筛查",
        "匹配",
        "出报告",
        "给我一份",
        "帮我做",
        "帮我生成",
        "build",
        "create",
        "run",
        "draft",
        "generate",
    )
    workflow_markers = (
        "ebay",
        "listing",
        "sku",
        "vero",
        "ip 防侵权",
        "侵权",
        "刊登",
        "上架资料",
        "铺货",
        "选品",
        "货源",
        "采购",
        "库存",
        "订单",
        "客服",
        "物流",
        "履约",
        "素材",
        "主图",
        "详情页",
        "类目",
        "item specifics",
        "business policy",
        "市场报告",
        "market report",
        "listing package",
        "packet",
        "发布体检",
        "确认中心",
        "决策中心",
        "利润模型",
        "费用",
        "毛利",
    )
    if any(marker in text for marker in workflow_markers) and any(verb in text for verb in concrete_verbs):
        return True
    if "基于当前" in text and any(marker in text for marker in workflow_markers):
        return True
    if "基于 packet" in text or "基于packet" in text:
        return True
    return False


def _external_realtime_answer(kind: str, model_context: dict[str, Any], realtime_search: dict[str, Any] | None = None) -> str:
    provider = (
        _safe_text(model_context.get("provider_label") or model_context.get("provider_key") or model_context.get("name") or "AI", limit=80)
        or "AI"
    )
    model = _safe_text(model_context.get("model") or "", limit=80)
    model_label = f"{provider} / {model}" if model else provider
    blocked_by = set(realtime_search.get("blocked_by") or []) if isinstance(realtime_search, dict) else set()
    if "public_search_provider_not_configured" in blocked_by:
        return (
            f"我已连接 {model_label}，但当前环境还没有可用的实时搜索 provider。"
            "这类问题需要后端搜索源返回带时间戳的来源记录后才能回答；我不会用旧训练数据编最新结果。"
            "把搜索 provider 配好后，我会直接给结论、来源和时间。"
        )
    if "public_search_provider_error" in blocked_by:
        return (
            f"我已连接 {model_label}，但刚才实时搜索 provider 返回失败。"
            "我不会把失败搜索包装成确定答案；请稍后重试，或检查搜索 provider 网络、额度和配置。"
        )
    if "public_search_no_results" in blocked_by:
        return (
            f"我已连接 {model_label}，也尝试了实时搜索，但当前搜索词没有拿到足够来源。"
            "我可以换更具体的关键词继续查；没有来源时不会编最新数据。"
        )
    if kind == "stock_quote":
        return (
            f"我已连接 {model_label}，但这次没有拿到可核验的实时行情来源。"
            "所以我不能直接给出英伟达这类股票的“现在股价”，也不能用旧训练数据编一个数字。"
            "拿到实时搜索或行情数据后，我会把价格、时间戳、来源和涨跌幅一起给你。"
        )
    if kind == "exchange_rate":
        return (
            f"我已连接 {model_label}，但这次没有拿到可核验的实时汇率来源。"
            "我可以解释汇率含义和计算方式，但不能编最新汇率；需要有来源和时间戳后才能给实时数值。"
        )
    if kind == "weather":
        return (
            f"我已连接 {model_label}，但这次没有拿到可核验的实时天气来源。"
            "天气这类问题必须带来源和时间戳，不能用旧知识硬答。"
        )
    return (
        f"我已连接 {model_label}，但这次没有拿到可核验的联网搜索来源。"
        "需要最新外部信息时，我会停住并说明缺口，不能把旧训练记忆当成实时来源。"
    )


def _public_model_client(result: dict[str, Any] | None, model_client: Any) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    return {
        "name": _safe_text(result.get("model_client") or getattr(model_client, "name", "model_client"), limit=120),
        "mode": _safe_text(result.get("model_mode") or "", limit=80),
        "model": _safe_text(result.get("model") or getattr(model_client, "model", ""), limit=120),
        "configured": bool(result.get("model_configured", True)),
    }


def _classify_model_failure(exc: Exception) -> tuple[str, str]:
    raw = str(exc or "")
    lowered = raw.lower()
    if "402" in lowered or any(item in lowered for item in ("quota", "balance", "billing", "payment", "credit", "insufficient")):
        return "model_quota_or_billing_limited", "模型服务返回余额、额度或计费限制。"
    if any(item in lowered for item in ("timeout", "timed out", "connection", "network", "temporarily unavailable")):
        return "model_network_or_timeout", "模型连接暂时不稳定。"
    if "401" in lowered or "403" in lowered or any(item in lowered for item in ("unauthorized", "forbidden", "invalid api key")):
        return "model_auth_or_permission_error", "模型连接权限暂时不可用。"
    return "model_provider_error", "模型服务暂时没有返回可展示内容。"


def _model_unavailable_fallback_answer(route_meta: dict[str, Any], reason: str) -> str:
    route = str((route_meta or {}).get("route") or "")
    if route == AI_CEO_ROUTE_CONFIRMATION:
        next_step = "如果这条指令涉及发布、改价、库存、退款、广告或承诺，我会先停在决策中心，等你确认后才允许继续。"
    elif route == AI_CEO_ROUTE_EBAY_WORKFLOW:
        next_step = "如果这是 eBay 经营任务，我会先把它分到 Listing、批量铺货、素材工坊、客服订单或决策中心，不会直接执行真实动作。"
    elif route == AI_CEO_ROUTE_EXTERNAL_REALTIME:
        next_step = "如果问题需要实时数据，我会要求有来源和时间戳，不能用旧知识硬答。"
    else:
        next_step = "你可以继续追问普通问题；普通聊天默认不会进入长期经营记忆。"
    return (
        f"AI CEO 已接住这条消息，但当前 AI 通道暂时不可用：{reason}"
        "这次没有触发扣费，没有写入 eBay，也没有用固定话术冒充真实模型结果。"
        f"{next_step}"
    )


def _public_model_context(
    result: dict[str, Any] | None,
    model_client: Any,
    model_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    public = _public_model_client(result, model_client)
    model_resolution = model_resolution if isinstance(model_resolution, dict) else {}
    endpoint = str(getattr(model_client, "endpoint", "") or "")
    public.update(
        {
            "provider_key": _safe_text(model_resolution.get("provider_key") or "", limit=80),
            "provider_label": _safe_text(model_resolution.get("provider_label") or "", limit=120),
            "api_style": _safe_text(model_resolution.get("api_style") or "", limit=80),
            "model": _safe_text(public.get("model") or model_resolution.get("model") or getattr(model_client, "model", ""), limit=120),
            "endpoint_host": _safe_text(model_resolution.get("endpoint_host") or urlparse(endpoint).netloc, limit=160),
            "merchant_pays_provider_directly": bool(model_resolution.get("merchant_pays_provider_directly", True)),
            "frontend_gets_model_api_key": False,
            "secret_exposed": False,
        }
    )
    return public


def _safe_command(command: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(command, dict):
        return {}
    return {
        "id": _safe_text(command.get("id") or command.get("command_id") or "", limit=120),
        "text": _safe_text(command.get("text") or command.get("command_text") or "", limit=900),
        "intent": _safe_text(command.get("intent") or "", limit=60),
        "route": _safe_text(command.get("route") or "", limit=60),
        "memory_policy": _safe_text(command.get("memory_policy") or "", limit=80),
        "routes": [
            {
                "view": _safe_text(item.get("view") or "", limit=40),
                "label": _safe_text(item.get("label") or "", limit=80),
                "status": _safe_text(item.get("status") or "", limit=80),
            }
            for item in (command.get("routes") if isinstance(command.get("routes"), list) else [])[:8]
            if isinstance(item, dict)
        ],
        "high_risk": bool(command.get("high_risk")),
    }


def _safe_packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(packet, dict):
        return {}
    sections = packet.get("resource_sections") or packet.get("resources") or packet.get("sections") or {}
    if isinstance(sections, dict):
        keys = sorted(str(key) for key, value in sections.items() if value is not None)[:12]
    elif isinstance(sections, list):
        keys = [str(item.get("key") or item.get("name") or item)[:80] for item in sections[:12]]
    else:
        keys = []
    return {
        "section_count": len(keys),
        "sections": [_safe_text(key, limit=80) for key in keys],
        "official_api": bool(packet.get("official_api") or str(packet.get("source_mode") or "").lower() == "official_api"),
    }


def _clean_answer(value: Any) -> str:
    text = _safe_text(value, limit=2200)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalized_text(value: Any) -> str:
    return _safe_text(value, limit=1200).lower().replace("ｅｂａｙ", "ebay")


def _safe_text(value: Any, *, limit: int = 600) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[model_key_redacted]", text)
    text = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [redacted]", text)
    text = re.sub(
        r"\b(access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret)\s*[:=]\s*[^,\s;]+",
        r"\1=[redacted]",
        text,
        flags=re.IGNORECASE,
    )
    return text[:limit]


def _safe_error(exc: Exception) -> str:
    return _safe_text(str(exc), limit=360) or exc.__class__.__name__
