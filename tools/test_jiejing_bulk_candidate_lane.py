#!/usr/bin/env python3
"""Regression for bulk candidate lanes respecting critical source gaps."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    marker = "function saasBulkCandidateLane"
    assert marker in app_js, "bulk candidate lane classifier is missing"

    start = app_js.index(marker)
    end = app_js.index("\nfunction saasBulkCandidateToListingDraft", start)
    function_source = app_js[start:end]
    node_script = f"""
{function_source}
const cases = [
  [{{ score: 78, selected: true, missing_facts: ["采购成本", "库存"] }}, "info"],
  [{{ score: 78, selected: false, missing_facts: ["货源链接或图片"] }}, "info"],
  [{{ score: 78, selected: true, missing_facts: [] }}, "test"],
  [{{ score: 52, selected: true, missing_facts: ["库存"] }}, "blocked"],
  [{{ score: 66, selected: false, missing_facts: [] }}, "info"],
];
for (const [candidate, expected] of cases) {{
  const actual = saasBulkCandidateLane(candidate);
  if (actual !== expected) {{
    throw new Error(`expected ${{expected}}, received ${{actual}} for ${{JSON.stringify(candidate)}}`);
  }}
}}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    print("PASS jiejing_bulk_candidate_lane")


if __name__ == "__main__":
    main()
