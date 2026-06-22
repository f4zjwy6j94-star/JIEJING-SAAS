"""Runtime infrastructure driver status for Jiejing SaaS.

This module is the next layer after the adapter contracts. It can validate
Python dependencies, redacted connection configuration, migration runner shape,
repository/worker cutover implementation status, and optional live
Postgres/Redis probes. It deliberately keeps the public API honest: runtime
cutover is ready only when implementation, dependencies, URLs and live checks
are all satisfied.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import SaaSSettings
from .postgres_repository_runtime import postgres_connect_timeout_seconds
from .redis_queue_runtime import redis_runtime_status


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_MIGRATION = ROOT / "jiejing_saas" / "migrations" / "001_initial_schema_postgres.sql"


def build_infrastructure_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    postgres = build_postgres_driver_status(settings)
    redis = build_redis_driver_status(settings)
    cutover_blockers = sorted(
        set(
            [
                *postgres.get("runtime_cutover_blockers", []),
                *redis.get("runtime_cutover_blockers", []),
            ]
        )
    )
    return {
        "contract_version": "2026-05-17-infrastructure-drivers",
        "postgres": postgres,
        "redis": redis,
        "ready_for_runtime_cutover": not cutover_blockers,
        "cutover_blockers": cutover_blockers,
        "secret_exposed": False,
    }


def build_postgres_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    dependency = _dependency_status("psycopg")
    live_check_requested = _env_bool("JIEJING_POSTGRES_DRIVER_CHECK_LIVE", default=False)
    live_check = _postgres_live_check(settings) if live_check_requested else {"status": "not_requested"}
    runtime_cutover_blockers: list[str] = []
    if settings.database_adapter != "postgres-managed" and settings.database_engine != "postgres":
        runtime_cutover_blockers.append("postgres_adapter_not_selected")
    if not settings.database_url_configured:
        runtime_cutover_blockers.append("missing_database_url")
    if not dependency["available"]:
        runtime_cutover_blockers.append("missing_psycopg_dependency")
    if live_check_requested and live_check.get("status") != "ok":
        runtime_cutover_blockers.append("postgres_live_check_failed")
    return {
        "key": "postgres",
        "selected": settings.database_adapter == "postgres-managed" or settings.database_engine == "postgres",
        "dependency": dependency,
        "database_url_configured": settings.database_url_configured,
        "database_url_public": _redact_url(os.environ.get("JIEJING_DATABASE_URL") or ""),
        "migration_file": str(POSTGRES_MIGRATION.relative_to(ROOT)),
        "migration_file_exists": POSTGRES_MIGRATION.exists(),
        "migration_runner_implemented": True,
        "repository_runtime_switch_implemented": True,
        "live_check_requested": live_check_requested,
        "live_check": live_check,
        "runtime_cutover_blockers": runtime_cutover_blockers,
        "secret_exposed": False,
    }


def run_postgres_live_probe(settings: SaaSSettings) -> dict[str, Any]:
    """Run a redacted Postgres ``select 1`` probe for deep health checks."""

    if settings.database_engine != "postgres" and settings.database_adapter != "postgres-managed":
        return {
            "status": "not_required",
            "engine": settings.database_engine,
            "adapter": settings.database_adapter,
            "secret_exposed": False,
        }
    return _postgres_live_check(settings)


def build_redis_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    dependency = _dependency_status("redis")
    live_check_requested = _env_bool("JIEJING_REDIS_DRIVER_CHECK_LIVE", default=False)
    live_check = _redis_live_check(settings) if live_check_requested else {"status": "not_requested"}
    runtime_cutover_blockers: list[str] = []
    if settings.queue_provider == "postgres_durable":
        return {
            "key": "redis_streams",
            "selected": False,
            "replaced_by": "postgres_durable",
            "dependency": dependency,
            "queue_url_configured": False,
            "queue_url_public": "",
            "stream_name": "",
            "dead_letter_stream": "",
            "connection_probe_implemented": True,
            "worker_runtime_switch_implemented": True,
            "runtime": {"status": "skipped_postgres_durable_queue", "secret_exposed": False},
            "live_check_requested": False,
            "live_check": {"status": "not_required_postgres_durable_queue"},
            "runtime_cutover_blockers": [],
            "secret_exposed": False,
        }
    if settings.queue_provider != "redis_streams":
        runtime_cutover_blockers.append("redis_streams_provider_not_selected")
    if not settings.queue_url_configured:
        runtime_cutover_blockers.append("missing_queue_url")
    if not dependency["available"]:
        runtime_cutover_blockers.append("missing_redis_dependency")
    if live_check_requested and live_check.get("status") != "ok":
        runtime_cutover_blockers.append("redis_live_check_failed")
    runtime = redis_runtime_status(settings)
    return {
        "key": "redis_streams",
        "selected": settings.queue_provider == "redis_streams",
        "dependency": dependency,
        "queue_url_configured": settings.queue_url_configured,
        "queue_url_public": _redact_url(os.environ.get("JIEJING_QUEUE_URL") or ""),
        "stream_name": os.environ.get("JIEJING_REDIS_STREAM", "jiejing:queue"),
        "dead_letter_stream": os.environ.get("JIEJING_REDIS_DEAD_LETTER_STREAM", "jiejing:queue:dead"),
        "connection_probe_implemented": True,
        "worker_runtime_switch_implemented": True,
        "runtime": runtime,
        "live_check_requested": live_check_requested,
        "live_check": live_check,
        "runtime_cutover_blockers": runtime_cutover_blockers,
        "secret_exposed": False,
    }


def run_postgres_migration(*, database_url: str, migration_path: Path = POSTGRES_MIGRATION) -> dict[str, Any]:
    if not database_url:
        return {"status": "blocked", "blocked_by": ["missing_database_url"], "secret_exposed": False}
    if not migration_path.exists():
        return {"status": "blocked", "blocked_by": ["missing_migration_file"], "secret_exposed": False}
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_psycopg_dependency"], "secret_exposed": False}
    sql = migration_path.read_text(encoding="utf-8")
    try:
        with psycopg.connect(database_url, connect_timeout=postgres_connect_timeout_seconds()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "database_url_public": _redact_url(database_url),
            "secret_exposed": False,
        }
    return {
        "status": "ok",
        "migration_file": str(migration_path),
        "database_url_public": _redact_url(database_url),
        "secret_exposed": False,
    }


def _postgres_live_check(settings: SaaSSettings) -> dict[str, Any]:
    database_url = os.environ.get("JIEJING_DATABASE_URL") or ""
    if not database_url:
        return {"status": "blocked", "blocked_by": ["missing_database_url"], "secret_exposed": False}
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_psycopg_dependency"], "secret_exposed": False}
    try:
        with psycopg.connect(database_url, connect_timeout=postgres_connect_timeout_seconds()) as conn:
            with conn.cursor() as cursor:
                cursor.execute("select 1")
                row = cursor.fetchone()
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "database_url_public": _redact_url(database_url),
            "secret_exposed": False,
        }
    return {"status": "ok", "select_1": row[0] if row else None, "database_url_public": _redact_url(database_url), "secret_exposed": False}


def _redis_live_check(settings: SaaSSettings) -> dict[str, Any]:
    queue_url = os.environ.get("JIEJING_QUEUE_URL") or ""
    if not queue_url:
        return {"status": "blocked", "blocked_by": ["missing_queue_url"], "secret_exposed": False}
    try:
        import redis  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_redis_dependency"], "secret_exposed": False}
    try:
        client = redis.Redis.from_url(queue_url, socket_connect_timeout=5, socket_timeout=5)
        pong = client.ping()
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "queue_url_public": _redact_url(queue_url),
            "secret_exposed": False,
        }
    return {"status": "ok", "ping": bool(pong), "queue_url_public": _redact_url(queue_url), "secret_exposed": False}


def _dependency_status(module_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    return {
        "module": module_name,
        "available": spec is not None,
        "status": "available" if spec is not None else "missing_python_dependency",
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
