"""SQLite repository for the formal Jiejing SaaS backend MVP."""

from __future__ import annotations

import base64
import json
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from jiejing_runtime.models import now_iso

from .json_safe import json_default
from .operations_metering import (
    ANALYTICS_EVENT_KEYS,
    ANALYTICS_PAGE_KEYS,
    PROVIDER_MONITOR_AGGREGATE_KEYS,
    PROVIDER_TELEMETRY_SCOPES,
    build_reliability_alert_summary,
    reconcile_reliability_alert_state,
)
from .permissions import permissions_for_role, valid_role
from .postgres_repository_runtime import connect_postgres_repository
from .security import hash_password, verify_password


# Fixed PBKDF2 record used only to equalize unknown-account login work. It is
# not a credential and never authenticates a user.
AUTH_DUMMY_PASSWORD_SALT = "jiejing-auth-dummy-salt-v1"
AUTH_DUMMY_PASSWORD_HASH = "0fed6ff3d46dfba00b7f3f1a00a1b3ce6d0331d0cfbab025aea32467b26c97f7"
from .workflow_plan import step_status_from_runtime


HIGH_RISK_ACTIONS = {
    "ebay_oauth_scope_change",
    "publish_listing",
    "bulk_publish_listing",
    "revise_listing",
    "change_price",
    "change_inventory",
    "open_ad_campaign",
    "change_ad_budget",
    "refund",
    "partial_refund",
    "procurement_payment",
    "purchase_order",
    "cleanup_test_listing",
    "change_shipping_policy",
    "change_payment_policy",
    "change_return_policy",
    "sensitive_customer_reply",
}


ACTIVE_SECRET_REF_STATUSES = {
    "active",
    "ready",
    "stored",
    "managed_vault_stored",
    "local_secret_resolver_stored",
}


ACTIVE_MODEL_SECRET_REF_STATUSES = {
    "active",
    "ready",
    "stored",
    "managed_vault_stored",
    "local_development_secret_stored",
}


MERCHANT_CEO_COMMAND_MEMORY_TYPE = "merchant_ceo_command"
MERCHANT_CEO_COMMAND_SOURCE_TYPE = "merchant_ceo_command"
MERCHANT_RULE_MEMORY_TYPE = "merchant_rule"
AI_CEO_TRANSIENT_MEMORY_POLICY = "transient_no_long_term_memory"
AI_CEO_OPERATING_MEMORY_POLICY = "permanent_operating_memory"
AI_CEO_RULE_MEMORY_POLICY = "merchant_rule"
AI_CEO_MARKET_REPORT_CONTRACT_VERSION = "2026-07-04-ai-ceo-market-report-frontstage-v2"
AI_CEO_MARKET_LISTING_HANDOFF_CONTRACT_VERSION = "2026-07-04-ai-ceo-market-to-listing-handoff-v2"
AI_CEO_MARKET_EBAY_FIELD_MAP_CONTRACT = "ai_ceo_market_research_to_ebay_inventory_offer_v1"
_DOMESTIC_BILLING_COMPANY_LOCKS = tuple(threading.Lock() for _ in range(128))
_MEDIA_CREDIT_COMPANY_LOCKS = tuple(threading.Lock() for _ in range(128))
_PLATFORM_RELIABILITY_ALERT_LOCK = threading.Lock()
ACCOUNT_CLASSIFICATION_MERCHANT = "merchant"
ACCOUNT_CLASSIFICATION_SYNTHETIC_TEST = "synthetic_test"
_SYNTHETIC_ACCOUNT_DOMAINS = {"example.com", "example.test", "jiejing.local", "local.invalid"}
REAL_MERCHANT_VALIDATION_REQUIRED_COMPANIES = 3
REAL_MERCHANT_VALIDATION_REQUIRED_PATHS = 20
_NON_COMMERCIAL_BILLING_PROVIDERS = {"manual_beta", "stripe_test_mock"}


def _operations_short_ref(scope: str, value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(f"jiejing-ops|{scope}|{normalized}".encode("utf-8")).hexdigest()[:12]


def _operations_mask_email(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    local, separator, domain = normalized.partition("@")
    if not separator or not local or not domain:
        return ""
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * min(max(len(local) - len(visible), 3), 8)}@{domain}"


def _operations_cursor_offset(cursor: Any) -> int:
    normalized = str(cursor or "").strip()
    if not normalized:
        return 0
    try:
        padding = "=" * (-len(normalized) % 4)
        decoded = base64.urlsafe_b64decode(f"{normalized}{padding}".encode("ascii")).decode("ascii")
        version, raw_offset = decoded.split(":", 1)
        if version != "v1":
            return 0
        return min(max(int(raw_offset), 0), 5000)
    except (ValueError, UnicodeError, OSError):
        return 0


def _operations_next_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"v1:{max(0, int(offset))}".encode("ascii")).decode("ascii").rstrip("=")


def _account_classification_for_email(email: str) -> str:
    domain = str(email or "").strip().lower().partition("@")[2]
    return (
        ACCOUNT_CLASSIFICATION_SYNTHETIC_TEST
        if domain in _SYNTHETIC_ACCOUNT_DOMAINS
        else ACCOUNT_CLASSIFICATION_MERCHANT
    )


class SaaSRepository:
    def __init__(self, db_path: Path, *, database_engine: str | None = None, database_url: str | None = None) -> None:
        self.db_path = db_path
        self.database_engine = (database_engine or os.environ.get("JIEJING_DATABASE_ENGINE") or "sqlite").strip().lower() or "sqlite"
        self.database_url = database_url if database_url is not None else os.environ.get("JIEJING_DATABASE_URL", "")
        self._postgres_initialized = False
        self._postgres_initialize_lock = threading.Lock()

    def initialize(self) -> None:
        if self.database_engine == "postgres":
            self._initialize_postgres()
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists users (
                  user_id text primary key,
                  email text not null unique,
                  password_salt text not null,
                  password_hash text not null,
                  status text not null,
                  default_company_id text not null,
                  account_classification text not null default 'merchant',
                  created_at text not null
                );

                create table if not exists platform_trial_activations (
                  company_id text primary key,
                  user_id text not null,
                  status text not null,
                  activated_at text,
                  updated_at text not null,
                  activation_json text not null
                );

                create table if not exists user_sessions (
                  jti text primary key,
                  user_id text not null,
                  company_id text not null,
                  issued_at_epoch integer not null,
                  expires_epoch integer not null,
                  revoked_at text,
                  created_at text not null
                );

                create table if not exists companies (
                  company_id text primary key,
                  name text not null,
                  created_at text not null
                );

                create table if not exists team_members (
                  company_id text not null,
                  user_id text not null,
                  role text not null,
                  created_at text not null,
                  primary key (company_id, user_id)
                );

                create table if not exists team_invitations (
                  invitation_id text primary key,
                  company_id text not null,
                  email text not null,
                  role text not null,
                  status text not null,
                  invited_by text not null,
                  created_at text not null,
                  accepted_at text,
                  invite_json text not null
                );

                create table if not exists stores (
                  store_id text primary key,
                  company_id text not null,
                  platform text not null,
                  store_name text not null,
                  marketplace text not null,
                  stage text not null,
                  created_by text not null,
                  created_at text not null,
                  store_json text not null
                );

                create table if not exists secret_refs (
                  secret_ref text primary key,
                  company_id text not null,
                  store_id text,
                  provider text not null,
                  purpose text not null,
                  status text not null,
                  created_by text not null,
                  created_at text not null,
                  metadata_json text not null
                );

                create table if not exists platform_connections (
                  connection_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  platform text not null,
                  connection_type text not null,
                  status text not null,
                  scopes_json text not null,
                  secret_ref text,
                  metadata_json text not null,
                  created_by text not null,
                  created_at text not null
                );

                create table if not exists oauth_authorization_requests (
                  oauth_request_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  platform text not null,
                  status text not null,
                  state_nonce text not null,
                  scopes_json text not null,
                  auth_url text,
                  created_by text not null,
                  created_at text not null,
                  updated_at text not null,
                  request_json text not null
                );

                create table if not exists platform_data_packets (
                  packet_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  platform text not null,
                  packet_type text not null,
                  source_mode text not null,
                  status text not null,
                  created_by text not null,
                  created_at text not null,
                  expires_at text,
                  packet_json text not null
                );

                create table if not exists tasks (
                  task_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  user_id text not null,
                  runtime_run_id text,
                  task_type text not null,
                  title text not null,
                  status text not null,
                  created_at text not null,
                  updated_at text not null,
                  input_json text not null,
                  output_json text not null
                );

                create table if not exists queue_jobs (
                  job_id text primary key,
                  task_id text not null,
                  company_id text not null,
                  status text not null,
                  attempts integer not null,
                  max_attempts integer not null,
                  created_at text not null,
                  updated_at text not null,
                  job_json text not null
                );

                create table if not exists media_asset_jobs (
                  media_job_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  task_id text not null,
                  queue_job_id text,
                  provider_job_key text not null,
                  status text not null,
                  idempotency_key text not null,
                  retry_count integer not null,
                  error_reason text,
                  created_by text not null,
                  created_at text not null,
                  updated_at text not null,
                  media_job_json text not null,
                  unique (company_id, idempotency_key)
                );

                create table if not exists media_rework_reservations (
                  reservation_key_hash text primary key,
                  company_id text not null,
                  parent_media_job_id text not null,
                  version integer not null,
                  status text not null,
                  media_job_id text,
                  created_at text not null,
                  updated_at text not null,
                  expires_epoch integer not null,
                  unique (company_id, parent_media_job_id, version)
                );

                create table if not exists worker_runtime_heartbeats (
                  worker_id text primary key,
                  status text not null,
                  queue_provider text not null,
                  current_job_id text,
                  heartbeat_at text not null,
                  updated_at text not null,
                  heartbeat_json text not null
                );

                create table if not exists task_steps (
                  step_id text primary key,
                  task_id text not null,
                  company_id text not null,
                  store_id text not null,
                  step_order integer not null,
                  task_type text not null,
                  depends_on_task_type text,
                  role_key text not null,
                  merchant_label text not null,
                  status text not null,
                  attempts integer not null,
                  max_attempts integer not null,
                  timeout_seconds integer not null,
                  created_at text not null,
                  updated_at text not null,
                  started_at text,
                  finished_at text,
                  runtime_task_id text,
                  last_error text,
                  step_json text not null,
                  unique (task_id, task_type)
                );

                create table if not exists reports (
                  report_id text primary key,
                  task_id text not null,
                  runtime_run_id text not null,
                  report_type text not null,
                  title text not null,
                  status text not null,
                  created_at text not null,
                  report_json text not null
                );

                create table if not exists confirmations (
                  confirmation_id text primary key,
                  company_id text not null,
                  store_id text,
                  task_id text,
                  runtime_run_id text not null,
                  action_type text not null,
                  title text not null,
                  status text not null,
                  default_action text not null,
                  created_at text not null,
                  item_json text not null,
                  decided_by text,
                  decided_at text,
                  decision_note text
                );

                create table if not exists merchant_memory (
                  memory_id text primary key,
                  company_id text not null,
                  store_id text,
                  memory_type text not null,
                  source_type text not null,
                  source_id text not null,
                  title text not null,
                  summary text not null,
                  importance integer not null,
                  tags_json text not null,
                  memory_json text not null,
                  created_by text,
                  created_at text not null,
                  updated_at text not null,
                  unique (company_id, source_type, source_id, memory_type)
                );

                create table if not exists merchant_ceo_commands (
                  command_id text primary key,
                  company_id text not null,
                  store_id text not null,
                  user_id text,
                  status text not null,
                  route text not null,
                  memory_policy text not null,
                  created_at text not null,
                  updated_at text not null,
                  command_json text not null
                );

                create table if not exists ai_ceo_chat_turns (
                  chat_turn_id text primary key,
                  company_id text not null,
                  user_id text not null,
                  store_id text,
                  assistant_id text not null,
                  status text not null,
                  route text not null,
                  merge_score integer not null default 0,
                  created_at text not null,
                  updated_at text not null,
                  turn_json text not null,
                  unique (company_id, user_id, assistant_id)
                );

                create table if not exists execution_results (
                  execution_id text primary key,
                  confirmation_id text not null,
                  task_id text not null,
                  action_type text not null,
                  status text not null,
                  created_at text not null,
                  result_json text not null
                );

                create table if not exists audit_logs (
                  audit_id text primary key,
                  company_id text not null,
                  store_id text,
                  user_id text,
                  actor_type text not null,
                  action_type text not null,
                  target_type text not null,
                  target_id text,
                  summary text not null,
                  created_at text not null,
                  audit_json text not null
                );

                create table if not exists billing_subscriptions (
                  company_id text primary key,
                  provider text not null,
                  provider_customer_id text,
                  provider_subscription_id text,
                  plan_key text not null,
                  provider_plan_id text,
                  status text not null,
                  entitlement_active integer not null,
                  payment_attention_required integer not null,
                  updated_at text not null,
                  subscription_json text not null
                );

                create table if not exists billing_webhook_events (
                  event_key text primary key,
                  company_id text,
                  provider text not null,
                  event_type text not null,
                  status text not null,
                  created_at text not null,
                  billing_event_json text not null
                );

                create table if not exists billing_orders (
                  order_id text primary key,
                  company_id text not null,
                  user_id text not null,
                  provider text not null,
                  provider_order_id text,
                  plan_key text not null,
                  amount_minor integer not null,
                  currency text not null,
                  duration_days integer not null,
                  status text not null,
                  idempotency_key_hash text not null,
                  expires_at text,
                  paid_at text,
                  created_at text not null,
                  updated_at text not null,
                  order_json text not null,
                  unique (company_id, idempotency_key_hash)
                );

                create table if not exists media_credit_accounts (
                  company_id text primary key,
                  balance_points integer not null,
                  reserved_points integer not null,
                  lifetime_granted_points integer not null,
                  lifetime_spent_points integer not null,
                  updated_at text not null,
                  account_json text not null
                );

                create table if not exists media_credit_ledger (
                  ledger_id text primary key,
                  company_id text not null,
                  user_id text,
                  operation_type text not null,
                  points integer not null,
                  status text not null,
                  reference_type text not null,
                  reference_id text not null,
                  reservation_id text,
                  idempotency_key_hash text not null,
                  created_at text not null,
                  updated_at text not null,
                  ledger_json text not null,
                  unique (company_id, idempotency_key_hash)
                );

                create table if not exists platform_analytics_events (
                  analytics_event_id text primary key,
                  event_id_hash text not null unique,
                  company_id text,
                  user_id text,
                  event_key text not null,
                  page_key text not null,
                  visitor_hash text,
                  session_hash text,
                  occurred_at text not null,
                  analytics_json text not null
                );

                create table if not exists model_usage_ledger (
                  usage_id text primary key,
                  company_id text not null,
                  user_id text,
                  task_id text,
                  usage_owner text not null,
                  model_family text not null,
                  model_label text not null,
                  request_count integer not null,
                  input_tokens integer not null,
                  output_tokens integer not null,
                  total_tokens integer not null,
                  cost_minor integer not null,
                  currency text not null,
                  cost_status text not null,
                  idempotency_key_hash text not null unique,
                  created_at text not null,
                  usage_json text not null
                );

                create table if not exists provider_cost_ledger (
                  cost_id text primary key,
                  company_id text not null,
                  user_id text,
                  task_id text,
                  reference_type text not null,
                  reference_id text not null,
                  cost_category text not null,
                  resource_type text not null,
                  unit_count integer not null,
                  media_points integer not null,
                  cost_minor integer not null,
                  currency text not null,
                  cost_status text not null,
                  idempotency_key_hash text not null unique,
                  created_at text not null,
                  cost_json text not null
                );

                create table if not exists platform_reliability_alert_state (
                  alert_scope text primary key,
                  lifecycle_status text not null,
                  severity text not null,
                  observed_status text not null,
                  consecutive_breach_count integer not null,
                  consecutive_healthy_count integer not null,
                  fingerprint text not null,
                  opened_at text,
                  recovered_at text,
                  acknowledged_at text,
                  acknowledged_by text,
                  acknowledgement_action text,
                  last_evaluated_at text not null,
                  updated_at text not null,
                  state_json text not null
                );

                create table if not exists platform_reliability_alert_events (
                  event_id text primary key,
                  alert_scope text not null,
                  transition_key text not null,
                  severity text not null,
                  fingerprint text not null,
                  action_key text not null,
                  actor_user_id text,
                  created_at text not null,
                  event_json text not null,
                  unique (alert_scope, transition_key, fingerprint, action_key)
                );

                create table if not exists platform_provider_monitor_state (
                  scheduler_key text primary key,
                  lease_owner_hash text not null,
                  lease_expires_at_epoch integer not null,
                  last_evaluated_at text,
                  last_exported_at text,
                  last_outcome text not null,
                  snapshot_json text not null,
                  updated_at text not null
                );

                create table if not exists ebay_account_deletion_events (
                  event_key text primary key,
                  company_id text,
                  store_id text,
                  connection_id text,
                  task_id text,
                  job_id text,
                  status text not null,
                  created_at text not null,
                  updated_at text not null,
                  deletion_event_json text not null
                );

                create table if not exists api_rate_limit_buckets (
                  bucket_key_hash text primary key,
                  scope text not null,
                  request_count integer not null,
                  limit_count integer not null,
                  window_started_epoch integer not null,
                  expires_epoch integer not null
                );

                create table if not exists schema_migrations (
                  migration_id text primary key,
                  applied_at text not null,
                  checksum text not null,
                  summary text not null
                );
                """
            )
            self._ensure_user_account_classification(conn)
            self._ensure_ai_ceo_chat_merge_score_column(conn)
            self._ensure_account_scoped_confirmations(conn)
            self._ensure_indexes(conn)
            self._record_schema_migration(
                conn,
                migration_id="20260515_initial_sqlite_mvp_with_indexes",
                checksum="jiejing-saas-mvp-schema-v20260515-indexed",
                summary="Initial local SaaS MVP schema with tenant, task, report, confirmation, audit, OAuth, data packet and index boundaries.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260613_billing_subscription_state",
                checksum="jiejing-billing-subscription-state-v20260613",
                summary="Adds paid billing subscription state and sanitized webhook event persistence.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260714_user_account_classification",
                checksum="jiejing-user-account-classification-v20260714",
                summary="Separates merchant accounts from synthetic regression accounts for honest platform operations metrics.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260617_worker_runtime_heartbeats",
                checksum="jiejing-worker-runtime-heartbeats-v20260617",
                summary="Adds durable worker heartbeat records for deep operational health.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260701_media_asset_jobs",
                checksum="jiejing-media-asset-jobs-v20260701",
                summary="Adds provider-neutral media asset job records with idempotency, review and cost gate state.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260711_ai_ceo_account_chat_history",
                checksum="jiejing-ai-ceo-account-chat-history-v20260711",
                summary="Adds account-scoped, cross-device AI CEO chat history without provider secrets or raw credentials.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260711_shared_api_rate_limit_buckets",
                checksum="jiejing-shared-api-rate-limit-buckets-v20260711",
                summary="Adds expiring shared API rate-limit buckets without storing raw IP or email values.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260711_media_rework_reservations",
                checksum="jiejing-media-rework-reservations-v20260711",
                summary="Adds expiring database reservations so concurrent media rework requests enqueue at most one provider job.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260711_revocable_user_sessions",
                checksum="jiejing-revocable-user-sessions-v20260711",
                summary="Adds server-side session identifiers so logout immediately revokes signed browser and bearer sessions.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260713_ebay_account_deletion_events",
                checksum="jiejing-ebay-account-deletion-events-v20260713",
                summary="Adds sanitized, idempotent eBay marketplace account deletion receipts and compliance jobs.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260713_domestic_billing_orders",
                checksum="jiejing-domestic-billing-orders-v20260713",
                summary="Adds tenant-scoped, idempotent domestic billing orders without payment credentials or bank details.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260714_account_scoped_confirmations",
                checksum="jiejing-account-scoped-confirmations-v20260714",
                summary="Allows account-level billing confirmations without inventing a store or commerce task.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260714_platform_operations_metering",
                checksum="jiejing-platform-operations-metering-v20260714",
                summary="Adds privacy-safe traffic, provider-reported model usage and provider-neutral cost ledgers for the internal operator console.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260714_platform_reliability_alert_lifecycle",
                checksum="jiejing-platform-reliability-alert-lifecycle-v20260714",
                summary="Adds provider-neutral alert confirmation, recovery, deduplication and internal handling history.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260717_platform_provider_monitor_state",
                checksum="jiejing-platform-provider-monitor-state-v20260717",
                summary="Adds an expiring singleton lease and privacy-safe passive provider monitoring evidence.",
            )
            self._record_schema_migration(
                conn,
                migration_id="20260715_platform_trial_activations",
                checksum="jiejing-platform-trial-activations-v20260715",
                summary="Separates merchant registration from privacy-safe activation of Jiejing-funded AI and media trials.",
            )

    def _initialize_postgres(self) -> None:
        if self._postgres_initialized:
            return
        with self._postgres_initialize_lock:
            if self._postgres_initialized:
                return
            from .infrastructure_drivers import run_postgres_migration

            result = run_postgres_migration(database_url=self.database_url)
            if result.get("status") != "ok":
                blockers = result.get("blocked_by") if isinstance(result.get("blocked_by"), list) else []
                message = result.get("message") or ", ".join(str(item) for item in blockers) or result.get("status") or "unknown"
                raise RuntimeError(f"Postgres repository initialization failed: {message}")
            self._postgres_initialized = True

    def create_user_with_company(self, *, email: str, password: str, company_name: str) -> dict[str, Any]:
        self.initialize()
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("email is invalid")
        salt, password_digest = hash_password(password)
        created_at = now_iso()
        user_id = _id("user")
        company_id = _id("company")
        with self._connect() as conn:
            conn.execute(
                "insert into companies (company_id, name, created_at) values (?, ?, ?)",
                (company_id, company_name.strip() or "Jiejing Demo Company", created_at),
            )
            conn.execute(
                """
                insert into users (
                  user_id, email, password_salt, password_hash, status, default_company_id,
                  account_classification, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email,
                    salt,
                    password_digest,
                    "active",
                    company_id,
                    _account_classification_for_email(email),
                    created_at,
                ),
            )
            conn.execute(
                "insert into team_members (company_id, user_id, role, created_at) values (?, ?, ?, ?)",
                (company_id, user_id, "owner", created_at),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=user_id,
                actor_type="user",
                action_type="auth.register",
                target_type="user",
                target_id=user_id,
                summary="User registered and default company created.",
                details={"email": email, "secret_exposed": False},
            )
        return {"user": self.get_user(user_id), "company": self.get_company(company_id)}

    def authenticate_user(self, *, email: str, password: str) -> dict[str, Any]:
        self.initialize()
        user = self.get_user_by_email(email.strip().lower())
        if not user:
            verify_password(password, AUTH_DUMMY_PASSWORD_SALT, AUTH_DUMMY_PASSWORD_HASH)
            raise ValueError("invalid email or password")
        with self._connect() as conn:
            row = conn.execute(
                "select password_salt, password_hash from users where user_id = ?",
                (user["user_id"],),
            ).fetchone()
        if not row or not verify_password(password, row["password_salt"], row["password_hash"]):
            raise ValueError("invalid email or password")
        self.write_audit(
            company_id=user["default_company_id"],
            user_id=user["user_id"],
            action_type="auth.login",
            target_type="user",
            target_id=user["user_id"],
            summary="User logged in.",
            details={"email": user["email"], "secret_exposed": False},
        )
        return user

    def ensure_user_session(self, identity: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        jti = str(identity.get("jti") or "")[:160]
        user_id = str(identity.get("user_id") or "")
        company_id = str(identity.get("company_id") or "")
        issued_at = int(identity.get("iat") or 0)
        expires_epoch = int(identity.get("exp") or 0)
        if not jti or not user_id or not company_id or expires_epoch <= 0:
            return {"active": False, "status": "invalid_session_identity", "secret_exposed": False}
        with self._connect() as conn:
            conn.execute("delete from user_sessions where expires_epoch <= ?", (int(time.time()),))
            conn.execute(
                """
                insert or ignore into user_sessions (
                  jti, user_id, company_id, issued_at_epoch, expires_epoch, revoked_at, created_at
                ) values (?, ?, ?, ?, ?, null, ?)
                """,
                (jti, user_id, company_id, issued_at, expires_epoch, now_iso()),
            )
            row = conn.execute(
                "select user_id, company_id, expires_epoch, revoked_at from user_sessions where jti = ?",
                (jti,),
            ).fetchone()
        active = bool(
            row
            and str(row["user_id"]) == user_id
            and str(row["company_id"]) == company_id
            and int(row["expires_epoch"] or 0) > int(time.time())
            and not str(row["revoked_at"] or "")
        )
        return {
            "active": active,
            "status": "active" if active else "revoked_or_expired",
            "legacy_session_migrated": bool(identity.get("legacy_session")),
            "secret_exposed": False,
        }

    def revoke_user_session(self, *, jti: str, user_id: str) -> bool:
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                update user_sessions set revoked_at = ?
                where jti = ? and user_id = ? and revoked_at is null
                """,
                (now_iso(), str(jti or "")[:160], user_id),
            )
        return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select user_id, email, status, default_company_id, created_at
                from users where user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select user_id, email, status, default_company_id, created_at
                from users where email = ?
                """,
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def get_company(self, company_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("select company_id, name, created_at from companies where company_id = ?", (company_id,)).fetchone()
        return dict(row) if row else None

    def list_user_companies(self, *, user_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select c.company_id, c.name, c.created_at, tm.role, tm.created_at as joined_at
                from team_members tm
                join companies c on c.company_id = tm.company_id
                where tm.user_id = ?
                order by tm.created_at asc
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "company_id": row["company_id"],
                "name": row["name"],
                "created_at": row["created_at"],
                "role": row["role"],
                "joined_at": row["joined_at"],
                "permissions": permissions_for_role(row["role"]),
            }
            for row in rows
        ]

    def get_team_member(self, *, company_id: str, user_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select tm.company_id, tm.user_id, tm.role, tm.created_at, u.email, u.status
                from team_members tm
                join users u on u.user_id = tm.user_id
                where tm.company_id = ? and tm.user_id = ?
                """,
                (company_id, user_id),
            ).fetchone()
        return self._team_member_row_to_dict(row) if row else None

    def list_team_members(self, *, company_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select tm.company_id, tm.user_id, tm.role, tm.created_at, u.email, u.status
                from team_members tm
                join users u on u.user_id = tm.user_id
                where tm.company_id = ?
                order by case tm.role when 'owner' then 0 when 'admin' then 1 when 'operator' then 2 else 3 end,
                         tm.created_at asc
                """,
                (company_id,),
            ).fetchall()
        return [self._team_member_row_to_dict(row) for row in rows]

    def create_team_invitation(
        self,
        *,
        company_id: str,
        invited_by: str,
        email: str,
        role: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        email = email.strip().lower()
        role = role.strip().lower()
        if "@" not in email:
            raise ValueError("email is invalid")
        if not valid_role(role) or role == "owner":
            raise ValueError("role must be admin, operator, or viewer")
        created_at = now_iso()
        invitation_id = _id("invite")
        existing_user = self.get_user_by_email(email)
        accepted_at = created_at if existing_user else None
        status = "accepted_existing_user_added" if existing_user else "pending"
        record = {
            "invitation_id": invitation_id,
            "company_id": company_id,
            "email": email,
            "role": role,
            "status": status,
            "invited_by": invited_by,
            "created_at": created_at,
            "accepted_at": accepted_at,
            "permissions": permissions_for_role(role),
            "metadata": _redact_secret_like(metadata or {}),
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into team_invitations (
                  invitation_id, company_id, email, role, status, invited_by, created_at, accepted_at, invite_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invitation_id,
                    company_id,
                    email,
                    role,
                    status,
                    invited_by,
                    created_at,
                    accepted_at,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            if existing_user:
                conn.execute(
                    """
                    insert or ignore into team_members (company_id, user_id, role, created_at)
                    values (?, ?, ?, ?)
                    """,
                    (company_id, existing_user["user_id"], role, created_at),
                )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=invited_by,
                actor_type="user",
                action_type="team.invite",
                target_type="team_invitation",
                target_id=invitation_id,
                summary="Team invitation created or existing user added to company.",
                details={"email": email, "role": role, "status": status},
            )
        return record

    def list_team_invitations(self, *, company_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "select invite_json from team_invitations where company_id = ? order by created_at desc",
                (company_id,),
            ).fetchall()
        return [_load_json_field(row["invite_json"]) for row in rows]

    def create_store(self, *, company_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        store_id = _id("store")
        created_at = now_iso()
        record = {
            "store_id": store_id,
            "company_id": company_id,
            "platform": str(payload.get("platform") or "ebay"),
            "store_name": str(payload.get("store_name") or "eBay Store"),
            "marketplace": str(payload.get("marketplace") or "EBAY_US"),
            "stage": str(payload.get("stage") or "store_opened"),
            "created_by": user_id,
            "created_at": created_at,
            "settings": payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into stores (
                  store_id, company_id, platform, store_name, marketplace, stage, created_by, created_at, store_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["store_id"],
                    record["company_id"],
                    record["platform"],
                    record["store_name"],
                    record["marketplace"],
                    record["stage"],
                    record["created_by"],
                    record["created_at"],
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="store.create",
                target_type="store",
                target_id=store_id,
                summary="Store workspace created.",
                details={"platform": record["platform"], "marketplace": record["marketplace"]},
            )
        return record

    def create_task_steps(self, *, task: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.initialize()
        created_at = now_iso()
        with self._connect() as conn:
            conn.execute("delete from task_steps where task_id = ? and company_id = ?", (task["task_id"], task["company_id"]))
            for step in steps:
                conn.execute(
                    """
                    insert into task_steps (
                      step_id, task_id, company_id, store_id, step_order, task_type, depends_on_task_type,
                      role_key, merchant_label, status, attempts, max_attempts, timeout_seconds, created_at,
                      updated_at, started_at, finished_at, runtime_task_id, last_error, step_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _id("step"),
                        task["task_id"],
                        task["company_id"],
                        task["store_id"],
                        int(step.get("step_order") or 0),
                        str(step.get("task_type") or ""),
                        step.get("depends_on_task_type"),
                        str(step.get("role_key") or "runtime_agent"),
                        str(step.get("merchant_label") or step.get("task_type") or "Runtime step"),
                        "queued",
                        0,
                        int(step.get("retry_policy", {}).get("max_attempts") or 2) if isinstance(step.get("retry_policy"), dict) else 2,
                        int(step.get("timeout_seconds") or 180),
                        created_at,
                        created_at,
                        None,
                        None,
                        None,
                        None,
                        json.dumps(step, ensure_ascii=False),
                    ),
                )
            self._insert_audit(
                conn,
                company_id=task["company_id"],
                store_id=task["store_id"],
                user_id=task["user_id"],
                actor_type="system",
                action_type="task.steps.created",
                target_type="task",
                target_id=task["task_id"],
                summary="SaaS backend split product workflow into trackable steps.",
                details={"step_count": len(steps), "queue_provider": "local_worker"},
            )
        return self.list_task_steps(company_id=task["company_id"], task_id=task["task_id"])

    def list_stores(self, *, company_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select store_json from stores where company_id = ? order by created_at desc
                """,
                (company_id,),
            ).fetchall()
        return [_load_json_field(row["store_json"]) for row in rows]

    def get_store_for_company(self, *, company_id: str, store_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "select store_json from stores where company_id = ? and store_id = ?",
                (company_id, store_id),
            ).fetchone()
        return _load_json_field(row["store_json"]) if row else None

    def create_secret_reference(
        self,
        *,
        company_id: str,
        store_id: str | None,
        user_id: str,
        provider: str,
        purpose: str,
        status: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        if store_id and not self.get_store_for_company(company_id=company_id, store_id=store_id):
            raise KeyError("store not found")
        created_at = now_iso()
        secret_ref = _id("secret")
        record = {
            "secret_ref": secret_ref,
            "company_id": company_id,
            "store_id": store_id,
            "provider": provider,
            "purpose": purpose,
            "status": status,
            "created_by": user_id,
            "created_at": created_at,
            "metadata": _redact_secret_like(metadata),
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into secret_refs (
                  secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secret_ref,
                    company_id,
                    store_id,
                    provider,
                    purpose,
                    status,
                    user_id,
                    created_at,
                    json.dumps(record["metadata"], ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="secret_ref.create",
                target_type="secret_ref",
                target_id=secret_ref,
                summary="Secret reference created. Raw secret not stored in SaaS database.",
                details={
                    "provider": provider,
                    "purpose": purpose,
                    "status": status,
                    "raw_secret_input_seen": bool(record["metadata"].get("raw_secret_input_seen")),
                    "secret_value_stored": False,
                    "secret_exposed": False,
                },
            )
        return record

    def list_secret_refs(self, *, company_id: str, store_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
                from secret_refs where {where} order by created_at desc
                """,
                tuple(params),
            ).fetchall()
        return [self._secret_ref_row_to_dict(row) for row in rows]

    def get_secret_ref(self, *, company_id: str, secret_ref: str, store_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        params: list[Any] = [company_id, secret_ref]
        where = "company_id = ? and secret_ref = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
                from secret_refs where {where}
                """,
                tuple(params),
            ).fetchone()
        return self._secret_ref_row_to_dict(row) if row else None

    def update_secret_reference_status(
        self,
        *,
        company_id: str,
        secret_ref: str,
        status: str,
        metadata_patch: dict[str, Any],
        user_id: str,
        store_id: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        existing = self.get_secret_ref(company_id=company_id, secret_ref=secret_ref, store_id=store_id)
        if not existing:
            raise KeyError("secret_ref not found")
        merged_metadata = dict(existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {})
        merged_metadata.update(_redact_secret_like(metadata_patch))
        with self._connect() as conn:
            conn.execute(
                """
                update secret_refs
                set status = ?, metadata_json = ?
                where company_id = ? and secret_ref = ?
                """,
                (status, json.dumps(merged_metadata, ensure_ascii=False), company_id, secret_ref),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id or existing.get("store_id"),
                user_id=user_id,
                actor_type="system",
                action_type="secret_ref.status_update",
                target_type="secret_ref",
                target_id=secret_ref,
                summary="Secret reference status updated. Raw secret not stored in SaaS database.",
                details={
                    "status": status,
                    "metadata_keys": sorted(merged_metadata.keys()),
                    "secret_value_stored": False,
                    "secret_exposed": False,
                },
            )
        refreshed = self.get_secret_ref(company_id=company_id, secret_ref=secret_ref, store_id=store_id)
        return refreshed or existing

    def create_platform_connection(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        if not self.get_store_for_company(company_id=company_id, store_id=store_id):
            raise KeyError("store not found")
        created_at = now_iso()
        connection_id = _id("conn")
        platform = str(payload.get("platform") or "ebay")
        connection_type = str(payload.get("connection_type") or "oauth")
        scopes = payload.get("scopes") if isinstance(payload.get("scopes"), list) else []
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        stored_metadata = _redact_secret_like(metadata)
        has_secret_input = any(key in payload for key in ("token", "access_token", "refresh_token", "client_secret", "api_key"))
        provided_secret_ref = str(payload.get("secret_ref") or "").strip()
        secret_ref = None
        status = str(payload.get("status") or ("pending_oauth" if connection_type == "oauth" else "metadata_only"))
        with self._connect() as conn:
            if provided_secret_ref:
                ref_row = conn.execute(
                    """
                    select secret_ref from secret_refs
                    where company_id = ? and store_id = ? and secret_ref = ?
                    """,
                    (company_id, store_id, provided_secret_ref),
                ).fetchone()
                if not ref_row:
                    raise KeyError("secret_ref not found")
                secret_ref = provided_secret_ref
            if has_secret_input or payload.get("create_secret_ref"):
                secret_ref = _id("secret")
                conn.execute(
                    """
                    insert into secret_refs (
                      secret_ref, company_id, store_id, provider, purpose, status, created_by, created_at, metadata_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secret_ref,
                        company_id,
                        store_id,
                        platform,
                        str(payload.get("purpose") or "platform_connection"),
                        "external_vault_required",
                        user_id,
                        created_at,
                        json.dumps(
                            {
                                "note": "Local SaaS MVP stores only this reference. Raw secrets must live in Vault/KMS.",
                                "secret_input_seen": has_secret_input,
                                "secret_value_stored": False,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            record = {
                "connection_id": connection_id,
                "company_id": company_id,
                "store_id": store_id,
                "platform": platform,
                "connection_type": connection_type,
                "status": status,
                "scopes": scopes,
                "secret_ref": secret_ref,
                "metadata": _public_connection_metadata(stored_metadata),
                "created_by": user_id,
                "created_at": created_at,
                "secret_exposed": False,
            }
            conn.execute(
                """
                insert into platform_connections (
                  connection_id, company_id, store_id, platform, connection_type, status, scopes_json,
                  secret_ref, metadata_json, created_by, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    company_id,
                    store_id,
                    platform,
                    connection_type,
                    status,
                    json.dumps(scopes, ensure_ascii=False),
                    secret_ref,
                    json.dumps(stored_metadata, ensure_ascii=False),
                    user_id,
                    created_at,
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="connection.create",
                target_type="platform_connection",
                target_id=connection_id,
                summary="Platform connection metadata recorded. No raw secret stored.",
                details={"platform": platform, "status": status, "secret_ref": secret_ref, "secret_exposed": False},
            )
        return record

    def list_connections(self, *, company_id: str, store_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select connection_id, company_id, store_id, platform, connection_type, status, scopes_json,
                       secret_ref, metadata_json, created_by, created_at
                from platform_connections where {where} order by created_at desc
                """,
                tuple(params),
            ).fetchall()
        return [self._connection_row_to_dict(row) for row in rows]

    def create_oauth_authorization_request(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        if not self.get_store_for_company(company_id=company_id, store_id=store_id):
            raise KeyError("store not found")
        created_at = now_iso()
        request_id = _id("oauth")
        record = {
            "oauth_request_id": request_id,
            "company_id": company_id,
            "store_id": store_id,
            "platform": str(plan.get("platform") or "ebay"),
            "status": str(plan.get("status") or "created"),
            "state_nonce": str(plan.get("state_nonce") or ""),
            "scopes": plan.get("scopes") if isinstance(plan.get("scopes"), list) else [],
            "auth_url": plan.get("authorization_url") if isinstance(plan.get("authorization_url"), str) else None,
            "created_by": user_id,
            "created_at": created_at,
            "updated_at": created_at,
            "request": _redact_secret_like(plan),
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into oauth_authorization_requests (
                  oauth_request_id, company_id, store_id, platform, status, state_nonce, scopes_json,
                  auth_url, created_by, created_at, updated_at, request_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    company_id,
                    store_id,
                    record["platform"],
                    record["status"],
                    record["state_nonce"],
                    json.dumps(record["scopes"], ensure_ascii=False),
                    record["auth_url"],
                    user_id,
                    created_at,
                    created_at,
                    json.dumps(record["request"], ensure_ascii=False),
                ),
            )
            scope_profile = str(record["request"].get("scope_profile") or "seller_read_only")
            publish_scope = scope_profile == "seller_publish_listing"
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="oauth.publish.plan_created" if publish_scope else "oauth.read_only.plan_created",
                target_type="oauth_authorization_request",
                target_id=request_id,
                summary="eBay publish OAuth authorization plan created." if publish_scope else "eBay read-only OAuth authorization plan created.",
                details={
                    "status": record["status"],
                    "scope_profile": scope_profile,
                    "scope_count": len(record["scopes"]),
                    "authorization_url_created": bool(record["auth_url"]),
                    "secret_exposed": False,
                },
            )
        return record

    def list_oauth_authorization_requests(self, *, company_id: str, store_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from oauth_authorization_requests
                where {where}
                order by created_at desc
                """,
                tuple(params),
            ).fetchall()
        return [self._oauth_request_row_to_dict(row) for row in rows]

    def get_oauth_authorization_request_by_state(self, *, state_nonce: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "select * from oauth_authorization_requests where state_nonce = ?",
                (state_nonce,),
            ).fetchone()
        return self._oauth_request_row_to_dict(row) if row else None

    def create_platform_data_packet(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        packet: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        if not self.get_store_for_company(company_id=company_id, store_id=store_id):
            raise KeyError("store not found")
        created_at = now_iso()
        packet_id = _id("packet")
        record = {
            "packet_id": packet_id,
            "company_id": company_id,
            "store_id": store_id,
            "platform": str(packet.get("platform") or "ebay"),
            "packet_type": str(packet.get("packet_type") or "platform_data_packet"),
            "source_mode": str(packet.get("source_mode") or "unknown"),
            "status": str(packet.get("status") or "created"),
            "created_by": user_id,
            "created_at": created_at,
            "expires_at": packet.get("expires_at") if isinstance(packet.get("expires_at"), str) else None,
            "packet": _redact_secret_like(packet),
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into platform_data_packets (
                  packet_id, company_id, store_id, platform, packet_type, source_mode, status,
                  created_by, created_at, expires_at, packet_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    packet_id,
                    company_id,
                    store_id,
                    record["platform"],
                    record["packet_type"],
                    record["source_mode"],
                    record["status"],
                    user_id,
                    created_at,
                    record["expires_at"],
                    json.dumps(record["packet"], ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="system",
                action_type="platform_data_packet.create",
                target_type="platform_data_packet",
                target_id=packet_id,
                summary="Sanitized platform data packet created for Runtime/report use.",
                details={
                    "platform": record["platform"],
                    "packet_type": record["packet_type"],
                    "source_mode": record["source_mode"],
                    "resource_count": packet.get("resource_count"),
                    "source_gap_count": packet.get("source_gap_count"),
                    "raw_ebay_response_stored": False,
                    "secret_exposed": False,
                },
            )
        return record

    def list_platform_data_packets(
        self,
        *,
        company_id: str,
        store_id: str | None = None,
        platform: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        if platform:
            where += " and platform = ?"
            params.append(platform)
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from platform_data_packets
                where {where}
                order by created_at desc
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [self._platform_data_packet_row_to_dict(row) for row in rows]

    def get_platform_data_packet(self, *, company_id: str, packet_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "select * from platform_data_packets where company_id = ? and packet_id = ?",
                (company_id, packet_id),
            ).fetchone()
        return self._platform_data_packet_row_to_dict(row) if row else None

    def update_oauth_authorization_request(
        self,
        *,
        oauth_request_id: str,
        status: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        existing = None
        updated_at = now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "select * from oauth_authorization_requests where oauth_request_id = ?",
                (oauth_request_id,),
            ).fetchone()
            if not row:
                raise KeyError("oauth request not found")
            existing = self._oauth_request_row_to_dict(row)
            request_json = existing["request"]
            request_json.setdefault("callback_events", []).append({"created_at": updated_at, **_redact_secret_like(details)})
            conn.execute(
                """
                update oauth_authorization_requests
                set status = ?, updated_at = ?, request_json = ?
                where oauth_request_id = ?
                """,
                (status, updated_at, json.dumps(request_json, ensure_ascii=False), oauth_request_id),
            )
            self._insert_audit(
                conn,
                company_id=existing["company_id"],
                store_id=existing["store_id"],
                user_id=existing["created_by"],
                actor_type="system",
                action_type="oauth.callback.received",
                target_type="oauth_authorization_request",
                target_id=oauth_request_id,
                summary="eBay OAuth callback recorded by SaaS backend.",
                details={
                    "status": status,
                    "code_received": bool(details.get("code_received")),
                    "token_exchange_performed": bool(details.get("token_exchange_performed")),
                    "secret_exposed": False,
                },
            )
        refreshed = self.get_oauth_authorization_request_by_state(state_nonce=existing["state_nonce"])
        return refreshed or {}

    def create_task(self, *, company_id: str, store_id: str, user_id: str, task_type: str, title: str, input_data: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        task_id = _id("task")
        created_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                insert into tasks (
                  task_id, company_id, store_id, user_id, runtime_run_id, task_type, title,
                  status, created_at, updated_at, input_json, output_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    company_id,
                    store_id,
                    user_id,
                    None,
                    task_type,
                    title,
                    "queued",
                    created_at,
                    created_at,
                    json.dumps(input_data, ensure_ascii=False),
                    "{}",
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="task.create",
                target_type="task",
                target_id=task_id,
                summary="SaaS task created.",
                details={"task_type": task_type, "title": title},
            )
        return self.get_task(company_id=company_id, task_id=task_id) or {}

    def create_queue_job(self, *, company_id: str, task_id: str, job_data: dict[str, Any], max_attempts: int = 2) -> dict[str, Any]:
        self.initialize()
        job_id = _id("job")
        created_at = now_iso()
        queue_provider = os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker").strip().lower() or "local_worker"
        record = {
            "job_id": job_id,
            "task_id": task_id,
            "company_id": company_id,
            "status": "queued",
            "attempts": 0,
            "max_attempts": max_attempts,
            "created_at": created_at,
            "updated_at": created_at,
            "job": job_data,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into queue_jobs (
                  job_id, task_id, company_id, status, attempts, max_attempts, created_at, updated_at, job_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    task_id,
                    company_id,
                    record["status"],
                    record["attempts"],
                    record["max_attempts"],
                    created_at,
                    created_at,
                    json.dumps(job_data, ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=self._task_store_id(conn, task_id),
                user_id=self._task_user_id(conn, task_id),
                actor_type="system",
                action_type="queue.job.created",
                target_type="queue_job",
                target_id=job_id,
                summary="SaaS task was queued for worker execution.",
                details={"task_id": task_id, "queue_provider": queue_provider, "job_kind": job_data.get("kind")},
            )
        from .redis_queue_runtime import publish_redis_queue_job_if_configured

        dispatch = publish_redis_queue_job_if_configured(record)
        if dispatch.get("required") and dispatch.get("status") != "published":
            self.update_queue_job(
                job_id=job_id,
                company_id=company_id,
                status="failed",
                details={"queue_dispatch": dispatch, "error": "Redis queue dispatch failed."},
            )
            raise RuntimeError(f"Redis queue dispatch failed: {dispatch.get('message') or dispatch.get('error') or dispatch.get('status')}")
        if dispatch.get("status") == "published":
            record["queue_dispatch"] = dispatch
            return self.update_queue_job(
                job_id=job_id,
                company_id=company_id,
                status="queued",
                details={"queue_dispatch": dispatch},
            )
        return record

    def update_queue_job(self, *, job_id: str, company_id: str, status: str, attempts_delta: int = 0, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "select * from queue_jobs where job_id = ? and company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if not row:
                raise KeyError("queue job not found")
            job_json = _load_json_field(row["job_json"])
            if details:
                job_json.setdefault("updates", []).append({"created_at": updated_at, **details})
            attempts = int(row["attempts"]) + attempts_delta
            conn.execute(
                """
                update queue_jobs set status = ?, attempts = ?, updated_at = ?, job_json = ?
                where job_id = ? and company_id = ?
                """,
                (status, attempts, updated_at, json.dumps(job_json, ensure_ascii=False), job_id, company_id),
            )
        return self.get_queue_job(job_id=job_id, company_id=company_id) or {}

    def create_media_asset_job(
        self,
        *,
        company_id: str,
        store_id: str,
        task_id: str,
        user_id: str,
        provider_job_key: str,
        idempotency_key: str,
        job_spec: dict[str, Any],
        queue_job_id: str | None = None,
        status: str = "pending",
        version_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        clean_key = _safe_idempotency_key(idempotency_key)
        existing = self.get_media_asset_job_by_idempotency(company_id=company_id, idempotency_key=clean_key)
        if existing:
            return existing
        created_at = now_iso()
        media_job_id = _id("media_job")
        payload = _redact_secret_like(
            {
                "media_job_id": media_job_id,
                "job_spec": job_spec,
                "asset_version": version_context if isinstance(version_context, dict) else {
                    "contract_version": "2026-07-11-media-asset-version-v1",
                    "version": 1,
                    "root_media_job_id": media_job_id,
                    "parent_media_job_id": "",
                    "generation_reason": "initial_generation",
                    "prompt_version": "media_prompt_v1",
                    "immutable_prior_versions": True,
                    "secret_exposed": False,
                },
                "state_history": [
                    {
                        "status": status,
                        "created_at": created_at,
                        "message": "Media asset job accepted inside Jiejing task protocol. No live media provider was called.",
                    }
                ],
                "lifecycle": [
                    "pending",
                    "queued",
                    "running",
                    "provider_returned",
                    "validation_failed",
                    "waiting_review",
                    "approved_for_listing",
                    "needs_rework",
                ],
                "live_provider_called": False,
                "spend_now_allowed": False,
                "frontend_gets_media_api_key": False,
                "runtime_gets_raw_secret": False,
                "secret_exposed": False,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into media_asset_jobs (
                  media_job_id, company_id, store_id, task_id, queue_job_id, provider_job_key,
                  status, idempotency_key, retry_count, error_reason, created_by, created_at,
                  updated_at, media_job_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    media_job_id,
                    company_id,
                    store_id,
                    task_id,
                    queue_job_id or None,
                    provider_job_key,
                    status,
                    clean_key,
                    0,
                    "",
                    user_id,
                    created_at,
                    created_at,
                    json.dumps(payload, ensure_ascii=False, default=json_default),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="system",
                action_type="media.asset_job.created",
                target_type="media_asset_job",
                target_id=media_job_id,
                summary="Provider-neutral media asset job record created without live media provider calls.",
                details={
                    "task_id": task_id,
                    "queue_job_id": queue_job_id or "",
                    "provider_job_key": provider_job_key,
                    "status": status,
                    "idempotency_key": clean_key,
                    "live_provider_called": False,
                    "spend_now_allowed": False,
                    "secret_exposed": False,
                },
            )
        return self.get_media_asset_job(company_id=company_id, media_job_id=media_job_id) or {}

    def reserve_media_rework(
        self,
        *,
        company_id: str,
        parent_media_job_id: str,
        version: int,
        idempotency_key: str,
        ttl_seconds: int = 120,
    ) -> dict[str, Any]:
        self.initialize()
        now_epoch = int(time.time())
        created_at = now_iso()
        expires_epoch = now_epoch + max(30, int(ttl_seconds))
        reservation_key_hash = hashlib.sha256(
            f"{company_id}|{parent_media_job_id}|{version}|{idempotency_key}".encode("utf-8")
        ).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "delete from media_rework_reservations where status = 'preparing' and expires_epoch <= ?",
                (now_epoch,),
            )
            inserted = conn.execute(
                """
                insert into media_rework_reservations (
                  reservation_key_hash, company_id, parent_media_job_id, version,
                  status, media_job_id, created_at, updated_at, expires_epoch
                ) values (?, ?, ?, ?, 'preparing', null, ?, ?, ?)
                on conflict do nothing
                returning reservation_key_hash, status, media_job_id, expires_epoch
                """,
                (
                    reservation_key_hash,
                    company_id,
                    parent_media_job_id,
                    int(version),
                    created_at,
                    created_at,
                    expires_epoch,
                ),
            ).fetchone()
            row = inserted or conn.execute(
                """
                select reservation_key_hash, status, media_job_id, expires_epoch
                from media_rework_reservations
                where company_id = ? and parent_media_job_id = ? and version = ?
                """,
                (company_id, parent_media_job_id, int(version)),
            ).fetchone()
        return {
            "acquired": bool(inserted),
            "status": str(row["status"] if row else "preparing"),
            "media_job_id": str(row["media_job_id"] or "") if row else "",
            "retry_after_seconds": max(1, int((row["expires_epoch"] if row else expires_epoch) - now_epoch)),
            "reservation_key_hash": reservation_key_hash,
            "raw_idempotency_key_persisted": False,
            "secret_exposed": False,
        }

    def complete_media_rework_reservation(
        self,
        *,
        company_id: str,
        parent_media_job_id: str,
        version: int,
        media_job_id: str,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                update media_rework_reservations
                set status = 'created', media_job_id = ?, updated_at = ?, expires_epoch = ?
                where company_id = ? and parent_media_job_id = ? and version = ?
                """,
                (
                    media_job_id,
                    now_iso(),
                    int(time.time()) + 24 * 60 * 60,
                    company_id,
                    parent_media_job_id,
                    int(version),
                ),
            )

    def release_media_rework_reservation(
        self,
        *,
        company_id: str,
        parent_media_job_id: str,
        version: int,
    ) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                delete from media_rework_reservations
                where company_id = ? and parent_media_job_id = ? and version = ? and status = 'preparing'
                """,
                (company_id, parent_media_job_id, int(version)),
            )

    def update_media_asset_job(
        self,
        *,
        company_id: str,
        media_job_id: str,
        status: str,
        queue_job_id: str | None = None,
        provider_output: dict[str, Any] | None = None,
        error_reason: str | None = None,
        retry_delta: int = 0,
        details: dict[str, Any] | None = None,
        review_update: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "select * from media_asset_jobs where media_job_id = ? and company_id = ?",
                (media_job_id, company_id),
            ).fetchone()
            if not row:
                raise KeyError("media asset job not found")
            payload = _load_json_field(row["media_job_json"])
            if not isinstance(payload, dict):
                payload = {}
            provider_packet = provider_output.get("output_packet") if isinstance(provider_output, dict) and isinstance(provider_output.get("output_packet"), dict) else {}
            if provider_packet:
                payload["asset_manifest"] = provider_packet.get("asset_manifest") if isinstance(provider_packet.get("asset_manifest"), list) else []
                payload["asset_manifest_validation"] = provider_packet.get("asset_manifest_validation") if isinstance(provider_packet.get("asset_manifest_validation"), dict) else {}
                payload["asset_review"] = provider_packet.get("asset_review") if isinstance(provider_packet.get("asset_review"), dict) else {}
                payload["product_fact_gate"] = provider_packet.get("product_fact_gate") if isinstance(provider_packet.get("product_fact_gate"), dict) else {}
                payload["cost_guard"] = provider_packet.get("cost_guard") if isinstance(provider_packet.get("cost_guard"), dict) else {}
                payload["production_gate"] = provider_packet.get("production_gate") if isinstance(provider_packet.get("production_gate"), dict) else {}
                payload["merchant_visible_states"] = provider_packet.get("merchant_visible_states") if isinstance(provider_packet.get("merchant_visible_states"), list) else []
                payload["media_router"] = provider_packet.get("media_router") if isinstance(provider_packet.get("media_router"), dict) else {}
                payload["live_media_provider_status"] = (
                    provider_packet.get("live_media_provider_status")
                    if isinstance(provider_packet.get("live_media_provider_status"), dict)
                    else {}
                )
                if isinstance(provider_packet.get("asset_version"), dict):
                    current_version = payload.get("asset_version") if isinstance(payload.get("asset_version"), dict) else {}
                    packet_version = provider_packet["asset_version"]
                    payload["asset_version"] = {
                        **current_version,
                        **{key: value for key, value in packet_version.items() if value not in (None, "")},
                    }
                    payload["asset_version"].setdefault("root_media_job_id", media_job_id)
                validation_status = str(payload.get("asset_manifest_validation", {}).get("status") or "")
                if validation_status and validation_status != "manifest_ready" and status == "waiting_review":
                    status = "validation_failed"
                    error_reason = error_reason or "asset_manifest_validation_failed"
            if isinstance(provider_output, dict):
                safety = provider_output.get("safety") if isinstance(provider_output.get("safety"), dict) else {}
                payload["provider_job_status"] = provider_output.get("status")
                payload["live_provider_called"] = bool(safety.get("live_provider_called"))
                payload["raw_secret_read"] = bool(safety.get("raw_secret_read"))
                payload["raw_provider_response_stored"] = bool(safety.get("raw_provider_response_stored"))
                payload["secret_exposed"] = False
            if details:
                payload.setdefault("details", []).append(_redact_secret_like({"created_at": updated_at, **details}))
            if isinstance(review_update, dict):
                clean_review = _redact_secret_like(review_update)
                payload["merchant_review"] = clean_review
                approved = clean_review.get("decision") == "approve_for_listing_draft"
                manifest = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), list) else []
                for asset in manifest:
                    if not isinstance(asset, dict):
                        continue
                    asset["fact_review_status"] = "confirmed_by_merchant" if approved else "needs_rework"
                    asset["commercial_use_status"] = "confirmed_by_merchant" if approved else "needs_rework"
                    asset["listing_use_status"] = "approved_for_listing_draft" if approved else "needs_rework"
                    asset["review_status"] = "approved_for_listing_draft" if approved else "needs_rework"
                asset_review = payload.get("asset_review") if isinstance(payload.get("asset_review"), dict) else {}
                asset_review["status"] = "approved_for_listing_draft" if approved else "needs_rework"
                asset_review["listing_use_status"] = "approved_for_listing_draft" if approved else "needs_rework"
                asset_review["reviewed_at"] = updated_at
                payload["asset_review"] = asset_review
            payload.setdefault("state_history", []).append(
                _redact_secret_like(
                    {
                        "status": status,
                        "created_at": updated_at,
                        "queue_job_id": queue_job_id or row["queue_job_id"] or "",
                        "error_reason": error_reason or "",
                    }
                )
            )
            payload["secret_exposed"] = False
            retry_count = int(row["retry_count"]) + int(retry_delta or 0)
            conn.execute(
                """
                update media_asset_jobs
                set status = ?, queue_job_id = ?, retry_count = ?, error_reason = ?, updated_at = ?, media_job_json = ?
                where media_job_id = ? and company_id = ?
                """,
                (
                    status,
                    queue_job_id or row["queue_job_id"] or None,
                    retry_count,
                    (error_reason or "")[:500],
                    updated_at,
                    json.dumps(_redact_secret_like(payload), ensure_ascii=False, default=json_default),
                    media_job_id,
                    company_id,
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=row["store_id"],
                user_id=row["created_by"],
                actor_type="system",
                action_type="media.asset_job.status_updated",
                target_type="media_asset_job",
                target_id=media_job_id,
                summary="Media asset job status updated inside the provider-neutral asset pipeline.",
                details={
                    "task_id": row["task_id"],
                    "queue_job_id": queue_job_id or row["queue_job_id"] or "",
                    "provider_job_key": row["provider_job_key"],
                    "status": status,
                    "error_reason": error_reason or "",
                    "live_provider_called": bool(payload.get("live_provider_called")),
                    "spend_now_allowed": bool((payload.get("cost_guard") or {}).get("spend_now_allowed")) if isinstance(payload.get("cost_guard"), dict) else False,
                    "secret_exposed": False,
                },
            )
        return self.get_media_asset_job(company_id=company_id, media_job_id=media_job_id) or {}

    def get_media_asset_job(self, *, company_id: str, media_job_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "select * from media_asset_jobs where company_id = ? and media_job_id = ?",
                (company_id, media_job_id),
            ).fetchone()
        return self._media_asset_job_row_to_dict(row) if row else None

    def get_media_asset_job_by_idempotency(self, *, company_id: str, idempotency_key: str) -> dict[str, Any] | None:
        self.initialize()
        clean_key = _safe_idempotency_key(idempotency_key)
        with self._connect() as conn:
            row = conn.execute(
                "select * from media_asset_jobs where company_id = ? and idempotency_key = ?",
                (company_id, clean_key),
            ).fetchone()
        return self._media_asset_job_row_to_dict(row) if row else None

    def list_media_asset_jobs(
        self,
        *,
        company_id: str,
        store_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        if status:
            where += " and status = ?"
            params.append(status)
        params.append(max(1, min(int(limit), 200)))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from media_asset_jobs
                where {where}
                order by updated_at desc
                limit ?
                """,
                tuple(params),
            ).fetchall()
        return [self._media_asset_job_row_to_dict(row) for row in rows]

    def heartbeat_queue_job(self, *, job_id: str, company_id: str, worker_id: str, lease_seconds: int = 900) -> dict[str, Any]:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "select * from queue_jobs where job_id = ? and company_id = ?",
                (job_id, company_id),
            ).fetchone()
            if not row:
                raise KeyError("queue job not found")
            if row["status"] != "running":
                raise ValueError("only running queue jobs can receive heartbeat")
            job_json = _load_json_field(row["job_json"])
            job_json["worker_heartbeat"] = {
                "worker_id": worker_id,
                "heartbeat_at": updated_at,
                "lease_seconds": max(30, int(lease_seconds)),
            }
            conn.execute(
                """
                update queue_jobs set updated_at = ?, job_json = ?
                where job_id = ? and company_id = ? and status = 'running'
                """,
                (updated_at, json.dumps(job_json, ensure_ascii=False), job_id, company_id),
            )
        return self.get_queue_job(job_id=job_id, company_id=company_id) or {}

    def record_worker_heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        queue_provider: str | None = None,
        current_job_id: str | None = None,
        process_started_at: str | None = None,
        process_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        heartbeat_at = now_iso()
        clean_worker_id = (worker_id or "worker:unknown").strip()[:120] or "worker:unknown"
        clean_status = (status or "unknown").strip()[:60] or "unknown"
        clean_queue_provider = (queue_provider or os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker")).strip()[:80] or "local_worker"
        previous_heartbeat: dict[str, Any] = {}
        with self._connect() as conn:
            previous_row = conn.execute(
                "select heartbeat_json from worker_runtime_heartbeats where worker_id = ?",
                (clean_worker_id,),
            ).fetchone()
            if previous_row:
                previous_heartbeat = _load_json_field(previous_row["heartbeat_json"])
        previous_process_started_at = str(previous_heartbeat.get("process_started_at") or "")
        previous_restart_count = _safe_int(previous_heartbeat.get("restart_count_estimate"), default=0)
        clean_process_started_at = (process_started_at or previous_process_started_at or "").strip()
        restart_count_estimate = previous_restart_count
        if clean_process_started_at and previous_process_started_at and clean_process_started_at != previous_process_started_at:
            restart_count_estimate += 1
        payload = {
            "worker_id": clean_worker_id,
            "status": clean_status,
            "queue_provider": clean_queue_provider,
            "current_job_id": current_job_id or "",
            "heartbeat_at": heartbeat_at,
            "process_started_at": clean_process_started_at,
            "process_id": process_id,
            "restart_count_estimate": restart_count_estimate,
            "restart_count_source": "application_worker_heartbeat" if clean_process_started_at else "not_reported",
            "details": details or {},
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into worker_runtime_heartbeats (
                  worker_id, status, queue_provider, current_job_id, heartbeat_at, updated_at, heartbeat_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_worker_id,
                    clean_status,
                    clean_queue_provider,
                    current_job_id,
                    heartbeat_at,
                    heartbeat_at,
                    json.dumps(payload, ensure_ascii=False, default=json_default),
                ),
            )
        return payload

    def latest_worker_heartbeat(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from worker_runtime_heartbeats
                order by heartbeat_at desc
                limit 1
                """
            ).fetchone()
        if not row:
            return {}
        heartbeat_json = _load_json_field(row["heartbeat_json"])
        return {
            "worker_id": row["worker_id"],
            "status": row["status"],
            "queue_provider": row["queue_provider"],
            "current_job_id": row["current_job_id"] or "",
            "heartbeat_at": row["heartbeat_at"],
            "updated_at": row["updated_at"],
            "process_started_at": heartbeat_json.get("process_started_at") or "",
            "process_id": heartbeat_json.get("process_id"),
            "restart_count_estimate": _safe_int(heartbeat_json.get("restart_count_estimate"), default=0),
            "restart_count_source": heartbeat_json.get("restart_count_source") or "not_reported",
            "heartbeat": heartbeat_json,
            "secret_exposed": False,
        }

    def recover_stale_queue_jobs(
        self,
        *,
        company_id: str | None = None,
        stale_after_seconds: int = 900,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.initialize()
        recovered_at = now_iso()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_after_seconds)))
        params: list[Any] = []
        where = "status = 'running'"
        if company_id:
            where += " and company_id = ?"
            params.append(company_id)
        params.append(max(1, min(int(limit), 200)))
        recovered: list[dict[str, Any]] = []
        dead_lettered: list[dict[str, Any]] = []
        inspected = 0
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from queue_jobs
                where {where}
                order by updated_at asc
                limit ?
                """,
                tuple(params),
            ).fetchall()
            for row in rows:
                inspected += 1
                job_json = _load_json_field(row["job_json"])
                heartbeat = job_json.get("worker_heartbeat") if isinstance(job_json.get("worker_heartbeat"), dict) else {}
                last_seen = _parse_iso_datetime(str(heartbeat.get("heartbeat_at") or row["updated_at"] or row["created_at"]))
                if last_seen and last_seen > cutoff:
                    continue
                attempts = int(row["attempts"])
                max_attempts = int(row["max_attempts"])
                event = {
                    "created_at": recovered_at,
                    "message": "Queue watchdog recovered stale running job.",
                    "stale_after_seconds": max(30, int(stale_after_seconds)),
                    "last_seen_at": heartbeat.get("heartbeat_at") or row["updated_at"],
                }
                job_json.setdefault("updates", []).append(event)
                if attempts < max_attempts:
                    job_json["recovered_from_stale_running"] = event
                    conn.execute(
                        """
                        update queue_jobs set status = 'queued', updated_at = ?, job_json = ?
                        where job_id = ? and company_id = ?
                        """,
                        (recovered_at, json.dumps(job_json, ensure_ascii=False), row["job_id"], row["company_id"]),
                    )
                    conn.execute(
                        "update tasks set status = 'queued', updated_at = ? where task_id = ? and company_id = ?",
                        (recovered_at, row["task_id"], row["company_id"]),
                    )
                    recovered.append({"job_id": row["job_id"], "task_id": row["task_id"], "status": "queued"})
                else:
                    job_json["dead_letter"] = {**event, "reason": "stale_running_job_exhausted_attempts"}
                    conn.execute(
                        """
                        update queue_jobs set status = 'dead_letter', updated_at = ?, job_json = ?
                        where job_id = ? and company_id = ?
                        """,
                        (recovered_at, json.dumps(job_json, ensure_ascii=False), row["job_id"], row["company_id"]),
                    )
                    conn.execute(
                        "update tasks set status = 'failed', updated_at = ?, output_json = ? where task_id = ? and company_id = ?",
                        (
                            recovered_at,
                            json.dumps({"error": "Queue job moved to dead letter after stale worker heartbeat.", "failed_by": "queue_watchdog"}, ensure_ascii=False),
                            row["task_id"],
                            row["company_id"],
                        ),
                    )
                    dead_lettered.append({"job_id": row["job_id"], "task_id": row["task_id"], "status": "dead_letter"})
        return {
            "status": "completed",
            "inspected_running_jobs": inspected,
            "recovered_count": len(recovered),
            "dead_letter_count": len(dead_lettered),
            "recovered": recovered,
            "dead_lettered": dead_lettered,
            "stale_after_seconds": max(30, int(stale_after_seconds)),
            "secret_exposed": False,
        }

    def queue_health_summary(self, *, company_id: str, stale_after_seconds: int = 900) -> dict[str, Any]:
        self.initialize()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_after_seconds)))
        with self._connect() as conn:
            rows = conn.execute(
                """
                select status, count(*) as count
                from queue_jobs
                where company_id = ?
                group by status
                """,
                (company_id,),
            ).fetchall()
            running = conn.execute(
                """
                select * from queue_jobs
                where company_id = ? and status = 'running'
                order by updated_at asc
                limit 100
                """,
                (company_id,),
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        stale_running: list[dict[str, Any]] = []
        for row in running:
            job_json = _load_json_field(row["job_json"])
            heartbeat = job_json.get("worker_heartbeat") if isinstance(job_json.get("worker_heartbeat"), dict) else {}
            last_seen = _parse_iso_datetime(str(heartbeat.get("heartbeat_at") or row["updated_at"] or row["created_at"]))
            if last_seen and last_seen <= cutoff:
                stale_running.append(
                    {
                        "job_id": row["job_id"],
                        "task_id": row["task_id"],
                        "updated_at": row["updated_at"],
                        "heartbeat_at": heartbeat.get("heartbeat_at"),
                    }
                )
        return {
            "status": "attention_required" if stale_running or counts.get("dead_letter", 0) else "ready",
            "queue_provider": os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker").strip().lower() or "local_worker",
            "counts": counts,
            "stale_running_count": len(stale_running),
            "stale_running_jobs": stale_running,
            "stale_after_seconds": max(30, int(stale_after_seconds)),
            "worker_heartbeat_required": True,
            "dead_letter_visible": True,
            "secret_exposed": False,
        }

    def global_queue_health_summary(self, *, stale_after_seconds: int = 900) -> dict[str, Any]:
        self.initialize()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, int(stale_after_seconds)))
        with self._connect() as conn:
            rows = conn.execute(
                """
                select status, count(*) as count
                from queue_jobs
                group by status
                """
            ).fetchall()
            running = conn.execute(
                """
                select * from queue_jobs
                where status = 'running'
                order by updated_at asc
                limit 100
                """
            ).fetchall()
            latest_running = conn.execute(
                """
                select * from queue_jobs
                where status = 'running'
                order by updated_at desc
                limit 1
                """
            ).fetchone()
            oldest_queued = conn.execute(
                """
                select created_at from queue_jobs
                where status = 'queued'
                order by created_at asc
                limit 1
                """
            ).fetchone()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        stale_running: list[dict[str, Any]] = []
        latest_heartbeat_at = ""
        for row in running:
            job_json = _load_json_field(row["job_json"])
            heartbeat = job_json.get("worker_heartbeat") if isinstance(job_json.get("worker_heartbeat"), dict) else {}
            heartbeat_at = str(heartbeat.get("heartbeat_at") or "")
            if heartbeat_at and (not latest_heartbeat_at or heartbeat_at > latest_heartbeat_at):
                latest_heartbeat_at = heartbeat_at
            last_seen = _parse_iso_datetime(str(heartbeat.get("heartbeat_at") or row["updated_at"] or row["created_at"]))
            if last_seen and last_seen <= cutoff:
                stale_running.append(
                    {
                        "job_id": row["job_id"],
                        "task_id": row["task_id"],
                        "company_id": row["company_id"],
                        "updated_at": row["updated_at"],
                        "heartbeat_at": heartbeat.get("heartbeat_at"),
                    }
                )
        if latest_running and not latest_heartbeat_at:
            latest_job_json = _load_json_field(latest_running["job_json"])
            latest_heartbeat = latest_job_json.get("worker_heartbeat") if isinstance(latest_job_json.get("worker_heartbeat"), dict) else {}
            latest_heartbeat_at = str(latest_heartbeat.get("heartbeat_at") or latest_running["updated_at"] or "")
        return {
            "status": "attention_required" if stale_running or counts.get("dead_letter", 0) else "ready",
            "queue_provider": os.environ.get("JIEJING_QUEUE_PROVIDER", "local_worker").strip().lower() or "local_worker",
            "counts": counts,
            "stale_running_count": len(stale_running),
            "stale_running_jobs": stale_running,
            "stale_after_seconds": max(30, int(stale_after_seconds)),
            "latest_worker_heartbeat_at": latest_heartbeat_at,
            "oldest_queued_at": oldest_queued["created_at"] if oldest_queued else "",
            "timeout_recovery_available": True,
            "worker_heartbeat_required": True,
            "dead_letter_visible": True,
            "scope": "all_companies",
            "secret_exposed": False,
        }

    def claim_next_queue_job(self, *, company_id: str | None = None, job_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        if self.database_engine == "postgres":
            return self._claim_next_queue_job_postgres(company_id=company_id, job_id=job_id)
        claimed_at = now_iso()
        params: list[Any] = []
        where = "status = 'queued'"
        if company_id:
            where += " and company_id = ?"
            params.append(company_id)
        if job_id:
            where += " and job_id = ?"
            params.append(job_id)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select * from queue_jobs
                where {where}
                order by created_at asc
                limit 1
                """,
                tuple(params),
            ).fetchone()
            if not row:
                return None
            job_json = _load_json_field(row["job_json"])
            job_json.setdefault("updates", []).append(
                {
                    "created_at": claimed_at,
                    "message": "Local worker claimed queued job.",
                    "worker": "local_queue_worker",
                }
            )
            updated = conn.execute(
                """
                update queue_jobs
                set status = 'running', attempts = attempts + 1, updated_at = ?, job_json = ?
                where job_id = ? and status = 'queued'
                """,
                (claimed_at, json.dumps(job_json, ensure_ascii=False), row["job_id"]),
            ).rowcount
            if updated != 1:
                return None
            self._insert_audit(
                conn,
                company_id=row["company_id"],
                store_id=self._task_store_id(conn, row["task_id"]),
                user_id=self._task_user_id(conn, row["task_id"]),
                actor_type="system",
                action_type="queue.job.claimed",
                target_type="queue_job",
                target_id=row["job_id"],
                summary="Local worker claimed a queued SaaS task.",
                details={"task_id": row["task_id"], "queue_provider": "local_worker"},
            )
        return self.get_queue_job(job_id=row["job_id"], company_id=row["company_id"])

    def _claim_next_queue_job_postgres(self, *, company_id: str | None = None, job_id: str | None = None) -> dict[str, Any] | None:
        claimed_at = now_iso()
        params: list[Any] = []
        where = "status = 'queued'"
        if company_id:
            where += " and company_id = ?"
            params.append(company_id)
        if job_id:
            where += " and job_id = ?"
            params.append(job_id)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select * from queue_jobs
                where {where}
                order by created_at asc
                limit 1
                for update skip locked
                """,
                tuple(params),
            ).fetchone()
            if not row:
                return None
            job_json = _load_json_field(row["job_json"])
            job_json.setdefault("updates", []).append(
                {
                    "created_at": claimed_at,
                    "message": "Postgres durable worker claimed queued job.",
                    "worker": "postgres_durable_queue_worker",
                    "lock": "for_update_skip_locked",
                }
            )
            updated = conn.execute(
                """
                update queue_jobs
                set status = 'running', attempts = attempts + 1, updated_at = ?, job_json = ?
                where job_id = ? and company_id = ? and status = 'queued'
                """,
                (claimed_at, json.dumps(job_json, ensure_ascii=False), row["job_id"], row["company_id"]),
            ).rowcount
            if updated != 1:
                return None
            self._insert_audit(
                conn,
                company_id=row["company_id"],
                store_id=self._task_store_id(conn, row["task_id"]),
                user_id=self._task_user_id(conn, row["task_id"]),
                actor_type="system",
                action_type="queue.job.claimed",
                target_type="queue_job",
                target_id=row["job_id"],
                summary="Postgres durable worker claimed a queued SaaS task.",
                details={"task_id": row["task_id"], "queue_provider": "postgres_durable", "lock": "for_update_skip_locked"},
            )
        return self.get_queue_job(job_id=row["job_id"], company_id=row["company_id"])

    def mark_task_steps_running(self, *, task_id: str, company_id: str) -> None:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                update task_steps
                set status = 'running', attempts = attempts + 1, started_at = coalesce(started_at, ?), updated_at = ?
                where task_id = ? and company_id = ?
                """,
                (updated_at, updated_at, task_id, company_id),
            )

    def mark_task_steps_failed(self, *, task_id: str, company_id: str, error: str) -> None:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                update task_steps
                set status = 'failed', updated_at = ?, finished_at = coalesce(finished_at, ?), last_error = ?
                where task_id = ? and company_id = ? and status in ('queued', 'running')
                """,
                (updated_at, updated_at, error[:500], task_id, company_id),
            )

    def mark_task_steps_cancelled(self, *, task_id: str, company_id: str, reason: str) -> None:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                update task_steps
                set status = 'cancelled', updated_at = ?, finished_at = coalesce(finished_at, ?), last_error = ?
                where task_id = ? and company_id = ? and status in ('queued', 'running')
                """,
                (updated_at, updated_at, reason[:500], task_id, company_id),
            )

    def reset_task_steps_for_retry(self, *, task_id: str, company_id: str) -> None:
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                update task_steps
                set status = 'queued', attempts = 0, updated_at = ?, started_at = null,
                    finished_at = null, runtime_task_id = null, last_error = null
                where task_id = ? and company_id = ?
                """,
                (updated_at, task_id, company_id),
            )

    def get_queue_job(self, *, job_id: str, company_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("select * from queue_jobs where job_id = ? and company_id = ?", (job_id, company_id)).fetchone()
        return self._queue_job_row_to_dict(row) if row else None

    def list_queue_jobs(self, *, company_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if status:
            where += " and status = ?"
            params.append(status)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from queue_jobs
                where {where}
                order by created_at desc
                limit ?
                """,
                tuple(params),
            ).fetchall()
        return [self._queue_job_row_to_dict(row) for row in rows]

    def list_queue_jobs_for_task(self, *, company_id: str, task_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from queue_jobs
                where company_id = ? and task_id = ?
                order by created_at asc
                """,
                (company_id, task_id),
            ).fetchall()
        return [self._queue_job_row_to_dict(row) for row in rows]

    def cancel_queue_job(self, *, company_id: str, job_id: str, user_id: str, reason: str | None = None) -> dict[str, Any]:
        self.initialize()
        existing = self.get_queue_job(job_id=job_id, company_id=company_id)
        if not existing:
            raise KeyError("queue job not found")
        if existing["status"] not in {"queued", "running"}:
            raise ValueError("only queued or running jobs can be cancelled")
        cancelled = self.update_queue_job(
            job_id=job_id,
            company_id=company_id,
            status="cancelled",
            details={"message": "Queue job cancelled.", "reason": reason or "merchant_or_operator_cancelled"},
        )
        self.update_task_status(
            task_id=existing["task_id"],
            company_id=company_id,
            status="cancelled",
            audit_summary="Queued SaaS task was cancelled before completion.",
        )
        self.mark_task_steps_cancelled(task_id=existing["task_id"], company_id=company_id, reason=reason or "cancelled")
        self.write_audit(
            company_id=company_id,
            user_id=user_id,
            store_id=self._store_id_for_task(company_id=company_id, task_id=existing["task_id"]),
            actor_type="user",
            action_type="queue.job.cancelled",
            target_type="queue_job",
            target_id=job_id,
            summary="Queue job cancellation recorded.",
            details={"task_id": existing["task_id"], "reason": reason or "cancelled"},
        )
        return cancelled

    def retry_queue_job(self, *, company_id: str, job_id: str, user_id: str, reason: str | None = None) -> dict[str, Any]:
        self.initialize()
        existing = self.get_queue_job(job_id=job_id, company_id=company_id)
        if not existing:
            raise KeyError("queue job not found")
        if existing["status"] not in {"failed", "cancelled"}:
            raise ValueError("only failed or cancelled jobs can be retried")
        task = self.get_task(company_id=company_id, task_id=existing["task_id"])
        if not task:
            raise KeyError("task not found")
        job_data = dict(existing.get("job") or {})
        job_data["retry_of"] = job_id
        job_data["retry_reason"] = reason or "operator_retry"
        job_data["run_mode"] = "queued"
        retried = self.create_queue_job(
            company_id=company_id,
            task_id=task["task_id"],
            job_data=job_data,
            max_attempts=int(existing.get("max_attempts") or 2),
        )
        self.update_task_status(
            task_id=task["task_id"],
            company_id=company_id,
            status="queued",
            audit_summary="SaaS task was reset for queue retry.",
        )
        self.reset_task_steps_for_retry(task_id=task["task_id"], company_id=company_id)
        self.write_audit(
            company_id=company_id,
            user_id=user_id,
            store_id=task["store_id"],
            actor_type="user",
            action_type="queue.job.retry_requested",
            target_type="queue_job",
            target_id=retried["job_id"],
            summary="Queue retry requested.",
            details={"task_id": task["task_id"], "retry_of": job_id, "reason": reason or "operator_retry"},
        )
        return retried

    def complete_task_from_runtime(self, *, task_id: str, company_id: str, runtime_result: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        runtime_run_id = str(runtime_result.get("run", {}).get("run_id") or runtime_result.get("run_id") or "")
        status = str(runtime_result.get("run", {}).get("run_status") or "completed")
        updated_at = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                update tasks set runtime_run_id = ?, status = ?, updated_at = ?, output_json = ?
                where task_id = ? and company_id = ?
                """,
                (runtime_run_id, status, updated_at, json.dumps(runtime_result, ensure_ascii=False), task_id, company_id),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=self._task_store_id(conn, task_id),
                user_id=self._task_user_id(conn, task_id),
                actor_type="system",
                action_type="runtime.workflow.completed",
                target_type="task",
                target_id=task_id,
                summary="Runtime workflow completed and returned reports/confirmations.",
                details={"runtime_run_id": runtime_run_id, "status": status},
            )
        task = self.get_task(company_id=company_id, task_id=task_id)
        return task or {}

    def update_task_status(
        self,
        *,
        task_id: str,
        company_id: str,
        status: str,
        output: dict[str, Any] | None = None,
        audit_summary: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        updated_at = now_iso()
        task = self.get_task(company_id=company_id, task_id=task_id)
        if not task:
            raise KeyError("task not found")
        output_json = json.dumps(output if output is not None else task["output"], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                update tasks set status = ?, updated_at = ?, output_json = ?
                where task_id = ? and company_id = ?
                """,
                (status, updated_at, output_json, task_id, company_id),
            )
            if audit_summary:
                self._insert_audit(
                    conn,
                    company_id=company_id,
                    store_id=task["store_id"],
                    user_id=task["user_id"],
                    actor_type="system",
                    action_type="task.status.update",
                    target_type="task",
                    target_id=task_id,
                    summary=audit_summary,
                    details={"status": status},
                )
        return self.get_task(company_id=company_id, task_id=task_id) or {}

    def save_runtime_outputs(self, *, task: dict[str, Any], runtime_result: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        runtime_run_id = str(runtime_result.get("run", {}).get("run_id") or runtime_result.get("run_id") or task.get("runtime_run_id") or "")
        results = runtime_result.get("results") if isinstance(runtime_result.get("results"), list) else []
        confirmations = runtime_result.get("confirmations") if isinstance(runtime_result.get("confirmations"), list) else []
        created_at = now_iso()
        report_count = 0
        confirmation_count = 0
        with self._connect() as conn:
            for result in results:
                report_id = _id("report")
                report_type = str(result.get("task_type") or "runtime.result")
                title = str(result.get("summary") or result.get("task_type") or "Runtime report")[:180]
                conn.execute(
                    """
                    insert into reports (
                      report_id, task_id, runtime_run_id, report_type, title, status, created_at, report_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        task["task_id"],
                        runtime_run_id,
                        report_type,
                        title,
                        str(result.get("status") or "unknown"),
                        created_at,
                        json.dumps(result, ensure_ascii=False),
                    ),
                )
                report_count += 1
                self._insert_merchant_memory(
                    conn,
                    company_id=task["company_id"],
                    store_id=task["store_id"],
                    memory_type="ai_report",
                    source_type="report",
                    source_id=report_id,
                    title=title,
                    summary=_memory_summary_from_report(result),
                    importance=_memory_importance_from_report(result),
                    tags=[report_type, str(result.get("status") or "unknown"), "jiejing_runtime"],
                    memory={
                        "report_id": report_id,
                        "task_id": task["task_id"],
                        "runtime_run_id": runtime_run_id,
                        "report_type": report_type,
                        "report_status": str(result.get("status") or "unknown"),
                        "model_assist": ((result.get("report") or {}).get("model_assist") if isinstance(result.get("report"), dict) else {}),
                        "source_record_count": len(result.get("source_records") or []) if isinstance(result.get("source_records"), list) else 0,
                        "confirmation_item_count": len(result.get("confirmation_items") or []) if isinstance(result.get("confirmation_items"), list) else 0,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                    created_by=task.get("user_id"),
                )
            for item in confirmations:
                source_confirmation_id = str(item.get("confirmation_id") or _id("runtime_confirm"))
                confirmation_id = f"{task['task_id']}::{source_confirmation_id}"
                status = "pending"
                conn.execute(
                    """
                    insert or replace into confirmations (
                      confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status,
                      default_action, created_at, item_json, decided_by, decided_at, decision_note
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        confirmation_id,
                        task["company_id"],
                        task["store_id"],
                        task["task_id"],
                        runtime_run_id,
                        str(item.get("action_type") or "unknown"),
                        str(item.get("title") or "Confirmation item"),
                        status,
                        str(item.get("default_action") or "hold"),
                        created_at,
                        json.dumps(item, ensure_ascii=False),
                        None,
                        None,
                        None,
                    ),
                )
                confirmation_count += 1
                self._insert_merchant_memory(
                    conn,
                    company_id=task["company_id"],
                    store_id=task["store_id"],
                    memory_type="confirmation_boundary",
                    source_type="confirmation",
                    source_id=confirmation_id,
                    title=str(item.get("title") or "Confirmation item"),
                    summary=_memory_summary_from_confirmation(item),
                    importance=90 if str(item.get("action_type") or "") in HIGH_RISK_ACTIONS else 70,
                    tags=[str(item.get("action_type") or "unknown"), "confirmation_center", "risk_control"],
                    memory={
                        "confirmation_id": confirmation_id,
                        "task_id": task["task_id"],
                        "runtime_run_id": runtime_run_id,
                        "action_type": str(item.get("action_type") or "unknown"),
                        "default_action": str(item.get("default_action") or "hold"),
                        "source_packet_id": item.get("source_packet_id"),
                        "high_risk": str(item.get("action_type") or "") in HIGH_RISK_ACTIONS,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                    created_by=task.get("user_id"),
                )
            self._insert_audit(
                conn,
                company_id=task["company_id"],
                store_id=task["store_id"],
                user_id=task["user_id"],
                actor_type="system",
                action_type="runtime.outputs.saved",
                target_type="task",
                target_id=task["task_id"],
                summary="Runtime reports and confirmation items saved into SaaS database.",
                details={"reports": report_count, "confirmations": confirmation_count},
            )
            self._update_task_steps_from_runtime_results(conn, task=task, runtime_result=runtime_result)
        return {"runtime_run_id": runtime_run_id, "reports": report_count, "confirmations": confirmation_count}

    def save_ai_ceo_market_research_report(
        self,
        *,
        task: dict[str, Any],
        message: str,
        chat: dict[str, Any],
        command_id: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Persist a merchant-facing AI CEO market research chat turn as a report."""

        self.initialize()
        if not _looks_like_ai_ceo_market_research_turn(message=message, chat=chat):
            return None
        answer = _sanitize_merchant_ceo_text(chat.get("answer"), limit=5000)
        if not answer:
            return None
        created_at = now_iso()
        report_id = _id("report")
        runtime_run_id = str(task.get("runtime_run_id") or "ai_ceo_chat")
        source_records = _redact_secret_like((chat.get("source_records") if isinstance(chat.get("source_records"), list) else [])[:8])
        work_records = _redact_secret_like((chat.get("work_records") if isinstance(chat.get("work_records"), list) else [])[:8])
        confirmation_items = _redact_secret_like((chat.get("confirmation_items") if isinstance(chat.get("confirmation_items"), list) else [])[:8])
        answer_quality = chat.get("answer_quality") if isinstance(chat.get("answer_quality"), dict) else {}
        rejected_statuses = {
            "model_answer_rejected",
            "model_call_failed",
            "source_backed_market_report_draft",
            "market_report_recovery_draft",
        }
        answer_accepted = (
            answer_quality.get("accepted") is True
            if answer_quality
            else str(chat.get("status") or "") not in rejected_statuses
        )
        product_candidates = _ai_ceo_market_product_candidates(message=message, answer=answer) if answer_accepted else []
        if answer_accepted and not product_candidates and _ai_ceo_market_context_reset_requested(message):
            return None
        selection_mode = "current_turn" if product_candidates else "none"
        selected_candidate = _select_ai_ceo_market_candidate(answer=answer, candidates=product_candidates)
        if answer_accepted and not product_candidates:
            history_candidates, history_selected = _ai_ceo_market_context_from_history(conversation_history)
            requested_index = _ai_ceo_followup_candidate_index(message)
            if history_candidates and (requested_index is not None or _ai_ceo_should_inherit_market_context(message)):
                product_candidates = history_candidates
                if requested_index is not None and requested_index < len(product_candidates):
                    selected_candidate = product_candidates[requested_index]
                    selection_mode = "history_candidate_index"
                else:
                    selected_candidate = history_selected
                    selection_mode = "history_selected_candidate"
                selected_id = str(selected_candidate.get("candidate_id") or "")
                for candidate in product_candidates:
                    candidate["selected"] = str(candidate.get("candidate_id") or "") == selected_id
        product = ""
        if answer_accepted:
            product = _clean_ai_ceo_market_candidate_name(selected_candidate.get("name")) or _infer_ai_ceo_market_product(
                message=message,
                answer=answer,
                candidates=product_candidates,
            )
        listing_import_ready = bool(product and answer_accepted)
        question = _sanitize_merchant_ceo_text(message, limit=900)
        source_count = len(source_records) if isinstance(source_records, list) else 0
        title = f"AI CEO 市场调研：{product}"[:180] if product else "AI CEO 市场调研"
        summary = (
            f"AI CEO 已把“{product}”整理成可导入 Listing 的市场调研。"
            if product
            else "AI CEO 已把本次选品/市场调研整理成可导入 Listing 的工作记录。"
        )
        report_payload = {
            "contract_version": AI_CEO_MARKET_REPORT_CONTRACT_VERSION,
            "source_type": "ai_ceo_chat",
            "source_command_id": command_id or "",
            "product": product,
            "product_candidates": product_candidates,
            "selected_product_candidate": selected_candidate,
            "conversation_context": {
                "contract_version": "2026-07-11-ai-ceo-product-context-v1",
                "selection_mode": selection_mode,
                "history_used": selection_mode.startswith("history_"),
                "selected_candidate_id": str(selected_candidate.get("candidate_id") or ""),
                "raw_conversation_stored": False,
                "secret_exposed": False,
            },
            "merchant_question": question,
            "merchant_readable_summary": summary,
            "answer": answer,
            "route": str(chat.get("route") or ""),
            "route_label": str(chat.get("route_label") or ""),
            "status": str(chat.get("status") or ""),
            "answer_quality": _redact_secret_like(answer_quality),
            "model_client": _redact_secret_like(chat.get("model_client") if isinstance(chat.get("model_client"), dict) else {}),
            "source_records": source_records,
            "source_record_count": source_count,
            "work_records": work_records,
            "confirmation_items": confirmation_items,
            "listing_handoff": {
                "ready_for_listing_draft": listing_import_ready,
                "source_mode": "ai_ceo_chat_structured_handoff",
                "target_report_type": "ai_ceo.market_research",
                "listing_fields": (
                    _ai_ceo_listing_handoff_fields(
                        product=product,
                        answer=answer,
                        source_records=source_records if isinstance(source_records, list) else [],
                        selected_candidate=selected_candidate,
                        product_candidates=product_candidates,
                    )
                    if listing_import_ready
                    else {}
                ),
                "blocked_by": [] if listing_import_ready else ["answer_quality_not_ready_for_listing"],
                "requires_human_review_before_publish": True,
                "real_platform_writes_enabled": False,
                "triggers_real_platform_write": False,
            },
            "source_policy": _redact_secret_like(chat.get("source_policy") if isinstance(chat.get("source_policy"), dict) else {}),
            "frontend_gets_model_api_key": False,
            "runtime_gets_raw_ebay_token": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into reports (
                  report_id, task_id, runtime_run_id, report_type, title, status, created_at, report_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    task["task_id"],
                    runtime_run_id,
                    "ai_ceo.market_research",
                    title,
                    "saved",
                    created_at,
                    json.dumps(report_payload, ensure_ascii=False, default=json_default),
                ),
            )
            self._insert_merchant_memory(
                conn,
                company_id=task["company_id"],
                store_id=task["store_id"],
                memory_type="ai_ceo_market_research",
                source_type="report",
                source_id=report_id,
                title=title,
                summary=summary,
                importance=80,
                tags=["ai_ceo.market_research", "listing_handoff", "source_backed" if source_count else "needs_more_sources"],
                memory={
                    "report_id": report_id,
                    "task_id": task["task_id"],
                    "runtime_run_id": runtime_run_id,
                    "report_type": "ai_ceo.market_research",
                    "product": product,
                    "source_record_count": source_count,
                    "ready_for_listing_draft": listing_import_ready,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                created_by=task.get("user_id"),
            )
            self._insert_audit(
                conn,
                company_id=task["company_id"],
                store_id=task["store_id"],
                user_id=task.get("user_id"),
                actor_type="system",
                action_type="ai_ceo.market_research.saved",
                target_type="report",
                target_id=report_id,
                summary="AI CEO market research chat turn saved as a structured Listing handoff report.",
                details={
                    "report_type": "ai_ceo.market_research",
                    "task_id": task["task_id"],
                    "command_id": command_id or "",
                    "source_record_count": source_count,
                    "ready_for_listing_draft": True,
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_raw_ebay_token": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
        return {
            "report_id": report_id,
            "task_id": task["task_id"],
            "runtime_run_id": runtime_run_id,
            "report_type": "ai_ceo.market_research",
            "title": title,
            "status": "saved",
            "created_at": created_at,
            "report": report_payload,
            "secret_exposed": False,
        }

    def list_task_steps(self, *, company_id: str, task_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from task_steps
                where company_id = ? and task_id = ?
                order by step_order asc
                """,
                (company_id, task_id),
            ).fetchall()
        return [self._task_step_row_to_dict(row) for row in rows]

    def get_task(self, *, company_id: str, task_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("select * from tasks where company_id = ? and task_id = ?", (company_id, task_id)).fetchone()
        return self._task_row_to_dict(row) if row else None

    def list_tasks(self, *, company_id: str, store_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(f"select * from tasks where {where} order by created_at desc {limit_clause}", tuple(params)).fetchall()
        return [self._task_row_to_dict(row) for row in rows]

    def list_reports(self, *, company_id: str, task_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "t.company_id = ?"
        if task_id:
            where += " and r.task_id = ?"
            params.append(task_id)
        order_direction = "desc" if limit and limit > 0 else "asc"
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select r.* from reports r
                join tasks t on t.task_id = r.task_id
                where {where}
                order by r.created_at {order_direction}
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [self._report_row_to_dict(row) for row in rows]

    def list_confirmations(self, *, company_id: str, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if status:
            where += " and status = ?"
            params.append(status)
        order_direction = "desc" if limit and limit > 0 else "asc"
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(f"select * from confirmations where {where} order by created_at {order_direction} {limit_clause}", tuple(params)).fetchall()
        return [self._confirmation_row_to_dict(row) for row in rows]

    def test_data_governance_snapshot(self, *, company_id: str) -> dict[str, Any]:
        """Return current-company test-data evidence without exposing other tenants."""

        self.initialize()
        with self._connect() as conn:
            team_test_users = int(
                conn.execute(
                    """
                    select count(*) as count
                    from team_members tm
                    join users u on u.user_id = tm.user_id
                    where tm.company_id = ?
                      and (
                        lower(u.email) like ?
                        or lower(u.email) like ?
                      )
                    """,
                    (company_id, "codex-owner-launch-%@local.invalid", "%@example.test"),
                ).fetchone()["count"]
            )
            test_companies = int(
                conn.execute(
                    """
                    select count(*) as count
                    from companies
                    where company_id = ?
                      and lower(name) like ?
                    """,
                    (company_id, "codex owner launch%"),
                ).fetchone()["count"]
            )
            smoke_stores = int(
                conn.execute(
                    """
                    select count(*) as count
                    from stores
                    where company_id = ?
                      and (
                        lower(store_name) like ?
                        or lower(cast(store_json as text)) like ?
                      )
                    """,
                    (company_id, "codex owner launch smoke%", "%codex_owner_launch_control_smoke%"),
                ).fetchone()["count"]
            )
            billing_test_events = int(
                conn.execute(
                    """
                    select count(*) as count
                    from audit_logs
                    where company_id = ?
                      and action_type = 'billing.test_event.applied'
                    """,
                    (company_id,),
                ).fetchone()["count"]
            )
            marked_test_audits = int(
                conn.execute(
                    """
                    select count(*) as count
                    from audit_logs
                    where company_id = ?
                      and (
                        lower(cast(audit_json as text)) like ?
                        or lower(cast(audit_json as text)) like ?
                        or action_type = 'billing.test_event.applied'
                      )
                    """,
                    (company_id, "%codex-owner-launch-%", "%codex_owner_launch_control_smoke%"),
                ).fetchone()["count"]
            )
            pending_confirmations = int(
                conn.execute(
                    "select count(*) as count from confirmations where company_id = ? and status = 'pending'",
                    (company_id,),
                ).fetchone()["count"]
            )
            cleanup_confirmations = int(
                conn.execute(
                    "select count(*) as count from confirmations where company_id = ? and action_type = 'cleanup_test_listing'",
                    (company_id,),
                ).fetchone()["count"]
            )
            latest_activity = conn.execute(
                """
                select max(created_at) as latest
                from audit_logs
                where company_id = ?
                  and (
                    lower(cast(audit_json as text)) like ?
                    or lower(cast(audit_json as text)) like ?
                    or action_type = 'billing.test_event.applied'
                  )
                """,
                (company_id, "%codex-owner-launch-%", "%codex_owner_launch_control_smoke%"),
            ).fetchone()
            candidate_rows = conn.execute(
                """
                select store_id, store_name, marketplace, created_at
                from stores
                where company_id = ?
                  and (
                    lower(store_name) like ?
                    or lower(cast(store_json as text)) like ?
                  )
                order by created_at desc
                limit 5
                """,
                (company_id, "codex owner launch smoke%", "%codex_owner_launch_control_smoke%"),
            ).fetchall()
        candidate_count = team_test_users + test_companies + smoke_stores + billing_test_events
        return {
            "contract_version": "2026-06-20-test-data-governance",
            "scope": "current_company_only",
            "global_tenant_scan_exposed": False,
            "status": "test_data_present" if candidate_count else "no_test_data_detected",
            "tone": "amber" if candidate_count else "green",
            "candidate_count": candidate_count,
            "counts": {
                "team_test_users": team_test_users,
                "test_company_name_matches": test_companies,
                "smoke_stores": smoke_stores,
                "billing_test_events": billing_test_events,
                "marked_test_audits": marked_test_audits,
                "pending_confirmations": pending_confirmations,
                "cleanup_confirmations": cleanup_confirmations,
            },
            "latest_test_activity_at": latest_activity["latest"] if latest_activity else "",
            "candidate_records": [
                {
                    "type": "store",
                    "store_id": row["store_id"],
                    "label": row["store_name"],
                    "marketplace": row["marketplace"],
                    "created_at": row["created_at"],
                    "secret_exposed": False,
                }
                for row in candidate_rows
            ],
            "cleanup_policy": {
                "delete_now_allowed": False,
                "automatic_delete_allowed": False,
                "requires_owner_review": True,
                "recommended_mode": "mark_and_report_first",
                "reason": "Staging smoke data can be useful evidence. Do not delete tenant records automatically without an owner-approved cleanup plan.",
            },
            "next_action": (
                "Review candidate smoke records, keep them isolated, and only add deletion tooling after an owner-approved retention policy."
                if candidate_count
                else "No current-company smoke data markers detected."
            ),
            "secret_exposed": False,
        }

    def list_merchant_memory(
        self,
        *,
        company_id: str,
        store_id: str | None = None,
        memory_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        where = "company_id = ?"
        if store_id:
            where += " and store_id = ?"
            params.append(store_id)
        if memory_type:
            where += " and memory_type = ?"
            params.append(memory_type)
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from merchant_memory
                where {where}
                order by importance desc, created_at desc
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [self._merchant_memory_row_to_dict(row) for row in rows]

    def save_merchant_ceo_command(
        self,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        self.initialize()
        command_record = _normalize_merchant_ceo_command(command, store_id=store_id)
        command_id = command_record["id"]
        memory_policy = _merchant_ceo_memory_policy(command_record)
        memory_written = memory_policy != AI_CEO_TRANSIENT_MEMORY_POLICY
        memory_type = _merchant_ceo_memory_type(command_record)
        route_labels = [str(route.get("label") or route.get("view") or "") for route in command_record.get("routes", [])]
        source_record = {
            "id": f"ceo-command-source-{command_id}",
            "source_type": MERCHANT_CEO_COMMAND_SOURCE_TYPE,
            "title": f"AI CEO command: {command_record['title']}",
            "note": f"{command_record['text']}; routes: {', '.join([label for label in route_labels if label]) or 'pending'}",
            "status": "merchant_command_recorded",
            "captured_at": command_record["created_at"],
            "secret_exposed": False,
        }
        memory_payload = {
            **command_record,
            "command_id": command_id,
            "source_record": source_record,
            "module_handoff": {
                "routes": command_record.get("routes", []),
                "source_record_id": source_record["id"],
                "decision_boundary": (
                    "Real publish, procurement payment, price, inventory, refund, ads, policy, "
                    "and sensitive customer promises must stay in the confirmation center."
                ),
                "reports_and_sources_write_back": True,
            },
            "work_record_type": "ai_ceo_merchant_instruction",
            "real_platform_writes_enabled": False,
            "memory_policy": memory_policy,
            "long_term_memory": memory_written,
            "secret_exposed": False,
        }
        tags = [
            "ai_ceo",
            "merchant_command",
            command_record.get("intent") or "listing",
            command_record.get("status") or "ready",
            command_record.get("route") or "general_chat",
            memory_policy,
        ]
        with self._connect() as conn:
            self._upsert_merchant_ceo_command(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                command=command_record,
            )
            if memory_written:
                self._insert_merchant_memory(
                    conn,
                    company_id=company_id,
                    store_id=store_id,
                    memory_type=memory_type,
                    source_type=MERCHANT_CEO_COMMAND_SOURCE_TYPE,
                    source_id=command_id,
                    title=str(command_record["title"]),
                    summary=str(command_record["summary"]),
                    importance=_merchant_ceo_memory_importance(command_record),
                    tags=tags,
                    memory=memory_payload,
                    created_by=user_id,
                )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="user",
                action_type="merchant_ceo.command.recorded",
                target_type="merchant_ceo_command",
                target_id=command_id,
                summary="Merchant AI CEO command was persisted for work-record, source-record and module handoff recovery.",
                details={
                    "command_id": command_id,
                    "intent": command_record.get("intent"),
                    "status": command_record.get("status"),
                    "route_views": [route.get("view") for route in command_record.get("routes", [])],
                    "route": command_record.get("route"),
                    "route_label": command_record.get("route_label"),
                    "memory_policy": memory_policy,
                    "merchant_memory_written": memory_written,
                    "high_risk": bool(command_record.get("high_risk")),
                    "packet_id": command_record.get("packet_id"),
                    "text_excerpt": command_record.get("text"),
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
        return {
            "command": command_record,
            "source_record": source_record,
            "merchant_memory_type": memory_type if memory_written else "",
            "merchant_memory_written": memory_written,
            "memory_policy": memory_policy,
            "audit_action_type": "merchant_ceo.command.recorded",
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    def get_latest_merchant_ceo_command(self, *, company_id: str, store_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from merchant_ceo_commands
                where company_id = ? and store_id = ?
                order by updated_at desc, created_at desc, command_id desc
                limit 1
                """,
                (company_id, store_id),
            ).fetchone()
            if row:
                return self._merchant_ceo_command_row_to_dict(row)
            row = conn.execute(
                """
                select * from merchant_memory
                where company_id = ? and store_id = ? and memory_type = ?
                order by updated_at desc, created_at desc, memory_id desc
                limit 1
                """,
                (company_id, store_id, MERCHANT_CEO_COMMAND_MEMORY_TYPE),
            ).fetchone()
        if not row:
            return None
        memory = self._merchant_memory_row_to_dict(row)
        payload = memory.get("memory") if isinstance(memory.get("memory"), dict) else {}
        command = _normalize_merchant_ceo_command(payload, store_id=store_id)
        return {
            "command": command,
            "source_record": payload.get("source_record") if isinstance(payload.get("source_record"), dict) else None,
            "merchant_memory": memory,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    def sync_ai_ceo_chat_history(
        self,
        *,
        company_id: str,
        user_id: str,
        turns: list[dict[str, Any]],
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Merge a user's sanitized device history into the account timeline."""

        self.initialize()
        bounded_turns = turns[-30:] if isinstance(turns, list) else []
        prepared_turns: list[dict[str, Any]] = []
        for raw_turn in bounded_turns:
            turn = _normalize_ai_ceo_chat_history_turn(raw_turn, company_id=company_id, user_id=user_id)
            if not turn:
                continue
            store_id = str(turn.get("store_id") or "") or None
            if store_id and not self.get_store_for_company(company_id=company_id, store_id=store_id):
                turn["store_id"] = ""
            prepared_turns.append(turn)
        with self._connect() as conn:
            for turn in prepared_turns:
                store_id = str(turn.get("store_id") or "") or None
                assistant_id = str(turn["assistant_id"])
                chat_turn_id = _scoped_ai_ceo_chat_turn_id(
                    company_id=company_id,
                    user_id=user_id,
                    assistant_id=assistant_id,
                )
                updated_at = now_iso()
                existing_row = conn.execute(
                    "select * from ai_ceo_chat_turns where company_id = ? and user_id = ? and assistant_id = ?",
                    (company_id, user_id, assistant_id),
                ).fetchone()
                if existing_row:
                    existing_turn = self._ai_ceo_chat_turn_row_to_dict(existing_row)
                    if _ai_ceo_chat_turn_merge_score(existing_turn) >= _ai_ceo_chat_turn_merge_score(turn):
                        continue
                payload = json.dumps(turn, ensure_ascii=False, default=json_default)
                merge_score = _ai_ceo_chat_turn_merge_score(turn)
                conn.execute(
                    """
                    insert into ai_ceo_chat_turns (
                      chat_turn_id, company_id, user_id, store_id, assistant_id, status, route,
                      merge_score, created_at, updated_at, turn_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict (company_id, user_id, assistant_id) do update set
                      store_id = excluded.store_id,
                      status = excluded.status,
                      route = excluded.route,
                      merge_score = excluded.merge_score,
                      created_at = excluded.created_at,
                      updated_at = excluded.updated_at,
                      turn_json = excluded.turn_json
                    where excluded.merge_score > ai_ceo_chat_turns.merge_score
                    """,
                    (
                        chat_turn_id,
                        company_id,
                        user_id,
                        store_id,
                        assistant_id,
                        str(turn.get("status") or "completed")[:80],
                        str(turn.get("route") or "general_chat")[:80],
                        merge_score,
                        str(turn.get("created_at") or updated_at)[:80],
                        updated_at,
                        payload,
                    ),
                )
            retained_rows = conn.execute(
                """
                select chat_turn_id from ai_ceo_chat_turns
                where company_id = ? and user_id = ?
                order by created_at desc, updated_at desc, chat_turn_id desc
                """,
                (company_id, user_id),
            ).fetchall()
            for stale_row in retained_rows[50:]:
                conn.execute(
                    "delete from ai_ceo_chat_turns where company_id = ? and user_id = ? and chat_turn_id = ?",
                    (company_id, user_id, stale_row["chat_turn_id"]),
                )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=user_id,
                actor_type="user",
                action_type="ai_ceo.chat_history.synced",
                target_type="ai_ceo_account_chat_history",
                target_id=user_id,
                summary="Sanitized AI CEO chat turns were merged into the account-scoped cross-device timeline.",
                details={
                    "submitted_turn_count": len(bounded_turns),
                    "scope": "account",
                    "cross_store": True,
                    "raw_provider_secret_stored": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
        return self.list_ai_ceo_chat_history(company_id=company_id, user_id=user_id, limit=limit)

    def ai_ceo_chat_history_revision(self, *, company_id: str, user_id: str) -> str:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select assistant_id, status, updated_at, turn_json
                from ai_ceo_chat_turns
                where company_id = ? and user_id = ?
                order by assistant_id
                """,
                (company_id, user_id),
            ).fetchall()
        revision_payload = [
            [str(row["assistant_id"] or ""), str(row["status"] or ""), str(row["updated_at"] or ""), str(row["turn_json"] or "")]
            for row in rows
        ]
        digest = hashlib.sha256(json.dumps(revision_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]
        return f"chatrev_{len(rows)}_{digest}"

    def list_ai_ceo_chat_history(
        self,
        *,
        company_id: str,
        user_id: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        self.initialize()
        bounded_limit = min(max(int(limit or 30), 1), 50)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from ai_ceo_chat_turns
                where company_id = ? and user_id = ?
                order by created_at desc, updated_at desc, chat_turn_id desc
                limit ?
                """,
                (company_id, user_id, bounded_limit),
            ).fetchall()
        return [self._ai_ceo_chat_turn_row_to_dict(row) for row in reversed(rows)]

    def refresh_merchant_memory_from_existing_records(
        self,
        *,
        company_id: str,
        store_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.initialize()
        params: list[Any] = [company_id]
        report_where = "t.company_id = ?"
        confirmation_where = "company_id = ?"
        if store_id:
            report_where += " and t.store_id = ?"
            confirmation_where += " and store_id = ?"
            params.append(store_id)
        report_params = tuple(params + [int(limit)])
        confirmation_params = tuple(params + [int(limit)])
        created = 0
        with self._connect() as conn:
            report_rows = conn.execute(
                f"""
                select r.*, t.company_id, t.store_id, t.user_id
                from reports r
                join tasks t on t.task_id = r.task_id
                where {report_where}
                order by r.created_at desc
                limit ?
                """,
                report_params,
            ).fetchall()
            confirmation_rows = conn.execute(
                f"""
                select * from confirmations
                where {confirmation_where}
                order by created_at desc
                limit ?
                """,
                confirmation_params,
            ).fetchall()
            for row in report_rows:
                report = self._report_row_to_dict(row)
                payload = report.get("report") if isinstance(report.get("report"), dict) else {}
                created += int(
                    self._insert_merchant_memory(
                        conn,
                        company_id=str(row["company_id"]),
                        store_id=str(row["store_id"]),
                        memory_type="ai_report",
                        source_type="report",
                        source_id=str(row["report_id"]),
                        title=str(row["title"]),
                        summary=_memory_summary_from_report(payload),
                        importance=_memory_importance_from_report(payload),
                        tags=[str(row["report_type"]), str(row["status"]), "jiejing_runtime"],
                        memory={
                            "report_id": row["report_id"],
                            "task_id": row["task_id"],
                            "runtime_run_id": row["runtime_run_id"],
                            "report_type": row["report_type"],
                            "report_status": row["status"],
                            "real_platform_writes_enabled": False,
                            "secret_exposed": False,
                        },
                        created_by=user_id or row["user_id"],
                    )
                )
            for row in confirmation_rows:
                item = _load_json_field(row["item_json"])
                created += int(
                    self._insert_merchant_memory(
                        conn,
                        company_id=row["company_id"],
                        store_id=row["store_id"],
                        memory_type="confirmation_boundary",
                        source_type="confirmation",
                        source_id=row["confirmation_id"],
                        title=row["title"],
                        summary=_memory_summary_from_confirmation(item if isinstance(item, dict) else {}),
                        importance=90 if row["action_type"] in HIGH_RISK_ACTIONS else 70,
                        tags=[row["action_type"], "confirmation_center", row["status"]],
                        memory={
                            "confirmation_id": row["confirmation_id"],
                            "task_id": row["task_id"],
                            "runtime_run_id": row["runtime_run_id"],
                            "action_type": row["action_type"],
                            "default_action": row["default_action"],
                            "status": row["status"],
                            "real_platform_writes_enabled": False,
                            "secret_exposed": False,
                        },
                        created_by=user_id or row["decided_by"],
                    )
                )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="system",
                action_type="merchant_memory.refresh",
                target_type="merchant_memory",
                target_id=store_id or company_id,
                summary="Merchant memory was refreshed from existing reports and confirmation items.",
                details={"inserted_or_updated": created, "limit": limit, "secret_exposed": False},
            )
        return {
            "status": "refreshed",
            "inserted_or_updated": created,
            "store_id": store_id,
            "limit": limit,
            "secret_exposed": False,
        }

    def get_confirmation(self, *, company_id: str, confirmation_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "select * from confirmations where company_id = ? and confirmation_id = ?",
                (company_id, confirmation_id),
            ).fetchone()
        return self._confirmation_row_to_dict(row) if row else None

    def create_confirmation(
        self,
        *,
        company_id: str,
        store_id: str | None,
        task_id: str | None,
        runtime_run_id: str,
        action_type: str,
        title: str,
        item: dict[str, Any],
        created_by: str | None = None,
        confirmation_id: str | None = None,
        default_action: str = "hold",
    ) -> dict[str, Any]:
        self.initialize()
        record_id = confirmation_id or _id("confirm")
        created_at = now_iso()
        safe_item = _redact_secret_like(
            {
                **(item if isinstance(item, dict) else {}),
                "confirmation_id": record_id,
                "action_type": action_type,
                "title": title,
                "default_action": default_action,
                "secret_exposed": False,
            }
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into confirmations (
                  confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status,
                  default_action, created_at, item_json, decided_by, decided_at, decision_note
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    company_id,
                    store_id,
                    task_id,
                    runtime_run_id,
                    action_type,
                    title,
                    "pending",
                    default_action,
                    created_at,
                    json.dumps(safe_item, ensure_ascii=False, default=json_default),
                    None,
                    None,
                    None,
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=created_by,
                actor_type="system",
                action_type="confirmation.created",
                target_type="confirmation",
                target_id=record_id,
                summary="A new confirmation item was created from a controlled SaaS workflow.",
                details={"action_type": action_type, "source": safe_item.get("source"), "secret_exposed": False},
            )
            self._insert_merchant_memory(
                conn,
                company_id=company_id,
                store_id=store_id,
                memory_type="confirmation_boundary",
                source_type="confirmation",
                source_id=record_id,
                title=title,
                summary=_memory_summary_from_confirmation(safe_item),
                importance=90 if action_type in HIGH_RISK_ACTIONS else 70,
                tags=[action_type, "confirmation_center", "risk_control"],
                memory={
                    "confirmation_id": record_id,
                    "action_type": action_type,
                    "high_risk": action_type in HIGH_RISK_ACTIONS,
                    "secret_exposed": False,
                },
                created_by=created_by,
            )
        return self.get_confirmation(company_id=company_id, confirmation_id=record_id) or {}

    def decide_confirmation(
        self,
        *,
        company_id: str,
        confirmation_id: str,
        decision: str,
        decided_by: str,
        note: str | None,
    ) -> dict[str, Any]:
        self.initialize()
        if decision not in {"approve", "reject", "modify"}:
            raise ValueError("decision must be approve, reject, or modify")
        existing = self.get_confirmation(company_id=company_id, confirmation_id=confirmation_id)
        if not existing:
            raise KeyError("confirmation not found")
        decided_at = now_iso()
        status = {"approve": "approved", "reject": "rejected", "modify": "needs_revision"}[decision]
        with self._connect() as conn:
            conn.execute(
                """
                update confirmations
                set status = ?, decided_by = ?, decided_at = ?, decision_note = ?
                where company_id = ? and confirmation_id = ?
                """,
                (status, decided_by, decided_at, note, company_id, confirmation_id),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=existing["store_id"],
                user_id=decided_by,
                actor_type="user",
                action_type=f"confirmation.{decision}",
                target_type="confirmation",
                target_id=confirmation_id,
                summary=f"Merchant decision recorded: {decision}.",
                details={"action_type": existing["action_type"], "note": note},
            )
        return self.get_confirmation(company_id=company_id, confirmation_id=confirmation_id) or {}

    def save_execution_result(self, *, confirmation: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        execution_id = _id("exec")
        created_at = result.get("created_at") or now_iso()
        incoming_idempotency = _execution_idempotency(result)
        with self._connect() as conn:
            duplicate = _find_execution_duplicate(
                conn=conn,
                confirmation_id=confirmation["confirmation_id"],
                action_type=confirmation["action_type"],
                incoming_idempotency=incoming_idempotency,
            )
            if duplicate:
                duplicate_status = "duplicate_execution_suppressed"
                if duplicate.get("idempotency_conflict"):
                    duplicate_status = "blocked_idempotency_conflict"
                self._insert_audit(
                    conn,
                    company_id=confirmation["company_id"],
                    store_id=confirmation["store_id"],
                    user_id=confirmation.get("decided_by"),
                    actor_type="system",
                    action_type="execution_service.duplicate_guard",
                    target_type="execution",
                    target_id=duplicate.get("execution_id"),
                    summary="ExecutionService duplicate guard handled a repeated execution request.",
                    details={
                        "status": duplicate_status,
                        "duplicate_prevention_key": incoming_idempotency.get("duplicate_prevention_key"),
                        "payload_hash": incoming_idempotency.get("payload_hash"),
                        "secret_exposed": False,
                    },
                )
                return {
                    "execution_id": duplicate.get("execution_id"),
                    "status": duplicate_status,
                    "action_type": confirmation["action_type"],
                    "task_id": confirmation["task_id"],
                    "message": (
                        "Execution was not inserted again because the idempotency key was already used."
                        if duplicate_status == "duplicate_execution_suppressed"
                        else "Execution is blocked because the same idempotency key was reused with a different payload."
                    ),
                    "created_at": now_iso(),
                    "audit": {
                        "duplicate_guard": True,
                        "previous_execution_id": duplicate.get("execution_id"),
                        "idempotency": incoming_idempotency,
                        "real_execution": {
                            "published_to_ebay": False,
                            "procurement_paid": False,
                            "refund_executed": False,
                            "ad_budget_changed": False,
                            "store_policy_changed": False,
                        },
                    },
                }
            conn.execute(
                """
                insert into execution_results (
                  execution_id, confirmation_id, task_id, action_type, status, created_at, result_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    confirmation["confirmation_id"],
                    confirmation["task_id"],
                    confirmation["action_type"],
                    str(result.get("status") or "unknown"),
                    created_at,
                    json.dumps(result, ensure_ascii=False, default=json_default),
                ),
            )
            self._insert_audit(
                conn,
                company_id=confirmation["company_id"],
                store_id=confirmation["store_id"],
                user_id=confirmation.get("decided_by"),
                actor_type="system",
                action_type="execution_service.result",
                target_type="execution",
                target_id=execution_id,
                summary="ExecutionService returned a result.",
                details={"status": result.get("status"), "real_execution": result.get("audit", {}).get("real_execution")},
            )
        return {"execution_id": execution_id, **result}

    def list_execution_results(self, *, company_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = [company_id]
        limit_clause = ""
        if limit and limit > 0:
            limit_clause = "limit ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select e.* from execution_results e
                join confirmations c on c.confirmation_id = e.confirmation_id
                where c.company_id = ?
                order by e.created_at desc
                {limit_clause}
                """,
                tuple(params),
            ).fetchall()
        return [self._execution_row_to_dict(row) for row in rows]

    def write_audit(
        self,
        *,
        company_id: str,
        user_id: str | None,
        action_type: str,
        target_type: str,
        target_id: str | None,
        summary: str,
        details: dict[str, Any] | None = None,
        store_id: str | None = None,
        actor_type: str = "user",
    ) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            record = self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type=actor_type,
                action_type=action_type,
                target_type=target_type,
                target_id=target_id,
                summary=summary,
                details=details or {},
            )
        return record

    def get_billing_subscription(self, *, company_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select company_id, provider, provider_customer_id, provider_subscription_id,
                       plan_key, provider_plan_id, status, entitlement_active,
                       payment_attention_required, updated_at, subscription_json
                from billing_subscriptions
                where company_id = ?
                """,
                (company_id,),
            ).fetchone()
        return self._billing_subscription_row_to_dict(row) if row else None

    @contextmanager
    def media_credit_company_lock(self, *, company_id: str) -> Iterator[None]:
        """Serialize one tenant's media-point balance mutations."""

        normalized_company = str(company_id or "").strip()
        if not normalized_company:
            raise ValueError("company_id is required for media credit lock")
        digest = hashlib.sha256(f"jiejing-media-credit:{normalized_company}".encode("utf-8")).digest()
        if self.database_engine == "postgres":
            advisory_key = int.from_bytes(digest[:8], "big", signed=True)
            with self._connect() as conn:
                conn.execute("select pg_advisory_lock(?)", (advisory_key,)).fetchone()
                try:
                    yield
                finally:
                    conn.execute("select pg_advisory_unlock(?)", (advisory_key,)).fetchone()
            return
        lock = _MEDIA_CREDIT_COMPANY_LOCKS[int.from_bytes(digest[:2], "big") % len(_MEDIA_CREDIT_COMPANY_LOCKS)]
        with lock:
            yield

    def get_media_credit_account(self, *, company_id: str) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select company_id, balance_points, reserved_points, lifetime_granted_points,
                       lifetime_spent_points, updated_at, account_json
                from media_credit_accounts where company_id = ?
                """,
                (company_id,),
            ).fetchone()
        if row:
            return self._media_credit_account_row_to_dict(row)
        return {
            "balance_points": 0,
            "reserved_points": 0,
            "available_points": 0,
            "lifetime_granted_points": 0,
            "lifetime_spent_points": 0,
            "updated_at": "",
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def upsert_platform_trial_activation(
        self,
        *,
        company_id: str,
        user_id: str,
        status: str,
        platform_trial_allowed: bool,
        welcome_media_points_granted: int = 0,
        requires_challenge: bool,
        challenge_attested: bool,
        decision_reason: str,
    ) -> dict[str, Any]:
        """Persist a sanitized tenant trial decision without client IPs or provider secrets."""

        self.initialize()
        safe_status = str(status or "verification_required").strip().lower()
        if safe_status not in {"active", "verification_required", "activation_budget_exhausted"}:
            raise ValueError("unsupported platform trial activation status")
        now = now_iso()
        activated_at = now if safe_status == "active" else None
        record = {
            "contract_version": "2026-07-15-platform-trial-activation-v1",
            "status": safe_status,
            "platform_trial_allowed": bool(platform_trial_allowed),
            "welcome_media_points_granted": max(0, int(welcome_media_points_granted)),
            "requires_challenge": bool(requires_challenge),
            "challenge_attested": bool(challenge_attested),
            "merchant_byok_unaffected": True,
            "decision_reason": str(decision_reason or safe_status)[:120],
            "activated_at": activated_at or "",
            "updated_at": now,
            "raw_client_ip_persisted": False,
            "frontend_can_grant_trial": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert into platform_trial_activations (
                  company_id, user_id, status, activated_at, updated_at, activation_json
                ) values (?, ?, ?, ?, ?, ?)
                on conflict (company_id) do update set
                  user_id = excluded.user_id,
                  status = excluded.status,
                  activated_at = coalesce(platform_trial_activations.activated_at, excluded.activated_at),
                  updated_at = excluded.updated_at,
                  activation_json = excluded.activation_json
                """,
                (
                    company_id,
                    user_id,
                    safe_status,
                    activated_at,
                    now,
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=user_id,
                actor_type="system",
                action_type="platform_trial_activation_decided",
                target_type="platform_trial_activation",
                target_id=company_id,
                summary="Platform-funded trial activation decision recorded",
                details={
                    "status": safe_status,
                    "platform_trial_allowed": bool(platform_trial_allowed),
                    "welcome_media_points_granted": max(0, int(welcome_media_points_granted)),
                    "raw_client_ip_persisted": False,
                },
            )
        return record

    def get_platform_trial_activation(self, *, company_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select activation_json
                from platform_trial_activations
                where company_id = ?
                """,
                (company_id,),
            ).fetchone()
        if not row:
            return None
        value = _load_json_field(row["activation_json"])
        return value if isinstance(value, dict) else None

    def list_media_credit_ledger(self, *, company_id: str, limit: int = 30) -> list[dict[str, Any]]:
        self.initialize()
        safe_limit = min(max(int(limit), 1), 100)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select ledger_id, company_id, user_id, operation_type, points, status,
                       reference_type, reference_id, reservation_id, created_at, updated_at, ledger_json
                from media_credit_ledger
                where company_id = ?
                order by created_at desc, ledger_id desc
                limit ?
                """,
                (company_id, safe_limit),
            ).fetchall()
        return [self._media_credit_ledger_row_to_dict(row) for row in rows]

    def apply_media_credit_operation(
        self,
        *,
        company_id: str,
        user_id: str | None,
        operation_type: str,
        points: int,
        idempotency_key: str,
        reference_type: str,
        reference_id: str,
        reservation_id: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one idempotent grant, reserve, settle, release, or revoke operation."""

        self.initialize()
        operation = str(operation_type or "").strip().lower()
        if operation not in {"grant", "reserve", "settle", "release", "revoke"}:
            raise ValueError("unsupported media credit operation")
        safe_points = int(points)
        if safe_points <= 0:
            raise ValueError("media credit points must be positive")
        raw_idempotency = str(idempotency_key or "").strip()
        if len(raw_idempotency) < 8 or len(raw_idempotency) > 200:
            raise ValueError("media credit idempotency key is invalid")
        safe_reference_type = str(reference_type or "media_job").strip()[:64]
        safe_reference_id = str(reference_id or "").strip()[:160]
        safe_reservation_id = str(reservation_id or "").strip()[:80]
        idempotency_hash = hashlib.sha256(f"{company_id}|{raw_idempotency}".encode("utf-8")).hexdigest()
        safe_details = _redact_secret_like(details or {})

        with self.media_credit_company_lock(company_id=company_id):
            with self._connect() as conn:
                existing = conn.execute(
                    """
                    select ledger_id, company_id, user_id, operation_type, points, status,
                           reference_type, reference_id, reservation_id, created_at, updated_at, ledger_json
                    from media_credit_ledger
                    where company_id = ? and idempotency_key_hash = ?
                    """,
                    (company_id, idempotency_hash),
                ).fetchone()
                if existing:
                    account_row = self._ensure_media_credit_account_row(conn, company_id=company_id)
                    return {
                        "account": self._media_credit_account_row_to_dict(account_row),
                        "ledger_entry": self._media_credit_ledger_row_to_dict(existing),
                        "duplicate_request": True,
                        "secret_exposed": False,
                    }

                account_row = self._ensure_media_credit_account_row(conn, company_id=company_id)
                balance = int(account_row["balance_points"] or 0)
                reserved = int(account_row["reserved_points"] or 0)
                lifetime_granted = int(account_row["lifetime_granted_points"] or 0)
                lifetime_spent = int(account_row["lifetime_spent_points"] or 0)
                if operation in {"settle", "release"} or (operation == "revoke" and safe_reservation_id):
                    if not safe_reservation_id:
                        raise ValueError("reservation_id is required")
                    reservation = conn.execute(
                        """
                        select ledger_id, operation_type, points, status
                        from media_credit_ledger
                        where company_id = ? and ledger_id = ?
                        """,
                        (company_id, safe_reservation_id),
                    ).fetchone()
                    if not reservation or reservation["operation_type"] != "reserve" or reservation["status"] != "reserved":
                        raise ValueError("media credit reservation is not available")
                    reserved_by_entry = int(reservation["points"] or 0)
                    if operation in {"settle", "revoke"} and safe_points > reserved_by_entry:
                        raise ValueError("settlement exceeds reserved media points")
                    reserved = max(0, reserved - reserved_by_entry)
                    if operation == "settle":
                        if balance < safe_points:
                            raise ValueError("insufficient media point balance")
                        balance -= safe_points
                        lifetime_spent += safe_points
                    elif operation == "revoke":
                        balance -= safe_points
                    conn.execute(
                        "update media_credit_ledger set status = ?, updated_at = ? where company_id = ? and ledger_id = ?",
                        (
                            "settled" if operation == "settle" else "revoked" if operation == "revoke" else "released",
                            now_iso(),
                            company_id,
                            safe_reservation_id,
                        ),
                    )
                elif operation == "grant":
                    balance += safe_points
                    lifetime_granted += safe_points
                elif operation == "revoke":
                    # A provider-confirmed refund must remove its purchased points even
                    # when they were already consumed. A negative balance prevents more
                    # generation until the merchant tops up, closing refund abuse.
                    balance -= safe_points
                else:
                    if safe_points > balance - reserved:
                        raise ValueError("insufficient available media points")
                    reserved += safe_points

                now = now_iso()
                account_payload = {
                    "contract_version": "2026-07-14-media-points-account-v1",
                    "provider_neutral": True,
                    "secret_exposed": False,
                }
                conn.execute(
                    """
                    update media_credit_accounts
                    set balance_points = ?, reserved_points = ?, lifetime_granted_points = ?,
                        lifetime_spent_points = ?, updated_at = ?, account_json = ?
                    where company_id = ?
                    """,
                    (
                        balance,
                        reserved,
                        lifetime_granted,
                        lifetime_spent,
                        now,
                        json.dumps(account_payload, ensure_ascii=False),
                        company_id,
                    ),
                )
                ledger_id = _id("mcredit")
                ledger_status = "reserved" if operation == "reserve" else "completed"
                ledger_payload = {
                    "contract_version": "2026-07-14-media-points-ledger-v1",
                    "operation_type": operation,
                    "reference_type": safe_reference_type,
                    "reference_id": safe_reference_id,
                    "details": safe_details,
                    "provider_neutral": True,
                    "secret_exposed": False,
                }
                conn.execute(
                    """
                    insert into media_credit_ledger (
                      ledger_id, company_id, user_id, operation_type, points, status,
                      reference_type, reference_id, reservation_id, idempotency_key_hash,
                      created_at, updated_at, ledger_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ledger_id,
                        company_id,
                        user_id,
                        operation,
                        safe_points,
                        ledger_status,
                        safe_reference_type,
                        safe_reference_id,
                        safe_reservation_id or None,
                        idempotency_hash,
                        now,
                        now,
                        json.dumps(ledger_payload, ensure_ascii=False),
                    ),
                )
                account_row = conn.execute(
                    """
                    select company_id, balance_points, reserved_points, lifetime_granted_points,
                           lifetime_spent_points, updated_at, account_json
                    from media_credit_accounts where company_id = ?
                    """,
                    (company_id,),
                ).fetchone()
                ledger_row = conn.execute(
                    """
                    select ledger_id, company_id, user_id, operation_type, points, status,
                           reference_type, reference_id, reservation_id, created_at, updated_at, ledger_json
                    from media_credit_ledger where company_id = ? and ledger_id = ?
                    """,
                    (company_id, ledger_id),
                ).fetchone()
        return {
            "account": self._media_credit_account_row_to_dict(account_row),
            "ledger_entry": self._media_credit_ledger_row_to_dict(ledger_row),
            "duplicate_request": False,
            "secret_exposed": False,
        }

    def _ensure_media_credit_account_row(self, conn: Any, *, company_id: str) -> Any:
        now = now_iso()
        conn.execute(
            """
            insert or ignore into media_credit_accounts (
              company_id, balance_points, reserved_points, lifetime_granted_points,
              lifetime_spent_points, updated_at, account_json
            ) values (?, 0, 0, 0, 0, ?, ?)
            """,
            (
                company_id,
                now,
                json.dumps({"contract_version": "2026-07-14-media-points-account-v1", "provider_neutral": True}, ensure_ascii=False),
            ),
        )
        row = conn.execute(
            """
            select company_id, balance_points, reserved_points, lifetime_granted_points,
                   lifetime_spent_points, updated_at, account_json
            from media_credit_accounts where company_id = ?
            """,
            (company_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("media credit account was not persisted")
        return row

    def create_domestic_billing_order_record(
        self,
        *,
        order_id: str,
        company_id: str,
        user_id: str,
        provider: str,
        plan_key: str,
        amount_minor: int,
        currency: str,
        duration_days: int,
        status: str,
        idempotency_key_hash: str,
        order: dict[str, Any],
        provider_order_id: str = "",
        expires_at: str | None = None,
        paid_at: str | None = None,
    ) -> dict[str, Any]:
        """Create one sanitized domestic order or return its idempotent predecessor."""

        self.initialize()
        created_at = now_iso()
        safe_order = _redact_secret_like(order)
        with self._connect() as conn:
            inserted = conn.execute(
                """
                insert or ignore into billing_orders (
                  order_id, company_id, user_id, provider, provider_order_id,
                  plan_key, amount_minor, currency, duration_days, status,
                  idempotency_key_hash, expires_at, paid_at, created_at, updated_at, order_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    company_id,
                    user_id,
                    provider,
                    provider_order_id or None,
                    plan_key,
                    int(amount_minor),
                    currency,
                    int(duration_days),
                    status,
                    idempotency_key_hash,
                    expires_at,
                    paid_at,
                    created_at,
                    created_at,
                    json.dumps(safe_order, ensure_ascii=False),
                ),
            ).rowcount
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and idempotency_key_hash = ?
                """,
                (company_id, idempotency_key_hash),
            ).fetchone()
            if inserted:
                self._insert_audit(
                    conn,
                    company_id=company_id,
                    store_id=None,
                    user_id=user_id,
                    actor_type="user",
                    action_type="billing.domestic_order.created",
                    target_type="billing_order",
                    target_id=order_id,
                    summary="Domestic billing order created inside the backend payment boundary.",
                    details={
                        "provider": provider,
                        "plan_key": plan_key,
                        "amount_minor": int(amount_minor),
                        "currency": currency,
                        "status": status,
                        "provider_order_created": bool(provider_order_id),
                        "bank_details_persisted": False,
                        "payment_secret_persisted": False,
                        "secret_exposed": False,
                    },
                )
        if not row:
            raise RuntimeError("domestic billing order was not persisted")
        return {**self._domestic_billing_order_row_to_dict(row), "duplicate_request": not bool(inserted)}

    @contextmanager
    def domestic_billing_company_lock(self, *, company_id: str) -> Iterator[None]:
        """Serialize entitlement mutations for one company across callbacks and workers."""

        normalized_company = str(company_id or "").strip()
        if not normalized_company:
            raise ValueError("company_id is required for domestic billing lock")
        digest = hashlib.sha256(f"jiejing-domestic-billing:{normalized_company}".encode("utf-8")).digest()
        if self.database_engine == "postgres":
            advisory_key = int.from_bytes(digest[:8], "big", signed=True)
            with self._connect() as conn:
                conn.execute("select pg_advisory_lock(?)", (advisory_key,)).fetchone()
                try:
                    yield
                finally:
                    conn.execute("select pg_advisory_unlock(?)", (advisory_key,)).fetchone()
            return

        lock = _DOMESTIC_BILLING_COMPANY_LOCKS[int.from_bytes(digest[:2], "big") % len(_DOMESTIC_BILLING_COMPANY_LOCKS)]
        with lock:
            yield

    def get_domestic_billing_order(self, *, company_id: str, order_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
        return self._domestic_billing_order_row_to_dict(row) if row else None

    def find_domestic_billing_order_for_provider(self, *, provider: str, order_id: str) -> dict[str, Any] | None:
        """Resolve a provider callback without exposing a cross-tenant merchant API."""

        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where provider = ? and order_id = ?
                """,
                (provider, order_id),
            ).fetchone()
        return self._domestic_billing_order_row_to_dict(row) if row else None

    def mark_domestic_billing_order_paid(
        self,
        *,
        company_id: str,
        order_id: str,
        provider_order_id: str,
        paid_at: str,
        payment: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist a verified payment result without raw callback or payment secrets."""

        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            if not existing:
                return None
            current = self._domestic_billing_order_row_to_dict(existing)
            current_provider_order = str(current.get("provider_order_id") or "")
            if current.get("status") == "paid" and current_provider_order and current_provider_order != provider_order_id:
                raise ValueError("paid domestic order has a different provider transaction")
            if current.get("status") == "paid" and current_provider_order == provider_order_id:
                return current
            conflicting = conn.execute(
                """
                select order_id
                from billing_orders
                where provider = ? and provider_order_id = ? and order_id != ?
                limit 1
                """,
                (str(current.get("provider") or ""), provider_order_id, order_id),
            ).fetchone()
            if conflicting:
                raise ValueError("provider transaction is already bound to another domestic billing order")
            safe_order = current.get("order") if isinstance(current.get("order"), dict) else {}
            safe_order = _without_domestic_checkout_uri(safe_order)
            safe_order = _redact_secret_like(
                {
                    **safe_order,
                    "payment": payment,
                    "raw_callback_persisted": False,
                    "raw_signature_persisted": False,
                    "payment_secret_persisted": False,
                    "secret_exposed": False,
                }
            )
            updated = conn.execute(
                """
                update billing_orders
                set provider_order_id = ?, status = ?, paid_at = ?, updated_at = ?, order_json = ?
                where company_id = ? and order_id = ? and status = 'pending_payment'
                """,
                (
                    provider_order_id,
                    "paid",
                    paid_at,
                    updated_at,
                    json.dumps(safe_order, ensure_ascii=False),
                    company_id,
                    order_id,
                ),
            ).rowcount
            if not updated:
                latest = conn.execute(
                    """
                    select order_id, company_id, user_id, provider, provider_order_id,
                           plan_key, amount_minor, currency, duration_days, status,
                           expires_at, paid_at, created_at, updated_at, order_json
                    from billing_orders
                    where company_id = ? and order_id = ?
                    """,
                    (company_id, order_id),
                ).fetchone()
                if latest:
                    latest_order = self._domestic_billing_order_row_to_dict(latest)
                    if latest_order.get("status") == "paid" and str(latest_order.get("provider_order_id") or "") == provider_order_id:
                        return latest_order
                raise ValueError("domestic billing order is no longer payable")
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=None,
                actor_type="system",
                action_type="billing.domestic_order.payment_verified",
                target_type="billing_order",
                target_id=order_id,
                summary="Verified domestic payment marked the billing order as paid.",
                details={
                    "provider": current.get("provider"),
                    "plan_key": current.get("plan_key"),
                    "amount_minor": current.get("amount_minor"),
                    "currency": current.get("currency"),
                    "signature_verified": payment.get("signature_verified") is True,
                    "amount_verified": payment.get("amount_verified") is True,
                    "raw_callback_persisted": False,
                    "raw_signature_persisted": False,
                    "secret_exposed": False,
                },
            )
        return self._domestic_billing_order_row_to_dict(row) if row else None

    def attach_domestic_billing_checkout(
        self,
        *,
        company_id: str,
        order_id: str,
        code_url: str,
    ) -> dict[str, Any] | None:
        """Attach only the tenant-visible Native QR URL, never the raw provider response."""

        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            if not existing:
                return None
            current = self._domestic_billing_order_row_to_dict(existing)
            if current.get("status") != "pending_payment":
                return current
            safe_order = current.get("order") if isinstance(current.get("order"), dict) else {}
            safe_order = _redact_secret_like(
                {
                    **safe_order,
                    "provider_order_created": True,
                    "payable_qr_created": True,
                    "checkout": {
                        "code_url": str(code_url or "").strip(),
                        "raw_provider_response_persisted": False,
                        "payment_secret_persisted": False,
                        "secret_exposed": False,
                    },
                    "payment_secret_persisted": False,
                    "secret_exposed": False,
                }
            )
            updated = conn.execute(
                """
                update billing_orders
                set updated_at = ?, order_json = ?
                where company_id = ? and order_id = ? and status = 'pending_payment'
                """,
                (updated_at, json.dumps(safe_order, ensure_ascii=False), company_id, order_id),
            ).rowcount
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            if updated != 1:
                return self._domestic_billing_order_row_to_dict(row) if row else None
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=None,
                user_id=None,
                actor_type="system",
                action_type="billing.domestic_order.checkout_created",
                target_type="billing_order",
                target_id=order_id,
                summary="WeChat Pay Native checkout was attached to the tenant billing order.",
                details={
                    "provider": current.get("provider"),
                    "plan_key": current.get("plan_key"),
                    "payable_qr_created": True,
                    "raw_provider_response_persisted": False,
                    "payment_secret_persisted": False,
                    "secret_exposed": False,
                },
            )
        return self._domestic_billing_order_row_to_dict(row) if row else None

    def update_domestic_billing_order_state(
        self,
        *,
        company_id: str,
        order_id: str,
        status: str,
        allowed_current_statuses: set[str],
        state_details: dict[str, Any],
        audit_action: str,
        audit_summary: str,
        user_id: str | None = None,
        calls_external_payment_api: bool = False,
        triggers_real_refund: bool = False,
    ) -> dict[str, Any] | None:
        """Apply one allowlisted domestic billing state transition."""

        allowed_targets = {
            "closed",
            "payment_failed",
            "refund_review_requested",
            "refund_processing",
            "refunded",
            "refund_failed",
        }
        if status not in allowed_targets:
            raise ValueError("domestic billing target status is not allowed")
        self.initialize()
        updated_at = now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            if not existing:
                return None
            current = self._domestic_billing_order_row_to_dict(existing)
            current_status = str(current.get("status") or "")
            duplicate_transition = current_status == status
            if not duplicate_transition and current_status not in allowed_current_statuses:
                raise ValueError("domestic billing state transition is not allowed")
            safe_order = current.get("order") if isinstance(current.get("order"), dict) else {}
            if status in {"closed", "payment_failed", "refunded"}:
                safe_order = _without_domestic_checkout_uri(safe_order)
            safe_order = _redact_secret_like(
                {
                    **safe_order,
                    "state": {**(safe_order.get("state") if isinstance(safe_order.get("state"), dict) else {}), **state_details},
                    "payment_secret_persisted": False,
                    "secret_exposed": False,
                }
            )
            if not duplicate_transition:
                updated = conn.execute(
                    """
                    update billing_orders
                    set status = ?, updated_at = ?, order_json = ?
                    where company_id = ? and order_id = ? and status = ?
                    """,
                    (
                        status,
                        updated_at,
                        json.dumps(safe_order, ensure_ascii=False),
                        company_id,
                        order_id,
                        current_status,
                    ),
                ).rowcount
                if updated != 1:
                    latest = conn.execute(
                        """
                        select order_id, company_id, user_id, provider, provider_order_id,
                               plan_key, amount_minor, currency, duration_days, status,
                               expires_at, paid_at, created_at, updated_at, order_json
                        from billing_orders
                        where company_id = ? and order_id = ?
                        """,
                        (company_id, order_id),
                    ).fetchone()
                    if not latest:
                        return None
                    latest_order = self._domestic_billing_order_row_to_dict(latest)
                    if str(latest_order.get("status") or "") == status:
                        return {**latest_order, "duplicate_transition": True}
                    raise ValueError("domestic billing state changed concurrently")
            row = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ? and order_id = ?
                """,
                (company_id, order_id),
            ).fetchone()
            if not duplicate_transition:
                self._insert_audit(
                    conn,
                    company_id=company_id,
                    store_id=None,
                    user_id=user_id,
                    actor_type="user" if user_id else "system",
                    action_type=audit_action,
                    target_type="billing_order",
                    target_id=order_id,
                    summary=audit_summary,
                    details={
                        "from_status": current_status,
                        "to_status": status,
                        "provider": current.get("provider"),
                        "plan_key": current.get("plan_key"),
                        "calls_external_payment_api": bool(calls_external_payment_api),
                        "triggers_real_refund": bool(triggers_real_refund),
                        "secret_exposed": False,
                    },
                )
        result = self._domestic_billing_order_row_to_dict(row) if row else None
        return {**result, "duplicate_transition": duplicate_transition} if result else None

    def list_domestic_billing_orders(self, *, company_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        safe_limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                select order_id, company_id, user_id, provider, provider_order_id,
                       plan_key, amount_minor, currency, duration_days, status,
                       expires_at, paid_at, created_at, updated_at, order_json
                from billing_orders
                where company_id = ?
                order by created_at desc
                limit ?
                """,
                (company_id, safe_limit),
            ).fetchall()
        return [self._domestic_billing_order_row_to_dict(row) for row in rows]

    def list_domestic_billing_company_ids(self, *, limit: int = 100) -> list[str]:
        """Return a bounded internal tenant list ordered by recent billing activity."""

        self.initialize()
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                select company_id, max(updated_at) as latest_billing_activity
                from billing_orders
                group by company_id
                order by latest_billing_activity desc, company_id asc
                limit ?
                """,
                (safe_limit,),
            ).fetchall()
        return [str(row["company_id"]) for row in rows if str(row["company_id"] or "").strip()]

    def domestic_payment_acceptance_evidence(self) -> dict[str, Any]:
        """Return sanitized aggregate proof for readiness without opening charging.

        This application-layer proof rejects a single billing-order write or a
        direct repository payment mark unless the matching successful
        entitlement event was also persisted by the billing domain. Coordinated
        tampering across all tables by a privileged database administrator is
        outside this threat boundary.
        """

        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select o.order_id, o.company_id, o.provider_order_id, o.plan_key,
                       o.amount_minor, o.currency, o.duration_days, o.paid_at,
                       o.order_json,
                       case when exists (
                         select 1
                         from billing_webhook_events e
                         where e.company_id = o.company_id
                           and e.provider = 'wechat_pay_native'
                           and e.event_type = 'payment_succeeded'
                           and e.status in ('applied', 'applied_duplicate_ignored')
                           and e.event_key = 'wechat_pay_native:' || o.provider_order_id
                       ) then 1 else 0 end as entitlement_event_persisted
                from billing_orders o
                where o.provider = ? and o.status in ('paid', 'refund_review_requested', 'refund_processing', 'refund_failed', 'refunded')
                order by o.paid_at desc
                limit 100
                """,
                ("wechat_pay_native",),
            ).fetchall()
        verified_paid_at: list[str] = []
        for row in rows:
            order_id = str(row["order_id"] or "").strip()
            provider_order_id = str(row["provider_order_id"] or "").strip()
            paid_at = str(row["paid_at"] or "").strip()
            if re.fullmatch(r"JJLIVE[0-9a-f]{26}", order_id) is None:
                continue
            if not str(row["company_id"] or "").strip() or not provider_order_id or not paid_at:
                continue
            if row["entitlement_event_persisted"] != 1:
                continue
            if row["plan_key"] != "starter" or row["amount_minor"] != 100:
                continue
            if row["currency"] != "CNY" or row["duration_days"] != 30:
                continue
            payload = _load_json_field(row["order_json"])
            payment = payload.get("payment") if isinstance(payload, dict) and isinstance(payload.get("payment"), dict) else {}
            if not isinstance(payload, dict):
                continue
            if payload.get("contract_version") != "2026-07-13-wechat-pay-live-acceptance-v1":
                continue
            if payload.get("live_acceptance_test") is not True:
                continue
            if payload.get("provider_mode") != "owner_approved_single_live_acceptance":
                continue
            checkout = payload.get("checkout") if isinstance(payload.get("checkout"), dict) else {}
            if payload.get("provider_order_created") is not True:
                continue
            if payload.get("payable_qr_created") is not False or checkout.get("payable_uri_removed") is not True:
                continue
            if not all(
                payload.get(key) is False
                for key in (
                    "calls_external_payment_api",
                    "triggers_real_charge",
                    "bank_details_persisted",
                    "payment_secret_persisted",
                    "frontend_gets_payment_secret",
                    "secret_exposed",
                )
            ):
                continue
            if payment.get("provider_transaction_present") is not True:
                continue
            if type(payment.get("amount_minor")) is not int or payment.get("amount_minor") != 100:
                continue
            if payment.get("currency") != "CNY" or payment.get("purchase_type") != "subscription":
                continue
            verification_source = payment.get("verification_source")
            signature_verified = payment.get("signature_verified")
            if not (
                (verification_source == "signed_callback" and signature_verified is True)
                or (verification_source == "authenticated_order_query" and signature_verified is False)
            ):
                continue
            if payment.get("trade_type") != "NATIVE":
                continue
            if not str(payment.get("entitlement_active_from") or "").strip():
                continue
            if not str(payment.get("entitlement_active_until") or "").strip():
                continue
            if not all(payment.get(key) is True for key in ("appid_verified", "mchid_verified", "amount_verified")):
                continue
            verified_paid_at.append(paid_at)
        return {
            "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
            "provider": "wechat_pay_native",
            "acceptance_kind": "owner_approved_one_cny_live_acceptance",
            "controlled_acceptance_proven": bool(verified_paid_at),
            "verified_paid_order_count": len(verified_paid_at),
            "latest_verified_paid_at": verified_paid_at[0] if verified_paid_at else "",
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "calls_external_payment_api": False,
            "secret_exposed": False,
        }

    def apply_billing_webhook_event(self, *, event: dict[str, Any]) -> dict[str, Any]:
        """Persist a signed, normalized billing event and update entitlement state.

        The input is the sanitized event from ``billing_webhook``. Raw provider
        payloads and payment secrets must never be passed here.
        """

        self.initialize()
        provider = str(event.get("provider") or "").strip().lower()
        event_type = str(event.get("event_type") or "").strip()
        event_id = str(event.get("event_id") or "").strip()
        provider_customer_id = str(event.get("provider_customer_id") or "").strip()
        provider_subscription_id = str(event.get("provider_subscription_id") or "").strip()
        provider_plan_id = str(event.get("provider_plan_id") or "").strip()
        company_id = str(event.get("company_id") or "").strip()
        if not company_id:
            company_id = self._find_billing_company_id(
                provider=provider,
                provider_customer_id=provider_customer_id,
                provider_subscription_id=provider_subscription_id,
            )
        existing_subscription = self.get_billing_subscription(company_id=company_id) if company_id else None

        now = now_iso()
        event_key = _billing_event_key(provider=provider, event_id=event_id, event_type=event_type, fallback=now)
        status = _billing_entitlement_status(str(event.get("subscription_status") or ""), event_type=event_type)
        plan_key = str(event.get("plan_key") or "").strip().lower() or "unknown"
        if plan_key not in {"free", "starter", "operator", "team", "unknown"}:
            plan_key = "unknown"
        if plan_key == "unknown" and existing_subscription:
            plan_key = str(existing_subscription.get("plan_key") or "unknown")
        if not provider_plan_id and existing_subscription:
            provider_plan_id = str(existing_subscription.get("provider_plan_id") or "")
        if not provider_customer_id and existing_subscription:
            provider_customer_id = str(existing_subscription.get("provider_customer_id") or "")
        if not provider_subscription_id and existing_subscription:
            provider_subscription_id = str(existing_subscription.get("provider_subscription_id") or "")
        entitlement_blockers = _billing_entitlement_apply_blockers(
            event=event,
            event_id=event_id,
            event_type=event_type,
            company_id=company_id,
            provider_customer_id=provider_customer_id,
            provider_subscription_id=provider_subscription_id,
            provider_plan_id=provider_plan_id,
            plan_key=plan_key,
            status=status,
            existing_subscription=existing_subscription,
        )
        event_status = _billing_unmapped_status(entitlement_blockers)
        event_record = _redact_secret_like(
            {
                **event,
                "company_id": company_id or "",
                "event_id_present": bool(event_id),
                "provider_customer_id_present": bool(provider_customer_id),
                "provider_subscription_id_present": bool(provider_subscription_id),
                "provider_plan_id_present": bool(provider_plan_id),
                "entitlement_apply_blockers": entitlement_blockers,
                "raw_payload_persisted": False,
            }
        )
        subscription_record: dict[str, Any] | None = None
        with self._connect() as conn:
            inserted_event = conn.execute(
                """
                insert or ignore into billing_webhook_events (
                  event_key, company_id, provider, event_type, status, created_at, billing_event_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key,
                    company_id or None,
                    provider,
                    event_type,
                    event_status,
                    now,
                    json.dumps(event_record, ensure_ascii=False),
                ),
            ).rowcount
            duplicate_event = inserted_event == 0
            if company_id and not entitlement_blockers:
                if duplicate_event:
                    event_status = "applied_duplicate_ignored"
                    subscription_record = existing_subscription
                    conn.execute(
                        """
                        update billing_webhook_events
                        set company_id = ?, status = ?, billing_event_json = ?
                        where event_key = ?
                        """,
                        (
                            company_id,
                            event_status,
                            json.dumps({**event_record, "status": event_status, "duplicate_event": True}, ensure_ascii=False),
                            event_key,
                        ),
                    )
                    return {
                        "status": event_status,
                        "event_key": event_key,
                        "company_id": company_id or "",
                        "subscription": subscription_record,
                        "duplicate_event": True,
                        "entitlement_apply_blockers": [],
                        "raw_payload_persisted": False,
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    }
                entitlement_active = 1 if status in {"active", "trialing"} else 0
                payment_attention_required = (
                    1
                    if bool(event.get("payment_attention_required")) or status in {"past_due", "unpaid", "canceled", "expired", "refunded", "disputed"}
                    else 0
                )
                subscription_record = {
                    "company_id": company_id,
                    "provider": provider,
                    "provider_customer_id": provider_customer_id,
                    "provider_subscription_id": provider_subscription_id,
                    "plan_key": plan_key,
                    "provider_plan_id": provider_plan_id,
                    "status": status,
                    "entitlement_active": bool(entitlement_active),
                    "payment_attention_required": bool(payment_attention_required),
                    "updated_at": now,
                    "subscription": {
                        "source": "signed_billing_webhook",
                        "event_type": event_type,
                        "event_id_present": bool(event_id),
                        "provider_customer_id_present": bool(provider_customer_id),
                        "provider_subscription_id_present": bool(provider_subscription_id),
                        "provider_plan_id_present": bool(provider_plan_id),
                        "quota_recalculation_required": bool(event.get("quota_recalculation_required")),
                        "raw_payload_persisted": False,
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    },
                    "secret_exposed": False,
                }
                for safe_subscription_key in (
                    "manual_payment_order_id",
                    "amount_cny",
                    "duration_days",
                    "active_until",
                    "manual_reconciliation_required",
                    "private_beta_only",
                ):
                    if safe_subscription_key in event:
                        subscription_record["subscription"][safe_subscription_key] = event.get(safe_subscription_key)
                conn.execute(
                    """
                    insert or replace into billing_subscriptions (
                      company_id, provider, provider_customer_id, provider_subscription_id,
                      plan_key, provider_plan_id, status, entitlement_active,
                      payment_attention_required, updated_at, subscription_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        company_id,
                        provider,
                        provider_customer_id or None,
                        provider_subscription_id or None,
                        plan_key,
                        provider_plan_id or None,
                        status,
                        entitlement_active,
                        payment_attention_required,
                        now,
                        json.dumps(subscription_record["subscription"], ensure_ascii=False),
                    ),
                )
                event_status = "applied_duplicate_ignored" if duplicate_event else "applied"
                conn.execute(
                    """
                    update billing_webhook_events
                    set company_id = ?, status = ?, billing_event_json = ?
                    where event_key = ?
                    """,
                    (
                        company_id,
                        event_status,
                        json.dumps({**event_record, "status": event_status}, ensure_ascii=False),
                        event_key,
                    ),
                )
                self._insert_audit(
                    conn,
                    company_id=company_id,
                    store_id=None,
                    user_id=None,
                    actor_type="system",
                    action_type="billing.webhook.applied",
                    target_type="billing_subscription",
                    target_id=provider_subscription_id or provider_customer_id or company_id,
                    summary="Signed billing webhook updated merchant subscription entitlement.",
                    details={
                        "provider": provider,
                        "event_type": event_type,
                        "plan_key": plan_key,
                        "status": status,
                        "entitlement_active": bool(entitlement_active),
                        "payment_attention_required": bool(payment_attention_required),
                        "duplicate_event": duplicate_event,
                        "raw_payload_persisted": False,
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    },
                )
            elif inserted_event:
                conn.execute(
                    """
                    update billing_webhook_events
                    set company_id = ?, status = ?, billing_event_json = ?
                    where event_key = ?
                    """,
                    (
                        company_id or None,
                        event_status,
                        json.dumps({**event_record, "status": event_status}, ensure_ascii=False),
                        event_key,
                    ),
                )

        return {
            "status": event_status,
            "event_key": event_key,
            "company_id": company_id or "",
            "subscription": subscription_record,
            "duplicate_event": bool(event_status.endswith("ignored")),
            "entitlement_apply_blockers": entitlement_blockers,
            "raw_payload_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    def accept_ebay_account_deletion_event(self, *, event: dict[str, Any]) -> dict[str, Any]:
        """Persist one sanitized eBay deletion receipt and at most one compliance job."""

        self.initialize()
        event_key = str(event.get("event_key") or "")
        payload_sha256 = str(event.get("payload_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", event_key) or not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
            raise ValueError("invalid eBay account deletion event")
        allowed_keys = {
            "event_key", "notification_id_hash", "topic", "schema_version", "deprecated",
            "event_date", "publish_date", "publish_attempt_count", "user_id_hash",
            "username_hash", "eias_identity_hash", "payload_sha256", "signature_present",
            "raw_payload_persisted", "raw_identity_persisted", "secret_exposed",
        }
        safe_event = _redact_secret_like({key: value for key, value in event.items() if key in allowed_keys})
        created_at = now_iso()
        with self._connect() as conn:
            existing = conn.execute("select * from ebay_account_deletion_events where event_key = ?", (event_key,)).fetchone()
            if existing:
                record = _load_json_field(existing["deletion_event_json"])
                if str(record.get("payload_sha256") or "") != payload_sha256:
                    return {
                        "status": "idempotency_conflict", "event_key": event_key, "duplicate": True,
                        "data_mutated": False, "secret_exposed": False,
                    }
                return {
                    **record,
                    "status": str(existing["status"]),
                    "company_id": existing["company_id"],
                    "store_id": existing["store_id"],
                    "connection_id": existing["connection_id"],
                    "task_id": existing["task_id"],
                    "job_id": existing["job_id"],
                    "duplicate": True,
                    "secret_exposed": False,
                }

            match = self._find_ebay_connection_for_deletion(conn, event=safe_event)
            if not match:
                record = {
                    **safe_event,
                    "status": "completed_no_matching_connection",
                    "matched_connection": False,
                    "data_mutated": False,
                    "duplicate": False,
                    "secret_exposed": False,
                }
                conn.execute(
                    """
                    insert into ebay_account_deletion_events (
                      event_key, company_id, store_id, connection_id, task_id, job_id,
                      status, created_at, updated_at, deletion_event_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event_key, None, None, None, None, None, record["status"], created_at, created_at, json.dumps(record, ensure_ascii=False)),
                )
                return record

            company_id = str(match["company_id"])
            store_id = str(match["store_id"])
            connection_id = str(match["connection_id"])
            user_id = str(match["created_by"])
            task_id = _id("task")
            job_id = _id("job")
            task_input = {
                "event_key": event_key,
                "connection_id": connection_id,
                "topic": "MARKETPLACE_ACCOUNT_DELETION",
                "signature_verified": True,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            conn.execute(
                """
                insert into tasks (
                  task_id, company_id, store_id, user_id, runtime_run_id, task_type, title,
                  status, created_at, updated_at, input_json, output_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, company_id, store_id, user_id, None, "ebay_account_deletion_compliance",
                    "eBay marketplace account deletion compliance", "queued", created_at, created_at,
                    json.dumps(task_input, ensure_ascii=False), json.dumps({}, ensure_ascii=False),
                ),
            )
            job_data = {
                "kind": "ebay_account_deletion",
                "event_key": event_key,
                "connection_id": connection_id,
                "signature_verified": True,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            conn.execute(
                """
                insert into queue_jobs (
                  job_id, task_id, company_id, status, attempts, max_attempts,
                  created_at, updated_at, job_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, task_id, company_id, "queued", 0, 5, created_at, created_at, json.dumps(job_data, ensure_ascii=False)),
            )
            record = {
                **safe_event,
                "status": "queued",
                "company_id": company_id,
                "store_id": store_id,
                "connection_id": connection_id,
                "task_id": task_id,
                "job_id": job_id,
                "matched_connection": True,
                "data_mutated": False,
                "duplicate": False,
                "secret_exposed": False,
            }
            conn.execute(
                """
                insert into ebay_account_deletion_events (
                  event_key, company_id, store_id, connection_id, task_id, job_id,
                  status, created_at, updated_at, deletion_event_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_key, company_id, store_id, connection_id, task_id, job_id, "queued",
                    created_at, created_at, json.dumps(record, ensure_ascii=False),
                ),
            )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="system",
                action_type="ebay.account_deletion.received",
                target_type="ebay_account_deletion_event",
                target_id=event_key,
                summary="Verified eBay account deletion notification queued for scoped compliance processing.",
                details={
                    "connection_id": connection_id, "task_id": task_id, "job_id": job_id,
                    "raw_identity_persisted": False, "real_platform_writes_enabled": False, "secret_exposed": False,
                },
            )
        return record

    def ebay_account_deletion_event_count(self) -> int:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("select count(*) as count from ebay_account_deletion_events").fetchone()
        return int(row["count"] if row else 0)

    def process_ebay_account_deletion_event(
        self,
        *,
        event_key: str,
        company_id: str,
        connection_id: str,
    ) -> dict[str, Any]:
        """Irreversibly purge one matched eBay store while preserving a minimal receipt."""

        self.initialize()
        completed_at = now_iso()
        with self._connect() as conn:
            event_row = conn.execute(
                """
                select * from ebay_account_deletion_events
                where event_key = ? and company_id = ? and connection_id = ?
                """,
                (event_key, company_id, connection_id),
            ).fetchone()
            if not event_row:
                raise KeyError("eBay account deletion event not found")
            if str(event_row["status"]) == "completed":
                existing = _load_json_field(event_row["deletion_event_json"])
                return {**existing, "status": "completed", "duplicate": True, "secret_exposed": False}
            connection = conn.execute(
                """
                select * from platform_connections
                where connection_id = ? and company_id = ? and lower(platform) = 'ebay'
                """,
                (connection_id, company_id),
            ).fetchone()
            if not connection or str(connection["store_id"]) != str(event_row["store_id"]):
                raise KeyError("matched eBay connection not found")
            store_id = str(connection["store_id"])
            user_id = str(connection["created_by"])
            store_connections = conn.execute(
                """
                select connection_id, secret_ref from platform_connections
                where company_id = ? and store_id = ? and lower(platform) = 'ebay'
                """,
                (company_id, store_id),
            ).fetchall()
            compliance_task_id = str(event_row["task_id"] or "")
            compliance_job_id = str(event_row["job_id"] or "")
            task_rows = conn.execute(
                "select task_id from tasks where company_id = ? and store_id = ? and task_id <> ?",
                (company_id, store_id, compliance_task_id),
            ).fetchall()
            task_ids = [str(row["task_id"]) for row in task_rows]
            deleted_counts: dict[str, int] = {}

            def delete_where(table: str, where: str, params: tuple[Any, ...]) -> None:
                cursor = conn.execute(f"delete from {table} where {where}", params)
                deleted_counts[table] = int(cursor.rowcount if cursor.rowcount >= 0 else 0)

            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                ids = tuple(task_ids)
                delete_where("execution_results", f"task_id in ({placeholders})", ids)
                delete_where("confirmations", f"task_id in ({placeholders})", ids)
                delete_where("reports", f"task_id in ({placeholders})", ids)
                delete_where("media_asset_jobs", f"task_id in ({placeholders})", ids)
                delete_where("task_steps", f"task_id in ({placeholders})", ids)
                delete_where("queue_jobs", f"task_id in ({placeholders})", ids)
                delete_where("tasks", f"task_id in ({placeholders})", ids)
            delete_where("platform_data_packets", "company_id = ? and store_id = ?", (company_id, store_id))
            delete_where("merchant_memory", "company_id = ? and store_id = ?", (company_id, store_id))
            delete_where("merchant_ceo_commands", "company_id = ? and store_id = ?", (company_id, store_id))
            delete_where("ai_ceo_chat_turns", "company_id = ? and store_id = ?", (company_id, store_id))
            delete_where("audit_logs", "company_id = ? and store_id = ?", (company_id, store_id))

            secret_refs = sorted({str(row["secret_ref"] or "") for row in store_connections if row["secret_ref"]})
            for secret_ref in secret_refs:
                minimal_secret_metadata = {
                    "revoked_for": "ebay_marketplace_account_deletion",
                    "revoked_at": completed_at,
                    "secret_value_stored": False,
                    "secret_exposed": False,
                }
                conn.execute(
                    """
                    update secret_refs set status = ?, metadata_json = ?
                    where company_id = ? and store_id = ? and secret_ref = ?
                    """,
                    (
                        "revoked_account_deleted",
                        json.dumps(minimal_secret_metadata, ensure_ascii=False),
                        company_id,
                        store_id,
                        secret_ref,
                    ),
                )

            connection_metadata = {
                "revoked_for": "ebay_marketplace_account_deletion",
                "revoked_at": completed_at,
                "identity_selectors_removed": True,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            conn.execute(
                """
                update platform_connections
                set status = ?, scopes_json = ?, metadata_json = ?
                where company_id = ? and store_id = ? and lower(platform) = 'ebay'
                """,
                (
                    "revoked_account_deleted",
                    json.dumps([], ensure_ascii=False),
                    json.dumps(connection_metadata, ensure_ascii=False),
                    company_id,
                    store_id,
                ),
            )
            store_row = conn.execute(
                "select store_json from stores where company_id = ? and store_id = ?",
                (company_id, store_id),
            ).fetchone()
            store_record = _load_json_field(store_row["store_json"]) if store_row else {}
            store_record.update(
                {
                    "store_name": "Disconnected eBay store",
                    "stage": "account_deleted",
                    "settings": {},
                    "account_deletion_completed_at": completed_at,
                }
            )
            conn.execute(
                """
                update stores set store_name = ?, stage = ?, store_json = ?
                where company_id = ? and store_id = ?
                """,
                (
                    store_record["store_name"],
                    store_record["stage"],
                    json.dumps(store_record, ensure_ascii=False),
                    company_id,
                    store_id,
                ),
            )
            result = {
                "event_key": event_key,
                "status": "completed",
                "company_id": company_id,
                "store_id": store_id,
                "connection_id": connection_id,
                "task_id": compliance_task_id,
                "job_id": compliance_job_id,
                "completed_at": completed_at,
                "deleted_record_counts": deleted_counts,
                "secret_ref_present": bool(secret_refs),
                "secret_value_deleted_by_worker": False,
                "identity_selectors_removed": True,
                "other_stores_mutated": False,
                "real_platform_write_performed": False,
                "secret_exposed": False,
            }
            conn.execute(
                """
                update ebay_account_deletion_events
                set status = ?, updated_at = ?, deletion_event_json = ?
                where event_key = ?
                """,
                ("completed", completed_at, json.dumps(result, ensure_ascii=False), event_key),
            )
            if compliance_task_id:
                conn.execute(
                    "update tasks set status = ?, updated_at = ?, output_json = ? where task_id = ? and company_id = ?",
                    ("completed", completed_at, json.dumps(result, ensure_ascii=False), compliance_task_id, company_id),
                )
            if compliance_job_id:
                conn.execute(
                    "update queue_jobs set status = ?, updated_at = ?, job_json = ? where job_id = ? and company_id = ?",
                    (
                        "completed",
                        completed_at,
                        json.dumps({"kind": "ebay_account_deletion", "event_key": event_key, "status": "completed", "secret_exposed": False}, ensure_ascii=False),
                        compliance_job_id,
                        company_id,
                    ),
                )
            self._insert_audit(
                conn,
                company_id=company_id,
                store_id=store_id,
                user_id=user_id,
                actor_type="system",
                action_type="ebay.account_deletion.completed",
                target_type="ebay_account_deletion_event",
                target_id=event_key,
                summary="Scoped eBay account data was deleted or irreversibly anonymized.",
                details={
                    "deleted_record_counts": deleted_counts,
                    "identity_selectors_removed": True,
                    "ebay_connections_revoked": len(store_connections),
                    "credential_refs_revoked": len(secret_refs),
                    "other_stores_mutated": False,
                    "real_platform_write_performed": False,
                    "secret_exposed": False,
                },
            )
        return result

    @staticmethod
    def _find_ebay_connection_for_deletion(conn: sqlite3.Connection, *, event: dict[str, Any]) -> sqlite3.Row | None:
        selectors = {
            "ebay_user_id_hash": str(event.get("user_id_hash") or ""),
            "ebay_username_hash": str(event.get("username_hash") or ""),
            "ebay_eias_identity_hash": str(event.get("eias_identity_hash") or ""),
        }
        rows = conn.execute(
            """
            select connection_id, company_id, store_id, created_by, metadata_json
            from platform_connections where lower(platform) = 'ebay' order by created_at desc
            """
        ).fetchall()
        for row in rows:
            metadata = _load_json_field(row["metadata_json"])
            if any(expected and str(metadata.get(key) or "") == expected for key, expected in selectors.items()):
                return row
        return None

    def list_audit_logs(self, *, company_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from audit_logs
                where company_id = ?
                order by created_at desc
                limit ?
                """,
                (company_id, limit),
            ).fetchall()
        return [self._audit_row_to_dict(row) for row in rows]

    def task_timeline(self, *, company_id: str, task_id: str) -> dict[str, Any]:
        self.initialize()
        task = self.get_task(company_id=company_id, task_id=task_id)
        if not task:
            raise KeyError("task not found")
        queue_jobs = self.list_queue_jobs_for_task(company_id=company_id, task_id=task_id)
        steps = self.list_task_steps(company_id=company_id, task_id=task_id)
        reports = self.list_reports(company_id=company_id, task_id=task_id)
        confirmations = [item for item in self.list_confirmations(company_id=company_id) if item["task_id"] == task_id]
        audit_logs = self.list_audit_logs(company_id=company_id, limit=500)
        related_job_ids = {job["job_id"] for job in queue_jobs}
        related_audit = []
        for item in audit_logs:
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            if item.get("target_id") == task_id or item.get("target_id") in related_job_ids or details.get("task_id") == task_id:
                related_audit.append(item)
        events: list[dict[str, Any]] = []
        events.append(
            {
                "event_type": "task",
                "status": task["status"],
                "title": task["title"],
                "created_at": task["created_at"],
                "target_id": task_id,
            }
        )
        for job in queue_jobs:
            events.append(
                {
                    "event_type": "queue_job",
                    "status": job["status"],
                    "title": str(job.get("job", {}).get("kind") or "queue job"),
                    "created_at": job["created_at"],
                    "updated_at": job["updated_at"],
                    "target_id": job["job_id"],
                    "attempts": job["attempts"],
                }
            )
        for step in steps:
            events.append(
                {
                    "event_type": "step",
                    "status": step["status"],
                    "title": step["merchant_label"],
                    "created_at": step["updated_at"],
                    "target_id": step["step_id"],
                    "step_order": step["step_order"],
                }
            )
        for report in reports:
            events.append(
                {
                    "event_type": "report",
                    "status": report["status"],
                    "title": report["title"],
                    "created_at": report["created_at"],
                    "target_id": report["report_id"],
                }
            )
        for confirmation in confirmations:
            events.append(
                {
                    "event_type": "confirmation",
                    "status": confirmation["status"],
                    "title": confirmation["title"],
                    "created_at": confirmation["created_at"],
                    "target_id": confirmation["confirmation_id"],
                    "action_type": confirmation["action_type"],
                }
            )
        for audit in related_audit:
            events.append(
                {
                    "event_type": "audit",
                    "status": "recorded",
                    "title": audit["summary"],
                    "created_at": audit["created_at"],
                    "target_id": audit["audit_id"],
                    "action_type": audit["action_type"],
                }
            )
        events.sort(key=lambda item: str(item.get("created_at") or ""))
        return {
            "task": task,
            "queue_jobs": queue_jobs,
            "steps": steps,
            "reports": reports,
            "confirmations": confirmations,
            "audit_logs": related_audit,
            "events": events,
        }

    def record_platform_analytics_event(
        self,
        *,
        event_key: str,
        page_key: str,
        event_id_hash: str,
        visitor_hash: str = "",
        session_hash: str = "",
        company_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_event = str(event_key or "").strip().lower()
        normalized_page = str(page_key or "").strip().lower()
        normalized_event_hash = str(event_id_hash or "").strip().lower()
        if normalized_event not in ANALYTICS_EVENT_KEYS:
            raise ValueError("unsupported analytics event")
        if normalized_page not in ANALYTICS_PAGE_KEYS:
            raise ValueError("unsupported analytics page")
        if not re.fullmatch(r"[a-f0-9]{64}", normalized_event_hash):
            raise ValueError("analytics event id hash is invalid")
        occurred_at = now_iso()
        analytics_event_id = _id("analytics")
        event_json = {
            "contract_version": "2026-07-14-first-party-analytics-v1",
            "metadata": metadata if isinstance(metadata, dict) else {},
            "raw_ip_stored": False,
            "user_agent_stored": False,
            "raw_url_stored": False,
            "referrer_stored": False,
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into platform_analytics_events (
                  analytics_event_id, event_id_hash, company_id, user_id, event_key, page_key,
                  visitor_hash, session_hash, occurred_at, analytics_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analytics_event_id,
                    normalized_event_hash,
                    str(company_id or "") or None,
                    str(user_id or "") or None,
                    normalized_event,
                    normalized_page,
                    str(visitor_hash or "")[:64] or None,
                    str(session_hash or "")[:64] or None,
                    occurred_at,
                    json.dumps(event_json, ensure_ascii=False, default=json_default),
                ),
            )
            row = conn.execute(
                "select * from platform_analytics_events where event_id_hash = ?",
                (normalized_event_hash,),
            ).fetchone()
        return dict(row) if row else {}

    def record_model_usage(
        self,
        *,
        company_id: str,
        user_id: str | None,
        task_id: str | None,
        usage_owner: str,
        model_family: str,
        model_label: str,
        request_count: int,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        cost_minor: int,
        currency: str,
        cost_status: str,
        idempotency_key: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_company = str(company_id or "").strip()
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_company or not normalized_key:
            raise ValueError("model usage company and idempotency key are required")
        owner = str(usage_owner or "unknown").strip()[:80]
        idempotency_hash = hashlib.sha256(f"model-usage|{normalized_company}|{normalized_key}".encode("utf-8")).hexdigest()
        created_at = now_iso()
        usage_json = {
            "contract_version": "2026-07-14-model-usage-ledger-v1",
            "details": details if isinstance(details, dict) else {},
            "prompts_stored": False,
            "responses_stored": False,
            "provider_credentials_stored": False,
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into model_usage_ledger (
                  usage_id, company_id, user_id, task_id, usage_owner, model_family, model_label,
                  request_count, input_tokens, output_tokens, total_tokens, cost_minor, currency,
                  cost_status, idempotency_key_hash, created_at, usage_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("usage"), normalized_company, str(user_id or "") or None, str(task_id or "") or None,
                    owner, str(model_family or "provider_neutral")[:120], str(model_label or "")[:160],
                    max(0, int(request_count or 0)), max(0, int(input_tokens or 0)),
                    max(0, int(output_tokens or 0)), max(0, int(total_tokens or 0)),
                    max(0, int(cost_minor or 0)), str(currency or "CNY")[:8], str(cost_status or "unavailable")[:80],
                    idempotency_hash, created_at,
                    json.dumps(usage_json, ensure_ascii=False, default=json_default),
                ),
            )
            row = conn.execute(
                "select * from model_usage_ledger where idempotency_key_hash = ?",
                (idempotency_hash,),
            ).fetchone()
        return dict(row) if row else {}

    def record_provider_cost(
        self,
        *,
        company_id: str,
        user_id: str | None,
        task_id: str | None,
        reference_type: str,
        reference_id: str,
        cost_category: str,
        resource_type: str,
        unit_count: int,
        media_points: int,
        cost_minor: int,
        currency: str,
        cost_status: str,
        idempotency_key: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_company = str(company_id or "").strip()
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_company or not normalized_key:
            raise ValueError("provider cost company and idempotency key are required")
        idempotency_hash = hashlib.sha256(f"provider-cost|{normalized_company}|{normalized_key}".encode("utf-8")).hexdigest()
        created_at = now_iso()
        cost_json = {
            "contract_version": "2026-07-14-provider-cost-ledger-v1",
            "details": details if isinstance(details, dict) else {},
            "provider_neutral": True,
            "raw_provider_response_stored": False,
            "provider_credentials_stored": False,
            "secret_exposed": False,
        }
        with self._connect() as conn:
            conn.execute(
                """
                insert or ignore into provider_cost_ledger (
                  cost_id, company_id, user_id, task_id, reference_type, reference_id,
                  cost_category, resource_type, unit_count, media_points, cost_minor, currency,
                  cost_status, idempotency_key_hash, created_at, cost_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("cost"), normalized_company, str(user_id or "") or None, str(task_id or "") or None,
                    str(reference_type or "media_job")[:80], str(reference_id or "")[:160],
                    str(cost_category or "media_generation")[:80], str(resource_type or "mixed")[:40],
                    max(0, int(unit_count or 0)), max(0, int(media_points or 0)), max(0, int(cost_minor or 0)),
                    str(currency or "CNY")[:8], str(cost_status or "unavailable")[:80], idempotency_hash, created_at,
                    json.dumps(cost_json, ensure_ascii=False, default=json_default),
                ),
            )
            row = conn.execute(
                "select * from provider_cost_ledger where idempotency_key_hash = ?",
                (idempotency_hash,),
            ).fetchone()
        return dict(row) if row else {}

    def system_counts(self) -> dict[str, int]:
        self.initialize()
        tables = [
            "users",
            "companies",
            "platform_trial_activations",
            "team_members",
            "team_invitations",
            "stores",
            "platform_connections",
            "secret_refs",
            "oauth_authorization_requests",
            "platform_data_packets",
            "tasks",
            "queue_jobs",
            "task_steps",
            "reports",
            "confirmations",
            "merchant_memory",
            "merchant_ceo_commands",
            "ai_ceo_chat_turns",
            "execution_results",
            "audit_logs",
            "billing_subscriptions",
            "billing_webhook_events",
            "billing_orders",
            "media_credit_accounts",
            "media_credit_ledger",
            "platform_analytics_events",
            "model_usage_ledger",
            "provider_cost_ledger",
            "platform_reliability_alert_state",
            "platform_reliability_alert_events",
            "ebay_account_deletion_events",
            "schema_migrations",
        ]
        with self._connect() as conn:
            return {table: int(conn.execute(f"select count(*) as count from {table}").fetchone()["count"]) for table in tables}

    def reconcile_provider_reliability_alerts(
        self,
        *,
        alert_summary: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        """Persist only confirmed provider-neutral alert transitions."""

        self.initialize()
        items = alert_summary.get("items") if isinstance(alert_summary.get("items"), list) else []
        evaluated_at = now_iso()
        transitions: list[dict[str, Any]] = []
        with _PLATFORM_RELIABILITY_ALERT_LOCK:
            with self._connect() as conn:
                for observed in items:
                    if not isinstance(observed, dict):
                        continue
                    scope = str(observed.get("scope") or "").strip().lower()
                    if scope not in PROVIDER_TELEMETRY_SCOPES:
                        continue
                    row = conn.execute(
                        "select state_json from platform_reliability_alert_state where alert_scope = ?",
                        (scope,),
                    ).fetchone()
                    previous = _load_json_field(row["state_json"]) if row else None
                    reconciled = reconcile_reliability_alert_state(
                        previous_state=previous if isinstance(previous, dict) else None,
                        observed_alert=observed,
                        evaluated_at=evaluated_at,
                    )
                    state = _redact_secret_like(reconciled["state"])
                    conn.execute(
                        """
                        insert or replace into platform_reliability_alert_state (
                          alert_scope, lifecycle_status, severity, observed_status,
                          consecutive_breach_count, consecutive_healthy_count, fingerprint,
                          opened_at, recovered_at, acknowledged_at, acknowledged_by,
                          acknowledgement_action, last_evaluated_at, updated_at, state_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            scope,
                            state["lifecycle_status"],
                            state["severity"],
                            state["observed_status"],
                            int(state["consecutive_breach_count"]),
                            int(state["consecutive_healthy_count"]),
                            state["fingerprint"],
                            state.get("opened_at") or None,
                            state.get("recovered_at") or None,
                            state.get("acknowledged_at") or None,
                            state.get("acknowledged_by") or None,
                            state.get("acknowledgement_action") or None,
                            state["last_evaluated_at"],
                            state["updated_at"],
                            json.dumps(state, ensure_ascii=False, default=json_default),
                        ),
                    )
                    transition = reconciled.get("transition")
                    if isinstance(transition, dict) and self._insert_platform_reliability_alert_event(
                        conn,
                        transition=transition,
                        actor_user_id=actor_user_id,
                    ):
                        transitions.append(_redact_secret_like(transition))
        lifecycle = self.provider_reliability_alert_lifecycle()
        return {
            **lifecycle,
            "transition_count": len(transitions),
            "events": transitions,
            "mutated_by_get": False,
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def provider_reliability_alert_lifecycle(self, *, event_limit: int = 20) -> dict[str, Any]:
        self.initialize()
        safe_limit = min(max(int(event_limit or 20), 1), 100)
        with self._connect() as conn:
            state_rows = conn.execute(
                "select state_json from platform_reliability_alert_state order by alert_scope"
            ).fetchall()
            event_rows = conn.execute(
                """
                select event_id, alert_scope, transition_key, severity, fingerprint, action_key,
                       actor_user_id, created_at, event_json
                from platform_reliability_alert_events
                order by created_at desc, event_id desc
                limit ?
                """,
                (safe_limit,),
            ).fetchall()
        states = [
            _redact_secret_like(_load_json_field(row["state_json"]))
            for row in state_rows
            if isinstance(_load_json_field(row["state_json"]), dict)
        ]
        events = [
            {
                "event_id": str(row["event_id"]),
                "scope": str(row["alert_scope"]),
                "transition_key": str(row["transition_key"]),
                "severity": str(row["severity"]),
                "fingerprint": str(row["fingerprint"]),
                "action_key": str(row["action_key"]),
                "actor_user_id": str(row["actor_user_id"] or ""),
                "created_at": str(row["created_at"]),
                "provider_neutral": True,
                "secret_exposed": False,
            }
            for row in event_rows
        ]
        return {
            "contract_version": "2026-07-14-provider-reliability-alert-lifecycle-v1",
            "status": "instrumented" if states else "ready_no_evaluations",
            "open_count": sum(1 for state in states if state.get("lifecycle_status") == "open"),
            "pending_count": sum(1 for state in states if state.get("lifecycle_status") == "pending"),
            "recovering_count": sum(1 for state in states if state.get("lifecycle_status") == "recovering"),
            "states": states,
            "events": events,
            "event_count": len(events),
            "merchant_navigation_visible": False,
            "provider_neutral": True,
            "prompts_stored": False,
            "responses_stored": False,
            "queries_stored": False,
            "raw_errors_stored": False,
            "secret_exposed": False,
        }

    def acknowledge_provider_reliability_alert(
        self,
        *,
        scope: str,
        actor_user_id: str,
        action_key: str,
    ) -> dict[str, Any]:
        self.initialize()
        normalized_scope = str(scope or "").strip().lower()
        normalized_action = str(action_key or "").strip().lower()
        if normalized_scope not in PROVIDER_TELEMETRY_SCOPES:
            raise ValueError("unsupported reliability alert scope")
        if normalized_action not in {"investigating", "mitigation_in_progress", "monitoring"}:
            raise ValueError("unsupported reliability acknowledgement action")
        with _PLATFORM_RELIABILITY_ALERT_LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "select state_json from platform_reliability_alert_state where alert_scope = ?",
                    (normalized_scope,),
                ).fetchone()
                state = _load_json_field(row["state_json"]) if row else {}
                if not isinstance(state, dict) or state.get("lifecycle_status") not in {"open", "recovering"}:
                    return {
                        "ok": False,
                        "status": "no_open_alert",
                        "scope": normalized_scope,
                        "secret_exposed": False,
                    }
                acknowledged_at = now_iso()
                transition = {
                    "transition_key": "acknowledged",
                    "scope": normalized_scope,
                    "severity": str(state.get("severity") or "none"),
                    "fingerprint": str(state.get("fingerprint") or ""),
                    "action_key": normalized_action,
                    "created_at": acknowledged_at,
                    "provider_neutral": True,
                    "secret_exposed": False,
                }
                inserted = self._insert_platform_reliability_alert_event(
                    conn,
                    transition=transition,
                    actor_user_id=actor_user_id,
                )
                if inserted:
                    state["acknowledged_at"] = acknowledged_at
                    state["acknowledged_by"] = str(actor_user_id or "")[:160]
                    state["acknowledgement_action"] = normalized_action
                    state["updated_at"] = acknowledged_at
                    state = _redact_secret_like(state)
                    conn.execute(
                        """
                        update platform_reliability_alert_state
                        set acknowledged_at = ?, acknowledged_by = ?, acknowledgement_action = ?,
                            updated_at = ?, state_json = ?
                        where alert_scope = ?
                        """,
                        (
                            acknowledged_at,
                            state["acknowledged_by"],
                            normalized_action,
                            acknowledged_at,
                            json.dumps(state, ensure_ascii=False, default=json_default),
                            normalized_scope,
                        ),
                    )
        return {
            "ok": True,
            "status": "acknowledged" if inserted else "already_acknowledged",
            "duplicate": not inserted,
            "scope": normalized_scope,
            "action_key": normalized_action,
            "provider_neutral": True,
            "secret_exposed": False,
        }

    @staticmethod
    def _insert_platform_reliability_alert_event(
        conn: sqlite3.Connection,
        *,
        transition: dict[str, Any],
        actor_user_id: str,
    ) -> bool:
        safe_transition = _redact_secret_like(
            {
                "scope": str(transition.get("scope") or "")[:40],
                "transition_key": str(transition.get("transition_key") or "")[:40],
                "severity": str(transition.get("severity") or "none")[:20],
                "fingerprint": str(transition.get("fingerprint") or "")[:128],
                "action_key": str(transition.get("action_key") or "none")[:80],
                "created_at": str(transition.get("created_at") or now_iso())[:80],
                "provider_neutral": True,
                "secret_exposed": False,
            }
        )
        cursor = conn.execute(
            """
            insert or ignore into platform_reliability_alert_events (
              event_id, alert_scope, transition_key, severity, fingerprint,
              action_key, actor_user_id, created_at, event_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _id("reliability_event"),
                safe_transition["scope"],
                safe_transition["transition_key"],
                safe_transition["severity"],
                safe_transition["fingerprint"],
                safe_transition["action_key"],
                str(actor_user_id or "")[:160] or None,
                safe_transition["created_at"],
                json.dumps(safe_transition, ensure_ascii=False, default=json_default),
            ),
        )
        return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def merchant_workflow_validation_snapshot(self) -> dict[str, Any]:
        """Return privacy-safe proof of independent merchants completing the core path."""

        self.initialize()
        with self._connect() as conn:
            account_row = conn.execute(
                """
                select count(distinct default_company_id) as merchant_company_count
                from users
                where account_classification = ?
                """,
                (ACCOUNT_CLASSIFICATION_MERCHANT,),
            ).fetchone()
            evidence_row = conn.execute(
                """
                select
                  count(*) as validated_path_count,
                  count(distinct t.company_id) as validated_merchant_count
                from tasks t
                where t.task_type = ?
                  and t.status = ?
                  and exists (
                    select 1
                    from users u
                    where u.default_company_id = t.company_id
                      and u.account_classification = ?
                  )
                  and exists (
                    select 1
                    from reports r
                    where r.task_id = t.task_id
                  )
                  and exists (
                    select 1
                    from confirmations c
                    where c.company_id = t.company_id
                      and c.task_id = t.task_id
                      and c.status in (?, ?, ?)
                      and c.decided_at is not null
                  )
                """,
                (
                    "product_workflow",
                    "completed",
                    ACCOUNT_CLASSIFICATION_MERCHANT,
                    "approved",
                    "rejected",
                    "needs_revision",
                ),
            ).fetchone()

        eligible_merchants = int((account_row or {})["merchant_company_count"] or 0)
        validated_merchants = int((evidence_row or {})["validated_merchant_count"] or 0)
        validated_paths = int((evidence_row or {})["validated_path_count"] or 0)
        passed = (
            validated_merchants >= REAL_MERCHANT_VALIDATION_REQUIRED_COMPANIES
            and validated_paths >= REAL_MERCHANT_VALIDATION_REQUIRED_PATHS
        )
        remaining_merchants = max(REAL_MERCHANT_VALIDATION_REQUIRED_COMPANIES - validated_merchants, 0)
        remaining_paths = max(REAL_MERCHANT_VALIDATION_REQUIRED_PATHS - validated_paths, 0)
        return {
            "contract_version": "2026-07-14-real-merchant-workflow-validation-v1",
            "status": "threshold_met" if passed else "pending_real_merchant_evidence",
            "passed": passed,
            "required_merchant_count": REAL_MERCHANT_VALIDATION_REQUIRED_COMPANIES,
            "required_path_count": REAL_MERCHANT_VALIDATION_REQUIRED_PATHS,
            "eligible_merchant_count": eligible_merchants,
            "validated_merchant_count": validated_merchants,
            "validated_path_count": validated_paths,
            "remaining_merchant_count": remaining_merchants,
            "remaining_path_count": remaining_paths,
            "synthetic_accounts_excluded": True,
            "decision_required": True,
            "customer_visible": False,
            "read_only": True,
            "triggers_real_platform_write": False,
            "triggers_charge": False,
            "next_action": (
                "Evidence threshold met; keep public charging blocked until the separate final smoke and owner approvals pass."
                if passed
                else (
                    f"Complete the core workflow with {remaining_merchants} more independent merchant(s) "
                    f"and {remaining_paths} more decided path(s)."
                )
            ),
        }

    def platform_operations_overview(self, *, period_days: int = 30) -> dict[str, Any]:
        """Return platform-wide aggregates for the internal operator console only."""

        self.initialize()
        safe_period_days = min(max(int(30 if period_days is None else period_days), 1), 366)
        period_ended_at = datetime.now(timezone.utc)
        period_start_date = period_ended_at.date() - timedelta(days=safe_period_days - 1)
        period_started_at = datetime.combine(period_start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        with self._connect() as conn:
            accounts_row = conn.execute(
                """
                select
                  (select count(*) from users where account_classification = 'merchant') as registered_users,
                  (select count(distinct default_company_id) from users where account_classification = 'merchant') as merchant_companies,
                  (select count(*) from stores s where exists (
                    select 1 from users u
                    where u.default_company_id = s.company_id and u.account_classification = 'merchant'
                  )) as stores_created,
                  (select count(distinct pc.store_id) from platform_connections pc where
                    pc.status in ('read_only_authorized', 'publish_authorized') and exists (
                      select 1 from users u
                      where u.default_company_id = pc.company_id and u.account_classification = 'merchant'
                    )
                  ) as connected_stores,
                  (select count(*) from team_members tm where exists (
                    select 1 from users u
                    where u.default_company_id = tm.company_id and u.account_classification = 'merchant'
                  )) as team_members,
                  (select count(*) from users where account_classification = 'synthetic_test') as synthetic_test_accounts
                """
            ).fetchone()
            all_plan_rows = conn.execute(
                """
                select company_id, provider, plan_key, status, entitlement_active, subscription_json,
                       case when exists (
                         select 1 from users u
                         where u.default_company_id = s.company_id and u.account_classification = 'merchant'
                       ) then 1 else 0 end as merchant_account
                from billing_subscriptions s
                """
            ).fetchall()
            all_order_rows = conn.execute(
                """
                select company_id, provider, status, amount_minor, order_json,
                       case when exists (
                         select 1 from users u
                         where u.default_company_id = o.company_id and u.account_classification = 'merchant'
                       ) then 1 else 0 end as merchant_account
                from billing_orders o
                where coalesce(paid_at, created_at) >= ?
                """,
                (period_started_at,),
            ).fetchall()
            active_subscription_order_rows = conn.execute(
                """
                select o.company_id, o.provider, o.plan_key, o.status, o.amount_minor,
                       o.duration_days, o.paid_at, o.created_at, o.order_json,
                       case when exists (
                         select 1 from users u
                         where u.default_company_id = o.company_id and u.account_classification = 'merchant'
                       ) then 1 else 0 end as merchant_account
                from billing_orders o
                where o.status = 'paid' and exists (
                  select 1 from billing_subscriptions s where s.company_id = o.company_id
                )
                order by coalesce(o.paid_at, o.created_at) desc
                limit 10001
                """
            ).fetchall()
            task_rows = conn.execute(
                """
                select status, count(*) as count
                from tasks t
                where t.created_at >= ? and exists (
                  select 1 from users u
                  where u.default_company_id = t.company_id and u.account_classification = 'merchant'
                )
                group by status
                order by status
                """,
                (period_started_at,),
            ).fetchall()
            active_merchants_row = conn.execute(
                """
                select count(distinct t.company_id) as count
                from tasks t
                where t.created_at >= ? and exists (
                  select 1 from users u
                  where u.default_company_id = t.company_id and u.account_classification = 'merchant'
                )
                """,
                (period_started_at,),
            ).fetchone()
            media_row = conn.execute(
                """
                select
                  count(*) as account_count,
                  coalesce(sum(balance_points), 0) as balance_points,
                  coalesce(sum(reserved_points), 0) as reserved_points,
                  coalesce(sum(lifetime_granted_points), 0) as lifetime_granted_points,
                  coalesce(sum(lifetime_spent_points), 0) as lifetime_spent_points
                from media_credit_accounts m
                where exists (
                  select 1 from users u
                  where u.default_company_id = m.company_id and u.account_classification = 'merchant'
                )
                """
            ).fetchone()
            traffic_row = conn.execute(
                """
                select
                  count(*) as event_count,
                  count(distinct case when visitor_hash is not null and visitor_hash <> '' then visitor_hash end) as visitors,
                  count(distinct case when session_hash is not null and session_hash <> '' then session_hash end) as sessions,
                  coalesce(sum(case when event_key = 'page_view' then 1 else 0 end), 0) as page_views,
                  coalesce(sum(case when event_key = 'pricing_view' then 1 else 0 end), 0) as pricing_views,
                  coalesce(sum(case when event_key = 'signup_started' then 1 else 0 end), 0) as signup_started,
                  coalesce(sum(case when event_key = 'signup_completed' then 1 else 0 end), 0) as signup_completed,
                  count(distinct case when event_key = 'signup_completed' and visitor_hash is not null and visitor_hash <> '' then visitor_hash end) as signup_completed_visitors
                from platform_analytics_events
                where occurred_at >= ?
                """,
                (period_started_at,),
            ).fetchone()
            traffic_daily_rows = conn.execute(
                """
                select
                  substr(cast(occurred_at as text), 1, 10) as day_key,
                  count(distinct case when visitor_hash is not null and visitor_hash <> '' then visitor_hash end) as visitors,
                  count(distinct case when session_hash is not null and session_hash <> '' then session_hash end) as sessions,
                  coalesce(sum(case when event_key = 'page_view' then 1 else 0 end), 0) as page_views,
                  coalesce(sum(case when event_key = 'pricing_view' then 1 else 0 end), 0) as pricing_views,
                  coalesce(sum(case when event_key = 'signup_started' then 1 else 0 end), 0) as signup_started,
                  coalesce(sum(case when event_key = 'signup_completed' then 1 else 0 end), 0) as signup_completed
                from platform_analytics_events
                where occurred_at >= ? and event_key <> 'performance_sample'
                group by substr(cast(occurred_at as text), 1, 10)
                order by day_key
                """,
                (period_started_at,),
            ).fetchall()
            traffic_page_rows = conn.execute(
                """
                select
                  page_key,
                  count(*) as event_count,
                  count(distinct case when visitor_hash is not null and visitor_hash <> '' then visitor_hash end) as visitors,
                  count(distinct case when session_hash is not null and session_hash <> '' then session_hash end) as sessions,
                  coalesce(sum(case when event_key = 'page_view' then 1 else 0 end), 0) as page_views,
                  coalesce(sum(case when event_key = 'pricing_view' then 1 else 0 end), 0) as pricing_views,
                  coalesce(sum(case when event_key = 'signup_started' then 1 else 0 end), 0) as signup_started,
                  coalesce(sum(case when event_key = 'signup_completed' then 1 else 0 end), 0) as signup_completed
                from platform_analytics_events
                where occurred_at >= ? and event_key <> 'performance_sample'
                group by page_key
                order by event_count desc, page_key
                """,
                (period_started_at,),
            ).fetchall()
            performance_rows = conn.execute(
                """
                select analytics_json
                from platform_analytics_events
                where occurred_at >= ? and event_key = 'performance_sample'
                order by occurred_at desc
                limit 5000
                """,
                (period_started_at,),
            ).fetchall()
            model_usage_rows = conn.execute(
                """
                select usage_owner, cost_status,
                       coalesce(sum(request_count), 0) as request_count,
                       coalesce(sum(input_tokens), 0) as input_tokens,
                       coalesce(sum(output_tokens), 0) as output_tokens,
                       coalesce(sum(total_tokens), 0) as total_tokens,
                       coalesce(sum(cost_minor), 0) as cost_minor
                from model_usage_ledger m
                where created_at >= ? and (
                  company_id is null or exists (
                    select 1 from users u
                    where u.default_company_id = m.company_id and u.account_classification = 'merchant'
                  )
                )
                group by usage_owner, cost_status
                order by usage_owner, cost_status
                """,
                (period_started_at,),
            ).fetchall()
            model_reliability_rows = conn.execute(
                """
                select usage_json
                from model_usage_ledger m
                where created_at >= ? and (
                  company_id is null or exists (
                    select 1 from users u
                    where u.default_company_id = m.company_id and u.account_classification = 'merchant'
                  )
                )
                order by created_at desc
                limit 5000
                """,
                (period_started_at,),
            ).fetchall()
            provider_cost_rows = conn.execute(
                """
                select cost_category, cost_status,
                       count(*) as record_count,
                       coalesce(sum(unit_count), 0) as unit_count,
                       coalesce(sum(media_points), 0) as media_points,
                       coalesce(sum(cost_minor), 0) as cost_minor
                from provider_cost_ledger c
                where created_at >= ? and (
                  company_id is null or exists (
                    select 1 from users u
                    where u.default_company_id = c.company_id and u.account_classification = 'merchant'
                  )
                )
                group by cost_category, cost_status
                order by cost_category, cost_status
                """,
                (period_started_at,),
            ).fetchall()
            provider_reliability_rows = conn.execute(
                """
                select cost_json
                from provider_cost_ledger c
                where created_at >= ? and (
                  company_id is null or exists (
                    select 1 from users u
                    where u.default_company_id = c.company_id and u.account_classification = 'merchant'
                  )
                )
                order by created_at desc
                limit 5000
                """,
                (period_started_at,),
            ).fetchall()
            metering_migration_row = conn.execute(
                "select applied_at from schema_migrations where migration_id = ?",
                ("20260714_platform_operations_metering",),
            ).fetchone()
            metering_started_at_value = metering_migration_row["applied_at"] if metering_migration_row else None
            metering_started_at = (
                metering_started_at_value.isoformat()
                if hasattr(metering_started_at_value, "isoformat")
                else str(metering_started_at_value or "")
            )
            unmetered_model_row = conn.execute(
                """
                select count(*) as count
                from tasks t
                left join model_usage_ledger m on m.task_id = t.task_id
                where t.task_type = 'merchant_ceo_chat' and t.created_at >= ? and m.usage_id is null
                  and exists (
                    select 1 from users u
                    where u.default_company_id = t.company_id and u.account_classification = 'merchant'
                  )
                """,
                (period_started_at,),
            ).fetchone()
            current_unmetered_model_row = (
                conn.execute(
                    """
                    select count(*) as count
                    from tasks t
                    left join model_usage_ledger m on m.task_id = t.task_id
                    where t.task_type = 'merchant_ceo_chat'
                      and t.created_at >= ? and t.created_at >= ? and m.usage_id is null
                      and exists (
                        select 1 from users u
                        where u.default_company_id = t.company_id and u.account_classification = 'merchant'
                      )
                    """,
                    (period_started_at, metering_started_at_value),
                ).fetchone()
                if metering_started_at_value
                else None
            )
            unmetered_media_row = conn.execute(
                """
                select count(*) as count
                from media_credit_ledger l
                left join provider_cost_ledger c
                  on c.company_id = l.company_id and c.reference_type = 'media_job' and c.reference_id = l.reference_id
                where l.operation_type = 'settle' and l.created_at >= ? and c.cost_id is null
                  and exists (
                    select 1 from users u
                    where u.default_company_id = l.company_id and u.account_classification = 'merchant'
                  )
                """,
                (period_started_at,),
            ).fetchone()

        def non_commercial_provider(provider: Any) -> bool:
            normalized = str(provider or "").strip().lower()
            return normalized in _NON_COMMERCIAL_BILLING_PROVIDERS or normalized.endswith("_mock")

        def acceptance_order(row: Any) -> bool:
            payload = _load_json_field(row["order_json"])
            return isinstance(payload, dict) and payload.get("live_acceptance_test") is True

        plan_rows = [row for row in all_plan_rows if bool(row["merchant_account"])]
        order_rows = [row for row in all_order_rows if bool(row["merchant_account"])]
        commercial_order_rows = [
            row for row in order_rows if not non_commercial_provider(row["provider"]) and not acceptance_order(row)
        ]
        period_paid_company_ids = {
            str(row["company_id"])
            for row in commercial_order_rows
            if str(row["status"] or "").lower() == "paid"
        }
        subscription_order_scan_capped = len(active_subscription_order_rows) > 10000
        active_subscription_paid_rows: dict[str, Any] = {}
        for row in active_subscription_order_rows[:10000]:
            company_id = str(row["company_id"] or "")
            if (
                not company_id
                or not bool(row["merchant_account"])
                or non_commercial_provider(row["provider"])
                or acceptance_order(row)
                or company_id in active_subscription_paid_rows
            ):
                continue
            active_subscription_paid_rows[company_id] = row
        commercial_paid_company_ids = set(active_subscription_paid_rows)

        def non_commercial_subscription(row: Any) -> bool:
            provider = str(row["provider"] or "").strip().lower()
            if not bool(row["merchant_account"]) or non_commercial_provider(provider):
                return True
            return provider == "wechat_pay_native" and str(row["company_id"]) not in commercial_paid_company_ids

        subscription_counts: dict[tuple[str, str], int] = {}
        test_subscriptions_excluded = sum(1 for row in all_plan_rows if non_commercial_subscription(row))
        for row in plan_rows:
            if non_commercial_subscription(row):
                continue
            key = (str(row["plan_key"] or "unknown"), str(row["status"] or "unknown"))
            subscription_counts[key] = subscription_counts.get(key, 0) + 1
        subscriptions = [
            {"plan_key": key[0], "status": key[1], "count": count}
            for key, count in sorted(subscription_counts.items())
        ]
        payment_counts: dict[str, dict[str, int]] = {}
        for row in commercial_order_rows:
            status = str(row["status"] or "unknown")
            aggregate = payment_counts.setdefault(status, {"count": 0, "amount_minor": 0})
            aggregate["count"] += 1
            aggregate["amount_minor"] += int(row["amount_minor"] or 0)
        domestic_payments = [
            {
                "status": status,
                "count": values["count"],
                "amount_minor": values["amount_minor"],
                "currency": "CNY",
            }
            for status, values in sorted(payment_counts.items())
        ]
        visitors = int(traffic_row["visitors"] or 0)
        signup_completed = int(traffic_row["signup_completed"] or 0)
        signup_completed_visitors = int(traffic_row["signup_completed_visitors"] or 0)
        traffic_daily_by_day = {
            str(row["day_key"] or ""): {
                "visitors": int(row["visitors"] or 0),
                "sessions": int(row["sessions"] or 0),
                "page_views": int(row["page_views"] or 0),
                "pricing_views": int(row["pricing_views"] or 0),
                "signup_started": int(row["signup_started"] or 0),
                "signup_completed": int(row["signup_completed"] or 0),
            }
            for row in traffic_daily_rows
            if str(row["day_key"] or "")
        }
        traffic_daily_trend = []
        for offset in range(safe_period_days):
            day_key = (period_start_date + timedelta(days=offset)).isoformat()
            traffic_daily_trend.append(
                {
                    "day": day_key,
                    **traffic_daily_by_day.get(
                        day_key,
                        {
                            "visitors": 0,
                            "sessions": 0,
                            "page_views": 0,
                            "pricing_views": 0,
                            "signup_started": 0,
                            "signup_completed": 0,
                        },
                    ),
                }
            )
        traffic_page_breakdown = [
            {
                "page_key": str(row["page_key"] or "unknown"),
                "event_count": int(row["event_count"] or 0),
                "visitors": int(row["visitors"] or 0),
                "sessions": int(row["sessions"] or 0),
                "page_views": int(row["page_views"] or 0),
                "pricing_views": int(row["pricing_views"] or 0),
                "signup_started": int(row["signup_started"] or 0),
                "signup_completed": int(row["signup_completed"] or 0),
            }
            for row in traffic_page_rows
        ]

        performance_samples: list[dict[str, Any]] = []
        for row in performance_rows:
            packet = _load_json_field(row["analytics_json"])
            metadata = packet.get("metadata") if isinstance(packet, dict) and isinstance(packet.get("metadata"), dict) else {}
            scope = str(metadata.get("performance_scope") or "")
            if scope not in {"page_load", "settings_module"}:
                continue
            performance_samples.append({"scope": scope, **metadata})

        def performance_p75(scope: str, key: str) -> int | None:
            values = sorted(
                int(sample[key])
                for sample in performance_samples
                if sample.get("scope") == scope and isinstance(sample.get(key), int)
            )
            if not values:
                return None
            return values[max(0, ((len(values) * 3 + 3) // 4) - 1)]

        page_performance_samples = [sample for sample in performance_samples if sample.get("scope") == "page_load"]
        settings_performance_samples = [sample for sample in performance_samples if sample.get("scope") == "settings_module"]
        performance_analytics = {
            "status": "instrumented" if performance_samples else "ready_no_samples",
            "sample_count": len(performance_samples),
            "page_load": {
                "sample_count": len(page_performance_samples),
                "p75": {
                    key: performance_p75("page_load", key)
                    for key in (
                        "ttfb_ms",
                        "fcp_ms",
                        "lcp_ms",
                        "cls_milli",
                        "dom_ready_ms",
                        "load_complete_ms",
                        "app_shell_ready_ms",
                    )
                },
            },
            "settings_module": {
                "sample_count": len(settings_performance_samples),
                "success_count": sum(1 for sample in settings_performance_samples if sample.get("outcome") == "success"),
                "error_count": sum(1 for sample in settings_performance_samples if sample.get("outcome") == "error"),
                "p75": {"duration_ms": performance_p75("settings_module", "duration_ms")},
            },
            "raw_url_stored": False,
            "referrer_stored": False,
            "user_agent_stored": False,
            "prompt_or_response_stored": False,
        }

        def bounded_duration(value: Any) -> int | None:
            try:
                duration = int(value)
            except (TypeError, ValueError):
                return None
            return min(max(0, duration), 120_000)

        def nonnegative_int(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        reliability_buckets: dict[str, dict[str, Any]] = {
            scope: {
                "request_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "timeout_count": 0,
                "partial_count": 0,
                "blocked_count": 0,
                "durations": [],
                "error_classes": {},
            }
            for scope in ("model", "public_search", "media_generation", "payment")
        }

        for row in model_reliability_rows:
            packet = _load_json_field(row["usage_json"])
            details = packet.get("details") if isinstance(packet, dict) and isinstance(packet.get("details"), dict) else {}
            reliability = details.get("reliability") if isinstance(details.get("reliability"), dict) else {}
            if not reliability:
                continue
            bucket = reliability_buckets["model"]
            request_count = nonnegative_int(reliability.get("request_count"))
            success_count = min(request_count, nonnegative_int(reliability.get("success_count")))
            timeout_count = min(request_count, nonnegative_int(reliability.get("timeout_count")))
            bucket["request_count"] += request_count
            bucket["success_count"] += success_count
            bucket["failure_count"] += max(0, request_count - success_count)
            bucket["timeout_count"] += timeout_count
            duration_samples = reliability.get("duration_samples_ms") if isinstance(reliability.get("duration_samples_ms"), list) else []
            if not duration_samples:
                duration_samples = [reliability.get("p75_duration_ms")]
            for value in duration_samples[:50]:
                duration = bounded_duration(value)
                if duration is not None:
                    bucket["durations"].append(duration)
            error_classes = reliability.get("error_classes") if isinstance(reliability.get("error_classes"), dict) else {}
            for error_class, count in error_classes.items():
                normalized_error = str(error_class or "")
                if normalized_error not in {"timeout", "http_error", "provider_error", "invalid_response", "no_output", "not_configured", "blocked_input"}:
                    continue
                bucket["error_classes"][normalized_error] = bucket["error_classes"].get(normalized_error, 0) + nonnegative_int(count)

        for row in provider_reliability_rows:
            packet = _load_json_field(row["cost_json"])
            details = packet.get("details") if isinstance(packet, dict) and isinstance(packet.get("details"), dict) else {}
            telemetry = details.get("telemetry") if isinstance(details.get("telemetry"), dict) else {}
            scope = str(telemetry.get("scope") or "")
            if scope not in {"public_search", "media_generation", "payment"}:
                continue
            outcome = str(telemetry.get("outcome") or "error")
            if outcome not in {"success", "partial", "error", "timeout", "blocked"}:
                outcome = "error"
            bucket = reliability_buckets[scope]
            bucket["request_count"] += 1
            bucket["success_count"] += 1 if outcome == "success" else 0
            bucket["failure_count"] += 0 if outcome == "success" else 1
            bucket["timeout_count"] += 1 if outcome == "timeout" else 0
            bucket["partial_count"] += 1 if outcome == "partial" else 0
            bucket["blocked_count"] += 1 if outcome == "blocked" else 0
            duration = bounded_duration(telemetry.get("duration_ms"))
            if duration is not None:
                bucket["durations"].append(duration)
            error_class = str(telemetry.get("error_class") or "")
            if error_class in {"timeout", "http_error", "provider_error", "invalid_response", "no_output", "not_configured", "blocked_input"}:
                bucket["error_classes"][error_class] = bucket["error_classes"].get(error_class, 0) + 1

        def reliability_summary(scope: str) -> dict[str, Any]:
            bucket = reliability_buckets[scope]
            durations = sorted(bucket.pop("durations"))
            return {
                "status": "instrumented" if bucket["request_count"] else "ready_no_samples",
                "sample_count": len(durations),
                **bucket,
                "p75_duration_ms": durations[max(0, ((len(durations) * 3 + 3) // 4) - 1)] if durations else None,
                "max_duration_ms": max(durations) if durations else None,
            }

        provider_reliability_analytics = {
            "model": reliability_summary("model"),
            "public_search": reliability_summary("public_search"),
            "media_generation": reliability_summary("media_generation"),
            "payment": reliability_summary("payment"),
            "provider_neutral": True,
            "prompts_stored": False,
            "responses_stored": False,
            "queries_stored": False,
            "raw_errors_stored": False,
            "raw_provider_response_stored": False,
        }
        provider_reliability_analytics["alerts"] = build_reliability_alert_summary(provider_reliability_analytics)
        provider_reliability_analytics["lifecycle"] = self.provider_reliability_alert_lifecycle()
        model_usage = [
            {
                "usage_owner": str(row["usage_owner"] or "unknown"),
                "cost_status": str(row["cost_status"] or "unavailable"),
                "request_count": int(row["request_count"] or 0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cost_minor": int(row["cost_minor"] or 0),
                "currency": "CNY",
            }
            for row in model_usage_rows
        ]
        provider_costs = [
            {
                "cost_category": str(row["cost_category"] or "unknown"),
                "cost_status": str(row["cost_status"] or "unavailable"),
                "record_count": int(row["record_count"] or 0),
                "unit_count": int(row["unit_count"] or 0),
                "media_points": int(row["media_points"] or 0),
                "cost_minor": int(row["cost_minor"] or 0),
                "currency": "CNY",
            }
            for row in provider_cost_rows
        ]
        platform_model_cost_minor = sum(
            row["cost_minor"] for row in model_usage if row["usage_owner"] == "jiejing_platform_trial"
        )
        provider_cost_minor = sum(row["cost_minor"] for row in provider_costs)
        media_cost_minor = sum(row["cost_minor"] for row in provider_costs if row["cost_category"] == "media_generation")
        public_search_cost_minor = sum(row["cost_minor"] for row in provider_costs if row["cost_category"] == "public_search")
        unknown_model_cost_records = sum(
            row["request_count"]
            for row in model_usage
            if row["usage_owner"] in {"jiejing_platform_trial", "unknown"} and row["cost_status"] == "unavailable"
        ) + int(unmetered_model_row["count"] or 0)
        unknown_provider_cost_records = sum(
            row["record_count"] for row in provider_costs if row["cost_status"] == "unavailable"
        ) + int(unmetered_media_row["count"] or 0)
        unmetered_model_tasks = int(unmetered_model_row["count"] or 0)
        current_unmetered_model_tasks = (
            int(current_unmetered_model_row["count"] or 0) if current_unmetered_model_row else unmetered_model_tasks
        )
        legacy_unmetered_model_tasks = max(unmetered_model_tasks - current_unmetered_model_tasks, 0)
        current_metering_health = (
            "ready"
            if metering_started_at and current_unmetered_model_tasks == 0
            else "degraded"
            if metering_started_at
            else "unavailable"
        )
        cost_coverage_complete = unknown_model_cost_records == 0 and unknown_provider_cost_records == 0
        paid_order_rows = [row for row in commercial_order_rows if str(row["status"] or "").lower() == "paid"]
        paid_revenue_minor = sum(int(row["amount_minor"] or 0) for row in paid_order_rows)
        active_subscription_company_ids = {
            str(row["company_id"])
            for row in plan_rows
            if not non_commercial_subscription(row) and bool(row["entitlement_active"])
        }
        normalized_mrr_minor = 0
        mrr_missing_order_count = 0
        for company_id in active_subscription_company_ids:
            order = active_subscription_paid_rows.get(company_id)
            if not order:
                mrr_missing_order_count += 1
                continue
            duration_days = max(0, int(order["duration_days"] or 0))
            if duration_days <= 0:
                mrr_missing_order_count += 1
                continue
            normalized_mrr_minor += round(int(order["amount_minor"] or 0) * 30 / duration_days)
        contribution_margin_minor = (
            paid_revenue_minor - platform_model_cost_minor - provider_cost_minor
            if cost_coverage_complete
            else None
        )
        return {
            "contract_version": "2026-07-15-platform-operations-overview-v9",
            "audience": "platform_internal_admin",
            "period": {"days": safe_period_days, "started_at": period_started_at},
            "accounts": {
                "registered_users": int(accounts_row["registered_users"] or 0),
                "merchant_companies": int(accounts_row["merchant_companies"] or 0),
                "stores_created": int(accounts_row["stores_created"] or 0),
                "connected_stores": int(accounts_row["connected_stores"] or 0),
                "team_members": int(accounts_row["team_members"] or 0),
                "active_merchant_companies": int(active_merchants_row["count"] or 0),
            },
            "subscriptions": subscriptions,
            "domestic_payments": domestic_payments,
            "tasks": {str(row["status"] or "unknown"): int(row["count"] or 0) for row in task_rows},
            "media_points": {
                "account_count": int(media_row["account_count"] or 0),
                "balance_points": int(media_row["balance_points"] or 0),
                "reserved_points": int(media_row["reserved_points"] or 0),
                "lifetime_granted_points": int(media_row["lifetime_granted_points"] or 0),
                "lifetime_spent_points": int(media_row["lifetime_spent_points"] or 0),
            },
            "traffic_analytics": {
                "status": "instrumented" if int(traffic_row["event_count"] or 0) > 0 else "ready_no_events",
                "event_count": int(traffic_row["event_count"] or 0),
                "visitors": visitors,
                "sessions": int(traffic_row["sessions"] or 0),
                "page_views": int(traffic_row["page_views"] or 0),
                "pricing_views": int(traffic_row["pricing_views"] or 0),
                "signup_started": int(traffic_row["signup_started"] or 0),
                "signup_completed": signup_completed,
                "signup_completed_visitors": signup_completed_visitors,
                "visitor_to_signup_percent": round((signup_completed_visitors / visitors) * 100, 2) if visitors else 0.0,
                "daily_trend": traffic_daily_trend,
                "page_breakdown": traffic_page_breakdown,
                "automated_browser_collection_enabled": False,
                "raw_ip_stored": False,
                "user_agent_stored": False,
            },
            "performance_analytics": performance_analytics,
            "provider_reliability_analytics": provider_reliability_analytics,
            "model_cost_analytics": {
                "status": "metered" if model_usage else "ready_no_usage",
                "byok_tokens_are_merchant_billed": True,
                "usage": model_usage,
                "platform_trial_tokens": sum(
                    row["total_tokens"] for row in model_usage if row["usage_owner"] == "jiejing_platform_trial"
                ),
                "merchant_byok_tokens": sum(
                    row["total_tokens"] for row in model_usage if row["usage_owner"] == "merchant_account_byok"
                ),
                "platform_cost_minor": platform_model_cost_minor,
                "currency": "CNY",
                "prompts_stored": False,
                "responses_stored": False,
                "metering_started_at": metering_started_at,
                "current_metering_health": current_metering_health,
                "legacy_unmetered_tasks": legacy_unmetered_model_tasks,
                "current_unmetered_tasks": current_unmetered_model_tasks,
            },
            "provider_cost_analytics": {
                "status": "metered" if provider_costs else "ready_no_usage",
                "provider_neutral": True,
                "costs": provider_costs,
                "media_cost_minor": media_cost_minor,
                "public_search_cost_minor": public_search_cost_minor,
                "total_provider_cost_minor": provider_cost_minor,
                "currency": "CNY",
                "raw_provider_response_stored": False,
            },
            "unit_economics": {
                "status": "ready" if cost_coverage_complete else "partial",
                "paid_order_count": len(paid_order_rows),
                "paid_company_count": len(period_paid_company_ids),
                "paid_revenue_minor": paid_revenue_minor,
                "active_subscriber_company_count": len(active_subscription_company_ids),
                "normalized_mrr_minor": normalized_mrr_minor,
                "mrr_status": "ready" if mrr_missing_order_count == 0 and not subscription_order_scan_capped else "partial",
                "mrr_missing_order_count": mrr_missing_order_count,
                "platform_model_cost_minor": platform_model_cost_minor,
                "media_cost_minor": media_cost_minor,
                "public_search_cost_minor": public_search_cost_minor,
                "total_provider_cost_minor": provider_cost_minor,
                "contribution_margin_minor": contribution_margin_minor,
                "currency": "CNY",
                "unknown_model_cost_records": unknown_model_cost_records,
                "unknown_provider_cost_records": unknown_provider_cost_records,
                "unmetered_model_tasks": unmetered_model_tasks,
                "legacy_unmetered_model_tasks": legacy_unmetered_model_tasks,
                "current_unmetered_model_tasks": current_unmetered_model_tasks,
                "metering_started_at": metering_started_at,
                "current_metering_health": current_metering_health,
                "unmetered_media_settlements": int(unmetered_media_row["count"] or 0),
                "cost_coverage_complete": cost_coverage_complete,
            },
            "data_quality": {
                "scope": "merchant_accounts_and_commercial_transactions",
                "synthetic_test_accounts_excluded": int(accounts_row["synthetic_test_accounts"] or 0),
                "test_subscriptions_excluded": test_subscriptions_excluded,
                "acceptance_orders_excluded": sum(1 for row in all_order_rows if acceptance_order(row)),
                "test_payment_providers_excluded": sum(
                    1
                    for row in all_order_rows
                    if non_commercial_provider(row["provider"]) or not bool(row["merchant_account"])
                ),
                "rehearsal_data_excluded": True,
                "subscription_order_scan_capped": subscription_order_scan_capped,
            },
            "merchant_navigation_visible": False,
            "frontend_gets_secret": False,
            "secret_exposed": False,
        }

    def platform_operations_detail(
        self,
        *,
        section: str,
        period_days: int = 30,
        cursor: str | None = None,
        limit: int = 25,
        status: str | None = None,
        category: str | None = None,
        plan: str | None = None,
        module: str | None = None,
        event: str | None = None,
        result: str | None = None,
    ) -> dict[str, Any]:
        """Return bounded, sanitized internal operations drill-down records."""

        self.initialize()
        normalized_section = str(section or "").strip().lower()
        if normalized_section not in {"traffic", "merchants", "transactions", "costs", "workflows", "audit"}:
            raise ValueError("unsupported operations detail section")
        safe_period_days = min(max(int(30 if period_days is None else period_days), 1), 366)
        safe_limit = min(max(int(limit or 25), 1), 100)
        offset = _operations_cursor_offset(cursor)
        period_ended_at = datetime.now(timezone.utc)
        period_start_date = period_ended_at.date() - timedelta(days=safe_period_days - 1)
        period_started_at = datetime.combine(period_start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        normalized_filters = {
            "status": str(status or "").strip().lower(),
            "category": str(category or "").strip().lower(),
            "plan": str(plan or "").strip().lower(),
            "module": str(module or "").strip().lower(),
            "event": str(event or "").strip().lower(),
            "result": str(result or "").strip().lower(),
        }

        if normalized_section == "traffic":
            overview = self.platform_operations_overview(period_days=safe_period_days)
            return {
                "contract_version": "2026-07-15-platform-operations-detail-v1",
                "section": "traffic",
                "period": overview["period"],
                "summary": overview["traffic_analytics"],
                "performance": overview["performance_analytics"],
                "items": overview["traffic_analytics"].get("page_breakdown", []),
                "next_cursor": "",
                "privacy": {
                    "raw_ip_stored": False,
                    "raw_url_stored": False,
                    "visitor_level_tracking_exposed": False,
                },
                "secret_exposed": False,
            }

        with self._connect() as conn:
            if normalized_section == "merchants":
                rows = conn.execute(
                    """
                    select c.company_id, c.name, c.created_at,
                           (select u.email from users u where u.default_company_id = c.company_id
                            and u.account_classification = 'merchant' order by u.created_at asc limit 1) as email,
                           (select u.status from users u where u.default_company_id = c.company_id
                            and u.account_classification = 'merchant' order by u.created_at asc limit 1) as account_status,
                           s.plan_key, s.status as subscription_status, s.entitlement_active, s.updated_at as subscription_updated_at,
                           (select max(t.updated_at) from tasks t where t.company_id = c.company_id) as last_workflow_at,
                           (select count(*) from stores st where st.company_id = c.company_id) as store_count
                    from companies c
                    left join billing_subscriptions s on s.company_id = c.company_id
                    where exists (
                      select 1 from users u where u.default_company_id = c.company_id
                      and u.account_classification = 'merchant'
                    )
                    order by c.created_at desc, c.company_id asc
                    limit 5001
                    """
                ).fetchall()
                records = []
                for row in rows:
                    account_status = str(row["account_status"] or "unknown").lower()
                    subscription_status = str(row["subscription_status"] or "none").lower()
                    plan_key = str(row["plan_key"] or "free").lower()
                    if normalized_filters["status"] and normalized_filters["status"] not in {account_status, subscription_status}:
                        continue
                    if normalized_filters["plan"] and normalized_filters["plan"] != plan_key:
                        continue
                    records.append(
                        {
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "company_name": str(row["name"] or "未命名商家")[:80],
                            "email_masked": _operations_mask_email(row["email"]),
                            "account_status": account_status,
                            "plan_key": plan_key,
                            "subscription_status": subscription_status,
                            "entitlement_active": bool(row["entitlement_active"]),
                            "store_count": int(row["store_count"] or 0),
                            "registered_at": str(row["created_at"] or ""),
                            "last_active_at": str(row["last_workflow_at"] or row["subscription_updated_at"] or ""),
                        }
                    )
            elif normalized_section == "transactions":
                rows = conn.execute(
                    """
                    select o.* from billing_orders o
                    where coalesce(o.paid_at, o.created_at) >= ? and exists (
                      select 1 from users u where u.default_company_id = o.company_id
                      and u.account_classification = 'merchant'
                    )
                    order by o.created_at desc, o.order_id asc
                    limit 5001
                    """,
                    (period_started_at,),
                ).fetchall()
                records = []
                for row in rows:
                    provider = str(row["provider"] or "").strip().lower()
                    payload = _load_json_field(row["order_json"])
                    if provider in _NON_COMMERCIAL_BILLING_PROVIDERS or provider.endswith("_mock"):
                        continue
                    if isinstance(payload, dict) and payload.get("live_acceptance_test") is True:
                        continue
                    row_status = str(row["status"] or "unknown").lower()
                    plan_key = str(row["plan_key"] or "unknown").lower()
                    kind = "media_credit" if "media" in plan_key or "credit" in plan_key else "subscription"
                    if normalized_filters["status"] and normalized_filters["status"] != row_status:
                        continue
                    if normalized_filters["category"] and normalized_filters["category"] != kind:
                        continue
                    records.append(
                        {
                            "transaction_ref": _operations_short_ref("billing-order", row["order_id"]),
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "kind": kind,
                            "plan_key": plan_key,
                            "status": row_status,
                            "amount_minor": int(row["amount_minor"] or 0),
                            "currency": str(row["currency"] or "CNY"),
                            "payment_channel": "domestic_payment" if provider == "wechat_pay_native" else "external_payment",
                            "created_at": str(row["created_at"] or ""),
                            "paid_at": str(row["paid_at"] or ""),
                            "updated_at": str(row["updated_at"] or ""),
                        }
                    )
            elif normalized_section == "costs":
                model_rows = conn.execute(
                    """
                    select usage_id, company_id, task_id, usage_owner, request_count,
                           input_tokens, output_tokens, total_tokens, cost_minor, currency, cost_status, created_at
                    from model_usage_ledger m where created_at >= ? and (
                      company_id is null or exists (
                        select 1 from users u where u.default_company_id = m.company_id
                        and u.account_classification = 'merchant'
                      )
                    ) order by created_at desc limit 5001
                    """,
                    (period_started_at,),
                ).fetchall()
                provider_rows = conn.execute(
                    """
                    select cost_id, company_id, task_id, cost_category, resource_type,
                           unit_count, media_points, cost_minor, currency, cost_status, created_at
                    from provider_cost_ledger c where created_at >= ? and (
                      company_id is null or exists (
                        select 1 from users u where u.default_company_id = c.company_id
                        and u.account_classification = 'merchant'
                      )
                    ) order by created_at desc limit 5001
                    """,
                    (period_started_at,),
                ).fetchall()
                records = []
                for row in model_rows:
                    cost_status = str(row["cost_status"] or "unavailable").lower()
                    if normalized_filters["category"] and normalized_filters["category"] != "model":
                        continue
                    if normalized_filters["status"] and normalized_filters["status"] != cost_status:
                        continue
                    records.append(
                        {
                            "cost_ref": _operations_short_ref("model-cost", row["usage_id"]),
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "category": "model",
                            "resource_type": "text_model",
                            "usage_owner": str(row["usage_owner"] or "unknown"),
                            "units": int(row["request_count"] or 0),
                            "input_tokens": int(row["input_tokens"] or 0),
                            "output_tokens": int(row["output_tokens"] or 0),
                            "total_tokens": int(row["total_tokens"] or 0),
                            "cost_minor": int(row["cost_minor"] or 0),
                            "currency": str(row["currency"] or "CNY"),
                            "cost_status": cost_status,
                            "created_at": str(row["created_at"] or ""),
                        }
                    )
                for row in provider_rows:
                    cost_category = str(row["cost_category"] or "other").lower()
                    cost_status = str(row["cost_status"] or "unavailable").lower()
                    if normalized_filters["category"] and normalized_filters["category"] != cost_category:
                        continue
                    if normalized_filters["status"] and normalized_filters["status"] != cost_status:
                        continue
                    records.append(
                        {
                            "cost_ref": _operations_short_ref("provider-cost", row["cost_id"]),
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "category": cost_category,
                            "resource_type": str(row["resource_type"] or "unknown")[:40],
                            "units": int(row["unit_count"] or 0),
                            "media_points": int(row["media_points"] or 0),
                            "cost_minor": int(row["cost_minor"] or 0),
                            "currency": str(row["currency"] or "CNY"),
                            "cost_status": cost_status,
                            "created_at": str(row["created_at"] or ""),
                        }
                    )
                records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            elif normalized_section == "workflows":
                rows = conn.execute(
                    """
                    select t.task_id, t.company_id, t.task_type, t.status, t.created_at, t.updated_at,
                           (select count(*) from queue_jobs q where q.task_id = t.task_id) as job_count,
                           (select coalesce(sum(q.attempts), 0) from queue_jobs q where q.task_id = t.task_id) as attempt_count
                    from tasks t where t.created_at >= ? and exists (
                      select 1 from users u where u.default_company_id = t.company_id
                      and u.account_classification = 'merchant'
                    ) order by t.created_at desc, t.task_id asc limit 5001
                    """,
                    (period_started_at,),
                ).fetchall()
                records = []
                for row in rows:
                    task_status = str(row["status"] or "unknown").lower()
                    task_module = str(row["task_type"] or "unknown").lower()
                    if normalized_filters["status"] and normalized_filters["status"] != task_status:
                        continue
                    if normalized_filters["module"] and normalized_filters["module"] not in task_module:
                        continue
                    records.append(
                        {
                            "task_ref": _operations_short_ref("task", row["task_id"]),
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "module": task_module,
                            "status": task_status,
                            "job_count": int(row["job_count"] or 0),
                            "attempt_count": int(row["attempt_count"] or 0),
                            "created_at": str(row["created_at"] or ""),
                            "updated_at": str(row["updated_at"] or ""),
                        }
                    )
            else:
                rows = conn.execute(
                    """
                    select a.audit_id, a.company_id, a.actor_type, a.action_type, a.target_type,
                           a.created_at, a.audit_json from audit_logs a
                    where a.created_at >= ? and exists (
                      select 1 from users u where u.default_company_id = a.company_id
                      and u.account_classification = 'merchant'
                    ) order by a.created_at desc, a.audit_id asc limit 5001
                    """,
                    (period_started_at,),
                ).fetchall()
                records = []
                for row in rows:
                    action_type = str(row["action_type"] or "unknown").lower()
                    packet = _load_json_field(row["audit_json"])
                    details = packet.get("details") if isinstance(packet, dict) and isinstance(packet.get("details"), dict) else {}
                    action_result = str(details.get("result") or details.get("status") or "recorded").lower()
                    if normalized_filters["event"] and normalized_filters["event"] not in action_type:
                        continue
                    if normalized_filters["result"] and normalized_filters["result"] != action_result:
                        continue
                    records.append(
                        {
                            "audit_ref": _operations_short_ref("audit", row["audit_id"]),
                            "company_ref": _operations_short_ref("company", row["company_id"]),
                            "actor_type": str(row["actor_type"] or "unknown")[:32],
                            "action_type": action_type[:120],
                            "target_type": str(row["target_type"] or "unknown")[:80],
                            "result": action_result[:40],
                            "created_at": str(row["created_at"] or ""),
                        }
                    )

        total_available = len(records)
        page_items = records[offset : offset + safe_limit]
        next_offset = offset + len(page_items)
        return {
            "contract_version": "2026-07-15-platform-operations-detail-v1",
            "section": normalized_section,
            "period": {"days": safe_period_days, "started_at": period_started_at},
            "filters": {key: value for key, value in normalized_filters.items() if value},
            "items": page_items,
            "returned_count": len(page_items),
            "has_more": next_offset < total_available,
            "next_cursor": _operations_next_cursor(next_offset) if next_offset < total_available else "",
            "data_window_capped": total_available > 5000,
            "merchant_content_exposed": False,
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def product_readiness_evidence(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from platform_data_packets
                where platform = 'ebay'
                order by created_at desc
                limit 1
                """
            ).fetchone()
            latest_packet = self._platform_data_packet_row_to_dict(row) if row else None
            read_only_authorized_connections = int(
                conn.execute(
                    """
                    select count(*) as count from platform_connections
                    where platform = 'ebay' and status = 'read_only_authorized'
                    """
                ).fetchone()["count"]
            )
            ebay_secret_refs = int(
                conn.execute(
                    """
                    select count(*) as count from secret_refs
                    where provider = 'ebay'
                      and purpose = 'ebay_refresh_token'
                      and status in ({})
                    """.format(", ".join("?" for _ in ACTIVE_SECRET_REF_STATUSES)),
                    tuple(sorted(ACTIVE_SECRET_REF_STATUSES)),
                ).fetchone()["count"]
            )
            model_secret_refs = int(
                conn.execute(
                    """
                    select count(*) as count from secret_refs
                    where purpose = 'model_api_key'
                      and status in ({})
                    """.format(", ".join("?" for _ in ACTIVE_MODEL_SECRET_REF_STATUSES)),
                    tuple(sorted(ACTIVE_MODEL_SECRET_REF_STATUSES)),
                ).fetchone()["count"]
            )
            ebay_token_refresh_success_count = int(
                conn.execute(
                    """
                    select count(*) as count from audit_logs
                    where action_type = 'oauth.token_refresh.executed'
                      and cast(audit_json as text) like ?
                      and cast(audit_json as text) like ?
                    """,
                    ('%"ok": true%', '%"status": "refreshed"%'),
                ).fetchone()["count"]
            )
            latest_ebay_token_refresh_success = conn.execute(
                """
                select created_at from audit_logs
                where action_type = 'oauth.token_refresh.executed'
                  and cast(audit_json as text) like ?
                  and cast(audit_json as text) like ?
                order by created_at desc
                limit 1
                """,
                ('%"ok": true%', '%"status": "refreshed"%'),
            ).fetchone()
            report_count = int(conn.execute("select count(*) as count from reports").fetchone()["count"])
            confirmation_count = int(conn.execute("select count(*) as count from confirmations").fetchone()["count"])
            ebay_identity_rows = conn.execute(
                """
                select company_id, store_id, status, metadata_json from platform_connections
                where lower(platform) = 'ebay'
                  and status in ('read_only_authorized', 'publish_authorized')
                """
            ).fetchall()
            latest_packet_connection_count = 0
            latest_packet_secret_ref_count = 0
            if latest_packet:
                latest_packet_connection_count = int(
                    conn.execute(
                        """
                        select count(*) as count from platform_connections
                        where lower(platform) = 'ebay'
                          and company_id = ?
                          and store_id = ?
                          and status in ('read_only_authorized', 'publish_authorized')
                        """,
                        (latest_packet["company_id"], latest_packet["store_id"]),
                    ).fetchone()["count"]
                )
                latest_packet_secret_ref_count = int(
                    conn.execute(
                        """
                        select count(*) as count from secret_refs
                        where provider = 'ebay'
                          and purpose = 'ebay_refresh_token'
                          and company_id = ?
                          and store_id = ?
                          and status in ({})
                        """.format(", ".join("?" for _ in ACTIVE_SECRET_REF_STATUSES)),
                        (
                            latest_packet["company_id"],
                            latest_packet["store_id"],
                            *tuple(sorted(ACTIVE_SECRET_REF_STATUSES)),
                        ),
                    ).fetchone()["count"]
                )

        mapped_ebay_identities = 0
        identity_store_owners: dict[str, set[str]] = {}
        for identity_row in ebay_identity_rows:
            metadata = _load_json_field(identity_row["metadata_json"])
            if isinstance(metadata, dict) and any(
                str(metadata.get(key) or "")
                for key in ("ebay_user_id_hash", "ebay_username_hash", "ebay_eias_identity_hash")
            ):
                mapped_ebay_identities += 1
            if isinstance(metadata, dict) and metadata.get("ebay_user_id_hash"):
                selector = str(metadata["ebay_user_id_hash"])
                owner = f"{identity_row['company_id']}:{identity_row['store_id']}"
                identity_store_owners.setdefault(selector, set()).add(owner)
        duplicate_identity_store_count = sum(max(0, len(owners) - 1) for owners in identity_store_owners.values())

        packet_body = latest_packet.get("packet") if isinstance(latest_packet, dict) else {}
        if not isinstance(packet_body, dict):
            packet_body = {}
        present = packet_body.get("present_resource_keys")
        missing = packet_body.get("missing_resource_keys")
        latest_packet_current_connection = bool(
            latest_packet and latest_packet_connection_count > 0 and latest_packet_secret_ref_count > 0
        )
        return {
            "read_only_authorized_connections": read_only_authorized_connections,
            "ebay_secret_refs": ebay_secret_refs,
            "latest_ebay_packet_id": latest_packet.get("packet_id") if latest_packet else "",
            "latest_ebay_packet_status": latest_packet.get("status") if latest_packet else "",
            "latest_ebay_packet_source_mode": latest_packet.get("source_mode") if latest_packet else "",
            "latest_ebay_packet_created_at": latest_packet.get("created_at") if latest_packet else "",
            "latest_ebay_packet_present_resource_keys": present if isinstance(present, list) else [],
            "latest_ebay_packet_missing_resource_keys": missing if isinstance(missing, list) else [],
            "latest_ebay_packet_current_connection": latest_packet_current_connection,
            "historical_ebay_packet_present": bool(latest_packet and not latest_packet_current_connection),
            "model_secret_refs": model_secret_refs,
            "ebay_token_refresh_success_count": ebay_token_refresh_success_count,
            "latest_ebay_token_refresh_success_at": latest_ebay_token_refresh_success["created_at"] if latest_ebay_token_refresh_success else "",
            "report_count": report_count,
            "confirmation_count": confirmation_count,
            "active_ebay_identity_connections": len(ebay_identity_rows),
            "mapped_ebay_identity_connections": mapped_ebay_identities,
            "duplicate_ebay_identity_store_count": duplicate_identity_store_count,
            "secret_exposed": False,
        }

    def list_schema_migrations(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "select migration_id, applied_at, checksum, summary from schema_migrations order by applied_at, migration_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_database_indexes(self) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            tables = _table_names(conn)
            indexes: list[dict[str, Any]] = []
            if self.database_engine == "postgres":
                rows = conn.execute(
                    """
                    select
                      i.tablename as table,
                      i.indexname as index_name,
                      case when ix.indisunique then 1 else 0 end as unique,
                      'postgres' as origin,
                      case when ix.indpred is not null then 1 else 0 end as partial,
                      i.indexdef as indexdef
                    from pg_indexes i
                    join pg_class t on t.relname = i.tablename
                    join pg_class c on c.relname = i.indexname
                    join pg_index ix on ix.indexrelid = c.oid and ix.indrelid = t.oid
                    where i.schemaname = 'public'
                    order by i.tablename, i.indexname
                    """
                ).fetchall()
                for row in rows:
                    indexes.append(
                        {
                            "table": row["table"],
                            "index_name": row["index_name"],
                            "unique": bool(row["unique"]),
                            "origin": row["origin"],
                            "partial": bool(row["partial"]),
                            "columns": [],
                            "definition": row["indexdef"],
                        }
                    )
                return indexes
            for table in tables:
                for index_row in conn.execute(f"pragma index_list({table})").fetchall():
                    index_name = str(index_row["name"])
                    columns = [
                        str(column_row["name"])
                        for column_row in conn.execute(f"pragma index_info({index_name})").fetchall()
                    ]
                    indexes.append(
                        {
                            "table": table,
                            "index_name": index_name,
                            "unique": bool(index_row["unique"]),
                            "origin": index_row["origin"],
                            "partial": bool(index_row["partial"]),
                            "columns": columns,
                        }
                    )
        indexes.sort(key=lambda item: (str(item["table"]), str(item["index_name"])))
        return indexes

    def database_inventory(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            tables = _table_names(conn)
            table_rows = []
            for table in tables:
                count = int(conn.execute(f"select count(*) as count from {table}").fetchone()["count"])
                table_rows.append({"table": table, "row_count": count})
        migrations = self.list_schema_migrations()
        indexes = self.list_database_indexes()
        return {
            "db_path": str(self.db_path) if self.database_engine == "sqlite" else "[managed-postgres]",
            "engine": self.database_engine,
            "table_count": len(tables),
            "tables": table_rows,
            "migration_count": len(migrations),
            "migrations": migrations,
            "index_count": len(indexes),
            "indexes": indexes,
            "secret_exposed": False,
        }

    def queue_status_counts(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select status, count(*) as count
                from queue_jobs
                group by status
                order by status
                """
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def acquire_provider_monitoring_lease(
        self,
        *,
        scheduler_key: str,
        owner_hash: str,
        lease_seconds: int,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        """Atomically acquire an expiring singleton lease without exposing its owner."""

        self.initialize()
        safe_scheduler_key = str(scheduler_key or "").strip()[:120]
        safe_owner_hash = str(owner_hash or "").strip()[:128]
        if not safe_scheduler_key or not safe_owner_hash:
            raise ValueError("provider monitoring scheduler key and owner hash are required")
        current_epoch = int(now_epoch if now_epoch is not None else time.time())
        bounded_lease_seconds = min(3600, max(15, int(lease_seconds)))
        expires_epoch = current_epoch + bounded_lease_seconds
        updated_at = now_iso()
        with self._connect() as conn:
            row = conn.execute(
                """
                insert into platform_provider_monitor_state (
                  scheduler_key, lease_owner_hash, lease_expires_at_epoch,
                  last_evaluated_at, last_exported_at, last_outcome, snapshot_json, updated_at
                ) values (?, ?, ?, null, null, 'idle', '{}', ?)
                on conflict(scheduler_key) do update set
                  lease_owner_hash = excluded.lease_owner_hash,
                  lease_expires_at_epoch = excluded.lease_expires_at_epoch,
                  updated_at = excluded.updated_at
                where platform_provider_monitor_state.lease_expires_at_epoch <= ?
                returning scheduler_key
                """,
                (safe_scheduler_key, safe_owner_hash, expires_epoch, updated_at, current_epoch),
            ).fetchone()
        if not row:
            return {
                "acquired": False,
                "status": "skipped_lease_contended",
                "secret_exposed": False,
            }
        return {
            "acquired": True,
            "status": "lease_acquired",
            "lease_seconds": bounded_lease_seconds,
            "secret_exposed": False,
        }

    def complete_provider_monitoring_evaluation(
        self,
        *,
        scheduler_key: str,
        owner_hash: str,
        evaluated_at: str | None,
        exported_at: str | None,
        outcome: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist allowlisted aggregate evidence while retaining the lease until interval expiry."""

        self.initialize()
        safe_scheduler_key = str(scheduler_key or "").strip()[:120]
        safe_owner_hash = str(owner_hash or "").strip()[:128]
        if not safe_scheduler_key or not safe_owner_hash:
            raise ValueError("provider monitoring scheduler key and owner hash are required")
        normalized_outcome = str(outcome or "evaluation_failed").strip().lower()
        if normalized_outcome not in {
            "exported",
            "export_failed",
            "query_failed",
            "evaluation_failed",
        }:
            normalized_outcome = "evaluation_failed"
        safe_snapshot = {
            key: value
            for key, value in (snapshot.items() if isinstance(snapshot, dict) else [])
            if key in PROVIDER_MONITOR_AGGREGATE_KEYS and isinstance(value, (str, int, bool))
        }
        with self._connect() as conn:
            row = conn.execute(
                """
                update platform_provider_monitor_state
                set last_evaluated_at = coalesce(?, last_evaluated_at),
                    last_exported_at = coalesce(?, last_exported_at),
                    last_outcome = ?,
                    snapshot_json = ?,
                    updated_at = ?
                where scheduler_key = ? and lease_owner_hash = ?
                returning scheduler_key
                """,
                (
                    str(evaluated_at or "")[:80] or None,
                    str(exported_at or "")[:80] or None,
                    normalized_outcome,
                    json.dumps(safe_snapshot, ensure_ascii=False, sort_keys=True),
                    now_iso(),
                    safe_scheduler_key,
                    safe_owner_hash,
                ),
            ).fetchone()
        return {
            "updated": bool(row),
            "status": normalized_outcome if row else "lease_owner_mismatch",
            "secret_exposed": False,
        }

    def provider_monitoring_state(self, *, scheduler_key: str = "provider-monitor") -> dict[str, Any]:
        """Return scheduler evidence without lease ownership or cloud identifiers."""

        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                """
                select last_evaluated_at, last_exported_at, last_outcome, snapshot_json
                from platform_provider_monitor_state where scheduler_key = ?
                """,
                (str(scheduler_key or "provider-monitor").strip()[:120],),
            ).fetchone()
        if not row:
            return {
                "configured": False,
                "last_evaluated_at": "",
                "last_exported_at": "",
                "last_outcome": "never_run",
                "aggregate": {},
                "secret_exposed": False,
            }
        aggregate = _load_json_field(row["snapshot_json"])
        return {
            "configured": True,
            "last_evaluated_at": str(row["last_evaluated_at"] or ""),
            "last_exported_at": str(row["last_exported_at"] or ""),
            "last_outcome": str(row["last_outcome"] or "never_run"),
            "aggregate": aggregate if isinstance(aggregate, dict) else {},
            "secret_exposed": False,
        }

    def provider_monitoring_snapshot(
        self,
        *,
        reliability_window_minutes: int = 30,
        cost_window_hours: int = 24,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate passive real-business provider telemetry over focused windows."""

        self.initialize()
        bounded_reliability_minutes = min(1440, max(1, int(reliability_window_minutes)))
        bounded_cost_hours = min(168, max(1, int(cost_window_hours)))
        current = now_utc or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone()
        reliability_started_at = (current - timedelta(minutes=bounded_reliability_minutes)).isoformat()
        cost_started_at = (current - timedelta(hours=bounded_cost_hours)).isoformat()
        merchant_company_predicate = """
          exists (
            select 1 from users u
            where u.default_company_id = {alias}.company_id and u.account_classification = 'merchant'
          )
        """
        merchant_actor_predicate = """
          (
            {alias}.user_id is null
            or exists (
              select 1 from users actor_user
              where actor_user.user_id = {alias}.user_id
                and actor_user.account_classification = 'merchant'
            )
          )
        """
        task_predicate = """
          ({alias}.task_id is null or not exists (
            select 1 from tasks eligible_task
            where eligible_task.task_id = {alias}.task_id and (
              lower(eligible_task.task_type) like '%%rehearsal%%'
              or lower(eligible_task.task_type) like '%%acceptance%%'
              or lower(eligible_task.task_type) like '%%verification%%'
              or lower(eligible_task.task_type) like '%%probe%%'
              or not exists (
                select 1 from users task_actor
                where task_actor.user_id = eligible_task.user_id
                  and task_actor.account_classification = 'merchant'
              )
            )
          ))
        """
        payment_predicate = """
          (
            c.reference_type <> 'payment_provider_call'
            or (
              billing_order.order_id is not null
              and lower(coalesce(billing_order.provider, '')) not in ('manual_beta', 'stripe_test_mock')
              and replace(cast(billing_order.order_json as text), ' ', '') not like '%%\"live_acceptance_test\":true%%'
            )
          )
        """
        with self._connect() as conn:
            model_reliability_rows = conn.execute(
                f"""
                select usage_json
                from model_usage_ledger m
                where m.created_at >= ?
                  and {merchant_company_predicate.format(alias='m')}
                  and {merchant_actor_predicate.format(alias='m')}
                  and {task_predicate.format(alias='m')}
                order by m.created_at desc
                limit 5000
                """,
                (reliability_started_at,),
            ).fetchall()
            provider_reliability_rows = conn.execute(
                f"""
                select c.cost_json
                from provider_cost_ledger c
                left join billing_orders billing_order
                  on c.reference_type = 'payment_provider_call' and billing_order.order_id = c.reference_id
                where c.created_at >= ?
                  and {merchant_company_predicate.format(alias='c')}
                  and {merchant_actor_predicate.format(alias='c')}
                  and {task_predicate.format(alias='c')}
                  and {payment_predicate}
                order by c.created_at desc
                limit 5000
                """,
                (reliability_started_at,),
            ).fetchall()
            model_cost_rows = conn.execute(
                f"""
                select m.usage_owner, m.cost_status,
                       coalesce(sum(m.request_count), 0) as request_count,
                       coalesce(sum(m.cost_minor), 0) as cost_minor
                from model_usage_ledger m
                where m.created_at >= ?
                  and {merchant_company_predicate.format(alias='m')}
                  and {merchant_actor_predicate.format(alias='m')}
                  and {task_predicate.format(alias='m')}
                group by m.usage_owner, m.cost_status
                """,
                (cost_started_at,),
            ).fetchall()
            provider_cost_rows = conn.execute(
                f"""
                select c.cost_status, count(*) as record_count,
                       coalesce(sum(c.cost_minor), 0) as cost_minor
                from provider_cost_ledger c
                left join billing_orders billing_order
                  on c.reference_type = 'payment_provider_call' and billing_order.order_id = c.reference_id
                where c.created_at >= ?
                  and {merchant_company_predicate.format(alias='c')}
                  and {merchant_actor_predicate.format(alias='c')}
                  and {task_predicate.format(alias='c')}
                  and {payment_predicate}
                group by c.cost_status
                """,
                (cost_started_at,),
            ).fetchall()
            current_unmetered_row = conn.execute(
                f"""
                select count(*) as count
                from tasks t
                left join model_usage_ledger m on m.task_id = t.task_id
                where t.task_type = 'merchant_ceo_chat'
                  and t.created_at >= ? and m.usage_id is null
                  and {merchant_company_predicate.format(alias='t')}
                  and {merchant_actor_predicate.format(alias='t')}
                """,
                (cost_started_at,),
            ).fetchone()

        def nonnegative_int(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError, OverflowError):
                return 0

        def bounded_duration(value: Any) -> int | None:
            try:
                duration = int(value)
            except (TypeError, ValueError, OverflowError):
                return None
            return min(120_000, max(0, duration))

        buckets: dict[str, dict[str, Any]] = {
            scope: {
                "request_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "timeout_count": 0,
                "partial_count": 0,
                "blocked_count": 0,
                "durations": [],
                "error_classes": {},
            }
            for scope in ("model", "public_search", "media_generation", "payment")
        }
        for row in model_reliability_rows:
            packet = _load_json_field(row["usage_json"])
            details = packet.get("details") if isinstance(packet, dict) and isinstance(packet.get("details"), dict) else {}
            telemetry = details.get("reliability") if isinstance(details.get("reliability"), dict) else {}
            if not telemetry:
                continue
            bucket = buckets["model"]
            request_count = nonnegative_int(telemetry.get("request_count"))
            success_count = min(request_count, nonnegative_int(telemetry.get("success_count")))
            bucket["request_count"] += request_count
            bucket["success_count"] += success_count
            bucket["failure_count"] += max(0, request_count - success_count)
            bucket["timeout_count"] += min(request_count, nonnegative_int(telemetry.get("timeout_count")))
            duration_samples = telemetry.get("duration_samples_ms") if isinstance(telemetry.get("duration_samples_ms"), list) else []
            if not duration_samples:
                duration_samples = [telemetry.get("p75_duration_ms")]
            for value in duration_samples[:50]:
                duration = bounded_duration(value)
                if duration is not None:
                    bucket["durations"].append(duration)
        for row in provider_reliability_rows:
            packet = _load_json_field(row["cost_json"])
            details = packet.get("details") if isinstance(packet, dict) and isinstance(packet.get("details"), dict) else {}
            telemetry = details.get("telemetry") if isinstance(details.get("telemetry"), dict) else {}
            scope = str(telemetry.get("scope") or "")
            if scope not in {"public_search", "media_generation", "payment"}:
                continue
            outcome = str(telemetry.get("outcome") or "error")
            if outcome not in {"success", "partial", "error", "timeout", "blocked"}:
                outcome = "error"
            bucket = buckets[scope]
            bucket["request_count"] += 1
            bucket["success_count"] += 1 if outcome == "success" else 0
            bucket["failure_count"] += 0 if outcome == "success" else 1
            bucket["timeout_count"] += 1 if outcome == "timeout" else 0
            bucket["partial_count"] += 1 if outcome == "partial" else 0
            bucket["blocked_count"] += 1 if outcome == "blocked" else 0
            duration = bounded_duration(telemetry.get("duration_ms"))
            if duration is not None:
                bucket["durations"].append(duration)

        def reliability_summary(scope: str) -> dict[str, Any]:
            bucket = buckets[scope]
            durations = sorted(bucket.pop("durations"))
            return {
                "status": "instrumented" if bucket["request_count"] else "ready_no_samples",
                "sample_count": len(durations),
                **bucket,
                "p75_duration_ms": durations[max(0, ((len(durations) * 3 + 3) // 4) - 1)] if durations else None,
                "max_duration_ms": max(durations) if durations else None,
            }

        reliability = {scope: reliability_summary(scope) for scope in buckets}
        reliability.update(
            {
                "provider_neutral": True,
                "prompts_stored": False,
                "responses_stored": False,
                "queries_stored": False,
                "raw_errors_stored": False,
                "raw_provider_response_stored": False,
            }
        )
        reliability["alerts"] = build_reliability_alert_summary(reliability)
        platform_model_cost_minor = sum(
            nonnegative_int(row["cost_minor"])
            for row in model_cost_rows
            if str(row["usage_owner"] or "") == "jiejing_platform_trial"
        )
        provider_cost_minor = sum(nonnegative_int(row["cost_minor"]) for row in provider_cost_rows)
        current_unmetered_model_tasks = nonnegative_int(current_unmetered_row["count"] if current_unmetered_row else 0)
        unknown_model_cost_records = current_unmetered_model_tasks + sum(
            nonnegative_int(row["request_count"])
            for row in model_cost_rows
            if str(row["usage_owner"] or "") in {"jiejing_platform_trial", "unknown"}
            and str(row["cost_status"] or "") == "unavailable"
        )
        unknown_provider_cost_records = sum(
            nonnegative_int(row["record_count"])
            for row in provider_cost_rows
            if str(row["cost_status"] or "") == "unavailable"
        )
        return {
            "contract_version": "2026-07-17-provider-monitoring-snapshot-v1",
            "reliability_window_minutes": bounded_reliability_minutes,
            "cost_window_hours": bounded_cost_hours,
            "reliability": reliability,
            "platform_model_cost_minor": platform_model_cost_minor,
            "provider_cost_minor": provider_cost_minor,
            "cost_total_minor": platform_model_cost_minor + provider_cost_minor,
            "unknown_model_cost_records": unknown_model_cost_records,
            "unknown_provider_cost_records": unknown_provider_cost_records,
            "current_unmetered_model_tasks": current_unmetered_model_tasks,
            "cost_coverage_complete": not bool(unknown_model_cost_records or unknown_provider_cost_records),
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def consume_rate_limit_bucket(
        self,
        *,
        scope: str,
        subject: str,
        limit: int,
        window_seconds: int,
        now_epoch: int | None = None,
    ) -> dict[str, Any]:
        """Atomically consume an expiring shared bucket without persisting PII."""

        self.initialize()
        current_epoch = int(now_epoch if now_epoch is not None else time.time())
        bounded_limit = max(1, int(limit))
        bounded_window = max(1, int(window_seconds))
        expires_epoch = current_epoch + bounded_window
        safe_scope = str(scope or "unknown")[:160]
        bucket_key_hash = hashlib.sha256(f"{safe_scope}|{subject}".encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("delete from api_rate_limit_buckets where expires_epoch <= ?", (current_epoch,))
            row = conn.execute(
                """
                insert into api_rate_limit_buckets (
                  bucket_key_hash, scope, request_count, limit_count,
                  window_started_epoch, expires_epoch
                ) values (?, ?, 1, ?, ?, ?)
                on conflict (bucket_key_hash) do update set
                  scope = excluded.scope,
                  request_count = case
                    when api_rate_limit_buckets.expires_epoch <= excluded.window_started_epoch then 1
                    else api_rate_limit_buckets.request_count + 1
                  end,
                  limit_count = excluded.limit_count,
                  window_started_epoch = case
                    when api_rate_limit_buckets.expires_epoch <= excluded.window_started_epoch
                    then excluded.window_started_epoch
                    else api_rate_limit_buckets.window_started_epoch
                  end,
                  expires_epoch = case
                    when api_rate_limit_buckets.expires_epoch <= excluded.window_started_epoch
                    then excluded.expires_epoch
                    else api_rate_limit_buckets.expires_epoch
                  end
                returning request_count, limit_count, expires_epoch
                """,
                (bucket_key_hash, safe_scope, bounded_limit, current_epoch, expires_epoch),
            ).fetchone()
        request_count = int(row["request_count"] if row else 1)
        return {
            "allowed": request_count <= bounded_limit,
            "request_count": request_count,
            "limit": bounded_limit,
            "retry_after_seconds": max(1, int((row["expires_epoch"] if row else expires_epoch) - current_epoch)),
            "storage": "shared_database",
            "subject_persisted": False,
            "secret_exposed": False,
        }

    def rate_limit_bucket_summary(self, *, scope_prefix: str, now_epoch: int | None = None) -> list[dict[str, Any]]:
        self.initialize()
        current_epoch = int(now_epoch if now_epoch is not None else time.time())
        with self._connect() as conn:
            conn.execute("delete from api_rate_limit_buckets where expires_epoch <= ?", (current_epoch,))
            rows = conn.execute(
                """
                select scope,
                       count(*) as bucket_count,
                       sum(case when request_count > limit_count then limit_count else request_count end) as request_count,
                       sum(case when request_count >= limit_count then 1 else 0 end) as saturated_count,
                       max(limit_count) as max_requests
                from api_rate_limit_buckets
                where scope like ?
                group by scope
                order by scope
                limit 64
                """,
                (f"{scope_prefix}%",),
            ).fetchall()
        return [
            {
                "scope": str(row["scope"]),
                "active_client_bucket_count": int(row["bucket_count"] or 0),
                "active_request_count": int(row["request_count"] or 0),
                "saturated_client_bucket_count": int(row["saturated_count"] or 0),
                "max_requests": int(row["max_requests"] or 0),
                "client_ip_visible": False,
                "secret_exposed": False,
            }
            for row in rows
        ]

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            create index if not exists idx_users_account_classification_created
              on users(account_classification, created_at);
            create index if not exists idx_platform_trial_activations_status_updated
              on platform_trial_activations(status, updated_at);
            create index if not exists idx_stores_company_platform_created
              on stores(company_id, platform, created_at);
            create index if not exists idx_team_members_company_role
              on team_members(company_id, role);
            create index if not exists idx_user_sessions_user_expiry
              on user_sessions(user_id, expires_epoch);
            create index if not exists idx_team_invitations_company_status_created
              on team_invitations(company_id, status, created_at);
            create index if not exists idx_secret_refs_company_store_provider_purpose
              on secret_refs(company_id, store_id, provider, purpose);
            create index if not exists idx_platform_connections_company_store_platform_status
              on platform_connections(company_id, store_id, platform, status);
            create index if not exists idx_oauth_requests_company_store_status_updated
              on oauth_authorization_requests(company_id, store_id, status, updated_at);
            create index if not exists idx_platform_data_packets_company_store_platform_created
              on platform_data_packets(company_id, store_id, platform, created_at);
            create index if not exists idx_tasks_company_store_status_updated
              on tasks(company_id, store_id, status, updated_at);
            create index if not exists idx_queue_jobs_company_status_updated
              on queue_jobs(company_id, status, updated_at);
            create index if not exists idx_queue_jobs_task_status
              on queue_jobs(task_id, status);
            create index if not exists idx_media_asset_jobs_company_store_status
              on media_asset_jobs(company_id, store_id, status, updated_at);
            create index if not exists idx_media_asset_jobs_task_queue
              on media_asset_jobs(task_id, queue_job_id);
            create index if not exists idx_media_rework_reservations_company_parent
              on media_rework_reservations(company_id, parent_media_job_id, version);
            create index if not exists idx_worker_runtime_heartbeats_updated
              on worker_runtime_heartbeats(heartbeat_at);
            create index if not exists idx_task_steps_company_task_order
              on task_steps(company_id, task_id, step_order);
            create index if not exists idx_reports_task_type_created
              on reports(task_id, report_type, created_at);
            create index if not exists idx_confirmations_company_status_created
              on confirmations(company_id, status, created_at);
            create index if not exists idx_confirmations_task_status
              on confirmations(task_id, status);
            create index if not exists idx_merchant_memory_company_store_created
              on merchant_memory(company_id, store_id, created_at);
            create index if not exists idx_merchant_memory_company_type_created
              on merchant_memory(company_id, memory_type, created_at);
            create index if not exists idx_merchant_memory_source
              on merchant_memory(company_id, source_type, source_id);
            create index if not exists idx_merchant_ceo_commands_company_store_updated
              on merchant_ceo_commands(company_id, store_id, updated_at);
            create index if not exists idx_merchant_ceo_commands_company_route_updated
              on merchant_ceo_commands(company_id, route, updated_at);
            create index if not exists idx_ai_ceo_chat_turns_account_created
              on ai_ceo_chat_turns(company_id, user_id, created_at);
            create index if not exists idx_ai_ceo_chat_turns_account_store_created
              on ai_ceo_chat_turns(company_id, user_id, store_id, created_at);
            create index if not exists idx_execution_results_task_created
              on execution_results(task_id, created_at);
            create index if not exists idx_audit_logs_company_created
              on audit_logs(company_id, created_at);
            create index if not exists idx_audit_logs_target
              on audit_logs(target_type, target_id, created_at);
            create index if not exists idx_billing_subscriptions_provider_customer
              on billing_subscriptions(provider, provider_customer_id);
            create index if not exists idx_billing_subscriptions_provider_subscription
              on billing_subscriptions(provider, provider_subscription_id);
            create index if not exists idx_billing_webhook_events_company_created
              on billing_webhook_events(company_id, created_at);
            create index if not exists idx_billing_orders_company_created
              on billing_orders(company_id, created_at);
            create index if not exists idx_billing_orders_company_status_updated
              on billing_orders(company_id, status, updated_at);
            create index if not exists idx_billing_orders_provider_order
              on billing_orders(provider, provider_order_id);
            create unique index if not exists idx_billing_orders_provider_transaction_unique
              on billing_orders(provider, provider_order_id)
              where provider_order_id is not null;
            create index if not exists idx_media_credit_ledger_company_created
              on media_credit_ledger(company_id, created_at);
            create index if not exists idx_media_credit_ledger_company_reference
              on media_credit_ledger(company_id, reference_type, reference_id, created_at);
            create index if not exists idx_platform_analytics_events_time_event
              on platform_analytics_events(occurred_at, event_key);
            create index if not exists idx_platform_analytics_events_visitor_time
              on platform_analytics_events(visitor_hash, occurred_at);
            create index if not exists idx_model_usage_ledger_owner_created
              on model_usage_ledger(usage_owner, created_at);
            create index if not exists idx_model_usage_ledger_company_created
              on model_usage_ledger(company_id, created_at);
            create index if not exists idx_provider_cost_ledger_category_created
              on provider_cost_ledger(cost_category, created_at);
            create index if not exists idx_provider_cost_ledger_company_created
              on provider_cost_ledger(company_id, created_at);
            create index if not exists idx_platform_reliability_alert_state_status_updated
              on platform_reliability_alert_state(lifecycle_status, updated_at);
            create index if not exists idx_platform_reliability_alert_events_scope_created
              on platform_reliability_alert_events(alert_scope, created_at);
            create index if not exists idx_platform_reliability_alert_events_transition_created
              on platform_reliability_alert_events(transition_key, created_at);
            create index if not exists idx_platform_provider_monitor_state_lease_expiry
              on platform_provider_monitor_state(lease_expires_at_epoch);
            create index if not exists idx_ebay_account_deletion_events_status_updated
              on ebay_account_deletion_events(status, updated_at);
            create index if not exists idx_api_rate_limit_buckets_scope_expiry
              on api_rate_limit_buckets(scope, expires_epoch);
            """
        )

    @staticmethod
    def _ensure_user_account_classification(conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("pragma table_info(users)").fetchall()}
        if "account_classification" not in columns:
            conn.execute(
                "alter table users add column account_classification text not null default 'merchant'"
            )
        placeholders = ", ".join("?" for _ in _SYNTHETIC_ACCOUNT_DOMAINS)
        conn.execute(
            f"""
            update users
            set account_classification = ?
            where lower(substr(email, instr(email, '@') + 1)) in ({placeholders})
            """,
            (
                ACCOUNT_CLASSIFICATION_SYNTHETIC_TEST,
                *sorted(_SYNTHETIC_ACCOUNT_DOMAINS),
            ),
        )

    @staticmethod
    def _ensure_ai_ceo_chat_merge_score_column(conn: sqlite3.Connection) -> None:
        columns = {str(row["name"]) for row in conn.execute("pragma table_info(ai_ceo_chat_turns)").fetchall()}
        if "merge_score" not in columns:
            conn.execute("alter table ai_ceo_chat_turns add column merge_score integer not null default 0")

    @staticmethod
    def _ensure_account_scoped_confirmations(conn: sqlite3.Connection) -> None:
        """Make store/task ownership optional for billing and other account controls."""

        columns = {str(row["name"]): row for row in conn.execute("pragma table_info(confirmations)").fetchall()}
        if not columns or "store_id" not in columns or "task_id" not in columns:
            return
        if int(columns["store_id"]["notnull"] or 0) == 0 and int(columns["task_id"]["notnull"] or 0) == 0:
            return
        conn.executescript(
            """
            alter table confirmations rename to confirmations_store_scoped_legacy;
            create table confirmations (
              confirmation_id text primary key,
              company_id text not null,
              store_id text,
              task_id text,
              runtime_run_id text not null,
              action_type text not null,
              title text not null,
              status text not null,
              default_action text not null,
              created_at text not null,
              item_json text not null,
              decided_by text,
              decided_at text,
              decision_note text
            );
            insert into confirmations (
              confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status,
              default_action, created_at, item_json, decided_by, decided_at, decision_note
            )
            select
              confirmation_id, company_id, store_id, task_id, runtime_run_id, action_type, title, status,
              default_action, created_at, item_json, decided_by, decided_at, decision_note
            from confirmations_store_scoped_legacy;
            drop table confirmations_store_scoped_legacy;
            """
        )

    def _record_schema_migration(
        self,
        conn: sqlite3.Connection,
        *,
        migration_id: str,
        checksum: str,
        summary: str,
    ) -> None:
        conn.execute(
            """
            insert or ignore into schema_migrations (migration_id, applied_at, checksum, summary)
            values (?, ?, ?, ?)
            """,
            (migration_id, now_iso(), checksum, summary),
        )

    def _update_task_steps_from_runtime_results(
        self,
        conn: sqlite3.Connection,
        *,
        task: dict[str, Any],
        runtime_result: dict[str, Any],
    ) -> None:
        updated_at = now_iso()
        results = runtime_result.get("results") if isinstance(runtime_result.get("results"), list) else []
        by_type = {str(result.get("task_type") or ""): result for result in results if isinstance(result, dict)}
        rows = conn.execute(
            "select task_type from task_steps where task_id = ? and company_id = ?",
            (task["task_id"], task["company_id"]),
        ).fetchall()
        for row in rows:
            result = by_type.get(row["task_type"])
            if not result:
                continue
            runtime_status = str(result.get("status") or "")
            step_status = step_status_from_runtime(runtime_status)
            if step_status == "completed" and (
                row["task_type"] in {"confirmation.package", "owner.review"}
                or _runtime_step_needs_human_followup(result)
            ):
                step_status = "waiting"
            conn.execute(
                """
                update task_steps
                set status = ?, updated_at = ?, finished_at = ?, runtime_task_id = ?, last_error = ?, step_json = ?
                where task_id = ? and company_id = ? and task_type = ?
                """,
                (
                    step_status,
                    updated_at,
                    updated_at,
                    str(result.get("task_id") or ""),
                    _step_error_from_result(result),
                    json.dumps(
                        {
                            "runtime_status": runtime_status,
                            "summary": result.get("summary"),
                            "missing_inputs": len(result.get("missing_inputs", []) or []),
                            "risk_flags": len(result.get("risk_flags", []) or []),
                            "confirmation_items": len(result.get("confirmation_items", []) or []),
                            "source_records": len(result.get("source_records", []) or []),
                            "result_ref": result.get("task_id"),
                        },
                        ensure_ascii=False,
                    ),
                    task["task_id"],
                    task["company_id"],
                    row["task_type"],
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        if self.database_engine == "postgres":
            return connect_postgres_repository(self.database_url)  # type: ignore[return-value]
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _store_id_for_task(self, *, company_id: str, task_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("select store_id from tasks where company_id = ? and task_id = ?", (company_id, task_id)).fetchone()
        return row["store_id"] if row else None

    def _task_store_id(self, conn: sqlite3.Connection, task_id: str) -> str | None:
        row = conn.execute("select store_id from tasks where task_id = ?", (task_id,)).fetchone()
        return row["store_id"] if row else None

    def _task_user_id(self, conn: sqlite3.Connection, task_id: str) -> str | None:
        row = conn.execute("select user_id from tasks where task_id = ?", (task_id,)).fetchone()
        return row["user_id"] if row else None

    def _insert_merchant_memory(
        self,
        conn: sqlite3.Connection,
        *,
        company_id: str,
        store_id: str | None,
        memory_type: str,
        source_type: str,
        source_id: str,
        title: str,
        summary: str,
        importance: int,
        tags: list[str],
        memory: dict[str, Any],
        created_by: str | None,
    ) -> bool:
        updated_at = now_iso()
        existing = conn.execute(
            """
            select memory_id, created_at from merchant_memory
            where company_id = ? and source_type = ? and source_id = ? and memory_type = ?
            """,
            (company_id, source_type, source_id, memory_type),
        ).fetchone()
        safe_memory = _redact_secret_like(
            {
                **memory,
                "memory_type": memory_type,
                "source_type": source_type,
                "source_id": source_id,
                "permanent_merchant_memory": True,
                "secret_exposed": False,
            }
        )
        safe_tags = sorted({str(tag) for tag in tags if str(tag or "").strip()})
        if existing:
            conn.execute(
                """
                update merchant_memory
                set store_id = ?, title = ?, summary = ?, importance = ?, tags_json = ?, memory_json = ?,
                    created_by = ?, updated_at = ?
                where memory_id = ?
                """,
                (
                    store_id,
                    title[:220],
                    summary[:1200],
                    max(1, min(int(importance), 100)),
                    json.dumps(safe_tags, ensure_ascii=False),
                    json.dumps(safe_memory, ensure_ascii=False),
                    created_by,
                    updated_at,
                    existing["memory_id"],
                ),
            )
            return True
        memory_id = _id("memory")
        conn.execute(
            """
            insert into merchant_memory (
              memory_id, company_id, store_id, memory_type, source_type, source_id, title, summary,
              importance, tags_json, memory_json, created_by, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                company_id,
                store_id,
                memory_type,
                source_type,
                source_id,
                title[:220],
                summary[:1200],
                max(1, min(int(importance), 100)),
                json.dumps(safe_tags, ensure_ascii=False),
                json.dumps(safe_memory, ensure_ascii=False),
                created_by,
                updated_at,
                updated_at,
            ),
        )
        return True

    def _upsert_merchant_ceo_command(
        self,
        conn: sqlite3.Connection,
        *,
        company_id: str,
        store_id: str,
        user_id: str,
        command: dict[str, Any],
    ) -> None:
        command_id = str(command.get("id") or "").strip()
        if not command_id:
            return
        updated_at = now_iso()
        created_at = str(command.get("created_at") or updated_at)
        safe_command = _redact_secret_like(
            {
                **command,
                "command_id": command_id,
                "store_id": store_id,
                "memory_policy": _merchant_ceo_memory_policy(command),
                "secret_exposed": False,
            }
        )
        existing = conn.execute(
            "select command_id, created_at from merchant_ceo_commands where command_id = ?",
            (command_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                update merchant_ceo_commands
                set company_id = ?, store_id = ?, user_id = ?, status = ?, route = ?,
                    memory_policy = ?, updated_at = ?, command_json = ?
                where command_id = ?
                """,
                (
                    company_id,
                    store_id,
                    user_id,
                    str(command.get("status") or "ready")[:80],
                    str(command.get("route") or "general_chat")[:80],
                    _merchant_ceo_memory_policy(command),
                    updated_at,
                    json.dumps(safe_command, ensure_ascii=False, default=json_default),
                    command_id,
                ),
            )
            return
        conn.execute(
            """
            insert into merchant_ceo_commands (
              command_id, company_id, store_id, user_id, status, route, memory_policy,
              created_at, updated_at, command_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                command_id,
                company_id,
                store_id,
                user_id,
                str(command.get("status") or "ready")[:80],
                str(command.get("route") or "general_chat")[:80],
                _merchant_ceo_memory_policy(command),
                created_at,
                updated_at,
                json.dumps(safe_command, ensure_ascii=False, default=json_default),
            ),
        )

    def _insert_audit(
        self,
        conn: sqlite3.Connection,
        *,
        company_id: str,
        store_id: str | None,
        user_id: str | None,
        actor_type: str,
        action_type: str,
        target_type: str,
        target_id: str | None,
        summary: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        created_at = now_iso()
        record = {
            "audit_id": _id("audit"),
            "company_id": company_id,
            "store_id": store_id,
            "user_id": user_id,
            "actor_type": actor_type,
            "action_type": action_type,
            "target_type": target_type,
            "target_id": target_id,
            "summary": summary,
            "created_at": created_at,
            "details": _redact_secret_like(details),
        }
        conn.execute(
            """
            insert into audit_logs (
              audit_id, company_id, store_id, user_id, actor_type, action_type,
              target_type, target_id, summary, created_at, audit_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["audit_id"],
                company_id,
                store_id,
                user_id,
                actor_type,
                action_type,
                target_type,
                target_id,
                summary,
                created_at,
                json.dumps(record, ensure_ascii=False),
            ),
        )
        return record

    def _task_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "user_id": row["user_id"],
            "runtime_run_id": row["runtime_run_id"],
            "task_type": row["task_type"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "input": _load_json_field(row["input_json"]),
            "output": _load_json_field(row["output_json"]),
        }

    def _queue_job_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "task_id": row["task_id"],
            "company_id": row["company_id"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "job": _load_json_field(row["job_json"]),
        }

    def _media_asset_job_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _load_json_field(row["media_job_json"])
        if not isinstance(payload, dict):
            payload = {}
        return {
            "media_job_id": row["media_job_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "task_id": row["task_id"],
            "queue_job_id": row["queue_job_id"] or "",
            "provider_job_key": row["provider_job_key"],
            "status": row["status"],
            "idempotency_key": row["idempotency_key"],
            "retry_count": row["retry_count"],
            "error_reason": row["error_reason"] or "",
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "job": _redact_secret_like(payload),
            "asset_manifest": payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), list) else [],
            "asset_manifest_validation": payload.get("asset_manifest_validation") if isinstance(payload.get("asset_manifest_validation"), dict) else {},
            "asset_review": payload.get("asset_review") if isinstance(payload.get("asset_review"), dict) else {},
            "asset_version": payload.get("asset_version") if isinstance(payload.get("asset_version"), dict) else {},
            "merchant_review": payload.get("merchant_review") if isinstance(payload.get("merchant_review"), dict) else {},
            "cost_guard": payload.get("cost_guard") if isinstance(payload.get("cost_guard"), dict) else {},
            "production_gate": payload.get("production_gate") if isinstance(payload.get("production_gate"), dict) else {},
            "merchant_visible_states": payload.get("merchant_visible_states") if isinstance(payload.get("merchant_visible_states"), list) else [],
            "live_provider_called": bool(payload.get("live_provider_called")),
            "spend_now_allowed": bool((payload.get("cost_guard") or {}).get("spend_now_allowed")) if isinstance(payload.get("cost_guard"), dict) else False,
            "secret_exposed": False,
        }

    def _report_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id": row["report_id"],
            "task_id": row["task_id"],
            "runtime_run_id": row["runtime_run_id"],
            "report_type": row["report_type"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "report": _load_json_field(row["report_json"]),
        }

    def _task_step_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        step_json = _load_json_field(row["step_json"])
        return {
            "step_id": row["step_id"],
            "task_id": row["task_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "step_order": row["step_order"],
            "task_type": row["task_type"],
            "depends_on_task_type": row["depends_on_task_type"],
            "role_key": row["role_key"],
            "merchant_label": row["merchant_label"],
            "status": row["status"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "timeout_seconds": row["timeout_seconds"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "runtime_task_id": row["runtime_task_id"],
            "last_error": row["last_error"],
            "required_sections": step_json.get("required_sections", []),
            "provider_job_keys": step_json.get("provider_job_keys", []),
            "step": step_json,
        }

    def _confirmation_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "confirmation_id": row["confirmation_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "task_id": row["task_id"],
            "runtime_run_id": row["runtime_run_id"],
            "action_type": row["action_type"],
            "title": row["title"],
            "status": row["status"],
            "default_action": row["default_action"],
            "created_at": row["created_at"],
            "item": _load_json_field(row["item_json"]),
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
            "decision_note": row["decision_note"],
            "high_risk": row["action_type"] in HIGH_RISK_ACTIONS,
        }

    def _merchant_memory_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memory_id": row["memory_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "memory_type": row["memory_type"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": row["title"],
            "summary": row["summary"],
            "importance": row["importance"],
            "tags": _load_json_field(row["tags_json"]),
            "memory": _load_json_field(row["memory_json"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "secret_exposed": False,
        }

    def _merchant_ceo_command_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _load_json_field(row["command_json"])
        command = _normalize_merchant_ceo_command(payload if isinstance(payload, dict) else {}, store_id=row["store_id"])
        return {
            "command": command,
            "source_record": {
                "id": f"ceo-command-source-{command['id']}",
                "source_type": MERCHANT_CEO_COMMAND_SOURCE_TYPE,
                "title": f"AI CEO command: {command['title']}",
                "note": command.get("text") or "",
                "status": "merchant_command_recorded",
                "captured_at": command.get("created_at") or row["created_at"],
                "secret_exposed": False,
            },
            "merchant_ceo_command_record": {
                "command_id": row["command_id"],
                "company_id": row["company_id"],
                "store_id": row["store_id"],
                "user_id": row["user_id"],
                "status": row["status"],
                "route": row["route"],
                "memory_policy": row["memory_policy"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "secret_exposed": False,
            },
            "merchant_memory": None,
            "memory_policy": command.get("memory_policy") or row["memory_policy"],
            "merchant_memory_written": _merchant_ceo_memory_policy(command) != AI_CEO_TRANSIENT_MEMORY_POLICY,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }

    def _ai_ceo_chat_turn_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = _load_json_field(row["turn_json"])
        turn = _normalize_ai_ceo_chat_history_turn(
            payload if isinstance(payload, dict) else {},
            company_id=str(row["company_id"] or ""),
            user_id=str(row["user_id"] or ""),
        )
        if not turn:
            return {}
        turn["store_id"] = str(row["store_id"] or turn.get("store_id") or "")
        turn["created_at"] = str(row["created_at"] or turn.get("created_at") or "")
        turn["updated_at"] = str(row["updated_at"] or turn.get("updated_at") or "")
        turn["secret_exposed"] = False
        return turn

    def _connection_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "connection_id": row["connection_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "platform": row["platform"],
            "connection_type": row["connection_type"],
            "status": row["status"],
            "scopes": _load_json_field(row["scopes_json"]),
            "secret_ref": row["secret_ref"],
            "metadata": _public_connection_metadata(_load_json_field(row["metadata_json"])),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "secret_exposed": False,
        }

    def _secret_ref_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "secret_ref": row["secret_ref"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "provider": row["provider"],
            "purpose": row["purpose"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "metadata": _load_json_field(row["metadata_json"]),
            "secret_exposed": False,
        }

    def _billing_subscription_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "company_id": row["company_id"],
            "provider": row["provider"],
            "provider_customer_id": row["provider_customer_id"] or "",
            "provider_subscription_id": row["provider_subscription_id"] or "",
            "plan_key": row["plan_key"],
            "provider_plan_id": row["provider_plan_id"] or "",
            "status": row["status"],
            "entitlement_active": bool(row["entitlement_active"]),
            "payment_attention_required": bool(row["payment_attention_required"]),
            "updated_at": row["updated_at"],
            "subscription": _load_json_field(row["subscription_json"]),
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    def _media_credit_account_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        balance = int(row["balance_points"] or 0)
        reserved = int(row["reserved_points"] or 0)
        return {
            "balance_points": balance,
            "reserved_points": reserved,
            "available_points": max(0, balance - reserved),
            "lifetime_granted_points": int(row["lifetime_granted_points"] or 0),
            "lifetime_spent_points": int(row["lifetime_spent_points"] or 0),
            "updated_at": row["updated_at"],
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def _media_credit_ledger_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "ledger_id": row["ledger_id"],
            "operation_type": row["operation_type"],
            "points": int(row["points"] or 0),
            "status": row["status"],
            "reference_type": row["reference_type"],
            "reference_id": row["reference_id"],
            "reservation_id": row["reservation_id"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "provider_neutral": True,
            "secret_exposed": False,
        }

    def _domestic_billing_order_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        order = _load_json_field(row["order_json"])
        return {
            "order_id": row["order_id"],
            "company_id": row["company_id"],
            "user_id": row["user_id"],
            "provider": row["provider"],
            "provider_order_id": row["provider_order_id"] or "",
            "plan_key": row["plan_key"],
            "amount_minor": int(row["amount_minor"]),
            "currency": row["currency"],
            "duration_days": int(row["duration_days"]),
            "status": row["status"],
            "expires_at": row["expires_at"],
            "paid_at": row["paid_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "order": order if isinstance(order, dict) else {},
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    def _find_billing_company_id(
        self,
        *,
        provider: str,
        provider_customer_id: str,
        provider_subscription_id: str,
    ) -> str:
        if not provider:
            return ""
        clauses = ["provider = ?"]
        params: list[Any] = [provider]
        lookups = []
        if provider_subscription_id:
            lookups.append(("provider_subscription_id = ?", provider_subscription_id))
        if provider_customer_id:
            lookups.append(("provider_customer_id = ?", provider_customer_id))
        if not lookups:
            return ""
        clauses.append("(" + " or ".join(item[0] for item in lookups) + ")")
        params.extend(item[1] for item in lookups)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select company_id from billing_subscriptions
                where {' and '.join(clauses)}
                order by updated_at desc
                limit 1
                """,
                tuple(params),
            ).fetchone()
        return str(row["company_id"] or "") if row else ""

    def _team_member_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "company_id": row["company_id"],
            "user_id": row["user_id"],
            "email": row["email"],
            "role": row["role"],
            "status": row["status"],
            "created_at": row["created_at"],
            "permissions": permissions_for_role(row["role"]),
            "secret_exposed": False,
        }

    def _oauth_request_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "oauth_request_id": row["oauth_request_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "platform": row["platform"],
            "status": row["status"],
            "state_nonce": row["state_nonce"],
            "scopes": _load_json_field(row["scopes_json"]),
            "auth_url": row["auth_url"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "request": _load_json_field(row["request_json"]),
            "secret_exposed": False,
        }

    def _platform_data_packet_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "packet_id": row["packet_id"],
            "company_id": row["company_id"],
            "store_id": row["store_id"],
            "platform": row["platform"],
            "packet_type": row["packet_type"],
            "source_mode": row["source_mode"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "packet": _load_json_field(row["packet_json"]),
            "secret_exposed": False,
        }

    def _execution_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "execution_id": row["execution_id"],
            "confirmation_id": row["confirmation_id"],
            "task_id": row["task_id"],
            "action_type": row["action_type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "result": _load_json_field(row["result_json"]),
        }

    def _audit_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _load_json_field(row["audit_json"])


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _load_json_field(value: Any) -> Any:
    """Load JSON from SQLite text or return native Postgres JSONB values."""

    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    return json.loads(value)


def _public_connection_metadata(value: Any) -> dict[str, Any]:
    metadata = value if isinstance(value, dict) else {}
    hidden = {"ebay_user_id_hash", "ebay_username_hash", "ebay_eias_identity_hash"}
    return {key: item for key, item in metadata.items() if key not in hidden}


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _without_domestic_checkout_uri(value: dict[str, Any]) -> dict[str, Any]:
    """Remove a payable URI as soon as the order is no longer payable."""

    cleaned = dict(value or {})
    checkout = cleaned.get("checkout")
    if isinstance(checkout, dict):
        safe_checkout = dict(checkout)
        safe_checkout.pop("code_url", None)
        safe_checkout["payable_uri_removed"] = True
        cleaned["checkout"] = safe_checkout
    cleaned["payable_qr_created"] = False
    return cleaned


def _safe_idempotency_key(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._:-]+", "-", text)[:160].strip("-._:")
    if text:
        return text
    return f"media-{hashlib.sha256(now_iso().encode('utf-8')).hexdigest()[:24]}"


SAFE_SECRET_FLAG_KEYS = {
    "secret_exposed",
    "raw_secret_returned",
    "raw_secret_stored",
    "secret_value_stored",
    "runtime_gets_raw_secret",
    "frontend_gets_raw_secret",
    "access_token_present",
    "refresh_token_present",
    "token_values_returned_to_public_response",
    "access_token_returned_to_frontend",
    "refresh_token_returned_to_frontend",
    "access_token_returned_to_runtime",
    "refresh_token_returned_to_runtime",
    "access_token_stored_in_database",
    "refresh_token_stored_in_database",
    "access_token_ttl_seconds",
    "seller_refresh_credential_ttl_seconds",
    "token_exchange_http_status",
    "token_endpoint",
    "merchant_brings_own_key",
    "frontend_gets_model_api_key",
    "runtime_gets_model_api_key",
    "reports_get_model_api_key",
    "frontend_gets_raw_key_after_save",
    "raw_key_stored_in_database",
    "jiejing_stores_only_secret_ref",
    "secret_value_returned",
    "raw_provider_secret_stored",
    "payment_secret_persisted",
    "frontend_gets_payment_secret",
    "raw_provider_response_persisted",
}


def _redact_secret_like(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if lower in SAFE_SECRET_FLAG_KEYS:
                redacted[key] = _redact_secret_like(item)
            elif any(marker in lower for marker in ("secret", "token", "password", "api_key", "apikey", "refresh")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_secret_like(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secret_like(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value)
    return value


def _redact_secret_text(value: str) -> str:
    text = str(value or "")
    replacements = (
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[model_key_redacted]"),
        (r"\b(?:AIAK|AKID|ASIA)[A-Za-z0-9]{12,}\b", "[cloud_key_redacted]"),
        (r"\b[0-9a-f]{8}-[0-9a-f-]{27,}:[0-9a-f]{24,}\b", "[provider_key_redacted]"),
        (r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [redacted]"),
        (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[jwt_redacted]"),
        (
            r"\b(access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret)\s*[:=]\s*[^,\s;]+",
            r"\1=[redacted]",
        ),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _sanitize_merchant_ceo_text(value: Any, *, limit: int = 600) -> str:
    text = _redact_secret_text(str(value or "").strip())
    if not text:
        return ""
    return text[:limit]


def _scoped_ai_ceo_chat_turn_id(*, company_id: str, user_id: str, assistant_id: str) -> str:
    digest = hashlib.sha256(f"{company_id}|{user_id}|{assistant_id}".encode("utf-8")).hexdigest()[:32]
    return f"ceo_turn_{digest}"


def _normalize_ai_ceo_chat_history_turn(
    value: Any,
    *,
    company_id: str,
    user_id: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("pending") is True:
        return None
    user_text = _sanitize_merchant_ceo_text(value.get("user_text") or value.get("userText"), limit=900)
    assistant_text = _sanitize_merchant_ceo_text(value.get("assistant_text") or value.get("assistantText"), limit=6000)
    if not user_text and not assistant_text:
        return None
    raw_assistant_id = re.sub(r"[^A-Za-z0-9_-]", "", str(value.get("assistant_id") or value.get("assistantId") or ""))[:120]
    if not raw_assistant_id:
        seed = f"{value.get('created_at') or ''}|{user_text}|{assistant_text}"
        raw_assistant_id = f"turn-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"

    def clean_records(items: Any, *, record_type: str) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            if record_type == "source":
                cleaned.append(
                    {
                        "title": _sanitize_merchant_ceo_text(item.get("title") or item.get("domain"), limit=160),
                        "url": _sanitize_merchant_ceo_text(item.get("url"), limit=500),
                        "domain": _sanitize_merchant_ceo_text(item.get("domain"), limit=120),
                        "snippet": _sanitize_merchant_ceo_text(item.get("snippet"), limit=220),
                        "captured_at": str(item.get("captured_at") or "")[:80],
                        "source_type": _sanitize_merchant_ceo_text(item.get("source_type") or "live_public_search", limit=80),
                    }
                )
            elif record_type == "work":
                cleaned.append(
                    {
                        "title": _sanitize_merchant_ceo_text(item.get("title"), limit=120),
                        "summary": _sanitize_merchant_ceo_text(item.get("summary") or item.get("next_step"), limit=260),
                        "status": str(item.get("status") or "")[:60],
                        "work_record_type": str(item.get("work_record_type") or "")[:80],
                        "source_record_count": int(item.get("source_record_count") or 0),
                        "captured_at": str(item.get("captured_at") or "")[:80],
                    }
                )
            else:
                cleaned.append(
                    {
                        "title": _sanitize_merchant_ceo_text(item.get("title"), limit=120),
                        "summary": _sanitize_merchant_ceo_text(item.get("summary"), limit=260),
                        "status": str(item.get("status") or "")[:60],
                        "action_type": str(item.get("action_type") or "")[:80],
                        "is_actionable": bool(item.get("is_actionable")),
                        "requires_confirmation_center_before_execution": bool(
                            item.get("requires_confirmation_center_before_execution") or item.get("requires_confirmation_center")
                        ),
                        "real_write_allowed_without_confirmation": False,
                        "source_record_count": int(item.get("source_record_count") or 0),
                    }
                )
        return cleaned

    delivery = value.get("market_report_delivery") if isinstance(value.get("market_report_delivery"), dict) else {}
    normalized = {
        "assistant_id": raw_assistant_id,
        "store_id": re.sub(r"[^A-Za-z0-9_-]", "", str(value.get("store_id") or ""))[:120],
        "user_text": user_text,
        "assistant_text": assistant_text,
        "status": str(value.get("status") or "completed")[:80],
        "route": str(value.get("route") or "general_chat")[:80],
        "route_label": _sanitize_merchant_ceo_text(value.get("route_label"), limit=120),
        "memory_policy": str(value.get("memory_policy") or "")[:80],
        "long_term_memory": bool(value.get("long_term_memory")),
        "writes_merchant_rule": bool(value.get("writes_merchant_rule")),
        "decision_center_required": bool(value.get("decision_center_required")),
        "market_report_id": re.sub(r"[^A-Za-z0-9_-]", "", str(value.get("market_report_id") or ""))[:120],
        "market_report_delivery": {
            "report_id": re.sub(r"[^A-Za-z0-9_-]", "", str(delivery.get("report_id") or ""))[:120],
            "report_type": str(delivery.get("report_type") or "")[:80],
            "status": str(delivery.get("status") or "")[:80],
            "title": _sanitize_merchant_ceo_text(delivery.get("title"), limit=180),
            "product": _sanitize_merchant_ceo_text(delivery.get("product"), limit=120),
            "created_at": str(delivery.get("created_at") or "")[:80],
            "structured_report_saved": bool(delivery.get("structured_report_saved")),
            "listing_import_ready": bool(delivery.get("listing_import_ready")),
            "source_record_count": int(delivery.get("source_record_count") or 0),
            "requires_human_review_before_publish": True,
            "triggers_real_platform_write": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        if delivery
        else None,
        "blocked_by": [str(item)[:80] for item in value.get("blocked_by", [])[:8]] if isinstance(value.get("blocked_by"), list) else [],
        "source_records": clean_records(value.get("source_records"), record_type="source"),
        "work_records": clean_records(value.get("work_records"), record_type="work"),
        "confirmation_items": clean_records(value.get("confirmation_items"), record_type="confirmation"),
        "created_at": str(value.get("created_at") or now_iso())[:80],
        "updated_at": str(value.get("updated_at") or value.get("created_at") or "")[:80],
        "account_scope": "account",
        "cross_store": True,
        "raw_provider_secret_stored": False,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }
    return _redact_secret_like(normalized)


def _ai_ceo_chat_turn_merge_score(turn: Any) -> int:
    if not isinstance(turn, dict):
        return -1
    status = str(turn.get("status") or "")
    completion = 0 if turn.get("pending") is True or status in {"pending", "streaming"} else 100_000
    answer = min(30_000, len(str(turn.get("assistant_text") or "")) * 10)
    evidence = 0
    for key in ("source_records", "work_records", "confirmation_items"):
        records = turn.get(key) if isinstance(turn.get(key), list) else []
        evidence += len(records) * 250
    report = 5_000 if isinstance(turn.get("market_report_delivery"), dict) and turn["market_report_delivery"].get("report_id") else 0
    return completion + answer + evidence + report


def _looks_like_ai_ceo_market_research_turn(*, message: str, chat: dict[str, Any]) -> bool:
    answer = str(chat.get("answer") or "")
    route = str(chat.get("route") or "")
    status = str(chat.get("status") or "")
    combined = f"{message}\n{answer}\n{route}\n{chat.get('route_label') or ''}".lower()
    if status not in {
        "model_answered",
        "model_answered_non_live",
        "realtime_search_answered",
        "realtime_search_answered_without_model",
        "source_backed_market_report_draft",
        "market_report_recovery_draft",
    }:
        return False
    finance_only = any(
        marker in combined
        for marker in (
            "stock",
            "nasdaq",
            "nyse",
            "eps",
            "earnings",
            "美股",
            "股票",
            "股价",
            "财报",
            "营收",
            "利润指引",
        )
    ) and not any(marker in combined for marker in ("ebay", "listing", "sku", "商品", "产品", "选品", "货源", "上架", "刊登"))
    if finance_only:
        return False
    has_market_signal = any(
        marker in combined
        for marker in (
            "market research",
            "market report",
            "competitor",
            "keyword",
            "demand",
            "trend",
            "price band",
            "opportunity",
            "市场调研",
            "市场报告",
            "市场",
            "调研",
            "竞品",
            "热销",
            "趋势",
            "价格带",
            "需求",
        )
    )
    has_product_signal = any(
        marker in combined
        for marker in (
            "ebay",
            "listing",
            "sku",
            "item specific",
            "product",
            "supplier",
            "sourcing",
            "1688",
            "商品",
            "产品",
            "品类",
            "货源",
            "选品",
            "上架",
            "刊登",
            "标题",
            "主图",
            "类目",
        )
    )
    return bool(has_market_signal and has_product_signal and route in {"ebay_workflow", "external_realtime", "confirmation_required", ""})


def _is_invalid_ai_ceo_market_product_label(value: Any) -> bool:
    text = _sanitize_merchant_ceo_text(value, limit=120).strip(" -:：")
    if not text:
        return True
    compact = re.sub(r"\s+", " ", text).strip().lower()
    invalid_markers = (
        "ai ceo 市场调研",
        "ai ceo market",
        "市场调研",
        "市场报告",
        "market research",
        "market report",
        "listing package",
        "terapeak",
        "ebay terapeak",
        "ebay listing",
        "ebay us",
        "ebay 美国站",
        "这次调研",
        "本次调研",
        "待确认商品",
    )
    if compact in invalid_markers:
        return True
    if re.fullmatch(r"(?:商品|产品|品类|品|候选商品|候选品|方向|方案)\s*[一二三四五六七八九十\dA-Z]+", compact, flags=re.IGNORECASE):
        return True
    invalid_fragments = (
        "候选商品名称",
        "商品名称、推荐度",
        "名称、推荐度",
        "推荐度评分",
        "listing 草稿字段建议",
        "草稿字段建议",
        "字段建议",
        "风险和 listing",
        "风险和待补",
        "目标市场",
        "机会窗口",
        "竞争策略",
        "合规与物流",
        "数据缺口",
        "待补资料",
        "terapeak",
        "ebay 官方选品",
        "官方选品指引",
        "真实店铺数据",
    )
    if any(fragment in compact for fragment in invalid_fragments):
        return True
    if re.fullmatch(r"e?bay\s*(us|美国站)?", compact, flags=re.IGNORECASE):
        return True
    if len(text) > 70 and re.search(r"帮我|应该|卖什么|不知道|你觉得|市场调研|报告", text):
        return True
    return False


def _clean_ai_ceo_market_candidate_name(value: Any) -> str:
    text = _sanitize_merchant_ceo_text(value, limit=120)
    text = re.sub(r"^[#>*\-\d.)、\s]+", "", text).strip()
    text = re.sub(r"^(?:方向|方案|候选|推荐|建议)\s*[一二三四五六七八九十\dA-Z]*\s*[:：.)、-]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:产品名称|商品名称|候选商品名称|产品|品类|商品|名称|recommended product|suggested product|target product|product name|item name|name)\s*[:：-]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip(" -:：")
    if _is_invalid_ai_ceo_market_product_label(text):
        return ""
    return text[:90]


def _ai_ceo_market_candidate_score(raw_block: str, index: int) -> int:
    match = re.search(r"(?:评分|推荐度|score)\s*[:：]?\s*(\d{2,3})", raw_block, flags=re.IGNORECASE)
    if match:
        score = max(0, min(100, int(match.group(1))))
        return score
    return max(62, 88 - index * 5)


def _ai_ceo_market_product_candidates(*, message: str, answer: str) -> list[dict[str, Any]]:
    """Extract merchant-facing product cards from flexible AI CEO market reports."""

    clean_answer = _sanitize_merchant_ceo_text(answer, limit=5000)
    clean_message = _sanitize_merchant_ceo_text(message, limit=900)
    raw_lines = [line.strip() for line in clean_answer.replace("*", "").splitlines()]
    lines = [line for line in raw_lines if line and not re.fullmatch(r"[-_]{3,}", line)]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def nearby_reasons(start_index: int) -> list[str]:
        block = "\n".join(lines[start_index : start_index + 8])
        reasons: list[str] = []
        for line in lines[start_index + 1 : start_index + 8]:
            cleaned = re.sub(r"^[#>*\-\d.)、\s]+", "", line).strip()
            if not cleaned:
                continue
            if re.match(r"^(?:方向|方案|候选)\s*[一二三四五六七八九十\dA-Z]*\s*[:：.)、-]", cleaned):
                break
            if re.search(r"为什么|需求|市场|符合|轻小|不带电|差异|价格|风险|适合|卖点|利润|评分|推荐度", cleaned):
                reasons.append(_sanitize_merchant_ceo_text(cleaned, limit=160))
            if len(reasons) >= 3:
                break
        return reasons or [_sanitize_merchant_ceo_text(block, limit=160)]

    def plausible_name(name: str) -> str:
        cleaned = _clean_ai_ceo_market_candidate_name(name)
        if not cleaned:
            return ""
        generic_exact = {
            "\u4fbf\u643a",
            "\u6536\u7eb3",
            "\u7279\u5b9a\u573a\u666f\u4e13\u7528",
            "\u5c0f\u5de5\u5177",
            "\u5de5\u5177",
            "\u914d\u4ef6",
            "\u7528\u54c1",
            "\u793c\u54c1",
            "\u65b9\u5411",
            "\u54c1\u7c7b",
        }
        if cleaned.strip() in generic_exact:
            return ""
        if len(cleaned.strip()) <= 3 and not re.search(r"[A-Za-z0-9]", cleaned):
            return ""
        lower = cleaned.lower()
        reject_markers = (
            "codex",
            "store",
            "jiejing",
            "ai ceo",
            "listing",
            "market",
            "ebay",
            "\u5e02\u573a",
            "\u8c03\u7814",
            "\u62a5\u544a",
            "\u8f7b\u3001\u5c0f",
            "\u4e0d\u5e26\u7535",
            "\u5c0f\u4f17",
            "\u9700\u6c42",
            "\u5546\u54c1\u5361",
            "\u5019\u9009\u5546\u54c1",
            "\u5019\u9009\u54c1",
            "\u98ce\u9669",
            "\u5305\u88c5",
            "\u9700",
            "\u9700\u8981",
            "\u6210\u672c",
            "\u552e\u4ef7",
            "\u5229\u6da6",
            "\u7ade\u4e89",
            "\u5efa\u8bae",
            "\u540d\u79f0\u3001",
            "\u63a8\u8350\u5ea6",
            "\u5b57\u6bb5",
            "\u8349\u7a3f",
            "\u76ee\u6807\u5e02\u573a",
            "\u673a\u4f1a\u7a97\u53e3",
            "\u4f18\u5148",
            "\u907f\u514d",
            "\u5f3a\u8c03",
            "\u4f7f\u7528\u5b89\u5168",
        )
        if any(marker in lower for marker in reject_markers):
            return ""
        if len(cleaned) > 55 and re.search(r"[\u3002\uff1b;]", cleaned):
            return ""
        return cleaned

    def add_candidate(name: str, *, start_index: int = 0, block: str = "", source: str = "ai_ceo_market_report") -> None:
        cleaned = plausible_name(name)
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen or len(candidates) >= 5:
            return
        seen.add(key)
        score_block = block or "\n".join(lines[start_index : start_index + 8])
        candidates.append(
            {
                "candidate_id": f"candidate_{len(candidates) + 1}",
                "name": cleaned,
                "score": _ai_ceo_market_candidate_score(score_block, len(candidates)),
                "reasons": nearby_reasons(start_index) if lines else [_sanitize_merchant_ceo_text(score_block or clean_answer, limit=160)],
                "price_band": _extract_ai_ceo_price_band(score_block or clean_answer),
                "source": source,
                "selected": len(candidates) == 0,
                "missing_facts": ["SKU", "图片 URL", "采购成本", "重量尺寸", "eBay 类目", "店铺政策"],
                "ready_for_listing_draft": True,
            }
        )

    heading_patterns = (
        r"^(?:[-*•]\s*)?(?:#+\s*)?(?:\u5019\u9009\u5546\u54c1|\u5019\u9009\u54c1|\u5019\u9009)\s*[A-Z0-9\u4e00-\u9fff]*\s*[:\uff1a.)\u3001-]\s*(.+)$",
        r"^(?:[-*•]\s*)?(?:#+\s*)?(?:方向|方案|候选)\s*([一二三四五六七八九十\dA-Z]+)\s*[:：.)、-]\s*(.+)$",
        r"^(?:[-*•]\s*)?(?:#+\s*)?(?:推荐产品|建议产品|目标商品|推荐品类|建议品类|商品方向|具体商品|商品名称|产品名称|名称)\s*[:：-]\s*(.+)$",
        r"^(?:[-*•]\s*)?(?:#+\s*)?(?:recommended product|suggested product|target product|product name|item name)\s*[:：-]\s*(.+)$",
    )
    for index, line in enumerate(lines):
        name = ""
        for pattern in heading_patterns:
            match = re.search(pattern, line, flags=re.IGNORECASE)
            if not match:
                continue
            name = plausible_name(match.group(match.lastindex or 1))
            break
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        block = "\n".join(lines[index : index + 8])
        candidates.append(
            {
                "candidate_id": f"candidate_{len(candidates) + 1}",
                "name": name,
                "score": _ai_ceo_market_candidate_score(block, len(candidates)),
                "reasons": nearby_reasons(index),
                "price_band": _extract_ai_ceo_price_band(block),
                "source": "ai_ceo_market_report",
                "selected": len(candidates) == 0,
                "missing_facts": ["SKU", "图片 URL", "采购成本", "重量尺寸", "eBay 类目", "店铺政策"],
                "ready_for_listing_draft": True,
            }
        )
        if len(candidates) >= 5:
            break

    if not candidates:
        label_value_pattern = re.compile(
            r"^(?:[-*•]\s*)?(?:#+\s*)?(?:商品名称|产品名称|候选商品名称|名称|具体商品|推荐产品|建议产品|目标商品|推荐品类|建议品类|商品方向|product name|item name)\s*[:：-]\s*(.+)$",
            flags=re.IGNORECASE,
        )
        for index, line in enumerate(lines):
            match = label_value_pattern.search(line)
            if not match:
                continue
            block = "\n".join(lines[max(0, index - 2) : index + 8])
            if not re.search(r"推荐度|评分|需求|风险|Listing\s*草稿|字段建议|score|demand|risk|price", block, flags=re.IGNORECASE):
                continue
            add_candidate(match.group(1), start_index=index, block=block, source="ai_ceo_market_report_labeled_value")
            if len(candidates) >= 5:
                break

    if not candidates:
        numbered_heading_pattern = re.compile(r"^(?:[-*•]\s*)?(?:#+\s*)?(?:top\s*)?(?:\d+|[一二三四五六七八九十])\s*[.)、:：]\s*(.+)$", flags=re.IGNORECASE)
        for index, line in enumerate(lines):
            match = numbered_heading_pattern.search(line)
            if not match:
                continue
            block = "\n".join(lines[index : index + 8])
            if not re.search(
                r"推荐度|评分|为什么有需求|为什么适合|Listing\s*草稿|字段建议|score|demand|risk|price",
                block,
                flags=re.IGNORECASE,
            ):
                continue
            add_candidate(match.group(1), start_index=index, block=block, source="ai_ceo_market_report_numbered_card")
            if len(candidates) >= 5:
                break

    if not candidates:
        table_header_index = -1
        for index, line in enumerate(lines):
            if line.startswith("|") and re.search(r"商品|产品|品类|名称|product", line, flags=re.IGNORECASE) and re.search(r"推荐|评分|score|risk|风险", line, flags=re.IGNORECASE):
                table_header_index = index
                continue
            if table_header_index < 0 or index <= table_header_index:
                continue
            if not line.startswith("|") or re.fullmatch(r"\|?\s*[-:|\s]+\|?", line):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            add_candidate(cells[0], start_index=max(0, table_header_index), block="\n".join(lines[table_header_index : index + 2]), source="ai_ceo_market_report_table")
            if len(candidates) >= 5:
                break

    if not candidates:
        vertical_table_label_pattern = re.compile(
            r"^(?:候选商品|候选品|推荐商品|推荐产品|建议商品|建议产品|具体商品|商品名称|产品名称|product|candidate)\s*[\d一二三四五六七八九十A-Z]*$",
            flags=re.IGNORECASE,
        )
        for index, line in enumerate(lines):
            if not line.startswith("|") or re.fullmatch(r"\|?\s*[-:|\s]+\|?", line):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            label = re.sub(r"[:：\s]+$", "", cells[0]).strip()
            value = cells[1].strip()
            if not vertical_table_label_pattern.search(label):
                continue
            block_lines = []
            for block_line in lines[index : index + 10]:
                if block_line.startswith("|") and not re.fullmatch(r"\|?\s*[-:|\s]+\|?", block_line):
                    block_cells = [cell.strip() for cell in block_line.strip("|").split("|")]
                    if (
                        block_lines
                        and len(block_cells) >= 2
                        and vertical_table_label_pattern.search(re.sub(r"[:：\s]+$", "", block_cells[0]).strip())
                    ):
                        break
                block_lines.append(block_line)
            add_candidate(value, start_index=index, block="\n".join(block_lines), source="ai_ceo_market_report_vertical_table")
            if len(candidates) >= 5:
                break

    if not candidates:
        context_pattern = re.compile(
            r"(?:"
            r"\u8bc6\u522b\u51fa|\u9501\u5b9a|\u53d1\u73b0|\u63a8\u8350|\u5efa\u8bae|\u4f18\u5148\u6d4b\u8bd5|\u4f18\u5148\u5207\u5165|"
            r"identified|recommend|suggest|prioritize"
            r")[^\n\u3002\uff1b;]{0,220}",
            flags=re.IGNORECASE,
        )
        for context in context_pattern.findall(clean_answer):
            for quoted in re.findall(r"[\u201c\u201d\"']([^\"\u201c\u201d']{2,70})[\u201c\u201d\"']", context):
                add_candidate(quoted, block=context, source="ai_ceo_market_report_narrative")
            if len(candidates) >= 5:
                break

    if not candidates:
        for index, line in enumerate(lines):
            stripped = re.sub(r"^[#>\-\s]+", "", line).strip(" *-:：")
            if not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9 /()（）&+\-]{3,60}", stripped):
                continue
            block = "\n".join(lines[index : index + 8])
            if not re.search(
                r"\u9700\u6c42|\u7ade\u4e89|\u4f18\u52bf|\u98ce\u9669|\u91c7\u8d2d|\u6210\u672c|\u552e\u4ef7|\u5229\u6da6|\u8f7b\u5c0f|\u4e0d\u5e26\u7535|demand|competition|risk|cost|margin",
                block,
                flags=re.IGNORECASE,
            ):
                continue
            add_candidate(stripped, start_index=index, block=block, source="ai_ceo_market_report_heading")

    if not candidates:
        fallback_patterns = (
            r"(?:建议产品|推荐产品|目标商品|商品方向|推荐品类|建议品类)\s*[:：]\s*([^\n。；;]{2,90})",
            r"(?:recommended product|suggested product|target product)\s*[:：]\s*([^\n.;]{2,90})",
        )
        combined = f"{clean_answer}\n{clean_message}".replace("*", "")
        for pattern in fallback_patterns:
            match = re.search(pattern, combined, flags=re.IGNORECASE)
            if not match:
                continue
            name = _clean_ai_ceo_market_candidate_name(match.group(1))
            if name:
                candidates.append(
                    {
                        "candidate_id": "candidate_1",
                        "name": name,
                        "score": 84,
                        "reasons": ["AI CEO 已把这个方向整理成可继续做 Listing 草稿的候选商品。"],
                        "price_band": _extract_ai_ceo_price_band(clean_answer),
                        "source": "ai_ceo_market_report",
                        "selected": True,
                        "missing_facts": ["SKU", "图片 URL", "采购成本", "重量尺寸", "eBay 类目", "店铺政策"],
                        "ready_for_listing_draft": True,
                    }
                )
                break
    return candidates


def _normalize_ai_ceo_candidate_match(value: Any) -> str:
    text = _sanitize_merchant_ceo_text(value, limit=240).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text)


def _ai_ceo_market_context_from_history(
    conversation_history: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(conversation_history, list):
        return [], {}
    for item in reversed(conversation_history[-8:]):
        if not isinstance(item, dict):
            continue
        previous_message = _sanitize_merchant_ceo_text(item.get("user_text") or item.get("user") or "", limit=900)
        previous_answer = _sanitize_merchant_ceo_text(item.get("assistant_text") or item.get("assistant") or "", limit=5000)
        if not previous_answer:
            continue
        candidates = _ai_ceo_market_product_candidates(message=previous_message, answer=previous_answer)
        if not candidates:
            continue
        selected = _select_ai_ceo_market_candidate(answer=previous_answer, candidates=candidates)
        return candidates, selected
    return [], {}


def _ai_ceo_followup_candidate_index(message: str) -> int | None:
    text = _sanitize_merchant_ceo_text(message, limit=220)
    match = re.search(r"(?:第|选|用|要|看)\s*([一二三四五1-5])\s*(?:个|项|款|种|候选)", text)
    if not match:
        return None
    number = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}.get(match.group(1), int(match.group(1)) if match.group(1).isdigit() else 0)
    return number - 1 if number > 0 else None


def _ai_ceo_should_inherit_market_context(message: str) -> bool:
    text = _sanitize_merchant_ceo_text(message, limit=300)
    if _ai_ceo_market_context_reset_requested(text):
        return False
    return bool(
        re.search(
            r"这个品|这个商品|这个产品|该商品|该产品|它(?:的|有|是|能|适合)|刚才(?:的|那个)|上面(?:的|那个)|继续(?:分析|调研|整理)|接着(?:分析|调研|整理)",
            text,
        )
    )


def _ai_ceo_market_context_reset_requested(message: str) -> bool:
    text = _sanitize_merchant_ceo_text(message, limit=300)
    return bool(re.search(r"换一个|换个|不要这个|这个不合适|重新选|重新推荐|另一个", text))


def _select_ai_ceo_market_candidate(*, answer: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the candidate explicitly recommended by the model, then by score."""

    if not candidates:
        return {}
    clean_answer = _sanitize_merchant_ceo_text(answer, limit=5000).replace("*", "")
    explicit_pattern = re.compile(
        r"(?:最值得(?:优先)?测试|最值得先测|最终推荐|首选推荐|首选|最佳候选|优先测试|"
        r"建议优先测试|建议先测试|推荐选择|选定商品|best\s+candidate|top\s+pick|final\s+recommendation)"
        r"\s*[:：-]?\s*([^\n]{0,180})",
        flags=re.IGNORECASE,
    )

    explicit_windows = [match.group(0) for match in explicit_pattern.finditer(clean_answer)]
    for window in explicit_windows:
        normalized_window = _normalize_ai_ceo_candidate_match(window)
        for candidate in candidates:
            name = _clean_ai_ceo_market_candidate_name(candidate.get("name"))
            primary_name = re.split(r"[（(]", name, maxsplit=1)[0].strip()
            normalized_name = _normalize_ai_ceo_candidate_match(name)
            normalized_primary = _normalize_ai_ceo_candidate_match(primary_name)
            if normalized_name and normalized_name in normalized_window:
                selected = candidate
                break
            if len(normalized_primary) >= 4 and normalized_primary in normalized_window:
                selected = candidate
                break
        else:
            continue
        break
    else:
        selected = max(
            candidates,
            key=lambda item: (int(item.get("score") or 0), -candidates.index(item)),
        )

    selected_id = str(selected.get("candidate_id") or "")
    for candidate in candidates:
        candidate["selected"] = str(candidate.get("candidate_id") or "") == selected_id
    return selected


def _ai_ceo_selected_candidate_context(
    *,
    answer: str,
    selected_candidate: dict[str, Any],
    product_candidates: list[dict[str, Any]],
) -> str:
    """Isolate one candidate card so Listing fields do not leak from another card."""

    clean_answer = _sanitize_merchant_ceo_text(answer, limit=5000)
    selected_name = _clean_ai_ceo_market_candidate_name(selected_candidate.get("name"))
    if not clean_answer or not selected_name:
        return clean_answer
    lower_answer = clean_answer.casefold()
    start_index = lower_answer.find(selected_name.casefold())
    if start_index < 0:
        primary_name = re.split(r"[（(]", selected_name, maxsplit=1)[0].strip()
        start_index = lower_answer.find(primary_name.casefold())
    if start_index < 0:
        return clean_answer

    end_index = len(clean_answer)
    for candidate in product_candidates:
        candidate_name = _clean_ai_ceo_market_candidate_name(candidate.get("name"))
        if not candidate_name or candidate_name == selected_name:
            continue
        candidate_index = lower_answer.find(candidate_name.casefold(), start_index + len(selected_name))
        if candidate_index >= 0:
            end_index = min(end_index, candidate_index)
    return clean_answer[start_index:end_index][:1800].strip() or clean_answer


def _infer_ai_ceo_market_product(*, message: str, answer: str, candidates: list[dict[str, Any]] | None = None) -> str:
    for candidate in candidates or []:
        name = _clean_ai_ceo_market_candidate_name(candidate.get("name"))
        if name:
            return name
    text = f"{answer}\n{message}".replace("*", "")
    patterns = [
        r"(?:建议产品|推荐产品|产品建议|推荐品类|建议品类|目标商品|商品方向|推荐商品)\s*[:：]\s*([^\n。；;]{2,90})",
        r"(?:recommended product|suggested product|target product)\s*[:：]\s*([^\n.;]{2,90})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            cleaned = _clean_ai_ceo_market_candidate_name(match.group(1))
            if cleaned:
                return cleaned
    message_match = re.search(r"(?:目标商品|推荐商品|建议产品|推荐产品|商品方向|我准备卖|我想卖)\s*[:：]\s*([^\n。；;]{2,80})", message, flags=re.IGNORECASE)
    if message_match:
        cleaned = _clean_ai_ceo_market_candidate_name(message_match.group(1))
        if cleaned:
            return cleaned
    generic = re.search(r"(eBay\s+[A-Za-z0-9 /_-]{3,70}|[A-Za-z0-9 /_-]{3,70}\s+(?:product|item|listing))", text, flags=re.IGNORECASE)
    if generic:
        cleaned = _clean_ai_ceo_market_candidate_name(generic.group(1))
        if cleaned:
            return cleaned
    return ""


def _ai_ceo_listing_handoff_fields(
    *,
    product: str,
    answer: str,
    source_records: list[dict[str, Any]],
    selected_candidate: dict[str, Any] | None = None,
    product_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_answer = _sanitize_merchant_ceo_text(answer, limit=5000)
    selected_candidate = selected_candidate if isinstance(selected_candidate, dict) else {}
    product_candidates = product_candidates if isinstance(product_candidates, list) else []
    clean_product = _clean_ai_ceo_market_candidate_name(product) or _clean_ai_ceo_market_candidate_name(selected_candidate.get("name")) or "待选择商品方向"
    selected_context = _ai_ceo_selected_candidate_context(
        answer=clean_answer,
        selected_candidate=selected_candidate,
        product_candidates=product_candidates,
    )
    lines = [
        _sanitize_merchant_ceo_text(re.sub(r"^[#*\-\d.\s:：]+", "", line).strip(), limit=220)
        for line in clean_answer.splitlines()
    ]
    lines = [line for line in lines if line]
    price_band = _sanitize_merchant_ceo_text(selected_candidate.get("price_band"), limit=90) or _extract_ai_ceo_price_band(selected_context)
    keyword_candidates = _extract_ai_ceo_keywords(selected_context, clean_product)
    risk_notes = [
        line
        for line in [
            _sanitize_merchant_ceo_text(re.sub(r"^[#*\-\d.\s:：]+", "", line).strip(), limit=220)
            for line in selected_context.splitlines()
            if line.strip()
        ]
        if re.search(r"risk|gap|warning|confirm|review|policy|publish|refund|ad|inventory|风险|缺口|确认|发布|退款|广告|库存|政策", line, flags=re.IGNORECASE)
    ][:6]
    candidate_reasons = [
        _sanitize_merchant_ceo_text(reason, limit=180)
        for reason in (selected_candidate.get("reasons") if isinstance(selected_candidate.get("reasons"), list) else [])
        if _sanitize_merchant_ceo_text(reason, limit=180)
    ][:4]
    market_rationale = candidate_reasons or [
        line
        for line in lines
        if len(line) >= 8
        and not re.search(r"risk|gap|warning|confirm|review|policy|publish|refund|ad|inventory|风险|缺口|确认|发布|退款|广告|库存|政策", line, flags=re.IGNORECASE)
        and not re.match(r"^(target marketplace|suggested product|recommended product|market|price|source|目标市场|建议产品|推荐产品|价格|来源)", line, flags=re.IGNORECASE)
    ][:6]
    item_specifics = _ai_ceo_item_specifics(product=clean_product, answer=selected_context)
    image_plan = _ai_ceo_image_plan(answer=selected_context)
    logistics_plan = _ai_ceo_logistics_plan(answer=selected_context)
    publish_gaps = _ai_ceo_listing_publish_gaps(
        item_specifics=item_specifics,
        price_band=price_band,
        image_plan=image_plan,
        logistics_plan=logistics_plan,
    )
    field_matrix = _ai_ceo_ebay_publish_field_matrix(
        product=clean_product,
        price_band=price_band,
        item_specifics=item_specifics,
        image_plan=image_plan,
        logistics_plan=logistics_plan,
    )
    merchant_required_answers = _ai_ceo_merchant_required_answers(field_matrix=field_matrix, publish_gaps=publish_gaps)
    ready_field_count = len([item for item in field_matrix if item.get("status") == "ready"])
    return {
        "contract_version": AI_CEO_MARKET_LISTING_HANDOFF_CONTRACT_VERSION,
        "ebay_listing_field_map_contract": AI_CEO_MARKET_EBAY_FIELD_MAP_CONTRACT,
        "title": clean_product,
        "product": clean_product,
        "product_candidates": product_candidates,
        "selected_product_candidate": selected_candidate,
        "selected_candidate_id": str(selected_candidate.get("candidate_id") or ""),
        "recommendation_score": int(selected_candidate.get("score") or 0) if selected_candidate else 0,
        # Market rationale is merchant-facing evidence, not buyer-facing copy.
        # Research must not silently become product claims before facts exist.
        "market_rationale": market_rationale,
        "selling_points": [],
        "buyer_copy_status": "waiting_for_merchant_product_facts",
        "keywords": keyword_candidates,
        "price_band": price_band,
        "category_suggestion": "待 eBay 类目体检确认",
        "condition": "",
        "condition_suggestion": "NEW",
        "quantity": "",
        "quantity_suggestion": "1",
        "item_specifics": item_specifics,
        "image_requirements": image_plan,
        "logistics_requirements": logistics_plan,
        "risk_notes": risk_notes,
        "description_seed": "",
        "ebay_inventory_item_draft": {
            "sku": "",
            "condition": "",
            "product": {
                "title": clean_product,
                "description": "",
                "aspects": item_specifics,
                "imageUrls": [],
            },
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": 0,
                },
            },
        },
        "ebay_offer_draft": {
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "categoryId": "",
            "merchantLocationKey": "",
            "pricingSummary": {
                "price": {
                    "value": "",
                    "currency": "USD",
                },
            },
            "research_price_band": price_band,
            "listingDescription": "",
            "listingPolicies": {
                "fulfillmentPolicyId": "",
                "paymentPolicyId": "",
                "returnPolicyId": "",
            },
        },
        "publish_preflight_required_fields": [
            "sku",
            "categoryId",
            "condition",
            "price.value",
            "quantity",
            "merchantLocationKey",
            "product.aspects",
            "product.imageUrls",
            "fulfillmentPolicyId",
            "paymentPolicyId",
            "returnPolicyId",
        ],
        "publish_preflight_gaps": publish_gaps,
        "merchant_required_answers": merchant_required_answers,
        "merchant_question_contract": {
            "contract_version": "2026-07-11-listing-missing-facts-v1",
            "questions": merchant_required_answers,
            "confirmed_values_only_in_publish_prefill": True,
            "suggestions_are_not_confirmed_facts": True,
            "real_platform_write_allowed": False,
            "secret_exposed": False,
        },
        "ebay_publish_field_matrix": field_matrix,
        "listing_readiness": {
            "ready_field_count": ready_field_count,
            "total_field_count": len(field_matrix),
            "missing_or_review_count": len(field_matrix) - ready_field_count,
            "ready_for_real_publish": False,
            "reason": "AI CEO 市场调研只生成 Listing 草稿字段包；真实发布前仍要补齐字段并进入确认中心。",
        },
        "source_record_count": len(source_records),
        "draft_source": "ai_ceo_market_research_report",
        "ready_for_listing_draft": True,
        "requires_human_review_before_publish": True,
        "triggers_real_platform_write": False,
        "secret_exposed": False,
    }


def _ai_ceo_item_specifics(*, product: str, answer: str) -> dict[str, str]:
    specifics: dict[str, str] = {
        "Brand": "待补",
        "Type": "待补",
        "Material": "待补",
        "MPN": "待补",
    }
    lower_product = product.lower()
    lower_answer = answer.lower()
    if "mosquito" in lower_product or "mosquito" in lower_answer or "驱蚊" in answer or "蚊" in answer:
        specifics["Type"] = "待商家确认：Mosquito Repeller"
    elif "jewelry" in lower_product or "jewelry" in lower_answer or "首饰" in answer:
        specifics["Type"] = "待商家确认：Jewelry Organizer"
    elif "case" in lower_product or "box" in lower_product or "盒" in answer:
        specifics["Type"] = "待商家确认：Storage Case"
    for key, label in (("Brand", "Brand|品牌"), ("Type", "Type|类型|品类"), ("MPN", "MPN|制造商零件编号")):
        match = re.search(rf"(?:{label})\s*[:：]\s*([A-Za-z0-9\u4e00-\u9fff /_.-]{{2,60}})", answer, flags=re.IGNORECASE)
        if match:
            specifics[key] = _sanitize_merchant_ceo_text(match.group(1), limit=60)
    material_match = re.search(r"(?:Material|材质)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fff /_-]{2,60})", answer, flags=re.IGNORECASE)
    if material_match:
        specifics["Material"] = _sanitize_merchant_ceo_text(material_match.group(1), limit=60)
    pack_match = re.search(r"(?:Pack(?:age)? Quantity|数量|件数|pack)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fff /_-]{1,40})", answer, flags=re.IGNORECASE)
    if pack_match:
        specifics["Pack Quantity"] = _sanitize_merchant_ceo_text(pack_match.group(1), limit=40)
    return specifics


def _ai_ceo_image_plan(*, answer: str) -> dict[str, Any]:
    urls = re.findall(r"https?://[^\s,，；;]+", answer)
    return {
        "imageUrls": urls[:12],
        "main_image": "白底主图，展示真实商品全貌；不可使用旧 demo 图片冒充真实素材。",
        "detail_images": [
            "尺寸/比例图",
            "材质和细节图",
            "包装和配件图",
            "使用场景图",
        ],
        "rights_check_required": True,
        "ebay_accessible_url_required": True,
    }


def _ai_ceo_logistics_plan(*, answer: str) -> dict[str, str]:
    weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|千克|g|克)\b", answer, flags=re.IGNORECASE)
    dimension_match = re.search(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*cm", answer, flags=re.IGNORECASE)
    ship_from_match = re.search(r"(?:ship from|item location|发货地)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fff /_-]{2,60})", answer, flags=re.IGNORECASE)
    return {
        "merchantLocationKey": "",
        "item_location": _sanitize_merchant_ceo_text(ship_from_match.group(1), limit=60) if ship_from_match else "",
        "package_weight_g": str(round(float(weight_match.group(1)) * (1000 if re.search(r"kg|千克", weight_match.group(2), flags=re.IGNORECASE) else 1))) if weight_match else "",
        "package_length_cm": _sanitize_merchant_ceo_text(dimension_match.group(1), limit=20) if dimension_match else "",
        "package_width_cm": _sanitize_merchant_ceo_text(dimension_match.group(2), limit=20) if dimension_match else "",
        "package_height_cm": _sanitize_merchant_ceo_text(dimension_match.group(3), limit=20) if dimension_match else "",
        "fulfillment_policy_id": "",
        "payment_policy_id": "",
        "return_policy_id": "",
    }


def _ai_ceo_listing_publish_gaps(
    *,
    item_specifics: dict[str, str],
    price_band: str,
    image_plan: dict[str, Any],
    logistics_plan: dict[str, str],
) -> list[str]:
    gaps = [
        "SKU 需要按当前商家账号生成或确认",
        "eBay 叶子类目 categoryId 需要发布体检确认",
        "库存位置 merchantLocationKey 需要来自店铺真实 location",
        "履约、付款、退货三个店铺政策需要来自 eBay 账号",
    ]
    if price_band:
        gaps.append("公开调研价格带只能作为参考；最终售价、采购成本、平台费和利润预留仍需确认")
    else:
        gaps.append("最终售价、采购成本、平台费和利润预留待补")
    if not image_plan.get("imageUrls"):
        gaps.append("图片 URL 和素材授权待补")
    if any(value in {"", "待补"} for value in item_specifics.values()):
        gaps.append("Item specifics 仍有待补字段")
    if not all(
        logistics_plan.get(key)
        for key in ("item_location", "package_weight_g", "package_length_cm", "package_width_cm", "package_height_cm")
    ):
        gaps.append("重量、尺寸或发货地待补")
    return gaps[:10]


def _ai_ceo_ebay_publish_field_matrix(
    *,
    product: str,
    price_band: str,
    item_specifics: dict[str, str],
    image_plan: dict[str, Any],
    logistics_plan: dict[str, str],
) -> list[dict[str, Any]]:
    """Map AI CEO research into merchant-readable eBay Inventory/Offer fields."""

    def has_value(value: Any) -> bool:
        text = str(value or "").strip()
        return bool(text) and text not in {"待补", "unknown", "todo"} and not text.startswith("待")

    def row(
        *,
        label: str,
        ebay_field: str,
        target_api: str,
        value: Any,
        source: str,
        question: str,
        status: str | None = None,
        blocks_publish: bool = True,
    ) -> dict[str, Any]:
        current_status = status or ("ready" if has_value(value) else "missing")
        return {
            "label": label,
            "ebay_field": ebay_field,
            "target_api": target_api,
            "status": current_status,
            "current_value": _sanitize_merchant_ceo_text(value, limit=180) if not isinstance(value, (dict, list)) else _redact_secret_like(value),
            "source": source,
            "merchant_question": question,
            "blocks_publish": bool(blocks_publish and current_status != "ready"),
        }

    missing_specifics = [key for key, value in item_specifics.items() if not has_value(value)]
    specifics_status = "ready" if not missing_specifics else "needs_review"
    image_urls = image_plan.get("imageUrls") if isinstance(image_plan.get("imageUrls"), list) else []
    logistics_ready = all(
        has_value(logistics_plan.get(key))
        for key in ("item_location", "package_weight_g", "package_length_cm", "package_width_cm", "package_height_cm")
    )
    return [
        row(
            label="商品标题",
            ebay_field="product.title",
            target_api="InventoryItem.product.title",
            value=product,
            source="AI CEO 市场调研",
            question="确认最终 eBay 标题，控制在平台标题长度内。",
            status="needs_review",
            blocks_publish=False,
        ),
        row(
            label="SKU",
            ebay_field="sku",
            target_api="InventoryItem.sku",
            value="",
            source="商家账号",
            question="给这个商品填一个当前账号内唯一 SKU。",
        ),
        row(
            label="eBay 类目",
            ebay_field="categoryId",
            target_api="Offer.categoryId",
            value="",
            source="eBay 类目体检",
            question="确认 eBay 叶子类目 categoryId。",
        ),
        row(
            label="商品状态",
            ebay_field="condition",
            target_api="InventoryItem.condition",
            value="",
            source="建议 NEW，等待商家确认",
            question="确认商品状态；如果确为全新商品，再选择 NEW。",
        ),
        row(
            label="Item specifics",
            ebay_field="product.aspects",
            target_api="InventoryItem.product.aspects",
            value=item_specifics,
            source="AI CEO 调研 + 商家事实",
            question="补齐 Brand、Type、Material、尺寸、颜色等 eBay 必填属性。",
            status=specifics_status,
        ),
        row(
            label="售价",
            ebay_field="pricingSummary.price.value",
            target_api="Offer.pricingSummary.price",
            value=price_band,
            source="公开市场调研",
            question="把价格带确认成一个可发布售价，并补采购成本和利润预留。",
            status="needs_review" if has_value(price_band) else "missing",
        ),
        row(
            label="可售数量",
            ebay_field="availability.shipToLocationAvailability.quantity",
            target_api="InventoryItem.availability",
            value="",
            source="建议首批从 1 件开始，等待商家确认",
            question="填写当前真实可售数量；不要用建议数量代替库存事实。",
        ),
        row(
            label="图片 URL",
            ebay_field="product.imageUrls",
            target_api="InventoryItem.product.imageUrls",
            value=image_urls,
            source="素材工坊 / 商家上传",
            question="提供 eBay 可访问的主图和细节图 URL，并确认商业使用权。",
            status="ready" if image_urls else "missing",
        ),
        row(
            label="库存位置",
            ebay_field="merchantLocationKey",
            target_api="Offer.merchantLocationKey",
            value=logistics_plan.get("merchantLocationKey", ""),
            source="eBay 店铺 location",
            question="从已连接店铺选择 merchantLocationKey。",
        ),
        row(
            label="包装和发货地",
            ebay_field="packageWeightAndSize",
            target_api="InventoryItem.packageWeightAndSize",
            value={
                "item_location": logistics_plan.get("item_location", ""),
                "package_weight_g": logistics_plan.get("package_weight_g", ""),
                "package_length_cm": logistics_plan.get("package_length_cm", ""),
                "package_width_cm": logistics_plan.get("package_width_cm", ""),
                "package_height_cm": logistics_plan.get("package_height_cm", ""),
            },
            source="商家物流资料",
            question="补发货地、包装重量和长宽高。",
            status="ready" if logistics_ready else "missing",
        ),
        row(
            label="店铺政策",
            ebay_field="listingPolicies",
            target_api="Offer.listingPolicies",
            value="",
            source="eBay business policies",
            question="选择履约、付款、退货三个店铺政策。",
        ),
    ]


def _ai_ceo_merchant_required_answers(*, field_matrix: list[dict[str, Any]], publish_gaps: list[str]) -> list[str]:
    answers: list[str] = []
    for item in field_matrix:
        if item.get("status") == "ready" and not item.get("blocks_publish"):
            continue
        question = _sanitize_merchant_ceo_text(item.get("merchant_question"), limit=160)
        if question:
            answers.append(question)
    for gap in publish_gaps:
        text = _sanitize_merchant_ceo_text(gap, limit=160)
        if text and text not in answers:
            answers.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for answer in answers:
        key = answer.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(answer)
    return deduped[:10]


def _extract_ai_ceo_price_band(text: str) -> str:
    patterns = [
        r"(?:US\s*)?\$\s*\d+(?:\.\d{1,2})?\s*(?:-|to|~|–|—)\s*(?:US\s*)?\$?\s*\d+(?:\.\d{1,2})?",
        r"US\s*\$?\s*\d+(?:\.\d{1,2})?\s*(?:-|to|~|–|—)\s*\$?\s*\d+(?:\.\d{1,2})?",
        r"\d+(?:\.\d{1,2})?\s*(?:USD|美元)\s*(?:-|to|~|–|—)\s*\d+(?:\.\d{1,2})?\s*(?:USD|美元)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _sanitize_merchant_ceo_text(match.group(0), limit=80)
    return ""


def _extract_ai_ceo_keywords(text: str, product: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (
        r"(?:keywords?|search terms?|关键词|搜索词)\s*[:：]\s*([^\n。；;]{3,220})",
        r"(?:eBay\s+keywords?|listing\s+keywords?)\s*[:：]\s*([^\n.；;]{3,220})",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidates.extend(re.split(r"[,，/、;；|]+", match.group(1)))
    if product:
        candidates.extend(re.split(r"\s+|/|、", product))
    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        value = _sanitize_merchant_ceo_text(item, limit=40).strip(" -_.,，、;；:：")
        if len(value) < 2:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized[:12]


def _normalize_merchant_ceo_routes(value: Any) -> list[dict[str, str]]:
    routes = value if isinstance(value, list) else []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in routes:
        if not isinstance(item, dict):
            continue
        view = _sanitize_merchant_ceo_text(item.get("view") or "product", limit=40) or "product"
        key = _sanitize_merchant_ceo_text(item.get("key") or view, limit=60) or view
        dedupe_key = f"{view}:{key}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "view": view,
                "key": key,
                "label": _sanitize_merchant_ceo_text(item.get("label") or view, limit=80),
                "note": _sanitize_merchant_ceo_text(item.get("note") or "", limit=220),
                "status": _sanitize_merchant_ceo_text(item.get("status") or "", limit=120),
            }
        )
    return normalized[:8]


def _normalize_merchant_ceo_command(command: dict[str, Any], *, store_id: str) -> dict[str, Any]:
    payload = command if isinstance(command, dict) else {}
    raw_id = _sanitize_merchant_ceo_text(payload.get("id") or payload.get("command_id") or "", limit=120)
    command_id = raw_id or _id("ceo_command")
    text = _sanitize_merchant_ceo_text(payload.get("text") or payload.get("command_text") or "")
    title = _sanitize_merchant_ceo_text(payload.get("title") or "AI CEO command", limit=120)
    summary = _sanitize_merchant_ceo_text(
        payload.get("summary") or "AI CEO accepted the merchant instruction and prepared module handoff.",
        limit=320,
    )
    route = _sanitize_merchant_ceo_text(payload.get("route") or _infer_merchant_ceo_route(payload, text), limit=80) or "general_chat"
    memory_policy = _sanitize_merchant_ceo_text(payload.get("memory_policy") or _infer_merchant_ceo_memory_policy(payload, route, text), limit=80)
    return _redact_secret_like(
        {
            "id": command_id,
            "text": text,
            "title": title,
            "summary": summary,
            "intent": _sanitize_merchant_ceo_text(payload.get("intent") or "listing", limit=40),
            "status": _sanitize_merchant_ceo_text(payload.get("status") or "ready", limit=40),
            "status_label": _sanitize_merchant_ceo_text(payload.get("status_label") or "accepted", limit=120),
            "created_at": _sanitize_merchant_ceo_text(payload.get("created_at") or now_iso(), limit=80),
            "store_id": store_id,
            "packet_id": _sanitize_merchant_ceo_text(payload.get("packet_id") or "", limit=120),
            "source_label": _sanitize_merchant_ceo_text(payload.get("source_label") or "", limit=120),
            "ai_reply": _sanitize_merchant_ceo_text(payload.get("ai_reply") or "", limit=2200),
            "ai_reply_status": _sanitize_merchant_ceo_text(payload.get("ai_reply_status") or "", limit=80),
            "ai_reply_model": _redact_secret_like(payload.get("ai_reply_model") if isinstance(payload.get("ai_reply_model"), dict) else {}),
            "route": route,
            "route_label": _sanitize_merchant_ceo_text(payload.get("route_label") or _route_label_for_merchant_ceo(route), limit=80),
            "memory_policy": memory_policy,
            "long_term_memory": bool(payload.get("long_term_memory")) or memory_policy != AI_CEO_TRANSIENT_MEMORY_POLICY,
            "writes_merchant_rule": bool(payload.get("writes_merchant_rule")) or memory_policy == AI_CEO_RULE_MEMORY_POLICY,
            "decision_center_required": bool(payload.get("decision_center_required")) or route == "confirmation_required",
            "high_risk": bool(payload.get("high_risk")),
            "routes": _normalize_merchant_ceo_routes(payload.get("routes")),
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
    )


def _infer_merchant_ceo_route(payload: dict[str, Any], text: str) -> str:
    if bool(payload.get("high_risk")):
        return "confirmation_required"
    lower = text.lower()
    if any(marker in lower for marker in ("记住这个规则", "记住这条规则", "以后都按这个做", "以后默认", "作为规则", "remember this rule")):
        return "merchant_rule_memory"
    if any(marker in lower for marker in ("股价", "实时新闻", "最新新闻", "汇率", "天气", "stock price", "latest news")):
        return "external_realtime"
    if any(
        marker in lower
        for marker in (
            "ebay",
            "listing",
            "sku",
            "market report",
            "listing package",
            "packet",
            "选品",
            "刊登",
            "上架资料",
            "素材",
            "客服",
            "订单",
            "发布体检",
            "决策中心",
            "确认中心",
        )
    ):
        return "ebay_workflow"
    return "general_chat"


def _infer_merchant_ceo_memory_policy(payload: dict[str, Any], route: str, text: str) -> str:
    if str(payload.get("memory_policy") or ""):
        return str(payload.get("memory_policy"))
    if route == "merchant_rule_memory":
        return AI_CEO_RULE_MEMORY_POLICY
    if route in {"ebay_workflow", "confirmation_required"} or bool(payload.get("high_risk")):
        return AI_CEO_OPERATING_MEMORY_POLICY
    return AI_CEO_TRANSIENT_MEMORY_POLICY


def _route_label_for_merchant_ceo(route: str) -> str:
    return {
        "general_chat": "直接回答",
        "ebay_workflow": "已进入经营任务",
        "external_realtime": "需要实时数据源",
        "confirmation_required": "等待确认",
        "merchant_rule_memory": "已记录规则",
    }.get(route, "直接回答")


def _merchant_ceo_memory_policy(command: dict[str, Any]) -> str:
    policy = str(command.get("memory_policy") or "").strip()
    if policy in {AI_CEO_TRANSIENT_MEMORY_POLICY, AI_CEO_OPERATING_MEMORY_POLICY, AI_CEO_RULE_MEMORY_POLICY}:
        return policy
    return _infer_merchant_ceo_memory_policy(command, str(command.get("route") or "general_chat"), str(command.get("text") or ""))


def _merchant_ceo_memory_type(command: dict[str, Any]) -> str:
    if _merchant_ceo_memory_policy(command) == AI_CEO_RULE_MEMORY_POLICY:
        return MERCHANT_RULE_MEMORY_TYPE
    return MERCHANT_CEO_COMMAND_MEMORY_TYPE


def _merchant_ceo_memory_importance(command: dict[str, Any]) -> int:
    policy = _merchant_ceo_memory_policy(command)
    if policy == AI_CEO_RULE_MEMORY_POLICY:
        return 86
    if command.get("decision_center_required") or command.get("high_risk"):
        return 90
    return 78


def _memory_summary_from_report(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return "Jiejing Runtime saved an AI work report for this merchant."
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    model_report = report.get("model_report") if isinstance(report.get("model_report"), dict) else {}
    for candidate in (
        payload.get("summary"),
        report.get("merchant_readable_summary"),
        model_report.get("merchant_readable_summary"),
        report.get("summary"),
        payload.get("task_type"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return "Jiejing Runtime saved an AI work report for this merchant."


def _memory_importance_from_report(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 60
    task_type = str(payload.get("task_type") or payload.get("report_type") or "")
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    model_assist = report.get("model_assist") if isinstance(report.get("model_assist"), dict) else {}
    if task_type in {"market.report", "listing.package"} and model_assist.get("status") == "applied":
        return 88
    if task_type in {"market.report", "listing.package"}:
        return 78
    if payload.get("confirmation_items"):
        return 72
    return 60


def _memory_summary_from_confirmation(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return "A confirmation-center item was saved and must stay under human control."
    title = str(item.get("title") or "").strip()
    action_type = str(item.get("action_type") or "action").strip()
    default_action = str(item.get("default_action") or "hold").strip()
    reason = str(item.get("reason") or item.get("summary") or "").strip()
    if reason:
        return f"{title or action_type}: {reason} Default action is {default_action} until the merchant decides."
    return f"{title or action_type} remains in the confirmation center. Default action is {default_action} until the merchant decides."


def _execution_idempotency(result: dict[str, Any]) -> dict[str, Any]:
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    idempotency = audit.get("idempotency") if isinstance(audit.get("idempotency"), dict) else {}
    return {
        "idempotency_key": idempotency.get("idempotency_key"),
        "duplicate_prevention_key": idempotency.get("duplicate_prevention_key"),
        "payload_hash": idempotency.get("payload_hash"),
    }


def _find_execution_duplicate(
    *,
    conn: sqlite3.Connection,
    confirmation_id: str,
    action_type: str,
    incoming_idempotency: dict[str, Any],
) -> dict[str, Any] | None:
    duplicate_key = incoming_idempotency.get("duplicate_prevention_key")
    if not duplicate_key:
        return None
    rows = conn.execute(
        """
        select execution_id, result_json
        from execution_results
        where confirmation_id = ? and action_type = ?
        order by created_at desc
        """,
        (confirmation_id, action_type),
    ).fetchall()
    for row in rows:
        try:
            existing_result = _load_json_field(row["result_json"])
        except json.JSONDecodeError:
            continue
        existing_idempotency = _execution_idempotency(existing_result)
        if existing_idempotency.get("duplicate_prevention_key") != duplicate_key:
            continue
        return {
            "execution_id": row["execution_id"],
            "idempotency_conflict": existing_idempotency.get("payload_hash") != incoming_idempotency.get("payload_hash"),
        }
    return None


def _billing_event_key(*, provider: str, event_id: str, event_type: str, fallback: str) -> str:
    safe_provider = re.sub(r"[^a-z0-9_:-]+", "_", str(provider or "billing").lower())
    if event_id:
        safe_event_id = re.sub(r"[^a-zA-Z0-9_:-]+", "_", event_id)
        return f"{safe_provider}:{safe_event_id}"
    digest = hashlib.sha256(f"{provider}:{event_type}:{fallback}".encode("utf-8")).hexdigest()[:16]
    return f"{safe_provider}:generated:{digest}"


def _billing_entitlement_apply_blockers(
    *,
    event: dict[str, Any],
    event_id: str,
    event_type: str,
    company_id: str,
    provider_customer_id: str,
    provider_subscription_id: str,
    provider_plan_id: str,
    plan_key: str,
    status: str,
    existing_subscription: dict[str, Any] | None,
) -> list[str]:
    blockers: list[str] = []
    if not company_id:
        blockers.append("company_id_not_resolved")
    if not event_type:
        blockers.append("billing_event_type_missing")
    if event.get("supported_event") is False:
        blockers.append("unsupported_billing_event")
    if not event_id:
        blockers.append("billing_event_id_missing")
    if not (provider_customer_id or provider_subscription_id):
        blockers.append("provider_subscription_or_customer_missing")
    supported_statuses = {"active", "trialing", "past_due", "unpaid", "canceled", "expired", "refunded", "disputed"}
    if status not in supported_statuses:
        blockers.append("subscription_status_unmapped")
    if not existing_subscription and (plan_key == "unknown" or not provider_plan_id):
        blockers.append("plan_key_not_resolved")
    return blockers


def _billing_unmapped_status(blockers: list[str]) -> str:
    if not blockers:
        return "accepted_for_entitlement"
    reason = re.sub(r"[^a-z0-9_]+", "_", str(blockers[0] or "unmapped").lower()).strip("_")
    return f"accepted_unmapped_{reason or 'unmapped'}"


def _billing_entitlement_status(value: str, *, event_type: str) -> str:
    text = str(value or "").strip().lower()
    event = str(event_type or "").strip().lower()
    if event.endswith(".deleted") or event.endswith(".canceled") or "cancelled" in event or "canceled" in event:
        return "canceled"
    if "expired" in event:
        return "expired"
    if "refunded" in event or "refund" in event:
        return "refunded"
    if "dispute" in event or "chargeback" in event:
        return "disputed"
    if "payment_failed" in event or "invoice.payment_failed" in event:
        return "past_due"
    if "invoice.paid" in event or "payment_succeeded" in event or "payment_success" in event or "transaction.completed" in event:
        return "active"
    if text in {"active", "trialing", "trial", "paid", "on_trial"}:
        return "trialing" if text in {"trial", "on_trial"} else "active"
    if text in {"past_due", "unpaid", "paused", "canceled", "cancelled", "expired", "deleted", "refunded", "disputed", "needs_response"}:
        if text == "needs_response":
            return "disputed"
        return "canceled" if text in {"cancelled", "deleted"} else text
    return text or "unknown"


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        select name
        from sqlite_master
        where type = 'table'
          and name not like 'sqlite_%'
        order by name
        """
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _step_error_from_result(result: dict[str, Any]) -> str | None:
    if not str(result.get("status") or "").startswith("failed"):
        return None
    issues = result.get("audit", {}).get("runtime_policy_issues") if isinstance(result.get("audit"), dict) else None
    if isinstance(issues, list) and issues:
        return str(issues[0].get("message") if isinstance(issues[0], dict) else issues[0])[:500]
    return str(result.get("summary") or "Runtime step failed.")[:500]


def _runtime_step_needs_human_followup(result: dict[str, Any]) -> bool:
    """Keep SaaS task steps visibly waiting when Runtime produced follow-up work."""
    for key in ("missing_inputs", "confirmation_items"):
        value = result.get(key)
        if isinstance(value, list) and value:
            return True
    for item in result.get("risk_flags") or []:
        if not isinstance(item, dict):
            return True
        severity = str(item.get("severity") or item.get("level") or "").lower()
        if severity in {"high", "critical", "blocker"}:
            return True
    return False
