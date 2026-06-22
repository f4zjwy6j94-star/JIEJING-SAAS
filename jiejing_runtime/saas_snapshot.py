"""Frontend-safe SaaS snapshot for Jiejing Runtime runs.

The runtime result files are rich, but a merchant-facing SaaS screen should not
need to understand every internal field. This module folds a completed run into
stable module data for the AI CEO workspace, product listing, asset workshop,
customer service, finance review, and confirmation center.
"""

from __future__ import annotations

import json
import re
from typing import Any


SNAPSHOT_VERSION = "2026-05-14.1"

STANDARD_TASK_COUNT = 11

MODULES = [
    {
        "module_key": "cockpit",
        "label": "AI CEO workbench",
        "task_types": ["ceo.intake", "market.data_packet", "market.report"],
        "primary_task_type": "market.report",
        "next_action": "open_product_listing",
    },
    {
        "module_key": "source",
        "label": "Source and fulfillment facts",
        "task_types": ["source.match"],
        "primary_task_type": "source.match",
        "next_action": "open_product_listing",
    },
    {
        "module_key": "product_listing",
        "label": "Product listing",
        "task_types": ["listing.package"],
        "primary_task_type": "listing.package",
        "next_action": "open_asset_workshop",
    },
    {
        "module_key": "asset_workshop",
        "label": "Asset workshop",
        "task_types": ["asset.brief"],
        "primary_task_type": "asset.brief",
        "next_action": "open_customer_service",
    },
    {
        "module_key": "customer_service",
        "label": "Auto customer service",
        "task_types": ["customer.learn_product"],
        "primary_task_type": "customer.learn_product",
        "next_action": "open_finance_review",
    },
    {
        "module_key": "finance",
        "label": "Finance review",
        "task_types": ["finance.review"],
        "primary_task_type": "finance.review",
        "next_action": "open_confirmation_center",
    },
    {
        "module_key": "confirmation",
        "label": "Confirmation center",
        "task_types": ["confirmation.package"],
        "primary_task_type": "confirmation.package",
        "next_action": "merchant_confirm",
    },
    {
        "module_key": "ceo_final",
        "label": "AI CEO final report",
        "task_types": ["ceo.final_report", "owner.review"],
        "primary_task_type": "ceo.final_report",
        "next_action": "review_loop",
    },
]


