#!/usr/bin/env python3
"""Regression for honest Hermes replacement readiness scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import ProductWorkflowRequest, SQLiteRuntimeRepository, build_product_workflow, build_progress_scorecard, build_replacement_readiness  # noqa: E402
from jiejing_runtime.runtime import JiejingRuntime, RuntimeConfig  # noqa: E402


SAMPLE_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "replacement-readiness"
RUN_DIR = SAMPLE_DIR / "replacement-readiness-run"
DB_PATH = SAMPLE_DIR / "replacement-readiness.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Replacement Readiness Sample Product",
            merchant_goal="Verify that self-owned Runtime readiness is not overstated as full Hermes replacement.",
            project_id="replacement-readiness-regression",
            stage="store_opened",
            platform="ebay",
            source_mode="manual_or_1688",
        )
    )
    runtime = JiejingRuntime(RuntimeConfig(adapter_name="jiejing-local", demo_mode=True, clean_output=True))
    summary = runtime.run_tasks(tasks, RUN_DIR, run_id="replacement-readiness-regression")
    repo = SQLiteRuntimeRepository(DB_PATH)
    repo.save_run_directory(summary.run_dir)

    readiness = build_replacement_readiness(repo)
    production_percent = int(readiness.get("production_replacement_percent") or 0)
    local_percent = int(readiness.get("local_low_risk_takeover_percent") or 0)
    if readiness.get("can_replace_hermes_in_production") is not False:
        return fail("replacement readiness must not claim production replacement")
    if production_percent >= local_percent:
        return fail("production replacement percent must stay below local low-risk takeover percent")
    if production_percent > 45:
        return fail(f"production replacement percent is too optimistic: {production_percent}")
    if not readiness.get("hard_blockers"):
        return fail("replacement readiness should list hard blockers")

    scorecard = build_progress_scorecard(repo)
    replacement_track = next(
        (item for item in scorecard.get("tracks", []) if item.get("key") == "replace_internal_runtime_capability"),
        None,
    )
    if not replacement_track:
        return fail("progress scorecard missing replacement track")
    if replacement_track.get("production_equivalent_percent") != production_percent:
        return fail("scorecard production equivalent should come from replacement readiness evaluator")
    if "替代 Hermes 能力" in str(replacement_track.get("label")):
        return fail("replacement label should not imply mature Hermes replacement")
    if "低风险" not in str(replacement_track.get("label")):
        return fail("replacement label should explicitly say low-risk takeover")

    print("PASS replacement_readiness_regression")
    print(f"local_low_risk_takeover={local_percent}")
    print(f"production_replacement={production_percent}")
    print(f"db_path={DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
