"""Cross-platform reference probe boundary for Jiejing Runtime.

Cross-platform signals help the AI CEO understand buyer language, sourcing
availability, and visual merchandising, but they are not official eBay data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CrossPlatformReferenceConfig:
    product: str
    references: list[dict[str, Any]] | None = None
    context: str = "market.data_packet"


class CrossPlatformReferenceAdapter:
    """Normalizes public/authorized platform references into one snapshot."""

    version = "0.1.0"

    PLATFORM_ALIASES = {
        "amazon": "Amazon",
        "1688": "1688",
        "taobao": "Taobao",
        "淘宝": "Taobao",
        "pinduoduo": "Pinduoduo",
        "拼多多": "Pinduoduo",
        "shopify": "Shopify",
        "alibaba": "Alibaba",
        "aliexpress": "AliExpress",
        "temu": "Temu",
        "shein": "SHEIN",
    }

    def probe(self, config: CrossPlatformReferenceConfig) -> dict[str, Any]:
        references = config.references or []
        if not references:
            return self.pending_snapshot(config.product)
        normalized = [self._normalize(item) for item in references if isinstance(item, dict)]
        normalized = [item for item in normalized if item.get("platform") or item.get("title") or item.get("url")]
        platform_distribution = self._platform_distribution(normalized)
        useful_for = sorted({tag for item in normalized for tag in item.get("useful_for", [])})
        return {
            "source_type": "public_page",
            "confidence": "medium" if normalized else "low",
            "summary": self._summary(config.product, normalized, platform_distribution),
            "status": "ready" if normalized else "partial",
            "metrics": {
                "product": config.product,
                "reference_count": len(normalized),
                "platform_distribution": platform_distribution,
                "useful_for": useful_for,
            },
            "references": normalized[:16],
            "notes": [
                "Cross-platform references are directional only.",
                "Do not present Amazon/1688/Taobao/Pinduoduo/Shopify observations as eBay official demand.",
                "Use authorized API data or merchant-provided exports when platform pages are restricted.",
            ],
        }

    def pending_snapshot(self, product: str) -> dict[str, Any]:
        return {
            "source_type": "restricted_unavailable",
            "confidence": "low",
            "summary": f"No cross-platform reference snapshot was supplied for `{product}`.",
            "status": "pending_tool",
            "product": product,
        }

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        platform = self._platform(item)
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        price = item.get("price")
        currency = str(item.get("currency") or "").strip()
        source_type = str(item.get("source_type") or "public_page").strip()
        summary = str(item.get("summary") or item.get("snippet") or item.get("description") or "").strip()
        useful_for = self._useful_for(platform, title, summary, item)
        return {
            "platform": platform,
            "title": title,
            "url": url,
            "price": price,
            "currency": currency,
            "source_type": source_type,
            "summary": summary[:600],
            "useful_for": useful_for,
            "confidence": str(item.get("confidence") or "medium"),
        }

    def _platform(self, item: dict[str, Any]) -> str:
        raw = str(item.get("platform") or "").strip()
        if raw:
            return self.PLATFORM_ALIASES.get(raw.lower(), raw)
        text = f"{item.get('url', '')} {item.get('title', '')}".lower()
        for key, label in self.PLATFORM_ALIASES.items():
            if key in text:
                return label
        return "Other"

    def _useful_for(self, platform: str, title: str, summary: str, item: dict[str, Any]) -> list[str]:
        text = f"{platform} {title} {summary}".lower()
        tags = set(str(tag) for tag in item.get("useful_for", []) if tag)
        if platform in {"1688", "Alibaba", "AliExpress"}:
            tags.add("sourcing")
        if platform in {"Amazon", "Shopify", "Temu", "SHEIN"}:
            tags.add("buyer_language")
            tags.add("visual_merchandising")
        if any(word in text for word in ["review", "rating", "complaint", "return", "leak", "broken"]):
            tags.add("risk_signal")
        if any(word in text for word in ["price", "wholesale", "moq", "supplier", "factory"]):
            tags.add("price_or_supply_reference")
        return sorted(tags)

    def _platform_distribution(self, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in references:
            platform = item.get("platform") or "Other"
            counts[platform] = counts.get(platform, 0) + 1
        return [{"platform": platform, "count": count} for platform, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))]

    def _summary(self, product: str, references: list[dict[str, Any]], distribution: list[dict[str, Any]]) -> str:
        if not references:
            return f"Cross-platform reference snapshot for `{product}` has no usable records."
        platforms = ", ".join(item["platform"] for item in distribution[:5])
        return f"Cross-platform reference snapshot for `{product}` normalized {len(references)} records across {platforms}."
