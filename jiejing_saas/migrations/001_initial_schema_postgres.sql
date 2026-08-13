-- Jiejing SaaS initial PostgreSQL schema.
-- This is the production migration target for the local SQLite MVP schema.
-- It deliberately stores secret references only. Raw tokens, cookies, API keys,
-- passwords, refresh tokens and client secrets belong in Vault/KMS.

begin;

create table if not exists schema_migrations (
  migration_id text primary key,
  applied_at timestamptz not null default now(),
  checksum text not null,
  summary text not null
);

create table if not exists companies (
  company_id text primary key,
  name text not null,
  created_at timestamptz not null
);

create table if not exists users (
  user_id text primary key,
  email text not null unique,
  password_salt text not null,
  password_hash text not null,
  status text not null,
  default_company_id text not null references companies(company_id),
  account_classification text not null default 'merchant',
  created_at timestamptz not null
);

alter table users
  add column if not exists account_classification text not null default 'merchant';

update users
set account_classification = 'synthetic_test'
where lower(split_part(email, '@', 2)) in ('example.com', 'jiejing.local', 'local.invalid');

create table if not exists platform_trial_activations (
  company_id text primary key references companies(company_id),
  user_id text not null references users(user_id),
  status text not null,
  activated_at timestamptz,
  updated_at timestamptz not null,
  activation_json jsonb not null
);

create table if not exists user_sessions (
  jti text primary key,
  user_id text not null references users(user_id),
  company_id text not null,
  issued_at_epoch bigint not null,
  expires_epoch bigint not null,
  revoked_at timestamptz,
  created_at timestamptz not null
);

create table if not exists team_members (
  company_id text not null references companies(company_id),
  user_id text not null references users(user_id),
  role text not null check (role in ('owner', 'admin', 'operator', 'viewer')),
  created_at timestamptz not null,
  primary key (company_id, user_id)
);

create table if not exists team_invitations (
  invitation_id text primary key,
  company_id text not null references companies(company_id),
  email text not null,
  role text not null check (role in ('admin', 'operator', 'viewer')),
  status text not null,
  invited_by text not null references users(user_id),
  created_at timestamptz not null,
  accepted_at timestamptz,
  invite_json jsonb not null
);

create table if not exists stores (
  store_id text primary key,
  company_id text not null references companies(company_id),
  platform text not null,
  store_name text not null,
  marketplace text not null,
  stage text not null,
  created_by text not null references users(user_id),
  created_at timestamptz not null,
  store_json jsonb not null
);

create table if not exists merchant_onboarding_states (
  company_id text not null references companies(company_id),
  onboarding_key text not null,
  store_id text references stores(store_id),
  path_key text not null,
  current_step_key text not null,
  work_mode text not null,
  seller_returned boolean not null,
  answers_json jsonb not null,
  completed_step_keys_json jsonb not null,
  version bigint not null,
  updated_by_user_id text not null references users(user_id),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  primary key (company_id, onboarding_key)
);

create table if not exists merchant_product_feedback (
  feedback_id text primary key,
  company_id text not null references companies(company_id),
  user_id text not null references users(user_id),
  store_id text references stores(store_id),
  feedback_type text not null check (feedback_type = 'product_improvement'),
  module_key text not null,
  reason text not null check (reason in ('unclear', 'wrong_result', 'missing_action')),
  status text not null check (status in ('open', 'reviewing', 'resolved')),
  idempotency_key_hash text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  resolved_at timestamptz,
  feedback_json jsonb not null,
  unique (company_id, idempotency_key_hash)
);

create table if not exists secret_refs (
  secret_ref text primary key,
  company_id text not null references companies(company_id),
  store_id text references stores(store_id),
  provider text not null,
  purpose text not null,
  status text not null,
  created_by text not null references users(user_id),
  created_at timestamptz not null,
  metadata_json jsonb not null
);

create table if not exists platform_connections (
  connection_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  platform text not null,
  connection_type text not null,
  status text not null,
  scopes_json jsonb not null,
  secret_ref text references secret_refs(secret_ref),
  metadata_json jsonb not null,
  created_by text not null references users(user_id),
  created_at timestamptz not null
);

