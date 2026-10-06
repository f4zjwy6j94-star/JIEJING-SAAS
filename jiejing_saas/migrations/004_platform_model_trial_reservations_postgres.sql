begin;

create table if not exists platform_model_trial_reservations (
  reservation_id text primary key,
  company_id text not null references companies(company_id),
  period_key text not null,
  slot_number integer not null check (slot_number > 0),
  route_scope text not null check (route_scope in ('listing_draft_generation', 'merchant_ceo_chat')),
  baseline_used integer not null default 0
    constraint platform_model_trial_reservations_baseline_used_check check (baseline_used >= 0),
  status text not null default 'consumed'
    constraint platform_model_trial_reservations_status_check
      check (status in ('reserved', 'consumed', 'released')),
  created_at timestamptz not null,
  released_at timestamptz,
  unique (company_id, period_key, slot_number)
);

alter table platform_model_trial_reservations
  add column if not exists baseline_used integer not null default 0;
alter table platform_model_trial_reservations
  add column if not exists status text not null default 'consumed';
alter table platform_model_trial_reservations
  add column if not exists released_at timestamptz;

with period_baseline as (
  select company_id, period_key, greatest(min(slot_number) - 1, 0) as inferred_baseline
  from platform_model_trial_reservations
  group by company_id, period_key
)
update platform_model_trial_reservations as reservation
set baseline_used = greatest(reservation.baseline_used, period_baseline.inferred_baseline)
from period_baseline
where reservation.company_id = period_baseline.company_id
  and reservation.period_key = period_baseline.period_key;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.platform_model_trial_reservations'::regclass
      and conname = 'platform_model_trial_reservations_baseline_used_check'
  ) then
    alter table platform_model_trial_reservations
      add constraint platform_model_trial_reservations_baseline_used_check
      check (baseline_used >= 0);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.platform_model_trial_reservations'::regclass
      and conname = 'platform_model_trial_reservations_status_check'
  ) then
    alter table platform_model_trial_reservations
      add constraint platform_model_trial_reservations_status_check
      check (status in ('reserved', 'consumed', 'released'));
  end if;
end $$;

do $$
begin
  if exists (
    with expected(column_name, udt_name, is_nullable) as (
      values
        ('reservation_id'::text, 'text'::text, 'NO'::text),
        ('company_id', 'text', 'NO'),
        ('period_key', 'text', 'NO'),
        ('slot_number', 'int4', 'NO'),
        ('route_scope', 'text', 'NO'),
        ('baseline_used', 'int4', 'NO'),
        ('status', 'text', 'NO'),
        ('created_at', 'timestamptz', 'NO'),
        ('released_at', 'timestamptz', 'YES')
    )
    select 1
    from expected
    where not exists (
      select 1
      from information_schema.columns col
      where col.table_schema = 'public'
        and col.table_name = 'platform_model_trial_reservations'
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
      and rel.relname = 'platform_model_trial_reservations'
      and con.contype = 'u'
      and con.convalidated
      and (
        select array_agg(att.attname::text order by key_column.ordinality)
        from unnest(con.conkey) with ordinality as key_column(attnum, ordinality)
        join pg_attribute att
          on att.attrelid = con.conrelid
         and att.attnum = key_column.attnum
         and not att.attisdropped
      ) = array['company_id', 'period_key', 'slot_number']::text[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;

  if not exists (
    select 1
    from pg_constraint con
    join pg_class rel on rel.oid = con.conrelid
    join pg_namespace nsp on nsp.oid = rel.relnamespace
    where nsp.nspname = 'public'
      and rel.relname = 'platform_model_trial_reservations'
      and con.contype = 'f'
      and con.convalidated
      and con.confrelid = 'public.companies'::regclass
      and (
        select array_agg(att.attname::text order by key_column.ordinality)
        from unnest(con.conkey) with ordinality as key_column(attnum, ordinality)
        join pg_attribute att
          on att.attrelid = con.conrelid
         and att.attnum = key_column.attnum
         and not att.attisdropped
      ) = array['company_id']::text[]
  ) then
    raise exception using errcode = '23514', message = 'postgres_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values (
  '20260901_004_platform_model_trial_reservations_postgres',
  'jiejing-platform-model-trial-reservations-postgres-v20260901',
  'Add lifecycle-aware tenant-period slots for atomic platform-funded model trial quota'
)
on conflict (migration_id) do nothing;

commit;
