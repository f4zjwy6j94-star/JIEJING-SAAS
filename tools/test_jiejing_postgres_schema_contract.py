#!/usr/bin/env python3
"""Red-light contracts for the versioned Jiejing PostgreSQL schema boundary."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSSettings  # noqa: E402
from jiejing_saas.infrastructure_drivers import (  # noqa: E402
    run_postgres_live_probe,
    run_postgres_migration,
)


INITIAL_MIGRATION = ROOT / "jiejing_saas" / "migrations" / "001_initial_schema_postgres.sql"
BUCKET_MIGRATION = ROOT / "jiejing_saas" / "migrations" / "002_media_credit_buckets_postgres.sql"
INITIAL_MIGRATION_CANONICAL_SHA256 = "d76293f426d20cdcc0a2667284900c8cb91606f26e464ff1a4e1b96e409444f6"
BUCKET_MIGRATION_ID = "20260823_002_media_credit_buckets_postgres"
BUCKET_MIGRATION_CHECKSUM = "jiejing-media-credit-buckets-postgres-v20260823"
DATABASE_URL = "postgresql://jiejing:red-light-secret@postgres:5432/jiejing"
# Signed int64 from sha256("jiejing-postgres-schema-migration-v1")[:8].
POSTGRES_MIGRATION_ADVISORY_LOCK_KEY = -1280677561506917264
SESSION_ADVISORY_LOCK_SQL = re.compile(
    r"^\s*select\s+(?:pg_catalog\.)?pg_advisory_lock\s*\(",
    flags=re.IGNORECASE,
)
TRANSACTION_ADVISORY_LOCK_SQL = re.compile(
    r"^\s*select\s+(?:pg_catalog\.)?pg_advisory_xact_lock\s*\(",
    flags=re.IGNORECASE,
)
SESSION_ADVISORY_UNLOCK_SQL = re.compile(
    r"^\s*select\s+(?:pg_catalog\.)?pg_advisory_unlock\s*\(",
    flags=re.IGNORECASE,
)
AdvisoryLockKey = tuple[int, ...]


def _advisory_lock_key(sql: str, params: tuple[Any, ...]) -> AdvisoryLockKey | None:
    values: tuple[Any, ...]
    if params:
        values = params
    else:
        match = re.search(
            r"pg_advisory_(?:lock|unlock|xact_lock)\s*\(([^)]*)\)",
            sql,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        values = tuple(part.strip() for part in match.group(1).split(","))
    if len(values) not in {1, 2}:
        return None
    parsed: list[int] = []
    for value in values:
        token = re.sub(r"::\s*(?:bigint|integer|int8|int4)\s*$", "", str(value).strip(), flags=re.IGNORECASE)
        if not re.fullmatch(r"[+-]?\d+", token):
            return None
        parsed.append(int(token))
    return tuple(parsed)


class _FakePostgresState:
    def __init__(
        self,
        *,
        relations: set[str] | None = None,
        migration_checksums: dict[str, str] | None = None,
        simulate_migration_work: bool = False,
    ) -> None:
        self.relations = set(relations or set())
        self.migration_checksums = dict(migration_checksums or {})
        self.simulate_migration_work = simulate_migration_work
        self.session_advisory_locks: dict[AdvisoryLockKey, threading.Lock] = {}
        self.state_lock = threading.Lock()
        self.advisory_lock_calls = 0
        self.advisory_unlock_calls = 0
        self.active_migration_executions = 0
        self.max_concurrent_migration_executions = 0
        self.migration_execution_count = 0
        self.executed_sql: list[str] = []
        self.transaction_advisory_lock_calls = 0
        self.advisory_unlock_sql_calls = 0
        self.advisory_lock_keys: list[AdvisoryLockKey] = []
        self.transaction_advisory_lock_keys: list[AdvisoryLockKey | None] = []
        self.advisory_unlock_keys: list[AdvisoryLockKey | None] = []
        self.successful_advisory_unlock_keys: list[AdvisoryLockKey] = []

    def session_lock_for(self, key: AdvisoryLockKey) -> threading.Lock:
        with self.state_lock:
            lock = self.session_advisory_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self.session_advisory_locks[key] = lock
            return lock


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection
        self.state = connection.state
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> "_FakeCursor":
        normalized = " ".join(str(sql).lower().split())
        safe_params = tuple(params or ())
        with self.state.state_lock:
            self.state.executed_sql.append(normalized)

        if TRANSACTION_ADVISORY_LOCK_SQL.search(normalized):
            advisory_key = _advisory_lock_key(normalized, safe_params)
            with self.state.state_lock:
                self.state.transaction_advisory_lock_calls += 1
                self.state.transaction_advisory_lock_keys.append(advisory_key)
            self._rows = [(True,)]
            return self

        if SESSION_ADVISORY_LOCK_SQL.search(normalized):
            advisory_key = _advisory_lock_key(normalized, safe_params)
            if advisory_key is None:
                self._rows = [(False,)]
                return self
            self.state.session_lock_for(advisory_key).acquire()
            self.connection.held_advisory_lock_keys.add(advisory_key)
            with self.state.state_lock:
                self.state.advisory_lock_calls += 1
                self.state.advisory_lock_keys.append(advisory_key)
            self._rows = [(True,)]
            return self

        if SESSION_ADVISORY_UNLOCK_SQL.search(normalized):
            advisory_key = _advisory_lock_key(normalized, safe_params)
            released = False
            if advisory_key is not None and advisory_key in self.connection.held_advisory_lock_keys:
                self.state.session_lock_for(advisory_key).release()
                self.connection.held_advisory_lock_keys.remove(advisory_key)
                released = True
            with self.state.state_lock:
                self.state.advisory_unlock_sql_calls += 1
                self.state.advisory_unlock_keys.append(advisory_key)
                if released:
                    self.state.advisory_unlock_calls += 1
                    self.state.successful_advisory_unlock_keys.append(advisory_key)
            self._rows = [(released,)]
            return self

        if normalized == "select 1":
            self._rows = [(1,)]
            return self

        if normalized.startswith("select") and "schema_migrations" in normalized:
            rows = sorted(self.state.migration_checksums.items())
            if safe_params and isinstance(safe_params[0], str):
                rows = [item for item in rows if item[0] == safe_params[0]]
            projection = normalized.split("from schema_migrations", 1)[0]
            if re.search(r"\bselect\s+checksum\b", projection):
                self._rows = [(checksum,) for _migration_id, checksum in rows]
            else:
                self._rows = [(migration_id, checksum) for migration_id, checksum in rows]
            return self

        if normalized.startswith("select") and "to_regclass" in normalized:
            relation = str(safe_params[0]) if safe_params else _to_regclass_literal(normalized)
            relation = relation.rsplit(".", 1)[-1]
            self._rows = [(f"public.{relation}" if relation in self.state.relations else None,)]
            return self

        if normalized.startswith("select") and (
            "information_schema.tables" in normalized or "from pg_class" in normalized
        ):
            self._rows = [(name,) for name in sorted(self.state.relations)]
            return self

        if "create table" in normalized:
            self._record_migration_execution(sql)
        self._apply_migration_record(sql)
        self._rows = []
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def _record_migration_execution(self, sql: str) -> None:
        with self.state.state_lock:
            self.state.active_migration_executions += 1
            self.state.max_concurrent_migration_executions = max(
                self.state.max_concurrent_migration_executions,
                self.state.active_migration_executions,
            )
            self.state.migration_execution_count += 1
        if self.state.simulate_migration_work:
            time.sleep(0.1)
        with self.state.state_lock:
            self.state.active_migration_executions -= 1

    def _apply_migration_record(self, sql: str) -> None:
        match = re.search(
            r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
            str(sql),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            with self.state.state_lock:
                self.state.migration_checksums.setdefault(match.group(1), match.group(2))


class _FakeConnection:
    def __init__(self, state: _FakePostgresState) -> None:
        self.state = state
        self.held_advisory_lock_keys: set[AdvisoryLockKey] = set()

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for advisory_key in tuple(self.held_advisory_lock_keys):
            self.state.session_lock_for(advisory_key).release()
            self.held_advisory_lock_keys.remove(advisory_key)
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


@contextmanager
def _fake_psycopg(state: _FakePostgresState) -> Iterator[None]:
    previous = sys.modules.get("psycopg")
    module = types.ModuleType("psycopg")
    module.connect = lambda *_args, **_kwargs: _FakeConnection(state)  # type: ignore[attr-defined]
    sys.modules["psycopg"] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = previous


@contextmanager
def _postgres_settings() -> Iterator[SaaSSettings]:
    keys = (
        "JIEJING_SAAS_ENV",
        "JIEJING_DATABASE_ENGINE",
        "JIEJING_DATABASE_ADAPTER",
        "JIEJING_DATABASE_URL",
    )
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "production",
                "JIEJING_DATABASE_ENGINE": "postgres",
                "JIEJING_DATABASE_ADAPTER": "postgres-managed",
                "JIEJING_DATABASE_URL": DATABASE_URL,
            }
        )
        with tempfile.TemporaryDirectory(prefix="jiejing-schema-contract-") as temp_dir:
            root = Path(temp_dir)
            yield SaaSSettings.from_env(
                db_path=root / "saas.sqlite",
                runtime_db_path=root / "runtime.sqlite",
                output_root=root / "output",
                host="127.0.0.1",
                port=8788,
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _initial_relations_and_migrations() -> tuple[set[str], dict[str, str]]:
    sql = INITIAL_MIGRATION.read_text(encoding="utf-8")
    relations = set(
        re.findall(r"create\s+table\s+if\s+not\s+exists\s+([a-z_]+)", sql, flags=re.IGNORECASE)
    )
    migrations = dict(
        re.findall(
            r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    return relations, migrations


def _to_regclass_literal(sql: str) -> str:
    match = re.search(r"to_regclass\(\s*'([^']+)'\s*\)", sql, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _canonical_text_sha256(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _create_table_body(sql: str, table_name: str) -> str:
    match = re.search(
        rf"create\s+table\s+if\s+not\s+exists\s+{re.escape(table_name)}\s*\((.*?)\)\s*;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


class PostgresSchemaContractRedLightTests(unittest.TestCase):
    def test_002_is_an_independent_immutable_media_credit_bucket_migration(self) -> None:
        self.assertEqual(
            INITIAL_MIGRATION_CANONICAL_SHA256,
            _canonical_text_sha256(INITIAL_MIGRATION),
            "published migration 001 changed; production schema changes must be additive migrations",
        )
        initial_sql = INITIAL_MIGRATION.read_text(encoding="utf-8")
        self.assertNotIn(
            "media_credit_buckets",
            initial_sql.lower(),
            "media_credit_buckets must be introduced by additive migration 002, never by editing published 001",
        )
        self.assertTrue(BUCKET_MIGRATION.is_file(), "independent PostgreSQL 002 media-credit migration is missing")
        migration_sql = BUCKET_MIGRATION.read_text(encoding="utf-8")
        self.assertRegex(migration_sql, r"(?is)^\s*begin\s*;")
        self.assertRegex(migration_sql, r"(?is)commit\s*;\s*$")

        table_body = _create_table_body(migration_sql, "media_credit_buckets")
        self.assertTrue(table_body, "002 must create media_credit_buckets with an explicit table contract")
        column_contracts = {
            "bucket_id": r"\bbucket_id\s+text\s+primary\s+key\b",
            "company_id": r"\bcompany_id\s+text\s+not\s+null\s+references\s+companies\s*\(\s*company_id\s*\)",
            "source_type": r"\bsource_type\s+text\s+not\s+null\b",
            "source_reference_id": r"\bsource_reference_id\s+text\s+not\s+null\b",
            "granted_points": r"\bgranted_points\s+integer\s+not\s+null\b",
            "remaining_points": r"\bremaining_points\s+integer\s+not\s+null\b",
            "reserved_points": r"\breserved_points\s+integer\s+not\s+null\b",
            "expires_at": r"\bexpires_at\s+timestamptz\b",
            "status": r"\bstatus\s+text\s+not\s+null\b",
            "created_at": r"\bcreated_at\s+timestamptz\s+not\s+null\b",
            "updated_at": r"\bupdated_at\s+timestamptz\s+not\s+null\b",
            "bucket_json": r"\bbucket_json\s+jsonb\s+not\s+null\b",
        }
        for field, pattern in column_contracts.items():
            self.assertRegex(table_body, pattern, f"002 migration is missing field contract: {field}")
        self.assertRegex(
            table_body,
            r"(?is)\bunique\s*\(\s*company_id\s*,\s*source_type\s*,\s*source_reference_id\s*\)",
        )
        self.assertRegex(
            migration_sql,
            r"(?is)create\s+index\s+if\s+not\s+exists\s+idx_media_credit_buckets_company_status\s+"
            r"on\s+media_credit_buckets\s*\(\s*company_id\s*,\s*status\s*,\s*expires_at\s*\)",
        )
        migration_records = dict(
            re.findall(
                r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
                migration_sql,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        self.assertEqual(BUCKET_MIGRATION_CHECKSUM, migration_records.get(BUCKET_MIGRATION_ID))
        self.assertRegex(migration_sql, r"(?is)on\s+conflict\s*\(\s*migration_id\s*\)\s+do\s+nothing")

    def test_live_probe_blocks_and_names_missing_required_relation(self) -> None:
        relations, migrations = _initial_relations_and_migrations()
        migrations[BUCKET_MIGRATION_ID] = BUCKET_MIGRATION_CHECKSUM
        state = _FakePostgresState(relations=relations, migration_checksums=migrations)
        with _postgres_settings() as settings, _fake_psycopg(state):
            result = run_postgres_live_probe(settings)

        self.assertEqual("blocked", result.get("status"))
        self.assertIn("postgres_schema_missing_relations", result.get("blocked_by", []))
        contract = result.get("schema_contract") or {}
        self.assertEqual("blocked", contract.get("status"))
        self.assertEqual(["media_credit_buckets"], contract.get("missing_relations"))
        self.assertNotIn("database_url_public", result, "blocked schema probe must not return connection details")
        self.assertNotIn("red-light-secret", str(result))
        self.assertIs(False, result.get("secret_exposed"))

    def test_live_probe_blocks_and_names_migration_checksum_drift(self) -> None:
        relations, migrations = _initial_relations_and_migrations()
        relations.add("media_credit_buckets")
        migrations[BUCKET_MIGRATION_ID] = "unexpected-drifted-checksum"
        state = _FakePostgresState(relations=relations, migration_checksums=migrations)
        with _postgres_settings() as settings, _fake_psycopg(state):
            result = run_postgres_live_probe(settings)

        self.assertEqual("blocked", result.get("status"))
        self.assertIn("postgres_schema_migration_checksum_drift", result.get("blocked_by", []))
        contract = result.get("schema_contract") or {}
        self.assertEqual("blocked", contract.get("status"))
        self.assertEqual(
            [BUCKET_MIGRATION_ID],
            contract.get("checksum_drift_migration_ids"),
        )
        self.assertNotIn("database_url_public", result, "blocked schema probe must not return connection details")
        self.assertNotIn("unexpected-drifted-checksum", str(result), "probe must expose only drift code and migration id")
        self.assertNotIn("red-light-secret", str(result))
        self.assertIs(False, result.get("secret_exposed"))

    def test_migration_runner_blocks_existing_id_checksum_drift_before_ddl(self) -> None:
        drifted_checksum = "unexpected-existing-checksum"
        state = _FakePostgresState(migration_checksums={BUCKET_MIGRATION_ID: drifted_checksum})
        migration_sql = f"""
