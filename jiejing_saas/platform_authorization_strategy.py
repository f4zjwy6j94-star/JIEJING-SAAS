"""Platform authorization strategy for Jiejing SaaS.

This module explains how Jiejing avoids depending on every marketplace API
being approved on day one. It is intentionally read-only: no OAuth flow, token
refresh, provider call, write adapter, payment, or procurement action starts
from here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


STRATEGY_VERSION = "2026-07-01-platform-authorization-strategy-v1"


@dataclass(frozen=True, slots=True)
class PlatformAuthorizationLane:
    key: str
    label: str
    difficulty: str
    current_role: str
    official_api_path: str
    first_safe_mode: str
    fallback_modes: list[str]
    why_hard: list[str] = field(default_factory=list)
    jiejing_solution: list[str] = field(default_factory=list)
    never_do: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_platform_authorization_strategy() -> dict[str, Any]:
    lanes = _lanes()
    return {
        "strategy_version": STRATEGY_VERSION,
        "mode": "read_only_strategy_packet_no_oauth_no_platform_call",
        "product_positioning": "eBay-first AI CEO SaaS",
        "plain_language_summary": (
            "Jiejing does not collapse if a future marketplace API is slow to approve. "
            "The operating loop is owned by Jiejing; each marketplace is a connector with "
            "official API, read-only, manual-import, and confirmation-gated write lanes."
        ),
        "execution_order": [
            "prove_ebay_first_private_beta_loop",
            "support_manual_or_export_import_for_future_platforms",
            "add_read_only_api_lanes_before_write_lanes",
            "keep_draft_or_write_actions_behind_confirmation_center",
            "graduate_platforms_one_by_one_after_live_adapter_and_audit_evidence",
        ],
        "lanes": [lane.to_dict() for lane in lanes],
        "difficulty_order": ["ebay", "shopify", "etsy", "tiktok_shop", "amazon_sp_api"],
        "operating_rules": {
            "jiejing_task_protocol_owns_workflow": True,
            "platform_adapter_translates_fields": True,
            "manual_import_is_a_valid_beta_lane": True,
            "read_only_before_write": True,
            "writes_require_confirmation_center": True,
            "oauth_scope_change_requires_confirmation": True,
            "frontend_gets_raw_token": False,
            "runtime_gets_raw_token": False,
            "agent_gets_raw_token": False,
            "secret_exposed": False,
        },
        "blocked_actions": [
            "promise_all_platforms_live_before_approval",
            "silent_oauth_scope_escalation",
            "use_public_pages_as_verified_private_store_data",
            "perform_platform_write_without_confirmation",
            "store_or_echo_raw_access_or_refresh_tokens",
        ],
        "secret_exposed": False,
    }


def _lanes() -> list[PlatformAuthorizationLane]:
    return [
        PlatformAuthorizationLane(
            key="ebay",
            label="eBay",
            difficulty="medium_high_but_current_primary",
            current_role="primary_sales_channel",
            official_api_path="OAuth user authorization plus Sell APIs",
            first_safe_mode="read_only_oauth_and_sanitized_packets",
            fallback_modes=["manual_csv", "policy_snapshot", "listing_export", "screenshot_or_link_import"],
            why_hard=[
                "token_refresh_must_work_backend_only",
                "taxonomy_item_specifics_and_business_policies_are_strict",
                "account_health_and_listing_limits_can_block_publish",
            ],
            jiejing_solution=[
                "keep_ebay_first_until_private_beta_value_is_proven",
                "map_official_packets_to_listing_and_confirmation_workflows",
                "send_publish_revise_price_inventory_refund_ads_policy_to_confirmation_center",
            ],
            never_do=["repeat_old_frozen_account_oauth", "fake_publish_with_demo_assets"],
        ),
        PlatformAuthorizationLane(
            key="shopify",
            label="Shopify",
            difficulty="medium",
            current_role="future_storefront_channel",
            official_api_path="Shopify app authorization with Admin API scopes",
            first_safe_mode="product_order_read_or_csv_import",
            fallback_modes=["product_csv", "order_csv", "admin_export", "merchant_product_link"],
            why_hard=["scope_selection_and_app_review_must_match_real_use", "variant_inventory_shipping_profiles_differ_from_ebay"],
            jiejing_solution=[
                "reuse_ai_ceo_operating_loop",
                "translate_listing_package_to_shopify_product_fields",
                "allow_draft_update_only_after_confirmation",
            ],
            never_do=["treat_shopify_variants_as_ebay_item_specifics"],
        ),
        PlatformAuthorizationLane(
            key="etsy",
            label="Etsy",
            difficulty="medium_high",
            current_role="future_specialty_marketplace",
            official_api_path="API key plus OAuth scopes for shop/listing endpoints",
            first_safe_mode="shop_listing_read_or_export_import",
            fallback_modes=["listing_export", "shop_screenshot", "manual_order_or_listing_sheet"],
            why_hard=["app_approval_and_scopes_can_delay_access", "handmade_vintage_supply_claims_need_extra_review"],
            jiejing_solution=[
                "treat_etsy_as_a_platform_adapter_after_ebay_loop_is_stable",
                "keep_claim_and_material_reviews_explicit",
            ],
            never_do=["copy_etsy_listing_claims_into_ebay_without_source_review"],
        ),
        PlatformAuthorizationLane(
            key="tiktok_shop",
            label="TikTok Shop",
            difficulty="high_region_and_scope_dependent",
            current_role="future_sales_or_content_channel",
            official_api_path="TikTok Shop app authorization and approved scopes",
            first_safe_mode="manual_order_product_export_or_content_brief",
            fallback_modes=["shop_export", "campaign_or_content_screenshot", "product_link", "manual_sheet"],
            why_hard=["region_availability_varies", "scopes_and_partner_approval_can_be_limited", "content_and_shop_rules_are_tightly_coupled"],
            jiejing_solution=[
                "use_content_and_product_brief_lanes_before_live_write",
                "treat_shop_order_write_actions_as_confirmation_center_items",
            ],
            never_do=["assume_global_tiktok_shop_api_access"],
        ),
        PlatformAuthorizationLane(
            key="amazon_sp_api",
            label="Amazon SP-API",
            difficulty="very_high",
            current_role="future_reserved_not_p0",
            official_api_path="Amazon developer profile, roles, LWA authorization, SP-API scopes",
            first_safe_mode="seller_central_export_and_public_reference",
            fallback_modes=["seller_central_export", "business_report_csv", "inventory_csv", "public_asin_reference"],
            why_hard=[
                "developer_profile_and_roles_need_approval",
                "restricted_data_access_has_compliance_requirements",
                "orders_buyer_data_and_fulfillment_fields_are_sensitive",
                "write_actions_have_high_policy_risk",
            ],
            jiejing_solution=[
                "do_not_make_amazon_api_access_a_launch_blocker",
                "start_with_exports_and_reference_analysis",
                "graduate_to_read_only_sp_api_after_approval",
                "keep_listing_order_refund_ads_and_policy_changes_confirmation_gated",
            ],
            never_do=["promise_amazon_live_automation_before_approval", "handle_restricted_buyer_data_without_compliance_evidence"],
        ),
    ]
