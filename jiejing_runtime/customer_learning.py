"""Customer-service learning package validation for Jiejing Runtime.

Customer service automation is only useful after the role receives a structured
product file. This validator keeps "AI customer service is ready" separate from
"the customer-service role has actually learned the product, FAQ, reply
boundary, and escalation rules".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CustomerLearningCheck:
    field_id: str
    label: str
    aliases: tuple[str, ...] = ()

    def to_dict(self, present: bool) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "present": present,
        }


class CustomerLearningValidator:
    """Validates a customer-service learning handoff before auto replies."""

    version = "0.1.0"

    REQUIRED_FIELDS = [
        CustomerLearningCheck(
            "product_service_file",
            "Product service file",
            aliases=("product file", "product facts", "product profile", "service file"),
        ),
        CustomerLearningCheck(
            "buyer_question_map",
            "Buyer question map",
            aliases=("buyer questions", "question map", "buyer concerns", "pre-sale questions"),
        ),
        CustomerLearningCheck("faq", "FAQ", aliases=("frequently asked", "q&a")),
        CustomerLearningCheck(
            "reply_boundary",
            "Reply boundary",
            aliases=("auto reply boundary", "reply limits", "do not promise", "safe reply boundary"),
        ),
        CustomerLearningCheck(
            "auto_reply_templates",
            "Auto reply templates",
            aliases=("reply templates", "message templates", "auto replies"),
        ),
        CustomerLearningCheck(
            "escalation_rules",
            "Escalation rules",
            aliases=("human takeover", "manual takeover", "escalate", "handoff to human"),
        ),
    ]

    HIGH_RISK_TOPICS = [
        ("refund", "refund_or_compensation"),
        ("compensation", "refund_or_compensation"),
        ("guarantee", "guaranteed_promise"),
        ("guaranteed", "guaranteed_promise"),
        ("medical", "medical_or_therapeutic_claim"),
        ("therapeutic", "medical_or_therapeutic_claim"),
        ("customs", "customs_or_tax_promise"),
        ("tax", "customs_or_tax_promise"),
        ("delivery date", "delivery_date_promise"),
        ("exact arrival", "delivery_date_promise"),
        ("negative feedback", "feedback_dispute"),
    ]

    def validate_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize(text)
        checks = [field.to_dict(self._present(normalized, field)) for field in self.REQUIRED_FIELDS]
        missing_required = [check for check in checks if not check["present"]]
        high_risk_rules = self._high_risk_rules(normalized)
        takeover_present = self._takeover_present(normalized)
        automation_claim_present = self._automation_claim_present(normalized)

        status = "ready_for_auto_reply_review"
        if missing_required:
            status = "blocked_incomplete_learning_package"
        if not takeover_present:
            status = "blocked_missing_human_takeover"
        if automation_claim_present and missing_required:
            status = "blocked_unsafe_auto_reply_claim"

        return {
            "validator": "customer-learning-validator",
            "validator_version": self.version,
            "status": status,
            "field_checks": checks,
            "missing_required_fields": missing_required,
            "human_takeover_present": takeover_present,
            "automation_claim_present": automation_claim_present,
            "high_risk_rules_detected": high_risk_rules,
            "summary": self._summary(status, missing_required, takeover_present, high_risk_rules),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        missing = [
            {
                "input_id": f"customer_learning_{item['field_id']}",
                "reason": f"Customer-service learning package is missing: {item['label']}.",
                "severity": "blocking",
            }
            for item in validation.get("missing_required_fields", [])
        ]
        if not validation.get("human_takeover_present"):
            missing.append(
                {
                    "input_id": "customer_service_human_takeover",
                    "reason": "Customer-service package must define when AI stops and a human takes over.",
                    "severity": "blocking",
                }
            )
        return self._dedupe(missing)

    def _present(self, normalized: str, field: CustomerLearningCheck) -> bool:
        tokens = [field.field_id, field.label, *field.aliases]
        return any(self._normalize(token) in normalized for token in tokens)

    def _takeover_present(self, normalized: str) -> bool:
        tokens = [
            "human takeover",
            "manual takeover",
            "handoff to human",
            "escalation rules",
            "escalate to merchant",
            "人工接管",
            "转人工",
        ]
        return any(self._normalize(token) in normalized for token in tokens)

    def _automation_claim_present(self, normalized: str) -> bool:
        tokens = [
            "auto reply ready",
            "fully automatic reply",
            "customer service is ready",
            "ready for automatic replies",
            "客服已学习",
            "自动客服已准备",
        ]
        return any(self._normalize(token) in normalized for token in tokens)

    def _high_risk_rules(self, normalized: str) -> list[dict[str, str]]:
        detected: list[dict[str, str]] = []
        for token, risk_id in self.HIGH_RISK_TOPICS:
            if token in normalized and risk_id not in {item["risk_id"] for item in detected}:
                detected.append(
                    {
                        "risk_id": risk_id,
                        "rule": "Topic must be gated by escalation rules or confirmation before sending.",
                    }
                )
        return detected

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
        takeover_present: bool,
        high_risk_rules: list[dict[str, str]],
    ) -> str:
        if status == "ready_for_auto_reply_review":
            return (
                "Customer-service package contains product file, FAQ, templates, "
                f"and human takeover rules; {len(high_risk_rules)} high-risk topic rule(s) detected."
            )
        parts = []
        if missing_required:
            parts.append(f"{len(missing_required)} required field(s) missing")
        if not takeover_present:
            parts.append("human takeover rule missing")
        return "Customer-service package is blocked: " + ", ".join(parts) + "."
