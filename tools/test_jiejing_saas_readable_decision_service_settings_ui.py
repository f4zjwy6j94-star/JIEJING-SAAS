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


def assert_public_service_message_boundary(app_js: str) -> None:
    public_service = function_scope(app_js, "renderSaasServiceCenter")
    require(
        public_service,
        "连接店铺后可查看官方订单；买家消息暂未接入，当前可整理回复草稿并由你审核。",
        "honest order access and buyer-message capability boundary",
    )
    if "连接店铺后自动接收订单与买家消息" in public_service:
        raise AssertionError("connecting a store must not promise unavailable buyer-message ingestion")


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    activity_scope = (
        function_scope(app_js, "renderSaasHistoricalProjectArchive")
        + function_scope(app_js, "saasMerchantProjectWorkRecordItems")
        + function_scope(app_js, "saasMerchantWorkRecordStatusLabel")
        + function_scope(app_js, "renderSaasMerchantWorkRecordIndex")
        + function_scope(app_js, "renderSaasActivityCenter")
    )
    confirm_scope = function_scope(app_js, "renderSaasConfirmPanel")
    service_scope = function_scope(app_js, "renderSaasServiceCenter")
    service_scope = (
        function_scope(app_js, "saasServiceTraceStateLabel")
        + function_scope(app_js, "saasServiceTraceRecords")
        + function_scope(app_js, "renderSaasServiceTrace")
        + service_scope
    )
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
        "默认只显示当前项目的报告、确认和平台结果",
        "完整工作留痕",
        "merchant_project_work_record_index_v1",
        "同名商品和旧演示记录不会自动混入",
        "AI 已回复",
        "待审核",
        "受阻，等待处理",
        "saas-activity-simple-list",
        "历史项目归档",
    ]:
        require(activity_scope, marker, "AI CEO report center simplified surface")

    if "${escapeHtml(item.status)}" in activity_scope:
        raise AssertionError("AI CEO work records must not expose raw backend status codes")

    for marker in [
        "核对本次操作的对象、内容与影响",
        "批准不代表已执行",
        "对话、报告、Listing 版本和素材记录保留在对应业务页面",
        "发布、付款、退款、广告、客服承诺",
        "继续处理商品",
        "saas-confirm-action-model",
        "saas-confirm-card-decision",
        "saas-confirm-safety-detail",
        "未确认不会执行",
        "操作影响与执行条件",
    ]:
        require(confirm_scope, marker, "decision center simplified surface")

    for marker in [
        "service_order_plain_workbench_v2",
        "customer_service_trace_v1",
        "今日客服与订单",
        "依据商品资料和订单状态准备回复",
        "订单快照",
        "买家原消息",
        "AI 建议",
        "商家已修改",
        "已发送",
        "演练记录",
        "只有平台确认发送成功",
        "买家消息暂未接入",
        "确认事项",
        "尚无订单数据",
        "订单以最近一次同步为准，不代表当前待回复数量。",
        "草稿不会自动发送。",
        "发送前请核对商品事实、订单情况与承诺。",
        "退款、补偿、重发、地址修改、明确到货日和敏感承诺需单独确认。",
        "退款、补偿、重发、地址修改、明确到货日和敏感承诺会进入确认中心。",
        "下一步",
        "连接 eBay 店铺",
    ]:
        require(service_scope, marker, "service and orders simplified surface")

    if "待回复、催单、售前问题优先整理" in service_scope:
        raise AssertionError("orders must not be presented as buyer messages")

    assert_public_service_message_boundary(app_js)

    for marker in [
        "5 项设置，集中管理",
        "账号与店铺",
        "店铺数据",
        "AI 与素材",
        "团队权限",
        "套餐与付款",
        "什么时候需要打开设置",
        "在这里管理账号、店铺数据、AI、团队权限、套餐与付款",
        "商品和订单工作回到对应工作台继续",
        "账号边界",
        "AI 边界",
        "数据边界",
        "权限边界",
        "隐私和安全边界",
        "data-saas-settings-map-tab",
        "凭证安全",
        "保存后不回显",
        "资料真实性",
        "缺少的内容保持待补",
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
