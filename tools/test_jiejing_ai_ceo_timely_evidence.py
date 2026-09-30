"""Offline call-path regressions for open-domain, time-sensitive answers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiejing_saas import ai_ceo_chat as chat
from jiejing_saas.operations_metering import MeteredModelClient
from jiejing_saas.repository import SaaSRepository


NOW = "2026-09-29T02:20:00+00:00"
HISTORY = [{"user_text": "帮我生成平板支架Listing", "assistant_text": "请补充材质、颜色和尺寸。",
            "route": chat.AI_CEO_ROUTE_EBAY_WORKFLOW}]


class RepositoryBoundary:
    """An empty tenant read interface; no persisted/live merchant state involved."""
    def get_store_for_company(self, **kwargs):
        return {"store_id": "test-store", "platform": "ebay"}
    def list_platform_data_packets(self, **kwargs):
        return []
    def list_confirmations(self, **kwargs):
        return []
    def list_tasks(self, **kwargs):
        return []
    def list_reports(self, **kwargs):
        return []


class ModelBoundary:
    name = "offline-fixture"
    def __init__(self, answer, audit=None):
        self.answer, self.audit, self.calls = answer, audit, []
    def generate_text(self, **kwargs):
        self.calls.append(kwargs)
        text = self.answer
        if "timely_evidence_review_v1" in kwargs.get("system_prompt", ""):
            text = json.dumps(self.audit or {})
        if kwargs.get("on_text_delta"):
            kwargs["on_text_delta"](text)
        return {"text": text, "finish_reason": "stop", "_usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}}


class SearchResponse:
    def __init__(self, records):
        self.records = records
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None
    def read(self, *args):
        if isinstance(self.records, str):
            return self.records.encode("utf-8")
        return json.dumps({"results": self.records}).encode("utf-8")


class TimelyEvidenceTests(unittest.TestCase):
    @staticmethod
    def supporting_review(answer, excerpt):
        return {"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                "conflicts": [], "claims": [{"text": answer, "source_id": "S1", "excerpt": excerpt}]}

    def run_chat(self, question, records, answer, *, history=None, audit=None, fail_search=False, now=NOW,
                 synthesis=True, fast=False, builtin_rss=""):
        model, deltas, requests = MeteredModelClient(ModelBoundary(answer, audit)), [], []
        def http(request, timeout):
            requests.append(request.full_url)
            if fail_search:
                raise OSError("offline search failure")
            if builtin_rss:
                self.assertTrue(request.full_url.startswith("https://news.google.com/rss/search?"))
                return SearchResponse(builtin_rss)
            self.assertEqual(request.full_url, "https://search.invalid/search")
            return SearchResponse(records)
        with patch.dict("os.environ", {
            "JIEJING_SEARCH_ENDPOINT": "https://search.invalid/search",
            "JIEJING_SEARCH_API_KEY": "" if builtin_rss else "offline-fixture-value",
            "TAVILY_API_KEY": "",
            "JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED": "true",
            "JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED": "true",
            "JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED": str(synthesis).lower(),
            "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": "false",
        }), patch("urllib.request.urlopen", side_effect=http), patch.object(chat, "now_iso", return_value=now):
            kwargs = {"repository": RepositoryBoundary(), "company_id": "test-company", "store_id": "test-store",
                      "user_id": "test-user", "message": question, "conversation_history": history,
                      "client_timezone": "Asia/Shanghai"}
            result = (chat.run_ai_ceo_fast_turn(**kwargs) if fast else
                      chat.run_ai_ceo_chat(**kwargs, model_client=model, on_text_delta=deltas.append))
        return result, deltas, model, requests

    def test_independent_current_questions_use_public_research_after_product_chat(self):
        for question in ("微软现任CEO是谁", "微软CEO是谁", "Example公司CEO是谁", "英国首相是谁",
                         "2026年9月29日微软发布了哪些公告", "ChatGPT Plus现在多少钱", "最近有什么科技新闻",
                         "美元兑人民币汇率是多少", "某城市本周有哪些新展览？"):
            with self.subTest(question=question):
                plan = chat.build_ai_ceo_turn_plan(question, conversation_history=HISTORY)
                self.assertEqual(plan["route"], chat.AI_CEO_ROUTE_EXTERNAL_REALTIME)
                self.assertTrue(plan["freshness_required"])
                self.assertNotIn("ebay_public_research", plan["required_tools"])

    def test_no_source_selection_reaches_candidate_analysis_not_news_fast_answer(self):
        question = (
            "我现在没有货源，想从零开始做 eBay 美国站。请帮我做一次联网选品调研："
            "筛选轻小、不带电、非易碎、尽量降低侵权风险的商品，比较 3 个具体候选，推荐 1 个优先找货的方向。"
            "请说明需求依据、竞争情况、参考售价范围、物流和退货风险，并给出来源链接及资料日期；"
            "没有可靠成交数据就明确说，不能编造销量或宣称它是最畅销商品。"
            "我的采购预算、供应商、真实成本、材质规格和发货地还未确定，找到货源后我再补充。"
            "现在只做调研和找货清单，不生成虚构商品事实，不发布、不采购，也不要沿用旧平板支架或书签项目。"
        )
        records = [{"title": "Product research guide", "url": "https://example.test/research",
                    "content": "Compare competition, shipping costs and product claims before sourcing."}]
        answer = "\n".join(
            f"候选商品 {index}：{name}\n推荐度评分：{85-index}/100\n"
            "调研依据：[S1]仅提供筛选方法，未提供该商品的销量或价格。资料日期未标注。\n"
            "成交证据不足，竞争和参考售价待核实。材质、尺寸、重量、成本和发货地均未知。\n"
            "找货时应核对运输损坏、规格不符和退货费用风险。"
            for index, name in enumerate(("线缆标签", "行李拉链固定夹", "桌面线缆整理夹"), 1)
        ) + "\n最终推荐：线缆标签，作为优先找货的待验证方向，不是最畅销结论。"
        result, _, model, requests = self.run_chat(question, records, answer)
        self.assertTrue(requests)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(result["status"], "model_answered_non_live")
        self.assertEqual(result["route"], chat.AI_CEO_ROUTE_EBAY_WORKFLOW)
        self.assertEqual(result["answer_quality"]["quality_gate"], "ebay_product_selection_answer_v2")
        self.assertTrue(result["answer_quality"]["accepted"])
        self.assertEqual(result["answer_quality"]["candidate_count"], 3)
        self.assertEqual(result["turn_plan"]["source_mode"], "merchant_has_no_source")
        self.assertNotEqual(result["route_label"], "实时搜索")
        self.assertFalse(result["frontend_gets_model_api_key"])
        fast, _, fast_model, fast_requests = self.run_chat(question, records, answer, fast=True)
        self.assertIsNone(fast, "Trial AI must continue into the model-backed selection path")
        self.assertEqual(fast_requests, [])
        self.assertEqual(fast_model.calls, [])

    def test_undated_weather_never_streams_or_becomes_current_fact(self):
        records = [{"title": "Shanghai weather", "url": "https://weather.example/shanghai",
                    "content": "Shanghai temperature is 31 C and sunny.", "captured_at": NOW}]
        answer = "今天上海气温31度，天气晴朗[S1]。" + "这是今天的天气实况，可以据此安排出行。" * 6
        result, deltas, model, requests = self.run_chat("上海今天的天气怎么样", records, answer)
        self.assertTrue(requests, "The real planner/search/adapter path must perform the lookup")
        self.assertNotIn("31", "".join(deltas))
        self.assertNotIn("31", result["answer"])
        self.assertIn("未核实", result["answer"])
        self.assertTrue(result["answer_stream_buffered"])

    def test_short_dated_weather_answer_is_usable_after_evidence_review(self):
        excerpt = "2026-09-29 上海气温24°C，小雨。"
        answer = "2026-09-29 上海气温24°C，小雨[S1]。"
        records = [{"title": "上海天气", "url": "https://weather.example/shanghai", "content": excerpt}]
        audit = {"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                 "conflicts": [], "claims": [{"text": answer, "source_id": "S1", "excerpt": excerpt}]}
        result, deltas, model, requests = self.run_chat("上海今天的天气怎么样", records, answer, audit=audit)
        self.assertEqual(result["answer"], answer)
        self.assertTrue(result["temporal_evidence_quality"]["accepted"])
        self.assertTrue(result["answer_stream_buffered"])
        self.assertEqual(deltas, [])
        self.assertEqual(len(model.calls), 2, "One synthesis and one bounded review; no length-padding retry")
        self.assertEqual(model.usage_summary(), {"request_count": 2, "input_tokens": 160,
                                               "output_tokens": 40, "total_tokens": 200})

    def test_generic_search_query_preserves_entity_and_anchors_requested_date(self):
        with patch.object(chat, "now_iso", return_value=NOW):
            for kind, question, date_text in (("web_search", "ChatGPT Plus现在多少钱", "2026-09-29"),
                                             ("weather", "上海明天天气怎么样", "2026-09-30"),
                                             ("news_search", "最近有什么科技新闻", "2026-09-29")):
                query = chat._realtime_search_query(kind=kind, message=question)
                self.assertIn(question, query)
                self.assertIn(date_text, query)
                self.assertIn("primary", query)

    def test_explicit_page_update_date_survives_provider_and_prompt(self):
        answer = "截至2026-09-29，Example Pro套餐月费为20美元[S1]。"
        excerpt = "Example Pro monthly price is 20 USD."
        records = [{"title": "Pricing", "url": "https://example.com/pricing", "content": excerpt,
                    "updated_at": "2026-09-29T01:00:00Z"}]
        audit = {"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                 "conflicts": [], "claims": [{"text": answer, "source_id": "S1", "excerpt": excerpt}]}
        result, _, model, _ = self.run_chat("Example Pro现在多少钱", records, answer, audit=audit)
        self.assertEqual(result["answer"], answer)
        self.assertEqual(result["source_records"][0]["updated_at"], records[0]["updated_at"])
        prompt = json.loads(model.calls[0]["user_prompt"])
        self.assertEqual(prompt["temporal_evidence_contract"]["user_calendar_date"], "2026-09-29")

    def test_chinese_prefixed_calendar_date_respects_user_day_at_utc_boundary(self):
        excerpt = "截至2026年9月29日，上海气温24°C，小雨。"
        answer = "截至2026年9月29日，上海气温24°C，小雨[S1]。"
        records = [{"title": "上海天气", "url": "https://weather.example/shanghai", "content": excerpt}]
        audit = {"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                 "conflicts": [], "claims": [{"text": answer, "source_id": "S1", "excerpt": excerpt}]}
        result, _, _, _ = self.run_chat("上海今天的天气怎么样", records, answer,
                                       audit=audit, now="2026-09-28T18:20:00+00:00")
        self.assertEqual(result["answer"], answer)

    def test_common_knowledge_and_emotional_chat_stream_without_lookup(self):
        for question in ("光为什么会折射", "汇率是什么", "天气预报的原理是什么", "我今天心情很不好",
                         "请比较量子纠缠和经典相关性的本质区别，并解释贝尔不等式的含义"):
            with self.subTest(question=question):
                answer = "我会直接回应这个问题，不引用不存在的实时资料。"
                result, deltas, model, requests = self.run_chat(question, [], answer, history=HISTORY)
                self.assertEqual(result["route"], chat.AI_CEO_ROUTE_GENERAL)
                self.assertEqual(requests, [])
                self.assertEqual(deltas, [answer])

    def test_no_model_fast_path_does_not_launder_undated_weather_snippet(self):
        records = [{"title": "Weather", "url": "https://weather.example/shanghai", "content": "Shanghai is 31 C"}]
        result, _, model, _ = self.run_chat("上海今天天气", records, "unused", synthesis=False, fast=True)
        self.assertNotIn("31", result["answer"])
        self.assertIn("未核实", result["answer"])
        self.assertEqual(model.usage_summary()["request_count"], 0)

    def test_dated_nonfinancial_and_fx_facts_remain_answerable(self):
        cases = [
            ("今天美元兑人民币汇率是多少", "2026-09-29，参考汇率为1美元兑7.10人民币。"),
            ("最近有什么科技新闻", "2026-09-29，某研究团队公布了新的光学实验结果。"),
            ("Example公司现任CEO是谁", "截至2026-09-29，Example公司的CEO是林某。"),
        ]
        for question, excerpt in cases:
            with self.subTest(question=question):
                answer = excerpt[:-1] + "[S1]。"
                records = [{"title": "公开资料", "url": "https://example.com/current", "content": excerpt}]
                result, deltas, model, requests = self.run_chat(question, records, answer,
                    history=HISTORY, audit=self.supporting_review(answer, excerpt))
                self.assertEqual(result["answer"], answer)
                self.assertEqual(result["route"], chat.AI_CEO_ROUTE_EXTERNAL_REALTIME)
                self.assertEqual(deltas, [])
                self.assertEqual(model.usage_summary()["request_count"], 2)
                self.assertFalse(result["frontend_gets_model_api_key"])

    def test_stale_missing_and_future_content_dates_cannot_be_replaced_by_capture(self):
        for metadata in ({}, {"published_at": "2024-09-29"}, {"published_at": "2026-09-30T01:00:00Z"},
                         {"published_at": "not-a-date"}):
            with self.subTest(metadata=metadata):
                records = [{"title": "价格", "url": "https://example.com/2026/09/29/pricing",
                            "content": "Example Pro costs 99 USD", "captured_at": NOW, **metadata}]
                result, deltas, model, _ = self.run_chat("Example Pro现在多少钱", records,
                    "截至2026-09-29，Example Pro月费99美元[S1]。")
                self.assertIn("未核实", result["answer"])
                self.assertNotIn("99", result["answer"])
                self.assertEqual(deltas, [])
                self.assertEqual(model.usage_summary()["request_count"], 0)

    def test_search_failure_cannot_fall_back_to_model_memory(self):
        result, deltas, model, _ = self.run_chat("Example公司现任CEO是谁", [], "当前CEO是虚构人", fail_search=True)
        self.assertEqual(result["status"], "external_data_source_required")
        self.assertNotIn("虚构人", result["answer"])
        self.assertEqual(deltas, [])
        self.assertEqual(model.usage_summary()["request_count"], 0)

    def test_review_conflicts_and_wrong_entity_or_date_never_reach_user(self):
        excerpt = "2026-09-29，北京气温24°C，小雨。"
        answer = "2026-09-29，上海气温24°C，小雨[S1]。"
        record = {"title": "天气", "url": "https://weather.example/beijing", "content": excerpt}
        for field, value in (("answers_question", False), ("date_scope_matches", False),
                             ("all_claims_supported", False), ("conflicts", ["来源给出的城市或天气不同"])):
            with self.subTest(field=field):
                audit = {**self.supporting_review(answer, excerpt), field: value}
                result, deltas, _, _ = self.run_chat("上海今天天气怎么样", [record], answer, audit=audit)
                self.assertIn("未核实", result["answer"])
                self.assertNotIn("24", result["answer"])
                self.assertEqual(deltas, [])
                if field == "conflicts":
                    self.assertIn("冲突", result["answer"])

    def test_review_json_cannot_invent_evidence_citations_or_numbers(self):
        excerpt = "2026-09-29，Example Pro月费20美元。"
        answer = "2026-09-29，Example Pro月费20美元[S1]。"
        records = [{"title": "定价", "url": "https://example.com/pricing", "content": excerpt}]
        cases = [
            ({"excerpt": "2026-09-29，不存在于来源中的完整摘录。"}, answer),
            ({"source_id": "S99"}, answer),
            ({}, answer.replace("月费20", "月费99")),
            ({"text": "不存在于候选回答中的句子[S1]。"}, answer),
        ]
        for overrides, candidate in cases:
            with self.subTest(overrides=overrides, candidate=candidate):
                audit = self.supporting_review(candidate, excerpt)
                audit["claims"][0].update(overrides)
                result, deltas, _, _ = self.run_chat("Example Pro现在多少钱", records, candidate, audit=audit)
                self.assertIn("未核实", result["answer"])
                self.assertNotEqual(result["answer"], candidate)
                self.assertEqual(deltas, [])

    def test_unreviewed_sentence_and_unknown_citation_are_rejected(self):
        excerpt = "2026-09-29，Example Pro月费20美元。"
        answer = "2026-09-29，Example Pro月费20美元[S1]。"
        records = [{"title": "价格", "url": "https://example.com/pricing", "content": excerpt}]
        for candidate in (answer + "还保证永久免费升级。", answer.replace("S1", "S99")):
            result, deltas, _, _ = self.run_chat("Example Pro现在多少钱", records, candidate,
                audit=self.supporting_review(answer, excerpt))
            self.assertIn("未核实", result["answer"])
            self.assertEqual(deltas, [])

    def test_malformed_or_unavailable_review_fails_closed(self):
        excerpt = "2026-09-29，Example Pro月费20美元。"
        answer = "2026-09-29，Example Pro月费20美元[S1]。"
        records = [{"title": "价格", "url": "https://example.com/pricing", "content": excerpt}]
        for audit in ({}, "not a review object", TimeoutError("offline review timeout")):
            result, deltas, model, _ = self.run_chat("Example Pro现在多少钱", records, answer, audit=audit)
            self.assertIn("未核实", result["answer"])
            self.assertEqual(deltas, [])
            self.assertEqual(model.usage_summary()["request_count"], 2)

    def test_product_fact_followups_keep_workflow(self):
        for message in ("铝合金，银色，15×12厘米", "售价20美元", "是的", "第三个为什么显示一半？"):
            self.assertEqual(chat.build_ai_ceo_turn_plan(message, conversation_history=HISTORY)["route"],
                             chat.AI_CEO_ROUTE_EBAY_WORKFLOW)

    def test_local_clock_uses_no_model_or_public_search(self):
        result, deltas, model, requests = self.run_chat("今天几号", [], "unused")
        self.assertEqual(result["status"], "local_clock_answered")
        self.assertEqual(result["route"], chat.AI_CEO_ROUTE_GENERAL)
        self.assertEqual(model.usage_summary()["request_count"], 0)
        self.assertEqual(requests, [])

    def test_clock_shortcut_is_standalone_and_frontend_backend_agree(self):
        cases = {
            "今天几号": "date", "今天是几号？": "date", "今天星期几": "date",
            "请问今天周几？": "date", "你好，请告诉我今天的日期是什么。": "date",
            "今天几号你都不知道？": "date", "今天日期": "date",
            "What is today's date?": "date", "Current date": "date",
            "Please tell me the current date, please.": "date",
            "现在几点": "time", "请问现在几点了？": "time", "北京时间": "time",
            "北京时间现在是几点钟？": "time", "当前时间": "time",
            "What time is it?": "time", "What's the current time?": "time",
            "Please tell me current time, please.": "time",
            "不要填写今天日期": "", "不要回答今天几号，继续调研量勺": "",
            "修订报告，日期未知就写未验证，不要填写今天日期。": "",
            "生成 Listing，检索日期按北京时间记录。": "",
            "调研 eBay 量勺，当前时间不是成交日期。": "",
            "请发布这个商品，北京时间为准。": "",
            "翻译：今天几号？": "", "请解释 current date 在 SQL 中的含义": "",
            'Translate "what time is it" to Chinese.': "", '"今天几号"': "",
            "今天几号，另外帮我修改 Listing": "", "今天几号？还有天气怎么样？": "",
            "北京时间今天纳斯达克收盘多少点": "",
            "What time does the market close?": "",
            "What time is it and what is the weather?": "",
            "Explain the current date format in this file.": "",
            "Preserve the source date, do not replace it with today's date.": "",
            "今天日期" + " " * 1200 + "只是报告字段，不要报时，继续修订报告。": "",
        }
        source = (Path(__file__).resolve().parents[1] / "app.js").read_text(encoding="utf-8")
        start = source.index("function classifySaasLocalClockRequest")
        end = source.index("async function hydrateSaasCeoCommandFromBackend", start)
        script = source[start:end] + "\nconst queries = " + json.dumps(list(cases), ensure_ascii=False) + ";\n"
        script += "console.log(JSON.stringify(queries.map(q => ({ kind: classifySaasLocalClockRequest(q), answer: buildSaasLocalClockAnswer(q) }))));"
        process = subprocess.run(["node", "-"], input=script, text=True, encoding="utf-8", capture_output=True, check=True)
        frontend = json.loads(process.stdout)
        for (question, expected), browser in zip(cases.items(), frontend, strict=True):
            with self.subTest(question=question):
                self.assertEqual(expected, browser["kind"])
                self.assertEqual(expected, chat._classify_local_clock_request(question))
                if not expected:
                    self.assertIsNone(browser["answer"], "An instruction containing clock words must reach the normal task path")
                    continue
                self.assertEqual("local_clock_answered", browser["answer"]["status"])
                result, _, model, requests = self.run_chat(question, [], "unused", history=HISTORY, fast=True)
                self.assertEqual("local_clock_answered", result["status"])
                self.assertEqual(chat.AI_CEO_ROUTE_GENERAL, result["route"])
                self.assertEqual(0, model.usage_summary()["request_count"])
                self.assertEqual([], requests)

    def test_lookup_then_translation_still_gets_temporal_evidence(self):
        records = [{"title": "Price", "url": "https://example.com/pricing", "content": "Example Pro price is 999 USD."}]
        result, deltas, model, requests = self.run_chat("查一下今天的Example Pro价格并翻译成英文", records, "The price is $999.")
        self.assertTrue(requests)
        self.assertEqual(model.usage_summary()["request_count"], 0)
        self.assertNotIn("999", result["answer"])
        plan = chat.build_ai_ceo_turn_plan("翻译：Example Pro现在多少钱")
        self.assertEqual(plan["route"], chat.AI_CEO_ROUTE_GENERAL)

    def test_fact_answer_with_nonfactual_courtesy_is_not_rejected(self):
        excerpt = "2026-09-29，Example Pro月费20美元。"
        fact = "2026-09-29，Example Pro月费20美元[S1]。"
        answer = fact + "\n请以官方页面的最新信息为准。"
        records = [{"title": "定价", "url": "https://example.com/pricing", "content": excerpt}]
        result, _, _, _ = self.run_chat("Example Pro现在多少钱", records, answer,
                                       audit=self.supporting_review(fact, excerpt))
        self.assertEqual(result["answer"], answer)

    def test_two_dated_news_items_are_both_reviewed(self):
        excerpts = ["2026-09-29，研究团队发布了光学实验结果。", "2026-09-28，另一团队发布了新的论文。"]
        records = [{"title": "News", "url": f"https://example.com/news/{index}", "content": excerpt}
                   for index, excerpt in enumerate(excerpts)]
        facts = [f"{excerpt[:-1]}[S{index + 1}]。" for index, excerpt in enumerate(excerpts)]
        answer = "\n".join(facts)
        audit = {"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                 "conflicts": [], "claims": [{"text": fact, "source_id": f"S{index+1}", "excerpt": excerpts[index]}
                                              for index, fact in enumerate(facts)]}
        result, _, model, _ = self.run_chat("最近有什么科技新闻", records, answer, audit=audit)
        self.assertEqual(result["answer"], answer)
        review = json.loads(model.calls[-1]["user_prompt"])
        self.assertEqual(len(review["source_records"]), 2)

    def test_builtin_rss_publication_date_reaches_same_evidence_boundary(self):
        excerpt = "某研究团队公布了新的光学实验结果。"
        answer = "2026-09-29，某研究团队公布了新的光学实验结果[S1]。"
        rss = ("<rss><channel><item><title>研究公告</title><link>https://example.com/news</link>"
               "<description>" + excerpt + "</description><pubDate>Tue, 29 Sep 2026 01:00:00 GMT</pubDate>"
               "</item></channel></rss>")
        result, deltas, model, _ = self.run_chat("最近有什么科技新闻", [], answer, builtin_rss=rss,
                                                audit=self.supporting_review(answer, excerpt))
        self.assertEqual(result["answer"], answer)
        self.assertEqual(result["realtime_search"]["provider"], "builtin_public_news")
        self.assertIn("29 Sep 2026", result["source_records"][0]["published_at"])
        self.assertEqual(deltas, [])
        self.assertEqual(model.usage_summary()["request_count"], 2)

    def test_claim_date_must_come_from_its_evidence_not_search_capture(self):
        excerpt = "2026-09-01，Example Pro月费20美元。"
        records = [{"title": "价格", "url": "https://example.com/pricing", "content": excerpt, "captured_at": NOW}]
        forged = "截至2026-09-29，Example Pro月费20美元[S1]。"
        result, _, _, _ = self.run_chat("Example Pro现在多少钱", records, forged,
                                       audit=self.supporting_review(forged, excerpt))
        self.assertIn("未核实", result["answer"])
        self.assertIn("claim_date_not_in_evidence", result["temporal_evidence_quality"]["blocked_by"])
        dated = "截至2026-09-01，Example Pro月费20美元[S1]。"
        result, _, _, _ = self.run_chat("Example Pro现在多少钱", records, dated,
                                       audit=self.supporting_review(dated, excerpt))
        self.assertEqual(result["answer"], dated)

    def test_timely_platform_facts_keep_workflow_and_receive_same_evidence_gate(self):
        question = "帮我查一下eBay今天的成交费是多少"
        records = [{"title": "Fees", "url": "https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees",
                    "content": "The final value fee is 99%."}]
        answer = "今天eBay成交费为99%[S1]。" + "按这个比例计算平台费用即可。" * 8
        for fast in (False, True):
            result, deltas, model, requests = self.run_chat(question, records, answer,
                                                           fast=fast, synthesis=not fast)
            self.assertEqual(result["route"], chat.AI_CEO_ROUTE_EBAY_WORKFLOW)
            self.assertNotIn("99", result["answer"])
            self.assertEqual(deltas, [])
            self.assertEqual(model.usage_summary()["request_count"], 0)
            self.assertTrue(requests)

    def test_two_provider_calls_still_settle_one_trial_turn(self):
        excerpt = "2026-09-29，Example Pro月费20美元。"
        answer = "2026-09-29，Example Pro月费20美元[S1]。"
        records = [{"title": "价格", "url": "https://example.com/pricing", "content": excerpt}]
        _, _, model, _ = self.run_chat("Example Pro现在多少钱", records, answer,
                                       audit=self.supporting_review(answer, excerpt))
        self.assertEqual(model.usage_summary()["request_count"], 2)
        with tempfile.TemporaryDirectory(prefix="jiejing-timely-quota-", ignore_cleanup_errors=True) as directory:
            repository = SaaSRepository(Path(directory) / "test.sqlite")
            account = repository.create_user_with_company(email="timely-quota@local.invalid",
                password="timely-quota-fixture", company_name="Temporal test")
            company = account["company"]["company_id"]
            period = "a" * 64
            reservation = repository.reserve_platform_model_trial_slot(company_id=company, period_key=period,
                historical_used=0, limit=20, route_scope="merchant_ceo_chat")
            settled = repository.settle_platform_model_trial_reservation(company_id=company,
                reservation_id=reservation["reservation_id"], request_count=model.usage_summary()["request_count"])
            self.assertEqual(settled["provider_request_count"], 2)
            self.assertEqual(settled["status"], "consumed")
            self.assertEqual(repository.platform_model_trial_reservation_usage(
                company_id=company, period_key=period)["reservation_used"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
