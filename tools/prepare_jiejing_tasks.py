#!/usr/bin/env python3
"""Generate standard JiejingTask input files from an acceptance sample.

This converts a closed-loop sample sequence into the task objects the future
Jiejing backend should enqueue before calling HermesAdapter, JiejingAgentAdapter,
or MockAgentAdapter. It performs no network calls and does not execute Hermes.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TIMEOUTS_SECONDS = {
    "ceo.intake": 60,
    "market.data_packet": 180,
    "market.report": 180,
    "source.match": 180,
    "listing.package": 180,
    "asset.brief": 180,
    "customer.learn_product": 120,
    "finance.review": 120,
    "confirmation.package": 60,
    "ceo.final_report": 90,
    "owner.review": 90,
}

TASK_LABELS = {
    "ceo.intake": "AI CEO receives merchant goal and splits the work.",
    "market.data_packet": "Market manager gathers and labels the data packet.",
    "market.report": "Market manager produces a report-grade opportunity judgment.",
    "source.match": "Sourcing and finance check supplier feasibility and cost facts.",
    "listing.package": "Product manager prepares an eBay listing package.",
    "asset.brief": "Product manager prepares image and video requirements for the asset workshop.",
    "customer.learn_product": "Customer service learns the product before automatic replies.",
    "finance.review": "Finance reviews margin, shipping, fees, and risk.",
    "confirmation.package": "Confirmation center packages high-risk decisions for the merchant.",
    "ceo.final_report": "AI CEO summarizes the closed loop and next step.",
    "owner.review": "Founder/Codex review checks productization and blockers.",
}

OUTPUT_CONTRACTS = {
    "ceo.intake": [
        "merchant_goal",
        "risk_boundary",
        "task_breakdown",
        "next_tasks",
    ],
    "market.data_packet": [
        "keywords",
        "candidate_competitors",
        "price_bands",
        "source_records",
        "unavailable_data",
    ],
    "market.report": [
        "category_overview",
        "buyer_persona",
        "ebay_price_bands",
        "top_competitors",
        "keyword_direction",
        "risk_signals",
        "recommendation",
        "next_step",
    ],
    "source.match": [
        "supplier_candidates",
        "cost_inputs",
        "package_inputs",
        "supplier_questions",
        "procurement_risks",
    ],
    "listing.package": [
        "sku",
        "title",
        "subtitle_notice",
        "category_id",
        "condition",
        "format",
        "price",
        "quantity",
        "item_specifics",
        "description_html",
        "pictures_required",
        "video_required",
        "package_weight",
        "package_dimensions",
        "business_policies",
        "publish_blockers",
    ],
    "asset.brief": [
        "main_image_brief",
        "white_background_images",
        "scene_images",
        "detail_page_image",
        "size_image",
        "video_script",
        "asset_facts_to_confirm",
    ],
    "customer.learn_product": [
        "product_knowledge_card",
        "buyer_questions",
        "pre_sale_replies",
        "after_sale_replies",
        "human_takeover_rules",
        "forbidden_promises",
    ],
    "finance.review": [
        "cost_breakdown",
        "shipping_estimate",
        "platform_fee_estimate",
        "return_reserve",
        "margin_range",
        "red_line",
        "recommendation",
    ],
    "confirmation.package": [
        "publish_confirmation",
        "price_confirmation",
        "inventory_confirmation",
        "procurement_payment_confirmation",
        "policy_confirmation",
        "customer_service_boundary_confirmation",
    ],
    "ceo.final_report": [
        "what_was_done",
        "role_outputs",
        "key_conclusion",
        "missing_inputs",
        "risks",
        "confirmation_center_status",
        "next_step",
    ],
    "owner.review": [
        "workflow_alignment",
        "saas_productization_notes",
        "remaining_blockers",
        "follow_up_actions",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare standard JiejingTask inputs from a sample.")
    parser.add_argument("sample_dir", help="Sample directory containing task-sequence.json")
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to <sample_dir>/prepared-tasks",
    )
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def task_id(sample_id: str, order: int, task_type: str) -> str:
    return f"{sample_id}::{order:02d}::{task_type}"


def build_source_policy(task_type: str) -> dict[str, Any]:
    return {
        "must_label_sources": True,
        "allowed_source_types": [
            "official_api",
            "official_page",
            "public_page",
            "merchant_provided",
            "manual_input",
            "screenshot_or_video",
            "tool_estimate",
            "ai_inference",
            "restricted_unavailable",
            "hermes_closed_loop_sample",
        ],
        "ai_inference_rule": "AI inference must be labeled and cannot be presented as official platform data.",
        "task_specific_note": (
            "For listing work, eBay category and item specifics must be validated before real publish."
            if task_type == "listing.package"
            else ""
        ),
    }


def build_risk_policy() -> dict[str, Any]:
    return {
        "confirmation_required_actions": [
            "oauth_scope_change",
            "publish_listing",
            "bulk_publish_listing",
            "change_price",
            "change_inventory",
            "ad_budget",
            "refund",
            "partial_refund",
            "procurement_payment",
            "address_write",
            "policy_edit",
            "store_subscription",
            "sensitive_buyer_commitment",
        ],
        "default_action": "hold",
        "no_real_execution_in_demo": True,
    }


def build_input(sample: dict[str, Any], expected: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    task_type = task["task_type"]
    product = expected.get("product", sample.get("sample_name", "unknown product"))
    base = {
        "product": product,
        "merchant_goal": "Run an eBay-first closed loop from opportunity judgment to publish-ready confirmation.",
        "sample_source_file": task.get("source_file"),
        "expected_status": task.get("expected_status"),
        "notes": task.get("notes", ""),
    }

    if task_type == "market.data_packet":
        base.update(
            {
                "research_scope": ["eBay public/API data where available", "public web pages", "merchant-provided facts"],
                "constraints": ["small/light", "non-electric", "low after-sale complexity", "supplier-findable"],
            }
        )
    elif task_type == "source.match":
        base.update(
            {
                "sourcing_channels": ["1688", "manual supplier link", "merchant-provided table"],
                "must_confirm_before_publish": ["real dimensions", "weight", "material", "origin city", "packaging"],
            }
        )
    elif task_type == "listing.package":
        base.update(
            {
                "marketplace": "eBay US",
                "listing_mode": "fixed_price",
                "must_validate": ["category_id", "condition_values", "item_specifics", "business_policy_ids"],
            }
        )
    elif task_type == "asset.brief":
        base.update(
            {
                "asset_scope": ["main image", "white background image", "scene image", "size image", "detail page", "short video"],
                "asset_warning": "Asset brief is not the same as final generated media.",
            }
        )
    elif task_type == "customer.learn_product":
        base.update(
            {
                "automation_boundary": "Auto reply can handle routine questions only; refunds, disputes, compensation, and sensitive promises require human takeover.",
            }
        )
    elif task_type == "finance.review":
        base.update(
            {
                "cost_scope": ["purchase price", "platform fees", "shipping estimate", "return reserve", "ad budget impact"],
                "final_publish_rule": "If margin or policy facts are incomplete, stop at confirmation center.",
            }
        )
    elif task_type == "confirmation.package":
        base.update(
            {
                "confirmation_scope": ["publish", "price", "inventory", "procurement payment", "store policies", "customer-service boundary"],
            }
        )

    return base


def build_context(sample: dict[str, Any], previous_task_id: str | None) -> dict[str, Any]:
    return {
        "sample_id": sample["sample_id"],
        "sample_name": sample.get("sample_name"),
        "sample_status": sample.get("sample_status"),
        "source_root": sample.get("source_root"),
        "previous_task_id": previous_task_id,
        "execution_boundary": sample.get("real_execution", {}),
    }


def build_task(sample: dict[str, Any], expected: dict[str, Any], task: dict[str, Any], previous_task_id: str | None) -> dict[str, Any]:
    order = int(task["order"])
    task_type = task["task_type"]
    current_task_id = task_id(sample["sample_id"], order, task_type)
    return {
        "task_id": current_task_id,
        "task_type": task_type,
        "task_version": "2026-05-14",
        "user_id": "user_demo",
        "company_id": "company_demo",
        "store_id": "store_demo_northvalesource",
        "platform": sample.get("platform", "ebay"),
        "stage": "store_opened",
        "project_id": sample["sample_id"],
        "parent_task_id": previous_task_id,
        "input": build_input(sample, expected, task),
        "context": build_context(sample, previous_task_id),
        "source_policy": build_source_policy(task_type),
        "risk_policy": build_risk_policy(),
        "output_contract": {
            "summary_required": True,
            "merchant_readable": True,
            "required_sections": OUTPUT_CONTRACTS.get(task_type, []),
            "empty_output_allowed": False,
        },
        "timeout_seconds": TIMEOUTS_SECONDS.get(task_type, 180),
        "retry_policy": {
            "max_retries": 2,
            "split_on_timeout": True,
            "split_strategy": "return partial result, preserve source records, and create smaller follow-up tasks",
        },
        "audit": {
            "prepared_at": now_iso(),
            "prepared_by": "prepare_jiejing_tasks.py",
            "source_sample_file": "task-sequence.json",
            "description": TASK_LABELS.get(task_type, task_type),
        },
    }


def write_manifest(sample: dict[str, Any], tasks: list[dict[str, Any]], output_dir: Path) -> None:
    manifest = {
        "sample_id": sample["sample_id"],
        "generated_at": now_iso(),
        "task_count": len(tasks),
        "execution_note": "Prepared only. No Hermes, model, eBay, payment, sourcing, or network call was executed.",
        "tasks": [
            {
                "order": idx + 1,
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "timeout_seconds": task["timeout_seconds"],
                "file": f"tasks/{idx + 1:02d}_{task['task_type'].replace('.', '_')}.json",
            }
            for idx, task in enumerate(tasks)
        ],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Prepared Jiejing Tasks - {sample['sample_id']}",
        "",
        "These are standard task inputs for the future Jiejing backend queue.",
        "No Hermes, model, eBay, payment, sourcing, or network call was executed.",
        "",
        "## Task Queue",
        "",
    ]
    for idx, task in enumerate(tasks, start=1):
        lines.append(
            f"{idx}. `{task['task_type']}` -> timeout `{task['timeout_seconds']}s`, parent `{task['parent_task_id'] or 'none'}`"
        )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    sample_dir = Path(args.sample_dir).resolve()
    sequence_path = sample_dir / "task-sequence.json"
    expected_path = sample_dir / "expected-result-summary.json"
    if not sequence_path.exists():
        print(f"FAIL missing task sequence: {sequence_path}", file=sys.stderr)
        return 2
    if not expected_path.exists():
        print(f"FAIL missing expected summary: {expected_path}", file=sys.stderr)
        return 2

    sample = read_json(sequence_path)
    expected = read_json(expected_path)
    output_dir = Path(args.output_dir).resolve() if args.output_dir else sample_dir / "prepared-tasks"
    tasks_dir = output_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for old_task in tasks_dir.glob("*.json"):
        old_task.unlink()

    tasks: list[dict[str, Any]] = []
    previous_task_id: str | None = None
    for task in sample.get("tasks", []):
        prepared = build_task(sample, expected, task, previous_task_id)
        tasks.append(prepared)
        file_path = tasks_dir / f"{task['order']:02d}_{task['task_type'].replace('.', '_')}.json"
        file_path.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8")
        previous_task_id = prepared["task_id"]

    write_manifest(sample, tasks, output_dir)
    print(f"OK prepared tasks: {output_dir}")
    print(f"tasks={len(tasks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
