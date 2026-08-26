"""Merchant-visible eBay account health and incident-mode contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any


BLOCKED_REAL_ACTIONS = [
    "publish",
    "revise_price",
    "change_inventory",
    "refund",
    "ads",
    "policy_change",
    "procurement_payment",
    "sensitive_customer_commitment",
]

ALLOWED_INCIDENT_ACTIONS = [
    "diagnostics",
    "evidence_package",
    "read_only_sync",
    "appeal_draft",
]


def build_account_health_snapshot(
    repository: Any,
    *,
    company_id: str,
    store_id: str,
) -> dict[str, Any]:
    """Build a no-secret health snapshot for a seller account.

    The snapshot is intentionally read-only and conservative: if Jiejing does
    not have a current account-health packet, incident mode is enabled before
    any real write can proceed.
    """

    store = repository.get_store_for_company(company_id=company_id, store_id=store_id) or {}
    packets = repository.list_platform_data_packets(company_id=company_id, store_id=store_id, platform="ebay", limit=1)
    latest_packet = packets[0] if packets else {}
    packet = latest_packet.get("packet") if isinstance(latest_packet.get("packet"), dict) else {}
    store_profile = _packet_section_data(packet, "store_profile")
    business_policies = _packet_section_data(packet, "account_business_policies")
    finances = _packet_section_data(packet, "finances")
    connections = repository.list_connections(company_id=company_id, store_id=store_id)
    execution_results = repository.list_execution_results(company_id=company_id, limit=80)
    latest_packet_created_at = str(latest_packet.get("created_at") or packet.get("created_at") or "")
    recent_platform_errors = _recent_platform_error_summaries(
        execution_results,
        since=latest_packet_created_at,
    )

    raw_status = _first_text(
        store_profile.get("seller_account_status"),
        store_profile.get("account_status"),
        store_profile.get("status"),
    )
    selling_status = _first_text(store_profile.get("selling_status"), raw_status)
    payout_status = _first_text(
        finances.get("payout_status"),
        finances.get("payment_status"),
        finances.get("payout_hold_status"),
        store_profile.get("payout_status"),
    )
    selling_limits = store_profile.get("selling_limits")
    restrictions = _restriction_list(
        store_profile.get("restrictions"),
        store_profile.get("restriction"),
        store_profile.get("policy_warnings"),
        store_profile.get("verification_status"),
    )

    official_packet_present = bool(packet) and (
        latest_packet.get("source_mode") == "official_api" or packet.get("source_label") == "official_api"
    )
    present_resource_keys = _packet_resource_keys(packet, "present_resource_keys")
    missing_resource_keys = _packet_resource_keys(packet, "missing_resource_keys")
    business_policies_present = _business_policies_ready(business_policies)
    business_policy_statuses = _business_policy_statuses(business_policies)
    has_store_profile = bool(store_profile)
    status = _classify_status(
        raw_status=raw_status,
        selling_status=selling_status,
        payout_status=payout_status,
        restrictions=restrictions,
        selling_limits=selling_limits,
        recent_platform_errors=recent_platform_errors,
        has_store_profile=has_store_profile,
    )
    incident_mode = status in {
        "unknown",
        "registration_incomplete",
        "restricted",
        "suspended",
        "payout_hold",
        "quota_limited",
    }
    onboarding_stage = _onboarding_stage(
        status=status,
        business_policies_present=business_policies_present,
    )
    account_health_for_publish = _publish_health_payload(
        status=status,
        raw_status=raw_status,
        selling_status=selling_status,
        payout_status=payout_status,
        restrictions=restrictions,
        latest_packet=latest_packet,
        selling_limits=selling_limits,
    )
    return {
        "contract_version": "2026-08-26-account-health-provider-rejection-v3",
        "platform": "ebay",
        "company_id": company_id,
        "store_id": store_id,
        "store_name": store.get("store_name") or store.get("name") or "",
        "marketplace": store.get("marketplace") or "EBAY_US",
        "status": status,
        "label": _merchant_status_label(status),
        "severity": _status_severity(status),
        "incident_mode": incident_mode,
        "can_execute_real_writes": not incident_mode,
        "can_enter_publish_preflight": not incident_mode and business_policies_present,
        "onboarding_stage": onboarding_stage,
        "business_policy_statuses": business_policy_statuses,
        "summary": _merchant_summary(
            status,
            has_store_profile=has_store_profile,
            business_policies_present=business_policies_present,
            recent_platform_errors=recent_platform_errors,
        ),
        "account_health": account_health_for_publish,
        "evidence_package": {
            "status_source": "latest_sanitized_ebay_packet" if latest_packet else "missing_packet",
            "packet_id": latest_packet.get("packet_id") or "",
            "packet_source_mode": latest_packet.get("source_mode") or packet.get("source_label") or "",
            "packet_created_at": latest_packet.get("created_at") or packet.get("created_at") or "",
            "official_packet_present": official_packet_present,
            "store_profile_present": has_store_profile,
            "business_policies_present": business_policies_present,
            "present_resource_keys": present_resource_keys,
            "missing_resource_keys": missing_resource_keys,
            "connection_statuses": _connection_statuses(connections),
            "seller_account_status": raw_status or "",
            "selling_status": selling_status or "",
            "payout_status": payout_status or "",
            "selling_limits": _safe_public_value(selling_limits),
            "restriction_count": len(restrictions),
            "restrictions": restrictions[:10],
            "recent_platform_errors": recent_platform_errors[:8],
            "frontend_gets_token": False,
            "runtime_gets_token": False,
            "raw_secret_stored": False,
            "secret_exposed": False,
        },
        "guardrails": {
            "missing_snapshot_blocks_real_writes": True,
            "incident_mode_blocks_real_writes": True,
            "blocked_real_actions": BLOCKED_REAL_ACTIONS,
            "allowed_incident_actions": ALLOWED_INCIDENT_ACTIONS,
            "confirmation_center_still_required_when_clear": True,
        },
        "next_actions": _next_actions(
            status,
            business_policies_present=business_policies_present,
            recent_platform_errors=recent_platform_errors,
        ),
        "secret_exposed": False,
    }


def merge_account_health_into_payload(
    payload: dict[str, Any],
    account_health_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return a publish payload with account health filled from the snapshot."""

    merged = dict(payload or {})
    existing = merged.get("account_health") if isinstance(merged.get("account_health"), dict) else {}
    snapshot_health = account_health_snapshot.get("account_health") if isinstance(account_health_snapshot.get("account_health"), dict) else {}
    if not existing and snapshot_health:
        merged["account_health"] = snapshot_health
    elif existing and snapshot_health:
        merged["account_health"] = {**snapshot_health, **existing}
    merged["account_health_snapshot"] = {
        "status": account_health_snapshot.get("status"),
        "label": account_health_snapshot.get("label"),
        "incident_mode": bool(account_health_snapshot.get("incident_mode")),
        "source_packet_id": account_health_snapshot.get("evidence_package", {}).get("packet_id"),
        "secret_exposed": False,
    }
    return merged


