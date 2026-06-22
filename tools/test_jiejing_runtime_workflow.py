#!/usr/bin/env python3
"""Regression for dynamic Jiejing product workflow creation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow
from jiejing_runtime.market_data_packet import MarketDataPacketBuilder
from jiejing_runtime.models import JiejingTask
from jiejing_runtime.merchant_profile import merchant_profile_defaults

SAMPLE_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "runtime-generated-workflows"
WORKFLOW_RUN_DIR = SAMPLE_DIR / "stainless-cup-generated-workflow"
SHADOW_RUN_DIR = SAMPLE_DIR / "stainless-cup-hermes-shadow"
LLM_RUN_DIR = SAMPLE_DIR / "stainless-cup-llm-fallback"
FILE_HANDOFF_RUN_DIR = SAMPLE_DIR / "stainless-cup-hermes-file-handoff"
TEST_DB = SAMPLE_DIR / "workflow-test.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Screen and prepare one eBay product workflow with 1688/manual sourcing fallback.",
            project_id="workflow-regression-stainless-cup",
            merchant_profile={
                "merchantStage": "multi_store",
                "sourceApiMode": "api_1688_order_confirm",
                "permissionLevel": "service_auto",
                "riskLevel": "conservative",
                "profitFloor": 25,
            },
        )
    )
    if len(tasks) != 11:
        return fail("workflow must create 11 productized tasks")
    if tasks[0]["task_type"] != "ceo.intake" or tasks[-1]["task_type"] != "owner.review":
        return fail("workflow task order is incorrect")
    if tasks[4]["output_contract"]["required_sections"][0] != "sku":
        return fail("listing package should preserve eBay field contract")
    if tasks[8]["task_type"] != "confirmation.package":
        return fail("workflow must include independent confirmation package")
    profile = tasks[0]["context"].get("merchant_operating_profile", {})
    if profile.get("merchant_stage") != "multi_store":
        return fail("workflow should carry merchant operating profile")
    if "1688_purchase_after_confirmation" not in tasks[3]["input"].get("allowed_source_routes", []):
        return fail("source.match should inherit merchant source route preferences")
    if tasks[8]["input"].get("profit_floor") is not None:
        return fail("confirmation package should not duplicate finance-only profit floor")
    if "procurement_payment" not in tasks[8]["input"].get("confirm_actions", []):
        return fail("merchant profile must keep procurement payment confirmation-gated")
    if "unverified_battery" not in profile.get("blocked_actions", []):
        return fail("conservative profile should block unverified high-risk product attributes")
    defaults = merchant_profile_defaults()
    if set(defaults.get("stages", {})) != {"newbie", "store_opened", "has_orders", "multi_store"}:
        return fail("merchant profile defaults should expose four SaaS starting points")
    result = validate_market_probe_inputs()
    if result:
        return result

    result = run_cli("jiejing-local", WORKFLOW_RUN_DIR, "workflow-regression-stainless-cup")
    if result:
        return result
    run = json.loads((WORKFLOW_RUN_DIR / "run.json").read_text(encoding="utf-8"))
    if run.get("task_count") != 11 or run.get("run_status") != "completed_with_blocks":
        return fail("dynamic workflow should complete with blocks")
    data_packet_result = json.loads((WORKFLOW_RUN_DIR / "results" / "02_market_data_packet.json").read_text(encoding="utf-8"))
    if data_packet_result.get("report", {}).get("mode") != "market_data_packet":
        return fail("market.data_packet should use the Runtime data packet builder")
    probes = data_packet_result.get("report", {}).get("probes", [])
    probe_keys = {probe.get("key") for probe in probes}
    required_probe_keys = {
        "ebay_read_only",
        "public_search",
        "cross_platform_reference",
        "sourcing_availability",
        "logistics_estimate",
    }
    if not required_probe_keys.issubset(probe_keys):
        return fail("market.data_packet should expose all required probe slots")
    if not any(item.get("input_id") == "live_market_data" for item in data_packet_result.get("missing_inputs", [])):
        return fail("market.data_packet should block until live eBay market data exists")
    market_result = json.loads((WORKFLOW_RUN_DIR / "results" / "03_market_report.json").read_text(encoding="utf-8"))
    if not market_result.get("report", {}).get("runtime_knowledge"):
        return fail("dynamic workflow should use Runtime knowledge")

    result = run_cli("hermes-shadow", SHADOW_RUN_DIR, "workflow-regression-hermes-shadow")
    if result:
        return result
    shadow_result = json.loads((SHADOW_RUN_DIR / "results" / "03_market_report.json").read_text(encoding="utf-8"))
    if shadow_result.get("executor") != "hermes-shadow-adapter":
        return fail("hermes shadow adapter did not run")
    if "dispatch_prompt" not in shadow_result.get("report", {}):
        return fail("hermes shadow adapter should return dispatch prompt")
    if shadow_result.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("hermes shadow adapter must not allow real execution")

    result = run_cli("jiejing-llm", LLM_RUN_DIR, "workflow-regression-llm-fallback")
    if result:
        return result
    llm_result = json.loads((LLM_RUN_DIR / "results" / "03_market_report.json").read_text(encoding="utf-8"))
    if llm_result.get("executor") != "jiejing-agent":
        return fail("jiejing-llm should still use the jiejing-agent adapter boundary")
    if llm_result.get("report", {}).get("model_client") not in {
        "openai-responses-model",
        "openai-compatible-http-model",
        "deepseek-openai-compatible-model",
    }:
        return fail("jiejing-llm should use the live-model client boundary")
    if llm_result.get("report", {}).get("owned_agent_execution", {}).get("uses_live_model") is True:
        return fail("workflow regression must not make a live model call")
    if llm_result.get("report", {}).get("model_assist", {}).get("status") not in {"not_configured", None}:
        return fail("disabled live model should fall back without blocking the regression")

    result = run_cli("hermes-file", FILE_HANDOFF_RUN_DIR, "workflow-regression-hermes-file")
    if result:
        return result
    file_result = json.loads((FILE_HANDOFF_RUN_DIR / "results" / "03_market_report.json").read_text(encoding="utf-8"))
    artifacts = file_result.get("artifacts", [])
    if not artifacts or not all(Path(item["path"]).exists() for item in artifacts if item.get("path")):
        return fail("hermes-file adapter should write handoff artifacts")
    if file_result.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("hermes-file adapter must not allow real execution")
    result = validate_handoff_import(file_result)
    if result:
        return result

    result = validate_api_workflow()
    if result:
        return result

    print("PASS runtime_workflow_regression")
    print(f"workflow_run_dir={WORKFLOW_RUN_DIR}")
    print(f"shadow_run_dir={SHADOW_RUN_DIR}")
    print(f"llm_run_dir={LLM_RUN_DIR}")
    print(f"file_handoff_run_dir={FILE_HANDOFF_RUN_DIR}")
    return 0


def run_cli(adapter: str, output_dir: Path, run_id: str) -> int:
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "run-workflow",
        "--product",
        "Stainless Steel Travel Tumbler",
        "--goal",
        "Screen and prepare one eBay product workflow with 1688/manual sourcing fallback.",
        "--output-dir",
        str(output_dir),
        "--adapter",
        adapter,
        "--run-id",
        run_id,
    ]
    env = os.environ.copy()
    if adapter == "jiejing-llm":
        env["JIEJING_MODEL_DISABLE_LIVE"] = "1"
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False, env=env)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail(f"run-workflow failed for {adapter}")
    return 0


def validate_api_workflow() -> int:
    port = 8767
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
        created = post_json(
            f"{base_url}/workflows/product-test",
            {
                "product": "Stainless Steel Travel Tumbler",
                "merchant_goal": "Run Jiejing product workflow from SaaS.",
                "adapter": "jiejing-local",
                "run_id": "api-generated-workflow-regression",
                "merchant_profile": {
                    "merchantStage": "has_orders",
                    "permissionLevel": "service_auto",
                    "sourceApiMode": "manual_1688",
                    "riskLevel": "balanced",
                },
                "market_probe_inputs": sample_market_probe_inputs(),
            },
        )
        if created.get("run", {}).get("task_count") != 11:
            return fail("api workflow should create 11 tasks")
        results = fetch_json(f"{base_url}/runs/api-generated-workflow-regression/results")
        if len(results.get("results", [])) != 11:
            return fail("api workflow should store 11 results")
        created_snapshot = created.get("saas_snapshot", {})
        if created_snapshot.get("readiness", {}).get("saas_simulation_percent", 0) <= 0:
            return fail("api workflow should return SaaS snapshot readiness")
        snapshot = fetch_json(f"{base_url}/runs/api-generated-workflow-regression/saas-snapshot")
        saas_snapshot = snapshot.get("saas_snapshot", {})
        if saas_snapshot.get("owned_agent", {}).get("role_count", 0) < 7:
            return fail("SaaS snapshot should expose owned Agent role coverage")
        if saas_snapshot.get("safe_for_real_platform_write") is not False:
            return fail("SaaS snapshot must keep real platform writes blocked")
        if "Hermes" in json.dumps(saas_snapshot, ensure_ascii=False):
            return fail("SaaS snapshot should not expose Hermes in public payload")
        data_packet = next((item for item in results.get("results", []) if item.get("task_type") == "market.data_packet"), None)
        if not data_packet or data_packet.get("status") != "success":
            return fail("api workflow should accept supplied market probe inputs")
        profile_defaults = fetch_json(f"{base_url}/merchant-profiles/defaults")
        if "multi_store" not in profile_defaults.get("merchant_profiles", {}).get("stages", {}):
            return fail("api should expose merchant profile defaults")
        first_result = results.get("results", [])[0]
        if first_result.get("report", {}).get("merchant_profile", {}).get("merchant_stage") not in {None, "has_orders"}:
            return fail("api workflow should carry SaaS merchant profile into Runtime")
        capabilities = fetch_json(f"{base_url}/capabilities")
        profile = capabilities.get("capability_profile", {})
        if profile.get("safe_to_execute_real_platform_actions") is not False:
            return fail("capability profile must keep real execution blocked")
        keys = {item.get("key") for item in profile.get("capabilities", [])}
        if "hermes_file_handoff" not in keys or "model_client" not in keys:
            return fail("capability profile should expose model and Hermes handoff readiness")
        if "market_data_packet" not in keys:
            return fail("capability profile should expose market data packet readiness")
        if "ebay_read_only_probe" not in keys:
            return fail("capability profile should expose eBay read-only probe readiness")
        if "public_search_probe" not in keys:
            return fail("capability profile should expose public search probe readiness")
        if "cross_platform_reference_probe" not in keys:
            return fail("capability profile should expose cross-platform reference probe readiness")
        if "sourcing_availability_probe" not in keys:
            return fail("capability profile should expose sourcing availability probe readiness")
        if "logistics_estimate_probe" not in keys:
            return fail("capability profile should expose logistics estimate probe readiness")
        if "provider_job_contracts" not in keys:
            return fail("capability profile should expose provider job contracts")
        if "role_capability_map" not in keys:
            return fail("capability profile should expose Hermes-to-Runtime role capability map")
        provider_jobs = fetch_json(f"{base_url}/provider-job-contracts")
        if provider_jobs.get("provider_job_contracts", {}).get("contract_count", 0) < 6:
            return fail("api should expose provider job contracts")
        if "merchant_operating_profile" not in keys:
            return fail("capability profile should expose merchant operating profile readiness")
        if "role_report_contract" not in keys:
            return fail("capability profile should expose role report contract readiness")
        role_map = capabilities.get("capability_profile", {}).get("role_capability_map", {})
        if role_map.get("summary", {}).get("role_count") != 9:
            return fail("capability profile should include 9 role capabilities")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def validate_handoff_import(file_result: dict) -> int:
    json_artifact = next((item for item in file_result.get("artifacts", []) if item.get("artifact_type") == "hermes_handoff_json"), None)
    if not json_artifact:
        return fail("missing hermes handoff json artifact")
    packet_json = Path(json_artifact["path"])
    role_output = FILE_HANDOFF_RUN_DIR / "fake_hermes_market_output.md"
    role_output.write_text(
        "\n".join(
            [
                "# Market report returned by Hermes",
                "",
                "This is a draft only report. Supplier facts are Pending and need confirmation.",
                "",
                "## Source Health",
                "eBay signal is estimated, not official. 1688 supplier facts pending.",
                "",
                "## Publish Lock",
                "This product cannot be published yet because category and item specifics need check.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output_json = FILE_HANDOFF_RUN_DIR / "imported_handoff_result.json"
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "import-handoff-result",
        "--packet-json",
        str(packet_json),
        "--role-output",
        str(role_output),
        "--output-json",
        str(output_json),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail("import-handoff-result command failed")
    imported = json.loads(output_json.read_text(encoding="utf-8"))
    if imported.get("executor") != "hermes-handoff-importer":
        return fail("handoff importer returned wrong executor")
    if not imported.get("missing_inputs"):
        return fail("handoff importer should detect missing inputs")
    if not imported.get("report", {}).get("section_gaps"):
        return fail("handoff importer should detect missing required report sections")
    if imported.get("audit", {}).get("real_execution_allowed") is not False:
        return fail("handoff importer must keep real execution blocked")

    empty_output = FILE_HANDOFF_RUN_DIR / "empty_hermes_output.md"
    empty_output.write_text("", encoding="utf-8")
    empty_json = FILE_HANDOFF_RUN_DIR / "imported_empty_handoff_result.json"
    command = [
        sys.executable,
        str(ROOT / "tools" / "jiejing_runtime_cli.py"),
        "import-handoff-result",
        "--packet-json",
        str(packet_json),
        "--role-output",
        str(empty_output),
        "--output-json",
        str(empty_json),
    ]
    completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return fail("import-handoff-result command failed for empty output")
    empty_imported = json.loads(empty_json.read_text(encoding="utf-8"))
    if empty_imported.get("status") != "failed_tool":
        return fail("empty Hermes output must become failed_tool")
    if not any(item.get("input_id") == "role_output_empty" for item in empty_imported.get("missing_inputs", [])):
        return fail("empty Hermes output should record role_output_empty")
    return 0


def validate_market_probe_inputs() -> int:
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Validate supplied read-only market probe snapshots.",
            project_id="workflow-regression-probe-ready",
            market_probe_inputs=sample_market_probe_inputs(),
        )
    )
    data_packet = MarketDataPacketBuilder().build(JiejingTask(tasks[1]))
    if data_packet.get("status") != "success":
        return fail("supplied market probe inputs should unblock market.data_packet")
    probes = data_packet.get("report", {}).get("probes", [])
    if not probes or any(probe.get("status") != "ready" for probe in probes):
        return fail("all supplied market probe inputs should become ready probes")
    if data_packet.get("missing_inputs"):
        return fail("ready market probe packet should not report missing inputs")
    return 0


def sample_market_probe_inputs() -> dict:
    return {
        "ebay_read_only": {
            "source_type": "official_api",
            "confidence": "medium",
            "summary": "Read-only sample supplied: target keyword has active listings, visible price bands, and category candidates.",
            "metrics": {"active_listing_sample": 42, "observed_price_band": "US $14.99-$24.99"},
        },
        "public_search": {
            "source_type": "public_page",
            "confidence": "medium",
            "summary": "Public search sample supplied with reusable buyer-language patterns and comparison pages.",
        },
        "cross_platform_reference": {
            "source_type": "public_page",
            "confidence": "medium",
            "summary": "Cross-platform reference sample supplied; used only as directional context, not eBay official data.",
        },
        "sourcing_availability": {
            "source_type": "merchant_provided",
            "confidence": "medium",
            "summary": "Sample sourcing candidate supplied with price, MOQ, material, stock, and origin city placeholders.",
        },
        "logistics_estimate": {
            "source_type": "tool_estimate",
            "confidence": "medium",
            "summary": "Sample logistics estimate supplied with package weight and route placeholder.",
        },
    }


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
