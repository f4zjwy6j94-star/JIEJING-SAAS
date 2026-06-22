#!/usr/bin/env python3
"""Regression for safe eBay secret_ref metadata recovery from SSM payloads."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402
from tools.jiejing_recover_ebay_secret_refs_from_ssm import (  # noqa: E402
    _apply_recovery,
    _candidate_from_payload,
)


OUT = ROOT / "output" / "jiejing-recover-ebay-secret-refs-test"
SECRET_MARKER = "REFRESH_TOKEN_MUST_NOT_LEAK"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    candidate = _candidate_from_payload(
        secret_name="jiejing-company-store-ebay_refresh_token-secret_abc123",
        payload={
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "secret_ref": "secret_abc123",
            "refresh_token": SECRET_MARKER,
            "metadata": {
                "scopes": ["https://api.ebay.com/oauth/api_scope/sell.account.readonly"],
            },
        },
    )
    if not candidate:
        return fail("expected eBay refresh-token payload to be classified as a recovery candidate")
    serialized_candidate = json.dumps(candidate, ensure_ascii=False)
    if SECRET_MARKER in serialized_candidate:
        return fail("candidate output must not include the raw refresh token")
    if candidate.get("purpose") != "ebay_refresh_token" or candidate.get("provider") != "ebay":
        return fail("candidate should normalize provider/purpose for eBay refresh token")

    repo = SaaSRepository(OUT / "saas.sqlite", database_engine="sqlite", database_url="")
    account = repo.create_user_with_company(
        email="recover-ebay-secret@example.com",
        password="local-password",
        company_name="Recover eBay Secret Test",
    )
    user = account["user"]
    company = account["company"]
    store = repo.create_store(
        company_id=company["company_id"],
        user_id=user["user_id"],
        payload={"platform": "ebay", "store_name": "recover-test-store", "marketplace": "EBAY_US"},
    )
    packet = repo.create_platform_data_packet(
        company_id=company["company_id"],
        store_id=store["store_id"],
        user_id=user["user_id"],
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "packet_cached_sanitized",
            "present_resource_keys": ["store_profile"],
            "missing_resource_keys": [],
            "secret_exposed": False,
        },
    )
    action = _apply_recovery(repo=repo, packet={**packet, "created_by": user["user_id"]}, selected=candidate)
    if "secret_ref" not in action:
        return fail(f"unexpected apply action: {action}")
    evidence = repo.product_readiness_evidence()
    if evidence.get("ebay_secret_refs") != 1:
        return fail("recovered eBay secret_ref should count in readiness evidence")
    if evidence.get("read_only_authorized_connections") != 1:
        return fail("recovered platform connection should count as read-only authorized")
    dumped_refs = json.dumps(repo.list_secret_refs(company_id=company["company_id"], store_id=store["store_id"]), ensure_ascii=False)
    dumped_connections = json.dumps(repo.list_connections(company_id=company["company_id"], store_id=store["store_id"]), ensure_ascii=False)
    if SECRET_MARKER in dumped_refs or SECRET_MARKER in dumped_connections:
        return fail("raw refresh token must not be persisted in SaaS database metadata")

    print("PASS jiejing_recover_ebay_secret_refs_from_ssm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
