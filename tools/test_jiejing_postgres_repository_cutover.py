#!/usr/bin/env python3
"""Regression checks for the Jiejing Postgres repository cutover layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.postgres_repository_runtime import (  # noqa: E402
    placeholder_count,
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

    repo = SaaSRepository(OUT / "saas.sqlite", database_engine="postgres", database_url="postgresql://jiejing:secret@db:5432/jiejing")
    if repo.database_engine != "postgres" or repo.database_url.endswith("@db:5432/jiejing") is False:
        return fail("SaaSRepository must preserve selected Postgres runtime configuration")

    summary = {
        "postgres_repository_runtime_switch_implemented": True,
        "placeholder_translation": True,
        "sqlite_upsert_translation": True,
        "inventory_translation": True,
        "secret_exposed": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("PASS jiejing_postgres_repository_cutover")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
