#!/usr/bin/env python3
"""HTTP regression for the version-bound new-account publish/cleanup proof chain."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import api_server  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.commercial_launch_gate import (  # noqa: E402
    _build_current_store_new_account_action_evidence,
    build_commercial_launch_gate,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402


CONTRACT_VERSION = "2026-06-18-new-ebay-account-low-risk-smoke"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _post(base_url: str, path: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_status(base_url: str, path: str, payload: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    try:
        return 200, _post(base_url, path, payload, token)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def _publish_payload() -> dict[str, Any]:
    return {
        "workflow_scope": "new_ebay_account_low_risk_smoke",
        "idempotency_key": "new-account-smoke-publish-http-v1",
        "listing": {
            "sku": "SMOKE-001",
            "title": "New account smoke widget",
            "description_html": "<p>New account smoke widget.</p>",
            "category_id": "12345",
            "category_leaf": "Widgets",
            "condition": "NEW",
            "price": {"value": "1.00", "currency": "USD"},
            "quantity": 1,
            "item_specifics": {"Brand": "Jiejing", "Type": "Widget"},
            "merchant_location_key": "primary-location",
        },
        "business_policies": {
            "fulfillment_policy_id": "fulfillment-1",
            "payment_policy_id": "payment-1",
            "return_policy_id": "return-1",
        },
        "supplier_facts": {
            "package_weight_g": "100",
            "package_dimensions_cm": {"length": "10", "width": "5", "height": "2"},
            "material": "plastic",
            "item_location": "US",
        },
        "asset_manifest": {"assets": [{"url": "https://example.com/smoke.jpg"}]},
        "finance_review": {"net_profit_money": {"value": "0.25", "currency": "USD"}},
    }


class FakeWriteAdapter:
    """No-network adapter used only to exercise the real HTTP producer chain."""

    last_publish_payload: dict[str, Any] = {}
    last_cleanup_payload: dict[str, Any] = {}
    last_publish_platform = ""
    call_lock = threading.Lock()
    publish_call_count = 0
    cleanup_call_count = 0
    block_publish = False
    block_cleanup = False
    publish_started = threading.Event()
    cleanup_started = threading.Event()
    release_publish = threading.Event()
    release_cleanup = threading.Event()
    fail_publish = False
    fail_cleanup = False

    @classmethod
    def reset_control(cls) -> None:
        with cls.call_lock:
            cls.publish_call_count = 0
            cls.cleanup_call_count = 0
        cls.block_publish = False
        cls.block_cleanup = False
        cls.fail_publish = False
        cls.fail_cleanup = False
        cls.publish_started.clear()
        cls.cleanup_started.clear()
        cls.release_publish.clear()
        cls.release_cleanup.clear()

    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings

    def publish_listing(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> dict[str, Any]:
        with type(self).call_lock:
            type(self).publish_call_count += 1
        type(self).last_publish_payload = json.loads(json.dumps(request.payload))
        type(self).last_publish_platform = str(request.platform)
        type(self).publish_started.set()
        if type(self).block_publish:
            type(self).release_publish.wait(timeout=5)
        if type(self).fail_publish:
            raise RuntimeError("fake publish adapter failure sentinel")
        return {
            "status": "published_to_ebay",
            "action_type": "publish_listing",
            "task_id": request.task_id,
            "platform_result": {
                "listing_id": "listing-smoke-001",
                "offer_id": "offer-smoke-001",
                "sku": "SMOKE-001",
            },
            "audit": {
                "preflight": preflight,
                "real_execution": {
                    "published_to_ebay": True,
                    "cleanup_test_listing": False,
                },
            },
            "secret_exposed": False,
        }

    def inspect_publish_state(self, **_: Any) -> dict[str, Any]:
        return {
            "status": "publish_state_checked",
            "sku": "SMOKE-001",
            "published_offer": {"listing_id": "listing-smoke-001", "offer_id": "offer-smoke-001"},
            "cleanup_plan": {
                "status": "plan_only",
                "confirmation_required": True,
                "operations": [
                    {"operation": "withdraw_offer", "offer_id": "offer-smoke-001", "writes_to_ebay": True},
                    {"operation": "delete_offer", "offer_id": "offer-smoke-001", "writes_to_ebay": True},
                    {"operation": "delete_inventory_item", "sku": "SMOKE-001", "writes_to_ebay": True},
                ],
                "secret_exposed": False,
            },
            "secret_exposed": False,
        }

    def execute_cleanup_plan(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> dict[str, Any]:
        with type(self).call_lock:
            type(self).cleanup_call_count += 1
        type(self).last_cleanup_payload = json.loads(json.dumps(request.payload))
        type(self).cleanup_started.set()
        if type(self).block_cleanup:
            type(self).release_cleanup.wait(timeout=5)
        if type(self).fail_cleanup:
            raise RuntimeError("fake cleanup adapter failure sentinel")
        return {
            "status": "cleanup_completed",
            "action_type": "cleanup_test_listing",
            "task_id": request.task_id,
            "platform_result": {"sku": "SMOKE-001", "operation_count": 3},
            "audit": {
                "preflight": preflight,
                "real_execution": {
                    "published_to_ebay": False,
                    "cleanup_test_listing": True,
                },
            },
            "secret_exposed": False,
        }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jiejing-new-ebay-publish-http-", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        repo = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        account = repo.create_user_with_company(
            email="new-ebay-publish-http@example.com",
            password="Password123!",
            company_name="New eBay Publish HTTP",
        )
        user = account["user"]
        store = repo.create_store(
            company_id=user["default_company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "current new account", "marketplace": "EBAY_US"},
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        settings.environment = "staging"
        settings.requested_real_platform_writes = True
        settings.ebay_write_live_enabled = True
        settings.ebay_token_refresh_live_enabled = True
        sessions = SessionManager(secret="new-ebay-publish-http-secret")

        class TestHandler(SaaSBackendHandler):
            pass

        TestHandler.repository = repo
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.ebay_write_adapter_factory = FakeWriteAdapter
        original_health_builder = api_server.build_account_health_snapshot
        api_server.build_account_health_snapshot = lambda *_args, **kwargs: {
            "contract_version": "unit-current-store-health-v1",
            "company_id": kwargs["company_id"],
            "store_id": kwargs["store_id"],
            "status": "normal",
            "incident_mode": False,
            "can_execute_real_writes": True,
            "account_health": {"status": "normal"},
            "secret_exposed": False,
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(
            user_id=user["user_id"],
            company_id=user["default_company_id"],
            email=user["email"],
        )
        try:
            ordinary = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                {"listing": {"sku": "ORDINARY-001", "title": "Ordinary listing"}},
                token,
            )["confirmation"]
            ordinary_item = ordinary.get("item") if isinstance(ordinary.get("item"), dict) else {}
            if ordinary_item.get("source") == "new_ebay_account_low_risk_smoke":
                return fail("ordinary publish confirmation must never impersonate the new-account smoke contract")

            smoke_response = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                _publish_payload(),
                token,
            )
            smoke = smoke_response["confirmation"]
            item = smoke.get("item") if isinstance(smoke.get("item"), dict) else {}
            expected = {
                "source": "new_ebay_account_low_risk_smoke",
                "runbook_contract_version": CONTRACT_VERSION,
                "company_id": user["default_company_id"],
                "store_id": store["store_id"],
                "workflow_scope": "new_ebay_account_low_risk_smoke",
            }
            if any(item.get(key) != value for key, value in expected.items()):
                return fail("explicit smoke publish confirmation must persist the server-bound contract fields")
            if item.get("publish_health_ready") is not True:
                return fail("explicit smoke producer must persist publish-health readiness from the server preflight")

            approved_publish = _post(
                base_url,
                f"/confirmations/{smoke['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve exact new-account smoke publish."},
                token,
            )["confirmation"]
            if approved_publish.get("status") != "approved":
                return fail("HTTP decision center must approve the exact smoke publish confirmation")
            publish_execution = _post(
                base_url,
                f"/confirmations/{smoke['confirmation_id']}/execute",
                {
                    "idempotency_key": "new-account-smoke-publish-http-v1",
                    "platform": "attacker-platform",
                    "payload": {
                        "listing": {
                            "sku": "ATTACKER-SKU",
                            "title": "Attacker title",
                            "price": {"value": "99999.00", "currency": "USD"},
                        },
                        "store_id": "attacker-store",
                        "action_type": "refund",
                    },
                },
                token,
            )["execution"]
            if publish_execution.get("status") != "published_to_ebay":
                return fail("HTTP execute must reach the injected live publish adapter")
            if any(publish_execution.get(key) != value for key, value in expected.items() if key != "workflow_scope"):
                return fail("publish execution must persist the exact server-bound smoke contract")
            approved_payload = item.get("publish_payload") if isinstance(item.get("publish_payload"), dict) else {}
            if FakeWriteAdapter.last_publish_payload != approved_payload:
                return fail("execute body must not override the approved publish payload snapshot")
            if FakeWriteAdapter.last_publish_platform != "ebay":
                return fail("execute body must not override the approved store platform snapshot")

            cleanup_response = _post(
                base_url,
                f"/confirmations/{smoke['confirmation_id']}/publish-cleanup-plan",
                {},
                token,
            )
            cleanup = cleanup_response.get("cleanup_confirmation") or {}
            cleanup_item = cleanup.get("item") if isinstance(cleanup.get("item"), dict) else {}
            if cleanup_response.get("created") is not True or cleanup_item.get("source") != "new_ebay_account_low_risk_smoke":
                return fail("cleanup plan must inherit the exact verified smoke contract from its publish confirmation")
            approved_cleanup = _post(
                base_url,
                f"/confirmations/{cleanup['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve exact smoke cleanup."},
                token,
            )["confirmation"]
            if approved_cleanup.get("status") != "approved":
                return fail("HTTP decision center must approve the exact smoke cleanup confirmation")
            cleanup_execution = _post(
                base_url,
                f"/confirmations/{cleanup['confirmation_id']}/execute",
                {
                    "idempotency_key": "new-account-smoke-cleanup-http-v1",
                    "payload": {
                        "cleanup_plan": {
                            "confirmation_required": True,
                            "operations": [
                                {"operation": "delete_offer", "offer_id": "attacker-offer"}
                            ],
                        },
                        "store_id": "attacker-store",
                        "action_type": "publish_listing",
                    },
                },
                token,
            )["execution"]
            if cleanup_execution.get("status") != "cleanup_completed":
                return fail("HTTP execute must reach the cleanup adapter and persist terminal cleanup evidence")
            if FakeWriteAdapter.last_cleanup_payload != {"cleanup_plan": cleanup_item.get("cleanup_plan")}:
                return fail("execute body must not override the approved cleanup payload snapshot")

            evidence = _build_current_store_new_account_action_evidence(
                repository=repo,
                company_id=user["default_company_id"],
                store_id=store["store_id"],
            )
            if evidence.get("publish_health_confirmation_ready") is not True:
                return fail("real HTTP producer chain must make publish-health evidence ready")
            if evidence.get("controlled_real_publish_ready") is not True:
                return fail("real HTTP producer chain must make controlled publish evidence ready")
            if evidence.get("post_publish_cleanup_ready") is not True:
                return fail("real HTTP producer chain must make terminal cleanup evidence ready")
            commercial = build_commercial_launch_gate(
                settings,
                repo,
                company_id=user["default_company_id"],
                store_id=store["store_id"],
            )
            commercial_groups = {
                entry.get("key"): entry
                for entry in commercial.get("groups", [])
                if isinstance(entry, dict)
            }
            for key in ("publish_safety_system", "post_publish_cockpit", "new_ebay_account_low_risk_smoke"):
                if (commercial_groups.get(key) or {}).get("status") != "ready":
                    return fail(f"current-store HTTP action evidence must satisfy top-level commercial group: {key}")

            other_store = repo.create_store(
                company_id=user["default_company_id"],
                user_id=user["user_id"],
                payload={"platform": "ebay", "store_name": "wrong store", "marketplace": "EBAY_US"},
            )
            wrong_store = _build_current_store_new_account_action_evidence(
                repository=repo,
                company_id=user["default_company_id"],
                store_id=other_store["store_id"],
            )
            if any(
                wrong_store.get(key) is True
                for key in (
                    "publish_health_confirmation_ready",
                    "controlled_real_publish_ready",
                    "post_publish_cleanup_ready",
                )
            ):
                return fail("current-store consumer must reject a complete smoke chain owned by another store")

            original_item = dict(item)
            for field, bad_value in (
                ("runbook_contract_version", "wrong-contract-version"),
                ("source", "merchant_listing_publish_intake"),
            ):
                corrupted = {**original_item, field: bad_value}
                with sqlite3.connect(root / "saas.sqlite") as conn:
                    conn.execute(
                        "update confirmations set item_json = ? where confirmation_id = ?",
                        (json.dumps(corrupted, ensure_ascii=False), smoke["confirmation_id"]),
                    )
                blocked = _build_current_store_new_account_action_evidence(
                    repository=repo,
                    company_id=user["default_company_id"],
                    store_id=store["store_id"],
                )
                if blocked.get("controlled_real_publish_ready") is True:
                    return fail(f"consumer must reject current-store smoke evidence with wrong {field}")
                with sqlite3.connect(root / "saas.sqlite") as conn:
                    conn.execute(
                        "update confirmations set item_json = ? where confirmation_id = ?",
                        (json.dumps(original_item, ensure_ascii=False), smoke["confirmation_id"]),
                    )

            ordinary_complete_body = _publish_payload()
            ordinary_complete_body.pop("workflow_scope", None)
            ordinary_complete_body["idempotency_key"] = "ordinary-publish-intake-v1"
            ordinary_complete_body["listing"] = {
                **ordinary_complete_body["listing"],
                "sku": "ORDINARY-COMPLETE-001",
                "title": "Ordinary complete widget",
            }
            ordinary_complete = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                ordinary_complete_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{ordinary_complete['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve ordinary publish lifecycle regression."},
                token,
            )
            ordinary_execution = _post(
                base_url,
                f"/confirmations/{ordinary_complete['confirmation_id']}/execute",
                {"idempotency_key": "ordinary-publish-execute-v1"},
                token,
            )["execution"]
            ordinary_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=ordinary_complete["confirmation_id"],
            ) or {}
            if ordinary_execution.get("status") != "published_to_ebay" or ordinary_terminal.get("status") != "executed":
                return fail("successful claimed ordinary publish must atomically reach executed")
            ordinary_cleanup = _post(
                base_url,
                f"/confirmations/{ordinary_complete['confirmation_id']}/publish-cleanup-plan",
                {},
                token,
            )["cleanup_confirmation"]
            ordinary_cleanup_item = (
                ordinary_cleanup.get("item") if isinstance(ordinary_cleanup.get("item"), dict) else {}
            )
            if ordinary_cleanup_item.get("source") == "new_ebay_account_low_risk_smoke":
                return fail("ordinary cleanup must never impersonate the smoke evidence contract")
            _post(
                base_url,
                f"/confirmations/{ordinary_cleanup['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve ordinary cleanup lifecycle regression."},
                token,
            )
            ordinary_cleanup_execution = _post(
                base_url,
                f"/confirmations/{ordinary_cleanup['confirmation_id']}/execute",
                {"idempotency_key": "ordinary-cleanup-execute-v1"},
                token,
            )["execution"]
            ordinary_cleanup_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=ordinary_cleanup["confirmation_id"],
            ) or {}
            if (
                ordinary_cleanup_execution.get("status") != "cleanup_completed"
                or ordinary_cleanup_terminal.get("status") != "executed"
            ):
                return fail("successful claimed ordinary cleanup must atomically reach executed")

            FakeWriteAdapter.reset_control()
            concurrent_body = _publish_payload()
            concurrent_body["idempotency_key"] = "concurrent-publish-intake-v1"
            concurrent_body["listing"] = {
                **concurrent_body["listing"],
                "sku": "SMOKE-CONCURRENT-001",
                "title": "Concurrent smoke widget",
            }
            concurrent_publish = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                concurrent_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{concurrent_publish['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve concurrency regression."},
                token,
            )
            execute_path = f"/confirmations/{concurrent_publish['confirmation_id']}/execute"
            execute_body = {"idempotency_key": "concurrent-publish-execute-v1"}
            FakeWriteAdapter.block_publish = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(_post_status, base_url, execute_path, execute_body, token)
                if not FakeWriteAdapter.publish_started.wait(timeout=5):
                    return fail("first concurrent publish did not reach the fake adapter")
                second = pool.submit(_post_status, base_url, execute_path, execute_body, token)
                time.sleep(0.2)
                FakeWriteAdapter.release_publish.set()
                concurrent_results = [first.result(timeout=10), second.result(timeout=10)]
            if FakeWriteAdapter.publish_call_count != 1:
                return fail("concurrent execute must claim the confirmation before exactly one publish adapter call")
            if sorted(status for status, _payload in concurrent_results) != [200, 409]:
                return fail(f"concurrent publish execute must return one success and one 409: {concurrent_results}")
            concurrent_records = [
                record
                for record in repo.list_execution_results(company_id=user["default_company_id"], limit=200)
                if record.get("confirmation_id") == concurrent_publish["confirmation_id"]
            ]
            if len(concurrent_records) != 1:
                return fail("concurrent publish execute must persist exactly one execution result")

            FakeWriteAdapter.reset_control()
            failing_body = _publish_payload()
            failing_body["idempotency_key"] = "failed-publish-intake-v1"
            failing_body["listing"] = {
                **failing_body["listing"],
                "sku": "SMOKE-FAIL-001",
                "title": "Failed smoke widget",
            }
            failing_publish = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                failing_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{failing_publish['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve failure/manual-reconcile regression."},
                token,
            )
            FakeWriteAdapter.fail_publish = True
            failing_path = f"/confirmations/{failing_publish['confirmation_id']}/execute"
            failure_status, failure_payload = _post_status(
                base_url,
                failing_path,
                {"idempotency_key": "failed-publish-execute-v1"},
                token,
            )
            if failure_status != 409 or failure_payload.get("error") != "external_execution_processing_manual_reconcile":
                return fail("adapter exception must return a fixed manual-reconcile response")
            failed_confirmation = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=failing_publish["confirmation_id"],
            ) or {}
            if failed_confirmation.get("status") != "external_execution_processing_manual_reconcile":
                return fail("adapter exception must retain the durable manual-reconcile processing state")
            retry_status, _retry_payload = _post_status(
                base_url,
                failing_path,
                {"idempotency_key": "failed-publish-execute-v1"},
                token,
            )
            if retry_status != 409 or FakeWriteAdapter.publish_call_count != 1:
                return fail("an uncertain external publish must never be retried automatically")

            FakeWriteAdapter.reset_control()
            cleanup_source_body = _publish_payload()
            cleanup_source_body["idempotency_key"] = "concurrent-cleanup-source-v1"
            cleanup_source_body["listing"] = {
                **cleanup_source_body["listing"],
                "sku": "SMOKE-CLEANUP-CONCURRENT-001",
                "title": "Concurrent cleanup smoke widget",
            }
            cleanup_source = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                cleanup_source_body,
                token,
            )["confirmation"]
            concurrent_cleanup = _post(
                base_url,
                f"/confirmations/{cleanup_source['confirmation_id']}/publish-cleanup-plan",
                {},
                token,
            )["cleanup_confirmation"]
            _post(
                base_url,
                f"/confirmations/{concurrent_cleanup['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve concurrent cleanup regression."},
                token,
            )
            cleanup_execute_path = f"/confirmations/{concurrent_cleanup['confirmation_id']}/execute"
            cleanup_execute_body = {"idempotency_key": "concurrent-cleanup-execute-v1"}
            FakeWriteAdapter.block_cleanup = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                first_cleanup = pool.submit(
                    _post_status,
                    base_url,
                    cleanup_execute_path,
                    cleanup_execute_body,
                    token,
                )
                if not FakeWriteAdapter.cleanup_started.wait(timeout=5):
                    return fail("first concurrent cleanup did not reach the fake adapter")
                second_cleanup = pool.submit(
                    _post_status,
                    base_url,
                    cleanup_execute_path,
                    cleanup_execute_body,
                    token,
                )
                time.sleep(0.2)
                FakeWriteAdapter.release_cleanup.set()
                concurrent_cleanup_results = [
                    first_cleanup.result(timeout=10),
                    second_cleanup.result(timeout=10),
                ]
            if FakeWriteAdapter.cleanup_call_count != 1:
                return fail("concurrent cleanup execute must claim before exactly one cleanup adapter call")
            if sorted(status for status, _payload in concurrent_cleanup_results) != [200, 409]:
                return fail("concurrent cleanup execute must return one success and one 409")
            cleanup_records = [
                record
                for record in repo.list_execution_results(company_id=user["default_company_id"], limit=200)
                if record.get("confirmation_id") == concurrent_cleanup["confirmation_id"]
            ]
            if len(cleanup_records) != 1:
                return fail("concurrent cleanup execute must persist exactly one execution result")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            api_server.build_account_health_snapshot = original_health_builder
    print("PASS jiejing_new_ebay_account_publish_http_chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
