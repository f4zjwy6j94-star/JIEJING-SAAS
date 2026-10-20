#!/usr/bin/env python3
"""Generate a SQLite -> PostgreSQL import rehearsal script for Jiejing SaaS.

This tool is intentionally offline and conservative. It reads the local SQLite
MVP database, writes a PostgreSQL INSERT script in foreign-key-safe order, and
emits only table counts in its summary. It does not connect to Postgres and it
does not print row values to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "jiejing_saas" / "migrations" / "001_initial_schema_postgres.sql"
DEFAULT_OUT = ROOT / "output" / "jiejing-infrastructure-stage-gate" / "sqlite-to-postgres-rehearsal.sql"
DEFAULT_SUMMARY = ROOT / "output" / "jiejing-infrastructure-stage-gate" / "sqlite-to-postgres-rehearsal.json"

TABLE_ORDER = (
    "companies",
    "users",
    "platform_trial_activations",
    "platform_model_trial_reservations",
    "user_refresh_sessions",
    "user_refresh_token_history",
    "user_sessions",
    "team_members",
    "access_revocation_epochs",
    "team_invitations",
    "stores",
    "ai_ceo_chat_turns",
    "secret_refs",
    "platform_connections",
    "oauth_authorization_requests",
    "platform_data_packets",
    "tasks",
    "queue_jobs",
    "ebay_account_deletion_events",
    "media_asset_jobs",
    "task_steps",
    "reports",
    "listing_draft_edit_heads",
    "listing_draft_edit_revisions",
    "confirmations",
    "confirmation_approval_authorities_v1",
    "confirmation_execution_authorities_v1",
    "external_execution_claims",
    "execution_results",
    "audit_logs",
    "platform_analytics_events",
    "model_usage_ledger",
    "provider_cost_ledger",
    "platform_reliability_alert_state",
    "platform_reliability_alert_events",
    "schema_migrations",
)

JSON_COLUMNS = {
    "invite_json",
    "store_json",
    "metadata_json",
    "scopes_json",
    "request_json",
    "packet_json",
    "input_json",
    "output_json",
    "job_json",
    "deletion_event_json",
    "media_job_json",
    "turn_json",
    "step_json",
    "report_json",
    "receipt_json",
    "item_json",
    "binding_json",
    "result_json",
    "audit_json",
    "analytics_json",
    "usage_json",
    "cost_json",
    "state_json",
    "event_json",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Jiejing SQLite to Postgres import rehearsal script.")
    parser.add_argument("--sqlite", required=True, type=Path, help="Path to the source SQLite SaaS database.")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA, type=Path, help="Postgres schema migration used as the target contract.")
    parser.add_argument("--out-sql", default=DEFAULT_OUT, type=Path, help="Path to write the generated import SQL.")
    parser.add_argument("--summary", default=DEFAULT_SUMMARY, type=Path, help="Path to write the summary JSON.")
    args = parser.parse_args()

    try:
        summary = generate_rehearsal(
            sqlite_path=args.sqlite,
            schema_path=args.schema,
            out_sql_path=args.out_sql,
            summary_path=args.summary,
        )
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"OUTPUT_SQL={args.out_sql}")
    print(f"OUTPUT_SUMMARY={args.summary}")
    return 0


def generate_rehearsal(
    *,
    sqlite_path: Path,
    schema_path: Path = DEFAULT_SCHEMA,
    out_sql_path: Path = DEFAULT_OUT,
    summary_path: Path = DEFAULT_SUMMARY,
) -> dict[str, Any]:
    sqlite_path = sqlite_path.resolve()
    schema_path = schema_path.resolve()
    out_sql_path = out_sql_path.resolve()
    summary_path = summary_path.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if not schema_path.exists():
        raise FileNotFoundError(f"Postgres schema not found: {schema_path}")

    out_sql_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        # All epochs, pointers and receipts must describe one source snapshot.
        conn.execute('begin')
        existing_tables = _table_names(conn)
        export_tables = [table for table in TABLE_ORDER if table in existing_tables]
        missing_tables = [table for table in TABLE_ORDER if table not in existing_tables]
        table_counts: dict[str, int] = {}
        json_column_count = 0
        lines = _sql_header(sqlite_path=sqlite_path, schema_path=schema_path)
        pointer_rows = []
        for table in export_tables:
            columns = _table_columns(conn, table)
            json_column_count += len([column for column in columns if column in JSON_COLUMNS])
            rows = _table_rows(conn, table=table, columns=columns)
            table_counts[table] = len(rows)
            if table == 'confirmations' and 'approval_authority_id' in columns:
                pointer_rows = [dict(row) for row in rows]
                # Break only the current-pointer cycle; immutable history is
                # imported unchanged next, then the exact projection restored.
                rows = [{**row,'approval_authority_id':None} for row in pointer_rows]
            lines.extend(_table_insert_sql(table=table, columns=columns, rows=rows))
            if table in {'access_revocation_epochs','confirmation_approval_authorities_v1',
                         'confirmation_execution_authorities_v1','external_execution_claims'}:
                # ON CONFLICT is not permission to merge different histories.
                # A mismatch raises division-by-zero inside this transaction.
                lines.extend(_exact_row_guards(table,columns,rows))
        lines.append('-- Restore current approval pointers after immutable receipts.')
        for row in pointer_rows:
            columns = list(row)
            # Guard the existing parent before updating any current projection.
            lines.extend(_exact_row_guards('confirmations',[c for c in columns if c!='approval_authority_id'],[row]))
            pointer = _pg_literal(row['approval_authority_id'],column='approval_authority_id')
            company = _pg_literal(row['company_id'],column='company_id')
            confirmation = _pg_literal(row['confirmation_id'],column='confirmation_id')
            lines.append('update "confirmations" set "approval_authority_id"='+pointer+
                ' where "company_id"='+company+' and "confirmation_id"='+confirmation+
                ' and ("approval_authority_id" is null or "approval_authority_id" is not distinct from '+pointer+');')
            lines.extend(_exact_row_guards('confirmations',columns,[row]))
        lines.append("commit;")
        lines.append("")

    sql_text = "\n".join(lines)
    out_sql_path.write_text(sql_text, encoding="utf-8")
    sql_sha256 = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
    summary = {
        "product": "Jiejing SaaS",
        "task": "sqlite_to_postgres_migration_rehearsal",
        "status": "ready_for_isolated_postgres_import",
        "source_engine": "sqlite",
        "target_engine": "postgres",
        "source_sqlite_path": str(sqlite_path),
        "target_schema_path": str(schema_path),
        "generated_sql_path": str(out_sql_path),
        "sql_sha256": sql_sha256,
        "table_counts": table_counts,
        "total_rows": sum(table_counts.values()),
        "exported_tables": export_tables,
        "missing_tables": missing_tables,
        "json_column_count": json_column_count,
        "import_mode": "append_with_on_conflict_do_nothing",
        "authority_import_contract": "exact_history_and_epochs_then_current_pointer_v1",
        "raw_rows_printed": False,
        "secret_exposed": False,
        "real_platform_writes_enabled": False,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        select name from sqlite_master
        where type = 'table' and name not like 'sqlite_%'
        order by name
        """
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"pragma table_info({_quote_sqlite_identifier(table)})").fetchall()
    columns = [str(row["name"]) for row in rows]
    if not columns:
        raise ValueError(f"table has no columns: {table}")
    return columns


