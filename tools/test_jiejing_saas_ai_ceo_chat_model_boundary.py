#!/usr/bin/env python3
"""Smoke test that AI CEO chat uses the backend BYOK model boundary."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-ai-ceo-chat" / "test"
SAAS_DB = OUT / "saas-ai-ceo-chat.sqlite"
RUNTIME_DB = OUT / "runtime-ai-ceo-chat.sqlite"


class FakeModelHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeModelHandler.calls.append(
            {
                "path": self.path,
                "authorization_present": bool(self.headers.get("authorization")),
                "body": body,
            }
        )
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        user_prompt = str(messages[-1].get("content") if messages and isinstance(messages[-1], dict) else "")
        if "realtime_search" in user_prompt:
            content = "我查到的公开来源显示，NVDA 当前股价需要以行情页实时数值为准；这次来源里有 NASDAQ 和 Yahoo Finance 的实时行情页。来源：NASDAQ、Yahoo Finance。"
        else:
            content = "今天是 2026年5月25日。AI CEO 已通过后端 BYOK 模型回答，没有触发任何 eBay 写入。"
        payload = {
            "choices": [
                {
                    "message": {
                        "content": content
                    }
                }
            ]
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FakeSearchHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or "0")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeSearchHandler.calls.append(
            {
                "path": self.path,
                "authorization_present": bool(self.headers.get("authorization")),
                "body": body,
            }
        )
        payload = {
            "query": body.get("query") or "NVDA stock price",
            "results": [
                {
                    "title": "NVIDIA Corporation Common Stock (NVDA)",
                    "url": "https://www.nasdaq.com/market-activity/stocks/nvda",
                    "content": "NASDAQ market activity page for NVDA with current stock quote, price movement, and market status.",
                    "score": 0.97,
                },
                {
                    "title": "NVDA Stock Price and News",
                    "url": "https://finance.yahoo.com/quote/NVDA/",
                    "content": "Yahoo Finance quote page for NVIDIA stock with price, chart, and recent market news.",
                    "score": 0.93,
                },
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str) -> bool:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return False
        except Exception:
            time.sleep(0.2)
    return True


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token=token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=_headers(token=token), method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _headers(*, token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()
    search_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSearchHandler)
    search_thread = threading.Thread(target=search_server.serve_forever, daemon=True)
    search_thread.start()
    saas_port = free_port()
    env = os.environ.copy()
    env["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "1"
    env["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(OUT / "local-model-secrets.json")
    env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
    env["JIEJING_BILLING_PROVIDER"] = "stripe_test_mock"
    env["JIEJING_QUOTA_ENFORCEMENT_ENABLED"] = "1"
    env["JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED"] = "1"
    env["JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED"] = "1"
    env["TAVILY_API_KEY"] = "unit-test-search-credential-placeholder"
    env["TAVILY_SEARCH_ENDPOINT"] = f"http://127.0.0.1:{search_server.server_address[1]}/search"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(saas_port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{saas_port}"
        if wait_for_health(base_url):
            stderr = process.stderr.read() if process.stderr else ""
            return fail(f"saas backend did not become healthy: {stderr[-800:]}")

        auth = post_json(
            f"{base_url}/auth/register",
            {"email": "ai-ceo-chat@example.com", "password": "password123", "company_name": "AI CEO Chat Co"},
        )
        token = str(auth.get("token") or "")
        if not token:
            return fail("registration should return a bearer token")
        billing_trial = auth.get("billing_trial") if isinstance(auth.get("billing_trial"), dict) else {}
        if billing_trial.get("ok") is not True:
            return fail(f"registration should seed no-charge beta entitlement under stripe_test_mock: {billing_trial}")
        if billing_trial.get("triggers_real_charge") is not False or billing_trial.get("calls_stripe_api") is not False:
            return fail(f"registration trial must not call Stripe or trigger a real charge: {billing_trial}")

        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "AI CEO Chat Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=token,
        ).get("store", {})
        store_id = str(store.get("store_id") or "")
        if not store_id:
            return fail("store creation should return a store_id")

        empty_latest = fetch_json(f"{base_url}/stores/{store_id}/merchant-ceo/commands/latest", token=token)
        if empty_latest.get("command") is not None or empty_latest.get("merchant_ceo_command") is not None:
            return fail("empty AI CEO latest command should return a 200 empty state")

        pre_model_realtime_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "web search eBay seller policy latest update",
                "client_now": "2026-05-25T09:55:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-pre-model-search-test",
                    "text": "web search eBay seller policy latest update",
                    "title": "Realtime search before model setup",
                    "summary": "AI CEO fast realtime search question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "realtime_search",
                    "routes": [],
                },
            },
            token=token,
        )
        pre_model_chat = pre_model_realtime_response.get("ai_ceo_chat", {})
        if pre_model_chat.get("status") != "realtime_search_answered_without_model":
            return fail(f"pre-model realtime search should not be blocked by model setup: {pre_model_chat}")
        if pre_model_chat.get("route") != "external_realtime":
            return fail(f"pre-model realtime search should route as external_realtime, got {pre_model_chat.get('route')}")
        if not pre_model_chat.get("source_records"):
            return fail("pre-model realtime search should return source records")
        if FakeModelHandler.calls:
            return fail("pre-model realtime search should not call the text model provider")
        if pre_model_realtime_response.get("model_secret_resolution", {}).get("status") != "not_required_for_fast_route":
            return fail("pre-model realtime search should report model secret is not required for fast route")

        raw_secret = "unit-test-model-key-ai-ceo-chat-000000"
        model_port = model_server.server_address[1]
        post_json(
            f"{base_url}/stores/{store_id}/model/api-key",
            {
                "provider_key": "deepseek",
                "api_key": raw_secret,
                "model": "deepseek-chat",
                "base_url": f"http://127.0.0.1:{model_port}/v1",
            },
            token=token,
        )

        response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "今天几号",
                "client_now": "2026-05-25T10:00:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-date-test",
                    "text": "今天几号",
                    "title": "日期问题",
                    "summary": "AI CEO chat date question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        serialized = json.dumps(response, ensure_ascii=False)
        if raw_secret in serialized:
            return fail("AI CEO chat response must not expose model API key")
        chat = response.get("ai_ceo_chat", {})
        if chat.get("status") != "local_clock_answered":
            return fail(f"AI CEO clock question should be answered without waiting for provider text generation, got {chat.get('status')}: {chat}")
        if chat.get("route") != "general_chat":
            return fail(f"normal date question should route as general_chat, got {chat.get('route')}")
        if chat.get("route_label") != "直接回答":
            return fail(f"normal date question should expose direct-answer label, got {chat.get('route_label')}")
        if chat.get("memory_policy") != "transient_no_long_term_memory" or chat.get("long_term_memory") is not False:
            return fail(f"normal date question must not enter long-term merchant memory: {chat}")
        model_client = chat.get("model_client", {})
        if model_client.get("provider_key") != "deepseek" or model_client.get("model") != "deepseek-chat":
            return fail(f"AI CEO chat should expose sanitized provider/model metadata, got {model_client}")
        if "2026年5月25日" not in str(chat.get("answer") or ""):
            return fail("AI CEO clock answer should use the supplied client date context")
        if FakeModelHandler.calls:
            return fail("local clock question should not wait on the text model provider")

        capability_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "你现在有连接网络吗，连接 DeepSeek 吗？",
                "client_now": "2026-05-25T10:02:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-capability-test",
                    "text": "你现在有连接网络吗，连接 DeepSeek 吗？",
                    "title": "AI CEO 连接状态",
                    "summary": "AI CEO chat capability status question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        capability_chat = capability_response.get("ai_ceo_chat", {})
        if capability_chat.get("status") != "capability_status_answered":
            return fail(f"AI CEO capability question should return a fast capability status: {capability_chat}")
        capability_answer = str(capability_chat.get("answer") or "")
        if "AI 已接通" not in capability_answer or "实时搜索" not in capability_answer:
            return fail("AI CEO capability answer should explain AI and realtime search status")
        if FakeModelHandler.calls:
            return fail("AI CEO capability question should not wait on the text model provider")

        ebay_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "帮我为 eBay Listing 生成刊登资料和确认中心缺口",
                "client_now": "2026-05-25T10:05:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-ebay-route-test",
                    "text": "帮我为 eBay Listing 生成刊登资料和确认中心缺口",
                    "title": "eBay 经营任务",
                    "summary": "AI CEO chat eBay workflow question",
                    "intent": "listing_workflow",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        ebay_chat = ebay_response.get("ai_ceo_chat", {})
        if ebay_chat.get("status") != "model_answered" or ebay_chat.get("route") != "ebay_workflow":
            return fail(f"eBay operating request should call model with ebay_workflow route: {ebay_chat}")
        if ebay_chat.get("memory_policy") != "permanent_operating_memory" or ebay_chat.get("long_term_memory") is not True:
            return fail(f"eBay operating request should be permanent operating memory: {ebay_chat}")
        ebay_model_messages = json.dumps(FakeModelHandler.calls[-1]["body"].get("messages", []), ensure_ascii=False)
        if "route" not in ebay_model_messages or "ebay_workflow" not in ebay_model_messages:
            return fail("eBay operating prompt should include ebay_workflow route")

        call_count = len(FakeModelHandler.calls)
        realtime_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "英伟达现在股价是多少",
                "client_now": "2026-05-25T10:10:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-stock-test",
                    "text": "英伟达现在股价是多少",
                    "title": "实时股价问题",
                    "summary": "AI CEO chat realtime stock question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        realtime_chat = realtime_response.get("ai_ceo_chat", {})
        if realtime_chat.get("status") != "realtime_search_answered_without_model":
            return fail(f"realtime stock question should use fast live source records without waiting for the model, got {realtime_chat}")
        if realtime_chat.get("route") != "external_realtime":
            return fail(f"realtime stock question should route as external_realtime, got {realtime_chat.get('route')}")
        if realtime_chat.get("memory_policy") != "transient_no_long_term_memory" or realtime_chat.get("long_term_memory") is not False:
            return fail(f"realtime stock question must not enter long-term merchant memory: {realtime_chat}")
        realtime_answer = str(realtime_chat.get("answer") or "")
        if "NASDAQ" not in realtime_answer or "来源" not in realtime_answer:
            return fail("realtime stock answer should cite live search sources")
        if len(FakeModelHandler.calls) != call_count:
            return fail("realtime stock question should not wait for the text model after live source records are attached")
        if not FakeSearchHandler.calls:
            return fail("realtime stock question should call the backend search provider")
        if "unit-test-search-credential-placeholder" in json.dumps(realtime_response, ensure_ascii=False):
            return fail("AI CEO realtime search response must not expose search provider credential")

        latest = fetch_json(f"{base_url}/stores/{store_id}/merchant-ceo/commands/latest", token=token)
        latest_command = latest.get("command", {})
        if latest_command.get("ai_reply_status") != "realtime_search_answered_without_model":
            return fail("latest AI CEO command should keep realtime search status")
        if "NASDAQ" not in str(latest_command.get("ai_reply") or ""):
            return fail("latest AI CEO command should keep realtime source-backed reply")

        high_risk_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "把这个 Listing 现在发布到 eBay",
                "client_now": "2026-05-25T10:15:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-confirmation-route-test",
                    "text": "把这个 Listing 现在发布到 eBay",
                    "title": "真实发布确认",
                    "summary": "AI CEO chat high-risk publish request",
                    "intent": "publish",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        high_risk_chat = high_risk_response.get("ai_ceo_chat", {})
        if high_risk_chat.get("route") != "confirmation_required" or high_risk_chat.get("decision_center_required") is not True:
            return fail(f"high-risk publish request should route to confirmation center: {high_risk_chat}")
        if high_risk_chat.get("memory_policy") != "permanent_operating_memory":
            return fail(f"high-risk publish request should be permanent operating memory: {high_risk_chat}")

        rule_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "记住这个规则：利润低于 20% 不要发布",
                "client_now": "2026-05-25T10:20:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-rule-memory-test",
                    "text": "记住这个规则：利润低于 20% 不要发布",
                    "title": "商家规则记忆",
                    "summary": "AI CEO chat merchant rule memory",
                    "intent": "rule",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        rule_chat = rule_response.get("ai_ceo_chat", {})
        if rule_chat.get("route") != "merchant_rule_memory" or rule_chat.get("writes_merchant_rule") is not True:
            return fail(f"explicit rule should route to merchant rule memory: {rule_chat}")
        if rule_chat.get("memory_policy") != "merchant_rule" or rule_chat.get("long_term_memory") is not True:
            return fail(f"explicit rule should be long-term merchant rule memory: {rule_chat}")

        print("PASS jiejing_saas_ai_ceo_chat_model_boundary")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        model_server.shutdown()
        model_server.server_close()
        search_server.shutdown()
        search_server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
