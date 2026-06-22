"""Logistics estimate probe boundary for Jiejing Runtime.

This adapter normalizes shipping estimates and package facts for the market
data packet. It does not buy labels, update tracking, or promise delivery dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LogisticsEstimateConfig:
    product: str
    origin: str = "China"
    destination: str = "United States"
    package_weight_g: float | None = None
    package_dimensions_cm: str = ""
    route: str = "SpeedPAK/Orange Connex estimate"
    estimates: list[dict[str, Any]] | None = None


class LogisticsEstimateAdapter:
    """Normalizes logistics candidates and package blockers."""

    version = "0.1.0"

    def probe(self, config: LogisticsEstimateConfig) -> dict[str, Any]:
        package_facts = self._package_facts(config)
        estimates = [self._normalize_estimate(item) for item in (config.estimates or []) if isinstance(item, dict)]
        estimates = [item for item in estimates if item.get("service_name") or item.get("shipping_cost")]
        missing_facts = self._missing_facts(config, estimates)
        metrics = {
            "product": config.product,
            "origin": config.origin,
            "destination": config.destination,
            "route": config.route,
            "package_weight_g": package_facts["package_weight_g"],
            "package_dimensions_cm": package_facts["package_dimensions_cm"],
            "estimate_count": len(estimates),
            "lowest_shipping_cost": self._lowest_shipping_cost(estimates),
            "fastest_eta_days": self._fastest_eta_days(estimates),
            "missing_facts": missing_facts,
        }
        status = "ready" if estimates and not missing_facts else ("partial" if estimates or package_facts["has_any_package_fact"] else "pending_facts")
        return {
            "source_type": "tool_estimate",
            "confidence": "medium" if status == "ready" else "low",
            "summary": self._summary(config.product, metrics, status),
            "status": status,
            "metrics": metrics,
            "estimates": estimates[:8],
            "notes": [
                "Logistics estimate is not a purchased label.",
                "Do not promise a delivery date until a real carrier/service quote and handling policy are confirmed.",
                "Buying labels, writing tracking, or changing shipping policy remains confirmation-gated.",
            ],
        }

    def pending_snapshot(self, product: str) -> dict[str, Any]:
        return {
            "source_type": "tool_estimate",
            "confidence": "low",
            "summary": f"No logistics estimate or package facts were supplied for `{product}`.",
            "status": "pending_facts",
            "product": product,
        }

    def _package_facts(self, config: LogisticsEstimateConfig) -> dict[str, Any]:
        return {
            "package_weight_g": self._number(config.package_weight_g),
            "package_dimensions_cm": config.package_dimensions_cm.strip(),
            "has_any_package_fact": bool(config.package_weight_g or config.package_dimensions_cm.strip()),
        }

    def _normalize_estimate(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "carrier": str(item.get("carrier") or item.get("provider") or "").strip(),
            "service_name": str(item.get("service_name") or item.get("service") or item.get("route") or "").strip(),
            "shipping_cost": self._money(item.get("shipping_cost") or item.get("cost") or item.get("price")),
            "currency": str(item.get("currency") or "CNY").strip(),
            "eta_min_days": self._number(item.get("eta_min_days") or item.get("min_days")),
            "eta_max_days": self._number(item.get("eta_max_days") or item.get("max_days")),
            "tracking": self._bool_or_none(item.get("tracking")),
            "restriction_notes": str(item.get("restriction_notes") or item.get("notes") or "").strip(),
            "source": str(item.get("source") or "manual_or_tool_estimate").strip(),
        }

    def _missing_facts(self, config: LogisticsEstimateConfig, estimates: list[dict[str, Any]]) -> list[str]:
        missing = []
        if not config.package_weight_g:
            missing.append("package_weight_g")
        if not config.package_dimensions_cm:
            missing.append("package_dimensions_cm")
        if not config.origin:
            missing.append("origin")
        if not config.destination:
            missing.append("destination")
        if not estimates:
            missing.append("shipping_estimate")
        return missing

    def _lowest_shipping_cost(self, estimates: list[dict[str, Any]]) -> float | None:
        costs = [item.get("shipping_cost") for item in estimates if isinstance(item.get("shipping_cost"), (int, float))]
        return min(costs) if costs else None

    def _fastest_eta_days(self, estimates: list[dict[str, Any]]) -> float | None:
        days = [item.get("eta_min_days") for item in estimates if isinstance(item.get("eta_min_days"), (int, float))]
        return min(days) if days else None

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

    def _bool_or_none(self, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower().strip()
            if lowered in {"true", "yes", "y", "1"}:
                return True
            if lowered in {"false", "no", "n", "0"}:
                return False
        return None

    def _summary(self, product: str, metrics: dict[str, Any], status: str) -> str:
        if status == "ready":
            return (
                f"Logistics snapshot for `{product}` has package facts and {metrics.get('estimate_count')} estimate(s); "
                f"lowest observed shipping cost is {metrics.get('lowest_shipping_cost')}."
            )
        if status == "partial":
            return f"Logistics snapshot for `{product}` is partial; missing facts: {', '.join(metrics.get('missing_facts') or [])}."
        return f"Logistics snapshot for `{product}` is pending package facts and a shipping estimate."
