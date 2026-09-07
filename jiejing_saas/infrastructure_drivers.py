"""Runtime infrastructure driver status for Jiejing SaaS.

This module is the next layer after the adapter contracts. It can validate
Python dependencies, redacted connection configuration, migration runner shape,
repository/worker cutover implementation status, and optional live
Postgres/Redis probes. It deliberately keeps the public API honest: runtime
cutover is ready only when implementation, dependencies, URLs and live checks
are all satisfied.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import SaaSSettings
from .postgres_repository_runtime import postgres_connect_timeout_seconds
from .redis_queue_runtime import redis_runtime_status


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_MIGRATION = ROOT / "jiejing_saas" / "migrations" / "001_initial_schema_postgres.sql"
POSTGRES_MEDIA_CREDIT_BUCKETS_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "002_media_credit_buckets_postgres.sql"
)
POSTGRES_RUNTIME_SCHEMA_RECONCILIATION_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "003_runtime_schema_reconciliation_postgres.sql"
)
POSTGRES_PLATFORM_MODEL_TRIAL_RESERVATIONS_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "004_platform_model_trial_reservations_postgres.sql"
)
POSTGRES_LISTING_DRAFT_EDIT_CHECKPOINTS_MIGRATION = (
    ROOT / "jiejing_saas" / "migrations" / "005_listing_draft_edit_checkpoints_postgres.sql"
)
POSTGRES_MIGRATION_ADVISORY_LOCK_KEY = -1280677561506917264


@dataclass(frozen=True)
class _PostgresColumnPostcondition:
    table_name: str
    column_name: str
    udt_name: str
    nullable: bool

    @property
    def identifier(self) -> str:
        return f"{self.table_name}.{self.column_name}"


POSTGRES_CRITICAL_COLUMN_POSTCONDITIONS: tuple[_PostgresColumnPostcondition, ...] = (
    _PostgresColumnPostcondition("media_credit_buckets", "bucket_id", "text", False),
    _PostgresColumnPostcondition("media_credit_buckets", "company_id", "text", False),
    _PostgresColumnPostcondition("media_credit_buckets", "source_type", "text", False),
    _PostgresColumnPostcondition("media_credit_buckets", "source_reference_id", "text", False),
    _PostgresColumnPostcondition("media_credit_buckets", "granted_points", "int4", False),
    _PostgresColumnPostcondition("media_credit_buckets", "remaining_points", "int4", False),
    _PostgresColumnPostcondition("media_credit_buckets", "reserved_points", "int4", False),
    _PostgresColumnPostcondition("media_credit_buckets", "expires_at", "timestamptz", True),
    _PostgresColumnPostcondition("media_credit_buckets", "status", "text", False),
    _PostgresColumnPostcondition("media_credit_buckets", "created_at", "timestamptz", False),
    _PostgresColumnPostcondition("media_credit_buckets", "updated_at", "timestamptz", False),
    _PostgresColumnPostcondition("media_credit_buckets", "bucket_json", "jsonb", False),
    _PostgresColumnPostcondition("external_execution_claims", "claim_id", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "company_id", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "store_id", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "confirmation_id", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "action_type", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "status", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "nonce_sha256", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "binding_json", "jsonb", False),
    _PostgresColumnPostcondition("external_execution_claims", "claimed_by", "text", False),
    _PostgresColumnPostcondition("external_execution_claims", "claimed_at", "timestamptz", False),
    _PostgresColumnPostcondition("external_execution_claims", "expires_at", "timestamptz", False),
    _PostgresColumnPostcondition("external_execution_claims", "consumed_at", "timestamptz", True),
    _PostgresColumnPostcondition("user_refresh_sessions", "session_id", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "current_token_hash", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "user_id", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "company_id", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "device_class", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "status", "text", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "created_at", "timestamptz", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "last_seen_at", "timestamptz", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "expires_epoch", "int8", False),
    _PostgresColumnPostcondition("user_refresh_sessions", "revoked_at", "timestamptz", True),
    _PostgresColumnPostcondition("user_refresh_token_history", "token_hash", "text", False),
    _PostgresColumnPostcondition("user_refresh_token_history", "session_id", "text", False),
    _PostgresColumnPostcondition("user_refresh_token_history", "generation", "int8", False),
    _PostgresColumnPostcondition("user_refresh_token_history", "status", "text", False),
    _PostgresColumnPostcondition("user_refresh_token_history", "issued_at", "timestamptz", False),
    _PostgresColumnPostcondition("user_refresh_token_history", "rotated_at", "timestamptz", True),
    _PostgresColumnPostcondition("user_refresh_token_history", "replayed_at", "timestamptz", True),
    _PostgresColumnPostcondition("user_refresh_token_history", "expires_epoch", "int8", False),
    _PostgresColumnPostcondition("user_sessions", "refresh_session_id", "text", True),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "reservation_id", "text", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "company_id", "text", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "period_key", "text", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "slot_number", "int4", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "route_scope", "text", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "baseline_used", "int4", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "status", "text", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "created_at", "timestamptz", False),
    _PostgresColumnPostcondition("platform_model_trial_reservations", "released_at", "timestamptz", True),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "company_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "store_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "project_key", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "source_report_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "candidate_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "revision", "int4", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "checkpoint_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_heads", "updated_at", "timestamptz", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "checkpoint_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "company_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "store_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "project_key", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "source_report_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "candidate_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "revision", "int4", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "mutation_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "payload_fingerprint", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "base_report_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "actor_user_id", "text", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "created_at", "timestamptz", False),
    _PostgresColumnPostcondition("listing_draft_edit_revisions", "receipt_json", "jsonb", False),
)


@dataclass(frozen=True)
class _PostgresIndexPostcondition:
    identifier: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class _PostgresConstraintPostcondition:
    identifier: str
    table_name: str
    constraint_type: str
    columns: tuple[str, ...]
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    constraint_name: str | None = None


POSTGRES_CRITICAL_INDEX_POSTCONDITIONS: tuple[_PostgresIndexPostcondition, ...] = (
    _PostgresIndexPostcondition(
        "idx_media_credit_buckets_company_status",
        "media_credit_buckets",
        ("company_id", "status", "expires_at"),
    ),
    _PostgresIndexPostcondition(
        "idx_user_refresh_sessions_owner",
        "user_refresh_sessions",
        ("user_id", "company_id", "status", "last_seen_at"),
    ),
    _PostgresIndexPostcondition(
        "idx_user_refresh_token_history_session",
        "user_refresh_token_history",
        ("session_id", "generation"),
    ),
    _PostgresIndexPostcondition(
        "idx_user_sessions_refresh_session",
        "user_sessions",
        ("refresh_session_id",),
    ),
)
POSTGRES_CRITICAL_CONSTRAINT_POSTCONDITIONS: tuple[_PostgresConstraintPostcondition, ...] = (
    _PostgresConstraintPostcondition(
        "listing_draft_edit_heads.scope_pk", "listing_draft_edit_heads", "p",
        ("company_id", "store_id", "project_key"),
    ),
    _PostgresConstraintPostcondition(
        "listing_draft_edit_revisions.checkpoint_pk", "listing_draft_edit_revisions", "p",
        ("checkpoint_id",),
    ),
    _PostgresConstraintPostcondition(
        "listing_draft_edit_revisions.scope_revision_unique", "listing_draft_edit_revisions", "u",
        ("company_id", "store_id", "project_key", "revision"),
    ),
    _PostgresConstraintPostcondition(
        "listing_draft_edit_revisions.scope_mutation_unique", "listing_draft_edit_revisions", "u",
        ("company_id", "store_id", "project_key", "mutation_id"),
    ),
    _PostgresConstraintPostcondition(
        "media_credit_buckets.company_fk",
        "media_credit_buckets",
        "f",
        ("company_id",),
        "companies",
        ("company_id",),
    ),
    _PostgresConstraintPostcondition(
        "media_credit_buckets.company_source_reference_unique",
        "media_credit_buckets",
        "u",
        ("company_id", "source_type", "source_reference_id"),
    ),
    _PostgresConstraintPostcondition(
        "user_sessions_refresh_session_id_fkey",
        "user_sessions",
        "f",
        ("refresh_session_id",),
        "user_refresh_sessions",
        ("session_id",),
        "user_sessions_refresh_session_id_fkey",
    ),
    _PostgresConstraintPostcondition(
        "platform_model_trial_reservations.company_fk",
        "platform_model_trial_reservations",
        "f",
        ("company_id",),
        "companies",
        ("company_id",),
    ),
    _PostgresConstraintPostcondition(
        "platform_model_trial_reservations.company_period_slot_unique",
        "platform_model_trial_reservations",
        "u",
        ("company_id", "period_key", "slot_number"),
    ),
)


@dataclass(frozen=True)
class _PostgresMigrationSpec:
    path: Path
    canonical_sha256: str
    migration_records: tuple[tuple[str, str], ...]
    bootstrap_schema_migrations: bool = False


POSTGRES_MIGRATION_MANIFEST: tuple[_PostgresMigrationSpec, ...] = (
    _PostgresMigrationSpec(
        path=POSTGRES_MIGRATION,
        canonical_sha256="d76293f426d20cdcc0a2667284900c8cb91606f26e464ff1a4e1b96e409444f6",
        migration_records=(
            ("20260515_001_initial_schema_postgres", "jiejing-saas-postgres-schema-v20260515"),
            ("20260713_domestic_billing_orders", "jiejing-domestic-billing-orders-v20260713"),
            ("20260714_media_credit_ledger", "jiejing-media-credit-ledger-v20260714"),
            ("20260613_billing_subscription_state", "jiejing-billing-subscription-state-v20260613"),
            ("20260617_worker_runtime_heartbeats", "jiejing-worker-runtime-heartbeats-v20260617"),
            ("20260701_media_asset_jobs", "jiejing-media-asset-jobs-v20260701"),
            ("20260711_ai_ceo_account_chat_history", "jiejing-ai-ceo-account-chat-history-v20260711"),
            ("20260714_platform_operations_metering", "jiejing-platform-operations-metering-v20260714"),
            (
                "20260714_platform_reliability_alert_lifecycle",
                "jiejing-platform-reliability-alert-lifecycle-v20260714",
            ),
            ("20260715_platform_trial_activations", "jiejing-platform-trial-activations-v20260715"),
            ("20260717_platform_provider_monitor_state", "jiejing-platform-provider-monitor-state-v20260717"),
            ("20260802_merchant_onboarding_states", "jiejing-merchant-onboarding-states-v20260802"),
            ("20260803_merchant_product_feedback", "jiejing-merchant-product-feedback-v20260803"),
        ),
        bootstrap_schema_migrations=True,
    ),
    _PostgresMigrationSpec(
        path=POSTGRES_MEDIA_CREDIT_BUCKETS_MIGRATION,
        canonical_sha256="791a9b941eb6ffe20c39a1ab3eeed8a30a4849f3bb72a4dd42f2e538751b4b5d",
        migration_records=(
            (
                "20260823_002_media_credit_buckets_postgres",
                "jiejing-media-credit-buckets-postgres-v20260823",
            ),
        ),
    ),
    _PostgresMigrationSpec(
        path=POSTGRES_RUNTIME_SCHEMA_RECONCILIATION_MIGRATION,
        canonical_sha256="b90afa8333e2fc5092416e86021232e76f3d22584687c5401925bb871510400d",
        migration_records=(
            (
                "20260823_003_runtime_schema_reconciliation_postgres",
                "jiejing-runtime-schema-reconciliation-postgres-v20260823",
            ),
        ),
    ),
    _PostgresMigrationSpec(
        path=POSTGRES_PLATFORM_MODEL_TRIAL_RESERVATIONS_MIGRATION,
        canonical_sha256="b3f5262101e5c4a4d7d1e9cd53d50a5b73ea9867e51de2f3d3ba1f5de9f5e211",
        migration_records=(
            (
                "20260901_004_platform_model_trial_reservations_postgres",
                "jiejing-platform-model-trial-reservations-postgres-v20260901",
            ),
        ),
    ),
    _PostgresMigrationSpec(
        path=POSTGRES_LISTING_DRAFT_EDIT_CHECKPOINTS_MIGRATION,
        canonical_sha256="8ed85821d1d52c01cd5d13919c94d420eb9372dd0974bb2d56d7f3748c05aa1c",
        migration_records=(
            (
                "20260906_005_listing_draft_edit_checkpoints_postgres",
                "jiejing-listing-draft-edit-checkpoints-postgres-v20260906",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class _LoadedPostgresMigration:
    path: Path
    sql: str
    migration_records: tuple[tuple[str, str], ...]
    required_relations: tuple[str, ...]
    bootstrap_schema_migrations: bool = False


def build_infrastructure_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    postgres = build_postgres_driver_status(settings)
    redis = build_redis_driver_status(settings)
    cutover_blockers = sorted(
        set(
            [
                *postgres.get("runtime_cutover_blockers", []),
                *redis.get("runtime_cutover_blockers", []),
            ]
        )
    )
    return {
        "contract_version": "2026-05-17-infrastructure-drivers",
        "postgres": postgres,
        "redis": redis,
        "ready_for_runtime_cutover": not cutover_blockers,
        "cutover_blockers": cutover_blockers,
        "secret_exposed": False,
    }


def build_postgres_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    dependency = _dependency_status("psycopg")
    live_check_requested = _env_bool("JIEJING_POSTGRES_DRIVER_CHECK_LIVE", default=False)
    live_check = _postgres_live_check(settings) if live_check_requested else {"status": "not_requested"}
    runtime_cutover_blockers: list[str] = []
    if settings.database_adapter != "postgres-managed" and settings.database_engine != "postgres":
        runtime_cutover_blockers.append("postgres_adapter_not_selected")
    if not settings.database_url_configured:
        runtime_cutover_blockers.append("missing_database_url")
    if not dependency["available"]:
        runtime_cutover_blockers.append("missing_psycopg_dependency")
    if not live_check_requested:
        runtime_cutover_blockers.append("postgres_live_check_not_requested")
    elif live_check.get("status") != "ok":
        runtime_cutover_blockers.append("postgres_live_check_failed")
    return {
        "key": "postgres",
        "selected": settings.database_adapter == "postgres-managed" or settings.database_engine == "postgres",
        "dependency": dependency,
        "database_url_configured": settings.database_url_configured,
        "database_url_public": _redact_url(os.environ.get("JIEJING_DATABASE_URL") or ""),
        "migration_file": str(POSTGRES_MIGRATION.relative_to(ROOT)),
        "migration_file_exists": POSTGRES_MIGRATION.exists(),
        "migration_manifest": [
            {
                "path": str(spec.path.relative_to(ROOT)),
                "exists": spec.path.is_file(),
                "migration_ids": [migration_id for migration_id, _checksum in spec.migration_records],
            }
            for spec in POSTGRES_MIGRATION_MANIFEST
        ],
        "migration_runner_implemented": True,
        "repository_runtime_switch_implemented": True,
        "live_check_requested": live_check_requested,
        "live_check": live_check,
        "runtime_cutover_blockers": runtime_cutover_blockers,
        "secret_exposed": False,
    }


def run_postgres_live_probe(settings: SaaSSettings) -> dict[str, Any]:
    """Run a redacted Postgres ``select 1`` probe for deep health checks."""

    if settings.database_engine != "postgres" and settings.database_adapter != "postgres-managed":
        return {
            "status": "not_required",
            "engine": settings.database_engine,
            "adapter": settings.database_adapter,
            "secret_exposed": False,
        }
    return _postgres_live_check(settings)


def build_redis_driver_status(settings: SaaSSettings) -> dict[str, Any]:
    dependency = _dependency_status("redis")
    live_check_requested = _env_bool("JIEJING_REDIS_DRIVER_CHECK_LIVE", default=False)
    live_check = _redis_live_check(settings) if live_check_requested else {"status": "not_requested"}
    runtime_cutover_blockers: list[str] = []
    if settings.queue_provider == "postgres_durable":
        return {
            "key": "redis_streams",
            "selected": False,
            "replaced_by": "postgres_durable",
            "dependency": dependency,
            "queue_url_configured": False,
            "queue_url_public": "",
            "stream_name": "",
            "dead_letter_stream": "",
            "connection_probe_implemented": True,
            "worker_runtime_switch_implemented": True,
            "runtime": {"status": "skipped_postgres_durable_queue", "secret_exposed": False},
            "live_check_requested": False,
            "live_check": {"status": "not_required_postgres_durable_queue"},
            "runtime_cutover_blockers": [],
            "secret_exposed": False,
        }
    if settings.queue_provider != "redis_streams":
        runtime_cutover_blockers.append("redis_streams_provider_not_selected")
    if not settings.queue_url_configured:
        runtime_cutover_blockers.append("missing_queue_url")
    if not dependency["available"]:
        runtime_cutover_blockers.append("missing_redis_dependency")
    if not live_check_requested:
        runtime_cutover_blockers.append("redis_live_check_not_requested")
    elif live_check.get("status") != "ok":
        runtime_cutover_blockers.append("redis_live_check_failed")
    runtime = redis_runtime_status(settings)
    return {
        "key": "redis_streams",
        "selected": settings.queue_provider == "redis_streams",
        "dependency": dependency,
        "queue_url_configured": settings.queue_url_configured,
        "queue_url_public": _redact_url(os.environ.get("JIEJING_QUEUE_URL") or ""),
        "stream_name": os.environ.get("JIEJING_REDIS_STREAM", "jiejing:queue"),
        "dead_letter_stream": os.environ.get("JIEJING_REDIS_DEAD_LETTER_STREAM", "jiejing:queue:dead"),
        "connection_probe_implemented": True,
        "worker_runtime_switch_implemented": True,
        "runtime": runtime,
        "live_check_requested": live_check_requested,
        "live_check": live_check,
        "runtime_cutover_blockers": runtime_cutover_blockers,
        "secret_exposed": False,
    }


def run_postgres_migration(*, database_url: str, migration_path: Path | None = None) -> dict[str, Any]:
    """Apply the trusted manifest, or one explicitly supplied migration, fail-closed.

    The session advisory lock deliberately surrounds both checksum preflight and
    DDL. A runner that waited for another process therefore re-reads the ledger
    and skips work that is already complete.
    """

    if not database_url:
        return _postgres_blocked("missing_database_url")
    migrations, contract_failure = _load_postgres_migrations(migration_path)
    if contract_failure is not None:
        return contract_failure
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return _postgres_blocked("missing_psycopg_dependency")

    outcome: dict[str, Any] | None = None
    lock_acquired = False
    unlock_succeeded = False
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=postgres_connect_timeout_seconds(),
            autocommit=True,
        ) as conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "select pg_advisory_lock(%s)",
                        (POSTGRES_MIGRATION_ADVISORY_LOCK_KEY,),
                    )
                    lock_acquired = True
                    outcome = _apply_postgres_migrations(cursor, migrations)
            except Exception as exc:
                _rollback_postgres_connection(conn)
                outcome = _postgres_failed(exc)
            finally:
                if lock_acquired:
                    unlock_succeeded = _release_postgres_migration_lock(conn)
    except Exception as exc:
        return _postgres_failed(exc)

    if lock_acquired and not unlock_succeeded:
        return _postgres_blocked("postgres_schema_migration_unlock_failed")
    return outcome or _postgres_blocked("postgres_schema_migration_failed")


def _postgres_live_check(settings: SaaSSettings) -> dict[str, Any]:
    database_url = os.environ.get("JIEJING_DATABASE_URL") or ""
    if not database_url:
        return _postgres_blocked("missing_database_url")
    migrations, contract_failure = _load_postgres_migrations(None)
    if contract_failure is not None:
        return contract_failure
    try:
        import psycopg  # type: ignore[import-not-found]
    except Exception:
        return _postgres_blocked("missing_psycopg_dependency")
    try:
        with psycopg.connect(database_url, connect_timeout=postgres_connect_timeout_seconds()) as conn:
            with conn.cursor() as cursor:
                cursor.execute("select 1")
                row = cursor.fetchone()
                schema_contract = _probe_postgres_schema_contract(cursor, migrations)
    except Exception as exc:
        return _postgres_failed(exc)
    if schema_contract.get("status") != "ok":
        return {
            "status": "blocked",
            "blocked_by": list(schema_contract.get("blocked_by") or ["postgres_schema_contract_failed"]),
            "schema_contract": schema_contract,
            "secret_exposed": False,
        }
    return {
        "status": "ok",
        "select_1": row[0] if row else None,
        "schema_contract": schema_contract,
        "secret_exposed": False,
    }


def _load_postgres_migrations(
    migration_path: Path | None,
) -> tuple[tuple[_LoadedPostgresMigration, ...], dict[str, Any] | None]:
    if migration_path is None:
        loaded: list[_LoadedPostgresMigration] = []
        for spec in POSTGRES_MIGRATION_MANIFEST:
            migration, failure = _load_trusted_postgres_migration(spec)
            if failure is not None:
                return (), failure
            if migration is not None:
                loaded.append(migration)
        return tuple(loaded), None

    path = Path(migration_path)
    for spec in POSTGRES_MIGRATION_MANIFEST:
        if path.resolve(strict=False) == spec.path.resolve(strict=False):
            migration, failure = _load_trusted_postgres_migration(spec)
            return ((migration,) if migration is not None else ()), failure
    if not path.is_file():
        return (), _postgres_blocked("missing_migration_file")
    try:
        sql = path.read_text(encoding="utf-8")
    except Exception as exc:
        return (), _postgres_failed(exc, blocker="unreadable_migration_file")
    records = _postgres_migration_records(sql)
    if not records:
        return (), _postgres_blocked("invalid_migration_contract")
    required_relations = _postgres_required_relations(sql)
    return (
        _LoadedPostgresMigration(
            path=path,
            sql=sql,
            migration_records=records,
            required_relations=required_relations,
            bootstrap_schema_migrations="schema_migrations" in required_relations,
        ),
    ), None


def _load_trusted_postgres_migration(
    spec: _PostgresMigrationSpec,
) -> tuple[_LoadedPostgresMigration | None, dict[str, Any] | None]:
    migration_ids = [migration_id for migration_id, _checksum in spec.migration_records]
    if not spec.path.is_file():
        return None, _trusted_postgres_contract_failure(
            "postgres_schema_trusted_migration_missing",
            migration_ids,
        )
    try:
        sql = spec.path.read_text(encoding="utf-8")
    except Exception:
        return None, _trusted_postgres_contract_failure(
            "postgres_schema_trusted_migration_unreadable",
            migration_ids,
        )
    if _canonical_text_sha256(sql) != spec.canonical_sha256:
        return None, _trusted_postgres_contract_failure(
            "postgres_schema_trusted_migration_content_drift",
            migration_ids,
        )
    records = _postgres_migration_records(sql)
    if records != spec.migration_records:
        return None, _trusted_postgres_contract_failure(
            "postgres_schema_trusted_migration_contract_drift",
            migration_ids,
        )
    required_relations = _postgres_required_relations(sql)
    if not required_relations:
        return None, _trusted_postgres_contract_failure(
            "postgres_schema_trusted_migration_contract_invalid",
            migration_ids,
        )
    return (
        _LoadedPostgresMigration(
            path=spec.path,
            sql=sql,
            migration_records=records,
            required_relations=required_relations,
            bootstrap_schema_migrations=spec.bootstrap_schema_migrations,
        ),
        None,
    )


def _apply_postgres_migrations(
    cursor: Any,
    migrations: tuple[_LoadedPostgresMigration, ...],
) -> dict[str, Any]:
    applied_ids: list[str] = []
    skipped_ids: list[str] = []
    for migration in migrations:
        expected = dict(migration.migration_records)
        if migration.bootstrap_schema_migrations and not _postgres_relation_exists(cursor, "schema_migrations"):
            existing: dict[str, str] = {}
        else:
            existing = _postgres_migration_ledger(cursor)
        drifted = sorted(
            migration_id
            for migration_id, checksum in expected.items()
            if migration_id in existing and existing[migration_id] != checksum
        )
        if drifted:
            return _migration_drift_failure(drifted)
        missing = sorted(migration_id for migration_id in expected if migration_id not in existing)
        if not missing:
            skipped_ids.extend(expected)
            continue

        cursor.execute(migration.sql)
        verified = _postgres_migration_ledger(cursor)
        drifted_after = sorted(
            migration_id
            for migration_id, checksum in expected.items()
            if migration_id in verified and verified[migration_id] != checksum
        )
        if drifted_after:
            return _migration_drift_failure(drifted_after)
        still_missing = sorted(migration_id for migration_id in expected if migration_id not in verified)
        if still_missing:
            return {
                "status": "blocked",
                "blocked_by": ["postgres_schema_migration_record_missing"],
                "migration_ids": still_missing,
                "secret_exposed": False,
            }
        applied_ids.extend(missing)

    return {
        "status": "ok",
        "applied_migration_ids": applied_ids,
        "skipped_migration_ids": skipped_ids,
        "secret_exposed": False,
    }


def _probe_postgres_schema_contract(
    cursor: Any,
    migrations: tuple[_LoadedPostgresMigration, ...],
) -> dict[str, Any]:
    required_relations = sorted(
        {
            relation
            for migration in migrations
            for relation in migration.required_relations
        }
    )
    present_relations = _postgres_public_relations(cursor, required_relations)
    missing_relations = sorted(set(required_relations) - present_relations)
    if missing_relations:
        return {
            "status": "blocked",
            "blocked_by": ["postgres_schema_missing_relations"],
            "missing_relations": missing_relations,
            "secret_exposed": False,
        }

    expected = {
        migration_id: checksum
        for migration in migrations
        for migration_id, checksum in migration.migration_records
    }
    existing = _postgres_migration_ledger(cursor)
    drifted = sorted(
        migration_id
        for migration_id, checksum in expected.items()
        if migration_id in existing and existing[migration_id] != checksum
    )
    if drifted:
        return {
            "status": "blocked",
            "blocked_by": ["postgres_schema_migration_checksum_drift"],
            "checksum_drift_migration_ids": drifted,
            "secret_exposed": False,
        }
    missing_migrations = sorted(migration_id for migration_id in expected if migration_id not in existing)
    if missing_migrations:
        return {
            "status": "blocked",
            "blocked_by": ["postgres_schema_missing_migrations"],
            "missing_migration_ids": missing_migrations,
            "secret_exposed": False,
        }

    missing_columns, missing_indexes, missing_constraints = _postgres_missing_critical_postconditions(cursor)
    if missing_columns or missing_indexes or missing_constraints:
        return {
            "status": "blocked",
            "blocked_by": ["postgres_schema_missing_postconditions"],
            "missing_columns": missing_columns,
            "missing_indexes": missing_indexes,
            "missing_constraints": missing_constraints,
            "secret_exposed": False,
        }
    return {
        "status": "ok",
        "required_relation_count": len(required_relations),
        "required_migration_count": len(expected),
        "critical_postcondition_count": (
            len(POSTGRES_CRITICAL_COLUMN_POSTCONDITIONS)
            + len(POSTGRES_CRITICAL_INDEX_POSTCONDITIONS)
            + len(POSTGRES_CRITICAL_CONSTRAINT_POSTCONDITIONS)
        ),
        "secret_exposed": False,
    }


def _postgres_migration_ledger(cursor: Any) -> dict[str, str]:
    cursor.execute("select migration_id, checksum from schema_migrations")
    return {
        str(migration_id): str(checksum)
        for migration_id, checksum in cursor.fetchall()
    }


def _postgres_public_relations(cursor: Any, required_relations: list[str]) -> set[str]:
    cursor.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema = 'public'
          and table_type = 'BASE TABLE'
          and table_name::text = any(%s)
        """,
        (required_relations,),
    )
    return {str(row[0]) for row in cursor.fetchall() if row and row[0]}


