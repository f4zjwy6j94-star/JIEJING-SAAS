"""Backend-only immutable merchant approval receipts (not execution permits).

This layer captures and verifies the decision binding. Each outbound executor
must still perform its own final admission; a valid receipt alone cannot send.
"""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import re
import secrets
from typing import Any
from .permissions import permissions_for_role


def _sqlite_identifier_name(name):
    # SQLite's built-in NOCASE folds ASCII A-Z only. Do not use Unicode
    # casefold or apply this to SQL bodies / quoted phase values.
    return str(name).translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))


def item_digest(item: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def require_epochs(epochs: Any) -> dict[str, int]:
    if (not isinstance(epochs, dict) or set(epochs) != {'user_epoch','member_epoch'}
            or any(type(epochs[k]) is not int or epochs[k] < 0 for k in epochs)):
        raise PermissionError('approval_request_authority_required')
    return epochs


def create_approval(repo, conn, *, confirmation, user_id, expected_epochs, permission, approved_at):
    epochs = require_epochs(expected_epochs)
    company = confirmation['company_id']
    if repo._access_principal_state(conn, user_id=user_id, company_id=company) != 'active':
        raise PermissionError('approval_principal_invalid')
    if repo._access_epochs(conn, user_id=user_id, company_id=company) != epochs:
        raise PermissionError('approval_request_authority_changed')
    member = conn.execute('select role from team_members where company_id=? and user_id=?',(company,user_id)).fetchone()
    if permission not in permissions_for_role(str(member['role'])):
        raise PermissionError('approval_permission_denied')
    if confirmation['store_id'] is not None:
        # Serialize decisions with verified store deletion. No company lock is
        # acquired after the user lock; the store is the narrow lifecycle guard.
        lock = ' for update' if repo.database_engine == 'postgres' else ''
        store = conn.execute(f'select stage from stores where company_id=? and store_id=?{lock}',
                             (company,confirmation['store_id'])).fetchone()
        deleting = conn.execute("select 1 from ebay_account_deletion_events where company_id=? and store_id=? and status in ('processing','completed')",
                                (company,confirmation['store_id'])).fetchone()
        if not store or store['stage'] == 'account_deleted' or deleting:
            raise PermissionError('approval_store_deletion_in_progress')
    authority_id = 'approval_' + secrets.token_hex(16)
    conn.execute('''insert into confirmation_approval_authorities_v1
        (authority_id,company_id,confirmation_id,store_id,action_type,approver_user_id,
         approver_user_epoch,approver_member_epoch,required_permission,approved_role,
         approved_at,approved_item_sha256,binding_version) values (?,?,?,?,?,?,?,?,?,?,?,?,1)''',
        (authority_id,company,confirmation['confirmation_id'],confirmation['store_id'],confirmation['action_type'],
         user_id,epochs['user_epoch'],epochs['member_epoch'],permission,str(member['role']),approved_at,item_digest(confirmation['item'])))
    return authority_id


def require_approval_binding(conn, confirmation):
    """B0 binding check only. B1/B2 must add both principals at final admission."""
    row = conn.execute('''select a.* from confirmations c join confirmation_approval_authorities_v1 a
        on a.authority_id=c.approval_authority_id and a.company_id=c.company_id and a.confirmation_id=c.confirmation_id
        where c.company_id=? and c.confirmation_id=?''',
        (confirmation['company_id'],confirmation['confirmation_id'])).fetchone()
    if not row:
        raise PermissionError('approval_authority_missing_reapproval_required')
    def stamp(value):
        # PG returns timestamptz in the session timezone, SQLite stores ISO text.
        try:
            parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (TypeError,ValueError,OverflowError):
            return None
    if (row['binding_version'] != 1 or row['store_id'] != confirmation['store_id']
            or row['action_type'] != confirmation['action_type'] or row['approver_user_id'] != confirmation['decided_by']
            or stamp(row['approved_at']) is None or stamp(row['approved_at']) != stamp(confirmation['decided_at'])
            or row['approved_item_sha256'] != item_digest(confirmation['item'])
            or any(type(row[k]) is not int or row[k] < 0 for k in ('approver_user_epoch','approver_member_epoch'))):
        raise PermissionError('approval_authority_binding_changed_reapproval_required')
    return dict(row)


def require_execution_principals(repo, conn, *, confirmation, executor_user_id, expected_epochs):
    """Compare the original two authorities while holding every user before members.

    The caller already holds the narrow store/confirmation lifecycle locks. No
    company lock or network call is acquired here. An ABA transition therefore
    cannot be hidden by reading a fresh epoch after a preparatory wait.
    """
    approval = require_approval_binding(conn, confirmation)
    try:
        epochs = require_epochs(expected_epochs)
    except PermissionError as error:
        raise PermissionError('execution_request_authority_required') from error
    company = confirmation['company_id']
    approver = str(approval['approver_user_id'])
    principals = sorted({approver, str(executor_user_id)})
    lock = ' for update' if repo.database_engine == 'postgres' else ''
    users = {user: conn.execute(f'select status from users where user_id=?{lock}', (user,)).fetchone()
             for user in principals}
    members = {user: conn.execute(f'select role from team_members where company_id=? and user_id=?{lock}',
                                  (company, user)).fetchone() for user in principals}
    required = ['execute_confirmed_action']
    if confirmation['action_type'] == 'create_ebay_inventory_location':
        required.append('manage_connections')
    for user, wanted_epochs, permissions, reason in (
        (approver, {'user_epoch': approval['approver_user_epoch'], 'member_epoch': approval['approver_member_epoch']},
         ['approve_high_risk'], 'approval_authority_changed_reapproval_required'),
        (str(executor_user_id), epochs, required, 'execution_request_authority_changed'),
    ):
        if (not users[user] or users[user]['status'] != 'active' or not members[user]
                or not set(permissions).issubset(permissions_for_role(str(members[user]['role'])))
                or repo._access_epochs(conn, user_id=user, company_id=company) != wanted_epochs):
            raise PermissionError(reason)
    return approval


def initialize_sqlite_authorities(conn):
    # Additive only; do not invent authority for historical approved rows.
    for table,column,definition in (
        ('confirmations','approval_authority_id','text references confirmation_approval_authorities_v1(authority_id)'),
        ('external_execution_claims','authority_json','text'),
        ('ebay_account_deletion_events','verification_json',"text not null default '{}'"),
        ('ebay_account_deletion_events','processing_json',"text not null default '{}'"),
    ):
        if column not in {row['name'] for row in conn.execute(f'pragma table_info({table})').fetchall()}:
            conn.execute(f'alter table {table} add column {column} {definition}')
    schema_sql = '''
    create unique index if not exists confirmation_authority_scope on confirmations(company_id,confirmation_id,store_id);
    create unique index if not exists confirmation_authority_store_scope on stores(company_id,store_id);
    create table if not exists confirmation_approval_authorities_v1 (
      authority_id text primary key, company_id text not null, confirmation_id text not null, store_id text,
      action_type text not null, approver_user_id text not null references users(user_id),
      approver_user_epoch integer not null check(approver_user_epoch >= 0),
      approver_member_epoch integer not null check(approver_member_epoch >= 0),
      required_permission text not null, approved_role text not null, approved_at text not null,
      approved_item_sha256 text not null check(length(approved_item_sha256)=64), binding_version integer not null check(binding_version=1),
      unique(company_id,confirmation_id,authority_id),
      foreign key(company_id,confirmation_id,store_id) references confirmations(company_id,confirmation_id,store_id),
      foreign key(company_id,store_id) references stores(company_id,store_id));
    create table if not exists confirmation_execution_authorities_v1 (
      attempt_id text primary key, company_id text not null, store_id text, confirmation_id text not null,
      approval_authority_id text not null, executor_user_id text not null references users(user_id),
      executor_user_epoch integer not null check(executor_user_epoch >= 0),
      executor_member_epoch integer not null check(executor_member_epoch >= 0),
      required_permissions text not null, business_binding_sha256 text not null,
      operation_plan_sha256 text not null, operation_count integer not null check(operation_count >= 0),
      operation_state_json text not null, phase text not null, created_at text not null, admitted_at text, terminal_reason text,
      foreign key(company_id,confirmation_id,approval_authority_id)
        references confirmation_approval_authorities_v1(company_id,confirmation_id,authority_id),
      foreign key(company_id,confirmation_id,store_id) references confirmations(company_id,confirmation_id,store_id));
    create unique index if not exists confirmation_one_active_attempt on confirmation_execution_authorities_v1(confirmation_id)
      where phase in ('prewrite','admitted','reconciliation_required');
    create trigger if not exists approval_immutable_update before update on confirmation_approval_authorities_v1
      begin select raise(abort,'approval_authority_immutable'); end;
    create trigger if not exists approval_scope_insert before insert on confirmation_approval_authorities_v1
      when not exists(select 1 from confirmations c where c.confirmation_id=new.confirmation_id and c.company_id=new.company_id
        and c.store_id is new.store_id and c.action_type=new.action_type)
      begin select raise(abort,'approval_authority_scope_mismatch'); end;
    create trigger if not exists approval_pointer_scope before update on confirmations
      when new.approval_authority_id is not null and not exists(select 1 from confirmation_approval_authorities_v1 a
        where a.authority_id=new.approval_authority_id and a.company_id=new.company_id and a.confirmation_id=new.confirmation_id
          and a.store_id is new.store_id and a.action_type=new.action_type)
      begin select raise(abort,'approval_authority_pointer_mismatch'); end;
    create trigger if not exists approval_pointer_scope_insert before insert on confirmations
      when new.approval_authority_id is not null and not exists(select 1 from confirmation_approval_authorities_v1 a
        where a.authority_id=new.approval_authority_id and a.company_id=new.company_id and a.confirmation_id=new.confirmation_id
          and a.store_id is new.store_id and a.action_type=new.action_type)
      begin select raise(abort,'approval_authority_pointer_mismatch'); end;
    create trigger if not exists execution_authority_scope_insert before insert on confirmation_execution_authorities_v1
      when not exists(select 1 from confirmation_approval_authorities_v1 a where a.authority_id=new.approval_authority_id
        and a.company_id=new.company_id and a.confirmation_id=new.confirmation_id and a.store_id is new.store_id)
      begin select raise(abort,'execution_authority_scope_mismatch'); end;
    create trigger if not exists execution_authority_scope_update before update on confirmation_execution_authorities_v1
      when new.company_id<>old.company_id or new.confirmation_id<>old.confirmation_id or new.store_id is not old.store_id
        or new.approval_authority_id<>old.approval_authority_id or new.executor_user_id<>old.executor_user_id
        or new.executor_user_epoch<>old.executor_user_epoch or new.executor_member_epoch<>old.executor_member_epoch
        or new.attempt_id<>old.attempt_id or new.required_permissions<>old.required_permissions
        or new.business_binding_sha256<>old.business_binding_sha256 or new.operation_plan_sha256<>old.operation_plan_sha256
        or new.operation_count<>old.operation_count or new.created_at<>old.created_at
      begin select raise(abort,'execution_authority_scope_immutable'); end;
    '''
    # Stable request-time initialization must not repeatedly DROP/CREATE
    # triggers (DDL writes on every repository call). Existing unexpected
    # behavior is schema drift, not permission to silently overwrite a guard.
    index_name = 'confirmation_one_active_attempt'
    index_table = 'confirmation_execution_authorities_v1'
    index_sql = re.search(r'create unique index if not exists confirmation_one_active_attempt\b.*?;',
                          schema_sql, re.S).group(0)
    existing_index = conn.execute('select type,tbl_name,sql from sqlite_master where name collate nocase=?',
                                  (index_name,)).fetchall()
    if existing_index:
        def normalized_index(statement):
            # SQLite canonicalizes the CREATE INDEX prefix when storing SQL.
            # Preserve quoted literal contents, especially case-sensitive phases.
            text = re.sub(r'^\s*create\s+(unique\s+)?index\s+(?:if\s+not\s+exists\s+)?',
                          lambda match: 'create ' + ('unique ' if match.group(1) else '') + 'index ',
                          str(statement or ''), flags=re.I)
            text = re.sub(r'^(create (?:unique )?index )(\w+)\b',
                          lambda match: match.group(1) + _sqlite_identifier_name(match.group(2)),
                          text, flags=re.ASCII)
            parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", text)
            return ''.join(part if index % 2 else re.sub(r'\s+', ' ', part)
                           for index, part in enumerate(parts)).strip().rstrip(';')
        index_properties = [row for row in conn.execute(f'pragma index_list({index_table})').fetchall()
                            if _sqlite_identifier_name(row['name']) == index_name]
        index_columns = [row['name'] for row in conn.execute(f'pragma index_info({index_name})').fetchall()]
        if (len(existing_index) != 1 or existing_index[0]['type'] != 'index'
                or existing_index[0]['tbl_name'] != index_table
                or len(index_properties) != 1 or index_properties[0]['unique'] != 1
                or index_properties[0]['partial'] != 1 or index_columns != ['confirmation_id']
                or normalized_index(existing_index[0]['sql']) != normalized_index(index_sql)):
            raise RuntimeError('confirmation_authority_sqlite_guard_drift:' + index_name)
    expected = {
        name: statement for statement, name in re.findall(
            r'(create trigger if not exists (\w+)\b.*?\bend;)', schema_sql, re.S)
    }
    def normalized(statement):
        # SQLite canonicalizes only the leading CREATE TRIGGER keywords.
        # Do not case-fold the body: quoted values remain case-sensitive.
        text=re.sub(r'^\s*create\s+trigger\s+(?:if\s+not\s+exists\s+)?',
                    'create trigger ',str(statement or ''),flags=re.I)
        text=re.sub(r'^(create trigger )(\w+)\b',
                    lambda match: match.group(1) + _sqlite_identifier_name(match.group(2)),
                    text,flags=re.ASCII)
        return ' '.join(text.split()).rstrip(';')
    placeholders = ','.join('?' for _ in expected)
    for row in conn.execute(f"select name,sql from sqlite_master where type='trigger' and name collate nocase in ({placeholders})",
                            tuple(expected)).fetchall():
        name = _sqlite_identifier_name(row['name'])
        if normalized(row['sql']) != normalized(expected[name]):
            raise RuntimeError('confirmation_authority_sqlite_guard_drift:' + name)
    conn.executescript(schema_sql)
