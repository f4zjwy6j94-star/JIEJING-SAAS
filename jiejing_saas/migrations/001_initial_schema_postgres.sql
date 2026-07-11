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
  store_id text not null references stores(store_id),
  task_id text not null references tasks(task_id),
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
  created_at timestamptz not null,
  updated_at timestamptz not null,
  turn_json jsonb not null,
  unique (company_id, user_id, assistant_id)
);

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

create index if not exists idx_team_members_company_role on team_members(company_id, role);
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
create index if not exists idx_billing_webhook_events_company_created on billing_webhook_events(company_id, created_at);

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260515_001_initial_schema_postgres',
  'jiejing-saas-postgres-schema-v20260515',
  'Initial production PostgreSQL schema for Jiejing SaaS backend.'
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

commit;
