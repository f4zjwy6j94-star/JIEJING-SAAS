#!/usr/bin/env python3
"""Regression for model-assisted Jiejing Agents without live model spend."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.adapters import JiejingAgentAdapter  # noqa: E402
from jiejing_runtime.model_clients import ModelClient  # noqa: E402
from jiejing_runtime.models import JiejingTask  # noqa: E402
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow  # noqa: E402


class FakeLiveModelClient(ModelClient):
    name = "fake-live-model-client"
    version = "test"

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        sections = task.output_contract.get("required_sections", [])
        return {
            "model_mode": "live_http_model",
            "model_configured": True,
            "merchant_readable_summary": f"Model-assisted report for {task.task_type}.",
            "sections": {section: f"model-assisted {section} with source gaps preserved" for section in sections},
            "limits": ["Fake model client used for regression only; no live spend and no platform writes."],
        }


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="stainless steel measuring spoons",
            merchant_goal="Verify model-assisted Market Report and Listing Package without external calls.",
            project_id="agent-model-assist-regression",
            notes="The fake model client must enrich reports but preserve owned agent safety boundaries.",
        )
    )
    by_type = {task["task_type"]: JiejingTask(task) for task in tasks}
    adapter = JiejingAgentAdapter(model_client=FakeLiveModelClient())
    for task_type in ("market.report", "listing.package"):
        result = adapter.execute(by_type[task_type])
        report = result.get("report", {})
        assist = report.get("model_assist", {})
        execution = report.get("owned_agent_execution", {})
        if assist.get("status") != "applied":
            return fail(f"{task_type} should apply model assist")
        if assist.get("owned_scaffold_preserved") is not True:
            return fail(f"{task_type} should preserve owned agent scaffold")
        if execution.get("uses_live_model") is not True:
            return fail(f"{task_type} should mark live model availability in execution metadata")
        if report.get("owned_agent_quality_gate", {}).get("safe_for_real_execution") is not False:
            return fail(f"{task_type} model-assisted output must still block real execution")
        if report.get("report_contract", {}).get("status") not in {"ready", "pass", "needs_attention"}:
            return fail(f"{task_type} should remain inside report contract")
        serialized = json.dumps(result, ensure_ascii=False)
        for forbidden in ["access_token", "refresh_token", "client_secret", "published_to_ebay\": true"]:
            if forbidden in serialized:
                return fail(f"{task_type} leaked secret/write marker: {forbidden}")
    print("PASS jiejing_agent_model_assist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
