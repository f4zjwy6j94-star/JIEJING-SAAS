#!/usr/bin/env python3
"""Regression for the backend-only eBay Vault-backed token refresh adapter."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_token_refresh_adapter import (  # noqa: E402
    EbayVaultTokenRefreshAdapter,
    build_ebay_token_refresh_adapter_status,
    public_token_refresh_result,
)
from jiejing_saas.vault_secret_resolver import VaultSecretResolver  # noqa: E402


OUT = ROOT / "output" / "jiejing-ebay-vault-token-refresh-adapter-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    previous = _set_env()
    try:
        settings = SaaSSettings.from_env(
            db_path=OUT / "saas.sqlite",
            runtime_db_path=OUT / "runtime.sqlite",
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        secret_ref = {
            "secret_ref": "secret_ebay_refresh_unit",
            "company_id": "company_unit",
            "store_id": "store_unit",
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "local_development_secret_stored",
        }
        stored = VaultSecretResolver(settings).store_secret(
            secret_ref=secret_ref,
            secret_value="EBAY-REFRESH-TOKEN-MUST-NOT-LEAK",
            created_by="unit",
        )
        if stored.get("status") not in {"ready", "stored"}:
            return fail(f"local resolver should store refresh token for internal adapter test: {stored}")

        seen: dict[str, Any] = {"calls": 0, "body": ""}

        def fake_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            seen["calls"] += 1
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["authorization_header_present"] = bool(request.headers.get("Authorization"))
            body = request.data.decode("utf-8") if request.data else ""
            seen["body"] = body
            if "EBAY-REFRESH-TOKEN-MUST-NOT-LEAK" not in body:
                return 400, {"content-type": "application/json"}, b'{"error":"missing_refresh"}'
            return (
                200,
                {"content-type": "application/json"},
                b'{"access_token":"EBAY-ACCESS-TOKEN-MUST-NOT-LEAK","expires_in":7200,"token_type":"Bearer"}',
            )

        status = build_ebay_token_refresh_adapter_status(settings)
        if status.get("status") != "ready":
            return fail(f"adapter status should be ready in local resolver test: {status}")
        adapter = EbayVaultTokenRefreshAdapter(settings, transport=fake_transport)
        private_result = adapter.refresh_access_token_from_secret_ref(
            secret_ref=secret_ref,
            company_id="company_unit",
            store_id="store_unit",
            task_scope="unit_read_only_sync",
        )
        if private_result.get("ok") is not True or private_result.get("access_token") != "EBAY-ACCESS-TOKEN-MUST-NOT-LEAK":
            return fail(f"internal adapter should mint an access token for backend callers: {private_result}")
        public_result = public_token_refresh_result(private_result)
        public_serialized = json.dumps({"status": status, "public": public_result}, ensure_ascii=False)
        for forbidden in (
            "EBAY-ACCESS-TOKEN-MUST-NOT-LEAK",
            "EBAY-REFRESH-TOKEN-MUST-NOT-LEAK",
            "EBAY-CLIENT-SECRET-MUST-NOT-LEAK",
        ):
            if forbidden in public_serialized:
                return fail(f"public refresh output leaked forbidden marker: {forbidden}")
        if public_result.get("access_token_returned_to_frontend") is not False or public_result.get("secret_ref_present") is not True:
            return fail(f"public refresh result should expose only safe evidence: {public_result}")
        if seen.get("calls") != 1 or seen.get("method") != "POST" or seen.get("authorization_header_present") is not True:
            return fail(f"adapter should perform exactly one backend POST with auth header: {seen}")
        print("PASS jiejing_ebay_vault_token_refresh_adapter")
        return 0
    finally:
        _restore_env(previous)


def _set_env() -> dict[str, str | None]:
    keys = [
        "JIEJING_SAAS_ENV",
        "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED",
        "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH",
        "JIEJING_EBAY_CLIENT_ID",
        "JIEJING_EBAY_CLIENT_SECRET",
        "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
        "JIEJING_EBAY_OAUTH_ENV",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(
        {
            "JIEJING_SAAS_ENV": "local_dev",
            "JIEJING_VAULT_LOCAL_SECRET_RESOLVER_ENABLED": "1",
            "JIEJING_VAULT_LOCAL_SECRET_STORE_PATH": str(OUT / "local-secret-store.json"),
            "JIEJING_EBAY_CLIENT_ID": "ebay-client-unit",
            "JIEJING_EBAY_CLIENT_SECRET": "EBAY-CLIENT-SECRET-MUST-NOT-LEAK",
            "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "1",
            "JIEJING_EBAY_OAUTH_ENV": "production",
        }
    )
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
