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
from dataclasses import dataclass
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
RUNTIME_RECONCILIATION_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "003_runtime_schema_reconciliation_postgres.sql"
)
PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "004_platform_model_trial_reservations_postgres.sql"
)
INITIAL_MIGRATION_CANONICAL_SHA256 = "d76293f426d20cdcc0a2667284900c8cb91606f26e464ff1a4e1b96e409444f6"
BUCKET_MIGRATION_ID = "20260823_002_media_credit_buckets_postgres"
BUCKET_MIGRATION_CHECKSUM = "jiejing-media-credit-buckets-postgres-v20260823"
RUNTIME_RECONCILIATION_MIGRATION_ID = "20260823_003_runtime_schema_reconciliation_postgres"
RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM = "jiejing-runtime-schema-reconciliation-postgres-v20260823"
PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID = "20260901_004_platform_model_trial_reservations_postgres"
PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_CHECKSUM = (
    "jiejing-platform-model-trial-reservations-postgres-v20260901"
)
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

MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID = "media_credit_buckets.company_fk"
MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID = "media_credit_buckets.company_source_reference_unique"
USER_SESSION_REFRESH_FK_CONTRACT_ID = "user_sessions_refresh_session_id_fkey"
PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID = "platform_model_trial_reservations.company_fk"
PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID = (
    "platform_model_trial_reservations.company_period_slot_unique"
)


@dataclass(frozen=True)
class _FakeIndexDefinition:
    table_name: str
    columns: tuple[str, ...]
    access_method: str = "btree"
    is_unique: bool = False
    is_valid: bool = True
    is_ready: bool = True
    is_live: bool = True

    def catalog_definition(self, index_name: str) -> str:
        columns = ", ".join(self.columns)
        unique = "UNIQUE " if self.is_unique else ""
        return (
            f"CREATE {unique}INDEX {index_name} ON public.{self.table_name} "
            f"USING {self.access_method} ({columns})"
        )


@dataclass(frozen=True)
class _FakeColumnDefinition:
    data_type: str
    nullable: bool

    @property
    def information_schema_data_type(self) -> str:
        return {
            "timestamptz": "timestamp with time zone",
        }.get(self.data_type, self.data_type)

    @property
    def udt_name(self) -> str:
        return {
            "integer": "int4",
            "bigint": "int8",
        }.get(self.data_type, self.data_type)


@dataclass(frozen=True)
class _FakeConstraintDefinition:
    constraint_type: str
    table_name: str
    columns: tuple[str, ...]
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()

    def catalog_definition(self) -> str:
        columns = ", ".join(self.columns)
        if self.constraint_type == "f":
            referenced_columns = ", ".join(self.referenced_columns)
            return f"FOREIGN KEY ({columns}) REFERENCES {self.referenced_table}({referenced_columns})"
        if self.constraint_type == "u":
            return f"UNIQUE ({columns})"
        return f"UNSUPPORTED ({columns})"


def _expected_index_definitions() -> dict[str, _FakeIndexDefinition]:
    return {
        "idx_media_credit_buckets_company_status": _FakeIndexDefinition(
            "media_credit_buckets",
            ("company_id", "status", "expires_at"),
        ),
        "idx_user_refresh_sessions_owner": _FakeIndexDefinition(
            "user_refresh_sessions",
            ("user_id", "company_id", "status", "last_seen_at"),
        ),
        "idx_user_refresh_token_history_session": _FakeIndexDefinition(
            "user_refresh_token_history",
            ("session_id", "generation"),
        ),
        "idx_user_sessions_refresh_session": _FakeIndexDefinition(
            "user_sessions",
            ("refresh_session_id",),
        ),
    }


def _fake_index_matches_migration_contract(
    candidate: _FakeIndexDefinition | None,
    expected: _FakeIndexDefinition,
) -> bool:
    return bool(
        candidate is not None
        and candidate.table_name == expected.table_name
        and candidate.columns == expected.columns
        and candidate.access_method == "btree"
        and not candidate.is_unique
        and candidate.is_valid
        and candidate.is_ready
    )


def _expected_constraint_definitions() -> dict[str, _FakeConstraintDefinition]:
    return {
        MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID: _FakeConstraintDefinition(
            "f",
            "media_credit_buckets",
            ("company_id",),
            "companies",
            ("company_id",),
        ),
        MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID: _FakeConstraintDefinition(
            "u",
            "media_credit_buckets",
            ("company_id", "source_type", "source_reference_id"),
        ),
        USER_SESSION_REFRESH_FK_CONTRACT_ID: _FakeConstraintDefinition(
            "f",
            "user_sessions",
            ("refresh_session_id",),
            "user_refresh_sessions",
            ("session_id",),
        ),
        PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID: _FakeConstraintDefinition(
            "f",
            "platform_model_trial_reservations",
            ("company_id",),
            "companies",
            ("company_id",),
        ),
        PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID: _FakeConstraintDefinition(
            "u",
            "platform_model_trial_reservations",
            ("company_id", "period_key", "slot_number"),
        ),
    }


