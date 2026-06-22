#!/usr/bin/env python3
"""Validate a Hermes team_bus result file before using it in Jiejing reports.

This checker is intentionally small. It does not read credentials or call APIs.
It only verifies that a role result is usable enough for a SaaS work record.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Hermes team_bus result.")
    parser.add_argument("result_file", help="Path to a team_bus *_result.md file")
    parser.add_argument(
        "--heading",
        action="append",
        default=[],
        help="Required heading or section text. May be passed multiple times.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.result_file)
    if not path.exists():
        print(f"FAIL missing_file path={path}")
        return 2

    text = path.read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    warnings: list[str] = []

    status_match = re.search(r"(?im)^status:\s*(\w+)\s*$", text)
    status = status_match.group(1).upper() if status_match else "UNKNOWN"
    if status != "SUCCESS":
        failures.append(f"status_not_success:{status}")

    result_marker = "## Result"
    body = text.split(result_marker, 1)[1].strip() if result_marker in text else text.strip()
    if len(body) < 200:
        failures.append("body_too_short")

    for heading in args.heading:
        if heading.lower() not in text.lower():
            failures.append(f"missing_heading:{heading}")

    if "timed out after" in text.lower():
        failures.append("timeout_detected")
    if "returned no body output" in text.lower():
        failures.append("empty_output_detected")

    if "/shared/team_bus/outbox/" in text.replace("\\", "/"):
        warnings.append("role_report_mentions_non_role_outbox_path")

    if "\ufffd" in text:
        warnings.append("replacement_character_detected")

    print(f"file={path}")
    print(f"status={status}")
    print(f"chars={len(text)}")
    if warnings:
        print("warnings=" + ",".join(warnings))
    if failures:
        print("failures=" + ",".join(failures))
        return 1

    print("result=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