def account_health_readiness_item(account_health: dict[str, Any]) -> dict[str, str]:
    status = str(account_health.get("status") or "unknown")
    if status == "registration_incomplete":
        return {
            "status": "blocked_seller_registration_incomplete",
            "severity": "warning",
            "detail": "eBay authorization can be healthy while the seller account registration is still incomplete.",
            "next_action": "Complete seller registration in eBay Seller Hub; do not repeat OAuth. Then refresh the official read-only packet.",
        }
    if status == "normal":
        return {
            "status": "account_health_clear",
            "severity": "info",
            "detail": "Latest eBay account health snapshot is clear enough for publish preflight.",
            "next_action": "Keep publish, price, inventory, refund, ads and policy changes confirmation-gated.",
        }
    if status == "attention":
        return {
            "status": "account_health_attention",
            "severity": "warning",
            "detail": "Account health has attention signals; real writes remain confirmation-gated and should be reviewed.",
            "next_action": "Review selling limits, policy warnings and recent platform errors before publishing.",
        }
    return {
        "status": f"blocked_account_health_{status}",
        "severity": "warning",
        "detail": "Account health is unknown or abnormal; incident mode must stop real platform writes.",
        "next_action": "Run read-only sync and generate an account evidence package before any publish or other real write.",
    }


def _classify_status(
    *,
    raw_status: str,
    selling_status: str,
    payout_status: str,
    restrictions: list[str],
    selling_limits: Any,
    recent_platform_errors: list[dict[str, Any]],
    has_store_profile: bool,
) -> str:
    text = " ".join(
        [
            raw_status,
            selling_status,
            payout_status,
            " ".join(restrictions),
            str(_safe_public_value(selling_limits)),
            " ".join(
                " ".join(
                    str(value or "")
                    for value in (item.get("error_id"), item.get("code"), item.get("message"))
                )
                for item in recent_platform_errors
            ),
        ]
    ).strip().lower().replace("_", " ")
    if not has_store_profile:
        return "unknown"
    if any(marker in text for marker in ("registration incomplete", "registration_incomplete")):
        return "registration_incomplete"
    if any(marker in text for marker in ("suspended", "suspend", "frozen", "freeze", "closed", "disabled", "account freeze")):
        return "suspended"
    if any(marker in text for marker in ("payout hold", "payment hold", "funds on hold", "hold funds", "held payout")):
        return "payout_hold"
    if any(marker in text for marker in ("seller listing limit", "monthly listing amount", "limit exceeded", "exceed selling limit", "0 remaining")):
        return "quota_limited"
    if any(
        marker in text
        for marker in (
            "restricted",
            "restriction",
            "limited",
            "below standard",
            "unverified",
            "policy violation",
            "verification required",
            "25019",
        )
    ):
        return "restricted"
    if any(marker in text for marker in ("warning", "near limit", "below average", "case open", "appeal")):
        return "attention"
    return "normal"


