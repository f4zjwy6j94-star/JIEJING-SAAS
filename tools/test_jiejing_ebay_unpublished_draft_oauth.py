#!/usr/bin/env python3
"""Focused HTTP regression for confirmation-gated unpublished-draft OAuth."""

from __future__ import annotations

import json
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
from jiejing_saas.ebay_oauth import EbayOAuthPlanner  # noqa: E402
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.secret_store import SecretStoreBoundary  # noqa: E402
from jiejing_saas.security import SessionManager  # noqa: E402


SOURCE = "controlled_ebay_unpublished_draft_save"
STEP = "unpublished_draft_oauth_authorization_gate"
PROFILE = "seller_unpublished_draft"
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]


def _post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    token: str,
) -> tuple[int, dict[str, Any]]:
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="jiejing-ebay-draft-oauth-", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        repository = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        account = repository.create_user_with_company(
            email="draft-oauth-owner@example.com",
            password="Password123!",
            company_name="Draft OAuth fixture",
        )
        user = account["user"]
        company_id = user["default_company_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Draft OAuth store", "marketplace": "EBAY_US"},
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        settings.ebay_client_id = "draft-oauth-client-fixture"
        settings.ebay_ru_name = "draft-oauth-runame-fixture"
        sessions = SessionManager(secret="draft-oauth-session-secret")

        class TestHandler(SaaSBackendHandler):
            pass

        TestHandler.repository = repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        TestHandler.ebay_oauth_planner = EbayOAuthPlanner(settings)
        TestHandler.secret_store_boundary = SecretStoreBoundary(settings)

        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        token = sessions.create_token(
            user_id=user["user_id"],
            company_id=company_id,
            email=user["email"],
        )
        try:
            viewer_account = repository.create_user_with_company(
                email="draft-oauth-viewer@example.com",
                password="Password123!",
                company_name="Viewer fixture company",
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
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                {"scope_profile": PROFILE},
                viewer_token,
            )
            if viewer_status != 403:
                raise AssertionError("member without manage_connections must not create a draft OAuth confirmation")

            legacy_status, legacy_body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/publish-plan",
                {"scopes": SCOPES},
                token,
            )
            if legacy_status not in {409, 410}:
                raise AssertionError(f"legacy publish-plan must be fixed fail-closed; status={legacy_status}")
            if set(legacy_body) & {"oauth_plan", "oauth_request", "authorization_url", "state_nonce"}:
                raise AssertionError("legacy publish-plan rejection must remain value-free")
            if repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"]):
                raise AssertionError("legacy publish-plan must never create an OAuth request or state")

            status, body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                {"scope_profile": PROFILE},
                token,
            )
            if status != 201:
                raise AssertionError(f"draft OAuth intake must create one pending confirmation; status={status}")
            confirmation = body.get("oauth_confirmation") or {}
            if not (
                confirmation.get("status") == "pending"
                and confirmation.get("company_id") == company_id
                and confirmation.get("store_id") == store["store_id"]
                and confirmation.get("action_type") == "ebay_oauth_scope_change"
                and confirmation.get("source") == SOURCE
                and confirmation.get("requested_step") == STEP
                and confirmation.get("scope_profile") == PROFILE
                and confirmation.get("oauth_state_created") is False
                and confirmation.get("authorization_url_created") is False
                and confirmation.get("oauth_request_created") is False
                and confirmation.get("real_platform_writes_enabled") is False
                and confirmation.get("public_publish_enabled") is False
                and confirmation.get("secret_exposed") is False
            ):
                raise AssertionError("draft OAuth intake must return the exact safe pending contract")
            if repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"]):
                raise AssertionError("pending draft OAuth confirmation must not create state, URL, or request")
            duplicate_intake_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                {"scope_profile": PROFILE},
                token,
            )
            if duplicate_intake_status != 409:
                raise AssertionError("an exact active draft OAuth confirmation must not be duplicated")
            wrong_intake_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                {"scope_profile": "seller_read_only"},
                token,
            )
            if wrong_intake_status != 400:
                raise AssertionError("draft OAuth intake must reject the wrong scope profile")

            confirmation_id = str(confirmation.get("confirmation_id") or "")
            approval_status, approval_body = _post(
                base_url,
                f"/confirmations/{confirmation_id}/decision",
                {"decision": "approve", "note": "Approve exact unpublished-draft OAuth access."},
                token,
            )
            if approval_status != 201 or (approval_body.get("confirmation") or {}).get("status") != "approved":
                raise AssertionError("confirmation center must approve the exact draft OAuth card")

            viewer_plan_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-plan",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                viewer_token,
            )
            if viewer_plan_status != 403:
                raise AssertionError("member without manage_connections must not consume a draft OAuth approval")

            other_account = repository.create_user_with_company(
                email="draft-oauth-other-owner@example.com",
                password="Password123!",
                company_name="Other tenant fixture",
            )
            other_user = other_account["user"]
            other_company_id = other_user["default_company_id"]
            other_company_store = repository.create_store(
                company_id=other_company_id,
                user_id=other_user["user_id"],
                payload={"platform": "ebay", "store_name": "Other tenant store", "marketplace": "EBAY_US"},
            )
            other_company_token = sessions.create_token(
                user_id=other_user["user_id"],
                company_id=other_company_id,
                email=other_user["email"],
            )
            cross_tenant_status, _ = _post(
                base_url,
                f"/stores/{other_company_store['store_id']}/ebay-oauth/unpublished-draft-plan",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                other_company_token,
            )
            if cross_tenant_status != 409:
                raise AssertionError("a draft approval from another tenant must fail closed")

            other_store = repository.create_store(
                company_id=company_id,
                user_id=user["user_id"],
                payload={"platform": "ebay", "store_name": "Other draft store", "marketplace": "EBAY_US"},
            )
            negative_requests = [
                (store["store_id"], {}, 409),
                (store["store_id"], {"confirmation_id": confirmation_id, "scope_profile": "seller_read_only", "scopes": SCOPES}, 400),
                (store["store_id"], {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": [*SCOPES, SCOPES[-1]]}, 400),
                (store["store_id"], {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": "not-a-list"}, 400),
                (other_store["store_id"], {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES}, 409),
            ]
            for target_store_id, payload, expected_status in negative_requests:
                rejected_status, rejected_body = _post(
                    base_url,
                    f"/stores/{target_store_id}/ebay-oauth/unpublished-draft-plan",
                    payload,
                    token,
                )
                if rejected_status != expected_status:
                    raise AssertionError(f"malformed/mismatched draft OAuth plan must fail closed; status={rejected_status}")
                if set(rejected_body) & {"oauth_plan", "oauth_request", "authorization_url", "state_nonce"}:
                    raise AssertionError("draft OAuth plan rejection must remain value-free")
            if repository.get_confirmation(company_id=company_id, confirmation_id=confirmation_id).get("status") != "approved":
                raise AssertionError("rejected draft plan inputs must not consume the exact approval")
            if repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"]):
                raise AssertionError("rejected draft plan inputs must not persist OAuth request/state")

            plan_status, plan_body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-plan",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                token,
            )
            if plan_status != 201:
                raise AssertionError(f"exact approved draft OAuth plan must be created once; status={plan_status}")
            plan = plan_body.get("oauth_plan") or {}
            request = plan_body.get("oauth_request") or {}
            if not (
                plan.get("status") == "ready_to_redirect"
                and plan.get("scope_profile") == PROFILE
                and plan.get("confirmation_id") == confirmation_id
                and plan.get("scopes") == SCOPES
                and plan.get("draft_save_capability_requested") is True
                and plan.get("public_publish_enabled") is False
                and plan.get("real_platform_writes_enabled") is False
                and plan.get("secret_exposed") is False
                and request.get("request", {}).get("confirmation_id") == confirmation_id
                and request.get("request", {}).get("company_id") == company_id
                and request.get("request", {}).get("store_id") == store["store_id"]
                and request.get("request", {}).get("status") == "ready_to_redirect"
                and request.get("request", {}).get("write_actions_requested") == ["save_ebay_listing_draft"]
                and request.get("request", {}).get("draft_save_capability_requested") is True
                and request.get("request", {}).get("public_publish_enabled") is False
                and request.get("request", {}).get("real_platform_writes_enabled") is False
                and request.get("scopes") == SCOPES
                and request.get("real_platform_writes_enabled") is False
                and request.get("secret_exposed") is False
                and (plan_body.get("draft_oauth_boundary") or {}).get("company_id") == company_id
                and (plan_body.get("draft_oauth_boundary") or {}).get("store_id") == store["store_id"]
                and (plan_body.get("draft_oauth_boundary") or {}).get("confirmation_id") == confirmation_id
                and (plan_body.get("draft_oauth_boundary") or {}).get("scope_profile") == PROFILE
                and (plan_body.get("draft_oauth_boundary") or {}).get("scopes") == SCOPES
                and (plan_body.get("draft_oauth_boundary") or {}).get("state_nonce") == plan.get("state_nonce")
                and (plan_body.get("draft_oauth_boundary") or {}).get("authorization_url") == plan.get("authorization_url")
            ):
                raise AssertionError("draft OAuth plan/request must preserve the exact draft-only security contract")
            requests = repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"])
            if len(requests) != 1:
                raise AssertionError("exact draft OAuth approval must create exactly one request")
            resume_status, resume_body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-resume",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                token,
            )
            resumed_plan = resume_body.get("oauth_plan") or {}
            resumed_request = resume_body.get("oauth_request") or {}
            if not (
                resume_status == 200
                and resumed_plan == request.get("request")
                and resumed_request.get("request") == request.get("request")
                and resumed_request.get("confirmation_id") == confirmation_id
                and resumed_request.get("auth_url") == request.get("auth_url")
                and resumed_request.get("state_nonce") == request.get("state_nonce")
                and resumed_request.get("draft_save_capability_requested") is True
                and resumed_request.get("public_publish_enabled") is False
                and resumed_request.get("real_platform_writes_enabled") is False
                and resumed_request.get("secret_exposed") is False
                and len(repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"])) == 1
            ):
                raise AssertionError("an exact unconsumed draft OAuth request must resume without creating another request")
            viewer_resume_status, viewer_resume_body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-resume",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                viewer_token,
            )
            if viewer_resume_status != 403 or set(viewer_resume_body) & {
                "oauth_plan",
                "oauth_request",
                "authorization_url",
                "state_nonce",
            }:
                raise AssertionError("member without manage_connections must not resume a draft OAuth request")
            resume_attacks = [
                ({"confirmation_id": "wrong-confirmation", "scope_profile": PROFILE, "scopes": SCOPES}, 409),
                ({"confirmation_id": confirmation_id, "scope_profile": "seller_read_only", "scopes": SCOPES}, 400),
                ({"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": list(reversed(SCOPES))}, 400),
            ]
            for resume_payload, expected_resume_status in resume_attacks:
                attacked_status, attacked_body = _post(
                    base_url,
                    f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-resume",
                    resume_payload,
                    token,
                )
                if attacked_status != expected_resume_status or set(attacked_body) & {
                    "oauth_plan",
                    "oauth_request",
                    "authorization_url",
                    "state_nonce",
                }:
                    raise AssertionError("malformed or mismatched draft OAuth resume must fail closed and value-free")
            wrong_store_resume_status, wrong_store_resume_body = _post(
                base_url,
                f"/stores/{other_store['store_id']}/ebay-oauth/unpublished-draft-resume",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                token,
            )
            if wrong_store_resume_status != 409 or set(wrong_store_resume_body) & {
                "oauth_plan",
                "oauth_request",
                "authorization_url",
                "state_nonce",
            }:
                raise AssertionError("a different store must not resume the current store draft OAuth request")
            retry_status, _ = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-plan",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                token,
            )
            if retry_status != 409 or len(repository.list_oauth_authorization_requests(company_id=company_id, store_id=store["store_id"])) != 1:
                raise AssertionError("consumed draft approval must never create a second OAuth request")
            import sqlite3

            expired_request_time = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
            with sqlite3.connect(settings.db_path) as conn:
                conn.execute(
                    "update oauth_authorization_requests set updated_at = ? where company_id = ? and store_id = ?",
                    (expired_request_time, company_id, store["store_id"]),
                )
            expired_resume_status, expired_resume_body = _post(
                base_url,
                f"/stores/{store['store_id']}/ebay-oauth/unpublished-draft-resume",
                {"confirmation_id": confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                token,
            )
            if expired_resume_status != 409 or set(expired_resume_body) & {
                "oauth_plan",
                "oauth_request",
                "authorization_url",
                "state_nonce",
            }:
                raise AssertionError("an expired draft OAuth request must not resume or disclose authorization state")

            invalid_times = {
                "expired": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat(),
                "future": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                "naive": datetime.now().replace(microsecond=0).isoformat(),
                "malformed": "not-a-time",
            }
            for label, decided_at in invalid_times.items():
                invalid_store = repository.create_store(
                    company_id=company_id,
                    user_id=user["user_id"],
                    payload={"platform": "ebay", "store_name": f"{label} approval store", "marketplace": "EBAY_US"},
                )
                intake_status, intake_body = _post(
                    base_url,
                    f"/stores/{invalid_store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                    {"scope_profile": PROFILE},
                    token,
                )
                invalid_confirmation_id = str((intake_body.get("oauth_confirmation") or {}).get("confirmation_id") or "")
                if intake_status != 201 or not invalid_confirmation_id:
                    raise AssertionError(f"{label} approval fixture intake failed")
                decision_status, _ = _post(
                    base_url,
                    f"/confirmations/{invalid_confirmation_id}/decision",
                    {"decision": "approve", "note": f"{label} timestamp fixture"},
                    token,
                )
                if decision_status != 201:
                    raise AssertionError(f"{label} approval fixture decision failed")
                with sqlite3.connect(settings.db_path) as conn:
                    conn.execute(
                        "update confirmations set decided_at = ? where confirmation_id = ?",
                        (decided_at, invalid_confirmation_id),
                    )
                invalid_status, invalid_body = _post(
                    base_url,
                    f"/stores/{invalid_store['store_id']}/ebay-oauth/unpublished-draft-plan",
                    {"confirmation_id": invalid_confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                    token,
                )
                if invalid_status != 409 or set(invalid_body) & {"oauth_plan", "oauth_request", "state_nonce", "authorization_url"}:
                    raise AssertionError(f"{label} draft approval must fail closed without OAuth state")
                if repository.list_oauth_authorization_requests(company_id=company_id, store_id=invalid_store["store_id"]):
                    raise AssertionError(f"{label} draft approval must not persist OAuth request/state")
                replacement_status, replacement_body = _post(
                    base_url,
                    f"/stores/{invalid_store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                    {"scope_profile": PROFILE},
                    token,
                )
                if label == "expired":
                    replacement = replacement_body.get("oauth_confirmation") or {}
                    if not (
                        replacement_status == 201
                        and replacement.get("status") == "pending"
                        and replacement.get("confirmation_id")
                        and replacement.get("confirmation_id") != invalid_confirmation_id
                        and repository.get_confirmation(
                            company_id=company_id,
                            confirmation_id=invalid_confirmation_id,
                        ).get("status") == "expired"
                    ):
                        raise AssertionError("expired draft OAuth approval must be atomically superseded by one new pending confirmation")
                    if repository.list_oauth_authorization_requests(company_id=company_id, store_id=invalid_store["store_id"]):
                        raise AssertionError("expired draft OAuth replacement must not create OAuth request/state")
                elif (
                    replacement_status != 409
                    or repository.get_confirmation(
                        company_id=company_id,
                        confirmation_id=invalid_confirmation_id,
                    ).get("status") != "approved"
                ):
                    raise AssertionError(f"{label} draft OAuth approval must not be replaced")

            concurrent_store = repository.create_store(
                company_id=company_id,
                user_id=user["user_id"],
                payload={"platform": "ebay", "store_name": "Concurrent draft store", "marketplace": "EBAY_US"},
            )
            _, concurrent_intake = _post(
                base_url,
                f"/stores/{concurrent_store['store_id']}/ebay-oauth/unpublished-draft-confirmation",
                {"scope_profile": PROFILE},
                token,
            )
            concurrent_confirmation_id = str((concurrent_intake.get("oauth_confirmation") or {}).get("confirmation_id") or "")
            _post(
                base_url,
                f"/confirmations/{concurrent_confirmation_id}/decision",
                {"decision": "approve", "note": "Concurrent exact draft approval fixture"},
                token,
            )

            def invoke_plan(_index: int) -> int:
                response_status, _ = _post(
                    base_url,
                    f"/stores/{concurrent_store['store_id']}/ebay-oauth/unpublished-draft-plan",
                    {"confirmation_id": concurrent_confirmation_id, "scope_profile": PROFILE, "scopes": SCOPES},
                    token,
                )
                return response_status

            with ThreadPoolExecutor(max_workers=4) as executor:
                concurrent_statuses = list(executor.map(invoke_plan, range(4)))
            if concurrent_statuses.count(201) != 1 or concurrent_statuses.count(409) != 3:
                raise AssertionError(f"draft plan CAS must allow one request only: {concurrent_statuses}")
            if len(repository.list_oauth_authorization_requests(company_id=company_id, store_id=concurrent_store["store_id"])) != 1:
                raise AssertionError("draft plan CAS must persist exactly one request")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print("PASS jiejing_ebay_unpublished_draft_oauth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
