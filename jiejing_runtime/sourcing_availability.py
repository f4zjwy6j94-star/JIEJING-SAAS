"""Sourcing availability probe boundary for Jiejing Runtime.

This adapter normalizes sourcing candidates from 1688 links, manual links,
supplier quotes, merchant tables, image packs, or authorized read snapshots.
It never places orders or pays suppliers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SourcingAvailabilityConfig:
    product: str
    route: str = "manual_or_1688"
    candidates: list[dict[str, Any]] | None = None


class SourcingAvailabilityAdapter:
    """Normalizes supplier/source candidates for market.data_packet."""

    version = "0.1.0"

    def probe(self, config: SourcingAvailabilityConfig) -> dict[str, Any]:
        candidates = config.candidates or []
        if not candidates:
            return self.pending_snapshot(config.product, config.route)
        normalized = [self._normalize(item) for item in candidates if isinstance(item, dict)]
        normalized = [item for item in normalized if item.get("source_url") or item.get("supplier_name") or item.get("title")]
        blockers = self._blockers(normalized)
        metrics = {
            "product": config.product,
            "route": config.route,
            "candidate_count": len(normalized),
            "lowest_unit_cost": self._lowest_cost(normalized),
            "ship_from_distribution": self._ship_from_distribution(normalized),
            "ready_candidate_count": len([item for item in normalized if not item.get("missing_facts")]),
            "blockers": blockers,
        }
        return {
            "source_type": "merchant_provided",
            "confidence": "medium" if normalized else "low",
            "summary": self._summary(config.product, metrics),
            "status": "ready" if normalized and not blockers else "partial",
            "metrics": metrics,
            "candidates": normalized[:12],
            "notes": [
                "Sourcing availability is read/organize only.",
                "Supplier order, procurement payment, address write, and dropship instruction remain confirmation-gated.",
                "Final listing and margin still need verified cost, packaging, weight, origin, stock, and restriction facts.",
            ],
        }

    def pending_snapshot(self, product: str, route: str) -> dict[str, Any]:
        return {
            "source_type": "manual_input",
            "confidence": "low",
            "summary": f"No sourcing candidates were supplied for `{product}` via `{route}`.",
            "status": "pending_manual_input",
            "product": product,
            "route": route,
        }

    def _normalize(self, item: dict[str, Any]) -> dict[str, Any]:
        unit_cost = self._money(item.get("unit_cost") or item.get("price") or item.get("purchase_price"))
        shipping_cost = self._money(item.get("domestic_shipping_cost") or item.get("shipping_cost"))
        package_weight_g = self._number(item.get("package_weight_g") or item.get("weight_g"))
        missing_facts = self._missing_facts(item, unit_cost, package_weight_g)
        return {
            "source_platform": str(item.get("source_platform") or self._guess_platform(item)).strip(),
            "title": str(item.get("title") or item.get("name") or "").strip(),
            "source_url": str(item.get("source_url") or item.get("url") or item.get("link") or "").strip(),
            "supplier_name": str(item.get("supplier_name") or item.get("supplier") or "").strip(),
            "unit_cost": unit_cost,
            "currency": str(item.get("currency") or "CNY").strip(),
            "moq": self._number(item.get("moq")),
            "stock": self._number(item.get("stock")),
            "ship_from": str(item.get("ship_from") or item.get("origin") or item.get("city") or "").strip(),
            "domestic_shipping_cost": shipping_cost,
            "package_weight_g": package_weight_g,
            "package_dimensions_cm": str(item.get("package_dimensions_cm") or item.get("dimensions_cm") or "").strip(),
            "material": str(item.get("material") or "").strip(),
            "packaging": str(item.get("packaging") or "").strip(),
            "restriction_notes": str(item.get("restriction_notes") or "").strip(),
            "missing_facts": missing_facts,
        }

    def _missing_facts(self, item: dict[str, Any], unit_cost: float | None, package_weight_g: float | None) -> list[str]:
        checks = {
            "source_url": item.get("source_url") or item.get("url") or item.get("link"),
            "unit_cost": unit_cost,
            "ship_from": item.get("ship_from") or item.get("origin") or item.get("city"),
            "package_weight_g": package_weight_g,
            "package_dimensions_cm": item.get("package_dimensions_cm") or item.get("dimensions_cm"),
            "material": item.get("material"),
        }
        return [key for key, value in checks.items() if value in {None, "", 0}]

    def _blockers(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocker_counts: dict[str, int] = {}
        for item in candidates:
            for fact in item.get("missing_facts", []):
                blocker_counts[fact] = blocker_counts.get(fact, 0) + 1
        return [{"missing_fact": fact, "candidate_count": count} for fact, count in sorted(blocker_counts.items())]

    def _lowest_cost(self, candidates: list[dict[str, Any]]) -> float | None:
        costs = [item.get("unit_cost") for item in candidates if isinstance(item.get("unit_cost"), (int, float))]
        return min(costs) if costs else None

    def _ship_from_distribution(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in candidates:
            city = item.get("ship_from") or "unknown"
            counts[city] = counts.get(city, 0) + 1
        return [{"ship_from": city, "count": count} for city, count in sorted(counts.items(), key=lambda row: (-row[1], row[0]))]

    def _money(self, value: Any) -> float | None:
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    def _number(self, value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    def _guess_platform(self, item: dict[str, Any]) -> str:
        text = f"{item.get('source_url', '')} {item.get('url', '')}".lower()
        if "1688" in text:
            return "1688"
        if "alibaba" in text:
            return "Alibaba"
        if "taobao" in text:
            return "Taobao"
        return "manual"

    def _summary(self, product: str, metrics: dict[str, Any]) -> str:
        count = metrics.get("candidate_count") or 0
        if not count:
            return f"Sourcing snapshot for `{product}` has no usable candidates."
        blockers = metrics.get("blockers") or []
        if blockers:
            return f"Sourcing snapshot for `{product}` normalized {count} candidates, but supplier facts still need completion."
        return f"Sourcing snapshot for `{product}` normalized {count} candidates with core supplier facts present."
