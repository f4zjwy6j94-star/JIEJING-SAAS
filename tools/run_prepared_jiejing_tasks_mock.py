#!/usr/bin/env python3
"""Run prepared JiejingTask files through the deterministic mock adapter.

This proves the future backend shape: prepared task inputs go in, standard
JiejingTaskResult files come out. It does not call Hermes, models, eBay,
payment, sourcing, logistics, or any network service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jiejing_agent_runtime_mock import build_task_result, read_json, write_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prepared JiejingTask files with the mock adapter.")
    parser.add_argument("prepared_tasks_dir", help="Directory containing prepared task JSON files")
    parser.add_argument(
        "--sample-dir",
        help="Sample directory containing expected-result-summary.json. Defaults to <prepared_tasks_dir>/../..",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory. Defaults to <sample_dir>/prepared-mock-run",
    )
    return parser.parse_args()


def iter_task_files(path: Path) -> list[Path]:
    return sorted(path.glob("*.json"))


def prepared_to_sequence_task(prepared: dict[str, Any], order: int) -> dict[str, Any]:
    task_input = prepared.get("input", {})
    return {
        "order": order,
        "task_type": prepared["task_type"],
        "source_file": task_input.get("sample_source_file"),
        "expected_status": task_input.get("expected_status", "success"),
        "notes": task_input.get("notes", ""),
    }


def sample_from_prepared(first_task: dict[str, Any], sample_dir: Path) -> dict[str, Any]:
    context = first_task.get("context", {})
    execution_boundary = context.get("execution_boundary", {})
    return {
        "sample_id": context.get("sample_id") or first_task.get("project_id") or sample_dir.name,
        "sample_name": context.get("sample_name") or first_task.get("project_id") or sample_dir.name,
        "source_root": context.get("source_root"),
        "platform": first_task.get("platform", "ebay"),
        "sample_status": context.get("sample_status", "prepared_task_run"),
        "real_execution": execution_boundary
        or {
            "published_to_ebay": False,
            "procurement_paid": False,
            "refund_executed": False,
            "ad_budget_changed": False,
            "store_policy_changed": False,
        },
    }


def clean_output(output_dir: Path) -> None:
    tasks_dir = output_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for old_task in tasks_dir.glob("*.json"):
        old_task.unlink()


def main() -> int:
    args = parse_args()
    prepared_tasks_dir = Path(args.prepared_tasks_dir).resolve()
    if not prepared_tasks_dir.exists():
        print(f"FAIL missing prepared tasks dir: {prepared_tasks_dir}", file=sys.stderr)
        return 2

    task_files = iter_task_files(prepared_tasks_dir)
    if not task_files:
        print(f"FAIL no prepared task JSON files: {prepared_tasks_dir}", file=sys.stderr)
        return 2

    sample_dir = Path(args.sample_dir).resolve() if args.sample_dir else prepared_tasks_dir.parents[1]
    expected_path = sample_dir / "expected-result-summary.json"
    if not expected_path.exists():
        print(f"FAIL missing expected summary: {expected_path}", file=sys.stderr)
        return 2

    prepared_tasks = [json.loads(path.read_text(encoding="utf-8")) for path in task_files]
    sample = sample_from_prepared(prepared_tasks[0], sample_dir)
    if not sample.get("source_root"):
        print("FAIL prepared task context missing source_root", file=sys.stderr)
        return 2

    expected = read_json(expected_path)
    source_root = Path(sample["source_root"])
    if not source_root.exists():
        print(f"FAIL missing source root: {source_root}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve() if args.output_dir else sample_dir / "prepared-mock-run"
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_output(output_dir)

    results = []
    for order, prepared in enumerate(prepared_tasks, start=1):
        sequence_task = prepared_to_sequence_task(prepared, order)
        results.append(build_task_result(sample, expected, sequence_task, source_root, output_dir))

    write_summary(sample, results, output_dir)
    print(f"OK prepared mock run completed: {output_dir}")
    print(f"tasks={len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
