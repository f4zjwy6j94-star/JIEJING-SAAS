#!/usr/bin/env python3
"""Tenant-scoped team seats include pending invitations and serialize admission."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler
from jiejing_saas.billing_plan import build_billing_usage
from jiejing_saas.config import SaaSSettings
from jiejing_saas.repository import SaaSRepository
from jiejing_saas.security import SessionManager


class TeamSeatQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jiejing-team-seats-", ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_DEFAULT_PLAN_KEY": "starter",
            "JIEJING_SAAS_ENV": "test",
        })
        self.env.start()
        self.repo = SaaSRepository(self.root / "saas.sqlite")
        self.owner = self.register("owner@example.invalid")
        self.company = self.owner["company"]["company_id"]
        self.user = self.owner["user"]["user_id"]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def register(self, email):
        return self.repo.create_user_with_company(email=email, password="test-seat-password", company_name=email)

    def invite(self, email, role="viewer"):
        return self.repo.create_team_invitation(company_id=self.company, invited_by=self.user, email=email, role=role)

    def blocked(self, email, role="viewer"):
        with self.assertRaisesRegex(ValueError, "team_member_quota_exhausted") as caught:
            self.invite(email, role)
        return getattr(caught.exception, "quota", {})

    def test_free_owner_occupies_only_seat(self):
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "free"
        quota = self.blocked("new@example.invalid")
        self.assertEqual((quota["used"], quota["limit"]), (1, 1))
        self.assertEqual(self.repo.list_team_invitations(company_id=self.company), [])

    def test_pending_invites_reserve_seat_and_duplicate_is_idempotent(self):
        first = self.invite("new@example.invalid")
        duplicate = self.invite(" NEW@EXAMPLE.INVALID ")
        self.assertEqual(first["invitation_id"], duplicate["invitation_id"])
        self.assertEqual(len(self.repo.list_team_invitations(company_id=self.company)), 1)
        quota = self.blocked("another@example.invalid", "admin")
        self.assertEqual((quota["member_count"], quota["pending_invitation_count"], quota["limit"]), (1, 1, 2))

    def test_registered_user_joins_and_reinvite_cannot_change_role(self):
        account = self.register("member@example.invalid")
        first = self.invite(account["user"]["email"], "viewer")
        self.assertEqual(first["status"], "accepted_existing_user_added")
        duplicate = self.invite(account["user"]["email"], "admin")
        self.assertEqual(duplicate["invitation_id"], first["invitation_id"])
        member = self.repo.get_team_member(company_id=self.company, user_id=account["user"]["user_id"])
        self.assertEqual(member["role"], "viewer")
        self.blocked("third@example.invalid", "operator")

    def test_pending_acceptance_swaps_reserved_seat_for_membership(self):
        pending = self.invite("later@example.invalid")
        account = self.register("later@example.invalid")
        accepted = self.invite("later@example.invalid")
        self.assertEqual(accepted["invitation_id"], pending["invitation_id"])
        self.assertEqual(accepted["status"], "accepted_existing_user_added")
        self.assertIsNotNone(self.repo.get_team_member(company_id=self.company, user_id=account["user"]["user_id"]))
        self.assertEqual(len(self.repo.list_team_members(company_id=self.company)), 2)
        self.blocked("third@example.invalid")

    def test_pending_acceptance_rechecks_downgraded_plan(self):
        pending = self.invite("later@example.invalid")
        account = self.register("later@example.invalid")
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "free"
        self.blocked("later@example.invalid", "admin")
        self.assertIsNone(self.repo.get_team_member(company_id=self.company, user_id=account["user"]["user_id"]))
        invitations = self.repo.list_team_invitations(company_id=self.company)
        self.assertEqual([(x["invitation_id"], x["status"]) for x in invitations], [(pending["invitation_id"], "pending")])

    def test_operator_plan_has_five_total_seats(self):
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "operator"
        for number in range(4):
            self.invite(f"member{number}@example.invalid")
        quota = self.blocked("fifth-invite@example.invalid")
        self.assertEqual((quota["used"], quota["limit"]), (5, 5))

    def test_active_subscription_entitlement_overrides_free_default(self):
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "free"
        os.environ["JIEJING_BILLING_PROVIDER"] = "stripe_test_mock"
        with self.repo._connect() as conn:
            conn.execute(
                """
                insert into billing_subscriptions (
                  company_id, provider, plan_key, status, entitlement_active,
                  payment_attention_required, updated_at, subscription_json
                ) values (?, 'stripe_test_mock', 'operator', 'active', 1, 0, ?, '{}')
                """,
                (self.company, "2026-09-05T00:00:00+00:00"),
            )
        self.invite("paid-member@example.invalid")
        with self.repo._connect() as conn:
            conn.execute("update billing_subscriptions set entitlement_active = 0 where company_id = ?", (self.company,))
        quota = self.blocked("after-expiry@example.invalid")
        self.assertEqual((quota["plan_key"], quota["limit"]), ("free", 1))

    def test_explicit_development_quota_switch_remains_supported(self):
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "free"
        os.environ["JIEJING_QUOTA_ENFORCEMENT_ENABLED"] = "0"
        self.invite("development@example.invalid")

    def apply_subscription(self, *, provider="wechat_pay_native", active_until=None):
        os.environ["JIEJING_DEFAULT_PLAN_KEY"] = "free"
        os.environ["JIEJING_BILLING_PROVIDER"] = provider
        result = self.repo.apply_billing_webhook_event(event={
            "provider": provider, "event_id": "seat-entitlement-fixture",
            "event_type": "payment_succeeded", "company_id": self.company,
            "provider_customer_id": "verified-domestic-payment",
            "provider_subscription_id": "seat-entitlement-order",
            "provider_plan_id": "wechat_native_operator_19900_30d",
            "plan_key": "operator", "subscription_status": "active",
            "payment_attention_required": False,
            "active_until": active_until or (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        })
        self.assertEqual(result["status"], "applied")

    def billing_usage(self):
        settings = SaaSSettings.from_env(db_path=self.root / "saas.sqlite", runtime_db_path=self.root / "runtime.sqlite", output_root=self.root, host="127.0.0.1", port=0)
        return build_billing_usage(settings, self.repo, company_id=self.company)

    def test_real_wechat_subscription_grants_paid_seats_and_usage(self):
        self.apply_subscription()
        usage = self.billing_usage()
        self.assertEqual(usage["plan"]["key"], "operator")
        self.assertTrue(usage["subscription"]["entitlement_active"])
        for number in range(4):
            self.invite(f"wechat-member{number}@example.invalid")
        self.assertEqual(self.blocked("wechat-sixth@example.invalid")["limit"], 5)

    def test_expired_subscription_flag_cannot_grant_paid_seats_or_usage(self):
        self.apply_subscription(active_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        self.assertTrue(self.repo.get_billing_subscription(company_id=self.company)["entitlement_active"])
        usage = self.billing_usage()
        self.assertEqual(usage["plan"]["key"], "free")
        self.assertFalse(usage["subscription"]["entitlement_active"])
        self.assertEqual(self.blocked("expired-member@example.invalid")["limit"], 1)

    def test_invalid_subscription_expiry_fails_closed(self):
        self.apply_subscription(active_until="not-a-date")
        self.assertFalse(self.billing_usage()["subscription"]["entitlement_active"])
        self.assertEqual(self.blocked("invalid-date@example.invalid")["plan_key"], "free")

    def test_unsupported_billing_provider_still_cannot_grant_paid_seats(self):
        self.apply_subscription(provider="unrecognized_payment_provider")
        self.assertEqual(self.billing_usage()["plan"]["key"], "free")
        self.assertEqual(self.blocked("unsupported-provider@example.invalid")["limit"], 1)

    def test_expired_supported_test_provider_also_falls_back(self):
        self.apply_subscription(provider="stripe_test_mock", active_until="2000-01-01T00:00:00Z")
        self.assertEqual(self.billing_usage()["plan"]["key"], "free")
        self.assertEqual(self.blocked("expired-test-provider@example.invalid")["limit"], 1)

    def test_concurrent_last_seat_allows_exactly_one(self):
        start = threading.Barrier(2)

        def run(number):
            start.wait(timeout=5)
            try:
                return self.invite(f"racer{number}@example.invalid")["invitation_id"]
            except ValueError as exc:
                self.assertEqual(str(exc), "team_member_quota_exhausted")
                return "blocked"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, range(2)))
        self.assertEqual(results.count("blocked"), 1)
        self.assertEqual(len(self.repo.list_team_invitations(company_id=self.company)), 1)

    def test_concurrent_duplicate_returns_same_invitation(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            invitations = list(executor.map(lambda _: self.invite("same@example.invalid"), range(4)))
        self.assertEqual(len({x["invitation_id"] for x in invitations}), 1)
        self.assertEqual(len(self.repo.list_team_invitations(company_id=self.company)), 1)

    def test_other_tenant_does_not_consume_this_company_seat(self):
        other = self.register("other-owner@example.invalid")
        self.repo.create_team_invitation(company_id=other["company"]["company_id"], invited_by=other["user"]["user_id"], email="other-member@example.invalid", role="viewer")
        self.invite("our-member@example.invalid")
        self.assertEqual(len(self.repo.list_team_invitations(company_id=self.company)), 1)

    def test_http_reports_bounded_merchant_quota_error(self):
        sessions = SessionManager(secret="team-seat-local-test-session-secret")

        class Handler(SaaSBackendHandler):
            def log_message(self, *_args):
                pass

        Handler.repository = self.repo
        Handler.sessions = sessions
        Handler.settings = SaaSSettings.from_env(db_path=self.root / "saas.sqlite", runtime_db_path=self.root / "runtime.sqlite", output_root=self.root, host="127.0.0.1", port=0)
        token = sessions.create_token(user_id=self.user, company_id=self.company, email=self.owner["user"]["email"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.invite("full@example.invalid")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/team/invitations",
                data=json.dumps({"email": "blocked@example.invalid", "role": "admin", "team_member_quota": 999}).encode(),
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"}, method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=30)
            self.assertEqual(caught.exception.code, 402)
            payload = json.loads(caught.exception.read().decode())
            self.assertEqual(payload["error"], "team_member_quota_exhausted")
            self.assertEqual(payload["quota"]["limit"], 2)
            self.assertIn("席位", payload["merchant_message"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
