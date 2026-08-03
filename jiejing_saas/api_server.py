"""Local HTTP server for the formal Jiejing SaaS backend MVP."""

from __future__ import annotations

import html
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from jiejing_runtime.execution import ExecutionRequest, ExecutionService
from jiejing_runtime.provider_job_contracts import build_provider_job_contract_catalog

from .account_health import build_account_health_snapshot, merge_account_health_into_payload
from .ai_ceo_chat import ai_ceo_route_metadata, run_ai_ceo_chat, run_ai_ceo_fast_turn
from .backup_plan import build_backup_plan
from .billing_plan import build_billing_plan, build_billing_usage, evaluate_quota_action
from .billing_checkout import build_billing_checkout_contract, create_stripe_checkout_session, create_stripe_customer_portal_session
from .billing_domestic import (
    build_domestic_billing_operations_snapshot,
    close_domestic_billing_order,
    create_domestic_billing_order,
    execute_approved_domestic_billing_refund,
    merchant_domestic_billing_order,
    open_domestic_billing_checkout,
    query_and_reconcile_domestic_billing_order,
    query_and_reconcile_domestic_billing_refund,
    reconcile_domestic_billing_orders,
    request_domestic_billing_refund_review,
)
from .billing_domain_cutover_rehearsal import build_billing_domain_cutover_rehearsal
from .billing_manual_beta import create_manual_beta_payment_order, confirm_manual_beta_payment_order, list_manual_beta_payment_orders
from .billing_payment_options import build_mainland_payment_strategy, validate_mainland_payment_launch_for_public
from .billing_provider_evidence_register import build_billing_provider_evidence_register
from .billing_provider_rehearsal import run_billing_provider_rehearsal
from .billing_test_provider import apply_test_billing_event
from .billing_webhook import handle_billing_webhook
from .billing_wechat_pay import (
    build_wechat_pay_native_contract,
    process_wechat_pay_notification_from_env,
    process_wechat_pay_refund_notification_from_env,
)
from .commercial_launch_gate import build_commercial_launch_gate
from .config import SaaSSettings
from .controlled_bridges import build_controlled_bridge_contract
from .database_adapter import build_database_adapter_contract
from .database_plan import build_database_plan
from .domain_readiness import build_domain_readiness
from .edge_cutover_preflight import build_edge_cutover_preflight
from .ebay_credential_preflight import build_ebay_credential_preflight
from .ebay_account_deletion import (
    AccountDeletionError,
    EbayNotificationSignatureVerifier,
    build_challenge_response,
    normalize_notification,
)
from .ebay_data_packet import build_ebay_read_only_data_packet
from .ebay_http_client import build_ebay_http_client_contract, build_http_dry_run_from_live_plan
from .ebay_live_read_adapter import EbayLiveReadPlanBuilder, build_live_read_adapter_status
from .ebay_oauth import EbayOAuthPlanner
from .ebay_oauth_callback import process_ebay_oauth_callback
from .ebay_oauth_token_store import build_local_oauth_token_store_status
from .ebay_read_contract import build_field_contract_catalog
from .ebay_read_normalizers import normalizer_catalog
from .ebay_read_adapter import EbayReadOnlyAdapter
from .ebay_token_refresh_adapter import EbayVaultTokenRefreshAdapter, public_token_refresh_result
from .ebay_write_adapter import EbayWriteHttpAdapter, build_ebay_write_adapter_contract, build_publish_readiness
from .independence import build_independence_status
from .infrastructure_drivers import build_infrastructure_driver_status
from .media_credits import build_media_credit_summary, estimate_media_points
from .merchant_onboarding import (
    AUTHORIZED_CONNECTION_STATUSES,
    MerchantOnboardingValidationError,
    MerchantOnboardingVersionConflict,
    build_merchant_onboarding_read_model,
)
from .ip_risk_screening import build_ip_logo_brand_screening
from .json_safe import json_default
from .model_value_gate import build_model_value_gate
from .model_value_rehearsal import run_model_value_rehearsal
from .model_provider_catalog import (
    MODEL_SECRET_PURPOSE,
    READY_MODEL_SECRET_STATUSES,
    build_model_client_from_byok_secret,
    build_model_provider_catalog,
    get_model_provider,
    model_secret_provider,
    normalize_model_api_base_url,
    public_model_settings_from_secret_refs,
)
from .monitoring import build_monitoring_status
from .operations_metering import MeteredModelClient, model_cost_measurement, sanitize_analytics_event
from .media_source_assets import MAX_MEDIA_SOURCE_BYTES, MediaSourceAssetError, MediaSourceAssetStore
from .operational_health import build_operational_health
from .owner_launch_control import build_owner_launch_control
from .platform_model_status import platform_default_serving_model
from .paid_launch_approval_packet import build_paid_launch_approval_packet
from .platform_registry import build_platform_connection_plan, get_platform_definition, registry_summary
from .platform_data_packet_handoff import build_runtime_handoff_from_platform_packet, merge_runtime_handoff_input
from .post_publish_cockpit import build_post_publish_cockpit
from .permissions import has_permission, role_summary
from .production_evidence_ledger import build_production_evidence_ledger
from .production_release_gate import build_production_release_gate
from .postgres_repository_runtime import postgres_unique_error_classes
from .public_search_handoff import build_public_search_market_handoff, merge_public_search_handoff_input
from .queue_plan import build_queue_plan
from .queue_adapter import build_queue_adapter_contract
from .provider_workflow_plan import build_provider_workflow_plan
from .product_feedback import (
    ProductFeedbackIdempotencyConflict,
    ProductFeedbackStatusConflict,
    ProductFeedbackValidationError,
)
from .readiness import build_degraded_product_readiness, build_product_readiness_or_degraded
from .repository import HIGH_RISK_ACTIONS, SaaSRepository
from .runtime_bridge import RuntimeBridge
from .security import SessionManager
from .secret_store import SecretStoreBoundary
from .staging_security_gate import build_controlled_staging_security_gate
from .task_secret_grants import build_task_secret_grant_plan
from .vault_client import build_task_secret_resolution_contract, build_vault_client_contract
from .vault_secret_resolver import VaultSecretResolver, build_vault_secret_resolver_status
from .redis_queue_runtime import RedisStreamQueueWorker, publish_redis_queue_job_if_configured
from .registration_challenge import public_registration_challenge_config, verify_registration_challenge
from .worker import LocalQueueWorker
from .workflow_plan import product_workflow_steps


MAX_JSON_BODY_BYTES = 1024 * 1024
AUTH_RATE_LIMIT_WINDOW_SECONDS = 5 * 60
AUTH_RATE_LIMIT_MAX_PER_EMAIL = 20
AUTH_RATE_LIMIT_MAX_PER_IP = 80
AUTH_RATE_LIMIT_MAX_GLOBAL_DEFAULT = 1500
AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP_DEFAULT = 10
AUTH_REGISTER_RATE_LIMIT_MAX_GLOBAL_DEFAULT = 60
EXPENSIVE_API_RATE_LIMIT_WINDOW_SECONDS_DEFAULT = 60
EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP_DEFAULT = 180
EXPENSIVE_API_RATE_LIMIT_MAX_GLOBAL_DEFAULT = 5000
PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_DEFAULT = 60
PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_MIN = 10
PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_MAX = 60 * 60
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER_DEFAULT = 12
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER_MAX = 120
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY_DEFAULT = 30
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY_MAX = 300
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP_DEFAULT = 60
PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP_MAX = 600
DOMESTIC_RECONCILIATION_RATE_LIMIT_WINDOW_SECONDS = 60
DOMESTIC_RECONCILIATION_RATE_LIMIT_MAX_PER_COMPANY = 6
LOCAL_RATE_LIMIT_MAX_BUCKETS_DEFAULT = 4096
EXPENSIVE_API_RATE_LIMIT_PREFIXES = (
    "tasks",
    "reports",
    "model/",
    "commercial/",
    "data-packets",
    "stores/",
    "ebay-read-only",
    "ebay-write",
    "ip-risk-screening",
    "merchant-memory",
    "merchant-ceo-commands",
    "ai-ceo/",
    "queue-jobs",
    "media-asset-jobs",
    "media-source-assets",
    "workers/",
    "confirmations",
    "execution-results",
    "audit-logs",
    "billing/manual-beta",
    "billing/domestic",
    "provider-job-contracts",
    "post-publish",
    "owner/",
    "webhooks/ebay/",
)
EXPENSIVE_API_RATE_LIMIT_EXACT_PATHS = {
    "billing/checkout-session",
    "billing/customer-portal",
    "billing/test-event",
}
SESSION_COOKIE_NAME = "jiejing_saas_session"
MEDIA_PROVIDER_JOB_KEYS = {"media.asset_generation", "media.fal_asset_generation"}
PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV = "JIEJING_AI_CEO_PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT"
PLATFORM_MODEL_TRIAL_DEFAULT_MONTHLY_LIMIT = 20
PLATFORM_TRIAL_ACTIVATION_WINDOW_SECONDS = 24 * 60 * 60
PLATFORM_TRIAL_ACTIVATION_MAX_PER_IP_DEFAULT = 3
PLATFORM_TRIAL_ACTIVATION_MAX_GLOBAL_DEFAULT = 200


def build_ai_ceo_market_report_delivery(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a merchant-safe handoff summary for AI CEO market reports."""

    if not isinstance(report, dict) or not report.get("report_id"):
        return None
    body = report.get("report") if isinstance(report.get("report"), dict) else {}
    handoff = body.get("listing_handoff") if isinstance(body.get("listing_handoff"), dict) else {}
    return {
        "contract_version": "2026-07-04-ai-ceo-market-report-delivery-v1",
        "mode": "quick_then_structured_report",
        "report_id": str(report.get("report_id") or ""),
        "report_type": str(report.get("report_type") or "ai_ceo.market_research"),
        "status": str(report.get("status") or "saved"),
        "title": str(report.get("title") or body.get("merchant_readable_summary") or "AI CEO 市场调研")[:180],
        "product": str(body.get("product") or "")[:120],
        "created_at": str(report.get("created_at") or ""),
        "structured_report_saved": True,
        "listing_import_ready": handoff.get("ready_for_listing_draft") is True,
        "source_record_count": int(body.get("source_record_count") or 0),
        "requires_human_review_before_publish": handoff.get("requires_human_review_before_publish") is not False,
        "triggers_real_platform_write": False,
        "real_platform_writes_enabled": False,
        "frontend_gets_model_api_key": False,
        "runtime_gets_raw_ebay_token": False,
        "secret_exposed": False,
    }


class RequestBodyError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class JiejingSafeThreadingHTTPServer(ThreadingHTTPServer):
    """Emit a bounded event for unhandled handlers without request or exception details."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        event = {
            "event": "http_request_handler_error",
            "request_data_logged": False,
            "client_address_logged": False,
            "exception_details_logged": False,
            "secret_exposed": False,
        }
        sys.stderr.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def initialize_repository_for_startup(repository: SaaSRepository, settings: SaaSSettings) -> Exception | None:
    try:
        repository.initialize()
        return None
    except Exception as exc:
        if settings.environment == "production":
            raise RuntimeError(
                "Refusing to start production Jiejing SaaS backend while repository readiness has blockers."
            ) from exc
        return exc


def _query_limit(query: dict[str, list[str]], *, default: int | None = None, maximum: int = 100) -> int | None:
    raw = query.get("limit", [None])[0]
    if raw in (None, ""):
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, maximum)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _bounded_positive_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    return min(max(_positive_int_env(name, default), minimum), maximum)


def _parse_ip_address(value: str) -> Any | None:
    try:
        parsed = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        return parsed.ipv4_mapped
    return parsed


def _trusted_proxy_networks() -> tuple[Any, ...]:
    raw = os.environ.get("JIEJING_TRUSTED_PROXY_CIDRS", "127.0.0.0/8,::1/128")
    networks: list[Any] = []
    for item in raw.replace(";", ",").split(","):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _ip_in_networks(value: Any, networks: tuple[Any, ...]) -> bool:
    return any(value.version == network.version and value in network for network in networks)


def _nonnegative_int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name) or "").strip())
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _media_asset_idempotency_key(*, store_id: str, provider_job_key: str, inputs: dict[str, Any], supplied: Any = None) -> str:
    supplied_text = str(supplied or "").strip()
    if supplied_text:
        return supplied_text[:160]
    fingerprint_payload = {
        "store_id": store_id,
        "provider_job_key": provider_job_key,
        "inputs": _redact_secret_like(inputs),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, default=json_default).encode("utf-8")).hexdigest()[:24]
    return f"media:{store_id}:{fingerprint}"


def _sanitize_media_source_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Persist only the opaque asset id, never a signed source capability URL."""
    sanitized = dict(inputs)
    product_facts = dict(sanitized.get("product_facts")) if isinstance(sanitized.get("product_facts"), dict) else {}
    asset_id = str(product_facts.get("source_asset_id") or sanitized.get("source_asset_id") or "").strip()
    if not asset_id:
        return sanitized
    if _is_signed_media_source_url(sanitized.get("reference_image_url")):
        sanitized.pop("reference_image_url", None)
    references = product_facts.get("reference_images") if isinstance(product_facts.get("reference_images"), list) else []
    product_facts["reference_images"] = [item for item in references if not _is_signed_media_source_url(item)]
    product_facts["private_source_transport"] = "backend_asset_id"
    sanitized["product_facts"] = product_facts
    return sanitized


def _merchant_safe_replaceable_media_provider(value: Any) -> Any:
    """Remove replaceable media driver names from every browser JSON response."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.lower() in {"media_provider", "preferred_media_provider", "source_provider_or_upload"}:
                safe[key] = "jiejing_media_router"
            else:
                safe[key] = _merchant_safe_replaceable_media_provider(raw_value)
        return safe
    if isinstance(value, list):
        return [_merchant_safe_replaceable_media_provider(item) for item in value]
    if isinstance(value, tuple):
        return [_merchant_safe_replaceable_media_provider(item) for item in value]
    if isinstance(value, str):
        safe_text = re.sub(r"media\.fal_asset_generation", "media.asset_generation", value, flags=re.IGNORECASE)
        return re.sub(r"\bfal(?:\.ai)?\b", "jiejing_media_router", safe_text, flags=re.IGNORECASE)
    return value


def _is_signed_media_source_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value or ""))
        query = parse_qs(parsed.query)
    except (TypeError, ValueError):
        return False
    return parsed.path.startswith("/media-source-assets/") and parsed.path.endswith("/content") and bool(query.get("signature"))


class SaaSBackendServer:
    def __init__(
        self,
        *,
        db_path: Path,
        runtime_db_path: Path,
        output_root: Path,
        host: str = "127.0.0.1",
        port: int = 8788,
    ) -> None:
        self.db_path = db_path
        self.runtime_db_path = runtime_db_path
        self.output_root = output_root
        self.host = host
        self.port = port
        self.settings = SaaSSettings.from_env(
            db_path=db_path,
            runtime_db_path=runtime_db_path,
            output_root=output_root,
            host=host,
            port=port,
        )

    def serve_forever(self) -> None:
        session_manager = SessionManager()
        backend_settings = self.settings
        public_base_url = str(os.environ.get("JIEJING_PUBLIC_BASE_URL") or f"http://{self.host}:{self.port}").rstrip("/")
        media_source_assets = MediaSourceAssetStore(
            root=self.output_root / "private-media-source-assets",
            signing_secret=session_manager.secret,
            public_base_url=public_base_url,
        )
        repo = SaaSRepository(
            self.db_path,
            database_engine=backend_settings.database_engine,
            database_url=os.environ.get("JIEJING_DATABASE_URL", ""),
        )
        startup_repository_error = initialize_repository_for_startup(repo, backend_settings)
        if startup_repository_error is not None:
            print(
                "Jiejing SaaS repository startup degraded: "
                f"{startup_repository_error.__class__.__name__}",
                file=sys.stderr,
            )
        bridge = RuntimeBridge(
            runtime_db_path=self.runtime_db_path,
            output_root=self.output_root,
            allow_hermes_adapters=backend_settings.allow_hermes_adapters,
        )
        worker_runtime = (
            RedisStreamQueueWorker(
                repository=repo,
                runtime_bridge=bridge,
                settings=backend_settings,
                media_source_asset_store=media_source_assets,
            )
            if backend_settings.queue_provider == "redis_streams"
            else LocalQueueWorker(
                repository=repo,
                runtime_bridge=bridge,
                settings=backend_settings,
                media_source_asset_store=media_source_assets,
            )
        )
        secret_store = SecretStoreBoundary(backend_settings)
        ebay_oauth = EbayOAuthPlanner(backend_settings)
        ebay_read = EbayReadOnlyAdapter(backend_settings)
        ebay_live_read_plan = EbayLiveReadPlanBuilder(backend_settings)
        ebay_account_deletion_verifier = EbayNotificationSignatureVerifier(
            environment=backend_settings.ebay_oauth_environment,
            client_id=backend_settings.ebay_client_id,
            client_secret=os.environ.get("JIEJING_EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CLIENT_SECRET") or "",
        )
        readiness = (
            build_degraded_product_readiness(settings=backend_settings, exc=startup_repository_error)
            if startup_repository_error is not None
            else build_product_readiness_or_degraded(backend_settings, repo)
        )
        if backend_settings.environment == "production" and not readiness.get("production_ready"):
            raise RuntimeError("Refusing to start production Jiejing SaaS backend while readiness has blockers.")
        if backend_settings.requested_real_platform_writes and not backend_settings.ebay_write_live_enabled:
            raise RuntimeError("Refusing to enable real platform writes without JIEJING_EBAY_WRITE_LIVE=true.")

        class Handler(SaaSBackendHandler):
            repository = repo
            sessions = session_manager
            runtime_bridge = bridge
            queue_worker = worker_runtime
            secret_store_boundary = secret_store
            ebay_oauth_planner = ebay_oauth
            ebay_read_adapter = ebay_read
            ebay_live_read_plan_builder = ebay_live_read_plan
            ebay_account_deletion_signature_verifier = ebay_account_deletion_verifier
            media_source_asset_store = media_source_assets
            settings = backend_settings
            repository_startup_error = startup_repository_error

        server = JiejingSafeThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Jiejing SaaS Backend MVP listening on http://{self.host}:{self.port} env={backend_settings.environment}")
        server.serve_forever()


_MERCHANT_PLAN_TEXT_FIELDS = {"key", "label", "intended_user", "currency", "store_access_mode"}
_MERCHANT_PLAN_COUNT_FIELDS = {
    "amount_minor",
    "duration_days",
    "workspace_quota",
    "team_member_quota",
    "monthly_task_quota",
    "connected_store_quota",
    "provider_job_quota",
    "batch_row_quota",
    "media_points_included",
}
_MERCHANT_METERED_UNITS = {
    "connected_store",
    "ai_ceo_task",
    "provider_job",
    "official_ebay_sync",
    "model_report_assist",
}
_MAINLAND_PAYMENT_SAFETY_FIELDS = (
    "public_charging_allowed",
    "charge_now_allowed",
    "triggers_real_charge",
    "triggers_real_refund",
    "calls_external_payment_api",
    "calls_stripe_api",
    "real_platform_writes_enabled",
    "frontend_gets_payment_secret",
    "secret_exposed",
)
_MAINLAND_PAYMENT_CAPABILITY_FIELDS = (
    "signed_payment_callback_implemented",
    "signed_refund_callback_implemented",
    "real_order_creation_implemented",
    "authenticated_order_query_implemented",
    "quota_entitlement_persistence_implemented",
    "high_risk_confirmation_boundary_implemented",
)


def _safe_bounded_text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str) else ""


_PUBLIC_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:bearer\s+\S+|secret[_-]?ref|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|password\s*[:=]|"
    r"credential\s*[:=]|-----BEGIN[^-]*PRIVATE KEY-----)"
)
_PUBLIC_TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/+-]{0,159}$")
_PUBLIC_MODEL_PROVIDERS = {
    "openai",
    "deepseek",
    "openrouter",
    "qwen_dashscope",
    "moonshot",
    "anthropic",
    "google_gemini",
    "tencent_hunyuan",
}


def _safe_public_text(value: Any, limit: int = 1024) -> str:
    text = _safe_bounded_text(value, limit)
    return "" if not text or _PUBLIC_SENSITIVE_TEXT.search(text) else text


def _safe_public_token(value: Any, *, allowed: set[str] | None = None, limit: int = 160) -> str:
    text = _safe_public_text(value, limit)
    if not text or not _PUBLIC_TOKEN.fullmatch(text):
        return ""
    if allowed is not None and text not in allowed:
        return ""
    return text


def _safe_public_token_list(value: Any, *, limit: int = 32) -> list[str]:
    safe: list[str] = []
    for item in value if isinstance(value, list) else []:
        token = _safe_public_token(item)
        if token and token not in safe:
            safe.append(token)
        if len(safe) >= limit:
            break
    return safe


def _safe_public_readiness_items(value: Any) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or item.get("severity") not in {"warning", "blocker"}:
            continue
        safe.append(
            {
                "key": _safe_public_token(item.get("key")),
                "label": _safe_public_text(item.get("label"), 256),
                "status": _safe_public_token(item.get("status")),
                "severity": item["severity"],
                "detail": _safe_public_text(item.get("detail"), 1024),
                "next_action": _safe_public_text(item.get("next_action"), 1024),
            }
        )
        if len(safe) >= 8:
            break
    return safe


def _strict_nonnegative_int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _merchant_safe_plan_catalog(value: Any) -> list[dict[str, Any]]:
    safe_catalog: list[dict[str, Any]] = []
    for raw_plan in value if isinstance(value, list) else []:
        if not isinstance(raw_plan, dict):
            continue
        safe_plan: dict[str, Any] = {}
        for key in _MERCHANT_PLAN_TEXT_FIELDS:
            if isinstance(raw_plan.get(key), str):
                safe_plan[key] = _safe_public_text(raw_plan[key], 512)
        for key in _MERCHANT_PLAN_COUNT_FIELDS:
            item = raw_plan.get(key)
            if type(item) is int and item >= 0:
                safe_plan[key] = item
        if "includes_real_platform_writes" in raw_plan:
            safe_plan["includes_real_platform_writes"] = False
        if safe_plan.get("key"):
            safe_catalog.append(safe_plan)
    return safe_catalog


def _merchant_safe_add_on_catalog(value: Any) -> list[dict[str, Any]]:
    safe_catalog: list[dict[str, Any]] = []
    for raw_add_on in value if isinstance(value, list) else []:
        if not isinstance(raw_add_on, dict):
            continue
        safe_add_on: dict[str, Any] = {}
        for key in ("key", "label", "currency"):
            if isinstance(raw_add_on.get(key), str):
                safe_add_on[key] = _safe_public_text(raw_add_on[key], 512)
        for key in ("amount_minor", "duration_days"):
            item = raw_add_on.get(key)
            if type(item) is int and item >= 0:
                safe_add_on[key] = item
        if safe_add_on.get("key"):
            safe_catalog.append(safe_add_on)
    return safe_catalog


def _merchant_safe_metered_units(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item in _MERCHANT_METERED_UNITS]


