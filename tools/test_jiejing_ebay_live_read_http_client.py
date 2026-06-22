#!/usr/bin/env python3
"""Regression for Jiejing's backend-only eBay read-only HTTP client."""

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
from jiejing_saas.ebay_data_packet import build_ebay_read_only_data_packet  # noqa: E402
from jiejing_saas.ebay_http_client import EbayReadOnlyHttpClient, build_ebay_http_client_contract  # noqa: E402
from jiejing_saas.ebay_live_read_adapter import EbayLiveReadPlanBuilder, build_live_read_adapter_status  # noqa: E402
from jiejing_saas.ebay_oauth_token_store import EbayLocalOAuthTokenStore  # noqa: E402
from jiejing_saas.ebay_read_adapter import EbayReadOnlyAdapter  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    env_keys = (
        "JIEJING_EBAY_READ_ONLY_LIVE",
        "JIEJING_EBAY_ACCESS_TOKEN",
        "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
        "JIEJING_EBAY_CLIENT_ID",
        "JIEJING_EBAY_CLIENT_SECRET",
        "JIEJING_EBAY_REFRESH_TOKEN",
        "JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED",
        "JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH",
        "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
        "JIEJING_EBAY_RU_NAME",
        "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
        "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
        "JIEJING_SAAS_ENV",
        "JIEJING_VAULT_ENABLED",
        "JIEJING_VAULT_PROVIDER",
        "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
        "JIEJING_VAULT_ADDR",
        "JIEJING_VAULT_TOKEN",
        "JIEJING_VAULT_MOUNT",
        "JIEJING_VAULT_KEYSPACE",
        "JIEJING_VAULT_KV_VERSION",
        "JIEJING_ENABLE_HERMES_EBAY_BRIDGE",
        "JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP",
        "JIEJING_EBAY_AUTO_REFRESH",
    )
    previous = {key: os.environ.get(key) for key in env_keys}
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_EBAY_ACCESS_TOKEN"] = "FAKE-ACCESS-TOKEN-MUST-NOT-LEAK"
    try:
        settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "test-live-read.sqlite",
            runtime_db_path=ROOT / "output" / "test-live-read-runtime.sqlite",
            output_root=ROOT / "output" / "test-live-read",
            host="127.0.0.1",
            port=8799,
        )
        contract = build_ebay_http_client_contract(settings)
        if contract.get("status") != "live_ready" or contract.get("live_implemented") is not True:
            return fail("HTTP client should be live-ready when read-only flag and backend token are present")
        adapter_status = build_live_read_adapter_status(settings)
        if adapter_status.get("enabled") is not True:
            return fail("live read adapter should be enabled when HTTP client is live-ready")

        store = {"store_id": "store_live_test", "platform": "ebay", "store_name": "northvalesource", "marketplace": "EBAY_US"}
        read_adapter = EbayReadOnlyAdapter(settings)
        token_refresh_plan = {"status": "refresh_blocked", "blocked_by": ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"]}
        live_read_plan = EbayLiveReadPlanBuilder(settings).build_execution_plan(
            company_id="company_live_test",
            store=store,
            user_id="user_live_test",
            requested_resources=["account_business_policies", "inventory_and_offers", "taxonomy_listing_metadata"],
            secret_refs=[{"secret_ref": "secret_live_ebay", "provider": "ebay", "purpose": "ebay_refresh_token", "status": "external_vault_required"}],
            connections=[{"connection_id": "conn_live_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.account.readonly", "sell.inventory.readonly"]}],
            token_refresh_plan=token_refresh_plan,
        )
        if live_read_plan.get("status") != "ready_to_queue_live_read_job":
            return fail("direct backend access token should allow the read-only plan to queue")
        routed_root_plan = EbayLiveReadPlanBuilder(settings).build_execution_plan(
            company_id="company_live_test",
            store=store,
            user_id="user_live_test",
            requested_resources=["store_profile", "finances"],
            secret_refs=[{"secret_ref": "secret_live_ebay", "provider": "ebay", "purpose": "ebay_refresh_token", "status": "external_vault_required"}],
            connections=[{"connection_id": "conn_live_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.account.readonly", "sell.finances"]}],
            token_refresh_plan=token_refresh_plan,
        )
        routed_by_key = {
            str(route.get("resource_key")): route
            for route in routed_root_plan.get("route_requests", [])
            if isinstance(route, dict)
        }
        if routed_by_key.get("store_profile", {}).get("path_templates") != ["/sell/account/v1/privilege"]:
            return fail("store profile route should use the official Account API privilege endpoint")
        if routed_by_key.get("store_profile", {}).get("query_template") != {}:
            return fail("store profile privilege route should not send unsupported query params")
        if not str(routed_by_key.get("finances", {}).get("base_url") or "").startswith("https://apiz."):
            return fail("finances route should use the official apiz eBay API root")

        seen_authorized = {"value": False}

        def fake_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            if auth == "Bearer FAKE-ACCESS-TOKEN-MUST-NOT-LEAK":
                seen_authorized["value"] = True
            url = request.full_url
            if "fulfillment_policy" in url:
                body = {"fulfillmentPolicies": [{"fulfillmentPolicyId": "FULFILL-1", "handlingTime": {"value": 2}, "shippingOptions": [{"shippingServices": [{"shippingServiceCode": "SpeedPAK Economy"}]}]}]}
            elif "payment_policy" in url:
                body = {"paymentPolicies": [{"paymentPolicyId": "PAY-1"}]}
            elif "return_policy" in url:
                body = {"returnPolicies": [{"returnPolicyId": "RET-1", "returnPeriod": {"value": 14, "unit": "DAY"}, "returnShippingCostPayer": "BUYER"}]}
            elif "inventory_item" in url:
                body = {"inventoryItems": [{"sku": "SKU-1", "condition": "NEW", "product": {"title": "Travel Storage Bag"}, "availability": {"shipToLocationAvailability": {"quantity": 50}}}]}
            elif url.endswith("/sell/inventory/v1/offer?limit=200") or "/sell/inventory/v1/offer?" in url:
                body = {"offers": [{"offerId": "OFFER-1", "marketplaceId": "EBAY_US", "categoryId": "20625", "status": "PUBLISHED", "format": "FIXED_PRICE", "pricingSummary": {"price": {"value": "12.99", "currency": "USD"}}}]}
            elif "location" in url:
                body = {"locations": [{"merchantLocationKey": "CN-FJ-01", "name": "Fujian CN"}]}
            elif "get_default_category_tree_id" in url:
                body = {"categoryTreeId": "0"}
            elif "get_category_suggestions" in url:
                body = {"categorySuggestions": [{"category": {"categoryId": "20625", "categoryName": "Home Storage"}}]}
            elif "get_item_aspects_for_category" in url:
                body = {"aspects": [{"localizedAspectName": "Brand", "aspectConstraint": {"aspectRequired": True}}, {"localizedAspectName": "Material", "aspectConstraint": {"aspectRequired": True}}, {"localizedAspectName": "Color", "aspectConstraint": {"aspectRequired": False}}]}
            else:
                body = {"ok": True}
            return 200, {"content-type": "application/json", "x-ebay-c-request-id": "unit"}, json.dumps(body).encode("utf-8")

        result = EbayReadOnlyHttpClient(settings, transport=fake_transport).execute_live_read(
            live_read_plan=live_read_plan,
            request_context={"product": "travel storage bag"},
        )
        if result.get("status") != "completed_live_read" or result.get("live_read_performed") is not True:
            return fail("live client should complete a read-only HTTP run")
        if not seen_authorized["value"]:
            return fail("fake eBay transport should receive backend Authorization header")
        if result.get("access_token_returned_to_frontend") is not False or result.get("access_token_returned_to_runtime") is not False:
            return fail("live result must not return access token to frontend or Runtime")
        serialized = json.dumps(result, ensure_ascii=False)
        if "FAKE-ACCESS-TOKEN-MUST-NOT-LEAK" in serialized or "Authorization" in serialized:
            return fail("live result leaked token or authorization header")

        probe_plan = {
            "status": "read_only_live_completed",
            "platform": "ebay",
            "company_id": "company_live_test",
            "store_id": store["store_id"],
            "store_name": store["store_name"],
            "marketplace": store["marketplace"],
            "user_id": "user_live_test",
            "resources_requested": live_read_plan.get("resources_requested"),
            "resources": read_adapter._select_resources(live_read_plan.get("resources_requested")),
            "blocked_by": [],
            "request_count": result.get("request_count"),
            "route_results": result.get("route_results"),
            "live_read_performed": True,
            "access_token_used": True,
            "access_token_returned_to_frontend": False,
            "raw_ebay_response_stored": False,
        }
        packet = build_ebay_read_only_data_packet(
            company_id="company_live_test",
            store=store,
            user_id="user_live_test",
            probe_plan=probe_plan,
            source_mode="official_api",
            sample_payload=result.get("sample_payload"),
        )
        if packet.get("source_label") != "official_api":
            return fail("data packet should preserve official API source label")
        if packet.get("lineage", {}).get("raw_ebay_response_stored") is not False:
            return fail("data packet must not store raw eBay responses")
        if packet.get("ready_for_runtime") is not True:
            return fail("official data packet should be safe for Runtime handoff")
        if packet.get("freshness", {}).get("status") != "fresh_at_creation":
            return fail("official data packet should expose freshness metadata")
        if packet.get("route_health", {}).get("route_count", 0) < 1:
            return fail("official data packet should expose route-level health")
        if packet.get("retry_policy", {}).get("real_platform_writes_enabled") is not False:
            return fail("packet retry policy must not enable platform writes")

        os.environ.pop("JIEJING_EBAY_ACCESS_TOKEN", None)
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-CLIENT-SECRET-MUST-NOT-LEAK"
        os.environ["JIEJING_EBAY_REFRESH_TOKEN"] = "FAKE-REFRESH-TOKEN-MUST-NOT-LEAK"
        refresh_settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "test-live-read-refresh.sqlite",
            runtime_db_path=ROOT / "output" / "test-live-read-refresh-runtime.sqlite",
            output_root=ROOT / "output" / "test-live-read-refresh",
            host="127.0.0.1",
            port=8800,
        )
        refresh_contract = build_ebay_http_client_contract(refresh_settings)
        if refresh_contract.get("status") != "live_ready":
            return fail("refresh-token path should be live-ready when backend refresh credentials are present")
        refresh_seen = {"token_post": False, "read_get": False}

        def refresh_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            url = request.full_url
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            if request.get_method() == "POST" and "/identity/v1/oauth2/token" in url:
                refresh_seen["token_post"] = True
                if not str(auth).startswith("Basic "):
                    return 401, {"content-type": "application/json"}, b'{"error":"missing_basic"}'
                return (
                    200,
                    {"content-type": "application/json"},
                    b'{"access_token":"REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK","expires_in":7200}',
                )
            if auth == "Bearer REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK":
                refresh_seen["read_get"] = True
            body = {"inventoryItems": [{"sku": "SKU-REFRESH", "condition": "NEW", "product": {"title": "Refresh Path Test"}, "availability": {"shipToLocationAvailability": {"quantity": 12}}}]}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")

        refresh_plan = EbayLiveReadPlanBuilder(refresh_settings).build_execution_plan(
            company_id="company_refresh_test",
            store=store,
            user_id="user_refresh_test",
            requested_resources=["inventory_and_offers"],
            secret_refs=[{"secret_ref": "secret_refresh_ebay", "provider": "ebay", "purpose": "ebay_refresh_token", "status": "external_vault_required"}],
            connections=[{"connection_id": "conn_refresh_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.inventory.readonly"]}],
            token_refresh_plan={"status": "ready_to_refresh"},
        )
        refresh_result = EbayReadOnlyHttpClient(refresh_settings, transport=refresh_transport).execute_live_read(
            live_read_plan=refresh_plan,
            request_context={"product": "refresh path test"},
        )
        if refresh_result.get("status") != "completed_live_read" or refresh_result.get("token_source") != "backend_refresh_token":
            return fail("refresh-token path should refresh then complete a read-only HTTP run")
        if refresh_seen != {"token_post": True, "read_get": True}:
            return fail("refresh-token path should call token endpoint then eBay read endpoint")
        refresh_serialized = json.dumps(refresh_result, ensure_ascii=False)
        forbidden = (
            "FAKE-CLIENT-SECRET-MUST-NOT-LEAK",
            "FAKE-REFRESH-TOKEN-MUST-NOT-LEAK",
            "REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
            "Authorization",
        )
        if any(value in refresh_serialized for value in forbidden):
            return fail("refresh-token path leaked a secret or authorization header")

        os.environ.pop("JIEJING_EBAY_ACCESS_TOKEN", None)
        os.environ.pop("JIEJING_EBAY_REFRESH_TOKEN", None)
        os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "true"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-LOCAL-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-LOCAL-CLIENT-SECRET-MUST-NOT-LEAK"
        local_store_path = ROOT / "output" / "test-live-read-local-token-store.json"
        if local_store_path.exists():
            local_store_path.unlink()
        os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH"] = str(local_store_path)
        local_settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "test-live-read-local-store.sqlite",
            runtime_db_path=ROOT / "output" / "test-live-read-local-store-runtime.sqlite",
            output_root=ROOT / "output" / "test-live-read-local-store",
            host="127.0.0.1",
            port=8801,
        )
        local_secret_ref = "secret_local_oauth_store"
        local_token_store = EbayLocalOAuthTokenStore(local_settings)
        local_token_store.store_exchange_result(
            secret_ref=local_secret_ref,
            company_id="company_local_store_test",
            store_id=store["store_id"],
            user_id="user_local_store_test",
            token_response={
                "access_token": "LOCAL-EXPIRED-ACCESS-TOKEN-MUST-NOT-LEAK",
                "refresh_token": "LOCAL-REFRESH-TOKEN-MUST-NOT-LEAK",
                "expires_in": -120,
            },
            scopes=["https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"],
        )
        local_contract = build_ebay_http_client_contract(local_settings)
        if local_contract.get("status") != "live_ready":
            return fail("local Jiejing OAuth token store should make the HTTP client live-ready")
        if local_contract.get("token_sources", {}).get("backend_local_oauth_store", {}).get("enabled") is not True:
            return fail("HTTP contract should expose only sanitized local OAuth token store readiness")

        local_seen = {"token_post": False, "read_get": False}

        def local_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            url = request.full_url
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            if request.get_method() == "POST" and "/identity/v1/oauth2/token" in url:
                local_seen["token_post"] = True
                if not str(auth).startswith("Basic "):
                    return 401, {"content-type": "application/json"}, b'{"error":"missing_basic"}'
                return (
                    200,
                    {"content-type": "application/json"},
                    b'{"access_token":"LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK","expires_in":7200}',
                )
            if auth == "Bearer LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK":
                local_seen["read_get"] = True
            body = {"inventoryItems": [{"sku": "SKU-LOCAL", "condition": "NEW", "product": {"title": "Local Store Path Test"}, "availability": {"shipToLocationAvailability": {"quantity": 7}}}]}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")

        local_plan = EbayLiveReadPlanBuilder(local_settings).build_execution_plan(
            company_id="company_local_store_test",
            store=store,
            user_id="user_local_store_test",
            requested_resources=["inventory_and_offers"],
            secret_refs=[{"secret_ref": local_secret_ref, "provider": "ebay", "purpose": "ebay_refresh_token", "status": "local_oauth_token_store"}],
            connections=[{"connection_id": "conn_local_store_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.inventory.readonly"]}],
            token_refresh_plan={"status": "refresh_ready", "token_source": "backend_jiejing_local_oauth_store"},
        )
        if local_plan.get("status") != "ready_to_queue_live_read_job":
            return fail("local OAuth token store plan should be ready when secret_ref and connection exist")
        local_result = EbayReadOnlyHttpClient(local_settings, transport=local_transport).execute_live_read(
            live_read_plan=local_plan,
            request_context={"product": "local token store path test"},
        )
        if local_result.get("status") != "completed_live_read" or local_result.get("token_source") != "backend_jiejing_local_oauth_store_refresh":
            return fail("local OAuth token store should refresh an expired access token before eBay reads")
        if local_seen != {"token_post": True, "read_get": True}:
            return fail("local OAuth token store path should call token endpoint then eBay read endpoint")
        local_serialized = json.dumps(local_result, ensure_ascii=False)
        local_forbidden = (
            "FAKE-LOCAL-CLIENT-SECRET-MUST-NOT-LEAK",
            "LOCAL-REFRESH-TOKEN-MUST-NOT-LEAK",
            "LOCAL-EXPIRED-ACCESS-TOKEN-MUST-NOT-LEAK",
            "LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
            "Authorization",
        )
        if any(value in local_serialized for value in local_forbidden):
            return fail("local OAuth token store path leaked a secret or authorization header")
        if local_store_path.exists():
            local_store_path.unlink()

        os.environ.pop("JIEJING_EBAY_ACCESS_TOKEN", None)
        os.environ.pop("JIEJING_EBAY_REFRESH_TOKEN", None)
        os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-RESOLVER-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-RESOLVER-CLIENT-SECRET-MUST-NOT-LEAK"
        resolver_store_path = ROOT / "output" / "test-live-read-secret-resolver.json"
        if resolver_store_path.exists():
            resolver_store_path.unlink()
        os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(resolver_store_path)
        resolver_settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "test-live-read-secret-resolver.sqlite",
            runtime_db_path=ROOT / "output" / "test-live-read-secret-resolver-runtime.sqlite",
            output_root=ROOT / "output" / "test-live-read-secret-resolver",
            host="127.0.0.1",
            port=8802,
        )
        resolver_secret_ref = {
            "secret_ref": "secret_ref_resolver_refresh",
            "company_id": "company_secret_resolver_test",
            "store_id": store["store_id"],
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "external_vault_required",
        }
        VaultSecretResolver(resolver_settings).store_local_secret(
            secret_ref=resolver_secret_ref,
            secret_value="RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK",
            created_by="user_secret_resolver_test",
        )
        resolver_contract = build_ebay_http_client_contract(resolver_settings)
        if resolver_contract.get("status") != "live_ready":
            return fail("secret_ref resolver should make the HTTP client live-ready when enabled")
        resolver_seen = {"token_post": False, "read_get": False}

        def resolver_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            url = request.full_url
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            if request.get_method() == "POST" and "/identity/v1/oauth2/token" in url:
                resolver_seen["token_post"] = True
                if not str(auth).startswith("Basic "):
                    return 401, {"content-type": "application/json"}, b'{"error":"missing_basic"}'
                return (
                    200,
                    {"content-type": "application/json"},
                    b'{"access_token":"RESOLVER-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK","expires_in":7200}',
                )
            if auth == "Bearer RESOLVER-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK":
                resolver_seen["read_get"] = True
            body = {"inventoryItems": [{"sku": "SKU-RESOLVER", "condition": "NEW", "product": {"title": "Secret Resolver Path Test"}, "availability": {"shipToLocationAvailability": {"quantity": 5}}}]}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")

        resolver_plan = EbayLiveReadPlanBuilder(resolver_settings).build_execution_plan(
            company_id="company_secret_resolver_test",
            store=store,
            user_id="user_secret_resolver_test",
            requested_resources=["inventory_and_offers"],
            secret_refs=[resolver_secret_ref],
            connections=[{"connection_id": "conn_secret_resolver_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.inventory.readonly"], "secret_ref": "secret_ref_resolver_refresh"}],
            token_refresh_plan={"status": "refresh_ready", "token_source": "backend_jiejing_secret_ref_resolver"},
        )
        resolver_result = EbayReadOnlyHttpClient(resolver_settings, transport=resolver_transport).execute_live_read(
            live_read_plan=resolver_plan,
            request_context={"product": "secret resolver path test"},
        )
        if resolver_result.get("status") != "completed_live_read" or resolver_result.get("token_source") != "backend_vault_secret_ref_refresh":
            return fail("secret_ref resolver should resolve refresh token then complete a read-only HTTP run")
        if resolver_seen != {"token_post": True, "read_get": True}:
            return fail("secret_ref resolver path should call token endpoint then eBay read endpoint")
        resolver_serialized = json.dumps(resolver_result, ensure_ascii=False)
        resolver_forbidden = (
            "FAKE-RESOLVER-CLIENT-SECRET-MUST-NOT-LEAK",
            "RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK",
            "RESOLVER-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
            "Authorization",
        )
        if any(value in resolver_serialized for value in resolver_forbidden):
            return fail("secret_ref resolver path leaked a secret or authorization header")
        if resolver_store_path.exists():
            resolver_store_path.unlink()

        os.environ.pop("JIEJING_EBAY_ACCESS_TOKEN", None)
        os.environ.pop("JIEJING_EBAY_REFRESH_TOKEN", None)
        os.environ["JIEJING_SAAS_ENV"] = "staging"
        os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "false"
        os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "false"
        os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
        os.environ["JIEJING_EBAY_CLIENT_ID"] = "FAKE-MANAGED-CLIENT-ID"
        os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "FAKE-MANAGED-CLIENT-SECRET-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
        os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
        os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
        os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-LIVE-TOKEN-MUST-NOT-LEAK"
        os.environ["JIEJING_VAULT_MOUNT"] = "secret"
        os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-live"
        os.environ["JIEJING_VAULT_KV_VERSION"] = "v2"
        managed_settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "test-live-read-managed-vault.sqlite",
            runtime_db_path=ROOT / "output" / "test-live-read-managed-vault-runtime.sqlite",
            output_root=ROOT / "output" / "test-live-read-managed-vault",
            host="127.0.0.1",
            port=8803,
        )
        managed_contract = build_ebay_http_client_contract(managed_settings)
        if managed_contract.get("status") != "live_ready":
            return fail("managed Vault resolver should make the HTTP client live-ready")
        managed_secret_ref = {
            "secret_ref": "secret_managed_vault_refresh",
            "company_id": "company_managed_vault_test",
            "store_id": store["store_id"],
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "external_vault_required",
        }
        managed_seen = {"vault_get": False, "token_post": False, "read_get": False}

        def managed_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            url = request.full_url
            auth = request.headers.get("Authorization") or request.headers.get("authorization")
            vault_token = request.headers.get("X-vault-token") or request.headers.get("X-Vault-Token")
            if request.get_method() == "GET" and "vault.example.test" in url:
                managed_seen["vault_get"] = True
                if vault_token != "VAULT-LIVE-TOKEN-MUST-NOT-LEAK":
                    return 403, {"content-type": "application/json"}, b'{"errors":["forbidden"]}'
                if "/v1/secret/data/jiejing-live/company_managed_vault_test/store_live_test/secret_managed_vault_refresh" not in url:
                    return 404, {"content-type": "application/json"}, b'{"errors":["missing"]}'
                return (
                    200,
                    {"content-type": "application/json"},
                    b'{"data":{"data":{"refresh_token":"MANAGED-VAULT-REFRESH-TOKEN-MUST-NOT-LEAK"}}}',
                )
            if request.get_method() == "POST" and "/identity/v1/oauth2/token" in url:
                managed_seen["token_post"] = True
                if not str(auth).startswith("Basic "):
                    return 401, {"content-type": "application/json"}, b'{"error":"missing_basic"}'
                return (
                    200,
                    {"content-type": "application/json"},
                    b'{"access_token":"MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK","expires_in":7200}',
                )
            if auth == "Bearer MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK":
                managed_seen["read_get"] = True
            body = {"inventoryItems": [{"sku": "SKU-MANAGED", "condition": "NEW", "product": {"title": "Managed Vault Path Test"}, "availability": {"shipToLocationAvailability": {"quantity": 3}}}]}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")

        managed_plan = EbayLiveReadPlanBuilder(managed_settings).build_execution_plan(
            company_id="company_managed_vault_test",
            store=store,
            user_id="user_managed_vault_test",
            requested_resources=["inventory_and_offers"],
            secret_refs=[managed_secret_ref],
            connections=[{"connection_id": "conn_managed_vault_ebay", "platform": "ebay", "connection_type": "oauth", "status": "read_only_authorized", "scopes": ["sell.inventory.readonly"], "secret_ref": "secret_managed_vault_refresh"}],
            token_refresh_plan={"status": "refresh_ready", "token_source": "backend_jiejing_secret_ref_resolver"},
        )
        managed_result = EbayReadOnlyHttpClient(managed_settings, transport=managed_transport).execute_live_read(
            live_read_plan=managed_plan,
            request_context={"product": "managed vault path test"},
        )
        if managed_result.get("status") != "completed_live_read" or managed_result.get("token_source") != "backend_vault_secret_ref_refresh":
            return fail("managed Vault resolver should resolve refresh token then complete a read-only HTTP run")
        if managed_seen != {"vault_get": True, "token_post": True, "read_get": True}:
            return fail("managed Vault path should read Vault, refresh token, then call eBay")
        managed_serialized = json.dumps(managed_result, ensure_ascii=False)
        managed_forbidden = (
            "VAULT-LIVE-TOKEN-MUST-NOT-LEAK",
            "FAKE-MANAGED-CLIENT-SECRET-MUST-NOT-LEAK",
            "MANAGED-VAULT-REFRESH-TOKEN-MUST-NOT-LEAK",
            "MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK",
            "Authorization",
        )
        if any(value in managed_serialized for value in managed_forbidden):
            return fail("managed Vault eBay path leaked a secret or authorization header")
        print("PASS jiejing_ebay_live_read_http_client")
        return 0
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
