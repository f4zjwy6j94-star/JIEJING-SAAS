#!/usr/bin/env python3
"""Regression checks for Jiejing Postgres/Redis infrastructure driver status."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSSettings  # noqa: E402
from jiejing_saas.infrastructure_drivers import build_infrastructure_driver_status  # noqa: E402


OUT = ROOT / "output" / "jiejing-infrastructure-drivers-test"


ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_DATABASE_ENGINE",
    "JIEJING_DATABASE_ADAPTER",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_POSTGRES_DRIVER_CHECK_LIVE",
    "JIEJING_REDIS_DRIVER_CHECK_LIVE",
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_DATABASE_ENGINE": "postgres",
                "JIEJING_DATABASE_ADAPTER": "postgres-managed",
                "JIEJING_DATABASE_URL": "postgresql://jiejing:super-secret-password@postgres:5432/jiejing?sslmode=disable",
                "JIEJING_QUEUE_PROVIDER": "redis_streams",
                "JIEJING_QUEUE_URL": "redis://:super-secret-redis@redis:6379/0",
                "JIEJING_POSTGRES_DRIVER_CHECK_LIVE": "false",
                "JIEJING_REDIS_DRIVER_CHECK_LIVE": "false",
            }
        )
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        status = build_infrastructure_driver_status(settings)
    finally:
        _restore_env(previous)

    dumped = json.dumps(status, ensure_ascii=False)
    if "super-secret" in dumped:
        return fail("infrastructure driver status must redact database and queue URL secrets")
    if status.get("ready_for_runtime_cutover") is not False:
        return fail("driver status must not claim runtime cutover is ready without installed deps and live checks")
    if status.get("secret_exposed") is not False:
        return fail("driver status must not expose secrets")

    postgres = status.get("postgres", {})
    redis = status.get("redis", {})
    if postgres.get("selected") is not True:
        return fail("Postgres driver status should recognize selected postgres-managed adapter")
    if postgres.get("migration_runner_implemented") is not True:
        return fail("Postgres migration runner should be represented")
    if postgres.get("repository_runtime_switch_implemented") is not True:
        return fail("Postgres repository runtime switch should be implemented")
    if "saas_repository_runtime_switch_pending" in postgres.get("runtime_cutover_blockers", []):
        return fail("Postgres status should no longer expose repository runtime switch blocker")
    if "jiejing:***@postgres:5432" not in postgres.get("database_url_public", ""):
        return fail("Postgres public URL should preserve user/host but redact password")

    if redis.get("selected") is not True:
        return fail("Redis driver status should recognize selected redis_streams provider")
    if redis.get("connection_probe_implemented") is not True:
        return fail("Redis connection probe should be represented")
    if redis.get("worker_runtime_switch_implemented") is not True:
        return fail("Redis worker runtime switch should be implemented")
    if "distributed_worker_runtime_switch_pending" in redis.get("runtime_cutover_blockers", []):
        return fail("Redis status should no longer expose distributed worker runtime switch blocker")
    if redis.get("runtime", {}).get("redis_dispatch_on_enqueue_implemented") is not True:
        return fail("Redis status should expose dispatch-on-enqueue implementation")
    if "redis:6379/0" not in redis.get("queue_url_public", ""):
        return fail("Redis public URL should preserve host/path")
    if "super-secret" in redis.get("queue_url_public", ""):
        return fail("Redis public URL should redact password")

    print(json.dumps(status, ensure_ascii=False, indent=2))
    print("PASS jiejing_infrastructure_drivers")
    return 0


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
