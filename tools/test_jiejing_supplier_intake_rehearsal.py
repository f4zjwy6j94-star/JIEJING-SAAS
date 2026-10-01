#!/usr/bin/env python3
"""Supplier-intake failure and rehearsal boundaries; local data, no network."""
from __future__ import annotations

import gc
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository
from jiejing_saas.ai_ceo_chat import build_ai_ceo_turn_plan


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

    def test_failed_read_card_explains_the_actual_problem_without_an_import_button(self) -> None:
        script = r"""
const fs = require('fs');
const source = fs.readFileSync('app.js', 'utf8');
const start = source.indexOf('function renderSaasAiCeoMarketReportDeliveryMarkup(');
const end = source.indexOf('\nfunction ', start + 10);
const normalizeSaasAiCeoLatestTurn = value => value;
const saasAiCeoMarketProductLabel = () => 'Test measuring set';
const saasIsConcreteProductLabel = () => true;
const escapeHtml = value => String(value);
const saasAuthoritativeAiCeoMarketReportForTurn = () => ({report:{evidence_status:'supplier_source_unavailable'}});
const saasAiCeoMarketReportCanStartBlockedListingDraft = () => false;
eval(source.slice(start, end));
process.stdout.write(renderSaasAiCeoMarketReportDeliveryMarkup({market_report_delivery:{
  structured_report_saved:true, report_type:'ai_ceo.market_research',
  listing_import_ready:false, report_id:'test-report', product:'Test measuring set', source_record_count:3
}}));
"""
        result = subprocess.run(["node", "-e", script], text=True, encoding="utf-8", capture_output=True, check=True, cwd=ROOT)
        self.assertIn("来源页面暂不可读取", result.stdout)
        self.assertNotIn("补齐候选商品", result.stdout)
        self.assertNotIn("导入 Listing 草稿", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
