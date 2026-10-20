#!/usr/bin/env python3
"""Owned PG-only migration and SQLite authority round-trip regressions."""
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_jiejing_support_postgres as owned
from test_jiejing_confirmation_authorities import ApprovalLifecycleTests
from test_jiejing_confirmation_authorities_postgres import ApprovalPostgresTests
from jiejing_sqlite_to_postgres_rehearsal import generate_rehearsal
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.infrastructure_drivers import run_postgres_migration, _load_postgres_migrations, _probe_postgres_schema_contract


class AuthorityImportTests(unittest.TestCase):
    setUp=ApprovalPostgresTests.setUp
    tearDown=ApprovalPostgresTests.tearDown

    def seed_account(self):
        # Target business tables start empty; only the reviewed schema is present.
        pass

    def source(self):
        path=owned.RUN/('source-'+uuid.uuid4().hex+'.sqlite')
        fixture=ApprovalLifecycleTests()
        fixture.repo=SaaSRepository(path,database_engine='sqlite',database_url='')
        fixture.seed_account()
        record,approval=fixture.graph(fixture.company,fixture.store,fixture.user)
        with fixture.repo._connect() as conn:
            conn.execute('''insert into external_execution_claims
                (claim_id,company_id,store_id,confirmation_id,action_type,status,nonce_sha256,binding_json,
                 claimed_by,claimed_at,expires_at,authority_json) values (?,?,?,?,?,?,?,?,?,?,?,?)''',
                ('claim_import',fixture.company,fixture.store,record['confirmation_id'],'publish_listing','claimed',
                 'c'*64,'{"synthetic":true}',fixture.user,approval['approved_at'],approval['approved_at'],
                 json.dumps({'approval_authority_id':approval['authority_id'],'user_epoch':0,'member_epoch':0})))
        company_record=fixture.repo.create_confirmation(company_id=fixture.company,store_id=None,task_id=None,
            runtime_run_id='synthetic',item={'company-level':True},action_type='change_ad_budget',title='Company scoped')
        fixture.approve(company_record)
        legacy=fixture.confirmation()
        with fixture.repo._connect() as conn:
            conn.execute("update confirmations set status='approved',decided_by=? where confirmation_id=?",(fixture.user,legacy['confirmation_id']))
        fixture.repo.set_user_access_status(user_id=fixture.user,status='disabled')
        fixture.repo.set_user_access_status(user_id=fixture.user,status='active')
        # A retained membership-generation row, even if its actor is no longer
        # a current member, must not be filtered out by the export tool.
        with fixture.repo._connect() as conn:
            conn.execute('insert into access_revocation_epochs (user_id,company_id,generation) values (?,?,3)',(fixture.user,fixture.company))
            conn.execute('insert into access_revocation_epochs (user_id,company_id,generation) values (?,?,7)',('removed-synthetic-user',fixture.company))
        return path,fixture,legacy

    def generated(self,path):
        output=owned.RUN/('import-'+uuid.uuid4().hex+'.sql')
        generate_rehearsal(sqlite_path=path,out_sql_path=output,summary_path=output.with_suffix('.json'))
        return output.read_text(encoding='utf-8')

    def apply(self,sql):
        with owned.psycopg.connect(self.dsn,autocommit=True) as conn:
            try:
                conn.execute(sql)
            except Exception:
                conn.execute('rollback')
                raise

    def rows(self,repo,table):
        with repo._connect() as conn:
            return sorted((dict(r) for r in conn.execute('select * from '+table).fetchall()),key=lambda r:json.dumps(r,sort_keys=True,default=str))

    def test_round_trip_preserves_receipts_epochs_null_store_and_legacy(self):
        path,fixture,legacy=self.source()
        sql=self.generated(path)
        self.apply(sql)
        self.apply(sql)  # Identical history is idempotent; never creates a receipt.
        for table in ('confirmation_approval_authorities_v1','confirmation_execution_authorities_v1','access_revocation_epochs'):
            self.assertEqual(self.rows(fixture.repo,table),self.rows(self.repo,table),table)
        with fixture.repo._connect() as source,self.repo._connect() as target:
            query='select authority_json,nonce_sha256,status,claimed_by,company_id,store_id,confirmation_id from external_execution_claims where claim_id=?'
            self.assertEqual(dict(source.execute(query,('claim_import',)).fetchone()),
                             dict(target.execute(query,('claim_import',)).fetchone()))
        self.assertEqual(self.repo.access_session_epochs(user_id=fixture.user,company_id=fixture.company),{'user_epoch':2,'member_epoch':3})
        old_identity={'user_id':fixture.user,'company_id':fixture.company,'user_epoch':0,'member_epoch':0}
        with self.repo._connect() as conn:
            self.assertFalse(self.repo._identity_epochs_match(conn,old_identity))
            self.assertEqual(conn.execute('select count(*) as n from confirmations where approval_authority_id is not null').fetchone()['n'],2)
        self.assertEqual(self.repo.get_confirmation(company_id=fixture.company,confirmation_id=legacy['confirmation_id'])['status'],'approved')
        with self.assertRaisesRegex(PermissionError,'approval_authority_missing'):
            self.repo.claim_external_execution(company_id=fixture.company,confirmation_id=legacy['confirmation_id'],user_id=fixture.user)
        pending=self.repo.create_confirmation(company_id=fixture.company,store_id=None,task_id=None,runtime_run_id='new',item={},action_type='change_ad_budget',title='New request')
        with self.assertRaisesRegex(PermissionError,'approval_request_authority_changed'):
            self.repo.decide_confirmation(company_id=fixture.company,confirmation_id=pending['confirmation_id'],decided_by=fixture.user,decision='approve',note=None,expected_access_epochs={'user_epoch':0,'member_epoch':0})
        self.repo.decide_confirmation(company_id=fixture.company,confirmation_id=pending['confirmation_id'],decided_by=fixture.user,decision='approve',note=None,expected_access_epochs={'user_epoch':2,'member_epoch':3})

    def test_conflicting_epoch_history_aborts_without_replacing_current_authority(self):
        path,fixture,_=self.source()
        sql=self.generated(path)
        self.apply(sql)
        with self.repo._connect() as conn:
            conn.execute('update access_revocation_epochs set generation=9 where user_id=? and company_id=?',
                         (fixture.user,''))
        tables=('access_revocation_epochs','confirmations','confirmation_approval_authorities_v1',
                'confirmation_execution_authorities_v1','external_execution_claims')
        before={table:self.rows(self.repo,table) for table in tables}
        with self.assertRaises(owned.psycopg.errors.DivisionByZero):
            self.apply(sql)
        self.assertEqual(before,{table:self.rows(self.repo,table) for table in tables})
        self.assertEqual(self.repo.access_session_epochs(user_id=fixture.user,company_id=fixture.company)['user_epoch'],9)

    def test_failure_before_pointer_restore_rolls_back_the_whole_import(self):
        path,fixture,_=self.source()
        sql=self.generated(path)
        sql=sql.replace('-- Restore current approval pointers', 'select 1/0;\n-- Restore current approval pointers')
        with self.assertRaises(owned.psycopg.errors.DivisionByZero):
            self.apply(sql)
        for table in ('users','companies','confirmations','confirmation_approval_authorities_v1','confirmation_execution_authorities_v1','access_revocation_epochs','external_execution_claims'):
            self.assertEqual(self.rows(self.repo,table),[],table)

    def test_008_replay_is_noop_and_probe_rejects_missing_scope_constraint(self):
        migrations,error=_load_postgres_migrations(None)
        self.assertIsNone(error)
        first=run_postgres_migration(database_url=self.dsn)
        self.assertEqual(first['status'],'ok')
        self.assertEqual(first.get('applied_migration_ids'),[])
        self.assertIn('20261014_008_confirmation_authorities_postgres',first['skipped_migration_ids'])
        with owned.psycopg.connect(self.dsn,autocommit=True) as conn:
            conn.execute('alter table confirmations drop constraint confirmation_current_approval_scope')
            probe=_probe_postgres_schema_contract(conn.cursor(),migrations)
            self.assertEqual(probe['status'],'blocked')
            self.assertIn('confirmation.current_approval_scope_fk',probe['missing_constraints'])
            conn.execute('drop table confirmation_execution_authorities_v1')
            probe=_probe_postgres_schema_contract(conn.cursor(),migrations)
            self.assertEqual(probe['status'],'blocked')
            self.assertIn('confirmation_execution_authorities_v1',probe['missing_relations'])

    def test_008_upgrade_preserves_historical_approved_without_re_signing(self):
        account=self.repo.create_user_with_company(email='legacy-upgrade@example.test',password='synthetic-only',company_name='Legacy')
        company,user=account['company']['company_id'],account['user']['user_id']
        record=self.repo.create_confirmation(company_id=company,store_id=None,task_id=None,runtime_run_id='legacy',item={},action_type='change_ad_budget',title='Legacy')
        with self.repo._connect() as conn:
            conn.execute("update confirmations set status='approved',decided_by=? where confirmation_id=?",(user,record['confirmation_id']))
        # Owned DB only: reconstruct the pre-008 schema by removing empty new
        # objects. Business history remains present while the additive upgrade runs.
        with owned.psycopg.connect(self.dsn,autocommit=True) as conn:
            conn.execute('drop table confirmation_execution_authorities_v1')
            conn.execute('alter table confirmations drop constraint confirmation_current_approval_scope')
            conn.execute('drop table confirmation_approval_authorities_v1')
            conn.execute("delete from schema_migrations where migration_id='20261014_008_confirmation_authorities_postgres'")
        result=run_postgres_migration(database_url=self.dsn)
        self.assertEqual(result['status'],'ok',result)
        self.assertEqual(result['applied_migration_ids'],['20261014_008_confirmation_authorities_postgres'])
        self.assertEqual(self.rows(self.repo,'confirmation_approval_authorities_v1'),[])
        with self.repo._connect() as conn:
            row=conn.execute('select status,decided_by,approval_authority_id from confirmations where confirmation_id=?',(record['confirmation_id'],)).fetchone()
            self.assertEqual(dict(row),{'status':'approved','decided_by':user,'approval_authority_id':None})

    def test_008_probe_rejects_disabled_trigger_and_replaced_function(self):
        migrations,error=_load_postgres_migrations(None)
        self.assertIsNone(error)
        with owned.psycopg.connect(self.dsn,autocommit=True) as conn:
            conn.execute('alter table confirmation_approval_authorities_v1 disable trigger approval_receipt_guard')
            probe=_probe_postgres_schema_contract(conn.cursor(),migrations)
            self.assertEqual(probe['status'],'blocked',probe)
            self.assertIn('approval_receipt_guard',probe['missing_authority_guards'])
            conn.execute('alter table confirmation_approval_authorities_v1 enable trigger approval_receipt_guard')
            conn.execute('create or replace function jiejing_approval_receipt_guard() returns trigger language plpgsql as $$ begin return NEW; end $$;')
            probe=_probe_postgres_schema_contract(conn.cursor(),migrations)
            self.assertEqual(probe['status'],'blocked',probe)
            self.assertIn('approval_receipt_guard',probe['missing_authority_guards'])

    def test_008_probe_rejects_missing_active_attempt_index(self):
        migrations,error=_load_postgres_migrations(None)
        self.assertIsNone(error)
        with owned.psycopg.connect(self.dsn,autocommit=True) as conn:
            conn.execute('drop index confirmation_one_active_attempt')
            probe=_probe_postgres_schema_contract(conn.cursor(),migrations)
            self.assertEqual(probe['status'],'blocked',probe)
            self.assertIn('confirmation_one_active_attempt',probe['missing_authority_guards'])

    def test_008_probe_rejects_uppercase_active_predicate_without_changing_it(self):
        path, _, _ = self.source()
        self.apply(self.generated(path))
        migrations, error = _load_postgres_migrations(None)
        self.assertIsNone(error)
        duplicate = '''insert into confirmation_execution_authorities_v1
            (attempt_id,company_id,store_id,confirmation_id,approval_authority_id,executor_user_id,
             executor_user_epoch,executor_member_epoch,required_permissions,business_binding_sha256,
             operation_plan_sha256,operation_count,operation_state_json,phase,created_at,admitted_at,terminal_reason)
            select %s,company_id,store_id,confirmation_id,approval_authority_id,executor_user_id,
             executor_user_epoch,executor_member_epoch,required_permissions,business_binding_sha256,
             operation_plan_sha256,operation_count,operation_state_json,%s,created_at,admitted_at,terminal_reason
            from confirmation_execution_authorities_v1 order by attempt_id limit 1'''
        with owned.psycopg.connect(self.dsn, autocommit=True) as conn:
            self.assertEqual(_probe_postgres_schema_contract(conn.cursor(), migrations)['status'], 'ok')
            for phase in ('prewrite', 'admitted', 'reconciliation_required'):
                with self.subTest(healthy_phase=phase), self.assertRaises(owned.psycopg.errors.UniqueViolation):
                    conn.execute(duplicate, ('duplicate_healthy_' + phase, phase))
            conn.execute('drop index confirmation_one_active_attempt')
            conn.execute("create unique index confirmation_one_active_attempt on confirmation_execution_authorities_v1(confirmation_id) "
                         "where phase in ('PREWRITE','ADMITTED','RECONCILIATION_REQUIRED')")
            before = conn.execute("select pg_get_indexdef('confirmation_one_active_attempt'::regclass)").fetchone()[0]
            # A real duplicate lowercase active row proves the mutated guard is ineffective.
            conn.execute(duplicate, ('duplicate_bad_predicate', 'prewrite'))
            self.assertEqual(conn.execute('select count(*) from confirmation_execution_authorities_v1').fetchone()[0], 2)
            probe = _probe_postgres_schema_contract(conn.cursor(), migrations)
            self.assertEqual(conn.execute("select pg_get_indexdef('confirmation_one_active_attempt'::regclass)").fetchone()[0], before)
            self.assertEqual(probe['status'], 'blocked', probe)
            self.assertIn('confirmation_one_active_attempt', probe['missing_authority_guards'])


if __name__=='__main__':
    owned.SupportPostgresTests=AuthorityImportTests
    raise SystemExit(owned.main())
