#!/usr/bin/env python3
"""Regression checks for the Postgres/Redis cutover rehearsal tool."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "jiejing-infra-cutover-rehearsal-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # Build a current SQLite fixture through the existing backend E2E so the
    # rehearsal exercises real SaaS tables rather than a hand-written stub.
    backend = subprocess.run(
        [sys.executable, "tools/test_jiejing_saas_backend_mvp.py"],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if backend.returncode != 0:
        return fail("backend fixture failed: " + backend.stdout[-500:] + backend.stderr[-500:])

    out_path = OUT / "latest.json"
    sql_path = OUT / "import.sql"
    cmd = [
        sys.executable,
        "tools/jiejing_infra_cutover_rehearsal.py",
        "--sqlite-db",
        str(ROOT / "output" / "jiejing-saas-backend" / "test" / "saas-test.sqlite"),
        "--database-url",
        "postgresql://jiejing:super-secret-db@postgres:5432/jiejing",
        "--queue-url",
        "redis://:super-secret-redis@redis:6379/0",
        "--out",
        str(out_path),
        "--sql-out",
        str(sql_path),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return fail("dry-run rehearsal should pass without live infra writes")
    if not out_path.exists() or not sql_path.exists():
        return fail("rehearsal should write JSON summary and import SQL")
    text = out_path.read_text(encoding="utf-8")
    if "super-secret" in text or "super-secret" in completed.stdout:
        return fail("rehearsal output must redact database and queue URL passwords")
    data = json.loads(text)
    if data.get("dry_run") is not True:
        return fail("rehearsal must default to dry-run")
    if data.get("real_platform_writes_enabled") is not False or data.get("secret_exposed") is not False:
        return fail("rehearsal must preserve no-real-write and no-secret-exposure flags")
    checks = {item.get("key"): item for item in data.get("checks", [])}
    if checks.get("sqlite_export", {}).get("status") != "ready":
        return fail("rehearsal should export SQLite fixture")
    if checks.get("postgres_migration", {}).get("status") != "not_requested":
        return fail("Postgres migration should not run unless explicitly requested")
    if checks.get("postgres_import_sql", {}).get("status") != "not_requested":
        return fail("Postgres import should not run unless explicitly requested")
    if checks.get("redis_live_probe", {}).get("status") != "not_requested":
        return fail("Redis live probe should not run unless explicitly requested")
    if data.get("rehearsal_summary", {}).get("raw_rows_printed") is not False:
        return fail("rehearsal summary must not print raw row data")

    blocked = subprocess.run(
        [
            *cmd,
            "--apply-postgres-migration",
        ],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    blocked_data = json.loads(out_path.read_text(encoding="utf-8"))
    blocked_checks = {item.get("key"): item for item in blocked_data.get("checks", [])}
    if blocked_checks.get("postgres_migration", {}).get("status") != "blocked":
        return fail("live Postgres migration must be blocked without confirm flag")
    if "missing_confirm_live_infra_write" not in blocked_checks.get("postgres_migration", {}).get("blocked_by", []):
        return fail("blocked live migration should explain missing confirm flag")

    print(json.dumps({"infra_cutover_rehearsal": "pass", "secret_exposed": False}, ensure_ascii=False, indent=2))
    print("PASS jiejing_infra_cutover_rehearsal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
