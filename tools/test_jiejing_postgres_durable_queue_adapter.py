#!/usr/bin/env python3
"""Regression checks for the Postgres durable queue adapter."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.infrastructure_drivers import build_infrastructure_driver_status  # noqa: E402
from jiejing_saas.queue_adapter import build_queue_adapter_contract  # noqa: E402
from jiejing_saas.queue_plan import build_queue_plan  # noqa: E402
from jiejing_saas.readiness import _infrastructure_driver_item, _queue_adapter_item, _queue_item, _queue_worker_plan_item  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-postgres-durable-queue-test"
ENV_KEYS = (
    "JIEJING_SAAS_ENV",
    "JIEJING_DATABASE_ENGINE",
    "JIEJING_DATABASE_ADAPTER",
    "JIEJING_DATABASE_URL",
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_REDIS_STREAM",
    "JIEJING_REDIS_DEAD_LETTER_STREAM",
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
                "JIEJING_DATABASE_URL": "postgresql://jiejing:secret@postgres:5432/jiejing",
                "JIEJING_QUEUE_PROVIDER": "postgres_durable",
            }
        )
        for key in ("JIEJING_QUEUE_URL", "JIEJING_REDIS_STREAM", "JIEJING_REDIS_DEAD_LETTER_STREAM"):
            os.environ.pop(key, None)
        settings = _settings()
        repo = SaaSRepository(OUT / "queue.sqlite", database_engine="sqlite")
        repo.initialize()

        contract = build_queue_adapter_contract(settings)
        if contract.get("selected_adapter", {}).get("key") != "postgres_durable":
            return fail(f"Postgres durable adapter should be selected: {contract}")
        if contract.get("production_blockers"):
            return fail(f"Postgres durable queue should not require Redis queue URL: {contract.get('production_blockers')}")

        plan = build_queue_plan(settings, repo)
        if plan.get("postgres_durable_queue_ready") is not True:
            return fail(f"queue plan should mark postgres durable queue ready: {plan}")
        if plan.get("production_blockers"):
            return fail(f"Postgres durable queue plan should not keep production blockers: {plan.get('production_blockers')}")

        queue_item = _queue_item(settings).to_dict()
        if queue_item.get("status") != "postgres_durable_queue_ready" or queue_item.get("severity") == "blocker":
            return fail(f"readiness queue item should accept Postgres durable queue: {queue_item}")
        adapter_item = _queue_adapter_item(settings).to_dict()
        if adapter_item.get("status") != "managed_queue_live":
            return fail(f"readiness queue adapter item should be live: {adapter_item}")
        worker_item = _queue_worker_plan_item(settings, repo).to_dict()
        if worker_item.get("status") != "ready":
            return fail(f"readiness queue worker plan should be ready: {worker_item}")

        infra = build_infrastructure_driver_status(settings)
        if infra.get("redis", {}).get("replaced_by") != "postgres_durable":
            return fail(f"infrastructure status should treat Redis as replaced by Postgres durable queue: {infra}")
        if "redis_streams_provider_not_selected" in infra.get("cutover_blockers", []):
            return fail(f"Postgres durable queue should not keep Redis provider blocker: {infra}")
        infra_item = _infrastructure_driver_item(settings).to_dict()
        if "redis" in str(infra_item.get("next_action", "")).lower() and "psycopg" not in infra.get("cutover_blockers", []):
            return fail(f"infrastructure readiness should not ask for Redis when Postgres durable queue is selected: {infra_item}")

        os.environ["JIEJING_DATABASE_ENGINE"] = "sqlite"
        sqlite_settings = _settings()
        sqlite_contract = build_queue_adapter_contract(sqlite_settings)
        if "postgres_durable_queue_requires_postgres" not in sqlite_contract.get("production_blockers", []):
            return fail(f"Postgres durable queue must require Postgres engine: {sqlite_contract}")
    finally:
        _restore_env(previous)

    print("PASS jiejing_postgres_durable_queue_adapter")
    return 0


def _settings() -> SaaSSettings:
    return SaaSSettings.from_env(
        db_path=OUT / "saas.sqlite",
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