def _merchant_safe_mainland_payment(launch: dict[str, Any]) -> dict[str, Any]:
    payment = validate_mainland_payment_launch_for_public(launch)
    return {
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "status": payment["merchant_status"],
        "next_blocker": payment["next_paid_launch_blocker"],
        "mainland_payment_ready_for_owner_approval": payment["mainland_payment_ready_for_owner_approval"],
        "provider_configured": payment["provider_configured"],
        "configured_component_count": payment["configured_component_count"],
        "required_component_count": payment["required_component_count"],
        "verified_paid_order_count": payment["verified_paid_order_count"],
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "triggers_real_refund": False,
        "calls_external_payment_api": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _merchant_safe_launch_path(value: Any, *, mainland_payment: dict[str, Any], quota_enabled: bool) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    private_beta_active = all(
        (
            source.get("contract_version") == "2026-07-03-merchant-billing-launch-path-v1",
            source.get("current_stage") == "invited_beta_no_real_charge",
            source.get("public_paid_launch_allowed") is False,
            source.get("charge_now_allowed") is False,
            source.get("triggers_real_charge") is False,
            source.get("frontend_can_grant_entitlement") is False,
            source.get("frontend_can_grant_quota") is False,
            source.get("backend_confirmation_required_before_entitlement") is True,
            source.get("secret_exposed") is False,
        )
    )
    safe_steps: list[dict[str, Any]] = []
    if private_beta_active:
        for item in source.get("steps") if isinstance(source.get("steps"), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                continue
            safe_steps.append(
                {
                    "key": _safe_bounded_text(item.get("key"), 96),
                    "label": _safe_public_text(item.get("label"), 256),
                    "title": _safe_public_text(item.get("title"), 512),
                    "detail": _safe_public_text(item.get("detail"), 1024),
                    "ready": item.get("ready") is True,
                }
            )
    return {
        "contract_version": (
            "2026-07-03-merchant-billing-launch-path-v1"
            if private_beta_active
            else "2026-07-27-merchant-mainland-payment-path-v1"
        ),
        "current_stage": "invited_beta_no_real_charge" if private_beta_active else mainland_payment["status"],
        "headline": (
            _safe_public_text(source.get("headline"), 1024)
            if private_beta_active
            else "merchant_payment_status_available_in_billing_control_room"
        ),
        "current_charge_status": "no_real_charge_now",
        "merchant_visible": True,
        "internal_launch_evidence_visible": False,
        "public_paid_launch_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "frontend_can_grant_entitlement": False,
        "frontend_can_grant_quota": False,
        "backend_confirmation_required_before_entitlement": True,
        "hosted_payment_page_required_for_formal_payment": False,
        "quota_enforcement_enabled": quota_enabled,
        "quota_grant_source": "backend_subscription_state",
        "history_visible_after_billing_problem": True,
        "metered_work_only_blocks_on_billing_problem": True,
        "repeat_ebay_oauth_required_for_billing_recovery": False,
        "model_key_reentry_required_for_billing_recovery": False,
        "next_paid_launch_blocker": mainland_payment["next_blocker"],
        "steps": safe_steps,
        "secret_exposed": False,
    }


_MERCHANT_REHEARSAL_STEP_KEYS = {
    "test_provider_selected",
    "test_plan_catalog_available",
    "test_checkout_and_portal_contract",
    "test_subscription_lifecycle_events",
    "test_provider_order_query_or_signed_webhook",
    "quota_hard_stop_rehearsal",
    "test_checkout_session",
    "backend_order_query_or_signed_webhook_proof",
    "quota_shutdown_closure",
    "quota_guardrail_evaluated",
}
_MERCHANT_SHUTDOWN_STEP_KEYS = {
    "subscription_activation_grants_entitlement",
    "invoice_paid_keeps_quota_open",
    "payment_failed_disables_entitlement",
    "subscription_cancel_disables_entitlement",
    "quota_guardrail_blocks_metered_work",
    "customer_portal_changes_audited",
    "provider_cutover_no_real_charge_safety",
}
_MERCHANT_INCIDENT_CARD_KEYS = {
    "customer_portal_change",
    "payment_failed",
    "subscription_cancelled",
    "refund_or_dispute",
    "quota_hard_stop",
}
_MERCHANT_TRUST_CARD_KEYS = {
    "price_and_renewal_terms",
    "invoice_receipt_tax_path",
    "refund_support_public_entry",
    "entitlement_recovery_boundary",
}


def _merchant_safe_status_items(value: Any, *, allowed_keys: set[str], limit: int = 12) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or item.get("key") not in allowed_keys:
            continue
        status = item.get("status") if item.get("status") in {"ready", "blocked", "pending"} else "blocked"
        safe.append(
            {
                "key": item["key"],
                "status": status,
                "severity": "info" if status == "ready" else "blocker",
                "owner_approval_required": item.get("owner_approval_required") is True,
                "frontend_action_allowed": False,
                "charge_now_allowed": False,
                "triggers_real_charge": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            }
        )
        if len(safe) >= limit:
            break
    return safe


def _merchant_safe_item_counts(items: list[dict[str, Any]]) -> tuple[int, int, int]:
    ready = sum(1 for item in items if item.get("status") == "ready")
    total = len(items)
    return ready, total, total - ready


def _merchant_safe_rehearsal_summary(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    steps = _merchant_safe_status_items(source.get("steps"), allowed_keys=_MERCHANT_REHEARSAL_STEP_KEYS)
    ready_count, total_count, blocked_count = _merchant_safe_item_counts(steps)
    next_step = next((item["key"] for item in steps if item["status"] != "ready"), "")
    return {
        "contract_version": (
            "2026-06-18-no-charge-billing-rehearsal"
            if source.get("contract_version") == "2026-06-18-no-charge-billing-rehearsal"
            else ""
        ),
        "ready": source.get("ready") is True and blocked_count == 0 and total_count > 0,
        "ready_count": ready_count,
        "total_count": total_count,
        "blocked_count": blocked_count,
        "next_step": next_step,
        "steps": steps,
        "paid_launch_ready": False,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _merchant_safe_shutdown_summary(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    steps = _merchant_safe_status_items(source.get("steps"), allowed_keys=_MERCHANT_SHUTDOWN_STEP_KEYS)
    ready_count, total_count, blocked_count = _merchant_safe_item_counts(steps)
    guards = source.get("shutdown_guards") if isinstance(source.get("shutdown_guards"), dict) else {}
    return {
        "contract_version": (
            "2026-06-20-subscription-quota-shutdown-closure"
            if source.get("contract_version") == "2026-06-20-subscription-quota-shutdown-closure"
            else ""
        ),
        "ready": source.get("ready") is True and blocked_count == 0 and total_count > 0,
        "ready_count": ready_count,
        "total_count": total_count,
        "blocked_count": blocked_count,
        "next_step": next((item["key"] for item in steps if item["status"] != "ready"), ""),
        "steps": steps,
        "covered_actions": _merchant_safe_metered_units(source.get("covered_actions")),
        "shutdown_guards": {
            "hard_stop_on_inactive_subscription": guards.get("hard_stop_on_inactive_subscription") is True,
            "payment_failure_blocks_metered_work": guards.get("payment_failure_blocks_metered_work") is True,
            "cancellation_blocks_metered_work": guards.get("cancellation_blocks_metered_work") is True,
            "usage_remains_visible_after_shutdown": guards.get("usage_remains_visible_after_shutdown") is True,
            "owner_approval_required_for_reenable": True,
            "secret_exposed": False,
        },
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _merchant_safe_incident_runbook(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    cards = _merchant_safe_status_items(source.get("cards"), allowed_keys=_MERCHANT_INCIDENT_CARD_KEYS)
    ready_count, total_count, blocked_count = _merchant_safe_item_counts(cards)
    return {
        "contract_version": (
            "2026-07-01-billing-incident-runbook-v1"
            if source.get("contract_version") == "2026-07-01-billing-incident-runbook-v1"
            else ""
        ),
        "cards": cards,
        "ready_count": ready_count,
        "total_count": total_count,
        "blocked_count": blocked_count,
        "refund_or_dispute_cannot_be_frontend_executed": True,
        "history_and_audit_remain_visible": True,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _merchant_safe_trust_packet(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    cards = _merchant_safe_status_items(source.get("cards"), allowed_keys=_MERCHANT_TRUST_CARD_KEYS)
    ready_count, total_count, blocked_count = _merchant_safe_item_counts(cards)
    return {
        "contract_version": (
            "2026-07-01-customer-billing-trust-packet-v1"
            if source.get("contract_version") == "2026-07-01-customer-billing-trust-packet-v1"
            else ""
        ),
        "cards": cards,
        "ready_count": ready_count,
        "total_count": total_count,
        "blocked_count": blocked_count,
        "next_step": next((item["key"] for item in cards if item["status"] != "ready"), ""),
        "support_refund_links_visible": source.get("support_refund_links_visible") is True,
        "entitlement_recovery_does_not_repeat_ebay_oauth": True,
        "ready_for_paid_customer_display": False,
        "public_charging_allowed": False,
        "charge_now_allowed": False,
        "triggers_real_charge": False,
        "frontend_gets_payment_secret": False,
        "secret_exposed": False,
    }


def _public_safe_billing_summary(value: Any) -> dict[str, Any]:
    billing = value if isinstance(value, dict) else {}
    domestic = billing.get("domestic_payment") if isinstance(billing.get("domestic_payment"), dict) else {}
    launch_path = billing.get("merchant_launch_path") if isinstance(billing.get("merchant_launch_path"), dict) else {}
    configured_count = billing.get("configured_component_count")
    required_count = billing.get("required_component_count")
    verified_count = billing.get("verified_paid_order_count")
    payment_statuses = {
        "payment_status_unavailable",
        "configuration_in_progress",
        "backend_safety_controls_in_progress",
        "provider_connection_in_progress",
        "production_environment_pending",
        "refund_controls_pending",
        "controlled_acceptance_pending",
        "controlled_acceptance_proven_public_charging_closed",
    }
    domestic_statuses = {
        "unavailable",
        "configuration_in_progress",
        "backend_safety_controls_in_progress",
        "provider_connection_in_progress",
        "production_environment_pending",
        "refund_controls_pending",
        "controlled_acceptance_pending",
        "controlled_acceptance_proven",
    }
    status_contracts = {
        "payment_status_unavailable": ("unavailable", "merchant_payment_status_unavailable", False, False),
        "configuration_in_progress": (
            "configuration_in_progress",
            "merchant_payment_provider_configuration_incomplete",
            False,
            False,
        ),
        "backend_safety_controls_in_progress": (
            "backend_safety_controls_in_progress",
            "merchant_payment_backend_safety_controls_incomplete",
            False,
            True,
        ),
        "provider_connection_in_progress": (
            "provider_connection_in_progress",
            "merchant_payment_provider_connection_not_ready",
            False,
            False,
        ),
        "production_environment_pending": (
            "production_environment_pending",
            "merchant_payment_production_environment_required",
            False,
            True,
        ),
        "refund_controls_pending": (
            "refund_controls_pending",
            "merchant_payment_refund_not_ready",
            False,
            True,
        ),
        "controlled_acceptance_pending": (
            "controlled_acceptance_pending",
            "merchant_payment_controlled_acceptance_not_proven",
            False,
            True,
        ),
        "controlled_acceptance_proven_public_charging_closed": (
            "controlled_acceptance_proven",
            "merchant_payment_public_cutover_not_approved",
            True,
            True,
        ),
    }
    counts_valid = (
        type(configured_count) is int
        and type(required_count) is int
        and type(verified_count) is int
        and configured_count >= 0
        and required_count == 9
        and configured_count <= required_count
        and verified_count >= 0
        and type(domestic.get("configured_component_count")) is int
        and domestic.get("configured_component_count") == configured_count
        and type(domestic.get("required_component_count")) is int
        and domestic.get("required_component_count") == required_count
        and type(domestic.get("verified_paid_order_count")) is int
        and domestic.get("verified_paid_order_count") == verified_count
        and type(domestic.get("controlled_acceptance_proven")) is bool
        and domestic.get("controlled_acceptance_proven") is (verified_count > 0)
    )
    count_semantics_valid = counts_valid and (
        (
            billing.get("payment_path_status") == "configuration_in_progress"
            and configured_count < required_count
        )
        or (
            billing.get("payment_path_status") == "payment_status_unavailable"
            and configured_count == 0
            and verified_count == 0
        )
        or (
            billing.get("payment_path_status")
            not in {"configuration_in_progress", "payment_status_unavailable"}
            and configured_count == required_count
        )
    )
    safety_valid = all(
        billing.get(key) is False
        for key in (
            "billing_ready_for_paid_launch",
            "public_charging_allowed",
            "charge_now_allowed",
            "triggers_real_charge",
            "triggers_real_refund",
            "calls_external_payment_api",
            "real_platform_writes_enabled",
            "frontend_gets_payment_secret",
            "frontend_can_grant_quota",
            "secret_exposed",
        )
    ) and all(
        domestic.get(key) is False
        for key in (
            "public_charging_allowed",
            "charge_now_allowed",
            "triggers_real_charge",
            "triggers_real_refund",
            "calls_external_payment_api",
            "frontend_gets_payment_secret",
            "secret_exposed",
        )
    )
    expected_status_contract = status_contracts.get(billing.get("payment_path_status"))
    core_valid = all(
        (
            billing.get("provider") == "wechat_pay_native",
            billing.get("checkout_mode") == "native_qr",
            billing.get("billing_mode") == "one_time_30_day_plan",
            domestic.get("provider") == "wechat_pay_native",
            domestic.get("checkout_mode") == "native_qr",
            domestic.get("billing_mode") == "one_time_30_day_plan",
            type(billing.get("provider_configured")) is bool,
            type(billing.get("mainland_payment_ready_for_owner_approval")) is bool,
            type(billing.get("billing_ready_for_private_beta")) is bool,
            type(billing.get("quota_enforcement_enabled")) is bool,
            billing.get("payment_path_status") in payment_statuses,
            domestic.get("status") in domestic_statuses,
            expected_status_contract is not None,
            expected_status_contract is not None
            and domestic.get("status") == expected_status_contract[0],
            expected_status_contract is not None
            and billing.get("next_paid_launch_blocker") == expected_status_contract[1],
            expected_status_contract is not None
            and billing.get("mainland_payment_ready_for_owner_approval") is expected_status_contract[2],
            expected_status_contract is not None
            and billing.get("provider_configured") is expected_status_contract[3],
            count_semantics_valid,
            expected_status_contract is not None
            and (
                billing.get("payment_path_status") != "controlled_acceptance_pending"
                or verified_count == 0
            ),
            expected_status_contract is not None
            and (
                billing.get("payment_path_status") != "controlled_acceptance_proven_public_charging_closed"
                or verified_count > 0
            ),
            counts_valid,
            safety_valid,
        )
    )
    private_beta_path = all(
        (
            launch_path.get("contract_version") == "2026-07-03-merchant-billing-launch-path-v1",
            launch_path.get("current_stage") == "invited_beta_no_real_charge",
            billing.get("billing_ready_for_private_beta") is True,
        )
    )
    mainland_path = all(
        (
            launch_path.get("contract_version") == "2026-07-27-merchant-mainland-payment-path-v1",
            launch_path.get("current_stage") in payment_statuses,
        )
    )
    launch_path_valid = (private_beta_path or mainland_path) and all(
        launch_path.get(key) is expected
        for key, expected in {
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "secret_exposed": False,
        }.items()
    )
    if not core_valid:
        configured_count = 0
        required_count = 0
        verified_count = 0
        payment_status = "payment_status_unavailable"
        domestic_status = "unavailable"
        next_blocker = "merchant_payment_status_unavailable"
        owner_ready = False
        provider_configured = False
    else:
        payment_status = billing["payment_path_status"]
        domestic_status = domestic["status"]
        next_blocker = billing["next_paid_launch_blocker"]
        owner_ready = billing.get("mainland_payment_ready_for_owner_approval") is True
        provider_configured = billing.get("provider_configured") is True
    safe_stage = (
        "invited_beta_no_real_charge"
        if launch_path_valid and private_beta_path
        else payment_status
    )
    safe_path_contract = (
        "2026-07-03-merchant-billing-launch-path-v1"
        if launch_path_valid and private_beta_path
        else "2026-07-27-merchant-mainland-payment-path-v1"
    )
    return {
        "provider": "wechat_pay_native",
        "checkout_mode": "native_qr",
        "billing_mode": "one_time_30_day_plan",
        "provider_configured": provider_configured,
        "payment_path_status": payment_status,
        "mainland_payment_ready_for_owner_approval": owner_ready,
        "billing_ready_for_private_beta": billing.get("billing_ready_for_private_beta") is True,
        "billing_ready_for_paid_launch": False,
        "configured_component_count": configured_count,
        "required_component_count": required_count,
        "verified_paid_order_count": verified_count,
        "quota_enforcement_enabled": billing.get("quota_enforcement_enabled") is True,
        "paid_launch_blocker_count": 1,
        "next_paid_launch_blocker": next_blocker,
        "merchant_launch_path": {
            "contract_version": safe_path_contract,
            "current_stage": safe_stage,
            "current_charge_status": "no_real_charge_now",
            "public_paid_launch_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "quota_grant_source": "backend_subscription_state",
            "secret_exposed": False,
        },
        "domestic_payment": {
            "provider": "wechat_pay_native",
            "checkout_mode": "native_qr",
            "billing_mode": "one_time_30_day_plan",
            "status": domestic_status,
            "configured_component_count": configured_count,
            "required_component_count": required_count,
            "verified_paid_order_count": verified_count,
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
    }


class SaaSBackendHandler(BaseHTTPRequestHandler):
    repository: SaaSRepository
    sessions: SessionManager
    runtime_bridge: RuntimeBridge
    queue_worker: LocalQueueWorker
    secret_store_boundary: SecretStoreBoundary
    ebay_oauth_planner: EbayOAuthPlanner
    ebay_read_adapter: EbayReadOnlyAdapter
    ebay_live_read_plan_builder: EbayLiveReadPlanBuilder
    ebay_account_deletion_signature_verifier: EbayNotificationSignatureVerifier
    media_source_asset_store: MediaSourceAssetStore
    settings: SaaSSettings
    repository_startup_error: Exception | None = None
    auth_rate_limit_lock = threading.Lock()
    auth_rate_limit_buckets: dict[str, list[float]] = {}
    expensive_api_rate_limit_lock = threading.Lock()
    expensive_api_rate_limit_buckets: dict[str, list[float]] = {}
    platform_trial_activation_rate_limit_lock = threading.Lock()
    platform_trial_activation_rate_limit_buckets: dict[str, list[float]] = {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except Exception as exc:
            if self._handle_service_dependency_exception(exc):
                return
            raise

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        parts = [unquote(part) for part in path.split("/")] if path else []

        if path in {"", "health"}:
            self._send_json(
                {
                    "status": "ok",
                    "service": "jiejing-saas-backend-mvp",
                    "environment": self.settings.environment,
                    "chain": "frontend -> backend -> auth/permission -> database -> queue -> runtime -> reports -> confirmation -> execution_service -> audit",
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                    "requested_real_platform_writes": self.settings.requested_real_platform_writes,
                    "database_startup_status": "degraded" if self.repository_startup_error is not None else "ready",
                    "database_startup_error_type": self.repository_startup_error.__class__.__name__
                    if self.repository_startup_error is not None
                    else "",
                    "secret_exposed": False,
                }
            )
            return

        if path == "schema/chain":
            self._send_json({"chain": self._chain_schema()})
            return

        if path in {"readiness", "readiness/product-saas"}:
            readiness = build_product_readiness_or_degraded(self.settings, self.repository)
            identity = self._optional_identity()
            if not self.settings.is_production_like or self._can_view_internal_diagnostics(identity):
                self._send_json({"readiness": readiness})
            else:
                self._send_json({"readiness": self._public_readiness_summary(readiness, authenticated=identity is not None)})
            return

        if path in {"health/deep", "operational-health"}:
            operational_health = build_operational_health(self.settings, self.repository)
            identity = self._optional_identity()
            if not self.settings.is_production_like or self._can_view_internal_diagnostics(identity):
                self._send_json({"operational_health": operational_health})
            else:
                self._send_json({"operational_health": self._public_operational_health_summary(operational_health, authenticated=identity is not None)})
            return

        if path == "independence/status":
            self._send_json(
                {
                    "independence": build_independence_status(
                        settings=self.settings,
                        repository=self.repository,
                        project_root=Path(__file__).resolve().parents[1],
                    )
                }
            )
            return

        if path == "platforms":
            self._send_json({"platform_registry": registry_summary()})
            return

        if path.startswith("auth/qr-login"):
            self._send_error(HTTPStatus.NOT_FOUND, "QR login is not an active Jiejing login path")
            return

        if path == "auth/challenge-config":
            self._send_json(
                {
                    "registration_challenge": public_registration_challenge_config(
                        environment=self.settings.environment
                    ),
                    "secret_exposed": False,
                }
            )
            return

        if len(parts) == 2 and parts[0] == "platforms":
            platform = get_platform_definition(parts[1])
            if not platform:
                self._send_error(HTTPStatus.NOT_FOUND, "platform not found in connector registry")
                return
            self._send_json({"platform": platform})
            return

        if path == "webhooks/ebay/marketplace-account-deletion":
            if not self._check_expensive_api_rate_limit(method="GET", path=path):
                return
            try:
                response = build_challenge_response(
                    challenge_code=query.get("challenge_code", [""])[0],
                    verification_token=os.environ.get("JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN") or "",
                    endpoint_url=self.settings.ebay_account_deletion_endpoint_url,
                )
            except AccountDeletionError as exc:
                status = HTTPStatus.BAD_REQUEST if exc.code == "invalid_challenge" else HTTPStatus.SERVICE_UNAVAILABLE
                self._send_error(status, "account deletion endpoint verification is unavailable")
                return
            self._send_json(response)
            return

        if path == "oauth/ebay/callback":
            state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            error = query.get("error", [""])[0]
            result = self._handle_ebay_oauth_callback(state=state, code=code, error=error)
            status = self._oauth_callback_http_status(result)
            if self._wants_html_response():
                self._send_html(self._oauth_callback_public_html(result), status=status)
            else:
                self._send_json({"oauth_callback": result}, status=status)
            return

        if len(parts) == 3 and parts[0] == "media-source-assets" and parts[2] == "content":
            if not self._check_expensive_api_rate_limit(method="GET", path=path):
                return
            try:
                asset = self.media_source_asset_store.resolve(
                    asset_id=parts[1],
                    expires=query.get("expires", [""])[0],
                    signature=str(query.get("signature", [""])[0]),
                )
            except MediaSourceAssetError as exc:
                status = {
                    "asset_not_found": HTTPStatus.NOT_FOUND,
                    "signed_url_expired": HTTPStatus.GONE,
                    "asset_expired": HTTPStatus.GONE,
                }.get(exc.code, HTTPStatus.FORBIDDEN)
                self._send_error(status, str(exc))
                return
            self._send_media_source_asset(asset)
            return

        if not self._check_expensive_api_rate_limit(method="GET", path=path):
            return

        identity = self._require_auth()
        if identity is None:
            return

        if path == "product-feedback":
            limit = _query_limit(query, default=20, maximum=50) or 20
            receipts = self.repository.list_product_feedback(
                company_id=str(identity["company_id"]),
                limit=limit,
            )
            self._send_json(
                {
                    "product_feedback_receipts": receipts,
                    "returned_count": len(receipts),
                    "secret_exposed": False,
                }
            )
            return

        if path == "merchant-onboarding/primary-ebay":
            self._send_json({"merchant_onboarding": self._merchant_onboarding_read_model(identity)})
            return

        if path == "security/rate-limit/status":
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "rate-limit status is platform-internal admin only")
                return
            self._send_json({"rate_limit_status": self._rate_limit_status()})
            return

        if path == "me":
            member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
            self._send_json(
                {
                    "identity": identity,
                    "user": self.repository.get_user(identity["user_id"]),
                    "company": self.repository.get_company(identity["company_id"]),
                    "team_member": member,
                    "permissions": member.get("permissions", []) if member else [],
                }
            )
            return

        if path == "companies":
            self._send_json({"companies": self.repository.list_user_companies(user_id=identity["user_id"])})
            return

        if path == "permissions/me":
            member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
            self._send_json(
                {
                    "role": member.get("role") if member else None,
                    "permissions": member.get("permissions", []) if member else [],
                    "roles": role_summary(),
                    "platform_internal_admin": self._is_platform_internal_admin(identity),
                    "secret_exposed": False,
                }
            )
            return

        if path == "owner/launch-control":
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "owner launch control is platform-internal admin only")
                return
            store_id = query.get("store_id", [None])[0]
            if store_id:
                store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
                if not store:
                    self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                    return
            self._send_json(
                {
                    "owner_launch_control": build_owner_launch_control(
                        self.settings,
                        self.repository,
                        company_id=identity["company_id"],
                        store_id=store_id,
                    )
                }
            )
            return

        if path == "owner/production-release-gate":
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "production release gate is platform-internal admin only")
                return
            self._send_json({"production_release_gate": build_production_release_gate(self.settings, self.repository)})
            return

        if path == "owner/production-evidence-ledger":
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "production evidence ledger is platform-internal admin only")
                return
            self._send_json({"production_evidence_ledger": build_production_evidence_ledger(self.settings, self.repository)})
            return

        if path in {"owner/billing-domain-cutover-rehearsal", "commercial/billing-domain-cutover-rehearsal"}:
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "billing domain cutover rehearsal is platform-internal admin only")
                return
            self._send_json({"billing_domain_cutover_rehearsal": build_billing_domain_cutover_rehearsal(self.settings, self.repository)})
            return

        if path in {"owner/billing-provider-evidence-register", "commercial/billing-provider-evidence-register"}:
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "billing provider evidence register is platform-internal admin only")
                return
            self._send_json({"billing_provider_evidence_register": build_billing_provider_evidence_register(self.settings, self.repository)})
            return

        if path in {"owner/paid-launch-approval-packet", "commercial/paid-launch-approval-packet"}:
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "paid launch approval packet is platform-internal admin only")
                return
            self._send_json({"paid_launch_approval_packet": build_paid_launch_approval_packet(self.settings, self.repository)})
            return

        if path in {"owner/edge-cutover-preflight", "domain/edge-cutover-preflight"}:
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "edge cutover preflight is platform-internal admin only")
                return
            self._send_json({"edge_cutover_preflight": build_edge_cutover_preflight(self.settings)})
            return

        if path == "team/members":
            self._send_json({"team_members": self.repository.list_team_members(company_id=identity["company_id"])})
            return

        if path == "team/invitations":
            self._send_json({"team_invitations": self.repository.list_team_invitations(company_id=identity["company_id"])})
            return

        if path == "stores":
            self._send_json({"stores": self.repository.list_stores(company_id=identity["company_id"])})
            return

        if path == "vault/status":
            if not self._require_platform_internal_admin(identity, "vault status"):
                return
            self._send_json({"vault": self.secret_store_boundary.status()})
            return

        if path == "database/plan":
            if not self._require_platform_internal_admin(identity, "database plan"):
                return
            self._send_json({"database_plan": build_database_plan(self.settings, self.repository)})
            return

        if path == "database/inventory":
            if not self._require_platform_internal_admin(identity, "database inventory"):
                return
            self._send_json({"database_inventory": self.repository.database_inventory()})
            return

        if path == "database/adapters":
            if not self._require_platform_internal_admin(identity, "database adapters"):
                return
            self._send_json({"database_adapters": build_database_adapter_contract(self.settings)})
            return

        if path == "queue/plan":
            if not self._require_platform_internal_admin(identity, "queue plan"):
                return
            self._send_json({"queue_plan": build_queue_plan(self.settings, self.repository)})
            return

        if path == "queue/adapters":
            if not self._require_platform_internal_admin(identity, "queue adapters"):
                return
            self._send_json({"queue_adapters": build_queue_adapter_contract(self.settings)})
            return

        if path == "monitoring/status":
            if not self._require_platform_internal_admin(identity, "monitoring status"):
                return
            self._send_json({"monitoring": build_monitoring_status(self.settings, self.repository)})
            return

        if path == "infrastructure/drivers":
            if not self._require_platform_internal_admin(identity, "infrastructure drivers"):
                return
            self._send_json({"infrastructure_drivers": build_infrastructure_driver_status(self.settings)})
            return

        if path == "backup/plan":
            if not self._require_platform_internal_admin(identity, "backup plan"):
                return
            self._send_json({"backup_plan": build_backup_plan(self.settings, self.repository)})
            return

        if path == "billing/plans":
            plan = build_billing_plan(self.settings, self.repository)
            if not self._is_platform_internal_admin(identity):
                plan = self._merchant_safe_billing_plan(plan)
            self._send_json({"billing_plan": plan})
            return

        if path == "billing/payment-options":
            if not self._is_platform_internal_admin(identity):
                self._send_error(HTTPStatus.FORBIDDEN, "payment options are platform-internal admin only")
                return
            self._send_json({"payment_options": build_mainland_payment_strategy(self.settings)})
            return

        if path == "billing/checkout-contract":
            self._send_json({"billing_checkout": build_billing_checkout_contract()})
            return

        if path == "owner/operations-overview":
            if not self._require_platform_internal_admin(identity, "operations overview"):
                return
            try:
                period_days = int(query.get("period_days", ["30"])[0])
            except (TypeError, ValueError):
                period_days = 30
            self._send_json(
                {"operations_overview": self.repository.platform_operations_overview(period_days=period_days)}
            )
            return

        if len(parts) == 3 and parts[0] == "owner" and parts[1] == "operations":
            if not self._require_platform_internal_admin(identity, "operations detail"):
                return
            try:
                period_days = int(query.get("period_days", ["30"])[0])
                limit = int(query.get("limit", ["25"])[0])
                detail = self.repository.platform_operations_detail(
                    section=parts[2],
                    period_days=period_days,
                    cursor=query.get("cursor", [""])[0],
                    limit=limit,
                    status=query.get("status", [""])[0],
                    category=query.get("category", [""])[0],
                    plan=query.get("plan", [""])[0],
                    module=query.get("module", [""])[0],
                    event=query.get("event", [""])[0],
                    result=query.get("result", [""])[0],
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"operations_detail": detail})
            return

        if path == "billing/domestic/contract":
            contract = build_wechat_pay_native_contract()
            acceptance = self.repository.domestic_payment_acceptance_evidence()
            self._send_json(
                {
                    "domestic_billing": {
                        "provider": contract["provider"],
                        "checkout_mode": contract["checkout_mode"],
                        "billing_mode": contract["billing_mode"],
                        "status": (
                            "available"
                            if contract["real_checkout_ready"]
                            else "controlled_acceptance_proven"
                            if acceptance.get("controlled_acceptance_proven")
                            else "not_open"
                        ),
                        "rehearsal_order_supported": contract["rehearsal_order_supported"],
                        "real_checkout_ready": contract["real_checkout_ready"],
                        "charge_now_allowed": contract["charge_now_allowed"],
                        "controlled_acceptance_proven": bool(acceptance.get("controlled_acceptance_proven")),
                        "verified_paid_order_count": int(acceptance.get("verified_paid_order_count") or 0),
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    }
                }
            )
            return

        if path == "billing/domestic/orders":
            orders = self.repository.list_domestic_billing_orders(
                company_id=identity["company_id"],
                limit=_query_limit(query, default=20, maximum=100) or 20,
            )
            self._send_json(
                {
                    "domestic_billing_orders": [merchant_domestic_billing_order(order) for order in orders],
                    "secret_exposed": False,
                }
            )
            return

        if path == "billing/domestic/operations":
            if not self._require_permission(identity, "manage_billing"):
                return
            self._send_json(
                {
                    "domestic_billing_operations": build_domestic_billing_operations_snapshot(
                        self.repository,
                        company_id=identity["company_id"],
                    )
                }
            )
            return

        if len(parts) == 4 and parts[:3] == ["billing", "domestic", "orders"]:
            order = self.repository.get_domestic_billing_order(company_id=identity["company_id"], order_id=parts[3])
            if not order:
                self._send_error(HTTPStatus.NOT_FOUND, "domestic billing order not found")
                return
            self._send_json({"domestic_billing_order": merchant_domestic_billing_order(order), "secret_exposed": False})
            return

        if path == "billing/usage":
            self._send_json({"billing_usage": build_billing_usage(self.settings, self.repository, company_id=identity["company_id"])})
            return

        if path == "billing/media-credits":
            self._send_json(
                {
                    "media_credits": build_media_credit_summary(
                        self.repository,
                        company_id=identity["company_id"],
                        limit=_query_limit(query, default=30, maximum=100) or 30,
                    )
                }
            )
            return

        if path == "billing/manual-beta/orders":
            self._send_json(
                {
                    "manual_beta_payment_orders": list_manual_beta_payment_orders(
                        self.repository,
                        company_id=identity["company_id"],
                        limit=_query_limit(query, default=20, maximum=100) or 20,
                    ),
                    "manual_beta_payment_flow": {
                        "private_beta_only": True,
                        "amount_cny": 99,
                        "duration_days": 30,
                        "plan_key": "starter",
                        "manual_reconciliation_required": True,
                        "qr_code_in_repository": False,
                        "triggers_real_charge": False,
                        "frontend_gets_payment_secret": False,
                        "secret_exposed": False,
                    },
                }
            )
            return

        if path == "model/value-gate":
            self._send_json({"model_value_gate": build_model_value_gate(self.settings, self.repository)})
            return

        if path == "model/providers/catalog":
            self._send_json({"model_provider_catalog": build_model_provider_catalog()})
            return

        if path == "commercial/launch-gate":
            self._send_json({"commercial_launch_gate": build_commercial_launch_gate(self.settings, self.repository)})
            return

        if path == "post-publish/cockpit":
            execution_results = self.repository.list_execution_results(company_id=identity["company_id"], limit=100)
            confirmations = self.repository.list_confirmations(company_id=identity["company_id"], limit=100)
            audit_logs = self.repository.list_audit_logs(company_id=identity["company_id"], limit=80)
            self._send_json(
                {
                    "post_publish_cockpit": build_post_publish_cockpit(
                        execution_results=execution_results,
                        confirmations=confirmations,
                        audit_logs=audit_logs,
                    )
                }
            )
            return

        if path == "domain/status":
            self._send_json({"domain_status": build_domain_readiness(self.settings)})
            return

        if path == "provider-job-contracts":
            if not self._require_platform_internal_admin(identity, "provider job contracts"):
                return
            self._send_json({"provider_job_contracts": build_provider_job_contract_catalog()})
            return

        if path == "controlled-bridges":
            if not self._require_platform_internal_admin(identity, "controlled bridges"):
                return
            self._send_json({"controlled_bridges": build_controlled_bridge_contract(self.settings, self.repository)})
            return

        if path == "vault/targets":
            if not self._require_platform_internal_admin(identity, "vault targets"):
                return
            self._send_json({"vault_targets": self.secret_store_boundary.targets()})
            return

        if path == "vault/adapters":
            if not self._require_platform_internal_admin(identity, "vault adapters"):
                return
            self._send_json({"vault_adapters": self.secret_store_boundary.adapter_contract()})
            return

        if path == "vault/client-contract":
            if not self._require_platform_internal_admin(identity, "vault client contract"):
                return
            self._send_json({"vault_client": build_vault_client_contract(self.settings)})
            return

        if path == "vault/secret-resolver/status":
            if not self._require_platform_internal_admin(identity, "vault secret resolver status"):
                return
            self._send_json({"vault_secret_resolver": build_vault_secret_resolver_status(self.settings)})
            return

        if path == "secret-refs":
            store_id = query.get("store_id", [None])[0]
            self._send_json({"secret_refs": self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)})
            return

        if path == "security/staging-gate":
            store_id = query.get("store_id", [None])[0]
            if store_id:
                store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
                if not store:
                    self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                    return
            self._send_json(
                {
                    "staging_security_gate": build_controlled_staging_security_gate(
                        self.settings,
                        self.repository,
                        project_root=Path(__file__).resolve().parents[1],
                        company_id=identity["company_id"],
                        store_id=store_id,
                    )
                }
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "model" and parts[3] == "settings":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            settings = public_model_settings_from_secret_refs(
                self._model_settings_secret_refs_for_store(identity=identity, store_id=store_id)
            )
            settings["platform_trial_quota"] = self._platform_model_trial_quota(identity=identity)
            self._send_json({"model_settings": settings})
            return

        if path == "merchant-memory":
            store_id = query.get("store_id", [None])[0]
            memory_type = query.get("memory_type", [None])[0]
            limit = _query_limit(query, default=50, maximum=200) or 50
            self._send_json(
                {
                    "merchant_memory": self.repository.list_merchant_memory(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        memory_type=memory_type,
                        limit=limit,
                    )
                }
            )
            return

        if path == "ai-ceo/chat-history":
            limit = _query_limit(query, default=30, maximum=50) or 30
            turns = self.repository.list_ai_ceo_chat_history(
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                limit=limit,
            )
            revision = self.repository.ai_ceo_chat_history_revision(
                company_id=identity["company_id"],
                user_id=identity["user_id"],
            )
            self._send_json(
                {
                    "ai_ceo_chat_history": {
                        "scope": "account",
                        "cross_store": True,
                        "turns": turns,
                        "turn_count": len(turns),
                        "revision": revision,
                        "sync_contract": "2026-07-11-ai-ceo-cross-device-revision-v1",
                        "raw_provider_secret_stored": False,
                        "frontend_gets_model_api_key": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    }
                }
            )
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "merchant-ceo" and parts[3] == "commands" and parts[4] == "latest":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            command = self.repository.get_latest_merchant_ceo_command(company_id=identity["company_id"], store_id=store_id)
            self._send_json(
                {
                    "merchant_ceo_command": command,
                    "command": command.get("command") if isinstance(command, dict) else None,
                    "source_record": command.get("source_record") if isinstance(command, dict) else None,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                }
            )
            return

        if path == "connections":
            store_id = query.get("store_id", [None])[0]
            self._send_json({"connections": self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)})
            return

        if len(parts) == 3 and parts[0] == "stores" and parts[2] == "account-health":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            self._send_json(
                {
                    "account_health": build_account_health_snapshot(
                        self.repository,
                        company_id=identity["company_id"],
                        store_id=store_id,
                    )
                }
            )
            return

        if path == "oauth/requests":
            store_id = query.get("store_id", [None])[0]
            self._send_json({"oauth_requests": self.repository.list_oauth_authorization_requests(company_id=identity["company_id"], store_id=store_id)})
            return

        if path == "ebay-read-only/catalog":
            self._send_json({"ebay_read_only_catalog": self.ebay_read_adapter.resource_catalog()})
            return

        if path == "ebay-read-only/field-contracts":
            self._send_json({"ebay_read_only_field_contracts": build_field_contract_catalog()})
            return

        if path == "ebay-read-only/normalizers":
            self._send_json({"ebay_read_only_normalizers": normalizer_catalog()})
            return

        if path == "ebay-read-only/live-adapter/status":
            self._send_json({"ebay_live_read_adapter": build_live_read_adapter_status(self.settings)})
            return

        if path == "ebay-read-only/http-client/status":
            self._send_json({"ebay_http_client": build_ebay_http_client_contract(self.settings)})
            return
        if path == "ebay-oauth/local-token-store/status":
            self._send_json({"local_oauth_token_store": build_local_oauth_token_store_status(self.settings)})
            return

        if path == "ebay-write/adapter/status":
            self._send_json({"ebay_write_adapter": build_ebay_write_adapter_contract(self.settings)})
            return

        if path == "execution/adapters":
            self._send_json(
                {
                    "execution_adapters": {
                        "ebay_write_adapter": build_ebay_write_adapter_contract(self.settings),
                        "real_platform_writes_enabled": False,
                    }
                }
            )
            return

        if path == "data-packets":
            store_id = query.get("store_id", [None])[0]
            platform = query.get("platform", [None])[0]
            limit = _query_limit(query, default=None, maximum=50)
            self._send_json(
                {
                    "data_packets": self.repository.list_platform_data_packets(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        platform=platform,
                        limit=limit,
                    )
                }
            )
            return

        if len(parts) == 2 and parts[0] == "data-packets":
            packet = self.repository.get_platform_data_packet(company_id=identity["company_id"], packet_id=parts[1])
            if not packet:
                self._send_error(HTTPStatus.NOT_FOUND, "data packet not found")
                return
            self._send_json({"data_packet": packet})
            return

        if path == "ip-risk-screening":
            store_id = query.get("store_id", [None])[0]
            packet_id = query.get("packet_id", [None])[0]
            if not store_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "store_id is required")
                return
            self._send_json(
                {
                    "ip_risk_screening": build_ip_logo_brand_screening(
                        self.repository,
                        company_id=identity["company_id"],
                        store_id=store_id,
                        packet_id=packet_id,
                    )
                }
            )
            return

        if path == "tasks":
            store_id = query.get("store_id", [None])[0]
            limit = _query_limit(query, default=None, maximum=100)
            self._send_json({"tasks": self.repository.list_tasks(company_id=identity["company_id"], store_id=store_id, limit=limit)})
            return

        if path == "queue-jobs":
            status = query.get("status", [None])[0]
            limit = _query_limit(query, default=100, maximum=200) or 100
            self._send_json({"queue_jobs": self.repository.list_queue_jobs(company_id=identity["company_id"], status=status, limit=limit)})
            return

        if path == "media-asset-jobs":
            store_id = query.get("store_id", [None])[0]
            status = query.get("status", [None])[0]
            limit = _query_limit(query, default=100, maximum=200) or 100
            self._send_json(
                {
                    "media_asset_jobs": self.repository.list_media_asset_jobs(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        status=status,
                        limit=limit,
                    ),
                    "secret_exposed": False,
                }
            )
            return

        if len(parts) == 2 and parts[0] == "media-asset-jobs":
            media_job = self.repository.get_media_asset_job(company_id=identity["company_id"], media_job_id=parts[1])
            if not media_job:
                self._send_error(HTTPStatus.NOT_FOUND, "media asset job not found")
                return
            self._send_json({"media_asset_job": media_job, "secret_exposed": False})
            return

        if path == "queue/health":
            stale_after = _query_limit(query, default=900, maximum=86400) or 900
            self._send_json({"queue_health": self.repository.queue_health_summary(company_id=identity["company_id"], stale_after_seconds=stale_after)})
            return

        if len(parts) == 2 and parts[0] == "tasks":
            task = self.repository.get_task(company_id=identity["company_id"], task_id=parts[1])
            if not task:
                self._send_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            self._send_json({"task": task})
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "steps":
            task = self.repository.get_task(company_id=identity["company_id"], task_id=parts[1])
            if not task:
                self._send_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            self._send_json({"task_id": parts[1], "steps": self.repository.list_task_steps(company_id=identity["company_id"], task_id=parts[1])})
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "provider-job-plan":
            task = self.repository.get_task(company_id=identity["company_id"], task_id=parts[1])
            if not task:
                self._send_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            steps = self.repository.list_task_steps(company_id=identity["company_id"], task_id=parts[1])
            self._send_json({"provider_job_plan": build_provider_workflow_plan(task=task, steps=steps)})
            return

        if len(parts) == 3 and parts[0] == "stores" and parts[2] == "media-asset-jobs":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            status = query.get("status", [None])[0]
            limit = _query_limit(query, default=100, maximum=200) or 100
            self._send_json(
                {
                    "media_asset_jobs": self.repository.list_media_asset_jobs(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        status=status,
                        limit=limit,
                    ),
                    "secret_exposed": False,
                }
            )
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "secret-grant-plan":
            task = self.repository.get_task(company_id=identity["company_id"], task_id=parts[1])
            if not task:
                self._send_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            steps = self.repository.list_task_steps(company_id=identity["company_id"], task_id=parts[1])
            provider_job_plan = build_provider_workflow_plan(task=task, steps=steps)
            store_id = task.get("store_id")
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            self._send_json(
                {
                    "secret_grant_plan": build_task_secret_grant_plan(
                        task=task,
                        provider_job_plan=provider_job_plan,
                        secret_refs=secret_refs,
                        connections=connections,
                        vault_status=self.secret_store_boundary.status(),
                    )
                }
            )
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "timeline":
            try:
                self._send_json({"timeline": self.repository.task_timeline(company_id=identity["company_id"], task_id=parts[1])})
            except KeyError:
                self._send_error(HTTPStatus.NOT_FOUND, "task not found")
            return

        if path == "reports":
            task_id = query.get("task_id", [None])[0]
            limit = _query_limit(query, default=None, maximum=100)
            self._send_json({"reports": self.repository.list_reports(company_id=identity["company_id"], task_id=task_id, limit=limit)})
            return

        if path == "confirmations":
            status = query.get("status", [None])[0]
            limit = _query_limit(query, default=None, maximum=100)
            self._send_json({"confirmations": self.repository.list_confirmations(company_id=identity["company_id"], status=status, limit=limit)})
            return

        if path == "execution-results":
            limit = _query_limit(query, default=None, maximum=100)
            self._send_json({"execution_results": self.repository.list_execution_results(company_id=identity["company_id"], limit=limit)})
            return

        if path == "audit-logs":
            limit = int(query.get("limit", ["100"])[0] or 100)
            self._send_json({"audit_logs": self.repository.list_audit_logs(company_id=identity["company_id"], limit=limit)})
            return

        self._send_error(HTTPStatus.NOT_FOUND, "endpoint not found")

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post()
        except RequestBodyError as exc:
            self._send_error(exc.status, exc.message)
        except Exception as exc:
            if self._handle_service_dependency_exception(exc):
                return
            raise

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        parts = [unquote(part) for part in path.split("/")] if path else []

        if path == "analytics/events":
            body = self._read_json_body()
            if not self._check_public_analytics_rate_limit():
                return
            try:
                event = sanitize_analytics_event(body)
                if not event.get("event_id_hash"):
                    raise ValueError("analytics event id is required")
                self.repository.record_platform_analytics_event(**event)
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(
                {
                    "accepted": True,
                    "raw_ip_stored": False,
                    "user_agent_stored": False,
                    "raw_url_stored": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if path.startswith("auth/qr-login"):
            self._send_error(HTTPStatus.NOT_FOUND, "QR login is not an active Jiejing login path")
            return

        if path == "auth/demo-session":
            if not self._demo_session_bootstrap_allowed():
                self._send_error(
                    HTTPStatus.FORBIDDEN,
                    "demo session bootstrap is disabled unless local_dev/test or an explicit operator bootstrap secret is configured",
                )
                return
            body = self._read_json_body()
            if self.settings.environment in {"local_dev", "test"}:
                email = str(body.get("email") or "demo@jiejing.local")
                password = str(body.get("password") or "jiejing-demo-password")
                company_name = str(body.get("company_name") or "Jiejing Local Demo Company")
            else:
                email = str(body.get("email") or "")
                password = str(body.get("password") or "")
                company_name = str(body.get("company_name") or "Jiejing Operator Workspace")
                if not email or not password:
                    self._send_error(HTTPStatus.BAD_REQUEST, "operator bootstrap requires explicit email and password")
                    return
            if not self._check_auth_rate_limit(path, {"email": email}):
                return
            created = False
            try:
                user = self.repository.authenticate_user(email=email, password=password)
                company = self.repository.get_company(user["default_company_id"])
            except ValueError:
                try:
                    record = self.repository.create_user_with_company(email=email, password=password, company_name=company_name)
                except sqlite_unique_error():
                    self._send_error(HTTPStatus.UNAUTHORIZED, "demo user exists but password does not match")
                    return
                user = record["user"]
                company = record["company"]
                created = True
            token = self._issue_session_token(
                user_id=user["user_id"],
                company_id=user["default_company_id"],
                email=user["email"],
            )
            self._send_json(
                {
                    "token": token,
                    "user": user,
                    "company": company,
                    "created": created,
                    "demo_only": True,
                    "secret_exposed": False,
                },
                status=HTTPStatus.CREATED,
                headers=[("set-cookie", self._session_cookie_header(token))],
            )
            return

        if path == "auth/register":
            body = self._read_json_body()
            if not self._check_auth_rate_limit(path, body):
                return
            try:
                record = self.repository.create_user_with_company(
                    email=str(body.get("email") or ""),
                    password=str(body.get("password") or ""),
                    company_name=str(body.get("company_name") or "Jiejing Demo Company"),
                )
                user = record["user"]
                token = self._issue_session_token(
                    user_id=user["user_id"],
                    company_id=user["default_company_id"],
                    email=user["email"],
                )
                requested_plan = str(body.get("plan_key") or "free").strip().lower()
                if requested_plan == "free":
                    billing_trial = {
                        "ok": True,
                        "status": "free_plan_active",
                        "plan_key": "free",
                        "creates_real_checkout_session": False,
                        "calls_stripe_api": False,
                        "triggers_real_charge": False,
                        "secret_exposed": False,
                    }
                else:
                    try:
                        billing_trial = apply_test_billing_event(
                            self.repository,
                            company_id=user["default_company_id"],
                            user_id=user["user_id"],
                            plan_key=requested_plan,
                            action="activate",
                        )
                    except Exception as exc:  # pragma: no cover - defensive onboarding guardrail
                        billing_trial = {
                            "ok": False,
                            "status": "billing_trial_activation_skipped",
                            "reason": str(exc.__class__.__name__),
                            "creates_real_checkout_session": False,
                            "calls_stripe_api": False,
                            "triggers_real_charge": False,
                            "secret_exposed": False,
                        }
                challenge_verification = verify_registration_challenge(
                    body.get("trial_activation_challenge")
                    if isinstance(body.get("trial_activation_challenge"), dict)
                    else None,
                    environment=self.settings.environment,
                    remote_ip=self._client_ip_for_rate_limit(),
                )
                platform_trial_activation = self._platform_trial_activation_for_registration(
                    user=user,
                    challenge_verification=challenge_verification,
                )
                if platform_trial_activation.get("platform_trial_allowed") is True:
                    media_welcome = self.repository.apply_media_credit_operation(
                        company_id=user["default_company_id"],
                        user_id=user["user_id"],
                        operation_type="grant",
                        points=300,
                        idempotency_key="account-welcome-media-points-v1",
                        reference_type="onboarding",
                        reference_id="account_welcome",
                        details={"reason": "new_account_product_trial"},
                    )
                else:
                    media_welcome = {
                        "status": "platform_trial_activation_required",
                        "account": self.repository.get_media_credit_account(company_id=user["default_company_id"]),
                        "points_granted": 0,
                        "merchant_byok_unaffected": True,
                        "triggers_real_charge": False,
                        "secret_exposed": False,
                    }
                analytics_input = body.get("analytics") if isinstance(body.get("analytics"), dict) else {}
                try:
                    signup_event = sanitize_analytics_event(
                        {
                            **analytics_input,
                            "event_key": "signup_completed",
                            "page_key": "register",
                            "event_id": analytics_input.get("event_id") or f"signup-completed:{user['user_id']}",
                        }
                    )
                    self.repository.record_platform_analytics_event(
                        **signup_event,
                        company_id=user["default_company_id"],
                        user_id=user["user_id"],
                    )
                except (TypeError, ValueError):
                    pass
            except sqlite_unique_error() as exc:
                self._send_error(HTTPStatus.CONFLICT, "account registration could not be completed")
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(
                {
                    "token": token,
                    **record,
                    "billing_trial": billing_trial,
                    "media_welcome": media_welcome,
                    "platform_trial_activation": platform_trial_activation,
                    "secret_exposed": False,
                },
                status=HTTPStatus.CREATED,
                headers=[("set-cookie", self._session_cookie_header(token))],
            )
            return

        if path == "owner/auth/login":
            body = self._read_json_body()
            if not self._check_auth_rate_limit("auth/login", body):
                return
            try:
                user = self.repository.authenticate_user(
                    email=str(body.get("email") or ""),
                    password=str(body.get("password") or ""),
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.UNAUTHORIZED, str(exc))
                return
            preflight_identity = {
                "user_id": user["user_id"],
                "company_id": user["default_company_id"],
                "email": user["email"],
            }
            if not self._is_platform_internal_admin(preflight_identity):
                self._send_error(HTTPStatus.FORBIDDEN, "operations console is platform-internal admin only")
                return
            token = self._issue_session_token(
                user_id=user["user_id"],
                company_id=user["default_company_id"],
                email=user["email"],
            )
            self._send_json(
                {
                    "ok": True,
                    "platform_internal_admin": True,
                    "token_returned_to_frontend": False,
                    "secret_exposed": False,
                },
                headers=[("set-cookie", self._session_cookie_header(token))],
            )
            return

        if path == "auth/login":
            body = self._read_json_body()
            if not self._check_auth_rate_limit(path, body):
                return
            try:
                user = self.repository.authenticate_user(email=str(body.get("email") or ""), password=str(body.get("password") or ""))
                token = self._issue_session_token(
                    user_id=user["user_id"],
                    company_id=user["default_company_id"],
                    email=user["email"],
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.UNAUTHORIZED, str(exc))
                return
            self._send_json(
                {"token": token, "user": user, "secret_exposed": False},
                headers=[("set-cookie", self._session_cookie_header(token))],
            )
            return

        if path == "auth/logout":
            token = self._request_session_token()
            session_revoked = False
            if token:
                try:
                    identity = self.sessions.verify_token(token)
                    self.repository.ensure_user_session(identity)
                    session_revoked = self.repository.revoke_user_session(
                        jti=str(identity.get("jti") or ""),
                        user_id=str(identity.get("user_id") or ""),
                    )
                except ValueError:
                    session_revoked = False
            self._send_json(
                {"ok": True, "session_revoked": session_revoked, "secret_exposed": False},
                headers=[("set-cookie", self._expired_session_cookie_header())],
            )
            return

        if path == "auth/switch-company":
            body = self._read_json_body()
            identity = self._require_auth()
            if identity is None:
                return
            company_id = str(body.get("company_id") or "")
            member = self.repository.get_team_member(company_id=company_id, user_id=identity["user_id"])
            if not member:
                self._send_error(HTTPStatus.FORBIDDEN, "user is not a member of that company")
                return
            user = self.repository.get_user(identity["user_id"])
            if not user:
                self._send_error(HTTPStatus.UNAUTHORIZED, "user not found")
                return
            token = self._issue_session_token(user_id=user["user_id"], company_id=company_id, email=user["email"])
            self._send_json(
                {"token": token, "company": self.repository.get_company(company_id), "team_member": member, "secret_exposed": False},
                headers=[("set-cookie", self._session_cookie_header(token))],
            )
            return

        if path == "oauth/ebay/callback":
            body = self._read_json_body()
            result = self._handle_ebay_oauth_callback(
                state=str(body.get("state") or ""),
                code=str(body.get("code") or ""),
                error=str(body.get("error") or ""),
            )
            self._send_json({"oauth_callback": result}, status=self._oauth_callback_http_status(result))
            return

        if path == "monitoring/cls/callback":
            # Tencent CLS alarm callback endpoint. Body is intentionally ignored:
            # alarms are operational signals, not trusted product commands.
            length = int(self.headers.get("content-length") or "0")
            if length:
                self.rfile.read(min(length, 65536))
            self._send_json({"ok": True, "source": "cls_alarm_callback", "secret_exposed": False})
            return

        if path == "billing/webhook":
            length = int(self.headers.get("content-length") or "0")
            if length > MAX_JSON_BODY_BYTES:
                self._send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "webhook body too large")
                return
            raw_body = self.rfile.read(length) if length else b""
            result = handle_billing_webhook(raw_body=raw_body, headers=dict(self.headers.items()))
            if result.get("ok") and isinstance(result.get("event"), dict):
                result = {
                    **result,
                    "persistence": self.repository.apply_billing_webhook_event(event=result["event"]),
                    "payload_persisted": True,
                    "raw_payload_persisted": False,
                }
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400))
            self._send_json({"billing_webhook": result}, status=status)
            return

        if path == "billing/domestic/wechat-pay/notify":
            if not self._check_expensive_api_rate_limit(method="POST", path=path):
                return
            content_type = str(self.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json({"code": "FAIL", "message": "invalid request"}, status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                length = int(self.headers.get("content-length") or "0")
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > MAX_JSON_BODY_BYTES:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_JSON_BODY_BYTES else HTTPStatus.BAD_REQUEST
                self._send_json({"code": "FAIL", "message": "invalid request"}, status=status)
                return
            result = process_wechat_pay_notification_from_env(
                self.repository,
                raw_body=self.rfile.read(length),
                headers=dict(self.headers.items()),
            )
            if result.get("ok"):
                self._send_json({"code": "SUCCESS", "message": "成功", "secret_exposed": False})
            else:
                self._send_json(
                    {"code": "FAIL", "message": "payment notification rejected", "secret_exposed": False},
                    status=HTTPStatus(int(result.get("http_status") or 400)),
                )
            return

        if path == "billing/domestic/wechat-pay/refund-notify":
            if not self._check_expensive_api_rate_limit(method="POST", path=path):
                return
            content_type = str(self.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_json({"code": "FAIL", "message": "invalid request"}, status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                length = int(self.headers.get("content-length") or "0")
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > MAX_JSON_BODY_BYTES:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > MAX_JSON_BODY_BYTES else HTTPStatus.BAD_REQUEST
                self._send_json({"code": "FAIL", "message": "invalid request"}, status=status)
                return
            result = process_wechat_pay_refund_notification_from_env(
                self.repository,
                raw_body=self.rfile.read(length),
                headers=dict(self.headers.items()),
            )
            if result.get("ok"):
                self._send_json({"code": "SUCCESS", "message": "成功", "secret_exposed": False})
            else:
                self._send_json(
                    {"code": "FAIL", "message": "refund notification rejected", "secret_exposed": False},
                    status=HTTPStatus(int(result.get("http_status") or 400)),
                )
            return

        if path == "webhooks/ebay/marketplace-account-deletion":
            if not self._check_expensive_api_rate_limit(method="POST", path=path):
                return
            content_type = str(self.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "account deletion notification must be application/json")
                return
            try:
                length = int(self.headers.get("content-length") or "0")
            except (TypeError, ValueError):
                self._send_error(HTTPStatus.BAD_REQUEST, "account deletion notification body is invalid")
                return
            if length <= 0 or length > 65536:
                status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if length > 65536 else HTTPStatus.BAD_REQUEST
                self._send_error(status, "account deletion notification body is invalid")
                return
            raw_body = self.rfile.read(length)
            signature_header = str(self.headers.get("x-ebay-signature") or "")
            try:
                event = normalize_notification(raw_body=raw_body, signature_header=signature_header)
            except AccountDeletionError as exc:
                status = HTTPStatus.PRECONDITION_FAILED if exc.code == "invalid_signature_header" else HTTPStatus.BAD_REQUEST
                self._send_error(status, "account deletion notification is invalid")
                return
            verification = self.ebay_account_deletion_signature_verifier.verify(
                raw_body=raw_body,
                signature_header=signature_header,
            )
            if verification.get("verified") is not True:
                status = HTTPStatus.SERVICE_UNAVAILABLE if verification.get("retryable") else HTTPStatus.PRECONDITION_FAILED
                self._send_error(status, "account deletion notification could not be verified")
                return
            accepted = self.repository.accept_ebay_account_deletion_event(event=event)
            if accepted.get("status") == "idempotency_conflict":
                self._send_error(HTTPStatus.CONFLICT, "account deletion notification conflicts with a prior delivery")
                return
            job_id = str(accepted.get("job_id") or "")
            company_id = str(accepted.get("company_id") or "")
            if job_id and company_id:
                queue_job = self.repository.get_queue_job(company_id=company_id, job_id=job_id) or {}
                if queue_job.get("status") in {"completed", "cancelled"}:
                    queue_job = {}
                queue_job_body = queue_job.get("job") if isinstance(queue_job.get("job"), dict) else {}
                prior_dispatches = [
                    update.get("queue_dispatch")
                    for update in queue_job_body.get("updates", [])
                    if isinstance(update, dict) and isinstance(update.get("queue_dispatch"), dict)
                ]
                already_published = any(item.get("status") == "published" for item in prior_dispatches)
                if queue_job and not already_published:
                    dispatch = publish_redis_queue_job_if_configured(queue_job)
                    if dispatch.get("required") and dispatch.get("status") != "published":
                        self._send_error(HTTPStatus.SERVICE_UNAVAILABLE, "account deletion notification queue is unavailable")
                        return
                    if dispatch.get("status") == "published":
                        self.repository.update_queue_job(
                            job_id=job_id,
                            company_id=company_id,
                            status="queued",
                            details={"queue_dispatch": dispatch},
                        )
            self._send_json(
                {
                    "accepted": True,
                    "status": accepted.get("status"),
                    "duplicate": bool(accepted.get("duplicate")),
                    "matched_connection": bool(accepted.get("matched_connection")),
                    "raw_payload_persisted": False,
                    "real_platform_write_performed": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if not self._check_expensive_api_rate_limit(method="POST", path=path):
            return

        identity = self._require_auth()
        if identity is None:
            return

        if path == "product-feedback":
            if not self._check_product_feedback_rate_limit(identity):
                return
            body = self._read_json_body()
            idempotency_key = body.get("idempotency_key")
            if not isinstance(idempotency_key, str):
                self._send_error(HTTPStatus.BAD_REQUEST, "product feedback idempotency key must be text")
                return
            try:
                receipt = self.repository.create_product_feedback(
                    company_id=str(identity["company_id"]),
                    user_id=str(identity["user_id"]),
                    idempotency_key=idempotency_key,
                    payload={key: value for key, value in body.items() if key != "idempotency_key"},
                    store_id=None,
                )
            except ProductFeedbackIdempotencyConflict as exc:
                self._send_error(HTTPStatus.CONFLICT, str(exc))
                return
            except KeyError:
                self._send_error(HTTPStatus.FORBIDDEN, "access denied")
                return
            except (ProductFeedbackValidationError, ValueError) as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(
                {
                    "product_feedback": receipt,
                    "delivered": True,
                    "external_provider_action_triggered": False,
                    "real_platform_write_performed": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.OK if receipt.get("duplicate_request") is True else HTTPStatus.CREATED,
            )
            return

        if path in {"owner/product-feedback/review", "owner/product-feedback/resolve"}:
            if not self._require_platform_internal_admin(identity, "product feedback operation"):
                return
            body = self._read_json_body()
            feedback_id = body.get("feedback_id")
            if set(body) != {"feedback_id"} or not isinstance(feedback_id, str) or not feedback_id.strip():
                self._send_error(HTTPStatus.BAD_REQUEST, "feedback_id is required")
                return
            target_status = "reviewing" if path.endswith("/review") else "resolved"
            try:
                receipt = self.repository.transition_product_feedback_status(
                    feedback_id=feedback_id.strip(),
                    actor_user_id=str(identity["user_id"]),
                    target_status=target_status,
                )
            except KeyError:
                self._send_error(HTTPStatus.NOT_FOUND, "product feedback not found")
                return
            except ProductFeedbackStatusConflict as exc:
                self._send_error(HTTPStatus.CONFLICT, str(exc))
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(
                {
                    "product_feedback": receipt,
                    "external_provider_action_triggered": False,
                    "real_platform_write_performed": False,
                    "secret_exposed": False,
                }
            )
            return

        if path == "merchant-onboarding/primary-ebay/progress":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            expected_version = body.get("expected_version")
            if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
                self._send_error(HTTPStatus.BAD_REQUEST, "expected_version must be a non-negative integer")
                return
            existing = self.repository.get_merchant_onboarding_state(company_id=identity["company_id"])
            _, _, _, store = self._merchant_onboarding_context(identity, progress=existing)
            try:
                saved = self.repository.upsert_merchant_onboarding_state(
                    company_id=identity["company_id"],
                    user_id=identity["user_id"],
                    progress=body,
                    expected_version=expected_version,
                    store_id=str((store or {}).get("store_id") or "") or None,
                )
            except MerchantOnboardingValidationError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except (ValueError, KeyError) as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except MerchantOnboardingVersionConflict as exc:
                self._send_json(
                    {"merchant_onboarding": self._merchant_onboarding_read_model(identity, progress=exc.latest)},
                    status=HTTPStatus.CONFLICT,
                )
                return
            self._send_json({"merchant_onboarding": self._merchant_onboarding_read_model(identity, progress=saved)})
            return

        if path == "owner/operations-reliability-alerts/reconcile":
            if not self._require_platform_internal_admin(identity, "operations reliability alerts"):
                return
            monitoring_snapshot = self.repository.provider_monitoring_snapshot(
                reliability_window_minutes=30,
                cost_window_hours=24,
            )
            reliability = monitoring_snapshot.get("reliability")
            reliability = reliability if isinstance(reliability, dict) else {}
            alerts = reliability.get("alerts")
            alerts = alerts if isinstance(alerts, dict) else {}
            lifecycle = self.repository.reconcile_provider_reliability_alerts(
                alert_summary=alerts,
                actor_user_id=str(identity.get("user_id") or ""),
            )
            self._send_json(
                {
                    "reliability_alert_lifecycle": lifecycle,
                    "reliability_evaluation_window_minutes": int(
                        monitoring_snapshot.get("reliability_window_minutes") or 30
                    ),
                    "operations_overview": self.repository.platform_operations_overview(),
                    "real_platform_writes_enabled": False,
                    "external_provider_action_triggered": False,
                    "secret_exposed": False,
                }
            )
            return

        if path == "owner/operations-reliability-alerts/acknowledge":
            if not self._require_platform_internal_admin(identity, "operations reliability alerts"):
                return
            body = self._read_json_body()
            try:
                acknowledgement = self.repository.acknowledge_provider_reliability_alert(
                    scope=str(body.get("scope") or ""),
                    actor_user_id=str(identity.get("user_id") or ""),
                    action_key=str(body.get("action_key") or ""),
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if acknowledgement.get("ok") is not True:
                self._send_error(HTTPStatus.CONFLICT, "reliability alert is not open")
                return
            self._send_json(
                {
                    "reliability_alert_acknowledgement": acknowledgement,
                    "operations_overview": self.repository.platform_operations_overview(),
                    "real_platform_writes_enabled": False,
                    "external_provider_action_triggered": False,
                    "secret_exposed": False,
                }
            )
            return

        if len(parts) == 3 and parts[0] == "stores" and parts[2] == "media-source-assets":
            if not self._require_permission(identity, "create_task"):
                return
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            content = self._read_media_source_body()
            try:
                asset, source_url = self.media_source_asset_store.create(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    content_type=str(self.headers.get("content-type") or ""),
                    filename=unquote(str(self.headers.get("x-jiejing-file-name") or "source-image")),
                    content=content,
                )
            except MediaSourceAssetError as exc:
                status = {
                    "file_too_large": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "tenant_upload_quota_exceeded": HTTPStatus.TOO_MANY_REQUESTS,
                }.get(exc.code, HTTPStatus.BAD_REQUEST)
                self._send_error(status, str(exc))
                return
            self._send_json(
                {
                    "media_source_asset": asset.public_dict(source_url=source_url),
                    "provider_reference_ready": True,
                    "requires_asset_review": True,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 3 and parts[0] == "media-asset-jobs" and parts[2] == "review":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            decision = str(body.get("decision") or "").strip().lower()
            if decision not in {"approve_for_listing_draft", "needs_rework"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "media review decision must be approve_for_listing_draft or needs_rework")
                return
            media_job = self.repository.get_media_asset_job(company_id=identity["company_id"], media_job_id=parts[1])
            if not media_job:
                self._send_error(HTTPStatus.NOT_FOUND, "media asset job not found")
                return
            manifest = media_job.get("asset_manifest") if isinstance(media_job.get("asset_manifest"), list) else []
            if not manifest:
                self._send_error(HTTPStatus.BAD_REQUEST, "media asset job has no asset manifest to review")
                return
            live_provider_called = media_job.get("live_provider_called") is True
            real_asset_references = [
                str(item.get("url_or_file_path") or item.get("url") or item.get("file_path") or "").strip()
                for item in manifest
                if isinstance(item, dict)
            ]
            has_only_reviewable_asset_references = bool(real_asset_references) and all(
                reference.startswith("https://") for reference in real_asset_references
            )
            video_assets_present = any(
                "video" in str(item.get("asset_type") or item.get("type") or "").lower()
                or str(item.get("url_or_file_path") or item.get("url") or "").lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov"))
                for item in manifest
                if isinstance(item, dict)
            )
            confirmations = {
                "fact_consistency_confirmed": body.get("fact_consistency_confirmed") is True,
                "commercial_rights_confirmed": body.get("commercial_rights_confirmed") is True,
                "platform_rules_checked": body.get("platform_rules_checked") is True,
                "motion_and_usage_consistency_confirmed": body.get("motion_and_usage_consistency_confirmed") is True,
            }
            job_spec = media_job.get("job", {}).get("job_spec", {}) if isinstance(media_job.get("job"), dict) else {}
            job_inputs = job_spec.get("inputs") if isinstance(job_spec.get("inputs"), dict) else {}
            creative_job_spec = job_inputs.get("creative_job_spec") if isinstance(job_inputs.get("creative_job_spec"), dict) else {}
            product_fact_gate = media_job.get("product_fact_gate") if isinstance(media_job.get("product_fact_gate"), dict) else {}
            concept_only = creative_job_spec.get("output_safety_mode") == "concept_reference_only"
            missing_fact_keys = product_fact_gate.get("missing_fact_keys") if isinstance(product_fact_gate.get("missing_fact_keys"), list) else []
            if decision == "approve_for_listing_draft" and (not live_provider_called or not has_only_reviewable_asset_references):
                self._send_error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "素材服务没有返回可核验的真实文件，本次结果不能审核或回写 Listing",
                )
                return
            if decision == "approve_for_listing_draft" and (concept_only or "reference_images_or_source_notes" in missing_fact_keys):
                self._send_error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    "concept reference needs a real product source image before Listing draft approval",
                )
                return
            required_confirmations = [
                confirmations["fact_consistency_confirmed"],
                confirmations["commercial_rights_confirmed"],
                confirmations["platform_rules_checked"],
            ]
            if video_assets_present:
                required_confirmations.append(confirmations["motion_and_usage_consistency_confirmed"])
            if decision == "approve_for_listing_draft" and not all(required_confirmations):
                self._send_error(HTTPStatus.BAD_REQUEST, "all media review confirmations are required before Listing draft approval")
                return
            reviewed = self.repository.update_media_asset_job(
                company_id=identity["company_id"],
                media_job_id=parts[1],
                status="approved_for_listing" if decision == "approve_for_listing_draft" else "needs_rework",
                details={
                    "event": "merchant_media_review",
                    "decision": decision,
                    "reviewed_by": identity["user_id"],
                    "confirmations": confirmations,
                    "note": str(body.get("note") or "")[:300],
                    "triggers_real_platform_write": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                review_update={
                    "contract_version": "2026-07-11-media-review-v2",
                    "decision": decision,
                    "confirmations": confirmations,
                    "reviewed_by": identity["user_id"],
                    "note": str(body.get("note") or "")[:300],
                    "listing_draft_only": True,
                    "triggers_real_platform_write": False,
                    "secret_exposed": False,
                },
            )
            self._send_json(
                {
                    "media_asset_job": reviewed,
                    "review": {
                        "decision": decision,
                        "listing_draft_writeback_allowed": decision == "approve_for_listing_draft",
                        "triggers_real_platform_write": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                }
            )
            return

        if path == "billing/checkout-session":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = create_stripe_checkout_session(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                plan_key=str(body.get("plan_key") or ""),
                success_url=str(body.get("success_url") or ""),
                cancel_url=str(body.get("cancel_url") or ""),
            )
            self._send_json(
                {"billing_checkout": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if path == "billing/customer-portal":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = create_stripe_customer_portal_session(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                return_url=str(body.get("return_url") or ""),
            )
            self._send_json(
                {"billing_customer_portal": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if path == "billing/test-event":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = apply_test_billing_event(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                plan_key=str(body.get("plan_key") or "starter"),
                action=str(body.get("action") or "activate"),
            )
            self._send_json(
                {"billing_test_event": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if path == "billing/provider-rehearsal":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = run_billing_provider_rehearsal(
                self.settings,
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                plan_key=str(body.get("plan_key") or "starter"),
                action=str(body.get("action") or "activate"),
            )
            self._send_json(
                {"billing_provider_rehearsal": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if path == "billing/domestic/orders":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            payment_contract = build_wechat_pay_native_contract()
            live_checkout = payment_contract.get("charge_now_allowed") is True
            result = create_domestic_billing_order(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                provider=str(body.get("provider") or "wechat_pay_native"),
                plan_key=str(body.get("plan_key") or "starter"),
                idempotency_key=str(self.headers.get("idempotency-key") or ""),
                rehearsal=not live_checkout,
            )
            if result.get("ok") and live_checkout:
                result = open_domestic_billing_checkout(
                    self.repository,
                    company_id=identity["company_id"],
                    order_id=str(result.get("order_id") or ""),
                )
            if result.get("ok") is True:
                result = merchant_domestic_billing_order(result, include_checkout=live_checkout)
            self._send_json(
                {"domestic_billing_order": result},
                status=(
                    HTTPStatus.OK
                    if result.get("ok") and result.get("duplicate_request")
                    else HTTPStatus.CREATED
                    if result.get("ok")
                    else HTTPStatus(int(result.get("http_status") or 400))
                ),
            )
            return

        if path == "billing/domestic/reconcile":
            if not self._require_permission(identity, "manage_billing"):
                return
            if not self._check_domestic_reconciliation_rate_limit(identity):
                return
            body = self._read_json_body()
            order_ids = body.get("order_ids") if isinstance(body.get("order_ids"), list) else []
            result = reconcile_domestic_billing_orders(
                self.repository,
                company_id=identity["company_id"],
                order_ids=order_ids,
            )
            self._send_json(
                {"domestic_billing_reconciliation": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "checkout":
            if not self._require_permission(identity, "manage_billing"):
                return
            payment_contract = build_wechat_pay_native_contract()
            if payment_contract.get("charge_now_allowed") is not True:
                self._send_json(
                    {"domestic_billing_order": {"ok": False, "status": "blocked", "reason": "domestic_real_checkout_not_enabled", "secret_exposed": False}},
                    status=HTTPStatus.CONFLICT,
                )
                return
            result = open_domestic_billing_checkout(
                self.repository,
                company_id=identity["company_id"],
                order_id=parts[3],
            )
            safe_result = merchant_domestic_billing_order(result, include_checkout=True) if result.get("ok") is True else result
            self._send_json(
                {"domestic_billing_order": safe_result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "close":
            if not self._require_permission(identity, "manage_billing"):
                return
            result = close_domestic_billing_order(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                order_id=parts[3],
            )
            self._send_json(
                {"domestic_billing_order_close": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "query":
            if not self._require_permission(identity, "manage_billing"):
                return
            if not self._check_domestic_reconciliation_rate_limit(identity):
                return
            result = query_and_reconcile_domestic_billing_order(
                self.repository,
                company_id=identity["company_id"],
                order_id=parts[3],
            )
            self._send_json(
                {"domestic_billing_order_query": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "refund-request":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = request_domestic_billing_refund_review(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                order_id=parts[3],
                reason=str(body.get("reason") or ""),
            )
            self._send_json(
                {"domestic_billing_refund_request": result},
                status=HTTPStatus.ACCEPTED if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "refund-execute":
            if not self._require_permission(identity, "manage_billing"):
                return
            if not self._require_permission(identity, "approve_high_risk"):
                return
            if not self._check_domestic_reconciliation_rate_limit(identity):
                return
            result = execute_approved_domestic_billing_refund(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                order_id=parts[3],
            )
            self._send_json(
                {"domestic_billing_refund_execution": result},
                status=HTTPStatus.ACCEPTED if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 5 and parts[:3] == ["billing", "domestic", "orders"] and parts[4] == "refund-query":
            if not self._require_permission(identity, "manage_billing"):
                return
            if not self._check_domestic_reconciliation_rate_limit(identity):
                return
            result = query_and_reconcile_domestic_billing_refund(
                self.repository,
                company_id=identity["company_id"],
                order_id=parts[3],
            )
            self._send_json(
                {"domestic_billing_refund_query": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if path == "billing/manual-beta/orders":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = create_manual_beta_payment_order(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                plan_key=str(body.get("plan_key") or "starter"),
            )
            self._send_json(
                {"manual_beta_payment_order": result},
                status=HTTPStatus.CREATED if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 4 and parts[0] == "billing" and parts[1] == "manual-beta" and parts[2] == "orders" and parts[3].endswith("confirm"):
            self._send_error(HTTPStatus.NOT_FOUND, "manual beta confirmation route is /billing/manual-beta/orders/{order_id}/confirm")
            return

        if len(parts) == 5 and parts[0] == "billing" and parts[1] == "manual-beta" and parts[2] == "orders" and parts[4] == "confirm":
            if not self._require_permission(identity, "manage_billing"):
                return
            body = self._read_json_body()
            result = confirm_manual_beta_payment_order(
                self.repository,
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                order_id=parts[3],
                internal_admin=self._is_platform_internal_admin(identity),
                received_amount_cny=body.get("received_amount_cny") or 0,
                payment_reference=str(body.get("payment_reference") or ""),
            )
            self._send_json(
                {"manual_beta_payment_confirmation": result},
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus(int(result.get("http_status") or 400)),
            )
            return

        if len(parts) == 3 and parts[0] == "stores" and parts[2] in {"publish-confirmation", "ebay-draft-confirmation"}:
            body = self._read_json_body()
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=parts[1])
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found")
                return
            draft_save_intake = parts[2] == "ebay-draft-confirmation"
            action_type = "save_ebay_listing_draft" if draft_save_intake else "publish_listing"
            intake_source = "merchant_ebay_draft_save_intake" if draft_save_intake else "merchant_listing_publish_intake"
            latest_packets = self.repository.list_platform_data_packets(
                company_id=identity["company_id"],
                store_id=parts[1],
                platform="ebay",
                limit=1,
            )
            packet = latest_packets[0].get("packet") if latest_packets and isinstance(latest_packets[0].get("packet"), dict) else {}
            publish_payload = _publish_confirmation_payload_from_body(
                body=body,
                packet=packet,
                marketplace_id=str(store.get("marketplace") or body.get("marketplace_id") or "EBAY_US"),
            )
            account_health = build_account_health_snapshot(
                self.repository,
                company_id=identity["company_id"],
                store_id=parts[1],
            )
            publish_payload = merge_account_health_into_payload(publish_payload, account_health)
            raw_project_identity = body.get("listing_project_identity") if isinstance(body.get("listing_project_identity"), dict) else {}
            listing_project_identity = {
                "key": _safe_publish_text(raw_project_identity.get("key"), limit=160),
                "product": _safe_publish_text(raw_project_identity.get("product"), limit=160),
                "source_id": _safe_publish_text(raw_project_identity.get("source_id"), limit=160),
                "candidate_id": _safe_publish_text(raw_project_identity.get("candidate_id"), limit=120),
                "secret_exposed": False,
            }
            task_title = _safe_publish_text(
                body.get("product")
                or publish_payload.get("listing", {}).get("title")
                or publish_payload.get("listing", {}).get("sku")
                or ("Fresh eBay draft save confirmation" if draft_save_intake else "Fresh eBay publish confirmation"),
                limit=120,
            )
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=parts[1],
                user_id=identity["user_id"],
                task_type="ebay_draft_save_intake" if draft_save_intake else "publish_confirmation_intake",
                title=(f"eBay draft save intake · {task_title}" if draft_save_intake else f"Publish confirmation intake · {task_title}"),
                input_data={
                    "product": task_title,
                    "source": intake_source,
                    "packet_id": latest_packets[0].get("packet_id") if latest_packets else None,
                    "listing_project_identity": listing_project_identity,
                    "secret_exposed": False,
                },
            )
            execution_request = ExecutionRequest(
                action_type=action_type,
                task_id=task["task_id"],
                user_id=identity["user_id"],
                company_id=identity["company_id"],
                store_id=parts[1],
                platform="ebay",
                payload=publish_payload,
                confirmation_id=None,
                confirmed_by=None,
                confirmed_at=None,
                idempotency_key=str(
                    body.get("idempotency_key")
                    or (f"ebay-draft-intake-{task['task_id']}" if draft_save_intake else f"publish-intake-{task['task_id']}")
                ),
            )
            preflight = ExecutionService(demo_mode=True).preflight(execution_request)
            latest_execution_results = self.repository.list_execution_results(company_id=identity["company_id"], limit=100)
            recent_confirmations = self.repository.list_confirmations(company_id=identity["company_id"], limit=100)
            readiness = build_publish_readiness(
                publish_payload,
                preflight=preflight,
                latest_execution_results=latest_execution_results,
                recent_confirmations=recent_confirmations,
            )
            confirmation = self.repository.create_confirmation(
                company_id=identity["company_id"],
                store_id=parts[1],
                task_id=task["task_id"],
                runtime_run_id="merchant_ebay_draft_save_intake" if draft_save_intake else "merchant_publish_confirmation_intake",
                action_type=action_type,
                title=(f"保存到 eBay 草稿确认 · {task_title}" if draft_save_intake else f"发布确认 · {task_title}"),
                item={
                    "source": intake_source,
                    "reason": (
                        "商家希望先把完整商品资料保存为 eBay 未发布草稿；这仍会写入卖家账号，必须由确认中心批准。"
                        if draft_save_intake
                        else "商家从捷境 Listing 页面录入全新商品；真实发布必须先看发布体检报告，再由确认中心批准。"
                    ),
                    "expected_result": (
                        "后端只创建或更新 Inventory Item 和未发布 Offer，不调用 publishOffer，也不产生公开 Listing。"
                        if draft_save_intake
                        else "通过发布体检后，后端执行服务才可用 eBay Inventory API 发布；失败会写入审计和平台规则记忆。"
                    ),
                    "publish_payload": publish_payload,
                    "publish_payload_summary": _publish_payload_summary(publish_payload),
                    "listing_project_identity": listing_project_identity,
                    "publish_readiness": readiness,
                    "account_health": account_health,
                    "preflight_status": preflight.get("status"),
                    "source_packet_id": latest_packets[0].get("packet_id") if latest_packets else None,
                    "high_risk": True,
                    "writes_to_ebay_after_approval": self.settings.effective_real_platform_writes_enabled,
                    "creates_public_listing": False if draft_save_intake else self.settings.effective_real_platform_writes_enabled,
                    "requires_publish_offer_call": False if draft_save_intake else self.settings.effective_real_platform_writes_enabled,
                    "frontend_gets_token": False,
                    "runtime_gets_token": False,
                },
                created_by=identity["user_id"],
                default_action="hold",
            )
            self._send_json(
                {
                    "task": task,
                    "confirmation": confirmation,
                    "preflight": preflight,
                    "publish_readiness": readiness,
                    "account_health": account_health,
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                    "secret_exposed": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if path == "stores":
            if not self._require_permission(identity, "manage_store"):
                return
            if not self._require_quota(identity, "connected_store"):
                return
            body = self._read_json_body()
            store = self.repository.create_store(company_id=identity["company_id"], user_id=identity["user_id"], payload=body)
            self._send_json({"store": store}, status=HTTPStatus.CREATED)
            return

        if path == "team/invitations":
            if not self._require_permission(identity, "manage_team"):
                return
            body = self._read_json_body()
            try:
                invite = self.repository.create_team_invitation(
                    company_id=identity["company_id"],
                    invited_by=identity["user_id"],
                    email=str(body.get("email") or ""),
                    role=str(body.get("role") or "viewer"),
                    metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
                )
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"team_invitation": invite, "real_platform_writes_enabled": False}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "stores" and parts[2] == "connections":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            try:
                connection = self.repository.create_platform_connection(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    payload=body,
                )
            except KeyError:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found")
                return
            self._send_json({"connection": connection}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "platforms" and parts[4] == "connection-plan":
            body = self._read_json_body()
            store_id = parts[1]
            platform_key = parts[3]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            plan = build_platform_connection_plan(
                platform_key=platform_key,
                store=store,
                requested_mode=str(body.get("connection_mode") or "") or None,
            )
            status = HTTPStatus.NOT_FOUND if plan.get("status") == "unsupported_platform" else HTTPStatus.CREATED
            self._send_json({"connection_plan": plan, "real_platform_writes_enabled": False}, status=status)
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "vault" and parts[3] == "secret-ref-plan":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            plan = self.secret_store_boundary.build_secret_reference_plan(
                payload=body,
                store=store,
                user_id=identity["user_id"],
            )
            secret_ref = self.repository.create_secret_reference(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                provider=str(plan["provider"]),
                purpose=str(plan["purpose"]),
                status=str(plan["status"]),
                metadata=plan,
            )
            self._send_json(
                {
                    "secret_ref_plan": plan,
                    "secret_ref": secret_ref,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "vault" and parts[4] == "resolve-plan":
            body = self._read_json_body()
            store_id = parts[1]
            secret_ref_id = parts[3]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            secret_ref = self.repository.get_secret_ref(company_id=identity["company_id"], store_id=store_id, secret_ref=secret_ref_id)
            plan = self.secret_store_boundary.build_secret_resolution_plan(
                secret_ref=secret_ref,
                requested_by=str(body.get("requested_by") or "backend_adapter"),
                task_scope=str(body.get("task_scope") or "product_workflow_read_only"),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="vault.secret_resolve.plan",
                target_type="secret_ref",
                target_id=secret_ref_id,
                summary="Vault secret resolution plan evaluated. Raw secret was not read or returned.",
                details=plan,
            )
            self._send_json(
                {
                    "secret_resolution_plan": plan,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "vault" and parts[4] == "client-resolve-contract":
            body = self._read_json_body()
            store_id = parts[1]
            secret_ref_id = parts[3]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            secret_ref = self.repository.get_secret_ref(company_id=identity["company_id"], store_id=store_id, secret_ref=secret_ref_id)
            plan = build_task_secret_resolution_contract(
                settings=self.settings,
                secret_ref=secret_ref,
                requested_by=str(body.get("requested_by") or "backend_adapter"),
                task_scope=str(body.get("task_scope") or "ebay_read_only"),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="vault.client_resolve.contract",
                target_type="secret_ref",
                target_id=secret_ref_id,
                summary="Vault client resolve contract evaluated. No raw secret was read or returned.",
                details=plan,
            )
            self._send_json(
                {
                    "vault_client_resolution": plan,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "vault" and parts[4] == "rotation-plan":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            secret_ref_id = parts[3]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            secret_ref = self.repository.get_secret_ref(company_id=identity["company_id"], store_id=store_id, secret_ref=secret_ref_id)
            member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
            plan = self.secret_store_boundary.build_secret_rotation_plan(
                secret_ref=secret_ref,
                requested_by=str(member.get("role") if member else "viewer"),
                reason=str(body.get("reason") or "routine_rotation"),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="user",
                action_type="vault.secret_rotation.plan",
                target_type="secret_ref",
                target_id=secret_ref_id,
                summary="Vault secret rotation plan evaluated. Raw secret was not read or returned.",
                details=plan,
            )
            self._send_json(
                {
                    "secret_rotation_plan": plan,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 5 and parts[0] == "stores" and parts[2] == "vault" and parts[4] == "revoke-plan":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            secret_ref_id = parts[3]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            secret_ref = self.repository.get_secret_ref(company_id=identity["company_id"], store_id=store_id, secret_ref=secret_ref_id)
            member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
            plan = self.secret_store_boundary.build_secret_revoke_plan(
                secret_ref=secret_ref,
                requested_by=str(member.get("role") if member else "viewer"),
                reason=str(body.get("reason") or "security_or_disconnect"),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="user",
                action_type="vault.secret_revoke.plan",
                target_type="secret_ref",
                target_id=secret_ref_id,
                summary="Vault secret revoke plan evaluated. Raw secret was not read or returned.",
                details=plan,
            )
            self._send_json(
                {
                    "secret_revoke_plan": plan,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-oauth" and parts[3] == "read-only-plan":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_scopes = body.get("scopes") if isinstance(body.get("scopes"), list) else None
            plan = self.ebay_oauth_planner.read_only_authorization_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                marketplace_id=str(body.get("marketplace_id") or store.get("marketplace") or "EBAY_US"),
                requested_scopes=requested_scopes,
            )
            request_record = self.repository.create_oauth_authorization_request(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                plan=plan,
            )
            self._send_json(
                {
                    "oauth_plan": plan,
                    "oauth_request": request_record,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-oauth" and parts[3] == "publish-plan":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_scopes = body.get("scopes") if isinstance(body.get("scopes"), list) else None
            plan = self.ebay_oauth_planner.publish_authorization_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                marketplace_id=str(body.get("marketplace_id") or store.get("marketplace") or "EBAY_US"),
                requested_scopes=requested_scopes,
            )
            request_record = self.repository.create_oauth_authorization_request(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                plan=plan,
            )
            self._send_json(
                {
                    "oauth_plan": plan,
                    "oauth_request": request_record,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-oauth" and parts[3] == "refresh-plan":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id),
                connections=self.repository.list_connections(company_id=identity["company_id"], store_id=store_id),
                secret_store_status=self.secret_store_boundary.status(),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="oauth.token_refresh.plan",
                target_type="store",
                target_id=store_id,
                summary="eBay token refresh plan evaluated. No token was read, returned, or refreshed.",
                details=plan,
            )
            self._send_json(
                {
                    "token_refresh_plan": plan,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-oauth" and parts[3] == "refresh-execution-plan":
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            plan = self.ebay_oauth_planner.token_refresh_execution_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id),
                connections=self.repository.list_connections(company_id=identity["company_id"], store_id=store_id),
                secret_store_status=self.secret_store_boundary.status(),
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="oauth.token_refresh.execution_plan",
                target_type="store",
                target_id=store_id,
                summary="eBay token refresh execution plan evaluated. No secret was read and no token was refreshed.",
                details=plan,
            )
            self._send_json(
                {
                    "token_refresh_execution_plan": plan,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-oauth" and parts[3] == "refresh-now":
            if not self._require_permission(identity, "manage_connections"):
                return
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            secret_ref = next(
                (
                    item
                    for item in secret_refs
                    if str(item.get("provider") or "").lower() == "ebay"
                    and str(item.get("purpose") or "").lower() == "ebay_refresh_token"
                ),
                None,
            )
            refresh = EbayVaultTokenRefreshAdapter(self.settings).refresh_access_token_from_secret_ref(
                secret_ref=secret_ref,
                company_id=identity["company_id"],
                store_id=store_id,
                task_scope="merchant_visible_refresh_probe",
            )
            public_refresh = public_token_refresh_result(refresh)
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="oauth.token_refresh.executed",
                target_type="store",
                target_id=store_id,
                summary="eBay access token refresh executed through backend Vault-backed adapter. Token values were not returned or stored.",
                details=public_refresh,
            )
            status = HTTPStatus.OK if refresh.get("ok") else HTTPStatus.ACCEPTED
            self._send_json(
                {
                    "token_refresh": public_refresh,
                    "audit": audit,
                    "vault": self.secret_store_boundary.status(),
                    "real_platform_writes_enabled": False,
                },
                status=status,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "probe-plan":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            plan = self.ebay_read_adapter.build_probe_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.read_only.probe_plan",
                target_type="store",
                target_id=store_id,
                summary="eBay read-only probe plan evaluated. No live eBay read was performed.",
                details=plan,
            )
            self._send_json(
                {
                    "read_only_probe_plan": plan,
                    "token_refresh_plan": refresh_plan,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "workflow-plan":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            probe_plan = self.ebay_read_adapter.build_probe_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            workflow_plan = self.ebay_read_adapter.build_read_workflow_plan(probe_plan=probe_plan)
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.read_only.workflow_plan",
                target_type="store",
                target_id=store_id,
                summary="eBay read-only workflow plan evaluated. No live eBay read was performed.",
                details=workflow_plan,
            )
            self._send_json(
                {
                    "read_only_workflow_plan": workflow_plan,
                    "read_only_probe_plan": probe_plan,
                    "token_refresh_plan": refresh_plan,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "live-read-plan":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            live_read_plan = self.ebay_live_read_plan_builder.build_execution_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.read_only.live_read_plan",
                target_type="store",
                target_id=store_id,
                summary="eBay live read execution plan evaluated. No token was read and no live eBay request was performed.",
                details=live_read_plan,
            )
            self._send_json(
                {
                    "live_read_plan": live_read_plan,
                    "token_refresh_plan": refresh_plan,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "queue-read-job":
            if not self._require_permission(identity, "create_task"):
                return
            if not self._require_quota(identity, "official_ebay_sync"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            live_read_plan = self.ebay_live_read_plan_builder.build_execution_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                task_type="ebay_read_only_live_plan",
                title=f"eBay read-only official data plan: {store.get('store_name') or store_id}",
                input_data={
                    "resources": live_read_plan.get("resources_requested") or [],
                    "live_read_plan": live_read_plan,
                    "real_platform_writes_enabled": False,
                },
            )
            job = self.repository.create_queue_job(
                company_id=identity["company_id"],
                task_id=task["task_id"],
                job_data={
                    "kind": "ebay_read_only_live_plan",
                    "platform": "ebay",
                    "store_id": store_id,
                    "resources": live_read_plan.get("resources_requested") or [],
                    "live_read_plan": live_read_plan,
                    "live_read_performed": False,
                },
            )
            self._send_json(
                {
                    "task": task,
                    "queue_job": job,
                    "live_read_plan": live_read_plan,
                    "token_refresh_plan": refresh_plan,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "sync":
            if not self._require_permission(identity, "create_task"):
                return
            if not self._require_quota(identity, "official_ebay_sync"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            live_read_plan = self.ebay_live_read_plan_builder.build_execution_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            http_client_contract = build_ebay_http_client_contract(self.settings)
            credential_preflight = build_ebay_credential_preflight(
                settings=self.settings,
                store=store,
                secret_refs=secret_refs,
                connections=connections,
                requested_resources=requested_resources,
            )
            blocked_by = sorted(
                {
                    str(item)
                    for item in (
                        (live_read_plan.get("blocked_by") or [])
                        + (http_client_contract.get("blocked_by") or [])
                        + (credential_preflight.get("blocked_by") or [])
                    )
                }
            )
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                task_type="ebay_read_only_sync",
                title=f"同步 eBay 只读数据：{store.get('store_name') or store_id}",
                input_data={
                    "resources": live_read_plan.get("resources_requested") or [],
                    "live_read_plan": live_read_plan,
                    "http_client_contract": http_client_contract,
                    "credential_preflight": credential_preflight,
                    "real_platform_writes_enabled": False,
                },
            )
            if live_read_plan.get("status") != "ready_to_queue_live_read_job" or not credential_preflight.get("can_queue_sync") or blocked_by:
                blocked_output = {
                    "status": "blocked_before_queue",
                    "summary": "eBay 只读同步还不能执行。后端没有读取到可用的只读授权或运行开关，系统不会假装已经同步。",
                    "blocked_by": blocked_by,
                    "merchant_next_step": credential_preflight.get("merchant_next_step") or _merchant_next_step_for_ebay_sync_blockers(blocked_by),
                    "live_read_plan": live_read_plan,
                    "http_client_contract": http_client_contract,
                    "credential_preflight": credential_preflight,
                    "live_read_performed": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                }
                task = self.repository.update_task_status(
                    task_id=task["task_id"],
                    company_id=identity["company_id"],
                    status="blocked",
                    output=blocked_output,
                    audit_summary="eBay read-only sync blocked before queueing because preflight was incomplete.",
                )
                audit = self.repository.write_audit(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    actor_type="system",
                    action_type="ebay.read_only.sync.blocked",
                    target_type="task",
                    target_id=task["task_id"],
                    summary="eBay read-only sync blocked before queueing. No token was read and no live request was performed.",
                    details=blocked_output,
                )
                self._send_json(
                    {
                        "sync": blocked_output,
                        "credential_preflight": credential_preflight,
                        "task": task,
                        "queue_job": None,
                        "worker_result": None,
                        "audit": audit,
                        "real_platform_writes_enabled": False,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            job = self.repository.create_queue_job(
                company_id=identity["company_id"],
                task_id=task["task_id"],
                job_data={
                    "kind": "ebay_read_only_live_plan",
                    "platform": "ebay",
                    "store_id": store_id,
                    "resources": live_read_plan.get("resources_requested") or [],
                    "live_read_plan": live_read_plan,
                    "live_read_performed": False,
                    "run_mode": body.get("run_mode") or "queued",
                    "created_from": "ebay_read_only_sync",
                },
            )
            worker_result = None
            run_mode = str(body.get("run_mode") or "queued")
            if run_mode in {"inline", "enqueue_and_wait", "local_worker_now"}:
                worker_result = self.queue_worker.run_next(company_id=identity["company_id"], job_id=job["job_id"])
                task = worker_result.get("task") or self.repository.get_task(company_id=identity["company_id"], task_id=task["task_id"]) or task
                job = worker_result.get("queue_job") or self.repository.get_queue_job(job_id=job["job_id"], company_id=identity["company_id"]) or job
            self._send_json(
                {
                    "sync": {
                        "status": "queued" if worker_result is None else str(worker_result.get("status") or "completed"),
                        "summary": "eBay 只读同步已经进入后端队列。只有店铺、政策、Listing、订单、费用和类目字段会被读取，真实发布和改价仍然关闭。",
                        "merchant_next_step": "等待同步完成后，在数据包和工作记录里查看店铺政策、Listing、订单、费用和类目字段。",
                        "blocked_by": [],
                        "live_read_plan": live_read_plan,
                        "http_client_contract": http_client_contract,
                        "credential_preflight": credential_preflight,
                        "live_read_performed": bool(worker_result and worker_result.get("live_read_result", {}).get("live_read_performed")),
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                    "credential_preflight": credential_preflight,
                    "task": task,
                    "queue_job": job,
                    "worker_result": worker_result,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "credential-preflight":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            preflight = build_ebay_credential_preflight(
                settings=self.settings,
                store=store,
                secret_refs=self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id),
                connections=self.repository.list_connections(company_id=identity["company_id"], store_id=store_id),
                requested_resources=requested_resources,
            )
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.read_only.credential_preflight",
                target_type="store",
                target_id=store_id,
                summary="eBay credential preflight evaluated. No token or secret value was returned.",
                details=preflight,
            )
            self._send_json(
                {
                    "credential_preflight": preflight,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "http-client-dry-run":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            live_read_plan = self.ebay_live_read_plan_builder.build_execution_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            dry_run = build_http_dry_run_from_live_plan(settings=self.settings, live_read_plan=live_read_plan)
            audit = self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.read_only.http_client.dry_run",
                target_type="store",
                target_id=store_id,
                summary="eBay read-only HTTP client dry-run evaluated. No live eBay request was performed.",
                details=dry_run,
            )
            self._send_json(
                {
                    "http_client_dry_run": dry_run,
                    "live_read_plan": live_read_plan,
                    "token_refresh_plan": refresh_plan,
                    "audit": audit,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "ebay-read-only" and parts[3] == "data-packet":
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            requested_resources = body.get("resources") if isinstance(body.get("resources"), list) else None
            secret_refs = self.repository.list_secret_refs(company_id=identity["company_id"], store_id=store_id)
            connections = self.repository.list_connections(company_id=identity["company_id"], store_id=store_id)
            refresh_plan = self.ebay_oauth_planner.token_refresh_plan(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                secret_refs=secret_refs,
                connections=connections,
                secret_store_status=self.secret_store_boundary.status(),
            )
            probe_plan = self.ebay_read_adapter.build_probe_plan(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                requested_resources=requested_resources,
                secret_refs=secret_refs,
                connections=connections,
                token_refresh_plan=refresh_plan,
            )
            packet = build_ebay_read_only_data_packet(
                company_id=identity["company_id"],
                store=store,
                user_id=identity["user_id"],
                probe_plan=probe_plan,
                source_mode=str(body.get("source_mode") or "sample_payload"),
                sample_payload=body.get("sample_payload") if isinstance(body.get("sample_payload"), dict) else {},
            )
            stored_packet = self.repository.create_platform_data_packet(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                packet=packet,
            )
            self._send_json(
                {
                    "data_packet": stored_packet,
                    "read_only_probe_plan": probe_plan,
                    "token_refresh_plan": refresh_plan,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "provider-jobs" and parts[3] == "queue":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            catalog = build_provider_job_contract_catalog()
            contracts = {item.get("key"): item for item in catalog.get("contracts", [])}
            provider_job_key = str(body.get("provider_job_key") or body.get("contract_key") or "")
            contract = contracts.get(provider_job_key)
            if not contract:
                self._send_error(HTTPStatus.NOT_FOUND, "provider job contract not found")
                return
            raw_inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
            safe_inputs = _redact_secret_like(raw_inputs)
            is_media_provider_job = provider_job_key in MEDIA_PROVIDER_JOB_KEYS
            if not is_media_provider_job and not self._require_quota(identity, "provider_job"):
                return
            if is_media_provider_job:
                safe_inputs = _sanitize_media_source_inputs(safe_inputs)
            media_idempotency_key = ""
            media_credit_state: dict[str, Any] | None = None
            if is_media_provider_job:
                media_idempotency_key = _media_asset_idempotency_key(
                    store_id=store_id,
                    provider_job_key=provider_job_key,
                    inputs=safe_inputs,
                    supplied=body.get("idempotency_key"),
                )
                existing_media_job = self.repository.get_media_asset_job_by_idempotency(
                    company_id=identity["company_id"],
                    idempotency_key=media_idempotency_key,
                )
                if existing_media_job:
                    existing_task = self.repository.get_task(company_id=identity["company_id"], task_id=existing_media_job["task_id"])
                    existing_queue = None
                    if existing_media_job.get("queue_job_id"):
                        existing_queue = self.repository.get_queue_job(
                            job_id=existing_media_job["queue_job_id"],
                            company_id=identity["company_id"],
                        )
                    self._send_json(
                        {
                            "task": existing_task,
                            "queue_job": existing_queue,
                            "provider_job_contract": contract,
                            "worker_result": None,
                            "provider_job": (existing_task or {}).get("output") if isinstance((existing_task or {}).get("output"), dict) else None,
                            "media_asset_job": existing_media_job,
                            "idempotent_replay": True,
                            "real_platform_writes_enabled": False,
                            "secret_exposed": False,
                        },
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                media_quote = estimate_media_points(safe_inputs)
                media_credit_state = {
                    "quote": media_quote,
                    "enforcement_enabled": _env_bool("JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED"),
                    "reservation": None,
                    "provider_neutral": True,
                    "secret_exposed": False,
                }
                if media_credit_state["enforcement_enabled"] and bool(safe_inputs.get("live_provider_requested")):
                    try:
                        media_credit_state["reservation"] = self.repository.apply_media_credit_operation(
                            company_id=identity["company_id"],
                            user_id=identity["user_id"],
                            operation_type="reserve",
                            points=int(media_quote["estimated_points"]),
                            idempotency_key=f"{media_idempotency_key}:reserve:v1",
                            reference_type="media_job",
                            reference_id=media_idempotency_key,
                            details={"quote": media_quote},
                        )
                    except ValueError as exc:
                        if "insufficient" not in str(exc).lower():
                            raise
                        self._send_json(
                            {
                                "error": "素材点不足，当前任务没有进入生成队列。",
                                "status": int(HTTPStatus.PAYMENT_REQUIRED),
                                "media_credits": build_media_credit_summary(
                                    self.repository,
                                    company_id=identity["company_id"],
                                ),
                                "media_quote": media_quote,
                                "triggers_real_charge": False,
                                "secret_exposed": False,
                            },
                            status=HTTPStatus.PAYMENT_REQUIRED,
                        )
                        return
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                task_type="provider_job",
                title=str(body.get("title") or f"Provider job: {contract.get('label') or provider_job_key}"),
                input_data={
                    "provider_job_key": provider_job_key,
                    "provider_family": contract.get("provider_family"),
                    "store_id": store_id,
                    "inputs": safe_inputs,
                    "contract_version": catalog.get("contract_version"),
                    "media_asset_idempotency_key": media_idempotency_key,
                    "media_credits": media_credit_state,
                    "real_platform_writes_enabled": False,
                },
            )
            media_asset_job = None
            if is_media_provider_job:
                media_asset_job = self.repository.create_media_asset_job(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    task_id=task["task_id"],
                    user_id=identity["user_id"],
                    provider_job_key=provider_job_key,
                    idempotency_key=media_idempotency_key,
                    job_spec={
                        "provider_job_key": provider_job_key,
                        "contract_version": catalog.get("contract_version"),
                        "inputs": safe_inputs,
                        "merchant_visible_provider_name": False,
                        "live_media_provider_call_allowed": False,
                        "spend_now_allowed": False,
                        "media_credits": media_credit_state,
                        "secret_exposed": False,
                    },
                    status="pending",
                )
            max_attempts = int(contract.get("max_attempts") or 1)
            job = self.repository.create_queue_job(
                company_id=identity["company_id"],
                task_id=task["task_id"],
                max_attempts=max_attempts,
                job_data={
                    "kind": "provider_job",
                    "provider_job_key": provider_job_key,
                    "provider_family": contract.get("provider_family"),
                    "queue": contract.get("queue"),
                    "contract": contract,
                    "inputs": safe_inputs,
                    "secret_ref": str(body.get("secret_ref") or ""),
                    "media_job_id": media_asset_job.get("media_job_id") if media_asset_job else "",
                    "idempotency_key": media_idempotency_key,
                    "media_credits": media_credit_state,
                    "run_mode": body.get("run_mode") or "queued",
                    "live_provider_called": False,
                    "real_platform_writes_enabled": False,
                },
            )
            if media_asset_job:
                media_asset_job = self.repository.update_media_asset_job(
                    company_id=identity["company_id"],
                    media_job_id=media_asset_job["media_job_id"],
                    status="queued",
                    queue_job_id=job["job_id"],
                    details={
                        "message": "Media asset job linked to SaaS queue job.",
                        "queue": contract.get("queue"),
                        "live_provider_called": False,
                        "spend_now_allowed": False,
                        "secret_exposed": False,
                    },
                )
            worker_result = None
            run_mode = str(body.get("run_mode") or "queued")
            if run_mode in {"inline", "enqueue_and_wait", "local_worker_now"}:
                worker_result = self.queue_worker.run_next(company_id=identity["company_id"], job_id=job["job_id"])
                task = worker_result.get("task") or self.repository.get_task(company_id=identity["company_id"], task_id=task["task_id"]) or task
                job = worker_result.get("queue_job") or self.repository.get_queue_job(job_id=job["job_id"], company_id=identity["company_id"]) or job
                media_asset_job = worker_result.get("media_asset_job") if isinstance(worker_result, dict) else media_asset_job
                if not media_asset_job and is_media_provider_job:
                    media_asset_job = self.repository.get_media_asset_job_by_idempotency(
                        company_id=identity["company_id"],
                        idempotency_key=media_idempotency_key,
                    )
            self._send_json(
                {
                    "task": task,
                    "queue_job": job,
                    "provider_job_contract": contract,
                    "worker_result": worker_result,
                    "provider_job": worker_result.get("provider_job") if isinstance(worker_result, dict) else None,
                    "media_asset_job": media_asset_job,
                    "media_credits": media_credit_state,
                    "idempotent_replay": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "model" and parts[3] == "value-rehearsal":
            if not self._require_permission(identity, "create_task"):
                return
            if not self._require_quota(identity, "model_report_assist"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            model_client = None
            model_secret_resolution = self._resolve_model_client_for_store(identity=identity, store_id=store_id, body=body)
            if model_secret_resolution.get("status") == "blocked":
                self._send_json(
                    {
                        "model_value_rehearsal": {
                            "status": "blocked_before_model_rehearsal",
                            "blockers": model_secret_resolution.get("blocked_by") or [],
                            "model_secret_resolution": model_secret_resolution,
                            "runtime_gets_sanitized_packet_only": True,
                            "runtime_gets_raw_ebay_token": False,
                            "frontend_gets_model_api_key": False,
                            "real_platform_writes_enabled": False,
                            "secret_exposed": False,
                        },
                        "real_platform_writes_enabled": False,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            model_client = model_secret_resolution.get("model_client")
            rehearsal = run_model_value_rehearsal(
                settings=self.settings,
                repository=self.repository,
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                packet_id=str(body.get("packet_id") or "") or None,
                product=str(body.get("product") or store.get("store_name") or "eBay product from sanitized packet"),
                merchant_goal=str(body.get("merchant_goal") or "Prove Jiejing model-backed Market Report and Listing Package value."),
                allow_live_model=bool(body.get("allow_live_model") or model_client is not None),
                model_client=model_client,
            )
            status = HTTPStatus.CREATED if rehearsal.get("status") == "completed" else HTTPStatus.ACCEPTED
            self._send_json(
                {
                    "model_value_rehearsal": rehearsal,
                    "model_secret_resolution": {
                        key: value
                        for key, value in model_secret_resolution.items()
                        if key not in {"model_client", "secret_value"}
                    },
                    "real_platform_writes_enabled": False,
                },
                status=status,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "merchant-ceo" and parts[3] == "chat":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            command_body = body.get("command") if isinstance(body.get("command"), dict) else {}
            message = str(body.get("message") or command_body.get("text") or command_body.get("command_text") or "")
            route_meta = ai_ceo_route_metadata(message)
            stream_requested = str((query.get("stream") or [""])[0]).strip().lower() in {"1", "true", "yes", "on"}
            stream_started = False
            last_stream_stage = ""

            def send_chat_payload(payload: dict[str, Any], status: HTTPStatus) -> None:
                nonlocal stream_started
                if not stream_requested:
                    self._send_json(payload, status=status)
                    return
                if not stream_started:
                    self._start_ndjson_stream()
                    stream_started = True
                self._send_ndjson_event(
                    {
                        "type": "final",
                        "http_status": int(status),
                        "payload": payload,
                        "secret_exposed": False,
                    }
                )

            def emit_chat_stage(stage: str) -> None:
                nonlocal stream_started, last_stream_stage
                safe_stage = str(stage or "model").strip().lower()
                if safe_stage not in {"sources", "model"}:
                    safe_stage = "model"
                if not stream_requested or safe_stage == last_stream_stage:
                    return
                if not stream_started:
                    self._start_ndjson_stream()
                    stream_started = True
                last_stream_stage = safe_stage
                self._send_ndjson_event(
                    {
                        "type": "accepted",
                        "stage": safe_stage,
                        "route": route_meta.get("route") or "general_chat",
                        "secret_exposed": False,
                    }
                )

            def emit_text_delta(delta: str) -> None:
                safe_delta = str(delta or "")
                if not stream_requested or not safe_delta:
                    return
                emit_chat_stage("model")
                self._send_ndjson_event({"type": "delta", "delta": safe_delta, "secret_exposed": False})

            command_response = None
            if command_body:
                command_response = self.repository.save_merchant_ceo_command(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    command={**command_body, **route_meta},
                )
            fast_chat = run_ai_ceo_fast_turn(
                repository=self.repository,
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                message=message,
                client_now=str(body.get("client_now") or ""),
                client_timezone=str(body.get("client_timezone") or ""),
            )
            if fast_chat:
                if command_body and fast_chat.get("answer"):
                    command_response = self.repository.save_merchant_ceo_command(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        user_id=identity["user_id"],
                        command={
                            **command_body,
                            "ai_reply": fast_chat.get("answer"),
                            "ai_reply_status": fast_chat.get("status"),
                            "ai_reply_model": fast_chat.get("model_client"),
                            "route": fast_chat.get("route"),
                            "route_label": fast_chat.get("route_label"),
                            "memory_policy": fast_chat.get("memory_policy"),
                            "long_term_memory": fast_chat.get("long_term_memory"),
                            "writes_merchant_rule": fast_chat.get("writes_merchant_rule"),
                            "decision_center_required": fast_chat.get("decision_center_required"),
                        },
                    )
                task = self.repository.create_task(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    task_type="merchant_ceo_chat",
                    title="AI CEO fast chat turn",
                    input_data={
                        "message": message,
                        "command_id": (command_response or {}).get("command", {}).get("id") if isinstance(command_response, dict) else "",
                        "route": fast_chat.get("route"),
                        "route_label": fast_chat.get("route_label"),
                        "memory_policy": fast_chat.get("memory_policy"),
                        "decision_center_required": bool(fast_chat.get("decision_center_required")),
                        "model_secret_ref": "",
                        "provider_key": "fast_route",
                        "frontend_gets_model_api_key": False,
                        "runtime_gets_raw_ebay_token": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                )
                completed_statuses = {
                    "capability_status_answered",
                    "local_clock_answered",
                    "realtime_search_answered",
                    "realtime_search_answered_without_model",
                }
                self.repository.update_task_status(
                    task_id=task["task_id"],
                    company_id=identity["company_id"],
                    status="completed" if fast_chat.get("status") in completed_statuses else "blocked",
                    output={"ai_ceo_chat": fast_chat, "secret_exposed": False},
                    audit_summary="AI CEO fast chat turn completed before model secret resolution.",
                )
                ai_ceo_market_report = self.repository.save_ai_ceo_market_research_report(
                    task=task,
                    message=message,
                    chat=fast_chat,
                    command_id=(command_response or {}).get("command", {}).get("id") if isinstance(command_response, dict) else "",
                    conversation_history=body.get("conversation_history") if isinstance(body.get("conversation_history"), list) else [],
                )
                ai_ceo_market_report_delivery = build_ai_ceo_market_report_delivery(ai_ceo_market_report)
                send_chat_payload(
                    {
                        "ai_ceo_chat": fast_chat,
                        "merchant_ceo_command": command_response,
                        "ai_ceo_market_report": ai_ceo_market_report,
                        "ai_ceo_market_report_delivery": ai_ceo_market_report_delivery,
                        "model_secret_resolution": {
                            "status": "not_required_for_fast_route",
                            "frontend_gets_model_api_key": False,
                            "secret_exposed": False,
                        },
                        "frontend_gets_model_api_key": False,
                        "runtime_gets_raw_ebay_token": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.CREATED if fast_chat.get("status") in completed_statuses else HTTPStatus.ACCEPTED,
                )
                return
            model_secret_resolution = self._resolve_model_client_for_store(identity=identity, store_id=store_id, body=body)
            if model_secret_resolution.get("status") != "resolved":
                blockers = model_secret_resolution.get("blocked_by") or [model_secret_resolution.get("status") or "model_secret_not_resolved"]
                blocker_set = set(str(item) for item in blockers)
                if {"merchant_model_api_key_not_saved", "platform_model_default_not_configured"}.issubset(blocker_set):
                    blocked_answer = (
                        "AI CEO 这次还不能生成完整回复：当前账号还没有保存自己的 AI 连接，"
                        "捷境试用 AI 当前也未开通。你可以到设置里的 AI 与素材保存 DeepSeek/OpenAI 连接；"
                        "普通公开来源搜索已接入，但没有可用文本 AI 时不会冒充完整模型回答。"
                    )
                else:
                    blocked_answer = (
                        "AI 连接暂时不可用。这次没有拿到可展示回复。"
                        "你可以稍后重试，或到设置里的 AI 与素材查看连接状态；"
                        "不要重复保存连接信息，除非页面明确提示连接已失效。"
                    )
                send_chat_payload(
                    {
                        "ai_ceo_chat": {
                            "status": "blocked_before_model_chat",
                            "blocked_by": blockers,
                            "answer": blocked_answer,
                            **route_meta,
                            "model_secret_resolution": {
                                key: value
                                for key, value in model_secret_resolution.items()
                                if key not in {"model_client", "secret_value"}
                            },
                            "frontend_gets_model_api_key": False,
                            "runtime_gets_raw_ebay_token": False,
                            "secret_exposed": False,
                        },
                        "merchant_ceo_command": command_response,
                        "platform_model_resolution": model_secret_resolution.get("platform_model_resolution") or {},
                        "real_platform_writes_enabled": False,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            model_resolution_mode = str(model_secret_resolution.get("mode") or "")
            quota_action = (
                "model_report_assist"
                if model_resolution_mode == "platform_managed_default"
                else "ai_ceo_task"
            )
            if not self._require_quota(identity, quota_action):
                return
            if model_secret_resolution.get("mode") == "platform_managed_default":
                platform_trial_quota = self._platform_model_trial_quota(identity=identity)
                model_secret_resolution["platform_trial_quota"] = platform_trial_quota
                if not platform_trial_quota.get("allowed"):
                    trial_blocker = str(
                        platform_trial_quota.get("blocked_by") or "platform_default_model_trial_exhausted"
                    )
                    if trial_blocker == "platform_trial_activation_required":
                        trial_answer = (
                            "当前账号已注册，但捷境提供的 AI 试用尚未激活。"
                            "你仍可在设置中连接自己的 DeepSeek 或 OpenAI，连接后不占用捷境试用额度。"
                        )
                    else:
                        trial_answer = (
                            "当前账号本月的捷境 AI 试用额度已用完。"
                            "你可以在设置中连接自己的 DeepSeek 或 OpenAI，或升级套餐后继续使用。"
                        )
                    send_chat_payload(
                        {
                            "ai_ceo_chat": {
                                "status": "blocked_before_model_chat",
                                "blocked_by": [trial_blocker],
                                "answer": trial_answer,
                                **route_meta,
                                "model_secret_resolution": {
                                    key: value
                                    for key, value in model_secret_resolution.items()
                                    if key not in {"model_client", "secret_value"}
                                },
                                "platform_trial_quota": platform_trial_quota,
                                "frontend_gets_model_api_key": False,
                                "runtime_gets_raw_ebay_token": False,
                                "secret_exposed": False,
                            },
                            "merchant_ceo_command": command_response,
                            "model_secret_resolution": {
                                key: value
                                for key, value in model_secret_resolution.items()
                                if key not in {"model_client", "secret_value"}
                            },
                            "real_platform_writes_enabled": False,
                            "secret_exposed": False,
                        },
                        status=HTTPStatus.PAYMENT_REQUIRED,
                    )
                    return
            metered_model_client = MeteredModelClient(model_secret_resolution["model_client"])
            chat = run_ai_ceo_chat(
                repository=self.repository,
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                message=message,
                model_client=metered_model_client,
                client_now=str(body.get("client_now") or ""),
                client_timezone=str(body.get("client_timezone") or ""),
                command=command_body,
                conversation_history=body.get("conversation_history") if isinstance(body.get("conversation_history"), list) else [],
                model_resolution={
                    key: value
                    for key, value in model_secret_resolution.items()
                    if key not in {"model_client", "secret_value"}
                },
                on_stage=emit_chat_stage if stream_requested else None,
                on_text_delta=emit_text_delta if stream_requested else None,
            )
            if command_body and chat.get("answer"):
                command_response = self.repository.save_merchant_ceo_command(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    command={
                        **command_body,
                        "ai_reply": chat.get("answer"),
                        "ai_reply_status": chat.get("status"),
                        "ai_reply_model": chat.get("model_client"),
                        "route": chat.get("route"),
                        "route_label": chat.get("route_label"),
                        "memory_policy": chat.get("memory_policy"),
                        "long_term_memory": chat.get("long_term_memory"),
                        "writes_merchant_rule": chat.get("writes_merchant_rule"),
                        "decision_center_required": chat.get("decision_center_required"),
                    },
                )
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                task_type="merchant_ceo_chat",
                title="AI CEO chat turn",
                input_data={
                    "message": message,
                    "command_id": (command_response or {}).get("command", {}).get("id") if isinstance(command_response, dict) else "",
                    "route": chat.get("route"),
                    "route_label": chat.get("route_label"),
                    "memory_policy": chat.get("memory_policy"),
                    "decision_center_required": bool(chat.get("decision_center_required")),
                    "model_secret_ref": model_secret_resolution.get("secret_ref"),
                    "model_resolution_mode": model_secret_resolution.get("mode"),
                    "model_secret_ref_scope": model_secret_resolution.get("secret_ref_scope"),
                    "model_usage_owner": (
                        "merchant_account_byok"
                        if model_secret_resolution.get("merchant_pays_provider_directly")
                        else "jiejing_platform_trial"
                        if model_secret_resolution.get("mode") == "platform_managed_default"
                        else "unknown"
                    ),
                    "platform_trial_quota": model_secret_resolution.get("platform_trial_quota") or {},
                    "provider_key": model_secret_resolution.get("provider_key"),
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_raw_ebay_token": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
            )
            model_usage = metered_model_client.usage_summary()
            model_reliability = metered_model_client.reliability_summary()
            if model_usage.get("request_count"):
                usage_owner = (
                    "merchant_account_byok"
                    if model_secret_resolution.get("merchant_pays_provider_directly")
                    else "jiejing_platform_trial"
                    if model_secret_resolution.get("mode") == "platform_managed_default"
                    else "unknown"
                )
                cost_measurement = model_cost_measurement(usage_owner=usage_owner, usage=model_usage)
                try:
                    self.repository.record_model_usage(
                        company_id=identity["company_id"],
                        user_id=identity["user_id"],
                        task_id=task["task_id"],
                        usage_owner=usage_owner,
                        model_family=str(model_secret_resolution.get("provider_key") or "provider_neutral"),
                        model_label=str(model_secret_resolution.get("model") or getattr(metered_model_client, "model", "")),
                        request_count=int(model_usage.get("request_count") or 0),
                        input_tokens=int(model_usage.get("input_tokens") or 0),
                        output_tokens=int(model_usage.get("output_tokens") or 0),
                        total_tokens=int(model_usage.get("total_tokens") or 0),
                        cost_minor=int(cost_measurement.get("cost_minor") or 0),
                        currency=str(cost_measurement.get("currency") or "CNY"),
                        cost_status=str(cost_measurement.get("cost_status") or "unavailable"),
                        idempotency_key=f"{task['task_id']}:model-usage:v1",
                        details={
                            "provider_reported_tokens": bool(model_usage.get("total_tokens")),
                            "retry_calls_included": True,
                            "reliability": model_reliability,
                        },
                    )
                except Exception as exc:
                    self.repository.write_audit(
                        company_id=identity["company_id"],
                        store_id=store_id,
                        user_id=identity["user_id"],
                        actor_type="system",
                        action_type="operations.model_usage_metering.failed",
                        target_type="task",
                        target_id=task["task_id"],
                        summary="Model answer was preserved but internal usage metering did not persist.",
                        details={"error_type": exc.__class__.__name__, "secret_exposed": False},
                    )
            self.repository.update_task_status(
                task_id=task["task_id"],
                company_id=identity["company_id"],
                status="completed"
                if chat.get("status")
                in {
                    "capability_status_answered",
                    "model_answered",
                    "model_answered_non_live",
                    "local_clock_answered",
                    "realtime_search_answered",
                    "realtime_search_answered_without_model",
                    "source_backed_market_report_draft",
                    "market_report_recovery_draft",
                }
                else "blocked",
                output={"ai_ceo_chat": chat, "secret_exposed": False},
                audit_summary="AI CEO chat turn completed through backend model boundary.",
            )
            ai_ceo_market_report = self.repository.save_ai_ceo_market_research_report(
                task=task,
                message=message,
                chat=chat,
                command_id=(command_response or {}).get("command", {}).get("id") if isinstance(command_response, dict) else "",
                conversation_history=body.get("conversation_history") if isinstance(body.get("conversation_history"), list) else [],
            )
            ai_ceo_market_report_delivery = build_ai_ceo_market_report_delivery(ai_ceo_market_report)
            status = (
                HTTPStatus.CREATED
                if chat.get("status")
                in {
                    "capability_status_answered",
                    "model_answered",
                    "model_answered_non_live",
                    "local_clock_answered",
                    "realtime_search_answered",
                    "realtime_search_answered_without_model",
                    "source_backed_market_report_draft",
                    "market_report_recovery_draft",
                }
                else HTTPStatus.ACCEPTED
            )
            send_chat_payload(
                {
                    "ai_ceo_chat": chat,
                    "merchant_ceo_command": command_response,
                    "model_secret_resolution": {
                        key: value
                        for key, value in model_secret_resolution.items()
                        if key not in {"model_client", "secret_value"}
                    },
                    "ai_ceo_market_report": ai_ceo_market_report,
                    "ai_ceo_market_report_delivery": ai_ceo_market_report_delivery,
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_raw_ebay_token": False,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                status=status,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "model" and parts[3] == "api-key":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            provider_key = str(body.get("provider_key") or body.get("provider") or "")
            definition = get_model_provider(provider_key)
            if not definition:
                self._send_error(HTTPStatus.BAD_REQUEST, "unsupported model provider")
                return
            api_key = str(body.get("api_key") or "").strip()
            if len(api_key) < 8:
                self._send_error(HTTPStatus.BAD_REQUEST, "model api key is missing or too short")
                return
            model = str(body.get("model") or definition.default_model).strip() or definition.default_model
            raw_base_url = str(body.get("base_url") or "").strip().rstrip("/")
            base_url = normalize_model_api_base_url(provider_key=definition.provider_key, base_url=raw_base_url)
            if self.settings.is_production_like:
                expected_host = urlparse(definition.default_base_url).hostname or ""
                selected_host = urlparse(base_url).hostname or ""
                if selected_host.lower() != expected_host.lower():
                    self._send_json(
                        {
                            "error": "当前 AI 服务商只能使用捷境已核验的官方连接地址。",
                            "blocked_by": ["unapproved_model_base_url"],
                            "official_base_url": definition.default_base_url,
                            "secret_exposed": False,
                        },
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
            requested_scope = str(
                body.get("model_scope")
                or body.get("connection_scope")
                or body.get("scope")
                or "account"
            ).strip().lower()
            if requested_scope not in {"account", "store"}:
                self._send_error(HTTPStatus.BAD_REQUEST, "unsupported model connection scope")
                return
            model_connection_scope = requested_scope
            secret_store_id = store_id if model_connection_scope == "store" else None
            metadata = {
                "contract_version": "2026-07-03-merchant-account-byok-model-secret",
                "model_connection_scope": model_connection_scope,
                "scope": model_connection_scope,
                "store_context_id": store_id,
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "api_style": definition.api_style,
                "model": model,
                "base_url": base_url,
                "base_url_normalized": bool(raw_base_url and raw_base_url != base_url),
                "key_url": definition.key_url,
                "docs_url": definition.docs_url,
                "supported_live_adapter": definition.supported_live_adapter,
                "merchant_brings_own_key": True,
                "merchant_pays_provider_directly": True,
                "merchant_model_follows_account": model_connection_scope == "account",
                "jiejing_account_scoped_model_secret_ref": model_connection_scope == "account",
                "jiejing_store_scoped_model_secret_ref": model_connection_scope == "store",
                "jiejing_stores_only_secret_ref": model_connection_scope == "store",
                "frontend_gets_raw_key_after_save": False,
                "runtime_gets_raw_key": False,
                "reports_get_raw_key": False,
                "raw_key_stored_in_database": False,
                "secret_exposed": False,
            }
            secret_ref = self.repository.create_secret_reference(
                company_id=identity["company_id"],
                store_id=secret_store_id,
                user_id=identity["user_id"],
                provider=model_secret_provider(definition.provider_key),
                purpose=MODEL_SECRET_PURPOSE,
                status="pending_secret_storage",
                metadata=metadata,
            )
            resolver = VaultSecretResolver(self.settings)
            stored = resolver.store_secret(
                secret_ref=secret_ref,
                secret_value=api_key,
                created_by=identity["user_id"],
                metadata=metadata,
            )
            stored_status = str(stored.get("status") or "")
            storage_ready = stored_status in READY_MODEL_SECRET_STATUSES
            verification = (
                self._verify_model_connection_from_secret_value(
                    provider_key=definition.provider_key,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                )
                if storage_ready
                else {
                    "status": "not_run",
                    "verified": False,
                    "error_code": "model_secret_storage_failed",
                    "blocked_by": stored.get("blocked_by") or ["model_secret_storage_failed"],
                    "secret_exposed": False,
                }
            )
            verified = verification.get("verified") is True
            final_status = "ready" if verified else "stored_unverified" if storage_ready else stored_status or "store_blocked"
            secret_ref = self.repository.update_secret_reference_status(
                company_id=identity["company_id"],
                store_id=secret_store_id,
                secret_ref=str(secret_ref["secret_ref"]),
                status=final_status,
                user_id=identity["user_id"],
                metadata_patch={
                    "storage_adapter": stored.get("storage_adapter"),
                    "storage_status": stored_status,
                    "blocked_by": stored.get("blocked_by") or [],
                    "verification_status": "verified" if verified else "failed" if storage_ready else "not_run",
                    "verification_error_code": verification.get("error_code") or "",
                    "verification_blocked_by": verification.get("blocked_by") or [],
                    "verified_at": verification.get("verified_at") or "",
                    "managed_vault_write_performed": bool(stored.get("managed_vault_write_performed")),
                    "local_development_write_performed": bool(stored.get("local_development_write_performed")),
                    "secret_value_returned": False,
                    "secret_exposed": False,
                },
            )
            response = {
                "model_secret_ref": secret_ref,
                "model_settings": public_model_settings_from_secret_refs(
                    self._model_settings_secret_refs_for_store(identity=identity, store_id=store_id)
                ),
                "model_connection": {
                    "status": "ready" if verified else "verification_failed" if storage_ready else "storage_failed",
                    "verified": verified,
                    "requires_api_key_reentry": not storage_ready,
                    "can_retry_verification": storage_ready and not verified,
                    "blocked_by": verification.get("blocked_by") or stored.get("blocked_by") or [],
                    "verification_error_code": verification.get("error_code") or "",
                    "secret_exposed": False,
                },
                "model_connection_scope": model_connection_scope,
                "provider": definition.public_dict(),
                "storage": {
                    key: value
                    for key, value in stored.items()
                    if key not in {"secret_value"}
                },
                "frontend_gets_model_api_key": False,
                "runtime_gets_model_api_key": False,
                "reports_get_model_api_key": False,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            }
            if not storage_ready:
                response["error"] = "AI 连接没有保存成功，后端安全存储暂时不可用。"
                self._send_json(response, status=HTTPStatus.SERVICE_UNAVAILABLE)
            elif not verified:
                response["error"] = "AI 连接已安全保存，但服务商验证没有通过。"
                self._send_json(response, status=HTTPStatus.UNPROCESSABLE_ENTITY)
            else:
                self._send_json(response, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "media-asset-jobs" and parts[2] == "retry":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            original = self.repository.get_media_asset_job(company_id=identity["company_id"], media_job_id=parts[1])
            if not original:
                self._send_error(HTTPStatus.NOT_FOUND, "media asset job not found")
                return
            if str(original.get("status") or "") in {"pending", "queued", "running", "provider_returned"}:
                self._send_error(HTTPStatus.CONFLICT, "media asset job is still running and cannot be retried")
                return
            original_payload = original.get("job") if isinstance(original.get("job"), dict) else {}
            original_spec = original_payload.get("job_spec") if isinstance(original_payload.get("job_spec"), dict) else {}
            original_inputs = original_spec.get("inputs") if isinstance(original_spec.get("inputs"), dict) else {}
            if not original_inputs:
                self._send_error(HTTPStatus.BAD_REQUEST, "media asset job has no reusable generation inputs")
                return
            reason = str(body.get("reason") or "商家要求重做素材")[:200]
            prior_version = original.get("asset_version") if isinstance(original.get("asset_version"), dict) else {}
            version = max(1, int(prior_version.get("version") or 1)) + 1
            max_versions = _positive_int_env("JIEJING_MEDIA_ASSET_MAX_VERSIONS", 8)
            if version > max_versions:
                self._send_json(
                    {
                        "error": "media asset version limit reached",
                        "status": int(HTTPStatus.CONFLICT),
                        "media_asset_version_limit": max_versions,
                        "next_action": "review_or_archive_existing_versions_before_new_rework",
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            root_media_job_id = str(prior_version.get("root_media_job_id") or original["media_job_id"])
            safe_inputs = _redact_secret_like(dict(original_inputs))
            creative_override = body.get("creative_job_spec") if isinstance(body.get("creative_job_spec"), dict) else {}
            if creative_override:
                current_creative = safe_inputs.get("creative_job_spec") if isinstance(safe_inputs.get("creative_job_spec"), dict) else {}
                safe_inputs["creative_job_spec"] = {**current_creative, **_redact_secret_like(creative_override)}
            safe_inputs["asset_version"] = {
                "contract_version": "2026-07-11-media-asset-version-v1",
                "version": version,
                "root_media_job_id": root_media_job_id,
                "parent_media_job_id": original["media_job_id"],
                "generation_reason": reason,
                "prompt_version": f"media_prompt_v{version}",
                "immutable_prior_versions": True,
                "secret_exposed": False,
            }
            provider_job_key = str(original.get("provider_job_key") or "media.asset_generation")
            catalog = build_provider_job_contract_catalog()
            contracts = {item.get("key"): item for item in catalog.get("contracts", [])}
            contract = contracts.get(provider_job_key)
            if not contract:
                self._send_error(HTTPStatus.NOT_FOUND, "media provider job contract not found")
                return
            supplied_key = f"media-rework:{original['media_job_id']}:v{version}"
            retry_key = _media_asset_idempotency_key(
                store_id=original["store_id"],
                provider_job_key=provider_job_key,
                inputs=safe_inputs,
                supplied=supplied_key,
            )
            existing = self.repository.get_media_asset_job_by_idempotency(company_id=identity["company_id"], idempotency_key=retry_key)
            if existing:
                self._send_json({"media_asset_job": existing, "idempotent_replay": True, "secret_exposed": False}, status=HTTPStatus.ACCEPTED)
                return
            reservation = self.repository.reserve_media_rework(
                company_id=identity["company_id"],
                parent_media_job_id=original["media_job_id"],
                version=version,
                idempotency_key=retry_key,
            )
            if reservation.get("acquired") is not True:
                reserved_media_job_id = str(reservation.get("media_job_id") or "")
                reserved_media_job = (
                    self.repository.get_media_asset_job(
                        company_id=identity["company_id"],
                        media_job_id=reserved_media_job_id,
                    )
                    if reserved_media_job_id
                    else None
                )
                self._send_json(
                    {
                        "media_asset_job": reserved_media_job or {},
                        "idempotent_replay": True,
                        "retry_in_progress": not bool(reserved_media_job),
                        "retry_after_seconds": min(5, int(reservation.get("retry_after_seconds") or 1)),
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
                return
            media_quote = estimate_media_points(safe_inputs)
            media_credit_state: dict[str, Any] = {
                "quote": media_quote,
                "enforcement_enabled": _env_bool("JIEJING_MEDIA_CREDIT_ENFORCEMENT_ENABLED"),
                "reservation": None,
                "provider_neutral": True,
                "secret_exposed": False,
            }
            if media_credit_state["enforcement_enabled"] and bool(safe_inputs.get("live_provider_requested")):
                try:
                    media_credit_state["reservation"] = self.repository.apply_media_credit_operation(
                        company_id=identity["company_id"],
                        user_id=identity["user_id"],
                        operation_type="reserve",
                        points=int(media_quote["estimated_points"]),
                        idempotency_key=f"{retry_key}:reserve:v1",
                        reference_type="media_rework",
                        reference_id=retry_key,
                        details={"quote": media_quote, "parent_media_job_id": original["media_job_id"], "version": version},
                    )
                except ValueError as exc:
                    self.repository.release_media_rework_reservation(
                        company_id=identity["company_id"],
                        parent_media_job_id=original["media_job_id"],
                        version=version,
                    )
                    if "insufficient" not in str(exc).lower():
                        raise
                    self._send_json(
                        {
                            "error": "素材点不足，重做任务没有进入生成队列。",
                            "status": int(HTTPStatus.PAYMENT_REQUIRED),
                            "media_credits": build_media_credit_summary(
                                self.repository,
                                company_id=identity["company_id"],
                            ),
                            "media_quote": media_quote,
                            "triggers_real_charge": False,
                            "secret_exposed": False,
                        },
                        status=HTTPStatus.PAYMENT_REQUIRED,
                    )
                    return
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=original["store_id"],
                user_id=identity["user_id"],
                task_type="provider_job",
                title=f"素材重做 v{version}",
                input_data={
                    "provider_job_key": provider_job_key,
                    "provider_family": contract.get("provider_family"),
                    "store_id": original["store_id"],
                    "inputs": safe_inputs,
                    "contract_version": catalog.get("contract_version"),
                    "media_asset_idempotency_key": retry_key,
                    "media_credits": media_credit_state,
                    "real_platform_writes_enabled": False,
                },
            )
            version_context = safe_inputs["asset_version"]
            media_job = self.repository.create_media_asset_job(
                company_id=identity["company_id"],
                store_id=original["store_id"],
                task_id=task["task_id"],
                user_id=identity["user_id"],
                provider_job_key=provider_job_key,
                idempotency_key=retry_key,
                job_spec={
                    "provider_job_key": provider_job_key,
                    "contract_version": catalog.get("contract_version"),
                    "inputs": safe_inputs,
                    "merchant_visible_provider_name": False,
                    "live_media_provider_call_allowed": False,
                    "spend_now_allowed": False,
                    "media_credits": media_credit_state,
                    "secret_exposed": False,
                },
                status="pending",
                version_context=version_context,
            )
            self.repository.complete_media_rework_reservation(
                company_id=identity["company_id"],
                parent_media_job_id=original["media_job_id"],
                version=version,
                media_job_id=media_job["media_job_id"],
            )
            queue_job = self.repository.create_queue_job(
                company_id=identity["company_id"],
                task_id=task["task_id"],
                max_attempts=int(contract.get("max_attempts") or 1),
                job_data={
                    "kind": "provider_job",
                    "provider_job_key": provider_job_key,
                    "provider_family": contract.get("provider_family"),
                    "queue": contract.get("queue"),
                    "contract": contract,
                    "inputs": safe_inputs,
                    "media_job_id": media_job["media_job_id"],
                    "idempotency_key": retry_key,
                    "run_mode": body.get("run_mode") or "queued",
                    "live_provider_called": False,
                    "media_credits": media_credit_state,
                    "real_platform_writes_enabled": False,
                },
            )
            media_job = self.repository.update_media_asset_job(
                company_id=identity["company_id"],
                media_job_id=media_job["media_job_id"],
                status="queued",
                queue_job_id=queue_job["job_id"],
                details={"event": "merchant_media_rework_queued", "reason": reason, "secret_exposed": False},
            )
            self.repository.update_media_asset_job(
                company_id=identity["company_id"],
                media_job_id=original["media_job_id"],
                status=str(original.get("status") or "needs_rework"),
                retry_delta=1,
                details={
                    "event": "merchant_media_rework_created",
                    "child_media_job_id": media_job["media_job_id"],
                    "child_version": version,
                    "reason": reason,
                    "secret_exposed": False,
                },
            )
            worker_result = None
            if str(body.get("run_mode") or "queued") in {"inline", "enqueue_and_wait", "local_worker_now"}:
                worker_result = self.queue_worker.run_next(company_id=identity["company_id"], job_id=queue_job["job_id"])
                media_job = worker_result.get("media_asset_job") if isinstance(worker_result, dict) and isinstance(worker_result.get("media_asset_job"), dict) else media_job
                queue_job = worker_result.get("queue_job") if isinstance(worker_result, dict) and isinstance(worker_result.get("queue_job"), dict) else queue_job
            self._send_json(
                {
                    "media_asset_job": media_job,
                    "queue_job": queue_job,
                    "worker_result": worker_result,
                    "idempotent_replay": False,
                    "rework": {
                        "parent_media_job_id": original["media_job_id"],
                        "version": version,
                        "actual_cost_status": "unknown_until_provider_usage_record",
                        "triggers_real_platform_write": False,
                        "secret_exposed": False,
                    },
                    "media_credits": media_credit_state,
                    "real_platform_writes_enabled": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "model" and parts[3] == "verify":
            if not self._require_permission(identity, "manage_connections"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            result = self._verify_saved_model_connection(identity=identity, store_id=store_id, body=body)
            self._send_json(result, status=HTTPStatus.OK if result.get("verified") else HTTPStatus.UNPROCESSABLE_ENTITY)
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "merchant-memory" and parts[3] == "refresh":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            refresh = self.repository.refresh_merchant_memory_from_existing_records(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                limit=int(body.get("limit") or 100),
            )
            self._send_json({"merchant_memory_refresh": refresh, "secret_exposed": False}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 4 and parts[0] == "stores" and parts[2] == "merchant-ceo" and parts[3] == "commands":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            store_id = parts[1]
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            command_body = body.get("command") if isinstance(body.get("command"), dict) else body
            command = self.repository.save_merchant_ceo_command(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                command=command_body,
            )
            self._send_json({"merchant_ceo_command": command, **command}, status=HTTPStatus.CREATED)
            return

        if path == "ai-ceo/chat-history/sync":
            if not self._require_permission(identity, "create_task"):
                return
            body = self._read_json_body()
            turns = body.get("turns") if isinstance(body.get("turns"), list) else []
            base_revision = str(body.get("base_revision") or "")[:120]
            server_revision_before = self.repository.ai_ceo_chat_history_revision(
                company_id=identity["company_id"],
                user_id=identity["user_id"],
            )
            history = self.repository.sync_ai_ceo_chat_history(
                company_id=identity["company_id"],
                user_id=identity["user_id"],
                turns=turns,
                limit=30,
            )
            revision = self.repository.ai_ceo_chat_history_revision(
                company_id=identity["company_id"],
                user_id=identity["user_id"],
            )
            self._send_json(
                {
                    "ai_ceo_chat_history": {
                        "scope": "account",
                        "cross_store": True,
                        "turns": history,
                        "turn_count": len(history),
                        "submitted_turn_count": min(len(turns), 30),
                        "revision": revision,
                        "base_revision": base_revision,
                        "conflict_merged": bool(base_revision and base_revision != server_revision_before),
                        "sync_contract": "2026-07-11-ai-ceo-cross-device-revision-v1",
                        "raw_provider_secret_stored": False,
                        "frontend_gets_model_api_key": False,
                        "real_platform_writes_enabled": False,
                        "secret_exposed": False,
                    }
                },
                status=HTTPStatus.CREATED,
            )
            return

        if path == "tasks/product-workflow":
            if not self._require_permission(identity, "create_task"):
                return
            if not self._require_quota(identity, "ai_ceo_task"):
                return
            body = self._read_json_body()
            store_id = str(body.get("store_id") or "")
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=store_id)
            if not store:
                self._send_error(HTTPStatus.NOT_FOUND, "store not found or not accessible")
                return
            latest_packet = None
            packet_handoff: dict[str, Any] = {}
            if body.get("attach_latest_platform_data_packet") is not False:
                packets = self.repository.list_platform_data_packets(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    platform="ebay",
                )
                latest_packet = packets[0] if packets else None
                packet_handoff = build_runtime_handoff_from_platform_packet(latest_packet)
                if packet_handoff:
                    body = merge_runtime_handoff_input(body, packet_handoff)
            public_search_handoff: dict[str, Any] = {}
            if body.get("attach_public_search_market_signal") is not False:
                public_search_handoff = build_public_search_market_handoff(
                    settings=self.settings,
                    repository=self.repository,
                    company_id=identity["company_id"],
                    store=store,
                    user_id=identity["user_id"],
                    body=body,
                )
                if public_search_handoff:
                    body = merge_public_search_handoff_input(body, public_search_handoff)
            title = str(body.get("title") or f"AI CEO product workflow: {body.get('product') or 'Untitled product'}")
            task = self.repository.create_task(
                company_id=identity["company_id"],
                store_id=store_id,
                user_id=identity["user_id"],
                task_type="product_workflow",
                title=title,
                input_data=_redact_secret_like(body),
            )
            planned_steps = self.repository.create_task_steps(task=task, steps=product_workflow_steps())
            job = self.repository.create_queue_job(
                company_id=identity["company_id"],
                task_id=task["task_id"],
                job_data={
                    "kind": "runtime_product_workflow",
                    "runtime_adapter": body.get("adapter") or "jiejing-local",
                    "step_count": len(planned_steps),
                    "split_mode": "saas_task_steps_local_worker",
                    "run_mode": body.get("run_mode") or "queued",
                    "attached_platform_data_packet_id": latest_packet.get("packet_id") if isinstance(latest_packet, dict) else None,
                    "attached_public_search_status": public_search_handoff.get("status") if public_search_handoff else None,
                    "attached_public_search_result_count": public_search_handoff.get("result_count") if public_search_handoff else 0,
                },
            )
            if public_search_handoff:
                self.repository.write_audit(
                    company_id=identity["company_id"],
                    store_id=store_id,
                    user_id=identity["user_id"],
                    actor_type="system",
                    action_type="public_search.market_handoff.attached",
                    target_type="task",
                    target_id=task["task_id"],
                    summary="Public-search provider output was attached to the product workflow market data packet input.",
                    details={
                        "provider_status": public_search_handoff.get("provider_status"),
                        "source_mode": public_search_handoff.get("source_mode"),
                        "result_count": public_search_handoff.get("result_count"),
                        "telemetry": public_search_handoff.get("telemetry") or {},
                        "metering_status": public_search_handoff.get("metering_status"),
                        "raw_provider_response_stored": False,
                        "secret_exposed": False,
                    },
                )
            run_mode = str(body.get("run_mode") or "queued")
            worker_result = None
            if run_mode in {"inline", "enqueue_and_wait", "local_worker_now"}:
                worker_result = self.queue_worker.run_next(company_id=identity["company_id"], job_id=job["job_id"])
                task = worker_result.get("task") or self.repository.get_task(company_id=identity["company_id"], task_id=task["task_id"]) or task
                job = worker_result.get("queue_job") or self.repository.get_queue_job(job_id=job["job_id"], company_id=identity["company_id"]) or job
                planned_steps = worker_result.get("steps") or self.repository.list_task_steps(company_id=identity["company_id"], task_id=task["task_id"])
            self._send_json(
                {
                    "task": task,
                    "queue_job": job,
                    "steps": planned_steps,
                    "worker_result": worker_result,
                    "runtime": worker_result.get("runtime") if isinstance(worker_result, dict) else None,
                    "saved": worker_result.get("saved") if isinstance(worker_result, dict) else {"reports": 0, "confirmations": 0},
                    "platform_data_packet_handoff": packet_handoff.get("platform_data_packet_handoff") if packet_handoff else None,
                    "public_search_market_handoff": public_search_handoff,
                    "real_platform_writes_enabled": False,
                },
                status=HTTPStatus.ACCEPTED,
            )
            return

        if path == "workers/run-next":
            body = self._read_json_body()
            job_id = str(body.get("job_id") or "") or None
            result = self.queue_worker.run_next(company_id=identity["company_id"], job_id=job_id)
            status = HTTPStatus.OK if result.get("status") == "idle" else HTTPStatus.CREATED
            self._send_json(result, status=status)
            return

        if len(parts) == 3 and parts[0] == "queue-jobs" and parts[2] == "cancel":
            body = self._read_json_body()
            try:
                job = self.repository.cancel_queue_job(
                    company_id=identity["company_id"],
                    job_id=parts[1],
                    user_id=identity["user_id"],
                    reason=str(body.get("reason") or "cancelled_from_saas_api"),
                )
            except KeyError:
                self._send_error(HTTPStatus.NOT_FOUND, "queue job not found")
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"queue_job": job, "real_platform_writes_enabled": False}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "queue-jobs" and parts[2] == "retry":
            body = self._read_json_body()
            try:
                job = self.repository.retry_queue_job(
                    company_id=identity["company_id"],
                    job_id=parts[1],
                    user_id=identity["user_id"],
                    reason=str(body.get("reason") or "retry_from_saas_api"),
                )
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"queue_job": job, "real_platform_writes_enabled": False}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 2 and parts[0] == "queue-jobs" and parts[1] == "recover-stale":
            body = self._read_json_body()
            stale_after = int(body.get("stale_after_seconds") or 900)
            limit = int(body.get("limit") or 50)
            result = self.repository.recover_stale_queue_jobs(
                company_id=identity["company_id"],
                stale_after_seconds=stale_after,
                limit=limit,
            )
            self._send_json({"queue_recovery": result, "real_platform_writes_enabled": False}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "confirmations" and parts[2] == "decision":
            body = self._read_json_body()
            try:
                existing_confirmation = self.repository.get_confirmation(company_id=identity["company_id"], confirmation_id=parts[1])
                if not existing_confirmation:
                    self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                    return
                decision_value = str(body.get("decision") or "")
                if (
                    decision_value == "approve"
                    and existing_confirmation.get("action_type") in HIGH_RISK_ACTIONS
                    and not self._require_permission(identity, "approve_high_risk")
                ):
                    return
                record = self.repository.decide_confirmation(
                    company_id=identity["company_id"],
                    confirmation_id=parts[1],
                    decision=decision_value,
                    decided_by=identity["user_id"],
                    note=body.get("note") if isinstance(body.get("note"), str) else None,
                )
            except KeyError:
                self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                return
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json({"confirmation": record}, status=HTTPStatus.CREATED)
            return

        if len(parts) == 3 and parts[0] == "confirmations" and parts[2] == "preflight":
            body = self._read_json_body()
            confirmation = self.repository.get_confirmation(company_id=identity["company_id"], confirmation_id=parts[1])
            if not confirmation:
                self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                return
            payload = _execution_payload_from_context(
                repository=self.repository,
                company_id=identity["company_id"],
                confirmation=confirmation,
                body_payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
            execution_request = ExecutionRequest(
                action_type=confirmation["action_type"],
                task_id=confirmation["task_id"],
                user_id=identity["user_id"],
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                platform=str(body.get("platform") or "ebay"),
                payload=payload,
                confirmation_id=confirmation["confirmation_id"] if confirmation["status"] == "approved" else None,
                confirmed_by=(confirmation["decided_by"] or identity["user_id"]) if confirmation["status"] == "approved" else None,
                confirmed_at=confirmation["decided_at"] if confirmation["status"] == "approved" else None,
                idempotency_key=str(body.get("idempotency_key") or ""),
            )
            preflight = ExecutionService(demo_mode=True).preflight(execution_request)
            latest_execution_results = self.repository.list_execution_results(company_id=identity["company_id"], limit=20)
            recent_confirmations = [
                item
                for item in self.repository.list_confirmations(company_id=identity["company_id"], limit=100)
                if item.get("confirmation_id") != confirmation["confirmation_id"]
            ]
            self._send_json(
                {
                    "preflight": preflight,
                    "prepared_payload_summary": _publish_payload_summary(payload) if confirmation["action_type"] == "publish_listing" else {},
                    "publish_readiness": build_publish_readiness(
                        payload,
                        preflight=preflight,
                        latest_execution_results=latest_execution_results,
                        recent_confirmations=recent_confirmations,
                    )
                    if confirmation["action_type"] == "publish_listing"
                    else {},
                    "confirmation": confirmation,
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 3 and parts[0] == "confirmations" and parts[2] == "publish-recovery":
            body = self._read_json_body()
            confirmation = self.repository.get_confirmation(company_id=identity["company_id"], confirmation_id=parts[1])
            if not confirmation:
                self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                return
            if confirmation.get("action_type") != "publish_listing":
                self._send_error(HTTPStatus.BAD_REQUEST, "publish recovery only supports publish_listing confirmations")
                return
            payload = _execution_payload_from_context(
                repository=self.repository,
                company_id=identity["company_id"],
                confirmation=confirmation,
                body_payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
            latest_execution_results = self.repository.list_execution_results(company_id=identity["company_id"], limit=100)
            payload = _apply_publish_recovery_execution_context(
                payload=payload,
                execution_results=latest_execution_results,
                confirmation_id=confirmation["confirmation_id"],
            )
            execution_request = ExecutionRequest(
                action_type=confirmation["action_type"],
                task_id=confirmation["task_id"],
                user_id=identity["user_id"],
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                platform=str(body.get("platform") or "ebay"),
                payload=payload,
                confirmation_id=confirmation["confirmation_id"] if confirmation["status"] == "approved" else None,
                confirmed_by=(confirmation["decided_by"] or identity["user_id"]) if confirmation["status"] == "approved" else None,
                confirmed_at=confirmation["decided_at"] if confirmation["status"] == "approved" else None,
                idempotency_key=str(body.get("idempotency_key") or ""),
            )
            preflight = ExecutionService(demo_mode=True).preflight(execution_request)
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=confirmation["store_id"]) or {}
            publish_recovery = EbayWriteHttpAdapter(self.settings).inspect_publish_state(
                request=execution_request,
                connections=self.repository.list_connections(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                secret_refs=self.repository.list_secret_refs(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                marketplace_id=str(store.get("marketplace") or "EBAY_US"),
            )
            self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.publish.recovery_checked",
                target_type="confirmation",
                target_id=confirmation["confirmation_id"],
                summary="Checked eBay publish state by SKU before any retry.",
                details={
                    "sku": publish_recovery.get("sku"),
                    "status": publish_recovery.get("status"),
                    "safe_to_retry_publish": publish_recovery.get("safe_to_retry_publish"),
                    "recommended_action": publish_recovery.get("recommended_action"),
                    "secret_exposed": False,
                },
            )
            recent_confirmations = [
                item
                for item in self.repository.list_confirmations(company_id=identity["company_id"], limit=100)
                if item.get("confirmation_id") != confirmation["confirmation_id"]
            ]
            self._send_json(
                {
                    "publish_recovery": publish_recovery,
                    "publish_readiness": build_publish_readiness(
                        payload,
                        preflight=preflight,
                        latest_execution_results=latest_execution_results,
                        recent_confirmations=recent_confirmations,
                    ),
                    "confirmation": confirmation,
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 3 and parts[0] == "confirmations" and parts[2] == "publish-cleanup-plan":
            body = self._read_json_body()
            confirmation = self.repository.get_confirmation(company_id=identity["company_id"], confirmation_id=parts[1])
            if not confirmation:
                self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                return
            if confirmation.get("action_type") != "publish_listing":
                self._send_error(HTTPStatus.BAD_REQUEST, "publish cleanup plan only supports publish_listing confirmations")
                return
            payload = _execution_payload_from_context(
                repository=self.repository,
                company_id=identity["company_id"],
                confirmation=confirmation,
                body_payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
            latest_execution_results = self.repository.list_execution_results(company_id=identity["company_id"], limit=100)
            payload = _apply_publish_recovery_execution_context(
                payload=payload,
                execution_results=latest_execution_results,
                confirmation_id=confirmation["confirmation_id"],
            )
            execution_request = ExecutionRequest(
                action_type=confirmation["action_type"],
                task_id=confirmation["task_id"],
                user_id=identity["user_id"],
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                platform=str(body.get("platform") or "ebay"),
                payload=payload,
                confirmation_id=confirmation["confirmation_id"] if confirmation["status"] == "approved" else None,
                confirmed_by=(confirmation["decided_by"] or identity["user_id"]) if confirmation["status"] == "approved" else None,
                confirmed_at=confirmation["decided_at"] if confirmation["status"] == "approved" else None,
                idempotency_key=str(body.get("idempotency_key") or ""),
            )
            store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=confirmation["store_id"]) or {}
            publish_recovery = EbayWriteHttpAdapter(self.settings).inspect_publish_state(
                request=execution_request,
                connections=self.repository.list_connections(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                secret_refs=self.repository.list_secret_refs(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                marketplace_id=str(store.get("marketplace") or "EBAY_US"),
            )
            cleanup_plan = publish_recovery.get("cleanup_plan") if isinstance(publish_recovery.get("cleanup_plan"), dict) else {}
            operations = cleanup_plan.get("operations") if isinstance(cleanup_plan.get("operations"), list) else []
            if not operations:
                self.repository.write_audit(
                    company_id=identity["company_id"],
                    store_id=confirmation["store_id"],
                    user_id=identity["user_id"],
                    actor_type="system",
                    action_type="ebay.publish.cleanup_plan.skipped",
                    target_type="confirmation",
                    target_id=confirmation["confirmation_id"],
                    summary="No test listing cleanup confirmation was created because no cleanup operations were found.",
                    details={"sku": publish_recovery.get("sku"), "status": publish_recovery.get("status"), "secret_exposed": False},
                )
                self._send_json(
                    {
                        "publish_recovery": publish_recovery,
                        "cleanup_confirmation": None,
                        "created": False,
                        "reason": "no_cleanup_operations",
                        "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                    },
                    status=HTTPStatus.CREATED,
                )
                return
            cleanup_confirmation = self.repository.create_confirmation(
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                task_id=confirmation["task_id"],
                runtime_run_id=confirmation.get("runtime_run_id") or "publish_cleanup_plan",
                action_type="cleanup_test_listing",
                title=_cleanup_confirmation_title(publish_recovery),
                item=_cleanup_confirmation_item(
                    publish_confirmation=confirmation,
                    publish_recovery=publish_recovery,
                    cleanup_plan=cleanup_plan,
                ),
                created_by=identity["user_id"],
                confirmation_id=_cleanup_confirmation_id(
                    publish_confirmation_id=confirmation["confirmation_id"],
                    publish_recovery=publish_recovery,
                ),
                default_action="hold",
            )
            self.repository.write_audit(
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                user_id=identity["user_id"],
                actor_type="system",
                action_type="ebay.publish.cleanup_plan.created",
                target_type="confirmation",
                target_id=cleanup_confirmation.get("confirmation_id"),
                summary="Created a confirmation item for live test listing cleanup; no eBay cleanup write was executed.",
                details={
                    "source_publish_confirmation_id": confirmation["confirmation_id"],
                    "sku": publish_recovery.get("sku"),
                    "operation_count": len(operations),
                    "secret_exposed": False,
                },
            )
            self._send_json(
                {
                    "publish_recovery": publish_recovery,
                    "cleanup_confirmation": cleanup_confirmation,
                    "created": True,
                    "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled,
                },
                status=HTTPStatus.CREATED,
            )
            return

        if len(parts) == 3 and parts[0] == "confirmations" and parts[2] == "execute":
            body = self._read_json_body()
            confirmation = self.repository.get_confirmation(company_id=identity["company_id"], confirmation_id=parts[1])
            if not confirmation:
                self._send_error(HTTPStatus.NOT_FOUND, "confirmation not found")
                return
            if confirmation["status"] != "approved":
                self._send_error(HTTPStatus.BAD_REQUEST, "confirmation must be approved before execution service handoff")
                return
            payload = _execution_payload_from_context(
                repository=self.repository,
                company_id=identity["company_id"],
                confirmation=confirmation,
                body_payload=body.get("payload") if isinstance(body.get("payload"), dict) else {},
            )
            execution_request = ExecutionRequest(
                action_type=confirmation["action_type"],
                task_id=confirmation["task_id"],
                user_id=identity["user_id"],
                company_id=identity["company_id"],
                store_id=confirmation["store_id"],
                platform=str(body.get("platform") or "ebay"),
                payload=payload,
                confirmation_id=confirmation["confirmation_id"],
                confirmed_by=confirmation["decided_by"] or identity["user_id"],
                confirmed_at=confirmation["decided_at"],
                idempotency_key=str(body.get("idempotency_key") or ""),
            )
            live_ebay_write_actions = {"publish_listing", "save_ebay_listing_draft"}
            if self.settings.effective_real_platform_writes_enabled and confirmation["action_type"] in live_ebay_write_actions:
                boundary_result = ExecutionService(demo_mode=False).execute(execution_request).to_dict()
                if boundary_result.get("status") == "ready_for_platform_adapter":
                    store = self.repository.get_store_for_company(company_id=identity["company_id"], store_id=confirmation["store_id"]) or {}
                    adapter = EbayWriteHttpAdapter(self.settings)
                    adapter_kwargs = {
                        "request": execution_request,
                        "preflight": boundary_result.get("audit", {}).get("preflight") if isinstance(boundary_result.get("audit"), dict) else {},
                        "connections": self.repository.list_connections(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                        "secret_refs": self.repository.list_secret_refs(company_id=identity["company_id"], store_id=confirmation["store_id"]),
                        "marketplace_id": str(store.get("marketplace") or "EBAY_US"),
                    }
                    write_result = (
                        adapter.save_listing_draft(**adapter_kwargs)
                        if confirmation["action_type"] == "save_ebay_listing_draft"
                        else adapter.publish_listing(**adapter_kwargs)
                    )
                    write_result.setdefault("created_at", boundary_result.get("created_at"))
                    write_audit = write_result.get("audit") if isinstance(write_result.get("audit"), dict) else {}
                    boundary_audit = boundary_result.get("audit") if isinstance(boundary_result.get("audit"), dict) else {}
                    if isinstance(boundary_audit.get("idempotency"), dict):
                        write_audit["idempotency"] = boundary_audit["idempotency"]
                    if isinstance(boundary_audit.get("execution_intent"), dict):
                        write_audit["execution_intent"] = boundary_audit["execution_intent"]
                    write_result["audit"] = write_audit
                    result = write_result
                else:
                    result = boundary_result
            else:
                result = ExecutionService(demo_mode=True).execute(execution_request).to_dict()
            stored = self.repository.save_execution_result(confirmation=confirmation, result=result)
            self._send_json({"execution": stored, "real_platform_writes_enabled": self.settings.effective_real_platform_writes_enabled}, status=HTTPStatus.CREATED)
            return

        self._send_error(HTTPStatus.NOT_FOUND, "endpoint not found")

    def log_message(self, format: str, *args: Any) -> None:
        if not self._safe_access_log_enabled():
            return
        status_code = str(args[1]) if len(args) >= 2 else ""
        parsed = urlparse(self.path)
        event = {
            "event": "http_access",
            "method": self.command,
            "path": parsed.path,
            "status": status_code,
            "secret_exposed": False,
        }
        sys.stderr.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _safe_access_log_enabled(self) -> bool:
        settings = getattr(self, "settings", None)
        if settings and settings.is_production_like:
            return True
        return str(os.environ.get("JIEJING_SAFE_ACCESS_LOG") or "").strip().lower() in {"1", "true", "yes", "on"}

    def _merchant_onboarding_context(
        self,
        identity: dict[str, Any],
        *,
        progress: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
        """Resolve one tenant's current eBay evidence without invoking OAuth or a sync."""

        company_id = str(identity.get("company_id") or "")
        persisted = progress if isinstance(progress, dict) else self.repository.get_merchant_onboarding_state(company_id=company_id)
        all_connections = self.repository.list_connections(company_id=company_id)
        stores = self.repository.list_stores(company_id=company_id)
        accessible_stores = {
            str(store.get("store_id") or ""): store
            for store in stores
            if isinstance(store, dict) and str(store.get("store_id") or "")
        }
        preferred_store_id = str((persisted or {}).get("store_id") or "")
        if preferred_store_id not in accessible_stores:
            preferred_store_id = ""
        if not preferred_store_id:
            current_connection = next(
                (
                    connection
                    for connection in all_connections
                    if isinstance(connection, dict)
                    and str(connection.get("platform") or "ebay").strip().lower() == "ebay"
                    and str(connection.get("status") or "").strip().lower() in AUTHORIZED_CONNECTION_STATUSES
                    and str(connection.get("store_id") or "") in accessible_stores
                ),
                None,
            )
            preferred_store_id = str((current_connection or {}).get("store_id") or "")
        if not preferred_store_id:
            preferred_store = next(
                (
                    store
                    for store in stores
                    if isinstance(store, dict) and str(store.get("platform") or "ebay").strip().lower() == "ebay"
                ),
                None,
            )
            preferred_store_id = str((preferred_store or {}).get("store_id") or "")
        store = accessible_stores.get(preferred_store_id)
        connections = (
            [
                connection
                for connection in all_connections
                if isinstance(connection, dict) and str(connection.get("store_id") or "") == preferred_store_id
            ]
            if preferred_store_id
            else all_connections
        )
        account_health = (
            build_account_health_snapshot(self.repository, company_id=company_id, store_id=preferred_store_id)
            if preferred_store_id
            else {}
        )
        return persisted, connections, account_health, store

    def _merchant_onboarding_read_model(
        self,
        identity: dict[str, Any],
        *,
        progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        persisted, connections, account_health, store = self._merchant_onboarding_context(identity, progress=progress)
        return build_merchant_onboarding_read_model(
            progress=persisted or {},
            connections=connections,
            account_health=account_health,
            store=store,
        )

    def _require_auth(self) -> dict[str, Any] | None:
        token = self._request_session_token()
        if not token:
            self._send_error(HTTPStatus.UNAUTHORIZED, "missing bearer token or session cookie")
            return None
        try:
            return self._validated_session_identity(token)
        except ValueError as exc:
            self._send_error(HTTPStatus.UNAUTHORIZED, str(exc))
            return None

    def _optional_identity(self) -> dict[str, Any] | None:
        token = self._request_session_token()
        if not token:
            return None
        try:
            return self._validated_session_identity(token)
        except ValueError:
            return None

    def _issue_session_token(self, *, user_id: str, company_id: str, email: str) -> str:
        token = self.sessions.create_token(user_id=user_id, company_id=company_id, email=email)
        identity = self.sessions.verify_token(token)
        state = self.repository.ensure_user_session(identity)
        if state.get("active") is not True:
            raise RuntimeError("new session could not be persisted")
        return token

    def _validated_session_identity(self, token: str) -> dict[str, Any]:
        identity = self.sessions.verify_token(token)
        state = self.repository.ensure_user_session(identity)
        if state.get("active") is not True:
            raise ValueError("session revoked or expired")
        return identity

    def _request_session_token(self) -> str:
        header = self.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1].strip()
            if token:
                return token
        return self._session_cookie_token()

    def _can_view_internal_diagnostics(self, identity: dict[str, Any] | None) -> bool:
        return bool(identity and self._is_platform_internal_admin(identity))

    def _session_cookie_token(self) -> str:
        raw = self.headers.get("cookie", "")
        if not raw:
            return ""
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except Exception:
            return ""
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return str(morsel.value or "").strip() if morsel else ""

    def _session_cookie_header(self, token: str) -> str:
        same_site = "Strict" if self._operations_console_cookie_context() else "Lax"
        parts = [
            f"{SESSION_COOKIE_NAME}={token}",
            "Path=/",
            f"Max-Age={int(getattr(self.sessions, 'ttl_seconds', 60 * 60 * 24 * 7))}",
            "HttpOnly",
            f"SameSite={same_site}",
        ]
        if self._secure_cookie_context():
            parts.append("Secure")
        return "; ".join(parts)

    def _expired_session_cookie_header(self) -> str:
        same_site = "Strict" if self._operations_console_cookie_context() else "Lax"
        parts = [
            f"{SESSION_COOKIE_NAME}=",
            "Path=/",
            "Max-Age=0",
            "HttpOnly",
            f"SameSite={same_site}",
        ]
        if self._secure_cookie_context():
            parts.append("Secure")
        return "; ".join(parts)

    def _secure_cookie_context(self) -> bool:
        proto = str(self.headers.get("x-forwarded-proto") or "").lower()
        if proto == "https":
            return True
        origin = str(self.headers.get("origin") or "").lower()
        if origin.startswith("https://"):
            return True
        host = str(self.headers.get("host") or "").lower()
        return host.endswith(".trycloudflare.com")

    def _operations_console_cookie_context(self) -> bool:
        host = str(self.headers.get("host") or "").split(":", 1)[0].strip().lower()
        return host == "ops.jiejing.shop" or host.startswith("ops.") and host.endswith(".jiejing.shop")

    def _check_auth_rate_limit(self, action: str, body: dict[str, Any]) -> bool:
        client_ip = self._client_ip_for_rate_limit()
        email = str(body.get("email") or "").strip().lower()
        checks = [
            (f"auth:{action}:global", "global", self._auth_rate_limit_max_global(action)),
            (f"auth:{action}:ip", client_ip, self._auth_rate_limit_max_per_ip(action)),
        ]
        if email:
            checks.append((f"auth:{action}:email", email, AUTH_RATE_LIMIT_MAX_PER_EMAIL))
        for scope, subject, limit in checks:
            result = self._consume_rate_limit(
                scope=scope,
                subject=subject,
                limit=limit,
                window_seconds=AUTH_RATE_LIMIT_WINDOW_SECONDS,
                local_buckets=self.auth_rate_limit_buckets,
                local_lock=self.auth_rate_limit_lock,
            )
            if result.get("allowed") is not True:
                self._send_json(
                    {
                        "error": "too many authentication attempts; please retry later",
                        "status": int(HTTPStatus.TOO_MANY_REQUESTS),
                        "retry_after_seconds": int(result.get("retry_after_seconds") or AUTH_RATE_LIMIT_WINDOW_SECONDS),
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                )
                return False
        return True

    def _check_public_analytics_rate_limit(self) -> bool:
        window_seconds = 60
        checks = [
            ("analytics:events:global", "global", _positive_int_env("JIEJING_ANALYTICS_RATE_LIMIT_GLOBAL_PER_MINUTE", 6000)),
            ("analytics:events:ip", self._client_ip_for_rate_limit(), _positive_int_env("JIEJING_ANALYTICS_RATE_LIMIT_PER_IP_PER_MINUTE", 120)),
        ]
        for scope, subject, limit in checks:
            result = self._consume_rate_limit(
                scope=scope,
                subject=subject,
                limit=limit,
                window_seconds=window_seconds,
                local_buckets=self.expensive_api_rate_limit_buckets,
                local_lock=self.expensive_api_rate_limit_lock,
            )
            if result.get("allowed") is not True:
                self._send_json(
                    {
                        "error": "analytics rate limit exceeded",
                        "retry_after_seconds": int(result.get("retry_after_seconds") or window_seconds),
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                )
                return False
        return True

    def _check_expensive_api_rate_limit(self, *, method: str, path: str) -> bool:
        if not self._is_expensive_api_rate_limited_path(path):
            return True
        if not self._expensive_api_rate_limit_enabled():
            return True
        window_seconds = self._expensive_api_rate_limit_window_seconds()
        limit = self._expensive_api_rate_limit_max_per_ip()
        client_ip = self._client_ip_for_rate_limit()
        route_group = self._expensive_api_route_group(path)
        checks = [
            (f"expensive:{method.upper()}:{route_group}:global", "global", self._expensive_api_rate_limit_max_global()),
            (f"expensive:{method.upper()}:{route_group}:ip", client_ip, limit),
        ]
        for scope, subject, bucket_limit in checks:
            result = self._consume_rate_limit(
                scope=scope,
                subject=subject,
                limit=bucket_limit,
                window_seconds=window_seconds,
                local_buckets=self.expensive_api_rate_limit_buckets,
                local_lock=self.expensive_api_rate_limit_lock,
            )
            if result.get("allowed") is not True:
                self._send_json(
                    {
                        "error": "too many high-cost API requests; please retry later",
                        "status": int(HTTPStatus.TOO_MANY_REQUESTS),
                        "retry_after_seconds": int(result.get("retry_after_seconds") or window_seconds),
                        "rate_limit": {
                            "scope": "expensive_api_per_ip",
                            "route_group": route_group,
                            "window_seconds": window_seconds,
                            "max_requests": bucket_limit,
                            "protected_high_cost_api": True,
                            "operator_next_step": "wait_for_window_or_reduce_polling",
                            "customer_visible": False,
                            "frontend_gets_secret": False,
                            "triggers_real_platform_write": False,
                            "secret_exposed": False,
                        },
                        "secret_exposed": False,
                    },
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                )
                return False
        return True

    def _check_domestic_reconciliation_rate_limit(self, identity: dict[str, Any]) -> bool:
        result = self._consume_rate_limit(
            scope="billing:domestic:reconciliation:company",
            subject=str(identity.get("company_id") or ""),
            limit=DOMESTIC_RECONCILIATION_RATE_LIMIT_MAX_PER_COMPANY,
            window_seconds=DOMESTIC_RECONCILIATION_RATE_LIMIT_WINDOW_SECONDS,
            local_buckets=self.expensive_api_rate_limit_buckets,
            local_lock=self.expensive_api_rate_limit_lock,
        )
        if result.get("allowed") is True:
            return True
        self._send_json(
            {
                "error": "payment status checks are temporarily limited; please retry later",
                "status": int(HTTPStatus.TOO_MANY_REQUESTS),
                "retry_after_seconds": int(
                    result.get("retry_after_seconds") or DOMESTIC_RECONCILIATION_RATE_LIMIT_WINDOW_SECONDS
                ),
                "rate_limit": {
                    "scope": "domestic_reconciliation_per_company",
                    "window_seconds": DOMESTIC_RECONCILIATION_RATE_LIMIT_WINDOW_SECONDS,
                    "max_requests": DOMESTIC_RECONCILIATION_RATE_LIMIT_MAX_PER_COMPANY,
                    "query_only": True,
                    "triggers_real_charge": False,
                    "triggers_real_refund": False,
                    "secret_exposed": False,
                },
                "secret_exposed": False,
            },
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
        return False

    def _consume_rate_limit(
        self,
        *,
        scope: str,
        subject: str,
        limit: int,
        window_seconds: int,
        local_buckets: dict[str, list[float]],
        local_lock: threading.Lock,
    ) -> dict[str, Any]:
        try:
            return self.repository.consume_rate_limit_bucket(
                scope=scope,
                subject=subject,
                limit=limit,
                window_seconds=window_seconds,
            )
        except Exception:
            now = time.time()
            local_key = hashlib.sha256(f"{scope}|{subject}".encode("utf-8")).hexdigest()
            with local_lock:
                for key, values in list(local_buckets.items()):
                    active = [value for value in values if now - value < window_seconds]
                    if active:
                        local_buckets[key] = active
                    else:
                        local_buckets.pop(key, None)
                max_buckets = _positive_int_env("JIEJING_LOCAL_RATE_LIMIT_MAX_BUCKETS", LOCAL_RATE_LIMIT_MAX_BUCKETS_DEFAULT)
                while len(local_buckets) >= max_buckets:
                    local_buckets.pop(next(iter(local_buckets)), None)
                bucket = local_buckets.setdefault(local_key, [])
                if len(bucket) >= limit:
                    return {
                        "allowed": False,
                        "retry_after_seconds": window_seconds,
                        "storage": "bounded_process_fallback",
                        "secret_exposed": False,
                    }
                bucket.append(now)
            return {
                "allowed": True,
                "retry_after_seconds": window_seconds,
                "storage": "bounded_process_fallback",
                "secret_exposed": False,
            }

    def _check_product_feedback_rate_limit(self, identity: dict[str, Any]) -> bool:
        window_seconds = _bounded_positive_int_env(
            "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS",
            PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_DEFAULT,
            minimum=PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_MIN,
            maximum=PRODUCT_FEEDBACK_RATE_LIMIT_WINDOW_SECONDS_MAX,
        )
        checks = (
            (
                "product_feedback:submit:user",
                str(identity.get("user_id") or "unknown"),
                _bounded_positive_int_env(
                    "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER",
                    PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER_DEFAULT,
                    minimum=1,
                    maximum=PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_USER_MAX,
                ),
            ),
            (
                "product_feedback:submit:company",
                str(identity.get("company_id") or "unknown"),
                _bounded_positive_int_env(
                    "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY",
                    PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY_DEFAULT,
                    minimum=1,
                    maximum=PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_COMPANY_MAX,
                ),
            ),
            (
                "product_feedback:submit:ip",
                self._client_ip_for_rate_limit(),
                _bounded_positive_int_env(
                    "JIEJING_PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP",
                    PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP_DEFAULT,
                    minimum=1,
                    maximum=PRODUCT_FEEDBACK_RATE_LIMIT_MAX_PER_IP_MAX,
                ),
            ),
        )
        try:
            results = [
                self.repository.consume_rate_limit_bucket(
                    scope=scope,
                    subject=subject,
                    limit=limit,
                    window_seconds=window_seconds,
                )
                for scope, subject, limit in checks
            ]
        except Exception:
            self._send_json(
                {
                    "error": "product feedback is temporarily unavailable; keep this feedback queued and retry later",
                    "status": int(HTTPStatus.SERVICE_UNAVAILABLE),
                    "delivered": False,
                    "retryable": True,
                    "queue_locally": True,
                    "retry_after_seconds": window_seconds,
                    "external_provider_action_triggered": False,
                    "real_platform_write_performed": False,
                    "secret_exposed": False,
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        denied_results = [result for result in results if result.get("allowed") is not True]
        if not denied_results:
            return True
        self._send_json(
            {
                "error": "product feedback submissions are temporarily limited; please retry later",
                "status": int(HTTPStatus.TOO_MANY_REQUESTS),
                "delivered": False,
                "retryable": True,
                "queue_locally": True,
                "retry_after_seconds": max(
                    int(result.get("retry_after_seconds") or window_seconds) for result in denied_results
                ),
                "external_provider_action_triggered": False,
                "real_platform_write_performed": False,
                "secret_exposed": False,
            },
            status=HTTPStatus.TOO_MANY_REQUESTS,
        )
        return False

    @staticmethod
    def _public_readiness_summary(readiness: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
        evidence = readiness.get("product_evidence") if isinstance(readiness.get("product_evidence"), dict) else {}
        provider_status = readiness.get("provider_status") if isinstance(readiness.get("provider_status"), dict) else {}
        billing = provider_status.get("billing") if isinstance(provider_status.get("billing"), dict) else {}
        domestic_payment = (
            billing.get("domestic_payment")
            if isinstance(billing.get("domestic_payment"), dict)
            else {}
        )
        model_value = provider_status.get("model_value") if isinstance(provider_status.get("model_value"), dict) else {}
        model_value_ready = any(
            model_value.get(key) is True
            for key in ("ready_for_paid_value_claim", "ready", "model_value_ready")
        )
        model_value_blockers = model_value.get("blockers") if isinstance(model_value.get("blockers"), list) else []
        model_value_report_types = (
            model_value.get("live_model_report_types")
            if isinstance(model_value.get("live_model_report_types"), list)
            else []
        )
        platform_model = (
            provider_status.get("ai_ceo_platform_model")
            if isinstance(provider_status.get("ai_ceo_platform_model"), dict)
            else {}
        )
        public_search = provider_status.get("public_search") if isinstance(provider_status.get("public_search"), dict) else {}
        media_generation = (
            provider_status.get("media_generation")
            if isinstance(provider_status.get("media_generation"), dict)
            else {}
        )
        packet_current_marker = evidence.get("latest_ebay_packet_current_connection")
        packet_is_current = True if packet_current_marker is None else packet_current_marker is True
        historical_packet_present = evidence.get("historical_ebay_packet_present") is True
        public_evidence: dict[str, Any] = {
            "latest_ebay_packet_status": (
                _safe_public_token(evidence.get("latest_ebay_packet_status"))
                if packet_is_current
                else "historical_packet_archived_not_current"
            ),
            "latest_ebay_packet_source_mode": (
                _safe_public_token(evidence.get("latest_ebay_packet_source_mode"))
                if packet_is_current
                else "historical_archived"
            ),
            "latest_ebay_packet_present_resource_keys": (
                _safe_public_token_list(evidence.get("latest_ebay_packet_present_resource_keys"))
                if packet_is_current
                else []
            ),
            "latest_ebay_packet_missing_resource_keys": (
                _safe_public_token_list(evidence.get("latest_ebay_packet_missing_resource_keys"))
                if packet_is_current
                else []
            ),
            "latest_ebay_packet_current_connection": packet_is_current,
            "historical_ebay_packet_present": historical_packet_present,
            "ebay_token_refresh_success_count": _strict_nonnegative_int(evidence.get("ebay_token_refresh_success_count")),
            "secret_exposed": False,
        }
        if authenticated is True:
            public_evidence.update(
                {
                    "latest_ebay_packet_id": _safe_public_token(evidence.get("latest_ebay_packet_id")),
                    "latest_ebay_packet_created_at": _safe_public_token(evidence.get("latest_ebay_packet_created_at")),
                }
            )
        warning_items = _safe_public_readiness_items(readiness.get("items"))
        return {
            "service": "jiejing-saas-backend",
            "readiness_version": _safe_public_token(readiness.get("readiness_version")),
            "public_contract_version": "2026-07-15-public-readiness-current-ebay-evidence",
            "detail_scope": "public_summary",
            "internal_detail_required": True,
            "authenticated_summary": authenticated is True,
            "environment": _safe_public_token(
                readiness.get("environment"),
                allowed={"local", "test", "development", "staging", "production"},
            ),
            "production_ready": readiness.get("production_ready") is True,
            "beta_ready": readiness.get("beta_ready") is True,
            "can_accept_real_customers": readiness.get("can_accept_real_customers") is True,
            "real_platform_writes_enabled": readiness.get("real_platform_writes_enabled") is True,
            "requested_real_platform_writes": readiness.get("requested_real_platform_writes") is True,
            "blocker_count": _strict_nonnegative_int(readiness.get("blocker_count")),
            "warning_count": _strict_nonnegative_int(readiness.get("warning_count")),
            "items": warning_items,
            "product_evidence": public_evidence,
            "provider_status": {
                "billing": _public_safe_billing_summary(billing),
                "model_value": {
                    "status": "ready" if model_value_ready else _safe_public_token(model_value.get("status")) or "blocked",
                    "ready": model_value_ready,
                    "live_model_report_types": [
                        item
                        for item in model_value_report_types
                        if isinstance(item, str) and item in {"market.report", "listing.package"}
                    ],
                    "blocker_count": len(model_value_blockers),
                    "secret_exposed": False,
                },
                "ai_ceo_platform_model": {
                    "enabled": platform_model.get("enabled") is True,
                    "configured": platform_model.get("configured") is True,
                    "status": _safe_public_token(
                        platform_model.get("status"),
                        allowed={"ready", "not_enabled", "unsupported_provider", "missing_key", "live_disabled", "incomplete_configuration"},
                    ),
                    "provider": _safe_public_token(
                        platform_model.get("provider"),
                        allowed=_PUBLIC_MODEL_PROVIDERS,
                    ),
                    "model": _safe_public_token(platform_model.get("model")),
                    "trial_monthly_limit": _strict_nonnegative_int(platform_model.get("trial_monthly_limit")),
                    "trial_quota_scope": "account_month",
                    "usage_owner": "jiejing_platform_trial",
                    "quota_checked_by_backend": platform_model.get("quota_checked_by_backend") is True,
                    "hard_stop_on_exhaustion": platform_model.get("hard_stop_on_exhaustion") is True,
                    "exhaustion_blocker": "platform_default_model_trial_exhausted",
                    "merchant_byok_preferred": True,
                    "merchant_byok_not_counted_against_platform_trial": True,
                    "byok_bypasses_platform_trial": True,
                    "customer_visible_next_action": "save_account_ai_or_upgrade_plan",
                    "operator_cost_monitoring_required": True,
                    "frontend_can_grant_quota": False,
                    "frontend_gets_model_api_key": False,
                    "runtime_gets_model_api_key": False,
                    "secret_exposed": False,
                },
                "public_search": {
                    "provider": _safe_public_token(public_search.get("provider"), allowed={"tavily"}),
                    "configured": public_search.get("configured") is True,
                    "endpoint_host": _safe_public_token(public_search.get("endpoint_host"), allowed={"api.tavily.com"}),
                    "credential_present": public_search.get("credential_present") is True,
                    "ai_ceo_realtime_search_enabled": public_search.get("ai_ceo_realtime_search_enabled") is True,
                    "builtin_public_web_fallback_enabled": public_search.get("builtin_public_web_fallback_enabled") is True,
                    "builtin_stock_quote_fallback_enabled": public_search.get("builtin_stock_quote_fallback_enabled") is True,
                    "frontend_gets_search_api_key": False,
                    "runtime_gets_search_api_key": False,
                    "secret_exposed": False,
                },
                "media_generation": {
                    "contract_version": _safe_public_token(
                        media_generation.get("contract_version"),
                        allowed={"2026-07-05-media-generation-readiness"},
                    ),
                    "configured": media_generation.get("configured") is True,
                    "status": _safe_public_token(
                        media_generation.get("status"),
                        allowed={
                            "live_generation_ready_waiting_asset_review",
                            "dry_run_review_chain_ready_live_generation_disabled",
                            "dry_run_review_chain_ready_missing_media_driver",
                        },
                    ),
                    "live_generation_enabled": media_generation.get("live_generation_enabled") is True,
                    "live_image_generation_enabled": media_generation.get("live_image_generation_enabled") is True,
                    "live_video_generation_enabled": media_generation.get("live_video_generation_enabled") is True,
                    "live_provider_calls_allowed": media_generation.get("live_provider_calls_allowed") is True,
                    "asset_manifest_required": media_generation.get("asset_manifest_required") is True,
                    "asset_review_required": media_generation.get("asset_review_required") is True,
                    "fact_review_required": media_generation.get("fact_review_required") is True,
                    "human_review_required_before_listing": (
                        media_generation.get("human_review_required_before_listing") is True
                    ),
                    "cost_guard_required": media_generation.get("cost_guard_required") is True,
                    "spend_now_allowed": False,
                    "listing_use_requires_review": True,
                    "customer_visible_summary": _safe_public_text(media_generation.get("customer_visible_summary"), 1024),
                    "next_action": _safe_public_text(media_generation.get("next_action"), 1024),
                    "frontend_gets_media_api_key": False,
                    "runtime_gets_raw_secret": False,
                    "reports_get_raw_provider_response": False,
                    "raw_provider_response_stored": False,
                    "secret_exposed": False,
                },
            },
            "operational_health": {
                "status": (
                    _safe_public_token(readiness.get("operational_health", {}).get("status"))
                    if isinstance(readiness.get("operational_health"), dict)
                    else ""
                ),
                "detail_scope": "summary_only",
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def _public_operational_health_summary(self, operational_health: dict[str, Any], *, authenticated: bool) -> dict[str, Any]:
        database = operational_health.get("database_live_probe") if isinstance(operational_health.get("database_live_probe"), dict) else {}
        queue = operational_health.get("queue_runtime") if isinstance(operational_health.get("queue_runtime"), dict) else {}
        worker = operational_health.get("worker_runtime") if isinstance(operational_health.get("worker_runtime"), dict) else {}
        return {
            "contract_version": "2026-06-20-public-operational-health-summary",
            "status": operational_health.get("status", "unknown"),
            "environment": self.settings.environment,
            "detail_scope": "public_summary",
            "internal_detail_required": True,
            "authenticated_summary": authenticated,
            "database": {
                "status": database.get("status", "unknown"),
                "ready": database.get("status") == "ready",
                "secret_exposed": False,
            },
            "queue": {
                "status": queue.get("status", "unknown"),
                "ready": queue.get("status") == "ready",
                "secret_exposed": False,
            },
            "worker": {
                "status": worker.get("heartbeat_status") or worker.get("status") or "unknown",
                "ready": (worker.get("heartbeat_status") or worker.get("status")) == "ready",
                "secret_exposed": False,
            },
            "monitoring_safe_for_public_probe": True,
            "full_packet_requires_internal_admin": True,
            "secret_exposed": False,
        }

    def _rate_limit_status(self) -> dict[str, Any]:
        return {
            "contract_version": "2026-06-20-expensive-api-rate-limit-admin-only",
            "auth_rate_limit": {
                "enabled": True,
                "window_seconds": AUTH_RATE_LIMIT_WINDOW_SECONDS,
                "max_per_email": AUTH_RATE_LIMIT_MAX_PER_EMAIL,
                "max_per_ip": AUTH_RATE_LIMIT_MAX_PER_IP,
                "register_max_per_ip": AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP_DEFAULT,
                "max_global": self._auth_rate_limit_max_global("auth/login"),
                "register_max_global": self._auth_rate_limit_max_global("auth/register"),
                "storage": "shared_database_with_bounded_process_fallback",
                "protected_paths": ["auth/login", "auth/register", "auth/demo-session"],
                "secret_exposed": False,
            },
            "expensive_api_rate_limit": {
                "enabled": self._expensive_api_rate_limit_enabled(),
                "window_seconds": self._expensive_api_rate_limit_window_seconds(),
                "max_per_ip_per_route_group": self._expensive_api_rate_limit_max_per_ip(),
                "max_global_per_route_group": self._expensive_api_rate_limit_max_global(),
                "protected_prefixes": list(EXPENSIVE_API_RATE_LIMIT_PREFIXES),
                "protected_exact_paths": sorted(EXPENSIVE_API_RATE_LIMIT_EXACT_PATHS),
                "route_group_evidence": self._expensive_api_route_group_evidence(),
                "active_bucket_summary": self._expensive_api_bucket_summary(),
                "excluded_paths": [
                    "billing/webhook",
                    "oauth/ebay/callback",
                    "webhooks/ebay/marketplace-account-deletion",
                    "health",
                    "health/deep",
                    "readiness/product-saas",
                ],
                "bucket_count": sum(int(item.get("active_client_bucket_count") or 0) for item in self._expensive_api_bucket_summary()),
                "customer_visible": False,
                "operator_panel_only": True,
                "platform_internal_admin_only": True,
                "backend_status_requires_internal_admin": True,
                "protects_get_and_post": True,
                "edge_layer": "cloudflare_free_custom_rules_when_enabled",
                "origin_layer": "trusted_proxy_chain_plus_shared_database_bucket",
                "trusted_proxy_chain_parsing": True,
                "raw_client_ip_persisted": False,
                "protects_data_boundary": True,
                "prevents_complete_copy": False,
                "makes_scraping_costly": True,
                "frontend_gets_secret": False,
                "triggers_ebay_oauth": False,
                "calls_stripe_api": False,
                "triggers_real_charge": False,
                "triggers_real_platform_write": False,
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def _expensive_api_bucket_summary(self) -> list[dict[str, Any]]:
        window_seconds = self._expensive_api_rate_limit_window_seconds()
        try:
            rows = self.repository.rate_limit_bucket_summary(scope_prefix="expensive:")
        except Exception:
            return []
        summary: list[dict[str, Any]] = []
        for row in rows:
            parts = str(row.get("scope") or "").split(":")
            if len(parts) != 4 or parts[0] != "expensive" or parts[3] != "ip":
                continue
            summary.append(
                {
                    **row,
                    "method": parts[1],
                    "route_group": parts[2],
                    "window_seconds": window_seconds,
                }
            )
        return sorted(summary, key=lambda item: (str(item.get("route_group")), str(item.get("method"))))[:24]

    @staticmethod
    def _expensive_api_route_group_evidence() -> list[dict[str, Any]]:
        route_groups = [
            ("tasks", "workflow/job creation and task history", ["GET /tasks", "POST /tasks/product-workflow"]),
            ("reports", "AI/operator reports and report evidence", ["GET /reports"]),
            ("model", "model-backed AI CEO and value proof endpoints", ["GET /model/value-gate", "GET /model/providers/catalog"]),
            (
                "commercial",
                "merchant-safe launch readiness summary",
                [
                    "GET /commercial/launch-gate",
                ],
            ),
            (
                "owner",
                "platform-internal launch and payment cutover evidence",
                [
                    "GET /owner/billing-domain-cutover-rehearsal",
                    "GET /owner/billing-provider-evidence-register",
                    "GET /owner/edge-cutover-preflight",
                    "GET /owner/paid-launch-approval-packet",
                ],
            ),
            ("data-packets", "sanitized platform packet retrieval", ["GET /data-packets", "GET /data-packets/{packet_id}"]),
            (
                "stores",
                "store-scoped eBay workflows, AI CEO chat and connector operations",
                ["POST /stores/{store_id}/merchant-ceo/chat", "POST /stores/{store_id}/model/value-rehearsal"],
            ),
            (
                "ebay-read-only",
                "official eBay read-only adapters and sync status",
                ["GET /ebay-read-only/catalog", "POST /stores/{store_id}/ebay-read-only/sync"],
            ),
            ("ebay-write", "write adapter contracts and recovery checks", ["GET /ebay-write/adapter/status"]),
            ("ip-risk-screening", "policy, IP and copycat risk screening", ["GET /ip-risk-screening"]),
            (
                "merchant-memory",
                "operating memory and audit evidence",
                ["GET /merchant-memory", "POST /stores/{store_id}/merchant-memory/refresh"],
            ),
            (
                "merchant-ceo-commands",
                "AI CEO command persistence",
                ["GET /stores/{store_id}/merchant-ceo/commands/latest", "POST /stores/{store_id}/merchant-ceo/commands"],
            ),
            (
                "ai-ceo",
                "account-scoped AI CEO cross-device chat history",
                ["GET /ai-ceo/chat-history", "POST /ai-ceo/chat-history/sync"],
            ),
            ("confirmations", "decision-center actions and preflight", ["GET /confirmations", "POST /confirmations/{id}/preflight"]),
            ("execution-results", "execution audit and recovery evidence", ["GET /execution-results"]),
            ("audit-logs", "tenant audit trail", ["GET /audit-logs"]),
            ("post-publish", "post-publish cockpit evidence and cleanup boundary", ["GET /post-publish/cockpit"]),
            (
                "billing",
                "checkout, portal, billing test events and manual beta payment orders",
                ["POST /billing/checkout-session", "POST /billing/test-event", "POST /billing/manual-beta/orders"],
            ),
            (
                "owner",
                "platform-internal-admin-only launch and production-release evidence",
                [
                    "GET /owner/launch-control",
                    "GET /owner/production-release-gate",
                    "GET /owner/production-evidence-ledger",
                    "GET /security/rate-limit/status",
                ],
            ),
        ]
        return [
            {
                "route_group": route_group,
                "why_high_cost": why,
                "protection": "backend_ip_route_group_bucket",
                "edge_layer": "cloudflare_free_custom_rules_when_enabled",
                "origin_layer": "backend_ip_route_group_bucket",
                "protected_methods": ["GET", "POST"],
                "example_paths": examples,
                "auth_required_after_bucket": True,
                "customer_visible": False,
                "status_endpoint_requires_internal_admin": True,
                "secret_exposed": False,
            }
            for route_group, why, examples in route_groups
        ]

    @staticmethod
    def _is_expensive_api_rate_limited_path(path: str) -> bool:
        normalized = str(path or "").strip("/")
        if normalized in EXPENSIVE_API_RATE_LIMIT_EXACT_PATHS:
            return True
        return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in EXPENSIVE_API_RATE_LIMIT_PREFIXES)

    @staticmethod
    def _expensive_api_route_group(path: str) -> str:
        normalized = str(path or "").strip("/")
        for prefix in EXPENSIVE_API_RATE_LIMIT_PREFIXES:
            clean = prefix.rstrip("/")
            if normalized == clean or normalized.startswith(prefix):
                return clean
        return normalized.split("/", 1)[0] or "root"

    @staticmethod
    def _expensive_api_rate_limit_enabled() -> bool:
        value = os.environ.get("JIEJING_EXPENSIVE_API_RATE_LIMIT_ENABLED")
        if value is None:
            return True
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _expensive_api_rate_limit_window_seconds() -> int:
        return _positive_int_env("JIEJING_EXPENSIVE_API_RATE_LIMIT_WINDOW_SECONDS", EXPENSIVE_API_RATE_LIMIT_WINDOW_SECONDS_DEFAULT)

    @staticmethod
    def _expensive_api_rate_limit_max_per_ip() -> int:
        return _positive_int_env("JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP", EXPENSIVE_API_RATE_LIMIT_MAX_PER_IP_DEFAULT)

    @staticmethod
    def _expensive_api_rate_limit_max_global() -> int:
        return _positive_int_env("JIEJING_EXPENSIVE_API_RATE_LIMIT_MAX_GLOBAL", EXPENSIVE_API_RATE_LIMIT_MAX_GLOBAL_DEFAULT)

    @staticmethod
    def _auth_rate_limit_max_global(action: str) -> int:
        if str(action).rstrip("/").endswith("auth/register"):
            return _positive_int_env(
                "JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_GLOBAL",
                AUTH_REGISTER_RATE_LIMIT_MAX_GLOBAL_DEFAULT,
            )
        return _positive_int_env("JIEJING_AUTH_RATE_LIMIT_MAX_GLOBAL", AUTH_RATE_LIMIT_MAX_GLOBAL_DEFAULT)

    @staticmethod
    def _auth_rate_limit_max_per_ip(action: str) -> int:
        if str(action).rstrip("/").endswith("auth/register"):
            return _positive_int_env(
                "JIEJING_AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP",
                AUTH_REGISTER_RATE_LIMIT_MAX_PER_IP_DEFAULT,
            )
        return AUTH_RATE_LIMIT_MAX_PER_IP

    def _client_ip_for_rate_limit(self) -> str:
        peer_raw = str(self.client_address[0] if self.client_address else "").strip()
        peer = _parse_ip_address(peer_raw)
        if peer is None:
            return "unknown"
        trusted_networks = _trusted_proxy_networks()
        if not _ip_in_networks(peer, trusted_networks):
            return str(peer)[:80]
        forwarded = [
            parsed
            for parsed in (_parse_ip_address(item.strip()) for item in str(self.headers.get("x-forwarded-for") or "").split(","))
            if parsed is not None
        ]
        chain = [*forwarded, peer]
        for candidate in reversed(chain):
            if not _ip_in_networks(candidate, trusted_networks):
                return str(candidate)[:80]
        if forwarded:
            return str(forwarded[0])[:80]
        if peer:
            return str(peer)[:80]
        return "unknown"

    def _demo_session_bootstrap_allowed(self) -> bool:
        if self.settings.environment in {"local_dev", "test"}:
            return True
        if os.environ.get("JIEJING_ENABLE_DEMO_SESSION_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
        expected = os.environ.get("JIEJING_OPERATOR_BOOTSTRAP_SECRET") or ""
        provided = self.headers.get("x-jiejing-operator-secret", "")
        return bool(expected and provided and hmac.compare_digest(provided, expected))

    def _require_permission(self, identity: dict[str, Any], permission: str) -> bool:
        member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
        if member and has_permission(str(member.get("role") or ""), permission):
            return True
        self._send_error(HTTPStatus.FORBIDDEN, f"missing permission: {permission}")
        return False

    def _is_platform_internal_admin(self, identity: dict[str, Any]) -> bool:
        allowlist = set(self.settings.internal_admin_emails)
        if not allowlist:
            return False
        email = str(identity.get("email") or "").strip().lower()
        if email not in allowlist:
            return False
        member = self.repository.get_team_member(company_id=identity["company_id"], user_id=identity["user_id"])
        role = str(member.get("role") or "").lower() if member else ""
        return role in {"owner", "admin"}

    def _require_platform_internal_admin(self, identity: dict[str, Any], label: str) -> bool:
        if self._is_platform_internal_admin(identity):
            return True
        self._send_error(HTTPStatus.FORBIDDEN, f"{label} is platform-internal admin only")
        return False

    @staticmethod
    def _merchant_safe_billing_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Build a new merchant contract from positive allowlists only.

        The internal billing plan intentionally contains launch evidence and
        provider diagnostics.  None of its nested containers are reused here.
        """

        launch = plan.get("mainland_payment_launch") if isinstance(plan.get("mainland_payment_launch"), dict) else {}
        mainland_payment = _merchant_safe_mainland_payment(launch)
        quota = plan.get("quota_contract") if isinstance(plan.get("quota_contract"), dict) else {}
        return {
            "contract_version": _safe_bounded_text(plan.get("contract_version"), 128),
            "billing_ready_for_private_beta": plan.get("billing_ready_for_private_beta") is True,
            "billing_ready_for_paid_launch": False,
            "provider": {
                "provider": "wechat_pay_native",
                "checkout_mode": "native_qr",
                "billing_mode": "one_time_30_day_plan",
                "available": False,
                "provider_configured": mainland_payment["provider_configured"],
                "customer_visible": True,
                "charge_now_allowed": False,
                "triggers_real_charge": False,
                "frontend_gets_payment_secret": False,
                "secret_exposed": False,
            },
            "plan_catalog": _merchant_safe_plan_catalog(plan.get("plan_catalog")),
            "add_on_catalog": _merchant_safe_add_on_catalog(plan.get("add_on_catalog")),
            "quota_contract": {
                "enabled": quota.get("enabled") is True,
                "metered_units": _merchant_safe_metered_units(quota.get("metered_units")),
                "hard_stop_on_quota_exhaustion": quota.get("hard_stop_on_quota_exhaustion") is True,
                "merchant_visible_usage_required": quota.get("merchant_visible_usage_required") is True,
                "merchant_byok_chat_not_counted_as_workflow_task": (
                    quota.get("merchant_byok_chat_not_counted_as_workflow_task") is True
                ),
                "media_generation_uses_separate_media_points": (
                    quota.get("media_generation_uses_separate_media_points") is True
                ),
                "media_points_are_not_bundled_with_subscription": (
                    quota.get("media_points_are_not_bundled_with_subscription") is True
                ),
            },
            "mainland_payment": mainland_payment,
            "merchant_launch_path": _merchant_safe_launch_path(
                plan.get("merchant_launch_path"),
                mainland_payment=mainland_payment,
                quota_enabled=quota.get("enabled") is True,
            ),
            "paid_launch_blockers": [mainland_payment["next_blocker"]],
            "billing_test_rehearsal_summary": _merchant_safe_rehearsal_summary(
                plan.get("billing_test_rehearsal_summary")
            ),
            "subscription_quota_shutdown_closure": _merchant_safe_shutdown_summary(
                plan.get("subscription_quota_shutdown_closure")
            ),
            "billing_incident_runbook": _merchant_safe_incident_runbook(plan.get("billing_incident_runbook")),
            "customer_billing_trust_packet": _merchant_safe_trust_packet(
                plan.get("customer_billing_trust_packet")
            ),
            "confirmation_boundary": {
                "billing_changes_need_owner_or_admin": True,
                "real_platform_writes_not_included_in_any_current_plan": True,
                "refunds_and_payment_disputes_need_human_operator": True,
            },
            "public_charging_allowed": False,
            "charge_now_allowed": False,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "real_platform_writes_enabled": False,
            "frontend_gets_payment_secret": False,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "customer_visible": True,
            "internal_launch_evidence_visible": False,
            "secret_exposed": False,
        }

    def _platform_model_trial_guardrail(self, *, limit: int | None = None) -> dict[str, Any]:
        monthly_limit = (
            int(limit)
            if limit is not None
            else _nonnegative_int_env(
                PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV,
                PLATFORM_MODEL_TRIAL_DEFAULT_MONTHLY_LIMIT,
            )
        )
        return {
            "trial_quota_scope": "account_month",
            "usage_owner": "jiejing_platform_trial",
            "usage_owner_label": "捷境试用 AI",
            "quota_checked_by_backend": True,
            "monthly_limit": monthly_limit,
            "hard_stop_on_exhaustion": True,
            "exhaustion_blocker": "platform_default_model_trial_exhausted",
            "hard_stop_scope": "platform_managed_default_ai_only",
            "merchant_byok_not_counted": True,
            "byok_bypasses_platform_trial": True,
            "counted_model_resolution_modes": ["platform_managed_default"],
            "byok_model_resolution_modes_not_counted": ["account_byok", "company_byok_default", "merchant_byok"],
            "customer_visible_next_action": "save_account_ai_or_upgrade_plan",
            "operator_cost_monitoring_required": True,
            "frontend_can_grant_quota": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    def _platform_model_trial_quota(self, *, identity: dict[str, Any]) -> dict[str, Any]:
        limit = _nonnegative_int_env(
            PLATFORM_MODEL_TRIAL_MONTHLY_LIMIT_ENV,
            PLATFORM_MODEL_TRIAL_DEFAULT_MONTHLY_LIMIT,
        )
        guardrail = self._platform_model_trial_guardrail(limit=limit)
        period = time.strftime("%Y-%m", time.gmtime())
        used = 0
        for task in self.repository.list_tasks(company_id=identity["company_id"]):
            if str(task.get("created_at") or "")[:7] != period:
                continue
            if str(task.get("task_type") or "") != "merchant_ceo_chat":
                continue
            task_input = task.get("input") if isinstance(task.get("input"), dict) else {}
            task_output = task.get("output") if isinstance(task.get("output"), dict) else {}
            chat = task_output.get("ai_ceo_chat") if isinstance(task_output.get("ai_ceo_chat"), dict) else {}
            model_client = chat.get("model_client") if isinstance(chat.get("model_client"), dict) else {}
            platform_used = (
                task_input.get("model_resolution_mode") == "platform_managed_default"
                or task_input.get("model_usage_owner") == "jiejing_platform_trial"
                or (
                    model_client.get("merchant_pays_provider_directly") is False
                    and model_client.get("jiejing_pays_provider_usage") is True
                )
            )
            if platform_used:
                used += 1
        activation = self.repository.get_platform_trial_activation(company_id=identity["company_id"])
        if activation is None:
            activation_status = "grandfathered_active"
            activation_allowed = True
        else:
            activation_status = str(activation.get("status") or "verification_required")
            activation_allowed = activation.get("platform_trial_allowed") is True
        remaining = max(0, limit - used) if limit > 0 else 0
        quota_available = limit <= 0 or used < limit
        allowed = activation_allowed and quota_available
        return {
            "contract_version": "2026-07-03-ai-ceo-platform-model-trial-quota",
            **guardrail,
            "scope": "account_month",
            "period": period,
            "monthly_limit": limit,
            "used": used,
            "remaining": remaining,
            "allowed": allowed,
            "activation_status": activation_status,
            "platform_trial_activated": activation_allowed,
            "merchant_byok_unaffected": True,
            "blocked_by": (
                "platform_trial_activation_required"
                if not activation_allowed
                else ("platform_default_model_trial_exhausted" if not quota_available else "")
            ),
            "unlimited_when_limit_zero": limit <= 0,
            "quota_source": "backend_task_audit",
            "account_space_id_present": bool(identity.get("company_id")),
            "requires_merchant_byok_or_plan_upgrade_when_exhausted": True,
            "secret_exposed": False,
        }

    def _platform_trial_activation_for_registration(
        self,
        *,
        user: dict[str, Any],
        challenge_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        required = _env_bool(
            "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED",
            self.settings.environment in {"staging", "production"},
        )
        verification = challenge_verification if isinstance(challenge_verification, dict) else {}
        challenge_attested = verification.get("verified") is True
        status = "active"
        allowed = True
        reason = "activation_guard_not_required"
        if required and not challenge_attested:
            status = "verification_required"
            allowed = False
            reason = str(verification.get("decision_reason") or "challenge_required")
        elif required:
            client_subject = self._client_ip_for_rate_limit()
            checks = (
                (
                    "platform_trial_activation:daily:ip",
                    client_subject,
                    _positive_int_env(
                        "JIEJING_PLATFORM_TRIAL_ACTIVATION_MAX_PER_IP_PER_DAY",
                        PLATFORM_TRIAL_ACTIVATION_MAX_PER_IP_DEFAULT,
                    ),
                ),
                (
                    "platform_trial_activation:daily:global",
                    "global",
                    _positive_int_env(
                        "JIEJING_PLATFORM_TRIAL_ACTIVATION_MAX_GLOBAL_PER_DAY",
                        PLATFORM_TRIAL_ACTIVATION_MAX_GLOBAL_DEFAULT,
                    ),
                ),
            )
            for scope, subject, bucket_limit in checks:
                result = self._consume_rate_limit(
                    scope=scope,
                    subject=subject,
                    limit=bucket_limit,
                    window_seconds=PLATFORM_TRIAL_ACTIVATION_WINDOW_SECONDS,
                    local_buckets=self.platform_trial_activation_rate_limit_buckets,
                    local_lock=self.platform_trial_activation_rate_limit_lock,
                )
                if result.get("allowed") is not True:
                    status = "activation_budget_exhausted"
                    allowed = False
                    reason = "daily_activation_budget_exhausted"
                    break
            if allowed:
                reason = "server_verified_challenge_and_daily_budget_passed"
        return self.repository.upsert_platform_trial_activation(
            company_id=str(user["default_company_id"]),
            user_id=str(user["user_id"]),
            status=status,
            platform_trial_allowed=allowed,
            welcome_media_points_granted=300 if allowed else 0,
            requires_challenge=required,
            challenge_attested=challenge_attested,
            decision_reason=reason,
        )

    def _require_quota(self, identity: dict[str, Any], action_unit: str) -> bool:
        evaluation = evaluate_quota_action(
            self.settings,
            self.repository,
            company_id=identity["company_id"],
            action_unit=action_unit,
        )
        if evaluation.get("allowed") is True:
            return True
        recovery = self._recover_missing_private_beta_entitlement(identity=identity, evaluation=evaluation)
        if recovery.get("ok") is True:
            evaluation = evaluate_quota_action(
                self.settings,
                self.repository,
                company_id=identity["company_id"],
                action_unit=action_unit,
            )
            if evaluation.get("allowed") is True:
                return True
            evaluation = {**evaluation, "private_beta_entitlement_recovery": recovery}
        self._send_json(
            {
                "error": "quota exhausted",
                "status": int(HTTPStatus.PAYMENT_REQUIRED),
                "quota": evaluation,
                "real_platform_writes_enabled": False,
                "secret_exposed": False,
            },
            status=HTTPStatus.PAYMENT_REQUIRED,
        )
        return False

    def _recover_missing_private_beta_entitlement(self, *, identity: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """Recover legacy staging accounts that predate automatic beta entitlement seeding."""

        usage = evaluation.get("usage") if isinstance(evaluation.get("usage"), dict) else {}
        subscription = usage.get("subscription") if isinstance(usage.get("subscription"), dict) else {}
        reason = str(evaluation.get("reason") or subscription.get("block_reason") or "")
        if reason != "billing_test_subscription_not_rehearsed":
            return {"ok": False, "status": "not_missing_test_subscription", "secret_exposed": False}
        try:
            recovered = apply_test_billing_event(
                self.repository,
                company_id=str(identity.get("company_id") or ""),
                user_id=str(identity.get("user_id") or ""),
                plan_key="starter",
                action="activate",
                event_nonce=f"legacy_recovery:{time.time_ns()}",
            )
        except Exception as exc:  # pragma: no cover - defensive legacy recovery guardrail
            return {
                "ok": False,
                "status": "private_beta_entitlement_recovery_failed",
                "reason": exc.__class__.__name__,
                "creates_real_checkout_session": False,
                "calls_stripe_api": False,
                "triggers_real_charge": False,
                "secret_exposed": False,
            }
        return {
            "ok": bool(recovered.get("ok")),
            "status": recovered.get("status") or "private_beta_entitlement_recovery_attempted",
            "provider": recovered.get("provider"),
            "action": recovered.get("action"),
            "creates_real_checkout_session": False,
            "calls_stripe_api": False,
            "triggers_real_charge": False,
            "secret_exposed": False,
        }

    def _model_settings_secret_refs_for_store(self, *, identity: dict[str, Any], store_id: str) -> list[dict[str, Any]]:
        groups = self._model_secret_ref_groups_for_store(identity=identity, store_id=store_id)
        return [
            *[self._model_ref_with_effective_scope(item, "account") for item in groups["account"]],
            *[self._model_ref_with_effective_scope(item, "store") for item in groups["store"]],
            *[self._model_ref_with_effective_scope(item, "company") for item in groups["company"]],
        ]

    def _model_secret_ref_groups_for_store(self, *, identity: dict[str, Any], store_id: str) -> dict[str, list[dict[str, Any]]]:
        all_refs = [
            item
            for item in self.repository.list_secret_refs(company_id=identity["company_id"])
            if str(item.get("purpose") or "") == MODEL_SECRET_PURPOSE
        ]
        groups: dict[str, list[dict[str, Any]]] = {"account": [], "store": [], "company": []}
        seen: set[str] = set()
        for item in all_refs:
            secret_ref = str(item.get("secret_ref") or "")
            if not secret_ref or secret_ref in seen:
                continue
            scope = self._model_secret_ref_scope_for_identity(item, identity=identity, store_id=store_id)
            if scope in groups:
                groups[scope].append(item)
                seen.add(secret_ref)
        return groups

    @staticmethod
    def _model_secret_ref_scope_for_identity(item: dict[str, Any], *, identity: dict[str, Any], store_id: str) -> str:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        explicit_scope = str(
            metadata.get("model_connection_scope")
            or metadata.get("scope")
            or metadata.get("connection_scope")
            or ""
        ).strip().lower()
        ref_store_id = str(item.get("store_id") or "")
        created_by = str(item.get("created_by") or "")
        user_id = str(identity.get("user_id") or "")
        if explicit_scope == "company":
            return "company"
        if explicit_scope == "store":
            return "store" if ref_store_id == store_id else ""
        if created_by and created_by == user_id:
            return "account"
        if not ref_store_id:
            return ""
        if ref_store_id == store_id:
            return "store"
        return ""

    @staticmethod
    def _first_ready_model_ref(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in items
                if str(item.get("status") or "") in READY_MODEL_SECRET_STATUSES
            ),
            None,
        )

    @staticmethod
    def _model_ref_with_effective_scope(item: dict[str, Any], scope: str) -> dict[str, Any]:
        copied = dict(item)
        metadata = dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
        metadata["model_connection_scope"] = scope
        metadata["scope"] = scope
        copied["metadata"] = metadata
        return copied

    def _resolve_model_client_for_store(self, *, identity: dict[str, Any], store_id: str, body: dict[str, Any]) -> dict[str, Any]:
        requested_secret_ref = str(body.get("model_secret_ref") or "").strip()
        use_byok = body.get("use_merchant_byok") is not False
        if not requested_secret_ref and not use_byok:
            platform_resolution = self._resolve_platform_default_model_client(body=body)
            if platform_resolution.get("status") == "resolved":
                return platform_resolution
            return {"status": "not_requested", "mode": "env_model_or_none", "secret_exposed": False}
        grouped_refs = self._model_secret_ref_groups_for_store(identity=identity, store_id=store_id)
        account_refs = grouped_refs["account"]
        store_refs = grouped_refs["store"]
        company_refs = grouped_refs["company"]
        eligible_refs = [*account_refs, *store_refs, *company_refs]
        selected = None
        selected_mode = "merchant_byok"
        selected_scope = "store"
        if requested_secret_ref:
            selected = next((item for item in eligible_refs if item.get("secret_ref") == requested_secret_ref), None)
            if not selected:
                return {
                    "status": "blocked",
                    "blocked_by": ["model_secret_ref_not_found"],
                    "requested_secret_ref": requested_secret_ref,
                    "secret_exposed": False,
                }
            selected_scope = self._model_secret_ref_scope_for_identity(selected, identity=identity, store_id=store_id) or "store"
            selected_mode = (
                "account_byok"
                if selected_scope == "account"
                else "company_byok_default"
                if selected_scope == "company"
                else "merchant_byok"
            )
        else:
            selected = self._first_ready_model_ref(account_refs)
            if selected:
                selected_mode = "account_byok"
                selected_scope = "account"
            else:
                selected = self._first_ready_model_ref(store_refs)
                if selected:
                    selected_mode = "merchant_byok"
                    selected_scope = "store"
        if not selected:
            selected = self._first_ready_model_ref(company_refs)
            if selected:
                selected_mode = "company_byok_default"
                selected_scope = "company"
            else:
                platform_resolution = self._resolve_platform_default_model_client(body=body)
                if platform_resolution.get("status") == "resolved":
                    return platform_resolution
                return {
                    "status": "not_configured",
                    "mode": "merchant_byok_or_platform_default",
                    "blocked_by": ["merchant_model_api_key_not_saved", "platform_model_default_not_configured"],
                    "platform_model_resolution": {
                        key: value
                        for key, value in platform_resolution.items()
                        if key not in {"model_client", "secret_value"}
                    },
                    "secret_exposed": False,
                }
        if str(selected.get("status") or "") not in READY_MODEL_SECRET_STATUSES:
            return {
                "status": "blocked",
                "blocked_by": ["model_secret_ref_not_ready"],
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
        provider_key = str(metadata.get("provider_key") or selected.get("provider") or "")
        definition = get_model_provider(provider_key)
        if not definition:
            return {
                "status": "blocked",
                "blocked_by": ["unsupported_model_provider"],
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        if not definition.supported_live_adapter:
            return {
                "status": "blocked",
                "blocked_by": ["model_provider_adapter_not_implemented"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        resolver = VaultSecretResolver(self.settings)
        resolved = resolver.resolve_secret(
            secret_ref=selected,
            requested_by="model_provider_client",
            task_scope="model_value_rehearsal",
            allowed_purposes=[MODEL_SECRET_PURPOSE],
        )
        if not resolved.get("ok"):
            return {
                "status": "blocked",
                "blocked_by": resolved.get("blocked_by") or ["model_secret_resolve_blocked"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        try:
            model_client = build_model_client_from_byok_secret(
                provider_key=definition.provider_key,
                api_key=str(resolved.get("secret_value") or ""),
                model=str(body.get("model") or metadata.get("model") or definition.default_model),
                base_url=str(body.get("base_url") or metadata.get("base_url") or definition.default_base_url),
            )
        except ValueError as exc:
            return {
                "status": "blocked",
                "blocked_by": [str(exc)],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        if hasattr(model_client, "configured") and not model_client.configured():
            return {
                "status": "blocked",
                "blocked_by": ["model_client_not_configured_or_live_disabled"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_ref": selected.get("secret_ref"),
                "secret_exposed": False,
            }
        return {
            "status": "resolved",
            "mode": selected_mode,
            "provider_key": definition.provider_key,
            "provider_label": definition.label,
            "api_style": definition.api_style,
            "model": getattr(model_client, "model", "") or metadata.get("model") or definition.default_model,
            "endpoint_host": urlparse(getattr(model_client, "endpoint", "") or "").netloc,
            "secret_ref": selected.get("secret_ref"),
            "secret_ref_scope": selected_scope,
            "model_client": model_client,
            "merchant_pays_provider_directly": True,
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "reports_get_model_api_key": False,
            "secret_exposed": False,
        }

    def _resolve_platform_default_model_client(self, *, body: dict[str, Any]) -> dict[str, Any]:
        provider_key = (
            os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_PROVIDER")
            or os.environ.get("JIEJING_MODEL_PROVIDER")
            or ""
        ).strip()
        explicit_api_key = (os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_API_KEY") or "").strip()
        platform_enabled = _env_bool("JIEJING_AI_CEO_PLATFORM_MODEL_ENABLED", default=bool(explicit_api_key))
        if not platform_enabled:
            return {
                "status": "not_configured",
                "mode": "platform_managed_default",
                "blocked_by": ["platform_model_default_not_enabled"],
                "secret_exposed": False,
            }
        if not provider_key:
            provider_key = "deepseek" if os.environ.get("DEEPSEEK_API_KEY") else "openai"
        definition = get_model_provider(provider_key)
        if not definition:
            return {
                "status": "blocked",
                "mode": "platform_managed_default",
                "blocked_by": ["unsupported_platform_model_provider"],
                "provider_key": provider_key,
                "secret_exposed": False,
            }
        if not definition.supported_live_adapter:
            return {
                "status": "blocked",
                "mode": "platform_managed_default",
                "blocked_by": ["platform_model_provider_adapter_not_implemented"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_exposed": False,
            }
        api_key = explicit_api_key
        if not api_key:
            if definition.provider_key == "deepseek":
                api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
            if not api_key:
                api_key = (os.environ.get("JIEJING_MODEL_API_KEY") or "").strip()
        configured_model = (
            (os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL") or "").strip()
            or (os.environ.get("JIEJING_MODEL") or "").strip()
            or definition.default_model
        )
        model = platform_default_serving_model(provider=definition.provider_key, configured_model=configured_model)
        base_url = normalize_model_api_base_url(
            provider_key=definition.provider_key,
            base_url=(
                os.environ.get("JIEJING_AI_CEO_PLATFORM_MODEL_BASE_URL")
                or os.environ.get("JIEJING_MODEL_BASE_URL")
                or definition.default_base_url
            ),
        )
        if not api_key:
            return {
                "status": "not_configured",
                "mode": "platform_managed_default",
                "blocked_by": ["platform_model_api_key_not_configured"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "model": model,
                "secret_exposed": False,
            }
        try:
            model_client = build_model_client_from_byok_secret(
                provider_key=definition.provider_key,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
        except ValueError as exc:
            return {
                "status": "blocked",
                "mode": "platform_managed_default",
                "blocked_by": [str(exc)],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "secret_exposed": False,
            }
        fallback_model = (
            os.environ.get("JIEJING_AI_CEO_PLATFORM_FALLBACK_MODEL")
            or (configured_model if configured_model != model else "")
        ).strip()
        if fallback_model and fallback_model != model:
            try:
                fallback_model_client = build_model_client_from_byok_secret(
                    provider_key=definition.provider_key,
                    api_key=api_key,
                    model=fallback_model,
                    base_url=base_url,
                )
                setattr(model_client, "jiejing_fallback_model_client", fallback_model_client)
            except ValueError:
                fallback_model = ""
        if hasattr(model_client, "configured") and not model_client.configured():
            return {
                "status": "blocked",
                "mode": "platform_managed_default",
                "blocked_by": ["platform_model_client_not_configured_or_live_disabled"],
                "provider_key": definition.provider_key,
                "provider_label": definition.label,
                "model": model,
                "secret_exposed": False,
            }
        return {
            "status": "resolved",
            "mode": "platform_managed_default",
            "provider_key": definition.provider_key,
            "provider_label": definition.label,
            "api_style": definition.api_style,
            "model": getattr(model_client, "model", "") or model,
            "configured_model": configured_model,
            "fallback_model": fallback_model,
            "fallback_policy": "platform_default_transient_failover" if fallback_model else "disabled",
            "endpoint_host": urlparse(getattr(model_client, "endpoint", "") or "").netloc,
            "secret_ref": "",
            "secret_ref_scope": "platform",
            "model_client": model_client,
            "merchant_pays_provider_directly": False,
            "jiejing_pays_provider_usage": True,
            "platform_trial": {
                **self._platform_model_trial_guardrail(),
                "enabled": True,
                "requires_merchant_byok_or_plan_upgrade_when_exhausted": True,
                "secret_exposed": False,
            },
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "reports_get_model_api_key": False,
            "secret_exposed": False,
        }

    def _verify_saved_model_connection(
        self,
        *,
        identity: dict[str, Any],
        store_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        refs = self._model_settings_secret_refs_for_store(identity=identity, store_id=store_id)
        requested_secret_ref = str(body.get("model_secret_ref") or "").strip()
        selected = (
            next((item for item in refs if str(item.get("secret_ref") or "") == requested_secret_ref), None)
            if requested_secret_ref
            else next(
                (
                    item
                    for item in refs
                    if str(item.get("status") or "") in READY_MODEL_SECRET_STATUSES | {"stored_unverified"}
                ),
                refs[0] if refs else None,
            )
        )
        if not selected:
            return {
                "error": "当前账号还没有可检测的 AI 连接。",
                "verified": False,
                "requires_api_key_reentry": True,
                "can_retry_verification": False,
                "blocked_by": ["current_account_model_connection_missing"],
                "model_settings": public_model_settings_from_secret_refs(refs),
                "secret_exposed": False,
            }
        selected_status = str(selected.get("status") or "")
        storage_ready = selected_status in READY_MODEL_SECRET_STATUSES or selected_status == "stored_unverified"
        if not storage_ready:
            return {
                "error": "这次 AI 连接没有写入安全存储，需要重新粘贴一次连接信息。",
                "verified": False,
                "requires_api_key_reentry": True,
                "can_retry_verification": False,
                "blocked_by": ["model_secret_storage_failed"],
                "model_settings": public_model_settings_from_secret_refs(refs),
                "secret_exposed": False,
            }
        metadata = selected.get("metadata") if isinstance(selected.get("metadata"), dict) else {}
        provider_key = str(metadata.get("provider_key") or selected.get("provider") or "")
        definition = get_model_provider(provider_key)
        if not definition:
            return {
                "error": "当前 AI 服务商暂不支持检测。",
                "verified": False,
                "requires_api_key_reentry": False,
                "can_retry_verification": False,
                "blocked_by": ["unsupported_model_provider"],
                "model_settings": public_model_settings_from_secret_refs(refs),
                "secret_exposed": False,
            }
        resolver = VaultSecretResolver(self.settings)
        resolved = resolver.resolve_secret(
            secret_ref=selected,
            requested_by="model_provider_client",
            task_scope="model_connection_verification",
            allowed_purposes=[MODEL_SECRET_PURPOSE],
        )
        if not resolved.get("ok"):
            return {
                "error": "已保存的 AI 连接暂时无法从安全存储读取。",
                "verified": False,
                "requires_api_key_reentry": False,
                "can_retry_verification": True,
                "blocked_by": resolved.get("blocked_by") or ["model_secret_resolve_blocked"],
                "model_settings": public_model_settings_from_secret_refs(refs),
                "secret_exposed": False,
            }
        verification = self._verify_model_connection_from_secret_value(
            provider_key=definition.provider_key,
            api_key=str(resolved.get("secret_value") or ""),
            model=str(metadata.get("model") or definition.default_model),
            base_url=str(metadata.get("base_url") or definition.default_base_url),
        )
        verified = verification.get("verified") is True
        updated = self.repository.update_secret_reference_status(
            company_id=identity["company_id"],
            store_id=selected.get("store_id"),
            secret_ref=str(selected.get("secret_ref") or ""),
            status="ready" if verified else "stored_unverified",
            user_id=identity["user_id"],
            metadata_patch={
                "verification_status": "verified" if verified else "failed",
                "verification_error_code": verification.get("error_code") or "",
                "verification_blocked_by": verification.get("blocked_by") or [],
                "verified_at": verification.get("verified_at") or "",
                "secret_exposed": False,
            },
        )
        settings = public_model_settings_from_secret_refs(
            self._model_settings_secret_refs_for_store(identity=identity, store_id=store_id)
        )
        return {
            "error": "" if verified else "AI 连接已经保存，但服务商检测仍未通过。",
            "verified": verified,
            "requires_api_key_reentry": False,
            "can_retry_verification": not verified,
            "blocked_by": verification.get("blocked_by") or [],
            "verification_error_code": verification.get("error_code") or "",
            "model_secret_ref": updated,
            "model_settings": settings,
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "reports_get_model_api_key": False,
            "secret_exposed": False,
        }

    @staticmethod
    def _verify_model_connection_from_secret_value(
        *,
        provider_key: str,
        api_key: str,
        model: str,
        base_url: str,
    ) -> dict[str, Any]:
        try:
            client = build_model_client_from_byok_secret(
                provider_key=provider_key,
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout_seconds=20,
            )
            result = client.generate_text(
                system_prompt="You are performing a private connection check. Reply with OK only.",
                user_prompt="Jiejing model connection check.",
                temperature=0.0,
                max_output_tokens=16,
                timeout_seconds=20,
            )
            if not str(result.get("text") or "").strip():
                return {
                    "status": "failed",
                    "verified": False,
                    "error_code": "empty_model_verification_response",
                    "blocked_by": ["empty_model_verification_response"],
                    "secret_exposed": False,
                }
        except Exception as exc:  # pragma: no cover - provider dependent
            error_code = SaaSBackendHandler._safe_model_verification_error_code(exc)
            return {
                "status": "failed",
                "verified": False,
                "error_code": error_code,
                "blocked_by": [error_code],
                "secret_exposed": False,
            }
        return {
            "status": "verified",
            "verified": True,
            "error_code": "",
            "blocked_by": [],
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "secret_exposed": False,
        }

    @staticmethod
    def _safe_model_verification_error_code(exc: Exception) -> str:
        text = f"{exc.__class__.__name__}: {exc}".lower()
        if any(marker in text for marker in ("401", "unauthorized", "authentication", "invalid api key", "invalid_api_key")):
            return "model_authentication_failed"
        if any(marker in text for marker in ("quota", "billing", "insufficient", "balance", "payment", "credit")):
            return "model_quota_or_billing_blocked"
        if any(marker in text for marker in ("model_not_found", "model not found", "invalid model", "does not exist")):
            return "model_name_not_available"
        if any(marker in text for marker in ("timeout", "timed out", "etimedout", "econnreset")):
            return "model_provider_timeout"
        return "model_provider_verification_failed"

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("content-length", "0") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "invalid content-length") from exc
        if length <= 0:
            return {}
        if length > MAX_JSON_BODY_BYTES:
            self.close_connection = True
            raise RequestBodyError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "json body too large")
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(_positive_int_env("JIEJING_REQUEST_BODY_TIMEOUT_SECONDS", 15))
        try:
            raw = self.rfile.read(length)
        except (TimeoutError, socket.timeout) as exc:
            self.close_connection = True
            raise RequestBodyError(HTTPStatus.REQUEST_TIMEOUT, "request body timed out") from exc
        finally:
            if not self.close_connection:
                self.connection.settimeout(previous_timeout)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "request body must be utf-8 json") from exc
        except json.JSONDecodeError as exc:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "invalid json body") from exc
        if not isinstance(payload, dict):
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "json body must be an object")
        return payload

    def _read_media_source_body(self) -> bytes:
        raw_length = self.headers.get("content-length", "0") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "invalid content-length") from exc
        if length <= 0:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "source image is empty")
        if length > MAX_MEDIA_SOURCE_BYTES:
            self.close_connection = True
            raise RequestBodyError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "source image exceeds the 5 MB limit")
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(_positive_int_env("JIEJING_REQUEST_BODY_TIMEOUT_SECONDS", 15))
        try:
            content = self.rfile.read(length)
        except (TimeoutError, socket.timeout) as exc:
            self.close_connection = True
            raise RequestBodyError(HTTPStatus.REQUEST_TIMEOUT, "source image upload timed out") from exc
        finally:
            if not self.close_connection:
                self.connection.settimeout(previous_timeout)
        if len(content) != length:
            raise RequestBodyError(HTTPStatus.BAD_REQUEST, "source image upload was incomplete")
        return content

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK, headers: list[tuple[str, str]] | None = None) -> None:
        merchant_safe_data = _merchant_safe_replaceable_media_provider(data)
        body = json.dumps(merchant_safe_data, ensure_ascii=False, indent=2, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        for key, value in headers or []:
            self.send_header(key, value)
        self._send_security_headers()
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_media_source_asset(self, asset: Any) -> None:
        body = asset.file_path.read_bytes()
        if len(body) != asset.size_bytes or hashlib.sha256(body).hexdigest() != asset.sha256:
            self._send_error(HTTPStatus.GONE, "media source asset integrity check failed")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", asset.content_type)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "private, max-age=60")
        self.send_header("content-disposition", "inline")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _start_ndjson_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/x-ndjson; charset=utf-8")
        self.send_header("cache-control", "no-store, no-transform")
        self.send_header("x-accel-buffering", "no")
        self.send_header("connection", "close")
        self._send_security_headers()
        self._send_cors_headers()
        self.end_headers()
        self.close_connection = True

    def _send_ndjson_event(self, event: dict[str, Any]) -> bool:
        body = (json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=json_default) + "\n").encode("utf-8")
        try:
            self.wfile.write(body)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self._send_security_headers()
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _wants_html_response(self) -> bool:
        accept = str(self.headers.get("accept") or "").lower()
        return "text/html" in accept and "application/json" not in accept

    def _oauth_callback_public_html(self, result: dict[str, Any]) -> str:
        raw_status = str(result.get("status") or "unknown")
        title, tone, description, next_step = SaaSBackendHandler._oauth_callback_public_copy(self, raw_status, result)
        authorization_label = "eBay 发布授权" if _oauth_callback_is_publish(result) else "eBay 只读授权"
        safe_status = html.escape(raw_status)
        safe_title = html.escape(title)
        safe_authorization_label = html.escape(authorization_label)
        safe_tone = html.escape(tone)
        safe_description = html.escape(description)
        safe_next_step = html.escape(next_step)
        safe_summary = html.escape(str(result.get("summary") or "捷境已收到 eBay 授权回调。"))
        safe_store_id = html.escape(str(result.get("store_id") or ""))
        store_line = f'<div class="meta-row"><span>店铺记录</span><strong>{safe_store_id}</strong></div>' if safe_store_id else ""
        exchange_done = "是" if result.get("token_exchange_performed") else "否"
        vault_done = "是" if result.get("vault_write_performed") else "否"
        writes_enabled = "是" if result.get("real_platform_writes_enabled") else "否"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} · 捷境</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #667085;
      --line: #d9e0ea;
      --brand: #1967d2;
      --good: #0f7a4f;
      --warn: #a15c00;
      --bad: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
    }}
    main {{
      width: min(720px, calc(100vw - 32px));
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      box-shadow: 0 18px 50px rgba(23, 32, 51, 0.08);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--brand);
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(24px, 4vw, 34px);
      line-height: 1.18;
      letter-spacing: 0;
    }}
    p {{ margin: 0 0 16px; color: var(--muted); }}
    .status {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 8px 0 20px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      background: #fbfcfe;
      font-weight: 650;
    }}
    .status::before {{
      content: "";
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--warn);
    }}
    .status.success::before {{ background: var(--good); }}
    .status.error::before {{ background: var(--bad); }}
    .meta {{
      display: grid;
      gap: 10px;
      margin: 6px 0 22px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .meta-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 28px;
      color: var(--muted);
    }}
    .meta-row strong {{
      color: var(--ink);
      font-weight: 650;
      text-align: right;
      overflow-wrap: anywhere;
    }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    a.button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 0 14px;
      border-radius: 6px;
      color: #fff;
      background: var(--brand);
      text-decoration: none;
      font-weight: 700;
    }}
    .note {{ margin-top: 14px; font-size: 13px; }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">捷境 {safe_authorization_label}</p>
    <h1>{safe_title}</h1>
    <div class="status {safe_tone}">{safe_status}</div>
    <p>{safe_description}</p>
    <p>{safe_summary}</p>
    <section class="meta" aria-label="授权处理状态">
      {store_line}
      <div class="meta-row"><span>后端交换授权码</span><strong>{exchange_done}</strong></div>
      <div class="meta-row"><span>凭证写入 Vault/KMS 边界</span><strong>{vault_done}</strong></div>
      <div class="meta-row"><span>真实平台写入</span><strong>{writes_enabled}</strong></div>
    </section>
    <p><strong>下一步：</strong>{safe_next_step}</p>
    <div class="actions">
      <a class="button" href="/?start=app&amp;view=activity">返回捷境工作台</a>
    </div>
    <p class="note">这个页面不会展示 eBay access token、refresh token、授权码或 state。捷境 Runtime 只读取标准数据包。</p>
  </main>
</body>
</html>"""

    def _oauth_callback_public_copy(self, status: str, result: dict[str, Any] | None = None) -> tuple[str, str, str, str]:
        if status == "callback_exchange_completed":
            if _oauth_callback_is_publish(result or {}):
                return (
                    "eBay 发布授权已完成",
                    "success",
                    "捷境后端已完成授权码交换，并把卖家 refresh 凭证写入受控的 Vault/KMS 边界。",
                    "回到捷境工作台，刷新连接状态；确认中心通过预检后，单商品发布才会进入真实 eBay 发布适配器。",
                )
            return (
                "eBay 只读授权已完成",
                "success",
                "捷境后端已完成授权码交换，并把卖家 refresh 凭证写入受控的 Vault/KMS 边界。",
                "回到捷境工作台，执行 eBay 只读同步，生成标准数据包和 AI CEO 工作记录。",
            )
        if status.startswith("blocked_replayed"):
            return (
                "这个授权链接已经处理过",
                "error",
                "为了防止重复 callback，捷境已经拦截这次重复返回。",
                "回到工作台查看店铺连接状态；如果仍未授权，重新发起 eBay 连接。",
            )
        if status.startswith("blocked_invalid") or status == "blocked_missing_code":
            return (
                "这次授权链接已失效",
                "error",
                "捷境没有继续交换凭证，原始授权码不会被保存。",
                "回到工作台重新发起 eBay 只读授权。",
            )
        if status == "seller_declined_or_ebay_error":
            return (
                "eBay 授权未完成",
                "error",
                "eBay 返回了拒绝或错误结果，捷境没有交换凭证。",
                "回到工作台重新发起授权，或检查 eBay 开发者配置。",
            )
        return (
            "授权已返回，后端还需要处理",
            "warning",
            "捷境已收到 eBay callback，但当前还没有完成安全凭证存储或后续只读同步。",
            "检查 OAuth、Vault/KMS 与 eBay 只读开关，然后重新发起授权或同步。",
        )

    def _handle_service_dependency_exception(self, exc: Exception) -> bool:
        if not self._is_database_unavailable_exception(exc):
            return False
        self.close_connection = True
        self._send_json(
            {
                "error": "database_unavailable",
                "status": int(HTTPStatus.SERVICE_UNAVAILABLE),
                "message": "SaaS database is temporarily unavailable; readiness is degraded.",
                "retryable": True,
                "secret_exposed": False,
            },
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
        return True

    @staticmethod
    def _is_database_unavailable_exception(exc: Exception) -> bool:
        exc_type = exc.__class__.__name__.lower()
        exc_module = exc.__class__.__module__.lower()
        text = f"{exc_type}: {exc}".lower()
        if isinstance(exc, sqlite3.DatabaseError):
            return any(
                marker in text
                for marker in (
                    "database is locked",
                    "database table is locked",
                    "database schema is locked",
                    "unable to open database file",
                    "attempt to write a readonly database",
                    "disk i/o error",
                    "database or disk is full",
                    "database disk image is malformed",
                    "file is not a database",
                    "malformed database schema",
                    "cannot operate on a closed database",
                )
            )
        if exc_module.startswith("psycopg"):
            return True
        return any(
            marker in text
            for marker in (
                "postgres repository initialization failed",
                "connection timeout expired",
                "could not connect",
                "connection refused",
                "database is unavailable",
                "server closed the connection unexpectedly",
                "terminating connection",
            )
        )

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message, "status": int(status)}, status=status)

    def _handle_ebay_oauth_callback(self, *, state: str, code: str, error: str) -> dict[str, Any]:
        return process_ebay_oauth_callback(
            repository=self.repository,
            settings=self.settings,
            secret_store_boundary=self.secret_store_boundary,
            ebay_oauth_planner=self.ebay_oauth_planner,
            state=state,
            code=code,
            error=error,
        )

    def _send_cors_headers(self) -> None:
        origin = self._resolved_cors_origin()
        if origin:
            self.send_header("access-control-allow-origin", origin)
            self.send_header("vary", "Origin")
            if origin != "*":
                self.send_header("access-control-allow-credentials", "true")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type, authorization, x-jiejing-operator-secret, x-jiejing-file-name")

    def _send_security_headers(self) -> None:
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("x-frame-options", "DENY")
        self.send_header("referrer-policy", "strict-origin-when-cross-origin")
        self.send_header("permissions-policy", "geolocation=(), microphone=(), camera=(), payment=()")
        self.send_header("x-robots-tag", "noindex, nofollow, noarchive, nosnippet, noimageindex")

    def _resolved_cors_origin(self) -> str | None:
        configured = [item.strip() for item in str(self.settings.cors_origin or "").split(",") if item.strip()]
        if not configured:
            return None
        request_origin = self.headers.get("origin", "")
        if "*" in configured and not self.settings.is_production_like:
            return "*"
        if request_origin and request_origin in configured:
            return request_origin
        if not request_origin and "*" not in configured:
            return configured[0]
        return None

    def _oauth_callback_http_status(self, result: dict[str, Any]) -> HTTPStatus:
        status = str(result.get("status") or "")
        if status.startswith("blocked_replayed"):
            return HTTPStatus.CONFLICT
        if status.startswith("blocked_invalid"):
            return HTTPStatus.BAD_REQUEST
        return HTTPStatus.OK

    def _chain_schema(self) -> dict[str, Any]:
        return {
            "version": "2026-05-15-local-worker-mvp",
            "layers": [
                "Jiejing Frontend",
                "Jiejing SaaS Backend API",
                "Auth & Permission",
                "Team Role & Company Switch Boundary",
                "SaaS Database",
                "Database Adapter Contract",
                "Database Migration & Index Boundary",
                "Secret Reference / Vault Boundary",
                "Vault/KMS Adapter Contract",
                "Platform Connector Registry",
                "eBay OAuth Read-only Authorization Boundary",
                "eBay Token Refresh Boundary",
                "eBay Read-only Adapter Boundary",
                "Read-only Data Packet Cache",
                "Local Queue Boundary",
                "Queue Adapter Contract",
                "Queue Worker Production Plan",
                "Controlled Bridge Contract",
                "Jiejing Independence Status",
                "Provider Job Contracts",
                "QueueWorkerBridge",
                "ProviderAdapter",
                "RuntimeBridge",
                "Reports & Confirmation Center",
                "ExecutionService",
                "ConfirmationExecutionBridge",
                "Audit Logs",
                "AuditMemoryBridge",
                "HermesLegacyBridge Transitional Only",
            ],
            "blocked_real_actions": [
                "eBay publish/revise",
                "price or inventory write",
                "refund",
                "ad budget",
                "procurement payment",
                "business policy edit",
                "sensitive buyer promise",
            ],
            "production_replacements": {
                "database": "Postgres/MySQL",
                "queue": "Postgres durable queue or Redis/cloud queue",
                "secret_store": "Vault/KMS/cloud secret manager",
                "runtime_workers": "cloud Jiejing Runtime workers; Hermes legacy bridge is transitional only",
            },
            "current_settings": self.settings.public_dict(),
        }


def _execution_payload_from_context(
    *,
    repository: SaaSRepository,
    company_id: str,
    confirmation: dict[str, Any],
    body_payload: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(body_payload or {})
    if confirmation.get("action_type") not in {"publish_listing", "save_ebay_listing_draft"}:
        return payload
    item = confirmation.get("item") if isinstance(confirmation.get("item"), dict) else {}
    confirmation_payload = item.get("publish_payload") if isinstance(item.get("publish_payload"), dict) else {}
    inferred = _publish_payload_from_reports(repository=repository, company_id=company_id, confirmation=confirmation)
    merged = _deep_merge(_deep_merge(inferred, confirmation_payload), payload)
    account_health = build_account_health_snapshot(
        repository,
        company_id=company_id,
        store_id=confirmation["store_id"],
    )
    return merge_account_health_into_payload(merged, account_health)


def _publish_confirmation_payload_from_body(
    *,
    body: dict[str, Any],
    packet: dict[str, Any],
    marketplace_id: str,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    listing_in = body.get("listing") if isinstance(body.get("listing"), dict) else {}
    supplier_in = body.get("supplier_facts") if isinstance(body.get("supplier_facts"), dict) else {}
    assets_in = body.get("asset_manifest") if isinstance(body.get("asset_manifest"), dict) else {}
    finance_in = body.get("finance_review") if isinstance(body.get("finance_review"), dict) else {}
    regulatory_in = body.get("regulatory") if isinstance(body.get("regulatory"), dict) else {}
    dimensions_in = supplier_in.get("package_dimensions_cm") if isinstance(supplier_in.get("package_dimensions_cm"), dict) else {}
    item_specifics_in = listing_in.get("item_specifics") if isinstance(listing_in.get("item_specifics"), dict) else {}
    body_policies = body.get("business_policies") if isinstance(body.get("business_policies"), dict) else {}
    business_policies = _deep_merge(_business_policies_from_packet(packet), _clean_publish_text_map(body_policies))
    price_in = listing_in.get("price") if isinstance(listing_in.get("price"), dict) else {"value": listing_in.get("price"), "currency": "USD"}
    description = _safe_publish_description(listing_in.get("description_html") or listing_in.get("description") or "")
    listing = {
        "sku": _safe_publish_text(listing_in.get("sku") or f"JJ-FRESH-{int(time.time())}", limit=80),
        "title": _safe_publish_text(listing_in.get("title"), limit=80),
        "description_html": description,
        "category_id": _safe_publish_text(listing_in.get("category_id"), limit=40),
        "category_leaf": _safe_publish_text(listing_in.get("category_leaf") or listing_in.get("leaf_category"), limit=120),
        "condition": _safe_publish_condition(listing_in.get("condition")),
        "price": {
            "value": _safe_publish_decimal(price_in.get("value")),
            "currency": _safe_publish_text(price_in.get("currency") or "USD", limit=8) or "USD",
        },
        "quantity": _safe_publish_int(listing_in.get("quantity")),
        "item_specifics": _clean_publish_text_map(item_specifics_in, key_limit=80, value_limit=180),
        "merchant_location_key": _safe_publish_text(
            listing_in.get("merchant_location_key") or _packet_value(packet, "inventory_and_offers", "merchant_location_key"),
            limit=80,
        ),
        "marketplace_id": _safe_publish_text(marketplace_id or body.get("marketplace_id") or "EBAY_US", limit=16) or "EBAY_US",
    }
    supplier = {
        "package_weight_g": _safe_publish_decimal(supplier_in.get("package_weight_g")),
        "package_dimensions_cm": {
            "length": _safe_publish_decimal(dimensions_in.get("length")),
            "width": _safe_publish_decimal(dimensions_in.get("width")),
            "height": _safe_publish_decimal(dimensions_in.get("height")),
        },
        "material": _safe_publish_text(supplier_in.get("material"), limit=120),
        "item_location": _safe_publish_text(supplier_in.get("item_location") or _packet_value(packet, "inventory_and_offers", "item_location"), limit=80),
    }
    assets = []
    for item in assets_in.get("assets") if isinstance(assets_in.get("assets"), list) else []:
        if isinstance(item, str):
            url = item.strip()
            asset_type = "image"
            role = "gallery"
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("src") or "").strip()
            asset_type = _safe_publish_text(item.get("asset_type") or "image", limit=40)
            role = _safe_publish_text(item.get("role") or "gallery", limit=40)
        else:
            continue
        assets.append({"asset_type": asset_type, "role": role, "url": url, "source": "merchant_publish_confirmation_intake"})
    finance = {
        "procurement_cost_money": _safe_publish_money(finance_in.get("procurement_cost_money")),
        "shipping_cost_money": _safe_publish_money(finance_in.get("shipping_cost_money")),
        "ad_budget_money": _safe_publish_money(finance_in.get("ad_budget_money")),
        "net_profit_money": _safe_publish_money(finance_in.get("net_profit_money")),
        "gross_margin_percent": _safe_publish_decimal(finance_in.get("gross_margin_percent")),
    }
    return {
        "source": "merchant_listing_publish_intake",
        "marketplace_id": listing["marketplace_id"],
        "listing": {key: value for key, value in listing.items() if value not in ("", None, {}, [])},
        "business_policies": {key: value for key, value in business_policies.items() if value},
        "supplier_facts": {key: value for key, value in supplier.items() if value not in ("", None, {}, [])},
        "asset_manifest": {"assets": assets},
        "finance_review": {key: value for key, value in finance.items() if value not in ("", None, {}, [])},
        "regulatory": _clean_publish_text_map(regulatory_in, key_limit=80, value_limit=240),
        "publish_payload_inferred": False,
        "secret_exposed": False,
    }


def _safe_publish_text(value: Any, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    return text[:limit]


def _safe_publish_description(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "<" in text and ">" in text:
        return text[:6000]
    return f"<p>{html.escape(text[:4000])}</p>"


def _safe_publish_condition(value: Any) -> str:
    text = _safe_publish_text(value or "NEW", limit=32).upper().replace(" ", "_")
    return text if text in {"NEW", "USED", "LIKE_NEW", "VERY_GOOD", "GOOD", "ACCEPTABLE"} else "NEW"


def _safe_publish_decimal(value: Any) -> str:
    try:
        text = str(value if value is not None else "").strip()
        if not text:
            return ""
        return f"{float(text):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def _safe_publish_int(value: Any) -> int | None:
    try:
        text = str(value if value is not None else "").strip()
        if not text:
            return None
        number = int(float(text))
        return number if number >= 0 else None
    except (TypeError, ValueError):
        return None


def _safe_publish_money(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    amount = _safe_publish_decimal(value.get("value"))
    if not amount:
        return None
    return {"value": amount, "currency": _safe_publish_text(value.get("currency") or "USD", limit=8) or "USD"}


def _clean_publish_text_map(value: Any, *, key_limit: int = 80, value_limit: int = 240) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        safe_key = _safe_publish_text(key, limit=key_limit)
        safe_value = _safe_publish_text(item, limit=value_limit)
        if safe_key and safe_value:
            out[safe_key] = safe_value
    return out


def _apply_publish_recovery_execution_context(
    *,
    payload: dict[str, Any],
    execution_results: list[dict[str, Any]],
    confirmation_id: str,
) -> dict[str, Any]:
    """Prefer already persisted platform ids when recovering an ambiguous publish."""

    payload = dict(payload or {})
    for record in execution_results:
        if str(record.get("confirmation_id") or "") != str(confirmation_id or ""):
            continue
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        platform = _execution_platform_context(result)
        sku = str(platform.get("sku") or "").strip()
        if not sku:
            continue
        listing = dict(payload.get("listing") if isinstance(payload.get("listing"), dict) else {})
        listing["sku"] = sku
        payload["listing"] = listing
        payload["publish_recovery_source"] = {
            "source": "execution_result_platform_result",
            "execution_id": record.get("execution_id"),
            "listing_id": platform.get("listing_id") or platform.get("listingId"),
            "offer_id": platform.get("offer_id") or platform.get("offerId"),
            "secret_exposed": False,
        }
        return payload
    return payload


def _execution_platform_context(result: dict[str, Any]) -> dict[str, Any]:
    platform = result.get("platform_result") if isinstance(result.get("platform_result"), dict) else {}
    audit = result.get("audit") if isinstance(result.get("audit"), dict) else {}
    audit_platform = audit.get("platform_result") if isinstance(audit.get("platform_result"), dict) else {}
    out = dict(audit_platform)
    out.update(platform)
    if not str(out.get("sku") or "").strip():
        sku = _sku_from_execution_steps(result.get("steps") if isinstance(result.get("steps"), list) else [])
        if not sku:
            idempotency = audit.get("idempotency") if isinstance(audit.get("idempotency"), dict) else {}
            sku = _sku_from_idempotency_key(str(idempotency.get("idempotency_key") or ""))
        if sku:
            out["sku"] = sku
    return out


def _sku_from_execution_steps(steps: list[Any]) -> str:
    for step in steps:
        if not isinstance(step, dict):
            continue
        path = str(step.get("path") or "")
        inventory_match = re.search(r"/inventory_item/([^/?#]+)", path)
        if inventory_match:
            return unquote(inventory_match.group(1)).strip()
        offer_match = re.search(r"[?&]sku=([^&#]+)", path)
        if offer_match:
            return unquote(offer_match.group(1)).strip()
    return ""


def _sku_from_idempotency_key(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("publish-") and len(text) > len("publish-"):
        return text[len("publish-") :].strip()
    return ""


def _cleanup_confirmation_id(*, publish_confirmation_id: str, publish_recovery: dict[str, Any]) -> str:
    sku = str(publish_recovery.get("sku") or "").strip()
    digest = hashlib.sha1(f"{publish_confirmation_id}|{sku}".encode("utf-8")).hexdigest()[:10]
    return f"{publish_confirmation_id}::cleanup_test_listing::{digest}"


def _cleanup_confirmation_title(publish_recovery: dict[str, Any]) -> str:
    published = publish_recovery.get("published_offer") if isinstance(publish_recovery.get("published_offer"), dict) else {}
    listing_id = str(published.get("listing_id") or "").strip()
    sku = str(publish_recovery.get("sku") or "").strip()
    target = listing_id or sku or "test listing"
    return f"Confirm test listing cleanup · {target}"


def _cleanup_confirmation_item(
    *,
    publish_confirmation: dict[str, Any],
    publish_recovery: dict[str, Any],
    cleanup_plan: dict[str, Any],
) -> dict[str, Any]:
    published = publish_recovery.get("published_offer") if isinstance(publish_recovery.get("published_offer"), dict) else {}
    operations = cleanup_plan.get("operations") if isinstance(cleanup_plan.get("operations"), list) else []
    return {
        "source": "publish_recovery_cleanup_plan",
        "source_publish_confirmation_id": publish_confirmation.get("confirmation_id"),
        "action_type": "cleanup_test_listing",
        "title": _cleanup_confirmation_title(publish_recovery),
        "reason": "This cleanup may end or remove a live eBay test listing, so it must be explicitly confirmed and audited.",
        "default_action": "hold",
        "options": ["approve", "reject"],
        "sku": publish_recovery.get("sku"),
        "listing_id": published.get("listing_id"),
        "offer_id": published.get("offer_id"),
        "cleanup_plan": cleanup_plan,
        "operation_count": len(operations),
        "writes_to_ebay": any(bool(item.get("writes_to_ebay")) for item in operations if isinstance(item, dict)),
        "access_token_returned_to_frontend": False,
        "access_token_returned_to_runtime": False,
        "raw_response_stored": False,
        "secret_exposed": False,
    }


def _oauth_callback_is_publish(result: dict[str, Any]) -> bool:
    if bool(result.get("publish_scope_authorized")):
        return True
    if str(result.get("connection_status") or "") == "publish_authorized":
        return True
    connection = result.get("connection") if isinstance(result.get("connection"), dict) else {}
    if str(connection.get("status") or "") == "publish_authorized":
        return True
    scopes = connection.get("scopes") if isinstance(connection.get("scopes"), list) else []
    return any(str(scope).strip().lower().endswith("/sell.inventory") for scope in scopes)


def _publish_payload_from_reports(*, repository: SaaSRepository, company_id: str, confirmation: dict[str, Any]) -> dict[str, Any]:
    reports = repository.list_reports(company_id=company_id, task_id=confirmation["task_id"])
    listing_report = next((item for item in reversed(reports) if item.get("report_type") == "listing.package"), None)
    packets = repository.list_platform_data_packets(company_id=company_id, store_id=confirmation["store_id"], platform="ebay", limit=1)
    sections = _listing_sections(listing_report)
    packet = packets[0].get("packet") if packets and isinstance(packets[0].get("packet"), dict) else {}
    listing = {
        "sku": _confirmed_text(sections.get("sku")),
        "title": _confirmed_text(_section_value(sections.get("title"))),
        "description_html": _confirmed_text(sections.get("description_html")),
        "category_id": _confirmed_text(_section_value(sections.get("category_id"))),
        "category_leaf": _confirmed_text(
            _dict_value(sections.get("ebay_listing_metadata"), "leaf_category")
            or _packet_value(packet, "taxonomy_listing_metadata", "leaf_category")
        ),
        "condition": _confirmed_condition(sections.get("condition")),
        "price": _confirmed_price(sections.get("price")),
        "quantity": _confirmed_quantity(sections.get("quantity")),
        "item_specifics": _confirmed_item_specifics(sections.get("item_specifics")),
        "merchant_location_key": _confirmed_text(sections.get("merchant_location_key") or _packet_value(packet, "inventory_and_offers", "merchant_location_key")),
    }
    business = _business_policies_from_sections(sections) or _business_policies_from_packet(packet)
    supplier = {
        "package_weight_g": _confirmed_number(sections.get("package_weight_g") or sections.get("package_weight")),
        "package_dimensions_cm": _confirmed_dimensions(sections.get("package_dimensions_cm") or sections.get("package_dimensions")),
        "material": _confirmed_text(_nested_value(sections.get("item_specifics"), "Material")),
        "item_location": _confirmed_text(sections.get("item_location") or _packet_value(packet, "inventory_and_offers", "item_location")),
    }
    return {
        "source": "saas_confirmed_publish_context",
        "listing": {key: value for key, value in listing.items() if value not in ("", None, {}, [])},
        "business_policies": {key: value for key, value in business.items() if value},
        "supplier_facts": {key: value for key, value in supplier.items() if value not in ("", None, {}, [])},
        "asset_manifest": {"assets": []},
        "finance_review": {},
        "publish_payload_inferred": True,
        "publish_payload_source": {
            "listing_report_id": listing_report.get("report_id") if listing_report else None,
            "packet_id": packets[0].get("packet_id") if packets else None,
            "secret_exposed": False,
        },
    }


def _publish_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    business = payload.get("business_policies") if isinstance(payload.get("business_policies"), dict) else {}
    supplier = payload.get("supplier_facts") if isinstance(payload.get("supplier_facts"), dict) else {}
    assets = payload.get("asset_manifest") if isinstance(payload.get("asset_manifest"), dict) else {}
    return {
        "listing_fields": sorted(listing.keys()),
        "business_policy_fields": sorted(business.keys()),
        "supplier_fact_fields": sorted(supplier.keys()),
        "asset_count": len(assets.get("assets") if isinstance(assets.get("assets"), list) else []),
        "inferred": bool(payload.get("publish_payload_inferred")),
        "secret_exposed": False,
    }


def _listing_sections(report_record: dict[str, Any] | None) -> dict[str, Any]:
    if not report_record:
        return {}
    result = report_record.get("report") if isinstance(report_record.get("report"), dict) else {}
    inner = result.get("report") if isinstance(result.get("report"), dict) else result
    sections = inner.get("sections") if isinstance(inner.get("sections"), dict) else {}
    return sections


def _section_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _nested_value(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return None
    fixed = value.get("fixed_common") if isinstance(value.get("fixed_common"), dict) else value
    return fixed.get(key)


def _dict_value(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _confirmed_text(value: Any) -> str:
    value = _section_value(value)
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    pending_markers = ("pending", "unknown", "tbd", "confirm", "unless", "待", "未确认")
    if any(marker in lowered for marker in pending_markers):
        return ""
    return text


def _confirmed_condition(value: Any) -> str:
    text = _confirmed_text(value)
    normalized = text.upper().replace(" ", "_")
    return normalized if normalized in {"NEW", "USED", "LIKE_NEW", "VERY_GOOD", "GOOD", "ACCEPTABLE"} else ""


def _confirmed_price(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict) and value.get("value"):
        return {"value": str(value.get("value")), "currency": str(value.get("currency") or "USD")}
    text = _confirmed_text(value)
    if not text or any(marker in text for marker in ("-", "~", "to")):
        return None
    normalized = text.replace("US$", "").replace("$", "").strip()
    try:
        float(normalized)
    except ValueError:
        return None
    return {"value": normalized, "currency": "USD"}


def _confirmed_quantity(value: Any) -> int | None:
    text = _confirmed_text(value)
    if not text or any(marker in text for marker in ("-", "~", "to")):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _confirmed_number(value: Any) -> float | None:
    text = _confirmed_text(value)
    if not text or any(marker in text for marker in ("x", "X", "-", "~")):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _confirmed_dimensions(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        out: dict[str, float] = {}
        for key in ("length", "width", "height"):
            try:
                out[key] = float(str(value.get(key) or "").strip())
            except ValueError:
                return None
        return out if len(out) == 3 else None
    return None


def _confirmed_item_specifics(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    fixed = value.get("fixed_common") if isinstance(value.get("fixed_common"), dict) else value
    out: dict[str, str] = {}
    for key, item in fixed.items():
        text = _confirmed_text(item)
        if text:
            out[str(key)] = text
    return out


def _business_policies_from_sections(sections: dict[str, Any]) -> dict[str, str]:
    policies = sections.get("business_policies") if isinstance(sections.get("business_policies"), dict) else {}
    return _business_policies_from_policy_blob(policies)


def _business_policies_from_packet(packet: dict[str, Any]) -> dict[str, str]:
    resources = _packet_sections(packet)
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("key") != "account_business_policies":
            continue
        data = resource.get("data") if isinstance(resource.get("data"), dict) else {}
        return {
            "fulfillment_policy_id": _confirmed_text(data.get("fulfillment_policy_id")),
            "payment_policy_id": _confirmed_text(data.get("payment_policy_id")),
            "return_policy_id": _confirmed_text(data.get("return_policy_id")),
        }
    return {}


def _business_policies_from_policy_blob(policies: dict[str, Any]) -> dict[str, str]:
    return {
        "fulfillment_policy_id": _first_policy_id(policies.get("fulfillment")),
        "payment_policy_id": _first_policy_id(policies.get("payment")),
        "return_policy_id": _first_policy_id(policies.get("return")),
    }


def _first_policy_id(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0] if isinstance(value[0], dict) else {}
        return _confirmed_text(first.get("id") or first.get("policy_id"))
    if isinstance(value, dict):
        return _confirmed_text(value.get("id") or value.get("policy_id"))
    return ""


def _packet_value(packet: dict[str, Any], resource_key: str, field: str) -> Any:
    for resource in _packet_sections(packet):
        if not isinstance(resource, dict) or resource.get("key") != resource_key:
            continue
        data = resource.get("data") if isinstance(resource.get("data"), dict) else {}
        return data.get(field)
    return None


def _packet_sections(packet: dict[str, Any]) -> list[Any]:
    if isinstance(packet.get("resources"), list):
        return list(packet.get("resources") or [])
    if isinstance(packet.get("sections"), list):
        return list(packet.get("sections") or [])
    return []


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def sqlite_unique_error() -> type[Exception]:
    import sqlite3

    return (sqlite3.IntegrityError, *postgres_unique_error_classes())  # type: ignore[return-value]


def _merchant_next_step_for_ebay_sync_blockers(blocked_by: list[str]) -> str:
    blockers = set(blocked_by)
    if "JIEJING_EBAY_READ_ONLY_LIVE" in blockers:
        return "先在后端开启 eBay 只读同步开关；正式环境必须同时走 KMS/Vault 管理授权密钥。"
    if "JIEJING_EBAY_ACCESS_TOKEN_OR_REFRESH_TOKEN" in blockers or "token_refresh_not_ready" in blockers:
        return "先完成 eBay 店铺只读授权，或把 refresh token 的 secret_ref 绑定到这个店铺。"
    if "Vault/KMS" in blockers:
        return "先接入 KMS/Vault；生产环境不允许把 eBay 密钥放进前端、Runtime 或数据库明文。"
    if "JIEJING_EBAY_CLIENT_SECRET" in blockers:
        return "先把 eBay App 的 client secret 放入后端安全配置或 KMS。"
    if "JIEJING_EBAY_TOKEN_REFRESH_LIVE" in blockers:
        return "先确认后端允许用 refresh token 换短期 access token。"
    return "先补齐 eBay 只读授权、后端密钥配置和店铺连接状态，再重新同步。"


def _redact_secret_like(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(marker in lower for marker in ("secret", "token", "password", "api_key", "apikey", "refresh")):
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact_secret_like(item)
        return out
    if isinstance(value, list):
        return [_redact_secret_like(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value)
    return value


def _redact_secret_text(value: str) -> str:
    text = str(value or "")
    replacements = (
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[model_key_redacted]"),
        (r"\b(?:AIAK|AKID|ASIA)[A-Za-z0-9]{12,}\b", "[cloud_key_redacted]"),
        (r"\b[0-9a-f]{8}-[0-9a-f-]{27,}:[0-9a-f]{24,}\b", "[provider_key_redacted]"),
        (r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [redacted]"),
        (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "[jwt_redacted]"),
        (
            r"\b(access[_-]?token|refresh[_-]?token|api[_-]?key|apikey|password|secret)\s*[:=]\s*[^,\s;]+",
            r"\1=[redacted]",
        ),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
