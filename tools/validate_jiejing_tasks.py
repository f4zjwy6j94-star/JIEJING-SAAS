#!/usr/bin/env python3
"""Validate prepared JiejingTask input files.

The validator is intentionally dependency-light. If jsonschema is installed it
uses the formal schema; otherwise it falls back to core field checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ALLOWED_TASK_TYPES = {
    "ceo.intake",
    "market.data_packet",
    "market.report",
    "source.match",
    "listing.package",
    "asset.brief",
    "customer.learn_product",
    "finance.review",
    "confirmation.package",
    "ceo.final_report",
    "owner.review",
}

REQUIRED_FIELDS = {
    "task_id",
    "task_type",
    "task_version",
    "user_id",
    "company_id",
    "store_id",
    "platform",
    "stage",
    "input",
    "timeout_seconds",
    "retry_policy",
}

HIGH_RISK_ACTIONS = {
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
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate prepared JiejingTask input files.")
    parser.add_argument("path", help="A task JSON file or a directory containing task JSON files")
    parser.add_argument(
        "--schema",
        help="Optional jiejing-task.schema.json path. Defaults to ../schemas/jiejing-task.schema.json",
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

    task_type = data.get("task_type")
    if task_type not in ALLOWED_TASK_TYPES:
        failures.append(f"unknown_task_type:{task_type}")

    if not data.get("task_id"):
        failures.append("empty_task_id")
    if not isinstance(data.get("input"), dict):
        failures.append("input_not_object")
    if not isinstance(data.get("context", {}), dict):
        failures.append("context_not_object")
    if not isinstance(data.get("source_policy", {}), dict):
        failures.append("source_policy_not_object")
    if not isinstance(data.get("risk_policy", {}), dict):
        failures.append("risk_policy_not_object")
    if not isinstance(data.get("output_contract", {}), dict):
        failures.append("output_contract_not_object")

    timeout = data.get("timeout_seconds")
    if not isinstance(timeout, int) or timeout <= 0:
        failures.append("invalid_timeout_seconds")

    retry = data.get("retry_policy")
    if not isinstance(retry, dict):
        failures.append("retry_policy_not_object")
    else:
        if "max_retries" not in retry:
            failures.append("retry_policy_missing_max_retries")
        if "split_on_timeout" not in retry:
            failures.append("retry_policy_missing_split_on_timeout")

    source_policy = data.get("source_policy", {})
    if source_policy.get("must_label_sources") is not True:
        failures.append("source_policy_must_label_sources_not_true")

    risk_policy = data.get("risk_policy", {})
    required_actions = set(risk_policy.get("confirmation_required_actions", []))
    missing_actions = sorted(HIGH_RISK_ACTIONS - required_actions)
    if missing_actions:
        failures.append("risk_policy_missing_confirmation_actions:" + ",".join(missing_actions))
    if risk_policy.get("default_action") != "hold":
        failures.append("risk_policy_default_action_not_hold")

    output_contract = data.get("output_contract", {})
    if output_contract.get("empty_output_allowed") is not False:
        failures.append("output_contract_empty_output_not_blocked")
    if output_contract.get("merchant_readable") is not True:
        failures.append("output_contract_not_merchant_readable")

    return failures


def main() -> int:
    args = parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL missing path: {path}", file=sys.stderr)
        return 2

    default_schema = Path(__file__).resolve().parents[1] / "schemas" / "jiejing-task.schema.json"
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
