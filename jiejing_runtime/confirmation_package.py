"""Confirmation package validation for Jiejing Runtime.

The confirmation package is the hard boundary between AI work and real
execution. It must separate safe automation from actions that require merchant
confirmation every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ConfirmationCheck:
    field_id: str
    label: str
    aliases: tuple[str, ...] = ()

    def to_dict(self, present: bool) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "present": present,
        }


class ConfirmationPackageValidator:
    """Validates confirmation-center handoff output."""

    version = "0.1.0"

    REQUIRED_FIELDS = [
        ConfirmationCheck("allowed_auto_actions", "Allowed auto actions", aliases=("safe auto actions",)),
        ConfirmationCheck("default_rule_actions", "Default rule actions", aliases=("saved default rules",)),
        ConfirmationCheck("every_time_confirm_actions", "Every time confirm actions", aliases=("always confirm", "manual confirmation")),
        ConfirmationCheck("blocked_actions", "Blocked actions", aliases=("never auto", "forbidden actions")),
        ConfirmationCheck("missing_facts", "Missing facts", aliases=("missing inputs", "stop conditions")),
    ]

    HIGH_RISK_ACTIONS = [
        ("publish listing", ("publish", "listing")),
        ("batch publish", ("batch publish",)),
        ("procurement payment", ("procurement payment", "purchase payment", "pay supplier")),
        ("refund", ("refund", "partial refund")),
        ("ad budget", ("ad budget", "advertising budget", "promoted listing")),
        ("price change", ("price change", "change price", "modify price")),
        ("inventory change", ("inventory change", "change stock", "modify inventory")),
        ("store policy change", ("policy change", "fulfillment policy", "payment policy", "return policy")),
        ("store subscription", ("store subscription", "subscription change")),
        ("oauth authorization", ("oauth", "authorization", "token scope")),
        ("sensitive customer promise", ("compensation", "guarantee", "customs", "exact delivery date")),
    ]

    GATE_WORDS = (
        "confirm",
        "confirmation",
        "manual",
        "human",
        "blocked",
        "never auto",
        "do not auto",
        "every time",
        "approval",
        "确认",
        "人工",
        "禁止",
        "不自动",
    )

    def validate_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize(text)
        checks = [field.to_dict(self._present(normalized, field)) for field in self.REQUIRED_FIELDS]
        missing_required = [check for check in checks if not check["present"]]
        high_risk_coverage = self._high_risk_coverage(normalized)
        uncovered = [item for item in high_risk_coverage if not item["covered"]]
        status = "ready_for_confirmation_center"
        if missing_required:
            status = "blocked_missing_confirmation_sections"
        if uncovered:
            status = "blocked_high_risk_confirmation_gap"
        return {
            "validator": "confirmation-package-validator",
            "validator_version": self.version,
            "status": status,
            "field_checks": checks,
            "missing_required_fields": missing_required,
            "high_risk_coverage": high_risk_coverage,
            "uncovered_high_risk_actions": uncovered,
            "summary": self._summary(status, missing_required, uncovered),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        missing = [
            {
                "input_id": f"confirmation_field_{item['field_id']}",
                "reason": f"Confirmation package is missing required field: {item['label']}.",
                "severity": "blocking",
            }
            for item in validation.get("missing_required_fields", [])
        ]
        for item in validation.get("uncovered_high_risk_actions", []):
            missing.append(
                {
                    "input_id": f"confirmation_gate_{self._safe_id(item['action'])}",
                    "reason": f"High-risk action must be explicitly confirmation-gated: {item['action']}.",
                    "severity": "blocking",
                }
            )
        return self._dedupe(missing)

    def _present(self, normalized: str, field: ConfirmationCheck) -> bool:
        tokens = [field.field_id, field.label, *field.aliases]
        return any(self._normalize(token) in normalized for token in tokens)

    def _high_risk_coverage(self, normalized: str) -> list[dict[str, Any]]:
        coverage: list[dict[str, Any]] = []
        for action, tokens in self.HIGH_RISK_ACTIONS:
            token_hits = [token for token in tokens if self._normalize(token) in normalized]
            if not token_hits:
                coverage.append({"action": action, "mentioned": False, "covered": False})
                continue
            covered = any(self._window_has_gate_word(normalized, self._normalize(token)) for token in token_hits)
            coverage.append({"action": action, "mentioned": True, "covered": covered})
        return coverage

    def _window_has_gate_word(self, normalized: str, token: str) -> bool:
        search_from = 0
        while True:
            index = normalized.find(token, search_from)
            if index < 0:
                return False
            start = max(0, index - 160)
            end = min(len(normalized), index + len(token) + 160)
            window = normalized[start:end]
            if any(self._normalize(word) in window for word in self.GATE_WORDS):
                return True
            search_from = index + len(token)

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().replace("_", " ")).strip()

    def _safe_id(self, value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_") or "action"

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
        uncovered: list[dict[str, Any]],
    ) -> str:
        if status == "ready_for_confirmation_center":
            return "Confirmation package separates auto actions, default rules, every-time confirmations, blocked actions, and missing facts."
        parts = []
        if missing_required:
            parts.append(f"{len(missing_required)} required section(s) missing")
        if uncovered:
            parts.append(f"{len(uncovered)} high-risk action(s) not explicitly gated")
        return "Confirmation package is blocked: " + ", ".join(parts) + "."
