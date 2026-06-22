"""Sanitized eBay credential preflight for Jiejing SaaS.

This module answers one product question: can this backend run an official
eBay read-only sync now? It never returns token values, client secrets,
refresh tokens, cookies, or raw authorization headers.
"""

from __future__ import annotations

from typing import Any

from .config import SaaSSettings
from .ebay_http_client import build_ebay_http_client_contract
from .ebay_live_read_adapter import build_live_read_adapter_status
from .hermes_ebay_bridge import inspect_hermes_ebay_bridge
from .ebay_oauth_token_store import EbayLocalOAuthTokenStore
from .vault_secret_resolver import SecretTransport, VaultSecretResolver, build_vault_secret_resolver_status


def build_ebay_credential_preflight(
    *,
    settings: SaaSSettings,
    store: dict[str, Any] | None,
    secret_refs: list[dict[str, Any]] | None = None,
    connections: list[dict[str, Any]] | None = None,
    requested_resources: list[str] | None = None,
    secret_transport: SecretTransport | None = None,
) -> dict[str, Any]:
    secret_refs = secret_refs or []
    connections = connections or []
    resources = requested_resources or [
        "store_profile",
        "account_business_policies",
        "inventory_and_offers",
        "orders_and_fulfillment",
        "finances",
        "taxonomy_listing_metadata",
    ]
    refresh_ref = _find_ebay_refresh_ref(secret_refs)
    oauth_connection = _find_ebay_connection(connections)
    http_contract = build_ebay_http_client_contract(settings)
    live_adapter = build_live_read_adapter_status(settings)
    direct_token = settings.ebay_env_access_token_allowed
    hermes_bridge = inspect_hermes_ebay_bridge(settings)
    local_token_store = EbayLocalOAuthTokenStore(settings)
    local_token_secret_ref = refresh_ref.get("secret_ref") if isinstance(refresh_ref, dict) else None
    local_store_token = local_token_store.has_usable_token(str(local_token_secret_ref) if local_token_secret_ref else None)
    secret_resolver = VaultSecretResolver(settings, transport=secret_transport)
    secret_resolver_status = build_vault_secret_resolver_status(settings)
    secret_resolver_record = secret_resolver.public_record_status(secret_ref=refresh_ref)
    legacy_bridge_token = bool(hermes_bridge.get("can_resolve_access_token"))
    refresh_flow_configured = (
        settings.ebay_env_refresh_token_allowed
        and bool(settings.ebay_client_id)
        and settings.ebay_client_secret_configured
        and settings.ebay_token_refresh_live_enabled
    )
    secret_ref_refresh_ready = bool(
        refresh_ref
        and bool(settings.ebay_client_id)
        and settings.ebay_client_secret_configured
        and settings.ebay_token_refresh_live_enabled
        and secret_resolver.can_resolve_secret_values()
        and secret_resolver.has_resolvable_secret(secret_ref=refresh_ref, verify_secret_value=True)
    )
    backend_token_ready = direct_token or legacy_bridge_token or local_store_token
    backend_refresh_ready = refresh_flow_configured or bool(
        hermes_bridge.get("can_refresh_access_token") and settings.ebay_token_refresh_live_enabled
    ) or secret_ref_refresh_ready
    vault_refresh_ref_configured = bool(refresh_ref)
    production_vault_ready = not settings.is_production_like or (settings.vault_enabled and settings.vault_provider != "secret_ref_only")

    checks = [
        _check(
            "store_scope",
            "店铺工作区",
            bool(store and store.get("store_id")),
            "已经指定 eBay 店铺工作区。",
            "先创建或选择一个 eBay 店铺工作区。",
        ),
        _check(
            "live_read_switch",
            "只读同步开关",
            settings.ebay_read_only_live_enabled,
            "后端允许执行 eBay 官方只读请求。",
            "设置 JIEJING_EBAY_READ_ONLY_LIVE=true。",
        ),
        _check(
            "token_source",
            "后端 token 来源",
            backend_token_ready or backend_refresh_ready,
            "后端有短期 access token，或能用 refresh token 换取短期 token。",
            "本地验证可放短期 access token；正式版用 refresh token + client secret + KMS/Vault。",
            blockers=_unique(
                (["JIEJING_EBAY_ENV_ACCESS_TOKEN_DISABLED_IN_PRODUCTION"] if settings.ebay_env_access_token_blocked else [])
                + (["JIEJING_EBAY_ENV_REFRESH_TOKEN_DISABLED_IN_PRODUCTION"] if settings.ebay_env_refresh_token_blocked else [])
                + list(hermes_bridge.get("blocked_by") or [])
            ),
        ),
        _check(
            "oauth_connection",
            "店铺授权记录",
            bool(oauth_connection) or backend_token_ready or backend_refresh_ready,
            "店铺已有只读授权记录，或当前使用本地短期 token 验证。",
            "完成 eBay 官方只读 OAuth，或先用本地短期 token 做 smoke test。",
        ),
        _check(
            "refresh_secret_ref",
            "refresh token 引用",
            vault_refresh_ref_configured or backend_token_ready or settings.ebay_env_refresh_token_allowed or backend_refresh_ready,
            "已找到 refresh token 的 secret_ref，或本地环境提供了可用 token。",
            "把 eBay refresh token 放入 KMS/Vault，并在店铺连接里保存 secret_ref。",
        ),
        _check(
            "client_id",
            "eBay App ID",
            bool(settings.ebay_client_id) or backend_token_ready or bool(hermes_bridge.get("client_id_present")),
            "后端已配置 eBay App ID，或当前使用短期 access token 验证。",
            "配置 JIEJING_EBAY_CLIENT_ID。",
        ),
        _check(
            "client_secret",
            "eBay Client Secret",
            settings.ebay_client_secret_configured or backend_token_ready or bool(hermes_bridge.get("client_secret_present")),
            "后端已配置 eBay client secret，或当前使用短期 access token 验证。",
            "配置 JIEJING_EBAY_CLIENT_SECRET；正式版放 KMS/Vault。",
        ),
        _check(
            "vault_boundary",
            "生产密钥边界",
            production_vault_ready,
            "当前环境的密钥边界满足运行级别要求。",
            "生产/预发布必须启用 KMS/Vault，不能只用 secret_ref_only。",
        ),
        _check(
            "http_client",
            "eBay HTTP 只读客户端",
            http_contract.get("status") == "live_ready",
            "后端 HTTP 客户端具备执行官方只读 GET 的条件。",
            "补齐 HTTP client blockers 后再同步。",
            blockers=http_contract.get("blocked_by") or [],
        ),
        _check(
            "live_adapter",
            "只读路由与标准化",
            live_adapter.get("enabled") is True,
            "只读路由、标准化和 HTTP 客户端都已就绪。",
            "补齐 live adapter blockers 后再同步。",
            blockers=live_adapter.get("blocked_by") or [],
        ),
    ]
    blockers = _unique(
        item
        for check in checks
        if check["status"] != "ready"
        for item in ([check["key"]] + list(check.get("blockers") or []))
    )
    token_mode = (
        "backend_env_access_token"
        if direct_token
        else "backend_legacy_credential_bridge"
        if legacy_bridge_token or bool(hermes_bridge.get("can_refresh_access_token") and settings.ebay_token_refresh_live_enabled)
        else "backend_jiejing_local_oauth_store"
        if local_store_token
        else "backend_jiejing_secret_ref_resolver"
        if secret_ref_refresh_ready
        else "backend_refresh_token"
        if refresh_flow_configured
        else "not_ready"
    )
    ready = not blockers
    return {
        "preflight_version": "2026-05-15-ebay-credential-preflight",
        "platform": "ebay",
        "store_id": store.get("store_id") if store else None,
        "store_name": store.get("store_name") if store else None,
        "marketplace": (store or {}).get("marketplace") or "EBAY_US",
        "status": "ready_for_official_read" if ready else "blocked",
        "token_mode": token_mode,
        "backend_legacy_bridge": {
            "enabled": bool(hermes_bridge.get("bridge_enabled")),
            "status": hermes_bridge.get("status"),
            "can_resolve_access_token": bool(hermes_bridge.get("can_resolve_access_token")),
            "can_refresh_access_token": bool(hermes_bridge.get("can_refresh_access_token")),
            "credential_source": hermes_bridge.get("credential_source"),
            "policy_snapshot_present": bool(hermes_bridge.get("policy_snapshot_present")),
            "listing_rules_snapshot_present": bool(hermes_bridge.get("listing_rules_snapshot_present")),
            "secret_exposed": False,
        },
        "backend_local_oauth_store": {
            "enabled": bool(local_token_store.status().get("enabled")),
            "status": local_token_store.status().get("status"),
            "token_record": local_token_store.public_record_status(str(local_token_secret_ref) if local_token_secret_ref else None),
            "secret_exposed": False,
        },
        "backend_secret_ref_resolver": {
            "status": secret_resolver_status.get("status"),
            "local_development_enabled": bool(secret_resolver_status.get("local_development_enabled")),
            "live_secret_resolution_available": bool(secret_resolver_status.get("live_secret_resolution_available")),
            "secret_ref_verified": bool(secret_ref_refresh_ready),
            "token_record": secret_resolver_record,
            "secret_exposed": False,
        },
        "requested_resources": resources,
        "can_queue_sync": ready,
        "can_run_live_http": ready,
        "checks": checks,
        "blocked_by": blockers,
        "merchant_next_step": _merchant_next_step(blockers),
        "runtime_gets_access_token": False,
        "frontend_gets_access_token": False,
        "raw_secret_returned": False,
        "real_platform_writes_enabled": False,
        "writes_supported": False,
        "secret_exposed": False,
    }