create table if not exists oauth_authorization_requests (
  oauth_request_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  platform text not null,
  status text not null,
  state_nonce text not null unique,
  scopes_json jsonb not null,
  auth_url text,
  created_by text not null references users(user_id),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  request_json jsonb not null
);

create table if not exists platform_data_packets (
  packet_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  platform text not null,
  packet_type text not null,
  source_mode text not null,
  status text not null,
  created_by text not null references users(user_id),
  created_at timestamptz not null,
  expires_at timestamptz,
  packet_json jsonb not null
);

create table if not exists tasks (
  task_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  user_id text not null references users(user_id),
  runtime_run_id text,
  task_type text not null,
  title text not null,
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  input_json jsonb not null,
  output_json jsonb not null
);

create table if not exists queue_jobs (
  job_id text primary key,
  task_id text not null references tasks(task_id),
  company_id text not null references companies(company_id),
  status text not null,
  attempts integer not null,
  max_attempts integer not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  job_json jsonb not null
);

create table if not exists media_asset_jobs (
  media_job_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  task_id text not null references tasks(task_id),
  queue_job_id text references queue_jobs(job_id),
  provider_job_key text not null,
  status text not null,
  idempotency_key text not null,
  retry_count integer not null,
  error_reason text,
  created_by text not null references users(user_id),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  media_job_json jsonb not null,
  unique (company_id, idempotency_key)
);

create table if not exists media_rework_reservations (
  reservation_key_hash text primary key,
  company_id text not null references companies(company_id),
  parent_media_job_id text not null,
  version integer not null,
  status text not null,
  media_job_id text,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  expires_epoch bigint not null,
  unique (company_id, parent_media_job_id, version)
);

create table if not exists api_rate_limit_buckets (
  bucket_key_hash text primary key,
  scope text not null,
  request_count integer not null,
  limit_count integer not null,
  window_started_epoch bigint not null,
  expires_epoch bigint not null
);

create table if not exists worker_runtime_heartbeats (
  worker_id text primary key,
  status text not null,
  queue_provider text not null,
  current_job_id text,
  heartbeat_at timestamptz not null,
  updated_at timestamptz not null,
  heartbeat_json jsonb not null
);

create table if not exists task_steps (
  step_id text primary key,
  task_id text not null references tasks(task_id),
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  step_order integer not null,
  task_type text not null,
  depends_on_task_type text,
  role_key text not null,
  merchant_label text not null,
  status text not null,
  attempts integer not null,
  max_attempts integer not null,
  timeout_seconds integer not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  started_at timestamptz,
  finished_at timestamptz,
  runtime_task_id text,
  last_error text,
  step_json jsonb not null,
  unique (task_id, task_type)
);

create table if not exists reports (
  report_id text primary key,
  task_id text not null references tasks(task_id),
  runtime_run_id text not null,
  report_type text not null,
  title text not null,
  status text not null,
  created_at timestamptz not null,
  report_json jsonb not null
);

create table if not exists confirmations (
  confirmation_id text primary key,
  company_id text not null references companies(company_id),
  store_id text references stores(store_id),
  task_id text references tasks(task_id),
  runtime_run_id text not null,
  action_type text not null,
  title text not null,
  status text not null,
  default_action text not null,
  created_at timestamptz not null,
  item_json jsonb not null,
  decided_by text references users(user_id),
  decided_at timestamptz,
  decision_note text
);

create table if not exists merchant_memory (
  memory_id text primary key,
  company_id text not null references companies(company_id),
  store_id text references stores(store_id),
  memory_type text not null,
  source_type text not null,
  source_id text not null,
  title text not null,
  summary text not null,
  importance integer not null,
  tags_json jsonb not null,
  memory_json jsonb not null,
  created_by text references users(user_id),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  unique (company_id, source_type, source_id, memory_type)
);

create table if not exists merchant_ceo_commands (
  command_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  user_id text references users(user_id),
  status text not null,
  route text not null,
  memory_policy text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  command_json jsonb not null
);

create table if not exists ai_ceo_chat_turns (
  chat_turn_id text primary key,
  company_id text not null references companies(company_id),
  user_id text not null references users(user_id),
  store_id text references stores(store_id),
  assistant_id text not null,
  status text not null,
  route text not null,
  merge_score integer not null default 0,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  turn_json jsonb not null,
  unique (company_id, user_id, assistant_id)
);

