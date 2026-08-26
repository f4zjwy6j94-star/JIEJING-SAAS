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

    display_start = app_js.index("function saasConfirmationsForDisplay")
    display_end = app_js.index("function saasConfirmationCanonicalKey", display_start)
    display_source = app_js[display_start:display_end]
    display_script = f"""
globalThis.state = {{
  saasCompany: {{ company_id: "company-current" }},
  saasIdentity: {{ company_id: "company-current" }},
  saasConfirmations: [],
}};
function saasLatestProductWorkflowTask() {{ return {{ task_id: "task-old-workflow" }}; }}
function activeSaasStore() {{ return {{ store_id: "store-current" }}; }}
function dedupeSaasConfirmations(cards) {{ return [...cards]; }}
function saasTimestampMillis(value) {{ return Date.parse(value || 0) || 0; }}
function isSaasExactReadOnlyOAuthConfirmation() {{ return false; }}
function isSaasExactUnpublishedDraftOAuthConfirmation() {{ return false; }}
function isSaasExactReadOnlySyncConfirmation() {{ return false; }}
function isSaasExactUnpublishedDraftSaveConfirmation() {{ return false; }}
function isSaasUniqueCurrentInventoryLocationConfirmation() {{ return false; }}
function isSaasReadOnlyOAuthSensitiveConfirmation() {{ return false; }}
function isSaasReadOnlySyncSensitiveConfirmation() {{ return false; }}
function isSaasUnpublishedDraftSaveSensitiveConfirmation() {{ return false; }}
function isSaasInventoryLocationSensitiveConfirmation() {{ return false; }}
function isSaasControlledExistingDraftPublishConfirmation(card) {{
  return card?.item?.source === "merchant_existing_ebay_draft_publish_intake";
}}
function isSaasUniqueCurrentControlledExistingDraftPublishConfirmation(card) {{
  return Boolean(
    card?.confirmation_id === "confirm-controlled" &&
    card?.company_id === "company-current" &&
    card?.store_id === "store-current" &&
    card?.status === "pending" &&
    isSaasControlledExistingDraftPublishConfirmation(card)
  );
}}
function isSaasExactManualReconcileControlledExistingDraftPublishConfirmation(card) {{
  return Boolean(
    card?.confirmation_id === "confirm-controlled-reconcile" &&
    card?.company_id === "company-current" &&
    card?.store_id === "store-current" &&
    card?.status === "external_execution_processing_manual_reconcile" &&
    isSaasControlledExistingDraftPublishConfirmation(card)
  );
}}
{display_source}
const cards = [
  {{
    confirmation_id: "confirm-controlled",
    company_id: "company-current",
    store_id: "store-current",
    task_id: "task-controlled-publish",
    status: "pending",
    action_type: "publish_listing",
    created_at: "2026-08-25T20:31:31Z",
    item: {{ source: "merchant_existing_ebay_draft_publish_intake", controlled_existing_draft_publish: true }},
  }},
  {{
    confirmation_id: "confirm-controlled-reconcile",
    company_id: "company-current",
    store_id: "store-current",
    task_id: "task-controlled-publish-reconcile",
    status: "external_execution_processing_manual_reconcile",
    action_type: "publish_listing",
    created_at: "2026-08-26T01:09:07Z",
    item: {{ source: "merchant_existing_ebay_draft_publish_intake", controlled_existing_draft_publish: true }},
  }},
  {{
    confirmation_id: "confirm-old-generic",
    company_id: "company-current",
    store_id: "store-current",
    task_id: "task-old-workflow",
    status: "pending",
    action_type: "publish_listing",
    created_at: "2026-08-10T19:11:00Z",
    item: {{ source: "generic_workflow" }},
  }},
];
state.saasConfirmations = cards;
const visible = saasConfirmationsForDisplay(cards);
if (!visible.some((card) => card.confirmation_id === "confirm-controlled")) {{
  throw new Error("current exact controlled publish confirmation was hidden by latest-task filtering");
}}
if (visible.filter((card) => card.confirmation_id === "confirm-controlled").length !== 1) {{
  throw new Error("controlled publish confirmation must be displayed exactly once");
}}
if (visible.filter((card) => card.confirmation_id === "confirm-controlled-reconcile").length !== 1) {{
  throw new Error("manual-reconcile controlled publish must stay visible exactly once");
}}
"""
    display_result = subprocess.run(
        ["node", "-e", display_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if display_result.returncode != 0:
        raise AssertionError(display_result.stderr.strip() or "controlled publish confirmation display behavior failed")

    detail_marker = "function saasControlledExistingDraftPublishDetailMarkup"
    if detail_marker not in app_js:
        raise AssertionError("controlled publish confirmation must render exact merchant-reviewable parameters")
    detail_start = app_js.index(detail_marker)
    detail_end = app_js.index("function saasWorkbenchConfirmationDetailMarkup", detail_start)
    detail_source = app_js[detail_start:detail_end]
    detail_script = f"""
function escapeHtml(value) {{ return String(value ?? ""); }}
function publicRuntimeText(value) {{ return String(value ?? ""); }}
function isSaasControlledExistingDraftPublishConfirmation(card) {{ return card?.item?.controlled_existing_draft_publish === true; }}
{detail_source}
const card = {{
  confirmation_id: "confirm-controlled",
  action_type: "publish_listing",
  status: "pending",
  item: {{
    source: "merchant_existing_ebay_draft_publish_intake",
    controlled_existing_draft_publish: true,
    existing_ebay_draft: {{ offer_id: "245675556011", offer_status: "UNPUBLISHED", sku: "JJ-INCENSE-JC2023041300002-01" }},
    controlled_publish_preflight: {{
      status: "ready_for_confirmation",
      disclosed_missing_facts: [
        "supplier_facts.package_weight_g",
        "supplier_facts.package_dimensions_cm",
        "supplier_facts.material",
        "finance_review.net_profit_money",
      ],
    }},
    publish_payload: {{
      marketplace_id: "EBAY_US",
      listing: {{
        title: "Backflow Incense Burner with Lotus Flower and Hand Design",
        sku: "JJ-INCENSE-JC2023041300002-01",
        price: {{ value: "29.99", currency: "USD" }},
        quantity: 1,
        condition: "NEW",
        category_id: "20552",
        merchant_location_key: "shenzhen-warehouse",
        item_specifics: {{ Brand: "Unbranded", Type: "Backflow Incense Burner", MPN: "Does Not Apply", Style: "Asian" }},
      }},
      business_policies: {{ fulfillment_policy_id: "252706512026", payment_policy_id: "252706224026", return_policy_id: "252706513026" }},
      asset_manifest: {{ assets: [{{ url: "https://private.example.test/image.jpg" }}] }},
    }},
  }},
}};
const markup = saasControlledExistingDraftPublishDetailMarkup(card);
for (const required of [
  "245675556011",
  "JJ-INCENSE-JC2023041300002-01",
  "Backflow Incense Burner with Lotus Flower and Hand Design",
  "USD 29.99",
  "数量 1",
  "20552",
  "shenzhen-warehouse",
  "252706512026",
  "252706224026",
  "252706513026",
  "1 张",
  "包装重量",
  "准确材质",
  "利润测算",
  "publishOffer",
]) {{
  if (!markup.includes(required)) throw new Error(`controlled confirmation detail missing: ${{required}}`);
}}
for (const forbidden of ["private.example.test", "token", "secret"]) {{
  if (markup.toLowerCase().includes(forbidden)) throw new Error(`controlled confirmation leaked internal detail: ${{forbidden}}`);
}}
"""
    detail_result = subprocess.run(
        ["node", "-e", detail_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if detail_result.returncode != 0:
        raise AssertionError(detail_result.stderr.strip() or "controlled publish detail rendering failed")

    if "确认并正式发布这个 Offer" not in app_js:
        raise AssertionError("controlled publish approval button must say that approval performs the public publish")
    if "批准后会立即执行一次 publishOffer" not in app_js:
        raise AssertionError("controlled publish merchant brief must disclose the immediate external write")
    if "saasControlledExistingDraftPublishDetailMarkup(card)" not in app_js:
        raise AssertionError("decision center does not render the exact controlled publish parameter summary")
    if "只读核对原 Offer 状态" not in app_js:
        raise AssertionError("manual-reconcile controlled publish must expose a read-only recovery action")


if __name__ == "__main__":
    main()
