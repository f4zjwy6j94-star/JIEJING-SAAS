"""Durable merchant onboarding state and evidence-led next-action routing.

This module never initiates OAuth, read synchronization, billing or a platform
write. Merchant answers are intent only; current connection and account-health
evidence decide the effective stage.
"""

from __future__ import annotations

import re
from typing import Any


CONTRACT_VERSION = "2026-08-02-primary-ebay-onboarding-v1"
PRIMARY_EBAY_ONBOARDING_KEY = "primary_ebay"

ALLOWED_PATH_KEYS = {"newbie", "store_opened", "has_orders", "multi_store"}
ALLOWED_WORK_MODES = {"guided", "draft_only"}
ALLOWED_STEP_KEYS = {
    "actionQueue",
    "aiPermission",
    "bulkFactory",
    "businessPolicy",
    "costSplit",
    "dailyOps",
    "diagnosis",
    "dispatchRule",
    "ebayApi",
    "ebayStage",
    "firstListing",
    "fulfillment",
    "importScope",
    "listingAction",
    "logistics",
    "material",
    "messageLearning",
    "monitoring",
    "policyMap",
    "profitAudit",
    "profitFloor",
    "refundRule",
    "ruleInheritance",
    "serviceBoundary",
    "serviceQueue",
    "settingBacklog",
    "sourceApi",
    "sourceMap",
    "storeApiMap",
    "storeMap",
    "teamPermission",
}
AUTHORIZED_CONNECTION_STATUSES = {"read_only_authorized", "publish_authorized", "authorized", "connected"}
ACCOUNT_REVIEW_STATUSES = {"unknown", "restricted", "suspended", "payout_hold", "quota_limited"}
DERIVED_INPUT_KEYS = {
    "contract_version",
    "onboarding_key",
    "preferences_saved",
    "secret_exposed",
    "version",
    "store_id",
    "created_at",
    "updated_at",
    "updated_by_user_id",
    "effective_stage",
    "verified",
    "seller_registration_verified",
    "connection_current",
    "oauth_required",
    "publish_preflight_available",
    "real_publish_allowed",
}
ALLOWED_INPUT_KEYS = {
    "path_key",
    "current_step_key",
    "work_mode",
    "seller_returned",
    "answers",
    "completed_step_keys",
    "expected_version",
}
_CHOICE_PATTERN = re.compile(r"^choice_[0-7]$")
_SECRET_LIKE_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|credential|authorization|oauth[_-]?code|cookie|api[_-]?key|private[_-]?key|bank|card|identity|address)",
    re.IGNORECASE,
)


class MerchantOnboardingValidationError(ValueError):
    """Raised when client-supplied onboarding intent violates the allowlist."""


class MerchantOnboardingVersionConflict(RuntimeError):
    """Raised when a stale browser tries to overwrite newer onboarding state."""

    def __init__(self, latest: dict[str, Any] | None = None) -> None:
        super().__init__("merchant onboarding version conflict")
        self.latest = latest if isinstance(latest, dict) else {}


