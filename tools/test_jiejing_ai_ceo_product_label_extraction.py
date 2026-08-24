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
            + "]));\n"
        ),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    assert json.loads(intent_probe.stdout.strip()) == ["research", "listing", "bulk", "research"], intent_probe.stdout

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
    require(command_builder, ".slice(0, 900)", "AI CEO model request keeps the backend-supported instruction length")

    print("PASS jiejing_ai_ceo_product_label_extraction")


if __name__ == "__main__":
    main()
