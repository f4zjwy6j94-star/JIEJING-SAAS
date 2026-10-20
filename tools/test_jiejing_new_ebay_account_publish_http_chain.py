#!/usr/bin/env python3
"""HTTP regression for the version-bound new-account publish/cleanup proof chain."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas import api_server  # noqa: E402
from jiejing_runtime.execution import ExecutionRequest
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.commercial_launch_gate import (  # noqa: E402
    _build_current_store_new_account_action_evidence,
    build_commercial_launch_gate,
)
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.ebay_oauth import EbayOAuthPlanner, UNPUBLISHED_DRAFT_SCOPES  # noqa: E402
from jiejing_saas.ebay_oauth_callback import process_ebay_oauth_callback  # noqa: E402
from jiejing_saas.repository import ConfirmationDecisionConflict, SaaSRepository  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.ebay_write_adapter import build_ebay_execution_plan, _inventory_item_body, _offer_body


CONTRACT_VERSION = "2026-06-18-new-ebay-account-low-risk-smoke"


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _seed_legacy_connection(repo, *, company_id, store_id, user_id):
    connection=repo.create_platform_connection(company_id=company_id,store_id=store_id,user_id=user_id,
        payload={'platform':'ebay','connection_type':'oauth','status':'publish_authorized',
            'scopes':['https://api.ebay.com/oauth/api_scope/sell.inventory'],'create_secret_ref':True,
            'metadata':{'ebay_user_id_hash':hashlib.sha256(b'HTTP-CHAIN-DRAFT-SELLER-DO-NOT-LEAK').hexdigest()}})
    with repo._connect() as conn:
        conn.execute("update secret_refs set status='stored' where secret_ref=?",(connection['secret_ref'],))
    return repo.ebay_execution_connections(company_id=company_id,store_id=store_id)[0]


def _drive_synthetic_operations(request, permit, *, stop_after_admit=False):
    """Routing-fixture receipts use a real claim/permit, never fake capability.

    This is not adapter transport proof; the separate injected-adapter mains
    exercise the actual HTTP body and ordered provider transport contracts.
    """
    with permit._repo._connect() as conn:
        row=conn.execute('select operation_state_json from confirmation_execution_authorities_v1 where attempt_id=?',
            (permit._attempt,)).fetchone()
    plan=json.loads(row['operation_state_json'])['plan']
    offer_id='offer-draft-001' if request.action_type=='save_ebay_listing_draft' else 'offer-smoke-001'
    for index,operation in enumerate(plan['operations']):
        body=(_inventory_item_body(request.payload) if operation['kind']=='inventory' else
            _offer_body(request.payload,marketplace_id=plan['marketplace_id'])
            if operation['kind'] in {'create_offer','update_offer'} else {})
        target=operation['target'].replace('{offer_id}',offer_id)
        permit.admit(operation_index=index,method=operation['method'],path=target,body=body,
            marketplace_id=plan['marketplace_id'],credential=plan['credential'])
        if stop_after_admit:
            return
        permit.record(operation_index=index,result={'status':'ok','http_status':200,
            'json':{'offerId':offer_id,'listingId':'listing-smoke-001'}})


def _post(base_url: str, path: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_status(base_url: str, path: str, payload: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    try:
        return 200, _post(base_url, path, payload, token)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def _publish_payload(
    *,
    listing_project_identity: dict[str, str],
    product_fact_report_id: str,
    image_url: str = "https://example.com/smoke.jpg",
) -> dict[str, Any]:
    return {
        "workflow_scope": "new_ebay_account_low_risk_smoke",
        "idempotency_key": "new-account-smoke-publish-http-v1",
        "listing_project_identity": dict(listing_project_identity),
        "publish_evidence_refs": {
            "product_fact_report_id": product_fact_report_id,
            "media_job_id": "",
        },
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
        "asset_manifest": {"assets": [{"url": image_url}]},
        "finance_review": {"net_profit_money": {"value": "0.25", "currency": "USD"}},
    }


def _draft_oauth_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() == "GET" and request.full_url.endswith("/commerce/identity/v1/user/"):
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "userId": "HTTP-CHAIN-DRAFT-SELLER-DO-NOT-LEAK",
                    "username": "http-chain-draft-seller",
                    "registrationMarketplaceId": "EBAY_US",
                    "accountType": "BUSINESS",
                    "status": "CONFIRMED",
                }
            ).encode("utf-8"),
        )
    if request.get_method() == "POST" and "/identity/v1/oauth2/token" in request.full_url:
        return (
            200,
            {"content-type": "application/json"},
            json.dumps(
                {
                    "access_token": "HTTP-CHAIN-DRAFT-ACCESS-TOKEN-DO-NOT-LEAK",
                    "refresh_token": "HTTP-CHAIN-DRAFT-REFRESH-TOKEN-DO-NOT-LEAK",
                    "expires_in": 7200,
                    "refresh_token_expires_in": 47304000,
                    "scope": " ".join(UNPUBLISHED_DRAFT_SCOPES),
                }
            ).encode("utf-8"),
        )
    return 404, {"content-type": "application/json"}, b'{"error":"missing"}'


def _draft_vault_transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
    del timeout
    if request.get_method() != "POST":
        return 405, {"content-type": "application/json"}, b'{"errors":["method"]}'
    return 204, {"content-type": "application/json"}, b""


def _seed_exact_draft_callback(
    settings: SaaSSettings,
    repo: SaaSRepository,
    *,
    company_id: str,
    store_id: str,
    user_id: str,
) -> dict[str, Any]:
    settings.ebay_client_id = "HTTP-CHAIN-CLIENT-ID"
    settings.ebay_ru_name = "Jiejing_HTTP_Chain_RuName"
    settings.ebay_client_secret_configured = True
    settings.ebay_oauth_live_exchange_enabled = True
    settings.vault_enabled = True
    settings.vault_provider = "vault"
    planner = EbayOAuthPlanner(settings)
    confirmation = repo.create_unpublished_draft_oauth_confirmation(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
    )
    confirmation = repo.decide_confirmation(
        company_id=company_id,
        confirmation_id=confirmation["confirmation_id"],
        decision="approve",
        decided_by=user_id,
        note="Exact HTTP-chain draft callback fixture.",
        expected_access_epochs=repo.access_session_epochs(user_id=user_id,company_id=company_id),
    )
    plan = planner.unpublished_draft_authorization_plan(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        marketplace_id="EBAY_US",
        requested_scopes=UNPUBLISHED_DRAFT_SCOPES,
    )
    plan["confirmation_id"] = confirmation["confirmation_id"]
    oauth_request = repo.create_approved_unpublished_draft_oauth_authorization_request(
        company_id=company_id,
        store_id=store_id,
        user_id=user_id,
        confirmation_id=confirmation["confirmation_id"],
        plan=plan,
    )
    with patch.dict(
        os.environ,
        {
            "JIEJING_EBAY_CLIENT_SECRET": "HTTP-CHAIN-CLIENT-SECRET-DO-NOT-LEAK",
            "JIEJING_VAULT_LIVE_RESOLVE_ENABLED": "true",
            "JIEJING_VAULT_ADDR": "https://vault.example.test",
            "JIEJING_VAULT_TOKEN": "HTTP-CHAIN-VAULT-TOKEN-DO-NOT-LEAK",
            "JIEJING_VAULT_MOUNT": "secret",
            "JIEJING_VAULT_KEYSPACE": "http-chain",
            "JIEJING_VAULT_KV_VERSION": "v2",
        },
        clear=False,
    ):
        callback = process_ebay_oauth_callback(
            repository=repo,
            settings=settings,
            secret_store_boundary=SecretStoreBoundary(settings),
            ebay_oauth_planner=planner,
            state=oauth_request["state_nonce"],
            code="HTTP_CHAIN_EXACT_DRAFT_AUTH_CODE",
            error="",
            oauth_transport=_draft_oauth_transport,
            vault_transport=_draft_vault_transport,
        )
    if callback.get("status") != "callback_exchange_completed":
        raise AssertionError(
            "exact draft OAuth callback did not complete: "
            f"{callback.get('status')} blocked_by={callback.get('blocked_by')}"
        )
    boundary = repo.unpublished_draft_execution_credential_boundary(
        company_id=company_id,
        store_id=store_id,
    )
    if boundary.get("ready") is not True or boundary.get("connection_status") != "draft_save_authorized":
        raise AssertionError(f"exact draft credential boundary not ready: {boundary.get('code')}")
    return boundary


class FakeWriteAdapter:
    """No-network adapter used only to exercise the real HTTP producer chain."""

    last_publish_payload: dict[str, Any] = {}
    last_cleanup_payload: dict[str, Any] = {}
    last_draft_payload: dict[str, Any] = {}
    last_publish_platform = ""
    call_lock = threading.Lock()
    publish_call_count = 0
    cleanup_call_count = 0
    draft_call_count = 0
    block_publish = False
    block_cleanup = False
    publish_started = threading.Event()
    cleanup_started = threading.Event()
    release_publish = threading.Event()
    release_cleanup = threading.Event()
    fail_publish = False
    fail_draft_before_consume = False
    fail_draft_after_consume = False
    draft_execute_attempt_count = 0
    fail_cleanup = False

    @classmethod
    def reset_control(cls) -> None:
        with cls.call_lock:
            cls.publish_call_count = 0
            cls.cleanup_call_count = 0
            cls.draft_call_count = 0
        cls.block_publish = False
        cls.block_cleanup = False
        cls.fail_publish = False
        cls.fail_draft_before_consume = False
        cls.fail_draft_after_consume = False
        cls.draft_execute_attempt_count = 0
        cls.fail_cleanup = False
        cls.publish_started.clear()
        cls.cleanup_started.clear()
        cls.release_publish.clear()
        cls.release_cleanup.clear()

    def __init__(self, settings: SaaSSettings) -> None:
        self.settings = settings
        self._prepared: dict[int, tuple[Any, dict[str, Any]]] = {}

    def publish_listing(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> dict[str, Any]:
        with type(self).call_lock:
            type(self).publish_call_count += 1
        type(self).last_publish_payload = json.loads(json.dumps(request.payload))
        type(self).last_publish_platform = str(request.platform)
        type(self).publish_started.set()
        if type(self).block_publish:
            type(self).release_publish.wait(timeout=5)
        _drive_synthetic_operations(request,_['execution_permit'],stop_after_admit=type(self).fail_publish)
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

    def save_listing_draft(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> dict[str, Any]:
        with type(self).call_lock:
            type(self).draft_call_count += 1
        type(self).last_draft_payload = json.loads(json.dumps(request.payload))
        type(self).publish_started.set()
        if type(self).block_publish:
            type(self).release_publish.wait(timeout=5)
        if type(self).fail_publish:
            raise RuntimeError("fake draft adapter failure sentinel")
        return {
            "status": "saved_to_ebay_draft",
            "action_type": "save_ebay_listing_draft",
            "task_id": request.task_id,
            "platform_result": {
                "offer_id": "offer-draft-001",
                "sku": str(request.payload.get("listing", {}).get("sku") or ""),
                "offer_status": "UNPUBLISHED",
                "writes_to_ebay": True,
                "published_to_ebay": False,
                "public_listing_created": False,
            },
            "audit": {
                "preflight": preflight,
                "real_execution": {
                    "ebay_draft_saved": True,
                    "published_to_ebay": False,
                },
            },
            "secret_exposed": False,
        }

    def prepare_listing_draft(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> Any:
        class _DraftPreparationHandle:
            def __init__(self, safe: dict[str, str], plan: Any) -> None:
                self._safe = safe
                self._plan = plan

            def claim_binding(self) -> dict[str, str]:
                return dict(self._safe)

            def execution_plan(self):
                return self._plan

        boundary = _.get("credential_boundary") if isinstance(_.get("credential_boundary"), dict) else {}
        safe = {
            "confirmation_id": str(request.confirmation_id or ""),
            "company_id": str(request.company_id or ""),
            "store_id": str(request.store_id or ""),
            "action_type": "save_ebay_listing_draft",
            "task_id": str(request.task_id or ""),
            "idempotency_key": str(request.idempotency_key or ""),
            "marketplace_id": str(_.get("marketplace_id") or ""),
            "payload_sha256": hashlib.sha256(
                json.dumps(request.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "preparation_sha256": hashlib.sha256(
                f"fake-http-preparation:{request.confirmation_id}:{request.idempotency_key}".encode("utf-8")
            ).hexdigest(),
            "contract_version": "2026-08-13-unpublished-draft-credential-v1",
            **{
                key: str(boundary.get(key) or "")
                for key in (
                    "connection_id_sha256",
                    "credential_ref_sha256",
                    "oauth_request_id_sha256",
                    "seller_identity_sha256",
                )
            },
        }
        handle = _DraftPreparationHandle(safe,build_ebay_execution_plan(request=request,
            marketplace_id=str(_.get('marketplace_id') or ''),credential_boundary=boundary,draft_offer_id=''))
        self._prepared[id(handle)] = (request, preflight)
        return handle

    def execute_prepared_listing_draft(
        self,
        *,
        request: Any,
        preflight: dict[str, Any],
        prepared: Any,
        claim_capability: Any,
        **_: Any,
    ) -> dict[str, Any]:
        if id(prepared) not in self._prepared:
            raise RuntimeError("fake prepared handle missing")
        with type(self).call_lock:
            type(self).draft_execute_attempt_count += 1
        if type(self).fail_draft_before_consume:
            raise RuntimeError("fake deterministic draft prewrite failure sentinel")
        consumed = claim_capability.consume()
        if consumed.get("external_execution_claimed") is not True:
            raise RuntimeError("fake claim not consumed")
        _drive_synthetic_operations(request,claim_capability.execution_permit(),
            stop_after_admit=type(self).fail_draft_after_consume)
        if type(self).fail_draft_after_consume:
            raise RuntimeError("fake uncertain draft post-consume failure sentinel")
        return self.save_listing_draft(request=request, preflight=preflight)

    def execute_cleanup_plan(self, *, request: Any, preflight: dict[str, Any], **_: Any) -> dict[str, Any]:
        with type(self).call_lock:
            type(self).cleanup_call_count += 1
        type(self).last_cleanup_payload = json.loads(json.dumps(request.payload))
        type(self).cleanup_started.set()
        if type(self).block_cleanup:
            type(self).release_cleanup.wait(timeout=5)
        _drive_synthetic_operations(request,_['execution_permit'],stop_after_admit=type(self).fail_cleanup)
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
        legacy_connection=_seed_legacy_connection(repo,company_id=user['default_company_id'],store_id=store['store_id'],user_id=user['user_id'])
        listing_project_identity = {
            "key": "listing-project-new-account-http-chain",
            "source_report_id": "market-report-new-account-http-chain",
            "candidate_id": "candidate-new-account-http-chain",
        }
        product_fact_task = repo.create_task(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            task_type="merchant_product_facts",
            title="Authoritative publish evidence fixture",
            input_data={"listing_project_identity": listing_project_identity},
        )
        product_fact_report = repo.save_merchant_product_fact_report(
            task=product_fact_task,
            listing_project_identity=listing_project_identity,
            packet={
                "source": "authenticated_merchant_request",
                "source_mode": "merchant_owned_product",
                "simulation_only": False,
                "product_name": "New account smoke widget",
                "merchant_confirmed_facts": {
                    "merchant_owned_product_confirmed": True,
                    "image_rights_confirmed": True,
                },
                "source_records": [
                    {
                        "type": "merchant_product_image",
                        "url": "https://example.com/smoke.jpg",
                        "rights_status": "merchant_confirmed",
                    },
                    {
                        "type": "merchant_product_image",
                        "url": "https://example.com/ordinary.jpg",
                        "rights_status": "merchant_confirmed",
                    },
                ],
                "unknown_facts": [],
                "secret_exposed": False,
            },
        )
        revocation_project_identity = {
            "key": "listing-project-evidence-revocation-http",
            "source_report_id": "market-report-evidence-revocation-v1",
            "candidate_id": "candidate-evidence-revocation-v1",
        }
        revocation_fact_task = repo.create_task(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            task_type="merchant_product_facts",
            title="Evidence revocation positive checkpoint",
            input_data={"listing_project_identity": revocation_project_identity},
        )
        revocation_fact_report = repo.save_merchant_product_fact_report(
            task=revocation_fact_task,
            listing_project_identity=revocation_project_identity,
            packet={
                "source": "authenticated_merchant_request",
                "source_mode": "merchant_owned_product",
                "simulation_only": False,
                "product_name": "Evidence revocation widget",
                "merchant_confirmed_facts": {
                    "merchant_owned_product_confirmed": True,
                    "image_rights_confirmed": True,
                },
                "source_records": [
                    {
                        "type": "merchant_product_image",
                        "url": "https://example.com/revocation.jpg",
                        "rights_status": "merchant_confirmed",
                    }
                ],
                "unknown_facts": [],
                "secret_exposed": False,
            },
        )
        claim_window_project_identity = {
            "key": "listing-project-claim-window-http",
            "source_report_id": "market-report-claim-window-v1",
            "candidate_id": "candidate-claim-window-v1",
        }
        claim_window_fact_task = repo.create_task(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            task_type="merchant_product_facts",
            title="Claim-window positive checkpoint",
            input_data={"listing_project_identity": claim_window_project_identity},
        )
        claim_window_fact_report = repo.save_merchant_product_fact_report(
            task=claim_window_fact_task,
            listing_project_identity=claim_window_project_identity,
            packet={
                "source": "authenticated_merchant_request",
                "source_mode": "merchant_owned_product",
                "simulation_only": False,
                "product_name": "Claim-window widget",
                "merchant_confirmed_facts": {
                    "merchant_owned_product_confirmed": True,
                    "image_rights_confirmed": True,
                },
                "source_records": [
                    {
                        "type": "merchant_product_image",
                        "url": "https://example.com/claim-window.jpg",
                        "rights_status": "merchant_confirmed",
                    }
                ],
                "unknown_facts": [],
                "secret_exposed": False,
            },
        )

        def publish_payload(*, image_url: str = "https://example.com/smoke.jpg") -> dict[str, Any]:
            return _publish_payload(
                listing_project_identity=listing_project_identity,
                product_fact_report_id=product_fact_report["report_id"],
                image_url=image_url,
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
        settings.ebay_draft_save_live_enabled = True
        settings.ebay_token_refresh_live_enabled = True
        settings.ebay_read_only_live_enabled = True
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
            access_epochs=repo.access_session_epochs(user_id=user["user_id"],company_id=user["default_company_id"]),
        )
        restricted_account = repo.create_user_with_company(
            email="draft-permissions-http@example.com",
            password="Password123!",
            company_name="Draft Permissions Fixture",
        )
        restricted_user = restricted_account["user"]
        with repo._connect() as conn:
            conn.execute(
                "insert into team_members (company_id, user_id, role, created_at) values (?, ?, ?, ?)",
                (
                    user["default_company_id"],
                    restricted_user["user_id"],
                    "support",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        restricted_token = sessions.create_token(
            user_id=restricted_user["user_id"],
            company_id=user["default_company_id"],
            email=restricted_user["email"],
            access_epochs=repo.access_session_epochs(user_id=restricted_user["user_id"],company_id=user["default_company_id"]),
        )
        try:
            ordinary_body = publish_payload(image_url="https://example.com/ordinary.jpg")
            ordinary_body.pop("workflow_scope", None)
            ordinary_body["listing"] = {
                **ordinary_body["listing"],
                "sku": "ORDINARY-001",
                "title": "Ordinary listing",
            }
            ordinary = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                ordinary_body,
                token,
            )["confirmation"]
            ordinary_item = ordinary.get("item") if isinstance(ordinary.get("item"), dict) else {}
            if ordinary_item.get("source") == "new_ebay_account_low_risk_smoke":
                return fail("ordinary publish confirmation must never impersonate the new-account smoke contract")

            revocation_body = _publish_payload(
                listing_project_identity=revocation_project_identity,
                product_fact_report_id=revocation_fact_report["report_id"],
                image_url="https://example.com/revocation.jpg",
            )
            revocation_body.pop("workflow_scope", None)
            revocation_body["listing"] = {
                **revocation_body["listing"],
                "sku": "EVIDENCE-REVOCATION-001",
                "title": "Evidence revocation widget",
            }
            revocation_confirmation = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                revocation_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{revocation_confirmation['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve before normal fact-checkpoint revocation."},
                token,
            )
            revoked_identity_metadata = {
                **revocation_project_identity,
                "source_report_id": "market-report-evidence-revocation-v2",
                "candidate_id": "candidate-evidence-revocation-v2",
            }
            revoked_fact_task = repo.create_task(
                company_id=user["default_company_id"],
                store_id=store["store_id"],
                user_id=user["user_id"],
                task_type="merchant_product_facts",
                title="Evidence revocation negative checkpoint",
                input_data={"listing_project_identity": revoked_identity_metadata},
            )
            repo.save_merchant_product_fact_report(
                task=revoked_fact_task,
                listing_project_identity=revoked_identity_metadata,
                packet={
                    "source": "authenticated_merchant_request",
                    "source_mode": "source_missing",
                    "simulation_only": False,
                    "product_name": "Evidence revocation widget",
                    "merchant_confirmed_facts": {
                        "merchant_owned_product_confirmed": False,
                        "image_rights_confirmed": False,
                    },
                    "source_records": [
                        {
                            "type": "merchant_product_image",
                            "url": "https://example.com/revocation.jpg",
                            "rights_status": "pending",
                        }
                    ],
                    "unknown_facts": ["merchant_owned_product_confirmed", "image_rights_confirmed"],
                    "secret_exposed": False,
                },
            )
            preflight_status, revoked_preflight = _post_status(
                base_url,
                f"/confirmations/{revocation_confirmation['confirmation_id']}/preflight",
                {},
                token,
            )
            FakeWriteAdapter.reset_control()
            revocation_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=revocation_confirmation["confirmation_id"],
            ) or {}
            if (
                preflight_status != 409
                or revoked_preflight.get("error") != "publish_evidence_changed"
                or FakeWriteAdapter.publish_call_count != 0
                or revocation_terminal.get("status") != "needs_revision"
            ):
                return fail(
                    "a newer negative product-fact checkpoint must expire preflight with zero adapter calls: "
                    f"{preflight_status} {revoked_preflight} "
                    f"calls={FakeWriteAdapter.publish_call_count} terminal={revocation_terminal.get('status')}"
                )

            claim_window_body = _publish_payload(
                listing_project_identity=claim_window_project_identity,
                product_fact_report_id=claim_window_fact_report["report_id"],
                image_url="https://example.com/claim-window.jpg",
            )
            claim_window_body.pop("workflow_scope", None)
            claim_window_body["listing"] = {
                **claim_window_body["listing"],
                "sku": "CLAIM-WINDOW-001",
                "title": "Claim-window widget",
            }
            claim_window_confirmation = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                claim_window_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{claim_window_confirmation['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve before claim-window revocation regression."},
                token,
            )
            original_revalidate = api_server._revalidate_confirmation_publish_evidence
            claim_window_hook = {"armed": True}

            def revalidate_then_revoke(repository: Any, *, company_id: str, confirmation: dict[str, Any]) -> dict[str, Any]:
                fresh = original_revalidate(
                    repository,
                    company_id=company_id,
                    confirmation=confirmation,
                )
                if (
                    claim_window_hook["armed"]
                    and confirmation.get("confirmation_id") == claim_window_confirmation["confirmation_id"]
                ):
                    claim_window_hook["armed"] = False
                    negative_task = repo.create_task(
                        company_id=user["default_company_id"],
                        store_id=store["store_id"],
                        user_id=user["user_id"],
                        task_type="merchant_product_facts",
                        title="Claim-window negative checkpoint",
                        input_data={"listing_project_identity": claim_window_project_identity},
                    )
                    repo.save_merchant_product_fact_report(
                        task=negative_task,
                        listing_project_identity={
                            **claim_window_project_identity,
                            "source_report_id": "market-report-claim-window-v2",
                            "candidate_id": "candidate-claim-window-v2",
                        },
                        packet={
                            "source": "authenticated_merchant_request",
                            "source_mode": "source_missing",
                            "simulation_only": False,
                            "product_name": "Claim-window widget",
                            "merchant_confirmed_facts": {
                                "merchant_owned_product_confirmed": False,
                                "image_rights_confirmed": False,
                            },
                            "source_records": [
                                {
                                    "type": "merchant_product_image",
                                    "url": "https://example.com/claim-window.jpg",
                                    "rights_status": "pending",
                                }
                            ],
                            "unknown_facts": ["merchant_owned_product_confirmed", "image_rights_confirmed"],
                            "secret_exposed": False,
                        },
                    )
                return fresh

            FakeWriteAdapter.reset_control()
            api_server._revalidate_confirmation_publish_evidence = revalidate_then_revoke
            try:
                claim_window_status, claim_window_execute = _post_status(
                    base_url,
                    f"/confirmations/{claim_window_confirmation['confirmation_id']}/execute",
                    {"idempotency_key": "claim-window-revocation-must-not-write"},
                    token,
                )
            finally:
                api_server._revalidate_confirmation_publish_evidence = original_revalidate
            claim_window_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=claim_window_confirmation["confirmation_id"],
            ) or {}
            if (
                claim_window_status != 409
                or claim_window_execute.get("error") != "publish_evidence_changed"
                or claim_window_execute.get("external_execution_claim_restored") is not True
                or claim_window_execute.get("real_platform_write_attempted") is not False
                or FakeWriteAdapter.publish_call_count != 0
                or claim_window_terminal.get("status") != "needs_revision"
            ):
                return fail(
                    "claim-window evidence revocation must restore to needs_revision before any adapter call: "
                    f"{claim_window_status} {claim_window_execute} calls={FakeWriteAdapter.publish_call_count} "
                    f"terminal={claim_window_terminal.get('status')}"
                )

            smoke_response = _post(
                base_url,
                f"/stores/{store['store_id']}/publish-confirmation",
                publish_payload(),
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
                return fail(
                    "explicit smoke producer must persist publish-health readiness from the server preflight: "
                    f"{item.get('publish_readiness')}"
                )

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

            ordinary_complete_body = publish_payload()
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
            concurrent_body = publish_payload()
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
            failing_body = publish_payload()
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
            cleanup_source_body = publish_payload()
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

            # The earlier legacy transport fixture has no OAuth callback
            # provenance. Retire only its synthetic credential before the
            # original fresh-callback draft phase; do not forge an upgrade or
            # delete/change any prior confirmation, attempt, or receipt.
            with repo._connect() as conn:
                history_tables=('confirmations','confirmation_approval_authorities_v1',
                    'confirmation_execution_authorities_v1','external_execution_claims','execution_results')
                history_before={table:[dict(row) for row in conn.execute(f'select * from {table} order by 1').fetchall()]
                    for table in history_tables}
                changed=conn.execute("update platform_connections set status='revoked' where connection_id=? and company_id=? and store_id=? and status='publish_authorized'",
                    (legacy_connection['connection_id'],user['default_company_id'],store['store_id'])).rowcount
                conn.execute("update secret_refs set status='revoked' where secret_ref=?",(legacy_connection['secret_ref'],))
                history_after={table:[dict(row) for row in conn.execute(f'select * from {table} order by 1').fetchall()]
                    for table in history_tables}
                if changed!=1 or history_after!=history_before:
                    return fail('synthetic credential retirement must leave all prior authority and receipts intact')
            try:
                _seed_exact_draft_callback(
                    settings,
                    repo,
                    company_id=user["default_company_id"],
                    store_id=store["store_id"],
                    user_id=user["user_id"],
                )
            except AssertionError as exc:
                return fail(str(exc))

            settings.requested_real_platform_writes = False
            settings.ebay_write_live_enabled = False
            approval_guard_body = publish_payload()
            approval_guard_body.pop("workflow_scope", None)
            approval_guard_body["listing"] = {
                **approval_guard_body["listing"],
                "sku": "DRAFT-PERMISSION-APPROVAL-001",
                "title": "Draft approval permission guard",
            }
            approval_guard = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                approval_guard_body,
                token,
            )["confirmation"]
            approval_status, _approval_payload = _post_status(
                base_url,
                f"/confirmations/{approval_guard['confirmation_id']}/decision",
                {"decision": "approve", "note": "A support member must not approve a real draft write."},
                restricted_token,
            )
            approval_after = repo.get_confirmation(
                company_id=user["default_company_id"], confirmation_id=approval_guard["confirmation_id"]
            ) or {}
            if approval_status != 403 or approval_after.get("status") != "pending":
                return fail("a role without approve_high_risk must not approve an eBay draft write")

            execute_guard_body = publish_payload()
            execute_guard_body.pop("workflow_scope", None)
            execute_guard_body["listing"] = {
                **execute_guard_body["listing"],
                "sku": "DRAFT-PERMISSION-EXECUTE-001",
                "title": "Draft execute permission guard",
            }
            execute_guard = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                execute_guard_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{execute_guard['confirmation_id']}/decision",
                {"decision": "approve", "note": "Owner approves the exact execution permission guard."},
                token,
            )
            FakeWriteAdapter.reset_control()
            execute_status, _execute_payload = _post_status(
                base_url,
                f"/confirmations/{execute_guard['confirmation_id']}/execute",
                {"idempotency_key": "draft-permission-execute-v1"},
                restricted_token,
            )
            execute_after = repo.get_confirmation(
                company_id=user["default_company_id"], confirmation_id=execute_guard["confirmation_id"]
            ) or {}
            if (
                execute_status != 403
                or execute_after.get("status") != "approved"
                or FakeWriteAdapter.draft_execute_attempt_count != 0
            ):
                return fail("a role without execute_confirmed_action must not execute an approved eBay draft write")

            crash_recovery_body = publish_payload()
            crash_recovery_body.pop("workflow_scope", None)
            crash_recovery_body["listing"] = {
                **crash_recovery_body["listing"],
                "sku": "DRAFT-EXPIRED-PREWRITE-001",
                "title": "Expired prewrite recovery guard",
            }
            crash_recovery = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                crash_recovery_body,
                token,
            )["confirmation"]
            crash_recovery = _post(
                base_url,
                f"/confirmations/{crash_recovery['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve the exact expired prewrite recovery guard."},
                token,
            )["confirmation"]
            crash_idempotency_key = "draft-expired-prewrite-recovery-v1"
            crash_payload = crash_recovery.get("item", {}).get("publish_payload") or {}
            crash_boundary = repo.unpublished_draft_execution_credential_boundary(
                company_id=user["default_company_id"],
                store_id=store["store_id"],
            )
            crash_binding = {
                "confirmation_id": str(crash_recovery["confirmation_id"]),
                "company_id": str(user["default_company_id"]),
                "store_id": str(store["store_id"]),
                "action_type": "save_ebay_listing_draft",
                "task_id": str(crash_recovery["task_id"]),
                "idempotency_key": crash_idempotency_key,
                "marketplace_id": "EBAY_US",
                "payload_sha256": hashlib.sha256(
                    json.dumps(crash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "preparation_sha256": hashlib.sha256(
                    f"fake-http-preparation:{crash_recovery['confirmation_id']}:{crash_idempotency_key}".encode("utf-8")
                ).hexdigest(),
                "contract_version": "2026-08-13-unpublished-draft-credential-v1",
                **{
                    key: str(crash_boundary.get(key) or "")
                    for key in (
                        "connection_id_sha256",
                        "credential_ref_sha256",
                        "oauth_request_id_sha256",
                        "seller_identity_sha256",
                    )
                },
            }
            _crash_claimed, abandoned_capability = repo.claim_unpublished_draft_execution(
                company_id=user["default_company_id"],
                confirmation_id=crash_recovery["confirmation_id"],
                user_id=user["user_id"],
                expected_binding=crash_binding,
                expected_access_epochs=repo.access_session_epochs(user_id=user['user_id'],company_id=user['default_company_id']),
                operation_plan=build_ebay_execution_plan(request=ExecutionRequest(action_type='save_ebay_listing_draft',
                    company_id=user['default_company_id'],store_id=store['store_id'],user_id=user['user_id'],
                    task_id=crash_recovery['task_id'],confirmation_id=crash_recovery['confirmation_id'],platform='ebay',
                    payload=crash_payload,confirmed_by=user['user_id'],confirmed_at=crash_recovery['decided_at'],
                    idempotency_key=crash_idempotency_key),marketplace_id='EBAY_US',credential_boundary=crash_boundary,draft_offer_id=''),
            )
            with repo._connect() as conn:
                conn.execute(
                    "update external_execution_claims set expires_at = ? where confirmation_id = ?",
                    (
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                        crash_recovery["confirmation_id"],
                    ),
                )
            FakeWriteAdapter.reset_control()
            crash_status, _crash_response = _post_status(
                base_url,
                f"/confirmations/{crash_recovery['confirmation_id']}/execute",
                {"idempotency_key": crash_idempotency_key},
                token,
            )
            crash_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=crash_recovery["confirmation_id"],
            ) or {}
            if (
                crash_status != 409
                or crash_terminal.get("status") != "needs_revision"
                or FakeWriteAdapter.draft_call_count != 0
            ):
                return fail("an expired zero-write prewrite claim must retire without executing the old approval")
            for key in ('item','decided_at','decided_by','decision_note'):
                if crash_terminal.get(key)!=crash_recovery.get(key): return fail('expired claim changed original decision')
            new_crash=_post(base_url,f"/stores/{store['store_id']}/ebay-draft-confirmation",
                {**crash_recovery_body,'replaces_confirmation_id':crash_recovery['confirmation_id']},token)['confirmation']
            if new_crash['status']!='pending' or new_crash['confirmation_id']==crash_recovery['confirmation_id']:
                return fail('expired claim recovery must create a separately pending linked confirmation')
            _post(base_url,f"/confirmations/{new_crash['confirmation_id']}/decision",{'decision':'approve','note':'Fresh crash recovery approval'},token)
            _post(base_url,f"/confirmations/{new_crash['confirmation_id']}/execute",{'idempotency_key':'fresh-crash-recovery'},token)
            if FakeWriteAdapter.draft_call_count!=1: return fail('fresh crash recovery must execute exactly once')
            try:
                abandoned_capability.consume()
            except ConfirmationDecisionConflict:
                pass
            else:
                return fail("the abandoned prewrite capability must remain invalid after HTTP recovery")

            FakeWriteAdapter.reset_control()
            draft_body = publish_payload()
            draft_body.pop("workflow_scope", None)
            draft_body["listing"] = {
                **draft_body["listing"],
                "sku": "DRAFT-ONLY-001",
                "title": "Draft only smoke widget",
            }
            draft_confirmation = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                draft_body,
                token,
            )["confirmation"]
            draft_approval = _post(
                base_url,
                f"/confirmations/{draft_confirmation['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve exactly one unpublished draft write."},
                token,
            )
            with repo._connect() as conn:
                conn.execute(
                    "update confirmations set decided_at = ? where company_id = ? and confirmation_id = ?",
                    (
                        "2000-01-01T00:00:00+00:00",
                        user["default_company_id"],
                        draft_confirmation["confirmation_id"],
                    ),
                )
            stale_status, stale_payload = _post_status(
                base_url,
                f"/confirmations/{draft_confirmation['confirmation_id']}/execute",
                {"idempotency_key": "draft-stale-must-not-claim"},
                token,
            )
            if stale_status != 409 or stale_payload.get("error") != "external_execution_confirmation_not_fresh":
                return fail(f"expired draft execution approval must fail closed before claim: {stale_status} {stale_payload}")
            stale_confirmation = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=draft_confirmation["confirmation_id"],
            ) or {}
            if stale_confirmation.get("status") != "approved" or FakeWriteAdapter.draft_call_count != 0:
                return fail("expired draft execution approval must remain unconsumed and make zero adapter calls")
            with repo._connect() as conn:
                conn.execute(
                    "update confirmations set decided_at = ? where company_id = ? and confirmation_id = ?",
                    (
                        draft_approval['confirmation']['decided_at'],
                        user["default_company_id"],
                        draft_confirmation["confirmation_id"],
                    ),
                )
            draft_path = f"/confirmations/{draft_confirmation['confirmation_id']}/execute"
            draft_execute_body = {"idempotency_key": "draft-only-execute-v1"}
            FakeWriteAdapter.reset_control()
            FakeWriteAdapter.block_publish = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                first_draft = pool.submit(_post_status, base_url, draft_path, draft_execute_body, token)
                if not FakeWriteAdapter.publish_started.wait(timeout=5):
                    return fail("first draft execution did not reach the fake adapter")
                second_draft = pool.submit(_post_status, base_url, draft_path, draft_execute_body, token)
                time.sleep(0.2)
                FakeWriteAdapter.release_publish.set()
                draft_results = [first_draft.result(timeout=10), second_draft.result(timeout=10)]
            if FakeWriteAdapter.draft_call_count != 1:
                return fail("concurrent draft execute must claim before exactly one adapter call")
            if sorted(status for status, _payload in draft_results) != [200, 409]:
                return fail(f"concurrent draft execute must return one success and one 409: {draft_results}")
            stored_draft = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=draft_confirmation["confirmation_id"],
            ) or {}
            if stored_draft.get("status") != "executed":
                return fail(
                    "successful draft execution must durably become executed: "
                    f"stored_status={stored_draft.get('status')} results={[status for status, _payload in draft_results]}"
                )
            if FakeWriteAdapter.last_draft_payload != draft_confirmation.get("item", {}).get("publish_payload"):
                return fail("draft execution body must not override the approved payload snapshot")

            FakeWriteAdapter.reset_control()
            prewrite_body = publish_payload()
            prewrite_body.pop("workflow_scope", None)
            prewrite_body["listing"] = {
                **prewrite_body["listing"],
                "sku": "DRAFT-PREWRITE-001",
                "title": "Prewrite retry smoke widget",
            }
            prewrite_confirmation = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                prewrite_body,
                token,
            )["confirmation"]
            prewrite_approval = _post(
                base_url,
                f"/confirmations/{prewrite_confirmation['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve the deterministic prewrite abort regression."},
                token,
            )
            prewrite_path = f"/confirmations/{prewrite_confirmation['confirmation_id']}/execute"
            FakeWriteAdapter.fail_draft_before_consume = True
            prewrite_status, _prewrite_payload = _post_status(
                base_url,
                prewrite_path,
                {"idempotency_key": "draft-prewrite-execute-v1"},
                token,
            )
            prewrite_restored = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=prewrite_confirmation["confirmation_id"],
            ) or {}
            if (
                prewrite_status != 409
                or prewrite_restored.get("status") != "needs_revision"
                or FakeWriteAdapter.draft_call_count != 0
            ):
                return fail("a deterministic prewrite exception must retire old authority with zero draft writes")
            for key in ('item','decided_at','decided_by','decision_note'):
                if prewrite_restored.get(key)!=prewrite_approval['confirmation'].get(key): return fail('prewrite failure changed approval history')
            FakeWriteAdapter.fail_draft_before_consume = False
            retired_status,_=_post_status(base_url,prewrite_path,{'idempotency_key':'old-must-not-replay'},token)
            if retired_status!=409 or FakeWriteAdapter.draft_call_count: return fail('retired approval must not replay')
            recovered=_post(base_url,f"/stores/{store['store_id']}/ebay-draft-confirmation",
                {**prewrite_body,'replaces_confirmation_id':prewrite_confirmation['confirmation_id']},token)['confirmation']
            if recovered['status']!='pending' or recovered['confirmation_id']==prewrite_confirmation['confirmation_id']:
                return fail('prewrite recovery must need a distinct pending approval')
            unapproved_status,_=_post_status(base_url,f"/confirmations/{recovered['confirmation_id']}/execute",{},token)
            if unapproved_status!=409 or FakeWriteAdapter.draft_call_count: return fail('new pending cannot inherit old approval')
            _post(base_url,f"/confirmations/{recovered['confirmation_id']}/decision",{'decision':'approve','note':'Separate recovery approval'},token)
            recovered_status, _recovered_payload = _post_status(
                base_url,
                f"/confirmations/{recovered['confirmation_id']}/execute",
                {"idempotency_key": "draft-prewrite-execute-v1"},
                token,
            )
            recovered_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=recovered["confirmation_id"],
            ) or {}
            if recovered_status != 200 or recovered_terminal.get("status") != "executed":
                return fail("a safely retired zero-write request permits only the newly approved linked execution")

            FakeWriteAdapter.reset_control()
            uncertain_body = publish_payload()
            uncertain_body.pop("workflow_scope", None)
            uncertain_body["listing"] = {
                **uncertain_body["listing"],
                "sku": "DRAFT-UNCERTAIN-001",
                "title": "Uncertain draft smoke widget",
            }
            uncertain_confirmation = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-draft-confirmation",
                uncertain_body,
                token,
            )["confirmation"]
            _post(
                base_url,
                f"/confirmations/{uncertain_confirmation['confirmation_id']}/decision",
                {"decision": "approve", "note": "Approve the post-consume failure regression."},
                token,
            )
            FakeWriteAdapter.fail_draft_after_consume = True
            uncertain_path = f"/confirmations/{uncertain_confirmation['confirmation_id']}/execute"
            uncertain_status, uncertain_payload = _post_status(
                base_url,
                uncertain_path,
                {"idempotency_key": "draft-uncertain-execute-v1"},
                token,
            )
            if (
                uncertain_status != 409
                or uncertain_payload.get("error") != "external_execution_processing_manual_reconcile"
            ):
                return fail(
                    "a post-consume draft failure must return the fixed manual-reconcile response: "
                    f"{uncertain_status} {uncertain_payload}"
                )
            uncertain_terminal = repo.get_confirmation(
                company_id=user["default_company_id"],
                confirmation_id=uncertain_confirmation["confirmation_id"],
            ) or {}
            if uncertain_terminal.get("status") != "external_execution_processing_manual_reconcile":
                return fail("a post-consume draft failure must retain the durable manual-reconcile state")
            retry_status, _retry_payload = _post_status(
                base_url,
                uncertain_path,
                {"idempotency_key": "draft-uncertain-execute-v1"},
                token,
            )
            if retry_status != 409 or FakeWriteAdapter.draft_execute_attempt_count != 1:
                return fail("a post-consume draft failure must never retry the adapter automatically")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            api_server.build_account_health_snapshot = original_health_builder
    print("PASS jiejing_new_ebay_account_publish_http_chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
