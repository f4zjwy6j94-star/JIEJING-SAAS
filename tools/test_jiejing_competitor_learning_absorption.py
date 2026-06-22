#!/usr/bin/env python3
"""Guard that competitor learnings are absorbed as Jiejing product capabilities."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "styles.css").read_text(encoding="utf-8")

    required_markers = [
        "function renderSaasOperatingWorkbenchPanel",
        "经营执行工作台",
        "新手 7 步发布引导",
        "一人经营团队",
        "广告建议与 ACOS 模拟",
        "Amazon 经验沉淀",
        "ASIN、FBA/FBM、类目合规、广告和费用 contract",
        "真实广告、预算、库存和政策动作仍由确认中心放行",
        "ad_acos_budget_simulation",
        "amazon_contract_memory",
        "renderSaasOperatingWorkbenchPanel(ctx)",
    ]
    for marker in required_markers:
        if marker not in app_js:
            return fail(f"app.js missing learning marker: {marker}")

    required_style_markers = [
        ".saas-operating-workbench-panel",
        ".saas-operating-workbench-grid",
    ]
    for marker in required_style_markers:
        if marker not in styles:
            return fail(f"styles.css missing learning marker: {marker}")

    merchant_surface_start = app_js.find("function renderSaasOperatingWorkbenchPanel")
    merchant_surface_end = app_js.find("function saasEbaySkillPackRows")
    merchant_surface = app_js[merchant_surface_start:merchant_surface_end]
    forbidden_competitor_names = ["AccioWork", "SellAI Pro", "悟空"]
    for marker in forbidden_competitor_names:
        if marker in merchant_surface:
            return fail(f"merchant-facing absorbed panel should not mention competitor name: {marker}")

    print("PASS jiejing_competitor_learning_absorption")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
