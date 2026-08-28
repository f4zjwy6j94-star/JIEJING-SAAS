#!/usr/bin/env python3
"""Adversarial contract tests for the review-gated WeChat Pay refund boundary."""

from __future__ import annotations

import base64
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    execute_approved_domestic_billing_refund,
    query_and_reconcile_domestic_billing_refund,
    request_domestic_billing_refund_review,
)
from jiejing_saas.billing_wechat_pay import (  # noqa: E402
    WeChatPayTransportResponse,
    build_wechat_pay_refund_id,
    process_wechat_pay_refund_notification,
    query_wechat_pay_refund,
    request_wechat_pay_refund,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-wechat-pay-refund-provider-test"
API_V3_KEY = "r" * 32
MCH_ID = "1900000109"
PLATFORM_KEY_ID = "PUB_KEY_ID_REFUND_TEST"
FIXED_EPOCH = 1710000000


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
        email="refund-provider-owner@example.test",
        password="Refund-provider-owner-2026",
        company_name="Refund Provider Test",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])
    order_id = "domestic_refund_provider_01"
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
        idempotency_key_hash="f" * 64,
        order={"provider_mode": "refund_provider_test"},
    )
    repository.mark_domestic_billing_order_paid(
        company_id=company_id,
        order_id=order_id,
        provider_order_id="wx-paid-refund-provider-test",
        paid_at="2026-07-14T01:00:00+00:00",
        payment={"signature_verified": True, "amount_verified": True},
    )
    repository.apply_billing_webhook_event(
        event={
            "provider": "wechat_pay_native",
            "event_id": "wx-paid-refund-provider-test",
            "event_type": "payment_succeeded",
            "supported_event": True,
            "company_id": company_id,
            "provider_customer_id": MCH_ID,
            "provider_subscription_id": order_id,
            "provider_plan_id": "wechat_native_starter_9900_30d",
            "plan_key": "starter",
            "subscription_status": "active",
        }
    )
    review = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        reason="订阅不再需要",
    )
    confirmation_id = str(review.get("confirmation_id") or "")
    repository.decide_confirmation(
        company_id=company_id,
        confirmation_id=confirmation_id,
        decision="approve",
        decided_by=user_id,
        note="同意按原支付金额全额退款",
    )

    merchant_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_private_pem = merchant_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform_public_pem = platform_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    provider_calls: list[dict[str, Any]] = []

    blocked_transport_called = False

    def blocked_transport(**_: Any) -> WeChatPayTransportResponse:
        nonlocal blocked_transport_called
        blocked_transport_called = True
        raise AssertionError("refund transport must stay untouched while the owner gate is closed")

    blocked = request_wechat_pay_refund(
        order=repository.get_domestic_billing_order(company_id=company_id, order_id=order_id) or {},
        reason="订阅不再需要",
        live_api_enabled=True,
        refund_allowed=False,
        mchid=MCH_ID,
        merchant_serial_no="merchant-refund-test",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id=PLATFORM_KEY_ID,
        notify_url="https://app.jiejing.shop/billing/domestic/wechat-pay/refund-notify",
        transport=blocked_transport,
        timestamp=FIXED_EPOCH,
    )
    if blocked.get("reason") != "wechat_pay_refund_not_approved" or blocked_transport_called:
        return fail(f"closed refund gate must block before any provider call: {blocked}")

    def provider_transport(**request: Any) -> WeChatPayTransportResponse:
        provider_calls.append(request)
        request_payload = json.loads(request["body"].decode("utf-8"))
        response = {
            "refund_id": "wx-refund-provider-processing",
            "out_refund_no": request_payload["out_refund_no"],
            "transaction_id": "wx-paid-refund-provider-test",
            "out_trade_no": request_payload["out_trade_no"],
            "status": "PROCESSING",
            "user_received_account": "must-not-leave-provider-boundary",
            "amount": {"refund": 9900, "total": 9900, "currency": "CNY"},
        }
        return _signed_response(platform_key, response, timestamp=FIXED_EPOCH)

    def approved_provider_refund(*, order: dict[str, Any], reason: str) -> dict[str, Any]:
        return request_wechat_pay_refund(
            order=order,
            reason=reason,
            live_api_enabled=True,
            refund_allowed=True,
            mchid=MCH_ID,
            merchant_serial_no="merchant-refund-test",
            merchant_private_key_pem=merchant_private_pem,
            response_verification_key_pem=platform_public_pem,
            response_verification_key_id=PLATFORM_KEY_ID,
            notify_url="https://app.jiejing.shop/billing/domestic/wechat-pay/refund-notify",
            transport=provider_transport,
            timestamp=FIXED_EPOCH,
            nonce="refund-request-nonce",
        )

    processing = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        provider_refund=approved_provider_refund,
    )
    if processing.get("status") != "refund_processing" or processing.get("triggers_real_refund") is not True:
        return fail(f"approved provider response should enter refund processing: {processing}")
    if len(provider_calls) != 1 or provider_calls[0].get("url") != "https://api.mch.weixin.qq.com/v3/refund/domestic/refunds":
        return fail(f"refund client must pin the official provider endpoint: {provider_calls}")
    request_payload = json.loads(provider_calls[0]["body"].decode("utf-8"))
    if request_payload.get("amount") != {"refund": 9900, "total": 9900, "currency": "CNY"}:
        return fail(f"only an exact full refund may leave the backend: {request_payload}")
    if request_payload.get("out_refund_no") != build_wechat_pay_refund_id(order_id):
        return fail(f"refund retries must use a deterministic idempotency key: {request_payload}")
    if "must-not-leave" in json.dumps(processing, ensure_ascii=False):
        return fail("provider payout-account fields must not cross the backend boundary")

    duplicate_processing = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_id,
        provider_refund=approved_provider_refund,
    )
    if (
        duplicate_processing.get("status") != "refund_processing"
        or duplicate_processing.get("duplicate_request") is not True
        or duplicate_processing.get("provider_query_required") is not True
        or duplicate_processing.get("calls_external_payment_api") is not False
        or duplicate_processing.get("triggers_real_refund") is not False
        or len(provider_calls) != 1
    ):
        return fail(f"a processing refund must be queried, never submitted to the provider twice: {duplicate_processing}, {provider_calls}")

    def query_transport(**request: Any) -> WeChatPayTransportResponse:
        response = {
            "refund_id": "wx-refund-provider-success",
            "out_refund_no": build_wechat_pay_refund_id(order_id),
            "transaction_id": "wx-paid-refund-provider-test",
            "out_trade_no": order_id,
            "status": "SUCCESS",
            "amount": {"refund": 9900, "total": 9900, "currency": "CNY"},
        }
        return _signed_response(platform_key, response, timestamp=FIXED_EPOCH)

    def authenticated_query(*, order_id: str) -> dict[str, Any]:
        return query_wechat_pay_refund(
            order_id=order_id,
            live_api_enabled=True,
            mchid=MCH_ID,
            merchant_serial_no="merchant-refund-test",
            merchant_private_key_pem=merchant_private_pem,
            response_verification_key_pem=platform_public_pem,
            response_verification_key_id=PLATFORM_KEY_ID,
            transport=query_transport,
            timestamp=FIXED_EPOCH,
            nonce="refund-query-nonce",
        )

    refunded = query_and_reconcile_domestic_billing_refund(
        repository,
        company_id=company_id,
        order_id=order_id,
        provider_query=authenticated_query,
    )
    stored = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id)
    subscription = repository.get_billing_subscription(company_id=company_id)
    if refunded.get("status") != "refunded" or not stored or stored.get("status") != "refunded":
        return fail(f"signed refund query should close the order: {refunded}, {stored}")
    if not subscription or subscription.get("entitlement_active") is not False:
        return fail(f"provider-confirmed refund should revoke only the matching entitlement: {subscription}")

    invalid_body, invalid_headers = _refund_notification(
        platform_key=platform_key,
        order_id=order_id,
        refund_amount=1,
    )
    invalid = process_wechat_pay_refund_notification(
        repository,
        raw_body=invalid_body,
        headers=invalid_headers,
        api_v3_key=API_V3_KEY,
        platform_certificate_pem=platform_public_pem,
        expected_serial_no=PLATFORM_KEY_ID,
        expected_mchid=MCH_ID,
    )
    if invalid.get("reason") != "refund_amount_mismatch":
        return fail(f"a signed callback with a changed amount must still be rejected: {invalid}")

    callback_body, callback_headers = _refund_notification(
        platform_key=platform_key,
        order_id=order_id,
        refund_amount=9900,
    )
    duplicate = process_wechat_pay_refund_notification(
        repository,
        raw_body=callback_body,
        headers=callback_headers,
        api_v3_key=API_V3_KEY,
        platform_certificate_pem=platform_public_pem,
        expected_serial_no=PLATFORM_KEY_ID,
        expected_mchid=MCH_ID,
    )
    if duplicate.get("status") != "refunded" or duplicate.get("duplicate_refund_result") is not True:
        return fail(f"repeated signed refund callbacks must be idempotent: {duplicate}")

    print("PASS jiejing_wechat_pay_refund_provider")
    return 0


