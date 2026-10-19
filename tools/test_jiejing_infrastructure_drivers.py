#!/usr/bin/env python3
"""Regression checks for Jiejing Postgres/Redis infrastructure driver status."""

from __future__ import annotations

import json
import io
import gc
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSSettings  # noqa: E402
from jiejing_saas.infrastructure_drivers import POSTGRES_MIGRATION_MANIFEST, build_infrastructure_driver_status  # noqa: E402
import jiejing_infrastructure_stage_gate as stage_gate  # noqa: E402


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
    migration_error = _check_stage_gate_migrations()
    if migration_error:
        return fail(migration_error)
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


def _check_stage_gate_migrations() -> str:
    # Exercise the published gate report, not its private migration helper.
    def run_gate(missing_file: Path | None = None) -> tuple[int, dict]:
        exists = Path.exists
        with tempfile.TemporaryDirectory(prefix="jiejing-infra-manifest-", dir=OUT) as directory:
            output = Path(directory)
            # Fault only the filesystem boundary; no migration is actually removed.
            with patch.object(stage_gate, "OUT", output), patch.dict(os.environ, {}, clear=True), \
                    patch.object(Path, "exists", lambda path: False if path == missing_file else exists(path)), \
                    redirect_stdout(io.StringIO()):
                try:
                    exit_code = stage_gate.main()
                finally:
                    gc.collect()  # Release fixture connections before Windows removes the owned directory.
            report = json.loads((output / "latest.json").read_text(encoding="utf-8"))
        return exit_code, report

    exit_code, report = run_gate()
    migration = next(item for item in report["checks"] if item["key"] == "postgres_migration_shape")
    expected_paths = [str(spec.path.relative_to(ROOT)) for spec in POSTGRES_MIGRATION_MANIFEST]
    support_migration = ROOT / "jiejing_saas" / "migrations" / "006_support_conversations_postgres.sql"
    if str(support_migration.relative_to(ROOT)) not in expected_paths:
        return "support migration 006 must be reachable through the normal reviewed deployment manifest"
    if exit_code != 0 or migration["pass"] is not True:
        return "infrastructure stage gate must accept every checked-in canonical migration"
    if migration["migration_paths"] != expected_paths:
        return "infrastructure stage gate must cover the complete canonical migration manifest in order"
    if migration["missing_migration_files"] or migration["missing_tables"] or migration["missing_indexes"]:
        return "complete migration files must preserve every critical table and index check"
    missing = ROOT / "jiejing_saas" / "migrations" / "005_listing_draft_edit_checkpoints_postgres.sql"
    exit_code, report = run_gate(missing)
    migration = next(item for item in report["checks"] if item["key"] == "postgres_migration_shape")
    if exit_code != 1 or report["status"] != "failed" or migration["pass"] is not False:
        return "infrastructure stage gate must fail closed when migration 005 is unavailable"
    if migration["migration_paths"] != expected_paths or migration["missing_migration_files"] != [str(missing.relative_to(ROOT))]:
        return "missing migration 005 must remain in the manifest and be reported as unavailable"
    if set(migration["missing_tables"]) != {"listing_draft_edit_heads", "listing_draft_edit_revisions"}:
        return "missing migration 005 must still fail the critical Listing table checks"
    exit_code, report = run_gate(support_migration)
    migration = next(item for item in report["checks"] if item["key"] == "postgres_migration_shape")
    if exit_code != 1 or migration["pass"] is not False:
        return "infrastructure stage gate must fail closed when support migration 006 is unavailable"
    if set(migration["missing_tables"]) != {"support_messages_v1", "support_sync_v1", "support_drafts_v1", "support_send_intents_v1"}:
        return "missing support migration must fail all four support table checks"
    print("PASS infrastructure_stage_gate_manifest_regressions 3/3")
    return ""


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
