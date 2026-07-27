#!/usr/bin/env python3
"""Historical eBay packets must not prove the current seller connection."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import SaaSRepository, SaaSSettings, build_product_readiness  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402


OUT = ROOT / "output" / "jiejing-historical-ebay-readiness-test"
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
        email="historical-ebay@example.com",
        password="local-test-password",
        company_name="Historical eBay Packet Test",
    )
    user = account["user"]
    company = account["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "archived-seller", "marketplace": "EBAY_US"},
    )
    repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "packet_cached_sanitized",
            "present_resource_keys": ["store_profile", "account_business_policies"],
            "missing_resource_keys": [],
            "secret_exposed": False,
        },
    )

    evidence = repo.product_readiness_evidence()
    if evidence.get("latest_ebay_packet_current_connection") is not False:
        return fail("an archived packet without a matching active connection must not be current evidence")
    if evidence.get("historical_ebay_packet_present") is not True:
        return fail("the archived packet should remain visible as historical evidence")

    settings = SaaSSettings.from_env(
        db_path=SAAS_DB,
        runtime_db_path=RUNTIME_DB,
        output_root=OUT,
        host="127.0.0.1",
        port=8788,
    )
    readiness = build_product_readiness(settings, repo)
    items = {item.get("key"): item for item in readiness.get("items") or []}
    forbidden_current_statuses = {
        "official_read_completed",
        "official_packet_reports_confirmations",
        "official_packet_ready",
        "packet_backed_gate_ready",
        "official_policy_packet_ready",
    }
    for key in (
        "ebay_read_only_adapter",
        "real_saas_loop_evidence",
        "ebay_read",
        "account_health_incident_mode",
        "ebay_business_policies",
    ):
        status = str((items.get(key) or {}).get("status") or "")
        if status in forbidden_current_statuses:
            return fail(f"historical packet incorrectly made {key} current-ready: {status}")

    public_summary = SaaSBackendHandler._public_readiness_summary(readiness, authenticated=False)
    public_evidence = public_summary.get("product_evidence") or {}
    if public_evidence.get("latest_ebay_packet_status") != "historical_packet_archived_not_current":
        return fail(f"public readiness must label archived evidence honestly: {public_evidence}")
    if public_evidence.get("latest_ebay_packet_source_mode") != "historical_archived":
        return fail("public readiness must not present the archived packet as a current official API sync")
    if public_evidence.get("latest_ebay_packet_present_resource_keys"):
        return fail("public readiness must not expose historical resources as current seller coverage")
    if public_evidence.get("latest_ebay_packet_current_connection") is not False:
        return fail("public readiness must expose that the historical packet is not current")

    secret_ref = repo.create_secret_reference(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        provider="ebay",
        purpose="ebay_refresh_token",
        status="managed_vault_stored",
        metadata={"credential_owner": "jiejing_saas_backend", "secret_exposed": False},
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
    current_evidence = repo.product_readiness_evidence()
    if current_evidence.get("latest_ebay_packet_current_connection") is not True:
        return fail("a packet with a matching active store connection and Vault secret_ref should be current")
    if current_evidence.get("historical_ebay_packet_present") is not False:
        return fail("current packet evidence must not remain labelled historical")
    current_readiness = build_product_readiness(settings, repo)
    current_public = SaaSBackendHandler._public_readiness_summary(current_readiness, authenticated=False)
    current_public_evidence = current_public.get("product_evidence") or {}
    if current_public_evidence.get("latest_ebay_packet_source_mode") != "official_api":
        return fail("current official packet source should remain visible after the connection is proven")
    if "store_profile" not in (current_public_evidence.get("latest_ebay_packet_present_resource_keys") or []):
        return fail("current official packet resources should remain visible")

    serialized = str({"historical": public_summary, "current": current_public})
    if "local-test-password" in serialized or "managed_vault_stored:" in serialized:
        return fail("readiness summaries must not expose credentials")

    print("PASS jiejing_historical_ebay_readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
