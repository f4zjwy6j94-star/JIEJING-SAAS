"""AI CEO final report validation for Jiejing Runtime.

The final CEO report should translate role outputs into merchant-facing status:
what is ready, what is blocked, what source confidence is, whether publish is
locked, and the next smallest action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CeoFinalCheck:
    field_id: str
    label: str
    aliases: tuple[str, ...] = ()

    def to_dict(self, present: bool) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "present": present,
        }


class CeoFinalReportValidator:
    """Validates final AI CEO report before showing the merchant summary."""

    version = "0.1.0"

    REQUIRED_FIELDS = [
        CeoFinalCheck("current_status", "Current status", aliases=("status now", "where we are")),
        CeoFinalCheck("source_health", "Source health", aliases=("source confidence", "data health")),
        CeoFinalCheck("reports_ready", "Reports ready", aliases=("report readiness", "role reports")),
        CeoFinalCheck("publish_lock", "Publish lock", aliases=("publish blocked", "not ready to publish")),
        CeoFinalCheck("next_minimum_action", "Next minimum action", aliases=("next action", "what to do next")),
    ]

    ROLE_REPORTS = [
        ("market_report", ("market report", "market manager")),
        ("source_facts", ("source facts", "supplier facts", "source match")),
        ("listing_package", ("listing package", "product manager")),
        ("asset_manifest", ("asset manifest", "asset brief", "asset manager")),
        ("customer_learning", ("customer learning", "customer service")),
        ("finance_review", ("finance review", "finance manager")),
        ("confirmation_package", ("confirmation package", "confirmation center")),
    ]

    def validate_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize(text)
        checks = [field.to_dict(self._present(normalized, field)) for field in self.REQUIRED_FIELDS]
        missing_required = [check for check in checks if not check["present"]]
        role_coverage = self._role_coverage(normalized)
        missing_roles = [item for item in role_coverage if not item["present"]]
        publish_lock_present = self._present(normalized, CeoFinalCheck("publish_lock", "Publish lock", aliases=("do not publish", "confirmation center")))
        next_action_quality = self._next_action_quality(normalized)
        status = "ready_for_merchant_summary"
        if missing_required:
            status = "blocked_missing_ceo_summary_fields"
        if not publish_lock_present:
            status = "blocked_missing_publish_lock"
        if not next_action_quality:
            status = "blocked_unclear_next_action"
        return {
            "validator": "ceo-final-report-validator",
            "validator_version": self.version,
            "status": status,
            "field_checks": checks,
            "missing_required_fields": missing_required,
            "role_report_coverage": role_coverage,
            "missing_role_reports": missing_roles,
            "publish_lock_present": publish_lock_present,
            "next_action_quality": next_action_quality,
            "summary": self._summary(status, missing_required, missing_roles, next_action_quality),
        }

    def missing_inputs_from_validation(self, validation: dict[str, Any]) -> list[dict[str, str]]:
        missing = [
            {
                "input_id": f"ceo_final_{item['field_id']}",
                "reason": f"AI CEO final report is missing: {item['label']}.",
                "severity": "blocking",
            }
            for item in validation.get("missing_required_fields", [])
        ]
        if not validation.get("publish_lock_present"):
            missing.append(
                {
                    "input_id": "ceo_final_publish_lock",
                    "reason": "AI CEO final report must clearly state whether real publish is locked.",
                    "severity": "blocking",
                }
            )
        if not validation.get("next_action_quality"):
            missing.append(
                {
                    "input_id": "ceo_final_next_action",
                    "reason": "AI CEO final report must give one concrete next minimum action.",
                    "severity": "blocking",
                }
            )
        return self._dedupe(missing)

    def _present(self, normalized: str, field: CeoFinalCheck) -> bool:
        tokens = [field.field_id, field.label, *field.aliases]
        return any(self._normalize(token) in normalized for token in tokens)

    def _role_coverage(self, normalized: str) -> list[dict[str, Any]]:
        coverage = []
        for role_id, tokens in self.ROLE_REPORTS:
            coverage.append(
                {
                    "role_report": role_id,
                    "present": any(self._normalize(token) in normalized for token in tokens),
                }
            )
        return coverage

    def _next_action_quality(self, normalized: str) -> bool:
        action_tokens = ["next minimum action", "next action", "do next", "补", "确认", "上传", "授权", "publish lock"]
        has_action = any(self._normalize(token) in normalized for token in action_tokens)
        vague_bad = any(token in normalized for token in ["continue optimizing", "looks good", "all done", "keep watching"])
        return has_action and not vague_bad

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
        missing_roles: list[dict[str, Any]],
        next_action_quality: bool,
    ) -> str:
        if status == "ready_for_merchant_summary":
            return "AI CEO final report can be shown to merchant as the current workflow summary."
        parts = []
        if missing_required:
            parts.append(f"{len(missing_required)} required field(s) missing")
        if missing_roles:
            parts.append(f"{len(missing_roles)} role report reference(s) not mentioned")
        if not next_action_quality:
            parts.append("next action is unclear")
        return "AI CEO final report is blocked: " + ", ".join(parts) + "."
