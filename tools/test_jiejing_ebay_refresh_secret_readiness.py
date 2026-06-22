#!/usr/bin/env python3
"""Regression for eBay OAuth refresh secret readiness evidence."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository, SaaSSettings, build_product_readiness  # noqa: E402


OUT = ROOT / "output" / "jiejing-ebay-refresh-secret-readiness-test"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    repo = SaaSRepository(SAAS_DB, database_engine="sqlite", database_url="")
    account = repo.create_user_with_company(
        email="oauth-ready@example.com",
        password="local-test-password",
        company_name="OAuth Ready Merchant",
    )
    user = account["user"]
    company = account["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "oauth-ready-store", "marketplace": "EBAY_US"},
    )
    secret_ref = repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={
            "credential_owner": "jiejing_saas_backend",
            "token_values_returned_to_public_response": False,
            "refresh_token_stored_in_database": False,
        },
    )
    repo.create_platform_connection(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "read_only_authorized",
            "purpose": "ebay_refresh_token",
            "secret_ref": secret_ref["secret_ref"],
            "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            "metadata": {"credential_source": "jiejing_vault_secret_ref"},
        },
    )

    evidence = repo.product_readiness_evidence()
    if evidence.get("read_only_authorized_connections") != 1:
        return fail("readiness evidence should count the authorized eBay connection")
    if evidence.get("ebay_secret_refs") != 1:
        return fail("managed_vault_stored eBay refresh secret_ref should count as active readiness evidence")
    if evidence.get("ebay_token_refresh_success_count") != 0:
        return fail("new repositories should not invent a successful eBay token refresh proof")
    if evidence.get("secret_exposed") is not False:
        return fail("readiness evidence must not expose secrets")

    old_env = os.environ.copy()
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_SAAS_SESSION_SECRET": "oauth-refresh-readiness-secret-long-enough",
                "JIEJING_CORS_ORIGIN": "https://staging.example.com",
                "JIEJING_VAULT_ENABLED": "1",
                "JIEJING_VAULT_PROVIDER": "vault",
                "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "1",
                "JIEJING_VAULT_ADDR": "https://vault.example.test",
                "JIEJING_VAULT_TOKEN": "unit-vault-token",
                "JIEJING_VAULT_KEYSPACE": "jiejing-refresh-test",
                "JIEJING_EBAY_CLIENT_ID": "test-client-id",
                "JIEJING_EBAY_CLIENT_SECRET": "test-client-secret",
                "JIEJING_EBAY_RU_NAME": "test-ru-name",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "1",
            }
        )
        settings = SaaSSettings.from_env(
            db_path=SAAS_DB,
            runtime_db_path=RUNTIME_DB,
            output_root=OUT,
            host="127.0.0.1",
            port=8788,
        )
        readiness = build_product_readiness(settings, repo)
        repo.write_audit(
            company_id=company["company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            actor_type="system",
            action_type="oauth.token_refresh.executed",
            target_type="store",
            target_id=store["store_id"],
            summary="eBay access token refresh executed through backend Vault-backed adapter. Token values were not returned or stored.",
            details={
                "ok": True,
                "status": "refreshed",
                "source": "backend_vault_secret_ref_refresh",
                "secret_ref_present": True,
                "access_token_returned_to_frontend": False,
                "access_token_returned_to_runtime": False,
                "refresh_token_returned_to_frontend": False,
                "secret_exposed": False,
            },
        )
        readiness_after_probe = build_product_readiness(settings, repo)
    finally:
        os.environ.clear()
        os.environ.update(old_env)

    items = {item.get("key"): item for item in readiness.get("items") or []}
    token_refresh = items.get("ebay_token_refresh") or {}
    if token_refresh.get("status") != "refresh_adapter_probe_pending":
        return fail(f"eBay token refresh should require a successful refresh probe before ready, got {token_refresh.get('status')}")
    if token_refresh.get("severity") != "warning":
        return fail("pending token refresh proof should stay visible as a readiness warning")
    if readiness.get("product_evidence", {}).get("ebay_secret_refs") != 1:
        return fail("product readiness should expose the corrected eBay secret_ref count")
    after_items = {item.get("key"): item for item in readiness_after_probe.get("items") or []}
    after_token_refresh = after_items.get("ebay_token_refresh") or {}
    if after_token_refresh.get("status") != "vault_backed_refresh_adapter_ready":
        return fail(f"successful refresh audit should clear token refresh readiness, got {after_token_refresh.get('status')}")
    if readiness_after_probe.get("product_evidence", {}).get("ebay_token_refresh_success_count") != 1:
        return fail("product evidence should count successful eBay token refresh probes")
    serialized = str({"before": readiness, "after": readiness_after_probe})
    if "test-client-secret" in serialized or "unit-vault-token" in serialized or "refresh_token=" in serialized.lower():
        return fail("readiness response should not leak client secret or refresh token values")

    print("PASS jiejing_ebay_refresh_secret_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
