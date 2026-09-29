#!/usr/bin/env python3
"""Product research must search products, not substitute research-tool articles."""
from __future__ import annotations

import os
import json
import gc
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas import ai_ceo_chat as chat
from jiejing_saas.repository import SaaSRepository


FOLLOWUP = (
    "继续当前“不锈钢厨房量勺/量杯套装”商品项目，不新建项目，不沿用旧商品。"
    "刚才三个来源都是选品工具介绍，不能支持候选商品的需求和价格结论。"
    "请在本项目里继续做候选级联网调研：用 stainless steel measuring spoons cups set、"
    "silicone kitchen spatula、stainless steel coffee teaspoons 这些具体英文商品词查找 eBay 美国站商品或已售结果。"
    "每个候选分别给出真正匹配的商品页面链接、可核对的美元价格、商品件数、页面或抓取日期；"
    "明确区分在售标价和已售成交，不能把在售标价当成交价。"
    "没有检索到可靠结果就明确写未验证，不要用工具介绍顶替商品证据。"
    "仍不编造供应商、材质规格、实际重量、成本、发货地、品牌授权或销量，不创建 Listing，不生图、不采购、不发布。"
)
PRODUCTS = (
    "stainless steel measuring spoons cups set",
    "silicone kitchen spatula",
    "stainless steel coffee teaspoons",
)


class FakeSearch:
    calls = []
    guide_only = False

    def provider_status(self, provider):
        return {"configured": True, "provider": provider, "secret_exposed": False}

    def probe(self, config):
        self.calls.append(config)
        product = next((p for p in PRODUCTS if p in config.query), "physical product")
        suffix = PRODUCTS.index(product) + 1 if product in PRODUCTS else 8
        results = [{"title": "Best eBay product research tools", "url": "https://example.org/research-tools",
                    "snippet": "A guide to finding demand and sold listings."}]
        if not self.guide_only:
            results += [{"title": product, "url": f"https://www.ebay.com/itm/12345678900{suffix}",
                         "snippet": f"{product}. US $12.99. Buy it now."}]
        return {"status": "ready", "provider": config.provider, "query": config.query, "results": results}


