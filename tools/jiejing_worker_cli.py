#!/usr/bin/env python3
"""Standalone worker process for Jiejing SaaS queue jobs.

The API server should accept merchant requests and expose state. This worker is
the production-shaped process that consumes queued jobs in the background,
using Redis Streams when configured and the local DB queue during staging/local
validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_operations_maintenance import run_domestic_billing_maintenance  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.monitoring import ProviderMonitoringScheduler  # noqa: E402
from jiejing_saas.redis_queue_runtime import RedisStreamQueueWorker, redis_runtime_status  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.runtime_bridge import RuntimeBridge  # noqa: E402
from jiejing_saas.worker import LocalQueueWorker  # noqa: E402


DEFAULT_DB = ROOT / "output" / "jiejing-saas-backend" / "saas.sqlite"
DEFAULT_RUNTIME_DB = ROOT / "output" / "jiejing-saas-backend" / "runtime.sqlite"
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "jiejing-saas-backend"


class ProviderMonitoringBackgroundRunner:
    """Run one monitoring evaluation at a time without blocking queue polling."""

    def __init__(self, scheduler: ProviderMonitoringScheduler) -> None:
        self.scheduler = scheduler
        self.interval_seconds = max(1, int(scheduler.interval_seconds))
        self._thread: threading.Thread | None = None
        self._result: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._next_due_monotonic = 0.0
        self._closed = False

    def tick(self, *, now_monotonic: float | None = None) -> dict[str, Any]:
        current = time.monotonic() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            if self._closed:
                return {"status": "closed", "secret_exposed": False}
            if self._thread is not None and self._thread.is_alive():
                return {"status": "in_progress", "secret_exposed": False}
            if self._thread is not None:
                result = self._result or {
                    "status": "evaluation_failed",
                    "external_provider_action_triggered": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                }
                self._thread = None
                self._result = None
                return {"status": "completed", "result": result, "secret_exposed": False}
            if current < self._next_due_monotonic:
                return {"status": "not_due", "secret_exposed": False}
            self._next_due_monotonic = current + self.interval_seconds
            self._thread = threading.Thread(
                target=self._run,
                name="jiejing-provider-monitor",
                daemon=True,
            )
            self._thread.start()
            return {"status": "submitted", "secret_exposed": False}

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True

    def _run(self) -> None:
        try:
            result = self.scheduler.run_once()
        except Exception:
            result = {
                "status": "evaluation_failed",
                "external_provider_action_triggered": False,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
        with self._lock:
            self._result = result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Jiejing SaaS background worker.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--runtime-db", default=str(DEFAULT_RUNTIME_DB))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)

    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Print safe worker runtime status.")
    status.set_defaults(command="status")

    run_once = subparsers.add_parser("run-once", help="Run at most one queued job, then exit.")
    run_once.add_argument("--company-id", default=None)
    run_once.add_argument("--job-id", default=None)

    run_loop = subparsers.add_parser("run-loop", help="Continuously poll and run queued jobs.")
    run_loop.add_argument("--company-id", default=None)
    run_loop.add_argument("--job-id", default=None)
    run_loop.add_argument("--idle-sleep", type=float, default=2.0)
    run_loop.add_argument("--max-jobs", type=int, default=0, help="0 means no job-count limit.")
    run_loop.add_argument("--stop-after-seconds", type=float, default=0.0, help="0 means run until interrupted.")
    run_loop.add_argument("--json-lines", action="store_true", help="Print one JSON summary per worker attempt.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings, repository, worker = _build_worker(args)
    if args.command == "status":
        print(json.dumps(_status(settings), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run-once":
        result = worker.run_next(company_id=args.company_id, job_id=args.job_id)
        print(json.dumps(_summarize_result(result, settings=settings), ensure_ascii=False, indent=2))
        return 0 if result.get("status") != "failed" else 1
    if args.command == "run-loop":
        return _run_loop(args, settings=settings, worker=worker)
    return 2


def _build_worker(args: argparse.Namespace) -> tuple[SaaSSettings, SaaSRepository, LocalQueueWorker]:
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    settings = SaaSSettings.from_env(
        db_path=Path(args.db).resolve(),
        runtime_db_path=Path(args.runtime_db).resolve(),
        output_root=output_root,
        host=args.host,
        port=args.port,
    )
    repository = SaaSRepository(
        settings.db_path,
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repository.initialize()
    bridge = RuntimeBridge(
        runtime_db_path=settings.runtime_db_path,
        output_root=settings.output_root,
        allow_hermes_adapters=settings.allow_hermes_adapters,
    )
    if settings.queue_provider == "redis_streams":
        return settings, repository, RedisStreamQueueWorker(repository=repository, runtime_bridge=bridge, settings=settings)
    return settings, repository, LocalQueueWorker(repository=repository, runtime_bridge=bridge, settings=settings)


def _run_loop(args: argparse.Namespace, *, settings: SaaSSettings, worker: LocalQueueWorker) -> int:
    started = time.monotonic()
    maintenance_config = _domestic_billing_maintenance_config()
    next_maintenance_at = started
    provider_monitoring = ProviderMonitoringBackgroundRunner(
        ProviderMonitoringScheduler(
            repository=worker.repository,
            environment=settings.environment,
        )
    )
    attempts = 0
    processed = 0
    last: dict[str, Any] | None = None
    try:
        while True:
            if args.stop_after_seconds > 0 and time.monotonic() - started >= args.stop_after_seconds:
                break
            if args.max_jobs > 0 and processed >= args.max_jobs:
                break
            if maintenance_config["enabled"] and time.monotonic() >= next_maintenance_at:
                try:
                    maintenance = run_domestic_billing_maintenance(
                        worker.repository,
                        auto_reconcile=maintenance_config["auto_reconcile_enabled"],
                        max_companies=maintenance_config["max_companies"],
                        max_orders_per_company=maintenance_config["max_orders_per_company"],
                        max_queries_per_run=maintenance_config["max_queries_per_run"],
                    )
                except Exception:
                    maintenance = {
                        "event": "domestic_billing_maintenance",
                        "status": "failed",
                        "reason": "billing_maintenance_iteration_failed",
                        "alert_required": True,
                        "calls_external_payment_api": False,
                        "triggers_real_charge": False,
                        "triggers_real_refund": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    }
                print(json.dumps(maintenance, ensure_ascii=False), flush=True)
                next_maintenance_at = time.monotonic() + maintenance_config["interval_seconds"]
            monitoring_tick = provider_monitoring.tick()
            if monitoring_tick.get("status") == "completed":
                monitoring_result = monitoring_tick.get("result") if isinstance(monitoring_tick.get("result"), dict) else {}
                print(
                    json.dumps(
                        {"event": "provider_monitoring_evaluation", **monitoring_result},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            worker.repository.recover_stale_queue_jobs(company_id=args.company_id)
            result = worker.run_next(company_id=args.company_id, job_id=args.job_id)
            summary = _summarize_result(result, settings=settings)
            attempts += 1
            last = summary
            if args.json_lines:
                print(json.dumps(summary, ensure_ascii=False), flush=True)
            if result.get("status") == "failed":
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 1
            if result.get("status") == "idle":
                if args.job_id:
                    break
                time.sleep(max(args.idle_sleep, 0.1))
                continue
            processed += 1
    except KeyboardInterrupt:
        last = {
            "status": "interrupted",
            "queue_provider": settings.queue_provider,
            "database_engine": settings.database_engine,
            "processed_jobs": processed,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
    finally:
        provider_monitoring.shutdown()
    final = {
        "status": "completed_loop" if not last or last.get("status") != "interrupted" else "interrupted",
        "attempts": attempts,
        "processed_jobs": processed,
        "last_result": last,
        "queue_provider": settings.queue_provider,
        "database_engine": settings.database_engine,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


def _status(settings: SaaSSettings) -> dict[str, Any]:
    maintenance_config = _domestic_billing_maintenance_config()
    provider_monitoring_config = _provider_monitoring_config()
    status = {
        "product": "Jiejing SaaS",
        "process": "background_worker",
        "queue_provider": settings.queue_provider,
        "database_engine": settings.database_engine,
        "database_url_configured": settings.database_url_configured,
        "worker_runtime": (
            "redis_streams"
            if settings.queue_provider == "redis_streams"
            else "postgres_durable_queue"
            if settings.queue_provider == "postgres_durable"
            else "local_db_queue"
        ),
        "output_root": str(settings.output_root),
        "domestic_billing_maintenance": {
            **maintenance_config,
            "query_only": True,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
        },
        "provider_monitoring": {
            **provider_monitoring_config,
            "passive": True,
            "calls_business_provider": False,
            "triggers_real_charge": False,
            "real_platform_writes_enabled": False,
        },
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    if settings.queue_provider == "redis_streams":
        status["redis"] = redis_runtime_status(settings)
    return status


def _domestic_billing_maintenance_config() -> dict[str, Any]:
    return {
        "enabled": _env_bool("JIEJING_DOMESTIC_BILLING_MAINTENANCE_ENABLED", default=False),
        "auto_reconcile_enabled": _env_bool("JIEJING_DOMESTIC_BILLING_AUTO_RECONCILE_ENABLED", default=False),
        "interval_seconds": _bounded_env_int(
            "JIEJING_DOMESTIC_BILLING_MAINTENANCE_INTERVAL_SECONDS", default=300, minimum=60, maximum=3600
        ),
        "max_companies": _bounded_env_int(
            "JIEJING_DOMESTIC_BILLING_MAINTENANCE_MAX_COMPANIES", default=25, minimum=1, maximum=100
        ),
        "max_orders_per_company": _bounded_env_int(
            "JIEJING_DOMESTIC_BILLING_MAINTENANCE_MAX_ORDERS", default=10, minimum=1, maximum=10
        ),
        "max_queries_per_run": _bounded_env_int(
            "JIEJING_DOMESTIC_BILLING_MAINTENANCE_MAX_QUERIES", default=50, minimum=1, maximum=100
        ),
    }


def _provider_monitoring_config() -> dict[str, Any]:
    return {
        "enabled": _env_bool("JIEJING_PROVIDER_MONITOR_SCHEDULER_ENABLED", default=False),
        "interval_seconds": _bounded_env_int(
            "JIEJING_PROVIDER_MONITOR_INTERVAL_SECONDS", default=300, minimum=60, maximum=3600
        ),
        "reliability_window_minutes": _bounded_env_int(
            "JIEJING_PROVIDER_MONITOR_WINDOW_MINUTES", default=30, minimum=1, maximum=1440
        ),
        "cost_window_hours": _bounded_env_int(
            "JIEJING_PROVIDER_MONITOR_COST_WINDOW_HOURS", default=24, minimum=1, maximum=168
        ),
    }


def _env_bool(name: str, *, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _bounded_env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _summarize_result(result: dict[str, Any], *, settings: SaaSSettings) -> dict[str, Any]:
    task = result.get("task") if isinstance(result.get("task"), dict) else {}
    queue_job = result.get("queue_job") if isinstance(result.get("queue_job"), dict) else {}
    saved = result.get("saved") if isinstance(result.get("saved"), dict) else {}
    live_read_result = result.get("live_read_result") if isinstance(result.get("live_read_result"), dict) else {}
    return {
        "status": result.get("status"),
        "queue_provider": result.get("queue_provider") or settings.queue_provider,
        "database_engine": settings.database_engine,
        "job_id": queue_job.get("job_id") or result.get("job_id"),
        "task_id": task.get("task_id") or queue_job.get("task_id"),
        "company_id": task.get("company_id") or queue_job.get("company_id"),
        "store_id": task.get("store_id"),
        "reports": saved.get("reports", 0),
        "confirmations": saved.get("confirmations", 0),
        "data_packets": saved.get("data_packets", 0),
        "live_read_performed": bool(live_read_result.get("live_read_performed")),
        "error": result.get("error"),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
