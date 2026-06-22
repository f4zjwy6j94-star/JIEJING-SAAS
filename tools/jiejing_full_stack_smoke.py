#!/usr/bin/env python3
"""Run a local SaaS -> Runtime -> Agent smoke test.

This is still a safe demo test: it may use read-only/search providers when
configured, but it does not publish to eBay, pay suppliers, refund buyers,
change ads, or edit policies.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.shadow_compare import RuntimeComparisonScorer  # noqa: E402

OUTPUT_DIR = ROOT / "output" / "jiejing-agent-runtime-samples" / "full-stack-smoke"
PORT = 8777


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = OUTPUT_DIR / f"jiejing-full-stack-smoke-{int(time.time())}.sqlite"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_runtime_cli.py"),
            "serve",
            "--db",
            str(db_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{PORT}"
        wait_for_health(base_url)
        workflow = post_json(
            f"{base_url}/workflows/product-test",
            {
                "run_id": "full-stack-smoke-stainless-tumbler",
                "product": "Stainless Steel Travel Tumbler",
                "merchant_goal": "SaaS smoke test: run market, sourcing, listing, asset, service, finance, and confirmation stages without real execution.",
                "stage": "store_opened",
                "platform": "ebay",
                "marketplace": "eBay US",
                "source_mode": "manual_or_1688",
                "tool_mode": "safe_live_read",
                "media_tool_mode": "manifest_only",
                "media_generation_probe": {
                    "asset_manifest": {
                        "provider": "full-stack-smoke-media",
                        "assets": [
                            {
                                "asset_id": "tumbler_main_01",
                                "asset_type": "main_image",
                                "url": "https://example.test/assets/stainless-tumbler-main.jpg",
                                "dimensions": "1600x1600",
                            },
                            {
                                "asset_id": "tumbler_detail_01",
                                "asset_type": "detail_page",
                                "url": "https://example.test/assets/stainless-tumbler-detail.jpg",
                                "dimensions": "1200x3600",
                            },
                            {
                                "asset_id": "tumbler_video_01",
                                "asset_type": "product_video",
                                "url": "https://example.test/assets/stainless-tumbler-video.mp4",
                                "duration_seconds": 24,
                            },
                        ],
                    }
                },
                "sourcing_availability_probe": {
                    "candidates": [
                        {
                            "source_platform": "1688",
                            "title": "20oz stainless tumbler with lid",
                            "source_url": "https://detail.1688.com/offer/demo-stainless-tumbler",
                            "supplier_name": "Demo Zhejiang Drinkware Factory",
                            "unit_cost": 18.8,
                            "moq": 2,
                            "stock": 5000,
                            "ship_from": "Zhejiang",
                            "package_weight_g": 360,
                            "package_dimensions_cm": "9 x 9 x 22",
                            "material": "Stainless steel, PP lid, silicone ring",
                        }
                    ]
                },
                "logistics_estimate_probe": {
                    "origin": "Zhejiang, China",
                    "destination": "United States",
                    "package_weight_g": 360,
                    "package_dimensions_cm": "9 x 9 x 22",
                    "estimates": [
                        {
                            "carrier": "Orange Connex",
                            "service_name": "SpeedPAK Economy",
                            "shipping_cost": 58.5,
                            "currency": "CNY",
                            "eta_min_days": 12,
                            "eta_max_days": 25,
                            "tracking": True,
                        }
                    ],
                },
            },
        )
        run_id = workflow.get("run", {}).get("run_id") or "full-stack-smoke-stainless-tumbler"
        facts_update = post_json(
            f"{base_url}/runs/{run_id}/listing-facts",
            {
                "updated_by": "full_stack_smoke",
                "facts": {
                    "product": "Stainless Steel Travel Tumbler",
                    "ebay_title": "Stainless Steel Insulated Travel Tumbler Cup with Lid 20oz",
                    "source_link": "https://detail.1688.com/offer/demo-stainless-tumbler",
                    "purchase_price": "CNY 18.80",
                    "quantity": "30",
                    "source_location": "Zhejiang, China",
                    "package_dimensions": "9 x 9 x 22 cm",
                    "package_weight": "360 g",
                    "material": "Stainless steel inner, PP lid, silicone ring",
                    "included": "1 tumbler cup with lid; straw not included",
                    "quality_checks": "Leak check, odor check, inner wall inspection, lid fit, color consistency, and package crush protection remain merchant-confirmed before real publish.",
                    "category_id": "20687",
                    "fulfillment_policy_id": "fulfillmentPolicyId DEMO-FULFILLMENT-001 authorized store default",
                    "payment_policy_id": "paymentPolicyId DEMO-PAYMENT-001 authorized store default",
                    "return_policy_id": "returnPolicyId DEMO-RETURN-001 authorized store default",
                },
            },
        )
        scorecard = fetch_json(f"{base_url}/progress-scorecard")
        replacement_readiness = fetch_json(f"{base_url}/replacement-readiness")
        snapshot = fetch_json(f"{base_url}/runs/{run_id}/saas-snapshot")
        results = fetch_json(f"{base_url}/runs/{run_id}/results")
        confirmations = fetch_json(f"{base_url}/runs/{run_id}/confirmations")
        shadow_compare = build_shadow_compare(results.get("results", []))
        if shadow_compare.get("gate_status") != "pass":
            raise RuntimeError(f"shadow comparison gate failed: {shadow_compare.get('gate_status')}")
        report = {
            "status": "completed",
            "base_url": base_url,
            "db_path": str(db_path),
            "run_id": run_id,
            "workflow_run_status": workflow.get("run", {}).get("run_status"),
            "listing_fact_update_status": facts_update.get("validation", {}).get("status"),
            "scorecard": scorecard.get("progress_scorecard", {}),
            "replacement_readiness": replacement_readiness.get("replacement_readiness", {}),
            "shadow_compare": shadow_compare,
            "saas_snapshot": snapshot.get("saas_snapshot", {}),
            "confirmation_count": len(confirmations.get("confirmations", [])),
            "real_execution": {
                "published_to_ebay": False,
                "procurement_paid": False,
                "refund_executed": False,
                "ad_budget_changed": False,
                "store_policy_changed": False,
            },
        }
        json_path = OUTPUT_DIR / "jiejing_full_stack_smoke_latest.json"
        md_path = OUTPUT_DIR / "jiejing_full_stack_smoke_latest.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(to_markdown(report), encoding="utf-8")
        print(f"FULL_STACK_SMOKE_JSON={json_path}")
        print(f"FULL_STACK_SMOKE_MD={md_path}")
        print(f"RUN_ID={run_id}")
        print(f"WORKFLOW_STATUS={report['workflow_run_status']}")
        print(f"SCORE_AVERAGE={report['scorecard'].get('summary', {}).get('local_demo_average_percent')}")
        print(f"PRODUCTION_READY={report['scorecard'].get('summary', {}).get('can_claim_production_ready')}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_health(base_url: str) -> None:
    for _ in range(60):
        try:
            health = fetch_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Runtime API did not become healthy")


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def build_shadow_compare(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Run a required same-topic comparison gate with a sample Hermes baseline.

    This is not counted as production parity. It only proves that the smoke test
    exercises the comparison scorer and catches forbidden write claims.
    """

    market = next((item for item in results if item.get("task_type") == "market.report"), None)
    if not isinstance(market, dict):
        return {"gate_status": "failed_missing_market_result", "sample_only": True}
    hermes_sample = json.loads(json.dumps(market, ensure_ascii=False))
    hermes_sample["executor"] = "hermes-sample-baseline"
    hermes_sample["executor_version"] = "sample-only"
    hermes_sample["summary"] = "Sample Hermes baseline for same-topic smoke comparison. Not a live Hermes run."
    hermes_sample["source_records"] = (hermes_sample.get("source_records") or [])[:2]
    report = hermes_sample.get("report") if isinstance(hermes_sample.get("report"), dict) else {}
    sections = report.get("sections") if isinstance(report.get("sections"), dict) else {}
    if isinstance(sections, dict) and "source_health" in sections:
        report["sections"] = {"source_health": sections["source_health"], "category_overview": sections.get("category_overview", "")}
    comparison = RuntimeComparisonScorer().compare(market, hermes_sample)
    gate_status = "pass"
    if comparison.get("jiejing", {}).get("forbidden_write_claims") or comparison.get("hermes", {}).get("forbidden_write_claims"):
        gate_status = "failed_forbidden_write_claim"
    elif comparison.get("jiejing", {}).get("section_coverage", 0) < 0.95:
        gate_status = "failed_jiejing_section_coverage"
    return {
        "gate_status": gate_status,
        "sample_only": True,
        "counts_for_production_replacement": False,
        "comparison": comparison,
        "note": "Smoke-test comparison uses a sample Hermes baseline. Real replacement requires repeated live Hermes same-topic runs.",
    }


