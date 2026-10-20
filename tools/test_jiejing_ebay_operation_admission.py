#!/usr/bin/env python3
"""Actual injected eBay transport tests for exact operations and receipts."""
import json
import copy
from dataclasses import replace
import unittest
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
from jiejing_runtime.execution import ExecutionService
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
import jiejing_saas.ebay_write_adapter as adapter_module
import jiejing_saas.ebay_execution_authority as authority


class OperationAdmissionTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture
    claim=fixtures.EbayExecutionAuthorityTests.claim

    def attempt(self, permit):
        with self.repo._connect() as conn:
            row=conn.execute('select * from confirmation_execution_authorities_v1 where attempt_id=?',(permit._attempt,)).fetchone()
            return dict(row),json.loads(row['operation_state_json'])

    def publish(self, behavior, token_hook=None, after_claim=None):
        request,connection,settings=self.publish_fixture()
        permit=self.claim()['_execution_permit']
        calls=[]
        def transport(http_request,timeout):
            calls.append((http_request.get_method(),http_request.full_url,json.loads(http_request.data or b'{}')))
            return behavior(len(calls),http_request)
        adapter=EbayWriteHttpAdapter(settings,transport=transport)
        def token(**_):
            if token_hook: token_hook()
            return {'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}
        if after_claim: after_claim(request)
        self.calls,self.permit=calls,permit
        with patch.object(adapter,'_resolve_access_token',side_effect=token):
            return adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=permit)

    @staticmethod
    def success(index,request):
        return 200,{},json.dumps({'offerId':'offer-b1','listingId':'listing-b1'}).encode()

    def assert_unknown(self, submitted):
        row,state=self.attempt(self.permit)
        self.assertEqual(row['phase'],'reconciliation_required')
        self.assertEqual(len(self.calls),submitted)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertFalse(summary['zero_write_proven'])
        self.assertTrue(summary['provider_result_unknown'])
        self.assertFalse(summary['automatic_retry_allowed'])
        with self.assertRaises((PermissionError, ValueError)): self.claim()

    def test_b13_timeout_after_first_send_stays_unknown(self):
        def timeout(index,request): raise TimeoutError('synthetic transport timeout')
        self.publish(timeout)
        self.assert_unknown(1)

    def test_b13_success_http_decode_failure_stays_unknown(self):
        self.publish(lambda index,request:(200,{},b'not-json'))
        self.assert_unknown(1)

    def test_b13_create_offer_missing_id_stops_publish(self):
        self.publish(lambda index,request:(200,{},b'{}'))
        self.assert_unknown(2)

    def test_b13_malicious_offer_segment_stops_publish(self):
        self.publish(lambda index,request:(200,{},b'{"offerId":"elsewhere/offer"}'))
        self.assert_unknown(2)

    def test_b14_successful_first_operation_retained_after_revocation(self):
        def behavior(index,request):
            if index==1: self.repo.set_user_access_status(user_id=self.user,status='disabled')
            return self.success(index,request)
        with self.assertRaises(EbayExecutionDenied) as denied: self.publish(behavior)
        self.assertEqual(len(self.calls),1)
        row,state=self.attempt(self.permit)
        self.assertEqual(row['phase'],'reconciliation_required')
        self.assertEqual(state['operations'][0]['status'],'succeeded')
        self.assertEqual(state['operations'][1]['status'],'planned')
        self.assertTrue(denied.exception.recovery['partial_execution'])
        self.assertFalse(denied.exception.recovery['zero_write_proven'])

    def test_actual_body_change_after_claim_is_not_authorized(self):
        original=adapter_module._inventory_item_body
        generated=[]
        def changed(payload):
            body=original(payload)
            generated.append(body)
            if len(generated)>1:
                body['availability']['shipToLocationAvailability']['quantity']=7
            return body
        with patch.object(adapter_module,'_inventory_item_body',side_effect=changed), self.assertRaises(EbayExecutionDenied):
            self.publish(self.success)
        self.assertEqual(self.calls,[])
        row,state=self.attempt(self.permit)
        self.assertEqual(row['phase'],'blocked_before_call')

    def test_connection_change_after_token_wait_is_not_authorized(self):
        def mutate():
            with self.repo._connect() as conn:
                conn.execute("update platform_connections set scopes_json='[]' where connection_id=?",(self.connection['connection_id'],))
        with self.assertRaises(EbayExecutionDenied): self.publish(self.success,token_hook=mutate)
        self.assertEqual(self.calls,[])

    def test_credential_reference_revoked_after_token_wait_is_not_authorized(self):
        def mutate():
            with self.repo._connect() as conn:
                conn.execute("update secret_refs set status='revoked' where secret_ref=?",(self.connection['secret_ref'],))
        with self.assertRaises(EbayExecutionDenied): self.publish(self.success,token_hook=mutate)
        self.assertEqual(self.calls,[])

    def test_new_confirmation_cannot_replay_an_unknown_product_plan(self):
        def timeout(index,request): raise TimeoutError('synthetic transport timeout')
        self.publish(timeout)
        self.assert_unknown(1)
        original=self.permit
        # A fresh ID and explicit decision must not hide unresolved submission
        # facts for the same exact store/product operation.
        with self.assertRaises(PermissionError):
            self.publish(self.success)
        row,state=self.attempt(original)
        self.assertEqual(row['phase'],'reconciliation_required')

    def fresh_claim(self, *, sku='B1-001', existing_offer=''):
        payload=copy.deepcopy(self.request.payload); payload['listing']['sku']=sku
        if existing_offer: payload['existing_ebay_draft']={'offer_id':existing_offer,'sku':sku}
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-other',
            item={'publish_payload':payload},action_type='publish_listing',title='Exact resource control')
        record=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],decision='approve',
            decided_by=self.user,note='Separate explicit decision.',expected_access_epochs=self.epochs)
        request=replace(self.request,payload=payload,confirmation_id=record['confirmation_id'])
        return self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=self.user,
            expected_access_epochs=self.epochs,operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[self.connection]))

    def test_active_prewrite_blocks_same_sku_but_not_other_product(self):
        self.publish_fixture(); self.claim()
        with self.assertRaises(PermissionError): self.fresh_claim()
        self.assertTrue(self.fresh_claim(sku='B1-OTHER')['external_execution_claimed'])

    def test_unknown_same_sku_existing_offer_branch_cannot_bypass(self):
        self.publish(lambda *args: (200,{},b'{}'))
        self.assert_unknown(2)
        with self.assertRaises(PermissionError): self.fresh_claim(existing_offer='different-offer')

    def test_unknown_other_store_does_not_block_normal_claim(self):
        def timeout(*args): raise TimeoutError('Synthetic timeout')
        self.publish(timeout); self.assert_unknown(1)
        self.store=self.repo.create_store(company_id=self.company,user_id=self.user,payload={'platform':'ebay'})['store_id']
        self.publish_fixture()
        self.assertTrue(self.claim()['external_execution_claimed'])

    def test_completed_plan_does_not_permanently_block_explicit_later_action(self):
        self.publish(self.success)
        self.assertTrue(self.fresh_claim(sku='B1-001')['external_execution_claimed'])

    def test_unrelated_permission_error_preserves_prewrite_facts_and_exception(self):
        sentinel='ebay_execution_credential_changed: unrelated dependency error'
        def after_claim(_):
            mocked=patch.object(self.repo,'_ebay_execution_connection_conn',side_effect=PermissionError(sentinel))
            mocked.start();self.addCleanup(mocked.stop)
        with self.assertRaises(PermissionError) as rejected:
            self.publish(self.success,after_claim=after_claim)
        self.assertIs(type(rejected.exception),PermissionError)
        self.assertEqual(str(rejected.exception),sentinel)
        row,state=self.attempt(self.permit)
        self.assertEqual(self.calls,[]);self.assertEqual(row['phase'],'prewrite')
        self.assertIsNone(row['admitted_at']);self.assertTrue(all(op['status']=='planned' for op in state['operations']))

    def test_corrupt_active_plan_cannot_hide_same_resource_from_new_id(self):
        self.publish_fixture();permit=self.claim()['_execution_permit']
        _,state=self.attempt(permit)
        state['plan']['product_sku']='POISONED-OTHER-SKU'
        state['plan']['operations'][0]['target']='/sell/inventory/v1/inventory_item/POISONED-OTHER-SKU'
        with self.repo._connect() as conn:
            conn.execute('update confirmation_execution_authorities_v1 set operation_state_json=? where attempt_id=?',
                (json.dumps(state),permit._attempt))
        with self.assertRaisesRegex(PermissionError,'prior_outcome_unresolved'): self.fresh_claim()

    def test_legacy_unproven_processing_blocks_same_resource_but_not_other_product(self):
        self.publish_fixture()
        with self.repo._connect() as conn:
            conn.execute("update confirmations set status='external_execution_processing_manual_reconcile' where confirmation_id=?",
                (self.record['confirmation_id'],))
        with self.assertRaisesRegex(PermissionError,'prior_outcome_unresolved'): self.fresh_claim()
        self.assertTrue(self.fresh_claim(sku='B1-OTHER')['external_execution_claimed'])

    def test_incomplete_unknown_graph_never_proves_another_resource_available(self):
        self.publish(lambda *_:(200,{},b'{}'))
        row,state=self.attempt(self.permit)
        malformed=[]
        empty=copy.deepcopy(state);empty['operations']=[];malformed.append(empty)
        missing=copy.deepcopy(state);missing['plan'].pop('marketplace_id');malformed.append(missing)
        receipt=copy.deepcopy(state);receipt['operations'][1]['receipt']['binding_sha256']='f'*64;malformed.append(receipt)
        for index,broken in enumerate(malformed):
            with self.subTest(index=index):
                with self.repo._connect() as conn:
                    conn.execute('update confirmation_execution_authorities_v1 set operation_state_json=? where attempt_id=?',
                        (json.dumps(broken),self.permit._attempt))
                before=self.attempt(self.permit)
                with self.assertRaisesRegex(PermissionError,'prior_outcome_unresolved'): self.fresh_claim(sku='OTHER-'+str(index))
                self.assertEqual(self.attempt(self.permit),before)

    def test_dynamic_offer_rejects_receipt_from_another_attempt(self):
        original=authority.record
        def record(permit,*,operation_index,result):
            receipt=original(permit,operation_index=operation_index,result=result)
            if operation_index==1:
                _,state=self.attempt(permit)
                state['operations'][1]['receipt']['attempt_id']='not-this-attempt'
                with self.repo._connect() as conn:
                    conn.execute('update confirmation_execution_authorities_v1 set operation_state_json=? where attempt_id=?',
                        (json.dumps(state),permit._attempt))
            return receipt
        with patch.object(authority,'record',side_effect=record),self.assertRaises(PermissionError): self.publish(self.success)
        self.assertEqual(len(self.calls),2)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertFalse(summary['zero_write_proven']);self.assertTrue(summary['provider_result_unknown'])


if __name__=='__main__':
    unittest.main(verbosity=2)