def _postgres_missing_critical_postconditions(
    cursor: Any,
) -> tuple[list[str], list[str], list[str]]:
    critical_tables = sorted(
        {postcondition.table_name for postcondition in POSTGRES_CRITICAL_COLUMN_POSTCONDITIONS}
    )
    cursor.execute(
        """
        select table_name, column_name, data_type, udt_name, is_nullable
        from information_schema.columns
        where table_schema = 'public'
          and table_name::text = any(%s)
        """,
        (critical_tables,),
    )
    present_columns = {
        (str(table_name), str(column_name)): (
            str(data_type),
            str(udt_name),
            str(is_nullable),
        )
        for table_name, column_name, data_type, udt_name, is_nullable in cursor.fetchall()
    }

    cursor.execute(
        """
        select
          idx_rel.relname as index_name,
          table_rel.relname as table_name,
          am.amname as access_method,
          idx.indisunique as is_unique,
          idx.indisvalid as is_valid,
          idx.indisready as is_ready,
          idx.indislive as is_live,
          pg_catalog.pg_get_indexdef(idx.indexrelid) as index_definition
        from pg_index idx
        join pg_class idx_rel on idx_rel.oid = idx.indexrelid
        join pg_namespace idx_nsp on idx_nsp.oid = idx_rel.relnamespace
        join pg_class table_rel on table_rel.oid = idx.indrelid
        join pg_namespace table_nsp on table_nsp.oid = table_rel.relnamespace
        join pg_am am on am.oid = idx_rel.relam
        where idx_nsp.nspname = 'public'
          and table_nsp.nspname = 'public'
          and idx_rel.relname::text = any(%s)
          and idx.indnkeyatts = idx.indnatts
          and idx.indexprs is null
          and idx.indpred is null
        """,
        ([postcondition.identifier for postcondition in POSTGRES_CRITICAL_INDEX_POSTCONDITIONS],),
    )
    present_indexes = {
        str(index_name): (
            str(table_name),
            str(access_method),
            bool(is_unique),
            bool(is_valid),
            bool(is_ready),
            bool(is_live),
            str(index_definition),
        )
        for (
            index_name,
            table_name,
            access_method,
            is_unique,
            is_valid,
            is_ready,
            is_live,
            index_definition,
        ) in cursor.fetchall()
    }

    cursor.execute(
        """
        select con.conname, rel.relname, con.contype, pg_get_constraintdef(con.oid)
        from pg_constraint con
        join pg_class rel on rel.oid = con.conrelid
        join pg_namespace nsp on nsp.oid = rel.relnamespace
        where nsp.nspname = 'public'
          and con.contype in ('f', 'u', 'p')
          and rel.relname::text = any(%s)
        """,
        (
            sorted(
                {postcondition.table_name for postcondition in POSTGRES_CRITICAL_CONSTRAINT_POSTCONDITIONS}
            ),
        ),
    )
    present_constraints = [
        (str(constraint_name), str(table_name), str(constraint_type), str(constraint_definition))
        for constraint_name, table_name, constraint_type, constraint_definition in cursor.fetchall()
    ]

    missing_columns = sorted(
        postcondition.identifier
        for postcondition in POSTGRES_CRITICAL_COLUMN_POSTCONDITIONS
        if not _postgres_column_postcondition_matches(
            postcondition,
            present_columns.get((postcondition.table_name, postcondition.column_name)),
        )
    )
    missing_indexes = sorted(
        postcondition.identifier
        for postcondition in POSTGRES_CRITICAL_INDEX_POSTCONDITIONS
        if not _postgres_index_postcondition_matches(
            postcondition,
            present_indexes.get(postcondition.identifier),
        )
    )
    missing_constraints = sorted(
        postcondition.identifier
        for postcondition in POSTGRES_CRITICAL_CONSTRAINT_POSTCONDITIONS
        if not any(
            _postgres_constraint_postcondition_matches(postcondition, candidate)
            for candidate in present_constraints
        )
    )
    return missing_columns, missing_indexes, missing_constraints


