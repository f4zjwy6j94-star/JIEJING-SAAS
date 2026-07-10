#!/usr/bin/env python3
"""Regression checks for AI CEO complete answers and bounded conversation context."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import (  # noqa: E402
    AI_CEO_ROUTE_EBAY_WORKFLOW,
    _clean_answer,
    _complete_truncated_model_result,
    _realtime_answer_needs_repair,
    build_ai_ceo_chat_prompts,
)


class SequencedModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_text(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {"text": "第一部分已经完成，第二部分刚刚开始", "finish_reason": "length"}
        return {"text": "第二部分继续完成，并给出最终结论。", "finish_reason": "stop"}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    long_answer = "完整回答" * 1500
    if _clean_answer(long_answer) != long_answer:
        return fail("AI CEO must not silently cut a long answer at the old 2200-character boundary")

    model = SequencedModel()
    completed = _complete_truncated_model_result(
        model_client=model,
        result=model.generate_text(),
        system_prompt="system",
        user_prompt="user",
        route=AI_CEO_ROUTE_EBAY_WORKFLOW,
    )
    if completed.get("continuation_count") != 1 or "最终结论" not in str(completed.get("text") or ""):
        return fail(f"length-limited model output should be continued automatically: {completed}")
    if len(model.calls) != 2:
        return fail(f"one truncated response should require exactly one continuation call: {len(model.calls)}")

    sources = [{"title": "Market source", "url": "https://example.com/market"}]
    if not _realtime_answer_needs_repair("依据公开搜索到的信息，无法给出美", sources):
        return fail("a one-line realtime refusal with available sources must be repaired")
    if _realtime_answer_needs_repair("根据公开来源，当前可确认三项事实。主要驱动包括财报预期、行业价格与市场风险偏好；偏强和偏弱两种情景如下，并需留意来源时间。" * 2, sources):
        return fail("a substantive source-backed realtime analysis should pass the quality check")

    _system, prompt = build_ai_ceo_chat_prompts(
        message="第三个为什么显示一半？",
        context={},
        route=AI_CEO_ROUTE_EBAY_WORKFLOW,
        conversation_history=[
            {
                "user_text": "帮我选三个适合 eBay 的轻小件",
                "assistant_text": "候选商品 3：旅行收纳挂钩。",
                "route": "ebay_workflow",
            }
        ],
    )
    payload = json.loads(prompt)
    history = payload.get("recent_conversation") or []
    if not history or history[-1].get("assistant_text") != "候选商品 3：旅行收纳挂钩。":
        return fail(f"prompt should contain sanitized recent conversation: {payload}")
    print("PASS jiejing_ai_ceo_completion_helpers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