def _signed_response(
    private_key: rsa.RSAPrivateKey,
    payload: dict[str, Any],
    *,
    timestamp: int,
) -> WeChatPayTransportResponse:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    nonce = "provider-refund-response-nonce"
    signature = private_key.sign(
        f"{timestamp}\n{nonce}\n".encode("utf-8") + body + b"\n",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return WeChatPayTransportResponse(
        status_code=200,
        headers={
            "Wechatpay-Timestamp": str(timestamp),
            "Wechatpay-Nonce": nonce,
            "Wechatpay-Serial": PLATFORM_KEY_ID,
            "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
        },
        body=body,
    )


def _refund_notification(
    *,
    platform_key: rsa.RSAPrivateKey,
    order_id: str,
    refund_amount: int,
) -> tuple[bytes, dict[str, str]]:
    resource_nonce = "refundnonce1"
    associated_data = "refund-notification"
    refund = {
        "mchid": MCH_ID,
        "out_trade_no": order_id,
        "transaction_id": "wx-paid-refund-provider-test",
        "out_refund_no": build_wechat_pay_refund_id(order_id),
        "refund_id": "wx-refund-provider-success",
        "refund_status": "SUCCESS",
        "amount": {"refund": refund_amount, "total": 9900, "currency": "CNY"},
    }
    ciphertext = AESGCM(API_V3_KEY.encode("ascii")).encrypt(
        resource_nonce.encode("ascii"),
        json.dumps(refund, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        associated_data.encode("ascii"),
    )
    envelope = {
        "id": "refund-notification-test",
        "create_time": "2026-07-14T09:00:00+08:00",
        "event_type": "REFUND.SUCCESS",
        "resource_type": "encrypt-resource",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "nonce": resource_nonce,
            "associated_data": associated_data,
        },
    }
    body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = int(time.time())
    nonce = "refund-callback-signature-nonce"
    signature = platform_key.sign(
        f"{timestamp}\n{nonce}\n".encode("utf-8") + body + b"\n",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return body, {
        "Wechatpay-Timestamp": str(timestamp),
        "Wechatpay-Nonce": nonce,
        "Wechatpay-Serial": PLATFORM_KEY_ID,
        "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
