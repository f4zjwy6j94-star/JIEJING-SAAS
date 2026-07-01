"""Postgres runtime adapter for the Jiejing SaaS repository.

The current repository was born as a SQLite MVP. This module provides the
production cutover layer: it lets the existing repository call sites keep their
small DB-API shape while the selected runtime uses psycopg, the prepared
Postgres migration, Postgres placeholders, JSONB adapters, and Postgres index
inspection.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Sequence


JSON_COLUMNS = {
    "audit_json",
    "billing_event_json",
    "invite_json",
    "item_json",
    "job_json",
    "media_job_json",
    "metadata_json",
    "output_json",
    "packet_json",
    "report_json",
    "request_json",
    "result_json",
    "scopes_json",
    "step_json",
    "subscription_json",
    "store_json",
    "input_json",
    "memory_json",
    "command_json",
    "tags_json",
}


POSTGRES_INDEX_LIST_SQL = """
select
  i.indexname as name,
  case when ix.indisunique then 1 else 0 end as unique,
  'postgres' as origin,
  case when ix.indpred is not null then 1 else 0 end as partial
from pg_indexes i
join pg_class t on t.relname = i.tablename
join pg_class c on c.relname = i.indexname
join pg_index ix on ix.indexrelid = c.oid and ix.indrelid = t.oid
where i.schemaname = 'public' and i.tablename = %s
order by i.indexname
"""


POSTGRES_INDEX_INFO_SQL = """
select a.attname as name
from pg_class c
join pg_index ix on ix.indexrelid = c.oid
join pg_class t on t.oid = ix.indrelid
join pg_attribute a on a.attrelid = t.oid and a.attnum = any(ix.indkey)
where c.relname = %s
order by array_position(ix.indkey, a.attnum)
"""


POSTGRES_TABLE_NAMES_SQL = """
select table_name as name
from information_schema.tables
where table_schema = 'public'
  and table_type = 'BASE TABLE'
order by table_name
"""


def postgres_connect_timeout_seconds() -> int:
    raw = os.environ.get("JIEJING_DATABASE_CONNECT_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 3
    try:
        value = int(raw)
    except ValueError:
        return 3
    return min(max(value, 1), 15)


def connect_postgres_repository(database_url: str) -> PostgresConnectionAdapter:
    if not database_url:
        raise RuntimeError("Postgres repository selected but JIEJING_DATABASE_URL is not configured.")
    try:
        import psycopg  # type: ignore[import-not-found]
        from psycopg.rows import dict_row  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on deployment image
        raise RuntimeError("Postgres repository selected but psycopg is not installed.") from exc

    raw = psycopg.connect(database_url, connect_timeout=postgres_connect_timeout_seconds(), row_factory=dict_row)
    return PostgresConnectionAdapter(raw)


class PostgresConnectionAdapter:
    """Small DB-API compatibility layer used by ``SaaSRepository``."""

    driver_name = "postgres"

    def __init__(self, raw_connection: Any) -> None:
        self._conn = raw_connection

    def __enter__(self) -> "PostgresConnectionAdapter":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._conn.__exit__(exc_type, exc, tb)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> "PostgresCursorAdapter":
        translated, translated_params = translate_sqlite_query_to_postgres(sql, params or ())
        adapted_params = adapt_jsonb_parameters(translated, translated_params)
        cursor = self._conn.cursor()
        cursor.execute(translated, adapted_params)
        return PostgresCursorAdapter(cursor)

    def executescript(self, sql: str) -> "PostgresCursorAdapter":
        cursor = self._conn.cursor()
        cursor.execute(sql)
        return PostgresCursorAdapter(cursor)


class PostgresCursorAdapter:
    def __init__(self, raw_cursor: Any) -> None:
        self._cursor = raw_cursor

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", -1))

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        rows = self._cursor.fetchall()
        return list(rows or [])


def translate_sqlite_query_to_postgres(sql: str, params: Sequence[Any] = ()) -> tuple[str, tuple[Any, ...]]:
    """Translate the repository's SQLite-flavoured SQL into psycopg SQL."""

    stripped = sql.strip()
    pragma_index_list = _parse_pragma(stripped, "index_list")
    if pragma_index_list:
        return POSTGRES_INDEX_LIST_SQL, (pragma_index_list,)
    pragma_index_info = _parse_pragma(stripped, "index_info")
    if pragma_index_info:
        return POSTGRES_INDEX_INFO_SQL, (pragma_index_info,)
    if "sqlite_master" in stripped.lower():
        return POSTGRES_TABLE_NAMES_SQL, ()

    rewritten = _rewrite_insert_or_replace(stripped)
    rewritten = _rewrite_insert_or_ignore(rewritten)
    rewritten = _replace_qmark_placeholders(rewritten)
    return rewritten, tuple(params)


