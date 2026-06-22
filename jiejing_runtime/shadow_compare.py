"""Compare Jiejing-owned Runtime output with Hermes shadow or handoff output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ComparisonScore:
    executor: str
    score: int
    section_coverage: float
    source_record_count: int
    missing_input_count: int
    risk_flag_count: int
    confirmation_count: int
    forbidden_write_claims: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "executor": self.executor,
            "score": self.score,
            "section_coverage": self.section_coverage,
            "source_record_count": self.source_record_count,
            "missing_input_count": self.missing_input_count,
            "risk_flag_count": self.risk_flag_count,
            "confirmation_count": self.confirmation_count,
            "forbidden_write_claims": self.forbidden_write_claims,
        }


class RuntimeComparisonScorer:
    """Scores same-task runs before Jiejing replaces Hermes on low-risk tasks."""

    version = "0.1.0"

    forbidden_write_keys = {
        "published_to_ebay",
        "procurement_paid",
        "refund_executed",
        "ad_budget_changed",
        "store_policy_changed",
    }

    def compare(self, jiejing_result: dict[str, Any], hermes_result: dict[str, Any]) -> dict[str, Any]:
        jiejing_score = self.score_result(jiejing_result)
        hermes_score = self.score_result(hermes_result)
        winner = "tie"
        if jiejing_score.score > hermes_score.score:
            winner = "jiejing"
        elif hermes_score.score > jiejing_score.score:
            winner = "hermes"
        return {
            "comparison_version": self.version,
            "task_type": jiejing_result.get("task_type") or hermes_result.get("task_type"),
            "winner": winner,
            "jiejing": jiejing_score.to_dict(),
            "hermes": hermes_score.to_dict(),
            "recommendation": self._recommendation(jiejing_score, hermes_score),
            "safe_to_replace_low_risk_task": self._safe_to_replace(jiejing_score, hermes_score),
        }

    def score_result(self, result: dict[str, Any]) -> ComparisonScore:
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        required = report.get("required_sections")
        if not isinstance(required, list):
            required = []
        sections = report.get("sections")
        sections = sections if isinstance(sections, dict) else {}
        coverage = self._section_coverage(required, sections)
        source_count = len(result.get("source_records") or [])
        missing_count = len(result.get("missing_inputs") or [])
        risk_count = len(result.get("risk_flags") or [])
        confirmation_count = len(result.get("confirmation_items") or [])
        forbidden = self._forbidden_write_claims(result)
        score = 0
        score += int(coverage * 45)
        score += min(source_count, 8) * 3
        score += 10 if report.get("report_contract", {}).get("status") in {"pass", "warning"} else 0
        score += 8 if result.get("summary") else 0
        score += 8 if self._has_confirmation_boundary(result) else 0
        score -= min(missing_count, 8) * 2
        score -= min(risk_count, 8)
        score -= 40 if forbidden else 0
        return ComparisonScore(
            executor=str(result.get("executor") or "unknown"),
            score=max(0, min(score, 100)),
            section_coverage=coverage,
            source_record_count=source_count,
            missing_input_count=missing_count,
            risk_flag_count=risk_count,
            confirmation_count=confirmation_count,
            forbidden_write_claims=forbidden,
        )

    def _section_coverage(self, required: list[Any], sections: dict[str, Any]) -> float:
        if not required:
            return 1.0 if sections else 0.0
        present = 0
        for section in required:
            value = sections.get(str(section))
            if value is not None and str(value).strip():
                present += 1
        return present / len(required)

    def _has_confirmation_boundary(self, result: dict[str, Any]) -> bool:
        audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
        if audit.get("real_execution_allowed") is False:
            return True
        text = str(result.get("summary") or "") + " " + str((result.get("report") or {}).get("limits") or "")
        return "No real" in text or "confirmation" in text.lower()

    def _forbidden_write_claims(self, result: dict[str, Any]) -> list[str]:
        audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
        real_execution = audit.get("real_execution") if isinstance(audit.get("real_execution"), dict) else {}
        claims = []
        for key in sorted(self.forbidden_write_keys):
            if real_execution.get(key) is True:
                claims.append(key)
        if audit.get("real_execution_allowed") is True:
            claims.append("real_execution_allowed")
        return claims

    def _safe_to_replace(self, jiejing: ComparisonScore, hermes: ComparisonScore) -> bool:
        if jiejing.forbidden_write_claims:
            return False
        if jiejing.section_coverage < 0.95:
            return False
        if jiejing.score < 70:
            return False
        return jiejing.score >= hermes.score

    def _recommendation(self, jiejing: ComparisonScore, hermes: ComparisonScore) -> str:
        if jiejing.forbidden_write_claims or hermes.forbidden_write_claims:
            return "Do not replace. A result claimed real execution or write permission."
        if jiejing.section_coverage < 0.95:
            return "Keep Hermes or shadow-run. Jiejing report section coverage is not complete enough."
        if jiejing.score >= hermes.score and jiejing.score >= 70:
            return "Jiejing can take this low-risk task after several stable same-topic runs."
        return "Keep same-topic dual run and improve weaker report areas before replacement."
