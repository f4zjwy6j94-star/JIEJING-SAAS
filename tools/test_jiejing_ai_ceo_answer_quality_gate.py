#!/usr/bin/env python3
"""Regression checks for AI CEO request/answer consistency and Listing gating."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import (  # noqa: E402
    _looks_like_platform_rule_request,
    _model_answer_rejected_fallback,
    _selection_response_contract,
    _should_retry_initial_model_failure,
    _realtime_search_query,
    build_ai_ceo_chat_context,
    run_ai_ceo_chat,
    validate_ai_ceo_answer_quality,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-ai-ceo-answer-quality-gate"


class MinimalRepository:
    def get_store_for_company(self, **_: Any) -> dict[str, Any]:
        return {"platform": "ebay", "store_name": "等待 eBay 授权", "marketplace": "EBAY_US"}

    def list_connections(self, **_: Any) -> list[dict[str, Any]]:
        return [
            {
                "connection_id": "conn_quality",
                "platform": "ebay",
                "status": "draft_save_authorized",
                "connection_type": "oauth",
            }
        ]

    def list_platform_data_packets(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_confirmations(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_tasks(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_reports(self, **_: Any) -> list[dict[str, Any]]:
        return []


class SequenceModel:
    provider = "deepseek"
    model = "deepseek-v4-pro"
    endpoint = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, answers: list[str | Exception]) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.system_prompts: list[str] = []

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        self.system_prompts.append(str(kwargs.get("system_prompt") or ""))
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        if isinstance(answer, Exception):
            raise answer
        return {
            "text": answer,
            "model_mode": "live_http_model_text",
            "model_client": "quality-gate-test",
            "model_configured": True,
            "model": self.model,
        }


class TruncatedThenTimeoutModel(SequenceModel):
    def generate_text(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "text": self.answers[0],
                "model_mode": "live_http_model_text",
                "model_client": "quality-gate-test",
                "model_configured": True,
                "model": self.model,
                "finish_reason": "length",
            }
        raise TimeoutError("continuation timed out")


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    message = "请给我三个轻小件、不带电的 eBay 选品方向，并说明选择依据。"
    unrelated = "在 eBay 上购买虚拟主机有风险，建议选择知名独立服务商。"
    valid = (
        "### 候选商品卡\n"
        "候选商品 1：可折叠硅胶漏斗\n推荐度评分：86/100\n为什么有需求：厨房和露营分装场景。\n"
        "适合 eBay/轻小件：不带电且体积小。\n主要风险：材质和尺寸待核。\nListing 草稿字段建议：Material / Type / Size。\n"
        "候选商品 2：尼龙行李拉链固定夹\n推荐度评分：82/100\n为什么有需求：旅行收纳场景明确。\n"
        "适合 eBay/轻小件：轻量且不带电。\n主要风险：承重声明待核。\nListing 草稿字段建议：Material / Pack Quantity。\n"
        "候选商品 3：软木杯垫收纳套装\n推荐度评分：79/100\n为什么有需求：桌面防护和礼品场景。\n"
        "适合 eBay/轻小件：低售后、无电池。\n主要风险：图案权利待核。\nListing 草稿字段建议：Material / Shape / Set Includes。"
    )

    context = build_ai_ceo_chat_context(
        repository=MinimalRepository(),
        company_id="company_quality",
        store_id="store_quality",
        user_id="user_quality",
    )
    assert context["store"]["connection_status"] == "draft_save_authorized", context
    assert context["store"]["connection_authorized"] is True, context
    assert context["store"]["draft_save_authorized"] is True, context
    assert "等待" not in context["store"]["store_name"], context

    strict_message = (
        "请给我三个轻小件、不带电的 eBay 选品方向。现在没有供应商、实物和商品参数，"
        "重量、尺寸、材质、采购价都未知，不要编造；本轮只做候选筛选，先不要 Listing 草稿。"
    )
    unsafe_discovery_answer = (
        "当前店铺尚未授权 eBay，请先重新授权。\n"
        "### 候选商品卡\n"
        "候选商品 1：重型订书机\n推荐度评分：86/100\n为什么有需求：办公需求稳定。\n"
        "适合 eBay/轻小件：重量约 300-600g。\n主要风险：低。\nListing 草稿字段建议：Material=Steel。\n"
        "候选商品 2：3M 胶粘理线器\n推荐度评分：82/100\n为什么有需求：桌面整理。\n"
        "适合 eBay/轻小件：采用 3M 胶。\n主要风险：低。\nListing 草稿字段建议：Brand=3M。\n"
        "候选商品 3：机械计时器\n推荐度评分：79/100\n为什么有需求：厨房使用。\n"
        "适合 eBay/轻小件：重量 450g。\n主要风险：低。\nListing 草稿字段建议：USPS First Class。"
    )
    unsafe_discovery_quality = validate_ai_ceo_answer_quality(
        message=strict_message,
        route="ebay_workflow",
        answer=unsafe_discovery_answer,
        context=context,
    )
    assert unsafe_discovery_quality["accepted"] is False, unsafe_discovery_quality
    assert "connected_store_reported_as_unauthorized" in unsafe_discovery_quality["blocked_by"], unsafe_discovery_quality
    assert "listing_scope_exceeded" in unsafe_discovery_quality["blocked_by"], unsafe_discovery_quality
    assert "invented_unknown_product_facts" in unsafe_discovery_quality["blocked_by"], unsafe_discovery_quality

    safe_discovery_answer = (
        "### 候选商品卡\n"
        "候选商品 1：无品牌行李箱拉链固定夹\n推荐度评分：84/100\n为什么有需求：适合继续核验旅行收纳需求。\n"
        "适合 eBay/轻小件：这是待验证的选品假设，不是商品参数。\n主要风险：承重与尺寸未知。\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按非带电、结构简单方向初筛。\n待补资料：材质、重量、尺寸、成本、权利信息。\n"
        "候选商品 2：无品牌抽屉标签夹\n推荐度评分：81/100\n为什么有需求：适合继续核验家庭整理需求。\n"
        "适合 eBay/轻小件：这是待验证的选品假设，不是商品参数。\n主要风险：适配尺寸未知。\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按非带电、结构简单方向初筛。\n待补资料：材质、重量、尺寸、成本、权利信息。\n"
        "候选商品 3：无品牌缝纫线轴固定夹\n推荐度评分：78/100\n为什么有需求：适合继续核验手工收纳需求。\n"
        "适合 eBay/轻小件：这是待验证的选品假设，不是商品参数。\n主要风险：适配规格未知。\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按非带电、结构简单方向初筛。\n待补资料：材质、重量、尺寸、成本、权利信息。"
    )
    safe_discovery_quality = validate_ai_ceo_answer_quality(
        message=strict_message,
        route="ebay_workflow",
        answer=safe_discovery_answer,
        context=context,
    )
    assert safe_discovery_quality["accepted"] is True, safe_discovery_quality

    acceptance_message = (
        "继续纠正上一轮选品：淘汰金属吸管、U型锁、机械计时器。重新给3个结构简单、被动式、"
        "无食品或人体接触、真正轻小、非易碎、无电无液体、无尺码或机型适配的全新候选。"
        "每个候选必须给可点击的 eBay US 搜索链接或真实 Item ID；拿不到实时成交证据就明确写成交证据不足，"
        "不要把常识当需求证据。当前没有供应商、实物或商品参数，重量、尺寸、材质、采购价都未知，严禁编造。"
        "只读，本轮只做候选筛选，先不要 Listing 草稿、不要生图、不要写 eBay。"
    )
    previous_bad_answer = (
        "候选商品 1：重型订书机\n候选商品 2：自粘式线缆管理夹\n候选商品 3：钥匙整理扣"
    )
    acceptance_history = [
        {
            "user_text": "给我三个选品",
            "assistant_text": previous_bad_answer,
            "route": "ebay_workflow",
        }
    ]
    acceptance_contract = _selection_response_contract(
        message=acceptance_message,
        route="ebay_workflow",
        conversation_history=acceptance_history,
    )
    assert acceptance_contract["required_candidate_count"] == 3, acceptance_contract
    assert acceptance_contract["listing_deferred"] is True, acceptance_contract
    assert acceptance_contract["candidate_evidence_entry_required"] is True, acceptance_contract
    assert acceptance_contract["common_sense_demand_claims_forbidden"] is True, acceptance_contract
    for excluded_name in ("金属吸管", "U型锁", "机械计时器", "重型订书机", "自粘式线缆管理夹", "钥匙整理扣"):
        assert excluded_name in acceptance_contract["excluded_candidate_names"], acceptance_contract

    acceptance_context = {**context, "selection_contract": acceptance_contract}
    repeated_candidate_answer = (
        "### 候选商品卡\n"
        "候选商品 1：重型订书机\n推荐度评分：72/100\n为什么有需求：长期稳定需求。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=heavy+duty+stapler\n成交证据不足。\n"
        "已证实事实：当前没有商品事实。\n推断依据：待验证。\n待补资料：全部商品参数。\n"
        "候选商品 2：抽屉标签夹\n推荐度评分：70/100\n为什么有需求：成交证据不足。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=drawer+label+clip\n"
        "已证实事实：当前没有商品事实。\n推断依据：待验证。\n待补资料：全部商品参数。\n"
        "候选商品 3：缝纫线轴固定夹\n推荐度评分：68/100\n为什么有需求：成交证据不足。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=sewing+spool+clip\n"
        "已证实事实：当前没有商品事实。\n推断依据：待验证。\n待补资料：全部商品参数。"
    )
    repeated_quality = validate_ai_ceo_answer_quality(
        message=acceptance_message,
        route="ebay_workflow",
        answer=repeated_candidate_answer,
        context=acceptance_context,
    )
    assert repeated_quality["accepted"] is False, repeated_quality
    assert "excluded_previous_candidate_reused" in repeated_quality["blocked_by"], repeated_quality
    assert "unsupported_common_sense_demand_claim" in repeated_quality["blocked_by"], repeated_quality

    accepted_acceptance_answer = (
        "### 候选商品卡\n"
        "候选商品 1：无品牌抽屉标签夹\n推荐度评分：74/100\n为什么有需求：成交证据不足，只进入下一轮核验。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=drawer+label+clip\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按商家约束形成待验证方向。\n"
        "待补资料：材质、重量、尺寸、成本、权利信息均未知。\n"
        "候选商品 2：无品牌窗帘拉绳收纳钩\n推荐度评分：71/100\n为什么有需求：成交证据不足，只进入下一轮核验。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=curtain+cord+tidy+hook\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按商家约束形成待验证方向。\n"
        "待补资料：材质、重量、尺寸、成本、权利信息均未知。\n"
        "候选商品 3：无品牌缝纫线轴固定夹\n推荐度评分：69/100\n为什么有需求：成交证据不足，只进入下一轮核验。\n"
        "eBay US 搜索链接：https://www.ebay.com/sch/i.html?_nkw=sewing+spool+clip\n"
        "已证实事实：当前没有供应商或实物资料。\n推断依据：按商家约束形成待验证方向。\n"
        "待补资料：材质、重量、尺寸、成本、权利信息均未知。\n"
        "结论：三个方向均只进入下一轮实物与供应商核验。"
    )
    accepted_acceptance_quality = validate_ai_ceo_answer_quality(
        message=acceptance_message,
        route="ebay_workflow",
        answer=accepted_acceptance_answer,
        context=acceptance_context,
    )
    assert accepted_acceptance_quality["accepted"] is True, accepted_acceptance_quality

    projectable_new_answer = (
        "### 候选商品卡\n"
        "候选商品 1：桌面理线套管\n推荐度评分：73/100\n为什么有需求：家庭办公是持续场景。\n"
        "适合 eBay/轻小件：重量 80g，采用塑料制成。\n"
        "候选商品 2：窗帘拉绳收纳钩\n推荐度评分：70/100\n为什么有需求：需求稳定。\n"
        "适合 eBay/轻小件：重量 30g，USPS First Class 发货。\n"
        "候选商品 3：园艺标签固定夹\n推荐度评分：68/100\n为什么有需求：常青需求。\n"
        "适合 eBay/轻小件：重量 20g，材质：金属。"
    )
    selection_with_policy_risk = (
        "请筛选三个 eBay 候选商品，每个候选说明平台政策风险、合规要求和资料缺口；"
        "只做选品，不建 Listing。"
    )
    assert _looks_like_platform_rule_request(
        message=selection_with_policy_risk,
        route="ebay_workflow",
    ) is False, "candidate requirements must not turn the whole selection answer into a platform-rule-only response"

    rejected = validate_ai_ceo_answer_quality(message=message, route="ebay_workflow", answer=unrelated)
    assert rejected["accepted"] is False, rejected
    assert rejected["candidate_count"] == 0, rejected
    accepted = validate_ai_ceo_answer_quality(message=message, route="ebay_workflow", answer=valid)
    assert accepted["accepted"] is True, accepted
    assert accepted["candidate_count"] >= 3, accepted

    rule_message = "请用三句话说明 eBay Listing 发布前最重要的三个核对项。"
    rule_sources = [
        {
            "citation_id": "S1",
            "title": "eBay picture policy",
            "domain": "ebay.com",
            "url": "https://www.ebay.com/help/policies/listing-policies/picture-policy",
        },
        {
            "citation_id": "S2",
            "title": "Seller listing guidance",
            "domain": "example.com",
            "url": "https://example.com/listing-guidance",
        },
    ]
    missing_rule_citation = validate_ai_ceo_answer_quality(
        message=rule_message,
        route="ebay_workflow",
        answer="主图必须为纯白底，所有图片不得出现参照物。",
        source_records=rule_sources,
    )
    assert missing_rule_citation["accepted"] is False, missing_rule_citation
    assert "missing_source_citation_for_platform_rule" in missing_rule_citation["blocked_by"], missing_rule_citation
    assert "unsupported_absolute_platform_rule_claim" in missing_rule_citation["blocked_by"], missing_rule_citation

    cited_rule_answer = (
        "先核对标题、类目和 Item specifics 是否与商品事实一致，这是发布前的基础检查 [S1]。\n"
        "图片应清楚展示真实商品；白底可以作为主图最佳实践，但不要在没有官方依据时写成一律要求 [S1]。\n"
        "最后确认价格、库存、物流和退货政策，真实发布仍进入确认中心。"
    )
    cited_rule_quality = validate_ai_ceo_answer_quality(
        message=rule_message,
        route="ebay_workflow",
        answer=cited_rule_answer,
        source_records=rule_sources,
    )
    assert cited_rule_quality["accepted"] is True, cited_rule_quality
    assert cited_rule_quality["citation_count"] == 1, cited_rule_quality

    truncated_rule_quality = validate_ai_ceo_answer_quality(
        message=rule_message,
        route="ebay_workflow",
        answer=(
            "发布前先核对商业政策配置，并确保支付、运输和退货设置与本次商品一致 [S1]。"
            "再核对标题、类目、Item specifics、库存和商品事实，避免草稿与实物信息不一致 [S1]。"
            "图片应清楚展示真实商品，白底可以作为提升可读性的商家最佳实践，但不要在没有官方依据时写成纯"
        ),
        source_records=rule_sources,
    )
    assert truncated_rule_quality["accepted"] is False, truncated_rule_quality
    assert "truncated_platform_rule_answer" in truncated_rule_quality["blocked_by"], truncated_rule_quality

    rule_query = _realtime_search_query(kind="web_search", message=rule_message + "，区分官方要求和商家最佳实践")
    assert "site:ebay.com/help" in rule_query, rule_query
    assert "official listing policy" in rule_query, rule_query
    assert "最佳实践" not in rule_query, rule_query

    rule_fallback = _model_answer_rejected_fallback(
        message=rule_message,
        source_records=[
            *rule_sources,
            {
                "citation_id": "S3",
                "title": "Unrelated software best practices",
                "domain": "example.org",
                "url": "https://example.org/software-best-practices",
            },
        ],
    )
    assert "规则回答未通过来源校验" in rule_fallback, rule_fallback
    assert "选品要求" not in rule_fallback and "具体候选商品卡" not in rule_fallback, rule_fallback
    assert "Unrelated software" not in rule_fallback, rule_fallback
    assert "[S1]" in rule_fallback, rule_fallback

    assert _should_retry_initial_model_failure(
        failure_code="model_network_or_timeout",
        elapsed_ms=120,
        timeout_seconds=24,
    ) is True
    assert _should_retry_initial_model_failure(
        failure_code="model_network_or_timeout",
        elapsed_ms=23_500,
        timeout_seconds=24,
    ) is False
    assert _should_retry_initial_model_failure(
        failure_code="model_auth_or_permission_error",
        elapsed_ms=100,
        timeout_seconds=24,
    ) is False

    compact_query = _realtime_search_query(
        kind="web_search",
        message="帮我找个小众品，适合 eBay 美国站，轻小件，不带电，请给市场调研报告和 Listing 字段建议。",
    )
    assert "eBay US" in compact_query, compact_query
    assert "lightweight" in compact_query and "non-electric" in compact_query, compact_query
    assert "请给市场调研报告" not in compact_query, compact_query

    previous_search = os.environ.get("JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED")
    previous_retry = os.environ.get("JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED")
    previous_initial_retry = os.environ.get("JIEJING_AI_CEO_MODEL_INITIAL_RETRY_ENABLED")
    os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED"] = "false"
    os.environ["JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED"] = "true"
    os.environ["JIEJING_AI_CEO_MODEL_INITIAL_RETRY_ENABLED"] = "true"
    try:
        repaired_model = SequenceModel([unrelated, valid])
        repaired = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=repaired_model,
        )
        assert repaired["status"] == "model_answered", repaired
        assert repaired["answer_quality"]["accepted"] is True, repaired
        assert repaired["answer_quality"]["repair_retry_count"] == 1, repaired
        assert repaired_model.calls == 2, repaired_model.calls

        strict_repaired_model = SequenceModel([repeated_candidate_answer, accepted_acceptance_answer])
        strict_repaired = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=acceptance_message,
            model_client=strict_repaired_model,
            conversation_history=acceptance_history,
        )
        assert strict_repaired["status"] == "model_answered", strict_repaired
        assert strict_repaired["answer_quality"]["accepted"] is True, strict_repaired
        assert strict_repaired_model.calls == 2, strict_repaired_model.calls
        assert "excluded_previous_candidate_reused" in strict_repaired_model.system_prompts[1], strict_repaired_model.system_prompts[1]
        assert "重型订书机" in strict_repaired_model.system_prompts[1], strict_repaired_model.system_prompts[1]

        projected_model = SequenceModel([projectable_new_answer, projectable_new_answer])
        projected_chat = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=acceptance_message,
            model_client=projected_model,
            conversation_history=acceptance_history,
        )
        assert projected_chat["status"] == "model_answered", projected_chat
        assert projected_chat["answer_quality"]["accepted"] is True, projected_chat
        assert projected_chat["answer_quality"]["contract_projection_used"] is True, projected_chat
        assert projected_model.calls == 2, projected_model.calls
        assert "80g" not in projected_chat["answer"] and "USPS First Class" not in projected_chat["answer"], projected_chat
        assert projected_chat["answer"].count("打开 eBay US 搜索") == 3, projected_chat
        assert projected_chat["answer"].count("成交证据不足") == 3, projected_chat
        assert "不生成 Listing、不生图、不写入 eBay" in projected_chat["answer"], projected_chat

        transient_model = SequenceModel([TimeoutError("provider timed out"), valid])
        transient_recovered = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=transient_model,
        )
        assert transient_recovered["status"] == "model_answered", transient_recovered
        assert transient_recovered["answer_quality"]["initial_retry_count"] == 1, transient_recovered
        assert transient_model.calls == 2, transient_model.calls

        full_timeout_model = SequenceModel([TimeoutError("provider timed out")])
        fast_fallback_model = SequenceModel([valid])
        fast_fallback_model.model = "deepseek-v4-flash"
        full_timeout_model.jiejing_fallback_model_client = fast_fallback_model
        original_timeout_classifier = full_timeout_model.generate_text

        def delayed_timeout(**kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            raise TimeoutError("provider timed out after full workflow budget")

        full_timeout_model.generate_text = delayed_timeout
        failover_recovered = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=full_timeout_model,
        )
        full_timeout_model.generate_text = original_timeout_classifier
        assert failover_recovered["status"] == "model_answered", failover_recovered
        assert failover_recovered["answer_quality"]["initial_retry_count"] == 1, failover_recovered
        assert failover_recovered["model_client"]["model"] == "deepseek-v4-flash", failover_recovered
        assert fast_fallback_model.calls == 1, fast_fallback_model.calls

        truncated_model = TruncatedThenTimeoutModel([valid])
        truncated_recovered = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=truncated_model,
        )
        assert truncated_recovered["status"] == "model_answered", truncated_recovered
        assert truncated_recovered["answer_quality"]["accepted"] is True, truncated_recovered
        assert truncated_model.calls == 2, truncated_model.calls

        auth_model = SequenceModel([RuntimeError("model HTTP 401: unauthorized")])
        auth_blocked = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=auth_model,
        )
        assert auth_blocked["provider_error_type"] == "model_auth_or_permission_error", auth_blocked
        assert auth_blocked["model_initial_retry_count"] == 0, auth_blocked
        assert auth_model.calls == 1, auth_model.calls

        rejected_model = SequenceModel([unrelated])
        rejected_chat = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=rejected_model,
        )
    finally:
        if previous_search is None:
            os.environ.pop("JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED", None)
        else:
            os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED"] = previous_search
        if previous_retry is None:
            os.environ.pop("JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED", None)
        else:
            os.environ["JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED"] = previous_retry
        if previous_initial_retry is None:
            os.environ.pop("JIEJING_AI_CEO_MODEL_INITIAL_RETRY_ENABLED", None)
        else:
            os.environ["JIEJING_AI_CEO_MODEL_INITIAL_RETRY_ENABLED"] = previous_initial_retry

    assert rejected_chat["status"] == "model_answer_rejected", rejected_chat
    assert rejected_chat["answer_quality"]["accepted"] is False, rejected_chat
    assert "虚拟主机" not in rejected_chat["answer"], rejected_chat
    assert "硅胶水槽" not in rejected_chat["answer"] and "驱蚊" not in rejected_chat["answer"], rejected_chat

    repository = SaaSRepository(OUT / "quality.sqlite")
    task = repository.create_task(
        company_id="company_quality",
        store_id="store_quality",
        user_id="user_quality",
        task_type="ai_ceo.chat",
        title="AI CEO answer quality gate",
        input_data={"message": message},
    )
    report = repository.save_ai_ceo_market_research_report(task=task, message=message, chat=rejected_chat)
    assert report is None, "rejected answers must not be promoted into market reports or Listing handoffs"
    print("PASS jiejing_ai_ceo_answer_quality_gate")


if __name__ == "__main__":
    main()
