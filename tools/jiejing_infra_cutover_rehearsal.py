#!/usr/bin/env python3
"""Postgres/Redis cutover rehearsal for Jiejing SaaS staging.

Default mode is dry-run. It prepares the exact artifacts and checks needed
before switching the SaaS backend away from SQLite/local queue. Live database
or Redis operations require explicit flags so this tool cannot silently mutate
infrastructure.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSSettings  # noqa: E402
from jiejing_saas.infrastructure_drivers import build_infrastructure_driver_status, run_postgres_migration  # noqa: E402
from jiejing_sqlite_to_postgres_rehearsal import generate_rehearsal  # noqa: E402


OUT = ROOT / "output" / "jiejing-infra-cutover-rehearsal"
DEFAULT_SQLITE_DB = ROOT / "output" / "jiejing-saas-backend" / "test" / "saas-test.sqlite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and optionally execute Jiejing Postgres/Redis cutover checks.")
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_DB)
    parser.add_argument("--database-url", default=os.environ.get("JIEJING_DATABASE_URL", ""))
    parser.add_argument("--queue-url", default=os.environ.get("JIEJING_QUEUE_URL", ""))
    parser.add_argument("--out", type=Path, default=OUT / "latest.json")
    parser.add_argument("--sql-out", type=Path, default=OUT / "sqlite-to-postgres-import.sql")
    parser.add_argument("--apply-postgres-migration", action="store_true")
    parser.add_argument("--apply-import-sql", action="store_true")
    parser.add_argument("--probe-redis-live", action="store_true")
    parser.add_argument("--confirm-live-infra-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.time()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.sql_out.parent.mkdir(parents=True, exist_ok=True)

    previous_env = _capture_env()
    try:
        _set_env_for_status(args)
        settings = SaaSSettings.from_env(
            db_path=args.sqlite_db,
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        driver_status = build_infrastructure_driver_status(settings)
    finally:
        _restore_env(previous_env)

    checks: list[dict[str, Any]] = []
    rehearsal = None
    if args.sqlite_db.exists():
        summary_path = args.out.with_name(args.out.stem + "-sqlite-summary.json")
        rehearsal = generate_rehearsal(sqlite_path=args.sqlite_db, out_sql_path=args.sql_out, summary_path=summary_path)
        checks.append({"key": "sqlite_export", "status": "ready", "row_count": rehearsal.get("total_rows"), "sql_path": str(args.sql_out), "secret_exposed": False})
    else:
        checks.append({"key": "sqlite_export", "status": "blocked", "blocked_by": ["sqlite_db_not_found"], "path": str(args.sqlite_db), "secret_exposed": False})

    migration_result = _maybe_run_postgres_migration(args)
    checks.append({"key": "postgres_migration", **migration_result})

    import_result = _maybe_apply_import_sql(args)
    checks.append({"key": "postgres_import_sql", **import_result})

    redis_result = _maybe_probe_redis(args)
    checks.append({"key": "redis_live_probe", **redis_result})

    blockers = _collect_blockers(checks, driver_status)
    summary = {
        "product": "Jiejing SaaS",
        "task": "infra_cutover_rehearsal",
        "status": "ready_for_manual_live_cutover" if not blockers else "blocked_or_dry_run",
        "dry_run": not args.confirm_live_infra_write,
        "sqlite_db": str(args.sqlite_db),
        "database_url_public": _redact_url(args.database_url),
        "queue_url_public": _redact_url(args.queue_url),
        "driver_status": driver_status,
        "checks": checks,
        "blockers": blockers,
        "rehearsal_summary": _safe_rehearsal_summary(rehearsal),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    dumped = json.dumps(summary, ensure_ascii=False, indent=2)
    if _contains_secret_sentinel(dumped, args):
        return fail("summary would expose a configured secret sentinel")
    args.out.write_text(dumped, encoding="utf-8")
    print(dumped)
    print(f"OUTPUT={args.out}")
    return 0 if not [item for item in blockers if item.startswith("failed_")] else 1


def _maybe_run_postgres_migration(args: argparse.Namespace) -> dict[str, Any]:
    if not args.apply_postgres_migration:
        return {"status": "not_requested", "live_write": False, "secret_exposed": False}
    if not args.confirm_live_infra_write:
        return {"status": "blocked", "blocked_by": ["missing_confirm_live_infra_write"], "live_write": False, "secret_exposed": False}
    result = run_postgres_migration(database_url=args.database_url)
    result["live_write"] = result.get("status") == "ok"
    result["secret_exposed"] = False
    return result


def _maybe_apply_import_sql(args: argparse.Namespace) -> dict[str, Any]:
    if not args.apply_import_sql:
        return {"status": "not_requested", "live_write": False, "secret_exposed": False}
    if not args.confirm_live_infra_write:
        return {"status": "blocked", "blocked_by": ["missing_confirm_live_infra_write"], "live_write": False, "secret_exposed": False}
    if not args.database_url:
        return {"status": "blocked", "blocked_by": ["missing_database_url"], "live_write": False, "secret_exposed": False}
    if not args.sql_out.exists():
        return {"status": "blocked", "blocked_by": ["missing_import_sql"], "live_write": False, "secret_exposed": False}
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_psycopg_dependency"], "live_write": False, "secret_exposed": False}
    try:
        with psycopg.connect(args.database_url, connect_timeout=10) as conn:
            with conn.cursor() as cursor:
                cursor.execute(args.sql_out.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "database_url_public": _redact_url(args.database_url),
            "live_write": False,
            "secret_exposed": False,
        }
    return {"status": "ok", "database_url_public": _redact_url(args.database_url), "live_write": True, "secret_exposed": False}


def _maybe_probe_redis(args: argparse.Namespace) -> dict[str, Any]:
    if not args.probe_redis_live:
        return {"status": "not_requested", "live_network_call": False, "secret_exposed": False}
    if not args.queue_url:
        return {"status": "blocked", "blocked_by": ["missing_queue_url"], "live_network_call": False, "secret_exposed": False}
    try:
        import redis  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_redis_dependency"], "live_network_call": False, "secret_exposed": False}
    try:
        client = redis.Redis.from_url(args.queue_url, socket_connect_timeout=5, socket_timeout=5)
        pong = client.ping()
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "queue_url_public": _redact_url(args.queue_url),
            "live_network_call": True,
            "secret_exposed": False,
        }
    return {"status": "ok", "ping": bool(pong), "queue_url_public": _redact_url(args.queue_url), "live_network_call": True, "secret_exposed": False}


def _set_env_for_status(args: argparse.Namespace) -> None:
    os.environ["JIEJING_SAAS_ENV"] = "staging"
    os.environ["JIEJING_DATABASE_ENGINE"] = "postgres"
    os.environ["JIEJING_DATABASE_ADAPTER"] = "postgres-managed"
    os.environ["JIEJING_QUEUE_PROVIDER"] = "redis_streams"
    if args.database_url:
        os.environ["JIEJING_DATABASE_URL"] = args.database_url
    else:
        os.environ.pop("JIEJING_DATABASE_URL", None)
    if args.queue_url:
        os.environ["JIEJING_QUEUE_URL"] = args.queue_url
    else:
        os.environ.pop("JIEJING_QUEUE_URL", None)


def _capture_env() -> dict[str, str | None]:
    keys = {
        "JIEJING_SAAS_ENV",
        "JIEJING_DATABASE_ENGINE",
        "JIEJING_DATABASE_ADAPTER",
        "JIEJING_DATABASE_URL",
        "JIEJING_QUEUE_PROVIDER",
        "JIEJING_QUEUE_URL",
    }
    return {key: os.environ.get(key) for key in keys}


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _collect_blockers(checks: list[dict[str, Any]], driver_status: dict[str, Any]) -> list[str]:
    blockers = list(driver_status.get("cutover_blockers") or [])
    for check in checks:
        status = str(check.get("status") or "")
        if status == "blocked":
            blockers.extend(str(item) for item in check.get("blocked_by", []))
        if status == "failed":
            blockers.append(f"failed_{check.get('key')}")
    return sorted(set(blockers))


def _safe_rehearsal_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    return {
        "status": summary.get("status"),
        "total_rows": summary.get("total_rows"),
        "exported_tables": summary.get("exported_tables"),
        "missing_tables": summary.get("missing_tables"),
        "json_column_count": summary.get("json_column_count"),
        "raw_rows_printed": summary.get("raw_rows_printed"),
        "secret_exposed": False,
    }


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        username = userinfo.split(":", 1)[0]
        netloc = f"{username}:***@{host}" if username else f"***@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _contains_secret_sentinel(dumped: str, args: argparse.Namespace) -> bool:
    sentinels = []
    for value in (args.database_url, args.queue_url):
        if not value or "@" not in value:
            continue
        userinfo = urlsplit(value).netloc.split("@", 1)[0]
        if ":" in userinfo:
            password = userinfo.split(":", 1)[1]
            if password:
                sentinels.append(password)
    return any(sentinel in dumped for sentinel in sentinels)


def fail(message: str) -> int:
    print(json.dumps({"status": "failed", "error": message, "secret_exposed": False}, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
