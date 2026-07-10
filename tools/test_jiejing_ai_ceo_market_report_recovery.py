#!/usr/bin/env python3
"""Regression test for AI CEO market-report recovery drafts.

When both the merchant model and live search are temporarily unavailable, an
eBay product-research request may be saved as a clearly marked work record, but
it must not invent a product or become importable into Listing.
"""

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
    AI_CEO_STATUS_MARKET_REPORT_RECOVERY_DRAFT,
    run_ai_ceo_chat,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-ai-ceo-market-report-recovery"
SAAS_DB = OUT / "recovery.sqlite"


class MinimalContextRepository:
    def get_store_for_company(self, *, company_id: str, store_id: str) -> dict[str, Any]:
        return {
            "store_id": store_id,
            "platform": "ebay",
            "store_name": "Recovery Test Store",
            "marketplace": "EBAY_US",
            "connection_status": "read_only",
        }

    def list_platform_data_packets(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_confirmations(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_tasks(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def list_reports(self, **_: Any) -> list[dict[str, Any]]:
        return []


class TimeoutModel:
    provider = "deepseek"
    model = "deepseek-v4-pro"
    endpoint = "https://api.deepseek.com"

    def generate_text(self, **_: Any) -> dict[str, Any]:
        raise TimeoutError("simulated model timeout")


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    previous_default_web = os.environ.get("JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED")
    os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED"] = "false"
    try:
        message = (
            "帮我找个小众品，市场有需求，适合 eBay 美国站，轻小件，不带电。"
            "请给我一份市场调研报告、候选商品名称、推荐度评分、风险和 Listing 草稿字段建议。"
        )
        chat = run_ai_ceo_chat(
            repository=MinimalContextRepository(),
            company_id="company_recovery",
            store_id="store_recovery",
            user_id="user_recovery",
            message=message,
            model_client=TimeoutModel(),
            model_resolution={
                "provider_key": "deepseek",
                "provider_label": "DeepSeek",
                "model": "deepseek-v4-pro",
                "endpoint_host": "api.deepseek.com",
            },
        )
    finally:
        if previous_default_web is None:
            os.environ.pop("JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED", None)
        else:
            os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED"] = previous_default_web

    assert chat["status"] == AI_CEO_STATUS_MARKET_REPORT_RECOVERY_DRAFT, chat
    assert chat["route"] == "ebay_workflow", chat
    assert chat["default_web_search"]["status"] == "not_requested", chat
    assert chat["source_records"] == [], chat
    assert chat["frontend_gets_model_api_key"] is False, chat
    assert chat["runtime_gets_raw_ebay_token"] is False, chat
    assert chat["secret_exposed"] is False, chat

    answer = chat["answer"]
    assert "AI CEO 市场调研待继续" in answer, answer
    assert "不会用固定样例补成商品" in answer, answer
    assert "系统不会把本记录标记为可导入 Listing" in answer, answer
    assert "硅胶水槽" not in answer and "驱蚊" not in answer, answer

    repository = SaaSRepository(SAAS_DB)
    task = repository.create_task(
        company_id="company_recovery",
        store_id="store_recovery",
        user_id="user_recovery",
        task_type="ai_ceo.chat",
        title="AI CEO 选品调研",
        input_data={"message": message},
    )
    saved = repository.save_ai_ceo_market_research_report(task=task, message=message, chat=chat)
    assert saved is not None, "recovery draft should be saved as ai_ceo.market_research"

    report = saved["report"]
    listing_handoff = report["listing_handoff"]
    assert report["source_record_count"] == 0, report
    memories = repository.list_merchant_memory(
        company_id="company_recovery",
        store_id="store_recovery",
        limit=5,
    )
    assert memories, "saved market report should also write merchant memory"
    assert "needs_more_sources" in memories[0]["tags"], memories
    assert listing_handoff["ready_for_listing_draft"] is False, listing_handoff
    assert listing_handoff["listing_fields"] == {}, listing_handoff
    assert listing_handoff["blocked_by"] == ["answer_quality_not_ready_for_listing"], listing_handoff
    assert listing_handoff["requires_human_review_before_publish"] is True, listing_handoff
    assert listing_handoff["triggers_real_platform_write"] is False, listing_handoff


if __name__ == "__main__":
    main()
