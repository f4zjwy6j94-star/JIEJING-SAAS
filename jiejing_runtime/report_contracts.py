"""Role report contracts for Jiejing Runtime.

The model can write text, but Runtime owns the shape. Every role report must
return the requested sections under `report.sections` so SaaS screens,
confirmations, and handoffs can read the output without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import JiejingTask


CONTRACT_VERSION = "2026-05-14"


TASK_REPORT_LABELS = {
    "ceo.intake": "AI CEO intake contract",
    "market.data_packet": "Market data packet contract",
    "market.report": "Market manager report contract",
    "source.match": "Source and fulfillment fact contract",
    "listing.package": "eBay listing package contract",
    "asset.brief": "Asset workshop brief contract",
    "customer.learn_product": "Customer service learning contract",
    "finance.review": "Finance and fulfillment review contract",
    "confirmation.package": "Confirmation center package contract",
    "ceo.final_report": "AI CEO final report contract",
    "owner.review": "Owner review contract",
}


@dataclass(slots=True)
class ReportContractStatus:
    status: str
    required_sections: list[str]
    present_sections: list[str]
    missing_sections: list[str]
    empty_sections: list[str]
    missing_report_fields: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": TASK_REPORT_LABELS.get("unknown", "Role report contract"),
            "contract_version": CONTRACT_VERSION,
            "status": self.status,
            "required_sections": self.required_sections,
            "present_sections": self.present_sections,
            "missing_sections": self.missing_sections,
            "empty_sections": self.empty_sections,
            "missing_report_fields": self.missing_report_fields,
            "summary": self.summary,
        }


class RoleReportContractValidator:
    """Validates the report object returned by an adapter or model client."""

    version = CONTRACT_VERSION

    def validate(self, task: JiejingTask, report: dict[str, Any]) -> dict[str, Any]:
        required_sections = [str(item) for item in task.output_contract.get("required_sections", [])]
        missing_report_fields: list[str] = []
        if not isinstance(report, dict):
            return self._status("blocked_report_not_object", required_sections, [], required_sections, [], ["report"], task)
        if not str(report.get("merchant_readable_summary") or report.get("summary") or "").strip():
            missing_report_fields.append("merchant_readable_summary")
        if "required_sections" not in report:
            missing_report_fields.append("required_sections")
        sections = report.get("sections")
        if not isinstance(sections, dict):
            missing_report_fields.append("sections")
            sections = {}

        present_sections = sorted(str(key) for key in sections)
        missing_sections = sorted(section for section in required_sections if section not in sections)
        empty_sections = sorted(
            section
            for section in required_sections
            if section in sections and not self._has_content(sections.get(section))
        )
        status = "ready"
        if missing_report_fields or missing_sections:
            status = "blocked_missing_report_contract"
        elif empty_sections:
            status = "blocked_empty_report_sections"
        return self._status(status, required_sections, present_sections, missing_sections, empty_sections, missing_report_fields, task)

    def _status(
        self,
        status: str,
        required_sections: list[str],
        present_sections: list[str],
        missing_sections: list[str],
        empty_sections: list[str],
        missing_report_fields: list[str],
        task: JiejingTask,
    ) -> dict[str, Any]:
        blocked = sorted(set(missing_sections + empty_sections + missing_report_fields))
        if status == "ready":
            summary = f"{TASK_REPORT_LABELS.get(task.task_type, 'Role report')} is ready with {len(required_sections)} sections."
        else:
            summary = "Report contract is not ready: " + ", ".join(blocked)
        return {
            "contract": TASK_REPORT_LABELS.get(task.task_type, "Role report contract"),
            "contract_version": self.version,
            "status": status,
            "required_sections": required_sections,
            "present_sections": present_sections,
            "missing_sections": missing_sections,
            "empty_sections": empty_sections,
            "missing_report_fields": missing_report_fields,
            "summary": summary,
        }

    def _has_content(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return True
        return True


def validate_role_report_contract(task: JiejingTask, report: dict[str, Any]) -> dict[str, Any]:
    return RoleReportContractValidator().validate(task, report)
