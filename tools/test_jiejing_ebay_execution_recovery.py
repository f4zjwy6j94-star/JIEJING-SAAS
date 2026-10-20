#!/usr/bin/env python3
"""Exact zero-write retirement preserves the original merchant decision."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import test_jiejing_ebay_execution_authority as fixtures
import test_jiejing_ebay_operation_admission as operation
import jiejing_saas.ebay_execution_authority as authority


class ExecutionRecoveryTests(unittest.TestCase):
    setUp=fixtures.EbayExecutionAuthorityTests.setUp
    scoped_claim=fixtures.EbayExecutionAuthorityTests.scoped_claim
    publish_fixture=fixtures.EbayExecutionAuthorityTests.publish_fixture
    claim=fixtures.EbayExecutionAuthorityTests.claim
    publish=operation.OperationAdmissionTests.publish
    success=staticmethod(operation.OperationAdmissionTests.success)
    attempt=operation.OperationAdmissionTests.attempt

    def noop(self):
        return self.repo.retire_external_execution_after_verified_noop(company_id=self.company,
            confirmation_id=self.record['confirmation_id'],user_id=self.user,action_type='publish_listing',
            evidence={'provider_read_only':True,'external_state_unchanged':True,'automatic_retry_allowed':False,'secret_exposed':False})

    def snapshot(self):
        with self.repo._connect() as conn:
            return {table:[dict(row) for row in conn.execute('select * from '+table+' where confirmation_id=?',
                (self.record['confirmation_id'],)).fetchall()] for table in
                ('confirmations','confirmation_approval_authorities_v1','confirmation_execution_authorities_v1')}

    def test_old_noop_cannot_retire_active_even_when_zero_recovery_is_eligible(self):
        self.publish_fixture();permit=self.claim()['_execution_permit'];row,state=self.attempt(permit)
        stamp=datetime.fromisoformat(row['created_at'])
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return (stamp+timedelta(seconds=61)).astimezone(tz)
        before=self.snapshot()
        with patch.object(authority,'datetime',Clock):
            self.assertTrue(self.repo.ebay_execution_recovery(company_id=self.company,
                confirmation_id=self.record['confirmation_id'])['zero_write_proven'])
            with self.assertRaisesRegex(PermissionError,'zero_write_not_proven'): self.noop()
        self.assertEqual(self.snapshot(),before)

    def test_old_zero_snapshot_cannot_retire_after_actual_unknown_submission(self):
        snapshots=[]
        def after_claim(_):
            with self.repo._connect() as conn:
                row=dict(conn.execute('select * from confirmation_execution_authorities_v1 where confirmation_id=?',
                    (self.record['confirmation_id'],)).fetchone())
            stamp=datetime.fromisoformat(row['created_at'])
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None): return (stamp+timedelta(seconds=61)).astimezone(tz)
            with patch.object(authority,'datetime',Clock): snapshots.append(self.repo.ebay_execution_recovery(
                company_id=self.company,confirmation_id=self.record['confirmation_id']))
        def timeout(*_): raise TimeoutError('Synthetic previously admitted request')
        self.publish(timeout,after_claim=after_claim)
        self.assertTrue(snapshots[0]['zero_write_proven']);self.assertEqual(len(self.calls),1)
        row,state=self.attempt(self.permit);self.assertEqual(state['operations'][0]['status'],'unknown')
        before=self.snapshot()
        with self.assertRaisesRegex(PermissionError,'zero_write_not_proven'): self.noop()
        self.assertEqual(self.snapshot(),before)

    def test_old_noop_only_acknowledges_already_retired_durable_zero(self):
        with self.assertRaises(authority.EbayExecutionDenied):
            self.publish(self.success,token_hook=lambda:self.repo.set_user_access_status(user_id=self.user,status='disabled'))
        self.assertEqual(self.calls,[]);self.assertEqual(self.attempt(self.permit)[0]['phase'],'blocked_before_call')
        before=self.snapshot();result=self.noop()
        self.assertEqual(result['status'],'needs_revision');self.assertEqual(self.snapshot(),before)

    def decision(self,repo,scope,record):
        value=repo.get_confirmation(company_id=scope['company_id'],confirmation_id=record['confirmation_id'])
        with repo._connect() as conn:
            row=conn.execute('select * from confirmation_approval_authorities_v1 where company_id=? and confirmation_id=?',
                             (scope['company_id'],record['confirmation_id'])).fetchone()
        value['approval_authority_id']=dict(row)
        return value

    def test_expired_prewrite_is_retired_not_reapproved(self):
        repo,scope,record,claimed,capability=self.scoped_claim('b1-expired-history')
        before=self.decision(repo,scope,record)
        with repo._connect() as conn:
            conn.execute('update external_execution_claims set expires_at=? where claim_id=?',
                         ((datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),capability._claim_id))
        result=repo.recover_expired_unpublished_draft_execution_claim(company_id=scope['company_id'],
            confirmation_id=record['confirmation_id'],user_id=scope['user_id'])
        after=self.decision(repo,scope,record)
        self.assertEqual(result['status'],'needs_revision')
        for key in ('decided_by','decided_at','decision_note','item','approval_authority_id'):
            self.assertEqual(before[key],after[key])
        self.assertFalse(result['automatic_retry_allowed'])
        with self.assertRaises((PermissionError,ValueError)):
            capability.consume()

    def test_revoked_consume_retirement_preserves_full_decision(self):
        repo,scope,record,claimed,capability=self.scoped_claim('b1-revoked-history')
        before=self.decision(repo,scope,record)
        repo.set_user_access_status(user_id=scope['user_id'],status='disabled')
        with self.assertRaises(PermissionError):
            capability.consume()
        repo.set_user_access_status(user_id=scope['user_id'],status='active')
        with self.assertRaises((PermissionError,ValueError)):
            capability.consume()
        after=self.decision(repo,scope,record)
        self.assertEqual(after['status'],'needs_revision')
        for key in ('decided_by','decided_at','decision_note','item','approval_authority_id'):
            self.assertEqual(before[key],after[key])
        summary=repo.ebay_execution_recovery(company_id=scope['company_id'],confirmation_id=record['confirmation_id'])
        self.assertTrue(summary['zero_write_proven'])


if __name__=='__main__':
    unittest.main(verbosity=2)
