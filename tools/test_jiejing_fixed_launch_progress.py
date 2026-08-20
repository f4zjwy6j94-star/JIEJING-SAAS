#!/usr/bin/env python3
"""Behavior regression for the fixed internal launch-progress contract."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.launch_progress import FIXED_LAUNCH_CATEGORY_WEIGHTS, build_fixed_launch_progress


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def fixture(
    *,
    browser_smoke_passed: bool = True,
    canonical_capabilities_only: bool = False,
    reliability_ready: bool = False,
    ebay_secret_refs: int = 0,
    execution_service_status: str = "safe_demo_boundary",
    backup_status: str | None = None,
    post_publish_ready: bool = True,
    real_platform_writes_enabled: bool = False,
    secret_exposed: bool = False,
) -> dict:
    groups = [
        {"key": key, "status": status}
        for key, status in {
            "official_ebay_read_loop": "blocked",
            "managed_database_queue": "blocked",
            "managed_secret_boundary": "blocked",
            "stable_domain_tls": "blocked",
            "backup_restore": "blocked",
            "monitoring_alerting": "blocked",
            "publish_safety_system": "blocked",
            "store_sync_visibility": "blocked",
            "post_publish_cockpit": "ready" if post_publish_ready else "blocked",
            "model_agent_value": "ready",
            "new_ebay_account_low_risk_smoke": "blocked",
            "legal_risk_boundary": "ready",
            "final_commercial_smoke": "blocked",
        }.items()
    ]
    readiness = {
        "beta_ready": True,
        "production_ready": False,
        "can_accept_real_customers": False,
        "real_platform_writes_enabled": real_platform_writes_enabled,
        "secret_exposed": secret_exposed,
        "product_evidence": {
            "ebay_secret_refs": ebay_secret_refs,
            "ebay_token_refresh_success_count": 0,
            "secret_exposed": secret_exposed,
        },
        "provider_status": {
            "model_value": {"ready_for_paid_value_claim": True, "model_configured": True},
            "public_search": {"configured": True, "ai_ceo_realtime_search_enabled": True},
            "media_generation": {
                "configured": True,
                "live_image_generation_enabled": True,
                "asset_manifest_required": True,
                "human_review_required_before_listing": True,
            },
        },
        "items": [
            {"key": "database_live_probe", "status": "ready"},
            {"key": "queue_runtime_health", "status": "ready"},
            {"key": "worker_runtime_health", "status": "ready"},
            {"key": "vault", "status": "ready"},
            {"key": "vault_adapter_contract", "status": "adapter_contract_ready"},
            {
                "key": "backup_restore",
                "status": backup_status
                or ("ready" if reliability_ready else "paid_launch_backup_evidence_stale"),
            },
            {
                "key": "monitoring_alerting",
                "status": "cloud_monitoring_ready" if reliability_ready else "managed_monitoring_pending",
            },
            {"key": "execution_service", "status": execution_service_status},
            {"key": "ebay_read_only_adapter", "status": "current_account_not_connected"},
            {"key": "ebay_read", "status": "current_account_packet_missing"},
            {"key": "platform_data_packets", "status": "current_account_packet_missing"},
        ],
    }
    billing = {
        "quota_contract": {"enabled": True},
        "domestic_payment": {
            "provider": "wechat_pay_native",
            "status": "controlled_acceptance_proven",
            "configured_component_count": 9,
            "required_component_count": 9,
            "public_charging_allowed": False,
        },
    }
    if canonical_capabilities_only:
        billing["mainland_payment_launch"] = {
            "code_capabilities": {
                "signed_payment_callback_implemented": True,
                "real_order_creation_implemented": True,
            }
        }
    else:
        billing["domestic_payment"].update(
            {
                "signed_callback_implemented": True,
                "real_order_creation_implemented": True,
            }
        )
    return build_fixed_launch_progress(
        readiness=readiness,
        launch_gate={"groups": groups, "paid_commercial_launch_ready": False},
        billing=billing,
        operational={"status": "ready"},
        test_data_governance={
            "contract_version": "2026-06-20-test-data-governance",
            "scope": "current_company_only",
            "status": "no_test_data_detected",
        },
        release_evidence={
            "browser_smoke_passed": browser_smoke_passed,
            "public_domain_tls_passed": True,
        },
    )


def main() -> int:
    if sum(FIXED_LAUNCH_CATEGORY_WEIGHTS.values()) != 100:
        return fail(f"fixed category denominator must remain 100: {FIXED_LAUNCH_CATEGORY_WEIGHTS}")

    packet = fixture()
    if packet.get("contract_version") != "2026-08-20-fixed-public-launch-progress-v2":
        return fail(f"fixed progress contract missing: {packet}")
    if packet.get("score_percent") != 59:
        return fail(f"current evidence baseline must remain fixed at 59/100: {packet.get('score_percent')}")
    if packet.get("fixed_denominator") is not True or packet.get("total_points") != 100:
        return fail(f"score denominator must be explicit and immutable: {packet}")
    if packet.get("public_paid_launch_allowed") is not False:
        return fail("controlled payment acceptance must not open public charging")
    if packet.get("score_can_change_only_when_evidence_changes") is not True:
        return fail("score change policy must be explicit")
    if packet != fixture():
        return fail("same evidence must produce exactly the same score and queue")

    canonical_capabilities = fixture(canonical_capabilities_only=True)
    if canonical_capabilities.get("score_percent") != 59:
        return fail(
            "internal progress must count canonical mainland code capabilities without relying on the public summary: "
            f"{canonical_capabilities.get('score_percent')}"
        )

    draft_save_proven = fixture(execution_service_status="unpublished_ebay_draft_save_proven")
    draft_categories = {
        item.get("key"): item
        for item in draft_save_proven.get("categories", [])
        if isinstance(item, dict)
    }
    draft_merchant_checks = {
        item.get("key"): item
        for item in draft_categories.get("merchant_product", {}).get("checks", [])
        if isinstance(item, dict)
    }
    draft_security_checks = {
        item.get("key"): item
        for item in draft_categories.get("security_compliance", {}).get("checks", [])
        if isinstance(item, dict)
    }
    if draft_merchant_checks.get("publish_safety_ready", {}).get("status") != "ready":
        return fail("one-shot confirmation-gated unpublished eBay draft proof must satisfy publish safety")
    if draft_security_checks.get("high_risk_confirmation_gate", {}).get("status") != "ready":
        return fail("one-shot confirmation-gated unpublished eBay draft proof must satisfy the high-risk gate")
    if draft_save_proven.get("score_percent") != packet.get("score_percent"):
        return fail(
            "new unpublished-draft proof must replace the legacy safe boundary without losing fixed points: "
            f"legacy={packet.get('score_percent')} draft={draft_save_proven.get('score_percent')}"
        )
    unsafe_draft = fixture(
        execution_service_status="unpublished_ebay_draft_save_proven",
        real_platform_writes_enabled=True,
    )
    unsafe_categories = {
        item.get("key"): item for item in unsafe_draft.get("categories", []) if isinstance(item, dict)
    }
    unsafe_security = {
        item.get("key"): item
        for item in unsafe_categories.get("security_compliance", {}).get("checks", [])
        if isinstance(item, dict)
    }
    if unsafe_security.get("high_risk_confirmation_gate", {}).get("status") != "pending":
        return fail("unpublished-draft proof must not earn the high-risk gate when broad real writes are enabled")
    leaked_draft = fixture(
        execution_service_status="unpublished_ebay_draft_save_proven",
        secret_exposed=True,
    )
    leaked_categories = {
        item.get("key"): item for item in leaked_draft.get("categories", []) if isinstance(item, dict)
    }
    leaked_security = {
        item.get("key"): item
        for item in leaked_categories.get("security_compliance", {}).get("checks", [])
        if isinstance(item, dict)
    }
    if leaked_security.get("high_risk_confirmation_gate", {}).get("status") != "pending":
        return fail("unpublished-draft proof must not earn the high-risk gate when the secret boundary is broken")

    categories = {item.get("key"): item for item in packet.get("categories", []) if isinstance(item, dict)}
    if categories.get("payment_entitlements", {}).get("earned_points") != 16:
        return fail(f"controlled WeChat acceptance should earn technical payment points only: {categories.get('payment_entitlements')}")
    payment_checks = {
        item.get("key"): item
        for item in categories.get("payment_entitlements", {}).get("checks", [])
        if isinstance(item, dict)
    }
    if payment_checks.get("public_charging_owner_approval", {}).get("earned_points") != 0:
        return fail(f"public charging approval must remain 0/4: {payment_checks.get('public_charging_owner_approval')}")
    if categories.get("platform_reliability", {}).get("earned_points") != 13:
        return fail(f"current backup and monitoring evidence must keep reliability at 13/20: {categories.get('platform_reliability')}")
    if categories.get("ebay_production", {}).get("earned_points") != 0:
        return fail(f"missing current account, secret and refresh proof must keep eBay at 0/20: {categories.get('ebay_production')}")

    actions = {item.get("key"): item for item in packet.get("remaining_actions", []) if isinstance(item, dict)}
    for key in ("public_charging_owner_approval", "ebay_current_secret_ref", "ebay_refresh_success_proof"):
        if key not in actions:
            return fail(f"remaining action missing: {key}")
    if actions["public_charging_owner_approval"].get("executor") != "joint_confirmation":
        return fail("public charging must remain joint confirmation work")
    if actions["ebay_current_secret_ref"].get("executor") != "founder_external":
        return fail("current eBay account connection must remain external founder work")
    custody_blocked = fixture(backup_status="blocked_vault_unseal_custody_not_ready")
    custody_actions = {
        item.get("key"): item
        for item in custody_blocked.get("remaining_actions", [])
        if isinstance(item, dict)
    }
    custody_action = custody_actions.get("backup_restore_ready") or {}
    if custody_action.get("executor") != "joint_confirmation" or custody_action.get("actionable_now") is not False:
        return fail(f"offline Vault-share custody must not be routed as autonomous code work: {custody_action}")
    post_publish_blocked = fixture(post_publish_ready=False)
    post_publish_actions = {
        item.get("key"): item
        for item in post_publish_blocked.get("remaining_actions", [])
        if isinstance(item, dict)
    }
    post_publish_action = post_publish_actions.get("post_publish_cockpit_ready") or {}
    if post_publish_action.get("executor") != "joint_confirmation" or post_publish_action.get("actionable_now") is not False:
        return fail(
            "post-publish proof must wait for a separately confirmed real listing and cleanup sequence: "
            f"{post_publish_action}"
        )
    final_smoke = actions.get("final_commercial_smoke_ready") or {}
    if final_smoke.get("actionable_now") is not False:
        return fail(f"final commercial smoke must wait for external production evidence: {final_smoke}")
    next_internal = packet.get("next_autonomous_action") or {}
    if next_internal.get("key") != "monitoring_alerting_ready" or next_internal.get("executor") != "codex_internal":
        return fail(f"monitoring reliability must remain the next autonomous internal task: {next_internal}")

    reliability_without_ebay_account = fixture(reliability_ready=True)
    reliability_actions = {
        item.get("key"): item
        for item in reliability_without_ebay_account.get("remaining_actions", [])
        if isinstance(item, dict)
    }
    for key in ("official_ebay_read_loop_ready", "store_sync_visibility_ready"):
        if reliability_actions.get(key, {}).get("actionable_now") is not False:
            return fail(f"{key} must wait for a current backend eBay secret reference: {reliability_actions.get(key)}")
    if reliability_without_ebay_account.get("next_autonomous_action") is not None:
        return fail(
            "fixed progress must not route Codex into eBay sync when the current account authorization is absent: "
            f"{reliability_without_ebay_account.get('next_autonomous_action')}"
        )

    reliability_with_ebay_account = fixture(reliability_ready=True, ebay_secret_refs=1)
    authorized_next = reliability_with_ebay_account.get("next_autonomous_action") or {}
    if authorized_next.get("key") != "official_ebay_read_loop_ready":
        return fail(f"current backend eBay authorization should unlock the read-only proof route: {authorized_next}")

    browser_pending = fixture(browser_smoke_passed=False)
    if browser_pending.get("score_percent") != 56:
        return fail(f"real evidence regression should reduce only its fixed points: {browser_pending.get('score_percent')}")
    next_action = browser_pending.get("next_autonomous_action") or {}
    if next_action.get("key") != "browser_smoke_evidence" or next_action.get("executor") != "codex_internal":
        return fail(f"Codex should automatically select the highest pending internal task: {next_action}")

    serialized = str(packet).lower()
    for forbidden in ("api_key", "client_secret", "refresh_token", "access_token", "payment_secret"):
        if forbidden in serialized:
            return fail(f"fixed progress must not expose secret-like fields: {forbidden}")

    print("PASS jiejing_fixed_launch_progress")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
