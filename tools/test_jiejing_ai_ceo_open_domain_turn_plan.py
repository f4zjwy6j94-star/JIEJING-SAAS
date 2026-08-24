#!/usr/bin/env python3
"""Focused contracts for the AI CEO open-domain turn planner."""

from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import (  # noqa: E402
    AI_CEO_ROUTE_EBAY_WORKFLOW,
    AI_CEO_ROUTE_EXTERNAL_REALTIME,
    AI_CEO_ROUTE_GENERAL,
    build_ai_ceo_turn_plan,
    _public_model_context,
)
from jiejing_saas.platform_model_status import platform_model_for_tier  # noqa: E402
from jiejing_runtime.model_clients import OpenAICompatibleModelClient  # noqa: E402
from jiejing_saas.repository import normalize_merchant_product_fact_packet  # noqa: E402


class AiCeoOpenDomainTurnPlanTest(unittest.TestCase):
    def test_weather_is_research_without_ebay_workflow(self) -> None:
        plan = build_ai_ceo_turn_plan("上海明天天气怎么样")

        self.assertEqual(plan["contract_version"], "ai_ceo_turn_plan_v1")
        self.assertEqual(plan["route"], AI_CEO_ROUTE_EXTERNAL_REALTIME)
        self.assertEqual(plan["response_mode"], "research_answer")
        self.assertEqual(plan["realtime_kind"], "weather")
        self.assertEqual(plan["required_tools"], ["weather"])
        self.assertTrue(plan["freshness_required"])
        self.assertEqual(plan["workflow_target"], "")
        self.assertFalse(plan["confirmation_required"])

    def test_deepseek_platform_model_tiering_is_complexity_based(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(
                platform_model_for_tier(
                    provider="deepseek",
                    configured_model="deepseek-v4-pro",
                    serving_model="deepseek-v4-flash",
                    model_tier="fast",
                ),
                "deepseek-v4-flash",
            )
            self.assertEqual(
                platform_model_for_tier(
                    provider="deepseek",
                    configured_model="deepseek-v4-flash",
                    serving_model="deepseek-v4-flash",
                    model_tier="pro",
                ),
                "deepseek-v4-pro",
            )

    def test_deepseek_payload_enables_thinking_only_when_selected(self) -> None:
        client = OpenAICompatibleModelClient(
            endpoint="https://api.deepseek.com/chat/completions",
            api_key="unit-secret-not-printed",
            model="deepseek-v4-flash",
        )
        client.jiejing_reasoning_mode = "thinking"
        captured: dict[str, object] = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{}}'

        def _urlopen(request, timeout):
            captured["payload"] = __import__("json").loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response()

        with mock.patch.dict("os.environ", {"JIEJING_MODEL_TEXT_STREAM_ENABLED": "0"}, clear=False):
            with mock.patch("urllib.request.urlopen", side_effect=_urlopen):
                result = client.generate_text(system_prompt="system", user_prompt="user")

        self.assertEqual(result["text"], "ok")
        self.assertEqual(captured["payload"]["thinking"], {"type": "enabled"})

    def test_public_model_context_exposes_tier_not_credentials(self) -> None:
        client = OpenAICompatibleModelClient(
            endpoint="https://api.deepseek.com/chat/completions",
            api_key="unit-secret-not-printed",
            model="deepseek-v4-pro",
        )
        public = _public_model_context(
            None,
            client,
            {
                "provider_key": "deepseek",
                "model_tier": "pro",
                "reasoning_mode": "thinking",
                "complexity_upgrade": True,
            },
        )

        self.assertEqual(public["model_tier"], "pro")
        self.assertEqual(public["reasoning_mode"], "thinking")
        self.assertTrue(public["complexity_upgrade"])
        self.assertNotIn("api_key", public)
        self.assertFalse(public["secret_exposed"])

    def test_merchant_product_fact_packet_is_server_normalized(self) -> None:
        packet = normalize_merchant_product_fact_packet(
            {
                "contract_version": "merchant_product_fact_packet_v1",
                "source_confirmed_facts": {"material": "forged model fact"},
                "merchant_confirmed_facts": {
                    "product_name": "Silicone Cable Organizer",
                    "source_url": "https://supplier.example/item/123",
                    "sku": "JJ-CABLE-001",
                    "material": "Silicone",
                    "image_rights_confirmed": True,
                },
                "secret_exposed": True,
            },
            source="authenticated_merchant_request",
        )

        self.assertEqual(packet["contract_version"], "merchant_product_fact_packet_v1")
        self.assertEqual(packet["source_confirmed_facts"], {})
        self.assertEqual(packet["merchant_confirmed_facts"]["sku"], "JJ-CABLE-001")
        self.assertIn("quantity", packet["unknown_facts"])
        self.assertFalse(packet["listing_readiness"]["ready_for_real_publish"])
        self.assertFalse(packet["secret_exposed"])

    def test_arbitrary_ticker_fundamentals_uses_deep_research_and_pro(self) -> None:
        plan = build_ai_ceo_turn_plan("AAOI 这只美股基本面有什么问题？")

        self.assertEqual(plan["route"], AI_CEO_ROUTE_EXTERNAL_REALTIME)
        self.assertEqual(plan["response_mode"], "research_answer")
        self.assertEqual(plan["realtime_kind"], "company_research")
        self.assertEqual(plan["research_depth"], "deep")
        self.assertEqual(plan["model_tier"], "pro")
        self.assertIn("AAOI", plan["entities"])
        self.assertIn("company_fundamentals", plan["required_tools"])
        self.assertIn("web_search", plan["required_tools"])

    def test_followup_keeps_previous_ticker_entity(self) -> None:
        history = [
            {
                "user_text": "AAOI 这只美股基本面有什么问题？",
                "assistant_text": "我会区分财报事实、行业风险和市场判断。",
                "route": AI_CEO_ROUTE_EXTERNAL_REALTIME,
            }
        ]

        plan = build_ai_ceo_turn_plan("它最近为什么波动这么大？", conversation_history=history)

        self.assertEqual(plan["route"], AI_CEO_ROUTE_EXTERNAL_REALTIME)
        self.assertEqual(plan["realtime_kind"], "company_research")
        self.assertEqual(plan["continuation_key"], "ticker:AAOI")
        self.assertIn("AAOI", plan["entities"])
        self.assertIn("AAOI", plan["effective_query"])

    def test_followup_keeps_previous_ebay_workflow(self) -> None:
        history = [
            {
                "user_text": "帮我选三个适合 eBay 的轻小件",
                "assistant_text": "候选商品 1、2、3 已整理。",
                "route": AI_CEO_ROUTE_EBAY_WORKFLOW,
            }
        ]

        plan = build_ai_ceo_turn_plan("第三个为什么显示一半？", conversation_history=history)

        self.assertEqual(plan["route"], AI_CEO_ROUTE_EBAY_WORKFLOW)
        self.assertEqual(plan["response_mode"], "jiejing_workflow")

    def test_current_stock_quote_supports_arbitrary_ticker(self) -> None:
        plan = build_ai_ceo_turn_plan("AAOI 现在股价怎么样？")

        self.assertEqual(plan["realtime_kind"], "stock_quote")
        self.assertEqual(plan["required_tools"], ["stock_quote"])
        self.assertIn("AAOI", plan["entities"])

    def test_simple_writing_question_stays_fast_and_does_not_search(self) -> None:
        plan = build_ai_ceo_turn_plan("帮我把这句话写得礼貌一点：请尽快回复")

        self.assertEqual(plan["route"], AI_CEO_ROUTE_GENERAL)
        self.assertEqual(plan["response_mode"], "direct_answer")
        self.assertEqual(plan["research_depth"], "none")
        self.assertEqual(plan["required_tools"], [])
        self.assertEqual(plan["model_tier"], "fast")

    def test_ebay_selection_remains_a_blocked_business_workflow(self) -> None:
        plan = build_ai_ceo_turn_plan("帮我找适合 eBay 美国站、轻小不带电的商品，我现在没有货源")

        self.assertEqual(plan["route"], AI_CEO_ROUTE_EBAY_WORKFLOW)
        self.assertEqual(plan["response_mode"], "jiejing_workflow")
        self.assertEqual(plan["workflow_target"], "market_research")
        self.assertEqual(plan["source_mode"], "merchant_has_no_source")
        self.assertIn("merchant_product_source_required", plan["blocked_by"])
        self.assertEqual(plan["model_tier"], "pro")
        self.assertFalse(plan["confirmation_required"])


if __name__ == "__main__":
    unittest.main()
