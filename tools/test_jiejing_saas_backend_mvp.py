#!/usr/bin/env python3
"""End-to-end regression for the local Jiejing SaaS backend MVP."""

from __future__ import annotations

import json
import http.client
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_TEMP_ROOT = tempfile.TemporaryDirectory(prefix="jiejing-saas-backend-test-")
OUT = Path(_TEMP_ROOT.name)
SAAS_DB = OUT / "saas-test.sqlite"
RUNTIME_DB = OUT / "runtime-test.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    from jiejing_saas.api_server import SaaSBackendHandler

    internal_plan = {
        "contract_version": "merchant-plan-test-v1",
        "environment": "production-internal-marker",
        "current_usage_shape": {"users": 99, "evidence_id": "internal-usage-marker"},
        "billing_ready_for_private_beta": True,
        "billing_ready_for_paid_launch": False,
        "provider": {
            "selected": "stripe",
            "checkout_mode": "hosted",
            "signed_webhook_contract": {"secret_ref": "internal-webhook-marker"},
            "checkout_portal_contract": {"price_id": "internal-price-marker"},
            "environment_keys": ["INTERNAL_PAYMENT_KEY"],
        },
        "plan_catalog": [
            {
                "key": "starter",
                "label": "Starter",
                "amount_minor": 9900,
                "currency": "CNY",
                "duration_days": 30,
                "monthly_task_quota": 100,
                "includes_real_platform_writes": False,
                "provider_plan_id": "internal-provider-plan-marker",
                "nested": {"secret_ref": "internal-plan-secret-marker"},
            }
        ],
        "add_on_catalog": [
            {
                "key": "extra_store_30d",
                "label": "Extra store",
                "amount_minor": 3900,
                "currency": "CNY",
                "duration_days": 30,
                "provider_price_id": "internal-addon-price-marker",
            }
        ],
        "quota_contract": {
            "enabled": True,
            "merchant_visible_usage_required": True,
            "hard_stop_on_quota_exhaustion": True,
            "environment_keys": ["INTERNAL_QUOTA_KEY"],
        },
        "mainland_payment_launch": {
            "contract_version": "2026-07-27-mainland-payment-launch-v1",
            "market": "mainland_china",
            "primary_provider": "wechat_pay_native",
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "configuration": {"complete": True, "completed_count": 9, "required_count": 9},
            "controlled_acceptance_proven": True,
            "provider_checkout_ready": True,
            "production_environment": True,
            "refund_now_allowed": True,
            "mainland_payment_ready_for_owner_approval": True,
            "code_capabilities": {
                "signed_payment_callback_implemented": True,
                "signed_refund_callback_implemented": True,
                "real_order_creation_implemented": True,
                "authenticated_order_query_implemented": True,
                "quota_entitlement_persistence_implemented": True,
                "high_risk_confirmation_boundary_implemented": True,
            },
            "acceptance_evidence": {
                "contract_version": "2026-07-27-domestic-payment-acceptance-evidence-v2",
                "provider": "wechat_pay_native",
                "acceptance_kind": "owner_approved_one_cny_live_acceptance",
                "controlled_acceptance_proven": True,
                "verified_paid_order_count": 1,
                "public_charging_allowed": False,
                "charge_now_allowed": False,
                "triggers_real_charge": False,
                "calls_external_payment_api": False,
                "secret_exposed": False,
            },
            "component_presence": {"merchant_private_key_ref": "internal-ref-marker"},
            "paid_launch_blockers": ["internal-blocker-marker"],
            "order_reference": "internal-order-marker",
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "calls_stripe_api": False,
            "real_platform_writes_enabled": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "mainland_payment_ready_for_owner_approval": True,
        "future_international_payment": {"provider_reference": "internal-provider-marker"},
        "merchant_launch_path": {
            "contract_version": "merchant-path-test-v1",
            "current_stage": "internal-launch-stage",
            "headline": "internal launch headline",
            "next_paid_launch_blocker": "raw_internal_launch_blocker",
            "environment_keys": ["INTERNAL_LAUNCH_KEY"],
            "quota_enforcement_enabled": True,
        },
        "confirmation_boundary": {
            "billing_changes_need_owner_or_admin": True,
            "real_platform_writes_not_included_in_any_current_plan": True,
            "refunds_and_payment_disputes_need_human_operator": True,
            "evidence_id": "internal-confirmation-marker",
        },
        "billing_test_rehearsal_summary": {"evidence_id": "internal-rehearsal-marker"},
        "customer_billing_trust_packet": {"provider_reference": "internal-trust-marker"},
        "blockers": ["raw-internal-blocker"],
        "paid_launch_blockers": ["raw-internal-paid-blocker"],
        "next_actions": ["internal-next-action"],
        "real_platform_writes_enabled": False,
        "customer_visible": False,
        "internal_launch_evidence_visible": True,
        "secret_exposed": True,
    }
    original_plan = json.loads(json.dumps(internal_plan))
    merchant_safe_plan = SaaSBackendHandler._merchant_safe_billing_plan(internal_plan)
    if internal_plan != original_plan:
        return fail("merchant billing-plan sanitizer must not mutate the platform-internal source plan")
    for internal_launch_key in {
        "mainland_payment_launch",
        "mainland_payment_ready_for_owner_approval",
        "future_international_payment",
    }:
        if internal_launch_key in merchant_safe_plan:
            return fail(f"merchant billing-plan sanitizer exposes internal launch key {internal_launch_key}")
    if merchant_safe_plan.get("customer_visible") is not True:
        return fail("merchant billing-plan sanitizer must preserve customer_visible=true")
    if merchant_safe_plan.get("internal_launch_evidence_visible") is not False:
        return fail("merchant billing-plan sanitizer must preserve internal_launch_evidence_visible=false")
    if merchant_safe_plan.get("secret_exposed") is not False:
        return fail("merchant billing-plan sanitizer must preserve secret_exposed=false")
    expected_top_level = {
        "contract_version",
        "billing_ready_for_private_beta",
        "billing_ready_for_paid_launch",
        "provider",
        "plan_catalog",
        "add_on_catalog",
        "quota_contract",
        "mainland_payment",
        "merchant_launch_path",
        "paid_launch_blockers",
        "billing_test_rehearsal_summary",
        "subscription_quota_shutdown_closure",
        "billing_incident_runbook",
        "customer_billing_trust_packet",
        "confirmation_boundary",
        "public_charging_allowed",
        "charge_now_allowed",
        "triggers_real_charge",
        "triggers_real_refund",
        "calls_external_payment_api",
        "real_platform_writes_enabled",
        "frontend_gets_payment_secret",
        "frontend_can_grant_entitlement",
        "frontend_can_grant_quota",
        "customer_visible",
        "internal_launch_evidence_visible",
        "secret_exposed",
    }
    if set(merchant_safe_plan) != expected_top_level:
        return fail(f"merchant billing plan must be a fresh top-level allowlist: {set(merchant_safe_plan)}")
    if merchant_safe_plan.get("provider") != {
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "available": False,
        "provider_configured": True,
        "customer_visible": True,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }:
        return fail(f"merchant provider payload must use only mainland merchant semantics: {merchant_safe_plan.get('provider')}")
    safe_catalog = merchant_safe_plan.get("plan_catalog", [])
    if safe_catalog != [
        {
            "key": "starter",
            "label": "Starter",
            "amount_minor": 9900,
            "currency": "CNY",
            "duration_days": 30,
            "monthly_task_quota": 100,
            "includes_real_platform_writes": False,
        }
    ]:
        return fail(f"merchant plan catalog must include only allowlisted price and quota fields: {safe_catalog}")
    merchant_safe_plan["plan_catalog"][0]["label"] = "merchant-copy-mutated"
    merchant_safe_plan["quota_contract"]["enabled"] = False
    if internal_plan != original_plan:
        return fail("nested merchant billing-plan values must not share mutable objects with the internal source")
    serialized_merchant_plan = json.dumps(merchant_safe_plan, ensure_ascii=False)
    if any(
        marker in serialized_merchant_plan
        for marker in {
            "internal-ref-marker",
            "internal-blocker-marker",
            "internal-order-marker",
            "internal-provider-marker",
            "production-internal-marker",
            "internal-usage-marker",
            "internal-webhook-marker",
            "internal-price-marker",
            "internal-provider-plan-marker",
            "internal-plan-secret-marker",
            "internal-addon-price-marker",
            "internal-rehearsal-marker",
            "internal-trust-marker",
            "raw-internal-blocker",
        }
    ):
        return fail("merchant billing-plan sanitizer leaked internal launch evidence")

    malformed_merchant_variants: list[tuple[str, dict[str, Any]]] = []
    for field, invalid_value in (
        ("contract_version", "wrong-contract"),
        ("market", "international"),
        ("primary_provider", "stripe"),
        ("refund_now_allowed", "true"),
        ("mainland_payment_ready_for_owner_approval", "true"),
    ):
        candidate = json.loads(json.dumps(internal_plan))
        candidate["mainland_payment_launch"][field] = invalid_value
        malformed_merchant_variants.append((field, candidate))
    invalid_merchant_count = json.loads(json.dumps(internal_plan))
    invalid_merchant_count["mainland_payment_launch"]["configuration"]["completed_count"] = 9.0
    malformed_merchant_variants.append(("completed_count_float", invalid_merchant_count))
    invalid_merchant_acceptance = json.loads(json.dumps(internal_plan))
    invalid_merchant_acceptance["mainland_payment_launch"]["acceptance_evidence"]["acceptance_kind"] = "uncontrolled"
    malformed_merchant_variants.append(("acceptance_kind", invalid_merchant_acceptance))
    for label, candidate in malformed_merchant_variants:
        malformed_safe = SaaSBackendHandler._merchant_safe_billing_plan(candidate)
        payment = malformed_safe.get("mainland_payment", {})
        if (
            payment.get("status") != "unavailable"
            or payment.get("mainland_payment_ready_for_owner_approval") is not False
            or payment.get("provider_configured") is not False
            or payment.get("configured_component_count") != 0
            or payment.get("verified_paid_order_count") != 0
        ):
            return fail(f"malformed merchant payment contract must fail closed ({label}): {payment}")

    refund_blocked_plan = json.loads(json.dumps(internal_plan))
    refund_blocked_plan["mainland_payment_launch"]["refund_now_allowed"] = False
    refund_blocked = SaaSBackendHandler._merchant_safe_billing_plan(refund_blocked_plan).get("mainland_payment", {})
    if (
        refund_blocked.get("status") != "refund_controls_pending"
        or refund_blocked.get("next_blocker") != "merchant_payment_refund_not_ready"
        or refund_blocked.get("mainland_payment_ready_for_owner_approval") is not False
    ):
        return fail(f"historical payment proof must not hide current refund control loss: {refund_blocked}")

    public_billing_source = {
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "provider_configured": True,
        "payment_path_status": "controlled_acceptance_proven_public_charging_closed",
        "mainland_payment_ready_for_owner_approval": True,
        "billing_ready_for_private_beta": False,
        "billing_ready_for_paid_launch": False,
        "configured_component_count": 9,
        "required_component_count": 9,
        "verified_paid_order_count": 1,
        "quota_enforcement_enabled": True,
        "next_paid_launch_blocker": "merchant_payment_public_cutover_not_approved",
        "merchant_launch_path": {
            "contract_version": "2026-07-27-merchant-mainland-payment-path-v1",
            "current_stage": "controlled_acceptance_proven_public_charging_closed",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "secret_exposed": False,
        },
        "domestic_payment": {
            "provider": "wechat_pay_native",
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "status": "controlled_acceptance_proven",
            "configured_component_count": 9,
            "required_component_count": 9,
            "verified_paid_order_count": 1,
            "controlled_acceptance_proven": True,
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_payment_secret": False,
        "frontend_can_grant_quota": False,
        "secret_exposed": False,
        "external_paid_provider_configured": True,
        "test_billing_provider_configured": True,
        "signed_webhook_configured": True,
    }
    malformed_public_readiness = {
        "production_ready": "true",
        "beta_ready": 1,
        "can_accept_real_customers": 1.0,
        "real_platform_writes_enabled": "false",
        "requested_real_platform_writes": True,
        "blocker_count": True,
        "warning_count": -1,
        "product_evidence": {"ebay_token_refresh_success_count": 1.0},
        "provider_status": {"billing": public_billing_source},
    }
    public_summary = SaaSBackendHandler._public_readiness_summary(malformed_public_readiness, authenticated=False)
    if any(
        public_summary.get(key) is not False
        for key in ("production_ready", "beta_ready", "can_accept_real_customers", "real_platform_writes_enabled")
    ):
        return fail(f"public readiness booleans must not coerce strings or numbers: {public_summary}")
    if public_summary.get("blocker_count") != 0 or public_summary.get("warning_count") != 0:
        return fail(f"public readiness counts must reject bool/negative values: {public_summary}")
    public_billing = public_summary.get("provider_status", {}).get("billing", {})
    for stale_key in (
        "external_paid_provider_configured",
        "test_billing_provider_configured",
        "checkout_ready",
        "customer_portal_ready",
        "signed_webhook_configured",
    ):
        if stale_key in public_billing:
            return fail(f"public readiness must not expose stale provider diagnostics: {stale_key}")
    malformed_public_readiness["provider_status"]["billing"]["configured_component_count"] = "9"
    malformed_payment_summary = SaaSBackendHandler._public_readiness_summary(
        malformed_public_readiness,
        authenticated=False,
    ).get("provider_status", {}).get("billing", {})
    if (
        malformed_payment_summary.get("payment_path_status") != "payment_status_unavailable"
        or malformed_payment_summary.get("mainland_payment_ready_for_owner_approval") is not False
        or malformed_payment_summary.get("configured_component_count") != 0
    ):
        return fail(f"public billing counts must fail closed without coercion: {malformed_payment_summary}")

    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()

    port = find_free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if wait_for_health(base_url):
            return fail("saas backend did not become healthy")

        health = fetch_json(f"{base_url}/health")
        if health.get("real_platform_writes_enabled") is not False:
            return fail("SaaS backend must not enable real platform writes in MVP")
        chain = fetch_json(f"{base_url}/schema/chain")
        if "ExecutionService" not in chain.get("chain", {}).get("layers", []):
            return fail("chain schema should expose ExecutionService boundary")
        if "Jiejing Independence Status" not in chain.get("chain", {}).get("layers", []):
            return fail("chain schema should expose Jiejing independent runtime status")
        readiness = fetch_json(f"{base_url}/readiness/product-saas")
        readiness_body = readiness.get("readiness", {})
        if readiness_body.get("production_ready") is not False:
            return fail("local MVP readiness must not claim production ready")
        if readiness_body.get("real_platform_writes_enabled") is not False:
            return fail("readiness must not enable real writes")
        readiness_keys = {item.get("key") for item in readiness_body.get("items", [])}
        for required_key in {
            "team_permission_boundary",
            "database",
            "database_adapter_contract",
            "database_migration_plan",
            "queue",
            "queue_adapter_contract",
            "queue_worker_plan",
            "infrastructure_drivers",
            "monitoring_alerting",
            "backup_restore",
            "billing_quota",
            "model_value_proof",
            "vault",
            "vault_adapter_contract",
            "platform_registry",
            "ebay_account_deletion_notifications",
            "ebay_token_refresh",
            "ebay_read_only_adapter",
            "ebay_live_read_adapter",
            "platform_data_packets",
            "provider_job_runner",
            "independent_runtime",
            "controlled_bridges",
            "execution_service",
        }:
            if required_key not in readiness_keys:
                return fail(f"readiness missing product-grade gate: {required_key}")
        controlled_bridge_status = readiness_body.get("provider_status", {}).get("controlled_bridges", {})
        if controlled_bridge_status.get("formal_bridge_count") != 5:
            return fail("controlled bridge readiness should expose five formal bridges")
        if controlled_bridge_status.get("hermes_legacy_bridge_can_be_production_dependency") is not False:
            return fail("Hermes legacy bridge must not be a production dependency")
        platform_status = readiness_body.get("provider_status", {}).get("platform_registry", {})
        if "ebay" not in platform_status.get("platform_keys", []) or "1688" not in platform_status.get("platform_keys", []):
            return fail("platform registry readiness should expose eBay and 1688")
        independence = fetch_json(f"{base_url}/independence/status").get("independence", {})
        if independence.get("runtime_independent_from_hermes") is not True:
            return fail("Jiejing SaaS should default to independent Runtime, not Hermes")
        if independence.get("hermes_adapters_allowed") is not False:
            return fail("Hermes adapters must be disabled by default")
        if independence.get("issue_count") != 7:
            return fail("independence status should track the seven productization gaps")
        issue_by_key = {item.get("key"): item for item in independence.get("issue_cards", [])}
        if issue_by_key.get("owned_agents", {}).get("status") != "independent_runtime_ready":
            return fail("owned agents should be marked independent when Hermes adapters are disabled")
        if not all(item.get("exists") for item in independence.get("deployment_files", [])):
            return fail("independent deployment skeleton files should exist")
        if independence.get("secret_exposed") is not False or "TOKEN" in json.dumps(independence, ensure_ascii=False):
            return fail("independence status must not expose raw secrets")

        platforms = fetch_json(f"{base_url}/platforms")
        registry = platforms.get("platform_registry", {})
        platform_keys = {item.get("key") for item in registry.get("platforms", [])}
        for required_platform in {"ebay", "1688", "amazon", "shopify", "taobao_tmall", "pinduoduo", "alibaba", "aliexpress"}:
            if required_platform not in platform_keys:
                return fail(f"platform registry missing {required_platform}")
        if registry.get("guardrails", {}).get("all_writes_confirmation_gated") is not True:
            return fail("platform registry must keep all writes confirmation-gated")
        authorization_strategy = registry.get("authorization_strategy") if isinstance(registry.get("authorization_strategy"), dict) else {}
        authorization_rules = authorization_strategy.get("operating_rules") if isinstance(authorization_strategy.get("operating_rules"), dict) else {}
        if authorization_strategy.get("product_positioning") != "eBay-first AI CEO SaaS":
            return fail("platform authorization strategy must keep Jiejing eBay-first")
        if authorization_rules.get("manual_import_is_a_valid_beta_lane") is not True:
            return fail("platform strategy must preserve manual/import beta fallback")
        if authorization_rules.get("read_only_before_write") is not True or authorization_rules.get("writes_require_confirmation_center") is not True:
            return fail("platform strategy must require read-only before write and confirmation-gated writes")
        amazon_lane = next(
            (item for item in authorization_strategy.get("lanes", []) if isinstance(item, dict) and item.get("key") == "amazon_sp_api"),
            {},
        )
        if amazon_lane.get("current_role") != "future_reserved_not_p0":
            return fail("Amazon SP-API should be reserved and not a P0 blocker")
        ebay_platform = fetch_json(f"{base_url}/platforms/ebay").get("platform", {})
        if ebay_platform.get("priority") != "current_primary":
            return fail("eBay should remain the current primary platform")

        invalid_json_status, invalid_json_body = post_raw_expect_error(f"{base_url}/auth/login", b"{")
        if invalid_json_status != 400 or "invalid json body" not in invalid_json_body.get("error", ""):
            return fail("invalid JSON request bodies should return a stable 400 response")
        array_json_status, array_json_body = post_raw_expect_error(f"{base_url}/auth/login", b"[]")
        if array_json_status != 400 or "json body must be an object" not in array_json_body.get("error", ""):
            return fail("non-object JSON request bodies should return a stable 400 response")
        large_json_status, large_json_body = post_declared_oversized_expect_error(
            f"{base_url}/auth/login",
            declared_length=1024 * 1024 + 4096,
        )
        if large_json_status != 413:
            return fail("oversized JSON request bodies should return a stable 413 response")
        if fetch_json(f"{base_url}/health").get("status") != "ok":
            return fail("backend must remain healthy after rejecting an oversized JSON request")

        demo_session_first = post_json(
            f"{base_url}/auth/demo-session",
            {
                "email": "demo@jiejing.local",
                "password": "jiejing-demo-password",
                "company_name": "Jiejing Local Demo Company",
            },
        )
        demo_session_second = post_json(
            f"{base_url}/auth/demo-session",
            {
                "email": "demo@jiejing.local",
                "password": "jiejing-demo-password",
                "company_name": "Jiejing Local Demo Company",
            },
        )
        if not demo_session_first.get("token") or not demo_session_second.get("token"):
            return fail("demo-session bootstrap should return reusable local bearer tokens")
        if demo_session_second.get("created") is not False:
            return fail("second demo-session bootstrap should login instead of causing register conflict")
        if demo_session_first.get("secret_exposed") is not False or demo_session_second.get("secret_exposed") is not False:
            return fail("demo-session bootstrap must not expose secrets")

        registered = post_json(
            f"{base_url}/auth/register",
            {
                "email": "owner@example.com",
                "password": "local-test-password",
                "company_name": "Northvale Source Demo",
            },
        )
        token = registered.get("token")
        if not token:
            return fail("registration should return bearer token")

        me = fetch_json(f"{base_url}/me", token=token)
        if me.get("user", {}).get("email") != "owner@example.com":
            return fail("bearer token should resolve current user")
        owner_company_id = me.get("company", {}).get("company_id")
        owner_permissions = fetch_json(f"{base_url}/permissions/me", token=token)
        if owner_permissions.get("role") != "owner":
            return fail("registered user should be owner of default company")
        if "manage_team" not in owner_permissions.get("permissions", []) or "approve_high_risk" not in owner_permissions.get("permissions", []):
            return fail("owner permissions should include team management and high-risk approval")
        owner_members = fetch_json(f"{base_url}/team/members", token=token).get("team_members", [])
        if len(owner_members) != 1 or owner_members[0].get("role") != "owner":
            return fail("new company should start with one owner team member")

        operator = post_json(
            f"{base_url}/auth/register",
            {
                "email": "operator@example.com",
                "password": "local-test-password",
                "company_name": "Operator Default Company",
            },
        )
        invited = post_json(
            f"{base_url}/team/invitations",
            {"email": "operator@example.com", "role": "operator", "metadata": {"note": "MVP regression invite"}},
            token=token,
        )
        if invited.get("team_invitation", {}).get("status") != "accepted_existing_user_added":
            return fail("inviting an existing user should add them to the company")
        team_members = fetch_json(f"{base_url}/team/members", token=token).get("team_members", [])
        if not any(item.get("email") == "operator@example.com" and item.get("role") == "operator" for item in team_members):
            return fail("operator should appear in owner company team members")
        operator_companies = fetch_json(f"{base_url}/companies", token=operator["token"]).get("companies", [])
        if not any(item.get("company_id") == owner_company_id and item.get("role") == "operator" for item in operator_companies):
            return fail("operator should be able to see invited company membership")
        switched = post_json(f"{base_url}/auth/switch-company", {"company_id": owner_company_id}, token=operator["token"])
        operator_company_token = switched.get("token")
        if switched.get("team_member", {}).get("role") != "operator" or not operator_company_token:
            return fail("operator should be able to switch into invited company")
        operator_permissions = fetch_json(f"{base_url}/permissions/me", token=operator_company_token)
        if "approve_high_risk" in operator_permissions.get("permissions", []):
            return fail("operator must not have high-risk approval permission")
        forbidden_status, _ = post_json_expect_error(
            f"{base_url}/team/invitations",
            {"email": "blocked@example.com", "role": "viewer"},
            token=operator_company_token,
        )
        if forbidden_status != 403:
            return fail("operator must not be able to invite team members")

        store_response = post_json(
            f"{base_url}/stores",
            {
                "platform": "ebay",
                "store_name": "northvalesource",
                "marketplace": "EBAY_US",
                "stage": "store_opened",
            },
            token=token,
        )
        store_id = store_response.get("store", {}).get("store_id")
        if not store_id:
            return fail("store creation should return store_id")

        source_plan = post_json(
            f"{base_url}/stores/{store_id}/platforms/1688/connection-plan",
            {"connection_mode": "link_import"},
            token=token,
        )
        source_plan_body = source_plan.get("connection_plan", {})
        if source_plan_body.get("platform") != "1688":
            return fail("1688 connection plan should use the sourcing platform key")
        if source_plan_body.get("current_scope") != "contract_reserved_no_live_call":
            return fail("reserved connector plan must not call live APIs")
        if "purchase_order" not in source_plan_body.get("requires_confirmation", []):
            return fail("1688 procurement must remain confirmation-gated")
        if "procurement_payment" not in source_plan_body.get("requires_confirmation", []):
            return fail("1688 payment must remain confirmation-gated")
        amazon_plan = post_json(
            f"{base_url}/stores/{store_id}/platforms/amazon/connection-plan",
            {"connection_mode": "official_oauth"},
            token=token,
        )
        if amazon_plan.get("connection_plan", {}).get("status") != "reserved_no_live_adapter":
            return fail("future sales channel should be reserved without a live adapter")

        for protected_endpoint in [
            "vault/status",
            "vault/adapters",
            "vault/client-contract",
            "vault/targets",
            "vault/secret-resolver/status",
            "database/plan",
            "database/adapters",
            "database/inventory",
            "queue/plan",
            "queue/adapters",
            "controlled-bridges",
            "monitoring/status",
            "infrastructure/drivers",
            "backup/plan",
            "provider-job-contracts",
        ]:
            protected_status, protected_body = fetch_json_expect_error(f"{base_url}/{protected_endpoint}", token=token)
            if protected_status != 403:
                return fail(f"ordinary merchant must not access platform-internal endpoint {protected_endpoint}: {protected_body}")
        billing_plan = fetch_json(f"{base_url}/billing/plans", token=token).get("billing_plan", {})
        if billing_plan.get("billing_ready_for_paid_launch") is not False:
            return fail("billing plan must not claim paid-launch readiness in local MVP")
        plan_keys = {item.get("key") for item in billing_plan.get("plan_catalog", [])}
        if not {"starter", "operator", "team"}.issubset(plan_keys):
            return fail("billing plan should expose starter/operator/team plans")
        if billing_plan.get("quota_contract", {}).get("merchant_visible_usage_required") is not True:
            return fail("billing plan should require merchant-visible usage")
        if billing_plan.get("customer_visible") is not True or billing_plan.get("internal_launch_evidence_visible") is not False:
            return fail("ordinary merchant billing plan should be the customer-visible safe payload")
        if "payment_strategy" in billing_plan or "billing_live_cutover_matrix" in billing_plan or "billing_live_cutover_summary" in billing_plan:
            return fail("ordinary merchant billing plan must not expose internal payment strategy or live cutover evidence")
        for internal_launch_key in {
            "mainland_payment_launch",
            "mainland_payment_ready_for_owner_approval",
            "future_international_payment",
        }:
            if internal_launch_key in billing_plan:
                return fail(f"ordinary merchant billing plan exposes internal launch key {internal_launch_key}")
        billing_provider = billing_plan.get("provider", {})
        for internal_provider_key in {
            "recommended_mainland_provider_order",
            "mainland_payment_strategy_contract",
            "allowed_private_beta_providers",
            "manual_seed_allowed_for_private_beta",
            "manual_beta_allowed_for_private_beta",
        }:
            if internal_provider_key in billing_provider:
                return fail(f"ordinary merchant billing provider payload exposes internal key {internal_provider_key}")
        payment_options_status, payment_options_error = fetch_json_expect_error(f"{base_url}/billing/payment-options", token=token)
        if payment_options_status != 403:
            return fail(f"ordinary merchant must not access internal payment options: {payment_options_error}")
        if billing_plan.get("real_platform_writes_enabled") is not False:
            return fail("billing plan must not enable real platform writes")
        if billing_plan.get("secret_exposed") is not False:
            return fail("billing plan must not expose secrets")
        model_value_gate = fetch_json(f"{base_url}/model/value-gate", token=token).get("model_value_gate", {})
        if model_value_gate.get("ready_for_paid_value_claim") is not False:
            return fail("model value gate must not claim paid value in local MVP")
        if model_value_gate.get("frontend_gets_model_api_key") is not False:
            return fail("model value gate must keep model API keys away from frontend")
        if model_value_gate.get("runtime_gets_raw_ebay_token") is not False:
            return fail("model value gate must keep raw eBay tokens away from Runtime")
        model_blockers = set(model_value_gate.get("blockers", []))
        if not {
            "market_and_listing_live_model_value_not_proven",
            "model_provider_not_configured",
            "live_model_calls_not_enabled",
        }.intersection(model_blockers):
            return fail("model value gate should expose paid-value blockers")
        proof_keys = {item.get("key") for item in model_value_gate.get("required_commercial_proof", [])}
        if not {"market.report", "listing.package"}.issubset(proof_keys):
            return fail("model value gate should require market and listing proof")
        if model_value_gate.get("secret_exposed") is not False:
            return fail("model value gate must not expose secrets")
        secret_ref_plan = post_json(
            f"{base_url}/stores/{store_id}/vault/secret-ref-plan",
            {
                "provider": "ebay",
                "purpose": "ebay_refresh_token",
                "vault_target": "tencent_kms",
                "refresh_token": "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST",
                "metadata": {"seller": "northvalesource", "client_secret_note": "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST"},
            },
            token=token,
        )
        secret_ref_id = secret_ref_plan.get("secret_ref", {}).get("secret_ref")
        if not secret_ref_id:
            return fail("vault secret-ref plan should create a secret_ref record")
        serialized_secret_plan = json.dumps(secret_ref_plan, ensure_ascii=False)
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in serialized_secret_plan or "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST" in serialized_secret_plan:
            return fail("secret-ref plan leaked a raw secret")
        if secret_ref_plan.get("secret_ref_plan", {}).get("secret_value_stored") is not False:
            return fail("local secret-ref plan must not store raw secret values")
        resolution_plan = post_json(
            f"{base_url}/stores/{store_id}/vault/{secret_ref_id}/resolve-plan",
            {"requested_by": "backend_adapter", "task_scope": "ebay_read_only_probe"},
            token=token,
        ).get("secret_resolution_plan", {})
        if resolution_plan.get("status") != "resolve_blocked":
            return fail("secret resolution should stay blocked until managed Vault is implemented")
        if resolution_plan.get("frontend_gets_raw_secret") is not False or resolution_plan.get("runtime_gets_raw_secret") is not False:
            return fail("secret resolution plan must not return raw secret to frontend or Runtime")
        client_resolution = post_json(
            f"{base_url}/stores/{store_id}/vault/{secret_ref_id}/client-resolve-contract",
            {"requested_by": "backend_adapter", "task_scope": "ebay_read_only_probe"},
            token=token,
        ).get("vault_client_resolution", {})
        if client_resolution.get("status") != "resolve_blocked":
            return fail("vault client resolution contract should stay blocked in local MVP")
        if client_resolution.get("raw_secret_returned") is not False or client_resolution.get("frontend_gets_raw_secret") is not False:
            return fail("vault client resolution contract must not return raw secrets")
        rotation_plan = post_json(
            f"{base_url}/stores/{store_id}/vault/{secret_ref_id}/rotation-plan",
            {"reason": "mvp regression rotation"},
            token=token,
        ).get("secret_rotation_plan", {})
        if rotation_plan.get("status") != "rotation_blocked":
            return fail("secret rotation should stay blocked until managed Vault is implemented")
        if "live_vault_client_not_implemented" not in rotation_plan.get("blocked_by", []) and "JIEJING_VAULT_ENABLED" not in rotation_plan.get("blocked_by", []):
            return fail("secret rotation should expose the managed Vault blocker")
        revoke_plan = post_json(
            f"{base_url}/stores/{store_id}/vault/{secret_ref_id}/revoke-plan",
            {"reason": "mvp regression revoke"},
            token=token,
        ).get("secret_revoke_plan", {})
        if revoke_plan.get("status") != "revoke_blocked":
            return fail("secret revoke should stay blocked until managed Vault is implemented")
        serialized_secret_ops = json.dumps({"resolution": resolution_plan, "rotation": rotation_plan, "revoke": revoke_plan}, ensure_ascii=False)
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in serialized_secret_ops or "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST" in serialized_secret_ops:
            return fail("secret operation plans leaked a raw secret")
        secret_refs = fetch_json(f"{base_url}/secret-refs?store_id={store_id}", token=token)
        if not any(item.get("purpose") == "ebay_refresh_token" for item in secret_refs.get("secret_refs", [])):
            return fail("secret refs endpoint should list the created eBay refresh-token ref")
        local_token_store = fetch_json(f"{base_url}/ebay-oauth/local-token-store/status", token=token).get("local_oauth_token_store", {})
        if local_token_store.get("enabled") is not False:
            return fail("local OAuth token store should be disabled by default")
        if local_token_store.get("returns_raw_secret_to_frontend") is not False or local_token_store.get("returns_raw_secret_to_runtime") is not False:
            return fail("local OAuth token store status must not expose raw secrets")
        if local_token_store.get("secret_exposed") is not False:
            return fail("local OAuth token store status should preserve secret_exposed=false")
        refresh_plan = post_json(
            f"{base_url}/stores/{store_id}/ebay-oauth/refresh-plan",
            {},
            token=token,
        )
        refresh_body = refresh_plan.get("token_refresh_plan", {})
        if refresh_body.get("status") != "refresh_blocked":
            return fail("token refresh should stay blocked in local MVP")
        if refresh_body.get("secret_refs_found") != 1:
            return fail("token refresh plan should see the eBay refresh-token secret_ref")
        if refresh_body.get("token_refresh_performed") is not False:
            return fail("token refresh plan must not perform real refresh in local MVP")
        if refresh_body.get("access_token_returned_to_frontend") is not False:
            return fail("token refresh plan must not return access token to frontend")
        for expected_blocker in {"JIEJING_EBAY_CLIENT_ID", "JIEJING_EBAY_CLIENT_SECRET", "JIEJING_EBAY_TOKEN_REFRESH_LIVE"}:
            if expected_blocker not in refresh_body.get("blocked_by", []):
                return fail(f"token refresh plan missing blocker {expected_blocker}")
        refresh_execution_plan = post_json(
            f"{base_url}/stores/{store_id}/ebay-oauth/refresh-execution-plan",
            {},
            token=token,
        ).get("token_refresh_execution_plan", {})
        if refresh_execution_plan.get("status") != "blocked_contract_only":
            return fail("token refresh execution plan should stay blocked in local MVP")
        if refresh_execution_plan.get("live_refresh_performed") is not False:
            return fail("token refresh execution plan must not refresh tokens in local MVP")
        if refresh_execution_plan.get("token_boundary", {}).get("access_token_returned_to_frontend") is not False:
            return fail("token refresh execution plan must not return access token to frontend")
        if refresh_execution_plan.get("token_boundary", {}).get("access_token_returned_to_runtime") is not False:
            return fail("token refresh execution plan must not return access token to Runtime")
        if refresh_execution_plan.get("http_request_contract", {}).get("body_redacted") is not True:
            return fail("token refresh execution plan should redact HTTP body secrets")
        serialized_refresh_execution = json.dumps(refresh_execution_plan, ensure_ascii=False)
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in serialized_refresh_execution or "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST" in serialized_refresh_execution:
            return fail("token refresh execution plan leaked a raw secret")

        oauth_plan = post_json(
            f"{base_url}/stores/{store_id}/ebay-oauth/read-only-plan",
            {
                "marketplace_id": "EBAY_US",
                "scopes": [
                    "https://api.ebay.com/oauth/api_scope/sell.inventory",
                    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
                    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
                ],
            },
            token=token,
        )
        plan = oauth_plan.get("oauth_plan", {})
        if plan.get("status") != "blocked_missing_oauth_config":
            return fail("OAuth plan should be blocked until eBay app config is supplied")
        if plan.get("authorization_url") is not None:
            return fail("OAuth plan must not create redirect URL without client_id and RuName")
        if any(str(scope).endswith("/sell.inventory") for scope in plan.get("scopes", [])):
            return fail("OAuth plan should filter high-risk write scopes from read-only plan")
        if "JIEJING_EBAY_CLIENT_ID" not in plan.get("missing_config", []):
            return fail("OAuth plan should report missing client id")
        oauth_requests = fetch_json(f"{base_url}/oauth/requests?store_id={store_id}", token=token)
        if not oauth_requests.get("oauth_requests"):
            return fail("OAuth authorization request should be persisted for audit")
        callback = fetch_json(f"{base_url}/oauth/ebay/callback?state={plan.get('state_nonce')}&code=TEST_AUTH_CODE")
        callback_body = callback.get("oauth_callback", {})
        if callback_body.get("status") != "callback_received_exchange_blocked":
            return fail("OAuth callback should be recorded but block token exchange without config/Vault")
        if callback_body.get("code_stored") is not False or callback_body.get("token_exchange_performed") is not False:
            return fail("OAuth callback must not store code or exchange tokens in local MVP")
        oauth_requests_after_callback = fetch_json(f"{base_url}/oauth/requests?store_id={store_id}", token=token)
        if oauth_requests_after_callback.get("oauth_requests", [{}])[0].get("status") != "callback_received_exchange_blocked":
            return fail("OAuth callback status should be persisted for audit")
        invalid_state_status, _ = fetch_json_expect_error(f"{base_url}/oauth/ebay/callback?state=invalid-state&code=TEST_AUTH_CODE")
        if invalid_state_status != 400:
            return fail("OAuth callback with invalid state should be rejected")

        connection = post_json(
            f"{base_url}/stores/{store_id}/connections",
            {
                "platform": "ebay",
                "connection_type": "oauth",
                "status": "read_only_authorized",
                "scopes": ["sell.inventory.readonly", "sell.account.readonly"],
                "refresh_token": "NEVER_STORE_THIS_REFRESH_TOKEN",
                "metadata": {"seller_username": "northvalesource", "token_note": "should redact"},
            },
            token=token,
        )
        if not connection.get("connection", {}).get("secret_ref"):
            return fail("connection with token input should create a secret_ref")
        if "NEVER_STORE_THIS_REFRESH_TOKEN" in json.dumps(connection, ensure_ascii=False):
            return fail("raw token leaked in connection response")
        if "NEVER_STORE_THIS_REFRESH_TOKEN" in json.dumps(fetch_json(f"{base_url}/readiness/product-saas"), ensure_ascii=False):
            return fail("raw token leaked in readiness response")
        read_catalog = fetch_json(f"{base_url}/ebay-read-only/catalog", token=token).get("ebay_read_only_catalog", {})
        catalog_keys = {item.get("key") for item in read_catalog.get("resources", [])}
        for required_resource in {"store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"}:
            if required_resource not in catalog_keys:
                return fail(f"eBay read-only catalog missing {required_resource}")
        field_contracts = fetch_json(f"{base_url}/ebay-read-only/field-contracts", token=token).get("ebay_read_only_field_contracts", {})
        contract_keys = {item.get("resource_key") for item in field_contracts.get("resources", [])}
        if not {"store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"}.issubset(contract_keys):
            return fail("eBay field contracts should cover required read-only resources")
        if field_contracts.get("rules", {}).get("sensitive_fields_are_redacted_before_persistence") is not True:
            return fail("eBay field contracts must preserve redaction rule")
        normalizers = fetch_json(f"{base_url}/ebay-read-only/normalizers", token=token).get("ebay_read_only_normalizers", {})
        normalizer_keys = set(normalizers.get("resource_keys", []))
        if not {"store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"}.issubset(normalizer_keys):
            return fail("eBay normalizer catalog should cover required read-only resources")
        if normalizers.get("normalizes_sanitized_resource_sections") is not True:
            return fail("eBay normalizers should be registered for sanitized packet sections")
        live_adapter = fetch_json(f"{base_url}/ebay-read-only/live-adapter/status", token=token).get("ebay_live_read_adapter", {})
        if live_adapter.get("enabled") is not False:
            return fail("live eBay read adapter must stay disabled in MVP")
        if live_adapter.get("route_count", 0) < 6:
            return fail("live eBay read adapter should expose route contracts")
        if live_adapter.get("guardrails", {}).get("frontend_gets_access_token") is not False:
            return fail("live read adapter must not expose access token to frontend")
        if "JIEJING_EBAY_READ_ONLY_LIVE" not in live_adapter.get("blocked_by", []):
            return fail("live read adapter should stay blocked until live read is explicitly enabled")
        if live_adapter.get("route_standardizers_registered") is not True:
            return fail("live read adapter should know route standardizers are registered")
        ebay_http_client = fetch_json(f"{base_url}/ebay-read-only/http-client/status", token=token).get("ebay_http_client", {})
        if ebay_http_client.get("contract_ready") is not True:
            return fail("eBay HTTP client contract should be ready")
        if ebay_http_client.get("live_request_performed") is not False or ebay_http_client.get("writes_supported") is not False:
            return fail("eBay HTTP client contract must not perform live requests or writes")
        if ebay_http_client.get("response_rules", {}).get("hand_runtime_sanitized_packet_only") is not True:
            return fail("eBay HTTP client should only hand sanitized packets to Runtime")
        write_adapter = fetch_json(f"{base_url}/ebay-write/adapter/status", token=token).get("ebay_write_adapter", {})
        if write_adapter.get("enabled") is not False or write_adapter.get("writes_supported") is not False:
            return fail("eBay write adapter must remain disabled in the backend MVP")
        write_actions = {item.get("action_type") for item in write_adapter.get("actions", [])}
        for required_action in {"publish_listing", "revise_listing", "change_price", "change_inventory", "refund", "policy_edit"}:
            if required_action not in write_actions:
                return fail(f"eBay write adapter contract missing {required_action}")
        if write_adapter.get("guardrails", {}).get("preflight_required") is not True:
            return fail("eBay write adapter must require execution preflight")
        if write_adapter.get("guardrails", {}).get("frontend_gets_token") is not False:
            return fail("eBay write adapter must not expose token to frontend")
        read_plan = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/probe-plan",
            {"resources": ["store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"]},
            token=token,
        )
        read_body = read_plan.get("read_only_probe_plan", {})
        if read_body.get("status") != "read_only_blocked":
            return fail("read-only probe must stay blocked in local MVP")
        if read_body.get("resource_count") != 6:
            return fail("read-only probe should keep requested resources")
        if read_body.get("live_read_performed") is not False:
            return fail("read-only probe must not call live eBay in local MVP")
        if read_body.get("access_token_returned_to_frontend") is not False:
            return fail("read-only probe must not expose access tokens")
        if "token_refresh_not_ready" not in read_body.get("blocked_by", []):
            return fail("read-only probe should depend on token refresh readiness")
        if "JIEJING_EBAY_READ_ONLY_LIVE" not in read_body.get("blocked_by", []):
            return fail("read-only probe should mark live reads disabled until explicitly enabled")
        workflow_plan = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/workflow-plan",
            {"resources": ["store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"]},
            token=token,
        )
        workflow_body = workflow_plan.get("read_only_workflow_plan", {})
        if workflow_body.get("status") != "blocked_until_live_adapter":
            return fail("read-only workflow plan should stay blocked until live adapter is implemented")
        if workflow_body.get("frontend_gets_access_token") is not False:
            return fail("read-only workflow must not expose access tokens to frontend")
        if workflow_body.get("runtime_gets_sanitized_packet_only") is not True:
            return fail("Runtime should only receive sanitized read-only packets")
        if workflow_body.get("step_count", 0) < 9:
            return fail("read-only workflow should expose backend read steps")
        live_read_plan_response = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/live-read-plan",
            {"resources": ["store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"]},
            token=token,
        )
        live_read_plan = live_read_plan_response.get("live_read_plan", {})
        if live_read_plan.get("status") != "blocked_contract_only":
            return fail("live-read execution plan should stay blocked in local MVP")
        if live_read_plan.get("route_request_count") != 6:
            return fail("live-read execution plan should keep requested route contracts")
        if live_read_plan.get("live_read_performed") is not False:
            return fail("live-read execution plan must not perform live eBay calls")
        token_boundary = live_read_plan.get("token_boundary", {})
        if token_boundary.get("frontend_gets_access_token") is not False or token_boundary.get("runtime_gets_access_token") is not False:
            return fail("live-read execution plan must keep access tokens away from frontend and Runtime")
        if token_boundary.get("refresh_secret_ref_found") is not True:
            return fail("live-read execution plan should find the created eBay refresh-token secret_ref")
        if live_read_plan.get("data_packet_handoff", {}).get("runtime_gets_sanitized_packet_only") is not True:
            return fail("live-read execution plan should hand Runtime sanitized packets only")
        if "JIEJING_EBAY_READ_ONLY_LIVE" not in live_read_plan.get("blocked_by", []):
            return fail("live-read execution plan should expose the disabled live read blocker")
        route_contracts = live_read_plan.get("route_requests", [])
        if not route_contracts or not all(item.get("required_headers") for item in route_contracts):
            return fail("live-read execution plan should expose HTTP request header contracts")
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in json.dumps(live_read_plan_response, ensure_ascii=False):
            return fail("live-read execution plan leaked a raw refresh token")
        http_dry_run = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/http-client-dry-run",
            {"resources": ["store_profile", "account_business_policies"]},
            token=token,
        ).get("http_client_dry_run", {})
        if http_dry_run.get("request_count") != 2:
            return fail("eBay HTTP dry-run should build requested route envelopes")
        if http_dry_run.get("live_request_performed") is not False or http_dry_run.get("access_token_returned_to_frontend") is not False:
            return fail("eBay HTTP dry-run must not call live eBay or return access token")
        serialized_dry_run = json.dumps(http_dry_run, ensure_ascii=False)
        if "Bearer <short_lived_access_token" in serialized_dry_run:
            return fail("eBay HTTP dry-run leaked token placeholder instead of redacting Authorization")
        credential_preflight = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/credential-preflight",
            {"resources": ["store_profile", "account_business_policies"]},
            token=token,
        ).get("credential_preflight", {})
        if credential_preflight.get("status") != "blocked":
            return fail("credential preflight should block in local MVP without live read switch/token")
        if credential_preflight.get("secret_exposed") is not False or credential_preflight.get("frontend_gets_access_token") is not False:
            return fail("credential preflight must not expose secrets or access tokens")
        if not credential_preflight.get("merchant_next_step"):
            return fail("credential preflight should return a merchant next step")
        if "JIEJING_EBAY_READ_ONLY_LIVE" not in credential_preflight.get("blocked_by", []):
            return fail("credential preflight should expose the disabled live-read switch")
        serialized_preflight = json.dumps(credential_preflight, ensure_ascii=False)
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in serialized_preflight or "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST" in serialized_preflight:
            return fail("credential preflight leaked a raw secret")
        queued_read_job = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/queue-read-job",
            {"resources": ["store_profile", "account_business_policies"]},
            token=token,
        )
        read_job_id = queued_read_job.get("queue_job", {}).get("job_id")
        if queued_read_job.get("queue_job", {}).get("status") != "queued" or not read_job_id:
            return fail("eBay read-only live-plan job should be queued before worker execution")
        if queued_read_job.get("live_read_plan", {}).get("live_read_performed") is not False:
            return fail("queued read-only live-plan job must not perform live read at request time")
        read_worker = post_json(f"{base_url}/workers/run-next", {"job_id": read_job_id}, token=token)
        if read_worker.get("status") != "completed":
            return fail("local worker should complete eBay read-only live-plan jobs")
        if read_worker.get("live_read_plan", {}).get("live_read_performed") is not False:
            return fail("read-only live-plan worker must not perform live eBay reads in MVP")
        if read_worker.get("task", {}).get("output", {}).get("status") != "completed_no_live_read":
            return fail("read-only live-plan worker should mark task completed without live read")
        sync_response = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/sync",
            {"resources": ["store_profile", "account_business_policies"], "run_mode": "inline"},
            token=token,
        )
        sync_body = sync_response.get("sync", {})
        if sync_body.get("status") != "blocked_before_queue":
            return fail("product-level eBay sync should block before queueing when live credentials are missing")
        if sync_response.get("queue_job") is not None or sync_response.get("worker_result") is not None:
            return fail("blocked eBay sync should not create a queue job or run a worker")
        if sync_response.get("task", {}).get("status") != "blocked":
            return fail("blocked eBay sync should persist a blocked task for merchant-visible feedback")
        if "JIEJING_EBAY_READ_ONLY_LIVE" not in sync_body.get("blocked_by", []):
            return fail("blocked eBay sync should explain the disabled live-read switch")
        if not sync_body.get("merchant_next_step"):
            return fail("blocked eBay sync should return a merchant next step")
        if sync_body.get("credential_preflight", {}).get("status") != "blocked":
            return fail("blocked eBay sync should include the same credential preflight state")
        if sync_body.get("real_platform_writes_enabled") is not False or sync_body.get("secret_exposed") is not False:
            return fail("blocked eBay sync must keep writes disabled and secrets hidden")
        serialized_sync = json.dumps(sync_response, ensure_ascii=False)
        if "UNIT-REFRESH-TOKEN-MUST-NOT-PERSIST" in serialized_sync or "UNIT-CLIENT-SECRET-MUST-NOT-PERSIST" in serialized_sync:
            return fail("product-level eBay sync leaked a raw secret")
        data_packet = post_json(
            f"{base_url}/stores/{store_id}/ebay-read-only/data-packet",
            {
                "resources": ["store_profile", "account_business_policies", "inventory_and_offers", "orders_and_fulfillment", "finances", "taxonomy_listing_metadata"],
                "source_mode": "sample_payload",
                "sample_payload": {
                    "store_profile": {
                        "seller_username": "UNIT-SELLER-USERNAME-MUST-NOT-PERSIST",
                        "marketplace_id": "EBAY_US",
                        "selling_limit": "31/35",
                    },
                    "account_business_policies": {
                        "fulfillment_policy_id": "fulfillmentPolicyId DEMO-FULFILLMENT-001",
                        "payment_policy_id": "paymentPolicyId DEMO-PAYMENT-001",
                        "return_policy_id": "returnPolicyId DEMO-RETURN-001",
                    },
                    "inventory_and_offers": {
                        "sku": "TEST-SPOONS-001",
                        "listing_title": "Stainless Steel Measuring Spoons Set",
                        "access_token": "UNIT-ACCESS-TOKEN-MUST-NOT-PERSIST",
                    },
                    "orders_and_fulfillment": {
                        "order_id": "ORDER-1",
                        "buyer_email": "buyer@example.com",
                        "ship_to_address": "123 Secret Street",
                        "fulfillment_status": "NOT_STARTED",
                    },
                    "finances": {
                        "transaction_count": 3,
                        "gross_amount": "29.97",
                        "buyer_name": "Jane Buyer",
                    },
                    "taxonomy_listing_metadata": {
                        "category_id": "20625",
                        "required_aspects": ["Brand", "Material", "Type"],
                    },
                },
            },
            token=token,
        )
        packet_record = data_packet.get("data_packet", {})
        if not packet_record.get("packet_id"):
            return fail("eBay read-only data packet should be persisted")
        packet_body = packet_record.get("packet", {})
        if packet_body.get("resource_count") != 6:
            return fail("data packet should include requested resource sections")
        if packet_body.get("safe_for_real_platform_write") is not False:
            return fail("data packet must not authorize real platform writes")
        if "store_profile" not in packet_body.get("present_resource_keys", []):
            return fail("data packet should include sanitized store profile when supplied")
        if packet_body.get("readiness_for_modules", {}).get("ai_ceo_home", {}).get("ready") is not True:
            return fail("store profile should make AI CEO home packet context ready")
        if packet_body.get("field_gap_count", 0) < 1:
            return fail("data packet should report missing required field gaps for incomplete sample sections")
        if packet_body.get("freshness", {}).get("stale_after_seconds") != 21600:
            return fail("data packet should expose a standard freshness window")
        if packet_body.get("packet_schema", {}).get("compatible_runtime_contract") != "jiejing_runtime.standard_data_packet.v1":
            return fail("data packet should expose the Runtime packet contract version")
        if packet_body.get("retry_policy", {}).get("real_platform_writes_enabled") is not False:
            return fail("data packet retry policy must not authorize platform writes")
        summary_by_key = {item.get("key"): item for item in packet_body.get("section_summary", [])}
        if not summary_by_key.get("store_profile", {}).get("missing_required_fields"):
            return fail("section summary should expose missing required fields")
        serialized_packet = json.dumps(data_packet, ensure_ascii=False)
        for forbidden in ["UNIT-ACCESS-TOKEN-MUST-NOT-PERSIST", "UNIT-SELLER-USERNAME-MUST-NOT-PERSIST", "buyer@example.com", "123 Secret Street", "Jane Buyer"]:
            if forbidden in serialized_packet:
                return fail(f"data packet leaked sensitive value: {forbidden}")
        packets = fetch_json(f"{base_url}/data-packets?store_id={store_id}&platform=ebay", token=token)
        if not packets.get("data_packets"):
            return fail("data packet list endpoint should return persisted packet")
        fetched_packet = fetch_json(f"{base_url}/data-packets/{packet_record.get('packet_id')}", token=token)
        if fetched_packet.get("data_packet", {}).get("packet_id") != packet_record.get("packet_id"):
            return fail("data packet detail endpoint should return the packet")
        commercial_launch_gate = fetch_json(f"{base_url}/commercial/launch-gate", token=token).get("commercial_launch_gate", {})
        if commercial_launch_gate.get("paid_commercial_launch_ready") is not False:
            return fail("commercial launch gate must not claim paid launch readiness in local MVP")
        launch_group_keys = {item.get("key") for item in commercial_launch_gate.get("groups", [])}
        for required_launch_group in {"official_ebay_read_loop", "managed_database_queue", "managed_secret_boundary", "backup_restore", "billing_quota", "model_agent_value"}:
            if required_launch_group not in launch_group_keys:
                return fail(f"commercial launch gate missing {required_launch_group}")
        if commercial_launch_gate.get("real_platform_writes_enabled") is not False or commercial_launch_gate.get("secret_exposed") is not False:
            return fail("commercial launch gate must not expose secrets or enable writes")
        provider_register_status, _ = fetch_json_expect_error(f"{base_url}/commercial/billing-provider-evidence-register")
        if provider_register_status != 401:
            return fail("billing provider evidence register must require authentication")
        provider_register_status, provider_register_error = fetch_json_expect_error(f"{base_url}/commercial/billing-provider-evidence-register", token=token)
        if provider_register_status != 403:
            return fail(f"ordinary merchant must not access internal billing provider evidence register: {provider_register_error}")
        owner_provider_status, owner_provider_error = fetch_json_expect_error(f"{base_url}/owner/billing-provider-evidence-register", token=token)
        if owner_provider_status != 403:
            return fail(f"ordinary merchant must not access owner billing provider evidence register: {owner_provider_error}")
        model_value_rehearsal = post_json(
            f"{base_url}/stores/{store_id}/model/value-rehearsal",
            {
                "packet_id": packet_record.get("packet_id"),
                "product": "Stainless Steel Measuring Spoons",
                "merchant_goal": "Prepare model-backed market and listing reports.",
                "allow_live_model": False,
            },
            token=token,
        ).get("model_value_rehearsal", {})
        if model_value_rehearsal.get("status") != "blocked_before_model_rehearsal":
            return fail("model value rehearsal endpoint should block when live model use is not explicitly enabled")
        if "live_model_rehearsal_not_requested" not in model_value_rehearsal.get("blockers", []):
            return fail("model value rehearsal endpoint should expose the live model approval blocker")
        if model_value_rehearsal.get("would_create_reports") is not False:
            return fail("blocked model value rehearsal should not create reports")
        if model_value_rehearsal.get("runtime_gets_raw_ebay_token") is not False or model_value_rehearsal.get("frontend_gets_model_api_key") is not False:
            return fail("model value rehearsal endpoint must preserve token/model-key boundaries")

        workflow = post_json(
            f"{base_url}/tasks/product-workflow",
            {
                "store_id": store_id,
                "product": "Stainless Steel Measuring Spoons",
                "merchant_goal": "Screen one light, non-electric eBay product and prepare listing, media, finance and confirmation records.",
                "adapter": "jiejing-local",
                "run_id": "saas-backend-mvp-workflow",
                "source_mode": "manual_or_1688",
                "market_probe_inputs": {
                    "ebay_price_band": "US $7.99-14.99",
                    "buyer_profile": "home cooks, baking users, compact kitchen organizers",
                    "source_type": "manual_test_input",
                },
                "merchant_profile": {
                    "merchantStage": "store_opened",
                    "permissionLevel": "service_auto",
                    "sourceApiMode": "manual_1688",
                    "riskLevel": "balanced",
                },
                "run_mode": "queued",
            },
            token=token,
        )
        task_id = workflow.get("task", {}).get("task_id")
        workflow_input = workflow.get("task", {}).get("input", {})
        handoff = workflow.get("platform_data_packet_handoff") or workflow_input.get("platform_data_packet_handoff") or {}
        if handoff.get("packet_id") != packet_record.get("packet_id"):
            return fail("product workflow should attach the latest sanitized eBay platform data packet")
        ebay_probe = workflow_input.get("market_probe_inputs", {}).get("ebay_read_only", {})
        if ebay_probe.get("packet_id") != packet_record.get("packet_id") or ebay_probe.get("status") != "ready":
            return fail("product workflow should hand the latest eBay packet to Runtime market_probe_inputs")
        if ebay_probe.get("source_type") != "merchant_provided":
            return fail("sample data packet should not be mislabeled as official eBay API data")
        if workflow.get("queue_job", {}).get("job", {}).get("attached_platform_data_packet_id") != packet_record.get("packet_id"):
            return fail("workflow queue job should record the attached data packet id")
        serialized_workflow = json.dumps(workflow, ensure_ascii=False)
        for forbidden in ["UNIT-ACCESS-TOKEN-MUST-NOT-PERSIST", "UNIT-SELLER-USERNAME-MUST-NOT-PERSIST", "buyer@example.com", "123 Secret Street", "Jane Buyer"]:
            if forbidden in serialized_workflow:
                return fail(f"workflow data packet handoff leaked sensitive value: {forbidden}")
        steps = workflow.get("steps", [])
        if len(steps) != 11:
            return fail("workflow should expose 11 SaaS task steps")
        step_types = [step.get("task_type") for step in steps]
        if step_types[:3] != ["ceo.intake", "market.data_packet", "market.report"]:
            return fail("SaaS task steps should preserve workflow order")
        provider_steps = {step.get("task_type"): step.get("provider_job_keys", []) for step in steps}
        if "public_search.market_research" not in provider_steps.get("market.data_packet", []):
            return fail("market data packet step should declare its public-search provider job")
        if "sourcing.1688_availability" not in provider_steps.get("source.match", []):
            return fail("source matching step should declare its sourcing provider job")
        if "media.asset_generation" not in provider_steps.get("asset.brief", []):
            return fail("asset brief step should declare its provider-neutral media provider job")
        if workflow.get("queue_job", {}).get("status") != "queued":
            return fail("workflow creation should enqueue a job before worker execution")
        if workflow.get("runtime") is not None:
            return fail("queued workflow creation should not run Runtime inline")
        provider_plan = fetch_json(f"{base_url}/tasks/{task_id}/provider-job-plan", token=token).get("provider_job_plan", {})
        if provider_plan.get("provider_step_count", 0) < 8:
            return fail("provider job plan should expand workflow steps into provider work units")
        provider_job_keys = {item.get("provider_job_key") for item in provider_plan.get("provider_steps", [])}
        for required_provider_job in {"public_search.market_research", "ebay.read_only_snapshot", "sourcing.1688_availability", "media.asset_generation", "logistics.orange_connex_quote", "model.role_report_assist"}:
            if required_provider_job not in provider_job_keys:
                return fail(f"provider job plan missing {required_provider_job}")
        if provider_plan.get("secret_exposed") is not False or provider_plan.get("real_platform_writes_enabled") is not False:
            return fail("provider job plan must not expose secrets or enable real writes")
        blocked_logistics = [
            item
            for item in provider_plan.get("provider_steps", [])
            if item.get("provider_job_key") == "logistics.orange_connex_quote" and item.get("missing_inputs")
        ]
        if not blocked_logistics:
            return fail("provider job plan should surface missing logistics package facts")
        secret_grant_plan = fetch_json(f"{base_url}/tasks/{task_id}/secret-grant-plan", token=token).get("secret_grant_plan", {})
        if secret_grant_plan.get("grant_request_count", 0) < 8:
            return fail("secret grant plan should expand provider jobs into task-scoped grant requests")
        if secret_grant_plan.get("raw_secret_returned") is not False or secret_grant_plan.get("frontend_gets_raw_secret") is not False:
            return fail("secret grant plan must not return raw secrets to frontend")
        if secret_grant_plan.get("runtime_gets_raw_secret") is not False or secret_grant_plan.get("secret_exposed") is not False:
            return fail("secret grant plan must not expose raw secrets to Runtime")
        if secret_grant_plan.get("rules", {}).get("one_provider_job_one_grant") is not True:
            return fail("secret grant plan should require one grant per provider job")
        if secret_grant_plan.get("grant_contract_ready_count", 0) < 1:
            return fail("secret grant plan should use the existing eBay refresh-token secret_ref")
        if secret_grant_plan.get("blocked_count", 0) < 1:
            return fail("secret grant plan should surface missing model/search/media/source/logistics secret_refs")
        ebay_grants = [
            item
            for item in secret_grant_plan.get("grant_requests", [])
            if item.get("required_secret_purpose") == "ebay_refresh_token"
        ]
        if not ebay_grants or any(item.get("secret_ref") != secret_ref_id for item in ebay_grants):
            return fail("eBay provider grants should bind to the task-scoped eBay refresh-token secret_ref")
        if any(item.get("runtime_handoff", {}).get("runtime_gets_raw_secret") is not False for item in secret_grant_plan.get("grant_requests", [])):
            return fail("each grant request must keep raw secrets away from Runtime")

        worker = post_json(f"{base_url}/workers/run-next", {}, token=token)
        if worker.get("status") != "completed":
            return fail("local worker should complete the queued product workflow")
        if not any(step.get("status") == "waiting" for step in worker.get("steps", [])):
            return fail("worker-run SaaS task steps should surface waiting/blocked states")
        if worker.get("saved", {}).get("reports", 0) < 10:
            return fail("worker should save Runtime reports into SaaS database")
        if worker.get("saved", {}).get("confirmations", 0) < 1:
            return fail("worker should save confirmation items into SaaS database")
        if worker.get("queue_job", {}).get("status") != "completed":
            return fail("queue job should complete after worker execution")
        if worker.get("runtime", {}).get("run", {}).get("task_count") != 11:
            return fail("Runtime bridge should run the 11-step product workflow")

        queue = fetch_json(f"{base_url}/queue-jobs", token=token)
        if not queue.get("queue_jobs") or queue["queue_jobs"][0].get("status") != "completed":
            return fail("queue endpoint should expose completed local worker job")
        timeline = fetch_json(f"{base_url}/tasks/{task_id}/timeline", token=token)
        timeline_events = timeline.get("timeline", {}).get("events", [])
        if not any(item.get("event_type") == "queue_job" for item in timeline_events):
            return fail("task timeline should include queue job events")
        if not any(item.get("event_type") == "report" for item in timeline_events):
            return fail("task timeline should include report events")

        blocked_hermes = post_json(
            f"{base_url}/tasks/product-workflow",
            {
                "store_id": store_id,
                "product": "Hermes Adapter Block Test",
                "merchant_goal": "This must fail because Jiejing SaaS no longer depends on Hermes adapters by default.",
                "adapter": "hermes-shadow",
                "run_mode": "inline",
            },
            token=token,
        )
        if blocked_hermes.get("worker_result", {}).get("status") != "failed":
            return fail("Hermes adapter must fail when independent SaaS mode is enabled")
        if blocked_hermes.get("queue_job", {}).get("status") != "failed":
            return fail("queue job should record failed Hermes adapter attempt")
        if "unsupported runtime adapter" not in str(blocked_hermes.get("worker_result", {}).get("error", "")):
            return fail("Hermes adapter failure should explain unsupported runtime adapter")

        queued_for_cancel = post_json(
            f"{base_url}/tasks/product-workflow",
            {
                "store_id": store_id,
                "product": "Cancel Retry Queue Test",
                "merchant_goal": "Create a queued task so cancellation and retry can be tested.",
                "adapter": "jiejing-local",
                "run_mode": "queued",
            },
            token=token,
        )
        cancel_job_id = queued_for_cancel.get("queue_job", {}).get("job_id")
        cancel_task_id = queued_for_cancel.get("task", {}).get("task_id")
        cancelled = post_json(
            f"{base_url}/queue-jobs/{cancel_job_id}/cancel",
            {"reason": "mvp regression cancellation"},
            token=token,
        )
        if cancelled.get("queue_job", {}).get("status") != "cancelled":
            return fail("queued job should be cancellable before worker execution")
        cancelled_steps = fetch_json(f"{base_url}/tasks/{cancel_task_id}/steps", token=token)
        if not all(step.get("status") == "cancelled" for step in cancelled_steps.get("steps", [])):
            return fail("cancelling a queued task should mark its steps cancelled")
        retried = post_json(
            f"{base_url}/queue-jobs/{cancel_job_id}/retry",
            {"reason": "mvp regression retry"},
            token=token,
        )
        retry_job_id = retried.get("queue_job", {}).get("job_id")
        if retried.get("queue_job", {}).get("status") != "queued":
            return fail("cancelled queue job should create a queued retry job")
        retried_worker = post_json(f"{base_url}/workers/run-next", {"job_id": retry_job_id}, token=token)
        if retried_worker.get("status") != "completed":
            return fail("retried queue job should complete through local worker")

        reports = fetch_json(f"{base_url}/reports?task_id={task_id}", token=token)
        if len(reports.get("reports", [])) < 10:
            return fail("reports endpoint should return persisted reports")
        steps_payload = fetch_json(f"{base_url}/tasks/{task_id}/steps", token=token)
        if len(steps_payload.get("steps", [])) != 11:
            return fail("task steps endpoint should return 11 persisted steps")

        confirmations = fetch_json(f"{base_url}/confirmations", token=token)
        pending = confirmations.get("confirmations", [])
        if not pending:
            return fail("confirmations endpoint should return pending items")
        high_risk_confirmation = next((item for item in pending if item.get("high_risk")), None)
        if not high_risk_confirmation:
            return fail("workflow should create at least one high-risk confirmation item")
        confirmation_id = high_risk_confirmation["confirmation_id"]
        encoded_confirmation_id = urllib.parse.quote(confirmation_id, safe="")
        operator_approve_status, _ = post_json_expect_error(
            f"{base_url}/confirmations/{encoded_confirmation_id}/decision",
            {"decision": "approve", "note": "operator should not approve high-risk actions"},
            token=operator_company_token,
        )
        if operator_approve_status != 403:
            return fail("operator must not approve high-risk confirmation items")

        decision = post_json(
            f"{base_url}/confirmations/{encoded_confirmation_id}/decision",
            {"decision": "approve", "note": "MVP regression only; still no real platform write."},
            token=token,
        )
        if decision.get("confirmation", {}).get("status") != "approved":
            return fail("confirmation decision should be recorded")

        preflight = post_json(
            f"{base_url}/confirmations/{encoded_confirmation_id}/preflight",
            {"platform": "ebay", "payload": {"publish_listing": True}},
            token=token,
        )
        if preflight.get("preflight", {}).get("status") != "blocked_missing_execution_facts":
            return fail("preflight should show missing publish facts before execution handoff")
        if preflight.get("preflight", {}).get("real_execution_allowed") is not False:
            return fail("preflight must not allow real execution")

        execution = post_json(
            f"{base_url}/confirmations/{encoded_confirmation_id}/execute",
            {"platform": "ebay", "idempotency_key": "mvp-regression-publish-001", "payload": {"publish_listing": True}},
            token=token,
        )
        if execution.get("execution", {}).get("status") != "simulated_no_platform_write":
            return fail("ExecutionService must remain demo/no-platform-write")
        if execution.get("execution", {}).get("audit", {}).get("preflight", {}).get("status") != "blocked_missing_execution_facts":
            return fail("ExecutionService should preserve the preflight result in audit")
        if not execution.get("execution", {}).get("audit", {}).get("idempotency", {}).get("duplicate_prevention_key"):
            return fail("ExecutionService should record a duplicate-prevention key")
        duplicate_execution = post_json(
            f"{base_url}/confirmations/{encoded_confirmation_id}/execute",
            {"platform": "ebay", "idempotency_key": "mvp-regression-publish-001", "payload": {"publish_listing": True}},
            token=token,
        )
        if duplicate_execution.get("execution", {}).get("status") != "duplicate_execution_suppressed":
            return fail("ExecutionService should suppress duplicate execution handoff with the same idempotency key")
        if duplicate_execution.get("execution", {}).get("audit", {}).get("duplicate_guard") is not True:
            return fail("duplicate execution response should expose duplicate guard audit state")

        audit = fetch_json(f"{base_url}/audit-logs?limit=200", token=token)
        action_types = {item.get("action_type") for item in audit.get("audit_logs", [])}
        required_actions = {
            "auth.register",
            "store.create",
            "connection.create",
            "task.create",
            "runtime.workflow.completed",
            "runtime.outputs.saved",
            "confirmation.approve",
            "execution_service.result",
            "execution_service.duplicate_guard",
        }
        if missing := required_actions - action_types:
            return fail("audit log missing actions: " + ",".join(sorted(missing)))

        other = post_json(
            f"{base_url}/auth/register",
            {
                "email": "other@example.com",
                "password": "local-test-password",
                "company_name": "Other Company",
            },
        )
        status, body = post_json_expect_error(
            f"{base_url}/tasks/product-workflow",
            {"store_id": store_id, "product": "Access Control Test", "merchant_goal": "Should not access another company store."},
            token=other["token"],
        )
        if status != 404 or "not accessible" not in body.get("error", ""):
            return fail("tenant isolation should block another company from using the store")

        print("PASS jiejing_saas_backend_mvp")
        print(f"saas_db={SAAS_DB}")
        print(f"runtime_db={RUNTIME_DB}")
        print(f"workflow_task_id={task_id}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_health(base_url: str) -> int:
    for _ in range(60):
        try:
            health = fetch_json(f"{base_url}/health")
            if health.get("status") == "ok":
                return 0
        except Exception:
            time.sleep(0.1)
    return 1


def fetch_json(url: str, token: str | None = None) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_json_expect_error(url: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, fetch_json(url, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json_expect_error(url: str, payload: dict[str, Any], token: str | None = None) -> tuple[int, dict[str, Any]]:
    try:
        return 200, post_json(url, payload, token=token)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def post_raw_expect_error(
    url: str,
    body: bytes,
    *,
    content_type: str = "application/json",
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body_bytes = exc.read()
        except OSError:
            return exc.code, {}
        if not body_bytes:
            return exc.code, {}
        return exc.code, json.loads(body_bytes.decode("utf-8"))


def post_declared_oversized_expect_error(url: str, *, declared_length: int) -> tuple[int, dict[str, Any]]:
    """Verify the server rejects an oversized request before reading its body.

    Sending the entire payload races the server's intentional early close and
    produces a client-side BrokenPipeError on Linux.  Declaring the oversized
    Content-Length exercises the actual boundary without depending on socket
    buffer behavior or allocating an unnecessary megabyte-scale fixture.
    """

    parsed = urllib.parse.urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=20)
    try:
        target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        connection.putrequest("POST", target)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(declared_length))
        connection.endheaders()
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body.decode("utf-8")) if body else {}
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
