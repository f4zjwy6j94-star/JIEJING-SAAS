#!/usr/bin/env python3
"""Regression for Stripe Checkout and Customer Portal billing boundary."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_checkout import (  # noqa: E402
    STRIPE_API_VERSION,
    build_billing_checkout_contract,
    create_stripe_checkout_session,
    create_stripe_customer_portal_session,
)
from jiejing_saas.billing_plan import build_billing_plan  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-stripe-checkout-test"


class FakeStripeHandler(BaseHTTPRequestHandler):
    calls: list[dict[str, object]] = []

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or "0")
        body = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(body)
        FakeStripeHandler.calls.append(
            {
                "path": self.path,
                "auth_present": bool(self.headers.get("authorization")),
                "stripe_version": self.headers.get("stripe-version"),
                "body": {key: values[0] if values else "" for key, values in parsed.items()},
            }
        )
        if self.path == "/v1/checkout/sessions":
            payload = {"id": "cs_test_unit", "url": "https://checkout.stripe.test/session", "expires_at": 1893456000}
        elif self.path == "/v1/billing_portal/sessions":
            payload = {"id": "bps_test_unit", "url": "https://billing.stripe.test/session"}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "billing.sqlite"
    runtime_db_path = OUT / "runtime.sqlite"
    db_path.unlink(missing_ok=True)
    runtime_db_path.unlink(missing_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStripeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous = _set_env(server.server_address[1])
    try:
        settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
        repository = SaaSRepository(db_path)
        fixture = repository.create_user_with_company(
            email="stripe-checkout@jiejing.local",
            password="unit-test-password",
            company_name="Jiejing Stripe Checkout Test",
        )
        company_id = fixture["company"]["company_id"]
        user_id = fixture["user"]["user_id"]

        contract = build_billing_checkout_contract()
        if contract.get("ready_for_paid_launch") is not True:
            return fail(f"checkout contract should be ready with Stripe env: {contract}")
        if contract.get("urls", {}).get("request_override_must_match_configured_url") is not True:
            return fail(f"checkout contract should lock request return URL overrides to configured URLs: {contract.get('urls')}")
        if contract.get("stripe_api_version") != "2026-05-27.dahlia" or STRIPE_API_VERSION != "2026-05-27.dahlia":
            return fail(f"Stripe API version should match the current official version: {contract.get('stripe_api_version')}")

        checkout = create_stripe_checkout_session(
            repository,
            company_id=company_id,
            user_id=user_id,
            plan_key="starter",
        )
        if checkout.get("ok") is not True or checkout.get("checkout_session", {}).get("url") != "https://checkout.stripe.test/session":
            return fail(f"checkout session should be created through backend adapter: {checkout}")
        first_call = FakeStripeHandler.calls[0]
        body = first_call.get("body") if isinstance(first_call.get("body"), dict) else {}
        if first_call.get("path") != "/v1/checkout/sessions" or body.get("mode") != "subscription":
            return fail(f"checkout call should use subscription Checkout Sessions: {first_call}")
        if body.get("success_url") != "https://app.example.test/billing/success" or body.get("cancel_url") != "https://app.example.test/billing/cancel":
            return fail(f"checkout call should use configured stable-domain return URLs: {first_call}")
        if first_call.get("stripe_version") != STRIPE_API_VERSION:
            return fail(f"checkout call should pin the expected Stripe-Version header: {first_call}")
        if body.get("metadata[company_id]") != company_id or body.get("line_items[0][price]") != "price_starter_unit":
            return fail(f"checkout call should include company metadata and Stripe price id: {first_call}")
        before_blocked_override = len(FakeStripeHandler.calls)
        blocked_override = create_stripe_checkout_session(
            repository,
            company_id=company_id,
            user_id=user_id,
            plan_key="starter",
            success_url="https://evil.example/billing/success",
            cancel_url="https://app.example.test/billing/cancel",
        )
        if blocked_override.get("ok") is not False or "billing_success_url_not_allowed" not in blocked_override.get("blocked_by", []):
            return fail(f"checkout should block unconfigured success_url override: {blocked_override}")
        if len(FakeStripeHandler.calls) != before_blocked_override:
            return fail("blocked checkout return URL override must not call Stripe")

        repository.apply_billing_webhook_event(
            event={
                "provider": "stripe",
                "event_id": "evt_checkout_unit",
                "event_type": "customer.subscription.updated",
                "company_id": company_id,
                "provider_customer_id": "cus_checkout_unit",
                "provider_subscription_id": "sub_checkout_unit",
                "provider_plan_id": "price_starter_unit",
                "plan_key": "starter",
                "subscription_status": "active",
                "quota_recalculation_required": True,
                "payment_attention_required": False,
                "secret_exposed": False,
            }
        )
        portal = create_stripe_customer_portal_session(
            repository,
            company_id=company_id,
            user_id=user_id,
        )
        if portal.get("ok") is not True or portal.get("customer_portal", {}).get("url") != "https://billing.stripe.test/session":
            return fail(f"customer portal should be created for existing Stripe customer: {portal}")
        portal_call = FakeStripeHandler.calls[-1]
        portal_body = portal_call.get("body") if isinstance(portal_call.get("body"), dict) else {}
        if portal_call.get("path") != "/v1/billing_portal/sessions" or portal_body.get("return_url") != "https://app.example.test/settings/billing":
            return fail(f"portal call should use configured stable-domain return URL: {portal_call}")
        before_blocked_portal = len(FakeStripeHandler.calls)
        blocked_portal = create_stripe_customer_portal_session(
            repository,
            company_id=company_id,
            user_id=user_id,
            return_url="https://evil.example/settings/billing",
        )
        if blocked_portal.get("ok") is not False or "billing_portal_return_url_not_allowed" not in blocked_portal.get("blocked_by", []):
            return fail(f"portal should block unconfigured return_url override: {blocked_portal}")
        if len(FakeStripeHandler.calls) != before_blocked_portal:
            return fail("blocked portal return URL override must not call Stripe")

        plan = build_billing_plan(settings, repository)
        if plan.get("billing_ready_for_paid_launch") is not True:
            return fail(f"Stripe billing plan should satisfy paid launch contract in this controlled fixture: {plan.get('paid_launch_blockers')}")
        matrix = {item.get("key"): item for item in plan.get("billing_live_cutover_matrix", []) if isinstance(item, dict)}
        if set(matrix) != {
            "stripe_live_provider_selected",
            "stripe_live_price_catalog",
            "stripe_subscription_checkout_contract",
            "stripe_customer_portal_contract",
            "stripe_signed_webhook_contract",
            "stripe_api_webhook_version_alignment",
            "stripe_webhook_failure_paths",
            "stripe_entitlement_quota_lifecycle",
        }:
            return fail(f"billing live cutover matrix missing or unexpected: {sorted(matrix)}")
        summary = plan.get("billing_live_cutover_summary") if isinstance(plan.get("billing_live_cutover_summary"), dict) else {}
        if summary.get("total_count") != 8 or summary.get("ready_count") != 8 or summary.get("ready_for_owner_approval") is not True:
            return fail(f"billing live cutover summary should be green in controlled fixture: {summary}")
        for key, item in matrix.items():
            if item.get("triggers_real_charge") is not False or item.get("charge_now_allowed") is not False:
                return fail(f"billing cutover step must not directly charge: {key}")
            if item.get("frontend_gets_payment_secret") is not False or item.get("secret_exposed") is not False:
                return fail(f"billing cutover step must not expose payment secrets: {key}")
        if matrix["stripe_subscription_checkout_contract"].get("status") != "ready":
            return fail("Checkout contract step should be ready in Stripe fixture")
        if matrix["stripe_signed_webhook_contract"].get("status") != "ready":
            return fail("signed webhook step should be ready in Stripe fixture")
        webhook_proof = (
            matrix["stripe_webhook_failure_paths"].get("local_contract_proof")
            if isinstance(matrix["stripe_webhook_failure_paths"].get("local_contract_proof"), dict)
            else {}
        )
        for proof_key in (
            "duplicate_event_idempotent",
            "unsupported_event_cannot_grant_entitlement",
            "missing_event_id_cannot_grant_entitlement",
            "unmapped_provider_identity_cannot_grant_entitlement",
        ):
            if webhook_proof.get(proof_key) is not True:
                return fail(f"webhook failure-path local contract proof missing: {proof_key}={webhook_proof.get(proof_key)}")
        if webhook_proof.get("raw_webhook_payload_persisted") is not False:
            return fail(f"webhook local proof must keep raw payload out of persistence: {webhook_proof}")
        shutdown_closure = (
            plan.get("subscription_quota_shutdown_closure")
            if isinstance(plan.get("subscription_quota_shutdown_closure"), dict)
            else {}
        )
        if shutdown_closure.get("ready_for_live_cutover") is not True or shutdown_closure.get("ready_count") != shutdown_closure.get("total_count"):
            return fail(f"Stripe fixture should prove subscription/quota shutdown closure: {shutdown_closure}")
        if shutdown_closure.get("mode") != "live_provider_rehearsal":
            return fail(f"Stripe fixture should report live-provider rehearsal mode: {shutdown_closure}")
        guards = shutdown_closure.get("shutdown_guards") if isinstance(shutdown_closure.get("shutdown_guards"), dict) else {}
        if guards.get("payment_failure_blocks_metered_work") is not True or guards.get("cancellation_blocks_metered_work") is not True:
            return fail(f"Stripe fixture should prove shutdown guards: {guards}")
        shutdown_keys = {item.get("key") for item in shutdown_closure.get("steps", []) if isinstance(item, dict)}
        if {
            "subscription_activation_grants_entitlement",
            "invoice_paid_keeps_quota_open",
            "payment_failed_disables_entitlement",
            "subscription_cancel_disables_entitlement",
            "quota_guardrail_blocks_metered_work",
            "customer_portal_changes_audited",
            "provider_cutover_no_real_charge_safety",
        } - shutdown_keys:
            return fail(f"shutdown closure missing required lifecycle steps: {shutdown_keys}")
        for flag in ("creates_checkout_session", "calls_stripe_api", "triggers_real_charge", "charge_now_allowed", "frontend_gets_payment_secret", "secret_exposed"):
            if shutdown_closure.get(flag) is not False:
                return fail(f"shutdown closure must not enable charge path directly: {flag}={shutdown_closure.get(flag)}")

        serialized = json.dumps({"checkout": checkout, "portal": portal, "plan": plan}, ensure_ascii=False)
        for forbidden in ["unit_stripe_secret", "whsec_checkout_unit", "authorization"]:
            if forbidden in serialized.lower():
                return fail(f"billing output leaked forbidden marker: {forbidden}")
        print("PASS jiejing_stripe_checkout_portal")
        return 0
    finally:
        _restore_env(previous)
        server.shutdown()
        thread.join(timeout=5)


def _set_env(port: int) -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_BILLING_PROVIDER",
        "JIEJING_BILLING_PLANS_PUBLISHED",
        "JIEJING_QUOTA_ENFORCEMENT_ENABLED",
        "JIEJING_STRIPE_SECRET_KEY",
        "JIEJING_STRIPE_WEBHOOK_SECRET",
        "JIEJING_BILLING_WEBHOOK_URL",
        "JIEJING_STRIPE_PRICE_STARTER_ID",
        "JIEJING_STRIPE_PRICE_OPERATOR_ID",
        "JIEJING_STRIPE_PRICE_TEAM_ID",
        "JIEJING_BILLING_SUCCESS_URL",
        "JIEJING_BILLING_CANCEL_URL",
        "JIEJING_BILLING_PORTAL_RETURN_URL",
        "JIEJING_STRIPE_API_BASE",
        "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRICES_VERIFIED",
        "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
        "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED",
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_STRIPE_SECRET_KEY": "unit_stripe_secret",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_checkout_unit",
            "JIEJING_BILLING_WEBHOOK_URL": "https://app.example.test/billing/webhook",
            "JIEJING_STRIPE_PRICE_STARTER_ID": "price_starter_unit",
            "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_operator_unit",
            "JIEJING_STRIPE_PRICE_TEAM_ID": "price_team_unit",
            "JIEJING_BILLING_SUCCESS_URL": "https://app.example.test/billing/success",
            "JIEJING_BILLING_CANCEL_URL": "https://app.example.test/billing/cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": "https://app.example.test/settings/billing",
            "JIEJING_STRIPE_API_BASE": f"http://127.0.0.1:{port}",
            "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRICES_VERIFIED": "1",
            "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG": "1",
            "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED": "1",
            "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED": "1",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED": "1",
            "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED": "1",
            "JIEJING_STRIPE_INVOICE_PAID_TESTED": "1",
            "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED": "1",
        }
    )
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
