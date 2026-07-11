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
    _model_answer_rejected_fallback,
    _should_retry_initial_model_failure,
    _realtime_search_query,
    run_ai_ceo_chat,
    validate_ai_ceo_answer_quality,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-ai-ceo-answer-quality-gate"


class MinimalRepository:
    def get_store_for_company(self, **_: Any) -> dict[str, Any]:
        return {"platform": "ebay", "store_name": "Quality Gate Store", "marketplace": "EBAY_US"}

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

    def generate_text(self, **_: Any) -> dict[str, Any]:
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
