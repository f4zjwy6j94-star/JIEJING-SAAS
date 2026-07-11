#!/usr/bin/env python3
"""Regression test for AI CEO multi-candidate market report selection."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-ai-ceo-market-candidate-selection"
SAAS_DB = OUT / "candidate-selection.sqlite"


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    repository = SaaSRepository(SAAS_DB)
    task = repository.create_task(
        company_id="company_candidate_selection",
        store_id="store_candidate_selection",
        user_id="user_candidate_selection",
        task_type="ai_ceo.chat",
        title="AI CEO 多候选选品调研",
        input_data={"message": "请给出三个候选并选出最值得测试的商品。"},
    )
    answer = """
### 候选商品卡
候选商品 1：冰箱食品收纳整理架（Fridge Organizer Bin with Dividers）
- 推荐度评分：63/100
- 为什么有需求：家庭冰箱空间整理需求稳定。
- Listing 草稿字段建议：价格 $12.99-$16.99，重量约 250g。

候选商品 2：多功能抽屉分隔板（Adjustable Drawer Dividers）
- 推荐度评分：65/100
- 为什么有需求：租房和儿童家庭有持续整理需求。
- Listing 草稿字段建议：价格 $9.99-$13.99，重量约 220g。

候选商品 3：厨房水槽海绵沥水收纳架（Over-Sink Sponge Holder）
- 推荐度评分：61/100
- 为什么有需求：厨房水槽收纳是高频痛点。
- Listing 草稿字段建议：价格 $7.99-$11.99，重量约 150g。

### 选品确认与推荐
### 最值得测试：多功能抽屉分隔板（Adjustable Drawer Dividers）
综合需求稳定性和差异化空间，建议先小批量测试这个商品。
""".strip()
    saved = repository.save_ai_ceo_market_research_report(
        task=task,
        message="请给出三个候选并选出最值得测试的商品。",
        chat={
            "answer": answer,
            "route": "ebay_workflow",
            "status": "model_answered",
            "source_records": [{"title": "Public market source", "url": "https://example.com/source"}],
        },
    )

    assert saved is not None, "multi-candidate market report should be saved"
    report = saved["report"]
    expected = "多功能抽屉分隔板（Adjustable Drawer Dividers）"
    assert report["product"] == expected, report
    assert report["selected_product_candidate"]["name"] == expected, report
    assert report["selected_product_candidate"]["score"] == 65, report
    candidates = report["product_candidates"]
    assert [item["selected"] for item in candidates] == [False, True, False], candidates

    fields = report["listing_handoff"]["listing_fields"]
    assert fields["title"] == expected, fields
    assert fields["product"] == expected, fields
    assert fields["selected_product_candidate"]["name"] == expected, fields
    assert fields["recommendation_score"] == 65, fields
    assert fields["price_band"] == "$9.99-$13.99", fields
    assert fields["logistics_requirements"]["package_weight_g"] == "220", fields
    assert fields["description_seed"] == "", fields
    assert fields["market_rationale"], fields
    assert "冰箱食品收纳整理架" not in fields["title"], fields
    assert fields["triggers_real_platform_write"] is False, fields

    followup_task = repository.create_task(
        company_id="company_candidate_selection",
        store_id="store_candidate_selection",
        user_id="user_candidate_selection",
        task_type="ai_ceo.chat",
        title="AI CEO 候选商品连续追问",
        input_data={"message": "第二个有市场吗？继续整理成 Listing 草稿。"},
    )
    followup = repository.save_ai_ceo_market_research_report(
        task=followup_task,
        message="第二个有市场吗？继续整理成 Listing 草稿。",
        chat={
            "answer": "这个品有持续的家庭收纳需求，建议先做小批量验证；价格、图片、尺寸和店铺政策仍需补齐。",
            "route": "ebay_workflow",
            "status": "model_answered",
            "source_records": [{"title": "Follow-up market source", "url": "https://example.com/follow-up"}],
        },
        conversation_history=[
            {
                "user_text": "请给出三个候选并选出最值得测试的商品。",
                "assistant_text": answer,
                "route": "ebay_workflow",
            }
        ],
    )
    assert followup is not None, "contextual product follow-up should save a structured report"
    followup_report = followup["report"]
    assert followup_report["product"] == expected, followup_report
    assert followup_report["selected_product_candidate"]["candidate_id"] == "candidate_2", followup_report
    assert followup_report["conversation_context"]["selection_mode"] == "history_candidate_index", followup_report
    followup_fields = followup_report["listing_handoff"]["listing_fields"]
    assert followup_fields["title"] == expected, followup_fields
    assert followup_fields["selected_candidate_id"] == "candidate_2", followup_fields
    assert followup_fields["price_band"] == "$9.99-$13.99", followup_fields
    assert followup_fields["description_seed"] == "", followup_fields
    assert "冰箱食品收纳整理架" not in " ".join(followup_fields["market_rationale"]), followup_fields
    assert followup_fields["triggers_real_platform_write"] is False, followup_fields

    reset_task = repository.create_task(
        company_id="company_candidate_selection",
        store_id="store_candidate_selection",
        user_id="user_candidate_selection",
        task_type="ai_ceo.chat",
        title="AI CEO 更换候选商品",
        input_data={"message": "换一个商品，这个不合适，重新做市场调研。"},
    )
    reset_without_new_product = repository.save_ai_ceo_market_research_report(
        task=reset_task,
        message="换一个商品，这个不合适，重新做市场调研。",
        chat={
            "answer": "好的，我会重新筛选市场方向；在形成具体候选商品前，不沿用刚才的商品。",
            "route": "ebay_workflow",
            "status": "model_answered",
        },
        conversation_history=[
            {
                "user_text": "请给出三个候选并选出最值得测试的商品。",
                "assistant_text": answer,
                "route": "ebay_workflow",
            }
        ],
    )
    assert reset_without_new_product is None, "a replacement request without a new concrete product must not save a stale report"


if __name__ == "__main__":
    main()
