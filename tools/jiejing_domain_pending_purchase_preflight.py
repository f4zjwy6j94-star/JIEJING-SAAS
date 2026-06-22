#!/usr/bin/env python3
"""Build a no-secret domain purchase preparation packet for Jiejing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.domain_readiness import build_domain_readiness  # noqa: E402


ENV_KEYS = [
    "JIEJING_SELECTED_DOMAIN",
    "JIEJING_DOMAIN_REGISTRATION_STATUS",
    "JIEJING_PUBLIC_BASE_URL",
    "JIEJING_STABLE_DOMAIN",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_DOMAIN_DNS_VERIFIED",
    "JIEJING_TLS_VERIFIED",
    "JIEJING_EBAY_CALLBACK_VERIFIED",
    "JIEJING_DEPLOYMENT_HARDENED",
    "JIEJING_SECURITY_HEADERS_VERIFIED",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Jiejing domain cutover evidence before final DNS/WAF cutover.")
    parser.add_argument("--domain", default=os.environ.get("JIEJING_SELECTED_DOMAIN", "jiejing.shop"), help="Root domain being reviewed or purchased.")
    parser.add_argument(
        "--registration-status",
        default=os.environ.get("JIEJING_DOMAIN_REGISTRATION_STATUS", "registered"),
        help="Current domain state, for example registry_name_review_pending or registered.",
    )
    args = parser.parse_args()

    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    try:
        os.environ["JIEJING_SELECTED_DOMAIN"] = args.domain.strip().lower()
        os.environ["JIEJING_DOMAIN_REGISTRATION_STATUS"] = args.registration_status.strip().lower()
        os.environ.setdefault("JIEJING_CORS_ORIGIN", "")
        settings = SaaSSettings.from_env(
            db_path=ROOT / "output" / "jiejing-domain-pending-purchase" / "saas.sqlite",
            runtime_db_path=ROOT / "output" / "jiejing-domain-pending-purchase" / "runtime.sqlite",
            output_root=ROOT / "output" / "jiejing-domain-pending-purchase",
            host="127.0.0.1",
            port=8788,
        )
        packet = build_domain_readiness(settings)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print(json.dumps({"domain_pending_purchase_preflight": packet}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
