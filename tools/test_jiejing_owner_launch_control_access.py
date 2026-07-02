#!/usr/bin/env python3
"""Functional access guard for platform-internal launch control."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-owner-launch-control-access-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    merchant = _run_case(
        port=8831,
        db_name="merchant.sqlite",
        email="merchant-owner@example.test",
        allowlist="platform-admin@example.test",
    )
    if merchant["owner_status"] != 403 or merchant["production_status"] != 403 or merchant["ledger_status"] != 403:
        return fail(f"ordinary merchant owner should receive 403: {merchant}")
    if any(status != 403 for status in merchant["protected_launch_statuses"].values()):
        return fail(f"ordinary merchant protected launch evidence should receive 403: {merchant['protected_launch_statuses']}")

    platform_admin = _run_case(
        port=8832,
        db_name="platform-admin.sqlite",
        email="platform-admin@example.test",
        allowlist="platform-admin@example.test",
    )
    if platform_admin["owner_status"] != 200 or platform_admin["production_status"] != 200 or platform_admin["ledger_status"] != 200:
        return fail(f"platform allowlisted admin should receive 200: {platform_admin}")
    if any(status != 200 for status in platform_admin["protected_launch_statuses"].values()):
        return fail(f"platform allowlisted admin should receive protected launch evidence: {platform_admin['protected_launch_statuses']}")
    packet = platform_admin["owner_body"].get("owner_launch_control") or {}
    if packet.get("audience") != "platform_internal_admin" or packet.get("customer_visible") is not False:
        return fail(f"platform admin packet should stay internal: {packet}")
    if "platform-admin@example.test" in json.dumps(packet, ensure_ascii=False).lower():
        return fail("owner launch-control packet must not echo internal admin emails")
    release_gate = platform_admin["production_body"].get("production_release_gate") or {}
    if release_gate.get("contract_version") != "2026-07-02-production-release-gate-v1":
        return fail(f"platform admin production release gate missing: {release_gate}")
    if release_gate.get("audience") != "platform_internal_admin":
        return fail(f"production release gate should stay internal: {release_gate}")
    if "platform-admin@example.test" in json.dumps(release_gate, ensure_ascii=False).lower():
        return fail("production release gate must not echo internal admin emails")
    ledger = platform_admin["ledger_body"].get("production_evidence_ledger") or {}
    if ledger.get("contract_version") != "2026-07-02-production-evidence-ledger-v1":
        return fail(f"platform admin production evidence ledger missing: {ledger}")
    if ledger.get("audience") != "platform_internal_admin" or ledger.get("customer_visible") is not False:
        return fail(f"production evidence ledger should stay internal: {ledger}")
    if "platform-admin@example.test" in json.dumps(ledger, ensure_ascii=False).lower():
        return fail("production evidence ledger must not echo internal admin emails")
    protected_bodies = platform_admin["protected_launch_bodies"]
    if (protected_bodies.get("owner_billing_domain") or {}).get("billing_domain_cutover_rehearsal", {}).get("contract_version") != "2026-06-18-stripe-domain-cutover-rehearsal":
        return fail("owner billing domain cutover rehearsal contract missing")
    if (protected_bodies.get("owner_billing_provider") or {}).get("billing_provider_evidence_register", {}).get("contract_version") != "2026-07-02-live-billing-provider-evidence-register":
        return fail("owner billing provider evidence register contract missing")
    if (protected_bodies.get("owner_edge_cutover") or {}).get("edge_cutover_preflight", {}).get("contract_version") != "2026-06-18-edge-waf-origin-callback-preflight":
        return fail("owner edge cutover preflight contract missing")
    if (protected_bodies.get("owner_paid_launch") or {}).get("paid_launch_approval_packet", {}).get("contract_version") != "2026-06-18-paid-launch-approval-packet":
        return fail("owner paid launch approval packet contract missing")
    if (protected_bodies.get("billing_payment_options") or {}).get("payment_options", {}).get("contract_version") != "2026-06-29-mainland-payment-strategy":
        return fail("owner billing payment options contract missing")

    print("PASS jiejing_owner_launch_control_access")
    return 0


def _run_case(*, port: int, db_name: str, email: str, allowlist: str) -> dict[str, Any]:
    db = OUT / db_name
    runtime_db = OUT / f"runtime-{db_name}"
    for path in (db, runtime_db):
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env["JIEJING_INTERNAL_ADMIN_EMAILS"] = allowlist
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
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_for_health(base)
        registered = _post_json(
            f"{base}/auth/register",
            {"email": email, "password": "local-test-password", "company_name": "Access Guard"},
        )
        token = str(registered.get("token") or "")
        if not token:
            raise RuntimeError(f"registration did not return token: {registered}")
        owner = _fetch_json_or_error(f"{base}/owner/launch-control", token=token)
        production = _fetch_json_or_error(f"{base}/owner/production-release-gate", token=token)
        ledger = _fetch_json_or_error(f"{base}/owner/production-evidence-ledger", token=token)
        protected_routes = {
            "owner_billing_domain": "/owner/billing-domain-cutover-rehearsal",
            "owner_billing_provider": "/owner/billing-provider-evidence-register",
            "owner_edge_cutover": "/owner/edge-cutover-preflight",
            "owner_paid_launch": "/owner/paid-launch-approval-packet",
            "legacy_commercial_billing_domain": "/commercial/billing-domain-cutover-rehearsal",
            "legacy_commercial_billing_provider": "/commercial/billing-provider-evidence-register",
            "legacy_domain_edge_cutover": "/domain/edge-cutover-preflight",
            "legacy_commercial_paid_launch": "/commercial/paid-launch-approval-packet",
            "billing_payment_options": "/billing/payment-options",
        }
        protected = {key: _fetch_json_or_error(f"{base}{route}", token=token) for key, route in protected_routes.items()}
        return {
            "owner_status": owner["status"],
            "owner_body": owner["body"],
            "production_status": production["status"],
            "production_body": production["body"],
            "ledger_status": ledger["status"],
            "ledger_body": ledger["body"],
            "protected_launch_statuses": {key: value["status"] for key, value in protected.items()},
            "protected_launch_bodies": {key: value["body"] for key, value in protected.items()},
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_for_health(base: str) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            body = _fetch_json_or_error(f"{base}/health")
            if body["status"] == 200:
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("backend did not become healthy")


def _post_json(url: str, body: dict[str, Any], *, token: str = "") -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json_or_error(url: str, *, token: str = "") -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:200]}
        return {"status": exc.code, "body": body}


if __name__ == "__main__":
    raise SystemExit(main())
