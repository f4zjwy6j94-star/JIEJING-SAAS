#!/usr/bin/env bash
set -euo pipefail

PRODUCTION_ROOT="/opt/jiejing-production"
ACTIVE_LINK="$PRODUCTION_ROOT/app"
RELEASE_ROOT="$PRODUCTION_ROOT/releases"
COMPOSE_NAME="docker-compose.production-pilot.yml"
LOCK_FILE="/run/lock/jiejing-production-maintenance.lock"
EVIDENCE_DIRECTORY="$PRODUCTION_ROOT/runtime-evidence"
EVIDENCE_MOUNT="/run/jiejing-production-evidence"
PUBLIC_BASE_URL="https://app.jiejing.shop"
PUBLIC_READINESS_MAX_ATTEMPTS=60
PUBLIC_READINESS_RETRY_SECONDS=2

fail_closed() {
  printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=blocked"
  printf 'JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=%s\n' "$1"
  exit 2
}

canonical_path_equals() {
  local candidate="$1" expected="$2" candidate_resolved expected_resolved
  candidate_resolved="$(readlink -f -- "$candidate" 2>/dev/null || true)"
  expected_resolved="$(readlink -f -- "$expected" 2>/dev/null || true)"
  [[ -n "$candidate_resolved" && "$candidate_resolved" == "$expected_resolved" ]]
}

acquire_nonblocking_lock() {
  local path="$1" flock_rc
  command -v flock >/dev/null 2>&1 || return 11
  if ! exec 9>"$path"; then
    return 11
  fi
  if flock -n 9; then
    flock_rc=0
  else
    flock_rc=$?
  fi
  case "$flock_rc" in
    0) return 0 ;;
    1) return 10 ;;
    *) return 11 ;;
  esac
}

trusted_private_file() {
  local path="$1" resolved metadata
  [[ -f "$path" && ! -L "$path" ]] || return 1
  resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
  [[ "$resolved" == "$path" ]] || return 1
  metadata="$(stat -c '%U:%G %a' -- "$path" 2>/dev/null || true)"
  [[ "$metadata" == "root:root 600" ]]
}

trusted_private_directory() {
  local path="$1" metadata owner mode
  [[ -d "$path" && ! -L "$path" ]] || return 1
  metadata="$(stat -c '%U:%G %a' -- "$path" 2>/dev/null || true)"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "root:root" && "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  (( (8#$mode & 0022) == 0 ))
}

evidence_excluded_env_digest() {
  python3 - "$1" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

EVIDENCE_FIELDS = {
    "JIEJING_COS_BACKUP_LAST_SUCCESS_AT",
    "JIEJING_CLS_LIVE_PROBE_LAST_AT",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_PASSED",
    "JIEJING_CLS_INGESTION_LIVE_PROBE_LAST_AT",
    "JIEJING_PROVIDER_LATENCY_ALARM_VERIFIED_AT",
    "JIEJING_PROVIDER_COST_ALARM_VERIFIED_AT",
}

path = Path(sys.argv[1])
filtered: list[bytes] = []
for line in path.read_bytes().splitlines(keepends=True):
    candidate = line.strip()
    if candidate and not candidate.startswith(b"#") and b"=" in candidate:
        key = candidate.split(b"=", 1)[0].strip().decode("ascii", errors="strict")
        if key in EVIDENCE_FIELDS:
            continue
    filtered.append(line)
print(hashlib.sha256(b"".join(filtered)).hexdigest())
PY
}

json_contract_verified() {
  local contract="$1"
  python3 -c '
from __future__ import annotations

import json
import sys

contract = sys.argv[1]
try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)

common = (
    isinstance(payload, dict)
    and payload.get("status") == "verified"
    and payload.get("verification_evidence_recorded") is True
    and payload.get("secret_exposed") is False
)
if contract == "cos":
    verified = (
        common
        and set(payload) == {
            "status",
            "contract_version",
            "probe_verified",
            "verification_evidence_recorded",
            "secret_exposed",
        }
        and payload.get("contract_version") == "jiejing_cos_backup_probe_v1"
        and payload.get("probe_verified") is True
    )
elif contract == "cls":
    verified = (
        common
        and set(payload) == {
            "status",
            "probe_uploaded",
            "probe_searchable",
            "alarm_queries_exclude_probe",
            "event_field_count",
            "event_allowlist_exact",
            "notification_test_sent",
            "resource_ids_exposed",
            "secret_exposed",
            "verification_evidence_recorded",
        }
        and payload.get("probe_uploaded") is True
        and payload.get("probe_searchable") is True
        and payload.get("alarm_queries_exclude_probe") is True
        and type(payload.get("event_field_count")) is int
        and payload.get("event_field_count") == 12
        and payload.get("event_allowlist_exact") is True
        and payload.get("notification_test_sent") is False
        and payload.get("resource_ids_exposed") is False
    )
elif contract == "alarm":
    index = payload.get("index") or {}
    alarms = payload.get("alarms") or []
    verified = (
        common
        and set(payload) == {
            "status",
            "mode",
            "index",
            "alarms",
            "blockers",
            "cloud_write_performed",
            "alarm_readback_verified",
            "notification_test_sent",
            "index_modified",
            "resource_ids_exposed",
            "secret_exposed",
            "verification_evidence_recorded",
        }
        and payload.get("mode") == "verify"
        and set(index) == {
            "ready",
            "enabled",
            "fulltext_enabled",
            "required_key_count",
            "configured_required_key_count",
            "missing_keys",
            "modified",
        }
        and index.get("ready") is True
        and index.get("enabled") is True
        and type(index.get("fulltext_enabled")) is bool
        and type(index.get("required_key_count")) is int
        and index.get("required_key_count") > 0
        and index.get("configured_required_key_count") == index.get("required_key_count")
        and index.get("missing_keys") == []
        and index.get("modified") is False
        and isinstance(alarms, list)
        and len(alarms) == 2
        and {item.get("key") for item in alarms if isinstance(item, dict)} == {"latency", "cost"}
        and all(
            set(item) == {"key", "action", "match_count", "readback_ready", "drift_field_count"}
            and item.get("action") == "noop"
            and item.get("match_count") == 1
            and item.get("readback_ready") is True
            and item.get("drift_field_count") == 0
            for item in alarms
            if isinstance(item, dict)
        )
        and payload.get("blockers") == []
        and payload.get("cloud_write_performed") is False
        and payload.get("alarm_readback_verified") is True
        and payload.get("notification_test_sent") is False
        and payload.get("index_modified") is False
        and payload.get("resource_ids_exposed") is False
    )
