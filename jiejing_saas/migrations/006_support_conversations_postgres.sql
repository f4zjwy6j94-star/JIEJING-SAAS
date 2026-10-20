-- Explicit support candidate only; production manifest/read/send remain unchanged.
-- Mirrors SupportConversations.schema_statements: JSON payloads stay TEXT.
begin;

create table if not exists support_messages_v1 (
  company_id text not null,
  store_id text not null,
  owner_id text not null,
  conversation_id text not null,
  message_id text not null,
  message_text text not null,
  created_at text not null,
  record_text text not null,
  primary key (company_id, store_id, owner_id, conversation_id, message_id)
);

create table if not exists support_sync_v1 (
  company_id text not null,
  store_id text not null,
  owner_id text not null,
  conversation_id text not null,
  sync_status text not null,
  attempted_at text not null,
  last_success_at text,
  truncated integer not null,
  current_message_ids_text text not null default '[]',
  current_message_hashes_text text not null default '{}',
  sync_generation integer not null default 0,
  primary key (company_id, store_id, owner_id, conversation_id)
);

create table if not exists support_drafts_v1 (
  company_id text not null,
  store_id text not null,
  owner_id text not null,
  draft_id text not null,
  revision integer not null,
  record_text text not null,
  primary key (company_id, store_id, owner_id, draft_id, revision)
);

create table if not exists support_send_intents_v1 (
  company_id text not null,
  store_id text not null,
  owner_id text not null,
  draft_id text not null,
  confirmation_id text not null,
  conversation_id text not null,
  source_message_id text not null,
  binding_hash text not null,
  status text not null,
  record_text text not null,
  primary key (company_id, store_id, owner_id, draft_id),
  unique (company_id, store_id, owner_id, confirmation_id),
  unique (company_id, store_id, owner_id, conversation_id, source_message_id)
);

create index if not exists idx_support_messages_scope_order
  on support_messages_v1 (company_id, store_id, owner_id, conversation_id, created_at, message_id);
create index if not exists idx_support_sync_scope_order
  on support_sync_v1 (company_id, store_id, owner_id, attempted_at desc, conversation_id);

