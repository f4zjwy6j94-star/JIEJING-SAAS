#!/usr/bin/env python3
"""Synthetic merchant approval and verified compliance lifecycle regressions.

No external adapters, real identities, credentials or existing databases.
"""
from __future__ import annotations
import hashlib
import json
import secrets
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.worker import LocalQueueWorker


class ApprovalLifecycleTests(unittest.TestCase):
    def setUp(self):
        # Retain isolated synthetic DBs as evidence; no cleanup races with SQLite
        # exception tracebacks that can temporarily retain connection objects.
        self.directory = Path(tempfile.mkdtemp(prefix='b0-'))
        self.repo = SaaSRepository(self.directory/'case.sqlite', database_engine='sqlite', database_url='')
        self.seed_account()

    def seed_account(self):
        account = self.repo.create_user_with_company(email='b0@example.test', password='synthetic-only', company_name='B0 Synthetic')
        self.company = account['company']['company_id']
        self.user = account['user']['user_id']
        self.store = self.repo.create_store(company_id=self.company, user_id=self.user, payload={'platform':'ebay'})['store_id']

    def confirmation(self, *, domestic=False):
        return self.repo.create_confirmation(company_id=self.company, store_id=None if domestic else self.store,
            task_id=None, runtime_run_id='billing_refund:synthetic' if domestic else 'synthetic',
            item={'source':'domestic_billing_refund_review','order_id':'synthetic'} if domestic else {'sku':'b0','title':'Synthetic item'},
            action_type='refund' if domestic else 'publish_listing', title='Synthetic decision')

    def test_b15_domestic_refund_cannot_use_merchant_decision(self):
        record = self.confirmation(domestic=True)
        with self.assertRaisesRegex(PermissionError, 'domestic_refund'):
            self.repo.decide_confirmation(company_id=self.company, confirmation_id=record['confirmation_id'],
                decision='approve', decided_by=self.user, note=None)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'])['status'],'pending')

    def test_b15_domestic_refund_cannot_use_merchant_claim(self):
        record = self.confirmation(domestic=True)
        # A pre-existing platform-reviewed row must not leak into merchant execution.
        with self.repo._connect() as conn:
            conn.execute("update confirmations set status='approved', decided_by=? where confirmation_id=?", (self.user,record['confirmation_id']))
        with self.assertRaisesRegex(PermissionError, 'domestic_refund'):
            self.repo.claim_external_execution(company_id=self.company, confirmation_id=record['confirmation_id'],user_id=self.user)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'])['status'],'approved')

    def deletion(self, *, secret=False):
        identity = hashlib.sha256(b'b0-synthetic-ebay-identity').hexdigest()
        connection = self.repo.create_platform_connection(company_id=self.company,store_id=self.store,user_id=self.user,
            payload={'platform':'ebay','status':'read_only_authorized','scopes':[], 'create_secret_ref':secret,
                     'metadata':{'ebay_user_id_hash':identity}})
        event = self.repo.accept_ebay_account_deletion_event(event={'event_key':'a'*64,'payload_sha256':'b'*64,
            'user_id_hash':identity,'topic':'MARKETPLACE_ACCOUNT_DELETION','schema_version':'1.0','signature_present':True},
            verification={'verified':True,'status':'verified'})
        job = self.repo.claim_next_queue_job(company_id=self.company, job_id=event['job_id'])
        return event, job, connection

    def test_b06_external_approval_requires_authenticated_epoch_snapshot(self):
        record = self.confirmation()
        with self.assertRaisesRegex(PermissionError, 'approval_request_authority_required'):
            self.repo.decide_confirmation(company_id=self.company, confirmation_id=record['confirmation_id'],
                decision='approve', decided_by=self.user, note=None)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company, confirmation_id=record['confirmation_id'])['status'],'pending')

    def test_b06_legacy_approved_without_authority_is_readable_but_not_claimable(self):
        record = self.confirmation()
        with self.repo._connect() as conn:
            conn.execute("update confirmations set status='approved', decided_by=? where confirmation_id=?", (self.user,record['confirmation_id']))
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'])['status'],'approved')
        with self.assertRaisesRegex(PermissionError, 'approval_authority_missing'):
            self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=self.user)

    def test_l01_missing_persistent_event_never_purges(self):
        event,job,_ = self.deletion()
        with self.repo._connect() as conn:
            conn.execute('delete from ebay_account_deletion_events where event_key=?',(event['event_key'],))
        calls=[]
        class Purger:
            def purge_store(self, **kwargs):
                calls.append(kwargs)
                return {'status':'ok','removed_files':0}
        worker=LocalQueueWorker(repository=self.repo,runtime_bridge=object(),media_source_asset_store=Purger())
        result=worker.run_claimed_job(job)
        self.assertNotEqual(result['status'],'completed')
        self.assertEqual(calls,[], 'Forged queue flag reached purge before persistent event validation')

    def approve(self, record, company=None, user=None):
        company, user = company or self.company, user or self.user
        return self.repo.decide_confirmation(company_id=company, confirmation_id=record['confirmation_id'],
            decision='approve', decided_by=user, note=None,
            expected_access_epochs=self.repo.access_session_epochs(user_id=user,company_id=company))

    def graph(self, company, store, user, phase='prewrite'):
        task=self.repo.create_task(company_id=company,store_id=store,user_id=user,
            task_type='listing_draft',title='Synthetic local task',input_data={})
        record=self.repo.create_confirmation(company_id=company,store_id=store,task_id=task['task_id'],
            runtime_run_id='synthetic',item={'sku':'not-to-retain','message':'private synthetic body'},
            action_type='publish_listing',title='Synthetic approval')
        self.approve(record,company,user)
        with self.repo._connect() as conn:
            approval=dict(conn.execute('select * from confirmation_approval_authorities_v1 where confirmation_id=?',
                (record['confirmation_id'],)).fetchone())
            conn.execute('''insert into confirmation_execution_authorities_v1
                (attempt_id,company_id,store_id,confirmation_id,approval_authority_id,executor_user_id,
                 executor_user_epoch,executor_member_epoch,required_permissions,business_binding_sha256,
                 operation_plan_sha256,operation_count,operation_state_json,phase,created_at)
                 values (?,?,?,?,?,?,0,0,?,?,?,?,?,?,?)''',
                ('attempt_'+secrets.token_hex(8),company,store,record['confirmation_id'],approval['authority_id'],user,
                 '["execute_confirmed_action"]','a'*64,'b'*64,1,'[]',phase,approval['approved_at']))
        return record,approval

    def scope_fingerprint(self,company,store):
        with self.repo._connect() as conn:
            rows={table:[dict(r) for r in conn.execute(f'select * from {table} where company_id=? and store_id=? order by 1',
                    (company,store)).fetchall()] for table in ('stores','confirmations','confirmation_approval_authorities_v1',
                        'confirmation_execution_authorities_v1','tasks')}
        return json.dumps(rows,sort_keys=True,default=str)

    def test_l03_l04_scoped_deletion_removes_children_before_parents(self):
        self.graph(self.company,self.store,self.user)
        self.graph(self.company,self.store,self.user,'admitted')
        other_store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        self.graph(self.company,other_store,self.user)
        account=self.repo.create_user_with_company(email='other@example.test',password='synthetic-only',company_name='Other')
        other_company,other_user=account['company']['company_id'],account['user']['user_id']
        foreign_store=self.repo.create_store(company_id=other_company,user_id=other_user,payload={'platform':'ebay'})['store_id']
        self.graph(other_company,foreign_store,other_user)
        controls=(self.scope_fingerprint(self.company,other_store),self.scope_fingerprint(other_company,foreign_store))
        event,job,_=self.deletion()
        calls=[]
        class Purger:
            def purge_store(self, **kwargs):
                calls.append(kwargs)
                return {'status':'purged','removed_files':0}
        worker=LocalQueueWorker(repository=self.repo,runtime_bridge=object(),media_source_asset_store=Purger())
        result=worker.run_claimed_job(job)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(len(calls),1)
        receipt=result['account_deletion']
        self.assertTrue(receipt['authority_lifecycle']['possible_in_flight'])
        self.assertEqual(receipt['authority_lifecycle']['approval_records_removed'],2)
        with self.repo._connect() as conn:
            for table in ('confirmations','confirmation_approval_authorities_v1','confirmation_execution_authorities_v1'):
                self.assertEqual(conn.execute(f'select count(*) as n from {table} where company_id=? and store_id=?',
                    (self.company,self.store)).fetchone()['n'],0,table)
            if self.repo.database_engine=='sqlite':
                self.assertEqual(conn.execute('pragma foreign_keys').fetchone()[0],1)
                self.assertEqual(conn.execute('pragma foreign_key_check').fetchall(),[])
        self.assertEqual(controls,(self.scope_fingerprint(self.company,other_store),self.scope_fingerprint(other_company,foreign_store)))
        serialized=json.dumps(receipt)
        for forbidden in ('private synthetic body','not-to-retain',self.user,'processing_token'):
            self.assertNotIn(forbidden,serialized)
        self.assertIsNone(self.repo.claim_next_queue_job(company_id=self.company,job_id=event['job_id']))
        duplicate=worker._run_ebay_account_deletion_job(job=job,
            task=self.repo.get_task(company_id=self.company,task_id=event['task_id']),job_body=job['job'])
        self.assertEqual(duplicate['status'],'completed')
        self.assertEqual(len(calls),1,'duplicate event repeated purge')

    def test_b06_valid_receipt_immutable_and_item_drift_denied(self):
        record=self.confirmation()
        self.approve(record)
        with self.repo._connect() as conn:
            row=dict(conn.execute('select * from confirmation_approval_authorities_v1 where confirmation_id=?',
                (record['confirmation_id'],)).fetchone())
        self.assertEqual(row['approver_user_id'],self.user)
        self.assertEqual(row['required_permission'],'approve_high_risk')
        with self.assertRaises(Exception):
            with self.repo._connect() as conn:
                conn.execute('update confirmation_approval_authorities_v1 set approver_user_epoch=1 where authority_id=?',(row['authority_id'],))
        with self.repo._connect() as conn:
            conn.execute('update confirmations set item_json=? where confirmation_id=?',('{"sku":"changed"}',record['confirmation_id']))
        with self.assertRaisesRegex(PermissionError,'approval_authority_binding_changed'):
            self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=self.user)
        with self.repo._connect() as conn:
            self.assertEqual(dict(conn.execute('select * from confirmation_approval_authorities_v1 where authority_id=?',
                (row['authority_id'],)).fetchone()),row)

    def test_b0_buyer_message_approval_does_not_upgrade_create_task(self):
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,
            runtime_run_id='synthetic',item={'source':'support'},action_type='buyer_message_send',title='Synthetic reply')
        with self.repo._connect() as conn:
            conn.execute("update team_members set role='operator' where company_id=? and user_id=?",(self.company,self.user))
        with self.assertRaisesRegex(PermissionError,'approval_permission_denied'):
            self.approve(record)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'])['status'],'pending')

    def test_b15_single_markers_with_valid_epochs_never_create_authority(self):
        for item,runtime in (({'source':'domestic_billing_refund_review'},'plain'),
                             ({'source':'other'},'billing_refund:malformed'),
                             ({'source':'domestic_billing_refund_review','order_id':[]},'plain')):
            with self.subTest(item=item,runtime=runtime):
                record=self.repo.create_confirmation(company_id=self.company,store_id=None,task_id=None,
                    runtime_run_id=runtime,item=item,action_type='refund',title='Synthetic refund')
                with self.repo._connect() as conn:
                    before=dict(conn.execute('select * from confirmations where confirmation_id=?',
                        (record['confirmation_id'],)).fetchone())
                with self.assertRaisesRegex(PermissionError,'domestic_refund'):
                    self.approve(record)
                self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'])['status'],'pending')
                with self.repo._connect() as conn:
                    self.assertEqual(before,dict(conn.execute('select * from confirmations where confirmation_id=?',
                        (record['confirmation_id'],)).fetchone()))
                    self.assertEqual(conn.execute('select count(*) as n from confirmation_approval_authorities_v1 where confirmation_id=?',
                        (record['confirmation_id'],)).fetchone()['n'],0)
                    # Explicit adversarial history, not a generic merchant
                    # approval: exercise the claim guard independently too.
                    conn.execute("update confirmations set status='approved',decided_by=? where confirmation_id=?",
                        (self.user,record['confirmation_id']))
                    legacy=dict(conn.execute('select * from confirmations where confirmation_id=?',
                        (record['confirmation_id'],)).fetchone())
                with self.assertRaisesRegex(PermissionError,'domestic_refund'):
                    self.repo.claim_external_execution(company_id=self.company,
                        confirmation_id=record['confirmation_id'],user_id=self.user)
                with self.repo._connect() as conn:
                    self.assertEqual(legacy,dict(conn.execute('select * from confirmations where confirmation_id=?',
                        (record['confirmation_id'],)).fetchone()))
                    for table in ('confirmation_approval_authorities_v1','confirmation_execution_authorities_v1','external_execution_claims'):
                        self.assertEqual(conn.execute(f'select count(*) as n from {table} where confirmation_id=?',
                            (record['confirmation_id'],)).fetchone()['n'],0,table)

    def test_l01_persistent_binding_matrix_zero_revocations_and_purges(self):
        event,job,connection=self.deletion(secret=True)
        # Existing alternate records deliberately satisfy each individual FK;
        # the worker must reject the inconsistent durable *combined* binding.
        account=self.repo.create_user_with_company(email='mismatch@example.test',password='synthetic-only',company_name='Mismatch')
        company,user=account['company']['company_id'],account['user']['user_id']
        store=self.repo.create_store(company_id=company,user_id=user,payload={'platform':'ebay'})['store_id']
        task=self.repo.create_task(company_id=company,store_id=store,user_id=user,
            task_type='listing_draft',title='Other task',input_data={})
        alternate_job=self.repo.create_queue_job(company_id=company,task_id=task['task_id'],job_data={})
        alternate_connection=self.repo.create_platform_connection(company_id=company,store_id=store,user_id=user,
            payload={'platform':'ebay','status':'read_only_authorized','scopes':[], 'create_secret_ref':False})
        calls=[]
        class Resolver:
            def __init__(self,*args): pass
            def revoke_secret(self,**kwargs):
                calls.append('revoke')
                return {'status':'revoked'}
        class Purger:
            def purge_store(self,**kwargs):
                calls.append('purge')
                return {'removed_files':0,'removed_metadata':0}
        worker=LocalQueueWorker(repository=self.repo,runtime_bridge=object(),settings=object(),media_source_asset_store=Purger())
        mutations=[('ebay_account_deletion_events','company_id',company),
            ('ebay_account_deletion_events','store_id',store),('ebay_account_deletion_events','connection_id',alternate_connection['connection_id']),
            ('ebay_account_deletion_events','task_id',task['task_id']),('ebay_account_deletion_events','job_id',alternate_job['job_id']),
            ('ebay_account_deletion_events','verification_json','{}'),
            ('ebay_account_deletion_events','status','cancelled'),
            ('tasks','task_type','paid_media_generation'),('tasks','store_id',store),('tasks','status','completed'),
            ('queue_jobs','task_id',task['task_id']),('queue_jobs','status','queued'),
            ('platform_connections','platform','other')]
        identifiers={'ebay_account_deletion_events':('event_key',event['event_key']),
            'tasks':('task_id',event['task_id']),'queue_jobs':('job_id',event['job_id']),
            'platform_connections':('connection_id',connection['connection_id'])}
        with patch('jiejing_saas.worker.VaultSecretResolver',Resolver):
            for table,column,value in mutations:
                key,ident=identifiers[table]
                with self.subTest(table=table,column=column):
                    with self.repo._connect() as conn:
                        original=conn.execute(f'select {column} from {table} where {key}=?',(ident,)).fetchone()[column]
                        conn.execute(f'update {table} set {column}=? where {key}=?',(value,ident))
                    try:
                        with self.assertRaises((PermissionError,KeyError)):
                            worker._run_ebay_account_deletion_job(job=job,
                                task={'company_id':self.company,'store_id':self.store,'task_id':event['task_id']},job_body=job['job'])
                        self.assertEqual(calls,[])
                    finally:
                        with self.repo._connect() as conn:
                            conn.execute(f'update {table} set {column}=? where {key}=?',(original,ident))

    def test_l04_execution_scope_cannot_use_null_to_escape_store_binding(self):
        _,authority=self.graph(self.company,self.store,self.user)
        with self.assertRaises(Exception):
            with self.repo._connect() as conn:
                conn.execute('update confirmation_execution_authorities_v1 set store_id=null where approval_authority_id=?',
                    (authority['authority_id'],))

    def test_b06_legitimate_company_scoped_approval_keeps_nullable_store(self):
        record=self.repo.create_confirmation(company_id=self.company,store_id=None,task_id=None,
            runtime_run_id='synthetic',item={'source':'account'},action_type='change_ad_budget',title='Synthetic company request')
        self.approve(record)
        with self.repo._connect() as conn:
            row=conn.execute('select store_id from confirmation_approval_authorities_v1 where confirmation_id=?',
                (record['confirmation_id'],)).fetchone()
        self.assertIsNone(row['store_id'])

    def test_l04_current_pointer_insert_cannot_reference_another_confirmation(self):
        record,authority=self.graph(self.company,self.store,self.user)
        with self.repo._connect() as conn:
            values=dict(conn.execute('select * from confirmations where confirmation_id=?',(record['confirmation_id'],)).fetchone())
        values['confirmation_id']='confirmation_'+secrets.token_hex(8)
        columns=','.join(values)
        with self.assertRaisesRegex(Exception,'approval_authority_pointer_mismatch|confirmation_current_approval_scope'):
            with self.repo._connect() as conn:
                conn.execute(f'insert into confirmations ({columns}) values ({",".join("?" for _ in values)})',tuple(values.values()))

    def test_l04_current_pointer_scope_updates_are_null_safe(self):
        record,authority=self.graph(self.company,self.store,self.user)
        for column,value in (('store_id',None),('action_type','refund')):
            with self.subTest(column=column):
                with self.assertRaisesRegex(Exception,'approval_authority_pointer_mismatch|confirmation_current_approval_scope'):
                    with self.repo._connect() as conn:
                        conn.execute(f'update confirmations set {column}=? where confirmation_id=?',(value,record['confirmation_id']))

    def test_l04_execution_plan_and_identity_bindings_cannot_mutate(self):
        _,authority=self.graph(self.company,self.store,self.user)
        changes=(('attempt_id','changed_attempt'),('required_permissions','[]'),
            ('business_binding_sha256','c'*64),('operation_plan_sha256','d'*64),
            ('operation_count',2),('created_at','2026-01-01T00:00:00+00:00'))
        for column,value in changes:
            with self.subTest(column=column):
                with self.assertRaisesRegex(Exception,'execution_authority_scope_immutable'):
                    with self.repo._connect() as conn:
                        conn.execute(f'update confirmation_execution_authorities_v1 set {column}=? where approval_authority_id=?',
                            (value,authority['authority_id']))
        # State/result fields are the future B1 CAS surface, not immutable plan.
        with self.repo._connect() as conn:
            conn.execute("update confirmation_execution_authorities_v1 set phase='admitted',operation_state_json='[{}]',admitted_at=?,terminal_reason=null where approval_authority_id=?",
                (authority['approved_at'],authority['authority_id']))

    def test_l03_retained_parent_and_sidecar_extensions_are_scoped_and_revoked(self):
        from jiejing_saas.support_conversations import SupportConversations
        other_store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        records=[]
        for store in (self.store,other_store):
            record=self.repo.create_confirmation(company_id=self.company,store_id=store,task_id=None,
                runtime_run_id='synthetic',item={'sku':'retained'},action_type='publish_listing',title='Retained parent')
            approved=self.approve(record)
            records.append(record)
            with self.repo._connect() as conn:
                for sql in SupportConversations.schema_statements(): conn.execute(sql)
                conn.execute('''insert into external_execution_claims
                    (claim_id,company_id,store_id,confirmation_id,action_type,status,nonce_sha256,binding_json,
                     claimed_by,claimed_at,expires_at,authority_json) values (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('claim_'+store,self.company,store,record['confirmation_id'],'publish_listing','processing','a'*64,'{}',
                     self.user,approved['decided_at'],approved['decided_at'],'{"authority":"private-actor"}'))
                conn.execute('''insert into support_send_intents_v1
                    (company_id,store_id,owner_id,draft_id,confirmation_id,conversation_id,source_message_id,binding_hash,status,record_text)
                     values (?,?,?,?,?,?,?,?,?,?)''',
                    (self.company,store,'owner-hash','draft',record['confirmation_id'],'conversation','message','b'*64,'unknown',
                     '{"authority":{"actor":"private-actor"},"old_retained_receipt":"unchanged"}'))
        with self.repo._connect() as conn:
            controls=[dict(conn.execute('select * from '+table+' where company_id=? and store_id=?',(self.company,other_store)).fetchone())
                      for table in ('external_execution_claims','support_send_intents_v1')]
        event,job,_=self.deletion()
        # Compliance authority belongs to the verified event, not creator login.
        self.repo.set_user_access_status(user_id=self.user,status='disabled')
        result=LocalQueueWorker(repository=self.repo,runtime_bridge=object()).run_claimed_job(job)
        self.assertEqual(result['status'],'completed',result)
        receipt=result['account_deletion']['authority_lifecycle']
        self.assertEqual(receipt['draft_authority_refs_removed'],1)
        self.assertEqual(receipt['support_authority_refs_removed'],1)
        with self.repo._connect() as conn:
            parent=conn.execute('select * from confirmations where confirmation_id=?',(records[0]['confirmation_id'],)).fetchone()
            self.assertIsNotNone(parent,'B0 must not expand existing taskless parent retention policy')
            self.assertIsNone(parent['approval_authority_id'])
            self.assertIsNone(conn.execute('select authority_json from external_execution_claims where company_id=? and store_id=?',
                (self.company,self.store)).fetchone()['authority_json'])
            retained=json.loads(conn.execute('select record_text from support_send_intents_v1 where company_id=? and store_id=?',
                (self.company,self.store)).fetchone()['record_text'])
            self.assertEqual(retained,{'old_retained_receipt':'unchanged'})
            self.assertEqual(controls,[dict(conn.execute('select * from '+table+' where company_id=? and store_id=?',
                (self.company,other_store)).fetchone()) for table in ('external_execution_claims','support_send_intents_v1')])


class SQLiteAuthorityInitializationTests(unittest.TestCase):
    setUp = ApprovalLifecycleTests.setUp
    seed_account = ApprovalLifecycleTests.seed_account
    approve = ApprovalLifecycleTests.approve
    graph = ApprovalLifecycleTests.graph

    def _duplicate_active_attempt(self, conn, confirmation_id):
        row = dict(conn.execute('select * from confirmation_execution_authorities_v1 where confirmation_id=?',
                               (confirmation_id,)).fetchone())
        row['attempt_id'] = 'duplicate_' + secrets.token_hex(8)
        conn.execute('insert into confirmation_execution_authorities_v1 (' + ','.join(row) + ') values ('
                     + ','.join('?' for _ in row) + ')', tuple(row.values()))

    def _assert_bad_active_index_is_rejected_unchanged(self, sql, *, name='confirmation_one_active_attempt'):
        record, _ = self.graph(self.company, self.store, self.user)
        with self.repo._connect() as conn:
            conn.execute('drop index confirmation_one_active_attempt')
            conn.execute(sql)
            before = conn.execute('select sql from sqlite_master where name=?', (name,)).fetchone()['sql']
            version = conn.execute('pragma schema_version').fetchone()[0]
            # This is a physically ineffective guard, not merely different SQL.
            self._duplicate_active_attempt(conn, record['confirmation_id'])
            self.assertEqual(conn.execute('select count(*) from confirmation_execution_authorities_v1 where confirmation_id=?',
                                          (record['confirmation_id'],)).fetchone()[0], 2)
        try:
            with self.assertRaisesRegex(RuntimeError, 'confirmation_authority_sqlite_guard_drift:confirmation_one_active_attempt'):
                self.repo.initialize()
        finally:
            with self.repo._connect() as conn:
                self.assertEqual(conn.execute('select sql from sqlite_master where name=?', (name,)).fetchone()['sql'], before)
                self.assertEqual(conn.execute('pragma schema_version').fetchone()[0], version)

    def test_b0_sqlite_uppercase_bad_index_name_blocks_without_overwriting(self):
        name = 'CONFIRMATION_ONE_ACTIVE_ATTEMPT'
        self._assert_bad_active_index_is_rejected_unchanged(
            f"create index {name} on confirmation_execution_authorities_v1(confirmation_id) "
            "where phase in ('prewrite','admitted','reconciliation_required')", name=name)

    def test_b0_sqlite_mixed_case_bad_index_name_blocks_without_overwriting(self):
        name = 'Confirmation_One_Active_Attempt'
        self._assert_bad_active_index_is_rejected_unchanged(
            f"create index {name} on confirmation_execution_authorities_v1(confirmation_id) "
            "where phase in ('prewrite','admitted','reconciliation_required')", name=name)

    def _assert_bad_immutable_trigger_is_rejected_unchanged(self, name):
        record = ApprovalLifecycleTests.confirmation(self)
        self.approve(record)
        with self.repo._connect() as conn:
            conn.execute('drop trigger approval_immutable_update')
            conn.execute(f'create trigger {name} before update on confirmation_approval_authorities_v1 begin select 1; end')
            before = conn.execute('select sql from sqlite_master where name=?', (name,)).fetchone()['sql']
            version = conn.execute('pragma schema_version').fetchone()[0]
            # Demonstrate ineffective immutability, not just differently cased SQL.
            conn.execute('update confirmation_approval_authorities_v1 set approved_role=? where confirmation_id=?',
                         ('synthetic-mutated-role', record['confirmation_id']))
            mutated = dict(conn.execute('select * from confirmation_approval_authorities_v1 where confirmation_id=?',
                                        (record['confirmation_id'],)).fetchone())
            self.assertEqual(mutated['approved_role'], 'synthetic-mutated-role')
        try:
            with self.assertRaisesRegex(RuntimeError, 'confirmation_authority_sqlite_guard_drift:approval_immutable_update'):
                self.repo.initialize()
        finally:
            with self.repo._connect() as conn:
                self.assertEqual(conn.execute('select sql from sqlite_master where name=?', (name,)).fetchone()['sql'], before)
                self.assertEqual(conn.execute('pragma schema_version').fetchone()[0], version)
                self.assertEqual(dict(conn.execute('select * from confirmation_approval_authorities_v1 where confirmation_id=?',
                                                  (record['confirmation_id'],)).fetchone()), mutated)
                self.assertEqual(conn.execute('pragma foreign_key_check').fetchall(), [])

    def test_b0_sqlite_uppercase_noop_trigger_name_blocks_without_overwriting(self):
        self._assert_bad_immutable_trigger_is_rejected_unchanged('APPROVAL_IMMUTABLE_UPDATE')

    def test_b0_sqlite_mixed_case_noop_trigger_name_blocks_without_overwriting(self):
        self._assert_bad_immutable_trigger_is_rejected_unchanged('Approval_Immutable_Update')

    def test_b0_sqlite_valid_case_variant_guard_names_keep_enforcement_and_stable_ddl(self):
        import sqlite3
        record, _ = self.graph(self.company, self.store, self.user)
        with self.repo._connect() as conn:
            for kind, name, varied in (
                ('index', 'confirmation_one_active_attempt', 'Confirmation_One_Active_Attempt'),
                ('trigger', 'approval_immutable_update', 'APPROVAL_IMMUTABLE_UPDATE'),
            ):
                sql = conn.execute('select sql from sqlite_master where type=? and name=?', (kind, name)).fetchone()['sql']
                conn.execute(f'drop {kind} {name}')
                conn.execute(sql.replace(name, varied, 1))
            before = conn.execute('pragma schema_version').fetchone()[0]
        self.repo.initialize()
        self.repo.initialize()
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute('pragma schema_version').fetchone()[0], before)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint failed'):
            with self.repo._connect() as conn:
                self._duplicate_active_attempt(conn, record['confirmation_id'])
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'approval_authority_immutable'):
            with self.repo._connect() as conn:
                conn.execute('update confirmation_approval_authorities_v1 set approved_role=? where confirmation_id=?',
                             ('synthetic-mutation-denied', record['confirmation_id']))

    def test_b0_sqlite_nonunique_active_index_blocks_without_overwriting(self):
        self._assert_bad_active_index_is_rejected_unchanged(
            "create index confirmation_one_active_attempt on confirmation_execution_authorities_v1(confirmation_id) "
            "where phase in ('prewrite','admitted','reconciliation_required')")

    def test_b0_sqlite_uppercase_active_predicate_blocks_without_overwriting(self):
        self._assert_bad_active_index_is_rejected_unchanged(
            "create unique index confirmation_one_active_attempt on confirmation_execution_authorities_v1(confirmation_id) "
            "where phase in ('PREWRITE','ADMITTED','RECONCILIATION_REQUIRED')")

    def test_b0_sqlite_wrong_active_index_table_blocks_without_overwriting(self):
        self._assert_bad_active_index_is_rejected_unchanged(
            "create unique index confirmation_one_active_attempt on confirmations(confirmation_id) where status='prewrite'")

    def test_b0_sqlite_wrong_active_index_column_blocks_without_overwriting(self):
        self._assert_bad_active_index_is_rejected_unchanged(
            "create unique index confirmation_one_active_attempt on confirmation_execution_authorities_v1(attempt_id) "
            "where phase in ('prewrite','admitted','reconciliation_required')")

    def test_b0_sqlite_missing_active_index_is_installed_and_enforced(self):
        import sqlite3
        record, _ = self.graph(self.company, self.store, self.user)
        with self.repo._connect() as conn:
            conn.execute('drop index confirmation_one_active_attempt')
        self.repo.initialize()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'UNIQUE constraint failed'):
            with self.repo._connect() as conn:
                self._duplicate_active_attempt(conn, record['confirmation_id'])
        with self.repo._connect() as conn:
            before = conn.execute('pragma schema_version').fetchone()[0]
        self.repo.initialize()
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute('pragma schema_version').fetchone()[0], before)

    def test_b0_sqlite_missing_guard_is_installed_and_enforced(self):
        record=ApprovalLifecycleTests.confirmation(self)
        ApprovalLifecycleTests.approve(self,record)
        with self.repo._connect() as conn:
            conn.execute('drop trigger approval_immutable_update')
        self.repo.initialize()
        with self.assertRaisesRegex(Exception,'approval_authority_immutable'):
            with self.repo._connect() as conn:
                conn.execute('update confirmation_approval_authorities_v1 set approved_role=? where confirmation_id=?',
                             ('changed',record['confirmation_id']))

    def test_b0_sqlite_reinitialize_has_no_repeated_guard_ddl(self):
        with self.repo._connect() as conn:
            before=conn.execute('pragma schema_version').fetchone()[0]
        self.repo.initialize()
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute('pragma schema_version').fetchone()[0],before)

    def test_b0_sqlite_existing_guard_drift_blocks_without_overwriting(self):
        with self.repo._connect() as conn:
            conn.execute('drop trigger approval_pointer_scope')
            conn.execute('create trigger approval_pointer_scope before update on confirmations begin select 1; end')
        with self.assertRaisesRegex(RuntimeError,'confirmation_authority_sqlite_guard_drift'):
            self.repo.initialize()
        with self.repo._connect() as conn:
            self.assertIn('select 1',conn.execute("select sql from sqlite_master where type='trigger' and name='approval_pointer_scope'").fetchone()['sql'])


if __name__ == '__main__':
    unittest.main()
