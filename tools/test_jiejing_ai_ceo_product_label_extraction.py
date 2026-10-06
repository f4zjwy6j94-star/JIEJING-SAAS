#!/usr/bin/env python3
"""Guard AI CEO product handoffs against generic prompt fragments."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    end = source.find("\nfunction ", start + len(marker))
    return source[start : end if end > start else len(source)]


def require(body: str, marker: str, label: str) -> None:
    if marker not in body:
        raise AssertionError(f"missing {label}: {marker}")


def reject(body: str, marker: str, label: str) -> None:
    if marker in body:
        raise AssertionError(f"forbidden {label}: {marker}")


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    invalid_label = function_body(app_js, "saasIsInvalidMarketProductLabel")
    for marker in ["产品名", "商品名", "两条理由", "名和两条理由"]:
        require(invalid_label, marker, "generic prompt-fragment product guard")
    invalid_label_probe = subprocess.run(
        ["node"], input="const publicRuntimeText = (value) => String(value || '');\n" + invalid_label
        + "\nconsole.log(JSON.stringify(['证据边界说明','来源与限制','sources and limitations','stainless steel measuring cups set']"
        + ".map(saasIsInvalidMarketProductLabel)));\n", text=True, encoding="utf-8", capture_output=True, check=True,
    )
    assert json.loads(invalid_label_probe.stdout.strip()) == [True, True, True, False], invalid_label_probe.stdout

    # Actual persisted bad report: metadata headings were projected into cards.
    # Keep legitimate supplier-incomplete drafts available while rejecting these.
    labels = ["未验证项汇总", "供应商资料清单（待补）", "边界说明", "supplier information checklist",
              "量勺量杯套装 vs 硅胶锅铲 vs 不锈钢咖啡勺", "cups versus spoons",
              "stainless steel measuring cups set", "边界测量仪"]
    blocked_draft_probe = subprocess.run(["node"], input=(
        "const publicRuntimeText = (value) => String(value || '');\n" + invalid_label + "\n"
        + function_body(app_js, "saasIsConcreteProductLabel") + "\n"
        + "const saasAiCeoListingHandoffFieldsFromReport = r => r.report.listing_handoff.listing_fields;\n"
        + "const saasSelectedMarketProductCandidate = c => c.find(x => x.selected);\n"
        + function_body(app_js, "saasAiCeoMarketReportCanStartBlockedListingDraft") + "\n"
        + "console.log(JSON.stringify(" + json.dumps(labels, ensure_ascii=False) + ".map(name => {"
        + "const candidate = {name, selected:true}; return saasAiCeoMarketReportCanStartBlockedListingDraft({"
        + "report_type:'ai_ceo.market_research',report:{listing_import_ready:false, answer_quality:{accepted:true},"
        + "blocked_by:['supplier_facts_incomplete'],listing_handoff:{listing_fields:{"
        + "product_candidates:[candidate],selected_product_candidate:candidate}}}}); })));\n"
    ), text=True, encoding="utf-8", capture_output=True, check=True)
    assert json.loads(blocked_draft_probe.stdout.strip()) == [False, False, False, False, False, False, True, True], blocked_draft_probe.stdout
    # Do not silently switch to another candidate when the saved selection is
    # invalid and normalization has discarded it from the visible candidate list.
    fallback_probe = subprocess.run(["node"], input=(
        "const publicRuntimeText = value => String(value || '');\n" + invalid_label + "\n"
        + function_body(app_js, "saasIsConcreteProductLabel") + "\n"
        + "const valid = {name:'不锈钢量勺量杯套装',selected:true};\n"
        + "const saasAiCeoListingHandoffFieldsFromReport = () => ({product_candidates:[valid],selected_product_candidate:valid});\n"
        + "const saasSelectedMarketProductCandidate = c => c[0];\n"
        + function_body(app_js, "saasAiCeoMarketReportCanStartBlockedListingDraft") + "\n"
        + "console.log(saasAiCeoMarketReportCanStartBlockedListingDraft({report_type:'ai_ceo.market_research',report:{"
        + "answer_quality:{accepted:true},selected_product_candidate:{name:'量勺量杯套装 vs 硅胶锅铲 vs 不锈钢咖啡勺'}}}));\n"
    ), text=True, encoding="utf-8", capture_output=True, check=True)
    assert fallback_probe.stdout.strip() == "false", fallback_probe.stdout

    concise_label = function_body(app_js, "saasAiCeoConciseAnswerProductLabel")
    for marker in ["assistant_text", "lines[0]", "理由", "saasIsConcreteProductLabel"]:
        require(concise_label, marker, "concise model answer product extraction")

    market_label = function_body(app_js, "saasAiCeoMarketProductLabel")
    require(market_label, "saasAiCeoConciseAnswerProductLabel(latest)", "answer-first product extraction")
    require(market_label, "(?:是|为|:|：)", "explicit merchant product delimiter")
    reject(market_label, "[:：]?\\s*([^\\n。；;]{2,80})", "optional product delimiter")

    concrete_label = function_body(app_js, "saasIsConcreteProductLabel")
    require(concrete_label, "saasIsInvalidMarketProductLabel(text)", "shared product-label validation")

    candidate_parser = function_body(app_js, "saasNormalizeMarketProductCandidates")
    require(candidate_parser, "候选商品|候选品|候选", "numbered candidate-card extraction")
    require(candidate_parser, "saasSelectMarketProductCandidateFromText", "explicit recommendation selection")

    intent_router = function_body(app_js, "saasCeoCommandIntent")
    risk_router = function_body(app_js, "isSaasCeoHighRiskCommand")
    require(intent_router, "asksForListingHandoff", "Listing handoff priority")
    require(intent_router, "listingDeferred", "negative Listing intent guard")
    require(intent_router, "asksForProductResearch", "AI CEO product-research route")
    require(intent_router, "if (asksForProductResearch)", "product research before generic Listing routing")
    require(intent_router, "asksForBulkWorkspace", "explicit bulk-workspace routing")
    require(intent_router, "批量筛", "natural bulk screening phrase")
    require(intent_router, "if (asksForListingHandoff)", "Listing routing before generic selection words")
    intent_probe = subprocess.run(
        ["node"],
        input=(
            risk_router
            + "\n"
            + intent_router
            + "\nconsole.log(JSON.stringify(["
            + "saasCeoCommandIntent('筛选3个全新低风险候选，只读，先不要 Listing 草稿'),"
            + "saasCeoCommandIntent('为这个商品生成 Listing 草稿'),"
            + "saasCeoCommandIntent('批量筛选20个商品'),"
            + "saasCeoCommandIntent('继续 report_5eaf36a405de7331，只补 eBay US Sold & Completed 成交证据并做三选一；不能复用品牌或图片，不生成 Listing、不生图、不写 eBay。')"
            + ",saasCeoCommandIntent('继续候选商品的真实供应商事实核验；实时库存和最终报价未确认。本轮不采购、不付款、不建 Listing、不生图、不写 eBay。')"
            + ",saasCeoCommandIntent('现在只创建捷境内部的、被事实阻断的 Listing 草稿；不采购、不付款、不生图、不保存 eBay 草稿、不公开发布。')"
            + ",saasCeoCommandIntent('本轮不做候选级联网调研，只根据已有商品资料生成 Listing 草稿。')"
            + "]));\n"
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert json.loads(intent_probe.stdout.strip()) == ["research", "listing", "bulk", "research", "research", "listing", "listing"], intent_probe.stdout

    candidate_research = (
        "继续当前商品项目，不新建项目。本轮只做候选级联网调研，请分别用 "
        "stainless steel measuring spoons cups set、silicone kitchen spatula、stainless steel coffee teaspoons "
        "搜索 eBay 美国站的具体商品页面。每个候选给出商品标题、链接、美元标价、套装件数和检索日期。"
        "根据实际证据比较并推荐一个暂定找货方向。不创建 Listing，不生图、不采购、不发布。"
    )
    research_messages = [candidate_research] + [
        "只核对当前候选的商品页面和价格，" + boundary + "。"
        for boundary in ("不创建 Listing", "不生成 Listing", "不需要生成 Listing", "无须创建 Listing",
                         "不必创建 Listing", "不允许生成 Listing 草稿", "先不要重新生成 Listing")
    ]
    research_probe = subprocess.run(
        ["node"], input=risk_router + "\n" + intent_router
        + "\nconsole.log(JSON.stringify(" + json.dumps(research_messages, ensure_ascii=False)
        + ".map(saasCeoCommandIntent)));\n", text=True, encoding="utf-8", capture_output=True, check=True,
    )
    assert json.loads(research_probe.stdout.strip()) == ["research"] * len(research_messages), research_probe.stdout

    risk_probe = subprocess.run(
        ["node"],
        input=(
            risk_router
            + "\nconsole.log(JSON.stringify(["
            + "isSaasCeoHighRiskCommand('本轮不采购、不付款、不发布，只做供应商事实核验'),"
            + "isSaasCeoHighRiskCommand('现在付款采购并发布'),"
            + "isSaasCeoHighRiskCommand('不要停，直接发布')"
            + "]));\n"
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert json.loads(risk_probe.stdout.strip()) == [False, True, True], risk_probe.stdout

    command_sanitizer = function_body(app_js, "sanitizeSaasCeoCommandSourceText")
    sanitizer_probe = subprocess.run(
        ["node"],
        input=(
            "const publicRuntimeText = (value) => String(value || '');\n"
            + command_sanitizer
            + "\nconsole.log(sanitizeSaasCeoCommandSourceText('x'.repeat(850)).length);\n"
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert int(sanitizer_probe.stdout.strip()) == 850, sanitizer_probe.stdout

    command_builder = function_body(app_js, "buildSaasCeoCommand")
    require(command_builder, "research:", "research route contract")
    require(command_builder, 'label: "AI CEO 选品调研"', "research route merchant label")
    # The semantic protocol must retain the complete instruction, especially a
    # trailing prohibition. Over-limit input is rejected rather than truncated.
    length_boundary_source = "\n".join([
        command_sanitizer, risk_router, intent_router,
        function_body(app_js, "hashString"),
        function_body(app_js, "normalizeSaasCeoCommand"),
        function_body(app_js, "uniqueSaasCeoRoutes"),
        command_builder,
        function_body(app_js, "handleSaasCeoCommandSubmit"),
    ])
    length_probe = subprocess.run(["node"], input=(
        "const assert = require('node:assert/strict');\n"
        "const publicRuntimeText = value => String(value || '');\n"
        "const activeSaasStore = () => ({store_id:'length-fixture-store'});\n"
        "const isSaasModelConfigured = () => true;\n"
        "const isSaasAuthorizedConnectionStatus = () => true;\n"
        "let workflowCalls = 0, requestCalls = 0; const toasts = [];\n"
        "const prepareSaasNewListingProjectRequest = () => { workflowCalls++; throw new Error('overlong input reached workflow'); };\n"
        "const requestSaasAiCeoChat = () => { requestCalls++; throw new Error('overlong input reached HTTP'); };\n"
        "const showActionToast = message => toasts.push(message);\n"
        "const tail = '最后限制：不要创建新项目，不要发布。';\n"
        "const atLimit = 'x'.repeat(900 - tail.length) + tail;\n"
        "const overLimit = 'x'.repeat(901 - tail.length) + tail;\n"
        "const input = {value:overLimit}; const document = {querySelector:() => input};\n"
        "const state = {saasAiCeoPendingAttachments:[{asset_id:'length-fixture-asset'}],saasListingComposerDraft:{product:'原项目'}};\n"
        "const stateBefore = JSON.stringify(state);\n"
        + length_boundary_source
        + "\nconst command = buildSaasCeoCommand(atLimit, {hasPacket:true});\n"
        "assert.equal(command.text, atLimit);\n"
        "assert.equal(buildSaasCeoCommand(overLimit, {}), null);\n"
        "assert.equal(handleSaasCeoCommandSubmit(overLimit), null);\n"
        "assert.equal(workflowCalls, 0); assert.equal(requestCalls, 0);\n"
        "assert.equal(input.value, overLimit); assert.equal(JSON.stringify(state), stateBefore);\n"
        "assert.equal(toasts.length, 1); assert.match(toasts[0], /900/);\n"
        "console.log('PASS complete 900-character input and side-effect-free over-limit rejection');\n"
    ), text=True, encoding="utf-8", capture_output=True, check=False)
    assert length_probe.returncode == 0, length_probe.stderr or length_probe.stdout

    print("PASS jiejing_ai_ceo_product_label_extraction")


if __name__ == "__main__":
    main()
