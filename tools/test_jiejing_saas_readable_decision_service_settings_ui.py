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
        + function_scope(app_js, "renderSaasSettingsCleanLayout")
        + function_scope(app_js, "saasSettingsTabDefinitions")
        + function_scope(app_js, "renderSaasCoreModuleDiagnosticsPanel")
        + function_scope(app_js, "renderSaasQueueHealthPanel")
    )

    for marker in [
        "这里只看 AI CEO 已经产出的经营报告",
        "授权、来源、模型连接和发布复盘已经归到设置",
        "排查细节在设置",
        "saas-activity-simple-list",
        "没有报告时，页面保持干净空状态",
    ]:
        require(activity_scope, marker, "AI CEO report center simplified surface")

    for marker in [
        "只确认会影响钱、账号和买家的动作",
        "没有高风险动作时，这里保持安静",
        "AI 可以继续整理草稿、素材和报告",
        "发布、付款、退款、广告和客服承诺必须等你点头",
        "这里只让你决定三件事",
    ]:
        require(confirm_scope, marker, "decision center simplified surface")

    for marker in [
        "三件事：消息、订单、回复",
        "订单 / 消息",
        "回复草稿",
        "需要你确认",
        "还没有真实订单或消息",
        "退款、补偿、重发、地址修改、明确到货日和敏感承诺必须进决策中心",
        "下一步",
        "连接 eBay 店铺",
    ]:
        require(service_scope, marker, "service and orders simplified surface")

    for marker in [
        "日常卖货不用进设置",
        "账号店铺",
        "店铺数据",
        "AI 设置",
        "流程复盘",
        "权限规则",
        "上线准备",
        "什么时候需要打开设置",
        "设置首页不让商家读技术排查",
        "账号健康和事故处理",
        "来源记录和可信度",
        "Listing 和发布体检",
        "运行可靠性",
        "data-saas-settings-map-tab",
        "生产队列",
        "worker heartbeat",
        "dead_letter",
        "stale_running_count",
    ]:
        require(settings_scope, marker, "settings readable map")

    for style_marker in [
        "saas-readable-page-head",
        "saas-activity-simple-list",
        "saas-service-lane-grid",
        "saas-service-simple-workspace",
        "saas-core-module-diagnostics-grid",
        "saas-settings-simple-map",
        "saas-settings-where-to-go",
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
