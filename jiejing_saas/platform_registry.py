"""Platform connector registry for Jiejing SaaS.

This module intentionally does not call any live platform. It defines the
contract the SaaS backend, Runtime, and UI can rely on before real adapters are
implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .platform_authorization_strategy import build_platform_authorization_strategy


COMMON_SECRET_BOUNDARY = {
    "frontend": "never_collect_or_store_raw_secrets",
    "backend": "accept_metadata_and_secret_refs_only_until_vault_is_enabled",
    "vault_required_for_live": True,
    "secret_exposed": False,
}


COMMON_HIGH_RISK_ACTIONS = [
    "oauth_scope_change",
    "publish_listing",
    "bulk_publish_listing",
    "revise_listing",
    "change_price",
    "change_inventory",
    "open_ad_campaign",
    "change_ad_budget",
    "refund",
    "partial_refund",
    "procurement_payment",
    "purchase_order",
    "address_write",
    "change_shipping_policy",
    "change_payment_policy",
    "change_return_policy",
    "sensitive_customer_reply",
]


@dataclass(frozen=True, slots=True)
class PlatformDefinition:
    key: str
    display_name: str
    region: str
    platform_role: str
    priority: str
    planned_adapter: str
    connection_modes: list[str]
    read_capabilities: list[str]
    write_capabilities: list[str] = field(default_factory=list)
    manual_fallbacks: list[str] = field(default_factory=list)
    high_risk_actions: list[str] = field(default_factory=lambda: list(COMMON_HIGH_RISK_ACTIONS))
    status: str = "reserved_no_live_adapter"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "region": self.region,
            "platform_role": self.platform_role,
            "priority": self.priority,
            "planned_adapter": self.planned_adapter,
            "connection_modes": self.connection_modes,
            "read_capabilities": self.read_capabilities,
            "write_capabilities": self.write_capabilities,
            "manual_fallbacks": self.manual_fallbacks,
            "high_risk_actions": self.high_risk_actions,
            "status": self.status,
            "note": self.note,
            "secret_boundary": COMMON_SECRET_BOUNDARY,
        }


PLATFORM_DEFINITIONS: dict[str, PlatformDefinition] = {
    "ebay": PlatformDefinition(
        key="ebay",
        display_name="eBay",
        region="global",
        platform_role="primary_sales_channel",
        priority="current_primary",
        planned_adapter="platform.ebay",
        status="oauth_skeleton_ready_read_only_first",
        connection_modes=["official_oauth", "manual_import"],
        read_capabilities=[
            "seller_profile_read",
            "listing_read",
            "order_read",
            "finance_read",
            "business_policy_read",
            "taxonomy_read",
        ],
        write_capabilities=[
            "internal_listing_draft_no_ebay_write",
            "save_ebay_listing_draft_after_confirmation",
            "publish_listing_after_confirmation",
            "revise_listing_after_confirmation",
            "tracking_sync_after_confirmation",
        ],
        manual_fallbacks=["csv_import", "screenshot_import", "policy_snapshot_import"],
        note="Jiejing's first production platform. Read-only OAuth comes first; all writes stay confirmation-gated.",
    ),
    "amazon": PlatformDefinition(
        key="amazon",
        display_name="Amazon",
        region="global",
        platform_role="future_sales_channel",
        priority="future_reserved",
        planned_adapter="platform.amazon_sp_api",
        connection_modes=["official_oauth", "seller_central_export"],
        read_capabilities=["catalog_reference", "seller_listing_read", "order_read", "fee_reference"],
        write_capabilities=["draft_listing_after_adapter_ready"],
        manual_fallbacks=["seller_central_export", "public_page_reference"],
        note="Reserved for Amazon SP-API style seller workflows after the eBay closed loop is stable.",
    ),
    "shopify": PlatformDefinition(
        key="shopify",
        display_name="Shopify",
        region="global",
        platform_role="future_storefront_channel",
        priority="future_reserved",
        planned_adapter="platform.shopify_admin",
        connection_modes=["official_oauth", "admin_api_token_ref", "csv_import"],
        read_capabilities=["product_read", "order_read", "customer_service_context"],
        write_capabilities=["product_draft_or_update_after_confirmation"],
        manual_fallbacks=["product_csv", "order_csv"],
        note="Reserved for independent-store product and order workflows.",
    ),
    "1688": PlatformDefinition(
        key="1688",
        display_name="1688",
        region="china",
        platform_role="sourcing_channel",
        priority="near_term_reserved",
        planned_adapter="sourcing.1688",
        connection_modes=["official_api", "link_import", "image_import", "sheet_import"],
        read_capabilities=["product_detail_read", "price_read", "sku_specs_read", "stock_read", "supplier_profile_read", "ship_from_read"],
        write_capabilities=["purchase_order_after_confirmation", "address_write_after_confirmation", "payment_after_confirmation"],
        manual_fallbacks=["product_link", "supplier_image", "quote_sheet", "merchant_entered_cost_weight_dimensions"],
        note="Used to match eBay opportunities to purchasable supply. Procurement, payment, and address writes require confirmation.",
    ),
    "taobao_tmall": PlatformDefinition(
        key="taobao_tmall",
        display_name="Taobao / Tmall",
        region="china",
        platform_role="sourcing_or_reference_channel",
        priority="reserved",
        planned_adapter="sourcing.taobao_tmall",
        connection_modes=["official_api_if_available", "link_import", "image_import", "sheet_import"],
        read_capabilities=["public_product_reference", "price_reference", "image_reference"],
        write_capabilities=[],
        manual_fallbacks=["product_link", "screenshot", "merchant_entered_cost"],
        note="Reserved as sourcing/reference input. Do not treat public pages as verified stock or cost.",
    ),
    "pinduoduo": PlatformDefinition(
        key="pinduoduo",
        display_name="Pinduoduo",
        region="china",
        platform_role="sourcing_or_reference_channel",
        priority="reserved",
        planned_adapter="sourcing.pinduoduo",
        connection_modes=["official_api_if_available", "link_import", "image_import", "sheet_import"],
        read_capabilities=["public_product_reference", "price_reference", "image_reference"],
        write_capabilities=[],
        manual_fallbacks=["product_link", "screenshot", "merchant_entered_cost"],
        note="Reserved as a domestic sourcing/reference channel after compliance review.",
    ),
    "alibaba": PlatformDefinition(
        key="alibaba",
        display_name="Alibaba.com",
        region="global",
        platform_role="b2b_sourcing_channel",
        priority="reserved",
        planned_adapter="sourcing.alibaba",
        connection_modes=["official_api_if_available", "link_import", "rfq_export", "sheet_import"],
        read_capabilities=["supplier_reference", "moq_reference", "quote_reference", "ship_from_reference"],
        write_capabilities=["rfq_or_procurement_after_confirmation"],
        manual_fallbacks=["supplier_link", "quote_sheet", "chat_summary"],
        note="Reserved for B2B sourcing and RFQ workflows.",
    ),
    "aliexpress": PlatformDefinition(
        key="aliexpress",
        display_name="AliExpress",
        region="global",
        platform_role="market_reference_or_sourcing_channel",
        priority="reserved",
        planned_adapter="sourcing.aliexpress",
        connection_modes=["official_api_if_available", "link_import", "public_reference"],
        read_capabilities=["public_product_reference", "price_reference", "shipping_reference"],
        write_capabilities=["procurement_after_confirmation"],
        manual_fallbacks=["product_link", "screenshot"],
        note="Reserved as a reference/sourcing input, not a replacement for eBay-first execution.",
    ),
}


def list_platform_definitions() -> list[dict[str, Any]]:
    return [PLATFORM_DEFINITIONS[key].to_dict() for key in sorted(PLATFORM_DEFINITIONS)]


def get_platform_definition(platform_key: str) -> dict[str, Any] | None:
    normalized = normalize_platform_key(platform_key)
    definition = PLATFORM_DEFINITIONS.get(normalized)
    return definition.to_dict() if definition else None


def normalize_platform_key(platform_key: str) -> str:
    return str(platform_key or "").strip().lower().replace("-", "_")


def build_platform_connection_plan(
    *,
    platform_key: str,
    store: dict[str, Any],
    requested_mode: str | None = None,
) -> dict[str, Any]:
    definition = get_platform_definition(platform_key)
    if not definition:
        return {
            "platform": normalize_platform_key(platform_key),
            "status": "unsupported_platform",
            "secret_exposed": False,
            "message": "Platform is not in the Jiejing connector registry yet.",
            "supported_platforms": sorted(PLATFORM_DEFINITIONS),
        }

    modes = definition["connection_modes"]
    mode = requested_mode if requested_mode in modes else modes[0]
    is_current_ebay = definition["key"] == "ebay"
    status = "use_dedicated_ebay_oauth_plan" if is_current_ebay and mode == "official_oauth" else definition["status"]
    return {
        "platform": definition["key"],
        "display_name": definition["display_name"],
        "store_id": store.get("store_id"),
        "store_platform": store.get("platform"),
        "status": status,
        "selected_connection_mode": mode,
        "available_connection_modes": modes,
        "planned_adapter": definition["planned_adapter"],
        "current_scope": "contract_reserved_no_live_call",
        "dedicated_endpoint": "/stores/{store_id}/ebay-oauth/read-only-plan" if is_current_ebay else None,
        "allowed_now": [
            "record_connection_metadata",
            "create_secret_ref_placeholder",
            "manual_import_links_images_or_sheets",
            "route_runtime_task_with_source_labels",
        ],
        "blocked_until_live_adapter": [
            "live_api_read",
            "live_api_write",
            "raw_secret_storage",
            "silent_scope_escalation",
        ],
        "requires_confirmation": definition["high_risk_actions"],
        "read_capabilities": definition["read_capabilities"],
        "write_capabilities": definition["write_capabilities"],
        "manual_fallbacks": definition["manual_fallbacks"],
        "secret_boundary": COMMON_SECRET_BOUNDARY,
        "next_steps": _connection_next_steps(definition),
        "secret_exposed": False,
    }


def registry_summary() -> dict[str, Any]:
    definitions = list_platform_definitions()
    return {
        "version": "2026-05-15-platform-registry",
        "current_primary": "ebay",
        "platform_count": len(definitions),
        "platforms": definitions,
        "authorization_strategy": build_platform_authorization_strategy(),
        "guardrails": {
            "public_product_focus": "eBay-first AI CEO operations workbench",
            "other_platforms": "reserved_as_future_sales_sourcing_or_reference_connectors",
            "no_live_calls": True,
            "no_raw_secret_storage": True,
            "all_writes_confirmation_gated": True,
            "secret_exposed": False,
        },
    }


def _connection_next_steps(definition: dict[str, Any]) -> list[dict[str, str]]:
    if definition["key"] == "ebay":
        return [
            {"key": "configure_oauth_app", "label": "Configure eBay App ID, RuName, Client Secret in backend/Vault."},
            {"key": "read_only_oauth", "label": "Start with read-only seller data and policy snapshots."},
            {"key": "write_adapter_later", "label": "Only add publish/revise/tracking writes behind confirmation center."},
        ]
    if definition["platform_role"] in {"sourcing_channel", "sourcing_or_reference_channel", "b2b_sourcing_channel"}:
        return [
            {"key": "manual_fallback_first", "label": "Support product links, images, quotes, and sheets before live API."},
            {"key": "source_record_contract", "label": "Normalize cost, stock, specs, ship-from, weight, dimensions, and supplier confidence."},
            {"key": "procurement_gate", "label": "Keep purchase, payment, and address writes confirmation-gated."},
        ]
    return [
        {"key": "read_scope_first", "label": "Start with read-only product, order, and policy data."},
        {"key": "draft_not_publish", "label": "Generate drafts and reports before allowing any live write adapter."},
        {"key": "confirm_writes", "label": "Route publishing, edits, refunds, and ads to confirmation center."},
    ]
