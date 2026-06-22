"""Core data helpers for the Jiejing Agent Runtime MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


ALLOWED_TASK_TYPES = {
    "ceo.intake",
    "market.data_packet",
    "market.report",
    "source.match",
    "listing.package",
    "asset.brief",
    "customer.learn_product",
    "finance.review",
    "confirmation.package",
    "ceo.final_report",
    "owner.review",
}

ALLOWED_STATUSES = {
    "queued",
    "running",
    "success",
    "partial_success",
    "blocked_missing_input",
    "blocked_permission",
    "failed_timeout",
    "failed_tool",
    "failed_policy",
    "blocked_confirmation_required",
    "cancelled",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


@dataclass(slots=True)
class JiejingTask:
    raw: dict[str, Any]

    @property
    def task_id(self) -> str:
        return str(self.raw.get("task_id", ""))

    @property
    def task_type(self) -> str:
        return str(self.raw.get("task_type", ""))

    @property
    def task_version(self) -> str:
        return str(self.raw.get("task_version", ""))

    @property
    def input(self) -> dict[str, Any]:
        value = self.raw.get("input", {})
        return value if isinstance(value, dict) else {}

    @property
    def context(self) -> dict[str, Any]:
        value = self.raw.get("context", {})
        return value if isinstance(value, dict) else {}

    @property
    def risk_policy(self) -> dict[str, Any]:
        value = self.raw.get("risk_policy", {})
        return value if isinstance(value, dict) else {}

    @property
    def output_contract(self) -> dict[str, Any]:
        value = self.raw.get("output_contract", {})
        return value if isinstance(value, dict) else {}

    @property
    def timeout_seconds(self) -> int:
        value = self.raw.get("timeout_seconds", 180)
        return value if isinstance(value, int) else 180


@dataclass(slots=True)
class RuntimeIssue:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(slots=True)
class RuntimeAuditEvent:
    event_type: str
    task_id: str | None
    message: str
    created_at: str = field(default_factory=now_iso)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "task_id": self.task_id,
            "message": self.message,
            "created_at": self.created_at,
            "details": self.details,
        }


def validate_task_core(task: JiejingTask) -> list[RuntimeIssue]:
    issues: list[RuntimeIssue] = []
    required = [
        "task_id",
        "task_type",
        "task_version",
        "user_id",
        "company_id",
        "store_id",
        "platform",
        "stage",
        "input",
        "timeout_seconds",
        "retry_policy",
    ]
    for field_name in required:
        if field_name not in task.raw:
            issues.append(RuntimeIssue("missing_field", f"Missing field: {field_name}"))

    if task.task_type not in ALLOWED_TASK_TYPES:
        issues.append(RuntimeIssue("unknown_task_type", f"Unknown task_type: {task.task_type}"))

    if not isinstance(task.raw.get("input"), dict):
        issues.append(RuntimeIssue("input_not_object", "Task input must be an object."))

    retry_policy = task.raw.get("retry_policy")
    if not isinstance(retry_policy, dict):
        issues.append(RuntimeIssue("retry_policy_not_object", "retry_policy must be an object."))
    else:
        if "max_retries" not in retry_policy:
            issues.append(RuntimeIssue("retry_missing_max_retries", "retry_policy.max_retries is required."))
        if "split_on_timeout" not in retry_policy:
            issues.append(RuntimeIssue("retry_missing_split_on_timeout", "retry_policy.split_on_timeout is required."))

    return issues
