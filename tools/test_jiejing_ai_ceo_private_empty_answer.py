#!/usr/bin/env python3
"""Private BYOK resolution -> real SSE adapter -> chat -> shared usage, offline."""
from __future__ import annotations

import json
import gc
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiejing_saas.ai_ceo_chat import run_ai_ceo_chat
from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.operations_metering import MeteredModelClient
from jiejing_saas.repository import SaaSRepository

FIXTURE_KEY = "unit-test-private-recovery-key"
PRIVATE_REASONING = "unit-test-hidden-reasoning"
VALID_ANSWER = "候选商品 1：行李拉链固定夹\n推荐依据：旅行收纳场景；不带电。\n主要风险：尺寸和材质待核。\n建议先找货，成本、售价、发货地和图片权利待确认；暂无可靠销量数据，不采购、不发布。"


class Response:
    def __init__(self, text="", finish="length", tokens=2400):
        self.body = {"choices": [{"message": {"content": text}, "finish_reason": finish}],
                     "usage": {"prompt_tokens": 100, "completion_tokens": tokens, "total_tokens": 100 + tokens}}
        events = [
            {"choices": [{"delta": {"reasoning_content": PRIVATE_REASONING}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": text}, "finish_reason": finish}]},
            {"choices": [], "usage": self.body["usage"]},
        ]
        self.lines = [f"data: {json.dumps(event)}\n".encode() for event in events]

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def __iter__(self): return iter(self.lines)
    def read(self): return json.dumps(self.body).encode()


class PrivateEmptyAnswerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jiejing-private-recovery-")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.env = patch.dict(os.environ, {"JIEJING_MODEL_DISABLE_LIVE": "0",
            "JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_ENABLED": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.repo = SaaSRepository(Path(self.tmp.name) / "fixture.sqlite")
        account = self.repo.create_user_with_company(email="private-recovery@example.test",
            password="unit-test-only-password", company_name="Offline recovery fixture")
        self.identity = {"user_id": account["user"]["user_id"], "company_id": account["company"]["company_id"]}
        self.store = self.repo.create_store(**self.identity, payload={"platform": "ebay", "marketplace": "EBAY_US"})
        self.repo.create_secret_reference(**self.identity, store_id=None, provider="model.deepseek",
            purpose="model_api_key", status="ready", metadata={"provider_key": "deepseek",
                "model": "deepseek-v4-pro", "model_connection_scope": "account", "base_url": "https://api.deepseek.com"})
        self.handler = SaaSBackendHandler.__new__(SaaSBackendHandler)
        self.handler.repository = self.repo
        self.handler.settings = SimpleNamespace(is_production_like=True, output_root=Path(self.tmp.name))
        self.calls = []
        self.deltas = []

    def run_chat(self, responses, *, tier="pro"):
        with patch("jiejing_saas.api_server.VaultSecretResolver.resolve_secret",
                   return_value={"ok": True, "secret_value": FIXTURE_KEY}):
            resolution = self.handler._resolve_model_client_for_store(identity=self.identity,
                store_id=self.store["store_id"], body={"ai_ceo_turn_plan": {"model_tier": tier}})
        self.assertEqual(resolution["mode"], "account_byok")
        metered = MeteredModelClient(resolution["model_client"])

        def provider(request, timeout):
            # The only fake boundary is HTTP transport; never call a live model.
            self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + FIXTURE_KEY)
            payload = json.loads(request.data)
            self.calls.append(payload)
            self.assertLessEqual(len(self.calls), len(responses), "Unexpected extra paid request")
            value = responses[len(self.calls) - 1]
            if isinstance(value, Exception): raise value
            return value

        with patch("jiejing_runtime.model_clients.urllib.request.urlopen", provider):
            result = run_ai_ceo_chat(repository=self.repo, **self.identity, store_id=self.store["store_id"],
                message="我没有货源，请推荐一个轻小、不带电的 eBay 选品方向，未知规格待找货确认。",
                model_client=metered, model_resolution={key: value for key, value in resolution.items() if key != "model_client"},
                on_text_delta=self.deltas.append)
        self.assertNotIn(FIXTURE_KEY, json.dumps(result))
        self.assertNotIn(PRIVATE_REASONING, json.dumps(result) + "".join(self.deltas))
        return result, metered.usage_summary()

    def test_same_private_connection_recovers_empty_reasoning_budget_once(self):
        result, usage = self.run_chat([Response(), Response(VALID_ANSWER, "stop", 90)])
        self.assertEqual(result["status"], "model_answered")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual([call["model"] for call in self.calls], ["deepseek-v4-pro"] * 2)
        self.assertEqual([call["thinking"]["type"] for call in self.calls], ["enabled", "disabled"])
        self.assertEqual(usage, {"request_count": 2, "input_tokens": 200, "output_tokens": 2490, "total_tokens": 2690})

    def test_empty_recovery_stops_after_one_extra_call(self):
        result, usage = self.run_chat([Response(), Response()])
        self.assertEqual(result["provider_error_type"], "empty_model_answer")
        self.assertEqual(usage["request_count"], 2)

    def test_recovery_does_not_recurse_on_truncation_or_quality_failure(self):
        result, usage = self.run_chat([Response(), Response("### 候选商品\n|", "length", 2400)])
        self.assertNotEqual(result["status"], "model_answered")
        self.assertEqual(usage["request_count"], 2)

    def test_empty_stop_is_not_reasoning_exhaustion(self):
        result, usage = self.run_chat([Response(finish="stop")])
        self.assertEqual(result["provider_error_type"], "empty_model_answer")
        self.assertEqual(usage["request_count"], 1)

    def test_authentication_failure_is_not_retried(self):
        result, usage = self.run_chat([RuntimeError("model HTTP 401: unauthorized")])
        self.assertNotEqual(result["status"], "model_answered")
        self.assertEqual(usage["request_count"], 1)

    def test_non_thinking_private_request_does_not_acquire_extra_retry(self):
        result, usage = self.run_chat([Response()], tier="fast")
        self.assertEqual(result["provider_error_type"], "empty_model_answer")
        self.assertEqual(usage["request_count"], 1)
        self.assertEqual(self.calls[0]["thinking"]["type"], "disabled")


if __name__ == "__main__":
    unittest.main()
