#!/usr/bin/env python3
"""Regression for the live billing provider evidence register."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_plan import STRIPE_CURRENT_API_VERSION  # noqa: E402
from jiejing_saas.billing_provider_evidence_register import build_billing_provider_evidence_register  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-billing-provider-evidence-register-test"
EXPECTED_ROWS = {
    "live_provider_account",
    "stripe_account_activation_go_live_evidence",
    "stripe_live_price_catalog",
    "stripe_live_mode_test_object_isolation",
    "stripe_subscription_checkout_contract",
    "stripe_customer_portal_contract",
    "stripe_signed_webhook_contract",
    "stripe_api_webhook_version_alignment",
    "stripe_webhook_failure_paths",
    "stripe_entitlement_quota_lifecycle",
    "stripe_tax_invoice_receipt_branding_evidence",
    "stable_domain_billing_callbacks",
    "cutover_rollback_audit_packet",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    previous = _set_blocked_env()
    try:
        blocked = _build("blocked.sqlite")
        if blocked.get("status") != "blocked" or blocked.get("ready_for_owner_review") is not False:
            return fail(f"manual provider fixture must stay blocked: {blocked.get('summary')}")
        if blocked.get("public_paid_launch_allowed") is not False or blocked.get("charge_now_allowed") is not False:
            return fail("evidence register must never directly allow public charging")
        rows = {item.get("key"): item for item in blocked.get("evidence_rows", []) if isinstance(item, dict)}
        if set(rows) != EXPECTED_ROWS:
            return fail(f"evidence register rows missing or unexpected: {sorted(rows)}")
        if rows["live_provider_account"].get("status") != "blocked":
            return fail("manual_seed must not satisfy live provider account evidence")
        if blocked.get("calls_stripe_api") is not False or blocked.get("creates_checkout_session") is not False:
            return fail("read-only register must not call Stripe or create Checkout sessions")
    finally:
        _restore_env(previous)

    previous = _set_ready_env()
    try:
        ready = _build("ready.sqlite")
        if ready.get("status") != "ready_for_owner_review" or ready.get("ready_for_owner_review") is not True:
            return fail(f"complete Stripe fixture should be ready for owner review: {ready.get('summary')}")
        summary = ready.get("summary") if isinstance(ready.get("summary"), dict) else {}
        if summary.get("ready_count") != len(EXPECTED_ROWS) or summary.get("blocked_count") != 0:
            return fail(f"all provider evidence rows should be ready: {summary}")
        rows = {item.get("key"): item for item in ready.get("evidence_rows", []) if isinstance(item, dict)}
        for key, item in rows.items():
            if item.get("status") != "ready":
                return fail(f"ready fixture row should be ready: {key}={item}")
            for flag in ("creates_checkout_session", "calls_stripe_api", "triggers_real_charge", "charge_now_allowed", "triggers_ebay_oauth", "triggers_real_platform_write"):
                if item.get(flag) is not False:
                    return fail(f"row must not trigger side effects: {key}.{flag}={item.get(flag)}")
            if item.get("secret_value_returned") is not False or item.get("secret_exposed") is not False:
                return fail(f"row must not expose secret values: {key}")
        owner = ready.get("owner_approval") if isinstance(ready.get("owner_approval"), dict) else {}
        if owner.get("status") != "recorded" or owner.get("owner_approval_required") is not True:
            return fail(f"owner approval packet id should be recorded but still required: {owner}")
        if ready.get("public_paid_launch_allowed") is not False or ready.get("charge_now_allowed") is not False:
            return fail("ready provider evidence still must not enable charging directly")
        serialized = json.dumps(ready, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "authorization: bearer", "refresh_token=", "access_token=", "client_secret="):
            if forbidden in serialized:
                return fail(f"evidence register leaked forbidden marker: {forbidden}")
        cli_output = OUT / "cli" / "billing-provider-evidence-register.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_billing_provider_evidence_register.py"),
                "--local-db",
                str(OUT / "cli-register.sqlite"),
                "--output",
                str(cli_output),
            ],
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            return fail(f"billing provider evidence register CLI failed: {completed.stderr[-300:] or completed.stdout[-300:]}")
        cli_payload = json.loads(cli_output.read_text(encoding="utf-8"))
        cli_register = cli_payload.get("billing_provider_evidence_register") if isinstance(cli_payload, dict) else {}
        if cli_register.get("contract_version") != "2026-07-02-live-billing-provider-evidence-register":
            return fail("billing provider evidence register CLI must emit the register contract")
        if cli_register.get("charge_now_allowed") is not False or cli_register.get("calls_stripe_api") is not False:
            return fail("billing provider evidence register CLI must remain no-charge and read-only")
        cli_serialized = json.dumps(cli_payload, ensure_ascii=False).lower()
        for forbidden in ("sk_live_unit_secret", "whsec_live_unit_secret", "authorization: bearer", "refresh_token=", "access_token=", "client_secret="):
            if forbidden in cli_serialized:
                return fail(f"evidence register CLI leaked forbidden marker: {forbidden}")

        os.environ.pop("JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID", None)
        missing_webhook = _build("missing-webhook-evidence.sqlite")
        missing_rows = {item.get("key"): item for item in missing_webhook.get("evidence_rows", []) if isinstance(item, dict)}
        if missing_rows["stripe_webhook_failure_paths"].get("status") != "blocked":
            return fail("missing webhook failure-path evidence id must block the register")
        print("PASS jiejing_billing_provider_evidence_register")
        return 0
    finally:
        _restore_env(previous)


def _build(name: str) -> dict[str, object]:
    db_path = OUT / name
    runtime_db_path = OUT / f"runtime-{name}"
    settings = SaaSSettings.from_env(db_path=db_path, runtime_db_path=runtime_db_path, output_root=OUT, host="127.0.0.1", port=8788)
    repo = SaaSRepository(db_path)
    repo.initialize()
    return build_billing_provider_evidence_register(settings, repo)


def _set_blocked_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "manual_seed",
            "JIEJING_PUBLIC_BASE_URL": "https://example.trycloudflare.com",
            "JIEJING_CORS_ORIGIN": "https://example.trycloudflare.com",
        }
    )
    return previous


def _set_ready_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _keys()}
    stable = "https://app.jiejing.example"
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_BILLING_PROVIDER": "stripe",
            "JIEJING_BILLING_PLANS_PUBLISHED": "1",
            "JIEJING_QUOTA_ENFORCEMENT_ENABLED": "1",
            "JIEJING_STRIPE_SECRET_KEY": "sk_live_unit_secret",
            "JIEJING_STRIPE_WEBHOOK_SECRET": "whsec_live_unit_secret",
            "JIEJING_BILLING_WEBHOOK_URL": f"{stable}/billing/webhook",
            "JIEJING_STRIPE_PRICE_STARTER_ID": "price_starter_live_unit",
            "JIEJING_STRIPE_PRICE_OPERATOR_ID": "price_operator_live_unit",
            "JIEJING_STRIPE_PRICE_TEAM_ID": "price_team_live_unit",
            "JIEJING_BILLING_SUCCESS_URL": f"{stable}/billing/success",
            "JIEJING_BILLING_CANCEL_URL": f"{stable}/billing/cancel",
            "JIEJING_BILLING_PORTAL_RETURN_URL": f"{stable}/settings/billing",
            "JIEJING_PUBLIC_BASE_URL": stable,
            "JIEJING_STABLE_DOMAIN": "app.jiejing.example",
            "JIEJING_CORS_ORIGIN": stable,
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED": "1",
            "JIEJING_STRIPE_LIVE_PRICES_VERIFIED": "1",
            "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG": "1",
            "JIEJING_STRIPE_ACCOUNT_ACTIVATED": "1",
            "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED": "1",
            "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID": "stripe_go_live_checklist_register_unit",
            "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED": "1",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED": "1",
            "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED": "1",
            "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID": "stripe_tax_invoice_receipt_register_unit",
            "JIEJING_STRIPE_WEBHOOK_API_VERSION": STRIPE_CURRENT_API_VERSION,
            "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED": "1",
            "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED": "1",
            "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID": "stripe_webhook_failure_path_register_unit",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED": "1",
            "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED": "1",
            "JIEJING_STRIPE_INVOICE_PAID_TESTED": "1",
            "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED": "1",
            "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID": "stripe_portal_failure_path_register_unit",
            "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED": "1",
            "JIEJING_CUTOVER_ROLLBACK_VERIFIED": "1",
            "JIEJING_SECRET_SCAN_PASSED": "1",
            "JIEJING_READINESS_SNAPSHOT_RECORDED": "1",
            "JIEJING_BROWSER_SMOKE_PASSED": "1",
            "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID": "rollback_audit_packet_register_unit",
            "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID": "owner_approval_register_unit",
        }
    )
    return previous


def _keys() -> list[str]:
    return [
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
        "JIEJING_PUBLIC_BASE_URL",
        "JIEJING_STABLE_DOMAIN",
        "JIEJING_CORS_ORIGIN",
        "JIEJING_DOMAIN_DNS_VERIFIED",
        "JIEJING_TLS_VERIFIED",
        "JIEJING_EBAY_CALLBACK_VERIFIED",
        "JIEJING_DEPLOYMENT_HARDENED",
        "JIEJING_SECURITY_HEADERS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRODUCTS_VERIFIED",
        "JIEJING_STRIPE_LIVE_PRICES_VERIFIED",
        "JIEJING_STRIPE_NO_TEST_OBJECTS_IN_LIVE_CONFIG",
        "JIEJING_STRIPE_ACCOUNT_ACTIVATED",
        "JIEJING_STRIPE_LIVE_MODE_DASHBOARD_REVIEWED",
        "JIEJING_STRIPE_GO_LIVE_CHECKLIST_EVIDENCE_ID",
        "JIEJING_STRIPE_TEST_MODE_OBJECTS_EXCLUDED",
        "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_REVIEWED",
        "JIEJING_STRIPE_SUPPORT_CONTACT_BRANDING_REVIEWED",
        "JIEJING_STRIPE_TAX_INVOICE_RECEIPT_EVIDENCE_ID",
        "JIEJING_STRIPE_WEBHOOK_API_VERSION",
        "JIEJING_STRIPE_WEBHOOK_API_VERSION_VERIFIED",
        "JIEJING_STRIPE_WEBHOOK_DUPLICATE_TESTED",
        "JIEJING_STRIPE_WEBHOOK_DELAYED_TESTED",
        "JIEJING_STRIPE_WEBHOOK_OUT_OF_ORDER_TESTED",
        "JIEJING_STRIPE_WEBHOOK_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_TESTED",
        "JIEJING_STRIPE_SUBSCRIPTION_CANCEL_TESTED",
        "JIEJING_STRIPE_INVOICE_PAID_TESTED",
        "JIEJING_STRIPE_PAYMENT_FAILURE_TESTED",
        "JIEJING_STRIPE_CUSTOMER_PORTAL_FAILURE_PATH_EVIDENCE_ID",
        "JIEJING_STRIPE_SUBSCRIPTION_STATE_PERSISTENCE_TESTED",
        "JIEJING_CUTOVER_ROLLBACK_VERIFIED",
        "JIEJING_SECRET_SCAN_PASSED",
        "JIEJING_READINESS_SNAPSHOT_RECORDED",
        "JIEJING_BROWSER_SMOKE_PASSED",
        "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID",
        "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
    ]


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
