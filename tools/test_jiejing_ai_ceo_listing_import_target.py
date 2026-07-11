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

    report_delivery = function_body(app_js, "renderSaasAiCeoMarketReportDeliveryMarkup")
    require(report_delivery, "data-report-id", "report-bound market delivery")
    require(report_delivery, "data-ai-ceo-assistant-id", "turn-bound market delivery")

    exact_target = function_body(app_js, "saasAiCeoMarketResearchTurnForImport")
    for marker in [
        "source?.dataset?.reportId",
        "source?.dataset?.aiCeoAssistantId",
        "item.report_id === reportId",
        "turn.assistant_id === assistantId",
        "saasAiCeoMarketResearchEligibility",
    ]:
        require(exact_target, marker, "exact clicked-report import resolution")

    import_handler = function_body(app_js, "handleSaasAiCeoImportMarketToListing")
    for marker in [
        "saasAiCeoMarketResearchTurnForImport(source)",
        "clickedTarget",
        "clickedTarget && !targetedTurn",
        "targetedTurn || saasAiCeoMarketResearchImportState().turn",
    ]:
        require(import_handler, marker, "clicked-report import handler")

    action_handler = function_body(app_js, "handleSaasAction")
    require(action_handler, "handleSaasAiCeoImportMarketToListing(button)", "clicked button forwarding")

    print("PASS jiejing_ai_ceo_listing_import_target")


if __name__ == "__main__":
    main()
