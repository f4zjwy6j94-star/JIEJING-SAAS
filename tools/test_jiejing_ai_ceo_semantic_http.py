#!/usr/bin/env python3
"""Hermetic HTTP regressions for model-planned product selection and isolation."""
from __future__ import annotations

import json
import base64
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.test_jiejing_ai_ceo_routing_supplier_http_red import (
    free_port, isolated_backend_env, request_json, wait_for_health,
    LOCAL_SESSION_SECRET,
)
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.api_server import _ai_ceo_chat_request_fingerprint


def model_hook() -> str:
    return r'''
import json
import time
from jiejing_saas import api_server as api
from jiejing_saas.product_vision import ProductVisionError

class Model:
    name = "semantic_http_model"
    model = "semantic-http-model"
    endpoint = ""
    def generate_text(self, **kwargs):
        prompt = str(kwargs.get("user_prompt") or "")
        if "候选报告范围纠错器" in str(kwargs.get("system_prompt") or ""):
            text = json.dumps({"project_action": "none", "question": ""})
        elif "商品检索词补全器" in str(kwargs.get("system_prompt") or ""):
            data = json.loads(prompt)
            patch = {"research_queries": [{"subject": name, "query": "site:ebay.com/itm/ " + name}
                for name in ("adhesive cable clips", "silicone drain hair catcher")]}
            if "检索补词越界" in data["merchant_message"]:
                patch["project_action"] = "new"
            text = json.dumps(patch, ensure_ascii=False)
        elif "语义任务规划器" in str(kwargs.get("system_prompt") or ""):
            data = json.loads(prompt)
            message = data["merchant_message"]
            if "坏计划" in message:
                text = '{"project_action":"new", "company_id":"forged"}'
            elif "模型断线" in message:
                raise TimeoutError("unit provider timeout")
            else:
                action = "current" if "继续那把" in message else "clarify" if "弄一下" in message else "none" if "聊聊天" in message else "new"
                research = "研究候选" in message
                if research:
                    action = "none"
                proposals = []
                if "SPOON15" in message:
                    proposals = [
                        {"field": "material", "value": "304不锈钢和实木", "source_quote": "304不锈钢和实木"},
                        {"field": "supplier_item_number", "value": "SPOON15", "source_quote": "SPOON15"},
                        {"field": "product_dimensions_cm", "value": "18×4×2", "source_quote": "18×4×2厘米"},
                        {"field": "net_weight_g", "value": "42", "source_quote": "净重42克"},
                    ]
                if "伪造引用" in message:
                    proposals = [{"field": "material", "value": "铝", "source_quote": "本条消息没有这段来源"}]
                elif "未知字段" in message:
                    proposals = [{"field": "source_report_id", "value": "report-fake", "source_quote": "未知字段"}]
                elif "越权确认" in message:
                    proposals = [{"field": "image_rights_confirmed", "value": "true", "source_quote": "越权确认"}]
                text = json.dumps({"status": "clarification_required" if action == "clarify" else "ready",
                    "intent": "research" if research else "chat" if action == "none" else "listing", "project_action": action,
                    "research_delivery": "candidate_selection" if research else "none",
                    "research_queries": [],
                    "product_fact_proposals": proposals,
                    "product_name": "银色木柄15mL咖啡量勺" if action == "new" else "",
                    "question": "你想继续旧商品还是另建商品？" if action == "clarify" else "",
                    "search": "none", "query": "", "source_mode": "merchant_has_no_source" if research else "unknown",
                    "read_images": bool(data.get("has_new_images")) and action in {"new", "current"},
                    "save_artifact": (research or action in {"new", "current"}) and "不要保存" not in message, "candidate_count": 1,
                    "excluded_candidates": [], "listing_deferred": False, "steps": ["整理商品资料"]}, ensure_ascii=False)
                if "检索合同纠错" in message:
                    self.research_attempts = getattr(self, "research_attempts", 0) + 1
                    plan = json.loads(text)
                    queries = [{"subject": name, "query": "site:ebay.com/itm/ " + name}
                               for name in ("adhesive cable clips", "silicone drain hair catcher")]
                    plan.update(intent="research", project_action="none", product_name="", read_images=False,
                        save_artifact=True, research_delivery="candidate_selection", candidate_count=2,
                        listing_deferred=True, search="web_search", query=queries[0]["query"],
                        research_queries=queries if self.research_attempts > 1 else [])
                    text = json.dumps(plan, ensure_ascii=False)
                if "中英商品名" in message:
                    plan = json.loads(text)
                    queries = [
                        {"subject": "自粘桌面理线夹 adhesive cable clips", "query": "site:ebay.com adhesive cable clips desk"},
                        {"subject": "排水口硅胶滤网 silicone drain hair catcher", "query": "site:ebay.com silicone drain hair catcher strainer"},
                    ]
                    if "括号别名" in message:
                        queries[0]["subject"] = "自粘桌面理线夹（adhesive cable clips）"
                        queries[1]["subject"] = "排水口硅胶滤网 (silicone drain hair catcher)"
                    elif "斜线别名" in message:
                        queries[0]["subject"] = "自粘桌面理线夹 / adhesive cable clips"
                        queries[1]["subject"] = "排水口硅胶滤网 / silicone drain hair catcher"
                    plan.update(intent="research", project_action="none", product_name="", read_images=False,
                        save_artifact=True, research_delivery="candidate_selection", candidate_count=2,
                        listing_deferred=True, search="web_search", query=queries[0]["query"], research_queries=queries)
                    text = json.dumps(plan, ensure_ascii=False)
                if "源格式验收" in message:
                    plan = json.loads(text)
                    queries = [{"subject": name, "query": "site:ebay.com/itm/ source_format_fixture " + name}
                               for name in ("adhesive cable clips", "silicone drain hair catcher")]
                    plan.update(intent="research", project_action="new", product_name="两个方向的选品比较",
                        read_images=False, save_artifact=True, research_delivery="candidate_selection", candidate_count=2,
                        listing_deferred=True, search="web_search", query=queries[0]["query"], research_queries=queries)
                    text = json.dumps(plan, ensure_ascii=False)
        else:
            # Report prompt leakage as ordinary provider output so HTTP callers
            # can observe context isolation without mocking the chat function.
            old = "OLD_GOLDEN_EIGHT" in prompt or "OLD_SUPPLIER_FACT" in prompt
            if "回答断线" in prompt:
                raise TimeoutError("unit answer timeout")
            if "并发更新" in prompt:
                time.sleep(2)
            text = ("发现旧资料泄漏。" if old else "商品资料已按这次任务整理。") + " 未确认的重量、尺寸、材质、采购价和图片授权仍需核对；完成核对后可进入 Listing，发布前需要确认。"
            if "研究候选" in prompt:
                text = "### 候选商品 1：咖啡量勺\n推荐度评分：85/100\n理由：厨房计量场景明确，小件容易比较款式。尚未取得供应商来源，材质尺寸重量成本和图片权利均待核验。\n建议先自行找到货源并核对真实商品资料，再生成 Listing；当前不发布。"
            if "检索合同纠错" in prompt:
                text = ("### 候选商品 1：adhesive cable clips\n历史页面参考 [S1]，页面标价 $5.99。"
                    "供应商材质、成本、尺寸、重量和图片授权未知；风险是粘胶掉落，需实物验证。\n"
                    "| 项目 | 结论 |\n|---|---|\n| 当前在售状态 | 未验证 |\n"
                    "### 候选商品 2：silicone drain hair catcher\n历史页面参考 [S2]，页面标价 $4.99。"
                    "供应商材质、成本、尺寸、重量和图片授权未知；风险是排水口不适配，需实物验证。\n"
                    "| 项目 | 结论 |\n|---|---|\n| 当前在售状态 | 未验证 |\n"
                    "推荐先找 adhesive cable clips 的供应商并核对资料；只是待核对方向，不是销量或盈利证明。")
            if "中英商品名" in prompt:
                text = ("### 候选商品 1：自粘桌面理线夹 adhesive cable clips\n历史页面参考 [S1]，页面标价 $5.99。"
                    "当前在售状态、销量、利润未验证。供应商材质、成本、尺寸、重量和图片授权未知；风险是粘胶掉落，需实物验证。\n"
                    "### 候选商品 2：排水口硅胶滤网 silicone drain hair catcher\n历史页面参考 [S2]，页面标价 $4.99。"
                    "当前在售状态、销量、利润未验证。供应商材质、成本、尺寸、重量和图片授权未知；风险是排水口不适配，需实物验证。\n"
                    "推荐先找自粘桌面理线夹 adhesive cable clips 的供应商并核对资料；只是待核对方向，不是销量或盈利证明。")
                if "中文报告标题" in prompt:
                    text = text.replace("自粘桌面理线夹 adhesive cable clips", "自粘桌面理线夹").replace(
                        "排水口硅胶滤网 silicone drain hair catcher", "排水口硅胶滤网")
                if "交换引用" in prompt:
                    text = text.replace("[S1]", "[TEMP]").replace("[S2]", "[S1]").replace("[TEMP]", "[S2]")
            if "源格式验收" in prompt:
                text = ("### 候选商品 1：自粘理线夹 / adhesive cable clips\n历史商品参考 [S1]，单件主价 $5.99。\n"
                    "待补资料：供应商成本、包装规格、图片授权、当前在售状态、真实销量与利润。\n"
                    "### 候选商品 2：排水口滤网 / silicone drain hair catcher\n历史商品参考 [S2]，标价 $4.99。\n"
                    "当前在售状态未验证。供应商参数未知，排水口适配风险待实物检验。\n"
                    "## 市场调研正文\n### 一、自粘理线夹\n"
                    "| 来源 | 商品标题 | 可辨认价格 |\n|---|---|---|\n"
                    "| S1 | Adhesive Cable Clips Desk Organizer | $5.99（原价 $8.99） |\n"
                    "### 二、排水口滤网\n历史来源 [S2]，当前在售状态未验证，商品页不证明今天仍在售。\n"
                    "建议先找理线夹供应商，核对胶粘力和尺寸。该建议是待验证的找货方向，成交证据不足。")
                if "修复在售断言" in prompt and "上一版回复没有通过" not in str(kwargs.get("system_prompt")):
                    text += "\n多个卖家同时在售。"
        return {"text": text, "model": self.model, "model_mode": "live_unit",
            "finish_reason": "stop", "_usage": {"input_tokens": 30, "output_tokens": 40, "total_tokens": 70}}

def resolve(self, **kwargs):
    trial = "平台试用" in str((kwargs.get("body") or {}).get("message") or "")
    return {"status": "resolved", "mode": "platform_managed_default" if trial else "account_byok", "secret_ref": "unit-ref",
        "secret_ref_scope": "account", "provider_key": "unit", "model": "semantic-http-model",
        "merchant_pays_provider_directly": not trial, "model_client": Model(), "secret_exposed": False}
api.SaaSBackendHandler._resolve_model_client_for_store = resolve
class Vision:
    def analyze(self, **kwargs):
        if "视觉断线" in kwargs.get("merchant_message", ""):
            raise ProductVisionError("vision_unit_failure", "Unit vision unavailable")
        return {"analysis": {"product_name": {"value": "银色木柄15mL咖啡量勺", "confidence": .99, "image_indexes": [1]},
            "facts": {"material": {"value": "new image wood", "confidence": .99, "image_indexes": [1]}}},
            "usage": {"input_tokens": 17, "output_tokens": 9, "total_tokens": 26}}
api.fal_product_vision_client_from_env = lambda: Vision()
from jiejing_saas import ai_ceo_chat as chat
class ResearchSearch:
    def provider_status(self, provider):
        return {"configured": True, "provider": provider, "secret_exposed": False}
    def probe(self, config):
        first = "adhesive cable clips" in config.query
        name, item, price = (("adhesive cable clips", "123456789001", "5.99") if first else
                             ("silicone drain hair catcher", "123456789002", "4.99"))
        # Search providers reorder English product terms; the model's subject
        # may contain a Chinese alias too. Neither is evidence of a live sale.
        title = ("12 Pcs Cable Clips Adhesive Clamps on Desk Cord Organizer Holder" if first else
                 "1Pc Silicone Hair Drain Catcher Sink Strainer Filter Shower Drain Protector")
        return {"status": "ready", "provider": config.provider, "query": config.query,
                "results": [{"title": title, "url": "https://www.ebay.com/itm/" + item,
                             "snippet": ("Was US $8.99 Item price US $5.99 You save US $3.00" if first and "source_format_fixture" in config.query else "US $" + price)},
                            {"title": "Adhesive cable ties" if first else "Silicone drain cleaning brush",
                             "url": "https://www.ebay.com/itm/123456789003", "snippet": "US $8.99"}]}
chat.PublicSearchProbeAdapter = ResearchSearch
def reject_network(*args, **kwargs):
    raise AssertionError("semantic HTTP fixture forbids external requests")
import urllib.request
urllib.request.urlopen = reject_network
'''


class SemanticDispatchHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="jiejing-semantic-http-", ignore_cleanup_errors=True)
        root = Path(cls.temp.name)
        hook = root / "hook"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text(model_hook(), encoding="utf-8")
        port = free_port()
        cls.base = f"http://127.0.0.1:{port}"
        cls.logs = [(root / name).open("w", encoding="utf-8") for name in ("stdout", "stderr")]
        env = isolated_backend_env(port=port, hook_root=hook)
        env["JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP"] = "100"
        cls.process = subprocess.Popen([
            sys.executable, str(ROOT / "tools/jiejing_saas_backend_cli.py"), "serve",
            "--db", str(root / "saas.sqlite"), "--runtime-db", str(root / "runtime.sqlite"),
            "--output-root", str(root / "output"), "--host", "127.0.0.1", "--port", str(port),
        ], cwd=ROOT, env=env,
            stdout=cls.logs[0], stderr=cls.logs[1])
        wait_for_health(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        for stream in cls.logs:
            stream.close()
        cls.temp.cleanup()

    def setUp(self):
        status, payload = request_json(self.base + "/auth/register", method="POST", payload={
            "email": uuid.uuid4().hex + "@example.test", "password": "local-test-password",
            "company_name": "Semantic HTTP Test",
        })
        self.assertEqual(201, status)
        self.token = payload["token"]
        status, payload = self.call("/stores", {"platform": "ebay", "store_name": "Semantic Test", "marketplace": "EBAY_US"})
        self.assertEqual(201, status)
        self.store = payload["store"]["store_id"]
        self.old_identity = {"key": "old-project", "source_report_id": "old-source", "candidate_id": "old-candidate"}
        status, self.old = self.call(f"/stores/{self.store}/product-facts", {
            "listing_project_identity": self.old_identity,
            "merchant_product_fact_packet": {"merchant_confirmed_facts": {
                "product_name": "OLD_GOLDEN_EIGHT", "material": "OLD_SUPPLIER_FACT",
                "package_weight_g": "120", "merchant_owned_product_confirmed": True,
                "image_urls": "https://example.test/old.png", "image_rights_confirmed": True,
            }, "simulation_only": True, "field_evidence": {"material": {
                "source_type": "merchant_form", "confidence": 1, "image_indexes": [],
            }}},
        })
        self.assertEqual(201, status)

    def call(self, path, payload=None):
        return request_json(self.base + path, method="POST" if payload is not None else "GET",
            payload=payload, token=self.token)

    def envelope(self, message):
        return {"message": message, "command": {"id": "cmd-" + uuid.uuid4().hex, "text": message},
            "semantic_dispatch_contract": "ai_ceo_semantic_dispatch_v1",
            "chat_archive_contract": "server_finalized_chat_archive_v1",
            "conversation_history": [{"user_text": "OLD_GOLDEN_EIGHT", "assistant_text": "旧项目"}],
            "active_listing_context": {"contract_version": "active_listing_context_v1",
                "listing_project_identity": self.old_identity, "product_name": "OLD_GOLDEN_EIGHT",
                "listing": {"known_facts": {"material": "OLD_SUPPLIER_FACT"}}},
            "supplier_facts": {"material": "OLD_SUPPLIER_FACT"}, "supplier_facts_verified": True}

    def reports(self):
        status, payload = self.call("/reports")
        self.assertEqual(200, status)
        return payload["reports"]

    def upload(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=")
        req = urllib.request.Request(self.base + f"/stores/{self.store}/media-source-assets", data=png,
            method="POST", headers={"Authorization": "Bearer " + self.token, "Content-Type": "image/png",
                "X-Jiejing-File-Name": "semantic-test.png"})
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.load(response)
        return payload["media_source_asset"]["asset_id"]

    def test_natural_new_product_has_server_anchor_and_preserves_old_product(self):
        body = self.envelope("这回换一款，银色木柄15mL咖啡量勺，单只装，请单独整理。")
        before = self.reports()
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertIn(status, (200, 201, 202), payload)
        dispatch = payload.get("semantic_dispatch") or {}
        self.assertEqual("ready", dispatch.get("status"), payload)
        self.assertEqual("new", dispatch.get("project_action"))
        self.assertEqual(self.old_identity, dispatch["submitted_project_identity"])
        target = dispatch["target_project_identity"]
        self.assertNotEqual(self.old_identity["key"], target["key"])
        self.assertEqual(target, payload["ai_ceo_chat"]["listing_project_identity"])
        self.assertEqual(dispatch, payload["ai_ceo_chat"]["semantic_dispatch"])
        self.assertNotIn("旧资料泄漏", payload["ai_ceo_chat"]["answer"])
        self.assertFalse(payload["ai_ceo_chat"]["supplier_facts_verified"])
        after = self.reports()
        anchor = next(item for item in after if item["report_id"] == target["source_report_id"])
        self.assertEqual(target, anchor["report"]["listing_project_identity"])
        self.assertEqual("merchant.product_facts", anchor["report_type"])
        self.assertEqual(dispatch, anchor["report"].get("semantic_dispatch"))
        self.assertTrue(anchor["report"]["merchant_product_fact_packet"]["unknown_facts"])
        for old_report in before:
            self.assertEqual(old_report, next(item for item in after if item["report_id"] == old_report["report_id"]))

    def test_replay_keeps_archive_dispatch_and_two_provider_calls_only_once(self):
        body = self.envelope("另外准备银色木柄15mL咖啡量勺这个商品的资料。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, first = self.call(path, body)
        self.assertEqual(201, status, first)
        first_reports = self.reports()
        status, replay = self.call(path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["semantic_dispatch"], replay["semantic_dispatch"])
        self.assertEqual(first_reports, self.reports())
        status, history = self.call("/ai-ceo/chat-history")
        self.assertEqual(200, status, history)
        turns = history.get("turns") or history.get("ai_ceo_chat_history", {}).get("turns") or []
        self.assertTrue(turns, history)
        self.assertEqual(first["semantic_dispatch"], turns[-1].get("semantic_dispatch"))
        status, tasks = self.call("/tasks")
        self.assertEqual(200, status)
        chats = [t for t in tasks["tasks"] if t["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(1, len(chats))
        self.assertEqual(2, chats[0]["output"]["model_request_count"])

    def test_new_text_facts_are_saved_as_unconfirmed_suggestions(self):
        body = self.envelope("这回单独整理银色木柄15mL咖啡量勺，材质304不锈钢和实木，货号SPOON15，尺寸18×4×2厘米，净重42克。")
        before = self.reports()
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload)
        dispatch = payload["semantic_dispatch"]
        self.assertEqual("new", dispatch["project_action"])
        expected = {"material": "304不锈钢和实木", "supplier_item_number": "SPOON15",
                    "product_dimensions_cm": "18×4×2", "net_weight_g": "42"}
        after = self.reports()
        anchor = next(item for item in after if item["report_id"] == dispatch["target_project_identity"]["source_report_id"])
        packet = anchor["report"]["merchant_product_fact_packet"]
        for field, value in expected.items():
            self.assertEqual(value, packet["derived_listing_suggestions"].get(field), field)
            self.assertNotIn(field, packet["merchant_confirmed_facts"])
            self.assertNotIn(field, packet["source_confirmed_facts"])
        self.assertFalse(packet["listing_readiness"]["ready_for_real_publish"])
        self.assertEqual(packet, payload["product_vision_fact_packet"])
        self.assertEqual(anchor["report"], payload["product_vision_report"]["report"])
        for field in ("report_id", "task_id", "company_id", "store_id", "status", "report_type"):
            self.assertEqual(anchor[field], payload["product_vision_report"][field])
        self.assertEqual(dispatch, anchor["report"]["semantic_dispatch"])
        self.assertEqual("saved", anchor["status"])
        self.assertTrue(anchor["task_id"])
        self.assertEqual(dispatch["company_id"], anchor["company_id"])
        self.assertEqual(dispatch["store_id"], anchor["store_id"])
        self.assertIsNone(payload["product_vision_task"])
        self.assertEqual([], dispatch["consumed_source_asset_ids"])
        self.assertEqual(packet, payload["ai_ceo_market_report"]["report"]["merchant_product_fact_packet"])
        self.assertEqual(before, [item for item in after if item["report_id"] in {old["report_id"] for old in before}])

    def test_new_image_and_text_facts_preserve_both_sources_without_confirmation(self):
        body = self.envelope("这次单独整理银色木柄15mL咖啡量勺：材质304不锈钢和实木，货号SPOON15，尺寸18×4×2厘米，净重42克。结合本轮图片核对。")
        body["source_asset_ids"] = [self.upload()]
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload)
        packet = payload["product_vision_fact_packet"]
        self.assertEqual("304不锈钢和实木", packet["derived_listing_suggestions"]["material"])
        self.assertEqual("SPOON15", packet["derived_listing_suggestions"]["supplier_item_number"])
        self.assertEqual("18×4×2", packet["derived_listing_suggestions"]["product_dimensions_cm"])
        self.assertEqual("42", packet["derived_listing_suggestions"]["net_weight_g"])
        self.assertEqual("304不锈钢和实木", packet["field_evidence"]["material"]["source_quote"])
        self.assertFalse(packet["merchant_confirmed_facts"])
        self.assertFalse(packet["source_confirmed_facts"])
        self.assertTrue(any(x.get("field") == "material" and "new image wood" in x["values"] for x in packet["fact_conflicts"]))
        self.assertTrue(any(x.get("asset_id") == body["source_asset_ids"][0] and x["rights_status"] == "pending_merchant_confirmation" for x in packet["source_records"]))
        self.assertEqual(body["source_asset_ids"], payload["semantic_dispatch"]["consumed_source_asset_ids"])
        self.assertEqual(self.old["report"], next(item for item in self.reports() if item["report_id"] == self.old["report"]["report_id"]))

    def test_current_text_suggestions_preserve_confirmed_facts_rights_and_edited_copy(self):
        repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        previous = {**self.old["merchant_product_fact_packet"],
                    "listing_copy": {"title": "Merchant edited old title", "description": "Keep this old description"}}
        repository.save_merchant_product_fact_report(task=self.old["task"], packet=previous,
            listing_project_identity=self.old_identity)
        body = self.envelope("继续那把量勺，补充待核对资料：材质304不锈钢和实木，货号SPOON15，尺寸18×4×2厘米，净重42克。")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload)
        self.assertEqual(self.old_identity, payload["semantic_dispatch"]["target_project_identity"])
        packet = payload["product_vision_fact_packet"]
        self.assertEqual(previous["merchant_confirmed_facts"], packet["merchant_confirmed_facts"])
        self.assertEqual(previous["listing_copy"], packet["listing_copy"])
        self.assertEqual(previous["field_evidence"]["material"], packet["field_evidence"]["material"])
        self.assertEqual("304不锈钢和实木", packet["pending_field_evidence"]["material"]["source_quote"])
        self.assertTrue(packet["simulation_only"])
        self.assertEqual("304不锈钢和实木", packet["derived_listing_suggestions"]["material"])
        self.assertEqual("42", packet["derived_listing_suggestions"]["net_weight_g"])
        self.assertTrue(any(x["field"] == "material" for x in packet["fact_conflicts"]))
        self.assertTrue(any(x.get("rights_status") == "merchant_confirmed" for x in packet["source_records"]))
        self.assertEqual(packet, payload["ai_ceo_market_report"]["report"]["merchant_product_fact_packet"])
        self.assertIsNone(payload["product_vision_task"])

    def test_invalid_text_proposals_fail_closed_before_image_or_product_writes(self):
        before = self.reports()
        for case in ("伪造引用", "未知字段", "越权确认"):
            with self.subTest(case=case):
                body = self.envelope("另外整理商品。" + case)
                body["source_asset_ids"] = [self.upload()]
                status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertEqual(202, status, payload)
                self.assertEqual("blocked", payload["semantic_dispatch"]["status"])
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertEqual([], payload["semantic_dispatch"]["consumed_source_asset_ids"])
                self.assertIsNone(payload["merchant_ceo_command"])
                self.assertEqual(before, self.reports())
        _, tasks = self.call("/tasks")
        self.assertFalse(any(x["task_type"] == "ai_ceo_product_vision" for x in tasks["tasks"]))

    def test_current_image_suggestions_preserve_confirmed_values_and_rights(self):
        body = self.envelope("继续那把原来的量勺，看看本轮图片有没有差异。")
        body["source_asset_ids"] = [self.upload()]
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload)
        dispatch = payload["semantic_dispatch"]
        self.assertEqual("current", dispatch["project_action"])
        self.assertEqual(self.old_identity, dispatch["target_project_identity"])
        self.assertEqual(body["source_asset_ids"], dispatch["consumed_source_asset_ids"])
        report = payload["product_vision_report"]["report"]
        packet = report["merchant_product_fact_packet"]
        old_packet = self.old["merchant_product_fact_packet"]
        self.assertEqual(old_packet["merchant_confirmed_facts"], packet["merchant_confirmed_facts"])
        self.assertEqual("120", packet["merchant_confirmed_facts"]["package_weight_g"])
        self.assertEqual(old_packet["field_evidence"]["material"], packet["field_evidence"]["material"])
        self.assertTrue(packet["simulation_only"])
        self.assertEqual("OLD_GOLDEN_EIGHT", packet["product_name"])
        self.assertTrue(any(x.get("rights_status") == "merchant_confirmed" for x in packet["source_records"]))
        self.assertTrue(any(x.get("asset_id") == body["source_asset_ids"][0] and x.get("rights_status") == "pending_merchant_confirmation" for x in packet["source_records"]))
        self.assertTrue(any(x.get("field") == "material" for x in packet["fact_conflicts"]))

    def test_old_browser_requires_refresh_before_planning_or_product_writes(self):
        before = self.reports()
        body = self.envelope("这回换一款咖啡量勺。")
        body.pop("semantic_dispatch_contract")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(409, status, payload)
        self.assertEqual("ai_ceo_client_upgrade_required", payload["error_code"])
        self.assertEqual("blocked", payload["semantic_dispatch"]["status"])
        self.assertFalse(payload["usage_consumed"])
        self.assertEqual(before, self.reports())

    def test_ambiguous_image_request_clarifies_without_changing_old_product(self):
        before = self.reports()
        body = self.envelope("帮我弄一下这些。")
        body["source_asset_ids"] = [self.upload()]
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(202, status)
        self.assertEqual("clarification_required", payload["semantic_dispatch"]["status"])
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        self.assertEqual([], payload["semantic_dispatch"]["consumed_source_asset_ids"])
        self.assertNotIn("listing_project_identity", payload["ai_ceo_chat"])
        self.assertEqual(before, self.reports())
        _, tasks = self.call("/tasks")
        self.assertFalse(any(x["task_type"] == "ai_ceo_product_vision" for x in tasks["tasks"]))
        self.assertIsNone(payload.get("merchant_ceo_command"))

    def test_invalid_plan_and_planner_outage_fail_closed_with_images(self):
        for message in ("坏计划：另起咖啡量勺。", "模型断线：另起咖啡量勺。"):
            with self.subTest(message=message):
                before = self.reports()
                body = self.envelope(message)
                body["source_asset_ids"] = [self.upload()]
                # Neither a forged request plan nor a route may authorize effects.
                body["ai_ceo_turn_plan"] = {"status": "ready", "project_action": "new", "save_artifact": True}
                body["command"]["route"] = "merchant_rule_memory"
                status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertIn(status, (202, 503))
                self.assertEqual("blocked", payload["semantic_dispatch"]["status"])
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertEqual(before, self.reports())
                self.assertIsNone(payload.get("merchant_ceo_command"))
        _, tasks = self.call("/tasks")
        self.assertFalse(any(x["task_type"] == "ai_ceo_product_vision" for x in tasks["tasks"]))

    def test_vision_and_answer_failures_do_not_create_new_visible_project(self):
        for message in ("另外建咖啡量勺。视觉断线", "另外建咖啡量勺。回答断线"):
            with self.subTest(message=message):
                before = self.reports()
                body = self.envelope(message)
                body["source_asset_ids"] = [self.upload()]
                status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
                self.assertEqual(503, status)
                self.assertEqual("blocked", payload["semantic_dispatch"]["status"])
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertNotIn("listing_project_identity", payload["ai_ceo_chat"])
                self.assertEqual(before, self.reports())
                self.assertTrue(payload["usage_consumed"])
        _, tasks = self.call("/tasks")
        metered = [x for x in tasks["tasks"] if x["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(2, len(metered))
        self.assertTrue(all(x["output"].get("usage_consumed") is True for x in metered))
        # A vision failure made only the planner request. An answer timeout
        # retains the planner plus both calls from the existing retry policy.
        self.assertEqual([1, 3], sorted(x["output"]["model_request_count"] for x in metered))

    def test_current_identity_must_match_all_fields_and_the_store(self):
        # Seed a pre-existing second store using the repository's public setup
        # interface. The real HTTP chat quota/reservation checks stay enabled.
        repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        second = repository.create_store(company_id=self.old["task"]["company_id"],
            user_id=self.old["task"]["user_id"], payload={"platform": "ebay", "store_name": "Other Store", "marketplace": "EBAY_US"})
        for key in ("key", "source_report_id", "candidate_id", "store"):
            with self.subTest(key=key):
                before = self.reports()
                body = self.envelope("继续那把原来的量勺。")
                if key != "store":
                    body["active_listing_context"]["listing_project_identity"] = {**self.old_identity, key: "forged"}
                target_store = second["store_id"] if key == "store" else self.store
                status, payload = self.call(f"/stores/{target_store}/merchant-ceo/chat", body)
                self.assertEqual(202, status)
                self.assertEqual("clarification_required", payload["semantic_dispatch"]["status"])
                self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
                self.assertEqual(before, self.reports())

    def test_current_identity_from_another_merchant_cannot_be_used(self):
        # Same-looking identity fields in another tenant do not establish scope.
        status, account = request_json(self.base + "/auth/register", method="POST", payload={
            "email": uuid.uuid4().hex + "@example.test", "password": "local-test-password", "company_name": "Other Merchant"})
        self.assertEqual(201, status)
        other_token = account["token"]
        status, store = request_json(self.base + "/stores", method="POST", token=other_token,
            payload={"platform": "ebay", "store_name": "Other Merchant", "marketplace": "EBAY_US"})
        self.assertEqual(201, status)
        before = self.reports()
        status, payload = request_json(self.base + f"/stores/{store['store']['store_id']}/merchant-ceo/chat",
            method="POST", token=other_token, payload=self.envelope("继续那把原来的量勺。"))
        self.assertEqual(202, status)
        self.assertEqual("clarification_required", payload["semantic_dispatch"]["status"])
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        self.assertEqual(before, self.reports())

    def test_general_chat_does_not_bind_the_open_product(self):
        before = self.reports()
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", self.envelope("今天聊聊天就好。"))
        self.assertEqual(201, status)
        self.assertEqual("none", payload["semantic_dispatch"]["project_action"])
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        self.assertNotIn("listing_project_identity", payload["ai_ceo_chat"])
        self.assertEqual(before, self.reports())

    def test_http_quota_ignores_internal_records_but_keeps_real_limit_and_replay(self):
        repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        scope = {"company_id": self.old["task"]["company_id"], "store_id": self.store,
                 "user_id": self.old["task"]["user_id"]}
        _, initial = self.call("/billing/usage")
        limit = next(row["limit"] for row in initial["billing_usage"]["quota_status"] if row["unit"] == "ai_ceo_task")
        for kind in ("ai_ceo_chat_request", "merchant_ceo_chat_attempt", "merchant_product_facts", "ai_ceo_product_vision"):
            for _ in range(30):
                repository.create_task(**scope, task_type=kind, title="internal fixture", input_data={})
        for _ in range(limit - 1):
            repository.create_task(**scope, task_type="product_workflow", title="business fixture", input_data={})
        before = self.reports()
        body = self.envelope("只聊聊天，不改动商品。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, first = self.call(path, body)
        self.assertEqual(201, status, first.get("ai_ceo_chat", {}).get("blocked_by"))
        self.assertEqual("ready", first["semantic_dispatch"]["status"])
        self.assertEqual(before, self.reports())
        _, usage = self.call("/billing/usage")
        self.assertEqual(limit, usage["billing_usage"]["usage"]["monthly_task_count"])
        status, replay = self.call(path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        for _ in range(2):
            status, blocked = self.call(path, self.envelope("聊聊天，再发起一次。"))
            self.assertEqual(402, status)
            self.assertFalse(blocked["usage_consumed"])
            self.assertIn("subscription_quota_blocked", blocked["ai_ceo_chat"]["blocked_by"])
        _, usage = self.call("/billing/usage")
        self.assertEqual(limit, usage["billing_usage"]["usage"]["monthly_task_count"])
        _, tasks = self.call("/tasks")
        chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(1, len(chats))
        self.assertEqual(2, chats[0]["output"]["model_request_count"])
        self.assertEqual(before, self.reports())

    def test_idempotency_conflict_also_carries_an_unbound_receipt(self):
        body = self.envelope("另外整理咖啡量勺。")
        _, first = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual("ready", first["semantic_dispatch"]["status"])
        before = self.reports()
        body["message"] = "改了原请求内容。"
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(409, status)
        self.assertEqual("blocked", payload.get("semantic_dispatch", {}).get("status"))
        self.assertFalse(payload["semantic_dispatch"]["request_task_id"])
        self.assertNotIn(first["semantic_dispatch"]["request_task_id"], json.dumps(payload))
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        self.assertEqual(payload["semantic_dispatch"], payload["ai_ceo_chat"]["semantic_dispatch"])
        self.assertEqual(before, self.reports())

    def test_research_candidate_can_be_selected_without_inheriting_open_product(self):
        body = self.envelope("没有货源，请先研究候选，只推荐一款轻小商品。")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status, payload.get("ai_ceo_chat", {}).get("status"))
        self.assertEqual("none", payload["semantic_dispatch"]["project_action"])
        self.assertEqual({}, payload["semantic_dispatch"]["target_project_identity"])
        report = payload["ai_ceo_market_report"]
        self.assertTrue(report)
        self.assertFalse(report["report"].get("listing_project_identity"))
        candidate = report["report"]["product_candidates"][0]
        candidate_identity = candidate.get("listing_project_identity")
        self.assertTrue(candidate_identity)
        self.assertEqual(report["report_id"], candidate_identity["source_report_id"])
        followup = self.envelope("继续那把刚选的咖啡量勺，先看看还缺哪些资料。")
        followup["active_listing_context"]["listing_project_identity"] = candidate_identity
        status, continued = self.call(f"/stores/{self.store}/merchant-ceo/chat", followup)
        self.assertEqual(201, status, continued.get("ai_ceo_chat", {}).get("status"))
        self.assertEqual("ready", continued["semantic_dispatch"]["status"])
        self.assertEqual(candidate_identity, continued["semantic_dispatch"]["target_project_identity"])
        self.assertEqual("咖啡量勺", continued["ai_ceo_chat"]["context"]["active_listing_context"]["product_name"])

    def test_open_research_repairs_queries_and_saves_only_its_evidence_report(self):
        before = self.reports()
        body = self.envelope("无货源研究候选，检索合同纠错：联网比较两种商品，保存报告，不建项目，不改旧商品。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, result = self.call(path, body)
        self.assertEqual(201, status, result.get("ai_ceo_chat", {}).get("blocked_by"))
        self.assertEqual("ready", result["semantic_dispatch"]["status"])
        self.assertEqual("none", result["semantic_dispatch"]["project_action"])
        self.assertEqual({}, result["semantic_dispatch"]["target_project_identity"])
        self.assertIsNone(result.get("product_vision_report"))
        self.assertTrue(result["ai_ceo_chat"]["answer_quality"]["accepted"])
        report = result["ai_ceo_market_report"]
        self.assertTrue(report)
        self.assertEqual(2, len(report["report"]["product_candidates"]))
        self.assertNotIn("OLD_GOLDEN_EIGHT", result["ai_ceo_chat"]["answer"])
        after = self.reports()
        self.assertEqual(before, [item for item in after if item["report_id"] != report["report_id"]])
        status, replay = self.call(path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(after, self.reports())
        _, tasks = self.call("/tasks")
        chats = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(1, len(chats))
        self.assertEqual(3, chats[0]["output"]["model_request_count"])

    def test_real_source_formats_save_two_candidates_without_creating_product_or_changing_old_facts(self):
        for suffix in ("", "修复在售断言"):
            before = self.reports()
            body = self.envelope("无货源研究候选，源格式验收。保存比较报告，不建项目，不改旧商品。" + suffix)
            path = f"/stores/{self.store}/merchant-ceo/chat"
            status, result = self.call(path, body)
            self.assertEqual(201, status, result.get("ai_ceo_chat", {}).get("answer_quality"))
            self.assertEqual("none", result["semantic_dispatch"]["project_action"])
            self.assertEqual({}, result["semantic_dispatch"]["target_project_identity"])
            self.assertIsNone(result.get("product_vision_report"))
            self.assertTrue(result["ai_ceo_chat"]["answer_quality"]["accepted"])
            self.assertNotIn("多个卖家同时在售", result["ai_ceo_chat"]["answer"])
            report = result["ai_ceo_market_report"]
            self.assertEqual(2, len(report["report"]["product_candidates"]))
            after = self.reports()
            self.assertEqual(before, [item for item in after if item["report_id"] != report["report_id"]])
            status, replay = self.call(path, body)
            self.assertEqual(201, status)
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(after, self.reports())

    def test_query_completion_cannot_create_a_project_or_change_reports(self):
        before = self.reports()
        body = self.envelope("无货源研究候选，检索合同纠错，检索补词越界。只保存选品报告，不建项目。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, result = self.call(path, body)
        self.assertEqual(202, status)
        self.assertEqual("blocked", result["semantic_dispatch"]["status"])
        self.assertEqual({}, result["semantic_dispatch"]["target_project_identity"])
        self.assertIsNone(result.get("ai_ceo_market_report"))
        self.assertIsNone(result.get("product_vision_report"))
        self.assertIsNone(result.get("merchant_ceo_command"))
        self.assertEqual(before, self.reports())
        replay_status, replay = self.call(path, body)
        self.assertEqual(202, replay_status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(before, self.reports())

    def test_bilingual_research_subjects_keep_matching_english_pages_without_old_product_changes(self):
        before = self.reports()
        body = self.envelope("无货源研究候选：中英商品名，比较自粘桌面理线夹和排水口硅胶滤网。保存报告，不建项目。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        status, result = self.call(path, body)
        self.assertEqual(201, status, result.get("ai_ceo_chat", {}).get("blocked_by"))
        answer = result["ai_ceo_chat"]
        self.assertEqual("model_answered", answer["status"], answer.get("answer_quality"))
        self.assertTrue(answer["answer_quality"]["accepted"])
        self.assertEqual({"https://www.ebay.com/itm/123456789001", "https://www.ebay.com/itm/123456789002"},
                         {record["url"] for record in answer["source_records"]})
        self.assertEqual("none", result["semantic_dispatch"]["project_action"])
        self.assertEqual({}, result["semantic_dispatch"]["target_project_identity"])
        self.assertIsNone(result.get("product_vision_report"))
        report = result["ai_ceo_market_report"]
        self.assertEqual(2, len(report["report"]["product_candidates"]))
        after = self.reports()
        self.assertEqual(before, [item for item in after if item["report_id"] != report["report_id"]])
        status, replay = self.call(path, body)
        self.assertEqual(201, status)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(after, self.reports())

    def test_chinese_report_names_bind_to_explicit_planned_aliases_not_peer_sources(self):
        for spelling in ("空格别名", "括号别名", "斜线别名"):
            with self.subTest(spelling=spelling):
                body = self.envelope("无货源研究候选：中英商品名，中文报告标题，" + spelling + "。保存报告，不建项目。")
                path = f"/stores/{self.store}/merchant-ceo/chat"
                status, result = self.call(path, body)
                self.assertEqual(201, status, result.get("ai_ceo_chat", {}).get("answer_quality"))
                self.assertEqual("model_answered", result["ai_ceo_chat"]["status"])
                self.assertEqual({"自粘桌面理线夹", "排水口硅胶滤网"},
                    {item["name"] for item in result["ai_ceo_market_report"]["report"]["product_candidates"]})
                before = self.reports()
                status, wrong = self.call(path, self.envelope(body["message"] + "交换引用。"))
                self.assertEqual(202, status)
                self.assertIn("research_candidate_source_mismatch", wrong["ai_ceo_chat"]["answer_quality"]["blocked_by"])
                self.assertIsNone(wrong.get("ai_ceo_market_report"))
                self.assertEqual(before, self.reports())

    def test_platform_trial_counts_one_turn_for_two_calls_and_blocks_after_twenty(self):
        first_body = self.envelope("平台试用，聊聊天。")
        path = f"/stores/{self.store}/merchant-ceo/chat"
        for index in range(20):
            body = first_body if index == 0 else self.envelope("平台试用，聊聊天。")
            status, payload = self.call(path, body)
            self.assertEqual(201, status, payload.get("ai_ceo_chat", {}).get("blocked_by"))
            quota = payload["model_secret_resolution"]["platform_trial_quota"]
            self.assertEqual(20, quota["trial_limit"])
            self.assertEqual(index, quota["used"])
            self.assertEqual("backend_model_task_audit_and_atomic_reservations", quota["quota_source"])
            if index == 0:
                replay_status, replay = self.call(path, first_body)
                self.assertEqual(201, replay_status)
                self.assertTrue(replay["idempotent_replay"])
        status, blocked = self.call(path, self.envelope("平台试用，聊聊天。"))
        self.assertEqual(402, status)
        self.assertFalse(blocked["usage_consumed"])
        self.assertEqual("blocked", blocked["semantic_dispatch"]["status"])
        _, tasks = self.call("/tasks")
        model_tasks = [item for item in tasks["tasks"] if item["task_type"] == "merchant_ceo_chat"]
        self.assertEqual(20, len(model_tasks))
        self.assertTrue(all(item["output"]["model_request_count"] == 2 for item in model_tasks))

    def test_concurrent_merchant_save_wins_over_late_image_suggestions(self):
        body = self.envelope("继续那把量勺，识别图片；并发更新测试。")
        body["source_asset_ids"] = [self.upload()]
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.call, f"/stores/{self.store}/merchant-ceo/chat", body)
            deadline = time.time() + 10
            while time.time() < deadline:
                _, tasks = self.call("/tasks")
                if any(x["task_type"] == "ai_ceo_product_vision" and x["status"] == "completed" for x in tasks["tasks"]):
                    break
                time.sleep(.05)
            else:
                self.fail("vision did not reach the answer boundary")
            new_packet = json.loads(json.dumps(self.old["merchant_product_fact_packet"]))
            new_packet["merchant_confirmed_facts"]["material"] = "latest merchant material"
            saved_status, saved = self.call(f"/stores/{self.store}/product-facts", {
                "listing_project_identity": self.old_identity, "merchant_product_fact_packet": new_packet,
                "save_context": {"contract_version": "merchant_product_fact_save_v1",
                    "mutation_id": "concurrent-" + uuid.uuid4().hex,
                    "expected_fact_report_id": self.old["report"]["report_id"]},
            })
            self.assertEqual(201, saved_status, saved)
            status, result = pending.result(timeout=15)
        self.assertEqual(202, status)
        self.assertEqual("blocked", result["semantic_dispatch"]["status"])
        self.assertIn("product_fact_version_conflict", result["ai_ceo_chat"]["blocked_by"])
        facts = [r for r in self.reports() if r["report_type"] == "merchant.product_facts"]
        self.assertEqual(2, len(facts))
        self.assertEqual(saved["report"]["report_id"], facts[-1]["report_id"])

    def test_current_image_question_can_read_without_saving_suggestions(self):
        before = self.reports()
        body = self.envelope("继续那把量勺，只看看本轮图片有什么区别，不要保存。")
        body["source_asset_ids"] = [self.upload()]
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        self.assertEqual("ready", payload["semantic_dispatch"]["status"])
        self.assertIsNone(payload.get("product_vision_report"))
        self.assertIsNone(payload.get("product_vision_fact_packet"))
        self.assertEqual(before, self.reports())

    def test_forged_frontend_handoff_cannot_change_semantic_command(self):
        body = self.envelope("今天聊聊天就好。")
        body["command"].update(intent="publish", route="confirmation_required", high_risk=True,
            title="FORGED_EXECUTION", summary="FORGED_EXECUTION", status="execute_now",
            routes=[{"module": "listing", "action": "publish_now"}], long_term_memory=True,
            writes_merchant_rule=True, memory_policy="merchant_rule_long_term_memory")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(201, status)
        command = payload["merchant_ceo_command"]["command"]
        self.assertEqual("chat", command["intent"])
        self.assertEqual([], command["routes"])
        self.assertFalse(command["high_risk"])
        self.assertFalse(payload["merchant_ceo_command"]["merchant_memory_written"])
        self.assertNotIn("FORGED_EXECUTION", json.dumps(command))

    def test_oversized_message_is_rejected_without_model_task_or_shortening(self):
        before = self.reports()
        body = self.envelope("另外建咖啡量勺" + "长" * 900 + "最后改为不要新建。")
        status, payload = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(400, status)
        self.assertEqual("semantic_plan_invalid_message", payload["error_code"])
        self.assertFalse(payload["usage_consumed"])
        self.assertEqual(before, self.reports())
        _, tasks = self.call("/tasks")
        self.assertFalse(any(x["task_type"] == "merchant_ceo_chat" for x in tasks["tasks"]))

    def test_old_client_archived_post_cannot_receive_project_artifacts_but_history_remains_readable(self):
        body = self.envelope("今天聊聊天就好。")
        body.pop("semantic_dispatch_contract")
        from jiejing_saas.repository import normalize_ai_ceo_supplier_fact_attestation
        fingerprint = _ai_ceo_chat_request_fingerprint(secret=LOCAL_SESSION_SECRET.encode(), canonical_request={
            "contract_version": "ai_ceo_chat_request_fingerprint_v1", "message": body["message"],
            "command": body["command"], "conversation_history": body["conversation_history"],
            "source_asset_ids": [], "listing_project_identity": {},
            "active_listing_context": body["active_listing_context"],
            "supplier_fact_attestation": normalize_ai_ceo_supplier_fact_attestation(supplier_facts=body["supplier_facts"],
                supplier_facts_verified=body["supplier_facts_verified"], source="authenticated_merchant_request"),
            "client_now": "", "client_timezone": "", "chat_archive_contract": body["chat_archive_contract"],
        })
        repository = SaaSRepository(Path(self.temp.name) / "saas.sqlite", database_engine="sqlite", database_url="")
        scope = {"company_id": self.old["task"]["company_id"], "store_id": self.store}
        request = repository.claim_ai_ceo_chat_request(**scope, user_id=self.old["task"]["user_id"],
            idempotency_key="ai-ceo:" + body["command"]["id"], payload_fingerprint=fingerprint,
            archive_context={"contract_version": body["chat_archive_contract"], "user_text": body["message"]})
        repository.finalize_ai_ceo_chat_request(**scope, request_task_id=request["request_task"]["task_id"],
            terminal_status="completed", response_status=201,
            response_payload={"ai_ceo_chat": {"status": "model_answered", "answer": "已归档旧回复。",
                "listing_project_identity": self.old_identity}, "usage_consumed": True,
                "product_vision_report": self.old["report"], "product_vision_fact_packet": self.old["merchant_product_fact_packet"],
                "ai_ceo_market_report": self.old["report"], "listing_draft_prefill_ready": True})
        before = self.reports()
        status, replay = self.call(f"/stores/{self.store}/merchant-ceo/chat", body)
        self.assertEqual(409, status, replay)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual("ai_ceo_client_upgrade_required", replay["error_code"])
        self.assertFalse(replay["usage_consumed"])
        for field in ("product_vision_report", "product_vision_fact_packet", "ai_ceo_market_report", "listing_draft_prefill_ready"):
            self.assertFalse(replay.get(field), field)
        self.assertEqual({}, replay["semantic_dispatch"]["target_project_identity"])
        self.assertNotIn("listing_project_identity", replay["ai_ceo_chat"])
        self.assertEqual(before, self.reports())
        history_status, history = self.call("/ai-ceo/chat-history")
        self.assertEqual(200, history_status)
        turns = history.get("turns") or history.get("ai_ceo_chat_history", {}).get("turns") or []
        self.assertTrue(any(turn["assistant_text"] == "已归档旧回复。" for turn in turns), history)
        _, tasks = self.call("/tasks")
        self.assertFalse(any(x["task_type"] == "merchant_ceo_chat" for x in tasks["tasks"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
