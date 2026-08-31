#!/usr/bin/env python3
"""Regression for merchant-created publish confirmations."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.repository import SaaSRepository  # noqa: E402

OUT = ROOT / "output" / "test-jiejing-publish-confirmation-intake"
SAAS_DB = OUT / "saas.sqlite"
RUNTIME_DB = OUT / "runtime.sqlite"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in (SAAS_DB, RUNTIME_DB):
        if path.exists():
            path.unlink()
    port = 8798
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
            "serve",
            "--db",
            str(SAAS_DB),
            "--runtime-db",
            str(RUNTIME_DB),
            "--output-root",
            str(OUT),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        if wait_for_health(base_url):
            return fail("saas backend did not become healthy")
        registered = post_json(
            f"{base_url}/auth/register",
            {"email": "publish-intake@example.test", "password": "local-test-password", "company_name": "Publish Intake Test"},
        )
        token = registered.get("token")
        user = registered.get("user", {})
        if not token:
            return fail("registration should return token")
        store = post_json(
            f"{base_url}/stores",
            {"platform": "ebay", "store_name": "publish-intake-store", "marketplace": "EBAY_US"},
            token=token,
        ).get("store", {})
        if not store.get("store_id"):
            return fail("store should be created")
        packet_result = post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-read-only/data-packet",
            {
                "resources": ["account_business_policies", "inventory_and_offers"],
                "source_mode": "official_api",
                "sample_payload": {
                    "account_business_policies": {
                        "fulfillment_policy_id": "fulfillment-policy",
                        "payment_policy_id": "payment-policy",
                        "return_policy_id": "return-policy",
                    },
                    "inventory_and_offers": {
                        "merchant_location_key": "default",
                        "item_location": "US",
                    },
                },
            },
            token=token,
        )
        if not packet_result.get("data_packet", {}).get("packet_id"):
            return fail("publish intake setup should create a sanitized data packet")
        listing_project_identity = {
            "key": "listing-project-unit-fresh-bumper",
            "source_report_id": "report-unit-fresh-bumper",
            "candidate_id": "candidate-unit-fresh-bumper",
        }
        product_image_url = "https://EXAMPLE.test:443/fresh-bumper.jpg#browser-fragment"
        product_facts = post_json(
            f"{base_url}/stores/{store['store_id']}/product-facts",
            {
                "listing_project_identity": listing_project_identity,
                "merchant_product_fact_packet": {
                    "merchant_confirmed_facts": {
                        "product_name": "Fresh silicone door bumper pads",
                        "source_url": "https://supplier.example.test/fresh-bumper",
                        "sku": "JJ-FRESH-INTAKE-001",
                        "condition": "NEW",
                        "material": "Silicone",
                        "package_weight_g": "80",
                        "package_length_cm": "12",
                        "package_width_cm": "8",
                        "package_height_cm": "2",
                        "unit_cost": "2.50",
                        "selling_price": "9.99",
                        "currency": "USD",
                        "quantity": "1",
                        "item_location": "US",
                        "image_urls": product_image_url,
                        "image_rights_confirmed": True,
                    }
                },
            },
            token=token,
        )
        product_fact_report_id = product_facts.get("report", {}).get("report_id")
        if not product_fact_report_id:
            return fail(f"product facts should create an authoritative report: {product_facts}")
        with sqlite3.connect(SAAS_DB) as conn:
            confirmations_before_simulation_guard = conn.execute("select count(*) from confirmations").fetchone()[0]
        for route in (
            "publish-confirmation",
            "ebay-draft-confirmation",
            "existing-draft-publish-confirmation",
        ):
            status, guarded = post_json_status(
                f"{base_url}/stores/{store['store_id']}/{route}",
                {
                    "simulation_only": True,
                    "product": "Simulation-only bookmark",
                    "listing_project_identity": {"key": "simulation-only-bookmark"},
                },
                token=token,
            )
            if status != 409 or guarded.get("error") != "simulation_only_listing_cannot_create_ebay_confirmation":
                return fail(f"{route} must reject simulation-only product data before any eBay confirmation: {status} {guarded}")
        with sqlite3.connect(SAAS_DB) as conn:
            confirmations_after_simulation_guard = conn.execute("select count(*) from confirmations").fetchone()[0]
        if confirmations_after_simulation_guard != confirmations_before_simulation_guard:
            return fail("simulation-only requests must not create any eBay confirmation record")
        status, arbitrary_rights = post_json_status(
            f"{base_url}/stores/{store['store_id']}/publish-confirmation",
            {
                "product": "Unverified arbitrary image",
                "listing_project_identity": listing_project_identity,
                "listing": {"sku": "UNVERIFIED", "title": "Unverified arbitrary image"},
                "asset_manifest": {"assets": [{"url": "https://untrusted.example.test/arbitrary.jpg"}]},
                "publish_evidence_refs": {"product_fact_report_id": product_fact_report_id},
            },
            token=token,
        )
        if status != 422 or arbitrary_rights.get("error") != "publish_evidence_not_ready":
            return fail(f"arbitrary browser image without server evidence must be blocked: {status} {arbitrary_rights}")
        with sqlite3.connect(SAAS_DB) as conn:
            if conn.execute("select count(*) from confirmations").fetchone()[0] != confirmations_after_simulation_guard:
                return fail("blocked publish evidence must not create a confirmation")
        result = post_json(
            f"{base_url}/stores/{store['store_id']}/publish-confirmation",
            {
                "product": "Fresh silicone door bumper pads",
                "listing_project_identity": listing_project_identity,
                "listing": {
                    "sku": "JJ-FRESH-INTAKE-001",
                    "title": "Clear Silicone Cabinet Door Bumper Pads Quiet Stopper Set",
                    "description_html": "<p>Clear silicone bumper pads for cabinet doors.</p>",
                    "category_id": "259153",
                    "category_leaf": "Cabinet Door Dampers & Bumpers",
                    "condition": "NEW",
                    "price": {"value": "9.99", "currency": "USD"},
                    "quantity": 1,
                    "item_specifics": {"Brand": "Unbranded", "Type": "Door Bumper", "Material": "Silicone"},
                },
                "supplier_facts": {
                    "package_weight_g": 80,
                    "package_dimensions_cm": {"length": 12, "width": 8, "height": 2},
                    "material": "Silicone",
                    "item_location": "US",
                },
                "asset_manifest": {"assets": [{"url": product_image_url}]},
                "publish_evidence_refs": {"product_fact_report_id": product_fact_report_id},
                "finance_review": {"net_profit_money": {"value": "3.25", "currency": "USD"}},
            },
            token=token,
        )
        confirmation = result.get("confirmation", {})
        if confirmation.get("action_type") != "publish_listing" or confirmation.get("status") != "pending":
            return fail(f"publish intake should create a pending publish confirmation: {result}")
        with sqlite3.connect(SAAS_DB) as conn:
            publish_task_status = conn.execute(
                "select status from tasks where task_id = ?",
                (confirmation.get("task_id"),),
            ).fetchone()[0]
        if publish_task_status != "waiting_confirmation":
            return fail(f"publish intake task must show its real waiting state: {publish_task_status}")
        if result.get("real_platform_writes_enabled") is not False:
            return fail("local publish intake must not enable real writes")
        if confirmation.get("item", {}).get("listing_project_identity", {}).get("key") != "listing-project-unit-fresh-bumper":
            return fail(f"publish confirmation must remain bound to its Listing project: {confirmation}")
        readiness = result.get("publish_readiness", {})
        keys = {item.get("key") for item in readiness.get("checks", [])}
        for required in {"ip_vero_and_claims", "profit_and_fee_sanity", "inventory_api_lifecycle"}:
            if required not in keys:
                return fail(f"publish intake readiness missing {required}: {readiness}")
        traffic = readiness.get("traffic_light_report", {})
        if not traffic or traffic.get("requires_confirmation_center") is not True:
            return fail(f"publish intake should expose the red/yellow/green confirmation gate: {readiness}")
        if traffic.get("real_write_allowed_without_confirmation") is not False:
            return fail(f"publish intake must not allow real writes without confirmation: {traffic}")
        evidence_packet = readiness.get("backend_evidence_packet", {})
        if evidence_packet.get("contract_version") != "2026-06-19-backend-publish-preflight-evidence":
            return fail(f"publish intake should expose backend evidence packet contract: {evidence_packet}")
        for marker in [
            "checks_have_source_records",
            "checks_have_fix_actions",
            "requires_confirmation_center",
        ]:
            if evidence_packet.get(marker) is not True:
                return fail(f"backend evidence packet should mark {marker}=true: {evidence_packet}")
        for marker in [
            "creates_real_write",
            "real_write_allowed_without_confirmation",
            "frontend_gets_token",
            "runtime_gets_token",
            "secret_exposed",
        ]:
            if evidence_packet.get(marker) is not False:
                return fail(f"backend evidence packet should mark {marker}=false: {evidence_packet}")
        for check in readiness.get("checks", []):
            if not check.get("source_records"):
                return fail(f"each readiness check should expose sanitized source_records: {check}")
            fix_action = check.get("fix_action", {})
            if not fix_action or fix_action.get("can_trigger_real_write") is not False:
                return fail(f"each readiness check should expose a safe backend fix_action: {check}")
            if fix_action.get("can_trigger_ebay_oauth") is not False or fix_action.get("can_trigger_payment") is not False:
                return fail(f"readiness fix_action must not trigger OAuth or payment: {check}")
            confirmation_gate = check.get("confirmation_gate", {})
            if confirmation_gate.get("real_write_allowed_without_confirmation") is not False:
                return fail(f"each readiness check should remain confirmation gated: {check}")
        item = confirmation.get("item", {})
        payload = item.get("publish_payload", {})
        if payload.get("listing_project_identity", {}).get("key") != listing_project_identity["key"]:
            return fail(f"approved payload must carry the server-normalized Listing project scope: {payload}")
        if payload.get("asset_manifest", {}).get("assets", [{}])[0].get("url") != "https://example.test/fresh-bumper.jpg":
            return fail(f"approved payload must persist the resolver's canonical asset URL: {payload}")
        if payload.get("business_policies", {}).get("return_policy_id") != "return-policy":
            return fail(f"publish intake should merge business policies from packet: {payload}")
        serialized = json.dumps(result, ensure_ascii=False).lower()
        if "refresh_token" in serialized or "api_key" in serialized or "access_token" in serialized:
            return fail("publish intake response must not expose secrets")

        draft_request = {
                "product": "Fresh silicone door bumper pads",
                "listing_project_identity": {
                    "key": "listing-project-unit-fresh-bumper",
                    "product": "Fresh silicone door bumper pads",
                    "source_id": "report-unit-fresh-bumper",
                    "candidate_id": "candidate-unit-fresh-bumper",
                },
                "listing": result.get("confirmation", {}).get("item", {}).get("publish_payload", {}).get("listing", {}),
                "supplier_facts": result.get("confirmation", {}).get("item", {}).get("publish_payload", {}).get("supplier_facts", {}),
                "asset_manifest": result.get("confirmation", {}).get("item", {}).get("publish_payload", {}).get("asset_manifest", {}),
                "publish_evidence_refs": {"product_fact_report_id": product_fact_report_id},
                "finance_review": result.get("confirmation", {}).get("item", {}).get("publish_payload", {}).get("finance_review", {}),
                "idempotency_key": "draft-intake-unit-fresh-bumper",
            }
        draft_result = post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-draft-confirmation",
            draft_request,
            token=token,
        )
        draft_confirmation = draft_result.get("confirmation", {})
        if draft_confirmation.get("action_type") != "save_ebay_listing_draft" or draft_confirmation.get("status") != "pending":
            return fail(f"draft intake should create a distinct pending eBay draft confirmation: {draft_result}")
        with sqlite3.connect(SAAS_DB) as conn:
            draft_task_status = conn.execute(
                "select status from tasks where task_id = ?",
                (draft_confirmation.get("task_id"),),
            ).fetchone()[0]
        if draft_task_status != "waiting_confirmation":
            return fail(f"draft intake task must show its real waiting state: {draft_task_status}")
        if draft_confirmation.get("item", {}).get("creates_public_listing") is not False:
            return fail(f"draft confirmation must explicitly prove it cannot create a public listing: {draft_confirmation}")
        if draft_confirmation.get("item", {}).get("requires_publish_offer_call") is not False:
            return fail(f"draft confirmation must explicitly prohibit publishOffer: {draft_confirmation}")
        for safe_flag in ("frontend_gets_token", "runtime_gets_token"):
            if draft_confirmation.get("item", {}).get(safe_flag) is not False:
                return fail(
                    f"draft confirmation must preserve the value-free {safe_flag}=false safety proof: "
                    f"{draft_confirmation.get('item', {}).get(safe_flag)!r}"
                )
        if draft_result.get("real_platform_writes_enabled") is not False:
            return fail("local draft intake must not enable real external writes")
        draft_serialized = json.dumps(draft_result, ensure_ascii=False).lower()
        if "refresh_token" in draft_serialized or "api_key" in draft_serialized or "access_token" in draft_serialized:
            return fail("draft intake response must not expose secrets")
        draft_confirmation_id = draft_confirmation.get("confirmation_id")
        with sqlite3.connect(SAAS_DB) as conn:
            original_report_json = conn.execute(
                "select report_json from reports where report_id = ?",
                (product_fact_report_id,),
            ).fetchone()[0]
            revoked_report = json.loads(original_report_json)
            revoked_packet = revoked_report["merchant_product_fact_packet"]
            revoked_packet["merchant_confirmed_facts"]["image_rights_confirmed"] = False
            for source_record in revoked_packet.get("source_records", []):
                if source_record.get("type") == "merchant_product_image":
                    source_record["rights_status"] = "pending"
            conn.execute(
                "update reports set report_json = ? where report_id = ?",
                (json.dumps(revoked_report, ensure_ascii=False), product_fact_report_id),
            )
        status, revoked_decision = post_json_status(
            f"{base_url}/confirmations/{draft_confirmation_id}/decision",
            {"decision": "approve", "note": "Must be blocked after rights evidence is revoked."},
            token=token,
        )
        if status != 409 or revoked_decision.get("error") != "publish_evidence_not_ready":
            return fail(f"approval must revalidate revoked image rights: {status} {revoked_decision}")
        with sqlite3.connect(SAAS_DB) as conn:
            if conn.execute(
                "select status from confirmations where confirmation_id = ?",
                (draft_confirmation_id,),
            ).fetchone()[0] != "pending":
                return fail("revoked evidence must leave the confirmation pending")
            conn.execute(
                "update reports set report_json = ? where report_id = ?",
                (original_report_json, product_fact_report_id),
            )
        draft_decision = post_json(
            f"{base_url}/confirmations/{draft_confirmation_id}/decision",
            {"decision": "approve", "note": "Contract test only; external writes remain disabled."},
            token=token,
        )
        if draft_decision.get("confirmation", {}).get("status") != "approved":
            return fail(f"merchant should be able to approve the distinct draft-save confirmation: {draft_decision}")
        with sqlite3.connect(SAAS_DB) as conn:
            approved_task_status = conn.execute(
                "select status from tasks where task_id = ?",
                (draft_confirmation.get("task_id"),),
            ).fetchone()[0]
        if approved_task_status != "approved_waiting_execution":
            return fail(f"approved draft task must show its real execution state: {approved_task_status}")
        with sqlite3.connect(SAAS_DB) as conn:
            conn.execute(
                "update reports set report_json = ? where report_id = ?",
                (json.dumps(revoked_report, ensure_ascii=False), product_fact_report_id),
            )
        status, revoked_execution = post_json_status(
            f"{base_url}/confirmations/{draft_confirmation_id}/execute",
            {"platform": "ebay", "idempotency_key": "draft-intake-unit-fresh-bumper"},
            token=token,
        )
        if status != 409 or revoked_execution.get("real_platform_write_attempted") is not False:
            return fail(f"execution must stop before claim/write after evidence revocation: {status} {revoked_execution}")
        with sqlite3.connect(SAAS_DB) as conn:
            if conn.execute(
                "select status from confirmations where confirmation_id = ?",
                (draft_confirmation_id,),
            ).fetchone()[0] != "needs_revision":
                return fail("revoked evidence must expire the old action-time approval")
            conn.execute(
                "update reports set report_json = ? where report_id = ?",
                (original_report_json, product_fact_report_id),
            )
        replacement_draft = post_json(
            f"{base_url}/stores/{store['store_id']}/ebay-draft-confirmation",
            {**draft_request, "idempotency_key": "draft-intake-unit-fresh-bumper-replacement"},
            token=token,
        ).get("confirmation", {})
        replacement_draft_id = replacement_draft.get("confirmation_id")
        if replacement_draft.get("status") != "pending" or not replacement_draft_id:
            return fail(f"restored evidence must require a fresh pending confirmation: {replacement_draft}")
        replacement_decision = post_json(
            f"{base_url}/confirmations/{replacement_draft_id}/decision",
            {"decision": "approve", "note": "Fresh action-time approval after evidence restoration."},
            token=token,
        )
        if replacement_decision.get("confirmation", {}).get("status") != "approved":
            return fail(f"replacement draft confirmation must be independently approved: {replacement_decision}")
        draft_execution = post_json(
            f"{base_url}/confirmations/{replacement_draft_id}/execute",
            {"platform": "ebay", "idempotency_key": "draft-intake-unit-fresh-bumper-replacement"},
            token=token,
        )
        stored_draft_execution = draft_execution.get("execution", {})
        if stored_draft_execution.get("status") != "simulated_no_platform_write":
            return fail(f"disabled staging boundary should simulate the draft handoff without eBay writes: {draft_execution}")
        draft_intent = stored_draft_execution.get("audit", {}).get("execution_intent", {})
        if draft_intent.get("platform_adapter") != "ebay.save_ebay_listing_draft":
            return fail(f"draft execution should preserve the dedicated adapter intent: {draft_intent}")
        if draft_intent.get("writes_to_ebay") is not True or draft_intent.get("creates_public_listing") is not False:
            return fail(f"draft intent must distinguish an external draft write from public publish: {draft_intent}")
        if draft_intent.get("requires_publish_offer_call") is not False:
            return fail(f"draft intent must explicitly prohibit publishOffer: {draft_intent}")
        with sqlite3.connect(SAAS_DB) as conn:
            completed_task_status = conn.execute(
                "select status from tasks where task_id = ?",
                (replacement_draft.get("task_id"),),
            ).fetchone()[0]
        if completed_task_status != "completed_no_platform_write":
            return fail(f"simulated draft task must close instead of remaining queued: {completed_task_status}")
        with sqlite3.connect(SAAS_DB) as conn:
            conn.execute(
                "update tasks set status = 'queued' where task_id = ?",
                (replacement_draft.get("task_id"),),
            )
        repository = SaaSRepository(SAAS_DB)
        dry_run = repository.reconcile_confirmation_managed_tasks(apply=False)
        if dry_run.get("candidate_count") != 1 or dry_run.get("provider_write_attempted") is not False:
            return fail(f"task reconciliation dry-run must be exact and value-free: {dry_run}")
        with sqlite3.connect(SAAS_DB) as conn:
            still_queued = conn.execute(
                "select status from tasks where task_id = ?",
                (replacement_draft.get("task_id"),),
            ).fetchone()[0]
        if still_queued != "queued":
            return fail("task reconciliation dry-run mutated data")
        applied = repository.reconcile_confirmation_managed_tasks(apply=True)
        if applied.get("transition_counts") != {"queued->completed": 1}:
            return fail(f"task reconciliation apply result is wrong: {applied}")
        print("PASS jiejing_publish_confirmation_intake")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def wait_for_health(base_url: str) -> int:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            fetch_json(f"{base_url}/health")
            return 0
        except Exception:
            time.sleep(0.2)
    return 1


def fetch_json(url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"HTTP {exc.code} for {url}: {detail}") from exc


def post_json_status(url: str, payload: dict[str, Any], *, token: str | None = None) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, json.loads(detail)


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


if __name__ == "__main__":
    raise SystemExit(main())
