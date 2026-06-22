#!/usr/bin/env python3
"""Regression for public-search handoff into SaaS product workflows."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-public-search-handoff" / "test"
SAAS_DB = OUT / "saas-public-search-handoff.sqlite"
RUNTIME_DB = OUT / "runtime-public-search-handoff.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8798
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if wait_for_health(base_url):
            return fail("saas backend did not become healthy")
        registered = post_json(
            f"{base_url}/auth/register",
            {
                "email": "public-search-owner@example.com",
                "password": "local-test-password",
                "company_name": "Public Search Handoff Test Company",
            },
        )
        token = registered.get("token")
        if not token:
            return fail("registration should return token")
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "northvalesource", "marketplace": "EBAY_US"},
            token=token,
        ).get("store", {})
        store_id = store.get("store_id")
        if not store_id:
            return fail("store should be created")

        workflow = post_json(
            f"{base_url}/tasks/product-workflow",
            {
                "store_id": store_id,
                "product": "Travel Compression Packing Cubes",
                "merchant_goal": "AI CEO should create a source-backed market packet before market report.",
                "adapter": "jiejing-local",
                "run_id": "public-search-handoff-workflow",
                "source_mode": "manual_or_1688",
                "attach_public_search_market_signal": True,
                "attach_latest_platform_data_packet": False,
                "run_mode": "local_worker_now",
            },
            token=token,
        )
        handoff = workflow.get("public_search_market_handoff", {})
        if handoff.get("status") != "ready":
            return fail("product workflow should attach a ready public-search handoff")
        if handoff.get("result_count", 0) < 1:
            return fail("public-search handoff should contain normalized source records")
        if handoff.get("raw_provider_response_stored") is not False or handoff.get("secret_exposed") is not False:
            return fail("public-search handoff must not store raw provider responses or expose secrets")
        workflow_input = workflow.get("task", {}).get("input", {})
        public_probe = workflow_input.get("market_probe_inputs", {}).get("public_search", {})
        if public_probe.get("status") != "ready":
            return fail("Runtime input should include market_probe_inputs.public_search")
        if len(public_probe.get("source_records", [])) < 1:
            return fail("Runtime public_search probe should carry source_records")
        if workflow.get("worker_result", {}).get("status") != "completed":
            return fail("inline local worker should complete the product workflow")
        task_id = workflow.get("task", {}).get("task_id")
        reports = fetch_json(f"{base_url}/reports?task_id={task_id}", token=token).get("reports", [])
        data_packet = next((item for item in reports if item.get("report_type") == "market.data_packet"), {})
        market_report = next((item for item in reports if item.get("report_type") == "market.report"), {})
        if not data_packet or not market_report:
            return fail("workflow should save market.data_packet and market.report reports")
        packet_sources = data_packet.get("report", {}).get("source_records", [])
        if not any("Public search" in str(item.get("title") or "") or item.get("provider_source_type") for item in packet_sources):
            return fail("market.data_packet should include public-search source records")
        report_sources = market_report.get("report", {}).get("source_records", [])
        if not any("market.report" in (item.get("used_for") or []) for item in report_sources if isinstance(item, dict)):
            return fail("market.report should inherit market packet source records")
        search_signal = market_report.get("report", {}).get("report", {}).get("sections", {}).get("search_and_keyword_signal", {})
        if isinstance(search_signal, dict) and not search_signal.get("source_records"):
            return fail("market.report search section should expose source records")
        serialized = json.dumps(workflow, ensure_ascii=False) + json.dumps(reports, ensure_ascii=False)
        for forbidden in ["Authorization", "Bearer ", "PUBLIC-SEARCH-KEY-MUST-NOT-LEAK"]:
            if forbidden in serialized:
                return fail(f"public-search workflow leaked provider secret material: {forbidden}")
        audit = fetch_json(f"{base_url}/audit-logs?limit=120", token=token).get("audit_logs", [])
        if not any(item.get("action_type") == "public_search.market_handoff.attached" for item in audit):
            return fail("public-search handoff should write an audit event")
        print("PASS jiejing_saas_public_search_workflow_handoff")
        print(f"saas_db={SAAS_DB}")
        print(f"workflow_task_id={task_id}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_health(base_url: str) -> int:
    for _ in range(60):
        try:
            health = fetch_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return 0
        except Exception:
            time.sleep(0.1)
    return 1


def fetch_json(url: str, token: str | None = None) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
