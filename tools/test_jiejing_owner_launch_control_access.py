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
REQUEST_TIMEOUT_SECONDS = 30
OPS_HOST = "ops.jiejing.shop"


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
    if merchant["permissions_body"].get("platform_internal_admin") is not False:
        return fail(f"ordinary merchant permissions should not mark platform admin: {merchant['permissions_body']}")
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
    if platform_admin["permissions_body"].get("platform_internal_admin") is not True:
        return fail(f"platform allowlisted admin permissions should mark platform admin: {platform_admin['permissions_body']}")
    if platform_admin["owner_status"] != 200 or platform_admin["production_status"] != 200 or platform_admin["ledger_status"] != 200:
        return fail(f"platform allowlisted admin should receive 200: {platform_admin}")
    if any(status != 403 for status in platform_admin["non_ops_owner_statuses"].values()):
        return fail(
            "platform admin must not access owner routes through app or localhost hosts: "
            f"{platform_admin['non_ops_owner_statuses']}"
        )
    if any(status != 403 for status in platform_admin["lookalike_ops_owner_statuses"].values()):
        return fail(
            "production-like owner routes must reject lookalike ops subdomains: "
            f"{platform_admin['lookalike_ops_owner_statuses']}"
        )
    readiness = platform_admin["admin_app_readiness_body"].get("readiness") or {}
    if platform_admin["admin_app_readiness_status"] != 200:
        return fail(f"platform admin merchant readiness request failed: {platform_admin['admin_app_readiness_status']}")
    if (
        readiness.get("detail_scope") != "public_summary"
        or readiness.get("authenticated_summary") is not True
        or readiness.get("secret_exposed") is not False
    ):
        return fail(f"platform admin must receive merchant-safe readiness on app host: {readiness}")
    legacy_keys = {
        "owner_billing_domain",
        "owner_billing_provider",
        "legacy_commercial_billing_domain",
        "legacy_commercial_billing_provider",
    }
    for key, status in platform_admin["protected_launch_statuses"].items():
        expected = 410 if key in legacy_keys else 200
        if status != expected:
            return fail(f"platform admin protected launch status mismatch: {key}={status}, expected={expected}")
    if any(status != 401 for status in platform_admin["anonymous_legacy_statuses"].values()):
        return fail(f"legacy retirement routes must remain authenticated: {platform_admin['anonymous_legacy_statuses']}")
    packet = platform_admin["owner_body"].get("owner_launch_control") or {}
    if packet.get("audience") != "platform_internal_admin" or packet.get("customer_visible") is not False:
        return fail(f"platform admin packet should stay internal: {packet}")
    if "platform-admin@example.test" in json.dumps(packet, ensure_ascii=False).lower():
        return fail("owner launch-control packet must not echo internal admin emails")
    release_gate = platform_admin["production_body"].get("production_release_gate") or {}
    if release_gate.get("contract_version") != "2026-07-27-production-release-gate-v2":
        return fail(f"platform admin production release gate missing: {release_gate}")
    if release_gate.get("audience") != "platform_internal_admin":
        return fail(f"production release gate should stay internal: {release_gate}")
    if "platform-admin@example.test" in json.dumps(release_gate, ensure_ascii=False).lower():
        return fail("production release gate must not echo internal admin emails")
    ledger = platform_admin["ledger_body"].get("production_evidence_ledger") or {}
    if ledger.get("contract_version") != "2026-07-27-production-evidence-ledger-v2":
        return fail(f"platform admin production evidence ledger missing: {ledger}")
    if ledger.get("audience") != "platform_internal_admin" or ledger.get("customer_visible") is not False:
        return fail(f"production evidence ledger should stay internal: {ledger}")
    if "platform-admin@example.test" in json.dumps(ledger, ensure_ascii=False).lower():
        return fail("production evidence ledger must not echo internal admin emails")
    protected_bodies = platform_admin["protected_launch_bodies"]
    expected_legacy_codes = {
        "owner_billing_domain": "legacy_stripe_billing_cutover_retired",
        "legacy_commercial_billing_domain": "legacy_stripe_billing_cutover_retired",
        "owner_billing_provider": "legacy_stripe_billing_evidence_retired",
        "legacy_commercial_billing_provider": "legacy_stripe_billing_evidence_retired",
    }
    for key, code in expected_legacy_codes.items():
        body = protected_bodies.get(key) or {}
        if body.get("error") != code:
            return fail(f"legacy billing route must return a fixed retirement code: {key} {body}")
        serialized = json.dumps(body, ensure_ascii=False).lower()
        for forbidden in ("stripe", "checkout", "portal", "price_", "sk_live", "whsec_"):
            if forbidden in serialized and forbidden not in code:
                return fail(f"legacy retirement body leaked stale provider detail: {key} {forbidden}")
    if (protected_bodies.get("owner_edge_cutover") or {}).get("edge_cutover_preflight", {}).get("contract_version") != "2026-06-18-edge-waf-origin-callback-preflight":
        return fail("owner edge cutover preflight contract missing")
    if (protected_bodies.get("owner_paid_launch") or {}).get("paid_launch_approval_packet", {}).get("contract_version") != "2026-07-27-paid-launch-approval-packet-v2":
        return fail("owner paid launch approval packet contract missing")
    if (protected_bodies.get("billing_payment_options") or {}).get("payment_options", {}).get("contract_version") != "2026-06-29-mainland-payment-strategy":
        return fail("owner billing payment options contract missing")
    if (protected_bodies.get("vault_status") or {}).get("vault", {}).get("secret_exposed") is not False:
        return fail("owner vault status must stay redacted")
    if (protected_bodies.get("database_plan") or {}).get("database_plan", {}).get("plan_version") != "2026-05-15-db-migration-boundary":
        return fail("owner database plan contract missing")
    if (protected_bodies.get("queue_plan") or {}).get("queue_plan", {}).get("plan_version") != "2026-05-15-queue-worker-boundary":
        return fail("owner queue plan contract missing")
    if (protected_bodies.get("backup_plan") or {}).get("backup_plan", {}).get("contract_version") != "2026-05-18-backup-restore-boundary":
        return fail("owner backup plan contract missing")
    if (protected_bodies.get("monitoring_status") or {}).get("monitoring", {}).get("contract_version") != "2026-05-18-tencent-cls-monitoring-boundary":
        return fail("owner monitoring status contract missing")
    if (protected_bodies.get("infrastructure_drivers") or {}).get("infrastructure_drivers", {}).get("contract_version") != "2026-05-17-infrastructure-drivers":
        return fail("owner infrastructure drivers contract missing")
    if (protected_bodies.get("controlled_bridges") or {}).get("controlled_bridges", {}).get("contract_version") != "2026-07-14-controlled-bridges-v2":
        return fail("owner controlled bridges contract missing")

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
        # The functional probe issues dozens of authenticated requests.  Do not
        # attach unread PIPEs here: on Windows the access log can fill the pipe
        # and block the child server before it sends the HTTP response.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
        permissions = _fetch_json_or_error(f"{base}/permissions/me", token=token)
        owner = _fetch_json_or_error(f"{base}/owner/launch-control", token=token, host=OPS_HOST)
        production = _fetch_json_or_error(f"{base}/owner/production-release-gate", token=token, host=OPS_HOST)
        ledger = _fetch_json_or_error(f"{base}/owner/production-evidence-ledger", token=token, host=OPS_HOST)
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
            "vault_status": "/vault/status",
            "vault_adapters": "/vault/adapters",
            "vault_client_contract": "/vault/client-contract",
            "vault_targets": "/vault/targets",
            "vault_secret_resolver": "/vault/secret-resolver/status",
            "database_plan": "/database/plan",
            "database_adapters": "/database/adapters",
            "database_inventory": "/database/inventory",
            "queue_plan": "/queue/plan",
            "queue_adapters": "/queue/adapters",
            "controlled_bridges": "/controlled-bridges",
            "monitoring_status": "/monitoring/status",
            "infrastructure_drivers": "/infrastructure/drivers",
            "backup_plan": "/backup/plan",
            "provider_job_contracts": "/provider-job-contracts",
        }
        anonymous_legacy = {
            key: _fetch_json_or_error(f"{base}{protected_routes[key]}", host=OPS_HOST)["status"]
            for key in (
                "owner_billing_domain",
                "owner_billing_provider",
                "legacy_commercial_billing_domain",
                "legacy_commercial_billing_provider",
            )
        }
        protected = {
            key: _fetch_json_or_error(f"{base}{route}", token=token, host=OPS_HOST)
            for key, route in protected_routes.items()
        }
        owner_routes = {
            "launch_control": "/owner/launch-control",
            "production_release_gate": "/owner/production-release-gate",
            "production_evidence_ledger": "/owner/production-evidence-ledger",
            **{key: route for key, route in protected_routes.items() if route.startswith("/owner/")},
        }
        non_ops_owner_statuses = {
            f"{host_label}:{key}": _fetch_json_or_error(f"{base}{route}", token=token, host=host)["status"]
            for host_label, host in (("app", "app.jiejing.shop"), ("localhost", ""))
            for key, route in owner_routes.items()
        }
        lookalike_ops_owner_statuses = {
            f"{host}:{key}": _fetch_json_or_error(f"{base}{route}", token=token, host=host)["status"]
            for host in ("ops.preview.jiejing.shop", "ops.evil.jiejing.shop")
            for key, route in owner_routes.items()
        }
        admin_app_readiness = _fetch_json_or_error(
            f"{base}/readiness/product-saas",
            token=token,
            host="app.jiejing.shop",
        )
        return {
            "owner_status": owner["status"],
            "owner_body": owner["body"],
            "permissions_status": permissions["status"],
            "permissions_body": permissions["body"],
            "production_status": production["status"],
            "production_body": production["body"],
            "ledger_status": ledger["status"],
            "ledger_body": ledger["body"],
            "protected_launch_statuses": {key: value["status"] for key, value in protected.items()},
            "protected_launch_bodies": {key: value["body"] for key, value in protected.items()},
            "anonymous_legacy_statuses": anonymous_legacy,
            "non_ops_owner_statuses": non_ops_owner_statuses,
            "lookalike_ops_owner_statuses": lookalike_ops_owner_statuses,
            "admin_app_readiness_status": admin_app_readiness["status"],
            "admin_app_readiness_body": admin_app_readiness["body"],
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
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json_or_error(url: str, *, token: str = "", host: str = "") -> dict[str, Any]:
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    if host:
        headers["host"] = host
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
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
