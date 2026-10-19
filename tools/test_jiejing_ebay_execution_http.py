#!/usr/bin/env python3
"""Real loopback API -> real repository -> real adapter/injected transport."""
import copy
from datetime import datetime,timedelta
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
import test_jiejing_confirmation_authority_http as approval_http
from test_jiejing_new_ebay_account_publish_http_chain import _publish_payload
from test_jiejing_controlled_existing_draft_publish_http import _post, _get
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter
import jiejing_saas.ebay_execution_authority as authority


class ExecutionHTTPTests(unittest.TestCase):
    _close_server=approval_http.ApprovalAuthorityHTTPTests._close_server
    _execute=approval_http.ApprovalAuthorityHTTPTests._execute
    _assert_valid_preflight=approval_http.ApprovalAuthorityHTTPTests._assert_valid_preflight

    def setUp(self):
        approval_http.ApprovalAuthorityHTTPTests.setUp(self)
        self.calls=[]; self.token_hook=None; self.timeout=False
        owner=self
        class InjectedAdapter(EbayWriteHttpAdapter):
            def __init__(self,settings): super().__init__(settings,transport=owner.transport)
            def _resolve_access_token(self,**kwargs):
                if owner.token_hook: owner.token_hook()
                return {'ok':True,'access_token':'B1-SYNTHETIC-HTTP','source':'injected'}
        self.server.RequestHandlerClass.ebay_write_adapter_factory=InjectedAdapter
        self.addCleanup(lambda:self.assertEqual(self.server_errors,[]))

    def transport(self,request,timeout):
        self.calls.append((request.get_method(),request.full_url))
        if request.get_method()=='GET': return 200,{},b'{"offers":[]}'
        if self.timeout: raise TimeoutError('Synthetic HTTP-chain provider timeout')
        return 200,{},b'{"offerId":"offer-http","listingId":"listing-http"}'

    def fresh_session(self):
        self.token=self.server.RequestHandlerClass.sessions.create_token(user_id=self.user['user_id'],company_id=self.company,
            email=self.user['email'],access_epochs=self.repo.access_session_epochs(user_id=self.user['user_id'],company_id=self.company))

    def intake(self):
        item=self.confirmation['item']; payload=item['publish_payload']
        return _publish_payload(listing_project_identity=item['listing_project_identity'],
            product_fact_report_id=payload['publish_evidence']['refs']['product_fact_report_id'])

    def authority_state(self):
        with self.repo._connect() as conn:
            return {table:[dict(row) for row in conn.execute(
                f'select * from {table} where confirmation_id=? order by 1',(self.confirmation_id,)).fetchall()]
                for table in ('confirmations','confirmation_approval_authorities_v1',
                    'confirmation_execution_authorities_v1','external_execution_claims','execution_results')}

    def block_zero(self):
        self._assert_valid_preflight()
        self.token_hook=lambda:self.repo.set_user_access_status(user_id=self.user['user_id'],status='disabled')
        status,body,connection_error=self._execute()
        self.assertIsNone(connection_error);self.assertEqual(status,409)
        self.assertTrue(body['execution_recovery']['zero_write_proven']);self.assertEqual(self.calls,[])
        task=self.repo.get_task(company_id=self.company,task_id=self.confirmation['task_id'])
        self.assertEqual(task['status'],'needs_revision','A final-admission zero denial must not leave a reconciliation task')
        self.repo.set_user_access_status(user_id=self.user['user_id'],status='active'); self.fresh_session();self.token_hook=None
        return body

    def test_normal_http_actual_three_write_control(self):
        self._assert_valid_preflight()
        status,body,error=self._execute()
        self.assertEqual((status,error),(201,None));self.assertEqual(body['execution']['status'],'published_to_ebay')
        self.assertEqual([method for method,url in self.calls],['PUT','POST','POST'])
        self.assertEqual(self.repo.get_task(company_id=self.company,task_id=self.confirmation['task_id'])['status'],'completed')

    def test_late_revocation_json_and_exact_new_pending_http(self):
        old=copy.deepcopy(self.confirmation);self.block_zero()
        body=self.intake();body['replaces_confirmation_id']=self.confirmation_id
        status,result=_post(self.base_url,'/stores/'+self.store['store_id']+'/publish-confirmation',body,self.token)
        self.assertEqual(status,201,result);new=result['confirmation']
        self.assertEqual(new['status'],'pending');self.assertEqual(new['item']['replaces_confirmation_id'],self.confirmation_id)
        self.assertIsNone(new['decided_at']);self.assertEqual(self.calls,[])
        retained=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.confirmation_id)
        for key in ('decided_at','decided_by','decision_note','item'): self.assertEqual(retained[key],old[key])
        status,listed=_get(self.base_url,'/confirmations',self.token)
        self.assertEqual(status,200)
        old_card=next(card for card in listed['confirmations'] if card['confirmation_id']==self.confirmation_id)
        self.assertEqual(old_card['execution_recovery']['replacement_confirmation_id'],new['confirmation_id'])

    def test_unknown_result_json_cannot_prepare_new_pending(self):
        self.timeout=True
        status,body,error=self._execute()
        self.assertEqual((status,error),(201,None));summary=body['execution_recovery']
        self.assertFalse(summary['zero_write_proven']);self.assertTrue(summary['provider_result_unknown']);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.repo.get_task(company_id=self.company,task_id=self.confirmation['task_id'])['status'],'manual_reconcile_required')
        intake=self.intake();intake['replaces_confirmation_id']=self.confirmation_id
        status,result=_post(self.base_url,'/stores/'+self.store['store_id']+'/publish-confirmation',intake,self.token)
        self.assertEqual(status,409);self.assertFalse(result['execution_recovery']['zero_write_proven']);self.assertEqual(len(self.calls),1)

    def test_recovery_read_hint_cannot_unlock_unknown(self):
        self.timeout=True; self._execute(); self.timeout=False
        before=self.authority_state()
        status,body=_post(self.base_url,'/confirmations/'+self.confirmation_id+'/publish-recovery',{},self.token)
        self.assertEqual(status,201,body);self.assertFalse(body['publish_recovery']['safe_to_retry_publish'])
        self.assertFalse(body['execution_recovery']['zero_write_proven']);self.assertFalse(body['fresh_confirmation_required'])
        self.assertEqual(len([call for call in self.calls if call[0]!='GET']),1)
        self.assertEqual(self.authority_state(),before)

    def test_expired_zero_prewrite_recovery_read_does_not_retire_active_request(self):
        arrived,release=Event(),Event();token_calls=[]
        def token_hook():
            token_calls.append(1)
            if len(token_calls)==1:
                arrived.set();self.assertTrue(release.wait(30),'Owned execution was not released')
        self.token_hook=token_hook
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self._execute)
            try:
                self.assertTrue(arrived.wait(15),'The real claim did not reach the token wait')
                before=self.authority_state()
                stamp=datetime.fromisoformat(before['confirmation_execution_authorities_v1'][0]['created_at'])
                class Clock(datetime):
                    @classmethod
                    def now(cls,tz=None):
                        value=stamp+timedelta(seconds=61)
                        return value.astimezone(tz) if tz else value.replace(tzinfo=None)
                with patch.object(authority,'datetime',Clock):
                    status,body=_post(self.base_url,'/confirmations/'+self.confirmation_id+'/publish-recovery',{},self.token)
                self.assertEqual(status,201,body)
                self.assertTrue(body['execution_recovery']['zero_write_proven'])
                self.assertTrue(body['fresh_confirmation_required'])
                self.assertEqual(self.authority_state(),before)
                self.assertEqual([method for method,url in self.calls if method!='GET'],[])
            finally: release.set()
            status,body,error=pending.result(30)
        self.assertEqual((status,error),(201,None))
        self.assertEqual(body['execution']['status'],'published_to_ebay')
        self.assertEqual([method for method,url in self.calls if method!='GET'],['PUT','POST','POST'])

    def test_unrelated_permission_fault_is_not_flattened_into_reapproval(self):
        self.claim_fault=PermissionError('approval_authority_missing_reapproval_required: unrelated sentinel')
        self.assertEqual(self._execute(),(None,None,'RemoteDisconnected'))
        self.assertEqual(self.calls,[])
        self.assertEqual(self.server_errors,[{'type':'PermissionError','message':str(self.claim_fault)}])
        self.server_errors.clear()

    def cleanup_confirmation(self):
        plan={'status':'plan_only','confirmation_required':True,'operations':[
            {'operation':'withdraw_offer','offer_id':'offer-http-cleanup','writes_to_ebay':True},
            {'operation':'delete_offer','offer_id':'offer-http-cleanup','writes_to_ebay':True},
            {'operation':'delete_inventory_item','sku':'HTTP-CLEANUP','writes_to_ebay':True}]}
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store['store_id'],
            task_id=self.confirmation['task_id'],runtime_run_id='b1-http-cleanup',action_type='cleanup_test_listing',
            title='Exact HTTP cleanup',item={'source':'publish_recovery_cleanup_plan','cleanup_plan':plan,
                'source_publish_confirmation_id':self.confirmation_id})
        self.confirmation=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],
            decision='approve',decided_by=self.user['user_id'],note='Exact cleanup.',expected_access_epochs=self.repo.access_session_epochs(
                user_id=self.user['user_id'],company_id=self.company))
        self.confirmation_id=record['confirmation_id']

    def test_normal_cleanup_http_three_write_control(self):
        self.cleanup_confirmation()
        status,body,error=self._execute()
        self.assertEqual((status,error),(201,None));self.assertEqual(body['execution']['status'],'cleanup_completed')
        self.assertEqual([method for method,url in self.calls],['POST','DELETE','DELETE'])

    def revoke_between_claim_and_second_snapshot(self,cleanup=False):
        if cleanup: self.cleanup_confirmation()
        before=copy.deepcopy(self.confirmation)
        authority_before=self.authority_state()
        self.assertNotIn('approval_authority_id',before)
        committed,release=Event(),Event();original=self.repo.claim_external_execution
        def claim(**kwargs):
            result=original(**kwargs);committed.set()
            self.assertTrue(release.wait(10));return result
        with patch.object(self.repo,'claim_external_execution',side_effect=claim),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(self._execute)
            try:
                self.assertTrue(committed.wait(10),'The real claim never committed')
                with self.repo._connect() as conn:
                    conn.execute("update secret_refs set status='revoked' where secret_ref=?",(self.connection['secret_ref'],))
            finally: release.set()
            status,body,error=pending.result(15)
        try:
            self.assertEqual(self.calls,[])
            self.assertEqual((status,error),(409,None),str(self.server_errors))
            self.assertEqual(body['error'],'ebay_execution_credential_changed')
            self.assertTrue(body['execution_recovery']['zero_write_proven'])
            self.assertFalse(body['execution_recovery']['automatic_retry_allowed'])
            after=self.repo.get_confirmation(company_id=self.company,confirmation_id=self.confirmation_id)
            self.assertEqual(after['status'],'needs_revision')
            for key in ('decided_at','decided_by','decision_note','item'):
                self.assertEqual(after[key],before[key])
            self.assertNotIn('approval_authority_id',after)
            authority_after=self.authority_state()
            self.assertEqual(authority_after['confirmations'][0]['approval_authority_id'],
                authority_before['confirmations'][0]['approval_authority_id'])
            self.assertEqual(authority_after['confirmation_approval_authorities_v1'],
                authority_before['confirmation_approval_authorities_v1'])
            self.assertEqual(self.server_errors,[])
        finally: self.server_errors.clear()

    def test_publish_claim_to_second_snapshot_revocation_returns_zero_write_json(self):
        self.revoke_between_claim_and_second_snapshot()

    def test_cleanup_claim_to_second_snapshot_revocation_returns_zero_write_json(self):
        self.revoke_between_claim_and_second_snapshot(cleanup=True)

    def test_unrelated_second_snapshot_permission_error_is_not_domain_recovery(self):
        original=self.repo.ebay_execution_connections;calls=[]
        sentinel='ebay_execution_credential_changed: unrelated snapshot dependency'
        def snapshot(**kwargs):
            calls.append(1)
            if len(calls)==2: raise PermissionError(sentinel)
            return original(**kwargs)
        with patch.object(self.repo,'ebay_execution_connections',side_effect=snapshot):
            self.assertEqual(self._execute(),(None,None,'RemoteDisconnected'))
        self.assertEqual(len(calls),2);self.assertEqual(self.calls,[])
        self.assertEqual(self.server_errors,[{'type':'PermissionError','message':sentinel}])
        self.server_errors.clear()

    def test_preclaim_denial_survives_refresh_and_cannot_execute_old_approval(self):
        before=copy.deepcopy(self.confirmation)
        with self.repo._connect() as conn:
            approval_id=conn.execute('select approval_authority_id from confirmations where confirmation_id=?',
                (self.confirmation_id,)).fetchone()[0]
            conn.execute('update confirmations set approval_authority_id=NULL where confirmation_id=?',(self.confirmation_id,))
            audit_before=[dict(row) for row in conn.execute('select * from audit_logs where target_id=? order by audit_id',
                (self.confirmation_id,)).fetchall()]
        status,body,error=self._execute()
        self.assertEqual((status,error),(409,None));self.assertEqual(self.calls,[])
        reason='approval_authority_missing_reapproval_required'
        self.assertEqual(body['execution_recovery']['reason_code'],reason)
        status,listed=_get(self.base_url,'/confirmations',self.token)
        self.assertEqual(status,200)
        old=next(card for card in listed['confirmations'] if card['confirmation_id']==self.confirmation_id)
        self.assertEqual(old['execution_recovery']['reason_code'],reason,'A fresh GET must preserve the actual denial')
        self.assertEqual(old['execution_recovery']['next_action'],'prepare_reapproval')
        self.assertTrue(old['execution_recovery']['zero_write_proven'])
        for key in ('item','decided_by','decided_at','decision_note'): self.assertEqual(old[key],before[key])
        # Repairing a mutable projection cannot revive the explicitly retired
        # execution path; the approved history is retained, not re-authorized.
        with self.repo._connect() as conn:
            conn.execute('update confirmations set approval_authority_id=? where confirmation_id=?',(approval_id,self.confirmation_id))
        for _ in range(2):
            status,result,error=self._execute()
            self.assertEqual((status,error),(409,None));self.assertEqual(result['execution_recovery']['reason_code'],reason)
        self.assertEqual(self.calls,[])
        with self.repo._connect() as conn:
            audit_after=[dict(row) for row in conn.execute('select * from audit_logs where target_id=? order by audit_id',
                (self.confirmation_id,)).fetchall()]
        self.assertTrue(all(row in audit_after for row in audit_before))
        additions=[row for row in audit_after if row not in audit_before]
        self.assertEqual(len(additions),1);self.assertEqual(additions[0]['action_type'],'external_execution.preclaim_denied')
        self.assertEqual(additions[0]['company_id'],self.company);self.assertEqual(additions[0]['store_id'],self.store['store_id'])
        details=json.loads(additions[0]['audit_json'])['details']
        self.assertEqual(details['reason_code'],reason);self.assertFalse(details['secret_exposed'])
        status,again=_get(self.base_url,'/confirmations',self.token)
        self.assertEqual(status,200)
        with self.repo._connect() as conn:
            self.assertEqual([dict(row) for row in conn.execute('select * from audit_logs where target_id=? order by audit_id',
                (self.confirmation_id,)).fetchall()],audit_after,'GET must remain read-only')

    def test_preclaim_cleanup_denial_survives_refresh_with_immutable_approval(self):
        self.cleanup_confirmation();before=self.authority_state()
        with self.repo._connect() as conn:
            conn.execute('update confirmations set approval_authority_id=NULL where confirmation_id=?',(self.confirmation_id,))
        immutable=self.authority_state()
        status,body,error=self._execute()
        self.assertEqual((status,error),(409,None));self.assertEqual(self.calls,[])
        status,listed=_get(self.base_url,'/confirmations',self.token)
        old=next(card for card in listed['confirmations'] if card['confirmation_id']==self.confirmation_id)
        self.assertEqual(old['execution_recovery']['reason_code'],'approval_authority_missing_reapproval_required')
        self.assertEqual(old['execution_recovery']['next_action'],'prepare_reapproval')
        self.assertEqual(self.authority_state(),immutable)
        self.assertEqual(immutable['confirmation_approval_authorities_v1'],before['confirmation_approval_authorities_v1'])


if __name__=='__main__': unittest.main(verbosity=2)
