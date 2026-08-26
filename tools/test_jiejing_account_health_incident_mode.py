#!/usr/bin/env python3
"""Regression for merchant-visible account health and incident mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_runtime.execution import ExecutionRequest, ExecutionService  # noqa: E402
from jiejing_saas.account_health import build_account_health_snapshot, merge_account_health_into_payload  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402


OUT = ROOT / "output" / "jiejing-account-health-incident-mode-test"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _publish_payload() -> dict:
    return {
        "listing": {
            "sku": "JJ-ACCOUNT-INCIDENT-001",
            "title": "Fresh Account Health Test Product",
            "description_html": "<p>Fresh account health test product.</p>",
            "category_id": "20687",
            "condition": "NEW",
            "price": {"value": "12.99", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {"Brand": "Unbranded", "Type": "Test Product"},
            "merchant_location_key": "default",
        },
        "business_policies": {
            "fulfillment_policy_id": "fulfillment-policy",
            "payment_policy_id": "payment-policy",
            "return_policy_id": "return-policy",
        },
        "supplier_facts": {
            "package_weight_g": 180,
            "package_dimensions_cm": {"length": 10, "width": 8, "height": 4},
            "material": "Plastic",
            "item_location": "US",
        },
        "asset_manifest": {"assets": [{"url": "https://example.com/image.jpg"}]},
        "finance_review": {"net_profit_money": {"value": "3.20", "currency": "USD"}},
    }


def _request(payload: dict, *, store_id: str) -> ExecutionRequest:
    return ExecutionRequest(
        action_type="publish_listing",
        task_id=f"task_{store_id}",
        user_id="user_account_health",
        company_id="company_account_health",
        store_id=store_id,
        platform="ebay",
        confirmation_id=f"confirm_{store_id}",
        confirmed_by="user_account_health",
        confirmed_at="2026-06-13T00:00:00+00:00",
        idempotency_key=f"account-health-{store_id}",
        payload=payload,
    )


def _create_store_with_packet(
    repo: SaaSRepository,
    *,
    status: str,
    store_name: str,
    include_business_policies: bool = True,
    complete_business_policies: bool = True,
) -> dict:
    record = repo.create_user_with_company(
        email=f"{store_name}@jiejing.local",
        password="account-health-password",
        company_name="Jiejing Account Health Test",
    )
    company_id = record["company"]["company_id"]
    user_id = record["user"]["user_id"]
    store = repo.create_store(
        company_id=company_id,
        user_id=user_id,
        payload={"platform": "ebay", "store_name": store_name, "marketplace": "EBAY_US"},
    )
    repo.create_platform_connection(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        payload={
            "platform": "ebay",
            "connection_type": "oauth",
            "status": "publish_authorized",
            "scopes": ["sell.account.readonly", "sell.inventory"],
        },
    )
    sections = [
        {
            "key": "store_profile",
            "source_type": "official_api",
            "data": {
                "marketplace_id": "EBAY_US",
                "seller_account_status": status,
                "selling_limits": {"used": 1, "limit": 35},
            },
        }
    ]
    if include_business_policies:
        sections.append(
            {
                "key": "account_business_policies",
                "source_type": "official_api",
                "data": {
                    "fulfillment_policy_id": "fulfillment-policy",
                    "payment_policy_id": "payment-policy",
                    **({"return_policy_id": "return-policy"} if complete_business_policies else {}),
                },
            }
        )
    repo.create_platform_data_packet(
        company_id=company_id,
        store_id=store["store_id"],
        user_id=user_id,
        packet={
            "platform": "ebay",
            "packet_type": "ebay_read_only_snapshot",
            "source_mode": "official_api",
            "status": "packet_cached_sanitized",
            "source_label": "official_api",
            "present_resource_keys": ["store_profile", *(["account_business_policies"] if include_business_policies else [])],
            "missing_resource_keys": [] if include_business_policies else ["account_business_policies"],
            "sections": sections,
            "secret_exposed": False,
        },
    )
    return {"company_id": company_id, "user_id": user_id, "store": store}


class _RestrictedExecutionRepository:
    """Minimal repository proving an exact provider rejection overrides a stale clear packet."""

    def __init__(self, *, packet_created_at: str = "2026-08-26T03:00:00+00:00") -> None:
        self.packet_created_at = packet_created_at

    def get_store_for_company(self, *, company_id: str, store_id: str) -> dict:
        return {"store_id": store_id, "store_name": "restricted-execution-store", "marketplace": "EBAY_US"}

    def list_platform_data_packets(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "packet_id": "packet_before_provider_rejection",
                "source_mode": "official_api",
                "created_at": self.packet_created_at,
                "packet": {
                    "source_label": "official_api",
                    "sections": [
                        {
                            "key": "store_profile",
                            "data": {
                                "seller_account_status": "registration_completed",
                                "selling_limits": {"used": 1, "limit": 35},
                            },
                        },
                        {
                            "key": "account_business_policies",
                            "data": {
                                "fulfillment_policy_id": "fulfillment-policy",
                                "payment_policy_id": "payment-policy",
                                "return_policy_id": "return-policy",
                            },
                        },
                    ],
                },
            }
        ]

    def list_connections(self, **_kwargs: object) -> list[dict]:
        return [{"connection_id": "connection_restricted", "status": "publish_authorized", "connection_type": "oauth"}]

    def list_execution_results(self, **_kwargs: object) -> list[dict]:
        return [
            {
                "action_type": "publish_listing",
                "status": "blocked_platform_error",
                "created_at": "2026-08-26T04:08:00+00:00",
                "result": {
                    "status": "blocked_platform_error",
                    "steps": [
                        {
                            "step": "publish_existing_offer",
                            "status": "http_error",
                            "http_status": 400,
                            "platform_error": {
                                "error_id": 25019,
                                "code": "platform_error",
                                "message": "An error has occurred.",
                            },
                        }
                    ],
                    "audit": {"real_execution": {"published_to_ebay": False}},
                },
            }
        ]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "account-health.sqlite"
    if db_path.exists():
        db_path.unlink()
    repo = SaaSRepository(db_path)

    healthy_ctx = _create_store_with_packet(repo, status="registration_completed", store_name="healthy-store")
    healthy = build_account_health_snapshot(
        repo,
        company_id=healthy_ctx["company_id"],
        store_id=healthy_ctx["store"]["store_id"],
    )
    if healthy.get("status") != "normal" or healthy.get("incident_mode") is not False:
        return fail(f"healthy official store_profile should be clear: {healthy}")
    if healthy.get("business_policy_statuses") != {"payment": True, "fulfillment": True, "return": True}:
        return fail(f"healthy evidence should expose all three policy statuses: {healthy}")
    healthy_payload = merge_account_health_into_payload(_publish_payload(), healthy)
    healthy_preflight = ExecutionService(demo_mode=False).preflight(
        _request(healthy_payload, store_id=healthy_ctx["store"]["store_id"])
    )
    if healthy_preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"healthy account should allow publish preflight to continue: {healthy_preflight}")

    restricted_after_publish = build_account_health_snapshot(
        _RestrictedExecutionRepository(),
        company_id="company_restricted_execution",
        store_id="store_restricted_execution",
    )
    if restricted_after_publish.get("status") != "restricted" or restricted_after_publish.get("incident_mode") is not True:
        return fail(f"eBay provider error 25019 must override an older clear packet: {restricted_after_publish}")
    if restricted_after_publish.get("onboarding_stage") != "account_review_required":
        return fail(f"restricted execution must stop the onboarding publish route: {restricted_after_publish}")
    restricted_actions = " ".join(restricted_after_publish.get("next_actions") or [])
    for required in ("eBay 站内信", "资料核验", "无需重新授权"):
        if required not in restricted_actions:
            return fail(f"25019 recovery guidance should contain {required!r}: {restricted_after_publish}")
    restricted_errors = (restricted_after_publish.get("evidence_package") or {}).get("recent_platform_errors") or []
    if not restricted_errors or str(restricted_errors[0].get("error_id") or "") != "25019":
        return fail(f"merchant-safe account health evidence must preserve error_id 25019: {restricted_after_publish}")

    recovered_after_new_packet = build_account_health_snapshot(
        _RestrictedExecutionRepository(packet_created_at="2026-08-26T05:00:00+00:00"),
        company_id="company_recovered_execution",
        store_id="store_recovered_execution",
    )
    if recovered_after_new_packet.get("status") != "normal" or recovered_after_new_packet.get("incident_mode") is not False:
        return fail(f"a newer clear official packet must retire an older provider rejection: {recovered_after_new_packet}")

    frozen_ctx = _create_store_with_packet(repo, status="suspended", store_name="frozen-store")
    frozen = build_account_health_snapshot(
        repo,
        company_id=frozen_ctx["company_id"],
        store_id=frozen_ctx["store"]["store_id"],
    )
    if frozen.get("status") != "suspended" or frozen.get("incident_mode") is not True:
        return fail(f"suspended account should enter incident mode: {frozen}")
    frozen_payload = merge_account_health_into_payload(_publish_payload(), frozen)
    frozen_preflight = ExecutionService(demo_mode=False).preflight(
        _request(frozen_payload, store_id=frozen_ctx["store"]["store_id"])
    )
    issue_keys = {item.get("key") for item in frozen_preflight.get("issues", [])}
    if frozen_preflight.get("status") != "blocked_missing_execution_facts" or "account_health.status" not in issue_keys:
        return fail(f"incident account should block publish preflight: {frozen_preflight}")

    incomplete_ctx = _create_store_with_packet(
        repo,
        status="registration_incomplete",
        store_name="registration-incomplete-store",
        include_business_policies=False,
    )
    incomplete = build_account_health_snapshot(
        repo,
        company_id=incomplete_ctx["company_id"],
        store_id=incomplete_ctx["store"]["store_id"],
    )
    if incomplete.get("status") != "registration_incomplete" or incomplete.get("incident_mode") is not True:
        return fail(f"incomplete seller registration should have a precise blocked status: {incomplete}")
    if incomplete.get("onboarding_stage") != "seller_registration_required":
        return fail(f"incomplete seller registration should expose the exact onboarding stage: {incomplete}")
    incomplete_evidence = incomplete.get("evidence_package") or {}
    if incomplete_evidence.get("business_policies_present") is not False:
        return fail(f"missing business policies should remain visible without exposing secrets: {incomplete}")
    incomplete_actions = " ".join(incomplete.get("next_actions") or [])
    for required in ("完成 eBay 卖家注册", "无需重新授权", "Seller Hub"):
        if required not in incomplete_actions:
            return fail(f"registration guidance should contain {required!r}: {incomplete}")

    policies_ctx = _create_store_with_packet(
        repo,
        status="registration_completed",
        store_name="business-policies-missing-store",
        include_business_policies=False,
    )
    policies_missing = build_account_health_snapshot(
        repo,
        company_id=policies_ctx["company_id"],
        store_id=policies_ctx["store"]["store_id"],
    )
    if policies_missing.get("status") != "normal" or policies_missing.get("onboarding_stage") != "business_policies_required":
        return fail(f"healthy seller with missing policies should receive policy setup guidance: {policies_missing}")
    if policies_missing.get("can_enter_publish_preflight") is not False:
        return fail(f"missing policy references should stop publish preflight readiness: {policies_missing}")
    policies_actions = " ".join(policies_missing.get("next_actions") or [])
    for required in ("Business Policies", "付款、配送和退货", "无需重新授权"):
        if required not in policies_actions:
            return fail(f"business-policy guidance should contain {required!r}: {policies_missing}")

    incomplete_policies_ctx = _create_store_with_packet(
        repo,
        status="registration_completed",
        store_name="business-policies-incomplete-store",
        include_business_policies=True,
        complete_business_policies=False,
    )
    incomplete_policies = build_account_health_snapshot(
        repo,
        company_id=incomplete_policies_ctx["company_id"],
        store_id=incomplete_policies_ctx["store"]["store_id"],
    )
    if incomplete_policies.get("onboarding_stage") != "business_policies_required":
        return fail(f"a partial business-policy section must not be treated as publish-ready: {incomplete_policies}")
    if (incomplete_policies.get("evidence_package") or {}).get("business_policies_present") is not False:
        return fail(f"all three policy IDs are required for business-policy readiness: {incomplete_policies}")
    if incomplete_policies.get("business_policy_statuses") != {
        "payment": True,
        "fulfillment": True,
        "return": False,
    }:
        return fail(f"partial business policies should identify the exact missing policy: {incomplete_policies}")

    no_packet = repo.create_store(
        company_id=healthy_ctx["company_id"],
        user_id=healthy_ctx["user_id"],
        payload={"platform": "ebay", "store_name": "no-packet-store", "marketplace": "EBAY_US"},
    )
    unknown = build_account_health_snapshot(repo, company_id=healthy_ctx["company_id"], store_id=no_packet["store_id"])
    if unknown.get("status") != "unknown" or unknown.get("incident_mode") is not True:
        return fail(f"missing store_profile should default to incident mode: {unknown}")

    serialized = json.dumps(
        {
            "healthy": healthy,
            "frozen": frozen,
            "registration_incomplete": incomplete,
            "business_policies_missing": policies_missing,
            "business_policies_incomplete": incomplete_policies,
            "unknown": unknown,
        },
        ensure_ascii=False,
    )
    for forbidden in (
        "UNIT-ACCESS-TOKEN-MUST-NOT-PERSIST",
        "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST",
        "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST",
        "sk-",
        "Bearer ",
    ):
        if forbidden.lower() in serialized.lower():
            return fail(f"account health snapshot leaked forbidden marker: {forbidden}")
    print("PASS jiejing_account_health_incident_mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
