#!/usr/bin/env python3
"""Isolated HTTP checks for explicitly requested, one-way simulation protection."""
from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import test_jiejing_ai_ceo_semantic_http as base
from jiejing_saas.listing_draft_checkpoint import FIELD_KEYS, PUBLISH_INTAKE_KEYS


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
    if "语义任务规划器" not in str(kwargs.get("system_prompt") or "") and "等待无图并发" in str(kwargs.get("user_prompt") or ""):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        (root / "simulation-answer-entered").touch()
        deadline = time.monotonic() + 12
        while not (root / "simulation-answer-release").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("local simulation response was not released")
            time.sleep(.01)
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
        if "仅做费用测算" in message:
            plan.update(intent="research", research_delivery="single_product_analysis")
        if "合同纠错" in message:
            self.readonly_plan_attempts = getattr(self, "readonly_plan_attempts", 0) + 1
            plan.update(intent="chat" if self.readonly_plan_attempts == 1 else "research",
                project_action="current", read_images=False, save_artifact=False,
                product_fact_proposals=[], simulation_request=None,
                research_delivery="none" if self.readonly_plan_attempts == 1 else "single_product_analysis")
            if self.readonly_plan_attempts > 1 and "拒绝副作用" in message:
                plan.update(save_artifact=True, project_action="new", product_name="未经请求的新商品")
            if self.readonly_plan_attempts > 1 and "重复无效" in message:
                plan.update(intent="chat", research_delivery="none")
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

    def test_cost_consultation_repeating_existing_protection_keeps_fact_base_and_all_saved_fields(self):
        # All state is established and observed through authenticated HTTP.
        # A repeated safety restriction is audit data, not another fact action.
        status, protected = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": {**self.b["merchant_product_fact_packet"], "simulation_only": True},
            "save_context": {"contract_version": "merchant_product_fact_save_v1",
                "mutation_id": "protect-" + uuid.uuid4().hex,
                "expected_fact_report_id": self.b["report"]["report_id"]}})
        self.assertEqual(201, status)
        fields = {key: "Saved B " + key for key in FIELD_KEYS}
        intake = {"values": {key: "Saved B " + key for key in PUBLISH_INTAKE_KEYS}, "basis": {}}
        self.assertEqual(35, len(intake["values"]))
        checkpoint_path = f"/stores/{self.store}/listing-drafts/{self.b_identity['key']}/checkpoint"
        query = "?" + urlencode({key: self.b_identity[key] for key in ("source_report_id", "candidate_id")})
        status, saved = self.call(checkpoint_path, {"contract_version": "listing_merchant_edit_v1",
            "listing_project_identity": self.b_identity, "base_report_id": protected["report"]["report_id"],
            "expected_revision": 0, "mutation_id": "checkpoint-" + uuid.uuid4().hex,
            "fields": fields, "merchant_edited_fields": ["title", "description"], "publish_intake": intake})
        self.assertEqual(201, status)
        before_facts = [item for item in self.reports() if item["report_type"] == "merchant.product_facts"]
        status, before_checkpoint = self.call(checkpoint_path + query)
        self.assertEqual(200, status)
        self.assertFalse(before_checkpoint["base_changed"])
        body = self.b_envelope("继续那把：仅做费用测算，仅用于内部模拟；不要新增或修改商品资料，只讨论费用假设并保存咨询记录。")
        status, result = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertEqual("ready", result["semantic_dispatch"]["status"])
        self.assertEqual("research", result["ai_ceo_chat"]["turn_plan"]["intent"])
        self.assertEqual([], result["ai_ceo_chat"]["turn_plan"]["product_fact_proposals"])
        self.assertFalse(result["ai_ceo_chat"]["turn_plan"]["read_images"])
        self.assertEqual({"enabled": True, "source_quote": "仅用于内部模拟"},
                         result["ai_ceo_chat"]["turn_plan"]["simulation_request"])
        self.assertTrue(result.get("product_vision_report") is None,
                        "an already true restriction must not create a new product fact artifact")
        self.assertIsNone(result.get("product_vision_fact_packet"))
        self.assertEqual(before_facts, [item for item in self.reports() if item["report_type"] == "merchant.product_facts"])
        self.assertEqual(before_checkpoint, self.call(checkpoint_path + query)[1])
        self.assertEqual(saved["checkpoint"]["fields"], fields)
        self.assertEqual(saved["checkpoint"]["publish_intake"]["values"], intake["values"])
        market = result["ai_ceo_market_report"]
        self.assertEqual("ai_ceo.market_research", market["report_type"])
        persisted_market = next(item for item in self.reports() if item["report_id"] == market["report_id"])
        self.assertTrue(market["report"] == persisted_market["report"], "the consultation report must remain persisted")
        self.assertEqual(result["ai_ceo_chat"]["turn_plan"]["simulation_request"],
                         market["report"]["turn_plan"]["simulation_request"])
        _, tasks = self.call("/tasks")
        chat = next(item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat")
        self.assertEqual(result["ai_ceo_chat"]["turn_plan"]["simulation_request"], chat["input"]["turn_plan"]["simulation_request"])
        self.assertEqual(2, chat["output"]["model_request_count"])
        _, archive = self.call("/ai-ceo/chat-history")
        self.assertEqual(result["semantic_dispatch"], archive["ai_ceo_chat_history"]["turns"][-1]["semantic_dispatch"])
        before_replay = self.reports()
        status, replay = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(before_replay, self.reports())
        self.assertEqual(before_checkpoint, self.call(checkpoint_path + query)[1])
        # A different request streamed through the normal finalizer has the
        # same audit-only semantics; replay cannot resurrect an older artifact.
        streamed = {**body, "command": {**body["command"], "id": "cmd-" + uuid.uuid4().hex}}
        request = urllib.request.Request(f"{self.base}/stores/{self.store}/merchant-ceo/chat?stream=1",
            data=json.dumps(streamed).encode(), method="POST",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=25) as response:
            self.assertIn("ndjson", response.headers.get("Content-Type", ""))
            events = [json.loads(line) for line in response.read().decode().splitlines() if line]
        final = next(item["payload"] for item in events if item.get("type") == "final")
        self.assertTrue(final.get("product_vision_report") is None)
        self.assertTrue(final.get("product_vision_fact_packet") is None)
        self.assertEqual("ready", final["semantic_dispatch"]["status"])
        self.assertEqual(before_facts, [item for item in self.reports() if item["report_type"] == "merchant.product_facts"])
        self.assertEqual(before_checkpoint, self.call(checkpoint_path + query)[1])
        after_stream = self.reports()
        status, stream_replay = self.call(f"/stores/{self.store}/merchant-ceo/chat", streamed)
        self.assertEqual(201, status)
        self.assertTrue(stream_replay["idempotent_replay"])
        self.assertTrue(stream_replay.get("product_vision_report") is None)
        self.assertTrue(stream_replay.get("product_vision_fact_packet") is None)
        self.assertEqual(after_stream, self.reports())
        _, archive = self.call("/ai-ceo/chat-history")
        self.assertEqual(final["semantic_dispatch"], archive["ai_ceo_chat_history"]["turns"][-1]["semantic_dispatch"])
        _, after_tasks = self.call("/tasks")
        chats = [item for item in after_tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(2, len(chats))
        self.assertEqual([2, 2], [item["output"]["model_request_count"] for item in chats])
        archived_requests = [item for item in after_tasks["tasks"] if item["task_type"] == "ai_ceo_chat_request"]
        self.assertEqual(2, len(archived_requests))
        for archived in archived_requests:
            response = archived["output"]["response_payload"]
            self.assertTrue(response.get("product_vision_report") is None)
            self.assertTrue(response.get("product_vision_fact_packet") is None)
            self.assertTrue(response["ai_ceo_chat"].get("product_intake") is None)
            self.assertEqual({"enabled": True, "source_quote": "仅用于内部模拟"},
                             response["ai_ceo_chat"]["turn_plan"]["simulation_request"])

    def test_readonly_cost_plan_repair_preserves_all_fields_and_meters_replay_once(self):
        status, protected = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": {**self.b["merchant_product_fact_packet"], "simulation_only": True}})
        self.assertEqual(201, status)
        fields = {key: "Saved B " + key for key in FIELD_KEYS}
        intake = {"values": {key: "Saved B " + key for key in PUBLISH_INTAKE_KEYS}, "basis": {}}
        self.assertEqual(35, len(intake["values"]))
        path = f"/stores/{self.store}/listing-drafts/{self.b_identity['key']}/checkpoint"
        query = "?" + urlencode({key: self.b_identity[key] for key in ("source_report_id", "candidate_id")})
        status, saved = self.call(path, {"contract_version": "listing_merchant_edit_v1",
            "listing_project_identity": self.b_identity, "base_report_id": protected["report"]["report_id"],
            "expected_revision": 0, "mutation_id": "checkpoint-" + uuid.uuid4().hex,
            "fields": fields, "merchant_edited_fields": ["title", "description"], "publish_intake": intake})
        self.assertEqual(201, status)
        before_reports = self.reports()
        status, before_checkpoint = self.call(path + query)
        self.assertEqual(200, status)
        body = self.b_envelope("继续那把：合同纠错费用咨询。只回复模拟费用表，不变更任何商品资料，不联网，不要保存成果，不生成图片，不发布，保留原模拟保护。")
        chat_path = f"/stores/{self.store}/merchant-ceo/chat"
        status, result = self.call(chat_path, body)
        self.assertEqual(201, status, result)
        self.assertEqual("ready", result["semantic_dispatch"]["status"])
        plan = result["ai_ceo_chat"]["turn_plan"]
        self.assertEqual("research", plan["intent"])
        self.assertFalse(plan["save_artifact"])
        self.assertFalse(plan["read_images"])
        self.assertEqual([], plan["product_fact_proposals"])
        self.assertIsNone(plan["simulation_request"])
        self.assertTrue(result["ai_ceo_chat"]["answer"])
        self.assertIsNone(result.get("product_vision_report"))
        self.assertIsNone(result.get("ai_ceo_market_report"))
        self.assertEqual(before_reports, self.reports())
        self.assertEqual(before_checkpoint, self.call(path + query)[1])
        self.assertEqual(fields, saved["checkpoint"]["fields"])
        self.assertEqual(intake["values"], saved["checkpoint"]["publish_intake"]["values"])
        _, tasks = self.call("/tasks")
        chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(1, len(chats))
        self.assertEqual(3, chats[0]["output"]["model_request_count"])
        status, replay = self.call(chat_path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(before_reports, self.reports())
        self.assertEqual(before_checkpoint, self.call(path + query)[1])
        _, after_tasks = self.call("/tasks")
        after_chats = [item for item in after_tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(chats, after_chats)
        streamed = {**body, "command": {**body["command"], "id": "cmd-" + uuid.uuid4().hex}}
        request = urllib.request.Request(f"{self.base}{chat_path}?stream=1",
            data=json.dumps(streamed).encode(), method="POST",
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=25) as response:
            events = [json.loads(line) for line in response.read().decode().splitlines() if line]
        final = next(item["payload"] for item in events if item.get("type") == "final")
        self.assertEqual("ready", final["semantic_dispatch"]["status"])
        self.assertIsNone(final.get("product_vision_fact_packet"))
        self.assertEqual(before_reports, self.reports())
        self.assertEqual(before_checkpoint, self.call(path + query)[1])
        _, archive = self.call("/ai-ceo/chat-history")
        self.assertEqual(final["semantic_dispatch"], archive["ai_ceo_chat_history"]["turns"][-1]["semantic_dispatch"])
        status, stream_replay = self.call(chat_path, streamed)
        self.assertEqual(201, status)
        self.assertTrue(stream_replay["idempotent_replay"])
        _, tasks = self.call("/tasks")
        chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual([3, 3], [item["output"]["model_request_count"] for item in chats])

    def test_readonly_plan_repair_rejects_escalation_and_repeated_invalid_output(self):
        before_reports = self.reports()
        for scenario, expected in (("拒绝副作用", "semantic_plan_repair_effect_escalation"),
                                   ("重复无效", "semantic_plan_non_workflow_mutation")):
            with self.subTest(scenario=scenario):
                body = self.b_envelope("继续那把：合同纠错" + scenario + "；只讨论费用，不要保存商品。")
                status, result = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertEqual(202, status)
                self.assertEqual([expected], result["ai_ceo_chat"]["blocked_by"])
                self.assertIsNone(result.get("product_vision_report"))
                self.assertIsNone(result.get("ai_ceo_market_report"))
                self.assertEqual(before_reports, self.reports())
                _, tasks = self.call("/tasks")
                chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
                self.assertTrue(chats)
                self.assertTrue(all(item["output"]["model_request_count"] == 2 for item in chats))

    def test_simulation_listing_evidence_without_fact_report_keeps_first_save_payload(self):
        # A historical Listing can be the only durable project evidence. Seed
        # that public persistence seam without inventing a current fact report;
        # the first semantic fact save still travels through authenticated HTTP.
        repository = base.SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        project = {"key": "listing-only", "source_report_id": "listing-only-source", "candidate_id": "listing-only-candidate"}
        packet = {**self.b["merchant_product_fact_packet"], "simulation_only": True,
            "listing_copy": {"title": "Existing B listing title", "description": "Keep the existing B listing copy."},
            "pending_field_evidence": {"material": {"source_type": "merchant_message_model_proposal",
                "source_quote": "prior pending material", "merchant_confirmation_received": False}}}
        task = repository.create_task(company_id=self.b["task"]["company_id"], store_id=self.store,
            user_id=self.b["task"]["user_id"], task_type="listing_draft_generation", title="Existing simulation listing",
            input_data={"listing_project_identity": project, "merchant_product_fact_packet": packet})
        listing = repository.save_listing_draft_report(task=task, listing_project_identity=project,
            listing_handoff=packet["listing_copy"], merchant_product_fact_packet=packet,
            missing_fields=[], model_metadata={"mode": "live_unit"}, version=1)
        context = repository.resolve_ai_ceo_listing_context(company_id=task["company_id"], store_id=self.store, identity=project)
        self.assertEqual("", context["fact_report_id"])
        self.assertTrue(context["merchant_product_fact_packet"]["simulation_only"])
        body = self.b_envelope("继续那把：仅用于内部模拟，暂不添加数值，请保留已有文案并保存保护标记。")
        body["active_listing_context"]["listing_project_identity"] = project
        status, result = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertEqual("ready", result["semantic_dispatch"]["status"])
        self.assertEqual(project, result["semantic_dispatch"]["target_project_identity"])
        saved = result["product_vision_fact_packet"]
        self.assertTrue(saved["simulation_only"])
        self.assertEqual(packet["listing_copy"], saved.get("listing_copy"))
        self.assertEqual(packet["pending_field_evidence"], saved.get("pending_field_evidence"))
        self.assertEqual("merchant.product_facts", result["product_vision_report"]["report_type"])
        after = self.reports()
        self.assertEqual(listing["report"], next(item["report"] for item in after if item["report_id"] == listing["report_id"]))
        status, replay = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(saved, replay["product_vision_fact_packet"])
        self.assertEqual(after, self.reports())

    def test_existing_protection_does_not_swallow_new_proposals_or_new_image_evidence(self):
        status, protected = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": {**self.b["merchant_product_fact_packet"], "simulation_only": True}})
        self.assertEqual(201, status)
        current_id = protected["report"]["report_id"]
        message = "继续那把：仅用于内部模拟，补充待确认资料：材质304不锈钢和实木，货号SPOON15，尺寸18×4×2厘米，净重42克。"
        for _ in range(2):
            # Even equal values in a new explicit proposal retain their new
            # evidence; only zero-proposal safety repetitions are audit-only.
            status, result = self.call(f"/stores/{self.store}/merchant-ceo/chat", self.b_envelope(message))
            self.assertEqual(201, status)
            self.assertEqual("ready", result["semantic_dispatch"]["status"])
            self.assertNotEqual(current_id, result["product_vision_report"]["report_id"])
            current_id = result["product_vision_report"]["report_id"]
            packet = result["product_vision_fact_packet"]
            self.assertTrue(packet["simulation_only"])
            self.assertEqual("SPOON15", packet["derived_listing_suggestions"]["supplier_item_number"])
            self.assertEqual("REAL_B_MATERIAL", packet["merchant_confirmed_facts"]["material"])
            self.assertEqual(protected["merchant_product_fact_packet"]["source_records"], packet["source_records"])
        body = self.b_envelope("继续那把：仅用于内部模拟，请识别本轮新图片并保存待确认建议。")
        body["source_asset_ids"] = [self.upload()]
        status, image = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertNotEqual(current_id, image["product_vision_report"]["report_id"])
        self.assertEqual(body["source_asset_ids"], image["semantic_dispatch"]["consumed_source_asset_ids"])
        self.assertEqual([], image["ai_ceo_chat"]["turn_plan"]["product_fact_proposals"])
        self.assertTrue(image["ai_ceo_chat"]["turn_plan"]["read_images"])
        self.assertTrue(image["product_vision_fact_packet"]["simulation_only"])
        self.assertTrue(image["product_vision_task"])
        self.assertEqual("REAL_B_MATERIAL", image["product_vision_fact_packet"]["merchant_confirmed_facts"]["material"])
        self.assertIn(self.old["report"], self.reports())

    def test_stale_base_still_conflicts_before_repeated_protection_can_be_a_noop(self):
        status, protected = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.b_identity,
            "merchant_product_fact_packet": {**self.b["merchant_product_fact_packet"], "simulation_only": True}})
        self.assertEqual(201, status)
        body = self.b_envelope("继续那把：仅做费用测算，仅用于内部模拟，等待无图并发；不要新增或修改商品资料。")
        entered = Path(self.temp.name) / "simulation-answer-entered"
        release = Path(self.temp.name) / "simulation-answer-release"
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.call, f"/stores/{self.store}/merchant-ceo/chat", body)
            try:
                deadline = time.monotonic() + 10
                while not entered.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(entered.exists(), "the external response boundary must be reached after context resolution")
                changed = json.loads(json.dumps(protected["merchant_product_fact_packet"]))
                changed["merchant_confirmed_facts"]["material"] = "New merchant confirmed B material"
                status, latest = self.call(f"/stores/{self.store}/product-facts", {
                    "listing_project_identity": self.b_identity, "merchant_product_fact_packet": changed,
                    "save_context": {"contract_version": "merchant_product_fact_save_v1",
                        "mutation_id": "concurrent-protected-" + uuid.uuid4().hex,
                        "expected_fact_report_id": protected["report"]["report_id"]}})
                self.assertEqual(201, status)
            finally:
                release.touch()
            status, result = pending.result(timeout=15)
        self.assertEqual(202, status)
        self.assertEqual("blocked", result["semantic_dispatch"]["status"])
        self.assertIn("product_fact_version_conflict", result["ai_ceo_chat"]["blocked_by"])
        self.assertTrue(result.get("product_vision_report") is None)
        self.assertTrue(result.get("ai_ceo_market_report") is None)
        self.assertEqual([], result["semantic_dispatch"]["consumed_source_asset_ids"])
        facts = [item for item in self.reports() if item["report_type"] == "merchant.product_facts"]
        self.assertEqual(4, len(facts))
        self.assertEqual(latest["report"], facts[-1])
        self.assertTrue(latest["merchant_product_fact_packet"]["simulation_only"])

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
        # Planner, proposal-role review and answer are each metered once;
        # replay must not make another model request or remove protection.
        self.assertEqual(3, chats[0]["output"]["model_request_count"])
        review = {"policy": "backend_model_fact_role_review_v1", "status": "completed", "rejected_fields": []}
        self.assertNotIn("product_fact_review", first["ai_ceo_chat"]["turn_plan"])
        self.assertEqual(review, chats[0]["input"]["turn_plan"]["product_fact_review"])
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
