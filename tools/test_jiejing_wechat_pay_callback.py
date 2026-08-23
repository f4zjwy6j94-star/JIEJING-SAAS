#!/usr/bin/env python3
"""Adversarial test for WeChat Pay callback verification and entitlement."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_wechat_pay import (  # noqa: E402
    build_wechat_pay_native_contract,
    process_wechat_pay_notification,
    reconcile_wechat_pay_order_query,
)
from jiejing_saas.billing_domestic import apply_verified_domestic_refund  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-wechat-pay-callback-test"
APP_ID = "wx-test-app-id"
MCH_ID = "1900000109"
SERIAL_NO = "TEST-PLATFORM-CERT-SERIAL"
API_V3_KEY = b"0123456789abcdef0123456789abcdef"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    settings = SaaSSettings.from_env(
        db_path=OUT / "saas.sqlite",
        runtime_db_path=OUT / "runtime.sqlite",
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(settings.db_path)
    account = repository.create_user_with_company(
        email="wechat-callback@example.test",
        password="Wechat-callback-test-2026",
        company_name="WeChat Callback Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])
    order_id = "domestic_callback_test_order"
    repository.create_domestic_billing_order_record(
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="a" * 64,
        order={"provider_mode": "signed_callback_test", "provider_order_created": True},
    )

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    public_key_pem_b64 = base64.b64encode(public_key_pem.encode("ascii")).decode("ascii")
    merchant_private_key_pem_b64 = base64.b64encode(b"backend-only-test-key-present").decode("ascii")

    with patch.dict(
        "os.environ",
        {
            "JIEJING_WECHAT_PAY_APP_ID": APP_ID,
            "JIEJING_WECHAT_PAY_MCH_ID": MCH_ID,
            "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO": "TEST-MERCHANT-SERIAL",
            "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": merchant_private_key_pem_b64,
            "JIEJING_WECHAT_PAY_API_V3_KEY": API_V3_KEY.decode("ascii"),
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": public_key_pem_b64,
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": SERIAL_NO,
            "JIEJING_WECHAT_PAY_NOTIFY_URL": "https://app.jiejing.shop/billing/domestic/wechat-pay/notify",
        },
        clear=True,
    ):
        contract = build_wechat_pay_native_contract()
    if contract.get("response_verification_mode") != "wechat_pay_public_key":
        return fail(f"new merchant contract should prefer WeChat Pay public-key mode: {contract}")
    configured = contract.get("configured") if isinstance(contract.get("configured"), dict) else {}
    if not configured.get("response_verification_key") or not configured.get("response_verification_key_id"):
        return fail(f"public-key verification material should be detected without exposure: {contract}")
    if configured.get("merchant_private_key") is not False:
        return fail(f"non-key merchant private material must fail closed: {contract}")
    if public_key_pem in json.dumps(contract, ensure_ascii=False):
        return fail("capability contract must not expose the WeChat Pay public key material")
    if public_key_pem_b64 in json.dumps(contract, ensure_ascii=False):
        return fail("capability contract must not expose Base64 payment material")

    with patch.dict(
        "os.environ",
        {
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": "not-valid-base64!",
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": SERIAL_NO,
        },
        clear=True,
    ):
        invalid_b64_contract = build_wechat_pay_native_contract()
    invalid_b64_configured = invalid_b64_contract.get("configured", {})
    if invalid_b64_configured.get("response_verification_key") is not False:
        return fail(f"invalid Base64 verification material must fail closed: {invalid_b64_contract}")

    tampered_body, tampered_headers = _notification(
        private_key=private_key,
        order_id=order_id,
        transaction_id="wx-transaction-wrong-amount",
        amount_minor=1,
    )
    invalid_material = process_wechat_pay_notification(
        repository,
        raw_body=tampered_body,
        headers=tampered_headers,
        api_v3_key=API_V3_KEY.decode("ascii"),
        platform_certificate_pem="-----BEGIN PUBLIC KEY-----\nnot-a-key\n-----END PUBLIC KEY-----",
        expected_serial_no=SERIAL_NO,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if invalid_material.get("reason") != "wechat_pay_configuration_incomplete":
        return fail(f"invalid callback verification PEM must fail before signature processing: {invalid_material}")
    tampered = process_wechat_pay_notification(
        repository,
        raw_body=tampered_body,
        headers=tampered_headers,
        api_v3_key=API_V3_KEY.decode("ascii"),
        platform_certificate_pem=public_key_pem,
        expected_serial_no=SERIAL_NO,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if tampered.get("ok") is not False or tampered.get("reason") != "payment_amount_mismatch":
        return fail(f"tampered amount must be blocked: {tampered}")
    if repository.get_billing_subscription(company_id=company_id):
        return fail("tampered callback must not activate entitlement")

    valid_body, valid_headers = _notification(
        private_key=private_key,
        order_id=order_id,
        transaction_id="wx-transaction-valid-1",
        amount_minor=9900,
    )
    invalid_signature_headers = dict(valid_headers)
    invalid_signature_headers["Wechatpay-Signature"] = base64.b64encode(b"not-a-valid-signature").decode("ascii")
    invalid_signature = process_wechat_pay_notification(
        repository,
        raw_body=valid_body,
        headers=invalid_signature_headers,
        api_v3_key=API_V3_KEY.decode("ascii"),
        platform_certificate_pem=public_key_pem,
        expected_serial_no=SERIAL_NO,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if invalid_signature.get("ok") is not False or invalid_signature.get("reason") != "wechat_pay_signature_invalid":
        return fail(f"forged signature must be blocked: {invalid_signature}")

    first = process_wechat_pay_notification(
        repository,
        raw_body=valid_body,
        headers=valid_headers,
        api_v3_key=API_V3_KEY.decode("ascii"),
        platform_certificate_pem=public_key_pem,
        expected_serial_no=SERIAL_NO,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    second = process_wechat_pay_notification(
        repository,
        raw_body=valid_body,
        headers=valid_headers,
        api_v3_key=API_V3_KEY.decode("ascii"),
        platform_certificate_pem=public_key_pem,
        expected_serial_no=SERIAL_NO,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if first.get("ok") is not True or first.get("status") != "payment_confirmed":
        return fail(f"valid signed callback should confirm payment: {first}")
    if second.get("ok") is not True or second.get("duplicate_notification") is not True:
        return fail(f"duplicate callback must be idempotent: {second}")
    subscription = repository.get_billing_subscription(company_id=company_id)
    if not subscription or subscription.get("entitlement_active") is not True or subscription.get("plan_key") != "starter":
        return fail(f"valid callback should activate the reviewed plan: {subscription}")
    media_account = repository.get_media_credit_account(company_id=company_id)
    if media_account.get("included_points") != 1000 or media_account.get("purchased_points") != 0:
        return fail(f"a paid starter order must grant exactly one included media-point bucket: {media_account}")
    first_active_until = str(subscription.get("subscription", {}).get("active_until") or "")
    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id)
    if not stored or stored.get("status") != "paid" or stored.get("provider_order_id") != "wx-transaction-valid-1":
        return fail(f"paid order state should be durable: {stored}")
    serialized = json.dumps({"first": first, "second": second, "stored": stored}, ensure_ascii=False).lower()
    if API_V3_KEY.decode("ascii").lower() in serialized or "wechatpay-signature" in serialized:
        return fail("callback response must not expose secret or raw signature material")

    query_order_id = "domestic_query_test_order"
    repository.create_domestic_billing_order_record(
        order_id=query_order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="b" * 64,
        order={"provider_mode": "authenticated_query_test", "provider_order_created": True},
    )
    query_response = {
        "appid": APP_ID,
        "mchid": MCH_ID,
        "out_trade_no": query_order_id,
        "transaction_id": "wx-query-transaction-valid-1",
        "trade_type": "NATIVE",
        "trade_state": "SUCCESS",
        "success_time": "2026-07-13T12:15:00+08:00",
        "amount": {"total": 9900, "payer_total": 9900, "currency": "CNY"},
    }
    unauthenticated_query = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=query_order_id,
        provider_response=query_response,
        query_authenticated=False,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if unauthenticated_query.get("reason") != "wechat_pay_query_not_authenticated":
        return fail(f"browser-supplied payment claims must be rejected: {unauthenticated_query}")
    query_response_wrong_amount = {**query_response, "amount": {"total": 1, "currency": "CNY"}}
    wrong_query = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=query_order_id,
        provider_response=query_response_wrong_amount,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if wrong_query.get("reason") != "payment_amount_mismatch":
        return fail(f"authenticated query must still verify amount: {wrong_query}")
    query_first = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=query_order_id,
        provider_response=query_response,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    query_second = reconcile_wechat_pay_order_query(
        repository,
        company_id=company_id,
        order_id=query_order_id,
        provider_response=query_response,
        query_authenticated=True,
        expected_appid=APP_ID,
        expected_mchid=MCH_ID,
    )
    if query_first.get("status") != "payment_confirmed" or query_first.get("verification_source") != "authenticated_order_query":
        return fail(f"authenticated query should recover a missed callback: {query_first}")
    if query_second.get("duplicate_notification") is not True:
        return fail(f"repeated order query reconciliation must be idempotent: {query_second}")
    renewed_subscription = repository.get_billing_subscription(company_id=company_id)
    renewed_active_until = str(renewed_subscription.get("subscription", {}).get("active_until") or "") if renewed_subscription else ""
    if not first_active_until or not renewed_active_until or renewed_active_until <= first_active_until:
        return fail(f"a second paid order must add time instead of replacing the remaining term: {renewed_subscription}")
    renewed_media_account = repository.get_media_credit_account(company_id=company_id)
    if renewed_media_account.get("included_points") != 2000:
        return fail(f"each paid starter renewal must grant one separate included point bucket: {renewed_media_account}")

    refund_latest = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=query_order_id,
        provider_refund_id="wx-refund-latest-renewal",
        amount_minor=9900,
        currency="CNY",
        provider_verified=True,
    )
    fallback_subscription = repository.get_billing_subscription(company_id=company_id)
    fallback_active_until = str(fallback_subscription.get("subscription", {}).get("active_until") or "") if fallback_subscription else ""
    if refund_latest.get("remaining_paid_entitlement_restored") is not True:
        return fail(f"refunding the latest renewal must restore the earlier paid term: {refund_latest}")
    if not fallback_subscription or fallback_subscription.get("entitlement_active") is not True or fallback_active_until != first_active_until:
        return fail(f"the earlier paid entitlement must remain active after latest-order refund: {fallback_subscription}")
    refunded_media_account = repository.get_media_credit_account(company_id=company_id)
    if refunded_media_account.get("included_points") != 1000:
        return fail(f"refunding the latest renewal must revoke only that order's unused included points: {refunded_media_account}")

    query_audits = [
        item
        for item in repository.list_audit_logs(company_id=company_id, limit=100)
        if item.get("action_type") == "billing.domestic_order.payment_verified"
        and item.get("target_id") == query_order_id
    ]
    if not query_audits or query_audits[0].get("details", {}).get("signature_verified") is not False:
        return fail(f"order-query recovery audit must not claim callback signature verification: {query_audits}")

    terminal_order_id = "domestic_terminal_state_order"
    repository.create_domestic_billing_order_record(
        order_id=terminal_order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="refunded",
        idempotency_key_hash="c" * 64,
        order={"provider_mode": "terminal_state_test", "provider_order_created": True},
    )
    try:
        repository.mark_domestic_billing_order_paid(
            company_id=company_id,
            order_id=terminal_order_id,
            provider_order_id="wx-transaction-too-late",
            paid_at="2026-07-13T04:00:00+00:00",
            payment={"signature_verified": True, "verification_source": "signed_callback"},
        )
    except ValueError:
        pass
    else:
        return fail("a late callback must not overwrite a terminal refunded order")
    terminal_order = repository.get_domestic_billing_order(company_id=company_id, order_id=terminal_order_id)
    if not terminal_order or terminal_order.get("status") != "refunded":
        return fail(f"terminal billing state must remain durable: {terminal_order}")

    print("PASS jiejing_wechat_pay_callback")
    return 0


def _notification(
    *,
    private_key: rsa.RSAPrivateKey,
    order_id: str,
    transaction_id: str,
    amount_minor: int,
) -> tuple[bytes, dict[str, str]]:
    transaction = {
        "appid": APP_ID,
        "mchid": MCH_ID,
        "out_trade_no": order_id,
        "transaction_id": transaction_id,
        "trade_type": "NATIVE",
        "trade_state": "SUCCESS",
        "success_time": "2026-07-13T12:00:00+08:00",
        "amount": {"total": amount_minor, "payer_total": amount_minor, "currency": "CNY"},
    }
    nonce = b"callback-nonce"
    associated_data = b"transaction"
    ciphertext = AESGCM(API_V3_KEY).encrypt(nonce, json.dumps(transaction, separators=(",", ":")).encode("utf-8"), associated_data)
    body = json.dumps(
        {
            "id": f"event-{transaction_id}",
            "create_time": "2026-07-13T12:00:01+08:00",
            "event_type": "TRANSACTION.SUCCESS",
            "resource_type": "encrypt-resource",
            "summary": "payment success",
            "resource": {
                "algorithm": "AEAD_AES_256_GCM",
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "associated_data": associated_data.decode("ascii"),
                "nonce": nonce.decode("ascii"),
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    signature_message = f"{timestamp}\ncallback-test-nonce\n".encode("ascii") + body + b"\n"
    signature = private_key.sign(signature_message, padding.PKCS1v15(), hashes.SHA256())
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": "callback-test-nonce",
        "Wechatpay-Serial": SERIAL_NO,
        "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
    }
    return body, headers


if __name__ == "__main__":
    raise SystemExit(main())
