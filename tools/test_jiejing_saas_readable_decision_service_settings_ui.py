#!/usr/bin/env python3
"""Guard the three previously confusing SaaS pages with merchant-readable copy."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
STYLES = ROOT / "styles.css"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    next_match = re.search(r"\nfunction\s+\w+\(", source[start + len(marker) :])
    if not next_match:
        return source[start:]
    end = start + len(marker) + next_match.start()
    return source[start:end]


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    activity_scope = function_scope(app_js, "renderSaasActivityCenter")
    confirm_scope = function_scope(app_js, "renderSaasConfirmPanel")
    service_scope = function_scope(app_js, "renderSaasServiceCenter")
    settings_scope = (
        function_scope(app_js, "renderSaasSettingsReadableMap")
        + function_scope(app_js, "renderSaasSettingsGeneralPanel")
        + function_scope(app_js, "renderSaasSettingsFocusPanel")
        + function_scope(app_js, "renderSaasSettingsAccountFocusPanel")
        + function_scope(app_js, "renderSaasSettingsModelFocusPanel")
        + function_scope(app_js, "renderSaasSettingsDataFocusPanel")
        + function_scope(app_js, "renderSaasSettingsGovernanceFocusPanel")
        + function_scope(app_js, "renderSaasSettingsBillingFocusPanel")
        + function_scope(app_js, "renderSaasMerchantSecurityBoundaryPanel")
        + function_scope(app_js, "saasSettingsOneGlanceRows")
        + function_scope(app_js, "renderSaasSettingsOneGlanceStrip")
        + function_scope(app_js, "renderSaasSettingsCleanLayout")
        + function_scope(app_js, "saasSettingsTabDefinitions")
        + function_scope(app_js, "renderSaasCoreModuleDiagnosticsPanel")
    )

    for marker in [
        "AI CEO 已经产出的经营报告",
        "授权、来源、模型连接和发布复盘已经归到设置",
        "汇报页保留市场结论",
        "saas-activity-simple-list",
        "没有报告时不展示旧演示记录",
    ]:
        require(activity_scope, marker, "AI CEO report center simplified surface")

    for marker in [
        "只让你处理真正要拍板的事",
        "没有重要动作时，这里保持安静",
        "AI 继续整理草稿、素材和报告",
        "发布、付款、退款、广告和客服承诺必须等你点头",
        "这里只做三种选择",
        "saas-confirm-action-model",
        "saas-confirm-card-decision",
        "saas-confirm-safety-detail",
        "你没点头前不会执行",
        "为什么停住",
    ]:
        require(confirm_scope, marker, "decision center simplified surface")

    for marker in [
        "service_order_plain_workbench_v2",
        "今日客服与订单",
        "客服、物流和售后放在一页",
        "订单与消息",
        "回复草稿",
        "确认事项",
        "当前没有待处理内容",
        "不造假",
        "没有订单就保持安静",
        "只引用已知事实",
        "承诺停住",
        "退款、补偿、重发、地址修改、明确到货日和敏感承诺进决策中心",
        "当前重点",
        "连接 eBay 店铺",
    ]:
        require(service_scope, marker, "service and orders simplified surface")

    for marker in [
        "普通商家只看 5 个入口",
        "账号与店铺",
        "店铺数据",
        "AI 与素材",
        "团队权限",
        "套餐与付款",
        "什么时候需要打开设置",
        "只显示商家需要知道的设置",
        "不展示技术排查和部署细节",
        "账号边界",
        "AI 边界",
        "数据边界",
        "权限边界",
        "隐私和安全边界",
        "data-saas-settings-map-tab",
        "凭证安全",
        "保存后不回显",
        "不造假",
        "不用旧商品旧素材冒充",
        "普通聊天不进长期经营记忆",
    ]:
        require(settings_scope, marker, "settings readable map")

    for forbidden in [
        "主理人高级区",
        "主理人上线排查",
        "生产队列",
        "worker heartbeat",
        "dead_letter",
        "stale_running_count",
    ]:
        if forbidden in settings_scope:
            raise AssertionError(f"merchant settings still contains operations-only marker: {forbidden}")

    for style_marker in [
        "saas-readable-page-head",
        "saas-activity-simple-list",
        "saas-service-lane-grid",
        "saas-service-simple-workspace",
        "saas-service-first-run-strip",
        "saas-core-module-diagnostics-grid",
        "saas-settings-simple-map",
        "saas-settings-where-to-go",
        "saas-settings-one-glance",
    ]:
        require(styles, style_marker, "readable page styling")

    for label, scope, forbidden_markers in [
        (
            "activity",
            activity_scope,
            [
                "saas-workbench-truth-panel",
                "renderSaasPostPublishCockpitPanel()",
                "renderSaasPublishFlowReviewPanel()",
                "eBay 数据包",
                "真实写入",
            ],
        ),
        (
            "decision",
            confirm_scope,
            [
                "saas-decision-guide-row",
                "renderSaasPublishCommandSummaryPanel()",
                "renderSaasPostPublishCockpitPanel()",
                "renderSaasPublishFlowReviewPanel()",
                "发布确认命令摘要",
                "核对 eBay 状态",
            ],
        ),
        (
            "service",
            service_scope,
            [
                "saas-service-status-grid",
                "saas-real-service-layout",
                "客服学习来源",
                "客服消息入口",
                "订单 packet",
            ],
        ),
    ]:
        for forbidden in forbidden_markers:
            if forbidden in scope:
                raise AssertionError(f"{label} core surface still exposes internal/status marker: {forbidden}")

    for forbidden in ["通用智能体玩具", "泛 Agent", "BYOK ready", "blocked_before_model_chat"]:
        for label, scope in [
            ("activity", activity_scope),
            ("decision", confirm_scope),
            ("service", service_scope),
            ("settings", settings_scope),
        ]:
            if forbidden in scope:
                raise AssertionError(f"{label} page still leaks stale marker: {forbidden}")

    print("JIEJING_READABLE_DECISION_SERVICE_SETTINGS_UI_OK")


if __name__ == "__main__":
    main()
