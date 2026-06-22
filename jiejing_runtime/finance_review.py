"""Finance review validation for Jiejing Runtime.

The finance role must return money numbers, not only percentages or a vague
"profit looks fine" conclusion. Real publish remains locked until supplier,
logistics, policy, and merchant confirmation are complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FinanceCheck:
    field_id: str
    label: str
    aliases: tuple[str, ...] = ()

    def to_dict(self, present: bool) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "present": present,
        }


class FinanceReviewValidator:
    """Validates finance-manager output before confirmation package."""

    version = "0.1.0"

    REQUIRED_FIELDS = [
        FinanceCheck("cost_table", "Cost table", aliases=("cost breakdown", "cost inputs")),
        FinanceCheck("sale_price", "Sale price", aliases=("listing price", "selling price")),
        FinanceCheck("procurement_cost", "Procurement cost", aliases=("purchase cost", "supplier price", "1688 cost")),
        FinanceCheck("platform_fee", "Platform fee", aliases=("ebay fee", "final value fee")),
        FinanceCheck("logistics_cost", "Logistics cost", aliases=("shipping cost", "speedpak", "orange connex")),
        FinanceCheck("package_cost", "Package cost", aliases=("packaging cost", "packing cost")),
        FinanceCheck("net_profit_money", "Net profit money", aliases=("net profit", "profit money")),
        FinanceCheck("logistics_route", "Logistics route", aliases=("shipping route", "fulfillment route")),
        FinanceCheck("subscription_allocation", "Subscription allocation", aliases=("store subscription", "subscription fee")),
        FinanceCheck("return_reserve", "Return reserve", aliases=("refund reserve", "return buffer")),
        FinanceCheck("risk_notes", "Risk notes", aliases=("financial risk", "cashflow risk")),
        FinanceCheck("next_action", "Next action", aliases=("finance lock", "publish lock", "confirmation next")),
    ]

    MONEY_PATTERN = re.compile(
        r"(?i)(?:us\s*\$|\$|usd|cny|rmb|¥|￥)\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:usd|cny|rmb|yuan|元)"
    )

    def validate_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize(text)
        checks = [field.to_dict(self._present(normalized, field)) for field in self.REQUIRED_FIELDS]
        missing_required = [check for check in checks if not check["present"]]
        money_values = self._money_values(text)
        percent_only = bool(re.search(r"\d+(?:\.\d+)?\s*%", text)) and len(money_values) < 4
        finance_lock_present = self._finance_lock_present(normalized)
        status = "ready_for_confirmation_review"
        if missing_required:
            status = "blocked_incomplete_finance_review"
        if len(money_values) < 4 or percent_only:
            status = "blocked_missing_money_numbers"
        if not finance_lock_present:
            status = "blocked_missing_finance_lock"
        return {
            "validator": "finance-review-validator",
            "validator_version": self.version,
            "status": status,
            "field_checks": checks,
            "missing_required_fields": missing_required,
            "money_value_count": len(money_values),
            "money_values_sample": money_values[:12],
            "percent_only": percent_only,
            "finance_lock_present": finance_lock_present,
            "summary": self._summary(status, missing_required, len(money_values), finance_lock_present),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        missing = [
            {
                "input_id": f"finance_field_{item['field_id']}",
                "reason": f"Finance review is missing required field: {item['label']}.",
                "severity": "blocking",
            }
            for item in validation.get("missing_required_fields", [])
        ]
        if validation.get("money_value_count", 0) < 4 or validation.get("percent_only"):
            missing.append(
                {
                    "input_id": "finance_money_numbers",
                    "reason": "Finance review must include concrete money numbers, not only percentages.",
                    "severity": "blocking",
                }
            )
        if not validation.get("finance_lock_present"):
            missing.append(
                {
                    "input_id": "finance_publish_lock",
                    "reason": "Finance review must state whether publish is locked or ready for confirmation.",
                    "severity": "blocking",
                }
            )
        return self._dedupe(missing)

    def _present(self, normalized: str, field: FinanceCheck) -> bool:
        tokens = [field.field_id, field.label, *field.aliases]
        return any(self._normalize(token) in normalized for token in tokens)

    def _money_values(self, text: str) -> list[str]:
        return [match.group(0).strip() for match in self.MONEY_PATTERN.finditer(text)]

    def _finance_lock_present(self, normalized: str) -> bool:
        tokens = [
            "finance lock",
            "publish lock",
            "locked before confirmation",
            "ready for confirmation",
            "not ready for publish",
            "do not publish",
            "confirmation center",
            "发布锁",
            "确认中心",
        ]
        return any(self._normalize(token) in normalized for token in tokens)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()

    def _dedupe(self, items: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in items:
            input_id = item["input_id"]
            if input_id in seen:
                continue
            seen.add(input_id)
            deduped.append(item)
        return deduped

    def _summary(
        self,
        status: str,
        missing_required: list[dict[str, Any]],
        money_count: int,
        finance_lock_present: bool,
    ) -> str:
        if status == "ready_for_confirmation_review":
            return f"Finance review has {money_count} money value(s) and can move to confirmation review, not real publish."
        parts = []
        if missing_required:
            parts.append(f"{len(missing_required)} required field(s) missing")
        if money_count < 4:
            parts.append("too few concrete money numbers")
        if not finance_lock_present:
            parts.append("finance publish lock missing")
        return "Finance review is blocked: " + ", ".join(parts) + "."