def _postgres_index_postcondition_matches(
    postcondition: _PostgresIndexPostcondition,
    candidate: tuple[str, str, bool, bool, bool, bool, str] | None,
) -> bool:
    if candidate is None:
        return False
    table_name, access_method, is_unique, is_valid, is_ready, is_live, index_definition = candidate
    if not (
        table_name == postcondition.table_name
        and access_method == "btree"
        and not is_unique
        and is_valid
        and is_ready
        and is_live
    ):
        return False
    normalized = _normalize_postgres_catalog_definition(index_definition)
    match = re.fullmatch(
        r"create\s+(unique\s+)?index\s+\S+\s+on\s+(?:public\.)?\S+\s+"
        r"using\s+btree\s*\(([^()]*)\)",
        normalized,
    )
    return bool(
        match
        and not match.group(1)
        and _plain_postgres_identifier_list(match.group(2)) == postcondition.columns
    )


def _postgres_column_postcondition_matches(
    postcondition: _PostgresColumnPostcondition,
    candidate: tuple[str, str, str] | None,
) -> bool:
    if candidate is None:
        return False
    data_type, udt_name, is_nullable = candidate
    expected_data_type = {
        "int4": "integer",
        "int8": "bigint",
        "timestamptz": "timestamp with time zone",
    }.get(postcondition.udt_name, postcondition.udt_name)
    return bool(
        data_type == expected_data_type
        and udt_name == postcondition.udt_name
        and is_nullable == ("YES" if postcondition.nullable else "NO")
    )


