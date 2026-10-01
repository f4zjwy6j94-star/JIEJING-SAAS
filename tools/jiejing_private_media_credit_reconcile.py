"""Narrow, dry-run-first repair for CLOSED, EXPIRED, PRIVATE media credits.

Not a grant/refund API. Refuse purchased/plan/legacy credits, incomplete history,
live reservations, or changed plans. Append expiry evidence; never rewrite history.
The caller owns the PostgreSQL transaction. No provider or platform calls.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os

VERSION = 'closed-private-credit-reconcile-v1'
PRIVATE = {'controlled_acceptance', 'internal_owner_testing'}
ACCOUNT_FIELDS = ('balance_points', 'reserved_points', 'lifetime_granted_points', 'lifetime_spent_points')
BUCKET_FIELDS = ('bucket_id', 'source_type', 'source_reference_id', 'granted_points',
                 'remaining_points', 'reserved_points', 'expires_at', 'status')


class ReconcileBlocked(ValueError):
    """Only fixed, non-secret diagnostic codes belong in this exception."""


def require(condition, code):
    if not condition:
        raise ReconcileBlocked(code)


def points(value):
    require(type(value) is int and value >= 0, 'invalid_points')
    return value


def timestamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'timestamp_timezone_required')
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ReconcileBlocked('invalid_timestamp') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def plan_reconciliation(snapshot, *, now=None):
    now = timestamp(now or datetime.now(timezone.utc))
    require(bool(snapshot.get('company_id')), 'company_required')
    require(snapshot.get('active_provider_jobs') == 0, 'active_jobs_or_missing_check')
    account = {key: points(snapshot['account'][key]) for key in ACCOUNT_FIELDS}
    require(account['reserved_points'] == 0, 'account_reservations_active')
    buckets = sorted(({key: b[key] for key in BUCKET_FIELDS} for b in snapshot['buckets']), key=lambda b: b['bucket_id'])
    require(bool(buckets) and len(buckets) <= 100, 'bucket_scope_invalid')
    by_id = {b['bucket_id']: b for b in buckets}
    require(len(by_id) == len(buckets), 'duplicate_bucket')
    source_map = {}
    for b in buckets:
        require(b['source_type'] in PRIVATE, 'non_private_bucket')
        require(timestamp(b['expires_at']) <= now, 'unexpired_bucket')
        require(b['status'] in {'active', 'consumed', 'expired', 'expiring'}, 'unsupported_bucket_status')
        for key in ('granted_points', 'remaining_points', 'reserved_points'):
            points(b[key])
        require(0 <= b['reserved_points'] <= b['remaining_points'] <= b['granted_points'], 'invalid_bucket_projection')
        key = (b['source_type'], b['source_reference_id'])
        require(key not in source_map, 'duplicate_source')
        source_map[key] = b['bucket_id']
    ledger = sorted(deepcopy(snapshot['ledger']), key=lambda r: r['ledger_id'])
    require(0 < len(ledger) <= 10000 and len({r['ledger_id'] for r in ledger}) == len(ledger), 'ledger_incomplete_or_duplicate')
    reserves, outcomes = {}, {}
    granted, spent, expired = ({bid: 0 for bid in by_id} for _ in range(3))
    grant_ids = set()
    for row in ledger:
        points(row['points'])
        op = row['operation_type']
        require(op in {'grant', 'reserve', 'settle', 'release', 'expire'}, 'unsupported_ledger_operation')
        if op == 'reserve':
            require(row['status'] in {'settled', 'released'}, 'unfinished_reservation')
            allocations = row.get('allocations', [])
            require(len(allocations) == 1, 'complex_or_missing_allocation')
            a = allocations[0]
            require(a.get('bucket_id') in by_id and points(a.get('points')) == row['points'] > 0, 'invalid_allocation')
            reserves[row['ledger_id']] = (row, a['bucket_id'])
            continue
        require(row['status'] == 'completed', 'unfinished_ledger_operation')
        if op == 'grant':
            key = (row.get('credit_source'), row.get('source_reference_id'))
            require(key in source_map and key not in grant_ids, 'grant_source_mismatch')
            require((row.get('reference_type'), row.get('reference_id')) == key, 'grant_reference_mismatch')
            grant_ids.add(key)
            granted[source_map[key]] += row['points']
        elif op == 'expire':
            bid = row.get('reference_id')
            require(row.get('reference_type') == 'media_credit_bucket' and bid in by_id, 'expiry_source_mismatch')
            expired[bid] += row['points']
        else:
            rid = row.get('reservation_id')
            require(rid and rid not in outcomes, 'duplicate_or_missing_outcome')
            outcomes[rid] = row
    require(set(reserves) == set(outcomes), 'orphan_reservation_or_outcome')
    for rid, (reserve, bid) in reserves.items():
        outcome = outcomes[rid]
        require(outcome['operation_type'] + 'd' == reserve['status'], 'outcome_status_mismatch')
        require(outcome['points'] <= reserve['points'], 'outcome_exceeds_reserve')
        require(timestamp(reserve['created_at']) <= timestamp(outcome['created_at']) < timestamp(by_id[bid]['expires_at']), 'outcome_after_expiry_or_bad_order')
        if outcome['operation_type'] == 'settle':
            spent[bid] += outcome['points']
    require(all(granted[bid] == b['granted_points'] for bid, b in by_id.items()), 'bucket_grant_mismatch')
    remaining = {bid: granted[bid] - spent[bid] - expired[bid] for bid in by_id}
    require(all(v >= 0 for v in remaining.values()), 'ledger_overdrawn')
    require(account['balance_points'] == sum(remaining.values()) and
            account['lifetime_granted_points'] == sum(granted.values()) and
            account['lifetime_spent_points'] == sum(spent.values()), 'account_ledger_mismatch')
    plans = [{'bucket_id': b['bucket_id'], 'before': {k: b[k] for k in ('remaining_points', 'reserved_points', 'status')},
              'ledger_remaining_points': remaining[b['bucket_id']],
              'after': {'remaining_points': 0, 'reserved_points': 0, 'status': 'expired'}} for b in buckets]
    # Read-only getters touch updated_at even without financial changes; exclude it.
    normalized_ledger = [{k: v for k, v in r.items() if k != 'updated_at'} for r in ledger]
    fingerprint = digest({'company_id': snapshot['company_id'], 'account': account, 'buckets': buckets, 'ledger': normalized_ledger})
    return {'version': VERSION, 'company_id': snapshot['company_id'], 'fingerprint': fingerprint,
            'status': 'repairable' if any(p['before'] != p['after'] for p in plans) or sum(remaining.values()) else 'no_op',
            'expiry_points': sum(remaining.values()), 'buckets': plans,
            'account_before': account, 'account_after': {**account, 'balance_points': 0, 'reserved_points': 0},
            'provider_calls': 0, 'real_platform_write_performed': False, 'secret_exposed': False}


def load_snapshot(conn, *, company_id, account_email, lock=False):
    scope = conn.execute('select user_id, default_company_id, status from users where lower(email)=%s',
                         (account_email.strip().lower(),)).fetchall()
    require(len(scope) == 1 and scope[0]['default_company_id'] == company_id and scope[0]['status'] == 'active', 'owner_scope_mismatch')
    if lock:
        lock_key = int.from_bytes(hashlib.sha256(f'jiejing-media-credit:{company_id}'.encode()).digest()[:8], 'big', signed=True)
        conn.execute('select pg_advisory_xact_lock(%s)', (lock_key,))
    suffix = ' for update' if lock else ''
    account = conn.execute('select ' + ','.join(ACCOUNT_FIELDS) + ' from media_credit_accounts where company_id=%s' + suffix,
                           (company_id,)).fetchone()
    require(account is not None, 'account_missing')
    buckets = conn.execute('select ' + ','.join(BUCKET_FIELDS) + ' from media_credit_buckets where company_id=%s order by bucket_id limit 101' + suffix,
                           (company_id,)).fetchall()
    ledger = conn.execute('''select ledger_id, operation_type, points, status, reference_type,
        reference_id, reservation_id, created_at,
        coalesce(ledger_json::jsonb #> '{details,allocations}', '[]'::jsonb) as allocations,
        ledger_json::jsonb #>> '{details,credit_source}' as credit_source,
        ledger_json::jsonb #>> '{details,source_reference_id}' as source_reference_id
        from media_credit_ledger where company_id=%s order by ledger_id limit 10001''' + suffix, (company_id,)).fetchall()
    active = conn.execute('''select (
        (select count(*) from queue_jobs where company_id=%s and status in ('preparing','queued','pending','running','retrying','recovering')) +
        (select count(*) from tasks t where company_id=%s and status in ('queued','running','recovering')
            and (task_type='provider_job' or exists (select 1 from media_asset_jobs m where m.task_id=t.task_id and m.company_id=t.company_id))) +
        (select count(*) from media_asset_jobs where company_id=%s and status in ('queued','pending','running','processing','provider_returned','retrying','recovering'))
        ) as count''', (company_id, company_id, company_id)).fetchone()['count']
    return {'company_id': company_id, 'account': account, 'buckets': buckets, 'ledger': ledger,
            'active_provider_jobs': active, 'actor_user_id': scope[0]['user_id']}


def apply_reconciliation(conn, *, company_id, account_email, expected_fingerprint, now=None):
    require(bool(expected_fingerprint), 'reviewed_fingerprint_required')
    snapshot = load_snapshot(conn, company_id=company_id, account_email=account_email, lock=True)
    now = timestamp(now or datetime.now(timezone.utc))
    plan = plan_reconciliation(snapshot, now=now)
    if plan['status'] == 'no_op':
        return plan
    require(plan['fingerprint'] == expected_fingerprint, 'plan_changed')
    stamp = now.isoformat()
    for b in plan['buckets']:
        residual = b['ledger_remaining_points']
        if residual:
            key = digest(f'{VERSION}:{company_id}:{b["bucket_id"]}')
            entry = {'contract_version': VERSION, 'operation_type': 'expire', 'details': {
                'reason': 'closed_expired_private_credit_reconciliation', 'plan_fingerprint': plan['fingerprint'],
                'bucket_id': b['bucket_id'], 'prior_projection': b['before'], 'authoritative_residual': residual}, 'secret_exposed': False}
            conn.execute('''insert into media_credit_ledger (ledger_id,company_id,user_id,operation_type,points,status,
                reference_type,reference_id,reservation_id,idempotency_key_hash,created_at,updated_at,ledger_json)
                values (%s,%s,%s,'expire',%s,'completed','media_credit_bucket',%s,null,%s,%s,%s,%s)''',
                ('mcredit_reconcile_' + key[:24], company_id, snapshot['actor_user_id'], residual, b['bucket_id'], key, stamp, stamp, json.dumps(entry)))
        conn.execute("update media_credit_buckets set remaining_points=0,reserved_points=0,status='expired',updated_at=%s where company_id=%s and bucket_id=%s",
                     (stamp, company_id, b['bucket_id']))
    conn.execute('update media_credit_accounts set balance_points=0,reserved_points=0,updated_at=%s where company_id=%s', (stamp, company_id))
    conn.execute('''insert into audit_logs (audit_id,company_id,store_id,user_id,actor_type,action_type,target_type,target_id,summary,created_at,audit_json)
        values (%s,%s,null,%s,'platform_internal_admin','media_credit.private_expired.reconciled','media_credit_account',%s,%s,%s,%s)''',
        ('audit_reconcile_' + plan['fingerprint'][:24], company_id, snapshot['actor_user_id'], company_id,
         'Reconciled closed expired private credits from retained ledger; no grant or customer balance changes.', stamp, json.dumps(plan, default=str)))
    after = plan_reconciliation(load_snapshot(conn, company_id=company_id, account_email=account_email), now=now)
    require(after['status'] == 'no_op', 'postcondition_failed')
    return {**plan, 'status': 'reconciled', 'postcondition': 'verified', 'history_retained': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-email', required=True)
    parser.add_argument('--company-id', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-fingerprint')
    args = parser.parse_args(argv)
    try:
        import psycopg
        from psycopg.rows import dict_row
        options = '-c statement_timeout=15000 -c lock_timeout=5000'
        if not args.apply:
            options += ' -c default_transaction_read_only=on'
        with psycopg.connect(os.environ['JIEJING_DATABASE_URL'], row_factory=dict_row, connect_timeout=8, options=options) as conn:
            if args.apply:
                result = apply_reconciliation(conn, company_id=args.company_id, account_email=args.account_email,
                                              expected_fingerprint=args.expected_fingerprint)
            else:
                require(conn.execute('show transaction_read_only').fetchone()['transaction_read_only'] == 'on', 'read_only_required')
                result = plan_reconciliation(load_snapshot(conn, company_id=args.company_id, account_email=args.account_email))
                result['read_only'] = True
        print(json.dumps(result, sort_keys=True, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'code': str(exc) if isinstance(exc, ReconcileBlocked) else type(exc).__name__, 'secret_exposed': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
