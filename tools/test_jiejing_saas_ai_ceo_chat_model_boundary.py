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
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ai_ceo_chat import AI_CEO_ROUTE_EBAY_WORKFLOW, build_ai_ceo_chat_prompts  # noqa: E402
from jiejing_saas.repository import SaaSRepository, _ai_ceo_market_product_candidates, _infer_ai_ceo_market_product  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402

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
        system_prompt = str(messages[0].get("content") if messages and isinstance(messages[0], dict) else "")
        if "timely_evidence_review_v1" in system_prompt:
            evidence = json.loads(user_prompt)
            source = evidence["source_records"][0]
            content = json.dumps({"all_claims_supported": True, "answers_question": True, "date_scope_matches": True,
                "conflicts": [], "claims": [{"text": evidence["candidate_answer"], "source_id": source["citation_id"],
                                               "excerpt": source["snippet"]}]}, ensure_ascii=False)
        elif "realtime_search" in user_prompt and '"realtime_kind": "news_search"' in user_prompt:
            evidence = json.loads(user_prompt)
            source = evidence["realtime_search"]["source_records"][0]
            content = source["snippet"].rstrip("。") + "[" + source["citation_id"] + "]。"
        elif "travel mosquito repeller" in user_prompt.lower():
            content = (
                "### Product market research report\n"
                "**Suggested product:** Travel mosquito repeller product\n"
                "**Target marketplace:** eBay US listing\n"
                "**Demand signal:** outdoor, camping, patio, and summer travel keywords show repeat buyer intent.\n"
                "**Competitor signal:** compare compact repeller listings by price band, image proof, warranty, and shipping promise.\n"
                "**Listing handoff:** prepare title, selling points, item specifics, main image brief, price band, margin review, and publish confirmation.\n"
                "This is only a draft handoff. It must not publish, charge, refund, advertise, change inventory, or change eBay policy without confirmation."
            )
        elif "realtime_search" in user_prompt:
            content = "我查到的公开来源显示，NVDA 当前股价需要以行情页实时数值为准；这次来源里有 NASDAQ 和 Yahoo Finance 的实时行情页。来源：NASDAQ、Yahoo Finance。"
        else:
            content = "今天是 2026年5月25日。AI CEO 已通过后端 BYOK 模型回答，没有触发任何 eBay 写入。"
        payload = {
            "choices": [
                {
                    "message": {
                        "content": content
                    },
                    "finish_reason": "stop",
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
        if "美股为什么大跌" in str(body.get("query") or ""):
            today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            payload["results"] = [{"title": "Offline dated market-news fixture", "url": "https://www.reuters.com/markets/fixture",
                "content": f"截至{today}，该公开报道把这次美股回落与风险偏好下降联系起来。", "published_at": today}]
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


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    expected_status: int | tuple[int, ...] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = _headers(token=token)
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            parsed["_http_status"] = int(response.status)
            allowed = (expected_status,) if isinstance(expected_status, int) else expected_status
            if allowed is not None and int(response.status) not in allowed:
                raise AssertionError(f"expected HTTP {allowed}, got {response.status}: {parsed}")
            if allowed is None and not 200 <= int(response.status) < 300:
                raise AssertionError(f"expected HTTP 2xx, got {response.status}: {parsed}")
            return parsed
    except urllib.error.HTTPError as exc:
        parsed = json.loads(exc.read().decode("utf-8"))
        parsed["_http_status"] = int(exc.code)
        allowed = (expected_status,) if isinstance(expected_status, int) else expected_status
        if allowed is not None and int(exc.code) in allowed:
            return parsed
        raise AssertionError(f"expected HTTP {allowed or '2xx'}, got {exc.code}: {parsed}") from exc


def _headers(*, token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    narrative_candidates = _ai_ceo_market_product_candidates(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        answer=(
            "\u6211\u4eec\u8bc6\u522b\u51fa\u201c\u732b\u7528\u7845\u80f6\u7259\u5237\u6307\u5957\u201d\u548c"
            "\u201c\u4fbf\u643a\u5f0f\u65c5\u884c\u7845\u80f6\u6298\u53e0\u5ba0\u7269\u7897\u201d\u662f\u4e24\u4e2a\u5019\u9009\u54c1\u3002"
            "\u5efa\u8bae\u4f18\u5148\u6d4b\u8bd5\u201c\u732b\u7528\u7845\u80f6\u7259\u5237\u6307\u5957\u201d\u3002\n"
            "- **\u732b\u7528\u7845\u80f6\u7259\u5237\u6307\u5957**\n"
            "  - **\u9700\u6c42**\uff1a\u5ba0\u7269\u53e3\u8154\u5065\u5eb7\u610f\u8bc6\u63d0\u5347\u3002\n"
            "  - **\u98ce\u9669**\uff1a\u5305\u88c5\u9700\u9632\u6324\u538b\u53d8\u5f62\uff08\u4fe1\u5c01\u888b\u9700\u52a0\u56fa\uff09\u3002\n"
            "- **\u4fbf\u643a\u5f0f\u65c5\u884c\u7845\u80f6\u6298\u53e0\u5ba0\u7269\u7897**\n"
            "  - **\u9700\u6c42**\uff1a\u6237\u5916\u65c5\u884c\u573a\u666f\u3002"
        ),
    )
    narrative_names = [item.get("name") for item in narrative_candidates]
    if len(narrative_candidates) < 2 or narrative_names[0] != "\u732b\u7528\u7845\u80f6\u7259\u5237\u6307\u5957":
        return fail(f"AI CEO narrative market reports should extract concrete candidate products: {narrative_candidates}")
    if "\u5305\u88c5\u9700\u9632\u6324\u538b\u53d8\u5f62\uff08\u4fe1\u5c01\u888b\u9700\u52a0\u56fa\uff09" in narrative_names:
        return fail(f"AI CEO market parser must not treat risk notes as candidate products: {narrative_candidates}")
    card_candidates = _ai_ceo_market_product_candidates(
        message="\u8bf7\u7ed9\u6211\u4e00\u4efd\u5e02\u573a\u8c03\u7814\u62a5\u544a\u3001\u5019\u9009\u5546\u54c1\u540d\u79f0\u3001\u63a8\u8350\u5ea6\u8bc4\u5206\u3001\u98ce\u9669\u548c Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae\u3002",
        answer=(
            "**\u8f93\u51fa\u76ee\u6807**\n"
            "\u6316\u6398 2-4 \u4e2a\u6709\u9700\u6c42\u7684\u5c0f\u4f17\u5546\u54c1\u3002\n"
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "#### \u5019\u9009\u5546\u54c1 1: \u5929\u7136\u8f6f\u6728\u745c\u4f3d\u6309\u6469\u7403 (Cork Massage Ball Set)\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 4.5 / 5\n"
            "#### \u5019\u9009\u5546\u54c1 2: \u53ef\u79cd\u690d\u7684\u79cd\u5b50\u4e66\u7b7e/\u8d3a\u5361 (Plantable Seed Bookmarks/Cards)\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 4.2 / 5"
        ),
    )
    card_names = [item.get("name") for item in card_candidates]
    if not card_names or card_names[0] != "\u5929\u7136\u8f6f\u6728\u745c\u4f3d\u6309\u6469\u7403 (Cork Massage Ball Set)" or "\u8f93\u51fa\u76ee\u6807" in card_names:
        return fail(f"AI CEO candidate-card reports should prefer concrete candidate headings over report sections: {card_candidates}")
    numbered_card_candidates = _ai_ceo_market_product_candidates(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        answer=(
            "### \u5e02\u573a\u8c03\u7814\u62a5\u544a\uff1aeBay \u7f8e\u56fd\u7ad9 \u8f7b\u5c0f\u4ef6\u975e\u5e26\u7535\u5c0f\u4f17\u54c1\n"
            "#### 1. \u7845\u80f6\u53ef\u6298\u53e0\u5496\u5561\u6ee4\u676f (Silicone Collapsible Pour Over Coffee Cone)\n"
            "*   **\u63a8\u8350\u5ea6\u8bc4\u5206**\uff1a\u2605\u2605\u2605\u2605\u2605 (9.2/10)\n"
            "*   **\u4e3a\u4ec0\u4e48\u6709\u9700\u6c42**\uff1a\u7f8e\u56fd\u5496\u5561\u6587\u5316\u76db\u884c\uff0c\u6237\u5916\u3001\u65c5\u884c\u3001\u529e\u516c\u573a\u666f\u9700\u6c42\u5e7f\u3002\n"
            "*   **Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae**\uff1aTitle / item specifics / image brief.\n"
            "#### 2. \u68c9\u7ef3\u690d\u7269\u540a\u7bee\u6302\u94a9 (Cotton Rope Plant Hanger Hooks)\n"
            "*   **\u63a8\u8350\u5ea6\u8bc4\u5206**\uff1a8.4/10\n"
            "### 1. \u76ee\u6807\u5ba2\u7fa4\u753b\u50cf\n"
            "*   \u8fd9\u4e00\u6bb5\u4e0d\u662f\u5019\u9009\u5546\u54c1\u3002"
        ),
    )
    numbered_names = [item.get("name") for item in numbered_card_candidates]
    if not numbered_names or numbered_names[0] != "\u7845\u80f6\u53ef\u6298\u53e0\u5496\u5561\u6ee4\u676f (Silicone Collapsible Pour Over Coffee Cone)" or "\u76ee\u6807\u5ba2\u7fa4\u753b\u50cf" in numbered_names:
        return fail(f"AI CEO numbered candidate headings should extract product cards, not report sections: {numbered_card_candidates}")
    generic_candidates = _ai_ceo_market_product_candidates(
        message="\u5e2e\u6211\u9009\u54c1",
        answer=(
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "#### \u5019\u9009\u5546\u54c1 1: \u4fbf\u643a\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 4 / 5\n"
            "#### \u5019\u9009\u5546\u54c1 2: \u6536\u7eb3\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 4 / 5\n"
            "#### \u5019\u9009\u5546\u54c1 3: \u4fbf\u643a\u5f0f\u65c5\u884c\u5ba0\u7269\u7897\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 4.3 / 5"
        ),
    )
    generic_names = [item.get("name") for item in generic_candidates]
    if "\u4fbf\u643a" in generic_names or "\u6536\u7eb3" in generic_names or generic_names[:1] != ["\u4fbf\u643a\u5f0f\u65c5\u884c\u5ba0\u7269\u7897"]:
        return fail(f"AI CEO market parser should reject generic short labels as products: {generic_candidates}")
    placeholder_candidates = _ai_ceo_market_product_candidates(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        answer=(
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "#### \u5019\u9009\u5546\u54c1 1: \u5546\u54c1 1\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 88/100\n"
            "#### \u5019\u9009\u5546\u54c1 2: \u5019\u9009\u54c1 A\n"
            "* **\u63a8\u8350\u5ea6\u8bc4\u5206**: 82/100"
        ),
    )
    if placeholder_candidates:
        return fail(f"AI CEO market parser must reject placeholder product names: {placeholder_candidates}")
    labeled_candidates = _ai_ceo_market_product_candidates(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        answer=(
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "- \u5546\u54c1\u540d\u79f0\uff1a\u53ef\u6298\u53e0\u7845\u80f6\u6f0f\u6597\n"
            "- \u63a8\u8350\u5ea6\u8bc4\u5206\uff1a88/100\n"
            "- \u4e3a\u4ec0\u4e48\u6709\u9700\u6c42\uff1a\u9732\u8425\u548c\u53a8\u623f\u573a\u666f\u90fd\u80fd\u4f7f\u7528\u3002\n"
            "- Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae\uff1aTitle / Material / Type\u3002"
        ),
    )
    labeled_names = [item.get("name") for item in labeled_candidates]
    if labeled_names[:1] != ["\u53ef\u6298\u53e0\u7845\u80f6\u6f0f\u6597"]:
        return fail(f"AI CEO labeled candidate format should become a concrete Listing handoff product: {labeled_candidates}")
    table_candidates = _ai_ceo_market_product_candidates(
        message="\u8bf7\u505a\u9009\u54c1\u5e02\u573a\u8c03\u7814",
        answer=(
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "| \u5546\u54c1\u540d\u79f0 | \u63a8\u8350\u5ea6\u8bc4\u5206 | \u98ce\u9669 |\n"
            "| --- | --- | --- |\n"
            "| \u5e03\u827a\u7535\u7ebf\u6536\u7eb3\u5957 | 82/100 | \u9700\u6838\u5b9e\u6750\u8d28\u548c\u5c3a\u5bf8 |\n"
        ),
    )
    table_names = [item.get("name") for item in table_candidates]
    if table_names[:1] != ["\u5e03\u827a\u7535\u7ebf\u6536\u7eb3\u5957"]:
        return fail(f"AI CEO table candidate format should become a concrete Listing handoff product: {table_candidates}")
    vertical_table_candidates = _ai_ceo_market_product_candidates(
        message="\u8bf7\u7ed9\u6211\u4e00\u4efd\u5e02\u573a\u8c03\u7814\u62a5\u544a\u3001\u5019\u9009\u5546\u54c1\u540d\u79f0\u3001\u63a8\u8350\u5ea6\u8bc4\u5206\u3001\u98ce\u9669\u548c Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae\u3002",
        answer=(
            "### \u5019\u9009\u5546\u54c1\u5361\n"
            "| \u9879\u76ee | \u5177\u4f53\u5185\u5bb9 |\n"
            "| :--- | :--- |\n"
            "| \u5019\u9009\u5546\u54c1 1 | \u7845\u80f6\u53ef\u6298\u53e0\u6f0f\u6597 (Silicone Collapsible Funnel) |\n"
            "| \u63a8\u8350\u5ea6\u8bc4\u5206 | 88 / 100 |\n"
            "| \u4e3a\u4ec0\u4e48\u6709\u9700\u6c42 | \u89e3\u51b3\u53a8\u623f\u3001\u8f66\u5e93\u3001\u6237\u5916\u573a\u666f\u5206\u88c5\u75db\u70b9\u3002 |\n"
            "| Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae | Title / Material / Type / image brief |\n"
        ),
    )
    vertical_table_names = [item.get("name") for item in vertical_table_candidates]
    if vertical_table_names[:1] != ["\u7845\u80f6\u53ef\u6298\u53e0\u6f0f\u6597 (Silicone Collapsible Funnel)"]:
        return fail(f"AI CEO vertical key-value table should become product_candidates: {vertical_table_candidates}")
    generic_field_name = _infer_ai_ceo_market_product(
        message="\u8bf7\u7ed9\u6211\u4e00\u4efd\u5e02\u573a\u8c03\u7814\u62a5\u544a\u3001\u5019\u9009\u5546\u54c1\u540d\u79f0\u3001\u63a8\u8350\u5ea6\u8bc4\u5206\u3001\u98ce\u9669\u548c Listing \u8349\u7a3f\u5b57\u6bb5\u5efa\u8bae\u3002",
        answer=(
            "### \u4e00\u3001\u5e02\u573a\u8c03\u7814\u62a5\u544a\uff1aeBay \u7f8e\u56fd\u7ad9\u8f7b\u5c0f\u4ef6\u673a\u4f1a\u5feb\u7167\n"
            "**1. \u76ee\u6807\u5e02\u573a\u4e0e\u673a\u4f1a\u7a97\u53e3**\n"
            "\u8fd9\u4e00\u6bb5\u53ea\u662f\u62a5\u544a\u603b\u8bba\uff0c\u5c1a\u672a\u7ed9\u51fa\u5177\u4f53\u5019\u9009\u5546\u54c1\u3002"
        ),
        candidates=[],
    )
    if generic_field_name:
        return fail(f"AI CEO market product inference must not use template field names as products: {generic_field_name}")
    tool_name_product = _infer_ai_ceo_market_product(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        answer=(
            "\u9700\u8981\u4f60\u7528 eBay Terapeak \u548c\u771f\u5b9e\u5e97\u94fa\u6570\u636e\u590d\u6838\u540e\u624d\u53ef\u505a\u6700\u7ec8\u51b3\u7b56\u3002\n"
            "### \u5e02\u573a\u8c03\u7814\u62a5\u544a\uff1aeBay \u7f8e\u56fd\u7ad9\u8f7b\u5c0f\u4ef6\n"
            "\u8fd9\u4e00\u6bb5\u8fd8\u6ca1\u6709\u7ed9\u51fa\u5177\u4f53\u5019\u9009\u5546\u54c1\u3002"
        ),
        candidates=[],
    )
    if tool_name_product:
        return fail(f"AI CEO market product inference must not use eBay tools as product names: {tool_name_product}")
    workflow_prompt, _workflow_payload = build_ai_ceo_chat_prompts(
        message="\u5e2e\u6211\u627e\u4e2a\u5c0f\u4f17\u54c1\uff0c\u5e02\u573a\u6709\u9700\u6c42\uff0c\u8f7b\u5c0f\u4ef6\uff0c\u4e0d\u5e26\u7535",
        context={},
        route=AI_CEO_ROUTE_EBAY_WORKFLOW,
    )
    if "\u5148\u8f93\u51fa\u201c\u5019\u9009\u5546\u54c1\u5361\u201d" not in workflow_prompt or "\u524d 500 \u5b57\u5185" not in workflow_prompt:
        return fail("AI CEO market research prompt should force candidate cards before long analysis")
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
    env["JIEJING_INTERNAL_ADMIN_EMAILS"] = (
        "ai-ceo-chat@example.com,ai-ceo-legacy-account-model@example.com"
    )
    env["JIEJING_QUOTA_ENFORCEMENT_ENABLED"] = "1"
    env["JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED"] = "1"
    env["JIEJING_AI_CEO_REALTIME_MODEL_SYNTHESIS_ENABLED"] = "1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED"] = "1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER"] = "deepseek"
    env["JIEJING_AI_CEO_PLATFORM_MODEL"] = "deepseek-v4-pro"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL"] = f"http://127.0.0.1:{model_server.server_address[1]}/v1"
    env["JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"] = "20"
    env["TAVILY_API_KEY"] = "unit-test-search-credential-placeholder"
    env["TAVILY_SEARCH_ENDPOINT"] = f"http://127.0.0.1:{search_server.server_address[1]}/search"
    previous_local_resolver_env = {
        "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": os.environ.get("JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"),
        "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH": os.environ.get("JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"),
        "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP": os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"),
    }
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = env["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"]
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = env["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"]
    os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = env["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"]
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
        company_id = str((auth.get("company") or {}).get("company_id") or "")
        user_id = str((auth.get("user") or {}).get("user_id") or "")
        if not company_id or not user_id:
            return fail("registration should return company and user ids")
        billing_trial = auth.get("billing_trial") if isinstance(auth.get("billing_trial"), dict) else {}
        if billing_trial.get("ok") is not True:
            return fail(f"registration should seed no-charge beta entitlement under stripe_test_mock: {billing_trial}")
        if billing_trial.get("triggers_real_charge") is not False or billing_trial.get("calls_stripe_api") is not False:
            return fail(f"registration trial must not call Stripe or trigger a real charge: {billing_trial}")
        billing_activation = post_json(
            f"{base_url}/owner/billing/test-event",
            {"plan_key": "operator", "action": "activate"},
            token=token,
            extra_headers={"Host": "ops.jiejing.shop"},
        ).get("billing_test_event", {})
        if billing_activation.get("ok") is not True:
            return fail(f"test billing activation should unlock multi-store test quota without real charge: {billing_activation}")
        if billing_activation.get("triggers_real_charge") is not False or billing_activation.get("calls_stripe_api") is not False:
            return fail(f"test billing activation must not call Stripe or trigger a real charge: {billing_activation}")

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

        pre_model_capability_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "你现在什么大模型",
                "client_now": "2026-05-25T09:52:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-pre-model-capability-test",
                    "text": "你现在什么大模型",
                    "title": "AI CEO 模型状态",
                    "summary": "AI CEO current model status question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "model_status",
                    "routes": [],
                },
            },
            token=token,
        )
        pre_model_capability_chat = pre_model_capability_response.get("ai_ceo_chat", {})
        if pre_model_capability_chat.get("status") != "capability_status_answered":
            return fail(f"pre-model capability question should answer from current store status: {pre_model_capability_chat}")
        pre_model_capability_answer = str(pre_model_capability_chat.get("answer") or "")
        if "当前账号还没有可用的 AI 连接" not in pre_model_capability_answer:
            return fail("pre-model capability answer should explain the current account is not connected")
        if "不会跨商家、跨账号使用别人的模型连接" not in pre_model_capability_answer:
            return fail("pre-model capability answer should preserve merchant/account isolation")
        if FakeModelHandler.calls:
            return fail("pre-model capability question should not call the text model provider")

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
        if not pre_model_chat.get("work_records"):
            return fail("pre-model realtime search should return AI CEO work records")
        if not pre_model_chat.get("confirmation_items"):
            return fail("pre-model realtime search should return confirmation guidance")
        if pre_model_chat.get("source_policy", {}).get("no_source_no_latest_claim") is not True:
            return fail("pre-model realtime search should carry no-source-no-latest-claim policy")
        if FakeModelHandler.calls:
            return fail("pre-model realtime search should not call the text model provider")
        if pre_model_realtime_response.get("model_secret_resolution", {}).get("status") != "not_required_for_fast_route":
            return fail("pre-model realtime search should report model secret is not required for fast route")
        if pre_model_realtime_response.get("ai_ceo_market_report") is not None:
            return fail("generic eBay realtime search should not be saved as a Listing market-research handoff")

        pre_model_market_report_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "web search eBay market research and recommend one product for Listing: travel mosquito repeller",
                "client_now": "2026-05-25T09:56:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-pre-model-market-report-test",
                    "text": "web search eBay market research and recommend one product for Listing: travel mosquito repeller",
                    "title": "Realtime market research before model setup",
                    "summary": "AI CEO fast realtime market research should become a Listing handoff report",
                    "intent": "listing_workflow",
                    "status": "ready",
                    "status_label": "realtime_search",
                    "routes": [],
                },
            },
            token=token,
        )
        pre_model_market_chat = pre_model_market_report_response.get("ai_ceo_chat", {})
        if pre_model_market_chat.get("status") != "realtime_search_answered_without_model":
            return fail(f"pre-model realtime market research should use the fast search route: {pre_model_market_chat}")
        pre_model_ai_market_report = pre_model_market_report_response.get("ai_ceo_market_report", {})
        if pre_model_ai_market_report.get("report_type") != "ai_ceo.market_research":
            return fail(f"pre-model realtime market research should be saved as a structured Listing report: {pre_model_ai_market_report}")
        pre_model_report_body = pre_model_ai_market_report.get("report") if isinstance(pre_model_ai_market_report.get("report"), dict) else {}
        pre_model_handoff = pre_model_report_body.get("listing_handoff") if isinstance(pre_model_report_body.get("listing_handoff"), dict) else {}
        if pre_model_handoff.get("ready_for_listing_draft") is not False or pre_model_handoff.get("triggers_real_platform_write") is not False:
            return fail(f"pre-model realtime market report must wait for a concrete selection and supplier facts: {pre_model_handoff}")
        pre_model_delivery = pre_model_market_report_response.get("ai_ceo_market_report_delivery", {})
        if pre_model_delivery.get("contract_version") != "2026-07-04-ai-ceo-market-report-delivery-v1":
            return fail(f"pre-model realtime market report should return the Listing delivery contract: {pre_model_delivery}")
        if pre_model_delivery.get("structured_report_saved") is not True or pre_model_delivery.get("listing_import_ready") is not False:
            return fail(f"pre-model realtime market report should be saved but not import-ready before facts are complete: {pre_model_delivery}")
        for forbidden_key in ("frontend_gets_model_api_key", "runtime_gets_raw_ebay_token", "secret_exposed", "triggers_real_platform_write"):
            if pre_model_delivery.get(forbidden_key) is not False:
                return fail(f"pre-model report delivery should keep {forbidden_key}=False: {pre_model_delivery}")
        reports_after_pre_model_market = fetch_json(f"{base_url}/reports?limit=30", token=token).get("reports", [])
        if not any(item.get("report_id") == pre_model_ai_market_report.get("report_id") for item in reports_after_pre_model_market):
            return fail("pre-model realtime market report should be queryable from /reports before model setup")
        if "unit-test-search-credential-placeholder" in json.dumps(pre_model_market_report_response, ensure_ascii=False):
            return fail("pre-model realtime market report response must not expose the search credential")

        raw_secret = "unit-test-model-key-ai-ceo-chat-000000"
        model_port = model_server.server_address[1]
        saved_model = post_json(
            f"{base_url}/stores/{store_id}/model/api-key",
            {
                "provider_key": "deepseek",
                "api_key": raw_secret,
                "model": "deepseek-v4-pro",
                "base_url": f"http://127.0.0.1:{model_port}/v1",
            },
            token=token,
        )
        saved_ref = saved_model.get("model_secret_ref", {})
        if saved_ref.get("store_id") not in ("", None):
            return fail(f"model API key should be stored as an account-level secret_ref by default: {saved_ref}")
        saved_metadata = saved_ref.get("metadata") if isinstance(saved_ref.get("metadata"), dict) else {}
        if saved_metadata.get("model_connection_scope") != "account" or saved_metadata.get("store_context_id") != store_id:
            return fail(f"model secret metadata should record account scope and store context: {saved_metadata}")
        saved_settings = saved_model.get("model_settings", {})
        if saved_settings.get("active_scope") != "account" or saved_settings.get("merchant_model_follows_account") is not True:
            return fail(f"model settings should expose account-scoped BYOK status: {saved_settings}")

        company_default_store = SaaSRepository(SAAS_DB).create_store(
            company_id=company_id,
            user_id=user_id,
            payload={
                "platform": "ebay",
                "store_name": "AI CEO Company Default Store",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
                "settings": {"created_from": "ai_ceo_company_default_fixture"},
            },
        )
        company_default_store_id = str(company_default_store.get("store_id") or "")
        if not company_default_store_id:
            return fail("second store creation should return a store_id")
        legacy_missing_entitlement_repo = SaaSRepository(SAAS_DB)
        with legacy_missing_entitlement_repo._connect() as conn:
            conn.execute("delete from billing_subscriptions where company_id = ?", (company_id,))
        FakeModelHandler.calls.clear()
        FakeSearchHandler.calls.clear()
        company_default_response = post_json(
            f"{base_url}/stores/{company_default_store_id}/merchant-ceo/chat",
            {
                "message": "Introduce Jiejing in one sentence.",
                "client_now": "2026-05-25T09:58:00+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=token,
        )
        company_default_chat = company_default_response.get("ai_ceo_chat", {})
        if company_default_chat.get("status") != "model_answered":
            return fail(f"second store should inherit the same-account model default: {company_default_chat}")
        if FakeSearchHandler.calls:
            return fail("a timeless direct-answer turn should not spend a live-search request")
        if company_default_chat.get("default_web_search", {}).get("status") != "not_requested":
            return fail(f"a timeless direct-answer turn should mark web search not requested: {company_default_chat}")
        if company_default_chat.get("source_records"):
            return fail("a timeless direct-answer turn should not fabricate source_records")
        company_default_model_messages = json.dumps(FakeModelHandler.calls[-1]["body"].get("messages", []), ensure_ascii=False)
        if "web_context" not in company_default_model_messages:
            return fail("default account model prompt should include web_context")
        company_default_model_body = FakeModelHandler.calls[-1]["body"]
        if company_default_model_body.get("max_tokens") != 1200:
            return fail(f"default account model chat should use the general-chat token budget: {company_default_model_body}")
        company_default_performance = company_default_chat.get("performance") if isinstance(company_default_chat.get("performance"), dict) else {}
        if company_default_performance.get("contract_version") != "2026-07-04-ai-ceo-chat-latency-budget-v1":
            return fail(f"default account model chat should expose latency budget evidence: {company_default_chat}")
        if company_default_performance.get("model_timeout_seconds") != 16 or company_default_performance.get("model_max_output_tokens") != 1200:
            return fail(f"default account model chat should expose the general-chat model budget: {company_default_performance}")
        if company_default_performance.get("source_record_count") != 0:
            return fail(f"a timeless direct-answer turn should expose zero source records: {company_default_performance}")
        if company_default_performance.get("search_used_for_model_prompt") is not False:
            return fail(f"a timeless direct-answer turn should expose search_used_for_model_prompt=false: {company_default_performance}")
        if not isinstance(company_default_chat.get("latency_ms"), int) or company_default_chat.get("latency_ms", -1) < 0:
            return fail(f"default account model chat should expose sanitized total latency: {company_default_chat}")
        recovered_subscription = legacy_missing_entitlement_repo.get_billing_subscription(company_id=company_id)
        if not recovered_subscription or recovered_subscription.get("entitlement_active") is not True:
            return fail(f"missing private-beta entitlement should recover before model chat: {recovered_subscription}")
        if recovered_subscription.get("provider") != "stripe_test_mock" or recovered_subscription.get("status") != "active":
            return fail(f"recovered entitlement should stay inside the no-charge test provider: {recovered_subscription}")
        company_default_resolution = company_default_response.get("model_secret_resolution", {})
        if company_default_resolution.get("mode") != "account_byok":
            return fail(f"second store should report account_byok, got {company_default_resolution}")
        if company_default_resolution.get("secret_ref_scope") != "account":
            return fail(f"second store should keep inherited model scoped to the same account: {company_default_resolution}")
        if not FakeModelHandler.calls:
            return fail("second store company default should call the backend model provider")
        if raw_secret in json.dumps(company_default_response, ensure_ascii=False):
            return fail("company default response must not expose the model API key")

        other_auth = post_json(
            f"{base_url}/auth/register",
            {"email": "ai-ceo-other-company@example.com", "password": "password123", "company_name": "AI CEO Other Co"},
        )
        other_token = str(other_auth.get("token") or "")
        other_store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "Other Company Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=other_token,
        ).get("store", {})
        other_store_id = str(other_store.get("store_id") or "")
        FakeModelHandler.calls.clear()
        other_response = post_json(
            f"{base_url}/stores/{other_store_id}/merchant-ceo/chat",
            {
                "message": "Introduce Jiejing in one sentence.",
                "client_now": "2026-05-25T09:59:00+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=other_token,
            expected_status=503,
        )
        other_chat = other_response.get("ai_ceo_chat", {})
        if other_response.get("_http_status") != 503:
            return fail(f"missing model dependency must return HTTP 503: {other_response}")
        if other_chat.get("status") != "blocked_before_model_chat":
            return fail(f"other company must not inherit another company's model connection: {other_chat}")
        if set(other_chat.get("blocked_by") or []) != {"merchant_model_api_key_not_saved", "platform_model_default_not_configured"}:
            return fail(f"other company should see explicit account AI plus trial AI blocker: {other_chat}")
        other_answer = str(other_chat.get("answer") or "")
        if "当前账号还没有保存自己的 AI 连接" not in other_answer or "捷境试用 AI 当前也未开通" not in other_answer:
            return fail(f"missing-key blocker should use merchant-facing AI connection copy: {other_answer}")
        other_platform_resolution = other_response.get("platform_model_resolution", {})
        if other_platform_resolution.get("blocked_by") != ["platform_model_api_key_not_configured"]:
            return fail(f"platform trial AI missing-key blocker should be explicit and sanitized: {other_platform_resolution}")
        if other_platform_resolution.get("provider_key") != "deepseek" or other_platform_resolution.get("model") != "deepseek-v4-flash":
            return fail(f"platform trial AI summary should expose only safe provider/model labels: {other_platform_resolution}")
        if other_platform_resolution.get("secret_exposed") is not False:
            return fail(f"platform trial AI summary must not expose secrets: {other_platform_resolution}")
        if FakeModelHandler.calls:
            return fail("other company without its own model should not call the first company's model provider")
        FakeModelHandler.calls.clear()

        legacy_auth = post_json(
            f"{base_url}/auth/register",
            {"email": "ai-ceo-legacy-account-model@example.com", "password": "password123", "company_name": "AI CEO Legacy Co"},
        )
        legacy_token = str(legacy_auth.get("token") or "")
        legacy_company_id = str((legacy_auth.get("company") or {}).get("company_id") or "")
        legacy_user_id = str((legacy_auth.get("user") or {}).get("user_id") or "")
        if not legacy_token or not legacy_company_id or not legacy_user_id:
            return fail("legacy registration should return token, company id and user id")
        legacy_activation = post_json(
            f"{base_url}/owner/billing/test-event",
            {"plan_key": "operator", "action": "activate"},
            token=legacy_token,
            extra_headers={"Host": "ops.jiejing.shop"},
        ).get("billing_test_event", {})
        if legacy_activation.get("ok") is not True:
            return fail(f"legacy test billing activation should unlock multi-store test quota: {legacy_activation}")
        legacy_store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "Legacy Model Store", "marketplace": "EBAY_US", "stage": "store_opened"},
            token=legacy_token,
        ).get("store", {})
        legacy_store_id = str(legacy_store.get("store_id") or "")
        if not legacy_store_id:
            return fail("legacy store creation should return a store_id")
        legacy_repo = SaaSRepository(SAAS_DB)
        legacy_ref = legacy_repo.create_secret_reference(
            company_id=legacy_company_id,
            store_id=legacy_store_id,
            user_id=legacy_user_id,
            provider="model.deepseek",
            purpose="model_api_key",
            status="ready",
            metadata={
                "provider_key": "deepseek",
                "provider_label": "DeepSeek",
                "api_style": "openai_compatible",
                "model": "deepseek-v4-pro",
                "base_url": f"http://127.0.0.1:{model_port}/v1",
                "merchant_brings_own_key": True,
                "merchant_pays_provider_directly": True,
                "jiejing_stores_only_secret_ref": True,
                "frontend_gets_raw_key_after_save": False,
                "runtime_gets_raw_key": False,
                "reports_get_raw_key": False,
                "secret_exposed": False,
            },
        )
        legacy_settings = SaaSSettings.from_env(
            db_path=SAAS_DB,
            runtime_db_path=RUNTIME_DB,
            output_root=OUT,
            host="127.0.0.1",
            port=saas_port,
        )
        legacy_stored = VaultSecretResolver(legacy_settings).store_secret(
            secret_ref=legacy_ref,
            secret_value=raw_secret,
            created_by=legacy_user_id,
            metadata=legacy_ref.get("metadata") if isinstance(legacy_ref.get("metadata"), dict) else {},
        )
        if legacy_stored.get("status") not in {"ready", "local_development_secret_stored"}:
            return fail(f"legacy model secret should be stored in the backend local resolver: {legacy_stored}")
        legacy_second_store = legacy_repo.create_store(
            company_id=legacy_company_id,
            user_id=legacy_user_id,
            payload={
                "platform": "ebay",
                "store_name": "Legacy Second Store",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
                "settings": {"created_from": "legacy_account_model_fixture"},
            },
        )
        legacy_second_store_id = str(legacy_second_store.get("store_id") or "")
        FakeModelHandler.calls.clear()
        legacy_response = post_json(
            f"{base_url}/stores/{legacy_second_store_id}/merchant-ceo/chat",
            {
                "message": "Introduce Jiejing in one sentence.",
                "client_now": "2026-05-25T09:59:30+08:00",
                "client_timezone": "Asia/Shanghai",
            },
            token=legacy_token,
        )
        legacy_resolution = legacy_response.get("model_secret_resolution", {})
        if legacy_response.get("ai_ceo_chat", {}).get("status") != "model_answered":
            return fail(f"legacy store-scoped model should work as same-user account default: {legacy_response.get('ai_ceo_chat', {})}")
        if legacy_resolution.get("mode") != "account_byok" or legacy_resolution.get("secret_ref_scope") != "account":
            return fail(f"legacy same-user model should be resolved as account_byok: {legacy_resolution}")
        if not FakeModelHandler.calls:
            return fail("legacy same-user account default should call the backend model provider")
        FakeModelHandler.calls.clear()

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
        if model_client.get("provider_key") != "fast_route" or model_client.get("secret_exposed") is not False:
            return fail(f"local clock answer should use the no-secret fast route, got {model_client}")
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
        if "当前捷境账号 AI 已接通" not in capability_answer or "DeepSeek" not in capability_answer or "实时搜索" not in capability_answer:
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

        followup_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "第三个为什么显示一半？",
                "client_now": "2026-05-25T10:06:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "conversation_history": [
                    {
                        "user_text": "帮我选三个适合 eBay 的轻小件",
                        "assistant_text": "候选商品 1：折叠漏斗。候选商品 2：线缆标签。候选商品 3：旅行收纳挂钩。",
                        "route": "ebay_workflow",
                    }
                ],
                "command": {
                    "id": "ceo-chat-context-followup-test",
                    "text": "第三个为什么显示一半？",
                    "title": "继续上一轮选品",
                    "summary": "解释上一轮第三个候选商品",
                    "intent": "general_consultation",
                    "status": "ready",
                    "routes": [],
                },
            },
            token=token,
        )
        followup_chat = followup_response.get("ai_ceo_chat", {})
        if followup_chat.get("status") != "model_answered" or followup_chat.get("route") != "ebay_workflow":
            return fail(f"short follow-up should inherit the previous eBay conversation route: {followup_chat}")
        followup_prompt = json.loads(str(FakeModelHandler.calls[-1]["body"]["messages"][-1]["content"]))
        recent_conversation = followup_prompt.get("recent_conversation") or []
        if not recent_conversation or "旅行收纳挂钩" not in str(recent_conversation[-1].get("assistant_text") or ""):
            return fail(f"short follow-up should send sanitized recent conversation to the account model: {followup_prompt}")

        market_report_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "Please make an eBay market research report and recommend one product for Listing: travel mosquito repeller",
                "client_now": "2026-05-25T10:07:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-market-report-handoff-test",
                    "text": "Please make an eBay market research report and recommend one product for Listing: travel mosquito repeller",
                    "title": "AI CEO market research handoff",
                    "summary": "AI CEO market research should become a Listing handoff report",
                    "intent": "listing_workflow",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        market_report_chat = market_report_response.get("ai_ceo_chat", {})
        if market_report_chat.get("status") != "model_answered" or market_report_chat.get("route") != "ebay_workflow":
            return fail(f"market research handoff should use the eBay workflow model route: {market_report_chat}")
        ai_ceo_market_report = market_report_response.get("ai_ceo_market_report", {})
        if ai_ceo_market_report.get("report_type") != "ai_ceo.market_research":
            return fail(f"AI CEO market research should be returned as a structured report: {ai_ceo_market_report}")
        report_body = ai_ceo_market_report.get("report") if isinstance(ai_ceo_market_report.get("report"), dict) else {}
        if report_body.get("contract_version") != "2026-07-04-ai-ceo-market-report-frontstage-v2":
            return fail(f"AI CEO market report should carry the current contract version: {report_body}")
        handoff = report_body.get("listing_handoff") if isinstance(report_body.get("listing_handoff"), dict) else {}
        if handoff.get("ready_for_listing_draft") is not False or handoff.get("real_platform_writes_enabled") is not False:
            return fail(f"AI CEO market report must remain non-importable until supplier facts are verified: {handoff}")
        if handoff.get("source_mode") != "ai_ceo_chat_structured_handoff":
            return fail(f"AI CEO market report should use the shared chat-to-Listing handoff source mode: {handoff}")
        listing_fields = handoff.get("listing_fields") if isinstance(handoff.get("listing_fields"), dict) else {}
        if listing_fields.get("contract_version") != "2026-07-04-ai-ceo-market-to-listing-handoff-v2":
            return fail(f"AI CEO market report should expose structured Listing handoff fields: {listing_fields}")
        if listing_fields.get("ebay_listing_field_map_contract") != "ai_ceo_market_research_to_ebay_inventory_offer_v1":
            return fail(f"AI CEO market report should expose eBay Inventory/Offer field mapping: {listing_fields}")
        if listing_fields.get("ready_for_listing_draft") is not False or listing_fields.get("triggers_real_platform_write") is not False:
            return fail(f"AI CEO listing fields should remain non-importable and confirmation-gated: {listing_fields}")
        if not listing_fields.get("market_rationale") or listing_fields.get("selling_points") or listing_fields.get("description_seed"):
            return fail(f"AI CEO market rationale must stay separate from buyer-facing Listing copy: {listing_fields}")
        if listing_fields.get("buyer_copy_status") != "waiting_for_merchant_product_facts":
            return fail(f"AI CEO market handoff should wait for merchant product facts before buyer copy: {listing_fields}")
        product_candidates = listing_fields.get("product_candidates") if isinstance(listing_fields.get("product_candidates"), list) else []
        if not product_candidates or not listing_fields.get("selected_product_candidate"):
            return fail(f"AI CEO market handoff should carry product candidate cards before Listing import: {listing_fields}")
        if "市场调研" in str(listing_fields.get("product") or listing_fields.get("title") or ""):
            return fail(f"AI CEO market handoff should not use the report type as the product name: {listing_fields}")
        inventory_draft = listing_fields.get("ebay_inventory_item_draft") if isinstance(listing_fields.get("ebay_inventory_item_draft"), dict) else {}
        offer_draft = listing_fields.get("ebay_offer_draft") if isinstance(listing_fields.get("ebay_offer_draft"), dict) else {}
        if not inventory_draft.get("product", {}).get("aspects") or not offer_draft.get("listingPolicies"):
            return fail(f"AI CEO listing fields should include Inventory API product aspects and Offer policy placeholders: {listing_fields}")
        required_fields = listing_fields.get("publish_preflight_required_fields") if isinstance(listing_fields.get("publish_preflight_required_fields"), list) else []
        for required_field in ("sku", "categoryId", "product.aspects", "product.imageUrls", "fulfillmentPolicyId", "paymentPolicyId", "returnPolicyId"):
            if required_field not in required_fields:
                return fail(f"AI CEO listing handoff missing required eBay preflight field {required_field}: {required_fields}")
        if listing_fields.get("secret_exposed") is not False:
            return fail(f"AI CEO listing fields must not expose secrets: {listing_fields}")
        market_delivery = market_report_response.get("ai_ceo_market_report_delivery", {})
        if market_delivery.get("contract_version") != "2026-07-04-ai-ceo-market-report-delivery-v1":
            return fail(f"AI CEO market report should return the frontend delivery contract: {market_delivery}")
        if market_delivery.get("report_id") != ai_ceo_market_report.get("report_id"):
            return fail(f"AI CEO market delivery should point to the saved report: {market_delivery}")
        if market_delivery.get("structured_report_saved") is not True or market_delivery.get("listing_import_ready") is not False:
            return fail(f"AI CEO market delivery should expose saved-but-not-importable truth: {market_delivery}")
        for forbidden_key in ("frontend_gets_model_api_key", "runtime_gets_raw_ebay_token", "secret_exposed", "triggers_real_platform_write"):
            if market_delivery.get(forbidden_key) is not False:
                return fail(f"AI CEO market delivery should keep {forbidden_key}=False: {market_delivery}")
        market_report_model_body = FakeModelHandler.calls[-1]["body"]
        if market_report_model_body.get("max_tokens") != 2400:
            return fail(f"AI CEO market handoff should use the workflow token budget: {market_report_model_body}")
        market_report_performance = market_report_chat.get("performance") if isinstance(market_report_chat.get("performance"), dict) else {}
        if market_report_performance.get("model_timeout_seconds") != 24 or market_report_performance.get("model_max_output_tokens") != 2400:
            return fail(f"AI CEO market handoff should expose the workflow model budget: {market_report_performance}")
        for forbidden_key in ("frontend_gets_model_api_key", "runtime_gets_raw_ebay_token", "secret_exposed"):
            if report_body.get(forbidden_key) is not False:
                return fail(f"AI CEO market report should keep {forbidden_key}=False: {report_body}")
        if raw_secret in json.dumps(market_report_response, ensure_ascii=False):
            return fail("AI CEO market report response must not expose the model API key")
        reports_after_market = fetch_json(f"{base_url}/reports?limit=30", token=token).get("reports", [])
        ai_market_reports = [item for item in reports_after_market if item.get("report_type") == "ai_ceo.market_research"]
        if not ai_market_reports:
            return fail(f"AI CEO market research report should be queryable from /reports: {reports_after_market}")
        if ai_market_reports[0].get("report_id") != ai_ceo_market_report.get("report_id"):
            return fail(f"latest /reports AI CEO market report should match the chat response: {ai_market_reports[0]}")
        audit_logs = fetch_json(f"{base_url}/audit-logs?limit=120", token=token).get("audit_logs", [])
        if not any(item.get("action_type") == "ai_ceo.market_research.saved" and item.get("target_id") == ai_ceo_market_report.get("report_id") for item in audit_logs):
            return fail("AI CEO market research report should leave a tenant audit record")

        safe_non_publish_report_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "请做一个 eBay 市场调研并推荐一个可做 Listing 的商品：travel mosquito repeller，不要执行真实发布。",
                "client_now": "2026-05-25T10:08:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-market-report-no-publish-test",
                    "text": "请做一个 eBay 市场调研并推荐一个可做 Listing 的商品：travel mosquito repeller，不要执行真实发布。",
                    "title": "AI CEO safe market research handoff",
                    "summary": "AI CEO market research with an explicit no-publish boundary should still become a Listing handoff report",
                    "intent": "listing_workflow",
                    "status": "ready",
                    "status_label": "model_chat",
                    "routes": [],
                },
            },
            token=token,
        )
        safe_non_publish_chat = safe_non_publish_report_response.get("ai_ceo_chat", {})
        if safe_non_publish_chat.get("status") != "model_answered":
            return fail(f"safe no-publish market research should still get a model answer: {safe_non_publish_chat}")
        safe_non_publish_report = safe_non_publish_report_response.get("ai_ceo_market_report", {})
        if safe_non_publish_report.get("report_type") != "ai_ceo.market_research":
            return fail(f"safe no-publish market research should still be saved as a structured report: {safe_non_publish_report}")
        safe_non_publish_body = safe_non_publish_report.get("report") if isinstance(safe_non_publish_report.get("report"), dict) else {}
        safe_non_publish_handoff = safe_non_publish_body.get("listing_handoff") if isinstance(safe_non_publish_body.get("listing_handoff"), dict) else {}
        if safe_non_publish_handoff.get("ready_for_listing_draft") is not False or safe_non_publish_handoff.get("triggers_real_platform_write") is not False:
            return fail(f"safe no-publish market report should remain saved but non-importable until facts are verified: {safe_non_publish_handoff}")
        reports_after_safe_non_publish = fetch_json(f"{base_url}/reports?limit=30", token=token).get("reports", [])
        if not any(item.get("report_id") == safe_non_publish_report.get("report_id") for item in reports_after_safe_non_publish):
            return fail("safe no-publish market report should be queryable from /reports")
        ai_market_report_count = len([item for item in reports_after_safe_non_publish if item.get("report_type") == "ai_ceo.market_research"])

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
        if realtime_chat.get("status") != "realtime_search_answered":
            return fail(f"realtime stock question should use live source records and the account model, got {realtime_chat}")
        if realtime_chat.get("route") != "external_realtime":
            return fail(f"realtime stock question should route as external_realtime, got {realtime_chat.get('route')}")
        if realtime_chat.get("memory_policy") != "transient_no_long_term_memory" or realtime_chat.get("long_term_memory") is not False:
            return fail(f"realtime stock question must not enter long-term merchant memory: {realtime_chat}")
        realtime_answer = str(realtime_chat.get("answer") or "")
        if "NASDAQ" not in realtime_answer or "来源" not in realtime_answer:
            return fail("realtime stock answer should cite live search sources")
        if len(FakeModelHandler.calls) != call_count + 1:
            return fail("realtime stock question should synthesize live source records through the account model")
        realtime_model_body = FakeModelHandler.calls[-1]["body"]
        if realtime_model_body.get("max_tokens") != 1000:
            return fail(f"realtime stock question should use the realtime token budget: {realtime_model_body}")
        realtime_performance = realtime_chat.get("performance") if isinstance(realtime_chat.get("performance"), dict) else {}
        if realtime_performance.get("model_timeout_seconds") != 18 or realtime_performance.get("model_max_output_tokens") != 1000:
            return fail(f"realtime stock question should expose the realtime model budget: {realtime_performance}")
        if (
            realtime_performance.get("search_budget_seconds") != 4
            or realtime_performance.get("search_max_results") != 5
            or realtime_performance.get("source_record_count", -1) < 1
        ):
            return fail(f"realtime stock question should expose sanitized realtime search budget and source count: {realtime_performance}")
        if not isinstance(realtime_chat.get("search_latency_ms"), int) or not isinstance(realtime_chat.get("model_latency_ms"), int):
            return fail(f"realtime stock question should expose search and model latency separately: {realtime_chat}")
        if not FakeSearchHandler.calls:
            return fail("realtime stock question should call the backend search provider")
        if not realtime_chat.get("work_records"):
            return fail("realtime stock question should return AI CEO work records")
        if not realtime_chat.get("confirmation_items"):
            return fail("realtime stock question should return confirmation guidance")
        source_policy = realtime_chat.get("source_policy", {})
        if source_policy.get("requires_source_records") is not True or source_policy.get("raw_provider_response_stored") is not False:
            return fail(f"realtime stock question should expose safe source policy, got {source_policy}")
        if "unit-test-search-credential-placeholder" in json.dumps(realtime_response, ensure_ascii=False):
            return fail("AI CEO realtime search response must not expose search provider credential")

        search_call_count = len(FakeSearchHandler.calls)
        market_model_call_count = len(FakeModelHandler.calls)
        market_news_response = post_json(
            f"{base_url}/stores/{store_id}/merchant-ceo/chat",
            {
                "message": "美股为什么大跌",
                "client_now": "2026-05-25T10:12:00+08:00",
                "client_timezone": "Asia/Shanghai",
                "command": {
                    "id": "ceo-chat-market-news-test",
                    "text": "美股为什么大跌",
                    "title": "市场新闻问题",
                    "summary": "AI CEO chat realtime market news question",
                    "intent": "question",
                    "status": "ready",
                    "status_label": "realtime_search",
                    "routes": [],
                },
            },
            token=token,
        )
        market_news_chat = market_news_response.get("ai_ceo_chat", {})
        if market_news_chat.get("status") != "realtime_search_answered":
            return fail(f"market move question should use realtime search and the account model: {market_news_chat}")
        if market_news_chat.get("route") != "external_realtime" or market_news_chat.get("realtime_kind") != "news_search":
            return fail(f"market move question should route as realtime news_search: {market_news_chat}")
        if len(FakeSearchHandler.calls) <= search_call_count:
            return fail("market move question should call the backend search provider")
        if len(FakeModelHandler.calls) != market_model_call_count + 2:
            return fail("dated market news should make one synthesis call and one evidence review through the account model")
        if market_news_chat.get("answer_stream_buffered") is not True or not market_news_chat.get("temporal_evidence_quality", {}).get("accepted"):
            return fail("dated market news should pass the temporal review before returning its answer")
        if realtime_response.get("ai_ceo_market_report") is not None:
            return fail("realtime stock question must not be saved as an AI CEO Listing handoff report")
        if realtime_response.get("ai_ceo_market_report_delivery") is not None:
            return fail("realtime stock question must not return an AI CEO Listing handoff delivery")
        if market_news_response.get("ai_ceo_market_report") is not None:
            return fail("market news question must not be saved as an AI CEO Listing handoff report")
        if market_news_response.get("ai_ceo_market_report_delivery") is not None:
            return fail("market news question must not return an AI CEO Listing handoff delivery")
        reports_after_market_news = fetch_json(f"{base_url}/reports?limit=30", token=token).get("reports", [])
        if len([item for item in reports_after_market_news if item.get("report_type") == "ai_ceo.market_research"]) != ai_market_report_count:
            return fail("finance/news questions should not create extra AI CEO market research handoff reports")

        latest = fetch_json(f"{base_url}/stores/{store_id}/merchant-ceo/commands/latest", token=token)
        latest_command = latest.get("command", {})
        if latest_command.get("ai_reply_status") != "realtime_search_answered":
            return fail("latest AI CEO command should keep realtime model-synthesis status")
        if str(latest_command.get("ai_reply") or "") != market_news_chat.get("answer"):
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
        for key, value in previous_local_resolver_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
