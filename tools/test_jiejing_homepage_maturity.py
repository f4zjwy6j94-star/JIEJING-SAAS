#!/usr/bin/env python3
"""Contract checks for the public merchant homepage V3 maturity pass."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def main() -> None:
    body_match = re.search(r'<body\b[^>]*\bclass\s*=\s*"[^"]*\bpublic-home-v3\b[^"]*"[^>]*>', INDEX, re.I)
    assert body_match
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

    hero_start = re.search(r'<(?:header|section)\b(?=[^>]*data-home-section="hero")[^>]*>', INDEX, re.I).start()
    proof_start = re.search(r'<section\b(?=[^>]*data-home-section="proof")[^>]*>', INDEX[hero_start:], re.I).start() + hero_start
    hero_source = INDEX[hero_start:proof_start]
    assert hero_source.count('data-home-ai-ceo-core="merchant-goal-router-v3"') == 1
    hero_nodes = re.findall(
        r'<button\b(?=[^>]*data-home-ai-ceo-node="([^"]+)")(?=[^>]*data-home-ai-ceo-result-copy="[^"]+")(?=[^>]*aria-pressed="(?:true|false)")[^>]*>',
        hero_source,
        re.I,
    )
    assert hero_nodes == ["market", "listing", "media", "ads", "service", "finance"]
    hero_node_tags = re.findall(r'<button\b[^>]*data-home-ai-ceo-node="[^"]+"[^>]*>', hero_source, re.I)
    assert len(hero_node_tags) == 6
    assert sum('aria-pressed="true"' in tag for tag in hero_node_tags) == 1
    for label in ("市场与货源", "Listing 草稿", "素材工坊", "广告费用", "客服物流", "财务风控"):
        assert label in hero_source
    assert re.search(r'<svg\b[^>]*data-home-ai-ceo-connections="merchant-goal-router-v3"', hero_source, re.I)
    hero_lines = re.findall(
        r'<path\b[^>]*data-home-ai-ceo-line="([^"]+)"[^>]*>',
        hero_source,
        re.I,
    )
    assert hero_lines == hero_nodes
    assert len(re.findall(r'data-home-ai-ceo-line="[^"]+"', hero_source)) == 6
    assert 'data-home-ai-ceo-result="active-result"' in hero_source
    assert 'data-home-ai-ceo-result-key=' in hero_source
    assert 'data-home-ai-ceo-layout="classic-orbit-v1"' in hero_source
    assert "hero-ops-board" in hero_source
    for legacy_marker in ("home-command-steps", "home-command-step", "signalCanvas"):
        assert legacy_marker not in hero_source

    assert '--home-space: clamp(72px, 7vw, 104px);' in INDEX
    assert '--home-space: clamp(56px, 7vw, 72px);' in INDEX
    assert "clearEntrySaasSessionCandidate" in INDEX
    assert "validateEntrySaasSessionCandidate" in INDEX
    assert "entryLoggedIn = true;" in INDEX[INDEX.index("async function validateEntrySaasSessionCandidate"):INDEX.index("function appStageForPath")]

    footer_match = re.search(r'<footer\b', INDEX[body_match.end():], re.I)
    assert footer_match
    homepage_source = INDEX[body_match.end():body_match.end() + footer_match.start()]
    assert "工作记录" not in homepage_source
    path_data_source = INDEX[INDEX.index("const pathData = {"):INDEX.index("const planData = {")]
    plan_data_source = INDEX[INDEX.index("const planData = {"):INDEX.index("const guideData = {")]
    guide_data_source = INDEX[INDEX.index("const guideData = {"):INDEX.index("let guideAnswers =")]
    public_marketing_source = homepage_source + path_data_source + plan_data_source + guide_data_source
    assert "工作记录" not in public_marketing_source

    assert 'data-home-example="travel-compression-workflow-v1"' in INDEX
    workflow_start = re.search(r'<section\b(?=[^>]*data-home-section="workflow")[^>]*>', INDEX, re.I).start()
    merchants_start = re.search(r'<section\b(?=[^>]*data-home-section="merchants")[^>]*>', INDEX[workflow_start:], re.I).start() + workflow_start
    workflow_source = INDEX[workflow_start:merchants_start]
    assert 'data-home-material-studio="listing-media-v3"' in workflow_source
    for stage in ("input", "generation", "review", "listing"):
        assert f'data-home-material-stage="{stage}"' in workflow_source
    tasks = re.findall(r'data-home-material-task="([^"]+)"', workflow_source)
    assert tasks == ["main", "scene", "selling-points", "detail"]
    material_options = re.findall(
        r'<button\b(?=[^>]*data-home-material-option="([^"]+)")(?=[^>]*aria-pressed="(?:true|false)")[^>]*>',
        workflow_source,
        re.I,
    )
    assert material_options == ["main", "scene", "selling-points", "detail", "video-cover"]
    material_option_tags = re.findall(r'<button\b[^>]*data-home-material-option="[^"]+"[^>]*>', workflow_source, re.I)
    assert all(
        all(attribute in tag for attribute in (
            "data-home-material-src=",
            "data-home-material-title-copy=",
            "data-home-material-purpose-copy=",
        ))
        for tag in material_option_tags
    )
    assert sum('aria-pressed="true"' in tag for tag in material_option_tags) == 1
    active_key_match = re.search(r'data-home-active-material="([^"]+)"', workflow_source)
    assert active_key_match
    active_key = active_key_match.group(1)
    selected_tag = next(tag for tag in material_option_tags if 'aria-pressed="true"' in tag)
    assert f'data-home-material-option="{active_key}"' in selected_tag
    for marker in (
        'data-home-material-canvas="active-result"',
        'data-home-material-title="active-title"',
        'data-home-material-purpose="active-purpose"',
        'data-home-material-status="listing-draft"',
        'data-home-auto-rotate="true"',
        'data-home-motion-policy="respect-reduced-motion"',
    ):
        assert marker in workflow_source
    rotate_interval = re.search(r'data-home-rotate-interval-ms="(\d+)"', workflow_source)
    assert rotate_interval and 5000 <= int(rotate_interval.group(1)) <= 7000
    for active_marker in ("active-result", "active-title", "active-purpose", "listing-draft"):
        tag = re.search(
            rf'<[^>]+(?=[^>]*data-home-material-(?:canvas|title|purpose|status)="{active_marker}")(?=[^>]*data-home-material-key="{re.escape(active_key)}")[^>]*>',
            workflow_source,
            re.I,
        )
        assert tag
    approved_assets = {
        "assets/travel-compression-main-v2.webp",
        "assets/travel-compression-scene-v2.webp",
        "assets/travel-compression-feature-v2.webp",
        "assets/travel-compression-detail-v2.webp",
        "assets/travel-compression-video-cover.webp",
    }
    referenced_assets = set(re.findall(r'(?:\./)?(assets/travel-compression-[^"\s]+\.webp)', workflow_source))
    assert referenced_assets == approved_assets
    assert "setupHomepageMediaStudio" in INDEX
    assert "一份商品资料，生成可选择的 Listing 素材。" in workflow_source
    assert "流程示例｜实际结果以商家提供的商品资料与审核为准。" in workflow_source
    assert "示例商品工作流；实际内容以商家提供的商品事实与授权素材为准。" not in public_marketing_source
    assert "不代表捷境销售该商品" not in public_marketing_source
    assert "不代表商品事实或图片权利已经核验" not in public_marketing_source
    assert re.search(r'@media\s*\(prefers-reduced-motion:\s*reduce\)', INDEX)
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