alter table ai_ceo_chat_turns add column if not exists merge_score integer not null default 0;

create table if not exists execution_results (
  execution_id text primary key,
  confirmation_id text not null references confirmations(confirmation_id),
  task_id text not null references tasks(task_id),
  action_type text not null,
  status text not null,
  created_at timestamptz not null,
  result_json jsonb not null
);

create table if not exists audit_logs (
  audit_id text primary key,
  company_id text not null references companies(company_id),
  store_id text references stores(store_id),
  user_id text references users(user_id),
  actor_type text not null,
  action_type text not null,
  target_type text not null,
  target_id text,
  summary text not null,
  created_at timestamptz not null,
  audit_json jsonb not null
);

create table if not exists billing_subscriptions (
  company_id text primary key references companies(company_id),
  provider text not null,
  provider_customer_id text,
  provider_subscription_id text,
  plan_key text not null,
  provider_plan_id text,
  status text not null,
  entitlement_active integer not null,
  payment_attention_required integer not null,
  updated_at timestamptz not null,
  subscription_json jsonb not null
);

create table if not exists billing_webhook_events (
  event_key text primary key,
  company_id text references companies(company_id),
  provider text not null,
  event_type text not null,
  status text not null,
  created_at timestamptz not null,
  billing_event_json jsonb not null
);

create table if not exists external_execution_claims (
  claim_id text primary key,
  company_id text not null references companies(company_id),
  store_id text not null references stores(store_id),
  confirmation_id text not null unique references confirmations(confirmation_id),
  action_type text not null,
  status text not null,
  nonce_sha256 text not null,
  binding_json jsonb not null,
  claimed_by text not null references users(user_id),
  claimed_at timestamptz not null,
  expires_at timestamptz not null,
  consumed_at timestamptz
);

alter table confirmations alter column store_id drop not null;
alter table confirmations alter column task_id drop not null;

create table if not exists billing_orders (
  order_id text primary key,
  company_id text not null references companies(company_id),
  user_id text not null references users(user_id),
  provider text not null,
  provider_order_id text,
  plan_key text not null,
  amount_minor integer not null,
  currency text not null,
  duration_days integer not null,
  status text not null,
  idempotency_key_hash text not null,
  expires_at timestamptz,
  paid_at timestamptz,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  order_json jsonb not null,
  unique (company_id, idempotency_key_hash)
);

create table if not exists media_credit_accounts (
  company_id text primary key references companies(company_id),
  balance_points integer not null,
  reserved_points integer not null,
  lifetime_granted_points integer not null,
  lifetime_spent_points integer not null,
  updated_at timestamptz not null,
  account_json jsonb not null
);

create table if not exists media_credit_ledger (
  ledger_id text primary key,
  company_id text not null references companies(company_id),
  user_id text references users(user_id),
  operation_type text not null,
  points integer not null,
  status text not null,
  reference_type text not null,
  reference_id text not null,
  reservation_id text,
  idempotency_key_hash text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  ledger_json jsonb not null,
  unique (company_id, idempotency_key_hash)
);

create table if not exists platform_analytics_events (
  analytics_event_id text primary key,
  event_id_hash text not null unique,
  company_id text references companies(company_id),
  user_id text references users(user_id),
  event_key text not null,
  page_key text not null,
  visitor_hash text,
  session_hash text,
  occurred_at timestamptz not null,
  analytics_json jsonb not null
);

create table if not exists model_usage_ledger (
  usage_id text primary key,
  company_id text not null references companies(company_id),
  user_id text references users(user_id),
  task_id text references tasks(task_id),
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
  created_at timestamptz not null,
  usage_json jsonb not null
);

create table if not exists provider_cost_ledger (
  cost_id text primary key,
  company_id text not null references companies(company_id),
  user_id text references users(user_id),
  task_id text references tasks(task_id),
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
  created_at timestamptz not null,
  cost_json jsonb not null
);

