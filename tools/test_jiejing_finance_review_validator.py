#!/usr/bin/env python3
"""Regression for finance review validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import FinanceReviewValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "finance-review-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = FinanceReviewValidator()
    good = validator.validate_text(good_finance_text())
    if good.get("status") != "ready_for_confirmation_review":
        return fail(f"complete finance review should be ready: {good.get('summary')}")
    bad = validator.validate_text("Profit margin is about 35%. Finance looks good.")
    if bad.get("status") != "blocked_missing_finance_lock":
        return fail(f"finance review without money numbers and lock should be blocked: {bad.get('status')}")
    missing = validator.missing_inputs_from_validation(bad)
    if not missing:
        return fail("bad finance review should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Backflow Incense Burner",
            merchant_goal="Validate finance review import.",
            project_id="finance-review-validator-regression",
        )
    )
    finance_task = next(task for task in tasks if task["task_type"] == "finance.review")
    packet_json = RUN_DIR / "finance_review_packet.json"
    role_output = RUN_DIR / "finance_manager_output.md"
    output_json = RUN_DIR / "imported_finance_review_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": finance_task,
                "target_role": "finance-risk-manager",
                "dispatch_prompt": "Validate finance review output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(good_finance_text(), encoding="utf-8")
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
        return fail("import-handoff-result failed for finance review")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("finance_review_validation", {})
    if validation.get("status") != "ready_for_confirmation_review":
        return fail("Hermes importer should attach finance review validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("finance import must keep real execution blocked")

    print("PASS finance_review_validator_regression")
    return 0


def good_finance_text() -> str:
    return """
# Finance and Fulfillment Review

## cost_table
Sale price / listing price: US $19.99
Procurement cost / 1688 cost: CNY 18.00
Platform fee / eBay fee: US $2.75
Logistics cost / SpeedPAK / Orange Connex estimate: CNY 58.50
Package cost / packaging cost: CNY 2.00
Subscription allocation / store subscription fee: US $0.20 per unit
Return reserve / refund reserve: US $1.20 per unit

## net_profit_money
Net profit money estimate: US $4.80 before ads. This is not a guaranteed profit.

## logistics_route
Logistics route: supplier to merchant or direct source route, then SpeedPAK Economy after final weight check.

## subscription_allocation
Store subscription allocation is included as US $0.20 per unit for the draft.

## return_reserve
Return reserve is US $1.20 because fragile or description mismatch risk may create after-sale cost.

## risk_notes
Financial risk: logistics quote is still an estimate; supplier weight and package size must be confirmed.

## next_action
Finance lock / publish lock: do not publish. Send to confirmation center after supplier facts, policy IDs, and merchant approval are complete.
"""


if __name__ == "__main__":
    raise SystemExit(main())
