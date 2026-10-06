"""Public billing projection regression; isolated SQLite, no provider calls."""
from pathlib import Path
import json
import gc
from datetime import datetime, timedelta, timezone
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jiejing_saas.billing_plan import build_billing_usage, evaluate_quota_action
from jiejing_saas.media_credits import build_merchant_media_credit_summary, grant_plan_media_points
from jiejing_saas.repository import SaaSRepository


class BillingEntitlementProjectionTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_DEFAULT_PLAN_KEY": "starter",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tmp = tempfile.TemporaryDirectory(prefix="jiejing-billing-projection-")
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(gc.collect)
        self.repo = SaaSRepository(Path(self.tmp.name) / "test.sqlite")
        fixture = self.repo.create_user_with_company(
            email="projection@example.test", password="fixture-password-only", company_name="Projection test")
        self.company = fixture["company"]["company_id"]
        self.user = fixture["user"]["user_id"]

    def apply_subscription(self, *, status="active", until="2099-10-24T00:00:00Z", provider="wechat_pay_native"):
        return self.repo.apply_billing_webhook_event(event={
            "provider": provider, "event_id": f"fixture-{status}-{until}",
            "event_type": "subscription_updated", "supported_event": True,
            "company_id": self.company, "plan_key": "starter",
            "provider_customer_id": "fixture-merchant", "provider_subscription_id": "fixture-order",
            "provider_plan_id": "fixture-plan", "subscription_status": status,
            "duration_days": 30, "active_until": until,
        })

    def production_usage(self, company=None):
        return build_billing_usage(SimpleNamespace(environment="production"), self.repo,
            company_id=company or self.company)

    def test_production_manual_seed_cannot_restore_refunded_paid_access(self):
        self.apply_subscription(status="refunded")
        with patch.dict("os.environ", {"JIEJING_QUOTA_ENFORCEMENT_ENABLED": "true"}):
            usage = self.production_usage()
            action = evaluate_quota_action(SimpleNamespace(environment="production"), self.repo,
                company_id=self.company, action_unit="ai_ceo_task")
        self.assertFalse(usage["subscription"]["entitlement_active"])
        self.assertEqual(usage["subscription"]["status"], "refunded")
        self.assertEqual(usage["subscription"]["provider"], "wechat_pay_native")
        self.assertEqual(usage["plan"]["key"], "free")
        self.assertFalse(action["allowed"])

    def test_production_paid_access_requires_a_valid_unexpired_term(self):
        for until in ("", "not-a-date", "2000-01-01T00:00:00Z"):
            with self.subTest(until=until):
                self.apply_subscription(until=until)
                usage = self.production_usage()
                self.assertFalse(usage["subscription"]["entitlement_active"])
                self.assertEqual(usage["plan"]["key"], "free")
        self.apply_subscription()
        paid = self.production_usage()
        self.assertTrue(paid["subscription"]["entitlement_active"])
        self.assertEqual(paid["plan"]["key"], "starter")
        self.assertEqual(paid["plan"]["source"], "provider_subscription")
        self.assertEqual(paid["subscription"]["active_until"], "2099-10-24T00:00:00Z")

    def test_owner_preview_is_exact_tenant_scoped_and_preserves_billing_history(self):
        self.apply_subscription(status="refunded")
        other = self.repo.create_user_with_company(
            email="unlisted@example.test", password="fixture-password-only", company_name="Unlisted")
        other_company = other["company"]["company_id"]
        with patch.dict("os.environ", {"JIEJING_BILLING_PREVIEW_COMPANY_ALLOWLIST": self.company}):
            preview = self.production_usage()
            other_usage = self.production_usage(other_company)
        self.assertTrue(preview["subscription"]["entitlement_active"])
        self.assertEqual(preview["subscription"]["provider"], "owner_preview")
        self.assertEqual(preview["subscription"]["access_kind"], "owner_preview")
        self.assertTrue(preview["subscription"]["test_mode"])
        self.assertFalse(preview["subscription"].get("active_until"))
        self.assertEqual(preview["plan"]["key"], "starter")
        self.assertEqual(preview["media_credits"]["available_points"], 0)
        self.assertFalse(preview["real_platform_writes_enabled"])
        self.assertNotEqual(other_usage["subscription"]["provider"], "owner_preview")
        self.assertEqual(self.repo.get_billing_subscription(company_id=self.company)["status"], "refunded")
        self.assertNotIn(self.company, json.dumps(preview["subscription"]))
        for allowlist in ("*", self.company[:-1], self.company + "-suffix", ""):
            with self.subTest(allowlist=allowlist), patch.dict("os.environ", {
                "JIEJING_BILLING_PREVIEW_COMPANY_ALLOWLIST": allowlist,
            }):
                self.assertFalse(self.production_usage()["subscription"]["entitlement_active"])
        self.apply_subscription()
        with patch.dict("os.environ", {"JIEJING_BILLING_PREVIEW_COMPANY_ALLOWLIST": self.company}):
            self.assertEqual(self.production_usage()["subscription"]["provider"], "wechat_pay_native")

    def test_free_trial_remains_seven_days_without_paid_or_media_entitlements(self):
        # Missing challenge withholds platform-funded AI, not the merchant's BYOK access.
        self.repo.upsert_platform_trial_activation(company_id=self.company, user_id=self.user,
            status="verification_required", platform_trial_allowed=False, requires_challenge=True,
            challenge_attested=False, decision_reason="fixture")
        with patch.dict("os.environ", {"JIEJING_QUOTA_ENFORCEMENT_ENABLED": "true"}):
            usage = self.production_usage()
            action = evaluate_quota_action(SimpleNamespace(environment="production"), self.repo,
                company_id=self.company, action_unit="ai_ceo_task")
        self.assertTrue(action["allowed"])
        self.assertEqual(usage["plan"]["key"], "free")
        self.assertEqual(usage["subscription"]["access_kind"], "free_trial")
        self.assertEqual(usage["plan"]["media_points_included"], 0)
        self.assertEqual(usage["media_credits"]["available_points"], 0)
        self.assertFalse(self.repo.get_platform_trial_activation(company_id=self.company)["platform_trial_allowed"])
        created = datetime.fromisoformat(self.repo.get_company(self.company)["created_at"])
        until = datetime.fromisoformat(usage["subscription"]["active_until"])
        self.assertEqual(until - created, timedelta(days=7))
        class ExpiredClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return (until + timedelta(seconds=1)).astimezone(tz or timezone.utc)
        with patch("jiejing_saas.billing_plan.datetime", ExpiredClock):
            expired = self.production_usage()
        self.assertFalse(expired["subscription"]["entitlement_active"])
        self.assertEqual(expired["subscription"]["status"], "free_trial_expired")

    def test_team_seats_use_the_same_production_entitlement_as_usage(self):
        self.apply_subscription(status="refunded")
        with patch.dict("os.environ", {"JIEJING_SAAS_ENV": "production", "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "true"}):
            with self.assertRaisesRegex(ValueError, "team_member_quota_exhausted"):
                self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
                    email="extra@example.test", role="viewer")
            self.assertEqual(self.repo.list_team_invitations(company_id=self.company), [])
            with patch.dict("os.environ", {"JIEJING_BILLING_PREVIEW_COMPANY_ALLOWLIST": self.company}):
                self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
                    email="extra@example.test", role="viewer")
                with self.assertRaisesRegex(ValueError, "team_member_quota_exhausted"):
                    self.repo.create_team_invitation(company_id=self.company, invited_by=self.user,
                        email="excess@example.test", role="viewer")

    def test_simulated_subscription_cannot_become_paid_production_access(self):
        self.apply_subscription(provider="stripe_test_mock")
        usage = self.production_usage()
        self.assertFalse(usage["subscription"]["entitlement_active"])
        self.assertEqual(usage["plan"]["key"], "free")
        self.assertEqual(usage["media_credits"]["available_points"], 0)

    def test_paid_refund_cannot_restart_a_free_trial(self):
        self.repo.upsert_platform_trial_activation(company_id=self.company, user_id=self.user,
            status="active", platform_trial_allowed=True, requires_challenge=True,
            challenge_attested=True, decision_reason="fixture")
        self.apply_subscription(status="refunded")
        usage = self.production_usage()
        self.assertFalse(usage["subscription"]["entitlement_active"])
        self.assertNotEqual(usage["subscription"].get("access_kind"), "free_trial")

    def test_usage_cannot_leak_internal_media_ledger_or_testing_credits(self):
        self.repo.apply_media_credit_operation(
            company_id=self.company, user_id=self.user, operation_type="grant", points=320,
            idempotency_key="internal-unique", reference_type="controlled_acceptance",
            reference_id="internal-only-reference", details={"credit_source":"controlled_acceptance",
                "source_reference_id":"internal-only-reference", "expires_at":"2099-01-01T00:00:00Z"})
        usage = build_billing_usage(SimpleNamespace(environment="local_dev"), self.repo, company_id=self.company)
        expected = build_merchant_media_credit_summary(self.repo, company_id=self.company)
        self.assertEqual(usage["media_credits"], expected)
        self.assertEqual(usage["media_credits"]["available_points"], 0)
        encoded = json.dumps(usage["media_credits"])
        for forbidden in ("internal-only-reference", "recent_activity", "ledger_id", "owner_testing_points"):
            self.assertNotIn(forbidden, encoded)

    def test_purchase_closure_distinguishes_not_open_from_payment_unavailable(self):
        closed = build_merchant_media_credit_summary(self.repo, company_id=self.company)
        self.assertFalse(closed["purchase"]["purchase_enabled"])
        self.assertEqual(closed["purchase"].get("unavailable_reason"), "not_open")
        with patch.dict("os.environ", {"JIEJING_MEDIA_CREDIT_PURCHASE_ENABLED":"true"}):
            unavailable = build_merchant_media_credit_summary(self.repo, company_id=self.company)
        self.assertFalse(unavailable["purchase"]["purchase_enabled"])
        self.assertEqual(unavailable["purchase"].get("unavailable_reason"), "payment_unavailable")

    def test_preview_access_is_not_given_a_fabricated_paid_term(self):
        usage = build_billing_usage(SimpleNamespace(environment="local_dev"), self.repo, company_id=self.company)
        self.assertEqual(usage["subscription"]["status"], "private_beta_manual_seed")
        self.assertTrue(usage["subscription"]["entitlement_active"])
        self.assertFalse(usage["subscription"].get("active_until"))

    def test_live_provider_retains_verified_expiry_and_plan_points(self):
        event = {"provider":"wechat_pay_native", "event_id":"fixture-paid", "event_type":"payment_succeeded",
            "supported_event":True, "company_id":self.company, "plan_key":"starter",
            "provider_customer_id":"fixture-merchant", "provider_subscription_id":"fixture-order",
            "provider_plan_id":"fixture-plan", "subscription_status":"active",
            "duration_days":30, "active_until":"2099-10-24T00:00:00Z"}
        applied = self.repo.apply_billing_webhook_event(event=event)
        self.assertEqual(applied["status"], "applied")
        for _ in range(2):
            grant_plan_media_points(self.repo, company_id=self.company, user_id=self.user,
                plan_key="starter", order_id="fixture-order", expires_at=event["active_until"])
        with patch.dict("os.environ", {"JIEJING_BILLING_PROVIDER":"wechat_pay_native"}):
            usage = build_billing_usage(SimpleNamespace(environment="local_dev"), self.repo, company_id=self.company)
        self.assertTrue(usage["subscription"]["entitlement_active"])
        self.assertEqual(usage["subscription"]["active_until"], event["active_until"])
        self.assertEqual(usage["media_credits"]["included_points"], 1000)
        self.assertEqual(usage["media_credits"]["available_points"], 1000)
        other = self.repo.create_user_with_company(
            email="other@example.test", password="fixture-password-only", company_name="Other")
        isolated = build_billing_usage(SimpleNamespace(environment="local_dev"), self.repo,
            company_id=other["company"]["company_id"])
        self.assertEqual(isolated["media_credits"]["available_points"], 0)


if __name__ == "__main__":
    unittest.main()
