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
        "signed_read_only_query_accepted": (
            result.get("reason") == "wechat_pay_provider_rejected_request"
            and result.get("provider_code") == "ORDER_NOT_EXIST"
            and result.get("calls_external_payment_api") is True
            and result.get("provider_response_signature_verified") is True
        ),
        "creates_payable_order": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }
    if result.get("reason") == "wechat_pay_transport_unavailable":
        tls_ready, error_type = _official_tls_probe()
        summary["official_tls_ready"] = tls_ready
        summary["network_error_type"] = error_type
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["signed_read_only_query_accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
