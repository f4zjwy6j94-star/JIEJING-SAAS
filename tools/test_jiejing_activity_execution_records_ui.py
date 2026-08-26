#!/usr/bin/env python3
"""Merchant activity must show safe, actionable eBay execution records."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
APP_HTML = ROOT / "app.html"


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    app_html = APP_HTML.read_text(encoding="utf-8")
    if 'class="nav-item" data-view="activity"' not in app_html or "运行记录" not in app_html:
        raise AssertionError("Public merchant navigation must expose the account-scoped execution record page")
    start_marker = "function saasExecutionActionLabel"
    end_marker = "function renderSaasActivityCenter"
    if start_marker not in app_js or end_marker not in app_js:
        raise AssertionError("Activity page must expose merchant-safe execution record helpers")
    source = app_js[app_js.index(start_marker) : app_js.index(end_marker)]
    blocked_execution = {
        "execution_id": "exec_30819af518bc6997",
        "confirmation_id": "confirm_existing_draft_publish_1e407d92cf30e663a4f30468f64d7b34",
        "action_type": "publish_listing",
        "status": "blocked_platform_error",
        "created_at": "2026-08-26T03:50:00Z",
        "result": {
            "status": "blocked_platform_error",
            "action_type": "publish_listing",
            "message": "eBay publishOffer failed for the approved existing draft.",
            "steps": [
                {"step": "inspect_existing_offer", "status": "ok", "http_status": 200},
                {
                    "step": "publish_existing_offer",
                    "path": "/sell/inventory/v1/offer/245675556011/publish",
                    "status": "http_error",
                    "http_status": 400,
                    "platform_error": {
                        "error_id": 25019,
                        "code": "platform_error",
                        "domain": "API_INVENTORY",
                        "message": "The seller account is temporarily restricted.",
                    },
                },
            ],
            "audit": {"real_execution": {"published_to_ebay": False}},
            "secret_exposed": False,
        },
    }
    confirmation = {
        "confirmation_id": blocked_execution["confirmation_id"],
        "action_type": "publish_listing",
        "status": "needs_revision",
        "item": {
            "controlled_existing_draft_publish": True,
            "existing_ebay_draft": {
                "offer_id": "245675556011",
                "offer_status": "UNPUBLISHED",
                "sku": "JJ-INCENSE-JC2023041300002-01",
            },
            "publish_payload": {"listing": {"sku": "JJ-INCENSE-JC2023041300002-01"}},
        },
    }
    script = f"""
globalThis.state = {{
  saasExecutionResults: [{json.dumps(blocked_execution)}],
  saasConfirmations: [{json.dumps(confirmation)}],
}};
function escapeHtml(value) {{ return String(value ?? ""); }}
function publicRuntimeText(value) {{ return String(value ?? ""); }}
function saasTimestampLabel(value) {{ return value ? "08/26 11:50" : "-"; }}
function saasLatestExecutionPlatformError(record) {{
  const steps = Array.isArray(record?.result?.steps) ? record.result.steps : [];
  for (let index = steps.length - 1; index >= 0; index -= 1) {{
    if (steps[index]?.platform_error) return steps[index].platform_error;
  }}
  return null;
}}
{source}
const model = saasMerchantExecutionRecordViewModel(state.saasExecutionResults[0]);
if (!model) throw new Error("blocked eBay execution model missing");
if (model.offerId !== "245675556011") throw new Error("Offer ID was not recovered from approved confirmation/step");
if (model.sku !== "JJ-INCENSE-JC2023041300002-01") throw new Error("SKU was not recovered from approved confirmation");
if (model.publishedToEbay !== false) throw new Error("provider rejection was mislabeled as published");
if (model.recoveryKind !== "ebay_account_restricted") throw new Error("25019 restriction was not classified for merchant");
const markup = renderSaasActivityExecutionRecords();
for (const required of [
  "exec_30819af518bc6997",
  "confirm_existing_draft_publish_1e407d92cf30e663a4f30468f64d7b34",
  "245675556011",
  "JJ-INCENSE-JC2023041300002-01",
]) {{
  if (!markup.includes(required)) throw new Error(`merchant execution record missing: ${{required}}`);
}}
for (const forbidden of ["access_token", "refresh_token", "signedUrl"]) {{
  if (markup.includes(forbidden)) throw new Error(`unsafe or false execution record content: ${{forbidden}}`);
}}
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or "merchant execution record behavior failed")
    for required_copy in ["最近执行记录", "账号暂时受限", "eBay 站内信", "未公开"]:
        if required_copy not in source:
            raise AssertionError(f"merchant execution recovery copy missing: {required_copy}")
    activity_source = app_js[app_js.index(end_marker) : app_js.index("function renderActivities", app_js.index(end_marker))]
    if "renderSaasActivityExecutionRecords()" not in activity_source:
        raise AssertionError("AI CEO activity page does not render account-scoped execution records")
    print("PASS Jiejing activity shows safe merchant-facing eBay execution records")


if __name__ == "__main__":
    main()
