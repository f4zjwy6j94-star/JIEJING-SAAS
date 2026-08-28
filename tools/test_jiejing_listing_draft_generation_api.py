#!/usr/bin/env python3
"""HTTP preflight for the project-scoped Listing AI endpoint."""

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
OUT = ROOT / "output" / "jiejing-listing-draft-generation-api-test"
PORT = 8857
BASE = f"http://127.0.0.1:{PORT}"


def request(path: str, *, method: str = "GET", token: str = "", body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "saas.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    for path in (db, runtime_db):
        if path.exists():
            path.unlink()
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(db),
            "--runtime-db",
            str(runtime_db),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            status, _ = request("/health")
            if status == 200:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("local server did not become healthy")
        _, registered = request(
            "/auth/register",
            method="POST",
            body={
                "email": "listing-generation-api@local.invalid",
                "password": "listing-generation-api-password",
                "company_name": "Listing Generation API",
            },
        )
        token = str(registered.get("token") or "")
        _, store_payload = request(
            "/stores",
            method="POST",
            token=token,
            body={"platform": "ebay", "store_name": "Listing API Store", "marketplace": "EBAY_US"},
        )
        store_id = store_payload["store"]["store_id"]
        status, payload = request(
            f"/stores/{store_id}/listing-drafts/generate",
            method="POST",
            token=token,
            body={
                "listing_project_identity": {"key": "listing-project-http-blocked"},
                "merchant_product_fact_packet": {
                    "contract_version": "merchant_product_fact_packet_v1",
                    "merchant_confirmed_facts": {"product_name": "Unverified HTTP Product"},
                },
                "current_draft_fields": {},
                "api_key": "must-never-be-accepted-by-listing-endpoint",
            },
        )
        if status != 200 or payload.get("status") != "blocked":
            raise AssertionError(f"incomplete Listing HTTP preflight did not block safely: {status} {payload}")
        if payload.get("model_called") is not False or payload.get("usage_consumed") is not False:
            raise AssertionError(f"blocked Listing preflight claimed model usage: {payload}")
        if not {"condition", "material"}.issubset(set(payload.get("missing_fields") or [])):
            raise AssertionError(f"blocked Listing preflight did not name missing facts: {payload}")
        _, reports = request("/reports?limit=100", token=token)
        _, tasks = request("/tasks?limit=100", token=token)
        if reports.get("reports"):
            raise AssertionError("blocked Listing HTTP preflight created a report")
        if tasks.get("tasks"):
            raise AssertionError("blocked Listing HTTP preflight created a task")
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        if "must-never-be-accepted" in serialized:
            raise AssertionError("Listing HTTP response echoed a frontend credential")
        print("PASS jiejing_listing_draft_generation_api")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
