"""Run reconciliation against a fresh loopback-only portable PostgreSQL cluster."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'output/credit-reconcile-deps'))
from jiejing_private_media_credit_reconcile import (apply_reconciliation, load_snapshot, plan_reconciliation, ReconcileBlocked)
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.postgres_repository_runtime import close_postgres_pools


def main():
    import psycopg
    from psycopg.rows import dict_row
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', type=Path, required=True)
    args = parser.parse_args()
    args.pg_bin = args.pg_bin.resolve()
    run = Path(tempfile.mkdtemp(prefix='private-credit-repair-pg-', dir=ROOT/'output'))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    dsn = f'postgresql://credit_probe@127.0.0.1:{port}/postgres'
    evidence = {'passed': False, 'production_accessed': False, 'provider_calls': 0, 'cases': []}

    def pg(name, *items):
        result = subprocess.run([str(args.pg_bin/name), *map(str, items)], cwd=run,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert result.returncode == 0, 'portable_pg_command_failed'

    def connect():
        return psycopg.connect(dsn, row_factory=dict_row, options='-c statement_timeout=8000 -c lock_timeout=3000')

    started = False
    try:
        pg('initdb.exe', '-D', run/'data', '--username=credit_probe', '--auth=trust', '--encoding=UTF8', '--locale=C')
        pg('pg_ctl.exe', '-D', run/'data', '-l', run/'postgres.log', '-w', 'start', '-o',
           f'-h 127.0.0.1 -p {port} -c max_connections=20 -c shared_buffers=32MB')
        started = True
        with patch.dict(os.environ, {'JIEJING_DATABASE_POOL_ENABLED':'false'}, clear=True):
            repo = SaaSRepository(run/'unused.sqlite', database_engine='postgres', database_url=dsn)
            actor = repo.create_user_with_company(email='credit-probe@example.test', password='local-credit-only', company_name='Isolated credits')
            other = repo.create_user_with_company(email='other-probe@example.test', password='local-credit-only', company_name='Other tenant')
            cid, uid = actor['company']['company_id'], actor['user']['user_id']
            scope = {'company_id': cid, 'account_email':'credit-probe@example.test'}
            store = repo.create_store(company_id=cid,user_id=uid,payload={'platform':'ebay','store_name':'Local credit probe','marketplace':'EBAY_US'})
            unrelated_task = repo.create_task(company_id=cid,store_id=store['store_id'],user_id=uid,
                task_type='ebay_inventory_location_setup',title='Unrelated historical task',input_data={})
            repo.apply_media_credit_operation(company_id=cid,user_id=uid,operation_type='grant',points=1000,
                idempotency_key='repair-probe-grant',reference_type='internal_owner_testing',reference_id='repair-probe-owner',
                details={'credit_source':'internal_owner_testing','source_reference_id':'repair-probe-owner','expires_at':'2099-01-01T00:00:00Z'})
            reserve = repo.reserve_media_credit_source(company_id=cid,user_id=uid,source_type='internal_owner_testing',
                source_reference_id='repair-probe-owner',points=180,idempotency_key='repair-probe-reserve',reference_type='media_job',reference_id='local-job')
            repo.apply_media_credit_operation(company_id=cid,user_id=uid,operation_type='settle',points=180,
                idempotency_key='repair-probe-settle',reference_type='media_job',reference_id='local-job',reservation_id=reserve['ledger_entry']['ledger_id'])
            repo.apply_media_credit_operation(company_id=other['company']['company_id'],user_id=other['user']['user_id'],
                operation_type='grant',points=123,idempotency_key='other-tenant-paid-grant',reference_type='purchase',reference_id='local-purchase',
                details={'credit_source':'purchased','source_reference_id':'local-purchase'})
            with connect() as conn:
                assert conn.execute('show listen_addresses').fetchone()['listen_addresses'] == '127.0.0.1'
                bid = conn.execute('select bucket_id from media_credit_buckets where company_id=%s',(cid,)).fetchone()['bucket_id']
                conn.execute("update media_credit_ledger set created_at='2026-09-01T00:00:00Z',updated_at='2026-09-01T00:00:00Z' where company_id=%s",(cid,))
                conn.execute("update media_credit_buckets set expires_at='2026-09-24T00:00:00Z',remaining_points=160,reserved_points=160,status='expiring' where company_id=%s",(cid,))
                conn.execute('update media_credit_accounts set balance_points=40 where company_id=%s',(cid,))
                conn.execute('''insert into media_credit_ledger (ledger_id,company_id,user_id,operation_type,points,status,reference_type,
                    reference_id,reservation_id,idempotency_key_hash,created_at,updated_at,ledger_json)
                    values ('old-expiry',%s,null,'expire',780,'completed','media_credit_bucket',%s,null,'old-expiry-id','2026-09-24T00:00:00Z','2026-09-24T00:00:00Z','{}')''',(cid,bid))
            with connect() as conn:
                before = load_snapshot(conn,**scope); plan = plan_reconciliation(before)
                assert plan['expiry_points'] == 40
                other_before = conn.execute('select * from media_credit_accounts where company_id=%s',(other['company']['company_id'],)).fetchone()
                history = conn.execute('select * from media_credit_ledger where company_id=%s order by ledger_id',(cid,)).fetchall()
            evidence['cases'].append('actual_postgres_snapshot_and_jsonb_projection')
            with connect() as conn:
                conn.execute("update tasks set task_type='provider_job' where task_id=%s",(unrelated_task['task_id'],))
                try:
                    plan_reconciliation(load_snapshot(conn,**scope))
                    raise AssertionError('active_provider_task_not_blocked')
                except ReconcileBlocked as exc:
                    assert str(exc)=='active_jobs_or_missing_check'
                conn.execute("update tasks set task_type='ebay_inventory_location_setup' where task_id=%s",(unrelated_task['task_id'],))
            evidence['cases'].append('provider_task_blocks_but_unrelated_ebay_task_is_not_mutated')
            class FailAtAudit:
                def __init__(self, conn): self.conn=conn
                def execute(self, sql, params=None):
                    if 'insert into audit_logs' in sql: raise RuntimeError('injected_local_failure')
                    return self.conn.execute(sql,params)
            try:
                with connect() as conn:
                    apply_reconciliation(FailAtAudit(conn),**scope,expected_fingerprint=plan['fingerprint'])
                raise AssertionError('rollback_failure_not_injected')
            except RuntimeError as exc:
                assert str(exc) == 'injected_local_failure'
            with connect() as conn:
                assert plan_reconciliation(load_snapshot(conn,**scope))['fingerprint'] == plan['fingerprint']
            evidence['cases'].append('failure_after_ledger_and_bucket_updates_rolls_back_everything')
            for kwargs in ({**scope,'account_email':'other-probe@example.test'}, scope):
                try:
                    with connect() as conn:
                        apply_reconciliation(conn,**kwargs,expected_fingerprint='unreviewed')
                    raise AssertionError('guard_did_not_block')
                except ReconcileBlocked: pass
            evidence['cases'].append('scope_and_changed_fingerprint_block_writes')
            def apply(_):
                with connect() as conn:
                    return apply_reconciliation(conn,**scope,expected_fingerprint=plan['fingerprint'])['status']
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(apply,range(2)))
            assert sorted(statuses) == ['no_op','reconciled']
            with connect() as conn:
                assert plan_reconciliation(load_snapshot(conn,**scope))['status'] == 'no_op'
                assert conn.execute('select count(*) as n from audit_logs where company_id=%s and action_type=%s',(cid,'media_credit.private_expired.reconciled')).fetchone()['n'] == 1
                assert conn.execute('select * from media_credit_ledger where company_id=%s and ledger_id=any(%s) order by ledger_id',(cid,[r['ledger_id'] for r in history])).fetchall() == history
                assert conn.execute('select * from media_credit_accounts where company_id=%s',(other['company']['company_id'],)).fetchone() == other_before
                assert conn.execute('select status,task_type from tasks where task_id=%s',(unrelated_task['task_id'],)).fetchone() == {'status':'queued','task_type':'ebay_inventory_location_setup'}
            evidence['cases'].append('concurrent_apply_idempotent_one_audit_and_all_history_retained')
            evidence['cases'].append('other_tenant_purchased_balance_unchanged')
            # The normal runtime must not turn the former 40-point residue into legacy credits.
            with patch.dict(os.environ, {'JIEJING_OWNER_MEDIA_TESTING_ENABLED':'true','JIEJING_OWNER_MEDIA_TESTING_COMPANY_ALLOWLIST':cid}):
                from jiejing_saas.media_credits import grant_owner_media_testing_points
                grant = grant_owner_media_testing_points(repo,account_email=scope['account_email'],expected_company_id=cid)
                repeat = grant_owner_media_testing_points(repo,account_email=scope['account_email'],expected_company_id=cid)
                assert grant['ok'] and not grant['duplicate_request'] and repeat['duplicate_request']
                account=repo.get_media_credit_account(company_id=cid)
                assert account['balance_points'] == 1000 and account['reserved_points'] == 0
                with connect() as conn:
                    assert conn.execute("select count(*) as n from media_credit_buckets where company_id=%s and source_type='legacy'",(cid,)).fetchone()['n'] == 0
            evidence['cases'].append('normal_owner_monthly_grant_idempotent_no_legacy_credit_created')
            evidence['passed'] = True
    except Exception as exc:
        evidence['error_type'] = type(exc).__name__
        evidence['message'] = str(exc)[:180] if isinstance(exc,(AssertionError,ReconcileBlocked)) else 'local_test_failed'
        import traceback
        evidence['locations']=[{'file':Path(f.filename).name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)[-3:]]
    finally:
        close_postgres_pools()
        if started or (run/'data/postmaster.pid').exists():
            pg('pg_ctl.exe','-D',run/'data','-w','stop','-m','fast')
        evidence['local_postgres_stopped'] = not (run/'data/postmaster.pid').exists()
        evidence['finished_at'] = datetime.now(timezone.utc).isoformat()
        (run/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(json.dumps({**evidence,'safe_receipt':str(run/'evidence.json')},indent=2))
    return 0 if evidence['passed'] and evidence['local_postgres_stopped'] else 1


if __name__ == '__main__': raise SystemExit(main())
