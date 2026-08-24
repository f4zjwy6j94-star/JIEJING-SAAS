#!/usr/bin/env python3
"""Regression: dry-run media placeholders can never enter merchant review."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-media-placeholder-review-gate" / "test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8796
    env = os.environ.copy()
    env.update(
        {
            "JIEJING_SAAS_ENV": "test",
            "JIEJING_MEDIA_LIVE_PROVIDER_ENABLED": "false",
            "JIEJING_MEDIA_LIVE_VIDEO_ENABLED": "false",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "false",
        }
    )
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
        env=env,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_health(base_url)
        registered = _post(
            f"{base_url}/auth/register",
            {
                "email": "media-placeholder-gate@example.com",
                "password": "local-test-password",
                "company_name": "Media Placeholder Gate",
            },
        )
        token = str(registered.get("token") or "")
        store = _post(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "placeholdergate", "marketplace": "EBAY_US"},
            token,
        ).get("store", {})
        queued = _post(
            f"{base_url}/stores/{store.get('store_id')}/provider-jobs/queue",
            {
                "provider_job_key": "media.asset_generation",
                "title": "Dry-run placeholder must fail closed",
                "idempotency_key": "media-placeholder-review-gate-001",
                "inputs": {
                    "media_provider": "provider_neutral",
                    "creative_job_spec": {
                        "job_type": "eBay_listing_asset_package",
                        "output_safety_mode": "reference_grounded_listing_draft",
                        "blocked_claims": ["unverified_certification"],
                    },
                    "product_facts": {
                        "product": "silicone cable organizer",
                        "listing_project_key": "listing-placeholder-gate-001",
                        "supplier_facts": {
                            "material": "silicone",
                            "package_dimensions_cm": {"length": 10, "width": 6, "height": 2},
                        },
                        "allowed_claims": ["organizes loose cables"],
                        "forbidden_claims": ["medical"],
                        "reference_images": ["https://cdn.example.test/source.jpg"],
                        "target_marketplace_rules": {"platform": "ebay"},
                    },
                    "image_count": 1,
                    "image_sizes": ["1:1"],
                    "scene_types": ["white_background"],
                    "live_provider_requested": False,
                    "commercial_rights_confirmed": True,
                },
                "run_mode": "local_worker_now",
            },
            token,
        )
        media_job = queued.get("media_asset_job") if isinstance(queued.get("media_asset_job"), dict) else {}
        if media_job.get("status") != "needs_rework":
            raise AssertionError(f"dry-run media must fail closed before review: {media_job}")
        if media_job.get("live_provider_called") is not False:
            raise AssertionError("dry-run media must keep live_provider_called=false")
        status, rejected = _post_status(
            f"{base_url}/media-asset-jobs/{media_job.get('media_job_id')}/review",
            {
                "decision": "approve_for_listing_draft",
                "fact_consistency_confirmed": True,
                "commercial_rights_confirmed": True,
                "platform_rules_checked": True,
                "motion_and_usage_consistency_confirmed": True,
            },
            token,
        )
        if status != 422 or "不能审核" not in str(rejected.get("error") or ""):
            raise AssertionError(f"placeholder approval must be rejected with a merchant-readable reason: {status}, {rejected}")
        print("PASS jiejing_media_placeholder_review_gate")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_for_health(base_url: str) -> None:
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if json.loads(response.read().decode("utf-8")).get("status") == "ok":
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError("backend did not become healthy")


def _post(url: str, payload: dict, token: str = "") -> dict:
    status, body = _post_status(url, payload, token)
    if status >= 400:
        raise AssertionError(f"unexpected HTTP {status}: {body}")
    return body


def _post_status(url: str, payload: dict, token: str = "") -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


if __name__ == "__main__":
    raise SystemExit(main())
