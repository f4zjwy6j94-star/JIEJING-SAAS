#!/usr/bin/env python3
"""Regression for live-model and tool-provider contracts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import (  # noqa: E402
    EbayListingMetadataAdapter,
    EbayListingMetadataConfig,
    EbayCredentialResolver,
    EbayProviderStatus,
    DeepSeekModelClient,
    JiejingAgentAdapter,
    MediaGenerationAdapter,
    MediaGenerationConfig,
    RuntimeComparisonScorer,
)
from jiejing_runtime.model_clients import ModelClient, model_client_from_env  # noqa: E402
from jiejing_runtime.models import JiejingTask  # noqa: E402
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


class FakeLiveModelClient(ModelClient):
    name = "fake-live-model"
    version = "0.1-test"

    def generate_report(self, task: JiejingTask) -> dict:
        sections = {section: f"live model section for {section}" for section in task.output_contract.get("required_sections", [])}
        sections["model_extra"] = "extra live section"
        return {
            "model_configured": True,
            "model_mode": "test_live_model",
            "merchant_readable_summary": f"Live model assisted report for {task.task_type}",
            "required_sections": task.output_contract.get("required_sections", []),
            "sections": sections,
            "limits": ["test live model; no real write"],
        }


class FakeErrorModelClient(ModelClient):
    name = "fake-error-model"
    version = "0.1-test"

    def generate_report(self, task: JiejingTask) -> dict:
        fallback = FakeLiveModelClient().generate_report(task)
        fallback["model_mode"] = "http_model_error_fallback"
        fallback["model_error"] = "simulated provider failure"
        fallback["model_configured"] = True
        return fallback


class FakeFalMediaAdapter(MediaGenerationAdapter):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _post_json(self, endpoint: str, authorization: str, payload: dict, timeout_seconds: int, proxy_url: str = "") -> dict:
        if endpoint != "https://fal.run/openai/gpt-image-2":
            raise AssertionError(f"FAL provider should build current gpt-image-2 endpoint, got {endpoint}")
        if authorization != "Key unit-id:unit-secret":
            raise AssertionError("FAL provider should use Key authorization in memory only")
        if not (1 <= payload.get("num_images", 0) <= 4) or payload.get("image_size") != "square_hd" or payload.get("quality") != "low":
            raise AssertionError(f"FAL provider should send gpt-image-2 payload shape, got {payload}")
        self.calls.append(payload)
        return {
            "provider": "fal-test",
            "images": [
                {
                    "asset_id": "fal_main_01",
                    "asset_type": "main_image",
                    "url": "https://example.test/fal-main.png",
                    "dimensions": "1600x1600",
                    "commercial_use_status": "needs_review",
                }
            ],
        }


def main() -> int:
    result = validate_listing_metadata_adapter()
    if result:
        return result
    result = validate_ebay_provider_status()
    if result:
        return result
    result = validate_ebay_hermes_snapshot_resolver()
    if result:
        return result
    result = validate_media_generation_adapter()
    if result:
        return result
    result = validate_agent_model_and_tool_enrichment()
    if result:
        return result
    result = validate_agent_model_error_boundary()
    if result:
        return result
    result = validate_market_env_switches()
    if result:
        return result
    result = validate_shadow_compare()
    if result:
        return result
    result = validate_deepseek_hermes_credential_loader()
    if result:
        return result
    result = validate_default_model_prefers_deepseek_when_available()
    if result:
        return result
    print("PASS live_tool_contracts_regression")
    return 0


def validate_listing_metadata_adapter() -> int:
    adapter = EbayListingMetadataAdapter()
    snapshot = adapter.probe(
        EbayListingMetadataConfig(
            marketplace_id="EBAY_US",
            category_id="20687",
            taxonomy_response=sample_taxonomy(),
            fulfillment_policy_response={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful_1", "name": "SpeedPAK Default", "marketplaceId": "EBAY_US"}]},
            payment_policy_response={"paymentPolicies": [{"paymentPolicyId": "pay_1", "name": "eBay Managed Payments", "marketplaceId": "EBAY_US"}]},
            return_policy_response={"returnPolicies": [{"returnPolicyId": "ret_1", "name": "14 Day Buyer Pays", "marketplaceId": "EBAY_US"}]},
        )
    )
    if snapshot.get("status") != "ready":
        return fail("listing metadata snapshot should be ready")
    if len(snapshot.get("required_aspects", [])) != 2:
        return fail("required taxonomy aspects should be normalized")
    if snapshot.get("business_policies", {}).get("fulfillment", [{}])[0].get("id") != "ful_1":
        return fail("fulfillment policy id should normalize")
    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_read_token = os.environ.get("JIEJING_EBAY_READ_TOKEN")
    previous_account_token = os.environ.get("JIEJING_EBAY_ACCOUNT_READ_TOKEN")
    previous_ebay_token = os.environ.get("EBAY_ACCESS_TOKEN")
    try:
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ.pop("JIEJING_EBAY_READ_TOKEN", None)
        os.environ.pop("JIEJING_EBAY_ACCOUNT_READ_TOKEN", None)
        os.environ.pop("EBAY_ACCESS_TOKEN", None)
        pending = adapter.probe(EbayListingMetadataConfig(live_enabled=True, category_id="20687", access_token=None))
        if pending.get("status") != "pending_connector":
            return fail("listing metadata live probe without token should stay pending")
    finally:
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("JIEJING_EBAY_READ_TOKEN", previous_read_token)
        restore_env("JIEJING_EBAY_ACCOUNT_READ_TOKEN", previous_account_token)
        restore_env("EBAY_ACCESS_TOKEN", previous_ebay_token)
    return 0


def validate_ebay_provider_status() -> int:
    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_token = os.environ.get("JIEJING_EBAY_READ_TOKEN")
    try:
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ["JIEJING_EBAY_READ_TOKEN"] = "unit-ebay-token"
        status = EbayProviderStatus().to_dict()
        if status.get("provider") != "ebay" or status.get("credential_present") is not True:
            return fail("eBay provider status should expose sanitized credential presence")
        serialized = json.dumps(status)
        if "unit-ebay-token" in serialized or "api_key" in serialized:
            return fail("eBay provider status must not expose raw credential")
        if status.get("surfaces", {}).get("write_execution", {}).get("status") != "blocked_until_confirmation_service":
            return fail("eBay write execution should remain blocked in provider status")
    finally:
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("JIEJING_EBAY_READ_TOKEN", previous_token)
    return 0


def validate_ebay_hermes_snapshot_resolver() -> int:
    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_home = os.environ.get("JIEJING_HERMES_WSL_HOME")
    previous_token = os.environ.get("JIEJING_EBAY_READ_TOKEN")
    try:
        os.environ.pop("JIEJING_EBAY_READ_TOKEN", None)
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "1"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root_token_dir = root / "credentials"
            root_token_dir.mkdir(parents=True)
            (root_token_dir / "ebay_production_user_token.json").write_text(
                json.dumps({"access_token": "unit-root-ebay-token", "refresh_token": "unit-refresh", "app_id": "unit-app", "expires_at": time.time() + 7200}),
                encoding="utf-8",
            )
            (root_token_dir / "ebay_production_app_keyset.json").write_text(
                json.dumps({"client_id": "unit-app", "cert_id": "unit-cert"}),
                encoding="utf-8",
            )
            token_dir = root / "profiles" / "market-manager" / "credentials"
            token_dir.mkdir(parents=True)
            (token_dir / "ebay_production_user_token.json").write_text(
                json.dumps({"access_token": "unit-old-profile-ebay-token", "token_type": "User Access Token", "expires_at": time.time() - 3600}),
                encoding="utf-8",
            )
            policy_dir = root / "output" / "ebay-account"
            policy_dir.mkdir(parents=True)
            (policy_dir / "business_policies_latest.json").write_text(
                json.dumps(
                    {
                        "policies": {
                            "fulfillment": {
                                "policies": [
                                    {"fulfillmentPolicyId": "ful_wsl", "name": "SpeedPAK Default", "marketplaceId": "EBAY_US"}
                                ]
                            },
                            "payment": {
                                "policies": [{"paymentPolicyId": "pay_wsl", "name": "Managed Payments", "marketplaceId": "EBAY_US"}]
                            },
                            "return": {
                                "policies": [{"returnPolicyId": "ret_wsl", "name": "14 Day Returns", "marketplaceId": "EBAY_US"}]
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.environ["JIEJING_HERMES_WSL_HOME"] = str(root)
            resolver = EbayCredentialResolver()
            token, source = resolver.resolve_access_token()
            if token != "unit-root-ebay-token" or source != "wsl_hermes_root_credential_file":
                return fail("eBay resolver should prefer fresh Hermes root token over stale profile token")
            refresh = resolver.oauth_refresh_status()
            if refresh.get("refresh_ready") is not True:
                return fail("eBay resolver should detect Hermes refresh readiness from root keyset")
            summary = resolver.policy_snapshot_summary()
            if summary.get("counts", {}).get("fulfillment") != 1:
                return fail("eBay resolver should summarize Hermes policy snapshots")
            snapshot = EbayListingMetadataAdapter().probe(EbayListingMetadataConfig(live_enabled=True, category_id=""))
            serialized = json.dumps(snapshot)
            if "unit-wsl-ebay-token" in serialized or "api_key" in serialized:
                return fail("listing metadata snapshot must not expose Hermes token")
            if snapshot.get("business_policies", {}).get("fulfillment", [{}])[0].get("id") != "ful_wsl":
                return fail("listing metadata should use Hermes policy snapshot fallback")
    finally:
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("JIEJING_HERMES_WSL_HOME", previous_home)
        restore_env("JIEJING_EBAY_READ_TOKEN", previous_token)
    return 0


def validate_media_generation_adapter() -> int:
    adapter = MediaGenerationAdapter()
    snapshot = adapter.generate(
        MediaGenerationConfig(
            product="foldable travel organizer",
            asset_manifest={
                "provider": "unit-test-provider",
                "assets": [
                    {
                        "asset_id": "main_01",
                        "asset_type": "main_image",
                        "url": "https://example.test/main.jpg",
                        "dimensions": "1600x1600",
                        "commercial_use_status": "needs_review",
                    },
                    {
                        "asset_id": "video_01",
                        "asset_type": "product_video",
                        "url": "https://example.test/video.mp4",
                        "duration_seconds": 24,
                    },
                ],
            },
        )
    )
    if snapshot.get("status") != "ready" or len(snapshot.get("assets", [])) != 2:
        return fail("media manifest should normalize generated assets")
    pending = adapter.generate(MediaGenerationConfig(product="foldable travel organizer", live_enabled=True))
    if pending.get("status") != "pending_provider":
        return fail("media generation without provider should stay pending")
    fake_fal = FakeFalMediaAdapter()
    live_snapshot = fake_fal.generate(
        MediaGenerationConfig(
            product="foldable travel organizer",
            live_enabled=True,
            provider="fal",
            api_key="unit-id:unit-secret",
            image_prompt="Generate one clean eBay main image.",
            image_count=1,
        )
    )
    serialized = json.dumps(live_snapshot)
    if live_snapshot.get("status") != "ready" or len(live_snapshot.get("assets", [])) != 1:
        return fail("FAL media provider should normalize returned assets")
    if "unit-secret" in serialized or "api_key" in serialized:
        return fail("FAL media snapshot must not expose raw credential")
    batched_fal = FakeFalMediaAdapter()
    batched_snapshot = batched_fal.generate(
        MediaGenerationConfig(
            product="foldable travel organizer",
            live_enabled=True,
            provider="fal",
            api_key="unit-id:unit-secret",
            image_prompt="Generate five clean eBay images.",
            image_count=5,
        )
    )
    if [call.get("num_images") for call in batched_fal.calls] != [4, 1]:
        return fail(f"FAL media provider should split five images into 4+1 batches: {batched_fal.calls}")
    if batched_snapshot.get("status") != "ready" or len(batched_snapshot.get("assets", [])) != 2:
        return fail("batched FAL media snapshot should merge returned assets")
    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_id = os.environ.get("FAL_KEY_ID")
    previous_secret = os.environ.get("FAL_KEY_SECRET")
    try:
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ["FAL_KEY_ID"] = "unit-id"
        os.environ["FAL_KEY_SECRET"] = "unit-secret"
        status = MediaGenerationAdapter().provider_status("fal")
        if status.get("configured") is not True or status.get("credential_present") is not True:
            return fail("FAL provider status should detect configured env pair")
        if "unit-secret" in json.dumps(status) or "api_key" in json.dumps(status):
            return fail("FAL provider status must not expose raw credential")
    finally:
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("FAL_KEY_ID", previous_id)
        restore_env("FAL_KEY_SECRET", previous_secret)
    return 0


def validate_agent_model_and_tool_enrichment() -> int:
    market_tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Foldable Travel Organizer",
            merchant_goal="Prepare market report with supplied source probes.",
            project_id="market-tool-regression",
            public_search_probe={
                "results": [
                    {
                        "title": "Foldable Travel Organizer eBay examples",
                        "url": "https://www.ebay.com/sch/i.html?_nkw=foldable+travel+organizer",
                        "snippet": "Public eBay search page with travel organizer listings.",
                    }
                ]
            },
            ebay_read_only_probe={
                "keyword": "foldable travel organizer",
                "browse_response": {"total": 12, "itemSummaries": []},
            },
        )
    )
    market_result = JiejingAgentAdapter(model_client=FakeLiveModelClient()).execute(JiejingTask(market_tasks[2]))
    if "market_data_packet" not in market_result.get("report", {}).get("sections", {}):
        return fail("market report should include market data packet when probes are supplied")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Foldable Travel Organizer",
            merchant_goal="Prepare product listing and assets.",
            project_id="live-tool-contract-regression",
            listing_metadata_probe={
                "marketplace_id": "EBAY_US",
                "category_id": "20687",
                "taxonomy_response": sample_taxonomy(),
                "fulfillment_policy_response": {"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful_1", "name": "SpeedPAK Default"}]},
                "payment_policy_response": {"paymentPolicies": [{"paymentPolicyId": "pay_1", "name": "Managed Payments"}]},
                "return_policy_response": {"returnPolicies": [{"returnPolicyId": "ret_1", "name": "14 Day Returns"}]},
            },
            media_generation_probe={
                "asset_manifest": {
                    "assets": [
                        {"asset_type": "main_image", "url": "https://example.test/main.jpg", "dimensions": "1600x1600"},
                        {"asset_type": "detail_page", "url": "https://example.test/detail.jpg", "dimensions": "1200x3600"},
                    ]
                }
            },
        )
    )
    adapter = JiejingAgentAdapter(model_client=FakeLiveModelClient())
    listing_result = adapter.execute(JiejingTask(tasks[4]))
    report = listing_result.get("report", {})
    if report.get("model_assist", {}).get("status") != "applied":
        return fail("live model assist should be applied")
    if "ebay_listing_metadata" not in report.get("sections", {}):
        return fail("listing package should include eBay listing metadata section")
    if not any(record.get("source_id", "").endswith("ebay_listing_metadata") for record in listing_result.get("source_records", [])):
        return fail("listing metadata should create a source record")
    if listing_result.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("listing enrichment must not permit real execution")

    asset_result = adapter.execute(JiejingTask(tasks[5]))
    asset_report = asset_result.get("report", {})
    if "media_generation" not in asset_report.get("sections", {}):
        return fail("asset brief should include media generation section")
    if asset_report.get("media_generation_probe", {}).get("status") != "ready":
        return fail("asset manifest should be ready")
    return 0


def validate_agent_model_error_boundary() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Foldable Travel Organizer",
            merchant_goal="Validate model error boundary.",
            project_id="model-error-boundary-regression",
        )
    )
    result = JiejingAgentAdapter(model_client=FakeErrorModelClient()).execute(JiejingTask(tasks[0]))
    assist = result.get("report", {}).get("model_assist", {})
    if assist.get("status") != "fallback_error":
        return fail("model provider errors should be recorded as fallback_error, not applied")
    if not result.get("report", {}).get("model_error"):
        return fail("model provider error should be preserved in the report")
    return 0


def validate_market_env_switches() -> int:
    previous_search = os.environ.get("JIEJING_SEARCH_LIVE")
    previous_search_provider = os.environ.get("JIEJING_SEARCH_PROVIDER")
    previous_ebay = os.environ.get("JIEJING_EBAY_READ_LIVE")
    previous_lookup = os.environ.get("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP")
    previous_read_token = os.environ.get("JIEJING_EBAY_READ_TOKEN")
    previous_account_token = os.environ.get("JIEJING_EBAY_ACCOUNT_READ_TOKEN")
    previous_ebay_token = os.environ.get("EBAY_ACCESS_TOKEN")
    try:
        os.environ["JIEJING_SEARCH_LIVE"] = "1"
        os.environ["JIEJING_SEARCH_PROVIDER"] = "snapshot"
        os.environ["JIEJING_EBAY_READ_LIVE"] = "1"
        os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "0"
        os.environ.pop("JIEJING_EBAY_READ_TOKEN", None)
        os.environ.pop("JIEJING_EBAY_ACCOUNT_READ_TOKEN", None)
        os.environ.pop("EBAY_ACCESS_TOKEN", None)
        from jiejing_runtime import MarketDataPacketBuilder

        task = JiejingTask(build_product_workflow(ProductWorkflowRequest(product="Test Organizer", merchant_goal="Test env probes."))[1])
        packet = MarketDataPacketBuilder().build(task)
        probes = {probe.get("key"): probe for probe in packet.get("report", {}).get("probes", [])}
        if probes.get("public_search", {}).get("status") != "pending_tool":
            return fail("env live search without endpoint should return pending_tool")
        if probes.get("ebay_read_only", {}).get("status") != "pending_connector":
            return fail("env live eBay without token should return pending_connector")
    finally:
        restore_env("JIEJING_SEARCH_LIVE", previous_search)
        restore_env("JIEJING_SEARCH_PROVIDER", previous_search_provider)
        restore_env("JIEJING_EBAY_READ_LIVE", previous_ebay)
        restore_env("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", previous_lookup)
        restore_env("JIEJING_EBAY_READ_TOKEN", previous_read_token)
        restore_env("JIEJING_EBAY_ACCOUNT_READ_TOKEN", previous_account_token)
        restore_env("EBAY_ACCESS_TOKEN", previous_ebay_token)
    return 0


def validate_shadow_compare() -> int:
    tasks = build_product_workflow(ProductWorkflowRequest(product="Test Organizer", merchant_goal="Compare same task.", project_id="compare-regression"))
    jiejing_result = JiejingAgentAdapter().execute(JiejingTask(tasks[2]))
    hermes_result = json.loads(json.dumps(jiejing_result))
    hermes_result["executor"] = "hermes-imported-test"
    hermes_result["report"]["sections"] = {"category_overview": "partial only"}
    comparison = RuntimeComparisonScorer().compare(jiejing_result, hermes_result)
    if comparison.get("winner") != "jiejing":
        return fail("comparison should prefer the fuller Jiejing report in this fixture")
    if comparison.get("safe_to_replace_low_risk_task") is not True:
        return fail("full Jiejing result should be replace-ready against weaker fixture")
    hermes_result["audit"]["real_execution_allowed"] = True
    comparison = RuntimeComparisonScorer().compare(jiejing_result, hermes_result)
    if comparison.get("hermes", {}).get("forbidden_write_claims") != ["real_execution_allowed"]:
        return fail("comparison should catch forbidden execution claims")
    return 0


def validate_deepseek_hermes_credential_loader() -> int:
    previous_fallback = os.environ.get("JIEJING_ALLOW_HERMES_MODEL_FALLBACK")
    with tempfile.TemporaryDirectory() as temp_dir:
        auth_path = Path(temp_dir) / "auth.json"
        auth_path.write_text(
            json.dumps(
                {
                    "credential_pool": {
                        "deepseek": [
                            {
                                "priority": 0,
                                "access_token": "test-deepseek-key",
                                "last_status": "ok",
                                "base_url": "https://api.deepseek.com",
                                "source": "unit-test",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        try:
            os.environ.pop("JIEJING_ALLOW_HERMES_MODEL_FALLBACK", None)
            client = DeepSeekModelClient(hermes_auth_path=str(auth_path))
            if client.configured():
                return fail("DeepSeek client must not configure from Hermes auth JSON unless legacy fallback is explicit")
            os.environ["JIEJING_ALLOW_HERMES_MODEL_FALLBACK"] = "true"
            client = DeepSeekModelClient(hermes_auth_path=str(auth_path))
            if not client.configured():
                return fail("DeepSeek client should configure from Hermes auth JSON only with explicit legacy fallback")
            if client.api_key != "test-deepseek-key":
                return fail("DeepSeek client should read the selected credential into memory")
            if client.model != "deepseek-v4-pro":
                return fail("DeepSeek client default model should be deepseek-v4-pro")
            if "chat/completions" not in client.endpoint:
                return fail("DeepSeek client should use chat completions endpoint")
        finally:
            restore_env("JIEJING_ALLOW_HERMES_MODEL_FALLBACK", previous_fallback)
    return 0


def validate_default_model_prefers_deepseek_when_available() -> int:
    previous_provider = os.environ.get("JIEJING_MODEL_PROVIDER")
    previous_style = os.environ.get("JIEJING_MODEL_API_STYLE")
    previous_auth = os.environ.get("JIEJING_HERMES_AUTH_JSON")
    previous_fallback = os.environ.get("JIEJING_ALLOW_HERMES_MODEL_FALLBACK")
    previous_model_key = os.environ.get("JIEJING_MODEL_API_KEY")
    previous_deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    try:
        os.environ.pop("JIEJING_MODEL_PROVIDER", None)
        os.environ.pop("JIEJING_MODEL_API_STYLE", None)
        os.environ.pop("JIEJING_MODEL_API_KEY", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)
        os.environ.pop("JIEJING_ALLOW_HERMES_MODEL_FALLBACK", None)
        with tempfile.TemporaryDirectory() as temp_dir:
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "credential_pool": {
                            "deepseek": [
                                {
                                    "priority": 0,
                                    "access_token": "test-default-deepseek-key",
                                    "last_status": "ok",
                                    "base_url": "https://api.deepseek.com",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            os.environ["JIEJING_HERMES_AUTH_JSON"] = str(auth_path)
            client = model_client_from_env()
            if client.name == "deepseek-openai-compatible-model" and client.configured():
                return fail("default model client must ignore Hermes credentials unless legacy fallback is explicit")
            os.environ["JIEJING_ALLOW_HERMES_MODEL_FALLBACK"] = "true"
            client = model_client_from_env()
            if client.name != "deepseek-openai-compatible-model":
                return fail("default model client should prefer DeepSeek when explicit legacy Hermes credential fallback is enabled")
    finally:
        restore_env("JIEJING_MODEL_PROVIDER", previous_provider)
        restore_env("JIEJING_MODEL_API_STYLE", previous_style)
        restore_env("JIEJING_HERMES_AUTH_JSON", previous_auth)
        restore_env("JIEJING_ALLOW_HERMES_MODEL_FALLBACK", previous_fallback)
        restore_env("JIEJING_MODEL_API_KEY", previous_model_key)
        restore_env("DEEPSEEK_API_KEY", previous_deepseek_key)
    return 0


def sample_taxonomy() -> dict:
    return {
        "aspects": [
            {
                "localizedAspectName": "Brand",
                "aspectConstraint": {
                    "aspectRequired": True,
                    "aspectMode": "FREE_TEXT",
                    "aspectDataType": "STRING",
                    "itemToAspectCardinality": "SINGLE",
                    "aspectUsage": "RECOMMENDED",
                },
            },
            {
                "localizedAspectName": "Material",
                "aspectConstraint": {
                    "aspectRequired": True,
                    "aspectMode": "SELECTION_ONLY",
                    "aspectDataType": "STRING",
                    "itemToAspectCardinality": "SINGLE",
                    "aspectUsage": "RECOMMENDED",
                },
                "aspectValues": [{"localizedValue": "Nylon"}, {"localizedValue": "Polyester"}],
            },
        ]
    }


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    raise SystemExit(main())
