#!/usr/bin/env python3
"""Regression for Jiejing-owned public search provider job live boundary."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.provider_job_runner import ProviderJobRunner  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


ENV_KEYS = (
    "JIEJING_PUBLIC_SEARCH_LIVE_ENABLED",
    "JIEJING_PUBLIC_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    resolver_path = ROOT / "output" / "test-public-search-secret-resolver.json"
    try:
        _clear_env()
        settings = _settings()
        dry = ProviderJobRunner(settings=settings).run(
            company_id="company_search",
            store_id="store_search",
            user_id="user_search",
            task_id="task_search_dry",
            job_id="job_search_dry",
            job_body={
                "provider_job_key": "public_search.market_research",
                "inputs": {
                    "query": "eBay travel storage bag market demand",
                    "marketplace": "EBAY_US",
                    "category_hint": "travel accessories",
                },
            },
        )
        if dry.get("status") != "completed_dry_run":
            return fail("public search should remain dry-run unless live flag is enabled")
        if dry.get("safety", {}).get("live_provider_called") is not False:
            return fail("dry-run public search must not call the live provider")

        _clear_env()
        if resolver_path.exists():
            resolver_path.unlink()
        os.environ["JIEJING_PUBLIC_SEARCH_LIVE_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(resolver_path)
        live_settings = _settings()
        secret_ref = {
            "secret_ref": "secret_public_search",
            "company_id": "company_search",
            "store_id": "store_search",
            "provider": "public_search",
            "purpose": "public_search_api_key",
            "status": "external_vault_required",
        }
        VaultSecretResolver(live_settings).store_local_secret(
            secret_ref=secret_ref,
            secret_value="PUBLIC-SEARCH-KEY-MUST-NOT-LEAK",
            created_by="user_search",
        )
        seen = {"tavily_post": False}

        def fake_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            if request.get_method() != "POST" or request.full_url != "https://api.tavily.com/search":
                return 404, {"content-type": "application/json"}, b'{"error":"unexpected_url"}'
            seen["tavily_post"] = True
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            if auth != "Bearer PUBLIC-SEARCH-KEY-MUST-NOT-LEAK":
                return 401, {"content-type": "application/json"}, b'{"error":"bad_auth"}'
            body = json.loads((request.data or b"{}").decode("utf-8"))
            if "travel storage bag" not in str(body.get("query") or ""):
                return 400, {"content-type": "application/json"}, b'{"error":"bad_query"}'
            return (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "query": body.get("query"),
                        "results": [
                            {
                                "title": "Travel storage bag demand rises on marketplace search",
                                "url": "https://example.com/market/travel-storage-bag",
                                "content": "Buyers compare lightweight travel organizers, storage bags, and compression pouches.",
                                "score": 0.91,
                            },
                            {
                                "title": "eBay accessory sellers test bundle offers",
                                "url": "https://example.com/ebay/bundles",
                                "content": "Bundle pricing and pack quantity shape conversion in travel accessory categories.",
                                "score": 0.77,
                            },
                        ],
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
            )

        live = ProviderJobRunner(settings=live_settings, transport=fake_transport).run(
            company_id="company_search",
            store_id="store_search",
            user_id="user_search",
            task_id="task_search_live",
            job_id="job_search_live",
            job_body={
                "provider_job_key": "public_search.market_research",
                "secret_ref": "secret_public_search",
                "inputs": {
                    "query": "eBay travel storage bag market demand",
                    "marketplace": "EBAY_US",
                    "category_hint": "travel accessories",
                    "max_results": 2,
                },
            },
        )
        if live.get("status") != "completed_live_read":
            return fail("public search should complete a live read when live flag and secret_ref are ready")
        if seen != {"tavily_post": True}:
            return fail("public search live path should call Tavily once")
        if live.get("safety", {}).get("live_provider_called") is not True or live.get("safety", {}).get("raw_secret_read") is not True:
            return fail("public search live path should mark live call and backend secret read")
        packet = live.get("output_packet", {})
        if packet.get("packet_type") != "market_public_search_signal" or packet.get("result_count") != 2:
            return fail("public search live path should emit normalized market_public_search_signal records")
        source_record = live.get("source_record", {})
        if source_record.get("source_mode") != "live_public_search" or source_record.get("raw_provider_response_stored") is not False:
            return fail("public search source record should be live and should not store raw provider response")
        serialized = json.dumps(live, ensure_ascii=False)
        forbidden = (
            "PUBLIC-SEARCH-KEY-MUST-NOT-LEAK",
            "Authorization",
            "Bearer ",
        )
        if any(value in serialized for value in forbidden):
            return fail("public search live output leaked API key or authorization header")
        if live.get("real_platform_writes_enabled") is not False or live.get("secret_exposed") is not False:
            return fail("public search live output must preserve no-write and no-secret flags")
        if resolver_path.exists():
            resolver_path.unlink()
        print("PASS jiejing_public_search_provider_job")
        return 0
    finally:
        if resolver_path.exists():
            resolver_path.unlink()
        _restore_env(previous)


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _settings() -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=ROOT / "output" / "test-public-search-provider-job.sqlite",
        runtime_db_path=ROOT / "output" / "test-public-search-provider-job-runtime.sqlite",
        output_root=ROOT / "output" / "test-public-search-provider-job",
        host="127.0.0.1",
        port=8804,
    )


if __name__ == "__main__":
    raise SystemExit(main())
