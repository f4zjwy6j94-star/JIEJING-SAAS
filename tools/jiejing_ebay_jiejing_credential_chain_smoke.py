#!/usr/bin/env python3
"""Smoke the Jiejing-owned eBay credential chain without Hermes.

This is a production-shape boundary smoke, not a live eBay smoke. It disables
the legacy Hermes bridge, injects a fake backend transport, and verifies that
Jiejing-owned credential sources can mint a short-lived access token, perform
read-only route execution, and build a Runtime-safe data packet without leaking
secret values.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_credential_preflight import build_ebay_credential_preflight  # noqa: E402
from jiejing_saas.ebay_data_packet import build_ebay_read_only_data_packet  # noqa: E402
from jiejing_saas.ebay_http_client import EbayReadOnlyHttpClient  # noqa: E402
from jiejing_saas.ebay_live_read_adapter import EbayLiveReadPlanBuilder  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner  # noqa: E402
from jiejing_saas.ebay_oauth_token_store import EbayLocalOAuthTokenStore  # noqa: E402
from jiejing_saas.ebay_read_adapter import EbayReadOnlyAdapter  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


OUT = ROOT / "output" / "jiejing-saas-backend" / "jiejing-owned-credential-chain-smoke"
REQUIRED_RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_EBAY_OAUTH_ENV",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_EBAY_ACCESS_TOKEN",
    "EBAY_ACCESS_TOKEN",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_CLIENT_ID",
    "EBAY_CLIENT_ID",
    "JIEJING_EBAY_CLIENT_SECRET",
    "EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_REFRESH_TOKEN",
    "EBAY_REFRESH_TOKEN",
    "JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED",
    "JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH",
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_EBAY_RU_NAME",
    "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
    "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
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
    "JIEJING_ALLOW_HERMES_ADAPTERS",
)
SECRET_SENTINELS = (
    "DIRECT-ACCESS-TOKEN-MUST-NOT-LEAK",
    "LOCAL-EXPIRED-ACCESS-TOKEN-MUST-NOT-LEAK",
    "LOCAL-REFRESH-TOKEN-MUST-NOT-LEAK",
    "LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
    "LOCAL-CLIENT-SECRET-MUST-NOT-LEAK",
    "RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK",
    "RESOLVER-ACCESS-TOKEN-MUST-NOT-LEAK",
    "RESOLVER-CLIENT-SECRET-MUST-NOT-LEAK",
    "VAULT-LIVE-TOKEN-MUST-NOT-LEAK",
    "MANAGED-VAULT-REFRESH-TOKEN-MUST-NOT-LEAK",
    "MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK",
    "MANAGED-CLIENT-SECRET-MUST-NOT-LEAK",
    "Authorization",
)


def run_smoke(*, write_output: bool = True, output_root: Path | None = None) -> dict[str, Any]:
    output_root = output_root or OUT
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    cleanup_paths: list[Path] = []
    try:
        cases = [
            _run_env_access_token_case(output_root=output_root),
            _run_local_oauth_store_case(output_root=output_root, cleanup_paths=cleanup_paths),
            _run_local_secret_ref_case(output_root=output_root, cleanup_paths=cleanup_paths),
            _run_managed_vault_secret_ref_case(output_root=output_root),
        ]
        result = {
            "smoke_version": "2026-05-16-jiejing-owned-ebay-credential-chain",
            "status": "pass" if all(case["status"] == "pass" for case in cases) else "fail",
            "platform": "ebay",
            "purpose": "prove Jiejing-owned credential sources can replace the local Hermes credential bridge for read-only sync",
            "hermes_bridge_enabled": False,
            "case_count": len(cases),
            "ready_case_count": sum(1 for case in cases if case["status"] == "pass"),
            "cases": cases,
            "required_resources": REQUIRED_RESOURCES,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        serialized = json.dumps(result, ensure_ascii=False)
        leaks = [value for value in SECRET_SENTINELS if value in serialized]
        result["secret_leak_check"] = {
            "status": "pass" if not leaks else "fail",
            "leaked_sentinels": leaks,
            "secret_exposed": bool(leaks),
        }
        if leaks:
            result["status"] = "fail"
            result["secret_exposed"] = True
        if write_output:
            output_root.mkdir(parents=True, exist_ok=True)
            latest = output_root / "latest.json"
            latest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result["output_path"] = str(latest)
        return result
    finally:
        for path in cleanup_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        _restore_env(previous)


def main() -> int:
    result = run_smoke(write_output=True)
    print(json.dumps(_public_summary(result), ensure_ascii=False, indent=2))
    if result.get("status") != "pass":
        return 1
    print("PASS jiejing_ebay_jiejing_credential_chain_smoke")
    return 0


def _run_env_access_token_case(*, output_root: Path) -> dict[str, Any]:
    _clear_env()
    _base_env(environment="local_dev")
    os.environ["JIEJING_EBAY_ACCESS_TOKEN"] = "DIRECT-ACCESS-TOKEN-MUST-NOT-LEAK"
    settings = _settings(output_root=output_root, case_key="env-access-token", port=8810)
    return _execute_case(
        settings=settings,
        case_key="env_access_token",
        expected_preflight_token_mode="backend_env_access_token",
        expected_live_token_source="backend_env_access_token",
        access_token_seen="DIRECT-ACCESS-TOKEN-MUST-NOT-LEAK",
        secret_refs=[],
        connections=[],
        transport=_fake_transport(
            access_token="DIRECT-ACCESS-TOKEN-MUST-NOT-LEAK",
            refreshed_access_token=None,
            refresh_secret_value=None,
        ),
    )


def _run_local_oauth_store_case(*, output_root: Path, cleanup_paths: list[Path]) -> dict[str, Any]:
    _clear_env()
    _base_env(environment="local_dev")
    os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "LOCAL-CLIENT-ID"
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "LOCAL-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_ENABLED"] = "true"
    local_store_path = output_root / "local-oauth-token-store.local.json"
    local_store_path.unlink(missing_ok=True)
    cleanup_paths.append(local_store_path)
    os.environ["JIEJING_EBAY_LOCAL_TOKEN_STORE_PATH"] = str(local_store_path)
    settings = _settings(output_root=output_root, case_key="local-oauth-store", port=8811)
    secret_ref = _secret_ref(case_key="local_oauth_store")
    EbayLocalOAuthTokenStore(settings).store_exchange_result(
        secret_ref=str(secret_ref["secret_ref"]),
        company_id=str(secret_ref["company_id"]),
        store_id=str(secret_ref["store_id"]),
        user_id="user_jiejing_credential_smoke",
        token_response={
            "access_token": "LOCAL-EXPIRED-ACCESS-TOKEN-MUST-NOT-LEAK",
            "refresh_token": "LOCAL-REFRESH-TOKEN-MUST-NOT-LEAK",
            "expires_in": -120,
        },
        scopes=["https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"],
    )
    return _execute_case(
        settings=settings,
        case_key="local_oauth_store",
        expected_preflight_token_mode="backend_jiejing_local_oauth_store",
        expected_live_token_source="backend_jiejing_local_oauth_store_refresh",
        access_token_seen="LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
        secret_refs=[secret_ref],
        connections=[_connection(case_key="local_oauth_store", secret_ref=str(secret_ref["secret_ref"]))],
        transport=_fake_transport(
            access_token="LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
            refreshed_access_token="LOCAL-REFRESHED-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_secret_value=None,
        ),
    )


def _run_local_secret_ref_case(*, output_root: Path, cleanup_paths: list[Path]) -> dict[str, Any]:
    _clear_env()
    _base_env(environment="local_dev")
    os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "RESOLVER-CLIENT-ID"
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "RESOLVER-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED"] = "true"
    resolver_path = output_root / "local-secret-ref-resolver.local.json"
    resolver_path.unlink(missing_ok=True)
    cleanup_paths.append(resolver_path)
    os.environ["JIEJING_VAULT_LOCAL_SECRET_STORE_PATH"] = str(resolver_path)
    settings = _settings(output_root=output_root, case_key="local-secret-ref", port=8812)
    secret_ref = _secret_ref(case_key="local_secret_ref")
    VaultSecretResolver(settings).store_local_secret(
        secret_ref=secret_ref,
        secret_value="RESOLVER-REFRESH-TOKEN-MUST-NOT-LEAK",
        created_by="user_jiejing_credential_smoke",
    )
    return _execute_case(
        settings=settings,
        case_key="local_secret_ref_resolver",
        expected_preflight_token_mode="backend_jiejing_secret_ref_resolver",
        expected_live_token_source="backend_vault_secret_ref_refresh",
        access_token_seen="RESOLVER-ACCESS-TOKEN-MUST-NOT-LEAK",
        secret_refs=[secret_ref],
        connections=[_connection(case_key="local_secret_ref", secret_ref=str(secret_ref["secret_ref"]))],
        transport=_fake_transport(
            access_token="RESOLVER-ACCESS-TOKEN-MUST-NOT-LEAK",
            refreshed_access_token="RESOLVER-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_secret_value=None,
        ),
    )


def _run_managed_vault_secret_ref_case(*, output_root: Path) -> dict[str, Any]:
    _clear_env()
    _base_env(environment="staging")
    os.environ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"] = "true"
    os.environ["JIEJING_EBAY_CLIENT_ID"] = "MANAGED-CLIENT-ID"
    os.environ["JIEJING_EBAY_CLIENT_SECRET"] = "MANAGED-CLIENT-SECRET-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_PROVIDER"] = "vault"
    os.environ["JIEJING_VAULT_LIVE_RESOLVE_ENABLED"] = "true"
    os.environ["JIEJING_VAULT_ADDR"] = "https://vault.example.test"
    os.environ["JIEJING_VAULT_TOKEN"] = "VAULT-LIVE-TOKEN-MUST-NOT-LEAK"
    os.environ["JIEJING_VAULT_MOUNT"] = "secret"
    os.environ["JIEJING_VAULT_KEYSPACE"] = "jiejing-owned-credential-smoke"
    os.environ["JIEJING_VAULT_KV_VERSION"] = "v2"
    settings = _settings(output_root=output_root, case_key="managed-vault-secret-ref", port=8813)
    secret_ref = _secret_ref(case_key="managed_vault_secret_ref")
    return _execute_case(
        settings=settings,
        case_key="managed_vault_secret_ref",
        expected_preflight_token_mode="backend_jiejing_secret_ref_resolver",
        expected_live_token_source="backend_vault_secret_ref_refresh",
        access_token_seen="MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK",
        secret_refs=[secret_ref],
        connections=[_connection(case_key="managed_vault_secret_ref", secret_ref=str(secret_ref["secret_ref"]))],
        transport=_fake_transport(
            access_token="MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK",
            refreshed_access_token="MANAGED-VAULT-ACCESS-TOKEN-MUST-NOT-LEAK",
            refresh_secret_value="MANAGED-VAULT-REFRESH-TOKEN-MUST-NOT-LEAK",
        ),
    )


def _execute_case(
    *,
    settings: SaaSSettings,
    case_key: str,
    expected_preflight_token_mode: str,
    expected_live_token_source: str,
    access_token_seen: str,
    secret_refs: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    transport: Any,
) -> dict[str, Any]:
    store = _store(case_key)
    token_plan = EbayOAuthPlanner(settings).token_refresh_plan(
        company_id="company_jiejing_credential_smoke",
        store_id=str(store["store_id"]),
        user_id="user_jiejing_credential_smoke",
        secret_refs=secret_refs,
        connections=connections,
        secret_store_status=SecretStoreBoundary(settings).status(),
    )
    preflight = build_ebay_credential_preflight(
        settings=settings,
        store=store,
        secret_refs=secret_refs,
        connections=connections,
        requested_resources=REQUIRED_RESOURCES,
        secret_transport=transport,
    )
    live_plan = EbayLiveReadPlanBuilder(settings).build_execution_plan(
        company_id="company_jiejing_credential_smoke",
        store=store,
        user_id="user_jiejing_credential_smoke",
        requested_resources=REQUIRED_RESOURCES,
        secret_refs=secret_refs,
        connections=connections,
        token_refresh_plan=token_plan,
    )
    live_result = EbayReadOnlyHttpClient(settings, transport=transport).execute_live_read(
        live_read_plan=live_plan,
        request_context={"product": "travel storage bag", "query": "travel storage bag"},
    )
    probe_plan = {
        "status": "read_only_live_completed",
        "platform": "ebay",
        "company_id": "company_jiejing_credential_smoke",
        "store_id": store["store_id"],
        "store_name": store["store_name"],
        "marketplace": store["marketplace"],
        "user_id": "user_jiejing_credential_smoke",
        "resources_requested": REQUIRED_RESOURCES,
        "resources": EbayReadOnlyAdapter(settings)._select_resources(REQUIRED_RESOURCES),
        "blocked_by": [],
        "live_read_performed": True,
        "access_token_used": True,
        "access_token_returned_to_frontend": False,
        "raw_ebay_response_stored": False,
    }
    packet = build_ebay_read_only_data_packet(
        company_id="company_jiejing_credential_smoke",
        store=store,
        user_id="user_jiejing_credential_smoke",
        probe_plan=probe_plan,
        source_mode="official_api",
        sample_payload=live_result.get("sample_payload") if isinstance(live_result.get("sample_payload"), dict) else {},
    )
    checks = [
        _case_check("hermes_bridge_disabled", os.environ.get("JIEJING_ENABLE_HERMES_EBAY_BRIDGE") == "false"),
        _case_check("preflight_ready", preflight.get("status") == "ready_for_official_read"),
        _case_check("preflight_token_mode", preflight.get("token_mode") == expected_preflight_token_mode),
        _case_check("token_plan_ready", token_plan.get("status") == "refresh_ready"),
        _case_check("live_plan_ready", live_plan.get("status") == "ready_to_queue_live_read_job"),
        _case_check("live_read_completed", live_result.get("status") == "completed_live_read"),
        _case_check("live_token_source", live_result.get("token_source") == expected_live_token_source),
        _case_check("all_required_resources_present", set(packet.get("present_resource_keys") or []) == set(REQUIRED_RESOURCES)),
        _case_check("packet_runtime_safe", packet.get("ready_for_runtime") is True and packet.get("lineage", {}).get("raw_ebay_response_stored") is False),
        _case_check("no_frontend_or_runtime_token", live_result.get("access_token_returned_to_frontend") is False and live_result.get("access_token_returned_to_runtime") is False),
        _case_check("no_writes", live_result.get("real_platform_writes_enabled") is False and packet.get("safe_for_real_platform_write") is False),
        _case_check("read_transport_used_token", transport.seen.get("read_get_count", 0) >= 1 and transport.seen.get("access_token_seen") == access_token_seen),
    ]
    case = {
        "case_key": case_key,
        "status": "pass" if all(item["pass"] for item in checks) else "fail",
        "environment": settings.environment,
        "preflight_status": preflight.get("status"),
        "preflight_token_mode": preflight.get("token_mode"),
        "token_plan_status": token_plan.get("status"),
        "token_plan_source": token_plan.get("token_source"),
        "live_plan_status": live_plan.get("status"),
        "live_result_status": live_result.get("status"),
        "live_token_source": live_result.get("token_source"),
        "route_result_count": len(live_result.get("route_results") or []),
        "request_count": live_result.get("request_count"),
        "present_resource_keys": packet.get("present_resource_keys") or [],
        "missing_resource_keys": packet.get("missing_resource_keys") or [],
        "packet_status": packet.get("status"),
        "transport_seen": _safe_transport_seen(transport.seen),
        "checks": checks,
        "frontend_gets_access_token": False,
        "runtime_gets_access_token": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    serialized = json.dumps(case, ensure_ascii=False)
    leaked = [value for value in SECRET_SENTINELS if value in serialized]
    if leaked:
        case["status"] = "fail"
        case["secret_exposed"] = True
        case["leaked_sentinels"] = leaked
    return case


def _fake_transport(
    *,
    access_token: str,
    refreshed_access_token: str | None,
    refresh_secret_value: str | None,
) -> Any:
    def transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        url = request.full_url
        method = request.get_method()
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if method == "GET" and "vault.example.test" in url:
            transport.seen["vault_get"] += 1
            body = {"data": {"data": {"refresh_token": refresh_secret_value or "MISSING"}}}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")
        if method == "POST" and "/identity/v1/oauth2/token" in url:
            transport.seen["token_post"] += 1
            if not str(auth).startswith("Basic "):
                return 401, {"content-type": "application/json"}, b'{"error":"missing_basic"}'
            body = {"access_token": refreshed_access_token or access_token, "expires_in": 7200}
            return 200, {"content-type": "application/json"}, json.dumps(body).encode("utf-8")
        if auth == f"Bearer {access_token}":
            transport.seen["access_token_seen"] = access_token
            transport.seen["read_get_count"] += 1
        return 200, {"content-type": "application/json", "x-ebay-c-request-id": "jiejing-smoke"}, json.dumps(_fake_ebay_body(url)).encode("utf-8")

    transport.seen = {"vault_get": 0, "token_post": 0, "read_get_count": 0, "access_token_seen": None}
    return transport


def _fake_ebay_body(url: str) -> dict[str, Any]:
    if "/sell/account/v1/privilege" in url:
        return {
            "sellerRegistrationCompleted": True,
            "sellerBusinessType": "BUSINESS",
            "sellingLimit": {"amount": {"value": "5000.00", "currency": "USD"}, "quantity": 1000},
        }
    if "fulfillment_policy" in url:
        return {
            "fulfillmentPolicies": [
                {
                    "fulfillmentPolicyId": "FULFILL-JJ-1",
                    "handlingTime": {"value": 2, "unit": "DAY"},
                    "shippingOptions": [{"shippingServices": [{"shippingServiceCode": "SpeedPAK Economy"}]}],
                }
            ]
        }
    if "payment_policy" in url:
        return {"paymentPolicies": [{"paymentPolicyId": "PAY-JJ-1"}]}
    if "return_policy" in url:
        return {
            "returnPolicies": [
                {"returnPolicyId": "RETURN-JJ-1", "returnPeriod": {"value": 30, "unit": "DAY"}, "returnShippingCostPayer": "BUYER"}
            ]
        }
    if "/sell/inventory/v1/inventory_item" in url:
        return {
            "inventoryItems": [
                {
                    "sku": "JJ-SMOKE-SKU-1",
                    "condition": "NEW",
                    "product": {"title": "Travel Storage Bag"},
                    "availability": {"shipToLocationAvailability": {"quantity": 42}},
                }
            ]
        }
    if "/sell/inventory/v1/offer" in url:
        return {
            "offers": [
                {
                    "offerId": "OFFER-JJ-1",
                    "marketplaceId": "EBAY_US",
                    "categoryId": "20625",
                    "status": "PUBLISHED",
                    "format": "FIXED_PRICE",
                    "pricingSummary": {"price": {"value": "12.99", "currency": "USD"}},
                }
            ]
        }
    if "/sell/inventory/v1/location" in url:
        return {"locations": [{"merchantLocationKey": "CN-FJ-01", "name": "Fujian CN"}]}
    if "/sell/fulfillment/v1/order" in url:
        return {
            "orders": [
                {
                    "orderId": "ORDER-JJ-1",
                    "orderPaymentStatus": "PAID",
                    "orderFulfillmentStatus": "NOT_STARTED",
                    "lineItems": [
                        {
                            "lineItemId": "LINE-JJ-1",
                            "sku": "JJ-SMOKE-SKU-1",
                            "title": "Travel Storage Bag",
                            "quantity": 1,
                            "lineItemFulfillmentStatus": "NOT_STARTED",
                        }
                    ],
                }
            ]
        }
    if "/sell/finances/v1/transaction" in url:
        return {
            "transactions": [
                {
                    "transactionId": "TXN-JJ-1",
                    "transactionDate": "2026-05-16T00:00:00.000Z",
                    "transactionType": "SALE",
                    "orderId": "ORDER-JJ-1",
                    "amount": {"value": "12.99", "currency": "USD"},
                    "bookingEntry": "CREDIT",
                }
            ]
        }
    if "get_default_category_tree_id" in url:
        return {"categoryTreeId": "0"}
    if "get_category_suggestions" in url:
        return {"categorySuggestions": [{"category": {"categoryId": "20625", "categoryName": "Home Storage"}}]}
    if "get_item_aspects_for_category" in url:
        return {
            "aspects": [
                {"localizedAspectName": "Brand", "aspectConstraint": {"aspectRequired": True}},
                {"localizedAspectName": "Material", "aspectConstraint": {"aspectRequired": True}},
                {"localizedAspectName": "Color", "aspectConstraint": {"aspectRequired": False}},
            ]
        }
    return {"ok": True}


def _settings(*, output_root: Path, case_key: str, port: int) -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=output_root / f"{case_key}.sqlite",
        runtime_db_path=output_root / f"{case_key}-runtime.sqlite",
        output_root=output_root / case_key,
        host="127.0.0.1",
        port=port,
    )


def _store(case_key: str) -> dict[str, Any]:
    return {
        "store_id": f"store_{case_key}",
        "platform": "ebay",
        "store_name": "jiejing-owned-credential-smoke",
        "marketplace": "EBAY_US",
    }


def _secret_ref(case_key: str) -> dict[str, Any]:
    return {
        "secret_ref": f"secret_{case_key}_ebay_refresh",
        "company_id": "company_jiejing_credential_smoke",
        "store_id": f"store_{case_key}",
        "provider": "ebay",
        "purpose": "ebay_refresh_token",
        "status": "read_only_authorized",
        "secret_exposed": False,
    }


def _connection(*, case_key: str, secret_ref: str) -> dict[str, Any]:
    return {
        "connection_id": f"conn_{case_key}_ebay_readonly",
        "platform": "ebay",
        "connection_type": "oauth",
        "status": "read_only_authorized",
        "scopes": [
            "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
        ],
        "secret_ref": secret_ref,
    }


def _base_env(*, environment: str) -> None:
    os.environ["JIEJING_SAAS_ENV"] = environment
    os.environ["JIEJING_EBAY_OAUTH_ENV"] = "production"
    os.environ["JIEJING_EBAY_READ_ONLY_LIVE"] = "true"
    os.environ["JIEJING_ENABLE_HERMES_EBAY_BRIDGE"] = "false"
    os.environ["JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP"] = "false"
    os.environ["JIEJING_EBAY_AUTO_REFRESH"] = "false"
    os.environ["JIEJING_ALLOW_HERMES_ADAPTERS"] = "false"


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _case_check(key: str, passed: bool) -> dict[str, Any]:
    return {"key": key, "pass": bool(passed)}


def _safe_transport_seen(seen: dict[str, Any]) -> dict[str, Any]:
    return {
        "vault_get": seen.get("vault_get"),
        "token_post": seen.get("token_post"),
        "read_get_count": seen.get("read_get_count"),
        "access_token_seen": bool(seen.get("access_token_seen")),
    }


def _public_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "case_count": result.get("case_count"),
        "ready_case_count": result.get("ready_case_count"),
        "cases": [
            {
                "case_key": item.get("case_key"),
                "status": item.get("status"),
                "preflight_token_mode": item.get("preflight_token_mode"),
                "live_token_source": item.get("live_token_source"),
                "request_count": item.get("request_count"),
                "missing_resource_keys": item.get("missing_resource_keys"),
            }
            for item in result.get("cases", [])
        ],
        "secret_leak_check": result.get("secret_leak_check"),
        "output_path": result.get("output_path"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