def _check(
    key: str,
    label: str,
    passed: bool,
    ready_detail: str,
    blocked_detail: str,
    *,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": "ready" if passed else "blocked",
        "detail": ready_detail if passed else blocked_detail,
        "blockers": [] if passed else list(blockers or []),
    }


def _find_ebay_refresh_ref(secret_refs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in secret_refs:
        if str(item.get("provider") or "").lower() != "ebay":
            continue
        if str(item.get("purpose") or "").lower() == "ebay_refresh_token":
            return item
    return None


def _find_ebay_connection(connections: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in connections:
        if str(item.get("platform") or "").lower() != "ebay":
            continue
        if str(item.get("connection_type") or "").lower() != "oauth":
            continue
        if str(item.get("status") or "").lower() in {"read_only_authorized", "publish_authorized", "read_write_authorized", "authorized", "connected"}:
            return item
    return None


def _merchant_next_step(blockers: list[str]) -> str:
    blockers_set = set(blockers)
    if "store_scope" in blockers_set:
        return "先创建或选择一个 eBay 店铺工作区。"
    if "live_read_switch" in blockers_set or "JIEJING_EBAY_READ_ONLY_LIVE" in blockers_set:
        return "先在后端开启 eBay 只读同步开关。"
    if "token_source" in blockers_set or "JIEJING_EBAY_ACCESS_TOKEN_OR_REFRESH_TOKEN" in blockers_set:
        return "先提供后端可用的 eBay 只读 token：本地短期 access token，或正式 refresh token 流程。"
    if "vault_boundary" in blockers_set or "Vault/KMS" in blockers_set:
        return "预发布/生产环境先接 KMS/Vault，再读取真实店铺。"
    if "oauth_connection" in blockers_set:
        return "先完成 eBay 官方只读授权，或先做本地短期 token 验证。"
    if "client_id" in blockers_set:
        return "先配置 eBay App ID。"
    if "client_secret" in blockers_set:
        return "先配置 eBay client secret；正式版必须放 KMS/Vault。"
    return "补齐 eBay 只读授权、后端密钥和同步开关后再运行。"


def _unique(items: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
