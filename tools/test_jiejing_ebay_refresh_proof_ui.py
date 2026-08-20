#!/usr/bin/env python3
"""Focused contract for the merchant-visible, backend-only eBay refresh proof."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _FakeRepository:
    def __init__(self) -> None:
        self.boundary = {
            "authorized": True,
            "current_store_selected": True,
            "strong_identity_ready": True,
            "backend_provenance_ready": True,
            "store_id_sha256": _sha("store-current"),
            "connection_id_sha256": _sha("connection-current"),
            "secret_exposed": False,
        }
        self.connections = [
            {
                "connection_id": "connection-current",
                "secret_ref": "secret-current",
            }
        ]
        self.secret = {
            "secret_ref": "secret-current",
            "company_id": "company-current",
            "store_id": "store-current",
            "provider": "ebay",
            "purpose": "ebay_refresh_token",
            "status": "managed_vault_stored",
        }
        self.refresh_audit: dict[str, object] | None = None
        self.calls: list[str] = []

    def get_store_for_company(self, **kwargs: object) -> dict[str, object] | None:
        self.calls.append("store")
        return {"store_id": "store-current", "platform": "ebay"} if kwargs.get("store_id") == "store-current" else None

    def current_ebay_read_only_oauth_boundary(self, **_kwargs: object) -> dict[str, object]:
        self.calls.append("current_boundary")
        return dict(self.boundary)

    def find_latest_audit_log_by_target(self, **_kwargs: object) -> dict[str, object] | None:
        self.calls.append("refresh_audit")
        return dict(self.refresh_audit) if self.refresh_audit else None

    def ebay_read_only_oauth_boundary(self, **_kwargs: object) -> dict[str, object]:
        self.calls.append("boundary")
        return dict(self.boundary)

    def list_connections(self, **_kwargs: object) -> list[dict[str, object]]:
        self.calls.append("connections")
        return [dict(item) for item in self.connections]

    def get_secret_ref(self, **_kwargs: object) -> dict[str, object] | None:
        self.calls.append("secret")
        return dict(self.secret) if self.secret else None


def _evidence(*, ready: bool = False) -> dict[str, object]:
    return {
        "current_store_selected": True,
        "refresh_success_ready": ready,
        "refresh_same_connection_ready": ready,
        "connection_id_sha256": _sha("connection-current"),
        "secret_exposed": False,
    }


def _get_json(base_url: str, path: str, token: str = "") -> tuple[int, dict[str, object]]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(f"{base_url}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return int(exc.code), json.loads(raw) if raw else {}


def main() -> int:
    from jiejing_saas import api_server
    from jiejing_saas.config import SaaSSettings
    from jiejing_saas.ebay_oauth import EbayOAuthPlanner
    from jiejing_saas.repository import SaaSRepository
    from jiejing_saas.secret_store import SecretStoreBoundary
    from jiejing_saas.security import SessionManager

    proof_builder = getattr(api_server, "build_current_store_ebay_refresh_evidence", None)
    if not callable(proof_builder):
        return fail("backend must expose a lightweight current-store refresh proof builder")
    pending_repo = _FakeRepository()
    pending_proof = proof_builder(repository=pending_repo, company_id="company-current", store_id="store-current")
    if pending_proof.get("status") != "pending" or pending_proof.get("authorized") is not True:
        return fail(f"exact authorized store without refresh audit must remain pending: {pending_proof}")
    pending_repo.refresh_audit = {
        "company_id": "company-current",
        "store_id": "store-current",
        "actor_type": "system",
        "target_id": "store-current",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "details": {
            "connection_id_sha256": _sha("connection-current"),
            "credential_ref_sha256": _sha("secret-current"),
            "ok": True,
            "status": "refreshed",
            "source": "backend_vault_secret_ref_refresh",
            "secret_exposed": False,
        },
    }
    verified_proof = proof_builder(repository=pending_repo, company_id="company-current", store_id="store-current")
    if verified_proof.get("status") != "verified" or verified_proof.get("refresh_same_connection_ready") is not True:
        return fail(f"fresh same-connection audit must verify the selected store: {verified_proof}")
    pending_repo.refresh_audit["details"] = {**pending_repo.refresh_audit["details"], "connection_id_sha256": _sha("other-connection")}
    mismatched_proof = proof_builder(repository=pending_repo, company_id="company-current", store_id="store-current")
    if mismatched_proof.get("status") != "pending" or mismatched_proof.get("refresh_success_ready") is not False:
        return fail(f"wrong-connection refresh evidence must fail closed: {mismatched_proof}")

    resolver = getattr(api_server, "_resolve_merchant_visible_ebay_refresh_probe", None)
    sanitizer = getattr(api_server, "_merchant_safe_ebay_refresh_probe_result", None)
    if not callable(resolver) or not callable(sanitizer):
        return fail("backend refresh proof must expose a testable exact-boundary resolver and value-free sanitizer")

    fresh_repo = _FakeRepository()
    with patch.object(api_server, "build_current_store_ebay_refresh_evidence", return_value=_evidence(ready=True)):
        fresh = resolver(fresh_repo, company_id="company-current", store_id="store-current")
    if fresh.get("status") != "already_verified" or fresh_repo.calls:
        return fail(f"fresh same-connection proof must avoid Vault/provider work: result={fresh} calls={fresh_repo.calls}")

    unauthorized_repo = _FakeRepository()
    unauthorized_repo.boundary["authorized"] = False
    with patch.object(api_server, "build_current_store_ebay_refresh_evidence", return_value=_evidence()):
        unauthorized = resolver(unauthorized_repo, company_id="company-current", store_id="store-current")
    if unauthorized.get("blocked_by") != "oauth_refresh_strong_boundary_required" or unauthorized_repo.calls != ["boundary"]:
        return fail(f"unauthorized refresh must fail before connection/secret access: {unauthorized} {unauthorized_repo.calls}")

    duplicate_repo = _FakeRepository()
    duplicate_repo.connections.append(dict(duplicate_repo.connections[0]))
    with patch.object(api_server, "build_current_store_ebay_refresh_evidence", return_value=_evidence()):
        duplicate = resolver(duplicate_repo, company_id="company-current", store_id="store-current")
    if duplicate.get("blocked_by") != "oauth_refresh_connection_binding_invalid" or "secret" in duplicate_repo.calls:
        return fail(f"duplicate connection binding must fail before secret resolution: {duplicate} {duplicate_repo.calls}")

    bad_secret_repo = _FakeRepository()
    bad_secret_repo.secret["provider"] = "other"
    with patch.object(api_server, "build_current_store_ebay_refresh_evidence", return_value=_evidence()):
        bad_secret = resolver(bad_secret_repo, company_id="company-current", store_id="store-current")
    if bad_secret.get("blocked_by") != "oauth_refresh_secret_binding_invalid":
        return fail(f"wrong-provider secret must fail closed: {bad_secret}")

    exact_repo = _FakeRepository()
    with patch.object(api_server, "build_current_store_ebay_refresh_evidence", return_value=_evidence()):
        exact = resolver(exact_repo, company_id="company-current", store_id="store-current")
    if exact.get("status") != "ready" or exact.get("secret_ref") != exact_repo.secret:
        return fail(f"exact current-store Vault binding must be returned only to the backend caller: {exact}")

    private_result = {
        "ok": True,
        "status": "refreshed",
        "source": "backend_vault_secret_ref_refresh",
        "company_id": "company-current",
        "store_id": "store-current",
        "secret_ref": "SECRET-REF-SENTINEL",
        "access_token": "ACCESS-TOKEN-SENTINEL",
        "refresh_token": "REFRESH-TOKEN-SENTINEL",
        "provider_error": {"message": "PROVIDER-ERROR-SENTINEL"},
        "expires_in": 7200,
        "refreshed_at": 123456,
        "secret_exposed": False,
    }
    public_result = sanitizer(private_result)
    serialized = json.dumps(public_result, ensure_ascii=False)
    for forbidden in ("SECRET-REF-SENTINEL", "ACCESS-TOKEN-SENTINEL", "REFRESH-TOKEN-SENTINEL", "PROVIDER-ERROR-SENTINEL"):
        if forbidden in serialized:
            return fail(f"merchant refresh proof leaked a private marker: {forbidden}")
    required_false = {
        "access_token_returned_to_frontend",
        "access_token_returned_to_runtime",
        "access_token_stored_in_database",
        "refresh_token_returned_to_frontend",
        "real_platform_writes_enabled",
        "secret_exposed",
    }
    if public_result.get("ok") is not True or any(public_result.get(key) is not False for key in required_false):
        return fail(f"merchant refresh proof safety flags must be exact false: {public_result}")

    with tempfile.TemporaryDirectory(prefix="jiejing-refresh-proof-http-", ignore_cleanup_errors=True) as temp_dir:
        root = Path(temp_dir)
        repository = SaaSRepository(root / "saas.sqlite", database_engine="sqlite")
        account = repository.create_user_with_company(
            email="refresh-proof-owner@example.com",
            password="Password123!",
            company_name="Refresh proof fixture",
        )
        user = account["user"]
        company_id = user["default_company_id"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Refresh proof store", "marketplace": "EBAY_US"},
        )
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        sessions = SessionManager(secret="refresh-proof-session-secret")

        class TestHandler(api_server.SaaSBackendHandler):
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
        token = sessions.create_token(user_id=user["user_id"], company_id=company_id, email=user["email"])
        safe_boundary = {
            "status": "authorized",
            "authorized": True,
            "pending": False,
            "strong_identity_ready": True,
            "backend_provenance_ready": True,
            "connection_id_sha256": _sha("connection-current"),
            "repeat_oauth_allowed": False,
            "secret_exposed": False,
        }
        raw_evidence = {
            "status": "pending",
            "current_store_selected": True,
            "authorized": True,
            "strong_identity_ready": True,
            "backend_provenance_ready": True,
            "store_id_sha256": _sha(store["store_id"]),
            "connection_id_sha256": _sha("connection-current"),
            "refresh_success_ready": False,
            "refresh_same_connection_ready": False,
            "real_platform_writes_enabled": False,
            "secret_exposed": False,
            "raw_token": "REFRESH-PROOF-HTTP-SECRET-SENTINEL",
        }
        try:
            with patch.object(repository, "ebay_read_only_oauth_boundary", return_value=safe_boundary), patch.object(
                api_server,
                "build_current_store_ebay_refresh_evidence",
                return_value=raw_evidence,
            ):
                unauth_status, _ = _get_json(
                    base_url,
                    f"/stores/{store['store_id']}/ebay-oauth/read-only-status",
                )
                status, body = _get_json(
                    base_url,
                    f"/stores/{store['store_id']}/ebay-oauth/read-only-status",
                    token,
                )
            if unauth_status != 401 or status != 200:
                return fail(f"lightweight current-store proof must require auth and return 200: unauth={unauth_status} auth={status}")
            proof = body.get("ebay_refresh_proof") if isinstance(body, dict) else None
            if proof != {key: raw_evidence[key] for key in raw_evidence if key != "raw_token"}:
                return fail(f"lightweight current-store proof response must be exact and value-free: {body}")
            if "REFRESH-PROOF-HTTP-SECRET-SENTINEL" in json.dumps(body, ensure_ascii=False):
                return fail("lightweight current-store proof leaked an unapproved backend field")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    api = (ROOT / "jiejing_saas" / "api_server.py").read_text(encoding="utf-8")
    route_start = api.index('parts[3] == "refresh-now"')
    route_end = api.index('parts[3] == "probe-plan"', route_start)
    route = api[route_start:route_end]
    for marker, message in {
        '_require_permission(identity, "manage_connections")': "refresh proof must require manage_connections",
        'body.get("probe_type") == "merchant_visible_vault_refresh"': "refresh proof must require the exact explicit merchant intent",
        'set(body) != {"probe_type", "real_platform_writes_enabled", "secret_exposed"}': "refresh proof must reject extra request fields",
        "_resolve_merchant_visible_ebay_refresh_probe(": "refresh proof must resolve the exact boundary before the adapter",
        "_merchant_safe_ebay_refresh_probe_result(refresh)": "refresh proof must sanitize the adapter result",
        '"fresh_proof_reused": True': "fresh same-connection evidence must be idempotently reused",
    }.items():
        if marker not in route:
            return fail(message)
    if route.index("_resolve_merchant_visible_ebay_refresh_probe(") >= route.index("EbayVaultTokenRefreshAdapter(self.settings)"):
        return fail("exact current-store OAuth/Vault binding must be resolved before any provider refresh")
    response_tail = route[route.index("self._send_json(", route.index("audit =")) :]
    if '"audit": audit' in response_tail or '"vault":' in response_tail:
        return fail("merchant refresh response must not expose internal audit or Vault objects")

    app = (ROOT / "app.js").read_text(encoding="utf-8")
    try:
        start = app.index("async function verifySaasEbayCredentialProof()")
        end = app.index("async function syncSaasEbayReadOnlyData()", start)
    except ValueError:
        return fail("frontend must implement the explicit merchant credential-proof action")
    flow = app[start:end]
    required_markers = {
        'data-saas-action="verify-ebay-credential-proof"': "settings must expose the explicit merchant action",
        "/ebay-oauth/refresh-now": "the action must call the dedicated backend-only endpoint",
        "saasEbayRefreshProofAttemptKeys.has(attemptKey)": "the page must block a duplicate attempt",
        "saasEbayRefreshProofAttemptKeys.add(attemptKey)": "the attempt must be claimed before POST",
        "validatedSaasEbayRefreshProofResponse": "the response must pass a strict frontend contract",
        "refresh_success_ready === true": "the UI must use exact current-store refresh evidence",
        "/ebay-oauth/read-only-status": "the UI must use the lightweight current-store evidence endpoint",
        "saasEbayRefreshProofStatusStoreId": "the UI must bind refresh evidence to the store that was actually fetched",
        '"verify-ebay-credential-proof"': "the action must be protected by the authenticated-session guard",
        "验证 eBay 连接": "the merchant label must avoid KMS jargon",
        "不重新授权、不同步商品、不修改 eBay": "the UI must explain the zero-business-write boundary",
    }
    for marker, message in required_markers.items():
        if marker not in app:
            return fail(message)
    if flow.index("saasEbayRefreshProofAttemptKeys.add(attemptKey)") >= flow.index("/ebay-oauth/refresh-now"):
        return fail("the in-page refresh proof claim must happen before the backend POST")
    for forbidden in ("state.saasStores[0]", "localStorage", "sessionStorage"):
        if forbidden in flow:
            return fail(f"refresh proof flow must not use fallback/persistent sensitive state: {forbidden}")

    print("PASS jiejing_ebay_refresh_proof_ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
