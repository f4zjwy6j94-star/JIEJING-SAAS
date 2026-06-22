#!/usr/bin/env python3
"""CLI for the Jiejing Agent Runtime MVP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import JiejingRuntime, RuntimeConfig, SQLiteRuntimeRepository
from jiejing_runtime.api_server import RuntimeApiServer
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow
from jiejing_runtime.hermes_handoff import HermesHandoffResultImporter
from jiejing_runtime.shadow_compare import RuntimeComparisonScorer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Jiejing Agent Runtime MVP.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run prepared JiejingTask JSON files.")
    run_parser.add_argument("--tasks-dir", required=True, help="Directory containing prepared task JSON files")
    run_parser.add_argument("--output-dir", required=True, help="Directory for runtime output")
    run_parser.add_argument(
        "--adapter",
        choices=["mock", "jiejing-local", "jiejing-llm", "jiejing-deepseek", "hermes-plan", "hermes-shadow", "hermes-file"],
        default="mock",
    )
    run_parser.add_argument("--run-id", help="Optional run id")
    run_parser.add_argument("--stop-on-failure", action="store_true")

    workflow_parser = subparsers.add_parser("run-workflow", help="Create and run a product workflow without prepared task files.")
    workflow_parser.add_argument("--product", required=True, help="Product/category to test")
    workflow_parser.add_argument("--goal", required=True, help="Merchant goal")
    workflow_parser.add_argument("--output-dir", required=True, help="Directory for runtime output")
    workflow_parser.add_argument(
        "--adapter",
        choices=["mock", "jiejing-local", "jiejing-llm", "jiejing-deepseek", "hermes-plan", "hermes-shadow", "hermes-file"],
        default="jiejing-local",
    )
    workflow_parser.add_argument("--run-id", help="Optional run id")
    workflow_parser.add_argument("--stage", default="store_opened")
    workflow_parser.add_argument("--source-mode", default="manual_or_1688")

    import_parser = subparsers.add_parser("import-run", help="Import a runtime run directory into SQLite.")
    import_parser.add_argument("--run-dir", required=True, help="Directory containing run.json")
    import_parser.add_argument("--db", required=True, help="SQLite database path")

    list_parser = subparsers.add_parser("list-runs", help="List runs from SQLite.")
    list_parser.add_argument("--db", required=True, help="SQLite database path")

    serve_parser = subparsers.add_parser("serve", help="Serve local Runtime API over HTTP.")
    serve_parser.add_argument("--db", required=True, help="SQLite database path")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    subparsers.add_parser("ingest-knowledge", help="Build the sanitized Jiejing Runtime knowledge pack.")

    import_handoff_parser = subparsers.add_parser("import-handoff-result", help="Import a Hermes handoff markdown output into JiejingTaskResult JSON.")
    import_handoff_parser.add_argument("--packet-json", required=True, help="Handoff packet JSON created by hermes-file adapter")
    import_handoff_parser.add_argument("--role-output", required=True, help="Hermes/team_bus role markdown output")
    import_handoff_parser.add_argument("--output-json", required=True, help="Destination JiejingTaskResult JSON")

    compare_parser = subparsers.add_parser("compare-results", help="Compare a Jiejing result JSON with a Hermes/imported result JSON.")
    compare_parser.add_argument("--jiejing-result", required=True, help="Jiejing Runtime result JSON")
    compare_parser.add_argument("--hermes-result", required=True, help="Hermes shadow/imported result JSON")
    compare_parser.add_argument("--output-json", help="Optional destination comparison JSON")
    return parser.parse_args()


def run_command(args: argparse.Namespace) -> int:
    tasks_dir = Path(args.tasks_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not tasks_dir.exists():
        print(f"FAIL missing tasks dir: {tasks_dir}", file=sys.stderr)
        return 2

    task_files = sorted(tasks_dir.glob("*.json"))
    if not task_files:
        print(f"FAIL no task JSON files in: {tasks_dir}", file=sys.stderr)
        return 2

    runtime = JiejingRuntime(
        RuntimeConfig(
            adapter_name=args.adapter,
            demo_mode=True,
            stop_on_failure=args.stop_on_failure,
            clean_output=True,
        )
    )
    summary = runtime.run_task_files(task_files, output_dir, run_id=args.run_id)
    print(f"OK Jiejing Runtime completed: {summary.run_dir}")
    print(f"tasks={summary.task_count}")
    print(f"status={summary.run_status}")
    print(f"run_json={summary.run_json}")
    print(f"summary_md={summary.summary_md}")
    return 0 if not summary.run_status.startswith("partial_failure") else 1


def run_workflow_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    request = ProductWorkflowRequest(
        product=args.product,
        merchant_goal=args.goal,
        project_id=args.run_id or "",
        stage=args.stage,
        source_mode=args.source_mode,
    )
    tasks = build_product_workflow(request)
    runtime = JiejingRuntime(
        RuntimeConfig(
            adapter_name=args.adapter,
            demo_mode=True,
            stop_on_failure=False,
            clean_output=True,
        )
    )
    summary = runtime.run_tasks(tasks, output_dir, run_id=args.run_id)
    print(f"OK Jiejing Runtime workflow completed: {summary.run_dir}")
    print(f"tasks={summary.task_count}")
    print(f"status={summary.run_status}")
    print(f"run_json={summary.run_json}")
    print(f"summary_md={summary.summary_md}")
    return 0 if not summary.run_status.startswith("partial_failure") else 1


def import_run_command(args: argparse.Namespace) -> int:
    repository = SQLiteRuntimeRepository(Path(args.db).resolve())
    result = repository.save_run_directory(Path(args.run_dir).resolve())
    print("OK imported run")
    print(f"run_id={result['run_id']}")
    print(f"tasks={result['tasks']}")
    print(f"results={result['results']}")
    print(f"audit_events={result['audit_events']}")
    return 0


def list_runs_command(args: argparse.Namespace) -> int:
    repository = SQLiteRuntimeRepository(Path(args.db).resolve())
    runs = repository.list_runs()
    print(json_dumps({"runs": runs}))
    return 0


def serve_command(args: argparse.Namespace) -> int:
    RuntimeApiServer(Path(args.db).resolve(), host=args.host, port=args.port).serve_forever()
    return 0


def ingest_knowledge_command() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from ingest_jiejing_knowledge import main as ingest_main

    return int(ingest_main())


def import_handoff_result_command(args: argparse.Namespace) -> int:
    importer = HermesHandoffResultImporter()
    result = importer.import_markdown(Path(args.packet_json).resolve(), Path(args.role_output).resolve())
    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    import json

    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK imported Hermes handoff result: {output_json}")
    print(f"task_id={result['task_id']}")
    print(f"status={result['status']}")
    print(f"confirmations={len(result.get('confirmation_items', []))}")
    print(f"missing_inputs={len(result.get('missing_inputs', []))}")
    return 0


def compare_results_command(args: argparse.Namespace) -> int:
    import json

    jiejing_result = json.loads(Path(args.jiejing_result).resolve().read_text(encoding="utf-8"))
    hermes_result = json.loads(Path(args.hermes_result).resolve().read_text(encoding="utf-8"))
    comparison = RuntimeComparisonScorer().compare(jiejing_result, hermes_result)
    if args.output_json:
        output_json = Path(args.output_json).resolve()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"comparison_json={output_json}")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0


def json_dumps(data: object) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()
    if args.command == "run":
        return run_command(args)
    if args.command == "run-workflow":
        return run_workflow_command(args)
    if args.command == "import-run":
        return import_run_command(args)
    if args.command == "list-runs":
        return list_runs_command(args)
    if args.command == "serve":
        return serve_command(args)
    if args.command == "ingest-knowledge":
        return ingest_knowledge_command()
    if args.command == "import-handoff-result":
        return import_handoff_result_command(args)
    if args.command == "compare-results":
        return compare_results_command(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
