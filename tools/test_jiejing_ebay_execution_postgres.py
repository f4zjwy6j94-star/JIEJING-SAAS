#!/usr/bin/env python3
"""Owned-PG B1 authority/operation races. No external provider transport."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import copy
import json
from pathlib import Path
import sys
from threading import Barrier,Event,local
import time
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_jiejing_support_postgres as owned
import test_jiejing_ebay_dual_principals as dual
from jiejing_runtime.execution import ExecutionService
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter,build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
import jiejing_saas.ebay_execution_authority as authority
from jiejing_saas.postgres_repository_runtime import PostgresConnectionAdapter,close_postgres_pools


class ExecutionPostgresTests(dual.DualPrincipalTests):
    """Ten original dual-principal cases plus actual deterministic PG races."""
    def setUp(self):
        database='b1_'+uuid.uuid4().hex[:16]
        with owned.psycopg.connect(owned.ADMIN_DSN,autocommit=True) as conn:
            conn.execute(owned.psycopg.sql.SQL('create database {}').format(owned.psycopg.sql.Identifier(database)))
        self.dsn=owned.ADMIN_DSN.rsplit('/',1)[0]+'/'+database
        from jiejing_saas.infrastructure_drivers import run_postgres_migration
        self.assertEqual(run_postgres_migration(database_url=self.dsn)['status'],'ok')
        from jiejing_saas.repository import SaaSRepository
        self.directory=owned.RUN
        self.repo=SaaSRepository(owned.RUN/'unused.sqlite',database_engine='postgres',database_url=self.dsn)
        account=self.repo.create_user_with_company(email='b1-pg@example.test',password='synthetic-only',company_name='B1 PG')
        self.company=account['company']['company_id'];self.user=account['user']['user_id']
        self.store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        self.epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company)

    def tearDown(self): close_postgres_pools()

    def attempt(self,permit):
        with self.repo._connect() as conn:
            row=dict(conn.execute('select * from confirmation_execution_authorities_v1 where attempt_id=?',(permit._attempt,)).fetchone())
        return row,json.loads(row['operation_state_json'])

    def denial(self):
        return self.repo._record_ebay_preclaim_denial(company_id=self.company,store_id=self.store,
            confirmation_id=self.record['confirmation_id'],expected_confirmation=self.record,
            reason_code='execution_request_authority_required')

    def denial_history(self):
        with self.repo._connect() as conn:
            audit=[dict(row) for row in conn.execute('select * from audit_logs order by audit_id').fetchall()]
            approvals=[dict(row) for row in conn.execute('select * from confirmation_approval_authorities_v1 order by authority_id').fetchall()]
        return audit,approvals

    def assert_denial_history(self,before,count):
        audit,approvals=self.denial_history();self.assertEqual(approvals,before[1])
        self.assertTrue(all(row in audit for row in before[0]),'Every original audit row must remain byte-for-byte equivalent')
        denied=[row for row in audit if row['action_type']=='external_execution.preclaim_denied']
        self.assertEqual(len(denied),count)
        if count:
            row=denied[0];audit_value=row['audit_json']
            details=(json.loads(audit_value) if isinstance(audit_value,str) else audit_value)['details']
            self.assertEqual((row['company_id'],row['store_id'],row['target_type'],row['target_id']),
                (self.company,self.store,'confirmation',self.record['confirmation_id']))
            self.assertEqual(details,{**self.repo._ebay_preclaim_denial_binding(self.record),
                'reason_code':'execution_request_authority_required','secret_exposed':False})

    def test_denial_binding_matches_native_pg_and_api_aware_instant_without_history_changes(self):
        from jiejing_saas.json_safe import json_default
        self.actors();before=self.denial_history();original=copy.deepcopy(self.record)
        with self.repo._connect() as conn:
            original_binding=conn.execute('select approval_authority_id from confirmations where company_id=? and confirmation_id=?',
                (self.company,self.record['confirmation_id'])).fetchone()['approval_authority_id']
        self.assertTrue(original_binding,'The original internal approval binding must exist')
        native=self.record['decided_at'];self.assertIsInstance(native,datetime);self.assertIsNotNone(native.utcoffset())
        api_record=json.loads(json.dumps(self.record,default=json_default))
        expected=self.repo._ebay_preclaim_denial_binding(self.record)
        for stamp in (api_record['decided_at'],native.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
                native.astimezone(timezone(timedelta(hours=8))).isoformat()):
            with self.subTest(aware=stamp):
                self.assertEqual(self.repo._ebay_preclaim_denial_binding({**api_record,'decided_at':stamp}),expected)
        for stamp in (None,'unknown',native.replace(tzinfo=None),native.replace(tzinfo=None).isoformat(),[],{}):
            with self.subTest(invalid=repr(stamp)),self.assertRaisesRegex(PermissionError,'approval_authority_binding_changed_reapproval_required'):
                self.repo._record_ebay_preclaim_denial(company_id=self.company,store_id=self.store,
                    confirmation_id=self.record['confirmation_id'],expected_confirmation={**api_record,'decided_at':stamp},
                    reason_code='execution_request_authority_required')
            self.assertEqual(self.denial_history(),before)
        summary=self.repo._record_ebay_preclaim_denial(company_id=self.company,store_id=self.store,
            confirmation_id=self.record['confirmation_id'],expected_confirmation=api_record,
            reason_code='execution_request_authority_required')
        self.assertTrue(summary['zero_write_proven']);self.assert_denial_history(before,1)
        self.assertEqual(self.record,original)
        current=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        for key in ('item','decided_by','decided_at','decision_note'):
            self.assertEqual(current[key],original[key])
        history_after_denial=self.denial_history()
        with self.assertRaisesRegex(PermissionError,'execution_request_authority_required'): self.claim()
        self.assertEqual(self.denial_history(),history_after_denial)
        with self.repo._connect() as conn:
            current_binding=conn.execute('select approval_authority_id from confirmations where company_id=? and confirmation_id=?',
                (self.company,self.record['confirmation_id'])).fetchone()['approval_authority_id']
        self.assertEqual(current_binding,original_binding)

    def test_concurrent_preclaim_denials_append_exactly_one_safe_event(self):
        self.actors()
        with self.assertRaisesRegex(PermissionError,'execution_request_authority_required'): self.claim(epochs=False)
        before=self.denial_history();barrier=Barrier(2)
        def denied(): barrier.wait(5);return self.denial()
        with ThreadPoolExecutor(max_workers=2) as pool:
            left=pool.submit(denied);right=pool.submit(denied);results=[left.result(15),right.result(15)]
        self.assertTrue(all(row['zero_write_proven'] for row in results));self.assert_denial_history(before,1)
        snapshot=self.denial_history()
        for _ in range(3):
            self.denial();self.repo.list_confirmations(company_id=self.company)
            with self.assertRaisesRegex(PermissionError,'execution_request_authority_required'): self.claim()
        self.assertEqual(self.denial_history(),snapshot)

    def denial_claim_lock_race(self,first_role):
        self.actors()
        with self.assertRaisesRegex(PermissionError,'execution_request_authority_required'): self.claim(epochs=False)
        before=self.denial_history();locked,release,waiting=Event(),Event(),Event();thread_state=local();pid=[]
        original=PostgresConnectionAdapter.execute
        def observed(conn,sql,params=()):
            target=' '.join(sql.lower().split())=='select stage from stores where company_id=? and store_id=? for update'
            role=getattr(thread_state,'role','')
            if target and role and role!=first_role:
                pid.append(original(conn,'select pg_backend_pid() as pid').fetchone()['pid']);waiting.set()
            result=original(conn,sql,params)
            if target and role==first_role:
                locked.set();self.assertTrue(release.wait(10))
            return result
        def run(role):
            thread_state.role=role
            try: return self.denial() if role=='denial' else self.claim()
            except PermissionError as error: return str(error)
        with patch.object(PostgresConnectionAdapter,'execute',observed),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(run,first_role);self.assertTrue(locked.wait(10))
            second=pool.submit(run,'claim' if first_role=='denial' else 'denial')
            try:
                self.assertTrue(waiting.wait(10));deadline=time.monotonic()+5;blocked=False
                while time.monotonic()<deadline:
                    with owned.psycopg.connect(self.dsn) as conn:
                        blocked=conn.execute('select wait_event_type from pg_stat_activity where pid=%s',(pid[0],)).fetchone()[0]=='Lock'
                    if blocked: break
                    time.sleep(.01)
                self.assertTrue(blocked,'The competing transaction must actually wait on the existing PG store lock')
            finally: release.set()
            first_result=first.result(15);second_result=second.result(15)
        if first_role=='denial':
            self.assertEqual(second_result,'execution_request_authority_required');self.assertTrue(first_result['zero_write_proven'])
            self.assert_denial_history(before,1)
            with self.repo._connect() as conn:
                self.assertEqual(conn.execute('select count(*) as n from confirmation_execution_authorities_v1').fetchone()['n'],0)
        else:
            self.assertEqual(second_result['next_action'],'wait_for_current_attempt');self.assert_denial_history(before,0)
            permit=first_result['_execution_permit']
            self.assertEqual(self.send(permit,self.successful)['status'],'published_to_ebay')
            self.assertEqual(self.attempt(permit)[0]['phase'],'completed')

    def test_preclaim_denial_commit_first_blocks_waiting_claim(self): self.denial_claim_lock_race('denial')
    def test_claim_commit_first_cannot_be_replaced_by_zero_write_denial(self): self.denial_claim_lock_race('claim')

    def test_admitted_and_unknown_transport_never_append_zero_write_denial(self):
        self.actors();permit=self.claim()['_execution_permit'];arrived,release=Event(),Event();calls=[]
        def transport(request,timeout):
            calls.append(request.get_method());arrived.set();self.assertTrue(release.wait(10));raise TimeoutError('Synthetic unknown')
        before=self.denial_history()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.send,permit,transport)
            try:
                self.assertTrue(arrived.wait(10));self.assertEqual(self.attempt(permit)[0]['phase'],'admitted')
                summary=self.denial();self.assertFalse(summary['zero_write_proven'])
                self.assertEqual(summary['next_action'],'reconcile_read_only');self.assert_denial_history(before,0)
            finally: release.set()
            self.assertEqual(pending.result(15)['status'],'blocked_platform_error')
        snapshot=self.denial_history();summary=self.denial()
        self.assertFalse(summary['zero_write_proven']);self.assertTrue(summary['provider_result_unknown'])
        self.assertEqual(self.denial_history(),snapshot);self.assertEqual(calls,['PUT'])
        self.assertEqual(self.attempt(permit)[0]['phase'],'reconciliation_required')

    def send(self,permit,transport,token_hook=None):
        adapter=EbayWriteHttpAdapter(self.settings,transport=transport)
        def token(**_):
            if token_hook: token_hook()
            return {'ok':True,'access_token':'B1-SYNTHETIC-PG','source':'injected'}
        with patch.object(adapter,'_resolve_access_token',side_effect=token):
            return adapter.publish_listing(request=self.request,preflight=ExecutionService(demo_mode=False).preflight(self.request),
                connections=[self.connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=permit)

    @staticmethod
    def successful(request,timeout): return 200,{},b'{"offerId":"offer-pg","listingId":"listing-pg"}'

    def replacement(self,**overrides):
        args=dict(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-pg-reprepare',
            action_type='publish_listing',title='B1 PG exact replacement',item=copy.deepcopy(self.record['item']),
            created_by=self.user,replaces_confirmation_id=self.record['confirmation_id'])
        args.update(overrides)
        return self.repo.create_confirmation(**args)

    def expired_clock(self,permit):
        row,_=self.attempt(permit)
        stamp=row['created_at']
        self.assertIsInstance(stamp,str,'Repository normalizes persisted timestamps to ISO text')
        stamp=datetime.fromisoformat(stamp)
        self.assertIsNotNone(stamp.tzinfo)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                value=stamp+timedelta(seconds=61)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        return patch.object(authority,'datetime',Clock)

    def test_native_postgres_aware_timestamp_exact_recovery_boundary(self):
        self.actors();permit=self.claim()['_execution_permit'];row,state=self.attempt(permit)
        with owned.psycopg.connect(self.dsn) as conn:
            stamp=conn.execute('select created_at::timestamptz from confirmation_execution_authorities_v1 where attempt_id=%s',
                (permit._attempt,)).fetchone()[0]
        self.assertIsInstance(stamp,datetime);self.assertIsNotNone(stamp.utcoffset())
        row['created_at']=stamp
        for elapsed,eligible in ((60,False),(60.000001,True)):
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None): return (stamp+timedelta(seconds=elapsed)).astimezone(tz)
            with self.subTest(elapsed=elapsed),patch.object(authority,'datetime',Clock):
                self.assertEqual(authority.expired_zero_prewrite(row,state),eligible)

    def test_final_write_admission_is_durable_and_no_database_locks_cross_transport(self):
        self.actors();permit=self.claim()['_execution_permit'];calls=[]
        def transport(request,timeout):
            row,state=self.attempt(permit);index=len(calls)
            self.assertEqual(row['phase'],'admitted');self.assertEqual(state['operations'][index]['status'],'admitted')
            with owned.psycopg.connect(self.dsn) as conn:
                conn.execute('select store_id from stores where store_id=%s for update nowait',(self.store,))
                for user in sorted(person[0] for person in self.people.values()):
                    conn.execute('select user_id from users where user_id=%s for update nowait',(user,))
                    conn.execute('select user_id from team_members where company_id=%s and user_id=%s for update nowait',(self.company,user))
            calls.append(request.get_method());return self.successful(request,timeout)
        self.assertEqual(self.send(permit,transport)['status'],'published_to_ebay')
        self.assertEqual(calls,['PUT','POST','POST'])

    def test_revoke_commit_before_final_admission_blocks_actual_transport(self):
        self.actors();permit=self.claim()['_execution_permit'];target=self.people['approver'][0]
        revoked_lock,release,admission_waiting=Event(),Event(),Event();thread_state=local();calls=[];pid=[]
        original=PostgresConnectionAdapter.execute
        def observed(conn,sql,params=()):
            normalized=' '.join(sql.lower().split())
            if getattr(thread_state,'role','')=='admit' and normalized=='select status from users where user_id=? for update' and params[0]==target:
                pid.append(original(conn,'select pg_backend_pid() as pid').fetchone()['pid']);admission_waiting.set()
            result=original(conn,sql,params)
            if getattr(thread_state,'role','')=='revoke' and normalized=='select status, default_company_id from users where user_id = ? for update':
                revoked_lock.set();self.assertTrue(release.wait(10))
            return result
        def revoke():
            thread_state.role='revoke';self.repo.set_user_access_status(user_id=target,status='disabled')
        def send():
            thread_state.role='admit'
            return self.send(permit,lambda req,timeout:(calls.append(req.get_method()) or self.successful(req,timeout)))
        with patch.object(PostgresConnectionAdapter,'execute',observed),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(revoke);self.assertTrue(revoked_lock.wait(10));second=pool.submit(send)
            try:
                self.assertTrue(admission_waiting.wait(10))
                deadline=time.monotonic()+5;blocked=False
                while time.monotonic()<deadline:
                    with owned.psycopg.connect(self.dsn) as conn:
                        blocked=conn.execute('select wait_event_type from pg_stat_activity where pid=%s',(pid[0],)).fetchone()[0]=='Lock'
                    if blocked: break
                    time.sleep(.01)
                self.assertTrue(blocked,'Actual PG admission did not wait behind the revocation lock')
            finally: release.set()
            first.result(timeout=15)
            with self.assertRaises(EbayExecutionDenied): second.result(timeout=15)
        self.assertEqual(calls,[]);self.assertEqual(self.attempt(permit)[0]['phase'],'blocked_before_call')

    def test_admission_first_preserves_inflight_receipt_after_revocation(self):
        self.actors();permit=self.claim()['_execution_permit'];arrived,release=Event(),Event();calls=[]
        def transport(request,timeout):
            calls.append(request.get_method());arrived.set();self.assertTrue(release.wait(10));return self.successful(request,timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.send,permit,transport)
            try:
                self.assertTrue(arrived.wait(10));self.assertEqual(self.attempt(permit)[0]['phase'],'admitted')
                self.repo.set_user_access_status(user_id=self.people['executor'][0],status='disabled')
            finally: release.set()
            with self.assertRaises(EbayExecutionDenied): future.result(timeout=15)
        row,state=self.attempt(permit)
        self.assertEqual(calls,['PUT']);self.assertEqual(state['operations'][0]['status'],'succeeded')
        self.assertEqual(row['phase'],'reconciliation_required')

    def test_duplicate_inflight_does_not_erase_first_receipt_or_completion(self):
        self.actors();permit=self.claim()['_execution_permit'];arrived,release=Event(),Event();calls=[]
        def transport(request,timeout):
            calls.append(request.get_method())
            if len(calls)==1: arrived.set();self.assertTrue(release.wait(10))
            return self.successful(request,timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.send,permit,transport)
            try:
                self.assertTrue(arrived.wait(10))
                with self.assertRaises(EbayExecutionDenied): self.send(permit,lambda *_:self.fail('Duplicate reached transport'))
            finally: release.set()
            self.assertEqual(future.result(timeout=15)['status'],'published_to_ebay')
        self.assertEqual(calls,['PUT','POST','POST']);self.assertEqual(self.attempt(permit)[0]['phase'],'completed')
        with self.assertRaises(EbayExecutionDenied): self.send(permit,lambda *_:self.fail('Completed request replayed'))
        self.assertEqual(self.attempt(permit)[0]['phase'],'completed')

    def test_principal_lock_trace_is_all_sorted_users_before_all_sorted_members(self):
        self.actors();permit=self.claim()['_execution_permit'];trace=[];original=PostgresConnectionAdapter.execute
        def observed(conn,sql,params=()):
            normalized=' '.join(sql.lower().split())
            if normalized=='select status from users where user_id=? for update': trace.append(('user',params[0]))
            if normalized=='select role from team_members where company_id=? and user_id=? for update': trace.append(('member',params[1]))
            return original(conn,sql,params)
        with patch.object(PostgresConnectionAdapter,'execute',observed): self.send(permit,self.successful)
        users=sorted(person[0] for person in self.people.values())
        expected=[('user',user) for user in users]+[('member',user) for user in users]
        self.assertEqual(trace,expected*3)

    def test_two_new_ids_cannot_claim_same_resource_concurrently(self):
        self.actors();first_record=copy.deepcopy(self.record);first_request=self.request
        second=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-pg-other',
            action_type='publish_listing',title='Other explicit approval same SKU',item=copy.deepcopy(first_record['item']))
        second=self.repo.decide_confirmation(company_id=self.company,confirmation_id=second['confirmation_id'],decision='approve',
            decided_by=self.people['approver'][0],note='Synthetic second approval',
            expected_access_epochs=self.repo.access_session_epochs(user_id=self.people['approver'][0],company_id=self.company))
        barrier=Barrier(2)
        def claim(record):
            request=replace(first_request,confirmation_id=record['confirmation_id'],confirmed_at=record['decided_at'])
            plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[self.connection]);barrier.wait(5)
            try:
                return self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],
                    user_id=self.people['executor'][0],expected_access_epochs=self.executor_epochs,operation_plan=plan)
            except PermissionError as error: return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left=pool.submit(claim,first_record);right=pool.submit(claim,second);results=[left.result(15),right.result(15)]
        self.assertEqual(sum(isinstance(item,dict) for item in results),1)
        self.assertIn('ebay_execution_prior_outcome_unresolved',results)

    def test_receipt_transaction_failure_keeps_durable_admitted_no_replay(self):
        self.actors();permit=self.claim()['_execution_permit'];calls=[];original=PostgresConnectionAdapter.execute
        def observed(conn,sql,params=()):
            result=original(conn,sql,params)
            if sql.lower().startswith('update confirmation_execution_authorities_v1 set phase=?,terminal_reason=?,operation_state_json=?'):
                raise RuntimeError('Synthetic receipt persistence failure')
            return result
        with patch.object(PostgresConnectionAdapter,'execute',observed),self.assertRaisesRegex(RuntimeError,'receipt persistence'):
            self.send(permit,lambda req,timeout:(calls.append(req.get_method()) or self.successful(req,timeout)))
        row,state=self.attempt(permit);self.assertEqual(row['phase'],'admitted');self.assertEqual(calls,['PUT'])
        self.assertEqual(state['operations'][0]['status'],'admitted')
        with self.expired_clock(permit),self.assertRaises(PermissionError): self.replacement()
        with self.assertRaises(EbayExecutionDenied): self.send(permit,lambda *_:self.fail('Unknown request replayed'))

    def test_zero_replacement_commit_first_blocks_delayed_original_transport(self):
        self.actors();permit=self.claim()['_execution_permit'];token_wait,release=Event(),Event();calls=[]
        def token(): token_wait.set();self.assertTrue(release.wait(10))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.send,permit,lambda req,timeout:(calls.append(req.get_method()) or self.successful(req,timeout)),token)
            try:
                self.assertTrue(token_wait.wait(10))
                with self.expired_clock(permit): new=self.replacement()
                self.assertEqual(new['status'],'pending');self.assertEqual(self.attempt(permit)[0]['phase'],'blocked_before_call')
            finally: release.set()
            with self.assertRaises(EbayExecutionDenied): future.result(timeout=15)
        self.assertEqual(calls,[])

    def test_admission_commit_first_blocks_expired_zero_replacement(self):
        self.actors();permit=self.claim()['_execution_permit'];arrived,release=Event(),Event()
        def transport(request,timeout):
            arrived.set();self.assertTrue(release.wait(10));return self.successful(request,timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.send,permit,transport)
            try:
                self.assertTrue(arrived.wait(10))
                with self.expired_clock(permit),self.assertRaises(PermissionError): self.replacement()
            finally: release.set()
            self.assertEqual(future.result(timeout=15)['status'],'published_to_ebay')

    def test_concurrent_expired_replacements_create_one_pending_and_list_exact_link(self):
        self.actors();permit=self.claim()['_execution_permit'];barrier=Barrier(2)
        def replace_once():
            barrier.wait(5)
            try: return self.replacement()
            except PermissionError as error: return str(error)
        with self.expired_clock(permit),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(replace_once);second=pool.submit(replace_once);results=[first.result(15),second.result(15)]
        records=[value for value in results if isinstance(value,dict)]
        self.assertEqual(len(records),1);self.assertEqual(records[0]['status'],'pending')
        listed=self.repo.list_confirmations(company_id=self.company)
        old=next(row for row in listed if row['confirmation_id']==self.record['confirmation_id'])
        self.assertEqual(old['execution_recovery']['replacement_confirmation_id'],records[0]['confirmation_id'])

    def scoped_lifetime_lock_wait(self, *, draft, expire):
        """Actual final admission waits behind a PG principal lock, after GET/consume."""
        from test_jiejing_new_ebay_account_publish_http_chain import _seed_exact_draft_callback
        from test_jiejing_ebay_write_adapter import attach_publish_evidence
        self.actors()
        # A separately authorized synthetic seller/store, not an identity swap
        # over the unrelated legacy connection used by the inherited controls.
        self.store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        self.request=replace(self.request,store_id=self.store)
        credential=_seed_exact_draft_callback(self.settings,self.repo,company_id=self.company,store_id=self.store,user_id=self.user)
        self.settings.requested_real_platform_writes=False;self.settings.ebay_write_live_enabled=False
        self.settings.ebay_draft_save_live_enabled=True;self.settings.ebay_controlled_publish_live_enabled=True
        self.settings.ebay_read_only_live_enabled=True
        payload=copy.deepcopy(self.request.payload)
        attach_publish_evidence(payload,company_id=self.company,store_id=self.store)
        action='save_ebay_listing_draft' if draft else 'publish_listing'
        source='merchant_ebay_draft_save_intake' if draft else 'merchant_existing_ebay_draft_publish_intake'
        if not draft:
            payload['existing_ebay_draft']={'offer_id':'offer-clock','sku':payload['listing']['sku'],
                'offer_status':'UNPUBLISHED','public_listing_created':False,
                'source_execution_id':'synthetic-clock-receipt','source_confirmation_id':self.record['confirmation_id']}
        task=self.repo.create_task(company_id=self.company,store_id=self.store,user_id=self.user,
            task_type='ebay_draft_save_intake',title='Scoped clock wait',input_data={})
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=task['task_id'],
            runtime_run_id=source,action_type=action,title='Scoped clock wait',item={'source':source,
                'company_id':self.company,'store_id':self.store,'draft_save_capability_requested':True,
                'writes_to_ebay_after_approval':True,'public_publish_enabled':False,'real_platform_writes_enabled':False,
                'publish_payload':payload,'publish_payload_sha256':authority.item_digest(payload)})
        approver=self.people['approver'][0]
        record=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],decision='approve',
            decided_by=approver,note='Clock wait original approval.',expected_access_epochs=self.repo.access_session_epochs(user_id=approver,company_id=self.company))
        request=replace(self.request,action_type=action,task_id=task['task_id'],confirmation_id=record['confirmation_id'],
            confirmed_at=record['decided_at'],payload=payload)
        calls=[]
        def transport(http_request,timeout):
            method=http_request.get_method();calls.append(method)
            if http_request.full_url.endswith('/kyc'): return 204,{},b''
            if method=='GET': return 200,{},json.dumps({'offers':[] if draft else [
                {'offerId':'offer-clock','marketplaceId':'EBAY_US','status':'UNPUBLISHED'}]}).encode()
            return 200,{},b'{"offerId":"offer-clock","listingId":"listing-clock"}'
        adapter=EbayWriteHttpAdapter(self.settings,transport=transport)
        adapter._resolve_access_token=lambda **_:{'ok':True,'access_token':'SYNTHETIC-CLOCK','source':'injected'}
        preflight=ExecutionService(demo_mode=False).preflight(request)
        self.assertEqual(preflight['status'],'ready_for_platform_adapter')
        if draft:
            prepared=adapter.prepare_listing_draft(request=request,preflight=preflight,credential_boundary=credential,marketplace_id='EBAY_US')
            _,capability=self.repo.claim_unpublished_draft_execution(company_id=self.company,confirmation_id=record['confirmation_id'],
                user_id=request.user_id,expected_access_epochs=self.executor_epochs,expected_binding=prepared.claim_binding(),operation_plan=prepared.execution_plan())
            permit=capability.execution_permit()
            def send():
                return adapter.execute_prepared_listing_draft(request=request,preflight=preflight,prepared=prepared,
                    claim_capability=capability,marketplace_id='EBAY_US')
        else:
            permit=self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],
                user_id=request.user_id,expected_access_epochs=self.executor_epochs,operation_plan=build_ebay_execution_plan(
                    request=request,marketplace_id='EBAY_US',credential_boundary=credential))['_execution_permit']
            def send():
                return adapter.publish_existing_listing_draft(request=request,preflight=preflight,credential_boundary=credential,
                    marketplace_id='EBAY_US',expected_offer_id='offer-clock',execution_permit=permit)
        ready,continue_admit,waiting=Event(),Event(),Event();elapsed=[0];pid=[]
        target=min(person[0] for person in self.people.values())
        original_admit=authority.EbayWritePermit.admit;original_execute=PostgresConnectionAdapter.execute
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return datetime.now(tz)+timedelta(seconds=elapsed[0])
        def before_admit(this,**kwargs):
            if kwargs['operation_index']==0:
                ready.set();self.assertTrue(continue_admit.wait(10))
            return original_admit(this,**kwargs)
        def observed(conn,sql,params=()):
            if (ready.is_set() and ' '.join(sql.lower().split())=='select status from users where user_id=? for update'
                    and params[0]==target and not waiting.is_set()):
                pid.append(original_execute(conn,'select pg_backend_pid() as pid').fetchone()['pid']);waiting.set()
            return original_execute(conn,sql,params)
        with patch.object(authority,'datetime',Clock),patch.object(authority.EbayWritePermit,'admit',before_admit), \
                patch.object(PostgresConnectionAdapter,'execute',observed),owned.psycopg.connect(self.dsn) as held,ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(send)
            try:
                self.assertTrue(ready.wait(10),'Actual write admission was not reached')
                held.execute('select user_id from users where user_id=%s for update',(target,));continue_admit.set()
                self.assertTrue(waiting.wait(10))
                deadline=time.monotonic()+5;blocked=False
                while time.monotonic()<deadline:
                    with owned.psycopg.connect(self.dsn) as conn:
                        blocked=conn.execute('select wait_event_type from pg_stat_activity where pid=%s',(pid[0],)).fetchone()[0]=='Lock'
                    if blocked: break
                    time.sleep(.01)
                self.assertTrue(blocked,'The final admission did not actually wait on PostgreSQL')
                elapsed[0]=(31 if draft else 901) if expire else 1
            finally: continue_admit.set();held.rollback()
            if expire:
                with self.assertRaises(EbayExecutionDenied): pending.result(15)
            else:
                self.assertEqual(pending.result(15)['status'],'saved_to_ebay_draft' if draft else 'published_to_ebay')
        self.assertEqual([method for method in calls if method!='GET'],[] if expire else ['PUT','POST'] if draft else ['POST'])
        row,state=self.attempt(permit)
        self.assertEqual(row['phase'],'blocked_before_call' if expire else 'completed')

    def test_pg_draft_preparation_expiry_after_principal_lock_wait(self): self.scoped_lifetime_lock_wait(draft=True,expire=True)
    def test_pg_draft_principal_lock_wait_normal_control(self): self.scoped_lifetime_lock_wait(draft=True,expire=False)
    def test_pg_existing_approval_expiry_after_principal_lock_wait(self): self.scoped_lifetime_lock_wait(draft=False,expire=True)
    def test_pg_existing_principal_lock_wait_normal_control(self): self.scoped_lifetime_lock_wait(draft=False,expire=False)

    def verified_deletion(self):
        event=self.repo.accept_ebay_account_deletion_event(event={'event_key':'a'*64,'payload_sha256':'b'*64,
            'user_id_hash':self.connection['metadata']['ebay_user_id_hash'],'topic':'MARKETPLACE_ACCOUNT_DELETION',
            'schema_version':'1.0','signature_present':True},verification={'verified':True,'status':'verified'})
        self.repo.claim_next_queue_job(company_id=self.company,job_id=event['job_id'])
        return {key:event[key] for key in ('event_key','company_id','store_id','connection_id','task_id','job_id')}

    def test_verified_deletion_commit_first_blocks_delayed_write(self):
        self.actors();permit=self.claim()['_execution_permit'];event=self.verified_deletion()
        token_wait,release=Event(),Event();calls=[]
        def token(): token_wait.set();self.assertTrue(release.wait(10))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.send,permit,lambda req,timeout:(calls.append(req.get_method()) or self.successful(req,timeout)),token)
            try:
                self.assertTrue(token_wait.wait(10))
                self.assertEqual(self.repo.claim_ebay_account_deletion_processing(**event)['phase'],'claimed')
            finally: release.set()
            with self.assertRaises(EbayExecutionDenied): pending.result(15)
        self.assertEqual(calls,[]);self.assertEqual(self.attempt(permit)[0]['phase'],'blocked_before_call')

    def test_admitted_write_preserves_receipt_when_verified_deletion_commits(self):
        self.actors();permit=self.claim()['_execution_permit'];event=self.verified_deletion()
        arrived,release=Event(),Event();calls=[]
        def transport(request,timeout):
            calls.append(request.get_method());arrived.set();self.assertTrue(release.wait(10));return self.successful(request,timeout)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self.send,permit,transport)
            try:
                self.assertTrue(arrived.wait(10));self.assertEqual(self.attempt(permit)[0]['phase'],'admitted')
                self.repo.claim_ebay_account_deletion_processing(**event)
            finally: release.set()
            with self.assertRaises(EbayExecutionDenied): pending.result(15)
        row,state=self.attempt(permit)
        self.assertEqual(calls,['PUT']);self.assertEqual(state['operations'][0]['status'],'succeeded')
        self.assertEqual(row['phase'],'reconciliation_required')

    def test_opposite_principals_in_distinct_stores_complete_without_deadlock(self):
        self.actors();executor=self.people['executor'][0];approver=self.people['approver'][0]
        self.repo.set_team_member_access(company_id=self.company,user_id=executor,role='admin',actor_user_id=self.user)
        self.executor_epochs=self.repo.access_session_epochs(user_id=executor,company_id=self.company)
        first=self.claim()['_execution_permit']
        other_store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        payload=copy.deepcopy(self.request.payload)
        dual.fixtures.attach_publish_evidence(payload,company_id=self.company,store_id=other_store)
        record=self.repo.create_confirmation(company_id=self.company,store_id=other_store,task_id=None,runtime_run_id='b1-pg-reverse',
            action_type='publish_listing',title='Reversed actors',item={'publish_payload':payload})
        record=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],decision='approve',
            decided_by=executor,note='Reverse independent approval.',expected_access_epochs=self.executor_epochs)
        connection=self.repo.create_platform_connection(company_id=self.company,store_id=other_store,user_id=self.user,
            payload={'platform':'ebay','connection_type':'oauth','status':'publish_authorized',
                'scopes':['https://api.ebay.com/oauth/api_scope/sell.inventory'],'create_secret_ref':True})
        with self.repo._connect() as conn: conn.execute("update secret_refs set status='stored' where secret_ref=?",(connection['secret_ref'],))
        connection=self.repo.ebay_execution_connections(company_id=self.company,store_id=other_store)[0]
        request=replace(self.request,store_id=other_store,confirmation_id=record['confirmation_id'],user_id=approver,
            confirmed_by=executor,confirmed_at=record['decided_at'],payload=payload)
        second=self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=approver,
            expected_access_epochs=self.repo.access_session_epochs(user_id=approver,company_id=self.company),
            operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[connection]))['_execution_permit']
        barrier=Barrier(2);calls=[[],[]]
        def transport(index):
            def send(req,timeout): calls[index].append(req.get_method());return self.successful(req,timeout)
            return send
        def second_send():
            adapter=EbayWriteHttpAdapter(self.settings,transport=transport(1))
            def token(**_): barrier.wait(5);return {'ok':True,'access_token':'SYNTHETIC-REVERSE','source':'injected'}
            with patch.object(adapter,'_resolve_access_token',side_effect=token):
                return adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                    connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=second)
        with ThreadPoolExecutor(max_workers=2) as pool:
            left=pool.submit(self.send,first,transport(0),lambda:barrier.wait(5));right=pool.submit(second_send)
            self.assertEqual(left.result(15)['status'],'published_to_ebay');self.assertEqual(right.result(15)['status'],'published_to_ebay')
        self.assertEqual(calls,[['PUT','POST','POST'],['PUT','POST','POST']])


if __name__=='__main__':
    owned.SupportPostgresTests=ExecutionPostgresTests
    raise SystemExit(owned.main())
