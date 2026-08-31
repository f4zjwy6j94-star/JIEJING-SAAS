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
    _classify_external_realtime_request,
    _explicit_new_listing_project_request,
    _looks_like_product_selection_request,
    _looks_like_platform_rule_request,
    _model_answer_rejected_fallback,
    _selection_response_contract,
    _should_retry_initial_model_failure,
    _realtime_search_query,
    build_ai_ceo_chat_context,
    normalize_ai_ceo_active_listing_context,
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


class ReasoningExhaustedModel(SequenceModel):
    def generate_text(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "text": "",
            "model_mode": "live_http_model_text_stream",
            "model_client": "quality-gate-test",
            "model_configured": True,
            "model": self.model,
            "finish_reason": "length",
            "_usage": {"input_tokens": 16819, "output_tokens": 2400, "total_tokens": 19219},
        }


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

    incomplete_quality = validate_ai_ceo_answer_quality(
        message="继续当前复古黄铜书签模拟演练项目，不新建重复项目。",
        route="confirmation_required",
        answer="### 受控处理演练规格\n|",
        context={},
    )
    assert incomplete_quality["accepted"] is False, incomplete_quality
    assert incomplete_quality["quality_gate"] == "answer_completeness_v1", incomplete_quality
    assert "model_answer_truncated_table" in incomplete_quality["blocked_by"], incomplete_quality

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

    second_pass_message = (
        "第二遍真实闭环验收：继续当前禅意佛手托莲花倒流香炉项目，"
        "沿用现有 SKU JJ-INCENSE-JC2023041300002-01 和未发布 Offer 245675556011；"
        "重新核对 Listing 字段、素材和正式发布前预检，不要创建重复 Offer。"
    )
    second_pass_plan = __import__("jiejing_saas.ai_ceo_chat", fromlist=["build_ai_ceo_turn_plan"]).build_ai_ceo_turn_plan(
        second_pass_message
    )
    assert second_pass_plan["route"] == "ebay_workflow", second_pass_plan
    assert second_pass_plan["workflow_target"] in {"listing_draft", "ebay_operation"}, second_pass_plan
    assert "JJ" not in second_pass_plan["entities"], second_pass_plan

    active_listing_context = {
        "contract_version": "active_listing_context_v1",
        "source": "authenticated_current_listing_snapshot",
        "listing_project_identity": {
            "key": "incense-project",
            "source_report_id": "report-incense",
            "candidate_id": "candidate-incense",
        },
        "product_name": "禅意佛手托莲花倒流香炉",
        "listing": {
            "sku": "JJ-INCENSE-JC2023041300002-01",
            "title": "Zen Hand Lotus Backflow Incense Burner",
            "known_fact_keys": ["sku", "net_weight_g", "dimensions_cm"],
            "missing_fact_keys": ["package_weight_g", "selling_price"],
        },
        "media": {
            "asset_manifest_count": 1,
            "listing_eligible_asset_count": 1,
            "rights_confirmed_for_listing_draft": True,
            "product_fact_review_required_before_publish": True,
            "review_statuses": ["merchant_review_confirmed"],
        },
        "ebay_draft": {
            "offer_id": "245675556011",
            "sku": "JJ-INCENSE-JC2023041300002-01",
            "offer_status": "UNPUBLISHED",
            "public_listing_created": False,
        },
        "account_health": {"status": "restricted", "onboarding_stage": "account_review_required"},
        "secret_exposed": False,
    }
    normalized_active_listing = normalize_ai_ceo_active_listing_context(
        {
            **active_listing_context,
            "access_token": "MUST_NOT_LEAK",
            "listing": {
                **active_listing_context["listing"],
                "known_facts": {"material": "resin", "api_key": "MUST_NOT_LEAK"},
            },
            "ebay_draft": {**active_listing_context["ebay_draft"], "refresh_token": "MUST_NOT_LEAK"},
        }
    )
    assert normalized_active_listing["listing"]["known_facts"] == {"material": "resin"}, normalized_active_listing
    assert normalized_active_listing["media"]["rights_confirmed_for_listing_draft"] is True, normalized_active_listing
    assert normalized_active_listing["media"]["product_fact_review_required_before_publish"] is True, normalized_active_listing
    assert "MUST_NOT_LEAK" not in str(normalized_active_listing), normalized_active_listing
    second_pass_context = {**context, "active_listing_context": active_listing_context}
    contradictory_second_pass = (
        "第二遍检查完成。SKU 仍未指定，因此当前被 SKU 阻断。素材工坊尚未生成新图。"
        "eBay 草稿也还没有保存。"
    )
    contradictory_quality = validate_ai_ceo_answer_quality(
        message=second_pass_message,
        route="ebay_workflow",
        answer=contradictory_second_pass,
        context=second_pass_context,
    )
    assert contradictory_quality["accepted"] is False, contradictory_quality
    assert "existing_sku_reported_missing" in contradictory_quality["blocked_by"], contradictory_quality
    assert "existing_media_reported_missing" in contradictory_quality["blocked_by"], contradictory_quality
    assert "existing_unpublished_offer_reported_missing" in contradictory_quality["blocked_by"], contradictory_quality

    restored_media_contradiction = (
        "当前素材：未生成新的捷境商品图。现有 AssetManifest 中不含可发布的商品主图。"
    )
    restored_media_quality = validate_ai_ceo_answer_quality(
        message=second_pass_message,
        route="ebay_workflow",
        answer=restored_media_contradiction,
        context=second_pass_context,
    )
    assert restored_media_quality["accepted"] is False, restored_media_quality
    assert "existing_media_reported_missing" in restored_media_quality["blocked_by"], restored_media_quality

    contradictory_media_rights = (
        "现有 1 个素材符合 Listing 草稿要求，但图片发布权：阻断，图片商业使用权仍未确认。"
    )
    contradictory_media_rights_quality = validate_ai_ceo_answer_quality(
        message=second_pass_message,
        route="ebay_workflow",
        answer=contradictory_media_rights,
        context=second_pass_context,
    )
    assert contradictory_media_rights_quality["accepted"] is False, contradictory_media_rights_quality
    assert "existing_media_rights_reported_blocked" in contradictory_media_rights_quality["blocked_by"], contradictory_media_rights_quality

    accurate_second_pass = (
        "第二遍检查已读取当前项目：SKU JJ-INCENSE-JC2023041300002-01 已存在；"
        "AssetManifest 有 1 个可用于 Listing 草稿的已审核素材，图片使用权已确认，不是阻断项；"
        "商品事实和实物一致性仍需独立复核；"
        "Offer 245675556011 仍为 UNPUBLISHED。当前账号受限，先停在只读预检，不创建重复 Offer。"
    )
    accurate_quality = validate_ai_ceo_answer_quality(
        message=second_pass_message,
        route="ebay_workflow",
        answer=accurate_second_pass,
        context=second_pass_context,
    )
    assert accurate_quality["accepted"] is True, accurate_quality

    negated_missing_claims = (
        "SKU 不是缺失项；素材并非未生成；Offer 不是未保存，而是已处于 UNPUBLISHED 状态。"
    )
    negated_quality = validate_ai_ceo_answer_quality(
        message=second_pass_message,
        route="ebay_workflow",
        answer=negated_missing_claims,
        context=second_pass_context,
    )
    assert negated_quality["accepted"] is True, negated_quality

    stubborn_contradictory_model = SequenceModel([contradictory_second_pass, contradictory_second_pass])
    rejected_second_pass = run_ai_ceo_chat(
        repository=MinimalRepository(),
        company_id="company_quality",
        store_id="store_quality",
        user_id="user_quality",
        message=second_pass_message,
        model_client=stubborn_contradictory_model,
        active_listing_context=active_listing_context,
    )
    assert rejected_second_pass["status"] == "model_answered_with_context_correction", rejected_second_pass
    assert rejected_second_pass["blocked_by"] == [], rejected_second_pass
    assert rejected_second_pass["answer_quality"]["accepted"] is True, rejected_second_pass
    assert rejected_second_pass["answer_quality"]["context_correction_used"] is True, rejected_second_pass
    assert "existing_sku_reported_missing" in rejected_second_pass["answer_quality"]["model_answer_blocked_by"], rejected_second_pass
    assert "existing_unpublished_offer_reported_missing" in rejected_second_pass["answer_quality"]["model_answer_blocked_by"], rejected_second_pass
    assert "SKU JJ-INCENSE-JC2023041300002-01 已存在" in rejected_second_pass["answer"], rejected_second_pass
    assert "Offer 245675556011 已保存" in rejected_second_pass["answer"], rejected_second_pass
    assert "不会创建第二个 Offer" in rejected_second_pass["answer"], rejected_second_pass
    assert "Listing 草稿使用权已确认" in rejected_second_pass["answer"], rejected_second_pass
    assert rejected_second_pass["answer_quality"]["repair_retry_count"] == 1, rejected_second_pass

    new_project_message = (
        "请新建一个独立商品项目，不复用当前香炉项目。为本轮模拟演练创建新的内部 Listing 草稿，"
        "但不要保存 eBay 草稿、不要公开发布，也不要改动当前 Offer。"
    )
    new_project_answer = (
        "已创建独立模拟商品项目：无品牌便携缝纫线轴固定夹。"
        "新的捷境内部 Listing 草稿已生成；本项目的 SKU 尚未指定，素材尚未生成，图片使用权待补，"
        "eBay 草稿尚未创建，当前香炉项目和 Offer 保持不变。"
    )
    new_project_model = SequenceModel([new_project_answer, new_project_answer])
    isolated_new_project = run_ai_ceo_chat(
        repository=MinimalRepository(),
        company_id="company_quality",
        store_id="store_quality",
        user_id="user_quality",
        message=new_project_message,
        model_client=new_project_model,
        active_listing_context=active_listing_context,
    )
    assert isolated_new_project["status"] == "model_answered", isolated_new_project
    assert isolated_new_project["answer"] == new_project_answer, isolated_new_project
    assert isolated_new_project["answer_quality"]["accepted"] is True, isolated_new_project
    assert isolated_new_project["answer_quality"].get("context_correction_used") is not True, isolated_new_project
    assert _explicit_new_listing_project_request(new_project_message) is True
    assert _explicit_new_listing_project_request("请创建一个全新的 Listing 项目。") is True
    assert _explicit_new_listing_project_request("请另起一个独立商品项目。") is True
    assert _explicit_new_listing_project_request("请新建一个平板电脑支架的独立项目。") is True
    assert _explicit_new_listing_project_request("不要重复新建旧项目，请新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请新建一个商品项目，目标是平板电脑支架，并且独立于旧项目。") is True
    assert _explicit_new_listing_project_request("是否可以帮我新建一个全新的商品项目？") is True
    assert _explicit_new_listing_project_request("可以帮我新建商品项目吗？") is True
    assert _explicit_new_listing_project_request("能帮我新建一个全新商品项目吗？") is True
    assert _explicit_new_listing_project_request("麻烦帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我想新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请新建一个全新商品项目好吗？") is True
    assert _explicit_new_listing_project_request("你能帮我新建一个全新商品项目吗？") is True
    assert _explicit_new_listing_project_request("我想让你新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请你帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("帮忙新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我想让你帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我想请你帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请帮忙新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("麻烦你帮忙新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我希望你帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("给我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("麻烦给我创建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请协助我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请帮我重新创建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("帮我单独建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("新开一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("另开一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("帮我建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("那就新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("确认新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("立即创建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("开始新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("再帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请单独创建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请新增一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我想开一个新的 Listing 项目。") is True
    assert _explicit_new_listing_project_request("劳烦帮我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("请替我新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("我打算请执行新建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("另外建一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("帮我开一个全新商品项目。") is True
    assert _explicit_new_listing_project_request("继续当前项目，不得新建重复商品项目或 Offer。") is False
    assert _explicit_new_listing_project_request("继续当前项目，禁止创建全新 Listing 项目。") is False
    assert _explicit_new_listing_project_request("这个全新的商品项目已经创建好了，请继续完善 Listing。") is False
    assert _explicit_new_listing_project_request("确认刚才创建的全新商品项目，补充标题。") is False
    assert _explicit_new_listing_project_request("刚才新建的全新商品项目为什么没有显示？") is False
    assert _explicit_new_listing_project_request("为什么要新建一个全新商品项目？") is False
    assert _explicit_new_listing_project_request("我没有让你新建一个全新的商品项目。") is False
    assert _explicit_new_listing_project_request("不要把这句话理解成新建一个全新的商品项目。") is False
    assert _explicit_new_listing_project_request("我确认不是要新建一个全新的商品项目。") is False
    assert _explicit_new_listing_project_request("新建一个全新商品项目会覆盖旧草稿吗？") is False
    assert _explicit_new_listing_project_request("我想了解新建一个全新商品项目的流程。") is False
    assert _explicit_new_listing_project_request("新建一个全新商品项目有什么风险？") is False
    assert _explicit_new_listing_project_request("新建一个全新商品项目是不是已经完成了？") is False
    assert _explicit_new_listing_project_request("你新建一个全新商品项目了吗？") is False
    assert _explicit_new_listing_project_request("你帮我新建一个全新商品项目了吗？") is False
    assert _explicit_new_listing_project_request("你帮我新建一个全新商品项目了没有？") is False
    assert _explicit_new_listing_project_request("可以介绍一下新建商品项目的好处吗？") is False
    assert _explicit_new_listing_project_request("能讲讲新建商品项目和继续当前项目的区别吗？") is False
    assert _explicit_new_listing_project_request("新建商品项目适合什么场景？") is False
    assert _explicit_new_listing_project_request("新建商品项目需要什么资料？") is False
    assert _explicit_new_listing_project_request("新建商品项目要多少钱？") is False
    assert _explicit_new_listing_project_request("新建商品项目有哪些步骤？") is False
    assert _explicit_new_listing_project_request("新建商品项目的前提是什么？") is False
    assert _explicit_new_listing_project_request("新建商品项目需要什么资料") is False
    assert _explicit_new_listing_project_request("新建商品项目要多少钱") is False
    assert _explicit_new_listing_project_request("新建商品项目有哪些步骤") is False
    assert _explicit_new_listing_project_request("新建商品项目的前提是什么") is False
    assert _explicit_new_listing_project_request("新建商品项目需要什么资料，能告诉我吗？") is False
    assert _explicit_new_listing_project_request("可以新建一个全新商品项目，也可以继续旧项目，你判断。") is False
    for approval_message in (
        "我确定要创建一个全新商品项目",
        "我确认要新开一个全新商品项目",
        "按这个方案新建一个全新商品项目",
        "确认按上述方案新建一个全新商品项目",
        "我同意新建一个全新商品项目，开始吧",
        "批准创建一个全新商品项目",
        "确认执行：新建一个全新商品项目",
        "就按新建一个全新商品项目执行",
        "就按这个方案新建商品项目",
        "我同意，就按这个方案新建商品项目",
        "好，就按这个方案新建商品项目",
        "同意新建商品项目",
        "同意创建商品项目",
        "确定新建商品项目",
        "确定创建商品项目",
        "没问题，开始创建一个全新商品项目",
        "确认建一个全新商品项目",
        "确定开一个全新商品项目",
        "我同意建立一个全新商品项目",
        "再开一个全新商品项目",
        "开一个全新商品项目",
        "新起一个全新商品项目",
        "直接新开一个全新商品项目",
        "请另外开一个全新商品项目",
        "帮我单独开一个全新商品项目",
        "就这样创建一个全新商品项目",
    ):
        assert _explicit_new_listing_project_request(approval_message) is True, approval_message
    for consultation_message in (
        "新建商品项目收费吗",
        "新建商品项目在哪里操作",
        "新建商品项目多久能完成",
        "新建商品项目难不难",
        "新建商品项目值得吗",
        "新建商品项目是谁来审核",
        "新建商品项目何时生效",
        "新建商品项目需要准备资料吗",
        "新建商品项目能保留旧草稿吗",
        "客户问，能不能新建一个全新商品项目",
        "客户想问，能不能新建一个全新商品项目",
        "用户在问，能不能新建一个全新商品项目",
        "客户的问题是，能不能新建一个全新商品项目",
        "我想咨询，能不能新建一个全新商品项目",
        "我有个问题，能不能新建一个全新商品项目",
        "我想确认一下，能不能新建一个全新商品项目",
        "我问你，能不能新建一个全新商品项目",
        "想问一下，能不能新建一个全新商品项目",
        "例如，请新建一个全新商品项目",
        "比如，帮我新建一个全新商品项目",
        "例句，给我创建一个全新商品项目",
        "示例，请新增一个全新商品项目",
        "文案可以写，直接新开一个全新商品项目",
        "用户可能输入，请另外开一个全新商品项目",
        "旧项目不行的话，那就新建一个全新商品项目",
        "若旧项目不可用，请新建一个全新商品项目",
        "买家好奇，能不能新建一个全新商品项目",
        "我好奇，能不能新建一个全新商品项目",
        "我想请教，能不能新建一个全新商品项目",
        "请教一下，能不能新建一个全新商品项目",
        "我确认下，能不能新建一个全新商品项目",
        "我想核实，能不能新建一个全新商品项目",
        "我想知道，能不能新建一个全新商品项目",
        "老板让我转告，直接新建一个全新商品项目",
        "有人建议我，请新建一个全新商品项目",
        "举个例子，请新建一个全新商品项目",
        "比如说，帮我新建一个全新商品项目",
        "把提示文案改成：请新建一个全新商品项目",
        "假若旧项目不能用，请新建一个全新商品项目",
        "万一旧项目失败，直接新建一个全新商品项目",
        "前提是旧数据无法恢复，再新建一个全新商品项目",
        "直接新建一个全新商品项目或继续旧项目，任选一种",
    ):
        assert _explicit_new_listing_project_request(consultation_message) is False, consultation_message

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

    live_rehearsal_message = (
        "从零调研一个适合 eBay 的轻小、不带电、无品牌授权风险、非受限商品，"
        "排除旧手机壳、倒流香炉、竹制手机支架、复古青铜书签；"
        "给出市场判断、3 个候选、推荐 1 个及理由。"
    )
    live_rehearsal_contract = _selection_response_contract(
        message=live_rehearsal_message,
        route="ebay_workflow",
    )
    for excluded_name in ("旧手机壳", "倒流香炉", "竹制手机支架", "复古青铜书签"):
        assert excluded_name in live_rehearsal_contract["excluded_candidate_names"], live_rehearsal_contract
    semantically_reused_answer = (
        "### 候选商品卡\n"
        "候选商品 1：不锈钢咖啡量勺\n推荐度评分：72/100\n本轮结论：进入下一轮核验。\n"
        "候选商品 2：硅胶折叠旅行水杯\n推荐度评分：68/100\n本轮结论：进入下一轮核验。\n"
        "候选商品 3：黄铜书签套装\n推荐度评分：78/100\n本轮结论：推荐优先核验。\n"
        "最终推荐：黄铜书签套装。"
    )
    semantically_reused_quality = validate_ai_ceo_answer_quality(
        message=live_rehearsal_message,
        route="ebay_workflow",
        answer=semantically_reused_answer,
        context={**context, "selection_contract": live_rehearsal_contract},
    )
    assert semantically_reused_quality["accepted"] is False, semantically_reused_quality
    assert "excluded_previous_candidate_reused" in semantically_reused_quality["blocked_by"], semantically_reused_quality

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

    evidence_followup_message = (
        "继续现有市场调研 report_5eaf36a405de7331，只补 eBay US Sold & Completed 成交证据并做三选一结论。"
        "已核验真实 Item ID、价格和在售数量；部分结果含品牌或图片，只能作为需求可比证据。"
        "下一步进入供应商事实核验，不生成 Listing、不生图、不写 eBay。"
    )
    assert _looks_like_platform_rule_request(
        message=evidence_followup_message,
        route="ebay_workflow",
    ) is False, "market evidence follow-up must not be treated as a platform-rule answer merely because it mentions images"
    assert _looks_like_product_selection_request(
        message=evidence_followup_message,
        route="ebay_workflow",
    ) is False, "market evidence follow-up must update the existing report instead of regenerating candidate cards"
    evidence_followup_quality = validate_ai_ceo_answer_quality(
        message=evidence_followup_message,
        route="ebay_workflow",
        answer=(
            "相对赢家：竹制桌面手机支架。已售样本和在售竞争均高于另外两个候选；"
            "这只是商品方向证据，供应商、库存、材质、尺寸和图片权利仍待核验。"
        ),
        source_records=[
            {
                "citation_id": "S1",
                "title": "eBay sold results",
                "domain": "ebay.com",
                "url": "https://www.ebay.com/sch/i.html?_nkw=bamboo+phone+stand&LH_Sold=1&LH_Complete=1",
            }
        ],
    )
    assert evidence_followup_quality["accepted"] is True, evidence_followup_quality

    verified_evidence_followup = (
        "继续 report_5eaf36a405de7331，只处理已核验市场数据并做三选一："
        "竹制手机支架 Sold/Completed 16、在售67，样本 Item IDs 155898688458/298493684620/318495642696，"
        "中位价 RMB53.56；硅胶理线座 Sold 2、在售20；便签夹 Sold 0、在售4。"
        "相对赢家为竹制手机支架。请保存结论并进入真实供应商事实核验；"
        "不要重跑选品，不建 Listing、不生图、不写 eBay、不要求 OAuth。"
    )
    stale_candidate_card = (
        "### 候选商品卡\n"
        "候选商品 1：竹制桌面手机支架\n成交证据不足。\n"
        "候选商品 2：硅胶桌面线缆固定座\n成交证据不足。"
    )
    stale_evidence_quality = validate_ai_ceo_answer_quality(
        message=verified_evidence_followup,
        route="ebay_workflow",
        answer=stale_candidate_card,
    )
    assert stale_evidence_quality["accepted"] is False, stale_evidence_quality
    assert "missing_submitted_market_evidence" in stale_evidence_quality["blocked_by"], stale_evidence_quality

    grounded_evidence_quality = validate_ai_ceo_answer_quality(
        message=verified_evidence_followup,
        route="ebay_workflow",
        answer=(
            "### 市场成交证据结论\n"
            "相对赢家：竹制手机支架。人工核验样本 Item ID 155898688458；"
            "Sold/Completed 16、在售 67，中位价 RMB 53.56。"
            "这只是商品方向证据，不证明供应商、库存、材质、尺寸或图片权利。"
            "下一步进入真实供应商事实核验。"
        ),
    )
    assert grounded_evidence_quality["accepted"] is True, grounded_evidence_quality

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

    supplier_fact_message = (
        "继续候选商品的真实供应商事实核验。页面显示材质和尺寸；"
        "实时库存、最终报价、图片商用许可仍未得到供应商确认。"
        "本轮不采购、不付款、不建 Listing、不生图、不写 eBay。"
    )
    assert _classify_external_realtime_request(supplier_fact_message) == "", supplier_fact_message
    assert _classify_external_realtime_request("特斯拉现在的报价是多少？") == "stock_quote"

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

        incomplete_listing_model = SequenceModel(
            [
                "### 受控处理演练规格\n|",
                "已继续当前复古黄铜书签项目并更新内部 Listing；本轮未执行任何 eBay 写入。",
            ]
        )
        incomplete_listing_repaired = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=(
                "继续当前复古黄铜书签模拟演练项目，请更新当前内部 Listing；"
                "不得保存 eBay 草稿、公开发布或写入 eBay。"
            ),
            model_client=incomplete_listing_model,
        )
        assert incomplete_listing_repaired["status"] == "model_answered", incomplete_listing_repaired
        assert incomplete_listing_repaired["answer_quality"]["accepted"] is True, incomplete_listing_repaired
        assert incomplete_listing_repaired["answer_quality"]["repair_retry_count"] == 1, incomplete_listing_repaired
        assert incomplete_listing_model.calls == 2, incomplete_listing_model.calls

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

        evidence_projection_model = SequenceModel([stale_candidate_card, stale_candidate_card])
        evidence_projection = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=verified_evidence_followup,
            model_client=evidence_projection_model,
        )
        assert evidence_projection["status"] == "model_answered", evidence_projection
        assert evidence_projection["answer_quality"]["accepted"] is True, evidence_projection
        assert evidence_projection["answer_quality"]["contract_projection_used"] is True, evidence_projection
        assert "竹制手机支架" in evidence_projection["answer"], evidence_projection
        assert "155898688458" in evidence_projection["answer"], evidence_projection
        assert "真实供应商事实核验" in evidence_projection["answer"], evidence_projection
        assert "成交证据不足" not in evidence_projection["answer"], evidence_projection

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

        reasoning_exhausted_model = ReasoningExhaustedModel([""])
        reasoning_exhausted_fallback = SequenceModel([valid])
        reasoning_exhausted_fallback.model = "deepseek-v4-flash"
        reasoning_exhausted_model.jiejing_fallback_model_client = reasoning_exhausted_fallback
        reasoning_exhausted_recovered = run_ai_ceo_chat(
            repository=MinimalRepository(),
            company_id="company_quality",
            store_id="store_quality",
            user_id="user_quality",
            message=message,
            model_client=reasoning_exhausted_model,
        )
        assert reasoning_exhausted_recovered["status"] == "model_answered", reasoning_exhausted_recovered
        assert reasoning_exhausted_recovered["answer_quality"]["initial_retry_count"] == 1, reasoning_exhausted_recovered
        assert reasoning_exhausted_recovered["model_client"]["model"] == "deepseek-v4-flash", reasoning_exhausted_recovered
        assert reasoning_exhausted_model.calls == 1, reasoning_exhausted_model.calls
        assert reasoning_exhausted_fallback.calls == 1, reasoning_exhausted_fallback.calls

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
