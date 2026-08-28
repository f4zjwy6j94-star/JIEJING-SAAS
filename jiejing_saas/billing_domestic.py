"""Provider-neutral domestic billing order boundary for Jiejing.

The first adapter target is WeChat Pay Native. Rehearsal orders never call a
provider. Live orders remain behind backend capability and owner-approval
gates, and are persisted before any payable provider order is requested.
"""

from __future__ import annotations

import hashlib
import base64
import io
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .permissions import has_permission
from .repository import SaaSRepository
from .media_credits import media_credit_pack_terms, media_credit_purchase_enabled, revoke_plan_media_points
from .operations_metering import sanitize_provider_telemetry


DOMESTIC_PAYMENT_PROVIDERS = {"wechat_pay_native"}
_CHECKOUT_LOCKS = tuple(threading.Lock() for _ in range(64))
DOMESTIC_PLAN_TERMS: dict[str, dict[str, Any]] = {
    "starter": {
        "amount_minor": 9900,
        "currency": "CNY",
        "duration_days": 30,
        "display_name": "捷境有店铺 30 天",
    },
    "operator": {
        "amount_minor": 19900,
        "currency": "CNY",
        "duration_days": 30,
        "display_name": "捷境多店铺 30 天",
    },
}
CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL = "I_APPROVE_ONE_CNY_REAL_WECHAT_PAY_ORDER"
CONTROLLED_WECHAT_PAY_ACCEPTANCE_AMOUNT_MINOR = 100
DOMESTIC_CHECKOUT_TTL_MINUTES = 15
DOMESTIC_REFUND_REASON_MIN_LENGTH = 2
DOMESTIC_REFUND_REASON_MAX_LENGTH = 500
DOMESTIC_RECONCILIATION_BATCH_LIMIT = 10
DOMESTIC_REFUND_REVIEW_TARGET_HOURS = 24


