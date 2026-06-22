#!/usr/bin/env python3
"""Regression for listing package validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ListingPackageValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "listing-package-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = ListingPackageValidator()
    good = validator.validate_text(good_listing_text())
    if good.get("status") != "ready_for_confirmation_review":
        return fail(f"good listing should be ready_for_confirmation_review: {good.get('summary')}")
    bad = validator.validate_text("Title: short\nPrice: 19.99\n")
    if bad.get("status") != "blocked_missing_input":
        return fail("incomplete listing should be blocked_missing_input")
    if not validator.missing_inputs_from_validation(bad):
        return fail("incomplete listing should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate listing package import.",
            project_id="listing-package-validator-regression",
        )
    )
    listing_task = next(task for task in tasks if task["task_type"] == "listing.package")
    packet_json = RUN_DIR / "listing_package_packet.json"
    role_output = RUN_DIR / "product_manager_listing_output.md"
    output_json = RUN_DIR / "imported_listing_package_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": listing_task,
                "target_role": "product-manager",
                "dispatch_prompt": "Validate listing package output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(good_listing_text(), encoding="utf-8")
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
        return fail("import-handoff-result failed for listing package")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("listing_validation", {})
    if validation.get("status") != "ready_for_confirmation_review":
        return fail("Hermes importer should attach listing validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("listing import must keep real execution blocked")

    print("PASS listing_package_validator_regression")
    return 0


def good_listing_text() -> str:
    return """
# Product Manager Listing Package

SKU: TUMBLER-30OZ-BLACK-001
Title: 30oz Stainless Steel Tumbler with Lid Straw Travel Coffee Cup
Category ID: 20687
Condition: New
Format: Fixed Price
Price: US $19.99
Quantity: 50

Item Specifics:
- Brand: Unbranded
- Type: Travel Tumbler
- Material: Stainless Steel
- Color: Black
- MPN: Does Not Apply
- UPC: Does Not Apply

Pictures:
Picture 1 white background main image; Picture 2 lifestyle; Picture 3 dimensions; Picture 4 lid detail.
Video: 20 second product handling and leak-resistance demonstration concept.

Description HTML:
<div><h2>30oz Stainless Steel Tumbler</h2><p>Draft description. Claims pending supplier confirmation.</p></div>

Package weight: 620 g
Package dimensions: 12x12x26 cm
Handling time: 3 business days
Item Location: Zhejiang, China

Fulfillment policy: use authorized store default fulfillmentPolicyId after account read.
Payment policy: use authorized store default paymentPolicyId after account read.
Return policy: use authorized store default returnPolicyId after account read.

Publish blockers:
- Real publish locked until supplier facts, final logistics quote, policy IDs, category specifics, and merchant confirmation are complete.
"""


if __name__ == "__main__":
    raise SystemExit(main())
