#!/usr/bin/env python3
"""Regression for the Jiejing-owned commerce Agent Team."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import JiejingAgentTeam, JiejingRuntime, RuntimeCapabilityProfile, RuntimeConfig
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "owned-agent-team-test"


EXPECTED_TASK_ROLES = {
    "ceo.intake": "ceo",
    "market.data_packet": "market-manager",
    "market.report": "market-manager",
    "source.match": "finance-supply",
    "listing.package": "product-manager",
    "asset.brief": "asset-manager",
    "customer.learn_product": "customer-service",
    "finance.review": "finance-supply",
    "confirmation.package": "confirmation-center",
    "ceo.final_report": "ceo",
    "owner.review": "ceo",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    team = JiejingAgentTeam().to_dict()
    if team.get("role_count") != 7:
        return fail("owned Agent Team should expose 7 commerce roles")
    if not team.get("replacement_boundary", {}).get("not_a_hermes_clone"):
        return fail("owned Agent Team must be a commerce runtime, not a Hermes clone")
    for task_type, expected_role in EXPECTED_TASK_ROLES.items():
        actual = team.get("task_to_role", {}).get(task_type)
        if actual != expected_role:
            return fail(f"{task_type} routed to {actual}, expected {expected_role}")
    for role_spec in team.get("roles", []):
        if not role_spec.get("input_requirements"):
            return fail(f"{role_spec.get('role')} missing input requirements")
        if not role_spec.get("stop_conditions"):
            return fail(f"{role_spec.get('role')} missing stop conditions")

    capability_profile = RuntimeCapabilityProfile().to_dict()
    capability_keys = {item.get("key") for item in capability_profile.get("capabilities", [])}
    if "owned_agent_team" not in capability_keys:
        return fail("capability profile must expose owned_agent_team")
    if "owned_agent_execution" not in capability_keys:
        return fail("capability profile must expose owned_agent_execution")
    if "owned_agent_quality_gate" not in capability_keys:
        return fail("capability profile must expose owned_agent_quality_gate")
    if capability_profile.get("owned_agent_team", {}).get("role_count") != 7:
        return fail("capability profile should include owned Agent Team detail")
    if capability_profile.get("owned_agent_executor", {}).get("agent_count") != 7:
        return fail("capability profile should include owned Agent Executor detail")
    if capability_profile.get("owned_agent_quality_gate", {}).get("safe_for_real_execution") is not False:
        return fail("owned Agent quality gate should never mark safe_for_real_execution")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="stainless steel travel cup",
            merchant_goal="Run a Jiejing-owned Agent workflow without Hermes.",
            project_id="owned-agent-team-regression",
            notes="Regression should not call Hermes or execute platform writes.",
        )
    )
    runtime = JiejingRuntime(RuntimeConfig(adapter_name="jiejing-local", demo_mode=True, clean_output=True))
    summary = runtime.run_tasks(tasks, RUN_DIR, run_id="owned-agent-team-regression")
    if summary.task_count != len(tasks):
        return fail("runtime did not execute every workflow task")

    result_files = sorted((RUN_DIR / "results").glob("*.json"))
    if len(result_files) != len(tasks):
        return fail("result file count mismatch")
    for path in result_files:
        result = json.loads(path.read_text(encoding="utf-8"))
        task_type = result.get("task_type")
        report = result.get("report", {})
        expected_role = EXPECTED_TASK_ROLES.get(task_type)
        if report.get("agent_role") != expected_role:
            return fail(f"{task_type} report missing expected agent_role {expected_role}")
        if not report.get("agent_team", {}).get("not_hermes_clone"):
            return fail(f"{task_type} report should declare not_hermes_clone")
        execution = report.get("owned_agent_execution", {})
        if execution.get("executor") != "jiejing-owned-agent-executor":
            return fail(f"{task_type} report missing owned Agent Executor marker")
        if execution.get("role") != expected_role:
            return fail(f"{task_type} owned Agent Executor role mismatch")
        if execution.get("uses_live_model") is not False:
            return fail(f"{task_type} owned Agent Executor should stay local in this regression")
        if not report.get("tool_permissions"):
            return fail(f"{task_type} report missing tool permissions")
        if not report.get("forbidden_actions"):
            return fail(f"{task_type} report missing forbidden actions")
        if not report.get("quality_gates"):
            return fail(f"{task_type} report missing quality gates")
        if not report.get("input_requirements"):
            return fail(f"{task_type} report missing input requirements")
        if not report.get("stop_conditions"):
            return fail(f"{task_type} report missing stop conditions")
        if not report.get("job_spec"):
            return fail(f"{task_type} report missing job spec")
        compliance = report.get("job_spec_compliance", {})
        if compliance.get("status") not in {"pass", "needs_attention", "needs_repair"}:
            return fail(f"{task_type} job spec compliance missing status")
        if compliance.get("real_execution_allowed") is not False:
            return fail(f"{task_type} job spec compliance must block real execution")
        handoff = report.get("handoff_contract", {})
        if handoff.get("real_execution_allowed") is not False:
            return fail(f"{task_type} handoff must block real execution")
        if handoff.get("producer_role") != expected_role:
            return fail(f"{task_type} handoff producer role mismatch")
        quality = report.get("report_quality", {})
        if quality.get("status") not in {"pass", "needs_repair"}:
            return fail(f"{task_type} report quality missing status")
        if quality.get("safe_for_real_execution") is not False:
            return fail(f"{task_type} report quality should never mark safe_for_real_execution")
        gate = report.get("owned_agent_quality_gate", {})
        if gate.get("status") not in {"pass", "needs_attention"}:
            return fail(f"{task_type} owned Agent quality gate failed: {gate.get('status')}")
        if gate.get("safe_for_real_execution") is not False:
            return fail(f"{task_type} owned Agent quality gate must block real execution")
        if gate.get("real_execution_allowed") is not False:
            return fail(f"{task_type} owned Agent quality gate must not allow real execution")
        if gate.get("blockers"):
            return fail(f"{task_type} owned Agent quality gate has blockers")
        check_keys = {item.get("key") for item in gate.get("checks", [])}
        for required_check in {"required_sections", "runtime_controls", "execution_flags", "handoff_boundary", "forbidden_claims"}:
            if required_check not in check_keys:
                return fail(f"{task_type} owned Agent quality gate missing {required_check}")
        audit = result.get("audit", {})
        if audit.get("real_execution_allowed") is not False:
            return fail(f"{task_type} audit must block real execution")
        if any(result.get("audit", {}).get("real_execution", {}).values()):
            return fail(f"{task_type} audit contains a real execution flag")
        if result.get("audit", {}).get("owned_agent_executor", {}).get("agent_count") != 7:
            return fail(f"{task_type} audit missing owned Agent Executor detail")
        if not result.get("audit", {}).get("owned_agent_quality_gate"):
            return fail(f"{task_type} audit missing owned Agent quality gate")
        sections = report.get("sections", {})
        if task_type == "market.report":
            if "US $" not in json.dumps(sections.get("ebay_price_bands"), ensure_ascii=False):
                return fail("market.report should contain role-specific eBay price bands")
            if not sections.get("competitor_top5"):
                return fail("market.report should contain competitor_top5 content")
        if task_type == "listing.package":
            title = sections.get("title", {})
            if not isinstance(title, dict) or title.get("max_length") != 80:
                return fail("listing.package should contain eBay title max-length detail")
            if "fulfillmentPolicyId" not in json.dumps(sections.get("business_policies"), ensure_ascii=False):
                return fail("listing.package should contain the three eBay policy placeholders")
        if task_type == "asset.brief":
            if "1600x1600" not in json.dumps(sections.get("image_plan"), ensure_ascii=False):
                return fail("asset.brief should contain image size planning")
            if "15-30" not in json.dumps(sections.get("video_plan"), ensure_ascii=False):
                return fail("asset.brief should contain video planning")
        if task_type == "customer.learn_product":
            if "Refund" not in str(sections.get("reply_boundary")) and "refund" not in str(sections.get("reply_boundary")):
                return fail("customer.learn_product should contain service escalation boundaries")
        if task_type == "finance.review":
            if "US $" not in json.dumps(sections.get("cost_table"), ensure_ascii=False):
                return fail("finance.review should contain money-denominated cost table")
            if "Pending" not in str(sections.get("net_profit_money")):
                return fail("finance.review should keep unknown net profit pending")
        if task_type == "confirmation.package":
            decisions = json.dumps(sections.get("every_time_confirm_actions"), ensure_ascii=False)
            for word in ["publish", "Refund", "Ad", "Procurement"]:
                if word.lower() not in decisions.lower():
                    return fail("confirmation.package should include all high-risk decision classes")

    print("PASS owned_agent_team_regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
