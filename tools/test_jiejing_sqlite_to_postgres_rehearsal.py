#!/usr/bin/env python3
"""Regression test for the Jiejing SQLite -> Postgres rehearsal exporter."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from jiejing_saas import SaaSRepository  # noqa: E402
from jiejing_sqlite_to_postgres_rehearsal import generate_rehearsal  # noqa: E402


OUT = ROOT / "output" / "jiejing-sqlite-to-postgres-rehearsal-test"
SQLITE_DB = OUT / "fixture.sqlite"
OUT_SQL = OUT / "fixture-import.sql"
SUMMARY_JSON = OUT / "fixture-summary.json"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SQLITE_DB, OUT_SQL, SUMMARY_JSON):
        path.unlink(missing_ok=True)

    repo = SaaSRepository(SQLITE_DB)
    fixture = repo.create_user_with_company(
        email="migration-rehearsal@jiejing.local",
        password="local-test-password",
        company_name="Jiejing Migration Rehearsal",
    )
    user = fixture["user"]
    company = fixture["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "store_name": "northvalesource staging",
            "marketplace": "EBAY_US",
            "stage": "read_only_authorized",
        },
    )
    secret = repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="vault",
        purpose="ebay_oauth_refresh_token",
        status="active",
        metadata={
            "secret_ref_only": True,
            "raw_token_stored_in_database": False,
            "vault_path": "kv/jiejing/staging/ebay/northvalesource",
        },
    )
    repo.create_platform_connection(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"],
            "secret_ref": secret["secret_ref"],
            "metadata": {"marketplace": "EBAY_US", "token_visible_to_frontend": False},
        },
    )
    repo.create_oauth_authorization_request(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        plan={
            "platform": "ebay",
            "status": "consumed",
            "state_nonce": "state-migration-rehearsal",
            "scopes": ["https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"],
            "authorization_url": "https://auth.ebay.com/oauth2/authorize?client_id=masked",
        },
    )
    repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "created",
            "resource_count": 6,
            "sections": [{"resource": "store_profile", "source_type": "official_api"}],
        },
    )
    task = repo.create_task(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        task_type="ai_ceo_product_workflow",
        title="Migration rehearsal AI CEO task",
        input_data={"source": "standard_data_packet", "secret_exposed": False},
    )
    queue_job = repo.create_queue_job(
        company_id=company["company_id"],
        task_id=task["task_id"],
        job_data={"kind": "runtime_workflow", "source": "standard_data_packet"},
    )
    repo.create_media_asset_job(
        company_id=company["company_id"],
        store_id=store["store_id"],
        task_id=task["task_id"],
        queue_job_id=queue_job["job_id"],
        user_id=user["user_id"],
        provider_job_key="media.asset_generation",
        idempotency_key="migration-media-job-001",
        job_spec={
            "provider_job_key": "media.asset_generation",
            "inputs": {"product": "migration rehearsal product"},
            "live_media_provider_call_allowed": False,
            "spend_now_allowed": False,
            "secret_exposed": False,
        },
        status="queued",
    )
    repo.create_task_steps(
        task=task,
        steps=[
            {
                "step_order": 1,
                "task_type": "market_report",
                "role_key": "market_manager",
                "merchant_label": "市场报告",
                "timeout_seconds": 120,
            }
        ],
    )
    repo.complete_task_from_runtime(
        task_id=task["task_id"],
        company_id=company["company_id"],
        runtime_result={"run": {"run_id": "run_migration_rehearsal", "run_status": "completed"}},
    )
    refreshed_task = repo.get_task(company_id=company["company_id"], task_id=task["task_id"]) or task
    repo.save_runtime_outputs(
        task=refreshed_task,
        runtime_result={
            "run": {"run_id": "run_migration_rehearsal", "run_status": "completed"},
            "results": [
                {
                    "task_type": "market_report",
                    "summary": "真实数据包生成的市场报告",
                    "status": "completed",
                    "source": "official_api",
                }
            ],
            "confirmations": [
                {
                    "confirmation_id": "publish_guard",
                    "action_type": "publish_listing",
                    "title": "发布前人工确认",
                    "default_action": "hold",
                }
            ],
        },
    )
    confirmation = repo.list_confirmations(company_id=company["company_id"])[0]
    decided = repo.decide_confirmation(
        company_id=company["company_id"],
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=user["user_id"],
        note="migration rehearsal approval only",
    )
    repo.save_execution_result(
        confirmation=decided,
        result={
            "status": "dry_run_recorded",
            "action_type": decided["action_type"],
            "audit": {"real_execution": {"published_to_ebay": False}},
        },
    )

    summary = generate_rehearsal(
        sqlite_path=SQLITE_DB,
        out_sql_path=OUT_SQL,
        summary_path=SUMMARY_JSON,
    )
    summary_from_file = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    sql = OUT_SQL.read_text(encoding="utf-8")

    if summary != summary_from_file:
        return fail("summary JSON file should match returned summary")
    if summary.get("status") != "ready_for_isolated_postgres_import":
        return fail("rehearsal summary should be ready for isolated import")
    if summary.get("secret_exposed") is not False or summary.get("raw_rows_printed") is not False:
        return fail("summary must not expose raw row values or secrets")
    for table in ("companies", "users", "stores", "platform_data_packets", "tasks", "queue_jobs", "media_asset_jobs", "reports", "confirmations", "execution_results", "audit_logs"):
        if summary.get("table_counts", {}).get(table, 0) < 1:
            return fail(f"expected exported rows for {table}")
    if "\"packet_json\"" not in sql or "::jsonb" not in sql:
        return fail("generated SQL should cast JSON columns to jsonb")
    if "on conflict do nothing" not in sql:
        return fail("generated SQL should be append-safe for repeated rehearsals")
    if not _appears_before(sql, 'insert into "companies"', 'insert into "users"'):
        return fail("companies must be inserted before users for foreign keys")
    if not _appears_before(sql, 'insert into "stores"', 'insert into "tasks"'):
        return fail("stores must be inserted before tasks for foreign keys")
    if not _appears_before(sql, 'insert into "queue_jobs"', 'insert into "media_asset_jobs"'):
        return fail("queue jobs must be inserted before media asset jobs for foreign keys")
    if not _appears_before(sql, 'insert into "confirmations"', 'insert into "execution_results"'):
        return fail("confirmations must be inserted before execution results")
    if "local-test-password" in sql:
        return fail("plain-text password must not appear in generated SQL")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PASS jiejing_sqlite_to_postgres_rehearsal")
    return 0


def _appears_before(text: str, first: str, second: str) -> bool:
    first_index = text.find(first)
    second_index = text.find(second)
    return first_index >= 0 and second_index >= 0 and first_index < second_index


if __name__ == "__main__":
    raise SystemExit(main())