def _postgres_constraint_postcondition_matches(
    postcondition: _PostgresConstraintPostcondition,
    candidate: tuple[str, str, str, str],
) -> bool:
    constraint_name, table_name, constraint_type, constraint_definition = candidate
    if table_name != postcondition.table_name or constraint_type != postcondition.constraint_type:
        return False
    if postcondition.constraint_name is not None and constraint_name != postcondition.constraint_name:
        return False

    normalized = _normalize_postgres_catalog_definition(constraint_definition)
    if postcondition.constraint_type in {"u", "p"}:
        label = "unique" if postcondition.constraint_type == "u" else "primary key"
        match = re.fullmatch(rf"{label}\s*\(([^()]*)\)", normalized)
        return bool(match and _plain_postgres_identifier_list(match.group(1)) == postcondition.columns)
    if postcondition.constraint_type != "f":
        return False
    match = re.fullmatch(
        r"foreign\s+key\s*\(([^()]*)\)\s+references\s+"
        r"(?:public\.)?([a-z_][a-z0-9_]*)\s*\(([^()]*)\)",
        normalized,
    )
    return bool(
        match
        and _plain_postgres_identifier_list(match.group(1)) == postcondition.columns
        and match.group(2) == postcondition.referenced_table
        and _plain_postgres_identifier_list(match.group(3)) == postcondition.referenced_columns
    )


