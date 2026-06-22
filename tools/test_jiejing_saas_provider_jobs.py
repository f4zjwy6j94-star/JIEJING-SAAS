#!/usr/bin/env python3
"""Regression for SaaS-side provider job queue and local dry-run worker."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-saas-provider-jobs" / "test"
SAAS_DB = OUT / "saas-provider-jobs.sqlite"
RUNTIME_DB = OUT / "runtime-provider-jobs.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8793
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
                "email": "provider-owner@example.com",
                "password": "local-test-password",
                "company_name": "Provider Job Test Company",
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

        catalog = fetch_json(f"{base_url}/provider-job-contracts", token=token).get("provider_job_contracts", {})
        keys = {item.get("key") for item in catalog.get("contracts", [])}
        if "sourcing.1688_availability" not in keys or "media.fal_asset_generation" not in keys:
            return fail("SaaS backend should expose provider job contracts")
        if catalog.get("secret_exposed") is not False:
            return fail("provider catalog must not expose secrets")

        queued = post_json(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            {
                "provider_job_key": "sourcing.1688_availability",
                "title": "Dry-run 1688 sourcing availability",
                "inputs": {
                    "product_keyword_or_url": "stainless steel tumbler",
                    "merchant_source_mode": "1688_search",
                    "risk_filters": {"lightweight": True, "non_electric": True, "not_fragile": True},
                    "api_key": "UNIT-API-KEY-MUST-NOT-PERSIST",
                },
            },
            token=token,
        )
        job_id = queued.get("queue_job", {}).get("job_id")
        task_id = queued.get("task", {}).get("task_id")
        if queued.get("queue_job", {}).get("status") != "queued" or not job_id or not task_id:
            return fail("provider job should be queued before worker execution")
        if "UNIT-API-KEY-MUST-NOT-PERSIST" in json.dumps(queued, ensure_ascii=False):
            return fail("provider queue response leaked raw API key")

        worker = post_json(f"{base_url}/workers/run-next", {"job_id": job_id}, token=token)
        provider_job = worker.get("provider_job", {})
        if worker.get("status") != "completed" or provider_job.get("status") != "completed_dry_run":
            return fail("provider dry-run should complete through local worker")
        safety = provider_job.get("safety", {})
        if safety.get("live_provider_called") is not False or safety.get("raw_secret_read") is not False:
            return fail("provider dry-run must not call providers or read raw secrets")
        if provider_job.get("real_platform_writes_enabled") is not False or provider_job.get("secret_exposed") is not False:
            return fail("provider dry-run must keep writes and secrets blocked")
        packet = provider_job.get("output_packet", {})
        if packet.get("packet_type") != "sourcing_candidate_packet":
            return fail("provider dry-run should return the normalized sourcing packet shape")
        task = fetch_json(f"{base_url}/tasks/{task_id}", token=token).get("task", {})
        if task.get("output", {}).get("provider_job_key") != "sourcing.1688_availability":
            return fail("provider output should be saved on the SaaS task")
        audit = fetch_json(f"{base_url}/audit-logs?limit=80", token=token).get("audit_logs", [])
        if not any(item.get("action_type") == "provider_job.dry_run.completed" for item in audit):
            return fail("provider dry-run should write an audit record")

        blocked = post_json(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            {
                "provider_job_key": "logistics.orange_connex_quote",
                "inputs": {"origin": "CN", "destination": "US"},
                "run_mode": "local_worker_now",
            },
            token=token,
        )
        blocked_provider = blocked.get("provider_job", {})
        if blocked_provider.get("status") != "blocked_missing_input":
            return fail("provider job should surface missing inputs instead of pretending success")
        if "package_weight_g" not in blocked_provider.get("missing_inputs", []):
            return fail("missing package weight should be visible to merchant/work record")

        status, _ = post_json_expect_error(
            f"{base_url}/stores/{store_id}/provider-jobs/queue",
            {"provider_job_key": "unknown.provider", "inputs": {}},
            token=token,
        )
        if status != 404:
            return fail("unknown provider job should be rejected")

        print("PASS jiejing_saas_provider_jobs")
        print(f"saas_db={SAAS_DB}")
        print(f"provider_task_id={task_id}")
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
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_expect_error(url: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, post_json(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
