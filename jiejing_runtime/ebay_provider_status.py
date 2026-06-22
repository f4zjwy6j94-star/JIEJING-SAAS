"""Sanitized eBay provider status for Jiejing Runtime.

This module reports which eBay capability surfaces are available or mapped
without exposing seller credentials. It is for Runtime/Agent awareness, not for
real execution.
"""

from __future__ import annotations

from typing import Any

from .ebay_credentials import EbayCredentialResolver


class EbayProviderStatus:
    """Reports eBay provider readiness without printing tokens or policy secrets."""

    version = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        resolver = EbayCredentialResolver()
        credential, credential_source = resolver.resolve_access_token()
        credential_present = bool(credential)
        access_token_status = "ready" if credential_present else "expired" if "token_expired" in credential_source else "missing"
        read_status = "credential_ready" if credential_present else "pending_token_refresh" if access_token_status == "expired" else "pending_credential"
        policy_snapshot_present = resolver.policy_snapshot_present()
        listing_rules_present = resolver.listing_rules_snapshot_present()
        oauth_refresh = resolver.oauth_refresh_status()
        return {
            "provider": "ebay",
            "credential_present": credential_present,
            "credential_source": credential_source,
            "access_token_status": access_token_status,
            "refresh_required": access_token_status == "expired",
            "policy_snapshot_present": policy_snapshot_present,
            "listing_rules_snapshot_present": listing_rules_present,
            "oauth_refresh": oauth_refresh,
            "secret_exposed": False,
            "surfaces": {
                "browse_api": {
                    "purpose": "market item summaries, sample price bands, listing examples",
                    "status": read_status,
                    "risk": "read_only",
                },
                "taxonomy_api": {
                    "purpose": "category ID, item specifics, condition/category metadata",
                    "status": read_status,
                    "risk": "read_only",
                },
                "account_policy_read": {
                    "purpose": "fulfillment, payment, and return policy templates",
                    "status": "snapshot_or_credential_ready" if credential_present or policy_snapshot_present else "pending_permission",
                    "risk": "read_only; REST 403 can mean missing business permission",
                },
                "trading_api": {
                    "purpose": "legacy listing/order/shipping/price operations when REST sell APIs are limited",
                    "status": "mapped_via_hermes",
                    "risk": "writes require ExecutionService and confirmation",
                },
                "finances_api": {
                    "purpose": "transactions, fees, refunds, profit review",
                    "status": read_status,
                    "risk": "read_only for review; money-impacting actions gated",
                },
                "write_execution": {
                    "purpose": "publish, price, inventory, policy, refund, ad, and payment-impacting actions",
                    "status": "blocked_until_confirmation_service",
                    "risk": "high",
                },
            },
        }
