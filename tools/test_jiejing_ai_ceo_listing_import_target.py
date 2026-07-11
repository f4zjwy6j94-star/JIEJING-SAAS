#!/usr/bin/env python3
"""Keep AI CEO report import bound to the report the merchant clicked."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    if start < 0:
        marker = f"async function {name}"
        start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    next_function = source.find("\nfunction ", start + len(marker))
    next_async = source.find("\nasync function ", start + len(marker))
    ends = [value for value in (next_function, next_async) if value > start]
    end = min(ends) if ends else len(source)
    return source[start:end]


def require(body: str, marker: str, label: str) -> None:
    if marker not in body:
        raise AssertionError(f"missing {label}: {marker}")


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")

    listing_handoff = function_body(app_js, "renderSaasAiCeoListingHandoffMarkup")
    require(listing_handoff, "data-ai-ceo-assistant-id", "turn-bound Listing handoff")
    require(listing_handoff, "data-product-name", "product-bound Listing handoff")

    report_delivery = function_body(app_js, "renderSaasAiCeoMarketReportDeliveryMarkup")
    require(report_delivery, "data-report-id", "report-bound market delivery")
    require(report_delivery, "data-ai-ceo-assistant-id", "turn-bound market delivery")
    require(report_delivery, "data-product-name", "product-bound market delivery")
    require(report_delivery, "rememberSaasAiCeoMarketImportTarget(latest, title)", "render-time report identity registration")

    import_target_memory = function_body(app_js, "rememberSaasAiCeoMarketImportTarget")
    for marker in [
        "assistant:",
        "report:",
        "rendered_product:",
        "saasAiCeoMarketImportTargets.size > 80",
    ]:
        require(import_target_memory, marker, "bounded rendered-report target memory")

    exact_target = function_body(app_js, "saasAiCeoMarketResearchTurnForImport")
    for marker in [
        "source?.dataset?.reportId",
        "source?.dataset?.aiCeoAssistantId",
        "source?.dataset?.productName",
        "saasAiCeoMarketImportTargets.get(`assistant:${assistantId}`)",
        "saasAiCeoMarketImportTargets.get(`report:${reportId}`)",
        "item.report_id === reportId",
        "turn.assistant_id === assistantId",
        "saasAiCeoMarketResearchEligibility",
        ".filter((turn) => turn.assistant_id === assistantId)",
        ".find((eligibility) => eligibility.eligible)",
        "saasAiCeoMarketResearchTurnMatchesClickedProduct",
    ]:
        require(exact_target, marker, "exact clicked-report import resolution")

    product_match = function_body(app_js, "saasAiCeoMarketResearchTurnMatchesClickedProduct")
    require(product_match, "latest?.rendered_product", "rendered product identity comparison")

    import_handler = function_body(app_js, "handleSaasAiCeoImportMarketToListing")
    for marker in [
        "saasAiCeoMarketResearchTurnForImport(source)",
        "clickedTarget",
        "clickedTarget && !targetedTurn",
        "targetedTurn || saasAiCeoMarketResearchImportState().turn",
        "expectedProduct:",
    ]:
        require(import_handler, marker, "clicked-report import handler")

    apply_import = function_body(app_js, "applySaasAiCeoMarketTurnToListing")
    for marker in [
        "clickedProductMatches",
        "options.expectedProduct",
        "saasAiCeoMarketImportProductKey(sourceReportProduct)",
    ]:
        require(apply_import, marker, "clicked-product-safe draft application")

    action_handler = function_body(app_js, "handleSaasAction")
    require(action_handler, "handleSaasAiCeoImportMarketToListing(button)", "clicked button forwarding")

    chat_binding = function_body(app_js, "bindSaasAiCeoMarketImportControls")
    for marker in [
        'data-saas-action="ai-ceo-import-market-to-listing"',
        "event.stopPropagation()",
        "handleSaasAiCeoImportMarketToListing(button)",
        "系统不会改用其他商品代替",
    ]:
        require(chat_binding, marker, "dynamic AI CEO import control binding")

    viewport_sync = function_body(app_js, "syncSaasAiCeoFixedChatViewportState")
    require(viewport_sync, "bindSaasAiCeoMarketImportControls(chat)", "chat import binding activation")

    print("PASS jiejing_ai_ceo_listing_import_target")


if __name__ == "__main__":
    main()