def _expected_column_definitions() -> dict[str, dict[str, _FakeColumnDefinition]]:
    required = _FakeColumnDefinition
    return {
        "media_credit_buckets": {
            "bucket_id": required("text", False),
            "company_id": required("text", False),
            "source_type": required("text", False),
            "source_reference_id": required("text", False),
            "granted_points": required("integer", False),
            "remaining_points": required("integer", False),
            "reserved_points": required("integer", False),
            "expires_at": required("timestamptz", True),
            "status": required("text", False),
            "created_at": required("timestamptz", False),
            "updated_at": required("timestamptz", False),
            "bucket_json": required("jsonb", False),
        },
        "external_execution_claims": {
            "claim_id": required("text", False),
            "company_id": required("text", False),
            "store_id": required("text", False),
            "confirmation_id": required("text", False),
            "action_type": required("text", False),
            "status": required("text", False),
            "nonce_sha256": required("text", False),
            "binding_json": required("jsonb", False),
            "claimed_by": required("text", False),
            "claimed_at": required("timestamptz", False),
            "expires_at": required("timestamptz", False),
            "consumed_at": required("timestamptz", True),
        },
        "user_refresh_sessions": {
            "session_id": required("text", False),
            "current_token_hash": required("text", False),
            "user_id": required("text", False),
            "company_id": required("text", False),
            "device_class": required("text", False),
            "status": required("text", False),
            "created_at": required("timestamptz", False),
            "last_seen_at": required("timestamptz", False),
            "expires_epoch": required("bigint", False),
            "revoked_at": required("timestamptz", True),
        },
        "user_refresh_token_history": {
            "token_hash": required("text", False),
            "session_id": required("text", False),
            "generation": required("bigint", False),
            "status": required("text", False),
            "issued_at": required("timestamptz", False),
            "rotated_at": required("timestamptz", True),
            "replayed_at": required("timestamptz", True),
            "expires_epoch": required("bigint", False),
        },
        "user_sessions": {
            "refresh_session_id": required("text", True),
        },
        "platform_model_trial_reservations": {
            "reservation_id": required("text", False),
            "company_id": required("text", False),
            "period_key": required("text", False),
            "slot_number": required("integer", False),
            "route_scope": required("text", False),
            "baseline_used": required("integer", False),
            "status": required("text", False),
            "created_at": required("timestamptz", False),
            "released_at": required("timestamptz", True),
        },
    }


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
        relation_columns: dict[str, set[str]] | None = None,
        column_definitions: dict[str, dict[str, _FakeColumnDefinition]] | None = None,
        indexes: dict[str, _FakeIndexDefinition] | None = None,
        constraints: dict[str, _FakeConstraintDefinition] | None = None,
        simulate_migration_work: bool = False,
    ) -> None:
        self.relations = set(relations or set())
        self.migration_checksums = dict(migration_checksums or {})
        self.relation_columns = {
            str(relation): set(columns)
            for relation, columns in (relation_columns or {}).items()
        }
        expected_column_definitions = _expected_column_definitions()
        self.column_definitions = {
            relation: {
                column: expected_column_definitions.get(relation, {}).get(
                    column,
                    _FakeColumnDefinition("text", True),
                )
                for column in columns
            }
            for relation, columns in self.relation_columns.items()
        }
        for relation, definitions in (column_definitions or {}).items():
            self.column_definitions.setdefault(str(relation), {}).update(definitions)
            self.relation_columns.setdefault(str(relation), set()).update(definitions)
        self.indexes = dict(indexes or {})
        self.constraints = dict(constraints or {})
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


def _catalog_projection(sql: str, from_clause: str) -> list[str]:
    projection = sql.split(from_clause, 1)[0]
    projection = re.sub(r"^\s*select\s+", "", projection, flags=re.IGNORECASE)
    return [field.strip() for field in projection.split(",") if field.strip()]


