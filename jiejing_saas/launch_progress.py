"""Stable, evidence-driven public launch progress for internal operators.

The denominator and point allocation are versioned and fixed. This prevents
progress from moving merely because a new checklist item was discovered or a
legacy launch gate changed shape.
"""

from __future__ import annotations

from typing import Any


FIXED_LAUNCH_PROGRESS_VERSION = "2026-07-14-fixed-public-launch-progress-v1"

FIXED_LAUNCH_CATEGORY_WEIGHTS: dict[str, int] = {
    "merchant_product": 20,
    "platform_reliability": 20,
    "payment_entitlements": 20,
    "ebay_production": 20,
    "security_compliance": 10,
    "commercial_validation": 10,
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _group_ready(groups: dict[str, dict[str, Any]], key: str) -> bool:
    return str(_dict(groups.get(key)).get("status") or "").lower() == "ready"


def _readiness_item_statuses(readiness: dict[str, Any]) -> dict[str, str]:
    items = readiness.get("items") if isinstance(readiness.get("items"), list) else []
    return {
        str(item.get("key") or ""): str(item.get("status") or "").lower()
        for item in items
        if isinstance(item, dict) and item.get("key")
    }


def _item_status(items: dict[str, str], key: str, *accepted: str) -> bool:
    return items.get(key) in {str(value).lower() for value in accepted}


def _check(
    *,
    key: str,
    label: str,
    points: int,
    passed: bool,
    executor: str,
    priority: int,
    next_action: str,
    actionable_now: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "points": points,
        "earned_points": points if passed else 0,
        "status": "ready" if passed else "pending",
        "executor": executor,
        "priority": priority,
        "next_action": next_action,
        "actionable_now": actionable_now,
    }


def _category(*, key: str, label: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    total = FIXED_LAUNCH_CATEGORY_WEIGHTS[key]
    earned = sum(int(item.get("earned_points") or 0) for item in checks)
    if sum(int(item.get("points") or 0) for item in checks) != total:
        raise ValueError(f"fixed launch category points do not match weight: {key}")
    return {
        "key": key,
        "label": label,
        "earned_points": earned,
        "total_points": total,
        "status": "ready" if earned == total else "partial" if earned else "blocked",
        "checks": checks,
    }


def build_fixed_launch_progress(
    *,
    readiness: dict[str, Any],
    launch_gate: dict[str, Any],
    billing: dict[str, Any],
    operational: dict[str, Any],
    test_data_governance: dict[str, Any],
    release_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic internal progress packet from sanitized evidence."""

    release_evidence = _dict(release_evidence)
    group_items = launch_gate.get("groups") if isinstance(launch_gate.get("groups"), list) else []
    groups = {
        str(item.get("key") or ""): item
        for item in group_items
        if isinstance(item, dict) and item.get("key")
    }
    item_statuses = _readiness_item_statuses(readiness)
    provider_status = _dict(readiness.get("provider_status"))
    evidence = _dict(readiness.get("product_evidence"))
    current_ebay_secret_ref_ready = int(evidence.get("ebay_secret_refs") or 0) > 0
    model_value = _dict(provider_status.get("model_value"))
    public_search = _dict(provider_status.get("public_search"))
    media = _dict(provider_status.get("media_generation"))
    public_billing = _dict(provider_status.get("billing"))
    domestic_payment = _dict(billing.get("domestic_payment")) or _dict(public_billing.get("domestic_payment"))
    mainland_payment_launch = _dict(billing.get("mainland_payment_launch"))
    mainland_code_capabilities = _dict(mainland_payment_launch.get("code_capabilities"))
    quota = _dict(billing.get("quota_contract"))

    configured_count = int(domestic_payment.get("configured_component_count") or 0)
    required_count = int(domestic_payment.get("required_component_count") or 0)
    payment_components_configured = required_count > 0 and configured_count >= required_count
    controlled_payment_acceptance_proven = bool(domestic_payment.get("controlled_acceptance_proven")) or (
        str(domestic_payment.get("status") or "").lower() == "controlled_acceptance_proven"
    )
    secret_boundary_intact = not bool(readiness.get("secret_exposed")) and not bool(evidence.get("secret_exposed"))
    publish_safety_ready = not bool(readiness.get("real_platform_writes_enabled")) and _item_status(
        item_statuses,
        "execution_service",
        "safe_demo_boundary",
        "ebay_draft_save_adapter_ready_disabled",
        "confirmation_gated",
        "ready",
    )
    write_boundary_intact = publish_safety_ready and secret_boundary_intact
    managed_database_queue_ready = all(
        (
            _item_status(item_statuses, "database_live_probe", "ready"),
            _item_status(item_statuses, "queue_runtime_health", "ready"),
            _item_status(item_statuses, "worker_runtime_health", "ready"),
        )
    )
    managed_secret_boundary_ready = _item_status(item_statuses, "vault", "ready") and _item_status(
        item_statuses,
        "vault_adapter_contract",
        "adapter_contract_ready",
        "ready",
    )
    backup_restore_ready = _item_status(item_statuses, "backup_restore", "ready")
    monitoring_alerting_ready = _item_status(
        item_statuses,
        "monitoring_alerting",
        "cloud_monitoring_ready",
        "ready",
    ) and str(operational.get("status") or "").lower() == "ready"
    official_ebay_read_ready = _item_status(
        item_statuses,
        "ebay_read_only_adapter",
        "official_read_completed",
        "ready",
    ) and _item_status(item_statuses, "ebay_read", "official_packet_ready", "ready")
    store_sync_visibility_ready = _item_status(
        item_statuses,
        "platform_data_packets",
        "exercised",
        "ready",
    ) and _item_status(item_statuses, "ebay_read", "official_packet_ready", "ready")
    test_data_governance_ready = (
        test_data_governance.get("contract_version") == "2026-06-20-test-data-governance"
        and test_data_governance.get("scope") == "current_company_only"
        and str(test_data_governance.get("status") or "") in {"test_data_present", "no_test_data_detected"}
    )

    categories = [
        _category(
            key="merchant_product",
            label="商家产品闭环",
            checks=[
                _check(
                    key="model_value_ready",
                    label="AI CEO 模型能力可用",
                    points=4,
                    passed=bool(model_value.get("ready_for_paid_value_claim"))
                    and bool(model_value.get("model_configured")),
                    executor="codex_internal",
                    priority=40,
                    next_action="修复模型健康证据并完成对话回归。",
                ),
                _check(
                    key="realtime_search_ready",
                    label="实时联网检索可用",
                    points=3,
                    passed=bool(public_search.get("configured"))
                    and bool(public_search.get("ai_ceo_realtime_search_enabled")),
                    executor="codex_internal",
                    priority=35,
                    next_action="恢复联网检索并验证来源记录。",
                ),
                _check(
                    key="media_generation_ready",
                    label="素材生成与审核门禁可用",
                    points=3,
                    passed=bool(media.get("configured"))
                    and bool(media.get("live_image_generation_enabled"))
                    and bool(media.get("asset_manifest_required"))
                    and bool(media.get("human_review_required_before_listing")),
                    executor="codex_internal",
                    priority=32,
                    next_action="补齐素材清单、真实性检查和人工审核门禁。",
                ),
                _check(
                    key="publish_safety_ready",
                    label="发布安全边界完整",
                    points=3,
                    passed=publish_safety_ready,
                    executor="codex_internal",
                    priority=25,
                    next_action="恢复发布前体检、确认中心和回执链路。",
                ),
                _check(
                    key="post_publish_cockpit_ready",
                    label="发布后经营回路完整",
                    points=2,
                    passed=_group_ready(groups, "post_publish_cockpit"),
                    executor="codex_internal",
                    priority=30,
                    next_action="补齐发布回执、异常和后续经营反馈。",
                ),
                _check(
                    key="real_merchant_workflow_validation",
                    label="真实商家完整路径验证",
                    points=5,
                    passed=bool(release_evidence.get("real_merchant_workflow_validation_passed")),
                    executor="joint_confirmation",
                    priority=70,
                    next_action="邀请独立商家完成多轮完整流程并记录问题。",
                ),
            ],
        ),
        _category(
            key="platform_reliability",
            label="运行可靠性",
            checks=[
                _check(
                    key="managed_database_queue_ready",
                    label="托管数据库与队列",
                    points=5,
                    passed=managed_database_queue_ready,
                    executor="codex_internal",
                    priority=15,
                    next_action="修复托管数据库或任务队列的运行证据。",
                ),
                _check(
                    key="managed_secret_boundary_ready",
                    label="后端凭证边界",
                    points=4,
                    passed=managed_secret_boundary_ready,
                    executor="codex_internal",
                    priority=12,
                    next_action="恢复后端凭证引用和脱敏边界。",
                ),
                _check(
                    key="stable_domain_tls_ready",
                    label="正式域名与 TLS",
                    points=4,
                    passed=bool(release_evidence.get("public_domain_tls_passed")),
                    executor="codex_internal",
                    priority=18,
                    next_action="修复正式域名、证书和边缘路由。",
                ),
                _check(
                    key="backup_restore_ready",
                    label="备份与恢复",
                    points=3,
                    passed=backup_restore_ready,
                    executor="codex_internal",
                    priority=22,
                    next_action="完成备份恢复演练并归档证据。",
                ),
                _check(
                    key="monitoring_alerting_ready",
                    label="监控与告警",
                    points=4,
                    passed=monitoring_alerting_ready,
                    executor="codex_internal",
                    priority=20,
                    next_action="修复生产监控、告警和运行健康证据。",
                ),
            ],
        ),
        _category(
            key="payment_entitlements",
            label="支付与额度",
            checks=[
                _check(
                    key="domestic_payment_components",
                    label="境内支付组件完整",
                    points=3,
                    passed=payment_components_configured,
                    executor="codex_internal",
                    priority=14,
                    next_action="补齐境内支付必要组件的后端配置证据。",
                ),
                _check(
                    key="signed_payment_callback",
                    label="签名回调已实现",
                    points=3,
                    passed=bool(domestic_payment.get("signed_callback_implemented"))
                    or bool(mainland_code_capabilities.get("signed_payment_callback_implemented")),
                    executor="codex_internal",
                    priority=13,
                    next_action="完成签名回调校验和幂等处理。",
                ),
                _check(
                    key="real_payment_order_adapter",
                    label="真实订单适配器已实现",
                    points=3,
                    passed=bool(domestic_payment.get("real_order_creation_implemented"))
                    or bool(mainland_code_capabilities.get("real_order_creation_implemented")),
                    executor="codex_internal",
                    priority=16,
                    next_action="完成支付订单创建、查询和状态回写。",
                ),
                _check(
                    key="controlled_payment_acceptance",
                    label="受控小额收款验证",
                    points=4,
                    passed=controlled_payment_acceptance_proven,
                    executor="joint_confirmation",
                    priority=55,
                    next_action="在人工确认边界内完成小额收款和回调证据。",
                ),
                _check(
                    key="quota_enforcement_ready",
                    label="套餐额度后端执行",
                    points=3,
                    passed=bool(quota.get("enabled")),
                    executor="codex_internal",
                    priority=17,
                    next_action="启用套餐额度、素材点数和超额阻断。",
                ),
                _check(
                    key="public_charging_owner_approval",
                    label="公开收费上线批准",
                    points=4,
                    passed=bool(launch_gate.get("paid_commercial_launch_ready"))
                    and bool(readiness.get("production_ready"))
                    and bool(domestic_payment.get("public_charging_allowed")),
                    executor="joint_confirmation",
                    priority=90,
                    next_action="技术、退款、客服和对账证据齐全后由主理人批准公开收费。",
                ),
            ],
        ),
        _category(
            key="ebay_production",
            label="eBay 正式连接",
            checks=[
                _check(
                    key="official_ebay_read_loop_ready",
                    label="eBay 官方只读链路",
                    points=4,
                    passed=official_ebay_read_ready,
                    executor="codex_internal",
                    priority=28,
                    next_action="恢复 eBay 官方只读同步和来源证据。",
                    actionable_now=current_ebay_secret_ref_ready,
                ),
                _check(
                    key="ebay_current_secret_ref",
                    label="当前可用卖家授权引用",
                    points=4,
                    passed=current_ebay_secret_ref_ready,
                    executor="founder_external",
                    priority=65,
                    next_action="待新的合规卖家账号可用后，由商家本人完成一次授权。",
                ),
                _check(
                    key="ebay_refresh_success_proof",
                    label="授权续期成功证据",
                    points=4,
                    passed=int(evidence.get("ebay_token_refresh_success_count") or 0) > 0,
                    executor="founder_external",
                    priority=68,
                    next_action="新账号授权完成后等待并记录一次真实续期成功。",
                ),
                _check(
                    key="store_sync_visibility_ready",
                    label="店铺同步状态可见",
                    points=4,
                    passed=store_sync_visibility_ready,
                    executor="codex_internal",
                    priority=29,
                    next_action="补齐店铺同步状态、错误原因和恢复入口。",
                    actionable_now=current_ebay_secret_ref_ready,
                ),
                _check(
                    key="new_ebay_account_smoke",
                    label="新账号低风险验收",
                    points=4,
                    passed=_group_ready(groups, "new_ebay_account_low_risk_smoke"),
                    executor="joint_confirmation",
                    priority=72,
                    next_action="仅在新账号稳定后执行只读和低风险验收，不触发真实发布。",
                ),
            ],
        ),
        _category(
            key="security_compliance",
            label="安全与合规",
            checks=[
                _check(
                    key="legal_risk_boundary_ready",
                    label="法律页面与风险边界",
                    points=4,
                    passed=_group_ready(groups, "legal_risk_boundary"),
                    executor="codex_internal",
                    priority=24,
                    next_action="补齐条款、隐私、退款、客服和风险披露。",
                ),
                _check(
                    key="secret_boundary_intact",
                    label="凭证未越过后端边界",
                    points=3,
                    passed=secret_boundary_intact,
                    executor="codex_internal",
                    priority=11,
                    next_action="清除凭证暴露并重新完成安全扫描。",
                ),
                _check(
                    key="high_risk_confirmation_gate",
                    label="高风险动作必须确认",
                    points=3,
                    passed=write_boundary_intact,
                    executor="codex_internal",
                    priority=10,
                    next_action="恢复真实写入的确认门禁和审计记录。",
                ),
            ],
        ),
        _category(
            key="commercial_validation",
            label="商业上线验收",
            checks=[
                _check(
                    key="browser_smoke_evidence",
                    label="多端浏览器回归",
                    points=3,
                    passed=bool(release_evidence.get("browser_smoke_passed")),
                    executor="codex_internal",
                    priority=5,
                    next_action="自动执行桌面、平板和手机端核心商家路径回归。",
                ),
                _check(
                    key="test_data_governance_ready",
                    label="测试数据治理",
                    points=2,
                    passed=test_data_governance_ready,
                    executor="codex_internal",
                    priority=26,
                    next_action="清理演示数据并标记所有测试记录。",
                ),
                _check(
                    key="final_commercial_smoke_ready",
                    label="最终商业化验收",
                    points=3,
                    passed=_group_ready(groups, "final_commercial_smoke"),
                    executor="codex_internal",
                    priority=21,
                    next_action="在所有外部条件满足后执行最终商业化回归。",
                    actionable_now=bool(readiness.get("production_ready"))
                    and bool(readiness.get("can_accept_real_customers"))
                    and int(evidence.get("ebay_token_refresh_success_count") or 0) > 0,
                ),
                _check(
                    key="commercial_owner_release_approval",
                    label="正式公开上线批准",
                    points=2,
                    passed=bool(launch_gate.get("paid_commercial_launch_ready"))
                    and bool(readiness.get("can_accept_real_customers")),
                    executor="joint_confirmation",
                    priority=95,
                    next_action="所有证据通过后由主理人确认正式公开上线。",
                ),
            ],
        ),
    ]

    earned_points = sum(int(item.get("earned_points") or 0) for item in categories)
    remaining_actions = [
        {
            "key": check["key"],
            "label": check["label"],
            "category": category["key"],
            "points": check["points"],
            "executor": check["executor"],
            "priority": check["priority"],
            "next_action": check["next_action"],
            "actionable_now": bool(check.get("actionable_now", True)),
        }
        for category in categories
        for check in category["checks"]
        if check["status"] != "ready"
    ]
    remaining_actions.sort(key=lambda item: (int(item["priority"]), str(item["key"])))
    autonomous_actions = [
        item
        for item in remaining_actions
        if item["executor"] == "codex_internal" and item.get("actionable_now") is True
    ]

    return {
        "contract_version": FIXED_LAUNCH_PROGRESS_VERSION,
        "audience": "platform_internal_admin",
        "customer_visible": False,
        "fixed_denominator": True,
        "total_points": 100,
        "earned_points": earned_points,
        "score_percent": earned_points,
        "score_can_change_only_when_evidence_changes": True,
        "public_paid_launch_allowed": bool(launch_gate.get("paid_commercial_launch_ready"))
        and bool(readiness.get("production_ready"))
        and bool(readiness.get("can_accept_real_customers")),
        "categories": categories,
        "remaining_actions": remaining_actions,
        "next_autonomous_action": autonomous_actions[0] if autonomous_actions else None,
        "safety": {
            "read_only": True,
            "triggers_real_charge": False,
            "triggers_platform_write": False,
            "triggers_oauth": False,
            "secret_exposed": False,
        },
    }
