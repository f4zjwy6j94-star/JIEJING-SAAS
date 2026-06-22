#!/usr/bin/env python3
"""Regression checks for sanitized Runtime knowledge ingestion."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.knowledge import DEFAULT_KNOWLEDGE_PACK, KnowledgeBase
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow

def _resolve_sample_tasks_dir() -> Path:
    candidates = [
        ROOT / "output" / "jiejing-agent-runtime-samples" / "cable-clips-20260513" / "prepared-tasks" / "tasks",
        ROOT / "output" / "jiejing-agent-runtime-samples" / "self-check" / "sample-runtime-workflow" / "tasks",
        ROOT
        / "output"
        / "jiejing-agent-runtime-samples"
        / "full-stack-smoke"
        / "runtime-api-workflows"
        / "full-stack-smoke-stainless-tumbler"
        / "tasks",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    generated = candidates[1]
    generated.mkdir(parents=True, exist_ok=True)
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Generate a local Runtime regression sample without real execution.",
            project_id="self-check-runtime-workflow",
        )
    )
    for index, task in enumerate(tasks, start=1):
        task_name = str(task["task_type"]).replace(".", "_")
        (generated / f"{index:02d}_{task_name}.json").write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    return generated


TASKS_DIR = _resolve_sample_tasks_dir()
SAMPLE_DIR = TASKS_DIR.parents[1]
KNOWLEDGE_RUN_DIR = SAMPLE_DIR / "runtime-knowledge-test-run"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ingest_jiejing_knowledge.py")],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return fail("knowledge ingestion failed")

    if not DEFAULT_KNOWLEDGE_PACK.exists():
        return fail("knowledge pack was not written")
    pack_text = DEFAULT_KNOWLEDGE_PACK.read_text(encoding="utf-8")
    pack = json.loads(pack_text)
    if pack.get("item_count", 0) < 50:
        return fail("knowledge pack should include curated sources plus current Hermes shared notes, skills, and inventories")
    source_type_counts = {}
    for item in pack.get("items", []):
        source_type = item.get("source_type")
        source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
    for required_source_type in {
        "hermes_current_shared_note",
        "hermes_current_skill",
        "hermes_profile_inventory",
        "hermes_config_inventory",
    }:
        if required_source_type not in source_type_counts:
            return fail(f"knowledge pack missing {required_source_type}")
    if re.search(r"(?i)(refresh_token|access_token|authorization:|cookie:|bearer\s+[A-Za-z0-9])", pack_text):
        return fail("knowledge pack contains credential-like terms that should be redacted")
    if re.search(r"\b[A-Za-z0-9_./+=:-]{96,}\b", pack_text):
        return fail("knowledge pack contains a long secret-like value")

    knowledge = KnowledgeBase.load(DEFAULT_KNOWLEDGE_PACK)
    summary = knowledge.summary()
    if summary.get("source_types", {}).get("hermes_current_skill", 0) < 5:
        return fail("knowledge summary should expose current Hermes skills")
    if summary.get("redaction_report", {}).get("secret_assignments_redacted", 0) <= 0:
        return fail("knowledge ingestion should report secret-field redactions")
    market_items = knowledge.query(role="market-manager", task_type="market.report", limit=3)
    if not market_items:
        return fail("market-manager knowledge query returned no items")
    listing_items = knowledge.query(role="product-manager", task_type="listing.package", limit=3)
    if not listing_items:
        return fail("product-manager knowledge query returned no items")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_runtime_cli.py"),
            "run",
            "--tasks-dir",
            str(TASKS_DIR),
            "--output-dir",
            str(KNOWLEDGE_RUN_DIR),
            "--adapter",
            "jiejing-local",
            "--run-id",
            "runtime-knowledge-regression",
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        return fail("runtime run with knowledge failed")

    market_result_path = KNOWLEDGE_RUN_DIR / "results" / "03_market_report.json"
    if not market_result_path.exists():
        return fail("missing market report result")
    market_result = json.loads(market_result_path.read_text(encoding="utf-8"))
    if not market_result.get("report", {}).get("runtime_knowledge"):
        return fail("runtime result did not include knowledge references")
    source_types = {item.get("source_type") for item in market_result.get("source_records", [])}
    if "runtime_sanitized_knowledge" not in source_types:
        return fail("runtime source records should include sanitized knowledge references")

    print("PASS runtime_knowledge_regression")
    print(f"knowledge_pack={DEFAULT_KNOWLEDGE_PACK}")
    print(f"knowledge_items={pack.get('item_count')}")
    print(f"knowledge_run_dir={KNOWLEDGE_RUN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
