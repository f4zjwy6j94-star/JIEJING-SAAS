#!/usr/bin/env python3
"""Real loopback approval-rejection responses; synthetic DB and no-network adapter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from test_jiejing_new_ebay_account_publish_http_chain import (
    FakeWriteAdapter, SaaSBackendHandler, SaaSRepository, SaaSSettings,
    SessionManager, _post, _publish_payload, _seed_legacy_connection, api_server,
)


class ApprovalAuthorityHTTPTests(unittest.TestCase):
    def setUp(self):
        # Retained local synthetic evidence only; never an existing merchant DB.
        self.directory = Path(tempfile.mkdtemp(prefix='b0-authority-http-'))
        self.repo = SaaSRepository(self.directory / 'case.sqlite', database_engine='sqlite', database_url='')
        account = self.repo.create_user_with_company(email='authority-http@example.test',
            password='synthetic-only', company_name='Synthetic authority HTTP')
        self.user = account['user']
        self.company = self.user['default_company_id']
        self.store = self.repo.create_store(company_id=self.company, user_id=self.user['user_id'],
            payload={'platform': 'ebay', 'store_name': 'synthetic-only', 'marketplace': 'EBAY_US'})
        self.connection=_seed_legacy_connection(self.repo,company_id=self.company,
            store_id=self.store['store_id'],user_id=self.user['user_id'])
        project = {'key': 'listing-project-authority-http',
                   'source_report_id': 'market-report-authority-http', 'candidate_id': 'candidate-authority-http'}
        task = self.repo.create_task(company_id=self.company, store_id=self.store['store_id'],
            user_id=self.user['user_id'], task_type='merchant_product_facts',
            title='Synthetic authoritative evidence', input_data={'listing_project_identity': project})
        report = self.repo.save_merchant_product_fact_report(task=task, listing_project_identity=project, packet={
            'source': 'authenticated_merchant_request', 'source_mode': 'merchant_owned_product',
            'simulation_only': False, 'product_name': 'New account smoke widget',
            'merchant_confirmed_facts': {'merchant_owned_product_confirmed': True, 'image_rights_confirmed': True},
            'source_records': [{'type': 'merchant_product_image', 'url': 'https://example.com/smoke.jpg',
                                'rights_status': 'merchant_confirmed'}],
            'unknown_facts': [], 'secret_exposed': False})
        settings = SaaSSettings.from_env(db_path=self.directory / 'case.sqlite',
            runtime_db_path=self.directory / 'runtime.sqlite', output_root=self.directory / 'output',
            host='127.0.0.1', port=0)
        settings.environment = 'staging'
        settings.requested_real_platform_writes = True
        settings.ebay_write_live_enabled = True
        settings.ebay_draft_save_live_enabled = True
        settings.ebay_token_refresh_live_enabled = True
        settings.ebay_read_only_live_enabled = True
        sessions = SessionManager(secret='synthetic-authority-http-session')

        class TestHandler(SaaSBackendHandler):
            pass

        TestHandler.repository = self.repo
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.ebay_write_adapter_factory = FakeWriteAdapter
        self.server_errors = []
        error_records = self.server_errors

        class EvidenceServer(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                exc = sys.exception()
                error_records.append({'type': type(exc).__name__, 'message': str(exc)})
                super().handle_error(request, client_address)

        self.server = EvidenceServer(('127.0.0.1', 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._close_server)
        self.base_url = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.token = sessions.create_token(user_id=self.user['user_id'], company_id=self.company,
            email=self.user['email'], access_epochs=self.repo.access_session_epochs(
                user_id=self.user['user_id'], company_id=self.company))
        health = lambda *_args, **kwargs: {
            'contract_version': 'unit-current-store-health-v1', 'company_id': kwargs['company_id'],
            'store_id': kwargs['store_id'], 'status': 'normal', 'incident_mode': False,
            'can_execute_real_writes': True, 'account_health': {'status': 'normal'}, 'secret_exposed': False}
        health_patch = patch.object(api_server, 'build_account_health_snapshot', health)
        health_patch.start()
        self.addCleanup(health_patch.stop)
        body = _publish_payload(listing_project_identity=project, product_fact_report_id=report['report_id'])
        confirmation = _post(self.base_url, '/stores/' + self.store['store_id'] + '/publish-confirmation',
                             body, self.token)['confirmation']
        self.confirmation_id = confirmation['confirmation_id']
        self.confirmation = _post(self.base_url, '/confirmations/' + self.confirmation_id + '/decision',
            {'decision': 'approve', 'note': 'Synthetic HTTP regression approval.'}, self.token)['confirmation']
        self.assertEqual(self.confirmation['status'], 'approved')
        self.assertTrue(settings.effective_real_platform_writes_enabled)
        self.claim_trace = []
        self.claim_fault = None
        original_claim = self.repo.claim_external_execution

        def observe_claim(**kwargs):
            event = {'original_called': self.claim_fault is None}
            self.claim_trace.append(event)
            if self.claim_fault is not None:
                raise self.claim_fault
            try:
                return original_claim(**kwargs)
            except Exception as exc:
                event.update(exception_type=type(exc).__name__, exception_text=str(exc))
                raise

        self.repo.claim_external_execution = observe_claim
        self.addCleanup(setattr, self.repo, 'claim_external_execution', original_claim)
        FakeWriteAdapter.reset_control()

    def _close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), 'Owned HTTP server did not close')

    def _state(self):
        # Rejection must leave actual immutable decisions and execution state intact.
        with self.repo._connect() as conn:
            snapshot = {table: [dict(row) for row in conn.execute(
                f'select * from {table} where confirmation_id=? order by 1',
                (self.confirmation_id,)).fetchall()] for table in (
                    'confirmations', 'confirmation_approval_authorities_v1',
                    'confirmation_execution_authorities_v1', 'external_execution_claims', 'execution_results')}
            snapshot['tasks'] = [dict(row) for row in conn.execute(
                'select * from tasks where company_id=? order by task_id', (self.company,)).fetchall()]
            snapshot['decision_audit'] = [dict(row) for row in conn.execute(
                'select * from audit_logs where company_id=? and target_id=? order by audit_id',
                (self.company, self.confirmation_id)).fetchall()]
        return snapshot

    def _assert_valid_preflight(self):
        result = _post(self.base_url, '/confirmations/' + self.confirmation_id + '/preflight',
                       {'idempotency_key': 'synthetic-authority-preflight'}, self.token)
        self.assertEqual(result['preflight']['status'], 'ready_for_platform_adapter')
        self.assertEqual(result['publish_readiness']['status'], 'ready_for_execution')

    def _execute(self):
        request = urllib.request.Request(self.base_url + '/confirmations/' + self.confirmation_id + '/execute',
            data=json.dumps({'idempotency_key': 'synthetic-authority-execute'}).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read()), None
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), None
        except http.client.RemoteDisconnected as exc:
            return None, None, type(exc).__name__

    def _assert_zero_adapter_calls(self):
        self.assertEqual((FakeWriteAdapter.publish_call_count, FakeWriteAdapter.cleanup_call_count,
                          FakeWriteAdapter.draft_call_count, FakeWriteAdapter.draft_execute_attempt_count), (0, 0, 0, 0))

    def _assert_reapproval_denial(self, code):
        self._assert_valid_preflight()
        before = self._state()
        status, body, connection_error = self._execute()
        self._assert_zero_adapter_calls()
        after = self._state()
        # B1's bounded pre-claim denial is new evidence, never a new decision.
        # Every original row and every immutable/execution table stays exact.
        self.assertEqual({key:value for key,value in after.items() if key != 'decision_audit'},
                         {key:value for key,value in before.items() if key != 'decision_audit'},
                         'Rejected execution silently changed decision or execution history')
        self.assertTrue(all(row in after['decision_audit'] for row in before['decision_audit']))
        added = [row for row in after['decision_audit'] if row not in before['decision_audit']]
        self.assertEqual(len(added), 1)
        audit = added[0]
        self.assertEqual((audit['company_id'], audit['store_id'], audit['target_id'], audit['target_type'], audit['action_type']),
                         (self.company, self.store['store_id'], self.confirmation_id, 'confirmation', 'external_execution.preclaim_denied'))
        details = json.loads(audit['audit_json'])['details']
        current = self.repo.get_confirmation(company_id=self.company, confirmation_id=self.confirmation_id)
        snapshot = {key:current.get(key) for key in
            ('company_id','store_id','confirmation_id','action_type','task_id','decided_by','decided_at','decision_note')}
        decided_at = datetime.fromisoformat(snapshot['decided_at'])
        self.assertIsNotNone(decided_at.tzinfo)
        self.assertIsNotNone(decided_at.utcoffset())
        snapshot['decided_at'] = decided_at.astimezone(timezone.utc).isoformat()
        digest = lambda value: hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',', ':'),allow_nan=False).encode()).hexdigest()
        self.assertEqual(details, {'action_type':current['action_type'], 'item_sha256':digest(current['item']),
            'approval_snapshot_sha256':digest(snapshot),
            'reason_code':code, 'secret_exposed':False})
        self.assertEqual(self.claim_trace, [{'original_called': True, 'exception_type': 'PermissionError', 'exception_text': code}])
        self.assertEqual(status, 409, f'Expected structured reapproval rejection, got {connection_error}')
        self.assertEqual((body['error'],body['status']), (code,409))
        self.assertFalse(body['execution_recovery']['automatic_retry_allowed'])
        self.assertFalse(body['execution_recovery']['secret_exposed'])
        self.assertIsNone(connection_error)
        self.assertEqual(self.server_errors, [])

    def test_missing_approval_returns_json_without_write_or_history_change(self):
        with self.repo._connect() as conn:
            self.assertTrue(conn.execute('select approval_authority_id from confirmations where confirmation_id=?',
                                         (self.confirmation_id,)).fetchone()[0])
            conn.execute('update confirmations set approval_authority_id=NULL where confirmation_id=?', (self.confirmation_id,))
        self._assert_reapproval_denial('approval_authority_missing_reapproval_required')

    def test_changed_approval_binding_returns_json_without_write_or_history_change(self):
        original_approval = self._state()['confirmation_approval_authorities_v1']
        changed_stamp = (datetime.fromisoformat(self.confirmation['decided_at']) - timedelta(seconds=1)).isoformat()
        with self.repo._connect() as conn:
            # Corrupt only the mutable confirmation projection in this fixture.
            # Do not disable guards, forge an authority or alter approval history.
            conn.execute('update confirmations set decided_at=? where confirmation_id=?', (changed_stamp, self.confirmation_id))
        self._assert_reapproval_denial('approval_authority_binding_changed_reapproval_required')
        self.assertEqual(self._state()['confirmation_approval_authorities_v1'], original_approval)

    def test_valid_approval_reaches_original_claim_and_fake_publish_once(self):
        self._assert_valid_preflight()
        original_approval = self._state()['confirmation_approval_authorities_v1']
        status, body, connection_error = self._execute()
        self.assertEqual(status, 201, body)
        self.assertIsNone(connection_error)
        self.assertEqual(self.claim_trace, [{'original_called': True}])
        self.assertEqual(FakeWriteAdapter.publish_call_count, 1)
        self.assertEqual((FakeWriteAdapter.cleanup_call_count, FakeWriteAdapter.draft_call_count,
                          FakeWriteAdapter.draft_execute_attempt_count), (0, 0, 0))
        self.assertEqual(self.repo.get_confirmation(company_id=self.company,
                         confirmation_id=self.confirmation_id)['status'], 'executed')
        self.assertEqual(self._state()['confirmation_approval_authorities_v1'], original_approval)
        self.assertEqual(self.server_errors, [])

    def test_similar_permission_error_is_not_misreported_as_reapproval(self):
        self._assert_valid_preflight()
        before = self._state()
        sentinel = 'approval_authority_missing_reapproval_required: unrelated sentinel'
        self.claim_fault = PermissionError(sentinel)
        self.assertEqual(self._execute(), (None, None, 'RemoteDisconnected'))
        self._assert_zero_adapter_calls()
        self.assertEqual(self._state(), before)
        self.assertEqual(self.server_errors, [{'type': 'PermissionError', 'message': sentinel}])

    def test_database_failure_retains_existing_service_unavailable_response(self):
        self._assert_valid_preflight()
        before = self._state()
        self.claim_fault = sqlite3.OperationalError('database is locked')
        status, body, connection_error = self._execute()
        self.assertEqual(status, 503)
        self.assertEqual(body['error'], 'database_unavailable')
        self.assertIsNone(connection_error)
        self._assert_zero_adapter_calls()
        self.assertEqual(self._state(), before)
        self.assertEqual(self.server_errors, [])

    def test_programming_error_is_not_misreported_as_reapproval(self):
        self._assert_valid_preflight()
        before = self._state()
        self.claim_fault = RuntimeError('synthetic unexpected claim fault')
        self.assertEqual(self._execute(), (None, None, 'RemoteDisconnected'))
        self._assert_zero_adapter_calls()
        self.assertEqual(self._state(), before)
        self.assertEqual(self.server_errors, [{'type': 'RuntimeError', 'message': 'synthetic unexpected claim fault'}])


if __name__ == '__main__':
    unittest.main()
