"""Read-only post-publish cockpit evidence for Jiejing SaaS."""

from __future__ import annotations

from typing import Any


REVIEW_WINDOWS: list[dict[str, Any]] = [
    {
        "after": "1h",
        "checks": ["曝光", "点击", "收藏", "客服风险", "是否需要补图"],
        "confirmation_required_for": ["改价", "补图", "暂停"],
    },
    {
        "after": "24h",
        "checks": ["曝光趋势", "点击率", "费用", "贡献毛利", "询单/售出"],
        "confirmation_required_for": ["改价", "库存", "广告预算"],
    },
    {
        "after": "7d",
        "checks": ["售出", "退货风险", "利润", "客服问题", "是否扩量"],
        "confirmation_required_for": ["下架", "扩库存", "调广告"],
    },
]


CONFIRMATION_GATED_OPERATIONS = [
    "revise_price",
    "revise_inventory",
    "end_listing",
    "delete_offer",
    "delete_inventory_item",
    "change_ads_budget",
    "refund_buyer",
    "change_store_policy",
    "sensitive_customer_promise",
]


def build_post_publish_cockpit(
    *,
    execution_results: list[dict[str, Any]] | None = None,
    confirmations: list[dict[str, Any]] | None = None,
    audit_logs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a merchant-safe post-publish cockpit packet without side effects."""

    execution_results = execution_results or []
    confirmations = confirmations or []
    audit_logs = audit_logs or []
    publish_executions = [item for item in execution_results if _action_type(item) == "publish_listing"]
    publish_confirmations = [item for item in confirmations if item.get("action_type") == "publish_listing"]
    cleanup_confirmations = [item for item in confirmations if item.get("action_type") == "cleanup_test_listing"]
    latest_execution = publish_executions[0] if publish_executions else None
    latest_result = _result(latest_execution)
    platform = _dict(latest_result.get("platform_result"))
    recovery = _dict(latest_result.get("publish_recovery"))
    published_offer = _dict(recovery.get("published_offer"))
    cleanup_plan = _dict(recovery.get("cleanup_plan"))
    cleanup_operations = [
        _sanitize_cleanup_operation(item)
        for item in _list(cleanup_plan.get("operations"))
        if isinstance(item, dict)
    ]
    listing_id = _first_text(platform.get("listing_id"), platform.get("listingId"), published_offer.get("listing_id"))
    offer_id = _first_text(platform.get("offer_id"), platform.get("offerId"), published_offer.get("offer_id"))
    sku = _first_text(platform.get("sku"), recovery.get("sku"), _result_sku(latest_result))
    published = _is_published(latest_execution, latest_result, listing_id)
    status = _cockpit_status(latest_execution=latest_execution, latest_result=latest_result, published=published)
    latest_confirmation = publish_confirmations[0] if publish_confirmations else None
    return {
        "contract_version": "2026-06-20-post-publish-cockpit-v1",
        "status": status,
        "ready_for_ui": True,
        "published": published,
        "latest_listing": {
            "listing_id": listing_id,
            "offer_id": offer_id,
            "sku": sku,
            "listing_url": _listing_url(platform, listing_id),
            "execution_status": str(latest_result.get("status") or latest_execution.get("status") if latest_execution else ""),
        },
        "latest_execution_result": _public_execution_summary(latest_execution),
        "latest_publish_confirmation": _public_confirmation_summary(latest_confirmation),
        "review_windows": [_window_with_status(window, published=published) for window in REVIEW_WINDOWS],
        "metrics_expected": [
            "impressions",
            "clicks",
            "watchers",
            "sold_units",
            "fees",
            "contribution_margin",
            "customer_service_risk",
            "refund_risk",
            "stock_risk",
        ],
        "empty_state": _empty_state(published=published, latest_execution=latest_execution),
        "cleanup_plan_boundary": {
            "status": cleanup_plan.get("status") or ("plan_only" if cleanup_operations else "waiting_for_listing"),
            "plan_only_allowed": True,
            "execution_allowed_now": False,
            "requires_confirmation_center": True,
            "confirmation_action_type": "cleanup_test_listing",
            "operations": cleanup_operations,
            "disabled_until_listing_present": not bool(listing_id or offer_id or sku),
            "reason": "下架、删除 offer、删除库存项都会改变 eBay 状态，必须先进确认中心并留下审计。",
        },
        "confirmation_boundary": {
            "real_publish_requires_confirmation_center": True,
            "cleanup_requires_confirmation_center": True,
            "price_inventory_ads_require_confirmation_center": True,
            "sensitive_support_promises_require_confirmation_center": True,
            "confirmation_gated_operations": CONFIRMATION_GATED_OPERATIONS,
        },
        "safety": {
            "triggers_real_platform_write": False,
            "triggers_ebay_oauth": False,
            "repeat_ebay_oauth_allowed": False,
            "old_frozen_account_reuse_allowed": False,
            "triggers_real_charge": False,
            "charge_now_allowed": False,
            "frontend_gets_raw_ebay_token": False,
            "frontend_gets_payment_secret": False,
            "secret_exposed": False,
        },
        "evidence_summary": {
            "execution_result_count": len(execution_results),
            "publish_execution_result_count": len(publish_executions),
            "publish_confirmation_count": len(publish_confirmations),
            "cleanup_confirmation_count": len(cleanup_confirmations),
            "audit_log_count": len(audit_logs),
            "latest_execution_id": str(latest_execution.get("execution_id") or "") if latest_execution else "",
            "latest_confirmation_id": str(latest_confirmation.get("confirmation_id") or "") if latest_confirmation else "",
        },
        "audit_evidence": _audit_evidence(
            latest_execution=latest_execution,
            publish_confirmations=publish_confirmations,
            cleanup_confirmations=cleanup_confirmations,
            audit_logs=audit_logs,
        ),
        "business_memory_policy": {
            "ordinary_chat_goes_to_long_term_memory": False,
            "workflow_confirmation_execution_report_audit_is_permanent": True,
            "source": "post_publish_cockpit_backend",
        },
        "next_actions": _next_actions(published=published, latest_execution=latest_execution, cleanup_operations=cleanup_operations),
        "paid_launch_claim_allowed": False,
        "production_ready_claim_allowed": False,
        "secret_exposed": False,
    }


def _action_type(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    result = _result(item)
    return str(item.get("action_type") or result.get("action_type") or "").strip()


def _result(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    value = item.get("result")
    return value if isinstance(value, dict) else {}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _is_published(latest_execution: dict[str, Any] | None, latest_result: dict[str, Any], listing_id: str) -> bool:
    status = str(latest_result.get("status") or latest_execution.get("status") if latest_execution else "").strip()
    return status == "published_to_ebay" or bool(listing_id)


def _cockpit_status(*, latest_execution: dict[str, Any] | None, latest_result: dict[str, Any], published: bool) -> str:
    if published:
        return "ready_with_execution_result"
    if latest_execution:
        status = str(latest_result.get("status") or latest_execution.get("status") or "")
        if "error" in status or "blocked" in status:
            return "execution_result_needs_recovery"
        return "execution_result_waiting_for_listing"
    return "dry_run_ready_no_live_listing"


def _listing_url(platform: dict[str, Any], listing_id: str) -> str:
    explicit = str(platform.get("listing_url") or platform.get("url") or "").strip()
    if explicit:
        return explicit
    return f"https://www.ebay.com/itm/{listing_id}" if listing_id else ""


def _result_sku(result: dict[str, Any]) -> str:
    audit = _dict(result.get("audit"))
    idempotency = _dict(audit.get("idempotency"))
    key = str(idempotency.get("idempotency_key") or "").strip()
    if key.lower().startswith("publish-"):
        return key.split("publish-", 1)[1]
    for step in _list(result.get("steps")):
        if not isinstance(step, dict):
            continue
        path = str(step.get("path") or "")
        marker = "/inventory_item/"
        if marker in path:
            return path.split(marker, 1)[1].split("/", 1)[0]
    return ""


def _public_execution_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    result = _result(item)
    platform = _dict(result.get("platform_result"))
    error = _latest_public_error(result)
    return {
        "execution_id": str(item.get("execution_id") or ""),
        "confirmation_id": str(item.get("confirmation_id") or ""),
        "task_id": str(item.get("task_id") or ""),
        "action_type": _action_type(item),
        "status": str(result.get("status") or item.get("status") or ""),
        "created_at": str(item.get("created_at") or result.get("executed_at") or ""),
        "platform_result": {
            "listing_id": str(platform.get("listing_id") or platform.get("listingId") or ""),
            "offer_id": str(platform.get("offer_id") or platform.get("offerId") or ""),
            "sku": str(platform.get("sku") or ""),
            "listing_url": _listing_url(platform, str(platform.get("listing_id") or platform.get("listingId") or "")),
        },
        "platform_error": error,
        "secret_exposed": False,
    }


def _latest_public_error(result: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    error = result.get("platform_error")
    if isinstance(error, dict):
        candidates.append(error)
    for step in _list(result.get("steps")):
        if isinstance(step, dict) and str(step.get("status") or "").lower().endswith("error"):
            candidates.append(step)
    if not candidates:
        return None
    error = candidates[0]
    return {
        "code": str(error.get("code") or error.get("error") or error.get("status") or "platform_error"),
        "message": str(error.get("message") or error.get("summary") or error.get("step") or "")[:240],
        "step": str(error.get("step") or ""),
        "secret_exposed": False,
    }


def _public_confirmation_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    return {
        "confirmation_id": str(item.get("confirmation_id") or ""),
        "task_id": str(item.get("task_id") or ""),
        "store_id": str(item.get("store_id") or ""),
        "action_type": str(item.get("action_type") or ""),
        "status": str(item.get("status") or ""),
        "title": str(item.get("title") or ""),
        "created_at": str(item.get("created_at") or ""),
        "decided_at": str(item.get("decided_at") or ""),
        "high_risk": bool(item.get("high_risk")),
        "secret_exposed": False,
    }


def _window_with_status(window: dict[str, Any], *, published: bool) -> dict[str, Any]:
    return {
        **window,
        "status": "pending_review" if published else "waiting_for_execution_result",
        "evidence_sources": ["execution_result", "official_ebay_packet", "confirmation_center", "audit_log"],
        "real_change_allowed_without_confirmation": False,
    }


def _empty_state(*, published: bool, latest_execution: dict[str, Any] | None) -> dict[str, Any]:
    if published:
        return {
            "show": False,
            "title": "",
            "detail": "",
            "safe_to_click_buttons": ["核对平台状态", "生成清理确认单"],
        }
    if latest_execution:
        return {
            "show": True,
            "title": "已有执行记录，但还没有可复盘的 eBay listing",
            "detail": "先核对平台状态和错误原因，不要盲目重试真实发布。",
            "disabled_real_actions": CONFIRMATION_GATED_OPERATIONS,
        }
    return {
        "show": True,
        "title": "等待真实发布结果",
        "detail": "当前只展示发布后复盘的结构和安全边界；不会创建 listing、不会 OAuth、不会收费、不会清理 eBay 状态。",
        "disabled_real_actions": CONFIRMATION_GATED_OPERATIONS,
    }


def _sanitize_cleanup_operation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": str(item.get("operation") or "cleanup"),
        "listing_id": str(item.get("listing_id") or ""),
        "offer_id": str(item.get("offer_id") or ""),
        "sku": str(item.get("sku") or ""),
        "writes_to_ebay": bool(item.get("writes_to_ebay")),
        "requires_confirmation_center": True,
        "secret_exposed": False,
    }


def _audit_evidence(
    *,
    latest_execution: dict[str, Any] | None,
    publish_confirmations: list[dict[str, Any]],
    cleanup_confirmations: list[dict[str, Any]],
    audit_logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence = [
        {
            "source": "post_publish_cockpit_backend",
            "status": "ready",
            "summary": "后端只读聚合，不触发 OAuth、收费或 eBay 写入。",
        }
    ]
    if latest_execution:
        evidence.append(
            {
                "source": "execution_results",
                "status": "present",
                "summary": f"latest execution {latest_execution.get('execution_id') or ''}",
            }
        )
    if publish_confirmations:
        evidence.append(
            {
                "source": "confirmation_center",
                "status": "present",
                "summary": f"{len(publish_confirmations)} publish confirmation(s)",
            }
        )
    if cleanup_confirmations:
        evidence.append(
            {
                "source": "cleanup_confirmation",
                "status": "present",
                "summary": f"{len(cleanup_confirmations)} cleanup confirmation(s)",
            }
        )
    if audit_logs:
        evidence.append(
            {
                "source": "audit_logs",
                "status": "present",
                "summary": f"{len(audit_logs)} recent audit record(s)",
            }
        )
    return [{**item, "secret_exposed": False} for item in evidence]


def _next_actions(
    *,
    published: bool,
    latest_execution: dict[str, Any] | None,
    cleanup_operations: list[dict[str, Any]],
) -> list[str]:
    if published and cleanup_operations:
        return [
            "按 1h/24h/7d 复盘曝光、点击、收藏、售出、费用、利润和客服风险。",
            "如需下架、删除 offer 或删除库存项，先生成清理确认单。",
            "改价、库存、广告、退款、政策和敏感客服承诺继续进确认中心。",
        ]
    if latest_execution:
        return [
            "先核对平台状态和最近执行错误，禁止盲目重试真实发布。",
            "修复发布体检红黄项后再回到确认中心。",
        ]
    return [
        "等待新 eBay 账号、全新真实测试商品素材和人工确认后再跑低风险 smoke。",
        "当前只完善驾驶舱结构，不重复旧 OAuth，不触发真实发布或收费。",
    ]
