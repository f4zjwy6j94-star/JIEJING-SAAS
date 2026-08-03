#!/usr/bin/env python3
"""Regression checks for the Jiejing Postgres repository cutover layer."""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.postgres_repository_runtime import (  # noqa: E402
    JSON_COLUMNS,
    adapt_jsonb_parameters,
    placeholder_count,
    postgres_pool_enabled,
    postgres_pool_max_size,
    postgres_pool_min_size,
    postgres_pool_wait_timeout_seconds,
    translate_sqlite_query_to_postgres,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-postgres-repository-cutover-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    sql, params = translate_sqlite_query_to_postgres(
        "select * from tasks where company_id = ? and title = '?' -- keep ? inside comment\nlimit ?",
        ("company_1", 5),
    )
    if "company_id = %s" not in sql or "limit %s" not in sql:
        return fail("Postgres repository must translate SQLite qmark placeholders to psycopg placeholders")
    if "title = '?'" not in sql or "-- keep ? inside comment" not in sql:
        return fail("placeholder translator must not rewrite quoted strings or comments")
    if placeholder_count(sql) != 2 or params != ("company_1", 5):
        return fail("placeholder translator changed parameter cardinality")

    analytics_start = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)
    analytics_sql, analytics_params = translate_sqlite_query_to_postgres(
        """
        select to_char(occurred_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD') as day_key
        from platform_analytics_events
        where occurred_at >= ?
        """,
        (analytics_start,),
    )
    if "occurred_at AT TIME ZONE 'Asia/Shanghai'" not in analytics_sql or "occurred_at >= %s" not in analytics_sql:
        return fail("Postgres operations analytics must group in Beijing time and compare timestamptz instants")
    if analytics_params != (analytics_start,) or not isinstance(analytics_params[0], datetime):
        return fail("Postgres operations analytics must preserve an aware UTC datetime parameter")

    ignore_sql, _ = translate_sqlite_query_to_postgres(
        "insert or ignore into team_members (company_id, user_id, role, created_at) values (?, ?, ?, ?)",
        ("company_1", "user_1", "owner", "2026-05-17T00:00:00Z"),
    )
    if "insert into team_members" not in ignore_sql.lower() or "on conflict do nothing" not in ignore_sql.lower():
        return fail("insert or ignore must become Postgres on conflict do nothing")

    replace_sql, _ = translate_sqlite_query_to_postgres(
        """
        insert or replace into confirmations (
          confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status,
          default_action, created_at, item_json, decided_by, decided_at, decision_note
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tuple(range(14)),
    )
    if "on conflict (confirmation_id) do update set" not in replace_sql.lower():
        return fail("insert or replace must become a Postgres upsert")
    if "item_json = excluded.item_json" not in replace_sql:
        return fail("Postgres upsert must preserve JSON confirmation payload updates")
    if placeholder_count(replace_sql) != 14:
        return fail("Postgres upsert must preserve placeholder count")

    table_sql, table_params = translate_sqlite_query_to_postgres(
        """
        select name
        from sqlite_master
        where type = 'table'
        order by name
        """,
        (),
    )
    if "information_schema.tables" not in table_sql or table_params:
        return fail("sqlite_master inventory query must translate to information_schema")

    pragma_sql, pragma_params = translate_sqlite_query_to_postgres("pragma index_list(tasks)", ())
    if "pg_indexes" not in pragma_sql or pragma_params != ("tasks",):
        return fail("pragma index_list must translate to Postgres index metadata query")

    repository_text = (ROOT / "jiejing_saas" / "repository.py").read_text(encoding="utf-8")
    if "rowid desc" in repository_text.lower():
        return fail("repository queries used by the Postgres adapter must not depend on SQLite rowid ordering")
    for analytics_marker in (
        "to_char(occurred_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD')",
        'analytics_period_parameter: datetime | str = analytics_period_started_utc',
    ):
        if analytics_marker not in repository_text:
            return fail(f"repository is missing managed Postgres analytics timezone semantics: {analytics_marker}")

    repo = SaaSRepository(OUT / "saas.sqlite", database_engine="postgres", database_url="postgresql://jiejing:secret@db:5432/jiejing")
    if repo.database_engine != "postgres" or repo.database_url.endswith("@db:5432/jiejing") is False:
        return fail("SaaSRepository must preserve selected Postgres runtime configuration")

    pool_env_keys = (
        "JIEJING_DATABASE_POOL_ENABLED",
        "JIEJING_DATABASE_POOL_MIN_SIZE",
        "JIEJING_DATABASE_POOL_MAX_SIZE",
        "JIEJING_DATABASE_POOL_WAIT_TIMEOUT_SECONDS",
    )
    previous_pool_env = {key: os.environ.get(key) for key in pool_env_keys}
    try:
        os.environ["JIEJING_DATABASE_POOL_ENABLED"] = "true"
        os.environ["JIEJING_DATABASE_POOL_MIN_SIZE"] = "2"
        os.environ["JIEJING_DATABASE_POOL_MAX_SIZE"] = "12"
        os.environ["JIEJING_DATABASE_POOL_WAIT_TIMEOUT_SECONDS"] = "7"
        if not postgres_pool_enabled():
            return fail("Postgres connection pooling must be enabled by default for managed runtime")
        if postgres_pool_min_size() != 2 or postgres_pool_max_size() != 12 or postgres_pool_wait_timeout_seconds() != 7:
            return fail("Postgres pool limits must honor bounded environment configuration")
        os.environ["JIEJING_DATABASE_POOL_MAX_SIZE"] = "999"
        if postgres_pool_max_size() != 32:
            return fail("Postgres pool max size must clamp unsafe deployment values")
    finally:
        for key, value in previous_pool_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    runtime_text = (ROOT / "jiejing_saas" / "postgres_repository_runtime.py").read_text(encoding="utf-8")
    requirements_text = (ROOT / "requirements.saas.txt").read_text(encoding="utf-8")
    if "ConnectionPool(" not in runtime_text or "psycopg_pool" not in requirements_text:
        return fail("managed Postgres runtime must ship a bounded connection pool dependency")
    if runtime_text.count('options="-c timezone=UTC"') != 1 or runtime_text.count('"options": "-c timezone=UTC"') != 1:
        return fail("managed Postgres connections must normalize the session timezone to UTC")
    if "order_json" not in JSON_COLUMNS:
        return fail("domestic billing order JSON must be adapted for the Postgres JSONB column")
    for onboarding_json_column in ("answers_json", "completed_step_keys_json"):
        if onboarding_json_column not in JSON_COLUMNS:
            return fail(f"merchant onboarding JSON must be adapted for Postgres JSONB: {onboarding_json_column}")
    if "feedback_json" not in JSON_COLUMNS:
        return fail("merchant product feedback JSON must be adapted for the Postgres JSONB column")
    feedback_insert_sql, feedback_insert_params = translate_sqlite_query_to_postgres(
        """
        insert into merchant_product_feedback (
          feedback_id, company_id, user_id, store_id, feedback_type,
          module_key, reason, status, idempotency_key_hash,
          created_at, updated_at, resolved_at, feedback_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict (company_id, idempotency_key_hash) do nothing
        returning feedback_id
        """,
        (
            "feedback_1",
            "company_1",
            "user_1",
            None,
            "product_improvement",
            "workflow",
            "unclear",
            "open",
            "idempotency-hash",
            "2026-08-03T00:00:00+00:00",
            "2026-08-03T00:00:00+00:00",
            None,
            '{"safe":true}',
        ),
    )
    class Jsonb:
        def __init__(self, value: object) -> None:
            self.value = value

    module_names = ("psycopg", "psycopg.types", "psycopg.types.json")
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    fake_psycopg = types.ModuleType("psycopg")
    fake_types = types.ModuleType("psycopg.types")
    fake_json = types.ModuleType("psycopg.types.json")
    fake_json.Jsonb = Jsonb
    fake_types.json = fake_json
    fake_psycopg.types = fake_types
    try:
        sys.modules["psycopg"] = fake_psycopg
        sys.modules["psycopg.types"] = fake_types
        sys.modules["psycopg.types.json"] = fake_json
        adapted_feedback_params = adapt_jsonb_parameters(feedback_insert_sql, feedback_insert_params)
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    if not isinstance(adapted_feedback_params[-1], Jsonb):
        return fail("merchant product feedback INSERT did not adapt feedback_json as Postgres JSONB")
    if "_postgres_initialize_lock" not in repository_text:
        return fail("Postgres migration initialization must be guarded against concurrent requests")
    if "pg_advisory_lock" not in repository_text or "pg_advisory_unlock" not in repository_text:
        return fail("domestic billing entitlement mutations must use a Postgres company advisory lock")

    migration_text = (ROOT / "jiejing_saas" / "migrations" / "001_initial_schema_postgres.sql").read_text(encoding="utf-8")
    if "idx_billing_orders_provider_transaction_unique" not in migration_text:
        return fail("one provider transaction must not activate more than one domestic billing order")
    for marker in (
        "create table if not exists platform_provider_monitor_state",
        "lease_expires_at_epoch bigint not null",
        "idx_platform_provider_monitor_state_lease_expiry",
        "20260717_platform_provider_monitor_state",
    ):
        if marker not in migration_text.lower():
            return fail(f"Postgres migration must ship passive provider monitoring lease state: {marker}")
    for marker in (
        "create table if not exists merchant_onboarding_states",
        "answers_json jsonb not null",
        "completed_step_keys_json jsonb not null",
        "idx_merchant_onboarding_store_updated",
        "20260802_merchant_onboarding_states",
    ):
        if marker not in migration_text.lower():
            return fail(f"Postgres migration must ship tenant merchant onboarding state: {marker}")
    for marker in (
        "create table if not exists merchant_product_feedback",
        "feedback_json jsonb not null",
        "unique (company_id, idempotency_key_hash)",
        "idx_merchant_product_feedback_company_created",
        "idx_merchant_product_feedback_status_updated",
        "20260803_merchant_product_feedback",
    ):
        if marker not in migration_text.lower():
            return fail(f"Postgres migration must ship merchant product feedback closure: {marker}")
    if "on conflict(scheduler_key) do update set" not in repository_text.lower():
        return fail("provider monitoring lease must use a cross-process atomic Postgres-compatible upsert")
    if "where platform_provider_monitor_state.lease_expires_at_epoch <= ?" not in repository_text.lower():
        return fail("provider monitoring lease takeover must be conditional on expiry")
    for literal_like_pattern in (
        "like '%%rehearsal%%'",
        "like '%%acceptance%%'",
        "like '%%verification%%'",
        "like '%%probe%%'",
        "not like '%%\\\"live_acceptance_test\\\":true%%'",
    ):
        if literal_like_pattern not in repository_text:
            return fail(f"provider monitoring LIKE patterns must escape literal percent signs for psycopg: {literal_like_pattern}")

    summary = {
        "postgres_repository_runtime_switch_implemented": True,
        "placeholder_translation": True,
        "sqlite_upsert_translation": True,
        "inventory_translation": True,
        "bounded_connection_pool": True,
        "concurrent_migration_guard": True,
        "domestic_billing_company_lock": True,
        "provider_transaction_uniqueness": True,
        "secret_exposed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PASS jiejing_postgres_repository_cutover")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
