#!/usr/bin/env python3
"""Verify WeChat Pay signing with a read-only query for a nonexistent order."""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_wechat_pay import query_wechat_pay_order_from_env
from jiejing_saas.config import SaaSSettings
from jiejing_saas.repository import SaaSRepository


def _signed_read_only_query_accepted(result: dict[str, object]) -> bool:
    return bool(
        result.get("reason") == "wechat_pay_provider_rejected_request"
        and result.get("provider_code") == "ORDER_NOT_EXIST"
        and result.get("calls_external_payment_api") is True
        and result.get("provider_response_signature_verified") is True
    )


def record_provider_connection_proof(
    repository: SaaSRepository,
    *,
    company_id: str,
    result: dict[str, object],
) -> bool:
    """Persist only a value-free provider proof after an exact signed response."""

    if not company_id or not _signed_read_only_query_accepted(result):
        return False
    repository.write_audit(
        company_id=company_id,
        user_id=None,
        action_type="billing.wechat_pay.provider_connection.proven",
        target_type="billing_provider",
        target_id="wechat_pay_native",
        summary="WeChat Pay provider connection proven by signed read-only query",
        details={
            "contract_version": "2026-08-21-wechat-pay-provider-connection-proof-v1",
            "provider": "wechat_pay_native",
            "query_authenticated": True,
            "provider_query_accepted": True,
            "provider_response_signature_verified": True,
            "provider_order_found": False,
            "calls_external_payment_api": True,
            "creates_payable_order": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "public_charging_allowed": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        },
        actor_type="platform_internal_admin",
    )
    evidence = repository.domestic_payment_provider_connection_evidence()
    return evidence.get("provider_connection_proof_ready") is True


def _official_tls_probe() -> tuple[bool, str]:
    try:
        with socket.create_connection(("api.mch.weixin.qq.com", 443), timeout=5) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname="api.mch.weixin.qq.com"):
                return True, ""
    except Exception as exc:
        return False, type(exc).__name__[:64]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-read-only-provider-query", action="store_true")
    parser.add_argument("--record-provider-connection-proof", action="store_true")
    args = parser.parse_args()
    if not args.allow_read_only_provider_query:
        return 2

    order_id = f"JJVERIFY{uuid.uuid4().hex[:24]}"
    os.environ["JIEJING_WECHAT_PAY_LIVE_API_ENABLED"] = "true"
    result = query_wechat_pay_order_from_env(order_id=order_id)
    summary = {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "provider_code": result.get("provider_code"),
        "signed_read_only_query_accepted": _signed_read_only_query_accepted(result),
        "creates_payable_order": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }
    if result.get("reason") == "wechat_pay_transport_unavailable":
        tls_ready, error_type = _official_tls_probe()
        summary["official_tls_ready"] = tls_ready
        summary["network_error_type"] = error_type
    if args.record_provider_connection_proof:
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
        company_ids = repository.list_domestic_billing_company_ids(limit=1)
        proof_recorded = bool(
            company_ids
            and record_provider_connection_proof(
                repository,
                company_id=company_ids[0],
                result=result,
            )
        )
        summary["provider_connection_proof_recorded"] = proof_recorded
        summary["provider_connection_proof_ready"] = proof_recorded
        if not proof_recorded:
            summary["proof_reason"] = (
                "controlled_billing_company_not_found"
                if not company_ids
                else "signed_provider_query_not_accepted"
            )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["signed_read_only_query_accepted"] and (
        not args.record_provider_connection_proof
        or summary.get("provider_connection_proof_recorded") is True
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
