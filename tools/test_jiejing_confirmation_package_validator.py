#!/usr/bin/env python3
"""Regression for confirmation package validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ConfirmationPackageValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "confirmation-package-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = ConfirmationPackageValidator()
    good = validator.validate_text(good_confirmation_text())
    if good.get("status") != "ready_for_confirmation_center":
        return fail(f"complete confirmation package should be ready: {good.get('summary')}")
    bad = validator.validate_text("Allowed auto actions: publish listing, refund, and ad budget update.")
    if bad.get("status") == "ready_for_confirmation_center":
        return fail("unsafe confirmation package should be blocked")
    if not validator.missing_inputs_from_validation(bad):
        return fail("bad confirmation package should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Backflow Incense Burner",
            merchant_goal="Validate confirmation package import.",
            project_id="confirmation-package-validator-regression",
        )
    )
    confirmation_task = next(task for task in tasks if task["task_type"] == "confirmation.package")
    packet_json = RUN_DIR / "confirmation_packet.json"
    role_output = RUN_DIR / "confirmation_center_output.md"
    output_json = RUN_DIR / "imported_confirmation_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": confirmation_task,
                "target_role": "confirmation-center",
                "dispatch_prompt": "Validate confirmation package output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(good_confirmation_text(), encoding="utf-8")
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
        return fail("import-handoff-result failed for confirmation package")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("confirmation_package_validation", {})
    if validation.get("status") != "ready_for_confirmation_center":
        return fail("Hermes importer should attach confirmation package validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("confirmation import must keep real execution blocked")

    print("PASS confirmation_package_validator_regression")
    return 0


def good_confirmation_text() -> str:
    return """
# Confirmation Center Package

## allowed_auto_actions
Allowed auto actions: organize reports, prepare draft listings, draft low-risk customer replies, update internal task status, and build asset tasks.

## default_rule_actions
Default rule actions: use saved eBay business policy drafts only after merchant approval; store default rules may prepare drafts but not execute real changes.

## every_time_confirm_actions
Every time confirm actions / manual confirmation:
- publish listing requires confirmation every time.
- batch publish requires confirmation every time.
- procurement payment / pay supplier requires confirmation every time.
- refund / partial refund requires confirmation every time.
- ad budget / promoted listing budget requires confirmation every time.
- price change / modify price requires confirmation every time.
- inventory change / modify inventory requires confirmation every time.
- store policy change including fulfillment policy, payment policy, and return policy requires confirmation every time.
- store subscription change requires confirmation every time.
- OAuth authorization / token scope change requires confirmation every time.
- sensitive customer promise, compensation, guarantee, customs, or exact delivery date requires human confirmation every time.

## blocked_actions
Never auto / blocked actions: no real publish, no procurement payment, no refund, no ad spend, no policy edit, no OAuth scope change without merchant confirmation.

## missing_facts
Missing facts / stop conditions: supplier facts, final logistics quote, business policy IDs, category item specifics, asset manifest, and finance lock.
"""


if __name__ == "__main__":
    raise SystemExit(main())