begin;
create table if not exists migration_checksum_drift_probe (probe_id text primary key);
insert into schema_migrations (migration_id, checksum, summary)
values ('{BUCKET_MIGRATION_ID}', '{BUCKET_MIGRATION_CHECKSUM}', 'checksum drift contract probe')
on conflict (migration_id) do nothing;
commit;
"""
        with tempfile.TemporaryDirectory(prefix="jiejing-migration-drift-") as temp_dir:
            migration_path = Path(temp_dir) / "002_checksum_drift_contract.sql"
            migration_path.write_text(migration_sql, encoding="utf-8")
            with _fake_psycopg(state):
                result = run_postgres_migration(database_url=DATABASE_URL, migration_path=migration_path)

        self.assertEqual("blocked", result.get("status"))
        self.assertEqual(["postgres_schema_migration_checksum_drift"], result.get("blocked_by"))
        self.assertEqual(BUCKET_MIGRATION_ID, result.get("migration_id"))
        self.assertEqual(0, state.migration_execution_count, "checksum drift must stop before migration DDL executes")
        self.assertEqual(
            drifted_checksum,
            state.migration_checksums.get(BUCKET_MIGRATION_ID),
            "ON CONFLICT must not overwrite or conceal an existing checksum",
        )
        for forbidden_key in ("database_url", "database_url_public", "connection", "connection_string"):
            self.assertNotIn(forbidden_key, result)
        self.assertNotIn("red-light-secret", str(result))
        self.assertNotIn(drifted_checksum, str(result), "the stored checksum is internal evidence, not response data")
        self.assertNotIn(BUCKET_MIGRATION_CHECKSUM, str(result), "the expected checksum is internal evidence, not response data")
        self.assertIs(False, result.get("secret_exposed"))

    def test_two_migration_runners_serialize_with_session_advisory_lock(self) -> None:
        state = _FakePostgresState(simulate_migration_work=True)
        approved_key = (POSTGRES_MIGRATION_ADVISORY_LOCK_KEY,)
        self.assertEqual(
            approved_key,
            _advisory_lock_key("select pg_advisory_lock(%s)", (POSTGRES_MIGRATION_ADVISORY_LOCK_KEY,)),
        )
        self.assertEqual(
            approved_key,
            _advisory_lock_key(f"select pg_advisory_lock({POSTGRES_MIGRATION_ADVISORY_LOCK_KEY})", ()),
        )
        self.assertIsNot(
            state.session_lock_for(approved_key),
            state.session_lock_for((POSTGRES_MIGRATION_ADVISORY_LOCK_KEY + 1,)),
            "different advisory keys must map to different fake session locks",
        )
        migration_sql = f"""
