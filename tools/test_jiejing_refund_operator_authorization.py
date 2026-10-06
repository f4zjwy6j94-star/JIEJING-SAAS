"""Local HTTP regression: SaaS refunds require an independent platform review."""

from __future__ import annotations

import gc
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.config import SaaSSettings
from jiejing_saas.repository import ConfirmationDecisionConflict, SaaSRepository
from jiejing_saas.security import SessionManager


class RefundOperatorAuthorizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-refund-authorization-")
        root = Path(self.temp.name)
        self.repo = SaaSRepository(root / "saas.sqlite")
        settings = replace(SaaSSettings.from_env(db_path=root / "saas.sqlite", runtime_db_path=root / "runtime.sqlite", output_root=root, host="127.0.0.1", port=0), environment="test", internal_admin_emails=("platform-reviewer@example.test",))
        sessions = SessionManager(secret="local-refund-authorization-fixture-only")
        self.accounts = {}
        self.tokens = {}
        for key, email in (("merchant", "merchant@example.test"), ("reviewer", "platform-reviewer@example.test"), ("other", "other@example.test")):
            account = self.repo.create_user_with_company(email=email, password="Local-fixture-password-2026", company_name=key)
            self.accounts[key] = account
            self.tokens[key] = sessions.create_token(user_id=account["user"]["user_id"], company_id=account["company"]["company_id"], email=email)
        self.company_id = self.accounts["merchant"]["company"]["company_id"]
        self.user_id = self.accounts["merchant"]["user"]["user_id"]
        self.order_id = "refund-auth-order"
        self.repo.create_domestic_billing_order_record(order_id=self.order_id, company_id=self.company_id, user_id=self.user_id, provider="wechat_pay_native", plan_key="starter", amount_minor=9900, currency="CNY", duration_days=30, status="pending_payment", idempotency_key_hash="a" * 64, order={})
        self.repo.mark_domestic_billing_order_paid(company_id=self.company_id, order_id=self.order_id, provider_order_id="local-paid-fixture", paid_at="2026-09-05T00:00:00+00:00", payment={"signature_verified": True, "amount_verified": True})
        class Handler(SaaSBackendHandler):
            def log_message(self, *_: object) -> None:
                pass
        Handler.repository = self.repo
        Handler.settings = settings
        Handler.sessions = sessions
        self.handler = Handler
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        gc.collect()
        self.temp.cleanup()

    def request(self, path: str, body: dict | None = None, *, account: str = "merchant", ops: bool = False) -> tuple[int, dict]:
        headers = {"authorization": f"Bearer {self.tokens[account]}", "content-type": "application/json"}
        if ops:
            headers["Host"] = "ops.jiejing.shop"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def request_review(self) -> str:
        status, response = self.request(f"/billing/domestic/orders/{self.order_id}/refund-request", {"reason": "Paid entitlement was not delivered; please review."})
        self.assertEqual(status, 202, response)
        return response["domestic_billing_refund_request"]["confirmation_id"]

    def test_merchant_cannot_approve_own_saas_refund(self) -> None:
        confirmation_id = self.request_review()
        status, response = self.request(f"/confirmations/{confirmation_id}/decision", {"decision": "approve"})
        self.assertEqual(status, 403, response)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=confirmation_id)["status"], "pending")

    def test_internal_review_and_exact_execution_are_available_in_ops(self) -> None:
        confirmation_id = self.request_review()
        review_path = f"/owner/billing/domestic/refunds/{self.order_id}/review"
        body = {"company_id": self.company_id, "decision": "approve", "review_reason": "Verified service activation failure against payment and usage records."}
        status, response = self.request(review_path, body, account="reviewer", ops=True)
        self.assertEqual(status, 201, response)
        self.assertEqual(response["refund_review"]["status"], "approved")
        status, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        self.assertEqual(status, 200, response)
        order = next(item for item in response["refund_reviews"] if item["order_id"] == self.order_id)
        self.assertEqual(order["company_id"], self.company_id)
        self.assertEqual(order["confirmation_id"], confirmation_id)
        calls = []
        def provider(**kwargs):
            from jiejing_saas.billing_wechat_pay import build_wechat_pay_refund_id
            calls.append(kwargs["order"]["order_id"])
            return {"ok": True, "query_authenticated": True, "provider_response": {"out_trade_no": self.order_id, "out_refund_no": build_wechat_pay_refund_id(self.order_id), "refund_id": "local-refund-fixture", "status": "PROCESSING", "amount": {"refund": 9900, "total": 9900, "currency": "CNY"}}}
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", side_effect=provider):
            status, response = self.request(f"/owner/billing/domestic/refunds/{self.order_id}/execute", {"company_id": self.company_id, "exact_confirmation": order["execution_confirmation"]}, account="reviewer", ops=True)
        self.assertEqual(status, 202, response)
        self.assertEqual(response["domestic_billing_refund_execution"]["status"], "refund_processing")
        self.assertEqual(calls, [self.order_id])
        persisted = self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)
        self.assertEqual(persisted["order"]["state"]["provider_refund_status"], "PROCESSING")

    def test_viewer_cannot_change_decisions_or_queue(self) -> None:
        account = self.accounts["other"]
        company_id, user_id = account["company"]["company_id"], account["user"]["user_id"]
        with self.repo._connect() as conn:
            conn.execute("update team_members set role = 'viewer' where company_id = ? and user_id = ?", (company_id, user_id))
        confirmation = self.repo.create_confirmation(company_id=company_id, store_id=None, task_id=None, runtime_run_id="business-refund-fixture", action_type="refund", title="Buyer refund review", item={"amount": 12}, created_by=user_id)
        for decision in ("reject", "modify", "approve"):
            status, response = self.request(f"/confirmations/{confirmation['confirmation_id']}/decision", {"decision": decision}, account="other")
            self.assertEqual(status, 403, (decision, response))
        for path in ("/queue-jobs/not-yet-created/cancel", "/queue-jobs/not-yet-created/retry", "/queue-jobs/recover-stale", "/workers/run-next"):
            status, response = self.request(path, {}, account="other")
            self.assertEqual(status, 403, (path, response))
        self.assertEqual(self.repo.get_confirmation(company_id=company_id, confirmation_id=confirmation["confirmation_id"])["status"], "pending")

    def test_merchant_business_decision_is_unchanged(self) -> None:
        for decision in ("approve", "reject", "modify"):
            confirmation = self.repo.create_confirmation(company_id=self.company_id, store_id=None, task_id=None, runtime_run_id="business-refund-fixture", action_type="refund", title="Buyer refund review", item={"amount": 12}, created_by=self.user_id)
            status, response = self.request(f"/confirmations/{confirmation['confirmation_id']}/decision", {"decision": decision})
            self.assertEqual(status, 201, response)

    def test_ops_identity_order_scope_reason_and_exact_money_are_required(self) -> None:
        confirmation_id = self.request_review()
        path = f"/owner/billing/domestic/refunds/{self.order_id}"
        review = {"company_id": self.company_id, "decision": "approve", "review_reason": "Verified failed service activation and payment records."}
        for account, ops, body, expected in (
            ("merchant", True, review, 403),
            ("reviewer", False, review, 403),
            ("reviewer", True, {**review, "company_id": self.accounts["other"]["company"]["company_id"]}, 404),
            ("reviewer", True, {**review, "review_reason": ""}, 400),
        ):
            status, response = self.request(path + "/review", body, account=account, ops=ops)
            self.assertEqual(status, expected, response)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=confirmation_id)["status"], "pending")
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", side_effect=AssertionError("must not reach payment provider")):
            status, response = self.request(f"/billing/domestic/orders/{self.order_id}/refund-execute", {})
            self.assertEqual(status, 403, response)
            status, response = self.request(path + "/execute", {"company_id": self.company_id, "exact_confirmation": "wrong-money"}, account="reviewer", ops=True)
            self.assertEqual(status, 409, response)

    def test_historical_merchant_approval_requires_new_platform_review(self) -> None:
        confirmation_id = self.request_review()
        self.repo.decide_confirmation(company_id=self.company_id, confirmation_id=confirmation_id, decision="approve", decided_by=self.user_id, note="Historical merchant self approval")
        status, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        self.assertEqual(status, 200, response)
        order = response["refund_reviews"][0]
        self.assertFalse(order["platform_review_verified"])
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", side_effect=AssertionError("must not reach payment provider")):
            status, response = self.request(f"/owner/billing/domestic/refunds/{self.order_id}/execute", {"company_id": self.company_id, "exact_confirmation": order["execution_confirmation"]}, account="reviewer", ops=True)
            self.assertEqual(status, 403, response)
        status, response = self.request(f"/owner/billing/domestic/refunds/{self.order_id}/review", {"company_id": self.company_id, "decision": "approve", "review_reason": "Rechecked the historical request against payment and usage evidence."}, account="reviewer", ops=True)
        self.assertEqual(status, 201, response)
        _, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        self.assertTrue(response["refund_reviews"][0]["platform_review_verified"])

    def test_audit_claim_without_live_platform_reviewer_cannot_authorize_refund(self) -> None:
        confirmation_id = self.request_review()
        self.repo.decide_confirmation(company_id=self.company_id, confirmation_id=confirmation_id, decision="approve", decided_by=self.user_id, note="Untrusted old approval")
        confirmation = self.repo.get_confirmation(company_id=self.company_id, confirmation_id=confirmation_id)
        self.repo.write_audit(company_id=self.company_id, store_id=None, user_id=self.user_id, actor_type="platform_internal_admin", action_type="billing.domestic_refund.reviewed", target_type="confirmation", target_id=confirmation_id, summary="Adversarial legacy audit fixture", details={"decision": "approve", "review_reason": "Forged role label is insufficient.", "reviewer_company_id": self.company_id, "order_id": self.order_id, "amount_minor": 9900, "currency": "CNY", "decided_at": confirmation["decided_at"]})
        _, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        self.assertFalse(response["refund_reviews"][0]["platform_review_verified"])

    def test_review_packet_has_scoped_usage_evidence_without_merchant_content(self) -> None:
        self.request_review()
        for company_id, amount in ((self.company_id, 3), (self.accounts["other"]["company"]["company_id"], 50)):
            self.repo.record_model_usage(company_id=company_id, user_id=None, task_id=None, usage_owner="jiejing_platform_trial", model_family="fixture", model_label="fixture", request_count=amount, input_tokens=10, output_tokens=20, total_tokens=30, cost_minor=0, currency="CNY", cost_status="unavailable", idempotency_key="refund-review-usage", details={"must_not_expose": "merchant private prompt fixture"})
        status, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        self.assertEqual(status, 200, response)
        evidence = response["refund_reviews"][0]["review_evidence"]
        self.assertEqual(evidence["platform_model_request_count"], 3)
        self.assertEqual(evidence["usage_scope"], "company_since_payment_not_order_allocated")
        self.assertNotIn("merchant private prompt fixture", json.dumps(response))

    def approve_and_get_packet(self) -> dict:
        self.request_review()
        status, response = self.request(f"/owner/billing/domestic/refunds/{self.order_id}/review", {"company_id": self.company_id, "decision": "approve", "review_reason": "Reviewed payment and unused entitlement evidence for this order."}, account="reviewer", ops=True)
        self.assertEqual(status, 201, response)
        _, response = self.request("/owner/billing/domestic/refunds", account="reviewer", ops=True)
        return response["refund_reviews"][0]

    def provider_packet(self, status="PROCESSING") -> dict:
        from jiejing_saas.billing_wechat_pay import build_wechat_pay_refund_id
        return {"ok": True, "query_authenticated": True, "calls_external_payment_api": True, "provider_response": {"out_trade_no": self.order_id, "out_refund_no": build_wechat_pay_refund_id(self.order_id), "refund_id": "local-refund-fixture", "status": status, "amount": {"refund": 9900, "total": 9900, "currency": "CNY"}}}

    def test_approved_query_is_available_to_merchant_and_ops(self) -> None:
        self.approve_and_get_packet()
        calls = []
        def provider(**kwargs):
            calls.append(kwargs["order_id"])
            return {"ok": False, "reason": "local-provider-not-found", "http_status": 404, "calls_external_payment_api": True}
        with patch("jiejing_saas.billing_wechat_pay.query_wechat_pay_refund_from_env", side_effect=provider):
            for path, body, account, ops in ((f"/billing/domestic/orders/{self.order_id}/refund-query", {}, "merchant", False), (f"/owner/billing/domestic/refunds/{self.order_id}/query", {"company_id": self.company_id}, "reviewer", True)):
                status, response = self.request(path, body, account=account, ops=ops)
                self.assertEqual(status, 404, response)
                self.assertEqual(response["domestic_billing_refund_query"]["reason"], "local-provider-not-found")
        self.assertEqual(calls, [self.order_id, self.order_id])

    def test_inflight_refund_cannot_be_rejected_or_sent_twice(self) -> None:
        packet = self.approve_and_get_packet()
        entered, release = threading.Event(), threading.Event()
        calls, results = [], []
        body = {"company_id": self.company_id, "exact_confirmation": packet["execution_confirmation"]}
        path = f"/owner/billing/domestic/refunds/{self.order_id}"
        def provider(**kwargs):
            calls.append(kwargs["order"]["order_id"])
            entered.set()
            self.assertTrue(release.wait(8), "test provider release timed out")
            return self.provider_packet()
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", side_effect=provider):
            worker = threading.Thread(target=lambda: results.append(self.request(path + "/execute", body, account="reviewer", ops=True)))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                status, response = self.request(path + "/review", {"company_id": self.company_id, "decision": "reject", "review_reason": "Second operator tried to revoke an already in-flight refund."}, account="reviewer", ops=True)
                self.assertEqual(status, 409, response)
                status, response = self.request(path + "/execute", body, account="reviewer", ops=True)
                self.assertEqual(status, 202, response)
                self.assertTrue(response["domestic_billing_refund_execution"]["duplicate_request"])
                self.assertEqual(calls, [self.order_id])
            finally:
                release.set()
                worker.join(10)
        self.assertEqual(results[0][0], 202, results)
        self.assertEqual(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=packet["confirmation_id"])["status"], "approved")

    def test_uncertain_send_is_query_only_and_does_not_resend(self) -> None:
        packet = self.approve_and_get_packet()
        body = {"company_id": self.company_id, "exact_confirmation": packet["execution_confirmation"]}
        path = f"/owner/billing/domestic/refunds/{self.order_id}"
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", return_value={"ok": False, "reason": "wechat_pay_transport_unavailable", "http_status": 503, "calls_external_payment_api": True}) as provider:
            status, response = self.request(path + "/execute", body, account="reviewer", ops=True)
            self.assertEqual(status, 503, response)
            self.assertEqual(self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)["status"], "refund_processing")
            status, response = self.request(path + "/execute", body, account="reviewer", ops=True)
            self.assertEqual(status, 202, response)
            self.assertTrue(response["domestic_billing_refund_execution"]["provider_query_required"])
            self.assertEqual(provider.call_count, 1)
        with patch("jiejing_saas.billing_wechat_pay.query_wechat_pay_refund_from_env", return_value=self.provider_packet()):
            status, response = self.request(path + "/query", {"company_id": self.company_id}, account="reviewer", ops=True)
            self.assertEqual(status, 202, response)
            self.assertEqual(response["domestic_billing_refund_query"]["status"], "refund_processing")

    def test_prewrite_failure_releases_claim_but_not_the_review(self) -> None:
        packet = self.approve_and_get_packet()
        body = {"company_id": self.company_id, "exact_confirmation": packet["execution_confirmation"]}
        path = f"/owner/billing/domestic/refunds/{self.order_id}/execute"
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", return_value={"ok": False, "reason": "local-configuration-missing", "http_status": 503, "calls_external_payment_api": False}):
            status, response = self.request(path, body, account="reviewer", ops=True)
            self.assertEqual(status, 503, response)
        self.assertEqual(self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)["status"], "refund_review_requested")
        with patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", return_value=self.provider_packet()) as provider:
            status, response = self.request(path, body, account="reviewer", ops=True)
            self.assertEqual(status, 202, response)
            self.assertEqual(provider.call_count, 1)

    def test_maintenance_query_passes_current_platform_allowlist(self) -> None:
        from jiejing_saas.billing_operations_maintenance import _default_refund_query
        self.approve_and_get_packet()
        with patch.dict("os.environ", {"JIEJING_INTERNAL_ADMIN_EMAILS": "platform-reviewer@example.test"}), patch("jiejing_saas.billing_wechat_pay.query_wechat_pay_refund_from_env", return_value=self.provider_packet()) as provider:
            response = _default_refund_query(self.repo, self.company_id, self.order_id)
            self.assertTrue(response["ok"], response)
            self.assertEqual(provider.call_count, 1)

    @contextmanager
    def native_confirmation_timestamp(self, value):
        """Emulate psycopg's native timestamp at the database cursor boundary."""
        connect = self.repo._connect
        class Cursor:
            def __init__(self, cursor):
                self.cursor = cursor
            def fetchone(self):
                row = self.cursor.fetchone()
                return {**dict(row), "decided_at": value} if row else None
            def __getattr__(self, name):
                return getattr(self.cursor, name)
        class Connection:
            def __init__(self, connection):
                self.connection = connection
            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                return Cursor(cursor) if "select * from confirmations" in " ".join(sql.lower().split()) else cursor
            def __getattr__(self, name):
                return getattr(self.connection, name)
        @contextmanager
        def adapted_connect():
            with connect() as connection:
                yield Connection(connection)
        with patch.object(self.repo, "_connect", adapted_connect):
            yield

    def claim_arguments(self, packet, reviewed_at):
        reviewer = self.accounts["reviewer"]
        return {"company_id": self.company_id, "order_id": self.order_id, "confirmation_id": packet["confirmation_id"],
                "reviewer_company_id": reviewer["company"]["company_id"], "reviewer_user_id": reviewer["user"]["user_id"],
                "reviewed_at": reviewed_at, "operator_company_id": reviewer["company"]["company_id"], "operator_user_id": reviewer["user"]["user_id"],
                "internal_admin_emails": self.handler.settings.internal_admin_emails}

    def test_postgres_native_and_equivalent_timezone_approval_timestamps(self) -> None:
        from jiejing_saas.billing_domestic import _approved_domestic_refund_confirmation
        packet = self.approve_and_get_packet()
        decided_at = self.repo.get_confirmation(company_id=self.company_id, confirmation_id=packet["confirmation_id"])["decided_at"]
        instant = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        for value in (instant, instant.astimezone(timezone(timedelta(hours=8))), instant.astimezone(timezone(timedelta(hours=-4))).isoformat()):
            with self.subTest(value_type=type(value).__name__), self.native_confirmation_timestamp(value):
                approval = _approved_domestic_refund_confirmation(self.repo, company_id=self.company_id, order_id=self.order_id, internal_admin_emails=self.handler.settings.internal_admin_emails)
                self.assertTrue(approval["ok"], approval)
                self.assertEqual(approval["reviewed_at"], instant.astimezone(timezone.utc).isoformat())

    def test_postgres_native_claim_timestamp_is_canonical_json_evidence(self) -> None:
        packet = self.approve_and_get_packet()
        instant = datetime.fromisoformat(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=packet["confirmation_id"])["decided_at"].replace("Z", "+00:00"))
        with self.native_confirmation_timestamp(instant):
            claim = self.repo.claim_platform_refund_execution(**self.claim_arguments(packet, instant.astimezone(timezone(timedelta(hours=8)))))
        self.assertTrue(claim["claimed"])
        expected = instant.astimezone(timezone.utc).isoformat()
        order = self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)
        self.assertEqual(order["order"]["state"]["refund_execution_reviewed_at"], expected)
        audit = self.repo.find_latest_audit_log_by_target(company_id=self.company_id, store_id=None, action_type="billing.domestic_refund.execution_claimed", target_type="billing_order", target_id=self.order_id)
        self.assertEqual(audit["details"]["reviewed_at"], expected)
        json.dumps({"order": order, "audit": audit})

    def test_ops_execution_accepts_native_database_timestamp_through_full_boundary(self) -> None:
        packet = self.approve_and_get_packet()
        instant = datetime.fromisoformat(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=packet["confirmation_id"])["decided_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        with self.native_confirmation_timestamp(instant), patch("jiejing_saas.billing_wechat_pay.request_wechat_pay_refund_from_env", return_value=self.provider_packet()) as provider:
            status, response = self.request(f"/owner/billing/domestic/refunds/{self.order_id}/execute", {"company_id": self.company_id, "exact_confirmation": packet["execution_confirmation"]}, account="reviewer", ops=True)
        self.assertEqual(status, 202, response)
        self.assertEqual(response["domestic_billing_refund_execution"]["status"], "refund_processing")
        self.assertEqual(provider.call_count, 1)
        persisted = self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)
        self.assertEqual(persisted["order"]["state"]["refund_execution_reviewed_at"], instant.isoformat())

    def test_refund_approval_rejects_invalid_naive_or_changed_review_time(self) -> None:
        from jiejing_saas.billing_domestic import _approved_domestic_refund_confirmation
        packet = self.approve_and_get_packet()
        audit = self.repo.find_latest_audit_log_by_target(company_id=self.company_id, store_id=None, action_type="billing.domestic_refund.reviewed", target_type="confirmation", target_id=packet["confirmation_id"])
        original = audit["details"]["decided_at"]
        instant = datetime.fromisoformat(original.replace("Z", "+00:00"))
        cases = [(None, None), ("not-a-time", "not-a-time"), (instant.replace(tzinfo=None), instant.replace(tzinfo=None).isoformat()), (instant + timedelta(microseconds=1), original)]
        for database_value, evidence_value in cases:
            with self.subTest(database_type=type(database_value).__name__, evidence=evidence_value):
                changed_audit = {**audit, "details": {**audit["details"], "decided_at": evidence_value}}
                with self.repo._connect() as connection:
                    connection.execute("update audit_logs set audit_json = ? where audit_id = ?", (json.dumps(changed_audit), audit["audit_id"]))
                with self.native_confirmation_timestamp(database_value):
                    result = _approved_domestic_refund_confirmation(self.repo, company_id=self.company_id, order_id=self.order_id, internal_admin_emails=self.handler.settings.internal_admin_emails)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["reason"], "domestic_refund_platform_review_required")

    def test_refund_claim_rejects_invalid_naive_or_changed_review_time(self) -> None:
        packet = self.approve_and_get_packet()
        instant = datetime.fromisoformat(self.repo.get_confirmation(company_id=self.company_id, confirmation_id=packet["confirmation_id"])["decided_at"].replace("Z", "+00:00"))
        for stored, requested in ((None, None), ("bad", "bad"), (instant.replace(tzinfo=None), instant.replace(tzinfo=None)), (instant, instant + timedelta(microseconds=1))):
            with self.subTest(stored_type=type(stored).__name__):
                with self.repo._connect() as connection:
                    connection.execute("update billing_orders set status = 'refund_review_requested' where order_id = ?", (self.order_id,))
                with self.native_confirmation_timestamp(stored), self.assertRaises(ConfirmationDecisionConflict):
                    self.repo.claim_platform_refund_execution(**self.claim_arguments(packet, requested))
                self.assertEqual(self.repo.get_domestic_billing_order(company_id=self.company_id, order_id=self.order_id)["status"], "refund_review_requested")


if __name__ == "__main__":
    unittest.main()
