#!/usr/bin/env python3
"""Regression for pending domain purchase readiness shape."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.domain_readiness import build_domain_readiness  # noqa: E402


OUT = ROOT / "output" / "jiejing-domain-pending-purchase-test"
ENV_KEYS = [
    "JIEJING_SAAS_ENV",
    "JIEJING_SELECTED_DOMAIN",
    "JIEJING_DOMAIN_REGISTRATION_STATUS",
    "JIEJING_PUBLIC_BASE_URL",
    "JIEJING_STABLE_DOMAIN",
    "JIEJING_TARGET_APP_HOST",
    "JIEJING_APP_HOST",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_DOMAIN_DNS_VERIFIED",
    "JIEJING_TLS_VERIFIED",
    "JIEJING_EBAY_CALLBACK_VERIFIED",
    "JIEJING_DEPLOYMENT_HARDENED",
    "JIEJING_SECURITY_HEADERS_VERIFIED",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_pending_env()
    try:
        pending = _build()
        if pending.get("production_domain_ready") is not False:
            return fail("pending domain review must not pass the production domain gate")
        if pending.get("selected_root_domain") != "jiejing.shop":
            return fail(f"selected domain missing: {pending}")
        if pending.get("domain_registration_status") != "registry_name_review_pending":
            return fail(f"registration status missing: {pending}")
        if pending.get("domain_payment_confirmed") is not True:
            return fail("registry-name-review fixture should record payment as confirmed")
        if pending.get("domain_registration_review_pending") is not True:
            return fail("registry-name-review fixture should record the review blocker")
        if pending.get("domain_registered") is not False:
            return fail("pending registry review should not be treated as registered")
        if pending.get("target_app_host") != "app.jiejing.shop":
            return fail(f"target app host should be prepared: {pending.get('target_app_host')}")
        if pending.get("required_callback_url") != "https://app.jiejing.shop/oauth/ebay/callback":
            return fail(f"callback URL should be prepared on the app host: {pending.get('required_callback_url')}")
        for blocker in {"stable_domain_not_selected", "domain_registry_name_review_pending", "domain_registration_not_confirmed", "domain_dns_not_verified", "domain_tls_not_verified"}:
            if blocker not in pending.get("blockers", []):
                return fail(f"pending domain blocker missing: {blocker} from {pending.get('blockers')}")
        records = {item.get("name"): item for item in pending.get("recommended_dns_records", []) if isinstance(item, dict)}
        if not {"@", "app", "api"}.issubset(records):
            return fail(f"recommended DNS records missing: {records}")
        if records["app"].get("configure_now") is not False:
            return fail("pending DNS records must not instruct immediate configuration before purchase")
        serialized = json.dumps(pending, ensure_ascii=False).lower()
        for forbidden in ("access_token", "refresh_token=", "client_secret=", "api_key=", "password="):
            if forbidden in serialized:
                return fail(f"pending domain packet leaked secret-shaped marker: {forbidden}")
    finally:
        _restore_env(previous)

    previous = _set_registered_ready_env()
    try:
        ready = _build()
        if ready.get("production_domain_ready") is not True:
            return fail(f"registered stable domain should pass when all evidence flags are set: {ready.get('blockers')}")
        if ready.get("domain_registered") is not True:
            return fail("registered status should be treated as purchased/active")
    finally:
        _restore_env(previous)

    previous = _set_active_pending_dns_env()
    try:
        active = _build()
        if active.get("domain_registered") is not True:
            return fail("normal Tencent service status should be treated as domain active")
        if active.get("domain_payment_confirmed") is not True:
            return fail("normal Tencent service status should record payment/ownership as confirmed")
        if "domain_registration_not_confirmed" in active.get("blockers", []):
            return fail(f"active domain should not keep registration blocker: {active.get('blockers')}")
        if active.get("production_domain_ready") is not False:
            return fail("active domain without DNS/TLS must still block production domain readiness")
    finally:
        _restore_env(previous)

    output = subprocess.check_output(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_domain_pending_purchase_preflight.py"),
            "--domain",
            "jiejing.shop",
            "--registration-status",
            "registry_name_review_pending",
        ],
        cwd=ROOT,
        text=True,
    )
    parsed = json.loads(output)
    cli_packet = parsed.get("domain_pending_purchase_preflight") or {}
    if cli_packet.get("selected_root_domain") != "jiejing.shop":
        return fail("CLI preflight should print the selected root domain")
    if cli_packet.get("triggers_real_charge") is True:
        return fail("CLI preflight must not expose a real-charge path")
    print("PASS jiejing_domain_pending_purchase_preflight")
    return 0


def _build() -> dict[str, object]:
    settings = SaaSSettings.from_env(db_path=OUT / "saas.sqlite", runtime_db_path=OUT / "runtime.sqlite", output_root=OUT, host="127.0.0.1", port=8788)
    return build_domain_readiness(settings)


def _set_pending_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    _clear_env()
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SELECTED_DOMAIN": "jiejing.shop",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "registry_name_review_pending",
        }
    )
    return previous


def _set_active_pending_dns_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    _clear_env()
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SELECTED_DOMAIN": "jiejing.shop",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "normal",
        }
    )
    return previous


def _set_registered_ready_env() -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    _clear_env()
    stable = "https://app.jiejing.shop"
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "staging",
            "JIEJING_SELECTED_DOMAIN": "jiejing.shop",
            "JIEJING_DOMAIN_REGISTRATION_STATUS": "registered",
            "JIEJING_PUBLIC_BASE_URL": stable,
            "JIEJING_STABLE_DOMAIN": "app.jiejing.shop",
            "JIEJING_CORS_ORIGIN": stable,
            "JIEJING_DOMAIN_DNS_VERIFIED": "1",
            "JIEJING_TLS_VERIFIED": "1",
            "JIEJING_EBAY_CALLBACK_VERIFIED": "1",
            "JIEJING_DEPLOYMENT_HARDENED": "1",
            "JIEJING_SECURITY_HEADERS_VERIFIED": "1",
        }
    )
    return previous


def _clear_env() -> None:
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _restore_env(previous: dict[str, str | None]) -> None:
    _clear_env()
    for key, value in previous.items():
        if value is not None:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
