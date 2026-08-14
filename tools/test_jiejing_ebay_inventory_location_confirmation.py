#!/usr/bin/env python3
"""Public HTTP contract for confirmation-gated eBay inventory locations."""

from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402


ACTION = "create_ebay_inventory_location"
SOURCE = "merchant_ebay_inventory_location_setup"
STEP = "inventory_location_confirmation_gate"


def _post(base_url: str, path: str, payload: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def _location_payload() -> dict[str, Any]:
    return {
        "merchant_location_key": "shenzhen-warehouse",
        "name": "Shenzhen Warehouse",
        "location_types": ["WAREHOUSE"],
        "address": {
            "city": "Shenzhen",
            "state_or_province": "Guangdong",
            "country": "CN",
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jiejing-ebay-location-confirmation-", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        repository = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        account = repository.create_user_with_company(
            email="inventory-location-owner@example.com",
            password="Password123!",
            company_name="Inventory location fixture",
        )
        user = account["user"]
        company_id = user["default_company_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Location fixture", "marketplace": "EBAY_US"},
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        sessions = SessionManager(secret="inventory-location-session-secret")

        class TestHandler(SaaSBackendHandler):
            pass

        class FakeInventoryLocationAdapter:
            class Handle:
                def __init__(self, confirmation: dict[str, Any], *, bad_binding: bool = False) -> None:
                    self.confirmation = confirmation
                    self.bad_binding = bad_binding

                def claim_binding(self) -> dict[str, str]:
                    payload = (self.confirmation.get("item") or {}).get("location_payload") or {}
                    digest = hashlib.sha256(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    return {
                        "action_type": ACTION,
                        "company_id": str(self.confirmation.get("company_id") or ""),
                        "store_id": str(self.confirmation.get("store_id") or ""),
                        "confirmation_id": str(self.confirmation.get("confirmation_id") or ""),
                        "task_id": str(self.confirmation.get("task_id") or ""),
                        "marketplace_id": "EBAY_US",
                        "payload_sha256": digest,
                        "connection_id_sha256": ("9" if self.bad_binding else "1") * 64,
                        "credential_ref_sha256": "2" * 64,
                        "oauth_request_id_sha256": "3" * 64,
                        "seller_identity_sha256": "4" * 64,
                    }

            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []
                self.reconcile_calls: list[dict[str, Any]] = []
                self.prepare_mode = "ready"
                self.execute_mode = "success"

            def prepare_inventory_location(
                self,
                *,
                confirmation: dict[str, Any],
                location_payload: dict[str, Any],
                credential_boundary: dict[str, Any],
                marketplace_id: str,
            ) -> Any:
                del location_payload, credential_boundary, marketplace_id
                if confirmation.get("status") != "approved":
                    return {"status": "inventory_location_approval_invalid", "secret_exposed": False}
                if self.prepare_mode == "blocked":
                    return {"status": "inventory_location_preflight_blocked", "secret_exposed": False}
                return self.Handle(confirmation, bad_binding=self.prepare_mode == "bad_binding")

            def discard_inventory_location_preparation(self, prepared: Any) -> None:
                del prepared

            def execute_prepared_inventory_location(
                self,
                *,
                confirmation: dict[str, Any],
                prepared: Any,
                marketplace_id: str,
            ) -> dict[str, Any]:
                del prepared, marketplace_id
                location_payload = (confirmation.get("item") or {}).get("location_payload") or {}
                self.calls.append(
                    {
                        "confirmation_id": confirmation.get("confirmation_id"),
                        "location_payload": location_payload,
                    }
                )
                if self.execute_mode == "manual_reconcile":
                    return {
                        "status": "inventory_location_manual_reconcile",
                        "action_type": ACTION,
                        "task_id": confirmation.get("task_id"),
                        "automatic_retry_allowed": False,
                        "location_write_completed": False,
                        "public_listing_created": False,
                        "secret_exposed": False,
                    }
                return {
                    "status": "inventory_location_created",
                    "action_type": ACTION,
                    "task_id": confirmation.get("task_id"),
                    "merchant_location_key": location_payload.get("merchantLocationKey"),
                    "location_write_completed": True,
                    "public_listing_created": False,
                    "secret_exposed": False,
                    "audit": {
                        "real_execution": {
                            "inventory_location_created": True,
                            "published_to_ebay": False,
                        }
                    },
                }

            def reconcile_inventory_location(
                self,
                *,
                confirmation: dict[str, Any],
                location_payload: dict[str, Any],
                credential_boundary: dict[str, Any],
                marketplace_id: str,
            ) -> dict[str, Any]:
                del credential_boundary, marketplace_id
                if confirmation.get("status") != "external_execution_processing_manual_reconcile":
                    return {
                        "status": "inventory_location_reconcile_confirmation_invalid",
                        "automatic_retry_allowed": False,
                        "writes_to_ebay": False,
                        "public_listing_created": False,
                        "secret_exposed": False,
                    }
                self.reconcile_calls.append(
                    {
                        "confirmation_id": confirmation.get("confirmation_id"),
                        "location_payload": location_payload,
                    }
                )
                return {
                    "status": "inventory_location_created",
                    "action_type": ACTION,
                    "task_id": confirmation.get("task_id"),
                    "merchant_location_key": location_payload.get("merchantLocationKey"),
                    "location_write_completed": True,
                    "reconciled_from_provider_read": True,
                    "writes_to_ebay": False,
                    "public_listing_created": False,
                    "secret_exposed": False,
                    "audit": {
                        "real_execution": {
                            "inventory_location_created": True,
                            "reconciled_from_provider_read": True,
                            "published_to_ebay": False,
                        }
                    },
                }

        TestHandler.repository = repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        adapter = FakeInventoryLocationAdapter()
        TestHandler.ebay_write_adapter = adapter
        repository._unpublished_draft_execution_credential_boundary_conn = (  # type: ignore[method-assign] # noqa: SLF001
            lambda _conn, **_kwargs: {
                "ready": True,
                "connection_id_sha256": "1" * 64,
                "credential_ref_sha256": "2" * 64,
                "oauth_request_id_sha256": "3" * 64,
                "seller_identity_sha256": "4" * 64,
                "secret_exposed": False,
            }
        )

        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(user_id=user["user_id"], company_id=company_id, email=user["email"])
        try:
            viewer_account = repository.create_user_with_company(
                email="inventory-location-viewer@example.com",
                password="Password123!",
                company_name="Inventory location viewer fixture",
            )
            viewer_user = viewer_account["user"]
            repository.create_team_invitation(
                company_id=company_id,
                invited_by=user["user_id"],
                email=viewer_user["email"],
                role="viewer",
            )
            viewer_token = sessions.create_token(
                user_id=viewer_user["user_id"],
                company_id=company_id,
                email=viewer_user["email"],
            )
            viewer_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-inventory-location/confirmation",
                _location_payload(),
                viewer_token,
            )
            if viewer_status != 403:
                raise AssertionError("a viewer must not create an inventory-location confirmation")

            malformed_payloads = [
                {},
                {**_location_payload(), "merchant_location_key": ""},
                {**_location_payload(), "name": ""},
                {**_location_payload(), "location_types": ["STORE"]},
                {**_location_payload(), "address": {"city": "", "state_or_province": "Guangdong", "country": "CN"}},
                {**_location_payload(), "address": {"city": "Shenzhen", "state_or_province": "", "country": "CN"}},
                {**_location_payload(), "address": {"city": "Shenzhen", "state_or_province": "Guangdong", "country": "CHN"}},
            ]
            for malformed in malformed_payloads:
                malformed_status, _ = _post(
                    base_url,
                    f"/stores/{store['store_id']}/ebay-inventory-location/confirmation",
                    malformed,
                    token,
                )
                if malformed_status != 400:
                    raise AssertionError("malformed inventory-location input must fail before creating a confirmation")
            if repository.list_confirmations(company_id=company_id, limit=100):
                raise AssertionError("permission and malformed-input attacks must create zero confirmations")

            before = repository.list_confirmations(company_id=company_id, limit=100)
            with ThreadPoolExecutor(max_workers=4) as pool:
                intake_results = list(
                    pool.map(
                        lambda _index: _post(
                            base_url,
                            f"/stores/{store['store_id']}/ebay-inventory-location/confirmation",
                            _location_payload(),
                            token,
                        ),
                        range(4),
                    )
                )
            statuses = sorted(status for status, _body in intake_results)
            if statuses != [201, 409, 409, 409]:
                raise AssertionError(
                    "concurrent exact inventory-location intake must create one active confirmation; "
                    f"statuses={statuses}"
                )
            status, body = next(result for result in intake_results if result[0] == 201)
            confirmation = body.get("inventory_location_confirmation") or {}
            if status != 201:
                raise AssertionError(f"inventory-location intake must create a pending confirmation; status={status}")
            if not (
                confirmation.get("status") == "pending"
                and confirmation.get("company_id") == company_id
                and confirmation.get("store_id") == store["store_id"]
                and confirmation.get("action_type") == ACTION
                and confirmation.get("source") == SOURCE
                and confirmation.get("requested_step") == STEP
                and confirmation.get("merchant_location_key") == "shenzhen-warehouse"
                and confirmation.get("location_write_started") is False
                and confirmation.get("public_listing_created") is False
                and confirmation.get("secret_exposed") is False
            ):
                raise AssertionError("inventory-location intake must return the exact value-free pending contract")
            after = repository.list_confirmations(company_id=company_id, limit=100)
            if len(after) != len(before) + 1:
                raise AssertionError("inventory-location intake must create exactly one confirmation")
            stored = repository.get_confirmation(
                company_id=company_id,
                confirmation_id=str(confirmation.get("confirmation_id") or ""),
            )
            item = stored.get("item") if isinstance(stored, dict) else {}
            if not (
                item.get("source") == SOURCE
                and item.get("requested_step") == STEP
                and item.get("merchant_location_key") == "shenzhen-warehouse"
                and item.get("location_payload_sha256")
                and item.get("writes_to_ebay_after_approval") is True
                and item.get("public_publish_enabled") is False
                and item.get("secret_exposed") is False
            ):
                raise AssertionError("stored location confirmation must preserve the exact safe payload binding")

            confirmation_id = str(confirmation.get("confirmation_id") or "")
            blocked_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": confirmation_id},
                token,
            )
            if blocked_status != 409 or adapter.calls:
                raise AssertionError("an unapproved inventory location must not reach the provider adapter")

            viewer_decision_status, _ = _post(
                base_url,
                f"/confirmations/{confirmation_id}/decision",
                {"decision": "approve", "note": "viewer must not approve"},
                viewer_token,
            )
            if viewer_decision_status != 403:
                raise AssertionError("a viewer must not approve the high-risk inventory-location confirmation")

            approval_status, approval_body = _post(
                base_url,
                f"/confirmations/{confirmation_id}/decision",
                {"decision": "approve", "note": "Approve the exact controlled inventory location."},
                token,
            )
            if approval_status != 201 or (approval_body.get("confirmation") or {}).get("status") != "approved":
                raise AssertionError("confirmation center must approve the exact inventory-location card")

            viewer_execute_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": confirmation_id},
                viewer_token,
            )
            if viewer_execute_status != 403 or adapter.calls:
                raise AssertionError("a viewer without execute_confirmed_action must not reach the provider adapter")

            with ThreadPoolExecutor(max_workers=4) as pool:
                execute_results = list(
                    pool.map(
                        lambda _index: _post(
                            base_url,
                            f"/stores/{store['store_id']}/ebay-inventory-location/execute",
                            {"confirmation_id": confirmation_id},
                            token,
                        ),
                        range(4),
                    )
                )
            execute_statuses = sorted(status for status, _body in execute_results)
            if execute_statuses != [200, 409, 409, 409]:
                raise AssertionError(f"concurrent approved execution must have one winner; statuses={execute_statuses}")
            execute_status, execute_body = next(result for result in execute_results if result[0] == 200)
            result = execute_body.get("inventory_location_execution") or {}
            if not (
                execute_status == 200
                and result.get("status") == "inventory_location_created"
                and result.get("merchant_location_key") == "shenzhen-warehouse"
                and result.get("location_write_completed") is True
                and result.get("public_listing_created") is False
                and result.get("secret_exposed") is False
                and len(adapter.calls) == 1
                and repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id).get("status")
                == "executed"
            ):
                raise AssertionError(
                    "one exact approved inventory location must execute and become terminal once: "
                    f"status={execute_status} result_status={result.get('status')} "
                    f"calls={len(adapter.calls)} stored_status="
                    f"{repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id).get('status')}"
                )

            replay_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": confirmation_id},
                token,
            )
            if replay_status != 409 or len(adapter.calls) != 1:
                raise AssertionError("an inventory-location confirmation must be one-shot")

            for index, decided_at in enumerate(
                [
                    (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    "2026-08-14 12:00:00",
                    (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
                ],
                start=1,
            ):
                time_store = repository.create_store(
                    company_id=company_id,
                    user_id=user["user_id"],
                    payload={"platform": "ebay", "store_name": f"Time guard {index}", "marketplace": "EBAY_US"},
                )
                time_status, time_body = _post(
                    base_url,
                    f"/stores/{time_store['store_id']}/ebay-inventory-location/confirmation",
                    {**_location_payload(), "merchant_location_key": f"time-guard-{index}"},
                    token,
                )
                time_confirmation_id = str((time_body.get("inventory_location_confirmation") or {}).get("confirmation_id") or "")
                if time_status != 201 or not time_confirmation_id:
                    raise AssertionError("time-boundary fixture must create one confirmation")
                approve_time_status, _ = _post(
                    base_url,
                    f"/confirmations/{time_confirmation_id}/decision",
                    {"decision": "approve", "note": "time boundary"},
                    token,
                )
                if approve_time_status != 201:
                    raise AssertionError("time-boundary fixture approval failed")
                with repository._connect() as conn:  # noqa: SLF001 - boundary injection for fail-closed HTTP proof.
                    conn.execute(
                        "update confirmations set decided_at = ? where company_id = ? and confirmation_id = ?",
                        (decided_at, company_id, time_confirmation_id),
                    )
                calls_before = len(adapter.calls)
                time_execute_status, _ = _post(
                    base_url,
                    f"/stores/{time_store['store_id']}/ebay-inventory-location/execute",
                    {"confirmation_id": time_confirmation_id},
                    token,
                )
                stored_time = repository.get_confirmation(company_id=company_id, confirmation_id=time_confirmation_id) or {}
                if time_execute_status != 409 or len(adapter.calls) != calls_before or stored_time.get("status") != "approved":
                    raise AssertionError(
                        "future, naive, and expired inventory-location approvals must fail closed without consumption"
                    )

            deterministic_store = repository.create_store(
                company_id=company_id,
                user_id=user["user_id"],
                payload={"platform": "ebay", "store_name": "Deterministic guard", "marketplace": "EBAY_US"},
            )
            deterministic_status, deterministic_body = _post(
                base_url,
                f"/stores/{deterministic_store['store_id']}/ebay-inventory-location/confirmation",
                {**_location_payload(), "merchant_location_key": "deterministic-guard"},
                token,
            )
            deterministic_id = str(
                (deterministic_body.get("inventory_location_confirmation") or {}).get("confirmation_id") or ""
            )
            if deterministic_status != 201 or not deterministic_id:
                raise AssertionError("deterministic preflight fixture must create one confirmation")
            deterministic_approval_status, _ = _post(
                base_url,
                f"/confirmations/{deterministic_id}/decision",
                {"decision": "approve", "note": "deterministic guard"},
                token,
            )
            if deterministic_approval_status != 201:
                raise AssertionError("deterministic preflight fixture approval failed")
            calls_before = len(adapter.calls)
            wrong_store_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": deterministic_id},
                token,
            )
            if wrong_store_status != 409 or len(adapter.calls) != calls_before:
                raise AssertionError("a confirmation bound to another store must not reach the provider write")
            adapter.prepare_mode = "blocked"
            deterministic_execute_status, deterministic_execute_body = _post(
                base_url,
                f"/stores/{deterministic_store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": deterministic_id},
                token,
            )
            adapter.prepare_mode = "ready"
            deterministic_result = deterministic_execute_body.get("inventory_location_execution") or {}
            deterministic_stored = repository.get_confirmation(company_id=company_id, confirmation_id=deterministic_id) or {}
            if not (
                deterministic_execute_status == 409
                and deterministic_result.get("location_write_started") is False
                and deterministic_result.get("automatic_retry_allowed") is False
                and deterministic_stored.get("status") == "approved"
                and len(adapter.calls) == calls_before
            ):
                raise AssertionError("a deterministic prewrite block must preserve the approval and perform zero provider writes")

            adapter.prepare_mode = "bad_binding"
            binding_execute_status, _ = _post(
                base_url,
                f"/stores/{deterministic_store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": deterministic_id},
                token,
            )
            adapter.prepare_mode = "ready"
            binding_stored = repository.get_confirmation(company_id=company_id, confirmation_id=deterministic_id) or {}
            if binding_execute_status != 409 or binding_stored.get("status") != "approved" or len(adapter.calls) != calls_before:
                raise AssertionError("credential binding drift must fail in the atomic claim and preserve the approval")

            reconcile_store = repository.create_store(
                company_id=company_id,
                user_id=user["user_id"],
                payload={"platform": "ebay", "store_name": "Reconcile fixture", "marketplace": "EBAY_US"},
            )
            reconcile_intake_status, reconcile_intake_body = _post(
                base_url,
                f"/stores/{reconcile_store['store_id']}/ebay-inventory-location/confirmation",
                {**_location_payload(), "merchant_location_key": "reconcile-location"},
                token,
            )
            reconcile_id = str(
                (reconcile_intake_body.get("inventory_location_confirmation") or {}).get("confirmation_id") or ""
            )
            if reconcile_intake_status != 201 or not reconcile_id:
                raise AssertionError("reconciliation fixture must create one confirmation")
            reconcile_approval_status, _ = _post(
                base_url,
                f"/confirmations/{reconcile_id}/decision",
                {"decision": "approve", "note": "reconciliation fixture"},
                token,
            )
            if reconcile_approval_status != 201:
                raise AssertionError("reconciliation fixture approval failed")
            adapter.execute_mode = "manual_reconcile"
            uncertain_status, _ = _post(
                base_url,
                f"/stores/{reconcile_store['store_id']}/ebay-inventory-location/execute",
                {"confirmation_id": reconcile_id},
                token,
            )
            adapter.execute_mode = "success"
            uncertain_confirmation = repository.get_confirmation(
                company_id=company_id,
                confirmation_id=reconcile_id,
            ) or {}
            if uncertain_status != 502 or uncertain_confirmation.get("status") != "external_execution_processing_manual_reconcile":
                raise AssertionError("an uncertain location write must remain in manual reconcile without automatic retry")
            write_count_before_reconcile = len(adapter.calls)
            viewer_reconcile_status, _ = _post(
                base_url,
                f"/stores/{reconcile_store['store_id']}/ebay-inventory-location/reconcile",
                {"confirmation_id": reconcile_id},
                viewer_token,
            )
            if viewer_reconcile_status != 403 or adapter.reconcile_calls:
                raise AssertionError("a viewer must not reconcile an uncertain provider write")
            reconcile_status, reconcile_body = _post(
                base_url,
                f"/stores/{reconcile_store['store_id']}/ebay-inventory-location/reconcile",
                {"confirmation_id": reconcile_id},
                token,
            )
            reconcile_result = reconcile_body.get("inventory_location_reconciliation") or {}
            if not (
                reconcile_status == 200
                and reconcile_result.get("status") == "inventory_location_created"
                and reconcile_result.get("merchant_location_key") == "reconcile-location"
                and reconcile_result.get("reconciled_from_provider_read") is True
                and reconcile_result.get("writes_to_ebay") is False
                and reconcile_result.get("public_listing_created") is False
                and reconcile_result.get("secret_exposed") is False
                and len(adapter.calls) == write_count_before_reconcile
                and len(adapter.reconcile_calls) == 1
                and (repository.get_confirmation(company_id=company_id, confirmation_id=reconcile_id) or {}).get("status")
                == "executed"
            ):
                raise AssertionError(
                    "read-only reconciliation must finalize one exact uncertain location without a second provider write: "
                    f"status={reconcile_status} result={reconcile_result.get('status')} "
                    f"writes={len(adapter.calls) - write_count_before_reconcile} reads={len(adapter.reconcile_calls)}"
                )
            replay_reconcile_status, _ = _post(
                base_url,
                f"/stores/{reconcile_store['store_id']}/ebay-inventory-location/reconcile",
                {"confirmation_id": reconcile_id},
                token,
            )
            if replay_reconcile_status != 409 or len(adapter.reconcile_calls) != 1:
                raise AssertionError("an executed location reconciliation must be one-shot and issue no second provider read")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print("PASS jiejing_ebay_inventory_location_confirmation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
