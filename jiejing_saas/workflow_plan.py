"""Product workflow step plan for the SaaS backend.

The Runtime already has task contracts. The SaaS backend also needs its own
step table so users, support, retries, queues, and audits can see where a
workflow is waiting without reading Runtime internals.
"""

from __future__ import annotations

from typing import Any

from jiejing_runtime.workflow_templates import WORKFLOW_STEPS


ROLE_LABELS = {
    "ceo.intake": ("ai_ceo", "AI CEO 接目标"),
    "market.data_packet": ("market_manager", "市场数据包"),
    "market.report": ("market_manager", "市场经理报告"),
    "source.match": ("sourcing_manager", "货源事实核对"),
    "listing.package": ("product_manager", "产品经理刊登包"),
    "asset.brief": ("asset_manager", "素材任务包"),
    "customer.learn_product": ("customer_service", "客服学习商品"),
    "finance.review": ("finance_risk", "财务与履约复核"),
    "confirmation.package": ("confirmation_center", "确认中心打包"),
    "ceo.final_report": ("ai_ceo", "AI CEO 汇总"),
    "owner.review": ("owner_review", "主理人复盘"),
}

STEP_PROVIDER_JOBS = {
    "market.data_packet": ["public_search.market_research", "ebay.read_only_snapshot"],
    "market.report": ["model.role_report_assist"],
    "source.match": ["sourcing.1688_availability"],
    "listing.package": ["ebay.read_only_snapshot", "model.role_report_assist"],
    "asset.brief": ["media.asset_generation"],
    "customer.learn_product": ["ebay.read_only_snapshot", "model.role_report_assist"],
    "finance.review": ["logistics.orange_connex_quote", "model.role_report_assist"],
    "confirmation.package": ["logistics.orange_connex_quote"],
    "ceo.final_report": ["model.role_report_assist"],
}


def product_workflow_steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, (task_type, parent_type, timeout, description, sections, expected_status) in enumerate(WORKFLOW_STEPS, start=1):
        role_key, label = ROLE_LABELS.get(task_type, ("runtime_agent", task_type))
        steps.append(
            {
                "step_order": index,
                "task_type": task_type,
                "depends_on_task_type": parent_type,
                "role_key": role_key,
                "merchant_label": label,
                "description": description,
                "expected_status": expected_status,
                "timeout_seconds": timeout,
                "required_sections": list(sections),
                "provider_job_keys": list(STEP_PROVIDER_JOBS.get(task_type, [])),
                "retry_policy": {
                    "max_attempts": 2,
                    "split_on_timeout": True,
                    "surface_failure_to_user": True,
                },
            }
        )
    return steps


def step_status_from_runtime(status: str) -> str:
    if status in {"success", "partial_success"}:
        return "completed"
    if status in {"blocked_missing_input", "blocked_confirmation_required", "blocked_permission"}:
        return "waiting"
    if status == "failed_policy":
        return "waiting"
    if str(status).startswith("failed"):
        return "failed"
    if status == "cancelled":
        return "cancelled"
    return "completed" if status else "unknown"
