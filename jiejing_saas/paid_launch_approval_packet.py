"""Owner approval packet for paid public launch readiness."""

from __future__ import annotations

import os
from typing import Any

from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .billing_payment_options import (
    build_mainland_payment_launch_status,
    validate_mainland_payment_launch_for_public,
)
from .commercial_launch_gate import build_commercial_launch_gate
from .config import SaaSSettings
from .domain_readiness import build_domain_readiness
from .readiness import build_product_readiness_or_degraded
from .repository import SaaSRepository


PRIMARY_SEQUENCE = [
    "stable_domain_hardening",
    "wechat_pay_native_cutover",
    "no_charge_launch_rehearsal",
    "new_ebay_account_low_risk_smoke",
]


def build_paid_launch_approval_packet(
    settings: SaaSSettings,
    repository: SaaSRepository,
    *,
    company_id: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    """Build a read-only packet that shows exactly what blocks public charging."""

    raw_readiness = build_product_readiness_or_degraded(settings, repository)
    readiness = raw_readiness if isinstance(raw_readiness, dict) else {}
    readiness_contract_valid = isinstance(raw_readiness, dict) and all(
        type(readiness.get(key)) is bool
        for key in ("production_ready", "beta_ready", "can_accept_real_customers")
    )
    domain = build_domain_readiness(settings)
    launch_gate = build_commercial_launch_gate(
        settings,
        repository,
        company_id=company_id,
        store_id=store_id,
    )
    rehearsal = build_billing_domain_cutover_rehearsal(settings, repository)
    mainland_payment = build_mainland_payment_launch_status(settings, repository)
    no_charge = _no_charge_launch_rehearsal_status()
    action_plan = launch_gate.get("launch_action_plan") if isinstance(launch_gate.get("launch_action_plan"), dict) else {}
    new_account = action_plan.get("new_ebay_account_smoke_runbook") if isinstance(action_plan.get("new_ebay_account_smoke_runbook"), list) else []
    current_store_oauth_boundary = (
        launch_gate.get("current_store_oauth_boundary")
        if isinstance(launch_gate.get("current_store_oauth_boundary"), dict)
        else {}
    )
    current_store_ebay_evidence = (
        launch_gate.get("current_store_ebay_evidence")
        if isinstance(launch_gate.get("current_store_ebay_evidence"), dict)
        else {}
    )
    oauth_store_hash = str(current_store_oauth_boundary.get("store_id_sha256") or "")
    oauth_connection_hash = str(current_store_oauth_boundary.get("connection_id_sha256") or "")
    current_store_hashes_match = bool(
        oauth_store_hash
        and oauth_connection_hash
        and oauth_store_hash == str(current_store_ebay_evidence.get("store_id_sha256") or "")
        and oauth_connection_hash == str(current_store_ebay_evidence.get("connection_id_sha256") or "")
    )
    steps = _build_steps(
        domain=domain,
        mainland_payment=mainland_payment,
        no_charge=no_charge,
        new_account=new_account,
    )
    if not readiness_contract_valid:
        steps = [
            {
                **step,
                "status": "blocked",
                "severity": "blocker",
                "blocked_by": [
                    *(
                        [str(item) for item in step.get("blocked_by", []) if isinstance(item, str)]
                        if isinstance(step.get("blocked_by"), list)
                        else []
                    ),
                    "readiness_contract_invalid",
                ],
            }
            if step.get("key") == "no_charge_launch_rehearsal"
            else step
            for step in steps
        ]
    if not current_store_hashes_match:
        steps = [
            {
                **step,
                "status": "blocked",
                "severity": "blocker",
                "blocked_by": [
                    *(
                        [str(item) for item in step.get("blocked_by", []) if isinstance(item, str)]
                        if isinstance(step.get("blocked_by"), list)
                        else []
                    ),
                    "current_store_oauth_evidence_binding_mismatch",
                ],
            }
            if step.get("key") == "new_ebay_account_low_risk_smoke"
            else step
            for step in steps
        ]
    blocked = [step for step in steps if step.get("status") != "ready"]
    user_items = _external_configuration_items(
        steps=steps,
        domain=domain,
        mainland_payment=mainland_payment,
        no_charge=no_charge,
        new_account=new_account,
    )
    future_international_payment = _future_international_payment(mainland_payment)
    return {
        "contract_version": "2026-07-27-paid-launch-approval-packet-v2",
        "mode": "owner_approval_packet_no_charge_no_write",
        "environment": settings.environment,
        "status": "ready_for_owner_approval" if not blocked else "blocked",
        "ready_for_owner_approval": not blocked,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "old_frozen_ebay_account_reuse_allowed": False,
        "old_demo_product_or_sku_allowed": False,
        "summary": {
            "ready_count": len(steps) - len(blocked),
            "total_count": len(steps),
            "blocked_count": len(blocked),
            "blocked_keys": [str(step.get("key") or "") for step in blocked],
            "next_step": str((blocked[0] if blocked else {}).get("key") or ""),
            "production_ready": readiness.get("production_ready") is True,
            "beta_ready": readiness.get("beta_ready") is True,
            "can_accept_real_customers": readiness.get("can_accept_real_customers") is True,
            "stable_domain_ready": domain.get("production_domain_ready") is True,
            "mainland_payment_status": validate_mainland_payment_launch_for_public(mainland_payment).get(
                "payment_path_status"
            ),
            "mainland_payment_ready_for_owner_approval": validate_mainland_payment_launch_for_public(
                mainland_payment
            ).get("mainland_payment_ready_for_owner_approval")
            is True,
            "stripe_rehearsal_status": rehearsal.get("status") or "unknown",
            "stripe_rehearsal_status_deprecated": True,
            "no_charge_evidence_packet_status": "ready" if no_charge.get("ready") is True else "blocked",
            "new_account_smoke_ready": _all_ready(new_account),
            "external_configuration_needed_count": len([item for item in user_items if item.get("status") != "ready"]),
        },
        "steps": steps,
        "new_ebay_account_smoke_runbook": new_account,
        "current_store_oauth_boundary": current_store_oauth_boundary,
        "current_store_ebay_evidence": current_store_ebay_evidence,
        "external_configuration_needed": user_items,
        "future_international_payment": future_international_payment,
        "agent_completed_before_user_intervention": [
            "read_only_paid_launch_approval_packet_contract",
            "stable_domain_dns_tls_callback_evidence_slots",
            "wechat_pay_native_backend_only_cutover_contract",
            "signed_payment_and_refund_callback_contract",
            "controlled_acceptance_evidence_contract",
            "subscription_state_quota_lifecycle_regressions",
            "new_ebay_account_low_risk_smoke_runbook",
            "settings_launch_gate_visibility",
        ],
        "final_rehearsal_commands": [
            "python tools/test_jiejing_paid_launch_approval_packet.py",
            "python tools/test_jiejing_domain_launch_gate.py",
            "python tools/test_jiejing_billing_domain_cutover_rehearsal.py",
            "python tools/test_jiejing_new_ebay_account_low_risk_runbook.py",
            "python tools/jiejing_secret_scan.py",
            "node tools/codex_jiejing_paid_cutover_decision_smoke.js",
        ],
        "evidence_register": [
            "/health",
            "/health/deep",
            "/readiness/product-saas",
            "/domain/status",
            "/billing/plans",
            "/billing/domestic/orders",
            "/billing/domestic/wechat-pay/notify",
            "/billing/domestic/wechat-pay/refund-notify",
            "/commercial/launch-gate",
            "/owner/paid-launch-approval-packet",
            "tools/jiejing_wechat_pay_acceptance_verify.py",
            "tools/jiejing_new_ebay_account_low_risk_check.py --checklist-only",
        ],
        "docs": [
            "docs/superpowers/specs/2026-07-13-wechat-pay-native-design.md",
            "docs/JIEJING_WECHAT_PAY_PRODUCTION_RUNBOOK_20260713.md",
            "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/",
            "https://developer.ebay.com/develop/guides-v2/authorization",
        ],
        "rollback_controls": [
            "keep_trycloudflare_staging_available_until_stable_domain_smoke_passes",
            "do_not_enable_public_checkout_until_owner_approval",
            "disable_wechat_public_charge_switch_if_signed_callback_or_query_smoke_fails",
            "keep_real_ebay_writes_confirmation_gated_after_billing_cutover",
            "never_retry_platform_write_after_timeout_without_platform_state_check",
        ],
        "secret_exposed": False,
    }


def _build_steps(
    *,
    domain: dict[str, Any],
    mainland_payment: dict[str, Any],
    no_charge: dict[str, Any],
    new_account: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payment = validate_mainland_payment_launch_for_public(mainland_payment)
    payment_ready = payment.get("mainland_payment_ready_for_owner_approval") is True
    payment_blockers = _mainland_payment_blockers(mainland_payment, fallback=payment.get("next_paid_launch_blocker"))
    no_charge_blockers = [
        str(item)
        for item in no_charge.get("blocked_by") or []
        if isinstance(item, str) and item
    ]
    return [
        _step(
            "stable_domain_hardening",
            "Stable domain, DNS, TLS, CORS and callback hardening",
            bool(domain.get("production_domain_ready")),
            category="domain",
            owner="platform_ops",
            evidence_summary=_evidence(
                domain=domain.get("stable_domain") or "not_selected",
                dns=bool(domain.get("dns_verified")),
                tls=bool(domain.get("tls_verified")),
                callback=bool(domain.get("ebay_callback_verified")),
                cors=bool(domain.get("cors_origin_aligned")),
                headers=bool(domain.get("security_headers_verified")),
            ),
            next_action="Bind a stable HTTPS domain, verify DNS/TLS/security headers, align CORS and update the eBay callback URL.",
            verification=["/domain/status", "/health/deep", "tools/test_jiejing_domain_launch_gate.py"],
            external_resource_required=True,
            blocked_by=domain.get("blockers") if isinstance(domain.get("blockers"), list) else [],
        ),
        _step(
            "wechat_pay_native_cutover",
            "WeChat Pay Native production prerequisites and controlled acceptance",
            payment_ready,
            category="billing",
            owner="platform_ops",
            evidence_summary=_evidence(
                provider="wechat_pay_native",
                checkout_mode="native_qr",
                configuration=(
                    f"{payment.get('configured_component_count', 0)}/"
                    f"{payment.get('required_component_count', 0)}"
                ),
                controlled_acceptance=payment.get("controlled_acceptance_proven") is True,
                verified_payments=payment.get("verified_paid_order_count", 0),
                status=payment.get("payment_path_status") or "payment_status_unavailable",
            ),
            next_action=(
                "Complete backend-only WeChat merchant credentials, signed payment/refund callbacks, "
                "authenticated query, controlled acceptance and refund proof."
            ),
            verification=[
                "/readiness/product-saas",
                "/billing/plans",
                "tools/jiejing_wechat_pay_acceptance_verify.py",
            ],
            external_resource_required=True,
            blocked_by=[] if payment_ready else payment_blockers,
        ),
        _step(
            "no_charge_launch_rehearsal",
            "No-charge full launch rehearsal and rollback packet",
            no_charge.get("ready") is True,
            category="release",
            owner="release_manager",
            evidence_summary=_evidence(
                public_paid_launch_allowed=False,
                evidence_packet="ready" if no_charge.get("ready") is True else "blocked",
                evidence_packet_ready=(
                    f"{no_charge.get('ready_count', 0)}/{no_charge.get('total_count', 0)}"
                ),
            ),
            next_action=(
                "Run final no-charge register/login/domain/WeChat callback/readiness/secret-scan/browser smoke "
                "and record rollback evidence."
            ),
            verification=["/commercial/launch-gate", "tools/jiejing_secret_scan.py", "output/browser-smoke"],
            external_resource_required=False,
            blocked_by=no_charge_blockers,
        ),
        _step(
            "new_ebay_account_low_risk_smoke",
            "Clean new eBay account low-risk smoke runbook",
            _all_ready(new_account),
            category="ebay",
            owner="founder_operator",
            evidence_summary=_evidence(
                ready=f"{sum(1 for item in new_account if isinstance(item, dict) and item.get('status') == 'ready')}/{len(new_account)}",
                old_frozen_account_reuse_allowed=False,
                old_demo_product_or_sku_allowed=False,
            ),
            next_action="Wait for the owner to provide a clean new eBay account, then run OAuth, packet, health, fresh product, confirmation, publish probe and cleanup in order.",
            verification=["tools/jiejing_new_ebay_account_low_risk_check.py --checklist-only", "/commercial/launch-gate"],
            external_resource_required=True,
            blocked_by=[str(item.get("key") or "") for item in new_account if isinstance(item, dict) and item.get("status") != "ready"],
        ),
    ]


def _external_configuration_items(
    *,
    steps: list[dict[str, Any]],
    domain: dict[str, Any],
    mainland_payment: dict[str, Any],
    no_charge: dict[str, Any],
    new_account: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    step_by_key = _by_key(steps)
    payment = validate_mainland_payment_launch_for_public(mainland_payment)
    return [
        _external_item(
            "stable_domain_dns_tls_callback",
            "Stable domain DNS/TLS/CORS/eBay callback",
            (step_by_key.get("stable_domain_hardening") or {}).get("status") == "ready",
            env_keys=[
                "JIEJING_PUBLIC_BASE_URL",
                "JIEJING_STABLE_DOMAIN",
                "JIEJING_CORS_ORIGIN",
                "JIEJING_DOMAIN_DNS_VERIFIED",
                "JIEJING_TLS_VERIFIED",
                "JIEJING_EBAY_CALLBACK_VERIFIED",
                "JIEJING_DEPLOYMENT_HARDENED",
                "JIEJING_SECURITY_HEADERS_VERIFIED",
            ],
            evidence=_evidence(domain=domain.get("stable_domain") or "not_selected", blockers=",".join(domain.get("blockers") or [])),
        ),
        _external_item(
            "wechat_pay_native_production_cutover",
            "WeChat Pay Native backend credentials, signed callbacks, query and refund controls",
            (step_by_key.get("wechat_pay_native_cutover") or {}).get("status") == "ready",
            env_keys=[
                "JIEJING_SAAS_ENV",
                "JIEJING_WECHAT_PAY_APP_ID",
                "JIEJING_WECHAT_PAY_MCH_ID",
                "JIEJING_WECHAT_PAY_MERCHANT_SERIAL_NO",
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM",
                "JIEJING_WECHAT_PAY_MERCHANT_PRIVATE_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_API_V3_KEY",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_PEM_B64",
                "JIEJING_WECHAT_PAY_PUBLIC_KEY_ID",
                "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM",
                "JIEJING_WECHAT_PAY_PLATFORM_CERTIFICATE_PEM_B64",
                "JIEJING_WECHAT_PAY_PLATFORM_SERIAL_NO",
                "JIEJING_WECHAT_PAY_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_REFUND_NOTIFY_URL",
                "JIEJING_WECHAT_PAY_LIVE_API_ENABLED",
                "JIEJING_WECHAT_PAY_REFUND_ALLOWED",
            ],
            evidence=_evidence(
                configured=(
                    f"{payment.get('configured_component_count', 0)}/"
                    f"{payment.get('required_component_count', 0)}"
                ),
                provider_configured=payment.get("provider_configured") is True,
                controlled_acceptance=payment.get("controlled_acceptance_proven") is True,
                refund_ready=(
                    isinstance(mainland_payment, dict)
                    and mainland_payment.get("refund_now_allowed") is True
                ),
                production_environment=(
                    isinstance(mainland_payment, dict)
                    and mainland_payment.get("production_environment") is True
                ),
            ),
        ),
        _external_item(
            "no_charge_rehearsal_evidence_flags",
            "No-charge rehearsal evidence flags",
            (step_by_key.get("no_charge_launch_rehearsal") or {}).get("status") == "ready",
            env_keys=[
                *list(no_charge.get("environment_keys") or []),
            ],
            evidence=_evidence(
                evidence_packet_status="ready" if no_charge.get("ready") is True else "blocked",
                evidence_packet_ready=(
                    f"{no_charge.get('ready_count', 0)}/{no_charge.get('total_count', 0)}"
                ),
                evidence_packet_blocked=",".join(
                    str(item) for item in no_charge.get("blocked_by") or [] if isinstance(item, str)
                ),
            ),
            external_resource_required=False,
        ),
        _external_item(
            "clean_new_ebay_account_and_fresh_product",
            "Clean new eBay account plus fresh product/SKU/assets",
            _all_ready(new_account),
            env_keys=[
                "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
                "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
                "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
                "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
                "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
                "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
                "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
                "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
                "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
                "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
            ],
            evidence="old frozen account and old demo product/SKU/assets remain forbidden",
        ),
    ]


def _no_charge_launch_rehearsal_status() -> dict[str, Any]:
    checks = (
        ("cutover_rollback_not_verified", "JIEJING_CUTOVER_ROLLBACK_VERIFIED", "bool"),
        ("secret_scan_not_verified", "JIEJING_SECRET_SCAN_PASSED", "bool"),
        ("readiness_snapshot_not_recorded", "JIEJING_READINESS_SNAPSHOT_RECORDED", "bool"),
        ("browser_smoke_not_verified", "JIEJING_BROWSER_SMOKE_PASSED", "bool"),
        ("cutover_rollback_audit_packet_missing", "JIEJING_CUTOVER_ROLLBACK_AUDIT_PACKET_ID", "present"),
        ("signed_payment_callback_smoke_not_verified", "JIEJING_NO_CHARGE_SIGNED_WEBHOOK_SMOKE_PASSED", "bool"),
        ("readiness_smoke_not_verified", "JIEJING_NO_CHARGE_READINESS_SMOKE_PASSED", "bool"),
        (
            "no_charge_live_domain_rehearsal_evidence_missing",
            "JIEJING_NO_CHARGE_LIVE_DOMAIN_REHEARSAL_EVIDENCE_ID",
            "present",
        ),
        ("final_commercial_smoke_not_verified", "JIEJING_FINAL_COMMERCIAL_SMOKE_PASSED", "bool"),
        ("final_commercial_smoke_evidence_missing", "JIEJING_FINAL_COMMERCIAL_SMOKE_EVIDENCE_ID", "present"),
    )
    readiness: list[bool] = []
    blocked_by: list[str] = []
    for blocker, environment_key, mode in checks:
        ready = _env_true(environment_key) if mode == "bool" else bool(os.environ.get(environment_key, "").strip())
        readiness.append(ready)
        if not ready:
            blocked_by.append(blocker)
    return {
        "ready": all(readiness),
        "ready_count": sum(1 for ready in readiness if ready),
        "total_count": len(readiness),
        "blocked_by": blocked_by,
        "environment_keys": [environment_key for _, environment_key, _ in checks],
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "calls_external_payment_api": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
    }


def _future_international_payment(mainland_payment: dict[str, Any]) -> dict[str, Any]:
    future = (
        mainland_payment.get("future_international_payment")
        if isinstance(mainland_payment, dict)
        and isinstance(mainland_payment.get("future_international_payment"), dict)
        else {}
    )
    return {
        "provider": "stripe",
        "role": "future_international_payment_only",
        "selected": future.get("selected") is True,
        "blocks_mainland_launch": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "secret_exposed": False,
        "docs": [
            "https://docs.stripe.com/api/versioning",
            "https://docs.stripe.com/billing/quickstart",
            "https://docs.stripe.com/webhooks/signature",
        ],
    }


def _mainland_payment_blockers(mainland_payment: dict[str, Any], *, fallback: Any) -> list[str]:
    ignored = {
        "paid_launch_owner_approval_packet_missing",
        "public_charging_requires_higher_commercial_release_gate",
    }
    blockers: list[str] = []
    raw = mainland_payment.get("paid_launch_blockers") if isinstance(mainland_payment, dict) else []
    if isinstance(raw, list):
        for item in raw:
            blocker = str(item or "").strip()
            if (
                blocker
                and blocker not in ignored
                and "stripe" not in blocker.lower()
                and len(blocker) <= 160
            ):
                blockers.append(blocker)
    fallback_blocker = str(fallback or "merchant_payment_status_unavailable").strip()
    if not blockers and fallback_blocker and "stripe" not in fallback_blocker.lower():
        blockers.append(fallback_blocker[:160])
    return list(dict.fromkeys(blockers))


def _env_true(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _step(
    key: str,
    title: str,
    ready: bool,
    *,
    category: str,
    owner: str,
    evidence_summary: str,
    next_action: str,
    verification: list[str],
    external_resource_required: bool,
    blocked_by: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "category": category,
        "owner": owner,
        "evidence_summary": evidence_summary,
        "next_action": next_action,
        "verification": verification,
        "blocked_by": [str(item) for item in blocked_by if str(item)],
        "external_resource_required": external_resource_required,
        "creates_checkout_session": False,
        "calls_stripe_api": False,
        "triggers_real_charge": False,
        "charge_now_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_ebay_oauth_allowed": False,
        "triggers_real_platform_write": False,
        "frontend_gets_payment_secret": False,
        "frontend_gets_ebay_token": False,
        "secret_exposed": False,
    }


def _external_item(
    key: str,
    title: str,
    ready: bool,
    *,
    env_keys: list[str],
    evidence: str,
    external_resource_required: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": "ready" if ready else "blocked",
        "severity": "info" if ready else "blocker",
        "environment_keys": env_keys,
        "evidence_summary": evidence,
        "external_resource_required": external_resource_required,
        "secret_values_required_in_backend_only": True,
        "secret_value_returned": False,
        "frontend_gets_secret": False,
        "secret_exposed": False,
    }


def _by_key(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("key") or ""): item for item in items if isinstance(item, dict)}


def _all_ready(items: list[dict[str, Any]]) -> bool:
    return bool(items) and all(isinstance(item, dict) and item.get("status") == "ready" for item in items)


def _evidence(**values: Any) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())
