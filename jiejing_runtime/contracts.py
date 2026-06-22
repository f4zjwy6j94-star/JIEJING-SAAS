"""Result contract checks for Jiejing Agent Runtime."""

from __future__ import annotations

from typing import Any

from .models import ALLOWED_STATUSES, JiejingTask, RuntimeIssue
from .policies import TASK_CONFIRMATION_ACTIONS
from .report_contracts import validate_role_report_contract


REQUIRED_RESULT_FIELDS = {
    "task_id",
    "task_type",
    "task_version",
    "status",
    "executor",
    "summary",
    "report",
    "source_records",
    "missing_inputs",
    "risk_flags",
    "confirmation_items",
    "next_tasks",
    "artifacts",
    "audit",
}


class ResultContractValidator:
    """Checks whether an adapter returned a usable JiejingTaskResult."""

    def validate(self, task: JiejingTask, result: dict[str, Any]) -> list[RuntimeIssue]:
        issues: list[RuntimeIssue] = []
        missing = sorted(REQUIRED_RESULT_FIELDS - set(result))
        if missing:
            issues.append(RuntimeIssue("result_missing_fields", "Result missing fields: " + ", ".join(missing)))

        if result.get("task_id") != task.task_id:
            issues.append(RuntimeIssue("result_task_id_mismatch", f"Result task_id does not match task_id: {task.task_id}"))
        if result.get("task_type") != task.task_type:
            issues.append(RuntimeIssue("result_task_type_mismatch", f"Result task_type does not match: {task.task_type}"))

        status = result.get("status")
        if status not in ALLOWED_STATUSES:
            issues.append(RuntimeIssue("result_unknown_status", f"Unknown result status: {status}"))

        if not str(result.get("summary", "")).strip():
            issues.append(RuntimeIssue("result_empty_summary", "Result summary is empty."))

        if not isinstance(result.get("report"), dict):
            issues.append(RuntimeIssue("result_report_not_object", "Result report must be an object."))

        source_records = result.get("source_records")
        if not isinstance(source_records, list) or not source_records:
            issues.append(RuntimeIssue("result_missing_source_records", "Result must include at least one source record."))

        for field_name in ["missing_inputs", "risk_flags", "confirmation_items", "next_tasks", "artifacts"]:
            if not isinstance(result.get(field_name), list):
                issues.append(RuntimeIssue("result_list_field_invalid", f"{field_name} must be a list."))

        issues.extend(self._validate_output_contract(task, result))
        issues.extend(self._validate_confirmation_contract(task, result))
        return issues

    def _validate_output_contract(self, task: JiejingTask, result: dict[str, Any]) -> list[RuntimeIssue]:
        issues: list[RuntimeIssue] = []
        contract = task.output_contract
        if contract.get("empty_output_allowed") is False and not str(result.get("summary", "")).strip():
            issues.append(RuntimeIssue("contract_empty_output", "Task contract does not allow empty output."))

        required_sections = contract.get("required_sections", [])
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        returned_sections = report.get("required_sections", [])
        if required_sections and isinstance(returned_sections, list):
            missing_sections = sorted(set(required_sections) - set(returned_sections))
            if missing_sections:
                issues.append(
                    RuntimeIssue(
                        "contract_missing_sections",
                        "Adapter did not acknowledge required sections: " + ", ".join(missing_sections),
                        "warning",
                    )
                )
        elif required_sections:
            issues.append(RuntimeIssue("contract_sections_not_acknowledged", "Adapter did not acknowledge required sections.", "warning"))
        report_contract = validate_role_report_contract(task, report)
        if report_contract.get("status") != "ready":
            issues.append(
                RuntimeIssue(
                    "report_contract_not_ready",
                    report_contract.get("summary", "Report contract is not ready."),
                    "error",
                )
            )
        return issues

    def _validate_confirmation_contract(self, task: JiejingTask, result: dict[str, Any]) -> list[RuntimeIssue]:
        expected_actions = set(TASK_CONFIRMATION_ACTIONS.get(task.task_type, []))
        if not expected_actions:
            return []
        items = result.get("confirmation_items", [])
        if not isinstance(items, list):
            return [RuntimeIssue("confirmation_items_invalid", "confirmation_items must be a list.")]
        actual_actions = {str(item.get("action_type")) for item in items if isinstance(item, dict)}
        missing_actions = sorted(expected_actions - actual_actions)
        if missing_actions:
            return [
                RuntimeIssue(
                    "confirmation_actions_missing",
                    "Missing confirmation actions: " + ", ".join(missing_actions),
                    "warning",
                )
            ]
        return []