def create_controlled_wechat_pay_acceptance_order(
    repository: SaaSRepository,
    *,
    account_email: str,
    approval_phrase: str,
    idempotency_key: str,
    provider_create: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create the single owner-approved one-CNY live acceptance checkout.

    This path is intentionally not exposed by the public HTTP API. It exists so
    the operator can prove the real provider lifecycle without changing the
    reviewed 99 CNY plan or opening checkout for every staging account.
    """

    if str(approval_phrase or "") != CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL:
        return _blocked("real_payment_owner_approval_required", http_status=403)
    normalized_email = str(account_email or "").strip().lower()
    user = repository.get_user_by_email(normalized_email)
    if not user or user.get("status") != "active":
        return _blocked("acceptance_account_not_found", http_status=404)
    company_id = str(user.get("default_company_id") or "").strip()
    user_id = str(user.get("user_id") or "").strip()
    member = repository.get_team_member(company_id=company_id, user_id=user_id)
    if not member or not has_permission(str(member.get("role") or ""), "manage_billing"):
        return _blocked("acceptance_account_missing_billing_permission", http_status=403)
    normalized_idempotency = str(idempotency_key or "").strip()
    if not (8 <= len(normalized_idempotency) <= 128) or not re.fullmatch(r"[A-Za-z0-9._:-]+", normalized_idempotency):
        return _blocked("billing_idempotency_key_invalid", http_status=400)

    idempotency_hash = hashlib.sha256(
        f"domestic-live-acceptance-v1:{company_id}:{normalized_idempotency}".encode("utf-8")
    ).hexdigest()
    order_id = f"JJLIVE{idempotency_hash[:26]}"
    stored = repository.create_domestic_billing_order_record(
        order_id=order_id,
        company_id=company_id,
        user_id=user_id,
        provider="wechat_pay_native",
        plan_key="starter",
        amount_minor=CONTROLLED_WECHAT_PAY_ACCEPTANCE_AMOUNT_MINOR,
        currency="CNY",
        duration_days=30,
        status="pending_payment",
        idempotency_key_hash=idempotency_hash,
        order={
            "contract_version": "2026-07-13-wechat-pay-live-acceptance-v1",
            "display_name": "捷境支付验收测试（1 元）",
            "live_acceptance_test": True,
            "provider_mode": "owner_approved_single_live_acceptance",
            "provider_order_created": False,
            "payable_qr_created": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "bank_details_persisted": False,
            "payment_secret_persisted": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
    checkout = open_domestic_billing_checkout(
        repository,
        company_id=company_id,
        order_id=str(stored.get("order_id") or order_id),
        provider_create=provider_create,
    )
    return {
        **checkout,
        "plan_key": "starter",
        "display_name": "捷境支付验收测试（1 元）",
        "duration_days": 30,
        "live_acceptance_test": True,
        "public_checkout_enabled": False,
        "secret_exposed": False,
    }


def create_domestic_billing_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    provider: str,
    plan_key: str,
    idempotency_key: str,
    rehearsal: bool = True,
) -> dict[str, Any]:
    """Persist one tenant order before any provider call is allowed."""

    normalized_company = str(company_id or "").strip()
    normalized_user = str(user_id or "").strip()
    normalized_provider = str(provider or "").strip().lower()
    normalized_plan = str(plan_key or "").strip().lower()
    normalized_idempotency = str(idempotency_key or "").strip()
    if not normalized_company or not normalized_user:
        return _blocked("billing_account_context_missing", http_status=400)
    if normalized_provider not in DOMESTIC_PAYMENT_PROVIDERS:
        return _blocked("domestic_payment_provider_not_supported", http_status=400)
    terms = DOMESTIC_PLAN_TERMS.get(normalized_plan)
    purchase_type = "subscription"
    if not terms:
        terms = media_credit_pack_terms(normalized_plan)
        if terms:
            purchase_type = "media_points"
            if not media_credit_purchase_enabled():
                return _blocked("media_credit_purchase_not_enabled", http_status=409)
    if not terms:
        return _blocked("domestic_billing_plan_not_supported", http_status=400)
    if not (8 <= len(normalized_idempotency) <= 128) or not re.fullmatch(r"[A-Za-z0-9._:-]+", normalized_idempotency):
        return _blocked("billing_idempotency_key_invalid", http_status=400)
    idempotency_hash = hashlib.sha256(
        f"domestic-order-v1:{normalized_company}:{normalized_idempotency}".encode("utf-8")
    ).hexdigest()
    creation_intent = purchase_type if purchase_type == "subscription" else f"{purchase_type}:{normalized_plan}"
    creation_lock_id = f"create:{normalized_provider}:{creation_intent}"
    with repository.domestic_billing_company_lock(company_id=normalized_company):
        with _checkout_lock(normalized_company, creation_lock_id):
            if not rehearsal:
                existing = _active_pending_domestic_order(
                    repository,
                    company_id=normalized_company,
                    provider=normalized_provider,
                    plan_key=normalized_plan,
                    purchase_type=purchase_type,
                )
                if existing:
                    return _domestic_order_creation_result(
                        existing,
                        terms=terms,
                        purchase_type=purchase_type,
                        duplicate_request=True,
                    )

            # WeChat Pay requires out_trade_no to be no longer than 32 characters.
            order_id = f"domestic_{idempotency_hash[:23]}"
            initial_status = "rehearsal_order_created" if rehearsal else "pending_payment"
            stored = repository.create_domestic_billing_order_record(
                order_id=order_id,
                company_id=normalized_company,
                user_id=normalized_user,
                provider=normalized_provider,
                plan_key=normalized_plan,
                amount_minor=int(terms["amount_minor"]),
                currency=str(terms["currency"]),
                duration_days=int(terms["duration_days"]),
                status=initial_status,
                idempotency_key_hash=idempotency_hash,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=DOMESTIC_CHECKOUT_TTL_MINUTES))
                .replace(microsecond=0)
                .isoformat()
                if not rehearsal
                else None,
                order={
                    "contract_version": "2026-07-15-domestic-billing-order-v4",
                    "display_name": str(terms["display_name"]),
                    "purchase_type": purchase_type,
                    "media_points": int(terms.get("points") or 0),
                    "provider_mode": "rehearsal_no_charge" if rehearsal else "live_provider_gated",
                    "provider_order_created": False,
                    "payable_qr_created": False,
                    "calls_external_payment_api": False,
                    "triggers_real_charge": False,
                    "bank_details_persisted": False,
                    "payment_secret_persisted": False,
                    "frontend_gets_payment_secret": False,
                    "secret_exposed": False,
                },
            )
            return _domestic_order_creation_result(
                stored,
                terms=terms,
                purchase_type=purchase_type,
                duplicate_request=bool(stored.get("duplicate_request")),
            )


def _active_pending_domestic_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    provider: str,
    plan_key: str,
    purchase_type: str,
) -> dict[str, Any] | None:
    for order in repository.list_domestic_billing_orders(company_id=company_id, limit=20):
        payload = order.get("order") if isinstance(order.get("order"), dict) else {}
        same_purchase_intent = purchase_type == "subscription" or str(order.get("plan_key") or "") == plan_key
        if (
            str(order.get("provider") or "") == provider
            and same_purchase_intent
            and str(payload.get("purchase_type") or "subscription") == purchase_type
            and str(order.get("status") or "") in {"pending_payment", "payable_order_created"}
            and not _is_checkout_expired(order.get("expires_at"))
        ):
            return order
    return None


def _domestic_order_creation_result(
    stored: dict[str, Any],
    *,
    terms: dict[str, Any],
    purchase_type: str,
    duplicate_request: bool,
) -> dict[str, Any]:
    order = stored.get("order") if isinstance(stored.get("order"), dict) else {}
    return {
        "ok": True,
        "status": stored["status"],
        "order_id": stored["order_id"],
        "provider": stored["provider"],
        "provider_order_id": stored["provider_order_id"],
        "plan_key": stored["plan_key"],
        "display_name": order.get("display_name") or str(terms["display_name"]),
        "amount_minor": stored["amount_minor"],
        "currency": stored["currency"],
        "duration_days": stored["duration_days"],
        "purchase_type": purchase_type,
        "media_points": int(terms.get("points") or 0),
        "expires_at": stored.get("expires_at"),
        "code_url": "",
        "duplicate_request": duplicate_request,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def open_domestic_billing_checkout(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_create: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or replay a tenant-scoped payable QR without persisting raw responses."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    with repository.domestic_billing_company_lock(company_id=normalized_company):
        with _checkout_lock(normalized_company, normalized_order):
            return _open_domestic_billing_checkout(
                repository,
                company_id=normalized_company,
                order_id=normalized_order,
                provider_create=provider_create,
            )


def _open_domestic_billing_checkout(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_create: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    normalized_company = company_id
    normalized_order = order_id
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order or order.get("provider") not in DOMESTIC_PAYMENT_PROVIDERS:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    purchase_type, media_points = _domestic_order_purchase(order)
    if order.get("status") == "rehearsal_order_created":
        return _blocked("domestic_real_checkout_not_enabled", http_status=409)
    if order.get("status") in {"paid", "refunded"}:
        return {
            "ok": True,
            "status": str(order["status"]),
            "order_id": normalized_order,
            "purchase_type": purchase_type,
            "media_points": media_points,
            "code_url": "",
            "duplicate_request": True,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if _is_checkout_expired(order.get("expires_at")):
        return _blocked("domestic_billing_order_expired", http_status=409)
    if order.get("status") != "pending_payment":
        return _blocked("domestic_billing_order_not_payable", http_status=409)
    order_payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    checkout = order_payload.get("checkout") if isinstance(order_payload.get("checkout"), dict) else {}
    stored_code_url = str(checkout.get("code_url") or "").strip()
    if stored_code_url.startswith("weixin://"):
        return {
            "ok": True,
            "status": "payable_order_created",
            "provider": str(order["provider"]),
            "order_id": normalized_order,
            "code_url": stored_code_url,
            "amount_minor": int(order["amount_minor"]),
            "currency": str(order["currency"]),
            "duration_days": int(order["duration_days"]),
            "purchase_type": purchase_type,
            "media_points": media_points,
            "expires_at": order.get("expires_at"),
            "display_name": str(order_payload.get("display_name") or "捷境套餐 30 天"),
            "duplicate_request": True,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if provider_create is None:
        from .billing_wechat_pay import create_wechat_pay_native_order_from_env

        provider_create = create_wechat_pay_native_order_from_env
    result = _call_and_meter_payment_provider(
        repository,
        company_id=normalized_company,
        user_id=str(order.get("user_id") or "") or None,
        order_id=normalized_order,
        operation="checkout_create",
        provider_call=provider_create,
        call_kwargs={"order": order},
        success_validator=lambda packet: str(packet.get("code_url") or "").startswith("weixin://"),
    )
    if not isinstance(result, dict) or result.get("ok") is not True:
        return result if isinstance(result, dict) else _blocked("wechat_pay_provider_response_invalid", http_status=502)
    code_url = str(result.get("code_url") or "").strip()
    if not code_url.startswith("weixin://"):
        return _blocked("wechat_pay_native_code_url_invalid", http_status=502)
    attached = repository.attach_domestic_billing_checkout(
        company_id=normalized_company,
        order_id=normalized_order,
        code_url=code_url,
    )
    if not attached:
        return _blocked("domestic_billing_order_update_failed", http_status=409)
    return {
        "ok": True,
        "status": "payable_order_created",
        "provider": str(order["provider"]),
        "order_id": normalized_order,
        "code_url": code_url,
        "amount_minor": int(order["amount_minor"]),
        "currency": str(order["currency"]),
        "duration_days": int(order["duration_days"]),
        "purchase_type": purchase_type,
        "media_points": media_points,
        "expires_at": order.get("expires_at"),
        "display_name": str(order_payload.get("display_name") or "捷境套餐 30 天"),
        "duplicate_request": False,
        "calls_external_payment_api": True,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def merchant_domestic_billing_order(order: dict[str, Any], *, include_checkout: bool = False) -> dict[str, Any]:
    """Return the merchant contract without tenant IDs, raw provider URIs or diagnostics."""

    payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    status = str(order.get("status") or "").strip()
    checkout_expired = _is_checkout_expired(order.get("expires_at"))
    display_name = str(order.get("display_name") or payload.get("display_name") or "捷境套餐 30 天").strip()
    purchase_type = str(order.get("purchase_type") or payload.get("purchase_type") or "subscription").strip().lower()
    safe = {
        "ok": order.get("ok") is True or bool(order.get("order_id")),
        "order_id": str(order.get("order_id") or ""),
        "provider": str(order.get("provider") or WECHAT_PAY_PROVIDER_FALLBACK),
        "plan_key": str(order.get("plan_key") or "starter"),
        "display_name": display_name,
        "amount_minor": int(order.get("amount_minor") or 0),
        "currency": str(order.get("currency") or "CNY"),
        "duration_days": int(order.get("duration_days") or 0),
        "purchase_type": purchase_type if purchase_type in {"subscription", "media_points"} else "subscription",
        "media_points": int(order.get("media_points") or payload.get("media_points") or 0),
        "status": status,
        "expires_at": order.get("expires_at"),
        "paid_at": order.get("paid_at"),
        "created_at": order.get("created_at"),
        "updated_at": order.get("updated_at"),
        "checkout_expired": checkout_expired,
        "can_continue_payment": status in {"pending_payment", "payable_order_created"} and not checkout_expired,
        "can_close": status in {"pending_payment", "payable_order_created"},
        "can_request_refund": status == "paid",
        "refund_review_pending": status in {"refund_review_requested", "refund_processing"},
        "refund_processing": status == "refund_processing",
        "refund_attention_required": status == "refund_failed",
        "payment_record_available": status in {"paid", "refund_review_requested", "refund_processing", "refund_failed", "refunded"},
        "payment_record_reference": str(order.get("order_id") or "")
        if status in {"paid", "refund_review_requested", "refund_processing", "refund_failed", "refunded"}
        else "",
        "invoice_request_available": status == "paid",
        "invoice_request_route": "service" if status == "paid" else "",
        "renewal_mode": "not_applicable" if purchase_type == "media_points" else "merchant_confirmed_one_time_30_day",
        "duplicate_request": bool(order.get("duplicate_request")),
        "calls_external_payment_api": bool(order.get("calls_external_payment_api")),
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    if include_checkout and status in {"pending_payment", "payable_order_created"} and not checkout_expired:
        checkout = payload.get("checkout") if isinstance(payload.get("checkout"), dict) else {}
        code_url = str(order.get("code_url") or checkout.get("code_url") or "").strip()
        if code_url.startswith("weixin://"):
            safe["qr_image_data_url"] = _native_qr_data_url(code_url)
    return safe


WECHAT_PAY_PROVIDER_FALLBACK = "wechat_pay_native"


def close_domestic_billing_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    order_id: str,
    provider_close: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Close one unpaid provider order and persist the result exactly once."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    with repository.domestic_billing_company_lock(company_id=normalized_company):
        with _checkout_lock(normalized_company, normalized_order):
            return _close_domestic_billing_order(
                repository,
                company_id=normalized_company,
                user_id=user_id,
                order_id=normalized_order,
                provider_close=provider_close,
            )


def _close_domestic_billing_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    order_id: str,
    provider_close: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    """Serialized implementation for the merchant close operation."""

    normalized_company = company_id
    normalized_user = str(user_id or "").strip()
    normalized_order = order_id
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    current_status = str(order.get("status") or "")
    if current_status == "closed":
        return {
            "ok": True,
            "status": "closed",
            "order_id": normalized_order,
            "duplicate_request": True,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }
    if current_status != "pending_payment":
        return _blocked("domestic_billing_order_not_closable", http_status=409)
    payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    checkout = payload.get("checkout") if isinstance(payload.get("checkout"), dict) else {}
    provider_order_created = str(checkout.get("code_url") or "").startswith("weixin://")
    provider_result: dict[str, Any] = {"ok": True, "calls_external_payment_api": False}
    if provider_order_created:
        if provider_close is None:
            from .billing_wechat_pay import close_wechat_pay_order_from_env

            provider_close = close_wechat_pay_order_from_env
        provider_result = _call_and_meter_payment_provider(
            repository,
            company_id=normalized_company,
            user_id=normalized_user or None,
            order_id=normalized_order,
            operation="order_close",
            provider_call=provider_close,
            call_kwargs={"order_id": normalized_order},
        )
        if not isinstance(provider_result, dict) or provider_result.get("ok") is not True:
            return provider_result if isinstance(provider_result, dict) else _blocked("wechat_pay_provider_response_invalid", http_status=502)
    try:
        updated = repository.update_domestic_billing_order_state(
            company_id=normalized_company,
            order_id=normalized_order,
            status="closed",
            allowed_current_statuses={"pending_payment"},
            state_details={
                "provider_order_closed": True,
                "provider_order_created": provider_order_created,
                "provider_close_authenticated": provider_order_created,
                "payable_qr_removed": True,
            },
            audit_action="billing.domestic_order.closed",
            audit_summary="Merchant closed an unpaid domestic billing order.",
            user_id=normalized_user,
        )
    except ValueError:
        return _blocked("domestic_billing_order_not_closable", http_status=409)
    if not updated:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    return {
        "ok": True,
        "status": "closed",
        "order_id": normalized_order,
        "duplicate_request": bool(updated.get("duplicate_transition")),
        "calls_external_payment_api": bool(provider_result.get("calls_external_payment_api")),
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _native_qr_data_url(code_url: str) -> str:
    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover - deployment dependency check covers this path.
        raise RuntimeError("qrcode dependency is required for WeChat Pay Native checkout") from exc
    image = qrcode.make(code_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _is_checkout_expired(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        expires_at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _checkout_lock(company_id: str, order_id: str) -> threading.Lock:
    digest = hashlib.sha256(f"{company_id}:{order_id}".encode("utf-8")).digest()
    return _CHECKOUT_LOCKS[int.from_bytes(digest[:2], "big") % len(_CHECKOUT_LOCKS)]


def query_and_reconcile_domestic_billing_order(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_query: Callable[..., dict[str, Any]] | None = None,
    expected_appid: str = "",
    expected_mchid: str = "",
) -> dict[str, Any]:
    """Query one owned order and expose only a sanitized merchant status."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    local = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not local or local.get("provider") not in DOMESTIC_PAYMENT_PROVIDERS:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if local.get("status") == "paid":
        from .billing_wechat_pay import recover_paid_wechat_pay_entitlement

        return recover_paid_wechat_pay_entitlement(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
            expected_mchid=expected_mchid or os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        )
    if local.get("status") in {"refunded", "closed", "payment_failed", "refund_review_requested"}:
        return {
            "ok": True,
            "status": str(local["status"]),
            "order_id": normalized_order,
            "provider_query_required": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if local.get("status") != "pending_payment":
        return _blocked("wechat_pay_live_order_query_not_enabled", http_status=409)
    if provider_query is None:
        from .billing_wechat_pay import query_wechat_pay_order_from_env

        provider_query = query_wechat_pay_order_from_env
    query_result = _call_and_meter_payment_provider(
        repository,
        company_id=normalized_company,
        user_id=str(local.get("user_id") or "") or None,
        order_id=normalized_order,
        operation="order_query",
        provider_call=provider_query,
        call_kwargs={"order_id": normalized_order},
        success_validator=lambda packet: (
            packet.get("query_authenticated") is True
            and isinstance(packet.get("provider_response"), dict)
            and str(packet["provider_response"].get("out_trade_no") or "").strip() == normalized_order
            and bool(str(packet["provider_response"].get("trade_state") or "").strip())
        ),
    )
    if not isinstance(query_result, dict) or query_result.get("ok") is not True:
        return query_result if isinstance(query_result, dict) else _blocked("wechat_pay_provider_response_invalid", http_status=502)
    provider_response = query_result.get("provider_response") if isinstance(query_result.get("provider_response"), dict) else {}
    if str(provider_response.get("out_trade_no") or "").strip() != normalized_order:
        return _blocked("wechat_pay_query_order_mismatch", http_status=400)
    provider_state = str(provider_response.get("trade_state") or "").strip().upper()
    if provider_state == "SUCCESS":
        from .billing_wechat_pay import reconcile_wechat_pay_order_query

        return reconcile_wechat_pay_order_query(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
            provider_response=provider_response,
            query_authenticated=query_result.get("query_authenticated") is True,
            expected_appid=expected_appid or os.environ.get("JIEJING_WECHAT_PAY_APP_ID", ""),
            expected_mchid=expected_mchid or os.environ.get("JIEJING_WECHAT_PAY_MCH_ID", ""),
        )
    allowed_states = {"NOTPAY", "USERPAYING", "CLOSED", "REVOKED", "PAYERROR"}
    if provider_state not in allowed_states:
        return _blocked("wechat_pay_query_response_invalid", http_status=502)
    target_status = "pending_payment"
    if provider_state in {"CLOSED", "REVOKED", "PAYERROR"}:
        target_status = "payment_failed" if provider_state == "PAYERROR" else "closed"
        try:
            repository.update_domestic_billing_order_state(
                company_id=normalized_company,
                order_id=normalized_order,
                status=target_status,
                allowed_current_statuses={"pending_payment"},
                state_details={
                    "provider_state": provider_state,
                    "provider_query_authenticated": query_result.get("query_authenticated") is True,
                    "payable_qr_removed": True,
                },
                audit_action=f"billing.domestic_order.{target_status}",
                audit_summary="Authenticated provider query closed a non-payable domestic billing order.",
            )
        except ValueError:
            return _blocked("domestic_billing_order_state_conflict", http_status=409)
    return {
        "ok": True,
        "status": "pending_payment" if provider_state in {"NOTPAY", "USERPAYING"} else target_status,
        "order_id": normalized_order,
        "provider_state": provider_state,
        "provider_query_required": provider_state in {"NOTPAY", "USERPAYING"},
        "calls_external_payment_api": True,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def request_domestic_billing_refund_review(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    order_id: str,
    reason: str,
) -> dict[str, Any]:
    """Record a merchant refund-review request without moving any money."""

    normalized_company = str(company_id or "").strip()
    normalized_user = str(user_id or "").strip()
    normalized_order = str(order_id or "").strip()
    if not normalized_company or not normalized_user or not normalized_order:
        return _blocked("billing_account_context_missing", http_status=400)
    normalized_reason = " ".join(str(reason or "").split())
    if len(normalized_reason) < DOMESTIC_REFUND_REASON_MIN_LENGTH:
        return _blocked("domestic_refund_reason_required", http_status=400)
    if len(normalized_reason) > DOMESTIC_REFUND_REASON_MAX_LENGTH:
        return _blocked("domestic_refund_reason_too_long", http_status=400)
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if order.get("status") not in {"paid", "refund_review_requested"}:
        return _blocked("domestic_billing_order_not_refundable", http_status=409)
    purchase_type, media_points = _domestic_order_purchase(order)
    try:
        updated = repository.update_domestic_billing_order_state(
            company_id=normalized_company,
            order_id=normalized_order,
            status="refund_review_requested",
            allowed_current_statuses={"paid"},
            state_details={
                "refund_reason_present": True,
                "refund_reason_summary": normalized_reason,
                "refund_reason_length": len(normalized_reason),
                "refund_reason_normalized_persisted": True,
                "refund_reason_raw_persisted": False,
                "provider_refund_called": False,
                "human_review_required": True,
            },
            audit_action="billing.domestic_refund.review_requested",
            audit_summary=(
                "Merchant requested review of a domestic media point refund."
                if purchase_type == "media_points"
                else "Merchant requested review of a domestic subscription refund."
            ),
            user_id=normalized_user,
        )
    except ValueError:
        return _blocked("domestic_billing_order_not_refundable", http_status=409)
    if not updated:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    confirmation_id = _domestic_refund_confirmation_id(normalized_order)
    confirmation = repository.get_confirmation(company_id=normalized_company, confirmation_id=confirmation_id)
    if not confirmation:
        state = updated.get("order", {}).get("state", {}) if isinstance(updated.get("order"), dict) else {}
        confirmation = repository.create_confirmation(
            company_id=normalized_company,
            store_id=None,
            task_id=None,
            runtime_run_id=f"billing_refund:{normalized_order}",
            action_type="refund",
            title="审核素材点退款" if purchase_type == "media_points" else "审核订阅退款",
            item={
                "source": "domestic_billing_refund_review",
                "scope": "account",
                "order_id": normalized_order,
                "plan_key": str(order.get("plan_key") or ""),
                "amount_minor": int(order.get("amount_minor") or 0),
                "currency": str(order.get("currency") or "").upper(),
                "purchase_type": purchase_type,
                "media_points": media_points,
                "refund_reason_summary": str(state.get("refund_reason_summary") or ""),
                "full_refund_only": True,
                "moves_money": True,
                "approval_does_not_execute": True,
                "provider_call_pending": True,
            },
            created_by=normalized_user,
            confirmation_id=confirmation_id,
            default_action="hold",
        )
    return {
        "ok": True,
        "status": "refund_review_requested",
        "order_id": normalized_order,
        "duplicate_request": bool(updated.get("duplicate_transition")),
        "refund_reason_received": True,
        "human_review_required": True,
        "confirmation_id": confirmation_id,
        "confirmation_status": str(confirmation.get("status") or "pending"),
        "calls_external_payment_api": False,
        "triggers_real_refund": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def execute_approved_domestic_billing_refund(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str,
    order_id: str,
    provider_refund: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one full refund only after an account-scoped approval."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    approval = _approved_domestic_refund_confirmation(
        repository,
        company_id=normalized_company,
        order_id=normalized_order,
    )
    if approval.get("ok") is not True:
        return approval
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order or order.get("provider") not in DOMESTIC_PAYMENT_PROVIDERS:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if order.get("status") == "refunded":
        return {
            "ok": True,
            "status": "refunded",
            "order_id": normalized_order,
            "duplicate_request": True,
            "confirmation_id": approval.get("confirmation_id"),
            "calls_external_payment_api": False,
            "triggers_real_refund": False,
            "secret_exposed": False,
        }
    if order.get("status") == "refund_processing":
        return {
            "ok": True,
            "status": "refund_processing",
            "order_id": normalized_order,
            "duplicate_request": True,
            "provider_query_required": True,
            "confirmation_id": approval.get("confirmation_id"),
            "calls_external_payment_api": False,
            "triggers_real_refund": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    if order.get("status") not in {"refund_review_requested", "refund_processing"}:
        return _blocked("domestic_billing_order_not_refundable", http_status=409)
    order_payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    state = order_payload.get("state") if isinstance(order_payload.get("state"), dict) else {}
    purchase_type, media_points = _domestic_order_purchase(order)
    reason = str(state.get("refund_reason_summary") or ("商家素材点退款" if purchase_type == "media_points" else "商家订阅退款"))
    refund_reservation: dict[str, Any] | None = None
    if purchase_type == "media_points":
        try:
            refund_reservation = repository.reserve_media_credit_source(
                company_id=normalized_company,
                user_id=str(user_id or "") or None,
                source_type="purchased",
                source_reference_id=normalized_order,
                points=media_points,
                idempotency_key=f"wechat-refund:{normalized_order}:media-points-reserve:v1",
                reference_type="billing_refund",
                reference_id=normalized_order,
                details={"unused_points_required": True, "purchase_type": "media_points"},
            )
        except ValueError:
            return {
                **_blocked("media_points_refund_requires_unused_balance", http_status=409),
                "blocked_by": ["purchased_media_points_already_used_or_reserved"],
            }
        reservation_entry = refund_reservation.get("ledger_entry") if isinstance(refund_reservation, dict) else {}
        if not isinstance(reservation_entry, dict) or reservation_entry.get("status") != "reserved":
            return _blocked("media_points_refund_reservation_unavailable", http_status=409)
    if provider_refund is None:
        from .billing_wechat_pay import request_wechat_pay_refund_from_env

        provider_refund = request_wechat_pay_refund_from_env
    provider_result = _call_and_meter_payment_provider(
        repository,
        company_id=normalized_company,
        user_id=str(user_id or "") or None,
        order_id=normalized_order,
        operation="refund_create",
        provider_call=provider_refund,
        call_kwargs={"order": order, "reason": reason},
        success_validator=lambda packet: packet.get("query_authenticated") is True
        and isinstance(packet.get("provider_response"), dict),
    )
    if not isinstance(provider_result, dict) or provider_result.get("ok") is not True:
        _release_media_refund_reservation(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
            user_id=str(user_id or "") or None,
            reservation=refund_reservation,
        )
        return provider_result if isinstance(provider_result, dict) else _blocked("wechat_pay_provider_response_invalid", http_status=502)
    provider_response = provider_result.get("provider_response") if isinstance(provider_result.get("provider_response"), dict) else {}
    from .billing_wechat_pay import build_wechat_pay_refund_id, reconcile_wechat_pay_refund_result

    result = reconcile_wechat_pay_refund_result(
        repository,
        company_id=normalized_company,
        order_id=normalized_order,
        expected_out_refund_no=build_wechat_pay_refund_id(normalized_order),
        provider_response=provider_response,
        provider_verified=provider_result.get("query_authenticated") is True,
        verification_source="authenticated_refund_request",
        calls_external_payment_api=True,
        triggers_real_refund=True,
    )
    if result.get("status") == "refund_failed":
        _release_media_refund_reservation(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
            user_id=str(user_id or "") or None,
            reservation=refund_reservation,
        )
    return {
        **result,
        "confirmation_id": approval.get("confirmation_id"),
        "executed_by": "approved_backend_refund_boundary" if result.get("ok") else "not_executed",
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def query_and_reconcile_domestic_billing_refund(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_query: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Query one owned refund and reconcile only a signed provider response."""

    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order or order.get("provider") not in DOMESTIC_PAYMENT_PROVIDERS:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if order.get("status") == "refunded":
        return {
            "ok": True,
            "status": "refunded",
            "order_id": normalized_order,
            "provider_query_required": False,
            "calls_external_payment_api": False,
            "triggers_real_refund": False,
            "secret_exposed": False,
        }
    if order.get("status") not in {"refund_review_requested", "refund_processing", "refund_failed"}:
        return _blocked("domestic_refund_query_not_available", http_status=409)
    if order.get("status") == "refund_review_requested":
        approval = _approved_domestic_refund_confirmation(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
        )
        if approval.get("ok") is not True:
            return approval
    if provider_query is None:
        from .billing_wechat_pay import query_wechat_pay_refund_from_env

        provider_query = query_wechat_pay_refund_from_env
    provider_result = _call_and_meter_payment_provider(
        repository,
        company_id=normalized_company,
        user_id=str(order.get("user_id") or "") or None,
        order_id=normalized_order,
        operation="refund_query",
        provider_call=provider_query,
        call_kwargs={"order_id": normalized_order},
        success_validator=lambda packet: packet.get("query_authenticated") is True
        and isinstance(packet.get("provider_response"), dict),
    )
    if not isinstance(provider_result, dict) or provider_result.get("ok") is not True:
        return provider_result if isinstance(provider_result, dict) else _blocked("wechat_pay_provider_response_invalid", http_status=502)
    provider_response = provider_result.get("provider_response") if isinstance(provider_result.get("provider_response"), dict) else {}
    from .billing_wechat_pay import build_wechat_pay_refund_id, reconcile_wechat_pay_refund_result

    return reconcile_wechat_pay_refund_result(
        repository,
        company_id=normalized_company,
        order_id=normalized_order,
        expected_out_refund_no=build_wechat_pay_refund_id(normalized_order),
        provider_response=provider_response,
        provider_verified=provider_result.get("query_authenticated") is True,
        verification_source="authenticated_refund_query",
        calls_external_payment_api=True,
        triggers_real_refund=False,
    )


def _approved_domestic_refund_confirmation(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
) -> dict[str, Any]:
    confirmation_id = _domestic_refund_confirmation_id(order_id)
    confirmation = repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id)
    if not confirmation:
        return _blocked("domestic_refund_confirmation_missing", http_status=409)
    item = confirmation.get("item") if isinstance(confirmation.get("item"), dict) else {}
    order = repository.get_domestic_billing_order(company_id=company_id, order_id=order_id)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    try:
        approved_amount = int(item.get("amount_minor"))
    except (TypeError, ValueError):
        approved_amount = -1
    approval_matches_order = (
        confirmation.get("action_type") == "refund"
        and confirmation.get("store_id") is None
        and confirmation.get("task_id") is None
        and str(confirmation.get("runtime_run_id") or "") == f"billing_refund:{order_id}"
        and str(confirmation.get("default_action") or "") == "hold"
        and str(item.get("source") or "") == "domestic_billing_refund_review"
        and str(item.get("scope") or "") == "account"
        and str(item.get("order_id") or "") == order_id
        and str(item.get("plan_key") or "") == str(order.get("plan_key") or "")
        and approved_amount == int(order.get("amount_minor") or 0)
        and str(item.get("currency") or "").upper() == str(order.get("currency") or "").upper()
        and item.get("full_refund_only") is True
        and item.get("moves_money") is True
        and item.get("approval_does_not_execute") is True
        and item.get("provider_call_pending") is True
    )
    if not approval_matches_order:
        return _blocked("domestic_refund_confirmation_invalid", http_status=409)
    if confirmation.get("status") != "approved":
        return {
            **_blocked("domestic_refund_confirmation_not_approved", http_status=409),
            "confirmation_id": confirmation_id,
            "confirmation_status": str(confirmation.get("status") or "pending"),
        }
    return {"ok": True, "confirmation_id": confirmation_id, "confirmation_status": "approved"}


def _domestic_refund_confirmation_id(order_id: str) -> str:
    digest = hashlib.sha256(f"domestic-refund-confirmation-v1:{str(order_id or '').strip()}".encode("utf-8")).hexdigest()
    return f"confirm_billing_refund_{digest[:24]}"


def _domestic_order_purchase(order: dict[str, Any]) -> tuple[str, int]:
    payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    purchase_type = str(payload.get("purchase_type") or "subscription").strip().lower()
    if purchase_type != "media_points":
        return "subscription", 0
    try:
        points = int(payload.get("media_points") or 0)
    except (TypeError, ValueError):
        points = 0
    return "media_points", max(0, points)


def _release_media_refund_reservation(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    user_id: str | None,
    reservation: dict[str, Any] | None,
) -> None:
    entry = reservation.get("ledger_entry") if isinstance(reservation, dict) else {}
    if not isinstance(entry, dict) or entry.get("status") != "reserved":
        return
    try:
        repository.apply_media_credit_operation(
            company_id=company_id,
            user_id=user_id,
            operation_type="release",
            points=int(entry.get("points") or 0),
            idempotency_key=f"wechat-refund:{order_id}:media-points-release:v1",
            reference_type="billing_refund",
            reference_id=order_id,
            reservation_id=str(entry.get("ledger_id") or ""),
            details={"provider_refund_not_completed": True},
        )
    except (RuntimeError, ValueError):
        return


def _revoke_refunded_media_points(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    user_id: str | None,
    points: int,
) -> dict[str, Any]:
    if points <= 0:
        return _blocked("media_credit_purchase_contract_invalid", http_status=500)
    reservation_entry: dict[str, Any] = {}
    try:
        reservation = repository.apply_media_credit_operation(
            company_id=company_id,
            user_id=user_id,
            operation_type="reserve",
            points=points,
            idempotency_key=f"wechat-refund:{order_id}:media-points-reserve:v1",
            reference_type="billing_refund",
            reference_id=order_id,
            details={"unused_points_required": True, "purchase_type": "media_points"},
        )
        candidate = reservation.get("ledger_entry") if isinstance(reservation, dict) else {}
        reservation_entry = candidate if isinstance(candidate, dict) else {}
    except ValueError:
        reservation_entry = {}

    try:
        result = repository.apply_media_credit_operation(
            company_id=company_id,
            user_id=user_id,
            operation_type="revoke",
            points=points,
            idempotency_key=f"wechat-refund:{order_id}:media-points-revoke:v1",
            reference_type="billing_refund",
            reference_id=order_id,
            reservation_id=str(reservation_entry.get("ledger_id") or "") if reservation_entry.get("status") == "reserved" else "",
            details={"provider_refund_verified": True, "purchase_type": "media_points"},
        )
    except (RuntimeError, ValueError):
        return _blocked("media_credit_refund_revoke_not_applied", http_status=500)
    return {"ok": True, **result}


def inspect_domestic_billing_order_before_query(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
) -> dict[str, Any]:
    """Fail closed until the backend live WeChat query client is enabled."""

    order = repository.get_domestic_billing_order(company_id=str(company_id or "").strip(), order_id=str(order_id or "").strip())
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if order.get("status") in {"paid", "refunded"}:
        return {
            "ok": True,
            "status": str(order["status"]),
            "order_id": str(order["order_id"]),
            "provider_query_required": False,
            "calls_external_payment_api": False,
            "triggers_real_charge": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }
    return {
        **_blocked("wechat_pay_live_order_query_not_enabled", http_status=409),
        "order_id": str(order["order_id"]),
        "provider_query_required": True,
    }


def apply_verified_domestic_refund(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_refund_id: str,
    amount_minor: int,
    currency: str,
    provider_verified: bool,
    verification_source: str = "provider_verified_result",
    calls_external_payment_api: bool = False,
    triggers_real_refund: bool = False,
) -> dict[str, Any]:
    """Apply one confirmed refund under the same company entitlement lock."""

    normalized_company = str(company_id or "").strip()
    if provider_verified is not True:
        return _blocked("domestic_refund_not_provider_verified", http_status=403)
    if not normalized_company:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    with repository.domestic_billing_company_lock(company_id=normalized_company):
        return _apply_verified_domestic_refund_locked(
            repository,
            company_id=normalized_company,
            order_id=order_id,
            provider_refund_id=provider_refund_id,
            amount_minor=amount_minor,
            currency=currency,
            provider_verified=provider_verified,
            verification_source=verification_source,
            calls_external_payment_api=calls_external_payment_api,
            triggers_real_refund=triggers_real_refund,
        )


def _apply_verified_domestic_refund_locked(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_id: str,
    provider_refund_id: str,
    amount_minor: int,
    currency: str,
    provider_verified: bool,
    verification_source: str,
    calls_external_payment_api: bool,
    triggers_real_refund: bool,
) -> dict[str, Any]:
    """Apply a provider-confirmed full refund; this function never initiates it."""

    if provider_verified is not True:
        return _blocked("domestic_refund_not_provider_verified", http_status=403)
    normalized_company = str(company_id or "").strip()
    normalized_order = str(order_id or "").strip()
    normalized_refund = str(provider_refund_id or "").strip()
    order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=normalized_order)
    if not order:
        return _blocked("domestic_billing_order_not_found", http_status=404)
    if not normalized_refund:
        return _blocked("provider_refund_reference_missing", http_status=400)
    if int(amount_minor) != int(order.get("amount_minor") or 0):
        return _blocked("refund_amount_mismatch", http_status=400)
    if str(currency or "").upper() != str(order.get("currency") or "").upper():
        return _blocked("refund_currency_mismatch", http_status=400)
    if order.get("status") not in {"paid", "refund_review_requested", "refund_processing", "refunded"}:
        return _blocked("domestic_billing_order_not_refundable", http_status=409)
    purchase_type, media_points = _domestic_order_purchase(order)
    media_credit_result: dict[str, Any] | None = None
    if purchase_type == "media_points":
        media_credit_result = _revoke_refunded_media_points(
            repository,
            company_id=normalized_company,
            order_id=normalized_order,
            user_id=str(order.get("user_id") or "") or None,
            points=media_points,
        )
        if media_credit_result.get("ok") is not True:
            return media_credit_result
    else:
        try:
            media_credit_result = revoke_plan_media_points(
                repository,
                company_id=normalized_company,
                user_id=str(order.get("user_id") or "") or None,
                order_id=normalized_order,
            )
        except (RuntimeError, ValueError):
            return _blocked("plan_media_credit_revoke_not_applied", http_status=500)
    refund_event_id = hashlib.sha256(f"wechat-refund-v1:{normalized_refund}".encode("utf-8")).hexdigest()
    try:
        updated = repository.update_domestic_billing_order_state(
            company_id=normalized_company,
            order_id=normalized_order,
            status="refunded",
            allowed_current_statuses={"paid", "refund_review_requested", "refund_processing"},
            state_details={
                "provider_refund_reference_hash": refund_event_id,
                "refund_amount_minor": int(amount_minor),
                "refund_currency": str(currency or "").upper(),
                "provider_verified": True,
                "verification_source": str(verification_source or "provider_verified_result"),
                "provider_refund_called_by_this_function": bool(triggers_real_refund),
            },
            audit_action="billing.domestic_refund.verified",
            audit_summary="Provider-confirmed domestic refund closed the billing order.",
            calls_external_payment_api=calls_external_payment_api,
            triggers_real_refund=triggers_real_refund,
        )
    except ValueError:
        return _blocked("domestic_billing_order_not_refundable", http_status=409)
    if not updated:
        return _blocked("domestic_billing_order_not_found", http_status=404)

    if purchase_type == "media_points":
        return {
            "ok": True,
            "status": "refunded",
            "order_id": normalized_order,
            "purchase_type": "media_points",
            "media_points_revoked": media_points,
            "duplicate_refund_result": bool(updated.get("duplicate_transition"))
            or bool(media_credit_result and media_credit_result.get("duplicate_request")),
            "entitlement_unchanged_for_newer_order": True,
            "remaining_paid_entitlement_restored": False,
            "calls_external_payment_api": bool(calls_external_payment_api),
            "triggers_real_refund": bool(triggers_real_refund),
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        }

    subscription = repository.get_billing_subscription(company_id=normalized_company)
    current_order_id = str(subscription.get("provider_subscription_id") or "") if subscription else ""
    entitlement_unchanged = bool(current_order_id and current_order_id != normalized_order)
    entitlement_result: dict[str, Any] | None = None
    fallback: dict[str, Any] | None = None
    if not entitlement_unchanged:
        fallback = _remaining_domestic_entitlement(repository, company_id=normalized_company, excluded_order_id=normalized_order)
        if fallback:
            entitlement_result = repository.apply_billing_webhook_event(
                event={
                    "provider": str(fallback.get("provider") or "wechat_pay_native"),
                    "event_id": f"{refund_event_id}-fallback",
                    "event_type": "payment_succeeded",
                    "supported_event": True,
                    "company_id": normalized_company,
                    "provider_customer_id": "verified_domestic_payment",
                    "provider_subscription_id": str(fallback["order_id"]),
                    "provider_plan_id": f"wechat_native_{fallback['plan_key']}_{fallback['amount_minor']}_{fallback['duration_days']}d",
                    "plan_key": str(fallback["plan_key"]),
                    "subscription_status": "active",
                    "duration_days": int(fallback["duration_days"]),
                    "active_until": str(fallback["active_until"]),
                    "payment_attention_required": False,
                    "quota_recalculation_required": True,
                    "raw_payload_persisted": False,
                    "frontend_gets_payment_secret": False,
                    "secret_exposed": False,
                }
            )
        else:
            entitlement_result = repository.apply_billing_webhook_event(
                event={
                    "provider": str(order.get("provider") or "wechat_pay_native"),
                    "event_id": refund_event_id,
                    "event_type": "refund_succeeded",
                    "supported_event": True,
                    "company_id": normalized_company,
                    "provider_customer_id": "verified_domestic_refund",
                    "provider_subscription_id": normalized_order,
                    "provider_plan_id": f"wechat_native_{order['plan_key']}_{order['amount_minor']}_{order['duration_days']}d",
                    "plan_key": str(order["plan_key"]),
                    "subscription_status": "refunded",
                    "payment_attention_required": False,
                    "quota_recalculation_required": True,
                    "raw_payload_persisted": False,
                    "frontend_gets_payment_secret": False,
                    "secret_exposed": False,
                }
            )
    return {
        "ok": True,
        "status": "refunded",
        "order_id": normalized_order,
        "duplicate_refund_result": bool(updated.get("duplicate_transition")) or bool(entitlement_result and entitlement_result.get("duplicate_event")),
        "entitlement_unchanged_for_newer_order": entitlement_unchanged,
        "remaining_paid_entitlement_restored": bool(not entitlement_unchanged and fallback),
        "media_points_revoked": int((media_credit_result or {}).get("points_revoked") or 0),
        "calls_external_payment_api": bool(calls_external_payment_api),
        "triggers_real_refund": bool(triggers_real_refund),
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _remaining_domestic_entitlement(
    repository: SaaSRepository,
    *,
    company_id: str,
    excluded_order_id: str,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    candidates: list[dict[str, Any]] = []
    for item in repository.list_domestic_billing_orders(company_id=company_id, limit=100):
        if str(item.get("order_id") or "") == excluded_order_id or item.get("status") not in {"paid", "refund_review_requested"}:
            continue
        if _domestic_order_purchase(item)[0] != "subscription":
            continue
        payload = item.get("order") if isinstance(item.get("order"), dict) else {}
        payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
        active_until_text = str(payment.get("entitlement_active_until") or "").strip()
        if not active_until_text:
            continue
        try:
            active_until = datetime.fromisoformat(active_until_text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if active_until.tzinfo is None:
            active_until = active_until.replace(tzinfo=timezone.utc)
        if active_until <= now:
            continue
        candidates.append({**item, "active_until": active_until.astimezone(timezone.utc).replace(microsecond=0).isoformat()})
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("active_until") or ""))


def build_domestic_billing_operations_snapshot(
    repository: SaaSRepository,
    *,
    company_id: str,
    now: datetime | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Build a tenant-scoped payment operations view without provider calls."""

    normalized_company = str(company_id or "").strip()
    current = _normalized_utc_datetime(now or datetime.now(timezone.utc))
    orders = repository.list_domestic_billing_orders(company_id=normalized_company, limit=max(1, min(int(limit), 100)))
    subscription = repository.get_billing_subscription(company_id=normalized_company) or {}
    subscription_payload = subscription.get("subscription") if isinstance(subscription.get("subscription"), dict) else {}
    subscription_active_until = _parse_billing_time(subscription_payload.get("active_until"))
    entitlement_active = subscription.get("entitlement_active") is True and (
        subscription_active_until is None or subscription_active_until > current
    )
    status_counts: dict[str, int] = {}
    incidents: list[dict[str, Any]] = []

    for order in orders:
        status = str(order.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        order_id = str(order.get("order_id") or "")
        if status == "pending_payment" and _billing_time_is_at_or_before(order.get("expires_at"), current):
            incidents.append(
                _billing_operations_incident(
                    order_id=order_id,
                    code="checkout_expired",
                    status=status,
                    severity="attention",
                    next_action="create_new_checkout",
                )
            )
            continue
        if status == "paid":
            if _domestic_order_purchase(order)[0] == "media_points":
                continue
            expected_until = _billing_order_entitlement_until(order)
            entitlement_covers_order = bool(
                expected_until is not None
                and subscription_active_until is not None
                and subscription_active_until >= expected_until
                and (entitlement_active or expected_until <= current)
            )
            if not entitlement_covers_order:
                incidents.append(
                    _billing_operations_incident(
                        order_id=order_id,
                        code="paid_entitlement_recovery_required",
                        status=status,
                        severity="critical",
                        next_action="recover_verified_entitlement",
                    )
                )
            continue
        if status == "refund_review_requested":
            updated_at = _parse_billing_time(order.get("updated_at"))
            overdue = bool(updated_at and current - updated_at >= timedelta(hours=DOMESTIC_REFUND_REVIEW_TARGET_HOURS))
            incidents.append(
                _billing_operations_incident(
                    order_id=order_id,
                    code="refund_review_overdue" if overdue else "refund_review_pending",
                    status=status,
                    severity="critical" if overdue else "attention",
                    next_action="complete_human_refund_review",
                )
            )
            continue
        if status == "refund_processing":
            incidents.append(
                _billing_operations_incident(
                    order_id=order_id,
                    code="refund_provider_processing",
                    status=status,
                    severity="attention",
                    next_action="query_provider_refund_status",
                )
            )
            continue
        if status == "refund_failed":
            incidents.append(
                _billing_operations_incident(
                    order_id=order_id,
                    code="refund_provider_followup_required",
                    status=status,
                    severity="critical",
                    next_action="verify_refund_with_provider",
                )
            )

    incident_counts: dict[str, int] = {}
    for incident in incidents:
        code = str(incident.get("code") or "unknown")
        incident_counts[code] = incident_counts.get(code, 0) + 1
    return {
        "status": "attention_required" if incidents else "healthy" if orders else "no_orders",
        "generated_at": current.replace(microsecond=0).isoformat(),
        "order_count": len(orders),
        "status_counts": status_counts,
        "action_required_count": len(incidents),
        "critical_count": sum(1 for item in incidents if item.get("severity") == "critical"),
        "incident_counts": incident_counts,
        "incidents": incidents,
        "entitlement_active": entitlement_active,
        "provider_query_performed": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "tenant_scoped": True,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def reconcile_domestic_billing_orders(
    repository: SaaSRepository,
    *,
    company_id: str,
    order_ids: list[str],
    query_order: Callable[[SaaSRepository, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile a bounded order batch; it can query but never charge or refund."""

    normalized_company = str(company_id or "").strip()
    normalized_ids: list[str] = []
    for raw_order_id in order_ids if isinstance(order_ids, list) else []:
        order_id = str(raw_order_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", order_id):
            return _blocked("domestic_reconciliation_order_id_invalid", http_status=400)
        if order_id not in normalized_ids:
            normalized_ids.append(order_id)
    if not normalized_ids:
        return _blocked("domestic_reconciliation_orders_required", http_status=400)
    if len(normalized_ids) > DOMESTIC_RECONCILIATION_BATCH_LIMIT:
        return _blocked("domestic_reconciliation_batch_too_large", http_status=400)

    reconcile_one = query_order or _query_domestic_order_for_reconciliation
    results: list[dict[str, Any]] = []
    for order_id in normalized_ids:
        order = repository.get_domestic_billing_order(company_id=normalized_company, order_id=order_id)
        if not order:
            results.append(
                {
                    "ok": False,
                    "order_id": order_id,
                    "status": "not_found",
                    "reason": "domestic_billing_order_not_found",
                    "http_status": 404,
                    "calls_external_payment_api": False,
                }
            )
            continue
        result = reconcile_one(repository, normalized_company, order_id)
        results.append(_merchant_safe_reconciliation_result(order_id=order_id, result=result))

    succeeded = sum(1 for item in results if item.get("ok") is True)
    provider_query_count = sum(1 for item in results if item.get("calls_external_payment_api") is True)
    return {
        "ok": True,
        "status": "completed" if succeeded == len(results) else "partial",
        "requested_count": len(normalized_ids),
        "succeeded_count": succeeded,
        "attention_count": len(results) - succeeded,
        "results": results,
        "batch_limit": DOMESTIC_RECONCILIATION_BATCH_LIMIT,
        "query_only": True,
        "provider_query_count": provider_query_count,
        "calls_external_payment_api": provider_query_count > 0,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "tenant_scoped": True,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _query_domestic_order_for_reconciliation(
    repository: SaaSRepository,
    company_id: str,
    order_id: str,
) -> dict[str, Any]:
    return query_and_reconcile_domestic_billing_order(
        repository,
        company_id=company_id,
        order_id=order_id,
    )


def _merchant_safe_reconciliation_result(*, order_id: str, result: dict[str, Any]) -> dict[str, Any]:
    safe_keys = {
        "ok",
        "status",
        "reason",
        "http_status",
        "entitlement_active",
        "entitlement_recovered",
        "provider_query_required",
        "calls_external_payment_api",
        "duplicate_notification",
    }
    safe = {key: result.get(key) for key in safe_keys if key in result}
    safe.update(
        {
            "order_id": order_id,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "secret_exposed": False,
        }
    )
    return safe


def _billing_operations_incident(
    *,
    order_id: str,
    code: str,
    status: str,
    severity: str,
    next_action: str,
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "code": code,
        "status": status,
        "severity": severity,
        "next_action": next_action,
        "automatic_money_movement": False,
        "secret_exposed": False,
    }


def _billing_order_entitlement_until(order: dict[str, Any]) -> datetime | None:
    if order.get("provider") == "wechat_pay_native":
        from .billing_wechat_pay import _persisted_paid_order_entitlement_window

        window = _persisted_paid_order_entitlement_window(order)
        return _parse_billing_time(window[1]) if window else None
    payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    return _parse_billing_time(payment.get("entitlement_active_until"))


def _billing_time_is_at_or_before(value: Any, current: datetime) -> bool:
    parsed = _parse_billing_time(value)
    return bool(parsed and parsed <= current)


def _parse_billing_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _normalized_utc_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def _normalized_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _call_and_meter_payment_provider(
    repository: SaaSRepository,
    *,
    company_id: str,
    user_id: str | None,
    order_id: str,
    operation: str,
    provider_call: Callable[..., dict[str, Any]],
    call_kwargs: dict[str, Any],
    success_validator: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Run one provider call and append only privacy-safe reliability telemetry."""

    started = time.perf_counter()
    result = provider_call(**call_kwargs)
    duration_ms = int(round((time.perf_counter() - started) * 1000))
    if not isinstance(result, dict) or result.get("calls_external_payment_api") is not True:
        return result
    outcome = "error"
    error_class = "provider_error"
    if result.get("ok") is True:
        valid_success = True
        if success_validator is not None:
            try:
                valid_success = success_validator(result) is True
            except (KeyError, TypeError, ValueError):
                valid_success = False
        if valid_success:
            outcome, error_class = "success", ""
        else:
            error_class = "invalid_response"
    else:
        reason = str(result.get("reason") or "").strip().lower()
        http_status = int(result.get("http_status") or 0)
        if "timeout" in reason or http_status in {408, 504}:
            outcome, error_class = "timeout", "timeout"
        elif "invalid" in reason or "signature" in reason or "mismatch" in reason:
            error_class = "invalid_response"
        elif http_status >= 400:
            error_class = "http_error"
    telemetry = sanitize_provider_telemetry(
        scope="payment",
        outcome=outcome,
        duration_ms=duration_ms,
        error_class=error_class,
    )
    idempotency_key = hashlib.sha256(
        f"payment-provider-call-v1:{company_id}:{order_id}:{operation}:{time.time_ns()}".encode("utf-8")
    ).hexdigest()
    try:
        repository.record_provider_cost(
            company_id=company_id,
            user_id=user_id,
            task_id=None,
            reference_type="payment_provider_call",
            reference_id=order_id,
            cost_category="payment_processing",
            resource_type=operation,
            unit_count=1,
            media_points=0,
            cost_minor=0,
            currency="CNY",
            cost_status="not_applicable",
            idempotency_key=idempotency_key,
            details={
                "telemetry": telemetry,
                "provider_neutral": True,
                "raw_provider_response_stored": False,
            },
        )
    except Exception:
        # Observability must never interrupt a payment, query, close or refund result.
        pass
    return result


def _blocked(reason: str, *, http_status: int) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "reason": reason,
        "http_status": http_status,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
