#!/usr/bin/env python3
"""Low-risk gate for the next clean eBay account test.

This tool checks observable SaaS state only. It never starts OAuth, never runs
sync, and never performs a real platform write.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


PUBLIC_ENDPOINTS = ["/health", "/health/deep", "/readiness/product-saas"]
AUTH_ENDPOINTS = [
    "/readiness/product-saas",
    "/stores",
    "/queue/health",
    "/billing/usage",
    "/queue-jobs?status=completed&limit=200",
    "/audit-logs?limit=200",
]
RUNBOOK_CONTRACT_VERSION = "2026-06-18-new-ebay-account-low-risk-smoke"
MAX_OFFICIAL_PACKET_AGE_SECONDS = 6 * 60 * 60
READINESS_ITEM_KEYS = {
    "database_live_probe",
    "queue_runtime_health",
    "worker_runtime_health",
    "account_health_incident_mode",
    "publish_safety_system",
    "post_publish_cockpit",
}
ACCOUNT_BOUNDARY_FLAGS = [
    "JIEJING_NEW_EBAY_ACCOUNT_CONFIRMED_CLEAN",
    "JIEJING_NEW_EBAY_OLD_FROZEN_ACCOUNT_REJECTED",
]
FRESH_PRODUCT_FLAGS = [
    "JIEJING_NEW_EBAY_FRESH_PRODUCT_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_SKU_DECLARED",
    "JIEJING_NEW_EBAY_FRESH_ASSETS_DECLARED",
    "JIEJING_NEW_EBAY_NO_OLD_LISTING_OR_REPORT_REUSE",
    "JIEJING_NEW_EBAY_PRODUCT_DUPLICATE_GUARD_PASSED",
]
PUBLISH_CONFIRMATION_FLAGS = [
    "JIEJING_NEW_EBAY_PUBLISH_HEALTH_CONFIRMATION_READY",
    "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
]
REAL_PUBLISH_FLAGS = [
    "JIEJING_NEW_EBAY_PUBLISH_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_ACCOUNT_REAL_PUBLISH_PASSED",
]
CLEANUP_FLAGS = [
    "JIEJING_NEW_EBAY_CLEANUP_CONFIRMATION_APPROVED",
    "JIEJING_NEW_EBAY_TEST_CLEANUP_CONFIRMED",
]
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
        "required_evidence": ["operator clean-account declaration", "old frozen account rejected"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "new_account_oauth_authorization_gate",
        "title": "New-account OAuth authorization gate",
        "category": "oauth",
        "required_evidence": [
            "/connections?store_id={store_id}",
            "/stores/{store_id}/ebay-oauth/read-only-status",
            "current-store authorized OAuth connection",
            "read-only-plan only when missing and explicitly approved",
        ],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "official_packet_account_health_snapshot",
        "title": "Official packet and account health snapshot",
        "category": "account_health",
        "required_evidence": [
            "/stores/{store_id}/account-health",
            "/connections?store_id={store_id}",
            "/stores/{store_id}/ebay-oauth/read-only-status",
            "/data-packets?store_id={store_id}&platform=ebay&limit=1",
            "/queue-jobs?status=completed&limit=200",
            "/audit-logs?limit=200",
        ],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "new_product_duplicate_guard",
        "title": "New product duplicate guard",
        "category": "product",
        "required_evidence": ["fresh product", "fresh SKU", "fresh images", "no old listing/report reuse", "duplicate guard proof"],
        "confirmation_center_required": False,
        "real_platform_write_step": False,
    },
    {
        "key": "publish_health_confirmation_gate",
        "title": "Publish health report and confirmation gate",
        "category": "publish_health",
        "required_evidence": ["red/yellow/green publish health report", "confirmation center preflight", "owner confirmation approval"],
        "confirmation_center_required": True,
        "real_platform_write_step": False,
    },
    {
        "key": "controlled_real_publish_probe",
        "title": "Controlled real publish probe",
        "category": "real_publish",
        "required_evidence": ["approved confirmation", "listing ID", "offer ID", "fresh SKU", "audit evidence"],
        "confirmation_center_required": True,
        "real_platform_write_step": True,
    },
    {
        "key": "post_publish_cockpit_cleanup_gate",
        "title": "Post-publish cockpit and test cleanup gate",
        "category": "post_publish",
        "required_evidence": ["1h/24h/7d cockpit", "cleanup confirmation approval", "execution result"],
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

    try:
        base_url = _validated_base_url(args.base_url)
    except ValueError:
        print(json.dumps({"ok": False, "blocked_by": ["invalid_base_url"], "secret_exposed": False}, ensure_ascii=False, indent=2))
        return 2
    token = os.environ.get(args.token_env, "").strip()
    if token and not _authenticated_origin_allowed(base_url):
        print(
            json.dumps(
                {"ok": False, "blocked_by": ["insecure_authenticated_origin"], "secret_exposed": False},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
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

    public_observed: dict[str, dict] = {}
    for path in PUBLIC_ENDPOINTS:
        payload = _get_json(base_url + path)
        public_observed[path] = payload
        result["public"][path] = _safe_endpoint_summary(path, payload)
        if payload.get("request_failed"):
            result["blockers"].append(f"{path}:request_failed")

    health = public_observed.get("/health", {})
    if health.get("status") != "ok":
        result["blockers"].append("public_health_not_ok")
    if health.get("database_startup_status") != "ready":
        result["blockers"].append("database_startup_not_ready")
    deep_payload = public_observed.get("/health/deep", {})
    operational = deep_payload.get("operational_health") if isinstance(deep_payload.get("operational_health"), dict) else {}
    deep_database = operational.get("database") if isinstance(operational.get("database"), dict) else {}
    deep_queue = operational.get("queue") if isinstance(operational.get("queue"), dict) else {}
    deep_worker = operational.get("worker") if isinstance(operational.get("worker"), dict) else {}
    if not (
        operational.get("status") == "ready"
        and deep_database.get("status") == "ready"
        and deep_queue.get("status") == "ready"
        and (deep_worker.get("status") or deep_worker.get("heartbeat_status")) == "ready"
    ):
        result["blockers"].append("public_deep_health_not_ready")

    readiness_payload = public_observed.get("/readiness/product-saas", {})
    readiness_value = readiness_payload.get("readiness") if isinstance(readiness_payload, dict) else None
    readiness = readiness_value if isinstance(readiness_value, dict) else {}
    if not _is_nonnegative_int(readiness.get("blocker_count")) or not _is_nonnegative_int(readiness.get("warning_count")):
        result["blockers"].append("readiness_count_invalid")
    item_status = {item.get("key"): item for item in readiness.get("items", []) if isinstance(item, dict)}
    for key in ["database_live_probe", "queue_runtime_health", "worker_runtime_health", "account_health_incident_mode"]:
        item = item_status.get(key)
        if item and item.get("severity") == "blocker" and item.get("status") != "ready":
            result["blockers"].append(f"readiness:{key}:not_ready")
    if readiness.get("can_accept_real_customers") is True:
        result["warnings"].append("public_readiness_claims_real_customers_allowed_recheck_business_gate")

    authenticated_observed: dict[str, dict] = {}
    if token:
        for path in AUTH_ENDPOINTS:
            payload = _get_json(base_url + path, token=token)
            authenticated_observed[path] = payload
            result["authenticated"][path] = _safe_endpoint_summary(path, payload)
            if payload.get("request_failed"):
                result["blockers"].append(f"{path}:request_failed")
        if args.store_id:
            encoded_store_id = quote(args.store_id, safe="")
            account_health = _get_json(base_url + f"/stores/{encoded_store_id}/account-health", token=token)
            authenticated_observed["/stores/{store_id}/account-health"] = account_health
            result["authenticated"]["/stores/{store_id}/account-health"] = _safe_endpoint_summary(
                "/stores/{store_id}/account-health",
                account_health,
            )
            connections = _get_json(
                base_url + f"/connections?store_id={encoded_store_id}",
                token=token,
            )
            authenticated_observed["/connections?store_id={store_id}"] = connections
            result["authenticated"]["/connections?store_id={store_id}"] = _safe_endpoint_summary(
                "/connections?store_id={store_id}",
                connections,
            )
            oauth_status = _get_json(
                base_url + f"/stores/{encoded_store_id}/ebay-oauth/read-only-status",
                token=token,
            )
            authenticated_observed["/stores/{store_id}/ebay-oauth/read-only-status"] = oauth_status
            result["authenticated"]["/stores/{store_id}/ebay-oauth/read-only-status"] = _safe_endpoint_summary(
                "/stores/{store_id}/ebay-oauth/read-only-status",
                oauth_status,
            )
            packets = _get_json(
                base_url + f"/data-packets?store_id={encoded_store_id}&platform=ebay&limit=1",
                token=token,
            )
            authenticated_observed["/data-packets?store_id={store_id}&platform=ebay&limit=1"] = packets
            result["authenticated"]["/data-packets?store_id={store_id}&platform=ebay&limit=1"] = _safe_endpoint_summary(
                "/data-packets?store_id={store_id}&platform=ebay&limit=1",
                packets,
            )
            commercial_gate = _get_json(
                base_url + f"/commercial/launch-gate?store_id={encoded_store_id}",
                token=token,
            )
            authenticated_observed["/commercial/launch-gate?store_id={store_id}"] = commercial_gate
            result["authenticated"]["/commercial/launch-gate?store_id={store_id}"] = _safe_endpoint_summary(
                "/commercial/launch-gate?store_id={store_id}",
                commercial_gate,
            )
            health_snapshot = account_health.get("account_health") if isinstance(account_health.get("account_health"), dict) else {}
            if health_snapshot.get("incident_mode"):
                result["blockers"].append("account_health_not_safe")
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
        expected_store_id=args.store_id,
        authenticated_observed=authenticated_observed,
    )
    result["phases"] = phase_statuses
    result["ready_phase_count"] = sum(1 for phase in phase_statuses if phase.get("status") == "ready")
    result["phase_count"] = len(phase_statuses)
    result["runbook_ready"] = result["ready_phase_count"] == result["phase_count"]
    for phase in phase_statuses:
        if phase.get("status") != "ready":
            result["blockers"].append(f"runbook:{phase.get('key')}:{phase.get('status')}")

    oauth_phase_ready = next(
        (
            phase.get("status") == "ready"
            for phase in phase_statuses
            if phase.get("key") == "new_account_oauth_authorization_gate"
        ),
        False,
    )
    if result["blockers"]:
        result["ok"] = False
        result["next_actions"].append("Fix blockers before new eBay OAuth, sync, publish health, confirmation, real publish or cleanup.")
        if oauth_phase_ready:
            result["next_actions"].append(
                "The current store is already OAuth-authorized: do not create a new OAuth plan and do not repeat OAuth."
            )
        else:
            result["next_actions"].append(
                "Current-store OAuth evidence is missing. Create a read-only plan only when this exact step has explicit owner approval; the checker never creates the plan."
            )
    else:
        result["next_actions"].append(
            "The current store is already OAuth-authorized: do not create a new OAuth plan and do not repeat OAuth."
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def _get_json(url: str, *, token: str = "") -> dict:
    parsed_url = urlsplit(url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        return {"request_failed": True, "error_type": "unsafe_request_url", "secret_exposed": False}
    if token and not _authenticated_origin_allowed(url):
        return {"request_failed": True, "error_type": "insecure_authenticated_origin", "secret_exposed": False}
    headers = {"accept": "application/json", "cache-control": "no-store"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with build_opener(_NoRedirectHandler()).open(request, timeout=15) as response:  # nosec B310 - validated SaaS origin.
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


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError("invalid base URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid base URL port") from exc
    hostname = parsed.hostname
    safe_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    return f"{parsed.scheme.lower()}://{safe_host}{f':{port}' if port is not None else ''}"


def _authenticated_origin_allowed(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme.lower() == "https" and bool(parsed.hostname):
        return True
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        return False
    hostname = parsed.hostname.strip().lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    scheme = str(parsed.scheme or "").lower()
    hostname = parsed.hostname or ""
    if not scheme or not hostname:
        return "configured"
    safe_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{scheme}://{safe_host}{f':{port}' if port is not None else ''}"


def _safe_endpoint_summary(path: str, payload: dict) -> dict:
    if payload.get("request_failed"):
        return {
            "request_failed": True,
            "http_status": _safe_nonnegative_int(payload.get("http_status")),
            "error_type": _allowed_classification(
                payload.get("error_type"),
                {"timeouterror", "urlerror", "invalid_json", "non_object_json", "unsafe_request_url", "insecure_authenticated_origin"},
            ),
            "secret_exposed": False,
        }
    if path == "/health":
        return {
            "status": _allowed_classification(payload.get("status"), {"ok", "degraded"}),
            "database_startup_status": _allowed_classification(payload.get("database_startup_status"), {"ready", "degraded"}),
            "secret_exposed": False,
        }
    if path == "/health/deep":
        operational = payload.get("operational_health") if isinstance(payload.get("operational_health"), dict) else {}
        database = operational.get("database") if isinstance(operational.get("database"), dict) else {}
        queue = operational.get("queue") if isinstance(operational.get("queue"), dict) else {}
        worker = operational.get("worker") if isinstance(operational.get("worker"), dict) else {}
        return {
            "status": _allowed_classification(operational.get("status"), {"ready", "degraded"}),
            "database_status": _allowed_classification(database.get("status"), {"ready", "degraded"}),
            "queue_status": _allowed_classification(queue.get("status"), {"ready", "degraded"}),
            "worker_status": _allowed_classification(worker.get("status") or worker.get("heartbeat_status"), {"ready", "degraded"}),
            "secret_exposed": False,
        }
    if path == "/readiness/product-saas":
        readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
        return {
            "beta_ready": readiness.get("beta_ready") is True,
            "can_accept_real_customers": readiness.get("can_accept_real_customers") is True,
            "blocker_count": _safe_nonnegative_int(readiness.get("blocker_count")),
            "warning_count": _safe_nonnegative_int(readiness.get("warning_count")),
            "authenticated_summary": readiness.get("authenticated_summary") is True,
            "item_statuses": [
                {
                    "key": _allowed_classification(item.get("key"), READINESS_ITEM_KEYS),
                    "status": _allowed_classification(item.get("status"), {"ready", "blocked", "degraded", "warning", "not_ready"}),
                    "severity": _allowed_classification(item.get("severity"), {"info", "warning", "blocker"}),
                }
                for item in readiness.get("items") or []
                if isinstance(item, dict)
            ],
            "global_ebay_evidence_not_used_for_store_scope": True,
            "secret_exposed": False,
        }
    if path == "/stores":
        stores = payload.get("stores") if isinstance(payload.get("stores"), list) else []
        return {"store_count": len(stores), "store_values_withheld": True, "secret_exposed": False}
    if path == "/stores/{store_id}/account-health":
        health = payload.get("account_health") if isinstance(payload.get("account_health"), dict) else {}
        return {
            "status": _allowed_classification(
                health.get("status"),
                {"normal", "attention", "restricted", "suspended", "payout_hold", "quota_limited"},
            ),
            "incident_mode": health.get("incident_mode") is True,
            "can_execute_real_writes": health.get("can_execute_real_writes") is True,
            "identity_values_withheld": True,
            "secret_exposed": False,
        }
    if path == "/connections?store_id={store_id}":
        connections = payload.get("connections") if isinstance(payload.get("connections"), list) else []
        return {
            "connection_count": len(connections),
            "authorized_ebay_connection_count": sum(
                1
                for item in connections
                if isinstance(item, dict)
                and str(item.get("platform") or "").strip().lower() == "ebay"
                and str(item.get("status") or "").strip().lower()
                in {"read_only_authorized", "publish_authorized", "read_write_authorized", "authorized", "connected"}
            ),
            "connection_values_withheld": True,
            "secret_exposed": False,
        }
    if path == "/stores/{store_id}/ebay-oauth/read-only-status":
        status = payload.get("ebay_oauth_read_only_status") if isinstance(payload.get("ebay_oauth_read_only_status"), dict) else {}
        return {
            "authorized": status.get("authorized") is True,
            "pending": status.get("pending") is True,
            "strong_identity_ready": status.get("strong_identity_ready") is True,
            "backend_provenance_ready": status.get("backend_provenance_ready") is True,
            "connection_binding_present": bool(str(status.get("connection_id_sha256") or "")),
            "secret_exposed": False,
        }
    if path == "/data-packets?store_id={store_id}&platform=ebay&limit=1":
        packets = payload.get("data_packets") if isinstance(payload.get("data_packets"), list) else []
        return {
            "packet_count": len(packets),
            "intrinsic_official_packet_count": sum(1 for item in packets if _official_store_packet_ready(item)),
            "packet_values_withheld": True,
            "secret_exposed": False,
        }
    if path == "/queue-jobs?status=completed&limit=200":
        jobs = payload.get("queue_jobs") if isinstance(payload.get("queue_jobs"), list) else []
        return {"completed_job_count": len(jobs), "job_values_withheld": True, "secret_exposed": False}
    if path == "/audit-logs?limit=200":
        audits = payload.get("audit_logs") if isinstance(payload.get("audit_logs"), list) else []
        return {"audit_count": len(audits), "audit_values_withheld": True, "secret_exposed": False}
    return {"response_received": True, "response_values_withheld": True, "secret_exposed": False}


def _checklist() -> dict:
    return {
        "contract_version": RUNBOOK_CONTRACT_VERSION,
        "phases": [_phase_contract(phase) for phase in RUNBOOK_PHASES],
        "phase_count": len(RUNBOOK_PHASES),
        "sequence": [
            "public health",
            "product readiness",
            "new Jiejing merchant login",
            "verify authenticated current-store eBay connection evidence",
            "create read-only OAuth plan only if evidence is missing and this step is explicitly approved",
            "run official read-only sync only if current-store evidence is missing and this exact step is approved",
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
            "create a new OAuth plan when current-store authorization evidence already exists",
            "create a read-only OAuth plan without explicit approval for that exact missing-evidence step",
            "mark duplicate guard ready without fresh product/SKU/assets declarations",
            "bypass confirmation center",
            "print or persist tokens",
        ],
        "required_operator_flags": {
            "account_boundary": ACCOUNT_BOUNDARY_FLAGS,
            "fresh_product_boundary": FRESH_PRODUCT_FLAGS,
            "publish_confirmation": PUBLISH_CONFIRMATION_FLAGS,
            "controlled_real_publish": REAL_PUBLISH_FLAGS,
            "cleanup_confirmation": CLEANUP_FLAGS,
        },
        "secret_exposed": False,
    }


def _phase_statuses(
    *,
    result: dict,
    readiness: dict,
    token_present: bool,
    store_id_present: bool,
    expected_store_id: str = "",
    authenticated_observed: dict | None = None,
) -> list[dict]:
    health = result.get("public", {}).get("/health", {}) if isinstance(result.get("public"), dict) else {}
    deep = result.get("public", {}).get("/health/deep", {}) if isinstance(result.get("public"), dict) else {}
    authenticated = (
        authenticated_observed
        if isinstance(authenticated_observed, dict)
        else result.get("authenticated", {})
        if isinstance(result.get("authenticated"), dict)
        else {}
    )
    store_scope = _current_store_evidence(
        authenticated=authenticated,
        expected_store_id=expected_store_id,
        token_present=token_present,
        store_id_present=store_id_present,
    )
    official_packet_ready = store_scope["official_packet_ready"]
    account_health_ready = store_scope["account_health_ready"]
    action_evidence = _current_store_new_account_action_evidence(authenticated)
    checks = {
        "public_preflight_ready": (
            health.get("status") == "ok"
            and health.get("database_startup_status") == "ready"
            and deep.get("status") == "ready"
            and deep.get("database_status") == "ready"
            and deep.get("queue_status") == "ready"
            and deep.get("worker_status") == "ready"
            and readiness.get("beta_ready") is True
            and _is_zero_nonnegative_int(readiness.get("blocker_count"))
            and _is_nonnegative_int(readiness.get("warning_count"))
            and _readiness_item(readiness, "database_live_probe").get("status") == "ready"
            and _readiness_item(readiness, "queue_runtime_health").get("status") == "ready"
            and _readiness_item(readiness, "worker_runtime_health").get("status") == "ready"
        ),
        "clean_new_account_declared": _env_all(ACCOUNT_BOUNDARY_FLAGS),
        "new_account_oauth_authorization_gate": store_scope["strong_oauth_boundary_ready"],
        "official_packet_account_health_snapshot": (
            store_scope["store_identity_ready"]
            and official_packet_ready
            and account_health_ready
            and store_scope["authorized_connection_ready"]
            and store_scope["account_identity_ready"]
            and store_scope["strong_oauth_boundary_ready"]
            and store_scope["packet_fresh"]
            and store_scope["packet_account_health_bound"]
            and store_scope["backend_official_sync_provenance_ready"]
        ),
        "new_product_duplicate_guard": _env_all(FRESH_PRODUCT_FLAGS),
        "publish_health_confirmation_gate": action_evidence["publish_health_confirmation_ready"],
        "controlled_real_publish_probe": action_evidence["controlled_real_publish_ready"],
        "post_publish_cockpit_cleanup_gate": action_evidence["post_publish_cleanup_ready"],
    }
    diagnostics = {
        "public_preflight_ready": {
            "health_status": health.get("status") or "missing",
            "beta_ready": readiness.get("beta_ready") is True,
            "blocker_count": _safe_nonnegative_int(readiness.get("blocker_count")),
        },
        "clean_new_account_declared": {"required_flags": _flag_diagnostics(ACCOUNT_BOUNDARY_FLAGS)},
        "new_account_oauth_authorization_gate": {
            "authorized_current_store_connection": store_scope["authorized_connection_ready"],
            "strong_oauth_identity_and_provenance": store_scope["strong_oauth_boundary_ready"],
            "oauth_plan_operator_approved_if_missing": _env_bool("JIEJING_NEW_EBAY_OAUTH_OPERATOR_APPROVED"),
        },
        "official_packet_account_health_snapshot": {
            "official_packet_ready": official_packet_ready,
            "token_present": token_present,
            "store_id_present": store_id_present,
            "account_health_ready": account_health_ready,
            "store_identity_ready": store_scope["store_identity_ready"],
            "authorized_connection_ready": store_scope["authorized_connection_ready"],
            "account_identity_ready": store_scope["account_identity_ready"],
            "packet_fresh": store_scope["packet_fresh"],
            "packet_account_health_bound": store_scope["packet_account_health_bound"],
            "backend_queue_job_provenance_ready": store_scope["backend_queue_job_provenance_ready"],
            "backend_system_audit_provenance_ready": store_scope["backend_system_audit_provenance_ready"],
            "backend_official_sync_provenance_ready": store_scope["backend_official_sync_provenance_ready"],
        },
        "new_product_duplicate_guard": {"required_flags": _flag_diagnostics(FRESH_PRODUCT_FLAGS)},
        "publish_health_confirmation_gate": {
            "current_store_version_bound_evidence": action_evidence["publish_health_confirmation_ready"],
        },
        "controlled_real_publish_probe": {
            "current_store_version_bound_evidence": action_evidence["controlled_real_publish_ready"],
        },
        "post_publish_cockpit_cleanup_gate": {
            "current_store_version_bound_evidence": action_evidence["post_publish_cleanup_ready"],
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


def _current_store_new_account_action_evidence(authenticated: dict) -> dict[str, bool]:
    payload = authenticated.get("/commercial/launch-gate?store_id={store_id}")
    gate = payload.get("commercial_launch_gate") if isinstance(payload, dict) else None
    evidence = gate.get("current_store_ebay_evidence") if isinstance(gate, dict) else None
    action = evidence.get("new_account_action_evidence") if isinstance(evidence, dict) else None
    if not isinstance(action, dict):
        action = {}
    contract_ready = action.get("contract_version") == RUNBOOK_CONTRACT_VERSION
    store_bound = action.get("company_store_bound") is True
    secret_safe = action.get("secret_exposed") is False
    boundary_ready = contract_ready and store_bound and secret_safe
    return {
        "publish_health_confirmation_ready": boundary_ready and action.get("publish_health_confirmation_ready") is True,
        "controlled_real_publish_ready": boundary_ready and action.get("controlled_real_publish_ready") is True,
        "post_publish_cleanup_ready": boundary_ready and action.get("post_publish_cleanup_ready") is True,
    }


def _current_store_evidence(
    *,
    authenticated: dict,
    expected_store_id: str,
    token_present: bool,
    store_id_present: bool,
) -> dict[str, bool]:
    stores_payload = authenticated.get("/stores", {}) if isinstance(authenticated.get("/stores"), dict) else {}
    stores = stores_payload.get("stores") if isinstance(stores_payload.get("stores"), list) else []
    selected_store = next(
        (
            store
            for store in stores
            if isinstance(store, dict)
            and str(store.get("store_id") or "") == expected_store_id
            and str(store.get("platform") or "").strip().lower() == "ebay"
        ),
        {},
    )
    company_id = str(selected_store.get("company_id") or "") if isinstance(selected_store, dict) else ""
    store_identity_ready = bool(token_present and store_id_present and expected_store_id and company_id)

    health_payload = authenticated.get("/stores/{store_id}/account-health", {})
    health = health_payload.get("account_health") if isinstance(health_payload, dict) and isinstance(health_payload.get("account_health"), dict) else {}
    account_health_ready = bool(
        store_identity_ready
        and not health_payload.get("request_failed")
        and str(health.get("company_id") or "") == company_id
        and str(health.get("store_id") or "") == expected_store_id
        and str(health.get("platform") or "").strip().lower() == "ebay"
        and str(health.get("status") or "").strip().lower() in {"normal"}
        and health.get("incident_mode") is False
        and health.get("can_execute_real_writes") is True
    )

    connections_payload = authenticated.get("/connections?store_id={store_id}", {})
    connections = connections_payload.get("connections") if isinstance(connections_payload, dict) and isinstance(connections_payload.get("connections"), list) else []
    oauth_status_payload = authenticated.get("/stores/{store_id}/ebay-oauth/read-only-status", {})
    oauth_status = (
        oauth_status_payload.get("ebay_oauth_read_only_status")
        if isinstance(oauth_status_payload, dict)
        and isinstance(oauth_status_payload.get("ebay_oauth_read_only_status"), dict)
        else {}
    )
    expected_connection_id_sha256 = str(oauth_status.get("connection_id_sha256") or "")
    connection = next(
        (
            item
            for item in connections
            if isinstance(item, dict)
            and str(item.get("company_id") or "") == company_id
            and str(item.get("store_id") or "") == expected_store_id
            and str(item.get("platform") or "").strip().lower() == "ebay"
            and str(item.get("status") or "").strip().lower()
            in {"read_only_authorized", "publish_authorized", "read_write_authorized", "authorized", "connected"}
            and str(item.get("connection_id") or "")
            and expected_connection_id_sha256
            == hashlib.sha256(str(item.get("connection_id") or "").encode("utf-8")).hexdigest()
        ),
        {},
    )
    authorized_connection_ready = bool(connection)
    connection_metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    account_identity_ready = bool(
        authorized_connection_ready
        and str(connection.get("connection_type") or "").strip().lower() == "oauth"
        and str(connection.get("secret_ref") or "")
        and str(connection_metadata.get("credential_source") or "") == "jiejing_vault_secret_ref"
        and str(connection_metadata.get("account_deletion_identity_mapping_status") or "") == "identity_mapping_ready"
    )
    strong_oauth_boundary_ready = bool(
        store_identity_ready
        and authorized_connection_ready
        and account_identity_ready
        and oauth_status.get("authorized") is True
        and oauth_status.get("pending") is False
        and oauth_status.get("strong_identity_ready") is True
        and oauth_status.get("backend_provenance_ready") is True
        and expected_connection_id_sha256
        == hashlib.sha256(str(connection.get("connection_id") or "").encode("utf-8")).hexdigest()
    )

    packets_payload = authenticated.get("/data-packets?store_id={store_id}&platform=ebay&limit=1", {})
    packets = packets_payload.get("data_packets") if isinstance(packets_payload, dict) and isinstance(packets_payload.get("data_packets"), list) else []
    packet = next(
        (
            item
            for item in packets
            if isinstance(item, dict)
            and str(item.get("company_id") or "") == company_id
            and str(item.get("store_id") or "") == expected_store_id
            and str(item.get("platform") or "").strip().lower() == "ebay"
        ),
        {},
    )
    official_packet_ready = _official_store_packet_ready(packet)
    health_evidence = health.get("evidence_package") if isinstance(health.get("evidence_package"), dict) else {}
    packet_account_health_bound = bool(
        official_packet_ready
        and health_evidence.get("official_packet_present") is True
        and str(health_evidence.get("packet_id") or "")
        and str(health_evidence.get("packet_id") or "") == str(packet.get("packet_id") or "")
    )
    packet_fresh = _packet_is_fresh(packet)
    provenance = _backend_official_sync_provenance(
        authenticated=authenticated,
        company_id=company_id,
        store_id=expected_store_id,
        connection_id=str(connection.get("connection_id") or ""),
        packet_id=str(packet.get("packet_id") or ""),
        packet_created_at=str(packet.get("created_at") or ""),
    )
    return {
        "store_identity_ready": store_identity_ready,
        "account_health_ready": account_health_ready,
        "authorized_connection_ready": authorized_connection_ready,
        "account_identity_ready": account_identity_ready,
        "strong_oauth_boundary_ready": strong_oauth_boundary_ready,
        "official_packet_ready": official_packet_ready,
        "packet_fresh": packet_fresh,
        "packet_account_health_bound": packet_account_health_bound,
        "backend_queue_job_provenance_ready": provenance["queue_job_ready"],
        "backend_system_audit_provenance_ready": provenance["system_audit_ready"],
        "backend_official_sync_provenance_ready": provenance["ready"],
    }


def _official_store_packet_ready(packet_record: dict) -> bool:
    if not isinstance(packet_record, dict) or not packet_record:
        return False
    packet = packet_record.get("packet") if isinstance(packet_record.get("packet"), dict) else {}
    source_mode = str(packet_record.get("source_mode") or "").strip().lower()
    source_label = str(packet.get("source_label") or "").strip().lower()
    lineage = packet.get("lineage") if isinstance(packet.get("lineage"), dict) else {}
    freshness = packet.get("freshness") if isinstance(packet.get("freshness"), dict) else {}
    required = {
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    }
    present = set(packet.get("present_resource_keys") or [])
    return bool(
        source_mode == "official_api"
        and source_label == "official_api"
        and bool(packet_record.get("packet_id"))
        and str(packet.get("company_id") or "") == str(packet_record.get("company_id") or "")
        and str(packet.get("store_id") or "") == str(packet_record.get("store_id") or "")
        and str(packet.get("platform") or "").strip().lower() == "ebay"
        and str(packet.get("source_mode") or "").strip().lower() == source_mode
        and required.issubset(present)
        and lineage.get("probe_live_read_performed") is True
        and lineage.get("access_token_used") is True
        and lineage.get("access_token_returned_to_frontend") is False
        and lineage.get("raw_ebay_response_stored") is False
        and _safe_positive_int(freshness.get("official_request_count")) > 0
        and _safe_positive_int(freshness.get("route_success_count")) >= 5
        and _is_zero_nonnegative_int(freshness.get("route_failure_count"))
    )


def _packet_is_fresh(packet_record: dict) -> bool:
    packet = packet_record.get("packet") if isinstance(packet_record.get("packet"), dict) else {}
    freshness = packet.get("freshness") if isinstance(packet.get("freshness"), dict) else {}
    snapshot_at = _parse_utc_timestamp(freshness.get("snapshot_created_at"))
    record_at = _parse_utc_timestamp(packet_record.get("created_at"))
    if snapshot_at is None or record_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - snapshot_at).total_seconds()
    return bool(
        -300 <= age_seconds <= MAX_OFFICIAL_PACKET_AGE_SECONDS
        and abs((record_at - snapshot_at).total_seconds()) <= 300
    )


def _backend_official_sync_provenance(
    *,
    authenticated: dict,
    company_id: str,
    store_id: str,
    connection_id: str,
    packet_id: str,
    packet_created_at: str,
) -> dict[str, bool]:
    packet_time = _parse_utc_timestamp(packet_created_at)
    if not all((company_id, store_id, connection_id, packet_id)) or packet_time is None:
        return {"queue_job_ready": False, "system_audit_ready": False, "ready": False}
    jobs_payload = authenticated.get("/queue-jobs?status=completed&limit=200", {})
    jobs = jobs_payload.get("queue_jobs") if isinstance(jobs_payload, dict) and isinstance(jobs_payload.get("queue_jobs"), list) else []
    matched_job: dict = {}
    matched_update: dict = {}
    for candidate in jobs:
        if not isinstance(candidate, dict) or str(candidate.get("company_id") or "") != company_id:
            continue
        job_body = candidate.get("job") if isinstance(candidate.get("job"), dict) else {}
        live_plan = job_body.get("live_read_plan") if isinstance(job_body.get("live_read_plan"), dict) else {}
        token_boundary = live_plan.get("token_boundary") if isinstance(live_plan.get("token_boundary"), dict) else {}
        updates = job_body.get("updates") if isinstance(job_body.get("updates"), list) else []
        update = next(
            (
                item
                for item in reversed(updates)
                if isinstance(item, dict)
                and item.get("live_read_performed") is True
                and str(item.get("data_packet_id") or "") == packet_id
            ),
            {},
        )
        if (
            bool(str(candidate.get("job_id") or ""))
            and str(candidate.get("status") or "") == "completed"
            and str(job_body.get("kind") or "") == "ebay_read_only_live_plan"
            and str(job_body.get("store_id") or "") == store_id
            and str(token_boundary.get("connection_id") or "") == connection_id
            and _safe_positive_int(update.get("request_count")) > 0
            and _timestamps_within_seconds(_parse_utc_timestamp(update.get("created_at")), packet_time, 300)
            and _timestamps_within_seconds(_parse_utc_timestamp(candidate.get("updated_at")), packet_time, 300)
            and update
        ):
            matched_job = candidate
            matched_update = update
            break
    queue_job_ready = bool(matched_job and matched_update)

    audits_payload = authenticated.get("/audit-logs?limit=200", {})
    audits = audits_payload.get("audit_logs") if isinstance(audits_payload, dict) and isinstance(audits_payload.get("audit_logs"), list) else []
    matched_audit = next(
        (
            audit
            for audit in audits
            if isinstance(audit, dict)
            and str(audit.get("company_id") or "") == company_id
            and str(audit.get("store_id") or "") == store_id
            and str(audit.get("actor_type") or "") == "system"
            and str(audit.get("action_type") or "") == "ebay.read_only.live.completed"
            and str(audit.get("target_type") or "") == "queue_job"
            and bool(str(audit.get("target_id") or ""))
            and str(audit.get("target_id") or "") == str(matched_job.get("job_id") or "")
            and isinstance(audit.get("details"), dict)
            and str(audit["details"].get("data_packet_id") or "") == packet_id
            and _safe_positive_int(audit["details"].get("request_count")) > 0
            and audit["details"].get("raw_response_stored") is False
            and _timestamps_within_seconds(_parse_utc_timestamp(audit.get("created_at")), packet_time, 300)
        ),
        {},
    )
    system_audit_ready = bool(queue_job_ready and matched_audit)
    return {
        "queue_job_ready": queue_job_ready,
        "system_audit_ready": system_audit_ready,
        "ready": bool(queue_job_ready and system_audit_ready),
    }


def _parse_utc_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_positive_int(value: object) -> int:
    return value if type(value) is int and value > 0 else 0


def _safe_nonnegative_int(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _is_nonnegative_int(value: object) -> bool:
    return bool(type(value) is int and value >= 0)


def _is_zero_nonnegative_int(value: object) -> bool:
    return bool(type(value) is int and value == 0)


def _allowed_classification(value: object, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else "unknown"


def _timestamps_within_seconds(left: datetime | None, right: datetime | None, maximum: int) -> bool:
    return bool(left is not None and right is not None and abs((left - right).total_seconds()) <= maximum)


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


def _env_bool(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_all(names: list[str]) -> bool:
    return all(_env_bool(name) for name in names)


def _flag_diagnostics(names: list[str]) -> list[dict[str, object]]:
    return [{"name": name, "present": _env_bool(name), "secret_exposed": False} for name in names]


if __name__ == "__main__":
    raise SystemExit(main())
