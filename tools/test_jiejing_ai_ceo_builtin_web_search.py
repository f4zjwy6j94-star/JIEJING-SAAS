#!/usr/bin/env python3
"""Regression test for AI CEO no-key realtime web-search fallback."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def read(self, *_args: Any) -> bytes:
        return self.body


def main() -> int:
    import sys

    sys.path.insert(0, str(ROOT))
    from jiejing_saas import ai_ceo_chat

    old_env = os.environ.copy()
    old_urlopen = ai_ceo_chat.urllib.request.urlopen

    calls: list[str] = []
    timeouts: list[int] = []

    def fake_urlopen(request: Any, timeout: int = 0) -> FakeResponse:  # noqa: ARG001
        url = str(getattr(request, "full_url", request))
        calls.append(url)
        timeouts.append(timeout)
        if "duckduckgo.com/html" in url and "empty-market-term" in url:
            return FakeResponse("<html><body>No public web results for this regression fixture.</body></html>")
        if "api.duckduckgo.com" in url and "empty-market-term" in url:
            return FakeResponse("{}")
        if "duckduckgo.com/html" in url:
            return FakeResponse(
                """
                <html><body>
                  <a rel="nofollow" class="result__a"
                     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fmarket-report">
                     Example Market Update
                  </a>
                  <a class="result__snippet">Fresh public web source snippet for the merchant question.</a>
                </body></html>
                """
            )
        return FakeResponse("{}")

    try:
        for key in ("TAVILY_API_KEY", "JIEJING_SEARCH_API_KEY", "JIEJING_SEARCH_ENDPOINT"):
            os.environ.pop(key, None)
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ["JIEJING_AI_CEO_REALTIME_SEARCH_ENABLED"] = "1"
        os.environ["JIEJING_AI_CEO_BUILTIN_WEB_FALLBACK_ENABLED"] = "1"
        os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_TIMEOUT_SECONDS"] = "1"
        os.environ["JIEJING_AI_CEO_DEFAULT_WEB_CONTEXT_CACHE_SECONDS"] = "180"
        ai_ceo_chat.urllib.request.urlopen = fake_urlopen

        result = ai_ceo_chat._run_realtime_search(kind="web_search", message="帮我联网搜索 eBay 最新政策")
        ai_ceo_chat._DEFAULT_WEB_CONTEXT_CACHE.clear()
        calls_before_default = len(calls)
        default_first = ai_ceo_chat._run_default_web_context_search(
            route=ai_ceo_chat.AI_CEO_ROUTE_GENERAL,
            message="Introduce Jiejing in one sentence.",
        )
        calls_after_default_first = len(calls)
        default_second = ai_ceo_chat._run_default_web_context_search(
            route=ai_ceo_chat.AI_CEO_ROUTE_GENERAL,
            message="Introduce Jiejing in one sentence.",
        )
        calls_after_default_second = len(calls)
        ai_ceo_chat._DEFAULT_WEB_CONTEXT_CACHE.clear()
        empty_calls_before = len(calls)
        default_empty_first = ai_ceo_chat._run_default_web_context_search(
            route=ai_ceo_chat.AI_CEO_ROUTE_GENERAL,
            message="empty-market-term",
        )
        empty_calls_after_first = len(calls)
        default_empty_second = ai_ceo_chat._run_default_web_context_search(
            route=ai_ceo_chat.AI_CEO_ROUTE_GENERAL,
            message="empty-market-term",
        )
        empty_calls_after_second = len(calls)
    finally:
        ai_ceo_chat.urllib.request.urlopen = old_urlopen
        ai_ceo_chat._DEFAULT_WEB_CONTEXT_CACHE.clear()
        os.environ.clear()
        os.environ.update(old_env)

    if result.get("status") != "ready":
        return fail(f"builtin web search should return ready, got {result}")
    if result.get("provider") != "builtin_public_web":
        return fail(f"builtin web search should expose builtin provider, got {result.get('provider')}")
    records = result.get("source_records") if isinstance(result.get("source_records"), list) else []
    if not records or records[0].get("domain") != "example.com":
        return fail(f"builtin web search should normalize source records: {records}")
    provider_status = result.get("provider_status") if isinstance(result.get("provider_status"), dict) else {}
    if provider_status.get("credential_present") is not False or result.get("secret_exposed") is not False:
        return fail("builtin web search must not expose or require search credentials")
    if result.get("search_budget_contract") != "2026-07-04-ai-ceo-public-search-budget-v1":
        return fail(f"builtin web search should expose the public search budget contract, got {result}")
    if result.get("search_budget_seconds") != 4 or result.get("search_max_results") != 5:
        return fail(f"builtin web search should expose sanitized default search budget, got {result}")
    if not calls or "duckduckgo.com/html" not in calls[0]:
        return fail(f"builtin web search should call the public web source, calls={calls}")
    if default_first.get("status") != "ready" or default_first.get("used_for_model_prompt") is not True:
        return fail(f"default web context should be ready for model prompt, got {default_first}")
    if default_first.get("search_budget_seconds") != 1:
        return fail(f"default web context should use short search budget, got {default_first}")
    if default_first.get("search_max_results") != 3 or default_first.get("search_depth") != "fast":
        return fail(f"default web context should use fast short-question search budget, got {default_first}")
    if not isinstance(default_first.get("search_latency_ms"), int) or default_first.get("search_latency_ms", -1) < 0:
        return fail(f"default web context should expose sanitized search latency, got {default_first}")
    if calls_after_default_first <= calls_before_default:
        return fail("first default web context lookup should call the public source")
    if default_second.get("cache_status") != "hit":
        return fail(f"second default web context lookup should hit sanitized cache, got {default_second}")
    if default_second.get("search_latency_ms") != 0:
        return fail(f"cached default web context should not report provider latency, got {default_second}")
    if calls_after_default_second != calls_after_default_first:
        return fail(f"cached default web context should not call public source again: {calls}")
    if timeouts[-1] != 1:
        return fail(f"default web context should pass the short timeout to urlopen, got {timeouts}")
    if default_empty_first.get("used_for_model_prompt") is not False:
        return fail(f"empty default web context should not be used for model prompt: {default_empty_first}")
    if empty_calls_after_first <= empty_calls_before:
        return fail("first empty default web context lookup should call the public source")
    if default_empty_second.get("cache_status") != "hit_no_sources":
        return fail(f"empty default web context lookup should short-cache no-source checks, got {default_empty_second}")
    if default_empty_second.get("search_latency_ms") != 0:
        return fail(f"cached empty default web context should not report provider latency, got {default_empty_second}")
    if empty_calls_after_second != empty_calls_after_first:
        return fail(f"cached empty default web context should not call public source again: {calls}")
    print("PASS jiejing_ai_ceo_builtin_web_search")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
