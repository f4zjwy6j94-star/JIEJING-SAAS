#!/usr/bin/env python3
"""Static guard for the pre-test anti-blocking publish flow."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    required_app_markers = [
        "function renderSaasPreTestRunGuardPanel",
        "function saasPreTestCheckRows",
        "function runSaasPreTestFormCheck",
        "新品低风险试跑保障",
        "下一步只点这里",
        "开始一次全新商品发布测试",
        "全新品查重",
        "疑似旧测试品",
        "SKU 未重复 / 图片未命中旧图",
        "红项阻断真实发布",
        "itemId / Listing URL",
        "1 小时 / 24 小时 / 7 天",
        "继续上一步",
        "重新生成",
        "重新体检",
        "查看失败原因",
        "生成清理确认单",
        "renderSaasPreTestRunGuardPanel(ctx)",
        "function saasSevenStepLaunchItems",
        "function renderSaasSevenStepLaunchGuidePanel",
        "新手 7 步发布引导",
        "连接 eBay → 同步店铺 → 输入商品 → 生成报告 → 素材 → 发布体检 → 决策中心发布",
        "店铺名",
        "Offer / 库存",
        "官方 packet",
        "最后同步",
        "renderSaasSevenStepLaunchGuidePanel(ctx)",
        "renderSaasSevenStepLaunchGuidePanel(ctx, { compact: true })",
    ]
    for marker in required_app_markers:
        if marker not in app_js:
            return fail(f"app.js missing pre-test marker: {marker}")

    forbidden_app_markers = [
        "明天试跑保障",
    ]
    for marker in forbidden_app_markers:
        if marker in app_js:
            return fail(f"app.js still contains stale pre-test timing marker: {marker}")

    required_style_markers = [
        ".saas-pretest-run-guard",
        ".saas-pretest-run-head",
        ".saas-pretest-check-grid",
        ".saas-pretest-result-card",
        ".saas-pretest-recovery-row",
        ".saas-seven-step-guide",
        ".saas-seven-step-head",
        ".saas-seven-step-grid",
        ".saas-seven-step-next",
        "article.is-red",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing pre-test marker: {marker}")

    forbidden_new_surface = [
        "DeepSeek 负责想图",
        "FAL 负责出图",
        "调用模型的文字",
        "后端模型已返回",
    ]
    pretest_start = app_js.find("function renderSaasPreTestRunGuardPanel")
    pretest_end = app_js.find("function renderSaasPublishConfirmationIntakePanel")
    pretest_scope = app_js[pretest_start:pretest_end]
    for marker in forbidden_new_surface:
        if marker in pretest_scope:
            return fail(f"pre-test merchant UI exposes internal wording: {marker}")

    print("PASS jiejing_pretest_blocker_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
