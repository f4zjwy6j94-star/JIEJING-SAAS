"""Smoke test for merchant BYOK model settings and merchant memory."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.model_provider_catalog import (  # noqa: E402
    build_model_provider_catalog,
    normalize_model_api_base_url,
    public_model_settings_from_secret_refs,
)
from jiejing_saas.model_value_gate import build_model_value_gate  # noqa: E402
from jiejing_saas.readiness import build_product_readiness  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="jiejing-merchant-byok-"))
    repo = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
    repo.initialize()
    user_company = repo.create_user_with_company(
        email="merchant@example.com",
        password="password123",
        company_name="Merchant Co",
    )
    user = user_company["user"]
    company = user_company["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "store_name": "Smoke eBay Store",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
        },
    )

    catalog = build_model_provider_catalog()
    providers = {item["provider_key"]: item for item in catalog["providers"]}
    assert providers["openai"]["key_url"] == "https://platform.openai.com/api-keys"
    assert providers["deepseek"]["merchant_brings_own_key"] is True
    assert providers["deepseek"]["default_base_url"] == "https://api.deepseek.com"
    assert providers["deepseek"]["default_model"] == "deepseek-v4-pro"
    assert providers["anthropic"]["supported_live_adapter"] is False
    assert catalog["jiejing_account_scoped_model_secret_ref"] is True
    assert catalog["jiejing_stores_only_secret_ref"] is False
    assert (
        normalize_model_api_base_url(provider_key="deepseek", base_url="https://api-docs.deepseek.com/zh-cn/")
        == providers["deepseek"]["default_base_url"]
    )
    assert normalize_model_api_base_url(provider_key="deepseek", base_url="https://api.deepseek.com/v1") == "https://api.deepseek.com"
    assert normalize_model_api_base_url(provider_key="deepseek", base_url="https://api.deepseek.com") == "https://api.deepseek.com"

    repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="model.openai",
        purpose="model_api_key",
        status="ready",
        metadata={
            "provider_key": "openai",
            "model": "gpt-4.1-mini",
            "base_url": "https://api.openai.com/v1",
            "merchant_brings_own_key": True,
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "reports_get_model_api_key": False,
        },
    )
    settings = public_model_settings_from_secret_refs(
        repo.list_secret_refs(company_id=company["company_id"], store_id=store["store_id"])
    )
    assert settings["mode"] == "merchant_byok_account_default"
    assert settings["configured"] is True
    assert settings["active_scope"] == "store"
    assert settings["merchant_model_follows_account"] is True
    assert settings["frontend_gets_raw_key_after_save"] is False

    packet = repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "source_label": "official_api",
            "status": "packet_cached_sanitized",
            "ready_for_runtime": True,
            "resource_count": 1,
            "present_resource_keys": ["inventory_and_offers"],
            "missing_resource_keys": [],
            "sections": [{"key": "inventory_and_offers", "data": {"sku": "SMOKE-SKU"}, "source_type": "official_api"}],
            "secret_exposed": False,
        },
    )

    task = repo.create_task(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="model_value_rehearsal",
        title="Smoke model value",
        input_data={},
    )
    repo.save_runtime_outputs(
        task=task,
        runtime_result={
            "run_id": "smoke-run",
            "results": [
                {
                    "task_type": "market.report",
                    "status": "completed",
                    "summary": "Market report ready",
                    "report": {
                        "model_assist": {"status": "applied", "model_mode": "live_http_model"},
                        "model_value_rehearsal": {"source_packet_id": packet["packet_id"]},
                    },
                },
                {
                    "task_type": "listing.package",
                    "status": "completed",
                    "summary": "Listing package ready",
                    "report": {
                        "model_assist": {"status": "applied", "model_mode": "live_http_model"},
                        "model_value_rehearsal": {"source_packet_id": packet["packet_id"]},
                    },
                },
            ],
            "confirmations": [
                {
                    "confirmation_id": "publish",
                    "action_type": "publish_listing",
                    "title": "Publish requires approval",
                    "default_action": "hold",
                    "reason": "Real eBay write remains disabled.",
                }
            ],
        },
    )
    memories = repo.list_merchant_memory(company_id=company["company_id"], store_id=store["store_id"], limit=20)
    assert len(memories) == 3
    assert {item["memory_type"] for item in memories} == {"ai_report", "confirmation_boundary"}

    settings_obj = SaaSSettings.from_env(
        db_path=root / "saas.sqlite",
        runtime_db_path=root / "runtime.sqlite",
        output_root=root,
        host="127.0.0.1",
        port=8788,
    )
    gate = build_model_value_gate(settings_obj, repo)
    assert gate["merchant_byok_model"]["configured"] is True
    assert gate["frontend_gets_model_api_key"] is False
    assert "model_provider_not_configured" not in gate["blockers"]
    assert gate["evidence"]["market_report_live_model_proven"] is True
    assert gate["evidence"]["listing_package_live_model_proven"] is True

    readiness = build_product_readiness(settings_obj, repo)
    model_item = {item["key"]: item for item in readiness["items"]}["model_provider"]
    readiness_model_status = readiness["provider_status"]["model"]
    assert readiness["product_evidence"]["model_secret_refs"] == 1
    assert model_item["status"] == "merchant_byok_secret_ref_ready"
    assert model_item["severity"] == "info"
    assert readiness_model_status["configured"] is True
    assert readiness_model_status["merchant_byok_configured"] is True
    assert readiness_model_status["merchant_byok_secret_ref_count"] == 1
    assert readiness_model_status["frontend_gets_model_api_key"] is False

    managed_store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "store_name": "Managed Vault Store",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
        },
    )
    repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=managed_store["store_id"],
        user_id=user["user_id"],
        provider="model.deepseek",
        purpose="model_api_key",
        status="managed_vault_stored",
        metadata={
            "provider_key": "deepseek",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
            "merchant_brings_own_key": True,
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "reports_get_model_api_key": False,
        },
    )
    managed_settings = public_model_settings_from_secret_refs(
        repo.list_secret_refs(company_id=company["company_id"], store_id=managed_store["store_id"])
    )
    assert managed_settings["configured"] is True
    assert managed_settings["active_provider"] == "deepseek"
    assert managed_settings["active_scope"] == "store"
    managed_gate = build_model_value_gate(settings_obj, repo)
    assert managed_gate["merchant_byok_model"]["configured"] is True
    assert managed_gate["merchant_byok_model"]["ready_secret_ref_count"] == 2
    assert managed_gate["merchant_byok_model"]["jiejing_account_scoped_model_secret_ref"] is True
    assert managed_gate["merchant_byok_model"]["jiejing_stores_only_secret_ref"] is False

    print("PASS jiejing_merchant_byok_model_and_memory")


if __name__ == "__main__":
    main()
