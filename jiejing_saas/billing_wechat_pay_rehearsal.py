"""Isolated, value-free WeChat Pay rehearsal that can never move money."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .billing_domestic import (
    apply_verified_domestic_refund,
    execute_approved_domestic_billing_refund,
    request_domestic_billing_refund_review,
)
from .billing_wechat_pay import (
    WeChatPayTransportResponse,
    create_wechat_pay_native_order,
    process_wechat_pay_notification,
)
from .repository import SaaSRepository


WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION = "RUN WECHAT ZERO CHARGE REHEARSAL"
WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION = "2026-08-11-wechat-pay-zero-charge-audit-v1"
WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE = "billing_provider_rehearsal"
WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID = "wechat_pay_native_zero_charge_v1"
_APP_ID = "wx-isolated-rehearsal"
_MCH_ID = "1900000001"
_PLATFORM_KEY_ID = "WECHAT_REHEARSAL_PLATFORM_KEY"


def run_wechat_pay_zero_charge_rehearsal(
    *,
    exact_confirmation: str,
    repository: SaaSRepository | None = None,
    company_id: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    """Exercise only an in-process fake provider after an exact safe-mode phrase."""

    if str(exact_confirmation or "") != WECHAT_PAY_ZERO_CHARGE_REHEARSAL_CONFIRMATION:
        return _report(
            status="blocked",
            reason="exact_rehearsal_confirmation_required",
            transport_invoked=False,
        )
    try:
        with tempfile.TemporaryDirectory(
            prefix="jiejing-wechat-zero-charge-rehearsal-",
            ignore_cleanup_errors=True,
        ) as temp_dir:
            result = _run_isolated_rehearsal(Path(temp_dir))
        evidence_recorded = False
        normalized_company = str(company_id or "").strip()
        normalized_user = str(user_id or "").strip()
        if (
            result.get("status") == "ready"
            and repository is not None
            and normalized_company
            and normalized_user
        ):
            build_artifact_id = current_deployment_build_artifact_id()
            if not build_artifact_id:
                return {
                    **result,
                    "status": "blocked",
                    "reason": "deployment_build_artifact_unavailable",
                    "ready_for_owner_review": False,
                    "evidence_recorded": False,
                }
            repository.write_audit(
                company_id=normalized_company,
                user_id=normalized_user,
                actor_type="user",
                action_type="billing.wechat_pay.zero_charge_rehearsal.completed",
                target_type=WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_TYPE,
                target_id=WECHAT_PAY_ZERO_CHARGE_AUDIT_TARGET_ID,
                summary="Isolated WeChat Pay zero-charge rehearsal completed.",
                details={
                    "contract_version": WECHAT_PAY_ZERO_CHARGE_AUDIT_CONTRACT_VERSION,
                    "build_artifact_id": build_artifact_id,
                    "ready": True,
                    "step_count": len(result.get("steps") or []),
                    "fake_transport_call_count": int(result.get("fake_transport_call_count") or 0),
                    "creates_real_order": False,
                    "calls_external_api": False,
                    "calls_external_payment_api": False,
                    "triggers_real_charge": False,
                    "triggers_real_refund": False,
                    "charge_allowed": False,
                    "public_charging_allowed": False,
                    "secret_exposed": False,
                },
            )
            evidence_recorded = True
        return {**result, "evidence_recorded": evidence_recorded}
    except Exception:
        return _report(
            status="blocked",
            reason="isolated_rehearsal_internal_failure",
            transport_invoked=False,
        )


def current_deployment_build_artifact_id() -> str:
    """Hash the deployed backend package without accepting a request-supplied version."""

    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    try:
        paths = sorted(package_root.glob("*.py"), key=lambda item: item.name)
        if not paths:
            return ""
        for path in paths:
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError:
        return ""
    return digest.hexdigest()


def _run_isolated_rehearsal(root: Path) -> dict[str, Any]:
    # This route runs inside the production API process, whose environment is
    # intentionally configured for Postgres.  Pin the disposable repository to
    # SQLite so the rehearsal can never inherit or mutate the production DB.
    repository = SaaSRepository(
        root / "isolated.sqlite",
        database_engine="sqlite",
        database_url="",
    )
    account = repository.create_user_with_company(
        email="wechat-zero-charge-rehearsal@example.test",
        password="WeChat-zero-charge-rehearsal-2026",
        company_name="Isolated WeChat Rehearsal",
    )
    company_id = str(account["company"]["company_id"])
    user_id = str(account["user"]["user_id"])
    order_reference = "JJREHEARSALZEROCHARGE"
    repository.create_domestic_billing_order_record(
        order_id=order_reference,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=9900,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash="0" * 64,
        order={
            "provider_mode": "isolated_fake_transport_zero_charge",
            "provider_order_created": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
        },
    )

    merchant_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    platform_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    merchant_private_pem = merchant_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    platform_public_pem = platform_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    api_v3_key = secrets.token_hex(16)
    now_epoch = int(time.time())
    transport_calls = 0
    native_request_contract_valid = False

    def fake_transport(**request: Any) -> WeChatPayTransportResponse:
        nonlocal transport_calls, native_request_contract_valid
        transport_calls += 1
        body = json.loads(bytes(request.get("body") or b"").decode("utf-8"))
        amount = body.get("amount") if isinstance(body.get("amount"), dict) else {}
        native_request_contract_valid = all(
            (
                request.get("method") == "POST",
                request.get("url") == "https://api.mch.weixin.qq.com/v3/pay/transactions/native",
                str((request.get("headers") or {}).get("Authorization") or "").startswith(
                    "WECHATPAY2-SHA256-RSA2048 "
                ),
                body.get("out_trade_no") == order_reference,
                body.get("appid") == _APP_ID,
                body.get("mchid") == _MCH_ID,
                amount.get("total") == 9900,
                amount.get("currency") == "CNY",
                str(body.get("notify_url") or "").startswith("https://"),
            )
        )
        response_body = json.dumps(
            {"code_url": "weixin://wxpay/bizpayurl?pr=isolated-rehearsal"},
            separators=(",", ":"),
        ).encode("utf-8")
        response_nonce = "isolated-native-response"
        signature = platform_key.sign(
            f"{now_epoch}\n{response_nonce}\n".encode("utf-8") + response_body + b"\n",
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return WeChatPayTransportResponse(
            status_code=200,
            headers={
                "Wechatpay-Timestamp": str(now_epoch),
                "Wechatpay-Nonce": response_nonce,
                "Wechatpay-Serial": _PLATFORM_KEY_ID,
                "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
            },
            body=response_body,
        )

    native = create_wechat_pay_native_order(
        order={
            "order_id": order_reference,
            "amount_minor": 9900,
            "currency": "CNY",
            "plan_key": "starter",
            "order": {"display_name": "Jiejing isolated rehearsal"},
        },
        live_api_enabled=True,
        charge_allowed=True,
        appid=_APP_ID,
        mchid=_MCH_ID,
        merchant_serial_no="MERCHANT_REHEARSAL_SERIAL",
        merchant_private_key_pem=merchant_private_pem,
        response_verification_key_pem=platform_public_pem,
        response_verification_key_id=_PLATFORM_KEY_ID,
        notify_url="https://rehearsal.invalid/wechat/notify",
        transport=fake_transport,
        timestamp=now_epoch,
        nonce="isolated-native-request",
    )
    native_ready = native.get("ok") is True and native_request_contract_valid and transport_calls == 1

    entitlement_before_verified_payment = repository.get_billing_subscription(company_id=company_id) is None
    callback_body, callback_headers = _signed_payment_callback(
        platform_key=platform_key,
        order_reference=order_reference,
        now_epoch=now_epoch,
        api_v3_key=api_v3_key,
    )
    applied = process_wechat_pay_notification(
        repository,
        raw_body=callback_body,
        headers=callback_headers,
        api_v3_key=api_v3_key,
        platform_certificate_pem=platform_public_pem,
        expected_serial_no=_PLATFORM_KEY_ID,
        expected_appid=_APP_ID,
        expected_mchid=_MCH_ID,
        now_epoch=now_epoch,
    )
    replayed = process_wechat_pay_notification(
        repository,
        raw_body=callback_body,
        headers=callback_headers,
        api_v3_key=api_v3_key,
        platform_certificate_pem=platform_public_pem,
        expected_serial_no=_PLATFORM_KEY_ID,
        expected_appid=_APP_ID,
        expected_mchid=_MCH_ID,
        now_epoch=now_epoch,
    )
    subscription = repository.get_billing_subscription(company_id=company_id) or {}
    signed_callback_ready = all(
        (
            applied.get("ok") is True,
            applied.get("duplicate_notification") is False,
            replayed.get("ok") is True,
            replayed.get("duplicate_notification") is True,
        )
    )
    entitlement_ready = entitlement_before_verified_payment and subscription.get("entitlement_active") is True

    refund_review = request_domestic_billing_refund_review(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_reference,
        reason="Zero-charge rehearsal refund confirmation check.",
    )
    refund_provider_calls = 0

    def forbidden_refund_provider(**_request: Any) -> dict[str, Any]:
        nonlocal refund_provider_calls
        refund_provider_calls += 1
        return {"ok": False}

    blocked_refund = execute_approved_domestic_billing_refund(
        repository,
        company_id=company_id,
        user_id=user_id,
        order_id=order_reference,
        provider_refund=forbidden_refund_provider,
    )
    refund_boundary_ready = all(
        (
            refund_review.get("status") == "refund_review_requested",
            blocked_refund.get("reason") == "domestic_refund_confirmation_not_approved",
            refund_provider_calls == 0,
        )
    )
    refunded = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=order_reference,
        provider_refund_id="isolated-refund-result",
        amount_minor=9900,
        currency="CNY",
        provider_verified=True,
        verification_source="isolated_fake_provider_result",
        calls_external_payment_api=False,
        triggers_real_refund=False,
    )
    refunded_replay = apply_verified_domestic_refund(
        repository,
        company_id=company_id,
        order_id=order_reference,
        provider_refund_id="isolated-refund-result",
        amount_minor=9900,
        currency="CNY",
        provider_verified=True,
        verification_source="isolated_fake_provider_result",
        calls_external_payment_api=False,
        triggers_real_refund=False,
    )
    closed_subscription = repository.get_billing_subscription(company_id=company_id) or {}
    refund_recovery_ready = all(
        (
            refunded.get("status") == "refunded",
            refunded_replay.get("duplicate_refund_result") is True,
            closed_subscription.get("entitlement_active") is False,
        )
    )
    steps = [
        _step("native_order_request_contract", native_ready, request_count=transport_calls),
        _step(
            "signed_callback_and_replay",
            signed_callback_ready,
            verified_apply_count=1 if signed_callback_ready else 0,
        ),
        _step(
            "entitlement_after_verified_payment",
            entitlement_ready,
            entitlement_absent_before_verification=entitlement_before_verified_payment,
            entitlement_active_after_verification=subscription.get("entitlement_active") is True,
        ),
        _step(
            "refund_confirmation_boundary",
            refund_boundary_ready,
            provider_call_count=refund_provider_calls,
        ),
        _step(
            "refund_accounting_recovery",
            refund_recovery_ready,
            entitlement_closed=closed_subscription.get("entitlement_active") is False,
        ),
    ]
    ready = all(step.get("status") == "ready" for step in steps)
    return {
        **_report(
            status="ready" if ready else "blocked",
            reason="" if ready else "isolated_rehearsal_check_failed",
            transport_invoked=transport_calls > 0,
        ),
        "ready_for_owner_review": ready,
        "fake_transport_call_count": transport_calls,
        "steps": steps,
    }


def _signed_payment_callback(
    *,
    platform_key: rsa.RSAPrivateKey,
    order_reference: str,
    now_epoch: int,
    api_v3_key: str,
) -> tuple[bytes, dict[str, str]]:
    resource_nonce = "paynonce1234"
    associated_data = "isolated-payment-callback"
    transaction = {
        "appid": _APP_ID,
        "mchid": _MCH_ID,
        "out_trade_no": order_reference,
        "transaction_id": "isolated-payment-result",
        "trade_type": "NATIVE",
        "trade_state": "SUCCESS",
        "success_time": "2026-08-11T00:00:00+00:00",
        "amount": {"total": 9900, "currency": "CNY"},
    }
    ciphertext = AESGCM(api_v3_key.encode("ascii")).encrypt(
        resource_nonce.encode("ascii"),
        json.dumps(transaction, separators=(",", ":")).encode("utf-8"),
        associated_data.encode("ascii"),
    )
    envelope = {
        "id": "isolated-payment-notification",
        "event_type": "TRANSACTION.SUCCESS",
        "resource_type": "encrypt-resource",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "nonce": resource_nonce,
            "associated_data": associated_data,
        },
    }
    body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    callback_nonce = "isolated-callback-signature"
    signature = platform_key.sign(
        f"{now_epoch}\n{callback_nonce}\n".encode("utf-8") + body + b"\n",
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return body, {
        "Wechatpay-Timestamp": str(now_epoch),
        "Wechatpay-Nonce": callback_nonce,
        "Wechatpay-Serial": _PLATFORM_KEY_ID,
        "Wechatpay-Signature": base64.b64encode(signature).decode("ascii"),
    }


def _step(key: str, ready: bool, **evidence: Any) -> dict[str, Any]:
    return {
        "key": key,
        "status": "ready" if ready else "blocked",
        **evidence,
        "calls_external_api": False,
        "calls_external_payment_api": False,
        "creates_real_order": False,
        "triggers_charge": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "charge_allowed": False,
        "public_charging_allowed": False,
        "secret_exposed": False,
    }


def _report(*, status: str, reason: str, transport_invoked: bool) -> dict[str, Any]:
    return {
        "contract_version": "2026-08-11-wechat-pay-zero-charge-rehearsal-v1",
        "mode": "isolated_fake_transport_zero_charge",
        "status": status,
        "reason": reason,
        "transport_invoked": transport_invoked,
        "evidence_recorded": False,
        "creates_real_order": False,
        "calls_external_api": False,
        "calls_external_payment_api": False,
        "triggers_charge": False,
        "triggers_real_charge": False,
        "charge_allowed": False,
        "public_charging_allowed": False,
        "triggers_real_refund": False,
        "secret_exposed": False,
    }