else:
    verified = False
raise SystemExit(0 if verified else 2)
' "$contract"
}

public_health_ready() {
  local body
  body="$(curl -fsS --max-time 15 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/health" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)
ready = (
    payload.get("status") == "ok"
    and payload.get("database_startup_status") == "ready"
    and payload.get("real_platform_writes_enabled") is False
    and payload.get("requested_real_platform_writes") is False
    and payload.get("secret_exposed") is False
)
raise SystemExit(0 if ready else 2)
' <<<"$body" >/dev/null 2>&1
}

public_deep_health_ready() {
  local body
  body="$(curl -fsS --max-time 15 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/health/deep" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError, UnicodeError):
    raise SystemExit(2)
operational = payload.get("operational_health") or {}
ready = (
    operational.get("status") == "ready"
    and operational.get("database", {}).get("status") == "ready"
    and operational.get("queue", {}).get("status") == "ready"
    and operational.get("worker", {}).get("status") == "ready"
    and operational.get("worker", {}).get("ready") is True
    and operational.get("secret_exposed") is False
)
raise SystemExit(0 if ready else 2)
' <<<"$body" >/dev/null 2>&1
}

public_readiness_ready() {
  local body
  PUBLIC_READINESS_REPORT=""
  body="$(curl -fsS --max-time 20 -A 'Mozilla/5.0 JiejingProductionEvidenceRefresh/1.0' \
    "$PUBLIC_BASE_URL/readiness/product-saas" 2>/dev/null)" || return 1
  PUBLIC_READINESS_REPORT="$(python3 -c '
import json
import sys

def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_object_key")
        value[key] = item
    return value

try:
    payload = json.load(sys.stdin, object_pairs_hook=unique_object)
except (json.JSONDecodeError, OSError, UnicodeError, ValueError):
    raise SystemExit(2)
PUBLIC_ROOT_FIELDS = {"readiness"}
READINESS_PUBLIC_FIELDS = {
    "service", "readiness_version", "public_contract_version", "detail_scope",
    "internal_detail_required", "authenticated_summary", "environment",
    "production_ready", "beta_ready", "can_accept_real_customers",
    "real_platform_writes_enabled", "requested_real_platform_writes",
    "blocker_count", "warning_count", "items", "product_evidence",
    "provider_status", "operational_health", "secret_exposed",
}
ITEM_PUBLIC_FIELDS = {"key", "label", "status", "severity", "detail", "next_action"}
PROVIDER_PUBLIC_FIELDS = {
    "billing", "model_value", "ai_ceo_platform_model", "public_search", "media_generation",
}
PROVIDER_SUBFIELDS = {
    "billing": {
        "provider", "checkout_mode", "billing_mode", "provider_configured",
        "payment_path_status", "mainland_payment_ready_for_owner_approval",
        "billing_ready_for_private_beta", "billing_ready_for_paid_launch",
        "configured_component_count", "required_component_count", "verified_paid_order_count",
        "quota_enforcement_enabled", "paid_launch_blocker_count", "next_paid_launch_blocker",
        "merchant_launch_path", "domestic_payment", "public_charging_allowed",
        "charge_now_allowed", "triggers_real_charge", "triggers_real_refund",
        "calls_external_payment_api", "real_platform_writes_enabled",
        "frontend_gets_payment_secret", "frontend_can_grant_quota", "secret_exposed",
    },
    "model_value": {"status", "ready", "live_model_report_types", "blocker_count", "secret_exposed"},
    "ai_ceo_platform_model": {
        "enabled", "configured", "status", "provider", "model", "trial_request_limit",
        "trial_duration_days", "trial_quota_scope", "usage_owner", "quota_checked_by_backend",
        "hard_stop_on_exhaustion", "exhaustion_blocker", "merchant_byok_preferred",
        "merchant_byok_not_counted_against_platform_trial", "byok_bypasses_platform_trial",
        "customer_visible_next_action", "operator_cost_monitoring_required",
        "frontend_can_grant_quota", "frontend_gets_model_api_key",
        "runtime_gets_model_api_key", "secret_exposed",
    },
    "public_search": {
        "provider", "configured", "endpoint_host", "credential_present",
        "ai_ceo_realtime_search_enabled", "builtin_public_web_fallback_enabled",
        "builtin_stock_quote_fallback_enabled", "frontend_gets_search_api_key",
        "runtime_gets_search_api_key", "secret_exposed",
    },
    "media_generation": {
        "contract_version", "configured", "status", "live_generation_enabled",
        "live_image_generation_enabled", "live_video_generation_enabled",
        "live_provider_calls_allowed", "asset_manifest_required", "asset_review_required",
        "fact_review_required", "human_review_required_before_listing", "cost_guard_required",
        "spend_now_allowed", "listing_use_requires_review", "customer_visible_summary",
        "next_action", "frontend_gets_media_api_key", "runtime_gets_raw_secret",
        "reports_get_raw_provider_response", "raw_provider_response_stored", "secret_exposed",
    },
}
BILLING_NESTED_SUBFIELDS = {
    "merchant_launch_path": {
        "contract_version", "current_stage", "current_charge_status",
        "public_paid_launch_allowed", "charge_now_allowed", "triggers_real_charge",
        "backend_confirmation_required_before_entitlement", "frontend_can_grant_entitlement",
        "frontend_can_grant_quota", "quota_grant_source", "secret_exposed",
    },
    "domestic_payment": {
        "provider", "checkout_mode", "billing_mode", "status", "configured_component_count",
        "required_component_count", "verified_paid_order_count", "public_charging_allowed",
        "charge_now_allowed", "triggers_real_charge", "triggers_real_refund",
        "calls_external_payment_api", "frontend_gets_payment_secret", "secret_exposed",
    },
}
PRODUCT_EVIDENCE_PUBLIC_FIELDS = {
    "latest_ebay_packet_status", "latest_ebay_packet_source_mode",
    "latest_ebay_packet_present_resource_keys", "latest_ebay_packet_missing_resource_keys",
    "latest_ebay_packet_current_connection", "historical_ebay_packet_present",
    "ebay_token_refresh_success_count", "secret_exposed",
}
OPERATIONAL_HEALTH_PUBLIC_FIELDS = {"status", "detail_scope", "secret_exposed"}
APPROVED_SENSITIVE_PUBLIC_FIELDS = {
    "internal_detail_required", "credential_present", "ebay_token_refresh_success_count",
    "frontend_gets_payment_secret", "frontend_gets_model_api_key",
    "runtime_gets_model_api_key", "frontend_gets_search_api_key",
    "runtime_gets_search_api_key", "frontend_gets_media_api_key",
    "runtime_gets_raw_secret", "reports_get_raw_provider_response",
    "raw_provider_response_stored", "secret_exposed",
}

def has_unapproved_sensitive_field(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = key.lower()
            sensitive = any(
                marker in lowered
                for marker in ("secret", "token", "credential", "password", "api_key", "internal", "raw_")
            )
            if sensitive and key not in APPROVED_SENSITIVE_PUBLIC_FIELDS:
                return True
            if has_unapproved_sensitive_field(nested):
                return True
    elif isinstance(value, list):
        return any(has_unapproved_sensitive_field(item) for item in value)
    return False

if not isinstance(payload, dict) or set(payload) != PUBLIC_ROOT_FIELDS:
    raise SystemExit(2)
readiness = payload.get("readiness") or {}
if not isinstance(readiness, dict) or set(readiness) != READINESS_PUBLIC_FIELDS:
    raise SystemExit(2)
if has_unapproved_sensitive_field(payload):
    raise SystemExit(2)
items = readiness.get("items")
if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
    raise SystemExit(2)
item_by_key = {}
for item in items:
    if set(item) != ITEM_PUBLIC_FIELDS:
        raise SystemExit(2)
    key = item.get("key")
    if not isinstance(key, str) or not key or key in item_by_key:
        raise SystemExit(2)
    if item.get("severity") not in {"blocker", "warning"}:
        raise SystemExit(2)
    item_by_key[key] = item
blockers = [item for item in items if item.get("severity") == "blocker"]
warnings = [item for item in items if item.get("severity") == "warning"]
blocker_count = readiness.get("blocker_count")
warning_count = readiness.get("warning_count")
providers = readiness.get("provider_status") or {}
if not isinstance(providers, dict) or set(providers) != PROVIDER_PUBLIC_FIELDS:
    raise SystemExit(2)
for provider_key, provider_value in providers.items():
    if not isinstance(provider_value, dict) or set(provider_value) != PROVIDER_SUBFIELDS[provider_key]:
        raise SystemExit(2)
billing = providers.get("billing") or {}
model_value = providers.get("model_value") or {}
platform_model = providers.get("ai_ceo_platform_model") or {}
public_search = providers.get("public_search") or {}
media_generation = providers.get("media_generation") or {}
for nested_key, allowed_fields in BILLING_NESTED_SUBFIELDS.items():
    if nested_key in billing:
        nested_value = billing.get(nested_key)
        if not isinstance(nested_value, dict) or set(nested_value) != allowed_fields:
            raise SystemExit(2)
product_evidence = readiness.get("product_evidence")
if product_evidence is not None and (
    not isinstance(product_evidence, dict)
    or set(product_evidence) != PRODUCT_EVIDENCE_PUBLIC_FIELDS
):
    raise SystemExit(2)
operational_health = readiness.get("operational_health")
if operational_health is not None and (
    not isinstance(operational_health, dict)
    or set(operational_health) != OPERATIONAL_HEALTH_PUBLIC_FIELDS
):
    raise SystemExit(2)
billing_item = item_by_key.get("billing_quota") or {}
launch_path = billing.get("merchant_launch_path") or {}
domestic_payment = billing.get("domestic_payment") or {}

def strict_nonnegative_int(value):
    return type(value) is int and value >= 0

def strict_text(value, *, allowed=None, limit=1024):
    return (
        isinstance(value, str)
        and 0 < len(value) <= limit
        and (allowed is None or value in allowed)
    )

def strict_string_set(value, expected):
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and len(value) == len(set(value))
        and set(value) == expected
    )

def exact_boolean_fields(value, expectations):
    return all(value.get(field) is expected for field, expected in expectations.items())

payment_status_contracts = {
    "provider_connection_in_progress": (
        "provider_connection_in_progress",
        "merchant_payment_provider_connection_not_ready",
        False,
        False,
    ),
    "provider_activation_pending": (
        "provider_activation_pending",
        "merchant_payment_provider_runtime_activation_pending",
        False,
        True,
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
private_beta_payment_statuses = {
    "provider_connection_in_progress", "provider_activation_pending",
    "production_environment_pending", "refund_controls_pending",
    "controlled_acceptance_pending",
}
payment_contract = payment_status_contracts.get(billing.get("payment_path_status"))
public_launch_mode = billing.get("payment_path_status") == "public_checkout_available"
expected_ebay_resource_keys = {
    "store_profile", "account_business_policies", "inventory_and_offers",
    "orders_and_fulfillment", "finances", "taxonomy_listing_metadata",
}
top_level_contract_ready = (
    readiness.get("readiness_version") == "2026-05-15-product-saas"
    and readiness.get("authenticated_summary") is False
)
backup_item = item_by_key.get("backup_restore") or {}
# This is an admission hold, not proof of its underlying cause or a restore drill.
# Other backup statuses, provider failures and unknown public items stay rejected.
public_backup_hold = (
    public_launch_mode
    and set(item_by_key) == {"backup_restore"}
    and backup_item.get("label") == "Backup and restore"
    and backup_item.get("status") == "blocked_backup_restore_not_ready"
    and backup_item.get("severity") == "blocker"
    and strict_text(backup_item.get("detail"))
    and strict_text(backup_item.get("next_action"))
)
item_contract_ready = (
    (
        public_launch_mode
        and (item_by_key == {} or public_backup_hold)
    )
    or (
        not public_launch_mode
        and billing_item.get("key") == "billing_quota"
        and billing_item.get("label") == "Billing and quota"
        and billing_item.get("severity") == "warning"
        and strict_text(billing_item.get("detail"))
        and strict_text(billing_item.get("next_action"))
    )
)
product_evidence_ready = (
    product_evidence.get("latest_ebay_packet_status") == "packet_cached_sanitized"
    and product_evidence.get("latest_ebay_packet_source_mode") == "official_api"
    and strict_string_set(
        product_evidence.get("latest_ebay_packet_present_resource_keys"),
        expected_ebay_resource_keys,
    )
    and product_evidence.get("latest_ebay_packet_missing_resource_keys") == []
    and product_evidence.get("latest_ebay_packet_current_connection") is True
    and type(product_evidence.get("historical_ebay_packet_present")) is bool
    and strict_nonnegative_int(product_evidence.get("ebay_token_refresh_success_count"))
    and product_evidence.get("secret_exposed") is False
)
operational_health_ready = (
    operational_health.get("status") == "ready"
    and operational_health.get("detail_scope") == "summary_only"
    and operational_health.get("secret_exposed") is False
)
model_value_ready = (
    model_value.get("status") == "ready"
    and model_value.get("ready") is True
    and strict_string_set(
        model_value.get("live_model_report_types"),
        {"listing.package", "market.report"},
    )
    and type(model_value.get("blocker_count")) is int
    and model_value.get("blocker_count") == 0
    and model_value.get("secret_exposed") is False
)
platform_model_ready = (
    platform_model.get("status") == "ready"
    and strict_text(
        platform_model.get("provider"),
        allowed={
            "openai", "deepseek", "openrouter", "qwen_dashscope", "moonshot",
            "anthropic", "google_gemini", "tencent_hunyuan",
        },
        limit=64,
    )
    and strict_text(platform_model.get("model"), limit=160)
    and platform_model.get("trial_request_limit") == 20
    and type(platform_model.get("trial_request_limit")) is int
    and platform_model.get("trial_duration_days") == 7
    and type(platform_model.get("trial_duration_days")) is int
    and platform_model.get("trial_quota_scope") == "account_trial_window"
    and platform_model.get("usage_owner") == "jiejing_platform_trial"
    and platform_model.get("exhaustion_blocker") == "platform_default_model_trial_exhausted"
    and platform_model.get("customer_visible_next_action") == "save_account_ai_or_upgrade_plan"
    and exact_boolean_fields(
        platform_model,
        {
            "enabled": True,
            "configured": True,
            "quota_checked_by_backend": True,
            "hard_stop_on_exhaustion": True,
            "merchant_byok_preferred": True,
            "merchant_byok_not_counted_against_platform_trial": True,
            "byok_bypasses_platform_trial": True,
            "operator_cost_monitoring_required": True,
            "frontend_can_grant_quota": False,
            "frontend_gets_model_api_key": False,
            "runtime_gets_model_api_key": False,
            "secret_exposed": False,
        },
    )
)
public_search_ready = (
    public_search.get("provider") == "tavily"
    and public_search.get("endpoint_host") == "api.tavily.com"
    and exact_boolean_fields(
        public_search,
        {
            "configured": True,
            "credential_present": True,
            "ai_ceo_realtime_search_enabled": True,
            "builtin_public_web_fallback_enabled": True,
            "builtin_stock_quote_fallback_enabled": True,
            "frontend_gets_search_api_key": False,
            "runtime_gets_search_api_key": False,
            "secret_exposed": False,
        },
    )
)
media_generation_ready = (
    media_generation.get("contract_version") == "2026-07-05-media-generation-readiness"
    and media_generation.get("status") == "live_generation_ready_waiting_asset_review"
    and strict_text(media_generation.get("customer_visible_summary"))
    and strict_text(media_generation.get("next_action"))
    and exact_boolean_fields(
        media_generation,
        {
            "configured": True,
            "live_generation_enabled": True,
            "live_image_generation_enabled": True,
            "live_video_generation_enabled": True,
            "live_provider_calls_allowed": True,
            "asset_manifest_required": True,
            "asset_review_required": True,
            "fact_review_required": True,
            "human_review_required_before_listing": True,
            "cost_guard_required": True,
            "spend_now_allowed": False,
            "listing_use_requires_review": True,
            "frontend_gets_media_api_key": False,
            "runtime_gets_raw_secret": False,
            "reports_get_raw_provider_response": False,
            "raw_provider_response_stored": False,
            "secret_exposed": False,
        },
    )
)
billing_counts_ready = (
    strict_nonnegative_int(billing.get("configured_component_count"))
    and billing.get("configured_component_count") == 9
    and strict_nonnegative_int(billing.get("required_component_count"))
    and billing.get("required_component_count") == 9
    and strict_nonnegative_int(billing.get("verified_paid_order_count"))
    and (
        not public_launch_mode
        or billing.get("verified_paid_order_count") > 0
    )
    and type(billing.get("paid_launch_blocker_count")) is int
    and billing.get("paid_launch_blocker_count") == (0 if public_launch_mode else 1)
    and domestic_payment.get("configured_component_count") == billing.get("configured_component_count")
    and type(domestic_payment.get("configured_component_count")) is int
    and domestic_payment.get("required_component_count") == billing.get("required_component_count")
    and type(domestic_payment.get("required_component_count")) is int
    and domestic_payment.get("verified_paid_order_count") == billing.get("verified_paid_order_count")
    and type(domestic_payment.get("verified_paid_order_count")) is int
)
billing_status_ready = (
    billing.get("provider") == "wechat_pay_native"
    and billing.get("checkout_mode") == "native_qr"
    and billing.get("billing_mode") == "one_time_30_day_plan"
    and domestic_payment.get("provider") == "wechat_pay_native"
    and domestic_payment.get("checkout_mode") == "native_qr"
    and domestic_payment.get("billing_mode") == "one_time_30_day_plan"
    and (
        (
            public_launch_mode
            and billing.get("provider_configured") is True
            and billing.get("next_paid_launch_blocker") == ""
            and billing.get("mainland_payment_ready_for_owner_approval") is True
            and domestic_payment.get("status") == "public_checkout_available"
            and launch_path.get("contract_version")
            == "2026-08-22-public-commercial-release-v1"
            and launch_path.get("current_stage") == "public_checkout_available"
            and launch_path.get("current_charge_status") == "checkout_available"
        )
        or (
            not public_launch_mode
            and payment_contract is not None
            and billing.get("provider_configured") is payment_contract[3]
            and domestic_payment.get("status") == payment_contract[0]
            and billing.get("next_paid_launch_blocker") == payment_contract[1]
            and billing.get("mainland_payment_ready_for_owner_approval") is payment_contract[2]
            and (
                (
                    launch_path.get("contract_version")
                    == "2026-07-27-merchant-mainland-payment-path-v1"
                    and launch_path.get("current_stage") == billing.get("payment_path_status")
                )
                or (
                    billing_item.get("status") == "private_beta_ready_paid_launch_pending"
                    and launch_path.get("contract_version")
                    == "2026-07-03-merchant-billing-launch-path-v1"
                    and launch_path.get("current_stage") == "invited_beta_no_real_charge"
                )
            )
            and launch_path.get("current_charge_status") == "no_real_charge_now"
        )
    )
    and launch_path.get("quota_grant_source") == "backend_subscription_state"
)
billing_safety_ready = (
    exact_boolean_fields(
        billing,
        {
            "billing_ready_for_private_beta": True,
            "billing_ready_for_paid_launch": public_launch_mode,
            "quota_enforcement_enabled": True,
            "public_charging_allowed": public_launch_mode,
            "charge_now_allowed": public_launch_mode,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "real_platform_writes_enabled": False,
            "frontend_gets_payment_secret": False,
            "frontend_can_grant_quota": False,
            "secret_exposed": False,
        },
    )
    and exact_boolean_fields(
        launch_path,
        {
            "public_paid_launch_allowed": public_launch_mode,
            "charge_now_allowed": public_launch_mode,
            "triggers_real_charge": False,
            "backend_confirmation_required_before_entitlement": True,
            "frontend_can_grant_entitlement": False,
            "frontend_can_grant_quota": False,
            "secret_exposed": False,
        },
    )
    and exact_boolean_fields(
        domestic_payment,
        {
            "public_charging_allowed": public_launch_mode,
            "charge_now_allowed": public_launch_mode,
            "triggers_real_charge": False,
            "triggers_real_refund": False,
            "calls_external_payment_api": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
    )
)
item_payment_projection_ready = (
    (public_launch_mode and (item_by_key == {} or public_backup_hold))
    or (
        billing_item.get("status") == "private_beta_ready_paid_launch_pending"
        and billing.get("payment_path_status") in private_beta_payment_statuses
    )
    or (
        billing_item.get("status") == "mainland_payment_ready_for_owner_approval"
        and billing.get("payment_path_status")
        == "controlled_acceptance_proven_public_charging_closed"
    )
)
owner_verified_order_ready = (
    (
        public_launch_mode
        and type(billing.get("verified_paid_order_count")) is int
        and billing.get("verified_paid_order_count") > 0
        and type(domestic_payment.get("verified_paid_order_count")) is int
        and domestic_payment.get("verified_paid_order_count")
        == billing.get("verified_paid_order_count")
    )
    or billing_item.get("status") != "mainland_payment_ready_for_owner_approval"
    or (
        type(billing.get("verified_paid_order_count")) is int
        and billing.get("verified_paid_order_count") > 0
        and type(domestic_payment.get("verified_paid_order_count")) is int
        and domestic_payment.get("verified_paid_order_count")
        == billing.get("verified_paid_order_count")
    )
)
readiness_projection_ready = (
    (
        public_launch_mode
        and (set(item_by_key) == set() or public_backup_hold)
        and warning_count == 0
        and readiness.get("production_ready") is (not public_backup_hold)
        and readiness.get("beta_ready") is (not public_backup_hold)
        and readiness.get("can_accept_real_customers") is (not public_backup_hold)
        and billing.get("billing_ready_for_paid_launch") is True
        and billing.get("public_charging_allowed") is True
        and billing.get("charge_now_allowed") is True
    )
    or (
        not public_launch_mode
        and set(item_by_key) == {"billing_quota"}
        and readiness.get("beta_ready") is True
        and readiness.get("production_ready") is False
        and readiness.get("can_accept_real_customers") is False
        and billing_item.get("status") in {
            "private_beta_ready_paid_launch_pending",
            "mainland_payment_ready_for_owner_approval",
        }
        and (
            (
                billing_item.get("status") == "private_beta_ready_paid_launch_pending"
                and billing.get("mainland_payment_ready_for_owner_approval") is False
            )
            or (
                billing_item.get("status") == "mainland_payment_ready_for_owner_approval"
                and billing.get("mainland_payment_ready_for_owner_approval") is True
            )
        )
        and billing_item.get("severity") == "warning"
        and billing.get("billing_ready_for_paid_launch") is False
        and billing.get("public_charging_allowed") is False
        and billing.get("charge_now_allowed") is False
    )
)
ready = (
    readiness.get("service") == "jiejing-saas-backend"
    and readiness.get("public_contract_version") == "2026-07-15-public-readiness-current-ebay-evidence"
    and readiness.get("detail_scope") == "public_summary"
    and readiness.get("internal_detail_required") is True
    and readiness.get("environment") == "production"
    and type(blocker_count) is int
    and blocker_count == len(blockers) == (1 if public_backup_hold else 0)
    and type(warning_count) is int
    and warning_count == len(warnings)
    and readiness_projection_ready
    and readiness.get("real_platform_writes_enabled") is False
    and readiness.get("requested_real_platform_writes") is False
    and readiness.get("secret_exposed") is False
    and product_evidence.get("latest_ebay_packet_status") == "packet_cached_sanitized"
    and model_value.get("status") == "ready"
    and (public_backup_hold or "backup_restore" not in item_by_key)
    and "monitoring_alerting" not in item_by_key
    and "backup" not in providers
    and billing.get("billing_ready_for_private_beta") is True
    and billing.get("quota_enforcement_enabled") is True
    and public_search.get("runtime_gets_search_api_key") is False
    and billing.get("triggers_real_charge") is False
    and billing.get("triggers_real_refund") is False
    and billing.get("real_platform_writes_enabled") is False
    and billing.get("secret_exposed") is False
    and top_level_contract_ready
    and item_contract_ready
    and product_evidence_ready
    and operational_health_ready
    and model_value_ready
    and platform_model_ready
    and public_search_ready
    and media_generation_ready
    and billing_counts_ready
    and billing_status_ready
    and billing_safety_ready
    and item_payment_projection_ready
    and owner_verified_order_ready
)
if not ready:
    raise SystemExit(2)
commercial_ready = public_launch_mode and not public_backup_hold
report = {
    "PUBLIC_READINESS_CONTRACT_STATUS": "verified",
    "COMMERCIAL_READINESS_STATUS": "ready" if commercial_ready else "blocked",
    "COMMERCIAL_READINESS_REASON": "backup_restore" if public_backup_hold else "none" if commercial_ready else "billing_quota",
    "COMMERCIAL_BLOCKER_COUNT": blocker_count,
    "COMMERCIAL_WARNING_COUNT": warning_count,
    "COMMERCIAL_PRODUCTION_READY": readiness["production_ready"],
    "COMMERCIAL_BETA_READY": readiness["beta_ready"],
    "COMMERCIAL_CAN_ACCEPT_REAL_CUSTOMERS": readiness["can_accept_real_customers"],
    "COMMERCIAL_PUBLIC_CHARGING_ALLOWED": billing["public_charging_allowed"],
}
for key, value in report.items():
    print(f"{key}={str(value).lower()}")
' <<<"$body" 2>/dev/null)" || { PUBLIC_READINESS_REPORT=""; return 2; }
}

wait_for_public_readiness() {
  local attempt
  for attempt in $(seq 1 "$PUBLIC_READINESS_MAX_ATTEMPTS"); do
    if public_readiness_ready; then
      return 0
    fi
    if [[ "$attempt" -lt "$PUBLIC_READINESS_MAX_ATTEMPTS" ]]; then
      sleep "$PUBLIC_READINESS_RETRY_SECONDS"
    fi
  done
  return 1
}

wait_for_api_health() {
  local container_id state health attempt
  for attempt in $(seq 1 60); do
    container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-saas 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id" 2>/dev/null || true)"
      if [[ "$state" == "running" && "$health" == "healthy" ]] && public_health_ready; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

wait_for_worker_health() {
  local container_id state attempt
  for attempt in $(seq 1 60); do
    container_id="$(docker compose "${COMPOSE_ARGS[@]}" ps -q jiejing-worker 2>/dev/null || true)"
    if [[ -n "$container_id" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
      if [[ "$state" == "running" ]] && public_deep_health_ready; then
        return 0
      fi
    fi
    sleep 2
  done
  return 1
}

approved_image_reference_matches() {
  local image_reference="$1" approved_image_id="$2" resolved_image_id
  resolved_image_id="$(docker image inspect --format '{{.Id}}' "$image_reference" 2>/dev/null || true)"
  [[ "$resolved_image_id" == "$approved_image_id" ]]
}

capture_and_validate_runtime_images() {
  mapfile -t api_containers < <(
    docker ps \
      --filter 'label=com.docker.compose.project=deploy' \
      --filter 'label=com.docker.compose.service=jiejing-saas' \
      --format '{{.ID}}'
  )
  [[ "${#api_containers[@]}" -eq 1 ]] || fail_closed "runtime_api_container_not_unique"
  approved_api_container_id="${api_containers[0]}"

  runtime_api_project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_service="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_config_files="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_project_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_environment_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_image_id="$(docker inspect --format '{{.Image}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_image_ref="$(docker inspect --format '{{.Config.Image}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_state="$(docker inspect --format '{{.State.Status}}' "$approved_api_container_id" 2>/dev/null || true)"
  runtime_api_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$approved_api_container_id" 2>/dev/null || true)"

  [[ "$runtime_api_project" == "deploy" && "$runtime_api_service" == "jiejing-saas" ]] \
    || fail_closed "runtime_compose_label_mismatch"
  canonical_path_equals "$runtime_api_config_files" "$runtime_compose" \
    || fail_closed "runtime_compose_label_mismatch"
  canonical_path_equals "$runtime_api_project_dir" "$active_app/deploy" \
    || fail_closed "runtime_compose_label_mismatch"
  [[ "$runtime_api_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail_closed "runtime_api_image_untrusted"
  docker image inspect "$runtime_api_image_id" >/dev/null 2>&1 \
    || fail_closed "runtime_api_image_untrusted"
  approved_image_reference_matches "$runtime_api_image_ref" "$runtime_api_image_id" \
    || fail_closed "api_image_reference_drift"
  [[ "$runtime_api_state" == "running" && "$runtime_api_health" == "healthy" ]] \
    || fail_closed "runtime_api_container_unhealthy"

  mapfile -t worker_containers < <(
    docker ps \
      --filter 'label=com.docker.compose.project=deploy' \
      --filter 'label=com.docker.compose.service=jiejing-worker' \
      --format '{{.ID}}'
  )
  [[ "${#worker_containers[@]}" -eq 1 ]] || fail_closed "runtime_worker_container_not_unique"
  approved_worker_container_id="${worker_containers[0]}"
  runtime_worker_project="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_service="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_config_files="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_project_dir="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_environment_file="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.environment_file" }}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_image_id="$(docker inspect --format '{{.Image}}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_image_ref="$(docker inspect --format '{{.Config.Image}}' "$approved_worker_container_id" 2>/dev/null || true)"
  runtime_worker_state="$(docker inspect --format '{{.State.Status}}' "$approved_worker_container_id" 2>/dev/null || true)"

  [[ "$runtime_worker_project" == "deploy" && "$runtime_worker_service" == "jiejing-worker" ]] \
    || fail_closed "runtime_worker_compose_label_mismatch"
  canonical_path_equals "$runtime_worker_config_files" "$runtime_compose" \
    || fail_closed "runtime_worker_compose_label_mismatch"
  canonical_path_equals "$runtime_worker_project_dir" "$active_app/deploy" \
    || fail_closed "runtime_worker_compose_label_mismatch"
  [[ "$runtime_worker_environment_file" == "$runtime_api_environment_file" ]] \
    || fail_closed "runtime_environment_label_mismatch"
  [[ "$runtime_worker_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || fail_closed "runtime_worker_image_untrusted"
  docker image inspect "$runtime_worker_image_id" >/dev/null 2>&1 \
    || fail_closed "runtime_worker_image_untrusted"
  approved_image_reference_matches "$runtime_worker_image_ref" "$runtime_worker_image_id" \
    || fail_closed "worker_image_reference_drift"
  [[ "$runtime_worker_state" == "running" ]] \
    || fail_closed "runtime_worker_image_untrusted"
  public_deep_health_ready \
    || fail_closed "runtime_worker_operational_unhealthy"

  environment_file="$runtime_api_environment_file"
}

run_cos_probe() {
  local cos_output env_digest_after
  cos_output="$(docker run --rm --network bridge \
    --mount "type=bind,src=$private_dir,dst=/private" \
    -w /app "$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py \
    --env-file /private/jiejing-saas.production.env \
    --verify-cos-backup-probe --apply 2>/dev/null)" || {
    LAST_BLOCKER="cos_probe_failed"
    return 2
  }
  if ! json_contract_verified cos <<<"$cos_output" >/dev/null 2>&1; then
    unset cos_output
    LAST_BLOCKER="cos_probe_contract_rejected"
    return 2
  fi
  unset cos_output
  if ! trusted_private_file "$APP_ENV"; then
    LAST_BLOCKER="private_env_permissions_untrusted"
    return 2
  fi
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" || {
    LAST_BLOCKER="private_env_digest_failed"
    return 2
  }
  if [[ "$env_digest_after" != "$env_digest_before" ]]; then
    LAST_BLOCKER="environment_drift_detected"
    return 2
  fi
  printf '%s\n' "COS_PROBE_STATUS=verified"
}

run_cls_probe() {
  local alarm_output cls_output env_digest_after
  alarm_output="$(docker run --rm --network bridge \
    --mount "type=bind,src=$private_dir,dst=/private" \
    -w /app "$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py \
    --env-file /private/jiejing-saas.production.env \
    --verify-provider-alarms --apply 2>/dev/null)" || {
    LAST_BLOCKER="provider_alarm_readback_failed"
    return 2
  }
  if ! json_contract_verified alarm <<<"$alarm_output" >/dev/null 2>&1; then
    unset alarm_output
    LAST_BLOCKER="provider_alarm_readback_contract_rejected"
    return 2
  fi
  unset alarm_output
  if ! trusted_private_file "$APP_ENV"; then
    LAST_BLOCKER="private_env_permissions_untrusted"
    return 2
  fi
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" || {
    LAST_BLOCKER="private_env_digest_failed"
    return 2
  }
  if [[ "$env_digest_after" != "$env_digest_before" ]]; then
    LAST_BLOCKER="environment_drift_detected"
    return 2
  fi
  printf '%s\n' "PROVIDER_ALARM_STATUS=verified"

  cls_output="$(docker run --rm --network bridge \
    --mount "type=bind,src=$private_dir,dst=/private" \
    -w /app "$runtime_api_image_id" python tools/jiejing_configure_tencent_runtime_env.py \
    --env-file /private/jiejing-saas.production.env \
    --verify-provider-cls-probe --apply 2>/dev/null)" || {
    LAST_BLOCKER="cls_probe_failed"
    return 2
  }
  if ! json_contract_verified cls <<<"$cls_output" >/dev/null 2>&1; then
    unset cls_output
    LAST_BLOCKER="cls_probe_contract_rejected"
    return 2
  fi
  unset cls_output
  if ! trusted_private_file "$APP_ENV"; then
    LAST_BLOCKER="private_env_permissions_untrusted"
    return 2
  fi
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" || {
    LAST_BLOCKER="private_env_digest_failed"
    return 2
  }
  if [[ "$env_digest_after" != "$env_digest_before" ]]; then
    LAST_BLOCKER="environment_drift_detected"
    return 2
  fi
  printf '%s\n' "CLS_PROBE_STATUS=verified"
}

runtime_evidence_json_verified() {
  python3 -c '
import json, re, sys
def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate")
        result[key] = value
    return result
try:
    value = json.load(sys.stdin, object_pairs_hook=unique)
    common = isinstance(value, dict) and value.get("contract_version") == "jiejing_runtime_evidence_snapshot_v1" and value.get("secret_exposed") is False
    if sys.argv[1] == "capability":
        valid = common and set(value) == {"status", "contract_version", "secret_exposed", "writes_snapshot"} and value.get("status") == "capable" and value.get("writes_snapshot") is False
    else:
        valid = common and set(value) == {"status", "contract_version", "secret_exposed", "evidence_sha256"} and value.get("status") == "verified" and isinstance(value.get("evidence_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", value["evidence_sha256"])
    sys.exit(0 if valid else 2)
except (ValueError, TypeError, KeyError):
    sys.exit(2)
' "$1"
}

trusted_runtime_evidence_directory() {
  local ancestor="$EVIDENCE_DIRECTORY"
  [[ "$EVIDENCE_DIRECTORY" == "$PRODUCTION_ROOT/runtime-evidence" ]] || return 1
  [[ -d "$EVIDENCE_DIRECTORY" && ! -L "$EVIDENCE_DIRECTORY" ]] || return 1
  [[ "$(readlink -f -- "$EVIDENCE_DIRECTORY" 2>/dev/null || true)" == "$EVIDENCE_DIRECTORY" ]] || return 1
  while :; do
    trusted_private_directory "$ancestor" || return 1
    [[ "$ancestor" != / ]] || break
    ancestor="$(dirname -- "$ancestor")"
  done
  [[ "$(stat -c '%U:%G %a' -- "$EVIDENCE_DIRECTORY" 2>/dev/null || true)" == "root:root 755" ]]
}

runtime_evidence_mount_verified() {
  local container="$1" selected_env
  # Select only this public path; never collect or print the container environment.
  selected_env="$(docker inspect --format '{{range .Config.Env}}{{if eq (index (split . "=") 0) "JIEJING_RUNTIME_EVIDENCE_FILE"}}{{println .}}{{end}}{{end}}' "$container" 2>/dev/null)" || return 1
  [[ "$selected_env" == "JIEJING_RUNTIME_EVIDENCE_FILE=$EVIDENCE_MOUNT/current.json" ]] || return 1
  docker inspect --format '{{json .Mounts}}' "$container" 2>/dev/null | python3 -c '
import json, sys
try:
    mounts = json.load(sys.stdin)
    target, source = sys.argv[1:]
    if not isinstance(mounts, list) or not all(isinstance(item, dict) for item in mounts): raise ValueError()
    selected = [item for item in mounts if item.get("Destination") == target]
    valid = len(selected) == 1 and selected[0].get("Type") == "bind" and selected[0].get("Source") == source and selected[0].get("RW") is False
    valid = valid and not any(str(item.get("Destination", "")).startswith(target + "/") for item in mounts)
    sys.exit(0 if valid else 2)
except (ValueError, TypeError):
    sys.exit(2)
' "$EVIDENCE_MOUNT" "$EVIDENCE_DIRECTORY" >/dev/null 2>&1
}

verify_runtime_evidence_support() {
  local image capability
  trusted_runtime_evidence_directory || { LAST_BLOCKER="runtime_evidence_directory_untrusted"; return 2; }
  runtime_evidence_mount_verified "$approved_api_container_id" \
    && runtime_evidence_mount_verified "$approved_worker_container_id" \
    || { LAST_BLOCKER="runtime_evidence_mount_untrusted"; return 2; }
  for image in "$runtime_api_image_id" "$runtime_worker_image_id"; do
    capability="$(docker run --rm --network none -w /app "$image" python \
      tools/jiejing_runtime_evidence_snapshot.py --check-capability 2>/dev/null)" \
      || { LAST_BLOCKER="runtime_evidence_capability_missing"; return 2; }
    if ! runtime_evidence_json_verified capability <<<"$capability" >/dev/null 2>&1; then
      unset capability
      LAST_BLOCKER="runtime_evidence_capability_missing"
      return 2
    fi
    unset capability
  done
}

publish_runtime_evidence_snapshot() {
  local snapshot_output env_digest_after
  trusted_runtime_evidence_directory || { LAST_BLOCKER="runtime_evidence_directory_untrusted"; return 2; }
  trusted_private_file "$APP_ENV" || { LAST_BLOCKER="private_env_permissions_untrusted"; return 2; }
  env_digest_after="$(evidence_excluded_env_digest "$APP_ENV")" \
    || { LAST_BLOCKER="private_env_digest_failed"; return 2; }
  [[ "$env_digest_after" == "$env_digest_before" ]] \
    || { LAST_BLOCKER="environment_drift_detected"; return 2; }
  snapshot_output="$(docker run --rm --network none \
    --mount "type=bind,src=$private_dir,dst=/private,readonly" \
    --mount "type=bind,src=$EVIDENCE_DIRECTORY,dst=/runtime-evidence" \
    -w /app "$runtime_api_image_id" python tools/jiejing_runtime_evidence_snapshot.py \
    --env-file /private/jiejing-saas.production.env --output-dir /runtime-evidence 2>/dev/null)" \
    || { LAST_BLOCKER="runtime_evidence_snapshot_failed"; return 2; }
  if ! runtime_evidence_json_verified snapshot <<<"$snapshot_output" >/dev/null 2>&1; then
    unset snapshot_output
    LAST_BLOCKER="runtime_evidence_snapshot_contract_rejected"
    return 2
  fi
  unset snapshot_output
  printf '%s\n' "RUNTIME_EVIDENCE_SNAPSHOT_STATUS=verified"
}

verify_unchanged_runtime() {
  local before_api="$approved_api_container_id" before_worker="$approved_worker_container_id"
  local before_api_image="$runtime_api_image_id" before_worker_image="$runtime_worker_image_id"
  # Recapture all labels, image refs and operational health without any lifecycle action.
  capture_and_validate_runtime_images || return $?
  [[ "$approved_api_container_id" == "$before_api" && "$runtime_api_image_id" == "$before_api_image" ]] \
    || { LAST_BLOCKER="api_identity_mismatch"; return 2; }
  [[ "$approved_worker_container_id" == "$before_worker" && "$runtime_worker_image_id" == "$before_worker_image" ]] \
    || { LAST_BLOCKER="worker_identity_mismatch"; return 2; }
  runtime_evidence_mount_verified "$approved_api_container_id" \
    && runtime_evidence_mount_verified "$approved_worker_container_id" \
    || { LAST_BLOCKER="runtime_evidence_mount_untrusted"; return 2; }
  printf '%s\n' "API_RUNTIME_STATUS=unchanged" "WORKER_RUNTIME_STATUS=unchanged"
}

run_refresh_phases() {
  verify_runtime_evidence_support || return $?
  run_cos_probe || return $?
  run_cls_probe || return $?
  publish_runtime_evidence_snapshot || return $?
  verify_unchanged_runtime || return $?
}

main() {
trap 'printf "%s\n" "SECRET_EXPOSED=false"' EXIT
[[ "$#" -eq 0 ]] || fail_closed "unexpected_arguments"

if acquire_nonblocking_lock "$LOCK_FILE" 2>/dev/null; then
  lock_rc=0
else
  lock_rc=$?
fi
case "$lock_rc" in
  0) ;;
  10)
    printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=skipped"
    printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_BLOCKER=lock_busy"
    exit 0
    ;;
  *) fail_closed "maintenance_lock_failed" ;;
esac

[[ -L "$ACTIVE_LINK" ]] || fail_closed "active_release_untrusted"
[[ "$(stat -c '%U:%G' -- "$ACTIVE_LINK" 2>/dev/null || true)" == "root:root" ]] \
  || fail_closed "active_release_untrusted"
active_app="$(readlink -f -- "$ACTIVE_LINK" 2>/dev/null || true)"
case "$active_app" in
  "$RELEASE_ROOT"/*/app) ;;
  *) fail_closed "active_release_untrusted" ;;
esac
[[ -d "$active_app" ]] || fail_closed "active_release_untrusted"
runtime_compose="$active_app/deploy/$COMPOSE_NAME"
[[ -f "$runtime_compose" && ! -L "$runtime_compose" ]] || fail_closed "runtime_compose_untrusted"

capture_and_validate_runtime_images

environment_file_label="$environment_file"
environment_file="$(readlink -f -- "$environment_file_label" 2>/dev/null || true)"
[[ "$environment_file_label" == "$environment_file" ]] \
  || fail_closed "runtime_environment_label_mismatch"
private_dir="$(dirname -- "$environment_file")"
private_dir="$(readlink -f -- "$private_dir" 2>/dev/null || true)"
case "$private_dir" in
  "$PRODUCTION_ROOT/private"|"$RELEASE_ROOT"/*/private) ;;
  *) fail_closed "private_dir_untrusted" ;;
