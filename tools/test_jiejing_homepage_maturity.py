#!/usr/bin/env python3
"""Release contract for the approved finish-review-v12 public homepage."""
from __future__ import annotations

import ast
import hashlib
import re
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


def visible_text_blocks(source: str) -> list[str]:
    source = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", source, flags=re.S | re.I)
    source = re.sub(r"</(?:p|li|article|section|aside|header|footer|div|figure)\s*>", "\n", source, flags=re.I)
    visible = unescape(re.sub(r"<[^>]+>", " ", source))
    return [re.sub(r"\s+", " ", item).strip() for item in re.split(r"(?<=[。！？!?])|\n+", visible) if item.strip()]


def assert_future_platform_copy(source: str) -> None:
    for platform in ("TikTok", "Amazon"):
        for block in (item for item in visible_text_blocks(source) if re.search(platform, item, re.I)):
            assert "后续开放" in block, f"{platform} must be explicitly future-only: {block}"
            assert not re.search(r"已支持|现已支持|立即使用|直接发布|当前可用", block), block


def assert_homepage_browser_release_wiring(gate_source: str, apply_source: str) -> None:
    runner = "tools/codex_jiejing_homepage_maturity_browser_smoke.js"
    catalog = next(node.value for node in ast.parse(gate_source).body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "CHECKS")
    matches = [node for node in catalog.elts if isinstance(node, ast.Tuple) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "browser_homepage_maturity"]
    assert len(matches) == 1
    assert ast.literal_eval(matches[0].elts[1]) == ["node", runner]
    whitelist = re.search(r"(?ms)^FILES=\(\n(.*?)^\)", apply_source)
    assert whitelist and whitelist.group(1).splitlines().count(f'  "{runner}"') == 1
    assert apply_source.splitlines().count(f'"$NODE_BIN" --check {runner}') == 1


def assert_premium_surface_contract() -> None:
    # Preserve the existing workbench layer while isolating the new homepage.
    asset = "assets/jiejing-premium-surfaces.css"
    css = (ROOT / asset).read_text(encoding="utf-8")
    app = (ROOT / "app.html").read_text(encoding="utf-8")
    versions = re.findall(rf'href="\./{re.escape(asset)}\?v=([A-Za-z0-9._-]+)"', app)
    assert len(versions) == 1 and versions[0].endswith(hashlib.sha256(css.encode()).hexdigest()[:12])
    assert app.index(asset) < app.index('id="jiejing-cockpit-layout-guard"')
    assert not re.search(r'<link\b[^>]*href="\./assets/jiejing-premium-surfaces\.css', INDEX)
    for protected in ("app-start-requested", "app-shell-empty", "saas-ai-ceo-chatgpt-shell", "#ceoInput", "!important"):
        assert protected not in css, f"shared CSS overrides a functional guard: {protected}"


