"""Backend-only eBay read-only HTTP client.

The client supports official eBay GET reads only. It never exposes access
tokens to the browser, Runtime, reports, database packets, or audit logs. In
local development it can use an environment access token for verification; in
staging/production the same boundary should be backed by Vault/KMS secret refs.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .config import SaaSSettings
from .hermes_ebay_bridge import inspect_hermes_ebay_bridge, resolve_hermes_ebay_access_token
from .ebay_oauth_token_store import EbayLocalOAuthTokenStore, build_local_oauth_token_store_status
from .ebay_token_refresh_adapter import EbayVaultTokenRefreshAdapter
from .vault_secret_resolver import build_vault_secret_resolver_status


HttpTransport = Callable[[urllib.request.Request, float], tuple[int, dict[str, str], bytes]]


def build_ebay_http_client_contract(settings: SaaSSettings) -> dict[str, Any]:
    live_implemented = True
    hermes_bridge = inspect_hermes_ebay_bridge(settings)
    local_token_store = build_local_oauth_token_store_status(settings)
    secret_resolver = build_vault_secret_resolver_status(settings)
    token_ready = (
        _direct_access_token_allowed(settings)
        or _refresh_credentials_configured(settings)
        or bool(hermes_bridge.get("can_resolve_access_token"))
        or EbayLocalOAuthTokenStore(settings).has_usable_token()
        or bool(secret_resolver.get("live_secret_resolution_available"))
    )
    blocked_by: list[str] = []
    if not settings.ebay_read_only_live_enabled:
        blocked_by.append("JIEJING_EBAY_READ_ONLY_LIVE")
    if not token_ready:
        blocked_by.append("JIEJING_EBAY_ACCESS_TOKEN_OR_REFRESH_TOKEN")
        blocked_by.extend(item for item in hermes_bridge.get("blocked_by", []) if item not in blocked_by)
    if settings.ebay_env_access_token_blocked:
        blocked_by.append("JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION")
    if settings.ebay_env_refresh_token_blocked:
        blocked_by.append("JIEJING_EBAY_ENV_REFRESH_TOKEN_DISABLED_IN_PRODUCTION")
    if settings.is_production_like and (not settings.vault_enabled or settings.vault_provider == "secret_ref_only"):
        blocked_by.append("Vault/KMS")
    return {
        "contract_version": "2026-05-15-ebay-readonly-http-client",
        "platform": "ebay",
        "contract_ready": True,
        "live_implemented": live_implemented,
        "status": "live_ready" if not blocked_by else "contract_only_blocked",
        "blocked_by": blocked_by,
        "supported_methods": ["GET"],
        "writes_supported": False,
        "token_sources": {
            "env_access_token_configured": _direct_access_token_configured(),
            "env_access_token_allowed": _direct_access_token_allowed(settings),
            "env_access_token_blocked": settings.ebay_env_access_token_blocked,
            "env_refresh_token_configured": bool(os.environ.get("JIEJING_EBAY_REFRESH_TOKEN") or os.environ.get("EBAY_REFRESH_TOKEN")),
            "env_refresh_token_allowed": settings.ebay_env_refresh_token_allowed,
            "env_refresh_token_blocked": settings.ebay_env_refresh_token_blocked,
            "client_secret_configured": settings.ebay_client_secret_configured,
            "backend_legacy_bridge": {
                "enabled": bool(hermes_bridge.get("bridge_enabled")),
                "status": hermes_bridge.get("status"),
                "can_resolve_access_token": bool(hermes_bridge.get("can_resolve_access_token")),
                "can_refresh_access_token": bool(hermes_bridge.get("can_refresh_access_token")),
                "credential_source": hermes_bridge.get("credential_source"),
                "policy_snapshot_present": bool(hermes_bridge.get("policy_snapshot_present")),
                "listing_rules_snapshot_present": bool(hermes_bridge.get("listing_rules_snapshot_present")),
                "secret_exposed": False,
            },
            "backend_local_oauth_store": {
                "enabled": bool(local_token_store.get("enabled")),
                "status": local_token_store.get("status"),
                "latest_secret_ref": EbayLocalOAuthTokenStore(settings).status().get("latest_secret_ref"),
                "secret_exposed": False,
            },
            "backend_secret_ref_resolver": {
                "status": secret_resolver.get("status"),
                "local_development_enabled": bool(secret_resolver.get("local_development_enabled")),
                "live_secret_resolution_available": bool(secret_resolver.get("live_secret_resolution_available")),
                "returns_raw_secret_to_frontend": False,
                "returns_raw_secret_to_runtime": False,
                "secret_exposed": False,
            },
            "production_requires_vault": True,
        },
        "request_rules": {
            "backend_only": True,
            "requires_task_scope": True,
            "requires_short_lived_access_token_cache": True,
            "requires_vault_resolution_first_in_production": True,
            "timeout_seconds": 20,
            "max_retries": 2,
            "retry_on": ["timeout", "429_with_backoff", "5xx"],
            "do_not_retry_on": ["401", "403", "invalid_scope", "invalid_grant"],
        },
        "response_rules": {
            "store_raw_response": False,
            "redact_tokens": True,
            "redact_buyer_pii": True,
            "standardize_before_persistence": True,
            "mark_source_gaps": True,
            "hand_runtime_sanitized_packet_only": True,
        },
        "audit_policy": {
            "audit_required": True,
            "record_url_path": True,
            "record_query_keys": True,
            "record_http_status": True,
            "record_response_size": True,
            "record_token_value": False,
            "record_raw_response": False,
        },
        "live_request_performed": False,
        "secret_exposed": False,
    }


def build_http_dry_run_from_live_plan(
    *,
    settings: SaaSSettings,
    live_read_plan: dict[str, Any],
) -> dict[str, Any]:
    contract = build_ebay_http_client_contract(settings)
    route_requests = live_read_plan.get("route_requests") if isinstance(live_read_plan.get("route_requests"), list) else []
    requests = []
    for route in route_requests:
        if not isinstance(route, dict):
            continue
        requests.append(_dry_run_request(route))
    return {
        "dry_run_version": "2026-05-15-ebay-http-dry-run",
        "platform": "ebay",
        "status": "dry_run_blocked_contract_only" if contract.get("blocked_by") else "dry_run_ready_for_live_client",
        "request_count": len(requests),
        "requests": requests,
        "client_contract": contract,
        "live_request_performed": False,
        "access_token_used": False,
        "access_token_returned_to_frontend": False,
        "raw_response_stored": False,
        "writes_supported": False,
        "secret_exposed": False,
    }


class EbayReadOnlyHttpClient:
    """Execute official eBay read-only GET requests behind the SaaS backend."""

    def __init__(self, settings: SaaSSettings, *, transport: HttpTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport or _urlopen_transport

    def execute_live_read(
        self,
        *,
        live_read_plan: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contract = build_ebay_http_client_contract(self.settings)
        if contract.get("blocked_by"):
            return {
                "status": "blocked",
                "platform": "ebay",
                "blocked_by": contract["blocked_by"],
                "live_read_performed": False,
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "raw_response_stored": False,
                "writes_supported": False,
                "secret_exposed": False,
            }

        token_boundary = live_read_plan.get("token_boundary") if isinstance(live_read_plan.get("token_boundary"), dict) else {}
        token_result = self._resolve_access_token(
            secret_ref_id=str(token_boundary.get("refresh_secret_ref_id") or ""),
            company_id=str(live_read_plan.get("company_id") or ""),
            store_id=str(live_read_plan.get("store_id") or ""),
        )
        if not token_result.get("ok"):
            return {
                "status": "blocked_token_resolution_failed",
                "platform": "ebay",
                "blocked_by": token_result.get("blocked_by") or ["access_token_unavailable"],
                "live_read_performed": False,
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "raw_response_stored": False,
                "writes_supported": False,
                "secret_exposed": False,
            }

        access_token = str(token_result["access_token"])
        base_url = str(live_read_plan.get("base_url") or "https://api.ebay.com").rstrip("/")
        marketplace = str(live_read_plan.get("marketplace") or "EBAY_US")
        context = dict(request_context or {})
        context.setdefault("marketplace_id", marketplace)
        context.setdefault("query", context.get("product") or context.get("q") or "eBay product")
        route_results: list[dict[str, Any]] = []
        resource_payloads: dict[str, dict[str, Any]] = {}
        live_count = 0

        for route in live_read_plan.get("route_requests", []):
            if not isinstance(route, dict):
                continue
            resource_key = str(route.get("resource_key") or "")
            route_base_url = str(route.get("base_url") or base_url).rstrip("/")
            path_summaries: list[dict[str, Any]] = []
            combined: dict[str, Any] = {}
            successful_path_count = 0
            for path_template in route.get("path_templates", []) or []:
                resolved_path = _resolve_path(str(path_template), context)
                if not resolved_path:
                    path_summaries.append(
                        {
                            "path_template": path_template,
                            "status": "skipped_missing_context",
                            "missing_context": _missing_placeholders(str(path_template), context),
                        }
                    )
                    continue
                query = _resolve_query(route.get("query_template") if isinstance(route.get("query_template"), dict) else {}, context)
                if resource_key == "inventory_and_offers" and resolved_path.endswith("/offer"):
                    sku = str(context.get("sku") or "").strip()
                    if not sku:
                        path_summaries.append(
                            {
                                "path": resolved_path,
                                "status": "skipped_missing_context",
                                "missing_context": ["sku"],
                            }
                        )
                        continue
                    query["sku"] = sku
                url = _build_url(route_base_url, resolved_path, query)
                response = self._get_json(url=url, marketplace=marketplace, access_token=access_token)
                live_count += 1
                path_summary = {
                    "path": resolved_path,
                    "query_keys": sorted(query.keys()),
                    "http_status": response.get("http_status"),
                    "response_size": response.get("response_size"),
                    "status": response.get("status"),
                    "error_type": response.get("error_type"),
                    "body_returned": False,
                }
                path_summaries.append(path_summary)
                if response.get("status") == "ok" and response.get("json") is not None:
                    combined.setdefault("marketplace_id", marketplace)
                    _fold_resource_payload(
                        resource_key=resource_key,
                        path=resolved_path,
                        payload=combined,
                        response=response["json"],
                        context=context,
                    )
                    successful_path_count += 1
            if _payload_has_meaningful_data(combined):
                resource_payloads[resource_key] = combined
            route_results.append(
                {
                    "resource_key": resource_key,
                    "request_key": route.get("request_key"),
                    "method": "GET",
                    "path_count": len(path_summaries),
                    "successful_path_count": successful_path_count,
                    "data_present": _payload_has_meaningful_data(combined),
                    "paths": path_summaries,
                    "live_request_performed": bool(path_summaries),
                    "raw_response_stored": False,
                    "access_token_returned": False,
                }
            )

        sanitized_payloads = {key: _redact_live_payload(value) for key, value in resource_payloads.items()}
        return {
            "status": "completed_live_read" if live_count else "completed_no_live_request",
            "platform": "ebay",
            "environment": self.settings.ebay_oauth_environment,
            "resource_count": len(sanitized_payloads),
            "request_count": live_count,
            "route_results": route_results,
            "sample_payload": sanitized_payloads,
            "token_source": token_result.get("source"),
            "access_token_used": live_count > 0,
            "access_token_returned_to_frontend": False,
            "access_token_returned_to_runtime": False,
            "raw_response_stored": False,
            "live_read_performed": live_count > 0,
            "real_platform_writes_enabled": False,
            "writes_supported": False,
            "secret_exposed": False,
        }

    def _resolve_access_token(self, *, secret_ref_id: str = "", company_id: str = "", store_id: str = "") -> dict[str, Any]:
        direct = os.environ.get("JIEJING_EBAY_ACCESS_TOKEN") or os.environ.get("EBAY_ACCESS_TOKEN")
        blocked_by: list[str] = []
        if direct and not self.settings.is_production_like:
            return {"ok": True, "source": "backend_env_access_token", "access_token": direct}
        if direct and self.settings.is_production_like:
            blocked_by.append("JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION")
        local_token = EbayLocalOAuthTokenStore(self.settings, transport=self.transport).resolve_access_token(secret_ref=secret_ref_id or None)
        if local_token.get("ok"):
            return local_token
        secret_ref_token = self._refresh_access_token_from_secret_ref(
            secret_ref_id=secret_ref_id,
            company_id=company_id,
            store_id=store_id,
        )
        if secret_ref_token.get("ok"):
            return secret_ref_token
        if secret_ref_id:
            blocked_by.extend(str(item) for item in secret_ref_token.get("blocked_by") or [] if item)
        bridge_token = resolve_hermes_ebay_access_token(self.settings)
        if bridge_token.get("ok"):
            return bridge_token
        if not _refresh_credentials_configured(self.settings):
            return {
                "ok": False,
                "blocked_by": _unique(blocked_by + list(bridge_token.get("blocked_by") or ["JIEJING_EBAY_ACCESS_TOKEN_OR_REFRESH_TOKEN"])),
            }
        if not self.settings.ebay_token_refresh_live_enabled:
            return {"ok": False, "blocked_by": _unique(blocked_by + ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"])}
        return self._refresh_access_token()

    def _refresh_access_token_from_secret_ref(self, *, secret_ref_id: str, company_id: str = "", store_id: str = "") -> dict[str, Any]:
        if not secret_ref_id:
            return {"ok": False, "blocked_by": ["ebay_refresh_token_secret_ref"]}
        if not self.settings.ebay_client_id:
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_CLIENT_ID"]}
        if not self.settings.ebay_client_secret_configured:
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_CLIENT_SECRET"]}
        if not self.settings.ebay_token_refresh_live_enabled:
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_TOKEN_REFRESH_LIVE"]}
        secret_ref = {
            "secret_ref": secret_ref_id,
            "company_id": company_id,
            "store_id": store_id,
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
        }
        adapter = EbayVaultTokenRefreshAdapter(self.settings, transport=self.transport)
        refreshed = adapter.refresh_access_token_from_secret_ref(
            secret_ref=secret_ref,
            company_id=company_id,
            store_id=store_id,
            task_scope="ebay_read_only_live_sync",
        )
        if not refreshed.get("ok"):
            return {"ok": False, "blocked_by": refreshed.get("blocked_by") or ["secret_ref_refresh_failed"]}
        return refreshed

    def _refresh_access_token(self, *, refresh_token: str | None = None, source: str = "backend_refresh_token") -> dict[str, Any]:
        client_id = self.settings.ebay_client_id
        client_secret = os.environ.get("JIEJING_EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CLIENT_SECRET") or ""
        if refresh_token is None and self.settings.ebay_env_refresh_token_blocked:
            return {"ok": False, "blocked_by": ["JIEJING_EBAY_ENV_REFRESH_TOKEN_DISABLED_IN_PRODUCTION"]}
        refresh_token = refresh_token if refresh_token is not None else (os.environ.get("JIEJING_EBAY_REFRESH_TOKEN") or os.environ.get("EBAY_REFRESH_TOKEN") or "")
        token_endpoint = (
            "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
            if self.settings.ebay_oauth_environment == "sandbox"
            else "https://api.ebay.com/identity/v1/oauth2/token"
        )
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode("utf-8")
        request = urllib.request.Request(
            token_endpoint,
            data=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            status, _headers, raw = self.transport(request, 20)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {"ok": False, "blocked_by": ["token_refresh_http_error"], "error_type": type(exc).__name__}
        access_token = data.get("access_token") if isinstance(data, dict) else None
        if status >= 400 or not access_token:
            return {"ok": False, "blocked_by": ["token_refresh_failed"], "http_status": status}
        return {
            "ok": True,
            "source": source,
            "access_token": access_token,
            "expires_in": data.get("expires_in"),
            "refreshed_at": int(time.time()),
        }

    def _get_json(self, *, url: str, marketplace: str, access_token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
            },
            method="GET",
        )
        try:
            status, headers, raw = self.transport(request, 20)
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return {
                "status": "ok" if status < 400 else "http_error",
                "http_status": status,
                "headers": _safe_headers(headers),
                "response_size": len(raw),
                "json": data if isinstance(data, dict) else {"items": data},
                "secret_exposed": False,
            }
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "http_error",
                "http_status": exc.code,
                "response_size": 0,
                "error_type": "HTTPError",
                "json": None,
                "secret_exposed": False,
            }
        except Exception as exc:  # pragma: no cover - live provider dependent
            return {
                "status": "transport_error",
                "http_status": None,
                "response_size": 0,
                "error_type": type(exc).__name__,
                "json": None,
                "secret_exposed": False,
            }


def _urlopen_transport(request: urllib.request.Request, timeout: float) -> tuple[int, dict[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key: value for key, value in response.headers.items()}
        return int(response.status), headers, response.read()


def _dry_run_request(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_key": route.get("request_key"),
        "resource_key": route.get("resource_key"),
        "api_root": route.get("api_root"),
        "base_url": route.get("base_url"),
        "method": route.get("method") or "GET",
        "path_templates": route.get("path_templates") or [],
        "query_template": route.get("query_template") or {},
        "headers": [
            {
                "name": header.get("name"),
                "redacted": True if str(header.get("name") or "").lower() == "authorization" else bool(header.get("redacted")),
                "value": "[REDACTED]" if str(header.get("name") or "").lower() == "authorization" else header.get("value"),
            }
            for header in route.get("required_headers", [])
            if isinstance(header, dict)
        ],
        "standardizer": route.get("standardizer"),
        "response_policy": route.get("response_policy") or {},
        "live_request_performed": False,
        "safe_for_real_platform_write": False,
    }


def _direct_access_token_configured() -> bool:
    return bool(os.environ.get("JIEJING_EBAY_ACCESS_TOKEN") or os.environ.get("EBAY_ACCESS_TOKEN"))


def _direct_access_token_allowed(settings: SaaSSettings) -> bool:
    return settings.ebay_env_access_token_allowed


def _refresh_credentials_configured(settings: SaaSSettings) -> bool:
    return bool(
        settings.ebay_client_id
        and settings.ebay_client_secret_configured
        and settings.ebay_env_refresh_token_allowed
    )


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _payload_has_meaningful_data(payload: dict[str, Any]) -> bool:
    return any(key != "marketplace_id" and value not in (None, "", [], {}) for key, value in payload.items())


def _build_url(base_url: str, path: str, query: dict[str, str]) -> str:
    query = {key: value for key, value in query.items() if value not in {"", "None", "{category_id_when_known}", "{query_when_known}"}}
    qs = urllib.parse.urlencode(query)
    return f"{base_url}{path}{'?' + qs if qs else ''}"


def _resolve_path(path: str, context: dict[str, Any]) -> str | None:
    placeholders = _missing_placeholders(path, context)
    if placeholders:
        return None
    resolved = path
    for key, value in context.items():
        resolved = resolved.replace("{" + key + "}", urllib.parse.quote(str(value), safe=""))
    return resolved


def _missing_placeholders(text: str, context: dict[str, Any]) -> list[str]:
    placeholders: list[str] = []
    for chunk in text.split("{")[1:]:
        name = chunk.split("}", 1)[0]
        if name and name not in context:
            placeholders.append(name)
    return placeholders


def _resolve_query(template: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in template.items():
        text = str(value)
        if text == "{marketplace}":
            out[key] = str(context.get("marketplace_id") or "EBAY_US")
        elif text == "{query_when_known}":
            query = context.get("query") or context.get("product")
            if query:
                out[key] = str(query)
        elif text == "{category_id_when_known}":
            category_id = context.get("category_id")
            if category_id:
                out[key] = str(category_id)
        else:
            out[key] = text
    return out


def _fold_resource_payload(
    *,
    resource_key: str,
    path: str,
    payload: dict[str, Any],
    response: dict[str, Any],
    context: dict[str, Any],
) -> None:
    if resource_key == "account_business_policies":
        if "fulfillment_policy" in path:
            first = _first_item(response, "fulfillmentPolicies")
            payload["fulfillment_policy_id"] = first.get("fulfillmentPolicyId") or first.get("id")
            payload["handling_time"] = first.get("handlingTime")
            payload["shipping_service"] = _first_shipping_service(first)
            payload["fulfillment_policy_count"] = len(response.get("fulfillmentPolicies", []) or [])
        elif "payment_policy" in path:
            first = _first_item(response, "paymentPolicies")
            payload["payment_policy_id"] = first.get("paymentPolicyId") or first.get("id")
            payload["payment_policy_count"] = len(response.get("paymentPolicies", []) or [])
        elif "return_policy" in path:
            first = _first_item(response, "returnPolicies")
            payload["return_policy_id"] = first.get("returnPolicyId") or first.get("id")
            payload["return_window"] = first.get("returnPeriod")
            payload["return_payer"] = first.get("returnShippingCostPayer")
            payload["return_policy_count"] = len(response.get("returnPolicies", []) or [])
    elif resource_key == "store_profile":
        payload["marketplace_id"] = context.get("marketplace_id")
        if path.endswith("/privilege"):
            payload["seller_account_status"] = (
                "registration_completed"
                if response.get("sellerRegistrationCompleted") is True
                else "registration_incomplete"
                if response.get("sellerRegistrationCompleted") is False
                else response.get("status")
            )
            selling_limit = response.get("sellingLimit") if isinstance(response.get("sellingLimit"), dict) else {}
            if selling_limit:
                payload["selling_limits"] = _redact_live_payload(selling_limit)
            else:
                payload["selling_limits"] = response.get("selling_limit") or response.get("limits")
            payload["policy_setup_status"] = response.get("sellerBusinessType") or response.get("sellingPolicyProfile")
        elif path.endswith("/kyc"):
            checks = _safe_kyc_checks(response)
            payload["kyc_check_status"] = "verification_required" if checks else "clear"
            payload["kyc_check_count"] = len(checks)
            payload["kyc_checks"] = checks
            if checks:
                payload["verification_status"] = "verification_required"
                if _kyc_mentions_payout_hold(checks):
                    payload["payout_status"] = "payout_hold"
    elif resource_key == "inventory_and_offers":
        if "inventory_item" in path:
            inventory_items = response.get("inventoryItems") if isinstance(response.get("inventoryItems"), list) else []
            first = _first_item(response, "inventoryItems")
            sku = first.get("sku")
            payload["sku"] = sku
            if sku:
                context["sku"] = sku
            availability = first.get("availability") if isinstance(first.get("availability"), dict) else {}
            ship_to = availability.get("shipToLocationAvailability") if isinstance(availability.get("shipToLocationAvailability"), dict) else {}
            payload["quantity"] = ship_to.get("quantity")
            product = first.get("product") if isinstance(first.get("product"), dict) else {}
            payload["title"] = product.get("title")
            payload["condition"] = first.get("condition")
            payload["inventory_items"] = _safe_inventory_items(inventory_items)
            payload["inventory_item_count"] = len(inventory_items)
        elif path.endswith("/offer"):
            offers = response.get("offers") if isinstance(response.get("offers"), list) else []
            first = _first_item(response, "offers")
            payload["offer_id"] = first.get("offerId")
            payload["listing_id"] = first.get("listingId")
            payload["item_id"] = first.get("listingId") or first.get("itemId")
            payload["marketplace_id"] = first.get("marketplaceId")
            payload["category_id"] = first.get("categoryId")
            payload["listing_status"] = first.get("status")
            payload["format"] = first.get("format")
            price = first.get("pricingSummary", {}).get("price") if isinstance(first.get("pricingSummary"), dict) else None
            payload["price"] = price
            payload["offers"] = _safe_offers(offers)
            payload["offer_count"] = len(offers)
        elif "location" in path:
            first = _first_item(response, "locations")
            payload["item_location"] = first.get("merchantLocationKey") or first.get("name")
            payload["location_count"] = len(response.get("locations", []) or [])
    elif resource_key == "orders_and_fulfillment":
        first = _first_item(response, "orders")
        payload["order_id"] = first.get("orderId")
        payload["order_status"] = first.get("orderPaymentStatus") or first.get("orderFulfillmentStatus")
        payload["fulfillment_status"] = first.get("orderFulfillmentStatus")
        payload["line_items"] = _safe_line_items(first.get("lineItems") if isinstance(first.get("lineItems"), list) else [])
        payload["order_count"] = len(response.get("orders", []) or [])
    elif resource_key == "finances":
        first = _first_item(response, "transactions")
        payload["transaction_id"] = first.get("transactionId")
        payload["transaction_date"] = first.get("transactionDate")
        payload["fee_type"] = first.get("transactionType")
        payload["order_id"] = first.get("orderId")
        amount = first.get("amount") if isinstance(first.get("amount"), dict) else {}
        payload["amount"] = amount.get("value") if amount else first.get("amount")
        payload["currency"] = amount.get("currency") if amount else first.get("currency")
        payload["net_amount"] = first.get("bookingEntry")
        payload["transaction_count"] = len(response.get("transactions", []) or [])
    elif resource_key == "taxonomy_listing_metadata":
        if "get_default_category_tree_id" in path:
            category_tree_id = response.get("categoryTreeId")
            if category_tree_id:
                context["category_tree_id"] = category_tree_id
                payload["category_tree_id"] = category_tree_id
        elif "get_category_suggestions" in path:
            first = _first_item(response, "categorySuggestions")
            category = first.get("category") if isinstance(first.get("category"), dict) else {}
            category_id = category.get("categoryId")
            if category_id:
                context["category_id"] = category_id
                payload["category_id"] = category_id
            payload["leaf_category"] = category.get("categoryName")
            payload["category_suggestion_count"] = len(response.get("categorySuggestions", []) or [])
        elif "get_item_aspects_for_category" in path:
            aspects = response.get("aspects") if isinstance(response.get("aspects"), list) else []
            payload["required_aspects"] = [
                aspect.get("localizedAspectName")
                for aspect in aspects
                if isinstance(aspect, dict)
                and aspect.get("aspectConstraint", {}).get("aspectRequired")
                and aspect.get("localizedAspectName")
            ]
            payload["recommended_aspects"] = [
                aspect.get("localizedAspectName")
                for aspect in aspects
                if isinstance(aspect, dict)
                and not aspect.get("aspectConstraint", {}).get("aspectRequired")
                and aspect.get("localizedAspectName")
            ][:20]
    elif resource_key == "marketing_readonly":
        first = _first_item(response, "campaigns")
        payload["campaign_id"] = first.get("campaignId")
        payload["campaign_status"] = first.get("campaignStatus") or first.get("status")
        payload["campaign_count"] = len(response.get("campaigns", []) or [])
    else:
        payload.update(_redact_live_payload(response))


def _first_item(response: dict[str, Any], key: str) -> dict[str, Any]:
    items = response.get(key)
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return {}


def _first_shipping_service(policy: dict[str, Any]) -> Any:
    options = policy.get("shippingOptions") if isinstance(policy.get("shippingOptions"), list) else []
    if not options:
        return None
    option = options[0] if isinstance(options[0], dict) else {}
    services = option.get("shippingServices") if isinstance(option.get("shippingServices"), list) else []
    service = services[0] if services and isinstance(services[0], dict) else {}
    return service.get("shippingServiceCode")


def _safe_line_items(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for item in line_items[:20]:
        if not isinstance(item, dict):
            continue
        safe.append(
            {
                "line_item_id": item.get("lineItemId"),
                "sku": item.get("sku"),
                "title": item.get("title"),
                "quantity": item.get("quantity"),
                "line_item_fulfillment_status": item.get("lineItemFulfillmentStatus"),
            }
        )
    return safe


def _safe_inventory_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        availability = item.get("availability") if isinstance(item.get("availability"), dict) else {}
        ship_to = availability.get("shipToLocationAvailability") if isinstance(availability.get("shipToLocationAvailability"), dict) else {}
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        safe.append(
            {
                "sku": item.get("sku"),
                "title": product.get("title"),
                "condition": item.get("condition"),
                "quantity": ship_to.get("quantity"),
                "description": product.get("description"),
                "image_urls": product.get("imageUrls") if isinstance(product.get("imageUrls"), list) else [],
                "aspects": product.get("aspects") if isinstance(product.get("aspects"), dict) else {},
            }
        )
    return safe


def _safe_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe = []
    for offer in offers[:50]:
        if not isinstance(offer, dict):
            continue
        price = offer.get("pricingSummary", {}).get("price") if isinstance(offer.get("pricingSummary"), dict) else None
        safe.append(
            {
                "offer_id": offer.get("offerId"),
                "listing_id": offer.get("listingId"),
                "item_id": offer.get("listingId") or offer.get("itemId"),
                "sku": offer.get("sku"),
                "marketplace_id": offer.get("marketplaceId"),
                "category_id": offer.get("categoryId"),
                "listing_status": offer.get("status"),
                "format": offer.get("format"),
                "price": price,
            }
        )
    return safe


def _redact_live_payload(value: Any) -> Any:
    sensitive_markers = ("token", "secret", "authorization", "cookie", "buyer", "email", "phone", "address", "name", "street", "postal")
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lower = str(key).lower()
            out[key] = "[REDACTED]" if any(marker in lower for marker in sensitive_markers) else _redact_live_payload(item)
        return out
    if isinstance(value, list):
        return [_redact_live_payload(item) for item in value]
    return value


def _safe_kyc_checks(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep actionable eBay KYC evidence without persisting remedy URLs or PII."""

    raw_checks = response.get("kycChecks") if isinstance(response.get("kycChecks"), list) else []
    checks: list[dict[str, Any]] = []
    for raw in raw_checks[:10]:
        if not isinstance(raw, dict):
            continue
        check = {
            "data_required": str(raw.get("dataRequired") or "").strip()[:80],
            "alert": str(raw.get("alert") or "").strip()[:240],
            "detail": str(raw.get("detailMessage") or "").strip()[:480],
            "due_date": str(raw.get("dueDate") or "").strip()[:80],
            "remedy_available": bool(raw.get("remedyUrl")),
        }
        checks.append({key: value for key, value in check.items() if value not in ("", None)})
    return checks


def _kyc_mentions_payout_hold(checks: list[dict[str, Any]]) -> bool:
    text = " ".join(
        f"{check.get('alert', '')} {check.get('detail', '')}" for check in checks
    ).lower()
    return any(
        marker in text
        for marker in (
            "payout hold",
            "payouts are on hold",
            "funds on hold",
            "发放款项",
            "發放款項",
            "款项冻结",
            "款項凍結",
        )
    )


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in {"content-type", "x-ebay-c-request-id", "x-ebay-c-version", "x-ebay-c-marketplace-id"}
    }
