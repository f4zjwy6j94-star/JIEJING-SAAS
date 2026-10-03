"""Semantic plan contracts: only the external model is replaced by a fixture."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_semantic_plan import SemanticPlanError, plan_ai_ceo_turn


class ModelFixture:
    def __init__(self, decision):
        self.decision = decision
        self.prompts = []

    def generate_text(self, **kwargs):
        self.prompts.append(kwargs)
        return {"text": json.dumps(self.decision, ensure_ascii=False), "finish_reason": "stop"}


class RawModelFixture(ModelFixture):
    def generate_text(self, **kwargs):
        self.prompts.append(kwargs)
        return {"text": self.decision, "finish_reason": "stop"}


class SequenceModelFixture(ModelFixture):
    def generate_text(self, **kwargs):
        self.prompts.append(kwargs)
        item = self.decision[min(len(self.prompts) - 1, len(self.decision) - 1)]
        if isinstance(item, Exception):
            raise item
        return {"text": json.dumps(item, ensure_ascii=False), "finish_reason": "stop"}


def decision(**changes):
    research = changes.get("intent") == "research"
    return {
        "status": "ready", "intent": "listing", "project_action": "new",
        "product_name": "银色木柄15mL量勺", "question": "", "search": "none",
        "query": "", "source_mode": "merchant_has_source", "read_images": True,
        "save_artifact": True, "candidate_count": 1, "excluded_candidates": [],
        "listing_deferred": False, "steps": ["整理商品资料", "核对缺失参数"],
        "research_delivery": "candidate_selection" if research else "none",
        "research_queries": ([{"subject": changes.get("product_name", ""), "query": changes.get("query", "")}]
                             if research and changes.get("search") == "web_search" else []),
        "product_fact_proposals": [],
        **changes,
    }


class SemanticDispatchTests(unittest.TestCase):
    def plan(self, payload=None, *, model=None, current=None, assets=True, message="处理这个商品。"):
        return plan_ai_ceo_turn(model_client=model or ModelFixture(payload), message=message,
            conversation_history=[], active_listing_context=current or {}, has_source_assets=assets)

    def test_natural_language_new_product_is_model_decision_not_punctuation(self):
        for message in ("新建一个独立商品项目：银色木柄15mL量勺", "金色那套留着，这回单独弄这把银色小勺", "Let's work on this scoop separately; keep the previous set untouched."):
            with self.subTest(message=message):
                model = ModelFixture(decision())
                plan = plan_ai_ceo_turn(model_client=model, message=message,
                    conversation_history=[], active_listing_context={"product_name": "金色8件套"},
                    has_source_assets=True)
                self.assertEqual(plan["project_action"], "new")
                self.assertEqual(plan["route"], "ebay_workflow")
                self.assertEqual(plan["planner_policy"], "backend_model_semantic_planner_v1")
                self.assertEqual(plan["workflow_target"], "listing_draft")
                self.assertFalse(plan["real_platform_writes_enabled"])
                self.assertIn(message, model.prompts[0]["user_prompt"])

    def test_model_failure_has_a_safe_typed_error_and_no_keyword_fallback(self):
        class FailedModel:
            def generate_text(self, **kwargs):
                raise TimeoutError("provider diagnostic must not be returned")
        with self.assertRaisesRegex(SemanticPlanError, "^semantic_plan_model_failed$"):
            self.plan(model=FailedModel(), message="新建一个独立商品项目：银色小勺")

    def test_model_repairs_readonly_context_conflict_with_fixed_feedback_only(self):
        invalid = decision(intent="chat", project_action="current", product_name="untrusted-model-output-marker",
                           read_images=False, save_artifact=False)
        repaired = decision(intent="research", project_action="current", read_images=False,
                            save_artifact=False, research_delivery="single_product_analysis")
        model = SequenceModelFixture([invalid, repaired])
        message = "只讨论当前商品的模拟费用，保留资料，不联网。"
        plan = self.plan(model=model, current={"product_name": "量勺"}, assets=False, message=message)
        self.assertEqual("research", plan["intent"])
        self.assertEqual("current", plan["project_action"])
        self.assertFalse(plan["save_artifact"])
        self.assertEqual(2, len(model.prompts))
        first, second = [json.loads(item["user_prompt"]) for item in model.prompts]
        self.assertEqual(message, second["merchant_message"])
        self.assertEqual(first, {k: v for k, v in second.items() if k != "plan_validation_feedback"})
        self.assertEqual("semantic_plan_non_workflow_mutation", second["plan_validation_feedback"]["code"])
        self.assertNotIn("untrusted-model-output-marker", model.prompts[1]["user_prompt"])
        self.assertEqual([45, 20], [item["timeout_seconds"] for item in model.prompts])

    def test_repair_cannot_escalate_effects_or_retry_more_than_once(self):
        invalid = decision(intent="chat", project_action="current", read_images=False, save_artifact=False)
        readonly = decision(intent="research", project_action="current", read_images=False,
                            save_artifact=False, research_delivery="single_product_analysis")
        escalations = [
            decision(read_images=False),
            {**readonly, "save_artifact": True},
            {**readonly, "read_images": True},
            decision(intent="live_action", project_action="current", read_images=False, save_artifact=False),
            decision(intent="remember_rule", project_action="none", read_images=False, save_artifact=False),
            {**readonly, "search": "web_search", "query": "scoop",
             "research_queries": [{"subject": "scoop", "query": "scoop"}]},
        ]
        for repaired in escalations:
            with self.subTest(repaired=repaired):
                model = SequenceModelFixture([invalid, repaired])
                with self.assertRaisesRegex(SemanticPlanError, "^semantic_plan_repair_effect_escalation$"):
                    self.plan(model=model, current={"product_name": "量勺"})
                self.assertEqual(2, len(model.prompts))
        repeated = SequenceModelFixture([invalid, invalid, readonly])
        with self.assertRaisesRegex(SemanticPlanError, "^semantic_plan_non_workflow_mutation$"):
            self.plan(model=repeated, current={"product_name": "量勺"})
        self.assertEqual(2, len(repeated.prompts))
        timeout = SequenceModelFixture([invalid, TimeoutError("do-not-leak-provider-detail")])
        with self.assertRaisesRegex(SemanticPlanError, "^semantic_plan_model_failed$"):
            self.plan(model=timeout, current={"product_name": "量勺"})
        self.assertEqual(2, len(timeout.prompts))

    def test_open_research_query_contract_gets_one_bounded_model_repair(self):
        valid = decision(intent="research", project_action="none", product_name="", read_images=False,
                         source_mode="merchant_has_no_source", candidate_count=2, listing_deferred=True,
                         query="eBay cable clips product", simulation_request=None,
                         search="web_search", research_queries=[{"subject": "cable clips", "query": "eBay cable clips product"}])
        for invalid in ({**valid, "research_queries": []}, {**valid, "query": "different top-level query"}):
            model = SequenceModelFixture([invalid, valid])
            plan = self.plan(model=model, assets=False, message="联网比较两种商品并保存选品报告，不新建项目。")
            self.assertEqual("none", plan["project_action"])
            self.assertTrue(plan["save_artifact"])
            self.assertEqual(valid["research_queries"], plan["research_queries"])
            self.assertEqual(2, len(model.prompts))
            feedback = json.loads(model.prompts[1]["user_prompt"])["plan_validation_feedback"]
            self.assertEqual("semantic_plan_missing_research_queries", feedback["code"])
            self.assertNotIn("different top-level query", model.prompts[1]["user_prompt"])
            self.assertEqual([45, 20], [item["timeout_seconds"] for item in model.prompts])
        for change in ({"project_action": "new", "product_name": "other"},
                       {"intent": "listing", "research_delivery": "none", "research_queries": []},
                       {"candidate_count": 5}, {"read_images": True},
                       {"excluded_candidates": ["changed exclusion"]},
                       {"source_mode": "merchant_has_source"}, {"save_artifact": False},
                       {"listing_deferred": False}):
            model = SequenceModelFixture([{**valid, "research_queries": []}, {**valid, **change}])
            with self.subTest(change=change), self.assertRaises(SemanticPlanError):
                self.plan(model=model, current={"product_name": "Old scoop"}, assets=True)
            self.assertEqual(2, len(model.prompts))
        for second, expected in (({**valid, "research_queries": []}, "semantic_plan_missing_research_queries"),
                                 (TimeoutError("untrusted provider message"), "semantic_plan_model_failed")):
            model = SequenceModelFixture([{**valid, "research_queries": []}, second, valid])
            with self.subTest(second=second), self.assertRaisesRegex(SemanticPlanError, "^" + expected + "$"):
                self.plan(model=model, assets=False)
            self.assertEqual(2, len(model.prompts))
        for invalid in ({**valid, "research_queries": [], "product_fact_proposals": [{"field": "price", "value": "1", "source_quote": "x"}]},
                        {**valid, "research_queries": [], "simulation_request": {"enabled": True, "source_quote": "x"}},
                        {**valid, "research_queries": [], "company_id": "forged"},
                        {**valid, "research_queries": [], "project_action": "current"}):
            model = SequenceModelFixture([invalid, valid])
            with self.subTest(invalid=invalid), self.assertRaises(SemanticPlanError):
                self.plan(model=model, current={"product_name": "Old scoop"}, message="x")
            self.assertEqual(1, len(model.prompts))

    def test_repair_is_not_offered_for_unknown_authority_or_invalid_fields(self):
        for invalid in (decision(company_id="forged"), decision(save_artifact="false"), None):
            with self.subTest(invalid=invalid):
                model = SequenceModelFixture([invalid, decision(read_images=False)])
                with self.assertRaises(SemanticPlanError):
                    self.plan(model=model)
                self.assertEqual(1, len(model.prompts))

    def test_strict_schema_rejects_unknown_authority_identity_types_and_bounds(self):
        invalid = [
            decision(real_platform_writes_enabled=True), decision(company_id="other-company"),
            decision(store_id="other-store"), decision(listing_project_identity={"key": "other-product"}),
            decision(status="execute"), decision(intent="publish_now"), decision(project_action="current_or_new"),
            decision(search="shell"), decision(source_mode="confirmed_by_model"),
            decision(read_images="true"), decision(save_artifact=1), decision(listing_deferred=None),
            decision(candidate_count=True), decision(candidate_count=0), decision(candidate_count=6),
            decision(candidate_count=float("nan")), decision(candidate_count=[]),
            decision(product_name=None), decision(product_name="x" * 121), decision(query="x" * 901),
            decision(question="x" * 301), decision(excluded_candidates=["x"] * 21),
            decision(excluded_candidates=[{}]), decision(steps=["x"] * 7), decision(steps=[]),
            decision(steps=[" "]), decision(steps=[False]),
            {key: value for key, value in decision().items() if key != "intent"},
            None, [], True,
        ]
        for index, payload in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(SemanticPlanError):
                self.plan(payload)

    def test_invalid_json_and_duplicate_fields_do_not_become_an_execution_plan(self):
        for text in ("not JSON", "", '{"intent": "listing"', json.dumps(decision())[:-1] + ', "intent": "listing"}'):
            with self.subTest(text=text[:30]), self.assertRaises(SemanticPlanError):
                self.plan(model=RawModelFixture(text))

    def test_live_search_requires_an_explicit_query_and_research_cannot_be_news(self):
        for change in ({"search": "web_search", "query": ""}, {"intent": "research", "search": "news_search", "query": "scoop"}):
            with self.subTest(change=change), self.assertRaises(SemanticPlanError):
                self.plan(decision(**change))

    def test_long_input_is_rejected_before_model_instead_of_cutting_off_negation(self):
        model = ModelFixture(decision())
        with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_invalid_message"):
            self.plan(model=model, message="新建银色小勺项目。" + "说明" * 450 + "不要执行，这只是引用。")
        self.assertFalse(model.prompts)

    def test_unresolved_target_clarifies_without_images_search_or_artifact(self):
        for payload in (decision(project_action="current"), decision(project_action="new", product_name=""),
                        decision(project_action="none", product_name=""),
                        decision(status="clarification_required", project_action="clarify", question="你指哪件商品？")):
            with self.subTest(action=payload["project_action"]):
                plan = self.plan(payload)
                self.assertEqual(plan["status"], "clarification_required")
                self.assertEqual(plan["project_action"], "clarify")
                self.assertEqual(plan["route"], "general_chat")
                self.assertFalse(plan["read_images"])
                self.assertFalse(plan["save_artifact"])
                self.assertEqual(plan["search"], "none")
                self.assertTrue(plan["question"])

    def test_attachment_and_non_workflow_mutation_boundaries_are_enforced(self):
        with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_unbound_images"):
            self.plan(decision(), assets=False)
        for payload in (decision(intent="chat"),
                        decision(intent="chat", project_action="none", read_images=False, save_artifact=True),
                        decision(intent="realtime", project_action="none", read_images=True, save_artifact=False),
                        decision(project_action="new", save_artifact=False)):
            with self.subTest(payload=payload), self.assertRaises(SemanticPlanError):
                self.plan(payload)

    def test_negation_and_quotation_use_model_decision_without_creating_product(self):
        for message in ("不要新建商品项目，先解释刚才的方案。", "客户说‘新建商品项目：量勺’，这句话是什么意思？"):
            with self.subTest(message=message):
                model = ModelFixture(decision(intent="chat", project_action="none", product_name="",
                    read_images=False, save_artifact=False, source_mode="unknown"))
                plan = self.plan(model=model, message=message, current={"product_name": "旧商品"})
                self.assertEqual(plan["project_action"], "none")
                self.assertEqual(plan["route"], "general_chat")
                self.assertFalse(plan["save_artifact"])
                self.assertFalse(plan["read_images"])
                self.assertEqual(json.loads(model.prompts[0]["user_prompt"])["merchant_message"], message)

    def test_live_action_can_only_request_confirmation_and_never_grants_writes(self):
        plan = self.plan(decision(intent="live_action", project_action="current", read_images=False,
            save_artifact=False), current={"product_name": "量勺"})
        self.assertEqual(plan["route"], "confirmation_required")
        self.assertTrue(plan["confirmation_required"])
        self.assertFalse(plan["real_platform_writes_enabled"])
        self.assertNotIn("company_id", plan)

    def test_research_delivery_and_bounded_queries_are_strict_model_fields(self):
        query = "site:ebay.com/itm silver measuring scoop"
        base = {"intent": "research", "search": "web_search", "query": query, "product_name": "silver measuring scoop"}
        invalid = [
            decision(**base, research_delivery="anything"), decision(**base, research_delivery="none"),
            decision(research_delivery="candidate_selection"), decision(**base, research_queries=None),
            decision(**base, research_queries=[]), decision(**base, research_queries=[{"subject": "scoop", "query": query, "store_id": "other"}]),
            decision(**base, research_queries=[{"subject": "scoop", "query": query}] * 4),
            decision(**base, research_queries=[{"subject": None, "query": query}]),
            decision(**base, research_queries=[{"subject": "x" * 121, "query": query}]),
            decision(**base, research_queries=[{"subject": "scoop", "query": ""}]),
            decision(**base, research_queries=[{"subject": "scoop", "query": "x" * 901}]),
            decision(**base, research_queries=[{"subject": "scoop", "query": "different query"}]),
            decision(**base, research_delivery="single_product_analysis", research_queries=[{"subject": "", "query": query}]),
            decision(research_queries=[{"subject": "scoop", "query": query}]),
        ]
        for index, payload in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(SemanticPlanError):
                self.plan(payload)
        plan = self.plan(decision(**base))
        self.assertEqual(plan["research_delivery"], "candidate_selection")
        self.assertEqual(plan["research_queries"], [{"subject": "silver measuring scoop", "query": query}])

    def test_text_facts_remain_model_proposals_with_current_message_quotes(self):
        message = "新建银色木柄量勺，材质304不锈钢和实木；货号SPOON15；尺寸18x4x2厘米；净重42克。"
        proposals = [
            {"field": "material", "value": "304不锈钢和实木", "source_quote": "材质304不锈钢和实木"},
            {"field": "supplier_item_number", "value": "SPOON15", "source_quote": "货号SPOON15"},
            {"field": "product_dimensions_cm", "value": "18x4x2", "source_quote": "尺寸18x4x2厘米"},
            {"field": "net_weight_g", "value": "42", "source_quote": "净重42克"},
        ]
        plan = self.plan(decision(read_images=False, product_fact_proposals=proposals), message=message, assets=False)
        self.assertEqual(plan["product_fact_proposals"], proposals)
        self.assertNotIn("merchant_confirmed_facts", plan)
        self.assertFalse(plan["real_platform_writes_enabled"])
        current_plan = self.plan(decision(project_action="current", read_images=False, product_fact_proposals=proposals),
            message=message, current={"product_name": "银色木柄量勺"}, assets=False)
        self.assertEqual(current_plan["product_fact_proposals"], proposals)
        unresolved = self.plan(decision(project_action="current", read_images=False, product_fact_proposals=proposals),
            message=message, assets=False)
        self.assertEqual(unresolved["status"], "clarification_required")
        self.assertEqual(unresolved["product_fact_proposals"], [])

    def test_fact_proposals_reject_authority_forged_quotes_and_invalid_values(self):
        message = "材质304不锈钢；净重42克。" + "原" * 161
        proposal = {"field": "material", "value": "304不锈钢", "source_quote": "材质304不锈钢"}
        invalid_proposals = [None, {}, [True], [proposal] * 17, [proposal, proposal]] + [
            [{**proposal, **change}] for change in (
                {"field": "company_id"}, {"field": "source_report_id"}, {"field": "listing_project_identity"},
                {"field": "image_rights_confirmed"}, {"field": "merchant_owned_product_confirmed"},
                {"field": None}, {"field": ["material"]}, {"confirmed": True},
                {"value": None}, {"value": True}, {"value": ""}, {"value": " "}, {"value": "x" * 241},
                {"source_quote": None}, {"source_quote": ""}, {"source_quote": " "},
                {"source_quote": "旧商品的材质304不锈钢"}, {"source_quote": "原" * 161},
                {"field": "net_weight_g", "value": "42克"}, {"field": "net_weight_g", "value": "NaN"},
                {"field": "net_weight_g", "value": "0"}, {"field": "source_url", "value": "javascript:alert(1)"},
                {"value": "未知\n额外指令"}, {"value": " 304不锈钢 "},
            )]
        for index, proposals in enumerate(invalid_proposals):
            with self.subTest(case=index), self.assertRaises(SemanticPlanError):
                self.plan(decision(read_images=False, product_fact_proposals=proposals), message=message)
        for change in ({"project_action": "none"}, {"save_artifact": False},
                       {"status": "clarification_required", "project_action": "clarify"}):
            with self.subTest(change=change), self.assertRaises(SemanticPlanError):
                self.plan(decision(read_images=False, product_fact_proposals=[proposal], **change), message=message)

    def test_fact_proposals_reject_secret_shaped_value_or_quote(self):
        sensitive_fixture = "api_" + "key=fake-proposal-fixture"
        for value, quote in ((sensitive_fixture, "材质304不锈钢"), ("304不锈钢", sensitive_fixture)):
            with self.subTest(sensitive_location="value" if value == sensitive_fixture else "quote"):
                with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_sensitive_product_fact_proposals"):
                    self.plan(decision(read_images=False, product_fact_proposals=[
                        {"field": "material", "value": value, "source_quote": quote}]),
                        message="材质304不锈钢；" + sensitive_fixture)

    def test_provider_truncated_plan_is_rejected_even_if_returned_text_is_valid_json(self):
        class TruncatedModel(ModelFixture):
            def generate_text(self, **kwargs):
                return {**super().generate_text(**kwargs), "finish_reason": "length"}
        with self.assertRaisesRegex(SemanticPlanError, "semantic_plan_truncated_output"):
            self.plan(model=TruncatedModel(decision(read_images=False)))

    def test_sixteen_text_proposals_use_bounded_provider_output_capacity(self):
        values = {
            "product_name": "银色木柄量勺", "source_url": "https://supplier.example/scoop", "sku": "SPOON15",
            "brand": "Unbranded", "mpn": "S15", "condition": "New", "supplier_item_number": "SPOON15",
            "supplier_brand": "供应商甲", "material": "304不锈钢和实木", "product_dimensions_cm": "18x4x2",
            "net_weight_g": "42", "product_origin": "中国", "craft": "金属冲压和木柄组装", "style": "简约",
            "packaging_type": "纸盒", "included_items": "量勺一把",
        }
        message = "新建这个量勺项目；" + "；".join(f"{key}={value}" for key, value in values.items())
        proposals = [{"field": key, "value": value, "source_quote": f"{key}={value}"} for key, value in values.items()]
        model = ModelFixture(decision(read_images=False, product_fact_proposals=proposals))
        plan = self.plan(model=model, message=message, assets=False)
        self.assertEqual(plan["product_fact_proposals"], proposals)
        self.assertEqual(model.prompts[0]["max_output_tokens"], 4096)


if __name__ == "__main__":
    unittest.main()
