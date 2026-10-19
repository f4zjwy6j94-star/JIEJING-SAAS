#!/usr/bin/env python3
"""Explicit bounded recovery of durable, never-admitted B1 operations."""
import copy
from datetime import datetime,timedelta,timezone
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import test_jiejing_ebay_execution_authority as fixtures
import test_jiejing_ebay_scoped_admission as scoped
import test_jiejing_ebay_cleanup_admission as cleanup
from jiejing_runtime.execution import ExecutionService
from jiejing_saas.confirmation_authority import item_digest
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
import jiejing_saas.ebay_execution_authority as authority


class PrewriteRecoveryTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture
    claim=fixtures.EbayExecutionAuthorityTests.claim
    scoped=scoped.ScopedAdmissionTests.scoped

    def prepare(self):
        self.publish_fixture();self.permit=self.claim()['_execution_permit']

    def attempt(self):
        with self.repo._connect() as conn:
            row=dict(conn.execute('select * from confirmation_execution_authorities_v1 where attempt_id=?',
                (self.permit._attempt,)).fetchone())
        return row,json.loads(row['operation_state_json'])

    def clock(self,seconds):
        stamp=self.attempt()[0]['created_at']
        if isinstance(stamp,str): stamp=datetime.fromisoformat(stamp)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                value=stamp+timedelta(seconds=seconds)
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        return patch.object(authority,'datetime',Clock)

    def summary(self):
        return self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])

    def replacement(self,**overrides):
        args=dict(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-bounded-recovery',
            action_type=self.record['action_type'],title='Fresh exact pending after explicit retirement',
            item=copy.deepcopy(self.record['item']),created_by=self.user,replaces_confirmation_id=self.record['confirmation_id'])
        args.update(overrides)
        return self.repo.create_confirmation(**args)

    def assert_recovered(self):
        before=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        with self.clock(61):
            summary=self.summary()
            self.assertEqual(summary['next_action'],'prepare_reapproval')
            self.assertEqual(summary['status'],'execution_prewrite_recovery_available')
            self.assertTrue(summary['zero_write_proven'])
            new=self.replacement()
        self.assertEqual(new['status'],'pending');self.assertIsNone(new['decided_by'])
        old=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(old['status'],'needs_revision')
        for key in ('item','decided_by','decided_at','decision_note'): self.assertEqual(old[key],before[key])
        self.assertEqual(self.attempt()[0]['phase'],'blocked_before_call')
        return new

    def test_lost_legacy_prewrite_can_prepare_a_new_pending(self):
        self.prepare();self.assert_recovered()

    def test_fresh_active_and_exact_sixty_second_boundary_remain_waiting(self):
        self.prepare()
        for seconds in (0,30,60):
            with self.subTest(seconds=seconds),self.clock(seconds):
                self.assertEqual(self.summary()['next_action'],'wait_for_current_attempt')
                with self.assertRaises(PermissionError): self.replacement()
        self.assertEqual(self.attempt()[0]['phase'],'prewrite')

    def test_one_microsecond_past_sixty_seconds_is_eligible(self):
        self.prepare()
        with self.clock(60.000001):
            self.assertEqual(self.summary()['next_action'],'prepare_reapproval')
            self.assertEqual(self.replacement()['status'],'pending')

    def test_aware_datetime_creation_type_is_supported(self):
        self.prepare();row,state=self.attempt()
        row['created_at']=datetime.fromisoformat(row['created_at'])
        with self.clock(60.000001):
            self.assertEqual(authority.recovery(row,state)['next_action'],'prepare_reapproval')

    def test_readonly_validation_does_not_retire_expired_attempt(self):
        self.prepare()
        with self.clock(61):
            self.repo.validate_ebay_replacement(company_id=self.company,store_id=self.store,
                action_type=self.record['action_type'],item=self.record['item'],
                replaces_confirmation_id=self.record['confirmation_id'])
        self.assertEqual(self.attempt()[0]['phase'],'prewrite')
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])['status'],
            'external_execution_processing_manual_reconcile')

    def test_failed_new_confirmation_insert_rolls_back_retirement(self):
        self.prepare();before=self.attempt()
        with self.clock(61),self.assertRaisesRegex(ValueError,'confirmation_create_conflict'):
            self.replacement(confirmation_id=self.record['confirmation_id'])
        self.assertEqual(self.attempt(),before)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])['status'],
            'external_execution_processing_manual_reconcile')

    def test_old_permit_cannot_send_after_explicit_retirement(self):
        self.prepare();self.assert_recovered();calls=[]
        adapter=EbayWriteHttpAdapter(self.settings,transport=lambda req,timeout:(calls.append(req.get_method()) or (200,{},b'{}')))
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}),self.assertRaises(EbayExecutionDenied):
            adapter.publish_listing(request=self.request,preflight=ExecutionService(demo_mode=False).preflight(self.request),
                connections=[self.connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=self.permit)
        self.assertEqual(calls,[])

    def test_invalid_naive_or_future_creation_time_never_proves_expiry(self):
        self.prepare();row,state=self.attempt()
        values=(None,'','broken','2020-01-01T00:00:00',datetime(2020,1,1),
            (datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        for value in values:
            with self.subTest(value=repr(value)):
                self.assertEqual(authority.recovery({**row,'created_at':value},state)['next_action'],'wait_for_current_attempt')

    def test_real_admitted_unknown_is_not_reclaimed_by_time(self):
        self.prepare();calls=[]
        def timeout(request,timeout): calls.append(request.get_method());raise TimeoutError('Synthetic timeout')
        adapter=EbayWriteHttpAdapter(self.settings,transport=timeout)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            adapter.publish_listing(request=self.request,preflight=ExecutionService(demo_mode=False).preflight(self.request),
                connections=[self.connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=self.permit)
        self.assertEqual(calls,['PUT'])
        with self.clock(86400):
            self.assertEqual(self.summary()['next_action'],'reconcile_read_only')
            with self.assertRaises(PermissionError): self.replacement()

    def test_incomplete_operation_log_is_not_reclaimed_by_time(self):
        self.prepare()
        with self.repo._connect() as conn:
            row,state=self.attempt();state['operations']=[]
            conn.execute('update confirmation_execution_authorities_v1 set operation_state_json=? where attempt_id=?',
                (json.dumps(state),self.permit._attempt))
        with self.clock(61):
            self.assertFalse(self.summary()['zero_write_proven'])
            with self.assertRaises(PermissionError): self.replacement()

    def test_lost_cleanup_prewrite_can_prepare_exact_new_pending(self):
        cleanup.CleanupAdmissionTests.prepare(self);self.assert_recovered()

    def test_lost_draft_prewrite_can_prepare_exact_new_pending(self):
        repo,scope,record,epochs,request,settings,credential=self.scoped('save_ebay_listing_draft')
        adapter=EbayWriteHttpAdapter(settings,transport=lambda req,timeout:(200,{},b'{"offers":[]}'))
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            prepared=adapter.prepare_listing_draft(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                credential_boundary=credential,marketplace_id='EBAY_US')
        _,capability=repo.claim_unpublished_draft_execution(company_id=scope['company_id'],confirmation_id=record['confirmation_id'],
            user_id=scope['user_id'],expected_binding=prepared.claim_binding(),expected_access_epochs=epochs,operation_plan=prepared.execution_plan())
        self.repo,self.company,self.store,self.user,self.record=repo,scope['company_id'],scope['store_id'],scope['user_id'],record
        self.permit=capability._execution_permit
        self.assert_recovered()
        with self.assertRaises((PermissionError,ValueError)): capability.consume()

    def test_lost_location_prewrite_can_prepare_exact_new_pending(self):
        repo,scope,old,epochs,request,settings,credential=self.scoped('save_ebay_listing_draft')
        payload=scoped.location_payload()
        created=repo.create_ebay_inventory_location_confirmation(company_id=scope['company_id'],store_id=scope['store_id'],
            user_id=scope['user_id'],location_payload=payload,payload_sha256=item_digest(payload))
        record=repo.decide_confirmation(company_id=scope['company_id'],confirmation_id=created['confirmation']['confirmation_id'],
            decision='approve',decided_by=scope['user_id'],note='Location recovery decision',expected_access_epochs=epochs)
        def missing(req,timeout):
            raise HTTPError(req.full_url,404,'missing',{},io.BytesIO(b'{"errors":[{"errorId":25805,"domain":"API_INVENTORY","category":"REQUEST"}]}'))
        adapter=EbayWriteHttpAdapter(settings,transport=missing)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            prepared=adapter.prepare_inventory_location(confirmation=record,location_payload=payload,credential_boundary=credential,marketplace_id='EBAY_US')
        claimed=repo.claim_ebay_inventory_location_execution(company_id=scope['company_id'],store_id=scope['store_id'],
            confirmation_id=record['confirmation_id'],user_id=scope['user_id'],expected_payload_sha256=item_digest(payload),
            expected_claim_binding=prepared.claim_binding(),marketplace_id='EBAY_US',expected_access_epochs=epochs,operation_plan=prepared.execution_plan())
        self.repo,self.company,self.store,self.user,self.record=repo,scope['company_id'],scope['store_id'],scope['user_id'],record
        self.permit=claimed['_execution_permit'];self.assert_recovered()


if __name__=='__main__': unittest.main(verbosity=2)
