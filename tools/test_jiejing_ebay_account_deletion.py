#!/usr/bin/env python3
"""Behavior regression for eBay marketplace account deletion compliance."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.ebay_account_deletion import (  # noqa: E402
    AccountDeletionError,
    EbayNotificationSignatureVerifier,
    build_challenge_response,
    fetch_ebay_identity_hashes,
    normalize_notification,
    verify_notification_signature,
)
from jiejing_saas.repository import SaaSRepository  # noqa: E402
from jiejing_saas.api_server import SaaSBackendHandler  # noqa: E402
from jiejing_saas.config import SaaSSettings  # noqa: E402
from jiejing_saas.worker import LocalQueueWorker  # noqa: E402


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def main() -> int:
    challenge = "challenge-unit-123"
    verification_token = "unit_verification_token_1234567890"
    endpoint = "https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion"
    expected = hashlib.sha256(f"{challenge}{verification_token}{endpoint}".encode("utf-8")).hexdigest()
    result = build_challenge_response(
        challenge_code=challenge,
        verification_token=verification_token,
        endpoint_url=endpoint,
    )
    if result != {"challengeResponse": expected}:
        return fail(f"challenge response did not match eBay algorithm: {json.dumps(result)}")
    serialized = json.dumps(result, ensure_ascii=False)
    if verification_token in serialized or challenge in serialized:
        return fail("challenge response leaked input material")
    nginx_proxy = (ROOT / "deploy" / "nginx.public-staging.conf").read_text(encoding="utf-8")
    production_proxy = (ROOT / "deploy" / "Caddyfile.production").read_text(encoding="utf-8")
    if "|webhooks)" not in nginx_proxy:
        return fail("public staging proxy does not route webhook requests to the backend")
    if "/webhooks/*" not in production_proxy:
        return fail("production proxy does not route webhook requests to the backend")
    for field_name, kwargs, expected_code in (
        (
            "missing verification token",
            {"challenge_code": challenge, "verification_token": "", "endpoint_url": endpoint},
            "configuration_unavailable",
        ),
        (
            "invalid verification token",
            {"challenge_code": challenge, "verification_token": "too short", "endpoint_url": endpoint},
            "configuration_unavailable",
        ),
        (
            "missing challenge",
            {"challenge_code": "", "verification_token": verification_token, "endpoint_url": endpoint},
            "invalid_challenge",
        ),
        (
            "oversized challenge",
            {"challenge_code": "x" * 257, "verification_token": verification_token, "endpoint_url": endpoint},
            "invalid_challenge",
        ),
        (
            "non-https endpoint",
            {"challenge_code": challenge, "verification_token": verification_token, "endpoint_url": "http://example.test/webhook"},
            "configuration_unavailable",
        ),
    ):
        try:
            build_challenge_response(**kwargs)
        except AccountDeletionError as exc:
            if exc.code != expected_code:
                return fail(f"{field_name} returned wrong error code: {exc.code}")
        else:
            return fail(f"{field_name} should fail closed")

    payload = {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION", "schemaVersion": "1.0", "deprecated": False},
        "notification": {
            "notificationId": "notification-unit-001",
            "eventDate": "2026-07-13T01:02:03.000Z",
            "publishDate": "2026-07-13T01:02:04.000Z",
            "publishAttemptCount": 1,
            "data": {
                "username": "merchant-private-name",
                "userId": "immutable-ebay-user-001",
                "eiasToken": "legacy-private-token-001",
            },
        },
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    normalized = normalize_notification(raw_body=raw_body, signature_header="signature-unit")
    if normalized.get("topic") != "MARKETPLACE_ACCOUNT_DELETION" or normalized.get("schema_version") != "1.0":
        return fail(f"valid deletion payload was not normalized: {normalized}")
    if normalized.get("publish_attempt_count") != 1 or not normalized.get("event_key"):
        return fail("normalized notification is missing bounded delivery metadata")
    if not all(normalized.get(key) for key in ("user_id_hash", "username_hash", "eias_identity_hash", "payload_sha256")):
        return fail("normalized notification should retain only hashed identity selectors")
    serialized = json.dumps(normalized, ensure_ascii=False)
    for forbidden in ("merchant-private-name", "immutable-ebay-user-001", "legacy-private-token-001", "signature-unit"):
        if forbidden in serialized:
            return fail(f"normalized notification leaked raw private input: {forbidden}")

    invalid_payloads = (
        ({**payload, "metadata": {**payload["metadata"], "topic": "OTHER_TOPIC"}}, "unsupported_topic"),
        ({**payload, "notification": {**payload["notification"], "notificationId": ""}}, "invalid_notification"),
        ({**payload, "notification": {**payload["notification"], "data": {}}}, "invalid_notification"),
    )
    for invalid_payload, expected_code in invalid_payloads:
        try:
            normalize_notification(
                raw_body=json.dumps(invalid_payload, separators=(",", ":")).encode("utf-8"),
                signature_header="signature-unit",
            )
        except AccountDeletionError as exc:
            if exc.code != expected_code:
                return fail(f"invalid payload returned wrong error code: {exc.code}")
        else:
            return fail("invalid notification payload should fail closed")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    signature = private_key.sign(raw_body, padding.PKCS1v15(), hashes.SHA1())
    signature_header = base64.b64encode(
        json.dumps(
            {"kid": "public-key-unit-001", "signature": base64.b64encode(signature).decode("ascii")},
            separators=(",", ":"),
        ).encode("ascii")
    ).decode("ascii")
    verification = verify_notification_signature(
        raw_body=raw_body,
        signature_header=signature_header,
        public_key_pem=public_key_pem,
    )
    if verification.get("verified") is not True or verification.get("key_id") != "public-key-unit-001":
        return fail(f"valid official-format signature should verify: {verification}")
    tampered_payload = json.loads(raw_body)
    tampered_payload["notification"]["data"]["userId"] = "different-ebay-user"
    tampered_verification = verify_notification_signature(
        raw_body=json.dumps(tampered_payload, separators=(",", ":")).encode("utf-8"),
        signature_header=signature_header,
        public_key_pem=public_key_pem,
    )
    if tampered_verification.get("verified") is not False:
        return fail("tampered notification body should fail signature verification")
    transport_calls: list[str] = []

    def fake_transport(request, timeout):
        transport_calls.append(request.full_url)
        if request.full_url.endswith("/identity/v1/oauth2/token"):
            return 200, {"content-type": "application/json"}, json.dumps({"access_token": "private-app-token"}).encode("utf-8")
        if request.full_url.endswith("/commerce/notification/v1/public_key/public-key-unit-001"):
            if request.get_header("Authorization") != "Bearer private-app-token":
                raise AssertionError("public key request should use backend application token")
            return 200, {"content-type": "application/json"}, json.dumps({"key": public_key_pem}).encode("utf-8")
        raise AssertionError(f"unexpected verifier URL: {request.full_url}")

    live_verifier = EbayNotificationSignatureVerifier(
        environment="production",
        client_id="client-id-unit",
        client_secret="client-secret-unit",
        transport=fake_transport,
    )
    live_result = live_verifier.verify(raw_body=raw_body, signature_header=signature_header)
    cached_result = live_verifier.verify(raw_body=raw_body, signature_header=signature_header)
    if live_result.get("verified") is not True or cached_result.get("verified") is not True:
        return fail(f"live verifier boundary did not verify official-format signature: {live_result}")
    if len(transport_calls) != 2:
        return fail("public key should be cached instead of fetched for every notification")
    live_serialized = json.dumps(live_result, ensure_ascii=False)
    for forbidden in ("client-secret-unit", "private-app-token", public_key_pem):
        if forbidden in live_serialized:
            return fail("signature verifier leaked backend credential material")

    identity_calls: list[str] = []

    def identity_transport(request, timeout):
        identity_calls.append(request.full_url)
        if request.get_header("Authorization") != "Bearer transient-user-token":
            raise AssertionError("identity read should use only the transient backend access token")
        return 200, {"content-type": "application/json"}, json.dumps(
            {
                "userId": "immutable-ebay-user-identity-test",
                "username": "private-seller-name-identity-test",
                "registrationMarketplaceId": "EBAY_US",
                "accountType": "INDIVIDUAL",
                "status": "CONFIRMED",
                "individualAccount": {"email": "must-not-be-retained@example.test"},
            }
        ).encode("utf-8")

    identity = fetch_ebay_identity_hashes(
        access_token="transient-user-token",
        environment="production",
        transport=identity_transport,
    )
    if identity.get("status") != "identity_mapping_ready" or not identity.get("ebay_user_id_hash"):
        return fail(f"OAuth identity should produce an immutable hash selector: {identity}")
    if identity_calls != ["https://apiz.ebay.com/commerce/identity/v1/user/"]:
        return fail(f"identity resolver used an unexpected endpoint: {identity_calls}")
    identity_serialized = json.dumps(identity, ensure_ascii=False)
    for forbidden in (
        "transient-user-token",
        "immutable-ebay-user-identity-test",
        "private-seller-name-identity-test",
        "must-not-be-retained@example.test",
    ):
        if forbidden in identity_serialized:
            return fail(f"identity resolver leaked raw seller material: {forbidden}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        repository = SaaSRepository(Path(temp_dir) / "account-deletion.sqlite", database_engine="sqlite", database_url="")
        private_env = Path(temp_dir) / "private.env"
        env_secret = "private_env_verification_token_123456"
        upsert = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_upsert_private_env_secret.py"),
                str(private_env),
                "JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN",
            ],
            input=env_secret,
            capture_output=True,
            text=True,
            check=False,
        )
        if upsert.returncode != 0 or upsert.stdout or upsert.stderr:
            return fail("private env secret upsert should succeed without printing secret material")
        if private_env.read_text(encoding="utf-8").strip() != f"JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN={env_secret}":
            return fail("private env secret upsert did not write the intended backend-only key")
        account = repository.create_user_with_company(
            email="account-deletion-owner@example.test",
            password="account-deletion-password",
            company_name="Account Deletion Test Company",
        )
        user = account["user"]
        store = repository.create_store(
            company_id=user["default_company_id"],
            user_id=user["user_id"],
            payload={"platform": "ebay", "store_name": "Private Seller Store", "marketplace": "EBAY_US"},
        )
        connection = repository.create_platform_connection(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            payload={
                "platform": "ebay",
                "status": "read_only_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope"],
                "metadata": {
                    "ebay_user_id_hash": normalized["user_id_hash"],
                    "ebay_username_hash": normalized["username_hash"],
                    "ebay_eias_identity_hash": normalized["eias_identity_hash"],
                },
            },
        )
        duplicate_connection = repository.create_platform_connection(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            payload={
                "platform": "ebay",
                "status": "read_only_authorized",
                "scopes": ["https://api.ebay.com/oauth/api_scope"],
                "metadata": {
                    "ebay_user_id_hash": normalized["user_id_hash"],
                    "ebay_username_hash": normalized["username_hash"],
                },
            },
        )
        public_connection = json.dumps(connection, ensure_ascii=False)
        if any(key in public_connection for key in ("ebay_user_id_hash", "ebay_username_hash", "ebay_eias_identity_hash")):
            return fail("public connection response should not expose internal identity selectors")
        first = repository.accept_ebay_account_deletion_event(event=normalized)
        duplicate = repository.accept_ebay_account_deletion_event(event=normalized)
        if first.get("status") != "queued" or first.get("connection_id") not in {
            connection["connection_id"], duplicate_connection["connection_id"]
        }:
            return fail(f"mapped notification should create a compliance job: {first}")
        if duplicate.get("duplicate") is not True or duplicate.get("job_id") != first.get("job_id"):
            return fail(f"duplicate notification should reuse one durable job: {duplicate}")
        if repository.ebay_account_deletion_event_count() != 1:
            return fail("duplicate delivery created more than one event")
        claimed = repository.claim_next_queue_job(
            company_id=user["default_company_id"],
            job_id=first["job_id"],
        )
        if not claimed:
            return fail("account deletion compliance job should be claimable")
        original_process = repository.process_ebay_account_deletion_event

        def temporary_failure(**kwargs):
            raise RuntimeError("temporary deletion dependency failure")

        repository.process_ebay_account_deletion_event = temporary_failure  # type: ignore[method-assign]
        try:
            retry_result = LocalQueueWorker(
                repository=repository,
                runtime_bridge=object(),  # type: ignore[arg-type]
            ).run_claimed_job(claimed)
        finally:
            repository.process_ebay_account_deletion_event = original_process  # type: ignore[method-assign]
        if retry_result.get("status") != "retrying":
            return fail(f"temporary compliance failure should schedule a durable retry: {retry_result}")
        retry_job = repository.get_queue_job(company_id=user["default_company_id"], job_id=first["job_id"])
        if not retry_job or retry_job.get("status") != "queued" or retry_job.get("attempts") != 1:
            return fail(f"account deletion retry should preserve attempt accounting: {retry_job}")
        tampered = {**normalized, "payload_sha256": "f" * 64}
        conflict = repository.accept_ebay_account_deletion_event(event=tampered)
        if conflict.get("status") != "idempotency_conflict":
            return fail("same notification id with a different payload should be quarantined")

        other_store = repository.create_store(
            company_id=user["default_company_id"],
            user_id=user["user_id"],
            payload={"platform": "shopify", "store_name": "Unaffected Store", "marketplace": "US"},
        )
        repository.create_platform_data_packet(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            packet={"platform": "ebay", "packet_type": "seller_private", "source_mode": "test", "private_note": "delete-me"},
        )
        repository.create_platform_data_packet(
            company_id=user["default_company_id"],
            store_id=other_store["store_id"],
            user_id=user["user_id"],
            packet={"platform": "shopify", "packet_type": "catalog", "source_mode": "test", "private_note": "keep-me"},
        )
        repository.create_task(
            company_id=user["default_company_id"],
            store_id=store["store_id"],
            user_id=user["user_id"],
            task_type="ebay_market_research",
            title="Delete this eBay task",
            input_data={"seller_data": "delete-me"},
        )
        repository.create_task(
            company_id=user["default_company_id"],
            store_id=other_store["store_id"],
            user_id=user["user_id"],
            task_type="shopify_catalog",
            title="Keep this other store task",
            input_data={"catalog_data": "keep-me"},
        )
        retry_claim = repository.claim_next_queue_job(
            company_id=user["default_company_id"],
            job_id=first["job_id"],
        )
        if not retry_claim:
            return fail("retried account deletion job should remain claimable")
        completed_worker_result = LocalQueueWorker(
            repository=repository,
            runtime_bridge=object(),  # type: ignore[arg-type]
        ).run_claimed_job(retry_claim)
        if completed_worker_result.get("status") != "completed":
            return fail(f"retried account deletion job should complete through the worker: {completed_worker_result}")
        processed = completed_worker_result.get("account_deletion") or {}
        if processed.get("status") != "completed" or processed.get("real_platform_write_performed") is not False:
            return fail(f"mapped account deletion should complete without an eBay write: {processed}")
        ebay_packets = repository.list_platform_data_packets(company_id=user["default_company_id"], store_id=store["store_id"])
        other_packets = repository.list_platform_data_packets(company_id=user["default_company_id"], store_id=other_store["store_id"])
        if ebay_packets or len(other_packets) != 1:
            return fail("account deletion should purge only the matched eBay store packets")
        other_tasks = repository.list_tasks(company_id=user["default_company_id"], store_id=other_store["store_id"])
        if len(other_tasks) != 1:
            return fail("account deletion should not touch tasks from another store")
        connection_after = next(
            item for item in repository.list_connections(company_id=user["default_company_id"], store_id=store["store_id"])
            if item["connection_id"] == connection["connection_id"]
        )
        if connection_after.get("status") != "revoked_account_deleted" or connection_after.get("scopes"):
            return fail("deleted eBay account connection should be revoked and lose scopes")
        duplicate_after = next(
            item for item in repository.list_connections(company_id=user["default_company_id"], store_id=store["store_id"])
            if item["connection_id"] == duplicate_connection["connection_id"]
        )
        if duplicate_after.get("status") != "revoked_account_deleted" or duplicate_after.get("scopes"):
            return fail("re-authorized eBay connection on the same store should also be revoked")

        unknown = {
            **normalized,
            "event_key": "a" * 64,
            "notification_id_hash": "a" * 64,
            "user_id_hash": "b" * 64,
            "username_hash": "c" * 64,
            "eias_identity_hash": "d" * 64,
        }
        no_match = repository.accept_ebay_account_deletion_event(event=unknown)
        if no_match.get("status") != "completed_no_matching_connection" or no_match.get("job_id"):
            return fail(f"unknown eBay identity should not enqueue a destructive task: {no_match}")

        endpoint_token = "portal_verification_token_unit_123456"
        previous_token = os.environ.get("JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN")
        previous_endpoint = os.environ.get("JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL")
        port = _free_port()
        endpoint_url = f"https://app.jiejing.shop/webhooks/ebay/marketplace-account-deletion"
        os.environ["JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN"] = endpoint_token
        os.environ["JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL"] = endpoint_url
        settings = SaaSSettings.from_env(
            db_path=Path(temp_dir) / "account-deletion.sqlite",
            runtime_db_path=Path(temp_dir) / "runtime.sqlite",
            output_root=Path(temp_dir) / "output",
            host="127.0.0.1",
            port=port,
        )

        class AcceptingVerifier:
            def verify(self, *, raw_body, signature_header):
                return {"verified": True, "status": "verified", "secret_exposed": False}

        class TestHandler(SaaSBackendHandler):
            pass

        TestHandler.repository = repository
        TestHandler.settings = settings
        TestHandler.ebay_account_deletion_signature_verifier = AcceptingVerifier()
        server = ThreadingHTTPServer(("127.0.0.1", port), TestHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            challenge_code = "http-route-challenge"
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/webhooks/ebay/marketplace-account-deletion?challenge_code={challenge_code}",
                timeout=5,
            ) as response:
                challenge_body = json.loads(response.read().decode("utf-8"))
            expected_http_hash = hashlib.sha256(f"{challenge_code}{endpoint_token}{endpoint_url}".encode("utf-8")).hexdigest()
            if challenge_body != {"challengeResponse": expected_http_hash}:
                return fail(f"public challenge route returned wrong response: {challenge_body}")

            http_payload = json.loads(raw_body)
            http_payload["notification"]["notificationId"] = "notification-http-002"
            http_raw = json.dumps(http_payload, separators=(",", ":")).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhooks/ebay/marketplace-account-deletion",
                data=http_raw,
                headers={"Content-Type": "application/json", "X-EBAY-SIGNATURE": "signature-unit"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                accepted_status = response.status
                accepted_body = json.loads(response.read().decode("utf-8"))
            if accepted_status != 202 or accepted_body.get("accepted") is not True:
                return fail(f"verified public notification should return 202: {accepted_body}")
            bad_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/webhooks/ebay/marketplace-account-deletion",
                data=http_raw,
                headers={"Content-Type": "text/plain", "X-EBAY-SIGNATURE": "signature-unit"},
                method="POST",
            )
            try:
                urllib.request.urlopen(bad_request, timeout=5)
            except urllib.error.HTTPError as exc:
                if exc.code != 415:
                    return fail(f"wrong webhook content type should return 415, got {exc.code}")
            else:
                return fail("wrong webhook content type should be rejected")
            malformed_response = _raw_http_request(
                port,
                (
                    "POST /webhooks/ebay/marketplace-account-deletion HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{port}\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: not-a-number\r\n"
                    "X-EBAY-SIGNATURE: signature-unit\r\n"
                    "Connection: close\r\n\r\n{}"
                ).encode("ascii"),
            )
            if b" 400 " not in malformed_response.split(b"\r\n", 1)[0]:
                return fail("nonnumeric account deletion Content-Length should return 400")
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
            if previous_token is None:
                os.environ.pop("JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN", None)
            else:
                os.environ["JIEJING_EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN"] = previous_token
            if previous_endpoint is None:
                os.environ.pop("JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL", None)
            else:
                os.environ["JIEJING_EBAY_ACCOUNT_DELETION_ENDPOINT_URL"] = previous_endpoint
    print("PASS jiejing_ebay_account_deletion")
    return 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _raw_http_request(port: int, payload: bytes) -> bytes:
    chunks: list[bytes] = []
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(payload)
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


if __name__ == "__main__":
    raise SystemExit(main())
