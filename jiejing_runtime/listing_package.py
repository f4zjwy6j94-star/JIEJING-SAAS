"""Listing package validation for Jiejing Runtime.

This checks whether a product-manager listing report contains the fixed eBay
listing skeleton and the blocking facts needed before any real publish path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ListingFieldCheck:
    field_id: str
    label: str
    required: bool = True
    aliases: tuple[str, ...] = ()

    def to_dict(self, present: bool) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "required": self.required,
            "present": present,
        }


class ListingPackageValidator:
    """Validates product-manager output against the Jiejing/eBay draft contract."""

    version = "0.1.0"

    FIXED_FIELDS = [
        ListingFieldCheck("sku", "SKU", aliases=("custom label",)),
        ListingFieldCheck("title", "Title", aliases=("80 characters", "80-character")),
        ListingFieldCheck("category_id", "Category ID", aliases=("category", "category id")),
        ListingFieldCheck("condition", "Condition"),
        ListingFieldCheck("format", "Format", aliases=("fixed price",)),
        ListingFieldCheck("price", "Price"),
        ListingFieldCheck("quantity", "Quantity"),
        ListingFieldCheck("item_specifics", "Item Specifics", aliases=("aspects", "specifics")),
        ListingFieldCheck("pictures", "Pictures", aliases=("picture 1", "image", "photo")),
        ListingFieldCheck("video", "Video"),
        ListingFieldCheck("description_html", "Description HTML", aliases=("description", "html")),
        ListingFieldCheck("package_weight", "Package weight", aliases=("weight",)),
        ListingFieldCheck("package_dimensions", "Package dimensions", aliases=("dimensions",)),
        ListingFieldCheck("handling_time", "Handling time"),
        ListingFieldCheck("item_location", "Item Location", aliases=("ship from", "location")),
        ListingFieldCheck("fulfillment_policy", "Fulfillment policy", aliases=("shipping policy", "fulfillmentpolicyid")),
        ListingFieldCheck("payment_policy", "Payment policy", aliases=("paymentpolicyid",)),
        ListingFieldCheck("return_policy", "Return policy", aliases=("returnpolicyid",)),
        ListingFieldCheck("publish_blockers", "Publish blockers", aliases=("publish lock", "blocker", "missing inputs")),
    ]

    def validate_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize(text)
        checks = [field.to_dict(self._present(normalized, field)) for field in self.FIXED_FIELDS]
        missing_required = [check for check in checks if check["required"] and not check["present"]]
        title = self._extract_title(text)
        title_warnings = self._title_warnings(title)
        policy_warnings = self._policy_warnings(normalized)
        publish_lock_present = self._publish_lock_present(normalized)
        status = "ready_for_confirmation_review" if not missing_required and publish_lock_present else "blocked_missing_input"
        if title_warnings or policy_warnings:
            status = "blocked_missing_input"
        return {
            "validator": "listing-package-validator",
            "validator_version": self.version,
            "status": status,
            "fixed_field_checks": checks,
            "missing_required_fields": missing_required,
            "title": title,
            "title_warnings": title_warnings,
            "policy_warnings": policy_warnings,
            "publish_lock_present": publish_lock_present,
            "summary": self._summary(missing_required, title_warnings, policy_warnings, publish_lock_present),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        missing = [
            {
                "input_id": f"listing_field_{item['field_id']}",
                "reason": f"Listing package is missing required eBay draft field: {item['label']}.",
                "severity": "blocking",
            }
            for item in validation.get("missing_required_fields", [])
        ]
        for warning in validation.get("title_warnings", []):
            missing.append({"input_id": "listing_title_quality", "reason": warning, "severity": "blocking"})
        for warning in validation.get("policy_warnings", []):
            missing.append({"input_id": "business_policy_status", "reason": warning, "severity": "blocking"})
        if not validation.get("publish_lock_present"):
            missing.append(
                {
                    "input_id": "publish_lock",
                    "reason": "Listing package must explicitly say whether real publish is locked or ready for confirmation.",
                    "severity": "blocking",
                }
            )
        return missing

    def _present(self, normalized: str, field: ListingFieldCheck) -> bool:
        tokens = [field.field_id, field.label, *field.aliases]
        return any(self._contains_token(normalized, token) for token in tokens)

    def _contains_token(self, normalized: str, token: str) -> bool:
        token = self._normalize(token)
        if not token:
            return False
        return token in normalized

    def _extract_title(self, text: str) -> str:
        patterns = [
            r"(?im)^\s*(?:title|标题)\s*[:：]\s*(.+?)\s*$",
            r"(?im)^\s*(?:ebay\s+title)\s*[:：]\s*(.+?)\s*$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip().strip("`")
        return ""

    def _title_warnings(self, title: str) -> list[str]:
        if not title:
            return ["Title line was not detected."]
        warnings = []
        if len(title) > 80:
            warnings.append(f"Title is {len(title)} characters; eBay title must stay within 80 characters.")
        if len(title) < 20:
            warnings.append("Title is too short for a useful eBay listing draft.")
        return warnings

    def _policy_warnings(self, normalized: str) -> list[str]:
        warnings = []
        for label in ["fulfillment policy", "payment policy", "return policy"]:
            label_norm = self._normalize(label)
            window = self._window(normalized, label_norm, 90)
            if window and any(word in window for word in ["unknown", "pending", "missing", "待", "缺"]):
                warnings.append(f"{label} is present but still pending or missing.")
        return warnings

    def _publish_lock_present(self, normalized: str) -> bool:
        return any(token in normalized for token in ["publish lock", "publish blocker", "publish blockers", "发布阻断", "发布锁"])

    def _window(self, text: str, token: str, radius: int) -> str:
        index = text.find(token)
        if index < 0:
            return ""
        start = max(0, index - radius)
        end = min(len(text), index + len(token) + radius)
        return text[start:end]

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()

    def _summary(
        self,
        missing_required: list[dict[str, Any]],
        title_warnings: list[str],
        policy_warnings: list[str],
        publish_lock_present: bool,
    ) -> str:
        if not missing_required and not title_warnings and not policy_warnings and publish_lock_present:
            return "Listing package contains the fixed eBay draft skeleton and can move to confirmation review, not real publish."
        parts = []
        if missing_required:
            parts.append(f"{len(missing_required)} required field(s) missing")
        if title_warnings:
            parts.append("title issue")
        if policy_warnings:
            parts.append("business policy issue")
        if not publish_lock_present:
            parts.append("publish lock missing")
        return "Listing package is blocked: " + ", ".join(parts) + "."