def adapt_jsonb_parameters(sql: str, params: Sequence[Any]) -> tuple[Any, ...]:
    if not params:
        return tuple()
    json_param_indexes = _json_parameter_indexes(sql)
    if not json_param_indexes:
        return tuple(params)

    try:
        from psycopg.types.json import Jsonb  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - only happens outside deployment image
        return tuple(params)

    adapted = list(params)
    for index in json_param_indexes:
        if index >= len(adapted):
            continue
        adapted[index] = Jsonb(_json_value(adapted[index]))
    return tuple(adapted)


def postgres_unique_error_classes() -> tuple[type[BaseException], ...]:
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return tuple()
    classes: list[type[BaseException]] = []
    for dotted in ("errors.UniqueViolation", "IntegrityError"):
        current: Any = psycopg
        try:
            for part in dotted.split("."):
                current = getattr(current, part)
        except AttributeError:
            continue
        if isinstance(current, type) and issubclass(current, BaseException):
            classes.append(current)
    return tuple(classes)


def _rewrite_insert_or_ignore(sql: str) -> str:
    rewritten, count = re.subn(r"\binsert\s+or\s+ignore\s+into\b", "insert into", sql, flags=re.IGNORECASE)
    if count and "on conflict" not in rewritten.lower():
        rewritten = f"{rewritten.rstrip().rstrip(';')} on conflict do nothing"
    return rewritten


def _rewrite_insert_or_replace(sql: str) -> str:
    match = re.match(
        r"insert\s+or\s+replace\s+into\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\((.*?)\)\s*values\s*\((.*?)\)\s*;?\s*$",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql
    table = match.group(1)
    columns = [item.strip() for item in match.group(2).replace("\n", " ").split(",") if item.strip()]
    values = match.group(3)
    if not columns:
        return sql
    conflict_column = columns[0]
    update_columns = [column for column in columns[1:] if column != conflict_column]
    assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
    return (
        f"insert into {table} ({', '.join(columns)}) values ({values}) "
        f"on conflict ({conflict_column}) do update set {assignments}"
    )


def _replace_qmark_placeholders(sql: str) -> str:
    pieces: list[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(sql):
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < len(sql) else ""
        if in_line_comment:
            pieces.append(char)
            if char == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            pieces.append(char)
            if char == "*" and nxt == "/":
                pieces.append(nxt)
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue
        if not in_single and not in_double and char == "-" and nxt == "-":
            pieces.append(char)
            pieces.append(nxt)
            in_line_comment = True
            index += 2
            continue
        if not in_single and not in_double and char == "/" and nxt == "*":
            pieces.append(char)
            pieces.append(nxt)
            in_block_comment = True
            index += 2
            continue
        if char == "'" and not in_double:
            pieces.append(char)
            if in_single and nxt == "'":
                pieces.append(nxt)
                index += 2
                continue
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            pieces.append(char)
            in_double = not in_double
            index += 1
            continue
        if char == "?" and not in_single and not in_double:
            pieces.append("%s")
        else:
            pieces.append(char)
        index += 1
    return "".join(pieces)


def _json_parameter_indexes(sql: str) -> set[int]:
    indexes: set[int] = set()
    indexes.update(_insert_json_parameter_indexes(sql))
    indexes.update(_update_json_parameter_indexes(sql))
    return indexes


def _insert_json_parameter_indexes(sql: str) -> set[int]:
    match = re.search(
        r"insert\s+into\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\((.*?)\)\s*values\s*\((.*?)\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return set()
    columns = [item.strip().lower() for item in match.group(1).replace("\n", " ").split(",") if item.strip()]
    return {index for index, column in enumerate(columns) if column in JSON_COLUMNS}


def _update_json_parameter_indexes(sql: str) -> set[int]:
    match = re.search(r"\bset\b(.*?)(?:\bwhere\b|$)", sql, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return set()
    assignments = _split_assignments(match.group(1))
    indexes: set[int] = set()
    parameter_index = 0
    for assignment in assignments:
        if "%s" not in assignment:
            continue
        column = assignment.split("=", 1)[0].strip().lower()
        placeholder_count = assignment.count("%s")
        if column in JSON_COLUMNS:
            indexes.add(parameter_index)
        parameter_index += placeholder_count
    return indexes


def _split_assignments(value: str) -> list[str]:
    assignments: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            assignments.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        assignments.append(tail)
    return assignments


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_pragma(sql: str, name: str) -> str | None:
    match = re.match(rf"pragma\s+{name}\(([^)]+)\)", sql, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().strip("'\"")


def placeholder_count(sql: str) -> int:
    return sql.count("%s")


def json_columns() -> Iterable[str]:
    return tuple(sorted(JSON_COLUMNS))