def main() -> None:
    apply_source = (ROOT / "deploy/apply-staging-patch.sh").read_text(encoding="utf-8")
    assert_homepage_browser_release_wiring((ROOT / "tools/jiejing_precloud_deployment_gate.py").read_text(encoding="utf-8"), apply_source)
    assert_future_platform_copy("<p>TikTok、Amazon 后续开放。</p>")
    for bad in ("<p>TikTok 后续开放；当前可用。</p>", "<div>Amazon 后续开放；现已支持。</div>", "<p>TikTok 当前可用。</p>", "<p>Amazon 即将开放。</p>"):
        try:
            assert_future_platform_copy(bad)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"future-platform guard accepted {bad}")

    assert re.search(r'<body\b[^>]*class="[^"]*\bworkflow-home\b', INDEX)
    assert 'data-home-version="finish-review-v12"' in INDEX
    assert re.findall(r'data-home-section="([^"]+)"', INDEX) == ["hero", "proof", "capabilities", "workflow", "merchants", "plans"]
    assert INDEX.count('data-home-primary-cta="jiejing_ai_ceo_workspace_v2"') == 1
    assert "进入 AI CEO 工作台" in INDEX
    assert re.findall(r'<button\b[^>]*data-plan="([^"]+)"', INDEX) == ["free", "single", "multi"]
    assert re.findall(r'data-workflow-module="([^"]+)"', INDEX) == ["cockpit", "product", "media", "confirm"]
    hero = INDEX[INDEX.index('data-home-section="hero"'):INDEX.index('data-home-section="proof"')]
    assert 'data-home-ai-ceo-layout="connected-map-v1"' in hero
    nodes = re.findall(r'<button\b(?=[^>]*data-home-ai-ceo-node="([^"]+)")(?=[^>]*data-home-ai-ceo-result-copy="[^"]+")(?=[^>]*aria-pressed="(?:true|false)")[^>]*>', hero)
    assert nodes == ["market", "listing", "media", "ads", "service", "finance"]
    assert re.findall(r'<path\b[^>]*data-home-ai-ceo-line="([^"]+)"', hero) == nodes
    assert "市场调研" in hero and "市场与货源" not in hero
    assert "当前支持 eBay" in hero and "关键动作执行前确认" in hero
    workflow = INDEX[INDEX.index('data-home-section="workflow"'):INDEX.index('data-home-section="merchants"')]
    steps = re.findall(r'<button\b[^>]*data-home-workflow-step="([^"]+)"', workflow)
    assert steps == ["goal", "research", "facts", "listing", "media", "confirm"]
    assert re.findall(r'data-home-workflow-panel="([^"]+)"', workflow) == steps
    assert re.findall(r'<button\b[^>]*data-studio-image="([^"]+)"', workflow) == ["collection", "suitcase", "packing", "detail"]
    for text in ("已有商品", "尚未选品", "批量铺货", "保存 eBay 未发布草稿与正式发布是不同操作", "图片使用权", "AI 生成示例", "不实时生成、不扣点"):
        assert text in workflow, f"missing merchant boundary: {text}"
    for ident in ("previewListingTitle", "previewListingDescription", "resetListingPreview", "previewListingStatus", "studioImage", "studioPrompt", "studioLoadStatus"):
        assert INDEX.count(f'id="{ident}"') == 1
    assert 'data-home-workflow-live="active-step"' in workflow and 'aria-live="polite"' in workflow
    public = INDEX[INDEX.index("<body"):INDEX.index("<footer")]
    marketing_data = INDEX[INDEX.index("const pathData = {"):INDEX.index("let guideAnswers =")]
    assert "工作记录" not in marketing_data, "onboarding and plan copy must not market internal work records"
    for forbidden in ("工作记录", "Hermes", "项目完成度", "开发完成度", "IP 初筛通过", "高转化主图", "previewNotice", "本地官网预览"):
        assert forbidden not in public
    assert_future_platform_copy(public)
    assert_future_platform_copy(marketing_data)
    assert "会未经确认直接发布吗？" in INDEX
    assert "免费体验不绑卡、不自动续费" in INDEX
    plans = INDEX[INDEX.index('data-home-section="plans"'):INDEX.index("<footer")]
    public_plan_text = " ".join(visible_text_blocks(plans))
    assert "通过 eBay API 正式发布" in public_plan_text, "public plans must describe the deployed confirmation-gated publication capability"
    for boundary in ("店铺授权", "套餐权限", "预检", "确认"):
        assert boundary in public_plan_text, f"public publication copy must retain its boundary: {boundary}"
    for closed_copy in ("eBay 公开发布暂未开放", "eBay 正式发布暂未开放"):
        assert closed_copy not in INDEX, "the broad write switch must not be mistaken for closed controlled publication"
    assert "订阅不会解除 eBay 账号限制" in public_plan_text
    assert "不会自动发送买家消息" in public_plan_text

    for ident in ("topLogin", "heroWorkbenchLogin", "publicWorkbenchEnter", "choosePlan", "nextStepModal", "nextStepEyebrow", "nextStepTitle", "nextStepBody", "entryLoginForm", "entryAuthEmail", "entryAuthPassword", "entryAuthStatus", "entryLoginSubmit", "entryRegisterSubmit", "entryModeArea", "entryModeGrid", "entryAccountPill", "toast"):
        assert INDEX.count(f'id="{ident}"') == 1, f"auth dependency missing or duplicated: {ident}"
    for behavior in ("function entrySaasApiBase", "function clearEntrySaasSessionCandidate", "async function validateEntrySaasSessionCandidate", "async function refreshEntryBrowserSession", "function openWorkbenchOrAuth", "function openRealSaasEntry", 'submitEntryAuth("login")', 'submitEntryAuth("register")', 'credentials: "include"'):
        assert behavior in INDEX, f"real authentication behavior missing: {behavior}"
    assert "entryLoggedIn = true;" in INDEX[INDEX.index("async function validateEntrySaasSessionCandidate"):INDEX.index("function appStageForPath")]

    assets = ("assets/homepage-finish.css", "assets/homepage-finish.js", "assets/homepage-media-data.js", "assets/jiejing-home-entry.css")
    for asset in assets:
        assert INDEX.count(asset) == 1 and (ROOT / asset).is_file()
        assert f'"{asset}"' in apply_source, f"asset absent from release bundle: {asset}"
    visual = (ROOT / assets[1]).read_text(encoding="utf-8")
    css = (ROOT / assets[0]).read_text(encoding="utf-8")
    assert "previewNotice" not in visual and "showNotice" not in visual
    assert not re.search(r"\b(?:fetch|XMLHttpRequest|sendBeacon)\s*\(", visual)
    assert "setInterval" not in visual, "examples must not automatically rotate"
    assert "prefers-reduced-motion" in css and "motionToggle" in INDEX
    assert "@import" not in css and "https://" not in css
    # Retain the existing light-surface/readable-copy guard with v12 tokens.
    palette = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", css))
    def luminance(color: str) -> float:
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum((v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) * w for v, w in zip(channels, (.2126, .7152, .0722)))
    assert luminance(palette["--paper"]) > .8
    for token in ("--ink", "--muted"):
        light, dark = sorted((luminance(palette["--paper"]), luminance(palette[token])), reverse=True)
        assert (light + .05) / (dark + .05) >= 4.5, f"insufficient body-copy contrast: {token}"
    assert "./assets/jiejing-" not in css, "font URLs must resolve from the assets directory"
    demo = "assets/workbench-demo/index.html"
    assert demo in INDEX and (ROOT / demo).is_file() and f'"{demo}"' in apply_source
    assert "./workbench.html" not in INDEX
    print("PASS jiejing_homepage_maturity: finish-review-v12, authentic entry, isolated demo, release wiring")


if __name__ == "__main__":
    assert_premium_surface_contract()
    main()
