#!/usr/bin/env python3
"""Regression for the public search probe adapter shell."""

from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import MarketDataPacketBuilder, PublicSearchProbeAdapter, PublicSearchProbeConfig
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    adapter = PublicSearchProbeAdapter()
    snapshot = adapter.probe(
        PublicSearchProbeConfig(
            query="stainless steel tumbler ebay reviews supplier",
            provider="unit-test",
            results=sample_results(),
        )
    )
    if snapshot.get("status") != "ready":
        return fail("sample public search results should normalize to ready")
    if snapshot.get("metrics", {}).get("result_count") != 4:
        return fail("result_count should be 4")
    if snapshot.get("metrics", {}).get("commercial_result_count", 0) < 3:
        return fail("commerce hints should be detected")

    pending = adapter.probe(PublicSearchProbeConfig(query="stainless steel tumbler", live_enabled=False))
    if pending.get("status") != "pending_tool":
        return fail("live-disabled search should stay pending_tool")

    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_tavily = os.environ.get("TAVILY_API_KEY")
    previous_jiejing_search_key = os.environ.get("JIEJING_SEARCH_API_KEY")
    try:
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ.pop("TAVILY_API_KEY", None)
        os.environ.pop("JIEJING_SEARCH_API_KEY", None)
        tavily_missing_key = adapter.probe(PublicSearchProbeConfig(query="stainless steel tumbler", provider="tavily", live_enabled=True, api_key=""))
    finally:
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("TAVILY_API_KEY", previous_tavily)
        restore_env("JIEJING_SEARCH_API_KEY", previous_jiejing_search_key)
    if tavily_missing_key.get("status") not in {"pending_tool", "ready", "failed_tool"}:
        return fail("tavily live search should return a controlled status")
    if tavily_missing_key.get("provider") != "tavily":
        return fail("tavily provider should be normalized")
    if tavily_missing_key.get("status") != "pending_tool" and "error" in tavily_missing_key and "tvly-" in tavily_missing_key.get("error", ""):
        return fail("tavily error must not expose the api key")

    fake_tavily = FakeTavilySearchAdapter()
    tavily_snapshot = fake_tavily.probe(
        PublicSearchProbeConfig(
            query="stainless steel tumbler eBay public demand",
            provider="tavily",
            api_key="unit-test-tavily-key",
            live_enabled=True,
            max_results=3,
        )
    )
    if tavily_snapshot.get("status") != "ready":
        return fail("fake tavily live results should normalize to ready")
    if tavily_snapshot.get("metrics", {}).get("provider") != "tavily":
        return fail("fake tavily metrics should preserve provider")
    if "insulated" not in tavily_snapshot.get("results", [{}])[0].get("snippet", "").lower():
        return fail("tavily content field should normalize into snippet")
    if tavily_snapshot.get("metrics", {}).get("secret_exposed") is not False:
        return fail("tavily metrics must not expose secrets")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate public search snapshot handoff.",
            project_id="public-search-probe-regression",
            public_search_probe={
                "query": "stainless steel tumbler ebay reviews supplier",
                "provider": "unit-test",
                "results": sample_results(),
            },
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    probes = {probe.get("key"): probe for probe in data_packet.get("report", {}).get("probes", [])}
    public_probe = probes.get("public_search")
    if not public_probe or public_probe.get("status") != "ready":
        return fail("market.data_packet should accept public search probe snapshots")
    if any(item.get("input_id") == "public_search_results" for item in data_packet.get("missing_inputs", [])):
        return fail("ready public search snapshot should remove public_search_results blocker")

    print("PASS public_search_probe_regression")
    return 0


class FakeTavilySearchAdapter(PublicSearchProbeAdapter):
    def _run_tavily_provider(self, endpoint: str, api_key: str, config: PublicSearchProbeConfig) -> list[dict]:
        if "unit-test" not in api_key:
            return []
        return [
            {
                "title": "Insulated tumbler eBay examples",
                "url": "https://www.ebay.com/sch/i.html?_nkw=insulated+tumbler",
                "content": "Insulated travel cup listings emphasize leak resistance, gift bundles, and shipping clarity.",
                "score": 0.91,
            }
        ]


def sample_results() -> list[dict]:
    return [
        {
            "title": "30oz Stainless Steel Tumbler with Straw - eBay",
            "url": "https://www.ebay.com/sch/i.html?_nkw=stainless+steel+tumbler",
            "snippet": "Public eBay search page showing price and listing language.",
        },
        {
            "title": "Insulated Tumblers Reviews and Buying Guide",
            "url": "https://example.com/tumbler-reviews",
            "snippet": "Review page compares lids, insulation claims, leakage, and gift bundles.",
        },
        {
            "title": "1688 stainless steel tumbler wholesale",
            "url": "https://s.1688.com/selloffer/offer_search.htm?keywords=tumbler",
            "snippet": "Wholesale supplier search page with price and MOQ language.",
        },
        {
            "title": "Amazon tumbler gift set examples",
            "url": "https://www.amazon.com/s?k=tumbler+gift+set",
            "snippet": "Public reference page for bundle language and buyer expectations.",
        },
    ]


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
