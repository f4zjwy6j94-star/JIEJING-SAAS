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

# Redacted merchant-visible production failure: products were table columns,
# not rows. Keep this format (including bare S# references) in the real path.
TRANSPOSED_ANSWER = """## 候选商品比较表

| 维度 | 不锈钢量勺量杯套装 | 硅胶锅铲 | 不锈钢咖啡勺 |
|---|---|---|---|
| 来源编号 | S1、S4 | S2、S5 | S3 |
| 来源状态 | S1 在售参考、S4 在售参考 | S2 已结束（卖家因 listing 错误下架）、S5 在售参考 | S3 在售参考（二手） |
| 品牌归属 | S4 为 Chef Select（有品牌，不可写无品牌） | S5 为 Soli；S2 未验证 | S3 为 Reed & Barton（有品牌） |
| 主价 | 未验证（S1/S4 片段含多商品多价格） | 未验证（S2 已结束，S5 未显示明确主价） | 未验证（S3 多价格，不能认作主价） |
| 成交证据 | 不足 | 不足 | 不足 |
| 销量推断 | 不推断 | 不推断 | 不推断 |
| 商品事实 | 材质、重量、尺寸、成本、发货地、图片授权均未知 | 同左 | 同左 |
| 主要风险 | 竞品多、需区分套装规格 | S2 已结束，不能作为在售依据 | 二手/品牌件，与轻小件新品定位可能不符 |

## 暂定找货建议

优先找 **不锈钢量勺量杯套装**，理由：来源记录相对完整（S1、S4 两条在售参考），且更贴近轻小件、不带电、非液体粉末的默认方向。但这是暂定方向，不是已证实需求。

## 供应商资料清单（待补）

- 供应商名称与资质
- 材质规格（是否为 18/8 不锈钢）
- 套装件数与单件尺寸
- 单品净重、包装重量与包装尺寸
- 采购成本与最小起订量
- 发货地与实际履约方案
- 图片授权证明
- 品牌/MPN 信息（确认是否自有品牌或无品牌，不能凭竞品推断）

## 边界确认

本轮不新建项目、不创建 Listing、不生图、不采购、不发布。竞品信息仅作市场参考，不构成你的商品事实；所有商品参数仍为待核状态。"""


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
        for message in ("候选商品只做调研，不创建 Listing。", "只比较候选，不生成 Listing 草稿。", "不要创建 Listing，先选品。",
                        "只做候选调研，不需要生成 Listing。", "无须创建 Listing。", "不必创建 Listing。",
                        "先不要重新生成 Listing，继续核对候选。", "不允许生成 Listing 草稿。"):
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
            self.assertEqual("not_established", web["product_research_evidence"].get("current_availability_verification"))
            self.assertFalse(web["product_research_evidence"]["merchant_product_facts_confirmed"])
            del repo
            gc.collect()

    def test_failed_sourced_comparison_cannot_pass_as_generic_candidate_cards(self):
        bad_answer = "\n\n".join(
            f"候选商品 {i}：{name}\n竞品参考 [S99]。供应商资料与成交证据未验证。"
            for i, name in enumerate(PRODUCTS, 1))

        class Model:
            provider, model, calls = "deepseek", "offline-failed-research", 0
            def generate_text(self, **kwargs):
                self.calls += 1
                return {"text": bad_answer, "model_mode": "live_http_model_text",
                        "model_configured": True, "bounded_empty_answer_recovery": True}

        with tempfile.TemporaryDirectory(prefix="jiejing-research-fallback-", ignore_cleanup_errors=True) as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="research-fallback@example.test",
                password="unit-test-only-password", company_name="Research fallback fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                    message="比较3个候选商品：" + "、".join(PRODUCTS) + "。用商品来源给比较依据，不创建 Listing。",
                    model_client=model)
            self.assertEqual(1, model.calls)
            self.assertEqual(3, len(result["source_records"]))
            self.assertEqual("model_answer_rejected", result["status"],
                             "A failed comparison must not be relabelled successful after deleting all evidence")
            self.assertFalse(result["answer_quality"]["accepted"])
            self.assertFalse(result["answer_quality"].get("contract_projection_used"))
            self.assertIn("research_citation_not_in_evidence", result["answer_quality"]["blocked_by"])
            self.assertNotIn("### 候选商品卡", result["answer"])
            del repo
            gc.collect()

    def test_terms_after_260_characters_are_not_lost(self):
        message = "先做候选商品市场调研。" + "要求来源清楚、不编造商品事实。" * 22 + "关键词：felt chair pads。"
        query = chat._realtime_search_query(kind="web_search", message=message)
        self.assertIn("felt chair pads", query)

    def test_candidate_evidence_table_survives_chat_validation_and_report_save(self):
        message = (
            "继续当前商品项目，不新建项目。本轮只做候选级联网调研，请分别用 "
            + "、".join(PRODUCTS)
            + " 搜索 eBay 美国站的具体商品页面。每个候选给出匹配的商品标题、链接、可核对的美元标价、"
            "套装件数和检索日期，精简表格呈现。只写来源明确显示的内容，缺失项标为未验证；"
            "在售标价不等于成交价，抓取时间不等于交易日期，不能编造销量、退货率或需求稳定结论。"
            "根据实际证据比较并推荐一个暂定找货方向。不创建 Listing，不生图、不采购、不发布。"
        )
        answer = (
            "### 候选级 eBay 美国站调研结果\n\n检索日期：2026-09-29（抓取时间，非成交日期）\n\n"
            "| 候选 | 匹配商品标题 | 链接 | 可核对美元标价 | 套装件数 | 检索日期 |\n"
            "|---|---|---|---|---|---|\n"
            + "\n".join(
                f"| {name} | {name} | https://www.ebay.com/itm/12345678900{i} | US $12.99 [S{i}] | 未验证 | 2026-09-29 |"
                for i, name in enumerate(PRODUCTS, 1)
            )
            + "\n\n### 证据边界说明\n在售标价不等于成交价；销量和退货率未验证。\n\n"
            "### 暂定找货方向（建议）\n建议优先找货：stainless steel measuring spoons cups set。"
            "这是暂定建议，商品规格、材质、成本、重量和实际发货地待供应商提供。"
        )
        class Model:
            provider = "deepseek"
            model = "deepseek-v4-pro"
            endpoint = "https://api.deepseek.com/v1/chat/completions"
            calls = 0

            def generate_text(self, **kwargs):
                self.calls += 1
                return {"text": answer, "model_mode": "live_http_model_text", "model_configured": True, "model": self.model}

        with tempfile.TemporaryDirectory(prefix="jiejing-product-table-test-") as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="product-table@example.test",
                password="unit-test-only-password", company_name="Offline table fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                    message=message, model_client=model)
            self.assertEqual("model_answered", result["status"], result.get("answer_quality"))
            self.assertEqual(answer, result["answer"], result.get("answer_quality"))
            self.assertEqual(1, model.calls, "A valid evidence table must not trigger a paid repair call")
            task = repo.create_task(**identity, store_id=store["store_id"], task_type="merchant_ceo_chat",
                title="Candidate table fixture", input_data={"message": message})
            report = repo.save_ai_ceo_market_research_report(task=task, message=message, chat=result)
            self.assertIsNotNone(report)
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn('"name": "证据边界说明"', serialized)
            for name in PRODUCTS:
                self.assertIn(f'"name": "{name}"', serialized)
            del repo
            gc.collect()

    def test_recommendation_summary_does_not_hide_other_table_candidates(self):
        message = "当前项目只做候选级联网调研，比较3个候选：" + "、".join(PRODUCTS) + "。每个候选最多保留2个来源，最终推荐1个找货方向。不创建 Listing。"
        answer = (
            "| 候选 | 商品标题 | 链接 | 标价 |\n|---|---|---|---|\n"
            + "\n".join(
                f"| {name} | {name} | https://www.ebay.com/itm/12345678900{i} | US $12.99 [S{i}] |"
                for i, name in enumerate(PRODUCTS, 1)
            )
            + f"\n\n推荐产品：{PRODUCTS[0]}\n"
            "以上是竞品在售标价，不是成交证据。销量和品牌未验证；供应商、实物规格、重量、成本、发货地及图片权利未知。"
        )

        class Model:
            provider, model = "deepseek", "offline-candidate-table"
            calls = 0

            def generate_text(self, **kwargs):
                self.calls += 1
                return {"text": answer, "model_mode": "live_http_model_text", "model_configured": True}

        with tempfile.TemporaryDirectory(prefix="jiejing-mixed-table-", ignore_cleanup_errors=True) as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="mixed-table@example.test",
                password="unit-test-only-password", company_name="Offline mixed table")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                    message=message, model_client=model)
            self.assertEqual("model_answered", result["status"], result.get("answer_quality"))
            self.assertEqual(1, model.calls, "A recommendation summary must not cause paid retries of a complete table")
            self.assertEqual(3, result["answer_quality"]["candidate_count"])
            task = repo.create_task(**identity, store_id=store["store_id"], task_type="merchant_ceo_chat",
                title="Mixed table fixture", input_data={"message": message})
            saved = repo.save_ai_ceo_market_research_report(task=task, message=message, chat=result)
            self.assertEqual(set(PRODUCTS), {item["name"] for item in saved["report"]["product_candidates"]})
            self.assertEqual(PRODUCTS[0], saved["report"]["selected_product_candidate"]["name"])
            del repo
            gc.collect()

    def test_candidate_count_is_not_source_limit_or_final_recommendation_count(self):
        comparison = "、".join(PRODUCTS)
        cases = (
            (f"只做候选级联网调研，比较 {comparison}。每个候选最多保留2个来源，推荐一个暂定找货方向。不创建 Listing。", 3),
            ("每个候选给2个链接，比较3个候选商品，最终推荐1个找货方向。", 3),
            ("比较3个原候选商品：量勺量杯套装、硅胶锅铲、不锈钢咖啡勺。", 3),
            ("比较三个原有的候选商品，每个保留2个来源。", 3),
            ("对比3个现有候选商品，最后推荐一个。", 3),
            ("比较三个轻小不带电商品，每个提供两个来源，最终推荐一个方向。", 3),
            ("调研四个候选商品，每个保留1个链接。", 4),
            ("推荐一款具体商品，给出3个来源。", 1),
            ("先给我两个候选商品，不要生成 Listing。", 2),
        )
        answer = "\n".join(f"候选商品 {i}：{name}\n品牌、销量与供应商事实未知。" for i, name in enumerate(PRODUCTS, 1))
        for message, count in cases:
            with self.subTest(message=message):
                result = chat.validate_ai_ceo_answer_quality(message="本轮选品调研。" + message, route="ebay_workflow", answer=answer)
                self.assertEqual(count, result["required_candidate_count"])
                if count > len(PRODUCTS):
                    self.assertFalse(result["accepted"], "A genuinely missing candidate must remain blocked")

    def test_comparison_heading_is_not_one_product_or_a_complete_comparison(self):
        from jiejing_saas.repository import _ai_ceo_market_product_candidates
        answer = ("候选商品 1：量勺量杯套装 vs 硅胶锅铲 vs 不锈钢咖啡勺\n证据待核实。\n"
                  "候选商品 2：不锈钢量勺量杯套装\n供应商事实未知。")
        message = "沿用这5条来源，不联网。比较3个原候选商品：量勺量杯套装、硅胶锅铲、不锈钢咖啡勺。"
        candidates = _ai_ceo_market_product_candidates(message=message, answer=answer)
        self.assertEqual(["不锈钢量勺量杯套装"], [c["name"] for c in candidates])
        quality = chat.validate_ai_ceo_answer_quality(message=message, route="ebay_workflow", answer=answer)
        self.assertEqual(3, quality["required_candidate_count"])
        self.assertFalse(quality["accepted"], quality)

    def test_no_source_discovery_searches_physical_listings_not_research_tools(self):
        query = chat._realtime_search_query(kind="web_search", message="无货源，帮我选品，eBay美国站轻小不带电，比较3个候选。")
        self.assertIn("site:ebay.com/itm/", query)
        self.assertIn("lightweight", query)
        self.assertIn("non-electric", query)
        self.assertNotIn("product research", query)
        self.assertNotIn("marketplace trends", query)

    def test_revision_uses_owned_report_sources_without_searching_again(self):
        message = (
            "修订当前商品调研报告，本轮不要联网检索，沿用上一份报告来源。"
            "没有明确日期就写未验证，不要填写今天日期。价格和品牌未验证，不创建 Listing。"
        )
        answer = "候选商品 1：stainless steel measuring spoons cups set\n[S1] 只能证明存在该商品页面；价格、品牌、销量和供应商资料未验证。"
        class Model:
            provider, model = "deepseek", "test-model"
            calls = []
            def generate_text(self, **kwargs):
                self.calls.append(json.loads(kwargs["user_prompt"]))
                if kwargs.get("on_text_delta"):
                    kwargs["on_text_delta"]("尚未核对的价格片段")
                return {"text": answer, "model_mode": "live_http_model_text", "model_configured": True}
        with tempfile.TemporaryDirectory(prefix="jiejing-source-revision-", ignore_cleanup_errors=True) as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="revision@example.test", password="unit-test-only-password", company_name="Revision fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            project = {"key": "listing-project-revision", "source_report_id": "seed", "candidate_id": "candidate-1"}
            sources = [{"citation_id": "S1", "title": PRODUCTS[0], "url": "https://www.ebay.com/itm/123456789001", "snippet": "Price not verified.", "captured_at": "2026-09-29T10:00:00Z"}]
            task = repo.create_task(**identity, store_id=store["store_id"], task_type="merchant_ceo_chat", title="Prior report", input_data={"message": "调研候选"})
            report = repo.save_ai_ceo_market_research_report(task=task, message="调研1个候选商品", chat={"answer": answer, "route": "ebay_workflow", "status": "model_answered", "source_records": sources}, listing_project_identity=project)
            history = [{"user_text": "调研1个候选商品", "assistant_text": answer, "route": "ebay_workflow", "market_report_id": report["report_id"]}]
            model = Model()
            streamed = []
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"], message=message, model_client=model,
                    conversation_history=history, on_text_delta=streamed.append, active_listing_context={"contract_version": "active_listing_context_v1", "listing_project_identity": project})
            self.assertEqual([], streamed, "Evidence must be checked before sending model prose to the merchant")
            self.assertEqual([], FakeSearch.calls, "An explicit no-search revision must never call a search provider")
            self.assertNotEqual("local_clock_answered", result["status"], "Date constraints are part of the report task, not a clock question")
            self.assertEqual([sources[0]["url"]], [s["url"] for s in result["source_records"]])
            self.assertEqual("S1", model.calls[0]["web_context"]["source_records"][0]["citation_id"])
            self.assertEqual("not_established", model.calls[0]["web_context"]["product_research_evidence"].get("current_availability_verification"))
            self.assertEqual(sources[0]["captured_at"], result["source_records"][0]["captured_at"])
            self.assertEqual("model_answered", result["status"], result.get("answer_quality"))
            # A client cannot replace the retained evidence with raw snippets or
            # a reference from another user, store, project, or company.
            for change in ("missing", "project", "store", "user", "company"):
                model.calls.clear()
                call_identity = dict(identity)
                call_store = store["store_id"]
                call_project = dict(project)
                call_history = history
                if change == "missing":
                    call_history = [{**history[0], "market_report_id": "report_missing", "source_records": sources}]
                elif change == "project": call_project["key"] = "listing-project-unrelated"
                elif change == "store": call_store = "store-unrelated"
                elif change == "user": call_identity["user_id"] = "user-unrelated"
                else: call_identity["company_id"] = "company-unrelated"
                with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                    invalid = chat.run_ai_ceo_chat(repository=repo, **call_identity, store_id=call_store,
                        message=message, model_client=model, conversation_history=call_history,
                        active_listing_context={"contract_version": "active_listing_context_v1", "listing_project_identity": call_project})
                self.assertEqual([], model.calls, change)
                self.assertEqual([], invalid["source_records"], change)
                self.assertFalse(invalid["answer_quality"]["accepted"], change)
            del repo
            gc.collect()

    def test_metadata_headings_cannot_become_product_candidates(self):
        for heading in ("证据边界说明", "证据边界", "来源与限制", "sources and limitations"):
            result = chat.validate_ai_ceo_answer_quality(
                message="帮我调研1个候选商品，不要编造商品事实。", route="ebay_workflow",
                answer=f"### {heading}\n需求和风险仍未核实。材质、尺寸和成本未知。",
            )
            self.assertFalse(result["accepted"], heading)
            self.assertIn("missing_concrete_product_candidates", result["blocked_by"])

    def test_report_sections_are_not_products_even_with_nearby_risk_terms(self):
        from jiejing_saas.repository import _ai_ceo_market_product_candidates
        sections = ("未验证项汇总", "供应商资料清单（待补）", "边界说明", "本轮观察摘要", "后续执行步骤")
        answer = "\n\n".join(f"### {heading}\n采购成本未知，风险需要核实。" for heading in sections)
        self.assertEqual([], _ai_ceo_market_product_candidates(message="比较3个候选商品", answer=answer))
        for heading in sections[:3]:
            with self.subTest(heading=heading):
                bad_card = f"候选商品 1：{heading}\n采购成本未知，风险需要核实。"
                result = chat.validate_ai_ceo_answer_quality(message="调研1个候选商品", route="ebay_workflow", answer=bad_card)
                self.assertFalse(result["accepted"], result)

    def test_compact_evidence_table_does_not_require_price_or_score_columns(self):
        from jiejing_saas.repository import _ai_ceo_market_product_candidates
        for header in ("候选商品", "候选商品（英文）", "Product name (English)"):
            with self.subTest(header=header):
                answer = f"| {header} | 依据 | 未验证项 |\n|---|---|---|\n" + "\n".join(
                    f"| {name} | [S{i}] 仅为竞品页面 | 规格与成交资料未知 |"
                    for i, name in enumerate(PRODUCTS, 1))
                answer += "\n\n### 未验证项汇总\n采购成本未知。\n### 供应商资料清单（待补）\n履约风险未知。\n### 边界说明\n不得采购。"
                candidates = _ai_ceo_market_product_candidates(message="比较3个候选商品", answer=answer)
                self.assertEqual(list(PRODUCTS), [item["name"] for item in candidates])

    def test_candidate_table_citations_satisfy_evidence_without_dropping_report(self):
        sources = [{"citation_id": f"S{i}", "title": name,
                    "url": f"https://www.ebay.com/itm/12345678900{i}", "market_evidence_role": "item_listing_reference"}
                   for i, name in enumerate(PRODUCTS, 1)]
        answer = "| 候选商品 | 依据 | 未验证项 |\n|---|---|---|\n" + "\n".join(
            f"| {name} | [S{i}] 仅为竞品页面，不能证明需求稳定 | 成交、供应商及商品事实未验证 |"
            for i, name in enumerate(PRODUCTS, 1))
        context = {"selection_contract": {"required_candidate_count": 3,
            "candidate_evidence_entry_required": True, "common_sense_demand_claims_forbidden": True}}
        quality = chat.validate_ai_ceo_answer_quality(message="比较3个候选商品，不创建 Listing", route="ebay_workflow",
            answer=answer, source_records=sources, context=context)
        self.assertTrue(quality["accepted"], quality)
        for missing_reference in ("", "[S99]"):
            bad = answer.replace("[S2]", missing_reference)
            quality = chat.validate_ai_ceo_answer_quality(message="比较3个候选商品，不创建 Listing", route="ebay_workflow",
                answer=bad, source_records=sources, context=context)
            self.assertFalse(quality["accepted"], quality)
        stale_contract = {"selection_contract": {**context["selection_contract"], "required_candidate_count": 2}}
        quality = chat.validate_ai_ceo_answer_quality(message="比较3个原候选商品，不创建 Listing", route="ebay_workflow",
            answer=answer.replace("[S3]", ""), source_records=sources, context=stale_contract)
        self.assertFalse(quality["accepted"], "An older count cannot excuse a displayed candidate's missing evidence")
        mixed = f"候选商品 1：{PRODUCTS[0]}\n" + answer.replace("[S1]", "")
        quality = chat.validate_ai_ceo_answer_quality(message="比较3个候选商品，不创建 Listing", route="ebay_workflow",
            answer=mixed, source_records=sources, context=context)
        self.assertFalse(quality["accepted"], "Another table row cannot provide the first product's missing evidence")
        with_own_attribute = mixed.replace(f"候选商品 1：{PRODUCTS[0]}\n",
            f"候选商品 1：{PRODUCTS[0]}\n| 项目 | 内容 |\n|---|---|\n| 依据 | [S1] |\n\n")
        quality = chat.validate_ai_ceo_answer_quality(message="比较3个候选商品，不创建 Listing", route="ebay_workflow",
            answer=with_own_attribute, source_records=sources, context=context)
        self.assertTrue(quality["accepted"], "A product's own attribute table still supplies its evidence")

    def test_row_comparison_explicit_source_cells_preserve_bare_references(self):
        sources = [{"citation_id": f"S{i}", "title": name,
                    "url": f"https://www.ebay.com/itm/12345678900{i}"}
                   for i, name in enumerate(PRODUCTS, 1)]
        answer = "| 候选商品 | 来源编号 | 未验证项 |\n|---|---|---|\n" + "\n".join(
            f"| {name} | S{i} | 成交及商品资料未知 |" for i, name in enumerate(PRODUCTS, 1))
        context = {"selection_contract": {"candidate_evidence_entry_required": True}}
        def quality(text):
            return chat.validate_ai_ceo_answer_quality(message="比较3个原候选商品", route="ebay_workflow",
                answer=text, source_records=sources, context=context)
        self.assertTrue(quality(answer)["accepted"], quality(answer))
        for replacement in ("", "同上", "S99"):
            self.assertFalse(quality(answer.replace("| S2 |", f"| {replacement} |"))["accepted"])
        unknown = quality(answer.replace("| S2 |", "| S99 |"))
        self.assertIn("research_citation_not_in_evidence", unknown["blocked_by"])
        # An arbitrary model or SKU containing S# is not a citation.
        self.assertFalse(quality(answer.replace("来源编号", "型号"))["accepted"])

    def test_owned_revision_compact_table_survives_real_chat_and_report_save(self):
        message = (
            "修订刚才的候选调研报告，不新建项目。本轮不要联网检索，沿用已保存报告的五条原始来源与原编号、链接和检索日期；"
            "没有明确日期就写未验证，不要填写今天日期。比较三个原候选商品：" + "、".join(PRODUCTS) + "。"
            "用简洁比较表列依据和未验证项，给一个暂定找货建议及供应商资料清单。"
            "S3 多价格不能认作主价，Chef Select 不能写无品牌，已结束商品不能说在售；无成交证据不推断销量。"
            "竞品不是我的商品事实，供应商规格、重量、成本、发货地和图片授权仍未知。不创建 Listing、生图、采购或发布。"
        )
        answer = "| 候选商品 | 来源依据 | 未验证项 |\n|---|---|---|\n" + "\n".join(
            f"| {name} | S{i} 仅为竞品页面，不能证明需求稳定 | 成交及真实商品资料未验证 |"
            for i, name in enumerate(PRODUCTS, 1))
        answer += ("\n\n### 未验证项汇总\n品牌、价格与成交量未验证。\n"
                   "### 供应商资料清单（待补）\n材质、规格、重量、成本、发货地及图片授权未知。\n"
                   "### 边界说明\n不创建 Listing，不采购、不发布。")
        class Model:
            provider, model, calls = "deepseek", "offline-owned-revision", 0
            def generate_text(self, **kwargs):
                self.calls += 1
                return {"text": answer, "model_mode": "live_http_model_text", "model_configured": True}
        with tempfile.TemporaryDirectory(prefix="jiejing-revision-table-", ignore_cleanup_errors=True) as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="revision-table@example.test", password="unit-test-only-password", company_name="Owned table fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
            project = {"key": "listing-project-owned-table", "source_report_id": "seed", "candidate_id": "candidate-1"}
            sources = [{"citation_id": f"S{i}", "title": PRODUCTS[(i-1) % 3],
                        "url": f"https://www.ebay.com/itm/12345678900{i}", "snippet": "Price and supplier facts unverified.",
                        "captured_at": "2026-09-29T10:00:00Z", "market_evidence_role": "item_listing_reference"}
                       for i in range(1, 6)]
            task = repo.create_task(**identity, store_id=store["store_id"], task_type="merchant_ceo_chat", title="Original research", input_data={"message":"比较3个候选商品"})
            seed = repo.save_ai_ceo_market_research_report(task=task, message="比较3个候选商品", chat={
                "answer":answer, "route":"ebay_workflow", "status":"model_answered", "source_records":sources}, listing_project_identity=project)
            history = [{"user_text":"比较3个候选商品", "assistant_text":answer, "route":"ebay_workflow", "market_report_id":seed["report_id"]}]
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"], message=message,
                    model_client=model, conversation_history=history,
                    active_listing_context={"contract_version":"active_listing_context_v1", "listing_project_identity":project})
            self.assertEqual([], FakeSearch.calls)
            self.assertEqual(1, model.calls, "Valid report structure must not require a paid repair")
            self.assertEqual("model_answered", result["status"], result.get("answer_quality"))
            self.assertEqual(answer, result["answer"])
            self.assertFalse(result["answer_quality"].get("contract_projection_used"))
            self.assertEqual([s["url"] for s in sources], [s["url"] for s in result["source_records"]])
            saved = repo.save_ai_ceo_market_research_report(task=task, message=message, chat=result, listing_project_identity=project)
            self.assertEqual(list(PRODUCTS), [c["name"] for c in saved["report"]["product_candidates"]])
            self.assertEqual("incomplete", saved["report"]["supplier_fact_status"])
            self.assertFalse(saved["report"]["listing_import_ready"])
            del repo
            gc.collect()

    def test_grouped_source_cells_are_citations_without_borrowing_other_columns(self):
        sources = [{"citation_id": f"S{i}", "title": name,
                    "url": f"https://www.ebay.com/itm/12345678900{i}"}
                   for i, name in enumerate(PRODUCTS, 1)]
        answer = "| 候选商品 | 来源编号 | 未验证项 |\n|---|---|---|\n" + "\n".join(
            f"| {name} | [S{i}、S{i}] | 成交及商品资料未知 |" for i, name in enumerate(PRODUCTS, 1))
        context = {"selection_contract": {"candidate_evidence_entry_required": True}}
        def quality(text):
            return chat.validate_ai_ceo_answer_quality(message="比较3个候选商品", route="ebay_workflow",
                answer=text, source_records=sources, context=context)
        self.assertTrue(quality(answer)["accepted"], quality(answer))
        self.assertIn("research_citation_not_in_evidence", quality(answer.replace("[S2、S2]", "[S2, S99]"))["blocked_by"])
        transposed = "| 维度 | " + " | ".join(PRODUCTS) + " |\n|---|---|---|---|\n| 来源编号 | [S1、S1] | [S2, S2] | [S3/S3] |\n| 风险 | 未验证 | 未验证 | 未验证 |"
        self.assertTrue(quality(transposed)["accepted"], quality(transposed))
        self.assertFalse(quality(transposed.replace("[S2, S2]", "同左"))["accepted"])

    def test_owned_transposed_comparison_survives_chat_and_report_without_repair(self):
        message = "修订刚才的候选调研报告，不新建项目。本轮不要联网检索，沿用已保存报告的五条原始来源。比较三个原候选商品：" + "、".join(PRODUCTS) + "。给暂定找货建议，商品事实未知，不创建 Listing、不生图、不发布。"

        class Model:
            provider, model, calls = "deepseek", "offline-transposed-replay", 0
            def generate_text(self, **kwargs):
                self.calls += 1
                return {"text": TRANSPOSED_ANSWER, "model_mode": "live_http_model_text", "model_configured": True}

        with tempfile.TemporaryDirectory(prefix="jiejing-transposed-", ignore_cleanup_errors=True) as folder:
            repo = SaaSRepository(Path(folder) / "fixture.sqlite")
            account = repo.create_user_with_company(email="transposed@example.test", password="unit-test-only-password", company_name="Transposed fixture")
            identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
            store = repo.create_store(**identity, payload={"platform":"ebay", "marketplace":"EBAY_US"})
            project = {"key":"listing-project-transposed", "source_report_id":"seed", "candidate_id":"candidate-1"}
            titles = [PRODUCTS[0], PRODUCTS[1], PRODUCTS[2], "Chef Select measuring cups", "Soli silicone spatula"]
            sources = [{"citation_id":f"S{i}", "title":title, "url":f"https://www.ebay.com/itm/12345678900{i}",
                        "snippet":"Supplier facts and current price not verified.", "captured_at":"2026-09-29T10:00:00Z",
                        "market_evidence_role":"item_listing_reference"} for i, title in enumerate(titles, 1)]
            task = repo.create_task(**identity, store_id=store["store_id"], task_type="merchant_ceo_chat", title="Original comparison", input_data={"message":"比较3个候选商品"})
            seed = repo.save_ai_ceo_market_research_report(task=task, message="比较3个候选商品", chat={"answer":TRANSPOSED_ANSWER,
                "route":"ebay_workflow", "status":"model_answered", "source_records":sources}, listing_project_identity=project)
            history = [{"user_text":"比较3个候选商品", "assistant_text":TRANSPOSED_ANSWER, "route":"ebay_workflow", "market_report_id":seed["report_id"]}]
            model = Model()
            with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"], message=message,
                    model_client=model, conversation_history=history,
                    active_listing_context={"contract_version":"active_listing_context_v1", "listing_project_identity":project})
            self.assertEqual("model_answered", result["status"], result.get("answer_quality"))
            self.assertEqual(TRANSPOSED_ANSWER, result["answer"])
            self.assertEqual(1, model.calls, "A valid column comparison must not consume a repair call")
            self.assertEqual([], FakeSearch.calls)
            self.assertEqual([s["url"] for s in sources], [s["url"] for s in result["source_records"]])
            self.assertFalse(result["answer_quality"].get("contract_projection_used"))
            saved = repo.save_ai_ceo_market_research_report(task=task, message=message, chat=result, listing_project_identity=project)
            self.assertEqual(["不锈钢量勺量杯套装", "硅胶锅铲", "不锈钢咖啡勺"], [c["name"] for c in saved["report"]["product_candidates"]])
            self.assertEqual("incomplete", saved["report"]["supplier_fact_status"])
            self.assertFalse(saved["report"]["listing_import_ready"])
            del repo
            gc.collect()

    def test_column_comparison_keeps_evidence_per_product_not_per_table(self):
        names = ["不锈钢量勺量杯套装", "硅胶锅铲", "不锈钢咖啡勺"]
        sources = [{"citation_id":f"S{i}", "title":name, "url":f"https://www.ebay.com/itm/12345678900{i}"}
                   for i, name in enumerate(names, 1)]
        answer = "| 维度 | " + " | ".join(names) + " |\n|---|---|---|---|\n| 来源编号 | S1 | S2 | S3 |\n| 未验证项 | 商品事实未知 | 商品事实未知 | 商品事实未知 |"
        context = {"selection_contract":{"candidate_evidence_entry_required":True}}
        def quality(text):
            return chat.validate_ai_ceo_answer_quality(message="比较3个候选商品", route="ebay_workflow",
                answer=text, source_records=sources, context=context)
        self.assertTrue(quality(answer)["accepted"], quality(answer))
        for replacement in ("", "同左", "S99"):
            for prefix in ("", "候选商品 1：不锈钢量勺量杯套装\n"):
                bad = prefix + answer.replace("| S2 |", f"| {replacement} |")
                self.assertFalse(quality(bad)["accepted"], "A peer column cannot lend its evidence")
        for heading in ("维度 | 依据 | 未验证项", "维度 | 不锈钢量勺量杯套装 | 不锈钢量勺量杯套装"):
            bad = f"| {heading} |\n|---|---|---|\n| 风险 | 未知 | 未知 |"
            self.assertFalse(quality(bad)["accepted"], "Metadata/duplicate headers are not a candidate comparison")
        self.assertFalse(quality(answer + "\n| 主价 | $99 |")["accepted"], "Misaligned columns must not silently drop claims")

    def test_column_comparison_cannot_bypass_price_brand_and_source_checks(self):
        sources = [
            {"citation_id":"S1", "title":"Unbranded measuring cups", "url":"https://www.ebay.com/itm/123456789001", "snippet":"Unbranded $12.99"},
            {"citation_id":"S2", "title":"Soli silicone spatula", "url":"https://www.ebay.com/itm/123456789002", "snippet":"Price unverified"},
            {"citation_id":"S3", "title":"Reed Barton teaspoons", "url":"https://www.ebay.com/itm/123456789003", "snippet":"$31.24 previous $36.75 other items $64.39"},
        ]
        prefix = "| 维度 | 不锈钢量勺量杯套装 | 硅胶锅铲 | 不锈钢咖啡勺 |\n|---|---|---|---|\n| 来源编号 | S1 | S2 | S3 |\n"
        def quality(text):
            return chat.validate_ai_ceo_answer_quality(message="比较3个候选商品", route="ebay_workflow", answer=text, source_records=sources)
        bad = quality(prefix + "| 主价 | $12.99 | 未验证 | $31.24 |")
        self.assertIn("research_ambiguous_main_item_price", bad["blocked_by"])
        bad_brand = quality(prefix + "| 品牌 | 无品牌 | 无品牌 | 无品牌 |")
        self.assertIn("research_unverified_unbranded_claim", bad_brand["blocked_by"])
        unknown = quality(prefix.replace("| S2 |", "| S99 |") + "| 主价 | 未验证 | 未验证 | 未验证 |")
        self.assertIn("research_citation_not_in_evidence", unknown["blocked_by"])
        good = quality(prefix + "| 主价 | $12.99 | 未验证 | 主商品价格未验证 |\n| 品牌 | 无品牌 | Soli | Reed Barton |")
        self.assertTrue(good["accepted"], good)
        good_with_cell_citations = quality(prefix + "| 主价 | $12.99 [S1] | 未验证 [S2] | 未验证 [S3] |")
        self.assertTrue(good_with_cell_citations["accepted"], "A different column's ambiguous prices cannot invalidate S1's own price")

    def test_uncertainty_about_demand_is_not_an_affirmative_demand_claim(self):
        for statement in ("不能证明需求稳定。", "不能据此判断存在长期稳定需求。", "需求长期稳定尚未验证。", "无成交证据，不要推断需求稳定。"):
            self.assertFalse(chat._answer_uses_unsupported_demand_shortcuts(statement), statement)
        for statement in ("长期稳定需求。", "虽然尚无成交证据，但需求稳定。", "不能证明销量，但存在持续痛点。", "不能证明销量而需求稳定。"):
            self.assertTrue(chat._answer_uses_unsupported_demand_shortcuts(statement), statement)

    def test_current_listing_claim_is_not_cancelled_by_later_uncertainty(self):
        # Minimized merchant-visible report740 failure. Historical search
        # snippets cannot prove current availability, even with a footer caveat.
        sources = [
            {"citation_id": "S1", "title": "Measuring Cups and Spoons",
             "url": "https://www.ebay.com/itm/123456789001",
             "snippet": "Measuring cups. Buy it now.", "market_evidence_role": "item_listing_reference"},
            {"citation_id": "S4", "title": "Chef Select measuring cups",
             "url": "https://www.ebay.com/itm/123456789004", "market_evidence_role": "item_listing_reference"},
        ]
        result = chat.validate_ai_ceo_answer_quality(
            message="比较1个候选商品，不创建 Listing。", route="ebay_workflow",
            answer=("候选 1：stainless steel measuring spoons cups set\n"
                    "来源支持：S1 和 S4 的标题都指向这一品类在 eBay US 有在售 listing。\n"
                    "来源日期、当前在售状态、主商品价格和销量：均未验证。"),
            source_records=sources)
        self.assertFalse(result["accepted"], result)
        self.assertIn("research_unverified_current_availability", result["blocked_by"])

    def test_availability_guard_checks_each_statement_and_table_status(self):
        sources = [{"citation_id": "S1", "title": "Measuring cups",
                    "url": "https://www.ebay.com/itm/123456789001", "snippet": "Buy it now"}]
        prefix = "候选商品 1：stainless steel measuring cups set\n"
        for claim in (
            "当前在售 [S1]。\n当前在售状态未验证。",
            "主商品价格未验证，但商品仍在售。", "不能证明销量，but currently available [S1].",
            "| 候选商品 | 状态 | 来源 |\n|---|---|---|\n| measuring cups | 在售 | [S1] |",
            "| 维度 | measuring cups |\n|---|---|\n| 来源 | S1 |\n| 状态 | 在售 |",
        ):
            result = chat.validate_ai_ceo_answer_quality(message="比较1个候选商品，不创建 Listing。",
                route="ebay_workflow", answer=prefix+claim, source_records=sources)
            self.assertIn("research_unverified_current_availability", result["blocked_by"], claim)
        for claim in (
            "来源日期、当前在售状态、主商品价格和销量：均未验证。",
            "不能确认是否仍在售 [S1]。", "不要写当前在售；只可确认历史页面存在。",
            "历史页面当时在售，无法确认目前在售状态。", "Current availability is unverified [S1].",
            "Not currently available evidence; availability unknown.",
            "在售标价不等于成交价。当前状态待核实。",
            "| 候选商品 | 状态 | 来源 |\n|---|---|---|\n| measuring cups | 在售状态未验证 | [S1] |",
        ):
            result = chat.validate_ai_ceo_answer_quality(message="比较1个候选商品，不创建 Listing。",
                route="ebay_workflow", answer=prefix+claim, source_records=sources)
            self.assertNotIn("research_unverified_current_availability", result["blocked_by"], claim)

    def test_availability_table_labels_are_not_positive_claims(self):
        sources = [{"citation_id": "S1", "title": "Adhesive cable clips",
                    "url": "https://www.ebay.com/itm/123456789001", "snippet": "US $5.99"}]
        for claim in (
            "| 商品 | 当前在售状态 | 来源 |\n|---|---|---|\n| Adhesive cable clips | 未验证 | [S1] |",
            "| 项目 | 结论 |\n|---|---|\n| 当前在售状态 | 未验证 [S1] |",
            "| 商品 | **当前在售状态** | 来源 |\n|---|---|---|\n| Adhesive cable clips | **未验证** | [S1] |",
            "| Product | Current availability | Source |\n|---|---|---|\n| Adhesive cable clips | unknown | [S1] |",
        ):
            with self.subTest(claim=claim):
                self.assertNotIn("research_unverified_current_availability",
                                 chat._research_source_answer_blockers(claim, sources))
        for claim in (
            "| 商品 | 当前在售状态 | 备注 |\n|---|---|---|\n| cable clips | 在售 | 销量未验证 |",
            "| 项目 | 结论 |\n|---|---|\n| 当前在售状态 | 在售 [S1] |",
            "| 商品 | 当前在售状态 |\n|---|---|\n| cable clips | 未验证 |\n| another product | 在售 |",
            "| 当前在售的商品 | 备注 |\n|---|---|\n| cable clips | 未验证 |",
            "当前在售 [S1]。\n| 项目 | 结论 |\n|---|---|\n| 当前在售状态 | 未验证 |",
        ):
            with self.subTest(claim=claim):
                self.assertIn("research_unverified_current_availability",
                              chat._research_source_answer_blockers(claim, sources))

    def test_real_chat_repairs_availability_or_rejects_without_generic_projection(self):
        bad = "\n\n".join(f"候选商品 {i}：{name}\n当前在售 [S{i}]。价格与供应商事实未验证。"
                          for i, name in enumerate(PRODUCTS, 1))
        good = bad.replace("当前在售", "历史商品页面参考，当前在售状态未验证")
        for already_recovered in (False, True):
            class Model:
                provider, model, calls = "deepseek", "offline-availability-fixture", 0
                def generate_text(self, **kwargs):
                    self.calls += 1
                    if self.calls > 1:
                        self_test.assertIn("research_unverified_current_availability", kwargs["system_prompt"])
                    return {"text": good if self.calls > 1 else bad, "model_mode": "live_http_model_text",
                            "model_configured": True, "bounded_empty_answer_recovery": already_recovered}
            self_test = self
            with tempfile.TemporaryDirectory(prefix="jiejing-availability-", ignore_cleanup_errors=True) as folder:
                repo = SaaSRepository(Path(folder) / "fixture.sqlite")
                account = repo.create_user_with_company(email="availability@example.test",
                    password="unit-test-only-password", company_name="Availability fixture")
                identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
                store = repo.create_store(**identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
                model = Model()
                with patch.object(chat, "PublicSearchProbeAdapter", FakeSearch):
                    result = chat.run_ai_ceo_chat(repository=repo, **identity, store_id=store["store_id"],
                        message="比较3个候选商品："+"、".join(PRODUCTS)+"。不创建 Listing。", model_client=model)
                self.assertFalse(result["answer_quality"].get("contract_projection_used"))
                if already_recovered:
                    self.assertEqual(1, model.calls, "Do not exceed the existing bounded recovery budget")
                    self.assertEqual("model_answer_rejected", result["status"])
                    self.assertIn("research_unverified_current_availability", result["answer_quality"]["blocked_by"])
                    self.assertIn("历史商品页面误写成了当前在售证明", result["answer"])
                else:
                    self.assertEqual(2, model.calls)
                    self.assertEqual("model_answered", result["status"])
                    self.assertEqual(good, result["answer"])
                    self.assertEqual(1, result["answer_quality"]["repair_retry_count"])
                del repo
                gc.collect()

    def test_research_cannot_swap_citations_or_promote_ambiguous_prices_and_brands(self):
        sources = [
            {"citation_id": "S1", "title": "Chef Select measuring cups", "url": "https://www.ebay.com/itm/123456789001", "snippet": "Seller feedback. $31.24 previous price $36.75. Other items $64.39.", "market_evidence_role": "item_listing_reference"},
            {"citation_id": "S2", "title": "Silicone spatula", "url": "https://www.ebay.com/itm/123456789002", "snippet": "No verified price", "market_evidence_role": "item_listing_reference"},
        ]
        prefix = "候选商品 1：stainless steel measuring cups set\n"
        for claim in ("主商品价格为 $31.24 [S1]。", "两款均为无品牌通用款。",
                      '| measuring cups | https://www.ebay.com/itm/123456789001 | $31.24（原价 $36.75） |',
                      '本轮命中的两个量杯页面均为**无品牌通用款**。',
                      "来源 [S3] 已核实。", "[S1] https://www.ebay.com/itm/123456789002",
                      "[S1] https://www.ebay.com/itm/999999999999"):
            result = chat.validate_ai_ceo_answer_quality(message="调研1个候选商品，不创建 Listing。", route="ebay_workflow", answer=prefix+claim, source_records=sources)
            self.assertFalse(result["accepted"], claim)
        valid = chat.validate_ai_ceo_answer_quality(message="调研1个候选商品，不创建 Listing。", route="ebay_workflow",
            answer=prefix+"片段含 $31.24 和其他价格，主商品价格未验证 [S1]。品牌状态未验证，不应认定为无品牌。", source_records=sources)
        self.assertTrue(valid["accepted"], valid)

        # Preserve the live failure's link-only table and Markdown emphasis,
        # rather than proving only an easier citation-tagged paraphrase.
        valid_table = chat.validate_ai_ceo_answer_quality(message="调研1个候选商品，不创建 Listing。", route="ebay_workflow",
            answer=prefix+'| measuring cups | https://www.ebay.com/itm/123456789001 | 片段含 $31.24；**主商品价格未验证** |\n'
                +'不能认定两个页面均为**无品牌通用款**，品牌状态未验证。', source_records=sources)
        self.assertTrue(valid_table["accepted"], valid_table)

    def test_cups_is_not_ups_but_unverified_shipping_remains_blocked(self):
        message = "帮我调研1个候选商品，不要编造商品事实。"
        valid = chat.validate_ai_ceo_answer_quality(message=message, route="ebay_workflow",
            answer="候选商品 1：stainless steel measuring cups set\n商品规格、成本和运输方案未知。")
        self.assertTrue(valid["accepted"], valid)
        for carrier in ("UPS Ground", "USPS First Class", "FedEx Express"):
            invalid = chat.validate_ai_ceo_answer_quality(message=message, route="ebay_workflow",
                answer=f"候选商品 1：stainless steel measuring cups set\n使用 {carrier} shipping。")
            self.assertFalse(invalid["accepted"], carrier)
            self.assertIn("invented_unknown_product_facts", invalid["blocked_by"])

    def test_deferred_listing_blocks_listing_fields_in_candidate_answer(self):
        for boundary in ("不创建 Listing", "不生成 Listing", "不需要生成 Listing", "无须创建 Listing",
                         "不必创建 Listing", "不允许生成 Listing 草稿"):
            result = chat.validate_ai_ceo_answer_quality(
                message="比较1个候选商品。" + boundary + "。", route="ebay_workflow",
                answer="候选商品 1：stainless steel measuring cups set\n商品规格、成本和运输方案未知。\nListing 标题：Stainless Steel Measuring Cups Set",
            )
            self.assertFalse(result["accepted"], (boundary, result))
            self.assertIn("listing_scope_exceeded", result["blocked_by"])

    def test_evidence_table_uses_named_product_column_not_row_number(self):
        result = chat.validate_ai_ceo_answer_quality(
            message="比较2个候选商品，核对商品链接与价格，不要编造商品事实。", route="ebay_workflow",
            answer=("| 序号 | 候选商品 | 商品链接 | 在售标价 |\n|---|---|---|---|\n"
                "| 1 | felt chair pads | https://www.ebay.com/itm/123456789001 | 未验证 |\n"
                "| 2 | wooden napkin rings | https://www.ebay.com/itm/123456789002 | 未验证 |\n"
                "\n证据边界：商品尺寸、重量、成本与发货地未知。"),
        )
        self.assertTrue(result["accepted"], result)
        self.assertEqual(2, result["candidate_count"])

    def test_one_unbranded_source_cannot_establish_all_products_are_unbranded(self):
        sources = [
            {"citation_id": "S1", "title": "Unbranded measuring cups", "url": "https://www.ebay.com/itm/123456789001"},
            {"citation_id": "S2", "title": "Chef Select measuring cups", "url": "https://www.ebay.com/itm/123456789002"},
        ]
        for claim in ("两款均为无品牌 [S1] [S2]", "这款品牌为无品牌 [S2]", "两款均为无品牌"):
            self.assertIn("research_unverified_unbranded_claim", chat._research_source_answer_blockers(claim, sources), claim)
        self.assertEqual([], chat._research_source_answer_blockers("这款品牌为无品牌 [S1]", sources))

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
