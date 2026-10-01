"""Closed internal-credit reconciliation must never touch purchased/active credits."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jiejing_private_media_credit_reconcile import plan_reconciliation, ReconcileBlocked

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)

def fixture():
    b = {'bucket_id':'private-bucket','source_type':'internal_owner_testing',
         'source_reference_id':'private-test-2026-08','granted_points':1000,
         'remaining_points':160,'reserved_points':160,'expires_at':'2026-09-24T00:00:00Z','status':'expiring'}
    rows = [
        {'ledger_id':'grant','operation_type':'grant','points':1000,'status':'completed',
         'reference_type':'internal_owner_testing','reference_id':'private-test-2026-08',
         'credit_source':'internal_owner_testing','source_reference_id':'private-test-2026-08'},
        {'ledger_id':'reserve','operation_type':'reserve','points':180,'status':'settled',
         'created_at':'2026-09-01T00:00:00Z','allocations':[{'bucket_id':'private-bucket','points':180}]},
        {'ledger_id':'settle','operation_type':'settle','points':180,'status':'completed',
         'reservation_id':'reserve','created_at':'2026-09-01T00:01:00Z'},
        {'ledger_id':'expiry','operation_type':'expire','points':780,'status':'completed',
         'reference_type':'media_credit_bucket','reference_id':'private-bucket'},
    ]
    return {'company_id':'local-company','account':{'balance_points':40,'reserved_points':0,
            'lifetime_granted_points':1000,'lifetime_spent_points':180},
            'buckets':[b], 'ledger':rows, 'active_provider_jobs':0}

class ReconciliationTest(unittest.TestCase):
    def test_closed_expired_private_bucket_uses_ledger_not_stale_projection(self):
        source=fixture(); before=deepcopy(source)
        plan=plan_reconciliation(source, now=NOW)
        self.assertEqual(plan['status'],'repairable')
        self.assertEqual(plan['expiry_points'],40)
        self.assertEqual(plan['buckets'][0]['ledger_remaining_points'],40)
        self.assertEqual(plan['buckets'][0]['after'],{'remaining_points':0,'reserved_points':0,'status':'expired'})
        self.assertEqual(source,before)

    def test_refuses_paid_plan_legacy_unexpired_and_revoked_buckets(self):
        for value in ('purchased','plan_included','legacy'):
            with self.subTest(value=value):
                source=fixture(); source['buckets'][0]['source_type']=value
                with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)
        for key,value in (('expires_at','2099-01-01T00:00:00Z'),('status','revoked')):
            source=fixture(); source['buckets'][0][key]=value
            with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)

    def test_refuses_active_jobs_reservations_and_missing_job_check(self):
        for field,value in (('active_provider_jobs',1),('active_provider_jobs',None)):
            source=fixture(); source[field]=value
            with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)
        source=fixture(); source['ledger'][1]['status']='reserved'
        with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)
        source=fixture(); source['account']['reserved_points']=20
        with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)

    def test_refuses_corrupt_incomplete_or_duplicate_history(self):
        mutations = [
            lambda s: s['ledger'].pop(2),
            lambda s: s['ledger'].append(deepcopy(s['ledger'][2])),
            lambda s: s['ledger'][2].update(reservation_id='missing'),
            lambda s: s['ledger'][2].update(points=181),
            lambda s: s['ledger'][2].update(created_at='2026-09-25T00:00:00Z'),
            lambda s: s['ledger'][2].update(created_at='2026-08-31T00:00:00Z'),
            lambda s: s['ledger'][1].update(allocations=[]),
            lambda s: s['ledger'][1]['allocations'][0].update(bucket_id='other'),
            lambda s: s['ledger'][0].update(source_reference_id='other'),
            lambda s: s['ledger'][0].update(reference_id='other'),
            lambda s: s['ledger'][0].update(points=999),
            lambda s: s['ledger'][3].update(points=900),
            lambda s: s['ledger'][3].update(operation_type='refund'),
            lambda s: s['ledger'][3].update(points=-1),
            lambda s: s['ledger'][3].update(points=True),
            lambda s: s['account'].update(balance_points=41),
            lambda s: s['account'].update(lifetime_spent_points=0),
            lambda s: s['buckets'][0].update(reserved_points=161),
        ]
        for index,mutate in enumerate(mutations):
            with self.subTest(index=index):
                source=fixture(); mutate(source)
                with self.assertRaises(ReconcileBlocked): plan_reconciliation(source,now=NOW)

    def test_release_does_not_count_as_spending(self):
        source=fixture(); source['ledger'][1]['status']='released'
        source['ledger'][2]['operation_type']='release'
        source['account'].update(balance_points=220,lifetime_spent_points=0)
        self.assertEqual(plan_reconciliation(source,now=NOW)['expiry_points'],220)

    def test_fingerprint_ignores_read_touch_but_not_financial_changes(self):
        source=fixture(); first=plan_reconciliation(source,now=NOW)
        source['account']['updated_at']='later'; source['buckets'][0]['updated_at']='later'
        source['ledger'][0]['updated_at']='later'
        self.assertEqual(first['fingerprint'],plan_reconciliation(source,now=NOW)['fingerprint'])
        source['buckets'][0]['reserved_points']=140
        self.assertNotEqual(first['fingerprint'],plan_reconciliation(source,now=NOW)['fingerprint'])

    def test_existing_expiry_not_overwritten_and_repaired_state_is_no_op(self):
        source=fixture(); original=deepcopy(source['ledger'])
        source['ledger'].append({'ledger_id':'repair-expire','operation_type':'expire','points':40,
            'status':'completed','reference_type':'media_credit_bucket','reference_id':'private-bucket'})
        source['account']['balance_points']=0
        source['buckets'][0].update(remaining_points=0,reserved_points=0,status='expired')
        plan=plan_reconciliation(source,now=NOW)
        self.assertEqual(plan['status'],'no_op'); self.assertEqual(plan['expiry_points'],0)
        self.assertEqual(source['ledger'][:4],original)

if __name__=='__main__': unittest.main()