def _publish_health_payload(
    *,
    status: str,
    raw_status: str,
    selling_status: str,
    payout_status: str,
    restrictions: list[str],
    latest_packet: dict[str, Any],
    selling_limits: Any,
) -> dict[str, Any]:
    if status == "normal":
        public_status = "clear"
    elif status == "attention":
        public_status = "review_required"
    else:
        public_status = status or "unknown"
    return {
        "status": public_status,
        "seller_account_status": raw_status or public_status,
        "selling_status": selling_status or ("active" if status == "normal" else public_status),
        "payout_status": payout_status or ("available" if status in {"normal", "attention"} else public_status),
        "restrictions": restrictions[:10],
        "selling_limits": _safe_public_value(selling_limits),
        "source_packet_id": latest_packet.get("packet_id") or "",
        "source": "sanitized_ebay_packet",
        "secret_exposed": False,
    }


def _packet_section_data(packet: dict[str, Any], key: str) -> dict[str, Any]:
    for section in _packet_sections(packet):
        if not isinstance(section, dict):
            continue
        if section.get("key") == key or section.get("resource") == key:
            data = section.get("data")
            return data if isinstance(data, dict) else {}
    return {}


def _packet_sections(packet: dict[str, Any]) -> list[Any]:
    if isinstance(packet.get("sections"), list):
        return list(packet.get("sections") or [])
    if isinstance(packet.get("resources"), list):
        return list(packet.get("resources") or [])
    return []


def _packet_resource_keys(packet: dict[str, Any], key: str) -> list[str]:
    values = packet.get(key)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()][:20]


def _business_policies_ready(policies: dict[str, Any]) -> bool:
    return all(_business_policy_statuses(policies).values())


def _business_policy_statuses(policies: dict[str, Any]) -> dict[str, bool]:
    """Expose presence only; policy identifiers remain backend evidence."""

    return {
        "payment": bool(str(policies.get("payment_policy_id") or "").strip()),
        "fulfillment": bool(str(policies.get("fulfillment_policy_id") or "").strip()),
        "return": bool(str(policies.get("return_policy_id") or "").strip()),
    }


def _recent_platform_error_summaries(
    execution_results: list[dict[str, Any]],
    *,
    since: str = "",
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for record in execution_results:
        created_at = str(record.get("created_at") or "")
        if since and created_at and not _is_after(created_at, since):
            continue
        result = record.get("result") if isinstance(record.get("result"), dict) else {}
        for error in _walk_platform_errors(result):
            error_id = str(error.get("error_id") or error.get("errorId") or "").strip()
            code = str(error.get("code") or error_id or error.get("category") or "").strip()
            message = str(error.get("message") or error.get("longMessage") or error.get("detail") or "").strip()
            if not error_id and not code and not message:
                continue
            summaries.append(
                {
                    "action_type": record.get("action_type") or result.get("action_type") or "",
                    "status": record.get("status") or result.get("status") or "",
                    "error_id": error_id[:80],
                    "code": code[:80],
                    "message": message[:240],
                    "created_at": created_at,
                }
            )
            break
    return summaries


def _is_after(candidate: str, baseline: str) -> bool:
    """Keep an execution incident only until a newer official packet supersedes it."""

    try:
        candidate_at = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        baseline_at = datetime.fromisoformat(baseline.replace("Z", "+00:00"))
        return candidate_at > baseline_at
    except (TypeError, ValueError):
        return True


def _walk_platform_errors(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("platform_error"), dict):
            found.append(value["platform_error"])
        if isinstance(value.get("error"), dict):
            found.append(value["error"])
        for key in ("errors", "warnings"):
            items = value.get(key)
            if isinstance(items, list):
                found.extend(item for item in items if isinstance(item, dict))
        for item in value.values():
            found.extend(_walk_platform_errors(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_platform_errors(item))
    return found[:20]


def _restriction_list(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            out.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, dict):
            out.extend(f"{key}:{item}" for key, item in value.items() if str(item).strip())
        elif str(value or "").strip():
            out.append(str(value).strip())
    return out


def _connection_statuses(connections: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "connection_id": str(item.get("connection_id") or ""),
            "status": str(item.get("status") or ""),
            "connection_type": str(item.get("connection_type") or ""),
        }
        for item in connections[:10]
        if isinstance(item, dict)
    ]


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe_public_value(item)
            for key, item in value.items()
            if not _secretish(key) and item not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [_safe_public_value(item) for item in value[:20]]
    return value


def _secretish(key: Any) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in ("token", "secret", "password", "authorization", "cookie", "refresh"))


