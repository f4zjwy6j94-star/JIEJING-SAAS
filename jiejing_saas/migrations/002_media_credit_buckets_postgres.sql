begin;

create table if not exists media_credit_buckets (
  bucket_id text primary key,
  company_id text not null references companies(company_id),
  source_type text not null,
  source_reference_id text not null,
  granted_points integer not null,
  remaining_points integer not null,
  reserved_points integer not null,
  expires_at timestamptz,
  status text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  bucket_json jsonb not null,
  unique (company_id, source_type, source_reference_id)
);

create index if not exists idx_media_credit_buckets_company_status
  on media_credit_buckets (company_id, status, expires_at);

do $$
begin
  if exists (
    with expected(column_name, udt_name, is_nullable) as (
      values
        ('bucket_id'::text, 'text'::text, 'NO'::text),
        ('company_id', 'text', 'NO'),
        ('source_type', 'text', 'NO'),
        ('source_reference_id', 'text', 'NO'),
        ('granted_points', 'int4', 'NO'),
        ('remaining_points', 'int4', 'NO'),
        ('reserved_points', 'int4', 'NO'),
        ('expires_at', 'timestamptz', 'YES'),
        ('status', 'text', 'NO'),
        ('created_at', 'timestamptz', 'NO'),
        ('updated_at', 'timestamptz', 'NO'),
        ('bucket_json', 'jsonb', 'NO')
    )
    select 1
    from expected
    where not exists (
      select 1
      from information_schema.columns col
      where col.table_schema = 'public'
        and col.table_name = 'media_credit_buckets'
        and col.column_name = expected.column_name
        and col.udt_name = expected.udt_name
        and col.is_nullable = expected.is_nullable
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
      and rel.relname = 'media_credit_buckets'
      and con.contype = 'f'
      and con.convalidated
      and con.confrelid = 'public.companies'::regclass
      and con.confmatchtype = 's'
      and con.confupdtype = 'a'
      and con.confdeltype = 'a'
      and con.conkey = array[
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.media_credit_buckets'::regclass
            and attname = 'company_id'
            and not attisdropped
        )
      ]::smallint[]
      and con.confkey = array[
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.companies'::regclass
            and attname = 'company_id'
            and not attisdropped
        )
      ]::smallint[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if not exists (
    select 1
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'media_credit_buckets'
      and con.contype = 'u'
      and con.convalidated
      and con.conkey = array[
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.media_credit_buckets'::regclass
            and attname = 'company_id'
            and not attisdropped
        ),
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.media_credit_buckets'::regclass
            and attname = 'source_type'
            and not attisdropped
        ),
        (
          select attnum
          from pg_attribute
          where attrelid = 'public.media_credit_buckets'::regclass
            and attname = 'source_reference_id'
            and not attisdropped
        )
      ]::smallint[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if not exists (
    select 1
    from pg_index idx
    join pg_class idx_rel on idx_rel.oid = idx.indexrelid
    join pg_namespace idx_nsp on idx_nsp.oid = idx_rel.relnamespace
    join pg_am am on am.oid = idx_rel.relam
    where idx_nsp.nspname = 'public'
      and idx_rel.relname = 'idx_media_credit_buckets_company_status'
      and idx.indrelid = 'public.media_credit_buckets'::regclass
      and am.amname = 'btree'
      and not idx.indisunique
      and idx.indisvalid
      and idx.indisready
      and idx.indnkeyatts = 3
      and idx.indnatts = 3
      and idx.indexprs is null
      and idx.indpred is null
      and (
        select array_agg(att.attname::text order by key_column.ordinality)
        from unnest(idx.indkey::smallint[]) with ordinality as key_column(attnum, ordinality)
        join pg_attribute att
          on att.attrelid = idx.indrelid
         and att.attnum = key_column.attnum
         and not att.attisdropped
      ) = array['company_id', 'status', 'expires_at']::text[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260823_002_media_credit_buckets_postgres',
  'jiejing-media-credit-buckets-postgres-v20260823',
  'Add expiring media-credit buckets with company-scoped idempotency'
)
on conflict (migration_id) do nothing;

commit;
