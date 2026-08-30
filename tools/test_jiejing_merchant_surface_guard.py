#!/usr/bin/env python3
"""Static guard for merchant-facing Jiejing SaaS surfaces.

This test is intentionally narrow: internal engineering terms may remain in
backend code or hidden operator-only branches, but the public homepage and the
merchant workbench render paths must stay focused on seller value.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


PUBLIC_FORBIDDEN = [
    "Public staging",
    "Public/staging",
    "<em>Staging</em>",
    "Jiejing Runtime",
    "Runtime API",
    "Hermes",
    "商用上线前",
    "正式上线前",
    "项目完善度",
    "演示产品成熟度",
    "正式上线准备",
    "Postgres",
    "Redis",
    "Vault",
    "KMS",
]

PUBLIC_VISIBLE_FORBIDDEN = [
    "模拟",
    "演示",
    "内测",
    "测试用",
    "Demo",
    "demo",
    "Mock",
    "mock",
    "Sample",
    "sample",
    "simulated",
    "tutorial",
]

PUBLIC_HOMEPAGE_SOURCE_FORBIDDEN = [
    "上线口径",
    "真实 SaaS 上线证据",
    "后台岗位",
    "审计链路",
    "回流审计",
    "审计回传",
    "token、AI 连接凭证",
    "后端密钥边界",
    "正式版应",
    "样本数据",
    "已有开发者配置",
    "Key、OAuth 和 Sell APIs",
    "接口凭证、token",
    "官方只读授权/API",
    "连接 eBay 店铺 API",
    "eBay 店铺 API",
    "按店铺分批测试",
    "账号/API",
    "不用 API",
]

APP_MERCHANT_ONBOARDING_SOURCE_FORBIDDEN = [
    "API 可以理解",
    "API 暂时",
    "不连接财务 API",
    "货源 API",
    "API 术语",
    "应用 Key",
    "OAuth 和 Sell APIs",
    "Key、OAuth",
    "正式版会由捷境",
    "正式版应该",
    "OAuth 授权说明",
    "eBay API 能力",
    "演示版",
    "演示数据",
    "演示样本",
    "样本导入",
    "订单样本",
    "接口凭证、token",
    "审计日志",
    "可审计",
    "正式 SaaS",
]

PUBLIC_LEGAL_FILES = [
    "terms.html",
    "privacy.html",
    "refund-policy.html",
    "support.html",
    "risk-disclosure.html",
]

PUBLIC_LEGAL_VISIBLE_FORBIDDEN = [
    "受控 beta",
    "上线前演练",
    "正式商户支付",
    "正式支付",
    "正式上线前",
    "正式公开收费",
    "个人收款码",
    "个人码",
    "主理人",
    "webhook",
    "provider",
    "client secret",
    "API key",
    "Vault",
    "secret_ref",
    "WAF",
    "Bot",
    "支付机构要求",
    "商户主体",
    "主体资料",
    "主体信息",
    "public_support",
    "payment_review",
    "support_contact_pending",
    "OAuth",
    "审计证据",
    "审计记录",
    "smoke",
]


MERCHANT_SCOPE_FUNCTIONS = [
    "renderGlobalLoopWorkbench",
    "renderSaasCockpitLiveStrip",
    "renderLaunchGapBoard",
    "renderSaasMerchantTruthPanel",
    "renderSaasMerchantOperatingPath",
    "renderSaasMerchantAiValueMap",
    "renderSaasMerchantDataCoveragePanel",
    "renderSaasMerchantAiValuePanel",
    "renderSaasMerchantWorkbenchPanel",
    "renderSaasCockpitRealWorkbench",
    "renderSaasProductListingCenter",
    "applySaasReportsToActivities",
    "applySaasDataPacketsToActivities",
    "renderTaskSplitStatusBoard",
    "renderReadinessScoreBoard",
]


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def visible_text(html: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    return re.sub(r"\s+", " ", text)


def function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise ValueError(f"missing function {name}")
    next_match = re.search(r"\nfunction\s+\w+\(", source[start + len(marker) :])
    if not next_match:
        return source[start:]
    end = start + len(marker) + next_match.start()
    return source[start:end]


def source_between(source: str, start_marker: str, end_marker: str) -> str:
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise ValueError(f"missing source window: {start_marker} -> {end_marker}")
    return source[start:end]


def main() -> int:
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "app.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    public_text = visible_text(index_html)
    app_static_text = visible_text(app_html)

    for marker in PUBLIC_FORBIDDEN:
        if marker in public_text:
            return fail(f"public homepage visible text exposes internal marker: {marker}")

    for marker in PUBLIC_VISIBLE_FORBIDDEN:
        if marker in public_text:
            return fail(f"public homepage visible text still feels simulated: {marker}")
        if marker in app_static_text:
            return fail(f"merchant workbench static text still feels simulated: {marker}")

    for marker in PUBLIC_HOMEPAGE_SOURCE_FORBIDDEN:
        if marker in index_html:
            return fail(f"public homepage/onboarding source exposes internal/customer-hostile marker: {marker}")

    merchant_onboarding_source = source_between(app_js, "const wizard = [", "const manualModal =")
    for marker in APP_MERCHANT_ONBOARDING_SOURCE_FORBIDDEN:
        if marker in merchant_onboarding_source:
            return fail(f"merchant onboarding source exposes internal/customer-hostile marker: {marker}")

    for filename in PUBLIC_LEGAL_FILES:
        legal_text = visible_text((ROOT / filename).read_text(encoding="utf-8"))
        for marker in PUBLIC_LEGAL_VISIBLE_FORBIDDEN:
            if marker in legal_text:
                return fail(f"{filename} visible text exposes internal/customer-hostile marker: {marker}")

    if "捷境 JIEJING / eBay AI 经营工作台" not in public_text:
        return fail("public homepage should lead with the merchant product positioning")
    if "让 eBay 经营少一点重复，多一点自动推进" not in public_text:
        return fail("public homepage must lead with the approved AI CEO outcome")
    body_boundary = re.search(r'<body\b[^>]*\bclass\s*=\s*"[^"]*\bpublic-home-v3\b[^"]*"[^>]*>', index_html, flags=re.I)
    if not body_boundary:
        return fail("public homepage must use the approved V3 design scope")
    primary_ctas = re.findall(
        r'<button\b(?=[^>]*data-home-primary-cta="jiejing_ai_ceo_workspace_v2")[^>]*>\s*进入 AI CEO 工作台\s*</button>',
        index_html,
        flags=re.I,
    )
    if len(primary_ctas) != 1:
        return fail(f"public homepage must expose exactly one AI CEO workspace primary CTA: {len(primary_ctas)}")
    footer_boundary = re.search(r'<footer\b', index_html[body_boundary.end():], flags=re.I)
    if not footer_boundary:
        return fail("public homepage semantic marketing boundaries are missing")
    homepage_source = index_html[body_boundary.end():body_boundary.end() + footer_boundary.start()]
    filled_home_buttons = re.findall(r'<button\b[^>]*class="button"[^>]*>', homepage_source, flags=re.I)
    if len(filled_home_buttons) != 1:
        return fail(f"public homepage must keep one filled primary button: {len(filled_home_buttons)}")
    home_sections = re.findall(
        r'<(?:header|section)\b(?=[^>]*data-home-section="([^"]+)")[^>]*>',
        index_html,
        flags=re.I,
    )
    expected_home_sections = ["hero", "proof", "capabilities", "workflow", "merchants", "plans"]
    if home_sections != expected_home_sections:
        return fail(f"public homepage must expose six ordered merchant sections: {home_sections}")
    if "工作记录" in visible_text(homepage_source):
        return fail("public homepage must not market internal work records to merchants")
    public_marketing_data = "".join([
        source_between(index_html, "const pathData = {", "const planData = {"),
        source_between(index_html, "const planData = {", "const guideData = {"),
        source_between(index_html, "const guideData = {", "let guideAnswers ="),
    ])
    if "工作记录" in public_marketing_data:
        return fail("public path, plan, and guide data must not sell work records as a product label")
    for retired_defensive_copy in [
        "不代表捷境销售该商品",
        "不代表商品事实或图片权利已经核验",
    ]:
        if retired_defensive_copy in homepage_source + public_marketing_data:
            return fail(f"public index must remove the retired defensive product disclaimer: {retired_defensive_copy}")
    for marker in ["IP 防侵权", "完整体验路径", "eBay 自动化系统架构", "先把 eBay 真实经营做深，再把同一套经营能力扩展到 Amazon"]:
        if marker in homepage_source:
            return fail(f"public homepage must not expose an overclaim or internal architecture narrative: {marker}")
    for section_id in ["merchant-guide", "ai-ceo-workbench-technical", "ai-ceo-workbench"]:
        section_match = re.search(rf'<section\b[^>]*id="{re.escape(section_id)}"[^>]*>', homepage_source)
        if section_match and " hidden" not in section_match.group(0):
            return fail(f"legacy homepage section must not remain visible: {section_id}")
    proof_start = index_html.find('data-home-section="proof"')
    capability_start = index_html.find('data-home-section="capabilities"', proof_start)
    workflow_start = index_html.find('data-home-section="workflow"', capability_start)
    merchants_start = index_html.find('data-home-section="merchants"', workflow_start)
    plans_start = index_html.find('data-home-section="plans"')
    footer_match = re.search(r'<footer\b', index_html[plans_start:], flags=re.I) if plans_start >= 0 else None
    footer_start = plans_start + footer_match.start() if footer_match else -1
    if min(proof_start, capability_start, workflow_start, merchants_start, plans_start, footer_start) < 0:
        return fail("public homepage section boundaries are missing")
    proof_source = index_html[proof_start:capability_start]
    capability_source = index_html[capability_start:workflow_start]
    workflow_source = index_html[workflow_start:merchants_start]
    merchants_source = index_html[merchants_start:plans_start]
    plans_source = index_html[plans_start:footer_start]
    if len(re.findall(r'data-home-proof-metric="[^"]+"', proof_source)) != 4:
        return fail("public homepage must expose four verifiable product proof metrics")
    if len(re.findall(r'<article>', capability_source)) != 6:
        return fail("public homepage must explain the six merchant work areas")
    hero_start = index_html.find('data-home-section="hero"')
    hero_source = index_html[hero_start:proof_start]
    if hero_source.count('data-home-ai-ceo-core="merchant-goal-router-v3"') != 1:
        return fail("public homepage hero must expose one AI CEO decision core")
    hero_nodes = re.findall(r'<button\b(?=[^>]*data-home-ai-ceo-node="([^"]+)")(?=[^>]*data-home-ai-ceo-result-copy="[^"]+")(?=[^>]*aria-pressed="(?:true|false)")[^>]*>', hero_source, flags=re.I)
    approved_hero_nodes = ["market", "listing", "media", "ads", "service", "finance"]
    if hero_nodes != approved_hero_nodes:
        return fail(f"public homepage hero must expose the six approved merchant nodes: {hero_nodes}")
    hero_lines = re.findall(r'<path\b[^>]*data-home-ai-ceo-line="([^"]+)"[^>]*>', hero_source, flags=re.I)
    if hero_lines != approved_hero_nodes:
        return fail(f"public homepage hero must connect every approved merchant node to AI CEO: {hero_lines}")
    if len(re.findall(r'data-home-ai-ceo-line="[^"]+"', hero_source)) != 6:
        return fail("public homepage hero line markers must belong to exactly six SVG paths")
    if 'data-home-ai-ceo-connections="merchant-goal-router-v3"' not in hero_source:
        return fail("public homepage hero must expose the approved SVG relationship map")
    if 'data-home-ai-ceo-result="active-result"' not in hero_source:
        return fail("public homepage hero must expose merchant-facing active-node result copy")
    if 'data-home-ai-ceo-result-key=' not in hero_source:
        return fail("public homepage hero result must expose its synchronized active key")
    if 'data-home-ai-ceo-layout="classic-orbit-v1"' not in hero_source or "hero-ops-board" not in hero_source:
        return fail("public homepage hero must preserve the approved classic AI CEO orbit")
    for legacy_marker in ["home-command-steps", "home-command-step", "signalCanvas"]:
        if legacy_marker in hero_source:
            return fail(f"public homepage hero must remove legacy relationship UI: {legacy_marker}")
    if 'data-home-example="travel-compression-workflow-v1"' not in workflow_source:
        return fail("public homepage workflow example must be explicitly marked")
    if 'data-home-material-studio="listing-media-v3"' not in workflow_source:
        return fail("public homepage workflow must present the material studio product interface")
    for stage in ["input", "generation", "review", "listing"]:
        if f'data-home-material-stage="{stage}"' not in workflow_source:
            return fail(f"public homepage material studio is missing stage: {stage}")
    material_tasks = re.findall(r'data-home-material-task="([^"]+)"', workflow_source)
    if material_tasks != ["main", "scene", "selling-points", "detail"]:
        return fail(f"public homepage material studio must expose four generation directions: {material_tasks}")
    material_options = re.findall(r'data-home-material-option="([^"]+)"', workflow_source)
    if material_options != ["main", "scene", "selling-points", "detail", "video-cover"]:
        return fail(f"public homepage material studio must expose five selectable results: {material_options}")
    for marker in [
        'data-home-material-canvas="active-result"',
        'data-home-material-title="active-title"',
        'data-home-material-purpose="active-purpose"',
        'data-home-material-status="listing-draft"',
    ]:
        if marker not in workflow_source:
            return fail(f"public homepage material studio is missing review contract: {marker}")
    for marker in ["data-home-active-material=", "data-home-material-key=", "data-home-rotate-interval-ms="]:
        if marker not in workflow_source:
            return fail(f"public homepage material studio is missing synchronized state: {marker}")
    rotate_interval = re.search(r'data-home-rotate-interval-ms="(\d+)"', workflow_source)
    if not rotate_interval or not 5000 <= int(rotate_interval.group(1)) <= 7000:
        return fail("public homepage material rotation interval must stay between 5000 and 7000 ms")
    material_option_tags = re.findall(r'<button\b[^>]*data-home-material-option="[^"]+"[^>]*>', workflow_source, flags=re.I)
    if len(material_option_tags) != 5 or sum('aria-pressed="true"' in tag for tag in material_option_tags) != 1:
        return fail("public homepage material studio must expose exactly one initial selection")
    for option_tag in material_option_tags:
        for attribute in ["data-home-material-src=", "data-home-material-title-copy=", "data-home-material-purpose-copy="]:
            if attribute not in option_tag:
                return fail(f"public homepage material option is missing synchronized copy: {attribute}")
    if "一份商品资料，生成可选择的 Listing 素材。" not in visible_text(workflow_source):
        return fail("public homepage material studio must lead with the merchant outcome")
    if "流程示例｜实际结果以商家提供的商品资料与审核为准。" not in visible_text(workflow_source):
        return fail("public homepage material studio must show the approved concise boundary")
    if "示例商品工作流；实际内容以商家提供的商品事实与授权素材为准。" in visible_text(workflow_source):
        return fail("public homepage must remove the retired defensive workflow disclaimer")
    for marker in ['data-merchant-source-path="stocked"', 'data-merchant-source-path="sourcing"']:
        if marker not in merchants_source:
            return fail(f"public homepage is missing a merchant source path: {marker}")
    for marker in ['data-plan="free"', 'data-plan="single"', 'data-plan="multi"']:
        if marker not in plans_source:
            return fail(f"merchant plan card must live in the plans section: {marker}")
    for marker in [
        "桌面线缆收纳盒",
        "抽屉分隔收纳板",
        "1688 货源图",
        "IP 初筛通过",
        "侵权检测通过",
    ]:
        if marker in public_text:
            return fail(f"public homepage must not expose a fixed product or overclaim risk screening: {marker}")
    if "旅行压缩收纳袋" not in visible_text(workflow_source):
        return fail("public homepage must restore the approved travel organizer workflow example")
    if "旅行压缩收纳袋" in visible_text(index_html[:workflow_start] + index_html[merchants_start:]):
        return fail("travel organizer example must stay inside the explicitly marked public workflow section")
    if "侵权风险初筛，仍需商家核对" not in public_text:
        return fail("public homepage must explain the merchant IP risk review boundary")
    for marker in ["会自动发布商品吗？", "免费体验会自动扣费吗？", "AI 设置和账单在哪里？"]:
        if marker not in public_text:
            return fail(f"public homepage FAQ is missing a merchant question: {marker}")
    for marker in ["模型 API", "BYOK", "应用 Key", "API Base", "Vault", "Runtime"]:
        if marker in homepage_source:
            return fail(f"public homepage must keep complex configuration in settings: {marker}")
    for marker in ["有店铺", "多店铺", "免费体验", "7 天", "20 次"]:
        if marker not in public_text:
            return fail(f"public homepage should expose the simplified merchant entry: {marker}")
    for marker in ["小白起步", "已有订单处理", "登录后按四种商家身份进入向导"]:
        if marker in public_text:
            return fail(f"public homepage should not expose the retired merchant path: {marker}")

    for function_name in MERCHANT_SCOPE_FUNCTIONS:
        scope = function_scope(app_js, function_name)
        for marker in PUBLIC_FORBIDDEN:
            if marker in scope:
                return fail(f"{function_name} exposes internal marker: {marker}")
        if function_name == "renderSaasProductListingCenter":
            for marker in ["测试草稿", "倒流香炉", "Backflow Incense", "旅行压缩收纳袋"]:
                if marker in scope:
                    return fail(f"{function_name} leaks legacy listing sample into real SaaS workbench: {marker}")

    cockpit_scope = function_scope(app_js, "renderSaasCockpitRealWorkbench")
    for marker in ["倒流香炉", "Backflow Incense", "5 个候选品", "1688 货源图", "后台读取中", 'label: "packet"', "连接、数据包、模型和上线状态集中到设置页"]:
        if marker in cockpit_scope:
            return fail(f"renderSaasCockpitRealWorkbench leaks legacy cockpit sample into real SaaS workbench: {marker}")
    for marker in ["读取账号状态中", "根据 eBay 连接、店铺资料、AI 状态、报告和待确认项", 'label: "数据"', "凭证安全", "连接、店铺资料、AI 和订阅状态集中到设置页"]:
        if marker not in cockpit_scope:
            return fail(f"renderSaasCockpitRealWorkbench missing merchant-readable cockpit copy: {marker}")

    first_run_scope = function_scope(app_js, "renderSaasAiCeoFirstRunHandoff")
    for marker in ["上传第一份商品资料", "商品图片、货源链接或文字说明", "merchant_blank_workbench_v1"]:
        if marker not in first_run_scope:
            return fail(f"new merchant workbench is missing the approved blank-state behavior: {marker}")
    for marker in ["倒流香炉", "Backflow Incense", "旅行压缩收纳袋"]:
        if marker in first_run_scope:
            return fail(f"new merchant workbench must not seed a fixed product: {marker}")

    public_empty_listing_contract = f"""
