#!/usr/bin/env python3
"""Create one owner-approved one-CNY WeChat Pay Native acceptance checkout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.billing_domestic import (  # noqa: E402
    CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL,
    create_controlled_wechat_pay_acceptance_order,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Controlled one-CNY WeChat Pay acceptance checkout")
    parser.add_argument("--account-email", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--code-url-output", type=Path, required=True)
    parser.add_argument("--approve-one-cny-real-order", action="store_true")
    args = parser.parse_args()
    if not args.approve_one_cny_real_order:
        print(json.dumps(_blocked("real_payment_owner_approval_required"), ensure_ascii=False, sort_keys=True))
        return 2

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

    # These flags live only in this one-shot process. The public SaaS service
    # remains no-charge and continues to report charge_now_allowed=false.
    os.environ["JIEJING_WECHAT_PAY_LIVE_API_ENABLED"] = "true"
    os.environ["JIEJING_WECHAT_PAY_CHARGE_ALLOWED"] = "true"
    result = create_controlled_wechat_pay_acceptance_order(
        repository,
        account_email=args.account_email,
        approval_phrase=CONTROLLED_WECHAT_PAY_ACCEPTANCE_APPROVAL,
        idempotency_key=args.idempotency_key,
    )
    code_url = str(result.get("code_url") or "").strip()
    if result.get("ok") is not True or not code_url.startswith("weixin://"):
        print(json.dumps(_public_summary(result), ensure_ascii=False, sort_keys=True))
        return 1

    output_path = args.code_url_output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code_url, encoding="utf-8")
    try:
        output_path.chmod(0o600)
    except OSError:
        pass
    summary = _public_summary(result)
    summary["code_url_written"] = True
    summary["public_checkout_enabled"] = False
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _public_summary(result: dict) -> dict:
    return {
        "ok": result.get("ok") is True,
        "status": result.get("status") or "blocked",
        "reason": result.get("reason") or "",
        "order_id": result.get("order_id") or "",
        "amount_minor": result.get("amount_minor") or 0,
        "currency": result.get("currency") or "",
        "duplicate_request": bool(result.get("duplicate_request")),
        "creates_payable_order": result.get("status") == "payable_order_created",
        "triggers_real_charge": False,
        "secret_exposed": False,
    }


def _blocked(reason: str) -> dict:
    return {
        "ok": False,
        "status": "blocked",
        "reason": reason,
        "creates_payable_order": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
