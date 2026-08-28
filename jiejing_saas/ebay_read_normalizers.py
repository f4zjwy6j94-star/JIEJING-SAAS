"""Normalize eBay read-only resource payloads into Jiejing packet fields."""

from __future__ import annotations

from typing import Any

from .ebay_read_contract import evaluate_resource_fields


SUPPORTED_READ_RESOURCE_KEYS = {
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
    "marketing_readonly",
}


def normalizer_catalog() -> dict[str, Any]:
    return {
        "version": "2026-05-15-ebay-read-normalizer-catalog",
        "resource_keys": sorted(SUPPORTED_READ_RESOURCE_KEYS),
        "resource_count": len(SUPPORTED_READ_RESOURCE_KEYS),
        "normalizes_raw_response": False,
        "normalizes_sanitized_resource_sections": True,
        "secret_exposed": False,
    }


def normalize_read_resource(resource_key: str, raw: dict[str, Any]) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    if resource_key == "store_profile":
        normalized = {
            "marketplace_id": _first(raw, "marketplace_id", "marketplace", "site_id"),
            "seller_account_status": _first(raw, "seller_account_status", "account_status", "status"),
            "selling_limits": _first(raw, "selling_limits", "selling_limit", "limits"),
            "store_name": _first(raw, "store_name", "seller_username", "username"),
            "registered_country": _first(raw, "registered_country", "country"),
            "seller_level": _first(raw, "seller_level", "seller_standing"),
            "policy_setup_status": _first(raw, "policy_setup_status", "policy_status"),
            "kyc_check_status": _first(raw, "kyc_check_status"),
            "kyc_check_count": _first(raw, "kyc_check_count"),
            "kyc_checks": _first(raw, "kyc_checks"),
            "verification_status": _first(raw, "verification_status"),
            "payout_status": _first(raw, "payout_status"),
        }
    elif resource_key == "account_business_policies":
        normalized = {
            "fulfillment_policy_id": _first(raw, "fulfillment_policy_id", "fulfillmentPolicyId"),
            "payment_policy_id": _first(raw, "payment_policy_id", "paymentPolicyId"),
            "return_policy_id": _first(raw, "return_policy_id", "returnPolicyId"),
            "handling_time": _first(raw, "handling_time", "handlingTime"),
            "shipping_service": _first(raw, "shipping_service", "shippingService"),
            "return_window": _first(raw, "return_window", "returnWindow"),
            "return_payer": _first(raw, "return_payer", "returnPayer"),
            "policy_marketplace": _first(raw, "policy_marketplace", "marketplace_id", "marketplaceId"),
        }
    elif resource_key == "inventory_and_offers":
        normalized = {
            "sku": _first(raw, "sku", "SKU"),
            "title": _first(raw, "title", "listing_title", "name"),
            "description": _first(raw, "description", "listing_description"),
            "price": _first(raw, "price", "current_price"),
            "quantity": _first(raw, "quantity", "available_quantity"),
            "condition": _first(raw, "condition", "condition_id"),
            "marketplace_id": _first(raw, "marketplace_id", "marketplaceId"),
            "offer_id": _first(raw, "offer_id", "offerId"),
            "listing_id": _first(raw, "listing_id", "listingId"),
            "item_id": _first(raw, "item_id", "itemId"),
            "category_id": _first(raw, "category_id", "categoryId"),
            "item_location": _first(raw, "item_location", "merchant_location_key", "location"),
            "listing_status": _first(raw, "listing_status", "status"),
            "format": _first(raw, "format", "listing_format"),
            "inventory_item_count": _first(raw, "inventory_item_count"),
            "offer_count": _first(raw, "offer_count"),
            "location_count": _first(raw, "location_count"),
            "inventory_items": _safe_inventory_items(_first(raw, "inventory_items", "inventoryItems", "items")),
            "offers": _safe_offer_items(_first(raw, "offers", "listings")),
            "pictures": _first(raw, "pictures", "picture_urls", "image_urls", "images"),
            "item_specifics": _first(raw, "item_specifics", "aspects"),
        }
    elif resource_key == "orders_and_fulfillment":
        normalized = {
            "order_id": _first(raw, "order_id", "orderId"),
            "order_status": _first(raw, "order_status", "status"),
            "fulfillment_status": _first(raw, "fulfillment_status", "fulfillmentStatus"),
            "line_items": _first(raw, "line_items", "lineItems"),
            "paid_at": _first(raw, "paid_at", "paidDate"),
            "ship_by_date": _first(raw, "ship_by_date", "shipByDate"),
            "tracking_number": _first(raw, "tracking_number", "trackingNumber"),
            "shipping_service": _first(raw, "shipping_service", "shippingService"),
            "delivery_status": _first(raw, "delivery_status", "deliveryStatus"),
            "order_count": _first(raw, "order_count"),
            "buyer_name": _first(raw, "buyer_name", "buyerName"),
            "buyer_email": _first(raw, "buyer_email", "buyerEmail"),
            "ship_to_address": _first(raw, "ship_to_address", "shipToAddress"),
        }
    elif resource_key == "finances":
        normalized = {
            "transaction_id": _first(raw, "transaction_id", "transactionId"),
            "amount": _first(raw, "amount", "gross_amount", "net_amount"),
            "currency": _first(raw, "currency", "currencyCode"),
            "fee_type": _first(raw, "fee_type", "transaction_type", "type"),
            "order_id": _first(raw, "order_id", "orderId"),
            "payout_id": _first(raw, "payout_id", "payoutId"),
            "net_amount": _first(raw, "net_amount", "netAmount"),
            "transaction_date": _first(raw, "transaction_date", "transactionDate"),
            "billing_reference": _first(raw, "billing_reference", "billingReference"),
            "transaction_count": _first(raw, "transaction_count"),
        }
    elif resource_key == "taxonomy_listing_metadata":
        normalized = {
            "marketplace_id": _first(raw, "marketplace_id", "marketplaceId"),
            "category_id": _first(raw, "category_id", "categoryId"),
            "required_aspects": _first(raw, "required_aspects", "requiredAspects"),
            "recommended_aspects": _first(raw, "recommended_aspects", "recommendedAspects"),
            "condition_values": _first(raw, "condition_values", "conditionValues"),
            "category_tree_id": _first(raw, "category_tree_id", "categoryTreeId"),
            "leaf_category": _first(raw, "leaf_category", "leafCategory"),
        }
    elif resource_key == "marketing_readonly":
        normalized = {
            "campaign_id": _first(raw, "campaign_id", "campaignId"),
            "campaign_status": _first(raw, "campaign_status", "status"),
            "ad_fee_basis": _first(raw, "ad_fee_basis", "fundingStrategy"),
            "impressions": _first(raw, "impressions"),
            "clicks": _first(raw, "clicks"),
            "sales": _first(raw, "sales"),
            "ad_spend": _first(raw, "ad_spend", "spend"),
            "acos": _first(raw, "acos"),
            "listing_ids": _first(raw, "listing_ids", "listingIds"),
        }
    else:
        normalized = dict(raw)

    normalized = {key: value for key, value in normalized.items() if value not in (None, "", [], {})}
    evaluation = evaluate_resource_fields(resource_key=resource_key, data=normalized)
    return {
        "resource_key": resource_key,
        "normalized": normalized,
        "field_evaluation": evaluation,
        "normalizer_version": "2026-05-15-ebay-read-normalizers",
        "secret_exposed": False,
    }


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, "", [], {}):
            return raw[key]
    return None


def _safe_inventory_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        safe.append(
            {
                key: item.get(key)
                for key in (
                    "sku",
                    "title",
                    "description",
                    "condition",
                    "quantity",
                    "image_urls",
                    "pictures",
                    "aspects",
                    "item_specifics",
                )
                if item.get(key) not in (None, "", [], {})
            }
        )
    return [item for item in safe if item]


def _safe_offer_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        safe.append(
            {
                key: item.get(key)
                for key in (
                    "offer_id",
                    "offerId",
                    "listing_id",
                    "listingId",
                    "item_id",
                    "itemId",
                    "sku",
                    "marketplace_id",
                    "marketplaceId",
                    "category_id",
                    "categoryId",
                    "listing_status",
                    "status",
                    "format",
                    "price",
                )
                if item.get(key) not in (None, "", [], {})
            }
        )
    return [item for item in safe if item]
