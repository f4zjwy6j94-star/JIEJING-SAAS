#!/usr/bin/env python3
"""Complete ordered real cleanup transport; no targets inferred at send time."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
from jiejing_runtime.execution import ExecutionService
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter,build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied


class CleanupAdmissionTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture

    def prepare(self, malformed=False):
        request,connection,settings=self.publish_fixture()
        plan={'status':'plan_only','confirmation_required':True,'operations':[
            {'operation':'end_listing','listing_id':'listing-cleanup','writes_to_ebay':True},
            {'operation':'delete_offer','offer_id':'offer-cleanup','writes_to_ebay':True},
            {'operation':'delete_inventory_item','sku':'B1-001','writes_to_ebay':True}]}
        if malformed: plan['operations'][-1].pop('sku')
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-cleanup',
            item={'source_publish_confirmation_id':self.record['confirmation_id'],'cleanup_plan':plan},
            action_type='cleanup_test_listing',title='B1 exact cleanup')
        approved=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],decision='approve',
            decided_by=self.user,note='Exact cleanup decision.',expected_access_epochs=self.epochs)
        request=replace(request,action_type='cleanup_test_listing',payload={'cleanup_plan':plan},confirmation_id=record['confirmation_id'],confirmed_at=approved['decided_at'])
        minted=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[connection])
        claimed=self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=self.user,
            expected_access_epochs=self.epochs,operation_plan=minted)
        self.request,self.settings,self.connection,self.permit,self.record=request,settings,connection,claimed['_execution_permit'],record

    def execute(self,token_hook=None,transport_hook=None):
        calls=[]; self.calls=calls
        def transport(request,timeout):
            calls.append((request.get_method(),request.full_url,json.loads(request.data or b'{}')))
            if transport_hook: return transport_hook(len(calls))
            return 204,{},b''
        def token(**_):
            if token_hook: token_hook()
            return {'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}
        adapter=EbayWriteHttpAdapter(self.settings,transport=transport)
        preflight=ExecutionService(demo_mode=False).preflight(self.request)
        self.assertEqual(preflight['status'],'ready_for_platform_adapter')
        with patch.object(adapter,'_resolve_access_token',side_effect=token):
            return adapter.execute_cleanup_plan(request=self.request,preflight=preflight,connections=[self.connection],secret_refs=[],
                marketplace_id='EBAY_US',execution_permit=self.permit)

    def test_normal_all_three_exact_operations(self):
        self.prepare(); result=self.execute()
        self.assertEqual([c[0] for c in self.calls],['POST','DELETE','DELETE'])
        self.assertEqual([c[1].split('/sell/inventory/v1/')[1] for c in self.calls],
                         ['offer/offer-cleanup/withdraw','offer/offer-cleanup','inventory_item/B1-001'])
        self.assertTrue(all(c[2]=={} for c in self.calls))
        self.assertEqual(result['status'],'cleanup_completed')

    def test_token_wait_revocation_blocks_first_cleanup_write(self):
        self.prepare()
        with self.assertRaises(EbayExecutionDenied):
            self.execute(token_hook=lambda:self.repo.set_user_access_status(user_id=self.user,status='disabled'))
        self.assertEqual(self.calls,[])

    def test_missing_last_target_rejected_before_first_write(self):
        with self.assertRaises(PermissionError): self.prepare(malformed=True)
        with self.repo._connect() as conn:
            self.assertEqual(conn.execute('select count(*) as n from confirmation_execution_authorities_v1').fetchone()['n'],0)

    def test_post_claim_target_order_change_never_sends(self):
        self.prepare(); self.request.payload['cleanup_plan']['operations'].reverse()
        with self.assertRaises(EbayExecutionDenied): self.execute()
        self.assertEqual(self.calls,[])

    def test_first_cleanup_timeout_never_sends_later_operations(self):
        self.prepare()
        def timeout(index): raise TimeoutError('Synthetic cleanup timeout')
        self.execute(transport_hook=timeout)
        self.assertEqual(len(self.calls),1)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertTrue(summary['provider_result_unknown'])
        self.assertFalse(summary['automatic_retry_allowed'])

    def test_first_success_then_revocation_keeps_receipt_and_stops(self):
        self.prepare()
        def revoke_after_first(index):
            self.repo.set_user_access_status(user_id=self.user,status='disabled')
            return 204,{},b''
        with self.assertRaises(EbayExecutionDenied): self.execute(transport_hook=revoke_after_first)
        self.assertEqual(len(self.calls),1)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(summary['completed_operation_count'],1)
        self.assertTrue(summary['partial_execution'])
        self.assertFalse(summary['zero_write_proven'])

    def test_first_success_second_unknown_keeps_receipt_and_stops(self):
        self.prepare()
        def timeout_second(index):
            if index==2: raise TimeoutError('Synthetic second cleanup timeout')
            return 204,{},b''
        self.execute(transport_hook=timeout_second)
        self.assertEqual(len(self.calls),2)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(summary['completed_operation_count'],1)
        self.assertEqual(summary['submitted_operation_count'],2)
        self.assertTrue(summary['provider_result_unknown'])
        self.assertFalse(summary['automatic_retry_allowed'])


if __name__=='__main__': unittest.main(verbosity=2)