def build_saas_snapshot(
    run: dict[str, Any] | None,
    results: list[dict[str, Any]],
    confirmations: list[dict[str, Any]],
    validation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a frontend-safe summary from repository records."""

    run = run or {}
    validation_summary = validation_summary or {}
    result_by_type = {str(result.get("task_type")): result for result in results}
    validations = validation_summary.get("validations", [])
    if not isinstance(validations, list):
        validations = []

    modules = [
        _module_snapshot(module, result_by_type, confirmations, validations)
        for module in MODULES
    ]
    owned_agent = _owned_agent_summary(results)
    confirmation_summary = _confirmation_summary(confirmations)
    readiness = _readiness_score(results, confirmations, validations, owned_agent)

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "run": {
            "run_id": _public_text(run.get("run_id") or ""),
            "adapter": _public_text(run.get("adapter") or ""),
            "run_status": _public_text(run.get("run_status") or ""),
            "task_count": int(run.get("task_count") or len(results)),
            "confirmation_item_count": int(run.get("confirmation_item_count") or len(confirmations)),
            "missing_input_count": int(run.get("missing_input_count") or _missing_input_count(results)),
            "generated_at": _public_text(run.get("generated_at") or ""),
        },
        "completion": {
            "standard_task_count": STANDARD_TASK_COUNT,
            "result_count": len(results),
            "result_coverage_percent": min(100, round(len(results) / STANDARD_TASK_COUNT * 100)) if STANDARD_TASK_COUNT else 0,
            "module_count": len(modules),
            "ready_module_count": len([item for item in modules if item["status"] in {"ready", "blocked_for_confirmation"}]),
            "blocked_module_count": len([item for item in modules if item["status"] == "blocked_missing_input"]),
        },
        "readiness": readiness,
        "owned_agent": owned_agent,
        "modules": modules,
        "handoff_chain": [
            {
                "from": modules[index]["module_key"],
                "to": modules[index + 1]["module_key"],
                "status": "connected"
                if modules[index]["has_result"] and modules[index + 1]["has_result"]
                else "pending",
            }
            for index in range(len(modules) - 1)
        ],
        "reports": {
            str(result.get("task_type")): _report_preview(result)
            for result in results
        },
        "confirmation_center": confirmation_summary,
        "safe_for_real_platform_write": False,
        "public_boundary": {
            "public_product_name": "Jiejing",
            "internal_runtime_hidden": True,
            "real_execution_requires_confirmation": True,
        },
    }


def _module_snapshot(
    module: dict[str, Any],
    result_by_type: dict[str, dict[str, Any]],
    confirmations: list[dict[str, Any]],
    validations: list[dict[str, Any]],
) -> dict[str, Any]:
    module_results = [result_by_type[task_type] for task_type in module["task_types"] if task_type in result_by_type]
    primary = result_by_type.get(module["primary_task_type"]) or (module_results[-1] if module_results else {})
    module_validations = [
        item for item in validations if str(item.get("task_type")) in set(module["task_types"])
    ]
    blocked_validations = [
        item for item in module_validations if _is_blocked_status(item.get("validation_status"))
    ]
    confirmation_count = sum(len(result.get("confirmation_items") or []) for result in module_results)
    missing_count = sum(len(result.get("missing_inputs") or []) for result in module_results)
    risk_count = sum(len(result.get("risk_flags") or []) for result in module_results)
    status = _module_status(primary, blocked_validations, confirmation_count, missing_count)
    return {
        "module_key": module["module_key"],
        "label": module["label"],
        "task_types": module["task_types"],
        "primary_task_type": module["primary_task_type"],
        "has_result": bool(primary),
        "status": status,
        "next_action": module["next_action"],
        "title": _public_text(_task_title(module["primary_task_type"])),
        "summary": _public_text(primary.get("summary") or _missing_summary(module["label"])),
        "result_status": _public_text(primary.get("status") or "pending"),
        "confirmation_count": confirmation_count,
        "missing_input_count": missing_count,
        "risk_count": risk_count,
        "validation_statuses": [
            {
                "validation_key": _public_text(item.get("validation_key") or ""),
                "status": _public_text(item.get("validation_status") or ""),
                "summary": _public_text(item.get("summary") or ""),
            }
            for item in module_validations
        ],
        "source_record_count": sum(len(result.get("source_records") or []) for result in module_results),
        "owned_agent_role": _public_text(
            (primary.get("report") or {}).get("owned_agent_execution", {}).get("role")
            or (primary.get("report") or {}).get("agent_role")
            or ""
        ),
    }


def _owned_agent_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    executions = []
    roles = set()
    for result in results:
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        execution = report.get("owned_agent_execution") if isinstance(report.get("owned_agent_execution"), dict) else None
        if not execution:
            continue
        role = _public_text(execution.get("role") or "")
        if role:
            roles.add(role)
        executions.append(
            {
                "task_type": _public_text(result.get("task_type") or ""),
                "role": role,
                "executor": _public_text(execution.get("executor") or ""),
                "agent_class": _public_text(execution.get("agent_class") or ""),
                "uses_live_model": bool(execution.get("uses_live_model")),
                "uses_external_tools": bool(execution.get("uses_external_tools")),
                "tool_driven_section_count": _tool_driven_section_count(execution),
                "knowledge_items_used_count": len(execution.get("knowledge_items_used") or []),
            }
        )
    return {
        "executor": "jiejing-owned-agent-executor" if executions else "",
        "execution_count": len(executions),
        "roles_seen": sorted(roles),
        "role_count": len(roles),
        "all_results_have_owned_execution": bool(results) and len(executions) == len(results),
        "local_only": not any(item["uses_live_model"] or item["uses_external_tools"] for item in executions),
        "executions": executions,
    }


def _tool_driven_section_count(execution: dict[str, Any]) -> int:
    tool_driven = execution.get("tool_driven_sections") if isinstance(execution.get("tool_driven_sections"), dict) else {}
    count = 0
    for value in tool_driven.values():
        if isinstance(value, list):
            count += len(value)
    return count


def _confirmation_summary(confirmations: list[dict[str, Any]]) -> dict[str, Any]:
    actions: dict[str, int] = {}
    for item in confirmations:
        action = _public_text(item.get("action_type") or "unknown")
        actions[action] = actions.get(action, 0) + 1
    return {
        "count": len(confirmations),
        "actions": actions,
        "items": [
            {
                "confirmation_id": _public_text(item.get("confirmation_id") or ""),
                "action_type": _public_text(item.get("action_type") or ""),
                "title": _public_text(item.get("title") or ""),
                "default_action": _public_text(item.get("default_action") or ""),
            }
            for item in confirmations[:12]
        ],
    }


def _readiness_score(
    results: list[dict[str, Any]],
    confirmations: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    owned_agent: dict[str, Any],
) -> dict[str, Any]:
    result_score = min(35, round(len(results) / STANDARD_TASK_COUNT * 35)) if STANDARD_TASK_COUNT else 0
    owned_score = 25 if owned_agent.get("all_results_have_owned_execution") else min(25, owned_agent.get("execution_count", 0) * 2)
    ready_validations = [
        item for item in validations if not _is_blocked_status(item.get("validation_status")) and item.get("validation_status")
    ]
    validation_score = min(20, round(len(ready_validations) / max(1, len(validations) or 1) * 20)) if validations else 0
    confirmation_score = 10 if confirmations else 0
    safety_score = 10
    total = min(100, result_score + owned_score + validation_score + confirmation_score + safety_score)
    return {
        "saas_simulation_percent": total,
        "score_parts": {
            "runtime_results": result_score,
            "owned_agent_execution": owned_score,
            "validation_contracts": validation_score,
            "confirmation_packaging": confirmation_score,
            "safety_boundary": safety_score,
        },
        "honest_limit": "This is local SaaS simulation readiness. Production replacement still needs live model, tools, cloud queue, auth, database, and real platform adapters.",
    }


def _report_preview(result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    return {
        "task_id": _public_text(result.get("task_id") or ""),
        "task_type": _public_text(result.get("task_type") or ""),
        "status": _public_text(result.get("status") or ""),
        "summary": _public_text(result.get("summary") or report.get("merchant_readable_summary") or ""),
        "agent_role": _public_text(report.get("agent_role") or ""),
        "section_count": len(sections),
        "sections": {
            _public_text(key): _public_value(value)
            for key, value in sections.items()
        },
        "limits": [_public_text(item) for item in report.get("limits", []) if item],
    }


def _module_status(
    primary: dict[str, Any],
    blocked_validations: list[dict[str, Any]],
    confirmation_count: int,
    missing_count: int,
) -> str:
    if not primary:
        return "pending"
    result_status = str(primary.get("status") or "")
    if blocked_validations or missing_count or "missing" in result_status:
        return "blocked_missing_input"
    if confirmation_count or "confirmation" in result_status:
        return "blocked_for_confirmation"
    if "partial" in result_status:
        return "partial"
    if "success" in result_status:
        return "ready"
    return "partial"


def _missing_input_count(results: list[dict[str, Any]]) -> int:
    return sum(len(result.get("missing_inputs") or []) for result in results)


def _is_blocked_status(status: Any) -> bool:
    text = str(status or "").lower()
    return "blocked" in text or "missing" in text or "fail" in text


def _missing_summary(label: str) -> str:
    return f"{label} has not returned a Runtime result yet."


def _task_title(task_type: str) -> str:
    return {
        "ceo.intake": "AI CEO intake",
        "market.data_packet": "Market data packet",
        "market.report": "Market report",
        "source.match": "Source match",
        "listing.package": "Product listing package",
        "asset.brief": "Asset task package",
        "customer.learn_product": "Customer service learning package",
        "finance.review": "Finance review",
        "confirmation.package": "Confirmation package",
        "ceo.final_report": "AI CEO final report",
        "owner.review": "Owner review",
    }.get(task_type, task_type)


def _public_value(value: Any) -> Any:
    if isinstance(value, str):
        return _public_text(value)
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _public_text(key): _public_value(item)
            for key, item in value.items()
        }
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _public_text(value)


def _public_text(value: Any) -> str:
    text = str(value)
    text = text.replace("\\\\wsl.localhost\\Ubuntu\\home\\hermes", "[internal-runtime-path]")
    text = re.sub(
        r"C:\\Users\\57249\\Documents\\Codex\\2026-04-29\\hermes-agents\\software-demo\\?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?i)hermes", "internal runtime", text)
    # Keep the snapshot payload compact enough for front-end use.
    if len(text) > 4000:
        text = text[:3997] + "..."
    return text


def snapshot_to_jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """Defensive JSON roundtrip for tests and API responses."""

    return json.loads(json.dumps(data, ensure_ascii=False))
