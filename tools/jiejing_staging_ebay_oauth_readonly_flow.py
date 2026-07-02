#!/usr/bin/env python3
"""Operator tool for the first real staging eBay OAuth/read-only loop.

The tool calls Jiejing SaaS backend APIs. It never prints bearer tokens,
authorization codes, access tokens, refresh tokens, client secrets, Vault
tokens, or raw Authorization headers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_RESOURCES = [
    "store_profile",
    "account_business_policies",
    "inventory_and_offers",
    "orders_and_fulfillment",
    "finances",
    "taxonomy_listing_metadata",
]
DEFAULT_OUTPUT_ROOT = ROOT / "output" / "jiejing-saas-backend" / "staging-ebay-oauth-readonly"
REQUIRED_ENV = [
    "JIEJING_SAAS_ENV",
    "JIEJING_CORS_ORIGIN",
    "JIEJING_EBAY_CLIENT_ID",
    "JIEJING_EBAY_RU_NAME",
    "JIEJING_EBAY_CLIENT_SECRET",
    "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE",
    "JIEJING_EBAY_TOKEN_REFRESH_LIVE",
    "JIEJING_EBAY_READ_ONLY_LIVE",
    "JIEJING_VAULT_ENABLED",
    "JIEJING_VAULT_PROVIDER",
    "JIEJING_VAULT_LIVE_RESOLVE_ENABLED",
    "JIEJING_VAULT_ADDR",
    "JIEJING_VAULT_TOKEN",
    "JIEJING_VAULT_MOUNT",
    "JIEJING_VAULT_KEYSPACE",
    "JIEJING_VAULT_KV_VERSION",
    "JIEJING_ENABLE_HERMES_EBAY_BRIDGE",
    "JIEJING_EBAY_ACCESS_TOKEN",
    "JIEJING_EBAY_REFRESH_TOKEN",
]
SECRET_ENV_MARKERS = ("SECRET", "TOKEN", "PASSWORD", "KEY", "URL", "ADDR")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the staging eBay OAuth/read-only validation workflow.")
    parser.add_argument("--base-url", default=os.environ.get("JIEJING_STAGING_BASE_URL", "http://127.0.0.1:8788"))
    parser.add_argument("--email", default=os.environ.get("JIEJING_STAGING_OPERATOR_EMAIL", "staging-oauth@jiejing.local"))
    parser.add_argument("--password", default=os.environ.get("JIEJING_STAGING_OPERATOR_PASSWORD", "jiejing-staging-oauth-password"))
    parser.add_argument("--company-name", default=os.environ.get("JIEJING_STAGING_COMPANY_NAME", "Jiejing Staging OAuth Validation"))
    parser.add_argument("--store-name", default=os.environ.get("JIEJING_STAGING_EBAY_STORE_NAME", "northvalesource staging"))
    parser.add_argument("--marketplace", default=os.environ.get("JIEJING_STAGING_EBAY_MARKETPLACE", "EBAY_US"))
    parser.add_argument("--context", default=str(DEFAULT_OUTPUT_ROOT / "staging_oauth_context.json"))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--env-file", default="", help="Load a KEY=VALUE env file before checking or calling staging.")
    parser.add_argument("--register-if-needed", action="store_true", help="Register the operator account if login fails.")
    parser.add_argument("--resources", default=",".join(DEFAULT_RESOURCES))

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-env", help="Check local staging environment shape without printing secret values.")
    subparsers.add_parser("doctor", help="Check the running staging backend guardrails before seller OAuth.")
    subparsers.add_parser("prepare", help="Create or reuse a store and generate an eBay read-only authorization URL.")
    subparsers.add_parser("status", help="Inspect OAuth callback result, secret_ref/connection state, and preflight.")
    sync = subparsers.add_parser("sync", help="Run eBay read-only sync after OAuth callback has completed.")
    sync.add_argument("--run-mode", default="local_worker_now", choices=["queued", "local_worker_now", "inline", "enqueue_and_wait"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file:
        _load_env_file(Path(args.env_file))
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    context_path = Path(args.context).resolve()
    resources = _resources(args.resources)

    if args.command == "check-env":
        result = _check_env()
        _write_json(output_root / "staging_env_check_latest.json", result)
        _print_env_check(result)
        return 0 if result["ready_for_staging_oauth"] else 2

    if args.command == "doctor":
        result = _doctor(args)
        _write_json(output_root / "staging_backend_doctor_latest.json", result)
        _print_doctor(result)
        return 0 if result["ready_for_oauth_prepare"] else 2

    if args.command == "prepare":
        token = _login_or_register(args)
        store = _get_or_create_store(args, token=token)
        existing = _status(args=args, token=token, context={"store_id": store.get("store_id")}, resources=resources)
        if existing.get("callback_completed") and existing.get("preflight", {}).get("can_queue_sync"):
            result = {
                "status": "authorization_already_completed_ready_for_sync",
                "base_url": args.base_url.rstrip("/"),
                "callback_url_expected": f"{args.base_url.rstrip('/')}/oauth/ebay/callback",
                "store_id": store.get("store_id"),
                "store_name": store.get("store_name"),
                "oauth_request_id": existing.get("oauth_request_id"),
                "state_nonce": existing.get("state_nonce"),
                "authorization_url": None,
                "reused_completed_oauth": True,
                "oauth_latest_status": existing.get("oauth_latest_status"),
                "preflight": existing.get("preflight"),
                "next_operator_action": "Existing seller OAuth is complete. Run sync; do not open a new eBay authorization URL.",
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            _write_json(output_root / "staging_oauth_prepare_latest.json", result)
            _write_json(context_path, _context_from_status(args=args, store=store, status=existing))
            _print_prepare(result)
            return 0
        plan_payload = _post_json(
            f"{args.base_url.rstrip('/')}/stores/{store['store_id']}/ebay-oauth/read-only-plan",
            {"marketplace_id": args.marketplace},
            token=token,
        )
        plan = plan_payload.get("oauth_plan") if isinstance(plan_payload.get("oauth_plan"), dict) else {}
        request_record = plan_payload.get("oauth_request") if isinstance(plan_payload.get("oauth_request"), dict) else {}
        result = {
            "status": "authorization_url_ready" if plan.get("authorization_url") else "blocked_before_authorization_url",
            "base_url": args.base_url.rstrip("/"),
            "callback_url_expected": f"{args.base_url.rstrip('/')}/oauth/ebay/callback",
            "store_id": store.get("store_id"),
            "store_name": store.get("store_name"),
            "oauth_request_id": request_record.get("oauth_request_id"),
            "state_nonce": request_record.get("state_nonce"),
            "authorization_url": plan.get("authorization_url"),
            "missing_config": plan.get("missing_config") or [],
            "vault_status": _public_vault_status(plan_payload.get("vault")),
            "next_operator_action": (
                "Open authorization_url in the seller browser, complete eBay consent, then return here and run the status command."
                if plan.get("authorization_url")
                else "Fix missing_config and Vault/OAuth settings, then rerun prepare."
            ),
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
        }
        _write_json(output_root / "staging_oauth_prepare_latest.json", result)
        _write_json(context_path, _context_from_prepare(args=args, store=store, request_record=request_record))
        _print_prepare(result)
        return 0 if result["status"] == "authorization_url_ready" else 2

    if args.command == "status":
        context = _load_context(context_path)
        token = _login_or_register(args)
        result = _status(args=args, token=token, context=context, resources=resources)
        _write_json(output_root / "staging_oauth_status_latest.json", result)
        _print_status(result)
        return 0 if result.get("callback_completed") else 2

    if args.command == "sync":
        context = _load_context(context_path)
        token = _login_or_register(args)
        result = _sync(args=args, token=token, context=context, resources=resources, run_mode=args.run_mode)
        _write_json(output_root / "staging_readonly_sync_latest.json", result)
        _print_sync(result)
        return 0 if result.get("sync_completed") and result.get("data_packet_id") else 2

    return 2


def _check_env() -> dict[str, Any]:
    items = []
    for key in REQUIRED_ENV:
        value = os.environ.get(key)
        configured = bool(value)
        expected = _expected_env_value(key)
        ok = _env_item_ok(key, value, expected)
        items.append(
            {
                "key": key,
                "configured": configured,
                "value": _safe_env_value(key, value),
                "expected": expected,
                "ok": ok,
            }
        )
    provider = os.environ.get("JIEJING_VAULT_PROVIDER", "")
    provider_warning = ""
    if provider in {"tencent_kms", "aliyun_kms"}:
        provider_warning = "Tencent/Aliyun KMS are adapter contracts in this repo; use provider=vault for the first real staging OAuth run unless the managed client has been implemented."
    ready = all(item["ok"] for item in items) and not provider_warning
    return {
        "status": "ready" if ready else "blocked",
        "ready_for_staging_oauth": ready,
        "items": items,
        "provider_warning": provider_warning,
        "callback_path": "/oauth/ebay/callback",
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _doctor(args: argparse.Namespace) -> dict[str, Any]:
    base = args.base_url.rstrip("/")
    health = _fetch_json(f"{base}/health")
    readiness = _fetch_json(f"{base}/readiness").get("readiness", {})
    token = _login_or_register(args)
    vault = _fetch_platform_internal_status(
        url=f"{base}/vault/status",
        token=token,
        payload_key="vault",
        blocked_by="vault_status_requires_platform_internal_admin",
        fallback={
            "status": "blocked_by_access_boundary",
            "provider": None,
            "enabled": False,
            "can_store_raw_secret": False,
            "can_resolve_task_secret": False,
        },
    )
    resolver = _fetch_platform_internal_status(
        url=f"{base}/vault/secret-resolver/status",
        token=token,
        payload_key="vault_secret_resolver",
        blocked_by="vault_secret_resolver_requires_platform_internal_admin",
        fallback={
            "status": "blocked_by_access_boundary",
            "provider": None,
            "managed_client_implemented": False,
            "live_secret_resolution_available": False,
        },
    )
    http_client = _fetch_json(f"{base}/ebay-read-only/http-client/status", token=token).get("ebay_http_client", {})
    live_adapter = _fetch_json(f"{base}/ebay-read-only/live-adapter/status", token=token).get("ebay_live_read_adapter", {})
    write_adapter = _fetch_json(f"{base}/ebay-write/adapter/status", token=token).get("ebay_write_adapter", {})
    blockers = _doctor_blockers(
        health=health,
        readiness=readiness,
        vault=vault,
        resolver=resolver,
        http_client=http_client,
        live_adapter=live_adapter,
        write_adapter=write_adapter,
    )
    return {
        "status": "ready_for_oauth_prepare" if not blockers else "blocked",
        "ready_for_oauth_prepare": not blockers,
        "base_url": base,
        "callback_url_expected": f"{base}/oauth/ebay/callback",
        "health": {
            "status": health.get("status"),
            "environment": health.get("environment"),
            "real_platform_writes_enabled": bool(health.get("real_platform_writes_enabled")),
            "secret_exposed": False,
        },
        "readiness": {
            "production_ready": bool(readiness.get("production_ready")),
            "beta_ready": bool(readiness.get("beta_ready")),
            "blocker_count": readiness.get("blocker_count"),
            "warning_count": readiness.get("warning_count"),
            "secret_exposed": False,
        },
        "vault": {
            "provider": vault.get("provider"),
            "enabled": bool(vault.get("enabled")),
            "can_store_raw_secret": bool(vault.get("can_store_raw_secret")),
            "can_resolve_task_secret": bool(vault.get("can_resolve_task_secret")),
            "secret_exposed": False,
        },
        "vault_secret_resolver": {
            "provider": resolver.get("provider"),
            "status": resolver.get("status"),
            "managed_client_implemented": bool(resolver.get("managed_client_implemented")),
            "managed_live_resolution_ready": bool(resolver.get("managed_live_resolution_ready")),
            "live_secret_resolution_available": bool(resolver.get("live_secret_resolution_available")),
            "blocked_by": resolver.get("blocked_by") or [],
            "secret_exposed": False,
        },
        "ebay_http_client": {
            "status": http_client.get("status"),
            "blocked_by": http_client.get("blocked_by") or [],
            "secret_exposed": False,
        },
        "ebay_live_read_adapter": {
            "status": live_adapter.get("status"),
            "enabled": bool(live_adapter.get("enabled")),
            "blocked_by": live_adapter.get("blocked_by") or [],
            "secret_exposed": False,
        },
        "ebay_write_adapter": {
            "writes_supported": bool(write_adapter.get("writes_supported")),
            "real_platform_writes_enabled": bool(write_adapter.get("real_platform_writes_enabled")),
            "secret_exposed": False,
        },
        "blocked_by": blockers,
        "next_operator_action": "Run prepare." if not blockers else "Fix blocked_by, then rerun doctor before seller OAuth.",
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _doctor_blockers(
    *,
    health: dict[str, Any],
    readiness: dict[str, Any],
    vault: dict[str, Any],
    resolver: dict[str, Any],
    http_client: dict[str, Any],
    live_adapter: dict[str, Any],
    write_adapter: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if health.get("status") != "ok":
        blockers.append("backend_health_not_ok")
    if health.get("environment") != "staging":
        blockers.append("JIEJING_SAAS_ENV_should_be_staging")
    if health.get("real_platform_writes_enabled"):
        blockers.append("real_platform_writes_must_remain_disabled")
    for item in vault.get("blocked_by") or []:
        if item not in blockers:
            blockers.append(str(item))
    if not vault.get("enabled") or vault.get("provider") == "secret_ref_only":
        blockers.append("managed_vault_not_enabled")
    if not vault.get("can_store_raw_secret") or not vault.get("can_resolve_task_secret"):
        blockers.append("vault_cannot_store_or_resolve_secret")
    if not resolver.get("live_secret_resolution_available"):
        blockers.append("vault_secret_resolver_not_live")
    for item in resolver.get("blocked_by") or []:
        if item not in blockers:
            blockers.append(str(item))
    if http_client.get("status") != "live_ready":
        blockers.append("ebay_http_client_not_live_ready")
    for item in http_client.get("blocked_by") or []:
        if item not in blockers:
            blockers.append(str(item))
    if live_adapter.get("status") != "live_ready" or not live_adapter.get("enabled"):
        blockers.append("ebay_live_read_adapter_not_live_ready")
    for item in live_adapter.get("blocked_by") or []:
        if item not in blockers:
            blockers.append(str(item))
    if write_adapter.get("real_platform_writes_enabled") or write_adapter.get("writes_supported"):
        blockers.append("write_adapter_must_remain_disabled")
    if readiness.get("secret_exposed") is True:
        blockers.append("readiness_secret_exposed")
    return blockers


def _login_or_register(args: argparse.Namespace) -> str:
    base = args.base_url.rstrip("/")
    try:
        login = _post_json(f"{base}/auth/login", {"email": args.email, "password": args.password})
    except RuntimeError:
        if not args.register_if_needed:
            raise
        login = _post_json(
            f"{base}/auth/register",
            {"email": args.email, "password": args.password, "company_name": args.company_name},
        )
    token = str(login.get("token") or "")
    if not token:
        raise RuntimeError("Jiejing SaaS auth did not return a session token.")
    return token


def _get_or_create_store(args: argparse.Namespace, *, token: str) -> dict[str, Any]:
    base = args.base_url.rstrip("/")
    stores = _fetch_json(f"{base}/stores", token=token).get("stores", [])
    for store in stores if isinstance(stores, list) else []:
        if not isinstance(store, dict):
            continue
        if str(store.get("platform") or "").lower() == "ebay" and str(store.get("store_name") or "") == args.store_name:
            return store
    payload = _post_json(
        f"{base}/stores",
        {"platform": "ebay", "store_name": args.store_name, "marketplace": args.marketplace, "stage": "oauth_staging_validation"},
        token=token,
    )
    store = payload.get("store") if isinstance(payload.get("store"), dict) else {}
    if not store.get("store_id"):
        raise RuntimeError("Store creation did not return a store_id.")
    return store


def _status(*, args: argparse.Namespace, token: str, context: dict[str, Any], resources: list[str]) -> dict[str, Any]:
    base = args.base_url.rstrip("/")
    store_id = _context_store_id(context)
    oauth_requests = _fetch_json(f"{base}/oauth/requests?store_id={urllib.parse.quote(store_id)}", token=token).get("oauth_requests", [])
    secret_refs = _fetch_json(f"{base}/secret-refs?store_id={urllib.parse.quote(store_id)}", token=token).get("secret_refs", [])
    connections = _fetch_json(f"{base}/connections?store_id={urllib.parse.quote(store_id)}", token=token).get("connections", [])
    preflight = _post_json(
        f"{base}/stores/{store_id}/ebay-read-only/credential-preflight",
        {"resources": resources},
        token=token,
    ).get("credential_preflight", {})
    latest_request = oauth_requests[0] if isinstance(oauth_requests, list) and oauth_requests else {}
    callback_completed = str(latest_request.get("status") or "") == "callback_exchange_completed"
    return {
        "status": "callback_completed_ready_for_sync" if callback_completed and preflight.get("can_queue_sync") else "waiting_or_blocked",
        "store_id": store_id,
        "oauth_request_id": latest_request.get("oauth_request_id"),
        "state_nonce": latest_request.get("state_nonce"),
        "oauth_latest_status": latest_request.get("status"),
        "oauth_request_count": len(oauth_requests) if isinstance(oauth_requests, list) else 0,
        "secret_ref_count": len(secret_refs) if isinstance(secret_refs, list) else 0,
        "connection_count": len(connections) if isinstance(connections, list) else 0,
        "callback_completed": callback_completed,
        "preflight": {
            "status": preflight.get("status"),
            "can_queue_sync": bool(preflight.get("can_queue_sync")),
            "token_mode": preflight.get("token_mode"),
            "blocked_by": preflight.get("blocked_by") or [],
            "secret_exposed": False,
        },
        "next_operator_action": "Run sync." if callback_completed and preflight.get("can_queue_sync") else preflight.get("merchant_next_step"),
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _sync(*, args: argparse.Namespace, token: str, context: dict[str, Any], resources: list[str], run_mode: str) -> dict[str, Any]:
    base = args.base_url.rstrip("/")
    store_id = _context_store_id(context)
    sync = _post_json(
        f"{base}/stores/{store_id}/ebay-read-only/sync",
        {"resources": resources, "run_mode": run_mode, "product": "Jiejing staging official eBay read-only validation"},
        token=token,
        timeout=300,
    )
    worker = sync.get("worker_result") if isinstance(sync.get("worker_result"), dict) else {}
    live = worker.get("live_read_result") if isinstance(worker.get("live_read_result"), dict) else {}
    packet = worker.get("data_packet") if isinstance(worker.get("data_packet"), dict) else {}
    packet_body = packet.get("packet") if isinstance(packet.get("packet"), dict) else {}
    packets = _fetch_json(f"{base}/data-packets?store_id={urllib.parse.quote(store_id)}&platform=ebay", token=token).get("data_packets", [])
    return {
        "status": "completed" if live.get("live_read_performed") and packet.get("packet_id") else "blocked_or_incomplete",
        "store_id": store_id,
        "sync_status": sync.get("sync", {}).get("status") if isinstance(sync.get("sync"), dict) else None,
        "worker_status": worker.get("status"),
        "live_read_status": live.get("status"),
        "live_request_performed": bool(live.get("live_read_performed")),
        "request_count": live.get("request_count"),
        "route_results": _route_results(live.get("route_results") if isinstance(live.get("route_results"), list) else []),
        "sync_completed": bool(live.get("live_read_performed") and packet.get("packet_id")),
        "data_packet_id": packet.get("packet_id"),
        "data_packet_status": packet_body.get("status"),
        "source_mode": packet.get("source_mode") or packet_body.get("source_mode"),
        "present_resource_keys": packet_body.get("present_resource_keys") or [],
        "missing_resource_keys": packet_body.get("missing_resource_keys") or [],
        "stored_packet_count": len(packets) if isinstance(packets, list) else 0,
        "real_platform_writes_enabled": False,
        "secret_exposed": False,
    }


def _route_results(routes: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        compact.append(
            {
                "resource_key": route.get("resource_key"),
                "successful_path_count": route.get("successful_path_count"),
                "data_present": bool(route.get("data_present")),
                "paths": [
                    {
                        "path": path.get("path") or path.get("path_template"),
                        "status": path.get("status"),
                        "http_status": path.get("http_status"),
                        "error_type": path.get("error_type"),
                        "missing_context": path.get("missing_context") or [],
                    }
                    for path in (route.get("paths") or [])
                    if isinstance(path, dict)
                ],
            }
        )
    return compact


def _resources(raw: str) -> list[str]:
    values = [item.strip() for item in str(raw).split(",") if item.strip()]
    return values or list(DEFAULT_RESOURCES)


def _context_from_prepare(*, args: argparse.Namespace, store: dict[str, Any], request_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_url": args.base_url.rstrip("/"),
        "operator_email": args.email,
        "store_id": store.get("store_id"),
        "store_name": store.get("store_name"),
        "marketplace": store.get("marketplace") or args.marketplace,
        "oauth_request_id": request_record.get("oauth_request_id"),
        "state_nonce": request_record.get("state_nonce"),
        "created_at": request_record.get("created_at"),
        "secret_exposed": False,
    }


def _context_from_status(*, args: argparse.Namespace, store: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_url": args.base_url.rstrip("/"),
        "operator_email": args.email,
        "store_id": store.get("store_id"),
        "store_name": store.get("store_name"),
        "marketplace": store.get("marketplace") or args.marketplace,
        "oauth_request_id": status.get("oauth_request_id"),
        "state_nonce": status.get("state_nonce"),
        "reused_completed_oauth": True,
        "secret_exposed": False,
    }


def _load_context(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing context file. Run prepare first: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _context_store_id(context: dict[str, Any]) -> str:
    store_id = str(context.get("store_id") or "")
    if not store_id:
        raise RuntimeError("Context file does not contain store_id. Run prepare again.")
    return store_id


def _expected_env_value(key: str) -> str | None:
    expected = {
        "JIEJING_SAAS_ENV": "staging",
        "JIEJING_EBAY_OAUTH_EXCHANGE_LIVE": "true",
        "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
        "JIEJING_EBAY_READ_ONLY_LIVE": "true",
        "JIEJING_VAULT_ENABLED": "true",
        "JIEJING_VAULT_PROVIDER": "vault",
        "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
        "JIEJING_ENABLE_HERMES_EBAY_BRIDGE": "false",
        "JIEJING_EBAY_ACCESS_TOKEN": "missing",
        "JIEJING_EBAY_REFRESH_TOKEN": "missing",
    }
    return expected.get(key)


def _safe_env_value(key: str, value: str | None) -> str:
    if not value:
        return "missing"
    if _is_placeholder_value(value):
        return "placeholder"
    if value.strip().lower() in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        return value.strip().lower()
    if any(marker in key for marker in SECRET_ENV_MARKERS):
        return "configured_redacted"
    return value


def _env_item_ok(key: str, value: str | None, expected: str | None) -> bool:
    if expected == "missing":
        return not value
    if not value:
        return False
    if _is_placeholder_value(value):
        return False
    if expected is None:
        return True
    return str(value).strip().lower() == expected


def _is_placeholder_value(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith("replace-with")
        or normalized.startswith("inject-from")
        or normalized in {"changeme", "todo", "example", "https://staging.jiejing.example", "https://vault.staging.example"}
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def _public_vault_status(value: Any) -> dict[str, Any]:
    vault = value if isinstance(value, dict) else {}
    return {
        "status": vault.get("status"),
        "provider": vault.get("provider"),
        "can_store_raw_secret": bool(vault.get("can_store_raw_secret")),
        "secret_exposed": False,
    }


def _fetch_platform_internal_status(
    *,
    url: str,
    token: str,
    payload_key: str,
    blocked_by: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    status_code, payload = _fetch_json_with_status(url, token=token)
    if status_code == 200:
        value = payload.get(payload_key)
        result = value if isinstance(value, dict) else {}
        result["secret_exposed"] = False
        return result
    if status_code == 403:
        result = dict(fallback)
        result["blocked_by"] = [blocked_by]
        result["secret_exposed"] = False
        return result
    error = payload.get("error") or payload.get("message") or "request_failed"
    raise RuntimeError(f"GET {url} failed with HTTP {status_code}: {str(error)[:200]}")


def _fetch_json_with_status(url: str, token: str | None = None, timeout: int = 60) -> tuple[int, dict[str, Any]]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"error": body}
        return exc.code, payload if isinstance(payload, dict) else {"error": body}


def _fetch_json(url: str, token: str | None = None, timeout: int = 60) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {body}") from exc


def _post_json(url: str, payload: dict[str, Any], token: str | None = None, timeout: int = 120) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"POST {url} failed with HTTP {exc.code}: {body}") from exc


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _print_env_check(result: dict[str, Any]) -> None:
    print(f"STAGING_ENV_STATUS={result.get('status')}")
    if result.get("provider_warning"):
        print(f"PROVIDER_WARNING={result.get('provider_warning')}")
    for item in result.get("items") or []:
        if isinstance(item, dict):
            print(f"{item.get('key')}={item.get('value')} ok={item.get('ok')}")


def _print_doctor(result: dict[str, Any]) -> None:
    print(f"DOCTOR_STATUS={result.get('status')}")
    print(f"BASE_URL={result.get('base_url')}")
    print(f"CALLBACK_URL_EXPECTED={result.get('callback_url_expected')}")
    health = result.get("health") if isinstance(result.get("health"), dict) else {}
    print(f"ENVIRONMENT={health.get('environment')}")
    print(f"HEALTH_STATUS={health.get('status')}")
    vault = result.get("vault") if isinstance(result.get("vault"), dict) else {}
    print(f"VAULT_PROVIDER={vault.get('provider')}")
    print(f"VAULT_CAN_RESOLVE_TASK_SECRET={vault.get('can_resolve_task_secret')}")
    resolver = result.get("vault_secret_resolver") if isinstance(result.get("vault_secret_resolver"), dict) else {}
    print(f"VAULT_RESOLVER_STATUS={resolver.get('status')}")
    print(f"VAULT_RESOLVER_LIVE={resolver.get('live_secret_resolution_available')}")
    http_client = result.get("ebay_http_client") if isinstance(result.get("ebay_http_client"), dict) else {}
    print(f"EBAY_HTTP_CLIENT_STATUS={http_client.get('status')}")
    live_adapter = result.get("ebay_live_read_adapter") if isinstance(result.get("ebay_live_read_adapter"), dict) else {}
    print(f"EBAY_LIVE_ADAPTER_STATUS={live_adapter.get('status')}")
    print(f"EBAY_LIVE_ADAPTER_ENABLED={live_adapter.get('enabled')}")
    print(f"REAL_PLATFORM_WRITES_ENABLED={result.get('real_platform_writes_enabled')}")
    print(f"BLOCKERS={','.join(result.get('blocked_by') or []) or '-'}")
    print(f"NEXT={result.get('next_operator_action')}")


def _print_prepare(result: dict[str, Any]) -> None:
    print(f"PREPARE_STATUS={result.get('status')}")
    print(f"STORE_ID={result.get('store_id')}")
    print(f"OAUTH_REQUEST_ID={result.get('oauth_request_id')}")
    print(f"CALLBACK_URL_EXPECTED={result.get('callback_url_expected')}")
    if result.get("authorization_url"):
        print(f"AUTHORIZATION_URL={result.get('authorization_url')}")
    else:
        print(f"MISSING_CONFIG={','.join(result.get('missing_config') or []) or '-'}")
    print(f"NEXT={result.get('next_operator_action')}")


def _print_status(result: dict[str, Any]) -> None:
    print(f"STATUS={result.get('status')}")
    print(f"OAUTH_LATEST_STATUS={result.get('oauth_latest_status')}")
    print(f"SECRET_REF_COUNT={result.get('secret_ref_count')}")
    print(f"CONNECTION_COUNT={result.get('connection_count')}")
    preflight = result.get("preflight") if isinstance(result.get("preflight"), dict) else {}
    print(f"PREFLIGHT_STATUS={preflight.get('status')}")
    print(f"CAN_QUEUE_SYNC={preflight.get('can_queue_sync')}")
    print(f"TOKEN_MODE={preflight.get('token_mode')}")
    print(f"BLOCKERS={','.join(preflight.get('blocked_by') or []) or '-'}")
    print(f"NEXT={result.get('next_operator_action')}")


def _print_sync(result: dict[str, Any]) -> None:
    print(f"SYNC_STATUS={result.get('status')}")
    print(f"LIVE_READ_STATUS={result.get('live_read_status')}")
    print(f"LIVE_REQUEST_PERFORMED={result.get('live_request_performed')}")
    print(f"REQUEST_COUNT={result.get('request_count')}")
    print(f"DATA_PACKET_ID={result.get('data_packet_id')}")
    print(f"SOURCE_MODE={result.get('source_mode')}")
    print(f"PRESENT_RESOURCES={','.join(result.get('present_resource_keys') or []) or '-'}")
    print(f"MISSING_RESOURCES={','.join(result.get('missing_resource_keys') or []) or '-'}")
    print(f"REAL_PLATFORM_WRITES_ENABLED={result.get('real_platform_writes_enabled')}")
    print(f"SECRET_EXPOSED={result.get('secret_exposed')}")


if __name__ == "__main__":
    raise SystemExit(main())
