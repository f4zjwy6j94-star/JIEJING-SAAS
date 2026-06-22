#!/usr/bin/env python3
"""Regression for customer-service learning validation and Hermes import checks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import CustomerLearningValidator
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

RUN_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "customer-learning-validator"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    validator = CustomerLearningValidator()
    good = validator.validate_text(good_customer_text())
    if good.get("status") != "ready_for_auto_reply_review":
        return fail(f"complete customer package should be ready: {good.get('summary')}")
    bad = validator.validate_text("Customer service is ready for automatic replies.")
    if bad.get("status") != "blocked_unsafe_auto_reply_claim":
        return fail("automation claim without learning package should be blocked")
    if not validator.missing_inputs_from_validation(bad):
        return fail("bad customer package should produce missing inputs")

    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Backflow Incense Burner",
            merchant_goal="Validate customer service learning package import.",
            project_id="customer-learning-validator-regression",
        )
    )
    customer_task = next(task for task in tasks if task["task_type"] == "customer.learn_product")
    packet_json = RUN_DIR / "customer_learning_packet.json"
    role_output = RUN_DIR / "customer_manager_output.md"
    output_json = RUN_DIR / "imported_customer_learning_result.json"
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    packet_json.write_text(
        json.dumps(
            {
                "task": customer_task,
                "target_role": "customer-service-manager",
                "dispatch_prompt": "Validate customer-service learning output.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    role_output.write_text(good_customer_text(), encoding="utf-8")
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
        return fail("import-handoff-result failed for customer learning")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    validation = imported.get("report", {}).get("customer_learning_validation", {})
    if validation.get("status") != "ready_for_auto_reply_review":
        return fail("Hermes importer should attach customer learning validation")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("customer import must keep real execution blocked")

    print("PASS customer_learning_validator_regression")
    return 0


def good_customer_text() -> str:
    return """
# Customer Service Learning Package

## product_service_file
Product file: Backflow incense burner. Material: ceramic or resin pending supplier confirmation.
Use case: home decor, meditation room, desk display. Do not claim medical or therapeutic effects.

## buyer_question_map
- Before purchase: size, included incense cones, smoke effect, material, package protection.
- After purchase: tracking, delayed delivery, broken item photo evidence, return process.

## faq
Q: Does it include incense cones?
A: Please check the final listing package; if the supplier has not confirmed, do not promise inclusion.
Q: What if it arrives damaged?
A: Ask for photos of the package and product, then escalate for refund or replacement review.

## reply_boundary
Auto reply boundary: low-risk product facts, tracking status wording, and basic FAQ can be drafted.
Do not promise exact arrival date, compensation, refund approval, customs result, or medical effect.

## auto_reply_templates
Template 1: Thank you for your message. I can help check the product details and shipping status.
Template 2: Could you please send a clear photo of the item and outer package so we can review it?

## escalation_rules
Human takeover / manual takeover is required for refund, compensation, negative feedback, customs, exact delivery date, and any buyer dispute.

Customer service is ready for automatic replies only within the safe reply boundary above.
"""


if __name__ == "__main__":
    raise SystemExit(main())
