#!/usr/bin/env python3
"""Isolated HTTP checks for explicitly requested, one-way simulation protection."""
from __future__ import annotations

import json
import sys
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import test_jiejing_ai_ceo_semantic_http as base


def simulation_model_hook() -> str:
    # Only the external provider is replaced; authentication, planning validation,
    # project binding, CAS, persistence, reporting and replay use production code.
    hook = base.model_hook().replace(
        '                if "SPOON15" in message:',
        '''                if "MOCK-B-015" in message:
                    proposals = [
                        {"field": "sku", "value": "MOCK-B-015", "source_quote": "SKU MOCK-B-015"},
                        {"field": "selling_price", "value": "19.5", "source_quote": "售价19.5 USD"},
                        {"field": "currency", "value": "USD", "source_quote": "售价19.5 USD"},
                        {"field": "quantity", "value": "5", "source_quote": "库存5"},
                        {"field": "material", "value": "模拟桦木", "source_quote": "材质模拟桦木"},
                        {"field": "net_weight_g", "value": "42", "source_quote": "净重42克"},
                        {"field": "package_weight_g", "value": "45", "source_quote": "包装45g"},
                        {"field": "package_length_cm", "value": "16", "source_quote": "包装尺寸16×4×2.5 cm"},
                        {"field": "package_width_cm", "value": "4", "source_quote": "包装尺寸16×4×2.5 cm"},
                        {"field": "package_height_cm", "value": "2.5", "source_quote": "包装尺寸16×4×2.5 cm"},
                        {"field": "unit_cost", "value": "1.20", "source_quote": "成本1.20 USD"},
                        {"field": "item_location", "value": "CN", "source_quote": "发货地CN"},
                    ]
                if "SPOON15" in message:''',
    ).replace(
        '"product_fact_proposals": proposals,',
        '"product_fact_proposals": proposals, "simulation_request": '
        '({"enabled": True, "source_quote": "仅用于内部模拟"} '
        'if "仅用于内部模拟" in message else None),',
    )
    # The base fixture's final network guard references a removed api import;
    # bind the actual HTTP module so startup cannot skip this provider wrapper.
    hook = hook.replace("api.urllib.request.urlopen = reject_network", "import urllib.request\nurllib.request.urlopen = reject_network")
    return hook + r'''
original_generate = Model.generate_text
def simulation_generate(self, **kwargs):
    result = original_generate(self, **kwargs)
    if "语义任务规划器" in str(kwargs.get("system_prompt") or ""):
        message = json.loads(kwargs["user_prompt"])["merchant_message"]
        plan = json.loads(result["text"])
        if "缺省保护字段" in message:
            plan.pop("simulation_request", None)
        if "伪造模拟引用" in message:
            plan["simulation_request"] = {"enabled": True, "source_quote": "本条没有这个请求"}
        if "错误模拟类型" in message:
            plan["simulation_request"] = {"enabled": 1, "source_quote": "仅用于内部模拟"}
        if "额外模拟权限" in message:
            plan["simulation_request"] = {"enabled": True, "source_quote": "仅用于内部模拟", "write_allowed": True}
        result["text"] = json.dumps(plan, ensure_ascii=False)
    return result
Model.generate_text = simulation_generate
'''


class SimulationRequestHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hook = simulation_model_hook()
        with patch.object(base, "model_hook", return_value=hook):
            base.SemanticDispatchHttpTests.setUpClass.__func__(cls)

    tearDownClass = classmethod(base.SemanticDispatchHttpTests.tearDownClass.__func__)
    call = base.SemanticDispatchHttpTests.call
    reports = base.SemanticDispatchHttpTests.reports
    envelope = base.SemanticDispatchHttpTests.envelope
    upload = base.SemanticDispatchHttpTests.upload

    def setUp(self):
        base.SemanticDispatchHttpTests.setUp(self)
        self.b_identity = {"key": "separate-b", "source_report_id": "source-b", "candidate_id": "candidate-b"}
        status, self.b = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": {
                "merchant_confirmed_facts": {"product_name": "B coffee scoop", "material": "REAL_B_MATERIAL",
                    "merchant_owned_product_confirmed": True, "image_rights_confirmed": True,
                    "image_urls": "https://example.test/b-owned.png"},
                "derived_listing_suggestions": {"material": "unconfirmed image material"},
                "simulation_only": False,
            },
        })
        self.assertEqual(201, status)

    def b_envelope(self, message):
        body = self.envelope(message)
        body["conversation_history"] = [{"user_text": "为B提供内部演练示例，暂不保存事实。",
            "assistant_text": "示例：SKU MOCK-B-015，售价19.5 USD，库存5，净重42克；均不是供应商真实资料。"}]
        body.pop("supplier_facts", None)
        body.pop("supplier_facts_verified", None)
        body["active_listing_context"] = {
            "contract_version": "active_listing_context_v1",
            "listing_project_identity": self.b_identity,
            "product_name": "B coffee scoop",
        }
        return body

    def test_explicit_request_without_numbers_persists_simulation_protection(self):
        # Seed an existing edited artifact through the repository's public
        # persistence seam; the behavior under test still uses authenticated HTTP.
        saved_packet = {**self.b["merchant_product_fact_packet"],
            "listing_copy": {"title": "Existing B merchant title", "description": "Keep B edited description"},
            "source_confirmed_facts": {"supplier_item_number": "REAL-B-SOURCE"},
            "field_evidence": {"material": {"source_type": "merchant_form", "merchant_confirmation_received": True}}}
        repository = base.SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        repository.save_merchant_product_fact_report(task=self.b["task"], packet=saved_packet,
            listing_project_identity=self.b_identity)
        before = self.reports()
        body = self.b_envelope("继续那把：仅用于内部模拟，暂不填写数值，请保存这个保护标记。")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload.get("ai_ceo_chat", {}).get("status"))
        self.assertEqual("ready", payload["semantic_dispatch"]["status"])
        self.assertEqual(self.b_identity, payload["semantic_dispatch"]["target_project_identity"])
        packet = payload["product_vision_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertEqual("simulation_rehearsal", packet["fact_scope"])
        self.assertIn("simulation_only_product_facts", packet["blocked_by"])
        self.assertEqual(self.b["merchant_product_fact_packet"]["merchant_confirmed_facts"], packet["merchant_confirmed_facts"])
        self.assertEqual(self.b["merchant_product_fact_packet"]["derived_listing_suggestions"], packet["derived_listing_suggestions"])
        self.assertEqual(saved_packet["source_confirmed_facts"], packet["source_confirmed_facts"])
        self.assertEqual(saved_packet["listing_copy"], packet["listing_copy"])
        self.assertEqual(saved_packet["field_evidence"], packet["field_evidence"])
        self.assertEqual(saved_packet["source_records"], packet["source_records"])
        request = {"enabled": True, "source_quote": "仅用于内部模拟"}
        self.assertEqual(request, payload["ai_ceo_chat"]["turn_plan"]["simulation_request"])
        self.assertEqual(request, packet["simulation_request"])
        self.assertEqual(packet, payload["product_vision_report"]["report"]["merchant_product_fact_packet"])
        self.assertEqual(packet, payload["ai_ceo_market_report"]["report"]["merchant_product_fact_packet"])
        after = self.reports()
        for report in before:
            self.assertEqual(report, next(item for item in after if item["report_id"] == report["report_id"]))

    def test_quoted_values_stay_derived_replay_is_stable_and_null_cannot_clear_protection(self):
        message = ("继续那把：仅用于内部模拟，接纳这些示例值：SKU MOCK-B-015；售价19.5 USD；库存5；材质模拟桦木；净重42克；"
                   "包装45g；包装尺寸16×4×2.5 cm；成本1.20 USD；发货地CN。")
        body = self.b_envelope(message)
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, first = self.call(path, body)
        self.assertEqual(201, status)
        packet = first["product_vision_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertEqual(self.b_identity, first["semantic_dispatch"]["target_project_identity"])
        self.assertEqual(self.b["merchant_product_fact_packet"]["merchant_confirmed_facts"], packet["merchant_confirmed_facts"])
        self.assertEqual(self.b["merchant_product_fact_packet"]["source_records"], packet["source_records"])
        for field, value in {"sku": "MOCK-B-015", "selling_price": "19.5", "currency": "USD",
                             "quantity": "5", "material": "模拟桦木", "net_weight_g": "42", "package_weight_g": "45",
                             "package_length_cm": "16", "package_width_cm": "4", "package_height_cm": "2.5",
                             "unit_cost": "1.20", "item_location": "CN"}.items():
            self.assertEqual(value, packet["derived_listing_suggestions"][field])
            self.assertNotIn(field, packet["source_confirmed_facts"])
            if field != "material":
                self.assertNotIn(field, packet["merchant_confirmed_facts"])
        self.assertEqual("REAL_B_MATERIAL", packet["merchant_confirmed_facts"]["material"])
        self.assertFalse(packet["pending_field_evidence"]["material"]["merchant_confirmation_received"])
        self.assertTrue(any(item["field"] == "material" for item in packet["fact_conflicts"]))
        self.assertEqual(packet, first["ai_ceo_market_report"]["report"]["merchant_product_fact_packet"])
        before_replay = self.reports()
        status, replay = self.call(path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(packet, replay["product_vision_fact_packet"])
        self.assertEqual(first["ai_ceo_chat"]["turn_plan"], replay["ai_ceo_chat"]["turn_plan"])
        self.assertEqual(before_replay, self.reports())
        status, history = self.call("/ai-ceo/chat-history")
        self.assertEqual(200, status)
        self.assertEqual(message, history["ai_ceo_chat_history"]["turns"][-1]["user_text"])
        status, tasks = self.call("/tasks")
        self.assertEqual(200, status)
        chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(1, len(chats))
        self.assertEqual(2, chats[0]["output"]["model_request_count"])
        self.assertEqual(first["ai_ceo_chat"]["turn_plan"]["simulation_request"], chats[0]["input"]["turn_plan"]["simulation_request"])
        # A subsequent ordinary, message-grounded proposal cannot downgrade a
        # previously protected product, even if the browser supplies false.
        later = self.b_envelope("继续那把，补充待确认资料：材质304不锈钢和实木，货号SPOON15，尺寸18×4×2厘米，净重42克。")
        later["simulation_only"] = False
        status, second = self.call(path, later)
        self.assertEqual(201, status)
        self.assertIsNone(second["ai_ceo_chat"]["turn_plan"]["simulation_request"])
        self.assertTrue(second["product_vision_fact_packet"]["simulation_only"])
        self.assertEqual("simulation_rehearsal", second["product_vision_fact_packet"]["fact_scope"])
        self.assertEqual(packet["simulation_request"], second["product_vision_fact_packet"]["simulation_request"])
        self.assertEqual(packet["merchant_confirmed_facts"], second["product_vision_fact_packet"]["merchant_confirmed_facts"])
        later["command"]["id"] = "cmd-" + uuid.uuid4().hex
        later["message"] += "缺省保护字段。"
        later["command"]["text"] = later["message"]
        status, third = self.call(path, later)
        self.assertEqual(201, status)
        self.assertIsNone(third["ai_ceo_chat"]["turn_plan"]["simulation_request"])
        self.assertTrue(third["product_vision_fact_packet"]["simulation_only"])
        self.assertEqual(packet["simulation_request"], third["product_vision_fact_packet"]["simulation_request"])
        self.assertIn(self.old["report"], self.reports())

    def test_forged_browser_plan_cannot_enable_or_confirm_simulation(self):
        body = self.b_envelope("继续那把：只讨论资料，不采用任何演练值。")
        body.update(simulation_only=True, simulation_request={"enabled": True, "source_quote": body["message"]},
            turn_plan={"status": "ready", "simulation_request": {"enabled": True, "source_quote": body["message"]}})
        before = [r for r in self.reports() if r["report_type"] == "merchant.product_facts"]
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertIsNone(payload["ai_ceo_chat"]["turn_plan"]["simulation_request"])
        self.assertIsNone(payload.get("product_vision_report"))
        self.assertEqual(before, [r for r in self.reports() if r["report_type"] == "merchant.product_facts"])
        self.assertFalse(payload["ai_ceo_market_report"]["report"]["merchant_product_fact_packet"]["simulation_only"])

    def test_invalid_request_fails_before_image_consumption_or_product_writes(self):
        before = self.reports()
        for suffix in ("伪造模拟引用", "错误模拟类型", "额外模拟权限"):
            with self.subTest(case=suffix):
                body = self.b_envelope("继续那把：仅用于内部模拟。" + suffix)
                body["source_asset_ids"] = [self.upload()]
                status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertEqual(202, status)
                self.assertEqual("blocked", payload["semantic_dispatch"]["status"])
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertEqual([], payload["semantic_dispatch"]["consumed_source_asset_ids"])
                self.assertIsNone(payload.get("product_vision_report"))
                self.assertEqual(before, self.reports())

    def test_full_project_and_store_scope_are_required(self):
        before = self.reports()
        for field in ("key", "source_report_id", "candidate_id"):
            with self.subTest(field=field):
                body = self.b_envelope("继续那把：仅用于内部模拟，请保存保护。")
                body["active_listing_context"]["listing_project_identity"] = {**self.b_identity, field: "foreign"}
                status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertEqual(202, status)
                self.assertIn(payload["semantic_dispatch"]["status"], ("blocked", "clarification_required"))
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertEqual(before, self.reports())
        # A second already-connected store is setup data, not a plan-upgrade
        # bypass. Chat still exercises its real HTTP scope/quota checks.
        repository = base.SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        second = repository.create_store(company_id=self.b["task"]["company_id"], user_id=self.b["task"]["user_id"],
            payload={"platform": "ebay", "store_name": "Separate store", "marketplace": "EBAY_US"})
        body = self.b_envelope("继续那把：仅用于内部模拟，请保存保护。")
        status, payload = self.call(f"/stores/{second['store_id']}/merchant-ceo/chat", body)
        self.assertEqual(202, status)
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        self.assertEqual(before, self.reports())
        status, account = base.request_json(self.base + "/auth/register", method="POST", payload={
            "email": uuid.uuid4().hex + "@example.test", "password": "local-test-password", "company_name": "Other merchant"})
        self.assertEqual(201, status)
        own_token = self.token
        try:
            self.token = account["token"]
            status, other = self.call("/stores", {"platform": "ebay", "store_name": "Other merchant store", "marketplace": "EBAY_US"})
            self.assertEqual(201, status)
            status, payload = self.call(f"/stores/{other['store']['store_id']}/merchant-ceo/chat", body)
            self.assertEqual(202, status)
            self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
            self.assertEqual([], self.reports())
        finally:
            self.token = own_token
        self.assertEqual(before, self.reports())

    def test_concurrent_real_fact_save_rejects_late_simulation_protection(self):
        body = self.b_envelope("继续那把：仅用于内部模拟；并发更新，请保存保护。")
        body["source_asset_ids"] = [self.upload()]
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.call, f"/stores/{self.store}/merchant-ceo/chat", body)
            deadline = time.time() + 10
            while time.time() < deadline:
                _, tasks = self.call("/tasks")
                if any(item["task_type"] == "ai_ceo_product_vision" and item["status"] == "completed" for item in tasks["tasks"]):
                    break
                time.sleep(.05)
            else:
                self.fail("provider did not reach the controlled answer boundary")
            packet = json.loads(json.dumps(self.b["merchant_product_fact_packet"]))
            packet["merchant_confirmed_facts"]["material"] = "latest real B material"
            status, saved = self.call(f"/stores/{self.store}/product-facts", {
                "listing_project_identity": self.b_identity, "merchant_product_fact_packet": packet,
                "save_context": {"contract_version": "merchant_product_fact_save_v1",
                    "mutation_id": "concurrent-simulation-" + uuid.uuid4().hex,
                    "expected_fact_report_id": self.b["report"]["report_id"]}})
            self.assertEqual(201, status)
            status, result = pending.result(timeout=15)
        self.assertEqual(202, status)
        self.assertEqual("blocked", result["semantic_dispatch"]["status"])
        self.assertIn("product_fact_version_conflict", result["ai_ceo_chat"]["blocked_by"])
        self.assertIsNone(result.get("product_vision_report"))
        reports = self.reports()
        self.assertEqual(3, len([r for r in reports if r["report_type"] == "merchant.product_facts"]))
        self.assertIn(saved["report"], reports)
        self.assertFalse(saved["merchant_product_fact_packet"]["simulation_only"])
        self.assertIn(self.old["report"], reports)

    def test_new_request_only_is_separate_and_answer_numbers_are_not_saved(self):
        before = self.reports()
        body = self.b_envelope("另建银色木柄15mL咖啡量勺项目，仅用于内部模拟。暂不提供数值，请先保存保护。")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        target = payload["semantic_dispatch"]["target_project_identity"]
        self.assertNotIn(target, (self.b_identity, self.old_identity))
        packet = payload["product_vision_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertFalse(packet["merchant_confirmed_facts"])
        self.assertFalse(packet["source_confirmed_facts"])
        self.assertFalse(packet["source_records"])
        self.assertEqual({"product_name": "银色木柄15mL咖啡量勺"}, packet["derived_listing_suggestions"])
        self.assertEqual([], payload["ai_ceo_chat"]["turn_plan"]["product_fact_proposals"])
        after = self.reports()
        for report in before:
            self.assertIn(report, after)

    def test_saved_protection_blocks_publish_even_when_browser_flag_is_false(self):
        status, result = self.call(f"/stores/{self.store}/merchant-ceo/chat",
            self.b_envelope("继续那把：仅用于内部模拟，请保存保护。"))
        self.assertEqual(201, status)
        # The normal first-step save authenticates the returned packet without
        # promoting any derived proposal or changing the simulation restriction.
        status, saved = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": result["product_vision_fact_packet"],
            "save_context": {"contract_version": "merchant_product_fact_save_v1",
                "mutation_id": "simulation-ui-save-" + uuid.uuid4().hex,
                "expected_fact_report_id": result["product_vision_report"]["report_id"]}})
        self.assertEqual(201, status)
        self.assertTrue(saved["merchant_product_fact_packet"]["simulation_only"])
        self.assertEqual(result["product_vision_fact_packet"]["merchant_confirmed_facts"],
                         saved["merchant_product_fact_packet"]["merchant_confirmed_facts"])
        self.assertEqual(result["product_vision_fact_packet"]["derived_listing_suggestions"],
                         saved["merchant_product_fact_packet"]["derived_listing_suggestions"])
        body = {"product": "B coffee scoop", "listing_project_identity": self.b_identity,
            "simulation_only": False, "listing": {"sku": "SIM-B", "title": "B simulation scoop"},
            "asset_manifest": {"assets": [{"url": "https://example.test/b-owned.png"}]},
            "publish_evidence_refs": {"product_fact_report_id": saved["report"]["report_id"]}}
        before_reports = self.reports()
        _, before_tasks = self.call("/tasks")
        _, before_confirmations = self.call("/confirmations")
        status, preview = self.call(f"/stores/{self.store}/publish-precheck", body)
        self.assertEqual(200, status)
        self.assertTrue(preview["simulation_only"])
        self.assertIn("simulation_only_product_facts", preview["source_blockers"])
        for key in ("confirmation_created", "task_created", "platform_write_attempted", "real_execution_allowed"):
            self.assertIs(preview[key], False)
        for route in ("publish-confirmation", "ebay-draft-confirmation"):
            status, blocked = self.call(f"/stores/{self.store}/{route}", body)
            self.assertEqual(422, status)
            self.assertFalse(blocked["confirmation_created"])
            self.assertIn("simulation_only_product_facts", blocked["blockers"])
        self.assertEqual(before_reports, self.reports())
        self.assertEqual(before_tasks, self.call("/tasks")[1])
        self.assertEqual(before_confirmations, self.call("/confirmations")[1])

    def test_text_protection_after_image_intake_is_not_new_image_consumption(self):
        vision_body = self.b_envelope("继续那把：识别这张图片，保存待核对资料。")
        vision_body["source_asset_ids"] = [self.upload()]
        status, prior = self.call(f"/stores/{self.store}/merchant-ceo/chat", vision_body)
        self.assertEqual(201, status)
        before = prior["product_vision_fact_packet"]
        self.assertEqual("backend_product_vision_extraction", before["source"])
        self.assertTrue(before["vision_contract_version"])
        self.assertFalse(before["simulation_only"])
        prior_stored = next(item for item in self.reports() if item["report_id"] == prior["product_vision_report"]["report_id"])
        status, current = self.call(f"/stores/{self.store}/merchant-ceo/chat",
            self.b_envelope("继续那把：仅用于内部模拟，暂不提供数字，请保存保护。"))
        self.assertEqual(201, status)
        packet = current["product_vision_fact_packet"]
        self.assertTrue(packet["simulation_only"])
        self.assertEqual([], current["semantic_dispatch"]["consumed_source_asset_ids"])
        self.assertIsNone(current.get("product_vision_task"))
        self.assertEqual("backend_semantic_product_proposals", packet["source"])
        self.assertFalse(packet.get("vision_contract_version"))
        self.assertFalse(packet.get("vision_usage"))
        for key in ("merchant_confirmed_facts", "source_confirmed_facts", "field_evidence", "pending_field_evidence",
                    "source_records", "listing_copy", "derived_listing_suggestions"):
            self.assertEqual(before.get(key), packet.get(key), key)
        self.assertTrue(packet["buyer_copy_requires_validated_listing_generation"])
        self.assertEqual(prior_stored, next(item for item in self.reports() if item["report_id"] == prior_stored["report_id"]))


if __name__ == "__main__":
    unittest.main()