create table if not exists platform_reliability_alert_state (
  alert_scope text primary key,
  lifecycle_status text not null,
  severity text not null,
  observed_status text not null,
  consecutive_breach_count integer not null,
  consecutive_healthy_count integer not null,
  fingerprint text not null,
  opened_at timestamptz,
  recovered_at timestamptz,
  acknowledged_at timestamptz,
  acknowledged_by text,
  acknowledgement_action text,
  last_evaluated_at timestamptz not null,
  updated_at timestamptz not null,
  state_json jsonb not null
);

create table if not exists platform_reliability_alert_events (
  event_id text primary key,
  alert_scope text not null,
  transition_key text not null,
  severity text not null,
  fingerprint text not null,
  action_key text not null,
  actor_user_id text,
  created_at timestamptz not null,
  event_json jsonb not null,
  unique (alert_scope, transition_key, fingerprint, action_key)
);

create table if not exists platform_provider_monitor_state (
  scheduler_key text primary key,
  lease_owner_hash text not null,
  lease_expires_at_epoch bigint not null,
  last_evaluated_at timestamptz,
  last_exported_at timestamptz,
  last_outcome text not null,
  snapshot_json text not null,
  updated_at timestamptz not null
);

create table if not exists ebay_account_deletion_events (
  event_key text primary key,
  company_id text references companies(company_id),
  store_id text references stores(store_id),
  connection_id text references platform_connections(connection_id),
  task_id text references tasks(task_id),
  job_id text references queue_jobs(job_id),
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deletion_event_json jsonb not null
);

create index if not exists idx_team_members_company_role on team_members(company_id, role);
create index if not exists idx_user_sessions_user_expiry on user_sessions(user_id, expires_epoch);
create index if not exists idx_team_invitations_company_status_created on team_invitations(company_id, status, created_at);
create index if not exists idx_stores_company_platform_created on stores(company_id, platform, created_at);
create index if not exists idx_secret_refs_company_store_provider_purpose on secret_refs(company_id, store_id, provider, purpose);
create index if not exists idx_platform_connections_company_store_platform_status on platform_connections(company_id, store_id, platform, status);
create index if not exists idx_oauth_requests_company_store_status_updated on oauth_authorization_requests(company_id, store_id, status, updated_at);
create index if not exists idx_platform_data_packets_company_store_platform_created on platform_data_packets(company_id, store_id, platform, created_at);
create index if not exists idx_tasks_company_store_status_updated on tasks(company_id, store_id, status, updated_at);
create index if not exists idx_queue_jobs_company_status_updated on queue_jobs(company_id, status, updated_at);
create index if not exists idx_queue_jobs_task_status on queue_jobs(task_id, status);
create index if not exists idx_media_asset_jobs_company_store_status on media_asset_jobs(company_id, store_id, status, updated_at);
create index if not exists idx_media_asset_jobs_task_queue on media_asset_jobs(task_id, queue_job_id);
create index if not exists idx_media_rework_reservations_company_parent on media_rework_reservations(company_id, parent_media_job_id, version);
create index if not exists idx_api_rate_limit_buckets_scope_expiry on api_rate_limit_buckets(scope, expires_epoch);
create index if not exists idx_worker_runtime_heartbeats_updated on worker_runtime_heartbeats(heartbeat_at);
create index if not exists idx_task_steps_company_task_order on task_steps(company_id, task_id, step_order);
create index if not exists idx_reports_task_type_created on reports(task_id, report_type, created_at);
create index if not exists idx_confirmations_company_status_created on confirmations(company_id, status, created_at);
create index if not exists idx_confirmations_task_status on confirmations(task_id, status);
create index if not exists idx_merchant_memory_company_store_created on merchant_memory(company_id, store_id, created_at);
create index if not exists idx_merchant_memory_company_type_created on merchant_memory(company_id, memory_type, created_at);
create index if not exists idx_merchant_memory_source on merchant_memory(company_id, source_type, source_id);
create index if not exists idx_merchant_ceo_commands_company_store_updated on merchant_ceo_commands(company_id, store_id, updated_at);
create index if not exists idx_merchant_ceo_commands_company_route_updated on merchant_ceo_commands(company_id, route, updated_at);
create index if not exists idx_ai_ceo_chat_turns_account_created on ai_ceo_chat_turns(company_id, user_id, created_at);
create index if not exists idx_ai_ceo_chat_turns_account_store_created on ai_ceo_chat_turns(company_id, user_id, store_id, created_at);
create index if not exists idx_execution_results_task_created on execution_results(task_id, created_at);
create index if not exists idx_audit_logs_company_created on audit_logs(company_id, created_at);
create index if not exists idx_audit_logs_target on audit_logs(target_type, target_id, created_at);
create index if not exists idx_billing_subscriptions_provider_customer on billing_subscriptions(provider, provider_customer_id);
create index if not exists idx_billing_subscriptions_provider_subscription on billing_subscriptions(provider, provider_subscription_id);
create index if not exists idx_users_account_classification_created on users(account_classification, created_at);
create index if not exists idx_billing_webhook_events_company_created on billing_webhook_events(company_id, created_at);
create index if not exists idx_billing_orders_company_created on billing_orders(company_id, created_at);
create index if not exists idx_billing_orders_company_status_updated on billing_orders(company_id, status, updated_at);
create index if not exists idx_billing_orders_provider_order on billing_orders(provider, provider_order_id);
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
create index if not exists idx_ebay_account_deletion_events_status_updated on ebay_account_deletion_events(status, updated_at);
create index if not exists idx_platform_trial_activations_status_updated
  on platform_trial_activations(status, updated_at);
