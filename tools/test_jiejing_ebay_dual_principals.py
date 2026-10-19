#!/usr/bin/env python3
"""Real account/membership ABA transitions through real final transport gate."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
from jiejing_runtime.execution import ExecutionService
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter,build_ebay_execution_plan
from jiejing_saas.ebay_execution_authority import EbayExecutionDenied


class DualPrincipalTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture

    def actors(self):
        request,connection,settings=self.publish_fixture()
        people={}
        for label,role in (('approver','admin'),('executor','operator')):
            email=f'{label}@example.test'
            account=self.repo.create_user_with_company(email=email,password='synthetic-only',company_name=f'Synthetic {label}')
            user=account['user']['user_id']
            self.repo.create_team_invitation(company_id=self.company,invited_by=self.user,email=email,role=role)
            people[label]=(user,email,role)
        approver=people['approver'][0]; executor=people['executor'][0]
        record=self.repo.create_confirmation(company_id=self.company,store_id=self.store,task_id=None,runtime_run_id='b1-dual',
            item={'publish_payload':request.payload},action_type='publish_listing',title='Dual principal B1')
        approved=self.repo.decide_confirmation(company_id=self.company,confirmation_id=record['confirmation_id'],decision='approve',
            decided_by=approver,note='Immutable different approver.',expected_access_epochs=self.repo.access_session_epochs(user_id=approver,company_id=self.company))
        request=replace(request,confirmation_id=approved['confirmation_id'],confirmed_by=approver,confirmed_at=approved['decided_at'],user_id=executor)
        self.people,self.request,self.record,self.settings,self.connection=people,request,approved,settings,connection
        self.executor_epochs=self.repo.access_session_epochs(user_id=executor,company_id=self.company)

    def claim(self, epochs=True):
        return self.repo.claim_external_execution(company_id=self.company,confirmation_id=self.record['confirmation_id'],
            user_id=self.people['executor'][0],expected_access_epochs=self.executor_epochs if epochs else None,
            operation_plan=build_ebay_execution_plan(request=self.request,marketplace_id='EBAY_US',connections=[self.connection]))

    def transition(self,actor,kind):
        user,email,role=self.people[actor]
        if kind=='disabled':
            self.repo.set_user_access_status(user_id=user,status='disabled')
            self.repo.set_user_access_status(user_id=user,status='active')
        elif kind=='removed':
            self.repo.set_team_member_access(company_id=self.company,user_id=user,role=None,actor_user_id=self.user)
            self.repo.create_team_invitation(company_id=self.company,invited_by=self.user,email=email,role=role)
        else:
            self.repo.set_team_member_access(company_id=self.company,user_id=user,role='viewer',actor_user_id=self.user)
            self.repo.set_team_member_access(company_id=self.company,user_id=user,role=role,actor_user_id=self.user)

    def execute(self,hook=None):
        permit=self.claim()['_execution_permit']; calls=[]; self.calls=calls
        def transport(request,timeout):
            calls.append(request.get_method())
            return 200,{},json.dumps({'offerId':'offer-dual','listingId':'listing-dual'}).encode()
        def token(**_):
            if hook: hook()
            return {'ok':True,'access_token':'B1-SYNTHETIC-TOKEN','source':'injected'}
        adapter=EbayWriteHttpAdapter(self.settings,transport=transport)
        with patch.object(adapter,'_resolve_access_token',side_effect=token):
            return adapter.publish_listing(request=self.request,preflight=ExecutionService(demo_mode=False).preflight(self.request),
                connections=[self.connection],secret_refs=[],marketplace_id='EBAY_US',execution_permit=permit)

    def aba(self,actor,kind):
        self.actors()
        with self.assertRaises(EbayExecutionDenied) as denied: self.execute(lambda:self.transition(actor,kind))
        self.assertEqual(self.calls,[])
        self.assertTrue(denied.exception.recovery['zero_write_proven'])
        self.assertIn('approval_' if actor=='approver' else 'execution_request_',str(denied.exception))

    def test_approver_disabled_active_aba(self): self.aba('approver','disabled')
    def test_approver_removed_readded_aba(self): self.aba('approver','removed')
    def test_approver_role_restored_aba(self): self.aba('approver','role')
    def test_executor_disabled_active_aba(self): self.aba('executor','disabled')
    def test_executor_removed_readded_aba(self): self.aba('executor','removed')
    def test_executor_role_restored_aba(self): self.aba('executor','role')

    def test_distinct_principals_normal_control(self):
        self.actors(); self.assertEqual(self.execute()['status'],'published_to_ebay')
        self.assertEqual(self.calls,['PUT','POST','POST'])

    def test_original_executor_epochs_cannot_be_omitted(self):
        self.actors()
        with self.assertRaisesRegex(PermissionError,'execution_request_authority_required'): self.claim(epochs=False)

    def test_executor_removed_between_entry_and_claim(self):
        self.actors()
        self.repo.set_team_member_access(company_id=self.company,user_id=self.people['executor'][0],role=None,actor_user_id=self.user)
        with self.assertRaisesRegex(PermissionError,'execution_request_authority_changed'): self.claim()

    def test_other_company_role_change_does_not_revoke_current_request(self):
        self.actors()
        other=self.repo.create_user_with_company(email='other-owner@example.test',password='synthetic-only',company_name='Other tenant')
        company=other['company']['company_id']; owner=other['user']['user_id']
        target,email,role=self.people['executor']
        self.repo.create_team_invitation(company_id=company,invited_by=owner,email=email,role=role)
        def mutate(): self.repo.set_team_member_access(company_id=company,user_id=target,role='viewer',actor_user_id=owner)
        self.assertEqual(self.execute(mutate)['status'],'published_to_ebay')
        self.assertEqual(self.calls,['PUT','POST','POST'])


if __name__=='__main__': unittest.main(verbosity=2)
