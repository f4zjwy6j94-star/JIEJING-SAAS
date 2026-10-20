#!/usr/bin/env python3
"""Persistent zero-write recovery and exact new-pending lineage."""
import copy
import json
from dataclasses import replace
import unittest
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter, build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied
from jiejing_runtime.execution import ExecutionService


class ReapprovalTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture
    claim=fixtures.EbayExecutionAuthorityTests.claim

    def test_active_prewrite_does_not_offer_new_confirmation(self):
        self.publish_fixture(); self.claim()
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(summary['next_action'],'wait_for_current_attempt')

    def test_raw_item_cannot_assert_a_recovery_link(self):
        self.publish_fixture()
        with self.assertRaises(PermissionError):
            self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-link',
                action_type='publish_listing',title='Untrusted recovery link',item={**self.record['item'],
                'replaces_confirmation_id':self.record['confirmation_id']})

    def test_historical_execution_is_not_misreported_as_zero_write(self):
        self.publish_fixture()
        task=self.repo.create_task(company_id=self.company,store_id=self.store,user_id=self.user,
            task_type='listing',title='Historical synthetic execution',input_data={})
        historical={**self.record,'task_id':task['task_id']}
        self.repo.save_execution_result(confirmation=historical,result={'status':'submission_unknown','action_type':'publish_listing',
            'platform_result':{},'secret_exposed':False})
        with self.repo._connect() as conn:
            conn.execute("update confirmations set status='needs_revision' where confirmation_id=?",(self.record['confirmation_id'],))
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertFalse(summary['zero_write_proven'])
        self.assertEqual(summary['next_action'],'reconcile_read_only')

    def test_unclaimed_approved_normal_control_is_zero_write(self):
        self.publish_fixture()
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertTrue(summary['zero_write_proven'])
        self.assertFalse(summary['automatic_retry_allowed'])

    def test_empty_operation_state_is_not_zero_write_proof(self):
        self.publish_fixture(); claimed=self.claim()
        with self.repo._connect() as conn:
            row=conn.execute('select operation_state_json from confirmation_execution_authorities_v1 where attempt_id=?',
                (claimed['_execution_permit']._attempt,)).fetchone()
            state=json.loads(row['operation_state_json']); state['operations']=[]
            conn.execute("update confirmation_execution_authorities_v1 set operation_state_json=? where attempt_id=?",
                (json.dumps(state),claimed['_execution_permit']._attempt))
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertFalse(summary['zero_write_proven'])
        self.assertEqual(summary['next_action'],'reconcile_read_only')

    def test_completed_attempt_is_displayed_as_completed_not_unknown(self):
        request,connection,settings=self.publish_fixture(); claimed=self.claim()
        adapter=EbayWriteHttpAdapter(settings,transport=lambda request,timeout:(200,{},b'{"offerId":"offer-done","listingId":"listing-done"}'))
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            result=adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        self.assertEqual(result['status'],'published_to_ebay')
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        self.assertEqual(summary['status'],'execution_completed')
        self.assertEqual(summary['next_action'],'view_receipt')
        self.assertEqual(summary['completed_operation_count'],3)

    def blocked(self):
        request,connection,settings=self.publish_fixture(); claimed=self.claim()
        self.before=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        def token(**_):
            self.repo.set_user_access_status(user_id=self.user,status='disabled')
            return {'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}
        def forbidden(*args,**kwargs): raise AssertionError('Zero-write recovery sent a provider request')
        adapter=EbayWriteHttpAdapter(settings,transport=forbidden)
        with patch.object(adapter,'_resolve_access_token',side_effect=token),self.assertRaises(EbayExecutionDenied):
            adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        self.repo.set_user_access_status(user_id=self.user,status='active')

    def replacement(self, **overrides):
        arguments=dict(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-reprepare',
            action_type='publish_listing',title='Current re-prepared product',item=copy.deepcopy(self.record['item']),
            created_by=self.user,replaces_confirmation_id=self.record['confirmation_id'])
        arguments.update(overrides)
        return self.repo.create_confirmation(**arguments)

    def test_zero_write_new_pending_preserves_history_and_requires_new_approval(self):
        self.blocked(); new=self.replacement()
        self.assertNotEqual(new['confirmation_id'],self.record['confirmation_id'])
        self.assertEqual(new['status'],'pending'); self.assertIsNone(new['decided_by']); self.assertIsNone(new['decided_at'])
        self.assertEqual(new['item']['replaces_confirmation_id'],self.record['confirmation_id'])
        old=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        for key in ('item','decided_by','decided_at','decision_note'): self.assertEqual(old[key],self.before[key])
        with self.repo._connect() as conn:
            approvals=conn.execute('select confirmation_id from confirmation_approval_authorities_v1 where confirmation_id in (?,?)',
                (new['confirmation_id'],old['confirmation_id'])).fetchall()
        self.assertEqual([row['confirmation_id'] for row in approvals],[old['confirmation_id']])
        epochs=self.repo.access_session_epochs(user_id=self.user,company_id=self.company)
        request=replace(self.request,confirmation_id=new['confirmation_id'])
        args=dict(company_id=self.company,confirmation_id=new['confirmation_id'],user_id=self.user,expected_access_epochs=epochs,
            operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[self.connection]))
        with self.assertRaises(ValueError): self.repo.claim_external_execution(**args)
        self.repo.decide_confirmation(company_id=self.company,confirmation_id=new['confirmation_id'],decision='approve',
            decided_by=self.user,note='A genuinely new approval.',expected_access_epochs=epochs)
        self.assertTrue(self.repo.claim_external_execution(**args)['external_execution_claimed'])
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=old['confirmation_id'])
        self.assertEqual(summary['replacement_confirmation_id'],new['confirmation_id'])

    def test_duplicate_replacement_cannot_create_another_pending(self):
        self.blocked(); self.replacement()
        with self.assertRaises(PermissionError): self.replacement()

    def test_replacement_cannot_change_exact_product_or_action(self):
        self.blocked(); changed=copy.deepcopy(self.record['item']); changed['publish_payload']['listing']['sku']='OTHER-SKU'
        with self.assertRaises(PermissionError): self.replacement(item=changed)
        with self.assertRaises(PermissionError): self.replacement(action_type='save_ebay_listing_draft')

    def test_active_or_unknown_attempt_cannot_prepare_linked_replacement(self):
        request,connection,settings=self.publish_fixture(); claimed=self.claim()
        with self.assertRaises(PermissionError): self.replacement()
        def timeout(*args,**kwargs): raise TimeoutError('Synthetic admitted timeout')
        adapter=EbayWriteHttpAdapter(settings,transport=timeout)
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        with self.assertRaises(PermissionError): self.replacement()

    def denial(self, **overrides):
        current=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        args=dict(company_id=self.company,store_id=self.store,confirmation_id=self.record['confirmation_id'],
            expected_confirmation=current,reason_code='approval_authority_missing_reapproval_required')
        args.update(overrides)
        return self.repo._record_ebay_preclaim_denial(**args)

    def denial_audit(self):
        with self.repo._connect() as conn:
            return [dict(row) for row in conn.execute('select * from audit_logs order by audit_id').fetchall()]

    def test_preclaim_denial_exact_scope_and_reason_reject_without_any_new_event(self):
        self.publish_fixture();before=self.denial_audit()
        current=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        for changes in ({'company_id':'other-company'},{'store_id':'other-store'},
                {'confirmation_id':'unknown-confirmation'},{'reason_code':'untrusted-private-message'},
                {'expected_confirmation':{**current,'action_type':'cleanup_test_listing'}},
                {'expected_confirmation':{**current,'item':{'sku':'other-item'}}}):
            with self.subTest(changes=tuple(changes)),self.assertRaises((KeyError,PermissionError)):
                self.denial(**changes)
            self.assertEqual(self.denial_audit(),before)

    def test_malformed_denial_audit_fails_closed_without_rewriting_history(self):
        self.publish_fixture();self.denial()
        for damaged in ('{private-invalid-json', b'\xff', 'null', '[]', '{"details":[]}',
                '{"details":{"reason_code":[]}}', '{"details":{"reason_code":{}}}'):
            with self.subTest(damaged=repr(damaged)):
                with self.repo._connect() as conn:
                    conn.execute("update audit_logs set audit_json=? where target_id=? and action_type='external_execution.preclaim_denied'",
                        (damaged,self.record['confirmation_id']))
                before=self.denial_audit()
                listed=self.repo.list_confirmations(company_id=self.company)
                current=next(row for row in listed if row['confirmation_id']==self.record['confirmation_id'])
                summary=current['execution_recovery']
                self.assertEqual(summary['reason_code'],'approval_authority_binding_changed_reapproval_required')
                self.assertNotIn('private-invalid-json',json.dumps(summary))
                with self.assertRaisesRegex(PermissionError,'approval_authority_binding_changed_reapproval_required'): self.claim()
                self.assertEqual(self.denial_audit(),before)

    def test_preclaim_denial_does_not_replace_an_existing_prewrite_or_unknown_attempt(self):
        request,connection,settings=self.publish_fixture();claimed=self.claim();before=self.denial_audit()
        summary=self.denial()
        self.assertEqual(summary['next_action'],'wait_for_current_attempt');self.assertEqual(self.denial_audit(),before)
        adapter=EbayWriteHttpAdapter(settings,transport=lambda *args:(_ for _ in ()).throw(TimeoutError('Synthetic unknown')))
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        before=self.denial_audit();summary=self.denial()
        self.assertFalse(summary['zero_write_proven']);self.assertTrue(summary['provider_result_unknown'])
        self.assertEqual(summary['next_action'],'reconcile_read_only');self.assertEqual(self.denial_audit(),before)

    def test_unresolved_other_attempt_is_not_zero_write_recovery_for_an_unclaimed_new_id(self):
        request,connection,settings=self.publish_fixture();self.claim()
        other=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-prior',
            action_type='publish_listing',title='Other approved ID same SKU',item=copy.deepcopy(self.record['item']))
        other=self.repo.decide_confirmation(company_id=self.company,confirmation_id=other['confirmation_id'],
            decision='approve',decided_by=self.user,note='Independent approval.',expected_access_epochs=self.epochs)
        other_request=replace(request,confirmation_id=other['confirmation_id'],confirmed_at=other['decided_at'])
        with self.assertRaisesRegex(PermissionError,'ebay_execution_prior_outcome_unresolved'):
            self.repo.claim_external_execution(company_id=self.company,confirmation_id=other['confirmation_id'],user_id=self.user,
                expected_access_epochs=self.epochs,operation_plan=build_ebay_execution_plan(request=other_request,
                    marketplace_id='EBAY_US',connections=[connection]))
        before=self.denial_audit()
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=other['confirmation_id'],
            reason_code='ebay_execution_prior_outcome_unresolved')
        self.assertFalse(summary['zero_write_proven']);self.assertEqual(summary['next_action'],'reconcile_read_only')
        fresh=fixtures.SaaSRepository(self.repo.db_path,database_engine='sqlite',database_url='')
        fresh_summary=fresh.ebay_execution_recovery(company_id=self.company,confirmation_id=other['confirmation_id'])
        listed=next(row for row in fresh.list_confirmations(company_id=self.company) if row['confirmation_id']==other['confirmation_id'])
        self.assertFalse(fresh_summary['zero_write_proven']);self.assertEqual(fresh_summary['next_action'],'reconcile_read_only')
        self.assertEqual(listed['execution_recovery'],fresh_summary)
        with self.assertRaisesRegex(PermissionError,'ebay_reapproval_zero_write_required'):
            fresh.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-no-bypass',
                action_type='publish_listing',title='Cannot reapprove over unresolved resource',item=copy.deepcopy(other['item']),
                replaces_confirmation_id=other['confirmation_id'])
        self.assertEqual(self.denial_audit(),before)

    def test_unresolved_other_sku_does_not_block_independent_normal_approved_control(self):
        request,connection,settings=self.publish_fixture();self.claim()
        item=copy.deepcopy(self.record['item']);item['publish_payload']['listing']['sku']='INDEPENDENT-SKU'
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-independent',
            action_type='publish_listing',title='Different SKU',item=item)
        record=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],
            decision='approve',decided_by=self.user,note='Different independent SKU.',expected_access_epochs=self.epochs)
        summary=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=record['confirmation_id'])
        self.assertTrue(summary['zero_write_proven']);self.assertEqual(summary['reason_code'],'')
        request=replace(request,confirmation_id=record['confirmation_id'],confirmed_at=record['decided_at'],payload=item['publish_payload'])
        claimed=self.repo.claim_external_execution(company_id=self.company,confirmation_id=record['confirmation_id'],user_id=self.user,
            expected_access_epochs=self.epochs,operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[connection]))
        self.assertTrue(claimed['external_execution_claimed'])

    def test_retired_zero_old_record_keeps_exact_link_when_replacement_becomes_unknown(self):
        self.publish_fixture();self.denial();new=self.replacement()
        new=self.repo.decide_confirmation(company_id=self.company,confirmation_id=new['confirmation_id'],
            decision='approve',decided_by=self.user,note='New independent decision.',expected_access_epochs=self.epochs)
        request=replace(self.request,confirmation_id=new['confirmation_id'],confirmed_at=new['decided_at'])
        claimed=self.repo.claim_external_execution(company_id=self.company,confirmation_id=new['confirmation_id'],user_id=self.user,
            expected_access_epochs=self.epochs,operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[self.connection]))
        def check_link():
            old=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=self.record['confirmation_id'])
            self.assertTrue(old['zero_write_proven']);self.assertEqual(old['next_action'],'view_replacement')
            self.assertEqual(old['replacement_confirmation_id'],new['confirmation_id'])
        check_link()
        adapter=EbayWriteHttpAdapter(self.settings,transport=lambda *args:(_ for _ in ()).throw(TimeoutError('Synthetic unknown')))
        with patch.object(adapter,'_resolve_access_token',return_value={'ok':True,'access_token':'B1-SYNTHETIC','source':'injected'}):
            adapter.publish_listing(request=request,preflight=ExecutionService(demo_mode=False).preflight(request),
                connections=[self.connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=claimed['_execution_permit'])
        check_link()
        active=self.repo.ebay_execution_recovery(company_id=self.company,confirmation_id=new['confirmation_id'])
        self.assertFalse(active['zero_write_proven']);self.assertEqual(active['next_action'],'reconcile_read_only')

    def test_preclaim_denial_creates_only_linked_pending_requiring_independent_approval(self):
        self.publish_fixture();before=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        with self.repo._connect() as conn:
            approvals=[dict(row) for row in conn.execute('select * from confirmation_approval_authorities_v1 order by authority_id')]
        self.denial();new=self.replacement()
        self.assertEqual(new['status'],'pending');self.assertIsNone(new['decided_by']);self.assertIsNone(new['decided_at'])
        retained=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.record['confirmation_id'])
        for key in ('item','decided_by','decided_at','decision_note'): self.assertEqual(retained[key],before[key])
        with self.repo._connect() as conn:
            self.assertEqual([dict(row) for row in conn.execute('select * from confirmation_approval_authorities_v1 order by authority_id')],approvals)
        request=replace(self.request,confirmation_id=new['confirmation_id'])
        with self.assertRaises(ValueError):
            self.repo.claim_external_execution(company_id=self.company,confirmation_id=new['confirmation_id'],user_id=self.user,
                expected_access_epochs=self.epochs,operation_plan=build_ebay_execution_plan(request=request,marketplace_id='EBAY_US',connections=[self.connection]))


if __name__=='__main__': unittest.main(verbosity=2)
