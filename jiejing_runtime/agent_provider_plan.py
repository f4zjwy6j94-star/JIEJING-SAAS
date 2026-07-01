"""Owned Agent to provider-job execution planning.

The Jiejing-owned agents should not know or carry platform credentials. This
planner maps commerce tasks to provider-job contracts, making each role's tool
dependencies explicit before the SaaS backend queues any external capability.
"""

from __future__ import annotations

from typing import Any

from .provider_job_contracts import build_provider_job_contract_catalog
from .role_capabilities import RuntimeRoleCapabilityMap


TASK_PROVIDER_JOBS = {
    "market.data_packet": ["public_search.market_research", "ebay.read_only_snapshot"],
    "market.report": ["public_search.market_research", "ebay.read_only_snapshot", "model.role_report_assist"],
    "source.match": ["sourcing.1688_availability"],
    "listing.package": ["ebay.read_only_snapshot", "model.role_report_assist"],
    "asset.brief": ["media.asset_generation", "model.role_report_assist"],
    "customer.learn_product": ["ebay.read_only_snapshot", "model.role_report_assist"],
    "finance.review": ["logistics.orange_connex_quote", "model.role_report_assist"],
    "confirmation.package": ["logistics.orange_connex_quote"],
    "ceo.final_report": ["model.role_report_assist"],
}


def build_agent_provider_execution_plan(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    catalog = build_provider_job_contract_catalog()
    contracts = {item["key"]: item for item in catalog.get("contracts", [])}
    role_map = RuntimeRoleCapabilityMap().to_dict()
    role_by_task = {
        item.get("task_type"): item.get("role_key")
        for item in role_map.get("task_routes", [])
        if isinstance(item, dict)
    }
    planned_tasks: list[dict[str, Any]] = []
    for task in tasks:
        task_type = str(task.get("task_type") or "")
        provider_keys = _provider_keys_from_task(task, task_type)
        provider_jobs = []
        for key in provider_keys:
            contract = contracts.get(key)
            if not contract:
                provider_jobs.append(
                    {
                        "provider_job_key": key,
                        "status": "blocked_unknown_contract",
                        "secret_exposed": False,
                        "real_execution_allowed": False,
                    }
                )
                continue
            provider_jobs.append(
                {
                    "provider_job_key": key,
                    "provider_family": contract.get("provider_family"),
                    "queue": contract.get("queue"),
                    "required_secret_purpose": contract.get("required_secret_purpose"),
                    "required_inputs": list(contract.get("required_inputs", [])),
                    "output_packet": contract.get("output_packet"),
                    "source_record_type": contract.get("source_record_type"),
                    "timeout_seconds": contract.get("timeout_seconds"),
                    "max_attempts": contract.get("max_attempts"),
                    "blocked_actions": list(contract.get("blocked_actions", [])),
                    "status": "contract_ready",
                    "secret_exposed": False,
                    "real_execution_allowed": False,
                }
            )
        planned_tasks.append(
            {
                "task_type": task_type,
                "role_key": task.get("role_key") or role_by_task.get(task_type) or _role_from_task_input(task),
                "merchant_label": task.get("merchant_label") or task.get("title") or task_type,
                "provider_job_count": len(provider_jobs),
                "provider_jobs": provider_jobs,
                "tool_dependencies_visible": bool(provider_jobs),
                "high_risk_actions_stay_confirmation_gated": True,
                "secret_exposed": False,
                "real_execution_allowed": False,
            }
        )
    provider_families = sorted(
        {
            str(job.get("provider_family"))
            for item in planned_tasks
            for job in item.get("provider_jobs", [])
            if job.get("provider_family")
        }
    )
    missing_contracts = [
        job.get("provider_job_key")
        for item in planned_tasks
        for job in item.get("provider_jobs", [])
        if job.get("status") == "blocked_unknown_contract"
    ]
    return {
        "planner": "jiejing-agent-provider-execution-plan",
        "planner_version": "2026-05-15.1",
        "task_count": len(tasks),
        "planned_task_count": len(planned_tasks),
        "provider_job_count": sum(int(item.get("provider_job_count") or 0) for item in planned_tasks),
        "provider_families": provider_families,
        "planned_tasks": planned_tasks,
        "missing_contracts": missing_contracts,
        "status": "ready" if not missing_contracts else "blocked_unknown_contract",
        "runtime_boundary": {
            "owned_agents_receive_sanitized_packets_only": True,
            "provider_jobs_are_backend_queued": True,
            "task_secret_grants_required": True,
            "frontend_gets_raw_secret": False,
            "runtime_gets_raw_secret": False,
            "real_platform_writes_enabled": False,
        },
        "secret_exposed": False,
        "real_execution_allowed": False,
    }


def _provider_keys_from_task(task: dict[str, Any], task_type: str) -> list[str]:
    if isinstance(task.get("provider_job_keys"), list):
        return [str(item) for item in task.get("provider_job_keys", []) if item]
    raw_step = task.get("step") if isinstance(task.get("step"), dict) else {}
    if isinstance(raw_step.get("provider_job_keys"), list):
        return [str(item) for item in raw_step.get("provider_job_keys", []) if item]
    return list(TASK_PROVIDER_JOBS.get(task_type, []))


def _role_from_task_input(task: dict[str, Any]) -> str:
    task_input = task.get("input") if isinstance(task.get("input"), dict) else {}
    agent_profile = task_input.get("agent_profile") if isinstance(task_input.get("agent_profile"), dict) else {}
    return str(agent_profile.get("role") or "ceo")
