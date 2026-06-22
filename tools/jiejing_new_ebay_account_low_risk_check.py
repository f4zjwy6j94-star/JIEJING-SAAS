#!/usr/bin/env python3
"""Low-risk gate for the next clean eBay account test.

This tool checks observable SaaS state only. It never starts OAuth, never runs
sync, and never performs a real platform write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PUBLIC_ENDPOINTS = ["/health", "/readiness/product-saas"]
AUTH_ENDPOINTS = ["/stores", "/queue/health", "/billing/usage"]
RUNBOOK_CONTRACT_VERSION = "2026-06-18-new-ebay-account-low-risk-smoke"
RUNBOOK_PHASES = [
    {
        "key": "public_preflight_ready",
        "title": "Public SaaS preflight is healthy",
        "category": "preflight",
        "required_evidence": ["/health", "/health/deep", "/readiness/product-saas"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "clean_new_account_declared",
        "title": "Clean new eBay account boundary",
        "category": "account",
        "required_evidence": ["operator clean-account declaration"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "new_account_oauth_authorization_gate",
        "title": "New-account OAuth authorization gate",
        "category": "oauth",
        "required_evidence": ["backend OAuth audit entry", "Vault/KMS secret_ref metadata"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "official_packet_account_health_snapshot",
        "title": "Official packet and account health snapshot",
        "category": "account_health",
        "required_evidence": ["/readiness/product-saas", "/stores/{store_id}/account-health"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "new_product_duplicate_guard",
        "title": "New product duplicate guard",
        "category": "product",
        "required_evidence": ["fresh product", "fresh SKU", "fresh images", "duplicate guard proof"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "publish_health_confirmation_gate",
        "title": "Publish health report and confirmation gate",
        "category": "publish_health",
        "required_evidence": ["red/yellow/green publish health report", "confirmation center preflight"],
        "confirmation_center_required": True,
        "real_platform_write_step": False,
    },
    {
        "key": "controlled_real_publish_probe",
        "title": "Controlled real publish probe",
        "category": "real_publish",
        "required_evidence": ["approved confirmation", "listing ID", "offer ID", "audit evidence"],
        "confirmation_center_required": True,
        "real_platform_write_step": True,
    },
    {
        "key": "post_publish_cockpit_cleanup_gate",
        "title": "Post-publish cockpit and test cleanup gate",
        "category": "post_publish",
        "required_evidence": ["1h/24h/7d cockpit", "cleanup confirmation", "execution result"],
        "confirmation_center_required": True,
        "real_platform_write_step": True,
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check readiness for a clean new eBay account test.")
    parser.add_argument("--base-url", default=os.environ.get("JIEJING_SAAS_BASE_URL", "").strip())
    parser.add_argument("--store-id", default=os.environ.get("JIEJING_STORE_ID", "").strip())
    parser.add_argument("--token-env", default="JIEJING_SAAS_TOKEN")
    parser.add_argument("--checklist-only", action="store_true")
    args = parser.parse_args()

    if args.checklist_only:
        print(json.dumps(_checklist(), ensure_ascii=False, indent=2))
        return 0
    if not args.base_url:
        print(json.dumps({"ok": False, "blocked_by": ["missing_base_url"], "secret_exposed": False}, ensure_ascii=False, indent=2))
        return 2

    base_url = args.base_url.rstrip("/")
    token = os.environ.get(args.token_env, "").strip()
    result = {
        "ok": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": _safe_base_url(base_url),
        "public": {},
        "authenticated": {},
        "blockers": [],
        "warnings": [],
        "next_actions": [],
        "runbook_contract_version": RUNBOOK_CONTRACT_VERSION,
        "phases": [],
        "phase_count": len(RUNBOOK_PHASES),
        "ready_phase_count": 0,
        "runbook_ready": False,
        "no_oauth_started": True,
        "no_real_write_performed": True,
        "secret_exposed": False,
    }

    for path in PUBLIC_ENDPOINTS:
        payload = _get_json(base_url + path)
        result["public"][path] = payload
        if payload.get("request_failed"):
            result["blockers"].append(f"{path}:request_failed")

    health = result["public"].get("/health", {})
    if health.get("status") != "ok":
        result["blockers"].append("public_health_not_ok")
    if health.get("database_startup_status") not in {"ready", None, ""}:
        result["blockers"].append("database_startup_not_ready")

    readiness = (result["public"].get("/readiness/product-saas", {}) or {}).get("readiness", {})
    item_status = {item.get("key"): item for item in readiness.get("items", []) if isinstance(item, dict)}
    for key in ["database_live_probe", "queue_runtime_health", "worker_runtime_health", "account_health_incident_mode"]:
        item = item_status.get(key)
        if item and item.get("severity") == "blocker" and item.get("status") != "ready":
            result["blockers"].append(f"readiness:{key}:{item.get('status')}")
    if readiness.get("can_accept_real_customers") is True:
        result["warnings"].append("public_readiness_claims_real_customers_allowed_recheck_business_gate")

    if token:
        for path in AUTH_ENDPOINTS:
            payload = _get_json(base_url + path, token=token)
            result["authenticated"][path] = payload
            if payload.get("request_failed"):
                result["blockers"].append(f"{path}:request_failed")
        if args.store_id:
            account_health = _get_json(base_url + f"/stores/{args.store_id}/account-health", token=token)
            result["authenticated"]["/stores/{store_id}/account-health"] = account_health
            health_snapshot = account_health.get("account_health") if isinstance(account_health.get("account_health"), dict) else {}
            if health_snapshot.get("incident_mode"):
                result["blockers"].append(f"account_health:{health_snapshot.get('status') or 'incident_mode'}")
            if health_snapshot.get("can_execute_real_writes") is False:
                result["warnings"].append("account_health_blocks_real_writes")
        else:
            result["warnings"].append("store_id_not_provided_for_account_health_check")
    else:
        result["warnings"].append("auth_token_not_provided_public_checks_only")

    phase_statuses = _phase_statuses(
        result=result,
        readiness=readiness,
        token_present=bool(token),
        store_id_present=bool(args.store_id),
    )
    result["phases"] = phase_statuses
    result["ready_phase_count"] = sum(1 for phase in phase_statuses if phase.get("status") == "ready")
    result["phase_count"] = len(phase_statuses)
    result["runbook_ready"] = result["ready_phase_count"] == result["phase_count"]
    for phase in phase_statuses:
        if phase.get("status") != "ready":
            result["blockers"].append(f"runbook:{phase.get('key')}:{phase.get('status')}")

    if result["blockers"]:
        result["ok"] = False
        result["next_actions"].append("Fix blockers before new eBay OAuth, sync, publish health, confirmation, real publish or cleanup.")
    else:
        result["next_actions"].append("Proceed to new-account OAuth only if this is the clean new eBay account, not the frozen old account.")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def _get_json(url: str, *, token: str = "") -> dict:
    headers = {"accept": "application/json", "cache-control": "no-store"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:  # nosec B310 - operator-supplied SaaS base URL.
            raw = response.read(1_000_000)
    except HTTPError as exc:
        return {"request_failed": True, "http_status": exc.code, "secret_exposed": False}
    except (TimeoutError, URLError) as exc:
        return {"request_failed": True, "error_type": type(exc).__name__, "secret_exposed": False}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"request_failed": True, "error_type": "invalid_json", "secret_exposed": False}
    return parsed if isinstance(parsed, dict) else {"request_failed": True, "error_type": "non_object_json", "secret_exposed": False}


def _safe_base_url(value: str) -> str:
    return value.split("?", 1)[0].rstrip("/")


def _checklist() -> dict:
    return {
        "contract_version": RUNBOOK_CONTRACT_VERSION,
        "phases": [_phase_contract(phase) for phase in RUNBOOK_PHASES],
        "phase_count": len(RUNBOOK_PHASES),
        "sequence": [
            "public health",
            "product readiness",
            "new Jiejing merchant login",
            "new eBay account OAuth",
            "official read-only sync",
            "account health",
            "new product duplicate check",
            "publish health report",
            "confirmation center",
            "real publish",
            "post-publish cockpit",
            "test cleanup through confirmation center",
        ],
        "never": [
            "reuse old frozen account",
            "reuse old listing/SKU/image/report",
            "bypass confirmation center",
            "print or persist tokens",
        ],
        "secret_exposed": False,
    }


def _phase_statuses(*, result: dict, readiness: dict, token_present: bool, store_id_present: bool) -> list[dict]:
    health = result.get("public", {}).get("/health", {}) if isinstance(result.get("public"), dict) else {}
    account_health = {}
    authenticated = result.get("authenticated", {}) if isinstance(result.get("authenticated"), dict) else {}
    account_health_payload = authenticated.get("/stores/{store_id}/account-health", {})
    if isinstance(account_health_payload, dict):
        account_health = account_health_payload.get("account_health") if isinstance(account_health_payload.get("account_health"), dict) else {}
    official_packet_ready = _official_packet_ready(readiness)
    account_health_ready = (
        token_present
        and store_id_present
        and isinstance(account_health_payload, dict)
        and not account_health_payload.get("request_failed")
        and not account_health.get("incident_mode")
        and account_health.get("can_execute_real_writes") is not False
    )
    checks = {
        "public_preflight_ready": (
            health.get("status") == "ok"
            and health.get("database_startup_status") in {"ready", None, ""}
            and readiness.get("beta_ready") is True
            and int(readiness.get("blocker_count") or 0) == 0
            and _readiness_item(readiness, "database_live_probe").get("status") == "ready"
            and _readiness_item(readiness, "queue_runtime_health").get("status") == "ready"
            and _readiness_item(readiness, "worker_runtime_health").get("status") == "ready"
        ),
        "clean_new_account_declared": _env_bool("JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN"),
        "new_account_oauth_authorization_gate": _env_bool("JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED"),
        "official_packet_account_health_snapshot": official_packet_ready and account_health_ready,
        "new_product_duplicate_guard": _env_bool("JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED"),
        "publish_health_confirmation_gate": _readiness_item(readiness, "publish_safety_system").get("status") == "ready"
        or _env_bool("JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY"),
        "controlled_real_publish_probe": _env_bool("JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"),
        "post_publish_cockpit_cleanup_gate": (
            _readiness_item(readiness, "post_publish_cockpit").get("status") == "ready"
            and _env_bool("JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED")
        ),
    }
    diagnostics = {
        "public_preflight_ready": {
            "health_status": health.get("status") or "missing",
            "beta_ready": readiness.get("beta_ready") is True,
            "blocker_count": int(readiness.get("blocker_count") or 0),
        },
        "clean_new_account_declared": {"env_flag": "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN"},
        "new_account_oauth_authorization_gate": {"env_flag": "JIEJING_NEW_EBAY_ACCOUNT_OAUTH_COMPLETED"},
        "official_packet_account_health_snapshot": {
            "official_packet_ready": official_packet_ready,
            "token_present": token_present,
            "store_id_present": store_id_present,
            "account_health_ready": account_health_ready,
        },
        "new_product_duplicate_guard": {"env_flag": "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED"},
        "publish_health_confirmation_gate": {
            "readiness_status": _readiness_item(readiness, "publish_safety_system").get("status") or "missing",
            "env_flag": "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
        },
        "controlled_real_publish_probe": {"env_flag": "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED"},
        "post_publish_cockpit_cleanup_gate": {
            "readiness_status": _readiness_item(readiness, "post_publish_cockpit").get("status") or "missing",
            "env_flag": "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
        },
    }
    phases = []
    for phase in RUNBOOK_PHASES:
        ready = bool(checks.get(phase["key"]))
        phases.append(
            {
                **_phase_contract(phase),
                "status": "ready" if ready else "blocked",
                "severity": "info" if ready else "blocker",
                "diagnostics": {**diagnostics.get(phase["key"], {}), "secret_exposed": False},
            }
        )
    return phases


def _phase_contract(phase: dict) -> dict:
    return {
        "key": phase["key"],
        "title": phase["title"],
        "category": phase["category"],
        "required_evidence": list(phase.get("required_evidence") or []),
        "requires_clean_new_ebay_account": True,
        "old_frozen_account_reuse_allowed": False,
        "old_demo_product_or_sku_allowed": False,
        "triggers_ebay_oauth": False,
        "repeat_oauth_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "real_platform_write_step": bool(phase.get("real_platform_write_step")),
        "confirmation_center_required": bool(phase.get("confirmation_center_required")),
        "permanent_audit_required": True,
        "secret_exposed": False,
    }


def _readiness_item(readiness: dict, key: str) -> dict:
    for item in readiness.get("items") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return {}


def _official_packet_ready(readiness: dict) -> bool:
    evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
    if not evidence:
        evidence = readiness.get("evidence") if isinstance(readiness.get("evidence"), dict) else {}
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    present = set(evidence.get("latest_ebay_packet_present_resource_keys") or [])
    return bool(evidence.get("latest_ebay_packet_id")) and required.issubset(present)


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
