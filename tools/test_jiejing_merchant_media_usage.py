"""Merchant media usage projection from isolated real accounting operations."""
from pathlib import Path
from datetime import datetime, timezone
import gc
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.media_credits import build_merchant_media_credit_summary
from jiejing_saas.repository import SaaSRepository


class MerchantMediaUsageTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix='jiejing-media-usage-')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.repo = SaaSRepository(Path(self.tmp.name) / 'test.sqlite')
        account = self.repo.create_user_with_company(email='media-usage@example.test', password='test-only-password', company_name='Usage fixture')
        self.company = account['company']['company_id']
        self.user = account['user']['user_id']

    def operation(self, operation, points, key, **kw):
        return self.repo.apply_media_credit_operation(company_id=self.company, user_id=self.user,
            operation_type=operation, points=points, idempotency_key=key,
            reference_type='media_job', reference_id=kw.pop('reference_id', 'fixture-job'), **kw)

    def grant(self, points=1000, source='purchased', **kw):
        return self.operation('grant', points, f'grant-{source}-fixture', details={'credit_source':source, **kw})

    def usage(self, **kw):
        return build_merchant_media_credit_summary(self.repo, company_id=self.company, include_usage=True, **kw)['usage']

    def test_pending_usage_is_reserved_not_spent(self):
        self.grant()
        self.operation('reserve', 80, 'reserve-first-fixture')
        usage = self.usage()
        self.assertEqual(usage['held_points'], 80)
        row = usage['items'][0]
        self.assertEqual((row['state'], row['estimated_points'], row['spent_points'], row['released_points']), ('reserved', 80, None, 0))
        self.assertEqual(build_merchant_media_credit_summary(self.repo, company_id=self.company)['available_points'], 920)

    def test_partial_success_settles_once_and_releases_unused_quote(self):
        self.grant()
        reservation = self.operation('reserve', 240, 'reserve-partial-fixture')['ledger_entry']['ledger_id']
        for _ in range(2):
            self.operation('settle', 80, 'settle-partial-fixture', reservation_id=reservation)
        usage = self.usage()
        self.assertEqual(len(usage['items']), 1)
        row = usage['items'][0]
        self.assertEqual((row['state'], row['spent_points'], row['released_points']), ('settled', 80, 160))
        self.assertEqual(usage['held_points'], 0)
        self.assertEqual(build_merchant_media_credit_summary(self.repo, company_id=self.company)['available_points'], 920)

    def test_failure_releases_full_hold_without_spend(self):
        self.grant()
        reservation = self.operation('reserve', 80, 'reserve-failed-fixture')['ledger_entry']['ledger_id']
        self.operation('release', 80, 'release-failed-fixture', reservation_id=reservation, details={'reason':'provider_failure', 'raw_provider_response':'private-canary'})
        usage = self.usage()
        self.assertEqual((usage['items'][0]['state'], usage['items'][0]['spent_points'], usage['items'][0]['released_points']), ('released', 0, 80))
        self.assertEqual(usage['held_points'], 0)
        self.assertEqual(build_merchant_media_credit_summary(self.repo, company_id=self.company)['available_points'], 1000)
        self.assertNotIn('private-canary', json.dumps(usage))

    def test_expired_release_is_not_claimed_as_available_balance(self):
        self.grant(80, 'plan_included', expires_at='2099-01-01T00:00:00+00:00')
        reservation = self.operation('reserve', 80, 'reserve-expired-fixture')['ledger_entry']['ledger_id']
        # Time is an external boundary; simulate a term ending with a hold in flight.
        future = datetime(2100, 1, 1, tzinfo=timezone.utc)
        with patch('jiejing_saas.repository.datetime') as clock:
            clock.now.return_value = future
            clock.fromisoformat.side_effect = datetime.fromisoformat
            self.assertEqual(self.usage()['held_points'], 80)
            self.operation('release', 80, 'release-expired-fixture', reservation_id=reservation)
        summary = build_merchant_media_credit_summary(self.repo, company_id=self.company, include_usage=True)
        self.assertEqual(summary['available_points'], 0)
        self.assertEqual(summary['usage']['items'][0]['released_points'], 80)
        self.assertNotIn('returned_to_balance', summary['usage']['items'][0])

    def test_internal_testing_records_never_enter_merchant_usage(self):
        self.grant(320, 'internal_owner_testing', expires_at='2099-01-01T00:00:00+00:00')
        self.repo.reserve_media_credit_source(company_id=self.company, user_id=self.user,
            source_type='internal_owner_testing', source_reference_id='fixture-job', points=80,
            idempotency_key='internal-private-reserve', reference_type='media_job', reference_id='private-owner-reference')
        summary = build_merchant_media_credit_summary(self.repo, company_id=self.company, include_usage=True)
        self.assertEqual(summary['available_points'], 0)
        self.assertEqual(summary['usage']['held_points'], 0)
        self.assertEqual(summary['usage']['items'], [])
        for forbidden in ('private-owner-reference', 'ledger_id', 'bucket_id', 'source_type', 'internal_owner_testing', 'recent_activity'):
            self.assertNotIn(forbidden, json.dumps(summary))

    def test_company_isolation_and_empty_account(self):
        self.grant()
        self.operation('reserve', 80, 'reserve-isolation-fixture')
        other = self.repo.create_user_with_company(email='media-other@example.test', password='other-test-only', company_name='Other')['company']['company_id']
        usage = build_merchant_media_credit_summary(self.repo, company_id=other, include_usage=True)['usage']
        self.assertEqual(usage['held_points'], 0)
        self.assertEqual(usage['items'], [])
        self.assertFalse(usage['incomplete'])

    def test_refund_holds_are_not_generation_spend(self):
        self.grant()
        self.repo.reserve_media_credit_source(company_id=self.company, user_id=self.user,
            source_type='purchased', source_reference_id='fixture-job', points=100,
            idempotency_key='refund-hold-fixture', reference_type='billing_refund', reference_id='refund-fixture')
        usage = self.usage()
        self.assertEqual(usage['held_points'], 100)
        self.assertEqual(usage['items'], [])

    def test_unknown_historical_allocation_is_not_fabricated(self):
        self.grant()
        reservation = self.operation('reserve', 80, 'reserve-unknown-fixture')['ledger_entry']['ledger_id']
        # Simulate pre-migration/malformed persisted evidence at the DB boundary.
        with self.repo._connect() as conn:
            conn.execute('update media_credit_ledger set ledger_json = ? where ledger_id = ?', ('{}', reservation))
        usage = self.usage()
        self.assertTrue(usage['incomplete'])
        self.assertEqual(usage['items'], [])
        self.assertEqual(usage['held_points'], 80)

    def test_missing_terminal_evidence_requires_review(self):
        self.grant()
        reservation = self.operation('reserve', 80, 'reserve-missing-fixture')['ledger_entry']['ledger_id']
        with self.repo._connect() as conn:
            conn.execute('update media_credit_ledger set status = ? where ledger_id = ?', ('released', reservation))
        row = self.usage()['items'][0]
        self.assertEqual(row['state'], 'needs_review')
        self.assertIsNone(row['spent_points'])
        self.assertEqual(row['released_points'], 0)

    def test_foreign_bucket_reference_cannot_bypass_company_isolation(self):
        self.grant()
        reservation = self.operation('reserve', 80, 'reserve-foreign-bucket-fixture')['ledger_entry']['ledger_id']
        other = self.repo.create_user_with_company(email='foreign-bucket@example.test', password='foreign-test-only', company_name='Other')['company']['company_id']
        self.repo.apply_media_credit_operation(company_id=other, user_id=None, operation_type='grant',
            points=80, idempotency_key='foreign-bucket-grant', reference_type='billing_order',
            reference_id='foreign-order', details={'credit_source':'purchased'})
        with self.repo._connect() as conn:
            foreign = conn.execute('select bucket_id from media_credit_buckets where company_id = ?', (other,)).fetchone()['bucket_id']
            evidence = {'details': {'allocations': [{'bucket_id': foreign, 'points': 80}]}}
            conn.execute('update media_credit_ledger set ledger_json = ? where ledger_id = ?', (json.dumps(evidence), reservation))
        usage = self.usage()
        self.assertEqual(usage['items'], [])
        self.assertTrue(usage['incomplete'])
        self.assertEqual(usage['held_points'], 80)
        self.assertNotIn(foreign, json.dumps(usage))

    def test_mixed_internal_and_merchant_allocation_does_not_inflate_usage(self):
        self.grant()
        self.grant(320, 'internal_owner_testing', expires_at='2099-01-01T00:00:00+00:00')
        reservation = self.operation('reserve', 80, 'reserve-mixed-fixture')['ledger_entry']['ledger_id']
        with self.repo._connect() as conn:
            buckets = conn.execute('select bucket_id from media_credit_buckets where company_id = ?', (self.company,)).fetchall()
            self.assertEqual(len(buckets), 2)
            evidence = {'details': {'allocations': [{'bucket_id': bucket['bucket_id'], 'points': 40} for bucket in buckets]}}
            conn.execute('update media_credit_ledger set ledger_json = ? where ledger_id = ?', (json.dumps(evidence), reservation))
        usage = self.usage()
        self.assertEqual(usage['items'], [])
        self.assertTrue(usage['incomplete'])
        self.assertEqual(usage['held_points'], 80)
        self.assertNotIn('internal_owner_testing', json.dumps(usage))

    def test_result_limit_is_explicit_not_an_all_time_total(self):
        self.grant()
        for index in range(3):
            self.operation('reserve', 80, f'reserve-limit-fixture-{index}')
        usage = self.usage(limit=2)
        self.assertEqual(len(usage['items']), 2)
        self.assertTrue(usage['has_more'])
        self.assertEqual(usage['held_points'], 240)
        self.assertNotIn('lifetime_spent_points', usage)

    def test_generation_record_correlates_only_to_own_media_job(self):
        self.grant()
        self.operation('reserve', 80, 'reserve-associated-fixture')
        job = self.repo.create_media_asset_job(company_id=self.company, store_id='test-store', task_id='test-task',
            user_id=self.user, provider_job_key='test-only', idempotency_key='fixture-job', job_spec={})
        row = self.usage()['items'][0]
        self.assertEqual(row['media_job_id'], job['media_job_id'])

    def test_foreign_job_with_same_reference_is_never_correlated(self):
        self.grant()
        self.operation('reserve', 80, 'reserve-foreign-job-fixture')
        other = self.repo.create_user_with_company(email='foreign-job@example.test', password='foreign-test-only', company_name='Other')['company']['company_id']
        self.repo.create_media_asset_job(company_id=other, store_id='test-store', task_id='test-task',
            user_id=self.user, provider_job_key='test-only', idempotency_key='fixture-job', job_spec={})
        self.assertEqual(self.usage()['items'][0]['media_job_id'], '')

    def test_scan_boundary_is_explicit_and_reading_does_not_change_ledger(self):
        self.grant(1000)
        for index in range(101):
            self.operation('reserve', 1, f'reserve-window-fixture-{index}')
        before = self.repo.list_media_credit_ledger(company_id=self.company, limit=100)
        usage = self.usage(limit=100)
        self.assertEqual(len(usage['items']), 100)
        self.assertTrue(usage['has_more'])
        self.assertEqual(usage['held_points'], 101)
        self.assertEqual(self.repo.list_media_credit_ledger(company_id=self.company, limit=100), before)


if __name__ == '__main__':
    unittest.main()
