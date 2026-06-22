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

    def fake_urlopen(request: Any, timeout: int = 0) -> FakeResponse:  # noqa: ARG001
        url = str(getattr(request, "full_url", request))
        calls.append(url)
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
        ai_ceo_chat.urllib.request.urlopen = fake_urlopen

        result = ai_ceo_chat._run_realtime_search(kind="web_search", message="帮我联网搜索 eBay 最新政策")
    finally:
        ai_ceo_chat.urllib.request.urlopen = old_urlopen
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
    if not calls or "duckduckgo.com/html" not in calls[0]:
        return fail(f"builtin web search should call the public web source, calls={calls}")
    print("PASS jiejing_ai_ceo_builtin_web_search")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