def normalize_merchant_onboarding_progress(
    value: dict[str, Any] | None,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return enum-only merchant intent without accepting derived truth fields."""

    payload = value if isinstance(value, dict) else {}
    prior = previous if isinstance(previous, dict) else {}
    unknown = set(payload) - ALLOWED_INPUT_KEYS - DERIVED_INPUT_KEYS
    if unknown:
        raise MerchantOnboardingValidationError(f"unsupported onboarding fields: {', '.join(sorted(unknown))}")

    path_key = _allowed_scalar(
        payload.get("path_key", prior.get("path_key", "newbie")),
        allowed=ALLOWED_PATH_KEYS,
        label="path_key",
    )
    default_step = "ebayStage" if path_key == "newbie" else _default_step_for_path(path_key)
    current_step_key = _allowed_scalar(
        payload.get("current_step_key", prior.get("current_step_key", default_step)),
        allowed=ALLOWED_STEP_KEYS,
        label="current_step_key",
    )
    work_mode = _allowed_scalar(
        payload.get("work_mode", prior.get("work_mode", "guided")),
        allowed=ALLOWED_WORK_MODES,
        label="work_mode",
    )
    seller_returned_value = payload.get("seller_returned", prior.get("seller_returned", False))
    if not isinstance(seller_returned_value, bool):
        raise MerchantOnboardingValidationError("seller_returned must be boolean")

    if "answers" in payload:
        answers = _normalize_answers(payload.get("answers"))
    else:
        answers = _normalize_answers(prior.get("answers", {}))
    if "completed_step_keys" in payload:
        completed_step_keys = _normalize_completed_steps(payload.get("completed_step_keys"))
    else:
        completed_step_keys = _normalize_completed_steps(prior.get("completed_step_keys", []))

    preferences_saved = bool(
        prior.get("preferences_saved")
        or answers
        or completed_step_keys
        or seller_returned_value
        or work_mode == "draft_only"
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "onboarding_key": PRIMARY_EBAY_ONBOARDING_KEY,
        "path_key": path_key,
        "current_step_key": current_step_key,
        "work_mode": work_mode,
        "seller_returned": seller_returned_value,
        "answers": answers,
        "completed_step_keys": completed_step_keys,
        "preferences_saved": preferences_saved,
        "secret_exposed": False,
    }


def build_merchant_onboarding_read_model(
    *,
    progress: dict[str, Any] | None = None,
    connections: list[dict[str, Any]] | None = None,
    account_health: dict[str, Any] | None = None,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive one merchant-safe next step from saved intent and backend evidence."""

    normalized = normalize_merchant_onboarding_progress(progress or {})
    safe_progress = {
        **normalized,
        "version": max(0, int((progress or {}).get("version") or 0)),
        "store_id": str((progress or {}).get("store_id") or ""),
        "created_at": str((progress or {}).get("created_at") or ""),
        "updated_at": str((progress or {}).get("updated_at") or ""),
    }
    safe_connections = connections if isinstance(connections, list) else []
    current_connection = next(
        (
            item
            for item in safe_connections
            if isinstance(item, dict)
            and str(item.get("platform") or "ebay").strip().lower() == "ebay"
            and str(item.get("status") or "").strip().lower() in AUTHORIZED_CONNECTION_STATUSES
        ),
        None,
    )
    connection_current = current_connection is not None
    health = account_health if isinstance(account_health, dict) else {}
    evidence = health.get("evidence_package") if isinstance(health.get("evidence_package"), dict) else {}
    account_status = str(health.get("status") or "").strip().lower()
    health_stage = str(health.get("onboarding_stage") or "").strip()
    official_packet_present = evidence.get("official_packet_present") is True
    business_policies_complete = evidence.get("business_policies_present") is True

    if not connection_current:
        new_seller_intent = normalized["path_key"] == "newbie" and normalized["answers"].get("ebayStage", "choice_0") == "choice_0"
        effective_stage = (
            "authorization_required"
            if normalized["seller_returned"] or not new_seller_intent
            else "seller_registration_required"
        )
    elif account_status == "registration_incomplete" or health_stage == "seller_registration_required":
        effective_stage = "seller_registration_required"
    elif account_status in ACCOUNT_REVIEW_STATUSES or health.get("incident_mode") is True or health_stage == "account_review_required":
        effective_stage = "account_review_required"
    elif not health or not official_packet_present:
        effective_stage = "read_only_check_required"
    elif health_stage == "business_policies_required" or not business_policies_complete:
        effective_stage = "business_policies_required"
    else:
        effective_stage = "ready_for_publish_preflight"

    next_action = _next_action(effective_stage, connection_current=connection_current)
    seller_registration_verified = bool(
        connection_current
        and official_packet_present
        and account_status not in ACCOUNT_REVIEW_STATUSES | {"registration_incomplete", ""}
    )
    store_id = str((store or {}).get("store_id") or (current_connection or {}).get("store_id") or "")
    return {
        "contract_version": CONTRACT_VERSION,
        "onboarding_key": PRIMARY_EBAY_ONBOARDING_KEY,
        "progress": safe_progress,
        "effective_stage": effective_stage,
        "stage_label": _stage_label(effective_stage),
        "stage_summary": _stage_summary(effective_stage, connection_current=connection_current),
        "next_action": next_action,
        "store_id": store_id,
        "connection_current": connection_current,
        "account_health_evidence_present": official_packet_present,
        "business_policies_complete": business_policies_complete,
        "business_policy_statuses": _business_policy_statuses(health, business_policies_complete),
        "seller_registration_verified": seller_registration_verified,
        "oauth_required": effective_stage == "authorization_required",
        "publish_preflight_available": effective_stage == "ready_for_publish_preflight",
        "draft_work_allowed": True,
        "verified": False,
        "real_publish_allowed": False,
        "triggers_oauth": False,
        "triggers_read_only_sync": False,
        "triggers_real_charge": False,
        "triggers_real_platform_write": False,
        "secret_exposed": False,
    }


def _allowed_scalar(value: Any, *, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise MerchantOnboardingValidationError(f"unsupported {label}")
    return value


def _normalize_answers(value: Any) -> dict[str, str | list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > len(ALLOWED_STEP_KEYS):
        raise MerchantOnboardingValidationError("answers must be a bounded object")
    result: dict[str, str | list[str]] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "")
        if key not in ALLOWED_STEP_KEYS or _SECRET_LIKE_PATTERN.search(key):
            raise MerchantOnboardingValidationError("unsupported onboarding answer key")
        if isinstance(raw_value, list):
            if len(raw_value) > 8 or not all(isinstance(item, str) and _CHOICE_PATTERN.fullmatch(item) for item in raw_value):
                raise MerchantOnboardingValidationError("unsupported onboarding answer choices")
            result[key] = list(dict.fromkeys(raw_value))
        elif isinstance(raw_value, str) and _CHOICE_PATTERN.fullmatch(raw_value):
            result[key] = raw_value
        else:
            raise MerchantOnboardingValidationError("unsupported onboarding answer choice")
    return result


def _normalize_completed_steps(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > len(ALLOWED_STEP_KEYS):
        raise MerchantOnboardingValidationError("completed_step_keys must be a bounded list")
    result: list[str] = []
    for raw_key in value:
        key = str(raw_key or "")
        if key not in ALLOWED_STEP_KEYS or _SECRET_LIKE_PATTERN.search(key):
            raise MerchantOnboardingValidationError("unsupported completed step")
        if key not in result:
            result.append(key)
    return result


def _default_step_for_path(path_key: str) -> str:
    return {
        "store_opened": "storeApiMap",
        "has_orders": "logistics",
        "multi_store": "storeMap",
    }.get(path_key, "ebayStage")


def _stage_label(stage: str) -> str:
    return {
        "seller_registration_required": "完成 eBay 卖家开通",
        "authorization_required": "连接 eBay 店铺",
        "read_only_check_required": "读取最新店铺状态",
        "account_review_required": "eBay 账号需要处理",
        "business_policies_required": "补齐店铺规则",
        "ready_for_publish_preflight": "可以准备第一条商品",
    }[stage]


def _stage_summary(stage: str, *, connection_current: bool) -> str:
    summaries = {
        "seller_registration_required": (
            "你的 eBay 连接仍然有效，无需重新授权。请先回 eBay 完成卖家资料、地址或收款验证。"
            if connection_current
            else "先去 eBay 官方完成卖家开通。身份、地址和收款资料只提交给 eBay，捷境不会向你索取 eBay 密码。"
        ),
        "authorization_required": "欢迎回来。下一步由你本人连接 eBay 官方授权；这一步不会发布商品。",
        "read_only_check_required": "连接已经保留。下一步只读取最新店铺状态，不会重新授权或写入 eBay。",
        "account_review_required": "账号存在需要处理的状态；先查看官方提示并保持真实操作暂停。",
        "business_policies_required": "付款、配送、退货三类店铺规则还没有全部准备好。可以先做草稿，发布前必须补齐。",
        "ready_for_publish_preflight": "eBay 卖家资料和三类店铺规则已可读取。下一步先做商品资料和发布体检；真实发布仍要你确认。",
    }
    return summaries[stage]


def _next_action(stage: str, *, connection_current: bool) -> dict[str, Any]:
    actions = {
        "seller_registration_required": {
            "key": "open_official_seller_registration",
            "label": "继续 eBay 卖家注册" if connection_current else "打开 eBay 官方卖家注册",
            "target": "https://www.ebay.com/sl/sell",
        },
        "authorization_required": {
            "key": "connect_ebay_official",
            "label": "连接 eBay 官方授权",
            "target": "settings.connections",
        },
        "read_only_check_required": {
            "key": "refresh_ebay_read_only",
            "label": "刷新只读店铺状态",
            "target": "settings.account",
        },
        "account_review_required": {
            "key": "review_ebay_account",
            "label": "查看账号处理清单",
            "target": "settings.account",
        },
        "business_policies_required": {
            "key": "review_business_policies",
            "label": "查看三类店铺规则",
            "target": "settings.connections",
        },
        "ready_for_publish_preflight": {
            "key": "open_listing_preflight",
            "label": "开始 Listing 草稿与发布体检",
            "target": "product.listing",
        },
    }
    return {
        **actions[stage],
        "requires_human": True,
        "can_trigger_oauth_on_explicit_click": stage == "authorization_required",
        "can_trigger_read_only_sync_on_explicit_click": stage == "read_only_check_required",
        "can_trigger_real_write": False,
        "can_trigger_payment": False,
    }


def _business_policy_statuses(health: dict[str, Any], complete: bool) -> dict[str, bool]:
    source = health.get("business_policy_statuses") if isinstance(health.get("business_policy_statuses"), dict) else {}
    if source:
        return {
            "payment": source.get("payment") is True,
            "fulfillment": source.get("fulfillment") is True,
            "return": source.get("return") is True,
        }
    return {"payment": complete, "fulfillment": complete, "return": complete}
