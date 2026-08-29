#!/usr/bin/env python3
"""Contract checks for the public merchant homepage maturity pass."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def main() -> None:
    assert len(re.findall(r'data-home-section="[^"]+"', INDEX)) == 6
    sections = re.findall(r'data-home-section="([^"]+)"', INDEX)
    assert sections == ["hero", "proof", "capabilities", "workflow", "merchants", "plans"]
    assert INDEX.count('data-home-primary-cta="jiejing_ai_ceo_workspace_v2"') == 1
    assert '>进入 AI CEO 工作台</button>' in INDEX
    assert re.search(r'id="heroWorkbenchLogin"[^>]*class="button"|class="button"[^>]*id="heroWorkbenchLogin"', INDEX)

    plans = re.findall(r'<button class="path-card[^"]*"[^>]*data-plan="(free|single|multi)"', INDEX)
    assert plans == ["free", "single", "multi"]

    assert "让 eBay 经营少一点重复，多一点自动推进" in INDEX
    assert 'data-home-proof-grid="jiejing_product_proof_v2"' in INDEX
    assert len(re.findall(r'data-home-proof-metric="[^"]+"', INDEX)) == 4
    assert 'data-home-example="travel-compression-workflow-v1"' in INDEX
    assert len(re.findall(r'data-home-workflow-step="[^"]+"', INDEX)) == 6
    assert "示例商品工作流；实际内容以商家提供的商品事实与授权素材为准。" in INDEX
    assert 'data-merchant-source-path="stocked"' in INDEX
    assert 'data-merchant-source-path="sourcing"' in INDEX
    assert "不会自动发布商品吗？" not in INDEX
    assert "会自动发布商品吗？" in INDEX
    assert not re.search(r"\.reveal\s*\{[^}]*opacity:\s*0\s*;", INDEX, re.S)

    for retired_id in (
        "retired-public-home-sections",
        "merchant-guide",
        "ai-ceo-workbench-technical",
        "ai-ceo-workbench",
    ):
        assert f'id="{retired_id}"' not in INDEX

    for forbidden in (
        "Packing Cubes",
        "Hermes",
        "开发完成度",
        "项目完成度",
        "IP 初筛通过",
        "高转化主图",
        "真实商家会用的工作流",
    ):
        assert forbidden not in INDEX

    print("PASS jiejing_homepage_maturity")


if __name__ == "__main__":
    main()