def _normalize_postgres_catalog_definition(definition: str) -> str:
    return " ".join(str(definition).lower().split())


def _plain_postgres_identifier_list(value: str) -> tuple[str, ...]:
    identifiers = tuple(part.strip() for part in str(value).split(","))
    if not identifiers or any(not re.fullmatch(r"[a-z_][a-z0-9_]*", item) for item in identifiers):
        return ()
    return identifiers


def _postgres_relation_exists(cursor: Any, relation: str) -> bool:
    cursor.execute("select to_regclass(%s)", (f"public.{relation}",))
    row = cursor.fetchone()
    return bool(row and row[0])


def _release_postgres_migration_lock(conn: Any) -> bool:
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "select pg_advisory_unlock(%s)",
                (POSTGRES_MIGRATION_ADVISORY_LOCK_KEY,),
            )
            row = cursor.fetchone()
        return bool(row and row[0] is True)
    except Exception:
        return False


def _rollback_postgres_connection(conn: Any) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        try:
            rollback()
        except Exception:
            pass


def _postgres_migration_records(sql: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        re.findall(
            r"insert\s+into\s+schema_migrations.*?values\s*\(\s*'([^']+)'\s*,\s*'([^']+)'",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _postgres_required_relations(sql: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            re.findall(
                r"create\s+table\s+if\s+not\s+exists\s+([a-z_][a-z0-9_]*)",
                sql,
                flags=re.IGNORECASE,
            )
        )
    )


def _canonical_text_sha256(text: str) -> str:
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _migration_drift_failure(migration_ids: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "blocked_by": ["postgres_schema_migration_checksum_drift"],
        "secret_exposed": False,
    }
    if len(migration_ids) == 1:
        result["migration_id"] = migration_ids[0]
    else:
        result["migration_ids"] = migration_ids
    return result


def _trusted_postgres_contract_failure(blocker: str, migration_ids: list[str]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blocked_by": [blocker],
        "schema_contract": {
            "status": "blocked",
            "migration_ids": migration_ids,
            "secret_exposed": False,
        },
        "secret_exposed": False,
    }


def _postgres_blocked(blocker: str) -> dict[str, Any]:
    return {"status": "blocked", "blocked_by": [blocker], "secret_exposed": False}


def _postgres_failed(exc: BaseException, *, blocker: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "failed",
        "error_type": exc.__class__.__name__,
        "secret_exposed": False,
    }
    if blocker:
        result["blocked_by"] = [blocker]
    return result


def _redis_live_check(settings: SaaSSettings) -> dict[str, Any]:
    queue_url = os.environ.get("JIEJING_QUEUE_URL") or ""
    if not queue_url:
        return {"status": "blocked", "blocked_by": ["missing_queue_url"], "secret_exposed": False}
    try:
        import redis  # type: ignore[import-not-found]
    except Exception:
        return {"status": "blocked", "blocked_by": ["missing_redis_dependency"], "secret_exposed": False}
    try:
        client = redis.Redis.from_url(queue_url, socket_connect_timeout=5, socket_timeout=5)
        pong = client.ping()
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "message": str(exc)[:240],
            "queue_url_public": _redact_url(queue_url),
            "secret_exposed": False,
        }
    return {"status": "ok", "ping": bool(pong), "queue_url_public": _redact_url(queue_url), "secret_exposed": False}


def _dependency_status(module_name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    return {
        "module": module_name,
        "available": spec is not None,
        "status": "available" if spec is not None else "missing_python_dependency",
    }


def _redact_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        username = userinfo.split(":", 1)[0]
        netloc = f"{username}:***@{host}" if username else f"***@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
