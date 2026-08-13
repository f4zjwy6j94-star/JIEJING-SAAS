"""Disabled-by-default live eBay read adapter contract.

This file defines how the production live adapter will be wired. It does not
perform HTTP calls in the current MVP. The contract is still concrete enough for
the SaaS backend to test routing, token boundaries, request construction,
standardization, cache handoff, and audit behavior before any real eBay read is
enabled.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .ebay_http_client import build_ebay_http_client_contract
from .ebay_read_normalizers import SUPPORTED_READ_RESOURCE_KEYS


EBAY_REST_ROOTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}


EBAY_APIZ_REST_ROOTS = {
    "production": "https://apiz.ebay.com",
    "sandbox": "https://apiz.sandbox.ebay.com",
}


EBAY_READ_ROUTES = [
    {
        "resource_key": "store_profile",
        "api_family": "sell.account_or_trading",
        "route_key": "seller_profile_and_privileges",
        "method": "GET",
        "path_templates": [
            "/sell/account/v1/privilege",
        ],
        "query_template": {},
        "required_scope_hints": ["sell.account.readonly"],
        "standardizer": "normalize_store_profile",
        "live_implemented": True,
    },
    {
        "resource_key": "account_business_policies",
        "api_family": "sell.account",
        "route_key": "fulfillment_payment_return_policies",
        "method": "GET",
        "path_templates": [
            "/sell/account/v1/fulfillment_policy",
            "/sell/account/v1/payment_policy",
            "/sell/account/v1/return_policy",
        ],
        "query_template": {"marketplace_id": "{marketplace}"},
        "required_scope_hints": ["sell.account.readonly"],
        "standardizer": "normalize_business_policies",
        "live_implemented": True,
    },
    {
        "resource_key": "inventory_and_offers",
        "api_family": "sell.inventory",
        "route_key": "inventory_items_offers_locations",
        "method": "GET",
        "path_templates": [
            "/sell/inventory/v1/inventory_item",
            "/sell/inventory/v1/offer",
            "/sell/inventory/v1/location",
        ],
        "query_template": {"limit": "200"},
        "required_scope_hints": ["sell.inventory.readonly"],
        "standardizer": "normalize_inventory_and_offers",
        "live_implemented": True,
    },
    {
        "resource_key": "orders_and_fulfillment",
        "api_family": "sell.fulfillment",
        "route_key": "orders_fulfillment_tracking",
        "method": "GET",
        "path_templates": [
            "/sell/fulfillment/v1/order",
        ],
        "query_template": {"filter": "orderfulfillmentstatus:{NOT_STARTED|IN_PROGRESS}", "limit": "100"},
        "required_scope_hints": ["sell.fulfillment.readonly"],
        "standardizer": "normalize_orders_and_fulfillment",
        "live_implemented": True,
    },
    {
        "resource_key": "finances",
        "api_family": "sell.finances",
        "api_root": "apiz",
        "route_key": "transactions_payouts_fees",
        "method": "GET",
        "path_templates": [
            "/sell/finances/v1/transaction",
        ],
        "query_template": {"limit": "200"},
        "required_scope_hints": ["sell.finances"],
        "standardizer": "normalize_finances",
        "live_implemented": True,
    },
    {
        "resource_key": "taxonomy_listing_metadata",
        "api_family": "commerce.taxonomy",
        "route_key": "category_tree_aspects_condition",
        "method": "GET",
        "path_templates": [
            "/commerce/taxonomy/v1/get_default_category_tree_id",
            "/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_category_suggestions",
            "/commerce/taxonomy/v1/category_tree/{category_tree_id}/get_item_aspects_for_category",
        ],
        "query_template": {"marketplace_id": "{marketplace}", "category_id": "{category_id_when_known}", "q": "{query_when_known}"},
        "required_scope_hints": ["commerce.identity.readonly_or_application_access"],
        "standardizer": "normalize_taxonomy_listing_metadata",
        "live_implemented": True,
    },
    {
        "resource_key": "marketing_readonly",
        "api_family": "sell.marketing",
        "route_key": "campaigns_ads_performance_readonly",
        "method": "GET",
        "path_templates": [
            "/sell/marketing/v1/ad_campaign",
        ],
        "query_template": {"limit": "100"},
        "required_scope_hints": ["sell.marketing.readonly"],
        "standardizer": "normalize_marketing_readonly",
        "live_implemented": True,
    },
]


def build_live_read_adapter_status(settings: SaaSSettings) -> dict[str, Any]:
    http_contract = build_ebay_http_client_contract(settings)
    blockers: list[str] = list(http_contract.get("blocked_by") or [])
    route_standardizers_registered = all(
        str(route.get("resource_key") or "") in SUPPORTED_READ_RESOURCE_KEYS
        for route in EBAY_READ_ROUTES
    )
    if not route_standardizers_registered:
        blockers.append("route_standardizers_not_implemented")
    enabled = settings.ebay_read_only_live_enabled and not blockers
    return {
        "adapter_version": "2026-05-15-ebay-live-read-adapter-contract",
        "enabled": enabled,
        "requested_live_enabled": settings.ebay_read_only_live_enabled,
        "status": "live_ready" if enabled else "disabled_or_blocked",
        "routes": EBAY_READ_ROUTES,
        "route_count": len(EBAY_READ_ROUTES),
        "route_standardizers_registered": route_standardizers_registered,
        "standardizer_count": len(SUPPORTED_READ_RESOURCE_KEYS),
        "blocked_by": blockers,
        "guardrails": {
            "backend_only": True,
            "frontend_gets_access_token": False,
            "runtime_gets_access_token": False,
            "raw_ebay_response_stored": False,
            "writes_supported": False,
            "confirmation_required_for_any_future_write": True,
        },
        "http_client": {
            "live_implemented": http_contract.get("live_implemented"),
            "status": http_contract.get("status"),
        },
        "secret_exposed": False,
    }


class EbayLiveReadPlanBuilder:
    """Build a backend-only execution plan for future live read jobs.

    This class intentionally does not read secrets or call eBay. It gives the
    SaaS backend a production-shaped plan that can be audited and tested now.
    """

    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings

    def build_execution_plan(
        self,
        *,
        company_id: str,
        store: dict[str, Any],
        user_id: str,
        requested_resources: list[str] | None,
        secret_refs: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        token_refresh_plan: dict[str, Any],
    ) -> dict[str, Any]:
        marketplace = str(store.get("marketplace") or "EBAY_US")
        selected_routes = self._select_routes(requested_resources)
        refresh_secret_ref = _find_ebay_refresh_ref(secret_refs)
        connection = _find_ebay_connection(connections)
        backend_bridge = token_refresh_plan.get("backend_legacy_bridge") if isinstance(token_refresh_plan.get("backend_legacy_bridge"), dict) else {}
        backend_source_available = bool(
            self.settings.ebay_env_access_token_allowed
            or token_refresh_plan.get("backend_access_token_available")
            or backend_bridge.get("can_resolve_access_token")
        )
        blocked_by = self._blockers(
            store=store,
            selected_routes=selected_routes,
            refresh_secret_ref=refresh_secret_ref,
            connection=connection,
            token_refresh_plan=token_refresh_plan,
        )
        status = "ready_to_queue_live_read_job" if not blocked_by else "blocked_contract_only"
        route_requests = [
            self._route_request_contract(
                route=route,
                store=store,
                marketplace=marketplace,
                index=index + 1,
                status=status,
            )
            for index, route in enumerate(selected_routes)
        ]
        return {
            "plan_version": "2026-05-15-ebay-live-read-execution-plan",
            "platform": "ebay",
            "status": status,
            "company_id": company_id,
            "store_id": store.get("store_id"),
            "store_name": store.get("store_name"),
            "marketplace": marketplace,
            "user_id": user_id,
            "environment": self.settings.ebay_oauth_environment,
            "base_url": EBAY_REST_ROOTS.get(self.settings.ebay_oauth_environment, EBAY_REST_ROOTS["production"]),
            "resources_requested": [route["resource_key"] for route in selected_routes],
            "route_request_count": len(route_requests),
            "route_requests": route_requests,
            "backend_steps": self._backend_steps(
                status=status,
                route_requests=route_requests,
                token_refresh_plan=token_refresh_plan,
                has_refresh_secret_ref=bool(refresh_secret_ref) or backend_source_available,
                has_connection=bool(connection) or backend_source_available,
            ),
            "token_boundary": {
                "refresh_secret_ref_found": bool(refresh_secret_ref),
                "refresh_secret_ref_id": refresh_secret_ref.get("secret_ref") if refresh_secret_ref else None,
                "connection_found": bool(connection),
                "connection_id": connection.get("connection_id") if connection else None,
                "backend_source_available": backend_source_available,
                "token_refresh_status": token_refresh_plan.get("status"),
                "token_source": token_refresh_plan.get("token_source"),
                "backend_legacy_bridge": token_refresh_plan.get("backend_legacy_bridge") if isinstance(token_refresh_plan.get("backend_legacy_bridge"), dict) else {},
                "refresh_token_read_from_vault": False,
                "short_lived_access_token_cache": "backend_memory_or_redis_cache_only",
                "frontend_gets_access_token": False,
                "runtime_gets_access_token": False,
                "database_stores_access_token": False,
            },
            "data_packet_handoff": {
                "raw_ebay_response_stored": False,
                "sanitized_packet_required": True,
                "packet_label": "official_api_when_live_else_sample_or_manual",
                "runtime_gets_sanitized_packet_only": True,
                "missing_live_data_must_be_marked_pending": True,
            },
            "cache_policy": {
                "access_token_ttl_seconds": 3600,
                "read_packet_ttl_seconds": 900,
                "cache_key_shape": "company_id:store_id:platform:resource_key:marketplace",
                "cache_raw_pii": False,
                "invalidate_on_oauth_revoke": True,
            },
            "audit_policy": {
                "audit_required": True,
                "audit_events": [
                    "ebay.read_only.live_plan",
                    "vault.secret.resolve",
                    "oauth.access_token.refresh",
                    "ebay.read_only.http_request",
                    "ebay.read_only.standardized_packet",
                ],
                "record_token_value": False,
                "record_request_resource_keys": True,
                "record_http_status_only": True,
            },
            "blocked_by": blocked_by,
            "live_read_performed": False,
            "real_platform_writes_enabled": False,
            "writes_supported": False,
            "secret_exposed": False,
            "next_step": "implement_backend_token_resolver_http_client_and_standardizers" if blocked_by else "enqueue_backend_read_job",
        }

    def _select_routes(self, requested_resources: list[str] | None) -> list[dict[str, Any]]:
        if not requested_resources:
            return [dict(route) for route in EBAY_READ_ROUTES]
        requested = {str(item).strip().lower() for item in requested_resources if str(item).strip()}
        selected = [dict(route) for route in EBAY_READ_ROUTES if str(route.get("resource_key") or "").lower() in requested]
        return selected or [dict(route) for route in EBAY_READ_ROUTES]

    def _blockers(
        self,
        *,
        store: dict[str, Any],
        selected_routes: list[dict[str, Any]],
        refresh_secret_ref: dict[str, Any] | None,
        connection: dict[str, Any] | None,
        token_refresh_plan: dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        backend_legacy_bridge = token_refresh_plan.get("backend_legacy_bridge") if isinstance(token_refresh_plan.get("backend_legacy_bridge"), dict) else {}
        bridge_can_resolve = bool(backend_legacy_bridge.get("can_resolve_access_token"))
        backend_access_token_available = bool(token_refresh_plan.get("backend_access_token_available"))
        backend_source_available = bool(bridge_can_resolve or backend_access_token_available or self.settings.ebay_env_access_token_allowed)
        if str(store.get("platform") or "").lower() != "ebay":
            blockers.append("store_platform_not_ebay")
        if not refresh_secret_ref and not backend_source_available:
            blockers.append("ebay_refresh_token_secret_ref")
        if not connection and not backend_source_available:
            blockers.append("ebay_read_only_connection")
        if not backend_source_available and token_refresh_plan.get("status") != "refresh_ready":
            blockers.append("token_refresh_not_ready")
        http_contract = build_ebay_http_client_contract(self.settings)
        blockers.extend(
            item for item in http_contract.get("blocked_by", [])
            if item not in blockers
        )
        blockers.extend(
            item
            for item in token_refresh_plan.get("blocked_by", [])
            if item not in blockers and not self.settings.ebay_env_access_token_allowed
        )
        if any(route.get("live_implemented") is not True for route in selected_routes):
            blockers.append("route_live_implementation_pending")
        if not all(str(route.get("resource_key") or "") in SUPPORTED_READ_RESOURCE_KEYS for route in selected_routes):
            blockers.append("route_standardizers_not_implemented")
        return blockers

    def _route_request_contract(
        self,
        *,
        route: dict[str, Any],
        store: dict[str, Any],
        marketplace: str,
        index: int,
        status: str,
    ) -> dict[str, Any]:
        route_status = "ready_to_queue_when_live" if status == "ready_to_queue_live_read_job" else "blocked_until_adapter_live"
        return {
            "request_order": index,
            "request_key": f"{index:02d}_{route.get('resource_key')}",
            "resource_key": route.get("resource_key"),
            "api_family": route.get("api_family"),
            "api_root": route.get("api_root") or "api",
            "route_key": route.get("route_key"),
            "method": route.get("method"),
            "base_url_kind": self.settings.ebay_oauth_environment,
            "base_url": _route_base_url(route=route, environment=self.settings.ebay_oauth_environment),
            "path_templates": route.get("path_templates") or [],
            "query_template": _fill_query_template(route.get("query_template") or {}, marketplace=marketplace),
            "required_headers": [
                {"name": "Authorization", "value": "Bearer <short_lived_access_token_from_backend_cache>", "redacted": True},
                {"name": "Accept", "value": "application/json", "redacted": False},
                {"name": "Content-Type", "value": "application/json", "redacted": False},
                {"name": "X-EBAY-C-MARKETPLACE-ID", "value": marketplace, "redacted": False},
            ],
            "required_scope_hints": route.get("required_scope_hints") or [],
            "token_source": "backend_short_lived_access_token_cache",
            "standardizer": route.get("standardizer"),
            "response_policy": {
                "store_raw_response": False,
                "redact_pii": True,
                "redact_tokens": True,
                "normalize_to_data_packet_section": True,
                "mark_missing_fields_pending": True,
            },
            "store_id": store.get("store_id"),
            "status": route_status,
            "live_implemented": bool(route.get("live_implemented")),
        }

    def _backend_steps(
        self,
        *,
        status: str,
        route_requests: list[dict[str, Any]],
        token_refresh_plan: dict[str, Any],
        has_refresh_secret_ref: bool,
        has_connection: bool,
    ) -> list[dict[str, Any]]:
        route_status = "planned" if status == "ready_to_queue_live_read_job" else "blocked"
        steps = [
            {
                "step_order": 1,
                "key": "check_tenant_store_scope",
                "label": "Check user/company/store permission before reading eBay data",
                "status": "planned",
                "backend_only": True,
            },
            {
                "step_order": 2,
                "key": "verify_readonly_connection",
                "label": "Verify seller completed read-only OAuth authorization",
                "status": "planned" if has_connection else "blocked",
                "backend_only": True,
            },
            {
                "step_order": 3,
                "key": "resolve_refresh_secret_ref",
                "label": "Resolve eBay refresh token from Vault/KMS by secret_ref",
                "status": "planned" if has_refresh_secret_ref else "blocked",
                "backend_only": True,
                "returns_secret": False,
            },
            {
                "step_order": 4,
                "key": "refresh_access_token",
                "label": "Mint short-lived eBay access token for this task scope",
                "status": "planned" if token_refresh_plan.get("status") == "refresh_ready" else "blocked",
                "backend_only": True,
                "returns_token_to_frontend": False,
                "returns_token_to_runtime": False,
            },
            {
                "step_order": 5,
                "key": "cache_access_token",
                "label": "Cache short-lived access token only in backend runtime cache",
                "status": route_status,
                "backend_only": True,
                "stores_token_in_database": False,
            },
        ]
        next_order = 6
        for request in route_requests:
            steps.append(
                {
                    "step_order": next_order,
                    "key": f"read_{request.get('resource_key')}",
                    "label": f"Read and standardize {request.get('resource_key')}",
                    "resource_key": request.get("resource_key"),
                    "status": request.get("status"),
                    "backend_only": True,
                    "standardizer": request.get("standardizer"),
                    "stores_raw_response": False,
                }
            )
            next_order += 1
        steps.extend(
            [
                {
                    "step_order": next_order,
                    "key": "build_sanitized_data_packet",
                    "label": "Build sanitized official data packet for Runtime",
                    "status": route_status,
                    "backend_only": True,
                    "runtime_gets_raw_response": False,
                },
                {
                    "step_order": next_order + 1,
                    "key": "persist_packet_and_audit",
                    "label": "Persist sanitized packet and audit source coverage",
                    "status": route_status,
                    "backend_only": True,
                },
                {
                    "step_order": next_order + 2,
                    "key": "handoff_to_reports",
                    "label": "Hand official packet to market, listing, customer, finance and confirmation tasks",
                    "status": route_status,
                    "backend_only": False,
                },
            ]
        )
        return steps


def _find_ebay_refresh_ref(secret_refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in secret_refs:
        if str(item.get("provider") or "").lower() != "ebay":
            continue
        if str(item.get("purpose") or "").lower() == "ebay_refresh_token":
            return item
    return None


def _find_ebay_connection(connections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in connections:
        if str(item.get("platform") or "").lower() != "ebay":
            continue
        if str(item.get("connection_type") or "").lower() != "oauth":
            continue
        status = str(item.get("status") or "").lower()
        if status in {"read_only_authorized", "draft_save_authorized", "publish_authorized", "read_write_authorized", "authorized", "connected"}:
            return item
    return None


def _fill_query_template(template: dict[str, Any], *, marketplace: str) -> dict[str, Any]:
    return {
        key: str(value).replace("{marketplace}", marketplace)
        for key, value in template.items()
    }


def _route_base_url(*, route: dict[str, Any], environment: str) -> str:
    if str(route.get("api_root") or "api") == "apiz":
        return EBAY_APIZ_REST_ROOTS.get(environment, EBAY_APIZ_REST_ROOTS["production"])
    return EBAY_REST_ROOTS.get(environment, EBAY_REST_ROOTS["production"])
