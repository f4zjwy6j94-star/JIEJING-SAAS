#!/usr/bin/env python3
"""Regression checks for Runtime long-term memory and creative contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import CreativeCapabilityProfile, ProductWorkflowRequest, SQLiteRuntimeRepository, ToolRegistry, build_memory_record, build_product_workflow
from jiejing_runtime.runtime import JiejingRuntime, RuntimeConfig


SAMPLE_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "runtime-long-term-memory"
RUN_DIR = SAMPLE_DIR / "insulated-bottle-memory-run"
DB_PATH = SAMPLE_DIR / "memory-test.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Insulated Stainless Steel Water Bottle",
            merchant_goal="Run a Jiejing-owned workflow and preserve safe lessons for future store automation.",
            project_id="memory-regression-bottle",
            stage="store_opened",
            platform="ebay",
            source_mode="manual_or_1688",
        )
    )
    runtime = JiejingRuntime(RuntimeConfig(adapter_name="jiejing-local", demo_mode=True, clean_output=True))
    summary = runtime.run_tasks(tasks, RUN_DIR, run_id="long-term-memory-regression")
    repo = SQLiteRuntimeRepository(DB_PATH)
    imported = repo.save_run_directory(summary.run_dir)
    if imported.get("results") != 11:
        return fail("memory regression run should import 11 results")

    memory_summary = repo.get_memory_summary()
    if memory_summary.get("record_count", 0) < 10:
        return fail("runtime should persist long-term memory candidates from results")
    listing_memories = repo.list_memories(task_type="listing.package", limit=10)
    if not listing_memories:
        return fail("listing.package should create reusable memory")
    if any("token" in item.get("content", "").lower() for item in repo.list_memories(limit=200)):
        return fail("long-term memory should not preserve credential-like content")
    unsafe = build_memory_record(
        scope_type="store",
        scope_id="demo_store",
        title="unsafe token",
        content="access_token=should_not_be_saved",
    )
    if unsafe is not None:
        return fail("unsafe memory content should be rejected")

    manual = repo.create_memory(
        {
            "scope_type": "store",
            "scope_id": "demo_store",
            "title": "Default confirmation preference",
            "content": "For this merchant, publishing, refund, ad budget, procurement payment, and policy edits require confirmation.",
            "tags": ["confirmation", "merchant-rule"],
            "priority": 90,
        }
    )
    if manual.get("memory_id") not in {item.get("memory_id") for item in repo.list_memories(scope_type="store", limit=20)}:
        return fail("manual safe memory should be queryable")

    creative = CreativeCapabilityProfile().to_dict()
    keys = {item.get("key") for item in creative.get("capabilities", [])}
    for key in {"open_design_method", "product_image_generation", "product_video_generation", "voiceover_and_script"}:
        if key not in keys:
            return fail(f"creative capability missing {key}")
    if creative.get("must_not_copy_closed_product_internals") is not True:
        return fail("creative profile should forbid copying closed product internals")

    tool_names = {item.get("name") for item in ToolRegistry().list_tools()}
    for name in {"runtime.long_term_memory", "asset.open_design_workflow", "asset.image_generation_provider", "asset.video_generation_provider"}:
        if name not in tool_names:
            return fail(f"tool registry missing {name}")

    print("PASS long_term_memory_and_creative_regression")
    print(f"memory_records={memory_summary.get('record_count')}")
    print(f"db_path={DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
