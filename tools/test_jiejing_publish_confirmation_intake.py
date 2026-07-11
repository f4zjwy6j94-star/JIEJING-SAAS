#!/usr/bin/env python3
"""Regression for merchant-created publish confirmations."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "output" / "test-jiejing-publish-confirmation-intake"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


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
            {"email": "publish-intake@example.test", "password": "local-test-password", "company_name": "Publish Intake Test"},
        )
        token = registered.get("token")
        user = registered.get("user", {})
        if not token:
            return fail("registration should return token")
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "publish-intake-store", "marketplace": "EBAY_US"},
            token=token,
        ).get("store", {})
        if not store.get("store_id"):
            return fail("store should be created")
        packet_result = post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-read-only/data-packet",
            {
                "resources": ["account_business_policies", "inventory_and_offers"],
                "source_mode": "official_api",
                "sample_payload": {
                    "account_business_policies": {
                        "fulfillment_policy_id": "fulfillment-policy",
                        "payment_policy_id": "payment-policy",
                        "return_policy_id": "return-policy",
                    },
                    "inventory_and_offers": {
                        "merchant_location_key": "default",
                        "item_location": "US",
                    },
                },
            },
            token=token,
        )
        if not packet_result.get("data_packet", {}).get("packet_id"):
            return fail("publish intake setup should create a sanitized data packet")
        result = post_json(
            f"{base_url}/stores/{store['store_id']}/publish-confirmation",
            {
                "product": "Fresh silicone door bumper pads",
                "listing_project_identity": {
                    "key": "listing-project-unit-fresh-bumper",
                    "product": "Fresh silicone door bumper pads",
                    "source_id": "report-unit-fresh-bumper",
                    "candidate_id": "candidate-unit-fresh-bumper",
                },
                "listing": {
                    "sku": "JJ-FRESH-INTAKE-001",
                    "title": "Clear Silicone Cabinet Door Bumper Pads Quiet Stopper Set",
                    "description_html": "<p>Clear silicone bumper pads for cabinet doors.</p>",
                    "category_id": "259153",
                    "category_leaf": "Cabinet Door Dampers & Bumpers",
                    "condition": "NEW",
                    "price": {"value": "9.99", "currency": "USD"},
                    "quantity": 1,
                    "item_specifics": {"Brand": "Unbranded", "Type": "Door Bumper", "Material": "Silicone"},
                },
                "supplier_facts": {
                    "package_weight_g": 80,
                    "package_dimensions_cm": {"length": 12, "width": 8, "height": 2},
                    "material": "Silicone",
                    "item_location": "US",
                },
                "asset_manifest": {"assets": [{"url": "https://example.test/fresh-bumper.jpg"}]},
                "finance_review": {"net_profit_money": {"value": "3.25", "currency": "USD"}},
            },
            token=token,
        )
        confirmation = result.get("confirmation", {})
        if confirmation.get("action_type") != "publish_listing" or confirmation.get("status") != "pending":
            return fail(f"publish intake should create a pending publish confirmation: {result}")
        if result.get("real_platform_writes_enabled") is not False:
            return fail("local publish intake must not enable real writes")
        if confirmation.get("item", {}).get("listing_project_identity", {}).get("key") != "listing-project-unit-fresh-bumper":
            return fail(f"publish confirmation must remain bound to its Listing project: {confirmation}")
        readiness = result.get("publish_readiness", {})
        keys = {item.get("key") for item in readiness.get("checks", [])}
        for required in {"ip_vero_and_claims", "profit_and_fee_sanity", "inventory_api_lifecycle"}:
            if required not in keys:
                return fail(f"publish intake readiness missing {required}: {readiness}")
        traffic = readiness.get("traffic_light_report", {})
        if not traffic or traffic.get("requires_confirmation_center") is not True:
            return fail(f"publish intake should expose the red/yellow/green confirmation gate: {readiness}")
        if traffic.get("real_write_allowed_without_confirmation") is not False:
            return fail(f"publish intake must not allow real writes without confirmation: {traffic}")
        evidence_packet = readiness.get("backend_evidence_packet", {})
        if evidence_packet.get("contract_version") != "2026-06-19-backend-publish-preflight-evidence":
            return fail(f"publish intake should expose backend evidence packet contract: {evidence_packet}")
        for marker in [
            "checks_have_source_records",
            "checks_have_fix_actions",
            "requires_confirmation_center",
        ]:
            if evidence_packet.get(marker) is not True:
                return fail(f"backend evidence packet should mark {marker}=true: {evidence_packet}")
        for marker in [
            "creates_real_write",
            "real_write_allowed_without_confirmation",
            "frontend_gets_token",
            "runtime_gets_token",
            "secret_exposed",
        ]:
            if evidence_packet.get(marker) is not False:
                return fail(f"backend evidence packet should mark {marker}=false: {evidence_packet}")
        for check in readiness.get("checks", []):
            if not check.get("source_records"):
                return fail(f"each readiness check should expose sanitized source_records: {check}")
            fix_action = check.get("fix_action", {})
            if not fix_action or fix_action.get("can_trigger_real_write") is not False:
                return fail(f"each readiness check should expose a safe backend fix_action: {check}")
            if fix_action.get("can_trigger_ebay_oauth") is not False or fix_action.get("can_trigger_payment") is not False:
                return fail(f"readiness fix_action must not trigger OAuth or payment: {check}")
            confirmation_gate = check.get("confirmation_gate", {})
            if confirmation_gate.get("real_write_allowed_without_confirmation") is not False:
                return fail(f"each readiness check should remain confirmation gated: {check}")
        item = confirmation.get("item", {})
        payload = item.get("publish_payload", {})
        if payload.get("business_policies", {}).get("return_policy_id") != "return-policy":
            return fail(f"publish intake should merge business policies from packet: {payload}")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        if "refresh_token" in serialized or "api_key" in serialized or "access_token" in serialized:
            return fail("publish intake response must not expose secrets")
        print("PASS jiejing_publish_confirmation_intake")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_health(base_url: str) -> int:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return 0
        except Exception:
            time.sleep(0.2)
    return 1


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code} for {url}: {detail}") from exc


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


if __name__ == "__main__":
    raise SystemExit(main())
