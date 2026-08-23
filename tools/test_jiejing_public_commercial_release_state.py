#!/usr/bin/env python3
"""Fail-closed contract for the owner-approved public commercial release."""

from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import readiness
from jiejing_saas import api_server
from jiejing_saas.billing_wechat_pay import (
    build_public_commercial_release_contract,
    build_wechat_pay_native_contract,
)


ENV_KEYS = {
    "JIEJING_SAAS_ENV",
    "JIEJING_WECHAT_PAY_APP_ID",
    "JIEJING_WECHAT_PAY_MCH_ID",
    "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
    "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
    "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
    "JIEJING_WECHAT_PAY_API_V3_KEY",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
    "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
    "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM",
    "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64",
    "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO",
    "JIEJING_WECHAT_PAY_NOTIFY_URL",
    "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
    "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
    "JIEJING_WECHAT_PAY_CHARGE_ALLOWED",
    "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
    "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID",
    "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID",
    "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED",
    "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED",
    "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED",
    "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED",
    "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED",
    "JIEJING_ENABLE_REAL_PLATFORM_WRITES",
    "JIEJING_EBAY_WRITE_LIVE",
}


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


@contextmanager
def _clean_environment():
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _configure_wechat_and_release() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "production",
            "JIEJING_WECHAT_PAY_APP_ID": "wx-release-contract",
            "JIEJING_WECHAT_PAY_MCH_ID": "1900000109",
            "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO": "SERIAL-RELEASE",
            "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": base64.b64encode(
                private_pem
            ).decode("ascii"),
            "JIEJING_WECHAT_PAY_API_V3_KEY": "0123456789abcdef0123456789abcdef",
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": base64.b64encode(public_pem).decode(
                "ascii"
            ),
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": "PUB_KEY_ID_RELEASE",
            "JIEJING_WECHAT_PAY_NOTIFY_URL": "https://app.jiejing.shop/billing/domestic/wechat-pay/notify",
            "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL": "https://app.jiejing.shop/billing/domestic/wechat-pay/refund-notify",
            "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "true",
            "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true",
            "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "true",
            "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID": "paid-owner-release-test",
            "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID": "production-owner-release-test",
            "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED": "true",
            "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED": "true",
            "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED": "true",
            "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED": "true",
            "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "false",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
            "JIEJING_EBAY_WRITE_LIVE": "false",
        }
    )


def _payment_summary() -> dict[str, object]:
    return {
        "merchant_status": "controlled_acceptance_proven",
        "domestic_payment_status": "controlled_acceptance_proven",
        "payment_path_status": "controlled_acceptance_proven_public_charging_closed",
        "mainland_payment_ready_for_owner_approval": True,
        "provider_configured": True,
        "configured_component_count": 9,
        "required_component_count": 9,
        "controlled_acceptance_proven": True,
        "verified_paid_order_count": 1,
        "next_paid_launch_blocker": "public_charging_owner_approval_required",
    }