class ProductSearchEvidenceTests(unittest.TestCase):
    def setUp(self):
        FakeSearch.calls = []
        FakeSearch.guide_only = False
        chat._DEFAULT_WEB_CONTEXT_CACHE.clear()
        self.env = patch.dict(os.environ, {
            "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "true",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED": "true",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_CACHE_SECONDS": "180",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_NEGATIVE_CACHE_SECONDS": "45",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_TIMEOUT_SECONDS": "2",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_MAX_RESULTS": "5",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(chat._DEFAULT_WEB_CONTEXT_CACHE.clear)

    def search(self, message=FOLLOWUP):
        with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
            return chat._run_default_web_context_search(route="ebay_workflow", message=message)

    def test_exact_merchant_words_reach_search_instead_of_tool_query(self):
        result = self.search()
        queries = [call.query for call in FakeSearch.calls]
        self.assertEqual(3, len(queries), queries)
        for product in PRODUCTS:
            self.assertTrue(any(product in q for q in queries), queries)
        for query in queries:
            self.assertIn("site:ebay.com/itm/", query)
            self.assertNotIn("product research", query)
            self.assertNotIn("marketplace trends", query)
        self.assertEqual("ready", result["status"])

    def test_no_listing_boundary_is_not_a_listing_creation_request(self):
        self.assertFalse(chat._looks_like_explicit_listing_intake(FOLLOWUP))
        for message in ("候选商品只做调研，不创建 Listing。", "只比较候选，不生成 Listing 草稿。", "不要创建 Listing，先选品。"):
            self.assertFalse(chat._looks_like_explicit_listing_intake(message), message)
        self.assertTrue(chat._looks_like_explicit_listing_intake("生成 Listing 草稿，不公开发布。"))
        plan = chat.build_ai_ceo_turn_plan(FOLLOWUP)
        self.assertEqual("market_research", plan["workflow_target"])
        self.assertEqual("", plan["realtime_kind"])

    def test_real_chat_passes_candidate_evidence_to_same_model_without_extra_model_call(self):
        class Model:
            provider = "deepseek"
            model = "deepseek-v4-pro"
            endpoint = "https://api.deepseek.com/v1/chat/completions"
            calls = []

            def generate_text(self, **kwargs):
                self.calls.append(json.loads(kwargs["user_prompt"]))
                return {"text": "\n".join(
                    f"候选商品 {i}：{name}\n推荐依据：商品页面中可见 US $12.99 标价 [S{i}]，不是成交价。\n"
                    "主要风险：规格、净重、成本、图片权利待供应商提供，销量和退货率未验证。"
                    for i, name in enumerate(PRODUCTS, 1)
                ), "model_mode": "live_http_model_text", "model_configured": True, "model": self.model}

        with tempfile.TemporaryDirectory(prefix="jiejing-product-search-test-") as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="product-search@example.test",
                password="unit-test-only-password", company_name="Offline search fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                    message=FOLLOWUP, model_client=model)
            self.assertEqual(1, len(model.calls))
            self.assertEqual(3, len(FakeSearch.calls))
            self.assertEqual("model_answered", result["status"])
            web = model.calls[0]["web_context"]
            self.assertEqual(3, len(web["source_records"]))
            self.assertEqual("not_established", web["product_research_evidence"]["sales_verification"])
            self.assertFalse(web["product_research_evidence"]["merchant_product_facts_confirmed"])
            del repo
            gc.collect()

    def test_terms_after_260_characters_are_not_lost(self):
        message = "先做候选商品市场调研。" + "要求来源清楚、不编造商品事实。" * 22 + "关键词：felt chair pads。"
        query = chat._realtime_search_query(kind="web_search", message=message)
        self.assertIn("felt chair pads", query)

    def test_no_source_discovery_searches_physical_listings_not_research_tools(self):
        query = chat._realtime_search_query(kind="web_search", message="无货源，帮我选品，eBay美国站轻小不带电，比较3个候选。")
        self.assertIn("site:ebay.com/itm/", query)
        self.assertIn("lightweight", query)
        self.assertIn("non-electric", query)
        self.assertNotIn("product research", query)
        self.assertNotIn("marketplace trends", query)

    def test_guide_results_do_not_count_as_product_evidence(self):
        FakeSearch.guide_only = True
        result = self.search()
        self.assertEqual("blocked", result["status"])
        self.assertIn("candidate_product_sources_missing", result["blocked_by"])
        self.assertFalse(result["used_for_model_prompt"])
        self.assertEqual([], result["source_records"])

    def test_product_sources_are_balanced_deduped_and_not_sales_proof(self):
        result = self.search()
        records = result["source_records"]
        self.assertEqual(3, len(records), records)
        self.assertEqual(["S1", "S2", "S3"], [r["citation_id"] for r in records])
        for record in records:
            self.assertEqual("item_listing_reference", record["market_evidence_role"])
            self.assertFalse(record["verified_transaction"])
        evidence = result["product_research_evidence"]
        self.assertEqual(3, evidence["search_query_count"])
        self.assertEqual("not_established", evidence["sales_verification"])
        self.assertFalse(evidence["merchant_product_facts_confirmed"])
        prompt = chat._prompt_web_context({"default_web_search": result})
        self.assertEqual(evidence, prompt["product_research_evidence"])

    def test_search_results_and_spoofed_hosts_are_not_item_evidence(self):
        snapshot = {"status": "ready", "provider": "test", "source_records": [
            {"title": "spoons", "url": "https://ebay.com.attacker.example/itm/123456789001", "domain": "ebay.com"},
            {"title": "spoons search", "url": "https://www.ebay.com/sch/i.html?_nkw=spoons"},
            {"title": "official help", "url": "https://www.ebay.com/help/selling"},
        ]}
        with patch.object(chat, "_run_realtime_search", return_value=snapshot):
            result = chat._run_default_web_context_search(route="ebay_workflow", message=FOLLOWUP)
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["source_records"])

    def test_unrelated_real_ebay_item_cannot_fill_candidate_evidence(self):
        snapshot = {"status": "ready", "source_records": [{
            "title": "Tablet computer stand", "url": "https://www.ebay.com/itm/123456789777",
            "snippet": "Adjustable tablet stand, US $9.99.",
        }]}
        with patch.object(chat, "_run_realtime_search", return_value=snapshot):
            result = chat._run_default_web_context_search(route="ebay_workflow", message=FOLLOWUP)
        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["source_records"])

    def test_one_search_timeout_does_not_erase_other_candidate_sources(self):
        original = chat._run_realtime_search
        def partial(**kwargs):
            if PRODUCTS[1] in kwargs["query_override"]:
                raise TimeoutError("private transport diagnostic must not escape")
            return original(**kwargs)
        with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch), patch.object(chat, "_run_realtime_search", side_effect=partial):
            result = chat._run_default_web_context_search(route="ebay_workflow", message=FOLLOWUP)
        self.assertEqual(2, len(result["source_records"]))
        self.assertNotIn("private transport", str(result))
        self.assertEqual(1, result["product_research_evidence"]["failed_query_count"])

    def test_late_product_names_do_not_share_a_truncated_cache_key(self):
        prefix = "候选调研：" + "只做市场研究、不要编商品事实。" * 35
        a = chat._default_web_context_cache_key(route="ebay_workflow", message=prefix + "felt chair pads")
        b = chat._default_web_context_cache_key(route="ebay_workflow", message=prefix + "wooden napkin rings")
        self.assertNotEqual(a, b)

    def test_repeated_request_reuses_cache_and_never_searches_more_than_three(self):
        first = self.search()
        second = self.search()
        self.assertEqual(3, len(FakeSearch.calls))
        self.assertEqual("hit", second["cache_status"])
        self.assertEqual(first["source_records"], second["source_records"])
        extra = FOLLOWUP + "其他候选：felt chair pads、magnetic cable clips、wooden napkin rings。"
        self.search(extra)
        self.assertLessEqual(len(FakeSearch.calls), 6)

    def test_disabled_search_does_not_resolve_provider_or_send_queries(self):
        with patch.dict(os.environ, {"JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "false"}):
            result = self.search()
        self.assertEqual("not_requested", result["status"])
        self.assertEqual([], FakeSearch.calls)

    def test_chinese_named_candidate_and_english_request_retain_product(self):
        for message, phrase in (
            ("继续候选商品调研，商品名称：羊毛毡椅脚垫。查eBay美国站商品标价。", "羊毛毡椅脚垫"),
            ('Compare product ideas: "felt chair pads" and "wooden napkin rings" on eBay US.', "felt chair pads"),
        ):
            query = chat._realtime_search_query(kind="web_search", message=message)
            self.assertIn(phrase, query)

    def test_positive_search_after_negative_clause_is_not_discarded(self):
        query = chat._realtime_search_query(kind="web_search", message="继续候选调研，不要复用旧书签，请查 felt chair pads。")
        self.assertIn("felt chair pads", query)
        self.assertNotIn("书签", query)


if __name__ == "__main__":
    unittest.main()
