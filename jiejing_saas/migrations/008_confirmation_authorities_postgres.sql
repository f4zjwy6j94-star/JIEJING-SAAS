-- B0 receipt foundation only. No historical approval is re-signed, no live gate
-- is enabled. Final execution admission belongs to the later B1/B2 phases.
begin;

create unique index if not exists confirmation_authority_scope
  on confirmations(company_id, confirmation_id, store_id);
create unique index if not exists confirmation_authority_store_scope
  on stores(company_id, store_id);

create table if not exists confirmation_approval_authorities_v1 (
  authority_id text primary key,
  company_id text not null,
  confirmation_id text not null,
  store_id text,
  action_type text not null,
  approver_user_id text not null references users(user_id),
  approver_user_epoch bigint not null check (approver_user_epoch >= 0),
  approver_member_epoch bigint not null check (approver_member_epoch >= 0),
  required_permission text not null,
  approved_role text not null,
  approved_at text not null,
  approved_item_sha256 text not null check (length(approved_item_sha256) = 64),
  binding_version integer not null check (binding_version = 1),
  unique (company_id, confirmation_id, authority_id),
  foreign key (company_id, confirmation_id, store_id) references confirmations(company_id, confirmation_id, store_id),
  foreign key (company_id, store_id) references stores(company_id, store_id)
);

create table if not exists confirmation_execution_authorities_v1 (
  attempt_id text primary key,
  company_id text not null,
  store_id text,
  confirmation_id text not null,
  approval_authority_id text not null,
  executor_user_id text not null references users(user_id),
  executor_user_epoch bigint not null check (executor_user_epoch >= 0),
  executor_member_epoch bigint not null check (executor_member_epoch >= 0),
  required_permissions text not null,
  business_binding_sha256 text not null,
  operation_plan_sha256 text not null,
  operation_count integer not null check (operation_count >= 0),
  operation_state_json text not null,
  phase text not null,
  created_at text not null,
  admitted_at text,
  terminal_reason text,
  foreign key (company_id, confirmation_id, approval_authority_id)
    references confirmation_approval_authorities_v1(company_id, confirmation_id, authority_id),
  foreign key (company_id, confirmation_id, store_id) references confirmations(company_id, confirmation_id, store_id)
);

create unique index if not exists confirmation_one_active_attempt
  on confirmation_execution_authorities_v1(confirmation_id)
  where phase in ('prewrite','admitted','reconciliation_required');

alter table confirmations add column if not exists approval_authority_id text;
alter table external_execution_claims add column if not exists authority_json text;
alter table ebay_account_deletion_events add column if not exists verification_json text not null default '{}';
alter table ebay_account_deletion_events add column if not exists processing_json text not null default '{}';

do $$
begin
  if not exists (select 1 from pg_constraint where conname='confirmation_current_approval_scope'
    and conrelid='confirmations'::regclass) then
    alter table confirmations add constraint confirmation_current_approval_scope
      foreign key (company_id, confirmation_id, approval_authority_id)
      references confirmation_approval_authorities_v1(company_id, confirmation_id, authority_id);
  end if;
end $$;

create or replace function jiejing_approval_receipt_guard() returns trigger language plpgsql as $$
begin
  if TG_OP = 'UPDATE' then
    raise exception using errcode='23514', message='approval_authority_immutable';
  end if;
  -- Composite FKs use MATCH SIMPLE. This extra null-safe check permits genuine
  -- company-level approvals without allowing NULL to escape a store binding.
  if not exists (select 1 from confirmations c where c.company_id=NEW.company_id
    and c.confirmation_id=NEW.confirmation_id and c.store_id is not distinct from NEW.store_id
    and c.action_type=NEW.action_type) then
    raise exception using errcode='23514', message='approval_authority_scope_mismatch';
  end if;
  return NEW;
end $$;

create or replace trigger approval_receipt_guard before insert or update
  on confirmation_approval_authorities_v1 for each row execute function jiejing_approval_receipt_guard();

create or replace function jiejing_current_approval_scope_guard() returns trigger language plpgsql as $$
begin
  if NEW.approval_authority_id is not null and not exists (
    select 1 from confirmation_approval_authorities_v1 a where a.authority_id=NEW.approval_authority_id
      and a.company_id=NEW.company_id and a.confirmation_id=NEW.confirmation_id
      and a.store_id is not distinct from NEW.store_id and a.action_type=NEW.action_type) then
    raise exception using errcode='23514', message='approval_authority_pointer_mismatch';
  end if;
  return NEW;
end $$;

create or replace trigger current_approval_scope_guard before insert or update
  on confirmations for each row execute function jiejing_current_approval_scope_guard();

