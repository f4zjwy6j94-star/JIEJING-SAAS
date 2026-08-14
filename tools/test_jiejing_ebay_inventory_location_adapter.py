#!/usr/bin/env python3
"""Provider contract for one confirmation-gated eBay inventory location."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_write_adapter import EbayWriteHttpAdapter  # noqa: E402


def _settings() -> SaaSSettings:
    old = dict(os.environ)
    try:
        os.environ.update(
            {
                "JIEJING_SAAS_ENV": "staging",
                "JIEJING_ENABLE_REAL_PLATFORM_WRITES": "false",
                "JIEJING_EBAY_WRITE_LIVE": "false",
                "JIEJING_EBAY_DRAFT_SAVE_LIVE": "true",
                "JIEJING_EBAY_TOKEN_REFRESH_LIVE": "true",
                "JIEJING_EBAY_READ_ONLY_LIVE": "true",
                "JIEJING_VAULT_ENABLED": "true",
            }
        )
        return SaaSSettings.from_env(
            db_path=ROOT / "output" / "inventory-location-adapter.sqlite",
            runtime_db_path=ROOT / "output" / "inventory-location-runtime.sqlite",
            output_root=ROOT / "output" / "inventory-location-adapter",
            host="127.0.0.1",
            port=8788,
        )
    finally:
        os.environ.clear()
        os.environ.update(old)


def _credential_boundary() -> dict[str, Any]:
    connection_id = "conn_inventory_location_exact"
    secret_ref = "vault://ebay/inventory-location-exact"
    oauth_request_id = "oauth_inventory_location_exact"
    seller_identity_hash = "seller-inventory-location-exact"
    connection = {
        "connection_id": connection_id,
        "company_id": "company_inventory_location",
        "store_id": "store_inventory_location",
        "platform": "ebay",
        "connection_type": "oauth",
        "status": "draft_save_authorized",
        "scopes": list(UNPUBLISHED_DRAFT_SCOPES),
        "secret_ref": secret_ref,
        "metadata": {
            "oauth_request_id": oauth_request_id,
            "confirmation_id": "confirm_oauth_inventory_location",
            "scope_profile": "seller_unpublished_draft",
            "authorization_kind": "unpublished_draft",
            "draft_save_scope_authorized": True,
            "publish_scope_authorized": False,
            "public_publish_enabled": False,
            "real_platform_writes_enabled": False,
            "credential_source": "jiejing_vault_secret_ref",
            "account_deletion_identity_mapping_status": "identity_mapping_ready",
            "ebay_user_id_hash": seller_identity_hash,
            "secret_exposed": False,
        },
    }
    secret = {
        "secret_ref": secret_ref,
        "company_id": "company_inventory_location",
        "store_id": "store_inventory_location",
        "provider": "ebay",
        "purpose": "ebay_refresh_token",
        "status": "managed_vault_stored",
        "metadata": {
            "oauth_request_id": oauth_request_id,
            "credential_owner": "jiejing_saas_backend",
            "secret_exposed": False,
        },
    }
    return {
        "ready": True,
        "contract_version": "2026-08-13-unpublished-draft-credential-v1",
        "company_id": "company_inventory_location",
        "store_id": "store_inventory_location",
        "connection_id_sha256": hashlib.sha256(connection_id.encode()).hexdigest(),
        "credential_ref_sha256": hashlib.sha256(secret_ref.encode()).hexdigest(),
        "oauth_request_id_sha256": hashlib.sha256(oauth_request_id.encode()).hexdigest(),
        "seller_identity_sha256": hashlib.sha256(seller_identity_hash.encode()).hexdigest(),
        "connection": connection,
        "secret_reference": secret,
        "secret_exposed": False,
    }


def _payload() -> dict[str, Any]:
    return {
        "merchantLocationKey": "shenzhen-warehouse",
        "name": "Shenzhen Warehouse",
        "locationTypes": ["WAREHOUSE"],
        "location": {
            "address": {
                "city": "Shenzhen",
                "stateOrProvince": "Guangdong",
                "country": "CN",
            }
        },
    }


def _confirmation(status: str) -> dict[str, Any]:
    payload = _payload()
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "confirmation_id": "confirm_inventory_location",
        "company_id": "company_inventory_location",
        "store_id": "store_inventory_location",
        "task_id": "task_inventory_location",
        "action_type": "create_ebay_inventory_location",
        "runtime_run_id": "merchant_ebay_inventory_location_setup",
        "status": status,
        "external_execution_claimed": status == "external_execution_processing_manual_reconcile",
        "item": {
            "source": "merchant_ebay_inventory_location_setup",
            "requested_step": "inventory_location_confirmation_gate",
            "company_id": "company_inventory_location",
            "store_id": "store_inventory_location",
            "merchant_location_key": "shenzhen-warehouse",
            "location_payload": payload,
            "location_payload_sha256": digest,
            "writes_to_ebay_after_approval": True,
            "public_publish_enabled": False,
            "public_listing_created": False,
            "secret_exposed": False,
        },
    }


class LocationTransport:
    def __init__(self, *, missing_error_id: int = 25805) -> None:
        self.calls: list[tuple[str, str]] = []
        self.missing_error_id = missing_error_id

    def __call__(self, request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del timeout
        method = request.get_method()
        self.calls.append((method, request.full_url))
        if method == "GET" and "/sell/inventory/v1/location/shenzhen-warehouse" in request.full_url:
            body = json.dumps(
                {
                    "errors": [
                        {
                            "errorId": self.missing_error_id,
                            "domain": "API_INVENTORY",
                            "category": "REQUEST",
                        }
                    ]
                }
            ).encode()
            raise HTTPError(request.full_url, 404, "missing", {}, io.BytesIO(body))
        if method == "POST" and "/sell/inventory/v1/location/shenzhen-warehouse" in request.full_url:
            return 204, {"content-type": "application/json"}, b""
        raise AssertionError(f"unexpected provider call: {method} {request.full_url}")


class ExistingLocationTransport:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.payload = payload or _payload()

    def __call__(self, request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        del timeout
        method = request.get_method()
        self.calls.append((method, request.full_url))
        if method != "GET" or "/sell/inventory/v1/location/shenzhen-warehouse" not in request.full_url:
            raise AssertionError(f"read-only reconciliation must never write: {method} {request.full_url}")
        return 200, {"content-type": "application/json"}, json.dumps(self.payload).encode()


def main() -> int:
    transport = LocationTransport()
    adapter = EbayWriteHttpAdapter(_settings(), transport=transport)
    adapter._resolve_access_token = lambda **_: {  # type: ignore[method-assign]
        "ok": True,
        "source": "test_backend_token",
        "access_token": "INVENTORY-LOCATION-TOKEN-DO-NOT-LEAK",
    }
    prepared = adapter.prepare_inventory_location(
        confirmation=_confirmation("approved"),
        location_payload=_payload(),
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if not hasattr(prepared, "claim_binding") or [method for method, _ in transport.calls] != ["GET"]:
        raise AssertionError(
            "prepare must do one exact GET and no provider write: "
            f"prepared_status={prepared.get('status') if isinstance(prepared, dict) else type(prepared).__name__} "
            f"calls={[method for method, _ in transport.calls]}"
        )

    result = adapter.execute_prepared_inventory_location(
        confirmation=_confirmation("external_execution_processing_manual_reconcile"),
        prepared=prepared,
        marketplace_id="EBAY_US",
    )
    if not (
        result.get("status") == "inventory_location_created"
        and result.get("action_type") == "create_ebay_inventory_location"
        and result.get("merchant_location_key") == "shenzhen-warehouse"
        and result.get("location_write_completed") is True
        and result.get("public_listing_created") is False
        and result.get("secret_exposed") is False
        and [method for method, _ in transport.calls] == ["GET", "POST"]
    ):
        raise AssertionError("claimed execution must create exactly one non-public inventory location")

    replay = adapter.execute_prepared_inventory_location(
        confirmation=_confirmation("external_execution_processing_manual_reconcile"),
        prepared=prepared,
        marketplace_id="EBAY_US",
    )
    if replay.get("status") != "inventory_location_preparation_invalid" or len(transport.calls) != 2:
        raise AssertionError("the opaque inventory-location preparation must be one-shot")

    reconcile_transport = ExistingLocationTransport()
    reconcile_adapter = EbayWriteHttpAdapter(_settings(), transport=reconcile_transport)
    reconcile_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[method-assign]
    reconciled = reconcile_adapter.reconcile_inventory_location(
        confirmation=_confirmation("external_execution_processing_manual_reconcile"),
        location_payload=_payload(),
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if not (
        reconciled.get("status") == "inventory_location_created"
        and reconciled.get("action_type") == "create_ebay_inventory_location"
        and reconciled.get("merchant_location_key") == "shenzhen-warehouse"
        and reconciled.get("location_write_completed") is True
        and reconciled.get("reconciled_from_provider_read") is True
        and reconciled.get("writes_to_ebay") is False
        and reconciled.get("public_listing_created") is False
        and reconciled.get("secret_exposed") is False
        and [method for method, _ in reconcile_transport.calls] == ["GET"]
    ):
        raise AssertionError("manual-reconcile recovery must prove the exact location using one GET and zero writes")

    absent_transport = LocationTransport()
    absent_adapter = EbayWriteHttpAdapter(_settings(), transport=absent_transport)
    absent_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[method-assign]
    absent = absent_adapter.reconcile_inventory_location(
        confirmation=_confirmation("external_execution_processing_manual_reconcile"),
        location_payload=_payload(),
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if not (
        absent.get("status") == "inventory_location_reconcile_unconfirmed"
        and absent.get("automatic_retry_allowed") is False
        and absent.get("writes_to_ebay") is False
        and absent.get("public_listing_created") is False
        and absent.get("secret_exposed") is False
        and [method for method, _ in absent_transport.calls] == ["GET"]
    ):
        raise AssertionError("an absent or unknown location must remain paused with one GET and zero writes")

    mismatch_transport = ExistingLocationTransport({**_payload(), "name": "Another Warehouse"})
    mismatch_adapter = EbayWriteHttpAdapter(_settings(), transport=mismatch_transport)
    mismatch_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[method-assign]
    mismatch = mismatch_adapter.reconcile_inventory_location(
        confirmation=_confirmation("external_execution_processing_manual_reconcile"),
        location_payload=_payload(),
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if not (
        mismatch.get("status") == "inventory_location_reconcile_response_mismatch"
        and mismatch.get("automatic_retry_allowed") is False
        and mismatch.get("writes_to_ebay") is False
        and [method for method, _ in mismatch_transport.calls] == ["GET"]
    ):
        raise AssertionError("a same-key location with different business fields must remain blocked without writes")

    attacked_transport = LocationTransport(missing_error_id=25713)
    attacked_adapter = EbayWriteHttpAdapter(_settings(), transport=attacked_transport)
    attacked_adapter._resolve_access_token = adapter._resolve_access_token  # type: ignore[method-assign]
    attacked = attacked_adapter.prepare_inventory_location(
        confirmation=_confirmation("approved"),
        location_payload=_payload(),
        credential_boundary=_credential_boundary(),
        marketplace_id="EBAY_US",
    )
    if not (
        isinstance(attacked, dict)
        and attacked.get("status") == "inventory_location_preflight_blocked"
        and [method for method, _ in attacked_transport.calls] == ["GET"]
    ):
        raise AssertionError("only exact eBay 25805 missing-location evidence may reach the write phase")

    serialized = json.dumps(result, ensure_ascii=False)
    if "DO-NOT-LEAK" in serialized or "vault://" in serialized:
        raise AssertionError("inventory-location result must not expose token or secret-reference values")

    print("PASS jiejing_ebay_inventory_location_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
