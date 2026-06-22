#!/usr/bin/env python3
"""Regression for Provider job contracts used by Jiejing-owned Runtime."""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog  # noqa: E402


TEST_DB = ROOT / "output" / "jiejing-agent-runtime-samples" / "provider-job-contracts" / "runtime-provider-jobs.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    catalog = build_provider_job_contract_catalog()
    required = {
        "public_search.market_research",
        "ebay.read_only_snapshot",
        "sourcing.1688_availability",
        "logistics.orange_connex_quote",
        "media.fal_asset_generation",
        "model.role_report_assist",
    }
    keys = {item.get("key") for item in catalog.get("contracts", [])}
    if not required.issubset(keys):
        return fail("provider job catalog missing required jobs")
    if catalog.get("secret_exposed") is not False or catalog.get("real_execution_allowed") is not False:
        return fail("provider job catalog must be front-end safe")
    if catalog.get("secret_boundary", {}).get("frontend_gets_raw_secret") is not False:
        return fail("provider job catalog must not expose raw secrets to frontend")
    for item in catalog.get("contracts", []):
        if item.get("raw_secret_exposed") is not False:
            return fail(f"contract exposes raw secret: {item.get('key')}")
        if item.get("real_execution_allowed") is not False:
            return fail(f"contract allows real execution: {item.get('key')}")
        if not item.get("output_packet") or not item.get("source_record_type"):
            return fail(f"contract lacks output/source shape: {item.get('key')}")
        if int(item.get("timeout_seconds") or 0) <= 0 or int(item.get("max_attempts") or 0) <= 0:
            return fail(f"contract lacks timeout/retry: {item.get('key')}")

    api_result = validate_runtime_api()
    if api_result:
        return api_result

    print("PASS provider_job_contracts_regression")
    return 0


def validate_runtime_api() -> int:
    port = 8768
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
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
            return fail("runtime api did not become healthy")
        payload = fetch_json(f"{base_url}/provider-job-contracts")
        catalog = payload.get("provider_job_contracts", {})
        if catalog.get("contract_count", 0) < 6:
            return fail("runtime api should expose provider job contracts")
        serialized = json.dumps(catalog, ensure_ascii=False).lower()
        if "unit-secret" in serialized or "bearer " in serialized or "[secret]" in serialized:
            return fail("provider job API payload exposed secret-like values")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
