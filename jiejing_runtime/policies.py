"""Safety and confirmation policies for Jiejing Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import JiejingTask, RuntimeIssue


HIGH_RISK_ACTIONS = {
    "oauth_scope_change",
    "publish_listing",
    "bulk_publish_listing",
    "change_price",
    "change_inventory",
    "ad_budget",
    "refund",
    "partial_refund",
    "procurement_payment",
    "cleanup_test_listing",
    "address_write",
    "policy_edit",
    "store_subscription",
    "sensitive_buyer_commitment",
}

FORBIDDEN_REAL_EXECUTION_FLAGS = {
    "published_to_ebay",
    "procurement_paid",
    "refund_executed",
    "ad_budget_changed",
    "store_policy_changed",
}

TASK_CONFIRMATION_ACTIONS = {
    "source.match": ["procurement_payment"],
    "listing.package": ["publish_listing", "policy_edit"],
    "finance.review": ["change_price"],
    "confirmation.package": [
        "publish_listing",
        "change_price",
        "procurement_payment",
        "policy_edit",
        "sensitive_buyer_commitment",
    ],
}

ACTION_TITLES = {
    "oauth_scope_change": "Confirm account authorization change",
    "publish_listing": "Confirm real eBay publish",
    "bulk_publish_listing": "Confirm bulk eBay publish",
    "change_price": "Confirm price strategy",
    "change_inventory": "Confirm inventory change",
    "ad_budget": "Confirm ad budget",
    "refund": "Confirm refund",
    "partial_refund": "Confirm partial refund",
    "procurement_payment": "Confirm supplier payment",
    "cleanup_test_listing": "Confirm test listing cleanup",
    "address_write": "Confirm address write",
    "policy_edit": "Confirm store policy use or edit",
    "store_subscription": "Confirm store subscription",
    "sensitive_buyer_commitment": "Confirm sensitive buyer commitment",
}


@dataclass(slots=True)
class SafetyGate:
    """Blocks real-world actions and ensures high-risk actions are confirmable."""

    demo_mode: bool = True

    def validate_task_policy(self, task: JiejingTask) -> list[RuntimeIssue]:
        issues: list[RuntimeIssue] = []
        risk_policy = task.risk_policy
        required_actions = set(risk_policy.get("confirmation_required_actions", []))
        missing = sorted(HIGH_RISK_ACTIONS - required_actions)
        if missing:
            issues.append(
                RuntimeIssue(
                    "risk_policy_incomplete",
                    "Task risk_policy is missing confirmation actions: " + ", ".join(missing),
                )
            )
        if risk_policy.get("default_action") != "hold":
            issues.append(RuntimeIssue("risk_policy_not_hold", "risk_policy.default_action must be hold."))
        return issues

    def validate_result(self, result: dict[str, Any]) -> list[RuntimeIssue]:
        issues: list[RuntimeIssue] = []
        real_execution = result.get("audit", {}).get("real_execution", {})
        if not isinstance(real_execution, dict):
            real_execution = {}
        for flag in FORBIDDEN_REAL_EXECUTION_FLAGS:
            if real_execution.get(flag):
                issues.append(RuntimeIssue("forbidden_real_execution", f"Result claims real execution: {flag}"))
        if self.demo_mode and result.get("audit", {}).get("real_execution_allowed") is True:
            issues.append(RuntimeIssue("demo_mode_real_execution", "Demo mode cannot allow real execution."))
        return issues


class ConfirmationCenter:
    """Builds merchant-facing confirmation items from task type and risk policy."""

    def build_for_task(self, task: JiejingTask) -> list[dict[str, Any]]:
        actions = TASK_CONFIRMATION_ACTIONS.get(task.task_type, [])
        items = []
        for action in actions:
            items.append(
                {
                    "confirmation_id": f"confirm_{task.task_id.replace(':', '_').replace('.', '_')}_{action}",
                    "action_type": action,
                    "title": ACTION_TITLES.get(action, action),
                    "reason": self._reason_for(action),
                    "default_action": "hold",
                    "options": ["approve", "edit", "reject"],
                    "source_task_ids": [task.task_id],
                }
            )
        return items

    def _reason_for(self, action: str) -> str:
        if action == "publish_listing":
            return "Publishing creates a live eBay listing and must be confirmed by the merchant."
        if action == "policy_edit":
            return "Shipping, payment, and return policies affect fees, delivery promises, and buyer expectations."
        if action == "procurement_payment":
            return "Supplier payment and fulfillment route must not be executed without merchant approval."
        if action == "cleanup_test_listing":
            return "Cleaning a live test listing changes eBay state and must be confirmed by the merchant."
        if action == "change_price":
            return "Price affects margin and conversion, so the merchant must confirm it."
        if action == "sensitive_buyer_commitment":
            return "Refunds, compensation, disputes, and sensitive commitments require human takeover."
        return "This is a high-risk action and must be held for merchant confirmation."
