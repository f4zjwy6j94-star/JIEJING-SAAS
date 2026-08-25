#!/usr/bin/env python3
"""HTTP regression for one exact existing eBay Offer publish handoff."""

from __future__ import annotations

import json
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


OFFER_ID = "245675556011"
SKU = "JJ-INCENSE-JC2023041300002-01"
SOURCE_EXECUTION_ID = "exec_exact_saved_draft_1"


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
        **_kwargs: Any,
    ) -> dict[str, Any]:
        type(self).exact_call_count += 1
        type(self).last_request = json.loads(json.dumps(request.payload))
        if preflight.get("status") != "ready_for_platform_adapter":
            raise AssertionError(f"exact publish adapter received blocked preflight: {preflight}")
        if credential_boundary.get("ready") is not True:
            raise AssertionError("exact publish adapter requires the backend credential boundary")
        if expected_offer_id != OFFER_ID or marketplace_id != "EBAY_US":
            raise AssertionError("exact publish adapter lost the Offer or marketplace binding")
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
        source_task = repository.create_task(
            company_id=company_id,
            store_id=store["store_id"],
            user_id=user["user_id"],
            task_type="ebay_draft_save_intake",
            title="Saved exact eBay draft fixture",
            input_data={"secret_exposed": False},
        )
        source_confirmation = repository.create_confirmation(
            company_id=company_id,
            store_id=store["store_id"],
            task_id=source_task["task_id"],
            runtime_run_id="merchant_ebay_draft_save_intake",
            action_type="save_ebay_listing_draft",
            title="Saved exact eBay draft fixture",
            item={"publish_payload": _publish_payload(), "secret_exposed": False},
            created_by=user["user_id"],
        )
        result = {
            "status": "saved_to_ebay_draft",
            "action_type": "save_ebay_listing_draft",
            "task_id": source_task["task_id"],
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
        with repository._connect() as conn:  # noqa: SLF001 - exact repository fixture
            conn.execute(
                "update confirmations set status = 'executed' where confirmation_id = ?",
                (source_confirmation["confirmation_id"],),
            )
            conn.execute("update tasks set status = 'completed' where task_id = ?", (source_task["task_id"],))
            conn.execute(
                """
                insert into execution_results (
                  execution_id, confirmation_id, task_id, action_type, status, created_at, result_json
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    SOURCE_EXECUTION_ID,
                    source_confirmation["confirmation_id"],
                    source_task["task_id"],
                    "save_ebay_listing_draft",
                    "saved_to_ebay_draft",
                    now_iso(),
                    json.dumps(result),
                ),
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
        repository.unpublished_draft_execution_credential_boundary = lambda **_kwargs: {  # type: ignore[method-assign]
            "ready": True,
            "secret_exposed": False,
        }
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
            "secret_exposed": False,
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(user_id=user["user_id"], company_id=company_id, email=user["email"])
        intake_path = f"/stores/{store['store_id']}/existing-draft-publish-confirmation"
        intake_body = {"offer_id": OFFER_ID, "sku": SKU, "execution_id": SOURCE_EXECUTION_ID}
        try:
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
            execute_status, execution = _post(
                base_url,
                f"/confirmations/{confirmation_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-001"},
                token,
            )
            stored = execution.get("execution") or {}
            if execute_status != 201 or stored.get("status") != "published_to_ebay":
                raise AssertionError(f"exact existing Offer did not reach its dedicated adapter: {execute_status} {execution}")
            if FakeExactPublishAdapter.exact_call_count != 1 or FakeExactPublishAdapter.broad_call_count != 0:
                raise AssertionError("controlled HTTP route must call only publish_existing_listing_draft exactly once")
            if FakeExactPublishAdapter.last_request.get("existing_ebay_draft", {}).get("offer_id") != OFFER_ID:
                raise AssertionError("controlled HTTP route changed the approved existing Offer binding")
            final_confirmation = repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id) or {}
            if final_confirmation.get("status") != "executed":
                raise AssertionError(f"successful public publish must close its confirmation: {final_confirmation}")
            repeat_status, _repeat = _post(
                base_url,
                f"/confirmations/{confirmation_id}/execute",
                {"platform": "ebay", "idempotency_key": "controlled-publish-http-001"},
                token,
            )
            if repeat_status != 409 or FakeExactPublishAdapter.exact_call_count != 1:
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
