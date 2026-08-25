import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    start_marker = "function saasUnpublishedDraftReceiptViewModel"
    end_marker = "function saasCurrentUnpublishedDraftReceipt"
    if start_marker not in app_js or end_marker not in app_js:
        raise AssertionError("Listing must expose a merchant-facing unpublished-draft receipt model")
    start = app_js.index(start_marker)
    end = app_js.index("function saasLatestExecutionResult", start)
    function_source = app_js[start:end]
    execution = {
        "execution_id": "exec_receipt_test",
        "confirmation_id": "confirm_receipt_test",
        "action_type": "save_ebay_listing_draft",
        "status": "saved_to_ebay_draft",
        "created_at": "2026-08-25T17:28:47Z",
        "result": {
            "status": "saved_to_ebay_draft",
            "action_type": "save_ebay_listing_draft",
            "secret_exposed": False,
            "platform_result": {
                "offer_id": "245675556011",
                "offer_status": "UNPUBLISHED",
                "sku": "JJ-INCENSE-JC2023041300002-01",
                "writes_to_ebay": True,
                "public_listing_created": False,
                "published_to_ebay": False,
            },
        },
    }
    script = f"""
{function_source}
const receipt = saasUnpublishedDraftReceiptViewModel({json.dumps(execution)});
if (!receipt || receipt.status !== "saved_to_ebay_draft") throw new Error("saved draft receipt missing");
if (receipt.offerId !== "245675556011") throw new Error("Offer ID missing");
if (receipt.offerStatus !== "UNPUBLISHED") throw new Error("unpublished state missing");
if (receipt.sku !== "JJ-INCENSE-JC2023041300002-01") throw new Error("SKU mismatch");
if (receipt.publicListingCreated !== false || receipt.publishedToEbay !== false) throw new Error("public publish boundary lost");
globalThis.state = {{
  saasListingComposerDraft: {{
    fields: {{}},
    publish_prefill: {{}},
    merchant_product_fact_packet: {{
      merchant_confirmed_facts: {{ sku: "JJ-INCENSE-JC2023041300002-01" }},
      derived_listing_suggestions: {{ sku: "OLD-DERIVED-SKU" }},
    }},
  }},
  saasConfirmations: [
    {{
      confirmation_id: "confirm_stale",
      action_type: "save_ebay_listing_draft",
      status: "executed",
      item: {{
        listing_project_identity: {{ key: "project-stale" }},
        publish_payload: {{ listing: {{ sku: "OLD-SKU" }} }},
      }},
    }},
    {{
      confirmation_id: "confirm_receipt_test",
      action_type: "save_ebay_listing_draft",
      status: "executed",
      item: {{
        listing_project_identity: {{ key: "project-current" }},
        publish_payload: {{ listing: {{ sku: "JJ-INCENSE-JC2023041300002-01" }} }},
      }},
    }},
  ],
  saasExecutionResults: [
    {{
      confirmation_id: "confirm_stale",
      action_type: "save_ebay_listing_draft",
      status: "saved_to_ebay_draft",
      result: {{
        status: "saved_to_ebay_draft",
        action_type: "save_ebay_listing_draft",
        secret_exposed: false,
        platform_result: {{ offer_id: "stale-offer", offer_status: "UNPUBLISHED", sku: "OLD-SKU", writes_to_ebay: true, public_listing_created: false, published_to_ebay: false }},
      }},
    }},
    {json.dumps(execution)},
  ],
}};
function saasCurrentListingProjectIdentity() {{ return {{ key: "project-current-after-refresh" }}; }}
const current = saasCurrentUnpublishedDraftReceipt();
if (!current || current.offerId !== "245675556011") throw new Error("current Listing receipt was not selected");
if (current.confirmationId !== "confirm_receipt_test") throw new Error("receipt crossed Listing project boundary");
if (current.executionId !== "exec_receipt_test") throw new Error("receipt execution binding missing");
function escapeHtml(value) {{ return String(value); }}
function saasTimestampLabel(value) {{ return value ? "08/26 01:28" : "-"; }}
const markup = renderSaasListingUnpublishedDraftReceipt();
for (const required of ["已保存到 eBay 未发布草稿", "245675556011", "JJ-INCENSE-JC2023041300002-01", "未公开", "没有创建公开 Listing"]) {{
  if (!markup.includes(required)) throw new Error(`merchant receipt missing: ${{required}}`);
}}
for (const required of [
  'data-saas-action="create-existing-draft-publish-confirmation"',
  'data-saas-offer-id="245675556011"',
  'data-saas-execution-id="exec_receipt_test"',
  'data-saas-sku="JJ-INCENSE-JC2023041300002-01"',
  "生成正式发布确认单",
]) {{
  if (!markup.includes(required)) throw new Error(`controlled publish handoff missing: ${{required}}`);
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
        raise AssertionError(result.stderr.strip() or "unpublished draft receipt behavior failed")
    composer_start = app_js.index("function renderSaasListingComposerWorkspace")
    composer_end = app_js.index("function renderSaasListingMinimalWorkspace", composer_start)
    composer = app_js[composer_start:composer_end]
    if "renderSaasListingUnpublishedDraftReceipt(draft)" not in composer:
        raise AssertionError("Listing workspace does not surface the current unpublished-draft receipt")
    for marker in [
        "async function createSaasExistingDraftPublishConfirmation",
        "existing-draft-publish-confirmation",
        '"create-existing-draft-publish-confirmation"',
    ]:
        if marker not in app_js:
            raise AssertionError(f"Listing receipt does not expose the controlled publish handoff: {marker}")


if __name__ == "__main__":
    main()