def _requested_catalog_names(params: tuple[Any, ...]) -> set[str] | None:
    for value in params:
        if isinstance(value, (list, tuple, set, frozenset)):
            return {str(item) for item in value}
    return None


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

        if normalized.startswith("select") and "information_schema.columns" in normalized:
            fields = _catalog_projection(normalized, "from information_schema.columns")
            requested_relation = str(safe_params[0]) if safe_params and isinstance(safe_params[0], str) else ""
            requested_names = _requested_catalog_names(safe_params)
            definitions = [
                (relation, column, definition)
                for relation, columns in sorted(self.state.column_definitions.items())
                if (not requested_relation or relation == requested_relation)
                and (requested_names is None or relation in requested_names)
                for column, definition in sorted(columns.items())
            ]
            self._rows = [
                tuple(
                    relation
                    if "table_name" in field
                    else column
                    if "column_name" in field
                    else definition.information_schema_data_type
                    if "data_type" in field
                    else definition.udt_name
                    if "udt_name" in field
                    else "YES" if "is_nullable" in field and definition.nullable
                    else "NO" if "is_nullable" in field
                    else None
                    for field in fields
                )
                for relation, column, definition in definitions
            ]
            return self

        if normalized.startswith("select") and (
            "pg_indexes" in normalized
            or "from pg_index" in normalized
            or ("from pg_class" in normalized and "relkind" in normalized and "'i'" in normalized)
        ):
            requested_names = _requested_catalog_names(safe_params)
            definitions = [
                (name, definition)
                for name, definition in sorted(self.state.indexes.items())
                if requested_names is None or name in requested_names
            ]
            if "pg_indexes" in normalized or "from pg_index" in normalized:
                from_clause = "from pg_indexes" if "pg_indexes" in normalized else "from pg_index"
                fields = _catalog_projection(normalized, from_clause)
                self._rows = [
                    tuple(
                        name
                        if "indexname" in field or "idx_rel.relname" in field or "index_name" in field
                        else definition.table_name
                        if "tablename" in field or "table_rel.relname" in field or "table_name" in field
                        else definition.access_method
                        if "amname" in field or "access_method" in field
                        else definition.is_unique
                        if "indisunique" in field or "is_unique" in field
                        else definition.is_valid
                        if "indisvalid" in field or "is_valid" in field
                        else definition.is_ready
                        if "indisready" in field or "is_ready" in field
                        else definition.is_live
                        if "indislive" in field or "is_live" in field
                        else list(definition.columns)
                        if "array_agg" in field or "column_names" in field or "columns" in field
                        else definition.catalog_definition(name)
                        if "indexdef" in field or "pg_get_indexdef" in field
                        else None
                        for field in fields
                    )
                    for name, definition in definitions
                ]
            else:
                self._rows = [(name,) for name, _definition in definitions]
            return self

        if normalized.startswith("select") and "pg_constraint" in normalized:
            requested_names = _requested_catalog_names(safe_params)
            definitions = [
                (name, definition)
                for name, definition in sorted(self.state.constraints.items())
                if requested_names is None
                or (
                    definition.table_name in requested_names
                    if "rel.relname::text = any" in normalized
                    else name in requested_names
                )
            ]
            fields = _catalog_projection(normalized, "from pg_constraint")
            self._rows = [
                tuple(
                    name
                    if "conname" in field
                    else definition.referenced_table
                    if "ref_rel.relname" in field
                    else definition.table_name
                    if "rel.relname" in field
                    else definition.constraint_type
                    if "contype" in field
                    else definition.catalog_definition()
                    if "pg_get_constraintdef" in field
                    else None
                    for field in fields
                )
                for name, definition in definitions
            ]
            return self

        if normalized.startswith("select") and (
            "information_schema.tables" in normalized or "from pg_class" in normalized
        ):
            self._rows = [(name,) for name in sorted(self.state.relations)]
            return self

        if "create table" in normalized:
            self._record_migration_execution(sql)
        self._apply_schema_ddl(sql)
        self._enforce_inline_schema_postconditions(sql)
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

    def _apply_schema_ddl(self, sql: str) -> None:
        relations: set[str] = set()
        created_column_definitions: dict[str, dict[str, _FakeColumnDefinition]] = {}
        for match in re.finditer(
            r"create\s+table\s+if\s+not\s+exists\s+([a-z_]+)\s*\((.*?)\)\s*;",
            str(sql),
            flags=re.IGNORECASE | re.DOTALL,
        ):
            relation = match.group(1).lower()
            relations.add(relation)
            created_column_definitions[relation] = _column_definitions_from_table_body(match.group(2))
        altered_column_definitions: dict[str, dict[str, _FakeColumnDefinition]] = {}
        for match in re.finditer(
            r"alter\s+table\s+([a-z_]+)\s+add\s+column\s+if\s+not\s+exists\s+"
            r"([a-z_]+)\s+([a-z_]+)(\s+not\s+null)?",
            str(sql),
            flags=re.IGNORECASE,
        ):
            altered_column_definitions.setdefault(match.group(1).lower(), {})[match.group(2).lower()] = (
                _FakeColumnDefinition(match.group(3).lower(), not bool(match.group(4)))
            )
        indexes: dict[str, _FakeIndexDefinition] = {}
        for match in re.finditer(
            r"create\s+(?:unique\s+)?index\s+if\s+not\s+exists\s+([a-z_]+)\s+"
            r"on\s+([a-z_]+)\s*\(([^)]+)\)",
            str(sql),
            flags=re.IGNORECASE,
        ):
            indexes[match.group(1).lower()] = _FakeIndexDefinition(
                match.group(2).lower(),
                tuple(part.strip().lower() for part in match.group(3).split(",")),
            )
        constraints: dict[str, _FakeConstraintDefinition] = {}
        for match in re.finditer(
            r"alter\s+table\s+([a-z_]+).*?add\s+constraint\s+([a-z_]+)\s+"
            r"foreign\s+key\s*\(([^)]+)\)\s+references\s+([a-z_]+)\s*\(([^)]+)\)",
            str(sql),
            flags=re.IGNORECASE | re.DOTALL,
        ):
            constraints[match.group(2).lower()] = _FakeConstraintDefinition(
                "f",
                match.group(1).lower(),
                tuple(part.strip().lower() for part in match.group(3).split(",")),
                match.group(4).lower(),
                tuple(part.strip().lower() for part in match.group(5).split(",")),
            )
        with self.state.state_lock:
            new_relations = relations - self.state.relations
            self.state.relations.update(relations)
            for relation in new_relations:
                definitions = created_column_definitions.get(relation, {})
                self.state.relation_columns.setdefault(relation, set()).update(definitions)
                self.state.column_definitions.setdefault(relation, {}).update(definitions)
            for relation, definitions in altered_column_definitions.items():
                existing_columns = self.state.relation_columns.setdefault(relation, set())
                existing_definitions = self.state.column_definitions.setdefault(relation, {})
                for column, definition in definitions.items():
                    if column not in existing_columns:
                        existing_columns.add(column)
                        existing_definitions[column] = definition
            for name, definition in indexes.items():
                self.state.indexes.setdefault(name, definition)
            for name, definition in constraints.items():
                self.state.constraints.setdefault(name, definition)
            if "media_credit_buckets" in new_relations:
                expected_constraints = _expected_constraint_definitions()
                self.state.constraints.setdefault(
                    MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID,
                    expected_constraints[MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID],
                )
                self.state.constraints.setdefault(
                    MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID,
                    expected_constraints[MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID],
                )
            if "platform_model_trial_reservations" in new_relations:
                expected_constraints = _expected_constraint_definitions()
                self.state.constraints.setdefault(
                    PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID,
                    expected_constraints[PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID],
                )
                self.state.constraints.setdefault(
                    PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID,
                    expected_constraints[PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID],
                )

    def _enforce_inline_schema_postconditions(self, sql: str) -> None:
        marker_match = re.search(
            r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'",
            str(sql),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if marker_match is None:
            return
        before_marker = str(sql)[: marker_match.start()]
        if not re.search(r"\braise\s+exception\b", before_marker, flags=re.IGNORECASE):
            return

        migration_id = marker_match.group(1)
        expected_indexes = _expected_index_definitions()
        expected_constraints = _expected_constraint_definitions()
        expected_columns = _expected_column_definitions()
        if migration_id == BUCKET_MIGRATION_ID:
            required_columns = {
                "media_credit_buckets": expected_columns["media_credit_buckets"],
            }
            required_indexes = {
                "idx_media_credit_buckets_company_status": expected_indexes[
                    "idx_media_credit_buckets_company_status"
                ]
            }
            required_constraints = {
                key: expected_constraints[key]
                for key in (
                    MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID,
                    MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID,
                )
            }
        elif migration_id == RUNTIME_RECONCILIATION_MIGRATION_ID:
            required_columns = {
                relation: expected_columns[relation]
                for relation in (
                    "external_execution_claims",
                    "user_refresh_sessions",
                    "user_refresh_token_history",
                    "user_sessions",
                )
            }
            required_indexes = {
                key: expected_indexes[key]
                for key in (
                    "idx_user_refresh_sessions_owner",
                    "idx_user_refresh_token_history_session",
                    "idx_user_sessions_refresh_session",
                )
            }
            required_constraints = {
                USER_SESSION_REFRESH_FK_CONTRACT_ID: expected_constraints[USER_SESSION_REFRESH_FK_CONTRACT_ID]
            }
        elif migration_id == PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID:
            required_columns = {
                "platform_model_trial_reservations": expected_columns[
                    "platform_model_trial_reservations"
                ],
            }
            required_indexes = {}
            required_constraints = {
                key: expected_constraints[key]
                for key in (
                    PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID,
                    PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID,
                )
            }
        else:
            return

        has_column_type_guard = bool(
            re.search(r"\b(?:format_type|atttypid|udt_name|data_type)\b", before_marker, re.IGNORECASE)
        )
        has_column_nullability_guard = bool(
            re.search(r"\b(?:attnotnull|is_nullable)\b", before_marker, re.IGNORECASE)
        )
        invalid_columns = []
        if has_column_type_guard and has_column_nullability_guard:
            invalid_columns = [
                f"{relation}.{column}"
                for relation, definitions in required_columns.items()
                for column, expected in definitions.items()
                if self.state.column_definitions.get(relation, {}).get(column) != expected
            ]
        invalid_indexes = [
            name
            for name, expected in required_indexes.items()
            if not _fake_index_matches_migration_contract(self.state.indexes.get(name), expected)
        ]
        invalid_constraints = [
            name for name, expected in required_constraints.items() if self.state.constraints.get(name) != expected
        ]
        if invalid_columns or invalid_indexes or invalid_constraints:
            raise RuntimeError("fake_postgres_schema_postcondition_failed")


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


def _column_names_from_table_body(table_body: str) -> set[str]:
    columns: set[str] = set()
    for raw_line in str(table_body).splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        first_token = line.split(None, 1)[0].lower()
        if first_token in {"check", "constraint", "foreign", "primary", "unique"}:
            continue
        if re.fullmatch(r"[a-z_][a-z0-9_]*", first_token):
            columns.add(first_token)
    return columns


def _column_definitions_from_table_body(table_body: str) -> dict[str, _FakeColumnDefinition]:
    definitions: dict[str, _FakeColumnDefinition] = {}
    for raw_line in str(table_body).splitlines():
        line = raw_line.strip().rstrip(",")
        match = re.match(
            r"([a-z_][a-z0-9_]*)\s+(text|integer|bigint|timestamptz|jsonb)\b(.*)",
            line,
            flags=re.IGNORECASE,
        )
        if match is None:
            continue
        tail = match.group(3).lower()
        definitions[match.group(1).lower()] = _FakeColumnDefinition(
            match.group(2).lower(),
            not ("not null" in tail or "primary key" in tail),
        )
    return definitions


def _intended_schema_state(
    *,
    include_runtime_reconciliation_marker: bool = True,
    include_platform_model_trial_reservation_marker: bool = True,
) -> tuple[
    set[str],
    dict[str, str],
    dict[str, set[str]],
    dict[str, _FakeIndexDefinition],
    dict[str, _FakeConstraintDefinition],
]:
    relations, migrations = _initial_relations_and_migrations()
    relations.add("media_credit_buckets")
    migrations[BUCKET_MIGRATION_ID] = BUCKET_MIGRATION_CHECKSUM
    if include_runtime_reconciliation_marker:
        migrations[RUNTIME_RECONCILIATION_MIGRATION_ID] = RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM
    relations.add("platform_model_trial_reservations")
    if include_platform_model_trial_reservation_marker:
        migrations[PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID] = (
            PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_CHECKSUM
        )
    relation_columns = {
        relation: set(definitions)
        for relation, definitions in _expected_column_definitions().items()
    }
    indexes = _expected_index_definitions()
    constraints = _expected_constraint_definitions()
    return relations, migrations, relation_columns, indexes, constraints


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


def _fail_closed_guard_before_marker(sql: str) -> str:
    marker = re.search(r"insert\s+into\s+schema_migrations", sql, flags=re.IGNORECASE)
    if marker is None:
        return ""
    before_marker = sql[: marker.start()]
    guards = re.findall(
        r"do\s+\$\$(.*?)end\s+\$\$\s*;",
        before_marker,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return "\n".join(guard for guard in guards if re.search(r"\braise\s+exception\b", guard, re.IGNORECASE))


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

    def test_003_is_an_independent_runtime_schema_reconciliation_migration(self) -> None:
        self.assertEqual(
            INITIAL_MIGRATION_CANONICAL_SHA256,
            _canonical_text_sha256(INITIAL_MIGRATION),
            "published migration 001 must remain byte-for-byte canonical",
        )
        self.assertTrue(
            RUNTIME_RECONCILIATION_MIGRATION.is_file(),
            "independent PostgreSQL 003 runtime-schema reconciliation migration is missing",
        )
        migration_sql = RUNTIME_RECONCILIATION_MIGRATION.read_text(encoding="utf-8")
        self.assertRegex(migration_sql, r"(?is)^\s*begin\s*;")
        self.assertRegex(migration_sql, r"(?is)commit\s*;\s*$")

        required_table_columns = {
            "external_execution_claims": {
                "claim_id",
                "company_id",
                "store_id",
                "confirmation_id",
                "action_type",
                "status",
                "nonce_sha256",
                "binding_json",
                "claimed_by",
                "claimed_at",
                "expires_at",
                "consumed_at",
            },
            "user_refresh_sessions": {
                "session_id",
                "current_token_hash",
                "user_id",
                "company_id",
                "device_class",
                "status",
                "created_at",
                "last_seen_at",
                "expires_epoch",
                "revoked_at",
            },
            "user_refresh_token_history": {
                "token_hash",
                "session_id",
                "generation",
                "status",
                "issued_at",
                "rotated_at",
                "replayed_at",
                "expires_epoch",
            },
        }
        for table_name, expected_columns in required_table_columns.items():
            table_body = _create_table_body(migration_sql, table_name)
            self.assertTrue(table_body, f"003 must independently reconcile missing table: {table_name}")
            self.assertTrue(
                expected_columns.issubset(_column_names_from_table_body(table_body)),
                f"003 has an incomplete column contract for {table_name}",
            )

        self.assertRegex(
            migration_sql,
            r"(?is)alter\s+table\s+user_sessions\s+add\s+column\s+if\s+not\s+exists\s+"
            r"refresh_session_id\s+text\b",
        )
        index_contracts = {
            "idx_user_refresh_sessions_owner": (
                "user_refresh_sessions",
                r"user_id\s*,\s*company_id\s*,\s*status\s*,\s*last_seen_at",
            ),
            "idx_user_refresh_token_history_session": (
                "user_refresh_token_history",
                r"session_id\s*,\s*generation",
            ),
            "idx_user_sessions_refresh_session": ("user_sessions", "refresh_session_id"),
        }
        for index_name, (table_name, columns_pattern) in index_contracts.items():
            self.assertRegex(
                migration_sql,
                rf"(?is)create\s+index\s+if\s+not\s+exists\s+{index_name}\s+"
                rf"on\s+{table_name}\s*\(\s*{columns_pattern}\s*\)",
            )
        self.assertRegex(
            migration_sql,
            r"(?is)add\s+constraint\s+user_sessions_refresh_session_id_fkey\s+"
            r"foreign\s+key\s*\(\s*refresh_session_id\s*\)\s+"
            r"references\s+user_refresh_sessions\s*\(\s*session_id\s*\)",
        )
        migration_records = dict(
            re.findall(
                r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
                migration_sql,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        self.assertEqual(
            {RUNTIME_RECONCILIATION_MIGRATION_ID: RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM},
            migration_records,
            "003 must own exactly one immutable migration marker",
        )
        self.assertRegex(migration_sql, r"(?is)on\s+conflict\s*\(\s*migration_id\s*\)\s+do\s+nothing")

    def test_004_is_an_independent_atomic_platform_trial_reservation_migration(self) -> None:
        initial_sql = INITIAL_MIGRATION.read_text(encoding="utf-8")
        self.assertNotIn("platform_model_trial_reservations", initial_sql.lower())
        self.assertTrue(PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION.is_file())
        migration_sql = PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION.read_text(encoding="utf-8")
        self.assertRegex(migration_sql, r"(?is)^\s*begin\s*;")
        self.assertRegex(migration_sql, r"(?is)commit\s*;\s*$")
        table_body = _create_table_body(migration_sql, "platform_model_trial_reservations")
        for pattern in (
            r"\breservation_id\s+text\s+primary\s+key\b",
            r"\bcompany_id\s+text\s+not\s+null\s+references\s+companies\s*\(\s*company_id\s*\)",
            r"\bperiod_key\s+text\s+not\s+null\b",
            r"\bslot_number\s+integer\s+not\s+null\s+check\s*\(\s*slot_number\s*>\s*0\s*\)",
            r"\broute_scope\s+text\s+not\s+null\b",
            r"\bbaseline_used\s+integer\s+not\s+null\s+default\s+0\b",
            r"\bstatus\s+text\s+not\s+null\s+default\s+'consumed'",
            r"\bcreated_at\s+timestamptz\s+not\s+null\b",
            r"\breleased_at\s+timestamptz\b",
            r"\bunique\s*\(\s*company_id\s*,\s*period_key\s*,\s*slot_number\s*\)",
        ):
            self.assertRegex(table_body, pattern)
        guard = _fail_closed_guard_before_marker(migration_sql)
        self.assertRegex(guard, r"(?is)information_schema\.columns")
        self.assertRegex(guard, r"(?is)pg_constraint")
        self.assertIn("company_id", guard)
        self.assertIn("period_key", guard)
        self.assertIn("slot_number", guard)
        self.assertIn("baseline_used", guard)
        self.assertIn("status", guard)
        self.assertIn("released_at", guard)
        self.assertRegex(
            migration_sql,
            r"(?is)alter\s+table\s+platform_model_trial_reservations\s+add\s+column\s+if\s+not\s+exists\s+status",
        )
        self.assertRegex(
            migration_sql,
            r"(?is)update\s+platform_model_trial_reservations.*?baseline_used",
        )
        migration_records = dict(
            re.findall(
                r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
                migration_sql,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
        self.assertEqual(
            {
                PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID:
                    PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_CHECKSUM,
            },
            migration_records,
        )
        self.assertRegex(migration_sql, r"(?is)on\s+conflict\s*\(\s*migration_id\s*\)\s+do\s+nothing")

    def test_002_and_003_fail_closed_validate_physical_definitions_before_marker(self) -> None:
        contracts = {
            BUCKET_MIGRATION: (
                "idx_media_credit_buckets_company_status",
                "media_credit_buckets",
                "company_id",
                "source_type",
                "source_reference_id",
                "companies",
            ),
            RUNTIME_RECONCILIATION_MIGRATION: (
                "idx_user_refresh_sessions_owner",
                "idx_user_refresh_token_history_session",
                "idx_user_sessions_refresh_session",
                USER_SESSION_REFRESH_FK_CONTRACT_ID,
                "user_sessions",
                "refresh_session_id",
                "user_refresh_sessions",
                "session_id",
            ),
        }
        for migration_path, required_tokens in contracts.items():
            with self.subTest(migration=migration_path.name):
                migration_sql = migration_path.read_text(encoding="utf-8")
                guard = _fail_closed_guard_before_marker(migration_sql)
                self.assertTrue(
                    guard,
                    f"{migration_path.name} must fail closed on wrong physical definitions before its marker",
                )
                self.assertRegex(guard, r"(?is)\bpg_constraint\b")
                self.assertRegex(guard, r"(?is)\b(?:pg_indexes|pg_index)\b")
                for token in required_tokens:
                    self.assertIn(token.lower(), guard.lower())

    def test_migration_003_does_not_record_marker_over_wrong_same_name_refresh_fk(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state(
            include_runtime_reconciliation_marker=False
        )
        constraints[USER_SESSION_REFRESH_FK_CONTRACT_ID] = _FakeConstraintDefinition(
            "f",
            "user_sessions",
            ("wrong_source_column",),
            "wrong_target_table",
            ("wrong_target_column",),
        )
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )

        with _fake_psycopg(state):
            result = run_postgres_migration(database_url=DATABASE_URL)

        self.assertNotIn(
            result.get("status"),
            {"ok", "already_applied"},
            "a same-name but structurally wrong refresh FK must fail closed instead of recording 003",
        )
        self.assertNotIn(
            RUNTIME_RECONCILIATION_MIGRATION_ID,
            state.migration_checksums,
            "003 marker must remain absent when its exact refresh-session FK postcondition is false",
        )
        self.assertNotIn("wrong_source_column", str(result))
        self.assertNotIn("wrong_target_table", str(result))
        self.assertNotIn("wrong_target_column", str(result))
        self.assertNotIn("red-light-secret", str(result))
        self.assertIs(False, result.get("secret_exposed"))

    def test_default_manifest_reconciles_legacy_marker_database_once_then_probes_clean(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state(
            include_runtime_reconciliation_marker=False,
            include_platform_model_trial_reservation_marker=False,
        )
        relations.difference_update(
            {
                "external_execution_claims",
                "user_refresh_sessions",
                "user_refresh_token_history",
                "platform_model_trial_reservations",
            }
        )
        relation_columns.pop("platform_model_trial_reservations", None)
        relation_columns["user_sessions"].discard("refresh_session_id")
        for index_name in (
            "idx_user_refresh_sessions_owner",
            "idx_user_refresh_token_history_session",
            "idx_user_sessions_refresh_session",
        ):
            indexes.pop(index_name)
        constraints.pop(USER_SESSION_REFRESH_FK_CONTRACT_ID)
        constraints.pop(PLATFORM_MODEL_TRIAL_COMPANY_FK_CONTRACT_ID)
        constraints.pop(PLATFORM_MODEL_TRIAL_SLOT_UNIQUE_CONTRACT_ID)
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )

        with _fake_psycopg(state):
            first = run_postgres_migration(database_url=DATABASE_URL)
            second = run_postgres_migration(database_url=DATABASE_URL)
        with _postgres_settings() as settings, _fake_psycopg(state):
            probe = run_postgres_live_probe(settings)

        self.assertEqual("ok", first.get("status"), first)
        self.assertEqual(
            [RUNTIME_RECONCILIATION_MIGRATION_ID, PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID],
            first.get("applied_migration_ids"),
            "a legacy marker database must execute each missing additive migration",
        )
        self.assertEqual("ok", second.get("status"), second)
        self.assertIn(
            RUNTIME_RECONCILIATION_MIGRATION_ID,
            second.get("skipped_migration_ids", []),
            "a second runner must observe the 003 marker and skip DDL",
        )
        self.assertIn(
            PLATFORM_MODEL_TRIAL_RESERVATION_MIGRATION_ID,
            second.get("skipped_migration_ids", []),
            "a second runner must observe the 004 marker and skip DDL",
        )
        self.assertEqual(2, state.migration_execution_count, "003 and 004 DDL must each execute exactly once")
        self.assertEqual("ok", probe.get("status"), probe)
        self.assertIs(False, probe.get("secret_exposed"))

    def test_live_probe_blocks_missing_critical_schema_postconditions_without_secrets(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
        relation_columns["media_credit_buckets"].discard("bucket_json")
        relation_columns["user_sessions"].discard("refresh_session_id")
        indexes.clear()
        constraints.pop(USER_SESSION_REFRESH_FK_CONTRACT_ID)
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )
        with _postgres_settings() as settings, _fake_psycopg(state):
            result = run_postgres_live_probe(settings)

        self.assertEqual("blocked", result.get("status"), result)
        self.assertIn("postgres_schema_missing_postconditions", result.get("blocked_by", []))
        contract = result.get("schema_contract") or {}
        self.assertEqual("blocked", contract.get("status"))
        self.assertEqual(
            ["media_credit_buckets.bucket_json", "user_sessions.refresh_session_id"],
            contract.get("missing_columns"),
        )
        self.assertEqual(
            [
                "idx_media_credit_buckets_company_status",
                "idx_user_refresh_sessions_owner",
                "idx_user_refresh_token_history_session",
                "idx_user_sessions_refresh_session",
            ],
            contract.get("missing_indexes"),
        )
        self.assertEqual(
            ["user_sessions_refresh_session_id_fkey"],
            contract.get("missing_constraints"),
        )
        self.assertNotIn("database_url_public", result)
        self.assertNotIn("red-light-secret", str(result))
        self.assertNotIn(RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM, str(result))
        self.assertIs(False, result.get("secret_exposed"))

    def test_live_probe_blocks_same_name_wrong_physical_definitions_without_echoing_them(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
        indexes["idx_media_credit_buckets_company_status"] = _FakeIndexDefinition(
            "wrong_index_table",
            ("wrong_index_column", "status", "expires_at"),
        )
        constraints[USER_SESSION_REFRESH_FK_CONTRACT_ID] = _FakeConstraintDefinition(
            "f",
            "wrong_fk_source_table",
            ("wrong_fk_source_column",),
            "wrong_fk_target_table",
            ("wrong_fk_target_column",),
        )
        constraints[MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID] = _FakeConstraintDefinition(
            "f",
            "media_credit_buckets",
            ("company_id",),
            "wrong_company_target_table",
            ("wrong_company_target_column",),
        )
        constraints[MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID] = _FakeConstraintDefinition(
            "u",
            "media_credit_buckets",
            ("company_id", "source_type"),
        )
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )

        with _postgres_settings() as settings, _fake_psycopg(state):
            result = run_postgres_live_probe(settings)

        self.assertEqual("blocked", result.get("status"), result)
        self.assertIn("postgres_schema_missing_postconditions", result.get("blocked_by", []))
        contract = result.get("schema_contract") or {}
        self.assertEqual("blocked", contract.get("status"))
        self.assertEqual(
            ["idx_media_credit_buckets_company_status"],
            contract.get("missing_indexes"),
        )
        self.assertEqual(
            [
                MEDIA_BUCKET_COMPANY_FK_CONTRACT_ID,
                MEDIA_BUCKET_IDEMPOTENCY_UNIQUE_CONTRACT_ID,
                USER_SESSION_REFRESH_FK_CONTRACT_ID,
            ],
            contract.get("missing_constraints"),
        )
        self.assertLessEqual(
            len(state.executed_sql),
            6,
            f"definition-aware live probe must remain bounded, got: {state.executed_sql}",
        )
        for forbidden in (
            "wrong_index_table",
            "wrong_index_column",
            "wrong_fk_source_table",
            "wrong_fk_source_column",
            "wrong_fk_target_table",
            "wrong_fk_target_column",
            "wrong_company_target_table",
            "wrong_company_target_column",
            "red-light-secret",
        ):
            self.assertNotIn(forbidden, str(result), "physical catalog definitions are internal evidence")
        self.assertIs(False, result.get("secret_exposed"))

    def test_live_probe_blocks_same_name_indexes_that_are_not_btree_valid_ready_and_live(self) -> None:
        scenarios = {
            "wrong_access_method": _FakeIndexDefinition(
                "user_sessions",
                ("refresh_session_id",),
                access_method="hash",
            ),
            "invalid": _FakeIndexDefinition(
                "user_sessions",
                ("refresh_session_id",),
                is_valid=False,
            ),
            "not_ready": _FakeIndexDefinition(
                "user_sessions",
                ("refresh_session_id",),
                is_ready=False,
            ),
            "not_live": _FakeIndexDefinition(
                "user_sessions",
                ("refresh_session_id",),
                is_live=False,
            ),
        }

        for scenario, wrong_definition in scenarios.items():
            relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
            indexes["idx_user_sessions_refresh_session"] = wrong_definition
            state = _FakePostgresState(
                relations=relations,
                migration_checksums=migrations,
                relation_columns=relation_columns,
                indexes=indexes,
                constraints=constraints,
            )
            with _postgres_settings() as settings, _fake_psycopg(state):
                result = run_postgres_live_probe(settings)

            with self.subTest(scenario=scenario):
                contract = result.get("schema_contract") or {}
                self.assertEqual("blocked", result.get("status"), result)
                self.assertIn("postgres_schema_missing_postconditions", result.get("blocked_by", []))
                self.assertEqual(
                    ["idx_user_sessions_refresh_session"],
                    contract.get("missing_indexes"),
                )
                self.assertLessEqual(len(state.executed_sql), 6, state.executed_sql)
                self.assertNotIn(wrong_definition.catalog_definition("internal_index_name"), str(result))
                self.assertNotIn("red-light-secret", str(result))
                self.assertNotIn(RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM, str(result))
                self.assertIs(False, result.get("secret_exposed"))

    def test_existing_wrong_table_column_contracts_block_marker_and_live_readiness(self) -> None:
        scenarios = (
            {
                "name": "002_media_bucket_partial_wrong_type_and_nullable",
                "migration_path": BUCKET_MIGRATION,
                "marker": BUCKET_MIGRATION_ID,
                "missing": {("media_credit_buckets", "reserved_points")},
                "overrides": {
                    "media_credit_buckets": {
                        "bucket_json": _FakeColumnDefinition("text", True),
                    }
                },
                "expected_missing": [
                    "media_credit_buckets.bucket_json",
                    "media_credit_buckets.reserved_points",
                ],
            },
            {
                "name": "003_external_claims_partial",
                "migration_path": RUNTIME_RECONCILIATION_MIGRATION,
                "marker": RUNTIME_RECONCILIATION_MIGRATION_ID,
                "missing": {("external_execution_claims", "binding_json")},
                "overrides": {},
                "expected_missing": ["external_execution_claims.binding_json"],
            },
            {
                "name": "003_refresh_sessions_wrong_type",
                "migration_path": RUNTIME_RECONCILIATION_MIGRATION,
                "marker": RUNTIME_RECONCILIATION_MIGRATION_ID,
                "missing": set(),
                "overrides": {
                    "user_refresh_sessions": {
                        "expires_epoch": _FakeColumnDefinition("text", False),
                    }
                },
                "expected_missing": ["user_refresh_sessions.expires_epoch"],
            },
            {
                "name": "003_refresh_history_wrong_nullability",
                "migration_path": RUNTIME_RECONCILIATION_MIGRATION,
                "marker": RUNTIME_RECONCILIATION_MIGRATION_ID,
                "missing": set(),
                "overrides": {
                    "user_refresh_token_history": {
                        "issued_at": _FakeColumnDefinition("timestamptz", True),
                    }
                },
                "expected_missing": ["user_refresh_token_history.issued_at"],
            },
        )

        for scenario in scenarios:
            relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
            migrations.pop(str(scenario["marker"]), None)
            for relation, column in scenario["missing"]:
                relation_columns[relation].discard(column)
            migration_state = _FakePostgresState(
                relations=relations,
                migration_checksums=migrations,
                relation_columns=relation_columns,
                column_definitions=scenario["overrides"],
                indexes=indexes,
                constraints=constraints,
            )
            with _fake_psycopg(migration_state):
                migration_result = run_postgres_migration(
                    database_url=DATABASE_URL,
                    migration_path=scenario["migration_path"],
                )

            with self.subTest(scenario=scenario["name"], phase="migration"):
                self.assertTrue(
                    migration_result.get("status") not in {"ok", "already_applied"}
                    and scenario["marker"] not in migration_state.migration_checksums,
                    f"wrong pre-existing table contract must fail before marker: {migration_result}",
                )
                self.assertNotIn("red-light-secret", str(migration_result))
                self.assertIs(False, migration_result.get("secret_exposed"))

            probe_relations, probe_migrations, probe_columns, probe_indexes, probe_constraints = (
                _intended_schema_state()
            )
            for relation, column in scenario["missing"]:
                probe_columns[relation].discard(column)
            probe_state = _FakePostgresState(
                relations=probe_relations,
                migration_checksums=probe_migrations,
                relation_columns=probe_columns,
                column_definitions=scenario["overrides"],
                indexes=probe_indexes,
                constraints=probe_constraints,
            )
            with _postgres_settings() as settings, _fake_psycopg(probe_state):
                probe_result = run_postgres_live_probe(settings)

            with self.subTest(scenario=scenario["name"], phase="live_probe"):
                contract = probe_result.get("schema_contract") or {}
                self.assertEqual("blocked", probe_result.get("status"), probe_result)
                self.assertIn("postgres_schema_missing_postconditions", probe_result.get("blocked_by", []))
                self.assertEqual(scenario["expected_missing"], contract.get("missing_columns"))
                self.assertLessEqual(len(probe_state.executed_sql), 6, probe_state.executed_sql)
                self.assertNotIn("red-light-secret", str(probe_result))
                self.assertNotIn("create table", str(probe_result).lower())
                self.assertNotIn(RUNTIME_RECONCILIATION_MIGRATION_CHECKSUM, str(probe_result))
                self.assertIs(False, probe_result.get("secret_exposed"))

    def test_live_probe_uses_bounded_bulk_catalog_queries_for_correct_schema(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )
        with _postgres_settings() as settings, _fake_psycopg(state):
            result = run_postgres_live_probe(settings)

        self.assertEqual("ok", result.get("status"), result)
        self.assertLessEqual(
            len(state.executed_sql),
            6,
            f"live schema probe must use bounded bulk catalog queries, got: {state.executed_sql}",
        )
        self.assertFalse(
            [sql for sql in state.executed_sql if "to_regclass" in sql],
            "live probe must not issue one to_regclass query per required relation",
        )
        self.assertNotIn("red-light-secret", str(result))
        self.assertIs(False, result.get("secret_exposed"))

    def test_live_probe_blocks_and_names_missing_required_relation(self) -> None:
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
        relations.discard("media_credit_buckets")
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )
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
        relations, migrations, relation_columns, indexes, constraints = _intended_schema_state()
        migrations[BUCKET_MIGRATION_ID] = "unexpected-drifted-checksum"
        state = _FakePostgresState(
            relations=relations,
            migration_checksums=migrations,
            relation_columns=relation_columns,
            indexes=indexes,
            constraints=constraints,
        )
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
        self.assertNotIn(
            "unexpected-drifted-checksum",
            str(result),
            "probe must expose only drift code and migration id",
        )
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
        self.assertNotIn(
            BUCKET_MIGRATION_CHECKSUM,
            str(result),
            "the expected checksum is internal evidence, not response data",
        )
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
