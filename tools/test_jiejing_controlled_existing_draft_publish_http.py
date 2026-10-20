#!/usr/bin/env python3
"""HTTP regression for one exact existing eBay Offer publish handoff."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jiejing_saas.api_server as api_server  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository, now_iso  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402
from jiejing_saas.ebay_execution_authority import scoped_credential, segment
from test_jiejing_new_ebay_account_publish_http_chain import _seed_exact_draft_callback


OFFER_ID = "245675556011"
SKU = "JJ-INCENSE-JC2023041300002-01"
SOURCE_EXECUTION_ID = "exec_exact_saved_draft_1"
LISTING_PROJECT_IDENTITY = {
    "key": "listing-project-controlled-incense",
    "source_report_id": "source-controlled-incense",
    "candidate_id": "candidate-controlled-incense",
}


def _post(base_url: str, path: str, payload: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), json.loads(raw) if raw else {}


def _get(base_url: str, path: str, token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), json.loads(raw) if raw else {}


def _task_status(base_url: str, token: str, task_id: str) -> str:
    status, body = _get(base_url, "/tasks?limit=100", token)
    if status != 200:
        raise AssertionError(f"task list failed while checking controlled publish state: {status} {body}")
    task = next((item for item in body.get("tasks") or [] if item.get("task_id") == task_id), None)
    if not task:
        raise AssertionError(f"controlled publish task is missing from the merchant task list: {task_id}")
    return str(task.get("status") or "")


def _publish_payload() -> dict[str, Any]:
    return {
        "account_health": {
            "status": "normal",
            "selling_status": "active",
            "payout_status": "available",
            "restrictions": [],
        },
        "listing": {
            "sku": SKU,
            "title": "Backflow Incense Burner with Lotus Flower and Hand Design",
            "description_html": "<p>Lotus and hand design backflow incense burner.</p>",
            "category_id": "20552",
            "condition": "NEW",
            "price": {"value": "29.99", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {
                "Brand": "Unbranded",
                "Type": "Backflow Incense Burner",
                "MPN": "Does Not Apply",
                "Style": "Asian",
            },
            "merchant_location_key": "shenzhen-warehouse",
        },
        "business_policies": {
            "fulfillment_policy_id": "252706512026",
            "payment_policy_id": "252706224026",
            "return_policy_id": "252706513026",
        },
        # These unknown internal/supplier facts are deliberately not invented.
        "supplier_facts": {"item_location": "shenzhen-warehouse"},
        "asset_manifest": {"assets": [{"url": "https://example.test/generated-approved.jpg"}]},
        "finance_review": {},
        "secret_exposed": False,
    }


class FakeExactPublishAdapter:
    exact_call_count = 0
    broad_call_count = 0
    fail_before_provider_once = False
    return_blocked_platform_once = False
    recovery_call_count = 0
    last_request: dict[str, Any] = {}

    def __init__(self, _settings: SaaSSettings) -> None:
        pass

    def publish_listing(self, **_kwargs: Any) -> dict[str, Any]:
        type(self).broad_call_count += 1
        raise AssertionError("controlled existing-draft flow must never call broad publish_listing")

    def publish_existing_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        credential_boundary: dict[str, Any],
        expected_offer_id: str,
        marketplace_id: str,
        execution_permit: Any,
    ) -> dict[str, Any]:
        type(self).exact_call_count += 1
        type(self).last_request = json.loads(json.dumps(request.payload))
        if type(self).fail_before_provider_once:
            type(self).fail_before_provider_once = False
            raise TypeError("simulated_pre_provider_adapter_contract_failure")
        execution_permit.admit(operation_index=0,method='POST',
            path='/sell/inventory/v1/offer/'+segment(expected_offer_id)+'/publish',body={},
            marketplace_id=marketplace_id,credential=scoped_credential(credential_boundary))
        if type(self).return_blocked_platform_once:
            type(self).return_blocked_platform_once = False
            execution_permit.record(operation_index=0,result={'status':'http_error','http_status':400,'json':{}})
            return {
                "status": "blocked_platform_error",
                "action_type": "publish_listing",
                "task_id": request.task_id,
                "message": "eBay rejected publishOffer before creating a public Listing.",
                "steps": [
                    {
                        "step": "inspect_existing_offer",
                        "status": "ok",
                        "http_status": 200,
                        "raw_response_stored": False,
                    },
                    {
                        "step": "publish_existing_offer",
                        "status": "http_error",
                        "http_status": 400,
                        "raw_response_stored": False,
                    },
                ],
                "audit": {
                    "preflight": preflight,
                    "real_execution": {
                        "published_to_ebay": False,
                        "public_listing_created": False,
                    },
                    "raw_response_stored": False,
                },
                "secret_exposed": False,
            }
        if preflight.get("status") != "ready_for_platform_adapter":
            raise AssertionError(f"exact publish adapter received blocked preflight: {preflight}")
        if credential_boundary.get("ready") is not True:
            raise AssertionError("exact publish adapter requires the backend credential boundary")
        if expected_offer_id != OFFER_ID or marketplace_id != "EBAY_US":
            raise AssertionError("exact publish adapter lost the Offer or marketplace binding")
        execution_permit.record(operation_index=0,result={'status':'ok','http_status':200,
            'json':{'listingId':'listing-controlled-http-001'}})
        return {
            "status": "published_to_ebay",
            "action_type": "publish_listing",
            "task_id": request.task_id,
            "platform_result": {
                "listing_id": "listing-controlled-http-001",
                "offer_id": OFFER_ID,
                "sku": SKU,
                "published_to_ebay": True,
                "public_listing_created": True,
            },
            "audit": {
                "preflight": preflight,
                "real_execution": {"published_to_ebay": True, "public_listing_created": True},
            },
            "secret_exposed": False,
        }

    def inspect_publish_state(
        self,
        *,
        request: Any,
        connections: list[dict[str, Any]],
        secret_refs: list[dict[str, Any]],
        marketplace_id: str,
    ) -> dict[str, Any]:
        del connections, secret_refs
        type(self).recovery_call_count += 1
        return {
            "status": "publish_state_checked",
            "action_type": "publish_listing",
            "sku": request.payload["listing"]["sku"],
            "inventory_item_found": True,
            "offer_count": 1,
            "published_offer": {},
            "exact_unpublished_offer": {
                "offer_id": OFFER_ID,
                "listing_status": "UNPUBLISHED",
                "marketplace_id": marketplace_id,
            },
            "safe_to_retry_publish": False,
            "safe_to_request_fresh_confirmation": True,
            "recommended_action": "request_fresh_exact_offer_confirmation",
            "checks": [],
            "secret_exposed": False,
        }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jiejing-controlled-publish-http-", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        repository = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        account = repository.create_user_with_company(
            email="controlled-publish-owner@example.com",
            password="Password123!",
            company_name="Controlled publish fixture",
        )
        user = account["user"]
        company_id = user["default_company_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Exact draft fixture", "marketplace": "EBAY_US"},
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        settings.environment = "production"
        settings.requested_real_platform_writes = False
        settings.ebay_write_live_enabled = False
        settings.ebay_draft_save_live_enabled = True
        settings.ebay_controlled_publish_live_enabled = True
        settings.ebay_token_refresh_live_enabled = True
        settings.ebay_read_only_live_enabled = True
        if settings.effective_real_platform_writes_enabled is not False:
            raise AssertionError("test fixture must keep broad real writes disabled")
        if settings.effective_ebay_controlled_publish_enabled is not True:
            raise AssertionError("test fixture must enable only the controlled existing-draft lane")
        sessions = SessionManager(secret="controlled-publish-http-session-secret")

        class TestHandler(SaaSBackendHandler):
            pass

        TestHandler.repository = repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.ebay_write_adapter_factory = FakeExactPublishAdapter
        original_health_builder = api_server.build_account_health_snapshot
        api_server.build_account_health_snapshot = lambda *_args, **kwargs: {
            "contract_version": "controlled-publish-http-health-v1",
            "company_id": kwargs["company_id"],
            "store_id": kwargs["store_id"],
            "status": "normal",
            "selling_status": "active",
            "payout_status": "available",
            "restrictions": [],
            "can_execute_real_writes": True,
            "account_health": {
                "status": "normal",
                "selling_status": "active",
                "payout_status": "available",
                "restrictions": [],
            },
            "secret_exposed": False,
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(user_id=user["user_id"], company_id=company_id, email=user["email"],
            access_epochs=repository.access_session_epochs(user_id=user['user_id'],company_id=company_id))
        intake_path = f"/stores/{store['store_id']}/existing-draft-publish-confirmation"
        intake_body = {"offer_id": OFFER_ID, "sku": SKU, "execution_id": SOURCE_EXECUTION_ID}
        def seed_saved_draft(store, source_execution_id):
            _seed_exact_draft_callback(settings,repository,company_id=company_id,store_id=store['store_id'],user_id=user['user_id'])
            product_facts_status, product_facts = _post(
                base_url,
                f"/stores/{store['store_id']}/product-facts",
                {
                    "listing_project_identity": LISTING_PROJECT_IDENTITY,
                    "merchant_product_fact_packet": {
                        "merchant_confirmed_facts": {
                            "product_name": "Backflow incense burner with lotus flower and hand design",
                            "source_url": "https://supplier.example.test/controlled-incense-burner",
                            "sku": SKU,
                            "condition": "NEW",
                            "material": "Resin",
                            "package_weight_g": "451",
                            "package_length_cm": "18",
                            "package_width_cm": "17",
                            "package_height_cm": "17",
                            "unit_cost": "9.00",
                            "selling_price": "29.99",
                            "currency": "USD",
                            "quantity": "1",
                            "item_location": "shenzhen-warehouse",
                            "image_urls": "https://example.test/generated-approved.jpg",
                            "image_rights_confirmed": True,
                        }
                    },
                },
                token,
            )
            product_fact_report_id = str((product_facts.get("report") or {}).get("report_id") or "")
            if product_facts_status != 201 or not product_fact_report_id:
                raise AssertionError(
                    f"controlled draft fixture must save authoritative merchant product facts: "
                    f"{product_facts_status} {product_facts}"
                )

            source_draft_body = {
                "product": "Backflow incense burner with lotus flower and hand design",
                "listing_project_identity": LISTING_PROJECT_IDENTITY,
                **_publish_payload(),
                "publish_evidence_refs": {"product_fact_report_id": product_fact_report_id},
            }
            source_status, source_draft = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                source_draft_body,
                token,
            )
            source_confirmation = source_draft.get("confirmation") or {}
            source_publish_evidence = (
                (source_confirmation.get("item") or {}).get("publish_payload") or {}
            ).get("publish_evidence") or {}
            if not (
                source_status == 201
                and source_confirmation.get("action_type") == "save_ebay_listing_draft"
                and source_publish_evidence.get("server_resolved") is True
                and (source_publish_evidence.get("refs") or {}).get("product_fact_report_id")
                == product_fact_report_id
            ):
                raise AssertionError(
                    "controlled draft fixture must cross the API source/rights evidence gate before execution: "
                    f"{source_status} {source_draft}"
                )

            source_task_id = str(source_confirmation.get("task_id") or "")
            result = {
                "status": "saved_to_ebay_draft",
                "action_type": "save_ebay_listing_draft",
                "task_id": source_task_id,
                "platform_result": {
                    "offer_id": OFFER_ID,
                    "offer_status": "UNPUBLISHED",
                    "sku": SKU,
                    "writes_to_ebay": True,
                    "published_to_ebay": False,
                    "public_listing_created": False,
                },
                "secret_exposed": False,
            }
            with repository._connect() as conn:  # noqa: SLF001 - exact executed-draft fixture
                conn.execute(
                    "update confirmations set status = 'executed' where confirmation_id = ?",
                    (source_confirmation["confirmation_id"],),
                )
                conn.execute("update tasks set status = 'completed' where task_id = ?", (source_task_id,))
                conn.execute(
                    """
                    insert into execution_results (
                      execution_id, confirmation_id, task_id, action_type, status, created_at, result_json
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_execution_id,
                        source_confirmation["confirmation_id"],
                        source_task_id,
                        "save_ebay_listing_draft",
                        "saved_to_ebay_draft",
                        now_iso(),
                        json.dumps(result),
                    ),
                )

        try:
            seed_saved_draft(store,SOURCE_EXECUTION_ID)

            with ThreadPoolExecutor(max_workers=2) as pool:
                intake_results = list(pool.map(lambda _index: _post(base_url, intake_path, intake_body, token), range(2)))
            if any(status not in {200, 201} for status, _body in intake_results):
                raise AssertionError(f"exact duplicate intake returned unexpected statuses: {intake_results}")
            ids = {
                str((body.get("confirmation") or {}).get("confirmation_id") or "")
                for _status, body in intake_results
            }
            if len(ids) != 1 or not next(iter(ids)):
                raise AssertionError(f"duplicate exact intake must return one confirmation: {intake_results}")
            controlled = next(iter(intake_results))[1]
            confirmation = controlled.get("confirmation") or {}
            if controlled.get("preflight", {}).get("status") != "ready_for_confirmation":
                raise AssertionError(f"disclosed supplier/profit gaps must not block confirmation: {controlled}")
            disclosed = set(controlled.get("preflight", {}).get("disclosed_missing_facts") or [])
            if "supplier_facts.material" not in disclosed or "finance_review.net_profit_money" not in disclosed:
                raise AssertionError(f"controlled intake lost merchant-facing warnings: {controlled}")
            matching = [
                item
                for item in repository.list_confirmations(company_id=company_id, limit=100)
                if (item.get("item") or {}).get("controlled_existing_draft_publish") is True
            ]
            if len(matching) != 1:
                raise AssertionError(f"duplicate clicks must persist exactly one controlled confirmation: {matching}")

            confirmation_id = confirmation["confirmation_id"]
            approval_status, approval = _post(
                base_url,
                f"/confirmations/{confirmation_id}/decision",
                {"decision": "approve", "note": "Approve exact existing Offer fixture."},
                token,
            )
            if approval_status != 201 or (approval.get("confirmation") or {}).get("status") != "approved":
                raise AssertionError(f"exact controlled approval failed: {approval_status} {approval}")
            if _task_status(base_url, token, confirmation["task_id"]) != "approved_waiting_execution":
                raise AssertionError("approved existing-draft publish task must leave queued state")
            preflight_status, preflight = _post(
                base_url,
                f"/confirmations/{confirmation_id}/preflight",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-001"},
                token,
            )
            if preflight_status != 201 or preflight.get("preflight", {}).get("status") != "ready_for_platform_adapter":
                raise AssertionError(f"approved exact Offer must pass controlled preflight: {preflight_status} {preflight}")
            if not (
                preflight.get("publish_readiness", {}).get("status") == "ready_for_platform_adapter"
                and preflight.get("publish_readiness", {}).get("ready_for_platform_adapter") is True
            ):
                raise AssertionError(f"approved readiness must agree with the controlled preflight: {preflight}")
            FakeExactPublishAdapter.fail_before_provider_once = True
            failed_status, failed_execution = _post(
                base_url,
                f"/confirmations/{confirmation_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-001"},
                token,
            )
            if failed_status != 409 or failed_execution.get('execution_recovery',{}).get('zero_write_proven') is not True:
                raise AssertionError(f"pre-provider failure must use durable zero-write recovery: {failed_status} {failed_execution}")
            with repository._connect() as conn:
                zero_row=dict(conn.execute('select * from confirmation_execution_authorities_v1 where confirmation_id=?',(confirmation_id,)).fetchone())
            zero_graph=json.loads(zero_row['operation_state_json'])
            if zero_row['admitted_at'] is not None or not all(op['status']=='planned' for op in zero_graph['operations']):
                raise AssertionError('pre-provider recovery cannot rely on an exception label')
            zero_confirmation=repository.get_confirmation(company_id=company_id,confirmation_id=confirmation_id)
            for field in ('item','decided_at','decided_by','decision_note'):
                if zero_confirmation[field]!=approval['confirmation'][field]: raise AssertionError('zero retirement changed approval history')
            recovery_status, recovery = _post(
                base_url,
                f"/confirmations/{confirmation_id}/publish-recovery",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-recovery-001"},
                token,
            )
            if not (
                recovery_status == 201
                and recovery.get("fresh_confirmation_required") is True
                and recovery.get("publish_recovery", {}).get("safe_to_request_fresh_confirmation") is True
                and recovery.get("confirmation", {}).get("status") == "needs_revision"
                and recovery.get("publish_readiness", {}).get("status") == "ready_for_confirmation"
                and recovery.get("publish_readiness", {}).get("ready_for_confirmation") is True
                and FakeExactPublishAdapter.recovery_call_count == 1
            ):
                raise AssertionError(f"read-only recovery must project the already retired durable zero: {recovery_status} {recovery}")
            if _task_status(base_url, token, confirmation["task_id"]) != "needs_revision":
                raise AssertionError("verified no-op recovery must retire the controlled publish task for revision")
            replacement_status, replacement = _post(base_url, intake_path,{**intake_body,'replaces_confirmation_id':confirmation_id}, token)
            replacement_confirmation = replacement.get("confirmation") or {}
            replacement_id = str(replacement_confirmation.get("confirmation_id") or "")
            if not (
                replacement_status == 201
                and replacement_id
                and replacement_id != confirmation_id
                and replacement_confirmation.get("status") == "pending"
            ):
                raise AssertionError(f"reconciled no-op must require one fresh confirmation: {replacement_status} {replacement}")
            replacement_approval_status, replacement_approval = _post(
                base_url,
                f"/confirmations/{replacement_id}/decision",
                {"decision": "approve", "note": "Approve exact existing Offer after verified no-op recovery."},
                token,
            )
            if replacement_approval_status != 201 or (replacement_approval.get("confirmation") or {}).get("status") != "approved":
                raise AssertionError(f"replacement exact approval failed: {replacement_approval_status} {replacement_approval}")
            replacement_preflight_status, replacement_preflight = _post(
                base_url,
                f"/confirmations/{replacement_id}/preflight",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-002"},
                token,
            )
            if replacement_preflight_status != 201 or replacement_preflight.get("preflight", {}).get("status") != "ready_for_platform_adapter":
                raise AssertionError(f"replacement exact Offer must pass preflight: {replacement_preflight_status} {replacement_preflight}")
            FakeExactPublishAdapter.return_blocked_platform_once = True
            blocked_status, blocked_execution = _post(
                base_url,
                f"/confirmations/{replacement_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-002"},
                token,
            )
            blocked_stored = blocked_execution.get("execution") or {}
            if blocked_status != 201 or blocked_stored.get("status") != "blocked_platform_error":
                raise AssertionError(f"provider rejection must be recorded without claiming success: {blocked_status} {blocked_execution}")
            recorded_recovery_status, recorded_recovery = _post(
                base_url,
                f"/confirmations/{replacement_id}/publish-recovery",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-recovery-002"},
                token,
            )
            if not (
                recorded_recovery_status == 201
                and recorded_recovery.get("fresh_confirmation_required") is False
                and recorded_recovery.get("publish_recovery", {}).get("safe_to_request_fresh_confirmation") is False
                and recorded_recovery.get("confirmation", {}).get("status") == "external_execution_processing_manual_reconcile"
                and recorded_recovery.get('execution_recovery',{}).get('zero_write_proven') is False
                and recorded_recovery.get('execution_recovery',{}).get('automatic_retry_allowed') is False
            ):
                raise AssertionError(
                    "a GET showing UNPUBLISHED must not retire or replay an admitted HTTP400 outcome: "
                    f"{recorded_recovery_status} {recorded_recovery}"
                )
            if _task_status(base_url, token, replacement_confirmation["task_id"]) != "manual_reconcile_required":
                raise AssertionError("admitted provider uncertainty must leave the controlled task in reconciliation")
            with sqlite3.connect(root / "saas.sqlite") as conn:
                conn.execute(
                    "update tasks set status = 'queued' where task_id = ?",
                    (replacement_confirmation["task_id"],),
                )
            stale_failed_publish = repository.reconcile_confirmation_managed_tasks(
                apply=False,
                company_id=company_id,
            )
            failed_publish_change = next(
                (
                    item
                    for item in stale_failed_publish.get("changes") or []
                    if item.get("task_id") == replacement_confirmation["task_id"]
                ),
                None,
            )
            if not failed_publish_change or failed_publish_change.get("to_status") != "manual_reconcile_required":
                raise AssertionError(
                    "reconciliation must not mistake a recorded provider rejection for a completed publish: "
                    f"{stale_failed_publish}"
                )
            repository.reconcile_confirmation_managed_tasks(apply=True, company_id=company_id)
            if _task_status(base_url, token, replacement_confirmation["task_id"]) != "manual_reconcile_required":
                raise AssertionError("task reconciliation must not unlock the unknown provider outcome")
            blocked_retry_status,_=_post(base_url,intake_path,{**intake_body,'replaces_confirmation_id':replacement_id},token)
            if blocked_retry_status!=409 or FakeExactPublishAdapter.exact_call_count!=2:
                raise AssertionError('a new confirmation ID cannot replay the unresolved same Offer')
            control_store=repository.create_store(company_id=company_id,user_id=user['user_id'],
                payload={'platform':'ebay','store_name':'Independent positive control','marketplace':'EBAY_US'})
            seed_saved_draft(control_store,SOURCE_EXECUTION_ID+'-independent')
            final_intake_status, final_intake = _post(base_url,
                f"/stores/{control_store['store_id']}/existing-draft-publish-confirmation",
                {**intake_body,'execution_id':SOURCE_EXECUTION_ID+'-independent'},token)
            final_confirmation = final_intake.get("confirmation") or {}
            final_confirmation_id = str(final_confirmation.get("confirmation_id") or "")
            if not (
                final_intake_status == 201
                and final_confirmation_id
                and final_confirmation_id not in {confirmation_id, replacement_id}
                and final_confirmation.get("status") == "pending"
            ):
                raise AssertionError(f"independent valid resource must still get a new pending confirmation: {final_intake_status} {final_intake}")
            final_approval_status, final_approval = _post(
                base_url,
                f"/confirmations/{final_confirmation_id}/decision",
                {"decision": "approve", "note": "Approve exact existing Offer after recorded provider rejection."},
                token,
            )
            if final_approval_status != 201 or (final_approval.get("confirmation") or {}).get("status") != "approved":
                raise AssertionError(f"final exact approval failed: {final_approval_status} {final_approval}")
            final_preflight_status, final_preflight = _post(
                base_url,
                f"/confirmations/{final_confirmation_id}/preflight",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-003"},
                token,
            )
            if final_preflight_status != 201 or final_preflight.get("preflight", {}).get("status") != "ready_for_platform_adapter":
                raise AssertionError(f"final exact Offer must pass preflight: {final_preflight_status} {final_preflight}")
            execute_status, execution = _post(
                base_url,
                f"/confirmations/{final_confirmation_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-003"},
                token,
            )
            stored = execution.get("execution") or {}
            if execute_status != 201 or stored.get("status") != "published_to_ebay":
                raise AssertionError(f"exact existing Offer did not reach its dedicated adapter: {execute_status} {execution}")
            if FakeExactPublishAdapter.exact_call_count != 3 or FakeExactPublishAdapter.broad_call_count != 0:
                raise AssertionError("controlled HTTP route must isolate failures and publish only after a fresh approval")
            if FakeExactPublishAdapter.last_request.get("existing_ebay_draft", {}).get("offer_id") != OFFER_ID:
                raise AssertionError("controlled HTTP route changed the approved existing Offer binding")
            stored_final_confirmation = repository.get_confirmation(company_id=company_id, confirmation_id=final_confirmation_id) or {}
            if stored_final_confirmation.get("status") != "executed":
                raise AssertionError(f"successful public publish must close its confirmation: {stored_final_confirmation}")
            if _task_status(base_url, token, final_confirmation["task_id"]) != "completed":
                raise AssertionError("successful controlled publish must complete its merchant task")
            repeat_status, _repeat = _post(
                base_url,
                f"/confirmations/{final_confirmation_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-003"},
                token,
            )
            if repeat_status != 409 or FakeExactPublishAdapter.exact_call_count != 3:
                raise AssertionError("a repeated execute must fail before a second publishOffer call")
            print("PASS jiejing_controlled_existing_draft_publish_http")
            return 0
        finally:
            api_server.build_account_health_snapshot = original_health_builder
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
