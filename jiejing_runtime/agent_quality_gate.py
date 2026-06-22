"""Quality gate for Jiejing-owned commerce Agent reports.

The owned Agent Team is allowed to draft, organize, and hand off work. It is
not allowed to silently become a live eBay operator. This gate reviews every
role report before SaaS screens, downstream roles, or Hermes comparisons use
it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .models import JiejingTask


HIGH_RISK_EXECUTION_KEYS = {
    "published_to_ebay",
    "procurement_paid",
    "refund_executed",
    "ad_budget_changed",
    "store_policy_changed",
    "tracking_written",
    "buyer_message_sent",
    "policy_edited",
    "oauth_scope_changed",
    "payment_charged",
}

REQUIRED_RUNTIME_CONTROLS = [
    "agent_team",
    "agent_role",
    "owned_agent_execution",
    "handoff_contract",
    "job_spec",
    "job_spec_compliance",
    "report_quality",
    "report_contract",
]

FORBIDDEN_TEXT_PATTERNS = {
    "claims_real_ebay_publish": r"\b(real\s+)?ebay\s+listing\s+(has\s+been\s+)?(published|posted|revised)\b",
    "claims_supplier_paid": r"\b(supplier|1688|procurement)\s+(has\s+been\s+)?(paid|ordered)\b",
    "claims_refund_executed": r"\b(refund|partial\s+refund|compensation)\s+(has\s+been\s+)?(executed|sent|approved)\b",
    "claims_ad_budget_changed": r"\b(ad|advertising|promoted\s+listing)\s+budget\s+(has\s+been\s+)?(changed|started|increased)\b",
    "claims_policy_edited": r"\b(fulfillment|payment|return|oauth|authorization)\s+policy\s+(has\s+been\s+)?(changed|edited|updated)\b",
    "guaranteed_sales_claim": r"\bguaranteed\s+(sales|orders|profit|ranking)\b",
}

TASKS_THAT_SHOULD_KEEP_PENDING_VISIBLE = {
    "source.match",
    "listing.package",
    "asset.brief",
    "finance.review",
    "confirmation.package",
}


@dataclass(slots=True)
class QualityCheck:
    key: str
    label: str
    passed: bool
    severity: str = "error"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "pass": self.passed,
            "severity": self.severity,
            "detail": self.detail,
        }


class OwnedAgentQualityGate:
    """Reviews owned Agent reports for contract, source, and safety discipline."""

    name = "jiejing-owned-agent-quality-gate"
    version = "2026-05-15.1"

    def review_report(self, task: JiejingTask, report: dict[str, Any]) -> dict[str, Any]:
        checks = [
            self._check_report_object(report),
            self._check_required_sections(task, report),
            self._check_runtime_controls(report),
            self._check_execution_flags(report),
            self._check_handoff_boundary(report),
            self._check_source_discipline(task, report),
            self._check_pending_visibility(task, report),
            self._check_forbidden_text(report),
        ]
        blockers = [check for check in checks if not check.passed and check.severity == "error"]
        warnings = [check for check in checks if not check.passed and check.severity == "warning"]
        status = "pass"
        if blockers:
            status = "needs_repair"
        elif warnings:
            status = "needs_attention"
        score = self._score(checks)
        return {
            "gate": self.name,
            "gate_version": self.version,
            "task_type": task.task_type,
            "agent_role": str(report.get("agent_role") or ""),
            "status": status,
            "score": score,
            "checks": [check.to_dict() for check in checks],
            "blockers": [check.to_dict() for check in blockers],
            "warnings": [check.to_dict() for check in warnings],
            "safe_for_real_execution": False,
            "real_execution_allowed": False,
            "next_runtime_action": "handoff_allowed" if status == "pass" else "repair_report_before_handoff",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "required_runtime_controls": list(REQUIRED_RUNTIME_CONTROLS),
            "high_risk_execution_keys": sorted(HIGH_RISK_EXECUTION_KEYS),
            "forbidden_text_patterns": sorted(FORBIDDEN_TEXT_PATTERNS),
            "safe_for_real_execution": False,
        }

    def _check_report_object(self, report: dict[str, Any]) -> QualityCheck:
        return QualityCheck(
            "report_object",
            "Report is a structured object.",
            isinstance(report, dict),
            detail="SaaS modules need structured reports, not free-form text.",
        )

    def _check_required_sections(self, task: JiejingTask, report: dict[str, Any]) -> QualityCheck:
        sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
        required = [str(item) for item in task.output_contract.get("required_sections", [])]
        missing = [section for section in required if section not in sections or not self._has_content(sections.get(section))]
        return QualityCheck(
            "required_sections",
            "Required report sections are present and non-empty.",
            not missing,
            detail=", ".join(missing) if missing else f"{len(required)} sections checked.",
        )

    def _check_runtime_controls(self, report: dict[str, Any]) -> QualityCheck:
        missing = [key for key in REQUIRED_RUNTIME_CONTROLS if not report.get(key)]
        return QualityCheck(
            "runtime_controls",
            "Runtime controls are attached to the report.",
            not missing,
            detail=", ".join(missing) if missing else "Agent team, job spec, quality, handoff, and contract controls are attached.",
        )

    def _check_execution_flags(self, report: dict[str, Any]) -> QualityCheck:
        bad_paths = self._true_high_risk_paths(report)
        return QualityCheck(
            "execution_flags",
            "High-risk execution flags remain false.",
            not bad_paths,
            detail=", ".join(bad_paths) if bad_paths else "No real eBay, payment, refund, ad, policy, or buyer-message execution flag is true.",
        )

    def _check_handoff_boundary(self, report: dict[str, Any]) -> QualityCheck:
        handoff = report.get("handoff_contract") if isinstance(report.get("handoff_contract"), dict) else {}
        execution = report.get("owned_agent_execution") if isinstance(report.get("owned_agent_execution"), dict) else {}
        passed = handoff.get("real_execution_allowed") is False and execution.get("real_execution_allowed") is False
        return QualityCheck(
            "handoff_boundary",
            "Handoff blocks real execution.",
            passed,
            detail="handoff_contract and owned_agent_execution must both say real_execution_allowed=false.",
        )

    def _check_source_discipline(self, task: JiejingTask, report: dict[str, Any]) -> QualityCheck:
        serialized = self._serialize(report)
        overclaim_markers = [
            "production ready",
            "publish ready",
            "officially verified",
            "实时销量已确认",
            "真实销量已确认",
        ]
        found = [marker for marker in overclaim_markers if marker in serialized.lower()]
        # Confirmation packages can mention what becomes ready after approval, but
        # a role report should not assert publish-readiness while blockers remain.
        if task.task_type == "confirmation.package":
            found = [item for item in found if item not in {"publish ready"}]
        return QualityCheck(
            "source_discipline",
            "Report does not overstate source-backed certainty.",
            not found,
            "warning",
            detail=", ".join(found) if found else "Source-backed, pending, and inference language remain distinguishable.",
        )

    def _check_pending_visibility(self, task: JiejingTask, report: dict[str, Any]) -> QualityCheck:
        if task.task_type not in TASKS_THAT_SHOULD_KEEP_PENDING_VISIBLE:
            return QualityCheck(
                "pending_visibility",
                "Pending fact visibility checked.",
                True,
                "info",
                detail="This task type does not require a pending-facts marker.",
            )
        text = self._serialize(report).lower()
        has_pending = "pending" in text or "missing" in text or "blocked" in text or "缺" in text or "待" in text
        return QualityCheck(
            "pending_visibility",
            "Missing or pending facts stay visible.",
            has_pending,
            "warning",
            detail="Supplier, taxonomy, policy, logistics, media, or confirmation gaps should remain visible.",
        )

    def _check_forbidden_text(self, report: dict[str, Any]) -> QualityCheck:
        text = self._serialize(report).lower()
        found = [key for key, pattern in FORBIDDEN_TEXT_PATTERNS.items() if re.search(pattern, text)]
        return QualityCheck(
            "forbidden_claims",
            "Report does not claim forbidden real-world actions or guaranteed outcomes.",
            not found,
            detail=", ".join(found) if found else "No forbidden publish/payment/refund/ad/policy/guarantee claim found.",
        )

    def _true_high_risk_paths(self, value: Any, path: str = "report") -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in HIGH_RISK_EXECUTION_KEYS and child is True:
                    found.append(child_path)
                elif key == "real_execution_allowed" and child is True:
                    found.append(child_path)
                else:
                    found.extend(self._true_high_risk_paths(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                found.extend(self._true_high_risk_paths(child, f"{path}[{index}]"))
        return found

    def _score(self, checks: list[QualityCheck]) -> int:
        if not checks:
            return 0
        weights = {"error": 18, "warning": 8, "info": 3}
        total = sum(weights.get(check.severity, 10) for check in checks)
        lost = sum(weights.get(check.severity, 10) for check in checks if not check.passed)
        return max(0, min(100, round((total - lost) * 100 / total)))

    def _serialize(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    def _has_content(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True
