-- Additive authentication generations. Absence is the legacy generation zero.
-- Empty company_id is an account epoch; membership tombstones are never deleted
-- by membership removal/re-invitation. No existing sessions are rewritten.
begin;

create table if not exists access_revocation_epochs (
  user_id text not null,
  company_id text not null,
  generation bigint not null check (generation >= 0),
  primary key (user_id, company_id)
);

do $$
begin
  if exists (
    with expected(column_name, udt_name) as (
      values ('user_id'::text, 'text'::text), ('company_id', 'text'), ('generation', 'int8')
    )
    select 1 from expected where not exists (
      select 1 from information_schema.columns c where c.table_schema = 'public'
        and c.table_name = 'access_revocation_epochs' and c.column_name = expected.column_name
        and c.udt_name = expected.udt_name and c.is_nullable = 'NO'
    )
  ) or not exists (
    select 1 from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    join pg_index ix on ix.indexrelid = con.conindid
    where nsp.nspname = 'public' and rel.relname = 'access_revocation_epochs'
      and con.contype = 'p' and con.convalidated and not con.condeferrable
      and ix.indisvalid and ix.indisready
      and (select array_agg(att.attname::text order by key_column.ordinality)
        from unnest(con.conkey) with ordinality as key_column(attnum, ordinality)
        join pg_attribute att on att.attrelid = con.conrelid and att.attnum = key_column.attnum
          and not att.attisdropped) = array['user_id', 'company_id']::text[]
  ) or not exists (
    select 1 from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public' and rel.relname = 'access_revocation_epochs'
      and con.contype = 'c' and con.convalidated
      and pg_get_constraintdef(con.oid) = 'CHECK ((generation >= 0))'
  ) then
    raise exception using errcode = '23514', message = 'postgres_access_epoch_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20261014_007_access_revocation_epochs_postgres',
  'jiejing-access-revocation-epochs-postgres-v20261014',
  'Persist account and company membership revocation generations without revoking valid baseline sessions'
)
on conflict (migration_id) do nothing;

commit;
