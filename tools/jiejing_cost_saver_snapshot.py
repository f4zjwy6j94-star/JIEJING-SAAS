#!/usr/bin/env python3
"""Create and verify a Jiejing cost-saver data snapshot.

This tool is intentionally offline and read-only. It is for the moment before
paid infrastructure is paused or destroyed: capture the active SQLite SaaS DB
into a manifest plus per-table JSONL files, then verify the snapshot is not an
empty directory. It never writes to eBay, model providers, or platform APIs.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_DB = Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite")
DEFAULT_OUT_ROOT = ROOT / "output" / "jiejing-cost-saver-snapshots"

CONTRACT_VERSION = "2026-05-21-cost-saver-snapshot-v1"

TABLE_ORDER = (
    "companies",
    "users",
    "team_members",
    "team_invitations",
    "stores",
    "secret_refs",
    "platform_connections",
    "oauth_authorization_requests",
    "platform_data_packets",
    "tasks",
    "queue_jobs",
    "task_steps",
    "reports",
    "confirmations",
    "merchant_memory",
    "execution_results",
    "audit_logs",
    "schema_migrations",
)

REQUIRED_TABLES = (
    "companies",
    "users",
    "stores",
    "secret_refs",
    "platform_connections",
    "platform_data_packets",
    "reports",
    "confirmations",
    "merchant_memory",
    "audit_logs",
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
    "step_json",
    "report_json",
    "item_json",
    "memory_json",
    "result_json",
    "audit_json",
}

RAW_SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "bearer_token",
    "client_secret",
    "ebay_access_token",
    "ebay_refresh_token",
    "id_token",
    "model_api_key",
    "model_key",
    "private_key",
    "provider_api_key",
    "raw_secret",
    "raw_token",
    "refresh_token",
    "secret_key",
    "secret_value",
}

SAFE_EMPTY_OR_FALSE = {"", "0", "false", "none", "null", "redacted", "[redacted]", "***", "masked"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify a Jiejing cost-saver snapshot.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a read-only SQLite snapshot.")
    export_parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE_DB, help="Source SaaS SQLite database.")
    export_parser.add_argument("--out", type=Path, default=None, help="Snapshot output directory.")
    export_parser.add_argument("--reason", default="cost_saver_before_paid_resource_pause")
    export_parser.add_argument("--allow-empty", action="store_true", help="Allow a zero-row snapshot for local test fixtures only.")

    verify_parser = subparsers.add_parser("verify", help="Verify a previously exported snapshot.")
    verify_parser.add_argument("--snapshot", type=Path, required=True, help="Snapshot directory containing manifest.json.")
    verify_parser.add_argument("--allow-empty", action="store_true", help="Allow a zero-row snapshot for local test fixtures only.")

    args = parser.parse_args()
    try:
        if args.command == "export":
            out_dir = args.out or _default_snapshot_dir()
            summary = export_sqlite_snapshot(
                sqlite_path=args.sqlite,
                output_dir=out_dir,
                reason=args.reason,
                allow_empty=args.allow_empty,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print(f"SNAPSHOT_DIR={summary['snapshot_dir']}")
            return 0
        if args.command == "verify":
            summary = verify_snapshot(snapshot_dir=args.snapshot, allow_empty=args.allow_empty)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print(f"SNAPSHOT_DIR={summary['snapshot_dir']}")
            return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "secret_exposed": False}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 2


def export_sqlite_snapshot(*, sqlite_path: Path, output_dir: Path, reason: str, allow_empty: bool = False) -> dict[str, Any]:
    sqlite_path = sqlite_path.resolve()
    output_dir = output_dir.resolve()
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"snapshot output directory is not empty: {output_dir}")

    tables_dir = output_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("pragma query_only = on")
        existing_tables = _table_names(conn)
        ordered_tables = [table for table in TABLE_ORDER if table in existing_tables]
        ordered_tables.extend(sorted(existing_tables.difference(TABLE_ORDER)))
        missing_required = [table for table in REQUIRED_TABLES if table not in existing_tables]
        if missing_required:
            raise ValueError("snapshot missing required tables: " + ",".join(missing_required))

        schema_sql = _schema_sql(conn, ordered_tables)
        (output_dir / "schema.sql").write_text(schema_sql, encoding="utf-8")

        table_manifests: list[dict[str, Any]] = []
        total_rows = 0
        for table in ordered_tables:
            table_manifest = _export_table(conn, table=table, tables_dir=tables_dir)
            table_manifests.append(table_manifest)
            total_rows += int(table_manifest["row_count"])

    business_rows = sum(
        int(item["row_count"]) for item in table_manifests if item.get("table") != "schema_migrations"
    )
    if business_rows == 0 and not allow_empty:
        raise ValueError("snapshot has zero business rows; refusing to treat it as a cost-saver recovery artifact")
    if not table_manifests:
        raise ValueError("snapshot has no table exports")

    table_counts = {item["table"]: item["row_count"] for item in table_manifests}
    manifest = {
        "product": "Jiejing SaaS",
        "contract_version": CONTRACT_VERSION,
        "task": "cost_saver_snapshot",
        "status": "snapshot_ready",
        "reason": reason,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_engine": "sqlite",
        "source_sqlite_path": str(sqlite_path),
        "snapshot_dir": str(output_dir),
        "table_count": len(table_manifests),
        "total_rows": total_rows,
        "business_rows": business_rows,
        "required_tables": list(REQUIRED_TABLES),
        "required_tables_present": True,
        "table_counts": table_counts,
        "tables": table_manifests,
        "schema_sha256": _sha256(output_dir / "schema.sql"),
        "raw_secret_export_allowed": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "restore_note": "Restore only inside a private Jiejing staging/runtime boundary; generated files contain tenant records and password hashes but no raw provider tokens or model keys.",
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = verify_snapshot(snapshot_dir=output_dir, allow_empty=allow_empty)
    return {**manifest, "verification": verified}


def verify_snapshot(*, snapshot_dir: Path, allow_empty: bool = False) -> dict[str, Any]:
    snapshot_dir = snapshot_dir.resolve()
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"snapshot manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise ValueError(f"unsupported snapshot contract: {manifest.get('contract_version')}")
    tables = manifest.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("snapshot manifest has no table files")
    total_rows = int(manifest.get("total_rows") or 0)
    business_rows = int(manifest.get("business_rows") if manifest.get("business_rows") is not None else total_rows)
    if business_rows == 0 and not allow_empty:
        raise ValueError("snapshot business_rows is zero")

    verified_tables = []
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("snapshot table entry is not an object")
        rel_path = str(item.get("file") or "")
        if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
            raise ValueError(f"unsafe snapshot table path: {rel_path}")
        table_path = snapshot_dir / rel_path
        if not table_path.exists():
            raise FileNotFoundError(f"snapshot table file not found: {table_path}")
        row_count = int(item.get("row_count") or 0)
        line_count = _line_count(table_path)
        if line_count != row_count:
            raise ValueError(f"snapshot row count mismatch for {item.get('table')}: manifest={row_count} lines={line_count}")
        bytes_size = table_path.stat().st_size
        if row_count > 0 and bytes_size <= 0:
            raise ValueError(f"snapshot table file is empty despite rows: {item.get('table')}")
        digest = _sha256(table_path)
        if digest != item.get("sha256"):
            raise ValueError(f"snapshot sha256 mismatch for {item.get('table')}")
        verified_tables.append({"table": item.get("table"), "row_count": row_count, "bytes": bytes_size})

    present_tables = {str(item.get("table")) for item in tables if isinstance(item, dict)}
    missing_required = [table for table in REQUIRED_TABLES if table not in present_tables]
    if missing_required:
        raise ValueError("snapshot missing required table files: " + ",".join(missing_required))
    if (snapshot_dir / "schema.sql").exists():
        schema_digest = _sha256(snapshot_dir / "schema.sql")
        if schema_digest != manifest.get("schema_sha256"):
            raise ValueError("snapshot schema sha256 mismatch")

    return {
        "product": "Jiejing SaaS",
        "contract_version": CONTRACT_VERSION,
        "task": "cost_saver_snapshot_verify",
        "status": "snapshot_verified",
        "snapshot_dir": str(snapshot_dir),
        "table_count": len(verified_tables),
        "total_rows": total_rows,
        "business_rows": business_rows,
        "required_tables_present": True,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _export_table(conn: sqlite3.Connection, *, table: str, tables_dir: Path) -> dict[str, Any]:
    columns = _table_columns(conn, table)
    table_file = tables_dir / f"{table}.jsonl"
    row_count = 0
    with table_file.open("w", encoding="utf-8", newline="\n") as fh:
        for row in _table_rows(conn, table=table, columns=columns):
            payload = {column: _jsonable(row[column]) for column in columns}
            leaks = _raw_secret_leaks(payload, path=table)
            if leaks:
                raise ValueError("raw secret-like values found while exporting " + table + ": " + ",".join(leaks[:5]))
            fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            row_count += 1
    return {
        "table": table,
        "file": table_file.relative_to(tables_dir.parent).as_posix(),
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "json_columns": [column for column in columns if column in JSON_COLUMNS],
        "bytes": table_file.stat().st_size,
        "sha256": _sha256(table_file),
    }


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
    column_sql = ", ".join(_quote_sqlite_identifier(column) for column in columns)
    order_by = ", ".join(_quote_sqlite_identifier(column) for column in columns)
    return conn.execute(
        f"select {column_sql} from {_quote_sqlite_identifier(table)} order by {order_by}"
    ).fetchall()


def _schema_sql(conn: sqlite3.Connection, tables: list[str]) -> str:
    rows = conn.execute(
        """
        select name, sql from sqlite_master
        where type in ('table', 'index') and name not like 'sqlite_%'
        order by type, name
        """
    ).fetchall()
    allowed_prefixes = set(tables)
    lines = [
        "-- Jiejing SaaS cost-saver SQLite schema snapshot.",
        "-- Contains schema only; table data is exported as JSONL beside the manifest.",
        "",
    ]
    for row in rows:
        name = str(row["name"])
        sql = row["sql"]
        if not sql:
            continue
        if name in allowed_prefixes or any(name.startswith(f"idx_{table}") for table in allowed_prefixes):
            lines.append(str(sql).rstrip(";") + ";")
    lines.append("")
    return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    return value


def _raw_secret_leaks(value: Any, *, path: str) -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            next_path = f"{path}.{key_text}"
            if normalized in RAW_SECRET_KEYS and _has_secret_like_value(item):
                leaks.append(next_path)
            if normalized in JSON_COLUMNS and isinstance(item, str):
                parsed = _parse_json_maybe(item)
                if parsed is not None:
                    leaks.extend(_raw_secret_leaks(parsed, path=next_path))
                    continue
            leaks.extend(_raw_secret_leaks(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaks.extend(_raw_secret_leaks(item, path=f"{path}[{index}]"))
    return leaks


def _has_secret_like_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, (dict, list)):
        return bool(value)
    text = str(value).strip()
    return text.lower() not in SAFE_EMPTY_OR_FALSE


def _parse_json_maybe(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _quote_sqlite_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_snapshot_dir() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return DEFAULT_OUT_ROOT / stamp


if __name__ == "__main__":
    raise SystemExit(main())