def main() -> int:
    with _clean_environment():
        _configure_wechat_and_release()
        release = build_public_commercial_release_contract()
        if release.get("approved") is not True or release.get("blocked_by") != []:
            return fail(f"complete exact release contract must approve: {release}")
        wechat = build_wechat_pay_native_contract()
        if not all(
            wechat.get(key) is True
            for key in (
                "public_commercial_release_approved",
                "real_checkout_ready",
                "charge_now_allowed",
            )
        ):
            return fail(f"exact release must enable the backend checkout contract: {wechat}")
        serialized = json.dumps(wechat, ensure_ascii=False)
        for secret in (
            os.environ["JIEJING_WECHAT_PAY_API_V3_KEY"],
            os.environ["JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64"],
        ):
            if secret in serialized:
                return fail("payment contract must not expose credential material")

        original_plan = readiness.build_billing_plan
        original_validator = readiness._validated_public_mainland_payment
        try:
            readiness.build_billing_plan = lambda *_args, **_kwargs: {
                "billing_ready_for_private_beta": True,
                "mainland_payment_launch": {},
            }
            readiness._validated_public_mainland_payment = lambda _value: _payment_summary()
            item = readiness._billing_item(object(), object())
        finally:
            readiness.build_billing_plan = original_plan
            readiness._validated_public_mainland_payment = original_validator
        if item.status != "ready" or item.severity != "info":
            return fail(f"approved public commercial release must close billing warning: {item}")

        original_plan = readiness.build_billing_plan
        original_validator = readiness._validated_public_mainland_payment
        try:
            readiness.build_billing_plan = lambda *_args, **_kwargs: {
                "contract_version": "billing-plan-test-v1",
                "billing_ready_for_private_beta": True,
                "mainland_payment_launch": {},
                "quota_contract": {"enabled": True},
                "plan_catalog": [{"key": "starter"}],
            }
            readiness._validated_public_mainland_payment = lambda _value: _payment_summary()
            public_billing = readiness._public_billing_status(object(), object())
        finally:
            readiness.build_billing_plan = original_plan
            readiness._validated_public_mainland_payment = original_validator
        if not all(
            public_billing.get(key) is True
            for key in ("billing_ready_for_paid_launch", "public_charging_allowed", "charge_now_allowed")
        ):
            return fail(f"public readiness must reflect the exact active release: {public_billing}")
        if public_billing.get("paid_launch_blockers") != [] or public_billing.get("triggers_real_charge") is not False:
            return fail(f"public billing read model must be active without charging on GET: {public_billing}")
        safe_public_billing = api_server._public_safe_billing_summary(public_billing)
        if not all(
            safe_public_billing.get(key) is True
            for key in ("billing_ready_for_paid_launch", "public_charging_allowed", "charge_now_allowed")
        ):
            return fail(f"public billing sanitizer drifted from the exact release: {safe_public_billing}")
        original_api_validator = api_server.validate_mainland_payment_launch_for_public
        try:
            api_server.validate_mainland_payment_launch_for_public = lambda _value: _payment_summary()
            merchant_billing = api_server.SaaSBackendHandler._merchant_safe_billing_plan(
                {
                    "contract_version": "billing-plan-test-v1",
                    "billing_ready_for_private_beta": True,
                    "mainland_payment_launch": {},
                    "quota_contract": {"enabled": True, "metered_units": []},
                    "plan_catalog": [],
                    "add_on_catalog": [],
                }
            )
        finally:
            api_server.validate_mainland_payment_launch_for_public = original_api_validator
        if not all(
            merchant_billing.get(key) is True
            for key in ("billing_ready_for_paid_launch", "public_charging_allowed", "charge_now_allowed")
        ) or merchant_billing.get("provider", {}).get("available") is not True:
            return fail(f"merchant billing control room drifted from the exact release: {merchant_billing}")

        fail_closed_cases = {
            "JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID": "",
            "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED": "true",
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "true",
            "JIEJING_EBAY_WRITE_LIVE": "true",
            "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED": "false",
        }
        for key, unsafe_value in fail_closed_cases.items():
            previous = os.environ[key]
            os.environ[key] = unsafe_value
            try:
                blocked_release = build_public_commercial_release_contract()
                blocked_wechat = build_wechat_pay_native_contract()
                blocked_public = api_server._public_safe_billing_summary(public_billing)
            finally:
                os.environ[key] = previous
            if blocked_release.get("approved") is not False:
                return fail(f"unsafe release mutation must fail closed: {key}")
            if blocked_wechat.get("charge_now_allowed") is not False:
                return fail(f"unsafe release mutation must close real checkout: {key}")

            if blocked_public.get("public_charging_allowed") is not False:
                return fail(f"public billing read model must fail closed with the release: {key}")

    print("PASS jiejing_public_commercial_release_state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