def _merchant_status_label(status: str) -> str:
    return {
        "normal": "账号正常",
        "attention": "需要关注",
        "registration_incomplete": "卖家注册未完成",
        "restricted": "账号受限",
        "suspended": "账号冻结",
        "payout_hold": "付款冻结",
        "quota_limited": "额度不足",
        "unknown": "状态未知",
    }.get(status, "状态未知")


def _status_severity(status: str) -> str:
    if status == "normal":
        return "green"
    if status == "attention":
        return "amber"
    return "red"


def _merchant_summary(
    status: str,
    *,
    has_store_profile: bool,
    business_policies_present: bool,
    recent_platform_errors: list[dict[str, Any]] | None = None,
) -> str:
    if status == "registration_incomplete":
        return "eBay 授权和安全凭证可以正常，但卖家注册尚未完成；无需重新授权，先在 eBay 完成身份、地址和收款验证。"
    if status == "normal":
        if not business_policies_present:
            return "卖家账号已完成注册，但官方数据包还没有付款、配送和退货政策；先在 Seller Hub 启用 Business Policies。"
        return "最新账号健康快照未发现冻结、受限、付款冻结或额度阻断；真实动作仍必须经过决策中心。"
    if status == "attention":
        return "账号存在需要关注的信号；发布前必须复核额度、政策警告和近期平台错误。"
    if not has_store_profile:
        return "当前没有可追溯的 eBay 账号健康快照；上线前默认进入事故模式，阻止真实写入。"
    if status == "restricted" and _has_ebay_verification_restriction(recent_platform_errors or []):
        return "eBay 拒绝了最近一次正式发布并暂时限制账号；Offer 仍未公开，捷境已暂停后续真实写入。"
    return "账号存在冻结、受限、付款冻结或额度风险；系统进入事故模式，只允许诊断、证据包和只读同步。"


def _next_actions(
    status: str,
    *,
    business_policies_present: bool,
    recent_platform_errors: list[dict[str, Any]] | None = None,
) -> list[str]:
    if status == "registration_incomplete":
        return [
            "在 eBay 官方页面完成 eBay 卖家注册，包括身份、注册地址和收款验证；无需重新授权。",
            "完成后回到 Seller Hub，确认卖家功能可用；捷境只刷新官方只读数据，不重复 OAuth。",
            "若账号恢复后仍缺政策，再在 Seller Hub 启用 Business Policies，并建立付款、配送和退货政策。",
        ]
    if status == "normal":
        if not business_policies_present:
            return [
                "在 Seller Hub 启用 Business Policies，并建立付款、配送和退货政策。",
                "完成后刷新官方只读数据即可，无需重新授权；真实动作仍进入决策中心。",
            ]
        return [
            "继续发布体检：类目、item specifics、图片、VeRO/IP、GPSR、政策、费用和利润。",
            "真实发布、改价、库存、退款、广告和政策动作仍进入决策中心。",
        ]
    if status == "attention":
        return [
            "复核 seller limits、policy warnings、业务政策和最近 eBay 拒绝记录。",
            "降低测试发布价格/数量，必要时先跑只读同步和证据包。",
        ]
    if status == "restricted" and _has_ebay_verification_restriction(recent_platform_errors or []):
        return [
            "在 eBay 站内信打开官方核验通知，并按要求提交一份有效且未修改的证明文件，完成资料核验；无需重新授权。",
            "等待 eBay 解除限制后回到捷境刷新账号状态；旧 Offer、Listing 草稿和素材无需重建。",
            "账号恢复后重新生成正式发布确认单，并再次获得动作时确认后再提交一次。",
        ]
    return [
        "暂停真实发布、改价、库存、退款、广告、政策和敏感客服承诺。",
        "运行只读同步并导出账号证据包，区分 eBay 原因、人工操作和捷境动作。",
        "账号恢复或换新账号后，再重新同步 packet 并跑发布体检。",
    ]


def _has_ebay_verification_restriction(errors: list[dict[str, Any]]) -> bool:
    return any(str(item.get("error_id") or "").strip() == "25019" for item in errors if isinstance(item, dict))


def _onboarding_stage(*, status: str, business_policies_present: bool) -> str:
    if status == "registration_incomplete":
        return "seller_registration_required"
    if status in {"unknown", "restricted", "suspended", "payout_hold", "quota_limited"}:
        return "account_review_required"
    if not business_policies_present:
        return "business_policies_required"
    return "ready_for_publish_preflight"
