begin;

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

create table if not exists user_refresh_sessions (
  session_id text primary key,
  current_token_hash text not null unique,
  user_id text not null references users(user_id),
  company_id text not null references companies(company_id),
  device_class text not null,
  status text not null check (status in ('active', 'revoked', 'expired', 'replay_revoked')),
  created_at timestamptz not null,
  last_seen_at timestamptz not null,
  expires_epoch bigint not null,
  revoked_at timestamptz
);

create table if not exists user_refresh_token_history (
  token_hash text primary key,
  session_id text not null references user_refresh_sessions(session_id),
  generation bigint not null,
  status text not null check (status in ('active', 'rotated', 'expired', 'replay_revoked')),
  issued_at timestamptz not null,
  rotated_at timestamptz,
  replayed_at timestamptz,
  expires_epoch bigint not null,
  unique (session_id, generation)
);

alter table user_sessions
  add column if not exists refresh_session_id text;

create index if not exists idx_user_refresh_sessions_owner
  on user_refresh_sessions (user_id, company_id, status, last_seen_at);

create index if not exists idx_user_refresh_token_history_session
  on user_refresh_token_history (session_id, generation);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'user_sessions_refresh_session_id_fkey'
      and conrelid = 'user_sessions'::regclass
  ) then
    alter table user_sessions
      add constraint user_sessions_refresh_session_id_fkey
      foreign key (refresh_session_id) references user_refresh_sessions(session_id);
  end if;
end $$;

create index if not exists idx_user_sessions_refresh_session
  on user_sessions (refresh_session_id);

do $$
begin
  if exists (
    with expected(table_name, column_name, udt_name, is_nullable) as (
      values
        ('external_execution_claims'::text, 'claim_id'::text, 'text'::text, 'NO'::text),
        ('external_execution_claims', 'company_id', 'text', 'NO'),
        ('external_execution_claims', 'store_id', 'text', 'NO'),
        ('external_execution_claims', 'confirmation_id', 'text', 'NO'),
        ('external_execution_claims', 'action_type', 'text', 'NO'),
        ('external_execution_claims', 'status', 'text', 'NO'),
        ('external_execution_claims', 'nonce_sha256', 'text', 'NO'),
        ('external_execution_claims', 'binding_json', 'jsonb', 'NO'),
        ('external_execution_claims', 'claimed_by', 'text', 'NO'),
        ('external_execution_claims', 'claimed_at', 'timestamptz', 'NO'),
        ('external_execution_claims', 'expires_at', 'timestamptz', 'NO'),
        ('external_execution_claims', 'consumed_at', 'timestamptz', 'YES'),
        ('user_refresh_sessions', 'session_id', 'text', 'NO'),
        ('user_refresh_sessions', 'current_token_hash', 'text', 'NO'),
        ('user_refresh_sessions', 'user_id', 'text', 'NO'),
        ('user_refresh_sessions', 'company_id', 'text', 'NO'),
        ('user_refresh_sessions', 'device_class', 'text', 'NO'),
        ('user_refresh_sessions', 'status', 'text', 'NO'),
        ('user_refresh_sessions', 'created_at', 'timestamptz', 'NO'),
        ('user_refresh_sessions', 'last_seen_at', 'timestamptz', 'NO'),
        ('user_refresh_sessions', 'expires_epoch', 'int8', 'NO'),
        ('user_refresh_sessions', 'revoked_at', 'timestamptz', 'YES'),
        ('user_refresh_token_history', 'token_hash', 'text', 'NO'),
        ('user_refresh_token_history', 'session_id', 'text', 'NO'),
        ('user_refresh_token_history', 'generation', 'int8', 'NO'),
        ('user_refresh_token_history', 'status', 'text', 'NO'),
        ('user_refresh_token_history', 'issued_at', 'timestamptz', 'NO'),
        ('user_refresh_token_history', 'rotated_at', 'timestamptz', 'YES'),
        ('user_refresh_token_history', 'replayed_at', 'timestamptz', 'YES'),
        ('user_refresh_token_history', 'expires_epoch', 'int8', 'NO'),
        ('user_sessions', 'refresh_session_id', 'text', 'YES')
    )
    select 1
    from expected
    where not exists (
      select 1
      from information_schema.columns col
      where col.table_schema = 'public'
        and col.table_name = expected.table_name
        and col.column_name = expected.column_name
        and col.udt_name = expected.udt_name
        and col.is_nullable = expected.is_nullable
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if exists (
    with expected(index_name, table_name, column_names) as (
      values
        (
          'idx_user_refresh_sessions_owner'::text,
          'user_refresh_sessions'::text,
          array['user_id', 'company_id', 'status', 'last_seen_at']::text[]
        ),
        (
          'idx_user_refresh_token_history_session'::text,
          'user_refresh_token_history'::text,
          array['session_id', 'generation']::text[]
        ),
        (
          'idx_user_sessions_refresh_session'::text,
          'user_sessions'::text,
          array['refresh_session_id']::text[]
        )
    )
    select 1
    from expected
    where not exists (
      select 1
      from pg_index idx
      join pg_class idx_rel on idx_rel.oid = idx.indexrelid
      join pg_namespace idx_nsp on idx_nsp.oid = idx_rel.relnamespace
      join pg_class table_rel on table_rel.oid = idx.indrelid
      join pg_namespace table_nsp on table_nsp.oid = table_rel.relnamespace
      join pg_am am on am.oid = idx_rel.relam
      where idx_nsp.nspname = 'public'
        and table_nsp.nspname = 'public'
        and idx_rel.relname = expected.index_name
        and table_rel.relname = expected.table_name
        and am.amname = 'btree'
        and not idx.indisunique
        and idx.indisvalid
        and idx.indisready
        and idx.indnkeyatts = cardinality(expected.column_names)
        and idx.indnatts = cardinality(expected.column_names)
        and idx.indexprs is null
        and idx.indpred is null
        and (
          select array_agg(att.attname::text order by key_column.ordinality)
          from unnest(idx.indkey::smallint[]) with ordinality as key_column(attnum, ordinality)
          join pg_attribute att
            on att.attrelid = idx.indrelid
           and att.attnum = key_column.attnum
           and not att.attisdropped
        ) = expected.column_names
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if not exists (
    select 1
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'user_sessions'
      and con.conname = 'user_sessions_refresh_session_id_fkey'
      and con.contype = 'f'
      and con.convalidated
      and con.confrelid = 'public.user_refresh_sessions'::regclass
      and con.confmatchtype = 's'
      and con.confupdtype = 'a'
      and con.confdeltype = 'a'
      and con.conkey = array[
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.user_sessions'::regclass
            and attname = 'refresh_session_id'
            and not attisdropped
        )
      ]::smallint[]
      and con.confkey = array[
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.user_refresh_sessions'::regclass
            and attname = 'session_id'
            and not attisdropped
        )
      ]::smallint[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260823_003_runtime_schema_reconciliation_postgres',
  'jiejing-runtime-schema-reconciliation-postgres-v20260823',
  'Reconcile runtime execution claims and browser refresh-session schema on legacy databases'
)
on conflict (migration_id) do nothing;

commit;