create or replace function jiejing_execution_receipt_scope_guard() returns trigger language plpgsql as $$
begin
  if TG_OP='UPDATE' and (NEW.company_id is distinct from OLD.company_id
    or NEW.confirmation_id is distinct from OLD.confirmation_id
    or NEW.store_id is distinct from OLD.store_id
    or NEW.approval_authority_id is distinct from OLD.approval_authority_id
    or NEW.executor_user_id is distinct from OLD.executor_user_id
    or NEW.executor_user_epoch is distinct from OLD.executor_user_epoch
    or NEW.executor_member_epoch is distinct from OLD.executor_member_epoch
    or NEW.attempt_id is distinct from OLD.attempt_id
    or NEW.required_permissions is distinct from OLD.required_permissions
    or NEW.business_binding_sha256 is distinct from OLD.business_binding_sha256
    or NEW.operation_plan_sha256 is distinct from OLD.operation_plan_sha256
    or NEW.operation_count is distinct from OLD.operation_count
    or NEW.created_at is distinct from OLD.created_at) then
    raise exception using errcode='23514', message='execution_authority_scope_immutable';
  end if;
  if not exists (select 1 from confirmation_approval_authorities_v1 a
    where a.company_id=NEW.company_id and a.confirmation_id=NEW.confirmation_id
      and a.authority_id=NEW.approval_authority_id and a.store_id is not distinct from NEW.store_id) then
    raise exception using errcode='23514', message='execution_authority_scope_mismatch';
  end if;
  return NEW;
end $$;

create or replace trigger execution_receipt_scope_guard before insert or update
  on confirmation_execution_authorities_v1 for each row execute function jiejing_execution_receipt_scope_guard();

do $$
begin
  if exists (
    with expected(table_name,column_name,udt_name,is_nullable) as (
      values
        ('confirmation_approval_authorities_v1'::text,'authority_id'::text,'text'::text,'NO'::text),
        ('confirmation_approval_authorities_v1','company_id','text','NO'),
        ('confirmation_approval_authorities_v1','confirmation_id','text','NO'),
        ('confirmation_approval_authorities_v1','store_id','text','YES'),
        ('confirmation_approval_authorities_v1','action_type','text','NO'),
        ('confirmation_approval_authorities_v1','approver_user_id','text','NO'),
        ('confirmation_approval_authorities_v1','approver_user_epoch','int8','NO'),
        ('confirmation_approval_authorities_v1','approver_member_epoch','int8','NO'),
        ('confirmation_approval_authorities_v1','required_permission','text','NO'),
        ('confirmation_approval_authorities_v1','approved_role','text','NO'),
        ('confirmation_approval_authorities_v1','approved_at','text','NO'),
        ('confirmation_approval_authorities_v1','approved_item_sha256','text','NO'),
        ('confirmation_approval_authorities_v1','binding_version','int4','NO'),
        ('confirmation_execution_authorities_v1','attempt_id','text','NO'),
        ('confirmation_execution_authorities_v1','company_id','text','NO'),
        ('confirmation_execution_authorities_v1','store_id','text','YES'),
        ('confirmation_execution_authorities_v1','confirmation_id','text','NO'),
        ('confirmation_execution_authorities_v1','approval_authority_id','text','NO'),
        ('confirmation_execution_authorities_v1','executor_user_id','text','NO'),
        ('confirmation_execution_authorities_v1','executor_user_epoch','int8','NO'),
        ('confirmation_execution_authorities_v1','executor_member_epoch','int8','NO'),
        ('confirmation_execution_authorities_v1','required_permissions','text','NO'),
        ('confirmation_execution_authorities_v1','business_binding_sha256','text','NO'),
        ('confirmation_execution_authorities_v1','operation_plan_sha256','text','NO'),
        ('confirmation_execution_authorities_v1','operation_count','int4','NO'),
        ('confirmation_execution_authorities_v1','operation_state_json','text','NO'),
        ('confirmation_execution_authorities_v1','phase','text','NO'),
        ('confirmation_execution_authorities_v1','created_at','text','NO'),
        ('confirmation_execution_authorities_v1','admitted_at','text','YES'),
        ('confirmation_execution_authorities_v1','terminal_reason','text','YES'),
        ('confirmations','approval_authority_id','text','YES'),
        ('external_execution_claims','authority_json','text','YES'),
        ('ebay_account_deletion_events','verification_json','text','NO'),
        ('ebay_account_deletion_events','processing_json','text','NO')
    ) select 1 from expected where not exists (select 1 from information_schema.columns c
      where c.table_schema='public' and c.table_name=expected.table_name and c.column_name=expected.column_name
        and c.udt_name=expected.udt_name and c.is_nullable=expected.is_nullable)
  ) then
    raise exception using errcode='23514',message='postgres_confirmation_authority_schema_postcondition_failed';
  end if;
end $$;

insert into schema_migrations (migration_id, checksum, summary)
values ('20261014_008_confirmation_authorities_postgres','jiejing-confirmation-authorities-postgres-v20261014',
  'Immutable scoped merchant approval receipts and verified deletion lifecycle foundation; no legacy re-signing')
on conflict (migration_id) do nothing;
commit;