const state = {{ activeListingDraft: "incense" }};
const listingDraftCatalog = [{{ id: "incense", title: "legacy fixture" }}];
function isSaasPublicMvpMode() {{ return true; }}
function isLegacySampleMediaDraftKey(value) {{ return value === "incense"; }}
{function_scope(app_js, "activeListingDraft")}
if (activeListingDraft() !== null) {{
  throw new Error("public merchant mode fell back to a seeded listing");
}}
"""
    public_empty_listing_result = subprocess.run(
        ["node", "-e", public_empty_listing_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_empty_listing_result.returncode != 0:
        return fail("public merchant mode must return an empty listing instead of a seeded fixture")

    public_empty_market_contract = f"""
const state = {{ activeCockpitMarketDraft: "incense" }};
const listingDraftCatalog = [{{ id: "incense", title: "legacy fixture" }}];
function isSaasPublicMvpMode() {{ return true; }}
function isLegacySampleMediaDraftKey(value) {{ return value === "incense"; }}
{function_scope(app_js, "activeCockpitMarketDraft")}
if (activeCockpitMarketDraft() !== null) {{
  throw new Error("public merchant mode fell back to a seeded market draft");
}}
"""
    public_empty_market_result = subprocess.run(
        ["node", "-e", public_empty_market_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_empty_market_result.returncode != 0:
        return fail("public merchant mode must return an empty market draft instead of a seeded fixture")

    public_empty_market_profile_contract = f"""