create index if not exists idx_merchant_onboarding_store_updated
  on merchant_onboarding_states(company_id, store_id, updated_at);
create index if not exists idx_merchant_product_feedback_company_created
  on merchant_product_feedback(company_id, created_at);
create index if not exists idx_merchant_product_feedback_status_updated
  on merchant_product_feedback(status, updated_at);

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260515_001_initial_schema_postgres',
  'jiejing-saas-postgres-schema-v20260515',
  'Initial production PostgreSQL schema for Jiejing SaaS backend.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260713_domestic_billing_orders',
  'jiejing-domestic-billing-orders-v20260713',
  'Adds tenant-scoped, idempotent domestic billing orders without payment credentials or bank details.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260714_media_credit_ledger',
  'jiejing-media-credit-ledger-v20260714',
  'Adds provider-neutral tenant media-point balances and an idempotent reserve, settle and release ledger.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260613_billing_subscription_state',
  'jiejing-billing-subscription-state-v20260613',
  'Adds paid billing subscription state and sanitized webhook event persistence.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260617_worker_runtime_heartbeats',
  'jiejing-worker-runtime-heartbeats-v20260617',
  'Adds durable worker heartbeat records for deep operational health.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260701_media_asset_jobs',
  'jiejing-media-asset-jobs-v20260701',
  'Adds provider-neutral media asset job records with idempotency, review and cost gate state.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260711_ai_ceo_account_chat_history',
  'jiejing-ai-ceo-account-chat-history-v20260711',
  'Adds account-scoped, cross-device AI CEO chat history without provider secrets or raw credentials.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260714_platform_operations_metering',
  'jiejing-platform-operations-metering-v20260714',
  'Adds privacy-safe traffic, provider-reported model usage and provider-neutral cost ledgers for the internal operator console.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260714_platform_reliability_alert_lifecycle',
  'jiejing-platform-reliability-alert-lifecycle-v20260714',
  'Adds provider-neutral alert confirmation, recovery, deduplication and internal handling history.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260715_platform_trial_activations',
  'jiejing-platform-trial-activations-v20260715',
  'Separates merchant registration from privacy-safe activation of Jiejing-funded AI and media trials.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260717_platform_provider_monitor_state',
  'jiejing-platform-provider-monitor-state-v20260717',
  'Adds an expiring singleton lease and privacy-safe passive provider monitoring evidence.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260802_merchant_onboarding_states',
  'jiejing-merchant-onboarding-states-v20260802',
  'Adds tenant-scoped enum-only merchant onboarding progress with optimistic concurrency.'
)
on conflict (migration_id) do nothing;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260803_merchant_product_feedback',
  'jiejing-merchant-product-feedback-v20260803',
  'Adds tenant-scoped, idempotent and auditable merchant product feedback.'
)
on conflict (migration_id) do nothing;

commit;
