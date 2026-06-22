"""Read-only eBay probe boundary for Jiejing Runtime.

This module is a safe adapter shell. It can normalize supplied Browse/Taxonomy
snapshots today, and it can perform live read-only REST calls only when a caller
explicitly enables live mode and provides a token. It never publishes, edits
price/inventory, refunds, changes ads, purchases, or edits store policy.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .ebay_credentials import EbayCredentialResolver


@dataclass(slots=True)
class EbayReadOnlyProbeConfig:
    keyword: str
    marketplace_id: str = "EBAY_US"
    limit: int = 10
    category_id: str | None = None
    category_tree_id: str = "0"
    base_url: str = "https://api.ebay.com"
    access_token: str | None = None
    live_enabled: bool = False
    timeout_seconds: int = 20


class EbayReadOnlyProbeAdapter:
    """Normalizes eBay read-only market/category data for market.data_packet."""

    version = "0.1.0"

    def probe(self, config: EbayReadOnlyProbeConfig) -> dict[str, Any]:
        if not config.live_enabled:
            return self.pending_snapshot(
                "Live eBay read-only probe is disabled. Provide a Browse API snapshot or enable live read-only mode in backend.",
                keyword=config.keyword,
                marketplace_id=config.marketplace_id,
            )
        token, token_source = EbayCredentialResolver().resolve_access_token(
            config.access_token,
            env_names=("JIEJING_EBAY_READ_TOKEN", "EBAY_ACCESS_TOKEN", "JIEJING_EBAY_ACCOUNT_READ_TOKEN"),
        )
        if not token:
            return self.pending_snapshot(
                "Live eBay read-only probe needs an access token in backend configuration; no token was available.",
                keyword=config.keyword,
                marketplace_id=config.marketplace_id,
            )
        try:
            browse = self._get_json(self._browse_search_url(config), token, config.marketplace_id, config.timeout_seconds)
            taxonomy = None
            if config.category_id:
                taxonomy = self._get_json(self._taxonomy_aspects_url(config), token, config.marketplace_id, config.timeout_seconds)
            return self.snapshot_from_responses(
                keyword=config.keyword,
                marketplace_id=config.marketplace_id,
                browse_response=browse,
                taxonomy_response=taxonomy,
            ) | {"credential_source": token_source, "secret_exposed": False}
        except Exception as exc:  # pragma: no cover - provider/network dependent
            error = self._safe_error(exc, token)
            return {
                "source_type": "official_api",
                "confidence": "low",
                "summary": f"eBay read-only probe failed: {error[:240]}",
                "status": "failed_tool",
                "error": error[:500],
                "credential_source": token_source,
                "secret_exposed": False,
            }

    def pending_snapshot(self, reason: str, keyword: str = "", marketplace_id: str = "EBAY_US") -> dict[str, Any]:
        return {
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": reason,
            "status": "pending_connector",
            "query": {"keyword": keyword, "marketplace_id": marketplace_id},
        }

    def snapshot_from_responses(
        self,
        keyword: str,
        marketplace_id: str,
        browse_response: dict[str, Any],
        taxonomy_response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item_summaries = browse_response.get("itemSummaries")
        items = item_summaries if isinstance(item_summaries, list) else []
        prices = self._prices(items)
        category_distribution = self._category_distribution(items, browse_response)
        top_items = [self._top_item(item) for item in items[:5]]
        required_aspects = self._required_aspects(taxonomy_response or {})
        metrics = {
            "query": keyword,
            "marketplace_id": marketplace_id,
            "total": browse_response.get("total"),
            "sample_count": len(items),
            "price_min": min(prices) if prices else None,
            "price_median": self._median(prices),
            "price_max": max(prices) if prices else None,
            "currency": self._currency(items),
            "category_distribution": category_distribution,
            "required_aspect_count": len(required_aspects),
        }
        return {
            "source_type": "official_api",
            "confidence": "medium" if items else "low",
            "summary": self._summary(keyword, metrics, required_aspects),
            "status": "ready" if items else "partial",
            "metrics": metrics,
            "top_items": top_items,
            "required_aspects": required_aspects,
            "raw_shape": {
                "browse_keys": sorted(browse_response.keys()),
                "taxonomy_keys": sorted((taxonomy_response or {}).keys()),
            },
        }

    def _browse_search_url(self, config: EbayReadOnlyProbeConfig) -> str:
        params = {
            "q": config.keyword,
            "limit": str(max(1, min(config.limit, 50))),
        }
        if config.category_id:
            params["category_ids"] = config.category_id
        return f"{config.base_url.rstrip('/')}/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}"

    def _taxonomy_aspects_url(self, config: EbayReadOnlyProbeConfig) -> str:
        params = {"category_id": config.category_id or ""}
        return (
            f"{config.base_url.rstrip('/')}/commerce/taxonomy/v1/category_tree/"
            f"{urllib.parse.quote(config.category_tree_id)}/get_item_aspects_for_category?{urllib.parse.urlencode(params)}"
        )

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

    def _prices(self, items: list[dict[str, Any]]) -> list[float]:
        prices: list[float] = []
        for item in items:
            price = item.get("price") if isinstance(item, dict) else None
            if not isinstance(price, dict):
                continue
            try:
                prices.append(float(price.get("value")))
            except (TypeError, ValueError):
                continue
        prices.sort()
        return prices

    def _currency(self, items: list[dict[str, Any]]) -> str | None:
        for item in items:
            price = item.get("price") if isinstance(item, dict) else None
            if isinstance(price, dict) and price.get("currency"):
                return str(price["currency"])
        return None

    def _median(self, values: list[float]) -> float | None:
        if not values:
            return None
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return round((values[middle - 1] + values[middle]) / 2, 2)

    def _category_distribution(self, items: list[dict[str, Any]], browse_response: dict[str, Any]) -> list[dict[str, Any]]:
        refinement = browse_response.get("refinement")
        category_distributions = refinement.get("categoryDistributions") if isinstance(refinement, dict) else None
        if isinstance(category_distributions, list) and category_distributions:
            return [
                {
                    "category_id": item.get("categoryId"),
                    "category_name": item.get("categoryName"),
                    "match_count": item.get("matchCount"),
                }
                for item in category_distributions[:8]
                if isinstance(item, dict)
            ]
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for item in items:
            categories = item.get("categories")
            if not isinstance(categories, list):
                continue
            for category in categories:
                if not isinstance(category, dict):
                    continue
                category_id = str(category.get("categoryId") or "")
                if not category_id:
                    continue
                counts[category_id] = counts.get(category_id, 0) + 1
                if category.get("categoryName"):
                    names[category_id] = str(category["categoryName"])
        return [
            {"category_id": category_id, "category_name": names.get(category_id), "match_count": count}
            for category_id, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:8]
        ]

    def _top_item(self, item: dict[str, Any]) -> dict[str, Any]:
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        return {
            "item_id": item.get("itemId"),
            "title": item.get("title"),
            "price": price.get("value"),
            "currency": price.get("currency"),
            "item_web_url": item.get("itemWebUrl"),
            "seller_username": seller.get("username") or seller.get("sellerUsername"),
            "condition": item.get("condition"),
        }

    def _required_aspects(self, taxonomy_response: dict[str, Any]) -> list[dict[str, Any]]:
        aspects = taxonomy_response.get("aspects")
        if not isinstance(aspects, list):
            return []
        required = []
        for aspect in aspects:
            if not isinstance(aspect, dict):
                continue
            constraint = aspect.get("aspectConstraint")
            if not isinstance(constraint, dict) or constraint.get("aspectRequired") is not True:
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
                        for value in (aspect.get("aspectValues") or [])[:20]
                        if isinstance(value, dict) and value.get("localizedValue")
                    ],
                }
            )
        return required

    def _summary(self, keyword: str, metrics: dict[str, Any], required_aspects: list[dict[str, Any]]) -> str:
        sample_count = metrics.get("sample_count") or 0
        if not sample_count:
            return f"eBay read-only Browse snapshot for `{keyword}` returned no item summaries."
        price_text = "price data unavailable"
        if metrics.get("price_min") is not None and metrics.get("price_max") is not None:
            currency = metrics.get("currency") or ""
            price_text = f"{currency} {metrics['price_min']}-{metrics['price_max']} sample band"
        aspect_text = f"; {len(required_aspects)} required category aspects found" if required_aspects else ""
        return f"eBay read-only Browse snapshot for `{keyword}` returned {sample_count} item summaries with {price_text}{aspect_text}."

    def _safe_error(self, exc: Exception, token: str) -> str:
        message = str(exc)
        if token:
            message = message.replace(token, "[redacted]")
        return message
