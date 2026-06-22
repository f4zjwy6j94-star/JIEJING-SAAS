#!/usr/bin/env python3
"""Self-check for Jiejing SaaS demo and owned Runtime progress.

This check is intentionally read-only. It does not publish to eBay, does not
pay suppliers, does not refund buyers, and does not print any secret value.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime import (  # noqa: E402
    DeepSeekModelClient,
    JiejingRuntime,
    RuntimeCapabilityProfile,
    RuntimeConfig,
    EbayProviderStatus,
    MediaGenerationAdapter,
    PublicSearchProbeAdapter,
    PublicSearchProbeConfig,
    model_client_status_from_env,
)
from jiejing_runtime.workflow_templates import ProductWorkflowRequest, build_product_workflow  # noqa: E402


OUTPUT_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "self-check"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    json_path = OUTPUT_DIR / "jiejing_runtime_self_check_latest.json"
    md_path = OUTPUT_DIR / "jiejing_runtime_self_check_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    print(f"SELF_CHECK_JSON={json_path}")
    print(f"SELF_CHECK_MD={md_path}")
    print(f"OVERALL_STATUS={report['overall_status']}")
    print(f"DEESEEK_CONFIGURED={report['deepseek_model']['configured']}")
    print(f"TAVILY_CONFIGURED={report['search_provider']['configured']}")
    print(f"FAL_CONFIGURED={report['media_provider']['configured']}")
    print(f"EBAY_CREDENTIAL_PRESENT={report['ebay_provider']['credential_present']}")
    print(f"WORKFLOW_STATUS={report['sample_workflow']['run_status']}")
    return 0 if report["overall_status"] in {"ready_with_blocks", "ready"} else 1


def build_report() -> dict[str, Any]:
    deepseek_client = DeepSeekModelClient()
    deepseek_status = {
        "client": deepseek_client.name,
        "configured": deepseek_client.configured(),
        "model": deepseek_client.model,
        "endpoint_host": _host(deepseek_client.endpoint),
        "credential_present": bool(deepseek_client.api_key),
        "credential_source": deepseek_client.credential_source,
        "secret_exposed": False,
    }
    capability = RuntimeCapabilityProfile().to_dict()
    workflow_summary = run_sample_workflow()
    live_model_smoke = maybe_run_live_model_smoke(deepseek_client)
    search_provider_status = PublicSearchProbeAdapter().provider_status("tavily")
    media_provider_status = MediaGenerationAdapter().provider_status("fal")
    ebay_provider_status = EbayProviderStatus().to_dict()
    live_search_smoke = maybe_run_live_search_smoke()
    blockers = []
    if not deepseek_status["configured"]:
        blockers.append("DeepSeek model credential is not configured or not discoverable.")
    if workflow_summary["run_status"] not in {"completed_with_blocks", "completed_with_warnings", "success"}:
        blockers.append(f"Sample workflow returned {workflow_summary['run_status']}.")
    production_blockers = [
        "Production SaaS still needs real auth, multi-tenant database, queue, vault, cloud deployment, and billing.",
        "Real eBay writes remain intentionally blocked until ExecutionService and confirmation center are production-ready.",
        "Image/video providers are contract-ready but need paid provider keys and live rendering tests.",
    ]
    return {
        "report_version": "2026-05-15.1",
        "overall_status": "ready_with_blocks" if not blockers else "blocked",
        "model_from_env": model_client_status_from_env(),
        "deepseek_model": deepseek_status,
        "runtime_capability_summary": {
            "safe_to_demo": capability.get("safe_to_demo"),
            "safe_to_execute_real_platform_actions": capability.get("safe_to_execute_real_platform_actions"),
            "capability_count": len(capability.get("capabilities", [])),
            "tools": capability.get("tools"),
        },
        "sample_workflow": workflow_summary,
        "live_model_smoke": live_model_smoke,
        "search_provider": search_provider_status,
        "media_provider": media_provider_status,
        "ebay_provider": ebay_provider_status,
        "live_search_smoke": live_search_smoke,
        "blockers": blockers,
        "production_blockers": production_blockers,
        "no_real_execution": {
            "published_to_ebay": False,
            "procurement_paid": False,
            "refund_executed": False,
            "ad_budget_changed": False,
            "store_policy_changed": False,
        },
    }


def run_sample_workflow() -> dict[str, Any]:
    run_dir = OUTPUT_DIR / "sample-runtime-workflow"
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Self-check Jiejing Runtime workflow without real execution.",
            project_id="self-check-runtime-workflow",
            stage="store_opened",
            source_mode="manual_or_1688",
        )
    )
    runtime = JiejingRuntime(RuntimeConfig(adapter_name="jiejing-local", demo_mode=True, stop_on_failure=False, clean_output=True))
    summary = runtime.run_tasks(tasks, run_dir, run_id="self-check-runtime-workflow")
    return {
        "run_dir": str(summary.run_dir),
        "run_json": str(summary.run_json),
        "summary_md": str(summary.summary_md),
        "task_count": summary.task_count,
        "run_status": summary.run_status,
        "issue_count": len(summary.issues),
    }


def maybe_run_live_model_smoke(client: DeepSeekModelClient) -> dict[str, Any]:
    if os.environ.get("JIEJING_SELF_CHECK_LIVE_MODEL", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "skipped",
            "reason": "Set JIEJING_SELF_CHECK_LIVE_MODEL=1 to spend model credits on a live DeepSeek smoke test.",
        }
    if not client.configured():
        return {"status": "skipped", "reason": "DeepSeek client is not configured."}
    run_dir = OUTPUT_DIR / "sample-deepseek-workflow"
    tasks = build_product_workflow(
        ProductWorkflowRequest(
            product="Stainless Steel Travel Tumbler",
            merchant_goal="Run one DeepSeek-backed Jiejing workflow smoke test.",
            project_id="self-check-deepseek-workflow",
        )
    )
    runtime = JiejingRuntime(
        RuntimeConfig(adapter_name="jiejing-deepseek", demo_mode=True, stop_on_failure=False, clean_output=True)
    )
    summary = runtime.run_tasks(tasks[:2], run_dir, run_id="self-check-deepseek-workflow")
    first_result_path = summary.run_dir / "results" / "01_ceo_intake.json"
    first_result = json.loads(first_result_path.read_text(encoding="utf-8")) if first_result_path.exists() else {}
    report = first_result.get("report") if isinstance(first_result.get("report"), dict) else {}
    model_assist = report.get("model_assist") if isinstance(report.get("model_assist"), dict) else {}
    return {
        "status": "ran",
        "run_dir": str(summary.run_dir),
        "task_count": summary.task_count,
        "run_status": summary.run_status,
        "issue_count": len(summary.issues),
        "model_assist_status": model_assist.get("status"),
        "model_mode": model_assist.get("model_mode") or report.get("model_client_boundary"),
        "model_error_present": bool(report.get("model_error")),
    }


def maybe_run_live_search_smoke() -> dict[str, Any]:
    if os.environ.get("JIEJING_SELF_CHECK_LIVE_SEARCH", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "skipped",
            "reason": "Set JIEJING_SELF_CHECK_LIVE_SEARCH=1 to spend one search credit on a Tavily public-search smoke test.",
        }
    adapter = PublicSearchProbeAdapter()
    snapshot = adapter.probe(
        PublicSearchProbeConfig(
            query="eBay stainless steel travel tumbler supplier reviews",
            provider="tavily",
            live_enabled=True,
            max_results=3,
            search_depth="basic",
            timeout_seconds=30,
        )
    )
    return {
        "status": snapshot.get("status"),
        "provider": snapshot.get("provider"),
        "confidence": snapshot.get("confidence"),
        "result_count": snapshot.get("metrics", {}).get("result_count") if isinstance(snapshot.get("metrics"), dict) else 0,
        "secret_exposed": False,
        "error_present": bool(snapshot.get("error")),
        "summary": snapshot.get("summary"),
    }


def _host(endpoint: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    return parsed.netloc


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Jiejing Runtime Self Check",
        "",
        f"- Overall status: `{report['overall_status']}`",
        f"- DeepSeek configured: `{report['deepseek_model']['configured']}`",
        f"- DeepSeek model: `{report['deepseek_model']['model']}`",
        f"- DeepSeek endpoint host: `{report['deepseek_model']['endpoint_host']}`",
        f"- Credential source: `{report['deepseek_model']['credential_source']}`",
        f"- Secret exposed: `{report['deepseek_model']['secret_exposed']}`",
        f"- Tavily search configured: `{report['search_provider']['configured']}`",
        f"- Search credential source: `{report['search_provider']['credential_source']}`",
        f"- FAL media configured: `{report['media_provider']['configured']}`",
        f"- FAL credential source: `{report['media_provider']['credential_source']}`",
        f"- eBay credential present: `{report['ebay_provider']['credential_present']}`",
        f"- eBay credential source: `{report['ebay_provider']['credential_source']}`",
        "",
        "## Sample Workflow",
        "",
        f"- Status: `{report['sample_workflow']['run_status']}`",
        f"- Tasks: `{report['sample_workflow']['task_count']}`",
        f"- Run: `{report['sample_workflow']['run_dir']}`",
        "",
        "## Live Model Smoke",
        "",
        f"- Status: `{report['live_model_smoke']['status']}`",
        f"- Reason: `{report['live_model_smoke'].get('reason', '')}`",
        f"- Model assist: `{report['live_model_smoke'].get('model_assist_status', '')}`",
        f"- Model error present: `{report['live_model_smoke'].get('model_error_present', '')}`",
        "",
        "## Live Search Smoke",
        "",
        f"- Status: `{report['live_search_smoke']['status']}`",
        f"- Reason: `{report['live_search_smoke'].get('reason', '')}`",
        f"- Result count: `{report['live_search_smoke'].get('result_count', '')}`",
        f"- Error present: `{report['live_search_smoke'].get('error_present', '')}`",
        "",
        "## Production Blockers",
        "",
    ]
    lines.extend(f"- {item}" for item in report["production_blockers"])
    lines.extend(["", "## Safety", ""])
    lines.append("No real eBay publish, procurement payment, refund, ad change, or policy edit was executed.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
