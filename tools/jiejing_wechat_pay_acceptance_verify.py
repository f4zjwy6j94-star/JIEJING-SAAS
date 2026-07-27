#!/usr/bin/env python3
"""Verify one controlled WeChat Pay acceptance order without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import query_and_reconcile_domestic_billing_order  # noqa: E402
from jiejing_saas.billing_plan import build_billing_usage  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one controlled WeChat Pay acceptance order")
    parser.add_argument("--account-email", required=True)
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--reconcile", action="store_true")
    args = parser.parse_args()

    settings = SaaSSettings.from_env(
        db_path=Path(os.environ.get("JIEJING_SAAS_DB_PATH") or "/data/saas.sqlite"),
        runtime_db_path=Path(os.environ.get("JIEJING_RUNTIME_DB_PATH") or "/data/runtime.sqlite"),
        output_root=Path(os.environ.get("JIEJING_OUTPUT_ROOT") or "/data/output"),
        host="127.0.0.1",
        port=8788,
    )
    repository = SaaSRepository(
        settings.db_path,
        database_engine=settings.database_engine,
        database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
    )
    repository.initialize()

    user = repository.get_user_by_email(str(args.account_email).strip().lower())
    company_id = str((user or {}).get("default_company_id") or "")
    if not user or not company_id:
        print(json.dumps(_blocked("account_not_found"), ensure_ascii=False, sort_keys=True))
        return 2

    order = repository.get_domestic_billing_order(company_id=company_id, order_id=str(args.order_id).strip())
    if not order:
        print(json.dumps(_blocked("order_not_found"), ensure_ascii=False, sort_keys=True))
        return 2

    reconciliation: dict[str, Any] = {
        "attempted": False,
        "ok": True,
        "status": "not_required" if order.get("status") in {"paid", "refunded"} else "not_requested",
    }
    if args.reconcile and order.get("status") == "pending_payment":
        os.environ["JIEJING_WECHAT_PAY_LIVE_API_ENABLED"] = "true"
        result = query_and_reconcile_domestic_billing_order(
            repository,
            company_id=company_id,
            order_id=str(args.order_id).strip(),
        )
        reconciliation = {
            "attempted": True,
            "ok": result.get("ok") is True,
            "status": str(result.get("status") or "blocked"),
            "reason": str(result.get("reason") or ""),
            "calls_external_payment_api": result.get("calls_external_payment_api") is True,
        }
        order = repository.get_domestic_billing_order(company_id=company_id, order_id=str(args.order_id).strip()) or order

    subscription = repository.get_billing_subscription(company_id=company_id) or {}
    usage = build_billing_usage(settings, repository, company_id=company_id)
    order_payload = order.get("order") if isinstance(order.get("order"), dict) else {}
    payment = order_payload.get("payment") if isinstance(order_payload.get("payment"), dict) else {}
    audit_logs = repository.list_audit_logs(company_id=company_id, limit=100)
    relevant_audits = [
        item
        for item in audit_logs
        if str(item.get("target_id") or "") == str(args.order_id).strip()
        or str(item.get("action_type") or "").startswith("billing.webhook")
    ]
    audit_actions = sorted({str(item.get("action_type") or "") for item in relevant_audits if item.get("action_type")})

    public_subscription = usage.get("subscription") if isinstance(usage.get("subscription"), dict) else {}
    plan = usage.get("plan") if isinstance(usage.get("plan"), dict) else {}
    quota_status = usage.get("quota_status") if isinstance(usage.get("quota_status"), list) else []
    result = {
        "ok": order.get("status") == "paid" and bool(subscription.get("entitlement_active")),
        "account_found": True,
        "order": {
            "found": True,
            "status": str(order.get("status") or ""),
            "amount_minor": int(order.get("amount_minor") or 0),
            "currency": str(order.get("currency") or ""),
            "plan_key": str(order.get("plan_key") or ""),
            "provider_transaction_present": bool(order.get("provider_order_id"))
            or payment.get("provider_transaction_present") is True,
            "paid_at_present": bool(order.get("paid_at")),
        },
        "payment_verification": {
            "signature_verified": payment.get("signature_verified") is True,
            "amount_verified": payment.get("amount_verified") is True,
            "appid_verified": payment.get("appid_verified") is True,
            "mchid_verified": payment.get("mchid_verified") is True,
            "verification_source": str(payment.get("verification_source") or ""),
            "raw_callback_persisted": order_payload.get("raw_callback_persisted") is True,
            "raw_signature_persisted": order_payload.get("raw_signature_persisted") is True,
        },
        "subscription": {
            "status": str(subscription.get("status") or "missing"),
            "entitlement_active": subscription.get("entitlement_active") is True,
            "payment_attention_required": subscription.get("payment_attention_required") is True,
            "plan_key": str(subscription.get("plan_key") or ""),
            "provider_subscription_present": bool(subscription.get("provider_subscription_id")),
        },
        "usage": {
            "effective_plan_key": str(plan.get("key") or ""),
            "entitlement_active": public_subscription.get("entitlement_active") is True,
            "quota_enforcement_enabled": usage.get("quota_enforcement_enabled") is True,
            "blocked_units": list(usage.get("blocked_units") or []),
            "quota_status": [
                {
                    "unit": str(item.get("unit") or ""),
                    "used": int(item.get("used") or 0),
                    "limit": int(item.get("limit") or 0),
                    "remaining": int(item.get("remaining") or 0),
                    "would_block_next_unit": item.get("would_block_next_unit") is True,
                }
                for item in quota_status
                if isinstance(item, dict)
            ],
        },
        "audit": {
            "payment_verified": "billing.domestic_order.payment_verified" in audit_actions,
            "actions": audit_actions,
        },
        "reconciliation": reconciliation,
        "creates_new_order": False,
        "triggers_refund": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "reason": reason,
        "creates_new_order": False,
        "triggers_refund": False,
        "secret_exposed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
