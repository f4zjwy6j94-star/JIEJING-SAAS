#!/usr/bin/env python3
"""No-charge contract tests for the WeChat Pay APIv3 client.

The transport is fully injected. This test never reaches WeChat Pay and never
creates a payable order outside the local fake transport.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_wechat_pay import (  # noqa: E402
    WeChatPayTransportResponse,
    build_wechat_pay_native_contract,
    build_wechat_pay_api_authorization,
    close_wechat_pay_order,
    create_wechat_pay_native_order,
    query_wechat_pay_order,
)


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    merchant_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_private_pem = merchant_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    platform_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform_public_pem = platform_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    merchant_private_pem_b64 = base64.b64encode(merchant_private_pem.encode("utf-8")).decode("ascii")
    platform_public_pem_b64 = base64.b64encode(platform_public_pem.encode("utf-8")).decode("ascii")
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jiejing WeChat test")])
    platform_certificate_pem = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(platform_private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(platform_private_key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
        .decode("ascii")
    )

    contract_env = {
        "JIEJING_WECHAT_PAY_APP_ID": "wx-test-app",
        "JIEJING_WECHAT_PAY_MCH_ID": "1900000109",
        "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO": "merchant-serial-test",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": merchant_private_pem_b64,
        "JIEJING_WECHAT_PAY_API_V3_KEY": "a" * 32,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": platform_public_pem_b64,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": "PUB_KEY_ID_TEST",
        "JIEJING_WECHAT_PAY_NOTIFY_URL": "https://app.jiejing.shop/billing/domestic/wechat-pay/notify",
        "JIEJING_WECHAT_PAY_LIVE_API_ENABLED": "true",
        "JIEJING_WECHAT_PAY_CHARGE_ALLOWED": "true",
        "JIEJING_WECHAT_PAY_REFUND_ALLOWED": "true",
        "JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID": "owner-approved-payment-cutover-test",
    }
    with temporary_env(**contract_env, JIEJING_SAAS_ENV="staging"):
        staging_contract = build_wechat_pay_native_contract()
    if staging_contract.get("provider_connection_ready") is not True or staging_contract.get("charge_now_allowed") is not False:
        return fail(f"staging must prove provider connectivity without opening public charging: {staging_contract}")
    with temporary_env(**contract_env, JIEJING_SAAS_ENV="production"):
        production_contract = build_wechat_pay_native_contract()
    if (
        production_contract.get("real_checkout_ready") is not True
        or production_contract.get("charge_now_allowed") is not True
        or production_contract.get("refund_now_allowed") is not True
    ):
        return fail(f"public checkout requires production, complete credentials and recorded owner approval: {production_contract}")

    raw_contract_env = {
        **contract_env,
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64": "",
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM": merchant_private_pem,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": "",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM": platform_public_pem,
    }
    with temporary_env(**raw_contract_env, JIEJING_SAAS_ENV="production"):
        raw_contract = build_wechat_pay_native_contract()
    if raw_contract.get("provider_connection_ready") is not True:
        return fail(f"valid raw RSA PEM material must be accepted: {raw_contract}")

    invalid_nonempty_env = {
        **raw_contract_env,
        "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM": "not-a-valid-rsa-private-key",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM": "-----BEGIN PUBLIC KEY-----\nnot-a-key\n-----END PUBLIC KEY-----",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM": platform_certificate_pem,
        "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO": "PLATFORM-CERT-SERIAL",
    }
    with temporary_env(**invalid_nonempty_env, JIEJING_SAAS_ENV="production"):
        invalid_nonempty_contract = build_wechat_pay_native_contract()
    invalid_configured = invalid_nonempty_contract.get("configured", {})
    if (
        invalid_configured.get("merchant_private_key") is not False
        or invalid_configured.get("response_verification_key") is not False
        or invalid_nonempty_contract.get("response_verification_mode") != "wechat_pay_public_key"
    ):
        return fail(
            "invalid nonempty/partial public-key material must fail closed without certificate fallback: "
            f"{invalid_nonempty_contract}"
        )

    weak_private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    weak_private_pem = weak_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    weak_public_pem = weak_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    with temporary_env(
        **{
            **raw_contract_env,
            "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM": weak_private_pem,
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM": weak_public_pem,
        },
        JIEJING_SAAS_ENV="production",
    ):
        weak_contract = build_wechat_pay_native_contract()
    weak_configured = weak_contract.get("configured", {})
    if weak_configured.get("merchant_private_key") is not False or weak_configured.get("response_verification_key") is not False:
        return fail(f"RSA keys below 2048 bits must fail closed: {weak_contract}")

    certificate_env = {
        **raw_contract_env,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID": "",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM": "",
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": "",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM": platform_certificate_pem,
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64": "",
        "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO": "PLATFORM-CERT-SERIAL",
    }
    with temporary_env(**certificate_env, JIEJING_SAAS_ENV="production"):
        certificate_contract = build_wechat_pay_native_contract()
    if (
        certificate_contract.get("response_verification_mode") != "platform_certificate"
        or certificate_contract.get("configured", {}).get("response_verification_key") is not True
    ):
        return fail(f"valid raw x509 certificate fallback must remain supported: {certificate_contract}")
    invalid_public_key_b64_env = {
        **certificate_env,
        "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64": "not-valid-base64!",
    }
    with temporary_env(**invalid_public_key_b64_env, JIEJING_SAAS_ENV="production"):
        invalid_public_key_b64_contract = build_wechat_pay_native_contract()
    if (
        invalid_public_key_b64_contract.get("response_verification_mode") != "wechat_pay_public_key"
        or invalid_public_key_b64_contract.get("configured", {}).get("response_verification_key") is not False
    ):
        return fail(
            "invalid/partial public-key Base64 must not silently fall back to a platform certificate: "
            f"{invalid_public_key_b64_contract}"
        )
    certificate_b64_env = {
        **certificate_env,
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM": "",
        "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64": base64.b64encode(
            platform_certificate_pem.encode("ascii")
        ).decode("ascii"),
    }
    with temporary_env(**certificate_b64_env, JIEJING_SAAS_ENV="production"):
        certificate_b64_contract = build_wechat_pay_native_contract()
    if certificate_b64_contract.get("configured", {}).get("response_verification_key") is not True:
        return fail(f"valid Base64 x509 certificate fallback must remain supported: {certificate_b64_contract}")

    body = json.dumps({"appid": "wx-test-app", "mchid": "1900000109"}, separators=(",", ":"), ensure_ascii=False)
    authorization = build_wechat_pay_api_authorization(
        method="POST",
        path_and_query="/v3/pay/transactions/native",
        body=body,
        mchid="1900000109",
        merchant_serial_no="merchant-serial-test",
        merchant_private_key_pem=merchant_private_pem,
        timestamp=1710000000,
        nonce="nonce-fixed-for-test",
    )
    if not authorization.startswith("WECHATPAY2-SHA256-RSA2048 "):
        return fail(f"unexpected authorization scheme: {authorization}")
    signature_match = re.search(r'signature="([^"]+)"', authorization)
    if not signature_match:
        return fail("authorization signature is missing")
    signing_message = f"POST\n/v3/pay/transactions/native\n1710000000\nnonce-fixed-for-test\n{body}\n".encode("utf-8")
    merchant_private_key.public_key().verify(
        base64.b64decode(signature_match.group(1), validate=True),
        signing_message,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    calls: list[dict[str, Any]] = []

    def signed_transport(**request: Any) -> WeChatPayTransportResponse:
        calls.append(request)
        response_body = json.dumps({"code_url": "weixin://wxpay/bizpayurl?pr=test-token"}, separators=(",", ":")).encode("utf-8")
        timestamp = "1710000001"
        nonce = "response-nonce"
        signature = platform_private_key.sign(
            f"{timestamp}\n{nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=200,
            headers={
                "Wechatpay-Timestamp": timestamp,
                "Wechatpay-Nonce": nonce,
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    common = {
        "appid": "wx-test-app",
        "mchid": "1900000109",
        "merchant_serial_no": "merchant-serial-test",
        "merchant_private_key_pem": merchant_private_pem,
        "response_verification_key_pem": platform_public_pem,
        "response_verification_key_id": "PUB_KEY_ID_TEST",
        "notify_url": "https://app.jiejing.shop/billing/domestic/wechat-pay/notify",
        "transport": signed_transport,
        "timestamp": 1710000000,
        "nonce": "request-nonce-fixed",
    }
    disabled = create_wechat_pay_native_order(
        order={"order_id": "domestic_01234567890123456789012", "amount_minor": 9900, "currency": "CNY", "plan_key": "starter"},
        live_api_enabled=False,
        charge_allowed=False,
        **common,
    )
    if disabled.get("reason") != "wechat_pay_live_api_disabled" or calls:
        return fail(f"disabled client must not call external payment transport: {disabled}, calls={len(calls)}")

    not_approved = create_wechat_pay_native_order(
        order={"order_id": "domestic_01234567890123456789012", "amount_minor": 9900, "currency": "CNY", "plan_key": "starter"},
        live_api_enabled=True,
        charge_allowed=False,
        **common,
    )
    if not_approved.get("reason") != "wechat_pay_charge_not_approved" or calls:
        return fail(f"owner approval gate must block payable QR creation: {not_approved}, calls={len(calls)}")

    created = create_wechat_pay_native_order(
        order={
            "order_id": "domestic_01234567890123456789012",
            "amount_minor": 9900,
            "currency": "CNY",
            "plan_key": "starter",
            "expires_at": "2026-07-13T18:30:00+08:00",
        },
        live_api_enabled=True,
        charge_allowed=True,
        **common,
    )
    if created.get("ok") is not True or not str(created.get("code_url") or "").startswith("weixin://"):
        return fail(f"valid signed provider response should return a sanitized QR URL: {created}")
    if created.get("frontend_gets_payment_secret") is not False or created.get("secret_exposed") is not False:
        return fail(f"merchant response must preserve backend-only secret handling: {created}")
    if len(calls) != 1 or calls[0].get("url") != "https://api.mch.weixin.qq.com/v3/pay/transactions/native":
        return fail(f"client must pin the official WeChat Pay API host: {calls}")
    request_payload = json.loads(bytes(calls[0]["body"]).decode("utf-8"))
    expected_payload = {
        "appid": "wx-test-app",
        "mchid": "1900000109",
        "description": "捷境 starter 30天订阅",
        "out_trade_no": "domestic_01234567890123456789012",
        "notify_url": "https://app.jiejing.shop/billing/domestic/wechat-pay/notify",
        "amount": {"total": 9900, "currency": "CNY"},
        "time_expire": "2026-07-13T10:30:00+00:00",
    }
    if request_payload != expected_payload:
        return fail(f"native request must use server-owned order facts: {request_payload}")

    def bad_signature_transport(**request: Any) -> WeChatPayTransportResponse:
        calls.append(request)
        return WeChatPayTransportResponse(
            status_code=200,
            headers={
                "Wechatpay-Timestamp": "1710000001",
                "Wechatpay-Nonce": "response-nonce",
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(b"invalid").decode("ascii"),
            },
            body=b'{"code_url":"weixin://forged"}',
        )

    forged = create_wechat_pay_native_order(
        order={"order_id": "domestic_01234567890123456789012", "amount_minor": 9900, "currency": "CNY", "plan_key": "starter"},
        live_api_enabled=True,
        charge_allowed=True,
        **{**common, "transport": bad_signature_transport},
    )
    if forged.get("reason") != "wechat_pay_response_signature_invalid" or forged.get("code_url"):
        return fail(f"forged response must not produce a QR URL: {forged}")

    def stale_response_transport(**request: Any) -> WeChatPayTransportResponse:
        response_body = b'{"code_url":"weixin://stale-response"}'
        response_timestamp = "1709999000"
        response_nonce = "stale-response-nonce"
        signature = platform_private_key.sign(
            f"{response_timestamp}\n{response_nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=200,
            headers={
                "Wechatpay-Timestamp": response_timestamp,
                "Wechatpay-Nonce": response_nonce,
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    stale = create_wechat_pay_native_order(
        order={"order_id": "domestic_01234567890123456789012", "amount_minor": 9900, "currency": "CNY", "plan_key": "starter"},
        live_api_enabled=True,
        charge_allowed=True,
        **{**common, "transport": stale_response_transport},
    )
    if stale.get("reason") != "wechat_pay_response_timestamp_expired" or stale.get("code_url"):
        return fail(f"an old but correctly signed response must not be replayed: {stale}")

    def timeout_transport(**request: Any) -> WeChatPayTransportResponse:
        raise TimeoutError("sensitive-upstream-details-must-not-escape")

    timed_out = create_wechat_pay_native_order(
        order={"order_id": "domestic_01234567890123456789012", "amount_minor": 9900, "currency": "CNY", "plan_key": "starter"},
        live_api_enabled=True,
        charge_allowed=True,
        **{**common, "transport": timeout_transport},
    )
    serialized_timeout = json.dumps(timed_out, ensure_ascii=False, sort_keys=True)
    if timed_out.get("reason") != "wechat_pay_transport_unavailable" or "sensitive-upstream" in serialized_timeout:
        return fail(f"transport failures must be sanitized: {timed_out}")

    query_calls: list[dict[str, Any]] = []

    def query_transport(**request: Any) -> WeChatPayTransportResponse:
        query_calls.append(request)
        response_body = json.dumps({"out_trade_no": "domestic_query-01", "trade_state": "NOTPAY"}, separators=(",", ":")).encode("utf-8")
        timestamp = "1710000002"
        nonce = "query-response-nonce"
        signature = platform_private_key.sign(
            f"{timestamp}\n{nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=200,
            headers={
                "Wechatpay-Timestamp": timestamp,
                "Wechatpay-Nonce": nonce,
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    queried = query_wechat_pay_order(
        order_id="domestic_query-01",
        live_api_enabled=True,
        appid="wx-test-app",
        mchid="1900000109",
        merchant_serial_no="merchant-serial-test",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id="PUB_KEY_ID_TEST",
        transport=query_transport,
        timestamp=1710000000,
        nonce="query-request-nonce",
    )
    if queried.get("ok") is not True or queried.get("provider_response", {}).get("trade_state") != "NOTPAY":
        return fail(f"valid signed query response should be accepted: {queried}")
    expected_query_url = "https://api.mch.weixin.qq.com/v3/pay/transactions/out-trade-no/domestic_query-01?mchid=1900000109"
    if len(query_calls) != 1 or query_calls[0].get("url") != expected_query_url:
        return fail(f"query client must pin and encode the official endpoint: {query_calls}")

    close_calls: list[dict[str, Any]] = []

    def close_transport(**request: Any) -> WeChatPayTransportResponse:
        close_calls.append(request)
        response_body = b""
        response_timestamp = "1710000003"
        response_nonce = "close-response-nonce"
        signature = platform_private_key.sign(
            f"{response_timestamp}\n{response_nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=204,
            headers={
                "Wechatpay-Timestamp": response_timestamp,
                "Wechatpay-Nonce": response_nonce,
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    closed = close_wechat_pay_order(
        order_id="domestic_close-01",
        live_api_enabled=True,
        mchid="1900000109",
        merchant_serial_no="merchant-serial-test",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id="PUB_KEY_ID_TEST",
        transport=close_transport,
        timestamp=1710000000,
        nonce="close-request-nonce",
    )
    expected_close_url = "https://api.mch.weixin.qq.com/v3/pay/transactions/out-trade-no/domestic_close-01/close"
    if closed.get("ok") is not True or closed.get("status") != "provider_order_closed":
        return fail(f"a signed empty 204 close response must be accepted: {closed}")
    if len(close_calls) != 1 or close_calls[0].get("url") != expected_close_url:
        return fail(f"close client must pin and encode the official endpoint: {close_calls}")
    if json.loads(bytes(close_calls[0]["body"]).decode("utf-8")) != {"mchid": "1900000109"}:
        return fail(f"close request must use the configured merchant identity: {close_calls}")

    def forged_close_transport(**request: Any) -> WeChatPayTransportResponse:
        return WeChatPayTransportResponse(
            status_code=204,
            headers={
                "Wechatpay-Timestamp": "1710000003",
                "Wechatpay-Nonce": "forged-close-response",
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(b"invalid").decode("ascii"),
            },
            body=b"",
        )

    forged_close = close_wechat_pay_order(
        order_id="domestic_close-01",
        live_api_enabled=True,
        mchid="1900000109",
        merchant_serial_no="merchant-serial-test",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id="PUB_KEY_ID_TEST",
        transport=forged_close_transport,
        timestamp=1710000000,
        nonce="forged-close-request",
    )
    if forged_close.get("reason") != "wechat_pay_response_signature_invalid":
        return fail(f"an unsigned or forged empty close response must fail closed: {forged_close}")

    def missing_order_transport(**request: Any) -> WeChatPayTransportResponse:
        response_body = json.dumps(
            {"code": "ORDER_NOT_EXIST", "message": "order does not exist"},
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = "1710000002"
        nonce = "missing-order-response-nonce"
        signature = platform_private_key.sign(
            f"{timestamp}\n{nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=404,
            headers={
                "Wechatpay-Timestamp": timestamp,
                "Wechatpay-Nonce": nonce,
                "Wechatpay-Serial": "PUB_KEY_ID_TEST",
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    missing_order = query_wechat_pay_order(
        order_id="domestic_missing-01",
        live_api_enabled=True,
        appid="wx-test-app",
        mchid="1900000109",
        merchant_serial_no="merchant-serial-test",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id="PUB_KEY_ID_TEST",
        transport=missing_order_transport,
        timestamp=1710000000,
        nonce="missing-order-request-nonce",
    )
    if (
        missing_order.get("reason") != "wechat_pay_provider_rejected_request"
        or missing_order.get("provider_code") != "ORDER_NOT_EXIST"
        or missing_order.get("calls_external_payment_api") is not True
        or missing_order.get("provider_response_signature_verified") is not True
        or missing_order.get("triggers_real_charge") is not False
    ):
        return fail(f"signed provider rejection must retain truthful no-charge audit semantics: {missing_order}")

    with temporary_env(JIEJING_WECHAT_PAY_API_BASE_URL="https://evil.example.test"):
        invalid_host = query_wechat_pay_order(
            order_id="domestic_query-01",
            live_api_enabled=True,
            appid="wx-test-app",
            mchid="1900000109",
            merchant_serial_no="merchant-serial-test",
            merchant_private_key_pem=merchant_private_pem,
            response_verification_key_pem=platform_public_pem,
            response_verification_key_id="PUB_KEY_ID_TEST",
            transport=query_transport,
        )
    if invalid_host.get("reason") != "wechat_pay_api_host_not_allowed":
        return fail(f"non-WeChat API hosts must be rejected: {invalid_host}")

    print("PASS jiejing_wechat_pay_live_client")
    return 0


@contextmanager
def temporary_env(**values: str) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