esac
trusted_private_directory "$private_dir" || fail_closed "private_dir_untrusted"
COMPOSE_ENV="$private_dir/production-compose.env"
APP_ENV="$private_dir/jiejing-saas.production.env"
[[ "$environment_file" == "$private_dir/production-compose.env" ]] \
  || fail_closed "runtime_environment_label_mismatch"
trusted_private_file "$COMPOSE_ENV" || fail_closed "private_env_permissions_untrusted"
trusted_private_file "$APP_ENV" || fail_closed "private_env_permissions_untrusted"

env_digest_before="$(evidence_excluded_env_digest "$APP_ENV")" \
  || fail_closed "private_env_digest_failed"

export JIEJING_PRODUCTION_PRIVATE_DIR="$private_dir"
COMPOSE_ARGS=(--project-name deploy --env-file "$COMPOSE_ENV" -f "$runtime_compose")
LAST_BLOCKER=""

docker run --rm --network none -w /app "$runtime_api_image_id" python -c \
  "from pathlib import Path; import sys; sys.exit(0 if Path('tools/jiejing_configure_tencent_runtime_env.py').is_file() else 2)" \
  >/dev/null 2>&1 || fail_closed "runtime_probe_tool_missing"
printf '%s\n' "LIVE_RELEASE_GUARD_STATUS=ready"

run_refresh_phases || fail_closed "${LAST_BLOCKER:-refresh_phase_failed}"

wait_for_public_readiness || fail_closed "public_readiness_contract_failed"
verify_unchanged_runtime || fail_closed "${LAST_BLOCKER:-runtime_identity_changed}"
printf '%s\n' "$PUBLIC_READINESS_REPORT"
printf '%s\n' "JIEJING_PRODUCTION_EVIDENCE_REFRESH_STATUS=success"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
