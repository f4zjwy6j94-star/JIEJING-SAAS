begin;

create table if not exists listing_draft_edit_heads (
  company_id text not null,
  store_id text not null,
  project_key text not null,
  source_report_id text not null,
  candidate_id text not null,
  revision integer not null check (revision >= 0),
  checkpoint_id text not null,
  updated_at timestamptz not null,
  primary key (company_id, store_id, project_key)
);

create table if not exists listing_draft_edit_revisions (
  checkpoint_id text not null primary key,
  company_id text not null,
  store_id text not null,
  project_key text not null,
  source_report_id text not null,
  candidate_id text not null,
  revision integer not null check (revision > 0),
  mutation_id text not null,
  payload_fingerprint text not null,
  base_report_id text not null,
  actor_user_id text not null,
  created_at timestamptz not null,
  receipt_json jsonb not null,
  unique (company_id, store_id, project_key, revision),
  unique (company_id, store_id, project_key, mutation_id)
);

-- The composite primary/unique keys already index every checkpoint lookup.
-- No forward FK: a revision-zero head is reserved only inside the save transaction.
do $$
begin
  if exists (
    with expected(table_name, column_name, udt_name, is_nullable) as (
      values
        ('listing_draft_edit_heads'::text, 'company_id'::text, 'text'::text, 'NO'::text),
        ('listing_draft_edit_heads', 'store_id', 'text', 'NO'),
        ('listing_draft_edit_heads', 'project_key', 'text', 'NO'),
        ('listing_draft_edit_heads', 'source_report_id', 'text', 'NO'),
        ('listing_draft_edit_heads', 'candidate_id', 'text', 'NO'),
        ('listing_draft_edit_heads', 'revision', 'int4', 'NO'),
        ('listing_draft_edit_heads', 'checkpoint_id', 'text', 'NO'),
        ('listing_draft_edit_heads', 'updated_at', 'timestamptz', 'NO'),
        ('listing_draft_edit_revisions', 'checkpoint_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'company_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'store_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'project_key', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'source_report_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'candidate_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'revision', 'int4', 'NO'),
        ('listing_draft_edit_revisions', 'mutation_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'payload_fingerprint', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'base_report_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'actor_user_id', 'text', 'NO'),
        ('listing_draft_edit_revisions', 'created_at', 'timestamptz', 'NO'),
        ('listing_draft_edit_revisions', 'receipt_json', 'jsonb', 'NO')
    )
    select 1 from expected
    where not exists (
      select 1 from information_schema.columns col
      where col.table_schema = 'public' and col.table_name = expected.table_name
        and col.column_name = expected.column_name and col.udt_name = expected.udt_name
        and col.is_nullable = expected.is_nullable
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if exists (
    with expected(table_name, constraint_type, columns) as (
      values
        ('listing_draft_edit_heads'::text, 'p'::text, array['company_id', 'store_id', 'project_key']::text[]),
        ('listing_draft_edit_revisions', 'p', array['checkpoint_id']::text[]),
        ('listing_draft_edit_revisions', 'u', array['company_id', 'store_id', 'project_key', 'revision']::text[]),
        ('listing_draft_edit_revisions', 'u', array['company_id', 'store_id', 'project_key', 'mutation_id']::text[])
    )
    select 1 from expected
    where not exists (
      select 1 from pg_constraint con
      join pg_class rel on rel.oid = con.conrelid
      join pg_namespace nsp on nsp.oid = rel.relnamespace
      where nsp.nspname = 'public' and rel.relname = expected.table_name
        and con.contype::text = expected.constraint_type and con.convalidated
        and (
          select array_agg(att.attname::text order by key_column.ordinality)
          from unnest(con.conkey) with ordinality as key_column(attnum, ordinality)
          join pg_attribute att on att.attrelid = con.conrelid and att.attnum = key_column.attnum
          where not att.attisdropped
        ) = expected.columns
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if exists (
    with expected(table_name, expression) as (
      values ('listing_draft_edit_heads'::text, 'checkrevision>=0'::text),
             ('listing_draft_edit_revisions', 'checkrevision>0')
    )
    select 1 from expected
    where not exists (
      select 1 from pg_constraint con
      join pg_class rel on rel.oid = con.conrelid
      join pg_namespace nsp on nsp.oid = rel.relnamespace
      where nsp.nspname = 'public' and rel.relname = expected.table_name
        and con.contype = 'c' and con.convalidated
        and regexp_replace(lower(pg_get_constraintdef(con.oid)), '[[:space:]()]', '', 'g') = expected.expression
    )
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260906_005_listing_draft_edit_checkpoints_postgres',
  'jiejing-listing-draft-edit-checkpoints-postgres-v20260906',
  'Add project-scoped Listing edit heads and immutable mutation-idempotent revisions without AI reports'
)
on conflict (migration_id) do nothing;

commit;
