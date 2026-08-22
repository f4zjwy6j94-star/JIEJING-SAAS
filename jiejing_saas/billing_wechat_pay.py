"""WeChat Pay Native signed callback boundary for Jiejing domestic billing."""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .repository import SaaSRepository


WECHAT_PAY_PROVIDER = "wechat_pay_native"
WECHAT_PAY_CALLBACK_TOLERANCE_SECONDS = 300
WECHAT_PAY_API_ORIGIN = "https://api.mch.weixin.qq.com"
WECHAT_PAY_API_TIMEOUT_SECONDS = 8
WECHAT_PAY_API_MAX_RESPONSE_BYTES = 1024 * 1024
WECHAT_PAY_ORDER_ID_PATTERN = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-|*"
WECHAT_PAY_REFUND_STATUSES = {"SUCCESS", "CLOSED", "PROCESSING", "ABNORMAL"}


def build_public_commercial_release_contract() -> dict[str, Any]:
    """Return the exact deploy-time approval state without exposing packet IDs.

    A paid-launch packet alone is deliberately insufficient. The production
    release packet, reviewed charge/write flags, reviewed customer-facing
    policy/copy, a non-candidate boot, and closed broad eBay publishing must all
    agree before the real checkout route can become available.
    """

    checks = {
        "paid_launch_owner_approval_recorded": bool(
            os.environ.get("JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID", "").strip()
        ),
        "production_release_owner_approval_recorded": bool(
            os.environ.get("JIEJING_PRODUCTION_RELEASE_OWNER_APPROVAL_PACKET_ID", "").strip()
        ),
        "public_charge_flag_reviewed": _env_true(
            "JIEJING_PRODUCTION_RELEASE_CHARGE_FLAG_REVIEWED"
        ),
        "real_write_flag_reviewed": _env_true(
            "JIEJING_PRODUCTION_RELEASE_REAL_WRITE_FLAG_REVIEWED"
        ),
        "support_refund_policy_reviewed": _env_true(
            "JIEJING_PRODUCTION_SUPPORT_REFUND_POLICY_REVIEWED"
        ),
        "merchant_surface_copy_scan_passed": _env_true(
            "JIEJING_PRODUCTION_MERCHANT_SURFACE_COPY_SCAN_PASSED"
        ),
        "production_environment": os.environ.get("JIEJING_SAAS_ENV", "").strip().lower()
        == "production",
        "production_candidate_boot_disabled": _env_false(
            "JIEJING_PRODUCTION_CANDIDATE_BOOT_ALLOWED"
        ),
        "wechat_charge_enabled": _env_true("JIEJING_WECHAT_PAY_CHARGE_ALLOWED"),
        "wechat_refund_enabled": _env_true("JIEJING_WECHAT_PAY_REFUND_ALLOWED"),
        "broad_platform_writes_disabled": _env_false(
            "JIEJING_ENABLE_REAL_PLATFORM_WRITES"
        ),
        "ebay_public_publish_disabled": _env_false("JIEJING_EBAY_WRITE_LIVE"),
    }
    approved = all(checks.values())
    return {
        "contract_version": "2026-08-22-public-commercial-release-v1",
        "approved": approved,
        "checks": checks,
        "blocked_by": [key for key, ready in checks.items() if not ready],
        "public_charging_allowed": approved,
        "broad_platform_writes_enabled": False,
        "ebay_public_publish_enabled": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


@dataclass(frozen=True)
class WeChatPayTransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


WeChatPayTransport = Callable[..., WeChatPayTransportResponse]


def build_wechat_pay_native_contract() -> dict[str, Any]:
    """Return capability booleans only; never return merchant credentials."""

    verification_key_pem, verification_key_id, verification_mode = _response_verification_material_from_env()
    configured = {
        "appid": bool(os.environ.get("JIEJING_WECHAT_PAY_APP_ID", "").strip()),
        "mchid": bool(os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", "").strip()),
        "merchant_serial": bool(os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", "").strip()),
        "merchant_private_key": _valid_rsa_private_key_pem(
            _pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM")
        ),
        "api_v3_key": len(os.environ.get("JIEJING_WECHAT_PAY_API_V3_KEY", "").encode("utf-8")) == 32,
        "response_verification_key": _valid_rsa_verification_material_pem(verification_key_pem),
        "response_verification_key_id": bool(verification_key_id.strip()),
        "notify_url": _https_url_configured(os.environ.get("JIEJING_WECHAT_PAY_NOTIFY_URL", "")),
        "refund_notify_url": _https_url_configured(_refund_notify_url_from_env()),
    }
    live_api_enabled = _env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED")
    charge_allowed = _env_true("JIEJING_WECHAT_PAY_CHARGE_ALLOWED")
    refund_allowed = _env_true("JIEJING_WECHAT_PAY_REFUND_ALLOWED")
    production_environment = os.environ.get("JIEJING_SAAS_ENV", "").strip().lower() == "production"
    owner_approval_recorded = bool(os.environ.get("JIEJING_PAID_LAUNCH_OWNER_APPROVAL_PACKET_ID", "").strip())
    commercial_release = build_public_commercial_release_contract()
    public_checkout_allowed = (
        all(configured.values())
        and live_api_enabled
        and charge_allowed
        and refund_allowed
        and production_environment
        and owner_approval_recorded
        and commercial_release.get("approved") is True
    )
    blockers = [f"{key}_not_configured" for key, ready in configured.items() if not ready]
    if not live_api_enabled:
        blockers.append("wechat_pay_live_api_disabled")
    if not charge_allowed:
        blockers.append("owner_paid_launch_approval_missing")
    if not refund_allowed:
        blockers.append("wechat_pay_refund_not_approved")
    if not owner_approval_recorded:
        blockers.append("paid_launch_owner_approval_packet_missing")
    blockers.extend(
        f"commercial_release_{key}_missing"
        for key in commercial_release.get("blocked_by", [])
        if key != "paid_launch_owner_approval_recorded"
    )
    if not production_environment:
        blockers.append("public_checkout_requires_production_environment")
    return {
        "contract_version": "2026-07-14-wechat-pay-native-v3",
        "provider": WECHAT_PAY_PROVIDER,
        "checkout_mode": "native_qr",
        "response_verification_mode": verification_mode,
        "billing_mode": "one_time_30_day_plan",
        "merchant_onboarding_required": True,
        "merchant_credentials_backend_only": True,
        "rehearsal_order_supported": True,
        "signed_callback_implemented": True,
        "signed_refund_callback_implemented": True,
        "refund_execution_confirmation_required": True,
        "full_refund_only": True,
        "callback_amount_match_required": True,
        "callback_idempotency_required": True,
        "real_order_creation_implemented": True,
        "provider_connection_ready": all(configured.values()) and live_api_enabled,
        "owner_approval_recorded": owner_approval_recorded,
        "public_commercial_release_approved": commercial_release.get("approved") is True,
        "commercial_release_contract_version": commercial_release.get("contract_version"),
        "production_environment": production_environment,
        "real_checkout_ready": public_checkout_allowed,
        "charge_now_allowed": public_checkout_allowed,
        "refund_now_allowed": all(configured.values()) and live_api_enabled and refund_allowed,
        "configured": configured,
        "blockers": blockers,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def build_wechat_pay_api_authorization(
    *,
    method: str,
    path_and_query: str,
    body: str,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> str:
    """Build one APIv3 request authorization header without exposing key material."""

    normalized_method = str(method or "").strip().upper()
    normalized_path = str(path_and_query or "").strip()
    normalized_mchid = str(mchid or "").strip()
    normalized_serial = str(merchant_serial_no or "").strip()
    if normalized_method not in {"GET", "POST"} or not normalized_path.startswith("/"):
        raise ValueError("wechat pay request target is invalid")
    if not normalized_mchid or not normalized_serial:
        raise ValueError("wechat pay merchant identity is incomplete")
    request_timestamp = int(time.time()) if timestamp is None else int(timestamp)
    request_nonce = str(nonce or secrets.token_hex(16)).strip()
    if not request_nonce or len(request_nonce) > 64:
        raise ValueError("wechat pay request nonce is invalid")
    if not _valid_rsa_private_key_pem(merchant_private_key_pem):
        raise ValueError("wechat pay merchant private key is invalid")
    private_key = serialization.load_pem_private_key(str(merchant_private_key_pem or "").encode("utf-8"), password=None)
    message = f"{normalized_method}\n{normalized_path}\n{request_timestamp}\n{request_nonce}\n{str(body or '')}\n".encode("utf-8")
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = base64.b64encode(signature).decode("ascii")
    return (
        "WECHATPAY2-SHA256-RSA2048 "
        f'mchid="{normalized_mchid}",nonce_str="{request_nonce}",timestamp="{request_timestamp}",'
        f'serial_no="{normalized_serial}",signature="{encoded_signature}"'
    )


def create_wechat_pay_native_order_from_env(
    *,
    order: Mapping[str, Any],
    transport: WeChatPayTransport | None = None,
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _mode = _response_verification_material_from_env()
    return create_wechat_pay_native_order(
        order=order,
        live_api_enabled=_env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED"),
        charge_allowed=_env_true("JIEJING_WECHAT_PAY_CHARGE_ALLOWED"),
        appid=os.environ.get("JIEJING_WECHAT_PAY_APP_ID", ""),
        mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        merchant_serial_no=os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", ""),
        merchant_private_key_pem=_pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM"),
        response_verification_key_pem=verification_key_pem,
        response_verification_key_id=verification_key_id,
        notify_url=os.environ.get("JIEJING_WECHAT_PAY_NOTIFY_URL", ""),
        transport=transport,
    )


def create_wechat_pay_native_order(
    *,
    order: Mapping[str, Any],
    live_api_enabled: bool,
    charge_allowed: bool,
    appid: str,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    notify_url: str,
    transport: WeChatPayTransport | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Create one payable Native order only after both backend gates are open."""

    if live_api_enabled is not True:
        return _blocked("wechat_pay_live_api_disabled", http_status=409)
    if charge_allowed is not True:
        return _blocked("wechat_pay_charge_not_approved", http_status=409)
    configuration_blockers = _live_api_configuration_blockers(
        appid=appid,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
    )
    if configuration_blockers:
        return _blocked("wechat_pay_configuration_incomplete", http_status=503, blocked_by=configuration_blockers)
    normalized_notify_url = str(notify_url or "").strip()
    if not _https_url_configured(normalized_notify_url):
        return _blocked("wechat_pay_notify_url_invalid", http_status=503)
    order_id = str(order.get("order_id") or "").strip()
    if not _valid_wechat_order_id(order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    try:
        amount_minor = int(order.get("amount_minor"))
    except (TypeError, ValueError):
        return _blocked("payment_amount_invalid", http_status=400)
    currency = str(order.get("currency") or "").strip().upper()
    if amount_minor <= 0 or currency != "CNY":
        return _blocked("payment_amount_invalid", http_status=400)
    plan_key = str(order.get("plan_key") or "subscription").strip()[:32] or "subscription"
    order_payload = order.get("order") if isinstance(order.get("order"), Mapping) else {}
    description = str(order_payload.get("display_name") or f"捷境 {plan_key} 30天订阅").strip()[:127]
    payload = {
        "appid": str(appid).strip(),
        "mchid": str(mchid).strip(),
        "description": description,
        "out_trade_no": order_id,
        "notify_url": normalized_notify_url,
        "amount": {"total": amount_minor, "currency": currency},
    }
    time_expire = _normalized_time_expire(order.get("expires_at"))
    if time_expire:
        payload["time_expire"] = time_expire
    result = _perform_signed_json_request(
        method="POST",
        path_and_query="/v3/pay/transactions/native",
        payload=payload,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        transport=transport,
        timestamp=timestamp,
        nonce=nonce,
    )
    if result.get("ok") is not True:
        return result
    provider_response = result.get("provider_response") if isinstance(result.get("provider_response"), dict) else {}
    code_url = str(provider_response.get("code_url") or "").strip()
    if not code_url.startswith("weixin://") or len(code_url) > 2048:
        return {**_blocked("wechat_pay_native_code_url_invalid", http_status=502), "calls_external_payment_api": True}
    return {
        "ok": True,
        "status": "payable_order_created",
        "provider": WECHAT_PAY_PROVIDER,
        "order_id": order_id,
        "code_url": code_url,
        "amount_minor": amount_minor,
        "currency": currency,
        "calls_external_payment_api": True,
        "creates_payable_order": True,
        "triggers_real_charge": False,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def query_wechat_pay_order_from_env(
    *,
    order_id: str,
    transport: WeChatPayTransport | None = None,
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _mode = _response_verification_material_from_env()
    return query_wechat_pay_order(
        order_id=order_id,
        live_api_enabled=_env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED"),
        appid=os.environ.get("JIEJING_WECHAT_PAY_APP_ID", ""),
        mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        merchant_serial_no=os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", ""),
        merchant_private_key_pem=_pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM"),
        response_verification_key_pem=verification_key_pem,
        response_verification_key_id=verification_key_id,
        transport=transport,
    )


def query_wechat_pay_order(
    *,
    order_id: str,
    live_api_enabled: bool,
    appid: str,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    transport: WeChatPayTransport | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Query one provider order through a signed, response-verified API call."""

    if live_api_enabled is not True:
        return _blocked("wechat_pay_live_api_disabled", http_status=409)
    configuration_blockers = _live_api_configuration_blockers(
        appid=appid,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
    )
    if configuration_blockers:
        return _blocked("wechat_pay_configuration_incomplete", http_status=503, blocked_by=configuration_blockers)
    normalized_order_id = str(order_id or "").strip()
    if not _valid_wechat_order_id(normalized_order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    encoded_order_id = urllib.parse.quote(normalized_order_id, safe="")
    encoded_mchid = urllib.parse.quote(str(mchid).strip(), safe="")
    path_and_query = f"/v3/pay/transactions/out-trade-no/{encoded_order_id}?mchid={encoded_mchid}"
    return _perform_signed_json_request(
        method="GET",
        path_and_query=path_and_query,
        payload=None,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        transport=transport,
        timestamp=timestamp,
        nonce=nonce,
    )


def close_wechat_pay_order_from_env(
    *,
    order_id: str,
    transport: WeChatPayTransport | None = None,
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _mode = _response_verification_material_from_env()
    return close_wechat_pay_order(
        order_id=order_id,
        live_api_enabled=_env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED"),
        mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        merchant_serial_no=os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", ""),
        merchant_private_key_pem=_pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM"),
        response_verification_key_pem=verification_key_pem,
        response_verification_key_id=verification_key_id,
        transport=transport,
    )


def close_wechat_pay_order(
    *,
    order_id: str,
    live_api_enabled: bool,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    transport: WeChatPayTransport | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Close one unpaid Native order using the signed WeChat Pay APIv3 route."""

    if live_api_enabled is not True:
        return _blocked("wechat_pay_live_api_disabled", http_status=409)
    configuration_blockers = _live_api_configuration_blockers(
        appid="",
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        require_appid=False,
    )
    if configuration_blockers:
        return _blocked("wechat_pay_configuration_incomplete", http_status=503, blocked_by=configuration_blockers)
    normalized_order_id = str(order_id or "").strip()
    if not _valid_wechat_order_id(normalized_order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    normalized_mchid = str(mchid or "").strip()
    encoded_order_id = urllib.parse.quote(normalized_order_id, safe="")
    result = _perform_signed_json_request(
        method="POST",
        path_and_query=f"/v3/pay/transactions/out-trade-no/{encoded_order_id}/close",
        payload={"mchid": normalized_mchid},
        mchid=normalized_mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        transport=transport,
        timestamp=timestamp,
        nonce=nonce,
        allow_empty_success=True,
    )
    if result.get("ok") is not True:
        return result
    return {
        "ok": True,
        "status": "provider_order_closed",
        "provider": WECHAT_PAY_PROVIDER,
        "order_id": normalized_order_id,
        "provider_response_signature_verified": True,
        "calls_external_payment_api": True,
        "triggers_real_charge": False,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def build_wechat_pay_refund_id(order_id: str) -> str:
    """Build a stable provider idempotency key without exposing tenant identity."""

    normalized_order_id = str(order_id or "").strip()
    if not _valid_wechat_order_id(normalized_order_id):
        raise ValueError("wechat pay order id is invalid")
    digest = hashes.Hash(hashes.SHA256())
    digest.update(f"jiejing-wechat-refund-v1:{normalized_order_id}".encode("utf-8"))
    return f"JJR{digest.finalize().hex()[:29]}"


def request_wechat_pay_refund_from_env(
    *,
    order: Mapping[str, Any],
    reason: str,
    transport: WeChatPayTransport | None = None,
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _mode = _response_verification_material_from_env()
    return request_wechat_pay_refund(
        order=order,
        reason=reason,
        live_api_enabled=_env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED"),
        refund_allowed=_env_true("JIEJING_WECHAT_PAY_REFUND_ALLOWED"),
        mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        merchant_serial_no=os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", ""),
        merchant_private_key_pem=_pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM"),
        response_verification_key_pem=verification_key_pem,
        response_verification_key_id=verification_key_id,
        notify_url=_refund_notify_url_from_env(),
        transport=transport,
    )


def request_wechat_pay_refund(
    *,
    order: Mapping[str, Any],
    reason: str,
    live_api_enabled: bool,
    refund_allowed: bool,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    notify_url: str,
    transport: WeChatPayTransport | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Request one approved full refund through the signed WeChat Pay API."""

    if live_api_enabled is not True:
        return _blocked("wechat_pay_live_api_disabled", http_status=409)
    if refund_allowed is not True:
        return _blocked("wechat_pay_refund_not_approved", http_status=409)
    configuration_blockers = _live_api_configuration_blockers(
        appid="",
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        require_appid=False,
    )
    if configuration_blockers:
        return _blocked("wechat_pay_configuration_incomplete", http_status=503, blocked_by=configuration_blockers)
    normalized_notify_url = str(notify_url or "").strip()
    if not _https_url_configured(normalized_notify_url):
        return _blocked("wechat_pay_refund_notify_url_invalid", http_status=503)
    order_id = str(order.get("order_id") or "").strip()
    if not _valid_wechat_order_id(order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    try:
        amount_minor = int(order.get("amount_minor"))
    except (TypeError, ValueError):
        return _blocked("refund_amount_invalid", http_status=400)
    currency = str(order.get("currency") or "").strip().upper()
    if amount_minor <= 0 or currency != "CNY":
        return _blocked("refund_amount_invalid", http_status=400)
    out_refund_no = build_wechat_pay_refund_id(order_id)
    payload = {
        "out_trade_no": order_id,
        "out_refund_no": out_refund_no,
        "reason": (" ".join(str(reason or "").split()) or "商家订阅退款")[:80],
        "notify_url": normalized_notify_url,
        "amount": {"refund": amount_minor, "total": amount_minor, "currency": currency},
    }
    result = _perform_signed_json_request(
        method="POST",
        path_and_query="/v3/refund/domestic/refunds",
        payload=payload,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        transport=transport,
        timestamp=timestamp,
        nonce=nonce,
    )
    if result.get("ok") is not True:
        return result
    provider_response = _sanitize_refund_response(result.get("provider_response"))
    if provider_response.get("out_trade_no") != order_id or provider_response.get("out_refund_no") != out_refund_no:
        return {**_blocked("wechat_pay_refund_order_mismatch", http_status=502), "calls_external_payment_api": True}
    if provider_response.get("status") not in WECHAT_PAY_REFUND_STATUSES:
        return {**_blocked("wechat_pay_refund_response_invalid", http_status=502), "calls_external_payment_api": True}
    return {
        "ok": True,
        "status": "provider_refund_response_verified",
        "provider": WECHAT_PAY_PROVIDER,
        "order_id": order_id,
        "out_refund_no": out_refund_no,
        "provider_response": provider_response,
        "query_authenticated": True,
        "calls_external_payment_api": True,
        "triggers_real_refund": True,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def query_wechat_pay_refund_from_env(
    *,
    order_id: str,
    transport: WeChatPayTransport | None = None,
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _mode = _response_verification_material_from_env()
    return query_wechat_pay_refund(
        order_id=order_id,
        live_api_enabled=_env_true("JIEJING_WECHAT_PAY_LIVE_API_ENABLED"),
        mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        merchant_serial_no=os.environ.get("JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO", ""),
        merchant_private_key_pem=_pem_from_env("JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM"),
        response_verification_key_pem=verification_key_pem,
        response_verification_key_id=verification_key_id,
        transport=transport,
    )


def query_wechat_pay_refund(
    *,
    order_id: str,
    live_api_enabled: bool,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    transport: WeChatPayTransport | None = None,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Query an existing refund; this never initiates money movement."""

    if live_api_enabled is not True:
        return _blocked("wechat_pay_live_api_disabled", http_status=409)
    configuration_blockers = _live_api_configuration_blockers(
        appid="",
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        require_appid=False,
    )
    if configuration_blockers:
        return _blocked("wechat_pay_configuration_incomplete", http_status=503, blocked_by=configuration_blockers)
    normalized_order_id = str(order_id or "").strip()
    if not _valid_wechat_order_id(normalized_order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    out_refund_no = build_wechat_pay_refund_id(normalized_order_id)
    encoded_refund_id = urllib.parse.quote(out_refund_no, safe="")
    result = _perform_signed_json_request(
        method="GET",
        path_and_query=f"/v3/refund/domestic/refunds/{encoded_refund_id}",
        payload=None,
        mchid=mchid,
        merchant_serial_no=merchant_serial_no,
        merchant_private_key_pem=merchant_private_key_pem,
        response_verification_key_pem=response_verification_key_pem,
        response_verification_key_id=response_verification_key_id,
        transport=transport,
        timestamp=timestamp,
        nonce=nonce,
    )
    if result.get("ok") is not True:
        return result
    provider_response = _sanitize_refund_response(result.get("provider_response"))
    if provider_response.get("out_trade_no") != normalized_order_id or provider_response.get("out_refund_no") != out_refund_no:
        return {**_blocked("wechat_pay_refund_order_mismatch", http_status=502), "calls_external_payment_api": True}
    if provider_response.get("status") not in WECHAT_PAY_REFUND_STATUSES:
        return {**_blocked("wechat_pay_refund_response_invalid", http_status=502), "calls_external_payment_api": True}
    return {
        "ok": True,
        "status": "provider_refund_query_verified",
        "provider": WECHAT_PAY_PROVIDER,
        "order_id": normalized_order_id,
        "out_refund_no": out_refund_no,
        "provider_response": provider_response,
        "query_authenticated": True,
        "calls_external_payment_api": True,
        "triggers_real_refund": False,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _perform_signed_json_request(
    *,
    method: str,
    path_and_query: str,
    payload: Mapping[str, Any] | None,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    transport: WeChatPayTransport | None,
    timestamp: int | None,
    nonce: str | None,
    allow_empty_success: bool = False,
) -> dict[str, Any]:
    origin = os.environ.get("JIEJING_WECHAT_PAY_API_BASE_URL", WECHAT_PAY_API_ORIGIN).strip().rstrip("/")
    if origin != WECHAT_PAY_API_ORIGIN:
        return _blocked("wechat_pay_api_host_not_allowed", http_status=503)
    body_text = "" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    request_timestamp = int(time.time()) if timestamp is None else int(timestamp)
    try:
        authorization = build_wechat_pay_api_authorization(
            method=method,
            path_and_query=path_and_query,
            body=body_text,
            mchid=mchid,
            merchant_serial_no=merchant_serial_no,
            merchant_private_key_pem=merchant_private_key_pem,
            timestamp=request_timestamp,
            nonce=nonce,
        )
    except (TypeError, ValueError):
        return _blocked("wechat_pay_request_signing_failed", http_status=503)
    request_body = body_text.encode("utf-8")
    request_headers = {
        "Accept": "application/json",
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Jiejing-WeChatPay/1.0",
    }
    try:
        response = (transport or _default_wechat_pay_transport)(
            method=method,
            url=f"{origin}{path_and_query}",
            headers=request_headers,
            body=request_body,
            timeout_seconds=WECHAT_PAY_API_TIMEOUT_SECONDS,
        )
    except Exception:
        return {**_blocked("wechat_pay_transport_unavailable", http_status=503), "calls_external_payment_api": True}
    if not isinstance(response, WeChatPayTransportResponse) or not isinstance(response.body, bytes):
        return {**_blocked("wechat_pay_transport_response_invalid", http_status=502), "calls_external_payment_api": True}
    if len(response.body) > WECHAT_PAY_API_MAX_RESPONSE_BYTES:
        return {**_blocked("wechat_pay_response_too_large", http_status=502), "calls_external_payment_api": True}
    signature_result = _verify_wechat_pay_response_signature(
        raw_body=response.body,
        headers=response.headers,
        verification_key_pem=response_verification_key_pem,
        expected_key_id=response_verification_key_id,
        now_epoch=request_timestamp,
    )
    if signature_result is not None:
        return {**signature_result, "calls_external_payment_api": True}
    if allow_empty_success and 200 <= int(response.status_code) < 300 and not response.body:
        return {
            "ok": True,
            "status": "provider_response_verified",
            "provider_response": {},
            "query_authenticated": True,
            "calls_external_payment_api": True,
            "raw_payload_persisted": False,
            "raw_signature_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    try:
        provider_response = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {**_blocked("wechat_pay_response_invalid", http_status=502), "calls_external_payment_api": True}
    if not isinstance(provider_response, dict):
        return {**_blocked("wechat_pay_response_invalid", http_status=502), "calls_external_payment_api": True}
    if not 200 <= int(response.status_code) < 300:
        return {
            **_blocked("wechat_pay_provider_rejected_request", http_status=502),
            "provider_code": str(provider_response.get("code") or "unknown")[:128],
            "calls_external_payment_api": True,
            "provider_response_signature_verified": True,
        }
    return {
        "ok": True,
        "status": "provider_response_verified",
        "provider_response": provider_response,
        "query_authenticated": True,
        "calls_external_payment_api": True,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _verify_wechat_pay_response_signature(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    verification_key_pem: str,
    expected_key_id: str,
    now_epoch: int,
) -> dict[str, Any] | None:
    normalized_headers = {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}
    timestamp = normalized_headers.get("wechatpay-timestamp", "")
    nonce = normalized_headers.get("wechatpay-nonce", "")
    serial = normalized_headers.get("wechatpay-serial", "")
    signature_text = normalized_headers.get("wechatpay-signature", "")
    if not timestamp.isdigit() or not nonce or len(nonce) > 128:
        return _blocked("wechat_pay_response_signature_header_invalid", http_status=502)
    if abs(int(timestamp) - int(now_epoch)) > WECHAT_PAY_CALLBACK_TOLERANCE_SECONDS:
        return _blocked("wechat_pay_response_timestamp_expired", http_status=502)
    if not hmac.compare_digest(serial, str(expected_key_id or "").strip()):
        return _blocked("wechat_pay_response_signature_header_invalid", http_status=502)
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = _load_platform_public_key(verification_key_pem)
        message = f"{timestamp}\n{nonce}\n".encode("utf-8") + raw_body + b"\n"
        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return _blocked("wechat_pay_response_signature_invalid", http_status=502)
    return None


def _default_wechat_pay_transport(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: int,
) -> WeChatPayTransportResponse:
    request = urllib.request.Request(
        url=url,
        data=body if method == "POST" else None,
        headers=dict(headers),
        method=method,
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            response_body = response.read(WECHAT_PAY_API_MAX_RESPONSE_BYTES + 1)
            return WeChatPayTransportResponse(
                status_code=int(response.status),
                headers=dict(response.headers.items()),
                body=response_body,
            )
    except urllib.error.HTTPError as exc:
        return WeChatPayTransportResponse(
            status_code=int(exc.code),
            headers=dict(exc.headers.items()) if exc.headers else {},
            body=exc.read(WECHAT_PAY_API_MAX_RESPONSE_BYTES + 1),
        )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _live_api_configuration_blockers(
    *,
    appid: str,
    mchid: str,
    merchant_serial_no: str,
    merchant_private_key_pem: str,
    response_verification_key_pem: str,
    response_verification_key_id: str,
    require_appid: bool = True,
) -> list[str]:
    checks = {
        "mchid_not_configured": bool(str(mchid or "").strip()),
        "merchant_serial_not_configured": bool(str(merchant_serial_no or "").strip()),
        "merchant_private_key_not_configured": _valid_rsa_private_key_pem(merchant_private_key_pem),
        "response_verification_key_not_configured": _valid_rsa_verification_material_pem(
            response_verification_key_pem
        ),
        "response_verification_key_id_not_configured": bool(str(response_verification_key_id or "").strip()),
    }
    if require_appid:
        checks = {"appid_not_configured": bool(str(appid or "").strip()), **checks}
    return [reason for reason, ready in checks.items() if not ready]


def _normalized_time_expire(value: Any) -> str:
    """Return a provider-safe RFC3339 expiry or omit an invalid optional value."""

    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _valid_wechat_order_id(value: str) -> bool:
    return 6 <= len(value) <= 32 and all(character in WECHAT_PAY_ORDER_ID_PATTERN for character in value)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_false(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def _refund_notify_url_from_env() -> str:
    explicit = os.environ.get("JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL", "").strip()
    if explicit:
        return explicit
    payment_notify_url = os.environ.get("JIEJING_WECHAT_PAY_NOTIFY_URL", "").strip()
    if payment_notify_url.endswith("/notify"):
        return f"{payment_notify_url[:-len('/notify')]}/refund-notify"
    return ""


def _sanitize_refund_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    amount = value.get("amount") if isinstance(value.get("amount"), Mapping) else {}
    return {
        "refund_id": str(value.get("refund_id") or "").strip()[:128],
        "out_refund_no": str(value.get("out_refund_no") or "").strip()[:64],
        "transaction_id": str(value.get("transaction_id") or "").strip()[:128],
        "out_trade_no": str(value.get("out_trade_no") or "").strip()[:32],
        "status": str(value.get("status") or value.get("refund_status") or "").strip().upper()[:32],
        "amount": {
            "refund": amount.get("refund"),
            "total": amount.get("total"),
            "currency": str(amount.get("currency") or "").strip().upper()[:8],
        },
    }


def _reference_hash(value: str) -> str:
    digest = hashes.Hash(hashes.SHA256())
    digest.update(str(value or "").encode("utf-8"))
    return digest.finalize().hex()


def _verify_and_decrypt_notification(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    api_v3_key: str,
    platform_certificate_pem: str,
    expected_serial_no: str,
    now_epoch: int | None,
) -> dict[str, Any]:
    if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > WECHAT_PAY_API_MAX_RESPONSE_BYTES:
        return _blocked("wechat_pay_callback_body_invalid", http_status=400)
    normalized_headers = {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}
    timestamp_text = normalized_headers.get("wechatpay-timestamp", "")
    nonce = normalized_headers.get("wechatpay-nonce", "")
    serial = normalized_headers.get("wechatpay-serial", "")
    signature_text = normalized_headers.get("wechatpay-signature", "")
    try:
        timestamp = int(timestamp_text)
    except (TypeError, ValueError):
        return _blocked("wechat_pay_signature_header_invalid", http_status=400)
    current_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    if abs(current_epoch - timestamp) > WECHAT_PAY_CALLBACK_TOLERANCE_SECONDS:
        return _blocked("wechat_pay_signature_timestamp_expired", http_status=400)
    if not nonce or len(nonce) > 128 or not hmac.compare_digest(serial, str(expected_serial_no).strip()):
        return _blocked("wechat_pay_signature_header_invalid", http_status=400)
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = _load_platform_public_key(platform_certificate_pem)
        message = f"{timestamp_text}\n{nonce}\n".encode("utf-8") + raw_body + b"\n"
        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return _blocked("wechat_pay_signature_invalid", http_status=400)
    try:
        envelope = json.loads(raw_body.decode("utf-8"))
        resource = envelope.get("resource") if isinstance(envelope, dict) else None
        if not isinstance(resource, dict) or str(resource.get("algorithm") or "") != "AEAD_AES_256_GCM":
            raise ValueError("unsupported encrypted resource")
        ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""), validate=True)
        resource_nonce = str(resource.get("nonce") or "").encode("utf-8")
        associated_data = str(resource.get("associated_data") or "").encode("utf-8")
        plaintext = AESGCM(api_v3_key.encode("utf-8")).decrypt(resource_nonce, ciphertext, associated_data)
        decrypted = json.loads(plaintext.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return _blocked("wechat_pay_resource_decryption_failed", http_status=400)
    except Exception:
        return _blocked("wechat_pay_resource_decryption_failed", http_status=400)
    if not isinstance(decrypted, dict):
        return _blocked("wechat_pay_refund_resource_invalid", http_status=400)
    return {
        "ok": True,
        "resource": decrypted,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "secret_exposed": False,
    }


def process_wechat_pay_notification_from_env(
    repository: SaaSRepository,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _verification_mode = _response_verification_material_from_env()
    return process_wechat_pay_notification(
        repository,
        raw_body=raw_body,
        headers=headers,
        api_v3_key=os.environ.get("JIEJING_WECHAT_PAY_API_V3_KEY", ""),
        platform_certificate_pem=verification_key_pem,
        expected_serial_no=verification_key_id,
        expected_appid=os.environ.get("JIEJING_WECHAT_PAY_APP_ID", ""),
        expected_mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
    )


def process_wechat_pay_notification(
    repository: SaaSRepository,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    api_v3_key: str,
    platform_certificate_pem: str,
    expected_serial_no: str,
    expected_appid: str,
    expected_mchid: str,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Verify, decrypt and apply one WeChat Pay payment-success notification."""

    if not _configuration_complete(
        api_v3_key=api_v3_key,
        platform_certificate_pem=platform_certificate_pem,
        expected_serial_no=expected_serial_no,
        expected_appid=expected_appid,
        expected_mchid=expected_mchid,
    ):
        return _blocked("wechat_pay_configuration_incomplete", http_status=503)
    if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > 1024 * 1024:
        return _blocked("wechat_pay_callback_body_invalid", http_status=400)

    normalized_headers = {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}
    timestamp_text = normalized_headers.get("wechatpay-timestamp", "")
    nonce = normalized_headers.get("wechatpay-nonce", "")
    serial = normalized_headers.get("wechatpay-serial", "")
    signature_text = normalized_headers.get("wechatpay-signature", "")
    try:
        timestamp = int(timestamp_text)
    except (TypeError, ValueError):
        return _blocked("wechat_pay_signature_header_invalid", http_status=400)
    current_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    if abs(current_epoch - timestamp) > WECHAT_PAY_CALLBACK_TOLERANCE_SECONDS:
        return _blocked("wechat_pay_signature_timestamp_expired", http_status=400)
    if not nonce or len(nonce) > 128 or not hmac.compare_digest(serial, str(expected_serial_no).strip()):
        return _blocked("wechat_pay_signature_header_invalid", http_status=400)
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = _load_platform_public_key(platform_certificate_pem)
        message = f"{timestamp_text}\n{nonce}\n".encode("utf-8") + raw_body + b"\n"
        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError):
        return _blocked("wechat_pay_signature_invalid", http_status=400)

    try:
        envelope = json.loads(raw_body.decode("utf-8"))
        resource = envelope.get("resource") if isinstance(envelope, dict) else None
        if not isinstance(resource, dict) or str(resource.get("algorithm") or "") != "AEAD_AES_256_GCM":
            raise ValueError("unsupported encrypted resource")
        ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""), validate=True)
        resource_nonce = str(resource.get("nonce") or "").encode("utf-8")
        associated_data = str(resource.get("associated_data") or "").encode("utf-8")
        plaintext = AESGCM(api_v3_key.encode("utf-8")).decrypt(resource_nonce, ciphertext, associated_data)
        transaction = json.loads(plaintext.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return _blocked("wechat_pay_resource_decryption_failed", http_status=400)
    except Exception:
        return _blocked("wechat_pay_resource_decryption_failed", http_status=400)
    if not isinstance(transaction, dict):
        return _blocked("wechat_pay_transaction_invalid", http_status=400)
    if str(transaction.get("trade_state") or "").upper() != "SUCCESS":
        return _blocked("wechat_pay_transaction_not_success", http_status=409)
    if not hmac.compare_digest(str(transaction.get("appid") or ""), str(expected_appid).strip()):
        return _blocked("wechat_pay_appid_mismatch", http_status=400)
    if not hmac.compare_digest(str(transaction.get("mchid") or ""), str(expected_mchid).strip()):
        return _blocked("wechat_pay_mchid_mismatch", http_status=400)

    return _apply_verified_transaction(
        repository,
        transaction=transaction,
        expected_appid=expected_appid,
        expected_mchid=expected_mchid,
        verification_source="signed_callback",
        signature_verified=True,
    )


def process_wechat_pay_refund_notification_from_env(
    repository: SaaSRepository,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    verification_key_pem, verification_key_id, _verification_mode = _response_verification_material_from_env()
    return process_wechat_pay_refund_notification(
        repository,
        raw_body=raw_body,
        headers=headers,
        api_v3_key=os.environ.get("JIEJING_WECHAT_PAY_API_V3_KEY", ""),
        platform_certificate_pem=verification_key_pem,
        expected_serial_no=verification_key_id,
        expected_mchid=os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
    )


def process_wechat_pay_refund_notification(
    repository: SaaSRepository,
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    api_v3_key: str,
    platform_certificate_pem: str,
    expected_serial_no: str,
    expected_mchid: str,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Verify, decrypt and apply one WeChat Pay refund notification."""

    if not (
        len(str(api_v3_key or "").encode("utf-8")) == 32
        and "BEGIN " in str(platform_certificate_pem or "")
        and bool(str(expected_serial_no or "").strip())
        and bool(str(expected_mchid or "").strip())
    ):
        return _blocked("wechat_pay_configuration_incomplete", http_status=503)
    decrypted = _verify_and_decrypt_notification(
        raw_body=raw_body,
        headers=headers,
        api_v3_key=api_v3_key,
        platform_certificate_pem=platform_certificate_pem,
        expected_serial_no=expected_serial_no,
        now_epoch=now_epoch,
    )
    if decrypted.get("ok") is not True:
        return decrypted
    refund = decrypted.get("resource") if isinstance(decrypted.get("resource"), dict) else {}
    if not hmac.compare_digest(str(refund.get("mchid") or ""), str(expected_mchid).strip()):
        return _blocked("wechat_pay_mchid_mismatch", http_status=400)
    order_id = str(refund.get("out_trade_no") or "").strip()
    if not _valid_wechat_order_id(order_id):
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    try:
        expected_refund_id = build_wechat_pay_refund_id(order_id)
    except ValueError:
        return _blocked("wechat_pay_order_id_invalid", http_status=400)
    return reconcile_wechat_pay_refund_result(
        repository,
        company_id="",
        order_id=order_id,
        expected_out_refund_no=expected_refund_id,
        provider_response=_sanitize_refund_response(refund),
        provider_verified=True,
        verification_source="signed_refund_callback",
        calls_external_payment_api=False,
        triggers_real_refund=False,
    )


def reconcile_wechat_pay_refund_result(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    expected_out_refund_no: str,
    provider_response: Mapping[str, Any],
    provider_verified: bool,
    verification_source: str,
    calls_external_payment_api: bool,
    triggers_real_refund: bool,
) -> dict[str, Any]:
    """Apply a verified refund request, query, or callback result idempotently."""

    if provider_verified is not True:
        return _blocked("wechat_pay_refund_result_not_verified", http_status=403)
    safe_response = _sanitize_refund_response(provider_response)
    normalized_order_id = str(order_id or "").strip()
    if not hmac.compare_digest(str(safe_response.get("out_trade_no") or ""), normalized_order_id):
        return _blocked("wechat_pay_refund_order_mismatch", http_status=400)
    if not hmac.compare_digest(str(safe_response.get("out_refund_no") or ""), str(expected_out_refund_no or "").strip()):
        return _blocked("wechat_pay_refund_reference_mismatch", http_status=400)
    order = repository.find_domestic_billing_order_for_provider(provider=WECHAT_PAY_PROVIDER, order_id=normalized_order_id)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    normalized_company = str(company_id or "").strip()
    if normalized_company and not hmac.compare_digest(str(order.get("company_id") or ""), normalized_company):
        return _blocked("domestic_billing_order_not_found", http_status=404)
    amount = safe_response.get("amount") if isinstance(safe_response.get("amount"), dict) else {}
    try:
        refund_amount = int(amount.get("refund"))
        total_amount = int(amount.get("total"))
    except (TypeError, ValueError):
        return _blocked("refund_amount_invalid", http_status=400)
    currency = str(amount.get("currency") or "").upper()
    if refund_amount != int(order.get("amount_minor") or 0) or total_amount != int(order.get("amount_minor") or 0):
        return _blocked("refund_amount_mismatch", http_status=400)
    if currency != str(order.get("currency") or "").upper():
        return _blocked("refund_currency_mismatch", http_status=400)
    refund_status = str(safe_response.get("status") or "").upper()
    if refund_status not in WECHAT_PAY_REFUND_STATUSES:
        return _blocked("wechat_pay_refund_response_invalid", http_status=400)
    provider_refund_id = str(safe_response.get("refund_id") or safe_response.get("out_refund_no") or "").strip()
    if refund_status == "SUCCESS":
        from .billing_domestic import apply_verified_domestic_refund

        result = apply_verified_domestic_refund(
            repository,
            company_id=str(order.get("company_id") or ""),
            order_id=normalized_order_id,
            provider_refund_id=provider_refund_id,
            amount_minor=refund_amount,
            currency=currency,
            provider_verified=True,
            verification_source=verification_source,
            calls_external_payment_api=calls_external_payment_api,
            triggers_real_refund=triggers_real_refund,
        )
        return {
            **result,
            "verification_source": verification_source,
            "calls_external_payment_api": bool(calls_external_payment_api),
            "triggers_real_refund": bool(triggers_real_refund),
        }

    target_status = "refund_processing" if refund_status == "PROCESSING" else "refund_failed"
    allowed_current = {"refund_review_requested", "refund_processing"}
    try:
        updated = repository.update_domestic_billing_order_state(
            company_id=str(order.get("company_id") or ""),
            order_id=normalized_order_id,
            status=target_status,
            allowed_current_statuses=allowed_current,
            state_details={
                "provider_refund_reference_hash": _reference_hash(provider_refund_id),
                "provider_refund_status": refund_status,
                "provider_verified": True,
                "verification_source": verification_source,
                "raw_provider_response_persisted": False,
            },
            audit_action=f"billing.domestic_refund.{target_status}",
            audit_summary=(
                "Provider-confirmed refund remains in progress."
                if target_status == "refund_processing"
                else "Provider reported that the refund needs operator attention."
            ),
            calls_external_payment_api=calls_external_payment_api,
            triggers_real_refund=triggers_real_refund,
        )
    except ValueError:
        return _blocked("domestic_billing_order_state_conflict", http_status=409)
    if not updated:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    return {
        "ok": True,
        "status": target_status,
        "provider_refund_status": refund_status,
        "order_id": normalized_order_id,
        "duplicate_result": bool(updated.get("duplicate_transition")),
        "verification_source": verification_source,
        "calls_external_payment_api": bool(calls_external_payment_api),
        "triggers_real_refund": bool(triggers_real_refund),
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def reconcile_wechat_pay_order_query(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_response: dict[str, Any],
    query_authenticated: bool,
    expected_appid: str,
    expected_mchid: str,
) -> dict[str, Any]:
    """Apply only a backend-authenticated WeChat order-query response."""

    if query_authenticated is not True:
        return _blocked("wechat_pay_query_not_authenticated", http_status=403)
    if not isinstance(provider_response, dict):
        return _blocked("wechat_pay_query_response_invalid", http_status=400)
    response_order_id = str(provider_response.get("out_trade_no") or "").strip()
    if not hmac.compare_digest(response_order_id, str(order_id or "").strip()):
        return _blocked("wechat_pay_query_order_mismatch", http_status=400)
    order = repository.get_domestic_billing_order(company_id=str(company_id or "").strip(), order_id=response_order_id)
    if not order or order.get("provider") != WECHAT_PAY_PROVIDER:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    return _apply_verified_transaction(
        repository,
        transaction=provider_response,
        expected_appid=expected_appid,
        expected_mchid=expected_mchid,
        verification_source="authenticated_order_query",
        signature_verified=False,
        expected_company_id=str(company_id or "").strip(),
    )


def _apply_verified_transaction(
    repository: SaaSRepository,
    *,
    transaction: dict[str, Any],
    expected_appid: str,
    expected_mchid: str,
    verification_source: str,
    signature_verified: bool,
    expected_company_id: str = "",
) -> dict[str, Any]:
    if str(transaction.get("trade_state") or "").upper() != "SUCCESS":
        return _blocked("wechat_pay_transaction_not_success", http_status=409)
    if not hmac.compare_digest(str(transaction.get("appid") or ""), str(expected_appid).strip()):
        return _blocked("wechat_pay_appid_mismatch", http_status=400)
    if not hmac.compare_digest(str(transaction.get("mchid") or ""), str(expected_mchid).strip()):
        return _blocked("wechat_pay_mchid_mismatch", http_status=400)
    order_id = str(transaction.get("out_trade_no") or "").strip()
    provider_order_id = str(transaction.get("transaction_id") or "").strip()
    if not order_id or not provider_order_id:
        return _blocked("wechat_pay_order_reference_missing", http_status=400)
    order = repository.find_domestic_billing_order_for_provider(provider=WECHAT_PAY_PROVIDER, order_id=order_id)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if expected_company_id and not hmac.compare_digest(str(order.get("company_id") or ""), expected_company_id):
        return _blocked("domestic_billing_order_not_found", http_status=404)
    company_id = str(order.get("company_id") or "")
    with repository.domestic_billing_company_lock(company_id=company_id):
        locked_order = repository.find_domestic_billing_order_for_provider(provider=WECHAT_PAY_PROVIDER, order_id=order_id)
        if not locked_order or not hmac.compare_digest(str(locked_order.get("company_id") or ""), company_id):
            return _blocked("domestic_billing_order_not_found", http_status=404)
        return _apply_verified_transaction_locked(
            repository,
            transaction=transaction,
            order=locked_order,
            order_id=order_id,
            provider_order_id=provider_order_id,
            expected_mchid=expected_mchid,
            verification_source=verification_source,
            signature_verified=signature_verified,
        )


def _apply_verified_transaction_locked(
    repository: SaaSRepository,
    *,
    transaction: dict[str, Any],
    order: dict[str, Any],
    order_id: str,
    provider_order_id: str,
    expected_mchid: str,
    verification_source: str,
    signature_verified: bool,
) -> dict[str, Any]:
    amount = transaction.get("amount") if isinstance(transaction.get("amount"), dict) else {}
    try:
        received_amount = int(amount.get("total"))
    except (TypeError, ValueError):
        return _blocked("payment_amount_invalid", http_status=400)
    received_currency = str(amount.get("currency") or "").upper()
    if received_amount != int(order.get("amount_minor") or 0):
        return _blocked("payment_amount_mismatch", http_status=400)
    if received_currency != str(order.get("currency") or "").upper():
        return _blocked("payment_currency_mismatch", http_status=400)
    if order.get("status") not in {"pending_payment", "paid"}:
        return _blocked("domestic_billing_order_not_payable", http_status=409)
    previous_provider_order_id = str(order.get("provider_order_id") or "")
    if order.get("status") == "paid" and previous_provider_order_id and previous_provider_order_id != provider_order_id:
        return _blocked("provider_transaction_conflict", http_status=409)

    duplicate_notification = order.get("status") == "paid"
    paid_at = _normalized_paid_at(transaction.get("success_time"))
    purchase_type, media_points = _domestic_order_purchase(order)
    entitlement_active_from = ""
    entitlement_active_until = ""
    if purchase_type == "subscription":
        stored_window = _persisted_paid_order_entitlement_window(order) if duplicate_notification else None
        if stored_window:
            entitlement_active_from, entitlement_active_until = stored_window
        else:
            entitlement_active_from, entitlement_active_until = _next_domestic_entitlement_window(
                repository,
                company_id=str(order["company_id"]),
                duration_days=int(order.get("duration_days") or 0),
            )
    try:
        paid_order = repository.mark_domestic_billing_order_paid(
            company_id=str(order["company_id"]),
            order_id=order_id,
            provider_order_id=provider_order_id,
            paid_at=paid_at,
            payment={
                "provider_transaction_present": True,
                "trade_type": str(transaction.get("trade_type") or ""),
                "amount_minor": received_amount,
                "currency": received_currency,
                "signature_verified": signature_verified,
                "verification_source": verification_source,
                "appid_verified": True,
                "mchid_verified": True,
                "amount_verified": True,
                "purchase_type": purchase_type,
                "media_points": media_points,
                "entitlement_active_from": entitlement_active_from,
                "entitlement_active_until": entitlement_active_until,
            },
        )
    except ValueError:
        return _blocked("domestic_billing_order_state_conflict", http_status=409)
    if not paid_order:
        return _blocked("domestic_billing_order_update_failed", http_status=409)
    if purchase_type == "media_points":
        if media_points <= 0:
            return _blocked("media_credit_purchase_contract_invalid", http_status=500)
        try:
            credit_result = repository.apply_media_credit_operation(
                company_id=str(order["company_id"]),
                user_id=str(order.get("user_id") or "") or None,
                operation_type="grant",
                points=media_points,
                idempotency_key=f"wechat-paid:{order_id}:media-points:v1",
                reference_type="billing_order",
                reference_id=order_id,
                details={"purchase_type": "media_points", "pack_key": str(order.get("plan_key") or "")},
            )
        except (RuntimeError, ValueError):
            return _blocked("media_credit_grant_not_applied", http_status=500)
        return {
            "ok": True,
            "status": "payment_confirmed",
            "order_id": order_id,
            "provider": WECHAT_PAY_PROVIDER,
            "plan_key": order["plan_key"],
            "purchase_type": "media_points",
            "media_points_granted": media_points,
            "amount_minor": received_amount,
            "currency": received_currency,
            "entitlement_active": False,
            "duplicate_notification": duplicate_notification or bool(credit_result.get("duplicate_request")),
            "verification_source": verification_source,
            "raw_payload_persisted": False,
            "raw_signature_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    entitlement = repository.apply_billing_webhook_event(
        event=_paid_order_entitlement_event(
            order=order,
            provider_order_id=provider_order_id,
            expected_mchid=expected_mchid,
            entitlement_active_until=entitlement_active_until,
        )
    )
    blockers = entitlement.get("entitlement_apply_blockers") if isinstance(entitlement.get("entitlement_apply_blockers"), list) else []
    if blockers:
        return _blocked("billing_entitlement_not_applied", http_status=500, blocked_by=blockers)
    return {
        "ok": True,
        "status": "payment_confirmed",
        "order_id": order_id,
        "provider": WECHAT_PAY_PROVIDER,
        "plan_key": order["plan_key"],
        "amount_minor": received_amount,
        "currency": received_currency,
        "entitlement_active": True,
        "duplicate_notification": duplicate_notification or bool(entitlement.get("duplicate_event")),
        "verification_source": verification_source,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def recover_paid_wechat_pay_entitlement(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    expected_mchid: str,
) -> dict[str, Any]:
    """Repair the narrow crash window after a verified payment was persisted."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    normalized_mchid = str(expected_mchid or "").strip()
    if not normalized_mchid:
        return _blocked("wechat_pay_mchid_not_configured", http_status=503)
    with repository.domestic_billing_company_lock(company_id=normalized_company):
        order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
        if not order or order.get("provider") != WECHAT_PAY_PROVIDER:
            return _blocked("domestic_billing_order_not_found", http_status=404)
        if order.get("status") != "paid":
            return _blocked("domestic_billing_order_not_paid", http_status=409)
        provider_order_id = str(order.get("provider_order_id") or "").strip()
        order_payload = order.get("order") if isinstance(order.get("order"), dict) else {}
        payment = order_payload.get("payment") if isinstance(order_payload.get("payment"), dict) else {}
        verified = all(
            payment.get(key) is True
            for key in ("provider_transaction_present", "appid_verified", "mchid_verified", "amount_verified")
        )
        try:
            amount_matches = int(payment.get("amount_minor")) == int(order.get("amount_minor") or 0)
        except (TypeError, ValueError):
            amount_matches = False
        currency_matches = str(payment.get("currency") or "").upper() == str(order.get("currency") or "").upper()
        if not provider_order_id or not verified or not amount_matches or not currency_matches:
            return _blocked("paid_order_entitlement_evidence_incomplete", http_status=500)

        purchase_type, media_points = _domestic_order_purchase(order)
        if purchase_type == "media_points":
            if media_points <= 0:
                return _blocked("media_credit_purchase_contract_invalid", http_status=500)
            try:
                credit_result = repository.apply_media_credit_operation(
                    company_id=normalized_company,
                    user_id=str(order.get("user_id") or "") or None,
                    operation_type="grant",
                    points=media_points,
                    idempotency_key=f"wechat-paid:{normalized_order}:media-points:v1",
                    reference_type="billing_order",
                    reference_id=normalized_order,
                    details={"purchase_type": "media_points", "pack_key": str(order.get("plan_key") or "")},
                )
            except (RuntimeError, ValueError):
                return _blocked("media_credit_grant_not_applied", http_status=500)
            return {
                "ok": True,
                "status": "paid",
                "order_id": normalized_order,
                "purchase_type": "media_points",
                "media_points_granted": media_points,
                "media_points_recovered": not bool(credit_result.get("duplicate_request")),
                "entitlement_recovered": False,
                "provider_query_required": False,
                "calls_external_payment_api": False,
                "triggers_real_charge": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            }

        window = _persisted_paid_order_entitlement_window(order)
        if not window:
            return _blocked("paid_order_entitlement_evidence_incomplete", http_status=500)

        _, entitlement_active_until = window
        subscription = repository.get_billing_subscription(company_id=normalized_company)
        subscription_payload = (
            subscription.get("subscription")
            if isinstance(subscription, dict) and isinstance(subscription.get("subscription"), dict)
            else {}
        )
        current_until = str(subscription_payload.get("active_until") or "").strip()
        if subscription and subscription.get("entitlement_active") is True and _iso_at_or_after(current_until, entitlement_active_until):
            return _paid_order_recovery_result(order=order, entitlement_recovered=False)

        entitlement = repository.apply_billing_webhook_event(
            event=_paid_order_entitlement_event(
                order=order,
                provider_order_id=provider_order_id,
                expected_mchid=normalized_mchid,
                entitlement_active_until=entitlement_active_until,
            )
        )
        blockers = entitlement.get("entitlement_apply_blockers") if isinstance(entitlement.get("entitlement_apply_blockers"), list) else []
        if blockers:
            return _blocked("billing_entitlement_not_applied", http_status=500, blocked_by=blockers)
        return _paid_order_recovery_result(order=order, entitlement_recovered=not bool(entitlement.get("duplicate_event")))


def _paid_order_recovery_result(*, order: dict[str, Any], entitlement_recovered: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "paid",
        "order_id": str(order.get("order_id") or ""),
        "entitlement_recovered": entitlement_recovered,
        "provider_query_required": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _paid_order_entitlement_event(
    *,
    order: dict[str, Any],
    provider_order_id: str,
    expected_mchid: str,
    entitlement_active_until: str,
) -> dict[str, Any]:
    return {
        "provider": WECHAT_PAY_PROVIDER,
        "event_id": provider_order_id,
        "event_type": "payment_succeeded",
        "supported_event": True,
        "company_id": str(order["company_id"]),
        "provider_customer_id": str(expected_mchid).strip(),
        "provider_subscription_id": str(order["order_id"]),
        "provider_plan_id": f"wechat_native_{order['plan_key']}_{order['amount_minor']}_{order['duration_days']}d",
        "plan_key": str(order["plan_key"]),
        "subscription_status": "active",
        "duration_days": int(order["duration_days"]),
        "active_until": entitlement_active_until,
        "quota_recalculation_required": True,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _domestic_order_purchase(order: Mapping[str, Any]) -> tuple[str, int]:
    payload = order.get("order") if isinstance(order.get("order"), Mapping) else {}
    purchase_type = str(payload.get("purchase_type") or "subscription").strip().lower()
    if purchase_type != "media_points":
        return "subscription", 0
    try:
        points = int(payload.get("media_points") or 0)
    except (TypeError, ValueError):
        points = 0
    return "media_points", points


def _persisted_paid_order_entitlement_window(order: dict[str, Any]) -> tuple[str, str] | None:
    if order.get("status") != "paid" or order.get("provider") != WECHAT_PAY_PROVIDER:
        return None
    if not str(order.get("provider_order_id") or "").strip():
        return None
    order_payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    payment = order_payload.get("payment") if isinstance(order_payload.get("payment"), dict) else {}
    if not all(
        payment.get(key) is True
        for key in ("provider_transaction_present", "appid_verified", "mchid_verified", "amount_verified")
    ):
        return None
    verification_source = str(payment.get("verification_source") or "").strip()
    if verification_source == "signed_callback":
        if payment.get("signature_verified") is not True:
            return None
    elif verification_source != "authenticated_order_query":
        return None
    try:
        stored_amount = int(payment.get("amount_minor"))
        order_amount = int(order.get("amount_minor"))
    except (TypeError, ValueError):
        return None
    stored_currency = str(payment.get("currency") or "").strip().upper()
    order_currency = str(order.get("currency") or "").strip().upper()
    if stored_amount <= 0 or stored_amount != order_amount or not stored_currency or stored_currency != order_currency:
        return None

    active_from = str(payment.get("entitlement_active_from") or "").strip()
    active_until = str(payment.get("entitlement_active_until") or "").strip()
    if not active_from or not active_until:
        active_from = str(order.get("paid_at") or "").strip()
        try:
            duration_days = int(order.get("duration_days"))
        except (TypeError, ValueError):
            return None
        if not active_from or not 1 <= duration_days <= 366:
            return None
        try:
            parsed_from = datetime.fromisoformat(active_from.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed_from.tzinfo is None:
            parsed_from = parsed_from.replace(tzinfo=timezone.utc)
        parsed_from = parsed_from.astimezone(timezone.utc).replace(microsecond=0)
        parsed_until = parsed_from + timedelta(days=duration_days)
        return parsed_from.isoformat(), parsed_until.isoformat()
    try:
        parsed_from = datetime.fromisoformat(active_from.replace("Z", "+00:00"))
        parsed_until = datetime.fromisoformat(active_until.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_from.tzinfo is None:
        parsed_from = parsed_from.replace(tzinfo=timezone.utc)
    if parsed_until.tzinfo is None:
        parsed_until = parsed_until.replace(tzinfo=timezone.utc)
    if parsed_until <= parsed_from:
        return None
    return parsed_from.astimezone(timezone.utc).replace(microsecond=0).isoformat(), parsed_until.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _iso_at_or_after(current_value: str, expected_value: str) -> bool:
    try:
        current = datetime.fromisoformat(str(current_value).replace("Z", "+00:00"))
        expected = datetime.fromisoformat(str(expected_value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) >= expected.astimezone(timezone.utc)


def _load_platform_public_key(value: str) -> Any:
    encoded = str(value or "").encode("utf-8")
    try:
        certificate = x509.load_pem_x509_certificate(encoded)
        return certificate.public_key()
    except ValueError:
        return serialization.load_pem_public_key(encoded)


def _valid_rsa_private_key_pem(value: str) -> bool:
    """Accept only a parseable unencrypted RSA private key of production strength."""

    try:
        private_key = serialization.load_pem_private_key(str(value or "").encode("utf-8"), password=None)
    except (TypeError, ValueError, UnicodeEncodeError, UnsupportedAlgorithm):
        return False
    return isinstance(private_key, rsa.RSAPrivateKey) and private_key.key_size >= 2048


def _valid_rsa_verification_material_pem(value: str) -> bool:
    """Accept a parseable RSA public key or x509 certificate, never mere PEM-looking text."""

    try:
        public_key = _load_platform_public_key(value)
    except (TypeError, ValueError, UnicodeEncodeError, UnsupportedAlgorithm):
        return False
    return isinstance(public_key, rsa.RSAPublicKey) and public_key.key_size >= 2048


def _response_verification_material_from_env() -> tuple[str, str, str]:
    """Prefer the public-key mode used by new merchants, with certificate fallback."""

    public_key_pem = _pem_from_env("JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM")
    public_key_id = os.environ.get("JIEJING_WECHAT_PAY_PUBLIC_KEY_ID", "").strip()
    public_key_material_supplied = any(
        os.environ.get(name, "").strip()
        for name in (
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
            "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
        )
    )
    if public_key_material_supplied:
        return public_key_pem, public_key_id, "wechat_pay_public_key"
    return (
        _pem_from_env("JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM"),
        os.environ.get("JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO", "").strip(),
        "platform_certificate",
    )


def _pem_from_env(name: str) -> str:
    """Read backend-only PEM text, preferring a Docker-safe Base64 value."""

    encoded = os.environ.get(f"{name}_B64", "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded, validate=True).decode("utf-8").strip()
        except (ValueError, UnicodeDecodeError):
            return ""
    return os.environ.get(name, "").strip()


def _configuration_complete(
    *,
    api_v3_key: str,
    platform_certificate_pem: str,
    expected_serial_no: str,
    expected_appid: str,
    expected_mchid: str,
) -> bool:
    return (
        len(str(api_v3_key or "").encode("utf-8")) == 32
        and _valid_rsa_verification_material_pem(platform_certificate_pem)
        and bool(str(expected_serial_no or "").strip())
        and bool(str(expected_appid or "").strip())
        and bool(str(expected_mchid or "").strip())
    )


def _https_url_configured(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("https://") and len(text) <= 2048


def _normalized_paid_at(value: Any) -> str:
    text = str(value or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_domestic_entitlement_window(
    repository: SaaSRepository,
    *,
    company_id: str,
    duration_days: int,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    active_from = now
    current = repository.get_billing_subscription(company_id=company_id)
    subscription = current.get("subscription") if isinstance(current, dict) and isinstance(current.get("subscription"), dict) else {}
    current_until = str(subscription.get("active_until") or "").strip()
    if current and current.get("entitlement_active") is True and current_until:
        try:
            parsed = datetime.fromisoformat(current_until.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
            if parsed > now:
                active_from = parsed
        except ValueError:
            pass
    active_until = active_from + timedelta(days=max(0, int(duration_days)))
    return active_from.isoformat(), active_until.isoformat()


def _blocked(reason: str, *, http_status: int, blocked_by: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "reason": reason,
        "blocked_by": list(blocked_by or [reason]),
        "http_status": http_status,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "raw_payload_persisted": False,
        "raw_signature_persisted": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
