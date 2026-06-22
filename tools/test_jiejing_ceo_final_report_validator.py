#!/usr/bin/env python3
"""Regression for AI CEO final report validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import CeoFinalReportValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "ceo-final-report-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = CeoFinalReportValidator()
    good = validator.validate_text(good_ceo_text())
    if good.get("status") != "ready_for_merchant_summary":
        return fail(f"complete CEO final report should be ready: {good.get('summary')}")
    bad = validator.validate_text("All done. Looks good. Continue optimizing.")
    if bad.get("status") == "ready_for_merchant_summary":
        return fail("vague CEO final report should be blocked")
    if not validator.missing_inputs_from_validation(bad):
        return fail("bad CEO final report should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Backflow Incense Burner",
            merchant_goal="Validate AI CEO final report import.",
            project_id="ceo-final-report-validator-regression",
        )
    )
    ceo_task = next(task for task in tasks if task["task_type"] == "ceo.final_report")
    packet_json = RUN_DIR / "ceo_final_packet.json"
    role_output = RUN_DIR / "ceo_final_output.md"
    output_json = RUN_DIR / "imported_ceo_final_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": ceo_task,
                "target_role": "ai-ceo",
                "dispatch_prompt": "Validate AI CEO final output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(good_ceo_text(), encoding="utf-8")
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "import-handoff-result",
        "--packet-json",
        str(packet_json),
        "--role-output",
        str(role_output),
        "--output-json",
        str(output_json),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail("import-handoff-result failed for CEO final report")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("ceo_final_report_validation", {})
    if validation.get("status") != "ready_for_merchant_summary":
        return fail("Hermes importer should attach CEO final report validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("CEO final import must keep real execution blocked")

    print("PASS ceo_final_report_validator_regression")
    return 0


def good_ceo_text() -> str:
    return """
# AI CEO Final Report

## current_status
Current status: market report, source facts, listing package, asset manifest, customer learning, finance review, and confirmation package are assembled for review.

## source_health
Source health / source confidence: eBay read-only and supplier facts remain draft-level until live sources and merchant inputs are confirmed.

## reports_ready
Reports ready: market manager report is ready; product manager listing package is ready; asset manager asset manifest is ready; customer service learning package is ready; finance manager finance review is ready; confirmation center package is ready.

## publish_lock
Publish lock: do not publish. Real eBay publish remains locked until merchant confirmation in the confirmation center.

## next_minimum_action
Next minimum action: confirm the supplier facts and business policy IDs, then review the confirmation center publish item.
"""


if __name__ == "__main__":
    raise SystemExit(main())
