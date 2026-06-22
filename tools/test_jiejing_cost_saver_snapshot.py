#!/usr/bin/env python3
"""Regression checks for the cost-saver snapshot exporter."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from jiejing_saas import SaaSRepository  # noqa: E402
from jiejing_cost_saver_snapshot import export_sqlite_snapshot, verify_snapshot  # noqa: E402


OUT = ROOT / "output" / "jiejing-cost-saver-snapshot-test"
SQLITE_DB = OUT / "fixture.sqlite"
SNAPSHOT_DIR = OUT / "snapshot"
EMPTY_SNAPSHOT_DIR = OUT / "empty-snapshot"
ZERO_ROW_DB = OUT / "zero-row.sqlite"
LEAKY_DB = OUT / "leaky.sqlite"
LEAKY_SNAPSHOT_DIR = OUT / "leaky-snapshot"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    _reset_output()
    _create_fixture_db(SQLITE_DB)

    summary = export_sqlite_snapshot(sqlite_path=SQLITE_DB, output_dir=SNAPSHOT_DIR, reason="test_cost_saver_snapshot")
    verified = verify_snapshot(snapshot_dir=SNAPSHOT_DIR)
    manifest = json.loads((SNAPSHOT_DIR / "manifest.json").read_text(encoding="utf-8"))

    if summary.get("status") != "snapshot_ready":
        return fail("snapshot export should report snapshot_ready")
    if verified.get("status") != "snapshot_verified":
        return fail("snapshot verify should report snapshot_verified")
    if summary.get("secret_exposed") is not False or verified.get("secret_exposed") is not False:
        return fail("snapshot summaries must not expose secrets")
    if summary.get("raw_secret_export_allowed") is not False:
        return fail("snapshot manifest must forbid raw secret export")
    if summary.get("real_platform_writes_enabled") is not False:
        return fail("snapshot tool must keep real platform writes disabled")
    if summary.get("total_rows", 0) <= 0:
        return fail("fixture snapshot should not be empty")
    for table in ("companies", "users", "stores", "secret_refs", "platform_data_packets", "reports", "confirmations", "merchant_memory", "audit_logs"):
        if manifest.get("table_counts", {}).get(table, 0) < 1:
            return fail(f"expected exported rows for {table}")
        table_path = SNAPSHOT_DIR / "tables" / f"{table}.jsonl"
        if not table_path.exists() or table_path.stat().st_size <= 0:
            return fail(f"expected non-empty table export for {table}")
    if not (SNAPSHOT_DIR / "schema.sql").exists():
        return fail("snapshot should include schema.sql")

    dumped = json.dumps(summary, ensure_ascii=False)
    for forbidden in ("sk-live-danger", "raw-live-token", "raw-refresh-token"):
        if forbidden in dumped:
            return fail(f"snapshot summary leaked forbidden marker {forbidden}")

    try:
        verify_snapshot(snapshot_dir=EMPTY_SNAPSHOT_DIR)
        return fail("empty snapshot directory should not verify")
    except FileNotFoundError:
        pass

    SaaSRepository(ZERO_ROW_DB).initialize()
    try:
        export_sqlite_snapshot(sqlite_path=ZERO_ROW_DB, output_dir=OUT / "zero-row-snapshot", reason="zero_row_test")
        return fail("zero-row snapshot should fail unless explicitly allowed")
    except ValueError as exc:
        if "zero business rows" not in str(exc):
            return fail(f"zero-row snapshot failed with unexpected message: {exc}")

    shutil.copyfile(SQLITE_DB, LEAKY_DB)
    with sqlite3.connect(LEAKY_DB) as conn:
        conn.execute(
            "update secret_refs set metadata_json = ? where secret_ref = ?",
            (json.dumps({"api_key": "sk-live-danger", "secret_ref_only": False}), "secret_model_fixture"),
        )
        conn.commit()
    try:
        export_sqlite_snapshot(sqlite_path=LEAKY_DB, output_dir=LEAKY_SNAPSHOT_DIR, reason="leak_guard_test")
        return fail("snapshot should reject raw provider secret markers")
    except ValueError as exc:
        if "raw secret-like values" not in str(exc):
            return fail(f"raw secret rejection had unexpected message: {exc}")

    print(json.dumps({"status": "PASS", "snapshot_dir": str(SNAPSHOT_DIR), "total_rows": summary.get("total_rows")}, ensure_ascii=False, indent=2))
    print("PASS jiejing_cost_saver_snapshot")
    return 0


def _reset_output() -> None:
    output_root = (ROOT / "output").resolve()
    target = OUT.resolve()
    if output_root not in target.parents:
        raise RuntimeError(f"refusing to delete outside output root: {target}")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    EMPTY_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _create_fixture_db(path: Path) -> None:
    repo = SaaSRepository(path)
    repo.initialize()
    now = "2026-05-21T16:00:00Z"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            insert into companies (company_id, name, created_at)
            values ('company_snapshot_fixture', 'Jiejing Snapshot Fixture', '2026-05-21T16:00:00Z');

            insert into users (user_id, email, password_salt, password_hash, status, default_company_id, created_at)
            values ('user_snapshot_fixture', 'snapshot-fixture@jiejing.local', 'salt-fixture', 'hash-fixture', 'active', 'company_snapshot_fixture', '2026-05-21T16:00:00Z');

            insert into team_members (company_id, user_id, role, created_at)
            values ('company_snapshot_fixture', 'user_snapshot_fixture', 'owner', '2026-05-21T16:00:00Z');
            """
        )
        conn.execute(
            """
            insert into stores (store_id, company_id, platform, store_name, marketplace, stage, created_by, created_at, store_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "store_snapshot_fixture",
                "company_snapshot_fixture",
                "ebay",
                "northvalesource official packet",
                "EBAY_US",
                "read_only_authorized",
                "user_snapshot_fixture",
                now,
                json.dumps({"display_name": "northvalesource official packet", "source": "official_api"}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            insert into secret_refs (secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "secret_model_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "DeepSeek",
                "model_byok",
                "managed_vault_stored",
                "user_snapshot_fixture",
                now,
                json.dumps({"secret_ref_only": True, "provider": "DeepSeek", "raw_secret_stored": False}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            insert into platform_connections (connection_id, company_id, store_id, platform, connection_type, status, scopes_json, secret_ref, metadata_json, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "connection_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "ebay",
                "oauth_read_only",
                "read_only_authorized",
                json.dumps(["https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"]),
                "secret_model_fixture",
                json.dumps({"token_visible_to_frontend": False, "raw_token_stored_in_database": False}),
                "user_snapshot_fixture",
                now,
            ),
        )
        conn.execute(
            """
            insert into platform_data_packets (packet_id, company_id, store_id, platform, packet_type, source_mode, status, created_by, created_at, expires_at, packet_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "packet_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "ebay",
                "ebay_read_only_snapshot",
                "official_api",
                "created",
                "user_snapshot_fixture",
                now,
                None,
                json.dumps({"source_records": [{"source_type": "official_ebay_packet"}], "secret_exposed": False}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            insert into tasks (task_id, company_id, store_id, user_id, runtime_run_id, task_type, title, status, created_at, updated_at, input_json, output_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "user_snapshot_fixture",
                "run_snapshot_fixture",
                "ai_ceo_workflow",
                "Cost saver snapshot fixture",
                "completed",
                now,
                now,
                json.dumps({"packet_id": "packet_snapshot_fixture"}),
                json.dumps({"status": "completed"}),
            ),
        )
        conn.execute(
            """
            insert into reports (report_id, task_id, runtime_run_id, report_type, title, status, created_at, report_json)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "report_snapshot_fixture",
                "task_snapshot_fixture",
                "run_snapshot_fixture",
                "market.report",
                "Live model-backed Market Report",
                "completed",
                now,
                json.dumps({"source_records": ["official_ebay_packet", "model_inference"], "secret_exposed": False}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            insert into confirmations (confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status, default_action, created_at, item_json, decided_by, decided_at, decision_note)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "confirm_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "task_snapshot_fixture",
                "run_snapshot_fixture",
                "publish_listing",
                "Confirm real eBay publish",
                "pending",
                "hold",
                now,
                json.dumps({"real_platform_writes_enabled": False, "requires_human_confirmation": True}, ensure_ascii=False),
                None,
                None,
                None,
            ),
        )
        conn.execute(
            """
            insert into merchant_memory (memory_id, company_id, store_id, memory_type, source_type, source_id, title, summary, importance, tags_json, memory_json, created_by, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "memory_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "merchant_rule",
                "report",
                "report_snapshot_fixture",
                "Keep source records visible",
                "Merchant wants every conclusion tied to official packet, upload, public page, or model inference.",
                4,
                json.dumps(["source_records", "market_report"]),
                json.dumps({"permanent_merchant_memory": True, "secret_exposed": False}, ensure_ascii=False),
                "user_snapshot_fixture",
                now,
                now,
            ),
        )
        conn.execute(
            """
            insert into audit_logs (audit_id, company_id, store_id, user_id, actor_type, action_type, target_type, target_id, summary, created_at, audit_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit_snapshot_fixture",
                "company_snapshot_fixture",
                "store_snapshot_fixture",
                "user_snapshot_fixture",
                "system",
                "cost_saver_snapshot.fixture",
                "snapshot",
                "snapshot_fixture",
                "Fixture audit record for cost-saver snapshot test.",
                now,
                json.dumps({"secret_exposed": False, "real_platform_writes_enabled": False}, ensure_ascii=False),
            ),
        )
        conn.commit()


if __name__ == "__main__":
    raise SystemExit(main())
