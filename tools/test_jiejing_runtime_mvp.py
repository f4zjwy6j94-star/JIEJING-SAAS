#!/usr/bin/env python3
"""Light regression test for the Jiejing Runtime MVP."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import (
    ExecutionRequest,
    ExecutionService,
    ProductWorkflowRequest,
    SQLiteRuntimeRepository,
    ToolRegistry,
    build_product_workflow,
    model_client_status_from_env,
)

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
MOCK_RUN_DIR = SAMPLE_DIR / "runtime-mvp-test-run"
LOCAL_RUN_DIR = SAMPLE_DIR / "runtime-jiejing-local-test-run"
TEST_DB = SAMPLE_DIR / "runtime-mvp-test.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def run_cli(adapter: str, run_dir: Path, run_id: str) -> int:
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "run",
        "--tasks-dir",
        str(TASKS_DIR),
        "--output-dir",
        str(run_dir),
        "--adapter",
        adapter,
        "--run-id",
        run_id,
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail("runtime cli returned non-zero")
    return 0


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_listing_facts() -> dict:
    return {
        "product": "Backflow Incense Burner",
        "title_cn": "倒流香炉",
        "ebay_title": "Backflow Incense Burner Ceramic Waterfall Smoke Holder Home Decor",
        "source_link": "https://detail.1688.com/offer/demo-backflow-incense-burner",
        "purchase_price": "US $22.99",
        "quantity": "20",
        "source_location": "Fujian, China",
        "package_dimensions": "21 x 18 x 14 cm",
        "package_weight": "620 g",
        "material": "Ceramic",
        "included": "Incense cones not included",
        "quality_checks": "Fragile packaging, breakage replacement, no invoice dropship, and image consistency checked.",
        "category_id": "20687",
        "fulfillment_policy_id": "fulfillmentPolicyId DEMO-FULFILLMENT-001 authorized store default",
        "payment_policy_id": "paymentPolicyId DEMO-PAYMENT-001 authorized store default",
        "return_policy_id": "returnPolicyId DEMO-RETURN-001 authorized store default",
    }


def main() -> int:
    if not TASKS_DIR.exists():
        return fail(f"missing tasks dir: {TASKS_DIR}")

    result = run_cli("mock", MOCK_RUN_DIR, "runtime-mvp-regression")
    if result:
        return result

    result = validate_run(MOCK_RUN_DIR, expected_adapter="jiejing-mock-agent")
    if result:
        return result

    result = run_cli("jiejing-local", LOCAL_RUN_DIR, "runtime-jiejing-local-regression")
    if result:
        return result
    result = validate_run(LOCAL_RUN_DIR, expected_adapter="jiejing-agent")
    if result:
        return result

    result = validate_execution_boundary()
    if result:
        return result
    result = validate_model_boundary()
    if result:
        return result
    result = validate_repository()
    if result:
        return result
    result = validate_tool_registry()
    if result:
        return result
    result = validate_api_server()
    if result:
        return result

    print("PASS runtime_mvp_regression")
    print(f"mock_run_dir={MOCK_RUN_DIR}")
    print(f"local_run_dir={LOCAL_RUN_DIR}")
    return 0


def validate_repository() -> int:
    if TEST_DB.exists():
        TEST_DB.unlink()
    repository = SQLiteRuntimeRepository(TEST_DB)
    imported = repository.save_run_directory(LOCAL_RUN_DIR)
    if imported.get("run_id") != "runtime-jiejing-local-regression":
        return fail("repository imported wrong run_id")
    runs = repository.list_runs()
    if len(runs) != 1:
        return fail("repository should list exactly one test run")
    run = repository.get_run("runtime-jiejing-local-regression")
    if not run or run.get("task_count") != 11:
        return fail("repository get_run failed")
    results = repository.get_results("runtime-jiejing-local-regression")
    if len(results) != 11:
        return fail("repository should store 11 results")
    validation_summary = repository.get_validation_summary("runtime-jiejing-local-regression")
    if "validations" not in validation_summary or validation_summary.get("run_id") != "runtime-jiejing-local-regression":
        return fail("repository should return validation summary envelope")
    if validation_summary.get("validation_count", 0) < 6:
        return fail("repository validation summary should include role package validations")
    applied = repository.apply_listing_facts(
        "runtime-jiejing-local-regression",
        facts=sample_listing_facts(),
        updated_by="regression_test",
    )
    if applied.get("validation", {}).get("status") != "ready_for_confirmation_review":
        return fail("listing facts should revalidate listing package as ready for confirmation")
    if applied.get("result_status") != "blocked_confirmation_required":
        return fail("revalidated listing package should still be held for confirmation")
    validation_summary = repository.get_validation_summary("runtime-jiejing-local-regression")
    listing_validations = [
        item
        for item in validation_summary.get("validations", [])
        if item.get("validation_key") == "listing_validation"
    ]
    if not listing_validations or listing_validations[0].get("validation_status") != "ready_for_confirmation_review":
        return fail("repository validation summary should reflect revalidated listing package")
    confirmations = repository.get_confirmations("runtime-jiejing-local-regression")
    if len(confirmations) < 5:
        return fail("repository should store confirmation items")
    decision = repository.record_confirmation_decision(
        run_id="runtime-jiejing-local-regression",
        confirmation_id=confirmations[0]["confirmation_id"],
        decision="approve",
        decided_by="merchant_demo",
        decided_at="2026-05-14T00:00:00+08:00",
        note="regression test only",
    )
    if decision.get("execution_status") != "held_for_execution_service":
        return fail("confirmation decision should be held for execution service")
    execution = repository.execute_confirmation_decision(
        run_id="runtime-jiejing-local-regression",
        confirmation_id=confirmations[0]["confirmation_id"],
        requested_by="merchant_demo",
    )
    if execution.get("execution_result", {}).get("status") != "simulated_no_platform_write":
        return fail("approved confirmation should enter execution service demo boundary")
    if execution.get("real_execution", {}).get("published_to_ebay") is not False:
        return fail("repository execution service must not mark real eBay publish")
    execution_results = repository.get_execution_results("runtime-jiejing-local-regression")
    if len(execution_results) != 1:
        return fail("repository should store execution service result")
    decisions = repository.get_confirmation_decisions("runtime-jiejing-local-regression")
    if len(decisions) != 1:
        return fail("repository should store confirmation decision")
    if decisions[0].get("execution_status") != "simulated_no_platform_write":
        return fail("confirmation decision should be updated with execution status")
    audit = repository.get_audit_events("runtime-jiejing-local-regression")
    if len(audit) < 20:
        return fail("repository should store audit events")
    return 0


def validate_tool_registry() -> int:
    registry = ToolRegistry()
    tools = registry.list_tools()
    required = {"web.public_search", "ebay.read_only", "ebay.execution", "sourcing.1688_read"}
    names = {tool["name"] for tool in tools}
    missing = required - names
    if missing:
        return fail("tool registry missing: " + ",".join(sorted(missing)))
    execution_tool = registry.get("ebay.execution")
    if execution_tool is None or not execution_tool.requires_confirmation:
        return fail("ebay.execution must require confirmation")
    if registry.enabled_for_task("market.report"):
        return fail("MVP tools should default to disabled")
    return 0


def validate_model_boundary() -> int:
    status = model_client_status_from_env()
    if "api_key" in status:
        return fail("model status must not expose raw api key")
    if status.get("secret_exposed") is not False:
        return fail("model status must explicitly avoid secret exposure")
    if not status.get("client"):
        return fail("model status should include selected client")
    return 0


def validate_api_server() -> int:
    port = 8766
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "serve",
        "--db",
        str(TEST_DB),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                health = fetch_json(f"{base_url}/health")
                if health.get("status") == "ok":
                    break
            except Exception:
                time.sleep(0.1)
        else:
            return fail("api server did not become healthy")

        runs = fetch_json(f"{base_url}/runs")
        if not runs.get("runs"):
            return fail("api /runs should return imported run")
        model_status = fetch_json(f"{base_url}/model-status")
        if "api_key" in json.dumps(model_status):
            return fail("api model status must not expose raw key")
        if not model_status.get("model_status", {}).get("client"):
            return fail("api model status should expose selected model client")
        provider_status = fetch_json(f"{base_url}/provider-status")
        if "api_key" in json.dumps(provider_status):
            return fail("api provider status must not expose raw key")
        if provider_status.get("secret_exposed") is not False:
            return fail("api provider status should explicitly avoid secret exposure")
        if not provider_status.get("providers", {}).get("public_search_tavily", {}).get("provider"):
            return fail("api provider status should include tavily public search provider")
        if not provider_status.get("providers", {}).get("media_fal", {}).get("provider"):
            return fail("api provider status should include fal media provider")
        if not provider_status.get("providers", {}).get("ebay", {}).get("provider"):
            return fail("api provider status should include ebay provider map")
        agent_job_specs = fetch_json(f"{base_url}/agent-job-specs")
        if agent_job_specs.get("secret_exposed") is not False:
            return fail("agent job specs should explicitly avoid secret exposure")
        if agent_job_specs.get("agent_job_specs", {}).get("role_count") != 7:
            return fail("agent job specs should expose 7 owned roles")
        for role in agent_job_specs.get("agent_job_specs", {}).get("roles", []):
            if not role.get("input_requirements") or not role.get("stop_conditions"):
                return fail("agent job specs should expose input requirements and stop conditions")
        progress = fetch_json(f"{base_url}/progress-scorecard")
        scorecard = progress.get("progress_scorecard", {})
        if scorecard.get("secret_exposed") is not False:
            return fail("progress scorecard must not expose secrets")
        tracks = scorecard.get("tracks", [])
        if len(tracks) != 5:
            return fail("progress scorecard should expose 5 project tracks")
        if scorecard.get("summary", {}).get("can_claim_production_ready") is not False:
            return fail("progress scorecard must not claim production-ready")
        if not all("remaining_to_real_100" in item for item in tracks):
            return fail("progress scorecard should explain remaining real-100 gaps")
        run_id = runs["runs"][0]["run_id"]
        confirmations = fetch_json(f"{base_url}/runs/{run_id}/confirmations")
        if len(confirmations.get("confirmations", [])) < 5:
            return fail("api confirmations should return confirmation items")
        validation_summary = fetch_json(f"{base_url}/runs/{run_id}/validation-summary")
        if validation_summary.get("run_id") != run_id or "validations" not in validation_summary:
            return fail("api validation summary should return validation envelope")
        if validation_summary.get("validation_count", 0) < 6:
            return fail("api validation summary should include role package validations")
        listing_update = post_json(
            f"{base_url}/runs/{run_id}/listing-facts",
            {"facts": sample_listing_facts(), "updated_by": "api_regression"},
        )
        if listing_update.get("validation", {}).get("status") != "ready_for_confirmation_review":
            return fail("api listing facts should revalidate listing package")
        if listing_update.get("result_status") != "blocked_confirmation_required":
            return fail("api listing facts should keep real publish confirmation-gated")
        validation_summary = fetch_json(f"{base_url}/runs/{run_id}/validation-summary")
        listing_validations = [
            item
            for item in validation_summary.get("validations", [])
            if item.get("validation_key") == "listing_validation"
        ]
        if not listing_validations or listing_validations[0].get("validation_status") != "ready_for_confirmation_review":
            return fail("api validation summary should reflect listing facts update")
        options = options_headers(f"{base_url}/runs")
        if options.get("status") != 204:
            return fail("api OPTIONS should return 204 for browser CORS preflight")
        if options.get("access-control-allow-origin") != "*":
            return fail("api OPTIONS should allow browser origin")
        if "POST" not in options.get("access-control-allow-methods", ""):
            return fail("api OPTIONS should allow POST")
        confirmation_id = confirmations["confirmations"][0]["confirmation_id"]
        decision = post_json(
            f"{base_url}/runs/{run_id}/confirmations/{confirmation_id}/decision",
            {"decision": "edit", "decided_by": "merchant_demo", "note": "api regression test"},
        )
        if decision.get("execution_status") != "held_for_execution_service":
            return fail("api decision should be held for execution service")
        approval_id = confirmations["confirmations"][1]["confirmation_id"]
        approval = post_json(
            f"{base_url}/runs/{run_id}/confirmations/{approval_id}/decision",
            {"decision": "approve", "decided_by": "merchant_demo", "note": "api approval before execution"},
        )
        if approval.get("execution_status") != "held_for_execution_service":
            return fail("api approved decision should initially be held for execution service")
        execution = post_json(
            f"{base_url}/runs/{run_id}/confirmations/{approval_id}/execute",
            {"requested_by": "merchant_demo", "demo_mode": True},
        )
        if execution.get("execution_result", {}).get("status") != "simulated_no_platform_write":
            return fail("api execution service should record demo no-platform-write result")
        execution_results = fetch_json(f"{base_url}/runs/{run_id}/execution-results")
        if not execution_results.get("execution_results"):
            return fail("api should return execution service results")
        decisions = fetch_json(f"{base_url}/runs/{run_id}/confirmation-decisions")
        if not decisions.get("decisions"):
            return fail("api should return confirmation decisions")
        tools = fetch_json(f"{base_url}/tools")
        if len(tools.get("tools", [])) < 5:
            return fail("api tools should return registry tools")
        created = post_json(
            f"{base_url}/runs",
            {
                "tasks_dir": str(TASKS_DIR),
                "output_dir": str(SAMPLE_DIR / "runtime-api-created-run"),
                "adapter": "jiejing-local",
                "run_id": "runtime-api-created-run",
            },
        )
        if created.get("run", {}).get("run_status") != "completed_with_blocks":
            return fail("api POST /runs should create completed_with_blocks run")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def options_headers(url: str) -> dict:
    request = urllib.request.Request(
        url,
        method="OPTIONS",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        headers["status"] = response.status
        return headers


def validate_run(run_dir: Path, expected_adapter: str) -> int:
    run_json_path = run_dir / "run.json"
    audit_path = run_dir / "audit-log.jsonl"
    results_dir = run_dir / "results"
    if not run_json_path.exists():
        return fail("missing run.json")
    if not audit_path.exists():
        return fail("missing audit-log.jsonl")
    if not results_dir.exists():
        return fail("missing results directory")

    run_json = load_json(run_json_path)
    if run_json.get("adapter") != expected_adapter:
        return fail(f"adapter should be {expected_adapter}")
    if run_json.get("task_count") != 11:
        return fail("task_count should be 11")
    if run_json.get("run_status") != "completed_with_blocks":
        return fail("run_status should be completed_with_blocks")
    if run_json.get("confirmation_item_count", 0) < 5:
        return fail("confirmation_item_count should prove confirmation center is active")
    if len(run_json.get("queue", [])) != 11:
        return fail("queue snapshot should contain 11 tasks")

    real_execution = run_json.get("real_execution", {})
    for key in ["published_to_ebay", "procurement_paid", "refund_executed", "ad_budget_changed", "store_policy_changed"]:
        if real_execution.get(key) is not False:
            return fail(f"real_execution flag is not false: {key}")

    result_files = sorted(results_dir.glob("*.json"))
    if len(result_files) != 11:
        return fail("results directory should contain 11 result files")

    audit_lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(audit_lines) < 20:
        return fail("audit log should include run and task events")
    first_event = json.loads(audit_lines[0])
    if not isinstance(first_event.get("created_at"), str):
        return fail("audit created_at must be a string")
    if not isinstance(first_event.get("details"), dict):
        return fail("audit details must be an object")

    return 0


def validate_execution_boundary() -> int:
    service = ExecutionService(demo_mode=True)
    base = {
        "action_type": "publish_listing",
        "task_id": "task_publish_test",
        "user_id": "user_demo",
        "company_id": "company_demo",
        "store_id": "store_demo",
        "platform": "ebay",
        "payload": {"listing_id": "draft_only"},
    }
    blocked = service.execute(ExecutionRequest(**base))
    if blocked.status != "blocked_confirmation_required":
        return fail("publish without confirmation must be blocked")
    confirmed = service.execute(
        ExecutionRequest(
            **base,
            confirmation_id="confirm_demo",
            confirmed_by="user_demo",
            confirmed_at="2026-05-14T00:00:00+08:00",
        )
    )
    if confirmed.status != "simulated_no_platform_write":
        return fail("confirmed publish in demo mode must record a no-platform-write execution")
    if confirmed.audit.get("real_execution", {}).get("published_to_ebay") is not False:
        return fail("execution service must not mark published_to_ebay true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