def to_markdown(report: dict[str, Any]) -> str:
    scorecard = report.get("scorecard", {})
    replacement = report.get("replacement_readiness", {})
    shadow = report.get("shadow_compare", {})
    lines = [
        "# Jiejing Full Stack Smoke Test",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Run ID: `{report.get('run_id')}`",
        f"- Workflow status: `{report.get('workflow_run_status')}`",
        f"- Listing fact validation: `{report.get('listing_fact_update_status')}`",
        f"- Confirmation count: `{report.get('confirmation_count')}`",
        f"- Local demo average: `{scorecard.get('summary', {}).get('local_demo_average_percent')}`",
        f"- Hermes production replacement readiness: `{replacement.get('production_replacement_percent')}`",
        f"- Local low-risk Agent takeover: `{replacement.get('local_low_risk_takeover_percent')}`",
        f"- Shadow compare gate: `{shadow.get('gate_status')}`",
        f"- Production ready: `{scorecard.get('summary', {}).get('can_claim_production_ready')}`",
        "",
        "## Progress Tracks",
        "",
    ]
    for track in scorecard.get("tracks", []):
        suffix = ""
        if track.get("production_equivalent_percent") is not None:
            suffix = f", production equivalent `{track.get('production_equivalent_percent')}%`"
        lines.append(f"- {track.get('label')}: `{track.get('percent')}%` ({track.get('status')}{suffix})")
    if replacement.get("hard_blockers"):
        lines.extend(["", "## Hermes Replacement Blockers", ""])
        for item in replacement.get("hard_blockers", [])[:5]:
            lines.append(f"- {item}")
    if shadow:
        comparison = shadow.get("comparison", {})
        lines.extend(
            [
                "",
                "## Same-Topic Comparison Gate",
                "",
                f"- Gate status: `{shadow.get('gate_status')}`",
                f"- Sample only: `{shadow.get('sample_only')}`",
                f"- Counts for production replacement: `{shadow.get('counts_for_production_replacement')}`",
                f"- Winner: `{comparison.get('winner')}`",
                f"- Jiejing score: `{comparison.get('jiejing', {}).get('score')}`",
                f"- Hermes sample score: `{comparison.get('hermes', {}).get('score')}`",
                f"- Note: {shadow.get('note')}",
            ]
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Real eBay publish: `false`",
            "- Supplier payment: `false`",
            "- Refund/ad/policy changes: `false`",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
