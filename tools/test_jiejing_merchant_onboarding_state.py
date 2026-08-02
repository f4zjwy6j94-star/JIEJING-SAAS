#!/usr/bin/env python3
"""Behavior tests for the durable, evidence-led new seller onboarding flow."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jiejing_saas.merchant_onboarding import (
    MerchantOnboardingValidationError,
    MerchantOnboardingVersionConflict,
    build_merchant_onboarding_read_model,
    normalize_merchant_onboarding_progress,
)
from jiejing_saas.repository import SaaSRepository


def fail(message: str) -> int:
    print(f"FAIL {message}")
    return 1


def _authorized_connection() -> list[dict[str, object]]:
    return [
        {
            "connection_id": "connection_current",
            "store_id": "store_current",
            "platform": "ebay",
            "status": "read_only_authorized",
        }
    ]


def _health(
    *,
    status: str = "normal",
    onboarding_stage: str = "ready_for_publish_preflight",
    packet_present: bool = True,
    policies_present: bool = True,
) -> dict[str, object]:
    return {
        "status": status,
        "onboarding_stage": onboarding_stage,
        "incident_mode": status in {"unknown", "restricted", "suspended", "payout_hold", "quota_limited"},
        "evidence_package": {
            "official_packet_present": packet_present,
            "business_policies_present": policies_present,
        },
        "secret_exposed": False,
    }


def main() -> int:
    default = build_merchant_onboarding_read_model()
    if default.get("effective_stage") != "seller_registration_required":
        return fail(f"new seller default should start at official registration: {default}")
    if default.get("verified") is not False or default.get("triggers_real_platform_write") is not False:
        return fail(f"default onboarding must not claim verification or trigger writes: {default}")

    returned = normalize_merchant_onboarding_progress(
        {
            "path_key": "newbie",
            "current_step_key": "ebayStage",
            "work_mode": "guided",
            "seller_returned": True,
            "answers": {"ebayStage": "choice_0"},
            "completed_step_keys": ["ebayStage"],
        }
    )
    returned_model = build_merchant_onboarding_read_model(progress=returned)
    if returned_model.get("effective_stage") != "authorization_required":
        return fail(f"returned merchant without a connection should be guided to authorization: {returned_model}")
    if returned_model.get("seller_registration_verified") is not False:
        return fail(f"returning from eBay must not claim registration verification: {returned_model}")

    needs_snapshot = build_merchant_onboarding_read_model(
        progress=returned,
        connections=_authorized_connection(),
    )
    if needs_snapshot.get("effective_stage") != "read_only_check_required":
        return fail(f"authorized connection without account evidence should request a read-only check: {needs_snapshot}")
    if needs_snapshot.get("oauth_required") is not False:
        return fail(f"authorized connection must suppress repeat OAuth: {needs_snapshot}")

    registration_incomplete = build_merchant_onboarding_read_model(
        progress=returned,
        connections=_authorized_connection(),
        account_health=_health(
            status="registration_incomplete",
            onboarding_stage="seller_registration_required",
            policies_present=False,
        ),
    )
    if registration_incomplete.get("effective_stage") != "seller_registration_required":
        return fail(f"official incomplete registration must override merchant intent: {registration_incomplete}")
    if registration_incomplete.get("oauth_required") is not False:
        return fail(f"registration repair must retain the current connection without OAuth: {registration_incomplete}")

    restricted = build_merchant_onboarding_read_model(
        progress=returned,
        connections=_authorized_connection(),
        account_health=_health(
            status="restricted",
            onboarding_stage="account_review_required",
            policies_present=False,
        ),
    )
    if restricted.get("effective_stage") != "account_review_required":
        return fail(f"restricted account should enter the safe review state: {restricted}")

    policies_missing = build_merchant_onboarding_read_model(
        progress=returned,
        connections=_authorized_connection(),
        account_health=_health(
            onboarding_stage="business_policies_required",
            policies_present=False,
        ),
    )
    if policies_missing.get("effective_stage") != "business_policies_required":
        return fail(f"missing one or more policies must block publish preflight: {policies_missing}")
    if policies_missing.get("publish_preflight_available") is not False:
        return fail(f"policy gap must not expose publish-preflight readiness: {policies_missing}")

    ready = build_merchant_onboarding_read_model(
        progress=returned,
        connections=_authorized_connection(),
        account_health=_health(),
    )
    if ready.get("effective_stage") != "ready_for_publish_preflight":
        return fail(f"complete read-only evidence should allow publish preflight only: {ready}")
    if ready.get("publish_preflight_available") is not True or ready.get("real_publish_allowed") is not False:
        return fail(f"ready onboarding must still stop before real publish: {ready}")

    draft = normalize_merchant_onboarding_progress(
        {
            "path_key": "newbie",
            "current_step_key": "businessPolicy",
            "work_mode": "draft_only",
            "seller_returned": False,
            "answers": {
                "ebayStage": "choice_0",
                "businessPolicy": "choice_2",
                "serviceBoundary": "choice_1",
            },
            "completed_step_keys": ["ebayStage", "businessPolicy"],
        }
    )
    if draft.get("work_mode") != "draft_only" or draft.get("preferences_saved") is not True:
        return fail(f"draft-only preference should be saved without readiness inflation: {draft}")

    invalid_cases = [
        {"path_key": "amazon"},
        {"current_step_key": "unknownStep"},
        {"work_mode": "auto_publish"},
        {"answers": {"refresh_token": "choice_0"}},
        {"answers": {"ebayStage": "javascript:alert(1)"}},
        {"answers": {"ebayStage": "choice_99"}},
        {"completed_step_keys": ["password"]},
    ]
    for value in invalid_cases:
        try:
            normalize_merchant_onboarding_progress(value)
        except MerchantOnboardingValidationError:
            continue
        return fail(f"unsafe or unsupported onboarding input was accepted: {value}")

    serialized = json.dumps(
        {
            "default": default,
            "returned": returned_model,
            "needs_snapshot": needs_snapshot,
            "registration_incomplete": registration_incomplete,
            "restricted": restricted,
            "policies_missing": policies_missing,
            "ready": ready,
            "draft": draft,
        },
        ensure_ascii=False,
    ).lower()
    for forbidden in ("access_token", "refresh_token", "client_secret", "oauth_code", "password"):
        if forbidden in serialized:
            return fail(f"onboarding read model leaked a forbidden field: {forbidden}")

    repository_error = _test_repository_behavior()
    if repository_error:
        return fail(repository_error)
    health_retry_error = _test_health_wait_retry_behavior()
    if health_retry_error:
        return fail(health_retry_error)
    api_error = _test_http_behavior()
    if api_error:
        return fail(api_error)

    print("PASS jiejing_merchant_onboarding_state")
    return 0


def _test_repository_behavior() -> str:
    with tempfile.TemporaryDirectory(prefix="jiejing-onboarding-", ignore_cleanup_errors=True) as directory:
        repository = SaaSRepository(Path(directory) / "saas.sqlite")
        first = repository.create_user_with_company(
            email="onboarding-first@example.test",
            password="Onboarding-test-password-2026",
            company_name="First Onboarding Company",
        )
        second = repository.create_user_with_company(
            email="onboarding-second@example.test",
            password="Onboarding-test-password-2026",
            company_name="Second Onboarding Company",
        )
        first_company_id = str(first["company"]["company_id"])
        first_user_id = str(first["user"]["user_id"])
        second_company_id = str(second["company"]["company_id"])

        if repository.get_merchant_onboarding_state(company_id=first_company_id) is not None:
            return "new company should not invent a persisted onboarding record"
        saved = repository.upsert_merchant_onboarding_state(
            company_id=first_company_id,
            user_id=first_user_id,
            progress={
                "path_key": "newbie",
                "current_step_key": "ebayStage",
                "work_mode": "guided",
                "seller_returned": False,
                "answers": {"ebayStage": "choice_0"},
                "completed_step_keys": ["ebayStage"],
            },
            expected_version=0,
        )
        if saved.get("version") != 1 or saved.get("store_id"):
            return f"company-level onboarding should persist before a store exists: {saved}"
        if repository.get_merchant_onboarding_state(company_id=second_company_id) is not None:
            return "onboarding progress crossed the company boundary"

        updated = repository.upsert_merchant_onboarding_state(
            company_id=first_company_id,
            user_id=first_user_id,
            progress={
                "path_key": "newbie",
                "current_step_key": "businessPolicy",
                "work_mode": "draft_only",
                "seller_returned": True,
                "answers": {"ebayStage": "choice_0", "businessPolicy": "choice_2"},
                "completed_step_keys": ["ebayStage", "businessPolicy"],
            },
            expected_version=1,
        )
        if updated.get("version") != 2 or updated.get("work_mode") != "draft_only":
            return f"onboarding update did not advance the optimistic version: {updated}"

        try:
            repository.upsert_merchant_onboarding_state(
                company_id=first_company_id,
                user_id=first_user_id,
                progress={"work_mode": "guided"},
                expected_version=1,
            )
        except MerchantOnboardingVersionConflict as exc:
            if exc.latest.get("version") != 2:
                return f"version conflict did not return the current safe record: {exc.latest}"
        else:
            return "stale onboarding update overwrote a newer version"

        current = repository.get_merchant_onboarding_state(company_id=first_company_id) or {}
        if current.get("version") != 2 or current.get("work_mode") != "draft_only":
            return f"stale update changed the persisted onboarding record: {current}"
        audits = repository.list_audit_logs(company_id=first_company_id, limit=20)
        audit_text = json.dumps(audits, ensure_ascii=False).lower()
        for forbidden in ("choice_0", "choice_2", "onboarding-test-password", "seller_returned\": true"):
            if forbidden in audit_text:
                return f"onboarding audit persisted raw answers or sensitive input: {forbidden}"
    return ""


def _test_health_wait_retry_behavior() -> str:
    original_request_json = globals()["_request_json"]
    attempts = 0

    def transient_request_json(url: str, **_: object) -> tuple[int, dict[str, object]]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return 200, {"status": "ok"}

    globals()["_request_json"] = transient_request_json
    try:
        if not _wait_for_health("http://127.0.0.1:1"):
            return "health wait did not recover from a transient connection refusal"
    except urllib.error.URLError:
        return "health wait leaked a transient connection refusal"
    finally:
        globals()["_request_json"] = original_request_json
    if attempts != 2:
        return f"health wait should recover on the second attempt, got {attempts} attempts"
    return ""


def _test_http_behavior() -> str:
    with tempfile.TemporaryDirectory(prefix="jiejing-onboarding-http-", ignore_cleanup_errors=True) as directory:
        port = _free_port()
        env = dict(os.environ)
        env.update(
            {
                "JIEJING_SAAS_ENV": "test",
                "JIEJING_PLATFORM_TRIAL_ACTIVATION_REQUIRED": "false",
                "JIEJING_TURNSTILE_OR_CHALLENGE_ENABLED": "false",
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools" / "jiejing_saas_backend_cli.py"),
                "serve",
                "--db",
                str(Path(directory) / "saas.sqlite"),
                "--runtime-db",
                str(Path(directory) / "runtime.sqlite"),
                "--output-root",
                directory,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            base_url = f"http://127.0.0.1:{port}"
            if not _wait_for_health(base_url):
                stderr = process.stderr.read() if process.stderr else ""
                return f"onboarding test backend did not become healthy: {stderr[-800:]}"

            unauth_status, _ = _request_json(f"{base_url}/merchant-onboarding/primary-ebay")
            if unauth_status != 401:
                return f"unauthenticated onboarding read should return 401, got {unauth_status}"

            first = _register(base_url, "onboarding-http-first@example.test")
            second = _register(base_url, "onboarding-http-second@example.test")
            first_token = str(first.get("token") or "")
            second_token = str(second.get("token") or "")
            status, initial = _request_json(
                f"{base_url}/merchant-onboarding/primary-ebay",
                token=first_token,
            )
            initial_model = initial.get("merchant_onboarding") if isinstance(initial.get("merchant_onboarding"), dict) else {}
            if status != 200 or initial_model.get("effective_stage") != "seller_registration_required":
                return f"authenticated new company should receive a safe default read model: {status} {initial}"
            if initial_model.get("progress", {}).get("version", 0) != 0:
                return f"read-only default must not invent a persisted version: {initial_model}"

            status, saved = _request_json(
                f"{base_url}/merchant-onboarding/primary-ebay/progress",
                method="POST",
                token=first_token,
                body={
                    "path_key": "newbie",
                    "current_step_key": "ebayStage",
                    "work_mode": "draft_only",
                    "seller_returned": True,
                    "answers": {"ebayStage": "choice_0"},
                    "completed_step_keys": ["ebayStage"],
                    "expected_version": 0,
                    "effective_stage": "ready_for_publish_preflight",
                    "verified": True,
                    "connection_current": True,
                },
            )
            saved_model = saved.get("merchant_onboarding") if isinstance(saved.get("merchant_onboarding"), dict) else {}
            if status != 200 or saved_model.get("effective_stage") != "authorization_required":
                return f"saved merchant intent must not override backend-derived stage: {status} {saved}"
            if saved_model.get("progress", {}).get("version") != 1 or saved_model.get("verified") is not False:
                return f"saved progress should advance once without accepting forged truth: {saved_model}"

            other_status, other = _request_json(
                f"{base_url}/merchant-onboarding/primary-ebay",
                token=second_token,
            )
            other_model = other.get("merchant_onboarding") if isinstance(other.get("merchant_onboarding"), dict) else {}
            if other_status != 200 or other_model.get("progress", {}).get("version", 0) != 0:
                return f"second company observed the first company's onboarding progress: {other_status} {other}"

            conflict_status, conflict = _request_json(
                f"{base_url}/merchant-onboarding/primary-ebay/progress",
                method="POST",
                token=first_token,
                body={
                    "path_key": "newbie",
                    "current_step_key": "ebayStage",
                    "work_mode": "guided",
                    "seller_returned": False,
                    "answers": {"ebayStage": "choice_0"},
                    "completed_step_keys": ["ebayStage"],
                    "expected_version": 0,
                },
            )
            latest = conflict.get("merchant_onboarding") if isinstance(conflict.get("merchant_onboarding"), dict) else {}
            if conflict_status != 409 or latest.get("progress", {}).get("version") != 1:
                return f"stale HTTP update should return 409 with the latest safe state: {conflict_status} {conflict}"

            invalid_status, _ = _request_json(
                f"{base_url}/merchant-onboarding/primary-ebay/progress",
                method="POST",
                token=first_token,
                body={"answers": {"refresh_token": "choice_0"}, "expected_version": 1},
            )
            if invalid_status != 400:
                return f"unsafe onboarding input should return 400, got {invalid_status}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return ""


def _register(base_url: str, email: str) -> dict[str, object]:
    status, body = _request_json(
        f"{base_url}/auth/register",
        method="POST",
        body={
            "email": email,
            "password": "Onboarding-http-test-2026",
            "company_name": "Onboarding HTTP Test",
        },
    )
    if status != 201:
        raise RuntimeError(f"test registration failed with HTTP {status}")
    return body


def _request_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    headers = {"Accept": "application/json", "User-Agent": "JiejingOnboardingTest/1.0"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return int(exc.code), parsed


def _wait_for_health(base_url: str) -> bool:
    for _ in range(100):
        try:
            status, body = _request_json(f"{base_url}/health")
        except urllib.error.URLError:
            time.sleep(0.1)
            continue
        if status == 200 and body.get("status") == "ok":
            return True
        time.sleep(0.1)
    return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
