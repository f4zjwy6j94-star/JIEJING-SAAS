#!/usr/bin/env python3
"""Run a deterministic Jiejing Agent Runtime mock over an acceptance sample.

This is the first executable "back-road" prototype. It does not call models,
Hermes, eBay, payment, sourcing platforms, or any external network. It reads a
sample task sequence and converts the existing Hermes closed-loop artifacts into
standard JiejingTaskResult-like JSON files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_ALLOWED = {
    "queued",
    "running",
    "success",
    "partial_success",
    "blocked_missing_input",
    "blocked_permission",
    "failed_timeout",
    "failed_tool",
    "failed_policy",
    "blocked_confirmation_required",
    "cancelled",
}

TASK_OUTPUT_NAMES = {
    "ceo.intake": "ceo_intake",
    "market.data_packet": "market_data_packet",
    "market.report": "market_report",
    "source.match": "source_match",
    "listing.package": "listing_package",
    "asset.brief": "asset_brief",
    "customer.learn_product": "customer_learning_package",
    "finance.review": "finance_review",
    "ceo.final_report": "ceo_final_report",
    "owner.review": "owner_review",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Jiejing Agent Runtime mock on a sample.")
    parser.add_argument("sample_dir", help="Sample directory containing task-sequence.json")
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to <sample_dir>/mock-runtime-run",
    )
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_excerpt(text: str, limit: int = 900) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def blocker_inputs(task_type: str) -> list[dict[str, str]]:
    common = {
        "supplier_real_facts": "Supplier real dimensions, weight, material, origin city, packaging, and test data must be confirmed before publish.",
        "taxonomy_item_specifics": "eBay Taxonomy category and required item specifics must be checked before real publish.",
        "commercial_assets": "Final commercial images/video require confirmed product facts and asset readiness.",
        "shipping_policy_price": "Shipping policy and price strategy must be confirmed because they affect conversion and margin.",
        "human_publish_confirmation": "Real eBay publishing must stay in confirmation center.",
    }
    mapping: dict[str, list[str]] = {
        "source.match": ["supplier_real_facts"],
        "listing.package": ["supplier_real_facts", "taxonomy_item_specifics", "commercial_assets", "shipping_policy_price"],
        "asset.brief": ["supplier_real_facts", "commercial_assets"],
        "customer.learn_product": ["supplier_real_facts"],
        "finance.review": ["supplier_real_facts", "shipping_policy_price", "human_publish_confirmation"],
        "ceo.final_report": ["human_publish_confirmation"],
    }
    return [
        {"input_id": key, "reason": common[key], "severity": "blocking" if key != "commercial_assets" else "high"}
        for key in mapping.get(task_type, [])
    ]


def risk_flags(task_type: str) -> list[dict[str, str]]:
    mapping: dict[str, list[tuple[str, str, str]]] = {
        "market.report": [
            ("source_confidence", "medium", "External platform restrictions or inference must be labeled."),
        ],
        "source.match": [
            ("supplier_verification", "high", "Simulated or unverified supplier facts cannot become publish facts."),
            ("procurement_payment", "high", "Procurement payment requires human confirmation."),
        ],
        "listing.package": [
            ("publish_listing", "critical", "Real listing publication requires confirmation center approval."),
            ("taxonomy_pending", "high", "Category and item specifics require platform validation."),
        ],
        "asset.brief": [
            ("asset_not_final", "high", "Asset brief is not final commercial media."),
        ],
        "customer.learn_product": [
            ("auto_reply_boundary", "medium", "Customer service automation should pause on refunds, disputes, and sensitive commitments."),
        ],
        "finance.review": [
            ("margin_shipping_policy", "high", "Shipping and pricing can invalidate the listing strategy."),
            ("payment_boundary", "critical", "Payments and refunds are not agent-executed actions."),
        ],
        "confirmation.package": [
            ("confirmation_gate", "critical", "High-risk actions must wait for merchant approval."),
        ],
    }
    return [
        {"risk_id": risk_id, "severity": severity, "message": message}
        for risk_id, severity, message in mapping.get(task_type, [])
    ]


def confirmation_items(task_type: str) -> list[dict[str, str]]:
    mapping: dict[str, list[tuple[str, str, str]]] = {
        "source.match": [
            ("procurement_payment", "Confirm procurement payment", "Hold any 1688 or supplier payment until merchant approval."),
        ],
        "listing.package": [
            ("publish_listing", "Confirm real eBay publish", "Only show publish after supplier facts, taxonomy, assets, price, and policies are ready."),
            ("policy_use", "Confirm store policies", "Shipping, payment, and return policies affect the final listing."),
        ],
        "finance.review": [
            ("price_strategy", "Confirm price and shipping strategy", "Margin and conversion depend on final price and shipping policy."),
        ],
        "confirmation.package": [
            ("publish_listing", "Confirm real eBay publish", "Publishing creates a live listing in the merchant store."),
            ("price_strategy", "Confirm price and shipping", "Price and shipping affect conversion, margin, and buyer expectation."),
            ("procurement_payment", "Confirm procurement payment", "Supplier payment and fulfillment route require merchant approval."),
            ("policy_use", "Confirm store policies", "Fulfillment, payment, and return policies are store-level business rules."),
            ("customer_service_boundary", "Confirm customer-service boundary", "Sensitive buyer promises, refunds, and disputes require human takeover."),
        ],
    }
    return [
        {
            "confirmation_id": f"confirm_{task_type.replace('.', '_')}_{action}",
            "action_type": action,
            "title": title,
            "reason": reason,
            "default_action": "hold",
            "options": ["approve", "edit", "reject"],
        }
        for action, title, reason in mapping.get(task_type, [])
    ]


def build_task_result(
    sample: dict[str, Any],
    expected: dict[str, Any],
    task: dict[str, Any],
    source_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    task_type = task["task_type"]
    expected_status = task.get("expected_status", "success")
    source_file = task.get("source_file")
    source_path = source_root / source_file if source_file else None

    if expected_status not in STATUS_ALLOWED:
        status = "failed_policy"
    else:
        status = expected_status

    text = ""
    synthetic_task = task_type == "confirmation.package" and not source_file
    file_exists = bool(source_path and source_path.exists())
    if file_exists and source_path:
        text = read_text(source_path)
    elif synthetic_task:
        text = build_synthetic_confirmation_text(expected)
    else:
        status = "failed_tool"

    started_at = finished_at = now_iso()
    result = {
        "task_id": f"{sample['sample_id']}::{task_type}",
        "task_type": task_type,
        "task_version": "2026-05-14",
        "status": status,
        "executor": "mock-agent",
        "executor_version": "0.1.0",
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": f"Mock converted {task_type} from {source_file or 'missing source'} with status {status}.",
        "report": {
            "source_file": str(source_path) if source_path else None,
            "source_file_exists": file_exists,
            "excerpt": normalize_excerpt(text) if text else "",
            "notes": task.get("notes", ""),
        },
        "source_records": [
            {
                "source_id": f"src_{task_type.replace('.', '_')}",
                "source_type": "hermes_closed_loop_sample",
                "title": source_file or task_type,
                "url": None,
                "captured_at": finished_at,
                "confidence": "medium" if status != "success" else "high",
                "used_for": [task_type],
                "note": "Imported from local Hermes/Jiejing acceptance sample, not from live platform execution.",
            }
        ],
        "missing_inputs": blocker_inputs(task_type),
        "risk_flags": risk_flags(task_type),
        "confirmation_items": confirmation_items(task_type),
        "next_tasks": [],
        "artifacts": [
            {
                "artifact_type": "markdown",
                "path": str(source_path) if source_path else None,
                "exists": file_exists,
                "synthetic": synthetic_task,
            }
        ],
        "audit": {
            "sample_id": sample["sample_id"],
            "sample_status": sample.get("sample_status"),
            "real_execution": sample.get("real_execution", {}),
            "source_chars": len(text),
            "source_lines": text.count("\n") + 1 if text else 0,
            "replacement_characters": text.count("\ufffd"),
            "must_not_do": expected.get("must_not_do", []),
        },
    }

    task_output = output_dir / "tasks" / f"{task['order']:02d}_{task_type.replace('.', '_')}.json"
    task_output.parent.mkdir(parents=True, exist_ok=True)
    task_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_synthetic_confirmation_text(expected: dict[str, Any]) -> str:
    blockers = expected.get("must_detect_blockers", [])
    must_not_do = expected.get("must_not_do", [])
    lines = [
        "Confirmation package synthesized from the acceptance summary.",
        "High-risk actions stay blocked until merchant approval.",
        "",
        "Detected blockers:",
    ]
    lines.extend(f"- {item}" for item in blockers)
    lines.extend(["", "Must not execute automatically:"])
    lines.extend(f"- {item}" for item in must_not_do)
    return "\n".join(lines)


def write_summary(sample: dict[str, Any], results: list[dict[str, Any]], output_dir: Path) -> None:
    status_counts: dict[str, int] = {}
    confirmation_count = 0
    blocker_count = 0
    for result in results:
        status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
        confirmation_count += len(result.get("confirmation_items", []))
        blocker_count += len(result.get("missing_inputs", []))

    summary = {
        "sample_id": sample["sample_id"],
        "executor": "mock-agent",
        "run_status": "success" if results else "failed_tool",
        "task_count": len(results),
        "status_counts": status_counts,
        "confirmation_item_count": confirmation_count,
        "missing_input_count": blocker_count,
        "real_execution": sample.get("real_execution", {}),
        "generated_at": now_iso(),
        "task_results": [f"tasks/{idx + 1:02d}_{result['task_type'].replace('.', '_')}.json" for idx, result in enumerate(results)],
    }
    (output_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Mock Runtime Run - {sample['sample_id']}",
        "",
        "This run used local acceptance samples only. No model, Hermes, eBay, payment, sourcing, or network calls were made.",
        "",
        f"- Task count: {len(results)}",
        f"- Status counts: {status_counts}",
        f"- Confirmation items: {confirmation_count}",
        f"- Missing inputs: {blocker_count}",
        "",
        "## Tasks",
        "",
    ]
    for result in results:
        lines.append(f"- `{result['task_type']}` -> `{result['status']}`: {result['summary']}")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    sample_dir = Path(args.sample_dir).resolve()
    task_sequence_path = sample_dir / "task-sequence.json"
    expected_path = sample_dir / "expected-result-summary.json"
    if not task_sequence_path.exists():
        print(f"FAIL missing task sequence: {task_sequence_path}", file=sys.stderr)
        return 2
    if not expected_path.exists():
        print(f"FAIL missing expected result summary: {expected_path}", file=sys.stderr)
        return 2

    sample = read_json(task_sequence_path)
    expected = read_json(expected_path)
    source_root = Path(sample["source_root"])
    if not source_root.exists():
        print(f"FAIL missing source root: {source_root}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve() if args.output_dir else sample_dir / "mock-runtime-run"
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir = output_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for old_task in tasks_dir.glob("*.json"):
        old_task.unlink()

    results = [build_task_result(sample, expected, task, source_root, output_dir) for task in sample.get("tasks", [])]
    write_summary(sample, results, output_dir)
    print(f"OK mock runtime completed: {output_dir}")
    print(f"tasks={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
