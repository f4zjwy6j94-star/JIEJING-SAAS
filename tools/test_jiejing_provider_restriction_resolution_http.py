#!/usr/bin/env python3
"""HTTP regression for audited eBay provider-restriction resolution evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
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


def _post(
    base_url: str,
    payload: dict[str, Any],
    token: str,
    *,
    host: str = "ops.jiejing.shop",
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{base_url}/owner/ebay/provider-restriction-resolution",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Host": host,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), json.loads(raw) if raw else {}


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="jiejing-provider-restriction-resolution-",
        ignore_cleanup_errors=True,
    ) as tmp:
        root = Path(tmp)
        repository = SaaSRepository(root / "saas.sqlite")
        owner = repository.create_user_with_company(
            email="provider-resolution-owner@jiejing.local",
            password="provider-resolution-owner-password",
            company_name="Provider Resolution Owner",
        )
        company_id = owner["company"]["company_id"]
        user = owner["user"]
        store = repository.create_store(
            company_id=company_id,
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "provider-resolution-store", "marketplace": "EBAY_US"},
        )
        outsider = repository.create_user_with_company(
            email="provider-resolution-outsider@jiejing.local",
            password="provider-resolution-outsider-password",
            company_name="Provider Resolution Outsider",
        )["user"]
        settings = SaaSSettings.from_env(
            db_path=root / "saas.sqlite",
            runtime_db_path=root / "runtime.sqlite",
            output_root=root / "output",
            host="127.0.0.1",
            port=0,
        )
        settings.environment = "test"
        settings.internal_admin_emails = (user["email"].lower(),)
        sessions = SessionManager(secret="provider-restriction-resolution-http-session-secret")

        class TestHandler(SaaSBackendHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

        TestHandler.repository = repository
        TestHandler.settings = settings
        TestHandler.sessions = sessions
        server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        owner_token = sessions.create_token(user_id=user["user_id"], company_id=company_id, email=user["email"])
        outsider_token = sessions.create_token(
            user_id=outsider["user_id"],
            company_id=outsider["default_company_id"],
            email=outsider["email"],
        )
        evidence_sha256 = hashlib.sha256(b"sanitized-ebay-resolution-notice-fixture").hexdigest()
        body = {
            "company_id": company_id,
            "store_id": store["store_id"],
            "evidence_type": "ebay_message_resolution_notice",
            "verified_at": "2026-08-28T03:00:00+00:00",
            "restriction_error_id": "25019",
            "evidence_sha256": evidence_sha256,
            "exact_confirmation": (
                f"record_provider_restriction_resolution:{company_id}:{store['store_id']}:25019:{evidence_sha256}"
            ),
        }
        try:
            status, _response = _post(base_url, body, owner_token, host="app.jiejing.shop")
            if status != 403:
                raise AssertionError(f"resolution evidence route must remain isolated to ops host: {status}")
            status, _response = _post(base_url, body, outsider_token)
            if status != 403:
                raise AssertionError(f"non-admin identity must not record restriction resolution: {status}")
            status, _response = _post(base_url, {**body, "evidence_sha256": "invalid"}, owner_token)
            if status != 400:
                raise AssertionError(f"invalid evidence digest must be rejected: {status}")
            status, _response = _post(base_url, {**body, "exact_confirmation": "wrong"}, owner_token)
            if status != 409:
                raise AssertionError(f"mismatched exact confirmation must be rejected: {status}")
            status, response = _post(base_url, body, owner_token)
            if status != 201:
                raise AssertionError(f"trusted restriction resolution should be recorded: {status} {response}")
            resolution = response.get("provider_restriction_resolution") or {}
            if resolution.get("recorded") is not True or resolution.get("raw_evidence_stored") is not False:
                raise AssertionError(f"resolution response lost its evidence boundary: {response}")
            audit = repository.find_latest_audit_log_by_target(
                company_id=company_id,
                store_id=store["store_id"],
                action_type="ebay.provider_restriction.resolution_verified",
                target_type="store",
                target_id=store["store_id"],
            )
            details = audit.get("details") if isinstance(audit, dict) else {}
            if audit.get("actor_type") != "platform_internal_admin" or details.get("evidence_sha256") != evidence_sha256:
                raise AssertionError(f"trusted audit evidence was not persisted correctly: {audit}")
            status, duplicate = _post(base_url, body, owner_token)
            if status != 200 or (duplicate.get("provider_restriction_resolution") or {}).get("duplicate_request") is not True:
                raise AssertionError(f"duplicate evidence must be idempotent: {status} {duplicate}")
            serialized = json.dumps({"response": response, "audit": audit}, ensure_ascii=False).lower()
            for forbidden in ("bearer ", "password", "refresh_token", "access_token", "cookie"):
                if forbidden in serialized:
                    raise AssertionError(f"resolution evidence leaked forbidden marker: {forbidden}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("PASS jiejing_provider_restriction_resolution_http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
