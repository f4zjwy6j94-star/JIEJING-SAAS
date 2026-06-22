#!/usr/bin/env python3
"""Validate generated Jiejing task result files.

If jsonschema is installed, this validator also checks the formal result schema.
It still keeps dependency-light fallback checks so it can run on a clean machine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {
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

REQUIRED_FIELDS = {
    "task_id",
    "task_type",
    "task_version",
    "status",
    "executor",
    "summary",
    "report",
    "source_records",
    "missing_inputs",
    "risk_flags",
    "confirmation_items",
    "next_tasks",
    "artifacts",
    "audit",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Jiejing task result files.")
    parser.add_argument("path", help="A task result JSON file or a directory containing task JSON files")
    parser.add_argument(
        "--schema",
        help="Optional jiejing-task-result.schema.json path. Defaults to ../schemas/jiejing-task-result.schema.json",
    )
    return parser.parse_args()


def iter_json_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("*.json"))


def load_schema(schema_path: Path) -> dict[str, Any] | None:
    if not schema_path.exists():
        return None
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def jsonschema_errors(data: dict[str, Any], schema: dict[str, Any] | None) -> list[str]:
    if schema is None:
        return []
    try:
        import jsonschema  # type: ignore
    except Exception:
        return []
    validator = jsonschema.Draft202012Validator(schema)
    return [f"schema:{error.message}" for error in sorted(validator.iter_errors(data), key=str)]


def validate_file(path: Path, schema: dict[str, Any] | None) -> list[str]:
    failures: list[str] = []
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - command-line guard
        return [f"invalid_json:{exc}"]

    failures.extend(jsonschema_errors(data, schema))

    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        failures.append("missing_fields:" + ",".join(missing))

    status = data.get("status")
    if status not in ALLOWED_STATUSES:
        failures.append(f"unknown_status:{status}")

    if not data.get("task_id"):
        failures.append("empty_task_id")
    if not data.get("task_type"):
        failures.append("empty_task_type")
    if not data.get("summary"):
        failures.append("empty_summary")

    source_records = data.get("source_records")
    if not isinstance(source_records, list) or not source_records:
        failures.append("missing_source_records")

    for list_field in ["missing_inputs", "risk_flags", "confirmation_items", "next_tasks", "artifacts"]:
        if not isinstance(data.get(list_field), list):
            failures.append(f"{list_field}_not_list")

    real_execution = data.get("audit", {}).get("real_execution", {})
    for forbidden in ["published_to_ebay", "procurement_paid", "refund_executed", "ad_budget_changed", "store_policy_changed"]:
        if real_execution.get(forbidden):
            failures.append(f"forbidden_real_execution:{forbidden}")

    return failures


def main() -> int:
    args = parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL missing path: {path}", file=sys.stderr)
        return 2

    default_schema = Path(__file__).resolve().parents[1] / "schemas" / "jiejing-task-result.schema.json"
    schema_path = Path(args.schema).resolve() if args.schema else default_schema
    schema = load_schema(schema_path)

    files = iter_json_files(path)
    if not files:
        print(f"FAIL no json files found: {path}", file=sys.stderr)
        return 2

    failed = 0
    for file_path in files:
        failures = validate_file(file_path, schema)
        if failures:
            failed += 1
            print(f"FAIL {file_path}: {';'.join(failures)}")
        else:
            print(f"PASS {file_path}")

    if failed:
        print(f"result=FAIL failed={failed} total={len(files)}")
        return 1
    print(f"result=PASS total={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
