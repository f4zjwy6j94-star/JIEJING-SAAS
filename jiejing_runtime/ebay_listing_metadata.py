"""Read-only eBay listing metadata for product listing packages.

This adapter reads or normalizes the exact pre-publish metadata a listing
manager needs: category aspects from Taxonomy and store business policies from
Account API. It never creates, edits, or publishes listings and never edits
business policies.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .ebay_credentials import EbayCredentialResolver


@dataclass(slots=True)
class EbayListingMetadataConfig:
    marketplace_id: str = "EBAY_US"
    category_id: str = ""
    category_tree_id: str = "0"
    base_url: str = "https://api.ebay.com"
    access_token: str | None = None
    live_enabled: bool = False
    taxonomy_response: dict[str, Any] | None = None
    fulfillment_policy_response: dict[str, Any] | None = None
    payment_policy_response: dict[str, Any] | None = None
    return_policy_response: dict[str, Any] | None = None
    timeout_seconds: int = 20


class EbayListingMetadataAdapter:
    """Builds a listing metadata packet from official read-only sources."""

    version = "0.1.0"

    def probe(self, config: EbayListingMetadataConfig) -> dict[str, Any]:
        resolver = EbayCredentialResolver()
        if any(
            isinstance(value, dict)
            for value in [
                config.taxonomy_response,
                config.fulfillment_policy_response,
                config.payment_policy_response,
                config.return_policy_response,
            ]
        ):
            return self.snapshot_from_responses(
                marketplace_id=config.marketplace_id,
                category_id=config.category_id,
                taxonomy_response=config.taxonomy_response or {},
                fulfillment_policy_response=config.fulfillment_policy_response or {},
                payment_policy_response=config.payment_policy_response or {},
                return_policy_response=config.return_policy_response or {},
            )
        if not config.live_enabled:
            return self.pending_snapshot("Listing metadata live read is disabled. Provide Taxonomy/Account snapshots or enable backend read-only mode.")
        token, token_source = resolver.resolve_access_token(
            config.access_token,
            env_names=("JIEJING_EBAY_ACCOUNT_READ_TOKEN", "JIEJING_EBAY_READ_TOKEN", "EBAY_ACCESS_TOKEN"),
        )
        policy_snapshot = resolver.policy_snapshot_responses()
        if not token:
            if any(policy_snapshot.values()):
                snapshot = self.snapshot_from_responses(
                    marketplace_id=config.marketplace_id,
                    category_id=config.category_id,
                    taxonomy_response={},
                    fulfillment_policy_response=policy_snapshot.get("fulfillment_policy_response", {}),
                    payment_policy_response=policy_snapshot.get("payment_policy_response", {}),
                    return_policy_response=policy_snapshot.get("return_policy_response", {}),
                )
                snapshot["credential_source"] = token_source
                snapshot["policy_snapshot_source"] = "wsl_hermes_business_policy_snapshot"
                snapshot["secret_exposed"] = False
                return snapshot
            return self.pending_snapshot("Listing metadata read needs an authorized eBay token with Taxonomy/Account read scopes.")
        try:
            taxonomy = {}
            if config.category_id:
                taxonomy = self._get_json(self._taxonomy_url(config), token, config.marketplace_id, config.timeout_seconds)
            fulfillment = self._get_json(self._account_policy_url(config, "fulfillment_policy"), token, config.marketplace_id, config.timeout_seconds)
            payment = self._get_json(self._account_policy_url(config, "payment_policy"), token, config.marketplace_id, config.timeout_seconds)
            returns = self._get_json(self._account_policy_url(config, "return_policy"), token, config.marketplace_id, config.timeout_seconds)
            return self.snapshot_from_responses(
                marketplace_id=config.marketplace_id,
                category_id=config.category_id,
                taxonomy_response=taxonomy,
                fulfillment_policy_response=fulfillment,
                payment_policy_response=payment,
                return_policy_response=returns,
            ) | {"credential_source": token_source, "secret_exposed": False}
        except Exception as exc:  # pragma: no cover - live provider dependent
            error = self._safe_error(exc, token)
            if any(policy_snapshot.values()):
                snapshot = self.snapshot_from_responses(
                    marketplace_id=config.marketplace_id,
                    category_id=config.category_id,
                    taxonomy_response={},
                    fulfillment_policy_response=policy_snapshot.get("fulfillment_policy_response", {}),
                    payment_policy_response=policy_snapshot.get("payment_policy_response", {}),
                    return_policy_response=policy_snapshot.get("return_policy_response", {}),
                )
                notes = list(snapshot.get("notes") or [])
                notes.append("Live Account/Taxonomy read failed, so Runtime used the latest sanitized Hermes business-policy snapshot.")
                snapshot["notes"] = notes
                snapshot["live_error"] = error[:500]
                snapshot["credential_source"] = token_source
                snapshot["policy_snapshot_source"] = "wsl_hermes_business_policy_snapshot"
                snapshot["secret_exposed"] = False
                return snapshot
            return {
                "status": "failed_tool",
                "source_type": "official_api",
                "confidence": "low",
                "summary": f"eBay listing metadata read failed: {error[:240]}",
                "error": error[:500],
                "credential_source": token_source,
                "secret_exposed": False,
                "real_execution_allowed": False,
            }

    def pending_snapshot(self, reason: str) -> dict[str, Any]:
        return {
            "status": "pending_connector",
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": reason,
            "required_before_publish": ["category item specifics", "fulfillment policy", "payment policy", "return policy"],
            "real_execution_allowed": False,
        }

    def snapshot_from_responses(
        self,
        marketplace_id: str,
        category_id: str,
        taxonomy_response: dict[str, Any],
        fulfillment_policy_response: dict[str, Any],
        payment_policy_response: dict[str, Any],
        return_policy_response: dict[str, Any],
    ) -> dict[str, Any]:
        required_aspects = self._required_aspects(taxonomy_response)
        policies = {
            "fulfillment": self._policies(fulfillment_policy_response, "fulfillmentPolicies", "fulfillmentPolicyId"),
            "payment": self._policies(payment_policy_response, "paymentPolicies", "paymentPolicyId"),
            "return": self._policies(return_policy_response, "returnPolicies", "returnPolicyId"),
        }
        missing = []
        if category_id and not required_aspects:
            missing.append("taxonomy_required_aspects")
        for key, items in policies.items():
            if not items:
                missing.append(f"{key}_policy")
        status = "ready" if not missing and (required_aspects or not category_id) else "partial"
        return {
            "status": status,
            "source_type": "official_api",
            "confidence": "medium" if status == "ready" else "low",
            "summary": self._summary(marketplace_id, category_id, required_aspects, policies, missing),
            "marketplace_id": marketplace_id,
            "category_id": category_id,
            "required_aspects": required_aspects,
            "business_policies": policies,
            "missing": missing,
            "real_execution_allowed": False,
            "notes": [
                "Account API policy reads require seller authorization and sell.account or sell.account.readonly scope.",
                "Taxonomy aspects are category and marketplace dependent; do not hardcode item specifics.",
                "Policy reads do not edit policy. Edits remain confirmation-gated.",
            ],
        }

    def _taxonomy_url(self, config: EbayListingMetadataConfig) -> str:
        params = {"category_id": config.category_id}
        return (
            f"{config.base_url.rstrip('/')}/commerce/taxonomy/v1/category_tree/"
            f"{urllib.parse.quote(config.category_tree_id)}/get_item_aspects_for_category?{urllib.parse.urlencode(params)}"
        )

    def _account_policy_url(self, config: EbayListingMetadataConfig, policy_path: str) -> str:
        params = {"marketplace_id": config.marketplace_id}
        return f"{config.base_url.rstrip('/')}/sell/account/v1/{policy_path}?{urllib.parse.urlencode(params)}"

    def _get_json(self, url: str, token: str, marketplace_id: str, timeout_seconds: int) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {token}",
                "x-ebay-c-marketplace-id": marketplace_id,
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _required_aspects(self, taxonomy_response: dict[str, Any]) -> list[dict[str, Any]]:
        aspects = taxonomy_response.get("aspects")
        if not isinstance(aspects, list):
            return []
        required = []
        for aspect in aspects:
            if not isinstance(aspect, dict):
                continue
            constraint = aspect.get("aspectConstraint") if isinstance(aspect.get("aspectConstraint"), dict) else {}
            if constraint.get("aspectRequired") is not True:
                continue
            required.append(
                {
                    "name": aspect.get("localizedAspectName"),
                    "mode": constraint.get("aspectMode"),
                    "data_type": constraint.get("aspectDataType"),
                    "cardinality": constraint.get("itemToAspectCardinality"),
                    "usage": constraint.get("aspectUsage"),
                    "values": [
                        value.get("localizedValue")
                        for value in (aspect.get("aspectValues") or [])[:25]
                        if isinstance(value, dict) and value.get("localizedValue")
                    ],
                }
            )
        return required

    def _policies(self, response: dict[str, Any], array_key: str, id_key: str) -> list[dict[str, Any]]:
        items = response.get(array_key)
        if not isinstance(items, list):
            return []
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "id": item.get(id_key),
                    "name": item.get("name"),
                    "marketplace_id": item.get("marketplaceId"),
                    "category_types": item.get("categoryTypes") if isinstance(item.get("categoryTypes"), list) else [],
                }
            )
        return normalized

    def _summary(
        self,
        marketplace_id: str,
        category_id: str,
        required_aspects: list[dict[str, Any]],
        policies: dict[str, list[dict[str, Any]]],
        missing: list[str],
    ) -> str:
        if missing:
            return f"Listing metadata for {marketplace_id}/{category_id or 'category pending'} is partial; missing: {', '.join(missing)}."
        return (
            f"Listing metadata for {marketplace_id}/{category_id or 'category pending'} is ready with "
            f"{len(required_aspects)} required aspects and policy counts "
            f"F/P/R={len(policies['fulfillment'])}/{len(policies['payment'])}/{len(policies['return'])}."
        )

    def _safe_error(self, exc: Exception, token: str) -> str:
        message = str(exc)
        if token:
            message = message.replace(token, "[redacted]")
        return message
