#!/usr/bin/env python3
"""Regression for concrete-product routing into the Listing workspace."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_body(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}")
    end = source.index(f"\nfunction {next_name}", start)
    return source[start:end]


def main() -> None:
    app_js = (ROOT / "app.js").read_text(encoding="utf-8")
    invalid_source = function_body(
        app_js,
        "saasIsInvalidMarketProductLabel",
        "saasCleanMarketCandidateName",
    )
    concrete_source = function_body(
        app_js,
        "saasIsConcreteProductLabel",
        "saasProductLabelForRecord",
    )
    draft_gate_source = function_body(
        app_js,
        "saasListingDraftHasConcreteProduct",
        "saasProductLabelForRecord",
    )

    rejected = [
        "先划掉这些高合规/高售后/红海方向",
        "暂时不做这些高风险商品",
        "不建议上架的品类",
        "排除高售后方向",
    ]
    accepted = [
        "硅胶柜门防撞垫",
        "Clear Silicone Cabinet Door Bumper Pads",
    ]
    node_script = f"""
const publicRuntimeText = (value = "") => String(value || "");
{invalid_source}
{concrete_source}
{draft_gate_source}
const rejected = {json.dumps(rejected, ensure_ascii=False)};
const accepted = {json.dumps(accepted, ensure_ascii=False)};
for (const value of rejected) {{
  if (saasIsConcreteProductLabel(value)) {{
    throw new Error(`negative operating decision became a product: ${{value}}`);
  }}
}}
for (const value of accepted) {{
  if (!saasIsConcreteProductLabel(value)) {{
    throw new Error(`real product was rejected: ${{value}}`);
  }}
}}
const poisonedDraft = {{
  source_type: "ai_ceo_market_report",
  product: rejected[0],
  title: rejected[0],
  fields: {{ title: rejected[0] }},
}};
if (saasListingDraftHasConcreteProduct(poisonedDraft)) {{
  throw new Error("legacy poisoned draft must be discarded during restore");
}}
const mixedPoisonedDraft = {{
  source_type: "ai_ceo_market_report",
  product: rejected[0],
  title: accepted[0],
  fields: {{ title: accepted[0] }},
}};
if (saasListingDraftHasConcreteProduct(mixedPoisonedDraft)) {{
  throw new Error("one plausible title must not hide a poisoned product identity");
}}
const realDraft = {{
  source_type: "merchant_input",
  product: accepted[0],
  title: accepted[0],
  fields: {{ title: accepted[0] }},
}};
if (!saasListingDraftHasConcreteProduct(realDraft)) {{
  throw new Error("real merchant product draft must remain restorable");
}}
"""
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    snapshot_restore = function_body(
        app_js,
        "hydrateSaasProtectedStateFromCache",
        "clearSaasSessionFromStorage",
    )
    assert "saasListingDraftHasConcreteProduct(restoredListingDraft)" in snapshot_restore
    assert "listing_composer_draft: null" in snapshot_restore

    backend_restore = function_body(
        app_js,
        "restoreSaasListingComposerDraftFromBackendReports",
        "sanitizeSaasListingComposerDraftSnapshot",
    )
    assert "saasListingDraftHasConcreteProduct(restored)" in backend_restore

    product_render = function_body(
        app_js,
        "renderSaasProductListingCenter",
        "renderProductListingCenter",
    )
    assert "saasListingDraftHasConcreteProduct(state.saasListingComposerDraft)" in product_render
    assert "state.saasListingComposerDraft = null" in product_render
    assert 'saasListingDraftFromReport(listingReport, "listing_render_gate")' in product_render
    assert "saasListingDraftHasConcreteProduct(safeListingReportDraft)" in product_render
    assert "const showPublishFlow = Boolean(safeListingDraft || hasLiveListing) && saasListingWizardRecord()?.step === 4;" in product_render

    print("PASS jiejing_listing_concrete_product_gate")


if __name__ == "__main__":
    main()
