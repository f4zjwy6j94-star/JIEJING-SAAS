#!/usr/bin/env python3
"""Supplier-intake failure and rehearsal boundaries; local data, no network."""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository
from jiejing_saas.ai_ceo_chat import (
    build_ai_ceo_chat_prompts, build_ai_ceo_turn_plan, run_ai_ceo_chat, validate_ai_ceo_answer_quality,
)
from tools.test_jiejing_ai_ceo_answer_quality_gate import MinimalRepository, SequenceModel


PRODUCT = "不锈钢厨房量勺／量杯套装"
IDENTITY = {"key": "project-supplier-rehearsal", "source_report_id": "report-original", "candidate_id": "candidate_1"}
REHEARSAL_MESSAGE = (
    f"继续当前项目。目标商品：{PRODUCT}。现在改为明确的模拟演练："
    "请生成一组仅用于内部 Listing 和素材流程的模拟商品规格。"
    "所有数值明确属于模拟演练资料，不是供应商参数，不代表真实库存或发货承诺。"
    "不要访问1688链接，不要联网或重新选品，不新建项目；"
    "不要声称读取了供应商资料，不把模拟值标成来源已确认。"
    "保留模拟标记，可用于内部待核对草稿，但禁止保存eBay草稿、正式发布、采购或付款。"
)
REHEARSAL_ANSWER = """### 模拟演练 · 商品规格表
以下数值全部为模拟演练资料，不是供应商参数。
| 字段 | 模拟演练值 |
|---|---|
| 商品状态 | 全新（New）— 演练值，待实物核验 |
| 材质 | 18/8 不锈钢 — 演练值，待供应商确认 |
| 包装重量 | 约 380 g — 演练值 |
| 包装尺寸 | 约 22 × 12 × 5 cm — 演练值 |
| 建议售价 | 约 $12.99 — 演练值 |
禁止保存 eBay 草稿、正式发布、采购或付款。
"""
SPEC_REVISION_MESSAGE = (
    "继续当前量勺／量杯项目，不新建项目、不重新选品、不联网。请修订刚才的商品规格表，"
    "明确作为受控处理演练，仅供内部 Listing 与素材流程测试，所有规格和数值都不是供应商参数。"
    f"目标商品：{PRODUCT}。沿用8件套、净重320g、包装重量380g、包装尺寸22×12×5cm；"
    "商品状态用New，材质用Stainless Steel。请以字段和受控处理演练值两列表格列出。"
    "真实发货地、供应商品牌、图片授权、食品接触认证仍未验证，不要编造成已确认。"
    "禁止保存eBay草稿、正式发布、采购或付款。"
)


class SupplierIntakeRehearsalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-supplier-rehearsal-")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(gc.collect)
        self.repository = SaaSRepository(Path(self.temp.name) / "test.sqlite")

    def save(self, message: str, answer: str, **extra: object) -> dict:
        task = self.repository.create_task(
            company_id="test-company", store_id="test-store", user_id="test-user",
            task_type="ai_ceo.chat", title="Supplier intake test", input_data={"message": message},
        )
        saved = self.repository.save_ai_ceo_market_research_report(
            task=task, message=message,
            chat={"answer": answer, "route": "ebay_workflow", "status": "model_answered", **extra},
            listing_project_identity=IDENTITY, active_listing_product_name=PRODUCT,
        )
        self.assertIsNotNone(saved)
        return saved["report"]

    def test_forbidden_publish_rehearsal_is_saved_as_simulation_not_real_facts(self) -> None:
        report = self.save(REHEARSAL_MESSAGE, REHEARSAL_ANSWER)
        packet = report["merchant_product_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertEqual(packet["fact_scope"], "simulation_rehearsal")
        self.assertIn("simulation_only_product_facts", packet["blocked_by"])
        self.assertFalse(packet["source_confirmed_facts"])
        self.assertNotIn("material", packet["merchant_confirmed_facts"])
        self.assertFalse(packet["listing_readiness"]["ready_for_real_publish"])
        self.assertEqual(report["listing_project_identity"], IDENTITY)

    def test_existing_product_spec_revision_is_not_forced_into_product_selection(self) -> None:
        message = (
            "继续当前量勺／量杯项目，不新建项目、不重新选品、不联网。"
            "请修订刚才的商品规格表，明确作为模拟演练，仅供内部 Listing 与素材流程测试。"
            f"目标商品：{PRODUCT}。禁止保存eBay草稿、正式发布、采购或付款。"
        )
        quality = validate_ai_ceo_answer_quality(
            message=message, route="ebay_workflow", answer=REHEARSAL_ANSWER,
            source_records=[], context={},
        )
        self.assertTrue(quality["accepted"], quality)
        self.assertEqual(quality["quality_gate"], "non_selection_answer_present_v1")

    def run_spec_chat(self, model: SequenceModel, message: str = SPEC_REVISION_MESSAGE) -> dict:
        with patch.dict(os.environ, {
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED": "false",
            "JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED": "true",
        }):
            return run_ai_ceo_chat(
                repository=MinimalRepository(), company_id="test-company", store_id="test-store",
                user_id="test-user", message=message, model_client=model,
                active_listing_context={
                    "contract_version": "active_listing_context_v1", "product_name": PRODUCT,
                    "listing_project_identity": IDENTITY,
                    "listing": {"title": PRODUCT, "known_facts": {"product_name": PRODUCT}},
                },
            )

    def test_spec_revision_prompt_does_not_request_candidate_cards(self) -> None:
        system, _ = build_ai_ceo_chat_prompts(
            message=SPEC_REVISION_MESSAGE, context={}, route="ebay_workflow",
        )
        self.assertNotIn("每张卡包含商品名", system)
        self.assertNotIn("目标、计划、来源/缺口、风险", system)
        self.assertIn("当前商品", system)
        selection_system, _ = build_ai_ceo_chat_prompts(
            message="请选品并比较三个适合 eBay 的商品。", context={}, route="ebay_workflow",
        )
        self.assertIn("每张卡包含商品名", selection_system)

    def test_incomplete_spec_repair_stays_on_current_task_and_rejects_if_still_incomplete(self) -> None:
        model = SequenceModel(["### 商品规格\n|", "### 商品规格\n|"])
        chat = self.run_spec_chat(model)
        self.assertEqual(model.calls, 2)
        repair_prompt = model.system_prompts[1]
        self.assertNotIn("选品问题必须", repair_prompt)
        self.assertNotIn("严格按 selection_contract 输出", repair_prompt)
        self.assertIn("表格", repair_prompt)
        self.assertIn("模拟", repair_prompt)
        self.assertEqual(chat["status"], "model_answer_rejected")
        self.assertIn("model_answer_truncated_table", chat["answer_quality"]["blocked_by"])
        self.assertIn("内容不完整", chat["answer"])
        self.assertNotIn("规则回答", chat["answer"])
        self.assertNotIn("重新生成具体候选", chat["answer"])
        report = self.save(SPEC_REVISION_MESSAGE, chat["answer"], answer_quality=chat["answer_quality"])
        self.assertFalse(self.frontend_can_import(report))

    def test_incomplete_spec_repair_can_return_a_valid_simulation_without_reselection(self) -> None:
        model = SequenceModel(["### 商品规格\n|", REHEARSAL_ANSWER])
        chat = self.run_spec_chat(model)
        self.assertEqual(chat["status"], "model_answered")
        self.assertEqual(chat["answer"], REHEARSAL_ANSWER.strip())
        self.assertEqual(model.calls, 2)
        self.assertNotIn("选品问题必须", model.system_prompts[1])
        report = self.save(SPEC_REVISION_MESSAGE, chat["answer"], answer_quality=chat["answer_quality"])
        self.assertTrue(report["merchant_product_fact_packet"]["simulation_only"])
        self.assertTrue(self.frontend_can_import(report))
        self.assertFalse(report["merchant_product_fact_packet"]["listing_readiness"]["ready_for_real_publish"])

    def test_partial_budget_exhaustion_uses_one_direct_recovery_without_continuation_or_repair(self) -> None:
        class ExhaustedTableModel(SequenceModel):
            def generate_text(self, **kwargs: object) -> dict:
                result = super().generate_text(**kwargs)
                result["finish_reason"] = "length"
                return result

        for recovered in [REHEARSAL_ANSWER, "### 商品规格\n|"]:
            with self.subTest(recovered_complete=recovered == REHEARSAL_ANSWER):
                model = ExhaustedTableModel(["### 商品规格\n|"])
                direct = SequenceModel([recovered])
                model.jiejing_empty_answer_model_client = direct
                chat = self.run_spec_chat(model)
                self.assertEqual(model.calls, 1, "do not keep spending on truncated reasoning continuations")
                self.assertEqual(direct.calls, 1, "direct recovery must remain bounded to one request")
                self.assertEqual(chat["answer_quality"]["repair_retry_count"], 0)
                self.assertEqual(chat["answer_quality"]["output_recovery_used"], True)
                self.assertEqual(chat["status"], "model_answered" if recovered == REHEARSAL_ANSWER else "model_answer_rejected")
                if recovered != REHEARSAL_ANSWER:
                    self.assertIn("内容不完整", chat["answer"])

    def test_complete_primary_answer_does_not_use_the_recovery_client(self) -> None:
        model = SequenceModel([REHEARSAL_ANSWER])
        direct = SequenceModel([AssertionError("unnecessary recovery")])
        model.jiejing_empty_answer_model_client = direct
        chat = self.run_spec_chat(model)
        self.assertEqual(chat["status"], "model_answered")
        self.assertEqual(model.calls, 1)
        self.assertEqual(direct.calls, 0)
        self.assertFalse(chat["answer_quality"]["output_recovery_used"])

    def test_incomplete_policy_answer_reports_completeness_not_a_source_accusation(self) -> None:
        model = SequenceModel(["### eBay 官方规则\n|", "### eBay 官方规则\n|"])
        chat = self.run_spec_chat(model, message="请说明 eBay Listing 主图政策要求。")
        self.assertEqual(chat["status"], "model_answer_rejected")
        self.assertIn("内容不完整", chat["answer"])
        self.assertNotIn("把建议写成了强制规定", chat["answer"])

    def test_fact_field_names_cannot_replace_the_current_product(self) -> None:
        report = self.save(
            f"继续当前项目，不重新选品。目标商品：{PRODUCT}。修订商品规格表，仅供模拟演练。",
            "### 候选商品卡\n候选商品 1：商品状态\nNew\n候选商品 2：SKU\nTEST-001\n",
        )
        self.assertEqual(report["product"], PRODUCT)
        self.assertEqual([c["name"] for c in report["product_candidates"]], [PRODUCT])
        stale_report = json.loads(json.dumps(report))
        stale_report["product"] = "商品状态"
        stale_report["selected_product_candidate"] = {"candidate_id": "candidate_1", "name": "SKU", "selected": True}
        stale_report["product_candidates"] = [stale_report["selected_product_candidate"]]
        stale_fields = stale_report["listing_handoff"]["listing_fields"]
        stale_fields["title"] = "商品状态"
        stale_fields["selected_product_candidate"] = stale_report["selected_product_candidate"]
        stale_fields["product_candidates"] = stale_report["product_candidates"]
        self.assertFalse(self.frontend_can_import(stale_report))

    def test_no_selection_boundaries_do_not_activate_candidate_quality_rules(self) -> None:
        for boundary in [
            "不重新选品", "不要重新选品", "无需推荐候选商品", "不再比较候选",
            "不要联网或重新选品", "禁止联网、调研和重新选品",
            "no new product ideas", "do not repeat product selection",
        ]:
            with self.subTest(boundary=boundary):
                quality = validate_ai_ceo_answer_quality(
                    message=f"继续当前项目，{boundary}。请修订商品规格表，仅供模拟演练。",
                    route="ebay_workflow", answer=REHEARSAL_ANSWER, source_records=[], context={},
                )
                self.assertTrue(quality["accepted"], quality)
                self.assertEqual(quality["quality_gate"], "non_selection_answer_present_v1")

    def test_affirmative_selection_keeps_its_quality_gate(self) -> None:
        for message in [
            "请选品并比较3个候选商品。", "比较原来的3个候选商品，不要重新选品。",
            "不要联网或重新选品，但请比较这3个候选商品。",
            "不重新选品；现在改变计划，请重新选品。",
            "No new product ideas; instead compare the product ideas already proposed.",
        ]:
            with self.subTest(message=message):
                quality = validate_ai_ceo_answer_quality(
                    message=message, route="ebay_workflow", answer=REHEARSAL_ANSWER,
                    source_records=[], context={},
                )
                self.assertFalse(quality["accepted"], quality)
                self.assertEqual(quality["quality_gate"], "ebay_product_selection_answer_v2")

    def test_spec_table_survives_chat_and_save_without_candidate_projection(self) -> None:
        message = (
            f"继续当前项目，目标商品：{PRODUCT}。不要联网或重新选品。"
            "请修订商品规格表，仅供模拟演练，不是供应商参数。"
            "禁止保存eBay草稿、正式发布、采购或付款。"
        )
        answer = REHEARSAL_ANSWER.replace(
            "| 建议售价 |", "| SKU | MSC-SET8-DRILL-001 |\n| 采购成本 | USD 2.50（模拟演练） |\n"
            "| 建议库存 | 10（模拟演练） |\n| 建议售价 |",
        )
        model = SequenceModel([answer])
        with patch.dict(os.environ, {
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED": "false",
            "JIEJING_AI_CEO_MODEL_REPAIR_RETRY_ENABLED": "true",
        }):
            chat = run_ai_ceo_chat(
                repository=MinimalRepository(), company_id="test-company", store_id="test-store",
                user_id="test-user", message=message, model_client=model,
                active_listing_context={
                    "contract_version": "active_listing_context_v1",
                    "product_name": PRODUCT, "listing_project_identity": IDENTITY,
                    "listing": {"title": PRODUCT, "known_facts": {"product_name": PRODUCT}},
                },
            )
        self.assertEqual(chat["status"], "model_answered", chat)
        self.assertEqual(chat["answer"], answer.strip())
        self.assertEqual(model.calls, 1)
        self.assertEqual(chat["context"]["active_listing_context"]["product_name"], PRODUCT)
        self.assertFalse(chat["answer_quality"].get("contract_projection_used", False))
        report = self.save(message, chat["answer"], answer_quality=chat["answer_quality"])
        self.assertEqual(report["product"], PRODUCT)
        self.assertEqual(report["listing_project_identity"], IDENTITY)
        self.assertEqual([c["name"] for c in report["product_candidates"]], [PRODUCT])
        packet = report["merchant_product_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertEqual(packet["derived_listing_suggestions"]["unit_cost"], "2.50")
        self.assertEqual(packet["derived_listing_suggestions"]["quantity"], "10")
        self.assertEqual(packet["derived_listing_suggestions"]["package_weight_g"], "380")
        self.assertFalse(packet["source_confirmed_facts"])
        self.assertFalse(packet["listing_readiness"]["ready_for_real_publish"])
        self.assertTrue(self.frontend_can_import(report))

    def test_legitimate_product_names_containing_field_words_remain_eligible(self) -> None:
        for name in ["SKU label printer", "商品标签纸", "Stainless Steel Measuring Cups Set"]:
            with self.subTest(name=name):
                report = self.save("请比较候选商品。", f"### 候选商品 1：{name}\n待核对供应商规格。")
                self.assertEqual(report["product"], name)
                self.assertTrue(self.frontend_can_import(report))

    def test_simulation_safety_does_not_depend_on_a_specific_no_publish_phrase(self) -> None:
        report = self.save(
            f"目标商品：{PRODUCT}。请生成模拟演练资料，用于内部 Listing。", REHEARSAL_ANSWER,
        )
        packet = report["merchant_product_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertIn("simulation_only_product_facts", packet["blocked_by"])
        self.assertFalse(packet["listing_readiness"]["ready_for_real_publish"])

    def frontend_high_risk(self, messages: list[str]) -> list[bool]:
        script = r"""
const fs = require('fs');
const source = fs.readFileSync('app.js', 'utf8');
const start = source.indexOf('function isSaasCeoHighRiskCommand(');
const end = source.indexOf('\nfunction uniqueSaasCeoRoutes(', start);
eval(source.slice(start, end));
process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(0, 'utf8')).map(isSaasCeoHighRiskCommand)));
"""
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps(messages), text=True,
            encoding="utf-8", capture_output=True, check=True, cwd=ROOT,
        )
        return json.loads(result.stdout)

    def test_a_prohibited_action_list_does_not_request_confirmation(self) -> None:
        messages = [
            REHEARSAL_MESSAGE,
            "帮我整理商品资料，禁止保存 eBay 草稿、正式发布、采购或付款。",
            "继续 Listing 演练，不要发布、退款或付款。",
            "生成内部 Listing，禁止采购、付款、改库存或正式发布。",
        ]
        for message in messages:
            with self.subTest(message=message):
                self.assertFalse(build_ai_ceo_turn_plan(message)["confirmation_required"])
        self.assertEqual(self.frontend_high_risk(messages), [False] * len(messages))

    def test_an_affirmative_action_after_a_prohibition_still_requires_confirmation(self) -> None:
        messages = [
            "不要发布、退款或付款，但现在正式发布到 eBay。",
            "禁止采购或付款，然后请立即发布到 eBay。",
            "不退款、请现在付款。",
            "禁止保存 eBay 草稿，直接正式发布到 eBay。",
        ]
        for message in messages:
            with self.subTest(message=message):
                self.assertTrue(build_ai_ceo_turn_plan(message)["confirmation_required"])
        self.assertEqual(self.frontend_high_risk(messages), [True] * len(messages))

    def test_numbered_failure_instructions_do_not_replace_the_active_product(self) -> None:
        report = self.save(
            "请提取当前商品供应商链接的规格 https://detail.1688.com/offer/808803317575.html ，不重新选品。",
            "## 读取结果：访问受限，未获取到1688页面内容\n"
            "### 需要确认的动作\n"
            "3. 如果本轮只是演练访问边界，我保持未成功读取的结果，不生成任何替代值。\n"
            "### 下一步\n本轮不生成 Listing 草稿、不写入 eBay、不采购、不付款。",
        )
        self.assertEqual(report["product"], PRODUCT)
        self.assertEqual([c["name"] for c in report["product_candidates"]], [PRODUCT])
        self.assertEqual(report["listing_project_identity"], IDENTITY)

    def test_supplier_read_failure_cannot_be_imported_as_a_product_result(self) -> None:
        report = self.save(
            "请读取当前商品供应商链接并提取参数：https://detail.1688.com/offer/808803317575.html 。",
            "## 读取结果：访问受限，未获取到1688页面内容\n商品参数均待补，不能伪装读取成功。",
            source_records=[{"url": "https://example.com/general-guide", "title": "General guide"}],
        )
        self.assertEqual(report["product"], PRODUCT)
        self.assertIn("supplier_source_unavailable", report["blocked_by"])
        self.assertEqual(report["evidence_status"], "supplier_source_unavailable")
        self.assertFalse(report["listing_import_ready"])
        self.assertFalse(self.frontend_can_import(report))

    def frontend_can_import(self, report: dict) -> bool:
        script = r"""
const fs = require('fs');
const source = fs.readFileSync('app.js', 'utf8');
function body(name) {
  const start = source.indexOf('function ' + name + '(');
  const end = source.indexOf('\nfunction ', start + 10);
  return source.slice(start, end);
}
const publicRuntimeText = value => String(value || '');
const saasAiCeoListingHandoffFieldsFromReport = r => r.report.listing_handoff.listing_fields;
const saasSelectedMarketProductCandidate = c => c.find(x => x.selected);
eval(body('saasIsInvalidMarketProductLabel'));
eval(body('saasIsConcreteProductLabel'));
eval(body('saasAiCeoMarketReportCanStartBlockedListingDraft'));
process.stdout.write(JSON.stringify(saasAiCeoMarketReportCanStartBlockedListingDraft({
  report_type:'ai_ceo.market_research', report: JSON.parse(fs.readFileSync(0, 'utf8'))
})));
"""
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps(report), text=True,
            encoding="utf-8", capture_output=True, check=True, cwd=ROOT,
        )
        return json.loads(result.stdout)

    def test_partial_intake_and_conditional_advice_keep_pending_drafts_available(self) -> None:
        for answer in [
            "已读取页面上的部分规格。未获取到包装重量参数，该字段保持待补。",
            "如果无法读取页面内容，请补充照片；目前已识别商品方向，规格保持待核对。",
        ]:
            with self.subTest(answer=answer):
                report = self.save(
                    "提取当前商品参数：https://example.com/supplier 。不重新选品。", answer,
                    source_records=[{"url": "https://example.com/supplier", "title": "Supplier"}],
                )
                self.assertNotIn("supplier_source_unavailable", report["blocked_by"])
                self.assertTrue(self.frontend_can_import(report))

    def report_delivery_markup(self, report: dict) -> str:
        script = r"""
const fs = require('fs');
const source = fs.readFileSync('app.js', 'utf8');
const start = source.indexOf('function renderSaasAiCeoMarketReportDeliveryMarkup(');
const end = source.indexOf('\nfunction ', start + 10);
const normalizeSaasAiCeoLatestTurn = value => value;
const saasAiCeoMarketProductLabel = () => 'Test measuring set';
const saasIsConcreteProductLabel = () => true;
const escapeHtml = value => String(value);
const saasAuthoritativeAiCeoMarketReportForTurn = () => ({report: JSON.parse(fs.readFileSync(0, 'utf8'))});
const saasAiCeoMarketReportCanStartBlockedListingDraft = () => false;
eval(source.slice(start, end));
process.stdout.write(renderSaasAiCeoMarketReportDeliveryMarkup({market_report_delivery:{
  structured_report_saved:true, report_type:'ai_ceo.market_research',
  listing_import_ready:false, report_id:'test-report', product:'Test measuring set', source_record_count:3
}}));
"""
        result = subprocess.run(["node", "-e", script], input=json.dumps(report), text=True, encoding="utf-8", capture_output=True, check=True, cwd=ROOT)
        return result.stdout

    def test_failed_read_card_explains_the_actual_problem_without_an_import_button(self) -> None:
        markup = self.report_delivery_markup({"evidence_status": "supplier_source_unavailable"})
        self.assertIn("来源页面暂不可读取", markup)
        self.assertNotIn("补齐候选商品", markup)
        self.assertNotIn("导入 Listing 草稿", markup)

    def test_rejected_answer_card_does_not_ask_for_unrelated_product_candidates(self) -> None:
        markup = self.report_delivery_markup({
            "answer_quality": {"accepted": False, "blocked_by": ["model_answer_truncated_table"]},
        })
        self.assertIn("本次内容未通过校验", markup)
        self.assertNotIn("补齐候选商品", markup)
        self.assertNotIn("市场调研已保存", markup)
        self.assertNotIn("导入 Listing 草稿", markup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