const cockpitMarketProfiles = {{ incense: {{ title: "legacy fixture" }} }};
function isSaasPublicMvpMode() {{ return true; }}
function isLegacySampleMediaDraftKey(value) {{ return value === "incense"; }}
{function_scope(app_js, "cockpitMarketProfile")}
if (cockpitMarketProfile(null) !== null) {{
  throw new Error("public merchant mode fell back to a seeded market profile");
}}
"""
    public_empty_market_profile_result = subprocess.run(
        ["node", "-e", public_empty_market_profile_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_empty_market_profile_result.returncode != 0:
        return fail("public merchant mode must return an empty market profile instead of a seeded fixture")

    public_empty_project_contract = f"""
const state = {{ activeProject: "backflow-incense" }};
const listingProjects = [{{ id: "backflow-incense", title: "legacy fixture" }}];
function isSaasPublicMvpMode() {{ return true; }}
function isLegacySampleMediaDraftKey(value) {{ return value === "backflow-incense"; }}
{function_scope(app_js, "getActiveProject")}
if (getActiveProject() !== null) {{
  throw new Error("public merchant mode fell back to a seeded project");
}}
"""
    public_empty_project_result = subprocess.run(
        ["node", "-e", public_empty_project_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_empty_project_result.returncode != 0:
        return fail("public merchant mode must return an empty project instead of a seeded fixture")

    public_empty_category_contract = f"""