begin;
create table if not exists migration_concurrency_probe (probe_id text primary key);
insert into schema_migrations (migration_id, checksum, summary)
values ('{BUCKET_MIGRATION_ID}', '{BUCKET_MIGRATION_CHECKSUM}', 'concurrency contract probe')
on conflict (migration_id) do nothing;
commit;
"""
        results: list[dict[str, Any]] = []
        errors: list[BaseException] = []
        start = threading.Barrier(2)

        def runner(path: Path) -> None:
            try:
                start.wait(timeout=2)
                results.append(run_postgres_migration(database_url=DATABASE_URL, migration_path=path))
            except BaseException as exc:  # pragma: no cover - retained for diagnostic assertion
                errors.append(exc)

        with tempfile.TemporaryDirectory(prefix="jiejing-migration-lock-") as temp_dir:
            migration_path = Path(temp_dir) / "002_concurrency_contract.sql"
            migration_path.write_text(migration_sql, encoding="utf-8")
            with _fake_psycopg(state):
                threads = [
                    threading.Thread(
                        target=runner,
                        args=(migration_path,),
                        name=f"postgres-migration-contract-{index}",
                        daemon=True,
                    )
                    for index in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)
                alive_threads = [thread.name for thread in threads if thread.is_alive()]
                self.assertFalse(
                    alive_threads,
                    f"concurrent migration runners did not terminate within 5 seconds: {alive_threads}",
                )

        self.assertFalse(errors, f"concurrent migration fixture raised unexpectedly: {errors}")
        self.assertEqual(2, len(results), "both runners must observe the same migration outcome")
        self.assertTrue(all(item.get("status") in {"ok", "already_applied"} for item in results))
        session_lock_sql = [sql for sql in state.executed_sql if SESSION_ADVISORY_LOCK_SQL.search(sql)]
        transaction_lock_sql = [sql for sql in state.executed_sql if TRANSACTION_ADVISORY_LOCK_SQL.search(sql)]
        explicit_unlock_sql = [sql for sql in state.executed_sql if SESSION_ADVISORY_UNLOCK_SQL.search(sql)]
        self.assertFalse(
            transaction_lock_sql,
            "transaction-scoped pg_advisory_xact_lock cannot replace the required cross-runner session lock",
        )
        self.assertEqual(2, len(session_lock_sql), "each runner must execute exact session-level pg_advisory_lock SQL")
        self.assertEqual(2, len(explicit_unlock_sql), "each runner must execute exact pg_advisory_unlock SQL")
        self.assertEqual(
            [approved_key, approved_key],
            state.advisory_lock_keys,
            "both migration runners must contend on the same approved fixed advisory key",
        )
        self.assertEqual(
            state.advisory_lock_keys,
            state.advisory_unlock_keys,
            "each runner must unlock the exact advisory key it acquired",
        )
        self.assertEqual(
            state.advisory_lock_keys,
            state.successful_advisory_unlock_keys,
            "unlocking a different key must not count as a successful session unlock",
        )
        self.assertEqual(2, state.advisory_lock_calls, "each runner must acquire the session advisory lock")
        self.assertEqual(2, state.advisory_unlock_sql_calls, "each runner must request explicit session unlock")
        self.assertEqual(
            2,
            state.advisory_unlock_calls,
            "a dummy unlock without a held session lock must not satisfy the migration contract",
        )
        self.assertEqual(1, state.max_concurrent_migration_executions, "migration DDL must not execute concurrently")
        self.assertEqual(1, state.migration_execution_count, "the waiting runner must verify instead of repeating DDL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
