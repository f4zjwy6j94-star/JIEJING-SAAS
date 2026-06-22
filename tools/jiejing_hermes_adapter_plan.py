#!/usr/bin/env python3
"""Generate a Hermes dispatch plan from a Jiejing task sample.

This planner does not send messages to Hermes. It only creates short,
bounded prompts and a dispatch-plan.json file so the future HermesAdapter can
execute the same task protocol without hand-written instructions each time.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROLE_BY_TASK = {
    "ceo.intake": "default",
    "market.data_packet": "market-manager",
    "market.report": "market-manager",
    "source.match": "finance-supply",
    "listing.package": "product-manager",
    "asset.brief": "product-manager",
    "customer.learn_product": "customer-service",
    "finance.review": "finance-supply",
    "confirmation.package": "default",
    "ceo.final_report": "default",
    "owner.review": "default",
}

REQUIRED_OUTPUTS = {
    "ceo.intake": [
        "merchant_goal",
        "automation_boundary",
        "task_split",
        "missing_questions",
        "next_tasks",
    ],
    "market.data_packet": [
        "keywords",
        "price_band",
        "competitor_sample",
        "source_records",
        "restricted_unavailable",
    ],
    "market.report": [
        "category_overview",
        "buyer_persona",
        "ebay_price_band",
        "top5_competitors",
        "risk_signals",
        "recommendation",
    ],
    "source.match": [
        "source_candidates",
        "procurement_cost",
        "supplier_questions",
        "shipping_origin",
        "source_risk",
    ],
    "listing.package": [
        "sku",
        "title",
        "category_id",
        "item_specifics",
        "price",
        "description_html",
        "business_policies",
        "publish_blockers",
    ],
    "asset.brief": [
        "image_plan",
        "video_plan",
        "detail_page_plan",
        "forbidden_claims",
        "asset_readiness",
    ],
    "customer.learn_product": [
        "product_knowledge_card",
        "buyer_faq",
        "auto_reply_boundary",
        "handoff_triggers",
        "forbidden_promises",
    ],
    "finance.review": [
        "cost_breakdown",
        "shipping_estimate",
        "fee_estimate",
        "margin_range",
        "publish_decision",
    ],
    "confirmation.package": [
        "confirmation_items",
        "impact",
        "default_action",
        "approve_edit_reject",
    ],
    "ceo.final_report": [
        "closed_loop_summary",
        "completed_tasks",
        "remaining_blockers",
        "confirmation_items",
        "next_step",
    ],
    "owner.review": [
        "acceptance_result",
        "saas_remediation",
        "runtime_learning",
        "do_not_execute",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Hermes dispatch plan from sample.")
    parser.add_argument("sample_dir", help="Sample directory containing task-sequence.json")
    parser.add_argument("--output-dir", help="Output directory. Defaults to <sample_dir>/hermes-dispatch-plan")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def excerpt(text: str, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def prompt_for_task(sample: dict[str, Any], task: dict[str, Any], source_root: Path) -> str:
    task_type = task["task_type"]
    role = ROLE_BY_TASK.get(task_type, "default")
    source_file = task.get("source_file")
    source_path = source_root / source_file if source_file else None
    source_excerpt = ""
    if source_path and source_path.exists():
        source_excerpt = excerpt(read_text(source_path))

    required = "\n".join(f"- {item}" for item in REQUIRED_OUTPUTS.get(task_type, []))
    notes = task.get("notes", "")
    return f"""# Jiejing HermesAdapter Dispatch Prompt

Role: {role}
Task type: {task_type}
Sample: {sample["sample_id"]}
Platform: {sample.get("platform", "ebay")}
Expected status: {task.get("expected_status", "success")}
Source file: {source_file or "none"}

## Mission
Execute this as a bounded Jiejing SaaS task. Do not treat it as free-form chat.
Return a report that can be converted into JiejingTaskResult.

## Required Output Fields
{required or "- structured_report"}

## Boundary
- Do not publish to eBay.
- Do not refund.
- Do not change price or inventory.
- Do not change ad budget.
- Do not pay suppliers or place procurement orders.
- Do not change OAuth scopes or store policies.
- Label official data, public pages, merchant-provided facts, test assumptions, and AI inference separately.
- If data is missing, return missing_inputs instead of inventing facts.

## Notes
{notes or "No extra notes."}

## Local Source Excerpt
{source_excerpt or "No source excerpt available."}
"""


def main() -> int:
    args = parse_args()
    sample_dir = Path(args.sample_dir).resolve()
    sequence_path = sample_dir / "task-sequence.json"
    if not sequence_path.exists():
        raise SystemExit(f"missing task sequence: {sequence_path}")

    sample = read_json(sequence_path)
    source_root = Path(sample["source_root"])
    output_dir = Path(args.output_dir).resolve() if args.output_dir else sample_dir / "hermes-dispatch-plan"
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for old_prompt in prompts_dir.glob("*.md"):
        old_prompt.unlink()

    dispatch_tasks = []
    for task in sample.get("tasks", []):
        task_type = task["task_type"]
        role = ROLE_BY_TASK.get(task_type, "default")
        prompt = prompt_for_task(sample, task, source_root)
        prompt_name = f"{task['order']:02d}_{task_type.replace('.', '_')}_{role}.md"
        prompt_path = prompts_dir / prompt_name
        prompt_path.write_text(prompt, encoding="utf-8")
        dispatch_tasks.append(
            {
                "order": task["order"],
                "task_type": task_type,
                "role": role,
                "prompt_path": str(prompt_path),
                "source_file": task.get("source_file"),
                "expected_status": task.get("expected_status", "success"),
                "execute_now": False,
            }
        )

    plan = {
        "sample_id": sample["sample_id"],
        "adapter": "HermesAdapter",
        "mode": "dispatch_plan_only",
        "generated_at": now_iso(),
        "execute_now": False,
        "safety": {
            "no_real_ebay_write": True,
            "no_payment": True,
            "no_refund": True,
            "no_ad_budget_change": True,
            "no_policy_edit": True,
        },
        "tasks": dispatch_tasks,
    }
    (output_dir / "dispatch-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = [
        f"# Hermes Dispatch Plan - {sample['sample_id']}",
        "",
        "Generated prompts only. No Hermes call was executed.",
        "",
    ]
    for task in dispatch_tasks:
        summary.append(f"- {task['order']:02d} `{task['task_type']}` -> `{task['role']}`")
    (output_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print(f"OK Hermes dispatch plan generated: {output_dir}")
    print(f"tasks={len(dispatch_tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