const listingCategoryProfiles = {{ incense: {{ title: "legacy fixture" }} }};
function isSaasPublicMvpMode() {{ return true; }}
function isLegacySampleMediaDraftKey(value) {{ return value === "incense"; }}
{function_scope(app_js, "listingCategoryProfile")}
if (listingCategoryProfile({{ id: "incense" }}) !== null) {{
  throw new Error("public merchant mode fell back to a seeded category profile");
}}
"""
    public_empty_category_result = subprocess.run(
        ["node", "-e", public_empty_category_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_empty_category_result.returncode != 0:
        return fail("public merchant mode must return an empty category profile instead of a seeded fixture")

    public_activity_boundary_contract = f"""
let merchantPanelRenderCount = 0;
const panel = {{ innerHTML: "" }};
const anchor = {{ id: "view-activity", insertAdjacentHTML() {{}} }};
const document = {{
  querySelector(selector) {{
    if (selector === "#saasBackendPanel") return panel;
    return anchor;
  }},
}};
function isSaasPublicMvpMode() {{ return true; }}
function renderSaasMerchantWorkbenchPanel() {{ merchantPanelRenderCount += 1; return "settings panel"; }}
{function_scope(app_js, "renderSaasBackendPanel")}
renderSaasBackendPanel();
if (merchantPanelRenderCount !== 0 || panel.innerHTML) {{
  throw new Error("public activity page received a settings/backend panel");
}}
"""
    public_activity_boundary_result = subprocess.run(
        ["node", "-e", public_activity_boundary_contract],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if public_activity_boundary_result.returncode != 0:
        return fail("public merchant activity page must not receive settings/backend panels")

    executive_scope = function_scope(app_js, "renderSaasMerchantExecutiveCockpit")
    for marker in ["<b>packet</b>", "<b>source_records</b>", "<b>secret</b>", "frontend_never_gets_token"]:
        if marker in executive_scope:
            return fail(f"renderSaasMerchantExecutiveCockpit still exposes technical evidence marker: {marker}")
    for marker in ["<b>店铺资料</b>", "<b>来源记录</b>", "<b>凭证安全</b>不在浏览器显示"]:
        if marker not in executive_scope:
            return fail(f"renderSaasMerchantExecutiveCockpit missing merchant-facing evidence rail: {marker}")

    operating_path_scope = function_scope(app_js, "renderSaasMerchantOperatingPath")
    for marker in ["标准数据包", "数据包已写回工作台", "等待生成数据包", "最新数据包", "最新 packet"]:
        if marker in operating_path_scope:
            return fail(f"renderSaasMerchantOperatingPath still exposes data-packet wording: {marker}")
    for marker in ["3. 店铺资料", "从 eBay 店铺资料到 AI CEO 经营结果", "AI CEO 只读取整理后的店铺资料"]:
        if marker not in operating_path_scope:
            return fail(f"renderSaasMerchantOperatingPath missing merchant-facing store-data wording: {marker}")

    handoff_scope = function_scope(app_js, "renderSaasCeoModuleHandoffPanel")
    for marker in ["等待 packet", "官方数据包", "指令、官方数据包"]:
        if marker in handoff_scope:
            return fail(f"renderSaasCeoModuleHandoffPanel still exposes module handoff internals: {marker}")
    for marker in ["店铺资料来源", "店铺资料", "连接 eBay 或补充商品资料后继续"]:
        if marker not in handoff_scope:
            return fail(f"renderSaasCeoModuleHandoffPanel missing simple handoff wording: {marker}")

    workflow_scope = function_scope(app_js, "saasWorkflowStageRows") + function_scope(app_js, "renderSaasWorkflowCenter")
    for marker in ["配置、授权、packet", "数据包状态到设置里处理", "等待官方数据包和 AI 连接"]:
        if marker in workflow_scope:
            return fail(f"workflow surface still exposes technical data-packet wording: {marker}")
    for marker in ["配置、授权、店铺资料和模型状态统一到设置页查看", "店铺资料状态到设置里处理", "等待店铺资料和 AI 连接"]:
        if marker not in workflow_scope:
            return fail(f"workflow surface missing merchant-facing data wording: {marker}")

    listing_scope = function_scope(app_js, "renderSaasProductListingCenter")
    listing_active = listing_scope.split("${false ? `", 1)[0]
    for marker in ["官方 eBay 数据包", "官方数据包", "标准数据包", "后端标准数据包"]:
        if marker in listing_active:
            return fail(f"active Listing surface still exposes data-packet wording: {marker}")
    for marker in ["这里只显示你的账号、店铺资料和模型生成结果", "先读取 eBay 店铺资料", "Listing 工厂只接收当前账号的店铺资料"]:
        if marker not in listing_active:
            return fail(f"active Listing surface missing merchant-facing store-data wording: {marker}")

    for required_guard in [
        "function normalizeSaasProtectedView",
        "function shouldOpenSaasAppRoute",
        "function hasCompletedSaasOnboarding",
        "function markSaasOnboardingCompleted",
        "openApp(rememberSaasStartupRequestedView(params.get(\"view\") || \"cockpit\"));",
        "markSaasOnboardingCompleted();",
    ]:
        if required_guard not in app_js:
            return fail(f"real SaaS route/onboarding guard missing: {required_guard}")

    if "new MutationObserver(scheduleJiejingProductModeCopy)" in app_js:
        return fail("merchant copy must be corrected at the source instead of by a global DOM observer")

    for required in [
        "AI CEO 经营价值核对",
        "eBay 经营数据同步",
        "AI CEO 经营输出",
        "确认中心",
        "发布、付款、退款、改价或承诺买家",
        "AI CEO 只读取整理后的店铺资料",
    ]:
        if required not in app_js:
            return fail(f"merchant workbench is missing required product copy: {required}")

    account_health_scope = function_scope(app_js, "renderSaasAccountHealthTrafficPanel")
    for marker in ["等待 packet", "官方 packet", "smoke", "Runtime", "Vault", "provider", "preflight"]:
        if marker in account_health_scope:
            return fail(f"merchant account health panel exposes an owner-only engineering term: {marker}")

    print("PASS jiejing_merchant_surface_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
