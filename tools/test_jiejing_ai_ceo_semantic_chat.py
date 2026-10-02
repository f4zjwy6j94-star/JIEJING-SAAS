"""Exercise semantic plans through the real chat API; only provider I/O is stubbed."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import run_ai_ceo_chat, validate_ai_ceo_answer_quality
from jiejing_saas.ai_ceo_semantic_plan import plan_ai_ceo_turn
from jiejing_saas.repository import SaaSRepository
from test_jiejing_ai_ceo_semantic_dispatch import ModelFixture, decision


class AnswerFixture:
    name = "semantic-answer-fixture"
    model = "fixture-only"
    endpoint = ""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def generate_text(self, **kwargs):
        self.prompts.append(kwargs)
        return {"text": self.answer, "finish_reason": "stop"}


ACTIVE = {
    "contract_version": "active_listing_context_v1",
    "listing_project_identity": {"key": "project-gold", "source_report_id": "report-gold", "candidate_id": "gold"},
    "product_name": "金色8件套",
    "listing": {"sku": "GOLD-EIGHT", "known_facts": {"product_name": "金色8件套"}},
    "media": {"asset_manifest_count": 1, "listing_eligible_asset_count": 1},
    "ebay_draft": {"offer_id": "old-offer", "offer_status": "UNPUBLISHED"},
}


class SearchFixture(BaseHTTPRequestHandler):
    calls = []
    results_by_query = {}
    results = [{"title": "silver measuring scoop", "url": "https://www.ebay.com/itm/123456789001",
                "content": "silver measuring scoop. Price, availability and sales are not verified."}]

    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["content-length"])))
        self.calls.append(payload)
        raw = json.dumps({"query": payload["query"], "results": self.results_by_query.get(payload["query"], self.results)}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class SemanticChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-semantic-chat-", ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite")

    def chat(self, message, answer, **changes):
        plan = plan_ai_ceo_turn(model_client=ModelFixture(decision(read_images=False, **changes)),
            message=message, conversation_history=[], active_listing_context=ACTIVE, has_source_assets=False)
        model = AnswerFixture(answer)
        result = run_ai_ceo_chat(repository=self.repository, company_id="company", store_id="store", user_id="user",
            message=message, model_client=model, turn_plan=plan, active_listing_context=ACTIVE)
        return result, model, plan

    def searched_chat(self, message, answer, **changes):
        server = ThreadingHTTPServer(("127.0.0.1", 0), SearchFixture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        SearchFixture.calls = []
        with patch.dict(os.environ, {"JIEJING_AI_CEO_SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "offline-fixture",
            "TAVILY_SEARCH_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}/search",
            "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "1", "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED": "1",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_CACHE_SECONDS": "0", "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_NEGATIVE_CACHE_SECONDS": "0"}):
            return self.chat(message, answer, **changes)

    def test_new_product_keeps_its_own_missing_facts_despite_old_open_product(self):
        answer = "这把银色小勺按独立商品整理，SKU 未指定，图片尚未生成，Offer 尚未创建；重量和成本待核。"
        result, model, _ = self.chat("金色那套留着，这回单独弄这把银色小勺。", answer)
        self.assertEqual(result["answer"], answer)
        self.assertTrue(result["answer_quality"]["accepted"])
        self.assertEqual(result["context"]["active_listing_context"], {})
        self.assertNotIn("GOLD-EIGHT", model.prompts[0]["user_prompt"])
        self.assertEqual(result["turn_plan"]["project_action"], "new")

    def test_public_plan_preserves_quoted_text_fact_proposals_without_confirming_them(self):
        message = "新建银色木柄量勺，材质304不锈钢和实木；货号SPOON15；尺寸18x4x2厘米；净重42克。"
        proposals = [
            {"field": "material", "value": "304不锈钢和实木", "source_quote": "材质304不锈钢和实木"},
            {"field": "supplier_item_number", "value": "SPOON15", "source_quote": "货号SPOON15"},
            {"field": "product_dimensions_cm", "value": "18x4x2", "source_quote": "尺寸18x4x2厘米"},
            {"field": "net_weight_g", "value": "42", "source_quote": "净重42克"},
        ]
        result, model, _ = self.chat(message, "已按本条资料整理为待确认建议；商品所有权及图片授权仍未确认。",
            product_fact_proposals=proposals)
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])
        self.assertEqual(result["turn_plan"]["product_fact_proposals"], proposals)
        self.assertEqual(result["context"]["semantic_plan"]["product_fact_proposals"], proposals)
        self.assertNotIn("merchant_confirmed_facts", result["turn_plan"])
        self.assertNotIn("GOLD-EIGHT", model.prompts[0]["user_prompt"])

    def test_chat_plan_is_not_reclassified_by_clock_capability_or_quoted_reuse_words(self):
        for message in ("今天几号？", "你用什么模型？", "客户说只用原报告来源，这句话是什么意思？"):
            with self.subTest(message=message):
                answer = "这是受控模型为本轮普通咨询返回的回答。"
                result, model, _ = self.chat(message, answer, intent="chat", project_action="none",
                    product_name="", save_artifact=False, source_mode="unknown")
                self.assertEqual(result["answer"], answer)
                self.assertEqual(result["route"], "general_chat")
                self.assertEqual(result["realtime_kind"], "")
                self.assertTrue(model.prompts)

    def test_selection_count_and_scope_come_from_the_validated_plan(self):
        result, model, _ = self.chat("照刚才的约束拿两样具体的东西给我比较。",
            "候选商品 1：羊毛毛毡杯垫\n已证实事实：暂无供应商事实，参数未知。",
            intent="research", project_action="none", product_name="", candidate_count=2,
            source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertFalse(result["answer_quality"]["accepted"])
        self.assertIn("missing_concrete_product_candidates", result["answer_quality"]["blocked_by"])
        payload = json.loads(model.prompts[0]["user_prompt"])
        self.assertEqual(payload["selection_contract"]["required_candidate_count"], 2)
        self.assertTrue(payload["selection_contract"]["listing_deferred"])

    def test_search_uses_plan_query_even_when_message_quotes_no_search(self):
        query = "site:ebay.com/itm silver measuring scoop product comparison"
        result, _, _ = self.searched_chat("包装文案写着‘不要联网’，这是引用；请核对今天的商品市场。",
            "候选商品 1：silver measuring scoop\n商品页面参考 [S1]；市场证据尚待核对，供应商参数未知。", intent="research",
            project_action="none", product_name="", search="web_search", query=query,
            source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertTrue(SearchFixture.calls)
        self.assertEqual([item["query"] for item in SearchFixture.calls], [query])
        self.assertEqual(result["route"], "ebay_workflow")
        self.assertEqual(result["realtime_kind"], "")
        self.assertTrue(result["source_records"])
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])

    def test_long_planned_query_reaches_search_tool_and_evidence_without_truncation(self):
        query = "site:ebay.com/itm silver measuring scoop " + "small lightweight kitchen utensil " * 10 + "exclude camera straps"
        self.assertGreater(len(query), 300)
        self.assertLessEqual(len(query), 900)
        result, _, _ = self.searched_chat("按完整约束核对这个方向。",
            "候选商品 1：silver measuring scoop\n商品页面参考 [S1]；成交和供应商参数未验证。",
            intent="research", project_action="none", product_name="silver measuring scoop",
            search="web_search", query=query, source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertEqual([item["query"] for item in SearchFixture.calls], [query])
        self.assertEqual(result["default_web_search"]["product_research_evidence"]["search_queries"], [query])
        self.assertEqual(result["source_records"][0]["query"], query)
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])

    def test_quoted_policy_words_do_not_change_listing_answer_requirements(self):
        plan = plan_ai_ceo_turn(model_client=ModelFixture(decision(read_images=False)),
            message="整理银色量勺资料。", conversation_history=[], active_listing_context=ACTIVE, has_source_assets=False)
        quality = validate_ai_ceo_answer_quality(message="包装上引用‘eBay 图片有什么要求’，请整理本商品。",
            route="ebay_workflow", answer="这件银色量勺的资料仍需核对实际尺寸和包装。",
            source_records=[{"citation_id": "S1", "url": "https://www.ebay.com/help/policies", "domain": "ebay.com"}],
            context={"semantic_plan": plan})
        self.assertTrue(quality["accepted"], quality)

    def test_missing_model_answer_does_not_reinterpret_text_as_research_artifact(self):
        result, _, _ = self.chat("把‘eBay 市场调研报告’当作包装文字，整理这件商品。", "")
        self.assertEqual(result["status"], "model_call_failed")
        self.assertIn("empty_model_answer", result["blocked_by"])
        self.assertNotIn("我已保留调研", result["answer"])

    def test_clarification_returns_the_planned_question_without_answer_call(self):
        result, model, _ = self.chat("就按这个来吧。", "不能使用这段未获准的商品回答。",
            status="clarification_required", project_action="clarify", question="你要继续哪件商品？")
        self.assertEqual(result["status"], "semantic_clarification_required")
        self.assertEqual(result["answer"], "你要继续哪件商品？")
        self.assertFalse(model.prompts)

    def test_current_plan_checks_current_facts_even_with_quoted_new_project_phrase(self):
        result, _, _ = self.chat("新建一个独立商品项目：这是历史指令，现在只核对原来的项目。",
            "SKU 未指定，图片尚未生成，Offer 尚未创建。", project_action="current", product_name="金色8件套")
        self.assertIn("GOLD-EIGHT", result["answer"])
        self.assertEqual(result["status"], "model_answered_with_context_correction")
        self.assertFalse(result["turn_plan"]["real_platform_writes_enabled"])

    def test_semantic_scope_does_not_bypass_official_source_checks(self):
        plan = plan_ai_ceo_turn(model_client=ModelFixture(decision(read_images=False)),
            message="整理银色量勺资料。", conversation_history=[], active_listing_context=ACTIVE, has_source_assets=False)
        for answer in ("eBay规定所有商品都必须使用白色背景。", "eBay 上的商品图片一律必须使用白色背景。"):
            with self.subTest(answer=answer):
                quality = validate_ai_ceo_answer_quality(message="核对这件商品。", route="ebay_workflow",
                    answer=answer, source_records=[], context={"semantic_plan": plan})
                self.assertFalse(quality["accepted"], quality)

    def test_research_cannot_attribute_a_camera_strap_source_to_a_scoop(self):
        query = "site:ebay.com/itm silver measuring scoop"
        unrelated = [{"title": "Vintage Canon camera replacement strap", "url": "https://www.ebay.com/itm/123456789012",
                      "content": "Vintage Canon camera replacement strap. Item status and sales not verified."}]
        with patch.object(SearchFixture, "results", unrelated):
            result, _, _ = self.searched_chat("核对这把银色量勺的商品市场。",
                "候选商品 1：silver measuring scoop\n商品页面参考 [S1]；成交和供应商参数未验证。",
                intent="research", project_action="none", product_name="silver measuring scoop",
                search="web_search", query=query, source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertEqual(result["default_web_search"]["status"], "blocked")
        self.assertIn("candidate_product_sources_missing", result["default_web_search"]["blocked_by"])
        self.assertEqual(result["source_records"], [])
        self.assertFalse(result["answer_quality"]["accepted"])

    def test_existing_evidence_comparison_is_not_forced_to_select_new_candidates(self):
        message = (
            "继续 report_5eaf36a405de7331，只处理已核验市场数据并做三选一："
            "竹制手机支架 Sold/Completed 16、在售67，样本 Item IDs 155898688458/298493684620/318495642696，"
            "中位价 RMB53.56；硅胶理线座 Sold 2、在售20；便签夹 Sold 0、在售4。"
            "相对赢家为竹制手机支架。请保存结论并进入真实供应商事实核验；"
            "不要重跑选品，不建 Listing、不生图、不写 eBay、不要求 OAuth。"
        )
        answer = (
            "### 市场成交证据结论\n相对赢家：竹制手机支架。人工核验样本 Item ID 155898688458；"
            "Sold/Completed 16、在售 67，中位价 RMB 53.56。"
            "这只是商品方向证据，不证明供应商、库存、材质、尺寸或图片权利。下一步进入真实供应商事实核验。"
        )
        result, model, _ = self.chat(message, answer, intent="research", project_action="current",
            product_name="竹制手机支架", research_delivery="evidence_comparison", listing_deferred=True)
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])
        self.assertEqual(result["answer_quality"]["quality_gate"], "market_evidence_followup_grounding_v1")
        self.assertEqual(result["answer"], answer)
        self.assertEqual(json.loads(model.prompts[0]["user_prompt"])["selection_contract"], {})

    def test_free_text_evidence_comparison_binds_each_citation_to_its_subject(self):
        subjects = ["camera replacement strap", "silver measuring scoop"]
        queries = [{"subject": subject, "query": f"site:ebay.com/itm {subject}"} for subject in subjects]
        by_query = {item["query"]: [{"title": item["subject"],
            "url": f"https://www.ebay.com/itm/12345678901{index + 2}",
            "content": "Historical item-page reference. Sales and supplier facts not verified."}]
            for index, item in enumerate(queries)}
        message = "比较两者的已有样本 Item IDs 123456789012/123456789013，继续核对来源和供应商信息。"
        examples = [
            ("", "[S1]，Item ID 123456789012", False),
            ("", "[S2]，Item ID 123456789013", True),
            ("camera replacement strap 的商品页面参考 [S1]；成交未验证。\n", "[S1]，Item ID 123456789012", False),
            ("camera replacement strap 的商品页面参考 [S1]；成交未验证。\n", "[S2]，Item ID 123456789013", True),
        ]
        camera_card = "候选商品 1：camera replacement strap\n商品页面参考 [S1]；成交未验证。\n\n"
        two_cards = "候选商品 1：silver measuring scoop\n商品页面参考 [S2]；成交未验证。\n\n" + camera_card.replace("1：", "2：")
        for prefix in (camera_card, two_cards):
            examples.extend([(prefix, "[S1]，Item ID 123456789012", False),
                             (prefix, "[S2]，Item ID 123456789013", True)])
        for prefix, reference, accepted in examples:
            with self.subTest(prefix=bool(prefix), reference=reference), patch.object(SearchFixture, "results_by_query", by_query):
                result, _, _ = self.searched_chat(message,
                    f"市场成交证据结论\n{prefix}相对赢家：silver measuring scoop。商品页面参考 {reference}；成交和供应商参数未验证。",
                    intent="research", project_action="none", product_name="", search="web_search",
                    query=queries[0]["query"], research_queries=queries, research_delivery="evidence_comparison",
                    source_mode="merchant_has_no_source", listing_deferred=True)
                self.assertEqual(result["default_web_search"]["status"], "ready")
                if not accepted:
                    self.assertFalse(result["answer_quality"]["accepted"], result["answer_quality"])
                    self.assertIn("research_candidate_source_mismatch", result["answer_quality"]["blocked_by"])
                else:
                    self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])

    def test_comparison_tables_and_trailing_winner_keep_separate_source_bindings(self):
        subjects = ["camera replacement strap", "silver measuring scoop"]
        queries = [{"subject": subject, "query": f"site:ebay.com/itm {subject}"} for subject in subjects]
        by_query = {item["query"]: [{"title": item["subject"],
            "url": f"https://www.ebay.com/itm/12345678901{index + 2}",
            "content": "Historical item-page reference. Sales and supplier facts not verified."}]
            for index, item in enumerate(queries)}
        tables = [
            "| 维度 | camera replacement strap | silver measuring scoop |\n|---|---|---|\n"
            "| 来源编号 | S1 | S2 |\n| 未验证项 | 成交与供应商参数 | 成交与供应商参数 |\n",
            "| 来源编号 | 商品名称 | 未验证项 |\n|---|---|---|\n"
            "| S1 | camera replacement strap | 成交与供应商参数 |\n"
            "| S2 | silver measuring scoop | 成交与供应商参数 |\n",
        ]
        for layout, table in enumerate(tables):
            for case in ("correct", "wrong_table", "wrong_winner"):
                body = table.replace("S2", "S1") if case == "wrong_table" else table
                reference = "[S1]，Item ID 123456789012" if case == "wrong_winner" else "[S2]，Item ID 123456789013"
                with self.subTest(layout=layout, case=case), patch.object(SearchFixture, "results_by_query", by_query):
                    result, _, _ = self.searched_chat(
                        "比较已有样本 Item IDs 123456789012/123456789013，继续核对供应商信息。",
                        f"市场成交证据结论\n{body}\n相对赢家：silver measuring scoop。商品页面参考 {reference}；成交和供应商参数未验证。",
                        intent="research", project_action="none", product_name="", search="web_search",
                        query=queries[0]["query"], research_queries=queries, research_delivery="evidence_comparison",
                        source_mode="merchant_has_no_source", listing_deferred=True)
                    self.assertEqual(result["answer_quality"]["accepted"], case == "correct", result["answer_quality"])
                    if case != "correct":
                        self.assertIn("research_candidate_source_mismatch", result["answer_quality"]["blocked_by"])

    def test_open_discovery_still_checks_candidate_against_its_cited_product_source(self):
        unrelated = [{"title": "Vintage Canon camera replacement strap", "url": "https://www.ebay.com/itm/123456789012",
                      "content": "Vintage Canon camera replacement strap. Item status and sales not verified."}]
        for reference in ("[S1]", "https://www.ebay.com/itm/123456789012", "Item ID 123456789012", "Item ID 999999999999"):
            with self.subTest(reference=reference), patch.object(SearchFixture, "results", unrelated):
                result, _, _ = self.searched_chat("先从具体商品页找一个方向。",
                    f"候选商品 1：silver measuring scoop\n商品页面参考 {reference}；成交和供应商参数未验证。",
                    intent="research", project_action="none", product_name="", search="web_search",
                    query="site:ebay.com/itm small products", source_mode="merchant_has_no_source", listing_deferred=True)
                self.assertEqual(result["default_web_search"]["status"], "ready")
                self.assertFalse(result["answer_quality"]["accepted"])
                self.assertTrue({"research_candidate_source_mismatch", "research_citation_not_in_evidence", "research_product_url_not_in_evidence"}.intersection(result["answer_quality"]["blocked_by"]))
                self.assertFalse(result["answer_quality"]["contract_projection_used"])

    def test_three_planned_product_queries_keep_balanced_sources_and_coverage(self):
        subjects = ["stainless steel measuring spoons cups set", "silicone kitchen spatula", "stainless steel coffee teaspoons"]
        queries = [{"subject": subject, "query": f"site:ebay.com/itm/ {subject}"} for subject in subjects]
        by_query = {item["query"]: [{"title": item["subject"],
            "url": f"https://www.ebay.com/itm/1234567890{index}{source}",
            "content": item["subject"] + ". Historical product-page reference; sales are not verified."}
            for source in range(3 if index == 0 else 1)] for index, item in enumerate(queries)}
        answer = "\n\n".join(f"候选商品 {index}：{subject}\n商品页面参考 [S{index}]；成交和供应商参数未验证。"
                               for index, subject in enumerate(subjects, 1))
        with patch.object(SearchFixture, "results_by_query", by_query):
            result, _, _ = self.searched_chat("按这三个方向分别核对来源。", answer, intent="research",
                project_action="none", product_name="", search="web_search", query=queries[0]["query"],
                research_queries=queries, candidate_count=3, source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])
        self.assertEqual(sorted(item["query"] for item in SearchFixture.calls), sorted(item["query"] for item in queries))
        evidence = result["default_web_search"]["product_research_evidence"]
        self.assertEqual(evidence["search_query_count"], 3)
        self.assertEqual([item["item_source_count"] for item in evidence["query_coverage"]], [3, 1, 1])
        self.assertEqual([item["title"] for item in result["source_records"][:3]], subjects)
        self.assertEqual(result["turn_plan"]["research_queries"], queries)
        self.assertFalse(evidence["merchant_product_facts_confirmed"])
        self.assertEqual(evidence["sales_verification"], "not_established")

    def test_single_product_analysis_keeps_source_checks_without_candidate_cards(self):
        result, model, _ = self.searched_chat("就分析这一把，不再找别的。",
            "silver measuring scoop 的商品页面参考 [S1]；价格、成交和供应商参数未验证。",
            intent="research", project_action="none", product_name="silver measuring scoop",
            search="web_search", query="site:ebay.com/itm silver measuring scoop",
            research_delivery="single_product_analysis", source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])
        self.assertEqual(result["answer_quality"]["quality_gate"], "non_selection_answer_present_v1")
        self.assertEqual(json.loads(model.prompts[0]["user_prompt"])["selection_contract"], {})
        self.assertEqual(result["turn_plan"]["research_delivery"], "single_product_analysis")

    def test_bilingual_research_subject_matches_title_without_repeated_snippet(self):
        subject = "银色量勺 / silver measuring scoop"
        query = "site:ebay.com/itm silver measuring scoop"
        source = [{"title": "silver measuring scoop", "url": "https://www.ebay.com/itm/123456789013",
                   "content": "Historical item-page reference. Sales and supplier facts not verified."}]
        with patch.object(SearchFixture, "results", source):
            result, _, _ = self.searched_chat("核对这个量勺的公开商品页面。",
                "候选商品 1：银色量勺\n商品页面参考 [S1]；成交和供应商参数未验证。",
                intent="research", project_action="none", product_name="银色量勺", search="web_search",
                query=query, research_queries=[{"subject": subject, "query": query}],
                source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertEqual(result["default_web_search"]["status"], "ready")
        self.assertTrue(result["answer_quality"]["accepted"], result["answer_quality"])

    def test_evidence_comparison_still_rejects_stale_cards_without_submitted_evidence(self):
        plan = plan_ai_ceo_turn(model_client=ModelFixture(decision(intent="research", project_action="current",
            read_images=False, research_delivery="evidence_comparison", listing_deferred=True)),
            message="核对已提交的成交证据。", conversation_history=[], active_listing_context=ACTIVE, has_source_assets=False)
        quality = validate_ai_ceo_answer_quality(message="样本 Item ID 155898688458，相对赢家为竹制手机支架，下一步供应商核验。",
            route="ebay_workflow", answer="候选商品 1：竹制手机支架\n候选商品 2：硅胶理线座\n成交证据不足。",
            context={"semantic_plan": plan})
        self.assertFalse(quality["accepted"])
        self.assertIn("missing_submitted_market_evidence", quality["blocked_by"])

    def test_different_planned_product_name_does_not_make_unrelated_subject_an_alias(self):
        query = "site:ebay.com/itm camera replacement strap"
        unrelated = [{"title": "Vintage Canon camera replacement strap", "url": "https://www.ebay.com/itm/123456789012",
                      "content": "Vintage Canon camera replacement strap. Sales not verified."}]
        with patch.object(SearchFixture, "results", unrelated):
            result, _, _ = self.searched_chat("核对量勺。",
                "候选商品 1：silver measuring scoop\n商品页面参考 [S1]；成交和供应商参数未验证。",
                intent="research", project_action="none", product_name="silver measuring scoop", search="web_search",
                query=query, research_queries=[{"subject": "camera replacement strap", "query": query}],
                source_mode="merchant_has_no_source", listing_deferred=True)
        self.assertFalse(result["answer_quality"]["accepted"])
        self.assertIn("research_candidate_source_mismatch", result["answer_quality"]["blocked_by"])


if __name__ == "__main__":
    unittest.main()
