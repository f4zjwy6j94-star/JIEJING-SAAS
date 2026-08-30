#!/usr/bin/env python3
"""Merchant reports exclude internal review artifacts and other tenants."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-merchant-report-projection-test"
PORT = 8856
BASE = f"http://127.0.0.1:{PORT}"


def request(path: str, *, method: str = "GET", token: str = "", body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=payload, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            request("/health")
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.2)
    raise RuntimeError("local SaaS server did not become healthy")


def create_account(label: str) -> tuple[str, dict[str, Any]]:
    registered = request(
        "/auth/register",
        method="POST",
        body={
            "email": f"merchant-report-{label}@local.invalid",
            "password": f"Merchant-report-{label}-password",
            "company_name": f"Merchant Report {label}",
        },
    )
    token = str(registered.get("token") or "")
    store = request(
        "/stores",
        method="POST",
        token=token,
        body={
            "platform": "ebay",
            "store_name": f"Report Store {label}",
            "marketplace": "EBAY_US",
            "stage": "store_opened",
        },
    )["store"]
    return token, store


def save_product_facts(token: str, store_id: str, label: str) -> dict[str, Any]:
    return request(
        f"/stores/{store_id}/product-facts",
        method="POST",
        token=token,
        body={
            "listing_project_identity": {"key": f"listing-project-{label}"},
            "merchant_product_fact_packet": {
                "contract_version": "merchant_product_fact_packet_v1",
                "merchant_confirmed_facts": {
                    "product_name": f"Merchant Product {label}",
                    "condition": "NEW",
                },
            },
        },
    )


def insert_internal_owner_review(db: Path, task_id: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            insert into reports (
              report_id, task_id, runtime_run_id, report_type, title, status, created_at, report_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "report_internal_owner_review",
                task_id,
                "owner_acceptance_runtime",
                "owner.review",
                "Internal owner acceptance",
                "saved",
                created_at,
                json.dumps(
                    {
                        "task_type": "owner.review",
                        "customer_visible": False,
                        "internal_prompt": "Never expose this internal prompt to merchants",
                        "secret_exposed": False,
                    },
                    ensure_ascii=False,
                ),
            ),
        )


def insert_internal_audit(db: Path, *, company_id: str, store_id: str, audit_id: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    record = {
        "audit_id": audit_id,
        "company_id": company_id,
        "store_id": store_id,
        "user_id": "user_internal_operator",
        "actor_type": "platform_internal_admin",
        "action_type": "owner.acceptance.step_recorded",
        "target_type": "listing_project",
        "target_id": "listing-project-acceptance",
        "summary": "A delegated acceptance step was recorded.",
        "created_at": created_at,
        "details": {
            "status": "completed",
            "step": "listing_draft_checked",
            "internal_prompt": "do not expose",
            "raw_request": {"authorization": "Bearer hidden-token"},
            "secret": "hidden-secret",
            "token": "hidden-token",
        },
    }
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            insert into audit_logs (
              audit_id, company_id, store_id, user_id, actor_type, action_type,
              target_type, target_id, summary, created_at, audit_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                company_id,
                store_id,
                record["user_id"],
                record["actor_type"],
                record["action_type"],
                record["target_type"],
                record["target_id"],
                record["summary"],
                created_at,
                json.dumps(record, ensure_ascii=False),
            ),
        )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db = OUT / "merchant-report-projection.sqlite"
    runtime_db = OUT / "runtime.sqlite"
    for path in (db, runtime_db):
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env["JIEJING_INTERNAL_ADMIN_EMAILS"] = "merchant-report-tenant-a@local.invalid"
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
        env=env,
    )
    try:
        wait_for_health()
        token_a, store_a = create_account("tenant-a")
        token_b, store_b = create_account("tenant-b")
        saved_a = save_product_facts(token_a, store_a["store_id"], "tenant-a")
        saved_b = save_product_facts(token_b, store_b["store_id"], "tenant-b")
        insert_internal_owner_review(db, saved_a["task"]["task_id"])
        insert_internal_audit(
            db,
            company_id=store_a["company_id"],
            store_id=store_a["store_id"],
            audit_id="audit_internal_admin_a",
        )
        insert_internal_audit(
            db,
            company_id=store_b["company_id"],
            store_id=store_b["store_id"],
            audit_id="audit_internal_admin_b",
        )

        reports_a = request("/reports?limit=100", token=token_a).get("reports") or []
        reports_b = request("/reports?limit=100", token=token_b).get("reports") or []
        types_a = {str(item.get("report_type") or "") for item in reports_a}
        ids_a = {str(item.get("report_id") or "") for item in reports_a}
        if "merchant.product_facts" not in types_a:
            raise AssertionError(f"tenant A merchant report missing: {types_a}")
        if "owner.review" in types_a or "report_internal_owner_review" in ids_a:
            raise AssertionError(f"ordinary merchant received internal owner.review: {types_a}")
        if saved_b["report"]["report_id"] in ids_a:
            raise AssertionError("tenant A received tenant B report")
        if saved_a["report"]["report_id"] in {str(item.get("report_id") or "") for item in reports_b}:
            raise AssertionError("tenant B received tenant A report")
        report_a = next((item for item in reports_a if item.get("report_id") == saved_a["report"]["report_id"]), None)
        report_b = next((item for item in reports_b if item.get("report_id") == saved_b["report"]["report_id"]), None)
        if not report_a or report_a.get("company_id") != store_a["company_id"] or report_a.get("store_id") != store_a["store_id"]:
            raise AssertionError(f"tenant A report missing authoritative scope: {report_a}")
        if not report_b or report_b.get("company_id") != store_b["company_id"] or report_b.get("store_id") != store_b["store_id"]:
            raise AssertionError(f"tenant B report missing authoritative scope: {report_b}")
        serialized = json.dumps(reports_a, ensure_ascii=False).lower()
        if "internal_prompt" in serialized or "never expose this internal prompt" in serialized or "hidden-token" in serialized or "hidden-secret" in serialized:
            raise AssertionError("merchant reports leaked internal review payload")

        admin_audits = request("/audit-logs?limit=100", token=token_a).get("audit_logs") or []
        merchant_audits = request("/audit-logs?limit=100", token=token_b).get("audit_logs") or []
        admin_trace = next((item for item in admin_audits if item.get("audit_id") == "audit_internal_admin_a"), None)
        if not admin_trace or admin_trace.get("internal_actor") is not True:
            raise AssertionError(f"platform admin did not receive sanitized acceptance trace: {admin_trace}")
        if any(key in admin_trace for key in ("company_id", "user_id")):
            raise AssertionError(f"acceptance trace exposed internal identity: {admin_trace}")
        if any(item.get("audit_id") == "audit_internal_admin_b" for item in merchant_audits):
            raise AssertionError("ordinary merchant received an internal acceptance trace")
        allowed_audit_keys = {
            "audit_id",
            "store_id",
            "actor_type",
            "action_type",
            "target_type",
            "target_id",
            "summary",
            "created_at",
            "details",
            "internal_actor",
        }
        for audit in merchant_audits:
            unexpected = set(audit) - allowed_audit_keys
            if unexpected:
                raise AssertionError(f"merchant audit exposed non-public fields: {unexpected}")
        serialized_audits = json.dumps(admin_audits + merchant_audits, ensure_ascii=False).lower()
        for forbidden in ("internal_prompt", "raw_request", "hidden-secret", "hidden-token", "authorization"):
            if forbidden in serialized_audits:
                raise AssertionError(f"merchant audit projection leaked {forbidden}")

        print("PASS jiejing_merchant_report_projection")
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
