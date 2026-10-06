#!/usr/bin/env python3
"""Regression for merchant-visible account health and incident mode."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
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


def _backend_publish_evidence(
    *,
    company_id: str,
    store_id: str,
    listing_project_key: str,
    report_id: str,
    image_url: str,
) -> dict:
    evidence = {
        "contract_version": "2026-08-31-publish-source-rights-evidence-v1",
        "status": "ready",
        "server_resolved": True,
        "scope": {
            "company_id": company_id,
            "store_id": store_id,
            "listing_project_key": listing_project_key,
        },
        "refs": {
            "product_fact_report_id": report_id,
            "media_job_id": "",
        },
        "product_source": {
            "status": "verified",
            "source_mode": "merchant_owned_product",
            "evidence_type": "merchant_product_fact_report",
            "evidence_id": report_id,
        },
        "image_rights": {
            "status": "verified",
            "required_asset_count": 1,
            "covered_asset_count": 1,
            "coverage_complete": True,
            "assets": [
                {
                    "asset_id": "",
                    "url_sha256": hashlib.sha256(image_url.encode("utf-8")).hexdigest(),
                    "evidence_type": "merchant_product_fact_report",
                    "evidence_id": report_id,
                }
            ],
        },
        "secret_exposed": False,
    }
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence["resolved_at"] = "2026-08-31T00:00:00Z"
    return evidence


def _publish_payload(*, company_id: str, store_id: str) -> dict:
    image_url = "https://example.com/image.jpg"
    listing_project_key = f"listing-project-account-health-{store_id}"
    report_id = f"report_account_health_{store_id}"
    return {
        "listing_project_identity": {
            "key": listing_project_key,
            "source_report_id": report_id,
            "candidate_id": "candidate-account-health",
        },
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
        "asset_manifest": {"assets": [{"url": image_url}]},
        "publish_evidence": _backend_publish_evidence(
            company_id=company_id,
            store_id=store_id,
            listing_project_key=listing_project_key,
            report_id=report_id,
            image_url=image_url,
        ),
        "finance_review": {"net_profit_money": {"value": "3.20", "currency": "USD"}},
    }


def _request(payload: dict, *, company_id: str, store_id: str) -> ExecutionRequest:
    return ExecutionRequest(
        action_type="publish_listing",
        task_id=f"task_{store_id}",
        user_id="user_account_health",
        company_id=company_id,
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
    kyc_check_status: str = "clear",
    kyc_checks: list[dict] | None = None,
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
                "kyc_check_status": kyc_check_status,
                "kyc_check_count": len(kyc_checks or []),
                "kyc_checks": kyc_checks or [],
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

    def __init__(
        self,
        *,
        packet_created_at: str = "2026-08-26T03:00:00+00:00",
        provider_restriction_resolution: dict | None = None,
        provider_restriction_resolution_audit: dict | None = None,
    ) -> None:
        self.packet_created_at = packet_created_at
        self.provider_restriction_resolution = provider_restriction_resolution
        self.provider_restriction_resolution_audit = provider_restriction_resolution_audit

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
                                "kyc_check_status": "clear",
                                "kyc_check_count": 0,
                                "kyc_checks": [],
                                **(
                                    {"provider_restriction_resolution": self.provider_restriction_resolution}
                                    if self.provider_restriction_resolution is not None
                                    else {}
                                ),
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

    def find_latest_audit_log_by_target(self, **_kwargs: object) -> dict | None:
        return self.provider_restriction_resolution_audit


def _health_regression_checks(repo: SaaSRepository, context: dict) -> list[str]:
    failures: list[str] = []
    company_id = context["company_id"]
    store_id = context["store"]["store_id"]
    other_store = repo.create_store(
        company_id=company_id,
        user_id=context["user_id"],
        payload={"platform": "ebay", "store_name": "other-health-store"},
    )

    def record(target_store_id: str, name: str, *, error: bool = False) -> None:
        task = repo.create_task(
            company_id=company_id, store_id=target_store_id, user_id=context["user_id"],
            task_type="account_health.test", title=name, input_data={},
        )
        confirmation = repo.create_confirmation(
            company_id=company_id, store_id=target_store_id, task_id=task["task_id"],
            runtime_run_id="account_health_test", action_type="publish_listing", title=name, item={},
        )
        repo.save_execution_result(
            confirmation=confirmation,
            result={
                "status": "blocked_platform_error" if error else "simulated_no_platform_write",
                "created_at": "2026-08-26T04:08:00+00:00" if error else "2027-01-01T00:00:00+00:00",
                "store_id": target_store_id,
                **({"steps": [{"provider_error": {"error_id": 25019, "message": "Account verification required"}}]} if error else {}),
            },
        )

    record(other_store["store_id"], "unrelated store restriction", error=True)
    other_health = build_account_health_snapshot(repo, company_id=company_id, store_id=store_id)
    if other_health["status"] != "normal":
        failures.append("another store's provider rejection contaminated this store")
    record(store_id, "sticky target store restriction", error=True)
    for index in range(81):
        record(store_id, f"newer ordinary execution {index}")
    retained = build_account_health_snapshot(repo, company_id=company_id, store_id=store_id)
    if retained["status"] != "restricted" or retained["can_execute_real_writes"] is not False:
        failures.append("25019 was forgotten after more than 80 ordinary executions")
    scoped_records = repo.list_execution_results(
        company_id=company_id, store_id=store_id, limit=80, include_error_ids=("25019",),
    )
    if len(scoped_records) != 81 or any(row.get("result", {}).get("store_id") != store_id for row in scoped_records):
        failures.append("historical restriction retrieval lost its store scope or bounded ordinary window")
    if repo.list_execution_results(
        company_id="unrelated-company", store_id=store_id, limit=80, include_error_ids=("25019",),
    ):
        failures.append("historical restriction retrieval crossed the company boundary")
    restricted = build_account_health_snapshot(
        _RestrictedExecutionRepository(), company_id=company_id, store_id=store_id,
    )
    old_clear_payload = _publish_payload(company_id=company_id, store_id=store_id)
    old_clear_payload["account_health"] = {
        "status": "clear", "selling_status": "active", "payout_status": "available", "restrictions": [],
    }
    original_payload = deepcopy(old_clear_payload)
    merged = merge_account_health_into_payload(old_clear_payload, restricted)
    issue_keys = {
        item.get("key") for item in ExecutionService(demo_mode=False).preflight(
            _request(merged, company_id=company_id, store_id=store_id),
        ).get("issues", [])
    }
    if merged["account_health"]["status"] != "restricted" or "account_health.status" not in issue_keys:
        failures.append("old clear payload overrode the latest restricted health during publish preflight")
    if old_clear_payload != original_payload:
        failures.append("account health merge mutated the saved payload")

    class NestedRestrictionRepository(_RestrictedExecutionRepository):
        def list_execution_results(self, **kwargs: object) -> list[dict]:
            records = super().list_execution_results(**kwargs)
            records[0]["result"] = {"steps": [
                {"platform_error": {"error_id": "40000", "message": "unrelated old error"}},
                {"result": {"provider_error": {"errorId": 25019, "message": "Account verification required"}}},
            ]}
            return records

    nested = build_account_health_snapshot(
        NestedRestrictionRepository(packet_created_at="2026-09-01T00:00:00+00:00"),
        company_id=company_id, store_id=store_id,
    )
    if nested["status"] != "restricted":
        failures.append("nested provider restriction was skipped after the first non-sticky error")

    class FreshnessRepository(_RestrictedExecutionRepository):
        def __init__(self, *, snapshot_time: str, threshold: object = 21600, blocked: bool = False) -> None:
            super().__init__(packet_created_at=snapshot_time)
            self.threshold = threshold
            self.blocked = blocked

        def list_platform_data_packets(self, **kwargs: object) -> list[dict]:
            packets = super().list_platform_data_packets(**kwargs)
            packets[0]["packet"]["freshness"] = {
                "status": "fresh_at_creation", "snapshot_created_at": self.packet_created_at,
                "stale_after_seconds": self.threshold,
            }
            return packets

        def list_execution_results(self, **kwargs: object) -> list[dict]:
            return super().list_execution_results(**kwargs) if self.blocked else []

    now = datetime.now(timezone.utc)
    freshness_cases = [
        ("fresh", (now - timedelta(minutes=1)).isoformat(), 21600, "normal", False),
        ("stale", (now - timedelta(hours=7)).isoformat(), 21600, "unknown", False),
        ("invalid timestamp", "not-a-date", 21600, "unknown", False),
        ("invalid threshold", now.isoformat(), 0, "unknown", False),
        ("future timestamp", (now + timedelta(days=1)).isoformat(), 21600, "unknown", False),
        ("known restriction stays visible", (now - timedelta(days=30)).isoformat(), 21600, "restricted", True),
    ]
    for label, stamp, threshold, expected, blocked in freshness_cases:
        snapshot = build_account_health_snapshot(
            FreshnessRepository(snapshot_time=stamp, threshold=threshold, blocked=blocked),
            company_id=company_id, store_id=store_id,
        )
        if snapshot["status"] != expected:
            failures.append(f"packet freshness {label}: expected {expected}, got {snapshot['status']}")
        if expected != "normal" and (snapshot["can_execute_real_writes"] or snapshot["can_enter_publish_preflight"]):
            failures.append(f"packet freshness {label} incorrectly permits writes or publish preflight")

    class RewrappedSnapshotRepository(FreshnessRepository):
        def __init__(self, *, old_timestamp_field: str) -> None:
            super().__init__(snapshot_time=now.isoformat())
            self.old_timestamp_field = old_timestamp_field

        def list_platform_data_packets(self, **kwargs: object) -> list[dict]:
            packets = super().list_platform_data_packets(**kwargs)
            packet = packets[0]["packet"]
            packet["created_at"] = now.isoformat()
            old_stamp = (now - timedelta(hours=7)).isoformat()
            if self.old_timestamp_field == "snapshot":
                packet["freshness"]["snapshot_created_at"] = old_stamp
            elif self.old_timestamp_field == "packet":
                packet["created_at"] = old_stamp
            else:
                packets[0]["created_at"] = old_stamp
            return packets

    for old_field in ("snapshot", "packet", "record"):
        snapshot = build_account_health_snapshot(
            RewrappedSnapshotRepository(old_timestamp_field=old_field),
            company_id=company_id, store_id=store_id,
        )
        evidence = snapshot["evidence_package"]["packet_freshness"]
        if snapshot["status"] != "unknown" or evidence["status"] != "stale":
            failures.append(f"new wrapper timestamps hid the old {old_field} timestamp")
        if evidence.get("age_seconds", 0) < 7 * 3600:
            failures.append(f"freshness did not preserve the oldest {old_field} evidence age")
        if snapshot["can_execute_real_writes"] or snapshot["can_enter_publish_preflight"]:
            failures.append(f"rewrapped old {old_field} data incorrectly permits publish")
    return failures


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
    healthy_payload = merge_account_health_into_payload(
        _publish_payload(
            company_id=healthy_ctx["company_id"],
            store_id=healthy_ctx["store"]["store_id"],
        ),
        healthy,
    )
    healthy_preflight = ExecutionService(demo_mode=False).preflight(
        _request(
            healthy_payload,
            company_id=healthy_ctx["company_id"],
            store_id=healthy_ctx["store"]["store_id"],
        )
    )
    if healthy_preflight.get("status") != "ready_for_platform_adapter":
        return fail(f"healthy account should allow publish preflight to continue: {healthy_preflight}")

    kyc_ctx = _create_store_with_packet(
        repo,
        status="registration_completed",
        store_name="kyc-review-store",
        kyc_check_status="verification_required",
        kyc_checks=[
            {
                "alert": "更新账户资料",
                "detail": "更新前发放款项将被冻结。",
                "due_date": "2026-08-31T00:00:00.000Z",
                "remedy_available": True,
            }
        ],
    )
    kyc_blocked = build_account_health_snapshot(
        repo,
        company_id=kyc_ctx["company_id"],
        store_id=kyc_ctx["store"]["store_id"],
    )
    if kyc_blocked.get("status") not in {"restricted", "payout_hold"} or kyc_blocked.get("incident_mode") is not True:
        return fail(f"an active official KYC check must enter incident mode: {kyc_blocked}")
    if kyc_blocked.get("can_execute_real_writes") is not False:
        return fail(f"an active official KYC check must block real writes: {kyc_blocked}")
    kyc_actions = " ".join(kyc_blocked.get("next_actions") or [])
    for required in ("eBay 官方页面", "账户资料", "无需重新授权"):
        if required not in kyc_actions:
            return fail(f"KYC guidance should contain {required!r}: {kyc_blocked}")
    kyc_evidence = kyc_blocked.get("evidence_package") or {}
    if kyc_evidence.get("kyc_check_status") != "verification_required" or kyc_evidence.get("kyc_check_count") != 1:
        return fail(f"KYC evidence must preserve the sanitized provider result: {kyc_blocked}")

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

    still_restricted_after_new_kyc_packet = build_account_health_snapshot(
        _RestrictedExecutionRepository(packet_created_at="2026-08-26T05:00:00+00:00"),
        company_id="company_still_restricted_execution",
        store_id="store_still_restricted_execution",
    )
    if (
        still_restricted_after_new_kyc_packet.get("status") != "restricted"
        or still_restricted_after_new_kyc_packet.get("incident_mode") is not True
    ):
        return fail(
            "a newer KYC-clear packet must not retire an unresolved provider restriction: "
            f"{still_restricted_after_new_kyc_packet}"
        )

    recovered_after_trusted_resolution = build_account_health_snapshot(
        _RestrictedExecutionRepository(
            packet_created_at="2026-08-26T05:00:00+00:00",
            provider_restriction_resolution_audit={
                "actor_type": "platform_internal_admin",
                "action_type": "ebay.provider_restriction.resolution_verified",
                "target_type": "store",
                "target_id": "store_recovered_execution",
                "created_at": "2026-08-26T04:30:00+00:00",
                "details": {
                    "status": "clear",
                    "evidence_type": "ebay_message_resolution_notice",
                    "verified_at": "2026-08-26T04:30:00+00:00",
                    "restriction_error_id": "25019",
                    "secret_exposed": False,
                },
            },
        ),
        company_id="company_recovered_execution",
        store_id="store_recovered_execution",
    )
    if recovered_after_trusted_resolution.get("status") != "normal" or recovered_after_trusted_resolution.get("incident_mode") is not False:
        return fail(f"trusted newer restriction-resolution evidence should retire error 25019: {recovered_after_trusted_resolution}")
    resolution_evidence = (recovered_after_trusted_resolution.get("evidence_package") or {}).get(
        "provider_restriction_resolution"
    ) or {}
    if resolution_evidence.get("trusted") is not True or resolution_evidence.get("evidence_type") != "ebay_message_resolution_notice":
        return fail(f"merchant-safe evidence must preserve the trusted resolution type: {recovered_after_trusted_resolution}")

    forged_packet_resolution = build_account_health_snapshot(
        _RestrictedExecutionRepository(
            packet_created_at="2026-08-26T05:00:00+00:00",
            provider_restriction_resolution={
                "status": "clear",
                "evidence_type": "ebay_message_resolution_notice",
                "verified_at": "2026-08-26T04:30:00+00:00",
                "restriction_error_id": "25019",
            },
        ),
        company_id="company_forged_packet_resolution",
        store_id="store_forged_packet_resolution",
    )
    if forged_packet_resolution.get("status") != "restricted" or forged_packet_resolution.get("incident_mode") is not True:
        return fail(f"packet-embedded merchant evidence must not clear provider restriction: {forged_packet_resolution}")

    forged_user_audit_resolution = build_account_health_snapshot(
        _RestrictedExecutionRepository(
            packet_created_at="2026-08-26T05:00:00+00:00",
            provider_restriction_resolution_audit={
                "actor_type": "user",
                "action_type": "ebay.provider_restriction.resolution_verified",
                "target_type": "store",
                "target_id": "store_forged_user_audit_resolution",
                "created_at": "2026-08-26T04:30:00+00:00",
                "details": {
                    "status": "clear",
                    "evidence_type": "ebay_message_resolution_notice",
                    "verified_at": "2026-08-26T04:30:00+00:00",
                    "restriction_error_id": "25019",
                },
            },
        ),
        company_id="company_forged_user_audit_resolution",
        store_id="store_forged_user_audit_resolution",
    )
    if forged_user_audit_resolution.get("status") != "restricted" or forged_user_audit_resolution.get("incident_mode") is not True:
        return fail(f"non-admin audit evidence must not clear provider restriction: {forged_user_audit_resolution}")

    frozen_ctx = _create_store_with_packet(repo, status="suspended", store_name="frozen-store")
    frozen = build_account_health_snapshot(
        repo,
        company_id=frozen_ctx["company_id"],
        store_id=frozen_ctx["store"]["store_id"],
    )
    if frozen.get("status") != "suspended" or frozen.get("incident_mode") is not True:
        return fail(f"suspended account should enter incident mode: {frozen}")
    frozen_payload = merge_account_health_into_payload(
        _publish_payload(
            company_id=frozen_ctx["company_id"],
            store_id=frozen_ctx["store"]["store_id"],
        ),
        frozen,
    )
    frozen_preflight = ExecutionService(demo_mode=False).preflight(
        _request(
            frozen_payload,
            company_id=frozen_ctx["company_id"],
            store_id=frozen_ctx["store"]["store_id"],
        )
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
    regression_failures = _health_regression_checks(repo, healthy_ctx)
    if regression_failures:
        return fail("; ".join(regression_failures))
    print("PASS jiejing_account_health_incident_mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