-- IF NOT EXISTS is not schema verification: reject incompatible prior objects.
do $$
begin
  if exists (
    with expected(table_name, column_name, udt_name, is_nullable) as (
      values
        ('support_messages_v1'::text, 'company_id'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'store_id'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'owner_id'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'conversation_id'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'message_id'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'message_text'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'created_at'::text, 'text'::text, 'NO'::text),
        ('support_messages_v1'::text, 'record_text'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'company_id'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'store_id'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'owner_id'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'conversation_id'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'sync_status'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'attempted_at'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'last_success_at'::text, 'text'::text, 'YES'::text),
        ('support_sync_v1'::text, 'truncated'::text, 'int4'::text, 'NO'::text),
        ('support_sync_v1'::text, 'current_message_ids_text'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'current_message_hashes_text'::text, 'text'::text, 'NO'::text),
        ('support_sync_v1'::text, 'sync_generation'::text, 'int4'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'company_id'::text, 'text'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'store_id'::text, 'text'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'owner_id'::text, 'text'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'draft_id'::text, 'text'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'revision'::text, 'int4'::text, 'NO'::text),
        ('support_drafts_v1'::text, 'record_text'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'company_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'store_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'owner_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'draft_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'confirmation_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'conversation_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'source_message_id'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'binding_hash'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'status'::text, 'text'::text, 'NO'::text),
        ('support_send_intents_v1'::text, 'record_text'::text, 'text'::text, 'NO'::text)
    )
    select 1 from expected where not exists (
      select 1 from information_schema.columns col
      where col.table_schema = 'public' and col.table_name = expected.table_name
        and col.column_name = expected.column_name and col.udt_name = expected.udt_name
        and col.is_nullable = expected.is_nullable
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_support_schema_postcondition_failed';
  end if;

  if exists (
    with expected(table_name, kind, columns) as (
      values
        ('support_messages_v1'::text, 'p'::text, array['company_id', 'store_id', 'owner_id', 'conversation_id', 'message_id']::text[]),
        ('support_sync_v1'::text, 'p'::text, array['company_id', 'store_id', 'owner_id', 'conversation_id']::text[]),
        ('support_drafts_v1'::text, 'p'::text, array['company_id', 'store_id', 'owner_id', 'draft_id', 'revision']::text[]),
        ('support_send_intents_v1'::text, 'p'::text, array['company_id', 'store_id', 'owner_id', 'draft_id']::text[]),
        ('support_send_intents_v1'::text, 'u'::text, array['company_id', 'store_id', 'owner_id', 'confirmation_id']::text[]),
        ('support_send_intents_v1'::text, 'u'::text, array['company_id', 'store_id', 'owner_id', 'conversation_id', 'source_message_id']::text[])
    )
    select 1 from expected where not exists (
      select 1 from pg_constraint con
      join pg_class rel on rel.oid = con.conrelid
      join pg_namespace nsp on nsp.oid = rel.relnamespace
      join pg_index ix on ix.indexrelid = con.conindid
      where nsp.nspname = 'public' and rel.relname = expected.table_name
        and con.contype::text = expected.kind and con.convalidated
        and not con.condeferrable and ix.indisvalid and ix.indisready
        and (select array_agg(att.attname::text order by key_column.ordinality)
          from unnest(con.conkey) with ordinality as key_column(attnum, ordinality)
          join pg_attribute att on att.attrelid = con.conrelid
            and att.attnum = key_column.attnum and not att.attisdropped) = expected.columns
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_support_schema_postcondition_failed';
  end if;

  if not exists (
    select 1 from information_schema.columns where table_schema = 'public'
      and table_name = 'support_sync_v1' and column_name = 'current_message_ids_text'
      and column_default = '''[]''::text'
  ) or not exists (
    select 1 from information_schema.columns where table_schema = 'public'
      and table_name = 'support_sync_v1' and column_name = 'current_message_hashes_text'
      and column_default = '''{}''::text'
  ) or not exists (
    select 1 from information_schema.columns where table_schema = 'public'
      and table_name = 'support_sync_v1' and column_name = 'sync_generation'
      and column_default = '0'
  ) then
    raise exception using errcode = '23514', message = 'postgres_support_schema_postcondition_failed';
  end if;

  if exists (
    with expected(index_name, table_name, columns, desc_position) as (
      values
        ('idx_support_messages_scope_order'::text, 'support_messages_v1'::text,
         array['company_id', 'store_id', 'owner_id', 'conversation_id', 'created_at', 'message_id']::text[], -1),
        ('idx_support_sync_scope_order', 'support_sync_v1',
         array['company_id', 'store_id', 'owner_id', 'attempted_at', 'conversation_id']::text[], 3)
    )
    select 1 from expected where not exists (
      select 1 from pg_index ix
      join pg_class idx on idx.oid = ix.indexrelid
      join pg_class rel on rel.oid = ix.indrelid
      join pg_namespace nsp on nsp.oid = rel.relnamespace
      join pg_am am on am.oid = idx.relam
      where nsp.nspname = 'public' and idx.relname = expected.index_name
        and rel.relname = expected.table_name and am.amname = 'btree'
        and ix.indisvalid and ix.indisready and ix.indpred is null and ix.indexprs is null
        and ix.indnkeyatts = array_length(expected.columns, 1)
        and (select array_agg(att.attname::text order by key_column.ordinality)
          from unnest(ix.indkey) with ordinality as key_column(attnum, ordinality)
          join pg_attribute att on att.attrelid = ix.indrelid
            and att.attnum = key_column.attnum and not att.attisdropped) = expected.columns
        and not exists (select 1 from generate_series(0, ix.indnkeyatts - 1) pos
          where ((ix.indoption[pos]::int & 1) <> 0) <> (pos = expected.desc_position))
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_support_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20261012_006_support_conversations_postgres',
  'jiejing-support-conversations-postgres-v20261012',
  'Add scoped support snapshots, immutable draft revisions and once-only send intents; no message capability enabled'
)
on conflict (migration_id) do nothing;

commit;

