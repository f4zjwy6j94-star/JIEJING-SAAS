"""Standard field contracts for eBay read-only packets."""

from __future__ import annotations

from typing import Any


RESOURCE_FIELD_CONTRACTS: dict[str, dict[str, Any]] = {
    "store_profile": {
        "required_fields": ["marketplace_id", "seller_account_status", "selling_limits"],
        "recommended_fields": ["store_name", "registered_country", "seller_level", "policy_setup_status"],
        "sensitive_fields": ["seller_username", "email", "phone", "address", "registration_name"],
        "used_by": ["ai_ceo_home", "ai_report", "connected_accounts"],
    },
    "account_business_policies": {
        "required_fields": ["fulfillment_policy_id", "payment_policy_id", "return_policy_id"],
        "recommended_fields": ["handling_time", "shipping_service", "return_window", "return_payer", "policy_marketplace"],
        "sensitive_fields": [],
        "used_by": ["product_listing", "confirmation_center", "connected_accounts"],
    },
    "inventory_and_offers": {
        "required_fields": ["sku", "title", "price", "quantity", "condition", "marketplace_id"],
        "recommended_fields": ["offer_id", "item_id", "category_id", "item_location", "listing_status", "format"],
        "sensitive_fields": [],
        "used_by": ["market_report", "product_listing", "ai_report"],
    },
    "orders_and_fulfillment": {
        "required_fields": ["order_id", "order_status", "fulfillment_status", "line_items"],
        "recommended_fields": ["paid_at", "ship_by_date", "tracking_number", "shipping_service", "delivery_status"],
        "sensitive_fields": ["buyer_name", "buyer_email", "ship_to_address", "phone", "recipient"],
        "used_by": ["customer_service", "logistics", "finance_review", "confirmation_center"],
    },
    "finances": {
        "required_fields": ["transaction_id", "amount", "currency", "fee_type"],
        "recommended_fields": ["order_id", "payout_id", "net_amount", "transaction_date", "billing_reference"],
        "sensitive_fields": ["buyer_name", "payout_account", "tax_id"],
        "used_by": ["finance_review", "ai_report"],
    },
    "taxonomy_listing_metadata": {
        "required_fields": ["marketplace_id", "category_id", "required_aspects"],
        "recommended_fields": ["recommended_aspects", "condition_values", "category_tree_id", "leaf_category"],
        "sensitive_fields": [],
        "used_by": ["product_listing", "market_report"],
    },
    "marketing_readonly": {
        "required_fields": ["campaign_id", "campaign_status", "ad_fee_basis"],
        "recommended_fields": ["impressions", "clicks", "sales", "ad_spend", "acos", "listing_ids"],
        "sensitive_fields": ["buyer_segment"],
        "used_by": ["market_report", "finance_review", "ai_report"],
    },
}


def build_field_contract_catalog() -> dict[str, Any]:
    return {
        "version": "2026-05-15-ebay-readonly-field-contract",
        "platform": "ebay",
        "resource_count": len(RESOURCE_FIELD_CONTRACTS),
        "resources": [
            {"resource_key": key, **contract}
            for key, contract in RESOURCE_FIELD_CONTRACTS.items()
        ],
        "rules": {
            "missing_required_fields_become_source_gaps": True,
            "sensitive_fields_are_redacted_before_persistence": True,
            "unknown_fields_are_kept_only_after_sanitization": True,
            "raw_ebay_response_not_stored": True,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def field_contract_for(resource_key: str) -> dict[str, Any]:
    return RESOURCE_FIELD_CONTRACTS.get(resource_key, {"required_fields": [], "recommended_fields": [], "sensitive_fields": [], "used_by": []})


def evaluate_resource_fields(*, resource_key: str, data: dict[str, Any]) -> dict[str, Any]:
    contract = field_contract_for(resource_key)
    required = [str(item) for item in contract.get("required_fields", [])]
    recommended = [str(item) for item in contract.get("recommended_fields", [])]
    present = {str(key) for key, value in data.items() if value not in (None, "", [], {})}
    missing_required = [field for field in required if field not in present]
    missing_recommended = [field for field in recommended if field not in present]
    return {
        "resource_key": resource_key,
        "required_fields": required,
        "recommended_fields": recommended,
        "present_fields": sorted(present),
        "missing_required_fields": missing_required,
        "missing_recommended_fields": missing_recommended,
        "contract_ready": not missing_required,
        "used_by": contract.get("used_by", []),
        "secret_exposed": False,
    }
