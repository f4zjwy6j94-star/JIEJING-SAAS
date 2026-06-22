#!/usr/bin/env python3
"""Regression checks for Redis Streams queue/worker cutover wiring."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSSettings  # noqa: E402
from jiejing_saas.queue_adapter import build_queue_adapter_contract  # noqa: E402
from jiejing_saas.redis_queue_runtime import publish_redis_queue_job_if_configured, redis_runtime_status  # noqa: E402


OUT = ROOT / "output" / "jiejing-redis-worker-cutover-test"
ENV_KEYS = (
    "JIEJING_QUEUE_PROVIDER",
    "JIEJING_QUEUE_URL",
    "JIEJING_REDIS_STREAM",
    "JIEJING_REDIS_DEAD_LETTER_STREAM",
    "JIEJING_REDIS_CONSUMER_GROUP",
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
                "JIEJING_QUEUE_PROVIDER": "redis_streams",
                "JIEJING_QUEUE_URL": "redis://:super-secret-redis@redis:6379/0",
                "JIEJING_REDIS_STREAM": "jiejing:test:queue",
                "JIEJING_REDIS_DEAD_LETTER_STREAM": "jiejing:test:queue:dead",
                "JIEJING_REDIS_CONSUMER_GROUP": "jiejing-test-workers",
            }
        )
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        contract = build_queue_adapter_contract(settings)
        runtime = redis_runtime_status(settings)
        dumped = json.dumps({"contract": contract, "runtime": runtime}, ensure_ascii=False)
        if "super-secret" in dumped:
            return fail("Redis worker cutover status must redact queue URL secrets")
        if contract.get("selected_adapter", {}).get("key") != "redis_streams":
            return fail("Redis Streams adapter must be selectable")
        if contract.get("selected_adapter", {}).get("driver_implemented") is not True:
            return fail("Redis Streams adapter must be marked as implemented")
        if "cloud_queue_driver_not_implemented" in contract.get("production_blockers", []):
            return fail("Redis Streams should no longer be blocked by missing driver implementation")
        if runtime.get("redis_stream_worker_implemented") is not True:
            return fail("Redis stream worker runtime should be implemented")
        if runtime.get("redis_dispatch_on_enqueue_implemented") is not True:
            return fail("Redis queue dispatch on enqueue should be implemented")
    finally:
        _restore_env(previous)

    previous_local = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        os.environ["JIEJING_QUEUE_PROVIDER"] = "local_worker"
        os.environ.pop("JIEJING_QUEUE_URL", None)
        skipped = publish_redis_queue_job_if_configured(
            {"job_id": "job_1", "company_id": "company_1", "task_id": "task_1", "job": {"kind": "provider_job"}}
        )
        if skipped.get("required") is not False:
            return fail("Redis dispatch should be a no-op when local queue provider is selected")
    finally:
        _restore_env(previous_local)

    summary = {
        "redis_stream_worker_runtime_switch_implemented": True,
        "redis_dispatch_on_enqueue_implemented": True,
        "secret_exposed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PASS jiejing_redis_worker_cutover")
    return 0


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
