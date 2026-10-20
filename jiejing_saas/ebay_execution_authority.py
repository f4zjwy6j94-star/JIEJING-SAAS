"""Fixed eBay write plans and durable, per-operation merchant admission.

Only the existing eBay adapter mints plans; this is not a user workflow language.
Each network call occurs after its admission transaction has committed. An
admitted call without a definite receipt remains possibly submitted forever
until the existing exact read-only reconciliation proves otherwise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import secrets
import urllib.parse

from .confirmation_authority import item_digest, require_approval_binding, require_execution_principals

_PLAN_MINT = object()
_PERMIT_MINT = object()
_DATETIME_TYPE = datetime
HASH_KEYS = ('connection_id_sha256', 'credential_ref_sha256', 'oauth_request_id_sha256', 'seller_identity_sha256')
SUPPORTED = {'publish_listing', 'save_ebay_listing_draft', 'cleanup_test_listing', 'create_ebay_inventory_location'}
EXECUTION_DENIAL_CODES = frozenset({
    'approval_authority_missing_reapproval_required', 'approval_authority_binding_changed_reapproval_required',
    'approval_authority_changed_reapproval_required', 'execution_request_authority_required',
    'execution_request_authority_changed', 'execution_store_deletion_in_progress', 'execution_confirmation_scope_changed',
    'ebay_execution_plan_binding_changed', 'ebay_execution_credential_changed', 'ebay_execution_target_invalid',
    'ebay_execution_permit_required', 'ebay_execution_attempt_already_recorded',
    'ebay_execution_operation_already_admitted_or_out_of_order', 'ebay_execution_operation_binding_changed',
    'ebay_execution_offer_receipt_invalid', 'ebay_execution_preparation_expired',
    'external_execution_confirmation_not_fresh',
})


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def segment(value):
    if (not isinstance(value, str) or not value or len(value) > 256 or value in {'.', '..'}
            or any(char.isspace() or ord(char) < 32 or char in '/\\%?#' for char in value)):
        raise PermissionError('ebay_execution_target_invalid')
    return urllib.parse.quote(value, safe='')


def legacy_credential(connection):
    metadata = connection.get('metadata') if isinstance(connection.get('metadata'), dict) else {}
    return {'kind': 'legacy', 'connection_id': str(connection.get('connection_id') or ''),
            'fingerprint': item_digest({'connection_id': str(connection.get('connection_id') or ''),
                'secret_ref_sha256': hashlib.sha256(str(connection.get('secret_ref') or '').encode()).hexdigest(),
                'status': connection.get('status'), 'scopes': connection.get('scopes'),
                'metadata_sha256': item_digest(metadata),
                'secret_boundary_sha256': connection.get('_execution_secret_boundary_sha256')})}


def scoped_credential(boundary):
    return {'kind': 'unpublished', **{key: str(boundary.get(key) or '') for key in HASH_KEYS}}


class EbayOperationPlan:
    """Immutable process-local output of the trusted fixed adapter factory."""
    __slots__ = ('_serialized', '_minted')

    def __init__(self, document, *, mint_token=None):
        if mint_token is not _PLAN_MINT:
            raise PermissionError('ebay_execution_plan_required')
        object.__setattr__(self, '_serialized', canonical(document))
        object.__setattr__(self, '_minted', True)

    def __setattr__(self, name, value):
        raise TypeError('ebay_execution_plan_immutable')

    def document(self):
        return json.loads(self._serialized)

    def __repr__(self):
        return 'EbayOperationPlan(<backend-only>)'

    def __reduce__(self):
        raise TypeError('ebay_execution_plan_not_serializable')


class EbayExecutionDenied(PermissionError):
    def __init__(self, reason, recovery):
        super().__init__(reason)
        self.recovery = recovery


class EbayWritePermit:
    """Repository-minted authority; neither a public dict nor a bearer token."""
    __slots__ = ('_repo', '_attempt', '_company', '_confirmation', '_minted')

    def __init__(self, repo, attempt, company, confirmation, *, mint_token=None):
        if mint_token is not _PERMIT_MINT:
            raise PermissionError('ebay_execution_permit_required')
        for name, value in (('_repo', repo), ('_attempt', attempt), ('_company', company),
                            ('_confirmation', confirmation), ('_minted', True)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise TypeError('ebay_execution_permit_immutable')

    def admit(self, *, operation_index, method, path, body, marketplace_id, credential):
        return admit(self, operation_index=operation_index, method=method, path=path,
                     body=body, marketplace_id=marketplace_id, credential=credential)

    def record(self, *, operation_index, result):
        return record(self, operation_index=operation_index, result=result)

    def __repr__(self):
        return 'EbayWritePermit(<backend-only>)'

    def __reduce__(self):
        raise TypeError('ebay_execution_permit_not_serializable')


def approved_payload(confirmation):
    item = confirmation['item']
    if confirmation['action_type'] == 'cleanup_test_listing':
        return {'cleanup_plan': item.get('cleanup_plan') or {}}
    if confirmation['action_type'] == 'create_ebay_inventory_location':
        return item.get('location_payload') or {}
    return item.get('publish_payload') or {}


def _fixed_resources(plan, state=None):
    """Only the four supported eBay routes, not a generic dependency engine."""
    resources = set()
    if plan.get('product_sku'):
        resources.add('/sell/inventory/v1/inventory_item/' + segment(plan['product_sku']))
    operations = list(plan['operations']) + list((state or {}).get('operations', []))
    for operation in operations:
        target = operation.get('resolved_target') or operation.get('target') or ''
        for prefix in ('/sell/inventory/v1/inventory_item/', '/sell/inventory/v1/offer/', '/sell/inventory/v1/location/'):
            if target.startswith(prefix) and '{' not in target:
                resources.add(prefix + target[len(prefix):].split('/')[0])
        receipt = operation.get('receipt') or {}
        if operation.get('status') == 'succeeded' and receipt.get('offer_id'):
            resources.add('/sell/inventory/v1/offer/' + segment(receipt['offer_id']))
    return resources


def valid_operation_state(attempt, state):
    """An absent/incomplete log is uncertainty, never evidence of zero writes."""
    if not isinstance(state, dict) or not isinstance(state.get('plan'), dict):
        return False
    operations = state.get('operations')
    planned = state['plan'].get('operations')
    count = attempt.get('operation_count')
    try:
        plan_digest = item_digest(state['plan'])
    except (TypeError, ValueError):
        return False
    if (type(count) is not int or count < 1 or not isinstance(operations, list)
            or not isinstance(planned, list) or len(operations) != count or len(planned) != count
            or plan_digest != attempt.get('operation_plan_sha256')
            or not isinstance(state['plan'].get('marketplace_id'), str) or not state['plan']['marketplace_id']
            or state['plan'].get('action_type') not in SUPPORTED
            or any(state['plan'].get(key) != attempt.get(key) for key in ('company_id','store_id','confirmation_id'))):
        return False
    trailing = False
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get('status') not in {'planned','admitted','succeeded','unknown'}:
            return False
        status = operation['status']
        if status == 'planned' and set(operation) != {'status'}:
            return False
        if status != 'planned' and (not attempt.get('admitted_at') or not operation.get('resolved_target')
                or not operation.get('admitted_at')):
            return False
        if trailing and status != 'planned':
            return False
        if status != 'succeeded':
            trailing = True
        if status in {'succeeded','unknown'}:
            receipt = operation.get('receipt')
            if (not isinstance(receipt, dict) or receipt.get('attempt_id') != attempt.get('attempt_id')
                    or receipt.get('operation_index') != index
                    or receipt.get('plan_sha256') != attempt.get('operation_plan_sha256')
                    or receipt.get('binding_sha256') != attempt.get('business_binding_sha256')
                    or (receipt.get('http_status') is not None and type(receipt['http_status']) is not int)):
                return False
            if status == 'succeeded':
                if type(receipt.get('http_status')) is not int or not 200 <= receipt['http_status'] < 300:
                    return False
                required = {'create_offer':'offer_id','publish_offer':'listing_id'}.get(planned[index]['kind'])
                if required:
                    try:
                        segment(receipt.get(required))
                    except PermissionError:
                        return False
    return True


def load_operation_state(value):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def expired_zero_prewrite(attempt, state):
    """Eligibility for explicit retirement only; time never recalls admission."""
    if (attempt.get('phase') != 'prewrite' or attempt.get('admitted_at') is not None
            or not valid_operation_state(attempt, state)
            or any(operation['status'] != 'planned' for operation in state['operations'])):
        return False
    stamp = attempt.get('created_at')
    try:
        if isinstance(stamp, str):
            stamp = _DATETIME_TYPE.fromisoformat(stamp)
        if not isinstance(stamp, _DATETIME_TYPE) or stamp.tzinfo is None or stamp.utcoffset() is None:
            return False
        current = datetime.now(timezone.utc)
        return stamp <= current and current > stamp + timedelta(seconds=60)
    except (TypeError, ValueError, OverflowError):
        return False


def _validate_lifetime(confirmation, plan):
    """Sample time only after every credential/principal lock has been acquired."""
    if plan['credential']['kind'] != 'unpublished':
        return
    current_time = datetime.now(timezone.utc)
    stamp = confirmation.get('decided_at')
    try:
        approved_at = stamp if isinstance(stamp, _DATETIME_TYPE) else _DATETIME_TYPE.fromisoformat(str(stamp))
        age = (current_time - approved_at).total_seconds()
    except (TypeError, ValueError, OverflowError):
        raise PermissionError('external_execution_confirmation_not_fresh') from None
    if not 0 <= age <= 900:
        raise PermissionError('external_execution_confirmation_not_fresh')
    if plan['action_type'] in {'save_ebay_listing_draft', 'create_ebay_inventory_location'}:
        deadline = plan.get('preparation_expires_at_epoch')
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not deadline - 30 <= current_time.timestamp() <= deadline):
            raise PermissionError('ebay_execution_preparation_expired')


def _validate_business_and_credential(repo, conn, confirmation, plan):
    for key in ('company_id', 'store_id', 'confirmation_id', 'action_type', 'task_id'):
        if str(plan.get(key) or '') != str(confirmation.get(key) or ''):
            raise PermissionError('ebay_execution_plan_binding_changed')
    if plan['action_type'] not in SUPPORTED or plan['payload_sha256'] != item_digest(approved_payload(confirmation)):
        raise PermissionError('ebay_execution_plan_binding_changed')
    lock = ' for update' if repo.database_engine == 'postgres' else ''
    store = conn.execute('select platform,marketplace,stage from stores where company_id=? and store_id=?',
                         (confirmation['company_id'], confirmation['store_id'])).fetchone()
    deleting = conn.execute("select 1 from ebay_account_deletion_events where company_id=? and store_id=? and status in ('processing','completed')",
                            (confirmation['company_id'], confirmation['store_id'])).fetchone()
    if (not store or store['stage'] == 'account_deleted' or deleting
            or str(store['platform']).lower() != 'ebay' or store['marketplace'] != plan['marketplace_id']):
        raise PermissionError('ebay_execution_plan_binding_changed')
    expected = plan['credential']
    if expected['kind'] == 'unpublished':
        current = repo._unpublished_draft_execution_credential_boundary_conn(conn,
            company_id=confirmation['company_id'], store_id=confirmation['store_id'], include_private=False, lock_rows=True)
        if current.get('ready') is not True or scoped_credential(current) != expected:
            raise PermissionError('ebay_execution_credential_changed')
    elif expected['kind'] == 'legacy':
        row = conn.execute(f'select * from platform_connections where company_id=? and store_id=? and connection_id=?{lock}',
            (confirmation['company_id'], confirmation['store_id'], expected['connection_id'])).fetchone()
        if not row:
            raise PermissionError('ebay_execution_credential_changed')
        current = repo._ebay_execution_connection_conn(conn, row, lock_rows=True)
        if legacy_credential(current) != expected:
            raise PermissionError('ebay_execution_credential_changed')
    else:
        raise PermissionError('ebay_execution_credential_changed')


def _historical_resources(confirmation):
    """Exact resource names in the four legacy approved payload contracts."""
    item = confirmation['item']
    resources = set()
    def add(prefix, value):
        if value:
            resources.add('/sell/inventory/v1/' + prefix + '/' + segment(value))
    if confirmation['action_type'] in {'publish_listing','save_ebay_listing_draft'}:
        payload = item.get('publish_payload') or {}
        add('inventory_item', (payload.get('listing') or {}).get('sku'))
        add('offer', (payload.get('existing_ebay_draft') or item.get('existing_ebay_draft') or {}).get('offer_id'))
    elif confirmation['action_type'] == 'create_ebay_inventory_location':
        add('location', (item.get('location_payload') or {}).get('merchantLocationKey'))
    elif confirmation['action_type'] == 'cleanup_test_listing':
        for operation in (item.get('cleanup_plan') or {}).get('operations') or []:
            add('offer', operation.get('offer_id'))
            add('inventory_item', operation.get('sku'))
    return resources


def require_no_unresolved_resources(repo, conn, *, confirmation, marketplace_id, resources):
    """One read-only conflict rule shared by claim and fresh recovery display.

    A claim caller holds the existing store lock. A display caller never gains
    authority from this read and never retires or appends an execution record.
    """
    active = conn.execute("select * from confirmation_execution_authorities_v1 "
                          "where company_id=? and store_id=? and phase in ('prewrite','admitted','reconciliation_required')",
                          (confirmation['company_id'], confirmation['store_id'])).fetchall()
    for row in active:
        state = load_operation_state(row['operation_state_json'])
        if not valid_operation_state(dict(row), state):
            raise PermissionError('ebay_execution_prior_outcome_unresolved')
        if (state['plan'].get('marketplace_id') == marketplace_id
                and resources.intersection(_fixed_resources(state['plan'], state))):
            raise PermissionError('ebay_execution_prior_outcome_unresolved')
    historical = conn.execute("""select c.* from confirmations c where c.company_id=? and c.store_id=?
        and c.action_type in ('publish_listing','save_ebay_listing_draft','cleanup_test_listing','create_ebay_inventory_location')
        and c.status in ('external_execution_processing_manual_reconcile','external_execution_claimed_prewrite')
        and not exists(select 1 from confirmation_execution_authorities_v1 a
          where a.company_id=c.company_id and a.confirmation_id=c.confirmation_id)""",
        (confirmation['company_id'], confirmation['store_id'])).fetchall()
    for row in historical:
        try:
            old_resources = _historical_resources(repo._confirmation_row_to_dict(row))
        except (TypeError, ValueError, AttributeError):
            raise PermissionError('ebay_execution_prior_outcome_unresolved') from None
        except PermissionError as error:
            if str(error) != 'ebay_execution_target_invalid':
                raise
            raise PermissionError('ebay_execution_prior_outcome_unresolved') from error
        if not old_resources or resources.intersection(old_resources):
            raise PermissionError('ebay_execution_prior_outcome_unresolved')


def require_no_unresolved_confirmation_resources(repo, conn, confirmation):
    store = conn.execute('select marketplace from stores where company_id=? and store_id=?',
                         (confirmation['company_id'], confirmation.get('store_id'))).fetchone()
    if not store:
        return
    require_no_unresolved_resources(repo, conn, confirmation=confirmation,
        marketplace_id=str(store['marketplace'] or 'EBAY_US'), resources=_historical_resources(confirmation))


def create_attempt(repo, conn, *, confirmation, executor_user_id, expected_epochs, operation_plan):
    # Keep binding errors distinct from missing executor epochs for old records.
    require_approval_binding(conn, confirmation)
    prior_denial = repo._ebay_preclaim_denial_reason_conn(conn, confirmation)
    if prior_denial:
        raise PermissionError(prior_denial)
    if not isinstance(operation_plan, EbayOperationPlan) or not operation_plan._minted:
        raise PermissionError('ebay_execution_plan_required')
    document = operation_plan.document()
    if not document.get('operations'):
        raise PermissionError('ebay_execution_plan_required')
    prior = conn.execute('select phase from confirmation_execution_authorities_v1 where company_id=? and confirmation_id=?',
                          (confirmation['company_id'], confirmation['confirmation_id'])).fetchall()
    if prior:
        # A new pending requires a new decision; an old attempt is never replayed.
        raise PermissionError('ebay_execution_attempt_already_recorded')
    require_no_unresolved_resources(repo, conn, confirmation=confirmation,
        marketplace_id=document['marketplace_id'], resources=_fixed_resources(document))
    _validate_business_and_credential(repo, conn, confirmation, document)
    approval = require_execution_principals(repo, conn, confirmation=confirmation,
        executor_user_id=executor_user_id, expected_epochs=expected_epochs)
    _validate_lifetime(confirmation, document)
    attempt_id = 'ebay_attempt_' + secrets.token_hex(16)
    timestamp = datetime.now(timezone.utc).isoformat()
    state = {'plan': document, 'operations': [{'status': 'planned'} for _ in document['operations']]}
    permissions = ['execute_confirmed_action']
    if document['action_type'] == 'create_ebay_inventory_location':
        permissions.append('manage_connections')
    conn.execute('''insert into confirmation_execution_authorities_v1
        (attempt_id,company_id,store_id,confirmation_id,approval_authority_id,executor_user_id,
         executor_user_epoch,executor_member_epoch,required_permissions,business_binding_sha256,
         operation_plan_sha256,operation_count,operation_state_json,phase,created_at)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,'prewrite',?)''',
        (attempt_id, confirmation['company_id'], confirmation['store_id'], confirmation['confirmation_id'],
         approval['authority_id'], executor_user_id, expected_epochs['user_epoch'], expected_epochs['member_epoch'],
         canonical(permissions), item_digest(confirmation['item']), item_digest(document), len(document['operations']), canonical(state), timestamp))
    return EbayWritePermit(repo, attempt_id, confirmation['company_id'], confirmation['confirmation_id'], mint_token=_PERMIT_MINT)


def validate_unconsumed_permit(permit, conn, confirmation):
    """Revalidate original authority inside the existing nonce-consume transaction."""
    if not isinstance(permit, EbayWritePermit) or not permit._minted:
        raise PermissionError('ebay_execution_permit_required')
    repo = permit._repo
    lock = ' for update' if repo.database_engine == 'postgres' else ''
    row = conn.execute(f'select * from confirmation_execution_authorities_v1 where attempt_id=?{lock}',
                       (permit._attempt,)).fetchone()
    if not row or row['phase'] != 'prewrite':
        raise PermissionError('ebay_execution_attempt_already_recorded')
    state = load_operation_state(row['operation_state_json'])
    if (not valid_operation_state(dict(row), state)
            or item_digest(confirmation['item']) != row['business_binding_sha256']
            or any(op['status'] != 'planned' for op in state['operations'])):
        raise PermissionError('ebay_execution_plan_binding_changed')
    _validate_business_and_credential(repo, conn, confirmation, state['plan'])
    require_execution_principals(repo, conn, confirmation=confirmation, executor_user_id=row['executor_user_id'],
        expected_epochs={'user_epoch': row['executor_user_epoch'], 'member_epoch': row['executor_member_epoch']})
    _validate_lifetime(confirmation, state['plan'])


def close_zero_attempt(repo, conn, *, company_id, confirmation_id, reason):
    """Retire only a durable never-admitted attempt; caller holds scope locks."""
    lock = ' for update' if repo.database_engine == 'postgres' else ''
    rows = conn.execute(f'select * from confirmation_execution_authorities_v1 where company_id=? and confirmation_id=?{lock}',
                        (company_id, confirmation_id)).fetchall()
    if len(rows) != 1:
        raise PermissionError('ebay_execution_zero_write_not_proven')
    attempt = dict(rows[0])
    state = load_operation_state(attempt['operation_state_json'])
    if (attempt['phase'] not in {'prewrite', 'blocked_before_call'} or attempt['admitted_at'] is not None
            or not valid_operation_state(attempt, state)
            or any(op['status'] != 'planned' for op in state['operations'])):
        raise PermissionError('ebay_execution_zero_write_not_proven')
    conn.execute("update confirmation_execution_authorities_v1 set phase='blocked_before_call',terminal_reason=? where attempt_id=?",
                 (reason, attempt['attempt_id']))
    attempt['phase'] = 'blocked_before_call'
    return recovery(attempt, state, reason=reason)


def _locked_attempt(permit, conn):
    repo = permit._repo
    row = repo._lock_execution_confirmation(conn, company_id=permit._company, confirmation_id=permit._confirmation, require_live_store=False)
    if not row:
        raise PermissionError('ebay_execution_confirmation_missing')
    lock = ' for update' if repo.database_engine == 'postgres' else ''
    attempt = conn.execute(f'select * from confirmation_execution_authorities_v1 where attempt_id=? and company_id=? and confirmation_id=?{lock}',
                            (permit._attempt, permit._company, permit._confirmation)).fetchone()
    if not attempt:
        raise PermissionError('ebay_execution_attempt_missing')
    state = load_operation_state(attempt['operation_state_json'])
    if not valid_operation_state(dict(attempt), state):
        raise PermissionError('ebay_execution_plan_binding_changed')
    return repo._confirmation_row_to_dict(row), dict(attempt), state


def recovery(attempt, state, *, reason=''):
    valid = valid_operation_state(attempt, state)
    operations = state['operations'] if valid else []
    submitted = sum(item.get('status') in {'admitted', 'succeeded', 'unknown'} for item in operations)
    succeeded = sum(item.get('status') == 'succeeded' for item in operations)
    unknown = not valid or any(item.get('status') in {'admitted', 'unknown'} for item in operations)
    reason = reason or str(attempt.get('terminal_reason') or '')
    zero = valid and submitted == 0 and attempt.get('admitted_at') is None and attempt.get('phase') in {'prewrite','blocked_before_call'}
    complete = valid and attempt.get('phase') == 'completed' and succeeded == len(operations)
    expired = zero and expired_zero_prewrite(attempt, state)
    active = zero and attempt.get('phase') == 'prewrite' and not expired
    status = ('execution_completed' if complete else 'execution_in_progress' if active else
        'execution_prewrite_recovery_available' if expired else 'execution_authority_blocked' if zero else 'execution_reconciliation_required')
    next_action = 'view_receipt' if complete else 'wait_for_current_attempt' if active else 'prepare_reapproval' if zero else 'reconcile_read_only'
    message = ('本次操作已完成，请查看原回执；不要重复执行。' if complete else
        '本次请求仍在处理，请等待原请求结果，不要另建确认单或重复执行。' if active else
        '本次尚未提交且等待已超时。可以取消旧请求并重新准备；新确认单仍需单独确认。' if expired else
        '本次权限或内容已变化，未发送。请重新准备并确认。' if zero else
        '已有操作提交或记录尚不完整。请先只读核对结果，不要重复执行。')
    return {'status': status,
        'reason_code': reason, 'confirmation_id': attempt['confirmation_id'], 'store_id': attempt['store_id'],
        'company_id': attempt.get('company_id'),
        'action_type': state['plan'].get('action_type') if valid else '', 'zero_write_proven': zero,
        'submitted_operation_count': submitted, 'completed_operation_count': succeeded,
        'provider_result_unknown': unknown, 'partial_execution': succeeded > 0 and succeeded < len(operations),
        'automatic_retry_allowed': False, 'next_action': next_action,
        'merchant_message': message,
        'secret_exposed': False}


def admit(permit, *, operation_index, method, path, body, marketplace_id, credential):
    repo = permit._repo
    denial = None
    with repo._connect() as conn:
        if repo.database_engine != 'postgres':
            conn.execute('begin immediate')
        confirmation, attempt, state = _locked_attempt(permit, conn)
        # A duplicate caller may not rewrite the original caller's in-flight
        # admission or a terminal result. Reject before the state-change path.
        if (attempt['phase'] != 'prewrite' or type(operation_index) is not int
                or not 0 <= operation_index < len(state['operations'])
                or state['operations'][operation_index]['status'] != 'planned'):
            raise EbayExecutionDenied('ebay_execution_operation_already_admitted_or_out_of_order',
                recovery(attempt, state, reason='ebay_execution_operation_already_admitted_or_out_of_order'))
        try:
            plan = state['plan']
            if (attempt['phase'] != 'prewrite' or type(operation_index) is not int
                    or not 0 <= operation_index < len(plan['operations'])
                    or any(op['status'] != 'succeeded' for op in state['operations'][:operation_index])
                    or any(op['status'] != 'planned' for op in state['operations'][operation_index:])):
                raise PermissionError('ebay_execution_operation_already_admitted_or_out_of_order')
            if (confirmation['status'] != 'external_execution_processing_manual_reconcile'
                    or item_digest(confirmation['item']) != attempt['business_binding_sha256']):
                raise PermissionError('ebay_execution_plan_binding_changed')
            _validate_business_and_credential(repo, conn, confirmation, plan)
            require_execution_principals(repo, conn, confirmation=confirmation, executor_user_id=attempt['executor_user_id'],
                expected_epochs={'user_epoch': attempt['executor_user_epoch'], 'member_epoch': attempt['executor_member_epoch']})
            operation = plan['operations'][operation_index]
            target = operation['target']
            if 'offer_from' in operation:
                index = operation['offer_from']
                previous = state['operations'][index]
                receipt = previous.get('receipt', {})
                if (index != 1 or operation_index != 2 or plan['action_type'] != 'publish_listing'
                        or previous['status'] != 'succeeded' or plan['operations'][index]['kind'] != 'create_offer'
                        or receipt.get('attempt_id') != attempt['attempt_id'] or receipt.get('operation_index') != index
                        or receipt.get('plan_sha256') != attempt['operation_plan_sha256']
                        or receipt.get('binding_sha256') != attempt['business_binding_sha256']):
                    raise PermissionError('ebay_execution_offer_receipt_invalid')
                target = '/sell/inventory/v1/offer/' + segment(receipt.get('offer_id')) + '/publish'
            if (method != operation['method'] or path != target or item_digest(body) != operation['payload_sha256']
                    or marketplace_id != plan['marketplace_id'] or credential != plan['credential']):
                raise PermissionError('ebay_execution_operation_binding_changed')
            _validate_lifetime(confirmation, plan)
            state['operations'][operation_index] = {'status': 'admitted', 'resolved_target': target,
                'admitted_at': datetime.now(timezone.utc).isoformat()}
            conn.execute("update confirmation_execution_authorities_v1 set phase='admitted',operation_state_json=?,admitted_at=? where attempt_id=? and phase='prewrite'",
                          (canonical(state), state['operations'][operation_index]['admitted_at'], attempt['attempt_id']))
        except PermissionError as error:
            if str(error) not in EXECUTION_DENIAL_CODES:
                raise
            zero = not any(op['status'] != 'planned' for op in state['operations']) and attempt.get('admitted_at') is None
            attempt['phase'] = 'blocked_before_call' if zero else 'reconciliation_required'
            summary = recovery(attempt, state, reason=str(error))
            phase = 'blocked_before_call' if summary['zero_write_proven'] else 'reconciliation_required'
            conn.execute('update confirmation_execution_authorities_v1 set phase=?,terminal_reason=?,operation_state_json=? where attempt_id=?',
                         (phase, str(error), canonical(state), attempt['attempt_id']))
            if summary['zero_write_proven']:
                conn.execute("update confirmations set status='needs_revision' where company_id=? and confirmation_id=?",
                             (permit._company, permit._confirmation))
            denial = EbayExecutionDenied(str(error), summary)
    if denial:
        raise denial


def record(permit, *, operation_index, result):
    repo = permit._repo
    with repo._connect() as conn:
        if repo.database_engine != 'postgres':
            conn.execute('begin immediate')
        confirmation, attempt, state = _locked_attempt(permit, conn)
        if (attempt['phase'] != 'admitted' or type(operation_index) is not int
                or not 0 <= operation_index < len(state['operations'])
                or state['operations'][operation_index]['status'] != 'admitted'):
            raise PermissionError('ebay_execution_receipt_already_recorded')
        operation = state['plan']['operations'][operation_index]
        body = result.get('json') if isinstance(result.get('json'), dict) else {}
        code = result.get('http_status')
        known = result.get('status') == 'ok' and type(code) is int and 200 <= code < 300
        receipt = {'attempt_id': attempt['attempt_id'], 'operation_index': operation_index,
                   'plan_sha256': attempt['operation_plan_sha256'], 'binding_sha256': attempt['business_binding_sha256'],
                   'http_status': code if type(code) is int else None}
        required_id = {'create_offer': ('offer_id', 'offerId'), 'publish_offer': ('listing_id', 'listingId')}.get(operation['kind'])
        if known and required_id:
            value = body.get(required_id[1]) or body.get(required_id[0])
            try:
                segment(value)
                receipt[required_id[0]] = value
            except PermissionError:
                known = False
        state['operations'][operation_index].update(status='succeeded' if known else 'unknown', receipt=receipt)
        complete = known and operation_index == len(state['operations']) - 1
        phase = 'completed' if complete else 'prewrite' if known else 'reconciliation_required'
        reason = '' if known else 'ebay_provider_result_unknown'
        conn.execute('update confirmation_execution_authorities_v1 set phase=?,terminal_reason=?,operation_state_json=? where attempt_id=?',
                     (phase, reason, canonical(state), attempt['attempt_id']))
        return {'definite_success': known, 'complete': complete, **({} if known else {'execution_recovery': recovery(attempt, state, reason=reason)})}