def _table_rows(conn: sqlite3.Connection, *, table: str, columns: list[str]) -> list[sqlite3.Row]:
    order_by = ", ".join(_quote_sqlite_identifier(column) for column in columns)
    column_sql = ", ".join(_quote_sqlite_identifier(column) for column in columns)
    return conn.execute(
        f"select {column_sql} from {_quote_sqlite_identifier(table)} order by {order_by}"
    ).fetchall()


def _table_insert_sql(*, table: str, columns: list[str], rows: list[Any]) -> list[str]:
    if not rows:
        return [f"-- {table}: 0 rows"]
    column_sql = ", ".join(_quote_pg_identifier(column) for column in columns)
    lines = [f"-- {table}: {len(rows)} rows"]
    for row in rows:
        value_sql = ", ".join(_pg_literal(row[column], column=column) for column in columns)
        lines.append(f"insert into {_quote_pg_identifier(table)} ({column_sql}) values ({value_sql}) on conflict do nothing;")
    return lines


def _exact_row_guards(table: str, columns: list[str], rows: list[Any]) -> list[str]:
    # Do not put merchant strings inside a dollar-quoted DO body. Ordinary
    # escaped literals and typed column comparisons keep this offline export
    # safe even when a stored value itself contains $$ or SQL-looking text.
    return ['select 1 / count(*) from '+_quote_pg_identifier(table)+' where '+
        ' and '.join(_quote_pg_identifier(column)+' is not distinct from '+_pg_literal(row[column],column=column)
                     for column in columns)+';' for row in rows]


def _sql_header(*, sqlite_path: Path, schema_path: Path) -> list[str]:
    return [
        "-- Jiejing SaaS SQLite -> PostgreSQL migration rehearsal.",
        "-- Apply every registered PostgreSQL migration before this import in an isolated Postgres instance.",
        "-- This file may contain hashed credentials and tenant records from the source database.",
        "-- Do not commit or share generated import SQL.",
        f"-- source_sqlite={sqlite_path}",
        f"-- target_schema={schema_path}",
        "begin;",
        "",
    ]


def _pg_literal(value: Any, *, column: str) -> str:
    if value is None:
        return "null"
    if column in JSON_COLUMNS:
        return f"{_pg_text_literal(_normalize_json(value, column=column))}::jsonb"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, bytes):
        return "'\\x" + value.hex() + "'"
    return _pg_text_literal(str(value))


def _normalize_json(value: Any, *, column: str) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {column}: {exc}") from exc
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def _pg_text_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quote_pg_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_sqlite_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


if __name__ == "__main__":
    raise SystemExit(main())
